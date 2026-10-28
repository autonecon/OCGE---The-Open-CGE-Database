# OECD National Accounts Table 6, output and value added by activity

- **Folder:** `data/oecd_na_table6/`
- **Source:** OECD SDMX API `OECD.SDD.NAD,DSD_NAMAIN10@DF_TABLE6` v2.0, annual, total economy (S1), transactions D1, B1G, D29X39, B2A3G, B3G, B2G, all activities, 2017-2022, SDMX-CSV; and P51C (consumption of fixed capital) in a second file.
- **Fetch:** `fetch_oecd_na_table6.sh` (keyless). Fetched 2026-10-23. Re-fetching can give other bytes if the source revises; the SHA-256 of the files used is in `data/MANIFEST.csv`.
- **Licence:** OECD terms and conditions (CC BY 4.0); cite OECD National Accounts.
- **Year:** latest year at or before the base year with D1 and B2A3G by activity, per country (2022 for 43 of 45).
- **Units:** national currency, millions, current prices (PRICE_BASE V, UNIT_MEASURE XDC)
- **Use:** S12 step 1: labour share by activity for ICIO economies not in FIGARO; total-economy shares for the S12 benchmark screen and the donor report; P51C / B2A3G caps natural-resource rent at net operating surplus (David, 2026-10-23).

## Files

| File | Bytes | SHA-256 |
|---|---|---|
| `oecd_na_table6/fetch_oecd_na_table6.sh` | 897 | `a60328a373ad8f49aeff1eab39c3d29ab34f303ef7e505684d88714d4b3da742` |
| `oecd_na_table6/oecd_table6_activity_2017_2022.csv.gz` | 1,595,111 | `42c0b920443e38bbd444fc23ed7896c814b23138536df7dab9f64ceb025adeea` |
| `oecd_na_table6/oecd_table6_p51c_2017_2022.csv.gz` | 544,513 | `c851cdb116ed73f219e034c7dd765d70ce4540fa41f997c98682a6f95c780c0a` |
