#!/usr/bin/env python3
"""Fetch public US Census international trade extracts for 2022 (annual, time=2022-12).
Key is read from env CENSUS_API_KEY only; it is never written or logged."""
import os, json, sys, urllib.request, urllib.parse
KEY = os.environ["CENSUS_API_KEY"]
BASE = "https://api.census.gov/data/timeseries/intltrade/"
Q = {
 # S08: US import charges by HS6 (all modes, air, vessel)
 "imports_hs_hs6_charges_2022.json": ("imports/hs", {"get":"I_COMMODITY,GEN_VAL_YR,GEN_CHA_YR,AIR_VAL_YR,AIR_CHA_YR,VES_VAL_YR,VES_CHA_YR","time":"2022-12","COMM_LVL":"HS6"}),
 "imports_hs_hs2_cty_charges_2022.json": ("imports/hs", {"get":"I_COMMODITY,CTY_CODE,CTY_NAME,GEN_VAL_YR,GEN_CHA_YR,AIR_VAL_YR,AIR_CHA_YR,VES_VAL_YR,VES_CHA_YR","time":"2022-12","COMM_LVL":"HS2"}),
 # S07 carve: PR and VI foreign trade by partner x HS6
 "pr_exports_statehs_hs6_2022.json": ("exports/statehs", {"get":"STATE,CTY_CODE,CTY_NAME,E_COMMODITY,ALL_VAL_YR","STATE":"PR","time":"2022-12","COMM_LVL":"HS6"}),
 "pr_imports_statehs_hs6_2022.json": ("imports/statehs", {"get":"STATE,CTY_CODE,CTY_NAME,I_COMMODITY,GEN_VAL_YR","STATE":"PR","time":"2022-12","COMM_LVL":"HS6"}),
 "vi_exports_statehs_hs6_2022.json": ("exports/statehs", {"get":"STATE,CTY_CODE,CTY_NAME,E_COMMODITY,ALL_VAL_YR","STATE":"VI","time":"2022-12","COMM_LVL":"HS6"}),
 "vi_imports_statehs_hs6_2022.json": ("imports/statehs", {"get":"STATE,CTY_CODE,CTY_NAME,I_COMMODITY,GEN_VAL_YR","STATE":"VI","time":"2022-12","COMM_LVL":"HS6"}),
}
out = sys.argv[1] if len(sys.argv) > 1 else "."
for fn, (ep, params) in Q.items():
    url = BASE + ep + "?" + urllib.parse.urlencode({**params, "key": KEY}, safe=",")
    try:
        with urllib.request.urlopen(url, timeout=300) as r:
            data = json.loads(r.read())
        with open(os.path.join(out, fn), "w") as f: json.dump(data, f)
        print(f"{fn}: {len(data)-1} rows (endpoint {ep}, params {params})")
    except Exception as e:
        print(f"{fn}: FAILED {type(e).__name__}")
