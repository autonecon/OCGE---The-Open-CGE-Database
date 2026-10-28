#!/usr/bin/env bash
# Fetch NDRC Notice 发改价格〔2022〕303号 (further improving the coal market price formation mechanism)
# and its annex: reasonable ranges for medium/long-term contract thermal coal prices, effective 2022-05-01.
# The annex is a scanned one-page PDF (no text layer); its table is transcribed in README.md.
set -euo pipefail
cd "$(dirname "$0")"
UA='Mozilla/5.0 (Matra data build)'
get() { curl -sSfL --retry 3 --max-time 300 -A "$UA" -o "$2" "$1"; }
get https://www.ndrc.gov.cn/xxgk/zcfb/tz/202202/t20220225_1317003.html ndrc_2022_303_notice.html
get https://www.ndrc.gov.cn/xxgk/zcfb/tz/202202/P020220225550328647794.pdf ndrc_2022_303_annex.pdf
sha256sum ndrc_2022_303_notice.html ndrc_2022_303_annex.pdf
