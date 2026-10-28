# US EIA spot prices (petroleum products; natural gas)

- **Folder:** `data/eia_prices/`
- **Source page:** [https://www.eia.gov/dnav/pet/pet_pri_spt_s1_a.htm](https://www.eia.gov/dnav/pet/pet_pri_spt_s1_a.htm)
- **Download URL / API:** https://www.eia.gov/dnav/pet/xls/PET_PRI_SPT_S1_A.xls ; https://www.eia.gov/dnav/ng/xls/NG_PRI_FUT_S1_A.xls
- **Version:** annual series, as published 2026-10
- **Download date / origin:** 2026-10-20
- **Licence:** US government work, public domain
- **Coverage (2022 or year-rule fallback):** US hubs (NY Harbor, US Gulf Coast, Mont Belvieu, Henry Hub)
- **Units:** USD per gallon (x42 = per barrel); USD per MMBtu
- **Valuation basis / concept:** FOB spot at hub, excluding taxes
- **How it is used (PLAN.md stage):** Stage (g): cross-check of the refined-product composite (crude marker + EI regional margin); Americas product valuation. 2022: NYH gasoline 3.076, USGC gasoline 2.949, NYH ULSD 3.72, USGC ULSD 3.509, USGC jet 3.374, propane 1.107 $/gal.

## Files

| File | Bytes | SHA-256 |
|---|---|---|
| `eia_prices/EIA_NG_PRI_FUT_S1_A.xls` | 33,792 | `601f7a9c7453fa8716280ffb665db02d5f45f31d8f52ca4dcfbd91ca836d1a22` |
| `eia_prices/EIA_PET_PRI_SPT_S1_A.xls` | 54,784 | `ec47fe32931211d77e88599957744a6ec5fa797c1a54530ea73521b3d2458347` |

Per-file URLs are in `data/MANIFEST.csv`.
