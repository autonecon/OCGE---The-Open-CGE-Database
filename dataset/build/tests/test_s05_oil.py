"""Mutation tests for the B8 oil and gas donor swap at S05 (s05_composite/oil.py) and its two config tables.

Every check is called on a good input (it must pass) and on a mutated input (it must fail).

Run from dataset/build:  python3 -m unittest tests.test_s05_oil -v
"""
import csv
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BUILD)

from s05_composite import oil as OIL  # noqa: E402

N_S, N_A, J = 4, 8, 1          # 4 sectors, p g i dpabr; B06 is sector 1
L = OIL.layout(N_S, N_A)
CFG = os.path.join(BUILD, 'config', 's05')

# The 18 members and donors of David's B8 card (s16 b8_oil_donors.md).
B8 = {'IRN': ('IND', 'SAU'), 'IRQ': ('JOR', 'SAU'), 'KWT': ('CYP', 'SAU'), 'OMN': ('TUR', 'SAU'),
      'LBY': ('TUN', 'SAU'), 'BHR': ('CYP', 'SAU'), 'SYR': ('JOR', 'SAU'), 'YEM': ('JOR', 'SAU'),
      'AZE': ('TUR', 'KAZ'), 'COG': ('CIV', 'AGO'), 'GUY': ('CHL', 'AGO'), 'GNQ': ('ZAF', 'AGO'),
      'GHA': ('CIV', 'AGO'), 'GAB': ('ZAF', 'AGO'), 'TCD': ('COD', 'AGO'), 'TTO': ('CHL', 'BRN'),
      'PNG': ('NZL', 'BRN'), 'TLS': ('MMR', 'BRN')}


def make_table(seed, resid=0.0):
    """A small single-region table in the S05 layout, balanced up to an optional row residual."""
    rng = np.random.default_rng(seed)
    T = np.zeros((2 * N_S + 3, N_A + 4))
    T[:N_S, :N_A] = rng.uniform(1, 10, (N_S, N_A))
    T[N_S:2 * N_S, :N_A] = rng.uniform(0, 5, (N_S, N_A))
    T[:N_S, L['X_C']] = rng.uniform(0, 20, N_S)
    T[:N_S, L['ST_C']] = rng.uniform(-1, 1, N_S)
    T[:N_S, L['GR_C']] = rng.uniform(0, 0.5, N_S)
    T[L['TLS_R'], :N_A] = rng.uniform(-0.5, 2, N_A)
    out = (T[:N_S, :N_A].sum(axis=1) + T[:N_S, L['X_C']] + T[:N_S, L['ST_C']] - T[:N_S, L['GR_C']]
           + resid * rng.uniform(-1, 1, N_S))
    T[:N_S, L['OUT_C']] = out
    T[L['OUT_R'], :N_S] = out
    T[L['VA_R'], :N_S] = out - T[:2 * N_S, :N_S].sum(axis=0) - T[L['TLS_R'], :N_S]
    T[L['VA_R'], N_S:N_A] = 0.0
    assert (T[L['VA_R'], :N_S] > 0).all()
    return T


class SwapTest(unittest.TestCase):
    def setUp(self):
        self.base, self.oil = make_table(1, resid=1e-4), make_table(2)
        self.new, self.info = OIL.swap_column(self.base, self.oil, J, N_S, N_A)

    def test_good_swap_passes(self):
        self.assertEqual(OIL.check_swap(self.base, self.oil, self.new, J, N_S, N_A), [])
        np.testing.assert_allclose(OIL.cost_shares(self.new, J, N_S, N_A),
                                   OIL.cost_shares(self.oil, J, N_S, N_A), atol=1e-12)
        self.assertGreater(self.info['out_after'], 0)

    def test_linear_in_scale(self):
        n2, _ = OIL.swap_column(3.7 * self.base, self.oil, J, N_S, N_A)
        np.testing.assert_allclose(n2, 3.7 * self.new, rtol=1e-12, atol=1e-12)

    def test_no_swap_fails(self):
        self.assertTrue(any('oil donor' in p for p in OIL.check_swap(self.base, self.oil, self.base, J, N_S, N_A)))

    def test_column_scaled_without_solve_fails(self):
        # B06 column swapped at fixed output, other columns untouched: the domestic rows lose their residual.
        bad = self.base.copy()
        bad[:L['OUT_R'], J] = OIL.cost_shares(self.oil, J, N_S, N_A) * self.base[L['OUT_R'], J]
        self.assertTrue(any('row residual' in p for p in OIL.check_swap(self.base, self.oil, bad, J, N_S, N_A)))

    def test_other_column_moved_fails(self):
        bad = self.new.copy()
        bad[0, 2] *= 1.01
        self.assertTrue(any('column 2' in p for p in OIL.check_swap(self.base, self.oil, bad, J, N_S, N_A)))

    def test_final_demand_moved_fails(self):
        for col in (N_S, L['X_C'], L['GR_C']):
            bad = self.new.copy()
            bad[0, col] += 0.5
            self.assertTrue(any('final-demand' in p for p in OIL.check_swap(self.base, self.oil, bad, J, N_S, N_A)))

    def test_b06_column_moved_fails(self):
        bad = self.new.copy()
        bad[L['VA_R'], J] *= 1.001
        self.assertTrue(any(f'column {J}' in p for p in OIL.check_swap(self.base, self.oil, bad, J, N_S, N_A)))

    def test_out_row_column_differ_fails(self):
        bad = self.new.copy()
        bad[L['OUT_R'], 3] += 1.0
        self.assertTrue(OIL.check_swap(self.base, self.oil, bad, J, N_S, N_A))

    def test_unbalanced_base_out_refused(self):
        bad = self.base.copy()
        bad[L['OUT_R'], 0] += 1.0
        with self.assertRaises(ValueError):
            OIL.swap_column(bad, self.oil, J, N_S, N_A)

    def test_zero_output_oil_donor_refused(self):
        bad = self.oil.copy()
        bad[L['OUT_R'], J] = 0.0
        with self.assertRaises(ValueError):
            OIL.swap_column(self.base, bad, J, N_S, N_A)

    def test_zero_output_sector_kept(self):
        base = make_table(3)
        k = 3                                     # a sector the base table does not produce
        base[k, :] = 0.0
        base[:, k] = 0.0
        base[:N_S, L['OUT_C']] = (base[:N_S, :N_A].sum(axis=1) + base[:N_S, L['X_C']] + base[:N_S, L['ST_C']]
                                  - base[:N_S, L['GR_C']])
        base[L['OUT_R'], :N_S] = base[:N_S, L['OUT_C']]
        base[L['VA_R'], :N_S] = base[L['OUT_R'], :N_S] - base[:2 * N_S, :N_S].sum(axis=0) - base[L['TLS_R'], :N_S]
        new, info = OIL.swap_column(base, self.oil, J, N_S, N_A)
        self.assertEqual(info['fixed_cols'], 1)
        self.assertEqual(new[L['OUT_R'], k], 0.0)
        self.assertEqual(OIL.check_swap(base, self.oil, new, J, N_S, N_A), [])


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        with open(os.path.join(CFG, 'oil_donors.csv'), newline='') as fh:
            self.donor_rows = list(csv.DictReader(fh))
        with open(os.path.join(CFG, 'oil_check_codes.csv'), newline='') as fh:
            self.check_rows = list(csv.DictReader(fh))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write(self, name, rows, cols):
        p = os.path.join(self.tmp, name)
        with open(p, 'w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        return p

    def donors(self, rows=None):
        return OIL.read_oil_donors(self.write('d.csv', rows if rows is not None else self.donor_rows, OIL.COLUMNS))

    def test_repo_donors_are_davids_table(self):
        got = self.donors()
        self.assertEqual({c: (r['base_donor'], r['oil_donor']) for c, r in got.items()}, B8)
        self.assertTrue(all(r['decided_by'] == 'David' and r['decided_at'] == '2026-10-24' for r in got.values()))

    def test_repo_oil_check_passes(self):
        got = OIL.read_oil_check(os.path.join(CFG, 'oil_check_codes.csv'), self.donors())
        resolved = {c for c, r in got.items() if r['flag'] == OIL.FLAG_RESOLVED}
        self.assertEqual(resolved, {'IRQ', 'KWT', 'OMN', 'AZE', 'COG', 'GAB', 'GNQ', 'BHR', 'TCD'})
        self.assertEqual(set(got) - resolved, {'CPV', 'NAM', 'SWZ'})

    def test_donor_mutations_fail(self):
        muts = [lambda r: r.update(decided_by=''), lambda r: r.update(sector='C19'),
                lambda r: r.update(oil_donor=r['base_donor']), lambda r: r.update(oil_donor=r['code']),
                lambda r: r.update(basis='')]
        for m in muts:
            rows = [dict(r) for r in self.donor_rows]
            m(rows[0])
            with self.assertRaises(ValueError):
                self.donors(rows)
        with self.assertRaises(ValueError):
            self.donors(self.donor_rows + [dict(self.donor_rows[0])])

    def test_oil_check_mutations_fail(self):
        donors = self.donors()

        def run(rows):
            return OIL.read_oil_check(self.write('c.csv', rows, OIL.CHECK_COLUMNS), donors)

        rows = [dict(r) for r in self.check_rows]
        i = next(k for k, r in enumerate(rows) if r['code'] == 'IRQ')
        rows[i].update(flag=OIL.FLAG_OPEN, resolved_by='', resolved_at='', resolution='')
        with self.assertRaises(ValueError):          # a switched member left open
            run(rows)
        rows = [dict(r) for r in self.check_rows]
        rows[i]['resolved_by'] = ''
        with self.assertRaises(ValueError):          # resolved without a name
            run(rows)
        rows = [dict(r) for r in self.check_rows]
        j = next(k for k, r in enumerate(rows) if r['code'] == 'CPV')
        rows[j].update(flag=OIL.FLAG_RESOLVED, resolved_by='David', resolved_at='2026-10-24', resolution='x')
        with self.assertRaises(ValueError):          # resolved but not switched
            run(rows)
        rows = [dict(r) for r in self.check_rows]
        rows[j]['flag'] = 'OIL-CHECK-OTHER'
        with self.assertRaises(ValueError):
            run(rows)


if __name__ == '__main__':
    unittest.main()
