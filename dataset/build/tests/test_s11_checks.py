"""Mutation tests for the S11 method, the S11 hard checks, the S11 screens and the config stop.

Every check is called on a good input (it must pass) and on a mutated input (it must fail).
The screens suite runs on a small fake build; each screen must report its mutation.

Run from dataset/build:  python3 -m unittest tests.test_s11_checks -v
"""
import csv
import json
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BUILD)

from s11_energy import checks as K  # noqa: E402
from s11_energy import config as C  # noqa: E402
from s11_energy import method as M  # noqa: E402
from s11_energy import domestic as DOM  # noqa: E402
import screens.s11_suite as suite  # noqa: E402


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
        bad = [self.rows[1:],                                                   # missing row
               self.rows + [dict(self.rows[0])],                                # duplicate
               self.rows + [dict(self.rows[0], choice='made_up')],              # unknown
               [dict(self.rows[0], value='other')] + self.rows[1:],             # value not implemented
               [dict(self.rows[0], decided_by='')] + self.rows[1:],             # unattributed
               [dict(self.rows[0], gtap_status='maybe')] + self.rows[1:]]       # status
        for rows in bad:
            self.write(rows)
            with self.assertRaises(C.ConfigError):
                C.load_choices(self.path)


# ------------------------------------------------------------------ method
class MethodTest(unittest.TestCase):
    def test_supply_use(self):
        p, m, x = np.array([10.0, 0, 5]), np.array([2.0, 0, 1]), np.array([20.0, 3, 4])
        p1, m1, x1, g, nos = M.supply_use(p, m, x)
        self.assertAlmostEqual(x1[0], p1[0] + m1[0])
        self.assertAlmostEqual(p1[0] * m1[0] / (p[0] * m[0]), 20 / 12)   # P and M x g each, g^2 = X/S
        self.assertEqual(x1[1], 0.0)
        self.assertTrue(nos[1])
        self.assertEqual((p1[2], m1[2], x1[2]), (5, 1, 4))               # feasible: untouched

    def test_reexports_keep_domestic_exports_below_production(self):
        p, m, x = np.array([10.0, 0, 5]), np.array([2.0, 4, 1]), np.array([11.0, 3, 4])
        x1, m1, rx = M.remove_reexports(p, m, x)
        self.assertTrue(np.all(x1 <= p + 1e-12))
        self.assertTrue(np.all(m1 >= -1e-12))
        np.testing.assert_allclose(rx, x * m / (p + m))
        x_bad, m_bad, _ = M.remove_reexports(p, m, np.array([30.0, 3, 4]))   # mutation: X > P + M
        self.assertTrue((m_bad < 0).any())

    def test_balance_with_bound(self):
        x, m, p = np.array([10.0, 5, 0]), np.array([2.0, 4, 12]), np.array([10.0, 50, 0])
        x2, m2, f, p2 = M.balance(x, m, p)
        self.assertAlmostEqual(x2.sum(), m2.sum(), places=9)
        self.assertTrue(np.all(x2 <= p2 * (1 + 1e-9)))
        self.assertGreater(p2[0], p[0])              # capped exporter: P rescaled up
        x3, _, _, _ = M.balance(x, m)
        self.assertGreater(x3[0], p[0])              # mutation: no bound, X above P

    def test_seed_and_ras(self):
        A0 = np.array([[0.0, 5, 0], [1, 0, 0], [0, 0, 0]])
        rows, cols = np.array([6.0, 2, 1]), np.array([2.0, 4, 3])
        A, sd = M.seed_matrix(A0, rows, cols, allow_diag=np.array([False, False, False]), eps=1e-6)
        self.assertTrue(np.all(np.diag(A) == 0))
        A1, it, err = M.ras(A, rows, cols)
        self.assertLess(err, 1e-9)
        np.testing.assert_allclose(A1.sum(1), rows, rtol=1e-8)
        _, _, err_bad = M.ras(np.eye(3), rows, cols, max_it=200)   # mutation: no off-diagonal support
        self.assertGreater(err_bad, 1e-6)

    def test_prices(self):
        p, filled, avg = M.fill_missing_prices(np.array([10.0, np.nan, 20]), np.array([True, True, False]))
        self.assertEqual(p[1], 15.0)
        self.assertTrue(filled[1] and not filled[2])
        R = ['A', 'B', 'C', 'D']
        z = {c: np.zeros(4) for c in DOM.COMMODITIES}
        px = {c: np.array([10.0, 12, 14, 16]) for c in DOM.COMMODITIES}
        pmb = {c: np.array([np.nan, 13, np.nan, 20]) for c in DOM.COMMODITIES}
        xv = dict(z, gas=np.array([5.0, 1, 3, 0]))
        mv = dict(z, gas=np.array([0.0, 2, 0, 1]))
        out = DOM.domestic_basic_prices(R, px, pmb, xv, mv, {('gas', 'A'): (7.0, 'hub')}, {('gas', 'C'): 4.0, ('gas', 'D'): 50.0})
        p, rule, det = out['gas']
        self.assertEqual(list(rule), ['source_data', 'import_basic_price', 'iea_price_gap', 'import_basic_price'])
        self.assertEqual(list(p[:3]), [7.0, 13.0, 10.0])
        self.assertIn('not used', det[3])                 # mutation: gap above the reference falls through
        p2, rule2, _ = DOM.domestic_basic_prices(R, px, pmb, xv, dict(mv, gas=np.zeros(4)), {}, {})['gas']
        self.assertTrue((rule2 == 'simple_average').all())  # nothing observed: GTAP fill
        # fill classes (§12.3.6): B and D are net energy importers, so a gap at A takes their average, not C's
        xv3, mv3 = dict(z, gas=np.array([5.0, 0, 0, 0])), dict(z, gas=np.array([0.0, 2, 0, 1]))
        src3 = {('gas', 'C'): (100.0, 'x')}
        p3, rule3, det3 = DOM.domestic_basic_prices(R, px, pmb, xv3, mv3, src3, {}, [True, False, True, False])['gas']
        self.assertEqual(p3[0], 100.0)                       # only net exporter observed is C
        p4, *_ = DOM.domestic_basic_prices(R, px, pmb, xv3, mv3, src3, {}, [False, False, True, False])['gas']
        self.assertAlmostEqual(p4[0], (13.0 + 20.0) / 2)     # mutation: A an importer takes the importer average
        # no trade: the gap is taken from the simple-average export price
        p5, rule5, _ = DOM.domestic_basic_prices(R, px, pmb, z, z, {}, {('gas', 'B'): 3.0})['gas']
        self.assertEqual((rule5[1], p5[1]), ('iea_price_gap', 13.0 - 3.0))
        self.assertAlmostEqual(DOM.basic_from_purchasers(230.0, 'gas'), 100.0)
        # §12.3.8 (David 20:13): a purchasers'-price source ranks after the import basic price of a net importer
        p6, rule6, _ = DOM.domestic_basic_prices(R, px, pmb, xv, mv, {('gas', 'B'): (5.0, 'eurostat', 'purchasers'),
                                                                     ('gas', 'A'): (7.0, 'hub', 'basic')}, {})['gas']
        self.assertEqual((rule6[1], p6[1]), ('import_basic_price', 13.0))
        self.assertEqual((rule6[0], p6[0]), ('source_data', 7.0))
        p7, rule7, _ = DOM.domestic_basic_prices(R, px, pmb, xv, mv, {}, {})['ely']
        self.assertNotIn('import_basic_price', list(rule7))   # §12.3.5: no import-price estimate for electricity
        self.assertAlmostEqual(DOM.usd_mmbtu_to_musd_bcm(1.0), 40.0 / 1.055056)
        gap = DOM.iea_gap_per_unit(['A', 'X'], {'A': ['A'], 'X': ['P', 'Q']}, {('gas', 'P'): 10.0},
                                   dict({c: np.zeros(2) for c in DOM.COMMODITIES}, gas=np.array([1.0, 4.0])), 0.9)
        self.assertEqual(gap, {('gas', 'X'): 10.0 * 0.9 / 4.0})

    def test_observed_gas_prices(self):
        # A ships 100 USD m to C on tonnes worth 0.2 bcm against 1.0 bcm exports; B and A share a route to C
        baci = pd.DataFrame(dict(exp=['A', 'A', 'B', 'C'], imp=['C', 'B', 'C', 'C'], v=[100000.0, 20000, 50000, 999],
                                 q=[150000.0, np.nan, 40000, 1]))
        R = ['A', 'B', 'C']
        gt = M.gas_tonnes_screen(baci, R, np.array([1.0, np.nan, 0.0]), 1.36)
        self.assertAlmostEqual(gt.loc[0, 'baci_value_musd'], 120.0)        # diagonal C->C left out
        self.assertAlmostEqual(gt.loc[0, 'bcm_ratio'], 0.15 * 1.36)
        self.assertTrue(np.isnan(gt.loc[1, 'bcm_ratio']) and np.isnan(gt.loc[2, 'bcm_ratio']))
        rows = [dict(region='A', method='baci_value_over_volume_source_exports', route_exporters='', route_importer=''),
                dict(region='B', method='baci_route_value_over_ei_route_volume', route_exporters='A;B', route_importer='C')]
        obs = M.observed_gas_export_prices(baci, rows, R, np.array([1.0, 0.5, 0.0]), {('A;B', 'C'): 0.6})
        self.assertAlmostEqual(obs['A']['price'], 120.0)                     # all of A's flows over its exports
        self.assertAlmostEqual(obs['B']['price'], 150.0 / 0.6)               # A->C + B->C over the route volume
        px = np.array([obs['A']['price'], obs['B']['price'], 7.0])
        self.assertEqual(K.observed_gas_prices(px, R, obs)[0], 0)
        self.assertEqual(K.observed_gas_prices(px * 1.01, R, obs)[0], 2)     # mutation: price not the observed one
        for bad in (dict(rows[1], route_exporters='A'), dict(rows[0], method='guess')):
            with self.assertRaises(SystemExit):                              # mutation: own route missing, unknown method
                M.observed_gas_export_prices(baci, [bad], R, np.array([1.0, 0.5, 0.0]), {('A', 'C'): 0.6})
        with self.assertRaises(SystemExit):                                  # mutation: no volume
            M.observed_gas_export_prices(baci, rows[:1], R, np.array([0.0, 0.5, 0.0]), {})

    def test_ninety_pct_both(self):
        # industry 1 (pet) uses domestic product 0 (crude): 80 of revenue 50 -> raise pet, lower crude
        rev_dom, rev_x = np.array([100.0, 50.0]), np.array([0.0, 0.0])
        fixed = np.array([0.0, 0.0])
        dom_in = np.array([[0.0, 80.0], [0.0, 0.0]])
        pi, _ = M.ninety_pct_both(rev_dom, rev_x, fixed, dom_in, np.arange(2))
        cost = fixed + dom_in.T @ pi
        self.assertTrue(np.all(cost <= 0.9 * (rev_x + pi * rev_dom) + 1e-7))
        self.assertGreater(pi[1], 1.0)
        self.assertLess(pi[0], 1.0)                      # GTAP p.29: input prices may fall
        up, _ = M.ninety_pct(rev_dom, rev_x, fixed, dom_in, np.arange(2))
        self.assertLess(rev_dom @ (pi - 1) ** 2, rev_dom @ (up - 1) ** 2)   # smaller change than upward-only
        same, it = M.ninety_pct_both(rev_dom, rev_x, fixed, dom_in * 0.1, np.arange(2))
        self.assertTrue(np.allclose(same, 1.0) and it == 0)                   # rule holds: nothing moves
        bad, _ = M.ninety_pct_both(np.array([10.0]), np.array([0.0]), np.array([0.0]), np.array([[20.0]]), np.arange(1))
        self.assertFalse(np.isfinite(bad[0]))            # own use above 90 percent: infeasible, reported

    def test_ninety_pct(self):
        rev_dom, rev_x = np.array([100.0, 50]), np.array([0.0, 10])
        fixed = np.array([85.0, 5])
        dom_in = np.array([[10.0, 0], [0, 5]])
        pi, _ = M.ninety_pct(rev_dom, rev_x, fixed, dom_in, np.arange(2))
        cost = fixed + dom_in.T @ pi
        self.assertTrue(np.all(cost <= 0.9 * (rev_x + pi * rev_dom) + 1e-9))
        self.assertGreater(pi[0], 1.0)
        self.assertEqual(pi[1], 1.0)
        pi_bad, _ = M.ninety_pct(np.array([10.0]), np.array([0.0]), np.array([0.0]), np.array([[20.0]]), np.arange(1))
        self.assertFalse(np.isfinite(pi_bad[0]))     # own use above 90 percent of revenue: no solution


# ------------------------------------------------------------------ B06 split and io checks
def toy_io():
    cols = ['crp', 'coa', 'B06', 'pet', 'p', 'X', 'stock_gap', 'OUT']
    rows = {'dom_crp': [5, 1, 1, 2, 10, 1, 0, 20], 'dom_coa': [1, 1, 1, 1, 1, 0, 0, 5],
            'dom_B06': [1, 1, 4, 30, 2, 12, 0, 50], 'dom_pet': [2, 1, 2, 3, 5, 2, 0, 15],
            'imp_crp': [1, 0, 0, 0, 1, 0, 0, 0], 'imp_coa': [0, 0, 0, 0, 0, 0, 0, 0],
            'imp_B06': [0, 0, 1, 6, 1, 0, 0, 0], 'imp_pet': [0, 0, 1, 1, 1, 0, 0, 0],
            'TLS': [1, 0, 1, 1, 0, 0, 0, 0], 'VA': [9, 1, 39, 6, 0, 0, 0, 0]}
    df = pd.DataFrame(rows, index=cols).T.astype(float)
    df.loc['OUT'] = df.drop(index=[]).sum()
    df.loc['OUT', 'OUT'] = 0.0
    df.loc['OUT', ['p', 'X', 'stock_gap']] = 0.0
    df.index.name = 'row'
    return df


class B06Test(unittest.TestCase):
    def setUp(self):
        blk = toy_io()
        out, self.info = M.split_b06(blk, 30.0, 10.0, 8.0, 4.0, 5.0, 2.0)
        io10 = blk.reset_index()
        io10.insert(0, 'region', 'AAA')
        io11 = out.reset_index().rename(columns={'index': 'row'})
        io11.insert(0, 'region', 'AAA')
        self.io10, self.io11 = io10, io11

    def test_identity_holds(self):
        r = K.b06_identity(self.io10, self.io11)
        self.assertLess(r['max_gap'], 1e-9)
        self.assertEqual(r['negative'], 0)
        self.assertEqual(K.io_unchanged_outside_b06(self.io10, self.io11), 0)

    def test_gas_to_pet_from_data(self):
        blk = toy_io()
        # dom row inner sum 38, oil share 0.75: oil 28.5; old rule puts 28.5 of the 30 pet cell to oil, gas 1.5
        old, _ = M.split_b06(blk, 30.0, 10.0, 8.0, 4.0, 5.0, 2.0)
        self.assertAlmostEqual(old.loc['dom_gas', 'pet'], 1.5)
        new, info = M.split_b06(blk, 30.0, 10.0, 8.0, 4.0, 5.0, 2.0, gas_pet={'dom': 0.5, 'imp': 9.0})
        # a share, not a value: 0.5 / 10 of the final io gas row. The pet cell (30) exceeds oil's row
        # share (28.5), so oil keeps 30 - g and the final gas row is 38 - 30 + g: g = 0.05 * 8 / 0.95
        self.assertAlmostEqual(new.loc['dom_gas', 'pet'], 0.05 * 8.0 / 0.95)
        gas_row = new.loc['dom_gas'].drop(['OUT', 'X']).sum()
        self.assertAlmostEqual(new.loc['dom_gas', 'pet'] / gas_row, 0.05)
        self.assertTrue(info['gas_pet_capped_imp'] or new.loc['imp_gas', 'pet'] == info['gas_row_io_imp'])
        B = pd.DataFrame([dict(region='AAA', **info)])
        self.assertEqual(K.gas_pet_share(B)[0], 0)
        B.loc[0, 'gas_pet_io_dom'] *= 2.0
        self.assertEqual(K.gas_pet_share(B)[0], 1)
        self.assertGreaterEqual(new.loc['dom_gas'].drop('OUT').min(), 0.0)
        io10 = blk.reset_index(); io10.insert(0, 'region', 'AAA')
        io11 = new.reset_index().rename(columns={'index': 'row'}); io11.insert(0, 'region', 'AAA')
        self.assertLess(K.b06_identity(io10, io11)['max_gap'], 1e-9)

    def test_mutations(self):
        bad = self.io11.copy()
        bad.loc[bad['row'] == 'dom_oil', 'crp'] += 0.5
        self.assertGreater(K.b06_identity(self.io10, bad)['max_gap'], 1e-6)
        bad = self.io11.copy()
        bad.loc[bad['row'] == 'VA', 'oil'] += 1.0
        self.assertGreater(K.b06_identity(self.io10, bad)['max_gap'], 1e-6)
        bad = self.io11.copy()
        bad.loc[bad['row'] == 'dom_oil', 'p'] = -1.0
        bad.loc[bad['row'] == 'dom_gas', 'p'] += 1.0 + float(self.io11.loc[self.io11['row'] == 'dom_oil', 'p'].iloc[0])
        self.assertGreater(K.b06_identity(self.io10, bad)['negative'], 0)
        bad = self.io11.copy()
        bad.loc[bad['row'] == 'dom_crp', 'crp'] += 1e-6
        self.assertEqual(K.io_unchanged_outside_b06(self.io10, bad), 1)


# ------------------------------------------------------------------ fix round 2026-10-24 (A8, A9, A10, B9)
class FixRoundTest(unittest.TestCase):
    ITEMS = {'u': dict(value='76.09', unit='USD/bbl', fx_iso3=''), 'm': dict(value='1.25', unit='USD/MMBtu', fx_iso3=''),
             'c': dict(value='1642', unit='LCU/t', fx_iso3='IND'), 'lo': dict(value='37000', unit='USD million', fx_iso3=''),
             'hi': dict(value='48000', unit='USD million', fx_iso3=''), 'q': dict(value='484', unit='bcm', fx_iso3='')}

    def test_transcribed_prices(self):
        T = DOM.transcribed_price
        self.assertEqual(T('oil', 'item:u', self.ITEMS, {})[0], 76.09)
        self.assertAlmostEqual(T('gas', 'item:m', self.ITEMS, {})[0], DOM.usd_mmbtu_to_musd_bcm(1.25))
        self.assertAlmostEqual(T('coa', 'item:c', self.ITEMS, {'IND': 78.6044905829915})[0], 1642 / 78.6044905829915)
        self.assertAlmostEqual(T('coa', 'item:c', self.ITEMS, {'IND': 78.6044905829915})[0], 20.889, places=3)
        self.assertAlmostEqual(T('gas', 'midpoint_value_over_volume:lo;hi:q', self.ITEMS, {})[0], 42500.0 / 484)
        bad = [('gas', 'item:u', {}),                                   # a crude unit on a gas row
               ('oil', 'item:nope', {}),                                # no such item
               ('coa', 'item:c', {}),                                   # no exchange rate
               ('gas', 'midpoint_value_over_volume:hi;lo:q', {}),       # low above high
               ('gas', 'average:lo;hi:q', {}),                          # unknown form
               ('gas', 'item:lo', {})]                                  # a value, not a price
        for c, s, fx in bad:
            with self.assertRaises(SystemExit):
                T(c, s, self.ITEMS, fx)

    def setUp(self):
        self.R = ['A', 'B', 'C', 'D']
        z = {c: np.zeros(4) for c in DOM.COMMODITIES}
        self.px = {c: np.array([50.0, 60.0, 70.0, 80.0]) for c in DOM.COMMODITIES}
        self.pmb = {c: np.array([200.0, np.nan, np.nan, 100.0]) for c in DOM.COMMODITIES}
        self.xv = dict(z, coa=np.array([0.0, 5.0, 1.0, 0.0]), gas=np.array([0.0, 5.0, 1.0, 0.0]), ely=np.array([0.0, 5.0, 1.0, 0.0]))
        self.mv = dict(z, coa=np.array([3.0, 0.0, 0.0, 2.0]), gas=np.array([3.0, 0.0, 0.0, 2.0]), ely=np.array([3.0, 0.0, 0.0, 2.0]))
        self.src = {('coa', 'D'): (90.0, 'mine'), ('gas', 'C'): (500.0, 'hub')}

    def run_order(self, **kw):
        return DOM.domestic_basic_prices(self.R, self.px, self.pmb, self.xv, self.mv, self.src, {}, None, **kw)

    def test_lignite_rule(self):
        share = np.array([0.5, 0.0, 0.0, 1.0])
        p0 = self.run_order()['coa'][0]
        p, rule, det = self.run_order(lignite=dict(share=share, price=24.0))['coa']
        self.assertAlmostEqual(p[0], 0.5 * 200.0 + 0.5 * 24.0)     # import basic price on the hard-coal half
        self.assertEqual(rule[0], 'import_basic_price' + DOM.LIGNITE_SUFFIX)
        self.assertEqual(p[3], 90.0)                               # its own source price: no lignite rule
        self.assertEqual(list(p[1:3]), list(p0[1:3]))              # no brown coal: unchanged
        self.assertEqual(list(self.run_order(lignite=None)['coa'][0]), list(p0))   # switched off: unchanged
        self.assertEqual(list(self.run_order(lignite=dict(share=share, price=24.0))['gas'][0]), list(self.run_order()['gas'][0]))
        shares = DOM.brown_coal_share(['X', 'Y', 'Z'], {'a': 'X', 'b': 'X', 'c': 'Y'},
                                      {('a', '0100'): 30.0, ('a', '0200'): 10.0, ('b', '0200'): 60.0, ('c', '0100'): 5.0})
        self.assertEqual(list(shares), [0.7, 0.0, 0.0])            # composite X sums its members

    def test_exporter_cap(self):
        p0, r0, _ = self.run_order()['coa']
        p, rule, det = self.run_order(export_cap=True)['coa']
        self.assertGreater(p0[1], self.px['coa'][1])                 # B: net exporter at a class average above its export price
        self.assertEqual(p[1], self.px['coa'][1])
        self.assertTrue(rule[1].endswith(DOM.CAP_SUFFIX))
        self.assertEqual(p[0], p0[0])                               # A: net importer, not capped
        pg, rg, _ = self.run_order(export_cap=True)['gas']
        self.assertEqual((pg[2], rg[2]), (500.0, 'source_data'))    # C: source data above its export price stays
        pe, re_, _ = self.run_order(export_cap=True)['ely']
        self.assertFalse(any(x.endswith(DOM.CAP_SUFFIX) for x in re_))   # electricity is outside the rule

    def test_switchable_choices(self):
        with open(C.CHOICES_PATH, newline='') as fh:
            rows = list(csv.DictReader(fh))
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, 'c.csv')

            def write(rs):
                with open(path, 'w', newline='') as fh:
                    w = csv.DictWriter(fh, fieldnames=C.CHOICE_COLUMNS)
                    w.writeheader()
                    w.writerows(rs)
            off = [dict(r, value='off') if r['choice'] in ('lignite_price', 'exporter_price_cap') else r for r in rows]
            write(off)
            ch = C.load_choices(path)
            self.assertFalse(C.switched_on(ch, 'lignite_price') or C.switched_on(ch, 'exporter_price_cap'))
            self.assertTrue(C.switched_on(C.load_choices(), 'lignite_price'))
            write([dict(r, value='off') if r['choice'] == 'crude_price' else r for r in rows])   # not a switch
            with self.assertRaises(C.ConfigError):
                C.load_choices(path)
        finally:
            shutil.rmtree(tmp)

    def test_crude_only_to_refining_and_listed_users(self):
        blk = toy_io()
        blk.loc['dom_B06', 'pet'] = 10.0         # a refinery cell below the oil share of the row
        users = {'coa': 0.1}                     # the energy balance lists coal mines as a crude user, 10 percent of absorption
        out, info = M.split_b06(blk, 30.0, 10.0, 8.0, 4.0, 5.0, 2.0, gas_pet={'dom': 0.5, 'imp': 0.5}, oil_users=users)
        oil_dom = 0.75 * blk.loc['dom_B06', ['crp', 'coa', 'B06', 'pet', 'p']].sum()
        self.assertAlmostEqual(out.loc['dom_oil', 'coa'], min(1.0, 0.1 * oil_dom))
        for c in ('crp', 'p'):                   # not listed: all gas
            self.assertEqual(out.loc['dom_oil', c], 0.0)
            self.assertEqual(out.loc['dom_gas', c], blk.loc['dom_B06', c])
        self.assertAlmostEqual(out.loc['dom_oil', 'pet'] + out.loc['dom_gas', 'pet'], 10.0)
        gas_row = out.loc['dom_gas', ['crp', 'coa', 'oil', 'gas', 'pet', 'p']].sum()
        self.assertAlmostEqual(out.loc['dom_gas', 'pet'] / gas_row, 0.5 / 10.0)      # refinery gas keeps its measured share
        io10 = blk.reset_index(); io10.insert(0, 'region', 'AAA')
        io11 = out.reset_index().rename(columns={'index': 'row'}); io11.insert(0, 'region', 'AAA')
        self.assertLess(K.b06_identity(io10, io11)['max_gap'], 1e-9)
        self.assertEqual(K.crude_users(io11, {'AAA': users}, ['AAA'])[0], 0)
        self.assertGreater(info['oil_share_to_gas_dom'], 0.0)
        self.assertGreater(K.crude_users(io11, {'AAA': {}}, ['AAA'])[0], 0)      # mutation: coa not listed
        old, _ = M.split_b06(blk, 30.0, 10.0, 8.0, 4.0, 5.0, 2.0, gas_pet={'dom': 0.5, 'imp': 0.5})
        o11 = old.reset_index().rename(columns={'index': 'row'}); o11.insert(0, 'region', 'AAA')
        self.assertGreater(K.crude_users(o11, {'AAA': users}, ['AAA'])[0], 0)    # the old pro-rata rule fails the check

    def test_vpv_source(self):
        V = pd.DataFrame([dict(region='A', commodity='oil', exports=100.0, export_price=90.0, export_value=9000.0),
                          dict(region='B', commodity='oil', exports=50.0, export_price=100.0, export_value=5000.0),
                          dict(region='A', commodity='pet', exports=10.0, export_price=110.0, export_value=1100.0)])
        t = {'oil': 0.1364, 'pet': 1 / 7.33}
        # BACI: A crude 9 bn for 100 million bbl, B 5 bn for 50 million bbl, A products 1.1 bn for 10 million bbl
        B = pd.DataFrame([dict(exp='A', k='270900', v=9.0e6, q=100e6 * 0.1364), dict(exp='B', k='270900', v=5.0e6, q=50e6 * 0.1364),
                          dict(exp='A', k='271000', v=1.1e6, q=10e6 / 7.33)])
        self.assertTrue(K.vpv_source(V, B, t)['ok'])
        V2 = V.copy()
        V2.loc[0, 'export_price'] *= 3.0                     # mutation: A's crude price three times its unit value
        V2.loc[0, 'export_value'] *= 3.0
        self.assertFalse(K.vpv_source(V2, B, t)['ok'])
        self.assertFalse(K.vpv_source(V, B[B['k'] == '270900'], t)['ok'])     # no product unit value
        V3 = V.copy()
        V3.loc[1, 'export_price'] *= 2.1                     # B's crude 2.1 x its unit value
        V3.loc[1, 'export_value'] *= 2.1
        V3.loc[0, 'export_price'] *= 0.75                    # A's lower, so the world ratio stays inside 0.8-1.25
        V3.loc[0, 'export_value'] *= 0.75
        self.assertFalse(K.vpv_source(V3, B, t)['ok'])
        r = K.vpv_source(V3, B, t, reviewed={('B', 'oil')})    # beta v4 dry run 3: a reviewed BACI quantity is reported, not failed
        self.assertTrue(r['ok'])
        self.assertIn('reviewed', r['detail'])

    def test_energy_use_caps(self):
        V = pd.DataFrame([dict(region='A', commodity='oil', domestic_sales=30.0, imports=10.0, domestic_price=80.0, import_basic_price=100.0),
                          dict(region='B', commodity='oil', domestic_sales=5.0, imports=0.0, domestic_price=70.0, import_basic_price=np.nan)])
        caps = M.energy_use_caps(V, ['A', 'B'], {'A': 20.0, 'B': 0.0}, {'A': 'jodi_refinobs', 'B': 's11_crude_use'},
                                 {'a': 'A', 'b1': 'B', 'b2': 'B'}, {'a': 10.0, 'b1': 1.0, 'b2': 2.0}, {'a': 100.0, 'b1': 10.0, 'b2': 20.0})
        a, b = caps.set_index('region').loc['A'], caps.set_index('region').loc['B']
        self.assertAlmostEqual(a['intake_value_dom_musd'], 20.0 * 0.75 * 80.0)
        self.assertAlmostEqual(a['intake_value_imp_musd'], 20.0 * 0.25 * 100.0)
        self.assertTrue(a['intake_measured'])
        self.assertFalse(b['intake_measured'])            # zero from a blank source is not a measurement
        self.assertAlmostEqual(a['gas_own_use_share'], 0.1)
        self.assertAlmostEqual(b['gas_own_use_share'], 0.1)  # members summed

    def test_own_use_shares(self):
        """Fix round wG: (own use + losses) / production by region, members summed, the median where UNSD has none."""
        V = pd.DataFrame([dict(region=r, commodity=c, output_value=v) for r, c, v in
                          (('A', 'ely', 100.0), ('B', 'ely', 50.0), ('C', 'ely', 20.0), ('D', 'ely', 0.0),
                           ('A', 'coa', 10.0), ('B', 'coa', 0.0), ('C', 'coa', 0.0), ('D', 'coa', 0.0))])
        unsd = {'ely': {'a': dict(own=5.0, losses=5.0, production=100.0), 'b1': dict(own=1.0, losses=0.0, production=10.0),
                        'b2': dict(own=0.0, losses=2.0, production=10.0)},
                'coa': {'a': dict(own=0.0, losses=0.0, production=7.0)}}
        OU = M.own_use_shares(V, ['A', 'B', 'C', 'D'], {'a': 'A', 'b1': 'B', 'b2': 'B'}, unsd, goods=('coa', 'ely'))
        o = OU.set_index(['region', 'commodity'])
        self.assertAlmostEqual(o.loc[('A', 'ely'), 'own_use_share'], 0.1)
        self.assertAlmostEqual(o.loc[('B', 'ely'), 'own_use_share'], 0.15)          # members summed
        self.assertEqual(o.loc[('C', 'ely'), 'basis'], 'median_of_reporters')
        self.assertAlmostEqual(o.loc[('C', 'ely'), 'own_use_share'], 0.125)
        self.assertAlmostEqual(o.loc[('C', 'ely'), 'own_use_value_musd'], 2.5)
        self.assertEqual(o.loc[('D', 'ely'), 'basis'], 'no_output')
        self.assertAlmostEqual(o.loc[('A', 'coa'), 'own_use_share'], 0.0)
        self.assertEqual(K.own_use_shares_ok(OU, V, goods=('coa', 'ely'))[0], 0)
        bad = OU.copy()
        bad.loc[(bad.region == 'A') & (bad.commodity == 'ely'), 'own_use_share'] = 1.5      # mutation: share above 1
        self.assertGreater(K.own_use_shares_ok(bad, V, goods=('coa', 'ely'))[0], 0)
        self.assertGreater(K.own_use_shares_ok(OU[OU.region != 'B'], V, goods=('coa', 'ely'))[0], 0)    # a region missing
        bad = OU.copy()
        bad.loc[(bad.region == 'C') & (bad.commodity == 'ely'), 'own_use_value_musd'] = 9.0  # mutation: value off the share
        self.assertGreater(K.own_use_shares_ok(bad, V, goods=('coa', 'ely'))[0], 0)


class FuelSubsidyTest(unittest.TestCase):
    """Fix-round B15 (GTAP's booking, Chepeliev et al. 2018 §3): an IEA-gap region takes the reference price and the gap
    is a consumption subsidy (fuel_subsidy_rows, S11-Hsubsidy)."""

    def setUp(self):
        self.R = ['A', 'B', 'C', 'D']
        z = {c: np.zeros(4) for c in DOM.COMMODITIES}
        self.px = {c: np.array([10.0, 12, 14, 16]) for c in DOM.COMMODITIES}
        self.pmb = {c: np.array([np.nan, 13, np.nan, 20]) for c in DOM.COMMODITIES}
        self.xv = dict(z, gas=np.array([5.0, 1, 3, 0]))
        self.mv = dict(z, gas=np.array([0.0, 2, 0, 1]))
        # B a net importer (reference = import basic price 13), C an exporter (14), A no gap; D's gap is above its reference
        self.gap = {('gas', 'B'): 3.0, ('gas', 'C'): 4.0, ('gas', 'D'): 50.0}
        self.cons = dict(z, gas=np.array([1.0, 10.0, 20.0, 5.0]))

    def prices(self, book):
        return DOM.domestic_basic_prices(self.R, self.px, self.pmb, self.xv, self.mv, {('gas', 'A'): (7.0, 'hub')}, self.gap,
                                         book_subsidy=book)

    def rows(self, out):
        return DOM.fuel_subsidy_rows(self.R, self.px, self.pmb, self.xv, self.mv, self.gap, self.cons,
                                     {c: out[c][1] for c in out}, {c: out[c][0] for c in out})

    def test_reference_price_and_subsidy(self):
        on, off = self.prices(True), self.prices(False)
        p, rule, det = on['gas']
        self.assertEqual(list(rule[:3]), ['source_data', 'iea_price_gap', 'iea_price_gap'])
        self.assertEqual((p[1], p[2]), (13.0, 14.0))                    # the reference, not reference less gap
        self.assertEqual((off['gas'][0][1], off['gas'][0][2]), (10.0, 10.0))   # off: the pre-B15 rule
        self.assertIn('booked as a consumption subsidy', det[2])
        rows = {x['region']: x for x in self.rows(on)}
        self.assertEqual(sorted(rows), ['B', 'C'])                       # D's gap is not used, A is source data
        self.assertEqual((rows['B']['reference_basis'], rows['C']['reference_basis']), ('import_basic_price', 'export_price'))
        self.assertAlmostEqual(rows['B']['subsidy_musd'], (13.0 - 10.0) * 10.0)
        self.assertAlmostEqual(rows['C']['subsidy_musd'], 4.0 * 20.0)
        self.assertAlmostEqual(rows['C']['consumer_price'], 10.0)
        n, det = K.fuel_subsidy_check(self.rows(on), {c: on[c][1] for c in on}, self.R)
        self.assertEqual(n, 0, det)

    def test_no_trade_reference(self):
        z = {c: np.zeros(4) for c in DOM.COMMODITIES}
        out = DOM.domestic_basic_prices(self.R, self.px, self.pmb, z, z, {}, {('gas', 'B'): 3.0}, book_subsidy=True)
        self.assertEqual((out['gas'][1][1], out['gas'][0][1]), ('iea_price_gap', 13.0))   # exporters' simple average of 10..16
        r = DOM.fuel_subsidy_rows(self.R, self.px, self.pmb, z, z, {('gas', 'B'): 3.0}, self.cons, {c: out[c][1] for c in out},
                                  {c: out[c][0] for c in out})
        self.assertEqual(r[0]['reference_basis'], 'exporters_simple_average_export_price')

    def test_volume_is_the_smaller_of_consumption_and_absorption(self):
        on = self.prices(True)
        absorb = {c: np.full(4, 8.0) for c in DOM.COMMODITIES}
        rows = {x['region']: x for x in DOM.fuel_subsidy_rows(self.R, self.px, self.pmb, self.xv, self.mv, self.gap, self.cons,
                                                               {c: on[c][1] for c in on}, {c: on[c][0] for c in on}, absorption=absorb)}
        self.assertEqual((rows['B']['domestic_use'], rows['B']['domestic_use_basis']), (8.0, 's11_absorption'))   # 10 > 8: GTAP volume
        self.assertAlmostEqual(rows['B']['subsidy_musd'], 3.0 * 8.0)
        self.assertEqual((rows['C']['domestic_use'], rows['C']['domestic_use_basis']), (8.0, 's11_absorption'))
        small = {c: np.full(4, 50.0) for c in DOM.COMMODITIES}
        rows2 = DOM.fuel_subsidy_rows(self.R, self.px, self.pmb, self.xv, self.mv, self.gap, self.cons,
                                      {c: on[c][1] for c in on}, {c: on[c][0] for c in on}, absorption=small)
        self.assertEqual({x['domestic_use_basis'] for x in rows2}, {'consumption'})                               # IEA value kept
        self.assertEqual(K.fuel_subsidy_check(list(rows.values()), {c: on[c][1] for c in on}, self.R)[0], 0)

    def test_check_mutations(self):
        on = self.prices(True)
        rule = {c: on[c][1] for c in on}
        good = self.rows(on)
        for mutate in (lambda x: x.update(subsidy_musd=x['subsidy_musd'] * 1.01),          # value off the identity
                       lambda x: x.update(consumer_price=x['consumer_price'] + 1.0, subsidy_musd=(x['reference_price'] - x['consumer_price'] - 1.0) * x['domestic_use']),
                       lambda x: x.update(domestic_price_before_90pct=x['consumer_price'])):   # the gap left in the basic price
            rows = [dict(x) for x in good]
            mutate(rows[0])
            self.assertGreater(K.fuel_subsidy_check(rows, rule, self.R)[0], 0)
        self.assertGreater(K.fuel_subsidy_check(good[1:], rule, self.R)[0], 0)   # an IEA-gap row with no subsidy row
        off = self.prices(False)
        self.assertGreater(K.fuel_subsidy_check(self.rows(off), {c: off[c][1] for c in off}, self.R)[0], 0)  # pre-B15 prices fail
        lig = dict(good[0], domestic_price_rule='iea_price_gap+lignite', domestic_price_before_90pct=1.0)
        self.assertEqual(K.fuel_subsidy_check([lig] + good[1:], rule, self.R)[0], 0)   # the lignite blend is allowed

    def test_choice_switch(self):
        self.assertTrue(C.switched_on(C.load_choices(), 'fuel_subsidies'))
        self.assertIn('off', C.ALTERNATIVES['fuel_subsidies'])



class FuelSubsidyExtensionTest(unittest.TestCase):
    """Fix-round B15 extension (David 2026-10-24, "stick to GTAP"; Chepeliev et al. 2018 §3.2 steps 1-2): an IEA subsidy is
    booked also where the S11 price is not the IEA gap (source data, a gap not used, no consumption volume). These tests run
    the w10 add-on-top rule (DOM.SUBSIDY_ADD_ON_TOP, kept as an alternative); FuelSubsidyPriceGapTest runs the fix-round wA rule."""

    def setUp(self):
        self.R = ['A', 'B', 'C', 'D']
        z = {c: np.zeros(4) for c in DOM.COMMODITIES}
        self.px = {c: np.array([10.0, 12, 14, 16]) for c in DOM.COMMODITIES}
        self.pmb = {c: np.array([np.nan, 13, np.nan, 20]) for c in DOM.COMMODITIES}
        self.xv = dict(z, gas=np.array([5.0, 1, 3, 0]))
        self.mv = dict(z, gas=np.array([0.0, 2, 0, 1]))
        self.gap = {('gas', 'A'): 2.0, ('gas', 'B'): 3.0, ('gas', 'C'): 4.0, ('gas', 'D'): 50.0}
        self.cons = dict(z, gas=np.array([4.0, 10.0, 20.0, 5.0]))
        self.absorb = {c: np.full(4, 100.0) for c in DOM.COMMODITIES}
        # IEA values at 2022 prices: gap x consumption where a consumption volume exists
        self.val = {(c, r): self.gap[(c, r)] * self.cons[c][i] for (c, r) in self.gap for i in [self.R.index(r)]}

    def build(self, val=None, mv=None, cons=None):
        mv = mv or self.mv
        cons = cons or self.cons
        out = DOM.domestic_basic_prices(self.R, self.px, self.pmb, self.xv, mv, {('gas', 'A'): (7.0, 'hub')}, self.gap, book_subsidy=True)
        price = {c: out[c][0].copy() for c in out}
        rule = {c: out[c][1].copy() for c in out}
        det = {c: out[c][2].copy() for c in out}
        before = {c: price[c].copy() for c in price}
        rows = DOM.fuel_subsidy_rows(self.R, self.px, self.pmb, self.xv, mv, self.gap, cons, rule, price,
                                     absorption=self.absorb, iea_value=self.val if val is None else val,
                                     mode=DOM.SUBSIDY_ADD_ON_TOP)
        DOM.apply_subsidy_prices(rows, self.R, price, rule, det)
        return rows, price, rule, det, before

    def test_source_and_unused_gap_rows_book_the_iea_value(self):
        rows, price, rule, det, before = self.build()
        x = {r['region']: r for r in rows}
        self.assertEqual(sorted(x), ['A', 'B', 'C', 'D'])
        a = x['A']                                                   # source data: the hub price is the consumer price
        self.assertEqual((a['source_rule'], a['consumer_price'], a['subsidy_per_unit']), ('source_data_gap_not_used', 7.0, 2.0))
        self.assertAlmostEqual(a['market_price'], 9.0)                # PM1 = PM0 + VS/ED, not the reference 10
        self.assertAlmostEqual(a['subsidy_musd'], 8.0)                # the IEA value, not the price gap
        self.assertAlmostEqual(a['price_gap_subsidy_musd'], (10.0 - 7.0) * 4.0)   # reported beside it
        self.assertEqual((price['gas'][0], rule['gas'][0]), (9.0, 'source_data' + DOM.SUBSIDY_SUFFIX))
        self.assertIn('booked as a consumption subsidy', det['gas'][0])
        d = x['D']                                                   # gap 50 above the reference 20: not used for the price
        self.assertEqual((before['gas'][3], d['consumer_price'], d['step2_rescaled']), (20.0, 20.0, False))   # imports 1 of 5
        self.assertAlmostEqual(d['subsidy_musd'], 250.0)
        self.assertAlmostEqual(d['market_price'], 70.0)
        self.assertEqual((x['B']['source_rule'], x['B']['market_price']), ('iea_price_gap', 13.0))   # B15 rows unchanged
        self.assertEqual(K.fuel_subsidy_check(rows, rule, self.R, price=price, mode=DOM.SUBSIDY_ADD_ON_TOP)[0], 0)

    def test_step2_rescales_where_imports_exceed_half(self):
        mv = dict(self.mv, gas=np.array([0.0, 2, 0, 4]))             # D imports 4 of a use of 5
        rows, price, rule, _, _ = self.build(mv=mv)
        d = [r for r in rows if r['region'] == 'D'][0]
        self.assertTrue(d['step2_rescaled'])
        self.assertAlmostEqual(d['subsidy_per_unit'], 20.0)           # the import basic price as the supply cost
        self.assertAlmostEqual(d['subsidy_musd'], 100.0)
        self.assertEqual(K.fuel_subsidy_check(rows, rule, self.R, price=price, mode=DOM.SUBSIDY_ADD_ON_TOP)[0], 0)

    def test_no_consumption_volume_uses_absorption(self):
        cons = dict(self.cons, gas=np.array([0.0, 10.0, 20.0, 5.0]))
        rows, *_ = self.build(val={**self.val, ('gas', 'A'): 50.0}, cons=cons)
        a = [r for r in rows if r['region'] == 'A'][0]
        self.assertEqual(a['domestic_use_basis'], 's11_absorption_no_consumption_volume')
        self.assertAlmostEqual(a['subsidy_per_unit'], 0.5)
        self.assertAlmostEqual(a['subsidy_musd'], 50.0)

    def test_gap_rows_only_without_iea_value(self):
        out = DOM.domestic_basic_prices(self.R, self.px, self.pmb, self.xv, self.mv, {('gas', 'A'): (7.0, 'hub')}, self.gap, book_subsidy=True)
        rows = DOM.fuel_subsidy_rows(self.R, self.px, self.pmb, self.xv, self.mv, self.gap, self.cons, {c: out[c][1] for c in out},
                                     {c: out[c][0] for c in out}, absorption=self.absorb)
        self.assertEqual(sorted(r['region'] for r in rows), ['B', 'C'])

    def test_check_mutations(self):
        rows, price, rule, _, before = self.build()
        n0 = K.fuel_subsidy_check(rows, rule, self.R, price=price, mode=DOM.SUBSIDY_ADD_ON_TOP)[0]
        self.assertEqual(n0, 0)
        ia = [i for i, r in enumerate(rows) if r['region'] == 'A'][0]
        muts = (lambda x: x.update(subsidy_musd=x['price_gap_subsidy_musd']),                 # the price gap booked, not the IEA value
                lambda x: x.update(subsidy_per_unit=3.0, market_price=10.0, subsidy_musd=12.0, domestic_price_before_90pct=10.0),  # above the IEA value
                lambda x: x.update(step2_rescaled=True),                                       # step 2 without its conditions
                lambda x: x.update(consumer_price=8.0))                                        # off the identity
        for mutate in muts:
            bad = [dict(r) for r in rows]
            mutate(bad[ia])
            self.assertGreater(K.fuel_subsidy_check(bad, rule, self.R, price=price, mode=DOM.SUBSIDY_ADD_ON_TOP)[0], 0)
        self.assertGreater(K.fuel_subsidy_check(rows, rule, self.R, price=before, mode=DOM.SUBSIDY_ADD_ON_TOP)[0], 0)        # price not raised to the market price
        self.assertGreater(K.fuel_subsidy_check([r for r in rows if r['region'] != 'A'], rule, self.R, mode=DOM.SUBSIDY_ADD_ON_TOP)[0], 0)   # +iea_subsidy, no row

    def test_choice_values(self):
        self.assertEqual(C.load_choices()['fuel_subsidies']['value'], C.FUEL_SUBSIDIES_PRICE_GAP)
        self.assertIn(C.FUEL_SUBSIDIES_ADD_ON_TOP, C.ALTERNATIVES['fuel_subsidies'])
        self.assertIn(C.FUEL_SUBSIDIES_GAP_ROWS_ONLY, C.ALTERNATIVES['fuel_subsidies'])
        self.assertIn('off', C.ALTERNATIVES['fuel_subsidies'])

    def test_iea_value_by_region(self):
        v = DOM.iea_subsidy_by_region(['X', 'Y'], {'X': ['AAA', 'BBB'], 'Y': ['CCC']}, {('gas', 'AAA'): 1.0, ('gas', 'BBB'): 2.0}, 0.9)
        self.assertEqual(list(v), [('gas', 'X')])
        self.assertAlmostEqual(v[('gas', 'X')], 2.7)


class FuelSubsidyPriceGapTest(unittest.TestCase):
    """Fix rounds wA and wA2 (independent QA HIGH-1; coordinator 2026-10-24; Chepeliev et al. 2018 §2.1 and §3.2 steps 2-3).
    Traded fuels: an IEA subsidy is a gap below the trade-parity reference; an observed price is the consumer price (market =
    price + rate, at most the reference); an unobserved price is unsubsidised, so the market price is the reference and the
    consumer price reference - rate, the rate at most 99% of the reference (S11-Hsubref, S11-Hsubcons). Electricity has no
    trade parity: market = IEA-implied reference = consumer price (observed, else tariff table, else income-group average) +
    the IEA rate, uncapped (S11-Rtariff)."""

    def setUp(self):
        self.R = ['A', 'B', 'C', 'D', 'E']
        z = {c: np.zeros(5) for c in DOM.COMMODITIES}
        self.px = {c: np.array([10.0, 12, 14, 16, 18]) for c in DOM.COMMODITIES}
        self.pmb = {c: np.array([np.nan, 13, np.nan, 20, np.nan]) for c in DOM.COMMODITIES}
        # gas: A, C, E exporters, B and D net importers; ely: everyone exports a little (trade parity = own unit value)
        self.xv = dict(z, gas=np.array([5.0, 1, 3, 0, 2]), ely=np.ones(5))
        self.mv = dict(z, gas=np.array([0.0, 2, 0, 1, 0]))
        self.source = {('gas', 'A'): (7.0, 'hub'), ('ely', 'A'): (100.0, 'eurostat')}
        # B's gas gap is used (rule 2); D's gas gap 50 is above its import price 20 (import_basic_price, gap not used);
        # electricity: A observed (100), B's gap 5 would be usable on its unit value 12, E's gap 40 would not
        self.gap = {('gas', 'A'): 2.0, ('gas', 'B'): 3.0, ('gas', 'D'): 50.0, ('ely', 'A'): 30.0, ('ely', 'B'): 5.0, ('ely', 'E'): 40.0}
        self.cons = dict(z, gas=np.array([4.0, 10.0, 20.0, 5.0, 1.0]), ely=np.array([1.0, 2, 1, 1, 10]))
        self.absorb = {c: np.full(5, 100.0) for c in DOM.COMMODITIES}
        self.val = {(c, r): self.gap[(c, r)] * self.cons[c][self.R.index(r)] for (c, r) in self.gap}
        self.tariffs = [dict(region='B', value='', unit='', fx_iso3='', fx_lcu_per_usd='', income_group='LMIC', source='none'),
                        dict(region='E', value='2.5', unit='LCU/kWh', fx_iso3='EEE', fx_lcu_per_usd='', income_group='LMIC', source='EVN-like'),
                        dict(region='C', value='60', unit='USD/MWh', fx_iso3='', fx_lcu_per_usd='', income_group='UMIC', source='cs')]
        self.fx = {'EEE': 50.0}

    def build(self, val=None, source=None, mode=DOM.SUBSIDY_PRICE_GAP, tariffs=None):
        source = self.source if source is None else source
        gap_price = {k: v for k, v in self.gap.items() if k[0] not in DOM.COST_REFERENCE_COMMODITIES}
        out = DOM.domestic_basic_prices(self.R, self.px, self.pmb, self.xv, self.mv, source, gap_price, book_subsidy=True)
        price = {c: out[c][0].copy() for c in out}
        rule = {c: out[c][1].copy() for c in out}
        det = {c: out[c][2].copy() for c in out}
        before = ({c: price[c].copy() for c in price}, {c: rule[c].copy() for c in rule})
        val = self.val if val is None else val
        obs = [r for i, r in enumerate(self.R) if str(rule['ely'][i]).split('+')[0] == 'source_data']
        cp = DOM.electricity_consumer_prices(self.R, self.tariffs if tariffs is None else tariffs, self.fx, observed=obs)
        rows = DOM.fuel_subsidy_rows(self.R, self.px, self.pmb, self.xv, self.mv, self.gap, self.cons, rule, price,
                                     absorption=self.absorb, iea_value=val, mode=mode, consumer_price=cp)
        why = DOM.unbooked_reason(self.R, before[1], before[0], val, rows, self.px, self.pmb, self.xv, self.mv)
        DOM.apply_subsidy_prices(rows, self.R, price, rule, det)
        return {(x['commodity'], x['region']): x for x in rows}, rows, price, rule, det, why

    def ok(self, rows, rule, price):
        self.assertEqual(K.fuel_subsidy_check(rows, rule, self.R, price=price)[0], 0, K.fuel_subsidy_check(rows, rule, self.R, price=price)[1])
        self.assertEqual(K.fuel_subsidy_reference_check(rows)[0], 0)
        self.assertEqual(K.fuel_subsidy_consumer_positive(rows)[0], 0)

    def test_observed_price_keeps_the_method(self):
        x, rows, price, rule, det, _ = self.build()
        a = x[('gas', 'A')]                                          # hub 7, reference 10 (export price), IEA rate 2
        self.assertEqual((a['consumer_price'], a['subsidy_per_unit'], a['rate_cap'], a['consumer_price_basis']),
                         (7.0, 2.0, 'none', 'observed_s11_price'))
        self.assertAlmostEqual(a['market_price'], 9.0)                # PM1 = PM0 + VS/ED, below the reference
        self.assertEqual(price['gas'][0], 9.0)
        self.ok(rows, rule, price)

    def test_observed_rate_capped_at_the_observed_gap(self):
        x, rows, price, rule, *_ = self.build(val={**self.val, ('gas', 'A'): 5.0 * 4.0})   # IEA rate 5 > gap 10 - 7
        a = x[('gas', 'A')]
        self.assertEqual((a['rate_cap'], a['subsidy_per_unit'], a['market_price']), ('observed_price_gap', 3.0, 10.0))
        self.assertAlmostEqual(a['subsidy_musd'], 12.0)
        self.ok(rows, rule, price)

    def test_observed_price_above_the_reference_books_nothing(self):
        x, rows, price, rule, det, why = self.build(source={('gas', 'A'): (12.0, 'hub'), ('ely', 'A'): (100.0, 'eurostat')})
        self.assertNotIn(('gas', 'A'), x)
        self.assertEqual((price['gas'][0], rule['gas'][0]), (12.0, 'source_data'))     # left as observed
        self.assertIn('no price gap', why[('gas', 'A')])
        self.ok(rows, rule, price)

    def test_unobserved_import_price_is_the_reference(self):
        x, rows, price, rule, det, _ = self.build(val={**self.val, ('gas', 'D'): 6.0 * 5.0})   # IEA rate 6 below the import price 20
        d = x[('gas', 'D')]
        self.assertEqual((d['source_rule'], d['consumer_price_basis'], d['rate_cap']),
                         ('import_basic_price_gap_not_used', 'reference_less_rate', 'none'))
        self.assertEqual((d['market_price'], d['consumer_price'], d['subsidy_per_unit']), (20.0, 14.0, 6.0))   # not 20 + 6
        self.assertEqual(price['gas'][3], 20.0)
        self.assertIn('not observed', det['gas'][3])
        self.ok(rows, rule, price)

    def test_traded_rate_capped_with_a_positive_consumer_price(self):
        x, rows, price, rule, *_ = self.build()
        d = x[('gas', 'D')]                                          # IEA rate 50, import price 20
        self.assertEqual((d['rate_cap'], d['step2_rescaled']), ('reference_less_consumer_floor', True))
        self.assertAlmostEqual(d['subsidy_per_unit'], 19.8)
        self.assertAlmostEqual(d['consumer_price'], 0.2)               # 1% of the reference, never 0
        self.assertEqual(d['market_price'], 20.0)
        self.assertAlmostEqual(d['subsidy_musd'], 99.0)
        old = self.build(mode=DOM.SUBSIDY_ADD_ON_TOP)[0][('gas', 'D')]     # w10: 20 + 50 = 70, the double count
        self.assertAlmostEqual(old['market_price'], 70.0)
        self.assertGreater(K.fuel_subsidy_reference_check([old])[0], 0)
        self.ok(rows, rule, price)

    def test_electricity_iea_implied_reference(self):
        x, rows, price, rule, det, _ = self.build()
        a, b, e = x[('ely', 'A')], x[('ely', 'B')], x[('ely', 'E')]
        # A observed 100 + IEA rate 30; E tariff 2.5 LCU/kWh at 50 per USD = 50 USD/MWh + 40; B no tariff: LMIC average 50 + 5
        self.assertEqual((a['consumer_price'], a['consumer_price_basis'], a['market_price']), (100.0, 'observed_s11_price', 130.0))
        self.assertAlmostEqual(e['consumer_price'], 50.0)
        self.assertEqual((e['consumer_price_basis'], e['rate_cap'], e['subsidy_per_unit']), ('end_user_tariff', 'none', 40.0))
        self.assertAlmostEqual(e['market_price'], 90.0)                # uncapped: the trade parity 18 is not used
        self.assertEqual((e['trade_parity_price'], e['source_rule']), (18.0, 'simple_average'))
        # round 3: B has no tariff of its own, so the LMIC average 50 is the reference and the consumer pays 50 - 5
        self.assertEqual(b['consumer_price_basis'], 'reference_less_rate_income_group_tariff')
        self.assertEqual((b['market_price'], b['consumer_price'], b['rate_cap']), (50.0, 45.0, 'none'))   # rule 2 does not price electricity
        self.assertEqual(b['reference_basis'], 'income_group_tariff_average_at_least_rate_over_0.99')
        self.assertAlmostEqual(b['subsidy_musd'], 5.0 * 2.0)            # the IEA money (rate x use) is kept
        for r in (a, e):
            self.assertEqual((r['reference_basis'], r['reference_price']), ('iea_implied_consumer_price_plus_iea_rate', r['market_price']))
        self.assertAlmostEqual(price['ely'][4], 90.0)
        self.assertIn('IEA-implied', det['ely'][4])
        self.ok(rows, rule, price)

    def test_electricity_unobserved_tariff_rate_above_regional_price(self):
        # round 3 (final QA item 4): B's IEA rate 80 is above the LMIC average 50: the reference rises to 80 / 0.99 so the
        # IEA money is kept and the consumer pays 1% of it; the wA2 rule (50 + 80 on top) is the alternative
        val = {**self.val, ('ely', 'B'): 80.0 * 2.0}
        x, rows, price, rule, *_ = self.build(val=val)
        b = x[('ely', 'B')]
        self.assertAlmostEqual(b['market_price'], 80.0 / 0.99)
        self.assertAlmostEqual(b['consumer_price'], 0.01 * 80.0 / 0.99)
        self.assertEqual((b['rate_cap'], b['subsidy_per_unit']), ('reference_raised_to_rate', 80.0))
        self.assertAlmostEqual(b['subsidy_musd'], 160.0)
        self.assertAlmostEqual(price['ely'][1], 80.0 / 0.99)
        self.ok(rows, rule, price)
        gap_price = {k: v for k, v in self.gap.items() if k[0] not in DOM.COST_REFERENCE_COMMODITIES}
        out = DOM.domestic_basic_prices(self.R, self.px, self.pmb, self.xv, self.mv, self.source, gap_price, book_subsidy=True)
        p2, r2 = {c: out[c][0].copy() for c in out}, {c: out[c][1].copy() for c in out}
        cp = DOM.electricity_consumer_prices(self.R, self.tariffs, self.fx, observed=['A'])
        old = {(y['commodity'], y['region']): y for y in DOM.fuel_subsidy_rows(
            self.R, self.px, self.pmb, self.xv, self.mv, self.gap, self.cons, r2, p2, absorption=self.absorb, iea_value=val,
            consumer_price=cp, ely_unobserved=DOM.ELY_UNOBSERVED_ADD_ON_TOP)}
        self.assertAlmostEqual(old[('ely', 'B')]['market_price'], 130.0)     # the add-on-top reference
        self.assertAlmostEqual(old[('ely', 'B')]['subsidy_musd'], 160.0)
        # mutation: a consumer price that is not reference - rate fails S11-Hsubsidy
        bad = [dict(y, consumer_price=50.0) if (y['commodity'], y['region']) == ('ely', 'B') else y for y in rows]
        self.assertGreater(K.fuel_subsidy_check(bad, rule, self.R)[0], 0)

    def test_electricity_consumer_prices(self):
        cp = DOM.electricity_consumer_prices(self.R, self.tariffs, self.fx)
        self.assertEqual({r: v[1] for r, v in cp.items()}, {'B': 'tariff_income_group_average', 'E': 'end_user_tariff', 'C': 'end_user_tariff'})
        self.assertAlmostEqual(cp['B'][0], 50.0)
        alone = [dict(self.tariffs[0], income_group='HIC')] + self.tariffs[1:]
        self.assertAlmostEqual(DOM.electricity_consumer_prices(self.R, alone, self.fx)['B'][0], 55.0)   # no HIC tariff: all groups
        self.assertNotIn('E', DOM.electricity_consumer_prices(self.R, self.tariffs, self.fx, observed=['E']))
        tw = [dict(self.tariffs[1], fx_iso3='', fx_lcu_per_usd='25')]
        self.assertAlmostEqual(DOM.electricity_consumer_prices(['E'], tw, {})['E'][0], 100.0)
        for bad in ([dict(self.tariffs[1], value='0')], [dict(self.tariffs[1], fx_iso3='ZZZ')], [self.tariffs[0]], self.tariffs + [self.tariffs[2]]):
            with self.assertRaises(SystemExit):
                DOM.electricity_consumer_prices(self.R, bad, self.fx)
        with self.assertRaises(SystemExit):                          # an IEA electricity row with no consumer price stops
            self.build(tariffs=[self.tariffs[2]])

    def test_check_mutations(self):
        x, rows, price, rule, *_ = self.build()
        self.ok(rows, rule, price)
        ix = {(r['commodity'], r['region']): i for i, r in enumerate(rows)}
        d, a, e = ix[('gas', 'D')], ix[('gas', 'A')], ix[('ely', 'E')]
        for k, mutate in ((d, lambda r: r.update(market_price=70.0, consumer_price=20.0, domestic_price_before_90pct=70.0, subsidy_per_unit=50.0,
                                                 subsidy_musd=250.0)),             # the w10 double count
                          (d, lambda r: r.update(subsidy_per_unit=25.0, subsidy_musd=125.0, consumer_price=-5.0)),   # rate above the reference
                          (a, lambda r: r.update(market_price=11.0, subsidy_per_unit=4.0, subsidy_musd=16.0, domestic_price_before_90pct=11.0))):
            bad = [dict(r) for r in rows]
            mutate(bad[k])
            self.assertGreater(K.fuel_subsidy_reference_check(bad)[0], 0)
        for k, mutate in ((d, lambda r: r.update(subsidy_per_unit=20.0, consumer_price=0.0, subsidy_musd=100.0)),   # a zero consumer price
                          (e, lambda r: r.update(consumer_price=0.0, subsidy_per_unit=90.0, subsidy_musd=900.0))):
            bad = [dict(r) for r in rows]
            mutate(bad[k])
            self.assertGreater(K.fuel_subsidy_consumer_positive(bad)[0], 0)
        for k, mutate in ((d, lambda r: r.update(rate_cap='none')),                # cap not marked
                          (a, lambda r: r.update(rate_cap='reference')),           # cap without its condition
                          (d, lambda r: r.update(market_price=25.0, consumer_price=5.0, domestic_price_before_90pct=25.0)),   # unobserved, not at the reference
                          (e, lambda r: r.update(subsidy_per_unit=18.0, subsidy_musd=180.0, market_price=68.0, reference_price=68.0,
                                                 domestic_price_before_90pct=68.0)),   # electricity rate capped
                          (e, lambda r: r.update(market_price=95.0, domestic_price_before_90pct=95.0, subsidy_musd=450.0)),     # not consumer + rate
                          (e, lambda r: r.update(consumer_price_basis='simple_average'))):
            bad = [dict(r) for r in rows]
            mutate(bad[k])
            self.assertGreater(K.fuel_subsidy_check(bad, rule, self.R)[0], 0)

    def test_choice_rows(self):
        ch = C.load_choices()
        self.assertEqual(ch['fuel_subsidies']['value'], C.FUEL_SUBSIDIES_PRICE_GAP)
        self.assertEqual(ch['iea_reference_ely']['value'], C.ELY_REFERENCE_ADD_ON_TOP)
        self.assertNotIn('iea_reference_floor_ely', ch)
        self.assertEqual({ch[k]['gtap_status'] for k in ('fuel_subsidy_rate_cap', 'iea_reference_ely')}, {'not_in_gtap_text'})
        self.assertEqual(ch['fuel_subsidy_unobserved_price']['gtap_status'], 'gtap')
        tab = C.read_table('electricity_tariffs_2022.csv', ('region', 'value', 'unit', 'income_group', 'source', 'accessed'))
        self.assertTrue(all(t['income_group'] in ('LIC', 'LMIC', 'UMIC', 'HIC') for t in tab))
        self.assertTrue(all(t['url'] for t in tab if t['value']))


# ------------------------------------------------------------------ other checks
class ChecksTest(unittest.TestCase):
    def arrays(self):
        exi = {'oil': np.array([[0.0, 2], [1, 0]])}
        px = {'oil': np.array([10.0, 20])}
        fob = {'oil': exi['oil'] * px['oil'][:, None]}
        mr = {'oil': np.full((2, 2), 0.1)}
        tm = {'oil': np.full((2, 2), 0.05)}
        cif = {'oil': fob['oil'] * 1.1}
        vmsb = {'oil': cif['oil'] * 1.05}
        tw = {'oil': np.stack([(cif['oil'] - fob['oil']) * 0.5, (cif['oil'] - fob['oil']) * 0.5, np.zeros((2, 2))])}
        V = pd.DataFrame(dict(region=['A', 'B'], commodity='oil', production=[5.0, 5], exports=[2.0, 1], imports=[1.0, 2],
                              export_price=[10.0, 20], export_value=[20.0, 20], domestic_sales=[3.0, 4],
                              domestic_sales_value=[30.0, 80], output_value=[50.0, 100], domestic_price=[10.0, 20]))
        return exi, px, fob, cif, vmsb, mr, tm, tw, V

    def test_identities(self):
        exi, px, fob, cif, vmsb, mr, tm, tw, V = self.arrays()
        r = K.identities(['A', 'B'], ('oil',), exi, px, fob, cif, vmsb, mr, tm, tw, V)
        self.assertLess(r['vpv'], 1e-12)
        self.assertLess(r['cif'], 1e-12)
        self.assertEqual(r['neg'], 0)
        cif2 = {'oil': cif['oil'] * 1.01}
        self.assertGreater(K.identities(['A', 'B'], ('oil',), exi, px, fob, cif2, vmsb, mr, tm, tw, V)['cif'], 1e-6)
        V2 = V.assign(output_value=[51.0, 100])
        self.assertGreater(K.identities(['A', 'B'], ('oil',), exi, px, fob, cif, vmsb, mr, tm, tw, V2)['vpv'], 1e-6)
        tm2 = {'oil': np.full((2, 2), -0.05)}
        self.assertGreater(K.identities(['A', 'B'], ('oil',), exi, px, fob, cif, vmsb, mr, tm2, tw, V)['neg'], 0)

    def test_prices_fixed(self):
        _, px, *_, V = self.arrays()
        V = V.assign(import_basic_price=[np.nan, 5.0])
        pmb = {'oil': np.array([np.nan, 5.0])}
        self.assertEqual(K.prices_fixed(V, px, pmb, ['A', 'B']), 0)
        self.assertEqual(K.prices_fixed(V.assign(export_price=[10.0, 21]), px, pmb, ['A', 'B']), 1)

    def test_ngl_parity(self):
        d = pd.DataFrame(dict(chosen_crude_source=['eia', 'eia'], chosen_crude_kbd=[10.0, 5], eia_57_crude_kbd=[10.0, 5],
                              eia_58_ngpl_kbd=[2.0, 0], eia_57_plus_58_kbd=[12.0, 5]))
        self.assertEqual(K.ngl_parity(d), 0)
        self.assertGreater(K.ngl_parity(d.assign(chosen_crude_kbd=[12.0, 5])), 0)

    def test_gas_balance(self):
        V = pd.DataFrame(dict(region=['IRQ', 'IRN'], commodity='gas', production=[10.0, 200], exports=[0.0, 15],
                              imports=[3.0, 2], absorption=[13.0, 187]))
        self.assertEqual(K.gas_balance(V, ('IRQ', 'IRN')), '')
        self.assertNotEqual(K.gas_balance(V.assign(exports=[11.0, 15]), ('IRQ', 'IRN')), '')

    def test_ninety_after(self):
        d = pd.DataFrame(dict(revenue_after=[10.0, 10], revenue_domestic=[5.0, 0], ratio_after=[0.9, 2.0]))
        self.assertEqual(K.ninety_after(d), 0)
        self.assertEqual(K.ninety_after(d.assign(ratio_after=[0.95, 2.0])), 1)

    def test_non_energy_unchanged(self):
        a = pd.DataFrame(dict(sector=['oil', 'crp'], exporter='A', importer='B', vfob_musd=[1.0, 2]))
        self.assertEqual(K.non_energy_unchanged(a, a), 0)
        self.assertEqual(K.non_energy_unchanged(a, a.assign(vfob_musd=[1.5, 2])), 1)

    def test_secret_scan(self):
        tmp = tempfile.mkdtemp()
        try:
            open(os.path.join(tmp, 'ok.py'), 'w').write('x = 1\n')
            self.assertEqual(K.secret_scan([tmp]), 0)
            open(os.path.join(tmp, 'bad.txt'), 'w').write('api_key = "abcdefghijklmnop"\n')
            self.assertEqual(K.secret_scan([tmp]), 1)
        finally:
            shutil.rmtree(tmp)


# ------------------------------------------------------------------ screens
class ScreensTest(unittest.TestCase):
    R = ['AAA', 'BBB', 'CCC']

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.prep = os.path.join(self.tmp, 'prep')
        os.makedirs(self.prep)
        pd.DataFrame([dict(comparison=k, n_regions_compared=3, concept_note='note') for k in suite.BENCHMARK]).assign(
            commodity='x', flow='production', same_concept='no').to_csv(self.prep + '/crosscheck_summary.csv', index=False)
        pd.DataFrame(columns=['region', 'commodity', 'flow', 'comparison', 'same_concept', 'chosen_value', 'other_value',
                              'chosen_source']).to_csv(self.prep + '/discrepancies_over_5pct.csv', index=False)
        pd.DataFrame([dict(iso3='AAA', region='AAA', commodity='gas', flow='production', year=2022, value=10.0, unit='bcm',
                           source='eia', series_id='INTL.26-1-AAA-BCM.A', fill='no')]).to_csv(self.prep + '/volumes_country_2022.csv', index=False)
        self.intl = os.path.join(self.tmp, 'INTL.txt')
        with open(self.intl, 'w') as fh:
            fh.write(json.dumps({'series_id': 'INTL.26-1-AAA-BCM.A', 'data': [['2022', 10.0], ['2021', 9.0]]}, separators=(',', ':')) + '\n')
        n = 3
        comms = ('oil', 'gas')
        exi = {c: np.array([[0.0, 1, 1], [1, 0, 1], [1, 1, 0]]) for c in comms}
        px = {'oil': np.array([100.0, 100, 100]), 'gas': np.array([500.0, 500, 500])}
        fob = {c: exi[c] * px[c][:, None] for c in comms}
        V = pd.DataFrame([dict(region=r, commodity=c, export_price=px[c][i]) for c in comms for i, r in enumerate(self.R)])
        gas_tonnes = pd.DataFrame(dict(region=self.R, baci_value_musd=[1000.0] * 3, baci_bcm=[2.0] * 3,
                                       volume_exports_bcm=[2.0] * 3, bcm_ratio=[1.0] * 3, observed_price=[False] * 3))
        self.ctx = dict(R=self.R, V=V, comms=comms, gas_tonnes=gas_tonnes, px=px, psrc={c: np.array(['src'] * n, dtype=object) for c in comms},
                        pfill={c: np.zeros(n, bool) for c in comms}, exi=exi, old_fob={c: fob[c].copy() for c in comms},
                        new_fob=fob, new_cif={c: fob[c] * 1.05 for c in comms}, new_vmsb={c: fob[c] * 1.05 for c in comms},
                        tmd={c: np.zeros((n, n)) for c in comms}, mrate={c: np.full((n, n), 0.05) for c in comms},
                        seeded={c: np.zeros((n, n), bool) for c in comms}, fill_rows=[], prep_dir=self.prep, intl_path=self.intl,
                        from_prep={'oil': 0.365, 'gas': 1.0, 'coa': 1.0, 'pet': 0.365, 'ely': 1.0},
                        unit={'oil': 'mbbl', 'gas': 'bcm'}, price_unit={'oil': 'USD/bbl', 'gas': 'USD m/bcm'})
        self.expl = os.path.join(self.tmp, 'expl.csv')

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_suite(self, ctx):
        return suite.run(ctx, report_dir=os.path.join(self.tmp, 'rep'), log=lambda *_: None, explanations=self.expl)

    def screen_hits(self, res, name):
        return [h for h in res['hits'] if h['screen'] == name]

    def test_clean_build_passes(self):
        res = self.run_suite(self.ctx)
        self.assertEqual(res['material_unexplained'], 0)
        for name in ('benchmark', 'outlier', 'year_jump', 'stale', 'identity', 'coverage', 'move', 'seed', 'gas_tonnes'):
            self.assertEqual(self.screen_hits(res, name), [], name)

    def test_each_screen_reports_its_mutation(self):
        ctx = dict(self.ctx)
        # 1 benchmark: AAA gas production twice EI
        pd.DataFrame([dict(region='AAA', commodity='gas', flow='production', comparison='ei_gas_production', same_concept='no',
                           chosen_value=10.0, other_value=4.0, chosen_source='eia')]).to_csv(self.prep + '/discrepancies_over_5pct.csv', index=False)
        # 2 outlier: BBB gas export price 5x
        ctx['px'] = dict(self.ctx['px'], gas=np.array([500.0, 2500, 500]))
        # 3 year jump: AAA gas 2021 at 2
        with open(self.intl, 'w') as fh:
            fh.write(json.dumps({'series_id': 'INTL.26-1-AAA-BCM.A', 'data': [['2022', 10.0], ['2021', 2.0]]}, separators=(',', ':')) + '\n')
        # 4 stale year
        v = pd.read_csv(self.prep + '/volumes_country_2022.csv')
        pd.concat([v, v.assign(year=2015, flow='imports', series_id='INTL.26-3-AAA-BCM.A')]).to_csv(self.prep + '/volumes_country_2022.csv', index=False)
        # 5 identity: VMSB below CIF on one cell
        vm = self.ctx['new_vmsb']['oil'].copy()
        vm[0, 1] = 0.5 * vm[0, 1]
        ctx['new_vmsb'] = dict(self.ctx['new_vmsb'], oil=vm)
        # 6 coverage: CCC oil price filled
        ctx['pfill'] = dict(self.ctx['pfill'], oil=np.array([False, False, True]))
        # 7 moves: AAA oil exports doubled against S10
        nf = self.ctx['new_fob']['oil'].copy()
        nf[0] *= 3.0
        ctx['new_fob'] = dict(self.ctx['new_fob'], oil=nf)
        ctx['new_cif'] = dict(self.ctx['new_cif'], oil=nf * 1.05)
        # 8 seed above 0.1 bn
        sd = np.zeros((3, 3), bool)
        sd[0, 1] = True
        ctx['seeded'] = dict(self.ctx['seeded'], oil=sd)
        # 9 gas tonnes: CCC's BACI tonnes give a quarter of its exports and its price is still the unit value
        ctx['gas_tonnes'] = self.ctx['gas_tonnes'].assign(baci_bcm=[2.0, 2.0, 0.5], bcm_ratio=[1.0, 1.0, 0.25], baci_value_musd=[1000.0, 1000.0, 200.0])
        res = self.run_suite(ctx)
        for name in ('benchmark', 'outlier', 'year_jump', 'stale', 'identity', 'coverage', 'move', 'seed', 'gas_tonnes'):
            self.assertTrue(self.screen_hits(res, name), name)
        self.assertGreater(res['material_unexplained'], 0)

    def test_gas_tonnes_observed_is_not_a_hit(self):
        gt = self.ctx['gas_tonnes'].assign(baci_bcm=[2.0, 2.0, 0.5], bcm_ratio=[1.0, 1.0, 0.25], baci_value_musd=[1000.0, 1000.0, 200.0])
        res = self.run_suite(dict(self.ctx, gas_tonnes=gt))
        self.assertEqual(len(self.screen_hits(res, 'gas_tonnes')), 1)
        self.assertEqual(res['material_unexplained'], 1)
        res = self.run_suite(dict(self.ctx, gas_tonnes=gt.assign(observed_price=[False, False, True])))
        self.assertEqual(self.screen_hits(res, 'gas_tonnes'), [])
        self.assertEqual(len(self.screen_hits(res, 'gas_tonnes_observed')), 1)
        self.assertEqual(res['material_unexplained'], 0)

    def test_explanation_row_clears_a_hit(self):
        ctx = dict(self.ctx, px=dict(self.ctx['px'], gas=np.array([500.0, 25000, 500])))
        res = self.run_suite(ctx)
        self.assertEqual(res['material_unexplained'], 1)
        with open(self.expl, 'w', newline='') as fh:
            w = csv.writer(fh)
            w.writerow(['importer', 'hs6/sector', 'screen', 'evidence class', 'source file and page', 'decided_by', 'date'])
            w.writerow(['BBB', 'gas', 'outlier', 'data_gap', 'test', 'test', '2026-10-23'])
        self.assertEqual(self.run_suite(ctx)['material_unexplained'], 0)
        with open(self.expl, 'w', newline='') as fh:
            w = csv.writer(fh)
            w.writerow(['importer', 'hs6/sector', 'screen', 'evidence class', 'source file and page', 'decided_by', 'date'])
            w.writerow(['BBB', 'gas', 'outlier', 'not_a_class', 'test', 'test', '2026-10-23'])
        self.assertEqual(self.run_suite(ctx)['material_unexplained'], 1)


if __name__ == '__main__':
    unittest.main()


# ------------------------------------------------------------------ fix list A2: export taxes on energy routes
class EnergyExportTaxTest(unittest.TestCase):
    """S10's export-tax rate on VFOB is held on the S11 energy routes: VXSB = VFOB x (1 - t), and the output value
    target is net of the tax (GTAP 12 ch.17A eq. 17.30)."""
    def setUp(self):
        self.xt10 = pd.DataFrame(dict(exporter=['KAZ', 'KAZ', 'ARG'], sector=['oil', 'pet', 'gas'], rate=[0.124, 0.102, 0.12]))
        self.R = ['ARG', 'KAZ', 'USA']
        fob = [100.0, 50.0, 20.0, 30.0]
        sec, exp = ['oil', 'pet', 'gas', 'oil'], ['KAZ', 'KAZ', 'ARG', 'USA']
        rate = K.export_tax_rates(self.xt10, self.R, ('coa', 'oil', 'gas', 'pet', 'ely'))
        r_ = [rate[c][self.R.index(e)] for c, e in zip(sec, exp)]
        self.vf = pd.DataFrame(dict(sector=sec, exporter=exp, importer=['CHN'] * 4, vfob_musd=fob, export_tax_rate=r_,
                                    vxsb_musd=[f * (1 - t) for f, t in zip(fob, r_)]))
        self.vfob10 = pd.DataFrame(dict(sector=sec, exporter=exp, importer=['CHN'] * 4, export_tax_rate=r_))
        self.V = pd.DataFrame(dict(region=['KAZ', 'KAZ', 'ARG', 'USA'], commodity=sec, export_tax=[12.4, 5.1, 2.4, 0.0]))

    def test_rates(self):
        r = K.export_tax_rates(self.xt10, self.R, ('oil', 'gas', 'pet'))
        self.assertEqual(list(r['oil']), [0.0, 0.124, 0.0])
        with self.assertRaises(ValueError):
            K.export_tax_rates(self.xt10.assign(rate=[1.2, 0.1, 0.1]), self.R, ('oil',))

    def test_clean_and_mutations(self):
        self.assertEqual(K.energy_export_tax(self.vf, self.xt10, self.vfob10, self.V, ('coa', 'oil', 'gas', 'pet')), (0, ''))
        # mutation: the pre-fix VXSB = VFOB on energy drops the tax
        bad = self.vf.assign(vxsb_musd=self.vf['vfob_musd'])
        self.assertGreater(K.energy_export_tax(bad, self.xt10, self.vfob10, self.V, ('oil', 'gas', 'pet'))[0], 0)
        # mutation: the output-value side keeps no tax
        self.assertGreater(K.energy_export_tax(self.vf, self.xt10, self.vfob10, self.V.assign(export_tax=0.0), ('oil',))[0], 0)
        # mutation: S10's vfob_s10 carries another rate than export_tax_s10
        self.assertGreater(K.energy_export_tax(self.vf, self.xt10, self.vfob10.assign(export_tax_rate=0.0), self.V, ('oil', 'gas', 'pet'))[0], 0)

    def test_rates_written_rounded_to_1e6_pass(self):
        # the S10 and S11 files are written rounded to 1e-6 (the 2026-10-24 rerun failed on ARG oil 0.0796848 vs 0.079685)
        # S10 writes the full rate, S11 computes VXSB with it and writes the route rate rounded
        xt = self.xt10.assign(rate=[0.124 + 4e-7, 0.102 - 3e-7, 0.12 + 2e-7])
        t = xt.set_index(['exporter', 'sector'])['rate']
        full = [float(t.get((e, c), 0.0)) for e, c in zip(self.vf['exporter'], self.vf['sector'])]
        vf = self.vf.assign(vxsb_musd=self.vf['vfob_musd'] * (1 - pd.Series(full)))
        V = self.V.assign(export_tax=list(self.vf['vfob_musd'] * pd.Series(full)))
        self.assertEqual(K.energy_export_tax(vf, xt, self.vfob10, V, ('coa', 'oil', 'gas', 'pet'))[0], 0)
        # a real rate gap still fails
        self.assertGreater(K.energy_export_tax(self.vf, self.xt10.assign(rate=[0.124, 0.102, 0.121]), self.vfob10, self.V, ('gas',))[0], 0)

    def test_output_value_identity_nets_the_tax(self):
        exi = {'oil': np.array([[0.0, 2], [1, 0]])}
        px = {'oil': np.array([10.0, 20])}
        fob = {'oil': exi['oil'] * px['oil'][:, None]}
        z = {'oil': np.zeros((2, 2))}
        cif = {'oil': fob['oil'].copy()}
        tw = {'oil': np.zeros((3, 2, 2))}
        V = pd.DataFrame(dict(region=['A', 'B'], commodity='oil', production=[5.0, 5], exports=[2.0, 1], imports=[1.0, 2],
                              export_price=[10.0, 20], export_value=[20.0, 20], export_tax=[2.0, 0.0], domestic_sales=[3.0, 4],
                              domestic_sales_value=[30.0, 80], output_value=[48.0, 100], domestic_price=[10.0, 20]))
        self.assertLess(K.identities(['A', 'B'], ('oil',), exi, px, fob, cif, cif, z, z, tw, V)['vpv'], 1e-12)
        # mutation: output value still at FOB exports
        self.assertGreater(K.identities(['A', 'B'], ('oil',), exi, px, fob, cif, cif, z, z, tw, V.assign(output_value=[50.0, 100]))['vpv'], 1e-6)


# ------------------------------------------------------------------ Fable QA D-02, D-04, C-03 (David 2026-10-25 "do all fixes")
from s11_energy import sources as SRC  # noqa: E402


class FableTradeTest(unittest.TestCase):
    """Route prices (D-02), observed re-exports (D-04) and the export tax by route (C-03)."""
    R = ['BLR', 'CHN', 'DEU', 'JPN', 'RUS']

    def test_observed_reexports_same_volume_both_sides(self):
        p, m, x = np.array([4500.0, 0, 220]), np.array([2400.0, 24, 204]), np.array([1270.0, 9, 190])
        share = np.array([0.031, np.nan, 0.6])
        x1, m1, rx, obs = M.remove_reexports_observed(p, m, x, share)
        self.assertAlmostEqual(rx[0], 0.031 * 1270)                       # USA crude: the customs share, not 34 percent
        self.assertAlmostEqual(rx[1], 9 * 24 / 24)                        # not observed: the same propensity
        self.assertAlmostEqual(rx[2], 0.6 * 190)
        np.testing.assert_allclose(x - x1, m - m1)                        # the same volume off exports and imports
        self.assertEqual(list(obs), [True, False, True])
        _, _, rx_cap, _ = M.remove_reexports_observed(np.array([6.0]), np.array([5.0]), np.array([10.0]), np.array([0.9]))
        self.assertAlmostEqual(rx_cap[0], 5.0)                            # at most the imports
        np.testing.assert_allclose(M.remove_reexports_observed(p, m, x, np.full(3, np.nan))[2], M.remove_reexports(p, m, x)[2])
        x0, _, rx0, _ = M.remove_reexports_observed(np.array([0.0, 1.0]), np.array([5.0, 5.0]), np.array([0.5, 3.0]), np.array([0.0, 0.1]))
        np.testing.assert_allclose(rx0, [0.5, 2.0])                       # no production: every export is a re-export (S11-Hdx)
        self.assertTrue(np.all(x0 <= np.array([0.0, 1.0])))

    def baci(self):
        return pd.DataFrame(dict(exp=['RUS', 'RUS', 'RUS', 'RUS', 'RUS'], imp=['CHN', 'CHN', 'JPN', 'DEU', 'BLR'],
                                 k=['271111', '271121', '271111', '271121', '271121'],
                                 v=[6746e3, 3981e3, 5153e3, 10.0, 900e3], q=[6.5e6, 2.95e6, 6.87e6, np.nan, 1.8e6]))

    def test_route_unit_values_and_prices(self):
        b = self.baci()
        uv = M.route_unit_values(b, self.R, 1 / 1.36)
        i, j = self.R.index('RUS'), self.R.index('CHN')
        self.assertAlmostEqual(uv[i, j], 10727 / (9.45 * 1.36), places=6)
        self.assertTrue(np.isnan(uv[i, self.R.index('DEU')]))             # a value without tonnes has no unit value
        b2 = b.copy()
        b2.loc[1, 'q'] = 0.0
        uv2 = M.route_unit_values(b2, self.R, 1 / 1.36, {('RUS', 'CHN'): 14.67})
        self.assertAlmostEqual(uv2[i, j], 10727 / (6.5 * 1.36 + 14.67), places=6)    # EI pipeline volume for the line
        px = np.array([300.0, 500, 500, 500, 885])
        P, ok = M.route_prices(px, uv2, band=(1 / 3, 3))
        self.assertTrue(ok[i, j])
        self.assertAlmostEqual(P[i, j], uv2[i, j])
        self.assertEqual(P[i, self.R.index('DEU')], 885)                   # no unit value: the reference
        far = uv2.copy()
        far[i, j] = 885 * 4
        self.assertFalse(M.route_prices(px, far)[1][i, j])                 # outside the band: a tonnes defect
        P3, ok3 = M.route_prices(px, uv2, at_reference=np.array([False, False, False, False, True]))
        self.assertFalse(ok3[i].any())
        self.assertTrue(np.all(P3[i] == 885))
        vol = np.zeros((5, 5))
        vol[i, j], vol[i, 0] = 10.0, 5.0
        fob = vol * P
        rp = M.realised_export_price(fob, vol, px)
        self.assertAlmostEqual(rp[i], fob[i].sum() / 15.0)
        self.assertEqual(rp[0], px[0])
        # the identity check takes the route prices; a single exporter price on these routes fails it
        z = {'gas': np.zeros((5, 5))}
        V = pd.DataFrame(dict(region=self.R, commodity='gas', production=0.0, exports=vol.sum(1), imports=vol.sum(0), export_price=rp,
                              export_value=vol.sum(1) * rp, export_tax=0.0, domestic_sales=0.0, domestic_sales_value=0.0,
                              output_value=vol.sum(1) * rp, domestic_price=1.0))
        args = (self.R, ('gas',), {'gas': vol})
        rest = ({'gas': fob}, {'gas': fob}, {'gas': fob}, z, z, {'gas': np.zeros((3, 5, 5))}, V)
        self.assertLess(K.identities(*args, {'gas': P}, *rest)['vpv'], 1e-12)
        self.assertGreater(K.identities(*args, {'gas': px}, *rest)['vpv'], 1e-6)

    def test_eurostat_origin_seed(self):
        s = M.eurostat_origin_seed({'NOR': 27.69, 'RUS': 25.94}, 34.06, {'NOR': 27.12, 'NLD': 9.98, 'BEL': 6.53, 'FRA': 0.0})
        self.assertAlmostEqual(sum(s.values()), 27.69 + 25.94 + 34.06)
        self.assertAlmostEqual(s['RUS'], 25.94)
        self.assertAlmostEqual(s['NLD'], 34.06 * 9.98 / (27.12 + 9.98 + 6.53))
        self.assertNotIn('FRA', s)
        self.assertEqual(M.eurostat_origin_seed({'RUS': 1.0}, 5.0, {}), {'RUS': 1.0})   # no mirror: NSP left out

    def test_eurostat_reader(self):
        tmp = tempfile.mkdtemp()
        try:
            def write(name, rows):
                pd.DataFrame(rows, columns=['siec', 'partner', 'unit', 'geo', 'OBS_VALUE']).to_csv(os.path.join(tmp, name), index=False)
            write('ti.csv', [('G3000', 'TOTAL', 'MIO_M3', 'DE', 100.0), ('G3000', 'NSP', 'MIO_M3', 'DE', 40.0), ('G3000', 'RU', 'MIO_M3', 'DE', 30.0),
                             ('G3000', 'NO', 'MIO_M3', 'DE', 25.0), ('G3000', 'AFR_OTH', 'MIO_M3', 'DE', 5.0)])
            write('te.csv', [('G3000', 'DE', 'MIO_M3', 'NO', 45.0), ('G3000', 'DE', 'MIO_M3', 'NL', 10.0), ('G3000', 'DE', 'MIO_M3', 'EL', 1.0)])
            a2 = {'RU': 'RUS', 'NO': 'NOR', 'NL': 'NLD', 'GR': 'GRC', 'DE': 'DEU'}
            named, nsp, mirror, tot = SRC.eurostat_gas_partners_2022(os.path.join(tmp, 'ti.csv'), os.path.join(tmp, 'te.csv'), 'DE', a2)
            self.assertEqual(named, {'RUS': 0.03, 'NOR': 0.025})
            self.assertAlmostEqual(nsp, 0.045)                             # aggregates count with NSP
            self.assertAlmostEqual(mirror['NOR'], 0.02)                    # 45 reported by Norway less the 25 Germany names
            self.assertAlmostEqual(mirror['GRC'], 0.001)                   # Eurostat EL is Greece
            self.assertAlmostEqual(tot, 0.1)
        finally:
            shutil.rmtree(tmp)

    def test_comtrade_reader(self):
        tmp = tempfile.mkdtemp()
        try:
            def put(name, rows):
                json.dump({'data': rows}, open(os.path.join(tmp, name), 'w'))
            put('comtrade_RX_TOTAL_2022.json', [dict(reporterCode=842, primaryValue=1e9), dict(reporterCode=784, primaryValue=1e9)])
            for f in ('X', 'RX'):
                for l in ('2701', '271111', '271121', '2710', '2716'):
                    put(f'comtrade_{f}_{l}_2022.json', [])
            put('comtrade_X_2709_2022.json', [dict(reporterCode=842, primaryValue=117e9, netWgt=209e9), dict(reporterCode=56, primaryValue=1e7, netWgt=1e7),
                                               dict(reporterCode=784, primaryValue=171e9, netWgt=None)])
            put('comtrade_RX_2709_2022.json', [dict(reporterCode=842, primaryValue=3.4e9, netWgt=6.5e9)])
            sh = SRC.comtrade_reexport_shares_2022(tmp, {'056': 'BEL', '784': 'ARE'})
            self.assertAlmostEqual(sh[('USA', 'oil')]['share'], 6.5 / 209)            # Comtrade 842 is the United States; by weight
            self.assertEqual(sh[('ARE', 'oil')]['share'], 0.0)                         # an RX reporter without RX on the good: zero
            self.assertNotIn(('BEL', 'oil'), sh)                                      # not an RX reporter: the same propensity
            put('comtrade_RX_2709_2022.json', [])
            put('comtrade_X_2709_2022.json', [])
            os.remove(os.path.join(tmp, 'comtrade_X_2716_2022.json'))
            with self.assertRaises(FileNotFoundError):
                SRC.comtrade_reexport_shares_2022(tmp, {})
        finally:
            shutil.rmtree(tmp)

    def test_line_rates_from_the_s10_table(self):
        lr = SRC.export_tax_line_rates(os.path.join(BUILD, 'config', 's10', 'export_tax_rates_2022.csv'),
                                       {'gas': SRC.GAS_HS, 'oil': ('270900',), 'pet': ('271000',)})
        self.assertEqual(lr['RUS']['gas'], {'271111': 0.0, '271121': 0.3})
        self.assertNotIn('oil', lr['RUS'])                                # one rate: the S10 rate itself

    def route_tax(self):
        R, n = self.R, len(self.R)
        i = R.index('RUS')
        xrate = np.zeros(n)
        xrate[i] = 0.18
        rl = {'271111': np.zeros((n, n)), '271121': np.zeros((n, n))}
        rl['271111'][i, R.index('JPN')] = 5.0
        rl['271111'][i, R.index('CHN')], rl['271121'][i, R.index('CHN')] = 6.7, 4.0
        rl['271121'][i, R.index('BLR')] = 0.9
        il = {k: v.sum(0) for k, v in rl.items()}
        il['271121'][R.index('DEU')] = 50.0                                # Germany receives pipeline gas from others
        ex = np.zeros((n, n), bool)
        for a in ('RUS', 'BLR'):
            for b in ('RUS', 'BLR'):
                ex[R.index(a), R.index(b)] = a != b
        return xrate, {i: {'271111': 0.0, '271121': 0.3}}, rl, il, ex

    def test_route_export_tax(self):
        xrate, lr, rl, il, ex = self.route_tax()
        T = M.route_export_tax(xrate, lr, rl, il, ex)
        i = self.R.index('RUS')
        self.assertEqual(T[i, self.R.index('JPN')], 0.0)                   # LNG only: the LNG rate
        self.assertEqual(T[i, self.R.index('BLR')], 0.0)                   # EAEU: exempt, although pipeline
        self.assertAlmostEqual(T[i, self.R.index('CHN')], 0.3 * 4.0 / 10.7)
        self.assertAlmostEqual(T[i, self.R.index('DEU')], 0.3)             # no BACI route: the importer's line mix (pipeline)
        R_, xr = self.R, {'gas': xrate}
        xtm = {'gas': T}
        lrr = {'RUS': {'gas': {'271111': 0.0, '271121': 0.3}}}
        self.assertEqual(K.export_route_rate_rule(xtm, R_, xr, lrr, ex), (0, ''))
        held = {'gas': np.repeat(xrate[:, None], len(R_), axis=1)}          # mutation: the S10 rate held on every route
        self.assertGreater(K.export_route_rate_rule(held, R_, xr, lrr, ex)[0], 0)
        over = {'gas': T.copy()}
        over['gas'][i, self.R.index('CHN')] = 0.35                         # mutation: above the highest line rate
        self.assertGreater(K.export_route_rate_rule(over, R_, xr, lrr, ex)[0], 0)

    def test_hxtax_on_route_rates(self):
        xrate, lr, rl, il, ex = self.route_tax()
        T = M.route_export_tax(xrate, lr, rl, il, ex)
        R = self.R
        i = R.index('RUS')
        imps = ['CHN', 'JPN', 'BLR']
        fob = [10.7, 5.0, 0.9]
        t = [T[i, R.index(j)] for j in imps]
        vf = pd.DataFrame(dict(sector='gas', exporter='RUS', importer=imps, vfob_musd=fob, export_tax_rate=t,
                               vxsb_musd=[f * (1 - x) for f, x in zip(fob, t)]))
        xt10 = pd.DataFrame(dict(exporter=['RUS'], sector=['gas'], rate=[0.18]))
        V = pd.DataFrame(dict(region=['RUS'], commodity=['gas'], export_tax=[sum(f * x for f, x in zip(fob, t))]))
        rr = pd.Series({('gas', 'RUS', j): T[i, R.index(j)] for j in R})
        v10 = pd.DataFrame(dict(sector=['gas'], exporter=['RUS'], importer=['JPN'], export_tax_rate=[0.18]))
        self.assertEqual(K.energy_export_tax(vf, xt10, v10, V, ('gas',), route_rate=rr), (0, ''))
        # without the route rule the LNG and EAEU routes are off the S10 rate
        self.assertGreater(K.energy_export_tax(vf, xt10, v10, V, ('gas',))[0], 0)


# ------------------------------------------------------------------ fix round w16: two-sided supply-use balance (§12.2.4)
class SupplyUseBalanceTest(unittest.TestCase):
    # A: crude producer whose measured use (exports + no refinery) is below supply (the GNQ case);
    # B: a consumer whose measured use exceeds supply (the USA case); C: use not measured; D: measured, no use at all
    P = np.array([100.0, 50, 30, 5])
    Mi = np.array([0.0, 40, 10, 0])
    X = np.array([60.0, 10, 20, 0])
    D = np.array([0.0, 90, 0, 0])
    meas = np.array([True, True, False, True])

    def solve(self, surplus_only=False):
        p0, m0, x0, d0, a0, nos, mm = M.supply_use_two_sided(self.P, self.Mi, self.X, self.D, self.meas, surplus_only=surplus_only)
        x1, m1, _ = M.remove_reexports(p0, m0, x0)
        x2, m2, f, p2, d2, a1, it = M.balance_joint(x1, m1, p0, d0, mm)
        return p2, m2, x2, d2, mm, (p0, m0, x0, d0, a0)

    def test_regional_step_opposite_senses(self):
        p0, m0, x0, d0, a0, nos, mm = M.supply_use_two_sided(self.P, self.Mi, self.X, self.D, self.meas)
        self.assertAlmostEqual(a0[0], np.sqrt(60 / 100))
        self.assertAlmostEqual(p0[0], 100 * a0[0])
        self.assertAlmostEqual(x0[0], 60 / a0[0])
        self.assertAlmostEqual(p0[0], x0[0])                               # GNQ: all of production exported
        self.assertGreater(p0[1], self.P[1])                               # USA: supply up, use down
        self.assertLess(d0[1], self.D[1])
        np.testing.assert_allclose(p0[:2] + m0[:2], d0[:2] + x0[:2])
        self.assertEqual((p0[2], m0[2], x0[2]), (30, 10, 20))              # unmeasured: one-sided rule only (feasible)
        self.assertFalse(mm[3])                                            # no use at all: not a measurement
        self.assertEqual(p0[3], 5.0)

    def test_joint_balance_and_check(self):
        p2, m2, x2, d2, mm, _ = self.solve()
        self.assertAlmostEqual(x2.sum(), m2.sum(), places=9)                # world exports = world imports
        self.assertTrue(np.all(x2 <= p2 * (1 + 1e-9)))                      # domestic exports at most production
        self.assertEqual(K.supply_use_balanced(list('ABCD'), p2, m2, x2, d2, mm)[0], 0)
        # mutations: production off by 1 percent; a negative import; the balance off (the rule before w16)
        self.assertEqual(K.supply_use_balanced(list('ABCD'), p2 * np.array([1.01, 1, 1, 1]), m2, x2, d2, mm)[0], 1)
        self.assertEqual(K.supply_use_balanced(list('ABCD'), p2, m2 - np.array([0, 1e3, 0, 0]), x2, d2, mm)[0], 1)
        p0, m0, x0, _, _ = M.supply_use(self.P, self.Mi, self.X)
        xo, mo, _ = M.remove_reexports(p0, m0, x0)
        xo2, mo2, _, po2 = M.balance(xo, mo, p0)
        self.assertGreater(K.supply_use_balanced(list('ABCD'), po2, mo2, xo2, self.D, mm)[0], 0)

    def test_surplus_only_leaves_the_consumer(self):
        p2, m2, x2, d2, mm, (p0, m0, x0, d0, a0) = self.solve(surplus_only=True)
        self.assertTrue(mm[0] and not mm[1])
        self.assertEqual(p0[1], self.P[1])                                  # use above supply: not rescaled
        self.assertAlmostEqual(p0[0], x0[0])

    def test_crude_use_absorbed(self):
        V = pd.DataFrame(dict(region=['A', 'B'], commodity='oil', absorption=[10.0, 0.0]))
        ok = K.crude_use_absorbed(V, ['A', 'B'], {'A': 8.0, 'B': 0.0}, {'A': {'ely': 2.0}}, np.array([True, True]))
        self.assertEqual(ok[0], 0)
        self.assertEqual(K.crude_use_absorbed(V, ['A', 'B'], {'A': 8.0, 'B': 0.0}, {}, np.array([True, True]))[0], 1)   # mutation
        self.assertEqual(K.crude_use_absorbed(V, ['A', 'B'], {'A': 8.0, 'B': 0.0}, {}, np.array([False, True]))[0], 0)  # unmeasured: no check

    def test_round_to_total(self):
        rng = np.random.default_rng(3)
        v = rng.random(300) * 1e-3
        g = np.repeat(['x', 'y', 'z'], 100)
        r = M.round_to_total(v, g, {'z': round(v[200:].sum(), 6)})
        for k, s in (('x', slice(0, 100)), ('y', slice(100, 200)), ('z', slice(200, 300))):
            self.assertAlmostEqual(r[s].sum(), round(v[s].sum(), 6), places=12)
        self.assertLess(np.abs(r - v).max(), 1e-6)
        # mutation: independent rounding does not keep the totals here
        self.assertGreater(max(abs(np.round(v[s], 6).sum() - round(v[s].sum(), 6)) for s in (slice(0, 100), slice(100, 200))), 1e-7)

    def test_choice_values(self):
        self.assertEqual(C.SUPPLY_USE_SCOPE[C.CHOICES['energy_supply_use_balance']], (('coa', 'oil', 'gas'), False))
        self.assertEqual(C.SUPPLY_USE_SCOPE['off'], ((), False))
        for v in C.ALTERNATIVES['energy_supply_use_balance']:
            self.assertIn(v, C.SUPPLY_USE_SCOPE)
        with open(C.CHOICES_PATH, newline='') as fh:
            rows = list(csv.DictReader(fh))
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, 'c.csv')
            for v, ok in (('off', True), (C.SUPPLY_USE_SURPLUS, True), ('two_sided_everything', False)):
                with open(path, 'w', newline='') as fh:
                    w = csv.DictWriter(fh, fieldnames=C.CHOICE_COLUMNS)
                    w.writeheader()
                    w.writerows([dict(r, value=v) if r['choice'] == 'energy_supply_use_balance' else r for r in rows])
                if ok:
                    self.assertEqual(C.load_choices(path)['energy_supply_use_balance']['value'], v)
                else:
                    with self.assertRaises(C.ConfigError):
                        C.load_choices(path)
        finally:
            shutil.rmtree(tmp)


# ------------------------------------------------------------------ Fable QA fix round (2026-10-25)
class FableRoundTest(unittest.TestCase):
    """C-02/B-03/F-10/B-08: sourced 2022 regulated prices in more units; D-06: ely fuels from the UNSD balance."""
    ITEMS = {'g1': dict(value='0.5', unit='USD/MMBtu', fx_iso3=''), 'g2': dict(value='2000', unit='LCU/kcm', fx_iso3='EGY'),
             'g3': dict(value='45', unit='USD/kcm', fx_iso3=''), 'g4': dict(value='3', unit='USD/GJ', fx_iso3=''),
             'g5': dict(value='10', unit='LCU/MMBtu', fx_iso3='EGY'), 'e1': dict(value='120', unit='USD/MWh', fx_iso3=''),
             'e2': dict(value='150', unit='LCU/kWh', fx_iso3='KOR'), 'e3': dict(value='20000', unit='LCU/MWh', fx_iso3='JPN')}

    def test_transcribed_units(self):
        T = DOM.transcribed_price
        self.assertAlmostEqual(T('gas', 'item:g1', self.ITEMS, {})[0], DOM.usd_mmbtu_to_musd_bcm(0.5))
        self.assertAlmostEqual(T('gas', 'item:g2', self.ITEMS, {'EGY': 20.0})[0], 100.0)        # per kcm = USD million per bcm
        self.assertEqual(T('gas', 'item:g3', self.ITEMS, {})[0], 45.0)
        self.assertAlmostEqual(T('gas', 'item:g4', self.ITEMS, {})[0], 120.0)                    # 3 USD/GJ x 40 PJ per bcm
        self.assertAlmostEqual(T('gas', 'item:g5', self.ITEMS, {'EGY': 20.0})[0], DOM.usd_mmbtu_to_musd_bcm(0.5))
        self.assertEqual(T('ely', 'item:e1', self.ITEMS, {})[0], 120.0)
        self.assertAlmostEqual(T('ely', 'item:e2', self.ITEMS, {'KOR': 1250.0})[0], 120.0)       # 150 KRW/kWh at 1250 per USD
        self.assertAlmostEqual(T('ely', 'item:e3', self.ITEMS, {'JPN': 125.0})[0], 160.0)
        for c, s, fx in (('ely', 'item:g3', {}), ('gas', 'item:e1', {}), ('gas', 'item:g2', {}), ('ely', 'item:e2', {})):
            with self.assertRaises(SystemExit):
                T(c, s, self.ITEMS, fx)

    def test_regulated_price_takes_the_observed_branch(self):
        """A sourced regulated price is the consumer price PM0 and the market price is PM0 + the IEA rate (GTAP's
        PM1 = PM0 + VS/ED), not the export-parity reference (the LBY case: export price 1,237, IEA rate 35)."""
        R = ['LBY']
        one = lambda v: {c: np.array([v]) for c in DOM.COMMODITIES}
        px, pmb = one(1237.0), one(np.nan)
        xv, mv = one(2.6), one(0.0)
        src = {('gas', 'LBY'): (DOM.usd_mmbtu_to_musd_bcm(0.5), 'regulated')}
        gap = {('gas', 'LBY'): 35.29}
        dom = DOM.domestic_basic_prices(R, px, pmb, xv, mv, src, gap, None, export_cap=True, book_subsidy=True)
        price = {c: dom[c][0].copy() for c in DOM.COMMODITIES}
        rule = {c: dom[c][1].copy() for c in DOM.COMMODITIES}
        det = {c: dom[c][2].copy() for c in DOM.COMMODITIES}
        self.assertEqual(rule['gas'][0], 'source_data')
        q = one(9.6)
        rows = DOM.fuel_subsidy_rows(R, px, pmb, xv, mv, gap, q, rule, price, absorption=q, iea_value={('gas', 'LBY'): 35.29 * 9.6})
        DOM.apply_subsidy_prices(rows, R, price, rule, det)
        g = [x for x in rows if x['commodity'] == 'gas'][0]
        self.assertAlmostEqual(g['consumer_price'], DOM.usd_mmbtu_to_musd_bcm(0.5))
        self.assertAlmostEqual(g['market_price'], DOM.usd_mmbtu_to_musd_bcm(0.5) + 35.29)
        self.assertLess(price['gas'][0], 100.0)                       # not the export price
        self.assertAlmostEqual(g['subsidy_musd'], 35.29 * 9.6)        # the IEA money is kept

    def test_power_fuel_rows(self):
        from s11_energy import power as PWR
        V_i = pd.DataFrame([dict(region='A', commodity='gas', domestic_sales=80.0, imports=20.0, domestic_price=10.0, import_basic_price=20.0),
                            dict(region='A', commodity='coa', domestic_sales=5.0, imports=0.0, domestic_price=50.0, import_basic_price=np.nan)]
                           ).set_index(['region', 'commodity'])
        rows = {x['fuel']: x for x in PWR.power_fuel_rows(['A'], {'A': {'gas': 10.0, 'gas_dist': 200.0, 'coa': 2.0}}, V_i)}
        self.assertAlmostEqual(rows['gas']['value_dom_musd'], 10 * 0.8 * 10)
        self.assertAlmostEqual(rows['gas']['value_imp_musd'], 10 * 0.2 * 20)
        self.assertEqual(rows['gas_dist']['volume'], 100.0)           # at most absorption
        self.assertEqual(rows['coa']['value_imp_musd'], 0.0)
        self.assertAlmostEqual(rows['coa']['value_dom_musd'], 100.0)

    def test_power_fuels_from_unsd(self):
        from s11_energy import power as PWR
        tmp = tempfile.mkdtemp()
        try:
            p = os.path.join(tmp, 'u.csv')
            hdr = 'DATAFLOW,FREQ,REF_AREA,COMMODITY,TRANSACTION,TIME_PERIOD,OBS_VALUE,UNIT_MULT,UNIT_MEASURE,OBS_STATUS,CONVERSION_FACTOR\n'
            body = ['x,A,156,3000,088,2022,40000,0,TJ,A,', 'x,A,156,3000,1231,2022,80000,0,TJ,A,', 'x,A,156,3000,1214,2022,99999,0,TJ,A,',
                    'x,A,156,0100,088,2022,2000,3,TN,A,', 'x,A,156,0200,088,2022,500,3,TN,A,', 'x,A,156,4610,088,2022,100,3,TN,A,',
                    'x,A,156,4100,088,2022,136.4,3,TN,A,']
            open(p, 'w').write(hdr + '\n'.join(body) + '\n')
            f = PWR.unsd_power_fuels_2022(p, {'156': 'CHN'}, {'CHN': 'CHN'}, 7.0)['CHN']
            self.assertAlmostEqual(f['gas'], 1.0)                     # 40,000 TJ at 40 PJ per bcm
            self.assertAlmostEqual(f['gas_dist'], 2.0)
            self.assertAlmostEqual(f['coa'], 2.5)
            self.assertAlmostEqual(f['pet'], 0.7)
            self.assertAlmostEqual(f['oil'], 1.0)
        finally:
            shutil.rmtree(tmp)


class RegulatedFillTest(unittest.TestCase):
    """Fable QA C-02 (choice regulated_price_fill, David 2026-10-25): PM0 is the observed regulated price, else the class
    average, else (IEA rate at least the average) the lowest observed; market = PM0 + IEA rate, capped at the own trade
    price only where the consumer price stays at or above the lowest observed price; the IEA money is kept."""

    def test_reference_rule(self):
        self.assertEqual(DOM.regulated_reference(110.0, 35.0, 1237.0, 13.5), (145.0, 110.0, 'none'))                  # LBY
        self.assertEqual(DOM.regulated_reference(115.0, 290.0, 310.0, 13.5), (310.0, 20.0, 'netback_reference'))       # UZB
        self.assertEqual(DOM.regulated_reference(56.0, 393.0, 310.0, 13.5), (449.0, 56.0, 'iea_reference_above_trade_price'))   # KAZ

    def test_fill_and_booking(self):
        R = ['RUS', 'SAU', 'LBY', 'IRN', 'UZB', 'DEU']
        arr = lambda *v: np.array(v, dtype=float)
        px = {c: arr(885, 743, 1237, 207, 310, np.nan) for c in DOM.COMMODITIES}
        pmb = {c: arr(np.nan, np.nan, np.nan, np.nan, np.nan, 900) for c in DOM.COMMODITIES}
        xv = {c: arr(166, 1, 2.6, 19, 2.4, 0) for c in DOM.COMMODITIES}
        mv = {c: arr(0, 0, 0, 0, 0, 80) for c in DOM.COMMODITIES}
        src = {('gas', 'RUS'): (88.0, 'regulated'), ('gas', 'SAU'): (13.5, 'regulated'), ('gas', 'UZB'): (115.0, 'regulated'),
               ('gas', 'DEU'): (500.0, 'eurostat')}
        gap = {('gas', 'LBY'): 35.0, ('gas', 'IRN'): 207.5}
        dom = DOM.domestic_basic_prices(R, px, pmb, xv, mv, src, gap, None, export_cap=True, book_subsidy=True)
        price = {c: dom[c][0].copy() for c in DOM.COMMODITIES}
        rule = {c: dom[c][1].copy() for c in DOM.COMMODITIES}
        det = {c: dom[c][2].copy() for c in DOM.COMMODITIES}
        q = {c: arr(470, 120, 9.6, 240, 48, 80) for c in DOM.COMMODITIES}
        val = {('gas', 'RUS'): 247.0 * 470, ('gas', 'SAU'): 123.0 * 120, ('gas', 'LBY'): 35.0 * 9.6, ('gas', 'IRN'): 207.5 * 240,
               ('gas', 'UZB'): 290.0 * 48}
        nx = np.array([True, True, True, True, True, False])
        got = DOM.regulated_consumer_fill(R, price, rule, det, val, nx, q)['gas']
        self.assertAlmostEqual(got['average'], (88 + 13.5 + 115) / 3)
        self.assertEqual((got['lowest'], got['filled']), (13.5, ['LBY', 'IRN']))
        self.assertAlmostEqual(price['gas'][3], 13.5)                  # IRN: IEA rate above the average, so the lowest
        self.assertEqual(rule['gas'][5], 'source_data')                # DEU: not a net exporter, not subsidised
        rows = DOM.fuel_subsidy_rows(R, px, pmb, xv, mv, gap, q, rule, price, absorption=q, iea_value=val, regulated={'gas': got})
        DOM.apply_subsidy_prices(rows, R, price, rule, det)
        x = {r['region']: r for r in rows if r['commodity'] == 'gas'}
        self.assertAlmostEqual(x['LBY']['market_price'], got['average'] + 35.0)        # not the export price 1,237
        self.assertAlmostEqual(x['IRN']['market_price'], 13.5 + 207.5)                 # above its export price 207, uncapped
        self.assertEqual(x['IRN']['rate_cap'], 'iea_reference_above_trade_price')
        self.assertEqual((x['UZB']['market_price'], x['UZB']['rate_cap']), (405.0, 'iea_reference_above_trade_price'))
        self.assertAlmostEqual(x['UZB']['consumer_price'], 115.0)       # observed: not moved by the netback cap
        for r in ('LBY', 'IRN', 'UZB', 'RUS'):
            self.assertAlmostEqual(x[r]['subsidy_musd'], val[('gas', r)])                # the IEA money is kept
        self.assertEqual(K.fuel_subsidy_check(rows, rule, R, price=price)[0], 0, K.fuel_subsidy_check(rows, rule, R, price=price)[1])

    def test_geo_group_exception_and_gas_exporter_class(self):
        R = ['SAU', 'DZA', 'ARE', 'IRN', 'UZB']
        arr = lambda *v: np.array(v, dtype=float)
        price = {c: arr(47.0, 13.5, 776.0, 207.0, 115.0) for c in DOM.COMMODITIES}
        rule = {c: np.array(['source_data', 'source_data', 'import_basic_price', 'simple_average', 'source_data'], dtype=object)
                for c in DOM.COMMODITIES}
        det = {c: np.array([''] * 5, dtype=object) for c in DOM.COMMODITIES}
        q = {c: arr(120, 50, 67, 240, 48) for c in DOM.COMMODITIES}
        val = {('gas', 'SAU'): 123.0 * 120, ('gas', 'DZA'): 470.0 * 50, ('gas', 'ARE'): 261.0 * 67, ('gas', 'IRN'): 207.5 * 240,
               ('gas', 'UZB'): 290.0 * 48}
        nx = np.array([True, True, True, True, False])                  # UZB: not a net energy exporter ...
        xv, mv = {'gas': arr(1, 48, 0, 19, 2.4)}, {'gas': arr(0, 0, 20, 5, 0)}   # ... but a net gas exporter
        geo = {'SAU': 'WEAS', 'ARE': 'WEAS', 'DZA': 'NAFR', 'IRN': 'STAS', 'UZB': 'CEAS'}
        got = DOM.regulated_consumer_fill(R, price, rule, det, val, nx, q, xv, mv, geo, commodities=('gas',))['gas']
        self.assertIn('UZB', got['members'])
        self.assertEqual(price['gas'][2], 47.0)                          # ARE: Saudi Arabia's price, its GTAP group
        self.assertEqual(price['gas'][3], 13.5)                          # IRN: no observed price in its group, class minimum


class RouteLineForcedTest(unittest.TestCase):
    def test_forced_pipeline_route(self):
        z = np.zeros((2, 2))
        lng = np.array([[0.0, 0.0], [0.0, 0.0]])
        T = M.route_export_tax(np.array([0.2, 0.0]), {0: {'271111': 0.0, '271121': 0.3}}, {'271111': lng, '271121': z},
                               {'271111': np.array([0.0, 9.0]), '271121': np.array([0.0, 1.0])}, np.zeros((2, 2), bool),
                               forced={(0, 1): '271121'})
        self.assertAlmostEqual(T[0, 1], 0.3)                         # not the importer's LNG-heavy mix (0.03)


class EiRefineryTest(unittest.TestCase):
    """Fable QA D-08: EI 2022 refinery throughput (thousand barrels daily) read as million bbl by iso3."""

    def test_reads_country_rows_only(self):
        import openpyxl
        d = tempfile.mkdtemp()
        try:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = 'Oil refinery - throughput'
            ws.append(['Oil: Refinery throughput'])
            ws.append(['Thousand barrels daily*', 2021, 2022])
            ws.append(['United Arab Emirates', 900.0, 954.1])
            ws.append(['Kazakhstan', 400.0, 457.17])
            ws.append(['Other Middle East', 170.0, 175.9])
            ws.append(['Total Middle East', 8000.0, 8902.3])
            ws.append(['Curacao', 0, 0])
            p = os.path.join(d, 'ei.xlsx')
            wb.save(p)
            out = SRC.ei_refinery_throughput_2022(p, {'Kazakhstan': 'KAZ'})
            self.assertEqual(set(out), {'ARE', 'KAZ'})
            self.assertAlmostEqual(out['ARE'], 954.1 * 365 / 1000)
            self.assertAlmostEqual(out['KAZ'], 457.17 * 365 / 1000)
        finally:
            shutil.rmtree(d)

    def test_choice_registered(self):
        self.assertIn('refinery_intake_ei_floor', C.CHOICES)
        self.assertEqual(C.EI_INTAKE_FLOOR_SHARE, 0.70)
