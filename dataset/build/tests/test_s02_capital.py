"""Tests for the S02 capital roll-forward helpers (s02_capital/pim.py) and the S02 choices file.

Run from dataset/build:  python3 -m unittest tests.test_s02_capital -v
"""
import math
import os
import shutil
import sys
import tempfile
import unittest

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BUILD)

from s02_capital import pim as PIM  # noqa: E402


class Revaluation(unittest.TestCase):
    def test_gfcf_deflator_used_when_available(self):
        # current GFCF 120 / constant 100 in t, 100 / 100 in t-1: investment prices +20%; GDP deflator +40%
        f, b = PIM.revaluation('gfcf_implicit_deflator_else_gdp_deflator', 120, 100, 100, 100, 140, 100)
        self.assertEqual(b, 'gfcf')
        self.assertAlmostEqual(f, 1.2)

    def test_gdp_deflator_fallback_without_constant_price_gfcf(self):
        f, b = PIM.revaluation('gfcf_implicit_deflator_else_gdp_deflator', 120, float('nan'), 100, 100, 140, 100)
        self.assertEqual(b, 'gdp')
        self.assertAlmostEqual(f, 1.4)

    def test_gdp_rule_ignores_gfcf(self):
        f, b = PIM.revaluation('gdp_deflator', 120, 100, 100, 100, 140, 100)
        self.assertEqual(b, 'gdp')
        self.assertAlmostEqual(f, 1.4)

    def test_no_index_gives_nan(self):
        f, b = PIM.revaluation('gfcf_implicit_deflator_else_gdp_deflator', None, None, None, None, float('nan'), 100)
        self.assertTrue(math.isnan(f))
        self.assertEqual(b, '')

    def test_unknown_rule_raises(self):
        with self.assertRaises(ValueError):
            PIM.revaluation('cpi', float('nan'), 1, 1, 1, 1, 1)


class RollAndRebase(unittest.TestCase):
    def test_roll_is_the_perpetual_inventory(self):
        # K1 = 0.96 * 300 * 1.1 + 30; K2 = 0.96 * K1 * 1.0 + 40
        k1 = 0.96 * 300 * 1.1 + 30
        self.assertAlmostEqual(PIM.roll(300, [(1.1, 30), (1.0, 40)]), 0.96 * k1 + 40)
        self.assertEqual(PIM.roll(300, []), 300)

    def test_oil_price_gdp_deflator_inflates_the_stock(self):
        # A GDP deflator driven by export prices revalues the stock more than the investment price does.
        k_gdp = PIM.roll(350, [(1.19, 25)])
        k_gfcf = PIM.roll(350, [(1.08, 25)])
        self.assertGreater(k_gdp, k_gfcf)

    def test_rebase_band(self):
        self.assertEqual(PIM.rebase(3.0, 2.0, 0.25), (2.0, True))     # +50%: re-based
        self.assertEqual(PIM.rebase(1.4, 2.0, 0.25), (2.0, True))     # -30%: re-based
        self.assertEqual(PIM.rebase(2.4, 2.0, 0.25), (2.4, False))    # +20%: kept
        self.assertEqual(PIM.rebase(3.0, 2.0, None), (3.0, False))    # no band
        self.assertEqual(PIM.band_value('none'), None)
        self.assertEqual(PIM.band_value('0.25'), 0.25)


class Choices(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, 's02_choices.csv')
        shutil.copy(PIM.CHOICES_PATH, self.path)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_shipped_file_loads(self):
        ch = PIM.load_choices()
        self.assertEqual(set(ch), set(PIM.CHOICES))
        for c, r in ch.items():
            self.assertEqual(r['value'], PIM.CHOICES[c][0], c)

    def _mutate(self, old, new):
        s = open(self.path).read()
        self.assertIn(old, s)
        open(self.path, 'w').write(s.replace(old, new, 1))

    def test_unknown_value_stops(self):
        self._mutate('gfcf_implicit_deflator_else_gdp_deflator', 'cpi')
        with self.assertRaises(PIM.ConfigError):
            PIM.load_choices(self.path)

    def test_missing_row_stops(self):
        lines = open(self.path).read().splitlines()
        open(self.path, 'w').write('\n'.join(l for l in lines if not l.startswith('capital_rebase_band')) + '\n')
        with self.assertRaises(PIM.ConfigError):
            PIM.load_choices(self.path)

    def test_bad_status_stops(self):
        self._mutate(',not_in_gtap_text', ',maybe')
        with self.assertRaises(PIM.ConfigError):
            PIM.load_choices(self.path)


if __name__ == '__main__':
    unittest.main()


class GfcfOutlier(unittest.TestCase):
    """Beta v4 G16a (gfcf_wdi_outlier, default off): WDI GFCF below 5% of GDP with UN AMA above twice it."""

    def test_rule(self):
        self.assertTrue(PIM.gfcf_outlier(0.012, 0.311))           # LBN
        self.assertTrue(PIM.gfcf_outlier(0.047, 0.141))           # VEN
        self.assertFalse(PIM.gfcf_outlier(0.044, 0.045))          # SYR: AMA agrees
        self.assertFalse(PIM.gfcf_outlier(0.06, 0.30))            # WDI not below 5%
        self.assertFalse(PIM.gfcf_outlier(0.03, float('nan')))

    def test_default(self):
        # David 2026-10-26: AMA for LBN and VEN (an estimate); LBN 2019 WDI share, every detected country and off as alternatives
        self.assertEqual(PIM.load_choices()['gfcf_wdi_outlier']['value'], PIM.GFCF_AMA_LBN_VEN_SDN)   # beta v5: SDN (XNF) added
        self.assertEqual(PIM.GFCF_REGIONS[PIM.GFCF_AMA_LBN_VEN_SDN], ('LBN', 'VEN', 'SDN'))
        self.assertTrue(PIM.gfcf_outlier(0.022, 0.087))           # SDN meets the G16a test
        self.assertEqual(PIM.GFCF_REGIONS[PIM.GFCF_AMA_LBN_VEN], ('LBN', 'VEN'))
        self.assertIsNone(PIM.GFCF_REGIONS[PIM.GFCF_AMA])
        self.assertEqual(set(PIM.CHOICES['gfcf_wdi_outlier']), set(PIM.GFCF_REGIONS))
