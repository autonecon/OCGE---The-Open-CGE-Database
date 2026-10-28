"""S12 population screens (dataset/docs/SCREENS.md seven questions on the factor variables).

The stage calls run() with the frames it built, so every screen sees the factor payments the stamp
booked. Reports go to dataset/reviews/screens/S12/; nothing is written under the stage output, so a
screen run does not change SHA256SUMS.

1 benchmark   region labour compensation against the national-accounts total D1/(D1+B2A3G) x region VA
              (FIGARO 2022 all industries, else OECD Table 6 total economy at the base year)
2 outliers    region x sector labour share of factor income (EVFP, VA net of the output tax) below 0.05 or above 0.95 in a cell of 0.1 bn VA or more
3 year_jump   sector labour share from the chosen national-accounts year against the latest earlier year
              in the repo on the same codes (FIGARO 2017; Table 6 latest earlier year): above 3x or 50 points
4 stale       ILOSTAT window or Table 6 year before 2019 (diagnostic)
5 identities  EVFP = VA, EVFB = EVFP - ftax, EVOS = EVFB - itax, labour share in [0,1], natres within
              non-labour income (WDI rule) or value added (ch.12.A rule), non-negative tax rates (any hit fails)
6 coverage    share of region VA split by a donor and of labour paid on F16c group shares (diagnostic)
7 moves       region x sector x factor EVFP against S12_PREV_OUTPUT when set (diagnostic)
8 natres      rent capped at non-labour income (WDI rule), or the share held by the guard (ch.12.A rule; diagnostic)

Screens 1, 2 and 3 need an explanation row in config/s12/screen_explanations.csv when a hit is
material: 0.1 bn of labour compensation, or 1 percent of the region's labour compensation.
In that file the `importer` column holds the region and `hs6/sector` the sector ('all' for screen 1).
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

EXPLANATIONS = BUILD + '/config/s12/screen_explanations.csv'
REPORT_DIR = DATASET + '/reviews/screens/S12'
MATERIAL_BN = 0.1
MATERIAL_SHARE = 0.01
RATIO_LO, RATIO_HI, GAP_BN = 0.5, 1.5, 0.05
SHARE_LO, SHARE_HI, CELL_BN = 0.05, 0.95, 0.1
JUMP_FACTOR, JUMP_POINTS = 3.0, 0.5
STALE_BEFORE = 2019
MOVE_SHARE, MOVE_BN = 0.10, 0.1
TOL = 1e-6
EXPLAINED_SCREENS = ('benchmark', 'outlier', 'year_jump')
COLUMNS = ['screen', 'importer', 'hs6/sector', 'flow', 'value_bn', 'benchmark_bn', 'ratio', 'gap_bn', 'region_labour_bn',
           'source_series', 'evidence class', 'material', 'detail']


def material(gap_bn, region_labour_bn):
    g = abs(float(gap_bn or 0))
    return g >= MATERIAL_BN or (region_labour_bn > 0 and g >= MATERIAL_SHARE * region_labour_bn)


def s1_benchmark(ctx):
    """ratio = S12 labour compensation / (national D1/(D1+B2A3G) x region VA), for every ICIO region with
    a national total at the base year."""
    vr, nat = ctx['va_rows'], ctx['national_share']
    g = vr.groupby('region')[['va_musd', 'labour_musd']].sum()
    hits, pop = [], 0
    for r, (share, src) in nat.items():
        if r not in g.index or g.loc[r, 'va_musd'] <= 0:
            continue
        pop += 1
        lab, bench = g.loc[r, 'labour_musd'] / 1000.0, share * g.loc[r, 'va_musd'] / 1000.0
        ratio = lab / bench if bench > 0 else np.inf
        if (ratio < RATIO_LO or ratio > RATIO_HI) and abs(lab - bench) > GAP_BN:
            hits.append(dict(screen='benchmark', importer=r, **{'hs6/sector': 'all'}, flow='labour', value_bn=lab,
                             benchmark_bn=bench, ratio=ratio, gap_bn=lab - bench, source_series=src,
                             detail=f'S12 split: {ctx["lam_src"].get(r, "")}'))
    return hits, pop


def s2_outliers(ctx):
    vr = ctx['va_rows']
    c = vr[(vr['va_musd'] >= CELL_BN * 1000) & vr['labour_share'].notna()]
    med = c.groupby('sector')['labour_share'].median()
    hits = []
    for x in c[(c['labour_share'] < SHARE_LO) | (c['labour_share'] > SHARE_HI)].itertuples():
        v = x.va_musd / 1000.0
        hits.append(dict(screen='outlier', importer=x.region, **{'hs6/sector': x.sector}, flow='labour share',
                         value_bn=x.labour_musd / 1000.0, benchmark_bn=med[x.sector] * v, ratio=x.labour_share,
                         gap_bn=(x.labour_share - med[x.sector]) * v, source_series=x.source,
                         detail=f'VA {v:.3f} bn; median share of the sector {med[x.sector]:.3f}; {ctx["cell_note"].get((x.region, x.sector), "")}'))
    return hits, len(c)


def s3_year_jumps(ctx):
    vr = ctx['va_rows'].set_index(['region', 'sector'])
    hits, pop = [], 0
    for (c, s), (now, prev, src) in ctx['share_years'].items():
        if now is None or prev is None:
            continue
        pop += 1
        if (prev > 0 and now > JUMP_FACTOR * prev) or abs(now - prev) > JUMP_POINTS:
            v = vr.loc[(c, s), 'va_musd'] / 1000.0 if (c, s) in vr.index else 0.0
            hits.append(dict(screen='year_jump', importer=c, **{'hs6/sector': s}, flow='labour share', value_bn=now * v,
                             benchmark_bn=prev * v, ratio=now / prev if prev > 0 else np.inf, gap_bn=(now - prev) * v,
                             source_series=src, detail=f'share {now:.3f} against {prev:.3f}'))
    return hits, pop


def s4_stale(ctx):
    hits, pop = [], 0
    lab = ctx['ev'][ctx['ev']['factor'].isin(ctx['labour5'])].groupby('region')['evfp'].sum() / 1000.0
    for x in ctx['lmeta'].itertuples():
        if x.status != 'used':
            continue
        pop += 1
        last = max(map(int, str(x.years).split()))
        if last < STALE_BEFORE:
            hits.append(dict(screen='stale', importer=x.iso3, **{'hs6/sector': 'all'}, flow='labour groups',
                             value_bn=lab.get(x.iso3, np.nan), source_series='ILOSTAT', detail=f'window {x.years}'))
    for r, src in ctx['lam_src'].items():
        if 'OECD Table 6' in src:
            pop += 1
            y = int(src.split('Table 6 ')[1][:4])
            if y < STALE_BEFORE:
                hits.append(dict(screen='stale', importer=r, **{'hs6/sector': 'all'}, flow='VA split',
                                 value_bn=lab.get(r, np.nan), source_series=src, detail=f'year {y}'))
    return hits, pop


def s5_identities(ctx):
    ev, va = ctx['ev'], ctx['va_long']
    hits = []
    s = ev.groupby(['region', 'sector'])['evfp'].sum().rename('sum').reset_index().merge(va, on=['region', 'sector'], how='outer').fillna(0.0)
    for x in s[(s['sum'] - s['va']).abs() > TOL * np.maximum(1.0, s['va'].abs())].itertuples():
        hits.append(dict(screen='identity', importer=x.region, **{'hs6/sector': x.sector}, flow='EVFP = VA',
                         value_bn=x.sum / 1000.0, benchmark_bn=x.va / 1000.0, gap_bn=(x.sum - x.va) / 1000.0))
    for name, a, b in (('EVFB = EVFP - ftax', ev['evfb'], ev['evfp'] - ev['ftax']), ('EVOS = EVFB - itax', ev['evos'], ev['evfb'] - ev['itax'])):
        bad = (a - b).abs() > TOL * np.maximum(1.0, b.abs())
        for x in ev[bad].itertuples():
            hits.append(dict(screen='identity', importer=x.region, **{'hs6/sector': x.sector}, flow=f'{name} ({x.factor})'))
    vr = ctx['va_rows']
    for x in vr[(vr['labour_share'] < -TOL) | (vr['labour_share'] > 1 + TOL)].itertuples():
        hits.append(dict(screen='identity', importer=x.region, **{'hs6/sector': x.sector}, flow='labour share in [0,1]', ratio=x.labour_share))
    nr = ctx['natres']
    # the base the rule draws on: non-labour income under the WDI rent rule, all factor VA under ch.12.A (fix round B16)
    base = nr['natres_base_musd'] if 'natres_base_musd' in nr.columns else nr['nonlabour_musd']
    what = 'value added' if 'natres_base_musd' in nr.columns else 'non-labour income'
    over = nr['natres_musd'] > np.maximum(base, 0) + TOL
    for x, b in zip(nr[over].itertuples(), base[over]):
        hits.append(dict(screen='identity', importer=x.region, **{'hs6/sector': x.sector}, flow=f'natres within {what}',
                         value_bn=x.natres_musd / 1000.0, benchmark_bn=b / 1000.0))
    rt = ctx['rates']
    for col in ('ssc_rate_on_labour_evfp', 'payroll_property_rate_on_evfp'):
        for x in rt[rt[col] < -TOL].itertuples():
            hits.append(dict(screen='identity', importer=x.region, **{'hs6/sector': 'all'}, flow=f'{col} >= 0', ratio=getattr(x, col)))
    return hits, len(ev) * 3 + len(vr) + len(nr) + 2 * len(rt)


def s6_coverage(ctx):
    vr, ev = ctx['va_rows'], ctx['ev']
    hits = []
    labr = ev[ev['factor'].isin(ctx['labour5'])].groupby('region')['evfp'].sum()
    for r, g in vr.groupby('region'):
        tot = g['va_musd'].clip(lower=0).sum()
        donor = g[g['source'].str.startswith(('donor', 'S05 donors')) | np.array([(r, s) in ctx['sector_donor'] for s in g['sector']], bool)]
        d = donor['va_musd'].clip(lower=0).sum()
        f16 = ctx['lab_src'].get(r, '').startswith('F16c')
        if d > 0 or f16:
            hits.append(dict(screen='coverage', importer=r, **{'hs6/sector': 'all'}, flow='VA split by a donor; labour groups',
                             value_bn=d / 1000.0, benchmark_bn=tot / 1000.0, ratio=d / tot if tot > 0 else np.nan,
                             source_series=ctx['lam_src'].get(r, ''),
                             detail=f'labour groups: {ctx["lab_src"].get(r, "")}; labour {labr.get(r, 0) / 1000:.3f} bn'))
    return hits, vr['region'].nunique()


def s7_moves(ctx):
    prev = ctx.get('prev')
    if prev is None:
        return [], 0
    a = prev.set_index(['region', 'sector', 'factor'])['evfp']
    b = ctx['ev'].set_index(['region', 'sector', 'factor'])['evfp']
    j = pd.concat([a.rename('old'), b.rename('new')], axis=1).fillna(0.0)
    j = j[(j['old'].abs() > 0) | (j['new'].abs() > 0)]
    hits = []
    for (r, s, f), x in j.iterrows():
        d = (x['new'] - x['old']) / 1000.0
        if abs(d) > MOVE_BN or (x['old'] > 0 and abs(x['new'] / x['old'] - 1) > MOVE_SHARE and abs(d) > 0.02):
            hits.append(dict(screen='move', importer=r, **{'hs6/sector': s}, flow=f, value_bn=x['new'] / 1000.0,
                             benchmark_bn=x['old'] / 1000.0, gap_bn=d, source_series='S12 against S12_PREV_OUTPUT'))
    return hits, len(j)


def s8_natres(ctx):
    nr = ctx['natres']
    hits = []
    if 'rule' in nr.columns and (nr['rule'] == 'gtap_ch12a').all():      # fix round B16: the guarded cells
        for x in nr[nr['guard'].astype(bool) & (nr['factor_va_musd'] > 0)].itertuples():
            hits.append(dict(screen='natres', importer=x.region, **{'hs6/sector': x.sector}, flow='natres share held by the guard',
                             value_bn=x.natres_musd / 1000.0, benchmark_bn=x.factor_va_musd / 1000.0, ratio=x.natres_share_of_va,
                             source_series=x.series, detail=f'theta_VA {x.theta_va:.4f} below the floor {x.theta_va_used}; implied eta {x.eta_implied:.3f} '
                             f'against the target {x.eta_target}'))
        return hits, len(nr)
    for x in nr[nr['capped']].itertuples():
        hits.append(dict(screen='natres', importer=x.region, **{'hs6/sector': x.sector}, flow='rent capped',
                         value_bn=x.rent_booked_at_s11_output_musd / 1000.0, benchmark_bn=x.rent_musd / 1000.0,
                         gap_bn=(x.rent_booked_at_s11_output_musd - x.rent_musd) / 1000.0, source_series=x.series,
                         detail=f'net operating surplus (non-labour income less CFC) at S11 output {x.nonlabour_at_s11_output_musd / 1000:.3f} bn'))
    return hits, len(nr)


SCREENS = (('1 benchmark', s1_benchmark), ('2 outliers', s2_outliers), ('3 year jumps', s3_year_jumps),
           ('4 stale years', s4_stale), ('5 identities', s5_identities), ('6 coverage', s6_coverage),
           ('7 moves', s7_moves), ('8 natres caps', s8_natres))


def run(ctx, report_dir=REPORT_DIR, log=print, explanations=EXPLANATIONS):
    ev = ctx['ev']
    labour = (ev[ev['factor'].isin(ctx['labour5'])].groupby('region')['evfp'].sum() / 1000.0).to_dict()
    by_key, _ = load_explanations(explanations)
    counts, allhits, missing = [], [], []
    for name, fn in SCREENS:
        hits, pop = fn(ctx)
        for h in hits:
            h['region_labour_bn'] = labour.get(h['importer'], 0.0)
            if h['screen'] in EXPLAINED_SCREENS:
                key = (h['screen'], h['importer'], h['hs6/sector'])
                row = by_key.get(key)
                if row is None:
                    row = blank_explanation(*key)
                    missing.append(row)
                    by_key[key] = row
                e = (row.get('evidence class') or 'unexplained').strip()
                h['evidence class'] = e if e in EVIDENCE_CLASSES else 'unexplained'
                h['material'] = 'yes' if material(h.get('gap_bn'), h['region_labour_bn']) else 'no'
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
    lines = ['# S12 population screens', '', '| Screen | Population | Hits |', '|---|---:|---:|']
    lines += [f'| {n} | {p} | {k} |' for n, p, k in counts]
    lines += ['', f'Material: {MATERIAL_BN} bn of labour compensation or {MATERIAL_SHARE:.0%} of the region\'s labour compensation. '
              f'{len(bad)} unexplained material hits (screens 1-3 without an explanation row, and every identity hit).', '']
    if bad:
        lines += ['| Screen | Region | Sector | Gap, bn | Ratio | Source |', '|---|---|---|---:|---:|---|']
        for h in bad:
            g = h.get('gap_bn')
            r = h.get('ratio', '')
            lines.append(f"| {h['screen']} | {h['importer']} | {h['hs6/sector']} | {float(g) if g not in ('', None) else 0:.3f} | "
                         f"{f'{r:.3f}' if isinstance(r, float) else r} | {h.get('source_series', '')} |")
    lines += ['', '## Could not check', '']
    if ctx.get('prev') is None:
        lines.append('- Moves: no previous S12 stamp (set S12_PREV_OUTPUT to a copy of a stamped output to compare).')
    lines += ['- Benchmark for regions with no national-accounts total (donor-built and composite regions): none in the repo.',
              '- Year jumps for the ILOSTAT labour-group shares: the window average is the GTAP rule (ch.14B p.6), so no single earlier year is compared.', '']
    os.makedirs(report_dir, exist_ok=True)
    with open(f'{report_dir}/SUMMARY.md', 'w') as fh:
        fh.write('\n'.join(lines))
    summary = '; '.join(f'{n}: {k}/{p}' for n, p, k in counts) + f'; material unexplained {len(bad)}'
    log('screens ' + summary)
    return dict(material_unexplained=len(bad), summary=summary, hits=allhits, unexplained=bad)
