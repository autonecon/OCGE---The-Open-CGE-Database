# imf_gfs: IMF Government Finance Statistics, taxes on international trade (for S10, fix-round item A2)

- **Source:** IMF Government Finance Statistics, Statement of Operations, SDMX 2.1 dataflow `IMF.STA,GFS_SOO` on `api.imf.org` (keyless). The exact query is in `fetch_gfs_soo_trade_taxes_2017_2023.sh`.
- **Fetched:** 2026-10-24 (UTC+7) by worker wB (QA finding HIGH-2).
- **Licence:** IMF terms of use (https://www.imf.org/external/terms.htm); data redistributable with attribution.
- **Contents:** RUS, IND, CHN; general government (S13) and budgetary central government (S1311B); national currency (XDC); 2017-2023. Indicators G1 (revenue), G11 (taxes), G115 (taxes on international trade), G1151 (customs and other import duties), G1152 (taxes on exports).
- **Use:** S10 `S10-Rxtaxrev` (report only). OECD GRS T_5124 has no 2022 value for these three countries, so S10 books them from statutory rates (`dataset/build/config/s10/export_tax_rates_2022.csv`) and compares the implied revenue with G1152.
- **2022 values (S13, G1152):** RUS 2,730,231 million RUB (2021: 2,530,841; 2023: 1,408,853). CHN 0 (China reports its export duties inside customs revenue G1151, 291,331 million CNY). IND: no S13 value; S1311B reports 0 for 2022.

| File | Bytes | SHA-256 |
|---|---|---|
| `imf_gfs/fetch_gfs_soo_trade_taxes_2017_2023.sh` | 833 | see MANIFEST.csv |
| `imf_gfs/gfs_soo_trade_taxes_rus_ind_chn_2017_2023.csv` | 153733 | `84ac09688acd0ad87eb8f4bfbbeeca4a32d0c32a2d2f72e2af3867b89148fd81` |

## Gulf income taxes and social contributions (round-3 fix wE2, 2026-10-24)

- **Query:** `fetch_gfs_soo_income_ssc_gulf_2017_2023.sh`: SAU, ARE, QAT, KWT, BHR, OMN; S13 (general government), S1311 (central government) and S1314 (social security funds); percent of GDP (POGDP_PT); G1, G11, G111, G1111, G1112, G112, G113, G116, G12, G121, G1211, G1212; 2017-2023. The service returns SAU and ARE only.
- **Use:** S10 `income_tax_source` (GTAP 12 ch.15, general government): used where OECD GRS has no value and IMF WoRLD has no general-government value (SAU). 2022 SAU S13: G121 2.500, G1112 0.527, G116 0.603 (zakat, `gulf_zakat`), G113 0.009, G112 0, G1111 0 percent of GDP; S1314 holds all of G121 (GOSI).

| File | Bytes | SHA-256 |
|---|---|---|
| `imf_gfs/fetch_gfs_soo_income_ssc_gulf_2017_2023.sh` | see MANIFEST.csv | see MANIFEST.csv |
| `imf_gfs/gfs_soo_income_ssc_gulf_2017_2023.csv` | 512954 | `447c03221005a4bcd1f976df7d032bd3cdab91f3707628329d0e97f08e3cd031` |
