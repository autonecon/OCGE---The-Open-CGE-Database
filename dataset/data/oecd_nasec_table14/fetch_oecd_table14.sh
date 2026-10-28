#!/usr/bin/env bash
# OECD Table 14 (annual non-financial accounts by institutional sector), keyless SDMX: taxes on products (D21), other
# taxes on production (D29) and subsidies (D3, D31, D39), total economy (S1) and general government (S13), national
# currency, 2017-2022. Re-fetching can give a different SHA if the source revises.
set -euo pipefail; cd "$(dirname "$0")"
curl -sSf --max-time 600 -H 'Accept: application/vnd.sdmx.data+csv; charset=utf-8' 'https://sdmx.oecd.org/public/rest/data/OECD.SDD.NAD,DSD_NASEC10@DF_TABLE14,/A..S1+S13...D29+D3+D39+D31+D21............?startPeriod=2017&endPeriod=2022' | gzip -n > oecd_table14_d21_d29_d3_2017_2022.csv.gz
sha256sum oecd_table14_d21_d29_d3_2017_2022.csv.gz
