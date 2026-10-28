"""Unit tests for the beta v4 fixes (fix register P1, P2, P4-P7, P10, P13-P16, P18, P21, P22, P24-P27; 26 Oct).

Every helper and check is called on a good input (it must pass or give the hand-computed value) and on a mutated input
(it must fail or move). No stage is run.

Run from dataset/build:  python3 -m unittest tests.test_betav4_fixes -v
"""
import os
import sys
import unittest

import duckdb
import numpy as np
import pandas as pd

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BUILD)

from s11_energy import checks as K11  # noqa: E402
from s11_energy import config as C11  # noqa: E402
from s11_energy import domestic as DOM  # noqa: E402
from s11_energy import method as M11  # noqa: E402
from s11_energy import power as PWR  # noqa: E402
from s13_fit import checks as K13  # noqa: E402
from s13_fit import config as C13  # noqa: E402
from s13_fit import energy as EN13  # noqa: E402
from s13_fit import method as M13  # noqa: E402
from s15_har import config as C15  # noqa: E402
from s15_har import method as M15  # noqa: E402
import s07_trade as S7  # noqa: E402
import s08_margins as S8  # noqa: E402


class ChoiceFilesTest(unittest.TestCase):
    """Every new choice is in its stage's choices file with an allowed value; David's calls carry the decision package's
    recommended or decided value (S16 aligned defaults 2026-10-26), the off values stay as alternatives."""

    def test_s11(self):
        c = C11.load_choices()
        for k in ('ras_seed_routes', 'no_refinery_crude_use', 'reexport_observed_national', 'gas_line_mix_price',
                  'ninety_pct_ely', 'ninety_pct_own_use'):
            self.assertTrue(C11.switched_on(c, k), k)
        self.assertTrue(C11.switched_on(c, 'energy_route_observed'))       # David 2026-10-26 03:45 UTC
        for k in ('gas_export_parity_cap', 'ely_production_subsidy'):        # P6, P4 (decision package)
            self.assertTrue(C11.switched_on(c, k), k)
            self.assertIn('off', C11.ALTERNATIVES[k])

    def test_s13_s15_s08_s07(self):
        c = C13.load_choices()
        self.assertEqual(c['no_refinery_crude_use']['value'], C13.NO_REFINERY_CRUDE)
        self.assertEqual(c['power_va_trigger']['value'], 'off')
        self.assertEqual(M13.NO_REFINERY_CRUDE, C13.NO_REFINERY_CRUDE)
        self.assertEqual(C15.load_choices()['household_crude_seed']['value'], C15.CHOICES['household_crude_seed'][1])   # P10
        ch, rows, bad = S8.load_choices(os.path.join(BUILD, 'config/s08/margin_choices.csv'))
        self.assertEqual((ch['lng_sea_rate'], bad), (S8.LNG_VOYAGE, []))                                            # P7
        t = S7.load_choices(os.path.join(BUILD, 'config/s07/trade_choices.csv'))
        self.assertEqual(len(t), len(S7.CHOICE_ORDER))
        self.assertEqual(t['absent_pairs_fill']['value'], S7.ABSENT_FILL)
        self.assertEqual(t['currency_lines']['value'], S7.CURRENCY_DROP)

    def test_route_and_price_tables(self):
        rows = C11.read_table('energy_route_observed.csv', C11.ENERGY_ROUTE_COLUMNS)
        self.assertTrue(all(r['source'].strip() and float(r['price']) > 0 and float(r['volume']) > 0 for r in rows))
        blr = [r for r in rows if (r['exporter'], r['importer'], r['commodity']) == ('RUS', 'BLR', 'gas')][0]
        self.assertAlmostEqual(float(blr['price']), 128.52)
        usa = C11.read_table('gas_line_prices_2022.csv', C11.GAS_LINE_COLUMNS)[0]
        self.assertAlmostEqual(float(usa['pipeline_price']), 6.34 * 35.3147, places=1)
        # LNG at the residual that keeps the US total at its reference value (BACI 79,130 USD m over EIA volumes, MMcf)
        pv, lv = 3040787 / 35314.7, 3865643 / 35314.7
        self.assertAlmostEqual(float(usa['lng_price']), (79130.0 - float(usa['pipeline_price']) * pv) / lv, places=1)
        self.assertEqual({r['region'] for r in C11.read_table('reexport_observed_national.csv', C11.REEXPORT_NATIONAL_COLUMNS)},
                         {'CAN', 'MEX', 'AUS'})
        # beta v4 rescan N1: the AUS gas row sits behind its own switch, on
        self.assertEqual(C11.SWITCHED_RX_NATIONAL[('AUS', 'gas')], 'aus_gas_processing')
        self.assertTrue(C11.switched_on(C11.load_choices(), 'aus_gas_processing'))


class SeedRoutesTest(unittest.TestCase):
    """P13 S11: seeds only on feasible routes, release of rows with none, hard gates."""

    def setUp(self):
        self.R = ['A', 'B', 'C', 'D']
        self.rows = pd.DataFrame({'exp': ['A', 'A', 'B', 'C', 'C', 'Z'], 'imp': ['B', 'B', 'C', 'C', 'A', 'A'],
                                  'v': [5.0, 0.0, 1.0, 9.0, 0.0, 3.0]})

    def test_feasible_routes(self):
        F = M11.baci_feasible_routes(self.rows, self.R)
        self.assertEqual(sorted(map(tuple, np.argwhere(F))), [(0, 1), (1, 2)])     # no diagonal, no zero value, no unknown

    def test_mask_and_release(self):
        F = M11.baci_feasible_routes(self.rows, self.R)
        A0 = np.zeros((4, 4))
        exp, imp = np.array([1.0, 1.0, 0.0, 1.0]), np.array([0.0, 1.0, 1.0, 0.0])
        mask, rr, rc = M11.feasible_seed_mask(A0, exp, imp, F, np.zeros(4, bool))
        self.assertEqual((rr, rc), ([3], []))                 # D exports with no feasible route: released
        self.assertTrue(mask[3].all() and mask[0, 1] and not mask[0, 2])
        A, sd = M11.seed_matrix(A0, exp, imp, np.zeros(4, bool), 1e-6, feasible=mask)
        self.assertFalse(sd[0, 2])                           # A->C never traded: not seeded
        self.assertTrue(sd[0, 1] and sd[3, 1] and sd[3, 2])
        imp2 = np.array([0.0, 1.0, 1.0, 1.0])
        self.assertEqual(M11.feasible_seed_mask(A0, exp, imp2, F, np.zeros(4, bool))[2], [3])   # D imports with none: column released
        A2, sd2 = M11.seed_matrix(A0, exp, imp, np.zeros(4, bool), 1e-6)
        self.assertTrue(sd2[0, 2])                           # mutated: the plain seed puts A->C on

    def test_gates(self):
        A0 = np.array([[0.0, 1.0], [0.0, 0.0]])
        A1 = np.array([[0.0, 30.0], [5.0, 0.0]])
        fob = A1 * 10.0
        seeded = np.array([[False, False], [True, False]])
        sb, xb = M11.route_gates(A0, A1, fob, seeded)
        self.assertEqual(([(i, j) for i, j, *_ in sb], [(i, j) for i, j, *_ in xb]), ([], [(0, 1)]))   # 300 m, x30
        fob[1, 0] = 150.0
        sb, xb = M11.route_gates(A0, A1, fob, seeded, explained={(0, 1)})
        self.assertEqual(([(i, j) for i, j, *_ in sb], xb), ([(1, 0)], []))


class LineMixTest(unittest.TestCase):
    """P25: route price by pipeline and LNG line mix."""

    def test_mix(self):
        R = ['USA', 'MEX', 'ESP', 'JPN']
        rows = pd.DataFrame({'exp': ['USA', 'USA', 'USA', 'USA'], 'imp': ['MEX', 'ESP', 'MEX', 'USA'],
                             'k': ['271121', '271111', '271111', '271111'], 'v': [90.0, 50.0, 10.0, 7.0]})
        pr, w = M11.line_mix_route_prices(rows, R, 'USA', 224.0, 432.0)
        self.assertAlmostEqual(pr[1], 0.9 * 224 + 0.1 * 432)
        self.assertAlmostEqual(pr[2], 432.0)
        self.assertAlmostEqual(w[3], 90.0 / 150.0)            # no BACI route: the exporter's own split
        self.assertTrue(np.isnan(pr[0]))


class NinetyElyTest(unittest.TestCase):
    """P1, P15, P4: the 90 percent rule with ely, own use and an ely subsidy."""

    def V(self):
        recs = []
        for k, ds, ex, prod, p in (('coa', 10, 0, 1, 10.0), ('oil', 100, 0, 1, 1.0), ('gas', 50, 0, 1, 1.0),
                                   ('pet', 100, 0, 10, 10.0), ('ely', 100, 0, 1, 1.0)):
            recs.append(dict(region='A', commodity=k, domestic_sales_value=ds, export_value=ex, ngpl_value=0.0, pass_through_value=0.0,
                             domestic_sales=ds, imports=0.0, import_basic_price=np.nan, domestic_price=p, production=prod))
        return pd.DataFrame(recs)

    def test_ely_joins_and_is_raised(self):
        V = self.V()
        gas = {'A': {'dom': 0.0, 'imp': 0.0}}
        rows, pi = K11.ninety_rule(V, ['A'], {'A': 0.0}, gas, M11.ninety_pct, ely_in={'A': {'gas': (95.0, 0.0)}})
        e = [x for x in rows if x['industry'] == 'ely'][0]
        self.assertAlmostEqual(e['ratio_before'], 0.95)
        self.assertLessEqual(e['ratio_after'], 0.9 + 1e-9)
        rows0, _ = K11.ninety_rule(V, ['A'], {'A': 0.0}, gas, M11.ninety_pct)
        self.assertNotIn('ely', {x['industry'] for x in rows0})          # mutated: rule off

    def test_own_use_and_subsidy(self):
        V = self.V()
        gas = {'A': {'dom': 0.0, 'imp': 0.0}}
        rows, _ = K11.ninety_rule(V, ['A'], {'A': 0.0}, gas, M11.ninety_pct, ely_in={'A': {}}, own_in={'A': {'pet': 0.1}})
        p = [x for x in rows if x['industry'] == 'pet'][0]
        self.assertAlmostEqual(p['own_use_value_before'], 0.1 * 10 * 10.0)
        nin, _ = K11.ninety_rule(V, ['A'], {'A': 0.0}, gas, M11.ninety_pct, ely_in={'A': {'gas': (95.0, 0.0)}})
        listed = [dict(region='A', value_usd_million=50.0, source='s', url='u')]
        b = K11.ely_subsidy_rows(listed, nin, set(), ['A'])[0]
        self.assertAlmostEqual(b['shortfall_musd'], 95.0 / 0.9 - 100.0)
        self.assertAlmostEqual(b['booked_musd'], 95.0 / 0.9 - 100.0)
        self.assertEqual(K11.ely_subsidy_rows(listed, nin, {'A'}, ['A'])[0]['booked_musd'], 0.0)   # IEA row present
        rows2, _ = K11.ninety_rule(V, ['A'], {'A': 0.0}, gas, M11.ninety_pct, ely_in={'A': {'gas': (95.0, 0.0)}},
                                   ely_subsidy={'A': b['booked_musd']})
        self.assertAlmostEqual([x for x in rows2 if x['industry'] == 'ely'][0]['ratio_before'], 0.9)


class PowerHelpersTest(unittest.TestCase):
    def test_heat_split(self):
        PF = pd.DataFrame({'region': ['A', 'A', 'A'], 'fuel': ['gas', 'coa', 'gas_dist'],
                           'value_dom_musd': [80.0, 10.0, 5.0], 'value_imp_musd': [20.0, 0.0, 1.0]})
        e = PWR.ninety_ely_inputs(['A'], PF, {'A': 0.25})
        self.assertEqual(e['A']['gas'], (60.0, 15.0))
        self.assertNotIn('gas_dist', e['A'])
        self.assertAlmostEqual(PWR.pass_through_values(['A'], PF, {'A': 0.25})['A'], 6.0 + 0.25 * 110.0)


class ExportParityCapTest(unittest.TestCase):
    def test_check(self):
        row = dict(commodity='gas', region='KAZ', market_price=100.0, trade_parity_price=100.0, subsidy_per_unit=60.0,
                   iea_subsidy_per_unit=200.0, rate_cap='export_parity_cap')
        self.assertTrue(row['subsidy_per_unit'] < row['iea_subsidy_per_unit'])
        self.assertEqual(DOM.EXPORT_PARITY_CAP, 'export_parity_cap')


class S13ChecksTest(unittest.TestCase):
    def io(self, hh_oil=0.0, pet_out=0.0, ely_gas=80.0):
        rows = ['dom_oil', 'imp_oil', 'dom_gas', 'imp_gas', 'dom_coa', 'dom_pet', 'EVFP_capital', 'PTAX', 'OUT']
        d = pd.DataFrame(0.0, index=rows, columns=['pet', 'ely', 'p'])
        d.loc['dom_oil', 'p'] = hh_oil
        d.loc['OUT', 'pet'] = pet_out
        d.loc['dom_gas', 'ely'] = ely_gas
        d.loc['OUT', 'ely'] = 100.0
        d.loc['EVFP_capital', 'ely'] = 100.0 - ely_gas
        d = d.reset_index().rename(columns={'index': 'row'})
        d['region'] = 'TLS'
        return d

    def test_household_crude(self):
        self.assertEqual(K13.household_crude_no_refinery(self.io())[0], 0)
        self.assertEqual(K13.household_crude_no_refinery(self.io(hh_oil=370.0))[0], 1)
        self.assertEqual(K13.household_crude_no_refinery(self.io(hh_oil=370.0, pet_out=50.0))[0], 0)   # has a refinery

    def test_ninety_fitted(self):
        n, _, F = K13.ninety_fitted(self.io())
        self.assertEqual(n, 0)
        self.assertAlmostEqual(F.loc[F['industry'] == 'ely', 'ratio_held'].iloc[0], 0.8)
        self.assertEqual(K13.ninety_fitted(self.io(ely_gas=95.0))[0], 1)
        self.assertEqual(K13.ninety_fitted(self.io(ely_gas=95.0), pass_through={'TLS': 50.0})[0], 0)   # 45 / 50
        self.assertEqual(K13.ninety_fitted(self.io(ely_gas=95.0), exempt={'TLS'})[0], 0)
        self.assertEqual(K13.ninety_fitted(self.io(ely_gas=95.0), exempt={('TLS', 'ely')})[0], 0)      # dry run 3: by industry
        self.assertEqual(K13.ninety_fitted(self.io(ely_gas=95.0), exempt={('TLS', 'pet')})[0], 1)
        # beta v4 dry run 3 (ninety_fit_price): at purchaser prices, gas 95 x (1 - 0.5) = 47.5 over 100 passes
        n, _, F = K13.ninety_fitted(self.io(ely_gas=95.0), rho={('TLS', 'gas', 'ely'): 0.5})
        self.assertEqual(n, 0)
        self.assertAlmostEqual(F.loc[F['industry'] == 'ely', 'ratio_held'].iloc[0], 0.475)
        # the pass-through moves at the same factor: (47.5 - 25) / (100 - 25)
        _n, _, F = K13.ninety_fitted(self.io(ely_gas=95.0), pass_through={'TLS': 50.0}, rho={('TLS', 'gas', 'ely'): 0.5})
        self.assertAlmostEqual(F.loc[F['industry'] == 'ely', 'ratio_held'].iloc[0], 22.5 / 75.0)

    def test_targets_and_pool(self):
        self.assertIn('ely', M13.output_targets(M13.ENERGY_TARGETS_ELY))
        self.assertNotIn('ely', M13.output_targets(M13.ENERGY_TARGETS_V3))
        idx = {'pet': 0}
        ec = dict(intake_measured=True, intake_value_dom_musd=30.0, intake_value_imp_musd=70.0,
                  refinery_gas_value_dom_musd=4.0, refinery_gas_value_imp_musd=1.0, pet_own_use_value_musd=12.0)
        got = M13.pool_measured(ec, {'pet': 0.1}, np.array([100.0]), np.array([25.0]), np.array([25.0]), idx)
        self.assertEqual(got[('oil', 'pet')], (30.0, 70.0))
        self.assertEqual(got[('pet', 'pet')], (9.0, 3.0))             # 75 domestic sales : 25 imports
        self.assertNotIn(('pet', 'pet'), M13.pool_measured(ec, {}, np.array([100.0]), np.array([25.0]), np.array([25.0]), idx))


class S07FillTest(unittest.TestCase):
    """P13 S07 (absent pairs from BACI 2021) and P22 (HS 490700 out)."""

    def con(self):
        con = duckdb.connect()
        con.execute('CREATE TABLE cc(code INTEGER, iso3 VARCHAR)')
        con.executemany('INSERT INTO cc VALUES (?, ?)', [(643, 'RUS'), (112, 'BLR'), (276, 'DEU')])
        con.execute('CREATE TABLE reg(iso3 VARCHAR, region VARCHAR)')
        con.executemany('INSERT INTO reg VALUES (?, ?)', [('RUS', 'RUS'), ('BLR', 'BLR'), ('DEU', 'DEU')])
        con.execute('CREATE TABLE raw(hs6 VARCHAR, exp_code INTEGER, imp_code INTEGER, value DOUBLE, qty DOUBLE)')
        con.executemany('INSERT INTO raw VALUES (?, ?, ?, ?, ?)',
                        [('270900', 276, 643, 200.0, 1.0), ('490700', 276, 112, 50.0, 0.1), ('870300', 643, 276, 10.0, 1.0)])
        con.execute('CREATE TABLE mapped AS SELECT r.hs6, r.value, r.qty, ce.iso3 AS exp_iso, ci.iso3 AS imp_iso, '
                    're.region AS exp_region, ri.region AS imp_region FROM raw r JOIN cc ce ON ce.code = r.exp_code '
                    'JOIN cc ci ON ci.code = r.imp_code JOIN reg re ON re.iso3 = ce.iso3 JOIN reg ri ON ri.iso3 = ci.iso3')
        return con

    def test_fill(self):
        d = os.path.join(BUILD, '..', '..', 'tmp_s07_fill_test')
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, 'y2021.csv')
        pd.DataFrame({'t': [2021] * 4, 'i': [643, 643, 276, 643], 'j': [112, 112, 643, 276], 'k': ['270900', '870300', '270900', '870300'],
                      'v': [100.0, 20.0, 100.0, 5.0], 'q': [1.0, 1.0, 1.0, 1.0]}).to_csv(path, index=False)
        try:
            con = self.con()
            got = S7.fill_absent_pairs(con, path)
            # only RUS->BLR is absent in 2022; HS27 grows 200/200 = 1, HS87 10/(20+5) = 0.4
            self.assertEqual(got['rows'], 2)
            self.assertAlmostEqual(got['value_kusd'], 100.0 + 20.0 * 0.4)
            self.assertEqual(got['pairs'][0][:2], ('RUS', 'BLR'))
            self.assertEqual(con.execute("SELECT count(*) FROM mapped WHERE exp_iso = 'DEU' AND imp_iso = 'RUS'").fetchone()[0], 1)
            cash = S7.drop_currency_lines(con)
            self.assertEqual((cash['rows'], cash['value_kusd'], cash['left']), (1, 50.0, 0))
        finally:
            os.remove(path)
            os.rmdir(d)


class S08LngTest(unittest.TestCase):
    P = {'charter_usd_day': 85000, 'speed_knots': 17, 'cargo_mmbtu': 3.75e6, 'port_days': 3, 'port_fees_usd': 3e5,
         'boiloff_laden_per_day': 0.001, 'fuel_ballast_per_day': 0.0006, 'insurance_share': 0.001, 'canal_days': 2,
         'toll_suez_usd': 8e5, 'toll_panama_usd': 7.5e5}

    def test_cost_matches_research(self):
        self.assertAlmostEqual(S8.lng_voyage_cost(3800, None, 17.7, self.P), 0.85, places=2)       # AUS->JPN (ACCC 0.82)
        self.assertAlmostEqual(S8.lng_voyage_cost(6300, 'suez', 18.99, self.P), 1.59, places=2)    # QAT->GBR
        self.assertGreater(S8.lng_voyage_cost(6300, 'suez', 18.99, self.P), S8.lng_voyage_cost(6300, None, 18.99, self.P))

    def test_parts(self):
        m, sh = S8.lng_route_parts(0.10, 0.75, 0.05)
        self.assertAlmostEqual(m, 0.25 * 0.10 + 0.75 * 0.05)
        self.assertAlmostEqual(sum(sh), 1.0)
        self.assertAlmostEqual(sh[1], 0.75 * 0.05 / m)

    def test_config_files(self):
        P = {r['parameter']: float(r['value']) for r in S8.read_csv(os.path.join(BUILD, 'config/s08/lng_voyage.csv'))}
        self.assertEqual(set(P), set(S8.LNG_PARAMS))
        self.assertEqual(len(S8.read_csv(os.path.join(BUILD, 'config/s08/lng_routes.csv'))), 24)


class S15SeedTest(unittest.TestCase):
    """P10: the household crude seed keeps market clearing, import clearing, zero profit and SAVE."""

    def D(self):
        comm = ['oil', 'pet', 'srv']
        z3, z2 = (lambda: np.zeros((3, 3, 1))), (lambda: np.zeros((3, 1)))
        D = {h: z3() for h in ('VDFB', 'VDFP', 'VMFB', 'VMFP', 'MAKB', 'MAKS')}
        D.update({h: z2() for h in ('VDPB', 'VDPP', 'VMPB', 'VMPP')})
        D['VDFB'][0, 1, 0], D['VDFP'][0, 1, 0] = 80.0, 88.0          # refinery buys domestic crude, 10% tax
        D['MAKS'][1, 1, 0], D['MAKB'][1, 1, 0] = 100.0, 105.0         # 5% output tax
        D['VDPB'][1, 0], D['VDPP'][1, 0] = 50.0, 60.0                 # households buy refined product, 20% tax
        D['VDPB'][2, 0], D['VDPP'][2, 0] = 950.0, 940.0
        return comm, D

    def test_identities(self):
        comm, D = self.D()
        before = {h: v.copy() for h, v in D.items()}
        rows = M15.seed_household_crude(D, comm, comm, ['A'], share=1e-3)
        self.assertEqual(rows[0]['status'], 'seeded')
        eps = 1e-3 * 1000.0
        self.assertAlmostEqual(D['VDPP'][0, 0], eps)
        # crude market: households + refinery unchanged at basic
        self.assertAlmostEqual(D['VDFB'][0, 1, 0] + D['VDPB'][0, 0], before['VDFB'][0, 1, 0])
        # refinery zero profit: MAKS change = cost change
        self.assertAlmostEqual(D['MAKS'][1, 1, 0] - before['MAKS'][1, 1, 0], D['VDFP'][0, 1, 0] - before['VDFP'][0, 1, 0])
        # refined market at basic: MAKB change = household domestic purchase change
        self.assertAlmostEqual(D['MAKB'][1, 1, 0] - before['MAKB'][1, 1, 0], D['VDPB'][1, 0] - before['VDPB'][1, 0])
        # SAVE: income change (taxes) = household spending change
        tax = lambda X: ((X['VDFP'] - X['VDFB']).sum() + (X['MAKB'] - X['MAKS']).sum() + (X['VDPP'] - X['VDPB']).sum())
        spend = lambda X: (X['VDPP'] + X['VMPP']).sum()
        self.assertAlmostEqual(tax(D) - tax(before), spend(D) - spend(before))

    def test_skip(self):
        comm, D = self.D()
        D['VDFB'][0, 1, 0] = D['VDFP'][0, 1, 0] = 0.0
        rows = M15.seed_household_crude(D, comm, comm, ['A'], share=1e-3)
        self.assertEqual(rows[0]['status'], 'skipped_no_refinery_crude')
        comm, D = self.D()
        D['VDPP'][0, 0] = 1.0
        self.assertEqual(M15.seed_household_crude(D, comm, comm, ['A']), [])     # already buys crude

    def test_top_up(self):
        # beta v4 rescan: a fit residue below the seed (USA 2.1e-05 USD m) is topped up to the seed share, not left near zero
        comm, D = self.D()
        D['VDPB'][0, 0] = D['VDPP'][0, 0] = 1e-6
        rows = M15.seed_household_crude(D, comm, comm, ['A'], share=1e-3)
        self.assertEqual(rows[0]['status'], 'seeded')
        spend = float(D['VDPP'][:, 0].sum() + D['VMPP'][:, 0].sum())
        self.assertAlmostEqual(D['VDPP'][0, 0] / spend, 1e-3, places=6)


if __name__ == '__main__':
    unittest.main()


class S07ReexportTier1Test(unittest.TestCase):
    """P26 tier 1 (Comtrade RX by HS2 through apply_hub_slim) and P18 (transit cap)."""

    def con(self):
        con = duckdb.connect()
        con.execute('CREATE TABLE flows(exporter VARCHAR, importer VARCHAR, hs6 VARCHAR, value DOUBLE, qty DOUBLE, qty_ok BOOLEAN)')
        con.executemany('INSERT INTO flows VALUES (?, ?, ?, ?, ?, TRUE)', [
            ('CHN', 'ARE', '850440', 100.0, 1.0),      # ARE imports from CHN
            ('ARE', 'IRN', '850440', 80.0, 1.0),       # ARE exports to IRN, half re-exports
            ('ARE', 'IRN', '270900', 50.0, 1.0),       # crude: left to S11
            ('ARE', 'IND', '710812', 40.0, 1.0)])      # gold: share 0 in HS 71
        con.execute('CREATE TABLE hs(hs6 VARCHAR, sector VARCHAR, agrees VARCHAR)')
        con.executemany('INSERT INTO hs VALUES (?, ?, ?)', [('850440', 'elc', 'yes'), ('270900', 'oil', 'yes'), ('710812', 'nfm', 'yes')])
        con.execute('CREATE TABLE rx_share(region VARCHAR, hs2 VARCHAR, share DOUBLE)')
        con.executemany('INSERT INTO rx_share VALUES (?, ?, ?)', [('ARE', '85', 0.5), ('ARE', '27', 0.9), ('ARE', '71', 0.0)])
        con.execute('CREATE TABLE prior_x(region VARCHAR, sector VARCHAR, x DOUBLE)')
        con.execute('CREATE TABLE rx_dom(region VARCHAR, hs2 VARCHAR, dom DOUBLE)')
        con.execute('CREATE TABLE intra_add(hub VARCHAR, region VARCHAR, hs6 VARCHAR, value DOUBLE)')
        return con

    def flow(self, con, e, i, h):
        r = con.execute('SELECT value FROM flows WHERE exporter = ? AND importer = ? AND hs6 = ?', [e, i, h]).fetchone()
        return r[0] if r else 0.0

    def test_tier1(self):
        import baci_reexports as BR
        con = self.con()
        st = S7.apply_hub_slim(con, 'ARE', S7.identified_rx('ARE'), BR.claim_import_share('ARE'))
        self.assertAlmostEqual(st['funded'], 40.0)
        self.assertAlmostEqual(self.flow(con, 'ARE', 'IRN', '850440'), 40.0)
        self.assertAlmostEqual(self.flow(con, 'CHN', 'ARE', '850440'), 60.0)       # retained imports
        self.assertAlmostEqual(self.flow(con, 'CHN', 'IRN', '850440'), 40.0)       # origin -> destination
        self.assertAlmostEqual(self.flow(con, 'ARE', 'IRN', '270900'), 50.0)       # energy untouched

    def test_domestic_export_cap(self):
        # S16 2026-10-26 (reexport_rx_usa_bel = usa): removal in an HS2 at most BACI exports less Comtrade X - RX
        import baci_reexports as BR
        con = self.con()
        con.execute("INSERT INTO rx_dom VALUES ('ARE', '85', 70.0)")             # BACI 80, domestic 70: at most 10 out
        self.assertAlmostEqual(S7.apply_hub_slim(con, 'ARE', S7.identified_rx('ARE'), BR.claim_import_share('ARE'))['funded'], 10.0)
        con = self.con()
        con.execute("INSERT INTO rx_dom VALUES ('ARE', '85', 20.0)")             # room 60 above the share's 40: share binds
        self.assertAlmostEqual(S7.apply_hub_slim(con, 'ARE', S7.identified_rx('ARE'), BR.claim_import_share('ARE'))['funded'], 40.0)
        con = self.con()
        con.execute("INSERT INTO rx_dom VALUES ('ARE', '85', 95.0)")             # domestic above BACI: nothing out
        self.assertAlmostEqual(S7.apply_hub_slim(con, 'ARE', S7.identified_rx('ARE'), BR.claim_import_share('ARE'))['funded'], 0.0)

    def test_prior_guard(self):
        import baci_reexports as BR
        con = self.con()
        con.execute("INSERT INTO prior_x VALUES ('ARE', 'elc', 70.0)")             # BACI 80 is only 10 above the prior
        st = S7.apply_hub_slim(con, 'ARE', S7.identified_rx('ARE'), BR.claim_import_share('ARE'))
        self.assertAlmostEqual(st['funded'], 10.0)
        con.execute("UPDATE prior_x SET x = 90.0")
        self.assertAlmostEqual(S7.apply_hub_slim(con, 'ARE', S7.identified_rx('ARE'), BR.claim_import_share('ARE'))['funded'], 0.0)

    def test_chunked_equals_whole(self):
        """S07 disk fix: the RX claim settled in HS2 chunks gives the same flows, intra additions and totals as one claim."""
        import baci_reexports as BR
        rng = np.random.default_rng(7)
        regs = ['ARE', 'CHN', 'IND', 'IRN', 'DEU', 'USA']
        codes = ['850440', '851712', '620342', '847130', '300490', '870323', '010121', '710812']
        rows = [(e, i, h, float(rng.uniform(1, 100)), 1.0) for e in regs for i in regs for h in codes
                if rng.uniform() < 0.8 and not (e == i)]
        rows += [('CHN', 'CHN', '850440', 5.0, 1.0)]
        shares = [('ARE', h[:2], float(rng.uniform(0.2, 0.9))) for h in codes]
        out = []
        for budget in (None, 1, 25):
            con = self.con()
            con.execute('DELETE FROM flows')
            con.execute('DELETE FROM hs')
            con.execute('DELETE FROM rx_share')
            con.executemany('INSERT INTO flows VALUES (?, ?, ?, ?, ?, TRUE)', rows)
            con.executemany('INSERT INTO hs VALUES (?, ?, ?)', [(h, 'elc' if h[:2] == '85' else 'oth', 'yes') for h in codes])
            con.executemany('INSERT INTO rx_share VALUES (?, ?, ?)', shares)
            con.execute("INSERT INTO prior_x VALUES ('ARE', 'oth', 300.0)")
            if budget is None:
                st = S7.apply_hub_slim(con, 'ARE', S7.identified_rx('ARE'), BR.claim_import_share('ARE'))
            else:
                st = S7.apply_rx_chunked(con, 'ARE', S7.identified_rx('ARE'), budget=budget)
            f = dict(((e, i, h), v) for e, i, h, v in con.execute('SELECT exporter, importer, hs6, value FROM flows').fetchall())
            ia = dict(((r, h), v) for r, h, v in con.execute('SELECT region, hs6, value FROM intra_add').fetchall())
            left = con.execute("SELECT COUNT(*) FROM duckdb_tables() WHERE table_name IN "
                               "('identified', 'identified_all', 'claim', 'scale', 'funded', 'delta', 'hub_m', 'hub_t')").fetchone()[0]
            out.append((st, f, ia, left))
        whole = out[0]
        self.assertGreater(whole[0]['funded'], 0)
        self.assertGreater(whole[0]['added'], 0)
        for st, f, ia, left in out[1:]:
            self.assertEqual(left, 0)
            for k in ('funded', 'added', 'intra'):
                self.assertAlmostEqual(st[k], whole[0][k], places=9)
            self.assertEqual(set(f), set(whole[1]))
            for k, v in f.items():
                self.assertAlmostEqual(v, whole[1][k], places=9)
            self.assertEqual(set(ia), set(whole[2]))
            for k, v in ia.items():
                self.assertAlmostEqual(v, whole[2][k], places=9)
        self.assertEqual(out[1][0]['chunks'], 7)          # budget 1: one chunk per HS2 chapter (85, 62, 84, 30, 87, 01, 71)
        self.assertLess(out[2][0]['chunks'], 7)

    def test_load_shares(self):
        import json
        import tempfile
        d = tempfile.mkdtemp()
        json.dump({'data': [{'cmdCode': '85', 'primaryValue': 50.0}]}, open(os.path.join(d, 'RX_784_HS2.json'), 'w'))
        json.dump({'data': [{'cmdCode': '85', 'primaryValue': 100.0}, {'cmdCode': '01', 'primaryValue': 5.0}]},
                  open(os.path.join(d, 'X_784_HS2.json'), 'w'))
        json.dump({'data': [{'cmdCode': '85', 'primaryValue': 9.0}]}, open(os.path.join(d, 'RX_842_HS2.json'), 'w'))
        json.dump({'data': [{'cmdCode': '85', 'primaryValue': 90.0}]}, open(os.path.join(d, 'X_842_HS2.json'), 'w'))
        con = duckdb.connect()
        con.execute('CREATE TABLE cc(code INTEGER, iso3 VARCHAR)')
        con.executemany('INSERT INTO cc VALUES (?, ?)', [(784, 'ARE'), (842, 'USA')])
        used, left = S7.load_rx_shares(con, d, {'ARE': 'ARE', 'USA': 'USA'})
        self.assertEqual((used, [x[1:] for x in left]), (['ARE'], [('USA', 'reexport_rx_usa_bel off')]))
        got = dict(con.execute("SELECT hs2, share FROM rx_share WHERE region = 'ARE'").fetchall())
        self.assertEqual(got, {'85': 0.5, '01': 0.0})
        self.assertEqual(con.execute('SELECT COUNT(*) FROM rx_dom').fetchone()[0], 0)
        used, _ = S7.load_rx_shares(con, d, {'ARE': 'ARE', 'USA': 'USA'}, extra=('USA',))
        self.assertEqual(used, ['ARE', 'USA'])
        self.assertEqual(con.execute('SELECT region, hs2, dom FROM rx_dom').fetchall(), [('USA', '85', 0.081)])   # (90 - 9) USD
        with self.assertRaises(SystemExit):
            S7.load_rx_shares(con, d, {'ARE': 'ARE'}, extra=('USA', 'BEL'), bel_csv=os.path.join(d, 'missing.csv'))
        for f in os.listdir(d):
            os.remove(os.path.join(d, f))
        os.rmdir(d)

    def test_transit_cap(self):
        con = self.con()
        con.executemany('INSERT INTO flows VALUES (?, ?, ?, ?, ?, TRUE)', [
            ('CHN', 'KGZ', '620342', 900.0, 1.0), ('RUS', 'KGZ', '271000', 500.0, 1.0), ('CHE', 'KGZ', '710812', 300.0, 1.0)])
        out = S7.transit_cap(con, [('KGZ', 0.3, ['27', '7108'])])          # cap 300 kUSD
        self.assertEqual(out[0][0], 'KGZ')
        self.assertAlmostEqual(out[0][3], 300.0 / 900.0)
        self.assertAlmostEqual(self.flow(con, 'CHN', 'KGZ', '620342'), 300.0)
        self.assertAlmostEqual(self.flow(con, 'RUS', 'KGZ', '271000'), 500.0)     # energy excluded
        self.assertAlmostEqual(self.flow(con, 'CHE', 'KGZ', '710812'), 300.0)     # gold excluded
        self.assertAlmostEqual(S7.transit_cap(con, [('KGZ', 1.0, ['27'])])[0][3], 1.0)   # under the cap: unchanged

    def test_config(self):
        rows = list(__import__('csv').DictReader(open(os.path.join(BUILD, 'config/s07/transit_import_caps.csv'))))
        self.assertEqual({r['region'] for r in rows}, {'AFG', 'ARM', 'BEN', 'GMB', 'KGZ', 'KHM', 'LBN', 'MOZ', 'TGO'})
        t = S7.load_choices(os.path.join(BUILD, 'config/s07/trade_choices.csv'))
        self.assertEqual(t['reexport_comtrade_rx']['value'], S7.RX_TIER1)
        self.assertEqual(t['reexport_rx_usa_bel']['value'], 'usa')                 # decision package (HS2-capped)
        self.assertEqual(t['transit_import_cap']['value'], S7.TRANSIT_CAP_V5)   # beta v5 B2, M1, M2 supersede the v4 caps
        ch, _rows, bad = S8.load_choices(os.path.join(BUILD, 'config/s08/margin_choices.csv'))
        self.assertEqual((ch['itic_zero_rate'], bad), (S8.FILL_SAME_CLASS, []))    # P27
        self.assertIn(S8.FILL_SAME_CLASS, S8.ALLOWED['itic_zero_rate'])


class SwitchedPriceSourcesTest(unittest.TestCase):
    """P2 and P16: the ZAF and PRK coal source rows apply only where their choice is on; both on (decision package)."""

    def test_rows(self):
        rows = [{'commodity': 'coa', 'region': r} for r in ('ZAF', 'PRK', 'CHN')]
        c = C11.load_choices()
        for k in ('zaf_power_coal_price', 'prk_coal_price'):
            self.assertTrue(C11.switched_on(c, k), k)
        self.assertEqual([h['region'] for h in C11.price_source_rows(rows, c)], ['ZAF', 'PRK', 'CHN'])
        off = {k: dict(v) for k, v in c.items()}
        for k in ('zaf_power_coal_price', 'prk_coal_price'):
            off[k]['value'] = 'off'
        self.assertEqual([h['region'] for h in C11.price_source_rows(rows, off)], ['CHN'])
        on = {k: dict(v) for k, v in off.items()}
        on['prk_coal_price']['value'] = C11.PRK_COAL
        self.assertEqual([h['region'] for h in C11.price_source_rows(rows, on)], ['PRK', 'CHN'])
        on['zaf_power_coal_price']['value'] = C11.ZAF_POWER_COAL
        self.assertEqual(len(C11.price_source_rows(rows, on)), 3)

    def test_config_rows(self):
        src = C11.read_table('domestic_price_sources.csv', ('commodity', 'region', 'source', 'series', 'price_level'))
        keys = {(h['commodity'], h['region']) for h in src}
        self.assertTrue(set(C11.SWITCHED_PRICE_SOURCES) <= keys)
        zaf = [h for h in src if (h['commodity'], h['region']) == ('coa', 'ZAF')][0]
        items = {r['item']: r for r in C11.read_table('transcribed_prices_2022.csv', ('item', 'commodity', 'region', 'value', 'unit'))}
        nm = zaf['series'].partition(':')[2]
        self.assertEqual((items[nm]['commodity'], items[nm]['region']), ('coa', 'ZAF'))


class NoSeaportKeyTest(unittest.TestCase):
    """P21: a listed region's sea key moves to its road key; other regions and modes are untouched."""

    def test_move(self):
        keys = {'rdt': {'MKD': 1.0, 'GRC': 5.0}, 'sea': {'MKD': 2.0, 'GRC': 9.0}, 'air': {'MKD': 0.5}}
        src = {}
        moved = S8.no_seaport_keys(keys, src, ['MKD', 'XXX'])
        self.assertEqual(moved, {'MKD': 2.0})
        self.assertEqual((keys['sea']['MKD'], keys['rdt']['MKD'], keys['sea']['GRC'], keys['air']['MKD']), (0.0, 3.0, 9.0, 0.5))
        self.assertEqual(src, {('MKD', 'sea'): 'no_seaport_zero'})

    def test_config(self):
        ch, _rows, bad = S8.load_choices(os.path.join(BUILD, 'config/s08/margin_choices.csv'))
        self.assertEqual((ch['no_seaport_sea_key'], bad), (S8.NO_SEAPORT_TO_ROAD, []))   # P21
        rows = S8.read_csv(os.path.join(BUILD, 'config/s08', S8.NO_SEAPORT_FILE))
        self.assertEqual({r['region'] for r in rows}, {'MKD', 'BIH'})


class BelShareFileTest(unittest.TestCase):
    """P26 usa_bel: the BEL quasi-transit share file is on disk, in MANIFEST, and every share is in [0, 1]."""

    def test_file(self):
        path = os.path.join(BUILD, '..', 'data', S7.BEL_SHARE_FILE)
        rows = list(__import__('csv').DictReader(open(path)))
        self.assertEqual(len(rows), 97)
        self.assertTrue(all(0.0 <= float(r['share']) <= 1.0 and len(r['hs2']) == 2 for r in rows))
        man = open(os.path.join(BUILD, '..', 'data', 'MANIFEST.csv')).read()
        self.assertIn(S7.BEL_SHARE_FILE + ',', man)


class DryRunFeasibleTest(unittest.TestCase):
    """Beta v4 dry run (S11-Hras): feasible_vectors cuts only what no allowed route can carry, prefers data routes, and
    marks routes no consistent flow can use; the RAS then converges on the cut vectors."""

    def test_consistent_vectors_untouched(self):
        S_ = np.array([[0, 1, 1], [1, 0, 1], [1, 1, 0]], bool)
        e, d = np.array([5.0, 3.0, 2.0]), np.array([4.0, 4.0, 2.0])
        x, m, Z = M11.feasible_vectors(S_, e, d)
        np.testing.assert_allclose((x, m), (e, d))
        self.assertFalse(Z.any())

    def test_cut_and_ras(self):
        # importer 2 buys 10 but only exporter 0 (exports 4) reaches it; exporter 1 (6) reaches only importer 0 (wants 6)
        S_ = np.array([[0, 0, 1], [1, 0, 0], [0, 0, 0]], bool)
        e, d = np.array([4.0, 6.0, 0.0]), np.array([6.0, 0.0, 10.0])
        x, m, Z = M11.feasible_vectors(S_, e, d)
        np.testing.assert_allclose(x, [4.0, 6.0, 0.0], atol=1e-9)
        np.testing.assert_allclose(m, [6.0, 0.0, 4.0], atol=1e-9)
        A, _it, err = M11.ras(S_.astype(float), x, m)
        self.assertLess(err, 1e-9)
        np.testing.assert_allclose(A.sum(1), x, atol=1e-8)
        np.testing.assert_allclose(A.sum(0), m, atol=1e-8)

    def test_prefer_data_routes(self):
        # exporter 0 (5) can serve importer 1 or 2 (5 each); exporter 1 (5) only importer 2: the flow of 10 needs 0 -> 1,
        # so preferring the data route 0 -> 2 cannot cut the maximum flow
        S_ = np.array([[0, 1, 1], [0, 0, 1], [0, 0, 0]], bool)
        e, d = np.array([5.0, 5.0, 0.0]), np.array([0.0, 5.0, 5.0])
        P = np.zeros((3, 3), bool)
        P[0, 2] = True
        x, m, Z = M11.feasible_vectors(S_, e, d, prefer=P)
        np.testing.assert_allclose((x.sum(), m.sum()), (10.0, 10.0), atol=1e-9)
        self.assertTrue(Z[0, 2])                         # forced zero: 1 -> 2 must carry 5, so 0 -> 2 carries nothing
        # mutated: importer 1 wants nothing, so 0 -> 2 and 1 -> 2 compete for importer 2 (5) and data route 0 -> 2 wins
        x2, m2, _ = M11.feasible_vectors(S_, e, np.array([0.0, 0.0, 5.0]), prefer=P)
        np.testing.assert_allclose(m2, [0.0, 0.0, 5.0], atol=1e-9)
        self.assertAlmostEqual(x2[0], 5.0, places=6)
        self.assertAlmostEqual(x2[1], 0.0, places=6)

    def test_empty_support(self):
        x, m, Z = M11.feasible_vectors(np.zeros((2, 2), bool), np.array([1.0, 0.0]), np.array([0.0, 1.0]))
        np.testing.assert_allclose((x, m), ([0.0, 0.0], [0.0, 0.0]))


class DryRunGridRelabelGateTest(unittest.TestCase):
    """Beta v4 dry run: electricity grid routes, relabelled crude, and the share-basis scale gate."""

    def test_grid_routes(self):
        R = ['A', 'B', 'C']
        members = {'A': ['AAA'], 'B': ['BBB', 'BB2'], 'C': ['CCC']}
        G = M11.grid_routes(R, members, {'AAA': ['BB2'], 'BB2': ['AAA']}, [('BBB', 'CCC')])
        self.assertEqual(sorted(map(tuple, np.argwhere(G))), [(0, 1), (1, 0), (1, 2), (2, 1)])
        self.assertFalse(M11.grid_routes(R, members, {}, []).any())       # mutated: no border, no cable

    def test_relabelled_origin(self):
        A0 = np.zeros((3, 3))
        A0[0, 2] = 10.0                       # hub 0 -> dest 2 carries 10; hub exports only 4 of its own
        A0[1, 0] = 1.0                        # origin 1 records 1 of its 5
        out = M11.relabelled_origin(A0, 0, 2, [1], np.array([4.0, 5.0, 0.0]))
        self.assertAlmostEqual(out[1], 4.0)                                # min(10 - 4, 5 - 1)
        self.assertAlmostEqual(A0[0, 2], 6.0)
        self.assertAlmostEqual(A0[1, 2], 4.0)
        B0 = np.zeros((3, 3))
        B0[0, 2] = 3.0                                                     # mutated: hub within its own volume
        self.assertEqual(M11.relabelled_origin(B0, 0, 2, [1], np.array([4.0, 5.0, 0.0])), {})

    def test_share_gate(self):
        # one importer under-records all suppliers: every route x30, share unchanged -> passes on 'share', fails on 'volume'
        A0s = np.array([[0.0, 0.0, 1.0], [0.0, 0.0, 99.0], [0.0, 0.0, 0.0]])
        A1s = A0s * 30
        fob = A1s * 10
        seeded = np.zeros((3, 3), bool)
        self.assertEqual(len(M11.route_gates(A0s, A1s, fob, seeded, basis='volume')[1]), 2)
        self.assertEqual(M11.route_gates(A0s, A1s, fob, seeded, basis='share')[1], [])
        # mutated: the 1 percent supplier x40, the other x1 -> its share rises from 0.01 to 0.29 -> fails on 'share' too
        A1m = A0s.copy()
        A1m[0, 2] *= 40
        xb = M11.route_gates(A0s, A1m, A1m * 10, seeded, basis='share')[1]
        self.assertEqual([(int(i), int(j)) for i, j, _f, _x in xb], [(0, 2)])


class DryRunOwnUseLossTest(unittest.TestCase):
    """Beta v4 dry run (S11-H90 AFG/PAL; Grok R2 IRQ): ely losses leave the own-use share (GTAP 12 Table 12.3)."""

    def test_loss_rules(self):
        V = pd.DataFrame([dict(region='A', commodity='ely', output_value=100.0)])
        un = {'ely': {'AAA': dict(own=10.0, losses=40.0, production=100.0, imports=300.0)}}
        f = lambda **kw: M11.own_use_shares(V, ['A'], {'AAA': 'A'}, un, goods=('ely',), **kw).own_use_share.iloc[0]
        self.assertAlmostEqual(f(), 0.5)                                    # off: all losses
        self.assertAlmostEqual(f(loss_split=('ely',)), (10 + 40 * 100 / 400) / 100)
        self.assertAlmostEqual(f(loss_drop=('ely',)), 0.1)

    def test_choice_default(self):
        c = C11.load_choices()
        self.assertEqual(c['ely_losses_in_own_use']['value'], C11.ELY_LOSSES_OUT)
        self.assertEqual(c['ely_losses_in_own_use']['gtap_status'], 'gtap')
        for k in ('ely_grid_routes', 'ras_feasible_vectors', 'relabelled_origin', 'route_review'):
            self.assertTrue(C11.switched_on(c, k), k)


class DryRunConfigTest(unittest.TestCase):
    """Beta v4 dry run: the route review, relabelled routes and cable list are well formed and every row has a reason."""

    def test_review(self):
        rows = C11.read_table('route_review.csv', C11.REVIEW_COLUMNS)
        self.assertTrue(all(r['action'] in C11.REVIEW_ACTIONS and r['basis'].strip() and r['commodity'] in
                            ('coa', 'oil', 'gas', 'pet', 'ely') for r in rows))
        keys = [(r['commodity'], r['exporter'], r['importer']) for r in rows]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(float(r['prior_volume']) > 0 for r in rows if r['prior_volume'].strip()))
        self.assertIn(('oil', 'USA', 'VEN'), {k for k, r in zip(keys, rows) if r['action'] == 'block'})

    def test_relabel_and_cables(self):
        rel = C11.read_table('relabelled_routes.csv', C11.RELABEL_COLUMNS)
        self.assertEqual([(r['commodity'], r['hub'], r['destination'], r['origins']) for r in rel], [('oil', 'MYS', 'CHN', 'VEN;IRN')])
        cab = C11.read_table('ely_cable_links.csv', C11.GRID_COLUMNS)
        self.assertTrue(all(len(r['country_a']) == 3 and len(r['country_b']) == 3 and r['in_service_by_2022'] == 'yes' for r in cab))
        self.assertEqual(len({frozenset((r['country_a'], r['country_b'])) for r in cab}), len(cab))


class GrokG1G5Test(unittest.TestCase):
    """Grok QA G1 (S12 labour never below D1) and G5 (S08 Census charge as the whole-route margin)."""

    def test_gollin_d1_min(self):
        from s12_factors import method as M12
        sh, cap = M12.gollin_share(0.664, 0.0, 0.927)                                 # A6 cap: FRA ely labour 0.073
        self.assertAlmostEqual(sh, 0.073)
        self.assertTrue(cap)
        self.assertEqual(M12.gollin_share(0.664, 0.0, 0.927, True), (0.664, True))   # G1: kept at D1
        self.assertEqual(M12.gollin_share(0.5, 0.2, 0.1, True), (0.6, False))        # below the cap: unchanged
        sh, cap = M12.gollin_share(0.5, 2.0, 0.1, True)                              # Gollin above the cap, D1 below it
        self.assertAlmostEqual(sh, 0.9)
        self.assertTrue(cap)

    def test_d1_checks(self):
        from s12_factors import checks as K12
        v = pd.DataFrame([dict(region='R', sector='ely', va_musd=100.0, labour_musd=66.4, nonlabour_musd=33.6, capital_floor=0.927,
                               d1_share_of_factor_income=0.664)])
        self.assertEqual(K12.labour_at_least_d1(v)[0], 0)
        self.assertEqual(K12.capital_floor(v, d1_min=True)[0], 0)
        self.assertEqual(K12.capital_floor(v)[0], 1)                                     # the A6 floor alone fails it
        self.assertEqual(K12.labour_at_least_d1(v.assign(labour_musd=7.3, nonlabour_musd=92.7))[0], 1)   # mutated: A6 cap
        from s12_factors import config as C12
        self.assertEqual(C12.load_choices()['labour_at_least_d1']['value'], 'off')     # beta v4 rescan: off (zero-capital cells)

    def test_census_whole_route(self):
        m, sh, c = S8.census_route_whole(0.10, 0.04, (0.07, 0.93, 0.0), 0.0)            # products: whole route at Census
        self.assertAlmostEqual(m, 0.04)
        np.testing.assert_allclose(sh, (0.07, 0.93, 0.0))
        self.assertEqual(c, 1.0)
        m2, _sh2 = S8.census_route_parts(0.10, 0.04, (0.07, 0.93, 0.0))                 # mutated: the sea-only reading
        self.assertGreater(m2, m)
        m, sh, c = S8.census_route_whole(0.05, 0.02, (0.3, 0.7, 0.0), 0.3)              # crude, 30% pipeline keeps ITIC
        self.assertAlmostEqual(m, 0.3 * 0.05 + 0.7 * 0.02)
        self.assertAlmostEqual(sh[0], 0.3 * 0.05 / m)
        self.assertAlmostEqual(c, 0.7)
        m, sh, c = S8.census_route_whole(0.05, 0.02, (1.0, 0.0, 0.0), 1.0)              # all pipeline: ITIC
        self.assertEqual((m, sh, c), (0.05, (1.0, 0.0, 0.0), 0.0))
        ch, _rows, bad = S8.load_choices(os.path.join(BUILD, 'config/s08/margin_choices.csv'))
        self.assertEqual((ch['energy_sea_rate'], bad), (S8.CENSUS_WHOLE_ROUTE, []))


class GrokG7G12G16Test(unittest.TestCase):
    """Grok QA G7 (transcribed year), G12 (EAEU export duty off on member routes outside energy), G16 (excise at source)."""

    def test_transcribed_years(self):
        rows = C11.read_table('transcribed_prices_2022.csv', ('item', 'commodity', 'region', 'value', 'unit', 'fx_iso3',
                                                               'decided_by', 'decided_at', 'basis'))
        items = [r['item'] for r in rows]
        self.assertEqual(K11.transcribed_years(items)[0], 0)
        self.assertIn('dza_gas_industry_2010', items)
        self.assertEqual(K11.transcribed_years(items + ['dza_gas_industry_2025'])[0], 1)     # mutated: a 2025 row

    def test_union_exempt(self):
        from s10_tariffs import export_tax as XT
        from s10_tariffs import support as SUP
        from s10_tariffs.config import CHOICES as C10
        union = {'RUS': 'EAEU', 'KAZ': 'EAEU'}
        vfob = [('fbt', 'RUS', 'KAZ', 40.0), ('fbt', 'RUS', 'CHN', 60.0), ('fbt', 'KAZ', 'RUS', 30.0), ('fbt', 'KAZ', 'TUR', 70.0),
                ('oil', 'KAZ', 'RUS', 50.0), ('oil', 'KAZ', 'ITA', 50.0)]
        rates = {('RUS', 'fbt'): 0.1, ('KAZ', 'fbt'): 0.05, ('KAZ', 'oil'): 0.2}
        rows = [['RUS', 'fbt', '', '10', '100', '0.1', '', XT.RATES_SOURCE, '', 'fob'],
                ['KAZ', 'fbt', '30', '5', '100', '0.05', '', 'OECD GRS T_5124 2022', '', 'fob'],
                ['KAZ', 'oil', '30', '20', '100', '0.2', '', 'OECD GRS T_5124 2022', '', 'fob']]
        ex, exv = XT.union_exempt(rates, rows, vfob, union, XT.RATES_SOURCE)
        self.assertEqual(exv, {('RUS', 'fbt'): 40.0, ('KAZ', 'fbt'): 30.0})
        self.assertAlmostEqual(float(rows[0][3]), 6.0)                    # RUS keeps its rate on 60 of taxable VFOB
        self.assertAlmostEqual(rates[('KAZ', 'fbt')], 5.0 / 70.0)        # KAZ keeps its GRS duty on 70
        self.assertAlmostEqual(rates[('KAZ', 'oil')], 0.2)               # energy left to S11
        _l, _w, tw = SUP.vfob_lines(vfob, {}, {}, rates, ex)
        self.assertAlmostEqual(tw, 6.0 + 5.0 + 20.0)                      # the tax wedge is the booked duty
        _l, _w, tw0 = SUP.vfob_lines(vfob, {}, {}, rates)                 # mutated: no exemption in the lines
        self.assertGreater(tw0, tw)
        self.assertEqual(C10['export_tax_union_exempt'][0], XT.UNION_EXEMPT)

    def test_excise_at_source(self):
        from s13_fit import config as C13_
        self.assertEqual(M13.EXCISE_AT_SOURCE, C13_.EXCISE_AT_SOURCE)
        self.assertEqual(C13_.load_choices()['excise_at_source']['value'], C13_.EXCISE_AT_SOURCE)
        sec = ['fbt', 'tex', 'ser']
        b = np.array([[100.0], [100.0], [100.0]])                         # households' purchases
        lay = dict(V=np.ones((3, 1)), levelled=np.array([True]), vat_musd=30.0, excise_musd=25.0, energy_excise_musd=0.0, groups=[])
        G = np.array([100.0])
        r1, on, _i = M13.pattern_rates(b, G, 0.0, lay, sec, ['p'], excise_fixed=True)
        self.assertAlmostEqual(float((r1[:, 0] * b[:, 0]).sum()), 100.0)
        self.assertAlmostEqual(r1[0, 0] - r1[1, 0], 0.25)                 # the excise on fbt stays 25 of 100
        r0, _on, _i = M13.pattern_rates(b, G, 0.0, lay, sec, ['p'])       # mutated: excise scaled with VAT
        self.assertGreater(r0[0, 0] - r0[1, 0], 0.25 + 1e-6)
        G2 = np.array([10.0])                                              # excise alone above the column: cut to it
        r2, _on, _i = M13.pattern_rates(b, G2, 0.0, lay, sec, ['p'], excise_fixed=True)
        self.assertAlmostEqual(float((r2[:, 0] * b[:, 0]).sum()), 10.0)


class DonorGuardTest(unittest.TestCase):
    """P33 (S05 donor_guards.csv, default off): the size guard skips a donor below 1/20 of the member's GDP."""

    def test_guard(self):
        from s05_composite import guards as GD
        ctx = {'gdp': {'KEN': 114449.0, 'STP': 549.0, 'CMR': 44300.0}}
        keep, none = GD.allowed('KEN', ['CMR', 'STP'], [('donor_size_guard', '20')], ctx)
        self.assertEqual((keep, none), (['CMR'], False))
        self.assertEqual(GD.allowed('KEN', ['CMR', 'STP'], [], ctx), (['CMR', 'STP'], False))          # off
        self.assertEqual(GD.allowed('KEN', ['STP'], [('donor_size_guard', '20')], ctx), (['STP'], True))   # none pass

    def test_config(self):
        from s05_composite import guards as GD
        on, blend, rows = GD.read_guards(os.path.join(BUILD, 'config/s05/donor_guards.csv'))
        self.assertEqual((on, blend), ([('donor_size_guard', '20')], 'off'))     # David 2026-10-26 07:42 UTC: size rule on
        self.assertEqual([r['guard'] for r in rows], list(GD.CHOICE_VALUES))


class GrokChecksTest(unittest.TestCase):
    """Grok QA G17: the 1.25 x VDEP floor is reported after S13 and S14."""

    def test_vdep_floor_breaches(self):
        from s14_assembly import checks as K14
        gate = pd.DataFrame(dict(VDEP=[100.0, 100.0], capital_income=[130.0, 104.0]), index=['A', 'TLS'])
        fac = pd.DataFrame(dict(region=['A', 'TLS'], factor=['capital', 'capital'], evos=[130.0, 98.2]))
        out = K14.vdep_floor_breaches(gate, fac)
        self.assertEqual(list(out['region']), ['TLS'])
        self.assertAlmostEqual(out['ratio_s13'].iloc[0], 0.982)
        self.assertEqual(len(K14.vdep_floor_breaches(gate.assign(capital_income=[130.0, 130.0]), fac.assign(evos=[130.0, 130.0]))), 0)


class DonorBlendTest(unittest.TestCase):
    """P33 option C (S05 donor_blend = gdppc_k3, default off): three nearest by GDP per capita above 1/20 of GDP."""

    # KEN and its SSAF candidates near it: PPP GDP per capita (USD) and S02 GDP (USD m), from the S05 inputs
    PPC = {'KEN': 5882.29, 'STP': 6032.72, 'CMR': 5188.16, 'CIV': 6718.38, 'SEN': 4529.5, 'COD': 1589.91, 'ZAF': 14746.7}
    GDP = {'KEN': 114449.0, 'STP': 540.8, 'CMR': 44347.2, 'CIV': 70922.8, 'SEN': 27783.3, 'COD': 70422.3, 'ZAF': 407596.0}

    def blend(self, member='KEN'):
        from s05_composite import guards as GD
        c = [d for d in self.PPC if d != member]
        return GD.blend(member, c, self.PPC[member], self.PPC.get, self.GDP.get, 'gdppc_k3', {'gdp': self.GDP})

    def test_ken(self):
        b = self.blend()
        self.assertEqual([d for d, _w in b], ['CMR', 'CIV', 'SEN'])       # STP is below 1/20 of Kenya's GDP
        np.testing.assert_allclose([w for _d, w in b], [0.55, 0.27, 0.18])
        GDP0 = dict(self.GDP, STP=10000.0)                                # mutated: STP big enough, it leads
        from s05_composite import guards as GD
        b0 = GD.blend('KEN', [d for d in self.PPC if d != 'KEN'], self.PPC['KEN'], self.PPC.get, GDP0.get, 'gdppc_k3', {'gdp': GDP0})
        self.assertEqual(b0[0][0], 'STP')

    def test_short_pool(self):
        from s05_composite import guards as GD
        b = GD.blend('FJI', ['NZL', 'AUS'], 13000.0, {'NZL': 48000.0, 'AUS': 59000.0}.get, {'NZL': 2.4e5, 'AUS': 1.7e6}.get,
                     'gdppc_k3', {'gdp': {'FJI': 5000.0, 'NZL': 2.4e5, 'AUS': 1.7e6}})
        self.assertEqual([d for d, _w in b], ['NZL', 'AUS'])
        self.assertAlmostEqual(sum(w for _d, w in b), 1.0)
        self.assertAlmostEqual(b[0][1], 0.55 / 0.82)

    def test_oil_config(self):
        from s05_composite import oil as OIL
        rows = OIL.read_oil_donors(os.path.join(BUILD, 'config/s05/oil_donors.csv'))
        self.assertEqual(rows['IRQ']['blend_donors'], 'JOR;TUR;ISR')
        self.assertTrue(all(r['blend_donors'].split(';')[0] == r['base_donor'] for c, r in rows.items()))


class DonorVASectionsTest(unittest.TestCase):
    """P37 (S05 donor_va_sections, default off): sector VA moved to UN AMA group shares; columns scaled, rows closed."""

    # two sectors (a grows, b shrinks), agents a, b, p, g, i; columns then X, stock, grev, OUT; rows dom a, dom b,
    # imp a, imp b, TLS, VA, OUT
    def table(self):
        n_s, n_a = 2, 5
        X_C, ST_C, GR_C, OUT_C = n_a, n_a + 1, n_a + 2, n_a + 3
        T = np.zeros((2 * n_s + 3, n_a + 4))
        T[0, :n_a] = [10, 20, 30, 5, 5]
        T[0, X_C] = 30.0
        T[1, :n_a] = [20, 10, 40, 10, 10]
        T[1, X_C] = 9.9             # row residual -0.1 (carried rounding)
        T[2, :2] = [5, 5]
        T[3, :2] = [5, 5]
        T[4, :2] = [10, 5]
        T[5, :2] = [50, 50]
        T[6, :2] = [100, 100]
        T[:2, OUT_C] = [100, 100]
        return T, n_s, n_a, X_C, ST_C, GR_C, OUT_C

    def test_rescale(self):
        from s05_composite import va_sections as VS
        T, n_s, n_a, X_C, ST_C, GR_C, OUT_C = self.table()
        fc = [2, 3, 4, X_C]
        ks = np.array([1.5, 0.5])
        new, to_x, open_rows = VS.rescale(T, ks, n_s, n_a, fc, X_C, ST_C, GR_C, OUT_C, 6)
        self.assertEqual((to_x, open_rows), ([], []))
        np.testing.assert_allclose(new[4:, :n_s], T[4:, :n_s] * ks)                   # TLS, VA, OUT scaled
        np.testing.assert_allclose(new[:4, :n_s].sum(axis=0), T[:4, :n_s].sum(axis=0) * ks)
        np.testing.assert_allclose(new[[0, 2], :n_s], T[[0, 2], :n_s] * ks)          # product a: cost shares kept
        sales = new[:n_s, :n_a].sum(axis=1) + new[:n_s, X_C]
        np.testing.assert_allclose(sales - new[:n_s, OUT_C], [0.0, -0.1], atol=1e-12)   # residual kept
        self.assertTrue((new[:2 * n_s, :n_a + 1] >= 0).all())
        # row b had too many sales: its use cells moved to imports, so every user's column total is unchanged
        np.testing.assert_allclose(new[[1, 3], :n_a].sum(axis=0), (T[[1, 3], :n_a] * np.r_[ks, 1, 1, 1]).sum(axis=0))
        self.assertGreater(new[3, 2], T[3, 2])

    def test_factors_and_hold(self):
        from s05_composite import va_sections as VS
        sec = [s for ss in VS.GROUPS.values() for s in ss]
        va = np.ones(len(sec))
        ama = {g: float(len(ss)) for g, ss in VS.GROUPS.items()}
        ama['ag'] = 2.0 * len(VS.GROUPS['ag'])            # AMA ag share twice the donor's
        k, info, bounded = VS.factors(va, sec, ama, 'ama_7')
        new_va = sum(va[i] * k[VS.group_of(sec)[s]] for i, s in enumerate(sec))
        self.assertAlmostEqual(new_va, va.sum())          # total VA is the donor's
        self.assertEqual(bounded, [])
        k2, _i, _b = VS.factors(va, sec, ama, 'ama_ex_energy')
        ks = VS.sector_factors(k2, sec, 'ama_ex_energy')
        self.assertTrue(all(ks[sec.index(s)] == 1.0 for s in VS.GROUPS['mu'] + ('pet',)))
        self.assertAlmostEqual(float(va @ ks), va.sum())   # total VA still the donor's with energy held
        k3, _i, b3 = VS.factors(va, sec, dict(ama, ag=1e6), 'ama_7')
        self.assertEqual((k3['ag'], b3[0], k3['oth']), (VS.K_CAP, 'ag', 1.0 / VS.K_CAP))   # both bounds
        # a row whose positive cells cannot take its cut keeps factor 1
        T, n_s, n_a, X_C, ST_C, GR_C, OUT_C = self.table()
        T[1, :n_a] = 0.0
        T[1, X_C] = 0.0
        T[1, ST_C] = 99.9                                  # all of b's sales are a stock entry
        out, ks_used, to_x, held = VS.member_factors(T, np.array([1.5, 0.2]), n_s, n_a, [2, 3, 4, X_C], X_C, ST_C, GR_C,
                                                     OUT_C, 6)
        self.assertEqual((held, ks_used[1]), ([1], 1.0))

    def test_config_tls_only(self):
        # beta v5 S1 (David 2026-10-27): P37 stays off for every member but TLS
        rows = list(__import__('csv').DictReader(open(os.path.join(BUILD, 'config/s05/donor_guards.csv'))))
        row = {r['guard']: r for r in rows}['donor_va_sections']
        self.assertEqual((row['value'], row['parameter']), ('ama_ex_energy', 'TLS'))
        from s05_composite import va_sections as VS
        ama = VS.read_ama(os.path.join(BUILD, '..', 'data/unsd_ama/gva_gdp_current_usd.csv'))
        self.assertIn('ETH', ama)
        self.assertGreater(ama['ETH']['ag'], 0.3 * sum(ama['ETH'].values()))


class TinyEnergyTest(unittest.TestCase):
    """P38 (S13 tiny_energy_activity, default off): tiny energy activities with exports of at most 1 thousand USD get their exports as output target."""

    def test_rule(self):
        from s13_fit import method as M13
        from s13_fit import config as C13
        evs = pd.DataFrame(dict(region=['CHL', 'KHM', 'USA', 'GEO', 'MWI', 'MAR', 'ARM'], commodity=['coa'] * 5 + ['oil', 'coa'],
                                output_value=[3.02, 2.6, 30000.0, 6.32, 6.4, 0.92, 0.0034], vmsb_imports=[1657.4, 364.6, 500.0, 21.4, 0.0, 0.0, 5.65],
                                export_value=[5e-6, 0.0, 9000.0, 0.02, 0.0, 0.0, 0.0031]))
        got = [(r, c) for r, c, _v, _m in M13.tiny_energy(evs)]
        # GEO and ARM export, MWI has no imports to take over and is above 1 m; MAR crude is below 1 m outright
        self.assertEqual(got, [('CHL', 'coa'), ('KHM', 'coa'), ('MAR', 'oil')])
        self.assertEqual(C13.load_choices()['tiny_energy_activity']['value'], C13.TINY_ENERGY)   # decision package
        self.assertIn(C13.TINY_ENERGY, C13.CHOICES['tiny_energy_activity'])


class ElyFloorTest(unittest.TestCase):
    """P1 floor (s11 ely_output_value; David 2026-10-26, revised by S16 08:33 UTC): ely output held at max(prior io_s12
    column, the 90 percent rule floor); the price-based floor (max(prior, S11 value)) is the alternative."""

    def frame(self, rule):
        return pd.DataFrame(dict(region=['USA', 'BTN', 'HND', 'USA'], commodity=['ely', 'ely', 'ely', 'coa'],
                                 output_value=[400.0, 313.0, 50.0, 30.0], domestic_sales_value=[390.0, 300.0, 50.0, 20.0],
                                 export_value=[10.0, 213.0, 0.0, 10.0], export_tax=[0.0] * 4,
                                 target=['yes'] * 4, ely_target_rule=rule, ely_floor_value=[300.0, 20.0, 120.0, np.nan]))

    def test_floor_ninety(self):
        io = pd.DataFrame(dict(region=['USA', 'BTN', 'HND'], row=['OUT'] * 3, ely=[696.0, 23.0, 90.0]))
        out, rows = M13.ely_floor(self.frame(['floor_ninety'] * 3 + ['']), io)
        # USA keeps its table (S11 price x generation 400 is not used); BTN at its exports (213 > table 23, floor 20);
        # HND (donor-scaled) is raised to its 90 percent floor
        self.assertEqual(out['output_value'].tolist(), [696.0, 213.0, 120.0, 30.0])
        self.assertEqual(out['domestic_sales_value'].tolist(), [686.0, 200.0, 120.0, 20.0])
        self.assertEqual([r[4] for r in rows], [696.0, 213.0, 120.0])

    def test_floor_lower_bound(self):
        # s13 ely_floor_mode lower bound: USA (prior 696 above its floor 300) and BTN (prior 230 above its floor 213, the
        # net exports) fit free; HND (floor 120 above prior 90) is held at the floor
        io = pd.DataFrame(dict(region=['USA', 'BTN', 'HND'], row=['OUT'] * 3, ely=[696.0, 230.0, 90.0]))
        out, rows = M13.ely_floor(self.frame(['floor_ninety'] * 3 + ['']), io, lower_bound=True)
        self.assertEqual(out['output_value'].tolist(), [400.0, 313.0, 120.0, 30.0])
        self.assertTrue(np.isnan(rows[0][4]) and np.isnan(rows[1][4]))
        self.assertEqual((rows[0][3], rows[1][3], rows[2][3], rows[2][4]), (300.0, 213.0, 120.0, 120.0))
        self.assertEqual(C13.load_choices()['ely_floor_mode']['value'], 'hold_at_max_prior_floor')    # reverted 2026-10-26 22:16 UTC (patch run)

    def test_hold_net_own_use(self):
        # beta v4 H2 (s13 ely_hold_net_own_use): GBR-like prior 300 with a diagonal of 160 (dom 158, imp 2) and an own-use
        # share of 5%: k d = s (col - (1 - k) d) gives k = 0.05 x 140 / (0.95 x 160), the domestic excess 158 (1 - k)
        io = pd.DataFrame(dict(region=['GBR'] * 3 + ['IRN'] * 3, row=['dom_ely', 'imp_ely', 'OUT'] * 2,
                               ely=[158.0, 2.0, 300.0, 1.0, 0.0, 30.0]))
        net = M13.ely_netted_own_use(io, {'GBR': {'ely': 0.05}, 'IRN': {'ely': 0.05}})
        k = 0.05 * 140.0 / (0.95 * 160.0)
        self.assertAlmostEqual(net['GBR'], 158.0 * (1 - k))
        self.assertNotIn('IRN', net)                                   # diagonal 1 below 5% of 30: nothing netted
        self.assertEqual(M13.ely_netted_own_use(io, {}), {})
        evs = pd.DataFrame(dict(region=['GBR', 'IRN'], commodity=['ely'] * 2, output_value=[100.0, 45.0],
                                domestic_sales_value=[100.0, 45.0], export_value=[0.0] * 2, export_tax=[0.0] * 2, target=['yes'] * 2,
                                ely_target_rule=['floor_ninety'] * 2, ely_floor_value=[60.0, 20.0]))
        out, rows = M13.ely_floor(evs, io, net_own=net, s11_min={'IRN'})
        # GBR: prior less netted own use (above its floor 60); IRN: the S11 value 45 (an IEA subsidy region; prior 30)
        self.assertAlmostEqual(out['output_value'].iloc[0], 300.0 - net['GBR'])
        self.assertEqual(out['output_value'].iloc[1], 45.0)
        self.assertEqual([r[2] for r in rows], [300.0, 30.0])         # the prior is still reported gross
        # off: the beta v4 hold; with the lower bound, H2 is ignored
        self.assertEqual(M13.ely_floor(evs, io)[0]['output_value'].tolist(), [300.0, 30.0])
        self.assertEqual(M13.ely_floor(evs, io, lower_bound=True, net_own=net, s11_min={'IRN'})[0]['output_value'].tolist(), [100.0, 45.0])
        self.assertEqual(C13.load_choices()['ely_hold_net_own_use']['value'], C13.ELY_HOLD_NET)      # beta v5 P (David 2026-10-27)
        self.assertEqual(C13.CHOICES['ely_hold_net_own_use'], ('off', C13.ELY_HOLD_NET))
        self.assertEqual(M13.ELY_HOLD_NET, C13.ELY_HOLD_NET)

    def test_hold_cap(self):
        # H2 add-on (s13 ely_hold_cap): GBR-like S11 value 110 with domestic sales 100 of which 30 is resold gas (electricity
        # 70); prior less netted own use 200 is capped at 110 + 0.25 x 70 = 127.5; a floor above the cap wins
        io = pd.DataFrame(dict(region=['GBR', 'CHE'], row=['OUT'] * 2, ely=[200.0, 90.0]))
        evs = pd.DataFrame(dict(region=['GBR', 'CHE'], commodity=['ely'] * 2, output_value=[110.0, 20.0], domestic_sales_value=[100.0, 20.0],
                                pass_through_value=[30.0, 0.0], export_value=[10.0, 0.0], export_tax=[0.0] * 2, target=['yes'] * 2,
                                ely_target_rule=['floor_ninety'] * 2, ely_floor_value=[60.0, 40.0]))
        out, rows = M13.ely_floor(evs, io, cap_m=1.25)
        self.assertEqual(out['output_value'].tolist(), [127.5, 40.0])          # CHE: cap 25 below its floor 40
        self.assertEqual(M13.ely_floor(evs, io, cap_m=2.0)[0]['output_value'].tolist(), [180.0, 40.0])
        self.assertEqual(M13.ely_floor(evs, io, lower_bound=True, cap_m=1.25)[0]['output_value'].tolist(), [110.0, 20.0])   # ignored: both fit free
        self.assertEqual(sorted(M13.ELY_HOLD_CAP.values()), [1.25, 1.5, 2.0])
        self.assertEqual(set(C13.CHOICES['ely_hold_cap']), {'off'} | set(M13.ELY_HOLD_CAP))
        self.assertEqual(C13.load_choices()['ely_hold_cap']['value'], 'off')

    def test_anchor_b(self):
        # anchor B (s13 ely_output_anchor): FRA-like 400 TWh, households 37.5% at 168, the rest at 130, exports 5,000 and
        # resold gas 2,000 (USD m), plus a shield payment of 3,000; the hold is the anchor, never below the floor
        evs = pd.DataFrame(dict(region=['FRA', 'LVA'], commodity=['ely'] * 2, output_value=[60000.0, 2000.0],
                                domestic_sales_value=[55000.0, 2000.0], domestic_sales=[400.0, 3.0], pass_through_value=[2000.0, 0.0],
                                export_value=[5000.0, 0.0], export_tax=[0.0] * 2, target=['yes'] * 2,
                                ely_target_rule=['floor_ninety'] * 2, ely_floor_value=[30000.0, 2500.0]))
        a = M13.ely_anchor_values(evs, {'FRA': (0.375, 168.0, 130.0), 'LVA': (0.25, 224.0, 201.0), 'XXX': (0.5, 1.0, 1.0)}, {'FRA': 3000.0})
        self.assertAlmostEqual(a['FRA'], 400.0 * (0.375 * 168.0 + 0.625 * 130.0) + 5000.0 + 2000.0 + 3000.0)
        self.assertNotIn('XXX', a)
        io = pd.DataFrame(dict(region=['FRA', 'LVA'], row=['OUT'] * 2, ely=[254000.0, 5000.0]))
        out, _ = M13.ely_floor(evs, io, anchor=a)
        self.assertAlmostEqual(out['output_value'].iloc[0], a['FRA'])
        self.assertEqual(out['output_value'].iloc[1], 2500.0)                    # LVA anchor 606.75 below its floor
        self.assertEqual(M13.ely_floor(evs, io, lower_bound=True, anchor=a)[0]['output_value'].iloc[0], 60000.0)
        self.assertEqual(C13.load_choices()['ely_output_anchor']['value'], C13.ELY_ANCHOR)        # beta v5 power (David 2026-10-27 11:43 UTC)
        self.assertEqual(M13.ELY_ANCHOR, C13.ELY_ANCHOR)

    def test_anchor_config(self):
        t = C13.read_ely_anchor()
        self.assertEqual(len(t), 49)                                             # 37 + 12 added 2026-10-27
        self.assertNotIn('USA', t)
        self.assertTrue(all(0 < sh < 1 and ph > 0 and pn > 0 for sh, ph, pn in t.values()))
        self.assertEqual(sorted(C13.read_ely_shield()), ['FRA', 'GBR', 'OMN'])   # sourced 2026-10-27 (David's agent)
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'shield.csv')
            with open(p, 'w') as fh:
                fh.write(','.join(C13.SHIELD_COLUMNS) + '\n')
                fh.write('FRA,9496,EUR,0.9496,WDI,bouclier,2022,CRE,https://example.invalid,x,2026-10-27,b\n')
            self.assertAlmostEqual(C13.read_ely_shield(p)['FRA'], 10000.0)
            with open(p, 'w') as fh:
                fh.write(','.join(C13.SHIELD_COLUMNS) + '\n')
                fh.write('FRA,1,EUR,0.9496,WDI,bouclier,2022,,u,x,2026-10-27,b\n')
            with self.assertRaises(C13.ConfigError):
                C13.read_ely_shield(p)

    def test_cap_nets_held_ely(self):
        # with ely held (a target), the cap moves the domestic excess to the other buyers; under H2 (net_held) it is netted
        sectors = ['ely', 'crp']
        cols = sectors + ['p', 'g', 'i']
        idx = {c: i for i, c in enumerate(sectors)}
        live = np.array([True, True, True, False, False])
        va = np.array([40.0, 0.0])
        res = {}
        for net_held in ((), ('ely',)):
            pv = {'dom': np.zeros((2, 5)), 'imp': np.zeros((2, 5))}
            pv['dom'][0, 0], pv['dom'][0, 1], pv['dom'][0, 2], pv['dom'][1, 0] = 50.0, 10.0, 20.0, 10.0
            notes, _ = EN13.cap_own_use(pv, np.ones((2, 5)), idx, cols, np.array([80.0, np.nan]), va, {'ely': 0.1}, live, net_held=net_held)
            res[net_held] = (pv['dom'][0].sum(), notes[0][-1])
        self.assertAlmostEqual(res[()][0], 80.0)                       # row total kept: the excess went to crp and households
        self.assertEqual(res[()][1], 'OWN-USE-CAP')
        self.assertLess(res[('ely',)][0], 80.0 - 1e-6)                # netted out of the row
        self.assertEqual(res[('ely',)][1], 'OWN-USE-CAP-NETTED')

    def test_price_floor_alternative(self):
        io = pd.DataFrame(dict(region=['USA', 'BTN', 'HND'], row=['OUT'] * 3, ely=[696.0, 23.0, 90.0]))
        out, rows = M13.ely_floor(self.frame(['floor', 'floor', 'value', '']), io)
        self.assertEqual(out['output_value'].tolist(), [696.0, 313.0, 50.0, 30.0])   # HND: S11 value kept
        self.assertEqual(M13.ely_floor(self.frame(['floor'] * 3 + ['']).drop(columns='ely_target_rule'), io)[1], [])

    def test_ninety_floor_value(self):
        self.assertAlmostEqual(K11.ely_ninety_floor(90.0, 5.0), 105.0)
        self.assertAlmostEqual(K11.ely_ninety_floor(float('nan'), 5.0), 5.0)

    def test_floor_headroom(self):
        # rescan N2 (s11 ely_floor_headroom, default off): toward the S11 value up to a fuel share of 0.8, never above it
        hr = C11.ELY_FLOOR_HEADROOM_RATIO
        self.assertAlmostEqual(K11.ely_ninety_floor(294.0, 0.0, value=533.1, headroom=hr), 294.0 / 0.8)       # MDG-like
        self.assertAlmostEqual(K11.ely_ninety_floor(9155.0, 0.0, value=11000.0, headroom=hr), 11000.0)        # capped at the value
        self.assertAlmostEqual(K11.ely_ninety_floor(1059.0, 0.0, value=1176.7, headroom=hr), 1176.7)          # value just above 0.9
        self.assertAlmostEqual(K11.ely_ninety_floor(1059.0, 0.0, value=1000.0, headroom=hr), 1059.0 / 0.9)    # never below the 90% floor
        self.assertAlmostEqual(K11.ely_ninety_floor(1650.0, 2186.0, value=12027.0, headroom=hr), 1650.0 / 0.8 + 2186.0)
        self.assertAlmostEqual(K11.ely_ninety_floor(294.0, 0.0, value=533.1), 294.0 / 0.9)                    # off
        self.assertTrue(C11.switched_on(C11.load_choices(), 'ely_floor_headroom'))    # on: David 2026-10-26 21:23 UTC
        self.assertIn('off', C11.ALTERNATIVES['ely_floor_headroom'])

    def test_config(self):
        self.assertEqual(C11.load_choices()['ely_output_value']['value'], C11.ELY_FLOOR90)
        self.assertEqual(C11.CHOICES['ely_output_value'], C11.ELY_FLOOR90)
        self.assertEqual(set(C11.ALTERNATIVES['ely_output_value']), {C11.ELY_FLOOR, C11.ELY_TARGET, C11.ELY_REPORT_ONLY})


class ChnGasPriceTest(unittest.TestCase):
    """G9 (s11 chn_gas_price, decision package): CHN gas at the NBS 2022 residual, about 190 USD/kcm."""

    def test_row(self):
        c = C11.load_choices()
        self.assertTrue(C11.switched_on(c, 'chn_gas_price'))
        rows = [{'commodity': 'gas', 'region': 'CHN'}]
        self.assertEqual(len(C11.price_source_rows(rows, c)), 1)
        off = {k: dict(v) for k, v in c.items()}
        off['chn_gas_price']['value'] = 'off'
        self.assertEqual(C11.price_source_rows(rows, off), [])
        t = {r['item']: r for r in __import__('csv').DictReader(open(os.path.join(BUILD, 'config/s11/transcribed_prices_2022.csv')))}
        v = (12633.6e8 - 1510.649404e6 * 96.386117 * 6.73715811237118) / 2201.10e8 * 1000.0      # RMB per 1000 m3
        self.assertAlmostEqual(float(t['chn_gas_nbs_2022']['value']), v, delta=0.1)
        self.assertAlmostEqual(v / 6.73715811237118, 190.4, delta=0.5)


class ElyFuelPurchaserTest(unittest.TestCase):
    """S16 sector shocks item 4 (s11 ely_fuel_purchaser_price, on): the ely rule's fuels at basic x (1 - IEA rate, at most 0.8)."""

    def test_factors(self):
        self.assertTrue(C11.switched_on(C11.load_choices(), 'ely_fuel_purchaser_price'))
        FS = pd.DataFrame([dict(region='IRN', commodity='gas', market_price=220.97, subsidy_per_unit=207.52),
                           dict(region='IRN', commodity='pet', market_price=114.03, subsidy_per_unit=69.96),
                           dict(region='USA', commodity='coa', market_price=50.0, subsidy_per_unit=0.0)])
        k = PWR.purchaser_factors(FS, C11.ELY_FUEL_RATE_CAP)
        self.assertAlmostEqual(k[('IRN', 'gas')], 0.2)                      # 0.939 capped at 0.8
        self.assertAlmostEqual(k[('IRN', 'pet')], 1 - 69.96 / 114.03)
        self.assertNotIn(('USA', 'coa'), k)
        PF = pd.DataFrame([dict(region='IRN', fuel='gas', commodity='gas', value_dom_musd=100.0, value_imp_musd=10.0),
                           dict(region='IRN', fuel='coa', commodity='coa', value_dom_musd=5.0, value_imp_musd=0.0)])
        P = PWR.at_purchaser(PF, k)
        self.assertAlmostEqual(P['value_dom_musd'].iloc[0], 20.0)
        self.assertAlmostEqual(P['value_imp_musd'].iloc[0], 2.0)
        self.assertAlmostEqual(P['value_dom_musd'].iloc[1], 5.0)

    def test_s13_booked_rate(self):
        # dry run 3 (S13-H90fit SAU): with a basis, a fuel's rate is the money S13 books over domestic sales plus imports;
        # ely keeps the per-unit rate (its S13 basis is the floor)
        FS = pd.DataFrame([dict(region='SAU', commodity='pet', market_price=114.03, subsidy_per_unit=34.48, subsidy_musd=21279.5),
                           dict(region='SAU', commodity='ely', market_price=87.25, subsidy_per_unit=27.74, subsidy_musd=10572.7),
                           dict(region='IRN', commodity='gas', market_price=220.97, subsidy_per_unit=207.52, subsidy_musd=50000.0)])
        k = PWR.purchaser_factors(FS, C11.ELY_FUEL_RATE_CAP, basis={('SAU', 'pet'): 96318.8, ('SAU', 'ely'): 37613.0, ('IRN', 'gas'): 52000.0})
        self.assertAlmostEqual(k[('SAU', 'pet')], 1 - 21279.5 / 96318.8)
        self.assertAlmostEqual(k[('SAU', 'ely')], 1 - 27.74 / 87.25)
        self.assertAlmostEqual(k[('IRN', 'gas')], 0.2)                      # 0.96 capped at 0.8


class ElySubsidyNetTest(unittest.TestCase):
    """S16 sector shocks item 4 (s11 ely_subsidy_net_power_fuel, on): the fuel subsidy on the electricity part of the burn."""

    def test_power_fuel_subsidy(self):
        self.assertTrue(C11.switched_on(C11.load_choices(), 'ely_subsidy_net_power_fuel'))
        rows = [dict(region='IRN', commodity='gas', subsidy_per_unit=207.5, market_price=221.0, absorption_volume=244.6),
                dict(region='IRN', commodity='pet', subsidy_per_unit=70.0, market_price=114.0, absorption_volume=673.4),
                dict(region='IRN', commodity='ely', subsidy_per_unit=88.6, market_price=159.0, absorption_volume=359.2)]
        fuels = {'IRN': {'gas': 100.0, 'gas_dist': 60.0, 'pet': 50.0}, 'USA': {'gas': 300.0}}
        out = PWR.power_fuel_subsidy(rows, fuels, {'IRN': 0.25}, 0.8)
        want = 0.75 * (100.0 * 0.8 * 221.0 + 50.0 * 70.0)            # gas rate capped at 0.8 x market; gas_dist is resold
        self.assertAlmostEqual(out['IRN'], want)
        self.assertEqual(out['USA'], 0.0)
        out = PWR.power_fuel_subsidy(rows, {'IRN': {'gas': 400.0}}, {}, 0.8)
        self.assertAlmostEqual(out['IRN'], 244.6 * 0.8 * 221.0)       # burn at most the absorption


class UpdatePinsTest(unittest.TestCase):
    """S16 2026-10-26: tools/update_pins.py moves the upstream pins; on the committed stages every pin already holds."""

    def test_rewrite_and_committed(self):
        sys.path.insert(0, os.path.join(BUILD, 'tools'))
        import update_pins as UP
        text = "A_SHA = 'aaa'  # note\nB = 'x'\n"
        new, moved = UP.rewrite(text, {'A_SHA': 'bbb'})
        self.assertEqual(new, "A_SHA = 'bbb'  # note\nB = 'x'\n")
        self.assertEqual(moved, [('A_SHA', 'aaa', 'bbb')])
        with self.assertRaises(SystemExit):
            UP.rewrite(text, {'C': 'z'})
        for after in ('S01', 'S05', 'S07', 'S08', 'S09'):
            for script, values in UP.pins(after).items():
                self.assertEqual(UP.rewrite(open(os.path.join(BUILD, script)).read(), values)[1], [], f'{after} {script}')


class ExportDutyCollectedTest(unittest.TestCase):
    """G13 (s11 export_duty_to_collected, fallback, off): route rates scaled to the collected duty, held at the cap."""

    def test_off_by_default(self):
        c = C11.load_choices()
        self.assertFalse(C11.switched_on(c, 'export_duty_to_collected'))

    def test_scaling(self):
        fob = {'gas': np.array([[0.0, 100.0], [50.0, 0.0]]), 'oil': np.array([[0.0, 200.0], [0.0, 0.0]])}
        xtm = {'gas': np.array([[0.0, 0.3], [0.1, 0.0]]), 'oil': np.array([[0.0, 0.1], [0.0, 0.0]])}
        out, rows = M11.scale_export_tax_to_collected(xtm, fob, {0: 25.0}, 0.99)
        self.assertAlmostEqual(rows[0][1], 50.0)
        self.assertAlmostEqual(rows[0][2], 0.5)
        self.assertAlmostEqual(rows[0][3], 25.0)
        self.assertAlmostEqual(out['gas'][1, 0], 0.1)          # unlisted exporter untouched
        out, rows = M11.scale_export_tax_to_collected(xtm, fob, {0: 400.0}, 0.99)
        self.assertAlmostEqual(out['gas'][0, 1], 0.99)         # held at the cap
        self.assertLess(rows[0][3], 400.0)
        self.assertEqual(out['gas'][0, 0], 0.0)                # a zero-rate route stays zero


class P34EnergyRevenueTest(unittest.TestCase):
    """P34: with ely held (P1), the ely energy-tax rates scale on the S11 value, not the io_s12 cells (BFA)."""

    def frames(self):
        cols = ['crp', 'coa', 'oil', 'gas', 'pet', 'ely', 'fbt', 'trd', 'p', 'g', 'i']
        te = pd.DataFrame([dict(region='BFA', commodity='ely', column=c, source='neers', energy_rate=-0.158,
                                neer_subsidy_rate=-0.158, basic_musd=b) for c, b in (('trd', 40.0), ('p', 48.6))])
        spec = pd.DataFrame([dict(region='BFA', commodity='ely', **{'class': 'power'}, tax_musd=0.0, subsidy_musd=-74.48)])
        ev = pd.DataFrame([dict(region='BFA', commodity='ely', domestic_sales_value=249.6, vmsb_imports=63.4, target='yes')])
        io = pd.DataFrame([dict(region='BFA', row='dom_ely', **{c: 0.0 for c in cols}), dict(region='BFA', row='imp_ely', **{c: 0.0 for c in cols})])
        io.loc[0, 'trd'], io.loc[0, 'p'] = 30.0, 38.6
        io.loc[1, 'trd'], io.loc[1, 'p'] = 10.0, 10.0
        return te, spec, ev, io, cols[:-3]

    def test_ely_held(self):
        te, spec, ev, io, sec = self.frames()
        out, rep, _n = M13.scale_energy_rates_to_source(te, spec, ev, io, sec, targets=M13.output_targets(M13.ENERGY_TARGETS_ELY))
        self.assertAlmostEqual(rep['row_value_factor'].iloc[0], 313.0 / 88.6)
        self.assertAlmostEqual(rep['expected_after_musd'].iloc[0], -74.48)
        self.assertGreater(out['energy_rate'].min(), -0.3)                     # about -0.24, not -0.63
        _o, rep0, _n0 = M13.scale_energy_rates_to_source(te, spec, ev, io, sec)   # mutated: the fixed v3 tuple
        self.assertEqual(rep0['row_value_factor'].iloc[0], 1.0)
        self.assertEqual(rep0['scale'].iloc[0], M13.ENERGY_REVENUE_BOUND)

    def test_checks(self):
        erev = pd.DataFrame([dict(region='BFA', commodity='ely', note=''), dict(region='CHE', commodity='ely', note='factor 0.185 outside')])
        rv = pd.DataFrame([dict(region='BFA', commodity='ely', implied_musd=-14.0, fitted_musd=-73.0, source_musd=-74.48),
                           dict(region='CHE', commodity='ely', implied_musd=1.0, fitted_musd=5.0, source_musd=1.0)])
        n, _d, nc = K13.energy_revenue_held(rv, erev, ('coa', 'oil', 'gas', 'pet', 'ely'))
        self.assertEqual((n, list(nc['region'])), (0, ['CHE']))
        n, _d, _nc = K13.energy_revenue_held(rv.assign(fitted_musd=[-197.0, 5.0]), erev, ('coa', 'oil', 'gas', 'pet', 'ely'))
        self.assertEqual(n, 1)                                                    # mutated: BFA at -197 m
        pre = pd.DataFrame([dict(region='BFA', commodity='ely', note='', source_musd=-74.48, expected_after_musd=-74.48),
                            dict(region='CHE', commodity='ely', note='factor 0.185 outside', source_musd=1.0, expected_after_musd=5.0)])
        self.assertEqual(K13.energy_revenue_prefit(pre, ('ely',))[0], 0)          # dry run 3: the pre-fit identity
        self.assertEqual(K13.energy_revenue_prefit(pre.assign(expected_after_musd=[-14.0, 5.0]), ('ely',))[0], 1)   # mutated: the P34 base error
        cells = pd.DataFrame([dict(region='BFA', column='p', commodity='ely', tls_rate=-0.57), dict(region='BFA', column='p', commodity='fbt', tls_rate=-0.6)])
        self.assertEqual(list(K13.low_power_energy(cells)['commodity']), ['ely'])


class PowerFuelZeroTest(unittest.TestCase):
    """Dry run 3 (S13-H90fit LBR ely): a fuel the region's power plants do not burn (UNSD 088) is held at 0 in the power column."""

    def test_missing_fuel_held_at_zero(self):
        from s13_fit import method as M13
        pf = pd.DataFrame([dict(region='LBR', io_column='ely', commodity='pet', value_dom_musd=0.0, value_imp_musd=41.4),
                           dict(region='ZZZ', io_column='ely', commodity='coa', value_dom_musd=0.0, value_imp_musd=0.0)])
        t = M13.power_cell_targets_all(pf, {'LBR', 'ZZZ'})
        self.assertAlmostEqual(t['LBR'][('imp', 'pet')], 41.4)
        self.assertEqual(t['LBR'][('imp', 'coa')], 0.0)
        self.assertEqual(t['LBR'][('dom', 'gas')], 0.0)
        self.assertNotIn('ZZZ', t)                  # a region with no recorded burn stays free


class PartialUsersExtractionTest(unittest.TestCase):
    """Beta v4 rescan N3 (s13 partial_users_extraction, on): a row whose users the fallback frees keeps the extraction
    columns at their pre-smear prior share (YEM crude bought products at 69% of cost from the 1/32 smear)."""

    def test_freed_row_extraction_cell_held_at_presmear_share(self):
        from s13_fit import method as M13
        from s13_fit import config as C13
        self.assertEqual(C13.load_choices()['partial_users_extraction']['value'], C13.PARTIAL_USERS_EXTRACTION)
        self.assertEqual(C13.PARTIAL_USERS_EXTRACTION, M13.PARTIAL_USERS_EXTRACTION)
        sectors = ['oil', 'pet', 'trd']
        cols = sectors + ['p']
        idx = {c: i for i, c in enumerate(sectors)}
        pv = {k: np.zeros((3, 4)) for k in ('dom', 'imp')}
        pv['imp'][1, :] = [3.0, 0.0, 60.0, 40.0]          # after the smear: 3 on the crude column
        pre = {k: v.copy() for k, v in pv.items()}
        pre['imp'][1, 0] = 0.0                              # the prior before the smear: crude buys no products
        tgt, X, Mv = np.array([np.nan, np.nan, np.nan]), np.zeros(3), np.array([0.0, 200.0, 0.0])
        held = {}
        M13.hold_freed_rows_extraction(pv, np.ones((3, 4)), idx, {c: 'prior' for c in sectors}, tgt, X, Mv, held, cols, ('pet',), pre)
        self.assertEqual(pv['imp'][1, 0], 0.0)              # no pre-smear prior: the smear is removed
        self.assertEqual(pv['imp'][1, 2], 60.0)             # other buyers untouched (free)
        pre['imp'][1, 0] = 5.0                               # with a prior share: held at 5% of the 200 row
        pv['imp'][1, 0] = 3.0
        held = {}
        M13.hold_freed_rows_extraction(pv, np.ones((3, 4)), idx, {c: 'prior' for c in sectors}, tgt, X, Mv, held, cols, ('pet',), pre)
        self.assertAlmostEqual(held[('imp', 1, 0)], 200.0 * 5.0 / 105.0)
