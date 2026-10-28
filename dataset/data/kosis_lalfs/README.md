# KOSIS (Statistics Korea) Local Area Labour Force Survey: national employed persons by sex x industry x occupation, table DT_1ES3B33S

- **Folder:** `data/kosis_lalfs/`
- **Source page:** [https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1ES3B33S&conn_path=I2](https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1ES3B33S&conn_path=I2)
- **Download URL / API:** https://kosis.kr/statHtml/statHtml.do?orgId=101&tblId=DT_1ES3B33S&conn_path=I2 (KOSIS large download, headless Chrome via Cloudflare WARP; see FETCH_NOTES.md and docs/fetch_routes/warp-tools_README.md)
- **Version:** DT_1ES3B33S (KSIC 10th / KSCO 7th), half-yearly 2013 H1 - 2024 H1, as downloaded 2026-10-20
- **Download date / origin:** 2026-10-20 ~20:18 UTC+7 via WARP; TLS verified
- **Licence:** KOSIS public statistics, free reuse with attribution ("Source: Statistics Korea, Local Area Labour Force Survey, KOSIS"); KOGL type 1 assumed, exact type not recorded
- **Coverage (2022 or year-rule fallback):** Korea, national, half-years 2013-2024 (2017 and 2022 present). Sex x 21 KSIC sections (~ISIC Rev.4 A-U) x 9 KSCO major groups (~ISCO-08 1-9; no armed forces). 2022 H1 total 28,078.3 thousand; H2 28,417.9; 10 of 189 2022 cells blank.
- **Units:** thousand persons; RSE in percent
- **Valuation basis / concept:** persons employed (LALFS, a larger half-yearly survey than the monthly EAPS); not wages
- **How it is used (PLAN.md stage):** Labour stage (GTAP 12 ch.14B, rule F16a): KOR occupation shares within each industry from the mean of 2022 H1 and H2; EAPS/ILOSTAT 2022 totals stay the control totals.

## Files

| File | Bytes | SHA-256 |
|---|---|---|
| `kosis_lalfs/FETCH_NOTES.md` | 3,431 | `ed4067371363ea815e85ac43a320dcf9c49761df6f3ed5c25795a0f29029047d` |
| `kosis_lalfs/kosis_DT_1ES3B33S_sex_industry_occupation_2013H1-2024H1.xls` | 1,929,592 | `b70156df939ef1dccdc3bdb2fe5412e6bf500e12e771ac19a98b9d5e7b7969bd` |
| `kosis_lalfs/kosis_DT_1ES3B33S_sex_industry_occupation_2013H1-2024H1_cp949.csv` | 193,122 | `15c2e5e2674c3bec192b13f5cab2ba45909c7252d127f428d2239e84f82b4705` |
| `kosis_lalfs/kosis_DT_1ES3B33S_sex_industry_occupation_2013H1-2024H1_utf8.csv` | 214,338 | `c28972952fccd4890a1b8a2b36d48675ccf266826b872e1bb68b47cf2414a253` |

Per-file URLs are in `data/MANIFEST.csv`.
