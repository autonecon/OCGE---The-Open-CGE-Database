# Region, composite and sector lists and the HS6 concordance (inputs to stage S01)

- **Folder:** `data/classifications/`
- **Source page:** the project repository
- **Download URL / API:** an earlier internal build earlier-build/master/{countries_2022,rest_of_2022,industry_codes}.csv and build/rest_of_{locked.csv,notes.md}; an internal working folder (PR #54 concordance)
- **Version:** an earlier internal build (countries_2022.csv last changed 21e45c8); pr54 hs6_to_icio51.csv as on box 2026-10-20
- **Download date / origin:** copied 2026-10-20 (UTC+7)
- **Licence:** internal project files; concordance built from UNSD HS-CPC-ISIC correspondences (UN terms)
- **Coverage (2022 or year-rule fallback):** 168 inherited regions (160 single + 8 composites, 52 members); 51 sectors; 5,839 HS6 codes
- **Units:** codes
- **Valuation basis / concept:** n/a
- **How it is used (PLAN.md stage):** Stage S01: start list for the final 167 regions (David decisions 2026-10-20 applied in the build, not here), 51 sectors, HS6 -> sector concordance.

## Files

| File | Bytes | SHA-256 |
|---|---|---|
| `classifications/countries_2022.csv` | 9,820 | `fab5652f600b3c3127177d8421f46654f15efe4784214280f068739048a0f05c` |
| `classifications/hs6_to_icio51.csv` | 1,366,488 | `037e6299c7501bf6207d4307bae9471f03410e1b4f4495815832e820266011ed` |
| `classifications/industry_codes.csv` | 1,279 | `4d9796c9c8a583c849b06b44b5cc6aaaffa8bf16bff4d2103fd5a0712ee283e1` |
| `classifications/rest_of_2022.csv` | 429 | `22dcf8e7d00b0456fbb0556bfab4e26cbe3cceb8320e8f5d1f6211fac7914f6c` |
| `classifications/rest_of_locked.csv` | 429 | `22dcf8e7d00b0456fbb0556bfab4e26cbe3cceb8320e8f5d1f6211fac7914f6c` |
| `classifications/rest_of_notes.md` | 5,722 | `c5d3d8bd25d031395ef0f138b351b6a12c7978e423b2582bb7a899b1f6c793c7` |

Per-file URLs are in `data/MANIFEST.csv`.
