#!/usr/bin/env bash
# IMF Government Finance Statistics, Statement of Operations (keyless SDMX 2.1, api.imf.org), percent of GDP:
# G1 revenue, G11 taxes, G111 income taxes (G1111 individuals, G1112 corporations), G112 payroll, G113 property,
# G116 other taxes, G12 social contributions (G121 social security, G1211 employee, G1212 employer).
# SAU ARE QAT KWT BHR OMN; general government (S13), central government (S1311) and social security funds (S1314).
# Round-3 fix wE2, 2026-10-24: GTAP 12 ch.15 uses general government; IMF WoRLD has SAU at central government only.
# The service returns SAU and ARE only (QAT, KWT, BHR and OMN have no GFS_SOO series).
set -euo pipefail
cd "$(dirname "$0")"
curl -sfS -m 300 -H "Accept: application/vnd.sdmx.data+csv;version=1.0.0" -o gfs_soo_income_ssc_gulf_2017_2023.csv \
 "https://api.imf.org/external/sdmx/2.1/data/IMF.STA,GFS_SOO/SAU+ARE+QAT+KWT+BHR+OMN.S13+S1311+S1314.G1.G1_T+G11_T+G111_T+G1111_T+G1112_T+G112_T+G113_T+G116_T+G12_T+G121_T+G1211_T+G1212_T.POGDP_PT.A?startPeriod=2017&endPeriod=2023"
sha256sum gfs_soo_income_ssc_gulf_2017_2023.csv
