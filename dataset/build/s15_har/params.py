"""S15 behavioural parameters (gsdfpar.har). Default edition: GTAP 12 Data Base ch.16 (Hertel, van der Mensbrugghe
and Aguiar; docs/gtap_method_sources/GTAP12_ch16_behavioral_parameters.txt); alternative: GTAP 7 Data Base ch.14
(docs/gtap_method_sources/gtap7ch14.pdf). The edition is the s15 choice `parameters` (s15_har/config.py EDITIONS).

- ESBD, ESBM, ESBV by sector: Table 16.2 (Table 14.2 in GTAP 7): sigma D and sigma M from Hertel et al. 2003, with
  sigma M = 2 sigma D; sigma VA from SALTER. A sector that covers several GTAP sectors takes the unweighted mean
  of their values (the rule of the public build, earlier-build/build/elasticities.jl on main). Same value in
  every region.
- ESBT = ESBC = 0 (ch.16.B and ch.14.2: "The default setting of the elasticity is zero"), ETRQ, ESBQ, ESBG, ESBS,
  RFLX, RDLT, ETRE and EFLG: the GTAP standard settings (ch.16.C: labour and capital mobile, land sluggish; ch.16.D:
  RORDELTA 1 with RORFLEX > 0). Natural resources are fixed by sector, as in the standard GTAP files (EFLG natlres = sluggish 0,
  mobile 0, fixed 1; choice natres_mobility). The values are in config/s15/s15_scalars.csv.
- INCP, SUBP: the CDE calibration of ch.16.E (ch.14.5-14.6 in GTAP 7). Targets are the income elasticities
  (Table 16.6; 14.5) and the own-price elasticities (Table 16.7; 14.6) for the 10 commodity categories of Table
  16.4 (14.3). Expansion (INCPAR = e) and substitution (SUBPAR = 1 - alpha) parameters are solved on this data
  base's household shares; every commodity in a category takes the category's parameters, as GTAP does ("all
  in-group commodities have the same parameter estimates as their aggregated parents").

CDE elasticities (Hertel et al. 1991; ch.16.E.1 and ch.14.6 with alpha = 1 - SUBPAR), at shares s:
  income:                 eta_i = [e_i (1 - alpha_i) + sum_k s_k e_k alpha_k] / sum_k s_k e_k + alpha_i - sum_k s_k alpha_k
  compensated own-price:  c_i   = s_i (2 alpha_i - sum_k s_k alpha_k) - alpha_i
  uncompensated:          u_i   = c_i - s_i eta_i  (Slutsky)

Own-price reading. GTAP 12 Table 16.7 is titled "Compensated Own-price Demand Elasticities" (ch.16.E computes
the compensated values from the Frisch-LES uncompensated ones), so its values are compensated magnitudes:
c_i = -value (choice cde_price_reading = table_16_7_compensated_as_titled). GTAP 7 Table 14.6 is titled
"Target Uncompensated Own-Price Elasticities", but its values fit GTAP 7's own construction (ch.14.5, one Frisch
parameter per region) only as compensated magnitudes: |u| >= s eta always, and USA HousOthServ prints 0.42 where
that bound needs 0.78 (S15 QA B1). David chose the compensated reading for it too (S15 card, 2026-10-24).
'uncompensated' keeps the GTAP 7 title's reading.
"""
import numpy as np
import pandas as pd

CATEGORIES = ['GrainCrops', 'MeatDairy', 'OthFoodBev', 'TextAppar', 'HousUtils', 'WRTrade', 'Mnfcs',
              'TransComm', 'FinService', 'HousOthServ']
# Table 14.5/14.6 print Romania as ROA (GTAP 7); Tables 16.6/16.7 code Palestine PSE where S01 has PAL (GTAP 12).
# The alias of the edition in use is passed in (config.EDITIONS); this default is the GTAP 7 one.
TARGET_ALIASES = {'ROA': 'ROU'}
ALPHA_MIN, ALPHA_MAX, E_MIN = 1e-6, 1 - 1e-6, 1e-6
# Fix list A11 (Grok-F6, QA#10): INCP is floored at 1e-6 after the normalisation sum s e = 1. The fit drives
# e to about 1e-17 where a category's income and own-price targets cannot both hold (GrainCrops in most high-income
# regions). A floor is sensible, but no GTAP rule documents one (David's fact-check, 2026-10-24): our choice
# (choice incp_floor). The income elasticities are homogeneous of degree 0 in e, so the floor moves eta by about 1e-6.
INCP_FLOOR = 1e-6
# Weight of the ridge toward e = 1 in the sequential INCPAR step (David, 2026-10-25, "sequential fit, no cap").
# Our choice: GTAP's program (Liu, Surry et al. 1999) regularises with maximum entropy instead. INCP max is 2.80-2.86
# for any weight from 1e-4 to 1e-2 on the 2022 shares.
INCP_RIDGE = 1e-3


def sector_elasticities(sector_map, table):
    """DataFrame indexed by sector: esubd, esubm, esubva (unweighted means of the GTAP members), and the
    CDE category. sector_map has columns sector, members, cde_category; table has code, esubd, esubm, esubva
    (config.edition_tables). Raises on an unknown member code or category."""
    t = table.set_index('code')
    rows = []
    for r in sector_map.itertuples():
        mem = r.members.split()
        miss = [m for m in mem if m not in t.index]
        if miss:
            raise ValueError(f'{r.sector}: GTAP members {miss} not in the elasticity table')
        if r.cde_category not in CATEGORIES:
            raise ValueError(f'{r.sector}: CDE category {r.cde_category}')
        sub = t.loc[mem]
        rows.append(dict(sector=r.sector, esubd=round(sub['esubd'].mean(), 4), esubm=round(sub['esubm'].mean(), 4),
                         esubva=round(sub['esubva'].mean(), 4), cde_category=r.cde_category, members=r.members))
    return pd.DataFrame(rows).set_index('sector')


def target_regions(regions, targets, rows, aliases=None):
    """Which target-table row(s) each region uses (Tables 16.6/16.7, or 14.5/14.6 in GTAP 7).

    A single economy with its own row uses it. Every other region uses the row the edition's target-row table
    names: the GTAP composite region that held it (GTAP applied a composite's targets to its members), or, for a
    composite whose members have rows of their own, the unweighted mean of those rows (several codes separated by
    spaces). Composites always go through the table, because a code such as XEF or XNF names a different region
    here than in GTAP. aliases maps a table code to the S01 code (e.g. PSE -> PAL)."""
    aliases = TARGET_ALIASES if aliases is None else aliases
    have = {aliases.get(c, c) for c in targets['target_region'].unique()}
    rev = {v: k for k, v in aliases.items()}
    tab = rows.set_index('region')
    out, bad = [], []
    for r in regions.itertuples():
        if r.type == 'single' and r.region in have:
            if r.region in tab.index:
                bad.append(f'{r.region}: has its own row and a cde_target_rows entry')
            out.append(dict(region=r.region, target_row=rev.get(r.region, r.region), rule='own_row', note=''))
        elif r.region in tab.index:
            tr = tab.loc[r.region, 'target_row']
            miss = [c for c in tr.split() if c not in set(targets['target_region'])]
            if miss:
                bad.append(f'{r.region}: target rows {miss} not in the target tables')
            out.append(dict(region=r.region, target_row=tr, rule='gtap_composite' if len(tr.split()) == 1 else 'mean_of_member_rows',
                            note=tab.loc[r.region, 'note']))
        else:
            bad.append(f'{r.region}: no own row and no cde_target_rows entry')
    extra = sorted(set(tab.index) - set(regions['region']))
    bad += [f'{x}: cde_target_rows entry for a region not in S01' for x in extra]
    if bad:
        raise ValueError('; '.join(bad))
    return pd.DataFrame(out).set_index('region')


def cde_elasticities(s, alpha, e):
    """Income, compensated and uncompensated own-price elasticities of the CDE at shares s."""
    s, alpha, e = (np.asarray(x, float) for x in (s, alpha, e))
    sa = s @ alpha
    se = s @ e
    eta = (e * (1 - alpha) + s @ (e * alpha)) / se + alpha - sa
    comp = s * (2 * alpha - sa) - alpha
    return eta, comp, comp - s * eta


def _exact(s, eta, comp):
    """Solve the two linear systems for alpha and e (normalised so that sum s e = 1)."""
    A = np.diag(2 * s - 1) - np.outer(s, s)
    alpha = np.linalg.solve(A, comp)
    B = np.diag(1 - alpha) + np.outer(np.ones_like(s), s * alpha)
    e = np.linalg.solve(B, eta - alpha + s @ alpha)
    return alpha, e


def _bvls(A, b, lo, hi, iters=500):
    """min |A x - b| with lo <= x <= hi: bounded-variable least squares (Lawson and Hanson 1974 ch.23; Stark and
    Parker 1995), one variable released per pass. The problems here have at most 10 unknowns."""
    n = A.shape[1]
    lo = np.broadcast_to(np.asarray(lo, float), n).copy()
    hi = np.broadcast_to(np.asarray(hi, float), n).copy()
    x = np.clip(np.zeros(n), lo, hi)
    free = (x > lo) & (x < hi)
    for _ in range(iters):
        if free.any():                           # minimise over the free set, keeping it feasible
            for _ in range(n + 1):
                z = x.copy()
                z[free] = np.linalg.lstsq(A[:, free], b - A[:, ~free] @ x[~free], rcond=None)[0]
                out = free & ((z <= lo) | (z >= hi))
                if not out.any():
                    x = z
                    break
                d = z - x
                with np.errstate(divide='ignore', invalid='ignore'):
                    t = np.where(d < 0, (lo - x) / d, (hi - x) / d)
                t = np.clip(np.where(out, t, np.inf), 0, 1)
                x = np.clip(x + t.min() * d, lo, hi)
                free &= (x > lo) & (x < hi)
                if not free.any():
                    break
        w = A.T @ (b - A @ x)                    # minus the gradient
        viol = ~free & (((x <= lo) & (w > 1e-12)) | ((x >= hi) & (w < -1e-12)))
        if not viol.any():
            break
        free[int(np.argmax(np.where(viol, np.abs(w), -1)))] = True
    return x


def _sequential(s, eta, comp, ridge=INCP_RIDGE):
    """The ch.16.E order where the exact solution leaves the bounds (choice cde_fit = exact_then_sequential).

    1. SUBPAR: alpha in [ALPHA_MIN, ALPHA_MAX] by bounded least squares on the compensated targets (c is linear in
       alpha: c = (diag(2s - 1) - s s') alpha).
    2. INCPAR: with alpha fixed and sum s e = 1, eta is linear in e (eta = (diag(1 - alpha) + 1 (s alpha)') e
       + alpha - s alpha). e >= E_MIN by bounded least squares on the income targets, plus a weak ridge toward the
       homothetic point e = 1 (Chen 2017 section 3.1 and eq. 10; the earlier project calibration, QA3-01).

    The income targets do not move SUBPAR. A joint fit lets them, and where alpha reaches 1 the income elasticity
    stops depending on e (eta_i moves with e_i (1 - alpha_i)), so e is unidentified and drifts (INCP 19.9 on XWE
    FinService and 0 on half the CHE budget in the joint fit; review 2026-10-25). The ridge picks the solution
    nearest e = 1 in that direction, as GTAP 10 does (uniform INCPAR where SUBPAR is on its bound)."""
    n = len(s)
    A = np.diag(2 * s - 1) - np.outer(s, s)
    alpha = _bvls(A, comp, ALPHA_MIN, ALPHA_MAX)
    M = np.diag(1 - alpha) + np.outer(np.ones(n), s * alpha)
    c = alpha - s @ alpha
    big = 1e3                                    # sum s e = 1 as a heavy row; e is renormalised afterwards
    AA = np.vstack([M, np.sqrt(ridge) * np.eye(n), big * s[None, :]])
    bb = np.concatenate([eta - c, np.sqrt(ridge) * np.ones(n), [big]])
    e = _bvls(AA, bb, E_MIN, np.inf)
    return alpha, e


def calibrate_region(s, eta_target, own_price_magnitude, reading='compensated'):
    """CDE parameters for one region on category shares s (positive, sum 1).

    Returns dict with alpha, e (normalised sum s e = 1), the Engel factor applied to the income targets, the
    compensated targets, the method used ('exact' or 'sequential') and the largest elasticity gaps."""
    s = np.asarray(s, float)
    eta0 = np.asarray(eta_target, float)
    engel = s @ eta0
    eta = eta0 / engel                      # Engel aggregation sum s eta = 1 (targets were set on 2004 shares)
    comp = -np.asarray(own_price_magnitude, float)
    if reading == 'uncompensated':
        comp = comp + s * eta                # Slutsky: c = u + s eta
    elif reading != 'compensated':
        raise ValueError(f'unknown own-price reading {reading!r}')
    method = 'exact'
    alpha, e = _exact(s, eta, comp)
    if not (np.all(alpha > ALPHA_MIN) and np.all(alpha < ALPHA_MAX) and np.all(e > E_MIN)):
        method = 'sequential'
        alpha, e = _sequential(s, eta, comp)
    e = e / (s @ e)
    floored = e < INCP_FLOOR
    e = np.maximum(e, INCP_FLOOR)            # A11: after the normalisation (our choice)
    h, c, u = cde_elasticities(s, alpha, e)
    return dict(alpha=alpha, e=e, engel=engel, eta=eta, comp=comp, method=method, floored=floored,
                eta_gap=float(np.max(np.abs(h - eta))), comp_gap=float(np.max(np.abs(c - comp))),
                eta_model=h, comp_model=c, unc_model=u)


def calibrate_cde(hh, sectors, cats, regions, target_rows, targets, reading='compensated'):
    """INCP and SUBP (COMM x REG arrays) and a per-region, per-category report.

    hh: household purchases at purchasers' prices, array COMM x REG; cats: CDE category of each sector."""
    tg = targets.set_index(['target_region', 'category'])
    cat_idx = {c: i for i, c in enumerate(CATEGORIES)}
    member = np.array([cat_idx[c] for c in cats])
    incp = np.zeros((len(sectors), len(regions)))
    subp = np.zeros_like(incp)
    rep = []
    for j, reg in enumerate(regions):
        sc = np.bincount(member, weights=hh[:, j], minlength=len(CATEGORIES))
        if sc.sum() <= 0:
            raise ValueError(f'{reg}: no household purchases')
        sc = sc / sc.sum()
        row = target_rows.loc[reg, 'target_row']
        eta = np.array([np.mean([tg.loc[(x, c), 'income_elasticity'] for x in row.split()]) for c in CATEGORIES])
        own = np.array([np.mean([tg.loc[(x, c), 'own_price_magnitude'] for x in row.split()]) for c in CATEGORIES])
        pos = sc > 0
        res = calibrate_region(sc[pos], eta[pos], own[pos], reading)
        alpha = np.full(len(CATEGORIES), np.nan)
        e = np.full(len(CATEGORIES), np.nan)
        alpha[pos], e[pos] = res['alpha'], res['e']
        # a category with no household purchases in this region carries the share-weighted mean (no effect on the model)
        alpha[~pos] = sc[pos] @ res['alpha']
        e[~pos] = 1.0
        incp[:, j] = e[member]
        subp[:, j] = 1 - alpha[member]
        k = 0
        for i, c in enumerate(CATEGORIES):
            d = dict(region=reg, category=c, target_row=row, share=sc[i], eta_target=eta[i], own_price_target=-own[i],
                     incpar=e[i], subpar=1 - alpha[i], method=res['method'], engel_factor=res['engel'], incp_floored=False)
            if pos[i]:
                d.update(eta_scaled=res['eta'][k], comp_target=res['comp'][k], eta_model=res['eta_model'][k],
                         comp_model=res['comp_model'][k], unc_model=res['unc_model'][k], incp_floored=bool(res['floored'][k]))
                k += 1
            rep.append(d)
    return incp, subp, pd.DataFrame(rep)
