"""Beta v4 G4 (S03 choice household_employers_va): the value added of activities of households as employers (ICIO T).

OECD ICIO 2025 ZAF T carries 44.0 bn USD of VA (10.9% of GDP), all sold to ZAF households, while ZAF O, P and Q carry
far less VA than FIGARO's compensation of employees there: public-sector pay sits in T. For each economy in
config/s03/household_employers_2022.csv, T's VA and output are set to the sourced value of paid domestic work
(workers x monthly pay x months, at the WDI 2022 exchange rate), and the rest moves to the recipient industries in
proportion to their FIGARO 2022 compensation of employees (D1); the same amount of the T purchase by households
(HFCE) becomes government consumption (GGFC) of the recipients. Each recipient gains the same VA, output and sales,
and T loses them, so every column and row stays balanced. A labelled source correction (no GTAP text covers it).

Value hfce_to_pq (the default since the S02-S06 build QA, 26 Oct): the GGFC version left ZAF table G 57% above WDI and C
17% below, because the 42.6 bn is household spending booked in the wrong industry. The rest moves to P and Q only (by
FIGARO D1 of P85 and Q86-Q88) and the purchase stays in HFCE, reassigned from T to P and Q, so C and G keep their totals.

Value hfce_by_coicop (beta v5 H, the default; David 2026-10-27 08:39 UTC): hfce_to_pq left ZAF households spending 14.8% of
their budget on education (P) and 9.3% on health (Q). Here P and Q take their FIGARO D1 parts only up to the room left
under the economy's own household spending by purpose (COICOP 10 education, COICOP 06 health; config/s03/
hfce_coicop_caps_2022.csv) times its ICIO HFCE total at purchasers' prices (industry rows plus TLS); the room is the cap less
what households already buy from P or Q (all origins). The rest goes to the other services households buy (OTHER_SERVICES),
in proportion to the economy's household purchases of each from its own industry, with VA and output moved the same way.
C and G keep their totals. The cap and the spread are ours (labelled; no GTAP text covers it).
"""
import csv
import json
import os

import numpy as np

CHOICE = 'household_employers_va'
IMPLEMENTED = 'listed_economies_t_va_at_domestic_workers_x_median_pay_rest_to_o_p_q_by_figaro_d1_households_purchase_to_government'
HFCE_TO_PQ = 'listed_economies_t_va_at_domestic_workers_x_median_pay_rest_to_p_q_by_figaro_d1_households_purchase_kept_in_hfce'
HFCE_BY_COICOP = ('listed_economies_t_va_at_domestic_workers_x_median_pay_rest_to_p_q_by_figaro_d1_up_to_the_hfce_by_coicop_share_'
                  'rest_to_other_household_services')
VALUES = (HFCE_BY_COICOP, HFCE_TO_PQ, IMPLEMENTED, 'off')
HFCE_VALUES = (HFCE_BY_COICOP, HFCE_TO_PQ)      # the purchase stays in HFCE
# hfce_by_coicop: services (ICIO 2025 industries) households buy that take the part of the move above the P and Q caps;
# not O (public administration), P and Q (capped), T (the source)
OTHER_SERVICES = ('G', 'H49', 'H50', 'H51', 'H52', 'H53', 'I', 'J58T60', 'J61', 'J62_63', 'K', 'L', 'M', 'N', 'R', 'S')
CAP_COLUMNS = ('economy', 'industry', 'coicop', 'value_lcu', 'hfce_lcu', 'source', 'decided_by', 'decided_at', 'basis')
HFCE_RECIPIENTS = ('P', 'Q')        # hfce_to_pq: education and health, which households buy; public administration (O) is not
CG_TOL = 0.02                       # S03-Hhhecg: the economy's HFCE and GGFC totals move by at most 2%
CHOICE_COLUMNS = ('choice', 'value', 'decided_by', 'decided_at', 'basis', 'gtap_status')
COLUMNS = ('economy', 'workers_thousand', 'monthly_pay_lcu', 'months', 'fx_iso3', 'recipients', 'figaro_country', 'source', 'url',
           'decided_by', 'decided_at', 'basis')
# ICIO 2025 industry -> FIGARO (NACE) columns whose D1 weights it
FIGARO_OF = {'O': ('O84',), 'P': ('P85',), 'Q': ('Q86', 'Q87_88')}
HHE = 'T'


def load_choice(path):
    """config/s03/s03_choices.csv -> the value of household_employers_va (one of VALUES); stop on any other value or a blank
    attribution."""
    with open(path, newline='') as fh:
        rd = csv.DictReader(fh)
        if tuple(rd.fieldnames or ()) != CHOICE_COLUMNS:
            raise SystemExit(f'{path}: columns {rd.fieldnames} are not {CHOICE_COLUMNS}')
        rows = {r['choice']: r for r in rd}
    if set(rows) != {CHOICE}:
        raise SystemExit(f'{path}: choices {sorted(rows)} are not [{CHOICE!r}]')
    r = rows[CHOICE]
    if r['value'] not in VALUES or not r['decided_by'].strip() or not r['decided_at'].strip():
        raise SystemExit(f'{path}: {CHOICE} value {r["value"]!r} or its attribution is not valid')
    return r['value']


def recipients_for(value, listed):
    """The recipient industries of a config row under the choice value: all listed ones (GGFC version) or the listed ones among
    HFCE_RECIPIENTS (hfce_to_pq)."""
    if value in HFCE_VALUES:
        out = [x for x in listed if x in HFCE_RECIPIENTS]
        if not out:
            raise SystemExit(f'household_employers_2022.csv: no recipient among {HFCE_RECIPIENTS} in {listed}')
        return out
    return list(listed)


def load_rows(path):
    """config/s03/household_employers_2022.csv -> list of rows (may be empty); stop on a missing column or source."""
    with open(path, newline='') as fh:
        rd = csv.DictReader(fh)
        if tuple(rd.fieldnames or ()) != COLUMNS:
            raise SystemExit(f'{path}: columns {rd.fieldnames} are not {COLUMNS}')
        rows = list(rd)
    seen = set()
    for r in rows:
        if r['economy'] in seen or not all(r[c].strip() for c in ('source', 'decided_by', 'decided_at')):
            raise SystemExit(f'{path}: row {r["economy"]} is listed twice or has no source or attribution')
        seen.add(r['economy'])
        for c in ('workers_thousand', 'monthly_pay_lcu', 'months'):
            if not float(r[c]) > 0:
                raise SystemExit(f'{path}: {r["economy"]} {c} must be positive')
    return rows


def target_musd(row, lcu_per_usd):
    """Value of paid domestic work, USD million: workers (thousand) x monthly pay x months / LCU per USD."""
    return float(row['workers_thousand']) * 1e3 * float(row['monthly_pay_lcu']) * float(row['months']) / float(lcu_per_usd) / 1e6


def figaro_d1(path, country, recipients):
    """{ICIO industry: FIGARO 2022 D1 (million EUR)} of the recipients for one FIGARO country (JSON-stat 2.0 file)."""
    d = json.load(open(path))
    ids, size, dims, val = d['id'], d['size'], d['dimension'], d['value']
    idx = {k: dims[k]['category']['index'] for k in ids}
    fixed = dict(ind_ava='D1', c_dest=country, c_orig='DOM')

    def get(ind):
        pos = 0
        for k, s in zip(ids, size):
            want = ind if k == 'ind_use' else fixed.get(k)
            i = idx[k][want] if want is not None else 0
            pos = pos * s + i
        v = val.get(str(pos)) if isinstance(val, dict) else val[pos]
        return float(v or 0.0)
    out = {}
    for r in recipients:
        if r not in FIGARO_OF:
            raise SystemExit(f'household_employers_2022.csv: no FIGARO map for recipient {r!r}')
        out[r] = sum(get(x) for x in FIGARO_OF[r])
    return out


def reallocate(A, rows, cols, economy, target, weights, to='GGFC', parts=None):
    """Move T's VA and output above `target` (USD million) to the recipients, in place on the published ICIO matrix A
    (rows/cols the ICIO labels; rows end TLS, VA, OUT; the last column is OUT). weights: {industry: weight > 0}.
    The T sale to the economy's HFCE falls by the moved amount and each recipient's sale to its `to` column ('GGFC', or
    'HFCE' for hfce_to_pq) rises by its part. Returns dict(va_before, target, moved, parts {industry: USD million},
    hfce_t_before, cg_before, cg_after), cg the economy's (HFCE total, GGFC total) over the industry rows.
    parts (hfce_by_coicop): {industry: USD million} that replaces the split by weights; it must sum to the amount moved."""
    if to not in ('GGFC', 'HFCE'):
        raise SystemExit(f'household_employers: unknown destination {to!r}')
    ri = {r: i for i, r in enumerate(rows)}
    ci = {c: j for j, c in enumerate(cols)}
    t = f'{economy}_{HHE}'
    va_t = float(A[ri['VA'], ci[t]])
    moved = va_t - float(target)
    hf = float(A[ri[t], ci[f'{economy}_HFCE']])
    ind = [i for i, r in enumerate(rows) if r not in ('TLS', 'VA', 'OUT')]

    def cg():
        return tuple(float(A[ind, ci[f'{economy}_{c}']].sum()) for c in ('HFCE', 'GGFC'))
    cg0 = cg()
    if not moved > 0:
        return dict(va_before=va_t, target=float(target), moved=0.0, parts={}, hfce_t_before=hf, cg_before=cg0, cg_after=cg0)
    if hf < moved - 1e-9:
        raise SystemExit(f'household_employers: {economy} T sale to HFCE {hf:.1f} is below the amount to move {moved:.1f}')
    if parts is None:
        W = sum(weights.values())
        if not W > 0 or any(w < 0 for w in weights.values()):
            raise SystemExit(f'household_employers: {economy} recipient weights {weights} are not positive')
        parts = {k: moved * w / W for k, w in weights.items()}
    elif abs(sum(parts.values()) - moved) > 1e-6 * max(1.0, moved) or any(x < 0 for x in parts.values()):
        raise SystemExit(f'household_employers: {economy} parts {parts} do not sum to the amount moved {moved:.3f}')
    parts = {k: x for k, x in parts.items() if x > 0}
    A[ri[t], ci[f'{economy}_HFCE']] -= moved
    A[ri['VA'], ci[t]] -= moved
    A[ri['OUT'], ci[t]] -= moved
    A[ri[t], ci['OUT']] -= moved
    for k, x in parts.items():
        s = f'{economy}_{k}'
        A[ri[s], ci[f'{economy}_{to}']] += x
        A[ri['VA'], ci[s]] += x
        A[ri['OUT'], ci[s]] += x
        A[ri[s], ci['OUT']] += x
    return dict(va_before=va_t, target=float(target), moved=moved, parts=parts, hfce_t_before=hf, cg_before=cg0, cg_after=cg())


def wdi_rate(path, iso3, year=2022):
    """WDI PA.NUS.FCRF (LCU per USD) from the extract csv (series, iso3, year, value)."""
    with open(path, newline='') as fh:
        for r in csv.reader(fh):
            if len(r) >= 4 and r[0] == 'PA.NUS.FCRF' and r[1] == iso3 and r[2] == str(year):
                return float(r[3])
    raise SystemExit(f'WDI extract {os.path.basename(path)} has no PA.NUS.FCRF {iso3} {year}')


def moved_amount(A, rows, cols, economy, target):
    """T's VA above the target (USD million), the amount reallocate moves."""
    ri = {r: i for i, r in enumerate(rows)}
    ci = {c: j for j, c in enumerate(cols)}
    return max(0.0, float(A[ri['VA'], ci[f'{economy}_{HHE}']]) - float(target))


def load_caps(path):
    """config/s03/hfce_coicop_caps_2022.csv -> {economy: {industry: share of HFCE}}; stop on a missing column, source or
    attribution, a share outside (0, 1) or an industry other than P and Q."""
    with open(path, newline='') as fh:
        rd = csv.DictReader(fh)
        if tuple(rd.fieldnames or ()) != CAP_COLUMNS:
            raise SystemExit(f'{path}: columns {rd.fieldnames} are not {CAP_COLUMNS}')
        rows = list(rd)
    out = {}
    for r in rows:
        if r['industry'] not in HFCE_RECIPIENTS or not all(r[c].strip() for c in ('source', 'decided_by', 'decided_at')):
            raise SystemExit(f'{path}: row {r["economy"]} {r["industry"]} has an industry outside {HFCE_RECIPIENTS} or no source')
        sh = float(r['value_lcu']) / float(r['hfce_lcu'])
        if not 0 < sh < 1 or r['industry'] in out.get(r['economy'], {}):
            raise SystemExit(f'{path}: {r["economy"]} {r["industry"]} share {sh} is not in (0, 1) or is listed twice')
        out.setdefault(r['economy'], {})[r['industry']] = sh
    return out


def household_purchases(A, rows, cols, economy):
    """(the economy's HFCE total at purchasers' prices: industry rows plus TLS, {industry: households' purchase from all
    origins}, {industry: households' purchase from the economy's own industry}) in USD million."""
    ci = {c: j for j, c in enumerate(cols)}
    h = A[:, ci[f'{economy}_HFCE']]
    total, by, own = 0.0, {}, {}
    for i, r in enumerate(rows):
        if r == 'TLS':
            total += float(h[i])
        if r in ('TLS', 'VA', 'OUT') or '_' not in r:
            continue
        o, ind = r.split('_', 1)
        total += float(h[i])
        by[ind] = by.get(ind, 0.0) + float(h[i])
        if o == economy:
            own[ind] = float(h[i])
    return total, by, own


def coicop_parts(moved, d1_weights, caps, total, by, own, others=OTHER_SERVICES):
    """hfce_by_coicop: split `moved` (USD million). Each capped recipient (P, Q) takes its FIGARO D1 part, at most the room
    under its cap (share x total less what households already buy from it); the rest goes to `others` in proportion to the
    households' purchases of each from the economy's own industry. Returns (parts, {industry: (cap, before, room)})."""
    W = sum(d1_weights.values())
    if not W > 0:
        raise SystemExit(f'household_employers: recipient weights {d1_weights} are not positive')
    parts, info = {}, {}
    for k, w in d1_weights.items():
        want = moved * w / W
        if k in caps:
            cap = caps[k] * total
            room = max(0.0, cap - by.get(k, 0.0))
            info[k] = (cap, by.get(k, 0.0), room)
            parts[k] = min(want, room)
        else:
            parts[k] = want
    rest = moved - sum(parts.values())
    if rest > 0:
        ow = {k: own.get(k, 0.0) for k in others if own.get(k, 0.0) > 0}
        if not ow:
            raise SystemExit('household_employers: no other household service to take the part above the caps')
        S = sum(ow.values())
        for k, x in ow.items():
            parts[k] = parts.get(k, 0.0) + rest * x / S
    return parts, info
