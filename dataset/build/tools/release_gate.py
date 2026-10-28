#!/usr/bin/env python3
"""Beta v5 RG: refuse to release a data base whose S16 run was not a release run.

    python3 tools/release_gate.py [STAGES_DIR]

Reads <STAGES_DIR>/S16_final_checks/checks.json (default: the stages folder of the build) and exits 1 unless S16 ran
with GTAP_RELEASE=1 and every release gate passed as a hard check: S16-Hrelease (the release run), S16-Grepro (a second
run of the same commit wrote the same SHA256SUMS: run S16 twice into two stages folders, the second with
GTAP_OTHER_STAGES_DIR set to the first), S16-Hscreenreview (no builder screen explanation unsigned, disagreed or dated
before the cutoff), S16-Hwaivers (no stale map exception) and S16-Hmaps; and no other hard check failed. Run it before
copying the S15 files to the release folder. Beta v4 was released from an S16 run without
GTAP_RELEASE=1 (round-3 oddities item 4), which this gate would have stopped.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.stagekit import STAGES  # noqa: E402
from s16_final import betav5 as B5  # noqa: E402


def main(argv):
    stages = argv[1] if len(argv) > 1 else STAGES
    p = os.path.join(stages, 'S16_final_checks', 'checks.json')
    if not os.path.exists(p):
        print(f'release gate: {p} is missing')
        return 1
    bad = B5.release_gate(json.load(open(p)))
    if not os.path.exists(os.path.join(stages, 'S16_final_checks', 'STAMP')):
        bad.append('S16 has no STAMP')
    if bad:
        print('release gate: REFUSED\n  ' + '\n  '.join(bad))
        return 1
    print('release gate: PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
