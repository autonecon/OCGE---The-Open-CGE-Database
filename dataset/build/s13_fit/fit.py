"""The FIT information problem of GTAP 12 ch.17A, solved one region at a time.

GTAP's information function (eq. 17.1 + 17.2, weights 1 as in the GEMPACK code, footnote 6) is
    I = sum_a E_a sum_c S^t_ca ln(S^t_ca / S^t0_ca) + sum_a E_a sum_c S^t_ca sum_s S^s_sca ln(S^s_sca / S^s0_sca).
Because the cell share of column a is S^t_ca * S^s_sca, the two terms add up to
    I = sum_a E_a sum_k theta_ka ln(theta_ka / theta0_ka),
the cross-entropy of each column's cost shares at agents' prices (with value added as one share of an
activity, eq. 17.43), weighted by the column total E_a.

The model is GTAP's eq. 17.41-17.46 with 17.22 and 17.28. The cost shares of a column satisfy the first-order
conditions theta_ka = theta0_ka exp(-g_ka) / Z_a, where g_ka = coefficient_k * lambda_(row of k) and lambda is
non-zero only on a priced row:
  - an import row (mu^m_c, eq. 17.16);
  - the market-clearing row of an activity whose output is held (the S11 energy output targets; this takes the
    place of GTAP's IEA energy constraints mu^iea, eq. 17.8-17.9).
The domestic cells and value added of a column carry no other shadow price, so they move only with the
column's adding-up price mu^t_a (Z_a here). An activity whose output is free gets it from its own
market-clearing row (eq. 17.28), with costs equal to output (eq. 17.22); there is no optimality condition
on E_a. The unknowns (lambda on priced rows, ln E of the free columns) are found by Newton's method on the
priced and market-clearing rows with a backtracking line search.

A Problem is plain arrays so that the solver can be tested on small hand-made cases.
"""
import numpy as np


class Column:
    """One agent: adjustable cells (constraint row or -1, coefficient, prior value), a fixed part and a total.
    total is None for a free column (an activity whose output the fit sets), else the fixed column total."""

    def __init__(self, name, rows, coefs, prior, fixed=0.0, total=None, own_row=-1, own_coef=0.0, groups=None, fixed_basic=None):
        self.name = name
        self.rows = np.asarray(rows, int)
        self.coefs = np.asarray(coefs, float)
        self.prior = np.asarray(prior, float)
        self.fixed = float(fixed)
        # held cells (round 3, final QA 2 item 3; s13 choice power_fuel_cells): basic values fixed by cell, not adjustable
        # (their prior is 0 in the cross-entropy). Their purchasers' value is fixed_basic / coef, so it follows the cell's
        # tax power if that is reset between passes; their basic value enters the cell's row as a constant.
        self.fixed_basic = np.zeros(len(self.prior)) if fixed_basic is None else np.asarray(fixed_basic, float)
        if self.fixed_basic.shape != self.prior.shape or (self.fixed_basic < 0).any() or \
                ((self.fixed_basic > 0) & ((self.rows < 0) | (self.coefs == 0) | (self.prior > 0))).any():
            raise ValueError(f'{name}: a held cell needs a row, a non-zero coefficient, no adjustable prior and a non-negative value')
        self.total = total
        self.own_row = own_row      # market-clearing row in which this column's output appears (activities)
        self.own_coef = own_coef    # its coefficient there (minus the power of the output tax)
        if (self.prior < 0).any():
            raise ValueError(f'{name}: negative prior cell')
        s = self.prior.sum()
        self.theta0 = self.prior / s if s > 0 else self.prior
        # share groups: every cell is in one group, and each group keeps its prior share of the column (the
        # column's other cells, group 0, share what the held groups leave). One group (the default) is GTAP's
        # eq. 17.5 alone; a held group (choice own_use_share) adds an adding-up constraint on its share.
        self.groups = np.zeros(len(self.prior), int) if groups is None else np.asarray(groups, int)
        if self.groups.shape != self.prior.shape or (self.groups < 0).any():
            raise ValueError(f'{name}: groups must give one non-negative group per cell')
        self.gid = np.unique(self.groups)
        self.H = np.array([self.theta0[self.groups == g].sum() for g in self.gid])

    def fixed_pv(self):
        """Purchasers' values of the held cells at the current coefficients."""
        return np.divide(self.fixed_basic, self.coefs, out=np.zeros_like(self.fixed_basic), where=self.fixed_basic > 0)

    def held(self):
        """Fixed part of the column: the fixed scalar plus the held cells at purchasers' values."""
        return self.fixed + float(self.fixed_pv().sum())


class Problem:
    """Constraint rows: sum over cells of coef * v + sum over free columns of own_coef * E + d = 0."""

    def __init__(self, row_names, d, columns):
        self.row_names = list(row_names)
        self.base = np.asarray(d, float).copy()
        self.columns = columns
        m = len(self.row_names)
        for c in columns:          # held cells: their basic value is a constant of their row
            k = c.fixed_basic > 0
            np.add.at(self.base, c.rows[k], c.fixed_basic[k])
        self.free = [c for c in columns if c.total is None]
        self.fixedcols = [c for c in columns if c.total is not None]
        for c in self.fixedcols:
            c.target = c.total
        self.set_totals()
        used = np.zeros(m, bool)
        for c in columns:
            used[c.rows[(c.rows >= 0) & (c.theta0 > 0)]] = True
            if c.total is None and c.own_row >= 0:
                used[c.own_row] = True
        self.active = np.where(used)[0]
        self.inactive = np.where(~used)[0]
        # a free activity's market-clearing row sets its output (eq. 17.28) and carries no shadow price
        self.priced = np.ones(m, bool)
        for c in self.free:
            if c.own_row >= 0:
                self.priced[c.own_row] = False
        if any(c.own_row < 0 for c in self.free):
            raise ValueError('a free column needs its own market-clearing row')

    def set_totals(self, shift=None):
        """d from the current fixed-column totals; shift is subtracted (the homotopy start offset)."""
        self.d = self.base.copy()
        # a fixed-total activity puts its known output into its market-clearing row as a constant
        for c in self.fixedcols:
            if c.own_row >= 0:
                self.d[c.own_row] += c.own_coef * c.total
        # each free column's fixed part also enters its own row
        for c in self.free:
            if c.own_row >= 0:
                self.d[c.own_row] += c.own_coef * c.held()
        if shift is not None:
            self.d -= shift


def _shares(col, lam):
    """Cell shares theta0 exp(-g) normalised within each share group to the group's prior share H (one group:
    the column's adding-up price mu^t_a, eq. 17.5)."""
    g = np.where(col.rows >= 0, col.coefs * lam[np.maximum(col.rows, 0)], 0.0)
    g = np.where(col.theta0 > 0, g, 0.0)
    s = np.zeros_like(col.theta0)
    for gi, H in zip(col.gid, col.H):
        k = (col.groups == gi) & (col.theta0 > 0)
        if not k.any() or H <= 0:
            continue
        gk = g[k] - g[k].min()
        w = col.theta0[k] * np.exp(-gk)
        s[k] = H * w / w.sum()
    return s


def evaluate(P, lam, lnE):
    """Residuals of every row and Jacobian in (lam, lnE) at (lam, lnE). lam is zero on unpriced rows.
    Returns r (m), J (m x (m + nf)), the cell values per column and the totals."""
    m, nf = len(P.row_names), len(P.free)
    r = P.d.copy()
    J = np.zeros((m, m + nf))
    vals, tots = {}, {}
    fidx = {c.name: j for j, c in enumerate(P.free)}
    for col in P.columns:
        s = _shares(col, lam)
        held = col.held()
        if col.total is None:
            j = fidx[col.name]
            E = np.exp(lnE[j])
            adj = E
        else:
            E = col.total
            adj = col.total - held
        v = adj * s
        vals[col.name] = v + col.fixed_pv() if held != col.fixed else v
        tots[col.name] = E + held if col.total is None else col.total
        k = col.rows >= 0
        rows, a, sk, gk = col.rows[k], col.coefs[k], s[k], col.groups[k]
        np.add.at(r, rows, a * v[k])
        w = np.zeros(m)
        np.add.at(w, rows, a * sk)
        # within share group G (prior share H_G): d v_k / d lambda_i = -v_k (a_k [i == row_k] - w^G_i / H_G)
        Hd = np.zeros(m)
        np.add.at(Hd, rows, a * a * sk)
        J[:, :m] -= adj * np.diag(Hd)
        for gi, H in zip(col.gid, col.H):
            if H <= 0:
                continue
            wg = np.zeros(m)
            q = gk == gi
            np.add.at(wg, rows[q], a[q] * sk[q])
            J[:, :m] += adj * np.outer(wg, wg) / H
        if col.total is None:
            r[col.own_row] += col.own_coef * E
            # d r / d lnE_j = E * w + own_coef * E e_own
            J[:, m + j] += E * w
            J[col.own_row, m + j] += col.own_coef * E
    return r, J, vals, tots


def _newton(P, lam, lnE, sc, eq, var, tol, maxit, log):
    m = len(P.row_names)

    def merit(r):
        return float(np.sum((r[eq] / sc[eq]) ** 2))

    r, J, vals, tots = evaluate(P, lam, lnE)
    f = merit(r)
    it = 0
    for it in range(1, maxit + 1):
        if np.max(np.abs(r[eq] / sc[eq])) < tol:
            break
        Ja = J[np.ix_(eq, var)]
        try:
            step = np.linalg.solve(Ja, -r[eq])
        except np.linalg.LinAlgError:
            step = np.linalg.lstsq(Ja, -r[eq], rcond=None)[0]
        z = np.concatenate([lam, lnE])
        t = 1.0
        while True:
            zn = z.copy()
            zn[var] += t * step
            with np.errstate(over='ignore', invalid='ignore'):
                rn, Jn, vn, tn = evaluate(P, zn[:m], zn[m:])
                fn = merit(rn)
            if np.isfinite(fn) and fn <= (1 - 1e-4 * t) * f:
                break
            t *= 0.5
            if t < 1e-12:
                break
        if t < 1e-12:
            break
        lam, lnE = zn[:m], zn[m:]
        r, J, vals, tots, f = rn, Jn, vn, tn, fn
        if log:
            log(f'  it {it} step {t:.3g} merit {f:.3e}')
    conv = bool(np.max(np.abs(r[eq] / sc[eq])) < tol)
    return conv, it, lam, lnE, r, vals, tots


def solve(P, tol=1e-9, maxit=60, log=None, min_step=1.0 / 1024, start=None):
    """Newton on the first-order conditions, along a homotopy from the prior (path parameter 0, where the
    prior solves the shifted conditions exactly) to the targets (1), as GEMPACK applies the FIT shocks in
    steps. start: (lam, lnE) of an earlier solution of the same problem with slightly different coefficients
    (s13 product_tax_totals passes); Newton is first tried from there at the targets, and the homotopy runs only
    if that does not converge. Returns dict(ok, it, lam, lnE, vals, tots, resid, worst, path)."""
    m, nf = len(P.row_names), len(P.free)
    if start is not None:
        for c in P.fixedcols:
            c.total = c.target
        P.set_totals()
        sc = np.maximum(1.0, np.abs(P.base))
        eq = P.active
        var = np.concatenate([P.active[P.priced[P.active]], m + np.arange(nf)])
        conv, it, lam, lnE, r, vals, tots = _newton(P, np.asarray(start[0], float).copy(), np.asarray(start[1], float).copy(),
                                                    sc, eq, var, tol, maxit, None)
        if conv:
            rel = np.abs(r[eq] / sc[eq])
            neg = [c.name for c in P.fixedcols if c.target - c.held() < 0]
            inact_ok = bool(np.all(np.abs(P.d[P.inactive]) <= 1e-9 * np.maximum(1.0, np.abs(P.base[P.inactive]))))
            if not neg and inact_ok:
                worst = [(P.row_names[eq[i]], float(r[eq[i]])) for i in np.argsort(-rel)[:5]]
                return dict(ok=True, it=it, lam=lam, lnE=lnE, vals=vals, tots=tots, resid=float(rel.max()), worst=worst, t=1.0)
    lam = np.zeros(m)
    lnE = np.array([np.log(max(c.prior.sum(), 1e-300)) if c.prior.sum() > 0 else -700.0 for c in P.free])
    tot1 = {c.name: c.target for c in P.fixedcols}
    tot0 = {c.name: c.prior.sum() + c.held() for c in P.fixedcols}
    for c in P.fixedcols:
        c.total = tot0[c.name]
    P.set_totals()
    r0, _, _, _ = evaluate(P, lam, lnE)
    shift = r0.copy()
    sc = np.maximum(1.0, np.abs(P.base))
    eq = P.active
    var = np.concatenate([P.active[P.priced[P.active]], m + np.arange(nf)])

    def at(t):
        for c in P.fixedcols:
            c.total = tot0[c.name] + t * (tot1[c.name] - tot0[c.name])
        P.set_totals(shift * (1.0 - t))

    t, h, its, path = 0.0, 1.0, 0, []
    while t < 1.0:
        tn = min(1.0, t + h)
        at(tn)
        conv, it, l2, e2, r, vals, tots = _newton(P, lam, lnE, sc, eq, var, tol if tn == 1.0 else 1e-7, maxit, None)
        its += it
        if conv:
            t, lam, lnE = tn, l2, e2
            path.append((tn, it))
            if it <= 6:
                h = min(1.0, h * 2)
        else:
            h /= 2
            if h < min_step:
                break
    at(t if t < 1.0 else 1.0)
    if t < 1.0:
        at(1.0)
    r, J, vals, tots = evaluate(P, lam, lnE)
    rel = np.abs(r[eq] / sc[eq])
    inact = P.d[P.inactive]
    neg = [c.name for c in P.fixedcols if c.target - c.held() < 0]     # a fixed column below its fixed part needs negative cells
    ok = not neg and bool(t >= 1.0) and bool(rel.max() < tol) and bool(np.all(np.abs(inact) <= 1e-9 * np.maximum(1.0, np.abs(P.base[P.inactive]))))
    worst = []
    for i in np.argsort(-rel)[:5]:
        worst.append((P.row_names[eq[i]], float(r[eq[i]])))
    worst += [(f'column {n} total below its fixed part (negative cells)', 0.0) for n in neg]
    for i in P.inactive:
        if abs(P.d[i]) > 1e-9 * max(1.0, abs(P.base[i])):
            worst.append((P.row_names[i] + ' (no variable can meet it)', float(P.d[i])))
    if log:
        log(f'  path {path}; reached t={t}')
    return dict(ok=ok, it=its, lam=lam, lnE=lnE, vals=vals, tots=tots, resid=float(rel.max()), worst=worst, t=t)


def information(P, vals, tots):
    """GTAP's total information I (eq. 17.4 with unit weights) at the solution, in USD million."""
    tot = 0.0
    for col in P.columns:
        v = vals[col.name] - col.fixed_pv()          # the adjustable cells only (held cells are not in the cross-entropy)
        adj = v.sum()
        if adj <= 0:
            continue
        th = v / adj
        k = th > 0
        tot += adj * float(np.sum(th[k] * np.log(th[k] / col.theta0[k])))
    return tot
