#!/bin/bash
# UN Comtrade public preview API (keyless): 2022 exports (X) and re-exports (RX) to World by HS2, per RX reporter.
cd "$(dirname "$0")"
C=$(python3 -c "print(','.join(f'{i:02d}' for i in range(1,100) if i!=77))")
for r in $(python3 -c "import json;print(' '.join(str(x['reporterCode']) for x in json.load(open('../comtrade_RX_TOTAL_2022.json'))['data']))"); do
  for f in RX X; do
    [ -s ${f}_${r}_HS2.json ] && python3 -c "import json,sys;sys.exit(0 if json.load(open('${f}_${r}_HS2.json')).get('data') else 1)" && continue
    curl -sS --max-time 90 "https://comtradeapi.un.org/public/v1/preview/C/A/HS?reporterCode=$r&period=2022&partnerCode=0&customsCode=C00&motCode=0&partner2Code=0&cmdCode=$C&flowCode=$f" -o ${f}_${r}_HS2.json
    sleep 4
  done
done
sha256sum *.json > SHA256SUMS
