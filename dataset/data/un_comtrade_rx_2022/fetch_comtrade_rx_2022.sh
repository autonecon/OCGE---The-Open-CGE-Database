#!/usr/bin/env bash
# UN Comtrade public API (preview endpoint, no key): 2022 annual HS exports (X) and re-exports (RX) to the world
# (partner 0) for the S11 energy lines, every reporter; plus the reporters with any 2022 RX at all (cmdCode TOTAL).
# Used by S11 (choice reexport_netting, Fable QA D-04): a reporter's observed re-export share replaces the
# same-propensity estimate of GTAP 12 ch.12 §12.2.5. Run from anywhere: bash dataset/data/un_comtrade_rx_2022/fetch_comtrade_rx_2022.sh
set -euo pipefail
cd "$(dirname "$0")"
: > fetch.log
base='https://comtradeapi.un.org/public/v1/preview/C/A/HS?period=2022&partnerCode=0&customsCode=C00&motCode=0&partner2Code=0'
for flow in X RX; do
  for cmd in 2701 2709 271111 271121 2710 2716; do
    curl -g -sS -m 120 -o "comtrade_${flow}_${cmd}_2022.json" "${base}&cmdCode=${cmd}&flowCode=${flow}"
    sleep 4
    echo "$(date -u +%FT%TZ) ${flow} ${cmd} $(sha256sum "comtrade_${flow}_${cmd}_2022.json" | cut -c1-64)" >> fetch.log
  done
done
sleep 4
curl -g -sS -m 120 -o comtrade_RX_TOTAL_2022.json "${base}&cmdCode=TOTAL&flowCode=RX"
echo "$(date -u +%FT%TZ) RX TOTAL $(sha256sum comtrade_RX_TOTAL_2022.json | cut -c1-64)" >> fetch.log
