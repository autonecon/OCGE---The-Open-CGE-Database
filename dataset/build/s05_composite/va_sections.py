"""Donor VA by section group (beta v4 P37; config/s05/donor_guards.csv donor_va_sections). David's call; default off.

A donor-built member's table carries its donor's production pattern. With this choice on, each member table's sector
value added is moved to the member's own 2022 UN AMA value added by ISIC section group (data/unsd_ama/
gva_gdp_current_usd.csv, current USD), before the GDP scaling. GTAP 12 does not do this: ch.9D §D.3 p.3 builds the
composite table from the donors' tables by GDP weights and adjusts it only in the FIT (macroeconomic aggregates, trade,
protection and energy), and ch.9A p.2 does not apply the agricultural production targets to composite regions. Ch.8
§8.3 p.4 aims at "the composite region's income level and production pattern". This choice is a labelled departure.

The method is a demand-side Leontief move. Every sector column in a group (inputs, taxes, value added and output) is
multiplied by the group's factor, so input coefficients and VA shares within a sector stay the donor's. Each
domestic product row is then closed on its final uses (household, government, investment and exports, in proportion
to their positive values), keeping the row's carried rounding residual. Import rows are uses and follow the columns.

AMA groups (ISIC Rev.3 letters as AMA publishes them): ag A-B; mu C and E (mining and utilities: AMA C-E less D);
mfg D; con F; gh G-H; tsc I (transport, storage and communications); oth J-P. Publishing and IT services go to oth.

Values: ama_7 scales all seven groups so the member's VA shares equal AMA's and total VA is the donor's.
ama_ex_energy leaves the mining and utilities group and petroleum products at the donor's VA (S11 rebuilds energy
from volumes); the other groups share the rest of the donor's VA in AMA's proportions (mfg's free part takes its
target less pet), so total VA is still the donor's.
Factors are bounded to [1 / K_CAP, K_CAP]; a bound hit is reported.

Scope (beta v5 S1; the guard row's parameter column): blank applies the value to every donor-built member (P37 as coded
in beta v4); a ';'-separated list of member codes applies it to those members only. Beta v5 uses ama_ex_energy for TLS
only (David 2026-10-27 08:39 UTC): the Myanmar donor gives Timor-Leste crops 69% of GDP in the prior.
"""
import csv

import numpy as np

# S05 sectors: oil and gas are one column, B06, until S11 splits it.
GROUPS = {
    'ag': ('crp', 'for', 'fsh'),
    'mu': ('coa', 'B06', 'ore', 'min', 'msp', 'ely', 'wat'),
    'mfg': ('fbt', 'tal', 'wod', 'pap', 'pet', 'chm', 'pha', 'rpl', 'nmm', 'stl', 'nfm', 'fmp', 'elc', 'eeq', 'mac',
            'mvh', 'shp', 'tre', 'omf'),
    'con': ('con',),
    'gh': ('trd', 'hos'),
    'tsc': ('rdt', 'sea', 'air', 'whs', 'pst', 'tel'),
    'oth': ('pub', 'its', 'fin', 'rle', 'pro', 'adm', 'gov', 'edu', 'hea', 'art', 'ots', 'hhe'),
}
AMA_COLUMNS = {'ag': 'gva_10_ag', 'mfg': 'gva_12_mfg', 'con': 'gva_13_f', 'gh': 'gva_14_gh', 'tsc': 'gva_15_i',
               'oth': 'gva_16_jp'}          # mu = gva_11_ce - gva_12_mfg
VALUES = ('off', 'ama_7', 'ama_ex_energy')
FIXED = {'off': (), 'ama_7': (), 'ama_ex_energy': GROUPS['mu'] + ('pet',)}
K_CAP = 5.0
YEAR = 2022


def members(parameter):
    """The guard parameter -> None (every donor-built member) or the set of member codes it lists."""
    p = (parameter or '').strip()
    if not p:
        return None
    out = {x.strip() for x in p.split(';') if x.strip()}
    if not all(len(x) == 3 and x.isalpha() and x.isupper() for x in out):
        raise ValueError(f'donor_va_sections parameter {parameter!r} is not blank or a ;-separated list of ISO3 codes')
    return out


def group_of(sectors):
    """sector -> group; raises ValueError when a sector has no group or two."""
    out = {}
    for g, ss in GROUPS.items():
        for s in ss:
            out[s] = g
    missing = [s for s in sectors if s not in out]
    extra = [s for s in out if s not in sectors]
    if missing or extra:
        raise ValueError(f'va_sections groups: sectors without a group {missing}; group sectors not in S05 {extra}')
    return out


def read_ama(path, year=YEAR):
    """{iso3: {group: USD}} for the year, with mu = C-E less manufacturing. Rows with a missing or negative group
    are left out (the member keeps its donor's pattern)."""
    out = {}
    with open(path, newline='') as fh:
        for r in csv.DictReader(fh):
            if int(r['year']) != year:
                continue
            try:
                v = {g: float(r[c]) for g, c in AMA_COLUMNS.items()}
                v['mu'] = float(r['gva_11_ce']) - v['mfg']
            except (TypeError, ValueError):
                continue
            if all(x >= 0 for x in v.values()) and sum(v.values()) > 0:
                out[r['iso3']] = v
    return out


def factors(va, sectors, ama, value, k_cap=K_CAP):
    """Group factors for one member: va is the member table's sector VA (in `sectors` order), ama its AMA groups.
    Returns ({group: k}, {group: (donor share, AMA share, raw k)}, [groups bounded]). A group with no positive free
    donor VA keeps k = 1."""
    gof = group_of(sectors)
    fixed = set(FIXED[value])
    total = float(sum(va))
    # a wholly fixed group keeps its donor VA; the other groups share the rest of the donor's total VA in AMA's
    # proportions, so total VA stays the donor's under every value
    whole = [g for g, ss in GROUPS.items() if all(s in fixed for s in ss)]
    pool = total - sum(float(va[sectors.index(s)]) for g in whole for s in GROUPS[g])
    ama_total = sum(v for g, v in ama.items() if g not in whole)
    k, info, bounded = {}, {}, []
    for g, ss in GROUPS.items():
        idx = [sectors.index(s) for s in ss]
        free = float(sum(va[i] for i in idx if sectors[i] not in fixed))
        fix = float(sum(va[i] for i in idx if sectors[i] in fixed))
        share_d = (free + fix) / total if total else 0.0
        share_a = ama[g] / ama_total if g not in whole else share_d
        if free <= 0 or g in whole:
            k[g] = 1.0
            info[g] = (share_d, share_a, 1.0)
            continue
        raw = (share_a * pool - fix) / free
        kk = min(max(raw, 1.0 / k_cap), k_cap)
        if kk != raw:
            bounded.append(g)
        k[g] = kk
        info[g] = (share_d, share_a, raw)
    assert set(gof.values()) == set(GROUPS)
    return k, info, bounded


def sector_factors(k, sectors, value):
    fixed = set(FIXED[value])
    gof = group_of(sectors)
    return np.array([1.0 if s in fixed else k[gof[s]] for s in sectors])


def rescale(T, ks, n_s, n_a, final_cols, x_c, st_c, gr_c, out_c, out_r):
    """Scale sector column j by ks[j], then close each domestic product row j on its new output, keeping the row
    residual (sales - OUT). A row short of sales adds the gap to its final uses (final_cols) in proportion to their
    positive values (to exports when it has none). A row with too many sales scales its positive use and export cells
    by one factor, and the use cells taken off domestic supply move to the import row of the same product, so every
    user's column total is unchanged (domestic to imported). Returns (new table, rows short of sales with no positive
    final use, whose gap went to exports; rows whose positive cells cannot take the cut, left open: the caller keeps
    those sectors at factor 1, see member_factors)."""
    T = np.array(T, copy=True)

    def sales(M):
        return M[:n_s, :n_a].sum(axis=1) + M[:n_s, x_c] + M[:n_s, st_c] - M[:n_s, gr_c]

    resid = sales(T) - T[:n_s, out_c]
    T[:out_r + 1, :n_s] *= ks[None, :]
    T[:n_s, out_c] *= ks
    cur = sales(T)
    gap = T[:n_s, out_c] + resid - cur
    use_cols = np.arange(n_a)
    to_x, open_rows = [], []
    for j in range(n_s):
        if gap[j] > 0:
            fd = T[j, final_cols]
            pos = np.clip(fd, 0.0, None)
            if pos.sum() > 0:
                T[j, final_cols] = fd + gap[j] * pos / pos.sum()
            else:
                T[j, x_c] += gap[j]
                to_x.append(j)
        elif gap[j] < 0:
            u = T[j, use_cols]
            up = np.clip(u, 0.0, None)
            xp = max(T[j, x_c], 0.0)
            flex = up.sum() + xp
            if flex + gap[j] < 0:
                open_rows.append(j)
                continue
            f = (flex + gap[j]) / flex
            moved = (1.0 - f) * up
            T[j, use_cols] = u - moved
            T[n_s + j, use_cols] += moved
            T[j, x_c] -= (1.0 - f) * xp
    return T, to_x, open_rows


def member_factors(T, ks, n_s, n_a, final_cols, x_c, st_c, gr_c, out_c, out_r, tries=10):
    """rescale, with every sector whose product row cannot take its cut held at factor 1 (repeated until none is
    left). Returns (table, sector factors used, rows to exports, sectors held at 1)."""
    ks = np.array(ks, dtype=float)
    held = []
    for _ in range(tries):
        out, to_x, open_rows = rescale(T, ks, n_s, n_a, final_cols, x_c, st_c, gr_c, out_c, out_r)
        if not open_rows:
            return out, ks, to_x, held
        ks[open_rows] = 1.0
        held += open_rows
    raise ValueError(f'va_sections: rows {open_rows} still cannot be closed after {tries} passes')
