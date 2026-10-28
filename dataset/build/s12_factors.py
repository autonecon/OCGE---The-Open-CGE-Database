#!/usr/bin/env python3
"""S12 factor shares and labour (GTAP 12 ch.14A, ch.14B, ch.15).

The method is in the s12_factors package; this file declares the inputs, runs the steps in the GTAP
order and turns every result into a check, a flag, a ledger row or an output file.

1. Labour and capital in value added (the I-O split; Aguiar et al. 2025 p.8): compensation of
   employees over factor income by industry from FIGARO 2022, else OECD Table 6; else the ch.9D donor.
   Non-ICIO regions combine their S05 donors unless a member has its own split. Fix round 2026-10-24:
   other net production taxes (D29X39) come out of VA by industry (A3); the part that is GFS payroll and
   property tax is a factor-use tax on all factors at one rate (ch.15 pp.2-3, fix round w13) and the rest an
   output tax (io_s12 row OTAX); a FIGARO parent code is
   split by the economy's own Table 6 divisions and an imputed-uniform block by a donor pattern (A5,
   Grok-F2); the self-employed get the employees' wage (Gollin 2002, A5); every non-hhe cell keeps at
   least its consumption of fixed capital (A6).
2. Agriculture (ch.14A): land, labour and capital of crp from the USDA ERS Fuglie cost shares; the
   ch.14A p.2 SUR regression where a country has none; the KF outliers of ch.14A Table 14.2 (AUS, NZL, JPN, CAN,
   MEX) take the ch.14A Table 14.1 GTAP shares (fix worker wD; the w13 Table 14.16 SUR prediction is the alternative).
3. Natural resources (fix round B16, David's card 2026-10-24; GTAP 7 ch.12.A, GTAP 12 ch.17B §B.1): in for, fsh,
   coa, oil, gas, ore, min and msp the natural-resource share is the one that gives ch.12.A's target supply
   elasticity, eta = sigma_VA (1/theta_R - 1/theta_VA), taken out of all value added (labour and capital pro rata);
   msp blends the fossil-fuel target (its ISIC 0910 part, GTAP oil and gas) and the other-mining target (w13).
   The alternative (config natres_rule) is the A7 WDI rent rule: WDI 2021 rents x S02 GDP, capped at net
   operating surplus.
4. Labour groups (ch.14B eqs. 14.1-14.4): ILOSTAT employment and earnings, wage calibration, payment
   shares by ISIC section; F16c regional averages where a country has no adequate window.
5. Income and factor taxes (ch.15): S10 rates applied to the factor cells; factor-based PSE support as a
   factor-use subsidy (A4). EVFP, EVFB, EVOS.

io_s12 is io_s11 with the VA row replaced by the eight factor rows at EVFP and the output tax row OTAX
(they add up to VA).
Choices come from config/s12/s12_choices.csv (s12_factors/config.py).
"""
import gzip
import os
import subprocess
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.stagekit import Stage, ROOT, DATA, BUILD, STAGES, BASE_YEAR  # noqa: E402
from lib.private_files import private_paths  # noqa: E402
from s12_factors import config as C  # noqa: E402
from s12_factors import sources as SRC  # noqa: E402
from s12_factors import method as M  # noqa: E402
from s12_factors import labour as LAB  # noqa: E402
from s12_factors import national as NL  # noqa: E402
from s12_factors import checks as K  # noqa: E402
from s12_factors.method import LABOUR5, FACTORS, SKILLED, SECTIONS  # noqa: E402
import screens.s12_suite as SCR  # noqa: E402

UP = {
    'S01': STAGES + '/S01_sets_registry',
    'S02': STAGES + '/S02_macro',
    'S05': STAGES + '/S05_composite',
    'S10': STAGES + '/S10_tariffs_taxes',
    'S11': STAGES + '/S11_energy',
}
GEO15 = {'CARB': 'LMAR', 'CAMR': 'LMAR', 'SAMR': 'LMAR', 'EAFR': 'SSAF', 'CAFR': 'SSAF', 'WAFR': 'SSAF', 'SAFR': 'SSAF'}
ALIAS = {'PSE': 'PAL', 'XKX': 'KSV'}
RENT_SERIES = {'oil': 'NY.GDP.PETR.RT.ZS', 'gas': 'NY.GDP.NGAS.RT.ZS', 'coa': 'NY.GDP.COAL.RT.ZS',
               'mineral': 'NY.GDP.MINR.RT.ZS', 'for': 'NY.GDP.FRST.RT.ZS'}
NATRES_SECTORS = ('coa', 'oil', 'gas', 'ore', 'min', 'msp', 'for', 'fsh')
TOL = 1e-6
MAX_MISSING = 5          # a source covering all but this many sectors is used, the rest filled (config partial_source)


def bn(x):
    return x / 1000.0


def main():
    choices = C.load_choices()
    V = {k: r['value'] for k, r in choices.items()}
    S = Stage('S12', 'factors')
    I = S.inp
    S.check('S12-Hconfig', f'config/s12/s12_choices.csv has the {len(C.CHOICES)} choices this code implements, each with decided_by and decided_at',
            'hard', len(choices), len(C.CHOICES), len(choices) == len(C.CHOICES), 's12_choices',
            'Departures and choices not in the GTAP text: ' + ', '.join(k for k, r in choices.items() if r['gtap_status'] in ('departure_logged', 'not_in_gtap_text')))
    for k in UP.values():
        S.upstream(k)
    I(C.CHOICES_PATH, 'S12 choices')

    # ------------------------------------------------------------- inputs
    regions = pd.read_csv(I(UP['S01'] + '/output/regions.csv', 'S01 regions'))
    cmap = pd.read_csv(I(UP['S01'] + '/output/country_region_map.csv', 'S01 country map'))
    sectors = pd.read_csv(I(UP['S01'] + '/output/sectors.csv', 'S01 sectors'))['sector'].tolist()
    concord = pd.read_csv(I(UP['S01'] + '/output/concord_isic4_to_sector.csv', 'S01 ISIC to sector'), dtype=str)
    isco = pd.read_csv(I(UP['S01'] + '/output/labour_isco_groups.csv', 'S01 ISCO groups (Table 14.18)'))
    macro = pd.read_csv(I(UP['S02'] + '/output/macro_country.csv', 'S02 country GDP and population'))
    vdep_on = V['labour_definition'] == 'd1_plus_gollin_self_employed_at_employee_wage' and V['capital_vdep_floor'] == C.VDEP_FLOOR
    if vdep_on:
        vdep = pd.read_csv(I(UP['S02'] + '/output/macro_regions.csv', 'S02 VDEP (capital-income floor)')).set_index('region')['VDEP_musd']
    dw = pd.read_csv(I(UP['S05'] + '/output/donor_weights.csv', 'S05 donors and member weights'))
    ftr = pd.read_csv(I(UP['S10'] + '/output/factor_tax_rates_s10.csv', 'S10 income and factor taxes'))
    sup = pd.read_csv(I(UP['S10'] + '/output/support_s10.csv', 'S10 domestic support'))
    io = pd.read_csv(I(UP['S11'] + '/output/io_s11.csv.gz', 'io_s11'))
    evs = pd.read_csv(I(UP['S11'] + '/output/energy_values_s11.csv', 'S11 energy output values (S13 targets)'))

    fig_file = {2022: 'figaro_va_2022.json', 2017: 'figaro_va_2017.json'}[BASE_YEAR]
    fig = SRC.figaro_va(I(f'{DATA}/figaro_va/{fig_file}', 'Eurostat FIGARO value-added rows (D1, B2A3G, D29X39)'), BASE_YEAR)
    t6_path = I(DATA + '/oecd_na_table6/oecd_table6_activity_2017_2022.csv.gz', 'OECD Table 6 by activity')
    t6, t6tot, t6_derived = SRC.oecd_table6(t6_path, BASE_YEAR)
    t6all = SRC.oecd_table6_all(t6_path, BASE_YEAR)
    t6cfc = SRC.oecd_table6_cfc(I(DATA + '/oecd_na_table6/oecd_table6_p51c_2017_2022.csv.gz', 'OECD Table 6 consumption of fixed capital (P51C)'),
                                t6_path, BASE_YEAR)
    fig_prev = None
    if BASE_YEAR == 2022:      # the latest earlier FIGARO year in the repo, for screen 3 only
        fig_prev = SRC.figaro_va(I(f'{DATA}/figaro_va/figaro_va_2017.json', 'FIGARO 2017 (screen 3: year jumps)'), 2017)
    ilo = DATA + '/ilostat/'
    occ = SRC.ilostat(I(ilo + 'EMP_TEMP_SEX_OCU_NB_A.csv.gz', 'ILOSTAT employment by occupation'), 'OCU_ISCO')
    ind = SRC.ilostat(I(ilo + 'EMP_TEMP_SEX_ECO_NB_A.csv.gz', 'ILOSTAT employment by economic activity'), 'ECO_ISIC4')
    wocc = SRC.ilostat(I(ilo + 'EAR_EMTA_SEX_OCU_CUR_NB_A.csv.gz', 'ILOSTAT earnings by occupation'), 'OCU_ISCO', usd=True)
    wind = SRC.ilostat(I(ilo + 'EAR_EMTA_SEX_ECO_CUR_NB_A.csv.gz', 'ILOSTAT earnings by economic activity'), 'ECO_ISIC4', usd=True)
    cross = None
    if V['labour_matrix'].startswith('observed'):
        cross = SRC.ilostat_cross(I(ilo + 'EMP_TEMP_SEX_OCU_EC2_NB_A.csv.gz', 'ILOSTAT occupation x activity'))
    kf = pd.read_csv(I(DATA + '/usda_ers/usda_ag_cost_shares.csv', 'USDA ERS Fuglie agricultural cost shares'))
    natres_gtap = V['natres_rule'] == 'gtap_ch12a_target_supply_elasticity_share_out_of_all_va'
    NT = C.load_natres_targets(I(C.NATRES_TARGETS_PATH, 'S12 natural-resource target elasticities and sigma_VA (ch.12.A, ch.16)'))
    theta_floor = C.NATRES_GUARD_FLOOR[V['natres_guard']]
    if natres_gtap and V['fishing_natres'] == 'zero_flagged_no_flow_source':
        NT = {k: v for k, v in NT.items() if k != 'fsh'}
    rents = {} if natres_gtap else {k: SRC.wb_series(I(f'{DATA}/wdi_rents_2021/{s}.json', f'WDI {s}')) for k, s in RENT_SERIES.items()}
    arable = SRC.wb_series(I(DATA + '/wdi_ag_2022/AG.LND.ARBL.HA.PC.json', 'WDI arable land per person'))
    gdppc_wb = SRC.wb_series(I(DATA + '/wdi_ag_2022/NY.GDP.PCAP.CD.json', 'WDI GDP per capita, current USD'))
    pwt = pd.read_csv(I(DATA + '/pwt/pwt110_ky_labsh.csv', 'PWT 11.0 labsh (report-only benchmark)'))
    a3 = V['other_production_taxes'].startswith('d29x39_out_of_va')
    ch15 = a3 and V['payroll_property'] == C.PAYROLL_CH15
    msp_blend = natres_gtap and V['msp_natres_target'] == C.MSP_BLEND
    gollin_on = V['labour_definition'] == 'd1_plus_gollin_self_employed_at_employee_wage'
    ilo_on = gollin_on and V['gollin_ilo_cap'] == C.GOLLIN_ILO_CAP
    ilo_share = {}
    if ilo_on:      # beta v4 G2/P40: ILO SDG 10.4.1 labour income share of GDP, latest year at or before the base year
        lis = pd.read_csv(I(ilo + 'LAP_2GDP_NOC_RT_A.csv.gz', 'ILOSTAT SDG 10.4.1 labour income share of GDP (gollin_ilo_cap)'))
        lis = lis[lis['time'].astype(int) <= BASE_YEAR].sort_values('time')
        ilo_share = (lis.groupby('ref_area')['obs_value'].last() / 100.0).to_dict()
    floor_on = V['labour_share_bounds'] != 'clip_to_0_1_ledger'
    d1_min = floor_on and V['labour_at_least_d1'] == C.LABOUR_AT_LEAST_D1
    t6cfi = SRC.oecd_table6_cfc_fi(I(DATA + '/oecd_na_table6/oecd_table6_p51c_2017_2022.csv.gz', 'OECD Table 6 P51C (capital floor, A6)'),
                                   t6_path, BASE_YEAR)
    grs = SRC.grs_payroll(I(DATA + '/oecd_grs/grs_rsglobal_2017_2022.csv', 'OECD GRS T_3000 and T_4000 (payroll part of D29, A3)'), BASE_YEAR)
    ste = SRC.ilostat_status(I(ilo + 'EMP_TEMP_SEX_STE_ECO_NB_A.csv.gz', 'ILOSTAT employment by status and activity (Gollin, A5)'), BASE_YEAR)
    pink = None if natres_gtap else SRC.pinksheet_annual(I(DATA + '/wb_pinksheet/CMO-Historical-Data-Annual.xlsx', 'World Bank Pink Sheet (2022 rent prices, A7)'),
                                                          ('Crude oil, average', 'Natural gas, US', 'Natural gas, Europe', 'Liquefied natural gas, Japan'))

    for d in [fig, t6, t6tot, t6all, t6cfc, t6cfi, occ, ind, wocc, wind, ste, *rents.values(), arable, gdppc_wb] + ([fig_prev] if fig_prev is not None else []):
        d['iso3'] = d['iso3'].replace(ALIAS)
    if cross is not None:
        cross['iso3'] = cross['iso3'].replace(ALIAS)
    grs = {ALIAS.get(k, k): v for k, v in grs.items()}
    section_divs, sector_divs = M.section_divisions(concord)
    # fix worker wF (QA round 2 P2, P6): the national-source economies are those whose activity D29X39 is the economy's own
    # supply-use or national accounts table: the EU members' FIGARO rows (Eurostat compiles them from the members' SUTs)
    # and the OECD Table 6 economies outside FIGARO (the USA is on BEA below). A FIGARO economy outside the EU is a
    # FIGARO estimate (GTAP 12 ch.8 takes net production taxes from the contributed national I-O table instead).
    fig_codes = set(fig['iso3'])
    nat_src = sorted([c for c in fig_codes if c in C.EU27] + [c for c in set(t6['iso3']) if c not in fig_codes])
    fig_est = {c for c in fig_codes if c not in C.EU27}
    d29_ref = {}
    if a3:
        ref_taus = {s_: [] for s_ in sectors}
        for c in nat_src:
            g = fig[fig['iso3'] == c] if c in fig_codes else t6[t6['iso3'] == c]
            for s_, x in M.labour_shares_from_na(g, sector_divs, section_divs, SRC.activity_divisions).items():
                if x['share'] is not None and not x['parent'] and x['d1'] + x['b2a3g'] + x['d29'] > 0:
                    ref_taus[s_].append(x['tau'])
        d29_ref = M.d29_reference(ref_taus)
    # fix worker wF (QA round 2 P6): listed FIGARO-estimated cells whose D29X39 share of VA is a balancing artefact
    # (JPN H52 warehousing +0.69 of VA against negative surplus, JPN H50 water transport -0.65, AUS M69-M75 the 2021
    # COVID wage subsidies, ARG A01 +0.95 of VA against negative surplus, export duties inside). The national I-O
    # tables GTAP uses (ch.8: ABS, MIC Japan, INDEC) are not in dataset/data, so a documented rule: S10 export duties
    # taken out where listed, then a share still outside the national-source [p5, p95] of the sector takes the
    # national-source median (crp: 0, ch.11A). Applied to the FIGARO activities of the cell before the JPN national
    # total, so JPN still meets its national D29 less subsidies (S12-Hd29nat).
    d29cell_rows = []
    if a3 and V['d29_outlier_cells'] == C.D29_CELLS:
        cells_cfg = C.load_d29_cells(I(C.D29_CELLS_PATH, 'S12 listed FIGARO-estimated D29X39 cells (QA round 2 P6)'))
        xt = pd.read_csv(I(UP['S10'] + '/output/export_tax_s10.csv', 'S10 export taxes (export duties out of listed D29X39 cells)'))
        duty = xt.drop_duplicates(['exporter', 'sector']).set_index(['exporter', 'sector'])['duty_musd'].to_dict()
        va_io = io[io['row'] == 'VA'].set_index('region')[sectors]
        for (c, s_), cfg in sorted(cells_cfg.items()):
            if c not in fig_est or s_ not in sectors or s_ not in d29_ref or c not in va_io.index:
                raise SystemExit(f'd29_outlier_cells: {c} {s_} is not a FIGARO-estimated (non-EU) economy and sector with a reference and io VA')
            g = fig[fig['iso3'] == c]
            x = M.labour_shares_from_na(g, {s_: sector_divs[s_]}, section_divs, SRC.activity_divisions).get(s_)
            if x is None or x['parent']:
                raise SystemExit(f'd29_outlier_cells: {c} {s_} has no own FIGARO activity')
            v_io = float(va_io.loc[c, s_])
            dsh = float(duty.get((c, s_), 0.0)) / v_io if cfg['export_duty_out'] and v_io > 0 else 0.0
            new_t, rule_ = M.d29_cell_target(x['tau'], dsh, d29_ref[s_], s_ == 'crp')
            acts = x['activity'].split('+')
            for a_ in acts:
                ma = (fig['iso3'] == c) & (fig['activity'] == a_)
                d1_a = float(fig.loc[ma & (fig['item'] == 'D1'), 'value'].sum())
                b2_a = float(fig.loc[ma & (fig['item'] == 'B2A3G'), 'value'].sum())
                md = ma & (fig['item'] == 'D29X39')
                if md.sum() != 1:
                    raise SystemExit(f'd29_outlier_cells: {c} {a_} has {int(md.sum())} D29X39 rows')
                fig.loc[md, 'value'] = M.d29_for_share(d1_a, b2_a, new_t)
            lo_, med_, hi_ = d29_ref[s_]
            d29cell_rows.append(dict(iso3=c, sector=s_, activities=x['activity'], tau_source=x['tau'], export_duty_musd=float(duty.get((c, s_), 0.0)) if cfg['export_duty_out'] else 0.0,
                                     export_duty_share_of_io_va=dsh, ref_p5=lo_, ref_median=med_, ref_p95=hi_, tau_new=new_t, rule=rule_,
                                     n_reference=len(ref_taus[s_])))
            S.flag('D29-CELL-OUTLIER', f'{c} {s_}', f'{cfg["reason"]}. FIGARO {x["activity"]} D29X39 share of VA {x["tau"]:.3f}'
                   + (f', less S10 export duty {dsh:.3f} of io VA' if dsh else '')
                   + f'; national-source range [{lo_:.3f}, {hi_:.3f}] median {med_:.4f} ({len(ref_taus[s_])} economies): {rule_} {new_t:.4f}',
                   rule=V['d29_outlier_cells'])
    # fix worker wD: an economy whose activity-level D29X39 holds taxes on products (JPN: JSNA GVA by activity carries the
    # consumption tax and excises) is brought to its national D29 less D39 (OECD Table 14, the NSO sector accounts) by
    # scaling its positive FIGARO D29X39 cells by one factor; the labour share D1 / (D1 + B2A3G) does not change
    d29nat_rows = []
    if a3 and V['d29x39_national_total'] == C.D29_NATIONAL:
        t14 = SRC.oecd_table14_d29_net(I(DATA + '/oecd_nasec_table14/oecd_table14_d21_d29_d3_2017_2022.csv.gz',
                                         'OECD Table 14 D29 and subsidies (national D29X39 totals)'), BASE_YEAR)
        for c, why in sorted(C.load_d29_national(I(C.D29_NATIONAL_PATH, 'S12 economies with national D29X39 totals')).items()):
            m = (fig['iso3'] == c) & (fig['item'] == 'D29X39')
            d1_fig = float(fig.loc[(fig['iso3'] == c) & (fig['item'] == 'D1'), 'value'].sum())
            d1_nat = t6tot[(t6tot['iso3'] == c) & (t6tot['item'] == 'D1') & (t6tot['year'] == BASE_YEAR)]['value']
            nat = t14.get(c)
            if not m.any() or d1_fig <= 0 or d1_nat.empty or nat is None or np.isnan(nat['net']):
                raise SystemExit(f'{c}: d29x39_national_total needs FIGARO D29X39 and D1, Table 6 D1 and Table 14 D29 and subsidies for {BASE_YEAR}')
            conv = d1_fig / float(d1_nat.iloc[0])          # FIGARO EUR per national-currency unit, from the same D1
            before = float(fig.loc[m, 'value'].sum())
            new, k, pos, neg = M.scale_positive_d29(fig.loc[m, 'value'].values, nat['net'] * conv)
            fig.loc[m, 'value'] = new
            d29nat_rows.append(dict(iso3=c, d29_xdc=nat['d29'], subsidy_xdc=nat['sub'], subsidy_item=nat['sub_item'], net_xdc=nat['net'],
                                    eur_per_xdc=conv, figaro_d29x39_eur=before, figaro_positive_eur=pos, figaro_negative_eur=neg,
                                    positive_factor=k, d29x39_after_eur=float(new.sum())))
            S.flag('D29-NATIONAL-TOTAL', c, f'{why}. FIGARO D29X39 {before:.0f} m EUR (positive {pos:.0f}, negative {neg:.0f}) to national D29 less '
                   f'{nat["sub_item"]} {nat["net"]:.0f} m XDC = {nat["net"] * conv:.0f} m EUR: positive cells x {k:.4f}', rule=V['d29x39_national_total'])
        bad_n = [x['iso3'] for x in d29nat_rows if abs(x['d29x39_after_eur'] - x['net_xdc'] * x['eur_per_xdc']) > 1e-6 * max(1.0, abs(x['net_xdc'] * x['eur_per_xdc']))]
        S.check('S12-Hd29nat', 'Economies on national D29X39 totals: the source D29X39 after scaling equals national D29 less subsidies (OECD Table 14)',
                'hard', len(bad_n), 0, not bad_n, 'd29x39_national_total',
                '; '.join(f'{x["iso3"]} {x["figaro_d29x39_eur"]:.0f} -> {x["d29x39_after_eur"]:.0f} m EUR (factor {x["positive_factor"]:.4f})' for x in d29nat_rows))

    R = regions.set_index('region')
    icio = [r for r in R.index if R.loc[r, 'icio_measured'] == 'yes']
    va = io[io['row'] == 'VA'].set_index('region')[sectors]
    out_io = io[io['row'] == 'OUT'].set_index('region')[sectors]
    tgt = evs[evs['target'] == 'yes'].set_index(['region', 'commodity'])['output_value'].to_dict()
    # fix round w13: the ISIC 0910 (oil and gas support) part of msp, by the region's oil and gas share of extraction output
    # (coa, oil and gas at the S11 output values S13 imposes, ore and min at io_s11)
    msp_w = {}
    for r_ in out_io.index:
        ext_ = {s_: float(tgt.get((r_, s_), out_io.loc[r_, s_])) for s_ in ('coa', 'oil', 'gas', 'ore', 'min')}
        msp_w[r_] = M.msp_oil_gas_weight(ext_)
    if (va.index.duplicated()).any() or set(va.index) != set(R.index):
        raise SystemExit('io_s11 VA rows do not match the S01 regions')
    # fix worker wD (independent QA MEDIUM-1): the USA D29X39 share of VA from the BEA supply-use table of the base year
    # (GTAP's USA I-O table is BEA's, ch.8 Table 8.1), in place of the FIGARO 2022 USA estimate, which carries the 2021
    # COVID subsidies (food services, air, ambulatory health) that BEA 2022 does not have
    bea_tau, bea_groups = {}, []
    if a3 and V['usa_other_production_taxes'] == C.USA_D29_BEA and 'USA' in va.index:
        bea = SRC.bea_sut_va(I(DATA + '/bea_sut/bea_use_sut_summary_va_2017_2023.csv', 'BEA supply-use table VA rows (USA D29X39)'), BASE_YEAR)
        bea_map = C.load_bea_map(I(C.BEA_MAP_PATH, 'S12 BEA summary industry to sector map'))
        bea_tau, bea_groups = M.bea_group_tau(bea, bea_map, va.loc['USA'].to_dict(), sectors)
        want_b = float((bea['T00OTOP'] - bea['T00OSUB'])[bea['industry_code'].map(lambda c: bool(bea_map[c]))].sum())
        got_b = sum(bea_tau[s] * max(float(va.loc['USA', s]), 0.0) for s in sectors)
        S.check('S12-Hbea', 'USA D29X39 from BEA: the shares times io_s11 VA give BEA net other taxes on production of the private industries (USD bn)',
                'hard', round(bn(got_b), 6), round(bn(want_b), 6), abs(got_b - want_b) <= 1e-6 * max(1.0, abs(want_b)), 'usa_other_production_taxes',
                f'BEA {BASE_YEAR} other taxes on production {bn(bea["T00OTOP"].sum()):.1f}, other subsidies {bn(bea["T00OSUB"].sum()):.1f}; {len(bea_groups)} groups')
        S.flag('D29-BEA-USA', 'USA', f'D29X39 share of VA from BEA {BASE_YEAR} supply-use table (T00OTOP - T00OSUB) by industry group over io_s11 VA, '
               f'net {bn(want_b):.1f} bn, in place of FIGARO', rule=V['usa_other_production_taxes'])
    gdp = macro.set_index('code')['GDP_musd'].to_dict()
    pop = macro.set_index('code')['POP'].to_dict()
    geo_of = cmap.set_index('code')['gtap_geo'].dropna().to_dict()
    geo_of.update(R['gtap_geo'].dropna().to_dict())

    # ------------------------------------------------------------- 1. labour vs capital
    section_divs, sector_divs = M.section_divisions(concord)
    gdppc_all_pre = {c: gdp[c] / pop[c] for c in gdp if gdp.get(c, 0) > 0 and pop.get(c, 0) > 0}
    pool_all_pre = {c: GEO15.get(geo_of.get(c, ''), geo_of.get(c, '')) for c in gdppc_all_pre}
    na_share, na_src, partial = {}, {}, {}
    for src, df in (('FIGARO', fig), ('OECD Table 6', t6)):
        for c, g in df.groupby('iso3'):
            if c in na_share:
                continue
            sh = M.labour_shares_from_na(g, sector_divs, section_divs, SRC.activity_divisions)
            miss = [s_ for s_ in sectors if s_ not in sh]
            if sh and len(miss) <= MAX_MISSING:
                for s_ in miss:
                    sh[s_] = dict(share=None, activity='', d1=np.nan, b2a3g=np.nan, flag='not_in_source')
                if miss:
                    S.flag('NA-PARTIAL-FILLED', c, f'{src} covers {len(sectors) - len(miss)} of {len(sectors)} sectors; {" ".join(miss)} filled under unobserved_sector',
                           rule=V['partial_source'])
                na_share[c], na_src[c] = sh, f'{src} {int(g["year"].iloc[0])}'
                if src == 'OECD Table 6':
                    yr = int(g['year'].iloc[0])
                    nd = sum(1 for (cc, yy, _) in t6_derived if cc == c and yy == yr)
                    if nd:
                        S.flag('VA-B2A3G-DERIVED', c, f'Table 6 {yr} has no B2A3G in {nd} activities; derived as B1G - D1 - D29X39', rule=V['derive_b2a3g'])
            elif sh:
                partial[c] = len(sh)
                S.flag('NA-PARTIAL', c, f'{src} covers {len(sh)} of {len(sectors)} sectors; not used')
    # Grok-F2 (fix round A5): a FIGARO sector read from a parent code (section B for coa, oil, gas, ore, min, msp) is split
    # by the economy's own OECD Table 6 divisions where Table 6 has them (config parent_split)
    t6_of = {c: g for c, g in t6.groupby('iso3')}
    for c, sh in na_share.items():
        if not na_src[c].startswith('FIGARO') or c not in t6_of:
            continue
        for s_, x in sh.items():
            if x['share'] is None or not x.get('parent'):
                continue
            pdivs = set(SRC.activity_divisions(x['activity'], section_divs) or [])
            fine = M.labour_shares_from_na(t6_of[c], {s_: sector_divs[s_]}, section_divs, SRC.activity_divisions).get(s_)
            fpar = M.labour_shares_from_na(t6_of[c], {'_parent': pdivs}, section_divs, SRC.activity_divisions).get('_parent')
            if not fine or not fpar or fine['parent'] or fpar['parent'] or fine['share'] is None:
                continue
            got = M.split_parent(dict(d1=x['d1'], b2a3g=x['b2a3g'], d29=x['d29']), fine, fpar)
            if got is None:
                continue
            share, tau, d1, b2, d29 = got
            S.flag('VA-PARENT-SPLIT', f'{c} {s_}', f'{na_src[c]} {x["activity"]} share {x["share"]:.3f} split by Table 6 {int(t6_of[c]["year"].iloc[0])} '
                   f'{fine["activity"]} over {fpar["activity"]}: share {share:.3f}', rule=V['parent_split'])
            sh[s_] = dict(x, share=share, tau=tau, d1=d1, b2a3g=b2, d29=d29, parent=False,
                          activity=f'{x["activity"]} split by Table 6 {fine["activity"]}', flag='parent_split')
    # fix round A5: a FIGARO section whose codes all carry one imputed labour share (IND manufacturing, 18 codes at 0.267)
    # keeps its own compensation total, shared out by the pattern of the nearest economy that observes the codes
    # (config uniform_block)
    for c in [c for c in na_share if na_src[c].startswith('FIGARO')]:
        g = fig[fig['iso3'] == c].pivot_table(index='activity', columns='item', values='value', aggfunc='sum')
        by_sec = {}
        for a, r_ in g.iterrows():
            if a[0] in SECTIONS and len(a) > 1 and r_.get('D1', 0) + r_.get('B2A3G', 0) > 0:
                by_sec.setdefault(a[0], {})[a] = r_['D1'] / (r_['D1'] + r_['B2A3G'])
        for sec, med in M.uniform_blocks(by_sec).items():
            secs_ = [s_ for s_ in sectors if na_share[c][s_]['share'] is not None and not na_share[c][s_].get('parent')
                     and all(a[0] == sec for a in na_share[c][s_]['activity'].split('+'))]
            cands = [d for d in na_share if d != c and all(na_share[d][s_]['share'] is not None and not na_share[d][s_].get('parent')
                                                         and na_share[d][s_]['flag'] != 'uniform_block_rescaled' for s_ in secs_)]
            d = (M.nearest_donor(c, gdppc_all_pre, pool_all_pre, cands)
                 or M.nearest_donor(c, gdppc_all_pre, {x: 'world' for x in gdppc_all_pre}, cands))
            if d is None or not secs_:
                continue
            f_own = {s_: na_share[c][s_]['d1'] + na_share[c][s_]['b2a3g'] for s_ in secs_}
            new = M.rescale_pattern(f_own, {s_: na_share[d][s_]['share'] for s_ in secs_},
                                    sum(na_share[c][s_]['d1'] for s_ in secs_ if f_own[s_] > 0))
            for s_, v_ in new.items():
                na_share[c][s_] = dict(na_share[c][s_], share=v_, flag='uniform_block_rescaled')
            S.flag('VA-UNIFORM-BLOCK', f'{c} {sec}', f'{na_src[c]}: {len(by_sec[sec])} codes of section {sec} at one labour share {med:.4f}; '
                   f'{len(new)} sectors take the pattern of {d} ({na_src[d]}) scaled to their own D1 total', rule=V['uniform_block'])
    # extraction sectors carry the natural-resource rent out of non-labour income: a source cell with no surplus
    # (share clipped at 1) cannot hold it and is treated as unobserved (config extraction_no_surplus)
    for c, sh in na_share.items():
        for s in ('coa', 'oil', 'gas', 'ore', 'min'):
            if sh[s]['share'] is not None and sh[s]['flag'] in ('share_above_1_clipped', 'nonpositive_factor_income'):
                S.flag('VA-EXTRACTION-NO-SURPLUS', f'{c} {s}', f'{na_src[c]} {sh[s]["activity"]}: D1 {sh[s]["d1"]:.1f}, B2A3G {sh[s]["b2a3g"]:.1f}; treated as unobserved',
                       rule=V['extraction_no_surplus'])
                sh[s] = dict(sh[s], share=None, flag='extraction_no_surplus')
    S.log(f'national-accounts labour shares: {len(na_share)} countries ({sum(v.startswith("FIGARO") for v in na_src.values())} FIGARO)')

    gdppc = {r: gdp[r] / pop[r] for r in icio if gdp.get(r, 0) > 0 and pop.get(r, 0) > 0}
    pool = {r: GEO15.get(R.loc[r, 'gtap_geo'], R.loc[r, 'gtap_geo']) for r in icio}
    with_src = [r for r in icio if r in na_share]
    lam, lam_src, donor_of, prov, flagged = {}, {}, {}, {}, set()
    gdppc_all = {c: gdp[c] / pop[c] for c in gdp if gdp.get(c, 0) > 0 and pop.get(c, 0) > 0}
    gdppc_all.update(gdppc)
    pool_all = {c: GEO15.get(geo_of.get(c, ''), geo_of.get(c, '')) for c in gdppc_all}
    pool_all.update(pool)
    observes = {s: [c for c in with_src if na_share[c][s]['share'] is not None] for s in sectors}

    tau_of = {}
    # fix worker wF (QA round 2 P2b; GTAP 12 ch.9D): a D29X39 share passed by a donor (sector donor, ch.9D VA donor or an S05
    # member donor) is max(0, share): a donor supplies structure, not a policy wedge (config donor_d29_sign)
    dsign = a3 and V['donor_d29_sign'] == C.DONOR_D29_SIGN
    donor_neg = {}

    def via_donor(t_, r, s):
        if dsign and t_ is not None and t_ < 0:
            donor_neg[(r, s)] = min(donor_neg.get((r, s), 0.0), float(t_))
        return M.donor_tau(t_, dsign)

    def cell(c, s, r):
        """Share of sector s from split c for region r; a sector c does not observe comes from the nearest
        economy that observes it (config unobserved_sector). The D29X39 share of VA of the same source cell is kept in
        tau_of[(c, s)] (fix round A3)."""
        x = na_share[c][s]
        if x['share'] is not None:
            tau_of[(c, s)] = (bea_tau[s] if c == 'USA' and bea_tau else x.get('tau', 0.0)) if a3 else 0.0
            prov.setdefault((r, s), []).append(f'{c} {na_src[c]} {x["activity"]}: D1 {x["d1"]:.1f}, B2A3G {x["b2a3g"]:.1f}'
                                                + (f' ({x["flag"]})' if x['flag'] else ''))
            return x['share']
        d = (M.nearest_donor(c, gdppc_all, pool_all, observes[s])
             or M.nearest_donor(c, gdppc_all, {x: 'world' for x in gdppc_all}, observes[s]))
        if d is None:
            raise SystemExit(f'{c} {s}: no economy observes the sector')
        why = {'extraction_no_surplus': 'no surplus in an extraction sector', 'not_in_source': 'no code in the source'}.get(
            x['flag'], 'no activity (D1 and B2A3G zero)')
        if (r, s) not in flagged:
            flagged.add((r, s))
            S.flag('VA-SECTOR-DONOR', f'{r} {s}', f'{na_src[c]} of {c}: {s} has {why}; share of {d} ({na_src[d]})',
                   rule=V['unobserved_sector'])
        y = na_share[d][s]
        tau_of[(c, s)] = (bea_tau[s] if c == 'USA' and bea_tau else via_donor(y.get('tau', 0.0), r, s)) if a3 else 0.0
        prov.setdefault((r, s), []).append(f'{c} unobserved ({x["flag"]}), sector donor {d} {na_src[d]} {y["activity"]}: '
                                            f'D1 {y["d1"]:.1f}, B2A3G {y["b2a3g"]:.1f}' + (f' ({y["flag"]})' if y['flag'] else ''))
        return y['share']
    tau = {}
    for r in icio:
        if r in na_share:
            lam[r] = {s: cell(r, s, r) for s in sectors}
            tau[r] = {s: tau_of[(r, s)] for s in sectors}
            lam_src[r] = na_src[r]
        else:
            d = M.nearest_donor(r, gdppc, pool, with_src)
            if d is None:
                d = M.nearest_donor(r, gdppc, {c: 'world' for c in icio}, with_src)
                S.flag('VA-DONOR-WORLD', r, f'pool {pool.get(r)} has no economy with a national-accounts split; nearest over all economies', rule=V['va_no_source_rule'])
            if d is None:
                raise SystemExit(f'no ch.9D donor with a national-accounts split for {r} in pool {pool.get(r)}')
            lam[r] = {s: cell(d, s, r) for s in sectors}
            tau[r] = {s: via_donor(tau_of[(d, s)], r, s) for s in sectors}
            lam_src[r], donor_of[r] = f'donor {d} ({na_src[d]})', d
            S.flag('VA-DONOR', r, f'no national-accounts split; ch.9D donor {d} (pool {pool[r]}, GDP per capita {gdppc[r]:.0f} vs {gdppc[d]:.0f} USD)', rule=V['va_no_source_rule'])
    members = {r: [(m.code, float(m.weight), m.donor) for m in g.itertuples() if float(m.weight) > 0]
               for r, g in dw.groupby('region')}
    # fix round B8 (S05, David 2026-10-24): a member whose B06 column comes from an oil-producer donor (donor_weights column
    # oil_donor, read by name) takes that donor's split for oil and gas, so the B06 factor split matches the B06 cost
    # structure (config oil_donor_split; IMPROVEMENTS_LOG S12-9). A pre-B8 S05 output has no such column: that is a stale
    # upstream stage, so the split choice stops the build rather than falling back to the old donor
    if V['oil_donor_split'] == 's05_oil_donor_split_for_oil_and_gas' and 'oil_donor' not in dw.columns:
        raise SystemExit('oil_donor_split needs the S05 donor_weights column oil_donor (rerun S05 with fix B8)')
    oil_donor_of = {}
    if 'oil_donor' in dw.columns:
        for m in dw.itertuples():
            od = getattr(m, 'oil_donor')
            if isinstance(od, str) and od.strip() and float(m.weight) > 0:
                oil_donor_of[(m.region, m.code)] = od.strip()
    B06_SECTORS = ('oil', 'gas') if V['oil_donor_split'] == 's05_oil_donor_split_for_oil_and_gas' else ()
    for r in R.index:
        if r in lam:
            continue
        mem = members.get(r)
        if not mem:
            raise SystemExit(f'non-ICIO region {r} has no S05 member weights')
        own = [m for m, _, _ in mem if m in na_share]
        lam[r], tau[r] = {}, {}
        for s in sectors:
            def donor_for(code, s=s):
                if s in B06_SECTORS and (r, code) in oil_donor_of:
                    return oil_donor_of[(r, code)]
                return next(dd for mm, _, dd in mem if mm == code)

            def share_of(code, s=s):
                if code in na_share:
                    return cell(code, s, r)
                d = donor_for(code)
                if d in na_share:                     # includes a donor table that is not a region (ISL inside XWE)
                    return cell(d, s, r)
                prov.setdefault((r, s), []).extend(f'via {d}: {x}' for x in prov.get((d, s), []))
                return lam[d][s]
            def tau_member(code, s=s):
                if code in na_share:
                    return tau_of[(code, s)]
                d = donor_for(code)
                return via_donor(tau_of[(d, s)] if d in na_share else tau[d][s], r, s)
            def size_of(code, s=s, r=r):
                d = donor_for(code)
                return float(va.loc[d, s]) if d in va.index else float(va.loc[r, s])
            lam[r][s] = M.weighted_member_share([(m, w) for m, w, _ in mem], share_of, size_of)
            tau[r][s] = M.weighted_member_share([(m, w) for m, w, _ in mem], tau_member, size_of)
        lam_src[r] = ('own ' + ','.join(own) + '; ' if own else '') + 'S05 donors ' + ','.join(sorted({d for _, _, d in mem}))
        ods = sorted({f'{c_}<-{d_}' for (rr_, c_), d_ in oil_donor_of.items() if rr_ == r and c_ not in na_share})
        if ods and V['oil_donor_split'] == 's05_oil_donor_split_for_oil_and_gas':
            lam_src[r] += '; oil and gas from S05 oil donors ' + ','.join(ods)
            S.flag('VA-OIL-DONOR', r, f'oil and gas labour/capital split and D29X39 share from the S05 B06 oil donor: {", ".join(ods)}',
                   rule=V['oil_donor_split'])

    # ------------------------------------------------------------- 2. agriculture (ch.14A)
    kf22 = kf[kf['year'] == BASE_YEAR].copy()
    kf22['iso3'] = kf22['country'].replace(ALIAS)
    kfs = {r.iso3: M.normalise_kf(r._asdict()) for r in kf22.itertuples()}
    kf17 = kf[kf['year'] == 2017].copy()
    kf17['iso3'] = kf17['country'].replace(ALIAS)
    dec = lambda d: d[(d['year'] >= 2011) & (d['year'] <= 2020)].groupby('iso3')['value'].mean()
    lg, la = np.log(dec(gdppc_wb)), np.log(dec(arable))
    obs = [(r.iso3, M.normalise_kf(r._asdict())) for r in kf17.itertuples() if r.iso3 in lg.index and r.iso3 in la.index]
    X = np.array([[1.0, lg[c], la[c]] for c, _ in obs])
    b_lab, b_kap, sd_lab, sd_kap, n_sur = M.sur_fit([s['labour'] for _, s in obs], [s['capital'] for _, s in obs], X)
    S.log(f'ch.14A SUR on {n_sur} KF observations: labour {np.round(b_lab, 4)}, capital {np.round(b_kap, 4)}')
    g22 = gdppc_wb[gdppc_wb['year'] <= BASE_YEAR].sort_values('year').groupby('iso3').tail(1).set_index('iso3')['value']
    a22 = arable[arable['year'] <= BASE_YEAR].sort_values('year').groupby('iso3').tail(1).set_index('iso3')['value']
    kf_src = {c: 'USDA ERS Fuglie' for c in kfs}
    # fix round w13 (GTAP 12 ch.14A Table 14.2): where ch.14A rejects the KF shares as outliers, the ch.14A SUR prediction
    # (Table 14.16 coefficients) takes their place; GTAP keeps its earlier shares there, which this build does not have
    if V['ag_shares_choice'] == C.AG_KF_OUTLIER_GTAP:
        # fix worker wD (independent QA MEDIUM-5): the earlier GTAP shares ch.14A prefers are published in Table 14.1
        # ('Current GTAP Build' labour and capital, land the residual) and repeated in Table 14.2, so they are used as GTAP does
        reasons = C.load_ag_outliers(I(C.AG_OUTLIERS_PATH, 'S12 ch.14A Table 14.2 KF outliers and Table 14.1 GTAP shares'))
        for code, s_ in sorted(C.load_ag_outlier_gtap_shares(C.AG_OUTLIERS_PATH).items()):
            old_ = kfs.get(code)
            kfs[code], kf_src[code] = s_, 'ch.14A Table 14.1 GTAP shares (KF outlier, Table 14.2)'
            S.flag('AG-KF-OUTLIER', code, f'{reasons[code]}. Land {s_["land"]:.3f} labour {s_["labour"]:.3f} capital {s_["capital"]:.3f}'
                   + (f' (KF was land {old_["land"]:.3f} labour {old_["labour"]:.3f} capital {old_["capital"]:.3f})' if old_ else ''),
                   rule=V['ag_shares_choice'])
    elif V['ag_shares_choice'] == C.AG_KF_OUTLIER_SUR:
        coef14 = C.load_ag_sur(I(C.AG_SUR_PATH, 'S12 ch.14A Table 14.16 SUR coefficients'))
        for code, why in sorted(C.load_ag_outliers(I(C.AG_OUTLIERS_PATH, 'S12 ch.14A Table 14.2 KF outliers')).items()):
            if not (code in g22.index and code in a22.index and g22[code] > 0 and a22[code] > 0):
                S.flag('AG-KF-OUTLIER-NO-PREDICTOR', code, 'ch.14A KF outlier without WDI GDP per capita or arable land; KF kept', rule=V['ag_shares_choice'])
                continue
            s_, clipped = M.ch14a_sur_prediction(float(g22[code]), float(a22[code]), coef14)
            old_ = kfs.get(code)
            kfs[code], kf_src[code] = s_, 'ch.14A Table 14.16 SUR prediction (KF outlier, Table 14.2)'
            S.flag('AG-KF-OUTLIER', code, f'{why}. ch.14A SUR prediction land {s_["land"]:.3f} labour {s_["labour"]:.3f} capital {s_["capital"]:.3f}'
                   + (f' (KF was land {old_["land"]:.3f} labour {old_["labour"]:.3f} capital {old_["capital"]:.3f})' if old_ else '')
                   + ('; clipped and renormalised' if clipped else ''), rule=V['ag_shares_choice'])
    # fix worker wF (QA round 2 P3; GTAP 12 ch.14A Table 14.2): the USDA ERS 2022 file gives whole country groups one row
    # (West Asia and North Africa, Northwest Europe, Mexico's row for Central America and the Caribbean). Where Table 14.2
    # chooses another row for those countries (Middle East: GTAP, no Fuglie estimate; Northwest Europe: the Fuglie NWE
    # row; Mexico: GTAP, KF rejected) or names the country (Philippines, Nepal, Peru, Zimbabwe: GTAP, no Fuglie
    # estimate), the country takes the Table 14.2 row (config/s12/ag_table14_2_rows.csv), land the residual
    if V['ag_table14_2_rows'] == C.AG_T142:
        t142 = C.load_ag_table14_2(I(C.AG_T142_PATH, 'S12 ch.14A Table 14.2 rows for USDA group members'))
        both = sorted(set(t142) & set(C.load_ag_outliers(C.AG_OUTLIERS_PATH)))
        if both:
            raise SystemExit(f'ag_table14_2_rows.csv and ag_kf_outliers.csv both list {both}')
        for code, s_ in sorted(t142.items()):
            old_ = kfs.get(code)
            kfs[code] = dict(land=s_['land'], labour=s_['labour'], capital=s_['capital'])
            kf_src[code] = f'ch.14A Table 14.2 {s_["row"]} ({s_["source"]})'
            S.flag('AG-TABLE14-2', code, f'{s_["reason"]}. Land {s_["land"]:.3f} labour {s_["labour"]:.3f} capital {s_["capital"]:.3f}'
                   + (f' (USDA 2022 group row was land {old_["land"]:.3f} labour {old_["labour"]:.3f} capital {old_["capital"]:.3f})' if old_ else ''),
                   rule=V['ag_table14_2_rows'])

    def kf_for(code):
        if code in kfs:
            return kfs[code]
        if code in g22.index and code in a22.index and g22[code] > 0 and a22[code] > 0:
            x = np.array([1.0, np.log(g22[code]), np.log(a22[code])])
            lab_, kap_ = float(x @ b_lab), float(x @ b_kap)
            land_ = 1.0 - lab_ - kap_
            s = dict(land=land_, labour=lab_, capital=kap_)
            if min(s.values()) < 0:
                S.flag('AG-SUR-BOUND', code, f'SUR prediction outside [0,1] ({s}); clipped and renormalised', rule=V['ag_fill'])
                s = {k: max(v, 0.0) for k, v in s.items()}
                t = sum(s.values())
                s = {k: v / t for k, v in s.items()}
            kfs[code], kf_src[code] = s, 'ch.14A SUR prediction'
            S.flag('AG-SUR', code, f'no Fuglie share; ch.14A SUR prediction land {s["land"]:.3f} labour {s["labour"]:.3f} capital {s["capital"]:.3f}', rule=V['ag_fill'])
            return s
        return None

    ag, ag_src = {}, {}
    for r in R.index:
        mem = [(r, 1.0, r)] if r in icio else members[r]
        parts = [(kf_for(m), w, m) for m, w, _ in mem]
        miss = [m for s, _, m in parts if s is None]
        if miss:
            S.flag('AG-NO-DATA', r, f'members with neither Fuglie shares nor SUR predictors: {" ".join(miss)}; dropped from the weights', rule=V['composite_shares'])
        parts = [(s, w) for s, w, _ in parts if s is not None]
        if not parts:
            g = geo_of.get(r, '')
            pool_kf = [kfs[c] for c in kfs if geo_of.get(c) == g and kf_src.get(c) == 'USDA ERS Fuglie']
            if not pool_kf:
                raise SystemExit(f'{r}: no agricultural factor shares and no geographic-region average')
            parts = [({k: float(np.mean([p[k] for p in pool_kf])) for k in ('land', 'labour', 'capital')}, 1.0)]
            kf_src[r] = f'{g} average of {len(pool_kf)} Fuglie countries'
            mem = [(r, 1.0, r)]
            S.flag('AG-GEO', r, f'no Fuglie share and no SUR predictors; {kf_src[r]}', rule=V['ag_fill'])
        W_ = sum(w for _, w in parts)
        ag[r] = {k: sum(s[k] * w for s, w in parts) / W_ for k in ('land', 'labour', 'capital')}
        ag_src[r] = 'ch.14A ' + ('; '.join(sorted({kf_src[m] for m, _, _ in mem if m in kf_src})))

    # ------------------------------------------------------------- 3a. consumption of fixed capital (natres cap)
    # David 2026-10-23 (QA B2): the rent is capped at net operating surplus, so capital keeps at least its CFC.
    # CFC / B2A3G by activity from Table 6; a sector a country does not report takes the nearest economy by GDP per
    # capita (same GTAP15 pool, else the world) that reports it (config cfc_source).
    ext = ('coa', 'oil', 'gas', 'ore', 'min', 'for')
    cfc_obs = {}
    for c, g in t6cfc.groupby('iso3'):
        sh = M.labour_shares_from_na(g, {s_: sector_divs[s_] for s_ in ext}, section_divs, SRC.activity_divisions)
        for s_, x in sh.items():
            # a cell with CFC at or above gross surplus (share >= 1) would leave no net surplus: unobserved, both for the
            # country itself and as a donor (QA B3, as extraction_no_surplus)
            if x['share'] is not None and x['d1'] + x['b2a3g'] > 0 and x['share'] < 1.0:
                cfc_obs[(c, s_)] = (max(x['share'], 0.0), f'OECD Table 6 {int(g["year"].iloc[0])} {x["activity"]}')
    def cfc_for(code, s_):
        if (code, s_) in cfc_obs:
            return cfc_obs[(code, s_)]
        if V['cfc_source'].startswith('oecd_table6_p51c_over_b2a3g_own_else_gtap15_pool_median'):
            p_ = pool_all.get(code)
            vals = [v_[0] for (c, ss), v_ in cfc_obs.items() if ss == s_ and pool_all.get(c) == p_]
            if len(vals) >= 3:
                return float(np.median(vals)), f'pool {p_} median of {len(vals)}'
            vals = [v_[0] for (c, ss), v_ in cfc_obs.items() if ss == s_]
            if vals:
                return float(np.median(vals)), f'median of {len(vals)} reporting economies'
        cand = [c for (c, ss) in cfc_obs if ss == s_ and c in gdppc_all]
        d = (M.nearest_donor(code, gdppc_all, pool_all, cand) or M.nearest_donor(code, gdppc_all, {x: 'world' for x in gdppc_all}, cand))
        if d is None:
            raise SystemExit(f'{code} {s_}: no economy reports CFC for the sector')
        return cfc_obs[(d, s_)][0], f'donor {d} ({cfc_obs[(d, s_)][1]})'
    cfc, cfc_src = {}, {}
    for r in R.index:
        mem = [(r, 1.0, r)] if r in icio else members[r]
        for s_ in ext:
            parts = [(cfc_for(m, s_), w) for m, w, _ in mem]
            W_ = sum(w for _, w in parts)
            cfc[(r, s_)] = sum(x[0] * w for x, w in parts) / W_
            cfc_src[(r, s_)] = parts[0][0][1] if len(parts) == 1 else f'{len(parts)} members'

    # ------------------------------------------------------------- 3. natural-resource rents (natres_rule = wdi only)
    rent_pct = {k: d[d['year'] <= BASE_YEAR].sort_values('year').groupby('iso3').tail(1).set_index('iso3')['value'] for k, d in rents.items()}
    rent_year = {k: int(d[d['year'] <= BASE_YEAR]['year'].max()) for k, d in rents.items()}
    rent = {r: dict.fromkeys(RENT_SERIES, 0.0) for r in R.index}
    # fix round A7: WDI's latest rents are 2021; oil and gas rents are taken to 2022 with the Pink Sheet benchmark price
    # ratio 2022/2021 (crude oil average; gas by the member's market: US Henry Hub for the Americas, Europe for Europe,
    # North Africa and Central Asia, Japan LNG elsewhere) (config natres_price_year). Coal, mineral and forest stay at 2021.
    def pr(n, k='oil'):
        return pink[n][BASE_YEAR] / pink[n][rent_year[k]] if V['natres_price_year'] != 'wdi_latest_year_unscaled' else 1.0
    GAS_MKT = {'NAMR': 'Natural gas, US', 'CAMR': 'Natural gas, US', 'CARB': 'Natural gas, US', 'SAMR': 'Natural gas, US',
               'EEUR': 'Natural gas, Europe', 'NEUR': 'Natural gas, Europe', 'SEUR': 'Natural gas, Europe', 'WEUR': 'Natural gas, Europe',
               'NAFR': 'Natural gas, Europe', 'CEAS': 'Natural gas, Europe'}
    price_scale = {'oil': pr('Crude oil, average')} if not natres_gtap else {}
    for r in (R.index if not natres_gtap else []):
        mem = [(r, 1.0, r)] if r in icio else members[r]
        for m, _, _ in mem:
            for k in RENT_SERIES:
                p = rent_pct[k].get(m)
                if p is not None and np.isfinite(p):
                    f_ = 1.0
                    if k == 'oil':
                        f_ = price_scale['oil']
                    elif k == 'gas':
                        f_ = pr(GAS_MKT.get(str(geo_of.get(m, R.loc[r, 'gtap_geo'])).split('+')[0], 'Liquefied natural gas, Japan'), 'gas')
                    rent[r][k] += p / 100.0 * gdp.get(m, 0.0) * f_

    # ------------------------------------------------------------- 4. labour groups (ch.14B)
    isco = isco[isco['isco08_major'].astype(str).isin([str(i) for i in range(1, 10)])]
    groups9 = isco.assign(k=isco['isco08_major'].astype(int)).sort_values('k')['group5'].tolist()
    if len(groups9) != 9 or set(groups9) != set(LABOUR5):
        raise SystemExit('S01 labour_isco_groups.csv does not give the five groups for ISCO 1-9')
    lsh, lmeta = LAB.country_shares(occ, ind, wocc, wind, groups9, BASE_YEAR, cross)
    used = set(lmeta.loc[lmeta['status'] == 'used', 'iso3'])
    # Fable QA B-02 (GTAP 12 ch.14B rule F16a: a national cross table ranks above ILOSTAT and above a regional average):
    # the listed economies take their national occupation x industry employment (config/s12/national_labour_sources.csv,
    # codes mapped by national_labour_map.csv), with ILOSTAT earnings of the latest year at or before the base year, else
    # the regional relative wage profile (config labour_national_tables)
    nat_lab, nat_rows, pre_lab = {}, [], {}
    if V['labour_national_tables'] == C.LABOUR_NATIONAL:
        nsrc = C.load_national_sources(I(C.NATIONAL_SOURCES_PATH, 'S12 national occupation x industry sources (B-02)'),
                                       readers=set(NL.READERS) | {'ilostat_cross'})
        nmap = C.load_national_map(I(C.NATIONAL_MAP_PATH, 'S12 national labour codes to ISCO-08 and ISIC Rev.4 (B-02)'), sections=SECTIONS)
        prof = LAB.occ_profiles(occ, sorted(set(occ['iso3'])), BASE_YEAR)
        prof_used = {k: v for k, v in prof.items() if k in used}
        rel = LAB.wage_relatives(occ, wocc, sorted(used), BASE_YEAR)

        def regional(vals, c):
            g = geo_of.get(c, '')
            pool_ = [v for k, v in vals.items() if k != c and geo_of.get(k, '') == g] or [v for k, v in vals.items() if k != c]
            return np.nanmean(np.vstack(pool_), axis=0), (g if any(geo_of.get(k, '') == g for k in vals if k != c) else 'world')
        tabs, wprior = {}, {}
        for c, x in sorted(nsrc.items()):
            folders = sorted({f.split('/')[0] for f in x['files']})
            off = [f for f in folders if S._years.get(f, {}).get('on_box', 'NO') != 'yes']
            if off:
                # config/source_years.csv has no table on disk for this base year (e.g. the 2021 census for 2017)
                S.flag('LAB-NATIONAL-NO-YEAR', c, f'{x["source"]}: no {BASE_YEAR} table on disk ({" ".join(off)}, config/source_years.csv); ILOSTAT/F16c rule kept',
                       rule=V['labour_national_tables'])
                continue
            paths = [I(f'{DATA}/{f}', f'{x["source"]} labour table ({c}, B-02)') for f in x['files']]
            if x['source'] == 'ilostat_cross':
                if cross is None:
                    raise SystemExit(f'{c}: ilostat_cross needs labour_matrix observed (the EC2 file)')
                xc = cross[(cross['iso3'] == c) & (cross['year'] <= BASE_YEAR)]
                if xc.empty:
                    S.flag('LAB-NATIONAL-NO-YEAR', c, f'ILOSTAT occupation x activity has no year at or before {BASE_YEAR}; ILOSTAT/F16c rule kept', rule=V['labour_national_tables'])
                    continue
                xc = LAB.pick_isco(LAB.pick_source(xc.assign(code=xc['code'] + xc['section'])).assign(code=lambda d: d['code'].str[0]))
                yx = int(xc['year'].max())
                xc = xc[xc['year'] == yx]
                tab = dict(kind='cross', year=yx, cross=pd.DataFrame(dict(occ=xc['code'], ind=xc['section'], value=xc['value'])))
                # ILOSTAT codes are ISCO-08 and ISIC sections already; a country row in the map (source ilostat_cross:<iso3>)
                # re-maps a group the country publishes combined (JPN: ISCO 2 holds 3)
                own_map = nmap.get(f'ilostat_cross:{c}', {'occ': {}, 'ind': {}})
                omap = {**{o9: [o9] for o9 in NL.OCC9}, **own_map['occ']}
                imap = {**{s_: [s_] for s_ in SECTIONS}, **{k: [] for k in ('U', 'X')}, **own_map['ind']}
            else:
                tab = NL.READERS[x['source']](*paths, BASE_YEAR)
                if tab is None:
                    S.flag('LAB-NATIONAL-NO-YEAR', c, f'{x["source"]} has no table at or before {BASE_YEAR}; ILOSTAT/F16c rule kept', rule=V['labour_national_tables'])
                    continue
                omap, imap = nmap[x['source']]['occ'], nmap[x['source']]['ind']
            sp = prof.get(c)
            if sp is None:
                sp, _ = regional(prof_used, c)
            N_, no_, ni_, unm = NL.to_matrix(tab, omap, imap, sp)
            if unm:
                raise SystemExit(f'{c} {x["source"]}: codes not in national_labour_map.csv: {unm}')
            ctl = ''
            if x['occ_controls'] == 'ilostat_isco08_base_year' and N_ is not None:
                # the national occupation classification is not ISCO-08 one to one (KSCO 7th clerks hold ISCO 3 business
                # associate professionals): the cross table is the seed, ILOSTAT's ISCO-08 occupation employment of the
                # base year the row totals and the table's own industry employment the column totals (RAS)
                ov, oy = LAB._latest(occ, c, BASE_YEAR, NL.OCC9)
                ov = np.nan_to_num(ov)
                if oy != BASE_YEAR or (ov > 0).sum() < 9:
                    raise SystemExit(f'{c}: occ_controls needs ILOSTAT ISCO-08 employment in all nine groups for {BASE_YEAR}')
                N_ = LAB.ras(N_, ov, ni_)
                no_, ni_ = N_.sum(axis=1), N_.sum(axis=0)
                ctl = f'; rows scaled to ILOSTAT ISCO-08 {oy} occupation employment (RAS)'
            if (no_ > 0).sum() < LAB.MIN_OCC or ni_.sum() <= 0:
                S.flag('LAB-NATIONAL-THIN', c, f'{x["source"]} {tab["year"]}: {(no_ > 0).sum()} occupation groups with workers; ILOSTAT/F16c rule kept', rule=V['labour_national_tables'])
                continue
            wprior[c], wg = regional(rel, c)
            tabs[c] = dict(N=N_, N_occ=no_, N_ind=ni_, year=tab['year'], source=x['source'])
            nat_rows.append(dict(iso3=c, source=x['source'], kind=tab['kind'], year=tab['year'], employed=float(no_.sum()),
                                 sections_with_workers=int((ni_ > 0).sum()), wage_prior_region=wg, citation=x['citation'] + ctl,
                                 replaces=('ILOSTAT ' + lmeta.set_index('iso3').loc[c, 'years']) if c in used else 'F16c average'))
        nsh, nmeta = LAB.national_shares(tabs, wocc, wind, groups9, BASE_YEAR, wprior)
        for m_ in nmeta.itertuples():
            nat_lab[m_.iso3] = m_
            nr_ = next(r_ for r_ in nat_rows if r_['iso3'] == m_.iso3)
            nr_.update(occ_wage_source=m_.occ_wage_source, ind_wage_source=m_.ind_wage_source, flags=m_.flags)
            S.flag('LAB-NATIONAL', m_.iso3, f'{m_.source} {m_.years} ({m_.n_matrix}) in place of {nr_["replaces"]}; occupation wages '
                   f'{m_.occ_wage_source}, industry wages {m_.ind_wage_source}' + (f'; {m_.flags}' if m_.flags else ''), rule=V['labour_national_tables'])
        # the split each listed economy had before (its ILOSTAT window, else the F16c average of its region), for S12-Rnational
        cs0 = lsh.pivot_table(index=['iso3', 'section'], columns='group', values='share')[list(LABOUR5)]
        geo0 = cs0.assign(geo=[geo_of.get(c, '') for c in cs0.index.get_level_values(0)]).groupby(['geo', 'section'])[list(LABOUR5)].mean()
        for c in nat_lab:
            if c in used:
                pre_lab[c] = (cs0.loc[c], 'ILOSTAT')
            elif geo_of.get(c, '') in geo0.index.get_level_values(0):
                t0 = geo0.loc[geo_of[c]]
                pre_lab[c] = (t0.div(t0.sum(axis=1), axis=0), f'F16c {geo_of[c]}')
        lsh = pd.concat([lsh[~lsh['iso3'].isin(nat_lab)], nsh], ignore_index=True)
        lmeta = pd.concat([lmeta[~lmeta['iso3'].isin(nat_lab)], nmeta], ignore_index=True)
        used |= set(nat_lab)
    cs = lsh.pivot_table(index=['iso3', 'section'], columns='group', values='share')[list(LABOUR5)]
    cs['geo'] = [geo_of.get(c, '') for c in cs.index.get_level_values(0)]
    geo_mean = cs.groupby(['geo', 'section'])[list(LABOUR5)].mean()
    world_mean = cs.groupby('section')[list(LABOUR5)].mean()

    def lab_for(code):
        if code in nat_lab:
            return cs.loc[code][list(LABOUR5)], f'national {nat_lab[code].source} {nat_lab[code].years}'
        if code in used:
            return cs.loc[code][list(LABOUR5)], 'ILOSTAT ' + lmeta.set_index('iso3').loc[code, 'years']
        g = geo_of.get(code, '')
        if g and g in geo_mean.index.get_level_values(0):
            t = geo_mean.loc[g]
            return t.div(t.sum(axis=1), axis=0), f'F16c {g} average'
        return world_mean.div(world_mean.sum(axis=1), axis=0), 'F16c world average'

    labsh, lab_src = {}, {}
    for r in R.index:
        mem = [(r, 1.0, r)] if r in icio else members[r]
        acc, W_, srcs = None, 0.0, []
        for m, w, _ in mem:
            t, src = lab_for(m)
            acc = t * w if acc is None else acc.add(t * w, fill_value=0.0)
            W_ += w
            srcs.append(src)
        labsh[r] = acc / W_
        lab_src[r] = srcs[0] if len(srcs) == 1 else f'{sum(s.startswith(("ILOSTAT", "national")) for s in srcs)} of {len(srcs)} members ILOSTAT or national'
        if all(s.startswith('F16c') for s in srcs):
            S.flag('LAB-F16C', r, f'no adequate ILOSTAT window for any member; {srcs[0]}', rule=V['labour_no_data'])
    sec_of = {}
    for s, divs in sector_divs.items():
        secs = {concord.loc[concord['isic4_code'].str[:2] == d, 'isic4_section'].iloc[0] for d in divs}
        if len(secs) != 1:
            raise SystemExit(f'sector {s} spans ISIC sections {secs}')
        sec_of[s] = secs.pop()

    # ------------------------------------------------------------- 4b. self-employed (A5) and capital floor (A6)
    # Capital floor: CFC / (D1 + B2A3G) by activity from OECD Table 6 P51C; a sector a country does not report takes the
    # median of the reporting economies in its GTAP15 pool (at least three), else of all reporting economies (config capital_floor)
    cfi_obs = {}
    for c, g in t6cfi.groupby('iso3'):
        for s_, x in M.labour_shares_from_na(g, sector_divs, section_divs, SRC.activity_divisions).items():
            if x['share'] is not None and x['d1'] + x['b2a3g'] > 0 and 0.0 <= x['share'] < 1.0 and not x['flag']:
                cfi_obs[(c, s_)] = x['share']
    cfi_world = {s_: float(np.median([v_ for (c, ss), v_ in cfi_obs.items() if ss == s_] or [0.0])) for s_ in sectors}

    def floor_for(code, s_):
        if (code, s_) in cfi_obs:
            return cfi_obs[(code, s_)], 'own'
        p_ = pool_all.get(code)
        vals = [v_ for (c, ss), v_ in cfi_obs.items() if ss == s_ and pool_all.get(c) == p_]
        if len(vals) >= 3:
            return float(np.median(vals)), f'pool {p_} median of {len(vals)}'
        return cfi_world[s_], 'world median'
    # Gollin (2002) adjustment 2: self-employed per employee by ISIC section from ILOSTAT, latest year at or before the base
    # year; a country without the series takes the nearest economy by S02 GDP per capita in its pool that has it (config gollin_source)
    ste_ok = ste[(ste['ees'] > 0)]
    m_obs = {(r_.iso3, r_.section): (r_.slf / r_.ees if np.isfinite(r_.slf) else 0.0) for r_ in ste_ok.itertuples()}
    m_year = ste_ok.groupby('iso3')['year'].max().to_dict()
    has_ste = [c for c in m_year if c in gdppc_all]

    def gollin_for(code):
        if code in m_year:
            return code
        return (M.nearest_donor(code, gdppc_all, pool_all, has_ste)
                or M.nearest_donor(code, gdppc_all, {x: 'world' for x in gdppc_all}, has_ste))
    floor, mratio, lam_d1, a56 = {}, {}, {}, {}
    gollin_donor = {}
    for r in R.index:
        mem = [(r, 1.0, r)] if r in icio else members[r]
        W_ = sum(w for _, w, _ in mem)
        floor[r] = {s_: sum(floor_for(m, s_)[0] * w for m, w, _ in mem) / W_ for s_ in sectors}
        src_m = [(gollin_for(m), w, m) for m, w, _ in mem]
        mratio[r] = {}
        for sec in SECTIONS:
            vals = [(m_obs.get((d, sec), 0.0) if d else 0.0, w) for d, w, _ in src_m]
            mratio[r][sec] = sum(v_ * w for v_, w in vals) / W_
        gollin_donor[r] = ', '.join(sorted({f'{m}<-{d}' for d, _, m in src_m if d != m}))
        if gollin_on and gollin_donor[r]:
            S.flag('LAB-GOLLIN-DONOR', r, f'no ILOSTAT status in employment by activity for {gollin_donor[r]}', rule=V['gollin_source'])
        lam_d1[r] = dict(lam[r])
        for s_ in sectors:
            if s_ in ('crp', 'hhe') or lam[r][s_] is None:
                continue
            m_ = mratio[r][sec_of[s_]] if gollin_on else 0.0
            fl = floor[r][s_] if floor_on else 0.0
            new, capped = M.gollin_share(lam[r][s_], m_, fl, d1_min)
            a56[(r, s_)] = dict(d1_share=lam[r][s_], slf_over_ees=m_, capital_floor=fl, capped=capped,
                                floor_binds_on_d1=lam[r][s_] > 1.0 - fl + 1e-12)
            if d1_min and a56[(r, s_)]['floor_binds_on_d1']:
                S.flag('LAB-D1-ABOVE-FLOOR', f'{r} {s_}', f'D1 share {lam[r][s_]:.4f} above 1 - capital floor {1.0 - fl:.4f}: labour kept at D1, '
                       'capital below its CFC share', rule=V['labour_at_least_d1'])
            lam[r][s_] = new
    S.log(f'capital floor: {len(cfi_obs)} own Table 6 cells; Gollin: {len(m_year)} countries with ILOSTAT status by activity')
    # beta v4 G4 (choice hhe_labour_share): activities of households as employers are all labour in every region (the output of
    # paid domestic services is the compensation paid, SNA 2008; the source or donor share, e.g. ZAF 0.942, is replaced)
    hhe_one = V['hhe_labour_share'] == C.HHE_ALL_LABOUR
    if hhe_one:
        moved_hhe = [(r, lam[r]['hhe']) for r in R.index if 'hhe' in lam[r] and lam[r]['hhe'] is not None and lam[r]['hhe'] != 1.0]
        for r, _ in moved_hhe:
            lam[r]['hhe'] = 1.0
        S.log('G4 hhe labour share set to 1 in ' + ', '.join(f'{r} {v:.3f}' for r, v in moved_hhe))

    # ------------------------------------------------------------- assemble EVFP
    # fix round A3: D29X39 out of VA. PSE support the build books elsewhere (S13 output support; land, capital, labour and
    # all-factor support here as factor-use subsidies) sits inside crp D39 and is added back so it is booked once.
    pse_crp = sup[sup['basis'].isin(('output', 'land', 'capital', 'labour', 'factors'))].groupby('region')['value_musd'].sum().to_dict()
    pp_val = ftr[ftr['tax_class'] == 'payroll_property'].groupby('region')['value_musd'].sum().to_dict()
    TAU_LO, TAU_HI = -1.0, 0.5
    # fix worker wF (QA round 2 P2): regions whose crp D29X39 is their own FIGARO estimate outside the EU (the USA is on
    # BEA); a donor-built region already carries no net subsidy (donor_d29_sign)
    crp_cap_regions = set()
    if a3 and V['crp_d29_beyond_pse'] == C.CRP_BEYOND_PSE:
        crp_cap_regions = {r for r in icio if r in na_share and r in fig_est and na_share[r]['crp']['share'] is not None
                           and not (r == 'USA' and bea_tau)}
    rows, natres_rows, va_rows, otax_rows = [], [], [], []
    payroll_r = {}
    for r in R.index:
        nonlab, lab_base = {}, {}
        for s in sectors:
            v = float(va.loc[r, s])
            t_raw = float(tau[r][s] or 0.0) if a3 else 0.0
            t_ = min(max(t_raw, TAU_LO), TAU_HI)
            if a3 and t_ != t_raw and v > 0:
                S.flag('D29-SHARE-CLIPPED', f'{r} {s}', f'D29X39 share of VA {t_raw:.3f} clipped to [{TAU_LO}, {TAU_HI}]', rule=V['other_production_taxes'])
            otp = addb = otx0 = ccap = 0.0
            if v <= 0:
                lab_v, land_v, cap_v = 0.0, 0.0, v
                if v < 0:
                    S.flag('NEG-VA', f'{r} {s}', f'VA {v:.3f} m is negative; booked whole to capital for S13', rule=V['negative_va'])
                    S.adjust(r, f'{s} VA split', v, f'capital {v:.6f}', 'negative_va', 'S12 config negative_va', 'NEG-VA')
            else:
                otp, fc, otx0, addb = M.output_tax(v, t_, 0.0, pse_crp.get(r, 0.0) if s == 'crp' else 0.0)
                if s == 'crp' and r in crp_cap_regions:
                    # fix worker wF (QA round 2 P2): no crp net subsidy beyond the PSE from a FIGARO estimate outside the EU
                    ccap = M.crp_beyond_pse_cap(otp, addb)
                    otx0, fc = otx0 + ccap, fc - ccap
                if s == 'crp':
                    land_v, lab_v, cap_v = ag[r]['land'] * fc, ag[r]['labour'] * fc, ag[r]['capital'] * fc
                else:
                    lab_v, land_v = lam[r][s] * fc, 0.0
                    cap_v = fc - lab_v
            nonlab[s], lab_base[s] = cap_v, lab_v
            x56 = a56.get((r, s), {})
            va_rows.append(dict(region=r, sector=s, va_musd=v, labour_musd=lab_v, land_musd=land_v,
                                nonlabour_musd=cap_v, labour_share=(lab_v / (lab_v + land_v + cap_v) if v > 0 and lab_v + land_v + cap_v > 0 else np.nan),
                                source=(ag_src[r] if s == 'crp' else lam_src[r]), d29x39_share_of_va=t_,
                                d1_share_of_factor_income=x56.get('d1_share', np.nan), slf_over_ees=x56.get('slf_over_ees', np.nan),
                                capital_floor=x56.get('capital_floor', np.nan), labour_capped=x56.get('capped', False),
                                floor_binds_on_d1=x56.get('floor_binds_on_d1', False)))
            otax_rows.append(dict(region=r, sector=s, va_musd=v, d29x39_share_of_va=t_, otp_musd=otp, pse_addback_musd=addb,
                                  crp_beyond_pse_removed_musd=ccap, output_tax_before_payroll_musd=otx0))
            rows.append((r, s, lab_v, land_v))
        # ch.15 pp.2-3 (fix round w13; David 2026-10-24: follow the GTAP 12 ch.15 text): the GFS/GRS payroll and property
        # taxes (S10 payroll_property, T_3000 + T_4000) are a factor employment tax on all factors at one rate across
        # industries (booked in factor_taxes below). They overlap D29X39, so the part of them that the region's positive
        # other production taxes hold is taken from the D29 output tax of the cells that pay it (pro rata to their positive
        # D29X39) and added to those cells' factor payments (all factors pro rata); the rest of D29 stays the output tax.
        # Alternative (fix round A3, w5): only the payroll part (GRS T_3000 share), from cells pro rata to labour.
        mem = [(r, 1.0, r)] if r in icio else members[r]
        netting = not V['payroll_d29_netting'].startswith('none_')
        if ch15 and netting:
            # Fable QA F-03: the part of payroll_property inside D29 is the payroll taxes (GRS T_3000) and the recurrent
            # taxes on immovable property (T_4100, D29 of the owner, incl. owner-occupiers); net wealth, estate and
            # transaction taxes (rest of T_4000) are not D29. Members without T_4100 count whole (the earlier rule)
            # (a negative GRS item, a net refund, counts as zero)
            pz = {m: tuple(max(v_, 0.0) if np.isfinite(v_) else v_ for v_ in (grs[m][0], grs[m][1], grs[m][3])) for m, _, _ in mem if m in grs}
            mg = [(w, pz[m]) for m, w, _ in mem if m in pz and pz[m][0] + pz[m][1] > 0]
            num = sum(w * (g_[0] + min(g_[2] if np.isfinite(g_[2]) else g_[1], g_[1])) for w, g_ in mg)
            den = sum(w * (g_[0] + g_[1]) for w, g_ in mg)
            frac = min(max(num / den, 0.0), 1.0) if den > 0 else 1.0
        else:
            num = sum(w * grs[m][0] for m, w, _ in mem if m in grs)
            den = sum(w * (grs[m][0] + grs[m][1]) for m, w, _ in mem if m in grs)
            frac = 1.0 if ch15 else (num / den if den > 0 else 0.0)
        pos = sum(max(x['output_tax_before_payroll_musd'], 0.0) for x in otax_rows[-len(sectors):])
        want_p = pp_val.get(r, 0.0) * frac if a3 else 0.0
        P = min(want_p, pos) if (netting or not ch15) else 0.0
        if netting and want_p > pos + TOL:
            S.flag('D29-PAYROLL-CAP', r, f'{"payroll and property" if ch15 else "payroll"} tax {want_p:.1f} m above positive D29X39 {pos:.1f} m; '
                   f'{want_p - P:.1f} m is not in D29' + (' and stays inside factor payments (ch.15)' if ch15 else '; capped'),
                   rule=V['payroll_property'])
        payroll_r[r] = dict(payroll_musd=P, payroll_wanted_musd=want_p, payroll_fraction_grs=frac)
        new_rows = rows[-len(sectors):]
        if ch15:
            base = {x['sector']: max(x['output_tax_before_payroll_musd'], 0.0) for x in otax_rows[-len(sectors):]}
        else:
            base = {s_: max(lv, 0.0) for (_, s_, lv, ld) in new_rows}
        lt = sum(base.values())
        for k, (x, (rr, s, lv, ld)) in enumerate(zip(otax_rows[-len(sectors):], new_rows)):
            pay = P * base[s] / lt if lt > 0 else 0.0
            x['payroll_musd'] = pay
            x['output_tax_musd'] = x['output_tax_before_payroll_musd'] - pay
            if ch15:
                fc_ = max(lv, 0.0) + max(ld, 0.0) + max(nonlab[s], 0.0)
                f_ = pay / fc_ if fc_ > 0 else 0.0
                if pay > 0 and fc_ <= 0:
                    raise SystemExit(f'{r} {s}: D29 part of payroll and property {pay:.3f} m on a cell without factor payments')
                lv_n, ld_n = lv + max(lv, 0.0) * f_, ld + max(ld, 0.0) * f_
                nonlab[s] = nonlab[s] + max(nonlab[s], 0.0) * f_
                rows[len(rows) - len(sectors) + k] = (rr, s, lv_n, ld_n)
            else:
                rows[len(rows) - len(sectors) + k] = (rr, s, lv + pay, ld)
        if natres_gtap:
            # fix round B16 (GTAP 7 ch.12.A pp.2-3; GTAP 12 ch.17B §B.1): the natural-resource share that gives the target
            # supply elasticity, out of all value added (labour and capital pro rata), at the cost (output less output tax)
            ox = {x['sector']: x for x in otax_rows[-len(sectors):]}
            new = []
            for (rr, s, lv, ld) in rows[-len(sectors):]:
                cap = nonlab[s]
                if s not in NT:
                    new.append((rr, s, lv, ld, cap, 0.0))
                    continue
                t_ = NT[s]
                fva = lv + ld + cap
                o_io = float(out_io.loc[r, s])
                cost = o_io - ox[s]['output_tax_musd']
                z = M.natres_target_share(fva, cost, t_['eta'], t_['sigma'], theta_floor)
                sh_, eta_used, w_og = z['share'], t_['eta'], np.nan
                if s == 'msp' and msp_blend and z['share'] > 0:
                    # fix round w13 (GTAP 12 ch.2 Table 2.11 note: oil and gas hold the support activities for petroleum
                    # and gas extraction, ISIC 091): the 0910 part of msp takes the fossil-fuel target, the 0990 part the
                    # other-mining target, at the cell's theta_VA; the 0910 part is the region's oil and gas share of
                    # extraction output (our choice: ICIO publishes D09 whole)
                    w_og = msp_w[r]
                    z_og = M.natres_target_share(fva, cost, NT['oil']['eta'], t_['sigma'], theta_floor)
                    sh_, eta_used = M.msp_blend(z_og['share'], z['share'], w_og, t_['sigma'], z['theta_va_used'])
                lab_n, cap_n = lv * (1.0 - sh_), cap * (1.0 - sh_)
                nat_n = sh_ * (lv + cap)
                if z['guard']:
                    S.flag('NATRES-GUARD', f'{r} {s}', f'value added {fva:.1f} m is {z["theta_va"]:.4f} of the cost {cost:.1f} m, below '
                           f'{theta_floor}; natural-resource share of VA held at {sh_:.4f} (the target share at theta_VA {theta_floor})',
                           rule=V['natres_guard'])
                cf = cfc.get((r, s), np.nan)
                natres_rows.append(dict(region=r, sector=s, rule='gtap_ch12a', series='ch.12.A target supply elasticity',
                                        gtap_sector=t_['gtap_sector'], target_class=t_['target_class'], eta_target=eta_used,
                                        msp_oil_gas_support_weight=w_og,
                                        sigma_va=t_['sigma'], factor_va_musd=fva, io_output_musd=o_io,
                                        output_tax_musd=ox[s]['output_tax_musd'], cost_musd=cost, theta_va=z['theta_va'],
                                        theta_va_used=z['theta_va_used'], guard=z['guard'], natres_share_of_va=sh_,
                                        theta_r=(nat_n / cost if cost > 0 else np.nan),
                                        eta_implied=M.implied_eta(nat_n, fva, cost, t_['sigma']),
                                        labour_before_musd=lv, capital_before_musd=cap, labour_musd=lab_n, capital_musd=cap_n,
                                        nonlabour_musd=cap, natres_base_musd=fva, natres_musd=nat_n,
                                        natres_share_of_nonlabour=(nat_n / cap if cap > 0 else 0.0), cfc_share=cf,
                                        capital_below_cfc=bool(np.isfinite(cf) and cap > 0 and cap_n < cf * cap - TOL),
                                        rent_musd=np.nan, rent_booked_at_s11_output_musd=nat_n, nonlabour_at_s11_output_musd=np.nan,
                                        capped=z['guard']))
                new.append((rr, s, lab_n, ld, cap_n, nat_n))
            rows[-len(sectors):] = new
        else:
            # natural resources out of non-labour income
            nat = dict.fromkeys(sectors, 0.0)
            for s, k in (('oil', 'oil'), ('gas', 'gas'), ('coa', 'coa'), ('for', 'for')):
                want = rent[r][k]
                base = max(nonlab[s], 0.0) * (1.0 - cfc[(r, s)])        # net operating surplus (natres_cap)
                # S13 imposes the S11 output values on coa, oil and gas (GTAP 12 §12.4.3): the rent is set against the
                # non-labour income at that output and booked here as the same share of the io_s11 non-labour income
                scale = 1.0
                o_io, o_t = float(out_io.loc[r, s]), tgt.get((r, s))
                if o_t is not None and o_io > 0 and o_t > 0:
                    scale = o_t / o_io
                share = min(1.0, want / (base * scale)) if base > 0 else 0.0
                nat[s] = share * base
                capped = want > base * scale * (1 + 1e-9) + TOL
                if capped:
                    S.flag('NATRES-CAP', f'{r} {s}', f'rent {want:.1f} m above net operating surplus {base * scale:.1f} m at the S11 output value; capped', rule=V['natres_cap'])
                natres_rows.append(dict(region=r, sector=s, series=RENT_SERIES[k], year=rent_year[k], rent_musd=want,
                                        io_output_musd=o_io, s11_output_musd=(o_t if o_t is not None else np.nan), scale=scale,
                                        nonlabour_musd=nonlab[s], cfc_share=cfc[(r, s)], cfc_source=cfc_src[(r, s)],
                                        nonlabour_at_s11_output_musd=base * scale,
                                        natres_share_of_nonlabour=(nat[s] / nonlab[s] if nonlab[s] > 0 else 0.0), natres_musd=nat[s], rent_booked_at_s11_output_musd=nat[s] * scale,
                                        capped=capped))
            gross = {s: max(nonlab[s], 0.0) for s in ('ore', 'min')}
            base = {s: gross[s] * (1.0 - cfc[(r, s)]) for s in ('ore', 'min')}
            want = rent[r]['mineral']
            tb, tg = sum(base.values()), sum(gross.values())
            left = want
            for s in ('ore', 'min'):
                if V['natres_map'].startswith('oil_petr_gas_ngas_coa_coal_minr_to_ore_first'):
                    w_s = left if s == 'ore' else max(left, 0.0)   # metal ores first (WDI minerals are mostly metals), the rest to min
                else:
                    w_s = want * gross[s] / tg if tg > 0 else 0.0  # split by gross non-labour income, then the net cap
                nat[s] = min(w_s, base[s])
                left = w_s - nat[s]
                natres_rows.append(dict(region=r, sector=s, series=RENT_SERIES['mineral'], year=rent_year['mineral'], rent_musd=w_s,
                                        io_output_musd=float(out_io.loc[r, s]), s11_output_musd=np.nan, scale=1.0,
                                        nonlabour_musd=nonlab[s], cfc_share=cfc[(r, s)], cfc_source=cfc_src[(r, s)],
                                        nonlabour_at_s11_output_musd=base[s],
                                        natres_share_of_nonlabour=(nat[s] / nonlab[s] if nonlab[s] > 0 else 0.0), natres_musd=nat[s],
                                        rent_booked_at_s11_output_musd=nat[s], capped=w_s > nat[s] + TOL))
            if want > sum(nat[s] for s in ('ore', 'min')) + TOL:
                S.flag('NATRES-CAP', f'{r} ore+min', f'mineral rent {want:.1f} m above ore+min net operating surplus {tb:.1f} m; capped', rule=V['natres_cap'])
            if float(va.loc[r, 'fsh']) > 0:
                S.flag('NATRES-FSH', r, 'fishing natural resources zero: no flow source (E10)', rule=V['fishing_natres'])
            rows[-len(sectors):] = [(rr, s, lv, ld, nonlab[s] - nat[s], nat[s]) for (rr, s, lv, ld) in rows[-len(sectors):]]
    if not natres_gtap and V['natres_zero_rent'] == 'ore_min_pool_median_natres_share_of_net_surplus':
        nr_df = pd.DataFrame(natres_rows)
        mm = nr_df[nr_df['sector'].isin(('ore', 'min'))].copy()
        mm['net'] = mm['nonlabour_musd'].clip(lower=0) * (1 - mm['cfc_share'])
        mm['pool'] = [pool_all.get(r_, R.loc[r_, 'gtap_geo']) for r_ in mm['region']]
        reg_want = mm.groupby('region')['rent_musd'].sum()
        obs = mm[(mm['region'].map(reg_want) > 0) & (mm['net'] > 0)].assign(sh=lambda d: d['natres_musd'] / d['net'])
        idx = {(r_, s_): k for k, (r_, s_) in enumerate(zip(nr_df['region'], nr_df['sector']))}
        pos = {(r_[0], r_[1]): k for k, r_ in enumerate(rows)}
        for x in mm[(mm['region'].map(reg_want) <= 0) & (mm['net'] > 0)].itertuples():
            vals = obs.loc[(obs['sector'] == x.sector) & (obs['pool'] == x.pool), 'sh']
            if len(vals) < 3:
                vals = obs.loc[obs['sector'] == x.sector, 'sh']
            if not len(vals):
                continue
            share = float(vals.median())
            nv = share * x.net
            k = pos[(x.region, x.sector)]
            rr, s_, lv, ld, cap, _ = rows[k]
            rows[k] = (rr, s_, lv, ld, cap - nv, nv)
            j = idx[(x.region, x.sector)]
            natres_rows[j] = dict(natres_rows[j], natres_musd=nv, rent_booked_at_s11_output_musd=nv,
                                  natres_share_of_nonlabour=nv / x.nonlabour_musd if x.nonlabour_musd > 0 else 0.0, pool_fill=True)
            S.flag('NATRES-POOL-FILL', f'{x.region} {x.sector}', f'no WDI mineral rent; pool median {share:.3f} of net operating surplus '
                   f'{x.net:.1f} m booked ({nv:.1f} m)', rule=V['natres_zero_rent'])
    # the I-O split in va_split_s12 stays as booked before natural resources; the final labour, capital and natural resources
    # are added beside it (fix round B16 takes natural resources out of labour as well as capital)
    def to_cells(rows_):
        cells_ = []
        for r_, s_, lv, ld, cap, nr in rows_:
            L5 = labsh[r_].loc[sec_of[s_]]
            for g_ in LABOUR5:
                cells_.append((r_, s_, g_, lv * float(L5[g_])))
            cells_ += [(r_, s_, 'land', ld), (r_, s_, 'capital', cap), (r_, s_, 'natres', nr)]
        return pd.DataFrame(cells_, columns=['region', 'sector', 'factor', 'evfp'])

    ft = ftr.pivot_table(index='region', columns='tax_class', values='value_musd', aggfunc='sum')
    sp = sup[sup['basis'].isin(('land', 'capital', 'labour', 'factors'))].pivot_table(index='region', columns='basis', values='value_musd', aggfunc='sum')
    wedge = ('factor_use' if V['factor_support'].startswith('s10_crp_factor_support_as_factor_use_subsidy')
             else 'land_factor_use' if V['factor_support'] == C.SUPPORT_LAND_FACTOR_USE else 'income')

    def region_taxes(r, g):
        t = ft.loc[r] if r in ft.index else pd.Series(dtype=float)
        supp = {b: float(sp.loc[r, b]) if r in sp.index and b in sp.columns and pd.notna(sp.loc[r, b]) else 0.0 for b in ('land', 'capital', 'labour', 'factors')}
        pp = float(t.get('payroll_property', 0.0))
        # ch.15 (w13): the whole GFS payroll and property tax on all factors at one rate; the part D29 holds was moved from the
        # output tax into the factor payments above. A3 alternative (w5): only the D29 payroll part, on labour.
        pp_booked = pp if (ch15 or not a3) else 0.0
        pay = 0.0 if ch15 else payroll_r.get(r, {}).get('payroll_musd', 0.0)
        df, rr = M.factor_taxes(g, float(t.get('ssc', 0.0)), pp_booked, float(t.get('pit', 0.0)), float(t.get('cit', 0.0)), supp,
                                payroll=pay, support_wedge=wedge)
        return df, rr, t, supp, pp, pp_booked, pay

    # ------------------------------------------------------------- 4c. capital-income floor on VDEP (capital_vdep_floor)
    # Our choice, not in the GTAP text (David 2026-10-25, with the Gollin labour): the model needs capital income above
    # depreciation (sum EVOS capital > VDEP, VDEP = 4% of VKB, GTAP 12 ch.7.3). Where the Gollin step leaves a region's
    # capital income (after the ch.15 taxes) below VDEP_FLOOR_RATIO x VDEP, a fraction b of each cell's Gollin addition
    # goes back to capital (one b for the region, the smallest that meets the floor, at most 1 = labour at D1). Cell VA,
    # land and natural resources do not move.
    vdep_rows, ilo_rows = [], []
    add = {}
    if vdep_on or ilo_on:
        for k, (r_, s_, lv, ld, cap, nr) in enumerate(rows):
            x56 = a56.get((r_, s_))
            if x56 is None:
                continue
            share_d1 = M.gollin_share(x56['d1_share'], 0.0, x56['capital_floor'], d1_min)[0]
            a_ = M.gollin_addition(lv, lam[r_][s_], share_d1)
            if a_ > 0:
                add.setdefault(r_, []).append((k, a_))
    pos_of = {}
    for k, x in enumerate(rows):
        pos_of.setdefault(x[0], []).append(k)
    # beta v4 G2/P40 (gollin_ilo_cap; our choice, not in the GTAP text): before the VDEP floor, the Gollin addition goes back
    # to capital (one fraction b per region, all cells pro rata) until labour income is at most the region's ILO SDG 10.4.1
    # labour income share (LAP_2GDP_NOC_RT, base year, GDP-weighted over the members) of S02 GDP; b <= 1 keeps labour >= D1
    if ilo_on:
        for r in R.index:
            mem_ = [r] if r in icio else [m for m, _w, _d in members[r]]
            share = M.region_ilo_share(mem_, gdp, ilo_share, C.ILO_MIN_COVER)
            ks = pos_of.get(r, [])
            adds = dict(add.get(r, []))
            gdp_r = sum(gdp.get(m, 0.0) for m in mem_)
            lab0 = sum(rows[k][2] for k in ks)
            if share is None:
                ilo_rows.append(dict(region=r, ilo_share=np.nan, labour_share_before=lab0 / gdp_r if gdp_r else np.nan,
                                     labour_share_after=lab0 / gdp_r if gdp_r else np.nan, labour_share_d1=np.nan,
                                     returned_share=0.0, returned_musd=0.0))
                continue
            A_ = sum(adds.values())
            b = M.ilo_cap_return(lab0, A_, share * gdp_r)
            if b > 0:
                for k in ks:
                    rr_, s_, lv, ld, cap, nr = rows[k]
                    a_ = adds.get(k, 0.0)
                    rows[k] = (rr_, s_, lv - b * a_, ld, cap + b * a_, nr)
                add[r] = [(k, a_ * (1.0 - b)) for k, a_ in add.get(r, [])]
                S.flag('LAB-ILO-CAP', r, f'labour {lab0 / gdp_r:.3f} of GDP above the ILO SDG 10.4.1 share {share:.3f}; {b:.4f} of the '
                       f'{A_:.1f} m Gollin addition returned to capital', rule=V['gollin_ilo_cap'])
                S.adjust(r, 'labour income capped at the ILO SDG 10.4.1 share of GDP: Gollin addition returned to capital (all cells pro rata)',
                         lab0, lab0 - b * A_, V['gollin_ilo_cap'], 'our choice (not in the GTAP text); ILOSTAT LAP_2GDP_NOC_RT', 'LAB-ILO-CAP')
            ilo_rows.append(dict(region=r, ilo_share=share, labour_share_before=lab0 / gdp_r, labour_share_after=(lab0 - b * A_) / gdp_r,
                                 labour_share_d1=(lab0 - A_) / gdp_r, returned_share=b, returned_musd=b * A_))
    if vdep_on:
        for r in R.index:
            ks = pos_of.get(r, [])
            adds = dict(add.get(r, []))
            target = C.VDEP_FLOOR_RATIO * float(vdep[r])

            def moved(b, ks=ks, adds=adds):
                return [(rr_, s_, lv - b * adds.get(k, 0.0), ld, cap + b * adds.get(k, 0.0), nr)
                        for k, (rr_, s_, lv, ld, cap, nr) in ((k, rows[k]) for k in ks)]

            def evos_at(b, r=r, moved=moved):
                df_ = region_taxes(r, to_cells(moved(b)))[0]
                return float(df_.loc[df_['factor'] == 'capital', 'evos'].sum())
            b, e_ = M.vdep_floor_return(evos_at, target)
            e0 = evos_at(0.0) if b > 0 else e_
            back = b * sum(adds.values())
            vdep_rows.append(dict(region=r, vdep_musd=float(vdep[r]), floor_musd=target, gollin_added_musd=sum(adds.values()),
                                  capital_evos_before_musd=e0, returned_share=b, returned_musd=back, capital_evos_after_musd=e_,
                                  floor_met=e_ >= target - TOL))
            if b > 0:
                new_r = moved(b)
                for k, x in zip(ks, new_r):
                    rows[k] = x
                S.flag('CAPITAL-VDEP-FLOOR', r, f'capital income {e0:.1f} m below {C.VDEP_FLOOR_RATIO} x VDEP {float(vdep[r]):.1f} m after the Gollin step; '
                       f'{b:.4f} of the {sum(adds.values()):.1f} m Gollin addition ({back:.1f} m) returned to capital, capital income {e_:.1f} m',
                       rule=V['capital_vdep_floor'])
                S.adjust(r, 'capital income floor on VDEP: Gollin addition returned from labour to capital (all cells pro rata)', e0, e_,
                         V['capital_vdep_floor'], 'our choice (not in the GTAP text); VDEP GTAP 12 ch.7.3; model needs sum EVOS capital > VDEP',
                         'CAPITAL-VDEP-FLOOR')
    fin = {(r_, s_): (lv, cap, nr_) for r_, s_, lv, ld, cap, nr_ in rows}
    for x in va_rows:
        lv, cap, nr_ = fin[(x['region'], x['sector'])]
        x.update(labour_after_natres_musd=lv, capital_after_natres_musd=cap, natres_musd=nr_)
    ev = to_cells(rows)

    # ------------------------------------------------------------- 5. taxes (ch.15)
    outs, rates = [], []
    for r, g in ev.groupby('region', sort=True):
        df, rr, t, supp, pp, pp_booked, pay = region_taxes(r, g)
        land_drop = 0.0
        if V['land_income_tax_cap'] != 'off':
            # round-3 final QA item 7: the land income tax at most 99% of the land rent (the S13 EVOS floor); the excess dropped
            df, capped = M.cap_land_income_tax(df)
            for s_, b_, a_ in capped:
                land_drop += b_ - a_
                S.adjust(r, f'{s_} land income tax (CIT share)', b_, a_, V['land_income_tax_cap'],
                         'GTAP 12 ch.17B p.3 (no sign violation); S13 EVOS_FLOOR_SHARE', 'LAND-ITAX-CAPPED')
        outs.append(df)
        rates.append(dict(region=r, ssc_rate_on_labour_evfp=rr['r_ssc'], payroll_property_rate_on_evfp=rr['r_pp'],
                          payroll_rate_on_labour_evfp=rr['r_pay'],
                          ssc_musd=float(t.get('ssc', 0.0)), payroll_property_musd=pp, payroll_property_booked_musd=pp_booked,
                          payroll_musd=pay, payroll_fraction_grs=payroll_r.get(r, {}).get('payroll_fraction_grs', 0.0),
                          d29_moved_to_factor_tax_musd=payroll_r.get(r, {}).get('payroll_musd', 0.0),
                          pit_musd=float(t.get('pit', 0.0)), cit_musd=float(t.get('cit', 0.0)), land_itax_dropped_musd=land_drop, support_wedge=wedge,
                          fbep_land_musd=rr['fbep_land'],
                          **{f'support_{k}_musd': v for k, v in supp.items()}))
    ev = pd.concat(outs, ignore_index=True)
    rates = pd.DataFrame(rates)
    otx = pd.DataFrame(otax_rows)
    otx['out_musd'] = [float(out_io.loc[r_, s_]) for r_, s_ in zip(otx['region'], otx['sector'])]
    otx['output_tax_rate_on_out'] = np.where(otx['out_musd'] > 0, otx['output_tax_musd'] / otx['out_musd'].where(otx['out_musd'] > 0, 1.0), 0.0)

    # ------------------------------------------------------------- checks
    va_long = va.stack().rename('va').reset_index().rename(columns={'level_1': 'sector'})
    va_long.columns = ['region', 'sector', 'va']
    va_long = va_long.merge(otx[['region', 'sector', 'output_tax_musd']], on=['region', 'sector'], how='left').fillna({'output_tax_musd': 0.0})
    va_long['va'] = va_long['va'] - va_long.pop('output_tax_musd')      # factor VA: io VA less the output tax (A3)
    n_bad, det = K.factor_sum(ev, va_long)
    S.check('S12-Hsum', 'Eight factors at EVFP plus the output tax (OTAX) add up to io_s11 VA in every region x sector', 'hard', n_bad, 0, n_bad == 0, 'P3 identity', det)
    n_ot, det = K.output_tax_identity(otx)
    S.check('S12-Hotax', 'D29X39 booked once: in every cell the net other production taxes taken out of VA (plus the PSE add-back) equal the payroll part plus the output tax',
            'hard', n_ot, 0, n_ot == 0, 'fix round A3 (E48 reopened)', det)
    n_cp, det = K.crp_no_subsidy_beyond_pse(otx, crp_cap_regions)
    S.check('S12-Hcrppse', 'crp in the FIGARO-estimated economies outside the EU: no output subsidy beyond the PSE add-back (output tax before payroll >= 0)',
            'hard', n_cp, 0, n_cp == 0, 'crp_d29_beyond_pse (QA round 2 P2; ch.11A)',
            det or f'{len(crp_cap_regions)} regions; removed {bn(otx["crp_beyond_pse_removed_musd"].sum()):.1f} bn: '
            + '; '.join(f'{x.region} {bn(x.crp_beyond_pse_removed_musd):.2f}' for x in otx[otx['crp_beyond_pse_removed_musd'] > 0].sort_values('crp_beyond_pse_removed_musd', ascending=False).itertuples()))
    # cells whose share comes wholly through a donor: every sector of an ICIO economy on a ch.9D donor and of a composite
    # with no own-source member, and the sector-donor cells of the own-source ICIO economies (a composite that mixes an
    # own-source member with donor members keeps its own member's share)
    via_only = [(r_, s_) for r_ in R.index for s_ in sectors
                if r_ in donor_of or (r_ not in icio and not any(m_ in na_share for m_, _, _ in members[r_]))
                or (r_ in icio and r_ in na_share and (r_, s_) in flagged and not (r_ == 'USA' and bea_tau))]
    neg_left = [f'{r_} {s_}' for (r_, s_) in via_only if dsign and tau[r_][s_] is not None and tau[r_][s_] < -1e-12]
    S.check('S12-Hdonorsign', 'No negative D29X39 share reaches a region through a donor (sector donor, ch.9D VA donor, S05 member donor)',
            'hard', len(neg_left), 0, not neg_left, 'donor_d29_sign (QA round 2 P2b; ch.9D)',
            ' '.join(neg_left[:10]) or f'{len(donor_neg)} region x sector cells had a negative donor share set to 0, e.g. '
            + '; '.join(f'{r_} {s_} {v_:.3f}' for (r_, s_), v_ in sorted(donor_neg.items(), key=lambda kv: kv[1])[:12]))
    bad_c = [f'{x["iso3"]} {x["sector"]}' for x in d29cell_rows
             if x['iso3'] not in {y['iso3'] for y in d29nat_rows} and abs(float(tau[x['iso3']][x['sector']]) - x['tau_new']) > 1e-9]
    S.check('S12-Hd29cells', 'Listed FIGARO-estimated D29X39 cells carry the rule share (export duty out, national-source median or crp 0; JPN then scaled to its national total)',
            'hard', len(bad_c), 0, not bad_c, 'd29_outlier_cells (QA round 2 P6)',
            ' '.join(bad_c) or '; '.join(f'{x["iso3"]} {x["sector"]} {x["tau_source"]:.3f} -> {tau[x["iso3"]][x["sector"]]:.4f} ({x["rule"]})' for x in d29cell_rows))
    n_fl, det = K.capital_floor(pd.DataFrame(va_rows), d1_min=d1_min) if floor_on else (0, '')
    S.check('S12-Hfloor', 'Every non-hhe, non-crp cell with value added keeps capital plus natural resources of at least its capital floor (CFC) share of factor income'
            + (' (or 1 - its D1 share where D1 is above 1 - floor, labour_at_least_d1)' if d1_min else ''),
            'hard', n_fl, 0, n_fl == 0, 'fix round A6', det)
    n_d1, det = K.labour_at_least_d1(pd.DataFrame(va_rows)) if d1_min else (0, f'off (labour_at_least_d1 {V["labour_at_least_d1"]})')
    S.check('S12-Hd1', 'Beta v4 G1: labour is at least observed compensation of employees (D1) in every non-hhe, non-crp cell with value added, '
            'before natural resources come out pro rata', 'hard', n_d1, 0, n_d1 == 0, 'labour_at_least_d1 (GTAP takes D1 as observed; the floor is ours)', det)
    n_neg, det = K.nonnegative(ev, {(f.split(' ')[0], f.split(' ')[1]) for f in [x['subject'] for x in S.flags if x['id'] == 'NEG-VA']})
    S.check('S12-Hsign', 'Every EVFP, EVFB and EVOS cell is non-negative, except capital in the flagged negative-VA cells', 'hard', n_neg, 0, n_neg == 0, 'PLAN §3k signs', det)
    n_land, det = K.land_only_crp(ev)
    S.check('S12-Hland', 'Land is booked in crp only; natural resources only in coa, oil, gas, ore, min, msp, for, fsh', 'hard', n_land, 0, n_land == 0, 'ch.14A; natres_rule', det)
    n_sh, det = K.group_shares(labsh)
    S.check('S12-Hgroups', 'Labour-group shares are in [0,1] and add up to 1 in every region x section', 'hard', n_sh, 0, n_sh == 0, 'ch.14B eq.14.4', det)
    n2, det = K.two_group(ev)
    S.check('S12-H2grp', 'The 2-group split is an exact aggregation of the 5 groups (skilled = ISCO 1-3)', 'hard', n2, 0, n2 == 0, 'labour_groups', det)
    n_tx, det = K.tax_totals(ev, rates, wedge)
    S.check('S12-Htax', 'Factor employment taxes add up to S10 SSC + payroll/property; income taxes to PIT + CIT less factor-based support', 'hard', n_tx, 0, n_tx == 0, 'ch.15 pp.1-3', det)
    n_li, det = K.land_itax_capped(ev, M.LAND_ITAX_FLOOR_SHARE) if V['land_income_tax_cap'] != 'off' else (0, 'cap off')
    dropped_li = float(rates['land_itax_dropped_musd'].sum())
    S.check('S12-Hlanditax', f'Round-3 final QA item 7 (land_income_tax_cap): no land cell pays an income tax above {1 - M.LAND_ITAX_FLOOR_SHARE:.0%} of its land rent '
            'less its factor-use tax (the S13 EVOS floor); the excess is dropped and ledgered (LAND-ITAX-CAPPED)', 'hard', n_li, 0, n_li == 0,
            'land_income_tax_cap', det or (f'{len(rates[rates["land_itax_dropped_musd"] > 0])} regions capped, {dropped_li:.3f} USD m dropped: '
                                           + '; '.join(f'{x.region} {x.land_itax_dropped_musd:.3f}' for x in rates[rates['land_itax_dropped_musd'] > 0].itertuples())))
    n_cov, det = K.source_coverage(icio, na_share, lam_src, donor_of, partial, len(sectors) - MAX_MISSING)
    S.check('S12-Hcover', 'Every ICIO economy with a FIGARO or OECD Table 6 split uses it; every other one names its ch.9D donor', 'hard', n_cov, 0, n_cov == 0, 'no silent fallback', det)
    if natres_gtap:
        nr_c = pd.DataFrame(natres_rows)
        n_eta, det = K.natres_eta(ev, nr_c[['region', 'sector', 'cost_musd', 'eta_target', 'sigma_va', 'guard', 'theta_va_used']])
        S.check('S12-Heta', 'In every natural-resource cell (for, fsh, coa, oil, gas, ore, min, msp) with value added and no guard, the booked factors give '
                'the ch.12.A target supply elasticity sigma_VA (1/theta_R - 1/theta_VA) within 1e-6; a guarded cell has the share at the theta_VA floor',
                'hard', n_eta, 0, n_eta == 0, 'natres_rule (fix round B16, David 2026-10-24); ch.12.A pp.2-3', det)
        n_pr, det = K.natres_pro_rata(nr_c)
        S.check('S12-Hnatpro', 'Natural resources come out of labour and capital pro rata: both fall by the same factor and the cell total is kept',
                'hard', n_pr, 0, n_pr == 0, 'natres_rule; ch.12.A p.2 (out of all value added)', det)
        gd = nr_c[nr_c['guard'] & (nr_c['factor_va_musd'] > 0)]
        S.check('S12-Rnatguard', f'Natural-resource cells held by the guard (theta_VA below {theta_floor}; supply elasticity above the target)', 'report',
                len(gd), 0, True, 'natres_guard (our choice)',
                '; '.join(f'{x.region} {x.sector} theta_VA {x.theta_va:.4f} share {x.natres_share_of_va:.3f} eta {x.eta_implied:.3f} VA {bn(x.factor_va_musd):.3f} bn'
                          for x in gd.sort_values('factor_va_musd', ascending=False).itertuples()))
        lc = nr_c[nr_c['capital_below_cfc']]
        S.check('S12-Rcfc', 'Natural-resource cells where capital, after the ch.12.A share is taken out of all value added, is below its consumption of fixed capital '
                '(the WDI rule kept it at CFC; ch.12.A takes the share out of labour and capital pro rata)', 'report',
                len(lc), 0, True, 'natres_rule', f'{bn((lc["cfc_share"] * lc["capital_before_musd"] - lc["capital_musd"]).sum()):.1f} bn below CFC; '
                + ' '.join(f'{x.region}:{x.sector}' for x in lc.sort_values('capital_before_musd', ascending=False).head(30).itertuples()))
    else:
        n_cfc, det = K.capital_keeps_cfc(pd.DataFrame(natres_rows))
        S.check('S12-Hcfc', 'Capital keeps at least its consumption of fixed capital in every extraction and forestry cell (natural resources capped at net operating surplus)',
                'hard', n_cfc, 0, n_cfc == 0, 'natres_cap (David 2026-10-23)', det)
    cap_neg = int(((ev['factor'] == 'capital') & (ev['evfp'] < -TOL)).sum())
    S.check('S12-Rnegcap', 'Capital cells below zero (negative VA only)', 'report', cap_neg, 0, True, 'negative_va')

    vr_df = pd.DataFrame(va_rows)
    S.check('S12-Rotax', 'Other net production taxes (D29X39) out of VA: output tax, payroll part on labour and PSE add-back (USD bn)', 'report',
            f'output tax {bn(otx["output_tax_musd"].sum()):.1f}; payroll on labour {bn(otx["payroll_musd"].sum()):.1f}; '
            f'PSE add-back {bn(otx["pse_addback_musd"].sum()):.1f}; D29X39 in VA {bn(otx["otp_musd"].sum()):.1f}', '', True, 'other_production_taxes')
    nz = vr_df[(vr_df['sector'] != 'hhe') & (vr_df['va_musd'] > 0)]
    S.check('S12-Rgollin', 'Cells whose labour share is capped at one less the capital floor (Gollin or D1 above the floor), of non-hhe cells with VA', 'report',
            f'{int(nz["labour_capped"].sum())} of {len(nz)}; D1 alone above the floor {int(nz["floor_binds_on_d1"].sum())}', '', True, 'labour_share_bounds')
    vf = pd.DataFrame(vdep_rows, columns=['region', 'vdep_musd', 'floor_musd', 'gollin_added_musd', 'capital_evos_before_musd',
                                          'returned_share', 'returned_musd', 'capital_evos_after_musd', 'floor_met'])
    n_vf, det = K.vdep_floor(ev, vf) if vdep_on else (0, f'off (labour_definition {V["labour_definition"]}, capital_vdep_floor {V["capital_vdep_floor"]})')
    hit = vf[vf['returned_share'] > 0]
    S.check('S12-Hvdepk', f'Capital income (sum EVOS capital) at least {C.VDEP_FLOOR_RATIO} x VDEP in every region after the Gollin step, '
            'or the whole Gollin addition back in capital (labour at D1)', 'hard', n_vf, 0, n_vf == 0,
            'capital_vdep_floor (our choice); VDEP GTAP 12 ch.7.3; model_requirements identity 12',
            det or (f'{len(hit)} regions returned: ' + '; '.join(f'{x.region} {x.capital_evos_before_musd:.1f} -> {x.capital_evos_after_musd:.1f} m '
                                                               f'(VDEP {x.vdep_musd:.1f}, {x.returned_share:.4f} of {x.gollin_added_musd:.1f} m)'
                                                               for x in hit.itertuples()) if vdep_on else ''))

    il = pd.DataFrame(ilo_rows, columns=['region', 'ilo_share', 'labour_share_before', 'labour_share_after', 'labour_share_d1',
                                       'returned_share', 'returned_musd'])
    capped = il[il['returned_share'] > 0]
    S.check('S12-Rilocap', 'Beta v4 G2/P40: regions whose Gollin labour is capped at the ILO SDG 10.4.1 labour income share of GDP '
            '(labour share of S02 GDP before -> after; b = share of the Gollin addition returned to capital, 1 = D1)', 'report',
            len(capped) if ilo_on else 0, '', True, 'gollin_ilo_cap (our choice, not in the GTAP text); ILOSTAT LAP_2GDP_NOC_RT',
            (f'{len(capped)} of {int(il["ilo_share"].notna().sum())} regions with an ILO share; '
             + '; '.join(f'{x.region} {x.labour_share_before:.3f} -> {x.labour_share_after:.3f} (ILO {x.ilo_share:.3f}, b {x.returned_share:.3f})'
                         for x in capped.itertuples())) if ilo_on else f'off (gollin_ilo_cap {V["gollin_ilo_cap"]})')

    # report-only benchmarks (concept: like with like, so report only)
    econ = ev.assign(lab=ev['factor'].isin(LABOUR5) * ev['evfp']).groupby('region')[['lab', 'evfp']].sum()
    econ['share'] = econ['lab'] / econ['evfp']
    pw = pwt[pwt['year'] <= BASE_YEAR].sort_values('year').groupby('countrycode').tail(1).set_index('countrycode')['labsh'] if 'labsh' in pwt.columns else pd.Series(dtype=float)
    gap = {r: econ.loc[r, 'share'] - pw[r] for r in econ.index if r in pw.index and pd.notna(pw[r])}
    far = sorted(((r, g) for r, g in gap.items() if abs(g) > 0.10), key=lambda x: -abs(x[1]))
    S.check('S12-Rpwt', 'Economy labour share (D1 basis) against PWT labsh (adds self-employed income): regions more than 10 points apart',
            'report', len(far), 0, True, 'PLAN §3h check; concept differs (Gollin), report only',
            '; '.join(f'{r} {econ.loc[r, "share"]:.3f} vs {pw[r]:.3f}' for r, _ in far[:40]))
    tt = t6tot[(t6tot['item'].isin(('D1', 'B2A3G'))) & (t6tot['year'] == BASE_YEAR)].pivot_table(index='iso3', columns='item', values='value')
    dchk = []
    for r, d in donor_of.items():
        if r in tt.index and tt.loc[r].notna().all():
            dchk.append(f'{r} {econ.loc[r, "share"]:.3f} vs national {tt.loc[r, "D1"] / (tt.loc[r, "D1"] + tt.loc[r, "B2A3G"]):.3f}')
    S.check('S12-Rdonor', 'Donor-split ICIO economies against their own national total D1/(D1+B2A3G), where published', 'report',
            len(dchk), '', True, 'va_no_source_rule', '; '.join(dchk))
    S.check('S12-Rsur', 'ch.14A SUR fit (labour, capital) on KF 2011-2020', 'report', f'n {n_sur}; sd {sd_lab:.3f}, {sd_kap:.3f}', '', True,
            'ag_fill', f'labour {np.round(b_lab, 4).tolist()}; capital {np.round(b_kap, 4).tolist()} on (1, log GDP pc, log arable pc)')
    nused = int((lmeta['status'] == 'used').sum())
    S.check('S12-Rilo', 'ILOSTAT countries with an adequate common window (ch.14B p.6)', 'report', nused, '', True, 'labour_year_window',
            'matrix: ' + (lmeta.loc[lmeta['status'] == 'used', 'n_matrix'].value_counts().to_dict().__repr__() if 'n_matrix' in lmeta else ''))
    stale = lmeta[(lmeta['status'] == 'used') & lmeta['years'].fillna('').map(lambda y: bool(y.split()) and max(map(int, y.split())) < 2019)]
    S.check('S12-Rstale', 'Labour windows that end before 2019 (SCREENS.md question 4)', 'report', len(stale), 0, True, 'labour_year_window',
            ' '.join(f'{c}:{y}' for c, y in zip(stale['iso3'], stale['years'])))
    if V['labour_national_tables'] == C.LABOUR_NATIONAL:
        miss_n = [r_['iso3'] for r_ in nat_rows if r_['iso3'] in R.index and not lab_src[r_['iso3']].startswith('national')]
        S.check('S12-Hnational', 'Every listed national occupation x industry table read for the base year is the labour split of its region (B-02, ch.14B F16a)',
                'hard', len(miss_n), 0, not miss_n, 'labour_national_tables',
                ' '.join(miss_n) or '; '.join(f'{r_["iso3"]} {r_["source"]} {r_["year"]} ({r_["kind"]}; occupation wages {r_.get("occ_wage_source", "")})' for r_ in nat_rows))
        # skilled (ISCO 1-3: off_mgr_pros + tech_aspros) share of the labour bill before and after, on the region's own
        # labour bill by ISIC section (Fable QA review of B-02: the direction each economy moved)
        lb = ev[ev['factor'].isin(LABOUR5)].assign(section=lambda d: d['sector'].map(sec_of)).groupby(['region', 'section'])['evfp'].sum()
        sk_det = []
        for r_ in nat_rows:
            c = r_['iso3']
            if c not in R.index or c not in pre_lab:
                continue
            w_ = lb.loc[c].reindex(list(SECTIONS)).fillna(0.0)
            new_ = labsh[c][['off_mgr_pros', 'tech_aspros']].sum(axis=1).reindex(list(SECTIONS)).fillna(0.0)
            old_ = pre_lab[c][0][['off_mgr_pros', 'tech_aspros']].sum(axis=1).reindex(list(SECTIONS)).fillna(0.0)
            r_.update(skilled_share_before=float((w_ * old_).sum() / w_.sum()), skilled_before_source=pre_lab[c][1],
                      skilled_share_after=float((w_ * new_).sum() / w_.sum()))
            no_ = np.asarray(tabs[c]['N_occ'], float)
            r_['skilled_employment_share'] = float(no_[:3].sum() / no_.sum())
            sk_det.append(f'{c} {r_["skilled_share_before"]:.3f} ({pre_lab[c][1]}) -> {r_["skilled_share_after"]:.3f}')
            # a move of more than NATIONAL_SHIFT is kept (it is the economy's own table and wages) but flagged for review
            if abs(r_['skilled_share_after'] - r_['skilled_share_before']) > C.NATIONAL_SHIFT:
                S.flag('LAB-NATIONAL-SHIFT', c, f'skilled (ISCO 1-3) share of the labour bill {r_["skilled_share_before"]:.3f} '
                       f'({pre_lab[c][1]}) -> {r_["skilled_share_after"]:.3f} on {r_["skilled_employment_share"]:.3f} of employment '
                       f'({r_["source"]} {r_["year"]}); occupation wages {r_.get("occ_wage_source", "")}', rule=V['labour_national_tables'])
        S.check('S12-Rnational', 'Skilled (ISCO 1-3) share of the labour bill in each national-table economy, before (ILOSTAT window or F16c) and after (B-02)',
                'report', len(sk_det), '', True, 'labour_national_tables', '; '.join(sk_det))
        S.write('national_labour_s12.csv', pd.DataFrame(nat_rows))
    lab_bill = ev[ev['factor'].isin(LABOUR5)].groupby('region')['evfp'].sum()
    f16 = [r_ for r_ in R.index if lab_src[r_].startswith('F16c')]
    S.check('S12-Rf16c', 'Labour bill of regions whose labour split is wholly an F16c regional average (B-02 measure)', 'report',
            f'{bn(lab_bill.reindex(f16).fillna(0).sum()):.1f} bn, {lab_bill.reindex(f16).fillna(0).sum() / lab_bill.sum():.3f} of the world labour bill; {len(f16)} regions',
            '', True, 'labour_no_data', ' '.join(f16[:60]))
    nr = pd.DataFrame(natres_rows)
    if natres_gtap:
        bys = nr.groupby('sector')[['natres_musd', 'factor_va_musd']].sum()
        S.check('S12-Rnatres', 'Natural resources booked by the ch.12.A target rule: world total and share of value added by sector (USD bn)', 'report',
                f'{bn(nr["natres_musd"].sum()):.1f} of {bn(nr["factor_va_musd"].clip(lower=0).sum()):.1f} VA in the resource sectors; {int(nr["guard"].sum())} guarded cells',
                '', True, 'natres_rule', '; '.join(f'{k} {bn(x.natres_musd):.1f} ({x.natres_musd / x.factor_va_musd:.3f} of VA)' for k, x in bys.iterrows() if x.factor_va_musd > 0))
    else:
        S.check('S12-Rnatres', 'Natural-resource rents booked and capped (USD bn)', 'report',
                f'booked at S11 output values {bn(nr["rent_booked_at_s11_output_musd"].sum()):.1f} (io_s11 scale {bn(nr["natres_musd"].sum()):.1f}); '
                f'wanted {bn(nr["rent_musd"].sum()):.1f}; {int(nr["capped"].sum())} capped cells', '', True, 'natres_cap')

    tracked = subprocess.run(['git', '-C', BUILD, 'ls-files', '--full-name', ROOT.rsplit('/', 1)[0]], capture_output=True, text=True).stdout.split()
    priv = private_paths(tracked)
    S.check('S12-Hprivate', 'No private file (credentials, GTAP database values) is tracked in git (lib/private_files.py)', 'hard',
            len(priv), 0, not priv, 'repo_rules committed_data_rule', ' '.join(priv[:10]))

    sec = K.secret_scan([BUILD + '/s12_factors.py', BUILD + '/s12_factors', BUILD + '/screens/s12_suite.py', C.CONFIG_DIR, S.out])
    S.check('S12-Hsecret', 'Key and password scan of the S12 code, config and outputs (count only)', 'hard', sec, 0, sec == 0, 'never commit credentials')

    # ------------------------------------------------------------- screens
    nat_share = {}
    for r in icio:
        g = fig[fig['iso3'] == r]
        if len(g):
            g = g[[SRC.activity_divisions(a, section_divs) is not None for a in g['activity']]]
            d1, b2 = g.loc[g['item'] == 'D1', 'value'].sum(), g.loc[g['item'] == 'B2A3G', 'value'].sum()
            if d1 + b2 > 0:
                nat_share[r] = (d1 / (d1 + b2), f'FIGARO {BASE_YEAR} all industries')
                continue
        if r in tt.index and tt.loc[r].notna().all():
            nat_share[r] = (tt.loc[r, 'D1'] / (tt.loc[r, 'D1'] + tt.loc[r, 'B2A3G']), f'OECD Table 6 {BASE_YEAR} total economy')
    if gollin_on:
        mt = ste_ok.groupby('iso3')[['slf', 'ees']].sum()
        for r in list(nat_share):
            d_ = gollin_for(r)
            if d_ in mt.index and mt.loc[d_, 'ees'] > 0:
                k_ = 1.0 + mt.loc[d_, 'slf'] / mt.loc[d_, 'ees']
                nat_share[r] = (min(nat_share[r][0] * k_, 0.95), nat_share[r][1] + f'; x (1 + SLF/EES {k_ - 1:.3f}, ILOSTAT {d_}), at most 0.95 (Gollin)')
    share_years = {}
    for c in na_share:
        if na_src[c].startswith('FIGARO'):
            if fig_prev is None:
                continue
            pg, psrc = fig_prev[fig_prev['iso3'] == c], f'FIGARO {BASE_YEAR} against 2017'
        else:
            y = int(na_src[c].split()[-1])
            ys = sorted(set(t6all.loc[(t6all['iso3'] == c) & (t6all['year'] < y), 'year']))
            if not ys:
                continue
            pg, psrc = t6all[(t6all['iso3'] == c) & (t6all['year'] == ys[-1])], f'OECD Table 6 {y} against {ys[-1]}'
        prev = M.labour_shares_from_na(pg, sector_divs, section_divs, SRC.activity_divisions) if len(pg) else {}
        for s_ in sectors:
            if na_share[c][s_]['share'] is not None and s_ in prev and prev[s_]['share'] is not None and s_ != 'crp':
                share_years[(c, s_)] = (na_share[c][s_]['share'], prev[s_]['share'], psrc)
    cell_note = {k: '; '.join(v[:6]) + (f'; and {len(v) - 6} more' if len(v) > 6 else '') for k, v in prov.items()}
    sector_donor = {tuple(f['subject'].split(' ')) for f in S.flags if f['id'] == 'VA-SECTOR-DONOR'}
    prev_out = os.environ.get('S12_PREV_OUTPUT')
    ctx = dict(ev=ev, va_long=va_long, va_rows=pd.DataFrame(va_rows), natres=nr, rates=rates, lmeta=lmeta, lam_src=lam_src,
               lab_src=lab_src, labour5=LABOUR5, national_share=nat_share, share_years=share_years, cell_note=cell_note,
               sector_donor=sector_donor,
               prev=pd.read_csv(prev_out + '/factors_s12.csv.gz') if prev_out else None)
    try:
        scr = SCR.run(ctx, log=S.log)
        S.check('S12-Hscreens', 'Population screens (SCREENS.md seven questions plus natres caps): no material unexplained hit', 'hard',
                scr['material_unexplained'], 0, scr['material_unexplained'] == 0, 'screen_materiality', scr['summary'])
    except Exception as e:   # a screen that raises fails the stage
        S.check('S12-Hscreens', 'Population screens ran', 'hard', repr(e)[:200], 'no exception', False, 'screen_materiality')
        raise

    # ------------------------------------------------------------- outputs
    def gzcsv(name, df):
        """gzip with mtime 0, so two runs give the same bytes (the S11 pattern)."""
        with gzip.GzipFile(f'{S.out}/{name}', 'wb', mtime=0) as fh:
            fh.write(df.to_csv(index=False).encode())
        S.log(f'output {name}: {len(df)} rows')

    ev = ev.sort_values(['region', 'sector', 'factor']).reset_index(drop=True)
    for c in ('evfp', 'ftax', 'evfb', 'itax', 'fbep', 'evos'):
        ev[c] = ev[c].round(6)
    gzcsv('factors_s12.csv.gz', ev[['region', 'sector', 'factor', 'evfp', 'ftax', 'evfb', 'itax', 'fbep', 'evos']])
    two = ev.assign(group=np.where(ev['factor'].isin(SKILLED), 'skilled', np.where(ev['factor'].isin(LABOUR5), 'unskilled', ev['factor'])))
    gzcsv('factors2_s12.csv.gz', two.groupby(['region', 'sector', 'group'], as_index=False)[['evfp', 'evfb', 'evos']].sum().round(6))
    S.write('va_split_s12.csv', pd.DataFrame(va_rows).round(6))
    if vdep_on:
        S.write('vdep_floor_s12.csv', vf.round(6))
    if ilo_on:
        S.write('ilo_cap_s12.csv', il.round(6))
    S.write('natres_s12.csv', nr.round(6))
    S.write('output_tax_s12.csv', otx.round(9))
    if bea_groups:
        S.write('usa_d29_bea_s12.csv', pd.DataFrame(bea_groups).round(9))
    if d29nat_rows:
        S.write('d29_national_s12.csv', pd.DataFrame(d29nat_rows).round(9))
    if d29cell_rows:
        S.write('d29_cells_s12.csv', pd.DataFrame(d29cell_rows).round(9))
    S.write('ag_shares_s12.csv', pd.DataFrame([dict(region=r, **{k: round(v, 6) for k, v in ag[r].items()}) for r in R.index]))
    lg_rows = [dict(region=r, section=sec, **{g: round(float(labsh[r].loc[sec, g]), 6) for g in LABOUR5}, source=lab_src[r])
               for r in R.index for sec in SECTIONS]
    S.write('labour_shares_s12.csv', pd.DataFrame(lg_rows))
    S.write('labour_countries_s12.csv', lmeta)
    S.write('factor_tax_s12.csv', rates.round(9))
    S.write('va_sources_s12.csv', pd.DataFrame([dict(region=r, source=lam_src[r], donor=donor_of.get(r, '')) for r in R.index]))
    io12 = K.io_with_factors(io, ev, sectors, otax=otx)
    gzcsv('io_s12.csv.gz', io12)
    with open(S.out + '/NOT_FOR_PUBLICATION.md', 'w') as f:
        f.write('# Not for publication\n\nio_s12.csv.gz and factors_s12.csv.gz carry the S10 tariff wedge through io_s10/io_s11 (TRAINS-derived). '
                'Keep them out of any public release, as for S10 and S11.\n')
    S.finish()


if __name__ == '__main__':
    main()
