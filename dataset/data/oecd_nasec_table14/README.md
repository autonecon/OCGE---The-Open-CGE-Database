# OECD Table 14: taxes on production and subsidies by institutional sector (2017-2022)

- **Folder:** `data/oecd_nasec_table14/`
- **Source:** OECD SDMX API `OECD.SDD.NAD,DSD_NASEC10@DF_TABLE14` (Annual non-financial accounts by institutional sector), annual, sectors S1 (total economy) and S13 (general government), transactions D21 (taxes on products), D29 (other taxes on production), D3, D31, D39 (subsidies), both accounting entries, 2017-2022, SDMX-CSV. Keyless. These are the national statistical offices' own sector accounts (Japan: ESRI JSNA; Germany: Destatis).
- **Fetch:** `fetch_oecd_table14.sh`. Fetched 2026-10-25. Re-fetching can give other bytes if the source revises.
- **Licence:** OECD terms and conditions (CC BY 4.0); cite OECD National Accounts.
- **Units:** national currency, millions, current prices (UNIT_MEASURE XDC); some rows also in other units, which S12 ignores.
- **Use:** S12 step 5 (choice `d29x39_national_total`, fix worker wD): the national total of other net production taxes, D29 paid less D39 (D3 where the country reports no D39), for the countries in `config/s12/d29_national_total.csv` whose activity-level D29X39 holds taxes on products (JPN: Table 6 and FIGARO D29X39 41.7 trn yen in 2022 against D29 14.9 and D3 5.9).

| File | Bytes | SHA-256 |
|---|---|---|
| `oecd_nasec_table14/fetch_oecd_table14.sh` | 717 | `e75282b31f8acecbce101d18fdb07e44743a77c21215c82272111705049f8b31` |
| `oecd_nasec_table14/oecd_table14_d21_d29_d3_2017_2022.csv.gz` | 28703 | `a3dcdf120ab7ca4d2a4eda9774dc50910bff6a2a4aa215164c4c443bc931cc63` |
