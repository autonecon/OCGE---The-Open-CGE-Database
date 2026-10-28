#!/usr/bin/env bash
# Fetch keyless EIA US 2022 energy tables for the S11 US scrutiny section (report-only).
# Public, no API key. Re-run is idempotent; sha256 is printed for MANIFEST.
set -euo pipefail
cd "$(dirname "$0")"
UA='Mozilla/5.0 (Matra data build)'
get() { curl -sSfL --retry 3 --max-time 300 -A "$UA" -o "$2" "$1"; }
# Monthly Energy Review (MER) tables, CSV (annual rows have YYYYMM = YYYY13)
for t in T01.02 T01.04A T01.04B T03.01 T04.01 T06.01 T07.01 T07.02A; do
  get "https://www.eia.gov/totalenergy/data/browser/csv.php?tbl=$t" "MER_${t}.csv"
done
# Petroleum and natural gas annual series (dnav XLS)
get https://www.eia.gov/dnav/pet/xls/PET_SUM_SND_D_NUS_MBBL_A_CUR.xls PET_SUM_SND_D_NUS_MBBL_A_CUR.xls   # US supply and disposition
get https://www.eia.gov/dnav/pet/xls/PET_PNP_REFP2_DC_NUS_MBBL_A.xls PET_PNP_REFP2_DC_NUS_MBBL_A.xls     # refinery net production
get https://www.eia.gov/dnav/pet/xls/PET_MOVE_IMPCUS_A2_NUS_EPC0_IM0_MBBL_A.xls PET_MOVE_IMPCUS_A2_NUS_EPC0_IM0_MBBL_A.xls  # crude imports by country
get "https://www.eia.gov/dnav/pet/xls/PET_MOVE_EXP_DC_NUS-Z00_MBBL_A.xls" "PET_MOVE_EXP_DC_NUS-Z00_MBBL_A.xls"  # petroleum exports
get https://www.eia.gov/dnav/ng/xls/NG_SUM_LSUM_DCU_NUS_A.xls NG_SUM_LSUM_DCU_NUS_A.xls                 # natural gas summary
get https://www.eia.gov/dnav/ng/xls/NG_MOVE_IMPC_S1_A.xls NG_MOVE_IMPC_S1_A.xls                         # gas imports by country
get https://www.eia.gov/dnav/ng/xls/NG_MOVE_EXPC_S1_A.xls NG_MOVE_EXPC_S1_A.xls                         # gas exports by country
sha256sum MER_*.csv *.xls
