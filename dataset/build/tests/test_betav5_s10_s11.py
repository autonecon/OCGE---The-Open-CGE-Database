"""Unit tests for the beta v5 S10-S11 fixes (David's package approval, 27 Oct 2026 08:39 UTC).

S10: E6 (NEERS at the base-year exchange rate), S5 (quota tariffs scaled to collected duty), K and S5-BGD (sourced line
overrides, off until a source is on disk). S11: E1 + R (bounded RAS, route screen, holds), A (contract routes out of the
regulated cap), E2 (Census route holds), E3 (physical routes), E4 (user exclusions), I (re-export rule override),
N2 (NGPL feedstock), E7 / E8 (switches off until sourced).

Every helper is called on a good input (it must give the hand-computed value) and on a mutated input (it must fail or
move), and each choice file must load with the new rows. No stage is run.

Run from dataset/build:  python3 -m unittest tests.test_betav5_s10_s11 -v
"""
import csv
import os
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BUILD)

from s10_tariffs import build as B10  # noqa: E402
from s10_tariffs import config as C10  # noqa: E402
from s10_tariffs import energy_tax as ET10  # noqa: E402
from s10_tariffs import overrides as OV10  # noqa: E402
from s11_energy import config as C11  # noqa: E402
from s11_energy import domestic as DOM11  # noqa: E402
from s11_energy import method as M11  # noqa: E402
from s11_energy import sources as SRC11  # noqa: E402

DATA = os.path.join(os.path.dirname(BUILD), 'data')


def write_csv(path, header, rows):
    with open(path, 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


# ------------------------------------------------------------------ S10
class ChoicesLoadTest(unittest.TestCase):
    """The new choice rows load, with the decided defaults."""

    def test_s10(self):
        ch = C10.load_choices()
        self.assertEqual(ch['energy_tax_fx'], 'lcu_neers_year_to_usd_base_year_wdi')
        self.assertEqual(ch['tariff_collected_scale'], 'off')       # David 2026-10-27 11:12 UTC: off for beta v5
        self.assertEqual(ch['tariff_pak_lng_concession'], 'off')
        self.assertEqual(ch['tariff_bgd_nbr_fuel'], 'off')

    def test_s11(self):
        ch = C11.load_choices()
        for name in ('ras_route_caps', 'physical_energy_routes', 'gas_users_excluded', 'contract_routes_out_of_parity_cap',
                     'census_route_hold', 'reexport_rule_override'):
            self.assertTrue(C11.switched_on(ch, name), name)
        for name in ('dza_gas_price_creg', 'chn_ely_own_use_cec', 'ngpl_feedstock'):
            self.assertFalse(C11.switched_on(ch, name), name)
        self.assertIn('hold', C11.REVIEW_ACTIONS)


class EnergyTaxFxTest(unittest.TestCase):
    """E6: the NEERS-year USD value times LCU per USD (NEERS year) / LCU per USD (base year)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wdi = os.path.join(self.tmp, 'wdi.csv')
        write_csv(self.wdi, ['series', 'iso3', 'year', 'value'], [
            ['PA.NUS.FCRF', 'DEU', '2021', '0.85'], ['PA.NUS.FCRF', 'DEU', '2022', '0.95'],
            ['PA.NUS.FCRF', 'TUR', '2021', '8.85'], ['PA.NUS.FCRF', 'TUR', '2022', '16.55'],
            ['PA.NUS.FCRF', 'USA', '2021', '1'], ['PA.NUS.FCRF', 'USA', '2022', '1'],
            ['NE.GDI.FTOT.CD', 'DEU', '2021', '5'], ['PA.NUS.FCRF', 'XXX', '2021', '2']])
        # one ROAD diesel row per country: 10 EUR per GJ on 1,000 TJ
        self.neer = {(2021, iso, 'ROAD', 'DIES'): {'TAXBTJ': 1000.0, 'TOTTAX': 10.0} for iso in ('DEU', 'TUR', 'USA', 'OECD00')}
        self.fx = {2021: 1.18}

    def test_ratios(self):
        r = ET10.lcu_ratios(self.wdi, (2021,), 2022)
        self.assertAlmostEqual(r[('DEU', 2021)], 0.85 / 0.95)
        self.assertAlmostEqual(r[('TUR', 2021)], 8.85 / 16.55)
        self.assertAlmostEqual(r[('USA', 2021)], 1.0)
        self.assertNotIn(('XXX', 2021), r)                      # no base-year rate

    def test_revenues(self):
        old = ET10.revenues(self.neer, self.fx, 'neer_2021', 'taxes_only')
        new = ET10.revenues(self.neer, self.fx, 'neer_2021', 'taxes_only', lcu_ratio=ET10.lcu_ratios(self.wdi, (2021,), 2022))
        key = ('ROAD', 'pet') if ('ROAD', 'pet') in old['DEU'] else next(iter(old['DEU']))
        self.assertAlmostEqual(old['DEU'][key][0], 1.18 * 10.0)            # 10 EUR/GJ x 1,000 TJ = 10 m EUR
        self.assertAlmostEqual(new['DEU'][key][0], 1.18 * 10.0 * 0.85 / 0.95)
        self.assertAlmostEqual(new['USA'][key][0], old['USA'][key][0])     # USD country unchanged
        self.assertAlmostEqual(new['DEU'][key][2], old['DEU'][key][2])     # the TJ base is not converted
        self.assertIn('OECD00', old)
        self.assertNotIn('OECD00', new)                                    # aggregate without a WDI rate left out


class _Acc:
    pass


class CollectedScaleTest(unittest.TestCase):
    """S5: listed sectors x min(1, collected / booked over all goods); other cells untouched."""

    def tb(self):
        t = B10.TariffBuild.__new__(B10.TariffBuild)
        t.rate = {('CHE', 'DEU', 'fbt'): 30.0, ('CHE', 'DEU', 'crp'): 20.0, ('CHE', 'DEU', 'mac'): 1.0,
                  ('TUR', 'DEU', 'fbt'): 10.0}
        return t

    def test_scale(self):
        t = self.tb()
        vcif = {k: 100.0 for k in t.rate}
        rows = [{'importer': 'CHE', 'sector': 'fbt'}, {'importer': 'CHE', 'sector': 'crp'}]
        d = t.scale_to_collected(rows, {'CHE': 25.5}, vcif)['CHE']
        self.assertAlmostEqual(d['booked_before'], 51.0)
        self.assertAlmostEqual(d['factor'], 0.5)
        self.assertAlmostEqual(t.rate[('CHE', 'DEU', 'fbt')], 15.0)
        self.assertAlmostEqual(t.rate[('CHE', 'DEU', 'crp')], 10.0)
        self.assertAlmostEqual(t.rate[('CHE', 'DEU', 'mac')], 1.0)          # unlisted sector
        self.assertAlmostEqual(t.rate[('TUR', 'DEU', 'fbt')], 10.0)         # unlisted importer
        self.assertAlmostEqual(d['booked_after'], 26.0)
        self.assertEqual(t.collected_scale[('CHE', 'DEU', 'fbt')], 0.5)

    def test_factor_at_most_one(self):
        t = self.tb()
        d = t.scale_to_collected([{'importer': 'CHE', 'sector': 'fbt'}], {'CHE': 999.0}, {k: 100.0 for k in t.rate})['CHE']
        self.assertEqual(d['factor'], 1.0)
        self.assertAlmostEqual(t.rate[('CHE', 'DEU', 'fbt')], 30.0)

    def test_missing_collected_raises(self):
        t = self.tb()
        with self.assertRaises(SystemExit):
            t.scale_to_collected([{'importer': 'CHE', 'sector': 'fbt'}], {}, {k: 100.0 for k in t.rate})

    def test_config_rows(self):
        rows = C10.read_table('tariff_collected_scale.csv', ('importer', 'sector', 'reason', 'source'))
        self.assertEqual({(r['importer'], r['sector']) for r in rows}, {('CHE', 'crp'), ('CHE', 'fbt'), ('TUR', 'crp'), ('TUR', 'fbt')})


class SourcedLinesTest(unittest.TestCase):
    """K and S5-BGD: rows apply only when their switch is on, and never with a pending source."""

    def test_off_gives_nothing(self):
        self.assertEqual(OV10.sourced_lines(C10.load_choices()), [])

    def test_on_with_pending_source_raises(self):
        ch = dict(C10.load_choices(), tariff_pak_lng_concession='fbr_fifth_schedule_rows')
        with self.assertRaises(SystemExit):
            OV10.sourced_lines(ch)

    def test_on_without_rows_raises(self):
        ch = dict(C10.load_choices(), tariff_bgd_nbr_fuel='nbr_2022_schedule_rows')
        with self.assertRaises(SystemExit):
            OV10.sourced_lines(ch)

    def test_on_with_source(self):
        tmp = os.path.join(tempfile.mkdtemp(), 'lines.csv')
        write_csv(tmp, OV10.SOURCED_LINE_COLUMNS, [['PAK', '271111', '5', 'tariff_pak_lng_concession', 'pak_lng_concession',
                                                    'FBR Customs Tariff 2022-23 Fifth Schedule p.x', '']])
        ch = dict(C10.load_choices(), tariff_pak_lng_concession='fbr_fifth_schedule_rows')
        self.assertEqual(OV10.sourced_lines(ch, path=tmp), [('PAK', '271111', 5.0, 'pak_lng_concession')])


# ------------------------------------------------------------------ S11
class CappedRasTest(unittest.TestCase):
    """E1 + R: bounds bind, totals hold, holds stay fixed, and an exporter whose routes are all capped spills."""

    def test_cap_binds_and_totals_hold(self):
        A = np.array([[0.0, 1.0, 1.0], [1.0, 0.0, 1.0], [1.0, 1.0, 0.0]])
        rows, cols = np.array([6.0, 3.0, 3.0]), np.array([3.0, 5.0, 4.0])
        cap = np.full((3, 3), np.inf)
        cap[0, 1] = 2.5
        B, fixed, spilled, _r, err = M11.capped_ras(A, rows, cols, cap)
        self.assertLess(err, 1e-9)
        self.assertAlmostEqual(B[0, 1], 2.5)
        self.assertTrue(fixed[0, 1])
        np.testing.assert_allclose(B.sum(1), rows, rtol=1e-8)
        np.testing.assert_allclose(B.sum(0), cols, rtol=1e-8)
        self.assertFalse(spilled.any())
        B0, *_ = M11.ras(A, rows, cols)                       # unbounded: the route takes more than its bound
        self.assertGreater(B0[0, 1], 3.0)                    # 3.40

    def test_hold(self):
        A = np.array([[0.0, 1.0, 1.0], [1.0, 0.0, 1.0], [1.0, 1.0, 0.0]])
        rows, cols = np.array([4.0, 4.0, 4.0]), np.array([4.0, 4.0, 4.0])
        hold = np.zeros((3, 3), bool)
        hold[0, 1] = True
        A[0, 1] = 0.5
        B, fixed, *_ = M11.capped_ras(A, rows, cols, np.full((3, 3), np.inf), hold=hold)
        self.assertAlmostEqual(B[0, 1], 0.5)
        np.testing.assert_allclose(B.sum(1), rows, rtol=1e-8)

    def test_spill(self):
        # exporter 0 has one route (to 1) capped at 1, but exports 5: the bound cannot carry it, so its zero to 2 spills
        A = np.array([[0.0, 1.0, 0.0], [1.0, 0.0, 1.0], [1.0, 1.0, 0.0]])
        rows, cols = np.array([5.0, 2.0, 2.0]), np.array([2.0, 2.0, 5.0])
        cap = np.full((3, 3), np.inf)
        cap[0, 1] = 1.0
        seed = 1e-6 * np.ones((3, 3))
        ok = ~np.eye(3, dtype=bool)
        B, fixed, spilled, _r, err = M11.capped_ras(A, rows, cols, cap, spill_ok=ok, seed=seed)
        self.assertTrue(spilled[0, 2])
        self.assertLess(err, 1e-9)
        self.assertAlmostEqual(B[0, 1], 1.0)
        self.assertAlmostEqual(B[0, 2], 4.0)
        np.testing.assert_allclose(B.sum(1), rows, rtol=1e-8)
        # with the spill route blocked there is no solution and the error is reported, not hidden
        ok[0, 2] = False
        *_x, err2 = M11.capped_ras(A, rows, cols, cap, spill_ok=ok, seed=seed)
        self.assertGreater(err2, 1e-6)

    def test_route_caps(self):
        A0 = np.array([[0.0, 10.0, 0.0], [2.0, 0.0, 1.0], [0.0, 0.0, 0.0]])
        px = np.full((3, 3), 50.0)                               # 50 USD per unit: 100 USD m = 2 units
        mo = np.array([False, False, True])
        cap = M11.route_caps(A0, px, 'oil', ('oil', 'pet'), 3.0, 100.0, mo, 20.0, exempt={(1, 0)})
        self.assertAlmostEqual(cap[0, 1], 30.0)                  # 3 x prior
        self.assertTrue(np.isinf(cap[1, 0]))                     # exempt
        self.assertAlmostEqual(cap[1, 2], 3.0)                   # max(3 x 1, floor 2 units), below 20 x 1 for a mirror-only partner
        self.assertTrue(np.isinf(cap[0, 2]))                     # a zero prior has no bound
        cap_gas = M11.route_caps(A0, px, 'gas', ('oil', 'pet'), 3.0, 100.0, mo, 20.0, exempt=set())
        self.assertTrue(np.isinf(cap_gas[0, 1]))                 # gas: no 3x bound
        self.assertAlmostEqual(cap_gas[1, 2], 20.0)              # mirror-only partner: 20 x prior

    def test_volume_cap_breaches(self):
        A0 = np.array([[0.0, 10.0], [1.0, 0.0]])
        A1 = np.array([[0.0, 40.0], [1.0, 0.0]])
        fob = A1 * 50.0
        hit = M11.volume_cap_breaches(A0, A1, fob, set(), 100.0, ('oil', 'pet'), 'oil', 3.0, np.zeros(2, bool), 20.0)
        self.assertEqual([(i, j) for i, j, *_ in hit], [(0, 1)])
        self.assertEqual(M11.volume_cap_breaches(A0, A1, fob, {(0, 1)}, 100.0, ('oil', 'pet'), 'oil', 3.0, np.zeros(2, bool), 20.0), [])
        self.assertEqual(M11.volume_cap_breaches(A0, A1, fob, set(), 100.0, ('oil', 'pet'), 'gas', 3.0, np.zeros(2, bool), 20.0), [])


class ReporterTest(unittest.TestCase):
    """R: the mirror-only screen reads the Comtrade 2022 X files; large reporters are in, Syria and Yemen are not."""

    def test_reporters(self):
        folder = os.path.join(DATA, 'un_comtrade_rx_2022')
        if not os.path.exists(os.path.join(folder, 'comtrade_X_2709_2022.json')):
            self.skipTest('Comtrade files not on disk')
        rep = SRC11.comtrade_energy_reporters_2022(folder, {'760': 'SYR', '887': 'YEM', '682': 'SAU'})
        self.assertIn('USA', rep)                                # Comtrade code 842
        self.assertIn('NOR', rep)                                # 579
        self.assertIn('SAU', rep)
        self.assertNotIn('SYR', rep)
        self.assertNotIn('YEM', rep)


class CensusTest(unittest.TestCase):
    """E2: Census IMDB customs value summed over rate provisions."""

    def test_sum(self):
        tmp = os.path.join(tempfile.mkdtemp(), 'c.csv')
        write_csv(tmp, ['hs6', 'cty', 'rate_prov', 'con_val', 'dut_val', 'cal_dut', 'con_cif', 'gen_val'],
                  [['271111', '2740', '10', '1000000000', '0', '0', '1', '1'], ['271111', '2740', '18', '500000', '0', '0', '1', '1'],
                   ['271121', '2740', '10', '2000000', '0', '0', '1', '1']])
        v = SRC11.census_imdb_values_2022(tmp)
        self.assertAlmostEqual(v[('271111', '2740')], 1000.5)
        self.assertAlmostEqual(v[('271121', '2740')], 2.0)

    def test_config(self):
        rows = C11.read_table('census_route_hold.csv', C11.CENSUS_HOLD_COLUMNS)
        self.assertEqual({r['exporter'] for r in rows}, {'TTO', 'NGA', 'OMN', 'RUS'})
        self.assertTrue(all(r['importer'] == 'USA' for r in rows))


class ContractParityTest(unittest.TestCase):
    """A: a contract route is valued at the exporter's reference in the cap price; other routes keep their value."""

    def test_price(self):
        vol = np.array([[0.0, 10.0, 0.0], [0.0, 0.0, 0.0], [0.0, 10.0, 0.0]])
        pxr = np.array([[0.0, 1.0, 0.0], [0.0, 0.0, 0.0], [0.0, 6.0, 0.0]])
        vmsb = vol * pxr * 1.1                                    # 10% wedge
        ref = np.array([5.0, 0.0, 6.0])
        plain = DOM11.contract_free_import_price(vmsb, vol, pxr, ref, [])
        cap = DOM11.contract_free_import_price(vmsb, vol, pxr, ref, [(0, 1)])
        self.assertAlmostEqual(plain[1], (11.0 + 66.0) / 20.0)
        self.assertAlmostEqual(cap[1], (55.0 + 66.0) / 20.0)
        self.assertTrue(np.isnan(cap[0]))


class PhysicalRoutesTest(unittest.TestCase):
    """E3: the pipeline-only table lists CAN to the USA only and no gas exports for SAU and BHR."""

    def test_table(self):
        rows = {r['exporter']: r['importers'] for r in C11.read_table('gas_pipeline_only.csv', C11.PIPELINE_ONLY_COLUMNS)}
        self.assertEqual(rows, {'CAN': 'USA', 'SAU': '', 'BHR': ''})


class UserExclusionTest(unittest.TestCase):
    """E4: excluded users' cells go pro rata to the other buying industries; final demand, pet and gaps take nothing."""

    def test_move(self):
        users = ['ely', 'chm', 'pet', 'trd', 'p', 'X']
        io = pd.DataFrame([dict(region='SAU', row='dom_gas', ely=30.0, chm=10.0, pet=5.0, trd=4.0, p=6.0, X=50.0),
                           dict(region='SAU', row='imp_gas', ely=0.0, chm=0.0, pet=0.0, trd=0.0, p=0.0, X=0.0),
                           dict(region='QAT', row='dom_gas', ely=1.0, chm=1.0, pet=1.0, trd=1.0, p=1.0, X=1.0)])
        d = M11.move_user_cells(io, 'SAU', 'gas', ['trd', 'p'], users)
        self.assertAlmostEqual(d['moved'], 10.0)
        r = io.iloc[0]
        self.assertAlmostEqual(r['ely'], 30.0 + 7.5)
        self.assertAlmostEqual(r['chm'], 10.0 + 2.5)
        self.assertEqual((r['trd'], r['p'], r['pet'], r['X']), (0.0, 0.0, 5.0, 50.0))
        self.assertLess(d['row_gap'], 1e-9)
        self.assertEqual(io.iloc[2]['p'], 1.0)                    # other region untouched

    def test_no_taker_raises(self):
        io = pd.DataFrame([dict(region='SAU', row='dom_gas', trd=4.0, p=6.0, X=1.0)])
        with self.assertRaises(SystemExit):
            M11.move_user_cells(io, 'SAU', 'gas', ['trd', 'p'], ['trd', 'p', 'X'])


class OwnUseOverrideTest(unittest.TestCase):
    """E8: off gives nothing; on with the pending row stops; on with a sourced row replaces the share."""

    def rows(self):
        return C11.read_table('own_use_overrides.csv', C11.OWN_USE_OVERRIDE_COLUMNS)

    def test_off(self):
        self.assertEqual(M11.own_use_override_rows(self.rows(), C11.load_choices(), C11.switched_on), [])

    def test_on_pending_raises(self):
        ch = C11.load_choices()
        ch['chn_ely_own_use_cec'] = dict(ch['chn_ely_own_use_cec'], value=C11.CHOICES['chn_ely_own_use_cec'])
        with self.assertRaises(SystemExit):
            M11.own_use_override_rows(self.rows(), ch, C11.switched_on)

    def test_apply(self):
        OU = pd.DataFrame([dict(region='CHN', commodity='ely', own_use_share=0.05, basis='unsd_2022', s11_output_value_musd=100.0,
                                own_use_value_musd=5.0)])
        out = M11.apply_own_use_overrides(OU, [('CHN', 'ely', 0.04, 'CEC 2022')])
        self.assertAlmostEqual(out.iloc[0]['own_use_value_musd'], 4.0)
        self.assertEqual(out.iloc[0]['basis'], 'sourced_override')
        self.assertAlmostEqual(OU.iloc[0]['own_use_share'], 0.05)     # input not changed


class DzaCregSwitchTest(unittest.TestCase):
    """E7: the CREG row is dropped while off and replaces the 2010 row when on."""

    def test_rows(self):
        rows = C11.read_table('domestic_price_sources.csv', ('commodity', 'region', 'source', 'series', 'price_level',
                                                             'decided_by', 'decided_at', 'basis'))
        ch = C11.load_choices()
        dza = [h['series'] for h in C11.price_source_rows(rows, ch) if (h['commodity'], h['region']) == ('gas', 'DZA')]
        self.assertEqual(dza, ['item:dza_gas_industry_2010'])
        ch['dza_gas_price_creg'] = dict(ch['dza_gas_price_creg'], value=C11.CHOICES['dza_gas_price_creg'])
        dza = [h['series'] for h in C11.price_source_rows(rows, ch) if (h['commodity'], h['region']) == ('gas', 'DZA')]
        self.assertEqual(dza, ['item:dza_gas_creg_2022'])


class RouteReviewRowsTest(unittest.TestCase):
    """R: the new review rows are present with the right actions."""

    def test_rows(self):
        rows = {(r['commodity'], r['exporter'], r['importer']): r['action'] for r in C11.read_table('route_review.csv', C11.REVIEW_COLUMNS)}
        self.assertEqual(rows[('oil', 'IRN', 'TWN')], 'block')
        self.assertEqual(rows[('pet', 'TUR', 'SYR')], 'hold')
        self.assertEqual(rows[('pet', 'RUS', 'YEM')], 'hold')
        self.assertEqual(rows[('gas', 'QAT', 'KWT')], 'feasible')
        self.assertEqual(rows[('oil', 'IRN', 'CHN')], 'reference')
        self.assertEqual(rows[('pet', 'UZB', 'AFG')], 'reference')
        self.assertTrue(all(a in C11.REVIEW_ACTIONS for a in rows.values()))



class NgplHeatTest(unittest.TestCase):
    """N2: EIA NGPL MMBtu per barrel from the bulk file, the world series under WORL; the choice takes both rules."""

    def test_heat(self):
        lines = ['{"series_id":"INTL.58-1-NGA-QBTU.A","geography":"NGA","data":[["2022",0.1032],["2021",0.1]]}',
                 '{"series_id":"INTL.58-1-NGA-TBPD.A","geography":"NGA","data":[["2022",65]]}',
                 '{"series_id":"INTL.58-1-WORL-QBTU.A","geography":"WLD","data":[["2022",18.844]]}',
                 '{"series_id":"INTL.58-1-WORL-TBPD.A","geography":"WLD","data":[["2022",13083.3]]}',
                 '{"series_id":"INTL.57-1-NGA-TBPD.A","geography":"NGA","data":[["2022",1400]]}',
                 '{"series_id":"INTL.58-1-GHA-QBTU.A","geography":"GHA","data":[["2022",null]]}']
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'INTL.txt')
            with open(path, 'w') as fh:
                fh.write('\n'.join(lines) + '\n')
            h = SRC11.eia_ngpl_heat_2022(path)
        self.assertAlmostEqual(h['NGA'], 0.1032e6 / (65 * 365), places=6)
        self.assertAlmostEqual(h['WORL'], 18.844e6 / (13083.3 * 365), places=6)
        self.assertNotIn('GHA', h)

    def test_choice(self):
        ch = C11.load_choices()
        self.assertEqual(ch['ngpl_feedstock']['value'], 'off')     # David 2026-10-27 11:12 UTC: off for beta v5
        self.assertIn(C11.NGPL_FEEDSTOCK_VALUE_SHARE, C11.ALTERNATIVES['ngpl_feedstock'])


if __name__ == '__main__':
    unittest.main()
