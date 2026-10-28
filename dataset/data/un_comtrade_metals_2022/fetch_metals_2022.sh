#!/usr/bin/env bash
# UN Comtrade public API (preview endpoint, no key): 2022 annual exports (flowCode X) to the world (partner 0) of
# HS 7108 (gold, unwrought or semi-manufactured, non-monetary included) and HS 7403 (refined copper, cathodes), every
# reporter, as each exporter's own customs reports them. Beta v5 fix G (S07 choice gold_reexport = metal_reexport): the
# ceiling on a listed region's BACI exports is max(own customs exports, mine output). Run from anywhere:
#   bash dataset/data/un_comtrade_metals_2022/fetch_metals_2022.sh
set -euo pipefail
cd "$(dirname "$0")"
base='https://comtradeapi.un.org/public/v1/preview/C/A/HS?period=2022&partnerCode=0&customsCode=C00&motCode=0&partner2Code=0'
: > fetch.log
for cmd in 7108 7403; do
  f="comtrade_X_${cmd}_2022.json"
  for try in 1 2 3 4 5; do
    curl -g -sS -m 120 -o "$f" "${base}&cmdCode=${cmd}&flowCode=X" && grep -q '"data"' "$f" && break
    sleep $((try * 8))
  done
  echo "$(date -u +%FT%TZ) X ${cmd} $(sha256sum "$f" | cut -c1-64)" >> fetch.log
  sleep 4
done
sha256sum comtrade_X_*_2022.json > SHA256SUMS
