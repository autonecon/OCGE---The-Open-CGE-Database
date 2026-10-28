"""S04 I-O disaggregation (9B) and the government consumption check (9C).

Order (GTAP 12 ch.9C §C.2 p.1: "The procedure is applied after initial cleaning
(chapter 8), but before any sectoral disaggregation (chapter 9B)"):

Step A. For each of the 80 ICIO economy tables, compare government consumption
over GDP with the S02 country ratio. Reject when the two ratios differ by a
factor of more than 2 (ch.9C §C.2 p.1), on both sides (p.2 and Table 9.6).

Step B. No sector is split. Every table already has the 50 ICIO labels. B06
stays one sector until S11. The representative table is not copied onto any cell.

A rejected table is revised only when config/s04/gov_revision.csv says so.
revise follows GTAP 8 ch.8.E p.3: G/GDP matches the macro ratio, and the product
composition of G matches the representative table. The sales gap is left for S13.
"""
import gzip
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/lib')
from stagekit import BUILD, STAGES, Stage

S = Stage('S04', 'disagg_gov')
I = S.inp
S01 = S.upstream(STAGES + '/S01_sets_registry')
S02 = S.upstream(STAGES + '/S02_macro')
S03 = S.upstream(STAGES + '/S03_io_cleaning')

sectors = pd.read_csv(I(S01 + '/output/sectors.csv', 'S01 sectors'))
conc = pd.read_csv(I(S01 + '/output/concord_icio_to_sector.csv', 'S01 ICIO concordance'))
macro = pd.read_csv(I(S02 + '/output/macro_country.csv', 'S02 country macro')).set_index('code')
io_path = I(S03 + '/output/io_cleaned.csv.gz', 'S03 cleaned I-O table')
use_path = I(S03 + '/output/use_domestic_imported.csv', 'S03 domestic and imported use')
cmp = pd.read_csv(I(S03 + '/output/macro_comparison.csv', 'S03 macro comparison')).set_index('economy')
weights = pd.read_csv(I(S03 + '/output/representative_weights.csv', 'S03 representative weights'))
gap_path = I(S03 + '/output/stock_change_gap.csv', 'S03 stock-change gap, for the rounded balance')
cfg_path = I(BUILD + '/config/s04/gov_revision.csv', 'S04 government-revision decisions')

CIT_9C = ('GTAP 12 ch.9C §C.2 p.1 ("the ratio of government consumption to GDP is calculated for each table, '
          'and compared to external macroeconomic data"; "differ by a factor of more than 2")')
CIT_9C2 = ('GTAP 12 ch.9C §C.2 p.2 ("not only sizable apparent underestimates of government consumption, '
           'but also some sizable apparent overestimates"); Table 9.6 rejects Luxembourg at 0.42 against 0.16')
CIT_8E = ('GTAP 8 ch.8.E p.3 ("adjust the contributed table, so that the ratio of government consumption to GDP '
          'matches the macroeconomic time-series data set, and the sectoral composition of government consumption '
          'as in the representative table")')
CIT_9B = ('GTAP 12 ch.9B §B.1 p.1 ("Where the contributed table uses an aggregated classification, we must '
          'disaggregate it to the standard GTAP sectors in-house")')
CIT_ORD = ('GTAP 12 ch.8 §8.3 p.3 ("Fourth, having cleaned the I-O tables as required, we take those that have '
           'the full 65-sector GTAP sectoral classification and calculate from them a representative table")')
TOL_ABS = 0.05
TOL_REL = 1e-9
GOVSVC = ('gov', 'edu', 'hea')

# ---------------------------------------------------------------- read the wide table
S.log(f'reading {io_path}')
with gzip.open(io_path, 'rt') as fh:
    header = fh.readline().rstrip('\n').split(',')
    row_labels = []
    data = []
    for line in fh:
        parts = line.rstrip('\n').split(',')
        row_labels.append(parts[0])
        data.append([0.0 if x == '0' or x == '' else float(x) for x in parts[1:]])
M = np.asarray(data, dtype=np.float64)
col_labels = header[1:]
assert col_labels[-1] == 'OUT' and row_labels[-3:] == ['TLS', 'VA', 'OUT']
del data

economies = []
for lab in col_labels[:-1]:
    eco, _agent = lab.split('_', 1)
    if eco not in economies:
        economies.append(eco)
sec = []
for lab in row_labels:
    if lab in ('TLS', 'VA', 'OUT'):
        break
    eco, name = lab.split('_', 1)
    if eco != economies[0]:
        break
    sec.append(name)
n_e, n_s = len(economies), len(sec)
agents = sec + ['p', 'g', 'i', 'dpabr']
n_a = len(agents)
assert n_a == 54 and M.shape == (n_e * n_s + 3, n_e * n_a + 1), M.shape
g_ai = agents.index('g')
tls_r, va_r, out_r = n_e * n_s, n_e * n_s + 1, n_e * n_s + 2
S.log(f'{n_e} blocks, {n_s} sector labels, matrix {M.shape[0]} x {M.shape[1]}')

P = M[:n_e * n_s, :n_e * n_a].reshape(n_e, n_s, n_e, n_a)
TLS = M[tls_r, :n_e * n_a].reshape(n_e, n_a)
VA = M[va_r, :n_e * n_a].reshape(n_e, n_a)
OUTC = M[:n_e * n_s, -1].reshape(n_e, n_s)
OUTR = M[out_r, :n_e * n_a].reshape(n_e, n_a)

eco_only = [e for e in economies if e != 'ROW']
assert len(eco_only) == 80 and 'ISL' in eco_only and 'ROW' in economies


def col_of(ei, ai):
    return ei * n_a + ai


def row_of(ei, si):
    return ei * n_s + si


def within(diff, ref):
    """abs ≤ 0.05 USD million or rel ≤ 1e-9, the tolerance for the 4-decimal S03 file."""
    d = abs(diff)
    return d <= TOL_ABS or d <= TOL_REL * max(abs(ref), 1e-30)


def fmt4(v):
    if v == 0:
        return '0'
    return f'{v:.4f}'


def fmt10(v):
    if v == 0:
        return '0'
    return f'{v:.10f}'


# ---------------------------------------------------------------- H1 balance on the file as read
stock = pd.read_csv(gap_path)
prod_gap = (stock.loc[stock.kind == 'product']
            .groupby(['origin', 'sector'], sort=False)['value_musd'].sum())
tls_gap = (stock.loc[stock.kind == 'tls_on_invnt']
           .groupby('origin', sort=False)['value_musd'].sum())

max_abs = 0.0
n_h1_fail = 0
n_h1 = 0
usa_h1 = []
worst = None
for ei, e in enumerate(economies):
    for si, name in enumerate(sec):
        n_h1 += 1
        sales = float(P[ei, si].sum())
        key = (e, name)
        sales += float(prod_gap.loc[key]) if key in prod_gap.index else 0.0
        costs = float(P[:, :, ei, si].sum() + TLS[ei, si] + VA[ei, si])
        outv = float(OUTC[ei, si])
        out_row = float(OUTR[ei, si])
        d_sc, d_so, d_co = sales - costs, sales - outv, costs - outv
        d_oo = outv - out_row
        mx = max(abs(d_sc), abs(d_so), abs(d_co), abs(d_oo))
        if mx > max_abs:
            max_abs = mx
            worst = (e, name, mx, sales, costs, outv)
        ok = (within(d_sc, outv) and within(d_so, outv) and within(d_co, outv) and within(d_oo, outv))
        if not ok:
            n_h1_fail += 1
        if e == 'USA':
            usa_h1.append((mx, name, sales, costs, outv, d_sc, d_so, d_co))
usa_h1.sort(reverse=True)
usa_max = usa_h1[0][0]
S.check('S04-H1',
        'S03 table as read: for every block x sector, sales plus the stock-change gap equal costs equal published OUT. '
        'Tolerance abs <= 0.05 USD million or rel <= 1e-9, because io_cleaned.csv.gz is written to 4 decimals',
        'hard',
        f'max residual {max_abs:.4f} USD m ({worst[0]}_{worst[1]}); USA max {usa_max:.4f} ({usa_h1[0][1]}); '
        f'sectors {n_h1}; outside tolerance {n_h1_fail}',
        'abs <= 0.05 or rel <= 1e-9 on sales-costs, sales-OUT, costs-OUT and OUT row-OUT column',
        n_h1_fail == 0,
        'S03 balance on the 4-decimal file; GTAP 12 ch.8 §8.2 p.2 (total sales equal total costs)',
        'Sales are the cleaned product row plus the S03 product stock-change gap. '
        'Costs are intermediate cells plus TLS plus VA. Published OUT is the OUT column, and the OUT row of that '
        'industry column is the same target. INVNT was removed from the rows at S03 and OUT was left at published '
        'output, so the gap is added back before this identity is the rounding residual. '
        'USA top 5: ' + '; '.join(
            f'{name} residual {mx:.4f} (sales-costs {dsc:+.4f}, sales-OUT {dso:+.4f}, costs-OUT {dco:+.4f})'
            for mx, name, _sales, _costs, _outv, dsc, dso, dco in usa_h1[:5]))

# ---------------------------------------------------------------- 9C ratios
members = set(weights.loc[weights.in_representative_table == 'yes', 'economy'])
assert len(members) == 41

cfg = pd.read_csv(cfg_path, dtype=str).fillna('')
cfg['economy'] = cfg['economy'].str.strip()
cfg['action'] = cfg['action'].str.strip()
cfg['decided_by'] = cfg['decided_by'].str.strip()
action_of = dict(zip(cfg['economy'], cfg['action']))

rows_9c = []
for ei, e in enumerate(eco_only):
    g_basic = float(P[:, :, ei, g_ai].sum())
    g_tls = float(TLS[ei, g_ai])
    g_table = g_basic + g_tls
    gdp = float(cmp.loc[e, 'icio_gdp'])
    s02_g = float(macro.loc[e, 'G_musd'])
    s02_y = float(macro.loc[e, 'GDP_musd'])
    gsrc = str(macro.loc[e, 'G_source'])
    r_table = g_table / gdp
    r_macro = s02_g / s02_y
    factor = r_table / r_macro
    fold = max(factor, 1.0 / factor) if factor > 0 else np.inf
    gsvc = float(P[:, [sec.index(s) for s in GOVSVC], ei, g_ai].sum())
    gsvc_share = gsvc / g_basic if g_basic != 0 else np.nan
    result = 'reject' if fold > 2 else 'accept'
    action = action_of.get(e, 'accept' if result == 'accept' else '')
    rows_9c.append(dict(
        economy=e, rep_member='yes' if e in members else 'no',
        g_basic=g_basic, g_tls=g_tls, G_table=g_table, icio_gdp=gdp,
        s02_G=s02_g, s02_GDP=s02_y, G_source=gsrc,
        r_table=r_table, r_macro=r_macro, factor=factor, fold=fold,
        result=result, govsvc_share=gsvc_share, action=action,
        ei=ei))

# Published GDP reconstructed from the file (VA + TLS on the file + TLS removed with INVNT).
gdp_gap = []
for rec in rows_9c:
    ei, e = rec['ei'], rec['economy']
    tls_inv = float(tls_gap.loc[e]) if e in tls_gap.index else 0.0
    recon = float(VA[ei, :n_s].sum() + TLS[ei].sum() + tls_inv)
    gdp_gap.append(abs(recon - rec['icio_gdp']))
gdp_gap_max = max(gdp_gap)

bad_num = [r['economy'] for r in rows_9c
           if not np.isfinite(r['r_table']) or not np.isfinite(r['r_macro'])
           or r['icio_gdp'] == 0 or r['s02_GDP'] == 0 or r['G_table'] == 0 or r['s02_G'] == 0]
S.check('S04-H2',
        '9C coverage: r_table and r_macro for all 80 economy tables (ISL included, ROW excluded). '
        'No NaN, no zero denominator. r_table is basic g plus TLS on g, over S03 ICIO GDP. '
        'r_macro is S02 country G over GDP. Both are purchasers\' prices',
        'hard',
        f'rows {len(rows_9c)}; non-finite or zero denominator {len(bad_num)}; '
        f'max |file VA+TLS+INVNT-TLS - icio_gdp| {gdp_gap_max:.4e}',
        '80 rows; 0 bad; reconstructed GDP within 0.05 USD million',
        len(rows_9c) == 80 and not bad_num and gdp_gap_max <= TOL_ABS and 'ISL' in {r['economy'] for r in rows_9c},
        CIT_9C + '; ' + CIT_9C2,
        'ICIO GDP is the S03 macro_comparison icio_gdp (VA + TLS as published). '
        'The file no longer contains TLS on INVNT, so the reconstruction adds that gap back. '
        'ROW is not in the 80. ' + (' '.join(bad_num)))

rejected = sorted(r['economy'] for r in rows_9c if r['result'] == 'reject')
cfg_set = list(cfg['economy'])
# David did not pick the AGO row. Timmy applied the GTAP 8 procedure under David's standing rule.
DECIDED_BY = "Timmy, applying GTAP 8 ch.8.E p.3 under David's standing GTAP-method rule (2026-10-20/21)"
cfg_bad_who = [r.economy for r in cfg.itertuples() if r.decided_by != DECIDED_BY]
cfg_bad_act = [r.economy for r in cfg.itertuples() if r.action not in ('revise', 'report_only')]
dup = sorted({e for e in cfg_set if cfg_set.count(e) > 1})
unknown = sorted(set(cfg_set) - set(eco_only))
S.check('S04-H3',
        '9C decisions: the reject set (fold > 2, two-sided) equals config/s04/gov_revision.csv, '
        'and each row records Timmy applying GTAP 8 ch.8.E p.3 under David\'s standing rule, '
        'with action revise or report_only. David did not pick the row',
        'hard',
        f'reject {rejected}; config {cfg_set}; decided_by mismatch {len(cfg_bad_who)}; '
        f'bad action {len(cfg_bad_act)}; duplicate {len(dup)}; unknown {len(unknown)}',
        'sets equal; decided_by is the Timmy attribution; action revise or report_only',
        rejected == sorted(set(cfg_set)) and not cfg_bad_who and not cfg_bad_act and not dup and not unknown
        and len(cfg_set) == len(set(cfg_set)),
        CIT_9C,
        'A fold of exactly 2 is accepted ("more than 2"). '
        + ' '.join(f'{r.economy} {r.action} {r.decided_by} {r.decided_at}' for r in cfg.itertuples()))

rej_members = sorted(members & set(rejected))
S.check('S04-H4',
        'No representative-table member is rejected. The representative table was built at S03, '
        'before this 9C step; that order is harmless only while H4 passes',
        'hard', f'members {len(members)}; rejected members {rej_members or "none"}',
        '0 rejected members',
        not rej_members and len(members) == 41,
        CIT_ORD,
        'If a member were rejected, this stage would stop. S03 would be rebuilt after the revision, not inside this run.')

# ---------------------------------------------------------------- representative G composition (plain sum of the 41)
mem_ix = [economies.index(e) for e in weights.loc[weights.in_representative_table == 'yes', 'economy']]
assert len(mem_ix) == 41
rep_dom = np.zeros(n_s)
rep_imp = np.zeros(n_s)
rep_tls = 0.0
for ix in mem_ix:
    col = P[:, :, ix, g_ai]
    rep_dom += col[ix]
    rep_imp += col.sum(axis=0) - col[ix]
    rep_tls += float(TLS[ix, g_ai])
rep_basic = rep_dom + rep_imp
rep_purch = float(rep_basic.sum() + rep_tls)
rep_share = rep_basic / rep_purch
rep_tls_share = rep_tls / rep_purch
assert abs(rep_share.sum() + rep_tls_share - 1) <= 1e-12
assert np.all(rep_basic >= 0) and rep_tls >= 0

# ---------------------------------------------------------------- H5 classification, no split
expect = []
for name in sectors['sector']:
    if name == 'oil':
        expect.append('B06')
    elif name == 'gas':
        continue
    else:
        expect.append(name)
assert len(expect) == 50 and expect.count('B06') == 1
b06 = conc.loc[conc.icio_code == 'B06']
other = conc.loc[conc.icio_code != 'B06', 'share'].astype(float)
b06_ok = set(b06['share_status']) == {'deferred:S11'} and len(b06) == 2
shares_ok = len(other) == 49 and bool((other == 1).all())
class_rows = []
class_bad = []
for e in economies:
    # Every block uses the same row labels. Check the block's own labels anyway.
    ei = economies.index(e)
    found = [row_labels[row_of(ei, si)].split('_', 1)[1] for si in range(n_s)]
    missing = [s for s in expect if s not in found]
    extra = [s for s in found if s not in expect]
    # oil and gas must not appear; B06 appears once.
    if found.count('B06') != 1 or 'oil' in found or 'gas' in found or found != expect:
        class_bad.append(e)
    class_rows.append((e, len(found), ' '.join(missing), ' '.join(extra), 0))
splits_done = 0
S.check('S04-H5',
        '9B classification: every economy table has the 50 labels of S01 sectors.csv with oil+gas as B06. '
        'Concordance shares are 1 except B06 (deferred:S11). Splits performed = 0. '
        'The representative table is not applied to any cell',
        'hard',
        f'bad blocks {len(class_bad)}; B06 deferred {b06_ok}; other shares all 1 {shares_ok}; splits {splits_done}',
        '0 bad blocks; B06 deferred:S11; 49 shares equal to 1; 0 splits',
        not class_bad and b06_ok and shares_ok and splits_done == 0 and 'oil' not in sec and 'gas' not in sec,
        CIT_9B + '; ch.9D §D.1 p.2 (structure adapted from the representative table only for sectors that are not disaggregated)',
        'Agriculture is one sector (crp), so ch.9B §B.2 does not apply. B06 is not split here. '
        'Expected labels: ' + ' '.join(expect))

# ---------------------------------------------------------------- revision
revise = [r['economy'] for r in rows_9c if action_of.get(r['economy']) == 'revise']
report_only = [r['economy'] for r in rows_9c if action_of.get(r['economy']) == 'report_only']
by_eco = {r['economy']: r for r in rows_9c}

# Cross-check AGO-style import shares against use_domestic_imported (4-decimal file).
use = pd.read_csv(use_path)
use_tot = (use.groupby(['destination', 'product'], sort=False)[['domestic_musd', 'imported_musd', 'total_musd']]
           .sum())


def import_pattern(ei):
    """All-users use of each product: total, domestic, and origin vector (imports keep their origins)."""
    total = P[:, :, ei, :].sum(axis=(0, 2))          # (sector,) summed over origins and agents? 
    # P is (origin, sector, dest, agent). Users of dest ei: sum over agents, keep origin.
    by_origin = P[:, :, ei, :].sum(axis=2)           # (origin, sector)
    total = by_origin.sum(axis=0)
    domestic = by_origin[ei].copy()
    return by_origin, total, domestic


M_new = M.copy()
planned = []          # (row, col, new_value) before the dust filter
gap_records = []      # filled after the written values are final
revision_notes = []

for e in revise:
    rec = by_eco[e]
    ei = rec['ei']
    new_g = rec['r_macro'] * rec['icio_gdp']
    by_origin, use_total, _dom_use = import_pattern(ei)
    # Targets at full precision, then round every cell but the domestic gov residual to 10 decimals.
    targets = np.zeros((n_e, n_s))
    for si, name in enumerate(sec):
        basic_target = rep_share[si] * new_g
        if basic_target == 0 or use_total[si] == 0:
            # hhe is zero in the representative sum and zero in use. No fill.
            if basic_target != 0 and use_total[si] == 0:
                raise SystemExit(f'FILL would be required: {e} {name} has representative G and no use')
            continue
        imp_use = use_total[si] - by_origin[ei, si]
        imp_share = imp_use / use_total[si]
        new_imp = basic_target * imp_share
        targets[ei, si] = basic_target - new_imp
        if imp_use > 0:
            for oi in range(n_e):
                if oi == ei or by_origin[oi, si] == 0:
                    continue
                targets[oi, si] = new_imp * by_origin[oi, si] / imp_use
    tls_target = rep_tls_share * new_g
    # Round to the written precision. Hold domestic gov back so the column sums to new_g.
    gov_si = sec.index('gov')
    written = np.zeros((n_e, n_s))
    for oi in range(n_e):
        for si in range(n_s):
            if oi == ei and si == gov_si:
                continue
            written[oi, si] = 0.0 if targets[oi, si] == 0 else float(fmt10(targets[oi, si]))
    tls_written = float(fmt10(tls_target))
    residual = new_g - float(written.sum()) - tls_written
    written[ei, gov_si] = float(fmt10(residual))
    # Drop changes that do not survive the H6 threshold, then close the sum again if needed.
    old_col = P[:, :, ei, g_ai]
    old_tls = float(TLS[ei, g_ai])
    for oi in range(n_e):
        for si in range(n_s):
            if abs(written[oi, si] - old_col[oi, si]) <= TOL_REL:
                written[oi, si] = old_col[oi, si]
    if abs(tls_written - old_tls) <= TOL_REL:
        tls_written = old_tls
    drift = new_g - float(written.sum()) - tls_written
    written[ei, gov_si] = float(fmt10(written[ei, gov_si] + drift))
    # Write into the matrix.
    gcol = col_of(ei, g_ai)
    for oi in range(n_e):
        for si in range(n_s):
            M_new[row_of(oi, si), gcol] = written[oi, si]
    M_new[tls_r, gcol] = tls_written
    got = float(written.sum() + tls_written)
    revision_notes.append((e, rec['G_table'], new_g, got, rec['r_table'], rec['r_macro'], got / rec['icio_gdp']))
    S.log(f'revise {e}: G {rec["G_table"]:.6f} -> {got:.6f} (target {new_g:.6f}); '
          f'r {rec["r_table"]:.8f} -> {got / rec["icio_gdp"]:.8f} vs macro {rec["r_macro"]:.8f}')

# Ledger, in file order, only for cells that differ by more than 1e-9.
region_of = {code: reg for code, reg in zip(macro.index, macro['region'].astype(str))}


def region(economy):
    return region_of.get(economy, economy)


n_changed = 0
changed_pos = []
for ei, e in enumerate(economies):
    gcol = col_of(ei, g_ai)
    if e not in revise:
        continue
    for oi, origin in enumerate(economies):
        for si, name in enumerate(sec):
            r = row_of(oi, si)
            old, new = float(M[r, gcol]), float(M_new[r, gcol])
            if abs(new - old) <= TOL_REL:
                M_new[r, gcol] = old
                continue
            n_changed += 1
            changed_pos.append((r, gcol))
            S.adjust(region(origin), f'{origin}_{name} sale to {e}_g',
                     fmt4(old), fmt10(new), 'GTAP8-8E-p3', CIT_8E, 'G-REVISE-9C')
    old, new = float(M[tls_r, gcol]), float(M_new[tls_r, gcol])
    if abs(new - old) > TOL_REL:
        n_changed += 1
        changed_pos.append((tls_r, gcol))
        S.adjust(region(e), f'{e} TLS on g', fmt4(old), fmt10(new),
                 'GTAP8-8E-p3', CIT_8E, 'G-REVISE-9C')

# Independent cell count, separate from the ledger append loop.
n_independent = int(np.sum(np.abs(M_new - M) > TOL_REL))

# ---------------------------------------------------------------- write io_s04, then read it back
S.log('writing io_s04.csv.gz')
changed_set = set(changed_pos)
gz_path = S.out + '/io_s04.csv.gz'
with open(gz_path, 'wb') as raw:
    with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0, compresslevel=9) as gz:
        gz.write(('row,' + ','.join(col_labels) + '\n').encode())
        for i, lab in enumerate(row_labels):
            vals = []
            for j in range(M_new.shape[1]):
                if (i, j) in changed_set:
                    vals.append(fmt10(M_new[i, j]))
                else:
                    vals.append(fmt4(M[i, j]))
            gz.write((lab + ',' + ','.join(vals) + '\n').encode())
S.log(f'output io_s04.csv.gz bytes {os.path.getsize(gz_path)}')

S.log('reading io_s04.csv.gz back')
with gzip.open(gz_path, 'rt') as fh:
    back_header = fh.readline().rstrip('\n').split(',')
    back = []
    for line in fh:
        parts = line.rstrip('\n').split(',')
        back.append([0.0 if x == '0' or x == '' else float(x) for x in parts[1:]])
B = np.asarray(back, dtype=np.float64)
assert back_header[1:] == col_labels and B.shape == M.shape
del back

diff = np.abs(B - M)
n_diff = int(np.sum(diff > TOL_REL))
max_unchanged = float(diff[diff <= TOL_REL].max()) if np.any(diff <= TOL_REL) else 0.0
# USA table: USA columns. USA rows can change where they sell to a revised g column.
usa_i = economies.index('USA')
usa_cols = slice(col_of(usa_i, 0), col_of(usa_i, n_a))
usa_col_changed = int(np.sum(diff[:, usa_cols] > TOL_REL))
S.check('S04-H6',
        'io_s04 equals io_cleaned cell for cell after reading (abs <= 1e-9), except cells with a ledger row. '
        'Ledger rows equal the changed-cell count',
        'hard',
        f'changed cells {n_diff}; ledger {len(S.ledger)}; counted in the loop {n_changed}; '
        f'independent mask {n_independent}; USA columns changed {usa_col_changed}',
        'changed = ledger = independent count; USA columns 0' if usa_col_changed == 0 else 'counts equal',
        n_diff == len(S.ledger) == n_changed == n_independent
        and (n_diff == 0) == (not revise),
        'same test as S02-H2 and S03-H9',
        f'Max |difference| on cells within the threshold {max_unchanged:.3e}. '
        'Under report_only both counts are 0. A USA column is the USA table; a USA row that sells to a revised '
        f'g column is that other table. USA columns changed {usa_col_changed}.')

# ---------------------------------------------------------------- H7
h7_ok = True
h7_bits = []
if not revise:
    h7_detail = 'not applicable'
    h7_value = 'not applicable'
else:
    Bp = B[:n_e * n_s, :n_e * n_a].reshape(n_e, n_s, n_e, n_a)
    Btls = B[tls_r, :n_e * n_a].reshape(n_e, n_a)
    Bva = B[va_r, :n_e * n_a].reshape(n_e, n_a)
    for e in revise:
        rec = by_eco[e]
        ei = rec['ei']
        g_basic = float(Bp[:, :, ei, g_ai].sum())
        g_tls = float(Btls[ei, g_ai])
        g_table = g_basic + g_tls
        r_post = g_table / rec['icio_gdp']
        # Own GDP adds the TLS-on-g change. Reported only. H7 still uses the S03 ICIO GDP.
        gdp_own = rec['icio_gdp'] + (g_tls - rec['g_tls'])
        r_own = g_table / gdp_own
        rel = abs(r_post - rec['r_macro']) / abs(rec['r_macro'])
        shares = Bp[:, :, ei, g_ai].sum(axis=0) / g_table
        share_err = float(np.max(np.abs(shares - rep_share)))
        tls_err = abs(g_tls / g_table - rep_tls_share)
        va_same = bool(np.array_equal(Bva, VA))
        out_same = bool(np.array_equal(B[out_r], M[out_r]) and np.array_equal(B[:, -1], M[:, -1]))
        tls_mask = np.ones(n_a, dtype=bool)
        tls_mask[g_ai] = False
        tls_outside = bool(np.array_equal(Btls[:, tls_mask], TLS[:, tls_mask]))
        # other economies' g columns, and this economy's non-g TLS, already covered;
        # every column except this g column is unchanged.
        gcol = col_of(ei, g_ai)
        other_cols = [j for j in range(B.shape[1]) if j != gcol]
        cols_same = bool(np.array_equal(B[:, other_cols], M[:, other_cols]))
        # gap equals the change in the row's sales. Only this column moves, so the
        # row-sum change is the cell change.
        max_gap_err = 0.0
        for oi, origin in enumerate(economies):
            for si, name in enumerate(sec):
                cell = float(B[row_of(oi, si), gcol] - M[row_of(oi, si), gcol])
                if abs(cell) <= TOL_REL and abs(cell) == 0:
                    continue
                if abs(cell) <= TOL_REL:
                    continue
                row_delta = float(B[row_of(oi, si), :-1].sum() - M[row_of(oi, si), :-1].sum())
                max_gap_err = max(max_gap_err, abs(row_delta - cell))
                gap_records.append((origin, name, 'product',
                                    float(M[row_of(oi, si), :-1].sum()),
                                    float(B[row_of(oi, si), :-1].sum()),
                                    row_delta))
        tls_cell = float(B[tls_r, gcol] - M[tls_r, gcol])
        if abs(tls_cell) > TOL_REL:
            gap_records.append((e, 'TLS', 'tls', float(M[tls_r, gcol]), float(B[tls_r, gcol]), tls_cell))
        # import share versus the economy's own all-users share, on products above 1 USD million
        by_origin, use_total, _dom = import_pattern(ei)
        imp_err = 0.0
        n_imp = 0
        for si in range(n_s):
            basic = float(Bp[:, si, ei, g_ai].sum())
            if basic <= 1.0 or use_total[si] == 0:
                continue
            want = (use_total[si] - by_origin[ei, si]) / use_total[si]
            got_imp = basic - float(Bp[ei, si, ei, g_ai])
            imp_err = max(imp_err, abs(got_imp / basic - want))
            n_imp += 1
        ok = (rel <= TOL_REL and share_err <= TOL_REL and tls_err <= TOL_REL
              and va_same and out_same and tls_outside and cols_same
              and max_gap_err <= TOL_REL and imp_err <= 1e-6)
        h7_ok = h7_ok and ok
        h7_bits.append(
            f'{e} rel_r {rel:.3e} share {share_err:.3e} tls_share {tls_err:.3e} '
            f'va {va_same} out {out_same} tls_outside {tls_outside} other_cols {cols_same} '
            f'gap_err {max_gap_err:.3e} import_share_err {imp_err:.3e} on {n_imp} products; '
            f'r_on_revised_table_gdp {r_own:.5f}')
        # use_domestic_imported cross-check (report in the detail, not a second rule)
        u_err = 0.0
        for si, name in enumerate(sec):
            if (e, name) not in use_tot.index:
                continue
            u = use_tot.loc[(e, name)]
            file_total = float(use_total[si])
            u_err = max(u_err, abs(float(u.total_musd) - file_total))
        h7_bits.append(f'{e} max |use_domestic_imported total - io_cleaned total| {u_err:.4f}')
    h7_value = '; '.join(h7_bits)
    h7_detail = h7_value

S.check('S04-H7',
        'Under revise: post-revision r_table equals r_macro (rel 1e-9) on the S03 ICIO GDP; '
        'basic product shares and the TLS share equal rep_g_composition (abs 1e-9); '
        'VA, OUT and TLS outside g are unchanged; the G-revision gap equals the change in that row\'s sales; '
        'every column other than the revised g column is unchanged. Under report_only: not applicable',
        'hard', 'not applicable' if not revise else h7_value,
        'not applicable' if not revise else 'rel 1e-9; abs 1e-9; other columns identical; gap exact',
        (not revise) or h7_ok,
        CIT_8E,
        'not applicable' if not revise else
        'The denominator is the S03 ICIO GDP, the same figure used to set new G = r_macro x ICIO GDP. '
        'TLS on g changes, so a GDP recomputed from the revised TLS is a different number; it is not the denominator. '
        'The ratio on that revised-table GDP is the r_on_revised_table_gdp figure (0.17348 for Angola). '
        'Domestic and imported dollars in rep_g_composition are the representative table. '
        'The revised table uses the economy\'s own all-users import share, then the same origin pattern. '
        + h7_detail)

# ---------------------------------------------------------------- H8 negatives
va_allowed = {('CYP', 'air'), ('ISL', 'pha')}
nan_n = int(np.isnan(B).sum())
neg_prod = []
neg_va = []
neg_tls = []
neg_out = []
agents_all = agents
for ei, e in enumerate(economies):
    for ai, ag in enumerate(agents_all):
        v = float(B[va_r, col_of(ei, ai)])
        if v < 0:
            neg_va.append((e, ag, v))
        v = float(B[tls_r, col_of(ei, ai)])
        if v < 0:
            neg_tls.append((e, ag, v))
for ei, e in enumerate(economies):
    for si, name in enumerate(sec):
        if float(B[row_of(ei, si), -1]) < 0:
            neg_out.append(f'{e}_{name}')
# product cells, including the revised g column
prod_neg_n = int(np.sum(B[:n_e * n_s, :n_e * n_a] < 0))
va_bad = [(e, ag, v) for e, ag, v in neg_va if (e, ag) not in va_allowed]
va_missing = sorted(va_allowed - {(e, ag) for e, ag, _v in neg_va})
tls_list = ', '.join(f'{e}_{ag}={v:.4f}' for e, ag, v in neg_tls)
va_list = ', '.join(f'{e}_{ag}={v:.4f}' for e, ag, v in neg_va)
S.check('S04-H8',
        'No NaN. Negatives only where S03-H8 allowed them: TLS subsidies, and VA in CYP_H51 (air) and ISL_C21 (pha). '
        'Count them and list them',
        'hard',
        f'NaN {nan_n}; product negatives {prod_neg_n}; OUT negatives {len(neg_out)}; '
        f'TLS negatives {len(neg_tls)}; VA negatives {len(neg_va)} [{va_list}]',
        'NaN 0; product 0; OUT 0; VA only CYP_air and ISL_pha; TLS subsidies only',
        nan_n == 0 and prod_neg_n == 0 and not neg_out and not va_bad and not va_missing,
        'S03-H8; GTAP 12 ch.8 §8.3 p.3 (deviations in sign)',
        f'VA: {va_list}. TLS subsidy cells ({len(neg_tls)}): {tls_list}')

# ---------------------------------------------------------------- flags
for e, old_g, target, got, r0, rm, r1 in revision_notes:
    S.flag('G-REVISE-9C', e,
           f'{e} government consumption revised. Purchasers\' G {old_g:.4f} -> {got:.4f} '
           f'(target r_macro x ICIO GDP {target:.4f}). r_table {r0:.6f} -> {r1:.6f}, r_macro {rm:.6f}. '
           f'Product composition and the TLS share are the representative table. '
           f'The domestic/imported split is {e}\'s own import share across all users. '
           f'{n_changed} cells changed. Nothing else in the table is changed.',
           'no', 'GTAP8-8E-p3', CIT_8E)
    S.flag('G-REVISION-GAP', e,
           'The change in each product row\'s sales is recorded in gov_revision_gap.csv and is not absorbed. '
           'GTAP 8 ch.8.E p.3 does not say how the rest of the table absorbs the change. '
           'Clearing the gap at the S13 fit is our choice where the text is silent (E40).',
           'no', 'E40', CIT_8E)
for e in report_only:
    S.flag('G-REJECT-9C', e,
           f'{e} fails the factor-of-2 test and the config says report_only. No cell is changed. '
           'The level is reached only when S13 scales G to S02. The ICIO composition stays. '
           'That skips the composition step in GTAP 8 ch.8.E p.3.',
           'no', 'report_only', CIT_9C)
S.flag('NO-SECTOR-SPLIT', 'all ICIO tables',
       'Splits performed = 0. Every table already has the 50 ICIO labels, and B06 stays one row and one column. '
       'ch.9B §B.3 is not applied. ch.9B §B.2 is not applied because agriculture is the one sector crp.',
       'no', 'S04-H5', CIT_9B)
S.flag('B06-DEFER-S11', 'B06',
       'B06 is not split into oil and gas. The representative table therefore has one cost structure for B06. '
       'Rule F4 cannot give oil and gas different structures until S11 resolves that. Logged, not done here.',
       'no', 'S04-H5', 'PLAN (b1) item 7; concord share_status deferred:S11')

# ---------------------------------------------------------------- report checks
rows_9c_sorted = sorted(rows_9c, key=lambda r: (-r['fold'], r['economy']))
near = [r for r in rows_9c_sorted if 1.5 <= r['fold'] <= 2.0]
low_gs = sorted(rows_9c, key=lambda r: r['govsvc_share'])[:10]
usa = by_eco['USA']
S.check('S04-R1', 'Full 9C table, 80 economies, sorted by fold. Accept or reject. No further action here.',
        'report',
        f'reject {rejected or "none"}; nearest accept {rows_9c_sorted[len(rejected)]["economy"]} '
        f'fold {rows_9c_sorted[len(rejected)]["fold"]:.4f}' if rejected else f'none rejected; top fold {rows_9c_sorted[0]["fold"]:.4f}',
        'report',
        not rejected, CIT_9C,
        'Sorted by fold: ' + '; '.join(
            f'{r["economy"]} fold {r["fold"]:.4f} {r["result"]} r_table {r["r_table"]:.4f} r_macro {r["r_macro"]:.4f}'
            for r in rows_9c_sorted[:12]))
S.check('S04-R2',
        'Government-services share in G (gov+edu+hea over basic G), Table 9.6 last column. '
        'GTAP 12 ch.9C sets no threshold, so the share is not acted on',
        'report',
        '10 lowest: ' + '; '.join(f'{r["economy"]} {r["govsvc_share"]:.4f}' for r in low_gs),
        'report only; no threshold',
        False, 'GTAP 12 ch.9C p.2 ("(GTAP commodity osg, edu and hht)")',
        'Share is basic prices, gov+edu+hea over the g column, TLS excluded from both.')
S.check('S04-R3', 'Economies with fold from 1.5 to 2.0. Accepted, listed, not revised.',
        'report',
        'none' if not near else '; '.join(
            f'{r["economy"]} {r["fold"]:.4f} rep_member {r["rep_member"]}' for r in near),
        'report',
        not near, CIT_9C,
        'The reject threshold is a factor of more than 2. This band is below it.')

# USA composition against the representative G composition.
usa_basic = P[:, :, usa_i, g_ai].sum(axis=0)
usa_g = float(usa_basic.sum() + TLS[usa_i, g_ai])
usa_shares = usa_basic / usa_g
usa_gaps = sorted(
    [(abs(float(usa_shares[si] - rep_share[si])), sec[si], float(usa_shares[si]), float(rep_share[si]),
      float(usa_basic[si])) for si in range(n_s)],
    reverse=True)
# Sales shares of hea, recomputed: hea output sold to g, and to p, versus the representative sales shares.
hea = sec.index('hea')
hea_out = float(OUTC[usa_i, hea])
hea_to_g = float(P[usa_i, hea, usa_i, g_ai])
hea_to_p = float(P[usa_i, hea, usa_i, agents.index('p')])
# Representative sales shares: plain sum of member "to g" / plain sum of member output, domestic column only
# is not the S03 sales share. S03-R4 compared the share of the sector's own output. Recompute that way
# for the 41 so the brief does not depend on copying the S03 outlier file.
mem = np.array(mem_ix)
hea_g_share_rep_num = 0.0
hea_p_share_rep_num = 0.0
hea_out_rep = 0.0
for ix in mem_ix:
    hea_g_share_rep_num += float(P[ix, hea, ix, g_ai])
    hea_p_share_rep_num += float(P[ix, hea, ix, agents.index('p')])
    hea_out_rep += float(OUTC[ix, hea])
S.check('S04-R4',
        'USA 9C ratios, government-services share, G composition against the representative composition, '
        'and H1 residuals. Report only. USA passes the ratio test, and no USA-table cell changes',
        'report',
        f'r_table {usa["r_table"]:.6f}; r_macro {usa["r_macro"]:.6f}; factor {usa["factor"]:.6f}; '
        f'fold {usa["fold"]:.6f}; {usa["result"]}; govsvc {usa["govsvc_share"]:.4f}; '
        f'USA columns changed {usa_col_changed}',
        'accept; USA columns changed 0',
        usa['result'] == 'accept' and usa_col_changed == 0,
        CIT_9C,
        f'G basic {usa["g_basic"]:.4f}; TLS on G {usa["g_tls"]:.4f}; ICIO GDP {usa["icio_gdp"]:.4f}; '
        f'S02 G {usa["s02_G"]:.4f}; S02 GDP {usa["s02_GDP"]:.4f}; source {usa["G_source"]}. '
        'Top composition gaps (share of G): ' + '; '.join(
            f'{name} USA {us:.4f} rep {rp:.4f}' for _d, name, us, rp, _usd in usa_gaps[:10]) +
        f'. hea sold to g is {hea_to_g / hea_out:.4f} of USA hea output against '
        f'{hea_g_share_rep_num / hea_out_rep:.4f} in the plain sum of the 41; '
        f'sold to p {hea_to_p / hea_out:.4f} against {hea_p_share_rep_num / hea_out_rep:.4f}. '
        'Why BEA or the OECD record health spending between households and government is unverified in this stage.')

# R6. Row imbalance left by the revision. Report only: this check writes no cell.
if not gap_records:
    S.check('S04-R6',
            'Per-product row imbalance after a government revision: the sales gap against published output. '
            'Report only. S13 absorbs it',
            'report', 'not applicable', 'report', True, 'E40', 'No revised economy.')
else:
    rows_imb = []
    total_gap = 0.0
    for origin, name, kind, _before, _after, gap in gap_records:
        total_gap += gap
        if kind != 'product':
            continue
        outv = float(OUTC[economies.index(origin), sec.index(name)])
        pct = gap / outv if outv != 0 else float('nan')
        rows_imb.append((abs(gap), origin, name, gap, outv, pct))
    rows_imb.sort(reverse=True)
    gdp_ref = float(by_eco[revise[0]]['icio_gdp'])
    pct_gdp = total_gap / gdp_ref
    top_txt = '; '.join(
        f'{o}_{n} {g:+,.0f} on output {outv:,.0f} ({pct:+.0%})'
        for _, o, n, g, outv, pct in rows_imb[:5])
    S.check('S04-R6',
            'Per-product row imbalance after the government revision. '
            'The gap is the change in that row\'s sales; the percent is the gap over published output, which is not changed. '
            'Report only. The total is left for S13',
            'report',
            f'total gap {total_gap:,.2f} USD m = {pct_gdp:.1%} of {revise[0]} ICIO GDP; top: {top_txt}',
            'report only; no cell changed',
            False, 'E40',
            'Sorted by absolute gap. ' + top_txt)

# ---------------------------------------------------------------- write the small outputs
def f6(v):
    return f'{v:.6f}'


def f8(v):
    return f'{v:.8f}'


def f12(v):
    return f'{v:.12f}'


check_rows = []
for r in rows_9c_sorted:
    check_rows.append((
        r['economy'], r['rep_member'], f6(r['g_basic']), f6(r['g_tls']), f6(r['G_table']),
        f6(r['icio_gdp']), f6(r['s02_G']), f6(r['s02_GDP']), r['G_source'],
        f8(r['r_table']), f8(r['r_macro']), f8(r['factor']), f8(r['fold']),
        r['result'], f8(r['govsvc_share']), r['action']))
S.write('gov_consumption_check.csv', check_rows,
        ['economy', 'rep_member', 'g_basic', 'g_tls', 'G_table', 'icio_gdp', 's02_G', 's02_GDP',
         'G_source', 'r_table', 'r_macro', 'factor', 'fold', 'result', 'govsvc_share', 'action'])

comp_rows = []
for si, name in enumerate(sec):
    comp_rows.append((name, f6(rep_dom[si]), f6(rep_imp[si]), f6(rep_basic[si]), f12(rep_share[si]), '41'))
comp_rows.append(('TLS', '', '', f6(rep_tls), f12(rep_tls_share), '41'))
S.write('rep_g_composition.csv', comp_rows,
        ['product', 'domestic_musd', 'imported_musd', 'total_musd', 'share', 'n_members'])

# Read the share column back so H7's file, not a second in-memory copy, is what we would have compared.
# The check above used the same full-precision shares these 12 decimals come from. Confirm the file.
comp_back = pd.read_csv(S.out + '/rep_g_composition.csv')
file_shares = comp_back.set_index('product')['share'].astype(float)
share_file_err = max(abs(float(file_shares.loc[sec[si]]) - rep_share[si]) for si in range(n_s))
share_file_err = max(share_file_err, abs(float(file_shares.loc['TLS']) - rep_tls_share))
if share_file_err > 5e-12:
    raise SystemExit(f'rep_g_composition share round-trip {share_file_err}')

S.write('sector_classification_check.csv', class_rows,
        ['economy', 'labels_found', 'missing', 'extra', 'splits'])

if revise:
    S.write('gov_revision_gap.csv',
            [(o, s, k, f'{b:.10f}', f'{a:.10f}', f'{g:.10f}') for o, s, k, b, a, g in gap_records],
            ['origin', 'sector', 'kind', 'sales_before', 'sales_after', 'gap_musd'])
    # The file's gaps, re-read, equal the in-memory row changes.
    gap_back = pd.read_csv(S.out + '/gov_revision_gap.csv')
    if len(gap_back) != len(gap_records):
        raise SystemExit('gov_revision_gap row count changed on read-back')

usa_rows = [
    ('gov', 'g_basic', f6(usa['g_basic']), 'USD million, basic prices, sum of the USA g column'),
    ('gov', 'g_tls', f6(usa['g_tls']), 'TLS row on USA g'),
    ('gov', 'G_table', f6(usa['G_table']), 'purchasers\' prices, basic plus TLS'),
    ('gov', 'icio_gdp', f6(usa['icio_gdp']), 'S03 ICIO GDP, VA + TLS as published'),
    ('gov', 's02_G', f6(usa['s02_G']), 'S02 country row, 50 states + DC'),
    ('gov', 's02_GDP', f6(usa['s02_GDP']), 'S02 country row, WDI'),
    ('gov', 'G_source', usa['G_source'], ''),
    ('gov', 'r_table', f8(usa['r_table']), 'G_table / icio_gdp'),
    ('gov', 'r_macro', f8(usa['r_macro']), 's02_G / s02_GDP'),
    ('gov', 'factor', f8(usa['factor']), 'r_table / r_macro'),
    ('gov', 'fold', f8(usa['fold']), 'max(factor, 1/factor)'),
    ('gov', 'result', usa['result'], 'fold > 2 rejects'),
    ('gov', 'govsvc_share', f8(usa['govsvc_share']), 'gov+edu+hea over basic G'),
    ('table', 'usa_columns_changed', str(usa_col_changed), 'H6 count for the USA table; expect 0'),
    ('hea', 'share_of_G', f8(float(usa_shares[hea])), 'USA hea purchases over USA purchasers\' G'),
    ('hea', 'rep_share_of_G', f8(float(rep_share[hea])), 'representative hea share of G'),
    ('hea', 'sales_share_to_g', f8(hea_to_g / hea_out), 'USA hea output sold to USA g'),
    ('hea', 'rep_sales_share_to_g', f8(hea_g_share_rep_num / hea_out_rep), 'plain sum of the 41, hea sold to own g, over hea output'),
    ('hea', 'sales_share_to_p', f8(hea_to_p / hea_out), 'USA hea output sold to USA p'),
    ('hea', 'rep_sales_share_to_p', f8(hea_p_share_rep_num / hea_out_rep), 'plain sum of the 41, hea sold to own p, over hea output'),
    ('hea', 'explanation', 'unverified',
     'How BEA or the OECD place health spending such as Medicare and Medicaid between households and government is not cited here'),
]
for rank, (_d, name, us, rp, usd) in enumerate(usa_gaps[:10], 1):
    usa_rows.append((f'composition_gap_{rank:02d}', name, f'{us - rp:.8f}',
                     f'USA share {us:.6f}; representative {rp:.6f}; USA USD m {usd:.4f}'))
for rank, (mx, name, sales, costs, outv, dsc, dso, dco) in enumerate(usa_h1[:5], 1):
    usa_rows.append((f'h1_residual_{rank}', name, f'{mx:.6f}',
                     f'sales {sales:.4f}; costs {costs:.4f}; OUT {outv:.4f}; '
                     f'sales-costs {dsc:+.4f}; sales-OUT {dso:+.4f}; costs-OUT {dco:+.4f}'))
S.write('usa_scrutiny_s04.csv', usa_rows, ['item', 'key', 'value', 'note'])

# File size cap from the handoff: each output under 50 MB.
too_big = []
for fn in os.listdir(S.out):
    sz = os.path.getsize(S.out + '/' + fn)
    if sz >= 50 * 1024 * 1024:
        too_big.append(f'{fn} {sz}')
if too_big:
    raise SystemExit('output file at or over 50 MB: ' + ' '.join(too_big))

S.log('rejected ' + (', '.join(rejected) or 'none')
      + '; near ' + ', '.join(r['economy'] for r in near)
      + f'; ledger {len(S.ledger)}; USA fold {usa["fold"]:.6f}')
S.finish()
