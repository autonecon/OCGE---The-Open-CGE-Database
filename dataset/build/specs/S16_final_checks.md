# S16 final checks (PLAN §3(k) and §4)

Built 2026-10-24. The stage entry is `dataset/build/s16_final_checks.py`. The method is the package `dataset/build/s16_final/`:
- `checks.py`: the §3(k) checks S15 does not already run, as pure functions (mutation tests in `tests/test_s16_checks.py`);
- `maps.py`: the map suite, resolved on the finished data base, with the one-sided-pair and S–I pre-checks;
- `gtap_compare.py`: the S10/S11 route border values, and the internal comparison with GTAP 10;
- `config.py`: strict config (`config/s16/s16_choices.csv`, `maps.csv`, `sector_schemes.csv`);
- `julia/map_suite.jl`: aggregate, prepare, calibrate and solve each map in GlobalTradeAnalysisProjectModelV7 0.1.11 (the pinned S15 project).

The gate is READINESS §1 S16: the full §3(k) table, and the build stops on any hard FAIL. S16 changes no number of the data base; its ledger is header-only.

## What is checked, and on what

The finished data base is the three S15 HAR files. S16 reads them back with harpy (Float32), so every check is on the file a user receives. The upstreams are S01, S02, S10, S11, S13, S14 and S15 (G0 and `S16-Hchain`).

| §3(k) row | S16 check | Class |
|---|---|---|
| (all stages) | `Hrollup`: S01–S15 each stamped, SHA256SUMS bound to the STAMP, no hard FAIL, every upstream SHA256SUMS a STAMP names equal to that upstream's current one | hard |
| Identities | `Hidentities` (zero profit, market clearing, imports, VCIF = VFOB + VTWR, ΣVST = ΣVTWR), `Hsave` (SAVE = Y − C − G, ΣSAVE = Σ(I − VDEP)), `Hsixm` (S − I = X − M per region) | hard, 1e-6 |
| Signs | `Hsign` (no negative cell but SAVE), `Hvmsb` (VMSB ≥ VCIF), `Hva` (EVFP > 0 with output), `Hvdepk` (VDEP < capital income), `Hsubsidy` (every subsidy cell traces to a source: TLS or PTAX of its I-O column, booked PSE input or output support, PSE support on that factor or on all factors, a booked WTO export subsidy, or an S14 rounding move of at most 0.001 USD million on a cell of at most 0.001) | hard |
| Price basis, concepts | `Hconcepts`: every S16 check names its concept (C01–C30, or identity, sign, model, stage, repo) and no hard check compares two bases | hard |
| Macro | `Hgdp` (GDP = S02 target), `Rfactor` (C, G, I factor outside ±10%), `Rgfcf` (I / S02 GFCF outside 0.8–1.25, E13) | hard / report |
| Pre-solve S–I | `Hsi` (VKB, I, Y > 0), `Hnegsave` (SAVE ≤ 0 regions = NEG-SAVE flags), `Hcarry` (saving share outside ±1 = CARRY-SAVE flags) | hard |
| VDEP < I | `Rvdep` against CARRY-VDEP | report |
| Trade | `Htrade` (exports, imports and VST equal what S13 held), `Hcollected` (S07, S09 rows against BACI, BaTIS and WDI) | hard |
| Tariffs | `Htariff` (no rate scaling and no added value: the route values S14 merged are rebuilt from S10 goods, S11 energy, S09 services and the travel S13 held (`s13_fit.method.assemble_trade`, `s14_assembly.method.bilateral`); VFOB equals the rebuilt VFOB and VMSB/VCIF the rebuilt power on every route), `Rcustoms` (E3), `Hcollected` (S10-Hwedge: written tm, VMSB and duty against S07 + S08 VCIF and the BACI accumulator) | hard / report |
| Energy | `Henergy` (output = S11 target values), `Rei` (top-15 producers against EI 2022, ±8%), `Reiexports` (not available: EI 2025 has 2024 bilateral only) | hard / report |
| Region list | `Hregions`: 167 regions, the S01 list | hard |
| Ledger | `Hledger`: every row of every stage ledger has a rule and a citation, every rule is on `config/s16/ledger_rules.csv` (kind method or absorbed), no plug, slack or unmatched residual; `Rabsorbed`: gaps the FIT absorbs under a named GTAP step (io_s12 imbalances, stock-change and G-revision gaps), rows and USD million; `Hrounding`: every S14 re-balance move at most 0.001 USD million, so S14 has no ledger row | hard / report |
| QA vs GTAP | `Rgtap`, `Rtaxcol` (below) | report |
| Solve | `Hmapdef`, `Hmapgate`, `Hmaps`, `Rmapscheme`, `Rpsave` (below) | hard / report |

Rows that need the source data the producing stage read (BACI, BaTIS, the duty wedge, volume × price) are collected from that stage's checks (`Hcollected`): each must be present and none hard-FAIL. S11-Hvpv, S11-Hcif and S09-H13 are identities inside their stage: they confirm the stage arithmetic, not the source (Grok review F1). S10-Hwedge is not an identity since fix-round item B9: it reads the written tm, VMSB and duty files back and compares them with VCIF re-read from the S07 vfob and S08 vtwr files by a separate reader and with the BACI line accumulator on every bilateral cell, and checks that every VCIF cell is written; only its duty = VCIF × tm and VMSB ≥ VCIF part is an identity.

## QA against GTAP 10 (internal)

David's card (2026-10-24): GTAP 10 (2014), results outside git; any comparison uses GTAP 10. David then asked for a thorough comparison. With `S16_GTAP10_DIR` set, the stage compares, for each single-economy region in both (`gtap_compare.full_compare`), every measure below. Sectors are compared on the coarsest common grouping of `config/s01/gtap65_to_sector.csv`, factors as labour, capital, land and natural resources.

- macro ratios: C, G, I, X, M over GDP, SAVE/Y, VDEP/VKB, VKB/GDP, tax/GDP; the tax mix (product taxes on firms and on final demand, output, factor-use, income, export and import taxes, each over the sum of their absolute values);
- production: output and VA shares, I-O coefficients (input group over activity cost), VA over output, factor shares by activity and in total;
- demand: household, government and investment budget shares; import shares by agent (firms, household, government, investment);
- trade: export shares, import mix, import partners (importer view; partners outside the compared set pooled), tariff, margin and export tax rates;
- taxes: net product tax rates (all agents, household, firms), output, factor-use and income tax rates. Taxes are compared as rates: a share of a near-zero net tax total is meaningless in the Gulf.

Each row carries a weight, the item's share of what the measure is taken over in that region (a share's own value, a rate's share of its base), and is material when the weight is at least 1% in either data base. Each gap is screened against the reference year (David: differences should be explainable by the 8-year gap): it is read as the reference year when it is at most 2 points, or when the median gap of the same measure and item over the other regions has the same sign and a similar size (within 2 points or half the gap). An item whose median gap over all regions is over 5 points is systematic: a build-wide difference is never read as the year, and is listed in the summary (`systematic_items`) for review (QA S16 #5). The screen is indicative; a 2022 price shock that hits a few exporters (gas) is not caught by a median.

`Rgtap` counts the flagged rows: not explained, material, in the 20 largest economies by S02 GDP (David: accuracy in large economies first), and over 5 points. The full table goes to `S16_PRIVATE_DIR` (`gtap10_compare_s16.csv.gz`); git gets `gtap10_compare_summary_s16.csv`, counts and item names only.

`Rtaxcol` counts the material product tax rates of the 20 largest economies more than 10 points below GTAP 10 and not explained by the year. On the first run these are fuel, power and gas in Europe, Japan, India and Russia. The cause is IMPROVEMENTS_LOG S13-2: each I-O column carries one net product-tax rate, so excise is spread over every product the column buys. The flag NEEDS-FIX goes to David. The other flagged rows are reviewed in the S16 fix list.

## Map suite (PLAN §4)

`config/s16/maps.csv` (40 maps): the S15 smoke map with its tariff shock; the closure maps of `earlier-build/build/closure_test_2022.jl` on main (default, small countries, A, B, C, the eight `usa_plus_*`, the energy-trade maps); each Gulf country, Iran, Iraq and Korea alone; each OPEC 2022 or OPEC+ exporter alone; and the twenty largest economies by S02 GDP (David: accuracy in large economies first). Factors are not aggregated.

- **Aggregation B and C** take their regions from the data as on main, but never pick a CARRY-SAVE region (E50: they stay pooled).
- **One-sided pairs.** Before the fix round, 332 commodity-region pairs bought only imports (coa 100, oil 76, gas 73, pet 60, hhe 20, msp 2, ore 1); the S15 swap has no donor there, and the levels model takes log(0). S14 now seeds them (fix list A13), so the fuel-pooling scheme `s7_fuels` (KOR and GAB) is gone from `sector_schemes.csv` and `maps.csv` (choice `one_sided_pairs` = `upstream_fix_first`). Each map still lists its sector schemes in order, and the first on which every named region buys every group domestically wherever it buys it is used; a map with none is refused (`Hmapdef`). The subsidy check traces a seeded column's negative taxes to its suppliers (`S14-A13-seed`).
- **Pre-solve S–I** (`Hmapgate`, E50): σsave and σ_qinv of every group in [−1, 1].
- **Julia** (`Hmaps`), for each map: aggregate_data; the S15 Armington swap; VST > 0; the calibration closure; the unshocked default closure (qo moves ≤ 1e-6); homogeneity, with every nominal variable × 1.1. Every variable of the package's `build_model!.jl` is classified (`NOMINAL`, `REAL`, `PARAM` in `map_suite.jl`); an unclassified variable stops the map, so a package update cannot slip one past the test (QA S16 #2). Nominal variables must move × 1.1 and real ones (quantities, rates of return, utility, elasticities) stay put within 1e-6, except psave, qsave, p and u (below). The smoke map also gets a +10% tariff shock (PLAN §4). Every solve must be solved and feasible. Memory grows with the region count (about 4 GB at 5 regions, 9.5 GB at 18), so maps with fewer than `S16_HEAVY_REGIONS` regions (default 10) run in `S16_JOBS` processes (default 3) and each larger map then runs alone in a fresh process; the stage frees the data base before the suite, a map left without a result (its process killed) is retried once alone, and the log gives each process's peak memory.
- **psave** (S15 QA N7). The package's `e_psave` (build_model!.jl line 495) is log ψ_r = log pinv_r + Σ_s w_s log pinv_s, with w_s = (netinv_s − qsave_s)/Σ netinv. It is homogeneous of degree 1 only if Σw = 0. Σw = (Σ netinv − Σ qsave)/Σ netinv is a sum of model quantities, while Walras balances values: Σ psave·qsave = pcgdswld·Σ netinv (`psave_base_value_gap` in the result lines). So Σw is zero only when psave is the same in every region, which no calibrated base has; it differs by map because the regional psave levels do (default_5 5e-7, alone_sau 5e-5). The data base itself has Σ SAVE = Σ(I − VDEP) at purchasers' prices to 1e-7. (An earlier version of this spec put the cause on basic-price investment; QA S16 #4 showed that was wrong.) The check predicts psave's move from the unshocked values and e_psave alone (a fixed point with qsave × 1.1/ρ), qsave's move (1.1/ρ), and what e_p and e_u carry of it (p = ppriv σyp + pgov σyg + psave (1 − σyp − σyg), u = y/p/pop), and requires the solve to match all four within 1e-6. `Rpsave` reports Σw on every map.

## Running

- Reader: as S15 (`S15_HARPY_PYTHON`). Julia: as S15 (`S15_JULIA`, project `s15_har/julia`).
- `cd dataset/build && S15_HARPY_PYTHON=<venv>/bin/python S16_GTAP10_DIR=<gtap10 dir> S16_PRIVATE_DIR=<outside git> python3 s16_final_checks.py`
- `S16_ONLY_MAPS=a,b` runs only those maps, for development; hard check `S16-Hfullsuite` then fails, so no STAMP.
- Tests: `python3 -m unittest tests.test_s16_checks`.

## Outputs

In `dataset/stages/S16_final_checks/output/`: `stage_rollup_s16.csv`, `collected_checks_s16.csv`, `subsidy_provenance_s16.csv`, `macro_s16.csv`, `ei_compare_s16.csv`, `ledger_summary_s16.csv`, `maps_resolved_s16.csv`, `map_gate_s16.csv`, `maps_regions_s16.csv.gz`, `maps_sectors_s16.csv`, `map_suite_s16.txt` (the Julia result lines; run times are in `build.log` only), `map_results_s16.csv`, `gtap10_compare_summary_s16.csv`.
