# wto_agims_trq: WTO AG-IMS tariff-quota fill notifications (Table MA:2)

- **Source:** WTO Agriculture Information Management System, Tariff and Other Quotas, Table MA:2 (https://agims.wto.org/en/TariffandOtherQuotas/TRQSearchResults). The members' notifications are G/AG/N/<member>/<n>.
- **Fetched:** 2026-10-24 (UTC+7) by worker wE2 (round-3 fix, QA round 2 P4). `fetch_agims_ma2.sh` repeats the fetch; the raw JSON dump (about 21 MB, every member) had SHA-256 `fcea967d82f666c61a62a5a656268cfcb4e32f6575149b0fd8e545d032f3f0c6` and is not kept.
- **Licence:** WTO terms of use (official documents, free reuse with attribution).
- **Contents:** `agims_ma2_can_che_nor_jpn_isr_chn_2019_2023.csv`: one row per member, implementation year and tariff quota (TQID) for CAN, CHE, NOR, JPN, ISR and CHN, 2019-2023: notification symbol, product description, the national tariff lines as notified, unit, quota quantity, in-quota imports, not-opened flag and reporting-year type.
- **2022 notifications used:** G/AG/N/CAN/157 (22 quotas), G/AG/N/CHE/124 (26), G/AG/N/JPN/283 (20, Japanese fiscal year 2022), G/AG/N/CHN/70 (7), and, checked only, G/AG/N/NOR/125 and G/AG/N/ISR/93.
- **Use:** S10 `trq_outside_kor_pan` (`dataset/build/s10_tariffs/trq.py`): fill = in-quota imports over the quota quantity; the MAcMap 90/98 percent rule sets each quota line's regime.
