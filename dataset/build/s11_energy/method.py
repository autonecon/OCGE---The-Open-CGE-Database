"""S11 method, in the GTAP 12 ch.12 order.

12.2.5  re-exports removed from the volume vectors (same propensity)
12.2.4  world exports = world imports by commodity (opposite rescaling)
12.3    export prices (EI markers, BACI unit values; simple average where missing); gas where the
        BACI tonnes are a Comtrade estimate: BACI value over an observed volume of the same flows
12.4.2  bilateral FOB / export price, seeded, RAS to the volume vectors, times export price;
        CIF from the trade data's margin rates, duty from the protection data
12.4.3  output values (exports at export price, domestic sales at basic price) and the 90 percent rule

All functions are pure: arrays and frames in, arrays and frames out. The stage file
(s11_energy.py) reads the inputs, calls these, and turns the results into checks and files.
Volumes are annual natural units (sources.UNIT); values are USD million.
"""
import numpy as np
import pandas as pd

from .sources import COMMODITIES

RAS_TOL = 1e-10
RAS_MAX_IT = 100000


# ------------------------------------------------------------------ 12.2.4 supply-use, 12.2.5 re-exports, 12.2.4 balance
def supply_use(prod, imp, exp):
    """Opposite rescaling of supply and use (ch.12 §12.2.4) where the volumes cannot hold:
    exports above production plus imports. Supply (P, M) x g and use (X) / g with g = sqrt(X / (P + M)),
    so X = P + M after. With no supply at all, exports have no source and are set to zero.
    Elsewhere consumption is not built (agent_use_volumes), so no imbalance is measured and nothing moves."""
    prod, imp, exp = (np.nan_to_num(np.asarray(a, float)).copy() for a in (prod, imp, exp))
    s = prod + imp
    g = np.ones_like(s)
    over = (exp > s) & (s > 0)
    g[over] = np.sqrt(exp[over] / s[over])
    nosupply = (exp > 0) & (s <= 0)
    return prod * g, imp * g, np.where(nosupply, 0.0, exp / g), g, nosupply


def supply_use_two_sided(prod, imp, exp, use, measured, surplus_only=False):
    """GTAP 12 ch.12 §12.2.4, regional step: supply (P + M) and use (D + X) rescaled in opposite senses so they
    balance, in every region whose domestic use D is measured (choice energy_supply_use_balance).
    Supply x a and use / a, a = sqrt((D + X) / (P + M)), so P a + M a = D / a + X / a exactly.
    A measured region with no use at all (D + X = 0) is treated as unmeasured: a = 0 would wipe its supply, and a
    zero from a source that reports no use is not a measurement (the A10 convention). Unmeasured regions keep the
    one-sided rule of supply_use (exports above P + M only). With no supply, exports have no source and are set to
    zero, and so is measured domestic use. surplus_only (an alternative of the choice, not the GTAP text): only regions
    whose supply exceeds measured use are balanced; the others are treated as unmeasured.
    Returns (P, M, X, D, a, nosupply, measured_used); D is NaN where not measured."""
    prod, imp, exp, use = (np.nan_to_num(np.asarray(v, float)).copy() for v in (prod, imp, exp, use))
    measured = np.asarray(measured, bool)
    s, u = prod + imp, use + exp
    meas = measured & (u > 0)
    if surplus_only:
        meas &= s > u
    p1, m1, x1, g, nosupply = supply_use(prod, imp, exp)
    a = np.where(meas, 1.0, g)
    two = meas & (s > 0)
    a[two] = np.sqrt(u[two] / s[two])
    P = np.where(two, prod * a, p1)
    Mi = np.where(two, imp * a, m1)
    X = np.where(two, exp / np.where(two, a, 1.0), x1)
    D = np.where(meas, np.where(two, use / np.where(two, a, 1.0), 0.0), np.nan)
    return P, Mi, X, D, a, nosupply, meas


def balance_joint(exp, imp, prod, use, measured, tol=1e-13, max_it=20000):
    """GTAP 12 ch.12 §12.2.4, both rescalings at once: "rescale use and supply in opposite senses to remove supply-use
    imbalances, and simultaneously rescale exports and imports in opposite senses to remove export-import imbalances.
    The re-scalings are interrelated, since imports are part of supply, and exports are part of use."
    One world factor f per commodity (exports x f, imports / f; the geometric split of volume_balance) and one factor
    a_i per measured region (P, M x a_i; D, X / a_i), solved together by fixed-point iteration, with the bound
    domestic exports <= production of balance() (P x g, X / g where it binds). At the fixed point: world X = world M,
    P + M = D + X in every measured region, and X <= P everywhere. use is D after the regional step (NaN where not
    measured). Returns (X, M, world factor, P, D, a_i product, iterations)."""
    x, m = np.asarray(exp, float).copy(), np.asarray(imp, float).copy()
    p = np.asarray(prod, float).copy()
    meas = np.asarray(measured, bool)
    d = np.where(meas, np.nan_to_num(np.asarray(use, float)), np.nan)
    atot = np.ones_like(x)
    if x.sum() <= 0 or m.sum() <= 0:
        return x * 0, m * 0, 1.0, p, d, atot, 0
    ftot = 1.0
    for it in range(1, max_it + 1):
        f = np.sqrt(m.sum() / x.sum())
        x, m, ftot = x * f, m / f, ftot * f
        s, u = p + m, np.nan_to_num(d) + x
        ok = meas & (s > 0) & (u > 0)
        a = np.ones_like(x)
        a[ok] = np.sqrt(u[ok] / s[ok])
        p, m, x = p * a, m * a, x / a
        d = np.where(meas, d / a, np.nan)
        atot *= a
        over = x > p * (1 + tol)
        g = np.sqrt(np.divide(x, p, out=np.ones_like(x), where=over & (p > 0)))
        p, x = np.where(over, p * g, p), np.where(over, x / g, x)
        if not over.any() and abs(f - 1) < tol and np.all(np.abs(a - 1) < tol):
            break
    return x, m, ftot, p, d, atot, it


def remove_reexports(prod, imp, exp):
    """Same propensity (ch.12 §12.2.5): re-exports = X * M / (P + M). Both X and M of the transit region lose them.
    Needs X <= P + M (supply_use first)."""
    prod, imp, exp = (np.nan_to_num(np.asarray(a, float)) for a in (prod, imp, exp))
    supply = prod + imp
    share = np.divide(imp, supply, out=np.zeros_like(supply), where=supply > 0)
    rx = exp * share
    return exp - rx, imp - rx, rx


def remove_reexports_observed(prod, imp, exp, share):
    """ch.12 §12.2.5 with the hub's own record (Fable QA D-04; choice reexport_removal). share: the region's observed
    re-export share of exports (UN Comtrade 2022 RX / X of the good's lines, reporters of RX only), NaN where not observed.
    Observed: rx = share x X; else the same propensity rx = X M / (P + M). rx at most min(X, M) and at least X - P
    (exports beyond production can only be re-exports, so domestic exports stay at most P), and the same volume
    leaves X and M of the hub (both sides of its routes netted alike). Needs X <= P + M (supply_use first).
    Returns (X - rx, M - rx, rx, observed)."""
    prod, imp, exp = (np.nan_to_num(np.asarray(a, float)) for a in (prod, imp, exp))
    share = np.asarray(share, float)
    _, _, rx = remove_reexports(prod, imp, exp)
    obs = np.isfinite(share) & (exp > 0)
    rx = np.where(obs, np.clip(np.nan_to_num(share), 0.0, 1.0) * exp, rx)
    rx = np.maximum(np.minimum(rx, np.minimum(exp, imp)), np.maximum(exp - prod, 0.0))    # exports beyond P are re-exports
    return exp - rx, imp - rx, rx, obs


def balance(exp, imp, prod=None, tol=1e-13, max_it=1000):
    """World X = world M: exports x sqrt(M/X), imports x sqrt(X/M) (ch.12 §12.2.4, §12.2.6).
    With prod, the rescalings are solved together with the bound domestic exports <= production
    (the supply-use balance of §12.2.4): where the world factor lifts X above P, P and X are
    rescaled in opposite senses to meet. Returns (X, M, world factor, P)."""
    X, M = exp.sum(), imp.sum()
    if X <= 0 or M <= 0:
        return exp * 0, imp * 0, 1.0, prod
    x, m = exp.astype(float).copy(), imp.astype(float).copy()
    p = None if prod is None else np.asarray(prod, float).copy()
    ftot = 1.0
    for _ in range(max_it):
        f = np.sqrt(m.sum() / x.sum())
        x, m, ftot = x * f, m / f, ftot * f
        if p is None:
            break
        over = x > p * (1 + tol)
        if not over.any() and abs(f - 1) < tol:
            break
        g = np.sqrt(np.divide(x, p, out=np.ones_like(x), where=over & (p > 0)))
        p, x = np.where(over, p * g, p), np.where(over, x / g, x)
    return x, m, ftot, p


def round_to_total(values, groups, totals=None, decimals=6):
    """Round values to `decimals` so that each group's rounded values add up to its rounded total (largest remainder).
    groups: a label per value; totals: {group: total} to round to (default: the group's own sum). Each value moves by
    less than one unit of the last decimal. Used where a later stage sums the written routes (fix round w16)."""
    v = np.asarray(values, float)
    unit = 10.0 ** -decimals
    q = v / unit
    fl = np.floor(q)
    out = fl.copy()
    g = pd.Series(np.asarray(groups, object))
    for key, idx in g.groupby(g).groups.items():
        idx = np.asarray(idx)
        tot = v[idx].sum() if totals is None or key not in totals else float(totals[key])
        need = int(round(round(tot / unit) - fl[idx].sum()))
        if need > 0:
            order = idx[np.argsort(-(q[idx] - fl[idx]), kind='stable')]
            out[order[:min(need, len(order))]] += 1
        elif need < 0:
            order = idx[np.argsort(q[idx] - fl[idx], kind='stable')]
            out[order[:min(-need, len(order))]] -= 1
    return np.round(out * unit, decimals) + 0.0


# ------------------------------------------------------------------ 12.3 prices
def fill_missing_prices(price, has_volume):
    """Exporters with a volume and no price take the simple average of the available prices (ch.12 p.19)."""
    price = np.asarray(price, float).copy()
    avail = np.isfinite(price) & (price > 0)
    avg = float(price[avail].mean()) if avail.any() else np.nan
    filled = (~avail) & has_volume
    price[~avail] = avg
    return price, filled, avg


def gas_tonnes_screen(baci_gas, R, volume_exports, bcm_per_mt):
    """Per gas exporter: BACI value (USD million) and tonnes as bcm on its off-diagonal flows, the volume-source
    exports (bcm) and their ratio. baci_gas has exp, imp (regions), v (thousand USD), q (tonnes)."""
    d = baci_gas[baci_gas['exp'] != baci_gas['imp']]
    g = d.groupby('exp').agg(v=('v', 'sum'), q=('q', lambda x: x.fillna(0).sum()))
    out = pd.DataFrame(index=pd.Index(R, name='region'))
    out['baci_value_musd'] = (g['v'] / 1000.0).reindex(R).fillna(0.0)
    out['baci_bcm'] = (g['q'] / 1e6 * bcm_per_mt).reindex(R).fillna(0.0)
    out['volume_exports_bcm'] = np.asarray(volume_exports, float)
    out['bcm_ratio'] = np.divide(out['baci_bcm'], out['volume_exports_bcm'], out=np.full(len(R), np.nan),
                                 where=np.nan_to_num(out['volume_exports_bcm'].to_numpy(float)) > 0)
    return out.reset_index()


def observed_gas_export_prices(baci_gas, rows, R, volume_exports, route_volume):
    """Gas export prices where the BACI tonnes are a Comtrade estimate: BACI value over an observed volume of
    the same flows (USD million per bcm). rows: config rows (region, method, route_exporters, route_importer);
    route_volume: {(route_exporters, route_importer): bcm} for route rows.
      baci_value_over_volume_source_exports: the exporter's BACI gas value on all its flows / its S11 volume-source exports
      baci_route_value_over_ei_route_volume: the BACI gas value of the route exporters to the route importer / the EI route volume
    Returns {region: dict(price, value_musd, volume_bcm, source)}."""
    d = baci_gas[baci_gas['exp'] != baci_gas['imp']]
    ix = {r: i for i, r in enumerate(R)}
    out = {}
    for row in rows:
        r, how = row['region'], row['method']
        if how == 'baci_value_over_volume_source_exports':
            val = d.loc[d['exp'] == r, 'v'].sum() / 1000.0
            vol = float(volume_exports[ix[r]])
            src = f'BACI 2022 gas value {val:.1f} USD m over S11 volume-source exports {vol:.3f} bcm (BACI tonnes estimated)'
        elif how == 'baci_route_value_over_ei_route_volume':
            exps = tuple(row['route_exporters'].split(';'))
            imp = row['route_importer']
            if r not in exps:
                raise SystemExit(f'gas_export_price_observed.csv: {r} is not in its own route {exps}')
            val = d.loc[d['exp'].isin(exps) & (d['imp'] == imp), 'v'].sum() / 1000.0
            vol = float(route_volume[(row['route_exporters'], imp)])
            src = (f'BACI 2022 gas value {"+".join(exps)} to {imp} {val:.1f} USD m over EI 2022 route volume {vol:.3f} bcm '
                   f'(BACI tonnes estimated)')
        else:
            raise SystemExit(f'gas_export_price_observed.csv: unknown method {how!r} for {r}')
        if not (val > 0 and vol > 0):
            raise SystemExit(f'gas_export_price_observed.csv: {r} has value {val} and volume {vol}; both must be positive')
        out[r] = dict(price=val / vol, value_musd=val, volume_bcm=vol, source=src)
    return out


def reporter_fob_gas_prices(rows, comtrade, bcm_per_mt):
    """Beta v4 P41 (choice gas_reporter_fob): a listed exporter's gas reference price from its own customs, the UN Comtrade
    2022 FOB value over net weight of its exports to the world on the listed HS lines (USD million per bcm at bcm_per_mt).
    rows: config rows (region, reporter_code, hs_lines 'a;b'); comtrade: {hs line: Comtrade preview 'data' records}.
    Returns {region: dict(price, value_musd, volume_bcm, source)}."""
    out = {}
    for row in rows:
        r, code = row['region'], int(row['reporter_code'])
        val = wt = 0.0
        used = []
        for line in row['hs_lines'].split(';'):
            for x in comtrade.get(line, ()):
                if int(x['reporterCode']) == code and int(x['partnerCode']) == 0 and x['flowCode'] == 'X':
                    v, w = float(x.get('fobvalue') or x.get('primaryValue') or 0.0), float(x.get('netWgt') or 0.0)
                    if v > 0 and w > 0:
                        val, wt = val + v, wt + w
                        used.append(f'{line} {v / 1e6:.1f} USD m on {w / 1e9:.4g} Mt')
        if not (val > 0 and wt > 0):
            raise SystemExit(f'gas_export_price_reporter.csv: no Comtrade 2022 FOB value and net weight for {r} (reporter {code})')
        vol = wt / 1e9 * bcm_per_mt
        out[r] = dict(price=val / 1e6 / vol, value_musd=val / 1e6, volume_bcm=vol,
                      source=f'UN Comtrade 2022 reporter {code} exports to the world, FOB ({"; ".join(used)}) over net weight at '
                             f'{bcm_per_mt:g} bcm per Mt (beta v4 P41)')
    return out


# ------------------------------------------------------------------ Fable QA D-02: route prices
ROUTE_BAND = (1.0 / 3.0, 3.0)    # a route unit value outside [1/3, 3] x the exporter's reference price is a tonnes defect


def route_unit_values(rows, R, per_unit, extra_volume=None):
    """BACI route unit values (USD per natural unit) by exporter x importer. rows: BACI rows with exp, imp (regions),
    v (thousand USD), q (tonnes); per_unit: tonnes per natural unit (crude 0.1364 t/bbl; coal 1; gas 1 / 1.36, Mt per
    bcm); uv = sum v x 1000 / sum q x per_unit, over the rows with tonnes. extra_volume: {(exp, imp):
    natural units} observed outside BACI (choice gas_route_volume_observed: a pipeline volume whose tonnes the
    importer did not report), added to the route's BACI volume (the caller leaves that line's tonnes out). NaN where the route has no
    positive volume. Off-diagonal only."""
    ix = {r: i for i, r in enumerate(R)}
    n = len(R)
    d = rows[(rows['exp'] != rows['imp']) & rows['exp'].isin(ix) & rows['imp'].isin(ix)]
    extra = set(extra_volume or {})
    keep = (d['q'].fillna(0) > 0) | pd.Series([k in extra for k in zip(d['exp'], d['imp'])], index=d.index, dtype=bool)
    d = d[keep]                                                    # a value without tonnes has no unit value
    g = d.groupby(['exp', 'imp']).agg(v=('v', 'sum'), q=('q', lambda x: x.fillna(0).sum()))
    V, Q = np.zeros((n, n)), np.zeros((n, n))
    ii = g.index.get_level_values(0).map(ix).to_numpy()
    jj = g.index.get_level_values(1).map(ix).to_numpy()
    V[ii, jj] = g['v'].to_numpy(float) / 1000.0                     # USD million
    Q[ii, jj] = g['q'].to_numpy(float) / 1e6 / per_unit            # million natural units
    for (e, i), vol in (extra_volume or {}).items():
        Q[ix[e], ix[i]] += vol
    return np.divide(V, Q, out=np.full((n, n), np.nan), where=Q > 0)


def route_prices(px, uv, band=ROUTE_BAND, at_reference=None):
    """GTAP 12 ch.12 §12.4.2 values kept route by route (Fable QA D-02; choice export_price_by_route): the price of a route
    is its own BACI unit value where it exists and lies in band x the exporter's reference price px (the §12.3 price),
    else px. at_reference: exporters priced at px on every route (gas_export_price_observed: BACI tonnes estimated).
    Returns (price matrix, mask of routes at their own unit value)."""
    px = np.asarray(px, float)
    P = np.repeat(px[:, None], len(px), axis=1)
    ok = np.isfinite(uv) & (uv >= band[0] * P) & (uv <= band[1] * P) & np.isfinite(P) & (P > 0)
    if at_reference is not None:
        ok &= ~np.asarray(at_reference, bool)[:, None]
    np.fill_diagonal(ok, False)
    return np.where(ok, uv, P), ok


def line_mix_route_prices(rows, R, exporter, p_pipe, p_lng, pipe_hs='271121', lng_hs='271111'):
    """Beta v4 P25 (choice gas_line_mix_price; extends the D-02 route pricing): an exporter priced at its reference on every
    route (estimated BACI tonnes) gets, on each route, w x p_pipe + (1 - w) x p_lng, w = the route's BACI pipeline value
    share (271121 over 271121 + 271111), else the exporter's share over all its routes. rows: BACI gas rows with exp,
    imp, k, v. Returns the price row (NaN on the diagonal) and the pipeline share row."""
    ix = {r: i for i, r in enumerate(R)}
    n = len(R)
    d = rows[(rows['exp'] == exporter) & rows['imp'].isin(ix) & (rows['imp'] != exporter) & (rows['v'] > 0)]
    pv = d[d['k'] == pipe_hs].groupby('imp')['v'].sum()
    lv = d[d['k'] == lng_hs].groupby('imp')['v'].sum()
    tot_p, tot_l = float(pv.sum()), float(lv.sum())
    w_all = tot_p / (tot_p + tot_l) if tot_p + tot_l > 0 else 1.0
    w = np.full(n, w_all)
    for imp in set(pv.index) | set(lv.index):
        a, b = float(pv.get(imp, 0.0)), float(lv.get(imp, 0.0))
        if a + b > 0:
            w[ix[imp]] = a / (a + b)
    price = w * p_pipe + (1.0 - w) * p_lng
    price[ix[exporter]] = np.nan
    return price, w


def realised_export_price(fob, vol, px):
    """The exporter's export price after route valuation: VFOB / volume over its routes (the price of its export value
    in energy_values), px where it exports nothing."""
    x = vol.sum(1)
    return np.divide(fob.sum(1), x, out=np.asarray(px, float).copy(), where=x > 0)


def eurostat_origin_seed(named, nsp, mirror_excess):
    """Fable QA D-02 (choice gas_import_origin): an importer's gas imports by origin from its own Eurostat report
    (nrg_ti_gas): named partners as reported; the volume reported without origin (NSP) shared over the partners'
    own reports of exports to it beyond what it names (nrg_te_gas less nrg_ti_gas, at least zero). named, mirror_excess:
    {partner: volume}. Returns {partner: volume}; NSP with no mirror excess anywhere is left out (reported)."""
    out = {p: float(v) for p, v in named.items() if v > 0}
    tot = sum(max(float(v), 0.0) for v in mirror_excess.values())
    if nsp > 0 and tot > 0:
        for p, v in mirror_excess.items():
            if v > 0:
                out[p] = out.get(p, 0.0) + nsp * float(v) / tot
    return out


# ------------------------------------------------------------------ Fable QA C-03: export tax by route
def route_export_tax(xrate, line_rate, route_line, imp_line, exempt, forced=None):
    """GTAP XTRV is bilateral (ch.2 Table 2.3; ch.17A eq. 17.30): the export-tax rate of a route (Fable QA C-03; choice
    export_tax_after_override). xrate: the S10 rate of each exporter (array). line_rate: {exporter: {line: rate}} where
    the statutory rate differs by HS line (config/s10/export_tax_rates_2022.csv); route_line: {line: n x n BACI
    route values}; imp_line: {line: n BACI import values by importer}; exempt: n x n bool, routes the duty does not
    apply to (EAEU internal trade). An exporter with line rates takes, on each route, the rates weighted by the route's
    own BACI line values (LNG routes at the LNG rate), else by the importer's BACI line mix (a route BACI does not
    record: the line the importer receives), else the S10 rate; other exporters the S10 rate. Exempt routes: zero.
    forced: {(exporter index, importer index): line} for routes whose physical line is known and BACI does not record
    (config/s11/export_tax_route_lines.csv: RUS to TUR by pipeline); the route takes that line's rate."""
    n = len(xrate)
    T = np.repeat(np.asarray(xrate, float)[:, None], n, axis=1)
    for i, rates in line_rate.items():
        lines = [l for l in rates if l in route_line]
        if not lines:
            continue
        w = np.array([route_line[l][i] for l in lines])                    # lines x importers
        wi = np.array([imp_line[l] for l in lines])
        r = np.array([rates[l] for l in lines])[:, None]
        own, imp_ = w.sum(0), wi.sum(0)
        t = np.where(own > 0, (w * r).sum(0) / np.where(own > 0, own, 1.0),
                     np.where(imp_ > 0, (wi * r).sum(0) / np.where(imp_ > 0, imp_, 1.0), T[i]))
        T[i] = t
    for (i, j), l in (forced or {}).items():
        if i in line_rate and l in line_rate[i]:
            T[i, j] = line_rate[i][l]
    return np.where(np.asarray(exempt, bool), 0.0, T)


def scale_export_tax_to_collected(xtm, fob, targets, cap):
    """Beta v4 G13 (choice export_duty_to_collected; fallback, a labelled departure: GTAP 12 ch.17A eq. 17.30 takes
    the statutory XTRV): the route export-tax rates of each listed exporter, every energy good, times one factor so that
    sum(fob x rate) equals its collected duty; a scaled rate is held at cap. xtm, fob: {commodity: n x n}; targets:
    {exporter index: collected USD m}. Returns (new xtm, [(index, booked before, factor, booked after)])."""
    out = {c: np.array(m, float) for c, m in xtm.items()}
    rows = []
    for i, want in targets.items():
        before = sum(float((fob[c][i] * out[c][i]).sum()) for c in out)
        f = want / before if before > 0 else 1.0
        for c in out:
            out[c][i] = np.minimum(out[c][i] * f, np.where(out[c][i] > 0, cap, 0.0))
        rows.append((i, before, f, sum(float((fob[c][i] * out[c][i]).sum()) for c in out)))
    return out, rows


# ------------------------------------------------------------------ 12.4.2 RAS
def seed_matrix(A0, exp, imp, allow_diag, eps, feasible=None):
    """Zeros of the initial volume matrix get eps * X_i * M_j / sum(M) (ras_seed). Diagonals only where allowed.
    feasible (beta v4 P13, choice ras_seed_routes): a bool matrix; a zero is seeded only where it is True."""
    A = np.asarray(A0, float).copy()
    n = A.shape[0]
    Msh = imp / imp.sum() if imp.sum() > 0 else np.zeros(n)
    seed = eps * np.outer(exp, Msh)
    mask = (A <= 0)
    if feasible is not None:
        mask &= np.asarray(feasible, bool)
    diag = np.eye(n, dtype=bool)
    mask &= ~(diag & ~allow_diag[:, None])
    A[mask] = seed[mask]
    A[diag & ~allow_diag[:, None]] = 0.0
    A[exp <= 0, :] = 0.0
    A[:, imp <= 0] = 0.0
    seeded = mask & (A > 0)
    return A, seeded


def baci_feasible_routes(rows, R):
    """Beta v4 P13 (choice ras_seed_routes): exporter x importer routes with a positive BACI value in any year read
    (rows: exp, imp regions and v), off-diagonal only. A route that never carried the good in BACI is not seeded by the
    RAS (GTAP 12 ch.12 §12.4.2 p.25 seeds zeros so the RAS can move; which zeros it seeds is our choice)."""
    ix = {r: i for i, r in enumerate(R)}
    n = len(R)
    F = np.zeros((n, n), bool)
    d = rows[(rows['v'] > 0) & rows['exp'].isin(ix) & rows['imp'].isin(ix) & (rows['exp'] != rows['imp'])]
    F[d['exp'].map(ix).to_numpy(int), d['imp'].map(ix).to_numpy(int)] = True
    return F


def feasible_seed_mask(A0, exp, imp, feasible, allow_diag):
    """Beta v4 P13: the zeros the RAS may seed. feasible: routes seen in BACI 2017-2024 or in the observed route table.
    An exporter (importer) with volume and no positive or feasible route to (from) any trading partner would leave the
    RAS without a solution, so its whole row (column) is released to the plain seed and reported. Returns (mask,
    released exporters, released importers) as index lists."""
    A0 = np.asarray(A0, float)
    n = A0.shape[0]
    diag = np.eye(n, dtype=bool)
    ok = (np.asarray(feasible, bool) | (A0 > 0)) & ~(diag & ~np.asarray(allow_diag, bool)[:, None])
    ok &= (np.asarray(exp) > 0)[:, None] & (np.asarray(imp) > 0)[None, :]
    mask = np.asarray(feasible, bool).copy()
    rel_r = [i for i in range(n) if exp[i] > 0 and not ok[i].any()]
    rel_c = [j for j in range(n) if imp[j] > 0 and not ok[:, j].any()]
    mask[rel_r, :] = True
    mask[:, rel_c] = True
    return mask, rel_r, rel_c


def relabelled_origin(A0, hub, dest, origins, vx):
    """Beta v4 dry run (choice relabelled_origin; labelled departure): crude relabelled in ship-to-ship transfers. The
    hub's prior exports above its own export volume (row sum - vx[hub], at most the hub -> dest prior) are crude of other
    origin; they move from hub -> dest to origin -> dest in proportion to each origin's export volume that its own prior
    routes do not carry (vx[o] - row sum, at least zero). A0: prior volumes (n x n, changed in place). Returns
    {origin: volume moved}."""
    excess = min(max(A0[hub].sum() - vx[hub], 0.0), A0[hub, dest])
    room = {o: max(vx[o] - A0[o].sum(), 0.0) for o in origins}
    tot = sum(room.values())
    if excess <= 0 or tot <= 0:
        return {}
    move = min(excess, tot)
    out = {o: move * v / tot for o, v in room.items() if v > 0}
    A0[hub, dest] -= move
    for o, v in out.items():
        A0[o, dest] += v
    return out


def grid_routes(R, members, borders, cables):
    """Beta v4 dry run (choice ely_grid_routes): region pairs that can trade electricity, off-diagonal: a member of one
    region shares a land border with a member of the other (borders: {iso3: [iso3]}, the mledoze/countries list) or the
    two are joined by a listed interconnector (cables: [(iso3, iso3)], config/s11/ely_cable_links.csv). members:
    {region: [iso3]}. BACI HS 271600 records between unconnected countries (CAN from VNM, IND from USA) are not grid
    trade. Returns an n x n bool matrix."""
    ix = {r: i for i, r in enumerate(R)}
    where = {}
    for r, ms in members.items():
        for m in ms:
            where.setdefault(m, set()).add(ix[r])
    n = len(R)
    G = np.zeros((n, n), bool)
    pairs = [(a, b) for a, bs in borders.items() for b in bs] + [(a, b) for a, b in cables] + [(b, a) for a, b in cables]
    for a, b in pairs:
        for i in where.get(a, ()):
            for j in where.get(b, ()):
                if i != j:
                    G[i, j] = True
    return G


def feasible_vectors(support, exp, imp, prefer=None, tol=1e-12, lower=None, upper=None):
    """Beta v4 dry run (choice ras_feasible_vectors; our choice): with seeds restricted to feasible routes the RAS has a
    solution only if every group of importers can be supplied by the exporters it is connected to. A maximum flow over
    the support (support: n x n bool, routes the RAS may use; capacities exp by exporter, imp by importer) gives the
    largest trade the routes can carry; among those flows the one that carries most on the prefer routes (routes with
    trade data: the prior or BACI 2017-2024), then the smallest sum of relative cuts (sum (exp - rows) / exp +
    sum (imp - cols) / imp), is kept. Returns (exp', imp'), equal to exp, imp where the vectors are already
    consistent; the cuts are the volumes no feasible route can carry. lower, upper (beta v5 E1/R/E2; n x n volumes,
    0 and inf where none): route bounds of the bounded RAS (held routes lower = upper), so the vectors are cut to what
    the bounded routes can carry."""
    from scipy.optimize import linprog
    from scipy.sparse import coo_matrix, vstack
    exp, imp = np.asarray(exp, float), np.asarray(imp, float)
    S_ = np.asarray(support, bool) & (exp > 0)[:, None] & (imp > 0)[None, :]
    ii, jj = np.nonzero(S_)
    n, m = len(exp), len(ii)
    if m == 0:
        return np.zeros_like(exp), np.zeros_like(imp), np.zeros((len(exp), len(exp)), bool)
    scale = max(exp.max(), imp.max())
    e, d = exp / scale, imp / scale
    k = np.arange(m)
    Arow = coo_matrix((np.ones(m), (ii, k)), shape=(n, m))
    Acol = coo_matrix((np.ones(m), (jj, k)), shape=(n, m))
    A = vstack([Arow, Acol]).tocsr()
    b = np.concatenate([e, d])
    bounds = (0, None)
    if lower is not None or upper is not None:
        lo = np.zeros(m) if lower is None else np.asarray(lower, float)[ii, jj] / scale
        hi = np.full(m, np.inf) if upper is None else np.asarray(upper, float)[ii, jj] / scale
        bounds = [(float(a), None if not np.isfinite(h) else float(max(h, a))) for a, h in zip(lo, hi)]
    r1 = linprog(-np.ones(m), A_ub=A, b_ub=b, bounds=bounds, method='highs')
    if r1.status != 0:
        raise SystemExit(f'feasible_vectors: max flow failed ({r1.message})')
    F = -r1.fun
    if F >= max(e.sum(), d.sum()) * (1 - 1e-12):     # every export and every import is carried
        return exp.copy(), imp.copy(), _forced_zero(ii, jj, r1.x, n, tol)
    # minimise the relative cuts at the maximum flow: cut_i = e_i - row_i, so maximise sum_k f_k (1/e_i + 1/d_j)
    w = 1.0 / np.where(e[ii] > 0, e[ii], 1.0) + 1.0 / np.where(d[jj] > 0, d[jj], 1.0)
    w = 1e-3 * w / w.max()
    if prefer is not None:
        w = w + np.asarray(prefer, bool)[ii, jj]
    r2 = linprog(-w, A_ub=A, b_ub=b, A_eq=np.ones((1, m)), b_eq=[F * (1 - 1e-12)], bounds=bounds, method='highs')
    f = r2.x if r2.status == 0 else r1.x
    rows = np.bincount(ii, weights=f, minlength=n) * scale
    cols = np.bincount(jj, weights=f, minlength=n) * scale
    return np.minimum(rows, exp), np.minimum(cols, imp), _forced_zero(ii, jj, f, n, tol)


def _forced_zero(ii, jj, f, n, tol):
    """Routes (ii, jj) with zero flow f whose exporter and importer are in different strongly connected components of
    the residual graph (exporter -> importer on every route; importer -> exporter where the route carries flow): no
    flow with the same row and column sums can use them."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    pos = f > tol * max(f.max(), 1e-300)
    src = np.concatenate([ii, n + jj[pos]])
    dst = np.concatenate([n + jj, ii[pos]])
    g = coo_matrix((np.ones(len(src)), (src, dst)), shape=(2 * n, 2 * n))
    _k, lab = connected_components(g, directed=True, connection='strong')
    Z = np.zeros((n, n), bool)
    z = (~pos) & (lab[ii] != lab[n + jj])
    Z[ii[z], jj[z]] = True
    return Z


def route_gates(A0, A1, fob, seeded, explained=frozenset(), cap_musd=100.0, scale_max=20.0, basis='volume'):
    """Beta v4 P13 hard gates on the RAS result: no seeded route above cap_musd, and no prior route above cap_musd that
    the RAS scaled more than scale_max times, unless the (i, j) pair is in explained. basis 'volume': the factor on the
    route's prior volume; 'share' (beta v4 dry run): the factor on the route's share of its importer's imports,
    A1_ij / A1_.j over A0_ij / A0_.j. Under the RAS (A1 = r_i A0_ij s_j) that is the exporter's row factor over the
    average row factor of the importer's suppliers: an importer whose customs under-record all its imports scales every
    supplier alike and passes, while an exporter whose unrecorded volume lands on a few recorded destinations (VEN to
    ESP) fails. Returns (seeded breaches, scaled breaches) as lists of (i, j, fob, factor)."""
    A0, A1, fob = (np.asarray(x, float) for x in (A0, A1, fob))
    big = fob > cap_musd
    if basis == 'share':
        c0, c1 = A0.sum(0), A1.sum(0)
        A1s = A1 * np.divide(c0, c1, out=np.ones_like(c0), where=c1 > 0)[None, :]
        fac = np.divide(A1s, A0, out=np.full(A0.shape, np.inf), where=A0 > 0)
    else:
        fac = np.divide(A1, A0, out=np.full(A0.shape, np.inf), where=A0 > 0)
    sb = [(i, j, fob[i, j], np.inf) for i, j in np.argwhere(seeded & big) if (i, j) not in explained]
    xb = [(i, j, fob[i, j], fac[i, j]) for i, j in np.argwhere(~seeded & (A0 > 0) & big & (fac > scale_max))
          if (i, j) not in explained]
    return sb, xb


def ras(A, rows, cols, tol=RAS_TOL, max_it=RAS_MAX_IT):
    """Bi-proportional scaling (ch.12 §12.4.2): A_ij -> R_i A_ij S_j with row sums = rows, column sums = cols."""
    A = np.asarray(A, float).copy()
    rows, cols = np.asarray(rows, float), np.asarray(cols, float)
    scale = max(rows.sum(), 1e-300)
    for it in range(1, max_it + 1):
        rs = A.sum(1)
        A *= np.divide(rows, rs, out=np.zeros_like(rs), where=rs > 0)[:, None]
        cs = A.sum(0)
        A *= np.divide(cols, cs, out=np.zeros_like(cs), where=cs > 0)[None, :]
        err = max(np.abs(A.sum(1) - rows).max(), np.abs(A.sum(0) - cols).max()) / scale
        if err < tol:
            return A, it, err
    return A, max_it, err


def capped_ras(A, rows, cols, cap, spill_ok=None, seed=None, hold=None, tol=RAS_TOL, max_rounds=80):
    """Beta v5 E1/R (choice ras_route_caps): RAS with upper bounds. A: the seeded volume matrix; cap: per-cell volume
    bound (inf where none). Each round scales the free cells to the row and column totals left after the fixed cells;
    cells above their bound are fixed at it and the round repeats, until no free cell is above its bound. When the free
    cells cannot carry a row or column total (every route of an exporter is capped and no other route is open), the
    zeros of that row or column where spill_ok is True take the plain seed (seed matrix) and are reported as spilled.
    hold: cells fixed at their value in A from the start (beta v5 R and E2 held routes).
    Returns (A, fixed, spilled, rounds, err); fixed includes the held cells."""
    A = np.asarray(A, float).copy()
    rows, cols = np.asarray(rows, float), np.asarray(cols, float)
    cap = np.asarray(cap, float)
    fixed = np.zeros(A.shape, bool) if hold is None else np.asarray(hold, bool).copy()
    spilled = np.zeros(A.shape, bool)
    scale = max(rows.sum(), 1e-300)
    err = np.inf
    for rnd in range(1, max_rounds + 1):
        fv = np.where(fixed, A, 0.0)
        fr = np.maximum(rows - fv.sum(1), 0.0)
        fc = np.maximum(cols - fv.sum(0), 0.0)
        B, _it, err = ras(np.where(fixed, 0.0, A), fr, fc, tol=tol)
        if err >= tol:
            rs = B.sum(1)
            B2 = B * np.divide(fr, rs, out=np.zeros_like(rs), where=rs > 0)[:, None]
            bad_r = np.abs(fr - B.sum(1)) > tol * scale
            bad_c = np.abs(fc - B2.sum(0)) > tol * scale
            add = (A <= 0) & ~fixed & (bad_r[:, None] | bad_c[None, :]) & (rows > 0)[:, None] & (cols > 0)[None, :]
            if spill_ok is not None:
                add &= np.asarray(spill_ok, bool)
            if seed is None or not add.any():
                return np.where(fixed, A, B), fixed, spilled, rnd, err
            A[add] = np.asarray(seed, float)[add]
            spilled |= add
            continue
        over = ~fixed & (B > cap * (1.0 + 1e-12))
        A = np.where(fixed, A, B)
        if not over.any():
            return A, fixed, spilled, rnd, err
        A[over] = cap[over]
        fixed |= over
    return A, fixed, spilled, max_rounds, err


def route_caps(A0, pxr, commodity, capped_goods, factor, floor_musd, mirror_only, mirror_factor, exempt):
    """Beta v5 E1/R: per-cell volume bounds for capped_ras. For a good in capped_goods (oil, pet) every prior route
    may grow to max(factor x its prior volume, floor_musd at the route price). For any good, a prior route whose
    exporter or importer is mirror-only (reports no energy trade of its own) may grow to mirror_factor x its prior.
    exempt: (i, j) pairs that keep no bound (observed, reviewed, relabelled and grid routes). Zero priors (seeds)
    have no bound here; the seed gate covers them."""
    A0 = np.asarray(A0, float)
    cap = np.full(A0.shape, np.inf)
    prior = A0 > 0
    if commodity in capped_goods:
        floor = np.divide(floor_musd, pxr, out=np.full(A0.shape, np.inf), where=pxr > 0)
        cap = np.where(prior, np.maximum(factor * A0, floor), cap)
    mo = np.asarray(mirror_only, bool)
    mirror = prior & (mo[:, None] | mo[None, :])
    cap = np.where(mirror, np.minimum(cap, mirror_factor * A0), cap)
    for i, j in exempt:
        cap[i, j] = np.inf
    return cap


def volume_cap_breaches(A0, A1, fob, explained, cap_musd, capped_goods, commodity, factor, mirror_only, mirror_factor):
    """Beta v5 E1/R hard gate S11-Hvolcap: prior routes above cap_musd after the RAS whose volume grew more than
    factor (oil, pet) or mirror_factor (a mirror-only partner, any good) times, unless explained. [(i, j, fob, f)]."""
    A0, A1, fob = (np.asarray(x, float) for x in (A0, A1, fob))
    fac = np.divide(A1, A0, out=np.zeros(A0.shape), where=A0 > 0)
    mo = np.asarray(mirror_only, bool)
    lim = np.full(A0.shape, np.inf)
    if commodity in capped_goods:
        lim[:] = factor
    lim = np.where(mo[:, None] | mo[None, :], np.minimum(lim, mirror_factor), lim)
    hit = (A0 > 0) & (fob > cap_musd * (1.0 + 1e-6)) & (fac > lim * (1.0 + 1e-6))
    return [(i, j, fob[i, j], fac[i, j]) for i, j in np.argwhere(hit) if (i, j) not in explained]


# ------------------------------------------------------------------ 12.4.3 values
def ninety_pct(revenue_dom, revenue_exp, fixed_cost, dom_input, own_index, max_it=200):
    """GTAP 12 ch.12 pp.28-29 in an I-O price model, upward only.

    revenue_dom[k]: domestic sales value of energy industry k at the initial domestic price;
    revenue_exp[k]: export value (export price fixed);
    fixed_cost[k]: energy-input cost at fixed prices (imports, exports-priced goods);
    dom_input[c, k]: domestic-product energy input c into industry k at the initial domestic price;
    own_index: the commodity index of each industry k.
    Returns pi[k] >= 1, the factor on industry k's domestic price, and the iterations used.
    Rule: sum_c dom_input[c,k] pi[c] + fixed_cost[k] <= 0.9 (revenue_exp[k] + pi[k] revenue_dom[k])."""
    n = len(revenue_dom)
    pi = np.ones(n)
    for it in range(1, max_it + 1):
        cost = fixed_cost + dom_input.T @ pi
        need = np.ones(n)
        for k in range(n):
            if revenue_dom[k] <= 0:     # no domestic sales: no domestic price to raise (the caller reports it)
                continue
            if cost[k] > 0.9 * (revenue_exp[k] + pi[k] * revenue_dom[k]) + 1e-12:
                own = dom_input[own_index[k], k]
                den = 0.9 * revenue_dom[k] - own
                other = cost[k] - own * pi[k]
                need[k] = max(1.0, (other - 0.9 * revenue_exp[k]) / den) if den > 0 else np.inf
        new = np.maximum(pi, need)
        if np.allclose(new, pi, rtol=1e-12, atol=0):
            return pi, it
        pi = new
        if not np.all(np.isfinite(pi)):
            return pi, it
    return pi, max_it


def ninety_pct_both(revenue_dom, revenue_exp, fixed_cost, dom_input, own_index, lb=1e-3, tol=1e-9):
    """GTAP 12 ch.12 §12.4.3 pp.28-29 with both sides of the adjustment: an imbalance is removed by
    raising the industry's output price and by lowering the prices of its domestically produced
    energy inputs, all solved at once in the I-O price model (export and import prices fixed).

    Same arguments as ninety_pct. The domestic price factors pi solve
        min  sum_c revenue_dom[c] (pi[c] - 1)^2
        s.t. sum_c dom_input[c,k] pi[c] + fixed_cost[k] <= 0.9 (revenue_exp[k] + pi[k] revenue_dom[k])
             for every industry k with domestic sales, and pi >= lb,
    i.e. the smallest value-weighted price change that meets the rule. Only commodities with domestic
    sales have a price to move. Exact: the KKT system is solved on every active set (at most 4
    industries). Where no price vector meets the rule, the upward-only solution is returned so the
    caller reports the industry (infinite pi)."""
    from itertools import combinations
    n = len(revenue_dom)
    var = [c for c in range(n) if revenue_dom[c] > 0]
    pi = np.ones(n)
    if not var:
        return pi, 0
    m = len(var)
    w = np.array([revenue_dom[c] for c in var])
    rows, rhs = [], []
    for k in range(n):
        if revenue_dom[k] <= 0:
            continue
        a = np.array([dom_input[c, k] - (0.9 * revenue_dom[k] if c == own_index[k] else 0.0) for c in var])
        fixed_in = sum(dom_input[c, k] for c in range(n) if c not in var)
        rows.append(a)
        rhs.append(0.9 * revenue_exp[k] - fixed_cost[k] - fixed_in)
    for j in range(m):                       # lower bounds as -pi <= -lb
        e = np.zeros(m)
        e[j] = -1.0
        rows.append(e)
        rhs.append(-lb)
    A, b = np.array(rows), np.array(rhs)
    one = np.ones(m)
    if np.all(A @ one <= b + tol * np.maximum(1.0, np.abs(b))):
        return pi, 0                          # the rule already holds
    best, best_obj, tried = None, np.inf, 0
    for size in range(1, min(len(b), m) + 1):
        for S in combinations(range(len(b)), size):
            tried += 1
            As, bs = A[list(S)], b[list(S)]
            K = As @ (As.T / w[:, None])
            try:
                lam = np.linalg.solve(K, As @ one - bs)
            except np.linalg.LinAlgError:
                continue
            if np.any(lam < -tol * max(1.0, np.abs(lam).max())):
                continue
            p = one - (As.T @ lam) / w
            if np.all(A @ p <= b + tol * np.maximum(1.0, np.abs(b))):
                obj = float(w @ (p - 1) ** 2)
                if obj < best_obj:
                    best, best_obj = p, obj
    if best is None:
        return ninety_pct(revenue_dom, revenue_exp, fixed_cost, dom_input, own_index)
    pi[var] = best
    return pi, tried


# ------------------------------------------------------------------ fix-round A10: caps that S13 applies at S11 prices
def energy_use_caps(V, R, crude_in, crude_src, iso_region, gas_own_tj, gas_supply_tj, gas_pet=None, pi=None, own_share=None, ely_subsidy=None):
    """Per region, what S13 needs to cap two cells of its prior at the S11 energy balance (fix-round A10):
    - the refinery's crude: measured intake (crude_in, million bbl) split domestic / imported by the region's crude
      supply shares, at the domestic basic price after the 90 percent rule and the import basic price, the same
      price basis as the pet and oil output targets (and as the 90 percent rule). Measured only where the intake is
      positive (JODI REFINOBS or EIA consumption); a zero from a blank source is not a measurement.
    - gas own use: UNSD 2022 gas used by the gas industry (0912 + 0931 + 0934) over UNSD total energy supply (GA),
      members of a composite summed; blank where UNSD has no supply.
    - beta v4 P15 (s13 energy_user_pool_split): the refinery gas (gas_pet {region: {'dom', 'imp'}} at the pre-rule prices, the
      domestic part times the rule's gas factor pi[(r, 'gas')]) and the refinery's own use + losses of products (own_share
      {region: share of production} x pet production x the domestic pet price after the rule), the values the 90 percent rule
      priced, for S13 to hold on the refining column.
    - beta v4 P4 (ely_subsidy {region: USD m}): the ely output subsidy S13 books (0 elsewhere).
    V: S11 energy values after the 90 percent rule. Returns a DataFrame by region."""
    Vi = V.set_index(['region', 'commodity'])
    own, sup = {}, {}
    for iso, v in gas_own_tj.items():
        r = iso_region.get(iso)
        if r is not None:
            own[r] = own.get(r, 0.0) + v
    for iso, v in gas_supply_tj.items():
        r = iso_region.get(iso)
        if r is not None:
            sup[r] = sup.get(r, 0.0) + v
    rows = []
    for r in R:
        o = Vi.loc[(r, 'oil')]
        dvol, mvol = max(float(o['domestic_sales']), 0.0), max(float(o['imports']), 0.0)
        sh = dvol / (dvol + mvol) if dvol + mvol > 0 else 1.0
        q = max(float(crude_in.get(r, 0.0)), 0.0)
        pm = float(o['import_basic_price'])
        s_tj, o_tj = sup.get(r, np.nan), own.get(r, 0.0)
        rows.append(dict(region=r, crude_intake_mbbl=q, crude_intake_source=crude_src.get(r, ''), intake_measured=bool(q > 0),
                         crude_domestic_share=sh, intake_value_dom_musd=q * sh * float(o['domestic_price']),
                         intake_value_imp_musd=q * (1 - sh) * (pm if np.isfinite(pm) else 0.0),
                         gas_own_use_tj=o_tj, gas_supply_tj=s_tj,
                         gas_own_use_share=min(o_tj / s_tj, 1.0) if np.isfinite(s_tj) and s_tj > 0 else np.nan,
                         **_pool_values(Vi, r, gas_pet, pi, own_share, ely_subsidy)))
    return pd.DataFrame(rows)


def _pool_values(Vi, r, gas_pet, pi, own_share, ely_subsidy):
    """The beta v4 columns of one energy_use_caps row (NaN where the input is not given)."""
    out = dict(refinery_gas_value_dom_musd=np.nan, refinery_gas_value_imp_musd=np.nan, pet_own_use_value_musd=np.nan,
               ely_output_subsidy_musd=float((ely_subsidy or {}).get(r, 0.0)))
    if gas_pet is not None and r in gas_pet:
        f = float((pi or {}).get((r, 'gas'), 1.0))
        out['refinery_gas_value_dom_musd'] = float(gas_pet[r]['dom']) * (f if np.isfinite(f) else 1.0)
        out['refinery_gas_value_imp_musd'] = float(gas_pet[r]['imp'])
    s = (own_share or {}).get(r)
    if s is not None and np.isfinite(s):
        x = Vi.loc[(r, 'pet')]
        p = float(x['domestic_price'])
        out['pet_own_use_value_musd'] = s * max(float(x['production']), 0.0) * (p if np.isfinite(p) else 0.0)
    return out


OWN_USE_GOODS = ('coa', 'oil', 'gas', 'ely')
OWN_USE_GOODS_PET = ('coa', 'oil', 'gas', 'pet', 'ely')      # beta v4 P15: refinery own use + losses as well


def own_use_shares(V, R, iso_region, unsd_own, goods=OWN_USE_GOODS, loss_split=(), loss_drop=()):
    """Fix round wG (QA round 2 P5): the share of each energy good's output that its own industry uses, from the UNSD
    2022 energy balance (sources.unsd_own_use_2022: energy-industry own use of the good by the industry that makes it,
    plus losses), members of a composite summed: share = (own use + losses) / production, at most 1. A region with
    S11 output but no UNSD production of the good takes the median share of the regions that have one
    (basis 'median_of_reporters'). The value is the share times the S11 output value (S11 prices; for ely the S11
    report-only output value). V: S11 energy values. Returns a DataFrame by region and good.
    loss_split (beta v4 dry run; choice ely_losses_in_own_use, alternative): goods whose losses are shared over domestic production
    and imports, so the industry carries losses x production / (production + imports): grid losses fall on all the power
    a network carries, and an import-dependent grid (AFG, PAL) would otherwise charge its small own output with the
    losses on imported power (own use above 90 percent of revenue). loss_drop (the default rule for ely): goods whose
    losses are left out, as GTAP 12 ch.12 Table 12.3 lists distribution losses under special treatment and maps only
    'own use in electricity, CHP and heat plants' to the ely industry."""
    Vi = V.set_index(['region', 'commodity'])
    agg = {g: {} for g in goods}
    for g in goods:
        for iso, d in unsd_own.get(g, {}).items():
            r = iso_region.get(iso)
            if r is None:
                continue
            a = agg[g].setdefault(r, dict(own=0.0, losses=0.0, production=0.0, imports=0.0))
            for k in a:
                a[k] += d.get(k, 0.0)
    rows = []
    for g in goods:
        def lost(a):
            if g in loss_drop:
                return 0.0
            return a['losses'] * a['production'] / (a['production'] + a['imports']) if g in loss_split else a['losses']
        # beta v4 dry run 3 (S11-Hownuse): clipped at 0, as UNSD rounding leaves CAF, CHN and LAO ely at -4.5e-8 to -3e-17
        sh = {r: min(max((a['own'] + lost(a)) / a['production'], 0.0), 1.0) for r, a in agg[g].items() if a['production'] > 0}
        med = float(np.median(list(sh.values()))) if sh else 0.0
        for r in R:
            a = agg[g].get(r, dict(own=np.nan, losses=np.nan, production=np.nan))
            outv = float(Vi.loc[(r, g), 'output_value']) if (r, g) in Vi.index else 0.0
            if r in sh:
                s, basis = sh[r], 'unsd_2022'
            elif outv > 0:
                s, basis = med, 'median_of_reporters'
            else:
                s, basis = np.nan, 'no_output'
            rows.append(dict(region=r, commodity=g, unsd_own_use=a['own'], unsd_losses=a['losses'], unsd_production=a['production'],
                             own_use_share=s, basis=basis, s11_output_value_musd=outv,
                             own_use_value_musd=s * outv if np.isfinite(s) else np.nan))
    return pd.DataFrame(rows)


def own_use_override_rows(rows, choices, switched_on):
    """Beta v5 E8: [(region, commodity, share, source)] of config/s11/own_use_overrides.csv whose switch is on. A row
    whose switch is on must carry a share in [0, 1] and a source that is not pending."""
    out = []
    for r in rows:
        if r['switch'] not in choices:
            raise SystemExit(f'own_use_overrides.csv: unknown switch {r["switch"]!r}')
        if not switched_on(choices, r['switch']):
            continue
        src = r['source'].strip()
        if not r['own_use_share'].strip() or not src or src.lower().startswith('pending'):
            raise SystemExit(f'own_use_overrides.csv: {r["switch"]} is on but {r["region"]} {r["commodity"]} has no sourced share')
        v = float(r['own_use_share'])
        if not 0.0 <= v <= 1.0:
            raise SystemExit(f'own_use_overrides.csv: share {v} outside [0, 1]')
        out.append((r['region'], r['commodity'], v, src))
    return out


def apply_own_use_overrides(OU, overrides):
    """Beta v5 E8: the own-use share of the listed (region, commodity) rows of own_use_shares' table set to the sourced
    value (basis 'sourced_override'), value = share x the S11 output value."""
    OU = OU.copy()
    for r, g, v, _src in overrides:
        m = (OU['region'] == r) & (OU['commodity'] == g)
        if not m.any():
            raise SystemExit(f'own_use_overrides.csv: {r} {g} is not an own-use row')
        OU.loc[m, 'own_use_share'] = v
        OU.loc[m, 'basis'] = 'sourced_override'
        OU.loc[m, 'own_use_value_musd'] = v * OU.loc[m, 's11_output_value_musd']
    return OU


IO_FINAL_COLUMNS = ('p', 'g', 'i', 'dpabr', 'X', 'stock_gap', 'grev_gap', 'OUT')


def move_user_cells(io, region, commodity, excluded, users, keep_out=('pet',)):
    """Beta v5 E4 (choice gas_users_excluded): in one region's dom_<c> and imp_<c> rows of io (changed in place), the cells
    of the excluded users go to the other industries that already buy the good, pro rata to their cells (final demand,
    exports, gaps and the keep_out columns take nothing). Returns a report dict; raises if no industry can take it."""
    moved, gap, total, to = 0.0, 0.0, 0.0, set()
    for kind in ('dom', 'imp'):
        m = (io['region'] == region) & (io['row'] == f'{kind}_{commodity}')
        if not m.any():
            continue
        idx = io.index[m][0]
        row = io.loc[idx, list(users)].astype(float)
        before = float(row.sum())
        take = float(row[list(excluded)].clip(lower=0).sum())
        if take <= 0:
            continue
        rec = [u for u in users if u not in excluded and u not in IO_FINAL_COLUMNS and u not in keep_out and row[u] > 0]
        if not rec:
            raise SystemExit(f'energy_user_exclusions: {region} {kind}_{commodity} has no other industry to take {take:.1f}')
        base = row[rec].sum()
        for u in rec:
            io.loc[idx, u] = row[u] + take * row[u] / base
        for u in excluded:
            if row[u] > 0:
                io.loc[idx, u] = 0.0
        moved += take
        to |= set(rec)
        total += before
        gap += abs(float(io.loc[idx, list(users)].astype(float).sum()) - before)
    big = sorted(to)
    return dict(region=region, commodity=commodity, moved=moved, row_gap=gap, row_total=total,
                **{'from': '+'.join(excluded) if len(excluded) <= 3 else f'{len(excluded)} users',
                   'to': f'{len(big)} industries'})


# ------------------------------------------------------------------ B06 split (PLAN b1 item 7)
def split_b06(io_r, oil_dom, gas_dom, oil_x, gas_x, oil_m, gas_m, pet_col='pet', x_col='X', gas_pet=None, oil_users=None,
              crude_value_share=None):
    """Split one region's B06 rows (dom_B06, imp_B06) and column into oil and gas.

    io_r: DataFrame indexed by row (dom_*, imp_*, TLS, VA, OUT), columns the region's io columns
    (sectors, final demand, X, gaps, OUT). oil_dom/gas_dom: S11 domestic-sales values of domestic
    product; oil_x/gas_x: export values; oil_m/gas_m: import basic values.
    Rows: dom by domestic-sales shares (X by export shares), imp by import shares. gas_pet
    ({'dom': value, 'imp': value}) is the gas used by refineries from energy data at S11 prices. It enters
    as a share, since io_s10 is not at S11 scale: gas_pet / S11 gas domestic sales (imports for imp) times
    the io gas row, at most the pet cell; oil takes the rest of the cell, and the rest of the oil row goes
    pro rata over the other cells, at most their value. Without gas_pet, oil goes to the pet column first.
    oil_users ({column: share}, fix-round A8, GTAP 12 ch.12 energy balance): crude goes only to refining and to the
    listed direct users. Each listed column takes share x the oil part of the row (share = the energy balance's
    crude use of that user over the region's crude absorption), at most its cell; every other cell of the row,
    beyond refining and exports, is gas. The refinery cell keeps all of the cell that gas does not take: io_s10
    is not at S11 scale, so the cap at measured intake is applied in S13, at S11 prices (A10).
    crude_value_share ({column: {'dom': f, 'imp': f}}, round 3, choice crude_direct_cell_cap; GTAP 12 ch.17A: energy
    volumes held at the energy balance and valued at prices): f = the listed crude burn of that user at the S11 crude
    price over that value plus the user's natural gas burn (same UNSD transaction) at the S11 gas price, domestic and
    imported product apart. The crude part of the listed cell is at most f x the cell, the rest of the cell is gas.
    A column without an entry (no gas burn reported) is capped by its row share alone, as before.
    Columns: the B06-row cells follow their row (oil row to the oil
    column, gas row to the gas column); every other input is split so each new sector keeps
    column total = row total. Returns (new io frame, info)."""
    info = {}
    cols = list(io_r.columns)
    users = [c for c in cols if c != 'OUT']

    def share(a, b):
        t = a + b
        return (a / t) if t > 0 else np.nan

    s_dom, s_x, s_m = share(oil_dom, gas_dom), share(oil_x, gas_x), share(oil_m, gas_m)
    basis = {'dom': 'values', 'x': 'values', 'm': 'values'}
    if not np.isfinite(s_dom):
        alt = next((v for v in (s_m, s_x) if np.isfinite(v)), 0.5)
        basis['dom'] = 'import_values' if np.isfinite(s_m) else ('export_values' if np.isfinite(s_x) else 'half')
        s_dom = alt
    if not np.isfinite(s_x):
        s_x, basis['x'] = s_dom, 'dom_share'
    if not np.isfinite(s_m):
        s_m, basis['m'] = s_dom, 'dom_share'
    info.update(s_dom=s_dom, s_x=s_x, s_m=s_m, **{f'basis_{k}': v for k, v in basis.items()})

    new_rows = {}
    for kind, s in (('dom', s_dom), ('imp', s_m)):
        r = io_r.loc[f'{kind}_B06', users].astype(float)
        oil = pd.Series(0.0, index=users)
        inner = [c for c in users if c != x_col]
        if kind == 'dom':
            oil[x_col] = r[x_col] * s_x
        total_oil = s * r[inner].sum()
        cell = max(r[pet_col], 0.0)
        rest_cols = [c for c in inner if c != pet_col]
        base = r[rest_cols].clip(lower=0)

        def fill(first):
            o = oil.copy()
            o[pet_col] = first
            if oil_users is not None:
                for u, q in oil_users.items():
                    if u in rest_cols:
                        f = (crude_value_share or {}).get(u, {}).get(kind, 1.0)
                        f = min(max(float(f), 0.0), 1.0) if np.isfinite(f) else 1.0
                        o[u] = min(base[u] * f, max(q, 0.0) * total_oil)
            elif total_oil - first > 0 and base.sum() > 0:
                o[rest_cols] = base / base.sum() * min(total_oil - first, base.sum())
            return o

        if gas_pet is None:
            oil = fill(cell if oil_users is not None else min(cell, total_oil))
        else:
            # the gas share of the final io gas row equals q; the final row depends on the cell when oil
            # cannot take its row share elsewhere, so iterate g = q * gas_row(g) (a contraction for q < 1)
            denom = gas_dom if kind == 'dom' else gas_m
            q = min(max(gas_pet[kind], 0.0) / denom, 1.0) if denom > 0 else 0.0
            g = 0.0
            for _ in range(500):
                o = fill(cell - min(g, cell))
                gas_row = float(r[inner].sum() - o[inner].sum())
                g_new = q * max(gas_row, 0.0)
                if abs(g_new - g) <= 1e-12 * max(1.0, abs(g)):
                    break
                g = g_new
            oil = fill(cell - min(g_new, cell))
            gas_row = float(r[inner].sum() - oil[inner].sum())
            info[f'gas_pet_share_{kind}'] = q
            info[f'gas_pet_capped_{kind}'] = bool(q * gas_row > cell + 1e-12)
            info[f'gas_pet_io_{kind}'] = cell - float(oil[pet_col])
            info[f'gas_row_io_{kind}'] = gas_row
        if oil_users is not None:
            info[f'oil_direct_{kind}'] = float(sum(oil[u] for u in oil_users if u in rest_cols))
            info[f'oil_share_to_gas_{kind}'] = float(max(total_oil - oil[inner].sum(), 0.0))   # the row's oil share left to gas
        new_rows[f'{kind}_oil'], new_rows[f'{kind}_gas'] = oil, r - oil

    # columns: own cells follow the row; the others split so column total = row total per sector
    col = io_r['B06'].astype(float)
    own_rows = ['dom_B06', 'imp_B06']
    other = col.drop(index=own_rows + ['OUT'])
    out_b06 = float(col['OUT'])
    own_oil = new_rows['dom_oil']['B06'] + new_rows['imp_oil']['B06']
    own_gas = new_rows['dom_gas']['B06'] + new_rows['imp_gas']['B06']
    r_oil = float(new_rows['dom_oil'].sum())
    r_tot = float(io_r.loc['dom_B06', users].astype(float).sum())
    out_oil = out_b06 * (r_oil / r_tot) if r_tot > 0 else out_b06 * s_dom
    s_col = (out_oil - own_oil) / (out_b06 - own_oil - own_gas) if abs(out_b06 - own_oil - own_gas) > 1e-12 else s_dom
    s_col = float(min(max(s_col, 0.0), 1.0))
    info['s_col'] = s_col
    oil_c = pd.Series(0.0, index=io_r.index)
    gas_c = pd.Series(0.0, index=io_r.index)
    oil_c[other.index] = other * s_col
    gas_c[other.index] = other * (1 - s_col)
    oil_c['OUT'], gas_c['OUT'] = out_oil, out_b06 - out_oil

    out = io_r.copy()
    out = out.drop(index=own_rows)
    add = pd.DataFrame({k: v for k, v in new_rows.items()}).T
    for kind in ('dom', 'imp'):        # the OUT column keeps io_s10's value, split by the row totals (zero on imp rows)
        o, t = float(io_r.loc[f'{kind}_B06', 'OUT']), float(io_r.loc[f'{kind}_B06', users].astype(float).sum())
        sh = float(new_rows[f'{kind}_oil'].sum()) / t if t != 0 else (s_dom if kind == 'dom' else s_m)
        add.loc[f'{kind}_oil', 'OUT'], add.loc[f'{kind}_gas', 'OUT'] = o * sh, o - o * sh
    out = pd.concat([out, add[out.columns]])
    # own-use cells: oil row -> oil column, gas row -> gas column
    for kind in ('dom', 'imp'):
        oil_c[f'{kind}_oil'], gas_c[f'{kind}_oil'] = new_rows[f'{kind}_oil']['B06'], 0.0
        oil_c[f'{kind}_gas'], gas_c[f'{kind}_gas'] = 0.0, new_rows[f'{kind}_gas']['B06']
    out['oil'] = oil_c.reindex(out.index).fillna(0.0)
    out['gas'] = gas_c.reindex(out.index).fillna(0.0)
    for kind in ('dom', 'imp'):
        out.loc[f'{kind}_oil', 'oil'] = new_rows[f'{kind}_oil']['B06']
        out.loc[f'{kind}_gas', 'gas'] = new_rows[f'{kind}_gas']['B06']
        out.loc[f'{kind}_oil', 'gas'] = 0.0
        out.loc[f'{kind}_gas', 'oil'] = 0.0
    out = out.drop(columns=['B06'])
    info['own_oil'], info['own_gas'] = own_oil, own_gas
    return out, info
