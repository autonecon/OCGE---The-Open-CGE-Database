# Release notes

## v0.5.5-beta (28 October 2026): OCGE Data Base beta v5.5, work in progress

Base year 2022, 167 regions, 51 sectors. First public release. Beta v5.5 is beta v5 plus one fix to the power sector in countries with electricity subsidies.

The data in the release files are the beta v5.5 build unchanged. Only the label in the DREL header (and the same label in the JLS copy) was renamed to `ocge_gtapv7`.

### Final checks (S16)
- 28 hard checks and 16 guards, 0 failures.
- 48 of 49 aggregation maps pass calibration, the unshocked test and the homogeneity test; 15 maps also run a tariff shock. The exception is `aggregation_B` (see caveat 9).
- GHA, KAZ and KEN calibrate when modelled alone.

### Changes from beta v5 (v5.5)
- In the 36 countries with an IEA electricity subsidy and no measured power price, power output is valued at tariff level as in beta v4, less the intra-industry resale that the beta v5 resale fix removes everywhere. The booked electricity subsidy rate is capped at half the basic price, so the subsidy fits inside that output instead of being counted twice.
- Power output (bn USD): RUS 264.7 to 133.2, IRN 48.8 to 18.1, UKR 30.0 to 8.5, EGY 33.7 to 15.4, KAZ 23.2 to 6.6, VEN 16.4 to 5.0, BHR 6.0 to 2.1, GHA 5.1 to 1.8. World 4,397.2 to 4,097.7 bn. Every other region is unchanged, and GDP is unchanged in every region.
- Power value added falls in 22 regions (RUS 78.6 to 29.7 bn, IRN 23.9 to 3.9, UKR 23.3 to 3.9, UZB 5.3 to 0.3). This is what power looks like at subsidised tariffs, but treat power-sector results in these regions as indicative.
- Electricity subsidy booked: 300.3 to 256.2 bn. The cap drops 41.4 bn of IEA subsidy (largest UKR 9.2, EGY 8.9, KAZ 6.6, VEN 4.4, BGD 2.8).
- 56 regions fail calibration when modelled alone (beta v5: 54). New are UZB and NGA: pool them with neighbours.

### Changes from beta v4 to beta v5
- **Macro (S02):** YEM GDP 24.7 bn (IMF WEO), Cuba 26.4 bn (ONEI at 24 CUP/USD), SSD 7.5 bn, SDN GFCF 4.5 bn.
- **South Africa households (S03):** spending split by COICOP.
- **Trade (S07):** gold re-exports dropped or rerouted, Hong Kong domestic-export cap, transit caps, and a China importer floor with a strict partner cap (CHN imports +50.3 bn to 2,210.4 bn). World goods trade 22,295.7 bn.
- **Services (S09):** Bermuda reinsurance routing; USA financial exports 154.2 bn.
- **Taxes (S10):** energy taxes now in 2022 terms (671.9 bn).
- **Energy (S11):** contract gas routes; IRN crude and refined reference prices.
- **Power (S13):** measured prices in 49 regions plus the resale fix.
- **GDP (S14):** world GDP 102,759.4 bn.

### Known caveats
1. **China imports (largest caveat).** China's goods imports are about 340 bn below China's own customs. China records imports by origin, while partners (TWN, KOR, JPN, MYS, VNM, THA) record exports by destination of shipment, so goods routed through third countries cannot simply be topped up without double counting. The partner cap keeps every partner within its own customs total. China's trade surplus is about 535 bn above the WDI balance of payments. Planned fix: move the flow from the partner's exports to the transit country using transit and re-export data.
2. **US insurance imports** are 41.9 bn against BEA's 64.1 bn (exports match: 24.7 against 24.9), because of the Bermuda reinsurance routing.
3. **Natural gas liquids** keep the beta v4 treatment; the full GTAP 12 ch.12 treatment is planned.
4. **Power in GNQ, AFG, AGO and ETH** has no measured price and uses the resale fix only.
5. **Cuba (XCB)** borrows its sector structure from Brazil. All donor regions borrow sector structure: trade and macro results are usable, sector results are indicative.
6. **Switzerland non-ferrous metals:** exports are only just covered by output plus imports (1.05 times) after the gold adjustment.
7. **Hong Kong** domestic-export cap is partial (exports 41.1 to 35.0 bn).
8. **Algeria gas** price is the 2010 regulated price held flat.
9. **Map exception:** `aggregation_B` stops at the iteration limit (10 of its 12 regions dissave at once). `alone_afg` has sigma_qinv of 1.0004, just above 1 (negative saving).
10. **Capital shocks on a region modelled alone:** depreciation exceeds investment in XNF, CAF, STP, SYR, TLS, GNQ and LBY. Pool them with neighbours.
11. **58 regions have no crude oil production.** Merge crude with another sector when modelling one of them alone.
12. **Zero-weight aggregation:** fill such cells with the unweighted member mean, as the S16 suite does (`dataset/build/s15_har/julia/prepare_for_solve.jl`).
13. **Single-region calibration:** UZB and NGA fail when modelled alone; pool them with neighbours.
