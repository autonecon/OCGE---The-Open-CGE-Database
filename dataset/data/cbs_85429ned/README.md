# cbs_85429ned: Statistics Netherlands table 85429NED (cross-border goods trade)

Used by the S07 re-export prep (`dataset/build/prep_trade/`). Licence CC BY 4.0 (Statistics Netherlands).

| File | Query |
|---|---|
| typed_2022.json | `https://opendata.cbs.nl/ODataApi/odata/85429NED/TypedDataSet?$format=json&$filter=Perioden eq '2022JJ00'`, re-serialised as `{"value": [...]}` |
| landen.json | `.../85429NED/Landen?$format=json` (raw bytes) |
| sitc.json | `.../85429NED/SITC?$format=json` (raw bytes) |

First fetched 2026-10-21. The files were then in no commit, so they were refetched and committed on 2026-10-23
with `dataset/data/fetch_trade_prep_sources.py cbs`. The SHA-256 values match the MANIFEST pins.
