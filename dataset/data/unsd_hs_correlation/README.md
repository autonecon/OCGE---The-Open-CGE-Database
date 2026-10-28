# UNSD HS2022 to HS2017 conversion and correlation tables

- **Folder:** `data/unsd_hs_correlation/`
- **Source page:** [https://unstats.un.org/unsd/classifications/Econ](https://unstats.un.org/unsd/classifications/Econ)
- **Download URL / API:** https://unstats.un.org/unsd/classifications/Econ/tables/HS2022toHS2017ConversionAndCorrelationTables.xlsx
- **Version:** 2022 tables, note v1.0
- **Download date / origin:** 2026-10-20
- **Licence:** United Nations terms of use (free, attribution)
- **Coverage (2022 or year-rule fallback):** all HS6 codes
- **Units:** code concordance
- **Valuation basis / concept:** n/a
- **How it is used (PLAN.md stage):** Stage (a): only needed if the BACI HS22 file is used; preferred route is the BACI HS17 file.

## Files

| File | Bytes | SHA-256 |
|---|---|---|
| `unsd_hs_correlation/HS2022_conversion_note_v1.0.pdf` | 914,506 | `ac3671c241646b3d98668473d003a7546ca45e3304d44a777b551cc19e5a26ff` |
| `unsd_hs_correlation/HS2022toHS2017ConversionAndCorrelationTables.xlsx` | 409,859 | `8eb17f1db419eed133d44f831176a51f9d9df499cc82a491b999da53652ba038` |
| `unsd_hs_correlation/hs2017_to_hs2012.csv` | 80,839 | `271d9fcfc5d771e0456e585c7dc1d08f7168cb65f6235385580926fb811a3f0e` |
| `unsd_hs_correlation/hs2017_to_hs2007.csv` | 80,839 | `3d09444d6aef8fc4f954f25b39dce9745b2248de5d1891be87d542d95ca8c2dc` |
| `unsd_hs_correlation/hs2017_to_hs2002.csv` | 80,839 | `bf4d47198b2064313f380723b569c4233d01cc121f8aef3733c63cc832800de0` |

The three CSV files are the UNSD conversion sheet only (one earlier code per HS2017 code), extracted on 2026-10-21 from the workbooks on `https://unstats.un.org/unsd/trade/conversions/`. S10 uses them to read an H4, H3 or H2 schedule. The xlsx workbooks are not committed.

Per-file URLs are in `data/MANIFEST.csv`.
