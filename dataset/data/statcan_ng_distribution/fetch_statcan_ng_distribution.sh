#!/usr/bin/env bash
# Fetch Statistics Canada table 25-10-0059-01 (Canadian monthly natural gas distribution, Canada and
# provinces): deliveries to industrial / commercial / residential consumers in m3, GJ, CAD and customers.
# Keyless WDS full-table CSV zip. CAD / GJ gives a delivered (distribution-level) price by province.
set -euo pipefail
cd "$(dirname "$0")"
UA='Mozilla/5.0 (Matra data build)'
get() { curl -sSfL --retry 3 --max-time 300 -A "$UA" -o "$2" "$1"; }
get https://www150.statcan.gc.ca/n1/tbl/csv/25100059-eng.zip 25100059-eng.zip
sha256sum 25100059-eng.zip
