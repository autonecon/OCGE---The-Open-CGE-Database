#!/usr/bin/env bash
# Eurostat household gas (nrg_pc_202) and electricity (nrg_pc_204) prices, bi-annual, 2022-S1 and 2022-S2,
# all bands, all tax levels (I_TAX, X_VAT, X_TAX), all currencies. Keyless SDMX 2.1 dissemination API.
set -euo pipefail
cd "$(dirname "$0")"
for t in nrg_pc_202 nrg_pc_204; do
  curl -sfS -m 300 -o ${t}_2022S1_2022S2.csv \
   "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/${t}/?format=SDMX-CSV&startPeriod=2022-S1&endPeriod=2022-S2&compressed=false"
done
sha256sum nrg_pc_202_2022S1_2022S2.csv nrg_pc_204_2022S1_2022S2.csv
