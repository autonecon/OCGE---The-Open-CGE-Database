# Uganda 2022 gold mine output (beta v4 P39)

- **Folder:** `data/gold_uga_2022/`
- **Source:** USGS Minerals Yearbook 2022, Gold (tables and text), and the Uganda Bureau of Statistics Statistical Abstract 2023, gathered by David's agent on 2026-10-26 (URLs in `data/MANIFEST.csv`). `.txt` files are pdftotext extracts. The UBOS PDF (9.8 MB) is not kept; its extract is.
- **Licence:** USGS is US public domain. UBOS states no licence, so it is a build input only and users are pointed to the source.
- **Year:** 2022.
- **Use:** S07 choice `gold_reexport`, through the transcribed row in `build/config/s07/gold_reexport_2022.csv`; not read by the build.
  - USGS MYB 2022 Gold, Table 8: Uganda mine production 3,200 kg in 2022 (txt line 905; 1,500 to 2,900 kg in 2018-2021). This is the value used. It is an estimate that includes artisanal output.
  - UBOS Statistical Abstract 2023: gold in mineral production 0.00421 (txt line 9751, apparently licensed production only) and gold exports 753 kg in 2022 (txt line 17762, against 19,150 kg in 2021). Context only: the gap to USGS and to the partners' reports (BACI, about 1.9 bn USD, about 33 t) is flagged in the S07 basis.

## Files

| File | Bytes | SHA-256 |
|---|---|---|
| `gold_uga_2022/USGS_MYB2022_gold.pdf` | 376,869 | `b475e7796a2a2e4c5412883ad6da623169ca03134f2c5af373819150b436d16a` |
| `gold_uga_2022/USGS_MYB2022_gold.txt` | 99,190 | `1df57b6038b72e90dc9b88774e6b2ff94adbb87d028ccf4a1e14d7f211c7e019` |
| `gold_uga_2022/USGS_MYB2022_gold_tables.xlsx` | 140,184 | `536f355dc1c7ccb35d0d4270a0a5563446faf2861d48e51128fb8c0759bb426d` |
| `gold_uga_2022/UBOS_Statistical_Abstract_2023.txt` | 1,221,534 | `d98156a93af20dc2489f94fb33f240d5563c114a7c43048bd10b744c2a466606` |
