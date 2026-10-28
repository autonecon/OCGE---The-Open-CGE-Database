# IEA End-Use Prices (API dump, fetched 2026-10-23)

- **Folder:** `data/iea_end_use_prices/`
- **Source page:** [https://www.iea.org/data-and-statistics/data-tools/end-use-prices-data-explorer](https://www.iea.org/data-and-statistics/data-tools/end-use-prices-data-explorer)
- **Download URL / API:** https://api.iea.org/prices (keyless JSON, the whole dataset in one call; 42,511 records, 163 countries and regions)
- **Version:** API state of 2026-10-23 (records updated to 2026-01-06)
- **Download date / origin:** 2026-10-23 UTC by the S11 prices thread; copied from the project share s11_prices/raw/ on 2026-10-25 (Fable QA B-07)
- **Licence:** IEA terms of use (https://www.iea.org/terms): internal use with citation; DO NOT redistribute the raw file
- **Coverage (2022 or year-rule fallback):** natural gas and electricity end-use prices only for 2000, 2010 and 2025 in most non-OECD countries; no 2022 gas rows for the gas exporters
- **Units:** per row (`USD/MWh`, `National currency/MWh`, `USD/l`, ...); `CODE_INDICATOR = PRICE` is the annual average end-use price including taxes
- **Valuation basis / concept:** end-use (purchasers') prices by sector (industry, residential, power generation)
- **How it is used (PLAN.md stage):** S11 (Fable QA C-02): the cited source of the Algeria regulated gas price row `dza_gas_industry_2025` in `build/config/s11/transcribed_prices_2022.csv` (Algeria, industry, natural gas, 2025: 171.96 DZD/MWh); not read by the build.

## Files

| File | What |
|---|---|
| `iea_api_prices.json.gz` | Raw API response, gzipped (`gzip -n -9`) |
| `iea_fetch.log` | Fetch time, ETag and hashes |
