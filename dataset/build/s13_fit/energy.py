"""S13 energy rows (fix round 2026-10-24, items A10 and B1). Kept apart from the fit and the tax placement.

A10, in the prior (before the ch.12 §12.4.1 smear), with the S11 energy-balance caps of energy_use_caps_s11.csv:
  - the refinery's crude: the pet cell of each oil row may hold at most the measured intake at S11 prices, the price
    basis of the oil and pet output targets. As a share of the row: intake value / the row's held total (domestic
    sales = oil target less exports; imports = held VMSB). The excess goes pro rata to the row's other buyers (the
    S11 listed direct users); with none, to the oil column, the energy balance's own use, losses and stock change.
  - gas own use: the gas cell of each gas row may hold at most the UNSD own-use share of the row; the excess goes pro
    rata to the row's other buyers.
B1, after the fit: for energy goods each agent's import share is the region's purchase-wide import share (import
proportionality, as GTAP does where the energy data have no agent split, IMPROVEMENTS_LOG S15-1). Each column keeps its
basic purchase of each energy good and each row keeps its total, so every held row and tax rate is unchanged.
"""
import numpy as np

ENERGY = ('coa', 'oil', 'gas', 'pet', 'ely')


def _move(b, j, new_bj, others, fallback=None):
    """Lower b[j] to new_bj and spread the excess over others (pro rata to b), or put it on fallback."""
    e = b[j] - new_bj
    out = b.copy()
    out[j] = new_bj
    w = np.where(others, b, 0.0)
    if w.sum() > 0:
        out += e * w / w.sum()
        return out, 'other buyers'
    if fallback is not None:
        out[fallback] += e
        return out, 'own use'
    return b, None


def cap_prior(pv, tau, idx, cols_all, tgt, X, M, caps, live, crude_cols=None):
    """Fix-round A10, in place on the prior purchaser values pv = {'dom', 'imp'} (commodities x agents).
    tau: tax power by agent; idx: commodity -> row index; tgt, X, M: held output, exports and imports by commodity;
    caps: the region's energy_use_caps_s11 row (dict) or None; live: agents that can buy; crude_cols: the listed crude
    users (s13 choice crude_smear_users), the only other buyers that take refinery crude above the cap (final round
    2026-10-25: BHR air, a representative-table column, took 1.45 bn of crude, its whole output). Returns ledger notes
    (item, column, before, after, rule, flag) and report rows."""
    notes, rep = [], []
    if caps is None:
        return notes, rep
    gi = np.array([c in ('g', 'i') for c in cols_all])
    buyers = live & ~gi
    io_, ig, ip = idx['oil'], idx['gas'], idx['pet']
    held = {'dom': tgt[io_] - X[io_], 'imp': M[io_]}
    if caps.get('intake_measured'):
        for kind, cap_v in (('dom', caps['intake_value_dom_musd']), ('imp', caps['intake_value_imp_musd'])):
            b = pv[kind][io_, :] / tau
            s, tot = b.sum(), held[kind]
            if not (np.isfinite(tot) and tot > 0 and s > 0):
                continue
            share = min(max(cap_v, 0.0) / tot, 1.0)
            if b[ip] <= share * s * (1 + 1e-9):
                continue
            others = buyers & (b > 0)
            if crude_cols is not None:
                others &= np.array([c in crude_cols for c in cols_all])
            others[ip] = False
            new, how = _move(b, ip, share * s, others, io_ if live[io_] else None)
            if how is None:
                rep.append(dict(item=f'{kind}_oil', column='pet', status='not capped: no other live buyer', share_cap=share,
                                share_prior=b[ip] / s))
                continue
            notes.append((f'{kind}_oil', 'pet', float(b[ip] * tau[ip]), float(new[ip] * tau[ip]), 'energy_use_caps',
                          'REFINERY-CRUDE-CAP' if how == 'other buyers' else 'REFINERY-CRUDE-CAP-OWN-USE'))
            rep.append(dict(item=f'{kind}_oil', column='pet', status=f'capped, excess to {how}', share_cap=share, share_prior=b[ip] / s))
            pv[kind][io_, :] = new * tau
    s_own = caps.get('gas_own_use_share', np.nan)
    if s_own is not None and np.isfinite(s_own):
        for kind in ('dom', 'imp'):
            b = pv[kind][ig, :] / tau
            s = b.sum()
            if s <= 0 or b[ig] <= s_own * s * (1 + 1e-9):
                continue
            others = buyers & (b > 0)
            others[ig] = False
            new, how = _move(b, ig, s_own * s, others)
            if how is None:
                rep.append(dict(item=f'{kind}_gas', column='gas', status='not capped: no other live buyer', share_cap=s_own, share_prior=b[ig] / s))
                continue
            notes.append((f'{kind}_gas', 'gas', float(b[ig] * tau[ig]), float(new[ig] * tau[ig]), 'energy_use_caps', 'GAS-OWN-USE-CAP'))
            rep.append(dict(item=f'{kind}_gas', column='gas', status='capped, excess to other buyers', share_cap=s_own, share_prior=b[ig] / s))
            pv[kind][ig, :] = new * tau
    return notes, rep


OWN_USE_NET_OUT = ('ely',)     # not an S11 target: the excess diagonal is intra-industry resale, netted out of row and column


def cap_own_use(pv, tau_cell, idx, cols_all, tgt, va, shares, live, net_out=OWN_USE_NET_OUT, basic=False, net_held=()):
    """Fix round wG (QA round 2 P5), in place on the prior purchaser values pv = {'dom', 'imp'}: the own-use (diagonal)
    cell of each energy good c in shares ({good: UNSD own use + losses share of production}, S11 own_use_s11.csv),
    domestic and imported together at agents' prices, holds at most that share of the activity's prior column (its
    purchases plus value added va, agents' prices). The column share is what the fit keeps (eq. 17.5; an activity's
    cost is its output, eq. 17.22), so a cap on the share of the prior column is a cap on the share of output after
    the fit has scaled the column to its S11 target. The excess (1 - k) d leaves the column, so k d = s (col - (1 - k) d):
      - a held good (S11 target): the excess goes pro rata to the row's other buyers (activities, households; not
        government or investment), domestic to domestic and imported to imported, so the held row totals stay; a row
        with no other buyer is not capped (reported);
      - ely (net_out, not a target): the domestic excess leaves row and column alike (intra-industry resale inside the
        ICIO D35 output); the imported excess (imports are held) goes to the other buyers of the import row;
      - a held good in net_held (beta v4 H2, s13 choice ely_hold_net_own_use: ely held at its prior less this netting,
        method.ely_floor) is netted like ely, not moved to the other buyers.
    tau_cell: the cell tax powers (basic = pv / tau_cell). basic (round 3, final QA 2 item 2; s13 choice
    own_use_cap_valuation): the cap is on the diagonal's basic value over the column (output), k d_b = s (col - (1 - k) d),
    so a subsidised or taxed diagonal is measured as the energy balance's volume at the basic price. Returns (ledger
    notes, report rows)."""
    notes, rep = [], []
    gi = np.array([c in ('g', 'i') for c in cols_all])
    buyers = live & ~gi
    for c, s in sorted(shares.items()):
        if c not in idx or s is None or not np.isfinite(s):
            continue
        i = idx[c]
        j = i
        d = pv['dom'][i, j] + pv['imp'][i, j]
        col = pv['dom'][:, j].sum() + pv['imp'][:, j].sum() + max(va[j], 0.0)
        held = np.isfinite(tgt[i])
        if d <= 0 or col <= 0:
            continue
        db = (pv['dom'][i, j] + pv['imp'][i, j]) / tau_cell[i, j] if basic else d
        if s >= 1.0:
            k = 1.0
        elif db - s * d > 0:
            k = s * (col - d) / (db - s * d)
        else:
            k = 1.0
        k = min(max(k, 0.0), 1.0)
        if k >= 1.0 - 1e-9:
            continue
        b = {kind: pv[kind][i, :] / tau_cell[i, :] for kind in ('dom', 'imp')}
        moved = {}
        ok = True
        new = {kind: b[kind].copy() for kind in ('dom', 'imp')}
        for kind in ('dom', 'imp'):
            e = b[kind][j] * (1.0 - k)
            if e <= 0:
                continue
            new[kind][j] = b[kind][j] * k
            if kind == 'dom' and c in net_out and (not held or c in net_held):
                moved[kind] = 'netted out'
                continue
            others = buyers & (b[kind] > 0)
            others[j] = False
            w = np.where(others, b[kind], 0.0)
            if w.sum() <= 0:
                ok = False
                break
            new[kind] += e * w / w.sum()
            moved[kind] = 'other buyers'
        if not ok:
            rep.append(dict(item=c, column=c, status='not capped: no other live buyer', share_cap=s, share_prior=db / col,
                            prior_musd=float(d), cap_musd=float(k * d)))
            continue
        for kind in ('dom', 'imp'):
            if kind in moved:
                notes.append((f'{kind}_{c}', c, float(b[kind][j] * tau_cell[i, j]), float(new[kind][j] * tau_cell[i, j]), 'own_use_cap',
                              'OWN-USE-CAP-NETTED' if moved[kind] == 'netted out' else 'OWN-USE-CAP'))
            pv[kind][i, :] = new[kind] * tau_cell[i, :]
        rep.append(dict(item=c, column=c, status='capped, excess ' + ' / '.join(f'{k_}: {v}' for k_, v in moved.items()), share_cap=s,
                        share_prior=db / col, prior_musd=float(d), cap_musd=float(k * d)))
    return notes, rep


def own_use_overshoot(P, R, sectors, shares, tol=0.01, tau_cell=None):
    """After a fit: the goods whose fitted own-use share of the column (agents' prices, fit.Column values; with
    tau_cell, the diagonal at basic value over the column, s13 choice own_use_cap_valuation) is above their cap share by
    more than tol. Returns {good: (fitted share, cap)}."""
    out = {}
    for c, s in shares.items():
        if c not in sectors or not np.isfinite(s):
            continue
        j = sectors.index(c)
        v = R['vals'].get(c)
        if v is None or v.sum() <= 0:
            continue
        t = 1.0 if tau_cell is None else float(tau_cell[j, j])
        f = float((v[2 * j] + v[2 * j + 1]) / t / v.sum())
        if f > s + tol:
            out[c] = (f, s)
    return out


def own_use_cap_report(io13, caps, tol=0.01, min_musd=100.0):
    """After the fit: diagonal cells (dom + imp own good, basic) above the UNSD own-use share of output by more than
    tol (share points) and min_musd. caps: {(region, good): share}. Returns a list of 'REG good fitted>cap'."""
    over = []
    for reg, b in io13.groupby('region'):
        b = b.set_index('row')
        for (r, c), s in caps.items():
            if r != reg or c not in b.columns or not np.isfinite(s):
                continue
            own = float(b.loc[f'dom_{c}', c] + b.loc[f'imp_{c}', c])
            out = float(b.loc['OUT', c])
            if out > 0 and own > (s + tol) * out + min_musd:
                over.append(f'{reg} {c} {own / out:.3f}>{s:.3f}')
    return over


def import_proportionality(dom, imp, idx, energy=ENERGY):
    """Fix-round B1, in place on the fitted basic values (commodities x agents): for each energy good, every agent's
    import share becomes the region's purchase-wide import share. Returns the absolute value moved (USD million)."""
    moved = 0.0
    for c in energy:
        i = idx[c]
        t = dom[i, :] + imp[i, :]
        T = t.sum()
        if T <= 0:
            continue
        m = imp[i, :].sum() / T
        new_imp = t * m
        moved += float(np.abs(new_imp - imp[i, :]).sum())
        imp[i, :] = new_imp
        dom[i, :] = t - new_imp
    return moved


def import_share_gap(io13, sectors, agents, energy=ENERGY):
    """Largest gap between an agent's import share of an energy good and the region's purchase-wide share
    (io_s13 rows dom_c, imp_c over the agent columns). Returns (cells above 1e-9, detail)."""
    bad, det = 0, []
    for reg, b in io13.groupby('region'):
        b = b.set_index('row')
        for c in energy:
            d, m = b.loc[f'dom_{c}', agents].to_numpy(float), b.loc[f'imp_{c}', agents].to_numpy(float)
            t = d + m
            if t.sum() <= 0:
                continue
            s = m.sum() / t.sum()
            k = t > 1e-6
            gap = np.abs(m[k] / t[k] - s)
            n = int((gap > 1e-6).sum())
            if n:
                bad += n
                det.append(f'{reg} {c} {gap.max():.2e}')
    return bad, '; '.join(det[:20])


def zero_mask(prior_zero_r, idx, energy=ENERGY):
    """Structural zeros for S13-Hzeros after import proportionality: for an energy good a cell is a structural zero
    only where both its domestic and its imported prior are zero (proportionality moves value between the two)."""
    out = {k: v.copy() for k, v in prior_zero_r.items()}
    for c in energy:
        i = idx[c]
        both = prior_zero_r['dom'][i, :] & prior_zero_r['imp'][i, :]
        out['dom'][i, :] = both
        out['imp'][i, :] = both
    return out


def cap_report(io13, caps, tol=0.01, min_musd=100.0):
    """After the fit: regions whose refinery crude purchase (dom + imp oil into pet) exceeds the measured intake
    value, and whose gas own use exceeds the UNSD share of gas purchases, by more than tol and min_musd."""
    over_c, over_g = [], []
    C = caps.set_index('region')
    for reg, b in io13.groupby('region'):
        if reg not in C.index:
            continue
        b = b.set_index('row')
        k = C.loc[reg]
        if bool(k['intake_measured']):
            crude = float(b.loc['dom_oil', 'pet'] + b.loc['imp_oil', 'pet'])
            cap = float(k['intake_value_dom_musd'] + k['intake_value_imp_musd'])
            if crude > cap * (1 + tol) + min_musd:
                over_c.append(f'{reg} {crude / 1e3:.1f}>{cap / 1e3:.1f}')
        s = k['gas_own_use_share']
        if np.isfinite(s):
            agents = [c for c in b.columns if c not in ('region', 'X', 'VST', 'M', 'OUT')]
            tot = float(b.loc[['dom_gas', 'imp_gas'], agents].to_numpy(float).sum())
            own = float(b.loc['dom_gas', 'gas'] + b.loc['imp_gas', 'gas'])
            if tot > 0 and own > (s + tol) * tot + min_musd:
                over_g.append(f'{reg} {own / tot:.3f}>{s:.3f}')
    return over_c, over_g
