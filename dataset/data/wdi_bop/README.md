# wdi_bop: World Bank WDI balance-of-payments goods and services, 2022

Used by the beta v5 S16 report check S16-Rmacrobn (trade-balance gaps in USD bn with a goods and services split).
Licence CC BY 4.0 (World Bank).

| File | Query |
|---|---|
| wdi_bop_goods_services_2022.csv | `https://api.worldbank.org/v2/country/all/indicator/<id>?date=2022&format=json&per_page=400` for BX.GSR.MRCH.CD (goods exports, BoP), BM.GSR.MRCH.CD (goods imports), BX.GSR.NFSV.CD (service exports), BM.GSR.NFSV.CD (service imports); one row per ISO3 code (aggregates included), current USD |

Fetched 2026-10-27 (API lastupdated 2026-10-08).
