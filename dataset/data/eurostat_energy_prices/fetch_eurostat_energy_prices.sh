#!/usr/bin/env bash
# Fetch Eurostat non-household gas (nrg_pc_203) and electricity (nrg_pc_205) prices, 2017-S1 to 2022-S2,
# all consumption bands, units, tax levels (I_TAX, X_TAX, X_VAT) and currencies (EUR, NAC, PPS).
# Eurostat dissemination API (SDMX 2.1, SDMX-CSV), keyless. Re-run is idempotent except for the
# LAST UPDATE column, which changes when Eurostat revises the table.
set -euo pipefail
cd "$(dirname "$0")"
UA='Mozilla/5.0 (Matra data build)'
get() { curl -sSfL --retry 3 --max-time 300 -A "$UA" -o "$2" "$1"; }
API=https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data
for d in nrg_pc_203 nrg_pc_205; do
  get "$API/$d/?format=SDMX-CSV&startPeriod=2017-S1&endPeriod=2022-S2&compressed=false" "${d}_2017S1_2022S2.csv"
done
sha256sum nrg_pc_*.csv
