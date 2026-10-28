# Census PR and VI statehs extracts, CY2022

Public US Census Bureau International Trade timeseries. Annual, `time=2022-12` (the year-to-date field is the full year), HS6 (`COMM_LVL=HS6`). No API key is stored in this folder.

| File | Endpoint | State | Value field |
|---|---|---|---|
| `pr_exports_statehs_hs6_2022.json` | `exports/statehs` | PR | `ALL_VAL_YR` (f.a.s.) |
| `pr_imports_statehs_hs6_2022.json` | `imports/statehs` | PR | `GEN_VAL_YR` (customs) |
| `vi_exports_statehs_hs6_2022.json` | `exports/statehs` | VI | `ALL_VAL_YR` |
| `vi_imports_statehs_hs6_2022.json` | `imports/statehs` | VI | `GEN_VAL_YR` |

The queries, without a key:

- https://api.census.gov/data/timeseries/intltrade/exports/statehs?get=STATE,CTY_CODE,CTY_NAME,E_COMMODITY,ALL_VAL_YR&STATE=PR&time=2022-12&COMM_LVL=HS6
- https://api.census.gov/data/timeseries/intltrade/imports/statehs?get=STATE,CTY_CODE,CTY_NAME,I_COMMODITY,GEN_VAL_YR&STATE=PR&time=2022-12&COMM_LVL=HS6
- the same two queries with `STATE=VI`

`fetch_census_2022.py` reads `CENSUS_API_KEY` from the environment and does not write or print it. The stage does not run the script. The four JSON files above are the extracts the carve uses. The script also names two import-charge queries that belong to a later stage. Those files are not in this folder.

Each JSON file is the API table: a header row, then data. `CTY_CODE='-'` is the per-HS total (`CTY_NAME` is TOTAL FOR ALL COUNTRIES). Summing that code across HS6 equals the sum of country rows, Schedule C `CTY_CODE` 1000–7999. Group rows are neither. The Puerto Rico export total on `CTY_CODE='-'` is 20,590,166,862 USD.

The partner-by-sector file the carve reads is `dataset/data/census_statehs_2022/census_pr_vi_2022_by_partner_sector.csv`. S07 re-derives that file from these JSON extracts and checks the two. The bridge steps are in that folder's README. The API totals and the Planning Board figures are in `dataset/build/config/s07/census_controls.csv` and `dataset/build/config/s07/pri_planning_board.csv`.

Licence: US government work, public domain. Redistributable.
