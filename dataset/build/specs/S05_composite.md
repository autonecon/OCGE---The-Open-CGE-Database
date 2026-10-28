# S05 composite and non-ICIO I-O tables (GTAP 12 ch.9D §D.3)

Spec for the 2022 build. Precedence: this file, then `PLAN.md` §3 run-order row "S05 | composite and non-ICIO tables (9D §D.3) | (b2)" and plan section (b2) as narrowed by erratum E41, then `data-round/READINESS.md` §1, then the GTAP chapters cited below. Errata E41, E42 and E43 are in `data-round/PLAN_ERRATA.md`.

The stage reads the committed S01, S02, S03 and S04 snapshots. It does not rerun them. No raw ICIO, WDI, TRAINS or EXIOBASE file is read. GTAP chapter texts are not inputs of the run and are not committed.

Cite chapter 9D only from its own file (GTAP 12, resource 7910). The chapter 9C PDF bundles an older-release copy of 9D. That copy's counts (141 contributed tables, 19 composite regions) are not the GTAP 12 text.

## What this stage builds

Every one of our 88 regions without an ICIO table is a GTAP composite region. An 80-economy single region is a composite with one member and weight 1. The primary regions are the 80 ICIO economy tables in `io_s04` (ISL included, ROW excluded). ISL is not a region. Its table enters XWE as a member.

S01 has 80 non-ICIO single regions plus 8 composites, which is 88 tables. The "81" in READINESS is an older count. The 79 ICIO single regions are converted to the same single-region form and are not scaled. Together that is 167 regions. GTAP 12 ch.8 §8.3 p.4: "At this point we have a set of tables covering all GTAP regions and the IOTs are ready to be incorporated into the GTAP Data Base and reconciled with the other macroeconomic datasets."

## Donor rule (one config row)

`dataset/build/config/s05/donor_rule.csv` has columns `rule,decided_by,decided_at,note`. `rule` is one of `pr71_chosen`, `pr71_gtap9d`, `gtap15_gdppc`. The stage reads that row. It does not choose.

David (2026-10-21 03:23 UTC+7) set `gtap15_gdppc`. The note is: Literal GTAP 9D rule; PR #71 four-block method logged as improvement for a later round.

`gtap15_gdppc` is GTAP 12 ch.9D §D.3 p.3 step 1 and §D.2 p.2, applied literally. Nearest GDP per capita, using the income concept PR #71 already stored (PPP where that file used PPP, otherwise market), inside GTAP's 15 composite-construction regions. Latin America is Caribbean + Central America + South America. Sub-Saharan Africa is Eastern + Central + Western + Southern Africa. Every member of those regions uses the wider pool, including members whose 19-region pool is not empty.

`pr71_chosen` is PR #71's four-block mean rank (income, value-added shares, resource rents, trade openness) inside the 19-region pool, widened only when that pool has no ICIO table (Caribbean, Eastern Africa). It is the matching aim in ch.8 §8.3 p.4 ("income level and production pattern"). It is not the ch.9D steps. It stays available: switching later is this one config row.

`pr71_gtap9d` is nearest GDP per capita inside those same PR #71 pools.

Under `pr71_chosen` or `pr71_gtap9d`, a PR #71 row keeps that file's donor. The stage does not refit the four blocks.

### GTAP text

GTAP 12 ch.9D §D.3 p.3: "In constructing an I-O table for a composite region, we start by associating a primary region to each of the member countries in a composite region. The steps involved in the procedure are:

- all the 251 standard countries are matched on the basis of similarity in GDP per capita with a primary region within the same geographic region
- the target total GDP is generated for each composite region; this is the sum of GDP for the individual countries comprising the composite region
- the primary regions matching the countries in the composite region in terms of similarity in GDP per capita are noted and GDP weights (ratio of country GDP to total target GDP) are assigned to each primary region
- the I-O table for each composite region is constructed by combining the I-O data from the primary region tables summed according to the GDP share weights."

GTAP 12 ch.9D §D.3 p.3: "The IOTs for the composite regions are then updated and adjusted to match aggregated regional data on macroeconomic aggregates, trade, protection, and energy in the FIT procedure documented in chapter 15.A." In GTAP 12 numbering that FIT chapter is 17A. It is our S13. S05 does not run it.

GTAP 12 ch.9D §D.3 p.3: "Further we assume here that the average patterns of production, consumption, and savings in any individual country in the 18 composite regions can be approximated by patterns observed in one of its neighboring primary regions."

GTAP 12 ch.9D §D.2 p.2: "Because of the constraint imposed by the unavailability of a single I-O table for any of the countries included in a geographic region such as the Caribbean, a smaller set of 15 geographic regions is used in constructing the composite regions. This was done by classifying the Caribbean, Central America, and South America together as the larger Latin America region and defining the larger Sub-Saharan Africa region as composed of Eastern Africa, Central Africa, Western Africa, and Southern Africa."

GTAP 12 ch.7 §7.2 p.3: "Similar per capita GDP is used as a criterion for matching a member country in a composite region to one of the primary regions within the same geographic area. A combination of one or more primary region I-O tables is then used to generate an I-O table for a composite region."

GTAP 12 ch.7 §7.2 p.3, on scaling: "all the coefficients in the regional I-O tables, initially in national currency units, are scaled-up by the ratio of gross domestic product (GDP) calculated from the I-O tables to external GDP data in current US dollars."

GTAP 12 ch.8 §8.3 p.4: "Finally, for each region where we have no contributed table, we calculate a composite table, as a linear combination of I-O tables for selected primary regions. We make a different selection of primary regions for each composite region, matching as closely as possible the composite region's income level and production pattern, as described in Chapter 9D."

### Candidates, fills, zeros

Candidates are the 80 ICIO economy tables except TWN. TWN has no PPP row in the SHA-checked PR #71 file (`unscored_icio_donors`). Never ROW. Never a composite.

Distance is the absolute log difference of GDP per capita. A tie breaks toward the larger donor GDP, then the code, so the result does not depend on row order.

Codes with S02 GDP > 0 and no PR #71 income data take the nearest donor by S02 GDP per capita (`GDP_musd / POP`, market USD) inside the rule's pool. Flag `DONOR-S02-GDPPC`. Where S02's GDP is itself a per-capita fill, the flag also says so (`F1-PER-CAPITA-FILL`). GTAP's step 1 covers "all the 251 standard countries", so these codes stay in the composite while their GDP sits in the S02 region total.

Codes with S02 GDP = 0 have weight 0 and no donor. GTAP 12 ch.7 p.2: "there was no data on GDP or sometimes population, so we assume and assigned a zero value for these territories."

Iceland in XWE uses its own ICIO table as its primary region (S01: XWE `partly: ISL`). Flag `ISL-IN-XWE`.

Every member keeps the PR #71 flag tokens (`weak_match`, `gdppc_gap`, `widened_region`, and the rest of that file's flag string). The S05 donor's GDP per capita ratio is tested against PR #71's 3× gate (`|ln(donor/target)| > ln(3)`). Past the gate, the member carries `gdppc_gap`. The stage does not act on it.

`dataset/build/config/s05/oil_check_codes.csv` is the post-energy oil and gas check list. Columns `code,flag,decided_by,decided_at,reason,evidence,note,resolved_by,resolved_at,resolution`. Every row has `decided_by`, `decided_at`, `reason` and `evidence`. The flag is `OIL-CHECK-POST-ENERGY` (open) or `OIL-CHECK-RESOLVED`. The flag does not change the donor. David (2026-10-20) listed IRQ, KWT, OMN, AZE and COG. Timmy (review finding, 2026-10-21) added GAB, GNQ, BHR and TCD (oil and gas rents of about 16–22% of GDP, GAB 15.8%, on non-oil donors) and CPV, NAM and SWZ (they inherit AGO's 28.8% oil and gas value-added share). Since B8 (below) the nine of them whose B06 column is switched are `OIL-CHECK-RESOLVED`, with `resolved_by` David, `resolved_at` 2026-10-24. An open row may not be a switched member, and a resolved row must be one (the stage refuses to run otherwise). CPV, NAM and SWZ stay open.

### Oil and gas donors for the B06 column (B8)

David's card (2026-10-24, fix list B8) reopens his 2026-10-20 "no oil donor override" choice. This is our own choice and a departure from the literal 9D rule (IMPROVEMENTS_LOG S05-1). `dataset/build/config/s05/oil_donors.csv` has columns `code,base_donor,oil_donor,sector,decided_by,decided_at,basis,note`, one row per member, sector always `B06`:

| Oil donor | Members (9D donor) |
|---|---|
| SAU | IRN (IND), IRQ (JOR), KWT (CYP), OMN (TUR), LBY (TUN), BHR (CYP), SYR (JOR), YEM (JOR) |
| KAZ | AZE (TUR) |
| AGO | COG (CIV), GUY (CHL), GNQ (ZAF), GHA (CIV), GAB (ZAF), TCD (COD) |
| BRN | TTO (CHL), PNG (NZL), TLS (MMR) |

The rule behind the table: the member is an oil and gas economy and its 9D donor has oil and gas output below 10% of GDP. QAT (ARE), TKM (KAZ), DZA (EGY) and VEN (COL) keep their donor, which is already an oil economy. `base_donor` must equal the donor the 9D rule gives; if the rule changes, the stage stops.

The B06 column is the one replaced because S11 splits it into oil and gas with every non-B06 input shared pro rata (`s11_energy/method.split_b06`), so both new columns inherit its cost shares. The swap (`s05_composite/oil.py`) is made on the member's donor table before the GDP scaling:

- The B06 column takes the oil donor's cost shares: each domestic and imported input, TLS and VA over output. A product the 9D donor does not produce at home is bought as an import.
- Every other sector column keeps the 9D donor's cost shares. Final demand, exports, `stock_gap` and `grev_gap` keep the 9D donor's cells.
- Sector outputs are solved again from the domestic product rows, x' = A'x' + f, where f is the 9D donor's row remainder (final uses, exports, stock_gap − grev_gap and the carried 4-decimal row residual). Every domestic row keeps its donor residual, and every column keeps cost = output up to its donor's residual.
- The member's GDP weight then uses this table: `T_R = Σ_m GDP_m × T'_m / GDP(T'_m)`, so H7 holds as before.

AGO as an oil donor gives only the B06 column; the Angola G-revision gap travels only with the 9D donor (H8). The B06 output level stays small (the 9D donor's); S11 and S13 set the energy output. Members carry the flag token `OIL-DONOR-B06-<donor>`.

EXIOBASE stays report-only (E26). It is not read at S05.

## Members, weights, construction

For each of the 88 target regions, the members are all S02 `macro_country.csv` codes whose `region` is that target. Territories that S01 put in a composite and S02 gives a GDP are members. GTAP step 2: "the sum of GDP for the individual countries comprising the composite region".

Weight `w_m = GDP_m / Σ GDP` from S02, current USD, 2022. PR #71 `composite_donor_weights.csv` is not the weight. Those weights are WDI-based, they leave territories out, and Cuba there uses WDI 2017 where S02 has the UNSD AMA figure.

No code whose S01 region is an ICIO economy gets a donor or a weight. That list includes PRI and VIR (USA), CHI, GGY, JEY, IMN and SHN (GBR), and ATF (FRA). E37: no PRI or VIR table.

### Donor table in single-region form

For donor economy `d` in `io_s04`:

- Domestic product `x` by agent = row `d_x`, column `d_agent`.
- Imported product `x` by agent = the sum over origins other than `d`, including ROW, of row `o_x`, column `d_agent`.
- Exports of `x` = row `d_x` summed over every agent column of every economy other than `d`, including ROW.
- TLS by agent = the TLS row, columns `d_*`. VA and OUT by sector from the VA and OUT rows, columns `d_<sector>`.
- Agents are the 50 sector labels (B06 unsplit) plus `p`, `g`, `i`, `dpabr`.

Carried gaps, columns `stock_gap` and `grev_gap`. Nothing is plugged.

- `stock_gap` on domestic rows: sum over destinations of S03 `stock_change_gap.csv` rows with origin `d`, sector `x`, kind `product`. On import rows: rows with destination `d` and origin other than `d`. On the TLS row: `tls_on_invnt` with destination `d`.
- `grev_gap` comes from S04 `gov_revision_gap.csv`. The only revised table is AGO, and the file records every origin's sales change into that revised `AGO_g` column. Domestic rows of donor `d` take the product rows whose origin is `d`. Import rows take product rows whose origin is not `d` only for AGO, because those sales were to AGO. The file's TLS row is not a `grev_gap`: that change is already in the TLS row of `AGO_g` in `io_s04`.

Signs, as in the S03 and S04 files: `stock_gap` is sales removed with INVNT, so it adds to sales. `grev_gap` is sales after minus sales before, so sales exceed output by it. The domestic product identity is sum of domestic use + exports + `stock_gap` − `grev_gap` = OUT.

Donor GDP `GDP_d` = sum of VA + sum of TLS over columns `d_*` in `io_s04` + `tls_on_invnt(d)`. That equals S03 `icio_gdp` for every donor except AGO. AGO's TLS on `g` rose by the revision, so AGO's donor GDP is S03 `icio_gdp` plus that TLS change.

### The sum

For region R with members `m` and donors `d(m)`:

`T_R = Σ_m GDP_m × T_d(m) / GDP_d(m)`

on every cell, including exports and both gap columns. For a B8 member `T_d(m)` is its swapped table `T'_m` and `GDP_d(m)` that table's GDP. Each donor table is divided by its own GDP, then weighted by the GDP share. This is the S03-H10 normalisation, and it is GTAP ch.7 p.3's "ratio of GDP calculated from the I-O tables to external GDP". An unnormalised USD table is never multiplied by a GDP share.

For a single-member region, `T_R = (GDP_R / GDP_d) × T_d`. By construction, GDP of `T_R`, including the carried `tls_on_invnt`, equals S02 `macro_regions.csv` GDP for R.

The 79 ICIO regions are the same single-region form, unchanged and unscaled. Scaling them to S02 GDP is the FIT's job (ch.7 p.3, ch.9D p.3). ISL is scaled to S02 ISL GDP inside XWE, like any other member.

## Angola's revision gap

GTAP builds the composite from "the primary region tables summed according to the GDP share weights" (ch.9D §D.3 p.3) and then FITs it (same page). In GTAP's order the primary table has already been through the 9C step: ch.8 §8.3 lists 9C as "Third" (p.3) and composites as "Finally" (p.4). The donor is AGO's S04 table as revised. S05 does nothing else to it.

The AGO table is scaled like every other donor, and its G-revision gap is scaled with it into `grev_gap`. Which regions receive it is whichever members the donor rule assigns to AGO. Percent imbalances are scale-free, so they carry over unchanged on a region whose only donor is AGO: health sales about 3× output, public administration and arts about +59% of output, education about +8%. S13 clears these gaps with AGO's (E40).

Balanced means the S04-H1 identity extended by the second carried gap: sum of domestic use + exports + `stock_gap` − `grev_gap` = OUT for every domestic product row, and costs = OUT for every sector column. No region passes by spreading, rescaling or dropping the gap.

Not allowed: AGO's pre-revision S03 table, moving the gap into another column, or rebalancing the AGO-derived table at S05.

The seller-side rows in `gov_revision_gap.csv` (origins other than AGO) are the same revision seen from the selling table. They stay on that origin's domestic product row so the row identity holds. They are not AGO's gap copied onto a region that does not use AGO. AGO's own product gap, and the import-side gap on AGO's table, travel only with the AGO donor table.

## What S05 does not do

No targets, no cross-entropy, no GRAS, no scaling of the 79 primary regions to AMA sectors, trade or energy. Those are the FIT (ch.9D p.3; S13).

The ICIO ROW block is report-only (R2). The plan's (b2) group constraint, the 88 summing to ROW, is an S13 constraint (E41). GTAP has no ROW block.

No bilateral detail. Bilateral trade is S07 and S09. B06 stays unsplit (S11). DPABR stays its own agent (S09). Labour is S12. The TLS split is S10.

The representative table is not used at S05.

No agricultural production targeting. GTAP 12 ch.9A p.2: "The APT procedure is not applied to the composite regions in the GTAP Data Base." E43 records the order question and does not swap stages. ch.8 §8.3 lists APT "Second" (p.3) and composites "Finally" (p.4). The composite tables in GTAP are therefore built from APT-targeted primary tables. That is inferred from the order; the text does not say it directly. Ours are built from untargeted ICIO donors. The effect is limited to agricultural coefficients of the 88 regions, which S13 reconciles.

## Outputs

Written under `dataset/stages/S05_composite/output/` by the stage kit. Each file under 50 MB.

| File | Content |
|---|---|
| `io_s05.csv.gz` | All 167 regions, single-region form. Columns `region,row` plus the 50 sector labels, `p,g,i,dpabr,X,stock_gap,grev_gap,OUT`. Rows `dom_<s>` (50), `imp_<s>` (50), `TLS`, `VA`, `OUT`. Deterministic gzip (`mtime=0`, empty filename). |
| `donor_weights.csv` | One row per S02 code in the 88 regions. Columns `region,code,geo,pool,s02_gdp,s02_pop,gdppc,income_concept,donor,donor_rule,donor_basis,weight,donor_gdp,scale,flags,oil_donor`. `oil_donor` is blank except for the B8 members; for those, `donor_gdp` is the GDP of the swapped table. |
| `oil_donor_columns.csv` | One row per B8 member: 9D donor, oil donor, B06 VA, TLS, input and import shares before and after, B06 output before and after (scaled), the two scales, the largest relative output change of the swap, and the H10 problem count. |
| `carried_gaps.csv` | Per region, row, gap kind and donor: the carried value. |
| `donor_changes_vs_pr71.csv` | Every code whose donor differs from PR #71 `chosen_donor`, and every code PR #71 left without a donor that S05 assigns. |
| `donor_rule_abc.csv` | The three donor columns for every S02 code in the 88, so a later edit of the config row can be compared. |
| `row_comparison.csv` | The 88 regions minus ISL against the ICIO ROW block. Report only. |
| `usa_scrutiny_s05.csv` | USA table, residuals, and the USA-derived share of XNA. |

## Tolerance

`io_s04.csv.gz` is the S03 4-decimal table plus the AGO cells written at 10 decimals. An identity that reads it uses absolute difference ≤ 0.05 USD million or relative difference ≤ 1e-9, as at S04.

Identities on S05's own float arithmetic use relative difference ≤ 1e-9. The 88 tables are linear combinations of the 4-decimal donor tables, so their residual equals the GDP-scaled donor residual within that relative tolerance. The donor residual itself is the 4-decimal residual.

## Hard checks

G0, G0c, IN1 and IN2 come from the kit. The rest are `S.check(..., 'hard', ...)`. STAMP only if every hard check PASSes and `dataset/build` is committed. A hard FAIL exits 1.

| ID | Check |
|---|---|
| S05-G0 | Four upstreams: S01, S02, S03, S04. Registered reads: S04 `io_s04.csv.gz`, `gov_revision_gap.csv`; S03 `stock_change_gap.csv`, `macro_comparison.csv`; S02 `macro_country.csv`, `macro_regions.csv`; S01 `regions.csv`, `composite_members.csv`, `country_region_map.csv`, `gtap_geo_regions_table910.csv`, `sectors.csv`. Config inputs, in `inputs.lock` and not upstreams: `dataset/prep/donor_tables/donor_tables.csv` (SHA-256 `2adaedabbe4b28dd411f1a3317298631c5d6f07aa6c0c61992fa9b5a92474377`, PR #71 commit `c719408`), `donor_candidates.csv` (SHA-256 `01b065b6a8d11e5668e4e5dc2966dc58db1e8e7a0fbbfc6b6af6354b48275ffa`, the same commit, pinned in `s05_composite.py`), `config/s05/donor_rule.csv`, `config/s05/oil_check_codes.csv`, `config/s05/oil_donors.csv`. |
| H1 | Input balance: for every economy × sector in `io_s04`, sales + stock_gap − grev_gap = OUT = costs, within the 4-decimal tolerance. Max residual, with AGO and USA separately. |
| H2 | Coverage: the 88 targets get a constructed table; the 79 ICIO regions get a converted one; ISL and ROW are not regions. No code whose S01 region is an ICIO economy gets a donor or a weight. |
| H3 | `donor_rule.csv` has exactly one valid row with `decided_by` filled. Every code with S02 GDP > 0 has exactly one donor, an ICIO economy table other than ROW and TWN, inside the rule's pool. Under `gtap15_gdppc` the pools are the 15 regions. Under the PR #71 rules, widening happens only for Caribbean and Eastern Africa, and donors equal the PR #71 column for every PR #71 row that has one. Zero-GDP codes have weight 0 and no donor. |
| H4 | For each region, the weights sum to 1 (1e-12). The sum of member GDP equals S02 `macro_regions.csv` GDP (rel 1e-9). |
| H5 | Construction, recomputed on a second code path (long-format group-by of `io_s04`, not the numpy reshape): every cell of each of the 88 tables equals Σ GDP_m × T_d / GDP_d (abs 1e-6 USD million). The 79 converted primaries equal their `io_s04` aggregates (abs 1e-9). |
| H6 | Balance, all 167 tables. Domestic product rows: sum of use + exports + stock_gap − grev_gap = OUT. Sector columns: sum of domestic and imported use + TLS + VA = OUT. Relative 1e-9 on the 88 against the carried donor residual. The 4-decimal tolerance on the 79. |
| H7 | GDP: for the 88, sum of VA + sum of TLS + TLS stock_gap = S02 region GDP (rel 1e-9). For the 79, it equals S03 `icio_gdp`, and for AGO that figure plus the TLS revision. |
| H8 | Gap carry: for each region and gap kind, the carried total equals Σ (GDP_m / GDP_d) × the donor total (rel 1e-9). AGO's own product gap is carried exactly to the regions that use AGO as a donor. |
| H9 | No NaN. Negatives only where a donor has them: TLS subsidies, and VA in CYP air and ISL pha (ISL pha reaches XWE). Count and list them by region. |
| H10 | B8 oil donors, on both code paths: for each member in `oil_donors.csv`, the B06 column has the oil donor's cost shares (abs 1e-9); every other sector column has the 9D donor's; final demand, exports and both gap columns are the 9D donor's cells; every domestic product row keeps the 9D donor's residual; outputs are not negative. Every other member's table is its donor table. H5 to H8 run on the swapped tables, with H6 predicting each column residual from the donor residual times the output change. |

## Report-only checks

- R1. `donor_weights.csv`: per region the donors and weights, with flags. The `DONOR-S02-GDPPC` codes, the zero-GDP codes, and the differences against the other two rules.
- R2. The 88 regions minus ISL against the ICIO ROW block: GDP, output, VA, C, G, I, X, M, and the ratio. Report only. S13 decides.
- R3. Regions that use AGO: carried `grev_gap` and `stock_gap`, and the top rows as a percent of OUT.
- R4. USA. No PRI or VIR member. The USA table equals the `io_s04` aggregates. USA table GDP against S02 region USA (USA country + PRI + VIR) is report-only; S13–S14 absorb it (E37). USA as a donor: Bermuda in XNA under every rule, and Greenland as well under `pr71_gtap9d` and `gtap15_gdppc`. The USA-derived share of XNA, the top XNA coefficients against USA's, and the top USA residuals.
- R5. Run the stage twice, the second with `GTAP_STAGES_DIR=/tmp/s05b`, and confirm the two `output/SHA256SUMS` files are byte-identical. Recorded in `REVIEW_BRIEF.md`.
- R6. The largest scale factors (GDP_m / GDP_d) and members whose donor GDP per capita ratio is past the 3× gate.

## Ledger

Each constructed region gets one ledger row per member, rule `GTAP12-9D-D3-p3`, citation ch.9D §D.3 p.3. The flag column carries that member's flags. There is no plug.
