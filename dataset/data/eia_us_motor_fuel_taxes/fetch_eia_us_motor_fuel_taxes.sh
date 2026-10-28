#!/usr/bin/env bash
# US motor fuel taxes and volumes for 2022 (S10 energy taxes, fix-round item A1: USA as a source region).
# All from www.eia.gov, keyless; US government work (public domain).
#  - EIA Petroleum Marketing Monthly, "Federal and state motor fuel taxes" (every half-year vintage; the
#    January 2022 and July 2022 (revised) sheets give the rates in effect on 1 January and 1 July 2022).
#  - EIA Monthly Energy Review Table 3.7c, petroleum consumption by the transportation sector (annual 2022 = 202213).
#  The on-highway share of transportation distillate (EIA FOKS, last year 2020) is in ../eia_foks/.
set -euo pipefail
cd "$(dirname "$0")"
curl -sfS -m 120 -o pmm_fueltaxes.xlsx "https://www.eia.gov/petroleum/marketing/monthly/xls/fueltaxes.xlsx"
curl -sfS -m 120 -o MER_T03.07C.csv "https://www.eia.gov/totalenergy/data/browser/csv.php?tbl=T03.07C"
sha256sum pmm_fueltaxes.xlsx MER_T03.07C.csv
