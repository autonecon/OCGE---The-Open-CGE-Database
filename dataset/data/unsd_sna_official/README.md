# UN National Accounts Official Country Data, table 1.1: GDP by expenditure at current prices, Cuba 2021-2024

Used by S02 (beta v5, choice `gdp_lcu_official_rate`, `build/config/s02/gdp_official_rate_2022.csv`): Cuba's 2022 GDP,
household and government consumption and GFCF in Cuban pesos, converted at the official 2022 rate (24 CUP per USD).

- Source: UNdata, SNA dataset, table 1.1 "Gross domestic product by expenditures at current prices", Cuba (country code
  192), series 300, SNA 1993, Cuban peso, as reported to UNSD by the Oficina Nacional de Estadística e Información (ONEI).
- Fetched 2026-10-27 09:33 UTC from `https://data.un.org/Data.aspx?d=SNA&f=group_code%3a101%3bcountry_code%3a192`
  (HTML table; onei.gob.cu is not reachable from the build box). `cub_table11_gdp_expenditure_2021_2024.csv` holds every
  row of the page as published (value in pesos); nothing is transformed.
- 2022: GDP 633.442 bn CUP; household consumption 377.846; government consumption 206.078; GFCF 72.713; exports 253.465;
  imports 309.051. The UN AMA national-currency file has 147.1 bn CUP for Cuban 2022 GDP, which is not this series.
- Licence: UN data terms of use (free reuse with attribution: "UNSD, National Accounts Official Country Data").
