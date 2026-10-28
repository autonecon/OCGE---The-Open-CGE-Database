# World Bank WDI US GDP deflator and CPI, for S11 price conversion

- **Folder:** `data/wdi_us_deflator/`
- **Source:** World Bank World Development Indicators API v2 (keyless JSON): https://api.worldbank.org/v2/country/USA/indicator/NY.GDP.DEFL.ZS?format=json&date=2015:2024&per_page=100 and the same for `FP.CPI.TOTL`.
- **Fetch:** `fetch_wdi_us_deflator.sh` (keyless). Fetched 2026-10-23 (UTC); WDI last updated 2026-10-08. sha256 in `fetch.log` and `data/MANIFEST.csv`.
- **Licence:** CC BY 4.0 (World Bank open data terms); cite World Bank, World Development Indicators.
- **Year:** 2015-2024 (covers 2017, 2022 and 2024).
- **Use:** S11 domestic basic prices (GTAP 12 ch.12 §12.3.6-12.3.8): bring the IEA fossil-fuel subsidy file (`data/iea_subsidies/`, real 2024 USD) to 2022 nominal USD.
- **Key values:**

| Year | GDP deflator (2020=100) | CPI (2010=100) |
|---|---|---|
| 2017 | 94.897 | 112.412 |
| 2020 | 100.000 | 118.691 |
| 2021 | 104.563 | 124.266 |
| 2022 | 112.000 | 134.211 |
| 2023 | 116.144 | 139.736 |
| 2024 | 119.027 | 143.857 |

  2024 USD to 2022 USD: multiply by 112.000/119.027 = 0.94096 (GDP deflator) or 134.211/143.857 = 0.93295 (CPI).
