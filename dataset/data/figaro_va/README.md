# Eurostat FIGARO value-added rows (D1, B2A3G, D29X39, D21X31)

- **Folder:** `data/figaro_va/`
- **Source:** Eurostat dissemination API, datasets `naio_10_fcp_ii4` (2022 and onwards, updated 2026-07-20) and `naio_10_fcp_ii2` (2014-2017, updated 2026-07-18): EU inter-country input-output table at basic prices, industry by industry. Rows `ind_ava` D1, B2A3G, D29X39, D21X31; `c_orig=DOM`; all 50 `c_dest` (49 economies and the rest of the world); 69 `ind_use` columns (64 industries plus final uses, which S12 ignores). JSON-stat 2.0.
- **Fetch:** `fetch_figaro_va.sh` (keyless). Fetched 2026-10-23. Re-fetching can give other bytes if the source revises; the SHA-256 of the files used is in `data/MANIFEST.csv`.
- **Licence:** Eurostat reuse policy (CC BY 4.0); cite Eurostat, FIGARO.
- **Year:** 2022 (2017 for the 2017 base year and for the S12 year-jump screen).
- **Units:** million EUR, current prices
- **Use:** S12 step 1: labour share D1/(D1+B2A3G) by industry for the 49 FIGARO economies (GTAP labour/capital split of the I-O table, Aguiar et al. 2025 p.8).

## Files

| File | Bytes | SHA-256 |
|---|---|---|
| `figaro_va/fetch_figaro_va.sh` | 628 | `9a731cf4da3910106524d9ce65c0017b013242e4dfd16d1c0e3cfb58b225ffc2` |
| `figaro_va/figaro_va_2017.json` | 208,194 | `ef3f5253ccccb5b68ce74f9fbc5809adf1bf4f5e48fce104b2e27ed915cd3fa9` |
| `figaro_va/figaro_va_2022.json` | 209,733 | `47679c8b064d3f2f8ef621926eb0065e7f27aba7674d7ffcf3008754d15d8b5d` |
