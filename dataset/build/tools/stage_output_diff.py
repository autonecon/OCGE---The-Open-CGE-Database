#!/usr/bin/env python3
"""Cell-level diff of two snapshots of one stage's output/ folder.

For every CSV (plain or .gz) in both folders: rows are joined on the text columns, and each numeric
column is compared. Writes one summary row per file and numeric column (cells changed, largest
absolute change, sum of changes) and, with --cells, every changed cell. Used to show that a fix
round changes only the cells it should (the S11 TKM gas fix, 2026-10-24).

  python3 tools/stage_output_diff.py OLD_OUTPUT_DIR NEW_OUTPUT_DIR OUT_DIR [--cells] [--tol 1e-9]
"""
import argparse
import hashlib
import os

import pandas as pd


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for b in iter(lambda: fh.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def read(path):
    return pd.read_csv(path, low_memory=False)


def diff_file(a, b, name, tol):
    text = [c for c in a.columns if not pd.api.types.is_numeric_dtype(a[c]) or pd.api.types.is_bool_dtype(a[c])]
    num = [c for c in a.columns if c not in text]
    summary, cells = [], []
    if list(a.columns) != list(b.columns):
        return [dict(file=name, column='(columns)', note=f'columns differ: {list(a.columns)} vs {list(b.columns)}')], []
    for c in text:
        a[c] = a[c].astype(str)
        b[c] = b[c].astype(str)
    if not text:
        a = a.reset_index().rename(columns={'index': 'row'})
        b = b.reset_index().rename(columns={'index': 'row'})
        text = ['row']
    if a.duplicated(text).any() or b.duplicated(text).any():
        a = a.assign(_n=a.groupby(text).cumcount())
        b = b.assign(_n=b.groupby(text).cumcount())
        text = text + ['_n']
    m = a.merge(b, on=text, how='outer', suffixes=('_old', '_new'), indicator=True)
    only = m['_merge'] != 'both'
    if only.any():
        summary.append(dict(file=name, column='(rows)', cells_changed=int(only.sum()),
                            note=f'{int((m["_merge"] == "left_only").sum())} rows only in old, '
                                 f'{int((m["_merge"] == "right_only").sum())} only in new'))
    for c in num:
        o, n = m[c + '_old'], m[c + '_new']
        if not (pd.api.types.is_numeric_dtype(o) and pd.api.types.is_numeric_dtype(n)) or pd.api.types.is_bool_dtype(o):
            ch = (o.astype(str) != n.astype(str)) & ~only
            if ch.any():
                summary.append(dict(file=name, column=c, cells_changed=int(ch.sum()), note='text change'))
                for _, r in m[ch].iterrows():
                    cells.append(dict(file=name, key='|'.join(str(r[k]) for k in text), column=c, old=r[c + '_old'], new=r[c + '_new']))
            continue
        d = (n - o)
        both_nan = o.isna() & n.isna()
        ch = ((d.abs() > tol) | (o.isna() != n.isna())) & ~both_nan & ~only
        if ch.any():
            summary.append(dict(file=name, column=c, cells_changed=int(ch.sum()), max_abs_change=float(d[ch].abs().max()),
                                sum_change=float(d[ch].sum()), sum_old=float(o[ch].sum()), sum_new=float(n[ch].sum())))
            for _, r in m[ch].iterrows():
                cells.append(dict(file=name, key='|'.join(str(r[k]) for k in text), column=c,
                                  old=r[c + '_old'], new=r[c + '_new'], change=r[c + '_new'] - r[c + '_old']))
    return summary, cells


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('old')
    ap.add_argument('new')
    ap.add_argument('out')
    ap.add_argument('--cells', action='store_true')
    ap.add_argument('--tol', type=float, default=1e-9)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    files = sorted(set(os.listdir(a.old)) | set(os.listdir(a.new)))
    rows, allcells = [], []
    for f in files:
        po, pn = os.path.join(a.old, f), os.path.join(a.new, f)
        if not (os.path.exists(po) and os.path.exists(pn)):
            rows.append(dict(file=f, column='(file)', note='only in ' + ('old' if os.path.exists(po) else 'new')))
            continue
        same = sha(po) == sha(pn)
        rows.append(dict(file=f, column='(file)', note='byte-identical' if same else 'differs'))
        if same or not (f.endswith('.csv') or f.endswith('.csv.gz')):
            continue
        s, c = diff_file(read(po), read(pn), f, a.tol)
        rows += s
        allcells += c
    pd.DataFrame(rows).to_csv(os.path.join(a.out, 'diff_summary.csv'), index=False)
    if a.cells:
        pd.DataFrame(allcells).to_csv(os.path.join(a.out, 'diff_cells.csv.gz'), index=False)
    print(pd.DataFrame(rows).to_string())


if __name__ == '__main__':
    main()
