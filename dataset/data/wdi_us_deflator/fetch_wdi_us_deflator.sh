#!/usr/bin/env bash
# Fetch World Bank WDI US GDP deflator (NY.GDP.DEFL.ZS) and CPI (FP.CPI.TOTL), 2015-2024, keyless JSON API.
# Used to bring IEA subsidy values (real 2024 USD) to 2022 nominal. sha256 is printed for MANIFEST.
set -euo pipefail
cd "$(dirname "$0")"
UA='Mozilla/5.0 (Matra data build)'
get() { curl -sSfL --retry 3 --max-time 300 -A "$UA" -o "$2" "$1"; }
for s in NY.GDP.DEFL.ZS FP.CPI.TOTL; do
  get "https://api.worldbank.org/v2/country/USA/indicator/$s?format=json&date=2015:2024&per_page=100" "USA_${s}_2015_2024.json"
done
sha256sum USA_*.json
