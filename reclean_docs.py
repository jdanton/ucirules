#!/usr/bin/env python3
"""One-off: apply clean_md.clean_markdown to the already-committed Markdown.

sync.py now cleans on conversion, but the existing docs/ were converted before
that. This rewrites each doc's body in place (front-matter untouched) without
re-downloading PDFs or re-rendering images. Safe to re-run (idempotent).
"""
from __future__ import annotations

import re
from pathlib import Path

import clean_md

DOCS = Path("docs")
_FM = re.compile(r"(---\n.*?\n---\n)(.*)", re.S)


def main() -> None:
    changed = 0
    for f in sorted(DOCS.glob("*.md")):
        if f.name in ("index.md", "whats-changed.md"):
            continue
        text = f.read_text(encoding="utf-8")
        m = _FM.match(text)
        front, body = (m.group(1), m.group(2)) if m else ("", text)
        body = clean_md.clean_markdown(body)
        body = clean_md.prune_tiny_images(body, DOCS / "images")
        body = clean_md.add_amendment_banner(body)
        cleaned = front + body
        if cleaned != text:
            f.write_text(cleaned, encoding="utf-8")
            changed += 1
    print(f"recleaned {changed} file(s)")


if __name__ == "__main__":
    main()
