# census_imdb_2022: US Census imports, December 2022 IMDB file (CY2022), and its summaries

- **Source:** US Census Bureau, IMDB December 2022 file, https://www.census.gov/trade/downloads/2022/Merch/im_m/IMDB2212.ZIP. Public download, no API key.
- **Licence:** US government work, public domain. Redistributable.
- **Files:** `IMDB2212.ZIP` (170.9 MB; not in git, too large; `fetch_imdb2212.sh` downloads it and checks the SHA), `agg.py` (reads IMP_DETL year-to-date fields for month 12), `hs10_cty_rp_2022.csv` (HS10 × country × rate provision: con_val, dut_val, cal_dut, con_cif, gen_val, USD), `hs6_cty_rp_2022.csv` (same at HS6). The script rebuilds both summaries byte for byte (checked 2026-10-21).
- **Totals:** imports for consumption 3,223.68 bn USD customs value; calculated duty 89.763 bn USD; CIF 3,352.88 bn USD.
- **Use:** S10 US scrutiny, report-only (duty benchmark and 301/232 decomposition). Never used to scale tariffs (David 2026-10-20 21:48).

| File | Bytes | SHA-256 |
|---|---|---|
| `census_imdb_2022/IMDB2212.ZIP` | 170935295 | `f3725a5cf34572abf7db9bfc6001cd23a88da58331977847c7db336d91b69e63` |
| `census_imdb_2022/agg.py` | 570 | `265e315abab8bef083a658c1f15cc60d55052371d7d7f29fb6921b68f8838bfb` |
| `census_imdb_2022/fetch_imdb2212.sh` | 971 | `8c274172a905f7ff4737c82a387954a124c8ecda55e17f08a004aa96e3f4b361` |
| `census_imdb_2022/hs10_cty_rp_2022.csv` | 19530798 | `080056f0459cf474f3a6d9458d8059411c0c00c74a497b1de82d9647dcfce5b5` |
| `census_imdb_2022/hs6_cty_rp_2022.csv` | 9226072 | `6a4812e903658210bca1671918393ef4b72ad6b2294c42d42b3c38a6c68583dc` |
