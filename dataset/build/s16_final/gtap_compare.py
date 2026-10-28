"""S16 helpers: the S10 and S11 route border values, and the internal QA against GTAP 10 shares (PLAN §3(k) "QA vs GTAP",
report-only, never an input).

The comparison is of shares, so the base years (2014 for GTAP 10, 2022 here) and the price levels drop out: for each
single-economy region in both data bases, the share of each sector in the region's value added and exports, and the net
product tax rate of each sector (net tax over purchases at basic prices). Sectors are compared on the coarsest common grouping of config/s01/gtap65_to_sector.csv (a GTAP
sector split into several of ours, or several merged into one, form one group). The table holds GTAP values, so it
is written outside git (S16_PRIVATE_DIR); the stage records counts only.
"""
import numpy as np
import pandas as pd


def border_values(gx, gm, ex, em, energy):
    """Route border values S14 merged: S10 goods (vfob_s10, vmsb_s10) without the energy rows, and S11 energy.
    Returns comm, src, dst, vfob, vcif, vmsb."""
    def part(x, m):
        x = x.rename(columns={'sector': 'comm', 'exporter': 'src', 'importer': 'dst', 'vfob_musd': 'vfob'})[['comm', 'src', 'dst', 'vfob']]
        m = m.rename(columns={'sector': 'comm', 'exporter': 'src', 'importer': 'dst', 'vcif_musd': 'vcif', 'vmsb_musd': 'vmsb'})[['comm', 'src', 'dst', 'vcif', 'vmsb']]
        return x.merge(m, on=['comm', 'src', 'dst'], how='outer').fillna(0.0)
    goods = part(gx[~gx['sector'].isin(energy)], gm[~gm['sector'].isin(energy)])
    return pd.concat([goods, part(ex, em)], ignore_index=True)


def common_groups(conc):
    """Connected components of the GTAP-code / our-sector links: {gtap code: group}, {our sector: group}."""
    links = [(r.gtap_code.lower(), s) for r in conc.itertuples() for s in str(r.sectors).split(';') if s]
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for g, s in links:
        parent[find('g:' + g)] = find('s:' + s)
    comp = {}
    for g, s in links:
        comp.setdefault(find('s:' + s), set()).update({'g:' + g, 's:' + s})
    name = {}
    for root, mem in comp.items():
        ours = sorted(m[2:] for m in mem if m.startswith('s:'))
        label = '+'.join(ours)
        for m in mem:
            name[m] = label
    return ({k[2:]: v for k, v in name.items() if k.startswith('g:')}, {k[2:]: v for k, v in name.items() if k.startswith('s:')})


# ------------------------------------------------------------------ the full comparison (David, 2026-10-24: compare thoroughly)
FACTOR_GROUP = {'land': 'land', 'capital': 'capital', 'natres': 'natres', 'natlres': 'natres', 'unsklab': 'labour', 'sklab': 'labour',
                'off_mgr_pros': 'labour', 'tech_aspros': 'labour', 'clerks': 'labour', 'service_shop': 'labour', 'ag_othlowsk': 'labour'}


def _gsum(a, axis, groups):
    """Sum array a over `axis` by labels `groups` (same length as that axis); the grouped axis comes first."""
    a = np.moveaxis(np.asarray(a, float), axis, 0)
    labs = sorted(set(groups))
    out = np.stack([a[[i for i, g in enumerate(groups) if g == l]].sum(axis=0) for l in labs])
    return labs, out


def _div(a, b):
    return np.where(np.abs(b) > 1e-9, a / np.where(np.abs(b) > 1e-9, b, 1.0), np.nan)


def measures(D, comm_g, acts_g, endw_g, reg_g):
    """Every comparison measure of one data base, long form: measure, kind (share, rate, ratio), item, region, value,
    weight. The weight is the item's share of what the measure is taken over in that region (a share's own value; a
    rate's share of the region's base; 1 for the macro ratios), for the materiality screen.
    comm_g / acts_g / endw_g: group label of each COMM / ACTS / ENDW element; reg_g: region label (or None to drop)."""
    rows = []
    nreg = len(reg_g)

    def put(measure, kind, items, arr, base=None, weight=None):   # items x regions; weight = base share of the region
        w = weight if weight is not None else np.ones_like(arr) if base is None else _div(base, base.sum(axis=0, keepdims=True))
        for i, it in enumerate(items):
            for r in range(nreg):
                if reg_g[r] is not None and np.isfinite(arr[i, r]):
                    rows.append((measure, kind, it, reg_g[r], float(arr[i, r]), float(np.nan_to_num(w[i, r]))))

    def share(measure, items, arr):
        put(measure, 'share', items, _div(arr, arr.sum(axis=0, keepdims=True)), arr)

    s = lambda a, ax: np.asarray(a, float).sum(axis=ax)
    C = s(D['VDPP'] + D['VMPP'], 0); G = s(D['VDGP'] + D['VMGP'], 0); I = s(D['VDIP'] + D['VMIP'], 0)
    X = s(D['VFOB'], (0, 2)) + s(D['VST'], 0); M = s(D['VCIF'], (0, 1)); GDP = C + G + I + X - M
    tax = {'product_firms': s(D['VDFP'] - D['VDFB'] + D['VMFP'] - D['VMFB'], (0, 1)),
           'product_final': s(D['VDPP'] - D['VDPB'] + D['VMPP'] - D['VMPB'] + D['VDGP'] - D['VDGB'] + D['VMGP'] - D['VMGB'] + D['VDIP'] - D['VDIB'] + D['VMIP'] - D['VMIB'], 0),
           'output': s(D['MAKB'] - D['MAKS'], (0, 1)), 'factor_use': s(D['EVFP'] - D['EVFB'], (0, 1)), 'income': s(D['EVFB'] - D['EVOS'], (0, 1)),
           'export': s(D['VFOB'] - D['VXSB'], (0, 2)), 'import': s(D['VMSB'] - D['VCIF'], (0, 1))}
    Y = s(D['EVOS'], (0, 1)) - D['VDEP'] + sum(tax.values())        # income tax is in tax, so factor income after it
    put('macro', 'ratio', ['C/GDP', 'G/GDP', 'I/GDP', 'X/GDP', 'M/GDP', 'SAVE/Y', 'VDEP/VKB', 'VKB/GDP', 'tax/GDP'],
        np.stack([C / GDP, G / GDP, I / GDP, X / GDP, M / GDP, _div(D['SAVE'], Y), _div(D['VDEP'], D['VKB']), _div(D['VKB'], GDP),
                  sum(tax.values()) / GDP]))
    tl = list(tax)
    tm = np.stack([tax[k] for k in tl])
    put('tax_mix', 'ratio', tl, _div(tm, np.abs(tm).sum(axis=0, keepdims=True)), np.abs(tm))

    # production
    la, out = _gsum(s(D['MAKB'], 0), 0, acts_g); share('output_share', la, out)
    la, va = _gsum(s(D['EVFB'], 0), 0, acts_g); share('va_share', la, va)
    cost = s(D['MAKS'], 0)                                             # acts x reg
    la, c_ = _gsum(cost, 0, acts_g)
    lc, inp = _gsum(s(D['VDFP'] + D['VMFP'], ()), 0, comm_g)           # input group x acts x reg
    _, inp = _gsum(np.moveaxis(inp, 1, 0), 0, acts_g)                 # act group x input group x reg
    for ai, a in enumerate(la):
        put('io_coefficient', 'share', [f'{c}>{a}' for c in lc], _div(inp[ai], c_[ai][None, :]), weight=_div(inp[ai], c_.sum(axis=0)[None, :]))
    put('va_over_output', 'ratio', la, _div(va, c_), c_)
    lf, fv = _gsum(D['EVFB'], 0, endw_g)                              # factor x acts x reg
    _, fv = _gsum(np.moveaxis(fv, 1, 0), 0, acts_g)                   # act x factor x reg
    for ai, a in enumerate(la):
        put('factor_share', 'share', [f'{f}@{a}' for f in lf], _div(fv[ai], fv[ai].sum(axis=0, keepdims=True)), weight=_div(fv[ai], fv.sum(axis=(0, 1))[None, :]))
    tot = fv.sum(axis=0); share('factor_share_total', lf, tot)

    # demand
    for ag, d, m in (('household', 'VDPP', 'VMPP'), ('government', 'VDGP', 'VMGP'), ('investment', 'VDIP', 'VMIP')):
        lc, v = _gsum(D[d] + D[m], 0, comm_g); share(f'{ag}_budget', lc, v)
    for ag, d, m in (('firms', 'VDFB', 'VMFB'), ('household', 'VDPB', 'VMPB'), ('government', 'VDGB', 'VMGB'), ('investment', 'VDIB', 'VMIB')):
        dd, mm = (s(D[d], 1), s(D[m], 1)) if ag == 'firms' else (D[d], D[m])
        lc, dv = _gsum(dd, 0, comm_g); _, mv = _gsum(mm, 0, comm_g)
        put(f'import_share_{ag}', 'share', lc, _div(mv, dv + mv), dv + mv)

    # trade
    lc, ex = _gsum(s(D['VXSB'], 2), 0, comm_g); share('export_share', lc, ex)
    lc, im = _gsum(s(D['VMSB'], 1), 0, comm_g); share('import_mix', lc, im)
    for lab, num, den, ax in (('tariff_rate', D['VMSB'] - D['VCIF'], D['VCIF'], 1), ('margin_rate', s(D['VTWR'], 0), D['VFOB'], 1),
                              ('export_tax_rate', D['VFOB'] - D['VXSB'], D['VXSB'], 2)):
        lc, n_ = _gsum(s(num, ax), 0, comm_g); _, d_ = _gsum(s(den, ax), 0, comm_g)
        put(lab, 'rate', lc, _div(n_, d_), d_)
    # partner shares (importer view, all commodities); partners outside the compared set pool to "other"
    tr = s(D['VMSB'], 0)                                              # src x dst
    lp, pv = _gsum(tr, 0, [g if g is not None else 'other' for g in reg_g])
    share('import_partner', lp, pv)

    # taxes
    lc, pt = _gsum(s(D['VDFP'] - D['VDFB'] + D['VMFP'] - D['VMFB'], 1) + D['VDPP'] - D['VDPB'] + D['VMPP'] - D['VMPB']
                   + D['VDGP'] - D['VDGB'] + D['VMGP'] - D['VMGB'] + D['VDIP'] - D['VDIB'] + D['VMIP'] - D['VMIB'], 0, comm_g)
    _, pb = _gsum(s(D['VDFB'] + D['VMFB'], 1) + D['VDPB'] + D['VMPB'] + D['VDGB'] + D['VMGB'] + D['VDIB'] + D['VMIB'], 0, comm_g)
    put('product_tax_rate', 'rate', lc, _div(pt, pb), pb)
    for ag, d, m in (('household', 'VDP', 'VMP'), ('firms', 'VDF', 'VMF')):
        nt = (D[d + 'P'] - D[d + 'B'] + D[m + 'P'] - D[m + 'B']); bs = D[d + 'B'] + D[m + 'B']
        if ag == 'firms':
            nt, bs = s(nt, 1), s(bs, 1)
        lc, a_ = _gsum(nt, 0, comm_g); _, b_ = _gsum(bs, 0, comm_g)
        put(f'product_tax_rate_{ag}', 'rate', lc, _div(a_, b_), b_)
    la, ot = _gsum(s(D['MAKB'] - D['MAKS'], 0), 0, acts_g); _, ob = _gsum(s(D['MAKS'], 0), 0, acts_g)
    put('output_tax_rate', 'rate', la, _div(ot, ob), ob)
    lf, fp = _gsum(s(D['EVFP'] - D['EVFB'], 1), 0, endw_g); _, fb = _gsum(s(D['EVFB'], 1), 0, endw_g)
    put('factor_tax_rate', 'rate', lf, _div(fp, fb), fb)
    _, fo = _gsum(s(D['EVFB'] - D['EVOS'], 1), 0, endw_g)
    put('income_tax_rate', 'rate', lf, _div(fo, fb), fb)
    return pd.DataFrame(rows, columns=['measure', 'kind', 'item', 'region', 'value', 'weight'])


def _loo_median(x):
    """Median of the other entries, for each entry (leave one out)."""
    v = x.to_numpy(float)
    if len(v) < 2:
        return pd.Series(np.nan, index=x.index)
    return pd.Series([np.median(np.delete(v, i)) for i in range(len(v))], index=x.index)


def full_compare(R, sets, ga, gchars, conc, regions, large, material=0.01):
    """Every measure of measures() for the single economies in both data bases, with the reference-year screen:
    a gap is read as the reference year when it is at most 2 points (rates and shares x 100), or when the median
    gap of the same measure and item over the other compared regions has the same sign and a similar size (within 2
    points or half the gap): a 2014 -> 2022 change in prices or structure moves every region alike. An item whose
    median gap over all regions is over 5 points is systematic and never read as the year (QA S16 #5).
    A gap is flagged when it is not read as the reference year, the item is material (weight >= 1% in either data
    base), the region is one of the `large` economies and the gap is over 5 points.
    Returns (table, summary by measure: counts and item names only, no GTAP value)."""
    g2grp, s2grp = common_groups(conc)
    single = set(regions.loc[regions['type'] == 'single', 'region'])
    greg = [r.lower() for r in gchars['REG']]
    both = {r.upper() for r in greg} & single & set(sets['REG'])
    ours = measures(R, [s2grp[c] for c in sets['COMM']], [s2grp[c] for c in sets['ACTS']], [FACTOR_GROUP[e] for e in sets['ENDW']],
                    [r if r in both else None for r in sets['REG']])
    gt = measures(ga, [g2grp[c.lower()] for c in gchars['COMM']], [g2grp[c.lower()] for c in gchars['ACTS']],
                  [FACTOR_GROUP[e.lower()] for e in gchars['ENDW']], [r.upper() if r.upper() in both else None for r in greg])
    t = ours.merge(gt, on=['measure', 'kind', 'item', 'region'], how='outer', suffixes=('_2022', '_gtap10'))
    t[['value_2022', 'value_gtap10', 'weight_2022', 'weight_gtap10']] = t[['value_2022', 'value_gtap10', 'weight_2022', 'weight_gtap10']].fillna(0.0)
    t['gap_pts'] = 100 * (t['value_2022'] - t['value_gtap10'])
    # the reference-year screen compares each gap with the median gap of the same measure and item over the OTHER
    # regions (a region's own error must not explain itself); an item whose median gap over all regions is over 5
    # points is systematic: a build-wide difference is not assumed to be the year, each one is reviewed by hand
    t['median_gap_pts'] = t.groupby(['measure', 'item'])['gap_pts'].transform(_loo_median)
    t['systematic'] = t.groupby(['measure', 'item'])['gap_pts'].transform('median').abs() > 5
    g_, w_ = t['gap_pts'], t['median_gap_pts']
    t['year_explained'] = (g_.abs() <= 2) | (~t['systematic'] & (np.sign(g_) == np.sign(w_))
                                             & ((g_ - w_).abs() <= np.maximum(2, 0.5 * g_.abs())))
    # material: the item is at least 1% of what the measure is taken over in that region, in either data base
    t['material'] = np.maximum(t['weight_2022'], t['weight_gtap10']) >= material
    t['large_economy'] = t['region'].isin(set(large))
    t['flag'] = ~t['year_explained'] & t['material'] & t['large_economy'] & (t['gap_pts'].abs() > 5)
    t = t.reindex(t['gap_pts'].abs().sort_values(ascending=False).index).reset_index(drop=True)
    summ = t.groupby('measure').agg(rows=('gap_pts', 'size'), material=('material', 'sum'),
                                    explained_material=('year_explained', lambda x: int((x & t.loc[x.index, 'material']).sum())),
                                    flagged_large=('flag', 'sum')).reset_index()
    sysi = t[t['systematic'] & t['material']].groupby('measure')['item'].agg(lambda x: ' '.join(sorted(set(x))[:12]))
    summ['systematic_items'] = summ['measure'].map(sysi).fillna('')
    summ['items_flagged'] = summ['measure'].map(lambda m: ' '.join(sorted(set(t.loc[t['flag'] & (t['measure'] == m), 'item']))[:12]))
    return t, summ
