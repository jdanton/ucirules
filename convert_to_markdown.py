#!/usr/bin/env python3
"""Convert every PDF in a directory tree to Markdown.

Uses pymupdf4llm, which preserves headings, lists, and tables — well suited to
the UCI regulation documents (text-based PDFs, no OCR required).

Each output file gets a small YAML front-matter block recording the source PDF,
its size, and a content hash, so the Markdown is traceable and change-controllable
(e.g. committed to git and diffed when regulations are updated).

Usage:
    ./convert_to_markdown.py [--src uci_pdfs] [--out uci_md] [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import pymupdf4llm


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def front_matter(pdf: Path, digest: str) -> str:
    # Minimal, stable metadata for indexing and change tracking.
    return (
        "---\n"
        f"source_pdf: {pdf.name}\n"
        f"source_bytes: {pdf.stat().st_size}\n"
        f"source_sha256: {digest}\n"
        "converter: pymupdf4llm\n"
        "---\n\n"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default="uci_pdfs", help="directory of PDFs (default: uci_pdfs)")
    ap.add_argument("--out", default="uci_md", help="output directory (default: uci_md)")
    ap.add_argument(
        "--force",
        action="store_true",
        help="re-convert even if the .md exists and the source hash is unchanged",
    )
    args = ap.parse_args()

    src = Path(args.src)
    out = Path(args.out)
    if not src.is_dir():
        print(f"Source directory not found: {src}", file=sys.stderr)
        return 1
    out.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(src.rglob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found under {src}", file=sys.stderr)
        return 1

    total = len(pdfs)
    converted = skipped = failed = 0
    print(f"Converting {total} PDF(s) from '{src}' -> '{out}'...")

    for i, pdf in enumerate(pdfs, 1):
        rel = pdf.relative_to(src).with_suffix(".md")
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        digest = sha256(pdf)

        # Idempotent: skip if the existing .md was built from this exact source.
        if not args.force and dest.exists() and f"source_sha256: {digest}" in dest.read_text(
            encoding="utf-8", errors="ignore"
        ):
            print(f"[{i}/{total}] skip (unchanged): {rel}")
            skipped += 1
            continue

        try:
            md = pymupdf4llm.to_markdown(str(pdf), show_progress=False)
        except Exception as e:  # noqa: BLE001 - report and continue
            print(f"[{i}/{total}] FAILED: {rel} -- {e}", file=sys.stderr)
            failed += 1
            continue

        dest.write_text(front_matter(pdf, digest) + md, encoding="utf-8")
        print(f"[{i}/{total}] wrote: {rel} ({len(md):,} chars)")
        converted += 1

    print(f"\nDone. converted={converted} skipped={skipped} failed={failed} -> '{out}/'")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
