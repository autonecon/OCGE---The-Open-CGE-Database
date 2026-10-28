# CEPII BACI (reconciled UN Comtrade bilateral goods trade)

- **Folder:** `data/baci/`
- **Source page:** [https://www.cepii.fr/CEPII/en/bdd_modele/bdd_modele_item.asp?id=37](https://www.cepii.fr/CEPII/en/bdd_modele/bdd_modele_item.asp?id=37)
- **Download URL / API:** https://www.cepii.fr/CEPII/en/bdd_modele/bdd_modele_item.asp?id=37 (files: https://www.cepii.fr/DATA_DOWNLOAD/baci/data/BACI_HS22_V202601.zip, BACI_HS17_V202601.zip)
- **Version:** v202601; HS2022 (2022-2024) and HS2017 (2017-2024)
- **Download date / origin:** 2026-10-20
- **Licence:** Etalab Open Licence 2.0; cite Gaulier & Zignago (2010), CEPII WP 2010-23
- **Coverage (2022 or year-rule fallback):** 158 of 168 regions for 2022 (Taiwan present as code 490 "Other Asia, nes")
- **Units:** USD thousand (v), metric tonnes (q); importer x exporter x HS6 x year
- **Valuation basis / concept:** FOB (importer CIF reports converted with estimated CIF/FOB); includes re-exports
- **How it is used (PLAN.md stage):** Stage (c): SHARES only, to split ICIO ROW into member countries and give ROW-to-ROW flows, after re-export removal; stage (f) import weights (2020-2022 average). Not comparable with ICIO in levels (concepts.md C01, C02). Prefer the HS17 file for 2022 so hs6_to_icio51 (HS2017) applies without conversion.

## Files

| File | Bytes | SHA-256 |
|---|---|---|
| `baci/BACI_HS17_V202601.zip` | 794,583,540 | `16aaa22d3b000cc87744c2c28ac97ce44394c3adf315ec259451d5bb4fcae609` |
| `baci/BACI_HS22_V202601.zip` | 301,386,611 | `376f9b4cda53710a580f347b9bae69c5fb16911d0ae19b50896c109bd5dfb1f7` |

Per-file URLs are in `data/MANIFEST.csv`.
