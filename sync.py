#!/usr/bin/env python3
"""Sync UCI regulation PDFs into a change-controlled Markdown tree.

One pass:
  1. Fetch the regulations page and extract every PDF URL (Contentful CDN).
  2. Download all PDFs into a temporary directory (removed when done).
  3. Checksum each and compare against the manifest from the last run.
  4. Convert only added/changed PDFs to Markdown; drop Markdown for removed
     PDFs; rewrite the manifest.

The manifest (uci_md/.manifest.json) is the single source of truth for change
detection, so PDFs never need to be kept on disk. Commit uci_md/ to git and the
delta report tells you exactly what each sync changed.

Usage:
    ./sync.py [--out uci_md] [--force] [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pymupdf4llm

PAGE_URL = "https://www.uci.org/regulations/3MyLDDrwJCJJ0BGGOFzOat"
# PDF URLs are embedded in escaped JSON inside the page HTML.
PDF_RE = re.compile(r'assets\.ctfassets\.net/[^\\"]+\.pdf')
MANIFEST_NAME = ".manifest.json"
IMG_DIR = "images"  # figures extracted from PDFs, stored under <out>/images/
UA = {"User-Agent": "Mozilla/5.0 (uci-regulations-sync)"}


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def discover_pdfs() -> dict[str, str]:
    """Return {output_md_name: pdf_url}, resolving filename collisions.

    Two distinct CDN assets can share a filename; disambiguate the loser with
    its Contentful asset ID (5th path segment) so neither output is lost.
    """
    html = fetch(PAGE_URL).decode("utf-8", "ignore")
    urls = sorted(set("https://" + m for m in PDF_RE.findall(html)))
    if not urls:
        sys.exit("No PDF links found — the page structure may have changed.")

    out: dict[str, str] = {}
    for url in urls:
        base = url.rsplit("/", 1)[-1]
        name = base[:-4] + ".md"  # strip .pdf, add .md
        if name in out:
            asset_id = url.split("/")[4]
            name = f"{asset_id}_{base[:-4]}.md"
        out[name] = url
    return out


def download_all(pdfs: dict[str, str], dest: Path) -> dict[str, tuple[Path, str]]:
    """Download every PDF into dest. Return {md_name: (path, sha256)}."""
    def grab(item: tuple[str, str]) -> tuple[str, Path, str]:
        md_name, url = item
        data = fetch(url)
        p = dest / (md_name[:-3] + ".pdf")
        p.write_bytes(data)
        return md_name, p, hashlib.sha256(data).hexdigest()

    results: dict[str, tuple[Path, str]] = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for md_name, path, digest in ex.map(grab, pdfs.items()):
            results[md_name] = (path, digest)
    return results


def front_matter(pdf_name: str, url: str, digest: str) -> str:
    return (
        "---\n"
        f"source_pdf: {pdf_name}\n"
        f"source_url: {url}\n"
        f"source_sha256: {digest}\n"
        "converter: pymupdf4llm\n"
        "---\n\n"
    )


def clear_images(images_dir: Path, md_name: str) -> None:
    """Remove any figures previously extracted for this document.

    pymupdf4llm names images '<pdf-basename>-<page>-<index>.png'; our temp PDF
    is named '<md-stem>.pdf', so all of a doc's images share that prefix.
    """
    for p in images_dir.glob(f"{md_name[:-3]}.pdf-*"):
        p.unlink()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="uci_md", help="Markdown output dir (default: uci_md)")
    ap.add_argument("--force", action="store_true", help="re-convert all, ignoring the manifest")
    ap.add_argument("--dry-run", action="store_true", help="report the delta but write nothing")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / MANIFEST_NAME
    old = {} if args.force else json.loads(
        manifest_path.read_text() if manifest_path.exists() else "{}"
    )

    print(f"Fetching {PAGE_URL}")
    pdfs = discover_pdfs()
    print(f"Found {len(pdfs)} PDF(s). Downloading to a temp dir for checksum compare...")

    with tempfile.TemporaryDirectory(prefix="uci_pdfs_") as tmp:
        current = download_all(pdfs, Path(tmp))

        added   = [n for n in current if n not in old]
        removed = [n for n in old if n not in current]
        changed = [n for n in current if n in old and current[n][1] != old[n].get("sha256")]
        todo = sorted(added + changed)

        print(
            f"\nDelta: +{len(added)} added  ~{len(changed)} changed  "
            f"-{len(removed)} removed  ={len(current) - len(added) - len(changed)} unchanged"
        )
        for n in sorted(added):   print(f"  + {n}")
        for n in sorted(changed): print(f"  ~ {n}")
        for n in sorted(removed): print(f"  - {n}")

        if args.dry_run:
            print("\n(dry run — nothing written)")
            return 0

        if not todo and not removed:
            print("\nNothing to do — Markdown is up to date.")
            return 0

        images_dir = out / IMG_DIR
        images_dir.mkdir(exist_ok=True)
        # to_markdown embeds the image_path prefix into each link; rewrite it to
        # a path relative to the Markdown file (which lives directly in <out>).
        link_prefix = images_dir.as_posix() + "/"

        for n in todo:
            path, digest = current[n]
            clear_images(images_dir, n)  # drop stale figures before re-rendering
            md = pymupdf4llm.to_markdown(
                str(path),
                show_progress=False,
                write_images=True,
                image_path=str(images_dir),
                dpi=150,
            )
            md = md.replace(link_prefix, IMG_DIR + "/")
            n_imgs = len(list(images_dir.glob(f"{n[:-3]}.pdf-*")))
            (out / n).write_text(front_matter(path.name, pdfs[n], digest) + md, encoding="utf-8")
            print(f"  wrote {n} ({len(md):,} chars, {n_imgs} image(s))")

        for n in removed:
            (out / n).unlink(missing_ok=True)
            clear_images(images_dir, n)
            print(f"  deleted {n}")

    manifest = {n: {"url": pdfs[n], "sha256": current[n][1]} for n in current}
    manifest_path.write_text(json.dumps(dict(sorted(manifest.items())), indent=2) + "\n")
    print(f"\nManifest updated: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
