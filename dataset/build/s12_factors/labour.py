"""Country labour-payment shares by ISIC section and GTAP labour group (GTAP 12 ch.14B).

The four ILOSTAT series are employment by occupation, employment by industry, earnings by occupation
and earnings by industry (Table 14.17). A country enters only when all four share a year window
(ch.14B p.6); otherwise it is excluded here and the stage fills it (F16c).
"""
import numpy as np
import pandas as pd

from .method import LABOUR5, SECTIONS, calibrate_wages, wage_beta, year_window

MIN_OCC = 6          # major groups with workers
MIN_OCC_WAGE = 5     # major groups with an earnings observation
MIN_IND_WAGE = 5     # sections with an earnings observation


def pick_source(df):
    """One source per country, year and series: the household labour force survey (code BA) when present,
    else the source with the most categories, then the larger total, then the code (not in the GTAP text)."""
    g = df.groupby(['iso3', 'year', 'source']).agg(n=('code', 'nunique'), tot=('value', 'sum')).reset_index()
    g['ba'] = g['source'].str.startswith('BA').astype(int)
    g = g.sort_values(['iso3', 'year', 'ba', 'n', 'tot', 'source'], ascending=[True, True, False, False, False, True])
    keep = g.groupby(['iso3', 'year']).head(1)[['iso3', 'year', 'source']]
    return df.merge(keep, on=['iso3', 'year', 'source'])


def pick_isco(df):
    """ISCO-08 where a country-year has it, else ISCO-88 major groups taken one to one."""
    has08 = df[df['cls'] == 'ISCO08'][['iso3', 'year']].drop_duplicates().assign(h=1)
    df = df.merge(has08, on=['iso3', 'year'], how='left')
    df = df[(df['cls'] == 'ISCO08') | df['h'].isna()].drop(columns='h')
    return df


def _vec(df, codes):
    s = df.groupby('code')['value'].mean()
    return np.array([s.get(c, np.nan) for c in codes], float)


def country_shares(occ, ind, wocc, wind, groups9, base_year, cross=None):
    """Returns (shares, meta). shares: frame iso3, section, group, share (sum over groups = 1 per section).
    meta: frame iso3, years, isco, n_occ, n_occ_wage, n_ind_wage, flags, status (used / excluded reason).
    cross: observed occupation x section employment; when given, a country with a cross table in the
    window uses it as N_ij instead of eq.14.1 (its own margins), and the meta row says so."""
    occ, wocc = pick_isco(pick_source(occ)), pick_isco(pick_source(wocc))
    if cross is not None:
        cross = pick_isco(pick_source(cross.assign(code=cross['code'] + cross['section'])).assign(code=lambda d: d['code'].str[0]))
    ind, wind = pick_source(ind), pick_source(wind)
    occ9 = [str(i) for i in range(1, 10)]
    out, meta = [], []
    yrs = {k: set(map(tuple, d[['iso3', 'year']].drop_duplicates().values)) for k, d in
           (('o', occ), ('i', ind), ('wo', wocc), ('wi', wind))}
    countries = sorted(set(occ['iso3']) | set(ind['iso3']))
    for c in countries:
        common = [y for (cc, y) in yrs['o'] if cc == c and (c, y) in yrs['i'] and (c, y) in yrs['wo'] and (c, y) in yrs['wi']]
        win = year_window(common, base_year)
        if not win:
            meta.append(dict(iso3=c, years='', isco='', status='excluded: no common window of the four series'))
            continue
        sel = lambda d: d[(d['iso3'] == c) & d['year'].isin(win)]
        o, i, wo, wi = sel(occ), sel(ind), sel(wocc), sel(wind)
        # average over the window (ch.14B p.6): mean of each cell over the years it is observed
        N_occ = np.nan_to_num(_vec(o, occ9))
        N_ind = np.nan_to_num(_vec(i, SECTIONS))
        w_occ = _vec(wo, occ9)
        w_ind = _vec(wi, SECTIONS)
        flags = []
        n_occ = int((N_occ > 0).sum())
        n_ow = int((np.isfinite(w_occ) & (N_occ > 0)).sum())
        n_iw = int((np.isfinite(w_ind) & (N_ind > 0)).sum())
        rec = dict(iso3=c, years=' '.join(map(str, win)), isco=','.join(sorted(set(o['cls']))), n_occ=n_occ,
                   n_occ_wage=n_ow, n_ind_wage=n_iw)
        if n_occ < MIN_OCC or n_ow < MIN_OCC_WAGE or n_iw < MIN_IND_WAGE or N_ind.sum() <= 0:
            meta.append(dict(rec, status=f'excluded: too few cells (occ {n_occ}, occ wages {n_ow}, industry wages {n_iw})'))
            continue
        miss = (N_occ > 0) & ~np.isfinite(w_occ)
        if miss.any():
            fill = float(np.average(w_occ[~miss & (N_occ > 0)], weights=N_occ[~miss & (N_occ > 0)]))
            flags.append('occ_wage_missing_' + '+'.join(np.array(occ9)[miss]) + '_country_mean')
            w_occ = np.where(miss, fill, w_occ)
        w_occ = np.where(N_occ > 0, w_occ, 0.0)
        dropped = [s for s, n, w in zip(SECTIONS, N_ind, w_ind) if n > 0 and not np.isfinite(w)]
        if dropped:
            flags.append('industry_wage_missing_' + '+'.join(dropped) + '_constraint_dropped')
        N_obs, nmode = None, 'eq14.1'
        if cross is not None:
            x = cross[(cross['iso3'] == c) & cross['year'].isin(win)]
            if len(x):
                t = x.groupby(['code', 'section', 'year'])['value'].sum().groupby(['code', 'section']).mean()
                M = np.array([[t.get((o9, s), 0.0) for s in SECTIONS] for o9 in occ9])
                if M.sum() > 0 and (M.sum(axis=1) > 0).sum() >= MIN_OCC:
                    N_obs, nmode = M, 'observed cross table'
                    gap = (M.sum(axis=1) > 0) & (w_occ <= 0)
                    if gap.any():
                        w_occ = np.where(gap, float(np.average(w_occ[w_occ > 0], weights=N_occ[w_occ > 0])), w_occ)
                        flags.append('occ_wage_missing_cross_' + '+'.join(np.array(occ9)[gap]) + '_country_mean')
                    N_occ, N_ind = M.sum(axis=1), M.sum(axis=0)
                    w_occ = np.where(N_occ > 0, w_occ, 0.0)
        rec['n_matrix'] = nmode
        out += _calibrated_shares(c, N_occ, N_ind, w_occ, w_ind, N_obs, groups9, flags)
        meta.append(dict(rec, flags=';'.join(sorted(set(flags))), status='used'))
    return pd.DataFrame(out), pd.DataFrame(meta)


def _calibrated_shares(c, N_occ, N_ind, w_occ, w_ind, N_obs, groups9, flags):
    """eqs.14.1-14.4 for one country and the five-group payment shares by section (a section without workers takes
    the national shares; flagged)."""
    beta = np.where(N_occ > 0, wage_beta(np.where(N_occ > 0, w_occ, 1.0), np.maximum(N_occ, 1e-12)), 1.0)
    N, W, S = calibrate_wages(N_occ, N_ind, w_occ, w_ind, beta, N_obs)
    tot_pay = (W * N).sum(axis=1)
    nat = tot_pay / tot_pay.sum()
    out = []
    for j, sec in enumerate(SECTIONS):
        col = S[:, j] if N[:, j].sum() > 0 else nat
        if N[:, j].sum() <= 0:
            flags.append(f'section_{sec}_no_workers_national_shares')
        for g in LABOUR5:
            out.append(dict(iso3=c, section=sec, group=g,
                            share=float(sum(col[k] for k, gg in enumerate(groups9) if gg == g))))
    return out


def _latest(df, c, base_year, codes):
    """One country's ILOSTAT series in its latest year at or before the base year (one source, ISCO-08 first):
    (vector over codes, NaN where unobserved; year or None)."""
    d = df[(df['iso3'] == c) & (df['year'] <= base_year)]
    if d.empty:
        return np.full(len(codes), np.nan), None
    if 'cls' in d.columns and d['cls'].isin(('ISCO08', 'ISCO88')).any():
        d = pick_isco(pick_source(d))
    else:
        d = pick_source(d)
    y = int(d['year'].max())
    return _vec(d[d['year'] == y], codes), y


PROFILE_MAX_AGE = 5     # an ILOSTAT occupation profile used to share a combined source group is at most this old


def occ_profiles(occ, countries, base_year):
    """ILOSTAT employment by ISCO major group, latest year at or before the base year: {iso3: (9,) shares}, kept only
    where the year is at most PROFILE_MAX_AGE before the base year and all nine groups have workers (a country that
    publishes two groups as one, as JPN does for ISCO 2 and 3, cannot share them out)."""
    occ9 = [str(i) for i in range(1, 10)]
    out = {}
    for c in countries:
        v, y = _latest(occ, c, base_year, occ9)
        v = np.nan_to_num(v)
        if y is not None and y >= base_year - PROFILE_MAX_AGE and (v > 0).all():
            out[c] = v / v.sum()
    return out


def wage_relatives(occ, wocc, countries, base_year):
    """Occupation wage relative to the employment-weighted country mean, latest ILOSTAT year at or before the base
    year: {iso3: (9,) with NaN where unobserved}. Used as the wage prior of a national table without ILOSTAT
    occupation earnings (the regional profile, as F16c takes regional averages)."""
    occ9 = [str(i) for i in range(1, 10)]
    out = {}
    for c in countries:
        w, y = _latest(wocc, c, base_year, occ9)
        n, _ = _latest(occ, c, base_year, occ9)
        ok = np.isfinite(w) & (np.nan_to_num(n) > 0) & (w > 0)
        if y is None or ok.sum() < MIN_OCC_WAGE:
            continue
        m = float(np.average(w[ok], weights=n[ok]))
        out[c] = np.where(ok, w / m, np.nan)
    return out


def national_shares(tabs, wocc, wind, groups9, base_year, wage_prior):
    """GTAP 12 ch.14B with a national employment table (rule F16a; Fable QA B-02).
    tabs: {iso3: dict(N (9 x sections) or None for margins, N_occ, N_ind, year, source)}. Employment is the national
    table (a cross table is N_ij, as labour_matrix observed; margins go through eq.14.1). Wages are ILOSTAT's, the
    latest year at or before the base year: occupation earnings where at least MIN_OCC_WAGE groups are observed (a
    missing group takes the regional relative wage at the country's level), else the regional relative wage profile
    wage_prior[iso3]; industry earnings where at least MIN_IND_WAGE sections are observed, scaled so their
    employment-weighted mean equals the occupation one (the two series can be from different years), else no
    industry constraint. Returns (shares, meta) as country_shares."""
    occ9 = [str(i) for i in range(1, 10)]
    out, meta = [], []
    for c, t in sorted(tabs.items()):
        flags = []
        N_occ, N_ind = np.asarray(t['N_occ'], float), np.asarray(t['N_ind'], float)
        w_occ, yo = _latest(wocc, c, base_year, occ9)
        prior = np.asarray(wage_prior[c], float)
        if not np.isfinite(prior).all():
            flags.append('wage_prior_missing_' + '+'.join(np.array(occ9)[~np.isfinite(prior)]) + '_at_mean')
            prior = np.where(np.isfinite(prior), prior, 1.0)
        obs = np.isfinite(w_occ) & (N_occ > 0) & (np.nan_to_num(w_occ) > 0)
        if obs.sum() >= MIN_OCC_WAGE:
            lvl = float(np.average(w_occ[obs], weights=N_occ[obs]) / np.average(prior[obs], weights=N_occ[obs]))
            miss = (N_occ > 0) & ~obs
            if miss.any():
                flags.append('occ_wage_missing_' + '+'.join(np.array(occ9)[miss]) + '_regional_relative')
            w_occ = np.where(obs, w_occ, prior * lvl)
            wsrc = f'ILOSTAT {yo}'
        else:
            w_occ, wsrc = prior.copy(), 'regional relative wage profile'
            flags.append('occ_wage_regional_profile')
        w_occ = np.where(N_occ > 0, w_occ, 0.0)
        w_ind, yi = _latest(wind, c, base_year, list(SECTIONS))
        ok = np.isfinite(w_ind) & (N_ind > 0) & (np.nan_to_num(w_ind) > 0)
        if ok.sum() >= MIN_IND_WAGE:
            k = float(np.average(w_occ, weights=N_occ) / np.average(w_ind[ok], weights=N_ind[ok]))
            w_ind = np.where(ok, w_ind * k, np.nan)
            isrc = f'ILOSTAT {yi}'
            dropped = [s for s, n, o in zip(SECTIONS, N_ind, ok) if n > 0 and not o]
            if dropped:
                flags.append('industry_wage_missing_' + '+'.join(dropped) + '_constraint_dropped')
        else:
            w_ind, isrc = np.full(len(SECTIONS), np.nan), 'none'
            flags.append('no_industry_wages_occupation_wages_only')
        out += _calibrated_shares(c, N_occ, N_ind, w_occ, w_ind, t['N'], groups9, flags)
        meta.append(dict(iso3=c, years=str(t['year']), isco='national', n_occ=int((N_occ > 0).sum()), n_occ_wage=int(obs.sum()),
                         n_ind_wage=int(ok.sum()), n_matrix='national cross table' if t['N'] is not None else 'national margins, eq14.1',
                         flags=';'.join(sorted(set(flags))), status='used', source=t['source'], occ_wage_source=wsrc, ind_wage_source=isrc))
    return pd.DataFrame(out), pd.DataFrame(meta)


def ras(N, rows, cols, iters=200, tol=1e-10):
    """Biproportional scaling of a non-negative seed to row and column totals (rows rescaled to sum to the column
    total). Returns the scaled matrix; rows or columns with a zero seed stay zero."""
    N = np.asarray(N, float).copy()
    r = np.asarray(rows, float) * (np.sum(cols) / np.sum(rows))
    c = np.asarray(cols, float)
    for _ in range(iters):
        rs = N.sum(axis=1)
        N *= np.divide(r, rs, out=np.ones_like(r), where=rs > 0)[:, None]
        cs = N.sum(axis=0)
        N *= np.divide(c, cs, out=np.ones_like(c), where=cs > 0)[None, :]
        if np.abs(N.sum(axis=1) - r)[N.sum(axis=1) > 0].max(initial=0.0) <= tol * max(1.0, r.sum()):
            break
    return N
