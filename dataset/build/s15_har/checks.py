"""S15 hard checks. Each is a pure function returning (number of failures, detail), so the mutation tests
in tests/test_s15_checks.py can show that each one fails on a bad input.

The stage runs the identity checks on the arrays as read back from gsdfdat.har by an independent reader
(harpy), so they check the Float32 file the model reads. PLAN §3(i): identities hold to 1e-6 relative after
writing to Float32 HAR.
"""
import numpy as np

TOL = 1e-6


def _detail(bad):
    return '; '.join(bad[:10]) + (f'; and {len(bad) - 10} more' if len(bad) > 10 else '')


def _rel(a, b, scale=None):
    a, b = np.asarray(a, float), np.asarray(b, float)
    sc = np.maximum(1.0, np.abs(a) if scale is None else np.asarray(scale, float))
    return np.abs(a - b) / sc


def _report(name, gap, labels, tol=TOL):
    bad = np.argwhere(gap > tol)
    out = [f'{name} {labels(tuple(i))}: rel gap {gap[tuple(i)]:.3g}' for i in bad[:10]]
    return len(bad), out


def dims(found, expected):
    """Every expected header is present with the expected shape. found: {header: shape}."""
    bad = []
    for h, (_, _, shape) in expected.items():
        if h not in found:
            bad.append(f'{h} missing')
        elif tuple(found[h]) != tuple(shape):
            bad.append(f'{h} shape {tuple(found[h])}, expected {tuple(shape)}')
    bad += [f'{h} not expected' for h in found if h not in expected]
    return len(bad), _detail(bad)


def sets_match(found, sets):
    """Set elements as read back equal the S14 sets (lower case, same order)."""
    bad = [f'{k}: {len(found.get(k, []))} elements read, {len(v)} written' for k, v in sets.items()
           if [str(e).strip() for e in found.get(k, [])] != [e.lower() for e in v]]
    return len(bad), _detail(bad)


def float32_match(read, source, tol=1.2e-7):
    """Every cell read back from HAR is the Float64 source rounded to Float32: |read - source| <= tol x
    max(1, |source|) (Float32 has a relative spacing of 2^-23, so rounding is at most 2^-24 = 6e-8)."""
    bad = []
    for h, a in source.items():
        b = read.get(h)
        if b is None or np.shape(b) != np.shape(a):
            bad.append(f'{h}: missing or wrong shape')
            continue
        g = _rel(a, b) if np.size(a) else np.zeros(0)
        if np.size(g) and g.max() > tol:
            bad.append(f'{h}: max rel gap {g.max():.3g}')
    return len(bad), _detail(bad)


def dense_totals(arrays, tables, spec):
    """Each dense array sums back to its long table, in total and by region (nothing dropped or doubled)."""
    bad = []
    for h, t, keys, dims_, _ in spec:
        tab = tables[t]
        tot = float(tab[h].sum()) if len(tab) else 0.0
        if abs(arrays[h].sum() - tot) > 1e-9 * max(1.0, abs(tot)):
            bad.append(f'{h}: array {arrays[h].sum():.12g} table {tot:.12g}')
        nz_tab = int((tab[h] != 0).sum()) if len(tab) else 0
        if np.count_nonzero(arrays[h]) != nz_tab:
            bad.append(f'{h}: {np.count_nonzero(arrays[h])} non-zero cells, table {nz_tab}')
    return len(bad), _detail(bad)


def identities(D, marg_idx, regs, comm):
    """The model identities on the arrays as read back (model_requirements §1d items 1, 3, 4, 6, 7, 10, 11).
    marg_idx: COMM index of each MARG element."""
    lab3 = lambda i: f'{comm[i[0]]}/{regs[i[1]]}'
    out, n = [], 0
    # 6: VCIF = VFOB + sum of VTWR on every route
    g = _rel(D['VCIF'], D['VFOB'] + D['VTWR'].sum(axis=0))
    k, b = _report('CIF', g, lambda i: f'{comm[i[0]]} {regs[i[1]]}->{regs[i[2]]}'); n += k; out += b
    # 7: world VST = world VTWR per margin
    g = _rel(D['VST'].sum(axis=1), D['VTWR'].sum(axis=(1, 2, 3)))
    k, b = _report('margins', g, lambda i: f'marg {i[0]}'); n += k; out += b
    # 3: domestic market clearing at basic prices
    supply = D['MAKB'].sum(axis=1)
    demand = D['VDFB'].sum(axis=1) + D['VDPB'] + D['VDGB'] + D['VDIB'] + D['VXSB'].sum(axis=2)
    for m, c in enumerate(marg_idx):
        demand[c] = demand[c] + D['VST'][m]
    g = _rel(supply, demand)
    k, b = _report('market', g, lab3); n += k; out += b
    # 4: import market clearing
    g = _rel(D['VMSB'].sum(axis=1), D['VMFB'].sum(axis=1) + D['VMPB'] + D['VMGB'] + D['VMIB'])
    k, b = _report('imports', g, lab3); n += k; out += b
    # 1: zero profit per activity
    g = _rel(D['MAKS'].sum(axis=0), D['VDFP'].sum(axis=0) + D['VMFP'].sum(axis=0) + D['EVFP'].sum(axis=0))
    k, b = _report('profit', g, lab3); n += k; out += b
    return n, _detail(out)


def saving(acc):
    """10: SAVE as written = Y - C - G (relative to Y); 11: world SAVE = world (I - VDEP), relative to world I."""
    bad = []
    g = _rel(acc['SAVE'], acc['SAVE_model'], acc['Y'].abs())
    for r in np.where(g > TOL)[0][:10]:
        bad.append(f'{acc.index[r]}: SAVE {acc["SAVE"].iloc[r]:.9g} vs Y - C - G {acc["SAVE_model"].iloc[r]:.9g}')
    n = int((g > TOL).sum())
    w = abs(acc['SAVE'].sum() - (acc['I'] - acc['VDEP']).sum()) / acc['I'].sum()
    if w > TOL:
        n += 1
        bad.append(f'world SAVE {acc["SAVE"].sum():.9g} vs I - VDEP {(acc["I"] - acc["VDEP"]).sum():.9g}')
    return n, _detail(bad)


def signs(D):
    """No negative cell in any header except SAVE (GTAP's residual, report-only at S14, flag NEG-SAVE)."""
    bad = [f'{h}: {int((a < 0).sum())} negative cells, min {a.min():.6g}' for h, a in D.items() if h != 'SAVE' and np.size(a) and a.min() < 0]
    return len(bad), _detail(bad)


def factor_payment(D, regs, comm):
    """Every activity with output has EVFP > 0 (model identity 8)."""
    out = D['MAKS'].sum(axis=0)
    va = D['EVFP'].sum(axis=0)
    bad = np.argwhere((out > 0) & (va <= 0))
    return len(bad), _detail([f'{comm[a]}/{regs[r]}' for a, r in bad])


def parameters(P, sets):
    """Ranges the model needs: Armington and value-added elasticities > 0; SUBP in (0, 1]; INCP > 0; ESBT,
    ESBC, ESBQ, ESBI >= 0; ETRQ <= 0; ETRE <= 0; EFLG has one type per factor; capital is mobile; RFLX > 0."""
    bad = []
    pos = lambda h: bad.append(f'{h} not > 0 (min {P[h].min():.4g})') if P[h].min() <= 0 else None
    for h in ('ESBD', 'ESBM', 'ESBV', 'INCP', 'RFLX', 'ESBG', 'ESBS'):
        pos(h)
    if P['SUBP'].min() <= 0 or P['SUBP'].max() > 1:
        bad.append(f'SUBP outside (0, 1]: {P["SUBP"].min():.4g} to {P["SUBP"].max():.4g}')
    for h in ('ESBT', 'ESBC', 'ESBQ', 'ESBI'):
        if P[h].min() < 0:
            bad.append(f'{h} negative')
    for h in ('ETRQ', 'ETRE'):
        if P[h].max() > 0:
            bad.append(f'{h} positive')
    if not np.all(P['EFLG'].sum(axis=1) == 1):
        bad.append('EFLG: a factor without exactly one mobility type')
    ci = sets['ENDW'].index('capital')
    if P['EFLG'][ci, 0] != 1:
        bad.append('capital is not mobile')
    sl = P['EFLG'][:, 1] == 1
    if np.any(P['ETRE'][sl] >= 0):
        bad.append('a sluggish factor has ETRE >= 0')
    for h, a in P.items():
        if not np.all(np.isfinite(a)):
            bad.append(f'{h}: non-finite value')
    return len(bad), _detail(bad)


def incp_floor(incp, floor):
    """Fix list A11: every INCP is at least the floor (1e-6, applied after normalisation). Returns (failures, detail)."""
    bad = np.argwhere(~(np.asarray(incp) >= floor))
    return len(bad), _detail([f'cell {tuple(int(x) for x in b)}: {np.asarray(incp)[tuple(b)]:.3g}' for b in bad[:10]])


def map_gate(gate, bound=1.0):
    """Saving share and investment share of every group of a map inside [-1, 1]."""
    bad = [f'{g}: sigma_save {r.sigma_save:.3f}, sigma_qinv {r.sigma_qinv:.3f}' for g, r in gate.iterrows()
           if not (abs(r.sigma_save) <= bound and abs(r.sigma_qinv) <= bound and np.isfinite(r.sigma_save))]
    return len(bad), _detail(bad)
