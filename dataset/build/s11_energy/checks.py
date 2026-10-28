"""S11 check helpers and report tables.

Each function takes the arrays and frames the stage built and returns a count, a dict or a
frame. The stage turns these into hard or report checks; the tests mutate the inputs and
expect the count to move.
"""
import os
import re

import numpy as np
import openpyxl
import pandas as pd

from .sources import COMMODITIES, DAYS, GJ_PER_TOE, COAL_TJ_PER_KT_DEFAULT, MTOE_PER_BCM, MTOE_PER_TWH, TOE_PER_BBL_CRUDE

TARGETS = ('coa', 'oil', 'gas', 'pet')
B06_ROWS = ('dom_B06', 'imp_B06')
SPLIT_ROWS = ('dom_oil', 'dom_gas', 'imp_oil', 'imp_gas')
DOMESTIC_USERS_EXCLUDE = ('X', 'OUT', 'stock_gap', 'grev_gap')
NINETY = 0.9
SHORT_TON_T = 0.90718474
BCM_PER_BCF = 0.028316846592
GAL_PER_BBL = 42.0


# ------------------------------------------------------------------ B06 split
def _block(io, r):
    return io[io['region'] == r].set_index('row').drop(columns='region').astype(float)


def b06_identity(io10, io11):
    """oil + gas rows equal the B06 row cell by cell; oil + gas columns equal the B06 column;
    the 2x2 own-use block sums to the B06 own-use cells. Gap relative to max(1, |B06 cell|)."""
    worst, neg, detail = 0.0, 0, []
    for r in io10['region'].drop_duplicates():
        a, b = _block(io10, r), _block(io11, r)
        cols = [c for c in a.columns if c != 'B06']
        gaps = []
        for k in ('dom', 'imp'):
            s = b.loc[f'{k}_oil', cols] + b.loc[f'{k}_gas', cols]
            gaps.append(((s - a.loc[f'{k}_B06', cols]).abs() / np.maximum(1.0, a.loc[f'{k}_B06', cols].abs())).max())
            own = b.loc[[f'{k}_oil', f'{k}_gas'], ['oil', 'gas']].to_numpy().sum()
            gaps.append(abs(own - a.loc[f'{k}_B06', 'B06']) / max(1.0, abs(a.loc[f'{k}_B06', 'B06'])))
        rows = [x for x in a.index if x not in B06_ROWS]
        s = b.loc[rows, 'oil'] + b.loc[rows, 'gas']
        gaps.append(((s - a.loc[rows, 'B06']).abs() / np.maximum(1.0, a.loc[rows, 'B06'].abs())).max())
        g = float(max(gaps))
        if g > worst:
            worst = g
        if g >= 1e-6:
            detail.append(f'{r} {g:.1e}')
        n = 0
        for k in ('dom', 'imp'):           # a split cell is negative only where the B06 cell is not
            ok = a.loc[f'{k}_B06'] >= 0
            n += int(((b.loc[[f'{k}_oil', f'{k}_gas'], [c for c in ok.index[ok] if c in b.columns]] < -1e-9).to_numpy()).sum())
        ok = a['B06'] >= 0
        rows_ok = [x for x in ok.index[ok] if x not in B06_ROWS]
        n += int((b.loc[rows_ok, ['oil', 'gas']] < -1e-9).to_numpy().sum())
        if n > 0:
            neg += n
            detail.append(f'{r} {n} negative')
    return dict(max_gap=worst, negative=neg, detail='; '.join(detail[:20]))


def io_unchanged_outside_b06(io10, io11):
    """Count io_s11 cells outside the B06 rows and column that differ from io_s10."""
    cols = [c for c in io10.columns if c not in ('region', 'row', 'B06')]
    a = io10[~io10['row'].isin(B06_ROWS)].set_index(['region', 'row'])[cols]
    b = io11[~io11['row'].isin(SPLIT_ROWS)].set_index(['region', 'row'])
    if set(a.index) != set(b.index) or any(c not in b.columns for c in cols):
        return max(len(a), 1)
    b = b.loc[a.index, cols]
    return int((a.to_numpy(float) != b.to_numpy(float)).sum())


def crude_users(io11, oil_users, R, tol=1e-9):
    """Fix-round A8: oil-row cells of io_s11 outside refining (pet), exports (X), OUT and the region's listed direct
    users (oil_users[r]: {io_s10 column: share}; the B06 column is the oil column in io_s11). Returns (count, detail)."""
    bad, det = 0, []
    for r in R:
        b = io11[io11['row'].isin(['dom_oil', 'imp_oil']) & (io11['region'] == r)].set_index('row')
        allowed = {'region', 'pet', 'X', 'OUT'} | {('oil' if u == 'B06' else u) for u in oil_users.get(r, {})}
        cols = [c for c in b.columns if c not in allowed]
        x = b[cols].astype(float).abs() > tol
        n = int(x.to_numpy().sum())
        if n:
            bad += n
            det.append(f'{r} ' + ','.join(sorted({c for c in cols if x[c].any()}))[:80])
    return bad, '; '.join(det[:20])


def crude_cell_share(io10, io11, cell_share, R, tol=1e-9):
    """Round 3 (final QA item 2): for each region's listed crude user u with a value share f (cell_share[r][u] =
    {'dom': f, 'imp': f}), the io_s11 oil cell of that column is at most f x the io_s10 B06 cell, on the domestic and the
    imported row. The B06 column is the oil column in io_s11. Returns (count, detail)."""
    bad, det = 0, []
    for r in R:
        a = io10[io10['region'] == r].set_index('row')
        b = io11[io11['region'] == r].set_index('row')
        for u, f in cell_share.get(r, {}).items():
            uc = 'oil' if u == 'B06' else u
            for kind in ('dom', 'imp'):
                if uc not in b.columns or f'{kind}_B06' not in a.index:
                    continue
                cell = max(float(a.loc[f'{kind}_B06', u]), 0.0)
                oil = float(b.loc[f'{kind}_oil', uc])
                if oil > f[kind] * cell + tol * max(1.0, cell):
                    bad += 1
                    det.append(f'{r} {kind} {u} oil {oil:.4g} > {f[kind]:.4f} x {cell:.4g}')
    return bad, '; '.join(det[:20])


# ------------------------------------------------------------------ 90 percent rule
def _uses(blk, row):
    users = [c for c in blk.columns if c not in DOMESTIC_USERS_EXCLUDE]
    return blk.loc[row, users].clip(lower=0)


def ninety_rule(V, R, crude_in, gas_pet, ninety_pct, ely_in=None, own_in=None, ely_subsidy=None):
    """GTAP 12 ch.12 §12.4.3 pp.28-29 on the energy inputs S11 measures by volume. For each region and
    energy industry k in coa/oil/gas/pet (and ely, beta v4 P1): energy-input cost must be at most 90 percent of k's revenue.
    Measured inputs are those of refining: crude intake (crude_in[r], million bbl) at the crude price,
    the domestic part (by the region's crude supply shares) at the domestic basic price and the
    imported part at the import basic price; and refinery gas (gas_pet[r] = {'dom', 'imp'} values).
    ely_in (beta v4 P1, choice ninety_pct_ely): {region: {fuel: (domestic value, imported value)}}, the electricity part of
    the UNSD 088 burn at S11 prices (power.ninety_ely_inputs); ely joins the industries and its fuels are its inputs,
    the domestic part moving with the fuel's domestic price, the imported part fixed. own_in (beta v4 P1 and P15, choice
    ninety_pct_own_use): {region: {industry: UNSD own use + losses share of production}}, the industry's own good at its
    own domestic price (the diagonal, own_index). Other energy inputs are left out until a use-by-industry balance exists
    (agent_use_volumes). ely_subsidy (beta v4 P4): {region: USD m} of ely production subsidy, fixed revenue of the ely
    industry. Revenue: domestic sales (less the NGPL add-on and any pass-through value) move with the domestic
    price; exports and NGPL are fixed. Only domestic prices of domestic products move; export and import prices are fixed."""
    Vi = V.set_index(['region', 'commodity'])
    inds = TARGETS + (('ely',) if ely_in is not None else ())
    rows, pi_all = [], {}
    nk = len(inds)
    io_, ig, ip = inds.index('oil'), inds.index('gas'), inds.index('pet')

    def col(r, k, name):
        return float(Vi.loc[(r, k), name]) if name in Vi.columns else 0.0
    for r in R:
        rev_dom = np.array([col(r, k, 'domestic_sales_value') - col(r, k, 'ngpl_value') - col(r, k, 'pass_through_value') for k in inds])
        rev_fix = np.array([col(r, k, 'export_value') + col(r, k, 'ngpl_value')
                            + (float((ely_subsidy or {}).get(r, 0.0)) if k == 'ely' else 0.0) for k in inds])
        dom_in = np.zeros((nk, nk))
        fixed = np.zeros(nk)
        o = Vi.loc[(r, 'oil')]
        dvol, mvol = max(float(o['domestic_sales']), 0.0), max(float(o['imports']), 0.0)
        sh = dvol / (dvol + mvol) if dvol + mvol > 0 else 1.0
        crude = max(float(crude_in.get(r, 0.0)), 0.0)
        pm = float(o['import_basic_price'])
        dom_in[io_, ip] = crude * sh * float(o['domestic_price'])
        fixed[ip] = crude * (1 - sh) * (pm if np.isfinite(pm) else float(o['domestic_price']))
        dom_in[ig, ip] = gas_pet[r]['dom']
        fixed[ip] += gas_pet[r]['imp']
        if ely_in is not None:
            ie = inds.index('ely')
            for f, (dv, mv) in ely_in.get(r, {}).items():
                dom_in[inds.index(f), ie] += max(dv, 0.0)
                fixed[ie] += max(mv, 0.0)
        own_v = np.zeros(nk)
        for k, share in (own_in or {}).get(r, {}).items():
            if k in inds and np.isfinite(share) and share > 0:
                x = Vi.loc[(r, k)]
                p = float(x['domestic_price'])
                own_v[inds.index(k)] = share * max(float(x['production']), 0.0) * (p if np.isfinite(p) else 0.0)
                dom_in[inds.index(k), inds.index(k)] += own_v[inds.index(k)]
        pi, it = ninety_pct(rev_dom, rev_fix, fixed, dom_in, np.arange(nk))
        cost0 = fixed + dom_in.sum(0)
        cost1 = fixed + dom_in.T @ np.where(np.isfinite(pi), pi, 1.0)
        for k, ind in enumerate(inds):
            rev0 = rev_fix[k] + rev_dom[k]
            rev1 = rev_fix[k] + (pi[k] if np.isfinite(pi[k]) else 1.0) * rev_dom[k]
            status = ('no_domestic_sales_cannot_adjust' if rev_dom[k] <= 0 and rev0 > 0 and cost0[k] > NINETY * rev0 else
                      'no_revenue' if rev0 <= 0 else 'raised' if pi[k] > 1 + 1e-12 else 'lowered' if pi[k] < 1 - 1e-12 else 'holds')
            rows.append(dict(region=r, industry=ind, status=status, pi=float(pi[k]), iterations=it,
                             domestic_price=float(Vi.loc[(r, ind), 'domestic_price']),
                             revenue_domestic=rev_dom[k], revenue_fixed=rev_fix[k], energy_cost_before=cost0[k],
                             revenue_before=rev0, ratio_before=cost0[k] / rev0 if rev0 > 0 else np.nan,
                             energy_cost_after=cost1[k], revenue_after=rev1,
                             ratio_after=cost1[k] / rev1 if rev1 > 0 else np.nan,
                             own_use_value_before=own_v[k],
                             crude_intake_mbbl=crude if ind == 'pet' else np.nan,
                             crude_domestic_share=sh if ind == 'pet' else np.nan))
            pi_all[(r, ind)] = float(pi[k])
    return rows, pi_all


def ely_ninety_floor(energy_cost, pass_through, value=None, headroom=None):
    """Beta v4 P1 revised (ely_output_value floor_ninety): the smallest ely output the 90 percent rule allows, its energy
    inputs and own use at S11 prices over 0.9, plus the gas and heat it resells at cost (outside the rule). With headroom
    (rescan N2, s11 ely_floor_headroom) and the S11 value: raised toward the value as far as a fuel share of headroom,
    max(floor, min(value, cost / headroom + pass-through))."""
    e = max(float(energy_cost) if np.isfinite(energy_cost) else 0.0, 0.0)
    pt = max(float(pass_through), 0.0)
    fl = e / NINETY + pt
    if headroom and value is not None and np.isfinite(float(value)):
        fl = max(fl, min(float(value), e / headroom + pt))
    return fl


def ninety_after(NIN):
    """Industries with revenue whose energy cost is above 90 percent of revenue after the rule."""
    d = NIN[(NIN['revenue_after'] > 0) & (NIN['revenue_domestic'] > 0)]
    return int((d['ratio_after'] > NINETY + 1e-9).sum())


def prices_fixed(V, px, pmb, R):
    """Cells where V's export price or import basic price differs from the pre-rule arrays."""
    ix = {r: i for i, r in enumerate(R)}
    bad = 0
    for row in V.itertuples():
        i = ix[row.region]
        a, b = px[row.commodity][i], pmb[row.commodity][i]
        if not np.isclose(row.export_price, a, rtol=0, atol=0, equal_nan=True):
            bad += 1
        if not np.isclose(row.import_basic_price, b, rtol=0, atol=0, equal_nan=True):
            bad += 1
    return bad


# ------------------------------------------------------------------ fix-round B9: export prices against an outside unit value
VPV_WORLD = (0.8, 1.25)        # world S11 export price over the BACI unit value
VPV_EXPORTER = (0.5, 2.0)      # the same ratio for each large exporter
VPV_BIG_MUSD = 5000.0


def vpv_source(V, baci_vpv, t_per_bbl, reviewed=()):
    """S11 crude and product export prices (EI markers, energy_values) against the BACI 2022 unit value of the
    same exporters' HS 270900 / 271000 flows (value / tonnes, converted to USD/bbl with t_per_bbl[c]).
    baci_vpv: BACI rows with exp (region), k, v (thousand USD), q (tonnes). reviewed (beta v4 dry run 3): (region,
    commodity) pairs whose BACI quantity is reviewed as wrong (config/s11/vpv_reviewed.csv); reported, not failed.
    Returns dict(ok, summary, detail)."""
    from .sources import VPV_COMMODITY
    ok, summ, det = True, [], []
    for k, c in VPV_COMMODITY.items():
        b = baci_vpv[(baci_vpv['k'] == k) & baci_vpv['q'].notna() & (baci_vpv['q'] > 0)]
        g = b.groupby('exp')[['v', 'q']].sum()
        uv = g['v'] * 1000.0 / g['q'] * t_per_bbl[c]
        v = V[V['commodity'] == c].set_index('region')
        if g['q'].sum() <= 0 or v['exports'].sum() <= 0:
            ok = False
            summ.append(f'{c} no data')
            continue
        world = (v['export_value'].sum() / v['exports'].sum()) / (g['v'].sum() * 1000.0 / g['q'].sum() * t_per_bbl[c])
        big = v[v['export_value'] > VPV_BIG_MUSD]
        rat = (big['export_price'] / uv.reindex(big.index)).dropna()
        out = rat[(rat < VPV_EXPORTER[0]) | (rat > VPV_EXPORTER[1])]
        rev = out[[(r, c) in set(reviewed) for r in out.index]]
        out = out.drop(rev.index)
        ok &= bool(VPV_WORLD[0] <= world <= VPV_WORLD[1] and out.empty)
        summ.append(f'{c} world {world:.3f}')
        det.append(f'{c}: {len(rat)} exporters above {VPV_BIG_MUSD / 1e3:g} bn, ratio {rat.min():.2f}-{rat.max():.2f}'
                   + ('; outside: ' +', '.join(f'{r} {x:.2f}' for r, x in out.items()) if not out.empty else '')
                   + ('; reviewed (BACI quantity): ' + ', '.join(f'{r} {x:.2f}' for r, x in rev.items()) if not rev.empty else ''))
    return dict(ok=ok, summary='; '.join(summ), detail='; '.join(det))


# ------------------------------------------------------------------ identities
def identities(R, comms, exi, px, new_fob, new_cif, new_vmsb, mrate, tmd, new_tw, V):
    vpv = cif = 0.0
    neg, neg_detail = 0, []
    for c in comms:
        scale = max(new_fob[c].max(), 1e-300)
        p_ = px[c] if np.ndim(px[c]) == 2 else px[c][:, None]       # route prices (Fable QA D-02) or one price per exporter
        vpv = max(vpv, float(np.abs(exi[c] * p_ - new_fob[c]).max() / scale))
        sc = np.maximum(new_cif[c], 1.0)
        cif = max(cif, float((np.abs(new_cif[c] - new_fob[c] * (1 + mrate[c])) / sc).max()),
                  float((np.abs(new_tw[c].sum(0) - (new_cif[c] - new_fob[c])) / sc).max()),
                  float((np.abs(new_vmsb[c] - new_cif[c] * (1 + tmd[c])) / np.maximum(new_vmsb[c], 1.0)).max()))
        for name, A in (('volume', exi[c]), ('fob', new_fob[c]), ('cif', new_cif[c]), ('vmsb', new_vmsb[c]),
                        ('vtwr', new_tw[c]), ('margin_rate', mrate[c]), ('tm', tmd[c]), ('export_price', px[c])):
            n = int((~np.isfinite(A)).sum() + (np.nan_to_num(A, nan=0.0) < 0).sum())
            if n:
                neg += n
                neg_detail.append(f'{c} {name} {n}')
    xv = (V['exports'] * V['export_price'] - V['export_value']).abs() / np.maximum(V['export_value'].abs(), 1.0)
    xtax = V['export_tax'] if 'export_tax' in V else 0.0          # fix list A2: output at basic prices, net of the export tax
    ov = (V['export_value'] - xtax + V['domestic_sales_value'] - V['output_value']).abs() / np.maximum(V['output_value'].abs(), 1.0)
    vpv = max(vpv, float(xv.max()), float(ov.max()))
    for k in ('production', 'exports', 'imports', 'export_value', 'domestic_sales_value', 'output_value', 'export_price'):
        a = V[k].to_numpy(float)
        n = int((~np.isfinite(a)).sum() + (np.nan_to_num(a) < 0).sum())
        if n:
            neg += n
            neg_detail.append(f'V {k} {n}')
    dp = V.loc[V['domestic_sales'] > 0, 'domestic_price'].to_numpy(float)
    n = int((~np.isfinite(dp)).sum() + (np.nan_to_num(dp) <= 0).sum())
    if n:
        neg += n
        neg_detail.append(f'V domestic_price {n}')
    return dict(vpv=vpv, cif=cif, neg=neg, neg_detail='; '.join(neg_detail))


def ngl_parity(ngl_raw):
    """Rows where the chosen crude volume includes NGPL: EIA-sourced crude must equal EIA 57 alone."""
    d = ngl_raw[ngl_raw['chosen_crude_source'] == 'eia']
    bad = d[(d['chosen_crude_kbd'] - d['eia_57_crude_kbd']).abs() > 1e-9]
    both = d[(d['eia_58_ngpl_kbd'] > 0) & ((d['chosen_crude_kbd'] - d['eia_57_plus_58_kbd']).abs() < 1e-9)
             & (d['eia_58_ngpl_kbd'] > 1e-9)]
    return int(len(bad) + len(both))


def gas_balance(V, regions):
    """PLAN §3(g): production >= domestic use + exports - imports, i.e. domestic sales >= 0 and
    absorption >= 0, for each named region. '' when every region passes."""
    out = []
    for r in regions:
        g = V[(V['region'] == r) & (V['commodity'] == 'gas')]
        if g.empty:
            out.append(f'{r} missing')
            continue
        g = g.iloc[0]
        if g['production'] + 1e-9 < g['exports'] or g['absorption'] < -1e-9:
            out.append(f'{r} P {g["production"]:.2f} X {g["exports"]:.2f} M {g["imports"]:.2f}')
    return '; '.join(out)


# ------------------------------------------------------------------ Mtoe
def mtoe_factors(R, ei, coal_heat, cmap, vol):
    """Mtoe per natural unit by (commodity, region). Coal: UNSD 2022 production heat value,
    tonne-weighted over the region's members, EI 25 TJ/kt where UNSD has none; oil: EI 0.1364 t/bbl;
    pet: EI product basket; gas: EI 0.8598 Mtoe/bcm; ely: EI 0.086 Mtoe/TWh."""
    heat, kt = coal_heat
    tj = {}
    for _, row in cmap.iterrows():
        r = row['region']
        if not isinstance(r, str) or row['code'] not in heat:
            continue
        t = tj.setdefault(r, [0.0, 0.0])
        t[0] += heat[row['code']] * kt[row['code']]
        t[1] += kt[row['code']]
    out = {}
    for r in R:
        h = tj[r][0] / tj[r][1] if r in tj and tj[r][1] > 0 else COAL_TJ_PER_KT_DEFAULT
        out[('coa', r)] = h / GJ_PER_TOE          # TJ/kt = GJ/t; Mtoe per Mt
        out[('oil', r)] = TOE_PER_BBL_CRUDE       # million bbl -> Mtoe
        out[('pet', r)] = ei['toe_per_bbl_products']
        out[('gas', r)] = MTOE_PER_BCM
        out[('ely', r)] = MTOE_PER_TWH
    return out


# ------------------------------------------------------------------ report tables
def subsidies(R, iea_path, booked=None):
    """IEA 2022 consumption subsidies by IEA country and product (real 2024 USD million). booked: {(country,
    product): USD million at 2022 prices} for the countries whose region has a row in fuel_subsidies_s11.csv, which S13
    books (fix-round B15 and its 2026-10-24 extension); None = report only (choice fuel_subsidies off)."""
    wb = openpyxl.load_workbook(iea_path, read_only=True, data_only=True)
    ws = wb['Subsidies by country']
    col, recs = None, []
    for r in ws.iter_rows(values_only=True):
        if col is None:
            if r and r[0] == 'Country':
                col = list(r).index(2022)
            continue
        if r and isinstance(r[0], str) and isinstance(r[1], str) and r[1] != 'Total':
            v = r[col]
            recs.append(dict(country=r[0], product=r[1], subsidy_musd_real2024=float(v) if isinstance(v, (int, float)) else np.nan))
    d = pd.DataFrame(recs)
    if booked is None:
        d['basis'] = 'IEA fossil fuel subsidies 2022, real 2024 USD million; not booked (fuel_subsidies off)'
        d['booked_musd'] = 0.0
    else:
        d['booked_musd'] = [float(booked.get((a, b), 0.0)) for a, b in zip(d['country'], d['product'])]
        d['basis'] = np.where(d['booked_musd'] > 0,
                              'IEA fossil fuel subsidies 2022, real 2024 USD million; booked at 2022 prices (US GDP deflator) by S13 as a '
                              'negative purchase tax (fuel_subsidies_s11.csv; fix-round B15)',
                              'IEA fossil fuel subsidies 2022, real 2024 USD million; not booked (no row in fuel_subsidies_s11.csv: no domestic use, '
                              'or the gap-rows-only rule)')
    return d


def fuel_subsidy_check(rows, rule, R, price=None, tol=1e-9, mode='price_gap', consumer_floor=0.01):
    """Fix-round B15 (S11-Hsubsidy). rows: fuel_subsidy_rows; rule: {c: domestic price rule array} after
    apply_subsidy_prices (before the 90 percent rule); price: {c: domestic price array} at the same point (None: not
    compared). Every row has subsidy = (market price - consumer price) x domestic use = subsidy per unit x domestic use,
    and market price - consumer price = the subsidy per unit. An IEA-gap row (source_rule iea_price_gap) has consumer
    price = reference - IEA gap and market price = reference, which is its domestic basic price unless the lignite rule
    blended it. A row booked under the extension (David 2026-10-24) has its rate at the IEA value per unit unless capped,
    its subsidy at most the IEA value, and its domestic basic price at the market price.
    mode 'price_gap' (fix round wA): the cap is the reference (rate_cap 'reference', only where the IEA rate is above it) or
    the observed price gap (rate_cap 'observed_price_gap', only on an observed price, where reference - consumer price is
    below the IEA rate); an observed row keeps its S11 price as the consumer price, an unobserved row has market price =
    reference. mode 'add_on_top' (the w10 rule): step 2 rescales only where the IEA rate is above the reference and imports
    exceed half of domestic use. Fix round wA2: an electricity row (reference_basis iea_implied_consumer_price_plus_iea_rate)
    has the IEA rate uncapped and market price = reference = consumer price + rate; an unobserved traded-fuel row may cap
    the rate at (1 - consumer_floor) x reference (rate_cap reference_less_consumer_floor). The rows are exactly the (commodity, region) pairs priced by the IEA gap or marked
    +iea_subsidy. Returns (number of failures, detail)."""
    bad = []
    seen = set()
    ix = {r: i for i, r in enumerate(R)}

    def off(a, b):
        return not (np.isfinite(a) and np.isfinite(b)) or abs(a - b) > tol * max(1.0, abs(b))
    for x in rows:
        k = (x['commodity'], x['region'])
        seen.add(k)
        want = (x['market_price'] - x['consumer_price']) * x['domestic_use']
        if off(x['subsidy_musd'], want) or x['subsidy_musd'] < 0:
            bad.append(f'{k[1]} {k[0]} subsidy {x["subsidy_musd"]:.6g} vs (market - consumer) x use {want:.6g}')
        if off(x['subsidy_musd'], x['subsidy_per_unit'] * x['domestic_use']):
            bad.append(f'{k[1]} {k[0]} subsidy is not the rate x domestic use')
        if x['source_rule'] == 'iea_price_gap':
            if off(x['reference_price'] - x['iea_subsidy_per_unit'], x['consumer_price']):
                bad.append(f'{k[1]} {k[0]} consumer price is not reference less the IEA gap')
            if off(x['market_price'], x['reference_price']):
                bad.append(f'{k[1]} {k[0]} market price {x["market_price"]:.6g} is not the reference {x["reference_price"]:.6g}')
            if '+lignite' not in x['domestic_price_rule'] and off(x['domestic_price_before_90pct'], x['reference_price']):
                bad.append(f'{k[1]} {k[0]} domestic basic price {x["domestic_price_before_90pct"]:.6g} is not the reference {x["reference_price"]:.6g}')
        else:
            cap = x.get('rate_cap', 'reference' if x['step2_rescaled'] else 'none')
            if mode == 'add_on_top':
                if x['step2_rescaled']:
                    ok = (off(x['subsidy_per_unit'], x['reference_price']) is False and x['iea_subsidy_per_unit'] > x['reference_price']
                          and x['domestic_use'] < 2.0 * x.get('imports_volume', np.inf))
                    if not ok:
                        bad.append(f'{k[1]} {k[0]} step 2 rescaling without its conditions (rate = reference < IEA rate, imports over half of use)')
                elif off(x['subsidy_per_unit'], x['iea_subsidy_per_unit']):
                    bad.append(f'{k[1]} {k[0]} rate {x["subsidy_per_unit"]:.6g} is not the IEA rate {x["iea_subsidy_per_unit"]:.6g}')
            elif x.get('reference_basis') == 'iea_implied_consumer_price_plus_iea_rate':
                # fix round wA2: electricity, reference = consumer price + IEA rate, the rate uncapped
                if off(x['subsidy_per_unit'], x['iea_subsidy_per_unit']) or cap != 'none':
                    bad.append(f'{k[1]} {k[0]} electricity rate {x["subsidy_per_unit"]:.6g} is not the IEA rate {x["iea_subsidy_per_unit"]:.6g}')
                if off(x['reference_price'], x['consumer_price'] + x['iea_subsidy_per_unit']) or off(x['market_price'], x['reference_price']):
                    bad.append(f'{k[1]} {k[0]} electricity market price is not the IEA-implied reference (consumer price + IEA rate)')
                if x.get('consumer_price_basis') not in ('observed_s11_price', 'end_user_tariff', 'tariff_income_group_average'):
                    bad.append(f'{k[1]} {k[0]} electricity consumer price basis {x.get("consumer_price_basis")!r}')
            elif x.get('reference_basis') == 'regulated_price_plus_iea_rate_at_most_own_trade_price':
                # Fable QA C-02 (regulated_price_fill): the IEA rate uncapped; market = consumer + rate, capped at the own
                # trade price only where the consumer price stays positive (netback_reference)
                if cap == 'export_parity_cap':
                    # beta v4 P6 (gas_export_parity_cap): market at the own trade price, the rate below the IEA rate
                    if off(x['market_price'], x['trade_parity_price']) or not x['subsidy_per_unit'] < x['iea_subsidy_per_unit'] * (1 + tol):
                        bad.append(f'{k[1]} {k[0]} regulated row capped at export parity: market {x["market_price"]:.6g} is not the own trade '
                                   f'price {x["trade_parity_price"]:.6g}, or the rate is above the IEA rate')
                elif off(x['subsidy_per_unit'], x['iea_subsidy_per_unit']):
                    bad.append(f'{k[1]} {k[0]} regulated row: rate {x["subsidy_per_unit"]:.6g} is not the IEA rate {x["iea_subsidy_per_unit"]:.6g}')
                if off(x['market_price'], x['reference_price']) or off(x['consumer_price'], x['market_price'] - x['subsidy_per_unit']):
                    bad.append(f'{k[1]} {k[0]} regulated row: market is not the reference, or consumer is not market - rate')
                if x['consumer_price'] <= 0:
                    bad.append(f'{k[1]} {k[0]} regulated row: consumer price {x["consumer_price"]:.6g} not positive')
                if cap == 'netback_reference' and off(x['market_price'], x['trade_parity_price']):
                    bad.append(f'{k[1]} {k[0]} regulated row capped at a price other than its own trade price')
            elif x.get('reference_basis') == 'income_group_tariff_average_at_least_rate_over_0.99':
                # round 3 (final QA item 4): no own tariff; reference = regional price, at least rate / (1 - floor);
                # consumer = reference - rate; the IEA rate (and so the IEA money) uncapped
                if off(x['subsidy_per_unit'], x['iea_subsidy_per_unit']) or cap not in ('none', 'reference_raised_to_rate'):
                    bad.append(f'{k[1]} {k[0]} electricity rate {x["subsidy_per_unit"]:.6g} is not the IEA rate {x["iea_subsidy_per_unit"]:.6g}')
                if off(x['market_price'], x['reference_price']) or off(x['consumer_price'], x['reference_price'] - x['subsidy_per_unit']):
                    bad.append(f'{k[1]} {k[0]} electricity: market price is not the reference, or consumer price is not reference - rate')
                if x['consumer_price'] < consumer_floor * x['reference_price'] * (1 - tol) - tol:
                    bad.append(f'{k[1]} {k[0]} electricity consumer price {x["consumer_price"]:.6g} below {consumer_floor:.0%} of the reference')
                if x.get('consumer_price_basis') != 'reference_less_rate_income_group_tariff':
                    bad.append(f'{k[1]} {k[0]} electricity consumer price basis {x.get("consumer_price_basis")!r}')
            else:
                observed = x.get('consumer_price_basis') in ('observed_s11_price', 'regulated_class_average')
                if cap == 'reference_less_consumer_floor':
                    if observed or off(x['subsidy_per_unit'], (1.0 - consumer_floor) * x['reference_price']) or not (
                            x['iea_subsidy_per_unit'] > (1.0 - consumer_floor) * x['reference_price']):
                        bad.append(f'{k[1]} {k[0]} rate capped at 99% of the reference without its condition')
                elif cap == 'reference':
                    if off(x['subsidy_per_unit'], x['reference_price']) or not x['iea_subsidy_per_unit'] > x['reference_price']:
                        bad.append(f'{k[1]} {k[0]} rate capped at the reference without the IEA rate above it')
                elif cap == 'observed_price_gap':
                    if not observed or off(x['subsidy_per_unit'], x['reference_price'] - x['consumer_price']) or not (
                            x['iea_subsidy_per_unit'] > x['reference_price'] - x['consumer_price']):
                        bad.append(f'{k[1]} {k[0]} rate capped at the observed price gap without an observed price below the IEA rate')
                elif off(x['subsidy_per_unit'], x['iea_subsidy_per_unit']):
                    bad.append(f'{k[1]} {k[0]} rate {x["subsidy_per_unit"]:.6g} is not the IEA rate {x["iea_subsidy_per_unit"]:.6g}')
                if not observed and off(x['market_price'], x['reference_price']):
                    bad.append(f'{k[1]} {k[0]} unobserved price: market price {x["market_price"]:.6g} is not the reference {x["reference_price"]:.6g}')
            if x['subsidy_musd'] > x['iea_subsidy_musd'] * (1 + tol) + tol:
                bad.append(f'{k[1]} {k[0]} subsidy {x["subsidy_musd"]:.6g} above the IEA value {x["iea_subsidy_musd"]:.6g}')
            if off(x['domestic_price_before_90pct'], x['market_price']):
                bad.append(f'{k[1]} {k[0]} domestic basic price {x["domestic_price_before_90pct"]:.6g} is not the market price {x["market_price"]:.6g}')
        if price is not None and k[1] in ix and off(float(price[k[0]][ix[k[1]]]), x['domestic_price_before_90pct']):
            bad.append(f'{k[1]} {k[0]} S11 domestic price {float(price[k[0]][ix[k[1]]]):.6g} is not the row\'s {x["domestic_price_before_90pct"]:.6g}')
    for c, ru in rule.items():
        for i, r in enumerate(R):
            s = str(ru[i])
            if (s.split('+')[0] == 'iea_price_gap' or '+iea_subsidy' in s) and (c, r) not in seen:
                bad.append(f'{r} {c} priced by the IEA gap or marked +iea_subsidy without a subsidy row')
    return len(bad), '; '.join(bad[:20])


def fuel_subsidy_reference_check(rows, tol=1e-9):
    """Fix round wA (S11-Hsubref; independent QA HIGH-1): a consumption subsidy is a price gap below the reference
    (Chepeliev et al. 2018 §2.1; step 2 caps the rate at the reference). On every booked row the market price and the
    subsidy per unit are at most the reference price and the consumer price is not negative. Returns (failures, detail)."""
    bad = []
    for x in rows:
        ref = float(x['reference_price'])
        lim = ref * (1 + tol) + tol
        k = f'{x["region"]} {x["commodity"]}'
        if not np.isfinite(ref):
            bad.append(f'{k} no reference price')
            continue
        if x['market_price'] > lim:
            bad.append(f'{k} market price {x["market_price"]:.6g} above the reference {ref:.6g}')
        if x['subsidy_per_unit'] > lim:
            bad.append(f'{k} subsidy per unit {x["subsidy_per_unit"]:.6g} above the reference {ref:.6g}')
        if x['consumer_price'] < -tol * max(1.0, ref):
            bad.append(f'{k} consumer price {x["consumer_price"]:.6g} below zero')
    return len(bad), '; '.join(bad[:20])


def fuel_subsidy_consumer_positive(rows, floor_share=0.01, tol=1e-9):
    """Fix round wA2 (S11-Hsubcons): no booked consumer price is 0 or negative; on a row whose rate was capped at the
    reference less the consumer floor, the consumer price is at least floor_share x reference. Returns (failures, detail)."""
    bad = []
    for x in rows:
        k = f'{x["region"]} {x["commodity"]}'
        c = float(x['consumer_price'])
        if not (np.isfinite(c) and c > 0):
            bad.append(f'{k} consumer price {c:.6g} is not positive')
        elif x.get('rate_cap') == 'reference_less_consumer_floor' and c < floor_share * float(x['reference_price']) * (1 - tol):
            bad.append(f'{k} consumer price {c:.6g} below {floor_share:.0%} of the reference')
    return len(bad), '; '.join(bad[:20])


def trade_change(R, comms, old_fob, new_fob):
    recs = []
    for c in comms:
        for i, r in enumerate(R):
            ox, nx = old_fob[c][i].sum(), new_fob[c][i].sum()
            om, nm = old_fob[c][:, i].sum(), new_fob[c][:, i].sum()
            recs.append(dict(region=r, commodity=c, exports_s10_musd=ox, exports_s11_musd=nx, exports_change_musd=nx - ox,
                             imports_s10_musd=om, imports_s11_musd=nm, imports_change_musd=nm - om))
    return pd.DataFrame(recs)


def _mer(path, msn):
    d = pd.read_csv(path, dtype=str)
    row = d[(d['MSN'] == msn) & (d['YYYYMM'] == '202213')]
    return float(row.iloc[0]['Value']) if len(row) == 1 else np.nan


IO_SECTOR = {'coa': 'coa', 'oil': 'B06', 'gas': 'B06', 'pet': 'pet', 'ely': 'ely'}


def usa_table(V, vol, mer, spot, io10):
    """USA S11 volumes and values against EIA MER 2022 and io_s10 output (report only)."""
    u = V[V['region'] == 'USA'].set_index('commodity')
    out_io = io10[(io10['region'] == 'USA') & (io10['row'] == 'OUT')].iloc[0]
    ref = {
        'oil': (_mer(mer['T03.01'], 'PAPRPUS') * DAYS / 1000.0, 'MER T03.01 PAPRPUS crude production kb/d x 365 / 1000'),
        'gas': (_mer(mer['T04.01'], 'NGPRPUS') * BCM_PER_BCF, 'MER T04.01 NGPRPUS dry production bcf x 0.0283168'),
        'coa': (_mer(mer['T06.01'], 'CLPRPUS') * SHORT_TON_T / 1000.0, 'MER T06.01 CLPRPUS thousand short tons x 0.9072 / 1000'),
        'ely': (_mer(mer['T07.01'], 'ELETPUS'), 'MER T07.01 ELETPUS net generation, billion kWh'),
        'pet': (np.nan, 'no MER refinery output series in the extract'),
    }
    recs = []
    for c in COMMODITIES:
        mv, msrc = ref[c]
        recs.append(dict(commodity=c, production_s11=u.loc[c, 'production'], production_mer=mv, mer_series=msrc,
                         ratio_s11_over_mer=u.loc[c, 'production'] / mv if mv and np.isfinite(mv) else np.nan,
                         exports_s11=u.loc[c, 'exports'], imports_s11=u.loc[c, 'imports'],
                         export_price=u.loc[c, 'export_price'], domestic_price=u.loc[c, 'domestic_price'],
                         output_value_s11_musd=u.loc[c, 'output_value'], io_s10_sector=IO_SECTOR[c],
                         io_s10_out_musd=float(out_io[IO_SECTOR[c]])))
    d = pd.DataFrame(recs)
    d['wti_eia_cushing'] = spot.get('Cushing, OK WTI Spot Price FOB (Dollars per Barrel)', np.nan)
    return d


def oil_check(V, io10, R):
    """S11 output values against io_s10 OUT by region: coa vs coa, oil+gas vs B06, pet vs pet."""
    out = io10[io10['row'] == 'OUT'].set_index('region')
    Vi = V.set_index(['region', 'commodity'])['output_value']
    recs = []
    for r in R:
        for label, comms, sec in (('coa', ('coa',), 'coa'), ('oil+gas', ('oil', 'gas'), 'B06'), ('pet', ('pet',), 'pet')):
            s11 = float(sum(Vi[(r, c)] for c in comms))
            io = float(out.loc[r, sec])
            recs.append(dict(region=r, commodity=label, io_s10_sector=sec, output_s11_musd=s11, io_s10_out_musd=io,
                             ratio_s11_over_io=s11 / io if io > 0 else np.nan, gap_musd=s11 - io))
    return pd.DataFrame(recs)


def non_energy_unchanged(vxsb7, vfob10):
    """Energy cells where S10 VFOB differs from S07R VFOB (1e-9 USD m): S11's 'before' values are the S07R values."""
    key = ['sector', 'exporter', 'importer']
    a = vxsb7[vxsb7['sector'].isin(TARGETS)][key + ['vfob_musd']]
    b = vfob10[vfob10['sector'].isin(TARGETS)][key + ['vfob_musd']]
    m = a.merge(b, on=key, how='outer', suffixes=('_7', '_10')).fillna(0.0)
    return int(((m['vfob_musd_7'] - m['vfob_musd_10']).abs() > 1e-9).sum())


GULF = ('U.S. Gulf Coast Conventional Gasoline Regular Spot Price FOB (Dollars per Gallon)',
        'U.S. Gulf Coast Ultra-Low Sulfur No 2 Diesel Spot Price (Dollars per Gallon)',
        'U.S. Gulf Coast Kerosene-Type Jet Fuel Spot Price FOB (Dollars per Gallon)')
# US petroleum domestic price: (EIA spot series, EIA refinery and blender net production series used as its weight)
US_PRODUCTS = ((GULF[0], 'U.S. Refinery and Blender Net Production of Finished Motor Gasoline (Thousand Barrels)'),
               (GULF[1], 'U.S. Refinery and Blender Net Production of Distillate Fuel Oil (Thousand Barrels)'),
               (GULF[2], 'U.S. Refinery and Blender Net Production of Kerosene-Type Jet Fuel (Thousand Barrels)'),
               ('Mont Belvieu, TX Propane Spot Price FOB (Dollars per Gallon)', 'U.S. Refinery and Blender Net Production of Propane (Thousand Barrels)'))


def hub_check(ei, spot):
    p = ei['wti'] + ei['margin_usgc']
    g = [spot[k] * GAL_PER_BBL for k in GULF if k in spot]
    avg = float(np.mean(g)) if g else np.nan
    return f'WTI + USGC margin {p:.2f} USD/bbl; EIA Gulf Coast gasoline/diesel/jet simple mean {avg:.2f} USD/bbl; ratio {p / avg:.3f}'


SECRET = re.compile(br'(?i)(?:api[_-]?key|password|secret|token)\s*[:=]\s*["\']?[A-Za-z0-9_\-]{12,}')


def secret_scan(paths):
    hits = 0
    for root in paths:
        if not os.path.exists(root):
            continue
        files = [root] if os.path.isfile(root) else [os.path.join(d, f) for d, _, fs in os.walk(root)
                                                      for f in fs if '__pycache__' not in d]
        for p in files:
            if p.endswith(('.gz', '.zip', '.xlsx', '.pyc')) or os.path.getsize(p) > 8_000_000:
                continue
            with open(p, 'rb') as fh:
                hits += bool(SECRET.search(fh.read()))
    return hits


def gas_pet_share(B, tol=1e-6):
    """B06 split rows: the share of the final io_s11 gas row (users other than exports) into pet equals
    refinery gas / S11 gas domestic sales (imports for imp) where the pet cell does not cap it, and is below that share where it does.
    Returns (number of bad rows, detail)."""
    bad = []
    for _, b in B.iterrows():
        for k in ('dom', 'imp'):
            if f'gas_pet_share_{k}' not in b or not np.isfinite(b[f'gas_pet_share_{k}']):
                continue
            row = b[f'gas_row_io_{k}']
            got = b[f'gas_pet_io_{k}'] / row if row > 0 else 0.0
            q = b[f'gas_pet_share_{k}'] if row > 0 else 0.0
            ok = (got <= q + tol) if b[f'gas_pet_capped_{k}'] else abs(got - q) <= tol
            if not ok:
                bad.append(f'{b["region"]} {k} {got:.4f} vs {q:.4f}')
    return len(bad), '; '.join(bad[:10])


# ------------------------------------------------------------------ observed gas export prices
def observed_gas_prices(px_gas, R, obs, tol=1e-9):
    """Every exporter in gas_export_price_observed.csv carries its observed price (value / volume) as its S11 gas
    export price, and the price is finite and positive. Returns (number of bad regions, detail)."""
    ix = {r: i for i, r in enumerate(R)}
    bad = []
    for r, o in obs.items():
        p = px_gas[ix[r]] if r in ix else np.nan
        want = o['value_musd'] / o['volume_bcm']
        if not (np.isfinite(p) and p > 0 and abs(p - want) <= tol * max(1.0, want)):
            bad.append(f'{r} {p} vs {want}')
    return len(bad), '; '.join(bad[:10])


# ------------------------------------------------------------------ fix list A2: export taxes on energy
def export_tax_rates(xt10, regions, comms):
    """{commodity: array by exporter} of the S10 export-tax rate on VFOB (export_tax_s10.csv: exporter, sector, rate);
    0 where S10 books none. A rate outside [0, 1) stops the stage (S10-Hxtax already holds it there)."""
    ix = {r: i for i, r in enumerate(regions)}
    out = {c: np.zeros(len(regions)) for c in comms}
    for x in xt10.itertuples():
        if x.sector in out and x.exporter in ix:
            t = float(x.rate)
            if not 0.0 <= t < 1.0:
                raise ValueError(f'export_tax_s10 {x.exporter} {x.sector}: rate {t} outside [0, 1)')
            out[x.sector][ix[x.exporter]] = t
    return out


def energy_export_tax(vf, xt10, vfob10, V, sectors, tol=1e-9, route_rate=None):
    """Fix list A2 on the written S11 energy routes. vf: vfob_energy_s11 (sector, exporter, importer, vxsb_musd,
    vfob_musd, export_tax_rate); xt10: export_tax_s10 (exporter, sector, rate); vfob10: vfob_s10 (with
    export_tax_rate when S10 writes it); V: energy_values (region, commodity, export_tax). route_rate (Fable QA C-03):
    a Series by (sector, exporter, importer) of the route rates of export_route_rate_rule; without it t is the
    export_tax_s10 rate of the route's exporter and good (0 if none). Fails where
      - a route's VXSB is not VFOB x (1 - t);
      - the route's export_tax_rate column is not that t;
      - an S10 energy route carries an export_tax_rate other than the export_tax_s10 rate;
      - the export tax of a region and good in V is not its routes' VFOB - VXSB.
    Returns (failures, detail)."""
    t = xt10.set_index(['exporter', 'sector'])['rate'].astype(float)
    key = pd.MultiIndex.from_frame(vf[['exporter', 'sector']])
    want = np.nan_to_num(key.map(t).to_numpy(float))
    if route_rate is not None:
        want = np.nan_to_num(pd.MultiIndex.from_frame(vf[['sector', 'exporter', 'importer']]).map(route_rate).to_numpy(float))
    bad = []
    vx, vfob = vf['vxsb_musd'].to_numpy(float), vf['vfob_musd'].to_numpy(float)
    gap = np.abs(vx - vfob * (1.0 - want)) > tol * np.maximum(1.0, np.abs(vfob)) + 2e-6      # the file is rounded to 1e-6
    bad += [f'{x.sector} {x.exporter}->{x.importer}: VXSB {x.vxsb_musd:.6g} vs VFOB x (1 - {w:.6g})' for x, w in zip(vf[gap].itertuples(), want[gap])]
    if 'export_tax_rate' in vf:
        g2 = np.abs(vf['export_tax_rate'].to_numpy(float) - want) > tol + 1e-6     # rates are written rounded to 1e-6
        bad += [f'{x.sector} {x.exporter}->{x.importer}: route rate {x.export_tax_rate:.6g} vs {w:.6g}' for x, w in zip(vf[g2].itertuples(), want[g2])]
    else:
        bad.append('vfob_energy_s11 has no export_tax_rate column')
    if 'export_tax_rate' in vfob10:
        e10 = vfob10[vfob10['sector'].isin(sectors)]
        w10 = np.nan_to_num(pd.MultiIndex.from_frame(e10[['exporter', 'sector']]).map(t).to_numpy(float))
        g3 = np.abs(e10['export_tax_rate'].to_numpy(float) - w10) > tol + 1e-6
        bad += [f'S10 {x.sector} {x.exporter}->{x.importer}: vfob_s10 rate {x.export_tax_rate:.6g} vs export_tax_s10 {w:.6g}'
                for x, w in zip(e10[g3].itertuples(), w10[g3])]
    routes = (vf['vfob_musd'] - vf['vxsb_musd']).groupby([vf['exporter'], vf['sector']]).sum()
    held = V.set_index(['region', 'commodity'])['export_tax'] if 'export_tax' in V else pd.Series(dtype=float)
    idx = routes.index.union(held.index)
    a, b = routes.reindex(idx, fill_value=0.0), held.reindex(idx, fill_value=0.0)
    for k in idx[(a - b).abs() > 1e-6 * np.maximum(1.0, b.abs()) + 1e-3]:
        bad.append(f'{k[0]} {k[1]}: routes VFOB - VXSB {a[k]:.6g} vs energy_values export tax {b[k]:.6g}')
    return len(bad), '; '.join(bad[:10]) + (f'; and {len(bad) - 10} more' if len(bad) > 10 else '')


def export_route_rate_rule(xtm, R, xrate, line_rates, exempt, tol=1e-9):
    """S11-Hxtroute (Fable QA C-03): every route rate follows the route rule independently of how it was formed: 0 on
    an exempt route (EAEU internal); for an exporter and good with line rates, between the lowest and highest line
    rate; else the S10 exporter rate. xtm: {good: n x n}; line_rates: {exporter: {good: {line: rate}}}.
    Returns (failures, detail)."""
    bad = []
    for c, T in xtm.items():
        for i, r in enumerate(R):
            lr = line_rates.get(r, {}).get(c)
            lo, hi = (min(lr.values()), max(lr.values())) if lr else (xrate[c][i], xrate[c][i])
            for j in range(len(R)):
                if i == j:
                    continue
                t = T[i, j]
                ok = abs(t) <= tol if exempt[i, j] else (lo - tol <= t <= hi + tol)
                if not ok:
                    bad.append(f'{c} {r}->{R[j]} {t:.6g}' + (' (exempt)' if exempt[i, j] else f' outside [{lo:.6g}, {hi:.6g}]'))
    return len(bad), '; '.join(bad[:20])


# ------------------------------------------------------------------ fix round w16: supply = use (GTAP 12 ch.12 §12.2.4)
def supply_use_balanced(R, prod, imp, exp, use, measured, tol=1e-9, floor=1e-12):
    """S11-Hsupuse. Per region whose domestic use is measured: production + imports = domestic use + exports after the
    two-sided balance (relative to the larger side; floor: an absolute allowance in natural units for float noise on
    zero flows), every array finite and not below -floor. Returns (bad count, detail)."""
    prod, imp, exp, use = (np.asarray(a, float) for a in (prod, imp, exp, use))
    bad = []
    for i in np.where(np.asarray(measured, bool))[0]:
        s, u = prod[i] + imp[i], use[i] + exp[i]
        vals = (prod[i], imp[i], exp[i], use[i])
        if not all(np.isfinite(v) and v >= -floor for v in vals) or abs(s - u) > max(tol * max(abs(s), abs(u)), floor):
            bad.append(f'{R[i]} P {prod[i]:.6g} + M {imp[i]:.6g} vs D {use[i]:.6g} + X {exp[i]:.6g}')
    return len(bad), '; '.join(bad[:20])


def crude_use_absorbed(V, R, crude_in, direct, measured, tol=1e-6):
    """S11-Hsupuse (crude): where crude use is measured and balanced, refinery intake + direct use = the oil absorption
    of energy_values (after the RAS), relative 1e-6. direct: {region: {column: million bbl}}. Returns (bad count, detail)."""
    Vi = V.set_index(['region', 'commodity'])
    bad = []
    for i, r in enumerate(R):
        if not measured[i]:
            continue
        ab = float(Vi.loc[(r, 'oil'), 'absorption'])
        u = float(crude_in[r]) + sum(direct.get(r, {}).values())
        if abs(ab - u) > tol * max(abs(ab), abs(u), 1e-9):
            bad.append(f'{r} intake + direct {u:.6g} vs absorption {ab:.6g}')
    return len(bad), '; '.join(bad[:20])


# ------------------------------------------------------------------ fix round wG: own-use shares for S13
def own_use_shares_ok(OU, V, goods=('coa', 'oil', 'gas', 'ely')):
    """S11-Hownuse: every region and good with S11 output carries an own-use share in [0, 1] and a basis, and the
    value equals the share times the S11 output value. Returns (bad count, detail)."""
    bad = []
    Vi = V.set_index(['region', 'commodity'])['output_value']
    for x in OU.itertuples():
        outv = float(Vi.get((x.region, x.commodity), 0.0))
        if x.commodity not in goods:
            bad.append(f'{x.region} {x.commodity} not an own-use good')
            continue
        if outv <= 0:
            continue
        if not (np.isfinite(x.own_use_share) and 0.0 <= x.own_use_share <= 1.0):
            bad.append(f'{x.region} {x.commodity} share {x.own_use_share}')
        elif x.basis not in ('unsd_2022', 'median_of_reporters'):
            bad.append(f'{x.region} {x.commodity} basis {x.basis}')
        elif abs(x.own_use_value_musd - x.own_use_share * outv) > 1e-9 * max(1.0, outv):
            bad.append(f'{x.region} {x.commodity} value')
    have = set(zip(OU['region'], OU['commodity']))
    for (r, c), v in Vi.items():
        if c in goods and v > 0 and (r, c) not in have:
            bad.append(f'{r} {c} missing')
    return len(bad), '; '.join(bad[:20])


# ------------------------------------------------------------------ Fable QA E-08: coal and gas against EI markers
BENCH_EXPORTER = (0.5, 1.8)     # each mapped exporter above BENCH_BIG_MUSD: export price over its EI marker
BENCH_WORLD = (0.75, 1.33)      # value-weighted over the mapped exporters
BENCH_BIG_MUSD = 5000.0
BENCH_REPORT = 0.25             # the Fable QA band, reported: quality mix and contract against hub prices sit outside it
MMBTU_PER_BCM = 35.7            # EI 2025 'Approximate conversion factors': 1 bcm natural gas = 35.7 trillion Btu


def price_benchmarks(V, bench, ei_coal, hubs, big=BENCH_BIG_MUSD):
    """S11's coal and gas export prices (BACI unit values, coal_price and gas_price) against the EI 2022 marker the
    config maps each exporter to (config/s11/export_price_benchmarks.csv; GTAP 12 ch.12 §12.4 prices from IEA and EI
    sources). Coal: USD/t against USD/t; gas: USD m per bcm against USD/MMBtu x MMBTU_PER_BCM. Every exporter of a
    mapped good above `big` USD m must have a mapping. A row with an open_finding outside the band is listed, not failed
    (S16 lists it for review). Returns dict(ok, summary, detail, table)."""
    rows, miss = [], []
    mk = {('coa', k): v for k, v in ei_coal.items()}
    mk.update({('gas', k): v * MMBTU_PER_BCM for k, v in hubs.items()})
    bmap = {(r['region'], r['commodity']): r['marker'] for r in bench}
    bfind = {(r['region'], r['commodity']): (r.get('open_finding') or '').strip() for r in bench}
    for c in ('coa', 'gas'):
        v = V[(V['commodity'] == c) & (V['export_value'] > big)]
        for x in v.itertuples():
            m = bmap.get((x.region, c))
            if m is None or (c, m) not in mk:
                miss.append(f'{x.region} {c}' + (f' (marker {m} not in EI)' if m else ''))
                continue
            rows.append(dict(region=x.region, commodity=c, marker=m, export_price=float(x.export_price), marker_price=mk[(c, m)],
                             ratio=float(x.export_price) / mk[(c, m)], export_value=float(x.export_value),
                             open_finding=bfind.get((x.region, c), '')))
    t = pd.DataFrame(rows, columns=['region', 'commodity', 'marker', 'export_price', 'marker_price', 'ratio', 'export_value', 'open_finding'])
    ok, det = not miss, []
    for c, g in t.groupby('commodity'):
        w = float((g['ratio'] * g['export_value']).sum() / g['export_value'].sum())
        band = (g['ratio'] < BENCH_EXPORTER[0]) | (g['ratio'] > BENCH_EXPORTER[1])
        out, exc = g[band & (g['open_finding'] == '')], g[band & (g['open_finding'] != '')]
        ok &= bool(BENCH_WORLD[0] <= w <= BENCH_WORLD[1] and out.empty)
        if len(exc):
            det.append('open findings (config, listed not failed): ' + '; '.join(f'{r.region} {c} {r.ratio:.2f}: {r.open_finding}' for r in exc.itertuples()))
        n25 = int(((g['ratio'] - 1).abs() > BENCH_REPORT).sum())
        det.append(f'{c}: {len(g)} exporters, weighted ratio {w:.2f}, range {g["ratio"].min():.2f}-{g["ratio"].max():.2f}; outside the band '
                   + (', '.join(f'{r.region} {r.ratio:.2f}' for r in out.itertuples()) or 'none')
                   + f'; outside ±{BENCH_REPORT:.0%} (report): {n25} (' + ', '.join(f'{r.region} {r.ratio:.2f}' for r in g.itertuples()) + ')')
    if miss:
        det.append('exporters with no marker: ' + ', '.join(miss))
    return dict(ok=ok, summary=f'{len(t)} exporters; {len(miss)} unmapped', detail='. '.join(det), table=t)


def gas_balance_values(V, regions):
    """The S11-Hgasbal value: production, exports, imports and absorption (bcm) of each named region."""
    out = []
    for r in regions:
        g = V[(V['region'] == r) & (V['commodity'] == 'gas')]
        if not g.empty:
            g = g.iloc[0]
            out.append(f'{r} P {g["production"]:.2f} X {g["exports"]:.2f} M {g["imports"]:.2f} absorption {g["absorption"]:.2f}')
    return '; '.join(out)


def ely_subsidy_rows(listed, nin_rows, iea_ely, R):
    """Beta v4 P4 (s11 choice ely_production_subsidy; GTAP 12 ch.12 §12.4.3 p.29): one row per listed region (config
    ely_production_subsidy_2022.csv, value_usd_million). The rule's shortfall is max(0, energy cost / 0.9 - revenue) of the ely
    industry before any price change (nin_rows: ninety_rule without the subsidy). Booked = min(transfer, shortfall), and 0 where
    the IEA has a 2022 electricity subsidy for the region (iea_ely: its gap is already booked; Chepeliev, McDougall and van der
    Mensbrugghe 2018 p.88 on double counting) or the region has no ely industry. Our selection rule, built from the GTAP condition."""
    ely = {x['region']: x for x in nin_rows if x['industry'] == 'ely'}
    out = []
    for x in listed:
        r, t = x['region'], float(x['value_usd_million'])
        if r not in R or r not in ely:
            out.append(dict(region=r, transfer_musd=t, shortfall_musd=np.nan, booked_musd=0.0, status='no ely industry in the rule',
                            source=x['source'], url=x['url']))
            continue
        e = ely[r]
        sf = max(0.0, e['energy_cost_before'] / NINETY - e['revenue_before'])
        if r in iea_ely:
            st, b = 'IEA 2022 electricity subsidy booked: not added', 0.0
        elif sf <= 0:
            st, b = 'the 90 percent rule holds: not booked', 0.0
        else:
            b = min(t, sf)
            st = 'booked at the shortfall' if b < t else 'booked in full'
        out.append(dict(region=r, transfer_musd=t, shortfall_musd=sf, booked_musd=b, status=st, source=x['source'], url=x['url']))
    return out


def transcribed_years(items, base_year=2022):
    """Beta v4 G7: a transcribed price whose item name carries a year (suffix _YYYY) is dated at or before the base
    year (latest year at or before the base year; the DZA row had used 2025). items: item names. Returns (n bad, detail)."""
    import re
    bad = [i for i in items if (m := re.search(r'_(\d{4})$', i)) and int(m.group(1)) > base_year]
    return len(bad), ' '.join(bad)
