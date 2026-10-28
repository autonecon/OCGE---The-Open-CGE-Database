#!/usr/bin/env python3
"""S13 FIT (GTAP 12 ch.17A; PLAN §3(i)).

Each region's table is fitted to the held targets by GTAP's FIT objective (eq. 17.1 + 17.2 with unit
weights, the column-share cross-entropy weighted by column totals); the method is in the s13_fit package.

1. Held trade: exports at basic prices (goods S10, energy S11, services and travel S09) and VST (S11);
   imports at basic prices (same sources). B06 travel is split into oil and gas; travel on an energy good is
   kept within the domestic sales S11 leaves (output target less S11 exports).
2. C, G and I: S02 values times one factor per region so that GDP = S02 GDP with trade fixed (decision 2).
3. Tax rates (ch.17A items 4-5, held): the energy rows carry GTAP ad valorem energy-tax rates, the S10 specific
   rates over the S11 basic prices (ch.12 §12.4.4; fix list A1), on top of the column's general rate, the io_s12
   net product-tax rate of the other purchases, placed by commodity with the S10 VAT and excise layers and the
   Eurostat product control, the column total unchanged (non_energy_rates, QA round 2 P1; ch.2 Table 2.3, ch.8);
   and the S10 farm support on crp as an output tax and an input tax (ch.11A; David's card 2026-10-23).
4. Energy: the S11 coal, oil, gas and petroleum output values with target = yes.
5. The prior: io_s12 with stock change and the G-revision gap removed, dpabr in households, negative
   purchases cleaned, representative-table columns for activities with exports or a target and no prior
   column (ch.9D), shut rows and columns where output is zero, and the ch.12 §12.4.1 smears.
6. Value added is split by the S12 factor shares; factor taxes move with EVFP (factors_s13).

Any region that does not reach every held row stops the stamp and is named (no plugs, PLAN §3(i)).
Choices come from config/s13/s13_choices.csv (s13_fit/config.py).
"""
import gzip
import os
import subprocess
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.stagekit import Stage, ROOT, BUILD, STAGES, DATA  # noqa: E402
from lib.private_files import private_paths  # noqa: E402
from s13_fit import config as C  # noqa: E402
from s13_fit import method as M  # noqa: E402
from s13_fit import checks as K  # noqa: E402
from s13_fit import energy as EN  # noqa: E402
from s13_fit import ptax_source as PS  # noqa: E402
from s13_fit.method import FD, FACTORS, ENERGY_TRADE  # noqa: E402
from s12_factors.checks import secret_scan  # noqa: E402
import screens.s13_suite as SCR  # noqa: E402

UP = {
    'S01': STAGES + '/S01_sets_registry',
    'S02': STAGES + '/S02_macro',
    'S03': STAGES + '/S03_io_cleaning',
    'S05': STAGES + '/S05_composite',
    'S09': STAGES + '/S09_services',
    'S10': STAGES + '/S10_tariffs_taxes',
    'S11': STAGES + '/S11_energy',
    'S12': STAGES + '/S12_factors',
}
CITE = {
    'dpabr_to_households': 'GTAP 12 ch.10B p.3',
    'negative_cells': 'GTAP 12 ch.8 §8.3 p.3',
    'negative_va': 'S12 negative_va; S13 config negative_va',
    'zero_output_no_domestic_sales': 'GTAP 12 ch.17A (no output, no sales)',
    'target_all_exported_no_domestic_sales': 'GTAP 12 ch.12 §12.4.1 targets; S13 config all_exported_energy',
    'zero_output_column_prior': 'GTAP 12 ch.9D (representative table)',
    'zero_imports': 'GTAP 12 ch.17A item 2 (imports held)',
    'gov_inv_energy_removed': 'GTAP 12 ch.17A footnote 4',
    'io12_column_imbalance': 'GTAP 12 ch.17A eq. 17.22 (output equals cost); S12 io_s12 gap',
    'io12_row_imbalance': 'GTAP 12 ch.17A eq. 17.28 (output equals sales); S12 io_s12 gap',
    'rep_column_tls_in_va': 'GTAP 12 ch.9D (representative table); S13 config zero_output_column',
    'shut_column': 'S13 config shut_activity',
    'prior_without_va': 'GTAP 12 ch.9D (representative table); S13 config prior_without_va (David, S14 card 2026-10-24)',
    'fuel_subsidies': 'Chepeliev, McDougall and van der Mensbrugghe (2018) §3.1-3.2; GTAP 12 ch.3 §3.2.4 (fix-round B15, David 2026-10-24)',
    'product_tax_source': 'GTAP 12 ch.8 Appendix A (tax revenue scaled to the reported revenue), ch.9D (representative table for structure), ch.15 (IMF GFS)',
}
MOVE_REL, MOVE_MUSD, TOP_MOVES = 0.25, 100.0, 20
ICIO_GATE = 0.02
BAND = 0.10



H90FIT_ABS_TOL = 1e-4   # beta v5 build: S13-H90fit tolerance on the ratio (fit rounding)

def bn(x):
    return x / 1000.0


def main():
    choices = C.load_choices()
    V = {k: r['value'] for k, r in choices.items()}
    # analysis runs only (Fable QA A-02 hold ablation, tools/s13_hold_ablation.py): S13_ANALYSIS_CHOICES overrides choice
    # values (choice=value,...), S13_ANALYSIS_REGIONS fits a subset; either one marks the run dirty, so it never stamps
    an_choices = dict(kv.split('=', 1) for kv in os.environ.get('S13_ANALYSIS_CHOICES', '').split(',') if kv)
    an_regions = [x for x in os.environ.get('S13_ANALYSIS_REGIONS', '').split(',') if x]
    for k, v in an_choices.items():
        if k not in C.CHOICES or v not in C.CHOICES[k]:
            raise SystemExit(f'S13_ANALYSIS_CHOICES: {k}={v} is not an implemented choice value')
        V[k] = v
    S = Stage('S13', 'fit')
    if an_choices or an_regions:
        S.dirty = True
        S.log(f'ANALYSIS RUN (no STAMP): choices {an_choices or "-"}; regions {an_regions or "all"}')
    I = S.inp
    S.check('S13-Hconfig', f'config/s13/s13_choices.csv has the {len(C.CHOICES)} choices this code implements, each with decided_by and decided_at',
            'hard', len(choices), len(C.CHOICES), len(choices) == len(C.CHOICES), 's13_choices',
            'Departures and choices not in the GTAP text: ' + ', '.join(k for k, r in choices.items() if r['gtap_status'] in ('departure_logged', 'not_in_gtap_text')))
    for k in UP.values():
        S.upstream(k)
    I(C.CHOICES_PATH, 'S13 choices')

    # ------------------------------------------------------------- inputs
    regions = pd.read_csv(I(UP['S01'] + '/output/regions.csv', 'S01 regions'))
    sectors = pd.read_csv(I(UP['S01'] + '/output/sectors.csv', 'S01 sectors'))['sector'].tolist()
    macro = pd.read_csv(I(UP['S02'] + '/output/macro_regions.csv', 'S02 GDP, C, G, GFCF'))
    rep = pd.read_csv(I(UP['S03'] + '/output/representative_table.csv', 'S03 representative table (ch.9D)'))
    svc = pd.read_csv(I(UP['S09'] + '/output/vxsb_services_s09.csv.gz', 'S09 services trade'))
    trv = pd.read_csv(I(UP['S09'] + '/output/travel_s09.csv.gz', 'S09 travel goods'))
    gx = pd.read_csv(I(UP['S10'] + '/output/vfob_s10.csv.gz', 'S10 goods exports VXSB/VFOB'))
    gm = pd.read_csv(I(UP['S10'] + '/output/vmsb_s10.csv.gz', 'S10 goods imports VCIF/VMSB'))
    sup = pd.read_csv(I(UP['S10'] + '/output/support_s10.csv', 'S10 farm support (PSE)'))
    spec10 = None
    if V['tax_rates'].startswith('energy_rows'):
        spec10 = pd.read_csv(I(UP['S10'] + '/output/energy_tax_s10.csv', 'S10 specific energy-tax rates by use class (fix list A1; GTAP 12 ch.12 §12.4.4)'),
                             keep_default_na=False, na_values=[''])
    pt_layers = {}
    if V['non_energy_rates'] != 'one_general_rate_per_column':
        # QA round 2 P1: the commodity structure of the non-energy product taxes (S10 product_tax_pattern)
        pt_layers = M.product_tax_layers(
            pd.read_csv(I(UP['S10'] + '/output/product_tax_pattern_s10.csv', 'S10 VAT weights by agent and commodity (non_energy_rates)')),
            pd.read_csv(I(UP['S10'] + '/output/product_tax_layers_s10.csv', 'S10 GRS VAT and excise revenue (non_energy_rates)')),
            pd.read_csv(I(UP['S10'] + '/output/product_tax_control_s10.csv', 'S10 Eurostat product control (non_energy_rates)')),
            sectors)
    ex = pd.read_csv(I(UP['S11'] + '/output/vfob_energy_s11.csv.gz', 'S11 energy exports'))
    xt10 = pd.read_csv(I(UP['S10'] + '/output/export_tax_s10.csv', 'S10 export-tax rates (fix list A2: S13-Hxtax)'))
    em = pd.read_csv(I(UP['S11'] + '/output/vmsb_energy_s11.csv.gz', 'S11 energy imports'))
    vst = pd.read_csv(I(UP['S11'] + '/output/vst_s11.csv', 'S11 VST'))
    evs = pd.read_csv(I(UP['S11'] + '/output/energy_values_s11.csv', 'S11 energy output values (targets)'))
    ecaps = pd.read_csv(I(UP['S11'] + '/output/energy_use_caps_s11.csv', 'S11 energy-balance caps: refinery crude intake, gas own use (fix-round A10)'))
    capd = {x['region']: x for x in ecaps.to_dict('records')} if V['energy_use_caps'] != 'off' else {}
    # fix round wG (QA round 2 P5): S11 UNSD own use + losses shares of output, the cap on the energy diagonals
    ou11 = pd.read_csv(I(UP['S11'] + '/output/own_use_s11.csv', 'S11 own use + losses shares of output (fix round wG)'))
    own_capd = {}
    if V['own_use_cap'] != 'off':
        for x in ou11.dropna(subset=['own_use_share']).itertuples():
            if x.commodity == 'pet' and V['own_use_cap'] == C.OWN_USE_CAP_V3:
                continue                # beta v3 rule: the refinery diagonal is not capped
            own_capd.setdefault(x.region, {})[x.commodity] = float(x.own_use_share)
    # beta v5 N1 (s13 choice own_use_cap_listed; our rule, not in the GTAP text): listed non-energy diagonals (NGA fbt)
    own_listed = C.read_own_use_listed(I(C.OWN_USE_LISTED_PATH, 'listed non-energy own-use caps (beta v5 N1)')) if V['own_use_cap_listed'] == C.OWN_USE_LISTED else {}
    for reg_, d_ in own_listed.items():
        own_capd.setdefault(reg_, {}).update(d_)
    # fix round wG (QA round 2 P7): PSE B1 sub-items on the input they pay for
    pse_items = C.read_pse_items() if V['pse_input_items'] != 'off' else {}
    I(C.CONFIG_DIR + '/pse_input_items_2022.csv', 'PSE B1 variable-input items by input (fix round wG)')
    # fix-round B15: the S11 IEA consumption subsidies (GTAP's booking; David's card 2026-10-24): the IEA price-gap rows and,
    # since David's 2026-10-24 extension, every other row with an IEA subsidy (fuel_subsidies_s11.csv source_rule)
    fuel_on = V['fuel_subsidies'] != 'off'
    fsub = pd.read_csv(I(UP['S11'] + '/output/fuel_subsidies_s11.csv', 'S11 fuel consumption subsidies (fix-round B15)')) if fuel_on else None
    # round 3 final QA 2 items 3 and 5: the S11 power-column fuel values and the energy balance's crude users
    pcs = pd.read_csv(I(UP['S11'] + '/output/crude_cell_split_s11.csv', 'S11 listed crude users: UNSD crude, gas and pet burn at S11 prices (power_fuel_cells)'))
    crude_cfg = pd.read_csv(I(BUILD + '/config/s11/crude_direct_users.csv', 'S11 listed crude users (crude_smear_users)'))
    crude_cols = None
    if V['crude_smear_users'] == M.CRUDE_SMEAR_USERS:
        # households keep their small smear weight: the model's CDE private demand needs a positive purchase of every
        # good in every region (a zero qpa/ppa is 0/0 at calibration, S15-Hjulia)
        crude_cols = {('oil' if c == 'B06' else c) for c in crude_cfg['io_column']} | {M.CRUDE_REFINERY, 'oil', 'p'}
    io = pd.read_csv(I(UP['S12'] + '/output/io_s12.csv.gz', 'io_s12'))
    # beta v4 P1 floor only (s11 choice ely_output_value, David 2026-10-26; our rule, not in the GTAP text): the S11 ely value
    # only raises the prior ely column; the donor-scaled regions keep the S11 value (ely_target_rule = value)
    ely_lb = V['ely_floor_mode'] == C.ELY_FLOOR_LOWER
    # beta v4 H2 (s13 choice ely_hold_net_own_use, default off; our rule, not in the GTAP text): the hold takes the prior net
    # of the domestic own use the cap nets out, and in the IEA electricity-subsidy regions at least the S11 value
    ely_h2 = V['ely_hold_net_own_use'] == C.ELY_HOLD_NET and not ely_lb
    ely_net = M.ely_netted_own_use(io, own_capd) if ely_h2 else {}
    ely_smin = (set(fsub.loc[(fsub['commodity'] == 'ely') & (fsub['subsidy_musd'] > 0), 'region'])
                if ely_h2 and fsub is not None else set())
    # beta v5.5 (s13 choice ely_subsidy_region_hold; David 2026-10-27 22:14 UTC; our rule, not in the GTAP text): these regions
    # keep the tariff-level hold, and their booked ely subsidy rate is capped (method.ELY_SUB_RHO_MAX) to fit inside it
    ely_sub_cap = set()
    if V['ely_subsidy_region_hold'] == C.ELY_SUB_TARIFF:
        ely_sub_cap, ely_smin = ely_smin, set()
    # beta v4 H2 add-on (s13 choice ely_hold_cap, default off): the held value at most the S11 value marked up by m
    ely_cap_m = M.ELY_HOLD_CAP.get(V['ely_hold_cap']) if not ely_lb else None
    if ely_lb and (V['ely_hold_net_own_use'] != 'off' or V['ely_hold_cap'] != 'off' or V['ely_output_anchor'] != 'off'):
        # review of PR #105: H2 and the cap act on the hold only; with the lower-bound floor they would be silently inert
        raise SystemExit('s13 ely_floor_mode is the lower bound: set ely_hold_net_own_use, ely_hold_cap and ely_output_anchor to off (they act on the hold only)')
    # beta v4 anchor B (s13 choice ely_output_anchor, default off; GTAP 12 ch.12 §12.3.6-12.4.3): in the listed regions the ely
    # hold is the measured value, use-class prices x S11 volumes plus any 2022 price-shield payment to suppliers
    ely_anc_on = V['ely_output_anchor'] == C.ELY_ANCHOR and not ely_lb
    I(C.CONFIG_DIR + '/ely_output_anchor_2022.csv', 'ely 2022 household share and use-class prices by region (anchor B)')
    I(C.CONFIG_DIR + '/ely_price_shield_2022.csv', 'ely 2022 price-shield payments to suppliers (anchor B)')
    anc_tab = C.read_ely_anchor() if ely_anc_on else {}
    ely_shield = C.read_ely_shield() if ely_anc_on else {}
    ely_anchor = M.ely_anchor_values(evs, anc_tab, ely_shield)
    ely_sub_cap -= set(ely_anchor)          # beta v5.5: a measured-price anchor region keeps its v5 hold and subsidy
    evs, ely_fl = M.ely_floor(evs, io, lower_bound=ely_lb, net_own=ely_net, s11_min=ely_smin, cap_m=ely_cap_m, anchor=ely_anchor)
    ely_free = {reg_: f_ for reg_, v_, p_, f_, h_ in ely_fl if not np.isfinite(h_)}     # fitted free, held at f_ if below
    ely_second = []
    for reg_, v_, p_, f_, h_ in ely_fl:
        if np.isfinite(h_) and h_ != v_:
            S.adjust(reg_, 'ely output target (S11 value, USD million)', v_, h_, 'ely_output_value floor',
                     'beta v4 P1 floor: max(prior ely column, 90 percent rule floor or S11 value); our rule, not in the GTAP text'
                     + ('; H2: prior less the netted own use, at least the S11 value in IEA ely-subsidy regions' if ely_h2 else ''), 'ELY-FLOOR')
    raised = sorted((x for x in ely_fl if np.isfinite(x[4]) and x[4] > x[2] + 1e-9), key=lambda x: -(x[4] - x[2]))
    fac12 = pd.read_csv(I(UP['S12'] + '/output/factors_s12.csv.gz', 'S12 factor payments and taxes'))
    # fix list A1 (GTAP 12 ch.12 §12.4.4): the S10 specific energy-tax rates as ad valorem rates at the S11 basic prices
    tls_energy, energy_notes = (M.energy_ad_valorem(spec10, evs, io, sectors) if spec10 is not None else (None, []))
    # Fable QA F-04 (s13 choice energy_tax_revenue): a source region's energy-tax rates scaled to its S10 revenue on the
    # S11-valued energy rows before the fit (GTAP 12 ch.8 Appendix A); the fit then holds the rates (ch.17A items 4-5)
    erev, erev_notes = None, []
    if tls_energy is not None and V['energy_tax_revenue'] == M.ENERGY_TAX_REVENUE:
        tls_energy, erev, erev_notes = M.scale_energy_rates_to_source(tls_energy, spec10, evs, io, sectors,
                                                                      targets=M.output_targets(V['energy_targets']))   # beta v4 P34

    R_ = regions.set_index('region')
    regs = sorted(R_.index)
    # fix round S16 (Fable QA C-03): gas into pipeline transport (msp) at most the UNSD 2022 pipeline-transport gas flow
    # (commodity 3000, transaction 1226, TJ) at the S11 domestic gas price (40 GJ per kcm, S11 basis); single economies that report it
    pipe_caps = {}
    if V['energy_user_cells'] == M.ENERGY_USER_CELLS:
        un = pd.read_csv(I(DATA + '/unsd_energy/undata_energy_2022.csv', 'UNSD 2022 pipeline-transport gas (energy_user_cells)'), dtype=str,
                         usecols=['REF_AREA', 'COMMODITY', 'TRANSACTION', 'OBS_VALUE', 'UNIT_MEASURE'])
        iso = pd.read_csv(I(BUILD + '/config/prep_energy/iso3166_alpha.csv', 'ISO 3166 numeric to alpha-3'), dtype=str)
        un = un[(un['COMMODITY'] == '3000') & (un['TRANSACTION'] == '1226') & (un['UNIT_MEASURE'] == 'TJ')]
        un = un.assign(region=un['REF_AREA'].map(dict(zip(iso['numeric'], iso['alpha3']))), tj=un['OBS_VALUE'].astype(float))
        gp = evs[evs['commodity'] == 'gas'].set_index('region')['domestic_price']
        for x in un.dropna(subset=['region']).itertuples():
            if x.region in R_.index and x.region in gp.index and np.isfinite(gp[x.region]) and x.tj > 0:
                pipe_caps[x.region] = {('gas', 'msp'): float(x.tj) * float(gp[x.region]) / 40e3}
        S.log(f'pipeline-transport gas caps: {len(pipe_caps)} regions')
    if sorted(io['region'].unique()) != regs:
        raise SystemExit('io_s12 regions do not match the S01 regions')
    gx = gx[~gx['sector'].isin(ENERGY_TRADE)]
    gm = gm[~gm['sector'].isin(ENERGY_TRADE)]
    evs_t = evs[evs['target'] == 'yes']
    tout = {(r.region, r.commodity): float(r.output_value) for r in evs_t.itertuples()}
    for reg_ in ely_free:          # beta v4 P1 lower bound: the ely row fits free (held at the floor only if it lands below)
        tout.pop((reg_, 'ely'), None)
    # beta v4 P38 (choice tiny_energy_activity, default off; labelled departure): tiny energy activities with no exports shut
    tiny = M.tiny_energy(evs_t) if V['tiny_energy_activity'] == C.TINY_ENERGY else []
    # beta v4 dry run 3 (CHL coal, S13-Hfit): the target falls to the activity's S11 exports (at most TINY_MAX_EXPORT), not to 0;
    # CHL coal keeps 5 USD of exports, which no output of 0 can supply (MC_coa infeasible). With exports the row is all
    # exported (no domestic sales, as with a zero target); with none the activity shuts
    tiny_x = {(x.region, x.commodity): max(float(x.export_value), 0.0) for x in evs_t.itertuples()}
    for reg_, com_, v_, m_ in tiny:
        tout[(reg_, com_)] = tiny_x[(reg_, com_)]
        S.adjust(reg_, f'{com_} output (S11 target, USD million)', v_, tout[(reg_, com_)], V['tiny_energy_activity'],
                 'beta v4 P38; not in the GTAP 12 text', 'TINY-ENERGY-SHUT')
    S.check('S13-Rtiny', 'Beta v4 P38 (choice tiny_energy_activity; default off; not in the GTAP 12 text): S11 energy activities below '
            f'{M.TINY_MAX_MUSD:g} USD million and {M.TINY_MAX_SHARE:.0%} of output plus imports, or below {M.TINY_ABS_MUSD:g} USD million, with exports of '
            f'at most {M.TINY_MAX_EXPORT * 1e3:g} thousand USD: output target cut to the exports (none: shut)',
            'report', len(tiny), 'n/a', True, 'tiny_energy_activity',
            f"{V['tiny_energy_activity']}; " + ('; '.join(f'{r} {c} {v:.2f} (imports {m:.0f})' for r, c, v, m in tiny) or 'none'))
    rep = rep[rep['side'] == 'cost']
    repd = {s: dict(zip(g['item'], g['share'])) for s, g in rep.groupby('sector')}
    dsum = io[io['row'].isin(['dom_oil', 'dom_gas'])].groupby('row')[sectors].sum().sum(axis=1)
    isum = io[io['row'].isin(['imp_oil', 'imp_gas'])].groupby('row')[sectors].sum().sum(axis=1)
    rep_b06 = {('dom', 'oil'): dsum['dom_oil'] / dsum.sum(), ('dom', 'gas'): dsum['dom_gas'] / dsum.sum(),
               ('imp', 'oil'): isum['imp_oil'] / isum.sum(), ('imp', 'gas'): isum['imp_gas'] / isum.sum()}
    supd = {r: g.groupby('basis')['value_musd'].sum().to_dict() for r, g in sup[sup['sector'] == 'crp'].groupby('region')}
    for r, it in pse_items.items():
        if r in supd:
            supd[r]['input_items'] = it
    # round-3 QA item 9: the PSE input remainder on the region's B1 rows instead of every crp input
    pse_rem = C.read_pse_remainder() if V['pse_input_items'].startswith('listed_items_on_their_row_remainder_on_the_listed_b1_rows') else {}
    I(C.CONFIG_DIR + '/pse_input_remainder_2022.csv', 'PSE B1 rows of the input-support remainder by region (round-3 QA item 9)')
    for r, rr in pse_rem.items():
        if r in supd:
            supd[r]['remainder_rows'] = rr
    # B15 double counting: the S10 energy rates are net of the NEERS subsidies (s10 choice energy_subsidies). On a row that
    # gets the IEA subsidy, the NEERS subsidy S10 already placed there is part of it, so S13 books the rest only.
    sub_rows, sub_book, neer_src = [], {}, {}
    neer_col = tls_energy is not None and 'neer_subsidy_rate' in tls_energy.columns
    if fuel_on and len(fsub):
        if tls_energy is not None:
            te = tls_energy[tls_energy['commodity'].isin(M.SUBSIDY_COMMODITIES)]
            neer_src = {k: str(g['source'].iloc[0]) for k, g in te.groupby(['region', 'commodity'])}
            neer_amt = ((te['neer_subsidy_rate'] * te['basic_musd']).groupby([te['region'], te['commodity']]).sum().to_dict()
                        if neer_col else {})
        else:
            neer_amt = {}
        net = V['fuel_subsidy_neer_overlap'] == 'iea_subsidy_net_of_the_neer_subsidy_on_the_row'
        for x in fsub.itertuples():
            nm = float(neer_amt.get((x.region, x.commodity), 0.0))
            book = max(float(x.subsidy_musd) - max(-nm, 0.0), 0.0) if net else float(x.subsidy_musd)
            sub_rows.append(dict(region=x.region, commodity=x.commodity, s11_subsidy_musd=float(x.subsidy_musd), neer_subsidy_musd=nm,
                                 to_book_musd=book, kind='held' if x.commodity in M.output_targets(V['energy_targets']) else 'prior',
                                 rho=0.0, basis='', status='not_fitted', booked_prior_musd=0.0, booked_fitted_musd=np.nan, money_held=False,
                                 capped_musd=0.0, capped_fit_musd=0.0))
            if book > 0:
                sub_book.setdefault(x.region, {})[x.commodity] = book
    # beta v4 anchor B: a 2022 price-shield payment to electricity suppliers is a consumption subsidy on electricity (booked
    # like the IEA subsidy, B15); without fuel_subsidies it stays in the anchor only (reported in S13-Relyanchor)
    shield_booked = {}
    if fuel_on:
        for reg_, amt_ in ely_shield.items():
            if amt_ <= 0 or reg_ not in R_.index:
                continue
            row_ = next((x for x in sub_rows if x['region'] == reg_ and x['commodity'] == 'ely'), None)
            if row_ is None:
                row_ = dict(region=reg_, commodity='ely', s11_subsidy_musd=0.0, neer_subsidy_musd=0.0, to_book_musd=0.0,
                            kind='held' if 'ely' in M.output_targets(V['energy_targets']) else 'prior', rho=0.0, basis='',
                            status='not_fitted', booked_prior_musd=0.0, booked_fitted_musd=np.nan, money_held=False,
                            capped_musd=0.0, capped_fit_musd=0.0)
                sub_rows.append(row_)
            row_['to_book_musd'] += amt_
            row_['shield_musd'] = row_.get('shield_musd', 0.0) + amt_     # S13-Hsubneer: not an IEA gap, nothing to net
            sub_book.setdefault(reg_, {})['ely'] = sub_book.get(reg_, {}).get('ely', 0.0) + amt_
            shield_booked[reg_] = amt_
    sub_ix = {(x['region'], x['commodity']): x for x in sub_rows}
    sub_mask = M.subsidy_columns(list(sectors) + list(FD), sectors, V['fuel_subsidy_users'] == M.FUEL_SUBSIDY_NON_ENERGY)
    if V['power_fuel_cells'] == M.POWER_FUEL_CELLS_ALL:
        pf11 = pd.read_csv(I(UP['S11'] + '/output/power_fuels_s11.csv', 'S11 power fuels by region: coal, crude, gas and pet values of the power column (Fable QA D-06)'))
        power_t = M.power_cell_targets_all(pf11, set(regs))
    else:
        power_t = M.power_cell_targets(pcs, set(regs), V['power_fuel_cells'] == M.POWER_FUEL_CELLS)
    power_rows, user_rows, free_users, partial_users, vat_rows = [], [], [], [], []
    power_scaled = []       # Fable QA F-08: (region, factor) where the power fuel cells are held below their S11 values
    power_dropped, va_trigger = [], []     # beta v4: regions whose power column is free; P5 ladder firings (region, factor, VA before, after)
    sub_tls_gap = 0.0

    # ------------------------------------------------------------- 1. held trade
    trade, travel_used, dropped = M.assemble_trade(gx, gm, ex, em, svc, trv, vst, M.b06_split(io, sectors), tout)
    for x in dropped.itertuples():
        S.adjust(x.exporter, f'travel {x.sector} to {x.importer}', float(x.v), 0.0, V['energy_travel'],
                 'GTAP 12 ch.10B p.3; ch.12 §12.4.1 (S11 output targets)', 'TRAVEL-ENERGY-DROPPED')
    S.log(f'travel on energy goods dropped beyond the S11 domestic room: {dropped["v"].sum():.3f} USD million in {len(dropped)} rows')
    T = trade.set_index(['region', 'sector'])
    n, det = K.export_tax_held(trade, ex, xt10, gx)
    S.check('S13-Hxtax', 'Fix list A2: the held trade carries the export tax: by region and commodity, XFOB - X is the S10 export-tax rate times the S11 VFOB on coa, oil, gas and pet, the S10 wedge on other goods, and 0 on services and travel', 'hard',
            n, 0, n == 0, 'GTAP 12 ch.17A item 2 and eq. 17.30; fix list A2', det or
            f'{bn((trade["XFOB"] - trade["X"]).sum()):.3f} bn of net export tax held, of which energy {bn((trade.loc[trade["sector"].isin(K.ENERGY_XT), "XFOB"] - trade.loc[trade["sector"].isin(K.ENERGY_XT), "X"]).sum()):.3f} bn')

    # ------------------------------------------------------------- 2. macro targets
    mt = M.macro_targets(macro, trade).set_index('region')
    # s13 choice product_tax_source (round-3 final QA2 item 1): representative-table regions' product-tax money from the
    # IMF GFS G114 (WoRLD) instead of the donor's io_s12 money; rates held where no 2022 G114 covers the region
    psrc, PSRC = {}, None
    if V['product_tax_source'] != 'io_s12_money_every_region':
        dw = pd.read_csv(I(UP['S05'] + '/output/donor_weights.csv', 'S05 donors and member weights (product_tax_source)'))
        wld = pd.read_csv(I(DATA + '/imf_world/imf_world_2017_2022.csv', 'IMF WoRLD G114 taxes on goods and services, % of GDP (product_tax_source)'),
                          usecols=['COUNTRY', 'GFS_STO', 'SECTOR', 'TIME_PERIOD', 'OBS_VALUE'], low_memory=False)
        nst = pd.read_csv(I(BUILD + '/config/s13/no_general_sales_tax_2022.csv', 'config: regions with no VAT, sales tax or excise in 2022 (product_tax_source)'))
        PSRC = PS.donor_regions_g114(dw, PS.g114_shares(wld), mt['GDP_musd'].to_dict(), statutory_zero=dict(zip(nst['region'], nst['basis'])))
        psrc = {x['region']: x for x in PSRC.to_dict('records')}
        for x in PSRC[PSRC['mode'] == 'rates'].itertuples():
            S.flag('PTAX-RATES-HELD', x.region, f'representative-table region, {x.note} (members without G114: {x.members_missing or "-"}; donors {x.donors})',
                   rule=V['product_tax_source'], citation=CITE['product_tax_source'])
        S.log('product_tax_source: ' + '; '.join(f'{x.region} {x.mode}' + (f' {x.g114_pct_gdp:.2f}%' if x.mode == 'g114' else '') for x in PSRC.itertuples()))
    # Fable QA C-09 (s13 choice vat_final_demand): the GCC VAT states' VAT on households and government at the IMF GFS money
    vatd = {}
    if V['vat_final_demand'] != 'off':
        vreg = PS.read_vat_regions(I(BUILD + '/config/s13/vat_final_demand_2022.csv', 'GCC VAT states and their VAT law (vat_final_demand)'))
        wld_v = pd.read_csv(I(DATA + '/imf_world/imf_world_2017_2022.csv', 'IMF WoRLD G114 and G1142, % of GDP (vat_final_demand)'),
                            usecols=['COUNTRY', 'GFS_STO', 'SECTOR', 'TIME_PERIOD', 'OBS_VALUE'], low_memory=False)
        parts = PS.gfs_parts(wld_v)
        # beta v5 V (s13 choice vat_exemptions): the exempt rows of the listed regions' VAT laws (config/s13/vat_exempt_rows.csv)
        vex = (PS.read_vat_exempt(I(BUILD + '/config/s13/vat_exempt_rows.csv', 'VAT-exempt rows of the listed VAT regions (beta v5 V)'), vreg)
               if V['vat_exemptions'] == C.VAT_EXEMPTIONS else {})
        for r_ in vreg:
            if (r_, 'G114') not in parts:
                raise SystemExit(f'vat_final_demand: {r_} has no {PS.G114_YEAR} G114 value in the WoRLD data')
            vatd[r_] = dict(g114_pct=parts[(r_, 'G114')], g1142_pct=parts.get((r_, 'G1142'), 0.0), gdp_musd=float(mt.loc[r_, 'GDP_musd']),
                            statutory_rate_pct=float(vreg[r_]['statutory_rate_pct']), excise_part=vreg[r_]['excise_part'], exempt_rows=vex.get(r_, []))
    n_neg, det = K.factor_positive(mt)
    S.check('S13-Hfactor', 'The C, G and I scale factor is positive in every region (GDP = S02 GDP with trade fixed can be met)', 'hard',
            n_neg, 0, n_neg == 0, 'decision 2; GTAP 12 ch.7 p.2; macro_gate', det)
    out_band = mt[(mt['factor'] - 1).abs() > BAND].sort_values('factor')
    gdp_share = out_band['GDP_musd'].sum() / mt['GDP_musd'].sum()
    S.check('S13-Rband', f'Regions whose C, G and I factor is outside 1 ± {BAND:.0%} (PLAN gate, report-only by decision; the large economies\' macro structure is checked hard against WDI at S14-Hmacro and S16-Hmacro, Fable QA E-04)', 'report',
            len(out_band), 0, True, 'macro_gate (David 2026-10-23)',
            f'{gdp_share:.1%} of world GDP. ' + '; '.join(f'{r} {f:.3f}' for r, f in out_band['factor'].items()))

    # ------------------------------------------------------------- 3-5. fit every region
    world_energy = M.world_energy_structure(io, sectors, crude_cols)
    world_sh = M.world_composition(fac12[['region', 'sector', 'factor', 'evfp']], sectors)
    tables, comps, fit_rows, smears, prior_zero, rates, supp_rows, status_rows = [], {}, [], [], {}, [], [], []
    presmear_zero, io12_gap = {}, []
    held_neg = set()
    own_netted = {}                  # beta v4 H2 report: region -> domestic ely own use netted out of the prior
    cap_rows, esplit_moved = [], 0.0
    own_cap_rows, pse_item_rows, own_hold_rows, own_drop_rows = [], [], [], []
    cells, placed_rows, pt_rows, ptax_rows = [], [], [], []
    ptax_drop, ptax_src_rows = {}, []
    choice0 = {'farm_support': V['farm_support'], 'prior_without_va': V['prior_without_va'], 'tax_rates': V['tax_rates'], 'excise_at_source': V['excise_at_source'], 'excise_cap_g114': V['excise_cap_g114'],
              'product_tax_totals': V['product_tax_totals'], 'electricity_subsidy_money': V['electricity_subsidy_money'],
              'own_use_share': V['own_use_share'], 'pse_iea_overlap': V['pse_iea_overlap'],
              'fuel_subsidy_users': V['fuel_subsidy_users'], 'own_use_cap_valuation': V['own_use_cap_valuation'],
              'ely_hold_net_own_use': V['ely_hold_net_own_use'],
              'ely_subsidy_rate_cap_regions': frozenset(ely_sub_cap),
              'energy_user_cells': V['energy_user_cells'], 'fuel_subsidy_rate_cap': V['fuel_subsidy_rate_cap'],
              'energy_targets': V['energy_targets'], 'energy_user_pool_split': V['energy_user_pool_split'],
              'no_refinery_crude_use': V['no_refinery_crude_use'], 'partial_users_extraction': V['partial_users_extraction'],
              'investment_con_share': V['investment_con_share']}
    con_dropped = []                 # beta v5 C: regions whose fit with construction's investment share held did not converge
    fuel_cap_rows = []               # beta v5 F: the fuel-share caps set, by region and pass
    own_basic = V['own_use_cap_valuation'] == M.OWN_USE_BASIC
    extreme_rows = []
    own_rows, held_own = [], M.own_use_held(sectors, V['own_use_share'])
    for reg in (an_regions or regs):
        choice = dict(choice0)       # per region: the beta v5 C fallback below turns investment_con_share off for one region
        fcap = {}                    # beta v5 F: this region's fuel-share caps {(good, column): basic USD million}
        ugoods = None                # the held user rows of the current fit (None: every one; the partial fallback drops pet)
        r = io[io['region'] == reg].set_index('row')
        tr_r = {}
        if reg in T.index.get_level_values(0):
            for c, row in T.loc[reg].iterrows():
                tr_r[('X', c)], tr_r[('M', c)], tr_r[('VST', c)] = row['X'], row['M'], row['VST']
        energy = M.energy_rates_of(tls_energy, reg, list(sectors) + list(FD)) if tls_energy is not None else None
        pw_r = power_t.get(reg)
        hu = V['energy_user_cells'] == M.ENERGY_USER_CELLS
        hx = False          # Fable QA F-06: the extraction fallback, carried into the own-use refits below
        P, info = M.build_problem(reg, r, sectors, tr_r, mt.loc[reg], tout, repd, rep_b06, supd.get(reg, {}), world_energy, choice,
                                  energy=energy, energy_caps=capd.get(reg), subsidies=sub_book.get(reg), own_caps=own_capd.get(reg),
                                  product_layers=pt_layers.get(reg), power_cells=pw_r, crude_cols=crude_cols, ptax_source=psrc.get(reg), hold_users=hu, user_caps=pipe_caps.get(reg), vat=vatd.get(reg), user_share_caps=fcap)
        R, held_r = None, set(held_own)
        if mt.loc[reg, 'factor'] > 0:
            R = M.fit_region(P, info, sectors)
            # beta v4 P1 lower bound, second pass: a free ely row that lands below its floor (or a free fit that fails) is
            # refitted with the row held at the floor; the fallbacks below then keep that hold
            if reg in ely_free and (not R['ok'] or R['out'][sectors.index('ely')] < ely_free[reg] * (1 - 1e-9)):
                ely_second.append((reg, float(R['out'][sectors.index('ely')]) if R['ok'] else np.nan, ely_free[reg]))
                tout[(reg, 'ely')] = ely_free[reg]
                P, info = M.build_problem(reg, r, sectors, tr_r, mt.loc[reg], tout, repd, rep_b06, supd.get(reg, {}), world_energy, choice,
                                          energy=energy, energy_caps=capd.get(reg), subsidies=sub_book.get(reg), own_caps=own_capd.get(reg),
                                          product_layers=pt_layers.get(reg), power_cells=pw_r, crude_cols=crude_cols, ptax_source=psrc.get(reg), hold_users=hu, user_caps=pipe_caps.get(reg), vat=vatd.get(reg), user_share_caps=fcap)
                R = M.fit_region(P, info, sectors)
            if not R['ok'] and choice['investment_con_share'] == M.INVESTMENT_CON_SHARE:
                # beta v5 C: a region whose fit cannot carry construction's source-table share of investment fits it free, flagged
                choice['investment_con_share'] = 'off'
                Pn, infon = M.build_problem(reg, r, sectors, tr_r, mt.loc[reg], tout, repd, rep_b06, supd.get(reg, {}), world_energy, choice,
                                            energy=energy, energy_caps=capd.get(reg), subsidies=sub_book.get(reg), own_caps=own_capd.get(reg),
                                            product_layers=pt_layers.get(reg), power_cells=pw_r, crude_cols=crude_cols, ptax_source=psrc.get(reg), hold_users=hu, user_caps=pipe_caps.get(reg), vat=vatd.get(reg), user_share_caps=fcap)
                Rn = M.fit_region(Pn, infon, sectors)
                if Rn['ok']:
                    S.log(f'{reg}: construction share of investment not held (the fit with it did not converge); fitted free')
                    S.flag('INV-CON-SHARE-FREE', reg, 'the fit with construction held at its io_s12 share of investment did not converge; the investment column fitted free',
                           rule=V['investment_con_share'])
                    P, info, R = Pn, infon, Rn
                    con_dropped.append(reg)
                else:
                    choice['investment_con_share'] = choice0['investment_con_share']     # not the cause: the other fallbacks keep it
            def _bp(pw, users, goods=None):
                return M.build_problem(reg, r, sectors, tr_r, mt.loc[reg], tout, repd, rep_b06, supd.get(reg, {}), world_energy, choice,
                                       energy=energy, energy_caps=capd.get(reg), subsidies=sub_book.get(reg), own_caps=own_capd.get(reg),
                                       product_layers=pt_layers.get(reg), power_cells=pw, crude_cols=crude_cols, ptax_source=psrc.get(reg),
                                       hold_users=users, user_caps=pipe_caps.get(reg), user_goods=goods, vat=vatd.get(reg), user_share_caps=fcap)
            # Fallback order (final round 2026-10-25, D-06 in every region): the S11 power fuel values come from the energy
            # balance (GTAP 12 ch.12 §12.4) and rank ahead of the other agents' prior user shares, so a region that cannot
            # carry both first frees the petroleum users, then every energy user, and only then scales or drops the power
            # cells. (The earlier order tried four power scales and four rounds of freed activities first: about 7 failed
            # fits per region, hours once every power column holds its fuels.)
            if not R['ok'] and hu:
                # the goods: every energy row's users held except the rows in M.USER_DROP_GOODS (petroleum products: DNK,
                # MLT, XWE, YEM, BIH fit with the coa, oil and gas users held), flag ENERGY-USERS-GOODS
                for drop in M.USER_DROP_GOODS:
                    keep = tuple(g for g in M.ENERGY_USER_GOODS if g not in drop)
                    Pp, infop = _bp(pw_r, hu, keep)
                    Rp = M.fit_region(Pp, infop, sectors)
                    if Rp['ok']:
                        S.log(f'{reg}: energy users of {" ".join(drop)} not held (the fit with them did not converge); {" ".join(keep)} held')
                        S.flag('ENERGY-USERS-GOODS', reg, f'users of {" ".join(drop)} fitted free; the users of {" ".join(keep)} held at their prior shares',
                               rule=V['energy_user_cells'])
                        P, info, R, ugoods = Pp, infop, Rp, keep
                        partial_users.append((reg, 'all users of ' + ' '.join(drop)))
                        break
            if not R['ok'] and hu:
                # fix round S16 (Fable QA C-01): a region whose fit cannot carry the held energy user cells fits them free,
                # flagged, with the power fuel cells still held
                Pn, infon = _bp(pw_r, False)
                Rn = M.fit_region(Pn, infon, sectors)
                if Rn['ok']:
                    S.log(f'{reg}: energy user cells not held (the fit with them did not converge); the free fit stays')
                    S.flag('ENERGY-USERS-FREE', reg, 'the fit with the energy rows held at their prior user shares did not converge; energy rows fitted free',
                           rule=V['energy_user_cells'])
                    P, info, R, hu = Pn, infon, Rn, False
                    free_users.append(reg)
            if not R['ok'] and pw_r and V['power_cells_scaled'] == M.POWER_CELLS_SCALED:
                # Fable QA F-08 (IRQ): a power column that cannot carry the S11 fuel values keeps their S11 mix (crude, gas and
                # pet split) at the highest level the fit carries, before the free power column (energy users free)
                for lam in M.POWER_CELL_SCALES:
                    pw_s = dict(pw_r, scale=lam)
                    Pn, infon = _bp(pw_s, False)
                    Rn = M.fit_region(Pn, infon, sectors)
                    if Rn['ok']:
                        S.log(f'{reg}: power fuel cells held at {lam:g} of the S11 values (S11 mix kept)')
                        S.flag('POWER-CELLS-SCALED', reg, f'the S11 crude, gas and pet power cells held at {lam:g} of their values, the S11 mix kept '
                               '(the fit cannot carry the full values)', rule=V['power_cells_scaled'])
                        if hu:
                            S.flag('ENERGY-USERS-FREE', reg, 'the fit with the energy rows held at their prior user shares did not converge; energy rows fitted free',
                                   rule=V['energy_user_cells'])
                            free_users.append(reg)
                        P, info, R, pw_r, hu = Pn, infon, Rn, pw_s, False
                        power_scaled.append((reg, lam))
                        break
            if not R['ok'] and pw_r:
                # round 3 (final QA 2 item 3): a region whose fit cannot carry the held power fuel cells keeps the free power
                # column, flagged (S13-Hpowercell then checks only the regions that hold them)
                Pn, infon = _bp(None, False)
                Rn = M.fit_region(Pn, infon, sectors)
                if Rn['ok']:
                    S.log(f'{reg}: power fuel cells not held (the fit with them did not converge); the free power column stays'
                          + (' (energy user cells not held either)' if hu else ''))
                    S.flag('POWER-CELLS-DROPPED', reg, 'the fit with the S11 crude, gas and pet power cells held did not converge; power column fitted free',
                           rule=V['power_fuel_cells'])
                    if hu:
                        S.flag('ENERGY-USERS-FREE', reg, 'the fit with the energy rows held at their prior user shares did not converge; energy rows fitted free',
                               rule=V['energy_user_cells'])
                        free_users.append(reg)
                    P, info, R, pw_r, hu = Pn, infon, Rn, None, False
                    power_dropped.append(reg)
            if (R['ok'] and not hu and V['energy_user_cells'] == M.ENERGY_USER_CELLS and V['energy_users_fallback'] == M.ENERGY_USERS_FALLBACK):
                # Fable QA F-06 (YEM oil buying refined products at 74% of its output) and C-01: where the held user cells cannot
                # be carried, the extraction columns' cells of the held energy rows keep their prior share of the row (eq. 17.8-17.9
                # for those agents only), every other buyer free
                Pn, infon = M.build_problem(reg, r, sectors, tr_r, mt.loc[reg], tout, repd, rep_b06, supd.get(reg, {}), world_energy, choice,
                                            energy=energy, energy_caps=capd.get(reg), subsidies=sub_book.get(reg), own_caps=own_capd.get(reg),
                                            product_layers=pt_layers.get(reg), power_cells=pw_r, crude_cols=crude_cols, ptax_source=psrc.get(reg), hold_users=False,
                                            user_caps=pipe_caps.get(reg), vat=vatd.get(reg), user_share_caps=fcap, hold_extraction=True)
                Rn = M.fit_region(Pn, infon, sectors)
                if Rn['ok']:
                    S.log(f'{reg}: the extraction columns hold their prior shares of the energy rows (the other energy user cells free)')
                    S.flag('ENERGY-EXTRACTION-SHARES', reg, 'energy user cells not held; the coal, oil and gas columns keep their prior share of each held energy row',
                           rule=V['energy_users_fallback'])
                    P, info, R, hx = Pn, infon, Rn, True
                else:
                    S.log(f'{reg}: the fit with the extraction columns\' energy cells held did not converge; the free fit stays')
            if R['ok'] and pw_r and V['power_va_trigger'] == C.POWER_VA_TRIGGER and 'ely' in sectors:
                # beta v4 P5 (our choice, not in the GTAP text; the only GTAP floor is the 90 percent rule, §12.4.3 p.28): a converged
                # fit that leaves power VA below 3% of output tries the F-08 levels below the one it holds, users held first, then free
                je = sectors.index('ely')
                sh0 = float(R['va'][je] / R['out'][je]) if R['out'][je] > 0 else np.nan
                if np.isfinite(sh0) and sh0 < K.VA_FORCE:
                    got = None
                    for lam in [x for x in M.POWER_CELL_SCALES if x < float(pw_r.get('scale', 1.0))]:
                        for users in ((hu, False) if hu else (False,)):
                            pw_s = dict(pw_r, scale=lam)
                            Pn, infon = _bp(pw_s, users)
                            Rn = M.fit_region(Pn, infon, sectors)
                            if Rn['ok'] and Rn['out'][je] > 0 and Rn['va'][je] / Rn['out'][je] >= K.VA_FORCE:
                                got = (lam, users, Pn, infon, Rn, pw_s)
                                break
                        if got:
                            break
                    if got:
                        lam, users, P, info, R, pw_r = got
                        if hu and not users:
                            free_users.append(reg)
                        hu = users
                        power_scaled.append((reg, lam))
                        va_trigger.append((reg, lam, sh0, float(R['va'][je] / R['out'][je])))
                        S.flag('POWER-VA-TRIGGER', reg, f'converged power VA {sh0:.2%} of output, below {K.VA_FORCE:.0%}: the S11 fuel cells held at {lam:g} '
                               f'of their values (S11 mix kept), VA {va_trigger[-1][3]:.2%}' + ('' if users else '; energy user cells free'),
                               rule=V['power_va_trigger'])
                    else:
                        va_trigger.append((reg, np.nan, sh0, sh0))
                        S.flag('POWER-VA-TRIGGER-NO-FIT', reg, f'converged power VA {sh0:.2%} of output; no F-08 level reaches {K.VA_FORCE:.0%}: the fit stays',
                               rule=V['power_va_trigger'])
            if R['ok'] and hu and V['fuel_share_cap'] == M.FUEL_SHARE_CAP:
                # beta v5 F (our rule, not in the GTAP text): a non-energy activity's held fuel cell at most max(2 x its prior
                # share, prior share + 5 points) of its fitted output; refit with the caps until none binds (or the refit fails)
                for pass_ in range(M.FUEL_CAP_PASSES):
                    caps_n, fr = M.fuel_share_caps(R, info, sectors, fcap)
                    if not fr:
                        break
                    keep_caps = fcap
                    fcap = caps_n
                    Pn, infon = _bp(pw_r, hu, ugoods)
                    Rn = M.fit_region(Pn, infon, sectors)
                    if not Rn['ok']:
                        fcap = keep_caps
                        S.flag('FUEL-SHARE-CAP-NO-FIT', reg, f'pass {pass_ + 1}: the refit with {len(fr)} more fuel-share caps did not converge; '
                               f'{len(fcap)} caps of the earlier passes kept', rule=V['fuel_share_cap'])
                        break
                    P, info, R = Pn, infon, Rn
                    fuel_cap_rows.extend(dict(region=reg, pass_=pass_ + 1, **x) for x in fr)
                for x in info.get('energy_users', []):
                    if x.get('share_capped_musd', 0.0) > M.FUEL_CAP_REMAINDER_FLAG * x['row_musd'] > 0:
                        S.flag('FUEL-SHARE-CAP-REMAINDER', f'{reg} {x["good"]} {x["kind"]}', f'the capped excess {x["share_capped_musd"]:.1f} m is above '
                               f'{M.FUEL_CAP_REMAINDER_FLAG:.0%} of the held row ({x["row_musd"]:.1f} m): the S11 row value or the prior structure may be wrong',
                               rule=V['fuel_share_cap'])
            ev12 = r.loc[[f'EVFP_{f}' for f in FACTORS], sectors].to_numpy(float)
            hm = V['factor_tax_totals'] == 's12_money_held_by_region_and_factor'
            neg = (lambda R_, i_: M.negative_surplus(reg, R_, i_, sectors, tr_r, ev12, world_sh, fac12, hm))
            if R['ok'] and own_capd.get(reg):
                # fix round wG, second pass: a free fit that takes a capped energy diagonal above its UNSD share refits with
                # that diagonal's share of the column held at its (capped) prior share; the refit is kept only if it converges
                # and adds no negative operating surplus (17B p.3 signs)
                over = EN.own_use_overshoot(P, R, sectors, {c: v for c, v in own_capd[reg].items() if info['status'].get(c) == 'prior'},
                                            tau_cell=info['tau_cell'] if own_basic else None)
                if pw_r:
                    # the held power fuel cells fix part of the ely column: its own-use share is not also held
                    over = {c: v for c, v in over.items() if c != 'ely'}
                if over:
                    P2, info2 = M.build_problem(reg, r, sectors, tr_r, mt.loc[reg], tout, repd, rep_b06, supd.get(reg, {}), world_energy, choice,
                                                energy=energy, energy_caps=capd.get(reg), subsidies=sub_book.get(reg), own_caps=own_capd.get(reg),
                                                hold_own=tuple(over), product_layers=pt_layers.get(reg), power_cells=pw_r,
                                                crude_cols=crude_cols, ptax_source=psrc.get(reg), hold_users=hu, user_caps=pipe_caps.get(reg), vat=vatd.get(reg), user_share_caps=fcap, hold_extraction=hx)
                    R2 = M.fit_region(P2, info2, sectors)
                    why = '' if R2['ok'] else 'did not converge'
                    if R2['ok']:
                        added = set(neg(R2, info2)) - set(neg(R, info))
                        if added:
                            why = 'negative EVOS ' + ', '.join(sorted(added))
                    own_hold_rows.extend(dict(region=reg, good=c, fitted_free=f, cap=cp, refit_ok=not why, refit_note=why) for c, (f, cp) in over.items())
                    if not why:
                        P, info, R = P2, info2, R2
                        held_r |= set(over)
                    else:
                        S.log(f'{reg}: own-use refit with {sorted(over)} held not kept ({why}); the free fit stays')
                # a capped fit that leaves negative operating surplus where the uncapped prior does not: the caps are dropped
                n1 = neg(R, info) if R['ok'] else []
                if n1:
                    P0, info0 = M.build_problem(reg, r, sectors, tr_r, mt.loc[reg], tout, repd, rep_b06, supd.get(reg, {}), world_energy, choice,
                                                energy=energy, energy_caps=capd.get(reg), subsidies=sub_book.get(reg),
                                                product_layers=pt_layers.get(reg), power_cells=pw_r, crude_cols=crude_cols, ptax_source=psrc.get(reg), hold_users=hu, user_caps=pipe_caps.get(reg), vat=vatd.get(reg), user_share_caps=fcap, hold_extraction=hx)
                    R0 = M.fit_region(P0, info0, sectors)
                    n0 = neg(R0, info0) if R0['ok'] else None
                    keep = n0 is not None and len(n0) < len(n1)
                    own_drop_rows.append(dict(region=reg, negative_capped='; '.join(n1), negative_uncapped='' if n0 is None else '; '.join(n0),
                                              caps_dropped=keep, goods='; '.join(f'{x["item"]} {x["share_cap"]:.4f}' for x in info['own_caps'])))
                    if keep:
                        S.log(f'{reg}: own-use caps dropped (negative EVOS {n1} with the caps, {n0} without)')
                        P, info, R, held_r = P0, info0, R0, set(held_own)
                        for x in own_hold_rows:
                            if x['region'] == reg:
                                x.update(refit_ok=False, refit_note='caps dropped (negative EVOS)')
        if info['placed'].get('pattern') is not None:
            pt_rows.append(dict(region=reg, **info['placed']['pattern']))
        for c, f in info['fuel'].items():
            if f.get('capped_musd'):
                sub_ix[(reg, c)].update(to_book_musd=sub_ix[(reg, c)]['to_book_musd'] - f['capped_musd'], capped_musd=f['capped_musd'],
                                        capped_fit_musd=f.get('capped_fit_musd', 0.0))
            sub_ix[(reg, c)].update(rho=f['rho'], basis=f['basis'], status=f['status'], booked_prior_musd=f['booked_prior'],
                                    money_held=bool(f.get('money_held')), mask=f.get('mask', sub_mask))
        power_rows += [dict(region=reg, **x) for x in info.get('power_cells', [])]
        if info.get('vat'):
            vat_rows.append(dict(region=reg, **info['vat']))
        user_rows += [dict(region=reg, **x) for x in info.get('energy_users', [])]
        cap_rows += [dict(region=reg, **x) for x in info['energy_caps']]
        own_cap_rows += [dict(region=reg, **x) for x in info['own_caps']]
        pse_item_rows += [dict(region=reg, input_row=c, listed_musd=float(pse_items.get(reg, {}).get(c, 0.0)), **f) for c, f in info['pse_items'].items()]
        pse_item_rows += [dict(region=reg, input_row=c, listed_musd=float(v), value_musd=0.0, rate=np.nan, basic_before=np.nan, basic_after=np.nan,
                               part='listed')
                          for c, v in pse_items.get(reg, {}).items() if c not in info['pse_items']]
        for col, k in info['placed']['capped']:
            placed_rows.append(dict(region=reg, column=col, how='energy part capped at the column TLS', factor=k, tls_musd=np.nan, total_musd=np.nan))
        for col, g_net, g in info['placed']['floored']:
            placed_rows.append(dict(region=reg, column=col, how=f'general rate {g_net:.6f} below min(IO rate, 0): set to {g:.6f}', factor=np.nan,
                                    tls_musd=np.nan, total_musd=np.nan))
        for col, t0, t1 in info['placed']['moved']:
            placed_rows.append(dict(region=reg, column=col, how='column product-tax total moved at the prior (energy rates held)', factor=np.nan,
                                    tls_musd=t0, total_musd=t1))
        for j, col in enumerate(list(sectors) + list(FD)):
            for i, c in enumerate(sectors):
                t, tt = info['tau_cell'][i, j], info['tau_tls_cell'][i, j]
                if t != 1.0 or tt != 1.0:
                    cells.append((reg, col, c, tt - 1.0, t - tt))
        for item, col, before, after, rule, flag in info['notes']:
            S.adjust(reg, f'{item} {col}', before, after, rule, CITE.get(rule, 'GTAP 12 ch.17A'), flag)
            if flag == 'NEG-VA-HELD':
                held_neg.add((reg, col))
            if flag == 'OWN-USE-CAP-NETTED' and item == 'dom_ely':
                own_netted[reg] = before - after         # beta v4 H2 report (S13-Relyhold), agents' prices
        for item, how, v in info['smears']:
            smears.append(dict(region=reg, item=item, how=how, value_musd=v))
            S.adjust(reg, f'{item} prior', 0.0, v, how, 'GTAP 12 ch.12 §12.4.1 (1/32 smear)', 'SMEAR')
        for c, st in info['status'].items():
            if st != 'prior':
                status_rows.append(dict(region=reg, sector=c, status=st))
                S.flag({'representative': 'REP-TABLE-COLUMN', 'zero_target': 'SHUT-ZERO-TARGET', 'none': 'SHUT-NO-OUTPUT'}[st], f'{reg} {c}',
                       {'representative': 'exports or an S11 target and no prior column: S03 representative-table cost structure (ch.9D)',
                        'zero_target': 'S11 output value 0: row and column shut',
                        'none': 'no prior output, no exports, no target: row and column shut'}[st],
                       rule=V['zero_output_column'] if st == 'representative' else V['shut_activity'])
        for g in ('stock_gap', 'grev_gap'):
            s = float(r.loc[[f'dom_{c}' for c in sectors] + [f'imp_{c}' for c in sectors] + ['TLS'], g].sum())
            if s:
                S.adjust(reg, f'{g} column', s, 0.0, V['stock_change' if g == 'stock_gap' else 'grev_gap'],
                         'GTAP 12 ch.17A item 3 and footnote 2' if g == 'stock_gap' else 'S04 handoff §1.3; E40', 'GAP-REMOVED')
        bsum = info['basic0']['dom'].sum(axis=0) + info['basic0']['imp'].sum(axis=0)
        for j, col in enumerate(list(sectors) + list(FD)):
            rates.append(dict(region=reg, column=col, tls_rate=info['tau_tls'][j] - 1.0, pse_rate=info['tau'][j] - info['tau_tls'][j],
                              output_tax_rate=(info['pi'][j] - 1.0) if j < len(sectors) else 0.0, s12_basic_musd=bsum[j]))
        if info['bad_tau']:
            S.flag('TAX-POWER-NONPOSITIVE', reg, f'columns {info["bad_tau"]} have a net tax power at or below zero')
        if R is None:
            fit_rows.append(dict(region=reg, ok=False, resid=np.inf, iterations=0, information_musd=np.nan,
                                 worst=f'C, G and I targets negative (factor {mt.loc[reg, "factor"]:.3f})', t=0.0))
            continue
        if R['ok']:
            own_rows += K.own_use_rows(reg, P, R, sectors, held_r, tau_cell=info['tau_cell'])
        fit_rows.append(dict(region=reg, ok=R['ok'], resid=R['resid'], iterations=R['it'], information_musd=R['I'],
                             worst='; '.join(f'{n} {v:.3g}' for n, v in R['worst'][:5]), t=R['t']))
        if not R['ok']:
            S.log(f'{reg}: fit did not reach the targets (path t={R["t"]}); binding rows {R["worst"][:5]}')
            continue
        if V['energy_import_shares'] != 'icio_agent_split':
            # fix-round B1: energy goods at the region's purchase-wide import share for every agent (s13_fit/energy.py)
            moved = EN.import_proportionality(R['dom'], R['imp'], {c: i for i, c in enumerate(sectors)})
            if moved > 0:
                S.adjust(reg, 'energy rows: domestic and imported split by agent (absolute value moved)', 0.0, moved,
                         'energy_import_shares', 'GTAP import proportionality for energy (IMPROVEMENTS_LOG S15-1; fix-round B1)', 'ENERGY-IMPORT-SHARE')
            esplit_moved += moved
        # GTAP 12 ch.17B (report, finding #12): very large net tax or subsidy rates on small basic flows
        extreme_rows += K.extreme_rates(reg, info['tau_cell'], info['basic0'], R['dom'] + R['imp'], sectors, list(sectors) + list(FD))
        evfp12_r = r.loc[[f'EVFP_{f}' for f in FACTORS], sectors].to_numpy(float)
        tab, comp = M.region_table(reg, R, info, sectors, tr_r, evfp12_r, world_sh)
        tables.append(tab)
        if info['fuel']:
            # B15: the subsidy in the fitted table, and the column TLS moving by exactly the booked subsidy
            bfit = R['dom'] + R['imp']
            rho_v = np.zeros(bfit.shape)
            for c, f in info['fuel'].items():
                if f['status'] == 'booked':
                    fm = f.get('mask', sub_mask)
                    rho_v[sectors.index(c), fm] = f['rho']
                    sub_ix[(reg, c)]['booked_fitted_musd'] = float(f['rho'] * bfit[sectors.index(c), fm].sum())
            tls_fit = tab.set_index('row').loc['TLS', list(sectors) + list(FD)].to_numpy(float)
            sub_tls_gap = max(sub_tls_gap, K.subsidy_tls_gap(bfit, info['tau_tls_nosub'], rho_v, sub_mask, tls_fit))
        comps[reg] = comp
        # round-3 QA item 3 (product_tax_totals): each column's product tax at the prior and in the fit, its general part
        # (held in money) and the scale on its general rates
        tls_fit = tab.set_index('row').loc['TLS', list(sectors) + list(FD)].to_numpy(float)
        pt = info['ptax']
        rep_pt = pt.get('report') or {}
        drop_r = float(rep_pt.get('dropped', 0.0)) if rep_pt else 0.0
        if drop_r:
            # round-3 final QA2 item 4: general product-tax money no column can carry within the 2x bound, dropped
            tgt_r = float(np.sum(pt['target']))
            S.adjust(reg, 'general product-tax money (all purchaser columns)', tgt_r, tgt_r - drop_r, 'product_tax_totals',
                     'GTAP 12 ch.8 Appendix A; S13 PTAX_SCALE_BOUND (round-3 final QA2 item 4)', 'PTAX-DROPPED')
        ptax_drop[reg] = drop_r
        if pt.get('source'):
            ps_ = pt['source']
            jp_ = (list(sectors) + list(FD)).index('p')
            bp_ = float(R['dom'][:, jp_].sum() + R['imp'][:, jp_].sum())
            ptax_src_rows.append(dict(region=reg, mode=ps_.get('mode'), g114_pct_gdp=ps_.get('g114_pct_gdp'), g114_musd=ps_.get('g114_musd'),
                                      cover=ps_.get('cover'), sectors=ps_.get('sectors'), members_missing=ps_.get('members_missing'),
                                      donors=ps_.get('donors'), energy_excise_musd=ps_.get('energy_excise_musd', np.nan),
                                      donor_general_musd=ps_.get('donor_general_musd', np.nan),
                                      general_target_musd=float(np.sum(pt['target'])) if ps_.get('mode') == 'g114' else np.nan,
                                      general_factor=ps_.get('factor', np.nan),
                                      general_fitted_musd=float(((R['dom'] + R['imp']) * pt['general']).sum()),
                                      dropped_musd=drop_r, unsourced_cells=ps_.get('unsourced_cells', 0),
                                      unsourced_musd=ps_.get('unsourced_musd', 0.0), negative_general_cells=int((pt['general'] < 0).sum()),
                                      household_general_rate=float(((R['dom'][:, jp_] + R['imp'][:, jp_]) * pt['general'][:, jp_]).sum() / bp_) if bp_ > 0 else np.nan,
                                      excise_cap_factor=ps_.get('excise_cap_factor', 1.0),
                                      energy_excise_before_cap_musd=ps_.get('energy_excise_before_cap_musd', np.nan),
                                      **PS.final_demand_rate_max(pt['general'], list(sectors), list(sectors) + list(FD)),
                                      note=ps_.get('note')))
        bfit = R['dom'] + R['imp']
        g_now = (bfit * pt['general']).sum(axis=0)
        g0 = np.abs(pt['general0']).sum(axis=0)
        for j, col in enumerate(list(sectors) + list(FD)):
            if pt['prior'][j] == 0 and tls_fit[j] == 0 and pt['target'][j] == 0:
                continue
            ptax_rows.append(dict(region=reg, column=col, prior_tls_musd=pt['prior'][j], general_target_musd=pt['target'][j],
                                  general_effective_musd=(rep_pt['effective'][j] if rep_pt else pt['target'][j]),
                                  general_free_fit_musd=(rep_pt['free_fit'][j] if rep_pt else g_now[j]), general_musd=g_now[j],
                                  general_scale=(np.abs(pt['general'][:, j]).sum() / g0[j]) if g0[j] > 0 else 1.0, tls_musd=tls_fit[j],
                                  held=pt['hold'], passes=rep_pt.get('passes', 0), unheld=rep_pt.get('unheld', {}).get(col, '')))
        idx_s = {c: i for i, c in enumerate(sectors)}
        prior_zero[reg] = EN.zero_mask({k: info['pv0'][k] <= 0 for k in ('dom', 'imp')}, idx_s)
        io12_gap.append(info['io12_gap'])
        presmear_zero[reg] = EN.zero_mask({k: info['pv_presmear'][k] <= 0 for k in ('dom', 'imp')}, idx_s)
        jc = sectors.index('crp')
        tb = tab.set_index('row')
        # PTAX on crp is the S12 output tax less the PSE output support (A3); the support's part keeps its base share
        ot, ps = float(info['otax0'][jc]), float(info['pse_out'])
        sup_part = ps / (ps - ot) if ps - ot > 0 else (1.0 if ot == 0 else 0.0)
        supp_rows.append(dict(region=reg, pse_input_s10_musd=info['pse_in'], pse_output_s10_musd=ps,
                              input_rate=-(info['tau'][jc] - info['tau_tls'][jc]), output_rate=ps / info['out0'][jc] if info['out0'][jc] > 0 else 0.0,
                              pse_input_booked_musd=-float(tb.loc['PSE_input', 'crp']), pse_output_booked_musd=-float(tb.loc['PTAX', 'crp']) * sup_part))
        for c, how in comp.items():
            if how == 'world':
                S.flag('FACTORS-WORLD-COMPOSITION', f'{reg} {c}', 'new activity: S12 world composition of the sector, region-average factor tax rates',
                       rule=V['new_activity_factors'])
    S.log(f'fitted {sum(x["ok"] for x in fit_rows)} of {len(regs)} regions')
    io13 = pd.concat(tables, ignore_index=True) if tables else pd.DataFrame(columns=['region', 'row'])
    fit = pd.DataFrame(fit_rows)
    fitted = sorted(io13['region'].unique()) if len(io13) else []
    rates = pd.DataFrame(rates)

    # ------------------------------------------------------------- 6. factors
    fac13 = M.factor_table(io13, fac12, sectors, hold_money=V['factor_tax_totals'] == 's12_money_held_by_region_and_factor')

    # ------------------------------------------------------------- checks
    n_c, det = K.converged(fit_rows)
    S.check('S13-Hfit', 'Every region reaches every held row (relative residual below 1e-9), with no slack or plug', 'hard',
            n_c, 0, n_c == 0, 'PLAN §3(i) no plugs; ch.17A', det)
    io_f = io13
    trade_f = trade[trade['region'].isin(fitted)]
    n, det = K.cost_identity(io_f, sectors)
    S.check('S13-Hcost', 'Zero profit: every activity\'s purchases, taxes, support, factor payments and output tax add up to its output', 'hard', n, 0, n == 0, 'PLAN §3(i) constraint 1', det)
    n, det = K.market_clearing(io_f, sectors)
    S.check('S13-Hmarket', 'Market clearing at basic prices: domestic purchases + exports + VST = output for every commodity', 'hard', n, 0, n == 0, 'PLAN §3(i) constraint 2', det)
    n, det = K.imports_identity(io_f, sectors)
    S.check('S13-Himports', 'Imported purchases add up to the held VMSB for every commodity', 'hard', n, 0, n == 0, 'PLAN §3(i) constraint 3', det)
    n, det = K.held_trade(io_f, trade_f, sectors)
    S.check('S13-Htrade', 'Exports, VST and imports in io_s13 equal the held S09, S10 and S11 values', 'hard', n, 0, n == 0, 'PLAN §3(i) constraint 4', det)
    n, det = K.final_demand(io_f, sectors, mt)
    S.check('S13-Hfd', 'C, G and I at purchasers\' prices equal S02 times the region factor', 'hard', n, 0, n == 0, 'PLAN §3(i) constraint 7; decision 2', det)
    n, det = K.gdp_identity(io_f, sectors, trade_f, mt['GDP_musd'].to_dict())
    S.check('S13-Hgdp', 'GDP from expenditure and from income both equal S02 GDP', 'hard', n, 0, n == 0, 'PLAN §3(i) constraint 6', det)
    n, det = K.energy_targets(io_f, {k: v for k, v in tout.items() if k[0] in fitted})
    S.check('S13-Henergy', 'Output equals the S11 value for every coal, oil, gas and petroleum target (and electricity, beta v4 P1, choice energy_targets)', 'hard', n, 0, n == 0, 'PLAN §3(i) constraint 5; E49', det)
    # beta v4 P1 (s11 ely_output_value; s13 ely_floor_mode): which ely rows were held at the floor, fitted free, or held in the second pass
    outf = io_f[io_f['row'] == 'OUT'].set_index('region')['ely'] if 'ely' in io_f.columns else pd.Series(dtype=float)
    fl_f = [x for x in ely_fl if x[0] in fitted]
    sec_r = {x[0] for x in ely_second}
    free_f = [x for x in fl_f if x[0] in ely_free and x[0] not in sec_r]
    below = [x for x in fl_f if outf.get(x[0], 0.0) < x[3] * (1 - 1e-6)]
    big = sorted(fl_f, key=lambda x: -abs(outf.get(x[0], 0.0) - x[2]))[:12]
    S.check('S13-Relyfloor', 'Beta v4 P1 floor (s11 ely_output_value; s13 ely_floor_mode ' + V['ely_floor_mode'] + '): the floor, (energy inputs + own use '
            'at S11 prices) / 0.9 + pass-through and at least net exports, is a lower bound: ely held at the floor where it is above the prior '
            'io_s12 column, otherwise fitted free and held at the floor only where the free fit lands below it (USD bn); no fitted ely row below its floor',
            'report', len(below), 0, not below, 'ely_output_value',
            (f'{len([x for x in raised if x[0] in fitted])} held at the floor above the prior (+{sum(x[4] - x[2] for x in raised if x[0] in fitted) / 1e3:.1f} bn); {len(free_f)} free; '
             f'{len(ely_second)} held in the second pass ({", ".join(r_ for r_, _, _ in ely_second[:20])}); '
             f'below the floor: {", ".join(x[0] for x in below) or "none"}; largest moves from the prior: '
             + '; '.join(f'{x[0]} prior {x[2] / 1e3:.2f} floor {x[3] / 1e3:.2f} fitted {outf.get(x[0], 0.0) / 1e3:.2f}' for x in big)) if fl_f else 'no floor rows')
    # beta v4 H2 (s13 choice ely_hold_net_own_use): what set each held ely row, and the netted own use against the estimate
    h2_rows = []
    for reg_, v_, p_, f_, h_ in fl_f:
        if not np.isfinite(h_):
            continue
        net_ = ely_net.get(reg_, 0.0)
        cands = {'prior less netted own use': p_ - net_, 'floor': f_, 'S11 value (IEA subsidy)': v_ if reg_ in ely_smin else -np.inf}
        by_ = max(cands, key=cands.get)
        if ely_cap_m is not None and h_ < cands[by_] - 1e-6:
            by_ = f'cap (m {ely_cap_m:g})'
        h2_rows.append((reg_, p_, net_, h_, by_, outf.get(reg_, 0.0)))
    netted = {r_: v_ for r_, v_ in own_netted.items() if r_ in fitted}
    S.check('S13-Relyhold', 'Beta v4 H2 (s13 choices ely_hold_net_own_use ' + V['ely_hold_net_own_use'] + ', ely_hold_cap ' + V['ely_hold_cap'] + '; our rule, not in the GTAP text): '
            'the ely hold is max(prior less the domestic own use the own-use cap nets out, the P1 floor, net exports, and in the IEA '
            'electricity-subsidy regions the S11 value), at most the S11 value marked up by m on its domestic electricity sales (ely_hold_cap), '
            'never below the floor; which term set each held row, the estimated against the netted own use, '
            'and the fitted output (USD bn)', 'report', len(h2_rows) if (ely_h2 or ely_cap_m) else 0, '', True, 'ely_hold_net_own_use; ely_hold_cap',
            ('off' if not (ely_h2 or ely_cap_m) else
             f'{len(ely_net)} regions with netted own use ({sum(ely_net.values()) / 1e3:.1f} bn estimated on io_s12, {sum(netted.values()) / 1e3:.1f} bn netted in the '
             f'prior of {len(netted)} fitted regions); '
             f'{len(ely_smin)} IEA ely-subsidy regions; set by: '
             + ', '.join(f'{k_} {n_}' for k_, n_ in pd.Series([x[4] for x in h2_rows], dtype=object).value_counts().items())
             + '; capped: ' + (', '.join(x[0] for x in h2_rows if x[4].startswith('cap')) or 'none')
             + '; largest nettings: ' + '; '.join(f'{x[0]} prior {x[1] / 1e3:.1f} netted {x[2] / 1e3:.1f} held {x[3] / 1e3:.1f} ({x[4]}) fitted {x[5] / 1e3:.1f}'
                                               for x in sorted(h2_rows, key=lambda x: -x[2])[:12])))
    # beta v5 F, C and N1 reports (our rules, labelled; not in the GTAP text)
    FC = pd.DataFrame(fuel_cap_rows, columns=['region', 'pass_', 'good', 'column', 'prior_share', 'fitted_share', 'cap_share', 'fitted_musd', 'cap_musd'])
    fc_last = FC.sort_values('pass_').groupby(['region', 'good', 'column']).first().reset_index() if len(FC) else FC
    fc_left = K.fuel_share_over(io_f, io[io['region'].isin(fitted)], sectors, M.FUEL_CAP_GOODS, M.FUEL_CAP_FACTOR, M.FUEL_CAP_POINTS, M.FUEL_CAP_MIN_MUSD)
    S.check('S13-Rfuelcap', 'Beta v5 F (s13 choice fuel_share_cap ' + V['fuel_share_cap'] + '; our rule, not in the GTAP text): non-energy activities\' '
            'coal, crude, gas and product cells (domestic plus imported, basic) capped at max(2 x prior share, prior share + 5 points) of fitted output; '
            'cells set, the excess moved to the other held users (USD bn), and fitted cells still above the cap (fallback regions with free users, refits that failed)',
            'report', len(fc_left), 0, True, 'fuel_share_cap',
            (f'{len(fc_last)} cells in {fc_last["region"].nunique() if len(fc_last) else 0} regions capped, '
             f'{(fc_last["fitted_musd"] - fc_last["cap_musd"]).sum() / 1e3:.2f} bn over the cap at the first pass; largest: '
             + '; '.join(f'{x.region} {x.column} {x.good} {x.fitted_share:.1%}->{x.cap_share:.1%}' for x in fc_last.assign(e=fc_last['fitted_musd'] - fc_last['cap_musd']).sort_values('e', ascending=False).head(12).itertuples())
             + '. Still above after the fit: ' + ('; '.join(fc_left[:25]) or 'none')) if V['fuel_share_cap'] != 'off' else 'off: ' + f'{len(fc_left)} cells above the cap')
    S.write('fuel_share_caps_s13.csv', FC.round(9))
    cs = K.investment_con_share(io_f, io[io['region'].isin(fitted)])
    gdp_f = mt['GDP_musd']
    con_va = (io_f[io_f['row'].str.startswith('EVFP_')].groupby('region')['con'].sum() / gdp_f.reindex(fitted)) if 'con' in io_f.columns else pd.Series(dtype=float)
    low = sorted(con_va.index[con_va < 0.02])
    S.check('S13-Rconshare', 'Beta v5 C (s13 choice investment_con_share ' + V['investment_con_share'] + '; our rule, not in the GTAP text): construction\'s share of '
            'the investment column (domestic plus imported) against its io_s12 share, the regions fitted free (flag INV-CON-SHARE-FREE), '
            'and the regions with construction VA below 2% of GDP', 'report', len(low), '', True, 'investment_con_share',
            f'{len(con_dropped)} fitted free ({", ".join(con_dropped) or "none"}; energy-user fallbacks there as well: '
            + (', '.join(f'{r_} {" ".join(sorted({f["id"] for f in S.flags if f["subject"] == r_ and f["id"].startswith("ENERGY-USERS")})) or "none"}'
                         for r_ in con_dropped) or 'none') + '); largest share moves: '
            + '; '.join(f'{x.region} {x.prior:.3f}->{x.fitted:.3f}' for x in cs.assign(m=(cs['fitted'] - cs['prior']).abs()).sort_values('m', ascending=False).head(10).itertuples())
            + f'; construction VA below 2% of GDP: {len(low)} ({" ".join(low)})')
    S.write('investment_con_share_s13.csv', cs.round(9))
    ol = [(r_, c_, s_) for r_, d_ in own_listed.items() for c_, s_ in d_.items() if r_ in fitted]
    olr = []
    for r_, c_, s_ in ol:
        b_ = io_f[io_f['region'] == r_].set_index('row')
        o_ = float(b_.loc['OUT', c_])
        olr.append((r_, c_, s_, float(b_.loc[f'dom_{c_}', c_] + b_.loc[f'imp_{c_}', c_]) / o_ if o_ > 0 else np.nan, o_))
    S.check('S13-Rownlisted', 'Beta v5 N1 (s13 choice own_use_cap_listed ' + V['own_use_cap_listed'] + '; our rule, not in the GTAP text): the listed non-energy '
            'diagonals (config/s13/own_use_cap_listed.csv) after the fit, share of output against the listed cap', 'report', len(olr), '', True, 'own_use_cap_listed',
            '; '.join(f'{r_} {c_} {f_:.3f} (cap {s_:.3f}), output {o_ / 1e3:.1f} bn' for r_, c_, s_, f_, o_ in olr) or 'none listed or fitted')
    # beta v4 anchor B (s13 choice ely_output_anchor): the measured value against the prior, held and fitted output
    anc_f = sorted((r_ for r_ in ely_anchor if r_ in fitted), key=lambda r_: -ely_anchor[r_])
    prior_ = {x[0]: x[2] for x in ely_fl}
    S.check('S13-Relyanchor', 'Beta v4 anchor B (s13 choice ely_output_anchor ' + V['ely_output_anchor'] + '; GTAP 12 ch.12 §12.3.6-12.4.3, prices '
            'by use class times volumes): in the regions of ely_output_anchor_2022.csv the ely hold is the S11 domestic sales at the '
            'households\' share times the household price and the rest at the non-household price (2022, before taxes), plus exports, '
            'the gas and heat resold at cost and any 2022 price-shield payment (ely_price_shield_2022.csv, booked as a consumption '
            'subsidy), never below the floor or net exports (USD bn)', 'report', len(anc_f), '', True, 'ely_output_anchor',
            ('off' if not ely_anc_on else
             f'{len(anc_tab)} listed, {len(anc_f)} fitted; anchor {sum(ely_anchor[r_] for r_ in anc_f) / 1e3:.1f} bn against prior '
             f'{sum(prior_.get(r_, 0.0) for r_ in anc_f) / 1e3:.1f} bn; shield payments {sum(ely_shield.values()) / 1e3:.2f} bn '
             f'({len(shield_booked)} booked{"" if fuel_on else ", fuel_subsidies off: not booked"}); '
             + '; '.join(f'{r_} anchor {ely_anchor[r_] / 1e3:.1f} prior {prior_.get(r_, 0.0) / 1e3:.1f} fitted {outf.get(r_, 0.0) / 1e3:.1f}'
                         for r_ in anc_f[:15])))
    # beta v4 P1 and P15 (GTAP 12 ch.12 §12.4.3 p.28 re-checked on the fitted table): the refining and power columns' energy
    # inputs that S11's rule priced and S13 held stay within 90 percent of revenue; regions fitted with those cells free are reported
    pts = (evs[evs['commodity'] == 'ely'].set_index('region')['pass_through_value'].to_dict() if 'pass_through_value' in evs.columns else {})
    # dry run 3 (S16 2026-10-26): the energy-user fallbacks free the other users of the energy rows, not the power fuel cells,
    # which stay held unless the power column itself is dropped; so ely is exempt only where the power cells are free, and
    # pet (its crude, gas and own-product cells are user cells) wherever the users are free
    unfit = set(regs) - set(fitted)
    exempt90 = ({(r_, 'ely') for r_ in set(power_dropped) | unfit}
                | {(r_, 'pet') for r_ in set(free_users) | set(power_dropped) | {r_ for r_, _ in partial_users} | unfit})
    hard90 = (V['energy_user_cells'] == M.ENERGY_USER_CELLS and V['energy_user_pool_split'] == M.POOL_SPLIT
              and V['energy_targets'] == M.ENERGY_TARGETS_ELY and V['power_fuel_cells'] == M.POWER_FUEL_CELLS_ALL)
    # beta v4 dry run 3 (choice ninety_fit_price): the held inputs at purchaser prices, the fitted rho on the columns it covers
    cols_all = list(sectors) + list(FD)
    rho90 = ({(x['region'], x['commodity'], col): float(x['rho']) for x in sub_rows if x['status'] == 'booked'
              for col in ('ely', 'pet') if col in cols_all and x.get('mask', sub_mask)[cols_all.index(col)]}
             if V['ninety_fit_price'] == C.NINETY_FIT_PURCHASER else None)
    # beta v5 build (coordinator OK 2026-10-27 17:24 UTC, check only): the fitted ratio may exceed 0.90 by at most 1e-4 (fit rounding;
    # CHE pet came out at 0.900029 after the v5 S13 fit, 0.1 USD m over)
    n, det, NF = K.ninety_fitted(io_f[io_f['region'].isin(fitted)], pass_through=pts, exempt=exempt90, rho=rho90, tol=H90FIT_ABS_TOL / K.NINETY)
    S.check('S13-H90fit', 'GTAP 12 ch.12 §12.4.3 on the fitted table (beta v4 P1, P15): in every region fitted with its power fuel cells and refining inputs held, '
            'the refining column\'s crude, gas and own-product purchases and the power column\'s coal, crude, gas and product purchases (at purchaser prices, '
            'basic x (1 - fitted fuel subsidy rate), with choice ninety_fit_price; less the gas and heat it '
            'resells at cost) are at most 90 percent of revenue (output less resale, plus any output subsidy); hard with energy_user_pool_split, energy_targets '
            'and power_fuel_cells on', 'hard' if hard90 else 'report', n, 0, n == 0, 'ninety_pct_ely; energy_user_pool_split',
            det or f'{len(NF)} columns; exempt (fitted with those cells free): {" ".join(f"{r_} {c_}" for r_, c_ in sorted(exempt90) if r_ in fitted) or "none"}')
    lo = NF[NF['va_share'] < K.VA_FORCE]
    band = NF[(NF['va_share'] >= K.VA_FORCE) & (NF['va_share'] < K.VA_FLAG)]
    S.check('S13-Rva', f'Refining and power value added below {K.VA_FORCE:.0%} of output, and in the {K.VA_FORCE:.0%}-{K.VA_FLAG:.0%} review band (beta v4 P5; '
            f'choice power_va_trigger = {V["power_va_trigger"]}); all energy inputs over revenue beside it', 'report', f'{len(lo)} below; {len(band)} in band', 0, True,
            'power_va_trigger', '; '.join(f'{x.region} {x.industry} VA {x.va_share:.2%} energy {x.ratio_all:.3f}' for x in pd.concat([lo, band]).itertuples())[:1500])
    S.check('S13-Rvatrigger', 'Beta v4 P5 (power_va_trigger): regions where a converged power VA below 3% fired the F-08 ladder (factor, VA before -> after; '
            'no factor: no level reached 3%)', 'report', len(va_trigger), 0, True, 'power_va_trigger',
            '; '.join(f'{r_} {l_:g} {a_:.2%} -> {b_:.2%}' for r_, l_, a_, b_ in va_trigger))
    S.write('ninety_fitted_s13.csv', NF.round(9))
    # beta v4 P14 (choice no_refinery_crude_use): no crude to households where there is no refinery
    n, det, chk = K.household_crude_no_refinery(io_f[io_f['region'].isin(fitted)])
    S.check('S13-Hcrudehh', 'Beta v4 P14 (GTAP 12 ch.12 §12.2.4; S11 sends a no-refinery producer\'s crude to exports): households buy no crude '
            '(at most 1 USD m) in a region with no refining output', 'hard' if V['no_refinery_crude_use'] == M.NO_REFINERY_CRUDE else 'report',
            n, 0, n == 0, 'no_refinery_crude_use', det or f'{len(chk)} regions without refining output checked')
    cells = pd.DataFrame(cells, columns=['region', 'column', 'commodity', 'tls_rate', 'pse_rate'])
    n, det = K.tax_rates(io_f, sectors, rates[rates['region'].isin(fitted)], cells[cells['region'].isin(fitted)])
    S.check('S13-Hrates', 'Every cell keeps its net product-tax rate (energy rows at the GTAP ad valorem energy rates plus the column\'s general part, the general part by commodity from the S10 VAT and excise layers (non_energy_rates) or one general rate; a representative column: the representative rate, ledgered), every column its farm input-support rate, and every activity its output-support rate: column TLS = sum of basic purchases x cell rate', 'hard', n, 0, n == 0, 'PLAN §3(i) constraint 8; ch.11A; fix list A1', det)
    # fix-round B15: fuel subsidies (GTAP's booking, Chepeliev et al. 2018 §3)
    if fuel_on:
        SB = [x for x in sub_rows if x['region'] in fitted]
        n1, det1 = K.fuel_subsidy_booked(SB)
        tls_ok = sub_tls_gap <= 1e-8
        S.check('S13-Hsubsidy', 'Fuel subsidies (fix-round B15): every S11 IEA subsidy row (price-gap and extension rows, net of the NEERS subsidy on the row) is booked as one '
                'negative rate on the good\'s purchases by firms, households and government, the prior purchasers\' values kept; the fitted table books '
                'it exactly for the S11 target goods (electricity: exactly in the prior, and in the fitted table when electricity_subsidy_money holds it), and every column TLS moves by exactly the booked subsidy (1e-8)', 'hard',
                n1 + (0 if tls_ok else 1), 0, n1 == 0 and tls_ok, 'fuel_subsidies',
                (det1 + ('' if tls_ok else f'; column TLS gap {sub_tls_gap:.2e}')) or
                f'{len([x for x in SB if x["status"] == "booked"])} rows; booked {bn(sum(x["booked_fitted_musd"] for x in SB if x["status"] == "booked")):.1f} bn at fitted '
                f'values of {bn(sum(x["to_book_musd"] for x in SB)):.1f} bn to book (S11 {bn(sum(x["s11_subsidy_musd"] for x in SB)):.1f} bn); TLS gap {sub_tls_gap:.1e}')
        net = V['fuel_subsidy_neer_overlap'] == 'iea_subsidy_net_of_the_neer_subsidy_on_the_row'
        n2, det2 = K.neer_overlap(SB, neer_src, neer_col or tls_energy is None) if net else (0, '')
        S.check('S13-Hsubneer' if net else 'S13-Rsubneer',
                'No double counting (fix-round B15): the IEA subsidy booked on an energy row is net of the NEERS subsidy S10 already placed '
                'on it (energy_tax_s10 neer_subsidy_rate)' + ('' if net else '; choice set to book in full, overlap reported only'),
                'hard' if net else 'report', n2, 0, n2 == 0, 'fuel_subsidy_neer_overlap',
                det2 or f'NEERS subsidies on IEA-gap rows {bn(-sum(x["neer_subsidy_musd"] for x in SB)):.1f} bn'
                + (', netted out' if net else ' (not netted)' + ('' if neer_col else '; S10 gives no neer_subsidy_rate, overlap unknown')))
        ely = [x for x in SB if x['kind'] == 'prior' and x['status'] == 'booked']
        S.check('S13-Rsubsidy', 'Fuel subsidies on electricity (not an S11 target): booked in the prior; ' + ('held in money through the fit (electricity_subsidy_money)' if V['electricity_subsidy_money'] == M.ELY_SUBSIDY_HOLD else 'the fit moves them with the purchases') + ' (bn, fitted vs prior)', 'report',
                f'{bn(sum(x["booked_fitted_musd"] for x in ely)):.1f} vs {bn(sum(x["booked_prior_musd"] for x in ely)):.1f}', '', True, 'fuel_subsidies',
                '; '.join(f'{x["region"]} {x["booked_fitted_musd"]:.0f}/{x["booked_prior_musd"]:.0f}' for x in ely)[:1500])
    # fix-round A10 and B1 (s13_fit/energy.py)
    agents_all = list(sectors) + list(FD)
    if V['energy_import_shares'] != 'icio_agent_split':
        n, det = EN.import_share_gap(io_f, sectors, agents_all)
        S.check('S13-Hesplit', 'Energy goods (coa, oil, gas, pet, ely): every agent\'s import share equals the region\'s purchase-wide import share (1e-6)', 'hard',
                n, 0, n == 0, 'energy_import_shares; GTAP import proportionality (fix-round B1)', det or f'{bn(esplit_moved):.1f} bn moved between domestic and imported cells')
    CR = pd.DataFrame(cap_rows, columns=['region', 'item', 'column', 'status', 'share_cap', 'share_prior'])
    S.check('S13-Rcaps', 'Prior cells capped at the S11 energy balance (fix-round A10): refinery crude at measured intake, gas own use at the UNSD share', 'report',
            '; '.join(f'{k} {v}' for k, v in CR.groupby('status').size().items()) or 'none', '', True, 'energy_use_caps',
            '; '.join(f'{x.region} {x.item} {x.share_prior:.2f}>{x.share_cap:.2f}' for x in CR.itertuples())[:1500])
    oc, og = EN.cap_report(io_f, ecaps)
    S.check('S13-Rcapfit', 'After the fit: refinery crude above the measured intake value, and gas own use above the UNSD share, by more than 1 percent and 0.1 bn', 'report',
            f'crude {len(oc)}; gas own use {len(og)}', '', True, 'energy_use_caps', '; '.join(oc + og)[:1500])
    # fix round wG (QA round 2 P5): energy diagonals capped at the UNSD own use + losses share of output
    OC = pd.DataFrame(own_cap_rows, columns=['region', 'item', 'column', 'status', 'share_cap', 'share_prior', 'prior_musd', 'cap_musd'])
    S.check('S13-Rowncap', 'Prior energy diagonals (dom + imp own good, basic) capped at the S11 UNSD own use + losses share of output '
            '(fix round wG; ely excess netted out, coa/oil/gas excess to the row\'s other buyers)', 'report',
            '; '.join(f'{k} {v}' for k, v in OC.groupby('status').size().items()) or 'none', '', True, 'own_use_cap',
            '; '.join(f'{x.region} {x.item} {x.share_prior:.3f}>{x.share_cap:.3f} ({(x.prior_musd - x.cap_musd) / 1e3:.1f} bn)'
                      for x in OC.sort_values('prior_musd', ascending=False).itertuples())[:1500])
    OH = pd.DataFrame(own_hold_rows, columns=['region', 'good', 'fitted_free', 'cap', 'refit_ok', 'refit_note'])
    OD = pd.DataFrame(own_drop_rows, columns=['region', 'negative_capped', 'negative_uncapped', 'caps_dropped', 'goods'])
    S.check('S13-Rowndrop', 'Own-use caps dropped (fix round wG): regions whose capped fit leaves a factor cell with negative operating surplus '
            '(factor taxes held as money) that the uncapped prior does not; there the caps are dropped and the uncapped fit stays (17B p.3 signs first)',
            'report', f'{int(OD["caps_dropped"].astype(bool).sum())} dropped of {len(OD)} with a negative EVOS', '', True, 'own_use_cap',
            '; '.join(f'{x.region}: capped [{x.negative_capped}] uncapped [{x.negative_uncapped}]{" dropped " + x.goods if x.caps_dropped else ""}'
                      for x in OD.itertuples())[:1500])
    S.check('S13-Rownhold', 'Own-use second pass (fix round wG): free fits whose energy diagonal ended above its UNSD share by more than 1 point, '
            'refitted with that share of the column held at its capped prior share (refit not converged or adding a negative EVOS: the free fit stays)', 'report',
            f'{int(OH["refit_ok"].sum())} held; {int((~OH["refit_ok"].astype(bool)).sum())} refit not kept', '', True, 'own_use_cap',
            '; '.join(f'{x.region} {x.good} {x.fitted_free:.3f}>{x.cap:.3f}{"" if x.refit_ok else f" (not kept: {x.refit_note})"}' for x in OH.itertuples())[:1500])
    caps_ou = {(x.region, x.commodity): float(x.own_use_share) for x in ou11.dropna(subset=['own_use_share']).itertuples()}
    caps_ou.update({(r_, c_): s_ for r_, d_ in own_listed.items() for c_, s_ in d_.items()})      # beta v5 N1
    ov = EN.own_use_cap_report(io_f, caps_ou) if V['own_use_cap'] != 'off' else []
    S.check('S13-Rowncapfit', 'After the fit: energy diagonals above the S11 UNSD own use + losses share of output by more than 1 point and 0.1 bn '
            '(the fit moves a capped cell with its column\'s priced rows; report: ch.17A holds no own-use target, the cap is applied to the prior; Fable QA E-04)', 'report', len(ov), '', True, 'own_use_cap', '; '.join(ov)[:1500])
    # round 3 final QA 2 item 3: the crude-burning power columns hold their S11 crude, gas and pet values (dom + imp, basic;
    # import proportionality moves value between domestic and imported, never the cell total)
    PC = pd.DataFrame(power_rows, columns=['region', 'good', 'kind', 's11_musd', 'held_musd', 'row_musd', 'status'])
    n_pc, d_pc, PCF = K.power_cells_held(io_f, PC, fitted)
    S.check('S13-Hpowercell', 'Power fuel cells (round 3, final QA 2 item 3; choice power_fuel_cells; GTAP 12 ch.12 §12.4, ch.17A): in every '
            'fitted region whose power column holds its S11 fuels (choice power_fuel_cells: every region from power_fuels_s11, Fable QA D-06; or the crude burners), the fitted coal, crude, gas and pet '
            'purchases of the power column (domestic plus imported, basic) equal the held S11 values (1e-6 relative)',
            'hard' if V['power_fuel_cells'] in (M.POWER_FUEL_CELLS, M.POWER_FUEL_CELLS_ALL) else 'report', n_pc, 0, n_pc == 0, 'power_fuel_cells',
            d_pc or '; '.join(f'{x.region} {x.good} {bn(x.fitted_musd):.2f} (S11 {bn(x.s11_musd):.2f})' for x in PCF.itertuples()))
    S.write('power_cells_s13.csv', PCF.round(9))
    S.check('S13-Rpowerscaled', 'Fable QA F-08 (power_cells_scaled; logged departure): regions whose power column holds the S11 crude, gas and pet fuel '
            'values at a factor below 1 (the S11 mix kept); the power column sits below the S11 energy balance by that factor', 'report',
            len(power_scaled), 0, True, 'power_cells_scaled', '; '.join(f'{r_} {f_:g}' for r_, f_ in sorted(power_scaled)))
    # fix round S16 (Fable QA C-01): the held energy rows by user; the report compares the share of each row the extraction
    # columns (coa, oil, gas) buy on the fitted table with the io_s12 prior share (the QA measure: LBY electricity 0.01 -> 0.82)
    EU = pd.DataFrame(user_rows, columns=['region', 'good', 'kind', 'row_musd', 'held_musd', 'pool_musd', 'cells', 'pool_prior_share', 'scale',
                                          'capped_column', 'capped_musd', 'free_columns', 'pool_held_musd', 'pool_held_columns'])
    S.write('energy_users_s13.csv', EU.round(9))
    # Fable QA review of the C-01 fix: by region, the share of the held energy rows' money that the fit leaves free (refining and
    # power pool, columns freed by HOLD_COLUMN_MAX or the fallbacks: their rows count as free), and the fuel subsidy money above the rate cap
    fr = []
    for r_ in fitted:
        e_ = EU[EU['region'] == r_]
        tot = float(e_['row_musd'].sum())
        free = 1.0 if r_ in free_users or not tot else 1.0 - float(e_['held_musd'].sum()) / tot
        fr.append((free, r_))
    fr.sort(reverse=True)
    S.check('S13-Rusersmoney', 'Held energy rows (coa, oil, gas, pet): share of their money the fit leaves free by region (the refining and power '
            'pool, freed columns; a region on the free fit counts 1), top 25 and the median; fuel subsidy money above the rate cap by region (bn)', 'report',
            f'median {np.median([f_ for f_, _ in fr]):.3f}' if fr else '', '', True, 'energy_user_cells',
            ('; '.join(f'{r_} {f_:.2f}' for f_, r_ in fr[:25]) + ' | capped subsidy: '
             + '; '.join(f'{x["region"]} {x["commodity"]} {bn(x["capped_musd"]):.2f}' for x in sub_rows if x.get('capped_musd')))[:1500])
    ext = [c for c in ('coa', 'oil', 'gas') if c in sectors]
    rise = []
    for g in ('coa', 'oil', 'gas', 'pet', 'ely'):
        rows_ = [f'dom_{g}', f'imp_{g}']
        cols_ = list(sectors) + list(FD)
        a = io[io['row'].isin(rows_)].groupby('region')[cols_].sum()
        b = io_f[io_f['row'].isin(rows_)].groupby('region')[cols_].sum()
        sa = a[ext].sum(axis=1) / a.sum(axis=1).where(a.sum(axis=1) > 0)
        sb = b[ext].sum(axis=1) / b.sum(axis=1).where(b.sum(axis=1) > 0)
        d = (sb - sa.reindex(sb.index)).dropna()
        rise += [(r_, g, float(sa.get(r_, np.nan)), float(sb[r_])) for r_ in d[d > 0.10].index]
    S.check('S13-Rusersfree', 'Regions whose fit could not carry the held energy user cells and keep the free fit (flag ENERGY-USERS-FREE; Fable QA review: listed, not silent)',
            'report', len(free_users), 0, True, 'energy_user_cells', ', '.join(sorted(free_users)))
    S.check('S13-Rusersheld', 'Regions that hold the energy user cells except in the listed activities or goods (flags ENERGY-USERS-PARTIAL: their own market rows bound with the cells held; ENERGY-USERS-GOODS)',
            'report', len(partial_users), 0, True, 'energy_user_cells', '; '.join(f'{r_}: {c_}' for r_, c_ in sorted(partial_users)))
    S.check('S13-Rextraction', 'Energy rows (coa, oil, gas, pet, ely; domestic plus imported) whose share bought by the extraction columns (coa, oil, gas) '
            'rises by more than 0.10 over the io_s12 prior (Fable QA C-01; report)', 'report', len(rise), 0, True, 'energy_user_cells',
            '; '.join(f'{r_} {g} {a_:.2f} -> {b_:.2f}' for r_, g, a_, b_ in sorted(rise, key=lambda x: x[2] - x[3])[:40]))
    PI = pd.DataFrame(pse_item_rows, columns=['region', 'input_row', 'listed_musd', 'value_musd', 'rate', 'basic_before', 'basic_after', 'part', 'netted_musd'])
    n_pi, d_pi = K.pse_items_booked(PI, {r: supd.get(r, {}).get('input', 0.0) for r in set(pse_items) | set(pse_rem)}, pse_items, fitted,
                                    remainder=pse_rem)
    S.check('S13-Hpseitem', 'PSE B1 items (fix round wG, config/s13/pse_input_items_2022.csv): every listed item of a fitted region is booked on its '
            'crp row in full (or scaled to the PSE input total), with a purchase on the row; where config/s13/pse_input_remainder_2022.csv names the '
            'region\'s B1 rows (round-3 QA item 9), the whole PSE input total is booked on the item rows, none on the other inputs', 'hard', n_pi, 0, n_pi == 0, 'pse_input_items',
            d_pi or '; '.join(f'{x.region} {x.input_row} {x.value_musd / 1e3:.1f} bn, cell rate {x.rate:.3f}' for x in PI.itertuples()))
    # round-3 QA item 3 (product_tax_totals): the general part of every column's product tax held in money, and every
    # region's net product tax against its prior (io_s12 TLS with the A1 move, less the fuel subsidies booked)
    PX = pd.DataFrame(ptax_rows, columns=['region', 'column', 'prior_tls_musd', 'general_target_musd', 'general_effective_musd', 'general_free_fit_musd', 'general_musd',
                                          'general_scale', 'tls_musd', 'held', 'passes', 'unheld'])
    held_pt = V['product_tax_totals'] == M.PTAX_HOLD
    fuel_reg = {}
    for x in sub_rows:
        if x['status'] == 'booked' and x['region'] in fitted and np.isfinite(x['booked_fitted_musd']):
            fuel_reg[x['region']] = fuel_reg.get(x['region'], 0.0) + float(x['booked_fitted_musd'])
    PXR = K.product_tax_by_region(PX, fuel_reg)
    # round-3 final QA item 4: factor income above GDP only by the product subsidies booked from their sources
    n_fg, d_fg, FG = K.factor_income_gdp(io_f, sectors, mt['GDP_musd'].to_dict(), fuel_reg)
    top_fg = FG.sort_values('factor_income_over_gdp', ascending=False).head(10)
    S.check('S13-Hfacgdp', 'Factor income above GDP only by the booked product subsidies (round-3 final QA item 4): in every region factor income '
            '(EVFP) less GDP is at most the fuel subsidies in the fitted table (B15) plus the PSE input support plus the output subsidies (negative '
            f'PTAX), within max({K.FACGDP_REL:g} of GDP, {K.FACGDP_MUSD:g} USD m)', 'hard', n_fg, 0, n_fg == 0, 'electricity_subsidy_money',
            d_fg or f'{len(FG)} regions; {int((FG["excess_musd"] > 0).sum())} with factor income above GDP; highest: '
            + '; '.join(f'{x.region} {x.factor_income_over_gdp:.3f} (excess {bn(x.excess_musd):.1f} bn, subsidies {bn(x.booked_subsidy_musd):.1f} bn)'
                        for x in top_fg.itertuples()))
    if held_pt:
        n_px, d_px = K.product_tax_held(PX)
        hp = PX[PX['held'].astype(bool) & (PX['general_target_musd'].abs() > 1.0)]
        sc = hp['general_scale']
        cl = PX[PX['unheld'].fillna('').astype(str) != '']
        S.check('S13-Hptaxheld', 'Product-tax money held by column (round-3 QA item 3, product_tax_totals; GTAP 12 ch.8 Appendix A, ch.15): in every '
                'purchaser column the general part of the product tax (cell rates less the energy-tax rates) on the fitted purchases equals its money on '
                f'the io_s12 flows, plus its share of what the region\'s columns at the scale bound ({M.PTAX_SCALE_BOUND:g}x) cannot carry (relative '
                f'{K.PTAX_COLUMN_TOL:g}); the cell pattern is kept and scaled by one factor per column', 'hard', n_px, 0, n_px == 0,
                'product_tax_totals', d_px or (f'{len(PX)} columns; general part {bn(PX["general_musd"].sum()):.1f} bn (free fit '
                                              f'{bn((PX["general_free_fit_musd"] - PX["general_target_musd"]).sum()):+.1f} bn off it); scale on the general '
                                              f'rates median {sc.median():.4f}, range {sc.min():.3f} to {sc.max():.3f}; passes up to {int(PX["passes"].max())}; '
                                              f'{len(cl)} columns at the bound, {bn((cl["general_target_musd"] - cl["general_musd"]).sum()):+.2f} bn carried by '
                                              'their regions\' other columns: ' + '; '.join(f'{x.region} {x.column} {x.general_target_musd:.0f}->{x.general_musd:.0f}'
                                                                                        for x in cl.reindex((cl['general_target_musd'] - cl['general_musd']).abs()
                                                                                                            .sort_values(ascending=False).index).head(12).itertuples())
                                              if len(PX) else 'no column'))
        n_pr, d_pr = K.product_tax_region(PX, dropped=ptax_drop)
        S.check('S13-Hptaxregion', 'Product-tax money held by region (round-3 QA item 3, product_tax_totals): every region\'s general product-tax money '
                f'(all purchaser columns, those at the scale bound included) on the fitted purchases equals its target (io_s12 money, or the G114 money of '
                f'product_tax_source) less what no column can carry within the {M.PTAX_SCALE_BOUND:g}x bound, the region fallback included (dropped and '
                f'ledgered as PTAX-DROPPED, round-3 final QA2 item 4; relative {K.PTAX_COLUMN_TOL:g})',
                'hard', n_pr, 0, n_pr == 0, 'product_tax_totals',
                d_pr or (f'{PXR["region"].nunique()} regions; general part {bn(PXR["general_fitted_musd"].sum()):.1f} bn of a target '
                         f'{bn(PXR["general_io12_musd"].sum()):.1f} bn; dropped {bn(sum(ptax_drop.values())):.2f} bn net, '
                         f'{bn(sum(abs(v) for v in ptax_drop.values())):.2f} bn gross in {sum(1 for v in ptax_drop.values() if v)} regions: '
                         + '; '.join(f'{r} {v:+.1f} m' for r, v in sorted(ptax_drop.items(), key=lambda kv: -abs(kv[1])) if v)))
    flag = PXR[PXR['gap_rel'].abs() > K.PTAX_QA_FLAG]
    top = PXR.reindex(PXR['gap_musd'].abs().sort_values(ascending=False).index).head(15)
    S.check('S13-Rptaxprior', 'Net product tax by region (TLS of firms, households, government and investment) against the round-3 QA prior: io_s12 TLS '
            'with the A1 energy move, less the fuel subsidies booked (USD bn; regions more than 5% off). With the general part held, the gap is the '
            'energy-tax part: the held GTAP ad valorem energy rates (ch.12 §12.4.4) on the fitted energy purchases (S11 values) instead of the io_s12 '
            'energy flows', 'report', f'{len(flag)} regions above 5%', '', True, 'product_tax_totals',
            f'world fitted {bn(PXR["fitted_musd"].sum()):.1f} bn vs prior {bn(PXR["prior_musd"].sum()):.1f} bn; energy part on io_s12 flows '
            f'{bn(PXR["energy_io12_musd"].sum()):.1f} bn, on fitted flows {bn(PXR["energy_fitted_musd"].sum()):.1f} bn; '
            + '; '.join(f'{x.region} {bn(x.gap_musd):+.2f} ({x.gap_rel:+.1%}; energy {bn(x.energy_io12_musd):.1f}->{bn(x.energy_fitted_musd):.1f})'
                        for x in top.itertuples()))
    PSX = pd.DataFrame(ptax_src_rows, columns=['region', 'mode', 'g114_pct_gdp', 'g114_musd', 'cover', 'sectors', 'members_missing', 'donors',
                                               'energy_excise_musd', 'donor_general_musd', 'general_target_musd', 'general_factor',
                                               'general_fitted_musd', 'dropped_musd', 'unsourced_cells', 'unsourced_musd', 'negative_general_cells',
                                               'household_general_rate', 'excise_cap_factor', 'energy_excise_before_cap_musd', 'p_rate_max',
                                               'g_rate_max', 'note'])
    # beta v4 G15 (Grok QA A6): where the energy excise on the io_s12 flows exceeds the region's G114 product-tax total, the
    # general product tax is set to 0 with no message (ptax_source.scale_general_to_total); listed here, and flagged
    ex_over = PSX[(PSX['mode'] == 'g114') & (PSX['energy_excise_musd'] > PSX['g114_musd'] + 1e-6)]
    for x in ex_over.itertuples():
        S.flag('PTAX-EXCISE-ABOVE-G114', x.region, f'energy excise {x.energy_excise_musd:.1f} USD m on the io_s12 flows exceeds G114 '
               f'{x.g114_musd:.1f} USD m: general product tax set to 0 (the S10 excise is a proxy fill; source or cap it: David)',
               rule='product_tax_source')
    S.check('S13-Rexcise', 'Beta v4 G15: representative-table regions whose energy excise exceeds their IMF GFS G114 product-tax total '
            '(their general product tax is set to 0)', 'report', len(ex_over), 0, True, 'product_tax_source',
            '; '.join(f'{x.region} excise {x.energy_excise_musd:.0f} vs G114 {x.g114_musd:.0f} USD m' for x in ex_over.itertuples()) or 'none')
    # beta v4 G15 (s13 choice excise_cap_g114): with the cap on, no representative-table region's energy excise exceeds G114
    cap_on = V.get('excise_cap_g114') == PS.EXCISE_CAP_G114
    capped = PSX[PSX['excise_cap_factor'].fillna(1.0) < 1.0] if len(PSX) else PSX
    for x in capped.itertuples():
        S.flag('PTAX-EXCISE-CAPPED', x.region, f'energy excise {x.energy_excise_before_cap_musd:.1f} USD m on the io_s12 flows scaled by '
               f'{x.excise_cap_factor:.3f} to the IMF GFS G114 total {x.g114_musd:.1f} USD m (beta v4 G15)', rule='excise_cap_g114')
    S.check('S13-Hexcise', 'Beta v4 G15 (excise_cap_g114): every representative-table region\'s energy excise on the io_s12 flows is at most its '
            'IMF GFS G114 product-tax total (hard when the cap is on)', 'hard' if cap_on else 'report', len(ex_over), 0,
            len(ex_over) == 0 or not cap_on, 'excise_cap_g114',
            '; '.join(f'{x.region} {x.energy_excise_before_cap_musd:.0f} -> {x.energy_excise_musd:.0f} USD m (x{x.excise_cap_factor:.3f})'
                      for x in capped.itertuples()) or 'none capped')
    # beta v4 G14: a representative-table region's non-energy household or government general rate above 100% is a donor artefact
    fd_hi = PSX[(PSX['p_rate_max'] > PS.FD_RATE_MAX) | (PSX['g_rate_max'] > PS.FD_RATE_MAX)] if len(PSX) else PSX
    S.check('S13-Hfdrate', f'Beta v4 G14: every representative-table region\'s general product-tax rate on households\' and government\'s '
            f'non-energy purchases (households\' fbt excise left out) is at most {PS.FD_RATE_MAX:.0%}', 'hard', len(fd_hi), 0, len(fd_hi) == 0,
            'vat_final_demand', '; '.join(f'{x.region} p {x.p_rate_max:.2f} g {x.g_rate_max:.2f}' for x in fd_hi.itertuples()) or
            f'max p {PSX["p_rate_max"].max():.3f}, g {PSX["g_rate_max"].max():.3f}' if len(PSX) else 'none')
    if PSRC is not None:
        n_ps, d_ps = K.product_tax_source(PSRC, PSX, fitted, money_held=held_pt)
        g = PSX[PSX['mode'] == 'g114']
        S.check('S13-Hptaxsource', 'Representative-table regions take their product-tax money from tax statistics (round-3 final QA2 item 1, '
                'product_tax_source; GTAP 12 ch.8 Appendix A, ch.9D, ch.15): every S05 donor region has a source; where the 2022 IMF GFS G114 '
                f'covers it (members with a value at least {PS.G114_COVER_MIN:.0%} of GDP) its general product-tax money '
                + ('on the fitted purchases equals G114 x S02 GDP less the energy excise on the io_s12 flows (less what the bound drops)' if held_pt else
                   'on the io_s12 flows (the prior) equals G114 x S02 GDP less the energy excise, and the fit holds the rates (product_tax_totals, ch.17A item 4)')
                + '; elsewhere its rates are held',
                'hard', n_ps, 0, n_ps == 0, 'product_tax_source',
                d_ps or (f'{len(PSRC)} donor regions: {len(g)} at G114, {int((PSRC["mode"] == "rates").sum())} rates held '
                         f'({" ".join(PSRC.loc[PSRC["mode"] == "rates", "region"])}); general money {bn(g["donor_general_musd"].sum()):.1f} bn '
                         f'(donor pattern) -> {bn(g["general_fitted_musd"].sum()):.1f} bn; '
                         + '; '.join(f'{x.region} {x.donor_general_musd:.0f}->{x.general_fitted_musd:.0f} m (G114 {x.g114_pct_gdp:.2f}% GDP)'
                                     for x in g.reindex((g['donor_general_musd'] - g['general_fitted_musd']).abs().sort_values(ascending=False).index).head(12).itertuples())))
        ng = PSX[PSX['negative_general_cells'] > 0]
        S.check('S13-Hdonorsub', 'No representative-table region keeps a donor subsidy: the negative general product-tax rates of the donor '
                'pattern have no source for the region and are set to 0 (ptax_source.zero_unsourced_general; GTAP 12 ch.11A, 11C: a subsidy '
                'from a cited source; the ch.12 energy-tax rates and the OECD PSE input support are booked apart)', 'hard', len(ng), 0, ng.empty,
                'product_tax_source', '; '.join(f'{x.region} {x.negative_general_cells}' for x in ng.itertuples())
                or (f'{int(PSX["unsourced_cells"].sum())} cells in {int((PSX["unsourced_cells"] > 0).sum())} regions set to 0 '
                    f'({bn(PSX["unsourced_musd"].sum()):.2f} bn of donor subsidies)'))
        nv = PSX[PSX['region'].isin(PS.NO_VAT_2022)]
        hi = nv[nv['household_general_rate'] > PS.NO_VAT_RATE_MAX]
        S.check('S13-Rnovat', f'Household general product-tax rate (general money over basic purchases) in the regions without a VAT or general sales '
                f'tax in 2022 ({" ".join(PS.NO_VAT_2022)}) below {PS.NO_VAT_RATE_MAX:.0%} (round-3 final QA2 item 1; report: a region without a '
                '2022 G114 keeps its donor rates)', 'report', len(hi), 0, True, 'product_tax_source',
                '; '.join(f'{x.region} {x.household_general_rate:.3f} ({x.mode})' for x in nv.itertuples()))
    if vatd and vat_rows:      # an analysis subset may hold no VAT state
        VT = pd.DataFrame(vat_rows)
        ne_ = [c for c in sectors if c not in PS.NON_ENERGY_EXCLUDED]
        hh = []
        for x in VT.itertuples():
            b = io13[io13['region'] == x.region].set_index('row')
            rt = cells[(cells['region'] == x.region) & (cells['column'] == 'p')].set_index('commodity')['tls_rate'].reindex(ne_).fillna(0.0)
            d = b.loc[[f'dom_{c}' for c in ne_], 'p'].to_numpy(float) if len(b) else np.zeros(len(ne_))
            hh.append(float(1.0 + (rt.to_numpy() * d).sum() / d.sum()) if d.sum() > 0 else np.nan)
        VT['household_non_energy_dom_power'] = hh
        S.write('vat_final_demand_s13.csv', VT.round(9))
        # beta v4 G14: the VAT rate on final demand is at most the statutory rate
        over = VT[(VT['p_rate_max'] > VT['statutory_rate'] + 1e-9) | (VT['g_rate_max'] > VT['statutory_rate'] + 1e-9)]
        S.check('S13-Hvatcap', 'Beta v4 G14: in every VAT state of vat_final_demand_2022.csv the general rate on households\' and government\'s '
                'non-energy purchases (households\' fbt excise left out) is at most the statutory VAT rate', 'hard', len(over), 0, len(over) == 0,
                'vat_final_demand', '; '.join(f'{x.region} p {x.p_rate_max:.3f} g {x.g_rate_max:.3f} vs {x.statutory_rate:.2f}' for x in
                                              (over if len(over) else VT).itertuples()))
        S.check('S13-Rvat', 'Fable QA C-09 (vat_final_demand): GCC VAT states\' VAT on households and government at the IMF GFS money (G114 less excises '
                'G1142, times S02 GDP, less the energy excise), firms deducting input VAT; the excises on households\' fbt (VAT rate; household '
                'non-energy power on domestic goods after the fit)', 'report', len(VT), '', True, 'vat_final_demand',
                '; '.join(f'{x.region} VAT {x.vat_musd / 1e3:.1f} bn at {x.vat_rate:.3f}, excise {x.excise_musd / 1e3:.2f} bn, firms {x.firms_general_musd / 1e3:+.1f} bn, '
                          f'household power {x.household_non_energy_dom_power:.3f}' for x in VT.itertuples()))
    # beta v4 G4 (Grok QA D N3): households as employers above 5% of household spending (the ZAF ICIO T column copied to donors)
    hhe_sh = []
    if len(io13):
        for reg_, b in io13.groupby('region'):
            b = b.set_index('row')
            hb = sum(float(b.loc[x, 'p']) for x in ('dom_hhe', 'imp_hhe') if x in b.index)
            tot = float(b.loc[[x for x in b.index if x.startswith(('dom_', 'imp_'))], 'p'].sum())
            if tot > 0 and hb / tot > K.HHE_SHARE_MAX:
                hhe_sh.append((reg_, hb / tot))
    S.check('S13-Rhhe', f'Beta v4 G4: regions whose households spend more than {K.HHE_SHARE_MAX:.0%} of their basic purchases on hhe (activities of '
            'households as employers)', 'report', len(hhe_sh), 0, True, 'household_employers_va (S03)',
            '; '.join(f'{r_} {v_:.1%}' for r_, v_ in sorted(hhe_sh, key=lambda t: -t[1])) or 'none')
    placed = pd.DataFrame(placed_rows, columns=['region', 'column', 'how', 'factor', 'tls_musd', 'total_musd'])
    if len(placed):
        nc = int(placed['how'].str.startswith('energy part capped').sum())
        nf = int(placed['how'].str.startswith('general rate').sum())
        S.flag('ENERGY-TAX-PLACED', 'TLS', f"{nc} columns had their energy rates scaled to fit the io_s12 column TLS; {nf} columns had the general rate "
               'set to min(IO rate, 0) because the energy excise exceeds the IO column tax (tax_cells_s13.csv.gz, energy_tax_placed_s13.csv).', rule=V['tax_rates'])
    mv = placed[placed['how'].str.startswith('column product-tax total moved')]
    mvr = (mv['total_musd'] - mv['tls_musd']).groupby(mv['region']).sum().sort_values(key=abs, ascending=False) if len(mv) else pd.Series(dtype=float)
    S.check('S13-Rtaxmove', 'Fix list A1: net product taxes at the prior less io_s12 TLS, by region (USD bn; the energy rates are held, so a column total '
            'moves where the excise exceeds the IO column tax; GDP is held by the C, G and I targets, so value added moves the other way in the fit, ch.17A)',
            'report', f'{bn(mvr.sum()):.2f} bn in {len(mvr)} regions', '', True, V['tax_rates'],
            '; '.join(f'{k} {bn(v):+.2f}' for k, v in mvr.head(40).items()))
    PT = pd.DataFrame(pt_rows, columns=['region', 'c_vat', 'excise_musd', 'excise_rate', 'energy_excise_musd', 'columns', 'capped_columns',
                                        'uniform_musd', 'ras_iter', 'ras_gap', 'controlled'])
    if V['non_energy_rates'] != 'one_general_rate_per_column':
        hh = cells[cells['column'] == 'p'].set_index(['region', 'commodity'])['tls_rate']
        big = [r for r in ('USA', 'CHN', 'JPN', 'DEU', 'GBR', 'FRA', 'IND', 'ITA', 'BRA', 'CAN') if r in set(PT['region'])]
        S.check('S13-Rptpattern', 'QA round 2 P1 (non_energy_rates): columns whose general part is placed on the commodities by the S10 VAT and excise '
                'layers (column totals unchanged), the Eurostat RAS gap, and household rates on fbt, tal, rle and hea in the large economies', 'report',
                f"{int(PT['columns'].sum())} columns in {len(PT)} regions; {int(PT['controlled'].sum())} with a Eurostat control, largest RAS gap "
                f"{PT['ras_gap'].max() if len(PT) else 0:.2e}", '', True, V['non_energy_rates'],
                '; '.join(f"{r} " + ' '.join(f"{c} {hh.get((r, c), 0.0):.3f}" for c in ('fbt', 'tal', 'rle', 'hea')) for r in big))
    if tls_energy is not None:
        S.check('S13-Renergyrates', 'Fix list A1 (GTAP 12 ch.12 §12.4.4): energy rates converted from the S10 specific rates at the S11 basic prices; '
                'cells with no S11 price or base, and rates at or below -100% set to zero as unknown (ch.12 §12.3.3)', 'report',
                f'{len(tls_energy)} cells; {len(energy_notes)} notes', '', True, V['tax_rates'], '; '.join(energy_notes)[:1500])
        for note in energy_notes:
            S.flag('ENERGY-RATE-NOTE', 'TLS', note, rule=V['tax_rates'])
        rv = K.energy_revenue_compare(tls_energy, spec10, fitted=io13 if len(io13) else None)
        rvc = rv.groupby('commodity')[['implied_musd', 'fitted_musd', 'source_musd']].sum()
        S.check('S13-Renergyrev', 'Fix list A1, Fable QA F-04: energy taxes of the held ad valorem rates on the io_s12 basic flows and on the fitted flows, '
                'against the S10 source revenue, source regions (USD bn: io_s12 / fitted vs source)', 'report',
                '; '.join(f'{c} {bn(x.implied_musd):.1f} / {bn(x.fitted_musd):.1f} vs {bn(x.source_musd):.1f}' for c, x in rvc.iterrows()), '', True, V['tax_rates'],
                '; '.join(f'{x.region} {x.commodity} {bn(x.implied_musd):.2f} / {bn(x.fitted_musd):.2f} vs {bn(x.source_musd):.2f}' for x in
                          rv.assign(d=(rv['fitted_musd'] - rv['source_musd']).abs()).sort_values('d', ascending=False).head(30).itertuples()))
        if erev is not None:
            S.write('energy_tax_revenue_s13.csv', erev.round(9))
            S.check('S13-Renergyscale', f'Fable QA F-04 (energy_tax_revenue): source regions\' energy-tax rates scaled by row to the S10 revenue on the S11-valued rows '
                    f'before the fit (GTAP 12 ch.8 Appendix A; factor within [1/{M.ENERGY_REVENUE_BOUND:g}, {M.ENERGY_REVENUE_BOUND:g}]); rows at the bound or kept', 'report',
                    f'{len(erev)} rows; median factor {erev["scale"].median():.3f}; {len(erev_notes)} noted', '', True, 'energy_tax_revenue',
                    '; '.join(erev_notes)[:1500])
            # beta v4 dry run 3 (S16 2026-10-26): the hard test is the pre-fit identity GTAP 12 ch.8 Appendix A sets, the scaled rates
            # times the S11-valued row = the S10 source money (the P34 base error, BFA ely, shows here); after the fit ch.17A holds
            # the rates and the money follows the fitted flows, so the fitted money against the source is reported
            n_ep, d_ep = K.energy_revenue_prefit(erev, M.output_targets(V['energy_targets']))
            S.check('S13-Henergyrev', 'Beta v4 P34: every source region\'s energy row whose rates were scaled freely (not at the bound, not kept) on a held row '
                    'books its S10 source money on the S11-valued row before the fit (1e-6 relative; GTAP 12 ch.8 Appendix A)', 'hard', n_ep, 0, n_ep == 0,
                    'energy_tax_revenue', d_ep)
            n_er, d_er, nc_er = K.energy_revenue_held(rv, erev, M.output_targets(V['energy_targets']))
            S.check('S13-Renergyrevfit', 'Beta v4 P34 after the fit: freely scaled rows on held rows whose money on the fitted flows is more than 5% from the S10 '
                    'source (ch.17A holds the rates, so the money follows the fitted users; report)', 'report', n_er, 0, True,
                    'energy_tax_revenue', d_er or (f'{len(erev) - len(nc_er)} rows checked; not checked (at the bound, kept or not held): '
                                                   + '; '.join(f'{x.region} {x.commodity}' for x in nc_er.head(40).itertuples())))
        lp = K.low_power_energy(cells)
        S.check('S13-Rlowpower', 'Beta v4 P34: energy cells with a price power (1 + net product-tax rate) below 0.5', 'report', len(lp), 0, True, V['tax_rates'],
                '; '.join(f'{x.region} {x.commodity}>{x.column} {1.0 + x.tls_rate:.3f}' for x in lp.head(40).itertuples()) or 'none')
    XR = pd.DataFrame(extreme_rows, columns=K.EXTREME_COLUMNS)
    xr = XR[XR['region'].isin(fitted)] if len(XR) else XR
    S.check('S13-Rextreme', f'GTAP 12 ch.17B (finding #12): cells whose net product-tax rate is at or above {K.EXTREME_TAX:.0%} or at or below {K.EXTREME_SUBSIDY:.0%}, and those on a fitted '
            f'basic flow below {K.SMALL_FLOW_MUSD} USD m. ch.17B adjusts firms\' purchases to remove very large subsidies on extremely small flows but states '
            'no threshold, so no trim is applied (report only; energy_tax_extremes_s13.csv)', 'report',
            f"{len(xr)} cells, {int((xr['basic_fit_musd'] < K.SMALL_FLOW_MUSD).sum()) if len(xr) else 0} on small flows", '', True, V['tax_rates'],
            '; '.join(f'{x.region} {x.row}>{x.column} {x.rate:+.2f} on {x.basic_fit_musd:.2f}' for x in xr.sort_values('rate', key=abs, ascending=False).head(40).itertuples())
            if len(xr) else 'none')
    e12 = fac12.groupby(['region', 'sector', 'factor'])['evfp'].sum().reset_index()
    e12['share'] = e12['evfp'] / e12.groupby(['region', 'sector'])['evfp'].transform('sum')
    keep = e12.groupby(['region', 'sector'])['evfp'].transform('sum') > 0
    n, det = K.factor_shares(io_f, sectors, e12[keep], world_sh)
    S.check('S13-Hshares', 'Each factor\'s share of an activity\'s VA equals its S12 share (a new activity: the S12 world composition of its sector)', 'hard', n, 0, n == 0, 'PLAN §3(i) constraint 9; eq. 17.27', det)
    n, det = K.signs(io_f, sectors, held_neg)
    S.check('S13-Hsign', 'Purchases, trade, output and factor payments are non-negative, except capital in held negative-VA cells (none while prior_without_va replaces them)', 'hard', n, 0, n == 0, 'PLAN §3(i) sign-preserving', det)
    n, det = K.structural_zeros(io_f, sectors, prior_zero)
    S.check('S13-Hzeros', 'No purchase is created where the prior (after cleaning and smears) is zero', 'hard', n, 0, n == 0, 'PLAN §3(i) structural zeros kept', det)
    n, det = K.no_plug_columns(io_f, sectors)
    S.check('S13-Hcolumns', 'io_s13 has the GTAP columns only: no stock, gap or slack column', 'hard', n, 0, n == 0, 'PLAN §3(i) no plugs', det)
    n, det = K.factors_match_io(fac13, io_f, sectors)
    S.check('S13-Hfactors', 'factors_s13 EVFP equals the io_s13 EVFP rows; EVFB = EVFP - ftax and EVOS = EVFB - itax', 'hard', n, 0, n == 0, 'ch.15', det)

    # report-only: fit report, ICIO gate, support, world consistency
    moves, gate = [], []
    agents = list(sectors) + list(FD)
    for reg in fitted:
        a = io[(io['region'] == reg)].set_index('row')
        b = io13[io13['region'] == reg].set_index('row')
        for prefix in ('dom', 'imp'):
            rows = [f'{prefix}_{c}' for c in sectors]
            A = a.loc[rows, agents].to_numpy(float)
            B = b.loc[rows, agents].to_numpy(float)
            for i, j in zip(*np.where((np.abs(B - A) > 0) & (np.maximum(np.abs(A), np.abs(B)) >= MOVE_MUSD))):
                rel = (B[i, j] - A[i, j]) / A[i, j] if A[i, j] != 0 else np.inf
                if abs(rel) > MOVE_REL:
                    moves.append(dict(region=reg, row=rows[i], column=agents[j], s12_musd=A[i, j], s13_musd=B[i, j], change_musd=B[i, j] - A[i, j], relative=rel))
        if R_.loc[reg, 'icio_measured'] == 'yes':
            rows = [f'dom_{c}' for c in sectors] + [f'imp_{c}' for c in sectors]
            A = a.loc[rows, sectors].to_numpy(float)
            B = b.loc[rows, sectors].to_numpy(float)
            o12, o13 = a.loc['OUT', sectors].to_numpy(float), b.loc['OUT', sectors].to_numpy(float)
            scale = np.where(o12 > 0, o13 / np.where(o12 > 0, o12, 1.0), 1.0)
            As = A * scale[None, :]            # the io_s12 cells scaled with their column's output
            gate.append(dict(region=reg, intermediate_s12_musd=A.sum(), abs_change_musd=np.abs(B - A).sum(), share=np.abs(B - A).sum() / A.sum(),
                             scale_part_musd=np.abs(As - A).sum(), composition_part_musd=np.abs(B - As).sum()))
    moves = pd.DataFrame(moves, columns=['region', 'row', 'column', 's12_musd', 's13_musd', 'change_musd', 'relative'])
    gate = pd.DataFrame(gate, columns=['region', 'intermediate_s12_musd', 'abs_change_musd', 'share', 'scale_part_musd', 'composition_part_musd'])
    over = gate[gate['share'] > ICIO_GATE].sort_values('share', ascending=False)
    S.check('S13-Ricio', f'ICIO economies: total absolute change in intermediate cells against io_s12, over io_s12 intermediate use (PLAN gate {ICIO_GATE:.0%}, report-only)',
            'report', f'{len(over)} of {len(gate)} above {ICIO_GATE:.0%}; median {gate["share"].median():.1%}' if len(gate) else 'no ICIO region fitted', 0, True,
            'icio_gate; PLAN §3(i) fit-report gates',
            (f'Of the total change {bn(gate["abs_change_musd"].sum()):.1f} bn, {bn(gate["scale_part_musd"].sum()):.1f} bn is the io_s12 cells scaled with '
             f'their column\'s output and {bn(gate["composition_part_musd"].sum()):.1f} bn the change in cost shares (the two parts need not add up). ' if len(gate) else '') +
            '; '.join(f'{x.region} {x.share:.1%}' for x in over.itertuples()))
    big = moves[moves['relative'].abs() > MOVE_REL]
    S.check('S13-Rmoves', f'Cells that moved more than {MOVE_REL:.0%} with a value of at least {MOVE_MUSD:.0f} USD million (fit report)', 'report',
            len(big), '', True, 'PLAN §3(i) outputs', f'total absolute change {bn(big["change_musd"].abs().sum()):.1f} bn')
    sr = pd.DataFrame(supp_rows)
    if len(sr):
        S.check('S13-Rsupport', 'Farm support booked as GTAP rates (USD bn at fitted values; S10 values in brackets)', 'report',
                f'input {bn(sr["pse_input_booked_musd"].sum()):.1f} ({bn(sr["pse_input_s10_musd"].sum()):.1f}); '
                f'output {bn(sr["pse_output_booked_musd"].sum()):.1f} ({bn(sr["pse_output_s10_musd"].sum()):.1f})', '', True, 'farm_support (David 2026-10-23)',
                'Overlap with ICIO net product taxes on crp is not removed; see IMPROVEMENTS_LOG S13.')
    tw = trade.groupby('sector')[['XFOB', 'MCIF']].sum()
    S.check('S13-Rworld', 'World totals: exports FOB, imports CIF and VST (USD bn; FOB and CIF differ by margins)', 'report',
            f'FOB {bn(tw["XFOB"].sum()):.1f}; CIF {bn(tw["MCIF"].sum()):.1f}; VST {bn(trade["VST"].sum()):.1f}', '', True, 'PLAN §3(i) global pass')
    non_icio = mt.loc[[r for r in regs if R_.loc[r, 'icio_measured'] != 'yes'], 'GDP_musd'].sum()
    S.check('S13-Rrow', 'Non-ICIO regions: S02 GDP total (the ICIO ROW block is not imposed; GTAP has no ROW constraint)', 'report',
            f'{bn(non_icio):.1f} bn', '', True, 'row_block')
    S.check('S13-Rinfo', 'Total GTAP information I over fitted regions (USD million, eq. 17.4 unit weights)', 'report',
            f'{fit["information_musd"].sum():.1f}', '', True, 'objective')
    g12 = pd.DataFrame(io12_gap).sum() if io12_gap else pd.Series(dict(column=0.0, row=0.0))
    S.check('S13-Rio12gap', 'io_s12 is not exactly balanced: total absolute gap between output and column cost, and between output and row sales (absorbed by the fit; eq. 17.22 and 17.28)', 'report',
            f'columns {bn(g12["column"]):.1f} bn; rows {bn(g12["row"]):.1f} bn', '', True, 'S12 io_s12')
    # fix round wC (independent QA MEDIUM-3): own-use (diagonal) shares at agents' prices, prior against fit
    OU = pd.DataFrame(own_rows, columns=K.OWN_USE_COLUMNS)
    if held_own or own_hold_rows:
        n, det = K.own_use_held(own_rows)
        S.check('S13-Hownuse', f"Own-use shares (choice own_use_share = {V['own_use_share']}; own_use_cap second pass): in every held activity the own "
                'good\'s domestic plus imported purchases keep their prior share of the column at agents\' prices (1e-8; an analogue of GTAP\'s IEA '
                'energy use of the energy activities, ch.17A eq. 17.8-17.9)', 'hard', n, 0, n == 0, 'own_use_share; own_use_cap',
                det or f"{int(OU['held'].sum())} columns held; own use {bn(OU.loc[OU['held'], 'fitted_own_musd'].sum()):.1f} bn fitted, "
                       f"{bn(OU.loc[OU['held'], 'prior_own_musd'].sum()):.1f} bn prior (agents' prices)")
    om = K.own_use_moves(own_rows)
    S.check('S13-Rownuse', f'Own-use (diagonal) cells of {K.OWN_USE_REPORT_MUSD / 1000:.0f} bn or more whose share of the column moved by more than '
            f'{K.OWN_USE_REPORT_PP * 100:.0f} points, prior to fit at agents\' prices (GTAP\'s cross-entropy moves a diagonal only with '
            'the priced rows of its column; output is demand from others over 1 - diagonal coefficient; own_use_s13.csv; report)', 'report', len(om), '', True, 'own_use_share',
            '; '.join(f"{x['region']} {x['sector']} {x['prior_share']:.1%}>{x['fitted_share']:.1%} ({bn(x['prior_own_musd']):.1f}>{bn(x['fitted_own_musd']):.1f} bn)"
                      for x in om[:30]) or 'none')
    nf, vf = K.smear_fill(io_f, sectors, presmear_zero)
    S.check('S13-Rsmearfill', 'Purchase cells the smears create: cells that are zero in the prior before smearing and positive after the fit (count and USD bn)', 'report',
            f'{nf} cells; {bn(vf):.1f} bn', '', True, 'energy_smear')

    tracked = subprocess.run(['git', '-C', BUILD, 'ls-files', '--full-name', ROOT.rsplit('/', 1)[0]], capture_output=True, text=True).stdout.split()
    priv = private_paths(tracked)
    S.check('S13-Hprivate', 'No private file (credentials, GTAP database values) is tracked in git (lib/private_files.py)', 'hard',
            len(priv), 0, not priv, 'repo_rules committed_data_rule', ' '.join(priv[:10]))
    sec = secret_scan([BUILD + '/s13_fit.py', BUILD + '/s13_fit', BUILD + '/screens/s13_suite.py', C.CONFIG_DIR, S.out])
    S.check('S13-Hsecret', 'Key and password scan of the S13 code, config and outputs (count only)', 'hard', sec, 0, sec == 0, 'never commit credentials')

    # ------------------------------------------------------------- screens
    prev_out = os.environ.get('S13_PREV_OUTPUT')
    ctx = dict(io13=io13, io12=io, sectors=sectors, mt=mt, fit=fit, gate=gate, moves=moves, status=pd.DataFrame(status_rows),
               smears=pd.DataFrame(smears), comps=comps, held_neg=held_neg, tout=tout,
               fuel={(x['region'], x['commodity']): x['booked_fitted_musd'] for x in sub_rows if x['status'] == 'booked'}, trade=trade, rates=rates, fac13=fac13,
               prev=pd.read_csv(prev_out + '/io_s13.csv.gz') if prev_out else None)
    try:
        # an analysis run (S13_ANALYSIS_*) writes its screen report inside its own stage folder, never to dataset/reviews
        if an_choices or an_regions:
            os.makedirs(S.dir + '/screens', exist_ok=True)
        scr = SCR.run(ctx, log=S.log, **({'report_dir': S.dir + '/screens'} if (an_choices or an_regions) else {}), explained=('benchmark', 'outlier') if V['screen_outliers'] == 'explanation_row_required' else ('benchmark',))
        S.check('S13-Hscreens', 'Population screens (SCREENS.md seven questions): no material unexplained hit', 'hard',
                scr['material_unexplained'], 0, scr['material_unexplained'] == 0, 'screen_materiality', scr['summary'])
    except Exception as e:   # a screen that raises fails the stage
        S.check('S13-Hscreens', 'Population screens ran', 'hard', repr(e)[:200], 'no exception', False, 'screen_materiality')
        raise

    # ------------------------------------------------------------- outputs
    def gzcsv(name, df):
        """gzip with mtime 0, so two runs give the same bytes (the S11 pattern)."""
        with gzip.GzipFile(f'{S.out}/{name}', 'wb', mtime=0) as fh:
            fh.write(df.to_csv(index=False).encode())
        S.log(f'output {name}: {len(df)} rows')

    num = [c for c in io13.columns if c not in ('region', 'row')]
    out13 = io13.copy()
    out13[num] = out13[num].round(6)
    gzcsv('io_s13.csv.gz', out13)
    f13 = fac13.copy()
    for c in ('evfp', 'ftax', 'evfb', 'itax', 'fbep', 'evos'):
        f13[c] = f13[c].round(6)
    gzcsv('factors_s13.csv.gz', f13.sort_values(['region', 'sector', 'factor']).reset_index(drop=True))
    gzcsv('trade_s13.csv.gz', trade.round(6))
    S.write('macro_s13.csv', mt.reset_index().round(6))
    S.write('fit_report_s13.csv', fit.round(12))
    top = moves.assign(a=moves['relative'].abs()).sort_values(['a', 'change_musd'], ascending=False).drop(columns='a')
    S.write('fit_moves_s13.csv', top.round(6))
    S.write('fit_top_moves_s13.csv', pd.concat([g.head(TOP_MOVES) for _, g in top.groupby('region', sort=True)]).round(6) if len(top) else top)
    S.write('icio_gate_s13.csv', gate.round(9))
    S.write('smears_s13.csv', pd.DataFrame(smears, columns=['region', 'item', 'how', 'value_musd']).round(6))
    S.write('activity_status_s13.csv', pd.DataFrame(status_rows, columns=['region', 'sector', 'status']))
    # the energy output targets this fit used (S11 targets after the beta v4 P1 ely floor and P38): S14 rebuilds the held
    # trade from them (S14-Htravel, S14-Hmerge); full precision, not rounded
    S.write('energy_targets_s13.csv', pd.DataFrame([(r, c, v) for (r, c), v in sorted(tout.items())],
                                                   columns=['region', 'commodity', 'output_value']))
    S.write('tax_rates_s13.csv', rates.round(12))
    gzcsv('tax_cells_s13.csv.gz', cells.round(12))
    S.write('energy_tax_placed_s13.csv', placed.round(12))
    if V['non_energy_rates'] != 'one_general_rate_per_column':
        S.write('product_tax_pattern_s13.csv', PT.round(12))
    if tls_energy is not None:
        S.write('energy_tax_rates_s13.csv', tls_energy.round(12))
    S.write('energy_tax_extremes_s13.csv', xr.round(9) if len(xr) else pd.DataFrame(columns=K.EXTREME_COLUMNS))
    S.write('fuel_subsidies_s13.csv', pd.DataFrame(sub_rows, columns=['region', 'commodity', 's11_subsidy_musd', 'neer_subsidy_musd', 'to_book_musd', 'kind',
                                                                       'rho', 'basis', 'status', 'booked_prior_musd', 'booked_fitted_musd', 'money_held', 'capped_musd', 'capped_fit_musd']).round(9))
    S.write('fuel_subsidy_columns_s13.csv', pd.DataFrame(K.fuel_subsidy_columns(io13, sub_rows, sectors, sub_mask) if len(io13) else [],
                                                        columns=['region', 'commodity', 'column', 'rate', 'basic_musd', 'subsidy_musd']).round(9))
    S.write('support_s13.csv', sr.round(6))
    S.write('own_use_s13.csv', OU.round(9))
    S.write('own_use_caps_s13.csv', OC.round(9))
    S.write('own_use_held_s13.csv', OH.round(9))
    S.write('own_use_dropped_s13.csv', OD)
    S.write('pse_input_items_s13.csv', PI.round(9))
    S.write('product_tax_s13.csv', PX.round(9))
    S.write('product_tax_regions_s13.csv', PXR.round(9))
    if PSRC is not None:
        S.write('product_tax_source_s13.csv', PSX.round(9))
    S.write('factor_income_gdp_s13.csv', FG.round(9))
    S.write('travel_dropped_s13.csv', dropped.rename(columns={'exporter': 'host', 'importer': 'visitor', 'v': 'musd'}).round(9))
    with open(S.out + '/NOT_FOR_PUBLICATION.md', 'w') as f:
        f.write('# Not for publication\n\nio_s13.csv.gz and factors_s13.csv.gz carry the S10 tariff wedge (TRAINS-derived) through io_s12. '
                'Keep them out of any public release, as for S10 to S12.\n')
    S.finish()


if __name__ == '__main__':
    main()
