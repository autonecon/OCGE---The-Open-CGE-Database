#!/usr/bin/env bash
# IMF Government Finance Statistics, Statement of Operations (keyless SDMX 2.1, api.imf.org):
# G1152 taxes on exports, G1151 customs and other import duties, G115 taxes on international trade, G11 taxes, G1 revenue.
# RUS, IND, CHN; general government (S13) and budgetary central government (S1311B); national currency; 2017-2023.
# Fix round A2 (worker wB), 2026-10-24: OECD GRS T_5124 has no 2022 value for these three countries.
set -euo pipefail
cd "$(dirname "$0")"
curl -sfS -m 300 -H "Accept: application/vnd.sdmx.data+csv;version=1.0.0" -o gfs_soo_trade_taxes_rus_ind_chn_2017_2023.csv \
 "https://api.imf.org/external/sdmx/2.1/data/IMF.STA,GFS_SOO/RUS+IND+CHN.S13+S1311B.G1.G1_T+G11_T+G115_T+G1151_T+G1152_T.XDC.A?startPeriod=2017&endPeriod=2023"
sha256sum gfs_soo_trade_taxes_rus_ind_chn_2017_2023.csv
