"""Runs the Julia unit test of the zero-weight parameter fallback (s15_har/julia/test_prepare.jl; beta v4 S16)."""
import os
import subprocess
import unittest

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@unittest.skipUnless(os.environ.get('S15_JULIA'), 'S15_JULIA not set (Julia with the s15_har/julia project)')
class ZeroWeightFallbackTest(unittest.TestCase):
    def test_fill_zero_weight_parameters(self):
        r = subprocess.run([os.environ['S15_JULIA'], '--project=s15_har/julia', 's15_har/julia/test_prepare.jl'],
                           cwd=BUILD, capture_output=True, text=True, timeout=900)
        self.assertEqual(r.returncode, 0, r.stdout[-2000:] + r.stderr[-2000:])


if __name__ == '__main__':
    unittest.main()
