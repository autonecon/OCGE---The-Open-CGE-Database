"""Mutation tests for the S12 method, the S12 hard checks, the S12 screens and the config stop.

Every check is called on a good input (it must pass) and on a mutated input (it must fail).
Each screen gets a small fake build and must report its mutation.

Run from dataset/build:  python3 -m unittest tests.test_s12_checks -v
"""
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

from s12_factors import checks as K  # noqa: E402
from s12_factors import config as C  # noqa: E402
from s12_factors import method as M  # noqa: E402
from s12_factors import labour as LAB  # noqa: E402
from s12_factors import sources as SRC  # noqa: E402
from s12_factors.method import LABOUR5, FACTORS  # noqa: E402
import screens.s12_suite as SCR  # noqa: E402

from s12_factors.method import SECTIONS as SECTIONS_  # noqa: E402
GROUPS9_ = ('off_mgr_pros', 'off_mgr_pros', 'tech_aspros', 'clerks', 'service_shop', 'ag_othlowsk', 'ag_othlowsk', 'ag_othlowsk', 'ag_othlowsk')
SECTION_DIVS = {'B': ['05', '06', '07', '08', '09'], 'C': ['10', '11', '12', '17', '18'], 'G': ['45', '46', '47'], 'T': ['97', '98']}


# ------------------------------------------------------------------ config

class LandIncomeTaxCapTest(unittest.TestCase):
    def test_cap(self):
        """Round-3 final QA2 item 7: land income tax at most 99% of the land rent less the factor-use tax."""
        df = pd.DataFrame([dict(sector='crp', factor='land', evfp=100.0, ftax=10.0, evfb=90.0, itax=95.0, fbep=0.0, evos=-5.0),
                           dict(sector='crp', factor='capital', evfp=100.0, ftax=0.0, evfb=100.0, itax=120.0, fbep=0.0, evos=-20.0)])
        out, capped = M.cap_land_income_tax(df)
        self.assertAlmostEqual(out.loc[0, 'itax'], 89.0)
        self.assertAlmostEqual(out.loc[0, 'evos'], 1.0)
        self.assertEqual(out.loc[1, 'itax'], 120.0)          # land only
        self.assertEqual(capped, [('crp', 95.0, 89.0)])
        ev = out.assign(region='AAA')
        self.assertEqual(K.land_itax_capped(ev, M.LAND_ITAX_FLOOR_SHARE)[0], 0)
        self.assertEqual(K.land_itax_capped(df.assign(region='AAA'), M.LAND_ITAX_FLOOR_SHARE)[0], 1)

    def test_floor_matches_s13(self):
        from s13_fit import method as M13
        self.assertEqual(M.LAND_ITAX_FLOOR_SHARE, M13.EVOS_FLOOR_SHARE)

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


# ------------------------------------------------------------------ method
class MethodTest(unittest.TestCase):
    def na(self, rows):
        return pd.DataFrame(rows, columns=['activity', 'item', 'value'])

    def test_exact_cover_and_superset(self):
        df = self.na([('C17', 'D1', 30), ('C17', 'B2A3G', 70), ('C18', 'D1', 10), ('C18', 'B2A3G', 10),
                      ('C', 'D1', 100), ('C', 'B2A3G', 100), ('B', 'D1', 5), ('B', 'B2A3G', 95)])
        out = M.labour_shares_from_na(df, {'pap': {'17', '18'}, 'oil': {'06'}, 'fod': {'10', '11'}}, SECTION_DIVS, SRC.activity_divisions)
        self.assertAlmostEqual(out['pap']['share'], 40 / 120)             # C17 + C18, not C
        self.assertEqual(out['pap']['activity'], 'C17+C18')
        self.assertAlmostEqual(out['oil']['share'], 0.05)                 # superset B
        self.assertEqual(out['fod']['activity'], 'C')

    def test_unobserved_and_clip(self):
        df = self.na([('T', 'D1', 0), ('T', 'B2A3G', 0), ('B', 'D1', 20), ('B', 'B2A3G', -5)])
        out = M.labour_shares_from_na(df, {'hhe': {'97', '98'}, 'oil': {'06'}}, SECTION_DIVS, SRC.activity_divisions)
        self.assertIsNone(out['hhe']['share'])                            # mutation: zero-zero is not labour share 0
        self.assertEqual((out['oil']['share'], out['oil']['flag']), (1.0, 'share_above_1_clipped'))

    def test_derive_b2a3g(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, 't6.csv')
            rows = [('CHL', 'B1G', 'B', 100.0), ('CHL', 'D1', 'B', 10.0), ('CHL', 'D29X39', 'B', 5.0),
                    ('CHL', 'B1G', 'C', 50.0), ('CHL', 'D1', 'C', 20.0),                       # no D29X39: not derived
                    ('COL', 'B1G', 'B', 80.0), ('COL', 'D1', 'B', 8.0), ('COL', 'D29X39', 'B', 2.0), ('COL', 'B2A3G', 'B', 60.0)]
            pd.DataFrame([dict(REF_AREA=a, TRANSACTION=t, ACTIVITY=c, UNIT_MEASURE='XDC', PRICE_BASE='V', TIME_PERIOD=2022, OBS_VALUE=v)
                          for a, t, c, v in rows]).to_csv(p, index=False)
            df, derived = SRC._table6(p, 2022)
            b2 = df[df['item'] == 'B2A3G'].set_index(['iso3', 'activity'])['value']
            self.assertEqual(b2[('CHL', 'B')], 85.0)
            self.assertNotIn(('CHL', 'C'), b2.index)
            self.assertEqual(b2[('COL', 'B')], 60.0)                                   # published value kept
            self.assertEqual(derived, {('CHL', 2022, 'B')})
        finally:
            shutil.rmtree(d)

    def test_wage_calibration_meets_industry_wages(self):
        N_occ, N_ind = np.array([10.0, 20, 30]), np.array([25.0, 35])
        w_occ, w_ind = np.array([3.0, 2, 1]), np.array([2.0, np.nan])
        N, W, S = M.calibrate_wages(N_occ, N_ind, w_occ, w_ind, M.wage_beta(w_occ, N_occ))
        np.testing.assert_allclose(N, np.outer(N_occ, N_ind) / N_occ.sum())   # eq.14.1
        self.assertAlmostEqual((W[:, 0] * N[:, 0]).sum() / N[:, 0].sum(), 2.0)  # eq.14.3 constraint
        np.testing.assert_allclose(W[:, 1], w_occ)                            # no industry wage: prior kept
        np.testing.assert_allclose(S.sum(axis=0), 1.0)
        _, W2, _ = M.calibrate_wages(N_occ, N_ind, w_occ, np.array([0.1, np.nan]), np.ones(3))
        self.assertTrue((W2 >= 0).all())                                      # active set keeps wages >= 0

    def test_year_window(self):
        self.assertEqual(M.year_window([2019, 2020, 2022, 2023], 2022), [2022])
        self.assertEqual(M.year_window([2019, 2020, 2021], 2022), [2021, 2020, 2019])
        self.assertEqual(M.year_window([2015, 2018, 2021], 2022), [2021, 2018])
        self.assertEqual(M.year_window([2023], 2022), [])                   # never after the base year

    def test_factor_taxes(self):
        ev = pd.DataFrame([('crp', 'land', 10.0), ('crp', 'clerks', 30.0), ('crp', 'capital', 20.0), ('mfg', 'clerks', 40.0)],
                          columns=['sector', 'factor', 'evfp'])
        df, r = M.factor_taxes(ev, ssc=7.0, payroll_property=10.0, pit=6.0, cit=3.0, support={'land': 2.0, 'factors': 0.0})
        self.assertAlmostEqual(df['ftax'].sum(), 17.0)
        self.assertAlmostEqual(df['itax'].sum(), 6.0 + 3.0 - 2.0)
        self.assertAlmostEqual(df.loc[0, 'fbep'], 2.0)
        np.testing.assert_allclose(df['evos'], df['evfb'] - df['itax'])

    def test_sur_is_ols(self):
        X = np.c_[np.ones(6), np.arange(6.0), np.arange(6.0) ** 2]
        y = X @ np.array([0.2, 0.01, 0.001])
        b, _, sd, _, n = M.sur_fit(y, y, X)
        np.testing.assert_allclose(b, [0.2, 0.01, 0.001], atol=1e-10)
        self.assertEqual(n, 6)

    def test_country_shares_window_and_exclusion(self):
        def frame(codes, val, years=(2022,)):
            return pd.DataFrame([dict(iso3='AAA', source='BA:1', cls='ISCO08', code=c, year=y, value=val(i))
                                 for y in years for i, c in enumerate(codes)])
        occ9 = [str(i) for i in range(1, 10)]
        secs = list(M.SECTIONS)
        groups9 = ['off_mgr_pros', 'off_mgr_pros', 'tech_aspros', 'clerks', 'service_shop'] + ['ag_othlowsk'] * 4
        sh, meta = LAB.country_shares(frame(occ9, lambda i: 10 + i), frame(secs, lambda i: 5 + i),
                                      frame(occ9, lambda i: 100 - 5 * i), frame(secs, lambda i: 50 + i), groups9, 2022)
        self.assertEqual(meta.loc[0, 'status'], 'used')
        tot = sh.groupby('section')['share'].sum()
        np.testing.assert_allclose(tot.values, 1.0)
        _, meta2 = LAB.country_shares(frame(occ9[:4], lambda i: 10), frame(secs, lambda i: 5), frame(occ9, lambda i: 9),
                                      frame(secs, lambda i: 9), groups9, 2022)
        self.assertTrue(meta2.loc[0, 'status'].startswith('excluded'))         # mutation: four occupations only


# ------------------------------------------------------------------ hard checks
def toy():
    ev = []
    for r in ('AAA', 'BBB'):
        for s, v in (('crp', 100.0), ('oil', 50.0), ('mfg', 80.0)):
            parts = {'land': 0.2 * v if s == 'crp' else 0.0, 'natres': 0.3 * v if s == 'oil' else 0.0}
            lab = 0.5 * v
            for i, g in enumerate(LABOUR5):
                parts[g] = lab * (i + 1) / 15
            parts['capital'] = v - sum(parts.values())
            for f in FACTORS:
                ev.append(dict(region=r, sector=s, factor=f, evfp=parts[f]))
    ev = pd.DataFrame(ev)
    va = ev.groupby(['region', 'sector'])['evfp'].sum().rename('va').reset_index()
    rates = pd.DataFrame([dict(region=r, ssc_rate_on_labour_evfp=0, payroll_property_rate_on_evfp=0, ssc_musd=10.0, payroll_property_musd=5.0,
                               pit_musd=8.0, cit_musd=4.0, support_land_musd=1.0, support_capital_musd=0.0, support_labour_musd=0.0,
                               support_factors_musd=0.0) for r in ('AAA', 'BBB')])
    out = []
    for r, g in ev.groupby('region'):
        df, _ = M.factor_taxes(g, 10.0, 5.0, 8.0, 4.0, {'land': 1.0})
        out.append(df)
    return pd.concat(out, ignore_index=True), va, rates


class ChecksTest(unittest.TestCase):
    def setUp(self):
        self.ev, self.va, self.rates = toy()

    def test_factor_sum(self):
        self.assertEqual(K.factor_sum(self.ev, self.va)[0], 0)
        bad = self.ev.copy()
        bad.loc[0, 'evfp'] += 1.0
        self.assertGreater(K.factor_sum(bad, self.va)[0], 0)

    def test_nonnegative(self):
        self.assertEqual(K.nonnegative(self.ev, set())[0], 0)
        bad = self.ev.copy()
        i = bad.index[(bad['factor'] == 'capital')][0]
        bad.loc[i, 'evfp'] = -1.0
        self.assertGreater(K.nonnegative(bad, set())[0], 0)
        self.assertEqual(K.nonnegative(bad, {(bad.loc[i, 'region'], bad.loc[i, 'sector'])})[0], 0)   # flagged negative VA

    def test_land_only_crp(self):
        self.assertEqual(K.land_only_crp(self.ev)[0], 0)
        bad = self.ev.copy()
        bad.loc[(bad['sector'] == 'mfg') & (bad['factor'] == 'land'), 'evfp'] = 1.0
        self.assertGreater(K.land_only_crp(bad)[0], 0)
        bad2 = self.ev.copy()
        bad2.loc[(bad2['sector'] == 'mfg') & (bad2['factor'] == 'natres'), 'evfp'] = 1.0
        self.assertGreater(K.land_only_crp(bad2)[0], 0)

    def test_group_shares(self):
        t = pd.DataFrame(np.full((2, 5), 0.2), index=['A', 'B'], columns=list(LABOUR5))
        self.assertEqual(K.group_shares({'R': t})[0], 0)
        t2 = t.copy()
        t2.iloc[0, 0] = 0.5
        self.assertEqual(K.group_shares({'R': t2})[0], 1)

    def test_two_group(self):
        self.assertEqual(K.two_group(self.ev)[0], 0)

    def test_tax_totals(self):
        self.assertEqual(K.tax_totals(self.ev, self.rates)[0], 0)
        bad = self.ev.copy()
        bad['ftax'] *= 1.1
        self.assertGreater(K.tax_totals(bad, self.rates)[0], 0)
        bad2 = self.ev.copy()
        bad2['fbep'] = 0.0
        self.assertGreater(K.tax_totals(bad2, self.rates)[0], 0)

    def test_source_coverage(self):
        self.assertEqual(K.source_coverage(['A', 'B'], {'A': {}}, {'A': 'FIGARO 2022', 'B': 'donor A'}, {'B': 'A'})[0], 0)
        self.assertGreater(K.source_coverage(['A', 'B'], {'A': {}}, {'A': 'donor C', 'B': 'donor A'}, {'B': 'A'})[0], 0)
        self.assertGreater(K.source_coverage(['A', 'B'], {'A': {}}, {'A': 'FIGARO 2022', 'B': ''}, {})[0], 0)
        self.assertGreater(K.source_coverage(['A', 'B'], {'A': {}}, {'A': 'FIGARO 2022', 'B': 'donor A'}, {'B': 'A'},
                                             {'B': 49}, 46)[0], 0)                  # mutation: usable partial source dropped
        self.assertEqual(K.source_coverage(['A', 'B'], {'A': {}}, {'A': 'FIGARO 2022', 'B': 'donor A'}, {'B': 'A'},
                                           {'B': 20}, 46)[0], 0)

    def test_capital_keeps_cfc(self):
        nr = pd.DataFrame([dict(region='A', sector='oil', nonlabour_musd=100.0, cfc_share=0.2, natres_musd=80.0)])
        self.assertEqual(K.capital_keeps_cfc(nr)[0], 0)
        self.assertEqual(K.capital_keeps_cfc(nr.assign(natres_musd=95.0))[0], 1)      # mutation: rent eats the CFC

    def test_secret_scan(self):
        d = tempfile.mkdtemp()
        try:
            with open(os.path.join(d, 'a.py'), 'w') as fh:
                fh.write('x = 1\n')
            self.assertEqual(K.secret_scan([d]), 0)
            with open(os.path.join(d, 'b.py'), 'w') as fh:
                fh.write('api_key = "' + 'A' * 20 + '"\n')
            self.assertEqual(K.secret_scan([d]), 1)
        finally:
            shutil.rmtree(d)


# ------------------------------------------------------------------ fix round 2026-10-24 (A3-A7)
class FixRoundTest(unittest.TestCase):
    def na(self, rows):
        return pd.DataFrame(rows, columns=['activity', 'item', 'value'])

    def test_d29_share_and_parent_flag(self):
        df = self.na([('B', 'D1', 20), ('B', 'B2A3G', 70), ('B', 'D29X39', 10), ('C17', 'D1', 30), ('C17', 'B2A3G', 70),
                      ('C18', 'D1', 10), ('C18', 'B2A3G', 10)])
        out = M.labour_shares_from_na(df, {'oil': {'06'}, 'pap': {'17', '18'}}, SECTION_DIVS, SRC.activity_divisions)
        self.assertAlmostEqual(out['oil']['tau'], 0.10)                 # D29X39 / (D1 + B2A3G + D29X39)
        self.assertTrue(out['oil']['parent'])                           # section B read for one division
        self.assertFalse(out['pap']['parent'])
        self.assertEqual(out['pap']['tau'], 0.0)                        # no D29X39 in the source: zero, not NaN

    def test_split_parent(self):
        fig = dict(d1=89.0, b2a3g=319.0, d29=33.0)                      # FIGARO parent B
        t6_b06, t6_b = dict(d1=26.4, b2a3g=250.0, d29=28.1), dict(d1=77.8, b2a3g=325.0, d29=33.8)
        share, tau, d1, b2, d29 = M.split_parent(fig, t6_b06, t6_b)
        self.assertAlmostEqual(d1, 89.0 * 26.4 / 77.8)
        self.assertAlmostEqual(share, d1 / (d1 + b2))
        self.assertLess(share, 0.12)                                    # oil and gas far below the section's 0.22
        self.assertIsNone(M.split_parent(fig, t6_b06, dict(d1=0.0, b2a3g=0.0, d29=0.0)))   # mutation: no parent in the finer source

    def test_uniform_blocks(self):
        flat = {'C': {f'C{i}': 0.267 + 1e-4 * (i % 2) for i in range(10, 28)}, 'G': {'G45': 0.2, 'G46': 0.15, 'G47': 0.18}}
        self.assertEqual(set(M.uniform_blocks(flat)), {'C'})
        varied = {'C': {f'C{i}': 0.2 + 0.02 * i for i in range(10)}}
        self.assertEqual(M.uniform_blocks(varied), {})                 # mutation: a real split is not a block

    def test_rescale_pattern_keeps_d1_total(self):
        f = {'a': 100.0, 'b': 100.0, 'c': 50.0}
        lam = M.rescale_pattern(f, {'a': 0.2, 'b': 0.6, 'c': 0.9}, 120.0)
        self.assertAlmostEqual(sum(lam[k] * f[k] for k in f), 120.0)
        self.assertGreater(lam['b'], lam['a'])
        lam2 = M.rescale_pattern(f, {'a': 0.2, 'b': 0.6, 'c': 0.9}, 230.0)
        self.assertLessEqual(max(lam2.values()), 1.0)                   # clipped, rest solved again
        self.assertAlmostEqual(sum(lam2[k] * f[k] for k in f), 230.0)

    def test_gollin_share_and_floor(self):
        self.assertEqual(M.gollin_share(0.5, 0.2, 0.1), (0.6, False))
        self.assertEqual(M.gollin_share(0.5, 2.0, 0.1), (0.9, True))     # capped at one less the CFC floor
        self.assertEqual(M.gollin_share(1.0, 0.0, 0.25), (0.75, True))   # A6: D1 above factor income, capital keeps CFC

    def test_factor_use_wedge_keeps_evos(self):
        ev = pd.DataFrame([('crp', 'land', 10.0), ('crp', 'clerks', 30.0), ('crp', 'capital', 20.0), ('mfg', 'clerks', 40.0)],
                          columns=['sector', 'factor', 'evfp'])
        a, _ = M.factor_taxes(ev, 7.0, 10.0, 6.0, 3.0, {'land': 2.0}, support_wedge='income')
        b, _ = M.factor_taxes(ev, 7.0, 10.0, 6.0, 3.0, {'land': 2.0}, support_wedge='factor_use')
        np.testing.assert_allclose(a['evos'], b['evos'])                # A4: EVOS unchanged
        np.testing.assert_allclose(a['evfp'], b['evfp'])
        self.assertAlmostEqual(b.loc[0, 'evfb'] - b.loc[0, 'evfp'], 2.0 - a.loc[0, 'ftax'])   # land subsidy on factor use
        self.assertAlmostEqual(b['itax'].sum(), 9.0)                    # income tax is GFS only
        rates = pd.DataFrame([dict(region='R', ssc_musd=7.0, payroll_property_musd=10.0, pit_musd=6.0, cit_musd=3.0, support_land_musd=2.0,
                                   support_capital_musd=0.0, support_labour_musd=0.0, support_factors_musd=0.0)])
        self.assertEqual(K.tax_totals(b.assign(region='R'), rates, 'factor_use')[0], 0)
        self.assertGreater(K.tax_totals(b.assign(region='R'), rates, 'income')[0], 0)   # mutation: wrong wedge

    def test_payroll_on_labour(self):
        ev = pd.DataFrame([('mfg', 'clerks', 40.0), ('mfg', 'capital', 60.0), ('srv', 'clerks', 60.0)], columns=['sector', 'factor', 'evfp'])
        df, r = M.factor_taxes(ev, 10.0, 0.0, 0.0, 0.0, {}, payroll=5.0)
        self.assertAlmostEqual(df['ftax'].sum(), 15.0)
        self.assertEqual(df.loc[1, 'ftax'], 0.0)                        # payroll tax only on labour
        self.assertAlmostEqual(r['r_pay'], 0.05)

    def test_output_tax(self):
        otp, fc, otx, add = M.output_tax(100.0, 0.05, 2.0)
        self.assertAlmostEqual(fc + 2.0 + otx, 100.0)                   # factors + payroll + output tax = VA
        self.assertAlmostEqual(otx, 3.0)
        otp, fc, otx, add = M.output_tax(100.0, -0.2, 0.0, pse_booked=50.0)
        self.assertAlmostEqual(add, 20.0)                               # add-back at most the net subsidy
        self.assertAlmostEqual(otx, 0.0)
        self.assertAlmostEqual(fc, 100.0)

    def test_output_tax_identity_check(self):
        o = pd.DataFrame([dict(region='R', sector='mfg', otp_musd=5.0, pse_addback_musd=0.0, payroll_musd=2.0, output_tax_musd=3.0)])
        self.assertEqual(K.output_tax_identity(o)[0], 0)
        self.assertEqual(K.output_tax_identity(o.assign(output_tax_musd=5.0))[0], 1)   # mutation: booked twice
        self.assertEqual(K.output_tax_identity(o.assign(payroll_musd=-1.0, output_tax_musd=6.0))[0], 1)

    def test_capital_floor_check(self):
        v = pd.DataFrame([dict(region='R', sector='gov', va_musd=100.0, labour_musd=80.0, nonlabour_musd=20.0, capital_floor=0.15),
                          dict(region='R', sector='hhe', va_musd=10.0, labour_musd=10.0, nonlabour_musd=0.0, capital_floor=np.nan)])
        self.assertEqual(K.capital_floor(v)[0], 0)
        self.assertEqual(K.capital_floor(v.assign(labour_musd=100.0, nonlabour_musd=0.0))[0], 1)   # mutation: zero capital

    def test_io_otax_row(self):
        io = pd.DataFrame([dict(region='R', row='dom_mfg', mfg=10.0, OUT=30.0), dict(region='R', row='VA', mfg=20.0, OUT=0.0),
                           dict(region='R', row='OUT', mfg=30.0, OUT=0.0)])
        ev = pd.DataFrame([dict(region='R', sector='mfg', factor=f, evfp=(18.0 if f == 'capital' else 0.0)) for f in FACTORS])
        out = K.io_with_factors(io, ev, ['mfg'], otax=pd.DataFrame([dict(region='R', sector='mfg', output_tax_musd=2.0)]))
        body = out[out['row'].str.startswith('EVFP_') | (out['row'] == 'OTAX')]
        self.assertAlmostEqual(body['mfg'].sum(), 20.0)                 # EVFP + OTAX = VA
        self.assertEqual(list(out['row'])[-1], 'OUT')

    def test_source_readers(self):
        d = tempfile.mkdtemp()
        try:
            g = os.path.join(d, 'grs.csv')
            pd.DataFrame([dict(REF_AREA='FRA', SECTOR='S13', STANDARD_REVENUE=t, UNIT_MEASURE='PT_B1GQ', TIME_PERIOD=y, OBS_VALUE=v)
                          for t, y, v in (('T_3000', 2021, 1.5), ('T_4000', 2021, 3.8), ('T_3000', 2022, 1.6), ('T_4000', 2022, 3.9),
                                          ('T_3000', 2023, 9.9), ('T_4000', 2023, 9.9))]).to_csv(g, index=False)
            self.assertEqual(SRC.grs_payroll(g, 2022)['FRA'][:3], (1.6, 3.9, 2022))   # never after the base year
            self.assertTrue(np.isnan(SRC.grs_payroll(g, 2022)['FRA'][3]))             # no T_4100 row: NaN, not zero
            e = os.path.join(d, 'ste.csv')
            rows = [dict(ref_area='AAA', source=src, sex='SEX_T', classif1=c1, classif2=f'ECO_ISIC4_{sec}', time=y, obs_value=v)
                    for src in ('BA:1', 'XX:2') for y in (2021, 2022) for sec in ('C', 'G')
                    for c1, v in (('STE_AGGREGATE_EES', 100.0), ('STE_AGGREGATE_SLF', 20.0 if src == 'BA:1' else 50.0))]
            pd.DataFrame(rows).to_csv(e, index=False)
            st = SRC.ilostat_status(e, 2022)
            self.assertEqual(set(st['year']), {2022})
            self.assertEqual(set(st['source']), {'BA:1'})                 # the labour force survey first
            self.assertAlmostEqual(float((st['slf'] / st['ees']).iloc[0]), 0.2)
        finally:
            shutil.rmtree(d)


# ------------------------------------------------------------------ screens
# ------------------------------------------------------------------ fix round B16: natural resources by ch.12.A targets
class NatresRuleTest(unittest.TestCase):
    TARGETS = {'for': 2.5, 'fsh': 0.525, 'coa': 0.5, 'oil': 0.5, 'gas': 0.5, 'ore': 2.5, 'min': 2.5, 'msp': 2.5}

    def test_repo_targets_are_ch12a(self):
        nt = C.load_natres_targets()
        self.assertEqual({k: v['eta'] for k, v in nt.items()}, self.TARGETS)
        self.assertTrue(all(v['sigma'] == 0.2 for v in nt.values()))            # ch.16 Table 16.2
        self.assertEqual({k for k, v in nt.items() if v['gtap_sector'] == 'oxt'}, {'ore', 'min', 'msp'})

    def test_targets_config_mutations_stop(self):
        with open(C.NATRES_TARGETS_PATH, newline='') as fh:
            rows = list(csv.DictReader(fh))
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, 't.csv')
            for bad in (rows[1:], rows + [dict(rows[0])], [dict(rows[0], eta_target='-1')] + rows[1:],
                        [dict(rows[0], sigma_va='x')] + rows[1:], [dict(rows[0], source='')] + rows[1:],
                        [dict(rows[0], sector='rle')] + rows[1:]):
                with open(p, 'w', newline='') as fh:
                    w = csv.DictWriter(fh, fieldnames=C.NATRES_TARGET_COLUMNS)
                    w.writeheader()
                    w.writerows(bad)
                with self.assertRaises(C.ConfigError):
                    C.load_natres_targets(p)
        finally:
            shutil.rmtree(d)

    def test_share_gives_the_target_elasticity(self):
        for eta in (0.5, 0.525, 2.5):
            for fva, cost in ((60.0, 100.0), (30.0, 100.0), (95.0, 100.0), (12.0, 100.0)):
                z = M.natres_target_share(fva, cost, eta, 0.2, 0.10)
                self.assertFalse(z['guard'])
                th = fva / cost
                self.assertAlmostEqual(z['share'] * th, 1.0 / (eta / 0.2 + 1.0 / th), places=12)   # theta_R
                self.assertAlmostEqual(M.implied_eta(z['share'] * fva, fva, cost, 0.2), eta, places=10)
                self.assertLess(z['share'], 1.0)
        self.assertAlmostEqual(M.natres_target_share(60.0, 100.0, 0.5, 0.2, 0.1)['share'], 0.2 / 0.5)   # fossil at theta_VA 0.6

    def test_guard_and_degenerate_cells(self):
        z = M.natres_target_share(5.0, 100.0, 0.5, 0.2, 0.10)          # theta_VA 0.05 < floor 0.10
        self.assertTrue(z['guard'])
        self.assertAlmostEqual(z['share'], 0.2 / (0.5 * 0.10 + 0.2))
        self.assertGreater(M.implied_eta(z['share'] * 5.0, 5.0, 100.0, 0.2), 0.5)   # more elastic than the target
        self.assertTrue(M.natres_target_share(5.0, -1.0, 0.5, 0.2, 0.10)['guard'])   # cost not positive
        self.assertEqual(M.natres_target_share(0.0, 100.0, 0.5, 0.2, 0.10)['share'], 0.0)
        self.assertEqual(M.natres_target_share(-3.0, 100.0, 0.5, 0.2, 0.10)['share'], 0.0)

    def cells(self):
        """Two regions, oil (no guard) and coa (guarded), natres booked by the rule out of labour and capital pro rata."""
        ev, cells, nr = [], [], []
        for r in ('AAA', 'BBB'):
            for s, lab, cap, cost in (('oil', 20.0, 40.0, 100.0), ('coa', 2.0, 3.0, 100.0)):
                z = M.natres_target_share(lab + cap, cost, 0.5, 0.2, 0.10)
                k = 1.0 - z['share']
                for i, g in enumerate(LABOUR5):
                    ev.append(dict(region=r, sector=s, factor=g, evfp=lab * k * (i + 1) / 15))
                ev += [dict(region=r, sector=s, factor='capital', evfp=cap * k), dict(region=r, sector=s, factor='natres', evfp=z['share'] * (lab + cap)),
                       dict(region=r, sector=s, factor='land', evfp=0.0)]
                cells.append(dict(region=r, sector=s, cost_musd=cost, eta_target=0.5, sigma_va=0.2, guard=z['guard'], theta_va_used=z['theta_va_used']))
                nr.append(dict(region=r, sector=s, labour_before_musd=lab, capital_before_musd=cap, labour_musd=lab * k, capital_musd=cap * k,
                               natres_musd=z['share'] * (lab + cap), natres_share_of_va=z['share']))
        return pd.DataFrame(ev), pd.DataFrame(cells), pd.DataFrame(nr)

    def test_eta_check(self):
        ev, cells, _ = self.cells()
        self.assertEqual(K.natres_eta(ev, cells)[0], 0)
        self.assertEqual(sorted(cells['guard']), [False, False, True, True])
        bad = ev.copy()                                                   # natres 1% too high in AAA oil: eta off target
        m = (bad['region'] == 'AAA') & (bad['sector'] == 'oil') & (bad['factor'] == 'natres')
        bad.loc[m, 'evfp'] *= 1.01
        self.assertEqual(K.natres_eta(bad, cells)[0], 1)
        bad = ev.copy()                                                   # guarded cell off its floor share
        m = (bad['region'] == 'BBB') & (bad['sector'] == 'coa') & (bad['factor'] == 'natres')
        bad.loc[m, 'evfp'] *= 0.5
        self.assertEqual(K.natres_eta(bad, cells)[0], 1)
        bad = ev.copy()                                                   # no natural resources in a targeted cell
        bad.loc[(bad['region'] == 'AAA') & (bad['sector'] == 'oil') & (bad['factor'] == 'natres'), 'evfp'] = 0.0
        self.assertEqual(K.natres_eta(bad, cells)[0], 1)
        bad = ev.copy()                                                   # natres where there is no value added
        bad.loc[(bad['region'] == 'AAA') & (bad['sector'] == 'oil'), 'evfp'] = 0.0
        bad.loc[(bad['region'] == 'AAA') & (bad['sector'] == 'oil') & (bad['factor'] == 'natres'), 'evfp'] = 1e-3
        self.assertGreaterEqual(K.natres_eta(bad, cells)[0], 1)

    def test_pro_rata_check(self):
        _, _, nr = self.cells()
        self.assertEqual(K.natres_pro_rata(nr)[0], 0)
        bad = nr.copy()                                                   # taken from capital only (the pre-B16 way)
        bad.loc[0, 'capital_musd'] = bad.loc[0, 'capital_before_musd'] - bad.loc[0, 'natres_musd']
        bad.loc[0, 'labour_musd'] = bad.loc[0, 'labour_before_musd']
        self.assertGreater(K.natres_pro_rata(bad)[0], 0)
        bad = nr.copy()                                                   # total not kept
        bad.loc[1, 'natres_musd'] += 1.0
        self.assertEqual(K.natres_pro_rata(bad)[0], 1)

    def test_msp_may_hold_natres_rle_may_not(self):
        ok = pd.DataFrame([dict(region='AAA', sector='msp', factor='natres', evfp=1.0)])   # msp is GTAP oxt
        self.assertEqual(K.land_only_crp(ok)[0], 0)
        self.assertEqual(K.land_only_crp(ok.assign(sector='rle'))[0], 1)

    def test_screens_under_the_rule(self):
        nr = pd.DataFrame([dict(region='AAA', sector='coa', rule='gtap_ch12a', series='ch.12.A target supply elasticity', guard=True,
                                factor_va_musd=5.0, natres_musd=4.0, natres_base_musd=5.0, nonlabour_musd=3.0, natres_share_of_va=0.8,
                                theta_va=0.05, theta_va_used=0.1, eta_implied=1.0, eta_target=0.5, capped=True),
                           dict(region='AAA', sector='oil', rule='gtap_ch12a', series='ch.12.A target supply elasticity', guard=False,
                                factor_va_musd=60.0, natres_musd=24.0, natres_base_musd=60.0, nonlabour_musd=20.0, natres_share_of_va=0.4,
                                theta_va=0.6, theta_va_used=0.6, eta_implied=0.5, eta_target=0.5, capped=False)])
        ev, va, rates = toy()
        ctx = dict(ev=ev, va_long=va, va_rows=pd.DataFrame(columns=['labour_share']), natres=nr, rates=rates)
        self.assertEqual(len(SCR.s8_natres(ctx)[0]), 1)                  # the guarded coa cell
        # natres above the cell's non-labour income is fine under ch.12.A (out of all VA), above VA is not
        self.assertEqual([h for h in SCR.s5_identities(ctx)[0] if h['flow'].startswith('natres')], [])
        ctx['natres'] = nr.assign(natres_musd=[6.0, 24.0])
        self.assertEqual(len([h for h in SCR.s5_identities(ctx)[0] if h['flow'].startswith('natres')]), 1)


class W13FixRoundTest(unittest.TestCase):
    """Fix round w13 (GTAP alignment, David 2026-10-24 "stick to GTAP"): ch.15 payroll and property on all factors,
    ch.14A KF outliers on the SUR prediction, the ISIC 0910 part of msp on the fossil-fuel target."""

    def test_repo_defaults_are_the_gtap_rules(self):
        V = {k: v['value'] for k, v in C.load_choices().items()}
        self.assertEqual(V['payroll_property'], C.PAYROLL_CH15)
        self.assertEqual(V['ag_shares_choice'], C.AG_KF_OUTLIER_GTAP)                      # wD: ch.14A Table 14.1 shares
        self.assertEqual(V['usa_other_production_taxes'], C.USA_D29_BEA)                  # wD: BEA SUT for the USA D29X39
        self.assertEqual(V['msp_natres_target'], C.MSP_BLEND)
        self.assertEqual(set(C.load_ag_outliers()), {'AUS', 'NZL', 'JPN', 'CAN', 'MEX'})     # ch.14A Table 14.2
        coef = C.load_ag_sur()
        self.assertEqual(coef['labour'], (0.5483, -0.00853, 0.01395))                    # Table 14.16 (2), percent / 100
        self.assertEqual(coef['capital'], (0.05398, 0.02903, 0.0333))

    def test_payroll_property_on_all_factors_one_rate(self):
        ev = pd.DataFrame([('crp', 'land', 10.0), ('crp', 'clerks', 30.0), ('crp', 'capital', 20.0), ('oil', 'natres', 40.0),
                           ('mfg', 'clerks', 50.0), ('mfg', 'capital', 50.0)], columns=['sector', 'factor', 'evfp'])
        df, r = M.factor_taxes(ev, 0.0, 20.0, 0.0, 0.0, {})
        np.testing.assert_allclose(df['ftax'] / df['evfp'], 0.1)                          # ch.15: one rate on every factor cell
        self.assertAlmostEqual(df['ftax'].sum(), 20.0)
        self.assertAlmostEqual(r['r_pp'], 0.1)
        bad, _ = M.factor_taxes(ev, 0.0, 0.0, 0.0, 0.0, {}, payroll=20.0)                 # mutation: the A3 labour-only reading
        self.assertEqual(bad.loc[0, 'ftax'], 0.0)                                         # land untaxed there: not ch.15
        rates = pd.DataFrame([dict(region='R', ssc_musd=0.0, payroll_property_musd=20.0, payroll_property_booked_musd=20.0, payroll_musd=0.0,
                                   pit_musd=0.0, cit_musd=0.0, support_land_musd=0.0, support_capital_musd=0.0, support_labour_musd=0.0,
                                   support_factors_musd=0.0)])
        self.assertEqual(K.tax_totals(df.assign(region='R'), rates)[0], 0)
        self.assertEqual(K.tax_totals(df.assign(region='R'), rates.assign(payroll_property_booked_musd=0.0))[0], 1)   # booked twice or not at all

    def outlier_rows(self):
        with open(C.AG_OUTLIERS_PATH, newline='') as fh:
            return list(csv.DictReader(fh))

    def test_outlier_and_sur_config_mutations_stop(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, 'o.csv')
            rows = self.outlier_rows()
            for bad in ([], rows + [dict(rows[0])], [dict(rows[0], table_14_2_preferred='Fuglie')] + rows[1:],
                        [dict(rows[0], reason='')] + rows[1:], [dict(rows[0], iso3='aus')] + rows[1:]):
                with open(p, 'w', newline='') as fh:
                    w = csv.DictWriter(fh, fieldnames=C.AG_OUTLIER_COLUMNS)
                    w.writeheader()
                    w.writerows(bad)
                with self.assertRaises(C.ConfigError):
                    C.load_ag_outliers(p)
            with open(C.AG_SUR_PATH, newline='') as fh:
                sur = list(csv.DictReader(fh))
            for bad in (sur[:1], sur + [dict(sur[0])], [dict(sur[0], const='x')] + sur[1:], [dict(sur[0], unit='share')] + sur[1:]):
                with open(p, 'w', newline='') as fh:
                    w = csv.DictWriter(fh, fieldnames=C.AG_SUR_COLUMNS)
                    w.writeheader()
                    w.writerows(bad)
                with self.assertRaises(C.ConfigError):
                    C.load_ag_sur(p)
        finally:
            shutil.rmtree(d)

    def test_ch14a_sur_prediction(self):
        coef = C.load_ag_sur()
        s, clipped = M.ch14a_sur_prediction(50000.0, 1.0, coef)
        self.assertFalse(clipped)
        self.assertAlmostEqual(s['labour'], 0.5483 - 0.00853 * np.log(50000.0))         # log arable 0 drops out
        self.assertAlmostEqual(s['capital'], 0.05398 + 0.02903 * np.log(50000.0))
        self.assertAlmostEqual(sum(s.values()), 1.0)
        self.assertGreater(s['land'], 0.0)
        s2, _ = M.ch14a_sur_prediction(50000.0, 0.03, coef)                              # less land per person: lower capital share
        self.assertLess(s2['capital'], s['capital'])
        s3, clipped = M.ch14a_sur_prediction(50000.0, 1.0, {'labour': (0.9, 0.0, 0.0), 'capital': (0.3, 0.0, 0.0)})
        self.assertTrue(clipped)                                                          # land negative: clipped and renormalised
        self.assertEqual(s3['land'], 0.0)
        self.assertAlmostEqual(sum(s3.values()), 1.0)

    def test_msp_weight_and_blend(self):
        self.assertAlmostEqual(M.msp_oil_gas_weight(dict(coa=10.0, oil=60.0, gas=20.0, ore=5.0, min=5.0)), 0.8)
        self.assertEqual(M.msp_oil_gas_weight(dict(coa=0.0, oil=0.0, gas=0.0, ore=0.0, min=0.0)), 0.0)
        self.assertEqual(M.msp_oil_gas_weight(dict(coa=1.0, oil=-5.0, gas=0.0, ore=1.0, min=0.0)), 0.0)
        fva, cost = 40.0, 100.0
        z_og = M.natres_target_share(fva, cost, 0.5, 0.2, 0.10)
        z_ot = M.natres_target_share(fva, cost, 2.5, 0.2, 0.10)
        sh, eta = M.msp_blend(z_og['share'], z_ot['share'], 0.8, 0.2, z_ot['theta_va_used'])
        self.assertAlmostEqual(sh, 0.8 * z_og['share'] + 0.2 * z_ot['share'])
        self.assertTrue(0.5 < eta < 2.5)                                                  # between the two ch.12.A targets
        self.assertAlmostEqual(M.implied_eta(sh * fva, fva, cost, 0.2), eta)            # S12-Heta holds at the effective eta
        self.assertEqual(M.msp_blend(z_og['share'], z_ot['share'], 0.0, 0.2, 0.4)[0], z_ot['share'])   # no oil and gas: oxt target
        ev = pd.DataFrame([dict(region='R', sector='msp', factor='capital', evfp=fva * (1 - sh)), dict(region='R', sector='msp', factor='natres', evfp=fva * sh)])
        cells = pd.DataFrame([dict(region='R', sector='msp', cost_musd=cost, eta_target=eta, sigma_va=0.2, guard=False, theta_va_used=0.4)])
        self.assertEqual(K.natres_eta(ev, cells)[0], 0)
        self.assertEqual(K.natres_eta(ev, cells.assign(eta_target=2.5))[0], 1)          # mutation: the unblended B16 target


class ScreensTest(unittest.TestCase):
    def ctx(self):
        ev, va, rates = toy()
        vr = []
        for (r, s), g in ev.groupby(['region', 'sector']):
            v = g['evfp'].sum()
            lab = g[g['factor'].isin(LABOUR5)]['evfp'].sum()
            vr.append(dict(region=r, sector=s, va_musd=v * 1000, labour_musd=lab * 1000, land_musd=0.0, nonlabour_musd=(v - lab) * 1000,
                           labour_share=lab / v, source='FIGARO 2022'))
        nr = pd.DataFrame([dict(region=r, sector='oil', series='NY.GDP.PETR.RT.ZS', natres_musd=15.0, nonlabour_musd=25.0,
                                rent_musd=15.0, rent_booked_at_s11_output_musd=15.0, nonlabour_at_s11_output_musd=25.0, capped=False)
                           for r in ('AAA', 'BBB')])
        lmeta = pd.DataFrame([dict(iso3='AAA', years='2022', status='used'), dict(iso3='BBB', years='2016 2015', status='used')])
        return dict(ev=ev, va_long=va, va_rows=pd.DataFrame(vr), natres=nr, rates=rates, lmeta=lmeta,
                    lam_src={'AAA': 'FIGARO 2022', 'BBB': 'OECD Table 6 2017'}, lab_src={'AAA': 'ILOSTAT 2022', 'BBB': 'F16c X average'},
                    labour5=LABOUR5, national_share={'AAA': (0.5, 'FIGARO'), 'BBB': (0.5, 'T6')},
                    share_years={('AAA', 'mfg'): (0.5, 0.45, 'FIGARO 2022 against 2017')}, cell_note={}, sector_donor=set(), prev=None)

    def run_suite(self, ctx, expl=None):
        d = tempfile.mkdtemp()
        try:
            return SCR.run(ctx, report_dir=d, log=lambda *_: None, explanations=expl)
        finally:
            shutil.rmtree(d)

    def test_clean_build_passes(self):
        out = self.run_suite(self.ctx())
        self.assertEqual(out['material_unexplained'], 0)

    def test_each_screen_reports_its_mutation(self):
        c = self.ctx()
        c['national_share']['AAA'] = (0.1, 'FIGARO')                     # 1 benchmark: S12 five times the national share
        self.assertTrue(any(h['screen'] == 'benchmark' for h in SCR.s1_benchmark(c)[0]))
        c = self.ctx()
        c['va_rows'].loc[0, 'labour_share'] = 0.01                         # 2 outlier
        self.assertEqual(len(SCR.s2_outliers(c)[0]), 1)
        c = self.ctx()
        c['share_years'][('AAA', 'mfg')] = (0.9, 0.2, 'x')               # 3 year jump
        self.assertEqual(len(SCR.s3_year_jumps(c)[0]), 1)
        self.assertEqual(len(SCR.s4_stale(self.ctx())[0]), 2)              # 4 BBB: ILOSTAT 2016 and Table 6 2017
        c = self.ctx()
        c['ev'].loc[0, 'evfp'] += 5.0                                      # 5 identity
        self.assertGreater(len(SCR.s5_identities(c)[0]), 0)
        self.assertEqual(len(SCR.s6_coverage(self.ctx())[0]), 1)           # 6 BBB F16c groups
        c = self.ctx()
        c['prev'] = c['ev'].assign(evfp=c['ev']['evfp'] * 2)               # 7 moves
        self.assertGreater(len(SCR.s7_moves(c)[0]), 0)
        c = self.ctx()
        c['natres'].loc[0, 'capped'] = True                                 # 8 natres
        self.assertEqual(len(SCR.s8_natres(c)[0]), 1)

    def test_material_unexplained_fails_and_row_explains(self):
        c = self.ctx()
        c['va_rows'].loc[(c['va_rows']['sector'] == 'mfg') & (c['va_rows']['region'] == 'AAA'), 'labour_share'] = 0.01
        c['va_rows'].loc[(c['va_rows']['sector'] == 'oil') & (c['va_rows']['region'] == 'BBB'), 'labour_share'] = 0.01
        out = self.run_suite(c)
        self.assertGreater(out['material_unexplained'], 0)
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, 'e.csv')
            with open(p, 'w', newline='') as fh:
                w = csv.writer(fh)
                w.writerow(['importer', 'hs6/sector', 'screen', 'evidence class', 'source file and page', 'decided_by', 'date'])
                for r, sec in (('AAA', 'mfg'), ('BBB', 'oil')):
                    w.writerow([r, sec, 'outlier', 'genuine_not_a_source_gap', 'test', 'test', '2026-10-23'])
            self.assertEqual(self.run_suite(c, p)['material_unexplained'], 0)
        finally:
            shutil.rmtree(d)


class WDFixTest(unittest.TestCase):
    """Fix worker wD (independent QA MEDIUM-1 and MEDIUM-5): the USA D29X39 from the BEA supply-use table, and the
    ch.14A Table 14.1 GTAP shares for the Table 14.2 KF outliers."""

    def test_ch14a_table14_1_shares(self):
        sh = C.load_ag_outlier_gtap_shares()
        self.assertEqual(set(sh), {'AUS', 'NZL', 'JPN', 'CAN', 'MEX'})
        self.assertAlmostEqual(sh['AUS']['labour'], 0.51)                                 # Table 14.1: Australia 51 / 28
        self.assertAlmostEqual(sh['AUS']['capital'], 0.28)
        self.assertAlmostEqual(sh['AUS']['land'], 0.21)
        self.assertAlmostEqual(sh['CAN']['land'], 0.16)                                   # Canada 41 / 43
        for s in sh.values():
            self.assertAlmostEqual(sum(s.values()), 1.0)

    def test_outlier_share_mutations_stop(self):
        with open(C.AG_OUTLIERS_PATH, newline='') as fh:
            rows = list(csv.DictReader(fh))
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, 'o.csv')
            for bad in ([dict(rows[0], gtap_labour_pct='x')] + rows[1:], [dict(rows[0], gtap_capital_pct='60')] + rows[1:],
                        [dict(rows[0], gtap_labour_pct='0')] + rows[1:]):
                with open(p, 'w', newline='') as fh:
                    w = csv.DictWriter(fh, fieldnames=C.AG_OUTLIER_COLUMNS)
                    w.writeheader()
                    w.writerows(bad)
                with self.assertRaises(C.ConfigError):
                    C.load_ag_outlier_gtap_shares(p)
        finally:
            shutil.rmtree(d)

    def test_bea_map_covers_the_bea_industries(self):
        bea = SRC.bea_sut_va(os.path.join(os.path.dirname(C.BUILD), 'data', 'bea_sut', 'bea_use_sut_summary_va_2017_2023.csv'), 2022)
        m = C.load_bea_map()
        self.assertEqual(set(bea['industry_code']) - set(m), set())
        self.assertEqual(m['GSLG'], ())
        self.assertAlmostEqual((bea['T00OTOP'].sum() - bea['T00OSUB'].sum()) / 1000.0, 773.898 - 24.370, places=2)   # BEA 2022 totals

    def test_bea_group_tau(self):
        sectors = ['oil', 'gas', 'hos', 'gov', 'pub', 'tel', 'its']
        bea = pd.DataFrame(dict(industry_code=['211', '722', 'G', '513', '514'], T00OTOP=[30.0, 5.0, 0.0, 4.0, 2.0],
                                T00OSUB=[0.0, 1.0, 0.0, 0.0, 0.0]))
        bmap = {'211': ('oil', 'gas'), '722': ('hos',), 'G': (), '513': ('pub', 'tel'), '514': ('tel', 'its')}
        va = dict(oil=200.0, gas=100.0, hos=40.0, gov=500.0, pub=10.0, tel=20.0, its=30.0)
        tau, groups = M.bea_group_tau(bea, bmap, va, sectors)
        self.assertAlmostEqual(tau['oil'], 0.1)                                           # 30 over oil + gas VA 300
        self.assertAlmostEqual(tau['gas'], 0.1)
        self.assertAlmostEqual(tau['hos'], 0.1)                                           # (5 - 1) / 40
        self.assertEqual(tau['gov'], 0.0)                                                 # government: none in BEA
        self.assertAlmostEqual(tau['its'], 6.0 / 60.0)                                    # 513 and 514 share tel: one group
        self.assertAlmostEqual(sum(tau[s] * va[s] for s in sectors), 30.0 + 4.0 + 6.0)    # the BEA net is booked once
        self.assertEqual(len(groups), 3)
        with self.assertRaises(SystemExit):                                               # an unmapped BEA code stops
            M.bea_group_tau(bea, {k: v for k, v in bmap.items() if k != '722'}, va, sectors)
        with self.assertRaises(SystemExit):                                               # a sector not in the list stops
            M.bea_group_tau(bea, dict(bmap, G=('xxx',)), va, sectors)

    def test_scale_positive_d29(self):
        new, k, pos, neg = M.scale_positive_d29([10.0, 30.0, -5.0], 15.0)
        self.assertAlmostEqual(k, 0.5)                                                    # (15 + 5) / 40
        np.testing.assert_allclose(new, [5.0, 15.0, -5.0])                                # negative cells kept
        self.assertAlmostEqual(new.sum(), 15.0)
        with self.assertRaises(SystemExit):                                               # never adds D29
            M.scale_positive_d29([10.0, -5.0], 20.0)
        with self.assertRaises(SystemExit):                                               # target below the subsidies
            M.scale_positive_d29([10.0, -5.0], -6.0)

    def test_jpn_national_d29_and_config(self):
        t14 = SRC.oecd_table14_d29_net(os.path.join(os.path.dirname(C.BUILD), 'data', 'oecd_nasec_table14',
                                                    'oecd_table14_d21_d29_d3_2017_2022.csv.gz'), 2022)
        self.assertAlmostEqual(t14['JPN']['d29'], 14946200.0)                              # ESRI via OECD Table 14, m yen
        self.assertEqual(t14['JPN']['sub_item'], 'D3')
        self.assertAlmostEqual(t14['JPN']['net'], 14946200.0 - 5925100.0)
        self.assertEqual(t14['DEU']['sub_item'], 'D39')
        self.assertEqual(set(C.load_d29_national()), {'JPN'})
        ch = C.load_choices()
        self.assertEqual(ch['d29x39_national_total']['value'], C.D29_NATIONAL)
        self.assertNotEqual(ch['payroll_d29_netting']['value'], C.PAYROLL_NETTED)   # Fable QA F-03: David chose GTAP (no netting)
        self.assertEqual(ch['payroll_d29_netting']['gtap_status'], 'gtap')
        self.assertEqual(ch['payroll_property']['gtap_status'], 'gtap')


class RoundThreeWF(unittest.TestCase):
    """Fix worker wF (QA round 2 P2, P3, P6)."""

    def test_crp_beyond_pse_cap(self):
        otp, fc, otx, addb = M.output_tax(100.0, -0.2, 0.0, 5.0)                       # D39 -20, PSE 5 added back
        cap = M.crp_beyond_pse_cap(otp, addb)
        self.assertAlmostEqual(cap, 15.0)
        self.assertAlmostEqual(otx + cap, 0.0)                                         # only the PSE is left
        self.assertAlmostEqual(fc - cap, 100.0)                                        # factor cost = VA
        self.assertEqual(M.crp_beyond_pse_cap(*M.output_tax(100.0, 0.03, 0.0, 5.0)[::3]), 0.0)   # a tax is kept
        self.assertEqual(M.crp_beyond_pse_cap(-20.0, 25.0), 0.0)

    def test_donor_tau(self):
        self.assertEqual(M.donor_tau(-0.16), 0.0)
        self.assertAlmostEqual(M.donor_tau(0.04), 0.04)
        self.assertAlmostEqual(M.donor_tau(-0.16, on=False), -0.16)
        self.assertIsNone(M.donor_tau(None))

    def test_d29_reference_and_cell_target(self):
        ref = M.d29_reference({'whs': [0.0, 0.01, 0.02, 0.03, 0.04, None, np.nan]})['whs']
        self.assertAlmostEqual(ref[1], 0.02)
        self.assertTrue(ref[0] < ref[1] < ref[2])
        r = (-0.04, 0.008, 0.06)
        self.assertEqual(M.d29_cell_target(0.69, 0.0, r, False), (0.008, 'national_source_median'))
        self.assertEqual(M.d29_cell_target(-0.65, 0.0, r, False), (0.008, 'national_source_median'))
        self.assertEqual(M.d29_cell_target(0.03, 0.0, r, False), (0.03, 'kept_inside_range'))
        t, rule = M.d29_cell_target(0.10, 0.05, r, False)                              # duty out brings it inside
        self.assertAlmostEqual(t, 0.05)
        self.assertEqual(rule, 'export_duty_out')
        self.assertEqual(M.d29_cell_target(0.95, 0.09, (-0.5, -0.2, 0.02), True), (0.0, 'crp_zero'))

    def test_d29_for_share_keeps_labour_share(self):
        d1, b2 = 31.9, -20.5
        d29 = M.d29_for_share(d1, b2, 0.008)
        self.assertAlmostEqual(d29 / (d1 + b2 + d29), 0.008)
        with self.assertRaises(ValueError):
            M.d29_for_share(1.0, 1.0, 1.0)

    def test_output_tax_identity_with_crp_cap(self):
        otx = pd.DataFrame(dict(region=['A'], sector=['crp'], va_musd=[100.0], otp_musd=[-20.0], pse_addback_musd=[5.0],
                                crp_beyond_pse_removed_musd=[15.0], output_tax_before_payroll_musd=[0.0], payroll_musd=[0.0],
                                output_tax_musd=[0.0]))
        self.assertEqual(K.output_tax_identity(otx)[0], 0)
        self.assertEqual(K.crp_no_subsidy_beyond_pse(otx, {'A'})[0], 0)
        bad = otx.assign(crp_beyond_pse_removed_musd=[0.0])
        self.assertEqual(K.output_tax_identity(bad)[0], 1)
        bad = otx.assign(output_tax_before_payroll_musd=[-15.0])
        self.assertEqual(K.crp_no_subsidy_beyond_pse(bad, {'A'})[0], 1)
        self.assertEqual(K.crp_no_subsidy_beyond_pse(bad, set())[0], 0)

    def test_eu27_matches_s10(self):
        from s10_tariffs.preferences import EU27
        self.assertEqual(C.EU27, EU27)

    def test_repo_config(self):
        ch = C.load_choices()
        self.assertEqual(ch['crp_d29_beyond_pse']['value'], C.CRP_BEYOND_PSE)
        self.assertEqual(ch['donor_d29_sign']['value'], C.DONOR_D29_SIGN)
        self.assertEqual(ch['d29_outlier_cells']['gtap_status'], 'not_in_gtap_text')
        self.assertEqual(ch['ag_table14_2_rows']['value'], C.AG_T142)
        cells = C.load_d29_cells()
        self.assertEqual(set(cells), {('JPN', 'whs'), ('JPN', 'sea'), ('AUS', 'pro'), ('ARG', 'crp')})
        self.assertTrue(cells[('ARG', 'crp')]['export_duty_out'])
        t = C.load_ag_table14_2()
        self.assertNotIn('EGY', t)                                                     # Egypt keeps its KF estimate
        for c in ('TUR', 'SAU', 'DZA'):
            self.assertEqual((t[c]['labour'], t[c]['capital']), (0.57, 0.32))         # Table 14.2 Middle East, GTAP
        self.assertAlmostEqual(t['TUR']['land'], 0.11)
        for c in ('DEU', 'FRA', 'NLD'):
            self.assertEqual((t[c]['labour'], t[c]['capital']), (0.49, 0.34))         # Table 14.2 NWE, Fuglie
        self.assertEqual((t['CRI']['labour'], t['CRI']['capital']), (0.47, 0.25))     # Mexico row, GTAP
        self.assertFalse(set(t) & set(C.load_ag_outliers()))

    def test_new_config_mutations_stop(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, 'c.csv')
            with open(p, 'w', newline='') as f:
                w = csv.writer(f)
                w.writerow(C.D29_CELLS_COLUMNS)
                w.writerow(['JPN', 'whs', 'maybe', 'r', 'x', 'y'])
            with self.assertRaises(C.ConfigError):
                C.load_d29_cells(p)
            with open(p, 'w', newline='') as f:
                w = csv.writer(f)
                w.writerow(C.AG_T142_COLUMNS)
                w.writerow(['TUR', 'Middle East', 'GTAP', '70', '32', 'r', 'x', 'y'])  # leaves no land
            with self.assertRaises(C.ConfigError):
                C.load_ag_table14_2(p)
            with open(p, 'w', newline='') as f:
                w = csv.writer(f)
                w.writerow(C.AG_T142_COLUMNS)
                w.writerow(['TUR', 'Middle East', 'USDA', '57', '32', 'r', 'x', 'y'])  # not a Table 14.2 source
            with self.assertRaises(C.ConfigError):
                C.load_ag_table14_2(p)
        finally:
            shutil.rmtree(d)


if __name__ == '__main__':
    unittest.main()


class FableRoundTest(unittest.TestCase):
    """Fable QA B-02 (national labour tables), F-03 (payroll and property netted out of D29), F-05 / A-06 (land support)."""

    def test_land_factor_use_wedge(self):
        ev = pd.DataFrame([dict(sector='crp', factor='land', evfp=10.0), dict(sector='crp', factor='capital', evfp=50.0),
                           dict(sector='crp', factor='clerks', evfp=40.0)])
        df, r = M.factor_taxes(ev, ssc=0.0, payroll_property=0.0, pit=0.0, cit=6.0, support={'land': 25.0, 'capital': 5.0},
                               support_wedge='land_factor_use')
        land, cap = df.iloc[0], df.iloc[1]
        self.assertAlmostEqual(land['ftax'], -25.0)                       # land support a factor-use subsidy
        self.assertAlmostEqual(land['evfb'], 35.0)
        self.assertGreater(land['itax'], 0.0)                              # land income tax is the CIT share, not < -100%
        self.assertAlmostEqual(cap['ftax'], 0.0)                           # capital support stays a negative income tax
        self.assertAlmostEqual(df['fbep'].sum(), 30.0)                     # FBEP memo keeps the whole support
        self.assertAlmostEqual(r['fbep_land'], 25.0)
        self.assertAlmostEqual(df['itax'].sum(), 6.0 - 5.0)
        old, _ = M.factor_taxes(ev, 0.0, 0.0, 0.0, 6.0, {'land': 25.0, 'capital': 5.0}, support_wedge='income')
        self.assertLess((old.iloc[0]['evfb'] - old.iloc[0]['evos']) / old.iloc[0]['evfb'], -1.0)   # the F-05 symptom
        rates = pd.DataFrame([dict(region='R', ssc_musd=0.0, payroll_property_musd=0.0, payroll_property_booked_musd=0.0,
                                   pit_musd=0.0, cit_musd=6.0, support_land_musd=25.0, support_capital_musd=5.0,
                                   support_labour_musd=0.0, support_factors_musd=0.0, fbep_land_musd=25.0)])
        self.assertEqual(K.tax_totals(df.assign(region='R'), rates, 'land_factor_use')[0], 0)
        self.assertEqual(K.tax_totals(df.assign(region='R'), rates, 'income')[0], 1)              # mutation: wrong wedge

    def test_to_matrix_split_and_exclusions(self):
        from s12_factors import national as NL
        tab = dict(kind='cross', year=2022, cross=pd.DataFrame(dict(occ=['a', 'b', 'tot', 'a'], ind=['x', 'x', 'x', 'y'],
                                                                     value=[10.0, 6.0, 16.0, 4.0])))
        prof = np.array([0, 0.3, 0.1, 0, 0, 0, 0, 0, 0.0]) + 0.0
        N, no, ni, unm = NL.to_matrix(tab, {'a': ['2', '3'], 'b': ['9'], 'tot': []}, {'x': ['C'], 'y': ['D', 'E']}, prof)
        self.assertEqual(unm, [])
        self.assertAlmostEqual(no.sum(), 20.0)                             # the total row is left out, nothing twice
        self.assertAlmostEqual(N[1, SECTIONS_.index('C')], 7.5)            # 'a' shared 3:1 over ISCO 2 and 3
        self.assertAlmostEqual(N[2, SECTIONS_.index('C')], 2.5)
        self.assertAlmostEqual(N[1, SECTIONS_.index('D')], 1.5)            # 'y' shared equally over D and E
        _, _, _, unm = NL.to_matrix(tab, {'a': ['2'], 'b': ['9']}, {'x': ['C'], 'y': ['D']}, prof)
        self.assertEqual(unm, ['occ tot'])                                 # mutation: an unmapped code is reported
        _, _, _, unm = NL.to_matrix(tab, {'a': ['2'], 'b': ['9'], '*': []}, {'x': ['C'], 'y': ['D']}, prof)
        self.assertEqual(unm, [])                                          # '*' leaves the rest out

    def test_ras(self):
        N = LAB.ras(np.array([[1.0, 1.0], [1.0, 3.0]]), [4.0, 6.0], [5.0, 5.0])
        np.testing.assert_allclose(N.sum(axis=1), [4.0, 6.0], rtol=1e-8)
        np.testing.assert_allclose(N.sum(axis=0), [5.0, 5.0], rtol=1e-8)

    def test_national_shares_wages(self):
        secs = list(SECTIONS_)
        N = np.zeros((9, len(secs)))
        N[1, 0], N[8, 0], N[1, 2], N[8, 2] = 10.0, 30.0, 30.0, 10.0           # A mostly elementary, C mostly professionals
        for k in range(9):
            N[k, 2] += 1.0
            N[k, 0] += 1.0
        tabs = {'ZZZ': dict(N=N, N_occ=N.sum(axis=1), N_ind=N.sum(axis=0), year=2022, source='t')}
        empty = pd.DataFrame(columns=['iso3', 'source', 'cls', 'code', 'year', 'value'])
        prior = np.array([3.0, 2.0, 1.5, 1.0, 0.8, 0.7, 0.9, 0.9, 0.6])
        sh, meta = LAB.national_shares(tabs, empty, empty, list(GROUPS9_), 2022, {'ZZZ': prior})
        self.assertEqual(meta.iloc[0]['occ_wage_source'], 'regional relative wage profile')
        a = sh[(sh['section'] == 'A')].set_index('group')['share']
        c = sh[(sh['section'] == 'C')].set_index('group')['share']
        self.assertGreater(c['off_mgr_pros'], a['off_mgr_pros'])          # the cross table's own mix by section
        self.assertAlmostEqual(sh.groupby('section')['share'].sum().max(), 1.0)
        bad = {'ZZZ': prior * np.nan}
        sh2, meta2 = LAB.national_shares(tabs, empty, empty, list(GROUPS9_), 2022, bad)
        self.assertIn('wage_prior_missing', meta2.iloc[0]['flags'])      # a missing prior never makes NaN shares
        self.assertTrue(np.isfinite(sh2['share']).all())

    def test_national_config(self):
        from s12_factors import national as NL
        from s12_factors.method import SECTIONS
        src = C.load_national_sources(readers=set(NL.READERS) | {'ilostat_cross'})
        self.assertTrue({'CHN', 'CAN', 'AUS', 'SAU', 'TWN', 'HKG'} <= set(src))
        self.assertNotIn('JPN', src)                                       # not ISCO-08 comparable without a control
        mp = C.load_national_map(sections=SECTIONS)
        for c, x in src.items():
            if x['source'] != 'ilostat_cross':
                self.assertIn(x['source'], mp)
        ch = C.load_choices()
        self.assertEqual(ch['labour_national_tables']['value'], C.LABOUR_NATIONAL)
        self.assertEqual(ch['factor_support']['value'], C.SUPPORT_LAND_FACTOR_USE)
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, 'm.csv')
            with open(C.NATIONAL_MAP_PATH) as f, open(p, 'w') as g:
                g.write(f.read() + 'qatar_lfs,ind,Nowhere,Z,bad target\n')
            with self.assertRaises(C.ConfigError):                       # mutation: a target that is not a section
                C.load_national_map(p, sections=SECTIONS)
        finally:
            shutil.rmtree(d)


class NationalReadersTest(unittest.TestCase):
    """The B-02 readers on the committed source files: totals equal the published totals."""
    D = os.path.join(os.path.dirname(C.BUILD), 'data')

    def test_cross_tables(self):
        from s12_factors import national as NL
        t = NL.dgbas_table49(os.path.join(self.D, 'twn_manpower', 'dgbas_2022_table49_employed_by_occupation_by_industry.xls'), 2022)
        x = t['cross']
        self.assertAlmostEqual(x[x['ind'] == 'Total']['value'].sum(), 11418.0, delta=2.0)   # Table 49 total (rounded cells)
        self.assertIsNone(NL.dgbas_table49('unused', 2017))                               # 2022 only: never after the base year
        h = NL.censtatd_210_06308(os.path.join(self.D, 'hk_censtatd', 'table_210-06308.json'), 2022)
        self.assertEqual(h['year'], 2022)
        self.assertAlmostEqual(h['cross']['value'].sum(), 3613.2, delta=1.0)             # leaf groups add to the total (rounding)
        k = NL.kosis_dt_1es3b33s(os.path.join(self.D, 'kosis_lalfs', 'kosis_DT_1ES3B33S_sex_industry_occupation_2013H1-2024H1_utf8.csv'), 2022)
        self.assertAlmostEqual(k['cross']['value'].sum(), (28078.3 + 28417.9) / 2, delta=20.0)
        q = NL.qatar_lfs(os.path.join(self.D, 'qatar_lfs', 'economically-active-population-15-years-and-above-by-occupation-and-economic-activity.csv'), 2022)
        self.assertAlmostEqual(q['cross']['value'].sum(), 2130356.0)

    def test_margins(self):
        from s12_factors import national as NL
        s = NL.gastat_lms(os.path.join(self.D, 'gastat_lms', 'LMS_2022_Q4_EN_1.xlsx'), 2022)
        self.assertAlmostEqual(s['occ']['Managers'], 297015.0)
        self.assertAlmostEqual(s['occ'].drop('Total').sum(), s['occ']['Total'])
        c = NL.nbs_census_2020(os.path.join(self.D, 'nbs_census_chn', 'B0404.xls'), os.path.join(self.D, 'nbs_census_chn', 'B0406.xls'), 2022)
        sub = c['ind'][[i for i in c['ind'].index if i.endswith('|小计')]]
        self.assertAlmostEqual(sub.sum(), 65631786.0)                                     # B0404 national total


class GollinIloCapTest(unittest.TestCase):
    """Beta v4 G2/P40 (gollin_ilo_cap): Gollin labour capped at the ILO SDG 10.4.1 labour income share, D1 the floor."""

    def test_default_on(self):
        # decision package (S16 aligned defaults 2026-10-26; David leans to it): on, with off as the alternative
        self.assertEqual(C.load_choices()['gollin_ilo_cap']['value'], C.GOLLIN_ILO_CAP)
        self.assertIn('off', C.CHOICES['gollin_ilo_cap'])

    def test_return_fraction(self):
        self.assertEqual(M.ilo_cap_return(50.0, 10.0, 55.0), 0.0)        # below the ILO share: not raised
        self.assertEqual(M.ilo_cap_return(60.0, 0.0, 50.0), 0.0)         # no Gollin addition to return
        self.assertAlmostEqual(M.ilo_cap_return(60.0, 20.0, 55.0), 0.25)
        self.assertEqual(M.ilo_cap_return(60.0, 5.0, 40.0), 1.0)         # D1 is the floor

    def test_region_share(self):
        gdp = {'A': 300.0, 'B': 100.0, 'C': 100.0}
        ilo = {'A': 0.5, 'B': 0.3}
        self.assertAlmostEqual(M.region_ilo_share(['A', 'B', 'C'], gdp, ilo, 0.5), (150.0 + 30.0) / 400.0)
        self.assertIsNone(M.region_ilo_share(['B', 'C'], gdp, ilo, 0.6))  # members with a value hold 50% < 60%
        self.assertIsNone(M.region_ilo_share(['C'], gdp, ilo, 0.5))
