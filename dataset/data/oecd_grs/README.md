# oecd_grs: OECD Global Revenue Statistics, 2017-2022 (for S10, GTAP 12 ch.15)

- **Source:** OECD Global Revenue Statistics Database, comparative tax revenues, SDMX dataflow `OECD.CTP.TPS,DSD_REV_COMP_GLOBAL@DF_RSGLOBAL,2.1`. Keyless.
- **Fetched:** 2026-10-21 11:59 UTC+7 by `fetch_grs_2017_2022.sh` (the exact query is in the script).
- **Licence:** OECD terms, CC BY 4.0 since 2024-07-01. Redistributable with attribution.
- **Contents:** general government (S13), years 2017-2022, units PT_B1GQ (% of GDP), USD and XDC (national currency). Codes T_1000, T_1100 (personal income), T_1200 (corporate), T_2000 (SSC total), T_2100/T_2200/T_2300 (employee/employer/self-employed SSC), T_3000 (payroll), T_4000 (property), T_4100, T_5000, T_5111 (VAT), T_5121 (excises), T_5123 (customs and import duties), TOTALTAX.
- **Coverage (PT_B1GQ, any year):** T_1100/T_1200 141 countries, T_2000 129, T_3000 146, T_4000 143.
- **Use:** S10 income and factor taxes (ch.15 pp.1-3) and the report-only product-tax and customs checks. IMF WoRLD (`imf_world/`) is the fallback.

| File | Bytes | SHA-256 |
|---|---|---|
| `oecd_grs/fetch_grs_2017_2022.sh` | 709 | `41c9760c16eb1fd32be57ba63d061d9c0d5fa39b03b7c7652e80e934d43a24f5` |
| `oecd_grs/grs_rsglobal_2017_2022.csv` | 3569198 | `282ed8d32609b4c7604eb226482f217a1cdbbbc235482d7d8f76a9ed22dc530e` |

## T_5121 and T_5124 (fix round, 2026-10-24)

- `grs_rsglobal_5121_5124_2017_2022.csv`: the same dataflow, T_5121 (excises) and T_5124 (taxes on exports), S13, 2017-2022, PT_B1GQ, USD and XDC, fetched 2026-10-24 by `fetch_grs_5121_5124_2017_2022.sh`.
- **Use:** T_5124 2022 in USD is the export-tax total of S10 `s10_tariffs/export_tax.py` (fix-round item A2). T_5121 is report-only (it mixes fuel, tobacco and alcohol excise).

| File | Bytes | SHA-256 |
|---|---|---|
| `oecd_grs/fetch_grs_5121_5124_2017_2022.sh` | 596 | `10cc2de0fe38aa6c43b88639f65d2f37f45d9dfbd703b102e8c9ae146b98cf97` |
| `oecd_grs/grs_rsglobal_5121_5124_2017_2022.csv` | 572858 | `80630062a42819f0aaf96dad8d55b082a41de701707a0686da7942cb7486f7f5` |
