# Merchandise and services trade prep

This is the prep for PLAN.md stages (c) and (e). It stops at a cleaned BACI
HS6 table and a BaTIS region × sector check. It does not read ICIO, and it
does not apply the stage (b2) cap of hub exports at domestic output.

The 167 regions and the services concordance are the S01 outputs. The HS6
concordance is not re-derived here; the cleaned table stays at HS6.

## What was measured

BACI HS17 v202601, year 2022, is FOB, thousand USD, mirror-reconciled, and
still contains re-exports. Hong Kong publishes re-exports in thousand HKD,
Singapore in million SGD, the Netherlands in million EUR. Those totals are a
different concept from BACI (customs valuation, classification, and, for the
Netherlands, quasi-transit). They are used only as shares. No exchange rate
is applied, and no national total is copied onto a BACI flow.

A missing partner share is left as the BACI flow. It is not filled with 0 or 1.

## Re-export removal

Hubs are applied in this order: Hong Kong, then the Netherlands, then
Singapore. The finer published breakdown goes first, so a later hub's import
shares are computed on what remains. That order is a rule, not a tuned weight.

For a funded amount on one HS6:

- the hub's export to the destination falls by that amount;
- the origin's export to the hub falls by the same amount (it was not retained);
- the origin's export to the destination rises by that amount when the two
  regions differ;
- when they are the same region, the amount is intra-region rather than bilateral.

The amount is capped at the origin's export to the hub in that same HS6. What
cannot be funded stays on the hub and is flagged. Quantity is cleared on every
cell this changes, because the re-export sources publish values only.

Hong Kong. Share = re-exports / total exports by consignment and HKHS 2-digit
chapter, from C&SD Trade-IDDS. The API will not cross origin with HKHS for
re-exports, so the origin mix is origin × consignment for all commodities and
is applied uniformly across the chapters of that consignment (`FILL-HS2-UNIFORM`,
`FILL-ORIGIN-ALL-COMMODITIES`). NESOI codes and the combined Micronesia+Palau
code are not moved onto real countries. The Hong Kong margin stays inside the
goods value (`MARGIN-IN-GOODS`): there is no margin published at this grain,
and a single annual rate is not applied.

Netherlands. Share = re-exports / (re-exports + Dutch product) by partner and
SITC section, from CBS 85429NED, 2022. Outgoing quasi-transit is not removed
and is not in the denominator. An HS6 is touched only when the UNSD HS2017–SITC
Rev.4 correlation puts it in a single section. Origin is that HS6's share of
BACI imports into the Netherlands (`FILL-ORIGIN-IMPORT-SHARE`), which is not
a published origin.

Singapore. Share = (total exports − domestic exports) / total exports by
partner, from SingStat M451521 and M451501, all goods, applied uniformly across
HS6 (`FILL-PARTNER-UNIFORM-HS6`). Origin is the same BACI import share.
M451001 commodity sections are stored as a diagnostic and are not crossed
with the partner margins.

Belgium, the UAE and Panama are not adjusted. No official bilateral re-export
file was verified. Their BACI flows stay as published.

## Services

BaTIS balanced exports, EBOPS 2010, 2022, USD million. Additive codes are the
children (SA, SB, SC1–SC4, SDA, SDB, SE, SF, SG, SH, SI1–SI3, SJ1–SJ3, SK1,
SK2, SL). Parents are not added on top of children. Partner `W` is the world
total. Named partners plus the other aggregate partners (WXD, EU, OECD and the
rest) equal that total, so `W` is not entered again as a flow.

SA and SH are the GTAP drops. They stay in the identity and out of the sector
matrix. SDA (business travel) is held for the household-consumption allocation
in stage (e). Codes whose sector split is TiSMoS are held unsplit: no weight
is invented here. Leaf codes are one sector each.

## Files

| Path | What it is |
|---|---|
| `batis_checks.md` | BaTIS hard checks and the bucket totals |
| `baci_checks.md` | BACI hard checks |
| `adjustment_summary.csv` | Funded removal by hub, thousand USD |
| `FETCH_NOTES.md` | URLs, units, and the SHA record |
| `NEEDS_DAVID.md` | Choices this prep did not make |

The bilateral HS6 table, the flow ledger and the BaTIS region × sector table
are under `build_cache/trade-baci-batis/`, with `SHA256SUMS`.
The same hashes are copied to `ARTIFACT_SHA256.txt` in this folder.

The artifact folder would not store the bilateral table as one file (about
246 MB). It is eight hash parts, `baci_hs6_bilateral_00.parquet` through
`_07.parquet`. The ledger is sixteen parts, `adjustment_ledger_00.parquet`
through `_15.parquet`. Read them together:

```
read_parquet('.../baci/baci_hs6_bilateral_*.parquet')
read_parquet('.../baci/adjustment_ledger_*.parquet')
```

The parts are a hash split of the full table, not a sample. Columns of the
bilateral table: `exporter_region`, `importer_region`, `hs6`, `value_kusd`
(thousand USD, FOB), `qty_tons` (null when the cell was adjusted), `adjusted`.

## Results

BACI 2022 is 24,184,090,264.298 thousand USD. None of it failed the region map.
The funded double-count removed is 499,030,868.074 thousand USD. Cleaned bilateral
plus intra-region plus that double-count equals the original total (the identity
gap in `baci_checks.md` is under 1 thousand USD). Hard checks passed.

| Hub | BACI exports before | Final exports | Funded removal |
|---|---:|---:|---:|
| HKG | 117,721,302.663 | 41,569,742.696 | 76,110,921.821 |
| NLD | 635,899,791.449 | 377,726,955.575 | 258,159,254.524 |
| SGP | 355,993,175.099 | 191,185,684.876 | 164,760,691.731 |

Thousand USD. "Final exports" is after all three hubs, so a hub that is later
an origin for another hub is a little lower than it was immediately after its
own step. Belgium, the UAE and Panama were not in this step.

BaTIS economy-reporter leaf rows sum to 14,162,073.123 USD million. Every row
is in one class. Partner W, 7,081,036.563, equals named partners plus the other
aggregate partners (gap 0.004). Assigned sectors are con, fin, gov, its, pro,
pst, pub, tel, trd, and all 167 regions have at least one such export.
Unsplit codes are 3,244,637.850; business travel held for S09 is 163,295.827;
SA and SH are 724,142.204. See `batis_checks.md`.
