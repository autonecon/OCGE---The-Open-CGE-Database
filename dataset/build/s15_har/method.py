"""S15: the S14 header tables as dense GTAPv7 arrays, the three HAR files, and the JLS bundle.

Array axes follow notes/model_requirements.md §1b (COMM x ACTS x REG and so on), with the set elements in
the order of sets_s14.csv. Nothing is changed: every value is the S14 value, and S15-Hdense checks that each
array sums back to its long table.
"""
import os

import numpy as np
import pandas as pd

from . import har

# header, table, columns of the long table that index it, dims, description (descriptions as in the standard GTAP files)
DATA_HEADERS = [
    ('VDFB', 'firms', ['comm', 'acts', 'region'], ['COMM', 'ACTS', 'REG'], 'Domestic purchases, by firms, at basic prices'),
    ('VDFP', 'firms', ['comm', 'acts', 'region'], ['COMM', 'ACTS', 'REG'], "Domestic purchases, by firms, at purchasers' prices"),
    ('VMFB', 'firms', ['comm', 'acts', 'region'], ['COMM', 'ACTS', 'REG'], 'Import purchases, by firms, at basic prices'),
    ('VMFP', 'firms', ['comm', 'acts', 'region'], ['COMM', 'ACTS', 'REG'], "Import purchases, by firms, at purchasers' prices"),
    ('VDPB', 'final', ['comm', 'region'], ['COMM', 'REG'], 'Domestic purchases, by households, at basic prices'),
    ('VDPP', 'final', ['comm', 'region'], ['COMM', 'REG'], "Domestic purchases, by households, at purchasers' prices"),
    ('VMPB', 'final', ['comm', 'region'], ['COMM', 'REG'], 'Import purchases, by households, at basic prices'),
    ('VMPP', 'final', ['comm', 'region'], ['COMM', 'REG'], "Import purchases, by households, at purchasers' prices"),
    ('VDGB', 'final', ['comm', 'region'], ['COMM', 'REG'], 'Domestic purchases, by government, at basic prices'),
    ('VDGP', 'final', ['comm', 'region'], ['COMM', 'REG'], "Domestic purchases, by government, at purchasers' prices"),
    ('VMGB', 'final', ['comm', 'region'], ['COMM', 'REG'], 'Import purchases, by government, at basic prices'),
    ('VMGP', 'final', ['comm', 'region'], ['COMM', 'REG'], "Import purchases, by government, at purchasers' prices"),
    ('VDIB', 'final', ['comm', 'region'], ['COMM', 'REG'], 'Domestic purchases, by investment, at basic prices'),
    ('VDIP', 'final', ['comm', 'region'], ['COMM', 'REG'], "Domestic purchases, by investment, at purchasers' prices"),
    ('VMIB', 'final', ['comm', 'region'], ['COMM', 'REG'], 'Import purchases, by investment, at basic prices'),
    ('VMIP', 'final', ['comm', 'region'], ['COMM', 'REG'], "Import purchases, by investment, at purchasers' prices"),
    ('EVFB', 'endw', ['endw', 'acts', 'region'], ['ENDW', 'ACTS', 'REG'], 'Primary factor purchases, by firms, at basic prices'),
    ('EVFP', 'endw', ['endw', 'acts', 'region'], ['ENDW', 'ACTS', 'REG'], "Primary factor purchases, at purchasers' prices"),
    ('EVOS', 'endw', ['endw', 'acts', 'region'], ['ENDW', 'ACTS', 'REG'], 'Factor remuneration after income tax'),
    ('VXSB', 'bilateral', ['comm', 'src', 'dst'], ['COMM', 'REG', 'REG'], 'Non-margin exports, at basic prices'),
    ('VFOB', 'bilateral', ['comm', 'src', 'dst'], ['COMM', 'REG', 'REG'], 'Non-margin exports, at FOB prices'),
    ('VCIF', 'bilateral', ['comm', 'src', 'dst'], ['COMM', 'REG', 'REG'], 'Imports, at CIF prices'),
    ('VMSB', 'bilateral', ['comm', 'src', 'dst'], ['COMM', 'REG', 'REG'], 'Imports, at basic prices'),
    ('VST', 'vst', ['marg', 'region'], ['MARG', 'REG'], 'Margin exports, at basic prices'),
    ('VTWR', 'vtwr', ['marg', 'comm', 'src', 'dst'], ['MARG', 'COMM', 'REG', 'REG'], 'Margins by margin commodity, good, source and destination'),
    ('SAVE', 'regional', ['region'], ['REG'], 'Net saving, by region'),
    ('VDEP', 'regional', ['region'], ['REG'], 'Capital depreciation'),
    ('VKB', 'regional', ['region'], ['REG'], 'Capital stock'),
    ('POP', 'regional', ['region'], ['REG'], 'Population (millions)'),
    ('MAKS', 'make', ['comm', 'acts', 'region'], ['COMM', 'ACTS', 'REG'], 'Make matrix at supply prices'),
    ('MAKB', 'make', ['comm', 'acts', 'region'], ['COMM', 'ACTS', 'REG'], 'Make matrix at basic prices (incl. output taxes)'),
]
PAR_HEADERS = [
    ('ESBT', ['ACTS', 'REG'], 'Elasticity of substitution, intermediate inputs vs value added'),
    ('ESBC', ['ACTS', 'REG'], 'Elasticity of substitution among intermediate inputs'),
    ('ESBV', ['ACTS', 'REG'], 'Elasticity of substitution among primary factors'),
    ('ETRQ', ['ACTS', 'REG'], 'CET elasticity, commodities produced by an activity'),
    ('ESBQ', ['COMM', 'REG'], 'CES elasticity, activities producing a commodity'),
    ('INCP', ['COMM', 'REG'], 'CDE expansion parameter'),
    ('SUBP', ['COMM', 'REG'], 'CDE substitution parameter'),
    ('ESBG', ['REG'], 'Elasticity of substitution, government purchases'),
    ('ESBI', ['REG'], 'Elasticity of substitution, investment purchases'),
    ('ESBD', ['COMM', 'REG'], 'Armington elasticity, domestic vs imported'),
    ('ESBM', ['COMM', 'REG'], 'Armington elasticity among import sources'),
    ('ESBS', ['MARG'], 'Elasticity of substitution among margin suppliers'),
    ('ETRE', ['ENDW', 'REG'], 'CET elasticity, sluggish factor allocation'),
    ('RFLX', ['REG'], 'Flexibility of expected net rate of return'),
    ('EFLG', ['ENDW', 'ENDT'], 'Factor mobility: mobile, sluggish or fixed'),
]
SET_HEADERS = [('REG', 'Regions'), ('COMM', 'Traded commodities'), ('ACTS', 'Activities'), ('ENDW', 'Endowments'),
               ('MARG', 'Margin commodities'), ('ENDT', 'Endowment mobility types')]
ENDT = ['mobile', 'sluggish', 'fixed']
LABOUR = ['off_mgr_pros', 'tech_aspros', 'clerks', 'service_shop', 'ag_othlowsk']
TABLE_FILES = {'firms': 'firms_s14.csv.gz', 'final': 'final_demand_s14.csv.gz', 'endw': 'endowments_s14.csv.gz',
               'make': 'make_s14.csv.gz', 'bilateral': 'bilateral_s14.csv.gz', 'vtwr': 'vtwr_s14.csv.gz',
               'vst': 'vst_s14.csv', 'regional': 'regional_s14.csv'}


def read_sets(df):
    """{set: [elements in position order]}, with ENDT added."""
    s = {k: g.sort_values('position')['element'].tolist() for k, g in df.groupby('set')}
    s['ENDT'] = list(ENDT)
    return s


def dense(table, keys, dims, col, sets):
    """One header as a dense array from its long table (non-zero rows only; the rest are zero)."""
    shape = tuple(len(sets[d]) for d in dims)
    out = np.zeros(shape)
    if not len(table):
        return out
    idx = []
    for k, d in zip(keys, dims):
        pos = {e: i for i, e in enumerate(sets[d])}
        ix = table[k].map(pos)
        if ix.isna().any():
            raise ValueError(f'{col}: {k} values not in set {d}: {sorted(set(table.loc[ix.isna(), k]))[:5]}')
        idx.append(ix.to_numpy(int))
    np.add.at(out, tuple(idx), table[col].to_numpy(float))
    return out


def data_arrays(tables, sets):
    return {h: dense(tables[t], k, d, h, sets) for h, t, k, d, _ in DATA_HEADERS}


def parameter_arrays(sets, el, scalars, incp, subp):
    """The gsdfpar arrays. el: sector elasticities indexed by sector; scalars: s15_scalars.csv."""
    nc, nr = len(sets['COMM']), len(sets['REG'])
    sc = scalars.set_index(['parameter', 'element'])['value']
    col = lambda c: np.repeat(el.loc[sets['COMM'], c].to_numpy(float)[:, None], nr, axis=1)
    full = lambda p: np.full((nc, nr), float(sc[(p, 'all')]))
    P = {
        'ESBT': full('ESBT'), 'ESBC': full('ESBC'), 'ESBV': col('esubva'), 'ETRQ': full('ETRQ'), 'ESBQ': full('ESBQ'),
        'INCP': incp, 'SUBP': subp, 'ESBG': np.full(nr, float(sc[('ESBG', 'all')])), 'ESBI': np.full(nr, float(sc[('ESBI', 'all')])),
        'ESBD': col('esubd'), 'ESBM': col('esubm'), 'ESBS': np.full(len(sets['MARG']), float(sc[('ESBS', 'all')])),
        'RFLX': np.full(nr, float(sc[('RFLX', 'all')])),
    }
    etre = np.zeros((len(sets['ENDW']), nr))
    eflg = np.zeros((len(sets['ENDW']), len(ENDT)))
    for i, e in enumerate(sets['ENDW']):
        key = e if (('EFLG', e) in sc.index) else ('labour' if e in LABOUR else None)
        if key is None:
            raise ValueError(f'no EFLG row for factor {e}')
        kind = sc[('EFLG', key)]
        eflg[i, ENDT.index(kind)] = 1.0
        etre[i, :] = float(sc[('ETRE', e)]) if ('ETRE', e) in sc.index else float(sc[('ETRE', 'mobile')])
        if kind == 'mobile' and etre[i, 0] != 0:
            raise ValueError(f'{e}: mobile factor with a non-zero ETRE')
    P['ETRE'] = etre
    P['EFLG'] = eflg
    return P, int(sc[('RDLT', 'all')])


def write_har(outdir, sets, data, par, rdlt, drel):
    """gsdfset.har, gsdfpar.har, gsdfdat.har. Returns their paths."""
    paths = {k: os.path.join(outdir, f'gsdf{k}.har') for k in ('set', 'par', 'dat')}
    with open(paths['set'], 'wb') as fh:
        har.write_1c(fh, 'DREL', 'Data base release: name, base year, upstream S14 checksum', drel)
        for name, desc in SET_HEADERS:
            har.write_1c(fh, name, f'Set {name} {desc.lower()}', sets[name])
    with open(paths['par'], 'wb') as fh:
        har.write_1c(fh, 'DREL', 'Data base release: name, base year, upstream S14 checksum', drel)
        for name, dims, desc in PAR_HEADERS:
            har.write_re(fh, name, desc, dims, sets, par[name])
        har.write_2i(fh, 'RDLT', 'Investment allocation switch (RORDELTA)', rdlt)
    with open(paths['dat'], 'wb') as fh:
        har.write_1c(fh, 'DREL', 'Data base release: name, base year, upstream S14 checksum', drel)
        for name, _, _, dims, desc in DATA_HEADERS:
            har.write_re(fh, name, desc, dims, sets, data[name])
    return paths


def expected_dims(sets):
    """header -> (file, dims, shape) for every header the stage writes."""
    out = {}
    for name, desc in SET_HEADERS:
        out[name] = ('set', [name], (len(sets[name]),))
    out['DREL'] = ('set', ['DREL'], (3,))
    for name, dims, _ in PAR_HEADERS:
        out[name] = ('par', dims, tuple(len(sets[d]) for d in dims))
    out['RDLT'] = ('par', [], (1, 1))
    for name, _, _, dims, _ in DATA_HEADERS:
        out[name] = ('dat', dims, tuple(len(sets[d]) for d in dims))
    return out


def write_bundle(path, sets, data, par, rdlt, drel):
    """Raw Float64 arrays (Fortran order) and a manifest, for julia/write_jls.jl (Julia Base only)."""
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, 'sets.txt'), 'w') as fh:
        for k in ['REG', 'COMM', 'ACTS', 'ENDW', 'MARG', 'ENDT']:
            fh.write(f'{k}|{",".join(e.lower() for e in sets[k])}\n')
        fh.write(f'DREL|{",".join(drel)}\n')
    with open(os.path.join(path, 'manifest.txt'), 'w') as fh:
        for group, items in (('data', [(h, d) for h, _, _, d, _ in DATA_HEADERS]), ('parameters', [(h, d) for h, d, _ in PAR_HEADERS])):
            for h, d in items:
                arr = (data if group == 'data' else par)[h]
                np.asarray(arr, dtype='<f8').ravel(order='F').tofile(os.path.join(path, f'{h}.f64'))
                fh.write(f'{group}|{h}|{",".join(d)}|{",".join(str(n) for n in np.shape(arr))}\n')
        fh.write(f'scalar|RDLT|{rdlt}\n')


# ---------------------------------------------------------------- accounts on dense arrays

def regional_accounts(D, cap):
    """Regional income Y and SAVE on dense arrays (the S14 regional_accounts, array form). cap: ENDW index of capital."""
    s = lambda a, ax: a.sum(axis=ax)
    tax = (s(D['VDFP'] - D['VDFB'] + D['VMFP'] - D['VMFB'], (0, 1))
           + s(D['VDPP'] - D['VDPB'] + D['VMPP'] - D['VMPB'], 0)
           + s(D['VDGP'] - D['VDGB'] + D['VMGP'] - D['VMGB'], 0)
           + s(D['VDIP'] - D['VDIB'] + D['VMIP'] - D['VMIB'], 0)
           + s(D['MAKB'] - D['MAKS'], (0, 1)) + s(D['EVFP'] - D['EVFB'], (0, 1))
           + s(D['VFOB'] - D['VXSB'], (0, 2)) + s(D['VMSB'] - D['VCIF'], (0, 1)))
    C = s(D['VDPP'] + D['VMPP'], 0)
    G = s(D['VDGP'] + D['VMGP'], 0)
    I = s(D['VDIP'] + D['VMIP'], 0)
    Y = s(D['EVFB'], (0, 1)) - D['VDEP'] + tax
    X = s(D['VFOB'], (0, 2)) + s(D['VST'], 0)
    M = s(D['VCIF'], (0, 1))
    return pd.DataFrame(dict(Y=Y, C=C, G=G, I=I, X=X, M=M, SAVE_model=Y - C - G, SAVE=D['SAVE'], VDEP=D['VDEP'], VKB=D['VKB'],
                             capital_income=D['EVOS'][cap].sum(axis=0)))


def map_groups(regions, rmap):
    """Group of each region under a map CSV (region, group; '*' is every region not listed)."""
    m = dict(zip(rmap['region'], rmap['group']))
    rest = m.pop('*', None)
    bad = sorted(set(m) - set(regions))
    if bad:
        raise ValueError(f'map regions not in REG: {bad}')
    if rest is None and set(regions) - set(m):
        raise ValueError('map leaves regions out and has no * row')
    return [m.get(r, rest) for r in regions]


def map_saving_gate(acc, regions, groups):
    """Saving share sigma_save = SAVE/Y and investment share sigma_qinv = SAVE/world SAVE for each group of a
    map: the Julia model bounds both by [-1, 1] (src/solve_model.jl)."""
    a = acc.assign(group=groups, region=regions).groupby('group')[['SAVE', 'Y']].sum()
    a['sigma_save'] = a['SAVE'] / a['Y']
    a['sigma_qinv'] = a['SAVE'] / a['SAVE'].sum()
    return a


HH_SEED_SHARE = 1e-7     # beta v4 P10: the seed, a share of the region's household spending at purchasers' prices


def seed_household_crude(D, comm, acts, regs, share=HH_SEED_SHARE, crude='oil', refin='pet', top_up=True):
    """Beta v4 P10 (choice household_crude_seed; our choice, GTAP 12 has no rule for zero cells): where households buy less
    crude than share x their spending (none, or a fit residue), they buy eps more, up to that share, at zero tax, from the source the refinery buys it from (domestic if
    the refinery buys domestic crude, else imported). The refinery buys eps less of that crude at basic prices, so crude
    supply and import clearing hold; its cost falls by eps x tf (tf: the cell's tax power), so refined output falls by
    eps x tf at supply prices (MAKS) and eps x tf x k at basic (MAKB, k = MAKB / MAKS), and households buy that much less
    domestic refined product at basic, th times it at purchasers' prices. Regional income and household spending both move
    by eps x (1 - tf k th), so SAVE is unchanged. D is changed in place.
    Returns rows (region, source, eps, refined_basic_cut, status); status 'skipped_...' where a needed cell is too small."""
    ci, ai = comm.index(crude), comm.index(refin)
    pa = acts.index(refin)
    rows = []
    for r, reg in enumerate(regs):
        # beta v4 rescan (S16 2026-10-26, USA 2.1e-05 USD m): a cell below the seed is topped up to it, so a household crude
        # share is either the seed or above it, never a near-zero fit residue (P15 puts the whole crude row on refining)
        cur = float(D['VDPP'][ci, r] + D['VMPP'][ci, r])
        target = share * float(D['VDPP'][:, r].sum() + D['VMPP'][:, r].sum())
        if cur >= target * (1 - 1e-9) or (cur > 0 and not top_up):
            continue
        eps = target - cur
        src = 'dom' if D['VDFB'][ci, pa, r] >= eps else ('imp' if D['VMFB'][ci, pa, r] >= eps else None)
        if src is None or eps <= 0:
            rows.append(dict(region=reg, source='', eps=eps, refined_basic_cut=0.0, status='skipped_no_refinery_crude'))
            continue
        FB, FP, PB, PP = (('VDFB', 'VDFP', 'VDPB', 'VDPP') if src == 'dom' else ('VMFB', 'VMFP', 'VMPB', 'VMPP'))
        tf = D[FP][ci, pa, r] / D[FB][ci, pa, r]
        k = D['MAKB'][ai, pa, r] / D['MAKS'][ai, pa, r] if D['MAKS'][ai, pa, r] > 0 else np.nan
        th = D['VDPP'][ai, r] / D['VDPB'][ai, r] if D['VDPB'][ai, r] > 0 else np.nan
        cut = eps * tf * k
        if not (np.isfinite(cut) and np.isfinite(th)) or D['VDPB'][ai, r] < cut or D['MAKS'][ai, pa, r] < eps * tf:
            rows.append(dict(region=reg, source=src, eps=eps, refined_basic_cut=0.0, status='skipped_no_household_refined_product'))
            continue
        D[FB][ci, pa, r] -= eps
        D[FP][ci, pa, r] -= eps * tf
        D[PB][ci, r] += eps
        D[PP][ci, r] += eps
        D['MAKS'][ai, pa, r] -= eps * tf
        D['MAKB'][ai, pa, r] -= cut
        D['VDPB'][ai, r] -= cut
        D['VDPP'][ai, r] -= cut * th
        rows.append(dict(region=reg, source=src, eps=eps, refined_basic_cut=cut, status='seeded'))
    return rows
