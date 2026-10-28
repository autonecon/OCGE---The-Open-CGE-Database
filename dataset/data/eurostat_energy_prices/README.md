# Eurostat non-household gas and electricity prices, for S11 domestic basic prices

- **Folder:** `data/eurostat_energy_prices/`
- **Source:** Eurostat dissemination API, SDMX 2.1, SDMX-CSV.
  - Gas, non-household consumers, bi-annual from 2007: `nrg_pc_203` (https://ec.europa.eu/eurostat/databrowser/view/nrg_pc_203/default/table), data URL https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/nrg_pc_203/?format=SDMX-CSV&startPeriod=2017-S1&endPeriod=2022-S2&compressed=false
  - Electricity, non-household consumers, bi-annual from 2007: `nrg_pc_205` (same pattern).
- **Fetch:** `fetch_eurostat_energy_prices.sh` (keyless). Fetched 2026-10-23 (UTC); Eurostat LAST UPDATE 19/10/26. sha256 in `fetch.log` and `data/MANIFEST.csv`.
- **Licence:** Eurostat reuse policy: free reuse with acknowledgement (CC BY 4.0 equivalent, Commission Decision 2011/833/EU).
- **Year:** 2022 (2022-S1 and 2022-S2; an annual figure is the simple or consumption-weighted mean of the two). 2017-S1 to 2021-S2 are in the same files, so 2017 is covered too.
- **Use:** S11 domestic basic prices (GTAP 12 ch.12 §12.3.6-12.3.8).
- **Coverage:** all consumption bands (`nrg_cons`, gas GJ bands and `TOT_GJ`; electricity MWh bands and `TOT_KWH`), all tax levels (`I_TAX` all taxes included, `X_VAT` excluding VAT and recoverable taxes, `X_TAX` excluding taxes and levies = the basic-price concept), currencies EUR, NAC, PPS. Gas units `GJ_GCV` and `KWH` (gross calorific value); electricity `KWH`. Missing cells (e.g. confidential DE 2022-S1 gas) are absent rows; `OBS_FLAG` keeps Eurostat flags (`e` estimated, `d` definition differs, `c` confidential, `p` provisional).
- **Key 2022 values (EUR, total band, EU27_2020):**
  - Gas, excluding taxes and levies: 19.73 (S1), 24.99 (S2) EUR/GJ GCV = 0.0710, 0.0900 EUR/kWh; all taxes 24.01, 29.42 EUR/GJ.
  - Electricity, excluding taxes and levies: 0.1634 (S1), 0.2029 (S2) EUR/kWh; all taxes 0.2211, 0.2540.
  - Examples, X_TAX: DE gas 2022-S2 20.40 EUR/GJ, electricity 0.1482 / 0.1831; FR gas 16.74 / 20.11 EUR/GJ, electricity 0.1241 / 0.1237 EUR/kWh.
