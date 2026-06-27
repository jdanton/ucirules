"""Post-process pymupdf4llm output into clean docs-site Markdown.

The UCI PDFs carry per-page furniture and printed tables of contents that
convert into noise: dot-leader lines (".......... 27"), TOC tables, repeated
"UCI CYCLING REGULATIONS" running headers, and "Page N of M" footers. This
strips that furniture while leaving real content — including legitimate data
tables — untouched.

Used by sync.py on every conversion, and by reclean_docs.py for a one-off pass
over the already-committed Markdown.
"""
from __future__ import annotations

import re

_DOT_LEADER = re.compile(r"\.{4,}")                       # ".......... 27"
_SEP_ROW = re.compile(r"\s*\|[\s:|-]+\|\s*$")             # table delimiter row
_RUNNING_HEADER = re.compile(r"(#+\s*)?\*\*UCI CYCLING REGULATIONS\*\*\s*$")
_PAGE_FOOTER = re.compile(r"Page \d+ of \d+\s*$")
_DOC_TAG = re.compile(r"UCI ADR \d{4}\s*$")               # e.g. "UCI ADR 2021"
_TOC_HEADING = re.compile(r"(?i)(#+\s*)?\*{0,2}\s*TABLE OF CONTENTS\s*\*{0,2}\s*$")
# Intra-word underscore: defined terms smashed together with no spaces, which
# only happens inside printed-TOC table cells ("the_Code_and"). Real body text
# spaces its italics (" _Code_ ") and is never affected; image links contain
# underscores too, so this signal is applied to table rows only.
_TOC_GARBLE = re.compile(r"\w_\w")


def _is_furniture(stripped: str) -> bool:
    return bool(
        _RUNNING_HEADER.fullmatch(stripped)
        or _PAGE_FOOTER.fullmatch(stripped)
        or _DOC_TAG.fullmatch(stripped)
        or _TOC_HEADING.fullmatch(stripped)
    )


_TOC_MARKER = re.compile(r"(?i)\bTABLE OF CONTENTS\b")


def _is_toc_table(block: list[str]) -> bool:
    """A printed table of contents, in any of the forms the PDFs produce."""
    text = "\n".join(block)
    return bool(
        _DOT_LEADER.search(text)      # dot leaders ".......... 27"
        or _TOC_GARBLE.search(text)   # smashed defined terms "the_Code_and"
        or _TOC_MARKER.search(text)   # an explicit "TABLE OF CONTENTS" cell
    )


def clean_markdown(md: str) -> str:
    lines = md.split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        ln = lines[i]
        if ln.lstrip().startswith("|"):
            # Gather the whole contiguous table block and drop it if it's a TOC.
            j = i
            while j < n and lines[j].lstrip().startswith("|"):
                j += 1
            block = lines[i:j]
            if not _is_toc_table(block):
                out.extend(block)
            i = j
            continue
        # Non-table line: drop dot-leader (prose TOC) lines and page furniture.
        if not _DOT_LEADER.search(ln) and not _is_furniture(ln.strip()):
            out.append(ln)
        i += 1

    md = "\n".join(out)
    # Cosmetic: italic defined-term markers leave a space before punctuation
    # ("_Riders_ ," -> "Riders ,"); tidy that, then collapse blank-line gaps.
    md = re.sub(r" +([,;:])", r"\1", md)
    md = re.sub(r" +\.(\s|$)", r".\1", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip() + "\n"
