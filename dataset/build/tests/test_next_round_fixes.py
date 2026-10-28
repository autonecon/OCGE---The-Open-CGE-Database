"""Unit tests for the next-round fixes (2026-10-25): the S12 Gollin labour with its capital-income floor on VDEP,
and the S08 Census sea rate for crude and petroleum products.

Every helper and check is called on a good input (it must pass) and on a mutated input (it must fail).

Run from dataset/build:  python3 -m unittest tests.test_next_round_fixes -v
"""
import csv
import json
import os
import shutil
import sys
import tempfile
import unittest

import pandas as pd

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BUILD)

from s12_factors import checks as K  # noqa: E402
from s12_factors import config as C  # noqa: E402
from s12_factors import method as M  # noqa: E402
import s08_margins as S8  # noqa: E402


class GollinConfigTest(unittest.TestCase):
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

    def test_repo_default_is_gollin_with_floor(self):
        V = {k: v['value'] for k, v in C.load_choices().items()}
        self.assertEqual(V['labour_definition'], 'd1_plus_gollin_self_employed_at_employee_wage')
        self.assertEqual(V['mixed_income'], C.MIXED_INCOME_OF[V['labour_definition']])
        self.assertEqual(V['capital_vdep_floor'], C.VDEP_FLOOR)

    def test_mixed_income_must_follow_labour_definition(self):
        for ld, mi in (('d1_plus_gollin_self_employed_at_employee_wage', 'operating_surplus_and_mixed_income_b2a3g_to_capital'),
                       ('compensation_of_employees_d1', 'self_employed_part_of_b2a3g_to_labour_gollin_rest_capital')):
            rows = [dict(r, value=ld) if r['choice'] == 'labour_definition' else dict(r, value=mi) if r['choice'] == 'mixed_income' else r
                    for r in self.rows]
            self.write(rows)
            with self.assertRaises(C.ConfigError):
                C.load_choices(self.path)
        rows = [dict(r, value='compensation_of_employees_d1') if r['choice'] == 'labour_definition'
                else dict(r, value='operating_surplus_and_mixed_income_b2a3g_to_capital') if r['choice'] == 'mixed_income' else r
                for r in self.rows]
        self.write(rows)
        self.assertEqual(len(C.load_choices(self.path)), len(C.CHOICES))     # the D1 pair still loads


class VdepFloorMethodTest(unittest.TestCase):
    def test_gollin_addition(self):
        self.assertAlmostEqual(M.gollin_addition(60.0, 0.6, 0.4), 20.0)       # 60 x (1 - 0.4 / 0.6)
        self.assertEqual(M.gollin_addition(60.0, 0.4, 0.6), 0.0)              # D1 above the capped share: nothing added
        self.assertEqual(M.gollin_addition(0.0, 0.6, 0.4), 0.0)
        self.assertEqual(M.gollin_addition(10.0, 0.0, 0.0), 0.0)

    def test_return_share(self):
        def evos(b):
            return 80.0 + 40.0 * b                                           # capital income rises with the share returned
        self.assertEqual(M.vdep_floor_return(evos, 70.0), (0.0, 80.0))        # floor already holds
        b, e = M.vdep_floor_return(evos, 100.0)
        self.assertAlmostEqual(b, 0.5, places=12)
        self.assertGreaterEqual(e, 100.0)                                    # the floor is met, never undershot
        self.assertEqual(M.vdep_floor_return(evos, 130.0), (1.0, 120.0))      # back at D1 and still short: b = 1

    def test_return_share_nonlinear(self):
        def evos(b):
            return 50.0 + 100.0 * b * b
        b, e = M.vdep_floor_return(evos, 75.0)
        self.assertAlmostEqual(b, 0.5, places=10)
        self.assertGreaterEqual(e, 75.0)


class VdepFloorCheckTest(unittest.TestCase):
    def setUp(self):
        self.ev = pd.DataFrame([('GNQ', 'oil', 'capital', 0.0, 60.0), ('GNQ', 'ser', 'capital', 0.0, 66.0),
                                ('GNQ', 'ser', 'clerks', 0.0, 50.0), ('TLS', 'oil', 'capital', 0.0, 40.0)],
                               columns=['region', 'sector', 'factor', 'evfp', 'evos'])
        self.fl = pd.DataFrame([dict(region='GNQ', floor_musd=125.0, returned_share=0.3, capital_evos_after_musd=126.0),
                                dict(region='TLS', floor_musd=50.0, returned_share=1.0, capital_evos_after_musd=40.0)])

    def test_good(self):
        self.assertEqual(K.vdep_floor(self.ev, self.fl)[0], 0)              # GNQ meets it; TLS is back at D1

    def test_mutations(self):
        self.assertEqual(K.vdep_floor(self.ev, self.fl.assign(floor_musd=[130.0, 50.0], capital_evos_after_musd=[126.0, 40.0]))[0], 1)
        self.assertEqual(K.vdep_floor(self.ev, self.fl.assign(returned_share=[0.3, 0.9]))[0], 1)       # TLS short, not at D1
        ev = self.ev.copy()
        ev.loc[0, 'evos'] = 59.0                                                                           # written != floor step
        self.assertEqual(K.vdep_floor(ev, self.fl)[0], 1)


class CensusSeaRateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.imdb = os.path.join(self.tmp, 'hs6.csv')
        with open(self.imdb, 'w', newline='') as fh:
            w = csv.writer(fh)
            w.writerow(['hs6', 'cty', 'rate_prov', 'con_val', 'dut_val', 'cal_dut', 'con_cif', 'gen_val'])
            w.writerow(['270900', '5170', '10', 2e9, 0, 0, 2.05e9, 2e9])      # SAU crude 2.5%
            w.writerow(['271019', '5170', '10', 1e9, 0, 0, 1.04e9, 1e9])      # SAU products 4%
            w.writerow(['270900', '1220', '10', 8e9, 0, 0, 8.08e9, 8e9])      # CAN crude 1%: not in the fallback
            w.writerow(['270900', '5330', '10', 5e7, 0, 0, 5.3e7, 5e7])       # IND crude 6% on 50 m: below the minimum
            w.writerow(['271111', '5170', '10', 1e9, 0, 0, 1.2e9, 1e9])       # gas: not re-rated
            w.writerow(['270900', '9999', '10', 1e9, 0, 0, 1.1e9, 1e9])       # unknown country
        self.hs2 = os.path.join(self.tmp, 'hs2.json')
        with open(self.hs2, 'w') as fh:
            json.dump([['CTY_CODE', 'CTY_NAME', 'I_COMMODITY'], ['5170', 'SAUDI ARABIA', '27'], ['1220', 'CANADA', '27'],
                       ['5330', 'INDIA', '27']], fh)
        self.by_norm = {'SAUDIARABIA': 'SAU', 'CANADA': 'CAN', 'INDIA': 'IND'}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_rates_and_fallback(self):
        rates, fb, val, unmatched = S8.census_energy_rates(self.imdb, self.hs2, self.by_norm, {'SAU': 'SAU', 'CAN': 'CAN', 'IND': 'XSA'})
        self.assertAlmostEqual(rates[('oil', 'SAU')], 0.025)
        self.assertAlmostEqual(rates[('pet', 'SAU')], 0.04)
        self.assertAlmostEqual(rates[('oil', 'CAN')], 0.01)
        self.assertNotIn(('oil', 'XSA'), rates)                              # India sits in its composite, under the minimum
        self.assertAlmostEqual(val[('oil', 'XSA')], 5e7)
        self.assertAlmostEqual(fb['oil'], (0.05e9 + 0.003e9) / (2e9 + 5e7))  # every exporter but Canada, value-weighted
        self.assertNotIn('gas', fb)
        self.assertEqual(unmatched, ['9999'])

    def test_route_parts(self):
        m, sh = S8.census_route_parts(0.075, 0.025, (0.0, 1.0, 0.0))          # tanker crude: all at the Census rate
        self.assertAlmostEqual(m, 0.025)
        self.assertEqual(sh, (0.0, 1.0, 0.0))
        m, sh = S8.census_route_parts(0.10, 0.04, (0.07, 0.93, 0.0))          # products: sea re-rated, road keeps ITIC
        self.assertAlmostEqual(m, 0.93 * 0.04 + 0.07 * 0.10)
        self.assertAlmostEqual(sh[1], 0.93 * 0.04 / m)
        self.assertAlmostEqual(sum(sh), 1.0)
        m, sh = S8.census_route_parts(0.05, 0.02, (1.0, 0.0, 0.0))            # a crude pipeline keeps ITIC
        self.assertAlmostEqual(m, 0.05)
        self.assertEqual(sh, (1.0, 0.0, 0.0))

    def test_choice_registered(self):
        self.assertIn('energy_sea_rate', S8.CHOICE_ORDER)
        self.assertEqual(S8.ALLOWED['energy_sea_rate'], {'itic', 'us_census_exporter_hs4', S8.CENSUS_WHOLE_ROUTE})
        with open(os.path.join(BUILD, 'config', 's08', 'margin_choices.csv'), newline='') as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual([r['choice'] for r in rows].count('energy_sea_rate'), 1)


if __name__ == '__main__':
    unittest.main()
