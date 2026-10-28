#!/bin/bash
# UN Comtrade 2022 total exports to World by reporter (public preview API, no key). Beta v5 B partner cap (S07).
set -euo pipefail
cd "$(dirname "$0")"
curl -sS --max-time 120 -o comtrade_X_TOTAL_2022.json \
  "https://comtradeapi.un.org/public/v1/preview/C/A/HS?period=2022&cmdCode=TOTAL&flowCode=X&partnerCode=0&customsCode=C00&motCode=0&partner2Code=0"
echo "$(date -u +%FT%TZ) X TOTAL $(sha256sum comtrade_X_TOTAL_2022.json | cut -d' ' -f1)" >> fetch.log
