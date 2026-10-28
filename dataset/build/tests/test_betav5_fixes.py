"""Unit tests for the beta v5 S13-S16 fixes (package v2, David 2026-10-27 08:39 UTC): P (power fix on), F (fuel-share cap),
C (construction share of investment), V (VAT exemptions), N1 (listed own-use cap), RG (release gates), TC (report checks).

Every helper is called on a small hand-computed input (it must give the hand value) and, where it guards, on a bad input
(it must stop or flag). No stage is run.

Run from dataset/build:  python3 -m unittest tests.test_betav5_fixes -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BUILD)

from s13_fit import checks as K13  # noqa: E402
from s13_fit import config as C13  # noqa: E402
from s13_fit import method as M13  # noqa: E402
from s13_fit import ptax_source as PS  # noqa: E402
from s16_final import betav5 as B5  # noqa: E402
from s16_final import config as C16  # noqa: E402


class ChoiceFilesTest(unittest.TestCase):
    """The package's calls are in the choices files, each with an implemented value, and 'off' stays an alternative."""

    def test_s13(self):
        c = C13.load_choices()
        self.assertEqual(c['ely_hold_net_own_use']['value'], C13.CHOICES['ely_hold_net_own_use'][1])
        self.assertEqual(c['ely_hold_cap']['value'], 'off')                    # David 11:43 UTC: measured prices, no markup cap
        self.assertEqual(c['ely_output_anchor']['value'], C13.ELY_ANCHOR)
        self.assertEqual(c['investment_con_share']['value'], M13.INVESTMENT_CON_SHARE)
        self.assertEqual(c['fuel_share_cap']['value'], M13.FUEL_SHARE_CAP)
        self.assertEqual(c['own_use_cap_listed']['value'], 'off')          # David 2026-10-27 11:15 UTC (audit): N1 off
        self.assertEqual(c['vat_exemptions']['value'], C13.VAT_EXEMPTIONS)
        for k in ('investment_con_share', 'fuel_share_cap', 'own_use_cap_listed', 'vat_exemptions', 'ely_hold_cap'):
            self.assertIn('off', C13.CHOICES[k])

    def test_s16(self):
        c = C16.load_choices()
        self.assertEqual(c['release_gates']['value'], C16.RELEASE_GATES)
        self.assertEqual(c['betav5_report_checks']['value'], C16.BETAV5_REPORTS)


class InvestmentConGroupsTest(unittest.TestCase):
    def test_con_cells_are_group_1(self):
        idx = {'mfr': 0, 'con': 1, 'trd': 2}
        prior = np.array([5.0, 1.0, 3.0, 0.5, 1.0, 0.0])
        g = M13.investment_con_groups(3, idx, prior)
        np.testing.assert_array_equal(g, [0, 0, 1, 1, 0, 0])

    def test_none_without_con_or_prior(self):
        self.assertIsNone(M13.investment_con_groups(2, {'mfr': 0, 'trd': 1}, np.ones(4)))
        self.assertIsNone(M13.investment_con_groups(2, {'mfr': 0, 'con': 1}, np.array([1.0, 1.0, 0.0, 0.0])))

    def test_report_share(self):
        io12 = pd.DataFrame({'region': ['A'] * 3, 'row': ['dom_con', 'imp_con', 'dom_mfr'], 'i': [30.0, 0.0, 70.0]})
        io13 = io12.assign(i=[12.0, 0.0, 88.0])
        r = K13.investment_con_share(io13, io12).set_index('region')
        self.assertAlmostEqual(r.loc['A', 'prior'], 0.30)
        self.assertAlmostEqual(r.loc['A', 'fitted'], 0.12)


def _fuel_case(fit_pet, fit_out):
    sectors = ['pet', 'rdt', 'mfr']
    z = lambda: np.zeros((3, 3))  # noqa: E731
    b0 = {'dom': z(), 'imp': z()}
    b0['dom'][0, 1] = 20.0                   # road transport: pet 20 of output 100 (20%)
    b0['dom'][0, 2] = 1.0                    # manufacturing: pet 1 of output 100 (1%)
    info = {'basic0': b0, 'out0': np.array([50.0, 100.0, 100.0]), 'status': {}}
    R = {'dom': z(), 'imp': z(), 'out': np.array([50.0, fit_out, 100.0])}
    R['dom'][0, 1] = fit_pet
    R['dom'][0, 2] = 1.0
    return R, info, sectors


class FuelShareCapsTest(unittest.TestCase):
    def test_cap_is_max_of_2x_and_plus_5pt(self):
        R, info, sec = _fuel_case(30.0, 50.0)      # 60% of a shrunk column; cap max(40%, 25%) = 40% of 50 = 20
        caps, rows = M13.fuel_share_caps(R, info, sec, goods=('pet',))
        self.assertAlmostEqual(caps[('pet', 'rdt')], 20.0)
        self.assertNotIn(('pet', 'mfr'), caps)
        self.assertAlmostEqual(rows[0]['cap_share'], 0.40)
        self.assertAlmostEqual(rows[0]['fitted_share'], 0.60)

    def test_plus_5pt_binds_on_a_small_prior(self):
        R, info, sec = _fuel_case(20.0, 100.0)
        R['dom'][0, 2] = 10.0                      # mfr 10% from 1%: cap max(2%, 6%) = 6
        caps, _ = M13.fuel_share_caps(R, info, sec, goods=('pet',))
        self.assertAlmostEqual(caps[('pet', 'mfr')], 6.0)
        self.assertNotIn(('pet', 'rdt'), caps)

    def test_no_cap_within_band_energy_or_representative(self):
        R, info, sec = _fuel_case(39.0, 100.0)     # 39% < 40%
        self.assertEqual(M13.fuel_share_caps(R, info, sec, goods=('pet',))[0], {})
        R, info, sec = _fuel_case(30.0, 50.0)
        info['status'] = {'rdt': 'representative'}
        self.assertEqual(M13.fuel_share_caps(R, info, sec, goods=('pet',))[0], {})

    def test_earlier_cap_kept_when_smaller(self):
        R, info, sec = _fuel_case(30.0, 50.0)
        caps, _ = M13.fuel_share_caps(R, info, sec, caps={('pet', 'rdt'): 15.0}, goods=('pet',))
        self.assertAlmostEqual(caps[('pet', 'rdt')], 15.0)

    def test_hold_energy_users_moves_the_cut_to_uncapped_users(self):
        sectors = ['gas', 'msp', 'mfr']
        idx = {c: i for i, c in enumerate(sectors)}
        cols = sectors + list(M13.FD)
        pv = {k: np.zeros((3, len(cols))) for k in ('dom', 'imp')}
        tau = np.ones((3, len(cols)))
        pv['dom'][0, [2, cols.index('p')]] = [3.0, 1.0]
        held = {}
        rows = M13.hold_energy_users(pv, tau, idx, {}, np.array([100.0, np.nan, np.nan]), np.zeros(3), np.zeros(3), held, cols,
                                     share_caps={('gas', 'mfr'): 50.0})
        self.assertAlmostEqual(held[('dom', 0, 2)], 50.0)
        self.assertAlmostEqual(held[('dom', 0, cols.index('p'))], 50.0)          # households take the 25 cut
        self.assertAlmostEqual(sum(v for (k, i, j), v in held.items() if i == 0), 100.0)
        self.assertAlmostEqual(rows[0]['share_capped_musd'], 25.0)

    def test_report_flags_over_cap(self):
        io12 = pd.DataFrame({'region': ['A'] * 3, 'row': ['dom_pet', 'imp_pet', 'OUT'], 'rdt': [20.0, 0.0, 100.0]})
        io13 = io12.assign(rdt=[30.0, 0.0, 50.0])
        self.assertEqual(K13.fuel_share_over(io13, io12, ['rdt'], ('pet',), 2.0, 0.05, 1.0), ['A rdt pet 0.200->0.600'])
        self.assertEqual(K13.fuel_share_over(io12, io12, ['rdt'], ('pet',), 2.0, 0.05, 1.0), [])


class OwnUseListedTest(unittest.TestCase):
    HEAD = 'region,commodity,own_use_share,source,decided_by,decided_at,basis\n'

    def _read(self, body):
        with tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False) as f:
            f.write(self.HEAD + body)
        try:
            return C13.read_own_use_listed(f.name)
        finally:
            os.unlink(f.name)

    def test_committed_file(self):
        self.assertEqual(C13.read_own_use_listed(), {'NGA': {'fbt': 0.138}})

    def test_bad_rows_stop(self):
        self.assertEqual(self._read('NGA,fbt,0.138,s,D,2026-10-27,b\n'), {'NGA': {'fbt': 0.138}})
        for bad in ('NGA,fbt,0.138,,D,2026-10-27,b\n', 'NGA,pet,0.1,s,D,2026-10-27,b\n', 'NGA,fbt,1.2,s,D,2026-10-27,b\n',
                    'NGA,fbt,0.1,s,D,d,b\nNGA,fbt,0.2,s,D,d,b\n'):
            with self.assertRaises(C13.ConfigError):
                self._read(bad)

    def test_non_energy_diagonal_nets_out(self):
        from s13_fit import energy as EN
        sectors = ['fbt', 'mfr']
        idx = {c: i for i, c in enumerate(sectors)}
        cols = sectors + list(M13.FD)
        pv = {k: np.zeros((2, len(cols))) for k in ('dom', 'imp')}
        pv['dom'][0, 0] = 30.0                     # fbt diagonal 30 of a column of 100 (30%)
        pv['dom'][1, 0] = 50.0
        pv['dom'][0, cols.index('p')] = 40.0
        va = np.array([20.0, 10.0])
        live = np.ones(len(cols), bool)
        EN.cap_own_use(pv, np.ones((2, len(cols))), idx, cols, np.array([np.nan, np.nan]), va, {'fbt': 0.138}, live,
                       net_out=EN.OWN_USE_NET_OUT + ('fbt',))
        d = pv['dom'][0, 0]
        col = pv['dom'][:, 0].sum() + va[0]
        self.assertAlmostEqual(d / col, 0.138, places=6)
        self.assertAlmostEqual(pv['dom'][0, cols.index('p')], 40.0)              # netted: households keep their cell


class VatExemptTest(unittest.TestCase):
    def _case(self):
        sectors = ['mfr', 'fin', 'fbt', 'pet']
        cols = sectors + ['p', 'g', 'i']
        b = np.zeros((4, 7))
        b[0, 4], b[1, 4], b[2, 4], b[3, 4] = 60.0, 30.0, 10.0, 5.0       # households
        b[0, 5], b[1, 5] = 10.0, 10.0                                     # government
        b[0, 1] = 20.0                                                    # finance buys mfr
        z = np.zeros((4, 7))
        return sectors, cols, b, z

    def test_exempt_rows_untaxed_total_kept(self):
        sectors, cols, b, z = self._case()
        cr, g, tls, info = PS.vat_final_demand(z.copy(), z.copy(), b, np.zeros(7), sectors, cols, 16.0, 0.0, exempt=('fin',))
        self.assertAlmostEqual(info['vat_rate'], 16.0 / 85.0)               # base: mfr 70, fbt 10, pet 5
        self.assertEqual(g[1, 4], 0.0)
        self.assertAlmostEqual(float((g * b).sum()), 16.0)
        self.assertAlmostEqual(info['exempt_base_musd'], 40.0)
        self.assertEqual(info['exempt_input_vat_musd'], 0.0)

    def test_rate_capped_at_statutory_rest_on_exempt_inputs(self):
        sectors, cols, b, z = self._case()
        cr, g, tls, info = PS.vat_final_demand(z.copy(), z.copy(), b, np.zeros(7), sectors, cols, 20.0, 0.0, exempt=('fin',), rate_max=0.2)
        self.assertAlmostEqual(info['vat_rate'], 0.2)
        self.assertAlmostEqual(info['exempt_input_vat_musd'], 3.0)          # 20 - 0.2 x 85
        self.assertAlmostEqual(g[0, 1], 3.0 / 20.0)                         # finance's non-deductible input VAT
        self.assertAlmostEqual(float((g * b).sum()), 20.0)
        self.assertAlmostEqual(float(tls.sum()), 20.0)

    def test_no_exempt_is_v4(self):
        sectors, cols, b, z = self._case()
        _, g, _, info = PS.vat_final_demand(z.copy(), z.copy(), b, np.zeros(7), sectors, cols, 23.0, 0.0, rate_max=0.2)
        self.assertAlmostEqual(info['vat_rate'], 23.0 / 125.0)
        self.assertEqual(info['exempt_input_vat_musd'], 0.0)

    def test_read_committed_and_bad(self):
        vreg = PS.read_vat_regions(os.path.join(BUILD, 'config/s13/vat_final_demand_2022.csv'))
        v = PS.read_vat_exempt(os.path.join(BUILD, 'config/s13/vat_exempt_rows.csv'), vreg)
        self.assertEqual(sorted(v), ['ALB', 'SRB'])
        self.assertNotIn('pub', v['SRB'])
        with tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False) as f:
            f.write(','.join(PS.VAT_EXEMPT_COLUMNS) + '\nSRB,fin pub,s,D,2026-10-27,b\n')
        try:
            with self.assertRaises(SystemExit):
                PS.read_vat_exempt(f.name, vreg)
        finally:
            os.unlink(f.name)


def _har(comm=('ely', 'mfr'), regs=('gha', 'usa')):
    nc, nr = len(comm), len(regs)
    a = ('crp', 'ely')
    na = len(a)
    D = {k: np.zeros((nc, na, nr)) for k in ('VDFB', 'VMFB', 'VDFP', 'VMFP')}
    for k in ('VDPB', 'VMPB', 'VDGB', 'VMGB', 'VDIB', 'VMIB', 'VDPP', 'VMPP', 'VDGP', 'VMGP', 'VDIP', 'VMIP'):
        D[k] = np.zeros((nc, nr))
    D['MAKB'] = np.zeros((nc, na, nr))
    D['VFOB'] = np.zeros((nc, nr, nr))
    D['VXSB'] = np.zeros((nc, nr, nr))
    D['VCIF'] = np.zeros((nc, nr, nr))
    D['EVFB'] = np.zeros((2, na, nr))
    return D, list(comm), list(regs)


class ReportChecksTest(unittest.TestCase):
    def test_energy_wedge(self):
        D, comm, regs = _har()
        D['VDFB'][0, 0, :] = [100.0, 100.0]
        D['VDFP'][0, 0, :] = [16.0, 110.0]          # GHA buyers pay 16% of the basic value
        D['MAKB'][0, 1, :] = [100.0, 100.0]
        w = B5.energy_wedge(D, comm, regs, goods=('ely',)).set_index('region')
        self.assertTrue(w.loc['gha', 'flag'])
        self.assertAlmostEqual(w.loc['gha', 'subsidy_share_output'], 0.84)
        self.assertFalse(w.loc['usa', 'flag'])

    def test_metal_exports_and_routes(self):
        D, comm, regs = _har(comm=('ore', 'oil'))
        D['MAKB'][0, 0, 0] = 2000.0
        D['VXSB'][0, 0, 1] = 1900.0
        D['VCIF'][0, 1, 0] = 1500.0
        m = B5.metal_exports(D, comm, regs)
        self.assertEqual(len(m), 1)
        D['VFOB'][1, 0, 1] = 800.0
        f = B5.filled_routes(D, comm, regs, {('GHA', 'USA')})
        self.assertEqual(f[['good', 'vfob_musd']].values.tolist(), [['oil', 800.0]])
        blocks = pd.DataFrame([dict(good='oil', src='GHA', dst='USA')])
        self.assertEqual(len(B5.blocked_routes(D, comm, regs, blocks)), 1)
        D['VFOB'][1, 0, 1] = 0.0
        self.assertEqual(len(B5.blocked_routes(D, comm, regs, blocks)), 0)

    def test_version_diff(self):
        D, comm, regs = _har()
        D['MAKB'][1, 0, :] = [1000.0, 5000.0]
        P = {k: v.copy() for k, v in D.items()}
        P['MAKB'][1, 0, 0] = 2500.0
        s, rows = B5.version_diff(D, P, comm, regs, regs, comm)
        self.assertEqual(rows[['region', 'item']].values.tolist(), [['gha', 'output mfr']])
        self.assertIsNone(B5.version_diff(D, P, comm, regs, regs[::-1], comm)[0])


class ReleaseGateTest(unittest.TestCase):
    GOOD = [dict(id=k, kind='hard', status='PASS', value=0) for k in ('S16-Hrelease', 'S16-Grepro', 'S16-Hscreenreview', 'S16-Hwaivers', 'S16-Hmaps')]

    def test_gate(self):
        self.assertEqual(B5.release_gate(self.GOOD), [])
        bad = [dict(c, kind='report', status='NOTE') if c['id'] == 'S16-Grepro' else c for c in self.GOOD]
        self.assertEqual(len(B5.release_gate(bad)), 1)
        self.assertEqual(len(B5.release_gate(self.GOOD[1:])), 1)
        self.assertEqual(len(B5.release_gate(self.GOOD + [dict(id='S16-Hx', kind='hard', status='FAIL')])), 1)

    def test_non_release_run_is_not_hard(self):
        # review of PR #105: a development S16 (gates on, GTAP_RELEASE unset) must stamp; only a release run is hard
        self.assertEqual(B5.release_kind(True, False), 'report')
        self.assertEqual(B5.release_kind(False, True), 'report')
        self.assertEqual(B5.release_kind(True, True), 'hard')
        src = open(os.path.join(BUILD, 's16_final_checks.py')).read()
        self.assertEqual(src.count('B5.release_kind(rg, rel)'), 2)
        old = os.environ.pop('GTAP_RELEASE', None)
        try:
            self.assertFalse(B5.release_mode())
            note = [dict(c, kind=B5.release_kind(True, B5.release_mode()), status='NOTE') if c['id'] == 'S16-Hrelease' else c for c in self.GOOD]
            self.assertEqual(len(B5.release_gate(note)), 1)          # the gate still refuses it
        finally:
            if old is not None:
                os.environ['GTAP_RELEASE'] = old

    def test_stale_screen_and_waivers(self):
        rows = pd.DataFrame([dict(stage='S07', importer='USA', item='x', screen='s1', date='2026-10-23'),
                             dict(stage='S07', importer='USA', item='y', screen='s1', date='2026-10-27')])
        self.assertEqual(len(B5.stale_screen_rows(rows, C16.SCREEN_CUTOFF)), 1)
        me = pd.DataFrame([dict(map='alone_ken'), dict(map='alone_x')])
        mr = pd.DataFrame([dict(map='alone_ken', status='FAIL', error=''), dict(map='alone_x', status='PASS', error='')])
        ge = pd.DataFrame([dict(map='alone_afg', group='sigma_qinv')])
        self.assertEqual(B5.stale_waivers(me, mr, ge, pd.DataFrame([dict(map='alone_afg', group='sigma_qinv')])), ['map_failure_exceptions alone_x: passes'])
        self.assertEqual(len(B5.stale_waivers(me.iloc[:1], mr, ge, pd.DataFrame(columns=['map', 'group']))), 1)

    def test_tool_refuses_without_release_run(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, 'S16_final_checks'))
            p = os.path.join(d, 'S16_final_checks', 'checks.json')
            tool = os.path.join(BUILD, 'tools', 'release_gate.py')
            json.dump(self.GOOD[1:], open(p, 'w'))
            self.assertEqual(subprocess.run([sys.executable, tool, d], capture_output=True).returncode, 1)
            json.dump(self.GOOD, open(p, 'w'))
            open(os.path.join(d, 'S16_final_checks', 'STAMP'), 'w').close()
            self.assertEqual(subprocess.run([sys.executable, tool, d], capture_output=True).returncode, 0)


class ShieldOverlapTest(unittest.TestCase):
    def test_shield_is_not_an_unnetted_iea_subsidy(self):
        row = dict(region='FRA', commodity='ely', s11_subsidy_musd=0.0, neer_subsidy_musd=0.0, to_book_musd=915.2, shield_musd=915.2)
        self.assertEqual(K13.neer_overlap([row], {}, True)[0], 0)
        self.assertEqual(K13.neer_overlap([dict(row, shield_musd=0.0)], {}, True)[0], 1)
        both = dict(row, s11_subsidy_musd=100.0, neer_subsidy_musd=-30.0, to_book_musd=70.0 + 915.2)
        self.assertEqual(K13.neer_overlap([both], {}, True)[0], 0)

    def test_shield_file(self):
        s = C13.read_ely_shield()
        self.assertAlmostEqual(s['FRA'], 869.1 / 0.9496)
        self.assertAlmostEqual(s['GBR'], (4174.2 + 1276.084) / 0.8113)
        self.assertAlmostEqual(C13.read_ely_anchor()['CHE'][2], 149.41)
        self.assertAlmostEqual(s['OMN'], 339.9 / 0.3845)
        for r in ('ETH', 'AGO', 'GNQ', 'AFG'):
            self.assertNotIn(r, C13.read_ely_anchor())       # subsidised tariff with no subsidy source / IEA subsidy region / no 2022 source


class MapsTest(unittest.TestCase):
    def test_new_maps_listed(self):
        m = pd.read_csv(os.path.join(BUILD, 'config/s16/maps.csv'))
        for k in ('alone_gha_24', 'alone_kaz_24', 'alone_tkm', 'alone_afg', 'alone_hkg'):
            self.assertIn(k, set(m['map']))
        s = pd.read_csv(os.path.join(BUILD, 'config/s16/sector_schemes.csv'))
        self.assertEqual(s['s24'].nunique(), 24)


if __name__ == '__main__':
    unittest.main()
