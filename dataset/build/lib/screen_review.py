"""Fable QA E-05: the population-screen hard checks (S10-S13 -Hscreens) pass when a row of config/sNN/screen_explanations.csv
names the hit, and a row written by the builder cannot be told apart from a justified one. S16 lists every row not
decided by a person (decided_by starting with 'Claude') for review; a reviewer signs it in
config/s16/screen_explanation_signoff.csv (stage, importer, item, screen, reviewed_by, reviewed_at, verdict: agree or
disagree, note). A 'disagree' verdict always fails S16-Hscreenreview; an unsigned row fails it at release
(GTAP_RELEASE=1) and is a NOTE otherwise.
"""
import csv
import os

import pandas as pd

STAGES = ('s10', 's11', 's12', 's13')
SIGNOFF_COLUMNS = ('stage', 'importer', 'item', 'screen', 'reviewed_by', 'reviewed_at', 'verdict', 'note')
VERDICTS = ('agree', 'disagree')
BUILDER = 'Claude'


def builder_rows(build, stages=STAGES):
    """Every explanation row the builder decided, with its stage: columns stage, importer, item, screen, evidence class,
    source, decided_by, date."""
    out = []
    for s in stages:
        p = os.path.join(build, 'config', s, 'screen_explanations.csv')
        if not os.path.exists(p):
            continue
        d = pd.read_csv(p, dtype=str, keep_default_na=False)
        d = d[d['decided_by'].str.startswith(BUILDER)]
        out.append(pd.DataFrame({'stage': s.upper(), 'importer': d['importer'], 'item': d['hs6/sector'], 'screen': d['screen'],
                                 'evidence_class': d['evidence class'], 'source': d['source file and page'],
                                 'decided_by': d['decided_by'], 'date': d['date']}))
    cols = ['stage', 'importer', 'item', 'screen', 'evidence_class', 'source', 'decided_by', 'date']
    return pd.concat(out, ignore_index=True)[cols] if out else pd.DataFrame(columns=cols)


def read_signoff(path):
    if not os.path.exists(path):
        raise SystemExit(f'{path} is missing')
    with open(path, newline='') as fh:
        rd = csv.DictReader(fh)
        if tuple(rd.fieldnames or ()) != SIGNOFF_COLUMNS:
            raise SystemExit(f'{path}: columns {rd.fieldnames} are not {SIGNOFF_COLUMNS}')
        rows = list(rd)
    for r in rows:
        if r['verdict'] not in VERDICTS or not r['reviewed_by'].strip() or r['reviewed_by'].startswith(BUILDER):
            raise SystemExit(f'{path}: row {r} needs a verdict ({VERDICTS}) and a reviewer who is not the builder')
    return {(r['stage'].upper(), r['importer'], r['item'], r['screen']): r for r in rows}


def review(rows, signoff):
    """rows with reviewed_by, verdict columns added; returns (rows, n_unsigned, disagreed list)."""
    key = list(zip(rows['stage'], rows['importer'], rows['item'], rows['screen']))
    rows = rows.copy()
    rows['reviewed_by'] = [signoff.get(k, {}).get('reviewed_by', '') for k in key]
    rows['verdict'] = [signoff.get(k, {}).get('verdict', '') for k in key]
    dis = [' '.join(k) for k in key if signoff.get(k, {}).get('verdict') == 'disagree']
    return rows, int((rows['verdict'] == '').sum()), dis
