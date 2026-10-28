"""S13 population screens (dataset/docs/SCREENS.md seven questions on the fitted tables).

The stage calls run() with the frames it built, so every screen sees the tables the stamp booked. Reports
go to dataset/reviews/screens/S13/; nothing is written under the stage output, so a screen run does not
change SHA256SUMS.

1 benchmark   region C + G + I against S02 absorption (the decision-2 factor): ratio outside 0.5 to 1.5
              with a gap above 0.05 bn
2 outliers    activity output against io_s12 output: more than 3 times or less than a third, or a new
              activity, in a cell of 0.1 bn or more. S11 targets and ch.9D representative columns are
              gtap_rule (the target or the held exports set the size), and so is a move at least half of which is
              the change in held exports (plus VST) against io_s12 in the same direction (ch.17A item 2)
3 year_jump   none: S13 chooses no source year (population 0)
4 stale       none: S13 reads stamped stages only (population 0)
5 identities  zero profit, market clearing, imports, non-negative cells, non-negative output (any hit fails)
6 coverage    share of region output in representative-table columns and the size of the smears (diagnostic)
7 moves       activity output against S13_PREV_OUTPUT when set (diagnostic)
8 icio gate   ICIO economies whose intermediate cells moved more than 2% of intermediate use (diagnostic)

Screens 1 and 2 need an explanation row (screen 1 only when config screen_outliers is report_only) in config/s13/screen_explanations.csv when a hit is material:
0.1 bn, or 1 percent of the region's GDP. In that file the `importer` column holds the region and
`hs6/sector` the sector ('all' for screen 1).
"""
import os
import sys

import numpy as np
import pandas as pd

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET = os.path.dirname(BUILD)
if BUILD not in sys.path:
    sys.path.insert(0, BUILD)

from screens.common import EVIDENCE_CLASSES, load_explanations, blank_explanation, write_dicts  # noqa: E402

EXPLANATIONS = BUILD + '/config/s13/screen_explanations.csv'
REPORT_DIR = DATASET + '/reviews/screens/S13'
MATERIAL_BN = 0.1
MATERIAL_SHARE = 0.01
RATIO_LO, RATIO_HI, GAP_BN = 0.5, 1.5, 0.05
OUT_FACTOR, CELL_BN = 3.0, 0.1
EXPORT_SHARE = 0.5         # an output move at least half explained by the held exports is gtap_rule
MOVE_SHARE, MOVE_BN = 0.10, 0.1
ICIO_GATE = 0.02
TOL = 1e-6
EXPLAINED_SCREENS = ('benchmark', 'outlier')
COLUMNS = ['screen', 'importer', 'hs6/sector', 'flow', 'value_bn', 'benchmark_bn', 'ratio', 'gap_bn', 'region_gdp_bn',
           'source_series', 'evidence class', 'material', 'detail']


def material(gap_bn, region_gdp_bn):
    g = abs(float(gap_bn or 0))
    return g >= MATERIAL_BN or (region_gdp_bn > 0 and g >= MATERIAL_SHARE * region_gdp_bn)


def _out(io, sectors):
    return io[io['row'] == 'OUT'].set_index('region')[sectors]


def _exports(io, sectors, cols):
    d = io[io['row'].isin([f'dom_{c}' for c in sectors])].set_index('region')
    d = d.assign(s=d['row'].str[4:], v=d[list(cols)].sum(axis=1))
    return d.reset_index().pivot(index='region', columns='s', values='v')[sectors]


def s1_benchmark(ctx):
    mt = ctx['mt']
    hits = []
    for r, x in mt.iterrows():
        s02 = (x['C_musd'] + x['G_musd'] + x['GFCF_musd']) / 1000.0
        val = (x['C'] + x['G'] + x['I']) / 1000.0
        ratio = x['factor']
        if (ratio < RATIO_LO or ratio > RATIO_HI) and abs(val - s02) > GAP_BN:
            hits.append(dict(screen='benchmark', importer=r, **{'hs6/sector': 'all'}, flow='C + G + I', value_bn=val,
                             benchmark_bn=s02, ratio=ratio, gap_bn=val - s02, source_series='S02 C, G, GFCF',
                             detail=f'GDP {x["GDP_musd"] / 1000:.3f} bn; net exports at border prices {x["NX"] / 1000:.3f} bn'))
    return hits, len(mt)


def s2_outliers(ctx):
    sectors = ctx['sectors']
    a, b = _out(ctx['io12'], sectors), _out(ctx['io13'], sectors)
    xa = _exports(ctx['io12'], sectors, ('X',))
    xb = _exports(ctx['io13'], sectors, ('X', 'VST'))
    st = ctx['status'].set_index(['region', 'sector'])['status'].to_dict() if len(ctx['status']) else {}
    hits, pop = [], 0
    for r in b.index:
        for c in sectors:
            o, n = float(a.loc[r, c]), float(b.loc[r, c])
            if max(abs(o), abs(n)) < CELL_BN * 1000:
                continue
            pop += 1
            if (o > 0 and (n > OUT_FACTOR * o or n < o / OUT_FACTOR)) or (o <= 0 < n):
                dx = float(xb.loc[r, c] - xa.loc[r, c])
                gap = n - o
                why = 'S11 output target' if (r, c) in ctx['tout'] else ('representative-table column (ch.9D)' if st.get((r, c)) == 'representative' else '')
                if not why and np.sign(dx) == np.sign(gap) and abs(dx) >= EXPORT_SHARE * abs(gap):
                    why = f'held exports (ch.17A item 2) moved {dx / 1000:.3f} bn against io_s12'
                fs = ctx.get('fuel', {}).get((r, c), 0.0)
                if not why and gap > 0 and fs >= EXPORT_SHARE * gap:
                    why = f'fuel subsidy booked at the reference price (fix-round B15, Chepeliev et al. 2018) {fs / 1000:.3f} bn'
                hits.append(dict(screen='outlier', importer=r, **{'hs6/sector': c}, flow='activity output', value_bn=n / 1000.0,
                                 benchmark_bn=o / 1000.0, ratio=n / o if o > 0 else np.inf, gap_bn=(n - o) / 1000.0,
                                 source_series='io_s12 OUT', detail=why, auto='gtap_rule' if why else ''))
    return hits, pop


def s3_year_jumps(ctx):
    return [], 0


def s4_stale(ctx):
    return [], 0


def s5_identities(ctx):
    io, sectors = ctx['io13'], ctx['sectors']
    agents = list(sectors) + ['p', 'g', 'i']
    hits, pop = [], 0
    for r, g in io.groupby('region'):
        g = g.set_index('row')
        dom = g.loc[[f'dom_{c}' for c in sectors]]
        imp = g.loc[[f'imp_{c}' for c in sectors]]
        cost = g.loc[[x for x in g.index if x != 'OUT'], sectors].sum(axis=0)
        sales = dom[agents].sum(axis=1).to_numpy() + dom['X'].to_numpy() + dom['VST'].to_numpy()
        for k, c in enumerate(sectors):
            pop += 3
            out = g.loc['OUT', c]
            if abs(cost[c] - out) > TOL * max(1.0, abs(out)):
                hits.append(dict(screen='identity', importer=r, **{'hs6/sector': c}, flow='cost = output', value_bn=cost[c] / 1000.0, benchmark_bn=out / 1000.0))
            if abs(sales[k] - out) > TOL * max(1.0, abs(out)):
                hits.append(dict(screen='identity', importer=r, **{'hs6/sector': c}, flow='sales = output', value_bn=sales[k] / 1000.0, benchmark_bn=out / 1000.0))
            u = imp.iloc[k][agents].sum()
            if abs(u - imp.iloc[k]['M']) > TOL * max(1.0, abs(u)):
                hits.append(dict(screen='identity', importer=r, **{'hs6/sector': c}, flow='imported use = M', value_bn=u / 1000.0, benchmark_bn=imp.iloc[k]['M'] / 1000.0))
            if out < -TOL:
                hits.append(dict(screen='identity', importer=r, **{'hs6/sector': c}, flow='output >= 0', value_bn=out / 1000.0))
        for m, kind in ((dom, 'dom'), (imp, 'imp')):
            v = m[agents].to_numpy()
            for i, j in zip(*np.where(v < -TOL)):
                hits.append(dict(screen='identity', importer=r, **{'hs6/sector': sectors[i]}, flow=f'{kind} purchase by {agents[j]} >= 0', value_bn=v[i, j] / 1000.0))
    return hits, pop


def s6_coverage(ctx):
    sectors = ctx['sectors']
    b = _out(ctx['io13'], sectors)
    st, sm = ctx['status'], ctx['smears']
    hits = []
    for r in b.index:
        tot = b.loc[r].sum()
        rep = [c for c in sectors if len(st) and ((st['region'] == r) & (st['sector'] == c) & (st['status'] == 'representative')).any()]
        rv = b.loc[r, rep].sum() if rep else 0.0
        smv = sm.loc[sm['region'] == r, 'value_musd'].sum() if len(sm) else 0.0
        if rv > 0 or smv > 0:
            hits.append(dict(screen='coverage', importer=r, **{'hs6/sector': ' '.join(rep) or 'all'}, flow='representative columns; smears',
                             value_bn=rv / 1000.0, benchmark_bn=tot / 1000.0, ratio=rv / tot if tot > 0 else np.nan,
                             detail=f'smeared prior {smv / 1000:.3f} bn'))
    return hits, len(b)


def s7_moves(ctx):
    prev = ctx.get('prev')
    if prev is None:
        return [], 0
    sectors = ctx['sectors']
    a, b = _out(prev, sectors), _out(ctx['io13'], sectors)
    hits, pop = [], 0
    for r in b.index:
        for c in sectors:
            o = float(a.loc[r, c]) if r in a.index else 0.0
            n = float(b.loc[r, c])
            if o == 0 and n == 0:
                continue
            pop += 1
            d = (n - o) / 1000.0
            if abs(d) > MOVE_BN or (o > 0 and abs(n / o - 1) > MOVE_SHARE and abs(d) > 0.02):
                hits.append(dict(screen='move', importer=r, **{'hs6/sector': c}, flow='activity output', value_bn=n / 1000.0,
                                 benchmark_bn=o / 1000.0, gap_bn=d, source_series='S13 against S13_PREV_OUTPUT'))
    return hits, pop


def s8_icio(ctx):
    g = ctx['gate']
    hits = []
    for x in g[g['share'] > ICIO_GATE].itertuples():
        hits.append(dict(screen='icio_gate', importer=x.region, **{'hs6/sector': 'all'}, flow='intermediate cells moved',
                         value_bn=x.abs_change_musd / 1000.0, benchmark_bn=x.intermediate_s12_musd / 1000.0, ratio=x.share,
                         source_series='io_s12 intermediate use'))
    return hits, len(g)


SCREENS = (('1 benchmark', s1_benchmark), ('2 outliers', s2_outliers), ('3 year jumps', s3_year_jumps),
           ('4 stale years', s4_stale), ('5 identities', s5_identities), ('6 coverage', s6_coverage),
           ('7 moves', s7_moves), ('8 icio gate', s8_icio))


def run(ctx, report_dir=REPORT_DIR, log=print, explanations=EXPLANATIONS, explained=EXPLAINED_SCREENS):
    gdp = (ctx['mt']['GDP_musd'] / 1000.0).to_dict()
    by_key, _ = load_explanations(explanations)
    counts, allhits, missing = [], [], []
    for name, fn in SCREENS:
        hits, pop = fn(ctx)
        for h in hits:
            h['region_gdp_bn'] = gdp.get(h['importer'], 0.0)
            auto = h.pop('auto', '')
            if h['screen'] in explained:
                key = (h['screen'], h['importer'], h['hs6/sector'])
                row = by_key.get(key)
                if row is None and not auto:
                    row = blank_explanation(*key)
                    missing.append(row)
                    by_key[key] = row
                e = auto if row is None else (row.get('evidence class') or 'unexplained').strip()
                h['evidence class'] = e if e in EVIDENCE_CLASSES else 'unexplained'
                h['material'] = 'yes' if material(h.get('gap_bn'), h['region_gdp_bn']) else 'no'
            elif h['screen'] == 'identity':
                h['evidence class'], h['material'] = 'unexplained', 'yes'
            else:
                h['evidence class'], h['material'] = 'diagnostic', ''
        counts.append((name, pop, len(hits)))
        allhits += hits
        write_dicts(f'{report_dir}/screen_{name.split()[0].zfill(2)}_{"_".join(name.split()[1:])}.csv', hits, COLUMNS)
    bad = [h for h in allhits if h['evidence class'] == 'unexplained' and h['material'] == 'yes']
    bad.sort(key=lambda h: -abs(float(h.get('gap_bn') or h.get('value_bn') or 0)))
    write_dicts(f'{report_dir}/unexplained_material.csv', bad, COLUMNS)
    write_dicts(f'{report_dir}/explanation_rows_needed.csv', [m for m in missing if any(
        h['screen'] == m['screen'] and h['importer'] == m['importer'] and h['hs6/sector'] == m['hs6/sector'] and h['material'] == 'yes'
        for h in allhits)], ['importer', 'hs6/sector', 'screen', 'evidence class', 'source file and page', 'decided_by', 'date'])
    lines = ['# S13 population screens', '', '| Screen | Population | Hits |', '|---|---:|---:|']
    lines += [f'| {n} | {p} | {k} |' for n, p, k in counts]
    lines += ['', f'Material: {MATERIAL_BN} bn, or {MATERIAL_SHARE:.0%} of the region\'s GDP. '
              f'{len(bad)} unexplained material hits (screens 1-2 without an explanation row, and every identity hit).', '']
    if bad:
        lines += ['| Screen | Region | Sector | Gap, bn | Ratio | Source |', '|---|---|---|---:|---:|---|']
        for h in bad:
            g = h.get('gap_bn')
            r = h.get('ratio', '')
            lines.append(f"| {h['screen']} | {h['importer']} | {h['hs6/sector']} | {float(g) if g not in ('', None) else 0:.3f} | "
                         f"{f'{r:.3f}' if isinstance(r, float) else r} | {h.get('source_series', '')} |")
    lines += ['', '## Could not check', '']
    if ctx.get('prev') is None:
        lines.append('- Moves: no previous S13 stamp (set S13_PREV_OUTPUT to a copy of a stamped output to compare).')
    lines += ['- Year jumps and stale years: S13 picks no source year; its inputs are stamped stages with their own screens.',
              '- An external benchmark for fitted output by activity: none in the repo for 2022 (GTAP 10 is 2014 and is not a 2022 benchmark).', '']
    os.makedirs(report_dir, exist_ok=True)
    with open(f'{report_dir}/SUMMARY.md', 'w') as fh:
        fh.write('\n'.join(lines))
    summary = '; '.join(f'{n}: {k}/{p}' for n, p, k in counts) + f'; material unexplained {len(bad)}'
    log('screens ' + summary)
    return dict(material_unexplained=len(bad), summary=summary, hits=allhits, unexplained=bad)
