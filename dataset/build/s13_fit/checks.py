"""S13 hard checks. Each is a pure function returning (number of failures, detail) so the mutation tests
in tests/test_s13_checks.py can show that each one fails on a bad input.

The io frame is io_s13 in wide form: columns region, row, the sectors, p, g, i, X, VST, M, OUT; rows dom_<c>,
imp_<c>, TLS, PSE_input, EVFP_<factor>, PTAX, OUT.
"""
import numpy as np
import pandas as pd

from .method import FD, FACTORS

TOL = 1e-6


def _close(a, b, tol=TOL):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return np.abs(a - b) <= tol * np.maximum(1.0, np.maximum(np.abs(a), np.abs(b)))


def _rows(g, prefix, sectors):
    return g.loc[[f'{prefix}_{c}' for c in sectors]]


def _detail(bad):
    return '; '.join(bad[:10]) + (f'; and {len(bad) - 10} more' if len(bad) > 10 else '')


def cost_identity(io, sectors):
    """Every activity: purchases at basic prices + TLS + PSE_input + EVFP + PTAX = OUT."""
    bad = []
    rows = [f'dom_{c}' for c in sectors] + [f'imp_{c}' for c in sectors] + ['TLS', 'PSE_input', 'PTAX'] + [f'EVFP_{f}' for f in FACTORS]
    for r, g in io.groupby('region'):
        g = g.set_index('row')
        cost = g.loc[rows, sectors].sum(axis=0).to_numpy()
        out = g.loc['OUT', sectors].to_numpy(float)
        for c in np.where(~_close(cost, out))[0]:
            bad.append(f'{r} {sectors[c]} cost {cost[c]:.6f} vs OUT {out[c]:.6f}')
    return len(bad), _detail(bad)


def market_clearing(io, sectors):
    """Every commodity: domestic purchases of all agents + X + VST = OUT, and the OUT column equals the OUT row."""
    bad = []
    agents = list(sectors) + list(FD)
    for r, g in io.groupby('region'):
        g = g.set_index('row')
        d = _rows(g, 'dom', sectors)
        sales = d[agents].sum(axis=1).to_numpy() + d['X'].to_numpy() + d['VST'].to_numpy()
        outc = d['OUT'].to_numpy(float)
        outr = g.loc['OUT', sectors].to_numpy(float)
        for c in np.where(~_close(sales, outc) | ~_close(outc, outr))[0]:
            bad.append(f'{r} {sectors[c]} sales {sales[c]:.6f} OUT column {outc[c]:.6f} OUT row {outr[c]:.6f}')
    return len(bad), _detail(bad)


def imports_identity(io, sectors):
    """Every commodity: imported purchases of all agents = M."""
    bad = []
    agents = list(sectors) + list(FD)
    for r, g in io.groupby('region'):
        m = _rows(g.set_index('row'), 'imp', sectors)
        use = m[agents].sum(axis=1).to_numpy()
        for c in np.where(~_close(use, m['M'].to_numpy(float)))[0]:
            bad.append(f'{r} {sectors[c]} use {use[c]:.6f} vs M {m["M"].iloc[c]:.6f}')
    return len(bad), _detail(bad)


def held_trade(io, trade, sectors):
    """X, VST and M in io_s13 equal the held trade (trade frame: region, sector, X, VST, M)."""
    t = trade.set_index(['region', 'sector'])
    bad = []
    for r, g in io.groupby('region'):
        g = g.set_index('row')
        for c in sectors:
            want = t.loc[(r, c)] if (r, c) in t.index else pd.Series(dict(X=0.0, VST=0.0, M=0.0))
            got = (g.loc[f'dom_{c}', 'X'], g.loc[f'dom_{c}', 'VST'], g.loc[f'imp_{c}', 'M'])
            for k, v in zip(('X', 'VST', 'M'), got):
                if not _close(v, want[k]):
                    bad.append(f'{r} {c} {k} {v:.6f} vs held {want[k]:.6f}')
    return len(bad), _detail(bad)


def final_demand(io, sectors, targets):
    """C, G and I at purchasers' prices (domestic + imported + TLS) equal the targets (frame indexed by region, columns C, G, I)."""
    bad = []
    rows = [f'dom_{c}' for c in sectors] + [f'imp_{c}' for c in sectors] + ['TLS']
    for r, g in io.groupby('region'):
        s = g.set_index('row').loc[rows, list(FD)].sum(axis=0)
        for col, k in zip(FD, ('C', 'G', 'I')):
            if not _close(s[col], targets.loc[r, k]):
                bad.append(f'{r} {k} {s[col]:.6f} vs {targets.loc[r, k]:.6f}')
    return len(bad), _detail(bad)


def gdp_identity(io, sectors, trade, gdp):
    """GDP from expenditure (C + G + I + VFOB + VST - VCIF) and from income (VA + TLS + PSE_input + PTAX + export
    and import taxes) both equal S02 GDP (gdp: region -> USD million; trade has XFOB and MCIF)."""
    bad = []
    t = trade.groupby('region')[['X', 'XFOB', 'VST', 'M', 'MCIF']].sum()
    for r, g in io.groupby('region'):
        g = g.set_index('row')
        tr = t.loc[r] if r in t.index else pd.Series(dict(X=0.0, XFOB=0.0, VST=0.0, M=0.0, MCIF=0.0))
        rows = [f'dom_{c}' for c in sectors] + [f'imp_{c}' for c in sectors] + ['TLS']
        absorption = g.loc[rows, list(FD)].to_numpy().sum()
        exp = absorption + tr['XFOB'] + tr['VST'] - tr['MCIF']
        va = g.loc[[f'EVFP_{f}' for f in FACTORS], sectors].to_numpy().sum()
        taxes = g.loc[['TLS', 'PSE_input', 'PTAX'], list(sectors) + list(FD)].to_numpy().sum()
        inc = va + taxes + (tr['XFOB'] - tr['X']) + (tr['M'] - tr['MCIF'])
        if not (_close(exp, gdp[r]) and _close(inc, gdp[r])):
            bad.append(f'{r} expenditure {exp:.3f} income {inc:.3f} S02 {gdp[r]:.3f}')
    return len(bad), _detail(bad)


FACGDP_REL, FACGDP_MUSD = 1e-6, 1.0


def factor_income_gdp(io, sectors, gdp, fuel, tol_rel=FACGDP_REL, tol_musd=FACGDP_MUSD):
    """S13-Hfacgdp (round-3 final QA item 4). Factor income (the EVFP cells) can exceed GDP only by the product
    subsidies the table books from their sources: for every region, factor income - GDP <= booked product subsidies +
    max(tol_rel GDP, tol_musd), where the booked subsidies are the B15 fuel subsidies in the fitted table (fuel: region ->
    USD million), the PSE input support (-PSE_input) and the output subsidies (the negative PTAX cells).
    Returns (n bad, detail, DataFrame by region)."""
    rows, bad = [], []
    cols = list(sectors) + list(FD)
    for r, g in io.groupby('region'):
        g = g.set_index('row')
        va = float(g.loc[[f'EVFP_{f}' for f in FACTORS], sectors].to_numpy().sum())
        pse = -float(g.loc['PSE_input', cols].sum()) if 'PSE_input' in g.index else 0.0
        pt = g.loc['PTAX', cols].to_numpy(float) if 'PTAX' in g.index else np.zeros(len(cols))
        osub = -float(pt[pt < 0].sum())
        fs = float(fuel.get(r, 0.0))
        sub = fs + pse + osub
        G = float(gdp[r])
        gap = va - G
        tol = max(tol_rel * abs(G), tol_musd)
        ok = bool(gap <= sub + tol)
        rows.append(dict(region=r, factor_income_musd=va, gdp_musd=G, factor_income_over_gdp=va / G if G else np.nan, excess_musd=gap,
                         fuel_subsidy_musd=fs, pse_input_musd=pse, output_subsidy_musd=osub, booked_subsidy_musd=sub, ok=ok))
        if not ok:
            bad.append(f'{r} factor income - GDP {gap:.1f} above booked subsidies {sub:.1f}')
    return len(bad), _detail(bad), pd.DataFrame(rows)


def energy_targets(io, target_out):
    """OUT equals the S11 output value for every (region, commodity) with target = yes."""
    bad = []
    io = io.set_index(['region', 'row'])
    for (r, c), v in target_out.items():
        if (r, 'OUT') not in io.index:
            continue
        got = io.loc[(r, 'OUT'), c]
        if not _close(got, v):
            bad.append(f'{r} {c} OUT {got:.6f} vs S11 {v:.6f}')
    return len(bad), _detail(bad)


def tax_rates(io, sectors, rates, cells=None):
    """The net product-tax rate of every cell and the farm input-support rate of every column, and the
    output-tax rate of every activity (OUT / cost - 1, the farm output support), equal the held rates (rates
    frame: region, column, tls_rate, pse_rate, output_tax_rate), wherever the column has purchases or costs.
    cells (region, column, commodity, tls_rate, pse_rate; fix list A1): the column TLS and PSE_input must equal
    the sum over its dom and imp rows of the basic purchase times the cell rate. A column without cells is
    held at its one column rate."""
    bad = []
    rt = rates.set_index(['region', 'column'])
    rows = [f'dom_{c}' for c in sectors] + [f'imp_{c}' for c in sectors]
    by_col = {}
    if cells is not None and len(cells):
        for (r, col), g in cells.groupby(['region', 'column']):
            by_col[(r, col)] = g.set_index('commodity')[['tls_rate', 'pse_rate']]
    for r, g in io.groupby('region'):
        g = g.set_index('row')
        cost_rows = rows + ['TLS', 'PSE_input'] + [x for x in g.index if x.startswith('EVFP_')]
        for col in list(sectors) + list(FD):
            if (r, col) not in rt.index:
                continue
            b = g.loc[rows, col].sum()
            if b > TOL:
                if (r, col) in by_col:
                    cr = by_col[(r, col)].reindex(list(sectors)).fillna(0.0)
                    bi = g.loc[[f'dom_{c}' for c in sectors], col].to_numpy(float) + g.loc[[f'imp_{c}' for c in sectors], col].to_numpy(float)
                    for row, k in (('TLS', 'tls_rate'), ('PSE_input', 'pse_rate')):
                        want = float((bi * cr[k].to_numpy(float)).sum())
                        if not _close(g.loc[row, col], want, 1e-8):
                            bad.append(f'{r} {col} {row} {g.loc[row, col]:.9f} vs cells {want:.9f}')
                else:
                    for row, k in (('TLS', 'tls_rate'), ('PSE_input', 'pse_rate')):
                        if not _close(g.loc[row, col] / b, rt.loc[(r, col), k], 1e-8):
                            bad.append(f'{r} {col} {row} rate {g.loc[row, col] / b:.9f} vs {rt.loc[(r, col), k]:.9f}')
            if col in sectors:
                cost = g.loc[cost_rows, col].sum()
                if cost > TOL and not _close(g.loc['OUT', col] / cost - 1.0, rt.loc[(r, col), 'output_tax_rate'], 1e-8):
                    bad.append(f'{r} {col} output-tax rate {g.loc["OUT", col] / cost - 1.0:.9f} vs {rt.loc[(r, col), "output_tax_rate"]:.9f}')
    return len(bad), _detail(bad)


def factor_shares(io, sectors, shares, world):
    """Each factor's share of VA equals its S12 share (shares frame: region, sector, factor, share, for the cells
    with S12 VA > 0); an activity with no S12 VA has the world composition of its sector (world: sector x factor)."""
    bad = []
    sh = shares.set_index(['region', 'sector', 'factor'])['share']
    own = set(zip(shares['region'], shares['sector']))
    for r, g in io.groupby('region'):
        e = g.set_index('row').loc[[f'EVFP_{f}' for f in FACTORS], sectors]
        va = e.sum(axis=0)
        for c in sectors:
            if va[c] <= TOL:
                continue
            for f in FACTORS:
                want = sh.get((r, c, f), 0.0) if (r, c) in own else float(world.loc[c, f])
                if not _close(e.loc[f'EVFP_{f}', c] / va[c], want, 1e-8):
                    bad.append(f'{r} {c} {f} share {e.loc[f"EVFP_{f}", c] / va[c]:.9f} vs S12 {want:.9f}')
    return len(bad), _detail(bad)


def signs(io, sectors, held_negative):
    """Purchases, trade, output and factor payments are non-negative, except capital in the held negative-VA cells."""
    bad = []
    agents = list(sectors) + list(FD)
    for r, g in io.groupby('region'):
        g = g.set_index('row')
        for prefix in ('dom', 'imp'):
            m = _rows(g, prefix, sectors)[agents + ['X', 'VST', 'M', 'OUT']]
            for row, col in zip(*np.where(m.to_numpy() < -TOL)):
                bad.append(f'{r} {m.index[row]} {m.columns[col]} {m.iat[row, col]:.6f}')
        for f in FACTORS:
            for c in sectors:
                v = g.loc[f'EVFP_{f}', c]
                if v < -TOL and not (f == 'capital' and (r, c) in held_negative):
                    bad.append(f'{r} EVFP_{f} {c} {v:.6f}')
        for c in sectors:
            if g.loc['OUT', c] < -TOL:
                bad.append(f'{r} OUT {c} {g.loc["OUT", c]:.6f}')
    return len(bad), _detail(bad)


def smear_fill(io, sectors, presmear_zero):
    """Report only: the purchase cells the smears create. Returns (count, total USD million) of cells that are
    zero in the prior before smearing and positive in the fitted table."""
    n, tot = 0, 0.0
    cols = list(sectors) + list(FD)
    for r, g in io.groupby('region'):
        if r not in presmear_zero:
            continue
        g = g.set_index('row')
        for prefix in ('dom', 'imp'):
            m = g.loc[[f'{prefix}_{c}' for c in sectors], cols].to_numpy(float)
            hit = (m > TOL) & presmear_zero[r][prefix]
            n += int(hit.sum())
            tot += float(m[hit].sum())
    return n, tot


def structural_zeros(io, sectors, prior_zero):
    """No purchase cell is positive where the prior (after cleaning and smears) is zero.
    prior_zero: region -> {'dom': bool array n x (n+3), 'imp': ...}."""
    bad = []
    agents = list(sectors) + list(FD)
    for r, g in io.groupby('region'):
        if r not in prior_zero:
            continue
        g = g.set_index('row')
        for prefix in ('dom', 'imp'):
            m = _rows(g, prefix, sectors)[agents].to_numpy()
            hit = (m > TOL) & prior_zero[r][prefix]
            for i, j in zip(*np.where(hit)):
                bad.append(f'{r} {prefix}_{sectors[i]} {agents[j]} {m[i, j]:.6f}')
    return len(bad), _detail(bad)


def factors_match_io(fac, io, sectors):
    """factors_s13 EVFP equals the io_s13 EVFP rows, and EVFB = EVFP - ftax, EVOS = EVFB - itax."""
    bad = []
    e = io[io['row'].str.startswith('EVFP_')].melt(id_vars=['region', 'row'], value_vars=list(sectors), var_name='sector', value_name='io')
    e['factor'] = e['row'].str[5:]
    m = fac.merge(e[['region', 'sector', 'factor', 'io']], on=['region', 'sector', 'factor'], how='outer').fillna(0.0)
    for x in m[~_close(m['evfp'], m['io'])].head(20).itertuples():
        bad.append(f'{x.region} {x.sector} {x.factor} factors {x.evfp:.6f} vs io {x.io:.6f}')
    for x in fac[~_close(fac['evfb'], fac['evfp'] - fac['ftax']) | ~_close(fac['evos'], fac['evfb'] - fac['itax'])].head(20).itertuples():
        bad.append(f'{x.region} {x.sector} {x.factor} EVFB/EVOS identity')
    n = int((~_close(m['evfp'], m['io'])).sum() + (~_close(fac['evfb'], fac['evfp'] - fac['ftax']) | ~_close(fac['evos'], fac['evfb'] - fac['itax'])).sum())
    return n, _detail(bad)


def converged(fit_rows):
    """Every region's fit reached the held targets (no slack, no plug): fit_rows has region, ok, resid, worst."""
    bad = [f'{x["region"]} (largest scaled residual {x["resid"]:.3g}; binding rows {x["worst"]})' for x in fit_rows if not x['ok']]
    return len(bad), _detail(bad)


def factor_positive(mt):
    """The C, G and I scale factor is positive in every region (decision 2): mt indexed by region with factor."""
    bad = [f'{r} {f:.3f}' for r, f in mt['factor'].items() if not f > 0]
    return len(bad), _detail(bad)


def no_plug_columns(io, sectors):
    """io_s13 has exactly the GTAP columns: no stock, gap, discrepancy or slack column survives."""
    want = ['region', 'row'] + list(sectors) + list(FD) + ['X', 'VST', 'M', 'OUT']
    extra = [c for c in io.columns if c not in want]
    miss = [c for c in want if c not in io.columns]
    return len(extra) + len(miss), ' '.join(f'+{c}' for c in extra) + ' ' + ' '.join(f'-{c}' for c in miss)


# ------------------------------------------------------------------ fix list A2: export taxes carried
ENERGY_XT = ('coa', 'oil', 'gas', 'pet')


RATE_ROUNDING = 1e-6   # S11 export_tax_rate is written to 6 decimals


def export_tax_held(held, ex, xt10, gx=None, rel=1e-6, abs_tol=1e-3):
    """Fix list A2: the export tax reaches the held trade. held: region, sector, X (VXSB), XFOB (S13 trade, or the
    S14 bilateral table summed by exporter and commodity). By region and commodity, XFOB - X must be
      - on coa, oil, gas and pet: t x the S11 VFOB of the region's energy routes (ex: vfob_energy_s11), with t the
        route's export_tax_rate S11 writes (else the S10 rate of the exporter and good, xt10: export_tax_s10 exporter, sector, rate);
      - on other goods (gx: vfob_s10 without energy, when given): the S10 wedge VFOB - VXSB of its routes (export
        tax less export subsidy);
      - anywhere else (services, travel): 0.
    rel, abs_tol: tolerance (abs_tol covers the 1e-6 rounding of the route files and the B14 routes below USD 1).
    Returns (failures, detail)."""
    e = ex[ex['sector'].isin(ENERGY_XT)]
    if 'export_tax_rate' in e.columns:          # Fable QA C-03: S11 writes the rate of each route (exempt and pipeline routes)
        rate = np.nan_to_num(e['export_tax_rate'].to_numpy(float))
    else:
        t = xt10.set_index(['exporter', 'sector'])['rate'].astype(float)
        rate = np.nan_to_num(pd.MultiIndex.from_frame(e[['exporter', 'sector']]).map(t).to_numpy(float))
    want = (e['vfob_musd'].astype(float) * rate).groupby([e['exporter'], e['sector']]).sum()
    # S11 writes export_tax_rate to 6 decimals, so t x VFOB can miss VFOB - VXSB by up to 5e-7 x VFOB (KAZ oil
    # 0.02 USD m on 46 bn); the tolerance carries that rounding, 1e-6 x the energy VFOB of the cell.
    rate_tol = (e['vfob_musd'].astype(float).abs() * RATE_ROUNDING).groupby([e['exporter'], e['sector']]).sum()
    rate_tol.index.names = ['region', 'sector']
    if gx is not None and len(gx):
        g = gx[~gx['sector'].isin(ENERGY_XT)]
        want = want.add((g['vfob_musd'] - g['vxsb_musd']).groupby([g['exporter'], g['sector']]).sum(), fill_value=0.0)
    want.index.names = ['region', 'sector']
    got = (held['XFOB'] - held['X']).groupby([held['region'], held['sector']]).sum()
    idx = got.index.union(want.index)
    a, b = got.reindex(idx, fill_value=0.0), want.reindex(idx, fill_value=0.0)
    tol = rel * np.maximum(1.0, b.abs()) + abs_tol + rate_tol.reindex(idx, fill_value=0.0)
    bad = [f'{k[0]} {k[1]}: XFOB - X {a[k]:.6g} vs export tax {b[k]:.6g}'
           for k in idx[((a - b).abs() > tol).to_numpy()]]
    return len(bad), _detail(bad)


# ------------------------------------------------------------------ fix-round B15: fuel subsidies
def fuel_subsidy_columns(io, rows, sectors, cols_mask):
    """Per (region, good, column): the fitted subsidy rho x basic purchases (dom + imp) of io_s13, for the columns
    cols_mask names (activities, households, government). rows: summary dicts with region, commodity, rho, status.
    Returns a list of dicts (region, commodity, column, basic_musd, subsidy_musd)."""
    out = []
    cols_all = list(sectors) + list(FD)
    for x in rows:
        if x['status'] != 'booked':
            continue
        g = io[io['region'] == x['region']].set_index('row')
        if not len(g):
            continue
        c = x['commodity']
        m = x.get('mask', cols_mask)          # the good's subsidised columns (s13 choice fuel_subsidy_users)
        for j, col in enumerate(cols_all):
            if not m[j]:
                continue
            b = float(g.loc[f'dom_{c}', col] + g.loc[f'imp_{c}', col])
            if b != 0:
                out.append(dict(region=x['region'], commodity=c, column=col, rate=-x['rho'], basic_musd=b, subsidy_musd=x['rho'] * b))
    return out


def fuel_subsidy_booked(rows, tol=TOL):
    """S13-Hsubsidy (fix-round B15). rows: per (region, good) dicts with to_book_musd (the S11 subsidy less the NEERS
    subsidy already on the row), rho, kind ('held': an S11 target good, booked exactly; 'prior': electricity, booked
    exactly in the prior), booked_prior_musd, booked_fitted_musd and status. Every subsidy to book is booked
    (status booked, 0 <= rho < 1); a held good's fitted table books it exactly (rho is set on the held purchases, which
    the prior only approaches), and an electricity subsidy is booked exactly in the prior, and also in the fitted table
    when its money is held (money_held, s13 choice electricity_subsidy_money)."""
    bad = []
    for x in rows:
        k = f'{x["region"]} {x["commodity"]}'
        if x['to_book_musd'] <= 0:
            continue
        if x['status'] != 'booked' or not (0.0 <= x['rho'] < 1.0):
            bad.append(f'{k} not booked ({x["status"]}, rho {x["rho"]:.4g})')
            continue
        # a rate cap that binds only in the fit (fuel_subsidy_rate_cap) leaves the prior booking at the amount before it
        prior_want = x['to_book_musd'] + x.get('capped_fit_musd', 0.0)
        if x['kind'] == 'prior' and not _close(x['booked_prior_musd'], prior_want, tol):
            bad.append(f'{k} prior books {x["booked_prior_musd"]:.6f} of {prior_want:.6f}')
        if (x['kind'] == 'held' or x.get('money_held')) and np.isfinite(x['booked_fitted_musd']) and not _close(x['booked_fitted_musd'], x['to_book_musd'], tol):
            bad.append(f'{k} fitted table books {x["booked_fitted_musd"]:.6f} of {x["to_book_musd"]:.6f}')
    return len(bad), _detail(bad)


def subsidy_tls_gap(basic, tau_tls_nosub, rho, mask, tls):
    """S13-Hsubsidy, column TLS: in every column the fitted TLS equals the cells' other taxes (each subsidised cell's
    rate before the booking, on the old basic quantity: (1 - rho) x basic x (tau_nosub - 1)) less the subsidy
    rho x basic, so the TLS moves by exactly the booked subsidy. basic: n x J fitted basic purchases (dom + imp);
    tau_tls_nosub: n x J net product-tax power before the booking; rho: length-n subsidy rate by good (0 elsewhere);
    mask: length-J subsidised columns; tls: length-J fitted TLS. Returns the largest gap relative to max(1, |TLS|)."""
    rho = np.asarray(rho, float)
    r = rho if rho.ndim == 2 else np.where(mask[None, :], rho[:, None], 0.0)      # a 2-D rho: rate by cell (per-good masks)
    want = (basic * (1.0 - r) * (tau_tls_nosub - 1.0)).sum(axis=0) - (basic * r).sum(axis=0)
    return float((np.abs(np.asarray(tls, float) - want) / np.maximum(1.0, np.abs(want))).max()) if len(want) else 0.0


def neer_overlap(subsidy_rows, neer, has_column):
    """S13-Hsubneer (fix-round B15, no double counting): where S10 placed NEERS energy subsidies on an energy row
    (energy_tax_s10 column neer_subsidy_rate), the IEA subsidy booked on that row is net of them. With the
    column missing, every IEA-gap row whose S10 rates come from NEERS or a NEERS pool fill is an unresolved overlap.
    subsidy_rows: dicts with region, commodity, s11_subsidy_musd, neer_subsidy_musd, to_book_musd (and shield_musd, the anchor B
    price-shield payment booked on top, which nets nothing); neer: {(region,
    good): S10 source label} for the rows S10 priced. Returns (failures, detail)."""
    bad = []
    for x in subsidy_rows:
        k = (x['region'], x['commodity'])
        if not has_column:
            if k in neer:
                bad.append(f'{k[0]} {k[1]} ({neer[k]}): energy_tax_s10 has no neer_subsidy_rate')
            continue
        want = max(x['s11_subsidy_musd'] - max(-x['neer_subsidy_musd'], 0.0), 0.0) + x.get('shield_musd', 0.0)   # anchor B price shield on top
        if not _close(x['to_book_musd'] + x.get('capped_musd', 0.0), want):     # the money above the rate cap is netted too
            bad.append(f'{k[0]} {k[1]} books {x["to_book_musd"]:.3f}, S11 {x["s11_subsidy_musd"]:.3f} less NEERS {-x["neer_subsidy_musd"]:.3f}')
    return len(bad), _detail(bad)


# ------------------------------------------------------------------ GTAP 12 ch.17B extreme rates (report; fix list A1, QA finding #12)
EXTREME_TAX, EXTREME_SUBSIDY = 1.0, -0.5        # report thresholds (our choice; ch.17B states none)
SMALL_FLOW_MUSD = 10.0
EXTREME_COLUMNS = ['region', 'row', 'column', 'rate', 'basic_prior_musd', 'basic_fit_musd', 'tax_fit_musd', 'small_flow']


def extreme_rates(region, tau_cell, basic_prior, basic_fit, sectors, cols_all):
    """Cells whose net product-tax rate (power - 1, product taxes, fuel subsidies and farm input support) is at or above
    EXTREME_TAX or at or below EXTREME_SUBSIDY, with their prior and fitted basic values (dom + imp). GTAP 12 ch.17B
    adjusts firms' purchases 'to eliminate cases of very large subsidies on extremely small base value flows' without a
    threshold, so S13 reports them and trims nothing."""
    rate = tau_cell - 1.0
    bp = basic_prior['dom'] + basic_prior['imp']
    out = []
    for i, j in zip(*np.where(((rate >= EXTREME_TAX) | (rate <= EXTREME_SUBSIDY)) & ((bp > 0) | (basic_fit > 0)))):
        bf = float(basic_fit[i, j])
        out.append([region, sectors[i], cols_all[j], float(rate[i, j]), float(bp[i, j]), bf, float(rate[i, j] * bf), bf < SMALL_FLOW_MUSD])
    return out


def energy_revenue_compare(adval, spec, fitted=None):
    """Fix list A1 report: energy taxes implied by the held ad valorem rates on the io_s12 basic flows (and, with
    fitted = io_s13, on the fitted basic flows; Fable QA F-04) against the S10 source revenue (NEERS or EIA, net of the
    NEERS subsidies), by source region and energy row. Returns a DataFrame (region, commodity, implied_musd,
    fitted_musd, source_musd)."""
    imp = (adval['energy_rate'] * adval['basic_musd']).groupby([adval['region'], adval['commodity']]).sum().rename('implied_musd')
    parts = [imp]
    if fitted is not None:
        f = fitted[fitted['row'].str.match(r'^(dom|imp)_')].copy()
        f['commodity'] = f['row'].str[4:]
        f = f[f['commodity'].isin(set(adval['commodity']))]
        cols = sorted(set(adval['column']) & set(f.columns))
        m = f.melt(id_vars=['region', 'commodity'], value_vars=cols, var_name='column', value_name='fit_basic')
        m = m.groupby(['region', 'commodity', 'column'], as_index=False)['fit_basic'].sum()
        x = adval.merge(m, on=['region', 'commodity', 'column'], how='inner')
        parts.append((x['energy_rate'] * x['fit_basic']).groupby([x['region'], x['commodity']]).sum().rename('fitted_musd'))
    s = spec[spec['class'] != '*']
    src = (pd.to_numeric(s['tax_musd']) + pd.to_numeric(s['subsidy_musd'])).groupby([s['region'], s['commodity']]).sum().rename('source_musd')
    out = pd.concat(parts + [src], axis=1).dropna(subset=['source_musd']).fillna(0.0).reset_index()
    out.columns = ['region', 'commodity'] + [p.name for p in parts] + ['source_musd']
    if 'fitted_musd' not in out:
        out['fitted_musd'] = np.nan
    return out[['region', 'commodity', 'implied_musd', 'fitted_musd', 'source_musd']]


def energy_revenue_held(rv, erev, held, tol=0.05):
    """Beta v4 P34 (S13-Henergyrev): every source (region, energy row) whose rates were scaled freely (no bound, sign
    or feasibility note) on a row the fit holds books its source money on the fitted flows within tol. rv:
    energy_revenue_compare with fitted; erev: scale_energy_rates_to_source report; held: the held rows. Returns
    (n bad, detail, rows not checked)."""
    x = erev.merge(rv, on=['region', 'commodity'], how='left', suffixes=('', '_rv'))
    free = x['note'].fillna('').eq('') & x['commodity'].isin(held)
    chk = x[free]
    gap = (chk['fitted_musd'] - chk['source_musd']).abs()
    bad = chk[gap.isna() | (gap > tol * chk['source_musd'].abs())]
    det = '; '.join(f'{r.region} {r.commodity} fitted {r.fitted_musd:.2f} vs source {r.source_musd:.2f}' for r in bad.head(20).itertuples())
    return len(bad), det, x[~free]


def energy_revenue_prefit(erev, held, tol=1e-6):
    """Beta v4 dry run 3 (S13-Henergyrev): every freely scaled (no note) source row on a held row has its money on the
    S11-valued row before the fit (expected_after_musd) equal to the S10 source money (tol relative). Returns (n, detail)."""
    x = erev[erev['note'].fillna('').eq('') & erev['commodity'].isin(held)]
    gap = (x['expected_after_musd'] - x['source_musd']).abs()
    bad = x[gap.isna() | (gap > tol * np.maximum(x['source_musd'].abs(), 1.0))]
    det = '; '.join(f'{r.region} {r.commodity} {r.expected_after_musd:.4f} vs {r.source_musd:.4f}' for r in bad.head(20).itertuples())
    return len(bad), det or f'{len(x)} rows: scaled rates x S11-valued row = S10 source money'


def low_power_energy(cells, rows=('pet', 'coa', 'gas', 'ely', 'oil'), floor=0.5):
    """Beta v4 P34 report: energy cells whose price power 1 + tls_rate is below floor (BFA ely about 0.43 in beta v3)."""
    c = cells[cells['commodity'].isin(rows) & (1.0 + cells['tls_rate'] < floor)]
    return c.sort_values('tls_rate')


# ------------------------------------------------------------------ fix round wC: own-use (diagonal) shares
OWN_USE_COLUMNS = ['region', 'sector', 'held', 'prior_share', 'fitted_share', 'prior_column_musd', 'fitted_column_musd',
                   'prior_own_musd', 'fitted_own_musd', 'fitted_own_basic_musd', 'fitted_share_basic']
OWN_USE_REPORT_MUSD, OWN_USE_REPORT_PP = 1000.0, 0.05


def own_use_rows(region, P, R, sectors, held, tau_cell=None):
    """One row per live activity: its own-use share (domestic plus imported own good, at agents' prices) of the
    column in the prior (fit.Column theta0) and in the fit, and the column and own-use values. held: the
    activities whose own-use share is a held share group (choice own_use_share). With tau_cell (round 3, final QA 2
    item 2) also the fitted diagonal at basic value and its share of the column (output)."""
    out = []
    for j, a in enumerate(sectors):
        col = P.columns[j]
        v = R['vals'][a]
        tot, p0 = float(v.sum()), float(col.prior.sum())
        # the share groups are shares of the adjustable cells: held cells (fixed_basic; Fable QA F-06 extraction fallback)
        # are left out of the column the held share is measured on
        tadj = tot - float(col.fixed_pv().sum())
        if tot <= 0 or p0 <= 0 or tadj <= 0:
            continue
        out.append(dict(region=region, sector=a, held=bool(a in held and len(col.gid) > 1),
                        prior_share=float(col.theta0[2 * j] + col.theta0[2 * j + 1]), fitted_share=float((v[2 * j] + v[2 * j + 1]) / tadj),
                        prior_column_musd=p0, fitted_column_musd=tot, prior_own_musd=float(col.prior[2 * j] + col.prior[2 * j + 1]),
                        fitted_own_musd=float(v[2 * j] + v[2 * j + 1]),
                        fitted_own_basic_musd=float((v[2 * j] + v[2 * j + 1]) / (tau_cell[j, j] if tau_cell is not None else 1.0)),
                        fitted_share_basic=float((v[2 * j] + v[2 * j + 1]) / (tau_cell[j, j] if tau_cell is not None else 1.0) / tot)))
    return out


def pse_items_booked(PI, pse_in, listed, fitted, tol=1e-6, remainder=None):
    """S13-Hpseitem (fix round wG): every listed PSE B1 item (listed: {region: {row: USD million}}) of a fitted region
    with PSE input support is booked on its row (PI rows from method.book_pse_input) at its listed value, or all items
    scaled by pse_in / their sum where they exceed the region's PSE input total pse_in, and its cell rate is in (-1, 0).
    remainder ({region: [rows]}, round-3 QA item 9): for such a region the items booked add up to pse_in (nothing is
    left on the other inputs), a listed item on a remainder row carrying its listed value plus its share; support netted
    off a row because another source books it there (netted_musd, s13 choice pse_iea_overlap) counts as booked."""
    bad = []
    remainder = remainder or {}
    P = {(x.region, x.input_row): x for x in PI.itertuples()}
    for r, items in listed.items():
        if r not in fitted or not pse_in.get(r, 0.0):
            continue
        tot = sum(items.values())
        k = min(1.0, pse_in[r] / tot) if tot > 0 else 0.0
        for c, v in items.items():
            x = P.get((r, c))
            if x is None:
                bad.append(f'{r} {c} not reported')
            elif 'remainder' in str(getattr(x, 'part', '')):
                if x.value_musd < v * k - tol * max(1.0, v):
                    bad.append(f'{r} {c} booked {x.value_musd:.3f} below the listed {v * k:.3f}')
            elif abs(x.value_musd - v * k) > tol * max(1.0, v):
                bad.append(f'{r} {c} booked {x.value_musd:.3f} of {v * k:.3f}')
            elif not (-1.0 < x.rate < 0.0):
                bad.append(f'{r} {c} rate {x.rate}')
    for r, rows in remainder.items():
        if r not in fitted or not pse_in.get(r, 0.0):
            continue
        sel = PI[PI['region'] == r]
        got = float(sel['value_musd'].sum()) + (float(sel['netted_musd'].fillna(0.0).sum()) if 'netted_musd' in sel.columns else 0.0)
        if abs(got - pse_in[r]) > tol * max(1.0, abs(pse_in[r])):
            bad.append(f'{r} items booked {got:.3f} of the PSE input total {pse_in[r]:.3f} (remainder rows {" ".join(rows)})')
        for x in sel.itertuples():
            if x.value_musd > 0 and not (-1.0 < x.rate < 0.0):
                bad.append(f'{r} {x.input_row} rate {x.rate}')
    return len(bad), _detail(bad)


def own_use_held(rows, tol=1e-8):
    """S13-Hownuse (choice own_use_share): every held own-use share in the fit equals its prior share (absolute 1e-8)."""
    bad = [f"{x['region']} {x['sector']} fitted {x['fitted_share']:.9f} vs prior {x['prior_share']:.9f}"
           for x in rows if x['held'] and abs(x['fitted_share'] - x['prior_share']) > tol]
    return len(bad), _detail(bad)


def own_use_moves(rows, musd=OWN_USE_REPORT_MUSD, pp=OWN_USE_REPORT_PP):
    """S13-Rownuse: own-use cells of at least musd (prior or fitted, agents' prices) whose share of the column moved by
    more than pp (a fraction), largest move first."""
    sel = [x for x in rows if max(x['prior_own_musd'], x['fitted_own_musd']) >= musd and abs(x['fitted_share'] - x['prior_share']) > pp]
    return sorted(sel, key=lambda x: -abs(x['fitted_share'] - x['prior_share']))


PTAX_COLUMN_TOL = 1e-6          # S13-Hptaxheld and S13-Hptaxregion: general product-tax money against its target (relative)
PTAX_QA_FLAG = 0.05             # S13-Rptaxprior: regions whose net product tax is more than 5% off the QA prior


def _unheld(x):
    u = x.get('unheld')
    return isinstance(u, str) and bool(u)


def product_tax_held(rows, tol=PTAX_COLUMN_TOL):
    """S13-Hptaxheld (s13 choice product_tax_totals, round-3 QA item 3): in every column where the choice holds the
    general part of the product tax, its money on the fitted purchases equals its effective target (the io_s12 money,
    plus its share of what the region's columns at the scale bound cannot carry; relative tol of max(1, |target|)).
    A column at the bound (unheld non-blank) is not checked here; S13-Hptaxregion holds the region total.
    rows: product_tax_s13 rows (dicts or a DataFrame)."""
    rows = rows.to_dict('records') if isinstance(rows, pd.DataFrame) else rows
    bad = [f"{x['region']} {x['column']} general {x['general_musd']:.6f} vs {x['general_effective_musd']:.6f}"
           for x in rows if x['held'] and not _unheld(x)
           and abs(x['general_musd'] - x['general_effective_musd']) > tol * max(1.0, abs(x['general_effective_musd']))]
    return len(bad), _detail(bad)


def product_tax_region(rows, tol=PTAX_COLUMN_TOL, dropped=None):
    """S13-Hptaxregion: every region's general product-tax money (all its purchaser columns) on the fitted purchases
    equals its target (io_s12 money, or the product_tax_source G114 money) less dropped[region], the money no column can
    carry within the scale bound (round-3 final QA2 item 4; relative tol of max(1, |total|)), the columns at the scale
    bound included."""
    df = pd.DataFrame(rows)
    if not len(df):
        return 0, ''
    dropped = dropped or {}
    df = df[df['held'].astype(bool)]
    g = df.groupby('region')[['general_musd', 'general_target_musd']].sum()
    bad = []
    for r, x in g.iterrows():
        want = x.general_target_musd - float(dropped.get(r, 0.0))
        if abs(x.general_musd - want) > tol * max(1.0, abs(x.general_target_musd)):
            bad.append(f'{r} {x.general_musd:.3f} vs {want:.3f}')
    return len(bad), _detail(bad)


def product_tax_source(src, rows, fitted, tol=PTAX_COLUMN_TOL, money_held=True):
    """S13-Hptaxsource (s13 choice product_tax_source, round-3 final QA2 item 1). src: ptax_source.donor_regions_g114
    (every S05 donor region); rows: product_tax_source_s13 rows of the fitted regions. Every fitted donor region has a
    row; a 'g114' region's general money target is max(G114 money - energy excise, 0) and its fitted general money is
    that target less the dropped money (relative tol); a 'rates' region holds no money (mode recorded). With
    money_held False (s13 product_tax_totals holds the rates, Fable QA A-03) the target is the money on the io_s12
    flows and the fitted money moves with the purchases, so only the target is checked."""
    bad = []
    R = {x['region']: x for x in pd.DataFrame(rows).to_dict('records')}
    for x in src.itertuples():
        if x.region not in fitted:
            continue
        y = R.get(x.region)
        if y is None:
            bad.append(f'{x.region} no product_tax_source row')
            continue
        if y['mode'] == 'g114':
            want = max(float(y['g114_musd']) - float(y['energy_excise_musd']), 0.0)
            if abs(float(y['general_target_musd']) - want) > tol * max(1.0, want):
                bad.append(f'{x.region} target {y["general_target_musd"]:.3f} vs G114 less energy {want:.3f}')
            got, w2 = float(y['general_fitted_musd']), float(y['general_target_musd']) - float(y['dropped_musd'])
            if money_held and abs(got - w2) > 1e-6 * max(1.0, abs(want)):
                bad.append(f'{x.region} fitted general {got:.3f} vs {w2:.3f}')
        elif y['mode'] != 'rates':
            bad.append(f'{x.region} mode {y["mode"]!r}')
    return len(bad), _detail(bad)


def product_tax_by_region(rows, fuel_booked):
    """Region totals of product_tax_s13 rows against the QA prior (io_s12 TLS with the A1 move, less the fuel subsidies
    booked in the fitted table, fuel_booked {region: USD m}). Returns a DataFrame region, prior_musd, fitted_musd,
    gap_musd, gap_rel, general_io12_musd, general_fitted_musd, energy_io12_musd (the energy-tax part at the held rates on
    the io_s12 flows), energy_fitted_musd (on the fitted flows, before the fuel subsidies) and fuel_subsidy_musd."""
    cols = ['region', 'prior_musd', 'fitted_musd', 'gap_musd', 'gap_rel', 'general_io12_musd', 'general_fitted_musd', 'energy_io12_musd',
            'energy_fitted_musd', 'fuel_subsidy_musd']
    df = pd.DataFrame(rows)
    if not len(df):
        return pd.DataFrame(columns=cols)
    g = df.groupby('region')[['prior_tls_musd', 'tls_musd', 'general_target_musd', 'general_musd']].sum()
    fb = pd.Series(fuel_booked, dtype=float).reindex(g.index).fillna(0.0)
    out = pd.DataFrame({'prior_musd': g['prior_tls_musd'] - fb, 'fitted_musd': g['tls_musd']})
    out['gap_musd'] = out['fitted_musd'] - out['prior_musd']
    out['gap_rel'] = out['gap_musd'] / out['prior_musd'].abs().where(out['prior_musd'].abs() > 0)
    out['general_io12_musd'] = g['general_target_musd']
    out['general_fitted_musd'] = g['general_musd']
    out['energy_io12_musd'] = g['prior_tls_musd'] - g['general_target_musd']
    out['energy_fitted_musd'] = g['tls_musd'] - g['general_musd'] + fb
    out['fuel_subsidy_musd'] = -fb
    out.index.name = 'region'
    return out.reset_index()[cols]


# ------------------------------------------------------------------ round 3 final QA 2 item 3: power fuel cells
def power_cells_held(io, rows, fitted, col='ely', tol=1e-6):
    """S13-Hpowercell. rows: method.hold_power_cells report rows (region, good, kind, s11_musd, held_musd); fitted: the
    regions with a fitted table. By region and good, the fitted io_s13 purchase of the power column (dom + imp, basic)
    equals the held value. Returns (failures, detail, frame of region, good, s11_musd, held_musd, fitted_musd)."""
    import pandas as pd
    out, bad = [], []
    if not len(rows):
        return 0, '', pd.DataFrame(columns=['region', 'good', 's11_musd', 'held_musd', 'fitted_musd', 'status'])
    g = rows.groupby(['region', 'good']).agg(s11_musd=('s11_musd', 'sum'), held_musd=('held_musd', 'sum'),
                                              status=('status', lambda x: '; '.join(sorted(set(x))))).reset_index()
    for x in g.itertuples():
        if x.region not in fitted:
            continue
        b = io[io['region'] == x.region].set_index('row')
        v = float(b.loc[f'dom_{x.good}', col] + b.loc[f'imp_{x.good}', col])
        out.append(dict(region=x.region, good=x.good, s11_musd=x.s11_musd, held_musd=x.held_musd, fitted_musd=v, status=x.status))
        if abs(v - x.held_musd) > tol * max(1.0, x.held_musd):
            bad.append(f'{x.region} {x.good} fitted {v:.6f} vs held {x.held_musd:.6f}')
    return len(bad), _detail(bad), pd.DataFrame(out)


NINETY = 0.9                      # GTAP 12 ch.12 §12.4.3 p.28
ENERGY_ROWS = ('coa', 'oil', 'gas', 'pet', 'ely')
# beta v4 P1 and P15: the energy inputs of each column that S11's 90 percent rule prices and S13 holds (pet: crude intake,
# refinery gas and own use, pinned by energy_user_pool_split; ely: the power fuel cells, gas distribution and heat netted out)
NINETY_HELD_ROWS = {'pet': ('oil', 'gas', 'pet'), 'ely': ('coa', 'oil', 'gas', 'pet')}
VA_FORCE, VA_FLAG = 0.03, 0.05    # beta v4 P5: the ladder trigger and the review band (our choice)


def ninety_fitted(io, pass_through=None, held_rows=NINETY_HELD_ROWS, exempt=(), tol=1e-9, rho=None):
    """Beta v4 P1 and P15 (GTAP 12 ch.12 §12.4.3 p.28, re-checked on the fitted table): for pet and ely in every region, the
    energy inputs S11's rule priced and S13 held (held_rows: dom + imp rows of the column, basic values; for ely less the
    gas and heat it resells at cost, pass_through {region: USD m}) are at most 90 percent of revenue (output at basic prices
    less the pass-through, plus any output subsidy, PTAX < 0). The frame also carries every energy row of the column
    (ratio_all) and the VA share, for the report. exempt: regions, or (region, industry) pairs, fitted with those cells free
    (fallbacks), reported only.
    rho (beta v4 dry run 3, choice ninety_fit_price): {(region, good, column): fitted fuel subsidy rate}; the held inputs
    are then at purchaser prices, basic x (1 - rho), the basis of the S11 rule and floor (s11 ely_fuel_purchaser_price), and
    the pass-through, resold at cost, at the held inputs' average factor (it is part of the gas and fuel cells).
    Returns (failures, detail, frame)."""
    bad, rows = [], []
    pt_ = pass_through or {}
    for r, g in io.groupby('region'):
        b = g.set_index('row')
        for c, held in held_rows.items():
            if c not in b.columns or 'OUT' not in b.index:
                continue
            out = float(b.loc['OUT', c])
            if out <= 0:
                continue

            def rows_of(goods, purch=False):
                return float(sum(b.loc[f'{k}_{x}', c] * ((1.0 - (rho or {}).get((r, x, c), 0.0)) if purch else 1.0)
                                 for x in goods for k in ('dom', 'imp') if f'{k}_{x}' in b.index))
            p = float(pt_.get(r, 0.0)) if c == 'ely' else 0.0
            if rho is not None:
                hb = rows_of(held)
                p *= rows_of(held, True) / hb if hb > 0 else 1.0
            ptax = float(b.loc['PTAX', c]) if 'PTAX' in b.index else 0.0
            va = float(sum(b.loc[x, c] for x in b.index if str(x).startswith('EVFP_')))
            rev = out - p - min(ptax, 0.0)
            e = rows_of(held, rho is not None) - p
            e_all = rows_of(ENERGY_ROWS, rho is not None) - p
            ratio = e / rev if rev > 0 else np.nan
            rows.append(dict(region=r, industry=c, output_musd=out, pass_through_musd=p, output_subsidy_musd=-min(ptax, 0.0),
                             energy_held_musd=e, ratio_held=ratio, energy_all_musd=e_all, ratio_all=e_all / rev if rev > 0 else np.nan,
                             va_musd=va, va_share=va / out, exempt=False))
            ex_ = r in exempt or (r, c) in exempt
            rows[-1]['exempt'] = ex_
            if not ex_ and not (ratio <= NINETY * (1 + tol)):
                bad.append(f'{r} {c} {ratio:.4f}')
    return len(bad), _detail(bad), pd.DataFrame(rows)


def household_crude_no_refinery(io, tol_musd=1.0):
    """Beta v4 P14 (choice no_refinery_crude_use; GTAP 12 ch.12 §12.2.4): in a region whose refining column has no output,
    households buy no crude (dom_oil + imp_oil in column p at most tol_musd). Returns (failures, detail, regions checked)."""
    bad, checked = [], []
    for r, g in io.groupby('region'):
        b = g.set_index('row')
        if 'pet' not in b.columns or 'p' not in b.columns or 'OUT' not in b.index or float(b.loc['OUT', 'pet']) > 0:
            continue
        checked.append(r)
        hh = float(sum(b.loc[k, 'p'] for k in ('dom_oil', 'imp_oil') if k in b.index))
        if hh > tol_musd:
            bad.append(f'{r} households crude {hh:.1f} USD m')
    return len(bad), _detail(bad), checked


HHE_SHARE_MAX = 0.05     # beta v4 G4: S13-Rhhe, households as employers above 5% of household basic purchases


def fuel_share_over(io13, io12, sectors, goods, factor, points, min_musd, energy=('coa', 'oil', 'gas', 'pet', 'ely')):
    """Beta v5 F report: fitted fuel cells of non-energy activities (domestic plus imported, basic) above max(factor x the
    io_s12 share of output, io_s12 share + points) by more than min_musd. Returns a list of 'REG column good s12->s13'."""
    out = []
    p12 = {r: b.set_index('row') for r, b in io12.groupby('region')}
    for reg, b in io13.groupby('region'):
        b = b.set_index('row')
        a = p12.get(reg)
        if a is None:
            continue
        for col in sectors:
            if col in energy or col not in b.columns:
                continue
            o1, o0 = float(b.loc['OUT', col]), float(a.loc['OUT', col])
            if o1 <= 0 or o0 <= 0:
                continue
            for c in goods:
                h1 = float(b.loc[f'dom_{c}', col] + b.loc[f'imp_{c}', col])
                s0 = float(a.loc[f'dom_{c}', col] + a.loc[f'imp_{c}', col]) / o0
                cap = max(factor * s0, s0 + points)
                if h1 - cap * o1 > min_musd:
                    out.append(f'{reg} {col} {c} {s0:.3f}->{h1 / o1:.3f}')
    return out


def investment_con_share(io13, io12):
    """Beta v5 C report: construction's share (domestic plus imported) of the investment column's purchases, io_s12 against
    the fit, by region. Returns a frame region, prior, fitted."""
    rows = []
    for nm, io in (('prior', io12), ('fitted', io13)):
        if 'i' not in io.columns:
            continue
        t = io[io['row'].str.startswith(('dom_', 'imp_'))]
        tot = t.groupby('region')['i'].sum()
        con = t[t['row'].isin(['dom_con', 'imp_con'])].groupby('region')['i'].sum()
        rows.append((con / tot).rename(nm))
    return pd.concat(rows, axis=1).reset_index(names='region') if rows else pd.DataFrame(columns=['region', 'prior', 'fitted'])
