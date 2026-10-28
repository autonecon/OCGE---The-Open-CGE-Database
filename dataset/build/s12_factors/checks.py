"""S12 hard checks. Each is a pure function returning (number of failures, detail) so the mutation tests
in tests/test_s12_checks.py can show that each one fails on a bad input."""
import os
import re

import numpy as np
import pandas as pd

from .method import LABOUR5, SKILLED, FACTORS

TOL = 1e-6
NATRES_OK = {'coa', 'oil', 'gas', 'ore', 'min', 'msp', 'for', 'fsh'}   # msp: GTAP oxt (fix round B16)


def factor_sum(ev, va_long, tol=TOL):
    s = ev.groupby(['region', 'sector'])['evfp'].sum().rename('sum').reset_index().merge(va_long, on=['region', 'sector'], how='outer')
    s = s.fillna(0.0)
    bad = s[(s['sum'] - s['va']).abs() > tol * np.maximum(1.0, s['va'].abs())]
    return len(bad), '; '.join(f'{r.region} {r.sector} {r.sum:.6f} vs {r.va:.6f}' for r in bad.head(10).itertuples())


def nonnegative(ev, negva_cells, tol=TOL):
    bad = []
    for c in ('evfp', 'evfb', 'evos'):
        if c not in ev.columns:
            continue
        m = ev[c] < -tol
        m &= ~((ev['factor'] == 'capital') & np.array([(r, s) in negva_cells for r, s in zip(ev['region'], ev['sector'])], bool))
        bad += [f'{r.region} {r.sector} {r.factor} {c} {getattr(r, c):.4f}' for r in ev[m].head(10).itertuples()]
    return len(bad), '; '.join(bad[:10])


def land_only_crp(ev, tol=TOL):
    bad = ev[((ev['factor'] == 'land') & (ev['sector'] != 'crp') & (ev['evfp'].abs() > tol)) |
             ((ev['factor'] == 'natres') & ~ev['sector'].isin(NATRES_OK) & (ev['evfp'].abs() > tol))]
    return len(bad), '; '.join(f'{r.region} {r.sector} {r.factor}' for r in bad.head(10).itertuples())


def group_shares(labsh, tol=1e-9):
    bad = []
    for r, t in labsh.items():
        t = t[list(LABOUR5)]
        if ((t < -tol) | (t > 1 + tol)).any().any() or ((t.sum(axis=1) - 1).abs() > 1e-6).any():
            bad.append(r)
    return len(bad), ' '.join(bad[:20])


def two_group(ev, tol=TOL):
    lab = ev[ev['factor'].isin(LABOUR5)]
    sk = lab[lab['factor'].isin(SKILLED)].groupby(['region', 'sector'])['evfp'].sum()
    un = lab[~lab['factor'].isin(SKILLED)].groupby(['region', 'sector'])['evfp'].sum()
    tot = lab.groupby(['region', 'sector'])['evfp'].sum()
    d = (sk.reindex(tot.index, fill_value=0) + un.reindex(tot.index, fill_value=0) - tot).abs()
    bad = d[d > tol]
    return len(bad), '; '.join(f'{a} {b}' for a, b in bad.index[:10])


def capital_keeps_cfc(nr, tol=TOL):
    """nr: natres rows (nonlabour_musd, cfc_share, natres_musd). Capital = non-labour - natres >= CFC share x non-labour."""
    nl = nr['nonlabour_musd'].clip(lower=0)
    bad = nr[(nl - nr['natres_musd']) < nr['cfc_share'] * nl - tol * np.maximum(1.0, nl)]
    return len(bad), '; '.join(f'{r.region} {r.sector}' for r in bad.head(10).itertuples())


def tax_totals(ev, rates, wedge='income', tol=1e-4):
    """Factor-use taxes add up to SSC + payroll and property booked + the payroll part of D29 (A3), less factor-based
    support when it is a factor-use subsidy (A4); income taxes to PIT + CIT, less the support when it is a negative
    income tax, less the land income tax dropped by the land_income_tax_cap (round-3 final QA item 7); under
    'land_factor_use' (Fable QA F-05) the land-based part is a factor-use subsidy and the rest a negative income tax;
    FBEP to the S10 support."""
    lab = ev['factor'].isin(LABOUR5)
    g = ev.assign(fl=np.where(lab, ev['ftax'], 0.0)).groupby('region').agg(ftax=('ftax', 'sum'), itax=('itax', 'sum'),
                                                                             fbep=('fbep', 'sum'), evfp=('evfp', 'sum'))
    bad = []
    for r in rates.itertuples():
        if r.region not in g.index:
            continue
        x = g.loc[r.region]
        pp = getattr(r, 'payroll_property_booked_musd', r.payroll_property_musd)
        fl = getattr(r, 'fbep_land_musd', 0.0) if wedge == 'land_factor_use' else 0.0
        want_f = r.ssc_musd + pp + getattr(r, 'payroll_musd', 0.0) - (x['fbep'] if wedge == 'factor_use' else fl)
        want_i = (r.pit_musd + r.cit_musd - (x['fbep'] if wedge == 'income' else (x['fbep'] - fl if wedge == 'land_factor_use' else 0.0))
                  - getattr(r, 'land_itax_dropped_musd', 0.0))
        if x['evfp'] > 0 and (abs(x['ftax'] - want_f) > tol * max(1, abs(want_f)) or abs(x['itax'] - want_i) > tol * max(1, abs(want_i))):
            bad.append(f'{r.region} ftax {x["ftax"]:.3f} vs {want_f:.3f}; itax {x["itax"]:.3f} vs {want_i:.3f}')
        sup = sum(getattr(r, f'support_{k}_musd') for k in ('land', 'capital', 'labour', 'factors'))
        if abs(x['fbep'] - sup) > tol * max(1, sup) and x['evfp'] > 0:
            bad.append(f'{r.region} fbep {x["fbep"]:.3f} vs support {sup:.3f}')
    return len(bad), '; '.join(bad[:10])


def land_itax_capped(ev, floor_share, tol=1e-9):
    """S12-Hlanditax (round-3 final QA item 7): every land cell's income tax is at most (1 - floor_share) x EVFP less its
    positive factor-use tax (absolute tol x max(1, EVFP))."""
    land = ev[(ev['factor'] == 'land') & (ev['evfp'] > 0)]
    cap = (1.0 - floor_share) * land['evfp'] - land['ftax'].clip(lower=0.0)
    bad = land[land['itax'] > cap.clip(lower=0.0) + tol * np.maximum(1.0, land['evfp'])]
    return len(bad), '; '.join(f'{x.region} {x.sector} itax {x.itax:.3f} on rent {x.evfp:.3f}' for x in bad.head(10).itertuples())


def output_tax_identity(otx, tol=TOL):
    """A3: in every cell otp + PSE add-back (+ the crp net subsidy beyond the PSE removed, fix worker wF) = payroll part +
    output tax (D29X39 booked once), and the payroll part is non-negative. otx: output_tax_s12 rows."""
    cap = otx['crp_beyond_pse_removed_musd'] if 'crp_beyond_pse_removed_musd' in otx.columns else 0.0
    d = (otx['otp_musd'] + otx['pse_addback_musd'] + cap - otx['payroll_musd'] - otx['output_tax_musd']).abs()
    bad = otx[(d > tol * np.maximum(1.0, otx['otp_musd'].abs())) | (otx['payroll_musd'] < -tol)]
    return len(bad), '; '.join(f'{r.region} {r.sector}' for r in bad.head(10).itertuples())


def crp_no_subsidy_beyond_pse(otx, regions, tol=TOL):
    """Fix worker wF (QA round 2 P2): in the listed regions the crp output tax before the payroll part is not below zero
    (only the PSE, booked in S13 and as factor support, subsidises farming) and the amount removed is non-negative."""
    x = otx[(otx['sector'] == 'crp') & otx['region'].isin(sorted(regions))]
    bad = x[(x['output_tax_before_payroll_musd'] < -tol * np.maximum(1.0, x['va_musd'].abs())) | (x['crp_beyond_pse_removed_musd'] < -tol)]
    return len(bad), '; '.join(f'{r.region} {r.output_tax_before_payroll_musd:.3f}' for r in bad.head(10).itertuples())


def capital_floor(va_rows, tol=TOL, d1_min=False):
    """A6: every cell with positive VA other than hhe (all labour) and crp (ch.14A cost shares) keeps non-labour income
    of at least capital_floor x factor income. va_rows: va_split rows (labour_musd, nonlabour_musd, capital_floor).
    d1_min (beta v4 G1, labour_at_least_d1): a cell whose observed D1 share is above 1 - capital_floor keeps
    1 - D1 share instead (labour is never cut below D1)."""
    v = va_rows[(~va_rows['sector'].isin(('hhe', 'crp'))) & (va_rows['va_musd'] > 0) & va_rows['capital_floor'].notna()]
    fi = v['labour_musd'] + v['nonlabour_musd']
    fl = v['capital_floor']
    if d1_min:
        fl = np.minimum(fl, 1.0 - v['d1_share_of_factor_income'].fillna(0.0))
    bad = v[v['nonlabour_musd'] < fl * fi - tol * np.maximum(1.0, fi)]
    return len(bad), '; '.join(f'{r.region} {r.sector} {r.nonlabour_musd:.3f}' for r in bad.head(10).itertuples())


def labour_at_least_d1(va_rows, tol=TOL):
    """Beta v4 G1 (labour_at_least_d1): in every non-hhe, non-crp cell with value added, labour (before natural resources
    come out pro rata) is at least the observed compensation of employees, D1 share x factor income. GTAP takes
    compensation of employees as observed (ch.8A); the capital floor is our rule and gives way to it."""
    v = va_rows[(~va_rows['sector'].isin(('hhe', 'crp'))) & (va_rows['va_musd'] > 0) & va_rows['d1_share_of_factor_income'].notna()]
    fi = v['labour_musd'] + v['nonlabour_musd']
    want = v['d1_share_of_factor_income'].clip(0.0, 1.0) * fi
    bad = v[v['labour_musd'] < want - tol * np.maximum(1.0, fi)]
    return len(bad), '; '.join(f'{r.region} {r.sector} labour {r.labour_musd:.3f} < D1 {w:.3f}'
                               for r, w in zip(bad.head(10).itertuples(), want[bad.index][:10]))


def vdep_floor(ev, floor_rows, tol=TOL):
    """capital_vdep_floor: in every region the final capital income (sum EVOS capital) is at least the floor, or the
    whole Gollin addition went back (labour at D1); and the capital income the floor step computed is the one written.
    ev: final factor cells (region, factor, evos); floor_rows: frame (region, floor_musd, returned_share,
    capital_evos_after_musd)."""
    k = ev[ev['factor'] == 'capital'].groupby('region')['evos'].sum()
    bad = []
    for x in floor_rows.itertuples():
        got = float(k.get(x.region, 0.0))
        if abs(got - x.capital_evos_after_musd) > tol * max(1.0, abs(got)):
            bad.append(f'{x.region} capital income {got:.3f} written, {x.capital_evos_after_musd:.3f} at the floor step')
        elif got < x.floor_musd - tol * max(1.0, x.floor_musd) and x.returned_share < 1.0:
            bad.append(f'{x.region} capital income {got:.3f} below the floor {x.floor_musd:.3f} with {x.returned_share:.4f} returned')
    return len(bad), '; '.join(bad[:10])


def source_coverage(icio, na_share, lam_src, donor_of, partial=None, min_sectors=None):
    """Every ICIO economy with a split uses it, every other one names its donor, and no usable partial source
    (at least min_sectors sectors covered) is dropped for a donor."""
    bad = []
    for r, n in (partial or {}).items():
        if r in icio and min_sectors is not None and n >= min_sectors and r not in na_share:
            bad.append(f'{r} has a usable partial source ({n} sectors) but takes a donor')
    for r in icio:
        if r in na_share and not (lam_src.get(r, '').startswith(('FIGARO', 'OECD'))):
            bad.append(f'{r} has a split but uses {lam_src.get(r)}')
        if r not in na_share and not donor_of.get(r):
            bad.append(f'{r} has no split and no donor')
    return len(bad), '; '.join(bad[:10])


def io_with_factors(io, ev, sectors, otax=None):
    """io_s11 with the VA row replaced by one row per factor (EVFP), in FACTORS order, and (fix round A3) the output tax
    row OTAX (D29X39 out of VA less its payroll part) when otax (region, sector, output_tax_musd) is given."""
    out = []
    piv = ev.pivot_table(index=['region', 'factor'], columns='sector', values='evfp', aggfunc='sum').reindex(columns=sectors).fillna(0.0)
    cols = list(io.columns)
    for r, g in io.groupby('region', sort=False):
        before = g[g['row'] != 'VA']
        tail = before[before['row'] == 'OUT']
        body = before[before['row'] != 'OUT']
        fr = []
        for f in FACTORS:
            rec = dict.fromkeys(cols, 0.0)
            rec['region'], rec['row'] = r, f'EVFP_{f}'
            for s in sectors:
                rec[s] = round(float(piv.loc[(r, f), s]), 6) if (r, f) in piv.index else 0.0
            fr.append(rec)
        if otax is not None:
            o = otax[otax['region'] == r].set_index('sector')['output_tax_musd']
            rec = dict.fromkeys(cols, 0.0)
            rec['region'], rec['row'] = r, 'OTAX'
            for s in sectors:
                rec[s] = round(float(o.get(s, 0.0)), 6)
            fr.append(rec)
        out += [body, pd.DataFrame(fr, columns=cols), tail]
    return pd.concat(out, ignore_index=True)


SECRET = re.compile(br'(?i)(?:api[_-]?key|password|secret|token)\s*[:=]\s*["\']?[A-Za-z0-9_\-]{12,}')


def secret_scan(paths):
    """Number of files under paths with something shaped like a key or password (count only, the S11 pattern)."""
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


def natres_eta(ev, cells, tol=TOL):
    """Fix round B16 (ch.12.A): in every targeted cell with factor VA and no guard, the booked factors give the target
    supply elasticity: sigma_VA x cost x (1 / EVFP natres - 1 / EVFP all factors) = eta_target within tol (relative to
    max(1, eta)); in a guarded cell the natural-resource share of VA is sigma / (eta theta_floor + sigma). cells: region,
    sector, cost_musd, eta_target, sigma_va, guard, theta_va_used. ev: factor rows (region, sector, factor, evfp)."""
    g = ev.groupby(['region', 'sector'])['evfp'].sum().rename('fva')
    n = ev[ev['factor'] == 'natres'].groupby(['region', 'sector'])['evfp'].sum().rename('nat')
    c = cells.merge(g.reset_index(), on=['region', 'sector'], how='left').merge(n.reset_index(), on=['region', 'sector'], how='left')
    c[['fva', 'nat']] = c[['fva', 'nat']].fillna(0.0)
    bad = []
    for x in c.itertuples():
        if not x.fva > TOL:
            if abs(x.nat) > tol:
                bad.append(f'{x.region} {x.sector} natres {x.nat:.6f} without value added')
            continue
        if x.guard:
            want = x.sigma_va / (x.eta_target * x.theta_va_used + x.sigma_va)
            if abs(x.nat / x.fva - want) > tol:
                bad.append(f'{x.region} {x.sector} guarded share {x.nat / x.fva:.9f} vs {want:.9f}')
            continue
        if not (x.nat > 0 and x.cost_musd > 0):
            bad.append(f'{x.region} {x.sector} no natural resources')
            continue
        eta = x.sigma_va * x.cost_musd * (1.0 / x.nat - 1.0 / x.fva)
        if abs(eta - x.eta_target) > tol * max(1.0, x.eta_target):
            bad.append(f'{x.region} {x.sector} eta {eta:.9f} vs target {x.eta_target}')
    return len(bad), '; '.join(bad[:10])


def natres_pro_rata(nr, tol=TOL):
    """Fix round B16 (ch.12.A p.2: the resource share is taken out of all value added): in every natural-resource cell
    labour and capital fall by the same factor, and labour + capital + natural resources after equal labour + capital
    before. nr: natres rows (labour_before_musd, capital_before_musd, labour_musd, capital_musd, natres_musd, natres_share_of_va)."""
    bad = []
    for x in nr.itertuples():
        k = 1.0 - x.natres_share_of_va
        for b, a, f in ((x.labour_before_musd, x.labour_musd, 'labour'), (x.capital_before_musd, x.capital_musd, 'capital')):
            if abs(a - k * b) > tol * max(1.0, abs(b)):
                bad.append(f'{x.region} {x.sector} {f} {a:.6f} vs {k * b:.6f}')
        before = x.labour_before_musd + x.capital_before_musd
        if abs(x.labour_musd + x.capital_musd + x.natres_musd - before) > tol * max(1.0, abs(before)):
            bad.append(f'{x.region} {x.sector} total moved')
    return len(bad), '; '.join(bad[:10])
