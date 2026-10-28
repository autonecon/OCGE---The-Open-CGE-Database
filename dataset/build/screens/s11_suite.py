"""S11 population screens (dataset/docs/SCREENS.md seven questions on the energy variables).

The stage calls run() with the arrays it built, so every screen sees the volumes, prices and
trade the stamp booked. Reports go to dataset/reviews/screens/S11/; nothing is written under
the stage output, so a screen run does not change SHA256SUMS.

1 benchmark   production volume x export price against EI 2025 country production (PREP crosscheck)
2 outliers    export unit values outside 0.5x to 2x the median export price of the commodity
3 year_jump   EIA INTL 2022 regional volume against 2021 on the same series: above 3x or below 1/3
4 stale       volume or price source year before 2019 (diagnostic)
5 identities  CIF >= FOB, VMSB >= CIF, tm >= 0, margin rate >= 0, VMSB = CIF x (1 + tm) (any hit fails)
6 coverage    share of the region's S11 energy exports carried by a filled volume or a filled price (diagnostic)
7 moves       region x commodity FOB exports and imports against the S10 input values (diagnostic)
8 seeds       RAS cells that come from a seed and carry more than 0.1 bn (diagnostic, S11 only)
9 gas_tonnes  gas exporters whose BACI tonnes (at 1.36 bcm per Mt) give under 2/3 of their volume-source exports
              while their export price is still the BACI unit value: the tonnes may be a Comtrade estimate, which
              inflates the unit value (TKM fix round). Exporters priced from an observed volume are listed as
              gas_tonnes_observed (diagnostic).

Screens 1, 2, 3 and 9 need an explanation row in config/s11/screen_explanations.csv when a hit is
material: 0.1 bn of value, or 1 percent of the region's S11 energy trade (screen_materiality).
In that file the `importer` column holds the region and `hs6/sector` the commodity.
"""
import json
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET = os.path.dirname(BUILD)
if BUILD not in sys.path:
    sys.path.insert(0, BUILD)

from screens.common import EVIDENCE_CLASSES, load_explanations, blank_explanation, write_dicts  # noqa: E402

EXPLANATIONS = BUILD + '/config/s11/screen_explanations.csv'
REPORT_DIR = DATASET + '/reviews/screens/S11'
MATERIAL_BN = 0.1
MATERIAL_SHARE = 0.01
RATIO_LO, RATIO_HI, GAP_BN = 0.5, 1.5, 0.05
OUT_LO, OUT_HI = 0.5, 2.0
JUMP_FACTOR = 3.0
STALE_BEFORE = 2019
MOVE_SHARE, MOVE_BN = 0.10, 0.1
SEED_BN = 0.1
TONNES_SHARE = 2.0 / 3.0
EXPLAINED_SCREENS = ('benchmark', 'outlier', 'year_jump', 'gas_tonnes')
FROM_PREP_NAME = {'coal': 'coa', 'crude': 'oil', 'gas': 'gas', 'refined': 'pet', 'electricity': 'ely'}
BENCHMARK = {'ei_coal_production': 'coa', 'ei_crude_production': 'oil', 'ei_gas_production': 'gas',
             'ei_refinery_throughput': 'pet', 'ei_elec_production': 'ely'}
EIA_FAMILY = {('7', '1'): ('coa', 'production', 1 / 1000), ('7', '3'): ('coa', 'imports', 1 / 1000),
              ('7', '4'): ('coa', 'exports', 1 / 1000), ('57', '1'): ('oil', 'production', 365 / 1000),
              ('26', '1'): ('gas', 'production', 1.0), ('26', '3'): ('gas', 'imports', 1.0),
              ('26', '4'): ('gas', 'exports', 1.0), ('2', '12'): ('ely', 'production', 1.0),
              ('2', '3'): ('ely', 'imports', 1.0), ('2', '4'): ('ely', 'exports', 1.0)}
COLUMNS = ['screen', 'importer', 'hs6/sector', 'flow', 'value_bn', 'benchmark_bn', 'ratio', 'gap_bn', 'region_trade_bn',
           'source_series', 'evidence class', 'material', 'detail']


def material(gap_bn, region_trade_bn):
    g = abs(float(gap_bn))
    return g >= MATERIAL_BN or (region_trade_bn > 0 and g >= MATERIAL_SHARE * region_trade_bn)


def eia_years(intl_path, series, years=('2021', '2022')):
    """{series_id: {year: value}} for the given EIA INTL annual series."""
    out = {}
    with open(intl_path) as fh:
        for line in fh:
            i = line.find('"series_id":"')
            if i < 0:
                continue
            sid = line[i + 13:line.find('"', i + 13)]
            if sid not in series:
                continue
            obj = json.loads(line)
            out[sid] = {str(y): float(v) for y, v in obj.get('data') or [] if str(y) in years and isinstance(v, (int, float))}
    return out


def s1_benchmark(ctx):
    """Every region compared with EI in the PREP crosscheck; ratio = S11 / EI. A region not in the
    over-5-percent file is within 5 percent and so inside the band."""
    disc = pd.read_csv(ctx['prep_dir'] + '/discrepancies_over_5pct.csv')
    summ = pd.read_csv(ctx['prep_dir'] + '/crosscheck_summary.csv').set_index('comparison')
    R, V = ctx['R'], ctx['V'].set_index(['region', 'commodity'])
    hits, pop = [], 0
    for comp, c in BENCHMARK.items():
        pop += int(summ.loc[comp, 'n_regions_compared'])
        d = disc[disc['comparison'] == comp]
        f = ctx['from_prep'][c]
        for row in d.itertuples():
            if row.region not in V.index.get_level_values(0):
                continue
            p = float(V.loc[(row.region, c), 'export_price'])
            val = row.chosen_value * f * p / 1000.0
            ben = row.other_value * f * p / 1000.0
            ratio = val / ben if ben > 0 else np.inf
            gap = val - ben
            if (ratio < RATIO_LO or ratio > RATIO_HI) and abs(gap) > GAP_BN:
                hits.append(dict(screen='benchmark', importer=row.region, **{'hs6/sector': c}, flow='production',
                                 value_bn=val, benchmark_bn=ben, ratio=ratio, gap_bn=gap,
                                 source_series=f'{row.chosen_source} vs {comp} (same_concept {row.same_concept})',
                                 detail=str(summ.loc[comp, 'concept_note'])[:300]))
    return hits, pop


def s2_outliers(ctx):
    hits, pop = [], 0
    R, px, psrc, filled, exi = ctx['R'], ctx['px'], ctx['psrc'], ctx['pfill'], ctx['exi']
    for c in ctx['comms']:
        x = exi[c].sum(1)
        own = (x > 0) & ~filled[c]
        if not own.any():
            continue
        ref = float(np.median(px[c][own]))      # median of the exporters with their own price: one outlier cannot move it
        for i in np.where(own)[0]:
            pop += 1
            ratio = px[c][i] / ref
            if ratio < OUT_LO or ratio > OUT_HI:
                gap = x[i] * (px[c][i] - ref) / 1000.0
                hits.append(dict(screen='outlier', importer=R[i], **{'hs6/sector': c}, flow='export_price',
                                 value_bn=x[i] * px[c][i] / 1000.0, benchmark_bn=x[i] * ref / 1000.0, ratio=ratio, gap_bn=gap,
                                 source_series=psrc[c][i], detail=f'price {px[c][i]:.2f} vs median exporter {ref:.2f} ({ctx["price_unit"][c]})'))
    return hits, pop


def s3_year_jumps(ctx):
    vc = pd.read_csv(ctx['prep_dir'] + '/volumes_country_2022.csv')
    vc = vc[vc['source'] == 'eia']
    fam = vc['series_id'].str.extract(r'^INTL\.(\d+)-(\d+)-')
    vc = vc.assign(prod=fam[0], act=fam[1])
    vc = vc[[(p, a) in EIA_FAMILY for p, a in zip(vc['prod'], vc['act'])]]
    data = eia_years(ctx['intl_path'], set(vc['series_id']))
    agg = defaultdict(lambda: [0.0, 0.0, 0])
    for row in vc.itertuples():
        c, flow, f = EIA_FAMILY[(row.prod, row.act)]
        d = data.get(row.series_id, {})
        if '2021' not in d or '2022' not in d:
            continue
        a = agg[(row.region, c, flow)]
        a[0] += d['2021'] * f
        a[1] += d['2022'] * f
        a[2] += 1
    V = ctx['V'].set_index(['region', 'commodity'])
    hits = []
    for (r, c, flow), (y1, y2, n) in sorted(agg.items()):
        if (r, c) not in V.index:
            continue
        p = float(V.loc[(r, c), 'export_price'])
        jump = (y1 > 0 and (y2 > JUMP_FACTOR * y1 or y2 < y1 / JUMP_FACTOR)) or (y1 == 0 and y2 > 0)
        if jump:
            gap = (y2 - y1) * p / 1000.0
            hits.append(dict(screen='year_jump', importer=r, **{'hs6/sector': c}, flow=flow, value_bn=y2 * p / 1000.0,
                             benchmark_bn=y1 * p / 1000.0, ratio=(y2 / y1) if y1 > 0 else np.inf, gap_bn=gap,
                             source_series=f'EIA INTL {flow} 2022 vs 2021, {n} countries',
                             detail=f'2021 {y1:.4g}, 2022 {y2:.4g} {ctx["unit"][c]}'))
    return hits, len(agg)


def s4_stale(ctx):
    vc = pd.read_csv(ctx['prep_dir'] + '/volumes_country_2022.csv')
    st = vc[vc['year'] < STALE_BEFORE]
    hits = [dict(screen='stale', importer=r.region, **{'hs6/sector': FROM_PREP_NAME[r.commodity]}, flow=r.flow,
                 value_bn='', source_series=r.series_id, detail=f'year {r.year}') for r in st.itertuples()]
    return hits, len(vc)


def s5_identities(ctx):
    hits, pop = [], 0
    R = ctx['R']
    for c in ctx['comms']:
        fob, cif, vmsb, tm, mr = ctx['new_fob'][c], ctx['new_cif'][c], ctx['new_vmsb'][c], ctx['tmd'][c], ctx['mrate'][c]
        on = fob > 0
        pop += int(on.sum())
        tests = (('cif_below_fob', cif < fob - 1e-9), ('vmsb_below_cif', vmsb < cif - 1e-9), ('negative_tm', tm < 0),
                 ('negative_margin_rate', mr < 0),
                 ('vmsb_ne_cif_x_1_plus_tm', np.abs(vmsb - cif * (1 + tm)) > 1e-9 * np.maximum(vmsb, 1.0)))
        for name, bad in tests:
            for i, j in np.argwhere(bad & on):
                hits.append(dict(screen='identity', importer=R[j], **{'hs6/sector': c}, flow=name,
                                 value_bn=fob[i, j] / 1000.0, detail=f'exporter {R[i]}'))
    return hits, pop


def s6_coverage(ctx):
    R, exi, px, filled = ctx['R'], ctx['exi'], ctx['px'], ctx['pfill']
    vfill = {(f['region'], f['commodity'], f['flow']) for f in ctx['fill_rows']}
    hits = []
    for i, r in enumerate(R):
        tot = cov = 0.0
        parts = []
        for c in ctx['comms']:
            x = exi[c][i].sum() * px[c][i]
            tot += x
            why = []
            if filled[c][i]:
                why.append('price')
            if (r, c, 'exports') in vfill:
                why.append('volume')
            if why and x > 0:
                cov += x
                parts.append(f'{c} {"+".join(why)} {x / 1000:.3f} bn')
        if cov > 0:
            hits.append(dict(screen='coverage', importer=r, **{'hs6/sector': 'all'}, flow='exports', value_bn=cov / 1000.0,
                             benchmark_bn=tot / 1000.0, ratio=cov / tot if tot > 0 else np.nan, detail='; '.join(parts)))
    return hits, len(R)


def s7_moves(ctx):
    R, old, new = ctx['R'], ctx['old_fob'], ctx['new_fob']
    hits, pop = [], 0
    for c in ctx['comms']:
        for i, r in enumerate(R):
            for flow, a, b in (('exports', old[c][i].sum(), new[c][i].sum()), ('imports', old[c][:, i].sum(), new[c][:, i].sum())):
                if a <= 0 and b <= 0:
                    continue
                pop += 1
                d = (b - a) / 1000.0
                if abs(d) > MOVE_BN or (a > 0 and abs(b / a - 1) > MOVE_SHARE and abs(d) > 0.02):
                    hits.append(dict(screen='move', importer=r, **{'hs6/sector': c}, flow=flow, value_bn=b / 1000.0,
                                     benchmark_bn=a / 1000.0, ratio=b / a if a > 0 else np.inf, gap_bn=d,
                                     source_series='S11 FOB vs S10 vfob_s10 (ely: BACI HS 271600)'))
    return hits, pop


def s8_seeds(ctx):
    R = ctx['R']
    hits, pop = [], 0
    for c in ctx['comms']:
        sd, fob = ctx['seeded'][c], ctx['new_fob'][c]
        pop += int(sd.sum())
        for i, j in np.argwhere(sd & (fob > SEED_BN * 1000)):
            hits.append(dict(screen='seed', importer=R[j], **{'hs6/sector': c}, flow=f'from {R[i]}', value_bn=fob[i, j] / 1000.0,
                             detail='cell has no S10 trade; value from the ras_seed after RAS'))
    return hits, pop


def s9_gas_tonnes(ctx):
    """Gas exporters still on the BACI unit value whose BACI tonnes give under TONNES_SHARE of their volume-source
    exports. benchmark_bn prices the S11 export volume at BACI value / volume-source exports instead; the gap is
    the overstatement if the tonnes, not the value, are short."""
    hits, pop = [], 0
    gt = ctx.get('gas_tonnes')
    if gt is None or 'gas' not in ctx['comms']:
        return hits, pop
    R, px = ctx['R'], ctx['px']['gas']
    ix = {r: i for i, r in enumerate(R)}
    x = ctx['exi']['gas'].sum(1)
    for t in gt.itertuples():
        if not (t.baci_value_musd > 0 and np.isfinite(t.bcm_ratio)):
            continue
        pop += 1
        i = ix[t.region]
        alt = t.baci_value_musd / t.volume_exports_bcm
        row = dict(importer=t.region, **{'hs6/sector': 'gas'}, flow='export_price', value_bn=x[i] * px[i] / 1000.0,
                   benchmark_bn=x[i] * alt / 1000.0, ratio=t.bcm_ratio, gap_bn=x[i] * (px[i] - alt) / 1000.0,
                   source_series=ctx['psrc']['gas'][i],
                   detail=f'BACI {t.baci_value_musd:.1f} USD m on {t.baci_bcm:.3f} bcm against {t.volume_exports_bcm:.3f} bcm exports; '
                          f'price {px[i]:.1f}, value over volume {alt:.1f} USD m/bcm')
        if t.observed_price:
            hits.append(dict(row, screen='gas_tonnes_observed'))
        elif t.bcm_ratio < TONNES_SHARE:
            hits.append(dict(row, screen='gas_tonnes'))
    return hits, pop


SCREENS = (('1 benchmark', s1_benchmark), ('2 outliers', s2_outliers), ('3 year jumps', s3_year_jumps),
           ('4 stale years', s4_stale), ('5 identities', s5_identities), ('6 coverage', s6_coverage),
           ('7 moves vs S10', s7_moves), ('8 RAS seeds', s8_seeds), ('9 gas tonnes', s9_gas_tonnes))


def run(ctx, report_dir=REPORT_DIR, log=print, explanations=EXPLANATIONS):
    R = ctx['R']
    trade = {r: 0.0 for r in R}
    for c in ctx['comms']:
        for i, r in enumerate(R):
            trade[r] += (ctx['new_fob'][c][i].sum() + ctx['new_fob'][c][:, i].sum()) / 1000.0
    by_key, _ = load_explanations(explanations)
    counts, allhits, missing = [], [], []
    for name, fn in SCREENS:
        hits, pop = fn(ctx)
        for h in hits:
            h['region_trade_bn'] = trade.get(h['importer'], 0.0)
            if h['screen'] in EXPLAINED_SCREENS:
                key = (h['screen'], h['importer'], h['hs6/sector'])
                row = by_key.get(key)
                if row is None:
                    row = blank_explanation(*key)
                    missing.append(row)
                    by_key[key] = row
                ev = (row.get('evidence class') or 'unexplained').strip()
                h['evidence class'] = ev if ev in EVIDENCE_CLASSES else 'unexplained'
                h['material'] = 'yes' if material(h['gap_bn'], h['region_trade_bn']) else 'no'
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
    write_dicts(f'{report_dir}/explanation_rows_needed.csv', missing,
                ['importer', 'hs6/sector', 'screen', 'evidence class', 'source file and page', 'decided_by', 'date'])
    lines = ['# S11 population screens', '', '| Screen | Population | Hits |', '|---|---:|---:|']
    lines += [f'| {n} | {p} | {k} |' for n, p, k in counts]
    lines += ['', f'Material: {MATERIAL_BN} bn or {MATERIAL_SHARE:.0%} of the region\'s S11 energy trade. '
              f'{len(bad)} unexplained material hits (screens 1-3 and 9 without an explanation row, and every identity hit).', '']
    if bad:
        lines += ['| Screen | Region | Commodity | Flow | Gap, bn | Ratio | Source |', '|---|---|---|---|---:|---:|---|']
        for h in bad:
            g = h.get('gap_bn')
            lines.append(f"| {h['screen']} | {h['importer']} | {h['hs6/sector']} | {h['flow']} | "
                         f"{float(g) if g not in ('', None) else 0:.3f} | {h.get('ratio', '')} | {h.get('source_series', '')} |")
    lines += ['', '## Could not check', '',
              '- Year jumps for JODI and UNSD volumes (crude and refined trade, refined production): no 2021 value in the repo extracts.',
              '- Prices have one year (2022) in every source, so prices have no year-jump screen.', '']
    os.makedirs(report_dir, exist_ok=True)
    with open(f'{report_dir}/SUMMARY.md', 'w') as fh:
        fh.write('\n'.join(lines))
    summary = '; '.join(f'{n}: {k}/{p}' for n, p, k in counts) + f'; material unexplained {len(bad)}'
    log('screens ' + summary)
    return dict(material_unexplained=len(bad), summary=summary, hits=allhits, unexplained=bad)
