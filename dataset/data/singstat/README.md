# singstat: Singapore Department of Statistics, merchandise trade by market (SingStat Table Builder API)

Used by the S07 re-export prep (`dataset/build/prep_trade/`). SingStat open data terms (free reuse with attribution).

| File | Table |
|---|---|
| M451521.json | total merchandise exports by market, 12 months of 2022 |
| M451501.json | domestic exports by market, 12 months of 2022 |
| M451001.json | commodity sections (series 3.x/4.x/5.x), diagnostic only |

First fetched 2026-10-21; refetched and committed 2026-10-23 with `fetch_trade_prep_sources.py singstat`.
The API writes the fetch date into `Data.dateGenerated`. The script sets it to 21/10/2026, the date of the pinned
copy (env `SINGSTAT_DATE_GENERATED`), so the SHA-256 values match the pins. All other content is as served.

`M451001_imports.json` (added 2026-10-23, S07 retained-import step): M451001 series 2 (total merchandise imports and
its commodity sections), 12 months of 2022, from
https://tablebuilder.singstat.gov.sg/api/table/tabledata/M451001 with `seriesNoORrowNo` set to the series-2 rows.
Content as served, including that day's `Data.dateGenerated`.
