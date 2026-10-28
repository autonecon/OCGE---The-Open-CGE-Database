#!/usr/bin/env bash
# WTO Agriculture Information Management System (AG-IMS), Tariff and Other Quotas, Table MA:2 (quota fill).
# The search page posts the report type to ViewResults (session cookie); GetResultsMA2 then returns every
# member's MA:2 rows as one JSON array (Spanish member names, about 21 MB). The extract keeps CAN, CHE, NOR,
# JPN, ISR and CHN, implementation years 2019-2023 (dataset/build/tools/s10_agims_trq_extract.py).
# Round-3 fix wE2, 2026-10-24 (S10 trq_outside_kor_pan).
set -euo pipefail
cd "$(dirname "$0")"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
curl -sfS -m 120 -c "$tmp/cj" -b "$tmp/cj" -o "$tmp/view.html" \
  -d "ProductCode=&ProductSelectedList=&TRQReportType=MA2&MembersSelectedList=C124&IsAllMembersSelected=false&ImplementationYearsSelectedList=2022&IsAllImpYearSelected=false" \
  https://agims.wto.org/en/TariffandOtherQuotas/ViewResults
curl -sfS -m 300 -c "$tmp/cj" -b "$tmp/cj" -o "$tmp/ma2.json" -d "sort=&page=1&pageSize=500&group=&filter=" \
  https://agims.wto.org/en/TariffandOtherQuotas/GetResultsMA2
sha256sum "$tmp/ma2.json"
python3 -I ../../build/tools/s10_agims_trq_extract.py "$tmp/ma2.json" agims_ma2_can_che_nor_jpn_isr_chn_2019_2023.csv 2019 2023
sha256sum agims_ma2_can_che_nor_jpn_isr_chn_2019_2023.csv
