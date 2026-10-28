# S15 HAR and JLS (GTAPv7-Julia header set)

Built 2026-10-24. The stage entry is `dataset/build/s15_har_jls.py`. The method is the package `dataset/build/s15_har/`:
- `har.py`: the GEMPACK HAR writer (standard GTAP record layout, a port of `earlier-build/build/write_har_2022.jl` on main);
- `method.py`: the 31 data headers, the parameter arrays, the three HAR files, the JLS bundle, the regional accounts and the map gate;
- `params.py`: the elasticities (GTAP 12 ch.16 by default, GTAP 7 ch.14 as the alternative) and the CDE calibration;
- `checks.py`: hard checks;
- `config.py`: strict config;
- `read_har.py`: the independent read-back (harpy3, CoPS);
- `julia/write_jls.jl`, `julia/model_check.jl`, `julia/prepare_for_solve.jl` and the pinned Julia project (`julia/Project.toml`, `Manifest.toml`).

The mutation tests are `dataset/build/tests/test_s15_checks.py`. Choices are in `dataset/build/config/s15/s15_choices.csv` (14 rows).

The gate is `data-round/READINESS.md` §1 S15: the files load in GTAPv7-Julia and aggregations solve (David: the full 167×51 solve is not required; READINESS writes 168, but REG has 167). PLAN §3(j) fixes the layout (HAR canonical, Float32; JLS a convenience copy) and §3(i) the tolerance (identities to 1e-6 after writing to Float32).

## Inputs

Upstream stamps:
- S01: `regions.csv` (single economies and composites, for the CDE target rows).
- S14: the 31 header tables, `sets_s14.csv` and `flags.csv` (CARRY-SAVE).

`S15-Hchain` checks that the S01 S14 was stamped on is the one read here. S15 changes no number of the data base: every data header is the S14 table as a dense array.

## What the stage writes

1. **`gsdfset.har`**: DREL (`ocge_gtapv7`, `y2022`, `s14_<first 8 of the S14 SHA256SUMS>`), REG, COMM, ACTS, ENDW, MARG, ENDT. Elements in lower case, in the S14 order. ACTS = COMM.
2. **`gsdfdat.har`**: DREL and the 31 headers of `notes/model_requirements.md` §1b (VDFB … MAKB), REAL, Float32, full dimension labels. Length-1 axes are kept (the write_har_2022.jl writer drops them).
3. **`gsdfpar.har`**: DREL, the 14 real parameter headers and RDLT (integer).
4. **`gtap_s15.jls.gz`**: a Julia `Dict` with `sets`, `data` (Float64, the S14 values), `parameters`, `dims` and `meta`, serialised by Julia 1.12 and `gzip -9 -n`, so two runs give the same bytes.

## Parameters (GTAP 12 Data Base ch.16; GTAP 7 ch.14 as the alternative)

Fix round, QA finding #7 (David 2026-10-24, "stick to GTAP"): the default edition is GTAP 12 Data Base ch.16 (`docs/gtap_method_sources/GTAP12_ch16_behavioral_parameters.txt`; choice `parameters` = `gtap12_ch16_standard`). GTAP 7 ch.14 (David's S15 card, 2026-10-24 12:02) stays as the alternative `gtap7_ch14_standard`. The choices `parameters`, `cde_targets`, `sector_means` and `cde_price_reading` must name the same edition, or the config stops (`config.EDITIONS`).

| | GTAP 12 ch.16 (default) | GTAP 7 ch.14 (alternative) |
|---|---|---|
| Elasticities | Table 16.2, `gtap12_table16_2.csv` (65 sectors) | Table 14.2, `gtap7_table14_2.csv` (57 sectors) |
| Sector map | `sector_gtap12.csv` (members from GTAP 12 ch.2 Tables 2.11–2.12) | `sector_gtap7.csv` |
| CDE categories | Table 16.4 | Table 14.3 |
| CDE targets | Tables 16.6/16.7, `cde_targets_gtap12.csv` (163 regions, GTAP 12 incomes) | Tables 14.5/14.6, `cde_targets_gtap7.csv` (113 regions, 2004) |
| Target rows | `cde_target_rows_gtap12.csv` (GTAP 12 composites, Table 2.14) | `cde_target_rows.csv` |
| Own-price reading | Table 16.7 compensated, as titled | Table 14.6 read as compensated (David's choice after QA B1) |

Each table row cites the chapter lines it is transcribed from; `tests.test_s15_checks.EditionTest` checks every value against those lines.

- **ESBD, ESBM, ESBV** by sector: same value in every region. A sector covering several GTAP sectors takes the unweighted mean of its members (the rule of the public build on main). Against GTAP 7, Table 16.2 changes σVA in primary agriculture (0.26 against 0.24) and construction (1.40 against 1.68), and eeq is a sector of its own (σD 4.40, σM 8.80, against the mean of ele and ome). σD and σM are otherwise unchanged. The Fontagné, Guimbard and Orefice (2022) elasticities of Table 16.3 are GTAP 12's optional headers ESMC/ESDC, not the default ESBD/ESBM, so they are not used.
- **CDE categories.** Table 16.4 moves pet (pc) to Mnfcs, its (ISIC 62–63, in GTAP 12 cmn) to TransComm, and prints oil under GrainCrops (GTAP 7: TransComm). The oil row is transcribed as printed; households buy little crude oil (37 bn of 58 trn). Multi-member sectors take the category of most members, or of household purchases (rle: dwellings, HousOthServ).
- **ESBT = ESBC = 0**, ESBI 0, ETRQ −5, ESBQ 0, ESBG 1, ESBS 1, RFLX 10, RDLT 1 (`s15_scalars.csv`; ch.16.B and D give the defaults ESUBT = 0 and RORDELTA = 1 with RORFLEX > 0 but no RORFLEX value; ESBI as in the standard GTAP gsdfpar.har).
- **Factor mobility.** Labour and capital mobile, land sluggish with ETRE −1 (ch.16.C gives no ETRAE value). Natural resources are fixed by sector, the standard GTAP setting (EFLG natlres = 0, 0, 1; choice `natres_mobility`), where ch.16.C (like ch.14.3) calls them sluggish. This also avoids the Julia levels CET, which raises each cell to the power 1/σT and overflows at GTAP's ETRE of −0.00001.
- **CDE (INCP, SUBP)**, ch.16.E (ch.14.5–14.6). The targets are the income and compensated own-price elasticities of the 10 categories.
  - A single economy with its own row uses it (Palestine is PSE in Tables 16.6/16.7). Every other region takes the row in the edition's target-row table: the GTAP composite that held it, or the unweighted mean of the rows that hold its members (XCB: HTI, JAM, XCB, XCA; XEF: COM, BDI, RWA, XEC; XSM: BOL, ECU, PRY).
  - Income targets are scaled to Engel aggregation on the 2022 household shares (Σ s η = 1).
  - The two linear systems are solved exactly; where α or e leave (0, 1) and (0, ∞), a bounded least-squares fit is used (the fuzzy constraints of ch.16.E.1).
  - INCP is floored at 1e-6 after the normalisation Σ s e = 1 (fix list A11, choice `incp_floor`). A floor is sensible, but no documented GTAP rule exists (David's fact-check, 2026-10-24), so it is our choice. The income elasticities are homogeneous of degree 0 in e, so the floor moves them by about 1e-6.
  - Every commodity in a category takes the category's parameters, as GTAP does.
  - **Bounds (fix list B6).** A read-only calibration on the current S14 inputs gives, GTAP 7 → GTAP 12: bounded regions 25 → 52, cells at a bound 37 → 119, INCP floored 25 → 88 cells, largest own-price gap 0.228 → 0.407. Table 16.6 prints negative GrainCrops income elasticities for 11 of our regions (USA, CAN, KOR, …), which no e > 0 meets, and the Frisch-LES own-price targets sit at the CDE's α ≤ 1 frontier in high-income regions. `S15-Rbounds` reports the count; IMPROVEMENTS_LOG S15-4.

## Model-run preparation (smoke map only)

Choice `model_run_prep` = `in_memory_armington_swap` (David's S15 model-run card).

The Julia port writes each agent's Armington nest in logs, so an agent that buys a commodity only domestically or only from imports gives log(0) and Ipopt stops with "Invalid number" (INVALID_MODEL). GEMPACK's linear form has no such problem, and GTAP 10 has no such cells. This data base keeps the structural zeros of the source tables (S13 FIT): 6,010 domestic-only and 14,539 imported-only firm cells (main's public data base has 1,644 and 3,360) (`S15-Rprep`).

`model_check.jl` therefore runs `prepare_for_solve.jl` on the aggregated copy in memory before calibration. `armington_swap!` gives each such agent a small amount (1e-6 of its purchases, at most half the donor's holding) of the missing side by swapping with the agent of the same commodity and region that has most of it. Region totals of domestic and imported purchases at basic prices are unchanged, so market clearing holds; each agent's totals at basic and purchasers' prices are unchanged. Each agent moves both sides at its own power on that side, so tax revenue is unchanged too (1.5e-11 on the smoke map); the donor's average powers shift by at most a few 1e-7. A pair with no donor (no domestic purchase by any agent in the region) stops the run with a message to pool that commodity or region. Since the fix round (A13) S14 seeds the 332 such pairs the data base had, so none is left. The data base files are not changed; the swap counts are in `model_check_s15.txt` (IMPROVEMENTS_LOG S15-1). `output/NOT_FOR_PUBLICATION.md` tells a user of stock GTAPv7-Julia to run this step. The files carry the headers GTAPv7-Julia reads; DVER and the GEMPACK long names are not written, so GEMPACK or RunGTAP use needs them added.

Margin supply needs no preparation: S08 now gives every region positive VST (TiSMoS freight, with the BaTIS fallback where TiSMoS is zero, capped at the region's own transport exports; S08 spec §7). `model_check.jl` asserts VST > 0 on the smoke map.

## Checks

**Hard checks:**
- Config (`Hconfig`), upstream G0, the chain (`Hchain`), inputs IN1 and IN2.
- Dense arrays equal to the S14 tables, in total and in non-zero count (`Hdense`).
- Parameter ranges (`Hparams`): elasticities > 0, SUBP in (0, 1], INCP > 0, one mobility type per factor, capital mobile, sluggish ETRE < 0, all finite.
- INCP floor (`Hincpfloor`): every INCP at least 1e-6; the floored category cells are listed (fix list A11).
- The JLS written by Julia 1.12 (`Hjls`).
- On the files as read back by harpy: every header with the expected dimensions and no other (`Hdims`); sets equal to S14, lower case, ACTS = COMM (`Hsets`); every cell equal to its Float64 source within Float32 rounding, 1.2e-7 relative (`Hfloat32`).
- On the Float32 values: VCIF = VFOB + VTWR, world VST = VTWR, market and import clearing, zero profit (`Hidentities`); SAVE = Y − C − G and world SAVE = world I − VDEP (`Hsave`); no negative cell except SAVE (`Hsign`); EVFP > 0 wherever there is output (`Hevfp`). All 1e-6 relative.
- Every region supplies every margin, VST > 0 (`Hvst`).
- Smoke-map S–I gate (`Hmapsave`, E50): σsave = SAVE/Y and σ_qinv = SAVE/world SAVE of every group in [−1, 1].
- GTAPv7-Julia (`Hjulia`): HeaderArrayFile reads the three files; the JLS equals the HAR within Float32; the smoke map aggregates with the package's `aggregate_data`, is prepared in memory (above), calibrates (`generate_initial_model`, `generate_calibration_inputs`, `run_model!` on the calibration closure) solves unshocked on the default closure with no qo moving more than 1e-6 relative, and solves a 5% tariff shock on mfr from the rest to USA, with qxs falling and Walras' law holding to 1e-6. Each solve must be solved and feasible.
- No private file (`Hprivate`), the secret scan (`Hsecret`).

**Report-only checks:**
- CARRY-SAVE regions on the smoke map (`Rcarry`): KGZ, LBR, YEM and LBN sit in the pooled rest group. The flags carry on to S16, where every map is checked.
- CDE fit gaps and method by region (`Rcde`), the Engel factor (`Rengel`), how each region got its target row (`Rtargets`), the category cells at a bound (`Rbounds`, fix list B6).
- Python package versions against `requirements-s15-build.txt` (`Renv`).
- File sizes (`Rsizes`), all under GitHub's 100 MB.
- Commodity-destination pairs with no import source (`Rnosource`, model_requirements §1d item 13).
- One-sided Armington agents in the full data base (`Rprep`).

## Smoke map

`config/s15/maps/smoke_11x7_*.csv`: SAU, ARE, QAT, KWT, IRQ, OMN, BHR, IRN, USA and CHN as their own regions plus the rest (11 regions from the 167); seven sectors (agr, oil, gas, pet, mfr, trn, svc); all eight factors. The full map suite is S16 (PLAN §4).

## Outputs

All in `dataset/stages/S15_har_jls/output/`:
- `gsdfset.har`, `gsdfpar.har`, `gsdfdat.har`, `gtap_s15.jls.gz`;
- `model_check_s15.txt` (the Julia result lines; the run time is in `build.log` only, so two runs give the same file);
- `parameters_by_sector_s15.csv`, `cde_target_rows_s15.csv`, `cde_calibration_s15.csv.gz`, `smoke_map_gate_s15.csv`;
- `NOT_FOR_PUBLICATION.md`: the files carry the S10 tariff wedge, as the S14 tables do.

The adjustments ledger is header-only: S15 changes no number of the data base.

## Running

- Build: `pip install -r requirements-s15-build.txt` (numpy and pandas pinned; the stage sets one BLAS thread, and `S15-Renv` reports the versions in use, so the Float64 JLS copy is bit-stable; Grok QA N1).
- Reader: `python3 -m venv <venv> && <venv>/bin/pip install -r requirements-s15-reader.txt` (harpy3 needs numpy < 2.3).
- Julia: 1.12 with the pinned project: `julia --project=s15_har/julia -e 'using Pkg; Pkg.instantiate()'`.
- Run: `cd dataset/build && S15_HARPY_PYTHON=<venv>/bin/python python3 s15_har_jls.py`. It takes about 8 minutes, most of it the Julia smoke solve. `S15_JULIA` names another Julia binary.
- Tests: `S15_HARPY_PYTHON=<venv>/bin/python python3 -m unittest tests.test_s15_checks` (the read-back test is skipped without it).
