#!/usr/bin/env bash
# World Bank WDI API v2 (keyless JSON).
set -euo pipefail; cd "$(dirname "$0")"
for s in AG.LND.ARBL.HA.PC NY.GDP.PCAP.CD; do
  curl -sSf --max-time 120 "https://api.worldbank.org/v2/country/all/indicator/$s?date=2011:2022&format=json&per_page=20000" -o "$s.json"
done
sha256sum *.json
