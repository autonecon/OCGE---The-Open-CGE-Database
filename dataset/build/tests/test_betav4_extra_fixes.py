"""Unit tests for the beta v4 extra fixes (G4, G10, G14, G15, P39, P41; 26 Oct).

Every helper and check is called on a good input (it must pass or give the hand-computed value) and on a mutated input
(it must fail or move). No stage is run.

Run from dataset/build:  python3 -m unittest tests.test_betav4_extra_fixes -v
"""
import os
import sys
import unittest

import numpy as np

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BUILD)

import json  # noqa: E402

import s03_household_employers as HHE  # noqa: E402
import s07_trade as T07  # noqa: E402
from s11_energy import config as C11  # noqa: E402
from s11_energy import domestic as DOM11  # noqa: E402
from s11_energy import method as M11  # noqa: E402
from s12_factors import config as C12  # noqa: E402
from s13_fit import config as C13  # noqa: E402
from s13_fit import ptax_source as PS13  # noqa: E402

DATA = os.path.join(os.path.dirname(BUILD), 'data')


def toy_icio():
    """One economy E with industries O, P, Q, T; final demand HFCE, GGFC; rows end TLS, VA, OUT; last column OUT."""
    rows = ['E_O', 'E_P', 'E_Q', 'E_T', 'TLS', 'VA', 'OUT']
    cols = ['E_O', 'E_P', 'E_Q', 'E_T', 'E_HFCE', 'E_GGFC', 'OUT']
    A = np.zeros((len(rows), len(cols)))
    A[0, 0], A[0, 4], A[0, 5] = 2.0, 1.0, 7.0          # O sells 10
    A[1, 1], A[1, 5] = 1.0, 9.0                        # P sells 10
    A[2, 4], A[2, 5] = 4.0, 6.0                        # Q sells 10
    A[3, 4] = 50.0                                     # T sells 50 to households
    A[5, :4] = [8.0, 9.0, 10.0, 50.0]                  # VA
    A[4, 0] = 0.0
    A[6, :4] = [10.0, 10.0, 10.0, 50.0]
    A[:4, 6] = [10.0, 10.0, 10.0, 50.0]
    return A, rows, cols


class HouseholdEmployersTest(unittest.TestCase):
    """G4: T's VA at the sourced value, the rest to O, P, Q by D1; HFCE -> GGFC; balance kept."""

    def test_reallocate(self):
        A, rows, cols = toy_icio()
        info = HHE.reallocate(A, rows, cols, 'E', 2.0, {'O': 2.0, 'P': 1.0, 'Q': 1.0})
        self.assertAlmostEqual(info['moved'], 48.0)
        self.assertAlmostEqual(A[5, 3], 2.0)                       # T VA
        self.assertAlmostEqual(A[6, 3], 2.0)                       # T output (OUT row)
        self.assertAlmostEqual(A[3, 6], 2.0)                       # T output (OUT column)
        self.assertAlmostEqual(A[3, 4], 2.0)                       # households keep 2 of T
        self.assertAlmostEqual(A[0, 5] - 7.0, 24.0)                # O gets half
        self.assertAlmostEqual(A[5, 1] - 9.0, 12.0)
        for i in range(4):                                         # sales = output = costs (intermediate + VA)
            self.assertAlmostEqual(A[i, :6].sum(), A[i, 6])
            self.assertAlmostEqual(A[:4, i].sum() + A[4, i] + A[5, i], A[6, i])
        self.assertAlmostEqual(A[:4, 4].sum() + A[:4, 5].sum(), 55.0 + 22.0)   # final demand total unchanged

    def test_no_move_and_mutations(self):
        A, rows, cols = toy_icio()
        info = HHE.reallocate(A, rows, cols, 'E', 60.0, {'O': 1.0})
        self.assertEqual(info['moved'], 0.0)                       # target above T's VA: nothing moves
        A, rows, cols = toy_icio()
        A[3, 4] = 10.0                                             # mutation: households buy too little T
        with self.assertRaises(SystemExit):
            HHE.reallocate(A, rows, cols, 'E', 2.0, {'O': 1.0})
        A, rows, cols = toy_icio()
        with self.assertRaises(SystemExit):
            HHE.reallocate(A, rows, cols, 'E', 2.0, {'O': 0.0})

    def test_hfce_to_pq(self):
        A, rows, cols = toy_icio()
        rec = HHE.recipients_for(HHE.HFCE_TO_PQ, ['O', 'P', 'Q'])
        self.assertEqual(rec, ['P', 'Q'])
        info = HHE.reallocate(A, rows, cols, 'E', 2.0, {'P': 1.0, 'Q': 3.0}, to='HFCE')
        self.assertAlmostEqual(info['moved'], 48.0)
        self.assertEqual(info['cg_before'], info['cg_after'])            # C and G totals kept
        self.assertAlmostEqual(A[1, 4], 12.0)                            # households buy P's part
        self.assertAlmostEqual(A[2, 4] - 4.0, 36.0)
        self.assertAlmostEqual(A[1, 5], 9.0)                             # government unchanged
        for i in range(4):
            self.assertAlmostEqual(A[i, :6].sum(), A[i, 6])
            self.assertAlmostEqual(A[:4, i].sum() + A[4, i] + A[5, i], A[6, i])
        A, rows, cols = toy_icio()
        info = HHE.reallocate(A, rows, cols, 'E', 2.0, {'O': 1.0}, to='GGFC')    # the first version moves C to G
        self.assertAlmostEqual(info['cg_before'][1] + 48.0, info['cg_after'][1])
        with self.assertRaises(SystemExit):
            HHE.recipients_for(HHE.HFCE_TO_PQ, ['O'])

    def test_config_and_target(self):
        cfg = os.path.join(BUILD, 'config/s03')
        self.assertEqual(HHE.load_choice(os.path.join(cfg, 's03_choices.csv')), HHE.HFCE_BY_COICOP)   # beta v5 H
        rows = HHE.load_rows(os.path.join(cfg, 'household_employers_2022.csv'))
        self.assertEqual([r['economy'] for r in rows], ['ZAF'])
        fx = HHE.wdi_rate(os.path.join(DATA, 'wdi/wdi_2017_2022_extract.csv'), 'ZAF')
        t = HHE.target_musd(rows[0], fx)
        self.assertAlmostEqual(t, 839e3 * 2350 * 12 / fx / 1e6)
        self.assertTrue(1440 < t < 1450, t)                        # R23.66 bn at 16.356 ZAR per USD
        w = HHE.figaro_d1(os.path.join(DATA, 'figaro_va/figaro_va_2022.json'), 'ZA', ['O', 'P', 'Q'])
        self.assertAlmostEqual(w['O'], 24043.398, places=2)
        self.assertAlmostEqual(w['Q'], 11402.78 + 522.621, places=2)
        with self.assertRaises(SystemExit):
            HHE.figaro_d1(os.path.join(DATA, 'figaro_va/figaro_va_2022.json'), 'ZA', ['R'])

    def test_hhe_labour_share_choice(self):
        c = C12.load_choices()
        self.assertEqual(c['hhe_labour_share']['value'], C12.HHE_ALL_LABOUR)


class ElyClassPriceTest(unittest.TestCase):
    """G10: only the used rows price their region; the others keep the class fill."""

    def row(self, r, v, u, used, measure='end_user_billed_tariff'):
        return dict(region=r, value=v, unit=u, fx_iso3=r, measure=measure, used=used, source='src')

    def test_conversion_and_used(self):
        tab = [self.row('BRA', '577.14', 'LCU/MWh', 'yes'), self.row('COL', '269.51', 'LCU/kWh', 'no', 'wholesale_contract'),
               self.row('OMN', '20.4', 'LCU/MWh', 'yes', 'revenue_per_mwh'), self.row('PNG', '', '', 'no', 'none')]
        out, pend = DOM11.ely_class_prices(tab, {'BRA': 5.16397, 'OMN': 0.3845, 'COL': 4256.19})
        self.assertEqual(sorted(out), ['BRA', 'OMN'])
        self.assertEqual(pend, ['COL', 'PNG'])
        self.assertAlmostEqual(out['BRA'][0], 577.14 / 5.16397)
        self.assertAlmostEqual(out['OMN'][0], 20.4 / 0.3845)
        self.assertTrue(110 < out['BRA'][0] < 113 and 52 < out['OMN'][0] < 54)

    def test_mutations(self):
        with self.assertRaises(SystemExit):                       # used with no value
            DOM11.ely_class_prices([self.row('PNG', '', '', 'yes')], {})
        with self.assertRaises(SystemExit):                       # used must be yes or no
            DOM11.ely_class_prices([self.row('BRA', '1', 'USD/MWh', 'maybe')], {})
        with self.assertRaises(SystemExit):                       # no exchange rate
            DOM11.ely_class_prices([self.row('BRA', '1', 'LCU/MWh', 'yes')], {})
        with self.assertRaises(SystemExit):                       # duplicate
            DOM11.ely_class_prices([self.row('BRA', '1', 'USD/MWh', 'yes')] * 2, {})

    def test_config(self):
        tab = C11.read_table('ely_industrial_prices_2022.csv', C11.ELY_CLASS_COLUMNS)
        used = sorted(t['region'] for t in tab if t['used'] == 'yes')
        self.assertEqual(used, ['BRA', 'OMN'])
        self.assertEqual(sorted(t['region'] for t in tab),
                         ['AUS', 'BRA', 'CAN', 'CMR', 'COG', 'COL', 'MNG', 'MOZ', 'OMN', 'PNG', 'XEF'])
        self.assertEqual(C11.load_choices()['ely_class_price']['value'], C11.ELY_CLASS_SOURCED)


class GasReporterFobTest(unittest.TestCase):
    """P41: TTO's gas reference price from its own Comtrade FOB report."""

    def test_toy(self):
        ct = {'271111': [dict(reporterCode=780, partnerCode=0, flowCode='X', fobvalue=1.36e9, netWgt=1e9),
                         dict(reporterCode=780, partnerCode=76, flowCode='X', fobvalue=9e9, netWgt=1e9),
                         dict(reporterCode=12, partnerCode=0, flowCode='X', fobvalue=9e9, netWgt=1e9)]}
        out = M11.reporter_fob_gas_prices([dict(region='TTO', reporter_code='780', hs_lines='271111;271121')], ct, 1.36)
        self.assertAlmostEqual(out['TTO']['price'], 1000.0)       # 1,360 USD m on 1.36 bcm
        with self.assertRaises(SystemExit):                       # mutation: no record for the reporter
            M11.reporter_fob_gas_prices([dict(region='TTO', reporter_code='781', hs_lines='271111')], ct, 1.36)

    def test_real_file(self):
        d = json.load(open(os.path.join(DATA, 'un_comtrade_rx_2022/comtrade_X_271111_2022.json')))['data']
        rows = C11.read_table('gas_export_price_reporter.csv', ('region', 'reporter_code', 'hs_lines', 'decided_by', 'decided_at', 'basis'))
        out = M11.reporter_fob_gas_prices(rows, {'271111': d, '271121': []}, 1.36)
        self.assertEqual(list(out), ['TTO'])
        self.assertTrue(650 < out['TTO']['price'] < 670, out['TTO'])
        self.assertAlmostEqual(out['TTO']['value_musd'], 1116.8, places=0)
        self.assertEqual(C11.load_choices()['gas_reporter_fob']['value'], C11.GAS_REPORTER_FOB)


class GoldReexportTest(unittest.TestCase):
    """P39: exports above imports plus mine output move to the origin, by destination and HS line."""

    def con(self):
        import duckdb
        c = duckdb.connect()
        c.execute('CREATE TABLE flows (exporter VARCHAR, importer VARCHAR, hs6 VARCHAR, value DOUBLE, qty DOUBLE, qty_ok BOOLEAN)')
        c.executemany('INSERT INTO flows VALUES (?, ?, ?, ?, ?, TRUE)', [
            ('U', 'A', '710812', 600.0, 6.0), ('U', 'B', '710812', 400.0, 4.0), ('U', 'C', '710812', 50.0, 0.5),   # C is the origin
            ('Z', 'U', '710812', 100.0, 1.0), ('C', 'A', '710812', 10.0, 0.1), ('U', 'A', '090111', 70.0, 7.0)])
        return c

    def test_move(self):
        c = self.con()
        out = T07.gold_reexport(c, [('U', '7108', 2.0, 'C')], 50.0)          # mine 2 kg x 50 USD = 0.1 kUSD
        g = out[0]
        self.assertAlmostEqual(g['exports'], 1050.0)
        self.assertAlmostEqual(g['moved'], 1050.0 - 100.0 - 0.1)
        v = dict(((e, i), x) for e, i, x in c.execute("SELECT exporter, importer, SUM(value) FROM flows WHERE hs6 LIKE '7108%' GROUP BY 1, 2").fetchall())
        self.assertAlmostEqual(v[('U', 'C')], 50.0)                          # exports to the origin stay
        self.assertAlmostEqual(v[('U', 'A')] + v[('U', 'B')] + 50.0, 100.1)  # U keeps imports + mine
        self.assertAlmostEqual(v[('U', 'A')] / v[('U', 'B')], 1.5)           # one proportion
        self.assertAlmostEqual(v[('C', 'A')] - 10.0 + v[('C', 'B')], 949.9)  # origin gains the moved value
        total = c.execute('SELECT SUM(value) FROM flows').fetchone()[0]
        self.assertAlmostEqual(total, 600 + 400 + 50 + 100 + 10 + 70)       # world trade unchanged
        self.assertAlmostEqual(c.execute("SELECT value FROM flows WHERE hs6 = '090111'").fetchone()[0], 70.0)

    def test_no_move(self):
        c = self.con()
        out = T07.gold_reexport(c, [('U', '7108', 1e6, 'C')], 50.0)          # mine output above exports
        self.assertEqual(out[0]['moved'], 0.0)
        self.assertAlmostEqual(c.execute("SELECT value FROM flows WHERE exporter = 'U' AND importer = 'A' AND hs6 = '710812'").fetchone()[0], 600.0)

    def test_config_and_price(self):
        rows = T07.read_gold_rows(os.path.join(BUILD, 'config/s07/gold_reexport_2022.csv'), {'UGA', 'COD'})
        self.assertEqual(rows, [('UGA', '7108', 3200.0, 'COD')])
        with self.assertRaises(SystemExit):
            T07.read_gold_rows(os.path.join(BUILD, 'config/s07/gold_reexport_2022.csv'), {'UGA'})
        p = T07.gold_price_2022(os.path.join(DATA, T07.GOLD_PRICE_SHEET))
        self.assertAlmostEqual(p, 1800.6025, places=3)
        self.assertTrue(180 < 3200 * p / T07.TROY_OZ_KG / 1e6 < 190)


class ExciseCapTest(unittest.TestCase):
    """G15: the energy excise scaled to G114 where above it; untouched below it or with the cap off."""

    def toy(self):
        general = np.array([[0.1, 0.1], [0.0, 0.0]])
        cell = general + np.array([[0.0, 0.0], [0.5, 1.0]])          # row 1 carries the energy excise
        b12 = np.array([[100.0, 100.0], [100.0, 100.0]])              # E = 50 + 100 = 150, general 20
        return cell, general, b12, (cell * b12).sum(axis=0)

    def test_cap(self):
        cell, general, b12, tls = self.toy()
        c2, g2, t2, info = PS13.scale_general_to_total(cell, general, b12, tls, 60.0, cap_excise=True)
        self.assertAlmostEqual(info['excise_cap_factor'], 0.4)
        self.assertAlmostEqual(info['energy_excise_musd'], 60.0)
        self.assertAlmostEqual(float((g2 * b12).sum()), 0.0)          # general product tax 0
        self.assertAlmostEqual(float((c2 * b12).sum()), 60.0)         # total = G114
        np.testing.assert_allclose(t2, (c2 * b12).sum(axis=0))        # tls moves with the money

    def test_off_and_below(self):
        cell, general, b12, tls = self.toy()
        _, _, _, info = PS13.scale_general_to_total(cell, general, b12, tls, 60.0, cap_excise=False)
        self.assertEqual(info['excise_cap_factor'], 1.0)
        self.assertAlmostEqual(info['energy_excise_musd'], 150.0)     # mutation check: off leaves the excise above G114
        c2, g2, _, info = PS13.scale_general_to_total(cell, general, b12, tls, 200.0, cap_excise=True)
        self.assertEqual(info['excise_cap_factor'], 1.0)
        self.assertAlmostEqual(float((g2 * b12).sum()), 50.0)

    def test_choice(self):
        self.assertEqual(C13.load_choices()['excise_cap_g114']['value'], PS13.EXCISE_CAP_G114)


class VatFinalDemandG14Test(unittest.TestCase):
    """G14: the new VAT rows, their excise part and the final-demand rate maximum."""

    def test_rows(self):
        v = PS13.read_vat_regions(os.path.join(BUILD, 'config/s13/vat_final_demand_2022.csv'))
        self.assertEqual({r for r, x in v.items() if x['excise_part'] == PS13.EXCISE_LESS_ENERGY}, {'NAM', 'SWZ', 'CPV', 'ALB', 'MKD', 'SRB'})
        self.assertEqual({r for r, x in v.items() if x['excise_part'] == 'g1142'}, {'SAU', 'ARE', 'OMN', 'BHR'})
        self.assertEqual(float(v['NAM']['statutory_rate_pct']), 15.0)

    def test_rate_max(self):
        sectors = ['fbt', 'mvh', 'ely']
        cols = sectors + ['p', 'g', 'i']
        g = np.zeros((3, 6))
        g[0, 3], g[1, 3], g[2, 3] = 0.9, 0.15, 5.0                   # fbt excise and ely left out of p
        g[0, 4], g[1, 4] = 2.9, 0.1                                    # government fbt counts
        m = PS13.final_demand_rate_max(g, sectors, cols)
        self.assertAlmostEqual(m['p_rate_max'], 0.15)
        self.assertAlmostEqual(m['g_rate_max'], 2.9)

    def test_vat_on_new_region(self):
        sectors = ['fbt', 'mvh', 'ely']
        cols = sectors + ['p', 'g', 'i']
        b = np.full((3, 6), 10.0)
        general = np.full((3, 6), 0.3)
        general[:, 4] = 2.9                                            # donor government rate (mutation: above 1)
        cell = general.copy()
        cell[2, :] += 0.2
        c2, g2, _, info = PS13.vat_final_demand(cell, general, b, (cell * b).sum(axis=0), sectors, cols, 6.0, 0.0, zero_firms=True)
        m = PS13.final_demand_rate_max(g2, sectors, cols)
        self.assertAlmostEqual(info['vat_rate'], 0.1)                 # 6 over the p and g base of 60
        self.assertLessEqual(max(m['p_rate_max'], m['g_rate_max']), 0.15)
        self.assertAlmostEqual(float(g2[:, :3].sum()), 0.0)            # firms deduct


if __name__ == '__main__':
    unittest.main()
