"""Unit tests for the beta v5 S02-S05 fixes (Y, H, S1; David 2026-10-27 08:39 UTC, package v2).

Y: S02 gdp_imputed_ama_to_weo (s02_capital/gdp_weo.py). H: S03 household_employers_va = hfce_by_coicop
(s03_household_employers.py). S1: S05 donor_va_sections scoped to TLS (s05_composite/va_sections.py members).
Each helper is called on a good input and on a mutated one. No stage is run.

Run from dataset/build:  python3 -m unittest tests.test_betav5_s02_s05 -v
"""
import csv
import os
import sys
import tempfile
import unittest

import numpy as np

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BUILD)

import s03_household_employers as HHE  # noqa: E402
from s02_capital import gdp_official as GO  # noqa: E402
from s02_capital import gdp_weo as GW  # noqa: E402
from s02_capital import pim as PIM  # noqa: E402
from s05_composite import guards as GD  # noqa: E402
from s05_composite import va_sections as VS  # noqa: E402
from tests.test_betav4_extra_fixes import toy_icio  # noqa: E402

DATA = os.path.join(os.path.dirname(BUILD), 'data')


class YemenGdpTest(unittest.TestCase):
    """Y: WEO GDP where WDI lacks the year and the UN AMA series is imputed or below 250 USD per head."""

    def test_imputation_test(self):
        self.assertTrue(GW.ama_imputed([6884.42, 7023.97, 7163.51, 7303.06, 7442.60]))        # YEM AMA 2020-2024, bn rial
        self.assertFalse(GW.ama_imputed([1695.76, 1791.92, 1646.97, 1809.13, 1891.92]))       # PRK
        self.assertFalse(GW.ama_imputed([100.0, 100.0, 100.0]))                               # flat is not a trend
        self.assertFalse(GW.ama_imputed([1.0, 2.0]))
        self.assertFalse(GW.ama_imputed([1.0, float('nan'), 3.0]))

    def test_rule(self):
        self.assertTrue(GW.applies('UNSD AMA', True, 168.0, 11107.0))
        self.assertTrue(GW.applies('UNSD AMA', False, 168.0, 11107.0))     # per-head test alone
        self.assertFalse(GW.applies('UNSD AMA', False, 395.0, 7533.0))     # SSD: not imputed, 395 USD per head
        self.assertFalse(GW.applies('UNSD AMA', True, 168.0, None))        # no WEO value (PRK, SYR)
        self.assertFalse(GW.applies('WDI', True, 168.0, 11107.0))          # WDI GDP is never replaced

    def test_weo_file_and_choice(self):
        weo = GW.read_weo(os.path.join(DATA, 'imf_weo/weo_2026oct_ngdpd_2017_2023.csv'), 2022)
        self.assertAlmostEqual(weo['YEM'][0], 11107.0)
        self.assertNotIn('PRK', weo)
        self.assertEqual(PIM.load_choices()[GW.CHOICE]['value'], GW.ON_RATE)       # South Sudan rate test (09:32 UTC)
        self.assertEqual(set(PIM.CHOICES[GW.CHOICE]), set(GW.VALUES))

    def test_rate_test(self):
        self.assertTrue(GW.rate_off(2138.78, 534.51))                     # SSD: AMA near the parallel rate
        self.assertFalse(GW.rate_off(1115.0, 1115.0))                     # YEM
        self.assertFalse(GW.rate_off(15.075, 15.075))                     # ERI
        self.assertFalse(GW.rate_off(1.0, None))                          # CUB: no WDI rate
        self.assertTrue(GW.rate_off(100.0, 200.0))                        # either direction
        self.assertTrue(GW.applies('UNSD AMA', False, 395.0, 7533.0, rate_mismatch=True))
        self.assertFalse(GW.applies('UNSD AMA', False, 395.0, None, rate_mismatch=True))

    def test_basis_per_head(self):
        # David 2026-10-27 10:00 UTC: WEO per head x S02 population (the WEO Yemen total implies 17.2 m people)
        self.assertAlmostEqual(GW.target_musd(11107.0, 645.764, 38.222876, GW.BASIS_PC), 645.764 * 38.222876)
        self.assertEqual(GW.target_musd(11107.0, 645.764, 38.222876, GW.BASIS_TOTAL), 11107.0)
        self.assertEqual(GW.target_musd(11107.0, None, 38.2, GW.BASIS_PC), 11107.0)      # no per head: the total
        self.assertEqual(PIM.load_choices()[GW.BASIS_CHOICE]['value'], GW.BASIS_PC)
        self.assertEqual(set(PIM.CHOICES[GW.BASIS_CHOICE]), set(GW.BASIS_VALUES))

    def test_choice_value_is_strict(self):
        rows = list(csv.DictReader(open(PIM.CHOICES_PATH)))
        for r in rows:
            if r['choice'] == GW.CHOICE:
                r['value'] = 'weo_everywhere'
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'c.csv')
            w = csv.DictWriter(open(p, 'w', newline=''), fieldnames=PIM.CHOICE_COLUMNS)
            w.writeheader(); w.writerows(rows)
            with self.assertRaises(PIM.ConfigError):
                PIM.load_choices(p)


def toy_hfce():
    """toy_icio plus a TLS cell and two other household services (G sells 10, L sells 30 to households)."""
    A, rows, cols = toy_icio()
    rows = rows[:4] + ['E_G', 'E_L'] + rows[4:]
    cols = cols[:4] + ['E_G', 'E_L'] + cols[4:]
    B = np.zeros((len(rows), len(cols)))
    old_r = [0, 1, 2, 3, 6, 7, 8]
    old_c = [0, 1, 2, 3, 6, 7, 8]
    B[np.ix_(old_r, old_c)] = A
    B[4, 6], B[5, 6] = 10.0, 30.0                     # households buy G and L
    B[7, 4], B[7, 5] = 10.0, 30.0                     # their VA
    B[8, 4], B[8, 5] = 10.0, 30.0                     # OUT row
    B[4, 8], B[5, 8] = 10.0, 30.0                     # OUT column
    B[6, 6] = 5.0                                     # TLS on household purchases
    return B, rows, cols


class HouseholdCoicopTest(unittest.TestCase):
    """H: P and Q take their D1 parts only up to the COICOP cap; the rest goes to the other household services."""

    def test_parts_capped_and_spread(self):
        A, rows, cols = toy_hfce()
        tot, by, own = HHE.household_purchases(A, rows, cols, 'E')
        self.assertAlmostEqual(tot, 1 + 4 + 50 + 10 + 30 + 5)                 # industry rows plus TLS
        moved = HHE.moved_amount(A, rows, cols, 'E', 2.0)
        self.assertAlmostEqual(moved, 48.0)
        # P cap 5% of 100 = 5, households buy 0 of P -> room 5; Q cap 10% = 10, buys 4 -> room 6
        parts, info = HHE.coicop_parts(moved, {'P': 1.0, 'Q': 1.0}, {'P': 0.05, 'Q': 0.10}, tot, by, own, others=('G', 'L'))
        self.assertAlmostEqual(parts['P'], 5.0)
        self.assertAlmostEqual(parts['Q'], 6.0)
        self.assertAlmostEqual(parts['G'], 37.0 * 10 / 40)
        self.assertAlmostEqual(parts['L'], 37.0 * 30 / 40)
        self.assertAlmostEqual(sum(parts.values()), moved)
        self.assertEqual(info['Q'], (10.0, 4.0, 6.0))
        info2 = HHE.reallocate(A, rows, cols, 'E', 2.0, None, to='HFCE', parts=parts)
        tot2, by2, _ = HHE.household_purchases(A, rows, cols, 'E')
        self.assertAlmostEqual(tot2, tot)                                     # C keeps its total
        self.assertAlmostEqual(by2['P'], 5.0)
        self.assertAlmostEqual(by2['Q'], 10.0)
        self.assertAlmostEqual(info2['moved'], 48.0)
        n = 6                                                                 # every industry still balances
        for i in range(n):
            self.assertAlmostEqual(A[i, :-1].sum(), A[i, -1])
            self.assertAlmostEqual(A[:n, i].sum() + A[n:n + 2, i].sum(), A[n + 2, i])

    def test_published_purchase_above_cap_is_not_cut(self):
        A, rows, cols = toy_hfce()
        tot, by, own = HHE.household_purchases(A, rows, cols, 'E')
        parts, info = HHE.coicop_parts(48.0, {'P': 1.0, 'Q': 1.0}, {'P': 0.05, 'Q': 0.02}, tot, by, own, others=('G', 'L'))
        self.assertEqual(parts['Q'], 0.0)                                     # cap 2 < bought 4: room 0, nothing cut
        self.assertEqual(info['Q'][2], 0.0)

    def test_parts_must_sum(self):
        A, rows, cols = toy_hfce()
        with self.assertRaises(SystemExit):
            HHE.reallocate(A, rows, cols, 'E', 2.0, None, to='HFCE', parts={'P': 1.0})
        with self.assertRaises(SystemExit):
            HHE.coicop_parts(48.0, {'P': 1.0}, {'P': 0.01}, 100.0, {}, {}, others=('X',))   # no other service to take it

    def test_config(self):
        cfg = os.path.join(BUILD, 'config/s03')
        self.assertEqual(HHE.load_choice(os.path.join(cfg, 's03_choices.csv')), HHE.HFCE_BY_COICOP)
        caps = HHE.load_caps(os.path.join(cfg, 'hfce_coicop_caps_2022.csv'))
        self.assertAlmostEqual(caps['ZAF']['P'], 148977 / 4222890)
        self.assertAlmostEqual(caps['ZAF']['Q'], 288673 / 4222890)
        self.assertEqual(HHE.recipients_for(HHE.HFCE_BY_COICOP, ['O', 'P', 'Q']), ['P', 'Q'])
        sna = {r['code']: float(r['value_lcu']) for r in csv.DictReader(open(os.path.join(DATA, 'unsd_sna_coicop/zaf_table32_hfce_by_purpose_2022.csv')))}
        self.assertAlmostEqual(sum(v for k, v in sna.items() if k.isdigit()), sna["P.31"], delta=1e7)   # 12 divisions add to HFCE (rounding)

    def test_bad_cap_row(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'c.csv')
            with open(p, 'w', newline='') as fh:
                w = csv.writer(fh); w.writerow(HHE.CAP_COLUMNS)
                w.writerow(['ZAF', 'R', '09', '1', '10', 'src', 'David', '2026-10-27', 'b'])
            with self.assertRaises(SystemExit):
                HHE.load_caps(p)


class CubaOfficialRateTest(unittest.TestCase):
    """Cuba: official national-currency accounts (UN SNA table 1.1) at the listed official rate."""

    def test_table_and_rate(self):
        rows = GO.load_rows(os.path.join(BUILD, 'config/s02/gdp_official_rate_2022.csv'))
        self.assertEqual(float(rows['CUB']['lcu_per_usd']), 24.0)
        lcu = GO.read_table(os.path.join(DATA, rows['CUB']['data_file']), 'CUB', 2022)
        self.assertEqual(lcu['GDP'], 633442000000.0)
        self.assertEqual(lcu['I'], 72713300000.0)
        usd = GO.to_musd(lcu, 24)
        self.assertAlmostEqual(usd['GDP'], 26393.4, places=1)
        self.assertAlmostEqual(usd['C'] / usd['GDP'], 377846 / 633442, places=9)
        self.assertEqual(PIM.load_choices()[GO.CHOICE]['value'], GO.ON)

    def test_missing_item_stops(self):
        with self.assertRaises(SystemExit):
            GO.read_table(os.path.join(DATA, 'unsd_sna_official/cub_table11_gdp_expenditure_2021_2024.csv'), 'CUB', 2017)

    def test_bad_rate_row(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'c.csv')
            with open(p, 'w', newline='') as fh:
                w = csv.writer(fh); w.writerow(GO.COLUMNS)
                w.writerow(['CUB', '2022', '0', 'src', 'f.csv', 'David', '2026-10-27', 'b'])
            with self.assertRaises(SystemExit):
                GO.load_rows(p)


class TimorScopeTest(unittest.TestCase):
    """S1: donor_va_sections applies to the members its parameter lists (TLS in beta v5)."""

    def test_members(self):
        self.assertIsNone(VS.members(''))
        self.assertEqual(VS.members('TLS'), {'TLS'})
        self.assertEqual(VS.members('TLS; ETH'), {'TLS', 'ETH'})
        with self.assertRaises(ValueError):
            VS.members('Timor')

    def test_config(self):
        on, blend, rows = GD.read_guards(os.path.join(BUILD, 'config/s05/donor_guards.csv'))
        row = {r['guard']: r for r in rows}['donor_va_sections']
        self.assertEqual(VS.members(row['parameter']), {'TLS'})
        self.assertEqual(row['value'], 'ama_ex_energy')
        self.assertEqual(blend, 'off')
        self.assertEqual(on, [('donor_size_guard', '20')])
        ama = VS.read_ama(os.path.join(DATA, 'unsd_ama/gva_gdp_current_usd.csv'))
        self.assertIn('TLS', ama)


if __name__ == '__main__':
    unittest.main()
