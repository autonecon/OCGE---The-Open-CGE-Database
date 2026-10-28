"""Mutation tests for the S01 HS6 sector overrides (fix round B13 and QA F-12: waste and scrap follow GTAP
HS->GSEC3) and for the HS22 split-code check (QA B-09).

Each test builds a small synthetic case that must pass, then a mutated copy that must fail.
The committed config table is also loaded and checked for the four headings of B13 and heading 7112 of F-12.

Run from dataset/build:  python3 -m unittest tests.test_s01_hs_override -v
"""
import csv
import os
import shutil
import sys
import tempfile
import unittest

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BUILD)

from s01_sets import hs_override as H  # noqa: E402
from s01_sets import hs22_parents as P  # noqa: E402

CONFIG = os.path.join(BUILD, 'config', 's01', 'hs6_sector_override.csv')
SECT = {'wat', 'pap', 'stl', 'nfm', 'chm', 'pub'}
G2S = {'PPP': {'pap'}, 'IS': {'stl'}, 'NFM': {'nfm'}, 'WTR': {'wat'}}


def row(hs6, heading, sector, gs, unsd='wat'):
    return dict(hs6=hs6, heading=heading, sector=sector, unsd_sector=unsd, gtap_gsec3=gs,
                decided_by='test', decided_at='2026-10-24', basis='test', gtap_status='gtap')


class LoadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, 'o.csv')

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write(self, rows, cols=H.COLUMNS):
        with open(self.path, 'w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=list(cols), lineterminator='\n', extrasaction='ignore')
            w.writeheader()
            w.writerows(rows)

    def test_good_table_loads(self):
        self.write([row('740400', '7404', 'nfm', 'NFM'), row('760200', '7602', 'nfm', 'NFM')])
        self.assertEqual(set(H.load(self.path, SECT)), {'740400', '760200'})

    def test_mutations_stop(self):
        bad = {
            'empty basis': [dict(row('740400', '7404', 'nfm', 'NFM'), basis='')],
            'code outside heading': [row('740400', '7602', 'nfm', 'NFM')],
            'unknown sector': [row('740400', '7404', 'xyz', 'NFM')],
            'not an override': [row('740400', '7404', 'wat', 'WTR')],
            'not gtap': [dict(row('740400', '7404', 'nfm', 'NFM'), gtap_status='our_choice')],
            'duplicate': [row('740400', '7404', 'nfm', 'NFM'), row('740400', '7404', 'nfm', 'NFM')],
            'two sectors in a heading': [row('720410', '7204', 'stl', 'I_S'), row('720421', '7204', 'nfm', 'NFM')],
        }
        for name, rows in bad.items():
            with self.subTest(name):
                self.write(rows)
                with self.assertRaises(SystemExit):
                    H.load(self.path, SECT)
        with self.subTest('missing column'):
            self.write([row('740400', '7404', 'nfm', 'NFM')], cols=[c for c in H.COLUMNS if c != 'decided_at'])
            with self.assertRaises(SystemExit):
                H.load(self.path, SECT)


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.rows = {'720410': row('720410', '7204', 'stl', 'I_S'), '720421': row('720421', '7204', 'stl', 'I_S'),
                     '740400': row('740400', '7404', 'nfm', 'NFM')}
        self.mapped = {'720410': 'stl', '720421': 'stl', '720450': 'stl', '740400': 'nfm', '711299': 'wat'}
        self.links = {'720410': {'wat'}, '720421': {'wat'}, '720450': {'stl'}, '740400': {'wat'}, '711299': {'wat'}}
        self.gtap = {'720410': 'IS', '720421': 'IS', '720450': 'IS', '740400': 'NFM', '711299': 'NFM'}

    def run_check(self, **kw):
        a = dict(mapped=self.mapped, links=self.links, gtap_of=self.gtap, g2s=G2S, rows=self.rows)
        a.update(kw)
        return H.check(a['mapped'], a['links'], a['gtap_of'], a['g2s'], a['rows'])

    def test_passes(self):
        self.assertEqual(self.run_check(), [])

    def test_override_not_applied_fails(self):
        self.assertTrue(self.run_check(mapped=dict(self.mapped, **{'740400': 'wat'})))

    def test_code_left_behind_in_heading_fails(self):
        # a new 7204 code still on wat while the heading goes to stl
        m = dict(self.mapped, **{'720449': 'wat'})
        lk = dict(self.links, **{'720449': {'wat'}})
        self.assertTrue(any('720449' in p for p in self.run_check(mapped=m, links=lk)))

    def test_gtap_disagreement_fails(self):
        self.assertTrue(self.run_check(gtap_of=dict(self.gtap, **{'740400': 'IS'})))

    def test_sector_not_gtaps_fails(self):
        rows = dict(self.rows, **{'740400': row('740400', '7404', 'stl', 'NFM')})
        self.assertTrue(self.run_check(rows=rows, mapped=dict(self.mapped, **{'740400': 'stl'})))

    def test_sector_already_a_link_fails(self):
        self.assertTrue(self.run_check(links=dict(self.links, **{'740400': {'wat', 'nfm'}})))

    def test_unknown_code_fails(self):
        self.assertTrue(self.run_check(rows=dict(self.rows, **{'740499': row('740499', '7404', 'nfm', 'NFM')})))


class CommittedTableTest(unittest.TestCase):
    def test_b13_and_f12_headings(self):
        sect = {'wat', 'pap', 'stl', 'nfm'}
        rows = H.load(CONFIG, sect)
        heads = {r['heading']: r['sector'] for r in rows.values()}
        self.assertEqual(heads, {'4707': 'pap', '7204': 'stl', '7404': 'nfm', '7602': 'nfm', '7112': 'nfm'})
        self.assertEqual({r['unsd_sector'] for r in rows.values()}, {'wat'})
        self.assertEqual({r['gtap_gsec3'] for r in rows.values()}, {'PPP', 'I_S', 'NFM'})
        # 720450 (remelting scrap ingots) is already stl through its UNSD link, so it is not an override row
        self.assertNotIn('720450', rows)
        # F-12: every HS17 code of heading 7112
        self.assertEqual(sorted(k for k in rows if k.startswith('7112')), ['711230', '711291', '711292', '711299'])
        self.assertEqual(len(rows), 16)


class Hs22ParentsTest(unittest.TestCase):
    """QA B-09: an HS22 code with HS17 sources in several sectors may leave the largest-value source's sector
    only where GTAP HS2022 (sheet H6) gives the sector it keeps."""
    def setUp(self):
        # 382219 comes from 382200 (chm) and 300215 (pha, larger); GTAP H6 says CHM, so chm stays
        self.corr = [('382219', '382200'), ('382219', '300215'), ('382212', '300215'), ('382212', '382200'), ('010121', '010121')]
        self.sec17 = {'382200': 'chm', '300215': 'pha', '010121': 'ctl'}
        self.chosen = {'382219': 'chm', '382212': 'pha', '010121': 'ctl'}
        self.gtap = {'382219': 'CHM', '382212': 'CHM', '010121': 'CTL'}
        self.g2s = {'CHM': {'chm'}, 'BPH': {'pha'}, 'CTL': {'ctl'}}
        self.val = {'382200': 57.8, '300215': 182.4, '010121': 1.0}

    def rows(self, **kw):
        a = dict(corr=self.corr, sec17=self.sec17, chosen=self.chosen, gtap22=self.gtap, g2s=self.g2s, value17=self.val)
        a.update(kw)
        return P.ambiguous(a['corr'], a['sec17'], a['chosen'], a['gtap22'], a['g2s'], a['value17'])

    def test_passes(self):
        r = self.rows()
        self.assertEqual([x['hs22'] for x in r], ['382212', '382219'])   # single-sector codes are not listed
        self.assertEqual({x['hs22']: x['largest_parent_sector'] for x in r}, {'382212': 'pha', '382219': 'pha'})
        self.assertEqual(P.problems(r), [])
        # 382212 follows its largest source (pha) although GTAP H6 says CHM: reported, not a failure
        self.assertEqual([x['hs22'] for x in P.gtap_differs(r)], ['382212'])

    def test_off_largest_without_gtap_fails(self):
        self.assertTrue(P.problems(self.rows(gtap22=dict(self.gtap, **{'382219': 'BPH'}))))
        self.assertTrue(P.problems(self.rows(gtap22={k: v for k, v in self.gtap.items() if k != '382219'})))

    def test_largest_source_decides_value(self):
        # with the chm source larger, 382219 is on its largest source and needs no GTAP backing
        r = self.rows(value17=dict(self.val, **{'382200': 500.0}), gtap22=dict(self.gtap, **{'382219': 'BPH'}))
        self.assertEqual([p[:6] for p in P.problems(r)], ['382212'])   # now 382212 (pha) is off its larger chm source and GTAP says CHM


if __name__ == '__main__':
    unittest.main()
