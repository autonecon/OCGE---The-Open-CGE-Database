# Trade prep (BACI re-exports and BaTIS)

Run from this directory, after `fetch_sources.py` has filled `$TRADE_PREP_CACHE`
(default `/tmp/trade-prep`):

```
python3 batis_aggregate.py
python3 baci_reexports.py
```

`fetch_sources.py` downloads the Hong Kong Trade-IDDS tables and the Singapore
SingStat tables. BACI, BaTIS, the CBS extract and the UNSD HS–SITC workbook
are fetched separately into the same cache. See `dataset/prep/trade/FETCH_NOTES.md`.

Outputs go to `$TRADE_PREP_ART` (default `build_cache/trade-baci-batis`)
and the short checks are copied to `dataset/prep/trade/`. Raw downloads are not
committed.
