#!/usr/bin/env bash
# Census IMDB December 2022 (public file, no API key). Rebuilds the HS10 and HS6 summaries.
set -euo pipefail
cd "$(dirname "$0")"
[ -f IMDB2212.ZIP ] || curl -sfS -m 900 -o IMDB2212.ZIP https://www.census.gov/trade/downloads/2022/Merch/im_m/IMDB2212.ZIP
echo "f3725a5cf34572abf7db9bfc6001cd23a88da58331977847c7db336d91b69e63  IMDB2212.ZIP" | sha256sum -c -
unzip -p IMDB2212.ZIP 'IMP_DETL.txt' | python3 agg.py
python3 - <<'PY'
import collections, csv
cols = ['con_val', 'dut_val', 'cal_dut', 'con_cif', 'gen_val']
acc = collections.OrderedDict()
for r in csv.reader(open('hs10_cty_rp_2022.csv')):
    if r[0] == 'hs10':
        continue
    v = acc.setdefault((r[0][:6], r[1], r[2]), [0] * 5)
    for i in range(5):
        v[i] += int(r[3 + i])
w = csv.writer(open('hs6_cty_rp_2022.csv', 'w'))
w.writerow(['hs6', 'cty', 'rate_prov'] + cols)
for k, v in acc.items():
    w.writerow(list(k) + v)
PY
sha256sum hs10_cty_rp_2022.csv hs6_cty_rp_2022.csv
