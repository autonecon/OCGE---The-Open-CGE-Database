# Donor tables for economies with no OECD ICIO 2025 table

Prep for S03 (Puerto Rico) and S05 (non-ICIO and composite tables). This folder records the chosen donor. It does not build an I-O table, and it does not move any country into a regional group.

Run: `python3 dataset/build/prep_donor_tables.py`

Raw files stay outside git (`DONOR_RAW`, default `/tmp/gtap-raw/earlier-build/sources`). The World Bank API pages stay in `DONOR_API` (default `/tmp/gtap-raw/wdi_api`). Only the code, these tables, and these notes are committed.

## What GTAP does

Aguiar, GTAP 12 Data Base documentation, chapter 8, resource 7623, PDF page 4 (https://www.gtap.agecon.purdue.edu/resources/res_download.asp?D_ID=13037):

> Finally, for each region where we have no contributed table, we calculate a composite table, as a linear combination of I-O tables for selected primary regions. We make a different selection of primary regions for each composite region, matching as closely as possible the composite region's income level and production pattern, as described in Chapter 9D.

Corong, chapter 9D, resource 7910, PDF pages 2–3 (https://www.gtap.agecon.purdue.edu/resources/res_download.asp?D_ID=13265):

Section D.2. Nineteen geographic regions (Table 9.9). Where a geographic region has no I-O table, composite construction uses 15 regions: Latin America is Caribbean + Central America + South America, and Sub-Saharan Africa is Eastern + Central + Western + Southern Africa.

Section D.3. Four steps:

1. Match each country to a primary region in the same geographic region by similarity in GDP per capita.
2. Composite target GDP is the sum of member GDP.
3. GDP weights are country GDP / composite GDP, assigned to each matched primary.
4. The composite I-O table is the GDP-share-weighted sum of those primary tables.

The tables are then FIT to macro, trade, protection, and energy (chapter 15A in that PDF; this project cites chapter 17A). FIT is not done here.

Wang and Aguiar, chapter 7, resource 7622, PDF page 3 (https://www.gtap.agecon.purdue.edu/resources/res_download.asp?D_ID=13309): "Similar per capita GDP is used as a criterion for matching a member country in a composite region to one of the primary regions within the same geographic area." The chapter does not say PPP.

This project's rule F3 (`data-round/READINESS.md`) names `ny_gdp_pcap_pp_cd.csv` and says: match each economy to an ICIO economy in the same GTAP geographic region by nearest GDP per capita, then GDP-weight the donor tables. Erratum E26 (David, 2026-10-20 7:03 PM UTC+7) makes that the prior. EXIOBASE is a report-only check and does not change the donor. Erratum E31: Puerto Rico stays in USA; S03 builds a PRI table from the F3 donor, scales it to S02 macro, and appends it to ICIO USA. This prep only selects the donor.

## Donor universe

Primary regions here are the 80 economies in OECD ICIO 2025 `2022_SML.csv` (the row prefixes, excluding `ROW`). The 2017 file has the same 80. Both files match `dataset/data/MANIFEST.csv`. Taiwan is in ICIO and has no World Bank PPP series in the SHA-checked file, so it is listed and never selected (`unscored_donors = TWN`).

GTAP's own contributed tables are not an input. No GTAP database value is read.

## Who is scored

From `dataset/stages/S01_sets_registry/output/regions.csv` (167 regions):

- 80 single regions with `icio_measured=no`
- Puerto Rico (`pri_append`, parent USA, geographic region CARB)
- Composite members that do not have their own ICIO table (52). Iceland is an ICIO economy inside XWE and keeps its own table in the composite weights.
- Territories already listed on those composites (17). They receive a donor when income data exist. They are not put into the GDP-weight denominator. See `NEEDS_DAVID.md`.

No single region is folded. Geographic codes come from `gtap_geo_regions_table910.csv`. Kosovo uses WDI code XKX and EXIOBASE code KSV. Palestine uses WDI code PSE and EXIOBASE code PAL. Zanzibar takes Tanzania's geographic region (EAFR).

The pool is the scored ICIO economies in the country's Table 9.10 region. The pool is widened only when that region has zero scored ICIO donors, and only to the two groups in chapter 9D §D.2:

| Empty Table 9.10 region | Widened pool | ICIO donors in the widened pool |
|---|---|---|
| CARB | LMAR = CARB+CAMR+SAMR | CRI, ARG, BRA, CHL, COL, PER |
| EAFR | SSAF = EAFR+CAFR+WAFR+SAFR | CIV, NGA, SEN, AGO, CMR, COD, STP, ZAF |

Central America is not widened: Costa Rica is a donor. Southern Africa is not widened: South Africa is a donor. Central Asia is not widened: Kazakhstan is the only donor.

## Selection

Four blocks, equal weight, fixed before the results were read:

| Block | Distance | Series |
|---|---|---|
| Income | absolute log difference of GDP per capita | PPP (`NY.GDP.PCAP.PP.CD`) when the SHA-checked file has it; otherwise market GDP per capita (GDP / population, current USD) |
| Value added | Euclidean distance of agriculture, manufacturing, industry-minus-manufacturing, and services, each as a fraction of GDP | WDI `NV.AGR.TOTL.ZS`, `NV.IND.MANF.ZS`, `NV.IND.TOTL.ZS`, `NV.SRV.TOTL.ZS` |
| Resource rents | Euclidean distance of oil, gas, coal, mineral, and forest rents, each as a fraction of GDP | SHA-checked `wdi_energy_rents_2021.csv` for oil, gas, coal; API for mineral and forest |
| Trade openness | absolute gap in (exports + imports) / GDP | `NE.EXP.GNFS.CD` and `NE.IMP.GNFS.CD` over `NY.GDP.MKTP.CD` in `wdi_accounts.csv` |

Shares are not renormalised to 1. A missing share is missing, not zero.

The chosen donor is the eligible ICIO economy with the best mean within-pool rank. Rank 1 is the smallest distance. Ties share the average rank. A donor with no income distance is ineligible. Remaining ties break on smaller income distance, then larger donor GDP.

Mean rank is the objective because a median-scaled Euclidean lets rents dominate. Among scored ICIO donors the median pairwise distances are about 0.880 (income, absolute log PPP), 0.183 (value-added Euclidean), 0.027 (rent Euclidean), and 0.552 (trade/GDP gap). Dividing by those medians makes a modest rent gap many times larger than an income gap. An earlier run that did that was discarded. The natural-unit gates below were not changed.

The pure chapter 9D step (nearest GDP per capita inside the pool, PPP when that is the income concept, otherwise market) is column `gtap9d_nearest_gdppc`. `departs_from_gdppc_only` means the rank donor is not that neighbour. Market-price nearest is always reported beside it. Chapter 7 does not say PPP; F3 uses the PPP file. Both are shown.

### Year

Prefer 2022, then 2021, 2020, 2019, 2018, 2017. The four value-added shares use one common year when one exists. Oil, gas, and coal rents are the 2021 file only: the accounts extract has those columns empty in 2022, and a country missing from the 2021 file does not fall back to its 2017 accounts rent. Kuwait and Syria are missing from that file. The gap is flagged in `NEEDS_DAVID.md` and was not filled. Mineral and forest rents prefer 2021 for the same reason (2022 is unpublished in the API pull; 2021 is present). The year used is on each row.

### Gates (fixed, not refit)

| Gate | Value | Weak if |
|---|---|---|
| `GDPPC_RATIO_MAX` | 3 | absolute log income distance > ln(3) |
| `VA_EUCLID_MAX` | 0.20 | value-added Euclidean above 0.20 |
| `RENT_EUCLID_MAX` | 0.10 | rent Euclidean above 0.10 |
| `OPEN_GAP_FLAG` | 0.50 | recorded as `open_gap`; not weak by itself |
| `RANK_NEAR` | 0.25 | second mean rank within 0.25 of the first |
| `EXIO_COSINE_GAP` | 0.10 | in-pool EXIOBASE cosine beats the chosen donor by at least 0.10 |

`weak_match=yes` if any of these is present: `no_geo`, `no_income`, `no_donor`, `empty_pool`, `income_is_market_gdppc`, `gdppc_gap`, `va_gap`, `rent_gap`, `departs_from_gdppc_only`, `near_tie`, `exiobase_disagrees`, `twn_unscored_same_region`, or `incomplete_features` when the income, value-added, or rent block is missing. `widened_region` and `sole_donor` are reported and are not, by themselves, a weak score. They are the chapter 9D fallback and the one-donor regions.

## EXIOBASE check

File: `EXIOBASE_3rx_2015_pxp.mat`, Bjelle, Stadler and Wood (2019), Zenodo 2654460, CC BY-SA 4.0. SHA-256 matches MANIFEST. Product-by-product, 2015, million EUR. Value added is the sum of rows that do not double-count: 3 other net taxes on production, 4 wage total, 8 consumption of fixed capital, 9 land, 10 royalties, 11 NOS. The check is the cosine of the 200-product value-added share vectors. The preferred in-pool donor is reported. It never replaces the chosen donor (E26). The base year of this build is 2022; the check is a 2015 coefficient comparison.

## SHA checks

Matched to `dataset/data/MANIFEST.csv` at run time: both ICIO SML files and the ICIO provenance note; `wdi_accounts.csv`, `wdi_energy_rents_2021.csv`, `ny_gdp_pcap_pp_cd.csv` and their provenance notes; the EXIOBASE mat, labels, and provenance note. Status is in `sha_checks.csv` and `checks.md`.

`wdi_2017_2022_extract.csv` and `wdi_services_2022.csv` are in MANIFEST and were not on this machine. They are not read. Trade openness comes from the accounts file. Sector shares and mineral and forest rents were fetched from the World Bank API v2 on 2026-10-20 (CC BY 4.0). Page hashes are in `wdi_fetch_provenance.csv`. The API pages are not committed.

Agriculture cross-check: median absolute gap between `NV.AGR.TOTL.ZS` and `100 × NV.AGR.TOTL.CD / GDP` in 2022 is 0.000 percentage points over 237 countries.

## Files

| File | Contents |
|---|---|
| `donor_tables.csv` | One row per scored economy: donor, three runners-up, distances, ranks, EXIOBASE check, flags |
| `donor_candidates.csv` | Every in-pool candidate |
| `flags.csv` | One row per flag |
| `composite_donor_weights.csv` | Member GDP weights for the eight composites. Territories are listed and left out of the denominator |
| `sha_checks.csv`, `wdi_fetch_provenance.csv`, `checks.md`, `run_summary.json` | Verification |
| `NEEDS_DAVID.md` | Decisions that this prep does not take |
| `DONOR_LIST.md` | The same rows in a readable table |

The run that wrote these files is `2026-10-20T13:55:57Z` (150 rows, 137 weak, unscored donor TWN).
