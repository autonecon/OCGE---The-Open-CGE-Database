"""Unit tests for the beta v5 trade fixes (S07-S09; David approved the v5 package 2026-10-27 08:39 UTC).

T1 (reexport_high_share, reexport_import_surplus, hkg_domestic_export_cap), G (gold_reexport = metal re-export, drop mode),
B (importer_floor), B2/M1/M2 (transit_import_cap v5 rows), T2 (reexport_rx_usa_bel = usa_bel_nbb, off) and M5 (S09
batis_scaling net of retrocession). Every helper is called on a good input (hand-computed value) and on a mutated input
(it must move or stop). No stage is run.

Run from dataset/build:  python3 -m unittest tests.test_betav5_trade_fixes -v
"""
import csv
import json
import os
import sys
import tempfile
import unittest

import duckdb

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BUILD)
sys.path.insert(0, os.path.join(BUILD, 'prep_trade'))

import s07_trade as S7  # noqa: E402
import s09_services as S9  # noqa: E402

CFG = os.path.join(BUILD, 'config', 's07')


def flows_con(rows, hs, prior=(), shares=()):
    con = duckdb.connect()
    con.execute('CREATE TABLE flows(exporter VARCHAR, importer VARCHAR, hs6 VARCHAR, value DOUBLE, qty DOUBLE, qty_ok BOOLEAN)')
    con.executemany('INSERT INTO flows VALUES (?, ?, ?, ?, ?, TRUE)', rows)
    con.execute('CREATE TABLE hs(hs6 VARCHAR, sector VARCHAR, agrees VARCHAR)')
    con.executemany('INSERT INTO hs VALUES (?, ?, ?)', hs)
    con.execute('CREATE TABLE prior_x(region VARCHAR, sector VARCHAR, x DOUBLE)')
    if prior:
        con.executemany('INSERT INTO prior_x VALUES (?, ?, ?)', prior)
    con.execute('CREATE TABLE rx_share(region VARCHAR, hs2 VARCHAR, share DOUBLE)')
    if shares:
        con.executemany('INSERT INTO rx_share VALUES (?, ?, ?)', shares)
    con.execute('CREATE TABLE rx_dom(region VARCHAR, hs2 VARCHAR, dom DOUBLE)')
    con.execute('CREATE TABLE intra_add(hub VARCHAR, region VARCHAR, hs6 VARCHAR, value DOUBLE)')
    return con


def flow(con, e, i, h):
    r = con.execute('SELECT value FROM flows WHERE exporter = ? AND importer = ? AND hs6 = ?', [e, i, h]).fetchone()
    return r[0] if r else 0.0


class HighShareTest(unittest.TestCase):
    """T1: a chapter with RX / X >= 0.90 is capped at BACI less Comtrade domestic exports, not at the prior."""

    def con(self):
        return flows_con(
            [('KOR', 'SAU', '890190', 100.0, 1.0), ('SAU', 'EGY', '890190', 50.0, 1.0),      # ships, 99% RX
             ('CHN', 'SAU', '850440', 100.0, 1.0), ('SAU', 'EGY', '850440', 40.0, 1.0)],     # electronics, 50% RX
            [('890190', 'shp', 'yes'), ('850440', 'elc', 'yes')],
            prior=[('SAU', 'shp', 48.0), ('SAU', 'elc', 30.0)],
            shares=[('SAU', '89', 0.99), ('SAU', '85', 0.5)])

    def test_v4_guard_keeps_ships(self):
        import baci_reexports as BR
        con = self.con()
        st = S7.apply_hub_slim(con, 'SAU', S7.identified_rx('SAU'), BR.claim_import_share('SAU'))
        self.assertAlmostEqual(st['funded'], 2.0 + 10.0)            # shp room 50 - 48; elc room 40 - 30 (share 20 binds at 10)
        self.assertAlmostEqual(flow(con, 'SAU', 'EGY', '890190'), 48.0)

    def test_high_share_relaxes_the_guard(self):
        import baci_reexports as BR
        con = self.con()
        con.execute("INSERT INTO rx_dom VALUES ('SAU', '89', 1.0)")             # Comtrade domestic ship exports 1 kUSD
        st = S7.apply_hub_slim(con, 'SAU', S7.identified_rx('SAU', 0.9), BR.claim_import_share('SAU'))
        self.assertAlmostEqual(flow(con, 'SAU', 'EGY', '890190'), 1.0)           # min(0.99 x 50, 50 - 1) = 49 out, not 2
        self.assertAlmostEqual(flow(con, 'KOR', 'EGY', '890190'), 49.0)
        self.assertAlmostEqual(flow(con, 'SAU', 'EGY', '850440'), 30.0)          # elc unchanged: 85 is below 0.90
        self.assertAlmostEqual(st['funded'], 49.0 + 10.0)
        con = self.con()                                                          # no Comtrade row for the chapter: the share
        S7.apply_hub_slim(con, 'SAU', S7.identified_rx('SAU', 0.9), BR.claim_import_share('SAU'))
        self.assertAlmostEqual(flow(con, 'SAU', 'EGY', '890190'), 0.5)

    def test_domestic_cap_binds(self):
        import baci_reexports as BR
        con = self.con()
        con.execute("INSERT INTO rx_dom VALUES ('SAU', '89', 10.0)")            # at most 50 - 10 out
        S7.apply_hub_slim(con, 'SAU', S7.identified_rx('SAU', 0.9), BR.claim_import_share('SAU'))
        self.assertAlmostEqual(flow(con, 'SAU', 'EGY', '890190'), 10.0)

    def test_high_uses_room_first(self):
        import baci_reexports as BR
        con = flows_con(
            [('CHN', 'ARE', '870323', 100.0, 1.0), ('ARE', 'IRN', '870323', 60.0, 1.0),   # 87: 0.95, same sector as 84
             ('CHN', 'ARE', '847130', 100.0, 1.0), ('ARE', 'IRN', '847130', 40.0, 1.0)],
            [('870323', 'mac', 'yes'), ('847130', 'mac', 'yes')], prior=[('ARE', 'mac', 50.0)],
            shares=[('ARE', '87', 0.95), ('ARE', '84', 0.5)])
        st = S7.apply_hub_slim(con, 'ARE', S7.identified_rx('ARE', 0.9), BR.claim_import_share('ARE'))
        self.assertAlmostEqual(st['funded'], 57.0)                   # room 100 - 50 = 50 < 57 from 87: 84 gets nothing
        self.assertAlmostEqual(flow(con, 'ARE', 'IRN', '847130'), 40.0)

    def test_default_sql_is_v4(self):
        self.assertEqual(S7.identified_rx('ARE'), S7.identified_rx('ARE', None))
        self.assertNotEqual(S7.identified_rx('ARE'), S7.identified_rx('ARE', 0.9))

    def test_load_shares_high(self):
        d = tempfile.mkdtemp()
        json.dump({'data': [{'cmdCode': '89', 'primaryValue': 99.0}, {'cmdCode': '85', 'primaryValue': 5.0}]},
                  open(os.path.join(d, 'RX_682_HS2.json'), 'w'))
        json.dump({'data': [{'cmdCode': '89', 'primaryValue': 100.0}, {'cmdCode': '85', 'primaryValue': 10.0}]},
                  open(os.path.join(d, 'X_682_HS2.json'), 'w'))
        con = duckdb.connect()
        con.execute('CREATE TABLE cc(code INTEGER, iso3 VARCHAR)')
        con.execute("INSERT INTO cc VALUES (682, 'SAU')")
        S7.load_rx_shares(con, d, {'SAU': 'SAU'})
        self.assertEqual(con.execute('SELECT COUNT(*) FROM rx_dom').fetchone()[0], 0)       # v4: USA only
        S7.load_rx_shares(con, d, {'SAU': 'SAU'}, high=0.9)
        self.assertEqual(con.execute('SELECT region, hs2, dom FROM rx_dom').fetchall(), [('SAU', '89', 0.001)])   # (100 - 99) USD


class ImportSurplusTest(unittest.TestCase):
    """T1: a non-reporter's sector with imports >= exports re-exports what it exports above the prior, at most its imports."""

    def test_surplus(self):
        import baci_reexports as BR
        con = flows_con(
            [('JPN', 'QAT', '870323', 30.0, 1.0), ('QAT', 'OMN', '870323', 20.0, 1.0),     # mvh: M 30 >= X 20
             ('CHN', 'QAT', '760110', 10.0, 1.0), ('QAT', 'IND', '760110', 25.0, 1.0),     # nfm: M 10 < X 25: real smelter
             ('QAT', 'IND', '271111', 99.0, 1.0)],                                         # gas: HS 27 out
            [('870323', 'mvh', 'yes'), ('760110', 'nfm', 'yes'), ('271111', 'gas', 'yes')], prior=[('QAT', 'mvh', 5.0)])
        st = S7.apply_rx_chunked(con, 'QAT', S7.identified_surplus('QAT'))
        self.assertAlmostEqual(st['funded'], 15.0)                   # min(20 - 5, 30)
        self.assertAlmostEqual(flow(con, 'QAT', 'OMN', '870323'), 5.0)
        self.assertAlmostEqual(flow(con, 'JPN', 'OMN', '870323'), 15.0)
        self.assertAlmostEqual(flow(con, 'JPN', 'QAT', '870323'), 15.0)
        self.assertAlmostEqual(flow(con, 'QAT', 'IND', '760110'), 25.0)
        self.assertAlmostEqual(flow(con, 'QAT', 'IND', '271111'), 99.0)

    def test_config(self):
        rows = list(csv.DictReader(open(os.path.join(CFG, 'reexport_surplus_regions.csv'))))
        self.assertEqual(tuple(rows[0]), S7.RX_SURPLUS_COLUMNS)
        self.assertEqual([r['region'] for r in rows], ['QAT', 'IRQ', 'IRN'])
        rx_codes = {int(n.split('_')[1]) for n in os.listdir(os.path.join(S7.DATA, 'un_comtrade_rx_2022', 'hs2')) if n.startswith('RX_')}
        self.assertFalse({634, 368, 364} & rx_codes)                  # none of them reports RX


class HkgDomesticCapTest(unittest.TestCase):
    """T1: HKG exports above C&SD domestic exports go to the origin; HKG imports are not debited."""

    def test_cap(self):
        import baci_reexports as BR
        con = flows_con(
            [('CHN', 'HKG', '710812', 500.0, 1.0), ('HKG', 'CHE', '710812', 300.0, 1.0), ('HKG', 'CHE', '710813', 100.0, 1.0),
             ('HKG', 'USA', '620342', 10.0, 1.0)],
            [('710812', 'nfm', 'yes'), ('710813', 'nfm', 'yes'), ('620342', 'wap', 'yes')])
        con.execute('CREATE TABLE hk_share(dest VARCHAR, hs2 VARCHAR, tx BIGINT, rx BIGINT, dx BIGINT, share DOUBLE)')
        con.executemany('INSERT INTO hk_share VALUES (?, ?, ?, ?, ?, ?)', [('CHE', '71', 0, 0, 783, 0.0)])   # 783 HK$ k = 100 kUSD
        con.execute('CREATE TABLE hk_origin(origin VARCHAR, dest VARCHAR, weight BIGINT, dest_total BIGINT)')
        con.executemany('INSERT INTO hk_origin VALUES (?, ?, ?, ?)', [('CHN', 'CHE', 3, 4)])                  # a quarter unmapped
        st = S7.apply_hub_slim(con, 'HKG', S7.identified_hk_dx(7.83), BR.claim_hk(), debit_imports=False)
        # excess 400 - 100 = 300 spread by value: 710812 225, 710813 75; three quarters to a mapped origin (CHN); CHN has
        # no 710813 import into HKG to fund it, so only 225 * 0.75 is funded
        self.assertAlmostEqual(st['funded'], 225.0 * 0.75)
        self.assertAlmostEqual(flow(con, 'HKG', 'CHE', '710812') + flow(con, 'HKG', 'CHE', '710813'), 400.0 - 225.0 * 0.75)
        self.assertAlmostEqual(flow(con, 'CHN', 'CHE', '710812'), 225.0 * 0.75)
        self.assertAlmostEqual(flow(con, 'CHN', 'HKG', '710812'), 500.0)    # no debit
        self.assertAlmostEqual(flow(con, 'HKG', 'USA', '620342'), 10.0)     # no Trade-IDDS row: untouched

    def test_debit_default(self):
        import baci_reexports as BR
        con = flows_con([('CHN', 'HKG', '710812', 500.0, 1.0), ('HKG', 'CHE', '710812', 300.0, 1.0)], [('710812', 'nfm', 'yes')])
        con.execute('CREATE TABLE hk_share(dest VARCHAR, hs2 VARCHAR, tx BIGINT, rx BIGINT, dx BIGINT, share DOUBLE)')
        con.execute("INSERT INTO hk_share VALUES ('CHE', '71', 0, 0, 0, 0.0)")
        con.execute('CREATE TABLE hk_origin(origin VARCHAR, dest VARCHAR, weight BIGINT, dest_total BIGINT)')
        con.execute("INSERT INTO hk_origin VALUES ('CHN', 'CHE', 1, 1)")
        S7.apply_hub_slim(con, 'HKG', S7.identified_hk_dx(7.83), BR.claim_hk())
        self.assertAlmostEqual(flow(con, 'CHN', 'HKG', '710812'), 200.0)    # debited as every other hub step


class TransitV5Test(unittest.TestCase):
    """B2, M1, M2: the all_lines scope and the CIF/FOB basis; the v5 file keeps the v4 rows."""

    def test_all_lines(self):
        con = flows_con([('CHN', 'KEN', '620342', 900.0, 1.0), ('ARE', 'KEN', '271000', 500.0, 1.0)],
                        [('620342', 'wap', 'yes'), ('271000', 'pet', 'yes')])
        out = S7.transit_cap(con, [('KEN', 1.1, ['27'], 'all_lines', 1.1)])          # 1.1 USD m CIF = 1,000 kUSD FOB
        self.assertAlmostEqual(out[0][2], 500.0)                    # 1000 less the 500 of energy inside the total
        self.assertAlmostEqual(flow(con, 'CHN', 'KEN', '620342'), 500.0)
        self.assertAlmostEqual(flow(con, 'ARE', 'KEN', '271000'), 500.0)
        con2 = flows_con([('CHN', 'KEN', '620342', 900.0, 1.0)], [('620342', 'wap', 'yes')])
        self.assertAlmostEqual(S7.transit_cap(con2, [('KEN', 0.3, ['27'])])[0][2], 300.0)   # v4 tuples unchanged
        with self.assertRaises(SystemExit):
            S7.transit_cap(con2, [('KEN', 0.3, ['27'], 'some', 1.0)])

    def test_v5_file(self):
        regions = {r['region'] for r in csv.DictReader(open(os.path.join(S7.STAGES, 'S01_sets_registry', 'output', 'regions.csv')))} \
            if os.path.exists(os.path.join(S7.STAGES, 'S01_sets_registry', 'output', 'regions.csv')) else None
        v4 = {r['region']: r for r in csv.DictReader(open(os.path.join(CFG, 'transit_import_caps.csv')))}
        rows = S7.read_transit_v5(os.path.join(CFG, 'transit_import_caps_v5.csv'), regions or set(v4) | {'POL', 'KEN'})
        got = {r[0]: r for r in rows}
        self.assertEqual(set(got), set(v4) | {'POL', 'KEN'})
        for reg, r in v4.items():
            if reg != 'KGZ':
                self.assertEqual(got[reg][1:], (float(r['goods_imports_musd']), r['excluded_hs_prefixes'].split(';'), 'non_excluded', 1.0))
        self.assertEqual(got['KGZ'][3], 'all_lines')
        self.assertAlmostEqual(got['KGZ'][1], 10611.93 - 1483.31 - (5623.00 - 3628.14), places=1)
        self.assertEqual((got['POL'][1], got['KEN'][1]), (381187.0, 21166.0))
        with self.assertRaises(SystemExit):
            S7.read_transit_v5(os.path.join(CFG, 'transit_import_caps_v5.csv'), set(v4))     # POL, KEN not known


class ImporterFloorTest(unittest.TestCase):
    """B: imports raised to the importer's own customs total on the partner x HS2 cells it reports above BACI."""

    def con(self):
        con = flows_con(
            [('TWN', 'CHN', '854231', 100.0, 2.0), ('TWN', 'CHN', '854232', 100.0, 2.0),    # BACI TWN 85: 200
             ('KOR', 'CHN', '854231', 300.0, 3.0),                                          # BACI KOR 85: 300
             ('MYS', 'CHN', '870323', 10.0, 1.0), ('MYS', 'USA', '850440', 7.0, 1.0),       # MYS has no 85 to CHN
             ('SAU', 'CHN', '270900', 1000.0, 10.0)],                                       # energy, excluded
            [('854231', 'elc', 'yes'), ('854232', 'elc', 'yes'), ('870323', 'mvh', 'yes'), ('850440', 'elc', 'yes'),
             ('270900', 'oil', 'yes')])
        con.execute('CREATE TABLE floor_m(region VARCHAR, partner VARCHAR, hs2 VARCHAR, value DOUBLE)')
        return con

    def test_scaled_gaps(self):
        con = self.con()
        con.executemany('INSERT INTO floor_m VALUES (?, ?, ?, ?)', [
            ('CHN', 'TWN', '85', 400.0), ('CHN', 'KOR', '85', 250.0), ('CHN', 'MYS', '85', 100.0), ('CHN', 'MYS', '87', 10.0)])
        out = S7.importer_floor(con, ['CHN'], {'CHN': ['27', '71', '99']})[0]
        # BACI 510 (outside 27), target 760: need 250; gaps TWN 200, MYS 100 (KOR is above its report); factor 250 / 300
        self.assertAlmostEqual(out['before'], 510.0)
        self.assertAlmostEqual(out['target'], 760.0)
        self.assertAlmostEqual(out['factor'], 250.0 / 300.0)
        self.assertAlmostEqual(out['added'], 250.0)
        self.assertAlmostEqual(flow(con, 'TWN', 'CHN', '854231'), 100.0 + 200.0 * 250 / 300 / 2)
        self.assertAlmostEqual(flow(con, 'KOR', 'CHN', '854231'), 300.0)            # not lowered
        self.assertAlmostEqual(flow(con, 'MYS', 'CHN', '854231'), 100.0 * 250 / 300 * 400 / 500)   # by CHN's 85 lines (854231: 400 of 500)
        self.assertAlmostEqual(flow(con, 'MYS', 'CHN', '854232'), 100.0 * 250 / 300 * 100 / 500)
        self.assertAlmostEqual(flow(con, 'SAU', 'CHN', '270900'), 1000.0)
        self.assertAlmostEqual(con.execute("SELECT qty FROM flows WHERE exporter = 'TWN' AND hs6 = '854231'").fetchone()[0],
                               2.0 * flow(con, 'TWN', 'CHN', '854231') / 100.0)

    def test_partner_cap(self):
        con = self.con()
        con.executemany('INSERT INTO floor_m VALUES (?, ?, ?, ?)', [
            ('CHN', 'TWN', '85', 400.0), ('CHN', 'KOR', '85', 250.0), ('CHN', 'MYS', '85', 100.0), ('CHN', 'MYS', '87', 10.0)])
        # TWN exports 200 before; its own customs total 250 leaves room 50 of its 200 * 250 / 300 top-up; MYS has no cap row
        out = S7.importer_floor(con, ['CHN'], {'CHN': ['27', '71', '99']}, {'TWN': 250.0, 'KOR': 10000.0})[0]
        twn_add = 200.0 * 250 / 300
        self.assertAlmostEqual(out['capped'], twn_add - 50.0)
        self.assertAlmostEqual(out['added'], 50.0 + 100.0 * 250 / 300)
        self.assertEqual([c[0] for c in out['capped_by']], ['TWN'])
        topped = {t[0]: t for t in out['topped']}                       # S07-H27: KOR is above its BACI report, so not topped up
        self.assertEqual(set(topped), {'TWN'})
        self.assertAlmostEqual(topped['TWN'][1], 250.0)                  # ends at its own customs exports, not above
        self.assertAlmostEqual(out['before'] + out['added'] + out['unplaced'] + out['capped'], out['target'])
        self.assertAlmostEqual(flow(con, 'TWN', 'CHN', '854231') + flow(con, 'TWN', 'CHN', '854232'), 250.0)   # at its cap
        self.assertAlmostEqual(flow(con, 'MYS', 'CHN', '854231'), 100.0 * 250 / 300 * 400 / 500)              # not moved up

    def test_load_partner_caps(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, 'x.json')
        row = dict(cmdCode='TOTAL', flowCode='X', partnerCode=0)
        json.dump({'data': [dict(row, reporterCode=490, primaryValue=477.8e9), dict(row, reporterCode=410, primaryValue=683.6e9),
                            dict(row, reporterCode=60, primaryValue=1.0e9)]}, open(path, 'w'))
        con = duckdb.connect()
        con.execute('CREATE TABLE cc(code INTEGER, iso3 VARCHAR)')
        con.executemany('INSERT INTO cc VALUES (?, ?)', [(490, 'S19'), (410, 'KOR'), (60, 'BMU')])
        con.execute('CREATE TABLE reg(iso3 VARCHAR, region VARCHAR)')
        con.executemany('INSERT INTO reg VALUES (?, ?)', [('S19', 'TWN'), ('KOR', 'KOR'), ('BMU', 'XNA')])
        caps, left = S7.load_partner_caps(con, path, {'XNA'})
        self.assertEqual(caps, {'TWN': 477.8e6, 'KOR': 683.6e6})     # thousand USD
        self.assertEqual(left, [(60, 'XNA')])

    def test_no_shortfall(self):
        con = self.con()
        con.execute("INSERT INTO floor_m VALUES ('CHN', 'TWN', '85', 100.0)")
        out = S7.importer_floor(con, ['CHN'], {'CHN': ['27']})[0]
        self.assertEqual(out['added'], 0.0)
        self.assertAlmostEqual(flow(con, 'TWN', 'CHN', '854231'), 100.0)

    def test_partner_exports_fallback(self):
        con = self.con()
        con.execute("INSERT INTO floor_m VALUES ('CHN', 'MYS', '85', 1000.0)")
        con.execute("DELETE FROM flows WHERE importer = 'CHN' AND substr(hs6, 1, 2) = '85'")
        S7.importer_floor(con, ['CHN'], {'CHN': ['27']})
        self.assertAlmostEqual(flow(con, 'MYS', 'CHN', '850440'), 1000.0 - 10.0)    # target 1010 less BACI 10; MYS's own 85 line

    def test_load_and_config(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, 'M_156'))
        json.dump({'data': [{'partnerCode': 0, 'primaryValue': 2000000.0}]}, open(os.path.join(d, 'M_156', 'M_156_TOTAL.json'), 'w'))
        row = dict(cmdCode='85', flowCode='M', reporterCode=156)
        json.dump({'data': [dict(row, partnerCode=0, primaryValue=1100000.0), dict(row, partnerCode=490, primaryValue=550000.0),
                            dict(row, partnerCode=156, primaryValue=110000.0), dict(row, partnerCode=899, primaryValue=11000.0)]},
                  open(os.path.join(d, 'M_156', 'M_156_85.json'), 'w'))
        json.dump({'data': [dict(row, cmdCode='27', partnerCode=682, primaryValue=500000.0)]}, open(os.path.join(d, 'M_156', 'M_156_27.json'), 'w'))
        con = duckdb.connect()
        con.execute('CREATE TABLE cc(code INTEGER, iso3 VARCHAR)')
        con.executemany('INSERT INTO cc VALUES (?, ?)', [(490, 'TWN'), (156, 'CHN'), (682, 'SAU')])
        con.execute('CREATE TABLE reg(iso3 VARCHAR, region VARCHAR)')
        con.executemany('INSERT INTO reg VALUES (?, ?)', [('TWN', 'TWN'), ('CHN', 'CHN'), ('SAU', 'SAU')])
        st = S7.load_floor_imports(con, d, [('CHN', 156, 1.1, ['27', '71', '99'])])['CHN']
        self.assertEqual([r[:3] + (round(r[3], 6),) for r in con.execute('SELECT * FROM floor_m').fetchall()], [('CHN', 'TWN', '85', 500.0)])   # USD 550,000 CIF / 1.1 = 500 kUSD
        self.assertAlmostEqual(st['own'], 100.0)
        self.assertAlmostEqual(st['unmapped'], 10.0)
        rows = S7.read_floor_rows(os.path.join(CFG, 'importer_floors.csv'), {'CHN', 'MEX'})
        self.assertEqual([(r[0], r[1], r[3]) for r in rows], [('CHN', 156, ['27', '71', '99']), ('MEX', 484, ['27', '71', '99'])])
        self.assertTrue(all(1.06 < r[2] < 1.08 for r in rows))


class MetalReexportTest(unittest.TestCase):
    """G: the ceiling max(own customs, mine + imports); drop removes the excess from both sides; reroute is P39."""

    def con(self):
        c = duckdb.connect()
        c.execute('CREATE TABLE flows (exporter VARCHAR, importer VARCHAR, hs6 VARCHAR, value DOUBLE, qty DOUBLE, qty_ok BOOLEAN)')
        c.executemany('INSERT INTO flows VALUES (?, ?, ?, ?, ?, TRUE)', [
            ('GHA', 'ARE', '710812', 600.0, 6.0), ('GHA', 'CHE', '710812', 400.0, 4.0), ('ZAF', 'GHA', '710812', 50.0, 0.5),
            ('GHA', 'ARE', '090111', 70.0, 7.0)])
        return c

    def test_drop_own_customs_ceiling(self):
        c = self.con()
        g = S7.metal_reexport(c, [('GHA', '7108', 1.0, 100.0, 400.0, 'drop')])[0]      # mine 0.1 + imports 50 < own 400
        self.assertAlmostEqual(g['ceiling'], 400.0)
        self.assertAlmostEqual(g['moved'], 600.0)
        self.assertAlmostEqual(g['after'], 400.0)
        self.assertAlmostEqual(flow(c, 'GHA', 'ARE', '710812') / flow(c, 'GHA', 'CHE', '710812'), 1.5)
        total = c.execute("SELECT SUM(value) FROM flows WHERE hs6 = '710812'").fetchone()[0]
        self.assertAlmostEqual(total, 1050.0 - 600.0)                # dropped from both sides
        self.assertAlmostEqual(flow(c, 'GHA', 'ARE', '090111'), 70.0)

    def test_mine_ceiling_and_no_move(self):
        c = self.con()
        g = S7.metal_reexport(c, [('GHA', '7108', 10.0, 30.0, 0.0, 'drop')])[0]       # mine 0.3 + imports 50
        self.assertAlmostEqual(g['ceiling'], 50.3)
        c = self.con()
        g = S7.metal_reexport(c, [('GHA', '7108', 0.0, 0.0, 5000.0, 'drop')])[0]
        self.assertEqual(g['moved'], 0.0)

    def test_reroute_matches_p39(self):
        c1, c2 = self.con(), self.con()
        S7.gold_reexport(c1, [('GHA', '7108', 2.0, 'ZAF')], 50.0)
        S7.metal_reexport(c2, [('GHA', '7108', 2.0, 50.0, 0.0, 'ZAF')])
        q = 'SELECT exporter, importer, hs6, value FROM flows ORDER BY 1, 2, 3'
        for a, b in zip(c1.execute(q).fetchall(), c2.execute(q).fetchall()):
            self.assertEqual(a[:3], b[:3])
            self.assertAlmostEqual(a[3], b[3])

    def test_config(self):
        rows = S7.read_metal_rows(os.path.join(CFG, 'metal_reexport_2022.csv'),
                                  {'UGA', 'COD', 'COG', 'GHA', 'MLI', 'BFA', 'GIN', 'NER', 'ZWE', 'ZMB', 'MNG', 'MRT', 'NAM', 'TGO'})
        got = {(r[0], r[1]): r for r in rows}
        self.assertEqual(got[('UGA', '7108')], ('UGA', '7108', 3200.0, 'gold', 'none', 'COD'))   # the P39 row is kept
        self.assertEqual(got[('COG', '7403')][3:], ('none', 'comtrade', 'COD'))
        drops = sorted(r[0] for r in rows if r[5] == 'drop')
        self.assertEqual(drops, ['BFA', 'GHA', 'GIN', 'MLI', 'MNG', 'MRT', 'NAM', 'NER', 'TGO', 'ZMB', 'ZWE'])
        self.assertEqual(got[('GHA', '7108')][2], 88000.0)
        with self.assertRaises(SystemExit):
            S7.read_metal_rows(os.path.join(CFG, 'metal_reexport_2022.csv'), {'GHA'})

    def test_own_customs_file(self):
        own = S7.metal_own_customs(os.path.join(S7.DATA, S7.METAL_CUSTOMS_DIR, 'comtrade_X_7108_2022.json'), {288: 'GHA', 466: 'MLI'})
        self.assertAlmostEqual(own['GHA'] / 1000.0, 6541.0, places=0)
        self.assertAlmostEqual(own['MLI'] / 1000.0, 3051.0, places=0)


class BelNbbTest(unittest.TestCase):
    """T2: the NBB share file (national and community concept) gives 1 - national / community; the switch stays off."""

    def test_share(self):
        d = tempfile.mkdtemp()
        json.dump({'data': [{'cmdCode': '30', 'primaryValue': 1.0}]}, open(os.path.join(d, 'X_56_HS2.json'), 'w'))
        bel = os.path.join(d, 'bel.csv')
        with open(bel, 'w') as fh:
            fh.write('hs2,national_eur,community_eur\n30,60,100\n85,120,100\n')
        con = duckdb.connect()
        con.execute('CREATE TABLE cc(code INTEGER, iso3 VARCHAR)')
        used, _ = S7.load_rx_shares(con, d, {}, extra=('USA', 'BEL'), bel_csv=bel, bel_nbb=True)
        self.assertEqual(used, ['BEL'])
        got = dict(con.execute("SELECT hs2, share FROM rx_share WHERE region = 'BEL'").fetchall())
        self.assertAlmostEqual(got['30'], 0.4)
        self.assertEqual(got['85'], 0.0)
        with self.assertRaises(SystemExit):
            S7.load_rx_shares(con, d, {}, extra=('USA', 'BEL'), bel_csv=os.path.join(d, 'none.csv'), bel_nbb=True)

    def test_off(self):
        t = S7.load_choices(os.path.join(CFG, 'trade_choices.csv'))
        self.assertEqual(t['reexport_rx_usa_bel']['value'], 'usa')
        self.assertIn('usa_bel_nbb', S7.ALLOWED['reexport_rx_usa_bel'])
        self.assertFalse(os.path.exists(os.path.join(S7.DATA, S7.NBB_BEL_FILE)))


class ChoicesTest(unittest.TestCase):
    """The v5 values are on (David approved the package), each choice keeps an off value, and H2's set is complete."""

    def test_trade_choices(self):
        t = S7.load_choices(os.path.join(CFG, 'trade_choices.csv'))
        self.assertEqual(set(t), set(S7.CHOICE_ORDER))
        for key in S7.CHOICE_ORDER:
            self.assertIn(t[key]['value'], S7.ALLOWED[key], key)
            self.assertIn(t[key]['gtap_status'], S7.GTAP_STATUS, key)
        on = dict(reexport_high_share=S7.RX_HIGH, reexport_import_surplus=S7.RX_SURPLUS, hkg_domestic_export_cap=S7.HKG_DX_CAP,
                  importer_floor=S7.IMPORTER_FLOOR, transit_import_cap=S7.TRANSIT_CAP_V5, gold_reexport=S7.METAL_RX)
        for key, value in on.items():
            self.assertEqual(t[key]['value'], value, key)
            self.assertTrue({'off'} <= S7.ALLOWED[key] or key in ('transit_import_cap', 'gold_reexport'))
        self.assertIn(S7.TRANSIT_CAP, S7.ALLOWED['transit_import_cap'])     # the v4 value still runs
        self.assertIn(S7.GOLD_RX, S7.ALLOWED['gold_reexport'])

    def test_services_choice(self):
        rows = {r['choice']: r for r in csv.DictReader(open(os.path.join(BUILD, 'config', 's09', 'services_choices.csv')))}
        self.assertEqual(rows['batis_scaling']['value'], S9.BMU_NET)
        self.assertIn('bmu_keep_us_insurance_and_lbr_own_bop', S9.ALLOWED['batis_scaling'])


class ReinsuranceNetTest(unittest.TestCase):
    """M5: the kept BMU to USA insurance is recorded net of the retrocession, which goes from the sellers to the USA."""

    def files(self):
        d = tempfile.mkdtemp()
        eb = os.path.join(d, 'ebops.csv')
        rows = [('BMU', 'W', 'S', 100.0), ('BMU', 'USA', 'SF', 60.0), ('BMU', 'W', 'SF', 70.0), ('BMU', 'GBR', 'SF', 10.0),
                ('USA', 'BMU', 'S', 30.0), ('GBR', 'BMU', 'S', 10.0), ('USA', 'BMU', 'SF', 30.0), ('GBR', 'BMU', 'SF', 10.0)]
        with open(eb, 'w', newline='') as fh:
            w = csv.writer(fh)
            w.writerow(['REF_AREA', 'COUNTERPART_AREA', 'SERVICE', 'OBS_VALUE'])
            w.writerows(rows)
        wdi = os.path.join(d, 'wdi.csv')
        with open(wdi, 'w', newline='') as fh:
            w = csv.writer(fh)
            w.writerow(['iso3', 'series', 'value'])
            w.writerows([('BMU', 'BX.GSR.NFSV.CD', 20e6), ('BMU', 'BM.GSR.NFSV.CD', 10e6)])
        return eb, wdi

    def test_scales(self):
        eb, wdi = self.files()
        keep = (('BMU', 'USA', 'SF'),)
        a = S9.own_bop_scales(eb, wdi, ('BMU',), set(), keep)['BMU']
        b = S9.own_bop_scales(eb, wdi, ('BMU',), set(), keep, net=True)['BMU']
        self.assertEqual((a['sx'], a['sm']), (b['sx'], b['sm']))          # H13 identity unchanged
        self.assertAlmostEqual(sum(a['passed'].values()), 60.0)
        self.assertEqual(b['passed'], {})
        self.assertEqual(b['rerouted'], {('USA', 'USA', 'SF'): 45.0, ('GBR', 'USA', 'SF'): 15.0})
        self.assertEqual(S9.scaled_value(a, 'USA', 'SF', 60.0), 60.0)
        self.assertEqual(S9.scaled_value(b, 'USA', 'SF', 60.0), 0.0)
        self.assertAlmostEqual(S9.scaled_value(a, 'W', 'S', 100.0), 60.0 + 40.0 * a['sx'])
        self.assertAlmostEqual(S9.scaled_value(b, 'W', 'S', 100.0), 40.0 * b['sx'])
        self.assertAlmostEqual(S9.scaled_value(b, 'GBR', 'SF', 10.0), 10.0 * b['sx'])
        self.assertEqual(S9.h13_identity({'BMU': b})[0], [])

    def test_ex_partner(self):
        eb, wdi = self.files()
        keep = (('BMU', 'USA', 'SF'),)
        c = S9.own_bop_scales(eb, wdi, ('BMU',), set(), keep, net=True, ex_partner=True)['BMU']
        self.assertEqual(c['rerouted'], {('GBR', 'USA', 'SF'): 60.0})      # the USA left out: all 60 from GBR
        self.assertEqual(S9.scaled_value(c, 'USA', 'SF', 60.0), 0.0)
        self.assertEqual(S9.h13_identity({'BMU': c})[0], [])
        self.assertIn(S9.BMU_NET_EX, S9.OWN_BOP_NET)
        self.assertEqual(S9.OWN_BOP_KEEP[S9.BMU_NET_EX], S9.OWN_BOP_KEEP[S9.BMU_NET])
        # ex_partner alone (not net) leaves the pass-through as it was
        a = S9.own_bop_scales(eb, wdi, ('BMU',), set(), keep, ex_partner=True)['BMU']
        self.assertAlmostEqual(a['passed'][('USA', 'SF')], 45.0)


if __name__ == '__main__':
    unittest.main()
