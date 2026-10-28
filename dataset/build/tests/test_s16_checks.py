"""Mutation tests for the S16 checks, the map resolution and the config stop.

Each check is called on a small synthetic input (it must pass) and on a mutated copy (it must fail). The map
suite itself (Julia) is not run here; the stage runs it.

Run from dataset/build:  python3 -m unittest tests.test_s16_checks -v
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

from lib.stagekit import sha256  # noqa: E402
from s16_final import checks as K  # noqa: E402
from s16_final import config as C  # noqa: E402
from s16_final import gtap_compare as G  # noqa: E402
from s16_final import maps as MP  # noqa: E402


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

    def test_maps_name_existing_schemes_without_fuel_pooling(self):
        # fix list A13: S14 seeds the one-sided pairs, so no map pools coal, oil and gas any more
        schemes = C.load_table('schemes')
        self.assertNotIn('s7_fuels', schemes.columns)
        for m in C.load_table('maps').itertuples():
            for sc in m.schemes.split('|'):
                self.assertIn(sc, schemes.columns, m.map)
        self.assertEqual(C.load_choices()['one_sided_pairs']['value'], 'upstream_fix_first')
        rules = C.load_table('ledger_rules')
        from s14_assembly import method as M14
        for rule in (M14.RULE_SMALL, M14.RULE_SEED, M14.RULE_CARVE, M14.RULE_NATRES):
            self.assertTrue(((rules['stage'] == 'S14_final_assembly') & (rules['rule'] == rule)).any(), rule)

    def test_mutations_stop(self):
        for rows in (self.rows[1:], self.rows + [dict(self.rows[0])], [dict(self.rows[0], value='other')] + self.rows[1:],
                     [dict(self.rows[0], decided_by='')] + self.rows[1:]):
            self.write(rows)
            with self.assertRaises(C.ConfigError):
                C.load_choices(self.path)


def world():
    """Two regions (A, B), two commodities (g, m; m is the margin), one factor."""
    sets = dict(REG=['A', 'B'], COMM=['g', 'm'], ACTS=['g', 'm'], MARG=['m'], ENDW=['capital'])
    D = {}
    for h in ('VDFB', 'VDFP', 'VMFB', 'VMFP', 'MAKS', 'MAKB'):
        D[h] = np.ones((2, 2, 2))
    for h in ('VDPB', 'VDPP', 'VMPB', 'VMPP', 'VDGB', 'VDGP', 'VMGB', 'VMGP', 'VDIB', 'VDIP', 'VMIB', 'VMIP'):
        D[h] = np.ones((2, 2))
    for h in ('EVFB', 'EVFP', 'EVOS'):
        D[h] = np.ones((1, 2, 2))
    for h in ('VXSB', 'VFOB', 'VCIF', 'VMSB'):
        D[h] = np.ones((2, 2, 2))
    D['VST'] = np.ones((1, 2))
    D['VTWR'] = np.zeros((1, 2, 2, 2))
    return sets, D


class SubsidyTest(unittest.TestCase):
    def setUp(self):
        self.sets, self.D = world()
        self.io = pd.DataFrame(columns=['region', 'row', 'column', 'value'])
        self.sup = pd.DataFrame(columns=['region', 'basis', 'sector', 'value_musd'])
        self.xs = pd.DataFrame(columns=['region', 'sector', 'booked'])
        self.rb = pd.DataFrame(columns=['kind', 'key', 'before', 'after'])

    def run_(self):
        return K.subsidy_provenance(self.D, self.sets, self.io, self.sup, self.xs, self.rb)[0]

    def test_seeded_column_traces_to_its_suppliers(self):
        # fix list A13: a seeded column carries its suppliers' subsidies; unsourced unless it is listed as seeded
        self.D['VDFP'][0, 1, 0] = 0.5
        self.assertGreater(self.run_(), 0)
        r, a = self.sets['REG'][0], self.sets['COMM'][1]
        self.assertEqual(K.subsidy_provenance(self.D, self.sets, self.io, self.sup, self.xs, self.rb, {(r, a)})[0], 0)

    def test_no_subsidy_passes(self):
        self.assertEqual(self.run_(), 0)

    def test_unsourced_subsidy_fails_and_sourced_passes(self):
        self.D['VDFP'][0, 1, 0] = 0.5   # g into m in A, purchasers below basic
        self.assertEqual(self.run_(), 1)
        self.io = pd.DataFrame([dict(region='A', row='TLS', column='m', value=-0.5)])
        self.assertEqual(self.run_(), 0)

    def test_export_subsidy_needs_wto_row(self):
        self.D['VFOB'][0, 0, 1] = 0.9
        self.assertEqual(self.run_(), 1)
        self.xs = pd.DataFrame([dict(region='A', sector='g', booked='yes')])
        self.assertEqual(self.run_(), 0)

    def test_output_rounding_needs_ledgered_move(self):
        self.D['MAKB'][1, 1, 1] = 1 - 5e-6
        self.assertEqual(self.run_(), 1)
        self.rb = pd.DataFrame([dict(kind='output tax', key='B m', before=0.0, after=-5e-6)])
        self.assertEqual(self.run_(), 0)

    def test_float32_noise_is_not_a_subsidy(self):
        self.D['VDFP'][0, 1, 0] = 1 - 1e-8
        self.assertEqual(self.run_(), 0)


class TradeTest(unittest.TestCase):
    def test_tariff_power(self):
        sets, D = world()
        D['VMSB'][0, 0, 1] = 1.1
        routes = pd.DataFrame([dict(comm=c, src=s, dst=d, VFOB=1.0, VCIF=1.0, VMSB=1.1 if (c, s, d) == ('g', 'A', 'B') else 1.0)
                               for c in 'gm' for s in 'AB' for d in 'AB'])
        self.assertEqual(K.tariff_power(D, sets, routes)[0], 0)
        D['VMSB'][0, 0, 1] = 1.2    # scaled rate
        self.assertEqual(K.tariff_power(D, sets, routes)[0], 1)
        # zero-rated value added to the route (dilution): the power falls to (1.1 + 1) / 2 and VFOB is off the rebuild
        D['VFOB'][0, 0, 1] = 2.0
        D['VCIF'][0, 0, 1] = 2.0
        D['VMSB'][0, 0, 1] = 2.1
        self.assertEqual(K.tariff_power(D, sets, routes)[0], 2)
        # the same travel in the rebuild (S13 held it): passes
        r2 = routes.copy()
        r2.loc[(r2.comm == 'g') & (r2.src == 'A') & (r2.dst == 'B'), ['VFOB', 'VCIF', 'VMSB']] = [2.0, 2.0, 2.1]
        self.assertEqual(K.tariff_power(D, sets, r2)[0], 0)

    def test_held_trade(self):
        sets, D = world()
        t = pd.DataFrame([dict(region=r, sector=c, X=2.0, M=2.0, VST=(1.0 if c == 'm' else 0.0)) for r in 'AB' for c in 'gm'])
        self.assertEqual(K.held_trade(D, sets, t)[0], 0)
        t.loc[0, 'X'] = 2.1
        self.assertEqual(K.held_trade(D, sets, t)[0], 1)

    def test_vmsb(self):
        sets, D = world()
        self.assertEqual(K.vmsb_ge_vcif(D, sets['REG'], sets['COMM'])[0], 0)
        D['VMSB'][1, 1, 0] = 0.5
        self.assertEqual(K.vmsb_ge_vcif(D, sets['REG'], sets['COMM'])[0], 1)


class BookkeepingTest(unittest.TestCase):
    def test_region_list(self):
        self.assertEqual(K.region_list(['a', 'b'], ['A', 'B'], n=2)[0], 0)
        self.assertGreater(K.region_list(['a', 'c'], ['A', 'B'], n=2)[0], 0)
        self.assertGreater(K.region_list(['a'], ['A', 'B'], n=2)[0], 0)

    def test_ledger(self):
        ok = pd.DataFrame([dict(rule='remove stock change', citation='Aguiar p.8', flag='x', before='1', after='1'),
                           dict(rule='inherited IO subsidy, not an S10 plug', citation='TP01', flag='', before='', after=''),
                           dict(rule='gap absorbed', citation='17A', flag='', before='5', after='2')])
        rules = pd.DataFrame(dict(stage='S1', rule=['remove stock change', 'inherited IO subsidy, not an S10 plug', 'gap absorbed'],
                                  kind=['method', 'method', 'absorbed'], note=''))
        n, _, t = K.ledger({'S1': ok}, rules)
        self.assertEqual(n, 0)
        self.assertEqual((t['absorbed_rows'][0], t['absorbed_musd'][0]), (1, 3.0))
        for bad in (dict(rule='', citation='c', flag=''), dict(rule='remove stock change', citation=' ', flag=''),
                    dict(rule='residual plug to stocks', citation='c', flag=''), dict(rule='a new rule', citation='c', flag='')):
            self.assertEqual(K.ledger({'S1': pd.concat([ok, pd.DataFrame([bad])])}, rules)[0], 1)

    def test_rounding_moves(self):
        m = pd.DataFrame(dict(kind='VCIF', key=['a', 'b'], before=1.0, after=1.0, change=[1e-17, 5e-4]))
        self.assertEqual(K.rounding_moves(m)[0], 0)
        m.loc[1, 'change'] = 0.01
        self.assertEqual(K.rounding_moves(m)[0], 1)

    def test_concepts(self):
        good = [dict(id='a', kind='hard', concept='identity; basis basic vs basic'), dict(id='b', kind='report', concept='C04; basis booked vs cash')]
        self.assertEqual(K.concept_tags(good)[0], 0)
        self.assertEqual(K.concept_tags(good + [dict(id='c', kind='hard', concept='')])[0], 1)
        self.assertEqual(K.concept_tags(good + [dict(id='d', kind='hard', concept='C04; basis booked vs cash')])[0], 1)

    def test_rollup_and_chain(self):
        tmp = tempfile.mkdtemp()
        try:
            def stage(name, ups, fail=False):
                d = os.path.join(tmp, name)
                os.makedirs(d + '/output')
                open(d + '/output/x.csv', 'w').write(name)
                open(d + '/output/SHA256SUMS', 'w').write(f'{sha256(d + "/output/x.csv")}  x.csv\n')
                json.dump([dict(id='c', kind='hard', status='FAIL' if fail else 'PASS')], open(d + '/checks.json', 'w'))
                up = ''.join(f'upstream {u} commit c stamped t SHA256SUMS {sha256(os.path.join(tmp, u, "output", "SHA256SUMS"))}\n' for u in ups)
                open(d + '/STAMP', 'w').write(f'{name}\n{up}output SHA256SUMS sha256 {sha256(d + "/output/SHA256SUMS")}\n')
            stage('S01', [])
            stage('S02', ['S01'])
            self.assertEqual(K.rollup(tmp, ['S01', 'S02'], sha256)[0], 0)
            open(os.path.join(tmp, 'S01/output/SHA256SUMS'), 'a').write('changed\n')   # S01 rerun after S02 stamped
            self.assertEqual(K.rollup(tmp, ['S01', 'S02'], sha256)[0], 2)               # S01 unbound, S02 chain broken
        finally:
            shutil.rmtree(tmp)


class MapTest(unittest.TestCase):
    def setUp(self):
        self.regs = ['A', 'B', 'C', 'K']
        self.comm = ['g', 'o']
        self.acc = pd.DataFrame(dict(SAVE=[10.0, 5.0, 5.0, -3.0], Y=[50.0, 30.0, 30.0, 2.0]), index=self.regs)
        self.acc['saving_share'] = self.acc['SAVE'] / self.acc['Y']
        self.dom = np.ones((2, 4))
        self.imp = np.ones((2, 4))
        self.schemes = pd.DataFrame(dict(fine=['g', 'o'], coarse=['all', 'all']), index=self.comm)

    def maps(self, regions, schemes='fine|coarse', kind='fixed'):
        return pd.DataFrame([dict(map='m', kind=kind, regions=regions, schemes=schemes, tariff_shock='', purpose='')])

    def test_one_sided_pair_moves_to_next_scheme(self):
        self.dom[1, 1] = 0.0   # B buys o only from imports
        rep = MP.resolve(self.maps('B'), self.schemes, self.acc, self.regs, self.comm, self.dom, self.imp, ['K'])[3]
        self.assertEqual(rep.loc[0, 'scheme'], 'coarse')
        rep = MP.resolve(self.maps('B', 'fine'), self.schemes, self.acc, self.regs, self.comm, self.dom, self.imp, ['K'])[3]
        self.assertEqual(rep.loc[0, 'scheme'], '')
        # pooled with A, B has a donor: the fine scheme stands
        rep = MP.resolve(self.maps('C'), self.schemes, self.acc, self.regs, self.comm, self.dom, self.imp, ['K'])[3]
        self.assertEqual(rep.loc[0, 'scheme'], 'fine')

    def test_carry_save_alone_and_gate(self):
        rep = MP.resolve(self.maps('K'), self.schemes, self.acc, self.regs, self.comm, self.dom, self.imp, ['K'])[3]
        self.assertEqual(rep.loc[0, 'carry_save_named'], 'K')
        self.assertIn('k', rep.loc[0, 'gate_fail'])
        rep = MP.resolve(self.maps('A'), self.schemes, self.acc, self.regs, self.comm, self.dom, self.imp, ['K'])[3]
        self.assertEqual((rep.loc[0, 'carry_save_named'], rep.loc[0, 'gate_fail']), ('', ''))

    def test_gate_exception_within_limit_only(self):
        g = pd.DataFrame([dict(map='m', group='row', SAVE=1.0, Y=2.0, sigma_save=0.5, sigma_qinv=1.0002),
                          dict(map='n', group='row', SAVE=1.0, Y=2.0, sigma_save=0.5, sigma_qinv=1.0002),
                          dict(map='m', group='a', SAVE=1.0, Y=2.0, sigma_save=0.5, sigma_qinv=0.3)])
        exc = pd.DataFrame([dict(map='m', group='row', measure='sigma_qinv', limit=1.001, decided_by='', decided_at='', basis='')])
        fails, excepted = MP.gate_split(g, exc)
        self.assertEqual(list(zip(fails['map'], fails['group'])), [('n', 'row')])
        self.assertEqual(list(zip(excepted['map'], excepted['group'])), [('m', 'row')])
        g.loc[0, 'sigma_qinv'] = 1.01   # past the limit: fails again
        fails, excepted = MP.gate_split(g, exc)
        self.assertEqual(len(fails), 2)
        self.assertTrue(excepted.empty)
        for e in C.load_table('gate_exceptions').itertuples():
            self.assertIn(e.measure, ('sigma_save', 'sigma_qinv'))
            self.assertIn(e.map, set(C.load_table('maps')['map']))

    def test_pools_and_tails(self):
        self.assertEqual(MP.group_regions(self.regs, ['P=A+B', 'C']), ['p', 'p', 'c', 'row'])
        tails = MP.saving_tails(self.acc, ['K'], n_low=1)
        self.assertNotIn('K', tails)
        self.assertLessEqual((self.acc['SAVE'].sum() - self.acc.loc[tails, 'SAVE'].sum()) / self.acc['SAVE'].sum(), 1)


class GtapCompareTest(unittest.TestCase):
    def test_common_groups(self):
        conc = pd.DataFrame(dict(gtap_code=['A', 'B', 'C'], sectors=['x', 'x', 'y;z'], relation=['merged', 'merged', 'split']))
        g, s = G.common_groups(conc)
        self.assertEqual(g, {'a': 'x', 'b': 'x', 'c': 'y+z'})
        self.assertEqual(s, {'x': 'x', 'y': 'y+z', 'z': 'y+z'})

    @staticmethod
    def synthetic(seed):
        """A random positive data base: 2 commodities = activities, 2 factors, 3 regions, 1 margin."""
        rng = np.random.default_rng(seed)
        c, f, r = 2, 2, 3
        u = lambda *sh: rng.uniform(1, 2, sh)
        D = {k: u(c, c, r) for k in ('VDFB', 'VMFB', 'MAKS')}
        D.update({k: u(c, r) for k in ('VDPB', 'VMPB', 'VDGB', 'VMGB', 'VDIB', 'VMIB')})
        for k in ('VDF', 'VMF', 'VDP', 'VMP', 'VDG', 'VMG', 'VDI', 'VMI'):
            D[k + 'P'] = D[k + 'B'] * 1.1
        D['MAKB'] = D['MAKS'] * 1.05
        D['EVFB'] = u(f, c, r); D['EVFP'] = D['EVFB'] * 1.2; D['EVOS'] = D['EVFB'] * 0.9
        D['VXSB'] = u(c, r, r); D['VFOB'] = D['VXSB'] * 1.0; D['VTWR'] = u(1, c, r, r) * 0.1
        D['VCIF'] = D['VFOB'] + D['VTWR'].sum(axis=0); D['VMSB'] = D['VCIF'] * 1.05
        D['VST'] = u(1, r); D['SAVE'] = u(r); D['VDEP'] = u(r) * 0.1; D['VKB'] = u(r) * 10
        return D

    def args(self):
        sets = dict(COMM=['x', 'y'], ACTS=['x', 'y'], ENDW=['capital', 'land'], REG=['A', 'B', 'C'])
        gchars = dict(COMM=['X', 'Y'], ACTS=['X', 'Y'], ENDW=['Capital', 'Land'], REG=['a', 'b', 'c'])
        conc = pd.DataFrame(dict(gtap_code=['X', 'Y'], sectors=['x', 'y'], relation=['1:1', '1:1']))
        regions = pd.DataFrame(dict(region=['A', 'B', 'C'], type='single'))
        return sets, gchars, conc, regions

    def test_measures_weights(self):
        m = G.measures(self.synthetic(0), ['x', 'y'], ['x', 'y'], ['capital', 'land'], ['A', 'B', 'C'])
        sh = m[m['measure'].isin(['va_share', 'export_share', 'household_budget', 'product_tax_rate'])]
        w = sh.groupby(['measure', 'region'])['weight'].sum()
        self.assertTrue(np.allclose(w, 1.0))
        self.assertTrue(np.allclose(m.loc[m['measure'] == 'product_tax_rate', 'value'], 0.1))

    def test_full_compare_flags(self):
        sets, gchars, conc, regions = self.args()
        ours, gt = self.synthetic(0), self.synthetic(0)
        t, s = G.full_compare(ours, sets, gt, gchars, conc, regions, large=['A'])
        self.assertTrue(np.allclose(t['gap_pts'], 0) and not t['flag'].any())
        ours['VDPP'] = ours['VDPP'].copy(); ours['VDPP'][0, 0] = ours['VDPB'][0, 0] * 1.6    # A, x: household tax 10% -> 60%
        t, s = G.full_compare(ours, sets, gt, gchars, conc, regions, large=['A'])
        f = t[t['flag'] & (t['measure'] == 'product_tax_rate_household')]
        self.assertEqual(f[['region', 'item']].values.tolist(), [['A', 'x']])
        self.assertNotIn('value_gtap10', s.columns)
        t, _ = G.full_compare(ours, sets, gt, gchars, conc, regions, large=['B'])     # not a large economy: no flag
        self.assertFalse(t.loc[t['measure'] == 'product_tax_rate_household', 'flag'].any())


class StageTagsTest(unittest.TestCase):
    def test_stage_concept_tags(self):
        """Every S.check in the stage file passes concept_tags (a literal kind and concept)."""
        import ast
        tree = ast.parse(open(os.path.join(BUILD, 's16_final_checks.py')).read())
        checks = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, 'attr', '') == 'check' and len(node.args) >= 7:
                cid, kind, concept = node.args[0], node.args[2], node.args[6]
                if all(isinstance(x, ast.Constant) for x in (cid, kind, concept)):
                    checks.append(dict(id=cid.value, kind=kind.value, concept=concept.value))
        self.assertGreater(len(checks), 30)
        self.assertEqual(K.concept_tags(checks), (0, ''))


if __name__ == '__main__':
    unittest.main()


class CollectedTextTest(unittest.TestCase):
    """S16-Hcollected names S10-Hwedge as a source comparison since fix-round B9 (S07 + S08 VCIF and the BACI
    accumulator), not as an identity; the S10 check it collects says the same."""
    def test_wedge_not_called_an_identity(self):
        src = open(os.path.join(BUILD, 's16_final_checks.py')).read()
        i = src.index("'S16-Hcollected'")
        text = src[i:src.index("'hard'", i)]
        ident = text[text.index('are identities'):] if 'are identities' in text else ''
        self.assertNotIn('S10-Hwedge', text[:text.index('are identities')].split('.')[-1])   # not in the identity list
        self.assertIn('S10-Hwedge is not', text)
        self.assertIn('BACI line accumulator', text)
        s10 = open(os.path.join(BUILD, 's10_tariffs_taxes.py')).read()
        self.assertIn('VCIF re-read from', s10[s10.index("'S10-Hwedge'"):][:400])
        self.assertTrue(ident)
