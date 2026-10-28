"""Move the upstream pins of S06, S08, S09, S10 and S11 to the stage just built (beta v4 build; S16 2026-10-26).

S06, S08, S09 and S10 bind their upstream by fixed constants: the io checksum carried through S05-S09, and for S07,
S08 and S09 the commit that last touched the stage's STAMP, the STAMP time, the output SHA256SUMS and the hashes of
the files read. After a rebuild of an upstream stage those constants must follow, or the G0bind checks stop the next
stage. This tool reads the stage in dataset/stages (the scripts bind dataset/stages, not GTAP_STAGES_DIR), computes
the values and rewrites the constants in place.

Order in a full build, from S05 on:
    python3 s05_composite.py;      commit stages;  python3 tools/update_pins.py --after S05;  commit code
    python3 s06_apt.py;            commit stages
    python3 s07_trade.py;          commit stages;  python3 tools/update_pins.py --after S07;  commit code
    python3 s08_margins.py;        commit stages;  python3 tools/update_pins.py --after S08;  commit code
    python3 s09_services.py;       commit stages;  python3 tools/update_pins.py --after S09;  commit code
    python3 s10_tariffs_taxes.py ...
The stage outputs must be committed before the tool runs, because the pins hold the commit that touched the STAMP.
--after S01 moves S10's S01_SUMS. --check only reports the pins that differ (exit 1 if any)."""
import argparse
import hashlib
import os
import re
import subprocess
import sys

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(BUILD)
STAGES = os.path.join(ROOT, 'stages')
DIRS = {'S01': 'S01_sets_registry', 'S05': 'S05_composite', 'S07': 'S07_trade', 'S08': 'S08_margins', 'S09': 'S09_services'}


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for b in iter(lambda: fh.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def stamp(stage, stages=STAGES):
    """(commit that last touched the STAMP in git, STAMP time line, STAMP build-commit line, SHA256SUMS hash)."""
    d = os.path.join(stages, DIRS[stage])
    lines = open(os.path.join(d, 'STAMP')).read().splitlines()
    build = next(x.split()[1] for x in lines if x.startswith('commit '))
    time = next(x for x in lines if re.match(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', x))
    rel = os.path.relpath(os.path.join(d, 'STAMP'), os.path.dirname(ROOT))
    touched = subprocess.run(['git', '-C', os.path.dirname(ROOT), 'log', '-1', '--format=%H', '--', rel],
                             capture_output=True, text=True).stdout.strip()
    return touched, time, build, sha256(os.path.join(d, 'output', 'SHA256SUMS'))


def pins(after, stages=STAGES):
    """{script: {constant: value}} for the stage just built."""
    out = lambda st, f: sha256(os.path.join(stages, DIRS[st], 'output', f))       # noqa: E731
    if after == 'S01':
        return {'s10_tariffs_taxes.py': {'S01_SUMS': stamp('S01', stages)[3]}}
    if after == 'S05':
        return {'s06_apt.py': {'IO_S05_SHA': out('S05', 'io_s05.csv.gz')}}
    t, time, build, sums = stamp(after, stages)
    if after == 'S07':
        vx, io = out('S07', 'vxsb_goods_s07r.csv.gz'), out('S07', 'io_s07.csv.gz')
        return {'s08_margins.py': {'S07_HEAD': t, 'S07_STAMP_TIME': time, 'S07_SHA256SUMS': sums, 'S07_VXSB_SHA': vx, 'S07_IO_SHA': io},
                's09_services.py': {'S07_HEAD': t, 'S07_SHA256SUMS': sums, 'S07_VXSB': vx},
                's10_tariffs_taxes.py': {'S07_SUMS': sums}}
    if after == 'S08':
        return {'s09_services.py': {'S08_HEAD': t, 'S08_STAMP_TIME': time, 'S08_BUILD': build, 'S08_SHA256SUMS': sums,
                                    'S08_FREIGHT': out('S08', 'freight_for_s09.csv'), 'S08_VST': out('S08', 'vst_s08.csv'),
                                    'S08_IO': out('S08', 'io_s08.csv.gz')},
                's10_tariffs_taxes.py': {'S08_SUMS': sums}}
    if after == 'S09':
        return {'s10_tariffs_taxes.py': {'S09_STAMP_COMMIT': t, 'S09_STAMP_TIME': time, 'S09_SUMS': sums,
                                         'S09_IO': out('S09', 'io_s09.csv.gz'), 'S09_TRAVEL': out('S09', 'travel_s09.csv.gz')},
                's11_energy.py': {'S09_TRAVEL_SHA': out('S09', 'travel_s09.csv.gz')}}
    raise SystemExit(f'--after {after}: one of S01, S05, S07, S08, S09')


def rewrite(text, values):
    """text with each NAME = '...' set to values[NAME] (the trailing comment kept). Returns (text, [(name, old, new)])."""
    moved = []
    for name, new in values.items():
        rx = re.compile(r"^(%s = ')([^']*)(')" % re.escape(name), re.M)
        m = rx.search(text)
        if m is None:
            raise SystemExit(f'constant {name} not found')
        if not new:
            raise SystemExit(f'{name}: no value (is the stage committed?)')
        if m.group(2) != new:
            moved.append((name, m.group(2), new))
            text = text[:m.start(2)] + new + text[m.end(2):]
    return text, moved


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--after', required=True, help='the stage just built and committed: S01, S05, S07, S08 or S09')
    ap.add_argument('--check', action='store_true', help='report the pins that differ, change nothing')
    a = ap.parse_args(argv)
    n = 0
    for script, values in pins(a.after).items():
        path = os.path.join(BUILD, script)
        text, moved = rewrite(open(path).read(), values)
        for name, old, new in moved:
            print(f'{script} {name}: {old} -> {new}')
        n += len(moved)
        if moved and not a.check:
            open(path, 'w').write(text)
    print(f'{n} pins {"differ" if a.check else "moved"}')
    return 1 if a.check and n else 0


if __name__ == '__main__':
    sys.exit(main())
