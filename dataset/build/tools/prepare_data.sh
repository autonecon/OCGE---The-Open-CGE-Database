#!/usr/bin/env bash
# Before a full build on a fresh clone (beta v4; S16 2026-10-26): files over GitHub's 100 MB limit are stored as
# .partNN pieces, and two stages read extracts that are not committed. This script, run once from anywhere:
#   1. joins every dataset/data/**/X.part00, X.part01, ... into X where X is missing (BACI HS17 and HS22 zips, the
#      Census IMDB zip, BaTIS EBOPS, the StatCan labour zip and others);
#   2. extracts EIA international INTL.txt from INTL.zip (S11);
#   3. runs dataset/data/baci/fetch_baci_hs22.sh, which checks the HS22 zip's SHA-256 and extracts the 2022 year
#      file and country codes that S10 reads (it downloads the zip only if step 1 found no pieces).
#   4. links dataset/docs/literature/gtap12/*.pdf to docs/gtap_method_sources/*.pdf when missing (S01 reads the
#      GTAP 12 ch.9D Table 9.10 PDF from there).
# S01 also writes concord_hs17_to_sector.csv (not committed); a fresh clone needs S01 run before S07.
set -euo pipefail
DATA="$(cd "$(dirname "$0")/../../data" && pwd)"
find "$DATA" -name '*.part00' | while read -r p; do
  t="${p%.part00}"
  if [ ! -e "$t" ]; then cat "$t".part* > "$t" && echo "joined $t"; fi
done
[ -f "$DATA/eia_intl/INTL.txt" ] || (cd "$DATA/eia_intl" && unzip -o -q INTL.zip INTL.txt && echo "extracted eia_intl/INTL.txt")
echo "cb9c045cb092fd38c0df4edc27715cb48ae2485d2c0401b53409dc21ac63abbc  $DATA/eia_intl/INTL.txt" | sha256sum -c -
bash "$DATA/baci/fetch_baci_hs22.sh"
LIT="$(cd "$DATA/.." && pwd)/docs/literature/gtap12"
SRC="$(cd "$DATA/../.." && pwd)/docs/gtap_method_sources"
mkdir -p "$LIT"
for f in "$SRC"/*.pdf; do [ -e "$LIT/$(basename "$f")" ] || ln -s "$f" "$LIT/"; done
