# WITS / UNCTAD TRAINS bulk: MFN and preferential rates including AVEs, 2017–2022

**NOT FOR PUBLICATION.** WITS/TRAINS terms: internal use only. Private repo only (David 2026-10-21 11:55 UTC+7).

- **What:** the WITS logged-in Bulk Download (TRAINS, UNCTAD AVE method, estimation code U2), all reporters, 2017–2022.
  - `trains_pref_ave_2017_2022.zip`: 587 members, 586 `AVEPref_<nomen>_<ISO>_<year>_U2.zip` files plus one stray `[Content_Types].xml`. 145 reporters, 106 files for 2022. Each inner CSV has `NomenCode, Reporter_ISO_N, Year, ProductCode, Partner, ExcludedFrom, Sum_Of_Rates, Min_Rate, Max_Rate, SimpleAverage, TotalNoOfLines, Nbr_Pref_Lines, Nbr_MFN_Lines, Nbr_NA_Lines, EstCode` at HS6.
  - `trains_mfn_ave_2017_2022.zip`: 616 members (614 `AVEMFN_*` plus two `MFN_H5_CRI_2021`/`MFN_H5_MUS_2021` files), 123 reporter codes (EU members are listed one by one). Inner CSV columns: `NomenCode, Reporter_ISO_N, Year, ProductCode, Sum_Of_Rates, Min_Rate, Max_Rate, SimpleAverage, Nbr_NA_Lines, Nbr_Free_Lines, Nbr_AVE_Lines, Nbr_Dutiable_Lines, TotalNoOfValidLines, TotalNoOfLines, EstCode`.
  - `TRAINSPreferenceBenficiaries.xls`, `AllCountries.xls`: the WITS reference tables that came with the bulk.
  - `groups/wits_pref_beneficiaries_full.csv` (28,410 rows, 660 group codes) and `groups/wits_tariff_measures_full.csv`: WITS Support Materials > TRAINS Tariff Measures and Preference Beneficiaries (https://wits.worldbank.org/WITS/WITS/Support%20Materials/TrfMeasures.aspx?Page=TfMeasures), downloaded with the WITS account. This full table has the group codes that the public 2018 workbook lacks (for example C57, C31, A84, C24, C47, C48).
- **Account:** the project's WITS account. No credential is stored here.
- **Retrieved:** inner files are dated 2026-10-19 (WITS job files inside are dated 2022-09 to 2025-07); copied locally 2026-10-21 11:19 UTC+7 under `an internal working folder`; committed 2026-10-22.
- **Integrity:** `trains_pref_ave_2017_2022.zip` has exactly the same 587 members (CRC and size) as the five `trains_pref_ave_2017_2022_partNof5.zip` files that built the v3.8 table (part sha256 86efb1f2…, 4e951311…, a8a17970…, 072d531d…, 4fb284a5…). `trains_mfn_ave_2017_2022.zip` is the same file v3.8 used (sha256 1a27bbfd…).
- **Use:** input to the fresh S10 tariff rebuild (`dataset/stages/S10_tariffs_taxes/S10_REBUILD_HANDOFF.md`). Read the zips in place; do not extract into the repo.
