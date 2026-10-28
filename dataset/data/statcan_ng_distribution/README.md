# Statistics Canada natural gas distribution (sales value and energy), for S11 domestic basic prices

- **Folder:** `data/statcan_ng_distribution/`
- **Source:** Statistics Canada table 25-10-0059-01, Canadian monthly natural gas distribution, Canada and provinces (inactive; 2016-01 to 2025-12), https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=2510005901. Full-table CSV zip https://www150.statcan.gc.ca/n1/tbl/csv/25100059-eng.zip (via keyless WDS `getFullTableDownloadCSV/25100059/en`).
- **Fetch:** `fetch_statcan_ng_distribution.sh` (keyless). Fetched 2026-10-23 (UTC). sha256 in `fetch.log` and `data/MANIFEST.csv`.
- **Licence:** Statistics Canada Open Licence (https://www.statcan.gc.ca/en/reference/licence); attribution required.
- **Year:** 2022 (monthly; sum the 12 months). 2017 is in the same file.
- **Use:** S11 domestic basic prices (GTAP 12 ch.12 §12.3.6-12.3.8), Canada gas. **This is not the AECO-C hub price.** AECO-C (AER, CER, Alberta government) could not be fetched: every host was blocked by the sandbox proxy. The AER ST98 (2023) executive summary states the 2022 AECO-C annual average as Cdn$5.10/GJ (from a web search, not downloaded; see the S11 hand-off note).
- **Units and basis:** dimensions Geography x Distribution (industrial / commercial and institutional / residential deliveries) x Statistics (cubic metres, gigajoules, Canadian dollars, customers); all values in thousands (`SCALAR_FACTOR`). A delivered price is CAD / GJ. It is a distributor sales value, so it includes distribution charges; in Alberta and other unbundled markets many customers buy the commodity from retailers, so the CAD may cover distribution only and understate the full delivered price.
- **Key 2022 values (CAD/GJ, 12-month sum of CAD / sum of GJ):** Canada industrial 6.737, commercial 7.292; Alberta industrial 3.868, commercial 2.510; Ontario industrial 8.259; British Columbia industrial 2.981. 2017: Canada industrial 4.664, Alberta industrial 1.579.
