#!/usr/bin/env python3
"""Sync UCI regulation PDFs into a change-controlled Markdown tree.

One pass:
  1. Fetch the regulations page and extract every PDF URL (Contentful CDN).
  2. Download all PDFs into a temporary directory (removed when done).
  3. Checksum each and compare against the manifest from the last run.
  4. Convert only added/changed PDFs to Markdown (extracting figures to
     images/), drop Markdown for removed PDFs, and rewrite the manifest.

Markdown files are named after their *content* — a descriptive slug derived
from the document's title, joined to the original source filename for
uniqueness and traceability, e.g.:

    11-JO-20260301-E.pdf  ->  part-11-olympic-games__11-JO-20260301-E.md

The manifest (docs/.manifest.json) is keyed by source URL — the stable
identity of each document — so renames never desync change detection. PDFs
never need to be kept on disk. Commit docs/ to git and the delta report
tells you exactly what each sync changed.

Usage:
    ./sync.py [--out DIR] [--force] [--dry-run] [--docs] [--ghdeploy] [--no-sync]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import clean_md  # post-process pymupdf4llm output (strip TOCs/page furniture)

# pymupdf4llm is imported lazily inside sync_markdown() — it pulls in the heavy
# PyMuPDF stack, which a docs-only build (--docs --no-sync) shouldn't require.

PAGE_URL = "https://www.uci.org/regulations/3MyLDDrwJCJJ0BGGOFzOat"
# PDF URLs are embedded in escaped JSON inside the page HTML.
PDF_RE = re.compile(r'assets\.ctfassets\.net/[^\\"]+\.pdf')
MANIFEST_NAME = ".manifest.json"
IMG_DIR = "images"  # figures extracted from PDFs, stored under <out>/images/
UA = {"User-Agent": "Mozilla/5.0 (uci-regulations-sync)"}

# Stable titles for the numbered Regulation Parts. Amendment documents often
# open with a generic "MEMORANDUM" heading, so the Part title is taken from
# here (keyed by Part number) rather than from the document's own wording.
PART_TITLES = {
    "1": "General Organisation of Cycling as a Sport",
    "2": "Road Races",
    "3": "Track Races",
    "4": "Mountain Bike",
    "5": "Cyclo-cross",
    "6": "BMX Racing",
    "6bis": "BMX Freestyle",
    "7": "Trials",
    "8": "Indoor Cycling",
    "9": "World Championships",
    "10": "Continental Championships and Regional Games",
    "11": "Olympic Games",
    "12": "Discipline and Procedures",
    "13": "Medical Rules",
    "14": "Anti-Doping Rules",
    "15": "Cycling for All",
    "16": "Para-Cycling",
    "17": "Cycling Esports",
}

# Headings that never describe a document; skipped when guessing a title.
_GENERIC = {"memorandum", "uci cycling regulations", "preamble"}
_GENERIC_PREFIXES = (
    "version on", "rules amendments applying", "rules amendment",
    "rule changes", "chapter ", "section ", "art. ", "annex ",
    "table of content",  # matches singular and plural
)
# Discipline keywords -> Part number, for source names with no explicit Part.
# Ordered: 'freestyle' must win over 'bmx' for the BMX Freestyle rules.
_KEYWORD_PART = [
    ("freestyle", "6bis"), ("bmx", "6"), ("mtb", "4"), ("mountain", "4"),
    ("cyclo", "5"), ("trials", "7"), ("track", "3"), ("road", "2"),
    ("esports", "17"), ("para", "16"), ("indoor", "8"),
]


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def discover_pdfs() -> dict[str, str]:
    """Return {source_stem: pdf_url}, resolving filename collisions.

    The stem is the source PDF's basename (no extension); it names the temp
    PDF, the extracted image files, and the source-code suffix of the Markdown.
    Two distinct CDN assets can share a filename; disambiguate the loser with
    its Contentful asset ID (5th path segment) so neither output is lost.
    """
    html = fetch(PAGE_URL).decode("utf-8", "ignore")
    urls = sorted(set("https://" + m for m in PDF_RE.findall(html)))
    if not urls:
        sys.exit("No PDF links found — the page structure may have changed.")

    out: dict[str, str] = {}
    for url in urls:
        stem = url.rsplit("/", 1)[-1][:-4]  # basename minus ".pdf"
        if stem in out:
            stem = url.split("/")[4] + "_" + stem  # prefix asset ID
        out[stem] = url
    return out


def download_all(pdfs: dict[str, str], dest: Path) -> dict[str, tuple[Path, str]]:
    """Download every PDF into dest. Return {stem: (path, sha256)}."""
    def grab(item: tuple[str, str]) -> tuple[str, Path, str]:
        stem, url = item
        data = fetch(url)
        p = dest / (stem + ".pdf")
        p.write_bytes(data)
        return stem, p, hashlib.sha256(data).hexdigest()

    results: dict[str, tuple[Path, str]] = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for stem, path, digest in ex.map(grab, pdfs.items()):
            results[stem] = (path, digest)
    return results


# --------------------------------------------------------------------------- #
# Content-aware naming
# --------------------------------------------------------------------------- #

_ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50}


def _roman_to_int(s: str) -> int | None:
    s = s.lower()
    if not s or any(c not in _ROMAN for c in s):
        return None
    total, prev = 0, 0
    for c in reversed(s):
        v = _ROMAN[c]
        total += -v if v < prev else v
        prev = max(prev, v)
    return total


def slugify(text: str, max_words: int = 8) -> str:
    """Lowercase ASCII kebab-case slug, capped at max_words words."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    words = re.findall(r"[A-Za-z0-9]+", text.lower())
    return "-".join(words[:max_words])


def _part_key(num: str, bis: bool) -> str | None:
    """Normalise a Part token ('11', 'IX', 'VI'+bis) to a PART_TITLES key."""
    n = int(num) if num.isdigit() else _roman_to_int(num)
    if n is None:
        return None
    return f"{n}bis" if bis else str(n)


_PART_RE = re.compile(r"(?i)\bPART[_\s]+(\d{1,2}|[IVXL]+)\s*(BIS)?")


def detect_part(text: str) -> str | None:
    """Find a 'PART <n>' reference and map it to a PART_TITLES key, or None."""
    for num, bis in _PART_RE.findall(text):
        key = _part_key(num, bool(bis))
        if key in PART_TITLES:
            return key
    return None


def detect_part_from_stem(stem: str) -> str | None:
    """Infer a Part number from a source filename: 'Part_IX', leading '2-ROA',
    '6BIS-BFR', or a discipline keyword."""
    if (key := detect_part(stem)):
        return key
    if (m := re.match(r"(?i)(\d{1,2})(bis)?[-_]", stem)):
        if (key := _part_key(m.group(1), bool(m.group(2)))) in PART_TITLES:
            return key
    low = stem.lower()
    for word, key in _KEYWORD_PART:
        if word in low:
            return key
    return None


def _strip_heading(line: str) -> str:
    """Turn a Markdown heading/emphasis line into plain text."""
    line = re.sub(r"^#+\s*", "", line.strip())
    line = line.replace("**", "").replace("~~", "").strip()
    line = re.sub(r"^_(.*)_$", r"\1", line).strip()
    return line


def title_candidates(md_text: str) -> list[str]:
    """Meaningful heading/bold lines, in order, with boilerplate removed.

    The document title is candidate 0; this also locates a 'PART n' title that
    sits just below a 'MEMORANDUM' banner in amendment documents.
    """
    out: list[str] = []
    for raw in md_text.splitlines():
        s = raw.strip()
        is_heading = s.startswith("#")
        is_bold = s.startswith("**") and s.endswith("**") and len(s) > 4
        if not (is_heading or is_bold):
            continue
        t = _strip_heading(s)
        low = t.lower()
        if not t or low in _GENERIC or any(low.startswith(p) for p in _GENERIC_PREFIXES):
            continue
        if re.match(r"^\d{1,3}[.)]\s", t) or t.startswith("§"):  # numbered section
            continue
        if not re.search(r"[A-Za-z]{3}", t):  # mostly punctuation/dates
            continue
        out.append(t)
    return out


def detect_part_in_title(candidates: list[str]) -> str | None:
    """A 'PART n ...' among the first few title lines marks a Regulation Part.

    Restricted to the title region so internal 'Part 1' cross-references in
    unrelated documents don't masquerade as the document's own Part.
    """
    for cand in candidates[:3]:
        if (m := re.match(r"(?i)PART[_\s]+(\d{1,2}|[IVXL]+)\s*(BIS)?\b", cand)):
            if (key := _part_key(m.group(1), bool(m.group(2)))) in PART_TITLES:
                return key
    return None


def doc_slug(md_text: str, stem: str) -> str:
    """Descriptive slug for a document, from its Part or its title heading."""
    candidates = title_candidates(md_text)
    part = detect_part_in_title(candidates) or detect_part_from_stem(stem)
    if part in PART_TITLES:
        n = part[:-3] if part.endswith("bis") else part
        suffix = "bis" if part.endswith("bis") else ""
        return f"part-{int(n):02d}{suffix}-{slugify(PART_TITLES[part])}"
    return slugify(candidates[0]) if candidates else slugify(stem)


def output_name(md_text: str, stem: str) -> str:
    """Final Markdown filename: '<slug>__<stem>.md', or '<stem>.md' when the
    slug adds nothing over the source name."""
    slug = doc_slug(md_text, stem)
    if not slug or slug == slugify(stem):
        return f"{stem}.md"
    return f"{slug}__{stem}.md"


def front_matter(pdf_name: str, url: str, digest: str) -> str:
    return (
        "---\n"
        f"source_pdf: {pdf_name}\n"
        f"source_url: {url}\n"
        f"source_sha256: {digest}\n"
        "converter: pymupdf4llm\n"
        "---\n\n"
    )


def clear_images(images_dir: Path, stem: str) -> None:
    """Remove any figures previously extracted for this document.

    pymupdf4llm names images '<stem>.pdf-<page>-<index>.png', so all of a
    document's images share that prefix.
    """
    for p in images_dir.glob(f"{stem}.pdf-*"):
        p.unlink()


def sync_markdown(args) -> bool:
    """Download PDFs, convert the added/changed ones to Markdown, and rewrite
    the manifest. Returns False if the run short-circuited (dry run, so the
    docs step should be skipped too), True otherwise."""
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / MANIFEST_NAME
    # Manifest is keyed by source URL: {url: {name, stem, sha256}}.
    old = {} if args.force else json.loads(
        manifest_path.read_text() if manifest_path.exists() else "{}"
    )

    print(f"Fetching {PAGE_URL}")
    pdfs = discover_pdfs()  # {stem: url}
    by_url = {url: stem for stem, url in pdfs.items()}
    print(f"Found {len(pdfs)} PDF(s). Downloading to a temp dir for checksum compare...")

    with tempfile.TemporaryDirectory(prefix="uci_pdfs_") as tmp:
        current = download_all(pdfs, Path(tmp))  # {stem: (path, sha)}
        cur_sha = {url: current[stem][1] for url, stem in by_url.items()}

        added   = [u for u in cur_sha if u not in old]
        removed = [u for u in old if u not in cur_sha]
        changed = [u for u in cur_sha if u in old and cur_sha[u] != old[u].get("sha256")]
        todo = sorted(added + changed, key=lambda u: by_url[u])

        print(
            f"\nDelta: +{len(added)} added  ~{len(changed)} changed  "
            f"-{len(removed)} removed  ={len(cur_sha) - len(added) - len(changed)} unchanged"
        )
        for u in sorted(added,   key=lambda u: by_url[u]): print(f"  + {by_url[u]}")
        for u in sorted(changed, key=lambda u: by_url[u]): print(f"  ~ {by_url[u]}")
        for u in sorted(removed, key=lambda u: old[u]['name']): print(f"  - {old[u]['name']}")

        if args.dry_run:
            print("\n(dry run — nothing written)")
            return False

        if not todo and not removed:
            print("\nNothing to do — Markdown is up to date.")
            return True

        images_dir = out / IMG_DIR
        images_dir.mkdir(exist_ok=True)
        # to_markdown embeds the image_path prefix into each link; rewrite it to
        # a path relative to the Markdown file (which lives directly in <out>).
        link_prefix = images_dir.as_posix() + "/"

        manifest = dict(old)
        if todo:
            import pymupdf4llm  # heavy import; only needed when converting PDFs
        for u in todo:
            stem, (path, digest) = by_url[u], current[by_url[u]]
            clear_images(images_dir, stem)  # drop stale figures before re-rendering
            md = pymupdf4llm.to_markdown(
                str(path), show_progress=False,
                write_images=True, image_path=str(images_dir), dpi=150,
            )
            md = md.replace(link_prefix, IMG_DIR + "/")
            md = clean_md.clean_markdown(md)  # strip printed TOCs and page furniture
            name = output_name(md, stem)
            # If a change renamed the doc, drop the file under its old name.
            if u in old and old[u]["name"] != name:
                (out / old[u]["name"]).unlink(missing_ok=True)
            (out / name).write_text(front_matter(stem + ".pdf", u, digest) + md, encoding="utf-8")
            manifest[u] = {"name": name, "stem": stem, "sha256": digest}
            n_imgs = len(list(images_dir.glob(f"{stem}.pdf-*")))
            print(f"  wrote {name} ({len(md):,} chars, {n_imgs} image(s))")

        for u in removed:
            (out / old[u]["name"]).unlink(missing_ok=True)
            clear_images(images_dir, old[u]["stem"])
            del manifest[u]
            print(f"  deleted {old[u]['name']}")

    manifest_path.write_text(json.dumps(dict(sorted(manifest.items())), indent=2) + "\n")
    print(f"\nManifest updated: {manifest_path}")
    return True


def build_docs(deploy: bool) -> None:
    """Build the docs site (and optionally deploy it) from the Markdown already
    on disk. `properdocs gh-deploy` builds as part of deploying, so a deploy
    doesn't also need a separate build pass.

    properdocs is invoked through the running interpreter (`-m`) rather than a
    bare `properdocs` so it resolves from the same environment as this script,
    even when that venv's bin/ isn't on PATH. It runs from the script's own
    directory, where properdocs.yml lives, so the build doesn't depend on the
    caller's working directory."""
    cmd = "gh-deploy" if deploy else "build"
    root = Path(__file__).resolve().parent
    subprocess.run([sys.executable, "-m", "properdocs", cmd], cwd=root, check=True)
    print(f"\n{'Deployed to /gh-pages/ branch' if deploy else 'Docs generated'}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="./docs", help="Markdown output dir (default: ./docs)")
    ap.add_argument("--force", action="store_true", help="re-convert all, ignoring the manifest")
    ap.add_argument("--dry-run", action="store_true", help="report the delta but write nothing")
    ap.add_argument("--docs", action="store_true", help="build the docs site from the Markdown")
    ap.add_argument("--ghdeploy", action="store_true", help="build the docs site and deploy it to the gh-pages branch")
    ap.add_argument("--no-sync", action="store_true",
                    help="skip the PDF sync; build/deploy docs from the existing Markdown")
    args = ap.parse_args()

    if args.no_sync:
        if not (args.docs or args.ghdeploy):
            sys.exit("--no-sync does nothing without --docs or --ghdeploy.")
    elif not sync_markdown(args):
        return 0  # dry run short-circuits before touching the docs site

    # The docs site is built from Markdown on disk, so it runs whether or not
    # the sync found changes — and a dry run never writes the site.
    if (args.docs or args.ghdeploy) and not args.dry_run:
        build_docs(deploy=args.ghdeploy)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
