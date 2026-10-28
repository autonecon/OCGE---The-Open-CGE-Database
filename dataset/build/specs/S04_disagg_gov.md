# S04 I-O disaggregation (9B) and the government consumption check (9C)

Spec for the 2022 build. Precedence: this file, then `PLAN.md` §3 (S04 is "(b1)/(b2)"), then `data-round/READINESS.md` §1, then the GTAP chapters cited below. Errata E39 and E40 are in `data-round/PLAN_ERRATA.md`.

The stage reads the committed S01, S02 and S03 snapshots. It does not rerun them. No raw ICIO, WDI, TRAINS or EXIOBASE file is read. GTAP chapter texts are not inputs of the run and are not committed.

## Order inside the stage

GTAP 12 ch.9C §C.2 p.1: "The procedure is applied after initial cleaning (chapter 8), but before any sectoral disaggregation (chapter 9B)."

GTAP 12 ch.8 §8.3 p.3: "For those that do not, modifications have been made in the construction process to rectify the problem. The procedure is outlined in Chapter 9C."

GTAP 12 ch.8 §8.3 p.4: "Fifth, for the tables that do not have the full 65 sectors, we disaggregate, as described in Chapter 9B."

Step A is the government check (9C). Step B is the sector check (9B). On this classification Step B performs no split.

## Step A. Government consumption (GTAP 12 ch.9C §C.2)

- p.1: "To identify non-compliant tables, the ratio of government consumption to GDP is calculated for each table, and compared to external macroeconomic data."
- p.1: "A table is deemed non-compliant if its ratio of government consumption to GDP is less than half the corresponding ratio in the external data."
- p.1: "We reject the government consumption data for those tables in which the ratios differ by a factor of more than 2."
- p.2: "We note that the IOTs present not only sizable apparent underestimates of government consumption, but also some sizable apparent overestimates." Table 9.6 rejects Luxembourg at 0.42 against 0.16. The test is two-sided: reject when `max(r_table / r_macro, r_macro / r_table) > 2`.
- p.1: "The time series data source used is same to the chapter 7, which combines the WDI data (primary), UN data, and IMF." Chapter 7 in this build is S02. The reference year is 2022 for every ICIO table. The macro row is the country row. `G_source` is reported.

Both sides are purchasers' prices.

- `r_table` = (cleaned `g` column at basic prices + the TLS row on `g`) / ICIO GDP.
- ICIO GDP is VA + TLS as published, the S03 `macro_comparison.csv` column `icio_gdp`. Removing INVNT does not change that published GDP. The denominator stays this S03 figure after a revision, including when TLS on `g` changes.
- `r_macro` = S02 `G_musd / GDP_musd`.

Coverage is the 80 ICIO economy tables, ISL included. ROW is not a table. It is opened at S05.

The government-services share in G (Table 9.6, last column) is `gov` + `edu` + `hea` over basic G. GTAP 12 ch.9C p.2: "(GTAP commodity osg, edu and hht)". GTAP sets no threshold on this share. It is report-only.

## Step B. Sectoral classification (GTAP 12 ch.9B)

- ch.9B §B.1 p.1: "Where the contributed table uses an aggregated classification, we must disaggregate it to the standard GTAP sectors in-house."
- ch.9B §B.3 p.3: "The additional detail that we require is obtained by using the representative table."
- ch.9D §D.1 p.2: "For sectors that are not disaggregated in the original I-O table, the structure of production, intermediate usage, and consumption are adapted from the representative table." Cite 9D from its own chapter, not from the pages bundled at the back of the 9C PDF.

Our standard sectors are the 51 rows of S01 `sectors.csv`. Every ICIO table already has the same 50 industries. The only split from those 50 to our 51 is B06 into `oil` and `gas`, and that split is `deferred:S11` (`concord_icio_to_sector.csv`; PLAN (b1) item 7). Agriculture is one sector (`crp`, ICIO A01), so ch.9B §B.2 (the FAO agricultural and food split) does not apply.

S04 performs no sector split. It does not split B06. It does not copy the representative table onto any cell in Step B. The READINESS gate "Sector splits sum back to the parent cell exactly" holds with zero splits, and the stage records 0.

## Rejected tables (config)

GTAP 12 ch.9C states the rejection test and does not state the revision. The revision is GTAP 8 ch.8.E p.3 (Aguiar, McDougall and Kharitonov):

> "We aggregate the representative table (see chapter 8.F) to the same sectoral classification as the contributed table, and calculate the sectoral composition of government consumption at that aggregation. We then adjust the contributed table, so that the ratio of government consumption to GDP matches the macroeconomic time-series data set, and the sectoral composition of government consumption as in the representative table."

`dataset/build/config/s04/gov_revision.csv` has columns `economy,action,decided_by,decided_at,note`. `action` is `revise` or `report_only`. The reject set (fold > 2, two-sided) must equal the economies in that file. An economy the check did not reject is a hard FAIL (H3). A rejected economy with no row is a hard FAIL.

Decision recorded for this build: Angola `revise`. David did not pick that row. `decided_by` is Timmy, applying GTAP 8 ch.8.E p.3 under David's standing GTAP-method rule (2026-10-20/21).

`revise` (GTAP 8 ch.8.E p.3):

- New purchasers' G = `r_macro ×` S03 ICIO GDP.
- Product composition and the TLS-on-`g` share come from the representative table, built the S03 way. Each member's `g` column divided by its GDP, then weighted by its GDP share, equals the plain sum of the member USD columns (S03-H10). The file `rep_g_composition.csv` records domestic, imported and TLS from that plain sum. It is written on every run. Only `revise` uses it.
- The domestic/imported split of each product in the revised table is the revised economy's own import share of that product across all of its users. Source countries inside the imported total follow that same all-users import pattern. GTAP 8 ch.8.E p.3 does not state this partner split; the handoff does. No other source is used.
- Nothing else in the table changes. VA, OUT, and TLS outside the revised `g` column stay as read. Other economies' columns stay as read.
- The change in each product row's sales is a G-revision gap (`gov_revision_gap.csv`), one ledger row per changed cell, rule `GTAP8-8E-p3`, flag `G-REVISE-9C`. GTAP does not say how the rest of the table absorbs the change. Leaving the gap for the S13 fit is our choice where the text is silent (E40).

`report_only`: no cell changes. Flag `G-REJECT-9C`. Not used for Angola.

## Representative table built at S03 (E39)

GTAP 12 ch.8 §8.3 p.3: "Fourth, having cleaned the I-O tables as required, we take those that have the full 65-sector GTAP sectoral classification and calculate from them a representative table". This build calculated it at S03, before 9C. That is harmless only when no member of the 41 is rejected. H4 tests that. If a member is rejected, stop. Do not rebuild S03 in this stage.

## Left for later stages

- B06 to oil and gas: S11. The representative table has B06 as one sector, so it cannot give oil a different cost structure from gas (logged for S11).
- Composite tables, non-ICIO tables, ISL into XWE, opening ROW: S05. GTAP 12 ch.8 §8.3 p.4: "Finally, for each region where we have no contributed table, we calculate a composite table". Donor tables are not an input. Do not merge `prep/donor-tables`.
- DPABR stays its own column until S09.
- TLS basic to purchasers' split: S10. VA factor split and labour: S12. Stock-change gap: S13.
- C, G and I scaling to macro: S13–S14. S04 scales G only for a rejected table whose action is `revise`.

## Outputs

Written under `dataset/stages/S04_disagg_gov/output/` by the stage kit. Each file under 50 MB.

| File | Content |
|---|---|
| `io_s04.csv.gz` | Same wide layout as S03 `io_cleaned.csv.gz`. Deterministic gzip (`mtime=0`, empty filename). The table S05 reads. |
| `gov_consumption_check.csv` | 80 rows: `economy, rep_member, g_basic, g_tls, G_table, icio_gdp, s02_G, s02_GDP, G_source, r_table, r_macro, factor, fold, result, govsvc_share, action`. |
| `rep_g_composition.csv` | Representative G by product: domestic, imported, total, share, and a TLS row. |
| `sector_classification_check.csv` | Per economy block: labels found, missing, extra, splits (0). |
| `gov_revision_gap.csv` | Under `revise` only. Change in each product row's sales, and the TLS-on-`g` change. |
| `usa_scrutiny_s04.csv` | USA 9C ratios, G composition against the representative composition, H1 residuals, cells changed. |

## Tolerance

`io_cleaned.csv.gz` is written to 4 decimals, so a sector identity on the file holds only up to rounding. Every identity that reads it uses absolute difference ≤ 0.05 USD million or relative difference ≤ 1e-9.

Sales in that identity are the cleaned product row plus the S03 stock-change gap. Costs are intermediate purchases plus TLS plus VA. Published OUT is the OUT column. S03 removed INVNT from the rows and left OUT at published output, so the gap has to be added back before the three-way balance is the rounding residual.

## Hard checks

G0, G0c, IN1 and IN2 come from the kit. The rest are `S.check(..., 'hard', ...)`. STAMP only if every hard check PASSes and `dataset/build` is committed. A hard FAIL exits 1.

| ID | Check |
|---|---|
| S04-G0 | Three upstreams: S01, S02, S03. Each STAMP present, SHA256SUMS bound to that STAMP, and every file read from `output/` matching. Registered reads: S03 `io_cleaned.csv.gz`, `use_domestic_imported.csv`, `macro_comparison.csv`, `representative_weights.csv`, `stock_change_gap.csv`; S02 `macro_country.csv`; S01 `sectors.csv`, `concord_icio_to_sector.csv`. The stock-change gap is read because the rounded balance identity needs it. |
| H1 | S03 table as read: for every block × sector, sales + stock-change gap = costs = published OUT, within the tolerance. Max residual, and the USA residual, are shown. |
| H2 | `r_table` and `r_macro` for all 80 economy tables. ISL in, ROW out. No NaN, no zero denominator. Both purchasers' prices. |
| H3 | Reject set equals `config/s04/gov_revision.csv`. Each row's `decided_by` is Timmy applying GTAP 8 ch.8.E p.3 under David's standing rule, and `action` is `revise` or `report_only`. |
| H4 | No economy with `in_representative_table` = yes in S03 `representative_weights.csv` is rejected. |
| H5 | Every economy table has the 50 labels (S01 sectors with `oil`+`gas` as `B06`). Concordance shares are 1 except B06 (`deferred:S11`). Splits performed = 0. |
| H6 | `io_s04` equals `io_cleaned` cell for cell after reading (abs ≤ 1e-9), except cells with a ledger row. Ledger rows equal the changed-cell count. Under `report_only` both are 0. |
| H7 | Under `revise`, for each revised economy: post-revision `r_table` = `r_macro` (rel 1e-9) on the S03 ICIO GDP; basic product shares and the TLS share equal `rep_g_composition` (abs 1e-9); VA, OUT and TLS outside `g` are unchanged; the gap equals the change in that row's sales; every column other than the revised `g` column is unchanged. Under `report_only`, PASS "not applicable". |
| H8 | No NaN. Negatives only where S03-H8 allowed them: TLS subsidies, and VA in CYP air (H51) and ISL pharmaceuticals (C21). Count them and list them. |

## Report-only checks

- R1. The 80-row 9C table, sorted by fold, with accept or reject.
- R2. Government-services share for all 80, and the 10 lowest. No threshold, so no action.
- R3. Economies with fold from 1.5 to 2.0.
- R4. USA: ratios, composition gaps, H1 residuals, and the count of changed USA-table cells (expect 0).
- R5. Run the stage twice, the second with `GTAP_STAGES_DIR=/tmp/s04b`, and confirm the two `output/SHA256SUMS` files are byte-identical. Recorded in `REVIEW_BRIEF.md`.
- R6. After `revise`, the per-product sales gap against published output, the largest rows, and the total gap as a share of that economy's ICIO GDP. Report only. No cell changes.

G0c lists build files changed since S03's stamp commit `1da2b10`. The S04 script and this config are expected there. The S01 and S02 stamp commit `5ddbe4d` is outside this repo, so that G0c count stays 0.
