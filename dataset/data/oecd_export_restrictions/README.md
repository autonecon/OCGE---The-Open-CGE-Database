# oecd_export_restrictions: OECD Inventory of Export Restrictions on Industrial Raw Materials, 2022 (for S10, fix-round item A2)

- **Source:** OECD Inventory of Export Restrictions on Industrial (Critical) Raw Materials, SDMX dataflow `OECD.TAD.ADM,DSD_QDD_TAD_EXP_RESTRIC@DF_QDD_TAD_EXP_RESTRIC,3.0` on `sdmx.oecd.org` (keyless). The exact query is in `fetch_oecd_export_restrictions_2022.sh`.
- **Fetched:** 2026-10-24 (UTC+7) by worker wB (QA finding HIGH-2).
- **Licence:** OECD terms, CC BY 4.0 since 2024-07-01. Redistributable with attribution.
- **Contents:** RUS, IND, CHN; policy types M1 (export tax), M2 (export surtax), M5 (fiscal tax on exports); HS 2007 six-digit products; one record per measure variation and attribute (`VAL` rate, `VAL_UNIT`, `HS8` national lines, `DATI` start, `END` end, `VAL_CONDITION`, `NOD` legal act, `LINK`).
- **Use:** the CHN rates in `dataset/build/config/s10/export_tax_rates_2022.csv` (every 2022 M1 measure: Customs Tariff Commission Announcement No. 18 of 2021, the 2022 tariff adjustment programme), read by `dataset/data/export_duty_schedules_2022/derive_export_duty_aves_2022.py`. The IND and RUS records are cross-references for the hand-entered regimes in `export_duty_schedules_2022/export_duty_regimes_2022.csv` (some IND records predate 2022 changes; the regimes file follows the 2022 notifications and the PIB release of 18 November 2022).
- **Coverage limits:** minerals, metals, scrap and wood only. CHN statutory export duties on fish (ch.03), animal products (ch.05), organic chemicals (ch.29) and raw hides (ch.41) (WTO TPR WT/TPR/S/458 Table 3.10) are not in the inventory and are not booked.

| File | Bytes | SHA-256 |
|---|---|---|
| `oecd_export_restrictions/fetch_oecd_export_restrictions_2022.sh` | 748 | see MANIFEST.csv |
| `oecd_export_restrictions/oecd_export_restrictions_rus_ind_chn_2022.csv` | 155628 | `e2eaa940b01f7cbdf06506f35ee73e0ca99762ae51978164e309664ce02f2709` |
