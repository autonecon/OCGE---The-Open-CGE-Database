# World Bank WDI arable land per person and GDP per capita

- **Folder:** `data/wdi_ag_2022/`
- **Source:** World Bank WDI API v2 (keyless JSON), indicators AG.LND.ARBL.HA.PC and NY.GDP.PCAP.CD, all countries, 2011-2022; WDI last updated 2026-10-08.
- **Fetch:** `fetch_wdi_ag_2022.sh` (keyless). Fetched 2026-10-23. Re-fetching can give other bytes if the source revises; the SHA-256 of the files used is in `data/MANIFEST.csv`.
- **Licence:** CC BY 4.0 (World Bank); cite World Bank, World Development Indicators.
- **Year:** 2011-2020 means for the SUR fit; latest at or before 2022 for the prediction.
- **Units:** hectares per person; current USD
- **Use:** S12 step 2: regressors of the GTAP 12 ch.14A p.2 SUR for agricultural factor shares where USDA ERS has none.

## Files

| File | Bytes | SHA-256 |
|---|---|---|
| `wdi_ag_2022/AG.LND.ARBL.HA.PC.json` | 741,828 | `c047a3da8a72d2831c56967b514aa5aec99ab4c295a0a9dd1409aae6b966519f` |
| `wdi_ag_2022/NY.GDP.PCAP.CD.json` | 712,656 | `0b8cb190bdbb287f579ce28e59b3ecea4e72980146751ca0e6c9461342b273f2` |
| `wdi_ag_2022/fetch_wdi_ag_2022.sh` | 306 | `2d32304aa5cff285e3ed41489b94f7ff249c297902ecae1990eec3d0dd000bbc` |
