"""Mutation tests for the S15 method, the S15 hard checks and the config stop.

A small synthetic world (two regions, two commodities of which one is a margin, two factors) is written to HAR
by the real writer and every check is called on it (it must pass) and on a mutated copy (it must fail). The HAR
read-back test uses the independent reader (harpy3) when S15_HARPY_PYTHON names a Python that has it
(requirements-s15-reader.txt); otherwise it is skipped.

Run from dataset/build:  python3 -m unittest tests.test_s15_checks -v
"""
import copy
import csv
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BUILD)

from s15_har import checks as K  # noqa: E402
from s15_har import config as C  # noqa: E402
from s15_har import har as H  # noqa: E402
from s15_har import method as M  # noqa: E402
from s15_har import params as PR  # noqa: E402


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
        for k in C.TABLES:
            self.assertFalse(C.load_table(k).empty)

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



# ------------------------------------------------------------------ parameter editions (GTAP 12 ch.16 default, GTAP 7 ch.14)
REPO = os.path.dirname(os.path.dirname(BUILD))
CH16 = os.path.join(REPO, 'docs', 'gtap_method_sources', 'GTAP12_ch16_behavioral_parameters.txt')


def cited_line_gaps(df, cols, doc_lines):
    """Rows whose values are not printed on the lines their source column cites ('... lines a and b').
    cols: (column, k) pairs, k = 0 for the first cited line, 1 for the second."""
    import re
    bad = []
    for i, d in df.iterrows():
        ln = [int(x) for x in re.findall(r'lines (\d+) and (\d+)', d['source'])[0]]
        for col, k in cols:
            toks = doc_lines[ln[k] - 1].split()
            if not any(abs(float(t) - float(d[col])) < 1e-12 for t in toks if re.fullmatch(r'-?\d+\.\d+', t)):
                bad.append((i, col, ln[k]))
        if 'cde_category' in d:                     # Table 16.4 prints code, category pairs
            toks = doc_lines[ln[1] - 1].split()
            pairs = dict(zip(toks[::2], toks[1::2]))
            if pairs.get(d['gtap12']) != d['cde_category']:
                bad.append((i, 'cde_category', ln[1]))
    return bad


class EditionTest(unittest.TestCase):
    """QA finding #7 (David 2026-10-24, "stick to GTAP"): GTAP 12 ch.16 is the default, GTAP 7 ch.14 the alternative."""
    def setUp(self):
        self.ch = C.load_choices()
        self.T = {k: C.load_table(k) for k in C.TABLES}

    def with_edition(self, ed):
        ch = copy.deepcopy(self.ch)
        e = C.EDITIONS[ed]
        ch['parameters']['value'] = ed
        for c in ('cde_targets', 'sector_means', 'cde_price_reading'):
            ch[c]['value'] = e[c]
        return ch

    def test_default_is_gtap12(self):
        self.assertEqual(self.ch['parameters']['value'], 'gtap12_ch16_standard')
        ed, tab, sm, tg, tr = C.edition_tables(self.ch, self.T)
        self.assertEqual(ed['label'], 'GTAP 12 ch.16')
        self.assertEqual(len(tab), 65)                       # the 65 GTAP 12 sectors of Table 16.2
        self.assertEqual(tg['target_region'].nunique(), 163)  # the 163 regions of Tables 16.6/16.7
        self.assertEqual(len(tg), 1630)
        self.assertEqual(set(tg['category']), set(PR.CATEGORIES))

    def test_mixed_editions_stop(self):
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, 'c.csv')
            with open(C.CHOICES_PATH, newline='') as fh:
                rows = list(csv.DictReader(fh))
            for c, v in (('parameters', 'gtap7_ch14_standard'), ('cde_targets', 'gtap7_tables_14_5_14_6_by_region'),
                         ('sector_means', 'unweighted_mean_of_gtap7_members'), ('cde_price_reading', 'table_14_6_as_compensated')):
                bad = [dict(r, value=v) if r['choice'] == c else r for r in rows]
                with open(path, 'w', newline='') as fh:
                    w = csv.DictWriter(fh, fieldnames=C.CHOICE_COLUMNS)
                    w.writeheader()
                    w.writerows(bad)
                with self.assertRaises(C.ConfigError, msg=c):
                    C.load_choices(path)
            # the whole GTAP 7 set together loads
            g7 = [dict(r, value=C.EDITIONS['gtap7_ch14_standard'].get(r['choice'], r['value'])) if r['choice'] in
                  ('cde_targets', 'sector_means', 'cde_price_reading') else (dict(r, value='gtap7_ch14_standard') if r['choice'] == 'parameters' else r)
                  for r in rows]
            with open(path, 'w', newline='') as fh:
                w = csv.DictWriter(fh, fieldnames=C.CHOICE_COLUMNS)
                w.writeheader()
                w.writerows(g7)
            self.assertEqual(C.load_choices(path)['parameters']['value'], 'gtap7_ch14_standard')
        finally:
            shutil.rmtree(tmp)

    def test_both_editions_cover_the_same_sectors(self):
        out = {}
        for ed in C.EDITIONS:
            _, tab, sm, _, _ = C.edition_tables(self.with_edition(ed), self.T)
            out[ed] = PR.sector_elasticities(sm, tab)
        self.assertEqual(sorted(out['gtap12_ch16_standard'].index), sorted(out['gtap7_ch14_standard'].index))
        g12, g7 = out['gtap12_ch16_standard'], out['gtap7_ch14_standard']
        # Table 16.2 against Table 14.2: sigma VA 0.26 in primary agriculture (0.24), 1.40 in construction (1.68)
        self.assertAlmostEqual(g12.loc['crp', 'esubva'], 0.26)
        self.assertAlmostEqual(g7.loc['crp', 'esubva'], 0.24)
        self.assertAlmostEqual(g12.loc['con', 'esubva'], 1.40)
        self.assertAlmostEqual(g7.loc['con', 'esubva'], 1.68)
        self.assertAlmostEqual(g12.loc['eeq', 'esubd'], 4.40)          # eeq is a GTAP 12 sector of its own
        # Table 16.4 categories
        self.assertEqual(g12.loc['pet', 'cde_category'], 'Mnfcs')
        self.assertEqual(g12.loc['its', 'cde_category'], 'TransComm')
        self.assertEqual(g12.loc['oil', 'cde_category'], 'GrainCrops')  # as printed in Table 16.4
        for s in g12.index:                                             # sigma M = 2 sigma D (rule of two)
            self.assertAlmostEqual(g12.loc[s, 'esubm'], 2 * g12.loc[s, 'esubd'], places=3)

    def test_sector_categories_follow_table_16_4(self):
        # a single-member sector takes its member's Table 16.4 category
        _, tab, sm, _, _ = C.edition_tables(self.ch, self.T)
        cat = tab.set_index('code')['cde_category']
        for r in sm.itertuples():
            mem = r.members.split()
            if len(set(cat[m] for m in mem)) == 1:
                self.assertEqual(r.cde_category, cat[mem[0]], r.sector)

    @unittest.skipUnless(os.path.exists(CH16), 'GTAP 12 ch.16 text not in the checkout')
    def test_transcription_matches_chapter_text(self):
        with open(CH16) as fh:
            doc = fh.read().split('\n')
        t = self.T['table16_2']
        tcols = [('esubd', 0), ('esubm', 0), ('esubva', 0)]
        self.assertEqual(cited_line_gaps(t, tcols, doc), [])
        tg = self.T['cde_targets_gtap12']
        gcols = [('income_elasticity', 0), ('compensated_own_price_magnitude', 1)]
        self.assertEqual(cited_line_gaps(tg, gcols, doc), [])
        # mutations: one changed value or category is caught
        t2 = t.copy(); t2.loc[0, 'esubva'] = 0.24
        self.assertEqual(len(cited_line_gaps(t2, tcols, doc)), 1)
        t3 = t.copy(); t3.loc[15, 'cde_category'] = 'TransComm'      # oil back to the GTAP 7 category
        self.assertEqual(len(cited_line_gaps(t3, tcols, doc)), 1)
        tg2 = tg.copy(); tg2.loc[5, 'compensated_own_price_magnitude'] = 0.5
        self.assertEqual(len(cited_line_gaps(tg2, gcols, doc)), 1)

    def test_target_rows(self):
        ed, _, _, tg, tr = C.edition_tables(self.ch, self.T)
        regions = pd.DataFrame({'region': ['USA', 'PAL', 'TKM', 'XSM', 'XCB'], 'type': ['single', 'single', 'single', 'composite', 'composite']})
        tab = tr[tr['region'].isin(regions['region'])]
        rows = PR.target_regions(regions, tg, tab, ed['aliases'])
        self.assertEqual(rows.loc['USA', 'rule'], 'own_row')
        self.assertEqual(rows.loc['PAL', 'target_row'], 'PSE')         # Tables 16.6/16.7 code Palestine PSE
        self.assertEqual(rows.loc['TKM', 'target_row'], 'XSU')
        self.assertEqual(rows.loc['XSM', 'rule'], 'mean_of_member_rows')
        self.assertEqual(rows.loc['XCB', 'target_row'], 'HTI JAM XCB XCA')
        with self.assertRaises(ValueError):                            # without the alias PAL has no row
            PR.target_regions(regions, tg, tab, {})
        bad = tab.copy(); bad.loc[bad['region'] == 'TKM', 'target_row'] = 'TKM'
        with self.assertRaises(ValueError):                            # a row the table does not have
            PR.target_regions(regions, tg, bad, ed['aliases'])
        with self.assertRaises(ValueError):                            # a region with neither
            PR.target_regions(regions, tg, tab[tab['region'] != 'TKM'], ed['aliases'])

    def test_negative_income_target_is_floored(self):
        # Table 16.6 prints negative GrainCrops income elasticities for 11 of our regions (USA -0.0046): no CDE point
        # with e > 0 meets them, so the fit is sequential and A11's floor holds INCP at 1e-6
        r = PR.calibrate_region([0.013, 0.3, 0.687], [-0.0046, 0.95, 1.03], [-0.0043, 0.7, 0.5])
        self.assertEqual(r['method'], 'sequential')
        self.assertAlmostEqual(r['e'][0], PR.INCP_FLOOR, delta=1e-12)   # held at the bound by the INCPAR step
        self.assertTrue(np.all(r['e'] >= PR.INCP_FLOOR))
        self.assertTrue(np.all((r['alpha'] > 0) & (r['alpha'] < 1)))

# ------------------------------------------------------------------ synthetic world
SETS = {'REG': ['AAA', 'BBB'], 'COMM': ['crp', 'trn'], 'ACTS': ['crp', 'trn'], 'MARG': ['trn'],
        'ENDW': ['labour', 'capital'], 'ENDT': list(M.ENDT)}


def world():
    """A balanced two-region world: each region makes both goods, sells crp abroad with a trn margin."""
    nr, nc = 2, 2
    D = {h: np.zeros(tuple(len(SETS[d]) for d in dims)) for h, _, _, dims, _ in M.DATA_HEADERS}
    # trade in crp only, both directions; margin 1 on each route, supplied by each region's trn as VST 1
    for s, d in ((0, 1), (1, 0)):
        D['VXSB'][0, s, d] = D['VFOB'][0, s, d] = 10.0
        D['VTWR'][0, 0, s, d] = 1.0
        D['VCIF'][0, s, d] = 11.0
        D['VMSB'][0, s, d] = 11.0
    D['VST'][0, :] = 1.0
    for r in range(nr):
        D['VDFB'][:, :, r] = [[5, 2], [2, 3]]
        D['VMFB'][0, :, r] = [6, 0]
        D['VDPB'][:, r] = [20, 30]
        D['VMPB'][0, r] = 5
        D['VDGB'][1, r] = 10
        D['VDIB'][1, r] = 5
    for h in ('VDF', 'VMF', 'VDP', 'VMP', 'VDG', 'VMG', 'VDI', 'VMI'):
        D[h + 'P'] = D[h + 'B'].copy()
    # supply = demand at basic prices: crp 5+2+20+10 = 37; trn 2+3+30+10+5+1 = 51
    out = np.array([37.0, 51.0])
    for r in range(nr):
        D['MAKB'][:, :, r] = np.diag(out)
        D['MAKS'][:, :, r] = np.diag(out)
        cost = D['VDFP'][:, :, r].sum(axis=0) + D['VMFP'][:, :, r].sum(axis=0)
        va = out - cost
        D['EVFP'][0, :, r] = 0.6 * va
        D['EVFP'][1, :, r] = 0.4 * va
    D['EVFB'] = D['EVFP'].copy()
    D['EVOS'] = D['EVFP'].copy()
    D['VDEP'][:] = 2.0
    D['VKB'][:] = 50.0
    D['POP'][:] = 1.0
    acc = M.regional_accounts(D, SETS['ENDW'].index('capital'))
    D['SAVE'] = acc['SAVE_model'].to_numpy()
    return D


def pars():
    el = pd.DataFrame({'esubd': [2.0, 1.9], 'esubm': [4.0, 3.8], 'esubva': [0.3, 1.4]}, index=['crp', 'trn'])
    sc = pd.DataFrame([('ESBT', 'all', 0), ('ESBC', 'all', 0), ('ETRQ', 'all', -5), ('ESBQ', 'all', 0),
                       ('ESBG', 'all', 1), ('ESBI', 'all', 0), ('ESBS', 'all', 1), ('RFLX', 'all', 10), ('RDLT', 'all', 1),
                       ('ETRE', 'mobile', 0), ('EFLG', 'labour', 'mobile'), ('EFLG', 'capital', 'mobile')],
                      columns=['parameter', 'element', 'value'])
    sc['value'] = sc['value'].astype(object)
    incp = np.full((2, 2), 1.0)
    subp = np.full((2, 2), 0.5)
    return M.parameter_arrays(SETS, el, sc, incp, subp)


class IdentityTest(unittest.TestCase):
    def setUp(self):
        self.D = world()
        self.mi = [SETS['COMM'].index(m) for m in SETS['MARG']]

    def ident(self, D):
        return K.identities(D, self.mi, SETS['REG'], SETS['COMM'])[0]

    def test_world_passes(self):
        self.assertEqual(self.ident(self.D), 0)
        self.assertEqual(K.saving(M.regional_accounts(self.D, 1))[0], 0)
        self.assertEqual(K.signs(self.D)[0], 0)
        self.assertEqual(K.factor_payment(self.D, SETS['REG'], SETS['COMM'])[0], 0)

    def test_identity_mutations_fail(self):
        for h, ix in (('VCIF', (0, 0, 1)), ('VST', (0, 0)), ('VDPB', (0, 0)), ('VMPB', (0, 1)), ('VDFP', (1, 0, 0))):
            D = copy.deepcopy(self.D)
            D[h][ix] += 0.01
            self.assertGreater(self.ident(D), 0, h)

    def test_saving_mutation_fails(self):
        D = copy.deepcopy(self.D)
        D['SAVE'][0] += 0.01
        self.assertGreater(K.saving(M.regional_accounts(D, 1))[0], 0)

    def test_sign_and_factor_mutations_fail(self):
        D = copy.deepcopy(self.D)
        D['VDGB'][0, 0] = -1e-3
        self.assertEqual(K.signs(D)[0], 1)
        D = copy.deepcopy(self.D)
        D['SAVE'][0] = -1.0
        self.assertEqual(K.signs(D)[0], 0)   # SAVE may be negative (S14 NEG-SAVE, report-only)
        D = copy.deepcopy(self.D)
        D['EVFP'][:, 1, 0] = 0
        self.assertEqual(K.factor_payment(D, SETS['REG'], SETS['COMM'])[0], 1)

    def test_dense_totals(self):
        tab = pd.DataFrame({'region': ['AAA', 'BBB', 'BBB'], 'comm': ['crp', 'crp', 'trn'], 'VDGB': [1.0, 2.0, 3.0]})
        spec = [('VDGB', 't', ['comm', 'region'], ['COMM', 'REG'], '')]
        a = {'VDGB': M.dense(tab, ['comm', 'region'], ['COMM', 'REG'], 'VDGB', SETS)}
        self.assertEqual(K.dense_totals(a, {'t': tab}, spec)[0], 0)
        a['VDGB'][0, 0] = 0
        self.assertGreater(K.dense_totals(a, {'t': tab}, spec)[0], 0)
        with self.assertRaises(ValueError):
            M.dense(tab.assign(comm=['crp', 'xyz', 'trn']), ['comm', 'region'], ['COMM', 'REG'], 'VDGB', SETS)


class ParameterTest(unittest.TestCase):
    def test_ranges(self):
        P, rdlt = pars()
        self.assertEqual(rdlt, 1)
        self.assertEqual(K.parameters(P, SETS)[0], 0)
        for h, v in (('ESBD', 0.0), ('SUBP', 1.5), ('INCP', -0.1), ('ETRE', 0.5), ('ESBM', np.nan)):
            Q = copy.deepcopy(P)
            Q[h].flat[0] = v
            self.assertGreater(K.parameters(Q, SETS)[0], 0, h)
        Q = copy.deepcopy(P)
        Q['EFLG'][1] = [0, 1, 0]          # capital sluggish
        self.assertGreater(K.parameters(Q, SETS)[0], 0)
        Q = copy.deepcopy(P)
        Q['EFLG'][0] = [0, 1, 0]          # sluggish labour with ETRE 0
        self.assertGreater(K.parameters(Q, SETS)[0], 0)

    def test_mobile_with_etre_stops(self):
        el = pd.DataFrame({'esubd': [2.0, 2.0], 'esubm': [4.0, 4.0], 'esubva': [1.0, 1.0]}, index=['crp', 'trn'])
        sc = pd.DataFrame([('ESBT', 'all', 0), ('ESBC', 'all', 0), ('ETRQ', 'all', -5), ('ESBQ', 'all', 0), ('ESBG', 'all', 1), ('ESBI', 'all', 0),
                           ('ESBS', 'all', 1), ('RFLX', 'all', 10), ('RDLT', 'all', 1), ('ETRE', 'mobile', -1),
                           ('EFLG', 'labour', 'mobile'), ('EFLG', 'capital', 'mobile')], columns=['parameter', 'element', 'value'])
        with self.assertRaises(ValueError):
            M.parameter_arrays(SETS, el, sc, np.ones((2, 2)), np.full((2, 2), 0.5))

    def test_sector_means(self):
        t = pd.DataFrame({'code': ['pdr', 'wht', 'ely'], 'name': ['', '', ''], 'esubd': [5.0, 4.0, 2.8],
                          'esubm': [10.1, 8.9, 5.6], 'esubva': [0.26, 0.26, 1.26], 'cde_category': ['', '', ''], 'source': ['', '', '']})
        sm = pd.DataFrame({'sector': ['crp', 'ely'], 'members': ['pdr wht', 'ely'], 'cde_category': ['GrainCrops', 'HousUtils'], 'note': ['', '']})
        el = PR.sector_elasticities(sm, t)
        self.assertAlmostEqual(el.loc['crp', 'esubd'], 4.5)
        self.assertAlmostEqual(el.loc['ely', 'esubm'], 5.6)


class CdeTest(unittest.TestCase):
    """GTAP 7 ch.14.6: the CDE elasticities and the calibration that inverts them."""
    s = np.array([0.2, 0.3, 0.5])

    def test_formulas_against_finite_differences(self):
        # CDE implicit utility: sum_i B_i u^(e_i b_i) (p_i/E)^b_i = 1, b = 1 - alpha. Check eta from u -> E numerically
        alpha = np.array([0.3, 0.6, 0.8])
        e = np.array([0.7, 1.1, 1.0])
        b = 1 - alpha
        p = np.ones(3)
        # base point u = 1, E = 1, p = 1: sum B = 1 and s_i proportional to b_i B_i
        B = (self.s / b) / np.sum(self.s / b)

        def demand(E, p):
            # solve sum B u^(e b) (p/E)^b = 1 for u, then shares s_i proportional to b_i B_i u^(e b) (p/E)^b
            lo, hi = 1e-6, 1e6
            for _ in range(200):
                u = np.sqrt(lo * hi)
                f = np.sum(B * u ** (e * b) * (p / E) ** b) - 1
                lo, hi = (lo, u) if f > 0 else (u, hi)
            w = b * B * u ** (e * b) * (p / E) ** b
            return w / w.sum() * E / p

        q0 = demand(1.0, p)
        sh0 = q0 * p / 1.0
        eta_fd = (np.log(demand(1.0 + 1e-6, p)) - np.log(q0)) / np.log(1 + 1e-6)
        p1 = p.copy(); p1[0] *= 1 + 1e-6
        unc_fd = (np.log(demand(1.0, p1)[0]) - np.log(q0[0])) / np.log(1 + 1e-6)
        eta_s, _, unc_s = PR.cde_elasticities(sh0, alpha, e)
        np.testing.assert_allclose(eta_fd, eta_s, rtol=1e-4, atol=1e-5)
        self.assertAlmostEqual(unc_fd, unc_s[0], places=4)

    def test_exact_calibration_hits_targets(self):
        # targets from a known CDE point, so the exact solve must recover it
        alpha0 = np.array([0.3, 0.5, 0.7]); e0 = np.array([0.6, 0.9, 1.2]); e0 = e0 / (self.s @ e0)
        eta0, comp0, _ = PR.cde_elasticities(self.s, alpha0, e0)
        r = PR.calibrate_region(self.s, eta0, -comp0)
        self.assertEqual(r['method'], 'exact')
        np.testing.assert_allclose(r['alpha'], alpha0, rtol=1e-8)
        self.assertLess(r['eta_gap'], 1e-10)
        self.assertLess(r['comp_gap'], 1e-10)
        self.assertAlmostEqual(self.s @ r['eta_model'], 1.0, places=10)   # Engel aggregation
        self.assertAlmostEqual(self.s @ r['e'], 1.0, places=12)

    def test_readings(self):
        # compensated (David's choice): the compensated target is -value; uncompensated adds s eta (Slutsky)
        own = np.array([0.4, 0.6, 0.9])
        rc = PR.calibrate_region(self.s, [0.5, 0.9, 1.2], own, 'compensated')
        np.testing.assert_allclose(rc['comp'], -own)
        ru = PR.calibrate_region(self.s, [0.5, 0.9, 1.2], own, 'uncompensated')
        np.testing.assert_allclose(ru['comp'], -own + self.s * ru['eta'])
        with self.assertRaises(ValueError):
            PR.calibrate_region(self.s, [0.5, 0.9, 1.2], own, 'other')

    def test_bounded_calibration_stays_inside(self):
        # an own-price target far above 1 for a small share needs alpha > 1, so the fit is sequential
        r = PR.calibrate_region(self.s, [0.5, 0.9, 1.2], [2.5, 0.6, 0.9])
        self.assertEqual(r['method'], 'sequential')
        self.assertTrue(np.all((r['alpha'] > 0) & (r['alpha'] < 1)))
        self.assertTrue(np.all(r['e'] > 0))

    def test_sequential_keeps_incpar_identified(self):
        # rich-region pattern: compensated targets near the CDE ceiling put SUBPAR on its bound, where the joint
        # fit left INCPAR free (19.9 and 0 in one region); the sequential fit stays near e = 1 there
        s = np.array([0.01, 0.07, 0.07, 0.15, 0.11, 0.06, 0.08, 0.45])
        eta = np.array([-0.01, 0.9, 0.94, 1.02, 1.01, 1.0, 1.02, 1.02])
        own = np.array([0.006, 0.89, 0.91, 0.81, 0.93, 0.94, 0.98, 0.67])
        r = PR.calibrate_region(s, eta, own)
        self.assertEqual(r['method'], 'sequential')
        self.assertLess(r['e'].max(), 2.5)
        self.assertTrue(np.all(r['e'][3:] > 0.5))
        r2 = PR.calibrate_region(s * (1 + 1e-7), eta, own)
        np.testing.assert_allclose(r2['e'], r['e'], atol=1e-4)

    def test_bvls_matches_kkt(self):
        rng = np.random.default_rng(3)
        for _ in range(50):
            A, b = rng.normal(size=(12, 6)), rng.normal(size=12)
            x = PR._bvls(A, b, 0.0, 0.5)
            g = A.T @ (A @ x - b)
            self.assertTrue(np.all((x >= 0) & (x <= 0.5)))
            inside = (x > 1e-12) & (x < 0.5 - 1e-12)
            self.assertLess(np.abs(g[inside]).max(initial=0), 1e-8)
            self.assertTrue(np.all(g[x <= 1e-12] >= -1e-8) and np.all(g[x >= 0.5 - 1e-12] <= 1e-8))


class IncpFloorTest(unittest.TestCase):
    """Fix list A11: INCP is floored at 1e-6 after normalisation (our choice)."""
    def test_bounded_fit_is_floored(self):
        # a low-share category with near-zero income and own-price targets drives e to zero in the sequential fit
        r = PR.calibrate_region([0.02, 0.3, 0.68], [0.02, 1.0, 1.1], [0.02, 0.7, 0.5])
        self.assertEqual(r['method'], 'sequential')
        self.assertAlmostEqual(r['e'][0], PR.INCP_FLOOR, delta=1e-12)   # the INCPAR step holds it at the bound
        self.assertTrue(np.all(r['e'] >= PR.INCP_FLOOR))

    def test_exact_fit_is_untouched(self):
        s = np.array([0.2, 0.3, 0.5])
        eta, comp, _ = PR.cde_elasticities(s, [0.3, 0.6, 0.8], [0.6, 1.0, 1.2])
        r = PR.calibrate_region(s, eta, -comp)
        self.assertEqual(r['method'], 'exact')
        self.assertFalse(r['floored'].any())

    def test_check_catches_a_cell_below_the_floor(self):
        incp = np.full((3, 2), 0.5)
        self.assertEqual(K.incp_floor(incp, PR.INCP_FLOOR)[0], 0)
        incp[1, 0] = 1e-12
        self.assertEqual(K.incp_floor(incp, PR.INCP_FLOOR)[0], 1)
        incp[2, 1] = np.nan
        self.assertEqual(K.incp_floor(incp, PR.INCP_FLOOR)[0], 2)


class ReadBackTest(unittest.TestCase):
    def test_dims(self):
        exp = M.expected_dims(SETS)
        found = {h: v[2] for h, v in exp.items()}
        self.assertEqual(K.dims(found, exp)[0], 0)
        bad = dict(found); bad['VCIF'] = (2, 2, 3)
        self.assertGreater(K.dims(bad, exp)[0], 0)
        bad = dict(found); bad.pop('ESBD')
        self.assertGreater(K.dims(bad, exp)[0], 0)
        bad = dict(found); bad['XTRA'] = (1,)
        self.assertGreater(K.dims(bad, exp)[0], 0)

    def test_sets(self):
        found = {k: [e.lower() for e in v] for k, v in SETS.items()}
        self.assertEqual(K.sets_match(found, SETS)[0], 0)
        bad = dict(found); bad['REG'] = ['bbb', 'aaa']
        self.assertGreater(K.sets_match(bad, SETS)[0], 0)
        bad = dict(found); bad['COMM'] = ['crp']
        self.assertGreater(K.sets_match(bad, SETS)[0], 0)

    def test_float32(self):
        src = {'A': np.array([1.0 / 3, 1e9 + 0.1, 0.0])}
        self.assertEqual(K.float32_match({'A': src['A'].astype(np.float32).astype(float)}, src)[0], 0)
        self.assertGreater(K.float32_match({'A': src['A'] * (1 + 1e-6)}, src)[0], 0)
        self.assertGreater(K.float32_match({'A': src['A'][:2]}, src)[0], 0)
        self.assertGreater(K.float32_match({}, src)[0], 0)


class MapGateTest(unittest.TestCase):
    def test_gate(self):
        acc = pd.DataFrame({'SAVE': [10.0, -3.0, 5.0], 'Y': [100.0, 2.0, 50.0]})
        regs = ['a', 'b', 'c']
        rmap = pd.DataFrame({'region': ['a', '*'], 'group': ['A', 'ROW']})
        g = M.map_groups(regs, rmap)
        self.assertEqual(g, ['A', 'ROW', 'ROW'])
        self.assertEqual(K.map_gate(M.map_saving_gate(acc, regs, g))[0], 0)
        alone = M.map_saving_gate(acc, regs, ['A', 'B', 'C'])          # b alone: SAVE/Y = -1.5
        self.assertGreater(K.map_gate(alone)[0], 0)
        with self.assertRaises(ValueError):
            M.map_groups(regs, pd.DataFrame({'region': ['zzz', '*'], 'group': ['Z', 'R']}))


# ------------------------------------------------------------------ HAR writer
class HarTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.D = world()
        self.P, self.rdlt = pars()
        self.paths = M.write_har(self.tmp, SETS, self.D, self.P, self.rdlt, ['test', 'y2022', 's14_x'])

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_chunks_cover_array(self):
        for sizes in ([7], [3, 5], [200, 60], [51, 51, 168], [4, 51, 168, 168]):
            ch = H._real_chunks(sizes)
            seen = 0
            for rng in ch:
                off, cnt = H._span(sizes, rng)
                self.assertLessEqual(cnt, H.MAX_REALS)
                self.assertEqual(off, seen)
                seen += cnt
            self.assertEqual(seen, int(np.prod(sizes)))

    def test_float32_gap(self):
        a = np.array([1.0 / 3, 1e9 + 0.1, 0.0])
        self.assertLessEqual(H.float32_relative_gap(a, a.astype(np.float32).astype(float)), 1.2e-7)
        self.assertGreater(H.float32_relative_gap(a, a * (1 + 1e-6)), 1.2e-7)

    def test_files_written(self):
        for p in self.paths.values():
            self.assertGreater(os.path.getsize(p), 0)

    @unittest.skipUnless(os.environ.get('S15_HARPY_PYTHON'), 'S15_HARPY_PYTHON not set (harpy3 reader)')
    def test_harpy_reads_back(self):
        dump = os.path.join(self.tmp, 'dump')
        subprocess.run([os.environ['S15_HARPY_PYTHON'], '-I', os.path.join(BUILD, 's15_har', 'read_har.py'), self.tmp, dump],
                       check=True, capture_output=True)
        with open(os.path.join(dump, 'index.txt')) as fh:
            idx = [l.split('|') for l in fh.read().splitlines()]
        found = {r[1]: tuple(int(x) for x in r[3].split('x')) if r[3] else () for r in idx}
        exp = M.expected_dims(SETS)
        self.assertEqual(K.dims({h: v for h, v in found.items()}, exp)[0], 0, K.dims(found, exp)[1])
        vcif = np.load(os.path.join(dump, 'dat_VCIF.npy'))
        np.testing.assert_allclose(vcif, self.D['VCIF'], rtol=1.2e-7)
        esbd = np.load(os.path.join(dump, 'par_ESBD.npy'))
        np.testing.assert_allclose(esbd, self.P['ESBD'], rtol=1.2e-7)
        read = {h: np.load(os.path.join(dump, f'dat_{h}.npy')) for h, *_ in M.DATA_HEADERS}
        self.assertEqual(K.identities(read, [1], SETS['REG'], SETS['COMM'])[0], 0)


if __name__ == '__main__':
    unittest.main()
