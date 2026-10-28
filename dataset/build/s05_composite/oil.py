"""B8 oil and gas donors (David, 2026-10-24, card; table in config/s05/oil_donors.csv).

A member listed in oil_donors.csv keeps its GTAP 9D donor (nearest GDP per capita) for every column
except the B06 column, which S11 later splits into oil and gas. That column takes the cost structure
(every domestic and imported input, TLS and VA, as a share of output) of an ICIO oil and gas producer.

The swap is done on the donor table in single-region form, before the GDP scaling:
- a product the base donor does not produce at home is bought by the B06 column as an import;
- the input coefficients of every other sector column stay the base donor's;
- final demand, exports and both carried gap columns stay the base donor's cells;
- sector outputs are solved again from the domestic product rows with the new B06 column
  (x' = A' x' + f, where f is the base donor's row remainder: final uses, exports, stock_gap minus
  grev_gap, and the carried 4-decimal row residual), so every domestic product row keeps its
  donor residual and every column keeps its cost total equal to output up to the donor's own residual.
The caller then scales the swapped table to the member's S02 GDP, like any other donor table.

The cost structure of the B06 column is our own choice (IMPROVEMENTS_LOG, S05); GTAP 9D matches
on GDP per capita only.
"""
import csv

import numpy as np

# blend_donors (beta v4 P33 option C): the member's donor_blend gdppc_k3 donors, ';'-joined, largest weight first; S05
# stops if the blend it computes differs while donor_blend is on (the base_donor check under the single-donor rule)
COLUMNS = ['code', 'base_donor', 'oil_donor', 'sector', 'decided_by', 'decided_at', 'basis', 'note', 'blend_donors']
SECTOR = 'B06'


def layout(n_s, n_a):
    """Row and column indices of the S05 single-region table."""
    return dict(X_C=n_a, ST_C=n_a + 1, GR_C=n_a + 2, OUT_C=n_a + 3,
                TLS_R=2 * n_s, VA_R=2 * n_s + 1, OUT_R=2 * n_s + 2)


def read_oil_donors(path):
    """Read and validate config/s05/oil_donors.csv. Returns {code: row dict}. Raises ValueError."""
    with open(path, newline='') as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != COLUMNS:
            raise ValueError(f'oil_donors.csv columns {reader.fieldnames}, expected {COLUMNS}')
        rows = [{k: (v or '').strip() for k, v in r.items()} for r in reader]
    if not rows:
        raise ValueError('oil_donors.csv has no rows')
    out = {}
    for r in rows:
        for k in ('code', 'base_donor', 'oil_donor', 'sector', 'decided_by', 'decided_at', 'basis'):
            if not r[k]:
                raise ValueError(f'oil_donors.csv row {r["code"] or "?"}: {k} is blank')
        if r['sector'] != SECTOR:
            raise ValueError(f'oil_donors.csv row {r["code"]}: sector {r["sector"]}, only {SECTOR} is allowed')
        if r['oil_donor'] == r['base_donor']:
            raise ValueError(f'oil_donors.csv row {r["code"]}: oil donor equals base donor')
        if r['oil_donor'] == r['code']:
            raise ValueError(f'oil_donors.csv row {r["code"]}: oil donor is the member itself')
        if r['code'] in out:
            raise ValueError(f'oil_donors.csv: duplicate code {r["code"]}')
        out[r['code']] = r
    return out


CHECK_COLUMNS = ['code', 'flag', 'decided_by', 'decided_at', 'reason', 'evidence', 'note',
                 'resolved_by', 'resolved_at', 'resolution']
FLAG_OPEN = 'OIL-CHECK-POST-ENERGY'
FLAG_RESOLVED = 'OIL-CHECK-RESOLVED'


def read_oil_check(path, oil_donors):
    """Read and validate config/s05/oil_check_codes.csv against the oil donor table.

    An open row (OIL-CHECK-POST-ENERGY) must not be a member whose B06 column is switched; a resolved row
    (OIL-CHECK-RESOLVED) must be one, with resolved_by, resolved_at and resolution filled. Raises ValueError."""
    with open(path, newline='') as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != CHECK_COLUMNS:
            raise ValueError(f'oil_check_codes.csv columns {reader.fieldnames}, expected {CHECK_COLUMNS}')
        rows = [{k: (v or '').strip() for k, v in r.items()} for r in reader]
    if not rows:
        raise ValueError('oil_check_codes.csv has no rows')
    out = {}
    for r in rows:
        for k in ('code', 'flag', 'decided_by', 'decided_at', 'reason', 'evidence'):
            if not r[k]:
                raise ValueError(f'oil_check_codes.csv row {r["code"] or "?"}: {k} is blank')
        if r['code'] in out:
            raise ValueError(f'oil_check_codes.csv: duplicate code {r["code"]}')
        switched = r['code'] in oil_donors
        if r['flag'] == FLAG_OPEN:
            if switched:
                raise ValueError(f'oil_check_codes.csv row {r["code"]}: its B06 column is switched in '
                                 f'oil_donors.csv, so the flag must be {FLAG_RESOLVED}')
            if r['resolved_by'] or r['resolved_at'] or r['resolution']:
                raise ValueError(f'oil_check_codes.csv row {r["code"]}: an open flag carries a resolution')
        elif r['flag'] == FLAG_RESOLVED:
            if not switched:
                raise ValueError(f'oil_check_codes.csv row {r["code"]}: resolved but not in oil_donors.csv')
            for k in ('resolved_by', 'resolved_at', 'resolution'):
                if not r[k]:
                    raise ValueError(f'oil_check_codes.csv row {r["code"]}: {k} is blank on a resolved flag')
        else:
            raise ValueError(f'oil_check_codes.csv row {r["code"]}: unknown flag {r["flag"]}')
        out[r['code']] = r
    return out


def cost_shares(T, j, n_s, n_a):
    """Cost rows (domestic, imported, TLS, VA) of sector column j over its output."""
    L = layout(n_s, n_a)
    out = float(T[L['OUT_R'], j])
    if not out > 0:
        raise ValueError(f'column {j} has no positive output')
    return T[:L['OUT_R'], j] / out


def target_shares(T_base, T_oil, j, n_s, n_a):
    """The cost shares the swapped column must have: the oil donor's, except that a product the base
    table does not produce at home is bought as an import (its domestic share moves to the import row)."""
    L = layout(n_s, n_a)
    sh = cost_shares(T_oil, j, n_s, n_a).copy()
    none = np.flatnonzero(~(T_base[L['OUT_R'], :n_s] > 0))
    sh[n_s + none] += sh[none]
    sh[none] = 0.0
    return sh


def swap_column(T_base, T_oil, j, n_s, n_a):
    """Return (T_new, info): T_base with sector column j given T_oil's cost structure.

    Outputs are solved again with every other column's coefficients and every row remainder fixed."""
    L = layout(n_s, n_a)
    OUT_R, OUT_C = L['OUT_R'], L['OUT_C']
    T = np.asarray(T_base, dtype=np.float64)
    x = T[OUT_R, :n_s].copy()
    if np.max(np.abs(x - T[:n_s, OUT_C])) != 0.0:
        raise ValueError('the OUT row and the OUT column of the base table differ')
    if not x[j] > 0:
        raise ValueError(f'base table column {j} has no positive output')
    # Sectors with no output in the base table keep their cells and their zero output. Their domestic rows
    # are not re-solved; the B06 column buys those products as imports (target_shares). Any other use of
    # them by a re-solved column would move their row residual (check_swap rule 4 catches that).
    act = np.flatnonzero(x > 0)
    coef = T[:OUT_R, :n_s][:, act] / x[act]
    coef[:, np.searchsorted(act, j)] = target_shares(T, T_oil, j, n_s, n_a)
    f = T[:n_s, OUT_C] - T[:n_s, act].sum(axis=1)     # row remainder, with the fixed columns' cells in it
    A = coef[act, :]
    x_act = np.linalg.solve(np.eye(len(act)) - A, f[act])
    x_new = x.copy()
    x_new[act] = x_act
    T_new = T.copy()
    T_new[:OUT_R, act] = coef * x_act
    T_new[OUT_R, :n_s] = x_new
    T_new[:n_s, OUT_C] = x_new
    info = dict(out_before=float(x[j]), out_after=float(x_new[j]), min_out=float(x_new.min()),
                max_rel_out_change=float(np.max(np.abs(x_act / x[act] - 1.0))),
                fixed_cols=int(n_s - len(act)))
    return T_new, info


def check_swap(T_base, T_oil, T_new, j, n_s, n_a, tol=1e-9):
    """Independent property check of one swapped table. Returns a list of problems (empty = pass).

    1. Column j cost shares equal the oil donor's (abs tol).
    2. Every other sector column with output keeps the base donor's cost shares (abs tol).
    3. Final-demand, export and gap columns are the base donor's cells (rel tol).
    4. Every domestic product row keeps the base donor's residual: uses + X + stock_gap - grev_gap - OUT.
    5. Outputs are not negative, and the OUT row equals the OUT column."""
    L = layout(n_s, n_a)
    OUT_R, OUT_C = L['OUT_R'], L['OUT_C']
    X_C, ST_C, GR_C = L['X_C'], L['ST_C'], L['GR_C']
    probs = []
    d = np.max(np.abs(cost_shares(T_new, j, n_s, n_a) - target_shares(T_base, T_oil, j, n_s, n_a)))
    if d > tol:
        probs.append(f'column {j} share gap to the oil donor {d:.3e}')
    for k in range(n_s):
        if k == j or not T_base[OUT_R, k] > 0:
            continue
        if not T_new[OUT_R, k] > 0:
            probs.append(f'column {k} lost its output')
            continue
        d = np.max(np.abs(cost_shares(T_new, k, n_s, n_a) - cost_shares(T_base, k, n_s, n_a)))
        if d > tol:
            probs.append(f'column {k} share gap to the base donor {d:.3e}')
    fixed = list(range(n_s, n_a)) + [X_C, ST_C, GR_C]
    a, b = T_new[:, fixed], T_base[:, fixed]
    d = np.max(np.abs(a - b) / np.maximum(np.maximum(np.abs(a), np.abs(b)), 1.0))
    if d > tol:
        probs.append(f'final-demand, export or gap cell moved, max rel {d:.3e}')

    def row_resid(T):
        return (T[:n_s, :n_a].sum(axis=1) + T[:n_s, X_C] + T[:n_s, ST_C] - T[:n_s, GR_C] - T[:n_s, OUT_C])

    scale = np.maximum(np.abs(T_new[:n_s, OUT_C]), 1.0)
    d = np.max(np.abs(row_resid(T_new) - row_resid(T_base)) / scale)
    if d > tol:
        probs.append(f'domestic row residual changed, max rel {d:.3e}')
    if T_new[OUT_R, :n_s].min() < 0:
        probs.append(f'negative output {T_new[OUT_R, :n_s].min():.6f}')
    if np.max(np.abs(T_new[OUT_R, :n_s] - T_new[:n_s, OUT_C])) > tol * max(1.0, float(np.abs(T_new[OUT_R, :n_s]).max())):
        probs.append('OUT row and OUT column differ')
    return probs
