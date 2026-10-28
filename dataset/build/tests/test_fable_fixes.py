"""Unit tests for the Fable QA fix round: energy-tax revenue scaling (F-04), the GCC VAT on final demand (C-09), the
extraction energy groups (F-06), the scaled power cells (F-08), the macro comparison with WDI (E-03, E-04) and the
stage-kit guards (E-03).

Run from dataset/build:  python3 -m unittest tests.test_fable_fixes -v
"""
import os
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BUILD)
sys.path.insert(0, os.path.join(BUILD, 'lib'))

from s13_fit import method as M  # noqa: E402
from s13_fit import ptax_source as PS  # noqa: E402
from s11_energy import checks as K11  # noqa: E402
import macro_external as MX  # noqa: E402
import stagekit as SK  # noqa: E402
import screen_review as SRV  # noqa: E402

SECTORS = ['crp', 'coa', 'oil', 'gas', 'pet', 'ely', 'fbt', 'trd']
COLS = SECTORS + ['p', 'g', 'i']


# ------------------------------------------------------------------ F-04
class EnergyRevenueScaleTest(unittest.TestCase):
    def frames(self, tax=120.0, sub=0.0, rate=0.1, basic=(400.0, 600.0)):
        te = pd.DataFrame([dict(region='AAA', commodity='pet', column=c, source='neers', energy_rate=rate,
                                neer_subsidy_rate=0.0, basic_musd=b) for c, b in zip(('trd', 'p'), basic)])
        spec = pd.DataFrame([dict(region='AAA', commodity='pet', **{'class': 'road'}, tax_musd=tax, subsidy_musd=sub)])
        ev = pd.DataFrame([dict(region='AAA', commodity='pet', domestic_sales_value=1500.0, vmsb_imports=500.0)])
        io = pd.DataFrame([dict(region='AAA', row='dom_pet', **{c: 0.0 for c in COLS}),
                           dict(region='AAA', row='imp_pet', **{c: 0.0 for c in COLS})])
        io.loc[0, 'trd'], io.loc[0, 'p'] = 300.0, 450.0
        io.loc[1, 'trd'], io.loc[1, 'p'] = 100.0, 150.0
        return te, spec, ev, io

    def test_revenue_meets_source_on_the_held_row(self):
        te, spec, ev, io = self.frames()
        out, rep, notes = M.scale_energy_rates_to_source(te, spec, ev, io, SECTORS)
        # implied on io12: 0.1 x 1000 = 100; the row is held at 2000 against an io12 total of 1000: expected 200
        self.assertAlmostEqual(rep['row_value_factor'].iloc[0], 2.0)
        self.assertAlmostEqual(rep['scale'].iloc[0], 0.6)
        self.assertAlmostEqual((out['energy_rate'] * out['basic_musd']).sum() * 2.0, 120.0)
        self.assertEqual(notes, [])

    def test_factor_bounded(self):
        te, spec, ev, io = self.frames(tax=5000.0)
        out, rep, notes = M.scale_energy_rates_to_source(te, spec, ev, io, SECTORS)
        self.assertAlmostEqual(rep['scale'].iloc[0], M.ENERGY_REVENUE_BOUND)
        self.assertTrue(notes)

    def test_opposite_sign_keeps_rates(self):
        te, spec, ev, io = self.frames(tax=0.0, sub=-50.0)
        out, rep, notes = M.scale_energy_rates_to_source(te, spec, ev, io, SECTORS)
        self.assertEqual(rep['scale'].iloc[0], 1.0)
        self.assertTrue((out['energy_rate'] == 0.1).all())

    def test_fill_region_untouched(self):
        te, spec, ev, io = self.frames()
        te['source'] = 'fill'
        out, rep, _ = M.scale_energy_rates_to_source(te, spec, ev, io, SECTORS)
        self.assertTrue(rep.empty)
        self.assertTrue((out['revenue_scale'] == 1.0).all())

    def test_subsidy_factor_capped_above_minus_one(self):
        te, spec, ev, io = self.frames(tax=-1900.0, rate=-0.5)
        out, rep, _ = M.scale_energy_rates_to_source(te, spec, ev, io, SECTORS)
        self.assertGreater(out['energy_rate'].min(), M.INFEASIBLE_RATE)


# ------------------------------------------------------------------ C-09
class VatFinalDemandTest(unittest.TestCase):
    def setUp(self):
        n, J = len(SECTORS), len(COLS)
        self.b12 = np.full((n, J), 10.0)
        self.general = np.full((n, J), 0.02)
        self.cell = self.general + 0.01             # an energy part of 0.01 everywhere
        self.tls = (self.general * self.b12).sum(axis=0)

    def test_vat_rate_and_excise(self):
        cell, g, tls, info = PS.vat_final_demand(self.cell, self.general, self.b12, self.tls, SECTORS, COLS, 32.0, 4.0)
        jp, jg = COLS.index('p'), COLS.index('g')
        base = self.b12[:, [jp, jg]].sum()
        self.assertAlmostEqual(info['vat_rate'], 32.0 / base)
        ix = SECTORS.index('fbt')
        self.assertAlmostEqual(g[ix, jp], 32.0 / base + 4.0 / 10.0)
        self.assertAlmostEqual((g[:, [jp, jg]] * self.b12[:, [jp, jg]]).sum(), 36.0)
        np.testing.assert_allclose(cell - g, self.cell - self.general)     # the energy part is kept
        np.testing.assert_allclose(tls, (g * self.b12).sum(axis=0))

    def test_zero_firms_clears_firms_and_investment(self):
        _, g, _, info = PS.vat_final_demand(self.cell, self.general, self.b12, self.tls, SECTORS, COLS, 32.0, 0.0, zero_firms=True)
        self.assertEqual(float(np.abs(g[:, :len(SECTORS)]).sum()), 0.0)
        self.assertEqual(float(np.abs(g[:, COLS.index('i')]).sum()), 0.0)
        self.assertAlmostEqual(info['general_after_musd'], 32.0)

    def test_gfs_parts_one_sector(self):
        w = pd.DataFrame([dict(COUNTRY='SAU', GFS_STO=k, SECTOR=s, TIME_PERIOD=PS.G114_YEAR, OBS_VALUE=v)
                          for k, s, v in (('G114', PS.G114_SECTORS[0], 4.0), ('G1142', PS.G114_SECTORS[0], 0.5),
                                          ('G114', PS.G114_SECTORS[-1], 9.0))])
        out = PS.gfs_parts(w)
        self.assertEqual(out, {('SAU', 'G114'): 4.0, ('SAU', 'G1142'): 0.5})


# ------------------------------------------------------------------ F-06, F-08
class ExtractionAndPowerTest(unittest.TestCase):
    def test_extraction_cells_held_at_row_share(self):
        idx = {c: i for i, c in enumerate(SECTORS)}
        n, J = len(SECTORS), len(COLS)
        pv = {k: np.zeros((n, J)) for k in ('dom', 'imp')}
        ie = idx['pet']
        pv['dom'][ie, idx['oil']] = 2.0          # 2% of the prior pet row
        pv['dom'][ie, idx['trd']] = 58.0
        pv['dom'][ie, COLS.index('p')] = 40.0
        pv['dom'][ie, idx['pet']] = 5.0          # own use: not held (refining is in the pool)
        tau = np.ones((n, J))
        tgt, X, M_ = np.full(n, np.inf), np.zeros(n), np.zeros(n)
        tgt[ie] = 50.0                           # the row S11 holds is half the prior
        held = {}
        M.hold_energy_users(pv, tau, idx, {c: 'prior' for c in SECTORS}, tgt, X, M_, held, COLS, only={idx['oil'], idx['pet']})
        self.assertEqual(set(held), {('dom', ie, idx['oil'])})
        self.assertAlmostEqual(held[('dom', ie, idx['oil'])], 50.0 * 2.0 / 105.0)

    def test_extraction_ely_group(self):
        n = len(SECTORS)
        j, ie = SECTORS.index('oil'), SECTORS.index('ely')
        g = M.extraction_ely_groups(SECTORS, j, None, [1.0] * (2 * n + 1))
        self.assertEqual((g[2 * ie], g[2 * ie + 1]), (1, 1))
        self.assertEqual(int(g.sum()), 2)
        self.assertIsNone(M.extraction_ely_groups(SECTORS, j, None, [0.0] * (2 * n + 1)))

    def test_power_cells_scaled(self):
        idx = {c: i for i, c in enumerate(SECTORS)}
        n, J = len(SECTORS), len(COLS)
        pv = {k: np.zeros((n, J)) for k in ('dom', 'imp')}
        tau = np.ones((n, J))
        tgt = np.full(n, 1000.0)
        X, M_ = np.zeros(n), np.full(n, 1000.0)
        cells = {('dom', 'gas'): 100.0, ('imp', 'gas'): 50.0}
        status = {'ely': 'prior'}
        held, rows = M.hold_power_cells(pv, tau, idx, status, tgt, X, M_, dict(cells, scale=0.5))
        self.assertAlmostEqual(held[('dom', idx['gas'], idx['ely'])], 50.0)
        self.assertAlmostEqual(held[('imp', idx['gas'], idx['ely'])], 25.0)
        self.assertTrue(any(r['status'].startswith('held at 0.5') for r in rows))


# ------------------------------------------------------------------ E-03, E-04
class MacroExternalTest(unittest.TestCase):
    def setUp(self):
        self.wdi = pd.DataFrame([
            dict(countrycode='AAA', year=2022, **{'NY.GDP.MKTP.CD': 900e6, 'NE.CON.PRVT.ZS': 60, 'NE.CON.GOVT.ZS': 20,
                                                 'NE.GDI.TOTL.ZS': 20, 'NE.EXP.GNFS.CD': 300e6, 'NE.IMP.GNFS.CD': 300e6,
                                                 'NY.GNS.ICTR.ZS': 22}),
            dict(countrycode='BBB', year=2022, **{'NY.GDP.MKTP.CD': 100e6, 'NE.CON.PRVT.ZS': 50, 'NE.CON.GOVT.ZS': 20,
                                                 'NE.GDI.TOTL.ZS': 30, 'NE.EXP.GNFS.CD': 20e6, 'NE.IMP.GNFS.CD': 20e6,
                                                 'NY.GNS.ICTR.ZS': 30})])
        self.regions = pd.DataFrame([dict(region='AAA', members='AAA'), dict(region='BBB', members='BBB')])

    def acc(self, x_aaa=300.0):
        return pd.DataFrame([dict(region='AAA', GDP=900.0, C=540.0, G=180.0, I=180.0, X=x_aaa, M=300.0, SAVE=150.0, VDEP=50.0),
                             dict(region='BBB', GDP=100.0, C=50.0, G=20.0, I=30.0, X=20.0, M=20.0, SAVE=10.0, VDEP=20.0)]
                            ).set_index('region')

    def test_composite_and_shares(self):
        regions = pd.DataFrame([dict(region='CMP', members='AAA BBB')])
        w = MX.wdi_by_region(self.wdi, regions)
        self.assertAlmostEqual(w.loc['CMP', 'wdi_saving'], (0.22 * 900 + 0.30 * 100) / 1000)

    def test_large_economy_fails_and_exception(self):
        w = MX.wdi_by_region(self.wdi, self.regions)
        t, fails, hit = MX.compare(self.acc(x_aaa=400.0), w)
        self.assertEqual([f.split()[:2] for f in fails], [['AAA', 'trade']])
        self.assertEqual(t.loc['BBB', 'status_trade'], 'ok')
        ex = {('AAA', 'trade'): dict(finding='D-01')}
        t, fails, hit = MX.compare(self.acc(x_aaa=400.0), w, ex)
        self.assertFalse(any(f.startswith('AAA') for f in fails))
        self.assertTrue(any('D-01' in h for h in hit))

    def test_stale_exception_listed(self):
        w = MX.wdi_by_region(self.wdi, self.regions)
        _, fails, hit = MX.compare(self.acc(), w, {('AAA', 'trade'): dict(finding='D-01')})
        self.assertTrue(any('stale' in h for h in hit))

    def test_read_exceptions_needs_attribution(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, 'e.csv')
        with open(p, 'w') as fh:
            fh.write(','.join(MX.EXCEPTION_COLUMNS) + '\nAAA,trade,D-01,basis,,2026-10-25\n')
        with self.assertRaises(SystemExit):
            MX.read_exceptions(p)


# ------------------------------------------------------------------ E-03 guards
class GuardTest(unittest.TestCase):
    def test_listed_hard_check_becomes_guard_and_fails(self):
        st = SK.Stage.__new__(SK.Stage)
        st.checks, st.log = [], lambda *a, **k: None
        cid = next(iter(SK.GUARDS))
        st.check(cid, 'x', 'hard', 1, 0, False)
        st.check('ZZ-Hnotlisted', 'x', 'hard', 1, 0, True)
        self.assertEqual(st.checks[0]['kind'], 'guard')
        self.assertEqual(st.checks[0]['status'], 'FAIL')
        self.assertEqual(st.checks[1]['kind'], 'hard')


class ReproTest(unittest.TestCase):
    def stage(self, root, sums):
        st = SK.Stage.__new__(SK.Stage)
        st.checks, st.log, st.sid, st.head, st.dirty = [], lambda *a, **k: None, 'S99', 'abc', False
        st.dir = os.path.join(root, 'S99_x')
        st.out = os.path.join(st.dir, 'output')
        os.makedirs(st.out, exist_ok=True)
        open(os.path.join(st.out, 'SHA256SUMS'), 'w').write(sums)
        return st

    def run_with(self, env, mine='aa  f.csv\n', other='aa  f.csv\n'):
        a, b = tempfile.mkdtemp(), tempfile.mkdtemp()
        st = self.stage(a, mine)
        self.stage(b, other)
        old = {k: os.environ.get(k) for k in ('GTAP_OTHER_STAGES_DIR', 'GTAP_RELEASE')}
        try:
            os.environ.pop('GTAP_OTHER_STAGES_DIR', None)
            os.environ.pop('GTAP_RELEASE', None)
            os.environ.update({k: (b if v == 'B' else v) for k, v in env.items()})
            st._repro()
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        return st, st.checks[-1]

    def test_match_passes(self):
        _, c = self.run_with({'GTAP_OTHER_STAGES_DIR': 'B', 'GTAP_RELEASE': '1'})
        self.assertEqual((c['kind'], c['status']), ('hard', 'PASS'))

    def test_mismatch_fails_at_release(self):
        _, c = self.run_with({'GTAP_OTHER_STAGES_DIR': 'B', 'GTAP_RELEASE': '1'}, other='bb  f.csv\n')
        self.assertEqual(c['status'], 'FAIL')

    def test_missing_other_run(self):
        _, c = self.run_with({'GTAP_RELEASE': '1'})
        self.assertEqual(c['status'], 'FAIL')
        _, c = self.run_with({})
        self.assertEqual((c['kind'], c['status']), ('report', 'NOTE'))

    def test_no_commit_is_dirty(self):
        a = tempfile.mkdtemp()
        st = self.stage(a, '')
        st.head = ''
        st._repro()
        self.assertTrue(st.dirty)


class ScreenReviewTest(unittest.TestCase):
    def test_builder_rows_signed(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, 'config', 's12'))
        pd.DataFrame([dict(importer='ALB', **{'hs6/sector': 'for', 'evidence class': 'gtap_rule', 'source file and page': 'x'},
                           screen='outlier', decided_by='Claude (S12 thread)', date='2026-10-23'),
                      dict(importer='ARE', **{'hs6/sector': 'edu', 'evidence class': 'gtap_rule', 'source file and page': 'x'},
                           screen='outlier', decided_by='David', date='2026-10-23')]
                     )[['importer', 'hs6/sector', 'screen', 'evidence class', 'source file and page', 'decided_by', 'date']].to_csv(
            os.path.join(d, 'config', 's12', 'screen_explanations.csv'), index=False)
        rows = SRV.builder_rows(d)
        self.assertEqual(rows['importer'].tolist(), ['ALB'])
        p = os.path.join(d, 'so.csv')
        with open(p, 'w') as fh:
            fh.write(','.join(SRV.SIGNOFF_COLUMNS) + '\nS12,ALB,for,outlier,Reviewer,2026-10-26,disagree,no\n')
        _, uns, dis = SRV.review(rows, SRV.read_signoff(p))
        self.assertEqual((uns, dis), (0, ['S12 ALB for outlier']))
        with open(p, 'w') as fh:
            fh.write(','.join(SRV.SIGNOFF_COLUMNS) + '\nS12,ALB,for,outlier,Claude,2026-10-26,agree,\n')
        with self.assertRaises(SystemExit):
            SRV.read_signoff(p)


class PriceBenchmarkTest(unittest.TestCase):
    def V(self, gas_price=900.0):
        return pd.DataFrame([dict(region='NOR', commodity='gas', export_price=gas_price, export_value=9000.0, production=1.0, exports=1.0,
                                  imports=0.0, absorption=0.0),
                             dict(region='AUS', commodity='coa', export_price=200.0, export_value=9000.0, production=1.0, exports=1.0,
                                  imports=0.0, absorption=0.0)])

    def bench(self, finding=''):
        return [dict(region='NOR', commodity='gas', marker='TTF', open_finding=finding),
                dict(region='AUS', commodity='coa', marker='Australia', open_finding='')]

    def test_within_band(self):
        r = K11.price_benchmarks(self.V(), self.bench(), {'Australia': 180.0}, {'TTF': 30.0})
        self.assertTrue(r['ok'])
        self.assertAlmostEqual(r['table'].set_index('region').loc['NOR', 'marker_price'], 30.0 * K11.MMBTU_PER_BCM)

    def test_price_error_fails_and_open_finding_listed(self):
        r = K11.price_benchmarks(self.V(gas_price=5000.0), self.bench(), {'Australia': 180.0}, {'TTF': 30.0})
        self.assertFalse(r['ok'])
        r = K11.price_benchmarks(self.V(gas_price=5000.0), self.bench('E-08 x'), {'Australia': 180.0}, {'TTF': 30.0})
        self.assertIn('open findings', r['detail'])

    def test_unmapped_exporter_fails(self):
        r = K11.price_benchmarks(self.V(), self.bench()[1:], {'Australia': 180.0}, {'TTF': 30.0})
        self.assertFalse(r['ok'])


if __name__ == '__main__':
    unittest.main()
