# wto_tpr: WTO Trade Policy Review Secretariat reports (for S10, fix-round item A2)

- **Source:** WTO Trade Policy Reviews, reports by the Secretariat, public PDFs on www.wto.org (`/english/tratop_e/tpr_e/s<N>_e.pdf`).
- **Fetched:** 2026-10-24 by `fetch_wto_tpr.sh`.
- **Licence:** WTO documents, public; reproduction with attribution (WTO terms of use). Redistributable.
- **Use:** the export-duty product lists and rates in `dataset/build/config/s10/export_tax_products_2022.csv`; each row cites the report, table and printed page. Revenue cross-checks in the S10 spec.

| Report | Member | Date | Used for |
|---|---|---|---|
| WT/TPR/S/401 | Indonesia | 4 Nov 2020 | Table 3.6 export duties |
| WT/TPR/S/403 | India | 25 Nov 2020 | Table 3.16 export taxes 2019-20 (no 2022 revenue; not booked) |
| WT/TPR/S/412 | Argentina | 11 Aug 2021 | Table 4.3 and Table A3.2, Decree 1060/2020 |
| WT/TPR/S/416 | Russian Federation | 22 Sep 2021 | export duties to 2019 (no 2022 revenue; not booked) |
| WT/TPR/S/436 | Malaysia | 14 Dec 2022 | Table 3.9 export duties; 2022 revenue |
| WT/TPR/S/439 | Türkiye | 1 Feb 2023 | export taxes (hazelnuts, hides); stl and nfm at zero |
| WT/TPR/S/458 | China | 12 Jun 2024 | Table 3.10 export duties (chapters only) |
| WT/TPR/S/459 | Kazakhstan | 21 Aug 2024 | Table 3.12 export duties; Table 3.2 2022 revenue |

| File | Bytes | SHA-256 |
|---|---|---|
| `wto_tpr/fetch_wto_tpr.sh` | 415 | `42c7f4dce5f6266974d7729930b3fb717d726839c3c839e3c9529a4aba0fab5d` |
| `wto_tpr/wt_tpr_s401.pdf` | 4010452 | `339e822456b04dbe88a9577899894fc17467c2733daa55587469c28dd510b14e` |
| `wto_tpr/wt_tpr_s403.pdf` | 2993892 | `7ecb0e459a2e3ea486d544ead3f85ab67e196e88d44a523b74773981774c739f` |
| `wto_tpr/wt_tpr_s412.pdf` | 4475691 | `2cc95d09dbd5797b7e2a0f948b46b1363cfd69d453c8c7e13d463bf354d87431` |
| `wto_tpr/wt_tpr_s416.pdf` | 2525582 | `01e529860bd96fd503b91678efd724e32791dd2b73e3234978b1f88e9f44efda` |
| `wto_tpr/wt_tpr_s436.pdf` | 2785556 | `f664bd56b4972f83fc1fe02902f47d28bf0be8e130174f9df90ce5482a552767` |
| `wto_tpr/wt_tpr_s439.pdf` | 3129590 | `7274954e9d6384f3ca1969464b38c2e776a07c57c2c6b1d5809679733d80ac5b` |
| `wto_tpr/wt_tpr_s458.pdf` | 3256194 | `8aff91c88cac156006c6bf490b25252113646f12df119572e057b3489d7ea217` |
| `wto_tpr/wt_tpr_s459.pdf` | 1819239 | `cca130bfe297f96a74363c67cba084448f4637cf59ba8591ae7c4b6fc43b91d6` |
