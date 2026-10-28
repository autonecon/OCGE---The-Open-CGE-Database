# IMF World Economic Outlook, October 2026: GDP in current USD

Used by S02 (beta v5 Y, choice `gdp_imputed_ama_to_weo` in `build/config/s02/s02_choices.csv`): where WDI has no
base-year GDP and the UN AMA series is an imputation, S02 takes WEO GDP in current USD.

- Source: IMF DataMapper API, dataset WEO, indicator metadata `"source": "World Economic Outlook (October 2026)"`,
  `last-modified 2026-10-08 14:43:33` (from `https://www.imf.org/external/datamapper/api/v1/indicators`).
- Files fetched 2026-10-27 08:44 UTC (curl from the build box, TLS verified):
  - `weo_2026oct_NGDPD_raw.json` from `https://www.imf.org/external/datamapper/api/v1/NGDPD` (GDP, current prices, billions of USD)
  - `weo_2026oct_NGDPDPC_raw.json` from `https://www.imf.org/external/datamapper/api/v1/NGDPDPC` (GDP per capita, current USD)
- `weo_2026oct_ngdpd_2017_2023.csv`: both series for 2017-2023, country codes only (the raw files also hold group codes),
  no transformation. Values for years after a country's last actual are IMF projections; for 2022 the WEO marks
  most countries as actuals, Yemen's 2022 figure is an IMF estimate.
- "October 2026" is the WEO edition; the values used are for 2022.
- Yemen 2022: total 11.107 bn USD and 645.8 USD per head, which implies 17.2 m people against WDI's 38.22 m: the total most likely
  covers only part of the country. S02 uses per head x the WDI population (choice `weo_gdp_basis`): 24.68 bn USD, an estimate.
  South Sudan's implied population (11.02 m) equals WDI's. North Korea, Syria and Eritrea (2020 on) have no WEO value.
- Licence: IMF terms of use (free reuse with attribution: "IMF, World Economic Outlook, October 2026").
