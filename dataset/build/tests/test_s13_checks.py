"""Mutation tests for the S13 solver, the S13 method, the S13 hard checks, the S13 screens and the config stop.

A small synthetic economy (seven sectors, one region) goes through the real method: prior, fit and the
io_s13 table. Every check is called on that table (it must pass) and on a mutated copy (it must fail).
Each screen gets a mutation it must report.

Run from dataset/build:  python3 -m unittest tests.test_s13_checks -v
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

from s13_fit import checks as K  # noqa: E402
from s13_fit import config as C  # noqa: E402
from s13_fit import method as M  # noqa: E402
from s13_fit import ptax_source as PS  # noqa: E402
from s13_fit.fit import Column, Problem, solve, information  # noqa: E402
from s13_fit.method import FD, FACTORS  # noqa: E402
import screens.s13_suite as SCR  # noqa: E402

SECTORS = ['crp', 'coa', 'oil', 'gas', 'pet', 'ely', 'trd']
CHOICE = {'farm_support': 'pse_output_and_input_as_fixed_rates_on_crp'}


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


# ------------------------------------------------------------------ solver
class SolverTest(unittest.TestCase):
    def toy(self, x=30.0):
        # two activities and households; rows: market clearing of a, b
        cols = [Column('a', [0, 1, -1], [1, 1, 0], [10, 20, 70], own_row=0, own_coef=-1.0),
                Column('b', [0, 1, -1], [1, 1, 0], [30, 10, 60], own_row=1, own_coef=-1.0),
                Column('p', [0, 1], [1, 1], [60, 70], total=150.0)]
        return Problem(['MC_a', 'MC_b'], [x, 20.0], cols)

    def test_reaches_targets(self):
        P = self.toy()
        R = solve(P)
        self.assertTrue(R['ok'])
        va, vb, vp = R['vals']['a'], R['vals']['b'], R['vals']['p']
        self.assertAlmostEqual(va[0] + vb[0] + vp[0] + 30.0, va.sum(), places=6)    # sales of a = output of a
        self.assertAlmostEqual(va[1] + vb[1] + vp[1] + 20.0, vb.sum(), places=6)
        self.assertAlmostEqual(vp.sum(), 150.0, places=6)

    def test_prior_is_a_fixed_point(self):
        # when the targets are the prior's own totals the fit does not move and I = 0
        cols = [Column('a', [0, -1], [1, 0], [10, 90], own_row=0, own_coef=-1.0),
                Column('p', [0], [1], [80], total=80.0)]
        P = Problem(['MC_a'], [10.0], cols)
        R = solve(P)
        self.assertTrue(R['ok'])
        np.testing.assert_allclose(R['vals']['a'], [10, 90], atol=1e-7)
        self.assertAlmostEqual(information(P, R['vals'], R['tots']), 0.0, places=6)

    def test_free_columns_keep_prior_shares(self):
        # with no priced row (no import or output target), GTAP's domestic shares move only with their column
        P = self.toy()
        R = solve(P)
        for c in P.columns:
            np.testing.assert_allclose(R['vals'][c.name] / R['vals'][c.name].sum(), c.theta0, atol=1e-9)

    def toy_imports(self):
        # rows: market clearing of a and b (free outputs), imports of m (priced, eq. 17.16)
        cols = [Column('a', [0, 1, 2, -1], [1, 1, 1, 0], [10, 20, 5, 65], own_row=0, own_coef=-1.0),
                Column('b', [0, 1, 2, -1], [1, 1, 1, 0], [30, 10, 15, 45], own_row=1, own_coef=-1.0),
                Column('p', [0, 1, 2], [1, 1, 1], [60, 70, 10], total=150.0)]
        return Problem(['MC_a', 'MC_b', 'IM_m'], [30.0, 20.0, -45.0], cols)

    def test_matches_general_optimiser(self):
        # at the solution, the cells minimise I given the column totals, subject only to the priced rows
        from scipy.optimize import minimize
        P = self.toy_imports()
        R = solve(P)
        self.assertTrue(R['ok'])
        self.assertEqual(list(P.priced), [False, False, True])
        I = information(P, R['vals'], R['tots'])
        th = [c.theta0 for c in P.columns]
        Ea, Eb = R['vals']['a'].sum(), R['vals']['b'].sum()

        def obj(z):
            v = [z[0:4], z[4:8], z[8:11]]
            t = 0.0
            for vv, t0 in zip(v, th):
                s = vv.sum()
                t += float(np.sum(vv * np.log(np.maximum(vv, 1e-12) / (s * t0))))
            return t
        cons = [{'type': 'eq', 'fun': lambda z: z[0:4].sum() - Ea},
                {'type': 'eq', 'fun': lambda z: z[4:8].sum() - Eb},
                {'type': 'eq', 'fun': lambda z: z[8:11].sum() - 150.0},
                {'type': 'eq', 'fun': lambda z: z[2] + z[6] + z[10] - 45.0}]
        z0 = np.concatenate([c.prior for c in P.columns])
        res = minimize(obj, z0, constraints=cons, bounds=[(1e-9, None)] * 11, method='SLSQP', options={'ftol': 1e-12, 'maxiter': 500})
        self.assertAlmostEqual(I, res.fun, places=4)
        np.testing.assert_allclose(np.concatenate([R['vals'][c.name] for c in P.columns]), res.x, atol=1e-3)
        # and outputs clear the domestic markets (eq. 17.28)
        va, vb, vp = R['vals']['a'], R['vals']['b'], R['vals']['p']
        self.assertAlmostEqual(va[0] + vb[0] + vp[0] + 30.0, Ea, places=6)
        self.assertAlmostEqual(va[1] + vb[1] + vp[1] + 20.0, Eb, places=6)

    def test_infeasible_is_named(self):
        # exports of a above anything the column can produce with households fixed: no slack, not ok
        cols = [Column('a', [0, -1], [1, 0], [10, 90], own_row=0, own_coef=-1.0),
                Column('p', [0], [1], [80], total=80.0)]
        P = Problem(['MC_a'], [10.0], cols)
        P.columns[1].target = -5.0
        R = solve(P)
        self.assertFalse(R['ok'])
        self.assertTrue(R['worst'])


# ------------------------------------------------------------------ synthetic economy
def synthetic(seed=0):
    rng = np.random.default_rng(seed)
    n = len(SECTORS)
    cols = SECTORS + ['p', 'g', 'i', 'dpabr', 'X', 'stock_gap', 'grev_gap', 'OUT']
    dom = rng.uniform(1, 10, (n, n + 3))
    imp = rng.uniform(0.5, 3, (n, n + 3))
    dom[:, n + 1] = 0.0
    dom[SECTORS.index('trd'), n + 1] = 20.0                      # government buys trade services only
    imp[:, n + 1] = 0.0
    X = rng.uniform(5, 15, n)
    out = dom.sum(axis=1) + X
    tls = 0.05 * (dom.sum(axis=0) + imp.sum(axis=0))
    va = out - dom.sum(axis=0)[:n] - imp.sum(axis=0)[:n] - tls[:n]
    if (va <= 0).any():
        raise RuntimeError('synthetic economy has negative VA')
    rows = []
    for i, c in enumerate(SECTORS):
        rows.append([f'dom_{c}', *dom[i], 0.0, X[i], 0.0, 0.0, out[i]])
    for i, c in enumerate(SECTORS):
        rows.append([f'imp_{c}', *imp[i], 0.0, 0.0, 0.0, 0.0, 0.0])
    rows.append(['TLS', *tls, 0.0, 0.0, 0.0, 0.0, 0.0])
    sh = np.array([0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.3, 0.1])
    for k, f in enumerate(FACTORS):
        rows.append([f'EVFP_{f}', *(va * sh[k]), 0, 0, 0, 0, 0, 0, 0, 0])
    rows.append(['OUT', *out, 0, 0, 0, 0, 0, 0, 0, 0])
    r = pd.DataFrame(rows, columns=['row'] + cols).set_index('row')
    M_ = imp.sum(axis=1) * 1.1
    trade_r = {}
    for i, c in enumerate(SECTORS):
        trade_r[('X', c)] = X[i] * 1.2 if c != 'coa' else 0.0    # coa is shut (S11 output 0): no exports
        trade_r[('M', c)] = M_[i]
        trade_r[('VST', c)] = 2.0 if c == 'trd' else 0.0
    fd = pd.Series(dict(C=dom[:, n].sum() * 1.1 + imp[:, n].sum() + tls[n], G=20.0 * 1.05, I=dom[:, n + 2].sum() + imp[:, n + 2].sum() + tls[n + 2]))
    tout = {('AAA', 'oil'): out[SECTORS.index('oil')] * 1.3, ('AAA', 'coa'): 0.0}
    return r, trade_r, fd, tout


def we(r):
    """world_energy_structure for the one synthetic region."""
    return M.world_energy_structure(r.reset_index().assign(region='AAA'), SECTORS)


def fitted(seed=0, support=None):
    r, trade_r, fd, tout = synthetic(seed)
    rep = {}
    rep_b06 = {('dom', 'oil'): 0.5, ('dom', 'gas'): 0.5, ('imp', 'oil'): 0.5, ('imp', 'gas'): 0.5}
    P, info = M.build_problem('AAA', r, SECTORS, trade_r, fd, tout, rep, rep_b06, support or {'input': 2.0, 'output': 1.0}, we(r), CHOICE)
    R = M.fit_region(P, info, SECTORS)
    evfp12 = r.loc[[f'EVFP_{f}' for f in FACTORS], SECTORS].to_numpy(float)
    world = pd.DataFrame(np.tile(evfp12.sum(axis=1) / evfp12.sum(), (len(SECTORS), 1)), index=SECTORS, columns=list(FACTORS))
    tab, comp = M.region_table('AAA', R, info, SECTORS, trade_r, evfp12, world)
    return dict(r=r, trade_r=trade_r, fd=fd, tout=tout, P=P, info=info, R=R, io=tab, comp=comp, world=world, evfp12=evfp12)


class MethodTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.F = fitted()

    def test_fit_converges(self):
        self.assertTrue(self.F['R']['ok'], self.F['R']['worst'])

    def test_output_tax_row_sets_output_power(self):
        # fix round A3: S12's OTAX row; pi = (OUT - PSE output) / (OUT - OTAX), so the fitted PTAX is the tax less the support
        r, trade_r, fd, tout = synthetic(0)
        r = r.copy()
        r.loc['OTAX'] = 0.0
        out0 = r.loc['OUT', SECTORS].to_numpy(float)
        j, jc = SECTORS.index('ely'), SECTORS.index('crp')
        r.loc['OTAX', 'ely'] = 0.05 * out0[j]
        r.loc['OTAX', 'crp'] = 0.02 * out0[jc]
        rb = {('dom', 'oil'): 0.5, ('dom', 'gas'): 0.5, ('imp', 'oil'): 0.5, ('imp', 'gas'): 0.5}
        P, info = M.build_problem('AAA', r, SECTORS, trade_r, fd, tout, {}, rb, {'input': 0.0, 'output': 1.0}, we(r), CHOICE)
        self.assertAlmostEqual(info['pi'][j], out0[j] / (0.95 * out0[j]), places=12)
        self.assertAlmostEqual(info['pi'][jc], (out0[jc] - 1.0) / (0.98 * out0[jc]), places=12)
        self.assertEqual(info['pi'][SECTORS.index('oil')], 1.0)
        # mutation: without the row the power is the PSE one and no other activity carries a tax
        r2 = r.drop(index='OTAX')
        _, info2 = M.build_problem('AAA', r2, SECTORS, trade_r, fd, tout, {}, rb, {'input': 0.0, 'output': 1.0}, we(r2), CHOICE)
        self.assertEqual(info2['pi'][j], 1.0)
        self.assertAlmostEqual(info2['pi'][jc], 1.0 - 1.0 / out0[jc], places=12)

    def test_energy_smear_is_a_31_32_blend(self):
        # ch.12 §12.4.1 weights: the row keeps its total, 31/32 of each cell stays, 1/32 follows the world structure
        info = self.F['info']
        i = SECTORS.index('oil')
        before, after = info['pv_presmear']['dom'][i], info['pv0']['dom'][i]
        self.assertAlmostEqual(after.sum(), before.sum(), places=9)
        self.assertTrue(np.all(after >= before * (1 - M.SMEAR) - 1e-12))
        self.assertEqual(after[len(SECTORS) + 1], 0.0)        # government: no energy (ch.17A footnote 4)

    def test_zero_target_shuts_row_and_column(self):
        io = self.F['io'].set_index('row')
        self.assertEqual(self.F['info']['status']['coa'], 'zero_target')
        self.assertAlmostEqual(io.loc['OUT', 'coa'], 0.0)
        self.assertAlmostEqual(io.loc['dom_coa', SECTORS + list(FD)].sum(), 0.0)

    def test_all_exported_energy_has_no_domestic_sales(self):
        r, trade_r, fd, tout = synthetic()
        tout[('AAA', 'oil')] = trade_r[('X', 'oil')]
        rb = {('dom', 'oil'): 0.5, ('dom', 'gas'): 0.5, ('imp', 'oil'): 0.5, ('imp', 'gas'): 0.5}
        P, info = M.build_problem('AAA', r, SECTORS, trade_r, fd, tout, {}, rb, {}, we(r), CHOICE)
        self.assertEqual(info['pv0']['dom'][SECTORS.index('oil')].sum(), 0.0)
        self.assertIn('target_all_exported_no_domestic_sales', [n[4] for n in info['notes']])
        R = M.fit_region(P, info, SECTORS)
        self.assertTrue(R['ok'], R['worst'])

    def test_prior_without_va_takes_representative_column(self):
        # a column with negative VA takes the S03 representative column (David's S14 card), with no io_s12
        # product tax and no farm support on it (QA S14 B1); keep_prior_column holds the negative VA instead
        r, trade_r, fd, tout = synthetic()
        r = r.copy()
        j = SECTORS.index('trd')
        for f in FACTORS:
            r.loc[f'EVFP_{f}', 'trd'] = -abs(r.loc[f'EVFP_{f}', 'trd'])
        rb = {('dom', 'oil'): 0.5, ('dom', 'gas'): 0.5, ('imp', 'oil'): 0.5, ('imp', 'gas'): 0.5}
        rep = {'trd': {'domestic trd': 0.2, 'imported crp': 0.1, 'va': 0.7}}
        P, info = M.build_problem('AAA', r, SECTORS, trade_r, fd, tout, rep, rb, {}, we(r),
                                  dict(CHOICE, prior_without_va='representative_column_when_needed'))
        self.assertEqual(info['status']['trd'], 'representative')
        self.assertEqual(info['fixed_va'][j], 0.0)
        self.assertEqual(info['tau'][j], 1.0)
        self.assertEqual(info['tau_tls'][j], 1.0)
        flags = [n[5] for n in info['notes'] if n[1] == 'trd']
        self.assertIn('NEG-VA-REP-COLUMN', flags)
        self.assertIn('REP-COLUMN-TLS-DROPPED', flags)
        self.assertNotIn('NEG-VA-HELD', flags)
        R = M.fit_region(P, info, SECTORS)
        self.assertTrue(R['ok'], R['worst'])
        self.assertGreater(R['va'][j], 0.0)
        P, info = M.build_problem('AAA', r, SECTORS, trade_r, fd, tout, rep, rb, {}, we(r),
                                  dict(CHOICE, prior_without_va='keep_prior_column'))
        self.assertEqual(info['status']['trd'], 'prior')
        self.assertLess(info['fixed_va'][j], 0.0)

    def test_energy_travel_capped_at_domestic_room(self):
        tr = pd.DataFrame([('AAA', 'BBB', 'B06', 10.0), ('AAA', 'CCC', 'B06', 10.0), ('AAA', 'BBB', 'crp', 3.0)],
                          columns=['host', 'visitor', 'commodity', 'musd'])
        en_x = pd.DataFrame([('AAA', 'BBB', 'oil', 95.0, 95.0)], columns=['exporter', 'importer', 'sector', 'vxsb_musd', 'vfob_musd'])
        empty_x = pd.DataFrame(columns=['exporter', 'importer', 'sector', 'vxsb_musd', 'vfob_musd'])
        empty_m = pd.DataFrame(columns=['exporter', 'importer', 'sector', 'vcif_musd', 'vmsb_musd'])
        svc = pd.DataFrame(columns=['exporter', 'importer', 'sector', 'vxsb_musd'])
        vst = pd.DataFrame(columns=['region', 'margin', 'vst_musd_s11'])
        t, used, dropped = M.assemble_trade(empty_x, empty_m, en_x, empty_m, svc, tr, vst, pd.Series({'AAA': 1.0}),
                                            {('AAA', 'oil'): 100.0, ('AAA', 'gas'): 0.0})
        t = t.set_index(['region', 'sector'])
        self.assertAlmostEqual(t.loc[('AAA', 'oil'), 'X'], 100.0)          # 95 S11 exports + 5 of the 20 travel
        self.assertAlmostEqual(dropped['v'].sum(), 15.0)
        self.assertAlmostEqual(t.loc[('BBB', 'oil'), 'M'] + t.loc[('CCC', 'oil'), 'M'], 5.0)
        self.assertAlmostEqual(t.loc[('AAA', 'crp'), 'X'], 3.0)             # non-energy travel untouched

    def test_macro_factor(self):
        macro = pd.DataFrame([dict(region='AAA', GDP_musd=100.0, C_musd=60.0, G_musd=20.0, GFCF_musd=20.0)])
        trade = pd.DataFrame([dict(region='AAA', sector='crp', XFOB=30.0, VST=0.0, MCIF=40.0)])
        m = M.macro_targets(macro, trade).set_index('region')
        self.assertAlmostEqual(m.loc['AAA', 'factor'], 1.1)
        self.assertAlmostEqual(m.loc['AAA', 'C'] + m.loc['AAA', 'G'] + m.loc['AAA', 'I'] + 30.0 - 40.0, 100.0)

    def test_place_column_taxes(self):
        # A1 (GTAP 12 ch.17A items 4-5): energy rows at their ad valorem rate on top of the column's general rate, the
        # general rate the IO rate of the other purchases (TLS less the excise), floored at min(IO rate, 0); rates held
        n = len(SECTORS)
        cols = SECTORS + list(FD)
        b = {'dom': np.ones((n, len(cols))) * 10.0, 'imp': np.ones((n, len(cols))) * 5.0}
        tls = np.full(len(cols), 7.0)
        tls[cols.index('trd')] = -14.0                                             # a net-subsidised column
        jp, ipet, jt = cols.index('p'), SECTORS.index('pet'), cols.index('trd')
        energy = {('pet', 'p'): 0.2, ('ely', 'crp'): 1.0, ('pet', 'trd'): 0.5}
        bt = b['dom'] + b['imp']
        B = bt.sum(axis=0)
        rate, placed = M.place_column_taxes(b, tls, cols, SECTORS, energy)        # default rule: held
        self.assertAlmostEqual(rate[ipet, jp] - rate[SECTORS.index('trd'), jp], 0.2)
        self.assertAlmostEqual(rate[SECTORS.index('trd'), jp], (7.0 - 0.2 * 15.0) / B[jp])   # TLS less the excise over all purchases
        self.assertAlmostEqual((bt[:, jp] * rate[:, jp]).sum(), 7.0)               # an ordinary column keeps its TLS at the prior
        self.assertAlmostEqual(rate[SECTORS.index('ely'), 0], 1.0)                 # held: the excise 15 above TLS 7 is not scaled
        self.assertAlmostEqual(rate[SECTORS.index('trd'), 0], 0.0)                 # the general rate is not negative (IO rate > 0)
        self.assertAlmostEqual((bt[:, 0] * rate[:, 0]).sum(), 15.0)                # the column total moves to the excise
        self.assertAlmostEqual(rate[SECTORS.index('crp'), jt], -14.0 / B[jt])      # a net-subsidised column keeps its IO rate
        self.assertAlmostEqual((bt[:, jt] * rate[:, jt]).sum(), -14.0 + 0.5 * 15.0)
        self.assertEqual([c for c, _g, _l in placed['floored']], ['crp', 'trd'])
        self.assertEqual({c for c, _a, _b in placed['moved']}, {'crp', 'trd'})
        self.assertEqual(placed['capped'], [])
        # the pre-w12 cap (alternative): every column keeps its TLS, the energy part is scaled
        rc, pc = M.place_column_taxes(b, tls, cols, SECTORS, energy, 'cap')
        np.testing.assert_allclose((bt * rc).sum(axis=0), tls)
        self.assertEqual([c for c, _k in pc['capped']], ['crp', 'trd'])
        self.assertAlmostEqual(rc[SECTORS.index('ely'), 0] * 15.0 - rc[SECTORS.index('trd'), 0] * 15.0, 7.0)
        # the IO column rate on every row (alternative): totals rise by the whole excise
        ri, _pi = M.place_column_taxes(b, tls, cols, SECTORS, energy, 'io_rate')
        np.testing.assert_allclose((bt * ri).sum(axis=0), tls + np.array([15.0 if c == 'crp' else 3.0 if c == 'p' else 7.5 if c == 'trd' else 0.0 for c in cols]))
        # mutation: the held rule is not the cap (the old default would scale the crp excise down)
        self.assertNotAlmostEqual(rate[SECTORS.index('ely'), 0], rc[SECTORS.index('ely'), 0])
        for rule in ('held', 'cap', 'io_rate'):
            np.testing.assert_allclose(M.place_column_taxes(b, tls, cols, SECTORS, {}, rule)[0], np.tile(tls / B, (n, 1)))
        with self.assertRaises(ValueError):
            M.place_column_taxes(b, tls, cols, SECTORS, energy, 'smear')
        self.assertEqual(M.TAX_RATE_RULE[C.CHOICES['tax_rates'][0]], 'held')
        self.assertEqual(set(M.TAX_RATE_RULE), set(C.CHOICES['tax_rates']) - {'one_net_product_tax_power_per_column_dom_and_imp_held'})
        te = pd.DataFrame([('AAA', 'B06', 'pet', 0.5, 0.3), ('AAA', 'p', 'gas', 0.2, 0.1), ('AAA', 'p', '_rest', 0.1, 0.0), ('AAA', 'gas', 'ely', 0.0, 0.4)],
                          columns=['region', 'column', 'commodity', 'rate', 'energy_rate'])
        self.assertEqual(M.energy_rates_of(te, 'AAA', cols), {('pet', 'oil'): 0.3, ('pet', 'gas'): 0.3, ('gas', 'p'): 0.1, ('ely', 'gas'): 0.4})

    def test_non_energy_pattern(self):
        """QA round 2 P1 (non_energy_rates): the general part of each column goes on its commodities by the S10 VAT and
        excise layers, the column total and the energy rates unchanged; exempt services carry no VAT; the Eurostat
        control RASes the non-energy rows with the columns held."""
        sec = ['crp', 'fbt', 'pet', 'fin', 'rle', 'trd']
        cols = sec + list(FD)
        n, J = len(sec), len(cols)
        w = {'crp': 0.07, 'fbt': 0.19, 'pet': 0.19, 'fin': 0.0, 'rle': 0.0, 'trd': 0.19}
        pat = [dict(region='AAA', agent=a, commodity=c, vat_weight=(1.0 if w[c] > 0 else 0.0) if a == 'firm' else w[c])
               for a in ('p', 'g', 'i', 'firm_exempt', 'firm') for c in sec]
        lay = pd.DataFrame([dict(region='AAA', vat_musd=30.0, excise_musd=12.0)])
        ctl = pd.DataFrame(columns=['region', 'group', 'commodities', 'share'])
        L = M.product_tax_layers(pd.DataFrame(pat), lay, ctl, sec)['AAA']
        self.assertTrue(L['levelled'][sec.index('fin')] and not L['levelled'][sec.index('trd')])   # fin exempt: it pays VAT on inputs
        rng = np.random.default_rng(3)
        b = {'dom': rng.uniform(1.0, 20.0, (n, J)), 'imp': rng.uniform(0.0, 5.0, (n, J))}
        bt = b['dom'] + b['imp']
        tls = np.full(J, 25.0)
        tls[cols.index('crp')] = -3.0                                             # net-subsidised column: one rate stays
        energy = {('pet', 'p'): 0.4}
        r0, p0 = M.place_column_taxes(b, tls, cols, sec, energy)
        r1, p1 = M.place_column_taxes(b, tls, cols, sec, energy, layers=L)
        np.testing.assert_allclose((bt * r1).sum(axis=0), (bt * r0).sum(axis=0))      # every column total unchanged
        jp, jc, jt = cols.index('p'), cols.index('crp'), cols.index('trd')
        for c in ('fin', 'rle'):
            self.assertAlmostEqual(r1[sec.index(c), jp], 0.0)                         # exempt for households
            self.assertAlmostEqual(r1[sec.index(c), jt], 0.0)                         # and for VAT-registered firms
        self.assertGreater(r1[sec.index('fbt'), jp], r1[sec.index('trd'), jp])       # excise on households' fbt
        self.assertGreater(r1[sec.index('trd'), jp], r1[sec.index('crp'), jp])       # standard over reduced rate
        # the energy wedge over the VAT part is the energy rate (VAT falls on energy like a standard good)
        self.assertAlmostEqual(r1[sec.index('pet'), jp] - r1[sec.index('trd'), jp], 0.4)
        np.testing.assert_allclose(r1[:, jc], r0[:, jc])                              # g <= 0: one general rate
        self.assertEqual(p1['pattern']['columns'], J - 1)
        # cap: government pays at most households' VAT on a good; the rest of its tax at one rate on all purchases
        jg = cols.index('g')
        self.assertIn('g', p1['pattern']['capped_columns'].split())
        u = r1[sec.index('fin'), jg]
        self.assertGreater(u, 0.0)
        self.assertAlmostEqual(r1[sec.index('trd'), jg] - u, r1[sec.index('trd'), jp], places=12)
        # with a control: the non-energy rows meet the shares, columns held (households large enough that no cap binds)
        tls[jp] = 400.0
        ctl = pd.DataFrame([dict(region='AAA', group=g, commodities=g, share=s)
                            for g, s in (('crp', 0.1), ('fbt', 0.5), ('fin', 0.0), ('rle', 0.0), ('trd', 0.4))])
        L2 = M.product_tax_layers(pd.DataFrame(pat), lay, ctl, sec)['AAA']
        r0, p0 = M.place_column_taxes(b, tls, cols, sec, energy)
        r2, p2 = M.place_column_taxes(b, tls, cols, sec, energy, layers=L2)
        self.assertEqual(p2['pattern']['capped_columns'], '')
        np.testing.assert_allclose((bt * r2).sum(axis=0), (bt * r0).sum(axis=0))
        on = np.array([c != 'crp' for c in cols])
        T = (bt * r2)[:, on] - (bt * np.array([[0.4 if (c == 'pet' and k == 'p') else 0.0 for k in cols] for c in sec]))[:, on]
        ne = [sec.index(c) for c in ('crp', 'fbt', 'trd')]
        sh = T[ne, :].sum(axis=1) / T[ne + [sec.index('fin'), sec.index('rle')], :].sum()
        np.testing.assert_allclose(sh, [0.1, 0.5, 0.4], atol=1e-8)
        self.assertLess(p2['pattern']['ras_gap'], 1e-9)
        # mutation: without layers every non-energy row has one rate
        self.assertAlmostEqual(r0[sec.index('fin'), jp], r0[sec.index('fbt'), jp])

    def test_energy_ad_valorem(self):
        """A1 (GTAP 12 ch.12 §12.4.4): specific rate per GJ over the S11 basic price per GJ; the electricity excise
        per GJ of S11 domestic use; USA barrels at the S11 factor; proxies' specific rates at the region's own price;
        a rate at or below -100% treated as unknown (zero)."""
        cols = SECTORS + list(FD)
        rows = []
        for reg in ('AAA', 'BBB', 'CCC'):
            for kind in ('dom', 'imp'):
                for c in SECTORS:
                    rows.append(dict(region=reg, row=f'{kind}_{c}', **{k: (4.0 if kind == 'dom' else 1.0) for k in cols}))
        io = pd.DataFrame(rows)
        ev = pd.DataFrame([dict(region=r, commodity=c, domestic_price=p, mtoe_per_unit=f, absorption=a)
                           for r, pp in (('AAA', 1.0), ('BBB', 2.0), ('CCC', 0.5)) for c, p, f, a in
                           (('pet', 100.0 * pp, 0.1, 50.0), ('gas', 300.0 * pp, 0.86, 10.0), ('ely', 100.0 * pp, 0.086, 200.0), ('coa', 60.0 * pp, 0.6, 1.0))])
        F = ['region', 'class', 'commodity', 'columns', 'tax_musd', 'subsidy_musd', 'base', 'base_unit', 'source', 'fill', 'proxies']
        spec = pd.DataFrame([
            ['AAA', 'ROAD', 'pet', 'p;trd', 12.0, -2.0, 1000.0, 'TJ', 'NEERS', '', ''],
            ['AAA', 'RESCOM', 'pet', 'p', 1.0, 0.0, 1000.0, 'TJ', 'NEERS', '', ''],
            ['AAA', 'INDUSTRY', 'gas', 'B06;pet', 3.0, 0.0, 600.0, 'TJ', 'NEERS', '', ''],
            ['AAA', 'ALL', 'ely', 'ALL', 7.2, 0.0, 0.0, 'electricity_s11', 'NEERS', '', ''],
            ['AAA', 'ELEC', 'coa', 'ely', -50.0, -50.0, 10.0, 'TJ', 'NEERS', '', ''],
            ['BBB', 'ROAD', 'pet', 'p;trd', 20.0, 0.0, 2.0, 'million_bbl', 'EIA', '', ''],
            ['CCC', '*', '*', '', 0.0, 0.0, 0.0, '', 'fill', 'pool', 'AAA:3;BBB:1'],
        ], columns=F)
        te, notes = M.energy_ad_valorem(spec, ev, io, SECTORS)
        R = {(x.region, x.column, x.commodity): x for x in te.itertuples()}
        gj = 41.868
        p_pet = 100.0 / 0.1 / gj                                                      # USD per GJ of petroleum products in AAA
        self.assertAlmostEqual(R[('AAA', 'trd', 'pet')].energy_rate, 10.0 / p_pet)   # ROAD only: 10 USD m / 1000 TJ = 10 USD/GJ
        self.assertAlmostEqual(R[('AAA', 'p', 'pet')].energy_rate, 11.0 / 2.0 / p_pet)   # ROAD + RESCOM by tax base (§12.3.9)
        self.assertAlmostEqual(R[('AAA', 'trd', 'pet')].neer_subsidy_rate, -2.0 / p_pet)
        self.assertAlmostEqual(R[('AAA', 'p', 'pet')].basic_musd, 5.0)
        self.assertAlmostEqual(R[('AAA', 'oil', 'gas')].energy_rate, 5.0 / (300.0 / 0.86 / gj))   # io_s12 oil and gas take the B06 class
        self.assertIn(('AAA', 'gas', 'gas'), R)
        self.assertNotIn(('AAA', 'p', 'gas'), R)
        ely_gj = 200.0 * 0.086 * gj * 1e6                                             # S11 domestic use of electricity in GJ
        self.assertAlmostEqual(R[('AAA', 'crp', 'ely')].energy_rate, 7.2e6 / ely_gj / (100.0 / 0.086 / gj))
        self.assertAlmostEqual(R[('AAA', 'i', 'ely')].energy_rate, R[('AAA', 'p', 'ely')].energy_rate)   # every buyer
        self.assertNotIn(('AAA', 'ely', 'ely'), R)                                   # but not the power sector's own purchases
        self.assertAlmostEqual(R[('AAA', 'ely', 'coa')].energy_rate, 0.0)             # -10000 USD/GJ: no positive purchasers' price
        self.assertTrue(any('AAA coa ely' in x for x in notes))
        bbl = 20.0e6 / (2.0 * 0.1 * gj * 1e6)                                         # USA-style: USD per GJ from barrels at the S11 factor
        self.assertAlmostEqual(R[('BBB', 'p', 'pet')].specific_usd_per_gj, bbl)
        self.assertAlmostEqual(R[('BBB', 'p', 'pet')].energy_rate, 20.0 / 2.0 / (2 * 100.0))   # = USD per bbl over the price per bbl
        # the fill copies the proxies' specific rates (trade weighted, member by member) and uses its own price
        self.assertAlmostEqual(R[('CCC', 'trd', 'pet')].specific_usd_per_gj, (3 * 10.0 + 1 * bbl) / 4)
        self.assertAlmostEqual(R[('CCC', 'trd', 'pet')].energy_rate, (3 * 10.0 + 1 * bbl) / 4 / (0.5 * p_pet))
        self.assertAlmostEqual(R[('CCC', 'p', 'gas')].energy_rate if ('CCC', 'p', 'gas') in R else 0.0, 0.0)
        self.assertAlmostEqual(R[('CCC', 'pet', 'gas')].specific_usd_per_gj, 5.0)      # AAA only taxes that cell
        self.assertEqual(R[('CCC', 'trd', 'pet')].source, 'fill')
        rv = K.energy_revenue_compare(te, spec).set_index(['region', 'commodity'])
        self.assertAlmostEqual(rv.loc[('AAA', 'pet'), 'source_musd'], 11.0)
        self.assertAlmostEqual(rv.loc[('AAA', 'pet'), 'implied_musd'], float((te.energy_rate * te.basic_musd)[(te.region == 'AAA') & (te.commodity == 'pet')].sum()))
        self.assertNotIn('CCC', rv.index.get_level_values(0))                        # a fill region has no source revenue
        # mutations: a missing S11 price leaves the cell untaxed and is noted; the ICIO-base rule is gone
        te2, notes2 = M.energy_ad_valorem(spec, ev[~((ev.region == 'AAA') & (ev.commodity == 'pet'))], io, SECTORS)
        self.assertNotIn(('AAA', 'p', 'pet'), {(x.region, x.column, x.commodity) for x in te2.itertuples()})
        self.assertTrue(any('no S11 basic price' in x for x in notes2))
        ev3 = ev.copy()
        ev3.loc[(ev3.region == 'AAA') & (ev3.commodity == 'pet'), 'domestic_price'] *= 2.0
        te3, _n = M.energy_ad_valorem(spec, ev3, io, SECTORS)
        self.assertAlmostEqual(te3.set_index(['region', 'column', 'commodity']).loc[('AAA', 'trd', 'pet'), 'energy_rate'],
                               R[('AAA', 'trd', 'pet')].energy_rate / 2.0)        # the rate moves with GTAP's own price

    def test_build_problem_routes_tax_rule(self):
        """The s13 choice tax_rates reaches place_column_taxes: held by default, the cap only when chosen."""
        r, trade_r, fd, tout = synthetic()
        rb = {('dom', 'oil'): 0.5, ('dom', 'gas'): 0.5, ('imp', 'oil'): 0.5, ('imp', 'gas'): 0.5}
        energy = {('pet', 'p'): 50.0}
        _P, held = M.build_problem('AAA', r, SECTORS, trade_r, fd, tout, {}, rb, {}, we(r), CHOICE, energy=energy)
        cap = dict(CHOICE, tax_rates='energy_rows_at_ad_valorem_rates_capped_at_column_tls_column_total_fixed')
        _P, capped = M.build_problem('AAA', r, SECTORS, trade_r, fd, tout, {}, rb, {}, we(r), cap, energy=energy)
        jp, ipet, itrd = (SECTORS + list(FD)).index('p'), SECTORS.index('pet'), SECTORS.index('trd')
        self.assertAlmostEqual(held['tau_cell'][ipet, jp] - held['tau_cell'][itrd, jp], 50.0)
        self.assertLess(capped['tau_cell'][ipet, jp] - capped['tau_cell'][itrd, jp], 50.0)
        self.assertEqual(held['placed']['capped'], [])
        self.assertEqual([c for c, _k in capped['placed']['capped']], ['p'])

    def test_extreme_rates_report(self):
        n = len(SECTORS)
        cols = SECTORS + list(FD)
        tau = np.ones((n, len(cols)))
        tau[SECTORS.index('pet'), cols.index('p')] = 2.5
        tau[SECTORS.index('ely'), cols.index('crp')] = 0.3
        tau[SECTORS.index('coa'), cols.index('crp')] = 0.9
        bp = {'dom': np.ones((n, len(cols))), 'imp': np.zeros((n, len(cols)))}
        bf = np.ones((n, len(cols))) * 50.0
        bf[SECTORS.index('ely'), cols.index('crp')] = 0.2
        out = K.extreme_rates('AAA', tau, bp, bf, SECTORS, cols)
        got = {(r[1], r[2]): r for r in out}
        self.assertEqual(set(got), {('pet', 'p'), ('ely', 'crp')})                 # -10% is not extreme
        self.assertTrue(got[('ely', 'crp')][-1])                                   # a small fitted flow
        self.assertFalse(got[('pet', 'p')][-1])
        self.assertAlmostEqual(got[('pet', 'p')][6], 1.5 * 50.0)

    def test_fit_holds_cell_rates(self):
        r, trade_r, fd, tout = synthetic()
        rb = {('dom', 'oil'): 0.5, ('dom', 'gas'): 0.5, ('imp', 'oil'): 0.5, ('imp', 'gas'): 0.5}
        energy = {('pet', 'p'): 0.3, ('ely', 'p'): 0.05, ('pet', 'trd'): 0.02}
        P, info = M.build_problem('AAA', r, SECTORS, trade_r, fd, tout, {}, rb, {'input': 2.0, 'output': 1.0}, we(r), CHOICE, energy=energy)
        R = M.fit_region(P, info, SECTORS)
        self.assertTrue(R['ok'], R['worst'])
        evfp12 = r.loc[[f'EVFP_{f}' for f in FACTORS], SECTORS].to_numpy(float)
        world = pd.DataFrame(np.tile(evfp12.sum(axis=1) / evfp12.sum(), (len(SECTORS), 1)), index=SECTORS, columns=list(FACTORS))
        tab, _comp = M.region_table('AAA', R, info, SECTORS, trade_r, evfp12, world)
        cols = SECTORS + list(FD)
        jp, ipet = cols.index('p'), SECTORS.index('pet')
        self.assertAlmostEqual(info['tau_cell'][ipet, jp] - info['tau_cell'][SECTORS.index('trd'), jp], 0.3)
        rates = pd.DataFrame([dict(region='AAA', column=c, tls_rate=info['tau_tls'][j] - 1, pse_rate=info['tau'][j] - info['tau_tls'][j],
                                   output_tax_rate=info['pi'][j] - 1 if j < len(SECTORS) else 0.0) for j, c in enumerate(cols)])
        cells = pd.DataFrame([('AAA', c, s, info['tau_tls_cell'][i, j] - 1, info['tau_cell'][i, j] - info['tau_tls_cell'][i, j])
                              for j, c in enumerate(cols) for i, s in enumerate(SECTORS)],
                             columns=['region', 'column', 'commodity', 'tls_rate', 'pse_rate'])
        self.assertEqual(K.tax_rates(tab, SECTORS, rates, cells)[0], 0, K.tax_rates(tab, SECTORS, rates, cells)[1])
        io = tab.copy()
        k = io.index[io['row'] == 'TLS'][0]
        io.at[k, 'p'] += 1.0
        self.assertGreater(K.tax_rates(io, SECTORS, rates, cells)[0], 0)          # TLS off the cell rates
        flat = cells.assign(tls_rate=cells.groupby('column')['tls_rate'].transform('mean'))
        self.assertGreater(K.tax_rates(tab, SECTORS, rates, flat)[0], 0)          # one rate per column no longer holds

    def test_factor_table_scales_taxes(self):
        io = self.F['io']
        fac12 = []
        for k, f in enumerate(FACTORS):
            for j, c in enumerate(SECTORS):
                e = self.F['evfp12'][k, j]
                fac12.append(dict(region='AAA', sector=c, factor=f, evfp=e, ftax=0.1 * e, evfb=0.9 * e, itax=0.09 * e, fbep=0.0, evos=0.81 * e))
        f13 = M.factor_table(io, pd.DataFrame(fac12), SECTORS)
        np.testing.assert_allclose(f13['ftax'], 0.1 * f13['evfp'], atol=1e-9)
        np.testing.assert_allclose(f13['evos'], f13['evfb'] - f13['itax'], atol=1e-9)

    def test_negative_surplus(self):
        # fix round wG: the own-use refit guard lists factor cells whose EVOS goes negative under money-held taxes
        r, trade_r, fd, tout = synthetic()
        rb = {('dom', 'oil'): 0.5, ('dom', 'gas'): 0.5, ('imp', 'oil'): 0.5, ('imp', 'gas'): 0.5}
        P, info = M.build_problem('AAA', r, SECTORS, trade_r, fd, tout, {}, rb, {}, we(r), CHOICE)
        R = M.fit_region(P, info, SECTORS)
        evfp12 = r.loc[[f'EVFP_{f}' for f in FACTORS], SECTORS].to_numpy(float)
        world = pd.DataFrame(np.tile(evfp12.sum(axis=1) / evfp12.sum(), (len(SECTORS), 1)), index=SECTORS, columns=list(FACTORS))
        fac12 = pd.DataFrame([dict(region='AAA', sector=c, factor=f, evfp=evfp12[k, j], ftax=0.0, evfb=evfp12[k, j],
                                   itax=0.5 * evfp12[k, j], fbep=0.0, evos=0.5 * evfp12[k, j])
                              for k, f in enumerate(FACTORS) for j, c in enumerate(SECTORS)])
        self.assertEqual(M.negative_surplus('AAA', R, info, SECTORS, trade_r, evfp12, world, fac12, True), [])
        big = fac12.assign(itax=lambda d: np.where(d['evfp'] > 0, 1e9, 0.0))       # taxes no fitted payment can carry
        # held money above every cell's payment is capped at EVFP (cap_held_factor_taxes): no negative surplus
        self.assertEqual(M.negative_surplus('AAA', R, info, SECTORS, trade_r, evfp12, world, big, True), [])

    def test_cap_held_factor_taxes(self):
        # one shrunken cell's held tax above its payment moves to the other cell of the region and factor
        m = pd.DataFrame(dict(region=['AAA', 'AAA'], sector=['crp', 'mfr'], factor=['land', 'land'], evfp=[1.0, 10.0],
                              ftax=[0.0, 0.0], itax=[3.0, 1.0], fbep=[0.0, 0.0]))
        reg = m.groupby(['region', 'factor'])[['ftax', 'itax', 'fbep']].sum()
        out = M.cap_held_factor_taxes(m, reg)
        self.assertLessEqual(out['itax'].iloc[0], 0.99 + 1e-12)
        self.assertAlmostEqual(out['itax'].sum(), 4.0, places=9)
        self.assertTrue(((out['evfp'] - out['ftax'] - out['itax']) >= -1e-12).all())
        # fix round S16: with a ceiling the shrunken cell carries at most half its payment; the rest goes to mfr
        out = M.cap_held_factor_taxes(m, reg, ceiling=np.maximum(M.HELD_RATE_MAX, [0.1, 0.1]))
        self.assertLessEqual(out['itax'].iloc[0], 0.5 + 1e-12)
        self.assertAlmostEqual(out['itax'].sum(), 4.0, places=9)


# ------------------------------------------------------------------ checks
class SmearStructureTest(unittest.TestCase):
    """ch.12 §12.4.1: the 1/32 smear follows the I-O structure. For crude that is the B06 row (oil + gas rows), not
    S11's energy-data oil rows (fix-round A8: crude to refining only), which left GNQ's held crude no buyer."""

    @staticmethod
    def crude_to_refining(r):
        """The synthetic region with S11's A8 shape: the oil rows go to pet (and imported crude to the oil industry)
        only, the rest of the B06 row is gas; every oil + gas cell (the B06 row) is unchanged."""
        r = r.copy()
        cols = SECTORS + ['p', 'g', 'i']
        for k in ('dom', 'imp'):
            keep = ['pet'] + (['oil'] if k == 'imp' else [])
            for c in cols:
                if c not in keep:
                    r.loc[f'{k}_gas', c] += r.loc[f'{k}_oil', c]
                    r.loc[f'{k}_oil', c] = 0.0
        return r

    def test_crude_follows_the_b06_row(self):
        r0, _, _, _ = synthetic(0)
        r = self.crude_to_refining(r0)
        w = we(r)
        cols = SECTORS + ['p', 'g', 'i']
        ix = {c: j for j, c in enumerate(cols)}
        b06 = sum(r.loc[f'{k}_{c}', cols].to_numpy(float) for k in ('dom', 'imp') for c in ('oil', 'gas'))
        own = b06[ix['oil']] + b06[ix['gas']]
        v = b06.copy()
        v[ix['oil']], v[ix['gas']] = own, 0.0
        self.assertTrue(np.allclose(w['oil'], v / v.sum(), atol=1e-15))
        self.assertGreater(w['oil'][ix['ely']], 0.0)          # crude reaches every B06 buyer, not only the refinery
        # coa, gas and pet keep their own rows
        for good in ('coa', 'gas', 'pet'):
            v = sum(r.loc[f'{k}_{good}', cols].to_numpy(float) for k in ('dom', 'imp'))
            self.assertTrue(np.allclose(w[good], v / v.sum(), atol=1e-15), good)
        # the crude structure does not depend on S11's split of the B06 row
        self.assertTrue(np.allclose(we(r0)['oil'], w['oil']))

    def test_crude_beyond_the_refinery_is_placed(self):
        # held crude sales three times the refinery's whole column: with the smear on S11's own oil rows only the
        # refinery can buy crude and the fit cannot reach the target; on the B06 row it fits
        r0, trade_r, fd, tout = synthetic(0)
        r = self.crude_to_refining(r0)
        io_, ip = SECTORS.index('oil'), SECTORS.index('pet')
        pet_col = float(r.loc[[f'{k}_{c}' for k in ('dom', 'imp') for c in SECTORS] + ['TLS'], 'pet'].sum()
                        + r.loc[[f'EVFP_{f}' for f in FACTORS], 'pet'].sum())
        tout = dict(tout)
        tout[('AAA', 'oil')] = trade_r[('X', 'oil')] + 3.0 * pet_col
        rb = {('dom', 'oil'): 0.5, ('dom', 'gas'): 0.5, ('imp', 'oil'): 0.5, ('imp', 'gas'): 0.5}
        P, info = M.build_problem('AAA', r, SECTORS, trade_r, fd, tout, {}, rb, {'input': 0.0, 'output': 0.0}, we(r), CHOICE)
        self.assertGreater(int((info['pv0']['dom'][io_] > 0).sum()), 2)
        R = M.fit_region(P, info, SECTORS)
        self.assertTrue(R['ok'], R['worst'])
        self.assertAlmostEqual(R['out'][io_], tout[('AAA', 'oil')], delta=1e-6 * tout[('AAA', 'oil')])
        self.assertLess(R['dom'][io_, ip], pet_col)
        # mutation: the energy-data structure (S11's oil rows, the pre-fix world_energy_structure) leaves only the refinery
        cols = SECTORS + ['p', 'g', 'i']
        old = {c: v for c, v in we(r).items()}
        v = sum(r.loc[f'{k}_oil', cols].to_numpy(float) for k in ('dom', 'imp'))
        old['oil'] = v / v.sum()
        P2, info2 = M.build_problem('AAA', r, SECTORS, trade_r, fd, tout, {}, rb, {'input': 0.0, 'output': 0.0}, old, CHOICE)
        self.assertFalse(M.fit_region(P2, info2, SECTORS)['ok'])


class ChecksTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        F = fitted()
        cls.F = F
        cls.io = F['io']
        tr = [dict(region='AAA', sector=c, X=F['trade_r'][('X', c)], XFOB=F['trade_r'][('X', c)], VST=F['trade_r'][('VST', c)],
                   M=F['trade_r'][('M', c)], MCIF=F['trade_r'][('M', c)]) for c in SECTORS]
        cls.trade = pd.DataFrame(tr)
        fd = F['fd']
        cls.mt = pd.DataFrame([dict(region='AAA', C=fd['C'], G=fd['G'], I=fd['I'], factor=1.0)]).set_index('region')
        t = cls.trade
        cls.gdp = {'AAA': fd['C'] + fd['G'] + fd['I'] + t['XFOB'].sum() + t['VST'].sum() - t['MCIF'].sum()}
        info = F['info']
        cls.rates = pd.DataFrame([dict(region='AAA', column=c, tls_rate=info['tau_tls'][j] - 1, pse_rate=info['tau'][j] - info['tau_tls'][j],
                                       output_tax_rate=info['pi'][j] - 1 if j < len(SECTORS) else 0.0)
                                  for j, c in enumerate(SECTORS + list(FD))])
        e = F['evfp12']
        cls.shares = pd.DataFrame([dict(region='AAA', sector=c, factor=f, share=e[k, j] / e[:, j].sum())
                                   for j, c in enumerate(SECTORS) if e[:, j].sum() > 0 for k, f in enumerate(FACTORS)])
        cls.zero = {'AAA': {k: info['pv0'][k] <= 0 for k in ('dom', 'imp')}}

    def mut(self, row, col, delta):
        io = self.io.copy()
        k = io.index[io['row'] == row][0]
        io.at[k, col] = io.at[k, col] + delta
        return io

    def both(self, fn, mutated, *args):
        self.assertEqual(fn(self.io, *args)[0], 0, fn(self.io, *args)[1])
        self.assertGreater(fn(mutated, *args)[0], 0)

    def test_cost_identity(self):
        self.both(K.cost_identity, self.mut('dom_trd', 'crp', 1.0), SECTORS)

    def test_market_clearing(self):
        self.both(K.market_clearing, self.mut('dom_trd', 'p', 1.0), SECTORS)

    def test_imports(self):
        self.both(K.imports_identity, self.mut('imp_crp', 'g', 0.5), SECTORS)

    def test_held_trade(self):
        self.both(K.held_trade, self.mut('dom_crp', 'X', 1.0), self.trade, SECTORS)

    def test_final_demand(self):
        self.both(K.final_demand, self.mut('dom_crp', 'p', 1.0), SECTORS, self.mt)

    def test_gdp(self):
        self.both(K.gdp_identity, self.mut('EVFP_capital', 'trd', 1.0), SECTORS, self.trade, self.gdp)

    def test_energy(self):
        self.both(K.energy_targets, self.mut('OUT', 'oil', 1.0), self.F['tout'])

    def test_rates(self):
        self.both(K.tax_rates, self.mut('TLS', 'ely', 1.0), SECTORS, self.rates)
        self.assertGreater(K.tax_rates(self.mut('PSE_input', 'crp', 0.5), SECTORS, self.rates)[0], 0)
        self.assertGreater(K.tax_rates(self.mut('OUT', 'crp', 0.5), SECTORS, self.rates)[0], 0)      # output support (pi)

    def test_shares(self):
        io = self.mut('EVFP_capital', 'trd', 1.0)
        io = io.copy()
        k = io.index[io['row'] == 'EVFP_land'][0]
        io.at[k, 'trd'] -= 1.0                                   # VA unchanged, composition changed
        self.both(K.factor_shares, io, SECTORS, self.shares, self.F['world'])

    def test_signs(self):
        self.both(K.signs, self.mut('imp_ely', 'i', -1e3), SECTORS, set())
        held = self.mut('EVFP_capital', 'ely', -1e4)
        self.assertGreater(K.signs(held, SECTORS, set())[0], 0)
        self.assertEqual(K.signs(held, SECTORS, {('AAA', 'ely')})[0], 0)

    def test_structural_zeros(self):
        self.both(K.structural_zeros, self.mut('dom_coa', 'p', 1.0), SECTORS, self.zero)

    def test_factors_match_io(self):
        fac = M.factor_table(self.io, pd.DataFrame(columns=['region', 'sector', 'factor', 'evfp', 'ftax', 'evfb', 'itax', 'fbep', 'evos']), SECTORS)
        self.assertEqual(K.factors_match_io(fac, self.io, SECTORS)[0], 0)
        bad = fac.copy()
        bad.loc[bad.index[0], 'evfp'] += 1.0
        self.assertGreater(K.factors_match_io(bad, self.io, SECTORS)[0], 0)

    def test_converged(self):
        self.assertEqual(K.converged([dict(region='AAA', ok=True, resid=0.0, worst='')])[0], 0)
        self.assertEqual(K.converged([dict(region='AAA', ok=False, resid=1.0, worst='MC_oil')])[0], 1)

    def test_factor_positive(self):
        self.assertEqual(K.factor_positive(pd.DataFrame({'factor': [1.0, 0.5]}, index=['A', 'B']))[0], 0)
        self.assertEqual(K.factor_positive(pd.DataFrame({'factor': [1.0, -0.3]}, index=['A', 'B']))[0], 1)

    def test_no_plug_columns(self):
        self.assertEqual(K.no_plug_columns(self.io, SECTORS)[0], 0)
        self.assertGreater(K.no_plug_columns(self.io.assign(stock_gap=0.0), SECTORS)[0], 0)


# ------------------------------------------------------------------ fix round 2026-10-24: energy rows (A10, B1)
class EnergyFixTest(unittest.TestCase):
    def problem(self, caps):
        r, trade_r, fd, tout = synthetic()
        rb = {('dom', 'oil'): 0.5, ('dom', 'gas'): 0.5, ('imp', 'oil'): 0.5, ('imp', 'gas'): 0.5}
        return M.build_problem('AAA', r, SECTORS, trade_r, fd, tout, {}, rb, {}, we(r), CHOICE, energy_caps=caps), trade_r, tout

    def test_caps_in_prior(self):
        io_, ig, ip = SECTORS.index('oil'), SECTORS.index('gas'), SECTORS.index('pet')
        (P0, i0), trade_r, tout = self.problem(None)
        caps = dict(intake_measured=True, intake_value_dom_musd=1.0, intake_value_imp_musd=0.5, gas_own_use_share=0.01)
        (P1, i1), _, _ = self.problem(caps)
        held = tout[('AAA', 'oil')] - trade_r[('X', 'oil')]
        for kind, cap in (('dom', 1.0 / held), ('imp', 0.5 / trade_r[('M', 'oil')])):
            b0 = i0['pv_presmear'][kind][io_] / i0['tau']
            b1 = i1['pv_presmear'][kind][io_] / i1['tau']
            self.assertGreater(b0[ip] / b0.sum(), cap)                   # the uncapped prior is above the cap
            self.assertAlmostEqual(b1[ip] / b1.sum(), cap)               # capped at intake / held total
            self.assertAlmostEqual(b1.sum(), b0.sum())                    # the row keeps its total
            g = i1['pv_presmear'][kind][ig] / i1['tau']
            self.assertAlmostEqual(g[ig] / g.sum(), 0.01)                 # gas own use at the UNSD share
        self.assertIn('REFINERY-CRUDE-CAP', [n[5] for n in i1['notes']])
        self.assertIn('GAS-OWN-USE-CAP', [n[5] for n in i1['notes']])
        self.assertTrue(M.fit_region(P1, i1, SECTORS)['ok'])
        (P2, i2), _, _ = self.problem(dict(caps, intake_measured=False, gas_own_use_share=np.nan))   # not measured: no cap
        self.assertTrue(np.allclose(i2['pv_presmear']['dom'], i0['pv_presmear']['dom']))

    def test_cap_without_other_buyers_goes_to_own_use(self):
        from s13_fit import energy as EN
        cols = SECTORS + list(FD)
        n = len(cols)
        pv = {k: np.zeros((len(SECTORS), n)) for k in ('dom', 'imp')}
        io_, ip = SECTORS.index('oil'), SECTORS.index('pet')
        pv['dom'][io_, ip] = 10.0
        tgt, X, Mv = np.full(len(SECTORS), np.nan), np.zeros(len(SECTORS)), np.zeros(len(SECTORS))
        tgt[io_] = 20.0
        notes, rep = EN.cap_prior(pv, np.ones(n), {c: i for i, c in enumerate(SECTORS)}, cols, tgt, X, Mv,
                                  dict(intake_measured=True, intake_value_dom_musd=5.0, intake_value_imp_musd=0.0, gas_own_use_share=np.nan),
                                  np.ones(n, bool))
        self.assertAlmostEqual(pv['dom'][io_, ip], 2.5)                  # 5 / 20 of the row
        self.assertAlmostEqual(pv['dom'][io_, io_], 7.5)                 # the rest: own use, losses and stock change
        self.assertEqual(notes[0][5], 'REFINERY-CRUDE-CAP-OWN-USE')

    def test_import_proportionality(self):
        from s13_fit import energy as EN
        F = fitted()
        agents = SECTORS + list(FD)
        self.assertGreater(EN.import_share_gap(F['io'], SECTORS, agents)[0], 0)      # the ICIO-style split fails the check
        R = copy.deepcopy(F['R'])
        moved = EN.import_proportionality(R['dom'], R['imp'], {c: i for i, c in enumerate(SECTORS)})
        self.assertGreater(moved, 0)
        tab, _ = M.region_table('AAA', R, F['info'], SECTORS, F['trade_r'], F['evfp12'], F['world'])
        self.assertEqual(EN.import_share_gap(tab, SECTORS, agents)[0], 0)
        for fn in (K.market_clearing, K.imports_identity, K.cost_identity):
            self.assertEqual(fn(tab, SECTORS)[0], 0)
        b0, b1 = F['io'].set_index('row'), tab.set_index('row')
        self.assertTrue(np.allclose(b0.loc['TLS', agents], b1.loc['TLS', agents]))          # tax by column unchanged
        self.assertTrue(np.allclose(b0.loc['dom_trd', agents], b1.loc['dom_trd', agents]))  # a non-energy row keeps its split
        info = F['info']
        z = EN.zero_mask({k: info['pv0'][k] <= 0 for k in ('dom', 'imp')}, {c: i for i, c in enumerate(SECTORS)})
        self.assertEqual(K.structural_zeros(tab, SECTORS, {'AAA': z})[0], 0)

    def test_cap_report(self):
        from s13_fit import energy as EN
        io = fitted()['io']
        b = io.set_index('row')
        crude = float(b.loc['dom_oil', 'pet'] + b.loc['imp_oil', 'pet'])
        caps = pd.DataFrame([dict(region='AAA', intake_measured=True, intake_value_dom_musd=crude, intake_value_imp_musd=0.0, gas_own_use_share=0.99)])
        self.assertEqual(EN.cap_report(io, caps, min_musd=0.0), ([], []))
        caps.loc[0, 'intake_value_dom_musd'] = crude / 2
        caps.loc[0, 'gas_own_use_share'] = 0.0
        oc, og = EN.cap_report(io, caps, min_musd=0.0)
        self.assertEqual((len(oc), len(og)), (1, 1))

    def test_own_use_cap(self):
        """Fix round wG: a held good's diagonal excess goes to the row's other buyers; ely's domestic excess is netted out."""
        from s13_fit import energy as EN
        cols = SECTORS + list(FD)
        n = len(cols)
        ig, ie, it, ip = SECTORS.index('gas'), SECTORS.index('ely'), SECTORS.index('trd'), cols.index('p')
        pv = {k: np.zeros((len(SECTORS), n)) for k in ('dom', 'imp')}
        pv['dom'][ig, ig], pv['dom'][ig, ie], pv['imp'][ig, ig], pv['imp'][ig, ip] = 6.0, 4.0, 2.0, 2.0
        pv['dom'][it, ig] = 12.0                                                       # the gas column: 8 own use, 12 trd
        pv['dom'][ie, ie], pv['dom'][ie, it], pv['imp'][ie, ie], pv['imp'][ie, ip] = 40.0, 60.0, 10.0, 10.0
        pv['dom'][it, ie] = 50.0                                                       # the ely column: 50 own use, 50 trd
        tau = np.ones((len(SECTORS), n))
        tau[ie, :] = 1.25
        tgt, va = np.full(len(SECTORS), np.nan), np.zeros(len(SECTORS))
        tgt[ig] = 20.0
        row_g = pv['dom'][ig].sum(), pv['imp'][ig].sum()
        notes, rep = EN.cap_own_use(pv, tau, {c: i for i, c in enumerate(SECTORS)}, cols, tgt, va, {'gas': 0.1, 'ely': 0.1},
                                    np.ones(n, bool))
        sh = {c: (pv['dom'][c, c] + pv['imp'][c, c]) / (pv['dom'][:, c].sum() + pv['imp'][:, c].sum()) for c in (ig, ie)}
        self.assertAlmostEqual(sh[ig], 0.1)                                            # 0.1 of the lower column
        self.assertLessEqual(sh[ie], 0.1 + 1e-12)      # ely capped first; the gas excess then raised its column
        self.assertAlmostEqual(pv['dom'][ig].sum(), row_g[0])                         # held rows keep their totals
        self.assertAlmostEqual(pv['imp'][ig].sum(), row_g[1])
        self.assertAlmostEqual(pv['dom'][ie, it], 60.0)                               # ely: the domestic excess left the row
        self.assertGreater(pv['imp'][ie, ip], 10.0)                                   # the imported excess went to households
        self.assertAlmostEqual(pv['imp'][ie].sum(), 20.0)
        self.assertEqual(sorted({x[5] for x in notes}), ['OWN-USE-CAP', 'OWN-USE-CAP-NETTED'])
        notes2, _ = EN.cap_own_use(pv, tau, {c: i for i, c in enumerate(SECTORS)}, cols, tgt, va, {'gas': 0.1}, np.ones(n, bool))
        self.assertEqual(notes2, [])                                                   # already at the cap

    def test_own_use_overshoot_and_hold(self):
        from s13_fit import energy as EN
        r, trade_r, fd, tout = synthetic()
        rb = {('dom', 'oil'): 0.5, ('dom', 'gas'): 0.5, ('imp', 'oil'): 0.5, ('imp', 'gas'): 0.5}
        P, i = M.build_problem('AAA', r, SECTORS, trade_r, fd, tout, {}, rb, {}, we(r), CHOICE)
        R = M.fit_region(P, i, SECTORS)
        je = SECTORS.index('ely')
        v = R['vals']['ely']
        f = float((v[2 * je] + v[2 * je + 1]) / v.sum())
        self.assertEqual(EN.own_use_overshoot(P, R, SECTORS, {'ely': f + 0.02}), {})
        self.assertIn('ely', EN.own_use_overshoot(P, R, SECTORS, {'ely': f - 0.02}))
        P2, i2 = M.build_problem('AAA', r, SECTORS, trade_r, fd, tout, {}, rb, {}, we(r), CHOICE, hold_own=('ely',))
        R2 = M.fit_region(P2, i2, SECTORS)
        self.assertTrue(R2['ok'])
        rows = K.own_use_rows('AAA', P2, R2, SECTORS, {'ely'})
        self.assertEqual(K.own_use_held(rows)[0], 0)                                   # held at its prior share

    def test_own_use_cap_in_problem_fits(self):
        (P0, i0), trade_r, tout = self.problem(None)
        r, trade_r, fd, tout = synthetic()
        rb = {('dom', 'oil'): 0.5, ('dom', 'gas'): 0.5, ('imp', 'oil'): 0.5, ('imp', 'gas'): 0.5}
        P1, i1 = M.build_problem('AAA', r, SECTORS, trade_r, fd, tout, {}, rb, {}, we(r), CHOICE, own_caps={'ely': 0.02, 'gas': 0.0})
        je = SECTORS.index('ely')
        self.assertLess(i1['pv0']['dom'][je, je], i0['pv0']['dom'][je, je])
        self.assertTrue(M.fit_region(P1, i1, SECTORS)['ok'])

    def test_pse_input_items(self):
        """Fix round wG (P7): a listed PSE B1 item goes on its row with the purchasers' value kept; the rest pro rata."""
        cols = SECTORS + list(FD)
        n = len(cols)
        ic, ie, jc = SECTORS.index('crp'), SECTORS.index('ely'), SECTORS.index('crp')
        basic = {k: np.zeros((len(SECTORS), n)) for k in ('dom', 'imp')}
        basic['dom'][ie, jc], basic['imp'][ie, jc], basic['dom'][ic, jc] = 6.0, 2.0, 12.0
        tau = np.ones((len(SECTORS), n))
        tau[:, jc] = 1.1
        tau_tls = tau.copy()
        P_before = basic['dom'][ie, jc] * tau[ie, jc]
        out = M.book_pse_input(basic, tau, tau_tls, {c: i for i, c in enumerate(SECTORS)}, jc, 5.0, {'ely': 4.0})
        self.assertAlmostEqual(out['ely']['value_musd'], 4.0)
        self.assertAlmostEqual(basic['dom'][ie, jc] + basic['imp'][ie, jc], 12.0)   # basic + the item
        rest = 1.0 / 20.0
        self.assertAlmostEqual(basic['dom'][ie, jc] * tau[ie, jc], P_before * (1.1 - rest) / 1.1)   # purchasers' value less the pro-rata part only
        self.assertAlmostEqual(tau[ic, jc], 1.1 - rest)
        sub = (12.0 * (tau[ie, jc] - tau_tls[ie, jc]))
        self.assertAlmostEqual(-sub, 4.0 + rest * 8.0)                               # item + its pro-rata share
        self.assertAlmostEqual(12.0 * (tau_tls[ie, jc] - 1.0), 8.0 * 0.1)            # the cell's other taxes keep their amount
        b2 = {k: np.zeros((len(SECTORS), n)) for k in ('dom', 'imp')}
        b2['dom'][ic, jc] = 10.0
        t2 = np.ones((len(SECTORS), n))
        out2 = M.book_pse_input(b2, t2, t2.copy(), {c: i for i, c in enumerate(SECTORS)}, jc, 2.0, {'ely': 9.0})
        self.assertEqual(out2, {})                                                    # no ely purchase: all pro rata
        self.assertAlmostEqual(t2[ic, jc], 0.8)
        PI = pd.DataFrame([dict(region='AAA', input_row='ely', listed_musd=4.0, **out['ely'])])
        self.assertEqual(K.pse_items_booked(PI, {'AAA': 5.0}, {'AAA': {'ely': 4.0}}, ['AAA'])[0], 0)
        self.assertEqual(K.pse_items_booked(PI, {'AAA': 2.0}, {'AAA': {'ely': 4.0}}, ['AAA'])[0], 1)   # should be scaled to 2
        self.assertEqual(K.pse_items_booked(PI.iloc[:0], {'AAA': 5.0}, {'AAA': {'ely': 4.0}}, ['AAA'])[0], 1)

    def test_pse_input_remainder_rows(self):
        """Round-3 QA item 9: the remainder goes on the region's B1 rows (one rate there), none on the other inputs."""
        cols = SECTORS + list(FD)
        n = len(cols)
        idx = {c: i for i, c in enumerate(SECTORS)}
        ic, ie, it, jc = idx['crp'], idx['ely'], idx['trd'], idx['crp']
        basic = {k: np.zeros((len(SECTORS), n)) for k in ('dom', 'imp')}
        basic['dom'][ie, jc], basic['dom'][it, jc], basic['dom'][ic, jc], basic['dom'][idx['pet'], jc] = 6.0, 5.0, 12.0, 2.0
        tau = np.ones((len(SECTORS), n))
        tau_tls = tau.copy()
        out = M.book_pse_input(basic, tau, tau_tls, idx, jc, 7.0, {'ely': 3.0}, remainder_rows=['ely', 'pet'])
        self.assertAlmostEqual(out['ely']['value_musd'], 3.0 + 4.0 * 6.0 / 8.0)
        self.assertEqual(out['ely']['part'], 'listed+remainder')
        self.assertAlmostEqual(out['pet']['value_musd'], 4.0 * 2.0 / 8.0)
        self.assertEqual(out['pet']['part'], 'remainder')
        self.assertAlmostEqual(tau[it, jc], 1.0)                                      # no flat rate on trade services
        self.assertAlmostEqual(tau[ic, jc], 1.0)
        PI = pd.DataFrame([dict(region='AAA', input_row=c, listed_musd=3.0 if c == 'ely' else 0.0, **f) for c, f in out.items()])
        self.assertEqual(K.pse_items_booked(PI, {'AAA': 7.0}, {'AAA': {'ely': 3.0}}, ['AAA'], remainder={'AAA': ['ely', 'pet']})[0], 0)
        self.assertEqual(K.pse_items_booked(PI.iloc[:1], {'AAA': 7.0}, {'AAA': {'ely': 3.0}}, ['AAA'], remainder={'AAA': ['ely', 'pet']})[0], 1)
        b2 = {k: np.zeros((len(SECTORS), n)) for k in ('dom', 'imp')}
        b2['dom'][ic, jc] = 10.0
        t2 = np.ones((len(SECTORS), n))
        self.assertEqual(M.book_pse_input(b2, t2, t2.copy(), idx, jc, 2.0, {}, remainder_rows=['ely']), {})   # no ely purchase
        self.assertAlmostEqual(t2[ic, jc], 0.8)                                       # stays on every input

    def test_pse_iea_full_netting(self):
        """Beta v4 G11: the PSE ely remainder netted against the whole IEA electricity money, at most the smaller."""
        cols = SECTORS + list(FD)
        n = len(cols)
        idx = {c: i for i, c in enumerate(SECTORS)}
        ie, iw, jc = idx['ely'], idx['pet'], idx['crp']
        def run(net):
            basic = {k: np.zeros((len(SECTORS), n)) for k in ('dom', 'imp')}
            basic['dom'][ie, jc], basic['dom'][iw, jc] = 6.0, 2.0
            tau = np.ones((len(SECTORS), n))
            return M.book_pse_input(basic, tau, tau.copy(), idx, jc, 8.0, {}, remainder_rows=['ely', 'pet'], net=net)
        big = run({'ely': 18.05})                                   # IEA above the PSE ely share (6): all 6 netted
        self.assertAlmostEqual(big['ely']['netted_musd'], 6.0)
        self.assertAlmostEqual(big['ely']['value_musd'], 0.0)
        self.assertAlmostEqual(big['pet']['value_musd'], 2.0)       # the other remainder row untouched
        small = run({'ely': 1.5})                                   # IEA below it: the IEA amount netted
        self.assertAlmostEqual(small['ely']['netted_musd'], 1.5)
        self.assertEqual(C.load_choices()['pse_iea_overlap']['value'], M.PSE_IEA_NET_FULL)
        self.assertIn(M.PSE_IEA_NET, C.CHOICES['pse_iea_overlap'])

    def test_pse_remainder_config(self):
        rem = C.read_pse_remainder()
        self.assertEqual(rem['IND'], ['ely', 'wat'])
        self.assertEqual(rem['IDN'], ['fin'])          # round-3 final QA2 item 6: fertiliser listed, the rest on credit
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, 'r.csv')
            with open(os.path.join(C.CONFIG_DIR, 'pse_input_remainder_2022.csv'), newline='') as fh:
                rows = list(csv.DictReader(fh))
            for bad in ([dict(rows[0], rows='trd')], [dict(rows[0], decided_by='')], rows + [rows[0]]):
                with open(p, 'w', newline='') as fh:
                    w = csv.DictWriter(fh, fieldnames=C.PSE_REMAINDER_COLUMNS)
                    w.writeheader()
                    w.writerows(bad)
                with self.assertRaises(SystemExit):
                    C.read_pse_remainder(p)
        finally:
            shutil.rmtree(tmp)

    def test_ptax_plan_bound(self):
        """A column that would need its rates moved beyond the bound stays at the bound; the others carry the rest."""
        pvs = [np.array([10.0, 10.0]), np.array([1.0, 0.0]), np.array([0.0, 0.0])]
        taus = [np.array([1.1, 1.1]), np.array([1.1, 1.0]), np.array([1.1, 1.1])]
        gens = [np.array([0.1, 0.1]), np.array([0.1, 0.0]), np.array([0.1, 0.1])]
        target = np.array([2.0, 0.3, 0.05])         # column 1 would need about 3.3x, column 2 has no base
        k, eff, cl = M.ptax_plan(pvs, taus, gens, target, np.ones(3), {})
        self.assertEqual(cl, {1: 'up', 2: 'no base'})
        self.assertAlmostEqual(k[1], M.PTAX_SCALE_BOUND)
        got = sum(M.ptax_money(pvs[j], taus[j], gens[j], k[j]) for j in range(3))
        self.assertAlmostEqual(got, target.sum(), places=9)                         # the region total held
        self.assertAlmostEqual(M.ptax_money(pvs[0], taus[0], gens[0], k[0]), eff[0], places=9)

    def test_ptax_plan_region_scale_signed(self):
        """Every column at its bound and the region still short of tax: the region fallback is bounded too (round-3
        final QA2 item 4), so no column moves beyond 2x and the money none can carry is dropped (rep['dropped'])."""
        pvs = [np.array([1.0]), np.array([1.0])]
        taus = [np.array([1.1]), np.array([0.95])]
        gens = [np.array([0.1]), np.array([-0.05])]
        target = np.array([0.5, -0.2])               # both need more than the 2x bound
        rep = {}
        k, eff, cl = M.ptax_plan(pvs, taus, gens, target, np.ones(2), {}, rep=rep)
        self.assertEqual(cl, {0: 'up', 1: 'up'})
        self.assertAlmostEqual(k[1], M.PTAX_SCALE_BOUND)                            # the subsidy column stays at its bound
        self.assertLessEqual(k[0], M.PTAX_SCALE_BOUND + 1e-12)                       # the tax column at most at its bound
        got = sum(M.ptax_money(pvs[j], taus[j], gens[j], k[j]) for j in range(2))
        self.assertGreater(rep['dropped'], 0.0)
        self.assertAlmostEqual(got + rep['dropped'], target.sum(), places=9)        # held + dropped = target

    def test_ptax_plan_region_fallback_within_bound(self):
        """Round-3 final QA2 item 4: when the bounded fallback can meet the gap, it does (nothing dropped) and every
        column's scale stays within [1/2, 2]."""
        pvs = [np.array([1.0]), np.array([1.0]), np.array([1.0])]
        taus = [np.array([1.1]), np.array([1.1]), np.array([0.95])]
        gens = [np.array([0.1]), np.array([0.1]), np.array([-0.05])]
        scale = np.array([1.0, 1.0, 1.0])
        # column 0 needs 3x alone, column 1 has no io_s12 money but a base (free with target 0): it takes the gap
        target = np.array([0.25, 0.0, -0.05])
        rep = {}
        k, eff, cl = M.ptax_plan(pvs, taus, gens, target, scale, {}, rep=rep)
        self.assertTrue(all(1 / M.PTAX_SCALE_BOUND - 1e-12 <= x <= M.PTAX_SCALE_BOUND + 1e-12 for x in k), k)
        got = sum(M.ptax_money(pvs[j], taus[j], gens[j], k[j]) for j in range(3))
        self.assertAlmostEqual(got + rep.get('dropped', 0.0), target.sum(), places=9)

    def test_product_tax_region_dropped(self):
        rows = [dict(region='AAA', column='p', general_musd=9.0, general_target_musd=10.0, held=True)]
        self.assertEqual(K.product_tax_region(rows)[0], 1)
        self.assertEqual(K.product_tax_region(rows, dropped={'AAA': 1.0})[0], 0)

    def test_g114_donor_regions(self):
        """Round-3 final QA2 item 1: a donor region takes G114 x GDP (general government first), a composite the
        GDP-weighted mean when 90% of its GDP is covered, else rates held."""
        world = pd.DataFrame([dict(COUNTRY='AAA', GFS_STO='G114', SECTOR='S1311MIXED', TIME_PERIOD=2022, OBS_VALUE=2.0),
                              dict(COUNTRY='AAA', GFS_STO='G114', SECTOR='S13', TIME_PERIOD=2022, OBS_VALUE=3.0),
                              dict(COUNTRY='BBB', GFS_STO='G114', SECTOR='S13', TIME_PERIOD=2021, OBS_VALUE=5.0),
                              dict(COUNTRY='C1', GFS_STO='G114', SECTOR='S13', TIME_PERIOD=2022, OBS_VALUE=10.0),
                              dict(COUNTRY='C2', GFS_STO='G114', SECTOR='S13', TIME_PERIOD=2022, OBS_VALUE=4.0)])
        sh = PS.g114_shares(world)
        self.assertEqual(sh['AAA'], (3.0, 'S13'))
        self.assertNotIn('BBB', sh)                    # 2021 only: not used
        w = pd.DataFrame([dict(region='AAA', code='AAA', s02_gdp=100.0, donor='DDD'),
                          dict(region='BBB', code='BBB', s02_gdp=50.0, donor='DDD'),
                          dict(region='XCC', code='C1', s02_gdp=30.0, donor='DDD'),
                          dict(region='XCC', code='C2', s02_gdp=60.0, donor='EEE'),
                          dict(region='XCC', code='C3', s02_gdp=5.0, donor='EEE'),
                          dict(region='XDD', code='C1', s02_gdp=10.0, donor='DDD'),
                          dict(region='XDD', code='D2', s02_gdp=10.0, donor='DDD')])
        t = PS.donor_regions_g114(w, sh, {'AAA': 200.0, 'BBB': 50.0, 'XCC': 100.0, 'XDD': 20.0}).set_index('region')
        self.assertEqual(t.loc['AAA', 'mode'], 'g114')
        self.assertAlmostEqual(t.loc['AAA', 'g114_musd'], 6.0)
        self.assertEqual(t.loc['BBB', 'mode'], 'rates')
        self.assertEqual(t.loc['XCC', 'mode'], 'g114')                       # 90 of 95 covered
        self.assertAlmostEqual(t.loc['XCC', 'g114_pct_gdp'], (10 * 30 + 4 * 60) / 90)
        self.assertEqual(t.loc['XDD', 'mode'], 'rates')                      # 50% covered

    def test_scale_general_to_total(self):
        cell = np.array([[0.2, 0.1], [0.5, 0.1]])      # row 1 has an energy rate 0.3 in column 0
        gen = np.array([[0.2, 0.1], [0.2, 0.1]])
        b = np.array([[10.0, 10.0], [10.0, 0.0]])
        tls = (cell * b).sum(axis=0)
        c2, g2, t2, info = PS.scale_general_to_total(cell, gen, b, tls, 3.0 + 2.0)   # G114 5, energy 3: general 2
        self.assertAlmostEqual(info['energy_excise_musd'], 3.0)
        self.assertAlmostEqual(float((g2 * b).sum()), 2.0)
        self.assertTrue(np.allclose(c2 - g2, cell - gen))                  # the energy rates stay
        self.assertTrue(np.allclose(t2, (c2 * b).sum(axis=0)))
        self.assertIsNone(PS.scale_general_to_total(cell, np.zeros_like(gen), b, tls, 5.0))

    def test_zero_unsourced_general(self):
        cell = np.array([[-0.02, 0.1], [0.28, 0.1]])     # column 0: a donor input subsidy -0.02, energy rate 0.3 on row 1
        gen = np.array([[-0.02, 0.1], [-0.02, 0.1]])
        b = np.array([[10.0, 10.0], [10.0, 0.0]])
        tls = (cell * b).sum(axis=0)
        c2, g2, t2, info = PS.zero_unsourced_general(cell, gen, b, tls)
        self.assertTrue((g2 >= 0).all())
        self.assertTrue(np.allclose(c2 - g2, cell - gen))                  # the energy rates stay
        self.assertTrue(np.allclose(t2, (c2 * b).sum(axis=0)))
        self.assertEqual(info['unsourced_cells'], 2)
        self.assertAlmostEqual(info['unsourced_musd'], 0.4)

    def test_product_tax_source_hold(self):
        """A donor region at G114 holds that money (less the energy excise) through the fit; a 'rates' region is not held."""
        r, trade_r, fd, tout = synthetic()
        rb = {('dom', 'oil'): 0.5, ('dom', 'gas'): 0.5, ('imp', 'oil'): 0.5, ('imp', 'gas'): 0.5}
        ch = dict(CHOICE, product_tax_totals=M.PTAX_HOLD)
        P, info = M.build_problem('AAA', r, SECTORS, trade_r, fd, tout, {}, rb, {}, we(r), ch,
                                  ptax_source=dict(mode='g114', g114_musd=1.0))
        src = info['ptax']['source']
        self.assertEqual(src['mode'], 'g114')
        self.assertAlmostEqual(float(info['ptax']['target'].sum()), src['general_target_musd'], places=9)
        R = M.fit_region(P, info, SECTORS)
        self.assertTrue(R['ok'], R['worst'])
        got = float(((R['dom'] + R['imp']) * info['ptax']['general']).sum())
        self.assertAlmostEqual(got + info['ptax']['report']['dropped'], src['general_target_musd'], places=6)
        P2, info2 = M.build_problem('AAA', r, SECTORS, trade_r, fd, tout, {}, rb, {}, we(r), ch, ptax_source=dict(mode='rates'))
        self.assertFalse(info2['ptax']['hold'])

    def test_pse_iea_netting(self):
        """Round-3 final QA2 item 6: support another source books on a remainder row is netted off it, not booked twice."""
        basic = {'dom': np.ones((len(SECTORS), len(SECTORS) + 3)), 'imp': np.zeros((len(SECTORS), len(SECTORS) + 3))}
        tc, tt = np.ones_like(basic['dom']), np.ones_like(basic['dom'])
        idx = {c: i for i, c in enumerate(SECTORS)}
        jc = idx['crp']
        out = M.book_pse_input(basic, tc, tt, idx, jc, 2.0, {}, remainder_rows=['ely'], net={'ely': 0.5})
        self.assertAlmostEqual(out['ely']['value_musd'], 1.5)
        self.assertAlmostEqual(out['ely']['netted_musd'], 0.5)

    def test_ptax_scale(self):
        pv, tau, gen = np.array([10.0, 5.0, 0.0]), np.array([1.2, 1.1, 1.0]), np.array([0.2, 0.1, 0.3])
        k = M.ptax_scale(pv, tau, gen, 1.0)
        d = tau + (k - 1.0) * gen
        self.assertAlmostEqual(float((pv * k * gen / d).sum()), 1.0, places=10)
        self.assertIsNone(M.ptax_scale(np.zeros(3), tau, gen, 1.0))                   # no base
        self.assertEqual(M.ptax_scale(np.zeros(3), tau, gen, 0.0), 1.0)

    def test_product_tax_totals_held(self):
        """Round-3 QA item 3: with product_tax_totals held, every column's general product-tax money equals its io_s12
        amount after the fit, the cell pattern scaled by one factor; without it the money moves with the fit."""
        r, trade_r, fd, tout = synthetic()
        rb = {('dom', 'oil'): 0.5, ('dom', 'gas'): 0.5, ('imp', 'oil'): 0.5, ('imp', 'gas'): 0.5}
        ch = dict(CHOICE, product_tax_totals=M.PTAX_HOLD)
        energy = {('pet', c): 0.3 for c in SECTORS + list(FD)}
        P, info = M.build_problem('AAA', r, SECTORS, trade_r, fd, tout, {}, rb, {'input': 2.0, 'output': 1.0}, we(r), ch, energy=energy)
        g0 = info['ptax']['general'].copy()
        R = M.fit_region(P, info, SECTORS)
        self.assertTrue(R['ok'], R['worst'])
        pt = info['ptax']
        b = R['dom'] + R['imp']
        got = (b * pt['general']).sum(axis=0)
        self.assertTrue(np.allclose(got, pt['target'], rtol=1e-8, atol=1e-8), (got, pt['target']))
        self.assertGreater(np.abs(pt['report']['free_fit'] - pt['target']).max(), 1e-6)   # the free fit had moved it
        for j in range(g0.shape[1]):                                                   # one factor per column
            nz = np.abs(g0[:, j]) > 1e-12
            if nz.sum() > 1:
                ratio = pt['general'][nz, j] / g0[nz, j]
                self.assertTrue(np.allclose(ratio, ratio[0], rtol=1e-10))
        ip = SECTORS.index('pet')
        self.assertTrue(np.allclose(info['tau_tls_cell'][ip, :] - 1.0 - pt['general'][ip, :], 0.3))   # energy rate kept
        rows = [dict(region='AAA', column=c, prior_tls_musd=pt['prior'][j], general_target_musd=pt['target'][j],
                     general_effective_musd=pt['report']['effective'][j], general_musd=got[j],
                     tls_musd=float((b[:, j] * (info['tau_tls_cell'][:, j] - 1.0)).sum()), held=True, unheld='')
                for j, c in enumerate(SECTORS + list(FD))]
        self.assertEqual(K.product_tax_held(rows)[0], 0)
        self.assertEqual(K.product_tax_region(rows)[0], 0)
        bad = [dict(rows[0], general_musd=rows[0]['general_musd'] + 1.0)] + rows[1:]
        self.assertEqual(K.product_tax_held(bad)[0], 1)
        self.assertEqual(K.product_tax_region(bad)[0], 1)
        self.assertEqual(K.product_tax_held([dict(bad[0], unheld='up')] + rows[1:])[0], 0)   # a column at the bound: region check only
        reg = K.product_tax_by_region(rows, {'AAA': 0.5})
        self.assertAlmostEqual(float(reg['prior_musd'].iloc[0]), float(sum(pt['prior'])) - 0.5)
        self.assertAlmostEqual(float(reg['general_fitted_musd'].iloc[0]), float(reg['general_io12_musd'].iloc[0]), places=6)
        P2, info2 = M.build_problem('AAA', r, SECTORS, trade_r, fd, tout, {}, rb, {'input': 2.0, 'output': 1.0}, we(r), CHOICE, energy=energy)
        R2 = M.fit_region(P2, info2, SECTORS)
        self.assertNotIn('report', info2['ptax'])
        self.assertTrue(np.allclose(info2['ptax']['general'], g0))


# ------------------------------------------------------------------ screens
class ScreensTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.expl = os.path.join(self.tmp, 'e.csv')
        F = fitted()
        io13 = F['io']
        io12 = F['r'].reset_index().assign(region='AAA')
        io12 = io12[['region'] + [c for c in io12.columns if c != 'region']]
        mt = pd.DataFrame([dict(region='AAA', GDP_musd=500.0, C_musd=100.0, G_musd=20.0, GFCF_musd=30.0, NX=0.0, factor=1.0,
                                C=100.0, G=20.0, I=30.0)]).set_index('region')
        self.ctx = dict(io13=io13, io12=io12, sectors=SECTORS, mt=mt, status=pd.DataFrame(columns=['region', 'sector', 'status']),
                        smears=pd.DataFrame(columns=['region', 'item', 'how', 'value_musd']), tout=F['tout'],
                        gate=pd.DataFrame([dict(region='AAA', intermediate_s12_musd=100.0, abs_change_musd=1.0, share=0.01)]), prev=None)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_(self, ctx):
        return SCR.run(ctx, report_dir=os.path.join(self.tmp, 'rep'), log=lambda *_: None, explanations=self.expl)

    def screen(self, res, name):
        return [h for h in res['hits'] if h['screen'] == name]

    def test_clean_build_passes(self):
        res = self.run_(self.ctx)
        self.assertEqual(res['material_unexplained'], 0, res['unexplained'])

    def test_each_screen_reports_its_mutation(self):
        c = copy.copy(self.ctx)
        c['mt'] = self.ctx['mt'].assign(factor=2.0, C=200.0, G=40.0, I=60.0)
        self.assertTrue(self.screen(self.run_(c), 'benchmark'))
        c = copy.copy(self.ctx)
        io12 = self.ctx['io12'].copy()
        k = io12.index[io12['row'] == 'OUT'][0]
        io12.at[k, 'ely'] = io12.at[k, 'ely'] / 10.0 if io12.at[k, 'ely'] > 1000 else 1.0     # ely output 'grows' many times
        c['io12'] = io12
        io13 = self.ctx['io13'].copy()
        k = io13.index[io13['row'] == 'OUT'][0]
        io13.at[k, 'ely'] = max(io13.at[k, 'ely'], 200.0)
        c['io13'] = io13
        self.assertTrue(self.screen(self.run_(c), 'outlier'))
        c = copy.copy(self.ctx)
        io13 = self.ctx['io13'].copy()
        k = io13.index[io13['row'] == 'dom_trd'][0]
        io13.at[k, 'p'] += 5.0
        c['io13'] = io13
        self.assertTrue(self.screen(self.run_(c), 'identity'))
        c = copy.copy(self.ctx)
        c['status'] = pd.DataFrame([dict(region='AAA', sector='ely', status='representative')])
        self.assertTrue(self.screen(self.run_(c), 'coverage'))
        c = copy.copy(self.ctx)
        prev = self.ctx['io13'].copy()
        k = prev.index[prev['row'] == 'OUT'][0]
        prev.at[k, 'trd'] *= 2.0
        c['prev'] = prev
        self.assertTrue(self.screen(self.run_(c), 'move'))
        c = copy.copy(self.ctx)
        c['gate'] = pd.DataFrame([dict(region='AAA', intermediate_s12_musd=100.0, abs_change_musd=30.0, share=0.3)])
        self.assertTrue(self.screen(self.run_(c), 'icio_gate'))

    def test_fuel_subsidy_explains_output_move(self):
        c = copy.copy(self.ctx)
        io12 = self.ctx['io12'].copy()
        k = io12.index[io12['row'] == 'OUT'][0]
        io12.at[k, 'ely'] = 1.0
        c['io12'] = io12
        io13 = self.ctx['io13'].copy()
        k = io13.index[io13['row'] == 'OUT'][0]
        io13.at[k, 'ely'] = max(io13.at[k, 'ely'], 200.0)
        c['io13'] = io13
        hit = self.screen(self.run_(c), 'outlier')
        self.assertTrue(hit and not hit[0]['detail'])                     # unexplained without the subsidy
        c['fuel'] = {('AAA', 'ely'): float(io13.at[k, 'ely'])}
        hit = self.screen(self.run_(c), 'outlier')
        self.assertIn('fuel subsidy', hit[0]['detail'])                   # B15: explained by the subsidy booking
        c['fuel'] = {('AAA', 'ely'): 1.0}
        self.assertFalse(self.screen(self.run_(c), 'outlier')[0]['detail'])   # a small subsidy does not explain it

    def test_material_unexplained_fails_and_row_explains(self):
        c = copy.copy(self.ctx)
        c['mt'] = self.ctx['mt'].assign(factor=2.0, C=200.0, G=40.0, I=60.0)
        self.assertEqual(self.run_(c)['material_unexplained'], 1)
        with open(self.expl, 'w', newline='') as fh:
            w = csv.writer(fh)
            w.writerow(['importer', 'hs6/sector', 'screen', 'evidence class', 'source file and page', 'decided_by', 'date'])
            w.writerow(['AAA', 'all', 'benchmark', 'data_gap', 'test', 'test', '2026-10-24'])
        self.assertEqual(self.run_(c)['material_unexplained'], 0)


if __name__ == '__main__':
    unittest.main()


# ------------------------------------------------------------------ fix list A2: export tax in the held trade
class ExportTaxHeldTest(unittest.TestCase):
    def setUp(self):
        self.xt10 = pd.DataFrame(dict(exporter=['KAZ'], sector=['oil'], rate=[0.1]))
        self.ex = pd.DataFrame(dict(sector=['oil', 'oil'], exporter=['KAZ', 'KAZ'], importer=['CHN', 'ITA'], vfob_musd=[60.0, 40.0], vxsb_musd=[54.0, 36.0]))
        self.gx = pd.DataFrame(dict(sector=['crp'], exporter=['ARG'], importer=['CHN'], vfob_musd=[10.0], vxsb_musd=[8.5]))
        self.held = pd.DataFrame(dict(region=['KAZ', 'ARG', 'KAZ'], sector=['oil', 'crp', 'tou'], X=[95.0, 8.5, 3.0], XFOB=[105.0, 10.0, 3.0]))

    def test_clean_and_mutations(self):
        # KAZ oil: 90 of energy VXSB + 5 of travel at FOB; tax 10
        self.assertEqual(K.export_tax_held(self.held, self.ex, self.xt10, self.gx), (0, ''))
        # mutation: energy exports at VXSB = VFOB (the tax dropped)
        bad = self.held.assign(X=[105.0, 8.5, 3.0])
        self.assertGreater(K.export_tax_held(bad, self.ex, self.xt10, self.gx)[0], 0)
        # mutation: a goods export tax lost
        self.assertGreater(K.export_tax_held(self.held.assign(X=[95.0, 10.0, 3.0]), self.ex, self.xt10, self.gx)[0], 0)
        # mutation: a wedge on services
        self.assertGreater(K.export_tax_held(self.held.assign(X=[95.0, 8.5, 2.0]), self.ex, self.xt10, self.gx)[0], 0)

    def test_rate_rounded_to_six_decimals(self):
        # S11 writes export_tax_rate to 6 decimals: KAZ oil 46 bn at 0.1273316 is booked as 0.127332, a 0.02 USD m gap
        v = 46247.688612
        ex = pd.DataFrame(dict(sector=['oil'], exporter=['KAZ'], importer=['CHN'], vfob_musd=[v], vxsb_musd=[v * (1 - 0.1273316)],
                               export_tax_rate=[0.127332]))
        held = pd.DataFrame(dict(region=['KAZ'], sector=['oil'], X=[v * (1 - 0.1273316)], XFOB=[v]))
        self.assertEqual(K.export_tax_held(held, ex, self.xt10), (0, ''))
        # a real miss (0.1% of the tax) still fails
        self.assertGreater(K.export_tax_held(held.assign(X=held['X'] + 6.0), ex, self.xt10)[0], 0)


# ------------------------------------------------------------------ fix-round B15: fuel subsidies
class FuelSubsidyTest(unittest.TestCase):
    """GTAP's booking (Chepeliev et al. 2018 §3): a negative purchase tax on firms, households and government,
    domestic and imported, with each prior purchasers' value kept; the column TLS moves by exactly the subsidy."""
    RB = {('dom', 'oil'): 0.5, ('dom', 'gas'): 0.5, ('imp', 'oil'): 0.5, ('imp', 'gas'): 0.5}

    @classmethod
    def setUpClass(cls):
        r, trade_r, fd, tout = synthetic()
        ip = SECTORS.index('pet')
        tout = {**tout, ('AAA', 'pet'): float(r.loc['OUT', 'pet']) * 1.2}       # pet is an S11 target here
        energy = {('pet', 'p'): 0.3, ('pet', 'trd'): 0.02}
        cls.args = (r, trade_r, fd, tout, energy)
        cls.sub = {'pet': 6.0, 'ely': 3.0}
        _, cls.info0 = M.build_problem('AAA', r, SECTORS, trade_r, fd, tout, {}, cls.RB, {}, we(r), CHOICE, energy=energy)
        P, info = M.build_problem('AAA', r, SECTORS, trade_r, fd, tout, {}, cls.RB, {}, we(r), CHOICE, energy=energy, subsidies=cls.sub)
        R = M.fit_region(P, info, SECTORS)
        evfp12 = r.loc[[f'EVFP_{f}' for f in FACTORS], SECTORS].to_numpy(float)
        world = pd.DataFrame(np.tile(evfp12.sum(axis=1) / evfp12.sum(), (len(SECTORS), 1)), index=SECTORS, columns=list(FACTORS))
        cls.tab, _ = M.region_table('AAA', R, info, SECTORS, trade_r, evfp12, world)
        cls.R, cls.info, cls.ip = R, info, ip
        cls.cols = SECTORS + list(FD)
        cls.mask = M.subsidy_columns(cls.cols, SECTORS)

    def test_prior_purchasers_values_kept_and_rate_scaled(self):
        i0, i1, ip = self.info0, self.info, self.ip
        for k in ('dom', 'imp'):
            np.testing.assert_allclose(i1['pv0'][k], i0['pv0'][k])                 # tax-paid values unchanged
        f = i1['fuel']['pet']
        self.assertEqual(f['status'], 'booked')
        np.testing.assert_allclose(i1['tau_cell'][ip, self.mask], i0['tau_cell'][ip, self.mask] * (1 - f['rho']))
        ji = self.cols.index('i')
        self.assertEqual(i1['tau_cell'][ip, ji], i0['tau_cell'][ip, ji])          # investment is not subsidised (paper §3.1)
        other = [i for i in range(len(SECTORS)) if SECTORS[i] not in ('pet', 'ely')]
        np.testing.assert_allclose(i1['tau_cell'][other], i0['tau_cell'][other])  # other rows untouched
        # basic value up and tax down by the same amount, cell by cell
        pv = i1['pv0']['dom'][ip] + i1['pv0']['imp'][ip]
        b0, b1 = pv / i0['tau_cell'][ip], pv / i1['tau_cell'][ip]
        np.testing.assert_allclose((b1 - b0)[self.mask].sum(), f['booked_prior'] * (b1 - b0)[self.mask].sum() / (f['rho'] * b1[self.mask].sum()))
        np.testing.assert_allclose(b1 * (i1['tau_cell'][ip] - 1) - b0 * (i0['tau_cell'][ip] - 1), -(b1 - b0), atol=1e-12)
        self.assertAlmostEqual(i1['fuel']['ely']['booked_prior'], 3.0)            # electricity: exact in the prior

    def test_fitted_table_books_held_subsidy_and_tls(self):
        self.assertTrue(self.R['ok'], self.R['worst'])
        b = self.R['dom'] + self.R['imp']
        f = self.info['fuel']['pet']
        booked = f['rho'] * b[self.ip, self.mask].sum()
        self.assertAlmostEqual(booked, 6.0, places=7)
        rho = np.zeros(len(SECTORS))
        for c, x in self.info['fuel'].items():
            rho[SECTORS.index(c)] = x['rho']
        tls = self.tab.set_index('row').loc['TLS', self.cols].to_numpy(float)
        self.assertLess(K.subsidy_tls_gap(b, self.info['tau_tls_nosub'], rho, self.mask, tls), 1e-9)
        self.assertGreater(K.subsidy_tls_gap(b, self.info['tau_tls_nosub'], rho, self.mask, tls + np.eye(len(tls))[0]), 1e-6)   # TLS off
        self.assertGreater(K.subsidy_tls_gap(b, self.info['tau_tls_nosub'], rho * 0.5, self.mask, tls), 1e-6)                   # subsidy off
        rows = [dict(region='AAA', commodity=c, to_book_musd=self.sub[c], rho=x['rho'], kind='held' if c == 'pet' else 'prior', status=x['status'],
                     booked_prior_musd=x['booked_prior'], booked_fitted_musd=x['rho'] * b[SECTORS.index(c), self.mask].sum())
                for c, x in self.info['fuel'].items()]
        self.assertEqual(K.fuel_subsidy_booked(rows)[0], 0, K.fuel_subsidy_booked(rows)[1])
        by = {x['commodity']: x for x in rows}
        for c, mut in (('pet', dict(booked_fitted_musd=5.0)), ('ely', dict(booked_prior_musd=2.0)), ('pet', dict(status='no_purchases')), ('ely', dict(rho=1.2))):
            self.assertGreater(K.fuel_subsidy_booked([dict(by[c], **mut)])[0], 0)
        cells = K.fuel_subsidy_columns(self.tab.assign(region='AAA'), rows, SECTORS, self.mask)
        self.assertAlmostEqual(sum(x['subsidy_musd'] for x in cells if x['commodity'] == 'pet'), 6.0, places=7)
        self.assertNotIn('i', {x['column'] for x in cells})

    def test_extension_sized_subsidy_books_exactly(self):
        """Fix-round B15 extension (David 2026-10-24): S11 rows not priced by the IEA gap (RUS and SAU gas at regulated
        prices, IRN) carry rho near 0.7; S13 books them as any other row, exactly in the fitted table, with rho < 1."""
        r, trade_r, fd, tout, energy = self.args
        held = 6.0 / self.info['fuel']['pet']['rho']
        sub = {'pet': 0.7 * held}
        P, info = M.build_problem('AAA', r, SECTORS, trade_r, fd, tout, {}, self.RB, {}, we(r), CHOICE, energy=energy, subsidies=sub)
        R = M.fit_region(P, info, SECTORS)
        self.assertTrue(R['ok'], R['worst'])
        f = info['fuel']['pet']
        self.assertAlmostEqual(f['rho'], 0.7, places=9)
        b = R['dom'] + R['imp']
        self.assertAlmostEqual(f['rho'] * b[self.ip, self.mask].sum(), sub['pet'], places=6)
        row = dict(region='AAA', commodity='pet', to_book_musd=sub['pet'], rho=f['rho'], kind='held', status=f['status'],
                   booked_prior_musd=f['booked_prior'], booked_fitted_musd=f['rho'] * b[self.ip, self.mask].sum())
        self.assertEqual(K.fuel_subsidy_booked([row])[0], 0)
        self.assertGreater(K.fuel_subsidy_booked([dict(row, booked_fitted_musd=0.5 * sub['pet'])])[0], 0)   # the IEA value short-booked

    def test_electricity_subsidy_money_held(self):
        """Round-3 final QA item 4 (electricity_subsidy_money): the electricity subsidy, booked exactly in the prior, is
        also booked exactly in the fitted table (rho reset after each pass), alone or with the product-tax hold; the
        column TLS still moves by exactly the booked subsidy and the held goods keep their exact booking."""
        r, trade_r, fd, tout, energy = self.args
        free = self.R['dom'] + self.R['imp']
        ie = SECTORS.index('ely')
        self.assertGreater(abs(self.info['fuel']['ely']['rho'] * free[ie, self.mask].sum() - self.sub['ely']), 1e-6)   # drifts without the hold
        for extra in (dict(), dict(product_tax_totals=M.PTAX_HOLD)):
            ch = dict(CHOICE, electricity_subsidy_money=M.ELY_SUBSIDY_HOLD, **extra)
            P, info = M.build_problem('AAA', r, SECTORS, trade_r, fd, tout, {}, self.RB, {}, we(r), ch, energy=energy, subsidies=self.sub)
            self.assertTrue(info['fuel']['ely']['money_held'])
            self.assertFalse(info['fuel']['pet']['money_held'])                       # an S11 target good is held by its basis
            R = M.fit_region(P, info, SECTORS)
            self.assertTrue(R['ok'], R['worst'])
            b = R['dom'] + R['imp']
            for c in ('ely', 'pet'):
                self.assertAlmostEqual(info['fuel'][c]['rho'] * b[SECTORS.index(c), self.mask].sum(), self.sub[c], places=6)
            rho = np.zeros(len(SECTORS))
            for c, x in info['fuel'].items():
                rho[SECTORS.index(c)] = x['rho']
            evfp12 = r.loc[[f'EVFP_{f}' for f in FACTORS], SECTORS].to_numpy(float)
            world = pd.DataFrame(np.tile(evfp12.sum(axis=1) / evfp12.sum(), (len(SECTORS), 1)), index=SECTORS, columns=list(FACTORS))
            tab, _ = M.region_table('AAA', R, info, SECTORS, trade_r, evfp12, world)
            tls = tab.set_index('row').loc['TLS', self.cols].to_numpy(float)
            self.assertLess(K.subsidy_tls_gap(b, info['tau_tls_nosub'], rho, self.mask, tls), 1e-8)
            row = dict(region='AAA', commodity='ely', to_book_musd=self.sub['ely'], rho=info['fuel']['ely']['rho'], kind='prior', status='booked',
                       booked_prior_musd=info['fuel']['ely']['booked_prior'], money_held=True,
                       booked_fitted_musd=info['fuel']['ely']['rho'] * b[ie, self.mask].sum())
            self.assertEqual(K.fuel_subsidy_booked([row])[0], 0)
            self.assertEqual(K.fuel_subsidy_booked([dict(row, booked_fitted_musd=row['booked_fitted_musd'] + 1.0)])[0], 1)
            self.assertEqual(K.fuel_subsidy_booked([dict(row, booked_fitted_musd=row['booked_fitted_musd'] + 1.0, money_held=False)])[0], 0)

    def test_factor_income_gdp(self):
        """Round-3 final QA item 4: factor income may exceed GDP only by the booked product subsidies."""
        cols = SECTORS + list(FD)
        rows = [dict(region='AAA', row=f'EVFP_{f}', **{c: (10.0 if c == SECTORS[0] and f == M.FACTORS[0] else 0.0) for c in cols})
                for f in M.FACTORS]
        rows += [dict(region='AAA', row='PSE_input', **{c: (-1.0 if c == SECTORS[0] else 0.0) for c in cols}),
                 dict(region='AAA', row='PTAX', **{c: (-0.5 if c == SECTORS[0] else 0.2 if c == SECTORS[1] else 0.0) for c in cols})]
        io = pd.DataFrame(rows)
        n, _, df = K.factor_income_gdp(io, SECTORS, {'AAA': 6.0}, {'AAA': 2.5})          # excess 4 = 2.5 + 1 + 0.5
        self.assertEqual(n, 0)
        self.assertAlmostEqual(float(df['booked_subsidy_musd'].iloc[0]), 4.0)
        self.assertEqual(K.factor_income_gdp(io, SECTORS, {'AAA': 6.0}, {'AAA': 1.0})[0], 1)   # factor income above GDP beyond the subsidies
        self.assertEqual(K.factor_income_gdp(io, SECTORS, {'AAA': 12.0}, {})[0], 0)            # below GDP

    def test_rates_and_identities_still_hold(self):
        info, tab = self.info, self.tab
        rates = pd.DataFrame([dict(region='AAA', column=c, tls_rate=info['tau_tls'][j] - 1, pse_rate=info['tau'][j] - info['tau_tls'][j],
                                   output_tax_rate=info['pi'][j] - 1 if j < len(SECTORS) else 0.0) for j, c in enumerate(self.cols)])
        cells = pd.DataFrame([('AAA', c, s, info['tau_tls_cell'][i, j] - 1, info['tau_cell'][i, j] - info['tau_tls_cell'][i, j])
                              for j, c in enumerate(self.cols) for i, s in enumerate(SECTORS)],
                             columns=['region', 'column', 'commodity', 'tls_rate', 'pse_rate'])
        self.assertEqual(K.tax_rates(tab, SECTORS, rates, cells)[0], 0)
        nosub = cells.assign(tls_rate=[info['tau_tls_nosub'][SECTORS.index(s), self.cols.index(c)] - 1 for c, s in zip(cells['column'], cells['commodity'])])
        self.assertGreater(K.tax_rates(tab, SECTORS, rates, nosub)[0], 0)        # S13-Hrates sees a missing subsidy
        r, trade_r, fd, tout, _ = self.args
        self.assertEqual(K.energy_targets(tab, tout)[0], 0)
        self.assertEqual(K.cost_identity(tab, SECTORS)[0], 0)
        self.assertEqual(K.market_clearing(tab, SECTORS)[0], 0)
        tr = pd.DataFrame([dict(region='AAA', sector=c, X=trade_r[('X', c)], XFOB=trade_r[('X', c)], VST=trade_r[('VST', c)],
                                M=trade_r[('M', c)], MCIF=trade_r[('M', c)]) for c in SECTORS])
        mt = pd.DataFrame([dict(region='AAA', C=fd['C'], G=fd['G'], I=fd['I'], factor=1.0)]).set_index('region')
        gdp = {'AAA': fd['C'] + fd['G'] + fd['I'] + tr['XFOB'].sum() + tr['VST'].sum() - tr['MCIF'].sum()}
        self.assertEqual(K.final_demand(tab, SECTORS, mt)[0], 0)
        self.assertEqual(K.gdp_identity(tab, SECTORS, tr, gdp)[0], 0, K.gdp_identity(tab, SECTORS, tr, gdp)[1])

    def test_no_purchases_and_rho_bound(self):
        r, trade_r, fd, tout, energy = self.args
        _, info = M.build_problem('AAA', r, SECTORS, trade_r, fd, tout, {}, self.RB, {}, we(r), CHOICE, energy=energy, subsidies={'pet': 1e9})
        self.assertEqual(info['fuel']['pet']['status'], 'rho_not_below_1')
        np.testing.assert_allclose(info['tau_cell'], self.info0['tau_cell'])     # nothing booked

    def test_neer_overlap(self):
        rows = [dict(region='AAA', commodity='pet', s11_subsidy_musd=10.0, neer_subsidy_musd=-4.0, to_book_musd=6.0),
                dict(region='AAA', commodity='gas', s11_subsidy_musd=3.0, neer_subsidy_musd=-5.0, to_book_musd=0.0)]
        src = {('AAA', 'pet'): 'OECD NEERS AAA', ('AAA', 'gas'): 'fill'}
        self.assertEqual(K.neer_overlap(rows, src, True)[0], 0)
        self.assertEqual(K.neer_overlap([dict(rows[0], to_book_musd=10.0)], src, True)[0], 1)   # booked twice
        self.assertEqual(K.neer_overlap(rows, src, False)[0], 2)                               # S10 column missing
        self.assertEqual(K.neer_overlap(rows, {}, False)[0], 0)                                # no S10 energy rates

    def test_choices(self):
        ch = C.load_choices()
        self.assertEqual(ch['fuel_subsidies']['value'], C.CHOICES['fuel_subsidies'][0])
        self.assertIn('off', C.CHOICES['fuel_subsidies'])


class FactorMoneyTest(unittest.TestCase):
    """factor_tax_totals (GTAP 12 ch.15): the fitted factor taxes keep S12's money totals by region and factor."""

    def test_hold_money(self):
        from s13_fit import method as M13
        io13 = pd.DataFrame([dict(region='R', row='EVFP_capital', a=30.0, b=10.0)])
        fac12 = pd.DataFrame([dict(region='R', sector=s, factor='capital', evfp=v, ftax=1.0, evfb=v - 1.0, itax=2.0, fbep=0.0, evos=v - 3.0)
                              for s, v in (('a', 10.0), ('b', 10.0))])
        rates = M13.factor_table(io13, fac12, ['a', 'b'])
        money = M13.factor_table(io13, fac12, ['a', 'b'], hold_money=True)
        self.assertAlmostEqual(rates['ftax'].sum(), 4.0)        # rates held: 3 + 1
        self.assertAlmostEqual(money['ftax'].sum(), 2.0)        # money held: S12 total
        self.assertAlmostEqual(money['itax'].sum(), 4.0)
        np.testing.assert_allclose(money['ftax'].to_numpy(), [1.5, 0.5])
        np.testing.assert_allclose((money['evfb'] - money['evfp'] + money['ftax']).to_numpy(), 0.0)
# ------------------------------------------------------------------ fix round wC: own-use (diagonal) shares
class OwnUseTest(unittest.TestCase):
    def problem(self, groups=None):
        # a and b free; the import row m is priced and must fall from 30 to 20, so every column's shares move
        cols = [Column('a', [0, 1, 2, -1], [1, 1, 1, 0], [40, 20, 15, 25], own_row=0, own_coef=-1.0, groups=groups),
                Column('b', [0, 1, 2, -1], [1, 1, 1, 0], [30, 10, 5, 55], own_row=1, own_coef=-1.0),
                Column('p', [0, 1, 2], [1, 1, 1], [60, 70, 10], total=150.0)]
        return Problem(['MC_a', 'MC_b', 'IM_m'], [30.0, 20.0, -20.0], cols)

    def test_free_own_share_moves_with_a_priced_row(self):
        # GTAP's cross-entropy alone: the import cell of a falls, so its other shares, the diagonal among them, rise
        P = self.problem()
        R = solve(P)
        self.assertTrue(R['ok'], R['worst'])
        v = R['vals']['a']
        self.assertGreater(v[0] / v.sum(), 0.4 + 1e-4)

    def test_held_group_keeps_its_prior_share(self):
        P = self.problem(groups=[1, 0, 0, 0])
        R = solve(P)
        self.assertTrue(R['ok'], R['worst'])
        v = R['vals']['a']
        self.assertAlmostEqual(v[0] / v.sum(), 0.4, places=10)
        va, vb, vp = R['vals']['a'], R['vals']['b'], R['vals']['p']
        self.assertAlmostEqual(va[2] + vb[2] + vp[2], 20.0, places=6)        # the import row is still met
        self.assertAlmostEqual(va[0] + vb[0] + vp[0] + 30.0, va.sum(), places=6)
        # and the cells minimise I given the extra adding-up constraint on the group
        from scipy.optimize import minimize
        th = [c.theta0 for c in P.columns]
        Ea, Eb = va.sum(), vb.sum()

        def obj(z):
            t = 0.0
            for vv, t0 in zip([z[0:4], z[4:8], z[8:11]], th):
                t += float(np.sum(vv * np.log(np.maximum(vv, 1e-12) / (vv.sum() * t0))))
            return t
        cons = [{'type': 'eq', 'fun': lambda z: z[0:4].sum() - Ea},
                {'type': 'eq', 'fun': lambda z: z[0] - 0.4 * Ea},
                {'type': 'eq', 'fun': lambda z: z[4:8].sum() - Eb},
                {'type': 'eq', 'fun': lambda z: z[8:11].sum() - 150.0},
                {'type': 'eq', 'fun': lambda z: z[2] + z[6] + z[10] - 20.0}]
        z0 = np.concatenate([c.prior for c in P.columns])
        res = minimize(obj, z0, constraints=cons, bounds=[(1e-9, None)] * 11, method='SLSQP', options={'ftol': 1e-12, 'maxiter': 500})
        np.testing.assert_allclose(np.concatenate([R['vals'][c.name] for c in P.columns]), res.x, atol=1e-3)

    def test_bad_groups_stop(self):
        with self.assertRaises(ValueError):
            Column('a', [0, -1], [1, 0], [1, 1], own_row=0, own_coef=-1.0, groups=[0])

    def fit(self, rule):
        r, trade_r, fd, tout = synthetic(0)
        rep_b06 = {('dom', 'oil'): 0.5, ('dom', 'gas'): 0.5, ('imp', 'oil'): 0.5, ('imp', 'gas'): 0.5}
        P, info = M.build_problem('AAA', r, SECTORS, trade_r, fd, tout, {}, rep_b06, {'input': 2.0, 'output': 1.0}, we(r),
                                  dict(CHOICE, own_use_share=rule))
        R = M.fit_region(P, info, SECTORS)
        self.assertTrue(R['ok'], R['worst'])
        return K.own_use_rows('AAA', P, R, SECTORS, M.own_use_held(SECTORS, rule))

    def test_energy_activities_held_in_the_fit(self):
        rows = self.fit('energy_activities_own_use_share_held_at_prior')
        held = {x['sector'] for x in rows if x['held']}
        self.assertEqual(held, {'oil', 'gas', 'pet', 'ely'})                  # coa is shut in the synthetic economy
        self.assertEqual(K.own_use_held(rows)[0], 0)
        moved = [dict(x, fitted_share=x['fitted_share'] + 1e-6) if x['sector'] == 'pet' else x for x in rows]
        self.assertEqual(K.own_use_held(moved)[0], 1)
        free = self.fit('cross_entropy_free')
        self.assertFalse(any(x['held'] for x in free))
        # the held target column (oil) keeps its own share; the free fit moves it
        o_h = [x for x in rows if x['sector'] == 'oil'][0]
        o_f = [x for x in free if x['sector'] == 'oil'][0]
        self.assertAlmostEqual(o_h['fitted_share'], o_h['prior_share'], places=9)
        self.assertGreater(abs(o_f['fitted_share'] - o_f['prior_share']), 1e-6)

    def test_every_activity_rule(self):
        rows = self.fit('every_activity_own_use_share_held_at_prior')
        self.assertTrue(all(x['held'] for x in rows))
        self.assertEqual(K.own_use_held(rows)[0], 0)

    def test_own_use_report(self):
        rows = [dict(region='R', sector='ely', held=False, prior_share=0.50, fitted_share=0.56, prior_own_musd=1500.0, fitted_own_musd=1900.0),
                dict(region='R', sector='msp', held=False, prior_share=0.56, fitted_share=0.54, prior_own_musd=72000.0, fitted_own_musd=95000.0),
                dict(region='R', sector='trd', held=False, prior_share=0.10, fitted_share=0.30, prior_own_musd=10.0, fitted_own_musd=50.0)]
        self.assertEqual([x['sector'] for x in K.own_use_moves(rows)], ['ely'])

    def test_choice_is_in_the_file(self):
        ch = C.load_choices()
        self.assertIn(ch['own_use_share']['value'], C.CHOICES['own_use_share'])
        self.assertEqual(set(C.CHOICES['own_use_share']), set(M.OWN_USE_RULE))


class EnergyUserCellsTest(unittest.TestCase):
    """Fix round S16 (Fable QA C-01): a held energy row is split across its users at their prior basic shares, with
    refining and power as one free pool; cells already held (power fuel cells) keep their values."""

    def test_split_at_prior_shares(self):
        sectors = ['gas', 'oil', 'pet', 'ely', 'mfr']
        idx = {c: i for i, c in enumerate(sectors)}
        cols = sectors + list(M.FD)
        J = len(cols)
        pv = {k: np.zeros((len(sectors), J)) for k in ('dom', 'imp')}
        tau = np.ones((len(sectors), J))
        tau[idx['gas'], cols.index('p')] = 0.5                     # subsidised households: basic is pv / 0.5
        pv['dom'][idx['gas'], [idx['gas'], idx['oil'], idx['pet'], idx['ely'], idx['mfr'], cols.index('p')]] = [1, 1, 2, 4, 1, 0.5]
        tgt = np.array([110.0, np.nan, np.nan, np.nan, np.nan]); X = np.array([10.0, 0, 0, 0, 0]); Mv = np.zeros(5)
        held = {}
        rows = M.hold_energy_users(pv, tau, idx, {}, tgt, X, Mv, held, cols)
        b = {'gas': 1, 'oil': 1, 'pet': 2, 'ely': 4, 'mfr': 1, 'p': 1}          # prior basic, total 10
        for c in ('gas', 'oil', 'mfr', 'p'):
            j = idx[c] if c in idx else cols.index(c)
            self.assertAlmostEqual(held[('dom', idx['gas'], j)], 100.0 * b[c] / 10.0)
        self.assertNotIn(('dom', idx['gas'], idx['pet']), held)                # the pool stays free
        self.assertAlmostEqual(rows[0]['pool_musd'], 60.0)
        self.assertAlmostEqual(pv['dom'][idx['gas'], cols.index('p')], 10.0 * 0.5)   # purchasers' value at the cell power

    def test_pipeline_cap_moves_excess_to_other_users(self):
        sectors = ['gas', 'msp', 'mfr']
        idx = {c: i for i, c in enumerate(sectors)}
        cols = sectors + list(M.FD)
        pv = {k: np.zeros((3, len(cols))) for k in ('dom', 'imp')}
        tau = np.ones((3, len(cols)))
        pv['dom'][0, [1, 2]] = [3.0, 1.0]
        held = {}
        rows = M.hold_energy_users(pv, tau, idx, {}, np.array([100.0, np.nan, np.nan]), np.zeros(3), np.zeros(3), held, cols,
                                   caps={('gas', 'msp'): 10.0})
        self.assertAlmostEqual(held[('dom', 0, 1)], 10.0)
        self.assertAlmostEqual(held[('dom', 0, 2)], 90.0)
        self.assertAlmostEqual(rows[0]['capped_musd'], 65.0)


class FuelSubsidyCapTest(unittest.TestCase):
    def test_rate_capped_at_rho_max(self):
        sectors = ['gas', 'mfr']
        idx = {c: i for i, c in enumerate(sectors)}
        cols = sectors + list(M.FD)
        pv = {k: np.zeros((2, len(cols))) for k in ('dom', 'imp')}
        pv['dom'][0, [1, cols.index('p')]] = [5.0, 5.0]
        tau = np.ones((2, len(cols))); tt = tau.copy()
        out = M.book_fuel_subsidies(pv, tau, tt, idx, cols, sectors, np.array([20.0, np.nan]), np.zeros(2), np.zeros(2),
                                    {'gas': 19.0}, rho_max=0.8)
        f = out['gas']
        self.assertAlmostEqual(f['rho'], 0.8)
        self.assertAlmostEqual(f['subsidy_musd'], 16.0)       # 0.8 of the held 20
        self.assertAlmostEqual(f['capped_musd'], 3.0)
        self.assertAlmostEqual(tau[0, 1], 0.2)
