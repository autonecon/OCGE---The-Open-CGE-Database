#!/usr/bin/env bash
# Rebuild raw inputs that are over GitHub's 100 MB file limit.
# Each such file is committed as <name>.part00, <name>.part01, ... (split -b 90M -d -a 2).
# SPLIT_FILES.sha256 holds the SHA-256 of each original (same value as dataset/data/MANIFEST.csv).
# Also extracts eia_intl/INTL.txt from the committed INTL.zip (MANIFEST row: "extracted from INTL.zip").
# Then runs baci/fetch_baci_hs22.sh, which extracts the BACI HS22 2022 csv and country codes for S10.
# The rebuilt files are git-ignored. Run from anywhere: bash dataset/data/reassemble_split_files.sh
set -euo pipefail
cd "$(dirname "$0")"
while read -r sha path; do
  [ -z "$sha" ] && continue
  if [ -f "$path" ] && [ "$(sha256sum "$path" | cut -c1-64)" = "$sha" ]; then echo "ok (already) $path"; continue; fi
  ls "$path".part?? >/dev/null 2>&1 || { echo "MISSING parts for $path" >&2; exit 1; }
  cat "$path".part?? > "$path.tmp"
  got=$(sha256sum "$path.tmp" | cut -c1-64)
  [ "$got" = "$sha" ] || { echo "SHA MISMATCH $path" >&2; rm -f "$path.tmp"; exit 1; }
  mv "$path.tmp" "$path"; echo "rebuilt $path"
done < SPLIT_FILES.sha256
want=cb9c045cb092fd38c0df4edc27715cb48ae2485d2c0401b53409dc21ac63abbc
if [ ! -f eia_intl/INTL.txt ] || [ "$(sha256sum eia_intl/INTL.txt | cut -c1-64)" != "$want" ]; then
  unzip -o -q eia_intl/INTL.zip INTL.txt -d eia_intl
  [ "$(sha256sum eia_intl/INTL.txt | cut -c1-64)" = "$want" ] || { echo "SHA MISMATCH eia_intl/INTL.txt" >&2; exit 1; }
  echo "extracted eia_intl/INTL.txt"
else echo "ok (already) eia_intl/INTL.txt"; fi
# S10 reads the 2022 BACI HS22 year file and the country codes. The zip was rebuilt above from
# its committed parts, so fetch_baci_hs22.sh only checks the sha and unzips (no download).
[ -f baci/BACI_HS22_V202601.zip ] || { echo "MISSING baci/BACI_HS22_V202601.zip" >&2; exit 1; }
bash baci/fetch_baci_hs22.sh
