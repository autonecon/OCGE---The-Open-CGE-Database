#!/usr/bin/env bash
# Fetch keyless EIA 2022 domestic energy prices for S11 domestic basic prices
# (coal sales prices, electricity retail prices, natural gas prices by state).
# Public, no API key. Re-run is idempotent; sha256 is printed for MANIFEST.
# Needs curl, pdftotext (poppler-utils) and python3.
set -euo pipefail
cd "$(dirname "$0")"
UA='Mozilla/5.0 (Matra data build)'
get() { curl -sSfL --retry 3 --max-time 300 -A "$UA" -o "$2" "$1"; }
# Annual Coal Report 2022 (the live xls tables now show 2024; the 2022 edition is archived as PDF only)
get https://www.eia.gov/coal/annual/archive/0584_2022.pdf ACR_2022_0584.pdf
pdftotext -layout ACR_2022_0584.pdf - > "${TMPDIR:-/tmp}/acr2022_layout.txt"
python3 -I extract_acr_tables.py "${TMPDIR:-/tmp}/acr2022_layout.txt" .   # tables 28 and 31 to CSV
# Electric Power Annual 2022 (archived edition) and the state average price history
get https://www.eia.gov/electricity/annual/archive/2022/xls/epa_02_10.xlsx EPA2022_epa_02_10.xlsx  # avg retail price by state and sector, 2022 and 2021
get https://www.eia.gov/electricity/annual/archive/2022/xls/epa_02_04.xlsx EPA2022_epa_02_04.xlsx  # US avg retail price by sector, 2012-2022
get https://www.eia.gov/electricity/data/state/avgprice_annual.xlsx avgprice_annual.xlsx            # by state, sector, provider type, 1990-latest
# Natural gas annual prices by state (dnav XLS, full history)
get https://www.eia.gov/dnav/ng/xls/NG_PRI_SUM_A_EPG0_PIN_DMCF_A.xls NG_PRI_SUM_A_EPG0_PIN_DMCF_A.xls  # industrial
get https://www.eia.gov/dnav/ng/xls/NG_PRI_SUM_A_EPG0_PEU_DMCF_A.xls NG_PRI_SUM_A_EPG0_PEU_DMCF_A.xls  # electric power
get https://www.eia.gov/dnav/ng/xls/NG_PRI_SUM_A_EPG0_PG1_DMCF_A.xls NG_PRI_SUM_A_EPG0_PG1_DMCF_A.xls  # citygate
get https://www.eia.gov/dnav/ng/xls/NG_PRI_SUM_A_EPG0_FWA_DMCF_A.xls NG_PRI_SUM_A_EPG0_FWA_DMCF_A.xls  # wellhead (discontinued)
get https://www.eia.gov/dnav/ng/xls/NG_PRI_SUM_DCU_NUS_A.xls NG_PRI_SUM_DCU_NUS_A.xls                  # US price summary
sha256sum ACR_2022_0584.pdf acr2022_*.csv *.xlsx *.xls
