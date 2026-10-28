# BEA supply-use tables: value-added rows by industry (USA, 2017-2023)

- **Folder:** `data/bea_sut/`
- **Source:** U.S. Bureau of Economic Analysis, Input-Output Accounts, supply-use tables, `AllTablesSUP.zip` from `https://apps.bea.gov/industry/iTables%20Static%20Files/AllTablesSUP.zip`, file `Use_Tables_Supply-Use_Framework_1997-2023_Summary.xlsx` (the Use of Commodities by Industries, summary level, 71 industries, supply-use framework at basic prices; 2024 comprehensive update, file dated 2024-09-06). Zip SHA-256 `fe60d189c01b89df331209977b644c7c4a18d48fee307d7b9e9c3a80cc912de3` (fetched 2026-10-25).
- **Fetch:** `fetch_bea_sut.sh` (keyless). It downloads the zip, extracts the summary Use table and writes the value-added rows for 2017-2023. Re-fetching can give other bytes if BEA revises.
- **Licence:** U.S. government work, public domain. Cite U.S. Bureau of Economic Analysis.
- **Contents:** `bea_use_sut_summary_va_2017_2023.csv`: year, industry_code, industry, V001 (compensation of employees), T00OTOP (other taxes on production), T00OSUB (less: other subsidies on production), V003 (gross operating surplus), VABAS (value added at basic prices). Million USD, current prices. The government industries (GFGD, GFGN, GFE, GSLG, GSLE) have no T00OTOP or T00OSUB (blank).
- **Use:** S12 step 5 (choice `usa_other_production_taxes`, independent QA MEDIUM-1): the USA D29X39 share of value added is T00OTOP - T00OSUB of the base year by industry group, in place of the FIGARO 2022 USA estimate. 2022: other taxes on production 773.9 bn, other subsidies on production 24.4 bn (2021: 731.2 and 505.2).

| File | Bytes | SHA-256 |
|---|---|---|
| `bea_sut/fetch_bea_sut.sh` | 1679 | `98ccddb8a4d1b1d578052564ab6c5dc7ae32f27ef27866278f268a8b92314958` |
| `bea_sut/bea_use_sut_summary_va_2017_2023.csv` | 34294 | `bd14aaaa7e774ebf2cad94ecf1afd227f13301bebae885ec994bd5df336baf04` |
