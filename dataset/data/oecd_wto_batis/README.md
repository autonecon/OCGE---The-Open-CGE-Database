# OECD-WTO Balanced Trade in Services (BaTIS), BPM6

- **Folder:** `data/oecd_wto_batis/`
- **Source page:** [https://www.oecd.org/en/data/datasets/balanced-trade-in-services.html](https://www.oecd.org/en/data/datasets/balanced-trade-in-services.html)
- **Download URL / API:** https://sdmx.oecd.org/public/rest/data/OECD.SDD.TPS,DSD_BATIS@DF_BATIS,1.0/ (2022, exports, USD; total and EBOPS 2010 detail)
- **Version:** DF_BATIS 1.0, 2022 values
- **Download date / origin:** downloaded 2026-10-20 13:26 (UTC+7) by the dataset-wedge-verify run (an internal working folder), copied 2026-10-20
- **Licence:** OECD; CC BY 4.0 since 1 July 2024 (cite OECD-WTO BaTIS)
- **Coverage (2022 or year-rule fallback):** 159 of 168 regions as reporters (missing only GTAP residual aggregates and PAL); every 2022 value OBS_STATUS=I (estimated)
- **Units:** USD million (UNIT_MULT 6)
- **Valuation basis / concept:** balanced bilateral services trade, residence principle, BPM6/EBOPS 2010; modelled estimates
- **How it is used (PLAN.md stage):** Stage (e): split ICIO ROW services trade and give ROW-to-ROW flows; SC freight to VST in stage (d); SD travel as direct purchases (concepts.md C15, C24).

## Files

| File | Bytes | SHA-256 |
|---|---|---|
| `oecd_wto_batis/ebops2022.csv` | 111,824,019 | `f2a3987df63ef21d93177187718fcefa7689e9be3e1bdc4fc11f328e41fda803` |

The S09 VM extract of `ebops2022.csv` is sha `201c7932ef3d44fa4511275bc8bb897fb0686183aafe23b58e7fe14b9d506ab9`, the same 111,824,019 bytes. The content matches this MANIFEST sha; the SDMX row order differs. S09 reports that sha and does not treat it as a failed total.
| `oecd_wto_batis/structure.xml` | 1,445,278 | `ed6f0bf197c1edb69a764503608e2323a24569c7c145ab95b3ebf9fb19d4628b` |
| `oecd_wto_batis/tot2022.csv` | 3,591,490 | `9e1739b6ae1444391117ff1f27c9f7fa6a27b0a4cc7ce929785347e85f7e949f` |

Per-file URLs are in `data/MANIFEST.csv`.
