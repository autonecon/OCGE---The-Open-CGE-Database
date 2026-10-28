# 2022 physical energy volumes (prep for S11)

Run from `dataset/build`:

```
python3 prep_energy_volumes.py
```

The script reads `dataset/data/` files and checks each SHA-256 against `MANIFEST.csv`. It does not download. Raw files are gitignored; fetch the URL in the manifest and keep the hash.

This is the volume prep for stage (g). It does not price volumes and it does not book subsidies.

## What is measured

Year is 2022. Regions and sectors are the S01 lists (167 regions, oil and gas split). Oil is HS 270900 and 271410. Gas is HS 271111 and 271121 only. LPG and NGL (HS 271112–271119) belong to petroleum products (PLAN_ERRATA E29).

| Commodity | Chosen volume | Unit | Why this series |
|---|---|---|---|
| Natural gas | EIA `INTL.26-1/2/3/4-{ISO}-BCM.A` | billion cubic metres, as EIA publishes them | Dry natural gas. Activity 1 production, 2 consumption, 3 imports, 4 exports. Product 26 excludes NGPL shrinkage. See `dataset/data/eia_intl/FETCH_NOTES.md` for the activity-id bug. |
| Crude oil | EIA `INTL.57-1-{ISO}-TBPD.A` for production. Imports and exports are JODI `CRUDEOIL` | thousand barrels per day | Crude including lease condensate. Product 58 (natural gas plant liquids) is not added. This bulk file has no 2022 value on activities 3 and 4 (the USA import series ends in 2020). |
| Crude use | JODI primary `CRUDEOIL` refinery intake (`REFINOBS`) plus direct use (`DIRECUSE`) | thousand barrels per day | EIA publishes no crude-consumption activity. This is refinery intake plus direct use of crude, not final consumption of a product. NGL is not included. |
| Coal | EIA `INTL.7-1/2/3/4-{ISO}-MT.A` divided by 1000 | million metric tonnes | The bulk file labels MT as 1000 metric tons. Dividing by 1000 changes the prefix only. |
| Refined products | JODI secondary `TOTPRODS`: `REFGROUT`, `TOTIMPSB`, `TOTEXPSB`, `TOTDEMO` | thousand barrels per day | EIA `INTL.54-1` has no 2022 values (PLAN E5). `TOTPRODS` already includes LPG. LPG is not added again. |
| Electricity | EIA `INTL.2-12` net generation, `2-3` imports, `2-4` exports, `2-2` net consumption | terawatt-hours (EIA billion kilowatthours) | Net, not gross. EI generation is gross. |

Natural gas plant liquids (EIA product 58, JODI `NGL`, UNSD commodity 4200, EI "NGLs production") are written to the NGL check and are not added to oil or gas.

## Fills

A country with no EIA gas or crude series can be filled from JODI if all 12 months of 2022 are present. Annual thousand barrels per day = sum of monthly thousand barrels / 365 (2022 is not a leap year). Annual billion cubic metres = sum of monthly million cubic metres / 1000. Each fill is a ledger row.

UNSD natural gas in this extract is terajoules, not cubic metres. It is not converted into the chosen gas volume. A cross-check divides by 40,000 because the EI workbook standardises gas volumes at a gross calorific value of 40 MJ/m3 (40,000 TJ per billion cubic metres). The same workbook's conversion sheet also shows 36 PJ per billion cubic metres; that factor is not used.

UNSD conventional crude oil (commodity 4100) fills crude imports and exports (transactions 03 and 04, thousand metric tons at the EI 0.1364 tonnes per barrel) where neither EIA nor a full JODI year exists. UNSD SIEC 46 oil products (leaf codes 4610 to 4699; feedstocks 4300, additives 4400 and other hydrocarbons 4500 are not products) fill refined production, imports and exports where JODI has no full year, at the EI product-basket factor of 8.0577 barrels per tonne. These are the S11 trade-volume fills (`trade_volume_fill`, GTAP 12 ch.12 p.5: UN data gap-fill countries the main source misses). Each fill carries `fill=yes` and source `unsd`.

UNSD electricity net production (commodity 7000, transaction 019, gigawatt-hours / 1000) fills electricity generation only where EIA is missing. UNSD coal (hard coal 0100 plus brown coal 0200, thousand metric tons / 1000) fills coal production, imports and exports only where EIA is missing. Children of 0100 and 0200 are not added on top of the parents.

## What is not the same thing

These are cross-checks. They do not replace the chosen series.

- EI gas volumes are standardised at 15°C and 1013 mbar from energy, at 40 MJ/m3, and exclude flared and recycled gas. EIA dry gas is EIA's own cubic-metre series (US standard conditions) after NGPL extraction.
- EI "Oil Production" includes NGLs. The comparison used for crude is the workbook sheet "Crude+cond production", which excludes NGLs. The NGL sheet excludes condensates.
- EI refinery throughput is atmospheric distillation input. JODI `REFGROUT` is refinery gross output.
- EI electricity is gross output. EIA and the chosen series are net generation.
- EI coal production is commercial solid fuels, million tonnes.
- JODI gas is at national conditions and the country's own gross or marketed definition.
- UNSD crude is metric tons. A barrel comparison uses the EI factor 0.1364 tonnes per barrel ("based on worldwide average gravity") and is not a chosen volume.
- IEA World Energy Statistics and Balances are not public. JODI is a joint dataset of APEC, Eurostat, the IEA, OLADE, OPEC and UNSD. UNSD energy statistics are the public joint IEA/Eurostat/UNECE questionnaire. Neither file is the IEA balance database.

## Report set

A discrepancy above 5% is listed when the region is in the S01 priority set `top50`, `gulf`, `opec_2022` or `opec_plus_partner`, or is one of the 50 largest regions by the chosen production of that commodity. The ratio is computed on the countries that both sources cover.

The gas gate follows PLAN E6: each of the top 15 gas producers must be within 8% of EI production, except Kuwait, Nigeria, Venezuela and Libya, which are reported rather than failed. A gap David accepted is listed in `accepted_gate_exceptions.csv` (Turkmenistan, 2026-10-20 21:24 UTC+7) and is reported, not failed. A missing file or a row without `decided_by` and `decided_at` stops the run.

Coal consumption in the cross-check is EIA product 7 activity 2 in terajoules, divided by 1e6, against the EI coal-consumption sheet in exajoules. The chosen coal volume stays in million tonnes. Those two units are not divided into each other.

EIA codes `WP11`–`WP27` and `OECD` are IEO or membership aggregates, including some whose names repeat a country (Canada, China, the United States). They are not added to the country series. `VIR`, `ESH`, `ATA` and `UMI` are in the bulk file and are blank or unmapped in the S01 country map, so they stay out of the 167-region totals.
