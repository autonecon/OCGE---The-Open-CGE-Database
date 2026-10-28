#!/usr/bin/env bash
# Eurostat supply table at basic prices incl. transformation into purchasers' prices (naio_10_cp15):
# taxes less subsidies on products (ind_impv D21X31) by CPA product, million EUR, every reporting country, 2015-2022.
# Keyless SDMX 2.1. QA round 2 P1 (S10 product_tax_pattern control), 2026-10-25.
set -euo pipefail
cd "$(dirname "$0")"
curl -sfS -m 300 -o naio_10_cp15_d21x31_2015_2022.csv \
 "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/naio_10_cp15/A.MIO_EUR.TOTAL.D21X31..?startPeriod=2015&endPeriod=2022&format=SDMX-CSV"
sha256sum naio_10_cp15_d21x31_2015_2022.csv
