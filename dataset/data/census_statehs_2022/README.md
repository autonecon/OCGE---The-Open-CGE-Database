# Census PR and VI merchandise trade, CY2022

Public US Census Bureau data, International Trade timeseries, calendar year 2022 (`time=2022-12`, year-to-date is the full year), HS6 (`COMM_LVL=HS6`). No API key is stored in this folder or in the queries below.

The raw API tables are `dataset/data/census_state_trade_2022/` (`pr_` and `vi_` exports and imports, statehs, HS6, JSON). `fetch_census_2022.py` in that folder reads `CENSUS_API_KEY` from the environment only. S07 does not run it. S07 re-derives the partner-by-sector file from those JSON tables and checks it.

Exports use `exports/statehs`, field `ALL_VAL_YR` (total value, f.a.s.):

- https://api.census.gov/data/timeseries/intltrade/exports/statehs?get=STATE,E_COMMODITY,CTY_CODE,CTY_NAME,ALL_VAL_YR&STATE=PR&time=2022-12&COMM_LVL=HS6
- the same query with `STATE=VI`

Imports use `imports/statehs`, field `GEN_VAL_YR` (general imports, customs value):

- https://api.census.gov/data/timeseries/intltrade/imports/statehs?get=STATE,I_COMMODITY,CTY_CODE,CTY_NAME,GEN_VAL_YR&STATE=PR&time=2022-12&COMM_LVL=HS6
- the same query with `STATE=VI`

The API takes the postal codes PR and VI, not FIPS 72.

Country rows are Schedule C `CTY_CODE` 1000–7999. Group rows are dropped. `CTY_CODE='-'` is the per-HS total (TOTAL FOR ALL COUNTRIES). Summed across HS6 it equals the country-row sum, in dollars. The stage checks that equality.

Countries: Census Schedule C (https://www.census.gov/foreign-trade/schedules/c/country.txt), then ISO3, then S01 `country_region_map.csv`. A Census label that does not match an S01 name is in `dataset/build/config/s07/census_schedule_c_aliases.csv` (28 labels, name normalization only). Guadeloupe, Martinique, French Guiana and Réunion (GLP, MTQ, GUF, REU) go to FRA. The Holy See (VAT) goes to ITA. Those five overrides are `dataset/build/config/s07/census_partner_overrides.csv`. They sit inside BACI's France and Italy. The partner is the ISO3 itself when that code is one of the 79 ICIO regions or ISL. Otherwise it is the S01 region (a composite, or the country's own region). ISL stays ISL.

Sectors: the 2022 codes are HS2022. They are bridged by S01 `concord_hs22_to_sector.csv`, share-weighted. Every mapped code in that file has share 1. The empty `999999` row has no sector. Chapter 98 is not in the concordance, so it is `unmapped`. The non-S07 sectors `wat`, `pub`, `art` and `ely` are kept in the census file and dropped by the carve. The exclusion list and the 650 USD million cap are `dataset/build/config/s07/census_controls.csv`, with the four API totals.

Values in the CSV are USD million, four decimal places. A re-derived cell under 0.0005 USD million is absent from the CSV. The carve reads this CSV. It does not replace it with the re-derivation.

The API totals (USD million) are PR exports 20590.2, PR imports 26914.9, VI exports 2100.4, VI imports 822.8. The Planning Board FY2022 figures are a different source. They live in `dataset/build/config/s07/pri_planning_board.csv`. The 44.62 USD billion of shipments to the United States is separate from the 14.84 USD billion of foreign exports.

- `census_pr_vi_2022_by_partner_sector.csv` is the stage input: `state`, `direction`, `partner_s01`, `icio_partner`, `sector`, `census_musd`.
- `pr_vi_carve_icio_partners.csv` is a cross-check prepared against `pri_row_gap.csv` of build `03cbda9`. It is derived from Census, ICIO and BACI aggregates. The stage recomputes the carve from the census file and the live ICIO and cleaned-BACI gaps. It does not copy the carve amounts from this file.

Licence: US government work, public domain, for the Census extract. The carve cross-check is derived (Census + ICIO + BACI aggregates). Redistributable.

Re-derived 2026-10-25 after fix B13 (HS 4707, 7204, 7404, 7602 scrap moved from `wat` to `pap`, `stl`, `nfm` in the S01 concordance) with `regen_by_partner_sector.py`, which calls the S07 re-derivation; cells that moved only by the last-digit rounding keep their earlier value. Re-derived again 2026-10-25 after Fable QA F-12 (HS 7112 precious-metal scrap from `wat` to `nfm`): 10 cells change, all `wat` or `nfm`.
