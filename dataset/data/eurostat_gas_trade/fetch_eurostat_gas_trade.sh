#!/usr/bin/env bash
# Fetch Eurostat natural gas imports (nrg_ti_gas) and exports (nrg_te_gas) by partner, 2022, natural gas (G3000),
# million m3, every reporting country. Eurostat dissemination API (SDMX 3.0, csvdata), keyless.
# Used by S11 (choice gas_import_origin, Fable QA D-02): the gas origin of importers that declare imports without origin.
set -euo pipefail
cd "$(dirname "$0")"
API='https://ec.europa.eu/eurostat/api/dissemination/sdmx/3.0/data/dataflow/ESTAT'
for d in nrg_ti_gas nrg_te_gas; do
  curl -g -sSfL --retry 3 --max-time 300 -o "${d}_2022.csv" \
    "${API}/${d}/1.0/A.G3000.*.MIO_M3.*?c[TIME_PERIOD]=2022&format=csvdata&formatVersion=2.0&compress=false"
done
sha256sum nrg_t?_gas_2022.csv | tee fetch.log
