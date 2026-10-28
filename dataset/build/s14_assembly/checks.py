"""S14 hard checks on the assembled header tables. Each is a pure function returning (number of failures,
detail) so the mutation tests in tests/test_s14_checks.py can show that each one fails on a bad input.

The stage runs them on the tables read back from the written output files, so they check what S15 reads.
Tables: firms (region, comm, acts, VDFB, VDFP, VMFB, VMFP), final (region, comm, VDPB ... VMIP), endw
(region, endw, acts, EVFP, EVFB, EVOS), make (region, comm, acts, MAKS, MAKB), bilateral (comm, src, dst,
VXSB, VFOB, VCIF, VMSB), vtwr (marg, comm, src, dst, VTWR), vst (marg, region, VST), regional (region,
SAVE, VDEP, VKB, POP).
"""
import numpy as np
import pandas as pd

from .method import FD_HEADERS, ROUTE, BORDER, FD, HEADERS, RULE_SMALL, RULE_NATRES, RULE_SEED_FACTOR, RULE_CAPITAL_MIN, REBAL_MAX, ENERGY_TAX_ROWS, natres_sectors, natres_target
from s12_factors.checks import natres_eta as _natres_eta_s12

TOL = 1e-6


def _close(a, b, tol=TOL):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return np.abs(a - b) <= tol * np.maximum(1.0, np.maximum(np.abs(a), np.abs(b)))


def _detail(bad):
    return '; '.join(bad[:10]) + (f'; and {len(bad) - 10} more' if len(bad) > 10 else '')


def _sum(df, keys, col):
    return df.groupby(keys)[col].sum() if len(df) else pd.Series(dtype=float)


def _both(a, b):
    idx = a.index.union(b.index)
    return a.reindex(idx, fill_value=0.0), b.reindex(idx, fill_value=0.0)


def sets(regions, sectors, endw, marg, acts=None):
    """REG has the S01 regions; COMM = ACTS (same elements, same order); MARG is a subset of COMM with more
    than one element; ENDW includes 'capital' (notes/model_requirements.md §1a)."""
    bad = []
    if acts is not None and list(acts) != list(sectors):
        bad.append('ACTS differs from COMM')
    if len(set(regions)) != len(regions) or not regions:
        bad.append('REG empty or duplicated')
    if not set(marg) <= set(sectors):
        bad.append(f'MARG {sorted(set(marg) - set(sectors))} not in COMM')
    if len(marg) < 2:
        bad.append('MARG has fewer than 2 elements')
    if 'capital' not in endw:
        bad.append('ENDW has no capital')
    return len(bad), _detail(bad)


def headers(t):
    """Every one of the 31 headers is a column of exactly one table."""
    cols = [c for k in ('firms', 'final', 'endw', 'make', 'bilateral', 'vtwr', 'vst', 'regional') for c in t[k].columns]
    bad = [f'{h}: {cols.count(h)} tables' for h in HEADERS if cols.count(h) != 1]
    return len(bad), _detail(bad)


def route_cif(b, v):
    """VCIF = VFOB + sum of VTWR on every commodity and route (model identity 6)."""
    m = _sum(v, ROUTE, 'VTWR')
    x = b.set_index(ROUTE)
    mm = m.reindex(x.index, fill_value=0.0)
    ok = _close(x['VCIF'], x['VFOB'] + mm)
    orphan = m.index.difference(x.index)
    bad = [f'{k}: VCIF {r.VCIF:.9g} VFOB {r.VFOB:.9g} VTWR {mm[k]:.9g}' for k, r in x[~ok].iterrows()]
    bad += [f'{k}: VTWR {m[k]:.9g} on a route with no trade' for k in orphan[:10]]
    return len(bad), _detail(bad)


def global_margins(v, vst):
    """World VST = world VTWR for each margin (model identity 7)."""
    a, b = _both(_sum(vst, 'marg', 'VST'), _sum(v, 'marg', 'VTWR'))
    bad = [f'{m}: VST {a[m]:.9g} VTWR {b[m]:.9g}' for m in a.index if not _close(a[m], b[m])]
    return len(bad), _detail(bad)


def merge_totals(b, vst, trade):
    """The bilateral flows add up to what S13 held, by region and commodity: VXSB and VFOB over destinations,
    VMSB and VCIF over sources, and VST (trade_s13 X, XFOB, M, MCIF, VST). Rounding tolerance REBAL bound."""
    from .method import REBAL_MAX
    t = trade.set_index(['region', 'sector'])
    pairs = [('X', _sum(b, ['src', 'comm'], 'VXSB')), ('XFOB', _sum(b, ['src', 'comm'], 'VFOB')),
             ('M', _sum(b, ['dst', 'comm'], 'VMSB')), ('MCIF', _sum(b, ['dst', 'comm'], 'VCIF')),
             ('VST', _sum(vst, ['region', 'marg'], 'VST'))]
    bad = []
    for col, s in pairs:
        s.index.names = ['region', 'sector']
        a, h = _both(s, t[col])
        gap = (a - h).abs()
        tol = np.maximum(REBAL_MAX * 10, TOL * np.maximum(a.abs(), h.abs()))
        for k in gap.index[gap > tol]:
            bad.append(f'{col} {k}: bilateral {a[k]:.9g} S13 {h[k]:.9g}')
    return len(bad), _detail(bad)


def market_clearing(fi, fd, mk, b, vst):
    """Domestic market at basic prices: sum over activities of MAKB = VDFB + VDPB + VDGB + VDIB + VXSB + VST
    for every commodity and region (model identity 3)."""
    supply = _sum(mk, ['region', 'comm'], 'MAKB')
    use = _sum(fi, ['region', 'comm'], 'VDFB')
    for ag in FD:
        use = use.add(_sum(fd, ['region', 'comm'], FD_HEADERS[ag][0]), fill_value=0.0)
    xs = _sum(b, ['src', 'comm'], 'VXSB'); xs.index.names = ['region', 'comm']
    vs = _sum(vst, ['region', 'marg'], 'VST'); vs.index.names = ['region', 'comm']
    use = use.add(xs, fill_value=0.0).add(vs, fill_value=0.0)
    a, u = _both(supply, use)
    bad = [f'{k}: supply {a[k]:.9g} use {u[k]:.9g}' for k in a.index if not _close(a[k], u[k])]
    return len(bad), _detail(bad)


def import_clearing(fi, fd, b):
    """Imports: sum over sources of VMSB = VMFB + VMPB + VMGB + VMIB (model identity 4)."""
    supply = _sum(b, ['dst', 'comm'], 'VMSB'); supply.index.names = ['region', 'comm']
    use = _sum(fi, ['region', 'comm'], 'VMFB')
    for ag in FD:
        use = use.add(_sum(fd, ['region', 'comm'], FD_HEADERS[ag][2]), fill_value=0.0)
    a, u = _both(supply, use)
    bad = [f'{k}: VMSB {a[k]:.9g} purchases {u[k]:.9g}' for k in a.index if not _close(a[k], u[k])]
    return len(bad), _detail(bad)


def zero_profit(fi, en, mk):
    """Every activity: sum of MAKS = VDFP + VMFP + EVFP (model identity 1)."""
    maks = _sum(mk, ['region', 'acts'], 'MAKS')
    cost = _sum(fi, ['region', 'acts'], 'VDFP').add(_sum(fi, ['region', 'acts'], 'VMFP'), fill_value=0.0)
    cost = cost.add(_sum(en, ['region', 'acts'], 'EVFP'), fill_value=0.0)
    a, c = _both(maks, cost)
    bad = [f'{k}: MAKS {a[k]:.9g} cost {c[k]:.9g}' for k in a.index if not _close(a[k], c[k])]
    return len(bad), _detail(bad)


def diagonal_make(mk):
    """MAKS and MAKB are diagonal (ACTS = COMM, one product per activity)."""
    bad = [f'{r.region} {r.comm} made by {r.acts}' for r in mk[mk['comm'] != mk['acts']].itertuples()]
    return len(bad), _detail(bad)


def one_tax_power(fi, fd):
    """Each column has one product-tax power on its domestic and imported purchases (purchaser / basic);
    a purchaser value implies a positive basic value."""
    bad = []
    for r in fi.itertuples():
        for b_, p_ in ((r.VDFB, r.VDFP), (r.VMFB, r.VMFP)):
            if (b_ == 0) != (p_ == 0):
                bad.append(f'{r.region} {r.comm} {r.acts}: basic {b_:.6g} purchaser {p_:.6g}')
    pw = fi.assign(bd=fi['VDFB'] + fi['VMFB'], pd_=fi['VDFP'] + fi['VMFP'])
    for (reg, a), g in pw.groupby(['region', 'acts']):
        dm = g[g['VDFB'] > 0]
        im = g[g['VMFB'] > 0]
        rates = np.concatenate([(dm['VDFP'] / dm['VDFB']).to_numpy(), (im['VMFP'] / im['VMFB']).to_numpy()])
        if len(rates) and not np.all(_close(rates, rates[0], 1e-8)):
            bad.append(f'{reg} {a}: tax powers from {rates.min():.9g} to {rates.max():.9g}')
    for ag in FD:
        db, dp, mb, mp = FD_HEADERS[ag]
        for reg, g in fd.groupby('region'):
            rates = np.concatenate([(g.loc[g[db] > 0, dp] / g.loc[g[db] > 0, db]).to_numpy(),
                                    (g.loc[g[mb] > 0, mp] / g.loc[g[mb] > 0, mb]).to_numpy()])
            if len(rates) and not np.all(_close(rates, rates[0], 1e-8)):
                bad.append(f'{reg} {ag}: tax powers from {rates.min():.9g} to {rates.max():.9g}')
            z = g[((g[db] == 0) != (g[dp] == 0)) | ((g[mb] == 0) != (g[mp] == 0))]
            bad += [f'{reg} {x} {ag}: basic and purchaser zero patterns differ' for x in z['comm']]
    return len(bad), _detail(bad)


def _cells(fi, fd):
    """Firm and final-demand purchases as one long table: region, comm, col, db, dp, mb, mp."""
    parts = [fi.rename(columns={'acts': 'col', 'VDFB': 'db', 'VDFP': 'dp', 'VMFB': 'mb', 'VMFP': 'mp'})[['region', 'comm', 'col', 'db', 'dp', 'mb', 'mp']]]
    for ag in FD:
        db, dp, mb, mp = FD_HEADERS[ag]
        parts.append(fd[['region', 'comm', db, dp, mb, mp]].rename(columns={db: 'db', dp: 'dp', mb: 'mb', mp: 'mp'}).assign(col=ag))
    c = pd.concat([p_ for p_ in parts if len(p_)], ignore_index=True) if any(len(p_) for p_ in parts) else pd.DataFrame(columns=['region', 'comm', 'col', 'db', 'dp', 'mb', 'mp'])
    c = c[(c[['db', 'dp', 'mb', 'mp']] != 0).any(axis=1)].copy()
    b = c['db'] + c['mb']
    c['power'] = np.where(b > 0, (c['dp'] + c['mp']) / np.where(b > 0, b, 1.0), np.nan)
    return c


def _with_s13(c, cells13):
    """c (_cells) with r13, each cell's S13 rate (tls_rate + pse_rate; a cell S13 does not list has rate 0), d, the
    cell's power less 1 less r13, and basic, its basic purchases."""
    t = cells13.assign(rate=cells13['tls_rate'] + cells13['pse_rate']).rename(columns={'column': 'col', 'commodity': 'comm'})
    r13 = t.set_index(['region', 'col', 'comm'])['rate']
    c = c.copy()
    c['r13'] = np.nan_to_num(pd.MultiIndex.from_frame(c[['region', 'col', 'comm']]).map(r13).to_numpy(float))
    c['d'] = c['power'] - 1.0 - c['r13']
    c['basic'] = c['db'] + c['mb']
    return c


def cell_tax_power(fi, fd, items=None, cells13=None, money=REBAL_MAX):
    """purchaser_split cell rates (fix list A1; fix round wG; QA round 2 P1): each (commodity, column) cell has one
    product-tax power on its domestic and imported purchases, and a purchaser value implies a positive basic value.
    On the non-energy rows of a column: with cells13 (tax_cells_s13), every cell's power is its S13 net rate
    (tls_rate + pse_rate: the non_energy_rates commodity rates and a listed PSE input item's own rate alike) plus one
    remainder shift per column (S14 re-sets one remainder to hold the column tax in a column the A13 seed moved;
    elsewhere the shift is 0 to rounding, which Hcellrates checks). A gap passes within 1e-8 or when it moves at most
    `money` USD million of tax on the cell. Without cells13 the rows share one power (one general rate per column).
    items ({(region, column, commodity)}, the S13 PSE input items) only labels the failures."""
    c = _cells(fi, fd)
    items = set(items or ())
    bad = [f'{x.region} {x.comm} {x.col}: basic and purchaser zero patterns differ'
           for x in c[((c['db'] == 0) != (c['dp'] == 0)) | ((c['mb'] == 0) != (c['mp'] == 0))].itertuples()]
    both = c[(c['db'] > 0) & (c['mb'] > 0)]
    pd_, pm = both['dp'] / both['db'], both['mp'] / both['mb']
    bad += [f'{x.region} {x.comm} {x.col}: domestic power {a:.9g} imported {b:.9g}' for x, a, b in zip(both.itertuples(), pd_, pm) if not _close(a, b, 1e-8)]
    ne = c[~c['comm'].isin(ENERGY_TAX_ROWS) & c['power'].notna()]
    if cells13 is not None:
        ne = _with_s13(ne, cells13)
        for (reg, col), g in ne.groupby(['region', 'col']):
            d = g['d'].to_numpy()
            mid = np.median(d)
            for x, o in zip(g.itertuples(), np.abs(d - mid)):
                if o > 1e-8 and o * x.basic > money:
                    what = 'PSE item' if (reg, col, x.comm) in items else 'cell'
                    bad.append(f'{reg} {x.comm} {col}: {what} power less S13 rate {x.d:.9g} against the column shift {mid:.9g}')
        return len(bad), _detail(bad)
    for (reg, col), g in ne.groupby(['region', 'col']):
        r = g['power'].to_numpy()
        if not np.all(_close(r, r[0], 1e-8)):
            bad.append(f'{reg} {col}: non-energy powers from {r.min():.9g} to {r.max():.9g}')
    return len(bad), _detail(bad)


def cell_rates_match_s13(fi, fd, cells13, seed_cols=None, tol=1e-6, money=REBAL_MAX):
    """Fix list A1 and QA round 2 P1 through S14: every cell of the tables as written, energy rows (pet, coa, gas, ely)
    and non-energy rows alike, has the S13 net product-tax rate of that cell (tax_cells_s13: tls_rate + pse_rate; a
    cell S13 does not list has rate 0). A gap passes when it is within tol, or when it moves at most `money` USD
    million of tax over the column's basic purchases (rounding of the io_s13 rows). In a column the A13 seed moved
    (seed_cols: {(region, col)}), the remainder rate is re-set to hold the column's tax, so there each cell's
    power less its S13 rate is compared with the column's median of that gap on the non-energy rows (one shift)."""
    c = _cells(fi, fd)
    c = _with_s13(c[c['power'].notna()], cells13)
    colb = c.groupby(['region', 'col'])['basic'].transform('sum')
    shift = c[~c['comm'].isin(ENERGY_TAX_ROWS)].groupby(['region', 'col'])['d'].median()
    seed_cols = set(seed_cols or ())
    bad = []
    for x, cb in zip(c.itertuples(), colb):
        k = (x.region, x.col)
        if k in seed_cols:
            if k not in shift.index:
                continue
            gap = abs(x.d - shift[k])
        else:
            gap = abs(x.d)
        if gap > tol and gap * cb > money:
            bad.append(f'{x.region} {x.comm} {x.col}: rate {x.power - 1.0:.9g} vs S13 {x.r13:.9g}' + (' (shift, A13 column)' if k in seed_cols else ''))
    return len(bad), _detail(bad)


def factor_identities(en):
    """EVFB <= EVFP is not required (factor subsidies), but EVFP = 0 exactly when EVFB = 0 and EVFB = 0 when
    EVOS = 0 (model identity 8: tfe = EVFP/EVFB and tinc = EVFB/EVOS need non-zero denominators)."""
    bad = [f'{r.region} {r.endw} {r.acts}: EVFP {r.EVFP:.6g} EVFB {r.EVFB:.6g} EVOS {r.EVOS:.6g}'
           for r in en.itertuples() if (r.EVFP == 0) != (r.EVFB == 0) or (r.EVFB == 0) != (r.EVOS == 0)]
    return len(bad), _detail(bad)


def factors_match_s13(en, fac13, delta=None):
    """EVFP, EVFB and EVOS equal factors_s13 cell by cell, plus the ledgered moves where given (delta: region,
    endw, acts, EVFP, EVFB, EVOS, rule). The A13 seed moves a cell from a supplying column to a seeded one, so
    those must sum to zero by region and factor; the A13 land and natres moves to capital (RULE_SEED_FACTOR), the
    capital floor moves (RULE_CAPITAL_MIN) and the B16 moves sum to zero by region and activity; the B14 moves (rule RULE_SMALL) lower an activity's factor
    payments by the output it lost with the trade cells below USD 1."""
    a = en.set_index(['region', 'endw', 'acts'])[['EVFP', 'EVFB', 'EVOS']]
    f = fac13.rename(columns={'factor': 'endw', 'sector': 'acts', 'evfp': 'EVFP', 'evfb': 'EVFB', 'evos': 'EVOS'})
    f = f.set_index(['region', 'endw', 'acts'])[['EVFP', 'EVFB', 'EVOS']]
    bad_tot = []
    if delta is not None and len(delta):
        d = delta.groupby(['region', 'endw', 'acts'])[['EVFP', 'EVFB', 'EVOS']].sum()
        f = f.add(d, fill_value=0.0)
        z = delta[~delta['rule'].isin((RULE_SMALL, RULE_NATRES, RULE_SEED_FACTOR, RULE_CAPITAL_MIN))] if 'rule' in delta.columns else delta
        tot = z.groupby(['region', 'endw'])[['EVFP', 'EVFB', 'EVOS']].sum()
        scale = fac13.groupby(['region', 'factor'])['evfp'].sum().abs().reindex(tot.index).fillna(0.0)
        for k, r in tot.iterrows():
            if np.abs(r.to_numpy(float)).max() > TOL * max(1.0, scale.get(k, 0.0)):
                bad_tot.append(f'{k}: A13 seed moves do not sum to zero ({r.to_dict()})')
        # B16 moves income between factors within an activity: its EVFP moves sum to zero by region and activity
        if 'rule' in delta.columns:
            va = fac13.groupby(['region', 'sector'])['evfp'].sum().abs()
            # (B16 holds EVFP only: each factor keeps its own tax rates; the A13 move holds all three)
            for rule, what, cols in ((RULE_NATRES, 'B16 natural-resource', ['EVFP']),
                                     (RULE_SEED_FACTOR, 'A13 land and natres to capital', ['EVFP', 'EVFB', 'EVOS']),
                                     (RULE_CAPITAL_MIN, 'capital floor labour to capital', ['EVFP', 'EVFB', 'EVOS'])):
                nz = delta[delta['rule'] == rule].groupby(['region', 'acts'])[cols].sum()
                for k, r in nz.iterrows():
                    v = np.abs(r.to_numpy(float)).max()
                    if v > TOL * max(1.0, va.get(k, 0.0)):
                        bad_tot.append(f'{k}: {what} moves change the activity value added by {v:.6g}')
    f = f[(f.abs() > 1e-12).any(axis=1)]
    idx = a.index.union(f.index)
    a, f = a.reindex(idx, fill_value=0.0), f.reindex(idx, fill_value=0.0)
    ok = np.all([_close(a[c], f[c]) for c in a.columns], axis=0)
    bad = [f'{k}: {a.loc[k].to_dict()} vs S13 {f.loc[k].to_dict()}' for k in idx[~ok]] + bad_tot
    return len(bad), _detail(bad)


def one_sided_pairs(fi, fd):
    """(region, comm) pairs bought from one source only: imported purchases and no domestic purchase, or the
    reverse. Returns a DataFrame region, comm, domestic, imported, missing."""
    dcols = [FD_HEADERS[ag][0] for ag in FD]
    mcols = [FD_HEADERS[ag][2] for ag in FD]
    d = _sum(fi, ['region', 'comm'], 'VDFB').add(fd.set_index(['region', 'comm'])[dcols].sum(axis=1) if len(fd) else 0.0, fill_value=0.0)
    m = _sum(fi, ['region', 'comm'], 'VMFB').add(fd.set_index(['region', 'comm'])[mcols].sum(axis=1) if len(fd) else 0.0, fill_value=0.0)
    d, m = _both(d, m)
    sel = (d > 0) != (m > 0)
    out = pd.DataFrame(dict(domestic=d[sel], imported=m[sel]))
    out['missing'] = np.where(out['domestic'] > 0, 'imported', 'domestic')
    return out.reset_index()


def seed_check(fi, fd, seeds, ratio, swaps=None, b=None):
    """A13: no commodity is bought from one source only (domestic only: checked when swaps is given), every seeded pair's domestic purchases are `ratio`
    times its imported purchases (rel 1e-9), and every swapped pair (swaps: region, comm, partner, musd) has
    the two swap routes at musd with no tax or margin (b: the bilateral table as written).
    Returns (failures, detail)."""
    bad = []
    p = one_sided_pairs(fi, fd)
    bad += [f'{r.region} {r.comm}: imported {r.imported:.6g} and no domestic purchase' for r in p[p['missing'] == 'domestic'].itertuples()]
    if swaps is not None:      # the swap ran: no pair is bought only from domestic producers either
        bad += [f'{r.region} {r.comm}: domestic {r.domestic:.6g} and no imported purchase' for r in p[p['missing'] == 'imported'].itertuples()]
    if len(seeds):
        dcols = [FD_HEADERS[ag][0] for ag in FD]
        d = _sum(fi, ['region', 'comm'], 'VDFB').add(fd.set_index(['region', 'comm'])[dcols].sum(axis=1), fill_value=0.0)
        for s in seeds.itertuples():
            got = d.get((s.region, s.comm), 0.0)
            r_ = getattr(s, 'ratio', ratio)      # beta v4 capital_floor: a small row's ratio rises to its seed minimum
            if r_ < ratio * (1 - 1e-9) or not _close(got, r_ * s.imports, 1e-9) or not _close(got, s.seed, 1e-9):
                bad.append(f'{s.region} {s.comm}: domestic {got:.9g}, seed {s.seed:.9g}, {r_:g} x imports {r_ * s.imports:.9g} (at least {ratio:g})')
    if swaps is not None and len(swaps) and b is not None:
        rt = b.set_index(ROUTE)
        for s in swaps.itertuples():
            if not s.partner:
                bad.append(f'{s.region} {s.comm}: no swap partner')
                continue
            for k in ((s.comm, s.partner, s.region), (s.comm, s.region, s.partner)):
                if getattr(s, 'merged', False) and k == (s.comm, s.region, s.partner):
                    # the swap added to an existing route (final round 2026-10-25): the route carries at least the swap
                    if k not in rt.index or any(float(rt.loc[k, h]) < s.musd * (1 - 1e-9) for h in BORDER):
                        bad.append(f'{" ".join(k)}: merged swap route below {s.musd:.9g} on VXSB, VFOB, VCIF or VMSB')
                    continue
                if k not in rt.index or any(not _close(float(rt.loc[k, h]), s.musd, 1e-9) for h in BORDER):
                    bad.append(f'{" ".join(k)}: swap route not at {s.musd:.9g} on VXSB, VFOB, VCIF and VMSB')
    return len(bad), _detail(bad)


def small_trade(b, v, cut):
    """B14: no route with 0 < VXSB < cut and no VTWR cell with 0 < VTWR < cut is left. Returns (failures, detail)."""
    xb = b[(b['VXSB'] > 0) & (b['VXSB'] < cut)]
    xv = v[(v['VTWR'] > 0) & (v['VTWR'] < cut)]
    bad = [f'VXSB {r.comm} {r.src} {r.dst}: {r.VXSB:.3g}' for r in xb.head(5).itertuples()]
    bad += [f'VTWR {r.marg} {r.comm} {r.src} {r.dst}: {r.VTWR:.3g}' for r in xv.head(5).itertuples()]
    n = len(xb) + len(xv)
    return n, _detail(bad) + (f' ({len(xb)} routes, {len(xv)} margin cells)' if n else '')


def signs(t):
    """Every flow is non-negative: purchases, make, factor payments (EVFP, EVFB, EVOS), border values,
    margins, VST, VKB, VDEP and POP, with no exception."""
    bad = []
    for k, cols in (('firms', ('VDFB', 'VDFP', 'VMFB', 'VMFP')), ('final', tuple(h for ag in FD for h in FD_HEADERS[ag])),
                    ('make', ('MAKS', 'MAKB')), ('bilateral', BORDER), ('vtwr', ('VTWR',)), ('vst', ('VST',)),
                    ('regional', ('VDEP', 'VKB', 'POP'))):
        d = t[k]
        for c in cols:
            for r in d[d[c] < 0].itertuples():
                bad.append(f'{k} {c} {r[1:4]} {getattr(r, c):.6g}')
    en = t['endw']
    for c in ('EVFP', 'EVFB', 'EVOS'):
        for r in en[en[c] < 0].itertuples():
            bad.append(f'endw {c} {r.region} {r.endw} {r.acts} {getattr(r, c):.6g}')
    return len(bad), _detail(bad)


def zero_divides(t):
    """No ratio the model forms has a zero denominator under a non-zero numerator (17B §B.2 zero-divide
    check; notes/model_requirements.md §1b): to = MAKB/MAKS, txs = VFOB/VXSB, tms = VMSB/VCIF; and every
    activity with output has positive EVFP (model identity 8)."""
    bad = []
    mk, b, en = t['make'], t['bilateral'], t['endw']
    bad += [f'MAKB/MAKS {r.region} {r.acts}: {r.MAKB:.6g}/{r.MAKS:.6g}' for r in mk[(mk['MAKS'] == 0) != (mk['MAKB'] == 0)].itertuples()]
    bad += [f'VFOB/VXSB {r.comm} {r.src} {r.dst}: {r.VFOB:.6g}/{r.VXSB:.6g}' for r in b[(b['VXSB'] == 0) != (b['VFOB'] == 0)].itertuples()]
    bad += [f'VMSB/VCIF {r.comm} {r.src} {r.dst}: {r.VMSB:.6g}/{r.VCIF:.6g}' for r in b[(b['VCIF'] == 0) != (b['VMSB'] == 0)].itertuples()]
    va = en.groupby(['region', 'acts'])['EVFP'].sum() if len(en) else pd.Series(dtype=float)
    for r in mk[mk['MAKB'] > 0].itertuples():
        if va.get((r.region, r.acts), 0.0) <= 0:
            bad.append(f'{r.region} {r.acts}: output {r.MAKB:.6g} with EVFP {va.get((r.region, r.acts), 0.0):.6g}')
    return len(bad), _detail(bad)


def gdp(acc, gdp_s02):
    """GDP from expenditure (C + G + I + VFOB + VST - VCIF) and from income (EVFP + all indirect taxes) both
    equal S02 GDP in every region."""
    bad = []
    for r, x in acc.iterrows():
        g = gdp_s02[r]
        if not (_close(x['GDP_expenditure'], g) and _close(x['GDP_income'], g)):
            bad.append(f'{r}: expenditure {x["GDP_expenditure"]:.6f} income {x["GDP_income"]:.6f} S02 {g:.6f}')
    return len(bad), _detail(bad)


def final_demand(acc, macro13):
    """C, G and I at purchasers' prices equal the S13 targets (S02 times the region factor)."""
    m = macro13.set_index('region')
    bad = [f'{r} {k}: {acc.loc[r, k]:.6f} vs S13 {m.loc[r, k]:.6f}' for r in acc.index for k in ('C', 'G', 'I')
           if not _close(acc.loc[r, k], m.loc[r, k])]
    return len(bad), _detail(bad)


def saving_identity(acc, regional):
    """SAVE in the header equals Y - C - G, S - (I - VDEP) = X - M in every region, and world SAVE equals
    world net investment (GTAP 12 ch.7 eq. 7.1; model identities 10 and 11)."""
    bad = []
    s = regional.set_index('region')['SAVE']
    for r, x in acc.iterrows():
        if not _close(s[r], x['SAVE'], TOL):
            bad.append(f'{r}: SAVE header {s[r]:.6f} vs Y - C - G {x["SAVE"]:.6f}')
        lhs, rhs = x['SAVE'] - (x['I'] - x['VDEP']), x['X'] - x['M']
        if abs(lhs - rhs) > TOL * max(1.0, abs(x['GDP_expenditure'])):
            bad.append(f'{r}: S - (I - VDEP) {lhs:.6f} vs X - M {rhs:.6f}')
    ws, wi = s.sum(), (acc['I'] - acc['VDEP']).sum()
    if abs(ws - wi) > TOL * max(1.0, acc['GDP_expenditure'].sum()):
        bad.append(f'world SAVE {ws:.6f} vs world I - VDEP {wi:.6f}')
    return len(bad), _detail(bad)


def si_gate_hard(gate, share_hard, save_hard=False):
    """Pre-solve S-I gate (PLAN §3(h)3, E12, E28): VKB > 0, I > 0, Y > 0 and VDEP below capital income; SAVE > 0
    as well when save_hard, and the saving share in [-1, 1] as well when share_hard."""
    items = ['vkb_positive', 'investment_positive', 'income_positive', 'vdep_below_capital_income']
    if save_hard:
        items.append('save_positive')
    if share_hard:
        items.append('saving_share_in_bounds')
    bad = [f'{r}: ' + ', '.join(i + (f' (capital income {x["capital_income"]:.1f} vs VDEP {x["VDEP"]:.1f} USD million)'
                                     if i == 'vdep_below_capital_income' else '') for i in items if not x[i])
           for r, x in gate.iterrows() if not all(x[i] for i in items)]
    return len(bad), _detail(bad)


def vdep_capital_sources(gate, fac13):
    """Report for S14-Hsi (fix round w17): each region with VDEP at or above capital income (sum EVOS capital, the
    model's identity 12), with its capital income in factors_s13 (before the S14 B16 and A13 moves), so the check names
    the stage that set it. Returns rows: region, VDEP, capital_income_s13, capital_income, moved_in_s14."""
    k13 = fac13[fac13['factor'] == 'capital'].groupby('region')['evos'].sum()
    g = gate[~gate['vdep_below_capital_income']]
    return pd.DataFrame(dict(region=g.index, VDEP=g['VDEP'].to_numpy(), capital_income_s13=k13.reindex(g.index).fillna(0.0).to_numpy(),
                             capital_income=g['capital_income'].to_numpy())).assign(
        moved_in_s14=lambda d: d['capital_income'] - d['capital_income_s13'])


def vdep_floor_breaches(gate, fac13, ratio=1.25):
    """Beta v4 G17 (Grok QA A4): regions whose capital income at S13 (factors_s13) or after S14 is below ratio x VDEP,
    the S12 capital_vdep_floor (our rule; S12-Hvdepk holds it at S12 only, and the fit can move it: TLS 1.250 at S12,
    0.982 at S13). Returns rows: region, VDEP, ratio_s13, ratio_final."""
    k13 = fac13[fac13['factor'] == 'capital'].groupby('region')['evos'].sum().reindex(gate.index).fillna(0.0)
    v = gate['VDEP'].where(gate['VDEP'] > 0)
    d = pd.DataFrame(dict(region=gate.index, VDEP=gate['VDEP'].to_numpy(), ratio_s13=(k13 / v).to_numpy(),
                          ratio_final=(gate['capital_income'] / v).to_numpy()))
    return d[(d['ratio_s13'] < ratio) | (d['ratio_final'] < ratio)].reset_index(drop=True)


def rebalance_bound(moves, bound):
    """Every re-balancing move is at most the rounding bound (no plug)."""
    if not len(moves):
        return 0, ''
    d = (moves['after'] - moves['before']).abs()
    big = moves[d > bound]
    bad = [f'{r.kind} {r.key}: {r.before:.9g} -> {r.after:.9g}' for r in big.itertuples()]
    return len(bad), _detail(bad)


def chain(upstreams):
    """Every upstream this stage reads is the one the other upstreams were stamped on: where upstream V's
    STAMP lists upstream U's SHA256SUMS, it equals U's actual SHA256SUMS. upstreams: {name: (actual sums,
    {listed name: listed sums})}."""
    bad = []
    for v, (_, listed) in upstreams.items():
        for u, h in listed.items():
            if u in upstreams and upstreams[u][0] != h:
                bad.append(f'{v} lists {u} SHA256SUMS {h[:12]}, actual {upstreams[u][0][:12]}')
    return len(bad), _detail(bad)


# ------------------------------------------------------------------ fix round B16 on the S14 data (ch.12.A; ch.17B)
def natres_cells(en, mk, targets, floor):
    """The targeted resource cells of the written tables: region, sector, cost_musd (MAKS), factor_va_musd (sum EVFP),
    natres_musd, theta_va, guard (theta_VA below floor or cost not positive, as S12 natres_guard), theta_va_used,
    eta_target, sigma_va, eta (sigma cost (1/natres - 1/VA), NaN without natural resources). Recomputed from the tables,
    not taken from the method."""
    e = en[en['acts'].isin(sorted(natres_sectors(targets)))]
    va = e.groupby(['region', 'acts'])['EVFP'].sum()
    nat = e[e['endw'] == 'natres'].groupby(['region', 'acts'])['EVFP'].sum().reindex(va.index, fill_value=0.0)
    c = mk.set_index(['region', 'acts'])['MAKS'].reindex(va.index).fillna(0.0)
    d = pd.DataFrame(dict(factor_va_musd=va, natres_musd=nat, cost_musd=c)).reset_index().rename(columns={'acts': 'sector'})
    t = [natres_target(targets, r, s) for r, s in zip(d['region'], d['sector'])]
    d['eta_target'] = [x['eta'] if x else np.nan for x in t]
    d['sigma_va'] = [x['sigma'] if x else np.nan for x in t]
    d['theta_va'] = np.where(d['cost_musd'] > 0, d['factor_va_musd'] / d['cost_musd'].where(d['cost_musd'] > 0, 1.0), np.nan)
    d['guard'] = ~(d['theta_va'] >= floor)
    d['theta_va_used'] = np.where(d['guard'], floor, d['theta_va'])
    ok = (d['natres_musd'] > 0) & (d['factor_va_musd'] > 0) & (d['cost_musd'] > 0)
    d['eta'] = np.where(ok, d['sigma_va'] * d['cost_musd'] * (1.0 / d['natres_musd'].where(ok, 1.0) - 1.0 / d['factor_va_musd'].where(ok, 1.0)), np.nan)
    return d


def natres_eta(en, mk, targets, floor):
    """S14-Heta: in every targeted cell with value added and no guard, eta on the S14 tables equals the ch.12.A target
    within 1e-6 (relative to max(1, eta)); a guarded cell has the share at the floor (the S12 check, s12_factors.checks
    natres_eta, on the S14 tables)."""
    d = natres_cells(en, mk, targets, floor)
    ev = en[en['acts'].isin(sorted(natres_sectors(targets)))].rename(columns={'acts': 'sector', 'endw': 'factor', 'EVFP': 'evfp'})[['region', 'sector', 'factor', 'evfp']]
    return _natres_eta_s12(ev, d[['region', 'sector', 'cost_musd', 'eta_target', 'sigma_va', 'guard', 'theta_va_used']])


def natres_booked(nat12, config, applied, blend=None, tol=1e-5):
    """S14-Hnatcfg: the B16 targets S14 applies are the ones S12 booked, and S12 booked the config's rule.
    nat12: natres_s12.csv (region, sector, eta_target, sigma_va, theta_va_used, msp_oil_gas_support_weight); config:
    {sector: dict(eta, sigma)} (config/s12/natres_targets.csv); applied: the B16 rows S14 wrote (region, sector, eta_target,
    sigma_va); blend: None, or dict(sector='msp', fossil='oil') when S12 msp_natres_target is the w13 blend.
      1. every booked cell has sigma_va equal to the config's, and eta_target equal to the config's, except a blended cell
         (blend sector with a weight w), whose eta_target must be the effective eta of the w13 blend recomputed from the
         booked w and theta_va_used: share = w sigma/(eta_fossil theta + sigma) + (1 - w) sigma/(eta theta + sigma),
         eta = sigma (1/share - 1)/theta (within tol relative to max(1, eta): natres_s12.csv is written to 6 decimals);
      2. every cell S14 applied a target to is booked, with the same eta_target and sigma_va (1e-12)."""
    need = {'region', 'sector', 'eta_target', 'sigma_va'}
    if not need <= set(nat12.columns):
        return 1, 'natres_s12.csv has no eta_target or sigma_va column (S12 not run under the ch.12.A rule)'
    bad = []
    bk = nat12.dropna(subset=['eta_target'])
    for x in bk.itertuples():
        t = config.get(x.sector)
        if t is None:
            bad.append(f'{x.region} {x.sector}: booked but not a config resource sector')
            continue
        if not np.isclose(x.sigma_va, t['sigma'], rtol=0, atol=1e-9):
            bad.append(f'{x.region} {x.sector}: S12 sigma_va {x.sigma_va} vs config {t["sigma"]}')
        w = getattr(x, 'msp_oil_gas_support_weight', np.nan)
        if blend and x.sector == blend['sector'] and np.isfinite(w):
            th, sg = float(x.theta_va_used), float(x.sigma_va)
            share = w * sg / (config[blend['fossil']]['eta'] * th + sg) + (1.0 - w) * sg / (t['eta'] * th + sg)
            want = sg * (1.0 / share - 1.0) / th
        else:
            want = t['eta']
        if not abs(x.eta_target - want) <= tol * max(1.0, abs(want)):
            bad.append(f'{x.region} {x.sector}: S12 eta_target {x.eta_target} vs the rule {want:.9g}')
    b = bk.set_index(['region', 'sector'])[['eta_target', 'sigma_va']]
    for x in applied.itertuples():
        k = (x.region, x.sector)
        if k not in b.index:
            bad.append(f'{x.region} {x.sector}: S14 applied a target S12 did not book')
            continue
        for col in ('eta_target', 'sigma_va'):
            if not abs(getattr(x, col) - b.loc[k, col]) <= 1e-12 * max(1.0, abs(b.loc[k, col])):
                bad.append(f'{x.region} {x.sector}: S14 {col} {getattr(x, col)} vs S12 booked {b.loc[k, col]}')
    return len(bad), _detail(bad)


def natres_pro_rata(en, delta, tol=TOL):
    """S14-Hnatpro: in every cell the B16 step moved (delta rows with rule RULE_NATRES), labour (every group) and capital
    change by one factor on EVFP, EVFB and EVOS alike, so each keeps its tax rates; land does not move; natural resources
    that were there keep their EVFB/EVFP and EVOS/EVFB; and the cell's EVFP total is unchanged."""
    if delta is None or not len(delta):
        return 0, ''
    d = delta[delta['rule'] == RULE_NATRES]
    if not len(d):
        return 0, ''
    a = en.set_index(['region', 'endw', 'acts'])[['EVFP', 'EVFB', 'EVOS']]
    cf = delta[delta['rule'] == RULE_CAPITAL_MIN]
    if len(cf):      # the capital floor runs after B16: compare with the factors as B16 left them
        a = a.sub(cf.groupby(['region', 'endw', 'acts'])[['EVFP', 'EVFB', 'EVOS']].sum(), fill_value=0.0)
    dd = d.groupby(['region', 'endw', 'acts'])[['EVFP', 'EVFB', 'EVOS']].sum()
    va = en.groupby(['region', 'acts'])['EVFP'].sum()
    bad = []
    for (r, s), g in dd.groupby(level=['region', 'acts']):
        fac = {}
        for (r_, e, s_), x in g.iterrows():
            aft = a.loc[(r_, e, s_)] if (r_, e, s_) in a.index else pd.Series(0.0, index=['EVFP', 'EVFB', 'EVOS'])
            bef = aft - x
            if e == 'land':
                bad.append(f'{r} {s}: land moved')
            elif e == 'natres':
                if bef['EVFP'] > tol and bef['EVFB'] > 0 and aft['EVFB'] > 0:
                    if abs(aft['EVFB'] / aft['EVFP'] - bef['EVFB'] / bef['EVFP']) > tol or abs(aft['EVOS'] / aft['EVFB'] - bef['EVOS'] / bef['EVFB']) > tol:
                        bad.append(f'{r} {s}: natural-resource tax rates changed')
            else:
                for k in ('EVFP', 'EVFB', 'EVOS'):
                    if abs(bef[k]) > tol:
                        fac.setdefault(e, []).append(aft[k] / bef[k])
        allf = [v for vs in fac.values() for v in vs]
        if allf and max(allf) - min(allf) > tol:
            bad.append(f'{r} {s}: labour and capital do not move by one factor ({min(allf):.9f} to {max(allf):.9f})')
        if abs(g['EVFP'].sum()) > tol * max(1.0, abs(va.get((r, s), 0.0))):
            bad.append(f'{r} {s}: EVFP total moved by {g["EVFP"].sum():.6g}')
    return len(bad), _detail(bad)


PTAX_S13_REL, PTAX_S13_MUSD = 1e-6, 1.0     # S14-Hptaxs13: the final tables against S13's held product tax by region


def product_tax_s13(acc, pse_input, s13, rel=PTAX_S13_REL, musd=PTAX_S13_MUSD):
    """S14-Hptaxs13 (round-3 QA item 3, S13 product_tax_totals): every region's net product tax in the final tables
    (firms, households, government and investment: purchasers' less basic values, less the PSE input support booked on
    them, pse_input {region: USD m, negative}) equals the TLS S13 held (product_tax_regions_s13.csv fitted_musd: the
    io_s12 general money plus the held energy-tax rates on the fitted energy purchases, less the fuel subsidies), within
    max(rel x |S13|, musd). Returns (failures, detail, DataFrame region, s13_musd, s14_musd, gap_musd, qa_prior_musd)."""
    t = acc[['tax_firms', 'tax_private', 'tax_government', 'tax_investment']].sum(axis=1)
    t = t - pd.Series(pse_input, dtype=float).reindex(t.index).fillna(0.0)
    p = s13.set_index('region').reindex(t.index)
    df = pd.DataFrame({'s13_musd': p['fitted_musd'], 's14_musd': t, 'qa_prior_musd': p['prior_musd']})
    df['gap_musd'] = df['s14_musd'] - df['s13_musd']
    bad = [f'{r} {x.s14_musd / 1e3:.4f} vs S13 {x.s13_musd / 1e3:.4f} bn' if np.isfinite(x.s13_musd) else f'{r} has no S13 row'
           for r, x in df.iterrows() if not np.isfinite(x.s13_musd) or abs(x.gap_musd) > max(rel * abs(x.s13_musd), musd)]
    df.index.name = 'region'
    return len(bad), _detail(bad), df.reset_index()


def capital_floor_held(en, kmin):
    """Beta v4 capital_floor: every activity with value added pays capital of at least min(kmin, half its VA), or
    has no labour left to move. Returns (failures, detail)."""
    va = en.groupby(['region', 'acts'])['EVFP'].sum()
    k = en[en['endw'] == 'capital'].groupby(['region', 'acts'])['EVFP'].sum().reindex(va.index).fillna(0.0)
    lab = en[~en['endw'].isin(('capital', 'land', 'natres'))].groupby(['region', 'acts'])['EVFP'].sum().reindex(va.index).fillna(0.0)
    need = np.minimum(kmin, 0.5 * va)
    bad = va[(va > 0) & (k < need * (1 - 1e-6)) & (lab > 1e-15)]
    return len(bad), _detail([f'{r} {a}: capital {k[(r, a)]:.3g} of VA {v:.3g}' for (r, a), v in bad.items()])
