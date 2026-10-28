# US EIA International Energy Statistics, bulk

- **Folder:** `data/eia_intl/`
- **Source page:** [https://www.eia.gov/international/data/world](https://www.eia.gov/international/data/world)
- **Download URL / API:** https://www.eia.gov/opendata/bulk/INTL.zip
- **Version:** bulk last-modified 2026-10-19
- **Download date / origin:** 2026-10-20
- **Licence:** US government work, public domain (cite EIA)
- **Coverage (2022 or year-rule fallback):** dry gas 157 regions, crude+NGPL 158 regions for 2022; refined products INTL.54-1 ends 2014 (no 2022)
- **Units:** bcm / kb/d as per series
- **Valuation basis / concept:** physical volumes
- **How it is used (PLAN.md stage):** Stage (g): volumes to value energy output where no I-O value exists (non-ICIO Gulf and oil exporters). Re-extract INTL.26 dry gas; the committed production_2022.csv gas column is wrong (energy_committed_pr55). Cross-check vs EI within +-8%.

## Files

| File | Bytes | SHA-256 |
|---|---|---|
| `eia_intl/INTL.txt` | 128,859,754 | `cb9c045cb092fd38c0df4edc27715cb48ae2485d2c0401b53409dc21ac63abbc` |
| `eia_intl/INTL.zip` | 24,264,743 | `367a8d8f93bc3c54f96c755e67ce68783ae92580a5751faa545a265376483216` |

Per-file URLs are in `data/MANIFEST.csv`.
