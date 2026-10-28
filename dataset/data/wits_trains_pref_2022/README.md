# WITS TRAINS preferential extracts used by S10

Fetched 2026-10-21 from the public WITS SDMX API.

A blank partner returns MFN only. A named partner or group code returns the preferential HS6 simple average (`TARIFFTYPE=PREF`, `OBS_VALUE_MEASURE=SimpleAverage`). The year is 2022 where that query has a partner other than `000`, otherwise the latest earlier year. Nothing after 2022 is used.

`availability/` is the data-availability response for each reporter. `sdmx/` is one structure-specific file per reporter, year and partner code. The gzip members have mtime 0. `trains_preference_beneficiaries_2018.csv` is the public beneficiaries workbook dated 2018-09-14, converted to csv. A group code that is not in that workbook is not given a membership list.

The WITS bulk zip for job 3187139 (sha256 `b57cbef550aede8c7e65ac40b2fe0f131773a69b2a64c0ce69f0c2f6e1cc9237`, Preferential Rates Including AVE) is in `dataset/data/trains_pref_2022_supp/` and is applied under the year rule. The latest year wins per importer and partner. Kenya 2022 H6, Myanmar 2022, and the 2021 AVEPref files for the UAE, Kuwait and Cambodia are in that zip. A 2020 file is used only where it is the latest year for that partner and the group has a membership list.

These files are the public API extract. The rates are TRAINS data and stay in this private repository.
