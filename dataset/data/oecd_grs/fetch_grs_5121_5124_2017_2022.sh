#!/usr/bin/env bash
# OECD Global Revenue Statistics (keyless SDMX): T_5121 (excises) and T_5124 (taxes on exports),
# general government (S13), 2017-2022, % of GDP, USD and national currency. Fix round A1/A2, 2026-10-24.
set -euo pipefail
cd "$(dirname "$0")"
curl -sfS -m 300 -H "Accept: application/vnd.sdmx.data+csv; charset=utf-8" -o grs_rsglobal_5121_5124_2017_2022.csv \
 "https://sdmx.oecd.org/public/rest/data/OECD.CTP.TPS,DSD_REV_COMP_GLOBAL@DF_RSGLOBAL,2.1/.TAX_REV.S13.T_5121+T_5124._T.PT_B1GQ+USD+XDC.A?startPeriod=2017&endPeriod=2022"
sha256sum grs_rsglobal_5121_5124_2017_2022.csv
