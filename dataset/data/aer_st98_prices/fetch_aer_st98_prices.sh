#!/usr/bin/env bash
# Fetch the Alberta Energy Regulator ST98 (Alberta Energy Outlook) price data workbooks.
# Table S1.2 gives the AECO-C natural gas hub price (Cdn$/GJ) by year: 2022 is an actual
# (Canadian Gas Price Reporter) in both editions; the 2024 edition is the latest with 2022 as history.
set -euo pipefail
cd "$(dirname "$0")"
UA='Mozilla/5.0 (Matra data build)'
get() { curl -sSfL --retry 3 --max-time 300 -A "$UA" -o "$2" "$1"; }
get https://www.aer.ca/documents/sts/ST98/2024/st98-2024-prices-and-capital-expenditure-data.xlsx st98-2024-prices-and-capital-expenditure-data.xlsx
get https://www.aer.ca/documents/sts/ST98/2023/ST98-Price-Capital-Expenditure-data.xlsx ST98-2023-Price-Capital-Expenditure-data.xlsx
sha256sum st98-2024-prices-and-capital-expenditure-data.xlsx ST98-2023-Price-Capital-Expenditure-data.xlsx
