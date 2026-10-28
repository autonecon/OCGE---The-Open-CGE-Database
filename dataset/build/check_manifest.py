"""Global audit of dataset/data/MANIFEST.csv (moved out of S01, review S01-M1).
Checks every MANIFEST file exists and its SHA-256 recomputes, and every data file on disk is in MANIFEST.
Not a stage: it writes no snapshot and gates nothing; run it after write_docs.py and before a release.
Not counted as data files: README.md and MANIFEST.csv, files at the top of data/ (split-file and fetch tooling),
and the <name>.partNN chunks of a file listed in SPLIT_FILES.sha256 (the rebuilt file has the MANIFEST row).
REBUILT lists git-ignored folders that a build script recreates; their rows are reported, not failed, when absent.
Writes dataset/MANIFEST_AUDIT.md and exits 1 on any problem."""
import os, re, sys
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/lib')
from stagekit import DATA, ROOT, sha256, now

REBUILT = {'oecd_itic/hs4_2022/': 'dataset/build/s08_fetch_itic.py (git-ignored; S08-H9)'}

man = pd.read_csv(DATA + '/MANIFEST.csv')
split = {ln.split()[1] for ln in open(DATA + '/SPLIT_FILES.sha256') if ln.strip()}
bad, absent = [], []
for r in man.itertuples():
    if r.path.startswith('('): continue
    p = DATA + '/' + r.path
    rb = next((v for k, v in REBUILT.items() if r.path.startswith(k)), None)
    if not os.path.exists(p):
        (absent.append((r.path, f'absent, rebuilt by {rb}')) if rb else bad.append((r.path, 'missing')))
    elif sha256(p) != r.sha256: bad.append((r.path, 'sha mismatch'))
on_disk = {os.path.relpath(os.path.join(rt, f), DATA) for rt, _, fs in os.walk(DATA) for f in fs if f not in ('README.md', 'MANIFEST.csv')}
on_disk = {p for p in on_disk if '/' in p and not (re.sub(r'\.part\d\d$', '', p) != p and re.sub(r'\.part\d\d$', '', p) in split)}
notman = sorted(on_disk - set(man.path))
folders = sorted(d for d in os.listdir(DATA) if os.path.isdir(os.path.join(DATA, d)))
md = ['# MANIFEST audit', '', f'Run {now()}.', '', f'- Source folders under data/: {len(folders)}', f'- MANIFEST rows checked: {len(man)}',
      f'- Missing or SHA mismatch: {len(bad)}', f'- Files on disk not in MANIFEST: {len(notman)}', f'- Absent by design (rebuilt by a script): {len(absent)}', '']
md += [f'- {a}: {b}' for a, b in bad] + [f'- not in MANIFEST: {x}' for x in notman] + [f'- {a}: {b}' for a, b in absent]
open(ROOT + '/MANIFEST_AUDIT.md', 'w').write('\n'.join(md) + '\n')
print('\n'.join(md))
sys.exit(1 if bad or notman else 0)
