#!/usr/bin/env bash
# BEA supply-use tables (keyless): value-added rows of the summary Use table, supply-use framework (basic prices).
# Re-fetching can give a different SHA if BEA revises (the 2024 comprehensive update is the vintage used).
set -euo pipefail; cd "$(dirname "$0")"
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
curl -sSf --max-time 600 'https://apps.bea.gov/industry/iTables%20Static%20Files/AllTablesSUP.zip' -o "$tmp/AllTablesSUP.zip"
sha256sum "$tmp/AllTablesSUP.zip"
unzip -q -o "$tmp/AllTablesSUP.zip" Use_Tables_Supply-Use_Framework_1997-2023_Summary.xlsx -d "$tmp"
python3 -I - "$tmp/Use_Tables_Supply-Use_Framework_1997-2023_Summary.xlsx" bea_use_sut_summary_va_2017_2023.csv <<'PY'
import sys
import pandas as pd
src, out = sys.argv[1], sys.argv[2]
rows = ('V001', 'T00OTOP', 'T00OSUB', 'V003', 'VABAS')
recs = []
for y in range(2017, 2024):
    d = pd.read_excel(src, str(y), header=None)
    codes, names = d.iloc[5], d.iloc[6]
    at = {str(d.iloc[i, 0]).strip(): i for i in range(len(d))}
    for j in range(2, d.shape[1]):
        code = str(codes[j]).strip()
        if code in ('nan', '') or code.startswith('T0'):
            continue
        if pd.isna(pd.to_numeric(d.iloc[at['VABAS'], j], errors='coerce')):
            continue                                    # a final-use column (F...), no value added
        rec = dict(year=y, industry_code=code, industry=str(names[j]).strip())
        for r in rows:
            v = pd.to_numeric(d.iloc[at[r], j], errors='coerce')
            rec[r] = '' if pd.isna(v) else int(v)
        recs.append(rec)
pd.DataFrame(recs).to_csv(out, index=False)
PY
sha256sum bea_use_sut_summary_va_2017_2023.csv
