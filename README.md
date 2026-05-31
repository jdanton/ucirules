# UCI Regulations → Markdown

Tracks the [UCI Cycling Regulations](https://www.uci.org/regulations/3MyLDDrwJCJJ0BGGOFzOat)
as searchable, diffable Markdown.

The PDFs are published on UCI's CDN and change over time. [`sync.py`](sync.py)
pulls the current set, detects what changed since the last run, and regenerates
only the affected Markdown — so `git diff` after a sync shows exactly which
regulations were amended.

## How it works

A single pass in [`sync.py`](sync.py):

1. **Fetch** the regulations page and extract every PDF URL (they're embedded in
   the page's JSON, hosted on Contentful's CDN).
2. **Download** all PDFs into a temporary directory (removed when the run ends —
   PDFs are never kept on disk).
3. **Checksum** each PDF (SHA-256) and compare against
   [`uci_md/.manifest.json`](uci_md/.manifest.json) from the previous run to
   classify every document as added / changed / removed / unchanged.
4. **Convert** only the added and changed PDFs to Markdown (via `pymupdf4llm`),
   extracting any figures/diagrams to `uci_md/images/`. Markdown and images for
   removed PDFs are deleted, and the manifest is rewritten.

The manifest is keyed by **source URL** — each document's stable identity — so
files can be renamed freely without desyncing change detection. Each Markdown
file also carries a small YAML front-matter block (`source_pdf`, `source_url`,
`source_sha256`) for traceability.

### File naming

Markdown files are named after their **content**: a descriptive slug derived
from the document's title, joined by `__` to the original source filename (kept
for uniqueness and traceability):

```
11-JO-20260301-E.pdf  ->  part-11-olympic-games__11-JO-20260301-E.md
```

The numbered Regulation Parts (and their amendments) are detected from the
document title — or the source code when the doc just opens with "MEMORANDUM" —
and named from a stable table (`PART_TITLES` in [`sync.py`](sync.py)), so all
of e.g. Part 2's documents share the `part-02-road-races__…` prefix and sort
together. Other documents (policies, lists, protocols, qualification systems)
take a slug from their title heading. When the slug would just repeat the
source name, the prefix is dropped (e.g. `preliminary-provisions.md`).

### Images

Figures are rendered to PNGs under `uci_md/images/`, named
`<document>.pdf-<page>-<index>.png`, and referenced from the Markdown with
relative links (`![](images/...)`). Because each image is namespaced by its
source document, the per-document figures are easy to find, and `clear_images`
removes a document's old figures before re-rendering so nothing is orphaned.

## Usage

```bash
# One-time setup
python3 -m venv .venv
./.venv/bin/pip install pymupdf4llm

# Sync (run anytime to pull the latest and regenerate changed docs)
./.venv/bin/python sync.py

# Preview the delta without writing anything
./.venv/bin/python sync.py --dry-run

# Rebuild everything from scratch, ignoring the manifest
./.venv/bin/python sync.py --force
```

Options: `--out DIR` (default `uci_md`), `--dry-run`, `--force`.

## Change-control workflow

```bash
./.venv/bin/python sync.py
git add uci_md/
git commit -m "Sync UCI regulations $(date +%F)"
```

The commit diff is a human-readable record of what UCI changed. Run on a
schedule (cron / CI) to keep a continuous history.

## Layout

| Path | Tracked | Description |
|------|:------:|-------------|
| `sync.py` | ✅ | Download → checksum-diff → convert, in one pass |
| `uci_md/` | ✅ | Generated Markdown, one file per regulation |
| `uci_md/images/` | ✅ | Figures/diagrams extracted from the PDFs (PNG) |
| `uci_md/.manifest.json` | ✅ | Source URL → {name, stem, SHA-256} (drives delta detection) |
| `.venv/` | ❌ | Local virtualenv |
| PDFs | ❌ | Pulled to a temp dir per run; never committed |

## Notes

- These are text-based PDFs, so extraction needs no OCR. If image-based/scanned
  PDFs are ever added, swap `pymupdf4llm` for an OCR-capable tool (e.g. `marker`
  or `docling`).
- Tables of contents render as Markdown tables with dot-leaders — faithful to
  the source but a little noisy; can be post-processed if desired.
