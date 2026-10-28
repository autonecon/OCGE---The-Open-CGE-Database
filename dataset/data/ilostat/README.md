# ILOSTAT (ILO) employment, earnings and labour share

- **Folder:** `data/ilostat/`
- **Source page:** [https://ilostat.ilo.org/data/bulk/](https://ilostat.ilo.org/data/bulk/)
- **Download URL / API:** https://rplumber.ilo.org/data/indicator?id=<ID>&format=.csv.gz
- **Version:** as published 2026-10
- **Download date / origin:** 2026-10-20
- **Licence:** CC BY 4.0 (ILO)
- **Coverage (2022 or year-rule fallback):** occupation x ISIC: 104 regions (missing CHN DEU RUS CAN KOR SAU NLD and others, see coverage.md); earnings by ISIC 148; labour share 158
- **Units:** thousands of persons; mean monthly earnings in current USD; percent
- **Valuation basis / concept:** earnings = gross earnings of EMPLOYEES (excl. employer social contributions and self-employed)
- **How it is used (PLAN.md stage):** Stage (h): occupation SHARES of the labour bill (5 GTAP occupation groups); applied to national-accounts compensation (concepts.md C17).

## Files

| File | Bytes | SHA-256 |
|---|---|---|
| `ilostat/EAR_EMTA_SEX_ECO_CUR_NB_A.csv.gz` | 4,398,348 | `48979c5a41e7f18fe69c66f8698364134f6fa4fad31c27bcb00934332a7f2c39` |
| `ilostat/EAR_EMTA_SEX_OCU_CUR_NB_A.csv.gz` | 1,919,588 | `16ede593047720ef1eb6ad8633db1acb3c09ca46188bb1feb67daa16c58d70d8` |
| `ilostat/EMP_TEMP_SEX_ECO_NB_A.csv.gz` | 3,842,673 | `bfd9d87cdbb2564c324bb140790f2cec2bd9e8a502a7214a7c9def0c47934047` |
| `ilostat/EMP_TEMP_SEX_OCU_EC2_NB_A.csv.gz` | 20,776,021 | `1b4ed6b61bcc17d7d9d2eecaeaaac5dbd817573c4193aaa12d8ac7f4f14f7419` |
| `ilostat/EMP_TEMP_SEX_OCU_NB_A.csv.gz` | 1,723,432 | `09dc59e976783a84b479f6dde5408a355675bef21cd9ce57c99d565468eb29a7` |
| `ilostat/EMP_TEMP_SEX_STE_ECO_NB_A.csv.gz` | 12,258,682 | `c61c0062af7259e217a93d377078a2ba92226af3f83afd65eebfeaa14a9c8e55` |
| `ilostat/LAP_2GDP_NOC_RT_A.csv.gz` | 36,653 | `2bc0d5ece95cf02dcfb8444b643b539d9c1e5eb466093b83d1dbb55e6c86979e` |
| `ilostat/indicator_index.html` | 2,629,295 | `8269c5aef1754ea02650493ea87543f02e81512a1279ce4b2bbc750072ef0c60` |

Per-file URLs are in `data/MANIFEST.csv`.
