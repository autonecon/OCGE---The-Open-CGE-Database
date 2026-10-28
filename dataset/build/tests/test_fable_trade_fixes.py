"""Unit tests for the Fable QA trade fixes in S07 to S09 (D-01, D-03, C-05, B-04).

Run from dataset/build:  python3 -m unittest tests.test_fable_trade_fixes -v
"""
import csv
import json
import os
import sys
import tempfile
import unittest

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BUILD)
sys.path.insert(0, os.path.join(BUILD, 'prep_trade'))

import duckdb  # noqa: E402

import retained_imports as RI  # noqa: E402
import s08_margins as S8  # noqa: E402
import s09_services as S9  # noqa: E402


class HkMarginTest(unittest.TestCase):
    """D-01: the HKG re-export margin leaves the origin flows and is booked once, never driving a flow negative."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(self.tmp.name, 'hk'))
        rows = [
            dict(co='CN', cc='US', figure='1000000', period=2022),   # CHN -> USA, margin 0.1 x 1e6 / 8 = 12,500
            dict(co='CN', cc='DE', figure='8000000', period=2022),   # CHN -> DEU, margin 100,000 > flow 50,000
            dict(co='CN', cc='CN', figure='400000', period=2022),    # back to origin: reported only
            dict(co='CN', cc='HK', figure='400000', period=2022),    # HKG partner: reported only
            dict(co='ZZ', cc='US', figure='400000', period=2022),    # unmapped
        ]
        with open(os.path.join(self.tmp.name, 'hk', 'rx_od.json'), 'w') as fh:
            json.dump(rows, fh)
        self.con = duckdb.connect()
        self.con.execute('CREATE TABLE flows(exporter VARCHAR, importer VARCHAR, hs6 VARCHAR, value DOUBLE, qty DOUBLE, qty_ok BOOLEAN)')
        self.con.executemany('INSERT INTO flows VALUES (?, ?, ?, ?, ?, ?)', [
            ('CHN', 'USA', '850000', 300000.0, 1.0, True),
            ('CHN', 'USA', '940000', 100000.0, 1.0, True),
            ('CHN', 'DEU', '850000', 50000.0, 1.0, True),
            ('JPN', 'USA', '850000', 70000.0, 1.0, True),
        ])
        self.iso2 = {'CN': 'CHN', 'US': 'USA', 'DE': 'DEU', 'HK': 'HKG'}
        self.reg = {'CHN': 'CHN', 'USA': 'USA', 'DEU': 'DEU', 'HKG': 'HKG'}

    def tearDown(self):
        self.tmp.cleanup()

    def test_margin_conserved_and_capped(self):
        checks = []
        before = self.con.execute('SELECT SUM(value) FROM flows').fetchone()[0]
        got = RI.hk_margin(self.con, self.tmp.name, 0.9, 8.0, self.iso2, self.reg, checks)
        after = self.con.execute('SELECT SUM(value) FROM flows').fetchone()[0]
        self.assertAlmostEqual(got['applied'], 12500.0 + 50000.0, places=6)
        self.assertAlmostEqual(before - after, got['applied'], places=6)
        self.assertAlmostEqual(got['short'], 50000.0, places=6)
        self.assertAlmostEqual(got['to_origin'], 5000.0, places=6)
        self.assertAlmostEqual(got['hkg'], 5000.0, places=6)
        self.assertAlmostEqual(got['unmapped'], 5000.0, places=6)
        self.assertEqual(self.con.execute('SELECT COUNT(*) FROM flows WHERE value < 0').fetchone()[0], 0)
        # Proportional within the pair; other exporters untouched.
        chn_usa = dict(self.con.execute("SELECT hs6, value FROM flows WHERE exporter = 'CHN' AND importer = 'USA'").fetchall())
        self.assertAlmostEqual(chn_usa['850000'] / chn_usa['940000'], 3.0, places=9)
        self.assertEqual(self.con.execute("SELECT value FROM flows WHERE exporter = 'JPN'").fetchone()[0], 70000.0)
        booked = dict(self.con.execute('SELECT dest, value FROM hk_margin').fetchall())
        self.assertAlmostEqual(sum(booked.values()), got['applied'], places=6)
        hard = [c for c in checks if c['kind'] == 'hard']
        self.assertTrue(hard and all(c['passed'] for c in hard))


class VstKeyTest(unittest.TestCase):
    """D-03: key = BoP freight exports plus own-carrier freight on imports."""

    def test_own_carrier_part(self):
        self.assertEqual(S8.own_carrier_key(10.0, 30.0, 50.0, 100.0), (30.0, 20.0))

    def test_foreign_cover_floors_at_zero(self):
        # Foreign carriers' freight above the region's VTWR into it gives no own-carrier part.
        self.assertEqual(S8.own_carrier_key(10.0, 80.0, 50.0, 100.0), (10.0, 0.0))

    def test_own_part_capped_at_output_headroom(self):
        # A region with little transport output cannot carry its own imports: own part <= output - freight exports.
        self.assertEqual(S8.own_carrier_key(10.0, 0.0, 50.0, 25.0), (25.0, 15.0))
        self.assertEqual(S8.own_carrier_key(30.0, 0.0, 50.0, 25.0), (30.0, 0.0))

    def test_cap_keeps_mode_total(self):
        vst = {'A': 60.0, 'B': 30.0, 'C': 10.0}
        out, fixed = S8.cap_filled(vst, ['A'], {'A': 20.0}, 100.0)
        self.assertAlmostEqual(out['A'], 20.0)
        self.assertAlmostEqual(sum(out.values()), 100.0)
        self.assertAlmostEqual(out['B'] / out['C'], 3.0)


class RouteModeTest(unittest.TestCase):
    """C-05: energy margin mode by route."""

    def setUp(self):
        self.oil = {('CAN', 'USA'): 0.95}
        self.gas = {('NOR', 'DEU'): (90.0, 10.0), ('QAT', 'JPN'): (0.0, 50.0)}
        self.tot = {'NOR': [90.0, 10.0], 'QAT': [0.0, 50.0], 'RUS': [30.0, 10.0]}

    def test_oil(self):
        self.assertEqual(S8.pipeline_share('oil', 'CAN', 'USA', self.oil, self.gas, self.tot), (0.95, 'oil_pipeline_route'))
        self.assertEqual(S8.pipeline_share('oil', 'SAU', 'CHN', self.oil, self.gas, self.tot), (0.0, 'oil_tanker'))

    def test_gas(self):
        self.assertEqual(S8.pipeline_share('gas', 'NOR', 'DEU', self.oil, self.gas, self.tot), (0.9, 'gas_baci_route'))
        self.assertEqual(S8.pipeline_share('gas', 'QAT', 'JPN', self.oil, self.gas, self.tot), (0.0, 'gas_baci_route'))
        self.assertEqual(S8.pipeline_share('gas', 'RUS', 'TUR', self.oil, self.gas, self.tot), (0.75, 'gas_baci_exporter'))
        self.assertEqual(S8.pipeline_share('gas', 'XYZ', 'TUR', self.oil, self.gas, self.tot), (1.0, 'gas_no_hs6_pipeline'))


class BermudaKeepTest(unittest.TestCase):
    """B-04: the kept BMU -> USA SF row stays at BaTIS, the rest scales to own BoP, the kept value comes back as imports."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ebops = os.path.join(self.tmp.name, 'ebops.csv')
        rows = [
            ('BMU', 'W', 'S', 48000.0), ('BMU', 'W', 'SF', 36000.0), ('BMU', 'USA', 'SF', 30000.0),
            ('BMU', 'USA', 'S', 31000.0), ('BMU', 'GBR', 'SF', 2000.0),
            ('USA', 'BMU', 'S', 9000.0), ('GBR', 'BMU', 'S', 9000.0),
            ('USA', 'BMU', 'SF', 3000.0), ('GBR', 'BMU', 'SF', 1000.0),
        ]
        with open(self.ebops, 'w', newline='') as fh:
            w = csv.writer(fh)
            w.writerow(['REF_AREA', 'COUNTERPART_AREA', 'SERVICE', 'OBS_VALUE'])
            w.writerows(rows)
        self.wdi = os.path.join(self.tmp.name, 'wdi.csv')
        with open(self.wdi, 'w', newline='') as fh:
            w = csv.writer(fh)
            w.writerow(['iso3', 'series', 'value'])
            w.writerow(['BMU', 'BX.GSR.NFSV.CD', '1400e6'])
            w.writerow(['BMU', 'BM.GSR.NFSV.CD', '1000e6'])

    def tearDown(self):
        self.tmp.cleanup()

    def scales(self, keep):
        return S9.own_bop_scales(self.ebops, self.wdi, ('BMU',), set(), keep)['BMU']

    def test_plain_scaling_unchanged(self):
        sc = self.scales(())
        self.assertAlmostEqual(sc['sx'], 1400.0 / 48000.0)
        self.assertEqual(sc['passed'], {})
        self.assertAlmostEqual(S9.scaled_value(sc, 'USA', 'SF', 30000.0), 30000.0 * sc['sx'])

    def test_keep_and_pass_through(self):
        sc = self.scales((('BMU', 'USA', 'SF'),))
        self.assertAlmostEqual(sc['kx'], 30000.0)
        self.assertAlmostEqual(sc['sx'], 1400.0 / 18000.0)
        # Kept row at BaTIS; other rows scaled; totals carry the kept part unscaled.
        self.assertEqual(S9.scaled_value(sc, 'USA', 'SF', 30000.0), 30000.0)
        self.assertAlmostEqual(S9.scaled_value(sc, 'GBR', 'SF', 2000.0), 2000.0 * sc['sx'])
        self.assertAlmostEqual(S9.scaled_value(sc, 'W', 'S', 48000.0), 30000.0 + 1400.0)
        self.assertAlmostEqual(S9.scaled_value(sc, 'W', 'SF', 36000.0), 30000.0 + 6000.0 * sc['sx'])
        self.assertAlmostEqual(S9.scaled_value(sc, 'USA', 'S', 31000.0), 30000.0 + 1000.0 * sc['sx'])
        # Pass-through imports equal the kept value, spread by the sellers' SF exports to Bermuda.
        self.assertAlmostEqual(sum(sc['passed'].values()), 30000.0)
        self.assertAlmostEqual(sc['passed'][('USA', 'SF')], 22500.0)
        self.assertAlmostEqual(sc['passed'][('GBR', 'SF')], 7500.0)
        # Net services stay at own BoP: (X kept + scaled rest) - (M scaled + pass-through) = WDI X - WDI M.
        x = sc['kx'] + (sc['bx'] - sc['kx']) * sc['sx']
        m = sc['bm'] * sc['sm'] + sum(sc['passed'].values())
        self.assertAlmostEqual(x - m, 1400.0 - 1000.0)
        bad, _parts = S9.h13_identity({'BMU': sc})
        self.assertEqual(bad, [])


if __name__ == '__main__':
    unittest.main()
