#!/usr/bin/env bash
# OECD Inventory of Export Restrictions on Industrial (Critical) Raw Materials (keyless SDMX, sdmx.oecd.org):
# dataflow OECD.TAD.ADM,DSD_QDD_TAD_EXP_RESTRIC@DF_QDD_TAD_EXP_RESTRIC,3.0; RUS, IND, CHN; M1 export tax, M2 export surtax,
# M5 fiscal tax on exports; every HS 2007 product and variation; 2022.
# Fix round A2 (worker wB), 2026-10-24.
set -euo pipefail
cd "$(dirname "$0")"
curl -sfS -m 300 -H "Accept: application/vnd.sdmx.data+csv; charset=utf-8" -o oecd_export_restrictions_rus_ind_chn_2022.csv \
 "https://sdmx.oecd.org/public/rest/data/OECD.TAD.ADM,DSD_QDD_TAD_EXP_RESTRIC@DF_QDD_TAD_EXP_RESTRIC,3.0/RUS+IND+CHN..M1+M2+M5..?startPeriod=2022&endPeriod=2022"
sha256sum oecd_export_restrictions_rus_ind_chn_2022.csv
