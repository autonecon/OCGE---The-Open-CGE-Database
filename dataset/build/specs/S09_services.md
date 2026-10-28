# S09 services trade

Services trade for the 2022 GTAP-method build. The pair source is the config row `services_pair_source`. This run is `batis_all_pairs` (David, 2026-10-21 10:21 UTC+7): BaTIS for every country pair, as GTAP 12 ch.10B §B.1 p.1. ICIO pair values are written to a compare file only. Rows and steps marked mode A only stay in the config and are not applied.

Every other choice is read from `dataset/build/config/s09/services_choices.csv`. The stage does not choose a value and does not rescale BaTIS.

## What GTAP says

GTAP 12 ch.10B p.1: since the previous release, services trade is Balanced Trade in Services (BaTiS), "bilateralized trade flows that do not need to be reconciled." Table 10.1 maps the BaTIS codes onto GTAP sectors. ch.10B p.2 §B.3: electricity, gas distribution, water and dwellings are not in BaTiS; water and dwellings "are assumed not to be traded"; SA is dropped because the manufacturing sector is not identified; SH is dropped as a factor payment. Aguiar et al. 2025 p.14 says the same for water and dwellings.

ch.10B p.3 and Table 10.2 split the remaining codes with TiSMoS, "the sum of all modes, except Mode 3." The sentence on p.3 that assigns 20 percent of other transport is truncated in the GTAP text. The build follows Table 10.2: SC13, SC23 and SC33 go to warehousing. Business travel (SDA, `trvl*`) is allocated by private consumption. Personal travel goes to the Table 10.2 sectors. ch.10B p.3 notes that this allocation is why the database can show trade in water or electricity between distant countries.

ch.02 p.17: VXSB is non-margin exports at basic prices. ch.17A p.2: FIT holds the export and import vectors at border prices. ch.17B §B.2 p.3: assembly merges that result with the bilateral trade.

Not in the GTAP text, and taken from the config: the exporter's TiSMoS export shares; F8 then world when TiSMoS is missing; removing the freight part of transport-services trade (E46) without netting it against VST by mode; recording the importer side for S13; the composite diagonal; zero services margins.

## Steps (mode B)

1. **Bilateral BaTIS, 2022, exports, adjustment B, USD million.** Additive leaves SA, SB, SC1–SC4, SDA, SDB, SE, SF, SG, SH, SI1–SI3, SJ1–SJ3, SK1, SK2, SL. Economies map through `country_region_map.csv` and the S01 aliases. Composites sum their members. A flow whose two ends fall in the same region is the composite diagonal. Partner `W` and the other BaTIS aggregates in `non_country_codes.csv` (including `WXD`) are not pairs. No rescaling.

2. **TiSMoS split** of SC1, SC2, SC3, SDB, SJ3 and SK2. Shares are the exporter's 2022 export leaves, Modes 1+2+4, partner World. Memo items and aggregates are ignored. A composite uses the sum of its members. If the parent is 0 in TiSMoS, or the exporter has no TiSMoS row, the share is the GTAP geographic region's summed TiSMoS (`TISMOS-F8`). If that is also 0, the World reporter (`WL`) is used (`TISMOS-WORLD`). The leaf-to-sector map is S01 `concord_ebops_to_sector.csv` (Table 10.2 on the ICIO sectors). SJ32 goes to `adm` and is flagged. Direct leaves are not split.

3. **Travel.** SDB1/SDB2/SDB3 go to hea/edu/hos by the TiSMoS split. SDA is allocated across every `dom_*` row of `io_s08` in proportion to that host's `p` column (household consumption of domestic products), goods and electricity included. Goods, `B06` (the unsplit oil and gas row in `io_s08`), electricity, and the untraded sectors `wat` and `rle`, plus `hhe`, are written to `travel_s09.csv.gz` with source `travel_sda`. The other commodities are services VXSB with the same source. `wat` and `rle` stay out of services VXSB because the config marks them untraded and H2 forbids that services trade. Goods `wat` is booked in S07. The travel file holds the SDA amount so the BaTIS total is kept. `ely` is not built as non-travel services trade (S11).

4. **Freight double count (E46).** For each exporter, f[sea] = SC12/SC1, f[air] = SC22/SC2, f[rdt] = SC32/SC3, Modes 1+2+4, with the same F8 then world fallback as the split. Mode B drops those three leaves on every pair. The removed amounts are `freight_removed_s09.csv`. They are not subtracted from VST by mode (S08 C3/W1: rdt is overstated for oil and gas). The comparison with VST and VTWR is report-only. The importer side is recorded for S13. `io_s09` is not edited.

5. **Mode A is not applied.** `travel_icio_pairs` and `row_split` remain in the config. ICIO does not govern any pair.

6. **Compare and hand on.** `icio_services_compare_s09.csv.gz` places the ICIO services pairs, the ICIO ROW totals, and the `dpabr` block (TLS on `dpabr` reported, not traded) next to the built trade. `io_s09.csv.gz` is a byte copy of `io_s08.csv.gz`. S07 VXSB and the S08 margin files are not rewritten. Services margins are zero: no VTWR file is written.

## Outputs

Under `dataset/stages/S09_services/output/`:

- `vxsb_services_s09.csv.gz` — sector, exporter, importer, source (`batis` or `travel_sda`), vxsb_musd. One row per key.
- `travel_s09.csv.gz` — commodity, host, visitor, musd, source.
- `freight_removed_s09.csv` — margin, exporter, importer, musd, f_share, f_source.
- `tismos_shares_s09.csv` — exporter, batis_code, leaf, sector, share, source.
- `icio_services_compare_s09.csv.gz` — sector, exporter, importer, kind, icio_musd, built_musd.
- `usa_services_s09.csv` — the §7 US detail.
- `io_s09.csv.gz` — byte copy of `io_s08.csv.gz`.

The stage kit writes STAMP (only if every hard check passes), SHA256SUMS, checks, flags, the adjustments ledger (every F8, world and freight-removal value), inputs.lock, NEEDS_DAVID.md, REVIEW_BRIEF.md and build.log.

## Hard checks

G0 and G0c from the stage kit, plus a binding check that this S08 snapshot is commit `4743780` (STAMP 2026-10-21 16:26:54 UTC+7, output SHA256SUMS `2f25457f3aa3695c7f52347e549d1fe5bb408cf7358bcb1cc0f863514587dd19`) and that S07R is snapshot `c8a2e29` with VXSB `7708ca32…`. IN1 and IN2 from the kit. H1 the 23 config rows. H2 no SA/SH in services trade, and no BaTIS services trade in ely (except the travel file), wat, rle or hhe. Goods wat is in S07. H3 TiSMoS shares. H4 BaTIS pair identity after the drop and the freight removal. H5 freight removal. H6 travel. H7 mode A, inactive in this run. H8 signs, regions, zero services margins. H9 the byte copy and the untouched upstream files. H10 no EXIOBASE tag. H11 no raw or licensed file in the git diff. H12: `vxsb_services_s09.csv.gz`, `travel_s09.csv.gz` and `icio_services_compare_s09.csv.gz` match snapshot `a36c746`. A non-identical file passes only when every cell is within 1e-9 USD million. `trade_identity` (Timmy, 2026-10-21) records that tolerance as float rounding from BaTIS row order. Those three files are not fed by S07 goods VXSB or S08 freight. Only the freight-versus-VST report is expected to move with S08. The refetched BaTIS EBOPS file and the refetched WDI services file are the MANIFEST rows.

H13 (`batis_scaling`) is an identity, not a source comparison (fix round B9, 2026-10-24; Grok review F1): the factor is defined as WDI BX/BM.GSR.NFSV.CD over BaTIS S, so BaTIS × factor = WDI holds by construction. It stays hard because it guards the arithmetic and the (0, 1] range. Its concept tag starts with `identity;` so S16-Hcollected can list it as an identity. No independent 2022 services total for Bermuda is on disk; a Bermuda BoP release would be the source to point it at.

Report checks R1–R8 are in the handoff. R6 is the two-run SHA256SUMS comparison (`GTAP_STAGES_DIR`).
