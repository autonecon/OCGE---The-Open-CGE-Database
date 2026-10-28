# S14 final assembly

Built 2026-10-24. The stage entry is `dataset/build/s14_final_assembly.py`. The method is the package `dataset/build/s14_assembly/`:
- `method.py`: trade block, re-balancing, the region assembly and the regional accounts;
- `checks.py`: hard checks;
- `config.py`: strict config.

The screens are `dataset/build/screens/s14_suite.py`. The mutation tests are `dataset/build/tests/test_s14_checks.py`. Choices are in `dataset/build/config/s14/s14_choices.csv` (15 rows).

The method is GTAP 12 ch.17B §B.2 (final assembly module), with PLAN §3(i) "then a global pass" and the S14 gate in `data-round/READINESS.md` §1: supply = demand, income = expenditure, no sign violations and no zero-divides (17B p.3). The pre-solve S–I gate of PLAN §3(h)3 (E12, E28) runs here.

## Inputs

Upstream stamps:
- S01: regions and sectors.
- S02: VKB, VDEP, POP and GDP; the BoP memo (net primary and secondary income).
- S08: VTWR by route for goods.
- S09: services VXSB by route, and travel by host and visitor.
- S10: goods VXSB, VFOB, VCIF and VMSB by route.
- S11: energy VXSB, VFOB, VCIF, VMSB and VTWR by route, VST, and the energy output targets.
- S12: `io_s12`, only for the B06 travel split that S13 applied; `natres_s12.csv` and the S12 config `config/s12/natres_targets.csv` and `s12_choices.csv` (`natres_rule`, `natres_guard`) for the B16 step.
- S13: `io_s13`, `factors_s13`, the held trade, the C, G and I targets, and the dropped travel.

S14 reads no raw data. The S12 config is read so that S14 applies S12's own targets, σVA and guard; `S14-Hnatcfg` checks them against what S12 booked. `S14-Hchain` checks that every upstream it reads is the one the other upstreams were stamped on.

## What the assembly does

1. **Trade block** (17B §B.2: merge with the trade, protection and margins data).
   - Bilateral VXSB, VFOB, VCIF and VMSB by commodity and route come from S10 (goods without energy), S11 (energy), S09 (services) and the travel rows S13 held. Services and travel have no margin and no border tax.
   - The travel rows are rebuilt with S13's own `assemble_trade` on the same inputs. `S14-Hmerge` checks that the bilateral flows add up to `trade_s13`, by region and commodity.
   - VTWR comes from S08 for goods and from S11 for coa, oil, gas and pet, and VST from S11.
   - **Trade cells below USD 1** (fix list B14, s14 choice `small_trade`; our choice: GTAP filters small values, but its threshold is not in the documents we hold). After `S14-Hmerge` and before the re-balancing, a route with VXSB below 1e-6 USD million is dropped with its border values and its VTWR, and a VTWR cell below 1e-6 on a route kept is set to zero (VCIF falls by it; VMSB keeps VMSB/VCIF). World VST falls with world VTWR, one factor per margin. The output an activity loses (its dropped sales abroad and margin supply) leaves its S13 output and comes off its factor payments pro rata (EVFP, EVFB and EVOS alike), so zero profit holds without a new output tax; where its EVFP is under twice the loss, the output tax takes it. On the S16 outputs: 118,324 routes (0.028 USD million) and 403,224 margin cells (0.057 USD million); the largest output loss is 0.004 USD million (CHN sea). The cells are listed in `small_trade_s14.csv.gz`, and the ledger has one row per exporter and kind and one per activity (rule `B14 trade cells below USD 1 set to zero`). A row whose imports all go (GIN msp) is scaled to zero rather than moved onto one cell.
2. **Re-balancing** (17B §B.2, fourth item). The upstream files are rounded to 1e-6 USD million, so the identities hold only up to rounding. S14 makes them exact:
   - VCIF = VFOB + ΣVTWR on each route, with VMSB keeping VMSB/VCIF. A route whose CIF is 0 keeps no VMSB.
   - World VST = world VTWR, one factor per margin.
   - Imported purchases add up to VMSB. The residual goes to the largest activity cell of the row.
   - Output = domestic sales, and the output tax closes zero profit.
   - Every move is at most 1e-3 USD million (`S14-Hrebalance`). A larger gap is not rounding and fails the stage.
   - **One-sided pairs** (fix list A13, s14 choice `one_sided_seed`; GTAP 10 has none, the size and the closure are our choice). Before the output re-balance, each commodity a region buys only from imports (332 pairs: coa 100, oil 76, gas 73, pet 60, hhe 20, msp 2, ore 1) gets domestic purchases: every column j that buys the import buys `SEED_RATIO` = 1e-4 of that purchase from domestic producers (inside the 1e-6 to 1e-3 range of the fix list) and gives up the same basic value of its purchases of the commodities that are not one-sided in the region, pro rata over its domestic and imported cells. A column gives up at most `SEED_GIVE_UP_MAX` = 0.5 of those purchases (our choice, fix round w17), so no cell turns negative or empties; where that binds, the rest of the row's seed goes to the other buyers pro rata to their imports (`method.seed_shares`), so the row seed stays 1e-4 of imports exactly. It binds in URY, whose mvh column (created at S13 for exports, `REP-TABLE-COLUMN`) buys 443.8 USD million of imported crude and 0.013 of everything else: under the plain pro-rata rule the crude seed took ten times the column's other purchases, which gave 168 negative mvh cells, made mvh one-sided and left the gas seed short. Its basic total stays, and its remainder tax rate is re-set so its tax and purchaser totals stay too (its energy-row wedges are kept). The imports given up become the new activity's imported inputs. Each activity whose domestic sales fell hands the same share of its whole column (domestic and imported inputs, TLS, PSE_input, EVFP, EVFB, EVOS and output tax) to the new activity, which therefore has the cost structure of the region's own supplying columns. Every row and column total, factor total by region, tax total, C, G, I, X, M and GDP stay as they were. The four pairs with output that is all exported (oil in COD, GAB, GUY, TCD) add the seed to that column. The pairs are in `seeded_pairs_s14.csv`; the ledger has one row per pair (rule `A13 seed domestic supply in a one-sided pair`) and one per supplying activity (rule `A13 seed cost structure carved from the supplying columns`). **The other side (fix round, S15 smoke map):** after fix-round A8 crude goes only to refining and the listed direct users, so the B06 travel no longer gives every region a little imported crude, and 31 pairs (oil in 30 crude exporters, IRN, SAU, RUS, IRQ, KWT, MEX and others, and msp in GIN) are bought only from domestic producers, which the Julia levels model cannot take (log of a zero import share). After the trade re-balance, each such pair (r, c) imports a = 1e-4 of its domestic purchases (`method.import_seed_swaps`): two new routes c s->r and c r->s with VXSB = VFOB = VCIF = VMSB = a (no export tax, margin or tariff), and in both regions the buyers switch a of their domestic purchases of c to imports, pro rata (`method.switch_to_imports`; the cell rate is the same on both, so each column keeps its basic, tax and purchaser totals). The partner s is the largest exporter of c that is not itself domestic-only in c, has neither route yet, and whose switches stay within `SWAP_PARTNER_MAX` = 1e-2 of its domestic purchases of c (KAZ, NOR, CAN, ARE and GBR on the 2022 data). Every output, column, factor, tax, C, G, I, X - M and GDP stays as it was in both regions. Our choice (GTAP 10 has no one-sided pair). The pairs are in `swapped_pairs_s14.csv`; the ledger has two rows per pair (rule `A13 seed imports in a domestic-only pair (swap with a partner exporter)`).
   - **S12 tax splits** (fix list A3, A4). S14 reads `d29_split_s12.csv` and `pse_land_factor_use_s12.csv` from S12 when they exist. Their join (`method.join_s12_tax_split`) is a stub until worker w5's layout is fixed: a present file fails `S14-Hs12join`, so it cannot be ignored silently.
3. **Purchaser values** (s14 choice `purchaser_split`, fix list A1, follows GTAP 12 ch.12). Every cell keeps its S13 net product-tax rate from `tax_cells_s13.csv.gz` (tls_rate + pse_rate), the same on its domestic and its imported purchases: the pet, coa, gas and ely rows carry the S10 energy-tax rates S13 placed, and the other rows their commodity rates (S13 `non_energy_rates`, QA round 2 P1; one rate where a column has g ≤ 0). S14 keeps each cell's wedge over the column's median non-energy rate and sets one remainder rate per column in its place so that the column's tax equals its io_s13 TLS and PSE_input over its basic purchases (`method.cell_powers`); on the rounded io_s13 it equals S13's remainder up to rounding. So column totals, C, G, I and every tax total are what one power per column gives, and the energy-row rates survive into the tables and the HAR. A column the A13 seed moves keeps its wedges and its tax value; only its remainder rate moves. The alternative `one_tax_power_per_column_dom_and_imp_from_s13` (one power per column, as before the fix round) would undo A1.
4. **Make matrix.** MAKB is diagonal and equals output at basic prices. MAKS = MAKB less the output tax, so to = MAKB/MAKS.
5. **Factors.** EVFP, EVFB and EVOS come from `factors_s13` as they are, except for the ledgered B14, A13 and B16 moves. The labour split (ch.14B) and the land share (ch.14A) were applied at S12.
   - **Natural resources on the final data** (fix list B16 and IMPROVEMENTS_LOG S12-17; s14 choice `natres_final`; follows GTAP: GTAP 12 ch.17B §B.1 does the reallocation to natural resources at global data assembly, after the FIT; David 2026-10-24 "stick to GTAP"). S12 sets the GTAP 7 ch.12.A share at its prior θVA. S13 keeps each factor's share of VA but moves VA over output, so η holds only at the prior. After the re-balancing, S14 sets the share again in every for, fsh, coa, oil, gas, ore, min and msp activity with value added (`method.natres_final`):
     - θVA = ΣEVFP / MAKS (MAKS is the cost: purchases at purchasers' prices plus EVFP), and the share of VA is σVA / (η θVA + σVA). The target and σVA of each cell are the ones S12 booked in `natres_s12.csv` (`eta_target`, `sigma_va`; fix round w17): the `config/s12/natres_targets.csv` value, or for msp under the w13 blend (`msp_natres_target`) the region's effective η, which S14 applies as it is; a cell with value added and no booked target is an `Hassemble` issue. `S14-Hnatcfg` checks each applied target against the booking and the booking against the config (the msp η recomputed from the booked weight and θVA, within 1e-5). The guard comes from S12 `natres_guard` (θVA below 0.10, or cost not positive: the share at θVA = 0.10; our choice, flag NATRES-GUARD). So η = σVA(1/θR − 1/θVA) equals the target on the written tables.
     - The difference between that share and the natural resources the activity carries comes out of (or goes back to) labour and capital. Every labour group and capital are scaled by one factor, on EVFP, EVFB and EVOS alike, so each cell keeps its factor-use and income-tax rates. Land is not touched.
     - Natural resources keep their own rates: those of the cell, else of the region's natural resources, else no factor-use tax and the region's income-tax rate on capital (S12 books CIT on natural resources as on capital and no factor-use tax).
     - Each activity's value added, cost, output tax and MAKS are unchanged, and so are Y, SAVE, GDP, C, G and I. What moves is the split of income by factor, and with it the factor-use and income-tax totals (labour carries SSC and PIT, natural resources CIT only).
     - One ledger row per moved cell (rule `B16 natural resources at the ch.12.A target on the S14 data`, flag NATRES-FINAL); the cells are in `natres_s14.csv`. `as_s13_s12_prior_shares` keeps the `factors_s13` split. S14 stops (ConfigError) if `natres_final` is on and S12 `natres_rule` is the WDI alternative.
     - On the pre-round outputs, with the S12 shares carried through S13: 1,088 cells; 56.4 bn net (72.5 bn gross) moves to natural resources, most in gas (+38.1 bn) and coal (+14.6 bn); the largest are RUS gas +14.8, IND coa +7.3 and IRN gas +5.8 bn. The guard holds 37 cells (12 at S12), all under 0.3 bn of VA except RUS msp (5.4 bn).
6. **Regional accounts.** Y = ΣEVFB − VDEP + every indirect tax (product taxes on all agents, output, factor-use, export and import taxes), which is the model's regional income. SAVE = Y − C − G, so S − (I − VDEP) = X − M (GTAP 12 ch.7 eq. 7.1). VKB, VDEP and POP come from S02.

## Pre-solve S–I gate

These items are hard, per region:
- VKB > 0;
- I > 0;
- Y > 0;
- VDEP below capital income (ΣEVOS capital). The report `Rvdepk` lists each region that fails it with its capital income in `factors_s13` and after the S14 moves, so the check names the stage that set it (fix round w17: GNQ and TLS fail with capital income already below VDEP in `factors_s13`; S14 moves it by −7.1 and −0.1 USD million).

These items are report-only:
- SAVE ≤ 0 (`negative_save`; David chose report-only in the S14 thread, 2026-10-24 10:24 UTC+7, after QA round 1). SAVE is GTAP's eq. 7.1 residual, so SAVE ≤ 0 is the same statement as a trade deficit at least as large as net investment, or VDEP above I; a check on that "cause" passes by construction (QA C1). Each such region is labelled with that label (flag NEG-SAVE), with the S02 BoP memo flows of eq. 7.2 beside it in `si_gate_s14.csv`, and screen 1 sets X − M against the S02 implied net exports, which separates trade-data causes (HKG, BLR) from genuine ones. The switch `hard_save_positive` makes SAVE > 0 hard.
- The saving share SAVE/Y in [−1, 1] (David's S14 card, 2026-10-24). The bound belongs to the Julia model (σsave) and applies to the regions of an aggregation map. KGZ, LBR, YEM and LBN are outside it and carry flag CARRY-SAVE to the S15–S16 aggregation solve checks. Their upstream causes are logged in `docs/IMPROVEMENTS_LOG.md` (S14). The switch `hard_per_region` makes this item hard.
- VDEP < I, as in GTAP (E28). It is carried as flag CARRY-VDEP.

## Checks and screens

**Hard checks:**
- Config, upstream G0 and the chain (`Hchain`), inputs IN1 and IN2.
- Export taxes carried (`Hxtax`, fix list A2, `s13_fit.checks.export_tax_held` on the bilateral table summed by exporter and commodity): VFOB − VXSB is the S10 export-tax rate times the S11 VFOB on coa, oil, gas and pet, the S10 wedge on other goods and 0 on services and travel (1e-3 USD million: rounding and the B14 routes).
- Merge totals (`Hmerge`), the rebuilt travel drop equal to S13's (`Htravel`), assembly issues (`Hassemble`), sets as written, with ACTS = COMM (`Hsets`), all 31 headers (`Hheaders`), re-balance bound (`Hrebalance`).
- Route CIF (`Hcif`), global margins (`Hmargins`), domestic market clearing (`Hmarket`), import clearing (`Himports`), zero profit (`Hprofit`), diagonal make (`Hmake`), one tax power per cell on domestic and imported purchases and, on the non-energy rows of a column, the S13 cell rates plus one remainder shift per column (`Hpower`; the S13 cell rates are the commodity rates of QA round 2 P1 and, for a listed S13 PSE input item, `pse_input_items_s13.csv`, fix round wG, its own S13 net rate; a cell passes within 1e-8 or at most 1e-3 USD million of tax), and every cell's rate, energy and non-energy rows, equal to S13's cells (`Hcellrates`: within 1e-6, or at most 1e-3 USD million over the column's basic purchases; in a column the A13 seed moved, up to the column's one shift). The powers come from the rounded `io_s13`, so they differ from `tax_rates_s13` by rounding only (up to about 3e-5), and the output re-balance leaves output taxes of the order of 1e-4 USD million on many activities.
- Factor zero patterns (`Hfactors`), factors against S13 plus the ledgered B14, A13 and B16 moves, the A13 moves netting to zero by region and factor and the B16 moves by region and activity (`Hfac13`), η at the ch.12.A target in every unguarded resource cell on the written tables within 1e-6 and the floor share in a guarded one (`Heta`, the S12 check `natres_eta` on the S14 tables), labour and capital moved by one factor with rates kept, land unmoved and each activity's VA kept (`Hnatpro`), the targets and σVA equal to those S12 booked (`Hnatcfg`), no commodity bought from one source only, each seed at 1e-4 of imports and each swap route at its size with no tax or margin (`Hseed`), no VXSB route or VTWR cell between 0 and USD 1 (`Hsmall`), no S12 tax split left unjoined (`Hs12join`), signs with no exception (`Hsign`), zero-divides, including EVFP > 0 wherever there is output (`Hzerodiv`).
- GDP from expenditure and from income equal to S02 GDP (`Hgdp`), C, G and I equal to the S13 targets (`Hfd`), the saving identities (`Hsave`), the S–I gate (`Hsi`).
- Product taxes by region as S13 held them (`Hptaxs13`, round-3 final QA item 3, S13 `product_tax_totals`; `checks.product_tax_s13`): the net product tax of firms, households, government and investment in the written tables (purchasers' less basic values, less the PSE input support) equals the S13 fitted TLS by region in `product_tax_regions_s13.csv` (io_s12 general money plus the held energy-tax rates on the fitted energy purchases, less the fuel subsidies) within max(1e-6 relative, 1 USD m); the detail gives the gap to the round-3 QA prior.
- No private file, the secret scan, and the screens.

The hard checks run on the files as written, read back.

**Report-only checks:**
- Saving share (`Rshare`).
- Negative SAVE with causes (`Rnegsave`).
- VDEP ≥ I (`Rvdep`).
- Gross return on capital against 4% (`Rcapital`).
- The model's basic-price investment quirk (`Rinvbasic`, model_requirements §1d item 11).
- World tax revenue by type (`Rtaxes`).
- Routes with 0 < VXSB ≤ 1e-4 (`Rsmall`).
- Pairs bought only from domestic producers (`Rdomonly`): GIN msp, whose imports B14 removes.
- B16 cells held by the guard on the S14 data (`Rnatguard`), and the income moved to natural resources by sector with the ten largest moves (`Rnatres`).
- The investment share σ_qinv = SAVE/ΣSAVE (`Rqinv`), which the Julia model also bounds by [−1, 1] on an aggregation map.

**Screens** (SCREENS.md):
1. SAVE against SAVE with the BoP memo flows (eq. 7.2), and X − M against the S02 implied net exports.
2. Saving share outside [−1, 1], and SAVE ≤ 0.
3. Year jumps: none, because S14 picks no source year.
4. Stale years: none, for the same reason.
5. Identities: VMSB below VCIF, negative cells, output with no factor payment. Any hit fails.
6. Coverage: tiny routes, and regions with no land, natural-resource or capital payment.
7. Moves against `S14_PREV_OUTPUT`.

## Outputs

All outputs go to `dataset/stages/S14_final_assembly/output/`. Header tables are long, with non-zero rows only and 12 significant digits:
- `firms_s14.csv.gz`: region, comm, acts, VDFB, VDFP, VMFB, VMFP.
- `final_demand_s14.csv.gz`: region, comm, VDPB, VDPP, VMPB, VMPP, VDGB, VDGP, VMGB, VMGP, VDIB, VDIP, VMIB, VMIP.
- `endowments_s14.csv.gz`: region, endw, acts, EVFP, EVFB, EVOS.
- `make_s14.csv.gz`: region, comm, acts, MAKS, MAKB.
- `bilateral_s14.csv.gz`: comm, src, dst, VXSB, VFOB, VCIF, VMSB.
- `vtwr_s14.csv.gz`: marg, comm, src, dst, VTWR.
- `vst_s14.csv`: marg, region, VST.
- `regional_s14.csv`: region, SAVE, VDEP, VKB, POP. POP is in millions of persons, as in GTAP.
- `sets_s14.csv`: REG, COMM, ACTS, ENDW and MARG, in order.

Reports:
- `accounts_s14.csv`: the regional accounts and the tax summary by type (17B §B.2 tax rates summary).
- `si_gate_s14.csv`
- `rebalance_s14.csv.gz`
- `seeded_pairs_s14.csv`: region, comm, imports, seed, ratio, n_buyers, seed_va, seed_ptax, output_before, output_after (A13).
- `swapped_pairs_s14.csv`: region, comm, partner, musd (A13, the domestic-only pairs).
- `small_trade_s14.csv.gz`: kind (VXSB route or VTWR cell), marg, comm, src, dst, VXSB, VTWR (B14).
- `natres_s14.csv`: region, sector, eta_target, sigma_va, cost_musd, factor_va_musd, theta_va, theta_va_used, guard, natres_before_musd, natres_musd, moved_musd, labour_capital_factor, share_before, share_after, eta_before, eta_after, natres_rates_from (B16).

The header tables carry the S10 tariff wedge and are not for publication (`NOT_FOR_PUBLICATION.md`).

The adjustments ledger holds only the B14, A13 and B16 rows (rules listed in `config/s16/ledger_rules.csv`). Every other change is rounding: each re-balancing move is in `rebalance_s14.csv.gz` and at most 1e-3 USD million.

## Notes

- **Large subsidies on small flows** (17B §B.2). Before the fix round (one tax power per column) this could not arise at cell level; with A1 the energy rows carry their own rates (S13-Hrates, S14-Hcellrates); the strongest column subsidy is IND crp, power 0.61, on a 130 bn base. On routes, 47 have a tariff power above 3, the largest 30.8 on fbt GIN to EGY (VCIF 0.0075 USD million). They come from S10 and are carried as they are.
- **Endowment totals after B16.** The B16 step changes the regional totals of EVFP, EVFB and EVOS by factor: natural resources rise where θVA fell after the fit (gas, coal) and labour and capital give the difference. On the pre-round outputs, world natural resources at EVFB go from 1,762 to 1,818 bn, capital from 42,473 to 42,436 bn and labour by −17.4 bn; ΣEVFB rises by 1.5 bn because the income moved off labour no longer pays SSC (ΣEVFP and Y are unchanged). S15 writes its EVFP, EVFB and EVOS headers from these tables, so it carries the new split with nothing to change (natural resources stay sector-specific, `natres_mobility`). S16 checks VDEP below capital income (`S16-Hvdepk`, also `S14-Hsi`): the smallest ratio of capital income to VDEP falls from 1.421 to 1.417 on the replay, so no region crosses it. The ledger rule is on `config/s16/ledger_rules.csv`.
- **FBEP.** The 204.9 bn farm support memo stays inside the factor-use taxes (GTAP 12 ch.15 p.3). No FBEP header is written.

## Running

- Run: `cd dataset/build && python3 s14_final_assembly.py`. It takes about a minute.
- `GTAP_STAGES_DIR=<dir>` runs against a scratch copy of the upstream stages.
- `S14_PREV_OUTPUT=<dir>` turns on screen 7.
- The screens write their reports to `dataset/reviews/screens/S14/` in the repo even when `GTAP_STAGES_DIR` is set, so a scratch run changes tracked files there; restore them with `git checkout` after it.
- Tests: `python3 -m unittest tests.test_s14_checks`.
