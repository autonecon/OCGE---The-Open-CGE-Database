# Trade prep: what was fetched

Nothing in this folder is a raw download. The files below were fetched into
`$TRADE_PREP_CACHE` (`/tmp/trade-prep` on the run) and checked there. The
cleaner reads them and writes tables under `build_cache/trade-baci-batis/`.

Year is 2022. Where a source is a share, the share is applied to BACI. The
national dollar total is not copied onto BACI.

## BACI

- File: `BACI_HS17_V202601.zip` (CEPII, vintage v202601).
- URL: https://www.cepii.fr/DATA_DOWNLOAD/baci/data/BACI_HS17_V202601.zip
- Manifest SHA256 `16aaa22d3b000cc87744c2c28ac97ce44394c3adf315ec259451d5bb4fcae609`, 794,583,540 bytes. The download matched.
- Year file used: `BACI_HS17_Y2022_V202601.csv`. Columns `t,i,j,k,v,q`. `v` is thousand USD, FOB, and includes re-exports (Gaulier and Zignago 2010). `k` is HS 2017, 6 digits.
- HS17 is the file the S01 concordance was built for. HS22 was not used.
- Country `490` / ISO3 `S19` is Taiwan, via `source_aliases.csv` (F6).

## BaTIS

- Dataset `OECD.SDD.TPS,DSD_BATIS@DF_BATIS,1.0`, balanced exports, EBOPS 2010, USD million, 2022.
- Detail: `https://sdmx.oecd.org/public/rest/data/OECD.SDD.TPS,DSD_BATIS@DF_BATIS,1.0/..X.S..A.USD_EXC.B?startPeriod=2022&endPeriod=2022&dimensionAtObservation=AllDimensions&format=csvfile`
- Services total (`SERVICE=S`): the same path with `..X.S.S.A.USD_EXC.B`.
- `tot2022.csv` matches the manifest byte-for-byte and by SHA256 (`9e1739b6…`).
- `ebops2022.csv` matches the manifest byte size (111,824,019). The SHA256 of this extract is `7a53ea1d704207cca802a97a2a9ae353ba28b1a96dd59068db0002a70daeed77`, not the manifest value. The SDMX header is not part of this CSV. Row order from the API is not stable. The services-total rows match `tot2022.csv` with a zero gap, and each EBOPS parent equals the sum of its children. The SHA difference is recorded and is not treated as a failed total.

## Hong Kong C&SD Trade-IDDS

- API: `https://tradeidds.censtatd.gov.hk/api/bb6578c6535a4269b76c5e7034a3b337/get`
- Token from the data.gov.hk dataset `hk-censtatd-trade-idds-trade`. The call needs a cookie jar.
- 2022 annual value, HK$ '000. Trade types: 4 total exports, 3 re-exports, 2 domestic exports, by consignment country and HKHS 2-digit chapter. Chapters 01–97 except 77. Chapter 99 is not defined for 2022.
- The API rejects origin crossed with HKHS or SITC for re-exports. Origin is origin × consignment, all commodities.
- Published totals (HK$ '000): imports 4,927,467,208; domestic exports 62,645,310; re-exports 4,469,004,325; total exports 4,531,649,635. Domestic exports + re-exports = total exports.
- NESOI codes XA–XH and the combined code FM (Micronesia and Palau) are not assigned to a region.
- The sum of consignment × HKHS2 cells is about 5% above the published cumulative total. The API footnote says adjustments for earlier months are put into the cumulative total only, so the parts need not equal that total. Cells are not rescaled. The share used is re-exports / total exports inside each cell, and that cell is kept only when total exports = domestic exports + re-exports.

## Singapore

- SingStat table builder, Enterprise Singapore.
- M451521 merchandise exports by market, M451501 domestic exports by market. Monthly, million SGD, summed over the twelve months of 2022. Re-exports by market are the difference. There is no origin dimension.
- M451001 commodity sections (total, domestic, re-exports) are a diagnostic only. They are not crossed with partners and they are not used to adjust BACI.

## Netherlands

- CBS OData `85429NED`, cross-border goods trade, period `2022JJ00`. Million EUR.
- Columns used: total exports, re-exports (`wederuitvoer`), Dutch product, outgoing quasi-transit (`doorvoer`).
- SITC is the 1-digit section. The HS6 link is the UNSD correlation workbook `HS2017toSITC4ConversionAndCorrelationTables.xlsx` (sheet `Correlation HS17-SITC4`), from https://unstats.un.org/unsd/trade/conversions/HS2017toSITC4ConversionAndCorrelationTables.xlsx
- An HS6 is adjusted only when every correlated SITC code falls in one section. The conversion sheet is UNSD's one-to-one judgment and is not used.

## Not used

- Comtrade's classic `comtrade.un.org/api/get` returned an HTML shell, not data. It is not an input.
- No re-export file for Belgium, the UAE or Panama was verified, so those hubs are not adjusted.
- No exchange rate is applied. Shares have no unit.
