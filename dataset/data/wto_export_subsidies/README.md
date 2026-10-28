# wto_export_subsidies: WTO agricultural export-subsidy notifications (for S10, GTAP 12 ch.11C)

- **Source:** WTO Agriculture Information Management System (AG-IMS), Export Subsidies search, https://agims.wto.org/en/ExportSubsidies/SearchResults (dataset page https://data.wto.org/en/dataset/expsub). Keyless public search, "Export to Excel".
- **Fetched:** 2026-10-21 11:59 UTC+7 by `fetch_agims_export_subsidies.py`. All members, all products, implementation years 2015-2024.
- **Licence:** CC BY 4.0 (data.wto.org dataset page). Redistributable with attribution.
- **Files:** `agims_es1_members_rc_2015_2024.xls` (Table ES:1, 748 rows), `agims_es2_developing_art94_2015_2024.xls` (Supporting Table ES:2, Art. 9.4, 150 rows), `export_subsidies_latest_le2022.csv` (each member's latest year <= 2022, 16 members, 150 rows).
- **Positive outlays in the latest year <= 2022:** Türkiye 2022 (ES:1, USD 1.56 m: eggs, cut flowers, preserves), Korea 2022 (ES:2, KRW 29.13 bn), Morocco 2022 (ES:2, MAD 336.1 m), Mauritius 2021 (ES:2, MUR 0.19 m), Tunisia 2019 (ES:2, TND 15.8 m), Pakistan 2017 (ES:2, wheat freight support, USD 338.6 m). Brazil, Canada, Iceland and Norway notified zero for 2022. The EU's latest is 2019 and the US's latest is 2015, both zero.
- **GTAP:** WTO notifications override the IOT; otherwise the IOT structure is kept (ch.11C pp.1-2; Aguiar et al. 2025 p.12, which for 2023 used Korea's 2023 and Türkiye/Morocco's 2022 notifications).
- **Year rule:** Mauritius, Tunisia and Pakistan are earlier-year fallbacks and are flagged in S10 (see the S10 config row `export_subsidy_year`).

| File | Bytes | SHA-256 |
|---|---|---|
| `wto_export_subsidies/agims_es1_members_rc_2015_2024.xls` | 396288 | `76ad93f3287ab6ce5df33cde361c4bb8d8aff7be976dc0c5e2fdbb9c48819718` |
| `wto_export_subsidies/agims_es2_developing_art94_2015_2024.xls` | 71680 | `2f3c3097e95989d31a756932cead4941c3a38675669fa97ff78fd1fc89ebee1f` |
| `wto_export_subsidies/export_subsidies_latest_le2022.csv` | 15367 | `cfe1e0f1b6cd70d174472c777cb25cfb156fd33e5c0a2f7f3a24958a408fa5e5` |
| `wto_export_subsidies/fetch_agims_export_subsidies.py` | 3172 | `44af137edba26f1425e0a7ff63f12684bb81045a359a3a1641afbd5b04641f70` |
