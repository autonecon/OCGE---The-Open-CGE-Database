"""Mutation tests for the S14 method, the S14 hard checks, the S14 screens and the config stop.

A small synthetic two-region, two-commodity world (one goods commodity and one margin) goes through the real
method: io_s13-style region tables, bilateral trade, re-balancing, assembly and regional accounts. Every check
is called on the assembled tables (it must pass) and on a mutated copy (it must fail).

Run from dataset/build:  python3 -m unittest tests.test_s14_checks -v
"""
import copy
import csv
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BUILD)

from s14_assembly import checks as K  # noqa: E402
from s14_assembly import config as C  # noqa: E402
from s14_assembly import method as M  # noqa: E402
from s13_fit.method import FD, FACTORS  # noqa: E402
import screens.s14_suite as SCR  # noqa: E402

SECTORS = ['crp', 'sea']
REGS = ['AAA', 'BBB']


# ------------------------------------------------------------------ config
class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, 'c.csv')
        with open(C.CHOICES_PATH, newline='') as fh:
            self.rows = list(csv.DictReader(fh))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write(self, rows):
        with open(self.path, 'w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=C.CHOICE_COLUMNS)
            w.writeheader()
            w.writerows(rows)

    def test_repo_file_loads(self):
        self.assertEqual(len(C.load_choices()), len(C.CHOICES))

    def test_mutations_stop(self):
        bad = [self.rows[1:],
               self.rows + [dict(self.rows[0])],
               self.rows + [dict(self.rows[0], choice='made_up')],
               [dict(self.rows[0], value='other')] + self.rows[1:],
               [dict(self.rows[0], decided_by='')] + self.rows[1:],
               [dict(self.rows[0], gtap_status='maybe')] + self.rows[1:]]
        for rows in bad:
            self.write(rows)
            with self.assertRaises(C.ConfigError):
                C.load_choices(self.path)


# ------------------------------------------------------------------ synthetic world
def world():
    """AAA exports crp to BBB (FOB 10, sea margin 2 supplied by AAA, CIF 12, tariff 10%: VMSB 13.2), and
    BBB exports crp to AAA (FOB 5 with a 2% export tax on VXSB, margin 1 supplied by BBB, CIF 6, no tariff).
    Each region has a balanced io_s13 table built around that trade."""
    gx = pd.DataFrame(dict(sector=['crp', 'crp'], exporter=['AAA', 'BBB'], importer=['BBB', 'AAA'],
                           vxsb_musd=[10.0, 5.0 / 1.02], vfob_musd=[10.0, 5.0]))
    gm = pd.DataFrame(dict(importer=['BBB', 'AAA'], exporter=['AAA', 'BBB'], sector=['crp', 'crp'],
                           vcif_musd=[12.0, 6.0], vmsb_musd=[13.2, 6.0]))
    vt = pd.DataFrame(dict(margin=['sea', 'sea'], sector=['crp', 'crp'], exporter=['AAA', 'BBB'], importer=['BBB', 'AAA'], vtwr_musd=[2.0, 1.0]))
    empty_e = pd.DataFrame(columns=['sector', 'exporter', 'importer', 'vxsb_musd', 'vfob_musd'])
    empty_m = pd.DataFrame(columns=['importer', 'exporter', 'sector', 'vcif_musd', 'vmsb_musd'])
    empty_v = pd.DataFrame(columns=['margin', 'sector', 'exporter', 'importer', 'vtwr_musd'])
    svc = pd.DataFrame(columns=['sector', 'exporter', 'importer', 'vxsb_musd'])
    trv = pd.DataFrame(columns=['sector', 'exporter', 'importer', 'v'])
    B = M.bilateral(gx, gm, empty_e, empty_m, svc, trv)
    V = M.margins(vt, empty_v)
    vst = pd.DataFrame(dict(marg=['sea', 'sea'], region=['AAA', 'BBB'], VST=[2.0, 1.0]))
    X = {'AAA': {'crp': 10.0}, 'BBB': {'crp': 5.0 / 1.02}}
    VS = {'AAA': {'sea': 2.0}, 'BBB': {'sea': 1.0}}
    MM = {'AAA': {'crp': 6.0}, 'BBB': {'crp': 13.2}}
    io, fac = {}, {}
    cols = SECTORS + list(FD)
    for r in REGS:
        rows = {f'dom_{c}': np.zeros(len(cols)) for c in SECTORS}
        rows.update({f'imp_{c}': np.zeros(len(cols)) for c in SECTORS})
        # crp: output 40 = domestic sales 40 - X; sea: output 20 = domestic 20 - VST
        x, vs, m = X[r]['crp'], VS[r]['sea'], MM[r]['crp']
        rows['dom_crp'][:] = [4.0, 1.0, 40.0 - x - 5.0 - 3.0 - 2.0, 3.0, 2.0][:len(cols)]
        rows['dom_sea'][:] = [2.0, 1.0, 20.0 - vs - 3.0 - 2.0 - 1.0, 2.0, 1.0][:len(cols)]
        rows['imp_crp'][:] = [m * 0.25, 0.0, m * 0.75, 0.0, 0.0][:len(cols)]
        g = pd.DataFrame(rows, index=cols).T
        basic = g.sum(axis=0)
        tls = basic * np.array([0.05, 0.0, 0.10, 0.0, 0.02])
        g.loc['TLS'] = tls
        g.loc['PSE_input'] = 0.0
        evfp = {}
        for j, a in enumerate(SECTORS):
            out = 40.0 if a == 'crp' else 20.0
            purch = basic[a] + tls[a]
            ptax = 0.01 * out
            va = out - purch - ptax
            evfp[a] = dict(capital=0.4 * va, ag_othlowsk=0.6 * va)
        for f in FACTORS:
            g.loc[f'EVFP_{f}'] = [evfp[a].get(f, 0.0) for a in SECTORS] + [0.0] * len(FD)
        g.loc['PTAX'] = [0.4, 0.2] + [0.0] * len(FD)
        g.loc['OUT'] = [40.0, 20.0] + [0.0] * len(FD)
        io[r] = g
        fac[r] = pd.DataFrame([dict(region=r, sector=a, factor=f, evfp=v, evfb=v * 0.95, evos=v * 0.9)
                               for a in SECTORS for f, v in evfp[a].items()])
    return dict(B=B, V=V, vst=vst, X=X, VS=VS, MM=MM, io=io, fac=fac)


def assemble(w):
    B, vst, moves = M.rebalance_trade(w['B'], w['V'], w['vst'])
    xr = B.groupby(['src', 'comm'])['VXSB'].sum()
    mr = B.groupby(['dst', 'comm'])['VMSB'].sum()
    vr = vst.groupby(['region', 'marg'])['VST'].sum()
    parts, mv_all, issues = [], [moves], []
    for r in REGS:
        p, mv, iss = M.assemble_region(r, w['io'][r], w['fac'][r], xr.loc[r].to_dict(), vr.loc[r].to_dict(), mr.loc[r].to_dict(), SECTORS)
        parts.append(p)
        mv_all.append(pd.DataFrame(mv, columns=['kind', 'key', 'before', 'after']))
        issues += iss
    T = M.frames(parts)
    T['bilateral'], T['vtwr'], T['vst'] = B, w['V'], vst
    T['regional'] = pd.DataFrame(dict(region=REGS, VDEP=[1.0, 1.0], VKB=[25.0, 25.0], POP=[1.0, 2.0]))
    acc = M.regional_accounts(T, REGS)
    T['regional'].insert(1, 'SAVE', acc['SAVE'].to_numpy())
    return T, acc, pd.concat(mv_all, ignore_index=True), issues


class MethodTest(unittest.TestCase):
    def setUp(self):
        self.w = world()
        self.T, self.acc, self.moves, self.issues = assemble(self.w)

    def test_assembly_is_clean(self):
        T, acc = self.T, self.acc
        self.assertEqual(self.issues, [])
        for fn in (lambda: K.route_cif(T['bilateral'], T['vtwr']), lambda: K.global_margins(T['vtwr'], T['vst']),
                   lambda: K.market_clearing(T['firms'], T['final'], T['make'], T['bilateral'], T['vst']),
                   lambda: K.import_clearing(T['firms'], T['final'], T['bilateral']),
                   lambda: K.zero_profit(T['firms'], T['endw'], T['make']), lambda: K.diagonal_make(T['make']),
                   lambda: K.one_tax_power(T['firms'], T['final']), lambda: K.factor_identities(T['endw']),
                   lambda: K.signs(T), lambda: K.zero_divides(T), lambda: K.saving_identity(acc, T['regional']),
                   lambda: K.headers(T), lambda: K.rebalance_bound(self.moves, M.REBAL_MAX)):
            n, det = fn()
            self.assertEqual(n, 0, det)
        self.assertTrue(np.allclose(acc['GDP_income'], acc['GDP_expenditure']))

    def test_rebalance_makes_cif_exact(self):
        w = copy.deepcopy(self.w)
        w['B'].loc[0, 'VCIF'] += 5e-7                 # a rounding remnant
        w['vst'].loc[0, 'VST'] += 3e-7
        T, acc, moves, _ = assemble(w)
        self.assertEqual(K.route_cif(T['bilateral'], T['vtwr'])[0], 0)
        self.assertEqual(K.global_margins(T['vtwr'], T['vst'])[0], 0)
        self.assertEqual(K.rebalance_bound(moves, M.REBAL_MAX)[0], 0)
        self.assertGreater(len(moves), 0)

    def test_rebalance_bound_catches_a_plug(self):
        w = copy.deepcopy(self.w)
        w['B'].loc[0, 'VCIF'] += 1.0                  # not rounding
        _, _, moves, _ = assemble(w)
        self.assertGreater(K.rebalance_bound(moves, M.REBAL_MAX)[0], 0)

    def test_zero_cif_drops_vmsb_remnant(self):
        b = pd.DataFrame(dict(comm=['crp'], src=['AAA'], dst=['BBB'], VXSB=[0.0], VFOB=[0.0], VCIF=[0.0], VMSB=[1e-6]))
        v = pd.DataFrame(columns=['marg', 'comm', 'src', 'dst', 'VTWR'])
        nb, _, moves = M.rebalance_trade(b, v, pd.DataFrame(columns=['marg', 'region', 'VST']))
        self.assertEqual(nb.loc[0, 'VMSB'], 0.0)
        self.assertEqual(len(moves[moves['kind'] == 'VMSB']), 1)

    def test_issue_on_tax_without_base(self):
        w = copy.deepcopy(self.w)
        g = w['io']['AAA']
        g.loc[[f'dom_{c}' for c in SECTORS] + [f'imp_{c}' for c in SECTORS], 'g'] = 0.0
        g.loc['TLS', 'g'] = 1.0
        _, _, _, issues = assemble(w)
        self.assertTrue(any('zero basic' in i for i in issues))


# ------------------------------------------------------------------ check mutations
class CheckMutationTest(unittest.TestCase):
    def setUp(self):
        self.T, self.acc, self.moves, _ = assemble(world())

    def t(self):
        return {k: v.copy() for k, v in self.T.items()}

    def test_route_cif(self):
        T = self.t(); T['bilateral'].loc[0, 'VCIF'] += 0.1
        self.assertGreater(K.route_cif(T['bilateral'], T['vtwr'])[0], 0)
        T = self.t(); T['vtwr'] = pd.concat([T['vtwr'], pd.DataFrame([dict(marg='sea', comm='sea', src='AAA', dst='BBB', VTWR=1.0)])])
        self.assertGreater(K.route_cif(T['bilateral'], T['vtwr'])[0], 0)

    def test_global_margins(self):
        T = self.t(); T['vst'].loc[0, 'VST'] += 0.1
        self.assertGreater(K.global_margins(T['vtwr'], T['vst'])[0], 0)

    def test_market_clearing(self):
        T = self.t(); T['make'].loc[0, 'MAKB'] += 0.1
        self.assertGreater(K.market_clearing(T['firms'], T['final'], T['make'], T['bilateral'], T['vst'])[0], 0)

    def test_import_clearing(self):
        T = self.t(); T['bilateral'].loc[0, 'VMSB'] += 0.1
        self.assertGreater(K.import_clearing(T['firms'], T['final'], T['bilateral'])[0], 0)

    def test_zero_profit(self):
        T = self.t(); T['endw'].loc[0, 'EVFP'] += 0.1
        self.assertGreater(K.zero_profit(T['firms'], T['endw'], T['make'])[0], 0)

    def test_diagonal_make(self):
        T = self.t(); T['make'].loc[0, 'comm'] = 'sea'
        self.assertGreater(K.diagonal_make(T['make'])[0], 0)

    def test_one_tax_power(self):
        T = self.t()
        i = T['firms'].index[(T['firms']['VDFB'] > 0)][0]
        T['firms'].loc[i, 'VDFP'] *= 1.1
        self.assertGreater(K.one_tax_power(T['firms'], T['final'])[0], 0)
        T = self.t(); T['final'].loc[0, 'VDPP'] *= 1.1
        self.assertGreater(K.one_tax_power(T['firms'], T['final'])[0], 0)

    def test_factor_identities(self):
        T = self.t(); T['endw'].loc[0, 'EVFB'] = 0.0
        self.assertGreater(K.factor_identities(T['endw'])[0], 0)

    def test_factors_match_s13(self):
        fac = pd.concat(world()['fac'].values(), ignore_index=True)
        self.assertEqual(K.factors_match_s13(self.T['endw'], fac)[0], 0)
        fac.loc[0, 'evfp'] += 0.1
        self.assertGreater(K.factors_match_s13(self.T['endw'], fac)[0], 0)

    def test_signs(self):
        for k, c in (('firms', 'VDFB'), ('bilateral', 'VMSB'), ('endw', 'EVOS'), ('regional', 'VKB'), ('vtwr', 'VTWR')):
            T = self.t(); T[k].loc[T[k].index[0], c] = -1.0
            self.assertGreater(K.signs(T)[0], 0, k)

    def test_zero_divides(self):
        T = self.t(); T['make'].loc[0, 'MAKS'] = 0.0
        self.assertGreater(K.zero_divides(T)[0], 0)
        T = self.t(); T['bilateral'].loc[0, 'VCIF'] = 0.0
        self.assertGreater(K.zero_divides(T)[0], 0)
        T = self.t(); T['endw'] = T['endw'][~((T['endw']['region'] == 'AAA') & (T['endw']['acts'] == 'crp'))]
        self.assertGreater(K.zero_divides(T)[0], 0)

    def test_gdp_and_final_demand(self):
        g = self.acc['GDP_expenditure']
        self.assertEqual(K.gdp(self.acc, g)[0], 0)
        self.assertGreater(K.gdp(self.acc, g * 1.01)[0], 0)
        m13 = self.acc[['C', 'G', 'I']].reset_index()
        self.assertEqual(K.final_demand(self.acc, m13)[0], 0)
        m13.loc[0, 'C'] += 1.0
        self.assertGreater(K.final_demand(self.acc, m13)[0], 0)

    def test_saving_identity(self):
        reg = self.T['regional'].copy(); reg.loc[0, 'SAVE'] += 0.5
        self.assertGreater(K.saving_identity(self.acc, reg)[0], 0)
        acc = self.acc.copy(); acc.loc['AAA', 'SAVE'] += 0.5
        self.assertGreater(K.saving_identity(acc, self.T['regional'].assign(SAVE=acc['SAVE'].to_numpy()))[0], 0)

    def test_si_gate(self):
        bop = pd.DataFrame(columns=['net_primary_income_musd', 'net_secondary_income_musd'], dtype=float)
        g = M.si_gate(self.acc, bop)
        self.assertEqual(K.si_gate_hard(g, True)[0], 0)
        for col, v in (('VKB', -1.0), ('capital_income', 0.0), ('I', -1.0)):
            acc = self.acc.copy(); acc.loc['AAA', col] = v
            self.assertGreater(K.si_gate_hard(M.si_gate(acc, bop), False)[0], 0, col)
        # SAVE <= 0 is the eq. 7.1 residual: labelled with its cause, report-only unless hard_save_positive
        acc = self.acc.copy(); acc.loc['AAA', ['SAVE', 'X', 'M', 'I', 'VDEP']] = [-2.0, 1.0, 4.0, 2.0, 1.0]
        g = M.si_gate(acc, bop)
        self.assertEqual(g.loc['AAA', 'save_cause'], 'trade_deficit_at_least_net_investment')
        self.assertEqual(K.si_gate_hard(g, False)[0], 0)
        self.assertGreater(K.si_gate_hard(g, False, save_hard=True)[0], 0)
        acc.loc['AAA', ['I', 'VDEP']] = [1.0, 2.0]
        self.assertEqual(M.si_gate(acc, bop).loc['AAA', 'save_cause'], 'depreciation_above_investment')
        # the saving-share bound is hard only under hard_per_region
        acc = self.acc.copy(); acc.loc['AAA', 'saving_share'] = -1.5
        self.assertEqual(K.si_gate_hard(M.si_gate(acc, bop).assign(saving_share=acc['saving_share']), False)[0], 0)
        g = M.si_gate(acc, bop); g.loc['AAA', 'saving_share_in_bounds'] = False
        self.assertGreater(K.si_gate_hard(g, True)[0], 0)

    def test_sets_headers_chain(self):
        self.assertEqual(K.sets(REGS, SECTORS + ['air'], list(FACTORS), ['sea', 'air'])[0], 0)
        self.assertGreater(K.sets(REGS, SECTORS, list(FACTORS), ['sea'])[0], 0)
        self.assertGreater(K.sets(REGS, SECTORS, [f for f in FACTORS if f != 'capital'], ['sea', 'crp'])[0], 0)
        self.assertGreater(K.sets(REGS, SECTORS, list(FACTORS), ['sea', 'crp'], acts=SECTORS[::-1])[0], 0)
        self.assertEqual(K.sets(REGS, SECTORS, list(FACTORS), ['sea', 'crp'], acts=SECTORS)[0], 0)
        T = self.t(); T['vst'] = T['vst'].rename(columns={'VST': 'VSTX'})
        self.assertGreater(K.headers(T)[0], 0)
        ok = {'S10': ('aaa', {'S08': 'bbb'}), 'S08': ('bbb', {})}
        self.assertEqual(K.chain(ok)[0], 0)
        self.assertGreater(K.chain({'S10': ('aaa', {'S08': 'ccc'}), 'S08': ('bbb', {})})[0], 0)

    def test_merge_totals(self):
        t = pd.DataFrame([dict(region='AAA', sector='crp', X=10.0, XFOB=10.0, M=6.0, MCIF=6.0, VST=0.0),
                          dict(region='AAA', sector='sea', X=0.0, XFOB=0.0, M=0.0, MCIF=0.0, VST=2.0),
                          dict(region='BBB', sector='crp', X=5.0 / 1.02, XFOB=5.0, M=13.2, MCIF=12.0, VST=0.0),
                          dict(region='BBB', sector='sea', X=0.0, XFOB=0.0, M=0.0, MCIF=0.0, VST=1.0)])
        self.assertEqual(K.merge_totals(self.T['bilateral'], self.T['vst'], t)[0], 0)
        t.loc[0, 'X'] += 1.0
        self.assertGreater(K.merge_totals(self.T['bilateral'], self.T['vst'], t)[0], 0)


# ------------------------------------------------------------------ fix round: B14 small trade cells, A13 seed, A3/A4 stub
class SmallTradeTest(unittest.TestCase):
    """B14: VXSB routes and VTWR cells below USD 1 (1e-6 USD million) are set to zero (our choice)."""
    def setUp(self):
        self.w = world()

    def tiny(self):
        b = pd.concat([self.w['B'], pd.DataFrame([dict(comm='crp', src='AAA', dst='CCC', VXSB=5e-7, VFOB=5e-7, VCIF=6e-7, VMSB=6e-7)])], ignore_index=True)
        v = pd.concat([self.w['V'], pd.DataFrame([dict(marg='sea', comm='crp', src='AAA', dst='CCC', VTWR=1e-7),
                                                   dict(marg='air', comm='crp', src='AAA', dst='BBB', VTWR=4e-7)])], ignore_index=True)
        b.loc[(b['src'] == 'AAA') & (b['dst'] == 'BBB'), ['VCIF', 'VMSB']] = [12.0 + 4e-7, (12.0 + 4e-7) * 1.1]
        return b, v

    def test_filter_drops_tiny_routes_and_margin_cells(self):
        b, v = self.tiny()
        self.assertGreater(K.small_trade(b, v, M.SMALL_TRADE)[0], 0)
        nb, nv, dropped = M.filter_small_trade(b, v)
        self.assertEqual(K.small_trade(nb, nv, M.SMALL_TRADE)[0], 0)
        self.assertEqual(sorted(dropped['kind']), ['VTWR cell', 'VXSB route'])
        self.assertFalse(((nb['src'] == 'AAA') & (nb['dst'] == 'CCC')).any())
        self.assertFalse(((nv['dst'] == 'CCC') | (nv['marg'] == 'air')).any())
        r = nb[(nb['src'] == 'AAA') & (nb['dst'] == 'BBB')].iloc[0]
        self.assertAlmostEqual(r.VCIF, 12.0, places=12)               # VCIF falls by the margin cell set to zero
        self.assertAlmostEqual(r.VMSB / r.VCIF, 1.1, places=12)       # VMSB keeps its tariff power
        self.assertEqual(K.route_cif(nb, nv)[0], 0)
        # nothing below the cut: nothing moves
        nb2, nv2, d2 = M.filter_small_trade(self.w['B'], self.w['V'])
        self.assertEqual(len(d2), 0)
        self.assertTrue(nb2[BORDER_COLS].equals(self.w['B'][BORDER_COLS]))

    def test_vst_and_output_shift(self):
        b, v = self.tiny()
        vst = pd.DataFrame(dict(marg=['sea', 'sea', 'air'], region=['AAA', 'BBB', 'AAA'], VST=[2.0 + 1e-7, 1.0, 4e-7]))
        nb, nv, dropped = M.filter_small_trade(b, v)
        nvst = M.small_trade_vst(vst, v, nv)
        self.assertAlmostEqual(nvst.loc[nvst['marg'] == 'sea', 'VST'].sum(), nv.loc[nv['marg'] == 'sea', 'VTWR'].sum(), places=12)
        self.assertEqual(nvst.loc[nvst['marg'] == 'air', 'VST'].sum(), 0.0)
        sh = M.small_trade_output_shift(dropped, vst, nvst)
        self.assertAlmostEqual(sh[('AAA', 'crp')], 5e-7, places=15)   # the dropped route's sales abroad
        self.assertAlmostEqual(sh[('AAA', 'air')], 4e-7, places=15)   # the air margin supply

    def test_lost_output_comes_off_factor_payments(self):
        w = self.w
        g, fac = w['io']['AAA'], w['fac']['AAA']
        d = 5e-4                    # (above the check tolerance, so the mutation shows)
        base, _, _ = M.assemble_region('AAA', g, fac, {'crp': 10.0}, {'sea': 2.0}, {'crp': 6.0}, SECTORS, seed_ratio=0.0)
        p, mv, iss = M.assemble_region('AAA', g, fac, {'crp': 10.0 - d}, {'sea': 2.0}, {'crp': 6.0}, SECTORS, seed_ratio=0.0, small_shift={'crp': d})
        self.assertEqual(iss, [])
        va0 = sum(r[3] for r in base['endw'] if r[2] == 'crp')
        va1 = sum(r[3] for r in p['endw'] if r[2] == 'crp')
        self.assertAlmostEqual(va0 - va1, d, places=14)
        mk0 = [r for r in base['make'] if r[1] == 'crp'][0]
        mk1 = [r for r in p['make'] if r[1] == 'crp'][0]
        self.assertAlmostEqual(mk1[4] - mk1[3], mk0[4] - mk0[3], places=12)     # output tax unchanged
        self.assertAlmostEqual(mk0[4] - mk1[4], d, places=12)
        self.assertEqual([l_['rule'] for l_ in p['ledger']], [M.RULE_SMALL])
        delta = pd.DataFrame(p['fac_delta'], columns=['region', 'endw', 'acts', 'EVFP', 'EVFB', 'EVOS', 'rule'])
        T = M.frames([p])
        self.assertEqual(K.factors_match_s13(T['endw'], fac, delta)[0], 0)
        self.assertGreater(K.factors_match_s13(T['endw'], fac)[0], 0)
        self.assertEqual(K.rebalance_bound(pd.DataFrame(mv, columns=['kind', 'key', 'before', 'after']), M.REBAL_MAX)[0], 0)

    def test_import_row_emptied_by_the_filter_scales_without_negatives(self):
        w = copy.deepcopy(self.w)
        g = w['io']['AAA']
        g.loc['imp_crp', 'crp'] = 4e-7
        g.loc['imp_crp', 'p'] = 3e-7
        p, mv, iss = M.assemble_region('AAA', g, w['fac']['AAA'], {'crp': 10.0}, {'sea': 2.0}, {'crp': 0.0}, SECTORS, seed_ratio=0.0)
        self.assertEqual(iss, [])
        self.assertTrue(all(r[5] >= 0 for r in p['firms']))
        self.assertEqual(sum(r[5] for r in p['firms'] if r[1] == 'crp'), 0.0)


BORDER_COLS = ['VXSB', 'VFOB', 'VCIF', 'VMSB']


def one_sided_world():
    """The synthetic world with AAA's domestic crp sales removed: AAA buys crp only from imports (the crp it makes
    is all exported), the case of oil in COD, GAB, GUY and TCD. The io_s13 output and output tax follow."""
    w = world()
    g = w['io']['AAA']
    g.loc['PTAX', 'sea'] += g.loc['dom_crp', 'sea']      # sea's cost falls with the crp it no longer buys (TLS on sea is 0)
    g.loc['dom_crp', :] = 0.0
    g.loc['OUT', 'crp'] = 10.0
    basic = g.loc[[r for r in g.index if r.startswith(('dom_', 'imp_'))], 'crp'].sum()
    g.loc['PTAX', 'crp'] = 10.0 - basic - g.loc['TLS', 'crp'] - sum(g.loc[f'EVFP_{f}', 'crp'] for f in FACTORS)
    return w


def assemble_seeded(w, ratio=M.SEED_RATIO):
    B, vst, moves = M.rebalance_trade(w['B'], w['V'], w['vst'])
    xr = B.groupby(['src', 'comm'])['VXSB'].sum()
    mr = B.groupby(['dst', 'comm'])['VMSB'].sum()
    vr = vst.groupby(['region', 'marg'])['VST'].sum()
    parts, mv_all = [], [moves]
    for r in REGS:
        p, mv, iss = M.assemble_region(r, w['io'][r], w['fac'][r], xr.loc[r].to_dict(), vr.loc[r].to_dict(), mr.loc[r].to_dict(), SECTORS, seed_ratio=ratio)
        assert not iss, iss
        parts.append(p)
        mv_all.append(pd.DataFrame(mv, columns=['kind', 'key', 'before', 'after']))
    T = M.frames(parts)
    T['bilateral'], T['vtwr'], T['vst'] = B, w['V'], vst
    T['regional'] = pd.DataFrame(dict(region=REGS, VDEP=[1.0, 1.0], VKB=[25.0, 25.0], POP=[1.0, 2.0]))
    acc = M.regional_accounts(T, REGS)
    T['regional'].insert(1, 'SAVE', acc['SAVE'].to_numpy())
    seeds = pd.DataFrame([s for p in parts for s in p['seeds']], columns=['region', 'comm', 'imports', 'seed', 'ratio', 'n_buyers', 'seed_va',
                                                                          'seed_ptax', 'output_before', 'output_after'])
    delta = pd.DataFrame([d for p in parts for d in p['fac_delta']], columns=['region', 'endw', 'acts', 'EVFP', 'EVFB', 'EVOS', 'rule'])
    return T, acc, pd.concat(mv_all, ignore_index=True), seeds, delta, [l_ for p in parts for l_ in p['ledger']]


class SeedTest(unittest.TestCase):
    """A13: each commodity a region buys only from imports gets domestic purchases of SEED_RATIO x imports, with
    every total unchanged (our choice of size and closure; GTAP 10 has no one-sided pair)."""
    def setUp(self):
        self.w = one_sided_world()
        self.T0, self.acc0, _, _, _, _ = assemble_seeded(self.w, 0.0)
        self.T, self.acc, self.moves, self.seeds, self.delta, self.led = assemble_seeded(self.w)

    def test_unseeded_world_has_the_one_sided_pair(self):
        p = K.one_sided_pairs(self.T0['firms'], self.T0['final'])
        p = p[p['missing'] == 'domestic']          # (sea is bought only domestically in the synthetic world)
        self.assertEqual(p[['region', 'comm', 'missing']].values.tolist(), [['AAA', 'crp', 'domestic']])
        self.assertGreater(K.seed_check(self.T0['firms'], self.T0['final'], self.seeds.iloc[:0], M.SEED_RATIO)[0], 0)

    def test_seed_size_and_no_pair_left(self):
        self.assertEqual(len(self.seeds), 1)
        s = self.seeds.iloc[0]
        self.assertEqual((s.region, s.comm), ('AAA', 'crp'))
        self.assertAlmostEqual(s.seed, M.SEED_RATIO * 6.0, places=14)
        self.assertGreater(s.seed_va, 0.0)
        self.assertEqual(K.seed_check(self.T['firms'], self.T['final'], self.seeds, M.SEED_RATIO), (0, ''))
        p = K.one_sided_pairs(self.T['firms'], self.T['final'])
        self.assertEqual(len(p[p['missing'] == 'domestic']), 0)
        # mutation: a seed of the wrong size fails
        bad = self.seeds.assign(seed=self.seeds['seed'] * 2)
        self.assertGreater(K.seed_check(self.T['firms'], self.T['final'], bad, M.SEED_RATIO)[0], 0)

    def test_every_identity_holds_and_totals_are_unchanged(self):
        T, acc = self.T, self.acc
        for fn in (lambda: K.market_clearing(T['firms'], T['final'], T['make'], T['bilateral'], T['vst']),
                   lambda: K.import_clearing(T['firms'], T['final'], T['bilateral']),
                   lambda: K.zero_profit(T['firms'], T['endw'], T['make']), lambda: K.one_tax_power(T['firms'], T['final']),
                   lambda: K.factor_identities(T['endw']), lambda: K.signs(T), lambda: K.zero_divides(T),
                   lambda: K.saving_identity(acc, T['regional'])):
            n, det = fn()
            self.assertEqual(n, 0, det)
        cols = ['C', 'G', 'I', 'X', 'M', 'Y', 'SAVE', 'GDP_expenditure', 'GDP_income', 'EVFP', 'EVFB'] + [c for c in acc.columns if c.startswith('tax_')]
        self.assertTrue(np.allclose(acc[cols].to_numpy(float), self.acc0[cols].to_numpy(float), rtol=0, atol=1e-10))
        # the seed moves no output or output tax beyond rounding in the re-balance
        self.assertEqual(K.rebalance_bound(self.moves, M.REBAL_MAX)[0], 0)
        self.assertTrue(self.led and all(l_['rule'] in (M.RULE_SEED, M.RULE_CARVE) for l_ in self.led))

    def test_factor_check_needs_the_ledgered_moves(self):
        fac = pd.concat(self.w['fac'].values(), ignore_index=True)
        self.assertEqual(K.factors_match_s13(self.T['endw'], fac, self.delta)[0], 0)
        self.assertGreater(K.factors_match_s13(self.T['endw'], fac)[0], 0)
        bad = self.delta.copy(); bad.loc[0, 'EVFP'] += 0.01           # a move that does not net to zero
        self.assertGreater(K.factors_match_s13(self.T['endw'], fac, bad)[0], 0)

    def test_buyers_keep_their_totals(self):
        f0 = self.T0['firms'].groupby(['region', 'acts'])[['VDFP', 'VMFP']].sum().sum(axis=1)
        f1 = self.T['firms'].groupby(['region', 'acts'])[['VDFP', 'VMFP']].sum().sum(axis=1)
        # BBB is untouched; AAA sea (a buyer and a supplier) keeps a cost that falls only with its carved share
        self.assertTrue(np.allclose(f0.loc['BBB'], f1.loc['BBB'], rtol=0, atol=1e-12))
        d = self.T['final'].set_index(['region', 'comm'])
        self.assertGreater(d.loc[('AAA', 'crp'), 'VDPB'], 0.0)

    def test_switch_off(self):
        self.assertEqual(len(assemble_seeded(self.w, 0.0)[3]), 0)


# ------------------------------------------------------------------ fix list A1: S13 cell rates through S14
SECTORS_E = ['pet', 'sea']
WEDGE = {'pet': 0.20, 'sea': 0.30, 'p': 0.45, 'g': 0.0, 'i': 0.0}     # S13 energy wedge of the pet row by column


def as_pet(w):
    """The synthetic world with crp renamed pet, so its row is an energy row (ENERGY_TAX_ROWS)."""
    w = copy.deepcopy(w)
    for k in ('B', 'V'):
        w[k]['comm'] = w[k]['comm'].replace('crp', 'pet')
    for r in REGS:
        w['io'][r] = w['io'][r].rename(index=lambda x: x.replace('crp', 'pet'), columns={'crp': 'pet'})
        w['fac'][r]['sector'] = w['fac'][r]['sector'].replace('crp', 'pet')
    return w


def s13_cells(w):
    """tax_cells_s13 rows for the world: the pet row at WEDGE over the column's remainder rate, which is set so the
    column's TLS (io_s13) is unchanged, as S13 place_column_taxes does."""
    rows = []
    for r in REGS:
        g = w['io'][r]
        for col in SECTORS_E + list(FD):
            b = g.loc[[f'dom_{c}' for c in SECTORS_E] + [f'imp_{c}' for c in SECTORS_E], col]
            bs, bp = b.sum(), g.loc['dom_pet', col] + g.loc['imp_pet', col]
            if bs <= 0:
                continue
            rest = (g.loc['TLS', col] - bp * WEDGE[col]) / bs
            rows += [dict(region=r, column=col, commodity='pet', tls_rate=rest + WEDGE[col], pse_rate=0.0),
                     dict(region=r, column=col, commodity='sea', tls_rate=rest, pse_rate=0.0)]
    return pd.DataFrame(rows)


def assemble_cells(w, cells, ratio=0.0):
    B, vst, moves = M.rebalance_trade(w['B'], w['V'], w['vst'])
    xr = B.groupby(['src', 'comm'])['VXSB'].sum()
    mr = B.groupby(['dst', 'comm'])['VMSB'].sum()
    vr = vst.groupby(['region', 'marg'])['VST'].sum()
    parts, mv_all, issues = [], [moves], []
    for r in REGS:
        cr = M.cell_rate_matrix(cells[cells['region'] == r], SECTORS_E) if cells is not None else None
        p, mv, iss = M.assemble_region(r, w['io'][r], w['fac'][r], xr.loc[r].to_dict(), vr.loc[r].to_dict(), mr.loc[r].to_dict(), SECTORS_E,
                                       seed_ratio=ratio, cell_rates=cr)
        parts.append(p)
        mv_all.append(pd.DataFrame(mv, columns=['kind', 'key', 'before', 'after']))
        issues += iss
    T = M.frames(parts)
    T['bilateral'], T['vtwr'], T['vst'] = B, w['V'], vst
    T['regional'] = pd.DataFrame(dict(region=REGS, VDEP=[1.0, 1.0], VKB=[25.0, 25.0], POP=[1.0, 2.0]))
    acc = M.regional_accounts(T, REGS)
    T['regional'].insert(1, 'SAVE', acc['SAVE'].to_numpy())
    seed_cols = {(r, c) for r, p in zip(REGS, parts) for c in p['seed_cols']}
    return T, acc, pd.concat(mv_all, ignore_index=True), issues, seed_cols


class SwapTest(unittest.TestCase):
    """A13, the other side: a domestic-only pair imports ratio x its domestic purchases through a swap."""

    def test_swap_routes_and_partner(self):
        b = pd.DataFrame([dict(comm='oil', src='BIG', dst='MID', VXSB=100.0, VFOB=100.0, VCIF=105.0, VMSB=105.0),
                          dict(comm='oil', src='SAU', dst='MID', VXSB=50.0, VFOB=55.0, VCIF=57.0, VMSB=57.0),
                          dict(comm='oil', src='SAU', dst='BIG', VXSB=10.0, VFOB=11.0, VCIF=12.0, VMSB=12.0),
                          dict(comm='oil', src='MID', dst='BIG', VXSB=1.0, VFOB=1.0, VCIF=1.1, VMSB=1.1),
                          dict(comm='oil', src='XTR', dst='BIG', VXSB=5.0, VFOB=5.0, VCIF=5.5, VMSB=5.5),
                          dict(comm='oil', src='BIG', dst='XTR', VXSB=0.5, VFOB=0.5, VCIF=0.6, VMSB=0.6)])
        dom = pd.Series({('SAU', 'oil'): 1000.0, ('BIG', 'oil'): 500.0, ('MID', 'oil'): 200.0, ('XTR', 'oil'): 300.0})
        b2, sw, switch = M.import_seed_swaps(b, dom, 1e-4)
        # BIG has the route SAU->BIG, MID the route SAU->MID; XTR is the next exporter with neither route
        self.assertEqual(sw.to_dict('records'), [dict(region='SAU', comm='oil', partner='XTR', musd=0.1, merged=False)])
        self.assertEqual(switch, {('SAU', 'oil'): 0.1, ('XTR', 'oil'): 0.1})
        for k in (('oil', 'XTR', 'SAU'), ('oil', 'SAU', 'XTR')):
            r = b2.set_index(['comm', 'src', 'dst']).loc[k]
            self.assertTrue(all(abs(r[h] - 0.1) < 1e-12 for h in M.BORDER))

    def test_swap_merged_when_every_partner_buys_from_r(self):
        # SAU sells to every exporter: the largest one with no route to SAU takes the swap, the route SAU->BIG grows by a
        b = pd.DataFrame([dict(comm='oil', src='BIG', dst='MID', VXSB=100.0, VFOB=100.0, VCIF=105.0, VMSB=105.0),
                          dict(comm='oil', src='SAU', dst='BIG', VXSB=10.0, VFOB=11.0, VCIF=12.0, VMSB=12.0),
                          dict(comm='oil', src='SAU', dst='MID', VXSB=5.0, VFOB=5.0, VCIF=5.5, VMSB=5.5),
                          dict(comm='oil', src='MID', dst='BIG', VXSB=1.0, VFOB=1.0, VCIF=1.1, VMSB=1.1)])
        dom = pd.Series({('SAU', 'oil'): 1000.0, ('BIG', 'oil'): 500.0, ('MID', 'oil'): 200.0})
        b2, sw, switch = M.import_seed_swaps(b, dom, 1e-4)
        self.assertEqual(sw.to_dict('records'), [dict(region='SAU', comm='oil', partner='BIG', musd=0.1, merged=True)])
        rt = b2.set_index(['comm', 'src', 'dst'])
        self.assertTrue(all(abs(rt.loc[('oil', 'BIG', 'SAU'), h] - 0.1) < 1e-12 for h in M.BORDER))
        self.assertAlmostEqual(rt.loc[('oil', 'SAU', 'BIG'), 'VXSB'], 10.1)
        self.assertAlmostEqual(rt.loc[('oil', 'SAU', 'BIG'), 'VMSB'], 12.1)
        self.assertEqual(switch, {('SAU', 'oil'): 0.1, ('BIG', 'oil'): 0.1})

    def test_switch_keeps_column_totals(self):
        dom = np.array([[2.0, 6.0], [1.0, 1.0]])
        imp = np.zeros((2, 2))
        M.switch_to_imports(dom, imp, 0, 0.8)
        np.testing.assert_allclose(dom[0] + imp[0], [2.0, 6.0])
        np.testing.assert_allclose(imp[0], [0.2, 0.6])

    def test_seed_check_flags_domestic_only(self):
        fi = pd.DataFrame([dict(region='R', comm='oil', acts='pet', VDFB=5.0, VDFP=5.0, VMFB=0.0, VMFP=0.0)])
        fd = pd.DataFrame(columns=['region', 'comm'] + [h for ag in FD for h in M.FD_HEADERS[ag]])
        n, det = K.seed_check(fi, fd, pd.DataFrame(), 1e-4, pd.DataFrame(columns=['region', 'comm', 'partner', 'musd']))
        self.assertEqual(n, 1)
        self.assertIn('no imported purchase', det)


class CellRateTest(unittest.TestCase):
    """Fix list A1: S14 keeps S13's net product-tax rate on every energy cell, with the column totals unchanged."""
    def setUp(self):
        self.w = as_pet(world())
        self.cells = s13_cells(self.w)
        self.T, self.acc, self.moves, self.issues, _ = assemble_cells(self.w, self.cells)
        self.T1, self.acc1, _, _, _ = assemble_cells(self.w, None)          # one power per column (pre-fix)

    def test_identities_and_totals(self):
        T, acc = self.T, self.acc
        self.assertEqual(self.issues, [])
        for fn in (lambda: K.market_clearing(T['firms'], T['final'], T['make'], T['bilateral'], T['vst']),
                   lambda: K.import_clearing(T['firms'], T['final'], T['bilateral']),
                   lambda: K.zero_profit(T['firms'], T['endw'], T['make']), lambda: K.cell_tax_power(T['firms'], T['final']),
                   lambda: K.cell_rates_match_s13(T['firms'], T['final'], self.cells), lambda: K.signs(T), lambda: K.zero_divides(T),
                   lambda: K.saving_identity(acc, T['regional']), lambda: K.rebalance_bound(self.moves, M.REBAL_MAX)):
            n, det = fn()
            self.assertEqual(n, 0, det)
        # every column total, C, G, I, GDP and tax total is what one power per column gives
        cols = ['C', 'G', 'I', 'GDP_expenditure', 'GDP_income', 'SAVE'] + [c for c in acc.columns if c.startswith('tax_')]
        self.assertTrue(np.allclose(acc[cols].to_numpy(float), self.acc1[cols].to_numpy(float), rtol=0, atol=1e-10))
        f0 = self.T1['firms'].groupby(['region', 'acts'])[['VDFP', 'VMFP']].sum().sum(axis=1)
        f1 = self.T['firms'].groupby(['region', 'acts'])[['VDFP', 'VMFP']].sum().sum(axis=1)
        self.assertTrue(np.allclose(f0, f1, rtol=0, atol=1e-10))

    def test_energy_cell_keeps_its_rate(self):
        fd = self.T['final'].set_index(['region', 'comm'])
        pet, sea = fd.loc[('AAA', 'pet')], fd.loc[('AAA', 'sea')]
        self.assertAlmostEqual(pet['VDPP'] / pet['VDPB'] - sea['VDPP'] / sea['VDPB'], WEDGE['p'], places=10)

    def test_one_power_per_column_undoes_a1(self):
        # mutation: the pre-fix one power per column fails the A1 check
        self.assertGreater(K.cell_rates_match_s13(self.T1['firms'], self.T1['final'], self.cells)[0], 0)
        # mutation: an S13 cell rate the tables do not carry
        bad = self.cells.copy()
        bad.loc[(bad['commodity'] == 'pet') & (bad['column'] == 'sea'), 'tls_rate'] += 0.05
        self.assertGreater(K.cell_rates_match_s13(self.T['firms'], self.T['final'], bad)[0], 0)

    def test_cell_power_mutations(self):
        T = copy.deepcopy(self.T)
        i = T['firms'].index[(T['firms']['comm'] == 'pet') & (T['firms']['VMFB'] > 0) & (T['firms']['VDFB'] > 0)][0]
        T['firms'].loc[i, 'VMFP'] *= 1.05                   # imported pet at another power than domestic pet
        self.assertGreater(K.cell_tax_power(T['firms'], T['final'])[0], 0)
        T = copy.deepcopy(self.T)
        i = T['firms'].index[T['firms']['comm'] == 'sea'][0]
        T['firms'].loc[i, 'VDFP'] = 0.0                     # a basic value with no purchaser value
        self.assertGreater(K.cell_tax_power(T['firms'], T['final'])[0], 0)
        # two powers on the non-energy rows of one column (a third commodity in the column)
        f = pd.DataFrame(dict(region=['AAA'] * 2, comm=['crp', 'sea'], acts=['sea'] * 2, VDFB=[1.0, 1.0], VDFP=[1.1, 1.2], VMFB=[0.0, 0.0], VMFP=[0.0, 0.0]))
        self.assertGreater(K.cell_tax_power(f, T['final'].iloc[:0])[0], 0)

    def test_cell_power_pse_item(self):
        # fix round wG: a listed PSE input item keeps its own S13 rate, apart from the column's shared non-energy power
        f = pd.DataFrame(dict(region=['AAA'] * 3, comm=['crp', 'sea', 'chm'], acts=['crp'] * 3, VDFB=[1.0, 1.0, 2.0],
                              VDFP=[0.9, 0.9, 0.5], VMFB=[0.0] * 3, VMFP=[0.0] * 3))
        fd0 = self.T['final'].iloc[:0]
        cells = pd.DataFrame(dict(region=['AAA'] * 3, column=['crp'] * 3, commodity=['crp', 'sea', 'chm'],
                                  tls_rate=[0.0] * 3, pse_rate=[-0.1, -0.1, -0.75]))
        self.assertGreater(K.cell_tax_power(f, fd0)[0], 0)                                   # unlisted: two powers fail
        self.assertEqual(K.cell_tax_power(f, fd0, {('AAA', 'crp', 'chm')}, cells)[0], 0)      # listed at its S13 rate
        bad = cells.assign(pse_rate=[-0.1, -0.1, -0.5])
        self.assertGreater(K.cell_tax_power(f, fd0, {('AAA', 'crp', 'chm')}, bad)[0], 0)      # listed but off its S13 rate
        # in a column the A13 seed moved, one shift on every non-energy row (the item included) still passes
        g = f.assign(VDFP=f['VDFB'] * (1.0 + np.array([-0.1, -0.1, -0.75]) + 0.03))
        self.assertEqual(K.cell_tax_power(g, fd0, {('AAA', 'crp', 'chm')}, cells)[0], 0)

    def test_commodity_rates_on_non_energy_rows(self):
        """QA round 2 P1: S13 puts a rate by commodity on the non-energy rows; S14-Hpower takes the S13 rates plus one
        shift per column, S14-Hcellrates every cell at its S13 rate (in an A13 column up to one shift)."""
        r13 = {'crp': 0.05, 'sea': 0.0, 'trd': 0.20, 'pet': 0.60}
        cells = pd.DataFrame([dict(region='AAA', column='x', commodity=c, tls_rate=r, pse_rate=0.0) for c, r in r13.items() if r])

        def tables(shift=0.0, bump=None):
            rows = []
            for c, r in r13.items():
                p = 1.0 + r + shift + (0.01 if c == bump else 0.0)
                rows.append(dict(region='AAA', comm=c, acts='x', VDFB=10.0, VDFP=10.0 * p, VMFB=2.0, VMFP=2.0 * p))
            return pd.DataFrame(rows), pd.DataFrame(columns=['region', 'comm'] + [h for ag in FD for h in M.FD_HEADERS[ag]])
        fi, fd = tables()
        self.assertEqual(K.cell_tax_power(fi, fd, cells13=cells)[0], 0)
        self.assertEqual(K.cell_rates_match_s13(fi, fd, cells)[0], 0)
        self.assertGreater(K.cell_tax_power(fi, fd)[0], 0)                       # one non-energy power does not hold any more
        fi, fd = tables(bump='trd')                                                # mutation: one commodity off its S13 rate
        self.assertGreater(K.cell_tax_power(fi, fd, cells13=cells)[0], 0)
        self.assertGreater(K.cell_rates_match_s13(fi, fd, cells)[0], 0)
        fi, fd = tables(shift=0.02)                                                # one shift per column: an A13 column passes
        self.assertEqual(K.cell_tax_power(fi, fd, cells13=cells)[0], 0)
        self.assertGreater(K.cell_rates_match_s13(fi, fd, cells)[0], 0)
        self.assertEqual(K.cell_rates_match_s13(fi, fd, cells, {('AAA', 'x')})[0], 0)

    def test_seed_keeps_wedges_and_totals(self):
        w = as_pet(one_sided_world())
        cells = s13_cells(w)
        T, acc, moves, issues, seed_cols = assemble_cells(w, cells, M.SEED_RATIO)
        T0, acc0, _, _, _ = assemble_cells(w, cells, 0.0)
        self.assertEqual(issues, [])
        self.assertTrue(seed_cols)
        for fn in (lambda: K.market_clearing(T['firms'], T['final'], T['make'], T['bilateral'], T['vst']),
                   lambda: K.zero_profit(T['firms'], T['endw'], T['make']), lambda: K.cell_tax_power(T['firms'], T['final']),
                   lambda: K.cell_rates_match_s13(T['firms'], T['final'], cells, seed_cols),
                   lambda: K.rebalance_bound(moves, M.REBAL_MAX)):
            n, det = fn()
            self.assertEqual(n, 0, det)
        cols = ['C', 'G', 'I', 'GDP_expenditure', 'GDP_income'] + [c for c in acc.columns if c.startswith('tax_')]
        self.assertTrue(np.allclose(acc[cols].to_numpy(float), acc0[cols].to_numpy(float), rtol=0, atol=1e-10))


class ExportTaxTest(unittest.TestCase):
    """Fix list A2: S14-Hxtax (s13_fit.checks.export_tax_held on the bilateral table): the export tax on goods (S10
    wedge) and on energy (S10 rate x S11 VFOB) reaches the header tables."""
    def test_carried_and_dropped(self):
        from s13_fit import checks as K13
        w = world()
        gx = pd.DataFrame(dict(sector=['crp', 'crp'], exporter=['AAA', 'BBB'], importer=['BBB', 'AAA'], vxsb_musd=[10.0, 5.0 / 1.02], vfob_musd=[10.0, 5.0]))
        ex = pd.DataFrame(dict(sector=['oil'], exporter=['AAA'], importer=['BBB'], vxsb_musd=[9.0], vfob_musd=[10.0]))
        xt10 = pd.DataFrame(dict(exporter=['AAA'], sector=['oil'], rate=[0.1]))
        B = pd.concat([w['B'], pd.DataFrame(dict(comm=['oil'], src=['AAA'], dst=['BBB'], VXSB=[9.0], VFOB=[10.0], VCIF=[10.0], VMSB=[10.0]))], ignore_index=True)

        def held(b):
            return b.groupby(['src', 'comm'], as_index=False)[['VXSB', 'VFOB']].sum().rename(columns={'src': 'region', 'comm': 'sector', 'VXSB': 'X', 'VFOB': 'XFOB'})
        self.assertEqual(K13.export_tax_held(held(B), ex, xt10, gx), (0, ''))
        bad = B.copy(); bad.loc[bad['comm'] == 'oil', 'VXSB'] = 10.0          # energy export tax dropped (pre-fix S11)
        self.assertGreater(K13.export_tax_held(held(bad), ex, xt10, gx)[0], 0)
        bad = B.copy(); bad.loc[(bad['comm'] == 'crp') & (bad['src'] == 'BBB'), 'VXSB'] = 5.0   # goods export tax dropped
        self.assertGreater(K13.export_tax_held(held(bad), ex, xt10, gx)[0], 0)


class S12StubTest(unittest.TestCase):
    """Fix list A3/A4: a present S12 tax split cannot be ignored silently."""
    def test_stub_raises(self):
        self.assertEqual(set(M.S12_OPTIONAL), {'d29_split', 'pse_land_factor_use'})
        with self.assertRaises(NotImplementedError):
            M.join_s12_tax_split('d29_split', pd.DataFrame({'region': ['AAA']}), {})


# ------------------------------------------------------------------ fix round B16 on the S14 data (ch.12.A; ch.17B)
NAT_T = {'crp': dict(eta=0.5, sigma=0.2)}       # crp stands in for a resource sector (fossil-fuel target, sigma_VA 0.2)
NAT_FLOOR = 0.10


def natres_world():
    """The synthetic world with crp as a resource activity. AAA crp carries natural resources at 10 percent of VA (taken
    from capital, at its own rates: EVFB 0.97, EVOS 0.92 of EVFP); BBB has none, so its new cell takes the fallback rates."""
    w = world()
    g, f = w['io']['AAA'], w['fac']['AAA']
    va = g.loc[[f'EVFP_{x}' for x in FACTORS], 'crp'].sum()
    n0 = 0.1 * va
    g.loc['EVFP_capital', 'crp'] -= n0
    g.loc['EVFP_natres', 'crp'] = n0
    k = (f['sector'] == 'crp') & (f['factor'] == 'capital')
    f.loc[k, ['evfp', 'evfb', 'evos']] = f.loc[k, ['evfp', 'evfb', 'evos']].to_numpy() - np.array([n0, 0.95 * n0, 0.9 * n0])
    w['fac']['AAA'] = pd.concat([f, pd.DataFrame([dict(region='AAA', sector='crp', factor='natres', evfp=n0, evfb=0.97 * n0, evos=0.92 * n0)])], ignore_index=True)
    return w


def assemble_natres(w, on=True):
    B, vst, moves = M.rebalance_trade(w['B'], w['V'], w['vst'])
    xr = B.groupby(['src', 'comm'])['VXSB'].sum()
    mr = B.groupby(['dst', 'comm'])['VMSB'].sum()
    vr = vst.groupby(['region', 'marg'])['VST'].sum()
    parts = []
    for r in REGS:
        p, mv, iss = M.assemble_region(r, w['io'][r], w['fac'][r], xr.loc[r].to_dict(), vr.loc[r].to_dict(), mr.loc[r].to_dict(), SECTORS,
                                       natres=dict(targets=NAT_T, floor=NAT_FLOOR) if on else None)
        assert not iss, iss
        parts.append(p)
    T = M.frames(parts)
    T['bilateral'], T['vtwr'], T['vst'] = B, w['V'], vst
    T['regional'] = pd.DataFrame(dict(region=REGS, VDEP=[1.0, 1.0], VKB=[25.0, 25.0], POP=[1.0, 2.0]))
    acc = M.regional_accounts(T, REGS)
    T['regional'].insert(1, 'SAVE', acc['SAVE'].to_numpy())
    delta = pd.DataFrame([d for p in parts for d in p['fac_delta']], columns=['region', 'endw', 'acts', 'EVFP', 'EVFB', 'EVOS', 'rule'])
    return T, acc, delta, pd.DataFrame([x for p in parts for x in p['natres']])


class NatresFinalTest(unittest.TestCase):
    """Fix round B16 on the final data (S12-17): S14 sets the ch.12.A natural-resource share at its own theta_VA, so eta
    equals the target on the S14 tables, with every column, income and tax-rate total held."""
    def setUp(self):
        self.w = natres_world()
        self.T0, self.acc0, self.d0, _ = assemble_natres(self.w, on=False)
        self.T, self.acc, self.delta, self.rows = assemble_natres(self.w)
        self.fac13 = pd.concat(self.w['fac'].values(), ignore_index=True)

    def test_eta_hits_the_target_only_after_the_step(self):
        self.assertEqual(K.natres_eta(self.T['endw'], self.T['make'], NAT_T, NAT_FLOOR), (0, ''))
        self.assertGreater(K.natres_eta(self.T0['endw'], self.T0['make'], NAT_T, NAT_FLOOR)[0], 0)
        c = K.natres_cells(self.T['endw'], self.T['make'], NAT_T, NAT_FLOOR)
        self.assertTrue(np.allclose(c['eta'], 0.5, rtol=0, atol=1e-9))
        self.assertTrue(np.allclose(self.rows['eta_after'], 0.5) and (self.rows['eta_before'].dropna() != 0.5).all())

    def test_totals_held(self):
        T, acc = self.T, self.acc
        for fn in (lambda: K.zero_profit(T['firms'], T['endw'], T['make']), lambda: K.market_clearing(T['firms'], T['final'], T['make'], T['bilateral'], T['vst']),
                   lambda: K.factor_identities(T['endw']), lambda: K.signs(T), lambda: K.zero_divides(T),
                   lambda: K.saving_identity(acc, T['regional']), lambda: K.factors_match_s13(T['endw'], self.fac13, self.delta),
                   lambda: K.natres_pro_rata(T['endw'], self.delta)):
            n, det = fn()
            self.assertEqual(n, 0, det)
        cols = ['C', 'G', 'I', 'X', 'M', 'Y', 'SAVE', 'GDP_expenditure', 'GDP_income', 'EVFP', 'tax_output', 'tax_firms']
        self.assertTrue(np.allclose(acc[cols].to_numpy(float), self.acc0[cols].to_numpy(float), rtol=0, atol=1e-10))
        va0 = self.T0['endw'].groupby(['region', 'acts'])['EVFP'].sum()
        va1 = T['endw'].groupby(['region', 'acts'])['EVFP'].sum()
        self.assertTrue(np.allclose(va0, va1.reindex(va0.index), rtol=0, atol=1e-12))
        self.assertTrue(np.allclose(self.T0['make'][['MAKS', 'MAKB']], T['make'][['MAKS', 'MAKB']], rtol=0, atol=1e-12))

    def test_rates_kept(self):
        e = self.T['endw'].set_index(['region', 'endw', 'acts'])
        e0 = self.T0['endw'].set_index(['region', 'endw', 'acts'])
        for k in e0.index:
            if k[1] == 'natres' or k[2] != 'crp':
                continue
            self.assertAlmostEqual(e.loc[k, 'EVFB'] / e.loc[k, 'EVFP'], e0.loc[k, 'EVFB'] / e0.loc[k, 'EVFP'], places=12)
            self.assertAlmostEqual(e.loc[k, 'EVOS'] / e.loc[k, 'EVFB'], e0.loc[k, 'EVOS'] / e0.loc[k, 'EVFB'], places=12)
        a = e.loc[('AAA', 'natres', 'crp')]                     # its own rates
        self.assertAlmostEqual(a['EVFB'] / a['EVFP'], 0.97, places=12)
        self.assertAlmostEqual(a['EVOS'] / a['EVFB'], 0.92 / 0.97, places=12)
        b = e.loc[('BBB', 'natres', 'crp')]                     # no factor-use tax, capital's income-tax rate
        self.assertEqual(b['EVFB'], b['EVFP'])
        self.assertAlmostEqual(b['EVOS'] / b['EVFB'], 0.9 / 0.95, places=12)
        self.assertEqual(dict(zip(self.rows['region'], self.rows['natres_rates_from'])),
                         {'AAA': 'cell', 'BBB': 'no factor-use tax, region capital income-tax rate'})

    def test_check_mutations(self):
        T = self.T
        bad = T['endw'].copy(); k = (bad['endw'] == 'natres') & (bad['region'] == 'AAA')
        bad.loc[k, 'EVFP'] *= 1.01                               # natural resources 1 percent high
        self.assertGreater(K.natres_eta(bad, T['make'], NAT_T, NAT_FLOOR)[0], 0)
        bad = T['endw'].copy(); k = (bad['endw'] == 'capital') & (bad['region'] == 'AAA') & (bad['acts'] == 'crp')
        bad.loc[k, 'EVFB'] *= 0.99                               # capital's factor-use rate moved
        self.assertGreater(K.natres_pro_rata(bad, self.delta)[0], 0)
        d = self.delta.copy(); k = (d['rule'] == M.RULE_NATRES) & (d['endw'] == 'natres') & (d['region'] == 'AAA')
        d.loc[k, 'EVFP'] += 0.05                                 # a move that changes the activity's value added
        self.assertGreater(K.factors_match_s13(T['endw'], self.fac13, d)[0], 0)
        self.assertGreater(K.natres_pro_rata(T['endw'], d)[0], 0)
        # a capital-only take: labour and capital no longer move by one factor
        bad = T['endw'].copy()
        lab = (bad['region'] == 'AAA') & (bad['acts'] == 'crp') & (bad['endw'] == 'ag_othlowsk')
        cap = (bad['region'] == 'AAA') & (bad['acts'] == 'crp') & (bad['endw'] == 'capital')
        x = 0.1 * bad.loc[lab, 'EVFP'].iloc[0]
        for c_ in ('EVFP', 'EVFB', 'EVOS'):
            r_ = bad.loc[lab, c_].iloc[0] / bad.loc[lab, 'EVFP'].iloc[0]
            bad.loc[lab, c_] += x * r_
            bad.loc[cap, c_] -= x * bad.loc[cap, c_].iloc[0] / bad.loc[cap, 'EVFP'].iloc[0]
        self.assertGreater(K.natres_pro_rata(bad, self.delta)[0], 0)

    def test_guard_and_unknown_sector(self):
        E = {k: np.zeros((len(FACTORS), 2)) for k in ('EVFP', 'EVFB', 'EVOS')}
        iK, iL = FACTORS.index('capital'), FACTORS.index('ag_othlowsk')
        for k in E:
            E[k][iK] = [1.0, 2.0]; E[k][iL] = [1.0, 2.0]
        iss = []
        rows = M.natres_final('AAA', E, np.array([100.0, 8.0]), ['crp', 'sea'], NAT_T, NAT_FLOOR, iss)
        self.assertEqual(iss, [])
        self.assertEqual(len(rows), 1)                           # sea is not a resource sector
        r = rows[0]
        self.assertTrue(r['guard'])                              # theta_VA 0.02 < 0.10
        self.assertAlmostEqual(r['share_after'], 0.2 / (0.5 * NAT_FLOOR + 0.2), places=12)
        self.assertAlmostEqual(E['EVFP'][:, 0].sum(), 2.0, places=12)
        self.assertEqual(E['EVFP'][FACTORS.index('natres'), 1], 0.0)
        en = pd.DataFrame([('AAA', FACTORS[k], 'crp', E['EVFP'][k, 0], E['EVFB'][k, 0], E['EVOS'][k, 0]) for k in range(len(FACTORS)) if E['EVFP'][k, 0]],
                          columns=['region', 'endw', 'acts', 'EVFP', 'EVFB', 'EVOS'])
        mk = pd.DataFrame(dict(region=['AAA'], comm=['crp'], acts=['crp'], MAKS=[100.0], MAKB=[100.0]))
        self.assertEqual(K.natres_eta(en, mk, NAT_T, NAT_FLOOR), (0, ''))
        en.loc[en['endw'] == 'natres', 'EVFP'] *= 0.9           # a guarded cell off its floor share
        self.assertGreater(K.natres_eta(en, mk, NAT_T, NAT_FLOOR)[0], 0)
        # natural resources without value added are an issue
        E2 = {k: np.zeros((len(FACTORS), 1)) for k in ('EVFP', 'EVFB', 'EVOS')}
        E2['EVFP'][FACTORS.index('natres'), 0] = 1.0; E2['EVFP'][iK, 0] = -1.0
        iss = []
        M.natres_final('AAA', E2, np.array([10.0]), ['crp'], NAT_T, NAT_FLOOR, iss)
        self.assertEqual(len(iss), 1)

    def test_s14_uses_the_s12_targets(self):
        from s12_factors import config as C12
        self.assertIn('natres_final', C.CHOICES)
        self.assertEqual(C.load_choices()['natres_final']['value'], C.CHOICES['natres_final'][0])
        c12 = C12.load_choices()
        self.assertEqual(c12['natres_rule']['value'], 'gtap_ch12a_target_supply_elasticity_share_out_of_all_va')
        self.assertIn(c12['natres_guard']['value'], C12.NATRES_GUARD_FLOOR)
        self.assertEqual(sorted(C12.load_natres_targets()), sorted(['for', 'fsh', 'coa', 'oil', 'gas', 'ore', 'min', 'msp']))


# ------------------------------------------------------------------ fix round w17: S14 hard-check failures on the rerun
def seed_arrays(other_sea=0.01):
    """One region, crp bought only from imports: the sea column buys 1000 of imported crp and other_sea of everything
    else (URY mvh: 443.8 of imported crude, 0.013 of the rest), households buy 10 of imported crp and 50 of sea."""
    n, J = 2, 2 + len(FD)
    dom, imp = np.zeros((n, J)), np.zeros((n, J))
    imp[0, 1], imp[0, 2] = 1000.0, 10.0
    dom[1, 0], dom[1, 1], dom[1, 2] = 1.0, 0.4 * other_sea, 50.0
    imp[1, 1] = 0.6 * other_sea
    E = {k: np.zeros((len(FACTORS), n)) for k in ('EVFP', 'EVFB', 'EVOS')}
    for k in E:
        E[k][FACTORS.index('capital')] = [2.0, 3.0]
        E[k][FACTORS.index('ag_othlowsk')] = [1.0, 4.0]
    out_pre = dom.sum(axis=1) + np.array([5.0, 0.0])
    return dom, imp, E, out_pre


class CapitalFloorTest(unittest.TestCase):
    """Beta v4 capital_floor (S16 alone_bfa): a small A13 seed is raised to SEED_MIN, and capital is at least
    min(CAPITAL_MIN, half of VA), taken from labour with VA unchanged."""
    def test_seed_min_raises_a_small_row(self):
        dom, imp, E, out_pre = seed_arrays(0.01)
        T = np.zeros(dom.shape[1]); iss = []
        seeds, _ = M.seed_one_sided('AAA', dom, imp, T, np.zeros_like(T), E, out_pre.copy(), np.zeros(2), SECTORS, M.SEED_RATIO, iss,
                                    seed_min=1.0)                                   # 1e-4 x 1010 = 0.101 < 1.0
        self.assertEqual(iss, [])
        self.assertAlmostEqual(seeds[0]['seed'], 1.0, delta=1e-12)
        self.assertAlmostEqual(seeds[0]['ratio'], 1.0 / 1010.0)
        self.assertAlmostEqual(dom[0].sum(), 1.0, delta=1e-12)
        # infeasible at the minimum: the plain ratio stands
        dom, imp, E, out_pre = seed_arrays(0.01)
        seeds, _ = M.seed_one_sided('AAA', dom, imp, T, np.zeros_like(T), E, out_pre.copy(), np.zeros(2), SECTORS, M.SEED_RATIO, iss,
                                    seed_min=500.0)
        self.assertAlmostEqual(seeds[0]['seed'], M.SEED_RATIO * 1010.0, delta=1e-12)

    def test_capital_floor_moves_labour(self):
        n = 3
        E = {k: np.zeros((len(FACTORS), n)) for k in ('EVFP', 'EVFB', 'EVOS')}
        cap, lab, nat = FACTORS.index('capital'), FACTORS.index('ag_othlowsk'), FACTORS.index('natres')
        for k, f in (('EVFP', 1.0), ('EVFB', 0.9), ('EVOS', 0.8)):
            E[k][cap] = [8e-10 * f, 5.0 * f, 0.0]
            E[k][lab] = [2e-6 * f, 1.0 * f, 0.0]
            E[k][nat] = [1e-9 * f, 0.0, 0.0]
        va0 = {k: E[k].sum(axis=0).copy() for k in E}
        moved = M.capital_floor(E)
        self.assertEqual(moved, [0])                                                # column 1 already holds capital; 2 has no VA
        self.assertAlmostEqual(E['EVFP'][cap, 0], 1e-6, delta=1e-18)
        self.assertEqual(E['EVFP'][nat, 0], 1e-9)                                   # natural resources untouched
        for k in E:
            np.testing.assert_allclose(E[k].sum(axis=0), va0[k], rtol=1e-12)
        en = pd.DataFrame([dict(region='R', endw=FACTORS[f], acts=str(j), EVFP=E['EVFP'][f, j]) for f in range(len(FACTORS)) for j in range(n)])
        self.assertEqual(K.capital_floor_held(en, M.CAPITAL_MIN)[0], 0)


class SeedCapTest(unittest.TestCase):
    """Fix round w17 (A13 on URY): a buyer column with too little else to give up must not turn cells negative or leave
    the seed short; the row seed stays ratio x imports exactly and every cell non-negative."""
    def run_seed(self, other_sea, ratio=M.SEED_RATIO):
        dom, imp, E, out_pre = seed_arrays(other_sea)
        T = np.zeros(dom.shape[1]); iss = []
        seeds, _ = M.seed_one_sided('AAA', dom, imp, T, np.zeros_like(T), E, out_pre.copy(), np.zeros(2), SECTORS, ratio, iss)
        return dom, imp, E, seeds, iss

    def test_small_column_gives_up_at_most_its_cap(self):
        dom, imp, E, seeds, iss = self.run_seed(0.01)
        self.assertEqual(iss, [])
        self.assertTrue((dom >= 0).all() and (imp >= 0).all(), (dom, imp))      # the old rule took 10x the column's other purchases
        self.assertAlmostEqual(dom[0].sum(), M.SEED_RATIO * 1010.0, delta=1e-15)
        self.assertAlmostEqual(seeds[0]['seed'], M.SEED_RATIO * 1010.0, delta=1e-15)
        self.assertTrue(0.0 < dom[0, 1] <= M.SEED_GIVE_UP_MAX * 0.01 + 1e-15)       # sea gives at most half of its 0.01
        self.assertAlmostEqual(dom[0, 2], M.SEED_RATIO * 1010.0 - M.SEED_GIVE_UP_MAX * 0.01, delta=1e-15)   # households take the rest
        self.assertTrue(dom[1, 1] > 0 and imp[1, 1] > 0)                           # and keeps the rest (no new one-sided pair)
        for k in E:
            self.assertTrue((E[k] >= 0).all())

    def test_column_with_nothing_else_takes_no_seed(self):
        dom, imp, E, seeds, iss = self.run_seed(0.0)
        self.assertEqual(iss, [])                                                   # was: "buyer column 1 has no other purchase"
        self.assertEqual(dom[0, 1], 0.0)
        self.assertAlmostEqual(dom[0].sum(), M.SEED_RATIO * 1010.0, delta=1e-15)   # was short by the sea share
        self.assertTrue((dom >= 0).all() and (imp >= 0).all())

    def test_infeasible_seed_is_an_issue(self):
        dom, imp, E, seeds, iss = self.run_seed(0.01, ratio=0.9)                   # 909 cannot come out of 25 of other purchases
        self.assertEqual(len(iss), 1)
        self.assertEqual(seeds, [])

    def test_carved_land_and_natres_are_paid_as_capital(self):
        # fix round S16: the supplier sea uses land and natres; the seeded crp column (neither before the seed) pays them as capital
        dom, imp, E, out_pre = seed_arrays(0.01)
        for k in E:
            E[k][FACTORS.index('land'), 1] = 2.0
            E[k][FACTORS.index('natres'), 1] = 1.0
        used = {f: E['EVFP'][FACTORS.index(f)] > 0 for f in ('land', 'natres')}
        T = np.zeros(dom.shape[1]); iss = []
        M.seed_one_sided('AAA', dom, imp, T, np.zeros_like(T), E, out_pre.copy(), np.zeros(2), SECTORS, M.SEED_RATIO, iss)
        self.assertEqual(iss, [])
        self.assertGreater(E['EVFP'][FACTORS.index('land'), 0], 0.0)              # the carve takes a slice of sea's land
        col0 = {k: E[k][:, 0].copy() for k in E}
        M.seed_fixed_factors(E, used, [0])
        for k in E:
            for f in ('land', 'natres'):
                self.assertEqual(E[k][FACTORS.index(f), 0], 0.0)
            self.assertGreater(E[k][FACTORS.index('land'), 1], 0.0)               # sea keeps its own
            self.assertAlmostEqual(E[k][:, 0].sum(), col0[k].sum(), delta=1e-15)  # column VA unchanged

    def test_seed_shares(self):
        w = np.array([3.0, 1.0])
        self.assertTrue(np.array_equal(M.seed_shares(4e-4, w, 1e-4 * w, np.array([1.0, 1.0])), 1e-4 * w))   # no cap binds: unchanged
        s = M.seed_shares(4.0, w, w, np.array([1.0, 10.0]))
        self.assertTrue(np.allclose(s, [1.0, 3.0]) and abs(s.sum() - 4.0) < 1e-15)
        s = M.seed_shares(4.0, np.array([2.0, 1.0, 1.0]), np.array([2.0, 1.0, 1.0]), np.array([1.0, 2.0, 1.5]))
        self.assertTrue(np.allclose(s, [1.0, 1.5, 1.5], rtol=0, atol=1e-15))
        self.assertIsNone(M.seed_shares(4.0, w, w, np.array([1.0, 2.0])))

    def test_seed_check_and_signs_on_the_case(self):
        """Through assemble_region: the one-sided world with AAA's crp column (a buyer of imported crp, 1.5) left with
        1e-6 of other purchases (its sea moves to households), at a 1 percent seed (0.015 to give up)."""
        w = one_sided_world()
        g = w['io']['AAA']
        g.loc['dom_sea', 'p'] += g.loc['dom_sea', 'crp'] - 1e-6
        g.loc['dom_sea', 'crp'] = 1e-6
        T, acc, moves, seeds, delta, led = assemble_seeded(w, ratio=0.01)
        self.assertEqual(K.signs(T), (0, ''))                       # the old rule took 15000x the column's sea
        self.assertEqual(K.seed_check(T['firms'], T['final'], seeds, 0.01), (0, ''))
        self.assertEqual(K.zero_profit(T['firms'], T['endw'], T['make']), (0, ''))
        self.assertEqual(K.market_clearing(T['firms'], T['final'], T['make'], T['bilateral'], T['vst']), (0, ''))


NAT_T2 = {('AAA', 'crp'): dict(eta=0.5, sigma=0.2), ('BBB', 'crp'): dict(eta=1.4, sigma=0.2)}   # one booked target per cell


class NatresBookedTest(unittest.TestCase):
    """Fix round w17 (S14-Hnatcfg): S14 applies the target S12 booked for each cell (msp under the w13 blend has a
    per-region effective eta), and the check compares cell by cell."""
    def setUp(self):
        self.w = natres_world()
        B, vst, _ = M.rebalance_trade(self.w['B'], self.w['V'], self.w['vst'])
        xr, mr = B.groupby(['src', 'comm'])['VXSB'].sum(), B.groupby(['dst', 'comm'])['VMSB'].sum()
        vr = vst.groupby(['region', 'marg'])['VST'].sum()
        parts = []
        for r in REGS:
            p, _, iss = M.assemble_region(r, self.w['io'][r], self.w['fac'][r], xr.loc[r].to_dict(), vr.loc[r].to_dict(), mr.loc[r].to_dict(), SECTORS,
                                          natres=dict(targets=NAT_T2, floor=NAT_FLOOR))
            self.assertEqual(iss, [])
            parts.append(p)
        self.T = M.frames(parts)
        self.rows = pd.DataFrame([x for p in parts for x in p['natres']])

    def test_each_cell_gets_its_own_target(self):
        self.assertEqual(dict(zip(self.rows['region'], self.rows['eta_target'])), {'AAA': 0.5, 'BBB': 1.4})
        self.assertEqual(K.natres_eta(self.T['endw'], self.T['make'], NAT_T2, NAT_FLOOR), (0, ''))
        c = K.natres_cells(self.T['endw'], self.T['make'], NAT_T2, NAT_FLOOR).set_index('region')
        self.assertAlmostEqual(c.loc['BBB', 'eta'], 1.4, places=9)
        # mutation: one target for the sector (the old natres_final) misses BBB's booked target
        self.assertGreater(K.natres_eta(self.T['endw'], self.T['make'], {'crp': dict(eta=0.5, sigma=0.2)}, NAT_FLOOR)[0], 0)

    def test_unbooked_cell_is_an_issue(self):
        E = {k: np.zeros((len(FACTORS), 1)) for k in ('EVFP', 'EVFB', 'EVOS')}
        for k in E:
            E[k][FACTORS.index('capital'), 0] = 1.0
        iss = []
        M.natres_final('CCC', E, np.array([2.0]), ['crp'], NAT_T2, NAT_FLOOR, iss)
        self.assertEqual(len(iss), 1)

    def booked(self, eta_bbb=1.4, w=0.5, th=0.4):
        cfg = {'crp': dict(eta=2.5, sigma=0.2), 'oil': dict(eta=0.5, sigma=0.2)}
        share = w * 0.2 / (0.5 * th + 0.2) + (1 - w) * 0.2 / (2.5 * th + 0.2)
        eff = 0.2 * (1 / share - 1) / th
        nat12 = pd.DataFrame(dict(region=['AAA', 'BBB'], sector=['crp', 'crp'], eta_target=[2.5, round(eff, 6)], sigma_va=[0.2, 0.2],
                                  theta_va_used=[0.5, th], msp_oil_gas_support_weight=[np.nan, w]))
        applied = nat12[['region', 'sector', 'eta_target', 'sigma_va']].copy()
        return nat12, cfg, applied, dict(sector='crp', fossil='oil')

    def test_check_passes_on_the_booking_and_fails_on_mutations(self):
        nat12, cfg, applied, blend = self.booked()
        self.assertEqual(K.natres_booked(nat12, cfg, applied, blend), (0, ''))
        self.assertGreater(K.natres_booked(nat12, cfg, applied, None)[0], 0)             # blended eta read as the plain 2.5 target
        self.assertGreater(K.natres_booked(nat12, cfg, applied.assign(eta_target=2.5), blend)[0], 0)   # S14 applied the sector target (old code)
        bad = nat12.copy(); bad.loc[1, 'eta_target'] *= 1.01
        self.assertGreater(K.natres_booked(bad, cfg, bad[['region', 'sector', 'eta_target', 'sigma_va']], blend)[0], 0)   # not the blend
        bad = nat12.copy(); bad.loc[0, 'eta_target'] = 2.4
        self.assertGreater(K.natres_booked(bad, cfg, bad[['region', 'sector', 'eta_target', 'sigma_va']], blend)[0], 0)   # not the config
        bad = nat12.copy(); bad['sigma_va'] = 0.3
        self.assertGreater(K.natres_booked(bad, cfg, bad[['region', 'sector', 'eta_target', 'sigma_va']], blend)[0], 0)
        extra = pd.concat([applied, pd.DataFrame([dict(region='CCC', sector='crp', eta_target=2.5, sigma_va=0.2)])], ignore_index=True)
        self.assertGreater(K.natres_booked(nat12, cfg, extra, blend)[0], 0)              # applied a target S12 did not book
        self.assertGreater(K.natres_booked(nat12.drop(columns=['eta_target']), cfg, applied, blend)[0], 0)


class VdepCapitalTest(unittest.TestCase):
    """Fix round w17 (S14-Hsi on GNQ and TLS): the gate names the values and the report names where capital income was set."""
    def test_detail_and_sources(self):
        T, acc, _, _ = assemble(world())
        bop = pd.DataFrame(columns=['net_primary_income_musd', 'net_secondary_income_musd'], dtype=float)
        acc = acc.copy(); acc.loc['AAA', 'VDEP'] = acc.loc['AAA', 'capital_income'] + 1.0
        g = M.si_gate(acc, bop)
        n, det = K.si_gate_hard(g, False)
        self.assertEqual(n, 1)
        self.assertIn('AAA: vdep_below_capital_income (capital income', det)
        fac = pd.concat(world()['fac'].values(), ignore_index=True)
        v = K.vdep_capital_sources(g, fac)
        self.assertEqual(v['region'].tolist(), ['AAA'])
        self.assertAlmostEqual(v['capital_income_s13'].iloc[0], fac[(fac.region == 'AAA') & (fac.factor == 'capital')]['evos'].sum(), places=12)
        self.assertEqual(len(K.vdep_capital_sources(M.si_gate(assemble(world())[1], bop), fac)), 0)


class ProductTaxS13Test(unittest.TestCase):
    """Round-3 QA item 3: S14-Hptaxs13, product taxes by region in the final tables against what S13 held."""
    def test_pass_and_fail(self):
        T, acc, _, _ = assemble(world())
        t = acc[['tax_firms', 'tax_private', 'tax_government', 'tax_investment']].sum(axis=1)
        pse = {r: -1.0 for r in acc.index}
        s13 = pd.DataFrame({'region': list(acc.index), 'fitted_musd': (t + 1.0).to_numpy(), 'prior_musd': (t * 1.1).to_numpy()})
        n, det, df = K.product_tax_s13(acc, pse, s13)
        self.assertEqual(n, 0, det)
        self.assertTrue(np.allclose(df['gap_musd'], 0.0))
        r0 = acc.index[0]
        far = s13.assign(fitted_musd=np.where(s13['region'] == r0, s13['fitted_musd'] + 5.0, s13['fitted_musd']))
        self.assertEqual(K.product_tax_s13(acc, pse, far)[0], 1)
        self.assertEqual(K.product_tax_s13(acc, pse, s13.iloc[1:])[0], 1)              # a region without an S13 row


# ------------------------------------------------------------------ screens
class ScreenTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.T, self.acc, _, _ = assemble(world())
        bop = pd.DataFrame(columns=['net_primary_income_musd', 'net_secondary_income_musd'], dtype=float)
        self.gate = M.si_gate(self.acc, bop)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def ctx(self, T=None, prev=None):
        return dict(R=T or self.T, acc=self.acc, gate=self.gate, regions=REGS, prev=prev)

    def test_clean_run(self):
        r = SCR.run(self.ctx(), log=lambda m: None, report_dir=self.tmp)
        self.assertEqual(r['material_unexplained'], 0)

    def test_identity_screen_fails(self):
        T = {k: v.copy() for k, v in self.T.items()}
        T['bilateral'].loc[0, 'VMSB'] = T['bilateral'].loc[0, 'VCIF'] * 0.5
        r = SCR.run(self.ctx(T), log=lambda m: None, report_dir=self.tmp)
        self.assertGreater(r['material_unexplained'], 0)
        T = {k: v.copy() for k, v in self.T.items()}
        T['endw'] = T['endw'][T['endw']['region'] != 'AAA']
        self.assertGreater(SCR.s5_identities(self.ctx(T))[0].__len__(), 0)

    def test_outlier_coverage_and_moves(self):
        g = self.gate.copy(); g.loc['AAA', 'saving_share_in_bounds'] = False
        self.assertEqual(len([h for h in SCR.s2_outliers(dict(gate=g))[0] if h['item'] == 'saving share']), 1)
        T = {k: v.copy() for k, v in self.T.items()}
        T['bilateral'].loc[0, 'VXSB'] = 5e-5
        self.assertGreater(len(SCR.s6_coverage(self.ctx(T))[0]), 0)
        prev = self.acc.reset_index().copy(); prev['SAVE'] += 500.0
        self.assertGreater(len(SCR.s7_moves(self.ctx(prev=prev))[0]), 0)


if __name__ == '__main__':
    unittest.main()
