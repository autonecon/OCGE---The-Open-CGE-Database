# S13 FIT

Built 2026-10-24; rebuilt the same day after QA round 1 (the GTAP 17.41-17.46 form, ch.17A footnote 4, the smear rule and the output-support check). The stage entry is `dataset/build/s13_fit.py`. The method is the package `dataset/build/s13_fit/`:
- `fit.py`: the solver;
- `method.py`: targets, prior and fitted table;
- `checks.py`: hard checks;
- `energy.py`: the energy-use caps and energy import proportionality (fix round A10 and B1);
- `config.py`: strict config.

The screens are `dataset/build/screens/s13_suite.py`. The mutation tests are `dataset/build/tests/test_s13_checks.py`. Choices are in `dataset/build/config/s13/s13_choices.csv` (39 rows).

The method is GTAP 12 ch.17A (FIT, van der Mensbrugghe) as PLAN §3(i) sets it, with the ch.12 §12.4.1 smearing and the ch.9D representative table. David's rule for this version is to follow GTAP and log improvements in `docs/IMPROVEMENTS_LOG.md` (S13 section) rather than apply them.

## Inputs

Upstream stamps:
- S01: regions and sectors.
- S02: GDP, C, G and GFCF.
- S03: the representative table.
- S09: services and travel trade.
- S10: goods trade without energy, and farm support.
- S11: energy trade, VST, energy output values and the fossil-fuel consumption subsidies (`fuel_subsidies_s11.csv`, fix round B15).
- S12: `io_s12` and the factor payments.

S13 reads no raw data.

## Objective and solver

GTAP's information function is eq. 17.1 + 17.2, with weights 1 as in the GEMPACK code (footnote 6). Its two terms add up to I = Σ_a E_a Σ_k θ_ka ln(θ_ka/θ0_ka), the cross-entropy of each column's cost shares, weighted by the column total. Value added is one share of an activity.

The model is eq. 17.41-17.46 with 17.22 and 17.28. A column's shares carry its own adding-up price (µt_a), and a shadow price appears only on
- an import row (µm_c, eq. 17.16), and
- the market-clearing row of an activity whose output is held: the S11 energy targets, in the place of GTAP's IEA energy constraints (µiea, eq. 17.8-17.9).

So a column's domestic shares and its value-added share move only with the column. An activity whose output is free takes it from its own market-clearing row (eq. 17.28), with cost equal to output (eq. 17.22); there is no optimality condition on E_a. The constraints are linear in cell values, so the problem is convex. Each region is solved on its own because trade is fixed:
- Newton's method on the first-order conditions, with a backtracking line search.
- A homotopy from the prior (path 0) to the targets (path 1), as GEMPACK applies the FIT shocks in steps.
- Every held row is met to a relative residual of 1e-9.

A region that does not converge, or whose final-demand totals are negative, is named with its binding rows. It stops the stamp. There is no slack and no plug.

**Own use (diagonal cells)** (fix round wC, independent QA MEDIUM-3; choice `own_use_share`, default `cross_entropy_free`, GTAP). An activity's purchases of its own good, domestic and imported, are a cost share like any other: GTAP's FIT (eq. 17.1-17.2, 17.5) has no separate term, penalty or cap for them, and ch.17B adds none. Two things follow, and they are GTAP's behaviour, not a defect:
- In a free column the diagonal share stays at its prior unless a priced row of that column moves. When the fit pushes an import or a held energy good out of a column (its share falls), every free share rises, the diagonal with it (GBR ely: S11 holds gas imports below the prior's, imported gas falls from 20% to 8% of the column and the diagonal rises from 52.2% to 56.1%). When it pulls a priced good in, the diagonal falls (the pre-round RUS msp diagonal was 30% against 57% in the prior because the gas row was strongly priced).
- An activity's output is its sales to others over (1 − diagonal coefficient at basic prices), eq. 17.22 and 17.28. With the ICIO diagonals near one half (RUS msp 56%, GBR ely 52%) any rise in demand from others is doubled. RUS msp output (176 bn against 130 in io_s12) is its held buyers, the S11 oil and gas targets at 3.3 and 4.2 times the ICIO columns (and the coal target), buying msp at their cost shares; its diagonal share falls slightly (57.2% to 54.3%). A fuel subsidy on the good (B15) raises every basic purchase by 1/(1 − ρ), the diagonal included, which is most of the ely moves in RUS, VNM and IRN (ρ 0.33, 0.31, 0.60; with `fuel_subsidies` off their ely outputs are 129, 49 and 13 bn against 280, 97 and 50).

`fit.Column` takes share groups: each group keeps its prior share of the column and its cells share it by GTAP's first-order conditions (one group, the default, is eq. 17.5 alone). The alternatives use them: `energy_activities_own_use_share_held_at_prior` holds the own good of coa, oil, gas, pet and ely at its prior share (an I-O analogue of GTAP's IEA energy use of the energy activities, eq. 17.8-17.9, for which S13 has no data; hard check `S13-Hownuse`), and `every_activity_own_use_share_held_at_prior` every activity's. Tested on the 2022 build (2026-10-25), the energy rule leaves 14 regions unfitted (BHR, BRN, CIV, CMR, COG, GAB, GHA, MOZ, NER, PER and four more, binding on their held gas, oil or pet rows), lowers GBR ely to 309 bn and IRN pet own use from 47.8 to 33.0 bn, but raises RUS ely to 317 bn and moves world ely output further from io_s12 (absolute gap 698 against 669 bn), so it is not the default. `S13-Rownuse` and `own_use_s13.csv` report every diagonal, prior against fit.

## What the fit holds

1. **Exports at basic prices, by commodity.**
   - Goods come from S10 with energy removed, energy from S11, and services and travel from S09.
   - VST comes from S11.
   - B06 travel is split into oil and gas by the host's household purchases of domestic oil and gas.
   - Travel on an energy good must fit within the domestic sales S11 leaves (output target less S11 exports). Any excess is dropped from both host and visitor and ledgered: 36.954 USD million in total.
2. **Imports at basic prices**, from the same sources.
3. **C, G and I.** These are S02 C, G and GFCF times one factor per region, so that C + G + I + VFOB + VST − VCIF = S02 GDP (decision 2).
   - The factor must be positive. This is a hard check.
   - The ±10% band is report-only (David, 2026-10-23).
4. **Tax rates.** Each cell keeps its net product-tax rate, domestic and imported alike, so revenue moves with the base (`tax_rates`, fix list A1, GTAP 12 ch.12 §12.3.3/§12.4.4 and ch.17A items 4-5; fix round w12, David 2026-10-24 "stick to GTAP").
   - `method.energy_ad_valorem` (GTAP 12 ch.12 §12.4.4: specific rates converted to ad valorem with GTAP's own final prices): S10 `energy_tax_s10.csv` gives, per region, NEERS use class and energy row, the net tax and its base. The specific rate per GJ is the tax over the base (TJ; the USA road-fuel barrels at the S11 pet toe per barrel; the electricity excise over the S11 domestic use of electricity); classes that share a column are combined with their bases as weights (§12.3.9). The ad valorem rate is that specific rate over the S11 domestic basic price per GJ (`domestic_price` / `mtoe_per_unit` / 41.868) of the commodity in the region, on every io_s12 column of the class (io_s12 oil and gas columns take the S10 B06 class; the gas rate is on the gas row; the electricity excise is on every ely buyer but the power sector's own ely purchases, the electricity-generation use class, whose rate is unknown, §12.3.3). A region without data takes the trade-weighted specific rates of its S10 proxies (member by member, where the member taxes the cell; §12.3.10; excise only: a member's S10 `fuel_sales_tax_musd`, the IND and BRA state fuel sales taxes, is taken out of its proxy rate) at its own price; a region with no proxy carries none (§12.3.3). A rate at or below −100% (a specific subsidy above the basic price, so no positive purchasers' price) is treated as unknown and set to zero (§12.3.3; `S13-Renergyrates`, flag `ENERGY-RATE-NOTE`). The table is `energy_tax_rates_s13.csv` (region, column, commodity, energy_rate, neer_subsidy_rate, basic_musd at io_s12, specific and price per GJ, source, fill); the fuel-subsidy overlap (B15) reads its `neer_subsidy_rate` and `basic_musd` in place of the former `tls_energy_s10.csv`.
   - `method.place_column_taxes` (default `held`): the energy rows carry their ad valorem rate on top of the column's general rate g, and every other row carries g. io_s12 has one TLS per column, which already contains the excise on the column's own energy, so the IO rate of the other purchases is g = (TLS − E) / B, E the energy part on the io_s12 flows and B all the column's basic purchases. Where that is below min(TLS / B, 0) (the excise exceeds the IO column tax), g = min(TLS / B, 0) and the column total moves instead of the rates (our choice; `energy_tax_placed_s13.csv`, `ENERGY-TAX-PLACED`, `S13-Rtaxmove`). Alternatives: `energy_rows_at_ad_valorem_rates_capped_at_column_tls_column_total_fixed` (the pre-w12 cap, not GTAP) and `energy_rows_at_ad_valorem_rates_plus_io_column_rate_on_every_row` (g = TLS / B, which counts the excise inside TLS twice).
   - **Non-energy rates by commodity** (QA round 2 P1, IMPROVEMENTS_LOG S13-2; choice `non_energy_rates`, tagged `not_in_gtap_text`; GTAP 12 ch.2 Table 2.3 holds rates by commodity, source and agent from the national valuation layers, ch.8). In every column with g > 0, the general part g B is placed on the commodities instead of one rate g (`method.product_tax_layers`, `method.pattern_rates`), from the S10 layers (`product_tax_pattern_s10`, `product_tax_layers_s10`, `product_tax_control_s10`): seed = the VAT weights, on households, government, investment and the exempt activities times c_V = GRS VAT / Σ(weight × basic) over them; plus on households' fbt the excise x = max(GRS T_5121 − S10 energy taxes, 0) / households' fbt purchases (alcohol and tobacco; a fill region nets the excise S13 holds on its energy rows). Each column is scaled to its g B; a government, investment or exempt-activity column at most as far as households (no agent pays more VAT on a good than households), the rest of its g B at one rate on all its purchases (product taxes the layers do not place; `capped_columns`, `uniform_musd`). With a Eurostat control the scaled seed is RASed on the non-energy rows towards the control shares, the columns re-scaled after each row step (200 iterations at most, 1e-10). The energy rows keep their energy rate and take the column's VAT part on top. Every column total, so C, G, I, GDP and revenue at the prior, is what `tax_rates` gives; a column with g ≤ 0 keeps one general rate. Report `S13-Rptpattern` and `product_tax_pattern_s13.csv` (c_V, excise, columns placed, capped columns, RAS iterations and gap by region). Alternative `one_general_rate_per_column` (the pre-round behaviour).
   - **GDP and total taxes** (ch.17A eq. 17.34, 17.39-17.40): C, G and I are held at purchasers' prices and trade is held, so GDP stays at the S02 target (`S13-Hgdp`) whatever the taxes. Where the net product taxes rise, the basic values of the purchases fall, and value added absorbs the change through zero profit (eq. 17.22): GDP from income = value added + taxes is still S02 GDP. Prototype on the pre-round io_s12 (w12 report): world net product taxes at the prior +115 bn (1.7%), largest in the top 20: CHN +18.7 bn, IND +12.8, KOR +8.6, GBR +8.4, NLD +7.5, DEU +5.9 (`S13-Rtaxmove`). `S13-Renergyrev` compares the energy taxes the held rates give on the io_s12 flows with the S10 source revenue.
   - `S13-Rextreme` (GTAP 12 ch.17B, report only): cells whose rate is at least +100% or at most −50%, and those on a fitted basic flow below 10 USD million (`energy_tax_extremes_s13.csv`). ch.17B adjusts firms' purchases to remove very large subsidies on extremely small flows but states no threshold, so nothing is trimmed.
   - The alternative `one_net_product_tax_power_per_column_dom_and_imp_held` is the earlier one rate per column (IMPROVEMENTS_LOG S13-2).
   - `S13-Hrates` checks every column's TLS against the sum of its fitted basic purchases times the cell rates.
   - **Product-tax money held by column** (round-3 final QA item 3, choice `product_tax_totals`, tagged `gtap`: GTAP 12 ch.8 Appendix A scales the expected tax revenue on the I-O flows to the actual revenue reported, and ch.15 sets income and factor taxes as revenue / GDP times GDP, as S13 `factor_tax_totals` does). With the rates held per cell, product-tax revenue rose in the fit (round 3 alone about 172 bn worldwide, mostly in the EU): the fit raises most columns' purchases (held trade and GDP) and moves them towards the cells the VAT and excise layers rate high; GDP is held, so value added fell by the same amount. `method.hold_product_taxes` runs after each fit pass: in every purchaser column (firms by activity, households, government, investment) the general part of the cell rates (each cell's rate less its energy-tax rate: the VAT and excise layers and Eurostat control of `non_energy_rates`, or the one general rate) is scaled by one factor so that its money on the fitted purchases equals its money on the io_s12 flows (`method.ptax_scale`, purchasers' values kept), and the fit is solved again with the new powers, warm-started (`fit.solve(start=...)`), until every column holds to 1e-9 (at most 200 passes). A column's general rates move at most `PTAX_SCALE_BOUND` = 2 either way (our choice: a column the fit shrinks many times, KWT fin or BHR its, would otherwise get rates above 100%); a column at the bound, or with no general base left, keeps the bound and the region's other columns carry what it cannot, in proportion to their io_s12 money (`method.ptax_plan`), so each region's general money is held exactly; where every column of a region is at its bound and the region is still off its total, one common factor beyond the bound goes on the columns whose money has the sign of the gap (a region short of tax does not raise its subsidies; 'region scale' in `product_tax_s13.csv`). The pattern of rates within a column is kept; the energy-tax rates (A1, ch.12 §12.4.4), the fuel-subsidy rate ρ (B15) and the PSE input rates are not scaled, so fuel subsidies are booked exactly as before and energy-tax revenue moves with the fitted energy purchases (the S11 values) as the held rates give. A representative or shut column has no target. `S13-Hptaxheld` (hard) checks every column's general part against its target (relative 1e-6), `S13-Hptaxregion` (hard) each region's general money against its io_s12 total; `S13-Rptaxprior` reports each region's TLS against the QA prior, io_s12 TLS with the A1 move less the booked fuel subsidies, the gap being the energy part on the fitted instead of the io_s12 energy flows; `product_tax_s13.csv` and `product_tax_regions_s13.csv` report them, and S14 checks its tables against the S13 TLS by region (`S14-Hptaxs13`). `cell_rates_held_revenue_moves_with_the_fit` is the round-3 rule.
   - **Representative-table regions' product-tax money from tax statistics** (round-3 final QA2 item 1, choice `product_tax_source`, tagged `gtap`: ch.9D takes the structure from the representative table, ch.8 Appendix A scales tax revenue to the reported revenue, ch.15 uses the IMF GFS). For every S05 donor region (`donor_weights.csv`) `s13_fit/ptax_source.py` sets the general part of the product-tax rates (one factor, the cell pattern kept) so that its money on the io_s12 flows equals IMF GFS G114 (taxes on goods and services, 2022, % of GDP; general government `S13` else the central-government series, from `data/imf_world`) times S02 GDP, less the positive energy excise on the io_s12 flows (A1, booked separately); a composite takes the GDP-weighted members' share when members with a value cover at least 90% of their GDP. `product_tax_totals` then holds that money through the fit. A region without such a value has its rates held (no money hold; flag `PTAX-RATES-HELD`). `product_tax_source_s13.csv` reports each donor region; `S13-Hptaxsource` (hard) checks the target and fitted money; `S13-Rnovat` reports the household general rate of KWT, QAT, IRQ and LBY against 2%.
   - **Bounded region fallback** (round-3 final QA2 item 4): the region factor of `ptax_plan` keeps every column's cumulative scale within [1/2, 2]; the money no column can carry is dropped and ledgered (`PTAX-DROPPED`), and `S13-Hptaxregion` checks each region against its target less that money.
   - **PSE input items, round-3 final QA2 item 6**: Indonesia's fertiliser subsidy (APBN 2022 allocation Rp 25.28 trillion) is a listed item on chm and the rest of its PSE input total goes on fin (KUR interest concessions; seeds and on-farm services inside). Choice `pse_iea_overlap` (`not_in_gtap_text`): the farm part of the IEA electricity subsidy (B15) is netted off the PSE electricity remainder on crp's ely row (India), reported as `netted_musd` in `pse_input_items_s13.csv`.
   - Export taxes (fix list A2): the held trade keeps VFOB above VXSB by the export tax, on goods from S10 and on coa, oil, gas and pet from S11, which holds the S10 export-tax rate on its re-priced routes. `S13-Hxtax` (hard, `checks.export_tax_held`) checks by region and commodity that XFOB − X is the S10 rate (`export_tax_s10.csv`) times the S11 VFOB on energy, the S10 wedge on other goods, and 0 on services and travel.
   - S10 farm support goes to crp as an output tax and an input tax (ch.11A; David's card, 2026-10-23).
   - **PSE input items** (fix round wG, QA round 2 P7, choice `pse_input_items`): GTAP 12 ch.11A (Figure 11.1) maps PSE B1 variable-input payments to input subsidies. The sub-items whose input is known are listed in `config/s13/pse_input_items_2022.csv` with a cited source (fertiliser -> chm, energy -> ely or pet, irrigation -> wat, credit -> fin); today India's 2022-23 fertiliser subsidy (Rs 2,54,798.93 crore, 32.4 bn at WDI 2022). `method.book_pse_input` puts each listed item F on its row's crp cells (domestic and imported pro rata), keeping the cell's purchasers' value (what the farmer pays): the basic value rises by F and the cell power falls by b / (b + F), its other product taxes keeping their amount, so the item's rate is F / (b + F) on the new basic value (the B15 convention). The remainder of the S10 PSE input total stays one rate on every crp purchase at its io_s12 basic value, except in a region listed in `config/s13/pse_input_remainder_2022.csv` (round-3 final QA item 9): there the remainder goes on the rows of the OECD B1 items whose amounts are not sourced, split by the crp column's basic purchases of those rows (one support rate on them), and is booked as an item (purchasers' value kept), so no flat rate is left on the other inputs (services included). India: fertiliser on chm and the 2022-23 MISS interest subvention (Rs 17,997.88 crore, Expenditure Budget 2024-25) on fin are listed, the rest goes on ely and wat (the OECD India B1 electricity and irrigation subsidies, OECD India PSE cookbook 2024). Indonesia: the whole B1 total on chm (the fertiliser subsidy programme, OECD Indonesia PSE cookbook 2024; no sub-item source, logged). Items above the PSE input total are scaled down; an item with no purchase on its row joins the remainder. `S13-Hpseitem` (hard) checks every listed item of a fitted region is booked in full on its row with a rate in (-1, 0); `pse_input_items_s13.csv` reports them. Other PSE countries (CHN, USA, TUR and the rest) keep the pro-rata rule until their PIV detail by input is sourced (S10-3); with the remainder rows `S13-Hpseitem` also checks that the region's whole PSE input total is booked on the item rows.
   - **Fossil-fuel consumption subsidies** (fix round B15, David's card 2026-10-24, choice `fuel_subsidies`; follows GTAP: Chepeliev, McDougall and van der Mensbrugghe 2018 §3.1-3.2, GTAP 12 ch.3 §3.2.4). The S11 subsidy of a region and good (coa, gas, pet, ely; every row of `fuel_subsidies_s11.csv`: the IEA price-gap rows and, since David's 2026-10-24 extension, the rows priced from source data or whose gap was not used, e.g. RUS and SAU gas and IRN, booked in the same way with no S13 change) is a negative purchase tax on that good's purchases by every activity, households and government, domestic and imported (tfd, tfm, tpd, tpm, tgd, tgm; investment is not in the paper's list, and government and investment energy is removed anyway). After every other change to the prior, each such cell keeps its purchasers' value and its tax power becomes τ(1 − ρ): the basic value rises and the tax falls by the same amount, the cell's other taxes keep their amount, and the subsidy rate −ρ is added on the new basic value. ρ is one rate for all buyers, so the subsidy falls on each in proportion to its purchases: ρ = subsidy over the held basic purchases (S11 output less exports, plus imports) for the S11 target goods, which the subsidised columns buy in full, so the fitted table books exactly the subsidy; for electricity (not a target) ρ = subsidy over the prior basic purchases after the booking, exact in the prior. **Electricity subsidy held in money** (round-3 final QA item 4, choice `electricity_subsidy_money`, tagged `gtap`: Chepeliev et al. 2018 §3.1-3.2 and GTAP 12 ch.3 §3.2.4 book the subsidy as the source money amount): left alone, the fit moved the electricity subsidy with the purchases, so a region could book well above its S11 amount and its factor income rose above GDP by more than its subsidies. `method.hold_product_taxes` now also resets ρ after each fit pass, ρ = S / (A + S) with A the fitted purchases at the cell powers without the subsidy (purchasers' values kept), and solves the fit again (warm start) until the fitted table books exactly S (1e-9); the S11 electricity price is not used by S13, so this hold is the mechanism. `prior_rate_moves_with_the_fit` is the earlier rule (`S13-Rsubsidy` reports fitted against prior). The column TLS falls by exactly the booked subsidy; the column rates in `tax_rates_s13.csv` stay the `io_s12` ones and the cells in `tax_cells_s13.csv.gz` carry the subsidy. Ledger flag `FUEL-SUBSIDY`. `S13-Hsubsidy` (hard): every subsidy to book is booked with 0 ≤ ρ < 1, exactly (held goods in the fitted table, electricity in the prior and, held in money, in the fitted table), and every column's fitted TLS equals its cells' other taxes less ρ × basic purchases.
   - **No double counting with NEERS** (choice `fuel_subsidy_neer_overlap`, our choice): S10's energy rates are net of the OECD NEERS fossil-fuel and electricity subsidies (s10 `energy_subsidies`), which sit inside the ICIO product-tax total. The IEA price gap measures the whole gap between the reference and end-user prices, whatever the instrument, so S13 keeps the S10 net rate on the row and books the S11 subsidy less the NEERS subsidy S10 placed on that region's row (sum of `neer_subsidy_rate` × `basic_musd` in `tls_energy_s10.csv`), at least zero. The row's total subsidy is then the IEA value. `S13-Hsubneer` (hard) fails while `tls_energy_s10.csv` has no `neer_subsidy_rate` column and an IEA-gap row has S10 NEERS or pool-fill rates. The alternative `iea_subsidy_in_full_overlap_reported` books the S11 subsidy in full and only reports.
   - The S12 output tax (row `OTAX`, D29 other taxes on production; fix round A3, GTAP 12 ch.15) is held as a fixed rate on its activity: the output power is (OUT − PSE output support) / (OUT − OTAX), so `PTAX` is the tax less any support, and `S13-Hrates` checks it. `S13-Rsupport` books the support part of crp's `PTAX` at its base share.
5. **Energy output.** coa, oil, gas and pet take the S11 output values where target = yes. A target of 0 shuts the row and the column.
6. **Factor composition.** VA is split by each activity's S12 EVFP shares, and the factor taxes move with EVFP (eq. 17.27).
   - An activity with no S12 VA takes the S12 world composition of its sector, plus the region's average factor tax rates.

## The prior

The prior is `io_s12` at purchasers' prices, changed as follows. Every change is a ledger row.

**Removed or merged:**
- The stock-change and G-revision gap columns are removed (ch.17A item 3, E40). The fit absorbs them.
- `dpabr` joins households (ch.10B p.3).
- Negative purchases are set to zero (ch.8 §8.3).

**Held:** a negative-VA cell without exports or a target (none in the 2022 build; the three air cells take the representative column, see below).

**Shut activities:**
- An activity is shut when its S11 target is 0, or when it has no output, no exports and no target.
- A shut activity has no domestic sales and no purchases.
- Where a target equals exports, the domestic row is removed (COD, GAB, GUY and TCD oil).

**Activities with no prior column:** an activity with exports or a target but no prior column takes the S03 representative-table column (ch.9D). The same holds for an activity whose prior column has no positive value added (`prior_without_va`, David's S14 card, 2026-10-24): BHR, CYP and KWT air (negative VA) and TUN gas (zero VA). Their factors take the S12 world composition of the sector, and their product-tax rate is the representative column's (the io_s12 TLS is dropped and ledgered, `REP-COLUMN-TLS-DROPPED`). S14 found them: the Julia model needs EVFP > 0 wherever there is output.

**Energy use by government and investment** is removed (ch.17A footnote 4). Their totals are held, so the fit moves the value to their other purchases.

**Energy-use caps** (fix round A10, choice `energy_use_caps`, our choice in place of GTAP's IEA use-by-industry constraints µiea; `off` skips them), applied after the government and investment removal and before the smears, from S11 `energy_use_caps_s11.csv`:
- Refinery crude: where S11 measured the crude intake, the oil-row cells in the pet column (domestic and imported) are capped at the intake value at the S11 domestic and import crude prices, as a share of the held oil totals (domestic sales = target less exports; imports). The excess goes pro rata to the other live buyers outside government and investment, else to oil own use (`REFINERY-CRUDE-CAP`, `REFINERY-CRUDE-CAP-OWN-USE`).
- Gas own use: the gas-row cells in the gas column are capped at the UNSD 2022 own-use share of gas supply, the excess going to the other buyers (`GAS-OWN-USE-CAP`).

The fit can move the capped cells; `S13-Rcapfit` reports where the fitted cell ends above its cap.

**Own-use caps** (fix round wG, QA round 2 P5, choice `own_use_cap`; GTAP 12 ch.12 energy balance and ch.17A eq. 17.8-17.9, `off` skips them), after the A10 caps and after the smears (the 1/32 energy smear of an import row would otherwise put the world structure back on the diagonal; for crude that is the B06 diagonal), from S11 `own_use_s11.csv`: the own-use cell of coa, oil, gas and ely (domestic plus imported own good at agents' prices) holds at most the UNSD 2022 own use + losses share of the activity's prior column (purchases plus value added). The fit keeps column shares (eq. 17.5) and cost equals output (eq. 17.22), so this caps the share of output once the fit scales the column to its S11 target; the excess leaves the column, so the cap share s is of the lower column. For a held good the excess goes pro rata to the row's other buyers (activities and households), domestic to domestic and imported to imported, so the held row totals stay (`OWN-USE-CAP`); a row with no other buyer is not capped and is reported. For ely, not an S11 target, the domestic excess is netted out of row and column alike (`OWN-USE-CAP-NETTED`): it is intra-industry resale inside the ICIO D35 output (which also holds gas distribution, fix list B7), the imported excess goes to the other buyers of the held import row. The fit then moves the cell like any cost share (`own_use_share` stays `cross_entropy_free`). **Second pass:** where the free fit takes a capped good's diagonal more than 1 point above its UNSD share, the region is refitted with that diagonal's share of the column held at its capped prior share (a `fit.Column` share group, the I-O analogue of GTAP's IEA energy use of the energy activities, eq. 17.8-17.9; `S13-Hownuse` hard checks the held shares); if the refit does not converge, or adds a factor cell with negative EVOS (17B p.3 signs: with `factor_tax_totals` holding the S12 factor taxes as money, a column the refit shrinks can leave a factor's tax above its payment), the free fit stays and is reported (`S13-Rownhold`, `own_use_held_s13.csv` with `refit_note`). **Sign fallback:** where the capped fit (after the second pass) leaves a factor cell with negative EVOS and the fit of the uncapped prior has fewer such cells, the region's caps are dropped and the uncapped fit stays (`S13-Rowndrop`, `own_use_dropped_s13.csv`); the signs of 17B p.3 come before the own-use cap. `S13-Rowncap` lists the capped cells, `S13-Rownhold` the refits and `S13-Rowncapfit` the fitted diagonals still above the cap by more than 1 point and 0.1 bn; `own_use_caps_s13.csv` has each capped cell.

**Smears** (the ch.12 §12.4.1 analogue, 1/32):
- Held imports with no buyer take 1/32 of domestic purchases, or go to households when there are none.
- Energy goods with required domestic sales and no buyer except their own industry take 1/32 of imported purchases.
- Each energy good whose domestic sales or imports S11 holds has its prior row set to 31/32 of its own cells plus 1/32 of its total on that good's world I-O structure over the live activities and households; the row total is unchanged. GTAP applies these weights to its IEA volume data; S13 has no IEA volume data, so they are applied to the I-O prior instead. Without it seven regions cannot place the S11 targets. `S13-Rsmearfill` reports the mass this creates.
- Why the smears grew in the fix round (`smears_s13` 66.5 → 93.5 bn, `Rsmearfill` 24 → 86 bn; QA LOW): the energy smear moves 1/32 of each row's distance from the world structure, so it scales with the row totals and with how far the row is from that structure, not with the S11 balance; w16 changes totals, not structure, so the smears could not fall. The rise is mostly crude: fix-round A8 gave the io_s12 oil rows only the refinery and the UNSD direct users, while the crude smear structure is the B06 row (w15), so about 1/32 of each oil row moves to the B06 buyers (dom_oil 3.6 → 9.9 bn, imp_oil 6.8 → 13.9; USA dom_oil +2.9, CHN +1.5). New no-buyer smears follow new S11 trade (CHE imp_oil 2.4 bn and NER dom_oil 0.6 bn to households). The fit then scales the smeared crude cells with the oil row's price: crude cells that are zero in io_s12 hold 55 bn after the fit (17 bn before the round), 40 bn of it in ely columns and 31 bn in SAU.

## Energy import shares

After the fit (fix round B1, choice `energy_import_shares`; GTAP's import proportionality), each agent's purchases of coa, oil, gas, pet and ely are split between domestic and imported at the region's purchase-wide import share of that good. Each agent's total basic purchase and each row's domestic and imported totals are unchanged, so the held targets, trade and column costs stay as fitted (`ENERGY-IMPORT-SHARE` ledger rows, `S13-Hesplit`). `icio_agent_split` keeps the fitted ICIO split. Other goods keep the ICIO split. For energy goods `Hzeros` counts a cell as a structural zero only where both its domestic and its imported prior are zero, since proportionality moves value between the two.

## Checks and screens

**Hard checks:**
- Config, upstream G0, inputs IN1 and IN2.
- Factor positive (`S13-Hfactor`) and every region fitted (`Hfit`).
- Zero profit (`Hcost`), market clearing (`Hmarket`), imports (`Himports`).
- Held trade (`Htrade`), C, G and I (`Hfd`), GDP from expenditure and from income (`Hgdp`).
- Energy targets (`Henergy`), tax and support rates, including each activity's output-support rate (`Hrates`), factor shares (`Hshares`).
- Signs (`Hsign`), structural zeros (`Hzeros`), GTAP columns only (`Hcolumns`), factors against io (`Hfactors`).
- Energy goods at one import share per region and good (`Hesplit`).
- Fuel subsidies booked exactly, column TLS moved by exactly the booked subsidy (`Hsubsidy`), and net of the NEERS subsidies on the row (`Hsubneer`).
- Held own-use shares at their prior share (`Hownuse`), when `own_use_share` is not the default or the own-use second pass held a diagonal.
- PSE input items booked on their rows (`Hpseitem`, fix round wG; the whole input total on the item rows where the remainder rows are listed, round-3 QA item 9).
- Factor income less GDP at most the booked product subsidies in every region: the B15 fuel subsidies in the fitted table, the PSE input support and the output subsidies (negative PTAX), within max(1e-6 of GDP, 1 USD m) (`Hfacgdp`; round-3 final QA item 4, `electricity_subsidy_money`).
- The general part of every column's product tax held in money (`Hptaxheld`) and each region's general money at its io_s12 total (`Hptaxregion`; round-3 QA item 3, `product_tax_totals`).
- No private file, the secret scan, and the screens.

Each check is a pure function with a mutation test.

**Report-only checks:**
- The ±10% band (`S13-Rband`).
- The ICIO gate (`Ricio`): total absolute change in intermediate cells over `io_s12` intermediate use, split into column scale and cost shares.
- Moves over 25% on cells of 100 USD million or more (`Rmoves`).
- Electricity fuel subsidies at fitted values against the prior (`Rsubsidy`).
- Support booked (`Rsupport`).
- Net product tax by region against the round-3 QA prior, io_s12 TLS with the A1 move less the booked fuel subsidies (`Rptaxprior`; the gap is the energy part).
- World trade totals (`Rworld`).
- Non-ICIO GDP (`Rrow`; the ICIO ROW block is not imposed).
- Total information (`Rinfo`).
- The `io_s12` imbalance the fit absorbs (`Rio12gap`).
- Purchase cells the smears create (`Rsmearfill`).
- Own-use (diagonal) cells of 1 bn or more whose share of the column moved by more than 5 points (`Rownuse`, `own_use_s13.csv`).
- The energy-use caps applied in the prior (`Rcaps`) and fitted cells above their cap (`Rcapfit`).
- The own-use caps applied in the prior (`Rowncap`) and fitted diagonals above their cap (`Rowncapfit`).

**Screens** (SCREENS.md):
1. C + G + I against S02 absorption.
2. Activity output against `io_s12`. More than 3× or under a third, on cells of 0.1 bn or more, is a hit. S11 targets, representative columns, and moves at least half explained by the held exports count as `gtap_rule`.
3. Year jumps: none, because S13 picks no source year.
4. Stale years: none, for the same reason.
5. Identities.
6. Coverage of representative columns and smears.
7. Moves against `S13_PREV_OUTPUT`.
8. The ICIO gate.

Screens 1 and 2 need a row in `config/s13/screen_explanations.csv` when a hit is material: 0.1 bn, or 1% of the region's GDP.

## Outputs

All outputs go to `dataset/stages/S13_fit/output/`:
- `io_s13.csv.gz`:
  - rows: `dom_*`, `imp_*`, TLS, PSE_input, the eight `EVFP_*`, PTAX, OUT;
  - columns: the sectors, p, g, i, X, VST, M, OUT.
- `factors_s13.csv.gz`: the S12 factor taxes scaled by each cell's EVFP ratio, then (choice `factor_tax_totals`, GTAP 12 ch.15: taxes are revenue / GDP × GDP, a money amount) ftax, itax and fbep scaled by region and factor to S12's totals.
- `trade_s13.csv.gz`
- `macro_s13.csv`
- `fit_report_s13.csv`: entropy, iterations and residual by region.
- `fit_moves_s13.csv` and `fit_top_moves_s13.csv`
- `icio_gate_s13.csv`
- `smears_s13.csv`
- `activity_status_s13.csv`
- `tax_rates_s13.csv` (column rates at the prior, for reporting)
- `tax_cells_s13.csv.gz`: region, column, commodity, tls_rate, pse_rate for every cell whose power is not 1 (S14 must read these; fix list A1)
- `energy_tax_placed_s13.csv`: columns whose energy part was capped (alternative), whose general rate was floored, and whose product-tax total moved at the prior
- `product_tax_pattern_s13.csv`: by region, the VAT level c_V, the alcohol and tobacco excise placed and its rate, the energy excise netted, the columns placed by commodity, the columns capped at the household scale and their uniform remainder, and the RAS iterations and gap (non_energy_rates, QA round 2 P1)
- `energy_tax_rates_s13.csv`: the ad valorem energy-tax rate of every taxed energy cell (fix list A1, GTAP 12 ch.12 §12.4.4)
- `energy_tax_extremes_s13.csv`: extreme net rates and small flows (ch.17B report)
- `fuel_subsidies_s13.csv` (fix round B15): region, good, S11 subsidy, NEERS subsidy on the row, subsidy booked, ρ, its basis, status, booked in the prior and in the fitted table
- `fuel_subsidy_columns_s13.csv`: the fitted subsidy by region, good and column (rate −ρ, basic purchases, subsidy)
- `support_s13.csv`
- `own_use_caps_s13.csv` (fix round wG): each prior diagonal capped at the UNSD own-use share, with its prior value and cap
- `own_use_held_s13.csv` (fix round wG): the regions and goods refitted with the diagonal share held, and whether the refit was kept (`refit_note`)
- `own_use_dropped_s13.csv` (fix round wG): regions whose capped fit left a negative EVOS, the cells with and without the caps, and whether the caps were dropped
- `pse_input_items_s13.csv` (fix round wG): each listed PSE B1 item, booked value, cell rate, basic before and after, and its part (listed, remainder, or listed+remainder; round-3 QA item 9)
- `product_tax_s13.csv` (round-3 QA item 3): by region and column, the net product tax at the prior (io_s12 TLS or the A1 total), the general part's target (io_s12) and effective target (with its share of what the region's bound columns cannot carry), its money in the free fit and after the hold, the scale on its general rates, the fitted TLS, the passes and, for a column at the bound, why
- `product_tax_regions_s13.csv` (round-3 QA item 3): by region, the QA prior (io_s12 TLS with the A1 move less the booked fuel subsidies), the fitted TLS and the gap, the general part (io_s12 and fitted), the energy part on the io_s12 and the fitted flows, and the fuel subsidies
- `factor_income_gdp_s13.csv` (round-3 final QA item 4): by region, factor income, GDP, their ratio and difference, and the booked product subsidies (fuel, PSE input, output) that `S13-Hfacgdp` compares it with
- `own_use_s13.csv` (fix round wC): region, sector, held, own-use share of the column at agents' prices in the prior and the fit, and the column and own-use values
- `travel_dropped_s13.csv`

`io_s13` and `factors_s13` carry the S10 tariff wedge and are not for publication.

## Running

- Run: `cd dataset/build && python3 s13_fit.py`. It takes about two minutes.
- Float outputs are rounded to 1e-6 USD million. The hard checks run on the unrounded table, so a rate or share recomputed from the published file on a column of under 1 USD million can miss the checks' 1e-8 tolerance by rounding alone.
- `GTAP_STAGES_DIR=<dir>` runs against a scratch copy of the upstream stages.
- `S13_PREV_OUTPUT=<dir>` turns on screen 7.
- Tests: `python3 -m unittest tests.test_s13_checks`.

## Round 3, final QA 2 items 2, 3 and 5 (energy parts)

- **Subsidy users (item 2; choice `fuel_subsidy_users`; Chepeliev et al. 2018 §3, GTAP 12 ch.12).** The S11 IEA consumption subsidy is booked on final consumption and non-energy users only: the coa, oil, gas, pet and ely activity columns (own use, transformation in power and refining, energy-industry own use) carry no IEA subsidy rate (`method.subsidy_columns`, `SUBSIDY_EXCLUDED_ACTIVITIES`). The money stays the S11 amount by region and good, booked on the other buyers and held through the fit by the rate reset after each pass (`money_held`, as `electricity_subsidy_money`); `S13-Hsubsidy` checks it. Each good's mask is kept with its row (`fuel_subsidy_columns_s13.csv`).
- **Own-use cap at basic values (item 2; choice `own_use_cap_valuation`).** The prior cap (`energy.cap_own_use`) and the second-pass overshoot test measure the diagonal's basic value over the column (output); `own_use_s13.csv` adds `fitted_own_basic_musd` and `fitted_share_basic`; `S13-Rowncapfit` (basic, io_s13) reports what is left.
- **Power fuel cells (item 3; choice `power_fuel_cells`; GTAP 12 ch.12 §12.4, ch.17A).** In every region whose power column burns listed crude (crude at least 5% of its listed crude, gas and pet value in S11 `crude_cell_split_s11.csv`), the ely column's crude, gas and pet cells are held at those S11 basic values, domestic and imported (`fit.Column fixed_basic`: held cells leave the cross-entropy, enter their rows as constants, and their purchasers' value follows the cell's tax power). A held row keeps at least 10% for its other buyers. `S13-Hpowercell` (hard) checks the fitted cells (dom + imp, basic, after import proportionality); `power_cells_s13.csv`.
- **Crude users (item 5; choice `crude_smear_users`).** io_s11 already gives crude only to refining, the listed direct users and exports (S11-Hcrude). The crude smear structure keeps the world B06 row on the crude users (pet, the oil industry, the listed columns of `config/s11/crude_direct_users.csv`) and gives every other buyer's weight to refining; a crude row with no prior buyer goes to refining (else, for imports, the oil column) instead of households.
