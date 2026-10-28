# EIA US domestic energy prices 2022 (keyless), for S11 domestic basic prices

- **Folder:** `data/eia_us_prices_2022/`
- **Source:** US Energy Information Administration.
  - Annual Coal Report 2022 (https://www.eia.gov/coal/annual/, PDF https://www.eia.gov/coal/annual/archive/0584_2022.pdf). The live xls tables on that page now hold the 2024 edition, so tables 28 and 31 for 2022 are extracted from the archived PDF by `extract_acr_tables.py` (`pdftotext -layout`). Cells keep EIA codes: `w` = withheld, `-` = no data.
  - Electric Power Annual 2022, archived edition (https://www.eia.gov/electricity/annual/archive/2022/xls/epa_02_10.xlsx, `epa_02_04.xlsx`), and the state price history https://www.eia.gov/electricity/data/state/avgprice_annual.xlsx (1990 to latest).
  - Natural gas annual prices by state, dnav XLS (https://www.eia.gov/dnav/ng/ng_pri_sum_a_EPG0_PIN_DMCF_a.htm and siblings): industrial (`PIN`), electric power (`PEU`), citygate (`PG1`), wellhead (`FWA`), and the US summary `NG_PRI_SUM_DCU_NUS_A.xls`.
- **Fetch:** `fetch_eia_us_prices_2022.sh` (no API key; needs curl, pdftotext, python3). Fetched 2026-10-23 (UTC). sha256 in `fetch.log` and `data/MANIFEST.csv`.
- **Licence:** US government work, public domain; cite EIA.
- **Year:** 2022. The dnav XLS and `avgprice_annual.xlsx` carry full history, so 2017 is in the same files; ACR 2017 was not fetched.
- **Use:** S11 domestic basic prices (GTAP 12 ch.12 §12.3.6-12.3.8).
- **Units and basis:** coal USD per short ton, f.o.b. mine (rail/barge), mines over 25,000 st; electricity US cents per kWh, average revenue to ultimate customers (includes taxes passed through in revenue); gas USD per thousand cubic feet.
- **Caveat:** the state wellhead series (`FWA`) and the US wellhead price stop in 2012; there is no 2022 wellhead price. Use citygate or Henry Hub (`data/eia_prices/`) instead.
- **Key 2022 values:**
  - Coal average sales price, US total 54.46 USD/st (underground 96.47, surface 29.20; ACR table 28). By rank (table 31): bituminous 97.96, subbituminous 16.55, lignite 21.79, anthracite 155.03. Wyoming 14.84, West Virginia 127.52, Illinois 35.96.
  - Electricity, US average (EPA table 2.10): residential 15.04, commercial 12.41, industrial 8.32, transportation 11.59, all sectors 12.36 cents/kWh.
  - Natural gas, US: industrial 7.69, electric power 7.51, citygate 6.87 USD/Mcf; imports 6.33, exports 9.64 (LNG exports 12.24). 2017: industrial 4.08, electric power 3.51, citygate 4.16.

## Files

| File | Content |
|---|---|
| `ACR_2022_0584.pdf` | Annual Coal Report 2022 |
| `acr2022_table28_price_by_state_minetype.csv` | Table 28, coal sales price by state and mine type, 2022 and 2021 |
| `acr2022_table31_price_by_state_rank.csv` | Table 31, coal sales price by state and rank, 2022 |
| `EPA2022_epa_02_10.xlsx` | EPA 2022 table 2.10, electricity price by state and sector, 2022 and 2021 |
| `EPA2022_epa_02_04.xlsx` | EPA 2022 table 2.4, US electricity price by sector, 2012-2022 |
| `avgprice_annual.xlsx` | Electricity price by state, sector and provider type, 1990 to latest |
| `NG_PRI_SUM_A_EPG0_{PIN,PEU,PG1,FWA}_DMCF_A.xls` | Gas industrial, electric power, citygate, wellhead price by state |
| `NG_PRI_SUM_DCU_NUS_A.xls` | US gas price summary (wellhead, imports, exports) |
