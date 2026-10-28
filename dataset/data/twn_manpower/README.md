# Taiwan labour: MoL table 2-10 employed persons by occupation, and DGBAS Manpower Survey 2022 annual report Table 49 (employed by industry x occupation) and Table 58 (weekly hours)

- **Folder:** `data/twn_manpower/`
- **Source page:** [https://statdb.mol.gov.tw/html/mon/c2100.htm](https://statdb.mol.gov.tw/html/mon/c2100.htm)
- **Download URL / API:** https://statdb.mol.gov.tw/html/mon/c2100.csv (TLS verification off, SHA recorded) ; https://ws.dgbas.gov.tw/001/Upload/463/relfile/11516/231112/table49.xls (+ .ods) ; .../231112/table58.xls (via Cloudflare WARP, TLS verified with the TWCA intermediate; see FETCH_NOTES.md and docs/fetch_routes/warp-tools_README.md)
- **Version:** MoL c2100 as downloaded 2026-10-20; DGBAS 111年人力資源調查統計年報 (2022) tables 49 and 58
- **Download date / origin:** 2026-10-20 (c2100 18:34; tables 49/58 ~20:13 UTC+7 via WARP)
- **Licence:** Taiwan Open Government Data License 1.0 (data.gov.tw dataset 37963); attribution DGBAS
- **Coverage (2022 or year-rule fallback):** TWN 2022 annual average, 11,418 thousand employed. Table 49: 19 industry sections (SIC Rev.11 ~ ISIC Rev.4 A-S) x 7 occupation groups (SOC Rev.6 ~ ISCO-08 1, 2, 3, 4, 5, 6 and 7-9 combined), total/male/female. Table 58: weekly hours, same layout (reference only).
- **Units:** thousand persons; hours per week (Table 58)
- **Valuation basis / concept:** persons employed, civilian 15+, household survey annual average (Taiwan area excl. Kinmen and Lienchiang); not wages
- **How it is used (PLAN.md stage):** Labour stage (GTAP 12 ch.14B, rule F16a): TWN occupation x industry cross table. The 7 groups map exactly to the 2-group and 5-group splits (ISCO 6-9 is one 5-group). c2100 gives the control totals.

## Files

| File | Bytes | SHA-256 |
|---|---|---|
| `twn_manpower/FETCH_NOTES.md` | 3,618 | `4340939b97636d48858161e3bda5131d0d3a4a3bb924548704e217f8639d2cff` |
| `twn_manpower/dgbas_2022_table49_employed_by_occupation_by_industry.ods` | 26,198 | `7df6786ca251e6cc257ff45a0678b11f0e0d77aa6e37d06364bceeda9ac7e653` |
| `twn_manpower/dgbas_2022_table49_employed_by_occupation_by_industry.xls` | 48,128 | `c9902ef8a8958215088e43c12e12e582e83de54f74354fccfee1f1112cf94eb8` |
| `twn_manpower/dgbas_2022_table58_weekly_hours_by_industry_occupation.xls` | 49,664 | `55c781769f3b691e2aec249638fae38026c8bc6eb7cd659927b64b43440c7455` |
| `twn_manpower/mol_c2100_employed_by_occupation.csv` | 3,637 | `b042215237188bbe32fc0bc661f5818234b00765c6106714ac035132d56bed73` |

Per-file URLs are in `data/MANIFEST.csv`.
