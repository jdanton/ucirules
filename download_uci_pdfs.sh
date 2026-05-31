#!/usr/bin/env bash
#
# Download every PDF linked from the UCI regulations page.
# PDFs are hosted on Contentful's CDN (assets.ctfassets.net) and their URLs
# are embedded in escaped JSON inside the page HTML.
#
# Usage: ./download_uci_pdfs.sh [output_dir]
set -euo pipefail

PAGE_URL="https://www.uci.org/regulations/3MyLDDrwJCJJ0BGGOFzOat"
OUT_DIR="${1:-uci_pdfs}"

mkdir -p "$OUT_DIR"

echo "Fetching page: $PAGE_URL"
html="$(curl -fsSL "$PAGE_URL")"

# Extract unique CDN PDF paths and prefix https://. Read into an array in a
# bash-3.2-compatible way (macOS ships no `mapfile`).
urls=()
while IFS= read -r line; do
  [[ -n "$line" ]] && urls+=("$line")
done < <(
  printf '%s' "$html" \
    | grep -oE 'assets\.ctfassets\.net/[^\\"]+\.pdf' \
    | sort -u \
    | sed 's#^#https://#'
)

count="${#urls[@]}"
if [[ "$count" -eq 0 ]]; then
  echo "No PDF links found — the page structure may have changed." >&2
  exit 1
fi

echo "Found $count unique PDF(s). Downloading into '$OUT_DIR/'..."

i=0
for url in "${urls[@]}"; do
  i=$((i + 1))
  # Use the original filename (last path segment) as the local name.
  fname="$(basename "${url%%\?*}")"
  dest="$OUT_DIR/$fname"
  # Two distinct CDN assets can share a filename; disambiguate with the
  # Contentful asset ID (the 3rd path segment) so neither gets overwritten.
  if [[ -e "$dest" ]]; then
    asset_id="$(printf '%s' "$url" | cut -d/ -f5)"
    dest="$OUT_DIR/${asset_id}_${fname}"
  fi
  printf '[%d/%d] %s\n' "$i" "$count" "$fname"
  # -C - resumes partial downloads; --create-dirs is harmless; retry on transient errors.
  curl -fsSL --retry 3 --retry-delay 2 -o "$dest" "$url" \
    || echo "  !! failed: $url" >&2
done

echo "Done. Files saved in '$OUT_DIR/'."
