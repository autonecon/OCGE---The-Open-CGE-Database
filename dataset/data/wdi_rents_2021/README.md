# World Bank WDI natural-resource rents (% of GDP)

- **Folder:** `data/wdi_rents_2021/`
- **Source:** World Bank WDI API v2 (keyless JSON), indicators NY.GDP.PETR.RT.ZS (oil), NY.GDP.NGAS.RT.ZS (natural gas), NY.GDP.COAL.RT.ZS (coal), NY.GDP.MINR.RT.ZS (minerals), NY.GDP.FRST.RT.ZS (forest), all countries, 2011-2022 requested; WDI last updated 2026-10-08.
- **Fetch:** `fetch_wdi_rents_2021.sh` (keyless). Fetched 2026-10-23. Re-fetching can give other bytes if the source revises; the SHA-256 of the files used is in `data/MANIFEST.csv`.
- **Licence:** CC BY 4.0 (World Bank); cite World Bank, World Development Indicators.
- **Year:** 2021: the series end in 2021 at source (no 2022 value for any country).
- **Units:** percent of GDP
- **Use:** S12 step 3: rent = share x S02 GDP, booked as natural resources in coa, oil, gas, ore, min and for.

## Files

| File | Bytes | SHA-256 |
|---|---|---|
| `wdi_rents_2021/NY.GDP.COAL.RT.ZS.json` | 675,630 | `5d3a2ad434f7bf26685323eff5b7813bd8137dff1c910b094d3b889bb806d4b0` |
| `wdi_rents_2021/NY.GDP.FRST.RT.ZS.json` | 701,678 | `13d10537084c138de47e8337b36598cdc2a4633d65fd908ea7644b83924bf107` |
| `wdi_rents_2021/NY.GDP.MINR.RT.ZS.json` | 691,951 | `cc8939b07e98b3f744b221b4efeb734676299ee96da9d709e13a2d8b152ae7dc` |
| `wdi_rents_2021/NY.GDP.NGAS.RT.ZS.json` | 702,435 | `9c123514431f3eebbf4d183cc19d43f1050727456d446727a13d0ac4dc4fd461` |
| `wdi_rents_2021/NY.GDP.PETR.RT.ZS.json` | 681,077 | `34db1a22280e1cedda9a42b1c2cf16c74094d1df72f553edb9a33a571105d09d` |
| `wdi_rents_2021/fetch_wdi_rents_2021.sh` | 363 | `b12d148a61f1a1361a45c7453ec87b38a167356c5809cb151fcee8307930e5df` |
