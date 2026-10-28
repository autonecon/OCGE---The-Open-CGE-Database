# S06 agricultural production targeting (GTAP 12 ch.9A)

Spec for the 2022 build. Precedence: this file, then `PLAN.md` §3 run-order row "S06 | agricultural production targeting (9A) | (b2) FAOSTAT" and plan §3(b2) N1, both as amended by erratum E44, then `data-round/READINESS.md` §1, then the GTAP chapters cited below. There was no `specs/S06_*.md` before this file. Errata E4 and E44 are in `data-round/PLAN_ERRATA.md`. E43 is closed here.

The stage reads the committed S01, S02, S03, S04 and S05 snapshots. It does not rerun them. No raw ICIO, BACI, TRAINS or PSE file is read. GTAP chapter texts are not inputs of the run and are not committed.

## What this stage does

GTAP 12 ch.9A §A.1 p.1: "agricultural production targeting (APT) is a procedure applied to a country's I-O table before the main data construction phase."

GTAP 12 ch.9A §A.1 p.2: "The GTAP 12 Data Base targets agricultural production data from Food and Agriculture Organization (FAO) of the United Nations 2022 for all primary regions (i.e., those for which we have an IOT). The APT procedure is not applied to the composite regions in the GTAP Data Base."

GTAP 12 ch.9A §A.1 p.2: "The targeting covers twelve agricultural sectors (Table 9.1)." Those sectors are PDR, WHT, GRO, OSD, VF, PFB, CB, OCR, CTL, OAP, WOL and RMK. Forestry and fishing are not targeted.

We have one sector, `crp` (ICIO A01, "Crops and livestock"), which covers all twelve. The only GTAP-literal level target would be the A01 total against FAO gross production value, element 57, item 2051 "Agriculture".

David's decision 10 (2026-10-20, E4, `concepts.md` C18), reconfirmed 2026-10-21 04:50 UTC+7 in `config/s06/apt_rule.csv`, is **report-only**. C18: FAO's value is "quantity x producer (farm-gate) price for listed crop & livestock items". ICIO A01 is "basic-price output of ISIC A01 incl. agricultural support services and hunting". The stage computes the ch.9A target and writes it. It changes no cell.

Under `report_only`:

1. For each of the 80 primary tables (the 79 S01 regions with `icio_measured=yes`, plus ISL; not ROW), compute the FAO value, the GDP scale, exports, domestic absorption, the hard/soft test, the adjusted target and the implied change. Write `apt_targets.csv`.
2. For all 167 regions plus ISL, report ICIO/FAO. For the 88 constructed regions, compare donor-derived `crp` with the sum of members' FAO values. ch.9A p.2: APT is not applied to composites.
3. Report the FAO crops and livestock split (items 2041 and 2044). E4 composition. We have no sub-sectors, so the split has nowhere to go in the table.
4. `io_s06.csv.gz` is a byte copy of `io_s05.csv.gz`.

`gtap9a_target` is not built. If that row is set, H2 hard-FAILs with "not built at S06; see ISSUES 'S06 GTAP-literal APT'". The outline, if a later round switches the row:

- Scale the `crp` cost column by `T*/(s·OUT)` and the domestic `crp` sales row (all uses except X) to `T*/s − X`, holding X. How the cells move is not in GTAP text. ch.9A names output, GDP, exports and production taxes, and does not give the cell method.
- Carry the knock-on imbalances in other sectors and final demand as `apt_gap` to S13, the same way the Angola G-revision gap is carried.
- Rebuild the 88 composites from the targeted primaries with S05's stamped `donor_weights.csv`, with no new donor choice. GTAP 12 ch.17B §B.6 p.6: "The final run then restarts the construction workflow using the APT-adjusted regional tables as the authoritative inputs: it re-executes upstream steps as needed to maintain internal consistency under the new targets".

A like-for-like GTAP target would also need a FAO-item to A01-scope map, including agricultural support services and hunting. That map is not in the GTAP text on disk (Chepeliev 2020 is cited and is not an input). It is logged, not invented here.

## The rule

GTAP 12 ch.9A §A.2 p.3: "In some cases, the export and agricultural production targets are simply incompatible. We encounter both hard inconsistencies, where the export target exceeds the production target, and soft inconsistencies, where the export target is lower than the production target, but still leaves very little domestic product available to the domestic market. Since the trade data are central to the whole data reconciliation process, in these cases, it is the production targets, not the export targets, that must give way."

GTAP 12 ch.9A §A.2 p.3: "we deem a soft inconsistency to exist if the production target is less than the export target plus one quarter of the initial level of domestic absorption ... before testing for inconsistencies, we scale the I-O tables to match the GDP target. Having identified the inconsistencies, we then adjust the inconsistent production targets to exports plus one quarter of initial domestic absorption."

GTAP 12 ch.9A §A.2 p.4, the outline: "Clean the I-O tables. — Adjust the tables to match the GDP targets. — Identify inconsistencies between export and production and export targets; adjust the production targets. — Adjust the tables to match export, output subsidy, and agricultural production targets."

The coded rule, which H7 tests on all 20 rows of ch.9A Table 9.3 (p.7):

`threshold = exports + soft_fraction × domestic absorption`

`T* = max(FAO, threshold)`

with `soft_fraction` from `apt_choices.csv` (0.25). Hard if FAO is below scaled exports. Soft if FAO is below the threshold and not hard. Otherwise none. When domestic absorption is non-negative, `T*` equals the GTAP sentence "adjust the inconsistent production targets to exports plus one quarter of initial domestic absorption", because that expression is then at least the export target. The handoff writes the max form. The stage uses that form.

Table 9.2 (p.4), net APT change against GDP-scaled I-O values, over 136 countries: −6.89% in 2023 and −9.52% in 2017. R1 reports our one-sector aggregate beside those two figures. The comparison is report-only. GTAP's figure is twelve sectors; ours is one.

### Not in GTAP text

- How the table cells are changed to hit a target. Logged under "S06 GTAP-literal APT". Not applied.
- The definition of domestic absorption. Tables 9.3 and 9.4 fit "GDP-scaled output − exports" closely (Iraq vegetables, fruit and nuts: scaled output 33,570 − exports 120 = 33,450, against domestic absorption 33,407, 0.13% apart; India other crops is further, about 3%). The choice row sets `DA = OUT − X`, GDP-scaled. The alternative `OUT − X + M` is reported as `DA_alt` and is not used in `T*`.
- The FAO-to-sector item mapping. We use FAO's own aggregate, item 2051, because the twelve Table 9.1 sectors are all crops and livestock and the aggregate does not double-count items. Items 2041 (crops) and 2044 (livestock) are the composition report only.

## Config rows

The stage does not choose. It reads:

| File | What it fixes |
|---|---|
| `config/s06/apt_rule.csv` | One row. `rule` is `report_only` or `gtap9a_target`. `decided_by` required. David, 2026-10-21T04:50+07:00, `report_only`. |
| `config/s06/apt_choices.csv` | Six rows, each with `decided_by` and `decided_at`. Timmy, 2026-10-21. |
| `config/s06/usa_crosscheck.csv` | Optional. USDA census and support-service constants for R3. Not fetched. |

The six choices:

| choice | What the stage does with it |
|---|---|
| `fao_series` | Element 57, current thousand USD, item 2051, divided by 1000 to USD million. |
| `fao_year` | 2022, else the latest earlier year. No row at or before 2022, or a latest year of 1998, is F5 (`APT-F5-NO-TARGET`, no target). Any other year before 2022 is used and flagged `FAO-YEAR-<y>`. |
| `export_target` | The table's own `dom_crp` exports. ch.9A p.3: APT "uses the same macroeconomic and protection data as those used in the final ... construction". Our export total is the ICIO total (plan §3(c) method 1). Trade reconciliation is S07. |
| `gdp_scale` | `s = S02 GDP / table GDP`. Table GDP is the S05-H7 definition: value added plus taxes less subsidies on products, including the TLS that sits on stock change. Used for the test and the target only. The table is not scaled. Scaling is S13 (ch.7 §7.2 p.3). |
| `domestic_absorption` | `DA = s·(OUT − X)`. `DA_alt = s·(OUT − X + M)` is reported beside it. |
| `soft_fraction` | The number in the row. The approved row is 0.25. |

For the 79 ICIO regions, table GDP is read from `io_s05` (VA row, TLS row, TLS `stock_gap`). ISL is not an S05 region. Its VA and TLS come from `io_s04`. Its TLS on stock change is the S03 `tls_on_invnt` total for destination ISL, because that term is in the S05-H7 definition and is not a column of `io_s04`. S03 is an upstream for that one number. S02 GDP for the 79 is `macro_regions.csv`. S02 GDP for ISL is the ISL row of `macro_country.csv` (ISL is a country in XWE, not a region).

Area mapping uses the M49 code in the FAO zip, not the area name alone. `China, mainland` (M49 156) is CHN. `China` (M49 159), which includes Hong Kong, Macao and Taiwan, is not mapped to CHN. Names that do not match an S01 name are listed as aliases in `s06_apt.py` (FAO's official name to the S01 code). That list is a concordance, not a method choice. H4 checks the anchors, including 156 for CHN.

F5 on this file, for ICIO economies: ARE, COD, MMR, STP (1998 only) and TWN. TWN is not filled from the Taiwan yearbook. The yearbook has not been fetched (READINESS F5, still a proposal).

The same year rule is used for members of the 88 when the ratio file sums FAO. A member with no usable year is counted as missing. The missing value is not filled with zero.

## Order (E43 closed)

GTAP 12 ch.8 §8.3 p.3: "Second, agricultural production targets are applied to the majority of I-O tables before the main data construction phase." Composites come "Finally" (p.4).

GTAP 12 ch.17B §B.6 p.5: "the pipeline inserts APT between two make-managed runs of the construction procedure". p.6, the final run "re-executes upstream steps as needed to maintain internal consistency under the new targets".

Under `report_only` the APT-adjusted primaries are the untargeted ones. The S05 composites are what that order produces. H5 is the proof: the table hash is unchanged. If the rule is later switched to `gtap9a_target`, the order does matter, and the composite rebuild above is required.

## Outputs

Written under `dataset/stages/S06_apt/output/` by the stage kit. Each file under 50 MB.

| File | Content |
|---|---|
| `io_s06.csv.gz` | Byte copy of `io_s05.csv.gz`. Not re-gzipped. |
| `apt_targets.csv` | One row per primary table (79 + ISL). Columns: `region, table, crp_OUT, crp_X, crp_M, table_gdp, s02_gdp, gdp_scale, fao_gpv, fao_year, fao_flag, DA, DA_alt, soft_threshold, inconsistency, target_adj, implied_change_pct, applied`. `table` is `io_s05` or, for ISL, `io_s04`. `applied` is `no`. `inconsistency` is `none`, `soft`, `hard` or `no FAO`. `DA` and `DA_alt` are GDP-scaled. `implied_change_pct` is `100·(T*/(s·OUT) − 1)`. |
| `apt_ratio_all.csv` | 167 regions + ISL. Columns: `region, kind, crp_OUT, fao_sum, members_missing_fao, icio_over_fao, crops_share, livestock_share`. `kind` is `primary` or `constructed`. `icio_over_fao` is unscaled `crp` output over the FAO sum. |
| `usa_scrutiny_s06.csv` | USA table, FAO, the USDA cross-check, Puerto Rico's FAO value, and XNA. |

No cell is adjusted, so the ledger has no cell-change row. It has one row per primary, rule `GTAP12-9A-A2-p3-report`, with the target in `after`.

Flags: `APT-REPORT-ONLY` on every primary, `APT-F5-NO-TARGET` on the F5 economies, `APT-SOFT` and `APT-HARD` where the test says so, `FAO-YEAR-<y>` where an earlier year is used, `ISL-IN-XWE` for ISL, and `FAO-MEMBER-MISSING` on each constructed region with at least one member that has no usable FAO value (`needs_david` no).

## Hard checks

The kit adds G0 (one per upstream), G0c, IN1 and IN2. The stage adds H1–H8.

| ID | Check |
|---|---|
| G0 | S01 (`regions.csv`, `sectors.csv`, `country_region_map.csv`), S02 (`macro_regions.csv`, `macro_country.csv`), S03 (`stock_change_gap.csv`, ISL TLS on stock change), S04 (`io_s04.csv.gz`), S05 (`io_s05.csv.gz`, `donor_weights.csv`). |
| IN1, IN2 | The FAO zip is the MANIFEST row `faostat_qv/Value_of_Production_E_All_Data_Normalized.zip`, SHA-256 `14e7b718f1be0dd70e3493aeccb04d2ff2ddc1a39e17a062867f1182a807c422`, 30,326,566 bytes. Year used 2022. |
| H1 | `crp` is the only sector mapped to ICIO A01. The FAO file has element 57 and item 2051. Values are divided by 1000. |
| H2 | One rule row, `decided_by` filled, rule in {`report_only`, `gtap9a_target`}. `gtap9a_target` FAILs. Six choices, each with `decided_by` and `decided_at`. |
| H3 | Exactly 80 primary rows. F5 set is the ICIO economies with no usable FAO year. No constructed region has a target. |
| H4 | `fao_year` is the latest year at or before 2022. CHN is M49 156, not 159. Every ICIO economy is mapped or in F5. |
| H5 | `io_s06.csv.gz` SHA-256 equals `io_s05.csv.gz` SHA-256, `1ca75f628b7a75ba301c466e52b9e96e102d2fdb5329f59f5bf765d7b5c725c5`. |
| H6 | A second path (pandas group-by of `io_s05`, and a long-format group-by of `io_s04` for ISL) recomputes `s`, `X`, `DA`, the threshold and `target_adj`. Absolute difference at most 1e-6. `target_adj` is at least the FAO value whenever both exist. |
| H7 | The coded rule reproduces all 20 adjusted targets in ch.9A Table 9.3 (p.7) from that table's domestic-absorption and export columns, within ±1 USD million. |
| H8 | No NaN in the required numeric columns. No negative FAO value. ISL's `crp` exports equal ISL's `crp` row summed over every other economy's columns. |

## Report-only checks

- R1. Primary ICIO/FAO: median, interquartile range, lowest and highest 10. Net implied change if the target were applied, beside Table 9.2 (−6.89% in 2023, −9.52% in 2017). The hard and soft lists. The same test under `DA_alt`.
- R2. The 88 constructed regions: `crp` against the members' FAO sum, with members missing FAO. ch.9A p.2, report only. The check reports the median over every constructed region that has a ratio, and beside it the median over the full-coverage subset (a ratio, and no missing member).
- R3. USA. Census of Agriculture sales are not production (inventory change, on-farm use). The comparison is approximate. Puerto Rico is in S02 USA GDP and in FAO M49 630, and is not in the ICIO US table (E37). FAO M49 840 excludes Puerto Rico.
- R4. FAO crops and livestock shares.
- R5. Run twice. The second run uses `GTAP_STAGES_DIR=/tmp/s06b` after S01–S05 have been copied there. The two `output/SHA256SUMS` files are byte-identical. This check is the rerun, not a line inside one process.
- R6. E43: S06 changes no cell, so the S05-then-S06 order equals GTAP's APT-then-composites order. H5 is the proof.

## What this stage does not read

Not ICIO, not BACI, not PSE, not the Taiwan yearbook, not the USDA pages (the census and ERS figures are the constants in `usa_crosscheck.csv`). The FAO zip is CC BY 4.0 and is not committed.
