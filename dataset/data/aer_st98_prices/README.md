# AER ST98 price tables (AECO-C natural gas hub price), for S11 domestic basic prices

- **Folder:** `data/aer_st98_prices/`
- **Source:** Alberta Energy Regulator, ST98 Alberta Energy Outlook, "Prices and Capital Expenditure" data workbooks. 2024 edition https://www.aer.ca/documents/sts/ST98/2024/st98-2024-prices-and-capital-expenditure-data.xlsx and 2023 edition https://www.aer.ca/documents/sts/ST98/2023/ST98-Price-Capital-Expenditure-data.xlsx (linked from https://www.aer.ca/providing-information/data-and-reports/statistical-reports/st98/executive-summary).
- **Fetch:** `fetch_aer_st98_prices.sh` (keyless). Fetched 2026-10-23 (UTC). sha256 in `fetch.log` and `data/MANIFEST.csv`.
- **Licence:** AER copyright (https://www.aer.ca/copyright-and-disclaimer): free reproduction for personal and public non-commercial (educational) use with the AER identified as source and not presented as an official version; commercial redistribution of multiple copies needs AER permission.
- **Year:** 2022 (actual). Also 2023 actual in the 2024 edition; forecasts for later years are in the same table and must not be used. 2017 is not in either workbook.
- **Where:** sheet `Tables`, Table S1.2 "Natural gas prices", row "AECO-C price (Cdn$/GJ)". Footnote: historical values from the Canadian Gas Price Reporter.
- **Units and basis:** Canadian dollars per gigajoule, annual average, AECO-C hub (Alberta wholesale; excludes transmission to and distribution at the consumer).
- **Key values:** AECO-C 2022 = **5.10 Cdn$/GJ** (both editions agree); 2023 = 2.74; 2021 = 3.37 (2023 edition). Henry Hub 2022 = 6.52 US$/MMBtu (same table).
- **Compare:** StatCan 25-10-0059 (`data/statcan_ng_distribution/`) gives a 2022 Alberta industrial delivered value of 3.87 CAD/GJ, below the hub price, consistent with it covering distribution charges only for many Alberta customers.
