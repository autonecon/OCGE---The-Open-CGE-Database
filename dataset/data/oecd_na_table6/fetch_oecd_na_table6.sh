#!/usr/bin/env bash
# OECD National Accounts Table 6 (output, value added and components by activity), keyless SDMX.
set -euo pipefail; cd "$(dirname "$0")"
curl -sSf --max-time 600 -H 'Accept: application/vnd.sdmx.data+csv; charset=utf-8' 'https://sdmx.oecd.org/public/rest/data/OECD.SDD.NAD,DSD_NAMAIN10@DF_TABLE6,/A..S1..D1+B1G+D29X39+B2A3G+B3G+B2G........?startPeriod=2017&endPeriod=2022' | gzip -n > oecd_table6_activity_2017_2022.csv.gz
sha256sum oecd_table6_activity_2017_2022.csv.gz
# consumption of fixed capital by activity (S12 natres cap at net operating surplus, David 2026-10-23)
curl -sSf --max-time 600 -H 'Accept: application/vnd.sdmx.data+csv; charset=utf-8' 'https://sdmx.oecd.org/public/rest/data/OECD.SDD.NAD,DSD_NAMAIN10@DF_TABLE6,/A..S1..P51C........?startPeriod=2017&endPeriod=2022' | gzip -n > oecd_table6_p51c_2017_2022.csv.gz
sha256sum oecd_table6_p51c_2017_2022.csv.gz
