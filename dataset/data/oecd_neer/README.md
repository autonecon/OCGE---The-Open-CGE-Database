# oecd_neer: OECD Net Effective Energy Rates, 2021 and 2023 (for S10, fix-round item A1)

- **Source:** OECD Net Effective Energy Rates (the Taxing Energy Use / Effective Carbon Rates family), SDMX dataflow `OECD.CTP.TPS,DSD_NEER@DF_NEERS,1.1` on sdmx.oecd.org. Keyless.
- **Fetched:** 2026-10-24 by `fetch_oecd_neer.sh` (the exact query is in the script). The dataflow has 2018, 2021 and 2023. The build uses 2021, the latest year at or before the 2022 base (the year rule, `config/source_years.csv`; S10 choice `energy_tax_year` = `neer_2021`, checked by `S10-Hneeryear`); the 2023 rows are kept in the file for comparison and are not used.
- **Contents:** 86 countries; the six base sectors (AGRIFISH, ELEC, INDUSTRY, OFFROAD, RESCOM, ROAD) and the base energy sources (no aggregates such as `_T`, FFUEL, NCOMB, ENE, ENEXROAD); measures FUETAX (fuel excise), CARBTAX (carbon tax), ELETAX (electricity excise, recorded on the ELEC sector's inputs), TOTTAX = FUETAX + CARBTAX + ELETAX, SUBSID and ELESUBSID (fossil-fuel and electricity subsidies, negative) and TOTSUBS, in EUR per GJ at current prices (PRICE_BASE V), and the tax base TAXBTJ in TJ. ETS permit prices are a separate measure and are not fetched (not a tax on products). The USA has no values in this dataflow.
- `eur_usd_ert_bil_eur_a.csv`: Eurostat `ert_bil_eur_a`, USD per EUR, annual average 2021-2023 (1.1827, 1.0530, 1.0813), for the EUR-to-USD conversion of the same year.
- **Licence:** OECD terms, CC BY 4.0 since 2024-07-01; Eurostat reuse policy (CC BY 4.0). Redistributable with attribution.
- **Use:** S10 `s10_tariffs/energy_tax.py`: revenue = rate (EUR/GJ) x base (TJ) x 1000, by sector and energy row, spread over the IO columns of `config/s10/energy_tax_classes.csv` (tls_energy_s10.csv).

| File | Bytes | SHA-256 |
|---|---|---|
| `oecd_neer/fetch_oecd_neer.sh` | 1223 | `cc5bcaaf32c2068db89cd1cfe6145f41b9c36263629ba1f2ca619c1519c85126` |
| `oecd_neer/neers_2021_2023.csv` | 5666331 | `99eb0bed0c0d7ae720be59895dd124baf19f81755338979af0e5ce8747dd7a13` |
| `oecd_neer/eur_usd_ert_bil_eur_a.csv` | 309 | `17e655f2be36fa3af65320d3094ba39d11ae9594cff15f61d4eaa809ab9c830a` |
