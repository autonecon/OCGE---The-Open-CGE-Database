"""Mutation tests for S09-H13 (fix round B9): the BoP scaling check is labelled an identity and still guards the arithmetic.

Run from dataset/build:  python3 -m unittest tests.test_s09_h13 -v
"""
import os
import sys
import unittest

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BUILD)

import s09_services as S9  # noqa: E402


def scale(bx=48350.0, bm=17900.0, wx=1407.3, wm=996.2):
    return {'BMU': dict(bx=bx, bm=bm, wx=wx, wm=wm, sx=wx / bx, sm=wm / bm)}


class H13Test(unittest.TestCase):
    def test_labelled_identity(self):
        # S16 reads the concept tag: an identity row must say so first, and the description must not read as a source comparison
        self.assertTrue(S9.H13_CONCEPT.startswith('identity;'))
        self.assertIn('identity, not a source comparison', S9.H13_DESC)

    def test_consistent_factor_passes(self):
        bad, parts = S9.h13_identity(scale())
        self.assertEqual(bad, [])
        self.assertEqual(len(parts), 1)

    def test_mutated_factor_fails(self):
        sc = scale()
        sc['BMU']['sx'] *= 1.001
        self.assertEqual(S9.h13_identity(sc)[0], ['BMU'])

    def test_factor_above_one_fails(self):
        # a target above the BaTIS total would scale up; batis_scaling only scales down
        self.assertEqual(S9.h13_identity(scale(wx=50000.0))[0], ['BMU'])

    def test_zero_factor_fails(self):
        self.assertEqual(S9.h13_identity(scale(wm=0.0))[0], ['BMU'])


if __name__ == '__main__':
    unittest.main()
