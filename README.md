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
   delete Markdown for removed PDFs, and rewrite the manifest.

The manifest is the single source of truth for change detection. Each Markdown
file also carries a small YAML front-matter block (`source_pdf`, `source_url`,
`source_sha256`) for traceability.

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
| `uci_md/.manifest.json` | ✅ | URL + SHA-256 per document (drives delta detection) |
| `.venv/` | ❌ | Local virtualenv |
| PDFs | ❌ | Pulled to a temp dir per run; never committed |

## Notes

- These are text-based PDFs, so extraction needs no OCR. If image-based/scanned
  PDFs are ever added, swap `pymupdf4llm` for an OCR-capable tool (e.g. `marker`
  or `docling`).
- Tables of contents render as Markdown tables with dot-leaders — faithful to
  the source but a little noisy; can be post-processed if desired.
