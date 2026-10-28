#!/usr/bin/env python3
"""S14 final assembly (GTAP 12 ch.17B §B.2; PLAN §3(i) global pass; READINESS §1 S14 gate).

The interim global file from FIT (io_s13, factors_s13) is merged with the bilateral trade data (S10 goods,
S11 energy, S09 services and travel), the margins by route (S08 goods, S11 energy), the protection data in
those flows, and the capital stock, depreciation and population (S02). The result is the 31 GTAPv7 data
headers the Julia model reads (notes/model_requirements.md §1b), as long tables for S15 to write as HAR.

The data base is then re-balanced (rounding only, bounded; see s14_assembly/method.py) and checked for
supply = demand, income = expenditure, sign violations and zero-divides (17B p.3), and the pre-solve S-I gate
(PLAN §3(h)3, E12, E28). Regional SAVE is GTAP's residual (ch.7 eq. 7.1). Choices come from
config/s14/s14_choices.csv (s14_assembly/config.py).
"""
import gzip
import os
import subprocess
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.stagekit import Stage, ROOT, BUILD, STAGES, DATA  # noqa: E402
from lib import macro_external as MX  # noqa: E402
from lib.private_files import private_paths  # noqa: E402
from s13_fit import method as M13  # noqa: E402
from s13_fit import checks as K13  # noqa: E402
from s13_fit.method import FACTORS, MARGINS, ENERGY_TRADE, FD  # noqa: E402
from s14_assembly import config as C  # noqa: E402
from s14_assembly import method as M  # noqa: E402
from s14_assembly import checks as K  # noqa: E402
from s12_factors.checks import secret_scan  # noqa: E402
from s12_factors import config as C12  # noqa: E402
import screens.s14_suite as SCR  # noqa: E402

UP = {
    'S01': STAGES + '/S01_sets_registry',
    'S02': STAGES + '/S02_macro',
    'S08': STAGES + '/S08_margins',
    'S09': STAGES + '/S09_services',
    'S10': STAGES + '/S10_tariffs_taxes',
    'S11': STAGES + '/S11_energy',
    'S12': STAGES + '/S12_factors',
    'S13': STAGES + '/S13_fit',
}
FLOAT = '%.12g'


def bn(x):
    return x / 1000.0


def listed_upstreams(stage_dir):
    """{upstream name: SHA256SUMS} as listed in a STAMP."""
    p = stage_dir + '/STAMP'
    out = {}
    if os.path.exists(p):
        for line in open(p).read().splitlines():
            if line.startswith('upstream '):
                parts = line.split()
                out[parts[1]] = parts[-1]
    return out


def main():
    choices = C.load_choices()
    V = {k: r['value'] for k, r in choices.items()}
    S = Stage('S14', 'final_assembly')
    I = S.inp
    S.check('S14-Hconfig', f'config/s14/s14_choices.csv has the {len(C.CHOICES)} choices this code implements, each with decided_by and decided_at',
            'hard', len(choices), len(C.CHOICES), len(choices) == len(C.CHOICES), 's14_choices',
            'Choices not in the GTAP text: ' + ', '.join(k for k, r in choices.items() if r['gtap_status'] in ('departure_logged', 'not_in_gtap_text')))
    for k in UP.values():
        S.upstream(k)
    I(C.CHOICES_PATH, 'S14 choices')
    # fix round B16 on the S14 data (GTAP 12 ch.17B; ch.12.A): S12's targets, sigma_VA and guard
    natres_on = V['natres_final'] == 'gtap_ch12a_target_elasticity_on_s14_data_labour_capital_pro_rata'
    natres_cfg = None
    if natres_on:
        c12 = C12.load_choices(I(C12.CHOICES_PATH, 'S12 choices (natres_rule, natres_guard for the B16 step)'))
        if c12['natres_rule']['value'] != 'gtap_ch12a_target_supply_elasticity_share_out_of_all_va':
            raise C.ConfigError('natres_final applies the ch.12.A rule on the S14 data, but S12 natres_rule is '
                                f"{c12['natres_rule']['value']}; set natres_final to as_s13_s12_prior_shares")
        nt = C12.load_natres_targets(I(C12.NATRES_TARGETS_PATH, 'S12 natural-resource targets and sigma_VA (ch.12.A, ch.16)'))
        nat_config = {k: dict(eta=v['eta'], sigma=v['sigma']) for k, v in nt.items()}
        nat_blend = dict(sector='msp', fossil='oil') if c12['msp_natres_target']['value'] == C12.MSP_BLEND else None
        # fix round w17: the target of each cell is the one S12 booked (natres_s12.csv): the config's, or for msp under
        # the w13 blend the region's effective eta (S14-Hnatcfg checks the booking against the rule)
        nat12 = pd.read_csv(I(UP['S12'] + '/output/natres_s12.csv', 'S12 natural resources by cell (B16 targets as booked)'))
        if not {'eta_target', 'sigma_va'} <= set(nat12.columns):
            raise C.ConfigError('natres_final applies the targets S12 booked, but natres_s12.csv has no eta_target or sigma_va column '
                                '(S12 not run under the ch.12.A rule)')
        natres_cfg = dict(targets={(x.region, x.sector): dict(eta=float(x.eta_target), sigma=float(x.sigma_va))
                                   for x in nat12.dropna(subset=['eta_target']).itertuples()},
                          floor=C12.NATRES_GUARD_FLOOR[c12['natres_guard']['value']])

    # ------------------------------------------------------------- inputs
    regions = pd.read_csv(I(UP['S01'] + '/output/regions.csv', 'S01 regions'))
    sectors = pd.read_csv(I(UP['S01'] + '/output/sectors.csv', 'S01 sectors'))['sector'].tolist()
    macro = pd.read_csv(I(UP['S02'] + '/output/macro_regions.csv', 'S02 VKB, VDEP, POP, GDP'))
    bop = pd.read_csv(I(UP['S02'] + '/output/memo_bop_net_flows.csv', 'S02 BoP memo (net primary and secondary income)'))
    vt8 = pd.read_csv(I(UP['S08'] + '/output/vtwr_s08.csv.gz', 'S08 VTWR by route (goods)'))
    svc = pd.read_csv(I(UP['S09'] + '/output/vxsb_services_s09.csv.gz', 'S09 services VXSB by route'))
    trv = pd.read_csv(I(UP['S09'] + '/output/travel_s09.csv.gz', 'S09 travel goods by host and visitor'))
    gx = pd.read_csv(I(UP['S10'] + '/output/vfob_s10.csv.gz', 'S10 goods VXSB/VFOB by route'))
    gm = pd.read_csv(I(UP['S10'] + '/output/vmsb_s10.csv.gz', 'S10 goods VCIF/VMSB by route'))
    ex = pd.read_csv(I(UP['S11'] + '/output/vfob_energy_s11.csv.gz', 'S11 energy VXSB/VFOB by route'))
    xt10 = pd.read_csv(I(UP['S10'] + '/output/export_tax_s10.csv', 'S10 export-tax rates (fix list A2: S14-Hxtax)'))
    em = pd.read_csv(I(UP['S11'] + '/output/vmsb_energy_s11.csv.gz', 'S11 energy VCIF/VMSB by route'))
    vte = pd.read_csv(I(UP['S11'] + '/output/vtwr_energy_s11.csv.gz', 'S11 VTWR by route (energy)'))
    vst11 = pd.read_csv(I(UP['S11'] + '/output/vst_s11.csv', 'S11 VST'))
    io12 = pd.read_csv(I(UP['S12'] + '/output/io_s12.csv.gz', 'io_s12 (S13 B06 travel split)'))
    io13 = pd.read_csv(I(UP['S13'] + '/output/io_s13.csv.gz', 'io_s13 (FIT interim global file)'))
    fac13 = pd.read_csv(I(UP['S13'] + '/output/factors_s13.csv.gz', 'factors_s13'))
    trade13 = pd.read_csv(I(UP['S13'] + '/output/trade_s13.csv.gz', 'S13 held trade by region and commodity'))
    macro13 = pd.read_csv(I(UP['S13'] + '/output/macro_s13.csv', 'S13 C, G, I targets'))
    drop13 = pd.read_csv(I(UP['S13'] + '/output/travel_dropped_s13.csv', 'S13 travel dropped on energy goods'))
    tgt13 = pd.read_csv(I(UP['S13'] + '/output/energy_targets_s13.csv', 'S13 energy output targets used (after the P1 ely floor and P38)'))
    cell_on = V['purchaser_split'] != 'one_tax_power_per_column_dom_and_imp_from_s13'
    cells13 = pd.read_csv(I(UP['S13'] + '/output/tax_cells_s13.csv.gz', 'S13 net product-tax rate by cell (fix list A1)')) if cell_on else None
    # fix round wG: S13 PSE input items (a listed farm input subsidy on its own row of the crp column, own rate)
    pi_path = UP['S13'] + '/output/pse_input_items_s13.csv'
    pse_items = ({(x.region, 'crp', x.input_row) for x in pd.read_csv(I(pi_path, 'S13 PSE input items (fix round wG)')).itertuples()}
                 if cell_on and os.path.exists(pi_path) else set())
    # fix list A3/A4: optional S12 tax splits (stub; the coordinator joins them, see s14_assembly/method.py)
    s12_opt = {}
    for name, fn in M.S12_OPTIONAL.items():
        for p_ in (f"{UP['S12']}/output/{fn}", f"{UP['S12']}/output/{fn}.gz"):
            if os.path.exists(p_):
                s12_opt[name] = pd.read_csv(I(p_, f'S12 {name} (fix list A3/A4)'))

    regs = sorted(regions['region'])
    if sorted(io13['region'].unique()) != regs:
        raise SystemExit('io_s13 regions do not match the S01 regions')
    sums = {u['name']: (u['actual_sums'], listed_upstreams(p)) for p, u in S.upstreams.items()}
    n, det = K.chain(sums)
    S.check('S14-Hchain', 'Each upstream read here is the one the other upstreams were stamped on (SHA256SUMS listed in their STAMPs)', 'hard',
            n, 0, n == 0, 'P7; 17B p.5-6 staged hand-off', det)

    # ------------------------------------------------------------- 1. trade block
    # The travel rows S13 held: S13's own assembly (s13_fit.method.assemble_trade) on the same inputs.
    # beta v4: the targets S13 used, after the P1 ely floor and P38 (S11 energy_values alone missed both: S14-Htravel and
    # S14-Hmerge failed on MOZ ely, BLR gas and NPL coal)
    tout = {(r.region, r.commodity): float(r.output_value) for r in tgt13.itertuples()}
    trade_re, travel_used, dropped = M13.assemble_trade(gx[~gx['sector'].isin(ENERGY_TRADE)], gm[~gm['sector'].isin(ENERGY_TRADE)],
                                                        ex, em, svc, trv, vst11, M13.b06_split(io12, sectors), tout)
    S.log(f'travel rows held by S13 rebuilt: {len(travel_used)}; dropped {dropped["v"].sum():.6f} USD million (S13 file {drop13["musd"].sum():.6f})')
    gap = abs(dropped['v'].sum() - drop13['musd'].sum())
    S.check('S14-Htravel', 'The travel rebuild drops the same energy travel as S13 (travel_dropped_s13, USD million)', 'hard',
            f'{dropped["v"].sum():.6f} vs {drop13["musd"].sum():.6f}', 'gap <= 1e-6', gap <= 1e-6 and len(dropped) == len(drop13), 'S13 energy_travel')
    B = M.bilateral(gx, gm, ex, em, svc, travel_used)
    Vt = M.margins(vt8, vte)
    vst = vst11.rename(columns={'margin': 'marg', 'vst_musd_s11': 'VST'})[['marg', 'region', 'VST']]
    n, det = K.merge_totals(B, vst, trade13)
    S.check('S14-Hmerge', 'The bilateral flows add up to the trade S13 held, by region and commodity (VXSB, VFOB, VMSB, VCIF, VST)', 'hard',
            n, 0, n == 0, '17B §B.2 merge of the interim file with the trade data', det)
    # the trade S13 held, by region and commodity, before the S14 trade rules (B14, re-balancing, A13 swaps): trade_moves_s14.csv
    held_xmv = (B.groupby(['src', 'comm'])['VXSB'].sum(), B.groupby(['dst', 'comm'])['VMSB'].sum(), vst.groupby(['region', 'marg'])['VST'].sum())
    # B14: trade cells below USD 1 set to zero, before the re-balancing and before the A13 seed
    small_on = V['small_trade'] != 'keep_all'
    shift = pd.Series(dtype=float)
    if small_on:
        Vt_pre, vst_pre = Vt, vst
        B, Vt, small = M.filter_small_trade(B, Vt, M.SMALL_TRADE)
        vst = M.small_trade_vst(vst, Vt_pre, Vt)
        shift = M.small_trade_output_shift(small, vst_pre, vst)
    else:
        small = pd.DataFrame(columns=['kind', 'marg', 'comm', 'src', 'dst', 'VXSB', 'VTWR'])
    for (src, kind), g_ in small.groupby(['src', 'kind']):
        col = 'VXSB' if kind == 'VXSB route' else 'VTWR'
        S.adjust(src, f'B14 {kind}s below USD 1 set to zero ({len(g_)}, {col} USD million)', float(g_[col].sum()), 0.0, M.RULE_SMALL,
                 'fix list B14 (QA#17), David 2026-10-24; our choice: GTAP filters small values, its threshold is not in the documents we hold', 'SMALL-TRADE')
    S.log(f'B14: {int((small["kind"] == "VXSB route").sum())} routes ({small["VXSB"].sum():.6f} USD million VXSB) and '
          f'{int((small["kind"] == "VTWR cell").sum())} margin cells ({small.loc[small["kind"] == "VTWR cell", "VTWR"].sum():.6f} USD million) set to zero')
    B, vst, tmoves = M.rebalance_trade(B, Vt, vst)
    S.log(f'trade re-balancing: {len(tmoves)} moves, largest {(tmoves["after"] - tmoves["before"]).abs().max() if len(tmoves) else 0:.3g} USD million')
    # A13, the other side: seed imports in the pairs bought only from domestic producers (a swap with a partner exporter)
    swap_switch = {}
    swaps = pd.DataFrame(columns=['region', 'comm', 'partner', 'musd', 'merged'])
    if V['one_sided_seed'] != 'none':
        drows = io13[io13['row'].str.startswith('dom_')]
        drows = drows.assign(comm=drows['row'].str[4:]).set_index(['region', 'comm'])[list(sectors) + list(FD)].sum(axis=1)
        B, swaps, swap_switch = M.import_seed_swaps(B, drows, M.SEED_RATIO)
        for s_ in swaps[swaps['partner'] != ''].itertuples():
            for r_, o_ in ((s_.region, s_.partner), (s_.partner, s_.region)):
                S.adjust(r_, f'A13 swap: {s_.comm} imported from {o_} and the same sold to it (domestic purchases switched to imports)', 0.0, s_.musd, M.RULE_SWAP,
                         'fix list A13, David 2026-10-24 (GTAP 10 has no one-sided pair); size 1e-4 of domestic purchases and the swap closure our choice', 'SEED-A13')
        S.log(f'A13 swap: {int((swaps["partner"] != "").sum())} domestic-only pairs given imports, {swaps["musd"].sum():.3f} USD million '
              f'({", ".join(f"{c} {n}" for c, n in swaps.groupby("comm").size().items())}); no partner: {int((swaps["partner"] == "").sum())}')

    # ------------------------------------------------------------- 2-5. regions
    xr = B.groupby(['src', 'comm'])['VXSB'].sum()
    mr = B.groupby(['dst', 'comm'])['VMSB'].sum()
    vr = vst.groupby(['region', 'marg'])['VST'].sum()
    tm = []
    for lab, a0, a1 in zip(('X', 'M', 'VST'), held_xmv, (xr, mr, vr)):
        d = a1.sub(a0, fill_value=0.0)
        d.index.names = ['region', 'sector']
        tm.append(d.rename('d' + lab))
    trade_moves = pd.concat(tm, axis=1).fillna(0.0)
    sw_ = swaps[swaps['partner'] != '']
    sw_x = pd.concat([sw_[['region', 'comm', 'musd']], sw_[['partner', 'comm', 'musd']].rename(columns={'partner': 'region'})])
    # beta v5 build: with no A13 swaps the empty series needs the two-level index too
    sw_x = (sw_x.groupby(['region', 'comm'])['musd'].sum() if len(sw_x)
            else pd.Series(dtype=float, index=pd.MultiIndex.from_tuples([], names=['region', 'comm'])))
    sw_x.index.names = ['region', 'sector']
    trade_moves = trade_moves.join(sw_x.rename('swap_musd'), how='left').fillna(0.0)
    trade_moves = trade_moves[(trade_moves[['dX', 'dM', 'dVST']] != 0).any(axis=1)].reset_index()
    parts, moves, issues = [], [tmoves], []
    for reg in regs:
        g = io13[io13['region'] == reg].set_index('row')
        f = fac13[fac13['region'] == reg]
        x_r = xr.loc[reg].to_dict() if reg in xr.index.get_level_values(0) else {}
        m_r = mr.loc[reg].to_dict() if reg in mr.index.get_level_values(0) else {}
        v_r = vr.loc[reg].to_dict() if reg in vr.index.get_level_values(0) else {}
        sh = shift.loc[reg].to_dict() if reg in shift.index.get_level_values(0) else {}
        cr = M.cell_rate_matrix(cells13[cells13['region'] == reg], sectors) if cell_on else None
        sw = {c_: a_ for (r_, c_), a_ in swap_switch.items() if r_ == reg}
        p, mv, iss = M.assemble_region(reg, g, f, x_r, v_r, m_r, sectors, seed_ratio=M.SEED_RATIO if V['one_sided_seed'] != 'none' else 0.0, small_shift=sh,
                                       cell_rates=cr, natres=natres_cfg, switch=sw, cap_floor=V['capital_floor'] != 'off')
        parts.append(p)
        moves.append(pd.DataFrame(mv, columns=['kind', 'key', 'before', 'after']))
        issues += iss
    moves = pd.concat([m for m in moves if len(m)], ignore_index=True) if any(len(m) for m in moves) else pd.DataFrame(columns=['kind', 'key', 'before', 'after'])
    S.check('S14-Hassemble', 'No product tax on a column with zero basic purchases, no VMSB without a buyer, and factors_s13 EVFP equal to the io_s13 EVFP rows', 'hard',
            len(issues), 0, not issues, '17B §B.2 zero-divide check', '; '.join(issues[:10]))
    T = M.frames(parts)
    seeds = pd.DataFrame([s_ for p in parts for s_ in p['seeds']],
                         columns=['region', 'comm', 'imports', 'seed', 'ratio', 'n_buyers', 'seed_va', 'seed_ptax', 'output_before', 'output_after'])
    fdelta = pd.DataFrame([d_ for p in parts for d_ in p['fac_delta']], columns=['region', 'endw', 'acts', 'EVFP', 'EVFB', 'EVOS', 'rule'])
    seed_cols = {(reg_, c_) for reg_, p in zip(regs, parts) for c_ in p['seed_cols']}
    for s_ in seeds.itertuples():
        S.adjust(s_.region, f'A13 domestic purchases of {s_.comm} (imports {s_.imports:.6g}, {s_.n_buyers} buyers)', 0.0, s_.seed, M.RULE_SEED,
                 'fix list A13, David 2026-10-24 (GTAP 10 has no one-sided pair); size 1e-4 of imports and closure our choice', 'SEED-A13')
    for p in parts:
        for l_ in p['ledger']:
            if l_['rule'] == M.RULE_SMALL:
                S.adjust(l_['region'], l_['item'], l_['before'], l_['after'], l_['rule'],
                         'fix list B14 (QA#17), David 2026-10-24; our choice: GTAP filters small values, its threshold is not in the documents we hold', 'SMALL-TRADE')
            else:
                S.adjust(l_['region'], l_['item'], l_['before'], l_['after'], l_['rule'],
                         'fix list A13, David 2026-10-24; the seeded column takes this share of the supplying column (our choice)', 'SEED-A13')
    natres = pd.DataFrame([x_ for p in parts for x_ in p['natres']],
                          columns=['region', 'sector', 'eta_target', 'sigma_va', 'cost_musd', 'factor_va_musd', 'theta_va', 'theta_va_used', 'guard',
                                   'natres_before_musd', 'natres_musd', 'moved_musd', 'labour_capital_factor', 'share_before', 'share_after',
                                   'eta_before', 'eta_after', 'natres_rates_from'])
    for (r_, f_), g_ in fdelta[(fdelta['rule'] == M.RULE_SEED_FACTOR) & (fdelta['endw'] != 'capital')].groupby(['region', 'endw']):
        S.adjust(r_, f'A13 {f_} in seeded columns paid as capital ({len(g_)} cells, EVFP USD million)', float(-g_['EVFP'].sum()), 0.0, M.RULE_SEED_FACTOR,
                 'fix round S16 (Fable QA C-07); GTAP 12 ch.14A land and ch.12A natural resources only in the activities that use them', 'SEED-A13')
    B16_CITE = ('fix list B16, David 2026-10-24 ("GTAP rule in all resource sectors"; "stick to GTAP"); GTAP 7 ch.12.A pp.2-3; '
                'GTAP 12 ch.17B §B.1 (reallocation at global assembly, after the FIT)')
    for x_ in natres[natres['moved_musd'] != 0].itertuples():
        S.adjust(x_.region, f'B16 natural resources of {x_.sector} at the ch.12.A target on the S14 data (theta_VA {x_.theta_va:.4f}; '
                 f'labour and capital x {x_.labour_capital_factor:.6f})', x_.natres_before_musd, x_.natres_musd, M.RULE_NATRES, B16_CITE, 'NATRES-FINAL')
    for x_ in natres[natres['guard']].itertuples():
        S.flag('NATRES-GUARD', f'{x_.region} {x_.sector}', f'value added {x_.factor_va_musd:.3f} m is {x_.theta_va:.4f} of the cost {x_.cost_musd:.3f} m on the S14 data, '
               f'below {natres_cfg["floor"]}; natural-resource share of VA held at {x_.share_after:.4f}', rule='S12 natres_guard (our choice)')
    S.log(f'B16: {len(natres)} resource cells; {(natres["moved_musd"] != 0).sum()} moved, net {natres["moved_musd"].sum():.3f} and gross '
          f'{natres["moved_musd"].abs().sum():.3f} USD million to natural resources; {int(natres["guard"].sum())} guarded')
    S.log(f'A13: {len(seeds)} one-sided pairs seeded, {seeds["seed"].sum():.3f} USD million of domestic purchases '
          f'({", ".join(f"{c} {n}" for c, n in seeds.groupby("comm").size().items())})')
    for name, df_ in s12_opt.items():
        try:
            M.join_s12_tax_split(name, df_, T)
            S.check('S14-Hs12join', f'S12 {name} joined (fix list A3/A4)', 'hard', len(df_), '', True, 'fix list A3/A4')
        except NotImplementedError as e:
            S.check('S14-Hs12join', f'S12 {name} is present and must be joined (fix list A3/A4)', 'hard', len(df_), 'joined', False, 'fix list A3/A4', str(e))
    T['bilateral'] = B
    T['vtwr'] = Vt
    T['vst'] = vst[vst['VST'] != 0].sort_values(['marg', 'region']).reset_index(drop=True)
    mreg = macro.set_index('region').reindex(regs)
    # POP in millions of persons, as in the GTAP data base (S02 holds persons)
    T['regional'] = pd.DataFrame(dict(region=regs, VDEP=mreg['VDEP_musd'].to_numpy(), VKB=mreg['VKB_musd'].to_numpy(), POP=mreg['POP'].to_numpy() / 1e6))
    acc0 = M.regional_accounts(T, regs)
    T['regional'].insert(1, 'SAVE', acc0['SAVE'].to_numpy())

    # ------------------------------------------------------------- outputs
    def gzcsv(name, df):
        """gzip with mtime 0 and 12 significant digits, so two runs give the same bytes."""
        with gzip.GzipFile(f'{S.out}/{name}', 'wb', mtime=0) as fh:
            fh.write(df.to_csv(index=False, float_format=FLOAT).encode())
        S.log(f'output {name}: {len(df)} rows')
    files = {'firms': 'firms_s14.csv.gz', 'final': 'final_demand_s14.csv.gz', 'endw': 'endowments_s14.csv.gz', 'make': 'make_s14.csv.gz',
             'bilateral': 'bilateral_s14.csv.gz', 'vtwr': 'vtwr_s14.csv.gz', 'vst': 'vst_s14.csv', 'regional': 'regional_s14.csv'}
    for k, fn in files.items():
        df = T[k].reset_index(drop=True)
        if fn.endswith('.gz'):
            gzcsv(fn, df)
        else:
            df.to_csv(f'{S.out}/{fn}', index=False, float_format=FLOAT)
            S.log(f'output {fn}: {len(df)} rows')
    sets = pd.DataFrame([('REG', r, i + 1) for i, r in enumerate(regs)] + [('COMM', c, i + 1) for i, c in enumerate(sectors)] +
                        [('ACTS', c, i + 1) for i, c in enumerate(sectors)] + [('ENDW', e, i + 1) for i, e in enumerate(FACTORS)] +
                        [('MARG', m, i + 1) for i, m in enumerate(MARGINS)], columns=['set', 'element', 'position'])
    S.write('sets_s14.csv', sets)

    # ------------------------------------------------------------- checks on the files as written
    R = {k: pd.read_csv(f'{S.out}/{fn}') for k, fn in files.items()}
    acc = M.regional_accounts(R, regs)
    bopr = bop.groupby('region')[['net_primary_income_musd', 'net_secondary_income_musd']].sum(min_count=1)
    gate = M.si_gate(acc, bopr)
    sw = pd.read_csv(f'{S.out}/sets_s14.csv')
    el = {k: g.sort_values('position')['element'].tolist() for k, g in sw.groupby('set')}
    n, det = K.sets(el.get('REG', []), el.get('COMM', []), el.get('ENDW', []), el.get('MARG', []), el.get('ACTS', []))
    S.check('S14-Hsets', 'Sets: 167 regions, COMM = ACTS, MARG a subset of COMM with more than one element, ENDW includes capital', 'hard',
            n, 0, n == 0 and el.get('REG', []) == regs and len(regs) == 167, 'model_requirements §1a', det)
    n, det = K.headers(R)
    S.check('S14-Hheaders', 'All 31 GTAPv7 data headers are written, each in exactly one table', 'hard', n, 0, n == 0, 'model_requirements §1b', det)
    n, det = K.rebalance_bound(moves, M.REBAL_MAX)
    S.check('S14-Hrebalance', f'Every re-balancing move is rounding: at most {M.REBAL_MAX:g} USD million per cell (no plug)', 'hard',
            n, 0, n == 0, '17B §B.2 re-balancing; PLAN §3(i) no plugs',
            f'{len(moves)} moves; ' + '; '.join(f'{k} {len(g)} moves, total {(g["after"] - g["before"]).abs().sum():.3g}' for k, g in moves.groupby('kind')) + '. ' + det)
    for cid, desc, fn, concept in [
        ('S14-Hcif', 'VCIF = VFOB + sum of VTWR on every commodity and route', lambda: K.route_cif(R['bilateral'], R['vtwr']), 'model identity 6'),
        ('S14-Hmargins', 'World VST = world VTWR for each margin', lambda: K.global_margins(R['vtwr'], R['vst']), 'model identity 7; PLAN §3(i) global pass'),
        ('S14-Hmarket', 'Supply = demand at basic prices: MAKB = VDFB + VDPB + VDGB + VDIB + VXSB + VST for every commodity and region', lambda: K.market_clearing(R['firms'], R['final'], R['make'], R['bilateral'], R['vst']), '17B p.3; model identity 3'),
        ('S14-Himports', 'Imports: sum of VMSB over sources = VMFB + VMPB + VMGB + VMIB', lambda: K.import_clearing(R['firms'], R['final'], R['bilateral']), 'model identity 4'),
        ('S14-Hprofit', 'Zero profit: MAKS = VDFP + VMFP + EVFP for every activity', lambda: K.zero_profit(R['firms'], R['endw'], R['make']), 'model identity 1'),
        ('S14-Hmake', 'MAKS and MAKB are diagonal', lambda: K.diagonal_make(R['make']), 'model_requirements §1a ACTS = COMM'),
        ('S14-Hpower', 'One product-tax power per cell on domestic and imported purchases; on the non-energy rows of a column, the S13 cell rates (the commodity rates of QA round 2 P1 and a listed S13 PSE input item\'s own rate, fix round wG) plus one remainder shift per column' if cell_on else 'One product-tax power per column on domestic and imported purchases',
         lambda: K.cell_tax_power(R['firms'], R['final'], pse_items, cells13) if cell_on else K.one_tax_power(R['firms'], R['final']), 'S13 tax_rates and non_energy_rates; purchaser_split; model identity 5'),
        ('S14-Hcellrates', 'Fix list A1 and QA round 2 P1: every cell, energy rows (pet, coa, gas, ely) and the commodity rates of the non-energy rows, keeps its S13 net product-tax rate (tax_cells_s13; within 1e-6 or 1e-3 USD million on the column; in a column the A13 seed moved, up to one shift per column)',
         lambda: K.cell_rates_match_s13(R['firms'], R['final'], cells13, seed_cols) if cell_on else (0, 'off (purchaser_split one power per column)'), 'fix list A1; S13 tax_rates; GTAP 12 ch.15'),
        ('S14-Hfactors', 'EVFP = 0 exactly when EVFB = 0, and EVFB = 0 exactly when EVOS = 0', lambda: K.factor_identities(R['endw']), 'model identity 8'),
        ('S14-Hfac13', 'EVFP, EVFB and EVOS equal factors_s13 cell by cell, plus the ledgered B14, A13 and B16 moves (the A13 moves sum to zero by region and factor, the B16 moves by region and activity)', lambda: K.factors_match_s13(R['endw'], fac13, fdelta), 'ch.17B §B.2 (factor data incorporated)'),
        ('S14-Hseed', f'A13: no commodity is bought from one source only: each seeded pair buys {M.SEED_RATIO:g} of its imports from domestic producers (more where the capital_floor seed minimum of {M.SEED_MIN:g} binds), and each domestic-only pair imports {M.SEED_RATIO:g} of its domestic purchases through a swap with a partner exporter', lambda: K.seed_check(R['firms'], R['final'], seeds, M.SEED_RATIO, swaps, R['bilateral']) if V['one_sided_seed'] != 'none' else (0, 'off'), 'fix list A13; model log(0) on one-sided pairs'),
        ('S14-Hcapfloor', f'Beta v4 capital_floor: every activity with value added pays capital of at least min({M.CAPITAL_MIN:g} USD million, half its VA) (labour moved to capital; seeds at least {M.SEED_MIN:g})',
         lambda: K.capital_floor_held(R['endw'], M.CAPITAL_MIN) if V['capital_floor'] != 'off' else (0, 'off'), 'S16 alone_bfa; labelled departure (our choice)'),
        ('S14-Hsmall', f'B14: no route with 0 < VXSB < {M.SMALL_TRADE:g} and no VTWR cell below it', lambda: K.small_trade(R['bilateral'], R['vtwr'], M.SMALL_TRADE) if small_on else (0, 'off'), 'fix list B14 (our choice)'),
        ('S14-Hxtax', 'Fix list A2: the bilateral table carries the export tax: by exporter and commodity, VFOB - VXSB is the S10 export-tax rate times the S11 VFOB on coa, oil, gas and pet, the S10 wedge on other goods, and 0 on services and travel (1e-3 USD million: rounding and the B14 routes)',
         lambda: K13.export_tax_held(R['bilateral'].groupby(['src', 'comm'], as_index=False)[['VXSB', 'VFOB']].sum().rename(columns={'src': 'region', 'comm': 'sector', 'VXSB': 'X', 'VFOB': 'XFOB'}),
                                     ex, xt10, gx[~gx['sector'].isin(ENERGY_TRADE)]), 'GTAP 12 ch.17A eq. 17.30; fix list A2'),
        ('S14-Hsign', 'No sign violation: every flow, factor payment, border value, margin, VKB, VDEP and POP is non-negative', lambda: K.signs(R), '17B p.3 sign violations; PLAN §3(k) signs'),
        ('S14-Hzerodiv', 'No zero-divide: MAKB/MAKS, VFOB/VXSB, VMSB/VCIF have no zero denominator under a non-zero numerator; every activity with output has EVFP > 0', lambda: K.zero_divides(R), '17B p.3 zero-divide problems; model identity 8'),
        ('S14-Hgdp', 'Income = expenditure: GDP from expenditure and from income both equal S02 GDP in every region', lambda: K.gdp(acc, mreg['GDP_musd']), '17B p.3; PLAN §3(i) constraint 6'),
        ('S14-Hfd', "C, G and I at purchasers' prices equal the S13 targets", lambda: K.final_demand(acc, macro13), 'PLAN §3(i) constraint 7'),
        ('S14-Hsave', 'SAVE = Y - C - G, S - (I - VDEP) = X - M in every region, and world SAVE = world net investment', lambda: K.saving_identity(acc, R['regional']), 'GTAP 12 ch.7 eq. 7.1; PLAN §3(k) identities'),
    ]:
        n, det = fn()
        S.check(cid, desc, 'hard', n, 0, n == 0, concept, det)
    if natres_on:
        n, det = K.natres_eta(R['endw'], R['make'], natres_cfg['targets'], natres_cfg['floor'])
        S.check('S14-Heta', 'Fix list B16 on the final data: in every resource cell (for, fsh, coa, oil, gas, ore, min, msp) with value added and no guard, '
                'the written tables give the ch.12.A target supply elasticity S12 booked for the cell, sigma_VA (1/theta_R - 1/theta_VA), theta at MAKS, within 1e-6; a guarded cell has the share at the theta_VA floor',
                'hard', n, 0, n == 0, 'natres_final; GTAP 7 ch.12.A pp.2-3; GTAP 12 ch.17B §B.1', det)
        n, det = K.natres_pro_rata(R['endw'], fdelta)
        S.check('S14-Hnatpro', 'B16: labour and capital give up (or take back) the natural-resource move by one factor on EVFP, EVFB and EVOS (rates kept), land does not move, '
                'natural resources keep their rates, and each activity keeps its value added', 'hard', n, 0, n == 0, 'natres_final; ch.12.A p.2 (out of all value added)', det)
        n, det = K.natres_booked(nat12, nat_config, natres, nat_blend)
        S.check('S14-Hnatcfg', 'B16: the target and sigma_VA S14 applies in each cell are the ones S12 booked (natres_s12.csv), and S12 booked '
                'the config targets (msp under the w13 blend: the effective eta recomputed from its weight and theta_VA)', 'hard',
                n, 0, n == 0, 'natres_final; S12 natres_rule, msp_natres_target', det)
        cells = K.natres_cells(R['endw'], R['make'], natres_cfg['targets'], natres_cfg['floor'])
        gd = cells[cells['guard'] & (cells['factor_va_musd'] > 0)].sort_values('factor_va_musd', ascending=False)
        S.check('S14-Rnatguard', f'B16 resource cells held by the S12 guard on the S14 data (theta_VA below {natres_cfg["floor"]}; supply elasticity above the target)', 'report',
                len(gd), 0, True, 'S12 natres_guard (our choice)',
                '; '.join(f'{x.region} {x.sector} theta_VA {x.theta_va:.4f} share {x.natres_musd / x.factor_va_musd:.3f} eta {x.eta:.3f} VA {bn(x.factor_va_musd):.3f} bn' for x in gd.itertuples()))
        bys = natres.groupby('sector')[['natres_before_musd', 'natres_musd', 'moved_musd']].sum()
        top = natres.reindex(natres['moved_musd'].abs().sort_values(ascending=False).index).head(10)
        S.check('S14-Rnatres', 'B16 income moved to natural resources on the S14 data, by sector (USD bn: before -> after), and the ten largest moves', 'report',
                f'net {bn(natres["moved_musd"].sum()):.2f}, gross {bn(natres["moved_musd"].abs().sum()):.2f} bn over {int((natres["moved_musd"] != 0).sum())} cells', '', True, 'natres_final',
                '; '.join(f'{k} {bn(x.natres_before_musd):.1f} -> {bn(x.natres_musd):.1f}' for k, x in bys.iterrows()) + '. Largest: '
                + '; '.join(f'{x.region} {x.sector} {bn(x.moved_musd):+.3f} (eta {x.eta_before:.3f} -> {x.eta_after:.3f})' for x in top.itertuples()))
    share_hard = V['saving_share_gate'] == 'hard_per_region'
    save_hard = V['negative_save'] == 'hard_save_positive'
    n, det = K.si_gate_hard(gate, share_hard, save_hard)
    S.check('S14-Hsi', 'Pre-solve S-I gate: VKB > 0, I > 0, Y > 0, VDEP below capital income' + (', SAVE > 0' if save_hard else '') + (', saving share in [-1, 1]' if share_hard else ''),
            'hard', n, 0, n == 0, 'PLAN §3(h)3; E12; E28', det)
    vk = K.vdep_capital_sources(gate, fac13)
    S.check('S14-Rvdepk', 'Regions with VDEP at or above capital income (sum EVOS capital): capital income in factors_s13 (S12 split through the FIT) '
            'and after the S14 B16 and A13 moves, USD million (names the stage that sets it; S14-Hsi is the hard check)', 'report', len(vk), 0, True,
            'model_requirements identity 12; GTAP 12 ch.7.3 (VDEP 4% of VKB)',
            '; '.join(f'{x.region} VDEP {x.VDEP:.1f}, capital income S13 {x.capital_income_s13:.1f}, S14 {x.capital_income:.1f} ({x.moved_in_s14:+.1f} in S14)'
                      for x in vk.itertuples()))
    vf = K.vdep_floor_breaches(gate, fac13)
    S.check('S14-Rvdepfloor', 'Beta v4 G17: regions whose capital income is below 1.25 x VDEP (the S12 capital_vdep_floor, held at S12 only) '
            'in factors_s13 or after S14 (ratio capital income / VDEP)', 'report', len(vf), 0, True, 'S12 capital_vdep_floor (our rule)',
            '; '.join(f'{x.region} S13 {x.ratio_s13:.3f}, final {x.ratio_final:.3f}' for x in vf.itertuples()) or 'none')
    out_share = gate[~gate['saving_share_in_bounds']]
    S.check('S14-Rshare', 'Regions whose saving share SAVE/Y is outside [-1, 1] (the Julia model bound on σsave; checked on every aggregation map at S15-S16 under CARRY-SAVE)',
            'report' if not share_hard else 'hard', len(out_share), 0, (not share_hard) or len(out_share) == 0, 'saving_share_gate',
            '; '.join(f'{r} {x.saving_share:.3f}' for r, x in out_share.iterrows()))
    for r, x in out_share.iterrows():
        S.flag('CARRY-SAVE', r, f'saving share {x.saving_share:.3f} outside [-1, 1]: every aggregation map must keep this region inside a pooled region or pass the bound', rule=V['saving_share_gate'])
    negs = gate[~gate['save_positive']]
    S.check('S14-Rnegsave', 'Regions with SAVE <= 0 (GTAP eq. 7.1 residual; the label restates the identity), with the S02 BoP memo (eq. 7.2) and the trade balance against S02', 'report',
            len(negs), '', True, 'negative_save; GTAP 12 ch.7 §7.4',
            f'{acc.loc[negs.index, "GDP_expenditure"].sum() / acc["GDP_expenditure"].sum():.1%} of world GDP; with BoP flows (eq. 7.2) {int((negs["save_bop_eq72"] > 0).sum())} turn positive. '
            + '; '.join(f'{r} {bn(x.SAVE):.2f} bn' for r, x in negs.iterrows()))
    for r, x in negs.iterrows():
        S.flag('NEG-SAVE', r, f'SAVE {bn(x.SAVE):.3f} bn: {x.save_cause}. {x.save_cause_detail}', needs_david='no' if choices['negative_save']['decided_by'].startswith('David') else 'yes', rule=V['negative_save'], citation='GTAP 12 ch.7 §7.4 eq. 7.1-7.2; Aguiar et al. (2025) p.5')
    cv = gate[~gate['vdep_below_investment']]
    S.check('S14-Rvdep', 'Regions with VDEP >= I (report-only, as in GTAP; carried flag CARRY-VDEP; hard for the large economies at S14-Hmacro, Fable QA E-04)', 'report', len(cv), 0, True, 'E28 (David 2026-10-20 19:25)',
            '; '.join(f'{r} VDEP/I {x.VDEP / x.I:.2f}' for r, x in cv.iterrows()))
    for r, x in cv.iterrows():
        S.flag('CARRY-VDEP', r, f'VDEP {bn(x.VDEP):.3f} bn >= I {bn(x.I):.3f} bn: must calibrate and solve in the aggregation solve checks', rule=V['vdep_gate'])
    # Fable QA E-03/E-04: the saving and macro structure against an independent figure (WDI 2022), hard for the large economies
    wdi_r = MX.wdi_by_region(pd.read_csv(I(DATA + '/wdi/wdi_accounts.csv', 'WDI national accounts 2022 (macro structure check, Fable QA E-03)')), regions)
    mx_exc = MX.read_exceptions(I(BUILD + '/config/macro_external_exceptions.csv', 'open macro findings excepted from S14-Hmacro (Fable QA E-04)'))
    mxt, mx_fail, mx_hit = MX.compare(acc, wdi_r, mx_exc)
    S.check('S14-Hmacro', f'Macro structure against WDI 2022 (Fable QA E-03, E-04; GTAP 12 ch.3, ch.7): in every large economy (at least {MX.LARGE_SHARE:.0%} of world GDP) '
            f'the trade balance (X - M) / GDP and the gross saving (SAVE + VDEP) / GDP are within {MX.BAND:.0%} and {MX.SAVE_BAND:.0%} of GDP of WDI '
            '(saving: gross national saving, NY.GNS.ICTR.ZS), and VDEP is below I; absorption (C + G + I) / GDP is reported (with GDP held it mirrors the trade balance). '
            'Open findings listed in config/macro_external_exceptions.csv are reported, not failed', 'hard', len(mx_fail), 0, not mx_fail,
            'basis national accounts vs national accounts; GTAP 12 ch.7 eq. 7.1-7.2', MX.summary(mxt, mx_fail, mx_hit))
    S.write('macro_wdi_s14.csv', mxt.reset_index().round(9))
    qi = acc['investment_share']
    S.check('S14-Rqinv', "Each region's share of world SAVE (the model's σ_qinv, bound [-1, 1] on each aggregation map)", 'report',
            f'min {qi.min():.4f} ({qi.idxmin()}), max {qi.max():.4f} ({qi.idxmax()})', '[-1, 1]', True, 'src/solve_model.jl σ_qinv')
    rho = acc['capital_income'] / acc['VKB']
    S.check('S14-Rcapital', 'Gross return on capital ΣEVOS(capital)/VKB against the 4% depreciation rate (model identity 12)', 'report',
            f'min {rho.min():.4f} ({rho.idxmin()}), median {rho.median():.4f}, max {rho.max():.4f} ({rho.idxmax()})', '> 0.04', True, 'model identity 12')
    wquirk = (acc['I_basic'] - acc['VDEP']).sum() - R['regional']['SAVE'].sum()
    S.check('S14-Rinvbasic', 'Model quirk: the Julia walras_sup uses investment at basic prices; world SAVE less world (VDIB + VMIB - VDEP), USD bn', 'report',
            f'{bn(-wquirk):.3f}', '', True, 'model_requirements §1d item 11 (quirk, model side)')
    tx = acc[[c for c in acc.columns if c.startswith('tax_')]].sum()
    S.check('S14-Rtaxes', 'World tax revenue by type, USD bn (17B §B.2 tax rates summary)', 'report',
            '; '.join(f'{k[4:]} {bn(v):.1f}' for k, v in tx.items()), '', True, '17B §B.2 p.4')
    # round-3 QA item 3 (S13 product_tax_totals): product taxes by region equal to what S13 held
    ptr_path = UP['S13'] + '/output/product_tax_regions_s13.csv'
    if os.path.exists(ptr_path):
        ptr = pd.read_csv(I(ptr_path, 'S13 product tax by region, held and against the QA prior (round-3 QA item 3)'))
        pse13 = io13[io13['row'] == 'PSE_input'].set_index('region')[sectors + list(FD)].sum(axis=1).to_dict()
        n_pt, d_pt, PTX = K.product_tax_s13(acc, pse13, ptr)
        qa = (PTX['s14_musd'] - PTX['qa_prior_musd'])
        S.check('S14-Hptaxs13', 'Net product tax by region in the final tables (firms, households, government, investment; PSE input support excluded) '
                f'equal to the TLS S13 held (S13 product_tax_totals: io_s12 general money plus the held energy-tax rates on the fitted energy purchases, '
                f'less the fuel subsidies; within max({K.PTAX_S13_REL:g} relative, {K.PTAX_S13_MUSD:g} USD m); round-3 QA item 3)', 'hard', n_pt, 0, n_pt == 0,
                'S13 product_tax_totals', (d_pt + '. ' if d_pt else '') + f'world {bn(PTX["s14_musd"].sum()):.1f} bn (S13 {bn(PTX["s13_musd"].sum()):.1f}); '
                f'against the QA prior (io_s12 TLS with the A1 move, less the fuel subsidies) {bn(qa.sum()):+.1f} bn, '
                f'{int((qa.abs() > 0.05 * PTX["qa_prior_musd"].abs()).sum())} regions more than 5% off (S13-Rptaxprior: the energy part)')
    else:
        S.check('S14-Hptaxs13', 'S13 product_tax_regions_s13.csv is present (round-3 QA item 3)', 'hard', 'missing', 'present', False,
                'S13 product_tax_totals', ptr_path)
    small = R['bilateral'][(R['bilateral']['VXSB'] > 0) & (R['bilateral']['VXSB'] <= 1e-4)]
    S.check('S14-Rsmall', 'Routes with 0 < VXSB <= 1e-4 USD million (the closure tests zero these, model_requirements §1d item 13)', 'report',
            len(small), '', True, 'model_requirements §1d item 13', f'{small["VXSB"].sum():.6f} USD million')

    # tax summary and gate files
    S.write('si_gate_s14.csv', gate.reset_index())
    S.write('seeded_pairs_s14.csv', seeds)
    S.write('swapped_pairs_s14.csv', swaps.round(9))
    S.write('seed_columns_s14.csv', pd.DataFrame(sorted(seed_cols), columns=['region', 'column']))
    if natres_on:
        S.write('natres_s14.csv', natres.round(9))
    gzcsv('small_trade_s14.csv.gz', small)
    gzcsv('trade_moves_s14.csv.gz', trade_moves)
    rev = K.one_sided_pairs(R['firms'], R['final'])
    rev = rev[rev['missing'] == 'imported']
    S.check('S14-Rdomonly', 'Commodity-region pairs bought only from domestic producers after the A13 swap (S14-Hseed is the hard check)', 'report',
            len(rev), 0, True, 'fix list B14', '; '.join(f'{r.region} {r.comm} {r.domestic:.6g}' for r in rev.head(10).itertuples()))
    S.write('accounts_s14.csv', acc.reset_index())
    gzcsv('rebalance_s14.csv.gz', moves.assign(change=moves['after'] - moves['before']))

    tracked = subprocess.run(['git', '-C', BUILD, 'ls-files', '--full-name', ROOT.rsplit('/', 1)[0]], capture_output=True, text=True).stdout.split()
    priv = private_paths(tracked)
    S.check('S14-Hprivate', 'No private file (credentials, GTAP database values) is tracked in git (lib/private_files.py)', 'hard',
            len(priv), 0, not priv, 'repo_rules committed_data_rule', ' '.join(priv[:10]))
    sec = secret_scan([BUILD + '/s14_final_assembly.py', BUILD + '/s14_assembly', BUILD + '/screens/s14_suite.py', C.CONFIG_DIR, S.out])
    S.check('S14-Hsecret', 'Key and password scan of the S14 code, config and outputs (count only)', 'hard', sec, 0, sec == 0, 'never commit credentials')

    # ------------------------------------------------------------- screens
    prev_out = os.environ.get('S14_PREV_OUTPUT')
    ctx = dict(R=R, acc=acc, gate=gate, regions=regs, s02_nx=mreg['implied_NX_musd'], prev=pd.read_csv(prev_out + '/accounts_s14.csv') if prev_out else None)
    try:
        scr = SCR.run(ctx, log=S.log)
        S.check('S14-Hscreens', 'Population screens (SCREENS.md seven questions): no identity hit', 'hard',
                scr['material_unexplained'], 0, scr['material_unexplained'] == 0, 'screens', scr['summary'])
    except Exception as e:   # a screen that raises fails the stage
        S.check('S14-Hscreens', 'Population screens ran', 'hard', repr(e)[:200], 'no exception', False, 'screens')
        raise
    with open(S.out + '/NOT_FOR_PUBLICATION.md', 'w') as f:
        f.write('# Not for publication\n\nThe S14 header tables carry the S10 tariff wedge (TRAINS-derived) in VMSB and, through io_s12 and '
                'io_s13, in the purchaser values. Keep them out of any public release, as for S10 to S13.\n')
    S.finish()


if __name__ == '__main__':
    main()
