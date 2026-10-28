# eurostat_naio_product_taxes: taxes less subsidies on products by CPA product (for S10)

- **Source:** Eurostat, supply table at basic prices including a transformation into purchasers' prices (`naio_10_cp15`), row `ind_impv = D21X31` (taxes less subsidies on products), every CPA product (`prd_amo`), million EUR, every reporting country, 2015-2022. Keyless SDMX 2.1.
- **Fetched:** 2026-10-25 (UTC+7) by `fetch_naio_10_cp15_d21x31.sh` (the exact query is in the script). The dataset's last update stamp in the file is 2026-10-21.
- **Licence:** Eurostat reuse policy (CC BY 4.0). Redistributable with attribution.
- **Coverage:** 2022 tables for the EU-27, Norway, Albania, Serbia and North Macedonia (Kosovo to 2019 only, not used).
- **Not used:** `naio_10_cp1630` (taxes less subsidies by product and user) is confidential for Germany, so the stage uses the supply-table product totals, which every country publishes.
- **Use:** S10 `product_tax_pattern` (QA round 2 P1): the product control of the non-energy product taxes. S13 RASes the column TLS layers towards these shares on the non-energy rows (GTAP 12 ch.8, national I-O valuation layers). The energy products (B05, B06, C19, D) are left out because S13 holds the energy excise on those rows.

| File | Bytes | SHA-256 |
|---|---|---|
| `eurostat_naio_product_taxes/fetch_naio_10_cp15_d21x31.sh` | 610 | `0fae9c5702f043504998b1d336a14a7782951af4b5f4514377a7d87caa9e5e8f` |
| `eurostat_naio_product_taxes/naio_10_cp15_d21x31_2015_2022.csv` | 1929648 | `13df0319706c20f04f79910d0cb6769c6937621b8e02956dedafb16f183a917a` |
