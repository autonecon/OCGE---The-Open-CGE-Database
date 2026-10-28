"""S14 final assembly method (GTAP 12 ch.17B §B.2; PLAN §3(i) global pass).

The assembly module merges the interim global file (io_s13 and factors_s13, from FIT) with the bilateral
trade data (S10 goods, S11 energy, S09 services and travel), the margins by route (S08 goods, S11 energy),
the protection data already inside those flows, and the capital stock and depreciation (S02). It writes the
31 GTAPv7 data headers the Julia model reads (notes/model_requirements.md §1b) as long tables.

Steps:
  1. Bilateral VXSB, VFOB, VCIF, VMSB by commodity and route; VTWR by margin, commodity and route; VST.
  2. Re-balancing (17B §B.2 fourth item). The stage outputs are rounded to 1e-6 USD million, so the
     identities hold only up to rounding. S14 makes them exact: VCIF = VFOB + sum of VTWR on each route
     (VMSB keeps its tariff power), world VST = world VTWR by margin (one factor per margin), each region's
     imported purchases add up to its VMSB (the residual goes to the largest activity cell of the row),
     output = domestic sales (market clearing) and the output tax closes zero profit. Every move is bounded
     by REBAL_MAX; a larger gap is not rounding and fails the stage (no plugs).
  3. Purchaser values (purchaser_split): every cell keeps its S13 net product-tax rate (tax_cells_s13; fix
     list A1: the pet, coa, gas and ely rows at their energy-tax rates; QA round 2 P1: the non-energy rows at their
     commodity rates from S13 non_energy_rates), the same on domestic and imported purchases. Each column's cells
     are its S13 cell wedges over the column's median non-energy rate plus one remainder rate, which is that median
     up to rounding, set so that the column's tax equals its io_s13 TLS and
     PSE_input over its basic purchases (cell_powers). With purchaser_split one_tax_power_per_column (no
     tax_cells_s13) every cell of a column has the column's one power, as before the fix round.
  4. MAKB is diagonal and equals output at basic prices; MAKS = MAKB less the output tax (to = MAKB/MAKS).
  5. EVFP, EVFB and EVOS from factors_s13 as they are (S13 prior_without_va leaves no activity with output
     and no positive value added; S14-Hsign and S14-Hzerodiv check it).
  6. Regional accounts: SAVE = Y - C - G with Y = sum EVFB - VDEP + all indirect taxes (the model's
     regional income), so S - (I - VDEP) = X - M (GTAP 12 ch.7 eq. 7.1).

Two ledgered steps run before the re-balancing (fix round, 2026-10-24):
  B14. Trade cells below USD 1 (SMALL_TRADE): a route with VXSB below it is dropped with its VTWR, and a VTWR
       cell below it is set to zero (VCIF falls by it, VMSB keeps its tariff power). Our choice: GTAP filters
       small values, but its threshold is not in the documents we hold.
  A13. One-sided pairs (a commodity a region buys only from imports): each buyer gets domestic purchases of
       SEED_RATIO times its imported purchase, and gives up the same basic value of its other purchases, pro
       rata (a column whose other purchases are too small for that gives up at most SEED_GIVE_UP_MAX of them, and the
       rest of the row's seed goes to the other buyers pro rata to their imports). The supplying activities lose those sales and hand the matching share of their whole column
       (inputs, product taxes, factor payments) to the new domestic activity, which therefore has the cost
       structure of the region's own supplying columns. Every row total, column total, factor total, tax total,
       C, G, I, X, M and GDP stay as they were. GTAP 10 has no one-sided pair; the size and the carve rule
       are our choice.
       The other side (import_seed_swaps): a commodity bought only from domestic producers imports SEED_RATIO of
       its domestic purchases through a tax-free, margin-free swap with a partner exporter (two routes of the same
       size), and both regions switch that much of their domestic purchases to imports, so every total stays.

One step runs after the re-balancing (fix round B16, S12-17; GTAP 12 ch.17B: the natural-resource reallocation is
part of the global data assembly, after the FIT):
  B16. In every targeted resource activity (for, fsh, coa, oil, gas, ore, min, msp) the natural-resource share of
       value added is set again on the S14 data, so the GTAP 7 ch.12.A target supply elasticity holds on the final
       data and not only at S12's prior (natres_final). Income moves between natural resources and labour plus
       capital (pro rata); each column's value added and cost, and every factor's tax rates, stay as they are.
"""
import numpy as np
import pandas as pd

from s13_fit.method import FD, FACTORS, ENERGY_TRADE, MARGINS, ENERGY_TAX_ROWS
from s12_factors.method import natres_target_share, implied_eta

REBAL_MAX = 1e-3            # USD million: the largest move the re-balancing may make (rounding only)
SMALL_TRADE = 1e-6          # USD million (USD 1): VXSB routes and VTWR cells below it are set to zero (fix list B14; our choice)
SEED_RATIO = 1e-4           # A13: domestic purchases seeded in a one-sided pair, as a share of its imported purchases (our choice)
SEED_GIVE_UP_MAX = 0.5      # A13: a buyer column gives up at most this share of its other purchases for the seed (our choice; see seed_one_sided)
SEED_MIN = 1e-5             # USD million (USD 10): beta v4 capital_floor, the smallest A13 seed, at most SEED_MIN_SHARE of the imports (our choice)
SEED_MIN_SHARE = 0.5
CAPITAL_MIN = 1e-6          # USD million (USD 1): beta v4 capital_floor, the capital of an activity with VA, at most half its VA (our choice)
RULE_SMALL = 'B14 trade cells below USD 1 set to zero'
RULE_CAPITAL_MIN = 'capital floor: capital at least USD 1 (at most half of VA) in an activity with value added'
RULE_SEED = 'A13 seed domestic supply in a one-sided pair'
RULE_CARVE = 'A13 seed cost structure carved from the supplying columns'
RULE_SWAP = 'A13 seed imports in a domestic-only pair (swap with a partner exporter)'
SWAP_PARTNER_MAX = 1e-2     # A13 swap: a partner switches at most this share of its domestic purchases of the good (our choice)
RULE_NATRES = 'B16 natural resources at the ch.12.A target on the S14 data'
RULE_SEED_FACTOR = 'A13 land and natural resources in a seeded column paid as capital'
NATRES_LK = tuple(f for f in FACTORS if f not in ('land', 'natres'))      # labour (all groups) and capital: the pro rata base
ROUTE = ['comm', 'src', 'dst']
BORDER = ['VXSB', 'VFOB', 'VCIF', 'VMSB']
FD_HEADERS = {'p': ('VDPB', 'VDPP', 'VMPB', 'VMPP'),
              'g': ('VDGB', 'VDGP', 'VMGB', 'VMGP'),
              'i': ('VDIB', 'VDIP', 'VMIB', 'VMIP')}
HEADERS = ('VDFB', 'VDFP', 'VMFB', 'VMFP', 'VDPB', 'VDPP', 'VMPB', 'VMPP', 'VDGB', 'VDGP', 'VMGB', 'VMGP',
           'VDIB', 'VDIP', 'VMIB', 'VMIP', 'EVFB', 'EVFP', 'EVOS', 'MAKS', 'MAKB', 'VXSB', 'VFOB', 'VCIF',
           'VMSB', 'VST', 'VTWR', 'SAVE', 'VDEP', 'VKB', 'POP')


# ------------------------------------------------------------------ 1. trade
def bilateral(goods_x, goods_m, en_x, en_m, svc, travel):
    """Route-level border values by commodity. goods_x/goods_m: S10 vfob/vmsb (energy rows are dropped, as
    in S13); en_x/en_m: S11 energy; svc: S09 services VXSB (every source row); travel: the travel rows S13
    held (exporter = host, importer = visitor, sector, v). Services and travel have no margin and no border
    tax, so VXSB = VFOB = VCIF = VMSB on them."""
    def ren(df):
        return df.rename(columns={'sector': 'comm', 'exporter': 'src', 'importer': 'dst', 'vxsb_musd': 'VXSB',
                                  'vfob_musd': 'VFOB', 'vcif_musd': 'VCIF', 'vmsb_musd': 'VMSB'})
    gx = ren(goods_x[~goods_x['sector'].isin(ENERGY_TRADE)])[ROUTE + ['VXSB', 'VFOB']]
    gm = ren(goods_m[~goods_m['sector'].isin(ENERGY_TRADE)])[ROUTE + ['VCIF', 'VMSB']]
    ex = ren(en_x)[ROUTE + ['VXSB', 'VFOB']]
    em = ren(en_m)[ROUTE + ['VCIF', 'VMSB']]
    parts = [gx.merge(gm, on=ROUTE, how='outer'), ex.merge(em, on=ROUTE, how='outer')]
    s = ren(svc).groupby(ROUTE, as_index=False)['VXSB'].sum()
    t = travel.rename(columns={'sector': 'comm', 'exporter': 'src', 'importer': 'dst', 'v': 'VXSB'}).groupby(ROUTE, as_index=False)['VXSB'].sum()
    for d in (s, t):
        parts.append(d.assign(VFOB=d['VXSB'], VCIF=d['VXSB'], VMSB=d['VXSB']))
    b = pd.concat([p_.astype({c: float for c in BORDER if c in p_.columns}) for p_ in parts if len(p_)], ignore_index=True)
    b = b.fillna(0.0).groupby(ROUTE, as_index=False)[BORDER].sum()
    return b[(b[BORDER] != 0).any(axis=1)].sort_values(ROUTE).reset_index(drop=True)


def margins(vtwr_goods, vtwr_energy):
    """VTWR by margin, commodity and route: S08 for goods, S11 for the energy goods (S11 re-priced them)."""
    v = pd.concat([d.astype({'vtwr_musd': float}) for d in (vtwr_goods[~vtwr_goods['sector'].isin(ENERGY_TRADE)], vtwr_energy) if len(d)], ignore_index=True)
    v = v.rename(columns={'margin': 'marg', 'sector': 'comm', 'exporter': 'src', 'importer': 'dst', 'vtwr_musd': 'VTWR'})
    v = v.groupby(['marg'] + ROUTE, as_index=False)['VTWR'].sum()
    return v[v['VTWR'] != 0].sort_values(['marg'] + ROUTE).reset_index(drop=True)


def filter_small_trade(b, v, cut=SMALL_TRADE):
    """B14: set trade cells below `cut` USD million to zero, before the re-balancing and before the A13 seed.
    A route with VXSB < cut is dropped with all its border values and its VTWR cells. On the routes kept, a VTWR
    cell below cut is set to zero, VCIF falls by it and VMSB keeps its tariff power (VMSB/VCIF).
    Returns (b, v, dropped) with dropped: kind (VXSB route or VTWR cell), marg, comm, src, dst, VXSB, VTWR."""
    small = b['VXSB'] < cut
    gone = b.loc[small, ROUTE]
    key = pd.MultiIndex.from_frame(gone)
    vi = pd.MultiIndex.from_frame(v[ROUTE])
    on_gone = vi.isin(key)
    tiny = (~on_gone) & (v['VTWR'].to_numpy(float) < cut)
    dropped = pd.concat([
        b.loc[small, ROUTE + ['VXSB']].assign(kind='VXSB route', marg='', VTWR=v.loc[on_gone].groupby(ROUTE)['VTWR'].sum().reindex(key).fillna(0.0).to_numpy()),
        v.loc[tiny, ['marg'] + ROUTE + ['VTWR']].assign(kind='VTWR cell', VXSB=0.0),
    ], ignore_index=True)[['kind', 'marg'] + ROUTE + ['VXSB', 'VTWR']]
    b = b[~small].copy()
    cut_m = v.loc[tiny].groupby(ROUTE)['VTWR'].sum()
    if len(cut_m):
        idx = b.set_index(ROUTE).index
        d = np.nan_to_num(idx.map(cut_m).to_numpy(float))
        old = b['VCIF'].to_numpy(float)
        new = old - d
        pw = np.where(old > 0, b['VMSB'].to_numpy(float) / np.where(old > 0, old, 1.0), 1.0)
        b['VCIF'] = new
        b['VMSB'] = np.where(d != 0, new * pw, b['VMSB'].to_numpy(float))
    v = v[~on_gone & ~tiny].reset_index(drop=True)
    return b.reset_index(drop=True), v, dropped


def small_trade_vst(vst, v_before, v_after):
    """B14 side effect on the margin supply: world VST of each margin falls with world VTWR (one factor per margin,
    as in the re-balancing), so the re-balancing itself is left with rounding only. Returns the new vst."""
    vst = vst.copy()
    w0 = v_before.groupby('marg')['VTWR'].sum()
    w1 = v_after.groupby('marg')['VTWR'].sum().reindex(w0.index, fill_value=0.0)
    f = (w1 / w0.where(w0 != 0)).reindex(vst['marg']).fillna(1.0).to_numpy()
    vst['VST'] = vst['VST'].to_numpy(float) * f
    return vst


def small_trade_output_shift(dropped, vst_before, vst_after):
    """B14: the fall in each region's sales abroad (VXSB of the dropped routes) and margin supply (VST), by
    (region, commodity): the output each activity loses with the cells set to zero. The output tax absorbs it at
    zero profit (each cell is below USD 1, so the shift is at most a few thousand dollars on activities of
    billions). dropped: filter_small_trade's list."""
    r = dropped[dropped['kind'] == 'VXSB route']
    d = r.groupby(['src', 'comm'])['VXSB'].sum() if len(r) else pd.Series(dtype=float)
    d.index.names = ['region', 'comm']
    m = vst_before.merge(vst_after, on=['marg', 'region'], how='left', suffixes=('', '_after')).fillna({'VST_after': 0.0})
    s = (m['VST'] - m['VST_after']).groupby([m['region'], m['marg']]).sum()
    s.index.names = ['region', 'comm']
    d = d.add(s, fill_value=0.0)
    return d[d != 0]


# ------------------------------------------------------------------ S12 tax splits (fix list A3, A4): stub
# Optional S12 outputs, read when present. Worker w5 (S12) defines their layout; the coordinator joins them.
#   d29_split            A3: other net taxes on production (D29) taken out of value added, by region and activity,
#                        split into the part booked on payroll (factor-use tax on labour, EVFP > EVFB) and the
#                        rest (output tax, MAKB > MAKS); D39 other subsidies as negative output tax.
#   pse_land_factor_use  A4: PSE land-based and area payments moved from the income-tax wedge (EVFB < EVOS) to
#                        the factor-use wedge (EVFP < EVFB) on land, with EVOS unchanged.
S12_OPTIONAL = {'d29_split': 'd29_split_s12.csv', 'pse_land_factor_use': 'pse_land_factor_use_s12.csv'}


def join_s12_tax_split(name, df, tables):
    """Book an optional S12 tax split (S12_OPTIONAL) in the assembled tables. STUB: not joined yet.

    The S14 side, once w5's layout is known: if S13 carries the split through io_s13 (PTAX) and factors_s13
    (EVFP, EVFB, EVOS), S14 books nothing new and this function only checks that the S12 split is what the
    header tables hold (output tax by activity, factor-use and income wedges on labour and land). If S13 does
    not, the split is booked here as moves between wedges that keep EVOS and every column total fixed.
    Raises NotImplementedError so a present file cannot be ignored silently (S14-Hs12join fails)."""
    raise NotImplementedError(f'S12 {name} is present ({len(df)} rows) but the S14 join is a stub (fix list A3/A4)')


# ------------------------------------------------------------------ 2. re-balancing of the trade block
def rebalance_trade(b, v, vst):
    """VCIF = VFOB + sum VTWR on every route (VMSB keeps VMSB/VCIF), and world VST = world VTWR by margin.
    vst: marg, region, VST. Returns (b, vst, moves) with moves: kind, key, before, after."""
    b = b.copy()
    m = v.groupby(ROUTE)['VTWR'].sum()
    mm = b.set_index(ROUTE).index.map(m).to_numpy(float)
    mm = np.nan_to_num(mm)
    new = b['VFOB'].to_numpy(float) + mm
    old = b['VCIF'].to_numpy(float)
    moved = new != old
    pw = np.where(old > 0, b['VMSB'].to_numpy(float) / np.where(old > 0, old, 1.0), 1.0)
    moves = [dict(kind='VCIF', key=f'{x.comm} {x.src} {x.dst}', before=o, after=n)
             for x, o, n in zip(b[moved].itertuples(), old[moved], new[moved])]
    vm_old = b['VMSB'].to_numpy(float)
    # a route whose CIF value is 0 after the fix keeps no VMSB (a rounding remnant of the upstream file)
    vm_new = np.where(old > 0, new * pw, np.where(new > 0, vm_old + (new - old), 0.0))
    moved = moved | ((new == 0) & (vm_old != 0))
    moves += [dict(kind='VMSB', key=f'{x.comm} {x.src} {x.dst}', before=o, after=n)
              for x, o, n in zip(b[moved].itertuples(), vm_old[moved], vm_new[moved])]
    b['VCIF'] = new
    b['VMSB'] = vm_new
    vst = vst.copy()
    tw = v.groupby('marg')['VTWR'].sum()
    ts = vst.groupby('marg')['VST'].sum()
    for mg in sorted(set(tw.index) | set(ts.index)):
        f = tw.get(mg, 0.0) / ts.get(mg, 0.0) if ts.get(mg, 0.0) else np.nan
        sel = vst['marg'] == mg
        if not np.isfinite(f):
            continue
        for x in vst[sel & (vst['VST'] != 0)].itertuples():
            moves.append(dict(kind='VST', key=f'{mg} {x.region}', before=x.VST, after=x.VST * f))
        vst.loc[sel, 'VST'] = vst.loc[sel, 'VST'] * f
    return b, vst, pd.DataFrame(moves, columns=['kind', 'key', 'before', 'after'])


# ------------------------------------------------------------------ 3-5. one region
def seed_one_sided(region, dom, imp, tls, pse, E, out_pre, ptax0, sectors, ratio, issues, seed_min=0.0):
    """A13: seed domestic supply in every commodity the region buys only from imports. Arrays are changed in place.

    dom, imp: basic purchases (COMM x cols, cols = sectors + FD); tls, pse: product-tax rows by column (moved with
    the carved share; assemble_region passes the column's whole product-tax value as tls and zeros as pse); E: factor
    payments {EVFP, EVFB, EVOS: FACTORS x sectors}; out_pre: output by activity before the seed; ptax0: the
    output tax the region carries into the re-balance (S13 PTAX). For each one-sided commodity c:
      1. every column j with imp[c, j] > 0 buys s_j = ratio * imp[c, j] from domestic producers of c, and gives
         up s_j of its purchases of the commodities that are not one-sided in the region, pro rata over its
         domestic and imported cells, so its basic total stays the same (assemble_region then re-sets the
         column's remainder tax rate so that its tax, and so its purchaser total, stays the same too). A column
         gives up at most SEED_GIVE_UP_MAX of those purchases (so no cell turns negative or empties, which would
         make a new one-sided pair); where that binds (fix round w17: URY mvh, a column that buys 443.8 of
         imported crude and 0.013 of everything else), the rest of the row's seed ratio * imports[c] goes to the
         other buyers pro rata to their imports (seed_shares), so the row seed is still exact;
      2. the imported cells given up move into column c as its imported inputs;
      3. each activity k whose domestic sales fell by d_k hands the share d_k / out_pre[k] of its whole column
         (domestic and imported inputs, TLS, PSE_input, EVFP, EVFB, EVOS and its output tax) to column c
         (seed_fixed_factors then pays the land and natural resources it took over as capital).
    So every market, every column's cost, the factor totals, the tax totals, C, G, I and GDP are unchanged, and
    column c has output sum s_j with the cost structure of the region's own supplying columns.
    seed_min (beta v4 capital_floor; 0 turns it off): a row's seed is at least seed_min USD million, at most
    SEED_MIN_SHARE of its imports (the row ratio rises; if the buyers cannot give that up, the plain ratio stands).
    Returns (seeds: one dict per seeded commodity, ptax_delta: the output-tax move by activity)."""
    n = len(sectors)
    rows_d, rows_m = dom.sum(axis=1), imp.sum(axis=1)
    one = [i for i in range(n) if rows_d[i] <= 0 and rows_m[i] > 0]
    ptax_delta = np.zeros(n)
    seeds = []
    if not one:
        return seeds, ptax_delta
    keep = np.ones(n, bool)
    keep[one] = False                      # never give up (or carve) a commodity that is itself being seeded
    for i in one:
        c = sectors[i]
        buyers = np.where(imp[i] > 0)[0]
        base_j = np.array([dom[keep, j].sum() + imp[keep, j].sum() for j in buyers])
        r_i = max(ratio, min(SEED_MIN_SHARE, seed_min / rows_m[i])) if seed_min > 0 else ratio
        s_j = seed_shares(r_i * rows_m[i], imp[i, buyers], r_i * imp[i, buyers], SEED_GIVE_UP_MAX * np.maximum(base_j, 0.0))
        if s_j is None and r_i > ratio:
            r_i = ratio
            s_j = seed_shares(r_i * rows_m[i], imp[i, buyers], r_i * imp[i, buyers], SEED_GIVE_UP_MAX * np.maximum(base_j, 0.0))
        if s_j is None:
            issues.append(f'{region} {c}: the buyers\' other purchases ({base_j.sum():.6g}) cannot give up the A13 seed '
                          f'{r_i * rows_m[i]:.6g} at most {SEED_GIVE_UP_MAX:g} of each')
            continue
        released_d = np.zeros(n)
        for j, s, base in zip(buyers, s_j, base_j):
            if s <= 0:
                continue
            f = s / base
            gd, gm = dom[keep, j] * f, imp[keep, j] * f
            dom[keep, j] -= gd
            imp[keep, j] -= gm
            released_d[keep] += gd
            imp[keep, i] += gm             # 2. the imports given up become column c's imported inputs
            dom[i, j] += s
        # 3. carve the supplying columns
        ptax_moved = 0.0
        for k in np.where(released_d > 0)[0]:
            if out_pre[k] <= 0:
                issues.append(f'{region} {c}: supplier {sectors[k]} has domestic sales but no output')
                continue
            f = released_d[k] / out_pre[k]
            for M_ in (dom, imp):
                mv = M_[:, k] * f
                M_[:, k] -= mv
                M_[:, i] += mv
            for row in (tls, pse):
                mv = row[k] * f
                row[k] -= mv
                row[i] += mv
            for key in ('EVFP', 'EVFB', 'EVOS'):
                mv = E[key][:, k] * f
                E[key][:, k] -= mv
                E[key][:, i] += mv
            pk = (ptax0[k] + ptax_delta[k]) * f      # the output tax column k still carries
            ptax_delta[k] -= pk
            ptax_delta[i] += pk
            ptax_moved += pk
            out_pre[k] -= released_d[k]
        out_pre[i] += s_j.sum()
        va = E['EVFP'][:, i].sum()
        if va <= 0:
            issues.append(f'{region} {c}: the A13 seed has no factor payment (its buyers give up no domestic purchase)')
        seeds.append(dict(region=region, comm=c, imports=float(rows_m[i]), seed=float(s_j.sum()), ratio=float(s_j.sum() / rows_m[i]),
                          n_buyers=int(len(buyers)), seed_va=float(va), seed_ptax=float(ptax_moved),
                          output_before=float(out_pre[i] - s_j.sum()), output_after=float(out_pre[i])))
    return seeds, ptax_delta


def capital_floor(E, kmin=CAPITAL_MIN):
    """Beta v4 capital_floor (S16 alone_bfa: an A13 seed column with VA and capital of 8e-10 USD million calibrated
    with zero capital): every activity with value added pays capital at least min(kmin, half its VA), taken from its
    labour payments pro rata (EVFP, EVFB and EVOS alike, so column VA, factor-tax money and regional income are
    unchanged; land and natural resources are left alone, B16). E changed in place. Returns the activities moved."""
    cap = FACTORS.index('capital')
    lab = [k for k, f in enumerate(FACTORS) if f not in ('capital', 'land', 'natres')]
    moved = []
    for j in range(E['EVFP'].shape[1]):
        va = E['EVFP'][:, j].sum()
        if va <= 0:
            continue
        need = min(kmin, 0.5 * va) - E['EVFP'][cap, j]
        lab_p = E['EVFP'][lab, j].sum()
        if need <= 0 or lab_p <= 0:
            continue
        f = min(need / lab_p, 1.0)
        for key in ('EVFP', 'EVFB', 'EVOS'):
            mv = E[key][lab, j] * f
            E[key][lab, j] -= mv
            E[key][cap, j] += mv.sum()
        moved.append(j)
    return moved


def seed_fixed_factors(E, used, cols):
    """A13 after the carve: land and natural resources a seeded column took over from a supplier that uses them (crp
    buys the import) are paid as capital in a seeded column that did not use them before the seed, so they stay in
    the activities that hold them (GTAP 12 ch.14A land, ch.12A natural resources; fix round S16: 273 dust land and
    80 natres cells in seeded oil, gas, coal, pet and hhe columns slowed calibration). used: {factor: bool by
    activity, before the seed}. Column VA, factor-tax money and regional income are unchanged. E changed in place."""
    cap = FACTORS.index('capital')
    for f_, u in used.items():
        k_ = FACTORS.index(f_)
        for i in cols:
            if u[i]:
                continue
            for key in ('EVFP', 'EVFB', 'EVOS'):
                E[key][cap, i] += E[key][k_, i]
                E[key][k_, i] = 0.0


def import_seed_swaps(b, dom_rows, ratio):
    """A13, the other side (fix round, S15 smoke map): seed imports in every commodity a region buys only from
    domestic producers. After fix-round A8 crude goes only to refining and the listed direct users, so the B06
    travel no longer gives every region a little imported crude, and 27 crude exporters buy none (GTAP 10 has no
    one-sided pair; the Julia levels model takes log of every Armington share).

    b: bilateral routes (comm, src, dst, VXSB, VFOB, VCIF, VMSB) after the re-balancing; dom_rows: domestic
    purchases by (region, comm) over all columns (io_s13 dom rows). For each pair (r, c) with dom_rows > 0 and no
    VMSB, a = ratio * dom_rows[r, c] is swapped with one partner s: two new routes c s->r and c r->s, each with
    VXSB = VFOB = VCIF = VMSB = a (no export tax, margin or tariff on them), and in both regions the buyers
    switch a of their domestic purchases of c to imports, pro rata (assemble_region, `switch`). So every
    output, column, factor, tax, C, G, I, X - M and GDP stays as it was in both regions. The partner is the
    largest exporter of c (world VXSB) that is not itself domestic-only in c, has neither route yet, and whose
    switches stay within SWAP_PARTNER_MAX of its domestic purchases of c. Our choice (size as the A13 seed).
    Returns (b with the new routes, swaps: region, comm, partner, musd, switch dict {(region, comm): musd})."""
    mr = b.groupby(['dst', 'comm'])['VMSB'].sum()
    pairs = [(r, c) for (r, c), v in dom_rows.items() if v > 0 and mr.get((r, c), 0.0) <= 0]
    dom_only = set(pairs)
    routes = set(zip(b['comm'], b['src'], b['dst']))
    wx = b.groupby(['comm', 'src'])['VXSB'].sum()
    switch, rows, new, add = {}, [], [], []
    for r, c in sorted(pairs):
        a = ratio * float(dom_rows[(r, c)])
        cand = wx.loc[c].sort_values(ascending=False) if c in wx.index.get_level_values(0) else pd.Series(dtype=float)
        partner = None
        for s, xv in cand.items():
            if s == r or xv <= 0 or (s, c) in dom_only or (c, s, r) in routes or (c, r, s) in routes:
                continue
            if switch.get((s, c), 0.0) + a > SWAP_PARTNER_MAX * float(dom_rows.get((s, c), 0.0)):
                continue
            partner = s
            break
        merged = False
        if partner is None:
            # final round 2026-10-25 (SAU oil: SAU already sells crude to every exporter of crude): the largest exporter
            # with no route to r, whose route from r exists; a is added to that route's four border values (no tax or
            # margin on the added part), the route from the partner is new as above
            for s, xv in cand.items():
                if s == r or xv <= 0 or (s, c) in dom_only or (c, s, r) in routes or (c, r, s) not in routes:
                    continue
                if switch.get((s, c), 0.0) + a > SWAP_PARTNER_MAX * float(dom_rows.get((s, c), 0.0)):
                    continue
                partner, merged = s, True
                break
        if partner is None:
            rows.append(dict(region=r, comm=c, partner='', musd=0.0, merged=False))
            continue
        for src, dst in ((partner, r), (r, partner)):
            if merged and (src, dst) == (r, partner):
                add.append((c, src, dst, a))
            else:
                new.append(dict(comm=c, src=src, dst=dst, VXSB=a, VFOB=a, VCIF=a, VMSB=a))
            routes.add((c, src, dst))
        switch[(r, c)] = switch.get((r, c), 0.0) + a
        switch[(partner, c)] = switch.get((partner, c), 0.0) + a
        rows.append(dict(region=r, comm=c, partner=partner, musd=a, merged=merged))
    if add:
        b = b.copy()
        for c, src, dst, a in add:
            k = (b['comm'] == c) & (b['src'] == src) & (b['dst'] == dst)
            for h in ('VXSB', 'VFOB', 'VCIF', 'VMSB'):
                b.loc[k, h] = b.loc[k, h] + a
    if new:
        b = pd.concat([b, pd.DataFrame(new)[b.columns]], ignore_index=True).sort_values(ROUTE).reset_index(drop=True)
    return b, pd.DataFrame(rows, columns=['region', 'comm', 'partner', 'musd', 'merged']), switch


def switch_to_imports(dom, imp, i, amount):
    """A13 swap: move `amount` of row i from domestic to imported purchases, pro rata over the domestic cells
    (each column keeps its basic total and, as the cell rate is the same on both, its tax). In place."""
    d = dom[i].copy()
    tot = d.sum()
    if amount <= 0 or tot <= 0:
        return
    mv = d * (amount / tot)
    dom[i] -= mv
    imp[i] += mv


def seed_shares(total, weight, first, cap):
    """A13: the seed of one row split over its buyers. first: each buyer's share ratio * imports (used as it is when no
    buyer is over its cap, so the common case is unchanged); cap: the most each buyer may give up. Where a buyer is over
    its cap it gives its cap, and the rest of total goes to the other buyers pro rata to weight (their imports), again
    up to their caps. Returns the shares (summing to total) or None when the caps together are below total."""
    first, cap, weight = np.asarray(first, float), np.asarray(cap, float), np.asarray(weight, float)
    if (first <= cap).all():
        return first
    if cap.sum() < total:
        return None
    s = np.zeros(len(first))
    free = np.ones(len(first), bool)
    while True:
        rest = total - s[~free].sum()
        trial = rest * weight[free] / weight[free].sum()
        over = trial > cap[free]
        if not over.any():
            s[free] = trial
            return s
        idx = np.where(free)[0][over]
        s[idx] = cap[idx]
        free[idx] = False
        if not free.any():
            return s


def cell_rate_matrix(cells, sectors):
    """S13 net product-tax rate of every (commodity, column) cell of one region, n x J (J = sectors + FD), from
    tax_cells_s13 rows (column, commodity, tls_rate, pse_rate; S13 writes every cell whose rate is not 0, so a
    missing cell has rate 0). The rate is the same on domestic and imported purchases (S13 tax_rates)."""
    cols = list(sectors) + list(FD)
    r = np.zeros((len(sectors), len(cols)))
    if cells is None or not len(cells):
        return r
    ci, ri = {c: j for j, c in enumerate(cols)}, {c: i for i, c in enumerate(sectors)}
    for x in cells.itertuples():
        if x.column in ci and x.commodity in ri:
            r[ri[x.commodity], ci[x.column]] = float(x.tls_rate) + float(x.pse_rate)
    return r


def cell_wedges(rate13, sectors):
    """Each cell's S13 rate less its column's reference rate (the median S13 rate on the column's non-energy rows),
    n x J, and the reference rates. With one general rate per column (S13 non_energy_rates off) the wedge is
    non-zero on the energy rows only (fix list A1); with the commodity rates (QA round 2 P1) on every row whose rate
    differs from the median. cell_powers adds one remainder rate per column to the wedges."""
    ne = [i for i, c in enumerate(sectors) if c not in ENERGY_TAX_ROWS]
    rest = np.median(rate13[ne, :], axis=0) if ne else np.zeros(rate13.shape[1])
    return rate13 - rest[None, :], rest


def cell_powers(dom, imp, wedge, tax, cols=None):
    """Cell tax powers n x J: 1 + wedge + one remainder rate per column, set so that the column's tax on its
    basic purchases equals tax (TLS + PSE_input). cols: the columns to set (default all); a column with no basic
    purchases gets power 1 on every cell (S14-Hassemble lists any tax on it). Returns (tau n x J, rest by column)."""
    b = dom + imp
    bsum = b.sum(axis=0)
    rest = np.where(bsum != 0, (tax - (b * wedge).sum(axis=0)) / np.where(bsum != 0, bsum, 1.0), 0.0)
    tau = np.where(bsum[None, :] != 0, 1.0 + wedge + rest[None, :], 1.0)
    return tau, rest


def natres_sectors(targets):
    """The resource sectors of a B16 targets dict, keyed by sector or by (region, sector)."""
    return {k[1] if isinstance(k, tuple) else k for k in targets}


def natres_target(targets, region, sector):
    """The B16 target of one cell: the (region, sector) entry (S12's booking, natres_s12.csv) if there is one, else the
    sector's (config/s12/natres_targets.csv). None if neither."""
    t = targets.get((region, sector))
    return t if t is not None else targets.get(sector)


def natres_final(region, E, cost, sectors, targets, floor, issues):
    """Fix round B16 on the S14 data (GTAP 7 ch.12.A pp.2-3; GTAP 12 ch.17B: the reallocation belongs to the global
    data assembly, after the FIT). E: factor payments {EVFP, EVFB, EVOS: FACTORS x sectors}, changed in place; cost:
    each activity's cost at agents' prices (MAKS: purchases at purchasers' prices plus EVFP); targets: {(region, sector):
    dict(eta, sigma)}, the target S12 booked for the cell (natres_s12.csv eta_target and sigma_va: the config value, or for
    msp under the w13 blend the region's effective eta), or {sector: dict(eta, sigma)} for one target per sector
    (natres_target); floor: the S12 natres_guard theta_VA floor.

    In each targeted activity with value added, the natural-resource share of value added becomes
    sigma / (eta theta_VA + sigma) at the activity's own theta_VA = sum EVFP / cost (guard below floor, as in S12), so
    eta = sigma (1/theta_R - 1/theta_VA) equals the target. The difference with the natural resources the activity
    carries comes out of (or goes back to) labour and capital, every group and capital by the same factor, with EVFP,
    EVFB and EVOS scaled alike (each cell keeps its factor-use and income-tax rates); land is left as it is. The natural
    resources keep their own rates (EVFB/EVFP, EVOS/EVFB of the cell; else of the region's natural resources; else no
    factor-use tax and the region's income-tax rate on capital, as S12 books CIT on natural resources). The column's
    value added, and so its cost and output tax, are unchanged. Returns one row per targeted cell with value added."""
    iN = FACTORS.index('natres')
    lk = [FACTORS.index(f) for f in NATRES_LK]
    iK = FACTORS.index('capital')
    pN = E['EVFP'][iN].sum()
    bN = E['EVFB'][iN].sum()
    if pN > 0 and bN > 0:
        reg_pf, reg_pi, src = bN / pN, E['EVOS'][iN].sum() / bN, 'region natural resources'
    else:
        bK = E['EVFB'][iK].sum()
        reg_pf, reg_pi, src = 1.0, (E['EVOS'][iK].sum() / bK if bK > 0 else 1.0), 'no factor-use tax, region capital income-tax rate'
    rows = []
    nsec = natres_sectors(targets)
    for j, s in enumerate(sectors):
        if s not in nsec:
            continue
        va = float(E['EVFP'][:, j].sum())
        n0 = float(E['EVFP'][iN, j])
        if not va > 0:
            if n0 != 0:
                issues.append(f'{region} {s}: natural resources {n0:.6g} without value added')
            continue
        t = natres_target(targets, region, s)
        if t is None:
            issues.append(f'{region} {s}: no B16 target booked for the cell (natres_s12.csv)')
            continue
        z = natres_target_share(va, float(cost[j]), t['eta'], t['sigma'], floor)
        want = z['share'] * va
        lk0 = float(E['EVFP'][lk, j].sum())
        lk1 = lk0 + n0 - want
        if not (lk0 > 0 and lk1 > 0):
            issues.append(f'{region} {s}: labour and capital {lk0:.6g} cannot give the natural-resource share {z["share"]:.6f} of VA {va:.6g}')
            continue
        f = lk1 / lk0
        for key in ('EVFP', 'EVFB', 'EVOS'):
            E[key][lk, j] *= f
        if n0 > 0 and E['EVFB'][iN, j] > 0:
            pf, pi, from_ = E['EVFB'][iN, j] / n0, E['EVOS'][iN, j] / E['EVFB'][iN, j], 'cell'
        else:
            pf, pi, from_ = reg_pf, reg_pi, src
        E['EVFP'][iN, j] = want
        E['EVFB'][iN, j] = want * pf
        E['EVOS'][iN, j] = want * pf * pi
        rows.append(dict(region=region, sector=s, eta_target=t['eta'], sigma_va=t['sigma'], cost_musd=float(cost[j]), factor_va_musd=va,
                         theta_va=z['theta_va'], theta_va_used=z['theta_va_used'], guard=z['guard'],
                         natres_before_musd=n0, natres_musd=want, moved_musd=want - n0, labour_capital_factor=f,
                         share_before=n0 / va, share_after=z['share'],
                         eta_before=implied_eta(n0, va, float(cost[j]), t['sigma']), eta_after=implied_eta(want, va, float(cost[j]), t['sigma']),
                         natres_rates_from=from_))
    return rows


TAU_FLOOR = 0.01   # at most a 99% purchase subsidy on any cell


def assemble_region(region, g, fac, x_r, vst_r, m_r, sectors, seed_ratio=SEED_RATIO, small_shift=None, cell_rates=None, natres=None, switch=None,
                    cap_floor=False):
    """g: io_s13 rows of the region indexed by row; fac: factors_s13 rows of the region; x_r, vst_r, m_r:
    VXSB summed over destinations, VST, VMSB summed over sources, by commodity (dicts); seed_ratio: the A13
    seed (0 turns it off); small_shift: the B14 fall in sales abroad and margin supply by commodity (dict);
    cell_rates: the S13 cell rates n x J (cell_rate_matrix), or None for one tax power per column;
    natres: dict(targets, floor) for the B16 step on the S14 data (natres_final), or None to keep factors_s13's split;
    switch: the A13 swap {comm: USD million} moved from domestic to imported purchases (import_seed_swaps);
    cap_floor: beta v4 capital_floor (A13 seeds at least SEED_MIN, then capital_floor after B16).
    Returns (tables dict, moves list, issues list). tables['tau'] is the n x J cell power written;
    tables['seed_cols'] the columns whose remainder rate the A13 seed re-set; tables['natres'] the B16 rows."""
    n = len(sectors)
    cols = list(sectors) + list(FD)
    dom = g.loc[[f'dom_{c}' for c in sectors], cols].to_numpy(float).copy()
    imp = g.loc[[f'imp_{c}' for c in sectors], cols].to_numpy(float).copy()
    tls = g.loc['TLS', cols].to_numpy(float).copy()
    pse = g.loc['PSE_input', cols].to_numpy(float).copy()
    ptax0 = g.loc['PTAX', sectors].to_numpy(float).copy()
    out0 = g.loc['OUT', sectors].to_numpy(float).copy()
    moves, issues = [], []
    for c, a in (switch or {}).items():
        switch_to_imports(dom, imp, sectors.index(c), a)
    # 3. net product-tax power of every cell: the S13 cell rates (fix list A1), with the column's remainder rate
    # set on the io_s13 rows, so the column tax is TLS + PSE_input (with no cell rates: one power per column)
    basic = dom.sum(axis=0) + imp.sum(axis=0)
    tax = tls + pse
    wedge = cell_wedges(cell_rates, sectors)[0] if cell_rates is not None else np.zeros(dom.shape)
    tau, _ = cell_powers(dom, imp, wedge, tax)
    for j in np.where((basic == 0) & (tax != 0))[0]:
        issues.append(f'{region} {cols[j]}: product tax {tax[j]:.6g} on zero basic purchases')
    # 2. imported purchases add up to VMSB (residual to the largest activity cell, else the largest cell)
    for i, c in enumerate(sectors):
        target = float(m_r.get(c, 0.0))
        resid = target - imp[i].sum()
        if resid == 0:
            continue
        if imp[i].sum() == 0:
            issues.append(f'{region} imp_{c}: VMSB {target:.6g} with no buyer')
            continue
        j = int(np.argmax(imp[i, :n])) if imp[i, :n].max() > 0 else int(np.argmax(imp[i]))
        if imp[i, j] + resid >= 0:
            moves.append(dict(kind='imports', key=f'{region} imp_{c} {cols[j]}', before=imp[i, j], after=imp[i, j] + resid))
            imp[i, j] += resid
        else:
            # B14 can take a row's imports to (nearly) zero: scale the row, so no cell turns negative
            f_ = max(target, 0.0) / imp[i].sum()
            for jj in np.where(imp[i] != 0)[0]:
                moves.append(dict(kind='imports', key=f'{region} imp_{c} {cols[jj]}', before=imp[i, jj], after=imp[i, jj] * f_))
            imp[i] *= f_
    # 5. factors as S13 wrote them
    f = fac.set_index(['factor', 'sector'])[['evfp', 'evfb', 'evos']]
    evfp_io = np.array([[g.loc[f'EVFP_{e}', a] for a in sectors] for e in FACTORS], float)
    E = {k: np.zeros((len(FACTORS), n)) for k in ('EVFP', 'EVFB', 'EVOS')}
    for (e, a), x in f.iterrows():
        k, j = FACTORS.index(e), sectors.index(a)
        E['EVFP'][k, j], E['EVFB'][k, j], E['EVOS'][k, j] = x['evfp'], x['evfb'], x['evos']
    for k, j in zip(*np.where(np.abs(E['EVFP'] - evfp_io) > 1e-9 * np.maximum(1.0, np.abs(evfp_io)))):
        issues.append(f'{region} {FACTORS[k]} {sectors[j]}: factors_s13 EVFP {E["EVFP"][k, j]:.6g} vs io_s13 {evfp_io[k, j]:.6g}')
    x = np.array([float(x_r.get(c, 0.0)) for c in sectors])
    vs = np.array([float(vst_r.get(c, 0.0)) for c in sectors])
    seeds, ledger, fac_delta = [], [], []

    def factor_moves(E_before, rule):
        return [(region, FACTORS[k], sectors[j], E['EVFP'][k, j] - E_before['EVFP'][k, j], E['EVFB'][k, j] - E_before['EVFB'][k, j],
                 E['EVOS'][k, j] - E_before['EVOS'][k, j], rule)
                for k, j in zip(*np.where((E['EVFP'] != E_before['EVFP']) | (E['EVFB'] != E_before['EVFB']) | (E['EVOS'] != E_before['EVOS'])))]
    if small_shift:
        # B14: the output lost with the trade cells set to zero leaves the S13 output. The activity's factor
        # payments fall by the same value, pro rata over its factors (EVFP, EVFB and EVOS alike, so its factor-tax
        # rates stay), so zero profit holds without a new output tax; where its EVFP is too small, the output tax takes it.
        d = np.array([float(small_shift.get(c, 0.0)) for c in sectors])
        E_b = {k_: v_.copy() for k_, v_ in E.items()}
        for j in np.where(d != 0)[0]:
            va = E['EVFP'][:, j].sum()
            if va > 2 * d[j]:
                for key in ('EVFP', 'EVFB', 'EVOS'):
                    E[key][:, j] *= 1.0 - d[j] / va
                ledger.append(dict(region=region, item=f'B14 output and factor payments of {sectors[j]} (sales abroad or margin supply below USD 1)',
                                   before=float(out0[j]), after=float(out0[j] - d[j]), rule=RULE_SMALL))
            else:
                ledger.append(dict(region=region, item=f'B14 output and output tax of {sectors[j]} (sales abroad or margin supply below USD 1)',
                                   before=float(out0[j]), after=float(out0[j] - d[j]), rule=RULE_SMALL))
                ptax0[j] -= d[j]
            out0[j] -= d[j]
        fac_delta += factor_moves(E_b, RULE_SMALL)
    # A13: seed domestic supply in the one-sided pairs (before the output re-balance; ledgered, not rounding)
    E0 = {k_: v_.copy() for k_, v_ in E.items()}
    seed_cols = []
    if seed_ratio:
        out_pre = dom.sum(axis=1) + x + vs
        # the product-tax value each column carries into the seed (its cells at their powers), moved with the carve
        T = (dom * (tau - 1.0)).sum(axis=0) + (imp * (tau - 1.0)).sum(axis=0)
        d0, m0 = dom.copy(), imp.copy()
        used = {f_: E['EVFP'][FACTORS.index(f_)] > 0 for f_ in ('land', 'natres')}
        seeds, ptax_delta = seed_one_sided(region, dom, imp, T, np.zeros_like(T), E, out_pre.copy(), ptax0, sectors, seed_ratio, issues,
                                           seed_min=SEED_MIN if cap_floor else 0.0)
        if seeds:
            seeded = {s_['comm'] for s_ in seeds}
            fac_delta += factor_moves(E0, RULE_SEED)
            E0 = {k_: v_.copy() for k_, v_ in E.items()}
            seed_fixed_factors(E, used, [sectors.index(c_) for c_ in seeded])
            fac_delta += factor_moves(E0, RULE_SEED_FACTOR)
            E0 = {k_: v_.copy() for k_, v_ in E.items()}
            # every column the seed moved keeps its cell rates over one remainder rate and its tax value T: the
            # buyers keep their tax and purchaser totals, the new column has the tax it took over
            moved_j = np.where(((dom != d0) | (imp != m0)).any(axis=0))[0]
            tau_m, _ = cell_powers(dom, imp, wedge, T)
            tau[:, moved_j] = tau_m[:, moved_j]
            seed_cols = [cols[j] for j in moved_j]
            out_post = dom.sum(axis=1) + x + vs
            for j in np.where(out_post != out_pre)[0]:
                ledger.append(dict(region=region, item=f'A13 output {sectors[j]}', before=out_pre[j], after=out_post[j],
                                   rule=RULE_SEED if sectors[j] in seeded else RULE_CARVE))
            # the output re-balance then compares with the S13 output and output tax as the seed moved them
            out0 = out0 + (out_post - out_pre)
            ptax0 = ptax0 + ptax_delta
    fac_delta += factor_moves(E0, RULE_SEED)
    # 2. output = domestic sales; the output tax closes zero profit
    out = dom.sum(axis=1) + x + vs
    for i in np.where(out != out0)[0]:
        moves.append(dict(kind='output', key=f'{region} {sectors[i]}', before=out0[i], after=out[i]))
    # a purchase subsidy cannot exceed the purchase (17B p.3 signs): the power is floored at TAU_FLOOR, and the
    # output tax below closes zero profit on the difference
    tau = np.maximum(tau, TAU_FLOOR)
    domp, impp = dom * tau, imp * tau
    cost = domp[:, :n].sum(axis=0) + impp[:, :n].sum(axis=0) + E['EVFP'].sum(axis=0)
    ptax = out - cost
    for j in np.where(ptax != ptax0)[0]:
        moves.append(dict(kind='output tax', key=f'{region} {sectors[j]}', before=ptax0[j], after=ptax[j]))
    # B16: the ch.12.A natural-resource share at the S14 theta_VA (column VA and cost unchanged)
    natres_rows = []
    if natres:
        E_n = {k_: v_.copy() for k_, v_ in E.items()}
        natres_rows = natres_final(region, E, cost, sectors, natres['targets'], natres['floor'], issues)
        fac_delta += factor_moves(E_n, RULE_NATRES)
    if cap_floor:
        E_k = {k_: v_.copy() for k_, v_ in E.items()}
        if capital_floor(E):
            fac_delta += factor_moves(E_k, RULE_CAPITAL_MIN)
    # long tables
    firms = []
    for i, c in enumerate(sectors):
        for j, a in enumerate(sectors):
            if dom[i, j] or imp[i, j]:
                firms.append((region, c, a, dom[i, j], domp[i, j], imp[i, j], impp[i, j]))
    final = []
    for i, c in enumerate(sectors):
        row = [region, c]
        for k, ag in enumerate(FD):
            j = n + k
            row += [dom[i, j], domp[i, j], imp[i, j], impp[i, j]]
        if any(row[2:]):
            final.append(tuple(row))
    endw = [(region, e, a, E['EVFP'][k, j], E['EVFB'][k, j], E['EVOS'][k, j])
            for k, e in enumerate(FACTORS) for j, a in enumerate(sectors)
            if E['EVFP'][k, j] or E['EVFB'][k, j] or E['EVOS'][k, j]]
    make = [(region, a, a, out[j] - ptax[j], out[j]) for j, a in enumerate(sectors) if out[j] or ptax[j]]
    return dict(firms=firms, final=final, endw=endw, make=make, tau=tau, seeds=seeds, seed_cols=seed_cols, ledger=ledger, fac_delta=fac_delta,
                natres=natres_rows), moves, issues


def frames(parts):
    """Concatenate the per-region tuples into the long header tables."""
    fd_cols = [h for ag in FD for h in FD_HEADERS[ag]]
    return dict(
        firms=pd.DataFrame([r for p in parts for r in p['firms']], columns=['region', 'comm', 'acts', 'VDFB', 'VDFP', 'VMFB', 'VMFP']),
        final=pd.DataFrame([r for p in parts for r in p['final']], columns=['region', 'comm'] + fd_cols),
        endw=pd.DataFrame([r for p in parts for r in p['endw']], columns=['region', 'endw', 'acts', 'EVFP', 'EVFB', 'EVOS']),
        make=pd.DataFrame([r for p in parts for r in p['make']], columns=['region', 'comm', 'acts', 'MAKS', 'MAKB']),
    )


# ------------------------------------------------------------------ 6. regional accounts
def regional_accounts(t, regions):
    """Regional income, expenditure and SAVE from the header tables. t: dict with firms, final, endw, make,
    bilateral, vst and regional (VDEP, VKB, POP by region). Returns a frame indexed by region."""
    R = pd.Index(regions, name='region')

    def s(df, col, by='region'):
        return df.groupby(by)[col].sum().reindex(R, fill_value=0.0) if len(df) else pd.Series(0.0, index=R)
    fi, fd, en, mk, b, vst = t['firms'], t['final'], t['endw'], t['make'], t['bilateral'], t['vst']
    a = pd.DataFrame(index=R)
    a['C'] = s(fd, 'VDPP') + s(fd, 'VMPP')
    a['G'] = s(fd, 'VDGP') + s(fd, 'VMGP')
    a['I'] = s(fd, 'VDIP') + s(fd, 'VMIP')
    a['I_basic'] = s(fd, 'VDIB') + s(fd, 'VMIB')
    a['X'] = s(b, 'VFOB', 'src') + s(vst, 'VST')
    a['M'] = s(b, 'VCIF', 'dst')
    a['tax_firms'] = s(fi, 'VDFP') - s(fi, 'VDFB') + s(fi, 'VMFP') - s(fi, 'VMFB')
    a['tax_private'] = s(fd, 'VDPP') - s(fd, 'VDPB') + s(fd, 'VMPP') - s(fd, 'VMPB')
    a['tax_government'] = s(fd, 'VDGP') - s(fd, 'VDGB') + s(fd, 'VMGP') - s(fd, 'VMGB')
    a['tax_investment'] = s(fd, 'VDIP') - s(fd, 'VDIB') + s(fd, 'VMIP') - s(fd, 'VMIB')
    a['tax_output'] = s(mk, 'MAKB') - s(mk, 'MAKS')
    a['tax_factor_use'] = s(en, 'EVFP') - s(en, 'EVFB')
    a['tax_income'] = s(en, 'EVFB') - s(en, 'EVOS')
    a['tax_export'] = s(b, 'VFOB', 'src') - s(b, 'VXSB', 'src')
    a['tax_import'] = s(b, 'VMSB', 'dst') - s(b, 'VCIF', 'dst')
    indirect = a[['tax_firms', 'tax_private', 'tax_government', 'tax_investment', 'tax_output', 'tax_factor_use', 'tax_export', 'tax_import']].sum(axis=1)
    a['EVFP'] = s(en, 'EVFP')
    a['EVFB'] = s(en, 'EVFB')
    reg = t['regional'].set_index('region').reindex(R)
    for k in ('VDEP', 'VKB', 'POP'):
        a[k] = reg[k].to_numpy(float)
    a['GDP_expenditure'] = a['C'] + a['G'] + a['I'] + a['X'] - a['M']
    a['GDP_income'] = a['EVFP'] + indirect - a['tax_factor_use']   # EVFP already holds the factor-use tax
    a['Y'] = a['EVFB'] - a['VDEP'] + indirect
    a['SAVE'] = a['Y'] - a['C'] - a['G']
    a['capital_income'] = en[en['endw'] == 'capital'].groupby('region')['EVOS'].sum().reindex(R, fill_value=0.0) if len(en) else 0.0
    a['saving_share'] = a['SAVE'] / a['Y'].where(a['Y'] != 0)
    a['investment_share'] = a['SAVE'] / a['SAVE'].sum()          # the model's σ_qinv (solve_model.jl), bound [-1, 1]
    return a


def si_gate(acc, bop):
    """Pre-solve S-I gate (PLAN §3(h)3, E12, E28) per region, with the cause of any SAVE <= 0.
    bop: S02 memo, net primary and net secondary income by region (blank where the memo has none)."""
    g = acc[['SAVE', 'Y', 'saving_share', 'I', 'VDEP', 'VKB', 'capital_income', 'X', 'M']].copy()
    g['net_investment'] = g['I'] - g['VDEP']
    g['trade_balance'] = g['X'] - g['M']
    g = g.join(bop, how='left')
    g['save_bop_eq72'] = g['SAVE'] + g['net_primary_income_musd'].fillna(0.0) + g['net_secondary_income_musd'].fillna(0.0)
    g['vkb_positive'] = g['VKB'] > 0
    g['investment_positive'] = g['I'] > 0
    g['income_positive'] = g['Y'] > 0
    g['vdep_below_capital_income'] = g['VDEP'] < g['capital_income']
    g['save_positive'] = g['SAVE'] > 0
    neg = ~g['save_positive']
    # GTAP 12 ch.7 eq. 7.1: SAVE - (I - VDEP) = X - M. This is an identity, so it labels SAVE <= 0 rather than
    # explaining it: a trade deficit at least as large as net investment, or depreciation above investment (E28).
    # The external income of eq. 7.2 (S02 memo) and the trade balance against S02 are reported beside it.
    g['save_cause'] = np.where(~neg, '', np.where(g['net_investment'] < 0, 'depreciation_above_investment',
                                                  'trade_deficit_at_least_net_investment'))
    g['save_cause_detail'] = [
        '' if not c else
        (f'X - M {tb / 1000:.3f} bn against I - VDEP {ni / 1000:.3f} bn (eq. 7.1). '
         + (f'S02 BoP memo: net primary income {p / 1000:.3f} bn, net secondary income {q / 1000:.3f} bn; SAVE with them (eq. 7.2) {sb / 1000:.3f} bn.'
            if np.isfinite(p) or np.isfinite(q) else 'No BoP memo row in S02.'))
        for c, tb, ni, p, q, sb in zip(g['save_cause'], g['trade_balance'], g['net_investment'],
                                       g['net_primary_income_musd'].fillna(np.nan), g['net_secondary_income_musd'].fillna(np.nan), g['save_bop_eq72'])]
    g['saving_share_in_bounds'] = g['saving_share'].between(-1.0, 1.0)
    g['vdep_below_investment'] = g['VDEP'] < g['I']
    return g
