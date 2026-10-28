# World Bank Changing Wealth of Nations 2024

- **Folder:** `data/wb_cwon/`
- **Source page:** [https://www.worldbank.org/en/publication/changing-wealth-of-nations](https://www.worldbank.org/en/publication/changing-wealth-of-nations)
- **Download URL / API:** https://api.worldbank.org/v2/sources/59 (indicators NW.NCA.*, NW.PCA.*); methodology PDF from the CWON 2024 report page
- **Version:** CWON 2024; latest year 2020
- **Download date / origin:** 2026-10-20
- **Licence:** CC BY 4.0 (World Bank)
- **Coverage (2022 or year-rule fallback):** asset values by country, to 2020
- **Units:** constant/current USD as per indicator (.TO.CD = current USD)
- **Valuation basis / concept:** Wealth = present value of future resource rents (an ASSET, not a flow)
- **How it is used (PLAN.md stage):** Plausibility cross-check only for the natural-resource factor (stage h). Flows come from WDI rents (concepts.md C19). Data-catalog page blocked (HTTP 429) - fetched via API instead.

## Files

| File | Bytes | SHA-256 |
|---|---|---|
| `wb_cwon/CWON2024_Methodology.pdf` | 1,441,995 | `9a94ad3cc70b574383b580d0c284048cb2ac8fe87c90060f5af94a13eccee191` |
| `wb_cwon/NW.NCA.AGRI.TO.CD.json` | 114,465 | `1556c8204e5ce7a58cb7b70ab1f08820d06f8cdaaa1f66b6822c5ac16658cd69` |
| `wb_cwon/NW.NCA.SAGA.TO.CD.json` | 109,900 | `9e97ae6853d26e85371812f67809307dd31ef59f4bd0986cb2b17fa8a325958b` |
| `wb_cwon/NW.NCA.SAOI.TO.CD.json` | 106,292 | `28634f9564edf472686d362d42c9a5f783983e3e553fb5c535213603a4e66984` |
| `wb_cwon/NW.NCA.SSOI.TO.CD.json` | 109,295 | `749402a1348f06e061edcd77f2b2c8cd016ba8aa048b8c3d55f56fd220e3f57c` |
| `wb_cwon/NW.PCA.TO.EX.CD.json` | 110,817 | `e4eeeadd14fb06c282b7cf3540e6661458d9e31f4916e4cc4aa5ff49c04276cf` |
| `wb_cwon/ind.json` | 48,942 | `cace61a93f22b4b3df302835d63116dcf999561f24f4fb1e024f75e5b6bdb71d` |

Per-file URLs are in `data/MANIFEST.csv`.
