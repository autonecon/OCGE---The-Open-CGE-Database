# WITS TRAINS earlier-year UNCTAD AVEs for the S10 lines at or above 1,000%

**NOT FOR PUBLICATION.** WITS/TRAINS terms: internal use only. Private repo only.

Public WITS SDMX API, the same endpoint family that produced `trains_internal/trains_mfn_894_2021_aveestimated.xml`:
`https://wits.worldbank.org/API/V1/SDMX/V21/datasource/TRN/reporter/<M49>/partner/000/product/<HS6>/year/<year>/datatype/aveestimated` (and `/datatype/reported` for the two Egypt `_reported` files).

One file per importer, HS6 and year, 2014–2016, for the 38 AVE-sourced lines at or above 1,000% with 2022 trade (list in `dataset/reviews/S10R/rebuild_prep/ave_ge1000_lines.csv`). Years 2017–2022 for these lines are already in `wits_trains_bulk_2017_2022/trains_mfn_ave_2017_2022.zip`. Only HTTP 200 responses are kept; a 404 (no data for that year) is recorded in `ave_ge1000_lines.csv` and not saved. For H6 lines the query code is the HS2017 code, then the UNSD HS2012 code. Fetched 2026-10-22 (UTC+7) without a login.
