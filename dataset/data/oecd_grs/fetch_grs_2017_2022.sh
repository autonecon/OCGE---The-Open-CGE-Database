#!/usr/bin/env bash
# OECD Global Revenue Statistics (keyless SDMX). General government (S13), 2017-2022,
# % of GDP, USD and national currency. Codes: T_1000 T_1100 T_1200 T_2000 T_2100 T_2200 T_2300
# T_3000 T_4000 T_4100 T_5000 T_5111 T_5121 T_5123 TOTALTAX.
set -euo pipefail
cd "$(dirname "$0")"
curl -sfS -m 300 -H "Accept: application/vnd.sdmx.data+csv; charset=utf-8" -o grs_rsglobal_2017_2022.csv \
 "https://sdmx.oecd.org/public/rest/data/OECD.CTP.TPS,DSD_REV_COMP_GLOBAL@DF_RSGLOBAL,2.1/.TAX_REV.S13.T_1000+T_1100+T_1200+T_2000+T_2100+T_2200+T_2300+T_3000+T_4000+T_4100+T_5000+T_5111+T_5121+T_5123+TOTALTAX._T.PT_B1GQ+USD+XDC.A?startPeriod=2017&endPeriod=2022"
sha256sum grs_rsglobal_2017_2022.csv
