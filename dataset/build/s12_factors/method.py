"""S12 method, in the GTAP 12 order: labour and capital in value added (the I-O split), agricultural
factor shares (ch.14A), natural resources, the five labour groups (ch.14B eqs. 14.1-14.4) and
income and factor taxes (ch.15). Pure functions on frames and dicts; the stage entry does the I/O.
"""
import numpy as np
import pandas as pd

LABOUR5 = ('off_mgr_pros', 'tech_aspros', 'clerks', 'service_shop', 'ag_othlowsk')
SKILLED = ('off_mgr_pros', 'tech_aspros')            # ISCO 1-3 (ch.14B Table 14.18; Weingarden-Tsigas 2010 p.16)
FACTORS = ('land',) + LABOUR5 + ('capital', 'natres')
NONLAB = ('land', 'capital', 'natres')
SECTIONS = tuple('ABCDEFGHIJKLMNOPQRST')            # ISIC Rev.4 sections that carry our sectors (U has none)


# ------------------------------------------------------------------ labour vs capital (the I-O split)
def section_divisions(concord):
    """section -> sorted ISIC divisions, and sector -> set of divisions, from the S01 ISIC concordance."""
    sec, sct = {}, {}
    for _, r in concord.iterrows():
        if not isinstance(r['sector'], str) or not r['sector']:
            continue
        div = str(r['isic4_code'])[:2]
        sec.setdefault(r['isic4_section'], set()).add(div)
        sct.setdefault(r['sector'], set()).add(div)
    return {k: sorted(v) for k, v in sec.items()}, sct


def labour_shares_from_na(df, sector_divs, section_divs, activity_divisions):
    """Labour share of factor income by sector for one country, from national-accounts rows
    (columns activity, item, value). For each sector the finest activity code that covers all of the
    sector's ISIC divisions and has both D1 and B2A3G is used: share = D1 / (D1 + B2A3G); where codes
    inside the sector cover it exactly (C17 + C18 for pap), their sum is used instead.
    Returns {sector: dict(share, activity, d1, b2a3g, d29, tau, parent, flag)}; a sector no code covers is absent,
    and a sector whose code has neither compensation nor surplus (D1 <= 0 and D1 + B2A3G <= 0) has share None.
    d29 is D29X39 of the same code(s) (0 where the source has none) and tau = D29X39 / (D1 + B2A3G + D29X39),
    the other net production taxes' share of value added (fix round A3). parent is True where the code covers
    more divisions than the sector (FIGARO section B for coa, oil, gas, ore, min and msp; Grok-F2)."""
    piv = df.pivot_table(index='activity', columns='item', values='value', aggfunc='sum')
    codes = []
    for act, r in piv.iterrows():
        if 'D1' not in piv.columns or 'B2A3G' not in piv.columns:
            break
        if pd.isna(r.get('D1')) or pd.isna(r.get('B2A3G')):
            continue
        divs = activity_divisions(act, section_divs)
        if divs:
            d29 = r.get('D29X39') if 'D29X39' in piv.columns else np.nan
            codes.append((act, set(divs), float(r['D1']), float(r['B2A3G']), float(d29) if pd.notna(d29) else 0.0))
    out = {}
    for s, need in sector_divs.items():
        # exact cover by codes inside the sector (largest first, no overlap), e.g. pap = C17 + C18, trd = G45 + G46 + G47
        inside = sorted((c for c in codes if c[1] <= need), key=lambda c: (-len(c[1]), c[0]))
        got, pick = set(), []
        for c in inside:
            if not (c[1] & got):
                pick.append(c)
                got |= c[1]
        if got == need:
            act = '+'.join(c[0] for c in pick)
            d1, b2, d29 = sum(c[2] for c in pick), sum(c[3] for c in pick), sum(c[4] for c in pick)
            parent = False
        else:
            cands = [c for c in codes if need <= c[1]]
            if not cands:
                continue
            act, divs, d1, b2, d29 = min(cands, key=lambda c: (len(c[1]), c[0]))
            parent = len(divs) > len(need)
        tot = d1 + b2
        tau = d29 / (tot + d29) if tot + d29 > 0 else 0.0
        if tot <= 0 and d1 <= 0:
            share, flag = None, 'not_observed'           # no activity in the source: filled from a donor that observes it
        elif tot <= 0:
            share, flag = 1.0, 'nonpositive_factor_income'
        else:
            share, flag = d1 / tot, ''
            if share > 1.0:
                share, flag = 1.0, 'share_above_1_clipped'
            elif share < 0.0:
                share, flag = 0.0, 'share_below_0_clipped'
        out[s] = dict(share=share, activity=act, d1=d1, b2a3g=b2, d29=d29, tau=tau, parent=parent, flag=flag)
    return out


def split_parent(parent, fine, fine_parent):
    """Grok-F2 (fix round A5): a sector the source reports only inside a parent code (parent: dict d1, b2a3g, d29)
    takes the parent's values shared out by a finer source of the same economy: fine holds the finer source's
    values for the sector and fine_parent its values for the parent's divisions, so
    D1_s = D1_parent x D1_s(fine) / D1_parent(fine), and the same for B2A3G and D29X39. Returns (share, tau, d1, b2, d29),
    share clipped to [0, 1], or None where the finer source has no positive parent factor income."""
    def part(k):
        den = fine_parent[k]
        return parent[k] * fine[k] / den if den else 0.0
    if fine_parent['d1'] + fine_parent['b2a3g'] <= 0 or fine_parent['d1'] <= 0:
        return None
    d1, b2, d29 = part('d1'), part('b2a3g'), part('d29')
    tot = d1 + b2
    if tot <= 0:
        return None
    share = min(max(d1 / tot, 0.0), 1.0)
    tau = d29 / (tot + d29) if tot + d29 > 0 else 0.0
    return share, tau, d1, b2, d29


def uniform_blocks(shares_by_code, min_codes=8, tol=1e-3):
    """Codes of one source section whose labour shares are one imputed ratio (FIGARO IND manufacturing: 18 codes
    within 0.0002 of 0.267). shares_by_code: {section: {code: share}}. A section with at least min_codes codes whose
    shares all lie within tol of their median is returned as {section: median}."""
    out = {}
    for sec, d in shares_by_code.items():
        v = np.array([x for x in d.values() if x is not None and np.isfinite(x)])
        if len(v) >= min_codes and np.all(np.abs(v - np.median(v)) <= tol):
            out[sec] = float(np.median(v))
    return out


def rescale_pattern(f_own, lam_donor, d1_total):
    """Shares for the codes of an imputed-uniform block (fix round A5, IND manufacturing): the donor's relative
    pattern lam_donor scaled by one factor so that the block keeps its own compensation total,
    sum_s lam_s x F_s = d1_total (F_s own factor income); each share clipped to [0, 1] and the scale solved again
    over the unclipped codes. f_own, lam_donor: {code: value}. Returns {code: share}."""
    codes = [c for c in f_own if c in lam_donor and f_own[c] > 0]
    lam = {c: 0.0 for c in codes}
    free, rest = set(codes), float(d1_total)
    for _ in range(len(codes) + 1):
        den = sum(lam_donor[c] * f_own[c] for c in free)
        k = rest / den if den > 0 else 0.0
        over = [c for c in free if lam_donor[c] * k > 1.0]
        if not over:
            for c in free:
                lam[c] = lam_donor[c] * k
            break
        for c in over:
            lam[c] = 1.0
            rest -= f_own[c]
            free.discard(c)
    return lam


def gollin_share(lam, slf_over_ees, floor, d1_min=False):
    """Fix round A5 (PLAN.md:508, Gollin 2002 adjustment 2) and A6. lam: D1 / (D1 + B2A3G) of a non-farm cell;
    slf_over_ees: self-employed per employee in the cell's ISIC section (ILOSTAT status in employment), so the
    self-employed earn the employees' average: labour = D1 x (1 + SLF / EES). The labour share is capped at
    1 - floor, floor the capital floor share of factor income (CFC), so a cell keeps at least its capital
    consumption (A6: labour takes the remainder). d1_min (beta v4 G1, choice labour_at_least_d1): the cap never
    takes labour below the observed D1 share, so labour = max(lam, min(adjusted, cap)); a cell whose D1 alone is above
    1 - floor keeps D1 and capital takes the rest (below its CFC). Returns (share, capped)."""
    adj = lam * (1.0 + max(slf_over_ees, 0.0))
    cap = 1.0 - min(max(floor, 0.0), 1.0)
    share, capped = (cap, True) if adj > cap else (adj, False)
    return (max(share, lam), capped) if d1_min else (share, capped)


def gollin_addition(labour, share, share_d1):
    """The part of a cell's labour that the Gollin step added: labour x (1 - share_d1 / share), where share is the
    labour share after the step and share_d1 the D1 share under the same capital-floor cap (never negative)."""
    if share <= 0 or labour <= 0:
        return 0.0
    return max(labour * (1.0 - share_d1 / share), 0.0)


def ilo_cap_return(labour, added, target):
    """Beta v4 G2/P40 (gollin_ilo_cap): the fraction b in [0, 1] of the region's Gollin addition `added` that, returned to
    capital, brings its labour income `labour` down to `target` (ILO share x GDP); 0 when labour is already at or below
    the target, 1 (labour at D1) when even that leaves it above."""
    if labour <= target or added <= 0:
        return 0.0
    return min((labour - target) / added, 1.0)


def region_ilo_share(members, gdp, ilo, min_cover):
    """GDP-weighted ILO SDG 10.4.1 labour income share of a region's members [(code, ...)] with a value, or None when
    those members hold less than min_cover of the members' GDP."""
    tot = sum(gdp.get(m, 0.0) for m in members)
    got = [(ilo[m], gdp.get(m, 0.0)) for m in members if m in ilo and gdp.get(m, 0.0) > 0]
    cov = sum(g for _v, g in got)
    if tot <= 0 or cov < min_cover * tot:
        return None
    return sum(v * g for v, g in got) / cov


def vdep_floor_return(evos_at, target, iters=80):
    """Capital-income floor (capital_vdep_floor): the smallest fraction b in [0, 1] of the region's Gollin addition that,
    returned to capital, gives capital income evos_at(b) >= target; evos_at rises with b. Returns (b, evos_at(b));
    b = 0 when the floor already holds, b = 1 (labour back at D1) when even that leaves capital income below target."""
    e0 = evos_at(0.0)
    if e0 >= target:
        return 0.0, e0
    e1 = evos_at(1.0)
    if e1 < target:
        return 1.0, e1
    lo, hi = 0.0, 1.0
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if evos_at(mid) >= target:
            hi = mid
        else:
            lo = mid
    return hi, evos_at(hi)


def nearest_donor(code, gdppc, pool_of, candidates):
    """GTAP 12 ch.9D §D.3 p.3 step 1: the candidate in the same pool with the nearest GDP per capita
    (absolute log distance; ties to the larger GDP per capita, then the code)."""
    pool = pool_of.get(code)
    cands = [c for c in candidates if c != code and pool_of.get(c) == pool and gdppc.get(c, 0) > 0]
    if not cands or not gdppc.get(code, 0) > 0:
        return None
    t = np.log(gdppc[code])
    return min(cands, key=lambda c: (abs(np.log(gdppc[c]) - t), -gdppc[c], c))


def weighted_member_share(members, share_of, size_of):
    """Region share from member shares: sum w*size*share / sum w*size. members: [(code, weight)].
    share_of(code) -> share or None; size_of(code) -> sector size used as the second weight."""
    num = den = 0.0
    for code, w in members:
        s = share_of(code)
        if s is None:
            return None
        z = w * max(size_of(code), 0.0)
        num += z * s
        den += z
    if den <= 0:
        vals = [share_of(c) for c, _ in members]
        ws = [w for _, w in members]
        return float(np.average(vals, weights=ws)) if sum(ws) > 0 else None
    return num / den


# ------------------------------------------------------------------ agriculture (ch.14A)
def normalise_kf(row):
    tot = row['land'] + row['labor'] + row['capital']
    return dict(land=row['land'] / tot, labour=row['labor'] / tot, capital=row['capital'] / tot)


def sur_fit(y_lab, y_kap, X):
    """ch.14A p.2: SHARE_LAB and SHARE_KAP on (1, log GDP per capita, log arable land per capita), estimated
    as seemingly unrelated regressions. With the same regressors in both equations SUR equals OLS
    equation by equation (Zellner 1962), so OLS is exact here. Returns (beta_lab, beta_kap, sd_lab, sd_kap, n)."""
    X = np.asarray(X, float)
    out = []
    for y in (y_lab, y_kap):
        y = np.asarray(y, float)
        b, *_ = np.linalg.lstsq(X, y, rcond=None)
        e = y - X @ b
        out.append((b, float(np.sqrt(e @ e / max(len(y) - X.shape[1], 1)))))
    return out[0][0], out[1][0], out[0][1], out[1][1], len(y_lab)


def ch14a_sur_prediction(gdppc, arable_pc, coef):
    """GTAP 12 ch.14A p.2 and Table 14.16 (2): SHARE_LAB = b1 + b2 log GDPpc + b3 log LANDpc, SHARE_KAP likewise, land the
    residual. coef: {'labour': (b1, b2, b3), 'capital': (g1, g2, g3)} as shares. A prediction outside [0, 1] is clipped
    and renormalised. Returns (dict(land, labour, capital), clipped)."""
    x = np.array([1.0, np.log(gdppc), np.log(arable_pc)])
    lab, kap = float(x @ np.array(coef['labour'])), float(x @ np.array(coef['capital']))
    s = dict(land=1.0 - lab - kap, labour=lab, capital=kap)
    if min(s.values()) >= 0:
        return s, False
    s = {k: max(v, 0.0) for k, v in s.items()}
    t = sum(s.values())
    return {k: v / t for k, v in s.items()}, True


# ------------------------------------------------------------------ labour groups (ch.14B)
def calibrate_wages(N_occ, N_ind, w_occ, w_ind, beta, N_obs=None):
    """GTAP 12 ch.14B eqs.14.1-14.4.
    N_occ: (9,) workers by ISCO major group; N_ind: (J,) workers by section; w_occ: (9,) occupation wage
    prior (hourly or monthly: the shares do not depend on the unit); w_ind: (J,) observed industry wage,
    NaN where unobserved; beta: (9,) weights. Returns (N_ij, W_ij, S_ij) with S the payment shares
    within each industry (columns sum to 1 where the industry has workers).
    The constraint sum_i W_ij N_ij / sum_i N_ij = w_ind_j is solved in closed form (Lagrange), with
    cells that would go negative fixed at zero and the rest solved again (active set).
    N_obs: an observed (9, J) occupation x industry table used instead of eq.14.1 (logged departure)."""
    N_occ = np.asarray(N_occ, float)
    N_ind = np.asarray(N_ind, float)
    N = np.outer(N_occ, N_ind) / N_occ.sum() if N_obs is None else np.asarray(N_obs, float)   # eq.14.1
    W = np.tile(np.asarray(w_occ, float)[:, None], (1, len(N_ind)))
    for j in range(len(N_ind)):
        if not np.isfinite(w_ind[j]) or N[:, j].sum() <= 0:
            continue
        target = w_ind[j] * N[:, j].sum()
        free = N[:, j] > 0
        w = np.array(w_occ, float)
        for _ in range(10):
            n, b = N[free, j], beta[free]
            mu = (target - n @ np.asarray(w_occ, float)[free]) / (n @ (n / b))
            w = np.zeros(len(w_occ))
            w[free] = np.asarray(w_occ, float)[free] + mu * n / b
            if (w >= -1e-12).all():
                break
            free = free & (w > 0)
            if not free.any():
                break
        W[:, j] = np.maximum(w, 0.0)
    pay = W * N
    col = pay.sum(axis=0)
    S = np.divide(pay, col, out=np.zeros_like(pay), where=col > 0)   # eq.14.4
    return N, W, S


def wage_beta(w_occ, N_occ):
    """Weights: cells whose wage prior is far from the country mean get less weight (ch.14B p.6; the exact
    form is not in the GTAP text): beta_i = mean / (mean + |w_i - mean|), mean employment-weighted."""
    w = np.asarray(w_occ, float)
    m = float(np.average(w, weights=np.asarray(N_occ, float)))
    return m / (m + np.abs(w - m))


def year_window(years, base_year):
    """ch.14B p.6 with the standing year rule (never after the base year): the base year if common;
    else the three latest common years when they are consecutive, else the two latest; one if only one."""
    ys = sorted((y for y in set(years) if y <= base_year), reverse=True)
    if not ys:
        return []
    if ys[0] == base_year:
        return [base_year]
    if len(ys) >= 3 and ys[0] - ys[2] == 2:
        return ys[:3]
    return ys[:2]


# ------------------------------------------------------------------ factor taxes (ch.15)
def factor_taxes(evfp, ssc, payroll_property, pit, cit, support, payroll=0.0, support_wedge='income'):
    """GTAP 12 ch.15 pp.1-3 on one region.
    evfp: frame (sector, factor, evfp). Factor employment taxes: SSC (and, fix round A3, the payroll part of D29,
    `payroll`) on the labour cells, payroll and property (`payroll_property`; zero once D29 is booked, A3) on all
    factor cells, each at one rate across industries, so tax = rate x EVFP (EVFP = EVFB + tax). Income tax: PIT on
    labour, CIT on land, capital and natural resources, pro rata to EVFB before support.
    Land-, capital- and labour-based support (ch.15 p.3, FBEP memo) on the crp cells:
      support_wedge 'factor_use' (fix round A4, GTAP): a factor-use subsidy, ftax lowered by FBEP, so EVFB = EVFP + FBEP
        and EVFP < EVFB on the supported cells; EVOS is the same as under 'income';
      support_wedge 'income' (before the fix round): a negative income tax, itax lowered by FBEP;
      support_wedge 'land_factor_use' (Fable QA F-05): land-based support as under 'factor_use' (ch.13D), capital-,
        labour- and all-factor-based support as under 'income' (ch.15 p.3).
    Returns the frame with evfb, ftax, itax, fbep, evos."""
    df = evfp.copy()
    lab = df['factor'].isin(LABOUR5)
    tot_l, tot = df.loc[lab, 'evfp'].sum(), df['evfp'].sum()
    r_ssc = ssc / tot_l if tot_l > 0 else 0.0
    r_pay = payroll / tot_l if tot_l > 0 else 0.0
    r_pp = payroll_property / tot if tot > 0 else 0.0
    df['ftax'] = df['evfp'] * r_pp + np.where(lab, df['evfp'] * (r_ssc + r_pay), 0.0)
    df['evfb'] = df['evfp'] - df['ftax']
    lb, nb = df.loc[lab, 'evfb'].sum(), df.loc[~lab, 'evfb'].sum()
    df['itax'] = np.where(lab, df['evfb'] * (pit / lb if lb > 0 else 0.0), df['evfb'] * (cit / nb if nb > 0 else 0.0))
    df['fbep'] = 0.0
    land_fbep = np.zeros(len(df))
    for cls, val in support.items():
        if val == 0:
            continue
        if cls == 'labour':
            m = (df['sector'] == 'crp') & lab
        elif cls in ('land', 'capital'):
            m = (df['sector'] == 'crp') & (df['factor'] == cls)
        else:                                            # 'factors': all crp factors
            m = df['sector'] == 'crp'
        base = df.loc[m, 'evfb'].sum()
        if base > 0:
            df.loc[m, 'fbep'] += val * df.loc[m, 'evfb'] / base
            if cls == 'land':
                land_fbep += np.where(m, val * df['evfb'] / base, 0.0)
    if support_wedge == 'factor_use':
        df['ftax'] -= df['fbep']
        df['evfb'] = df['evfp'] - df['ftax']
    elif support_wedge == 'income':
        df['itax'] -= df['fbep']
    elif support_wedge == 'land_factor_use':
        # Fable QA F-05 / A-06: land-based support (area payments, the ch.13D EU decoupled payments) is a land factor-use
        # subsidy (EVFB = EVFP + support), so the land income-tax rate is the CIT rate; the rest a negative income tax
        df['ftax'] -= land_fbep
        df['evfb'] = df['evfp'] - df['ftax']
        df['itax'] -= df['fbep'] - land_fbep
    else:
        raise ValueError(f'support_wedge {support_wedge!r}')
    df['evos'] = df['evfb'] - df['itax']
    return df, dict(r_ssc=r_ssc, r_pp=r_pp, r_pay=r_pay, fbep_land=float(land_fbep.sum()))


LAND_ITAX_FLOOR_SHARE = 0.01   # the same floor as s13_fit.method.EVOS_FLOOR_SHARE: a land cell keeps 1% of its rent as EVOS


def cap_land_income_tax(df, floor_share=LAND_ITAX_FLOOR_SHARE):
    """Round-3 final QA item 7 (s12 choice land_income_tax_cap): the income tax on a land cell (the CIT share, pro rata
    to EVFB) is at most (1 - floor_share) of the land rent EVFP less the cell's positive factor-use tax, so the cell's
    operating surplus stays at least floor_share of its rent (GTAP 12 ch.17B p.3: no sign violation; the floor is
    the one S13 cap_held_factor_taxes uses). The excess is dropped (not moved to other factors) and returned for the
    ledger. df: one region's factor_taxes frame (evfp, ftax, evfb, itax, fbep, evos). Returns (df, [(sector, before,
    after)])."""
    df = df.copy()
    land = (df['factor'] == 'land') & (df['evfp'] > 0)
    cap = (1.0 - floor_share) * df['evfp'] - df['ftax'].clip(lower=0.0)
    over = land & (df['itax'] > cap.clip(lower=0.0) * (1 + 1e-12)) & (df['itax'] > 1e-12)
    out = [(str(x.sector), float(x.itax), float(max(c, 0.0))) for x, c in zip(df[over].itertuples(), cap[over])]
    df.loc[over, 'itax'] = cap[over].clip(lower=0.0)
    df['evos'] = df['evfb'] - df['itax']
    return df, out


def output_tax(va, tau, payroll, pse_booked=0.0):
    """Fix round A3 (GTAP: other production taxes are output and factor-use taxes). va: the cell's io value added;
    tau: D29X39 / VA of the cell's source; payroll: the cell's share of the payroll part of D29, booked as a
    factor-use tax on labour; pse_booked: PSE support the stage books elsewhere (output support in S13, land,
    capital, labour and all-factor support as factor-use subsidies), which D39 already holds for crp: it is added
    back, at most up to the cell's net subsidy, so it is booked once. Returns (otp, factor_cost, output_tax, addback):
    otp = tau x VA (net other production taxes inside VA); factor_cost = VA - otp - addback, the factor payments
    before the payroll part; output_tax = otp + addback - payroll. factor_cost + payroll + output_tax = VA."""
    otp = tau * va
    addback = min(max(pse_booked, 0.0), max(-otp, 0.0))
    otp_b = otp + addback
    return otp, va - otp_b, otp_b - payroll, addback


# ------------------------------------------------------------------ natural resources (fix round B16, ch.12.A)
def natres_target_share(fva, cost, eta, sigma, theta_floor):
    """GTAP 7 ch.12.A pp.2-3 (GTAP 6 ch.18.C; GTAP 12 ch.17B §B.1). With sigma_T = 0 the partial-equilibrium supply
    elasticity of an activity with a fixed natural resource is eta = sigma_VA (1/theta_R - 1/theta_VA), theta_R and theta_VA
    the cost shares of the resource and of value added, so theta_R = 1 / (eta / sigma_VA + 1 / theta_VA) and the resource
    share of value added is theta_R / theta_VA = sigma_VA / (eta theta_VA + sigma_VA), below one for any theta_VA > 0.
    fva: the cell's factor value added (EVFP); cost: its cost (output less the output tax). Guard (config natres_guard, our
    choice): where theta_VA < theta_floor, or the cost is not positive, the share is the one at theta_VA = theta_floor.
    Returns dict(share, theta_va, theta_va_used, guard); share 0 where fva <= 0."""
    if not fva > 0:
        return dict(share=0.0, theta_va=np.nan, theta_va_used=np.nan, guard=False)
    th = fva / cost if cost > 0 else np.nan
    guard = not (th >= theta_floor)
    used = theta_floor if guard else th
    return dict(share=sigma / (eta * used + sigma), theta_va=th, theta_va_used=used, guard=guard)


def implied_eta(natres, fva, cost, sigma):
    """ch.12.A eq.(3) with sigma_T = 0: eta = sigma_VA (1/theta_R - 1/theta_VA) = sigma_VA cost (1/natres - 1/fva)."""
    if not (natres > 0 and fva > 0 and cost > 0):
        return np.nan
    return sigma * cost * (1.0 / natres - 1.0 / fva)


def msp_oil_gas_weight(ext):
    """Fix round w13: the share of mining support (msp, ISIC 09) that serves oil and gas extraction (ISIC 0910, which GTAP
    puts in oil and gas; GTAP 12 ch.2 Table 2.11 note), taken as the oil and gas share of the region's extraction output
    ext = {coa, oil, gas, ore, min: output}. Our choice: no source splits ISIC 09 by class. 0 where nothing is extracted."""
    tot = sum(max(v, 0.0) for v in ext.values())
    return (max(ext.get('oil', 0.0), 0.0) + max(ext.get('gas', 0.0), 0.0)) / tot if tot > 0 else 0.0


def msp_blend(share_oil_gas, share_other, w, sigma, theta_va_used):
    """Fix round w13: the msp natural-resource share of VA, w x the fossil-fuel target share (0910 part) + (1 - w) x the
    other-mining target share (0990 part), both at the cell's theta_VA. Returns (share, eta_effective), eta_effective the
    supply elasticity the blended share gives (ch.12.A eq.3 with sigma_T = 0): sigma (1/share - 1) / theta_VA."""
    w = min(max(w, 0.0), 1.0)
    share = w * share_oil_gas + (1.0 - w) * share_other
    return share, sigma * (1.0 / share - 1.0) / theta_va_used


# ------------------------------------------------------------------ USA other production taxes from BEA (fix worker wD)
def bea_group_tau(bea, bea_map, va_s, sectors):
    """Independent QA MEDIUM-1: the USA D29X39 share of VA by sector from the BEA supply-use table.
    bea: rows of one year (industry_code, T00OTOP, T00OSUB); bea_map: {industry_code: tuple of sectors} (empty for the
    government industries, to which BEA books no other taxes on production); va_s: {sector: io value added}. BEA
    industries and our sectors that share a code form a group (connected components); each group's net other taxes on
    production (T00OTOP - T00OSUB) is spread over its sectors pro rata to io value added, so every sector of the group
    takes tau = group net / group io VA. A sector no BEA code reaches takes 0. Returns (tau, groups), groups a list of
    dict(codes, sectors, net_musd, va_musd, tau). Raises SystemExit on a BEA code missing from the map or a mapped
    sector that is not one of ours."""
    codes = list(bea['industry_code'])
    miss = [c for c in codes if c not in bea_map]
    bad = sorted({s for c in codes for s in bea_map.get(c, ()) if s not in sectors})
    if miss or bad:
        raise SystemExit(f'BEA map: codes not mapped {miss}; sectors not in the sector list {bad}')
    parent = {s: s for s in sectors}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for c in codes:
        ss = bea_map[c]
        for s in ss[1:]:
            parent[find(s)] = find(ss[0])
    net = (bea['T00OTOP'] - bea['T00OSUB']).astype(float).values
    grp = {}
    for c, n in zip(codes, net):
        ss = bea_map[c]
        if not ss:
            continue
        g = grp.setdefault(find(ss[0]), dict(codes=[], net_musd=0.0))
        g['codes'].append(c)
        g['net_musd'] += float(n)
    tau, groups = {s: 0.0 for s in sectors}, []
    for root, g in sorted(grp.items()):
        ss = [s for s in sectors if find(s) == root]
        v = sum(max(float(va_s.get(s, 0.0)), 0.0) for s in ss)
        t = g['net_musd'] / v if v > 0 else 0.0
        for s in ss:
            tau[s] = t
        groups.append(dict(codes=' '.join(g['codes']), sectors=' '.join(ss), net_musd=g['net_musd'], va_musd=v, tau=t))
    return tau, groups


def scale_positive_d29(values, target):
    """Fix worker wD (JPN): an economy whose activity-level D29X39 holds taxes on products (JSNA records GVA by
    activity with the consumption tax and excises in it) is brought to its national net other production taxes, target
    (D29 less D39, in the units of values), by scaling its positive D29X39 cells by one factor; the negative cells (net
    subsidies) are kept as published. values: D29X39 by leaf activity. Returns (scaled values, factor, pos, neg).
    Raises SystemExit unless 0 < factor <= 1 (the fix only removes product taxes; it never adds D29)."""
    v = np.asarray(values, float)
    pos, neg = float(v[v > 0].sum()), float(v[v < 0].sum())
    k = (target - neg) / pos if pos > 0 else np.nan
    if not (k > 0 and k <= 1.0 + 1e-12):
        raise SystemExit(f'D29X39 national total {target:.1f}: positive-cell factor {k} outside (0, 1] (pos {pos:.1f}, neg {neg:.1f})')
    return np.where(v > 0, v * k, v), k, pos, neg


# ------------------------------------------------------------------ fix worker wF (QA round 2 P2, P6)
def crp_beyond_pse_cap(otp, addback):
    """QA round 2 P2 (GTAP 12 ch.11A: farm support is the OECD PSE budgetary transfers). otp: tau x VA of the crp cell;
    addback: the PSE support booked elsewhere and added back (output_tax). Where the source is a modelled estimate (a
    FIGARO economy outside the EU), a net subsidy left after the add-back is not an observed policy: it is removed, so
    the output tax is max(otp + addback, 0). Returns the amount removed (>= 0)."""
    return max(-(otp + addback), 0.0)


def donor_tau(tau, on=True):
    """QA round 2 P2b (GTAP 12 ch.9D: a donor supplies structure, not a policy wedge): a D29X39 share of VA passed by a
    donor is never a net subsidy. Returns max(tau, 0) when on, else tau (None stays None)."""
    if tau is None or not on:
        return tau
    return max(float(tau), 0.0)


def d29_reference(taus):
    """QA round 2 P6: {sector: [D29X39 / VA of the national-source economies]} -> {sector: (p5, median, p95)}."""
    out = {}
    for s, v in taus.items():
        v = np.asarray([x for x in v if x is not None and np.isfinite(x)], float)
        if len(v):
            out[s] = (float(np.percentile(v, 5)), float(np.median(v)), float(np.percentile(v, 95)))
    return out


def d29_cell_target(tau, duty_share, ref, crp):
    """QA round 2 P6 (listed FIGARO-estimated cells). tau: the source cell's D29X39 / VA; duty_share: S10 export duty on
    the sector over its io VA (0 unless the cell is listed with export_duty_out), taken out first because export duties
    are taxes on products (SNA D2122), which S10 books as the export tax; ref: (p5, median, p95) of the national-source
    economies in the sector. A share still outside [p5, p95] is a balancing artefact of the estimate and takes the
    national-source median, except crp, which takes 0 (ch.11A: farm support from the PSE only). Returns (tau, rule)."""
    t1 = tau - duty_share
    lo, med, hi = ref
    if lo - 1e-12 <= t1 <= hi + 1e-12:
        return t1, ('export_duty_out' if duty_share else 'kept_inside_range')
    return (0.0, 'crp_zero') if crp else (med, 'national_source_median')


def d29_for_share(d1, b2a3g, tau):
    """D29X39 that gives tau = D29X39 / (D1 + B2A3G + D29X39) with D1 and B2A3G kept, so the labour share
    D1 / (D1 + B2A3G) does not change. Raises ValueError unless tau < 1."""
    if not tau < 1.0:
        raise ValueError(f'D29X39 share {tau} must be below 1')
    return tau * (d1 + b2a3g) / (1.0 - tau)
