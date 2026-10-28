# Donor-table prep checks

Run 2026-10-20T13:55:57Z.

Thresholds are fixed in `dataset/build/prep_donor_tables.py`. They were not adjusted after the run.

## SHA-256 against dataset/data/MANIFEST.csv

| Path | Status |
|---|---|
| `oecd_icio/2022_SML.csv` | MATCH |
| `oecd_icio/2017_SML.csv` | MATCH |
| `oecd_icio/PROVENANCE_ICIO2025.txt` | MATCH |
| `wdi/wdi_accounts.csv` | MATCH |
| `wdi/wdi_energy_rents_2021.csv` | MATCH |
| `wdi/ny_gdp_pcap_pp_cd.csv` | MATCH |
| `wdi/PROVENANCE_ACCOUNTS.txt` | MATCH |
| `wdi/PROVENANCE_ENERGY_RENTS_2021.txt` | MATCH |
| `wdi/ny_gdp_pcap_pp_cd_PROVENANCE.txt` | MATCH |
| `exiobase3rx/EXIOBASE_3rx_2015_pxp.mat` | MATCH |
| `exiobase3rx/LABELS_2015.txt` | MATCH |
| `exiobase3rx/PROVENANCE_2015.txt` | MATCH |
| `wdi/wdi_2017_2022_extract.csv` | NOT_ON_DISK |
| `wdi/wdi_services_2022.csv` | NOT_ON_DISK |

`wdi_2017_2022_extract.csv` and `wdi_services_2022.csv` are in MANIFEST and are not on this machine (they were never committed). This prep does not read them. Trade openness comes from `wdi_accounts.csv` (NE.EXP.GNFS.CD and NE.IMP.GNFS.CD). Sector shares were fetched from the WDI API because the committed extracts do not contain NV.IND / NV.SRV / NV.AGR shares.

## Hard checks

| Check | Result | Value | Threshold |
|---|---|---|---|
| n_single_non_icio | PASS | 80 | 80 |
| pri_present | PASS | 1 | 1 |
| donors_are_icio | PASS | 0 | 0 |
| donor_is_not_a_composite | PASS | 0 | 0 |
| donor_inside_pool | PASS | 0 | 0 |
| icio_2022_count | PASS | 80 | 80 |
| icio_2017_same_set | PASS | 0 | 0 |
| agr_share_crosscheck_pp | PASS | 0.0 | 5 |

## Selection

The chosen donor is the scored ICIO economy in the Table 9.10 pool with the best mean within-pool rank across four blocks (income, value-added shares, resource rents, trade openness). Rank 1 is the smallest natural-unit distance. Ties share the average rank. A donor with no income distance is ineligible. Remaining ties break on smaller income distance, then larger donor GDP.
The median pairwise distances below are diagnostic only. They are not the objective. A first run that divided each block by its median pairwise gap let rents dominate, because most ICIO donors have rents near zero (median pairwise rent Euclidean about 0.027 versus income |ln| about 0.88). That run was discarded. Thresholds on the natural-unit distances were not changed.

## Diagnostic median pairwise distances among scored ICIO donors

- income |ln GDPpc PPP|: 0.879821
- VA-share Euclidean: 0.183132
- rent-share Euclidean: 0.0269337
- trade/GDP absolute gap: 0.552257

Unscored ICIO donors (no PPP GDP per capita, so they cannot be selected): TWN.

Agriculture cross-check: median |NV.AGR.TOTL.ZS − 100×NV.AGR.TOTL.CD/GDP| in 2022 = 0.000 percentage points over 237 countries.

## Counts

- single_region: 80, of which weak: 72
- pri_append: 1, of which weak: 1
- composite_member: 52, of which weak: 48
- composite_territory: 17, of which weak: 16

## Flag counts

- departs_from_gdppc_only: 52
- va_gap: 47
- widened_region: 44
- market_vs_ppp_gdppc: 39
- near_tie: 32
- incomplete_features: 30
- rent_gap: 29
- gdppc_gap: 25
- exiobase_disagrees: 23
- open_gap: 23
- no_income: 21
- no_donor: 21
- exiobase_not_covered: 17
- sole_donor: 14
- income_is_market_gdppc: 10
- twn_unscored_same_region: 3
