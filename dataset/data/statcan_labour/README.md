# Statistics Canada labour tables: 98-10-0456-01 (2021 Census, place of work status by industry sector, occupation broad category and gender) and 14-10-0416-01 (LFS, labour force characteristics by occupation, annual)

- **Folder:** `data/statcan_labour/`
- **Source page:** [https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810045601 ; https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1410041601](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=9810045601 ; https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=1410041601)
- **Download URL / API:** https://www150.statcan.gc.ca/n1/tbl/csv/98100456-eng.zip ; https://www150.statcan.gc.ca/n1/tbl/csv/14100416-eng.zip
- **Version:** 98-10-0456-01 released 2022-11-30 (server Last-Modified 2022-11-30); 14-10-0416-01 released 2026-01-09
- **Download date / origin:** 2026-10-20 (UTC 11:55), fetched by a cloud agent; see FETCH_NOTES.md; SHAs re-verified on disk
- **Licence:** Statistics Canada Open Licence (https://www.statcan.gc.ca/en/reference/licence); attribution required
- **Coverage (2022 or year-rule fallback):** 98-10-0456-01: Canada, 2021 Census (year rule: latest year at or before 2022), NOC 2021 broad categories (10 + total) x NAICS 2017 sectors (20 + total), employed labour force 15+ in private households, 25% sample. 14-10-0416-01: Canada and provinces, 1987-2025 incl. 2022, NOC occupation groups (not crossed by industry).
- **Units:** 98-10-0456-01: persons (units), plus 95% CI bounds; 14-10-0416-01: persons in thousands (rounded to nearest hundred), rates in percent
- **Valuation basis / concept:** counts of employed persons (Census: place of residence universe, all place-of-work statuses; LFS: annual average)
- **How it is used (PLAN.md stage):** Labour stage (GTAP 12 ch.14B, rule F16a): CAN occupation x industry from 98-10-0456-01 (2021) with 2022 occupation totals from 14-10-0416-01. NOC 2021 broad categories and NAICS 2017 sectors need a cited concordance to ISCO-08 groups and the 51 sectors (concept parity).

## Files

| File | Bytes | SHA-256 |
|---|---|---|
| `statcan_labour/14100416-eng.zip` | 8,977,705 | `d8cb954e0ffe8f14c9a1481cff9b2a0185450a54d59f912aff937453df3fe616` |
| `statcan_labour/98100456-eng.zip` | 102,604,595 | `209a84f4c8964dc030180e410be2a8beb57e9cadee056b944ae32fb30b70e4b3` |
| `statcan_labour/FETCH_NOTES.md` | 6,576 | `730943690341aa3c215bef2c9399d3eafd333dd6128d810550e0fca2aed96bba` |

Per-file URLs are in `data/MANIFEST.csv`.
