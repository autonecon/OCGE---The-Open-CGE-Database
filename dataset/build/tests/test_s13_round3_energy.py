"""Round 3 final QA 2 items 2, 3 and 5: held cells in the fit, the subsidy users, the own-use cap at basic values,
the power cell targets and the crude smear users (small hand-made cases, no stage outputs)."""
import os
import sys
import unittest

import numpy as np
import pandas as pd

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BUILD)
from s13_fit.fit import Column, Problem, solve  # noqa: E402
from s13_fit import method as M  # noqa: E402
from s13_fit import energy as EN  # noqa: E402
from s13_fit import checks as K  # noqa: E402


class HeldCells(unittest.TestCase):
    def _problem(self, held):
        # two goods (rows MC_a, MC_b), two fixed-total final columns; good a's row is held at 10, b at 20
        # column p buys a and b; column q buys a and b; q's cell a is held at `held` (basic, power 1.25)
        tau = 1.25
        cp = Column('p', [0, 1], [1.0, 1.0], [4.0, 6.0], total=15.0)
        cq = Column('q', [0, 1], [1.0 / tau, 1.0], [0.0 if held else 5.0, 5.0], total=15.75,
                    fixed_basic=[held, 0.0] if held else None)
        return Problem(['MC_a', 'MC_b'], [-10.0, -20.0], [cp, cq])

    def test_held_cell_stays_and_rows_clear(self):
        P = self._problem(3.0)
        R = solve(P)
        self.assertTrue(R['ok'])
        q = R['vals']['q']
        self.assertAlmostEqual(q[0] / 1.25, 3.0, places=9)        # held basic value
        self.assertAlmostEqual(R['vals']['p'][0] + q[0] / 1.25, 10.0, places=7)
        self.assertAlmostEqual(q.sum(), 15.75, places=7)

    def test_bad_held_cell_rejected(self):
        with self.assertRaises(ValueError):
            Column('x', [0], [1.0], [1.0], total=1.0, fixed_basic=[0.5])     # held cell with an adjustable prior


class SubsidyUsers(unittest.TestCase):
    def test_energy_columns_left_out_and_money_held(self):
        sectors = ['gas', 'ely', 'crp']
        cols = sectors + ['p', 'g', 'i']
        idx = {c: i for i, c in enumerate(sectors)}
        n, J = 3, 6
        pv = {'dom': np.zeros((n, J)), 'imp': np.zeros((n, J))}
        pv['dom'][0, :] = [50.0, 30.0, 10.0, 10.0, 0.0, 0.0]     # gas: own use, power, farm, households
        tau = np.ones((n, J))
        tt = tau.copy()
        tgt = np.array([100.0, np.nan, np.nan])
        f = M.book_fuel_subsidies(pv, tau, tt, idx, cols, sectors, tgt, np.zeros(n), np.zeros(n), {'gas': 5.0}, exclude_energy=True)['gas']
        self.assertTrue(f['money_held'])
        self.assertFalse(f['mask'][0] or f['mask'][1])
        self.assertEqual(tau[0, 0], 1.0)                          # own use not subsidised
        self.assertEqual(tau[0, 1], 1.0)                          # power not subsidised
        basic = pv['dom'][0, :] / tau[0, :]
        self.assertAlmostEqual(f['rho'] * basic[f['mask']].sum(), 5.0, places=9)

    def test_only_energy_buyers_falls_back(self):
        sectors = ['gas', 'ely']
        cols = sectors + ['p', 'g', 'i']
        idx = {c: i for i, c in enumerate(sectors)}
        pv = {'dom': np.zeros((2, 5)), 'imp': np.zeros((2, 5))}
        pv['dom'][0, 1] = 40.0
        tau = np.ones((2, 5))
        f = M.book_fuel_subsidies(pv, tau, tau.copy(), idx, cols, sectors, np.array([40.0, np.nan]), np.zeros(2), np.zeros(2),
                                  {'gas': 4.0}, exclude_energy=True)['gas']
        self.assertEqual(f['status'], 'booked')
        self.assertTrue(f['mask'][1])


class OwnUseBasic(unittest.TestCase):
    def test_cap_on_basic_value(self):
        sectors = ['gas', 'crp']
        cols = sectors + ['p', 'g', 'i']
        idx = {c: i for i, c in enumerate(sectors)}
        pv = {'dom': np.zeros((2, 5)), 'imp': np.zeros((2, 5))}
        pv['dom'][0, 0] = 5.0           # own use at purchasers' value 5, basic 50 (a 90% subsidy)
        pv['dom'][0, 1] = 20.0
        pv['dom'][1, 0] = 10.0
        tau = np.ones((2, 5))
        tau[0, 0] = 0.1
        va = np.array([85.0, 0.0])
        live = np.array([True, True, True, False, False])
        EN.cap_own_use(pv, tau, idx, cols, np.array([np.nan, np.nan]), va, {'gas': 0.1}, live, basic=True)
        col = pv['dom'][:, 0].sum() + va[0]
        self.assertAlmostEqual(pv['dom'][0, 0] / tau[0, 0] / col, 0.1, places=9)


class PowerCells(unittest.TestCase):
    def test_targets_and_room(self):
        cs = pd.DataFrame([dict(region='AAA', column='ely', crude_value_dom_musd=60.0, crude_value_imp_musd=0.0, gas_value_dom_musd=40.0,
                                gas_value_imp_musd=0.0, pet_value_dom_musd=10.0, pet_value_imp_musd=0.0),
                           dict(region='BBB', column='ely', crude_value_dom_musd=1.0, crude_value_imp_musd=0.0, gas_value_dom_musd=99.0,
                                gas_value_imp_musd=0.0, pet_value_dom_musd=0.0, pet_value_imp_musd=0.0)])
        t = M.power_cell_targets(cs, {'AAA', 'BBB'})
        self.assertIn('AAA', t)
        self.assertNotIn('BBB', t)                                 # crude below 5% of the fuel value
        sectors = ['oil', 'gas', 'pet', 'ely']
        idx = {c: i for i, c in enumerate(sectors)}
        pv = {'dom': np.ones((4, 7)), 'imp': np.ones((4, 7))}
        tau = np.ones((4, 7))
        status = {c: 'prior' for c in sectors}
        held, rows = M.hold_power_cells(pv, tau, idx, status, np.array([100.0, 50.0, 10.0, np.nan]), np.zeros(4), np.zeros(4), t['AAA'])
        self.assertAlmostEqual(held[('dom', 0, 3)], 60.0)
        self.assertAlmostEqual(held[('dom', 1, 3)], 40.0)
        self.assertAlmostEqual(held[('dom', 2, 3)], 9.0)           # 10 held at 90% of the pet row
        self.assertEqual(held[('imp', 0, 3)], 0.0)

    def test_power_cells_held_check(self):
        io = pd.DataFrame({'region': ['AAA', 'AAA'], 'row': ['dom_oil', 'imp_oil'], 'ely': [59.0, 1.0]})
        rows = pd.DataFrame([dict(region='AAA', good='oil', kind='dom', s11_musd=60.0, held_musd=60.0, row_musd=100.0, status='held'),
                             dict(region='AAA', good='oil', kind='imp', s11_musd=0.0, held_musd=0.0, row_musd=0.0, status='held')])
        n, _, F = K.power_cells_held(io, rows, ['AAA'])
        self.assertEqual(n, 0)
        io.loc[0, 'ely'] = 50.0
        self.assertEqual(K.power_cells_held(io, rows, ['AAA'])[0], 1)


class CrudeUsers(unittest.TestCase):
    def test_smear_structure_on_crude_users(self):
        sectors = ['oil', 'gas', 'pet', 'air']
        cols = sectors + ['p', 'g', 'i']
        rows = []
        for good, vals in (('oil', [1, 0, 6, 0, 0, 0, 0]), ('gas', [0, 1, 1, 2, 3, 0, 0])):
            for k in ('dom', 'imp'):
                rows.append(dict(row=f'{k}_{good}', **dict(zip(cols, vals))))
        for good in ('pet', 'air'):
            for k in ('dom', 'imp'):
                rows.append(dict(row=f'{k}_{good}', **dict(zip(cols, [1] * 7))))
        io = pd.DataFrame(rows)
        w = M.world_energy_structure(io, sectors, crude_cols={'pet', 'oil'})['oil']
        self.assertEqual(w[cols.index('air')], 0.0)
        self.assertEqual(w[cols.index('p')], 0.0)
        self.assertAlmostEqual(w.sum(), 1.0)
        self.assertEqual(M._crude_buyer('oil', {'pet'}, {c: i for i, c in enumerate(sectors)}, {'pet': 'prior'}), 2)
        self.assertIsNone(M._crude_buyer('gas', {'pet'}, {}, {}))


if __name__ == '__main__':
    unittest.main()
