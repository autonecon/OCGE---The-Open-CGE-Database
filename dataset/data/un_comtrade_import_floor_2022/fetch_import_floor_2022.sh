#!/usr/bin/env bash
# UN Comtrade public API (preview endpoint, no key, at most 500 rows a call): 2022 annual imports (flowCode M, CIF) by
# partner and HS2 chapter, as reported by the importer's own customs, for the beta v5 importer floor (S07 choice
# importer_floor, fix B): China (156) and Mexico (484). One call per HS2 chapter (every partner), plus the all-goods
# total (cmdCode TOTAL, partner World). Run from anywhere: bash dataset/data/un_comtrade_import_floor_2022/fetch_import_floor_2022.sh
set -euo pipefail
cd "$(dirname "$0")"
base='https://comtradeapi.un.org/public/v1/preview/C/A/HS?period=2022&customsCode=C00&motCode=0&partner2Code=0&flowCode=M'
: > fetch.log
for rep in 156 484; do
  mkdir -p "M_${rep}"
  f="M_${rep}/M_${rep}_TOTAL.json"
  for try in 1 2 3 4 5; do
    curl -g -sS -m 120 -o "$f" "${base}&reporterCode=${rep}&partnerCode=0&cmdCode=TOTAL" && grep -q '"data"' "$f" && break
    sleep $((try * 8))
  done
  echo "$(date -u +%FT%TZ) ${rep} TOTAL $(sha256sum "$f" | cut -c1-64)" >> fetch.log
  for ch in $(seq -w 1 99); do
    [ "$ch" = "77" ] && continue
    f="M_${rep}/M_${rep}_${ch}.json"
    for try in 1 2 3 4 5; do
      curl -g -sS -m 120 -o "$f" "${base}&reporterCode=${rep}&cmdCode=${ch}" && grep -q '"data"' "$f" && break
      sleep $((try * 8))
    done
    grep -q '"data"' "$f" || { echo "failed ${rep} ${ch}" >&2; exit 1; }
    echo "$(date -u +%FT%TZ) ${rep} ${ch} $(sha256sum "$f" | cut -c1-64)" >> fetch.log
    sleep 3
  done
done
find M_156 M_484 -name '*.json' | sort | xargs sha256sum > SHA256SUMS
