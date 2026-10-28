#!/usr/bin/env bash
# FIGARO value-added rows (Eurostat, keyless). Re-fetching can give a different SHA if Eurostat revises.
set -euo pipefail; cd "$(dirname "$0")"
curl -sSf --max-time 300 'https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/naio_10_fcp_ii4?lang=EN&ind_ava=D1&ind_ava=B2A3G&ind_ava=D29X39&ind_ava=D21X31&c_orig=DOM&time=2022' -o figaro_va_2022.json
curl -sSf --max-time 300 'https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/naio_10_fcp_ii2?lang=EN&ind_ava=D1&ind_ava=B2A3G&ind_ava=D29X39&ind_ava=D21X31&c_orig=DOM&time=2017' -o figaro_va_2017.json
sha256sum figaro_va_*.json
