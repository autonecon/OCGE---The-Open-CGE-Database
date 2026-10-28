# IMF World Revenue Longitudinal Database (WoRLD), general/central government revenue by GFS tax category

- **Folder:** `data/imf_world/`
- **Source page:** [https://data.imf.org/en/datasets/IMF.FAD:WORLD](https://data.imf.org/en/datasets/IMF.FAD:WORLD)
- **Download URL / API:** https://api.imf.org/external/sdmx/2.1/data/IMF.FAD,WORLD,/all?startPeriod=2017&endPeriod=2022 (SDMX-CSV)
- **Version:** WORLD dataflow 3.0.1, updated 2026-02-18
- **Download date / origin:** 2026-10-21 refetch. The 2026-10-20 file (sha `e07bf23a`, 3,032,791 bytes) is not what the API returns now. The refetch uses `Accept: application/vnd.sdmx.data+csv;version=1.0.0`.
- **Licence:** IMF terms of use (free reuse with attribution)
- **Coverage (2022 or year-rule fallback):** income tax G111 (% of GDP) at 2022 for 151 of 159 single economies; fills 34 of the 41 OECD GRS gaps (incl. IND RUS SAU ARE QAT OMN IRN IRQ); still missing BHR CUW PRK PYF KWT NCL SYR
- **Units:** percent of GDP
- **Valuation basis / concept:** GFS 2014 cash/accrual as reported; general or central government (SECTOR column)
- **How it is used (PLAN.md stage):** Stage (f): income and factor taxes (GTAP 12 ch.15 uses IMF GFS + OECD GRS; WoRLD is the IMF revenue compilation built on GFS).

## Files

| File | Bytes | SHA-256 |
|---|---|---|
| `imf_world/imf_world_2017_2022.csv` | 22,336,660 | `2d5f24a992e87845958490e799c3c5781754d2d867f0b254b9a58ee680c275d8` |

Per-file URLs are in `data/MANIFEST.csv`.
