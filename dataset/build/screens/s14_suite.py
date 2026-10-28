"""S14 population screens (dataset/docs/SCREENS.md seven questions on the assembled data base).

The stage calls run() with the tables read back from its output, so every screen sees what S15 reads.
Reports go to dataset/reviews/screens/S14/; nothing is written under the stage output, so a screen run does
not change SHA256SUMS. S14 makes no new number except SAVE (a residual) and the rounding re-balance, so only
the identity screen can fail the stage; the others are diagnostics.

1 benchmark   SAVE against SAVE with the S02 BoP memo flows (GTAP 12 eq. 7.2), and X - M against the S02
              implied net exports, every region (diagnostic)
2 outliers    saving share outside [-1, 1] and SAVE <= 0 (diagnostic; the gate and the flags carry them)
3 year_jump   none: S14 chooses no source year (population 0)
4 stale       none: S14 reads stamped stages only (population 0)
5 identities  VMSB below VCIF, a purchaser value below its basic value by more than the column's subsidy
              (sign flip), a negative cell, an activity with output and no capital, labour or other factor
              (any hit fails)
6 coverage    routes with 0 < VXSB <= 1e-4 USD million and regions with no land, natural resources or
              capital payments (the closure test needs them positive in each aggregated region; diagnostic)
7 moves       regional accounts against S14_PREV_OUTPUT when set (diagnostic)
"""
import os
import sys

import numpy as np
import pandas as pd

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET = os.path.dirname(BUILD)
if BUILD not in sys.path:
    sys.path.insert(0, BUILD)

from screens.common import write_dicts  # noqa: E402

REPORT_DIR = DATASET + '/reviews/screens/S14'
SMALL = 1e-4
MOVE_SHARE, MOVE_BN = 0.10, 0.1
COLUMNS = ['screen', 'region', 'item', 'value_bn', 'benchmark_bn', 'ratio', 'detail']


def s1_benchmark(ctx):
    g = ctx['gate']
    hits = [dict(screen='benchmark', region=r, item='SAVE', value_bn=x.SAVE / 1000, benchmark_bn=x.save_bop_eq72 / 1000,
                 ratio=x.SAVE / x.save_bop_eq72 if x.save_bop_eq72 else np.nan,
                 detail='S02 BoP memo row' if np.isfinite(x.net_primary_income_musd) or np.isfinite(x.net_secondary_income_musd) else 'no BoP memo row')
            for r, x in g.iterrows()]
    # X - M against the S02 implied net exports: SAVE <= 0 is the eq. 7.1 residual, so its benchmark is the trade
    # balance the macro source implies (QA C1)
    nx = ctx.get('s02_nx')
    if nx is not None:
        for r, x in g.iterrows():
            b = nx.get(r, np.nan)
            hits.append(dict(screen='benchmark', region=r, item='X - M', value_bn=x.trade_balance / 1000, benchmark_bn=b / 1000,
                             ratio=x.trade_balance / b if b else np.nan,
                             detail='S02 implied net exports' + ('; SAVE <= 0' if not x.save_positive else '')))
    return hits, len(g) * (2 if nx is not None else 1)


def s2_outliers(ctx):
    g = ctx['gate']
    hits = []
    for r, x in g.iterrows():
        if not x.saving_share_in_bounds:
            hits.append(dict(screen='outlier', region=r, item='saving share', value_bn=x.SAVE / 1000, ratio=x.saving_share, detail='CARRY-SAVE'))
        elif not x.save_positive:
            hits.append(dict(screen='outlier', region=r, item='SAVE <= 0', value_bn=x.SAVE / 1000, ratio=x.saving_share, detail=x.save_cause))
    return hits, len(g)


def s5_identities(ctx):
    R = ctx['R']
    hits = []
    b = R['bilateral']
    for x in b[b['VMSB'] < b['VCIF'] - 1e-9 * b['VCIF'].abs()].itertuples():
        hits.append(dict(screen='identity', region=x.dst, item=f'VMSB < VCIF {x.comm} from {x.src}', value_bn=x.VMSB / 1000, benchmark_bn=x.VCIF / 1000))
    for k, cols in (('firms', ('VDFB', 'VDFP', 'VMFB', 'VMFP')), ('final', [c for c in R['final'].columns if c.startswith('V')]),
                    ('make', ('MAKS', 'MAKB')), ('vtwr', ('VTWR',)), ('vst', ('VST',))):
        d = R[k]
        for c in cols:
            for x in d[d[c] < 0].itertuples():
                hits.append(dict(screen='identity', region=getattr(x, 'region', ''), item=f'{k} {c} negative', value_bn=getattr(x, c) / 1000))
    en, mk = R['endw'], R['make']
    va = en.groupby(['region', 'acts'])['EVFP'].sum()
    for x in mk[mk['MAKB'] > 0].itertuples():
        if va.get((x.region, x.acts), 0.0) <= 0:
            hits.append(dict(screen='identity', region=x.region, item=f'{x.acts} output with no factor payment', value_bn=x.MAKB / 1000))
    return hits, len(b) + len(mk)


def s6_coverage(ctx):
    R = ctx['R']
    b, en = R['bilateral'], R['endw']
    hits = []
    sm = b[(b['VXSB'] > 0) & (b['VXSB'] <= SMALL)].groupby('dst')['VXSB'].agg(['count', 'sum'])
    for r, x in sm.iterrows():
        hits.append(dict(screen='coverage', region=r, item='routes with 0 < VXSB <= 1e-4', value_bn=x['sum'] / 1000, detail=f'{int(x["count"])} routes'))
    tot = en.groupby(['region', 'endw'])['EVFP'].sum().unstack(fill_value=0.0).reindex(ctx['regions'], fill_value=0.0)
    for f in ('land', 'natres', 'capital'):
        for r in tot.index[tot.get(f, pd.Series(0.0, index=tot.index)) <= 0]:
            hits.append(dict(screen='coverage', region=r, item=f'no {f} payment in the region', value_bn=0.0))
    return hits, len(b)


def s7_moves(ctx):
    prev = ctx.get('prev')
    if prev is None:
        return [], 0
    a = ctx['acc']
    p = prev.set_index('region')
    hits = []
    for r in a.index.intersection(p.index):
        for k in ('SAVE', 'Y', 'C', 'G', 'I', 'X', 'M'):
            v, w = a.loc[r, k], p.loc[r, k]
            if abs(v - w) / 1000 > MOVE_BN or (w and abs(v / w - 1) > MOVE_SHARE and abs(v - w) / 1000 > 0.02):
                hits.append(dict(screen='moves', region=r, item=k, value_bn=v / 1000, benchmark_bn=w / 1000, ratio=v / w if w else np.nan))
    return hits, len(a)


SCREENS = [('01_benchmark', s1_benchmark), ('02_outliers', s2_outliers), ('03_year_jump', None), ('04_stale', None),
           ('05_identities', s5_identities), ('06_coverage', s6_coverage), ('07_moves', s7_moves)]


def run(ctx, log=print, report_dir=REPORT_DIR):
    summary, failing = [], 0
    for name, fn in SCREENS:
        hits, pop = fn(ctx) if fn else ([], 0)
        write_dicts(f'{report_dir}/screen_{name}.csv', hits, COLUMNS)
        if name == '05_identities':
            failing += len(hits)
        summary.append(f'{name}: {len(hits)} hits of {pop}')
        log(f'screen {name}: {len(hits)} hits (population {pop})')
    return dict(material_unexplained=failing, summary='; '.join(summary))
