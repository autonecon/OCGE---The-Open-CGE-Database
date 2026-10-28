# OECD International Transport and Insurance Costs (ITIC)

- **Folder:** `data/oecd_itic/`
- **Source page:** [https://www.oecd.org/en/data/datasets/international-transport-and-insurance-costs-of-merchandise-trade-itic.html](https://www.oecd.org/en/data/datasets/international-transport-and-insurance-costs-of-merchandise-trade-itic.html)
- **Download URL / API:** https://sdmx.oecd.org/sti-public/rest/data/OECD.SDD.TPS,DSD_ITIC@DF_ITIC,1.1/..C_F.C._T.A.PT_IM_CIF?startPeriod=2021&endPeriod=2022&format=csvfilewithlabels
- **Version:** ITIC (Miao & Fortanier 2017 method); 2022
- **Download date / origin:** ITIC_total_2022.csv 2026-10-20; pr55/ copied 2026-10-20 from an earlier internal build, earlier-build/sources/itic
- **Licence:** OECD; CC BY 4.0 since 1 July 2024
- **Coverage (2022 or year-rule fallback):** 157 importer regions; 82,476 rows; every 2022 value OBS_STATUS=I (imputed), METHODOLOGY=AG
- **Units:** percent of CIF value
- **Valuation basis / concept:** modelled CIF-FOB margin
- **How it is used (PLAN.md stage):** Stage (d): VTWR = VFOB x r/(1-r); remove the same freight from ICIO transport-services trade (concepts.md C03).

## Files

| File | Bytes | SHA-256 |
|---|---|---|
| `oecd_itic/ITIC_total_2022.csv` | 28,720,371 | `7a23be1cd3fdf838fc5df9bb55c97f3b8bdde6c786deb918576f43fb27c408b3` |
| `oecd_itic/pr55/PROVENANCE.txt` | 1,194 | `87cbfa31efb52c9291c17925989ae6643ac955e2f484c067adf256a8efb3ad0a` |
| `oecd_itic/pr55/PROVENANCE_HS_ENERGY.txt` | 1,695 | `2a16769d354ee03a31887f95bd81813cb754e37ded84665b4a64bc2d5695658c` |
| `oecd_itic/pr55/itic_hs_energy_margin.csv` | 919,824 | `6c964a6f18ec09f71edc396d1786b14a3efe3f5a64412055c8cf34706b1f82bf` |
| `oecd_itic/pr55/itic_total_margin.csv` | 2,727,747 | `fea974dc32459ca7a3ed78a8e0eb245ad8d2e79860062fb42a88ce3aca691b6d` |

Per-file URLs are in `data/MANIFEST.csv`.
