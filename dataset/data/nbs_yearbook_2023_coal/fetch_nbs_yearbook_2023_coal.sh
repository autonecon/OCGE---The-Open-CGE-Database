#!/usr/bin/env bash
# Fetch two tables of the China Statistical Yearbook 2023 (NBS), which publishes them only as JPG images:
#   13-2  Main indicators of industrial enterprises above designated size by sector (2022), 100 million yuan
#   13-12 Output of industrial products (2021, 2022)
# Values used by S11 are transcribed in README.md. The host sometimes resets connections; rerun on failure.
set -euo pipefail
cd "$(dirname "$0")"
UA='Mozilla/5.0 (Matra data build)'
get() { curl -sSfL --retry 5 --retry-all-errors --max-time 300 -A "$UA" -o "$2" "$1"; }
get https://www.stats.gov.cn/sj/ndsj/2023/html/C13-02.jpg C13-02.jpg
get https://www.stats.gov.cn/sj/ndsj/2023/html/C13-12.jpg C13-12.jpg
sha256sum C13-02.jpg C13-12.jpg
