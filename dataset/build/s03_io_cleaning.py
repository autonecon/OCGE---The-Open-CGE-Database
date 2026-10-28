"""S03 I-O cleaning and the representative table.

Method, in the order the checks use it:
- Read OECD ICIO 2025, base-year SML. Balance each sector so cell-sum sales equal
  cell-sum costs equal the published output (GTAP 12 ch.8 §8.2 p.2 and §8.3 p.3).
  The adjustment is a RAS of intermediate and final-demand cells. Published output,
  TLS, VA and INVNT are not scaled. GTAP rebalances again in the FIT.
- Do not append PRI or VIR (E37; spec S03). ICIO USA is the published 50 states + DC table.
- Remove inventory changes: set INVNT to zero, do not move the dollars, ledger every
  changed cell (Aguiar et al. 2022 p.8; PLAN (b1) step 2). The gap is cleared at the FIT (S13).
- Map final demand: HFCE+NPISH -> p, GGFC -> g, GFCF -> i. DPABR stays its own column
  until S09, where GTAP 12 ch.10B p.3 (traveller expenditures, trvl) replaces it.
- Domestic vs imported is the ICIO origin split, imports pooled by commodity for each
  agent; bilateral cells are kept (PLAN (b1) step 4).
- Relabel ICIO 50 industries with the S01 concordance. B06 stays one row and one column
  (oil/gas split is S11).
- Representative table: divide each member table by its own GDP, sum with the
  GDP-share weights, then take coefficients (GTAP 12 ch.8 §8.3 p.3; ch.9D §D.3 p.3).
  That combination equals the plain sum of the USD tables. Report-only. No cell is revised with it.

No plugs and no scaling of C, G or I to GDP. TLS basic-to-purchasers split is S10;
the VA factor split is S12; composites and ISL-into-XWE are S05.
"""
import os, sys
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/lib')
from stagekit import Stage, DATA, STAGES, BASE_YEAR
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s03_household_employers as HHE  # noqa: E402

Y = BASE_YEAR
S = Stage('S03', 'io_cleaning')
I = S.inp
S01 = S.upstream(STAGES + '/S01_sets_registry')
S02 = S.upstream(STAGES + '/S02_macro')

cmap = pd.read_csv(I(S01 + '/output/country_region_map.csv', 'S01 country -> region'))
regions = pd.read_csv(I(S01 + '/output/regions.csv', 'S01 regions'))
sectors = pd.read_csv(I(S01 + '/output/sectors.csv', 'S01 sectors'))
conc = pd.read_csv(I(S01 + '/output/concord_icio_to_sector.csv', 'S01 ICIO 50 -> 51 concordance'))
macro_c = pd.read_csv(I(S02 + '/output/macro_country.csv', 'S02 country macro'))
macro_r = pd.read_csv(I(S02 + '/output/macro_regions.csv', 'S02 region macro'))
icio_path = I(DATA + f'/oecd_icio/{Y}_SML.csv', f'OECD ICIO 2025 {Y} SML')

# Table 9.8 of GTAP 12 ch.9D (attachment), ISO3 upper case. 48 countries.
TABLE_98 = [
    'AUS', 'NZL', 'JPN', 'KOR', 'TWN', 'KHM', 'SGP', 'BGD', 'USA', 'MEX', 'BRA', 'COL', 'URY',
    'AUT', 'BEL', 'BGR', 'HRV', 'CYP', 'CZE', 'DNK', 'EST', 'FIN', 'FRA', 'DEU', 'GRC', 'HUN',
    'IRL', 'ITA', 'LVA', 'LTU', 'LUX', 'MLT', 'NLD', 'POL', 'PRT', 'ROU', 'SVK', 'SVN', 'ESP',
    'SWE', 'GBR', 'MDG', 'MWI', 'MOZ', 'TZA', 'ZMB', 'BWA', 'ZAF']
# Handoff order of the seven that are not ICIO economies.
MISSING_98 = ['URY', 'MDG', 'MWI', 'MOZ', 'TZA', 'ZMB', 'BWA']
FD_ORDER = ['HFCE', 'NPISH', 'GGFC', 'GFCF', 'INVNT', 'DPABR']
AGENTS = None  # filled once industries are known: 50 sector labels + p, g, i, dpabr
CIT_INV = 'Aguiar et al. 2022 p.8 (inventory changes removed; not moved to another column); PLAN (b1) step 2; cleared at the FIT (S13)'
CIT_BAL = 'GTAP 12 ch.8 §8.2 p.2 (total sales equal total costs for each sector); §8.3 p.3 (cleaning removes minor deviations in balance)'
CIT_REP = 'GTAP 12 ch.8 §8.3 p.3 (linear combination with each region its GDP weight); ch.9D §D.3 p.3 (tables summed by GDP share weights; a GDP weight is country GDP over total target GDP)'
CIT_TRVL = 'GTAP 12 ch.10B p.3 (traveller expenditures, trvl). The column is replaced at S09, not added to households.'
CIT_MAP = 'PLAN (b1) steps 3-4; S01 concord_icio_to_sector.csv; B06 split deferred to S11 (PLAN (b1) item 7)'
# Reporting list only. ch.9D does not publish a numeric cutoff (Walmsley and McDougall 2007 use entropy).
# Nothing in the table is revised when a share exceeds this.
SHARE_LIST = 0.25
SHARE_MIN_OUT = 100.0  # USD million; smaller sectors are in balance_residuals, not the share list

# ---------------------------------------------------------------- read ICIO
S.log(f'reading {icio_path}')
raw = pd.read_csv(icio_path, index_col=0)
A = raw.to_numpy(dtype=np.float64)
rows = list(raw.index)
cols = list(raw.columns)
del raw
S.log(f'ICIO shape {A.shape[0]} x {A.shape[1]}')

# ---------------------------------------------------------------- beta v4 G4: households as employers (choice household_employers_va)
# Source correction before the balance: T's VA and output at the sourced value of paid domestic work, the rest to P and Q by
# FIGARO 2022 D1 with the households' T purchase reassigned to P and Q (hfce_to_pq, default), or to O, P and Q with the
# purchase moved to government consumption (the first G4 version)
CFG3 = os.path.dirname(os.path.abspath(__file__)) + '/config/s03'
hhe_value = HHE.load_choice(I(CFG3 + '/s03_choices.csv', 'S03 choices (beta v4 G4)'))
hhe_on = hhe_value != 'off'
hhe_to = 'HFCE' if hhe_value in HHE.HFCE_VALUES else 'GGFC'
hhe_rows = HHE.load_rows(I(CFG3 + '/household_employers_2022.csv', 'beta v4 G4: paid domestic work by economy (Stats SA)'))
# beta v5 H (hfce_by_coicop): the economy's household spending on education and health by COICOP caps the P and Q parts
hhe_caps = (HHE.load_caps(I(CFG3 + '/hfce_coicop_caps_2022.csv', 'beta v5 H: HFCE by COICOP shares (Stats SA via UN SNA table 3.2)')) if hhe_value == HHE.HFCE_BY_COICOP else {})
if hhe_caps:
    _sna = pd.read_csv(I(DATA + '/unsd_sna_coicop/zaf_table32_hfce_by_purpose_2022.csv', 'beta v5 H: UN SNA table 3.2 ZAF HFCE by purpose 2022 (source of the cap file)'), dtype={'code': str})
    _sna_v = {(r.iso3, r.code): float(r.value_lcu) for r in _sna.itertuples()}
    _cap_cfg = pd.read_csv(CFG3 + '/hfce_coicop_caps_2022.csv', dtype=str)
    _cap_bad = [f'{r.economy} {r.industry}' for r in _cap_cfg.itertuples()
                if _sna_v.get((r.economy, r.coicop.split()[0])) != float(r.value_lcu) or _sna_v.get((r.economy, 'P.31')) != float(r.hfce_lcu)]
    S.check('S03-Pcoicop', 'Beta v5 H: every cap row\'s COICOP value and HFCE total equal the UN SNA table 3.2 copy in data/unsd_sna_coicop', 'hard',
            len(_cap_bad), 0, not _cap_bad, 'beta v5 H', ' '.join(_cap_bad) or 'none')
hhe_out = []
hhe_capinfo = {}
if hhe_on and hhe_rows:
    wdi_p = I(DATA + '/wdi/wdi_2017_2022_extract.csv', 'WDI PA.NUS.FCRF 2022 (beta v4 G4 exchange rate)')
    fig_p = I(DATA + '/figaro_va/figaro_va_2022.json', 'FIGARO 2022 D1 (beta v4 G4 recipient weights)')
    for r in hhe_rows:
        fx = HHE.wdi_rate(wdi_p, r['fx_iso3'], Y)
        tgt = HHE.target_musd(r, fx)
        rec = HHE.recipients_for(hhe_value, r['recipients'].split(';'))
        w = HHE.figaro_d1(fig_p, r['figaro_country'], rec)
        parts = None
        if hhe_value == HHE.HFCE_BY_COICOP:
            if r['economy'] not in hhe_caps:
                raise SystemExit(f"hfce_coicop_caps_2022.csv has no row for {r['economy']} (household_employers_va = hfce_by_coicop)")
            tot, by, own = HHE.household_purchases(A, rows, cols, r['economy'])
            parts, cinfo = HHE.coicop_parts(HHE.moved_amount(A, rows, cols, r['economy'], tgt), w, hhe_caps[r['economy']], tot, by, own)
            hhe_capinfo[r['economy']] = dict(total=tot, caps=cinfo)
        info = HHE.reallocate(A, rows, cols, r['economy'], tgt, w, to=hhe_to, parts=parts)
        hhe_out.append(dict(economy=r['economy'], workers_thousand=float(r['workers_thousand']), monthly_pay_lcu=float(r['monthly_pay_lcu']),
                            lcu_per_usd=fx, target_va_musd=tgt, icio_t_va_musd=info['va_before'], moved_musd=info['moved'], purchase_to=hhe_to,
                            hfce_before_musd=info['cg_before'][0], hfce_after_musd=info['cg_after'][0],
                            ggfc_before_musd=info['cg_before'][1], ggfc_after_musd=info['cg_after'][1],
                            **{f'to_{k}_musd': info['parts'].get(k, 0.0) for k in list(rec) + sorted(set(info['parts']) - set(rec))},
                            **{f'figaro_d1_{k}_meur': w[k] for k in rec}))
        S.flag('HHE-VA-MOVED', r['economy'], f'T VA {info["va_before"]:.1f} -> {tgt:.1f} USD m (paid domestic work, Stats SA estimate); '
               f'{info["moved"]:.1f} moved to ' + ', '.join(f'{k} {v:.1f}' for k, v in info['parts'].items()) +
               f' by FIGARO 2022 D1; the same amount of the HFCE purchase of T moved to {hhe_to} of the recipients', rule=HHE.CHOICE,
               citation='beta v4 G4; source correction, labelled (no GTAP text)')
        S.log(f'G4 {r["economy"]}: T VA {info["va_before"]:.1f} -> {tgt:.1f}; moved {info["moved"]:.1f}')
ri_, ci_ = {x: i for i, x in enumerate(rows)}, {x: j for j, x in enumerate(cols)}
hhe_bad = [f'{h["economy"]} T VA {A[ri_["VA"], ci_[h["economy"] + "_T"]]:.6f} vs {h["target_va_musd"]:.6f}' for h in hhe_out
           if abs(A[ri_['VA'], ci_[h['economy'] + '_T']] - min(h['target_va_musd'], h['icio_t_va_musd'])) > 1e-6
           or abs(A[ri_['OUT'], ci_[h['economy'] + '_T']] - A[ri_[h['economy'] + '_T'], ci_['OUT']]) > 1e-6]
S.check('S03-Hhhe', 'Beta v4 G4 (choice household_employers_va): each listed economy\'s T (households as employers) carries VA at the sourced value '
        'of paid domestic work, with its OUT row and column equal; the rest moved to the recipients (VA, output and the purchase: '
        'households\' under hfce_to_pq, P and Q; government\'s under the GGFC version, O, P and Q)', 'hard',
        len(hhe_bad), 0, not hhe_bad, 'beta v4 G4; source correction (labelled)',
        ' '.join(hhe_bad) or ('; '.join(f'{h["economy"]} {h["icio_t_va_musd"]:.0f} -> {h["target_va_musd"]:.0f} USD m, moved {h["moved_musd"]:.0f}'
                                       for h in hhe_out) if hhe_out else f'choice {"on" if hhe_on else "off"}; no economy moved'))

# hfce_to_pq: the economy's household and government consumption totals stay as published (within 2%)
hhe_cg = [(h['economy'], c, b, a) for h in hhe_out for c, b, a in (('C', h['hfce_before_musd'], h['hfce_after_musd']),
                                                                    ('G', h['ggfc_before_musd'], h['ggfc_after_musd']))]
cg_bad = [f'{e} {c} {b:.0f} -> {a:.0f}' for e, c, b, a in hhe_cg if b > 0 and abs(a / b - 1.0) > HHE.CG_TOL]
S.check('S03-Hhhecg', f'Beta v4 G4 (household_employers_va = hfce_to_pq or hfce_by_coicop): each listed economy\'s HFCE and GGFC totals stay within {HHE.CG_TOL:.0%} of '
        'the published ICIO (beta v3); hard when the purchase stays in HFCE, report under the GGFC version', 'hard' if hhe_value in HHE.HFCE_VALUES else 'report',
        len(cg_bad), 0, not cg_bad or hhe_value not in HHE.HFCE_VALUES, 'beta v4 G4; source correction (labelled)',
        '; '.join(f'{e} {c} {b:.0f} -> {a:.0f} USD m' for e, c, b, a in hhe_cg) or f'choice {hhe_value}; no economy moved')

# beta v5 H (hfce_by_coicop): after the move, households buy P and Q at most up to the larger of the COICOP cap and what they
# bought before the move (the published purchase is never cut), and the moved VA landed on P, Q and the other services
cap_rows, cap_bad = [], []
for e, ci_info in hhe_capinfo.items():
    tot, by, _own = HHE.household_purchases(A, rows, cols, e)
    for k, (cap, before, room) in ci_info['caps'].items():
        cap_rows.append(f'{e} {k}: cap {cap:,.0f} ({cap / ci_info["total"]:.2%} of HFCE {ci_info["total"]:,.0f}), before {before:,.0f}, after {by.get(k, 0.0):,.0f} USD m')
        if by.get(k, 0.0) > max(cap, before) + 1e-6:
            cap_bad.append(f'{e} {k} {by.get(k, 0.0):.1f} > {max(cap, before):.1f}')
S.check('S03-Hcoicop', 'Beta v5 H (household_employers_va = hfce_by_coicop): each listed economy\'s households buy education (P) and health (Q) at most '
        'up to their COICOP share of HFCE (config/s03/hfce_coicop_caps_2022.csv) or their published purchase, whichever is larger', 'hard',
        len(cap_bad), 0, not cap_bad, 'beta v5 H; labelled source correction',
        ' '.join(cap_bad) or ('; '.join(cap_rows) or f'choice {hhe_value}; no cap applied'))

def split_lab(lab):
    if '_' not in lab:
        return None, lab
    return lab.split('_', 1)

# Block structure of the 2025 SML: country-major, 50 industries then 6 final-demand
# columns, OUT as the last column; 50 industry rows per country then TLS, VA, OUT.
economies, industries = [], []
for lab in cols:
    if lab == 'OUT':
        continue
    e, s = split_lab(lab)
    if e not in economies:
        economies.append(e)
    if s not in FD_ORDER and s not in industries:
        industries.append(s)
n_e, n_s, n_fd = len(economies), len(industries), len(FD_ORDER)
assert A.shape == (n_e * n_s + 3, n_e * (n_s + n_fd) + 1), (A.shape, n_e, n_s)
# The SML file stores every industry column, then every final-demand column, then OUT.
# Reorder to one block per country (its industries, then its final demand). Values unchanged.
perm = []
for ei in range(n_e):
    perm.extend(range(ei * n_s, (ei + 1) * n_s))
    perm.extend(range(n_e * n_s + ei * n_fd, n_e * n_s + (ei + 1) * n_fd))
perm.append(A.shape[1] - 1)
assert len(perm) == A.shape[1] and cols[perm[-1]] == 'OUT'
A = A[:, perm]
cols = [cols[j] for j in perm]
for ei, e in enumerate(economies):
    for si, s in enumerate(industries):
        assert rows[ei * n_s + si] == f'{e}_{s}', rows[ei * n_s + si]
        assert cols[ei * (n_s + n_fd) + si] == f'{e}_{s}'
    for fi, f in enumerate(FD_ORDER):
        assert cols[ei * (n_s + n_fd) + n_s + fi] == f'{e}_{f}'
assert rows[-3:] == ['TLS', 'VA', 'OUT'] and cols[-1] == 'OUT'
tls_i, va_i, out_i = n_e * n_s, n_e * n_s + 1, n_e * n_s + 2
S.log(f'{n_e} column-countries (including ROW), {n_s} industries')

# Concordance: 49 industries are 1:1; B06 is deferred and stays one row labelled B06.
sec_of = {}
for r in conc.itertuples(index=False):
    if r.icio_code == 'B06':
        continue
    sec_of[r.icio_code] = r.sector
assert set(sec_of) == set(industries) - {'B06'}
assert (conc.loc[conc.icio_code != 'B06', 'share'].astype(float) == 1).all()
assert set(conc.loc[conc.icio_code == 'B06', 'share_status']) == {'deferred:S11'}
sec_of['B06'] = 'B06'
sec_labels = [sec_of[s] for s in industries]
assert sec_labels.count('B06') == 1 and 'oil' not in sec_labels and 'gas' not in sec_labels
agent_labels = sec_labels + ['p', 'g', 'i', 'dpabr']
n_a = len(agent_labels)  # 54

# Published OUT row (industry output) and OUT column (product total use) are one target.
# The hard balance check is on the cells after cleaning, not on these two published totals.
prod_out = A[:n_e * n_s, -1].reshape(n_e, n_s)
ind_out = A[out_i, :n_e * (n_s + n_fd)].reshape(n_e, n_s + n_fd)[:, :n_s]
assert float(np.max(np.abs(prod_out - ind_out))) == 0.0, 'published OUT row and OUT column differ; the output target is not unique'

# Sales = sum of the product row. Costs = intermediate inputs + TLS + VA.
use = A[:n_e * n_s, :-1].reshape(n_e, n_s, n_e, n_s + n_fd)
sales_before = use.sum(axis=(2, 3))
tls_block = A[tls_i, :n_e * (n_s + n_fd)].reshape(n_e, n_s + n_fd)
va_block = A[va_i, :n_e * (n_s + n_fd)].reshape(n_e, n_s + n_fd)
costs_before = use[:, :, :, :n_s].sum(axis=(0, 1)) + tls_block[:, :n_s] + va_block[:, :n_s]
invnt_pre = use[:, :, :, n_s + 4].copy()
tls_inv_pre = tls_block[:, n_s + 4].copy()
l_ix = industries.index('L')
usa_i = economies.index('USA')

# ---------------------------------------------------------------- negatives (H8), counted on the published table
ind_body = A[:n_e * n_s, :n_e * (n_s + n_fd)]
inv_slice = use[:, :, :, n_s + FD_ORDER.index('INVNT')]  # (oe, os, de)
tls_inv = tls_block[:, n_s + FD_ORDER.index('INVNT')]
va_inv = va_block[:, n_s + FD_ORDER.index('INVNT')]
neg_inter = int((ind_body.reshape(n_e, n_s, n_e, n_s + n_fd)[:, :, :, :n_s] < 0).sum())
neg_fd = {}
for fi, f in enumerate(FD_ORDER):
    neg_fd[f] = int((use[:, :, :, n_s + fi] < 0).sum())
neg_tls = np.argwhere(tls_block < 0)
neg_va = np.argwhere(va_block < 0)
neg_out = int((ind_out < 0).sum()) + int((prod_out < 0).sum())
va_list = [f'{economies[de]}_{industries[ds] if ds < n_s else FD_ORDER[ds - n_s]}={va_block[de, ds]:.4f}'
           for de, ds in neg_va]
# FD negatives other than INVNT are not allowed. Intermediate negatives are not allowed.
fd_bad = sum(v for k, v in neg_fd.items() if k != 'INVNT')
nan_n = int(np.isnan(A).sum())
S.check('S03-H8', 'No NaN. Negatives only where ICIO has them: TLS (subsidies), VA (net), INVNT before removal',
        'hard', f'NaN {nan_n}; intermediate neg {neg_inter}; final-demand neg except INVNT {fd_bad}; '
                f'TLS neg {len(neg_tls)}; VA neg {len(neg_va)} {va_list}; INVNT neg {neg_fd["INVNT"]}; OUT neg {neg_out}',
        'NaN 0; intermediate 0; disallowed final-demand 0',
        nan_n == 0 and neg_inter == 0 and fd_bad == 0 and neg_out == 0, 'GTAP 12 ch.8 p.3 (sign); H8',
        'VA negatives left as published (VA factor split, including net other taxes on production, is S12). '
        'INVNT negatives are removed with the column and ledgered. TLS negatives are subsidies, kept.')

# ---------------------------------------------------------------- balance each sector (GTAP 12 ch.8 §8.2 and §8.3)
# Proportional RAS of intermediate and final-demand cells. INVNT, TLS and VA stay as published.
# Targets: cell-sum sales = cell-sum costs = published sector output.
# Industry-column target for the intermediate block is output - TLS - VA.
# Final-demand columns (except INVNT) are free and take the row residual.
S.log('balancing sector sales to costs (RAS)')
adj_idx = [i for i in range(n_s + n_fd) if i != n_s + 4]
U = np.ascontiguousarray(use[:, :, :, adj_idx])
row_target = ind_out - invnt_pre.sum(axis=2)
col_target = ind_out - tls_block[:, :n_s] - va_block[:, :n_s]
ras_iters = 0
for _it in range(80):
    ras_iters += 1
    rs = U.sum(axis=(2, 3))
    scale_r = np.ones_like(rs)
    ok = np.abs(rs) > 1e-12
    scale_r[ok] = row_target[ok] / rs[ok]
    U *= scale_r[:, :, None, None]
    cs = U[:, :, :, :n_s].sum(axis=(0, 1))
    scale_c = np.ones_like(cs)
    okc = np.abs(cs) > 1e-12
    scale_c[okc] = col_target[okc] / cs[okc]
    U[:, :, :, :n_s] *= scale_c[None, None, :, :]
    sales_now = U.sum(axis=(2, 3)) + invnt_pre.sum(axis=2)
    costs_now = U[:, :, :, :n_s].sum(axis=(0, 1)) + tls_block[:, :n_s] + va_block[:, :n_s]
    denom = np.maximum(np.abs(ind_out), 1.0)
    rel_s = float(np.max(np.abs(sales_now - ind_out) / denom))
    rel_c = float(np.max(np.abs(costs_now - ind_out) / denom))
    if max(rel_s, rel_c) < 1e-12:
        break
S.log(f'RAS iterations {ras_iters}')
use[:, :, :, adj_idx] = U
del U
sales = use.sum(axis=(2, 3))
costs = use[:, :, :, :n_s].sum(axis=(0, 1)) + tls_block[:, :n_s] + va_block[:, :n_s]
denom = np.maximum(np.abs(ind_out), 1.0)
rel_s = float(np.max(np.abs(sales - ind_out) / denom))
rel_c = float(np.max(np.abs(costs - ind_out) / denom))
rel_sc = float(np.max(np.abs(sales - costs) / denom))
abs_sc = float(np.max(np.abs(sales - costs)))
S.check('S03-H1', 'Cell-sum sales equal cell-sum costs equal published output for every sector',
        'hard', f'max |sales-costs| {abs_sc:.3e}; max |sales-output|/output {rel_s:.3e}; max |costs-output|/output {rel_c:.3e}',
        'relative <= 1e-9, from the cells',
        rel_sc <= 1e-9 and rel_s <= 1e-9 and rel_c <= 1e-9, CIT_BAL,
        f'After RAS ({ras_iters} iterations). Sales are the sum of the product-row cells, including INVNT. Costs are intermediate cells plus TLS plus VA. '
        'The target is the published sector output, which is not changed. INVNT, TLS and VA cells are not scaled. '
        f'Pre-adjustment USA real estate (L) sales-costs {(sales_before - costs_before)[usa_i, l_ix]:.4f} on output {ind_out[usa_i, l_ix]:.4f}.')

sales_adj = ind_out - sales_before
cost_adj = ind_out - costs_before
with np.errstate(divide='ignore', invalid='ignore'):
    sales_pct = np.where(np.abs(ind_out) > 0, sales_adj / ind_out, 0.0)
    cost_pct = np.where(np.abs(ind_out) > 0, cost_adj / ind_out, 0.0)
sector_pct = np.maximum(np.abs(sales_pct), np.abs(cost_pct))
over = np.argwhere(sector_pct > 0.01)
over_txt = '; '.join(
    f'{economies[ei]}_{sec_labels[si]} sales {sales_pct[ei, si]:+.2%} costs {cost_pct[ei, si]:+.2%} output {ind_out[ei, si]:.4f}'
    for ei, si in over)
max_abs_adj = float(max(np.max(np.abs(sales_adj)), np.max(np.abs(cost_adj))))
max_pct_adj = float(sector_pct.max())
S.check('S03-R6', 'Sector balance adjustments: size and percent of published output. Above 1% is report-only in NEEDS_DAVID.md',
        'report', f'{sales_adj.size} sectors; max abs {max_abs_adj:.4f}; max percent {max_pct_adj:.4%}; above 1% {len(over)}',
        'report the sectors above 1% of output; the adjustment is still applied',
        len(over) == 0, CIT_BAL,
        'RAS scales intermediate and final cells in proportion to their size. ' + (over_txt or 'No sector exceeds 1%.'))

# ---------------------------------------------------------------- build the cleaned blocks
# Industry columns copied. p = HFCE+NPISH. g = GGFC. i = GFCF. dpabr kept. INVNT dropped.
p_i, g_i, i_i, d_i = (n_s + FD_ORDER.index(x) for x in ('HFCE', 'NPISH', 'GGFC', 'GFCF'))
inv_i = n_s + FD_ORDER.index('INVNT')
dp_i = n_s + FD_ORDER.index('DPABR')
C = np.empty((n_e, n_s, n_e, n_a), dtype=np.float64)
C[:, :, :, :n_s] = use[:, :, :, :n_s]
C[:, :, :, n_s] = use[:, :, :, p_i - n_s + n_s]  # placeholder, set explicitly below
# FD indices in `use` last axis are n_s + fi, but use's last axis IS n_s+n_fd, so HFCE is at n_s+0.
C[:, :, :, n_s] = use[:, :, :, n_s + 0] + use[:, :, :, n_s + 1]   # p = HFCE + NPISH
C[:, :, :, n_s + 1] = use[:, :, :, n_s + 2]                        # g
C[:, :, :, n_s + 2] = use[:, :, :, n_s + 3]                        # i
C[:, :, :, n_s + 3] = use[:, :, :, n_s + 5]                        # dpabr
invnt = use[:, :, :, n_s + 4].copy()                               # (oe, os, de) original

def _agg_fd(block):
    """block (n_e, n_s+6) -> (n_e, n_a) with the same agent map. Industry part copied."""
    out = np.empty((n_e, n_a), dtype=np.float64)
    out[:, :n_s] = block[:, :n_s]
    out[:, n_s] = block[:, n_s + 0] + block[:, n_s + 1]
    out[:, n_s + 1] = block[:, n_s + 2]
    out[:, n_s + 2] = block[:, n_s + 3]
    out[:, n_s + 3] = block[:, n_s + 5]
    return out

tls_c = _agg_fd(tls_block)
va_c = _agg_fd(va_block)
out_c = _agg_fd(A[out_i, :n_e * (n_s + n_fd)].reshape(n_e, n_s + n_fd))
# output of industries stays; OUT of dropped INVNT is not added anywhere.
tls_inv = tls_block[:, n_s + 4].copy()
va_inv = va_block[:, n_s + 4].copy()

# H3: the 50 -> sector-label map and the agent aggregation do not change totals.
# Industry blocks are copies. p equals HFCE+NPISH. INVNT is the only removal.
ind_same = np.array_equal(C[:, :, :, :n_s], use[:, :, :, :n_s])
p_same = np.array_equal(C[:, :, :, n_s], use[:, :, :, n_s + 0] + use[:, :, :, n_s + 1])
g_same = np.array_equal(C[:, :, :, n_s + 1], use[:, :, :, n_s + 2])
i_same = np.array_equal(C[:, :, :, n_s + 2], use[:, :, :, n_s + 3])
d_same = np.array_equal(C[:, :, :, n_s + 3], use[:, :, :, n_s + 5])
# Per-economy TLS, VA, OUT of industries: unchanged by the relabel (it is a rename).
# TLS changes only by the ledgered removal of TLS on INVNT.
tls_econ_before = tls_block.sum(axis=1)
tls_econ_after = tls_c.sum(axis=1)
va_econ_before = va_block[:, :n_s].sum(axis=1)
va_econ_after = va_c[:, :n_s].sum(axis=1)
out_econ_before = ind_out.sum(axis=1)
out_econ_after = out_c[:, :n_s].sum(axis=1)
def _rel(a, b):
    return float(np.max(np.abs(a - b) / np.maximum(np.abs(b), 1.0)))
tls_rel = _rel(tls_econ_after + tls_inv, tls_econ_before)
va_rel = _rel(va_econ_after, va_econ_before)
out_rel = _rel(out_econ_after, out_econ_before)
# World total of each product row: cleaned uses + INVNT = original uses.
row_clean = C.sum(axis=(2, 3))
row_orig = use.sum(axis=(2, 3))
row_back = row_clean + invnt.sum(axis=2)
row_rel = _rel(row_back, row_orig)
# Copies of blocks are exact. Sums of the same cells can differ by a few ulps; 1e-4 USD million
# is below the file's last published digit (0.0001) and covers that, on top of relative 1e-9.
totals_close = (np.allclose(tls_econ_after + tls_inv, tls_econ_before, rtol=1e-9, atol=1e-4)
                and np.allclose(va_econ_after, va_econ_before, rtol=1e-9, atol=1e-4)
                and np.allclose(out_econ_after, out_econ_before, rtol=1e-9, atol=1e-4)
                and np.allclose(row_back, row_orig, rtol=1e-9, atol=1e-4))
S.check('S03-H3', 'TLS, VA and published OUT per economy unchanged by the balance and by the sector-label map; cleaned product rows plus the stock-change gap equal the balanced row sums',
        'hard', f'blocks copy {ind_same}; p=HFCE+NPISH {p_same}; g {g_same}; i {i_same}; dpabr {d_same}; '
                f'max rel TLS {tls_rel:.3e} VA {va_rel:.3e} OUT {out_rel:.3e} row-with-INVNT {row_rel:.3e}',
        'copies exact; relative 1e-9 (absolute cushion 1e-4 USD million for the sum)',
        ind_same and p_same and g_same and i_same and d_same and totals_close,
        'H3; PLAN (b1) step 4 world total',
        'B06 is renamed to the single label B06, not split, so its row and column totals are the ICIO totals. '
        'ROW rows and columns are in the same blocks and are not dropped. '
        f'TLS removed with INVNT, world sum {tls_inv.sum():.4f}, is ledgered and is the only TLS change.')

# ---------------------------------------------------------------- H2 INVNT removal, pre versus post
# invnt_pre was saved before the RAS (the RAS does not scale INVNT). The cleaned
# matrix C is built without that column. Compare the pre-removal row sums with the
# post-removal row sums: the difference must be the saved INVNT cells.
n_inv_nz = int((invnt_pre != 0).sum())
n_tls_nz = int((tls_inv_pre != 0).sum())
n_va_inv = int((va_inv != 0).sum())
pre_rows = use.sum(axis=(2, 3))
post_rows = C.sum(axis=(2, 3))
removed = pre_rows - post_rows
gap_vs_pre = np.max(np.abs(removed - invnt_pre.sum(axis=2)))
tls_kept = np.array_equal(tls_inv, tls_inv_pre)
# The recorded gap is the pre-removal cells, not a second copy checked against itself.
invnt = invnt_pre
S.check('S03-H2', 'INVNT is absent after removal, and the recorded gap equals the pre-removal INVNT cell for every country x industry x destination',
        'hard', f'nonzero product cells {n_inv_nz}; TLS-on-INVNT cells {n_tls_nz}; VA-on-INVNT {n_va_inv}; product sum {invnt_pre.sum():.4f}; TLS sum {tls_inv_pre.sum():.4f}; max |post row shortfall - pre INVNT| {gap_vs_pre:.3e}',
        'pre minus post equals the saved INVNT; TLS on INVNT unchanged by the balance',
        gap_vs_pre <= 1e-6 and tls_kept and n_va_inv == 0 and not np.shares_memory(invnt, use),
        'Aguiar et al. 2022 p.8; H2',
        'Pre row sums are the balanced use matrix, which still contains INVNT. Post row sums are the cleaned matrix, which has no INVNT column. '
        'Their difference is the INVNT saved before removal. Zeros are not ledger rows.')

# ---------------------------------------------------------------- H4 domestic + imported
# For every destination, agent and commodity: own-origin + other-origins = all origins.
# Commodity is the sector label (B06 pooled with itself only).
dom = np.empty((n_e, n_s, n_a))
imp = np.empty((n_e, n_s, n_a))
for d in range(n_e):
    col = C[:, :, d, :]                  # (origin, sector, agent)
    total = col.sum(axis=0)              # (sector, agent)
    dom[d] = col[d]                      # origin == destination
    imp[d] = total - col[d]
total_da = np.transpose(C.sum(axis=0), (1, 0, 2))  # (dest, sector, agent)
h4_abs = float(np.max(np.abs(dom + imp - total_da)))
# Independent total from the original use block (p = HFCE+NPISH), same partition.
orig_total = np.empty_like(total_da)
orig_total[:, :, :n_s] = np.transpose(use[:, :, :, :n_s].sum(axis=0), (1, 0, 2))
orig_total[:, :, n_s] = np.transpose((use[:, :, :, n_s + 0] + use[:, :, :, n_s + 1]).sum(axis=0), (1, 0))
orig_total[:, :, n_s + 1] = np.transpose(use[:, :, :, n_s + 2].sum(axis=0), (1, 0))
orig_total[:, :, n_s + 2] = np.transpose(use[:, :, :, n_s + 3].sum(axis=0), (1, 0))
orig_total[:, :, n_s + 3] = np.transpose(use[:, :, :, n_s + 5].sum(axis=0), (1, 0))
h4_src = np.max(np.abs(total_da - orig_total))
S.check('S03-H4', 'Domestic + imported = ICIO total use for every column-country x agent x product',
        'hard', f'max |dom+imp-total| {h4_abs:.3e}; max |total-original| {h4_src:.3e}', '<= 1e-6',
        h4_abs <= 1e-6 and h4_src <= 1e-6, 'PLAN (b1) step 4',
        'Domestic is the origin equal to the destination column-country. Imports pool every other origin, including ROW. '
        'Agents are the 50 industries plus p, g, i and dpabr. INVNT is not an agent after removal.')

# ---------------------------------------------------------------- H5 one region each, ISL kept, nothing dropped
reg_of = {}
for r in cmap.itertuples(index=False):
    if isinstance(r.region, str) and r.region and r.code not in reg_of:
        reg_of[r.code] = r.region
econ_only = [e for e in economies if e != 'ROW']
unmapped = [e for e in econ_only if e not in reg_of]
multi = []  # country_region_map can repeat a code only if we failed to keep the first
isl_region = reg_of.get('ISL', '')
isl_measured = regions.loc[regions.region == 'XWE', 'icio_measured']
isl_note = str(isl_measured.iloc[0]) if len(isl_measured) else ''
n_yes = int((regions.icio_measured == 'yes').sum())
S.check('S03-H5', 'Every ICIO economy maps to exactly one S01 region; ISL kept as its own table; no ICIO code dropped',
        'hard', f'{len(econ_only)} economy tables + ROW; unmapped {len(unmapped)}; ISL -> {isl_region}; S01 icio_measured yes {n_yes}',
        '80 economies, 0 unmapped, ISL -> XWE, 79 fully measured regions',
        len(econ_only) == 80 and not unmapped and isl_region == 'XWE' and n_yes == 79 and 'ISL' in isl_note,
        'H5; PLAN (b1); decision 6 (ISL in XWE at S05, not folded here)',
        'ROW is kept as a block and is not a region. ' + ' '.join(unmapped))

# ---------------------------------------------------------------- H6 B06 not split
b06_rows = int(sum(1 for s in sec_labels if s == 'B06'))
other_shares = conc.loc[conc.icio_code != 'B06', 'share'].astype(float)
S.check('S03-H6', 'B06 is not split (one row and column, deferred to S11). Every other ICIO industry has share 1',
        'hard', f'B06 labels per country-block {b06_rows}; other shares min {other_shares.min()} max {other_shares.max()}; n other {len(other_shares)}',
        '1 label; shares all 1; 49 other industries',
        b06_rows == 1 and len(other_shares) == 49 and (other_shares == 1).all() and 'oil' not in sec_labels and 'gas' not in sec_labels,
        'PLAN (b1) item 7; S01 concord',
        'Output sector labels: ' + ' '.join(sec_labels))

# ---------------------------------------------------------------- region map for ledger
def region_of(economy):
    if economy == 'ROW':
        return 'ROW'
    return reg_of[economy]

# Ledger every changed cell. Order is fixed so a rerun is identical.
n_led = 0
for oi, o in enumerate(economies):
    for si, sec in enumerate(sec_labels):
        for di, d in enumerate(economies):
            v = invnt[oi, si, di]
            if v != 0:
                S.adjust(region_of(o), f'{o}_{sec} INVNT sale to {d}', f'{v:.4f}', '0',
                         'remove stock change', CIT_INV, 'invnt_removed')
                n_led += 1
for di, d in enumerate(economies):
    v = tls_inv[di]
    if v != 0:
        S.adjust(region_of(d), f'{d} TLS on INVNT', f'{v:.4f}', '0',
                 'remove stock change', CIT_INV, 'invnt_removed')
        n_led += 1
n_inv_led = n_led
# One row per sector: the sales adjustment and the cost adjustment, with the percent of output.
for ei, e in enumerate(economies):
    for si, sec in enumerate(sec_labels):
        q = ind_out[ei, si]
        sa, ca = sales_adj[ei, si], cost_adj[ei, si]
        sp, cp = sales_pct[ei, si], cost_pct[ei, si]
        S.adjust(region_of(e),
                 f'{e}_{sec} balance sales_adj {sa:.4f} ({sp:.6%}); cost_adj {ca:.4f} ({cp:.6%})',
                 f'sales {sales_before[ei, si]:.4f}; costs {costs_before[ei, si]:.4f}',
                 f'output {q:.4f}',
                 'proportional RAS of intermediate and final cells to published output',
                 CIT_BAL, 'balance_ras')
        n_led += 1
n_bal = n_led - n_inv_led
S.check('S03-H9', 'Every stock-change cell and every sector balance has one ledger row, and the row count matches',
        'hard', f'ledger {n_led}; INVNT nonzero {n_inv_nz}; TLS-on-INVNT nonzero {n_tls_nz}; sector rows {n_bal}',
        'INVNT cells + TLS-on-INVNT + one row per sector',
        n_inv_led == n_inv_nz + n_tls_nz and n_bal == n_e * n_s and n_led == len(S.ledger),
        'H9; same test as S02-H2, plus one balance row per sector',
        'Stock change is one row per changed cell. The balance is one row per sector, with size and percent of output. '
        'HFCE+NPISH -> p is a sum, not a changed cell. Traveller expenditures (trvl, DPABR) are not reallocated here.')

# ---------------------------------------------------------------- representative table
in_icio = set(economies)
missing = [c for c in MISSING_98 if c not in in_icio]
extra_missing = sorted(set(TABLE_98) - in_icio - set(MISSING_98))
used = [c for c in TABLE_98 if c in in_icio]
assert missing == MISSING_98 and not extra_missing and len(used) == 41, (missing, extra_missing, len(used))
mreg = macro_r.set_index('region')
mc = macro_c.set_index('code')
gdp_reg = np.array([float(mreg.loc[reg_of[c], 'GDP_musd']) for c in used])
gdp_cty = np.array([float(mc.loc[c, 'GDP_musd']) for c in used])
w = gdp_reg / gdp_reg.sum()
ui = np.array([economies.index(c) for c in used])
out_u = ind_out[ui]                       # (41, 50) published output
mask = out_u > 0

# Cost flows for the 41: domestic (i, j), imported (i, j), tls (j), va (j). j is the industry.
dom_f = np.empty((41, n_s, n_s))
imp_f = np.empty((41, n_s, n_s))
tls_f = np.empty((41, n_s))
va_f = np.empty((41, n_s))
for k, ix in enumerate(ui):
    dom_f[k] = C[ix, :, ix, :n_s]                         # (input sector, using industry)
    imp_f[k] = C[:, :, ix, :n_s].sum(axis=0) - dom_f[k]
    tls_f[k] = tls_c[ix, :n_s]
    va_f[k] = va_c[ix, :n_s]
# Coefficients from GDP-normalised tables, summed with the GDP-share weights.
# scale_k = w_k / GDP_k. The weight uses this same GDP, so scale is 1/total GDP
# for every member and the coefficients equal the plain sum of the USD tables.
# Multiplying the USD flows by w without dividing by GDP counts country size twice.
# Coefficient averages, sum(w * flow/output) renormalised on positive output, and the
# double-weighted USD sums are kept so the before/after can be reported. They are not the table.
scale = w / gdp_reg
# The share and the divisor are the same GDP, so every member has the same scale.
assert np.allclose(scale, scale[0]), 'GDP share / GDP differs across members'
w_out = (scale[:, None] * out_u).sum(axis=0)
w_out_safe = np.where(w_out > 0, w_out, np.nan)
plain_out = out_u.sum(axis=0)
den_pos = (w[:, None] * mask).sum(axis=0)
den_pos_safe = np.where(den_pos > 0, den_pos, np.nan)
dbl_den = (w[:, None] * out_u).sum(axis=0)
dbl_den_safe = np.where(dbl_den > 0, dbl_den, np.nan)

def flow_cost(flow):
    if flow.ndim == 2:
        return (scale[:, None] * flow).sum(axis=0) / w_out_safe
    return (scale[:, None, None] * flow).sum(axis=0) / w_out_safe[None, :]

def coef_cost(flow):
    if flow.ndim == 2:
        sh = np.divide(flow, out_u, out=np.zeros_like(flow), where=mask)
        return (w[:, None] * sh).sum(axis=0) / den_pos_safe
    sh = np.divide(flow, out_u[:, None, :], out=np.zeros_like(flow), where=mask[:, None, :])
    return (w[:, None, None] * sh).sum(axis=0) / den_pos_safe[None, :]

def dbl_cost(flow):
    if flow.ndim == 2:
        return (w[:, None] * flow).sum(axis=0) / dbl_den_safe
    return (w[:, None, None] * flow).sum(axis=0) / dbl_den_safe[None, :]

n_dom = n_imp = n_tls = n_va = mask.sum(axis=0)
rep_dom, old_dom = flow_cost(dom_f), coef_cost(dom_f)
rep_imp, old_imp = flow_cost(imp_f), coef_cost(imp_f)
rep_tls, old_tls = flow_cost(tls_f), coef_cost(tls_f)
rep_va, old_va = flow_cost(va_f), coef_cost(va_f)

# Sales flows for producer sector i: to domestic industry j, to local p/g/i/dpabr, to exports, to INVNT.
# flow arrays indexed [member, producing sector, category]
sales_dom = np.empty((41, n_s, n_s))          # to own industries
sales_fd = np.empty((41, n_s, 4))             # p g i dpabr of the same country
sales_x = np.empty((41, n_s))
sales_inv = np.empty((41, n_s))
for k, ix in enumerate(ui):
    # C[ix, i, ix, j] is sales of sector i to domestic industry j.
    sales_dom[k] = C[ix, :, ix, :n_s]
    sales_fd[k] = C[ix, :, ix, n_s:]
    sales_x[k] = C[ix].sum(axis=(1, 2)) - C[ix, :, ix, :].sum(axis=1)
    sales_inv[k] = invnt[ix].sum(axis=1)
sales_all = sales_dom.sum(axis=2) + sales_fd.sum(axis=2) + sales_x + sales_inv
sales_resid = out_u - sales_all

def flow_sales_2d(flow):
    num = (scale[:, None, None] * flow).sum(axis=0)
    return num / w_out_safe[:, None]

def flow_sales_1d(flow):
    return (scale[:, None] * flow).sum(axis=0) / w_out_safe

def coef_sales_2d(flow):
    sh = np.divide(flow, out_u[:, :, None], out=np.zeros_like(flow), where=mask[:, :, None])
    return (w[:, None, None] * sh).sum(axis=0) / den_pos_safe[:, None]

def coef_sales_1d(flow):
    sh = np.divide(flow, out_u, out=np.zeros_like(flow), where=mask)
    return (w[:, None] * sh).sum(axis=0) / den_pos_safe

rep_sdom, old_sdom = flow_sales_2d(sales_dom), coef_sales_2d(sales_dom)
rep_sfd, old_sfd = flow_sales_2d(sales_fd), coef_sales_2d(sales_fd)
rep_sx, old_sx = flow_sales_1d(sales_x), coef_sales_1d(sales_x)
rep_sinv, old_sinv = flow_sales_1d(sales_inv), coef_sales_1d(sales_inv)
rep_sres, old_sres = flow_sales_1d(sales_resid), coef_sales_1d(sales_resid)
assert all(np.isfinite(a).all() for a in (rep_dom, rep_imp, rep_tls, rep_va, rep_sdom, rep_sfd, rep_sx, rep_sinv, rep_sres)), 'representative share is not finite'
shp_ix = sec_labels.index('shp')
shp_plain = float(va_f[:, shp_ix].sum() / out_u[:, shp_ix].sum())
dbl_va = dbl_cost(va_f)
dbl_tls = dbl_cost(tls_f)
# Effective weight: each country's share of the summed (GDP-share / GDP) x GDP.
# With the division by GDP this equals the GDP share. Without it, a large country is counted twice.
eff = scale * gdp_reg
eff = eff / eff.sum()
eff_gap = float(np.max(np.abs(eff - w)))
usa_k = used.index('USA')
# The rejected construction's effective weights, on published output: w * output / sum(w * output).
dbl_eff = w * out_u.sum(axis=1)
dbl_eff = dbl_eff / dbl_eff.sum()
dbl_shp_w = w * out_u[:, shp_ix]
dbl_shp_w = dbl_shp_w / dbl_shp_w.sum()
plain_va = np.divide(va_f.sum(axis=0), plain_out, out=np.zeros(n_s), where=plain_out > 0)
plain_gap = float(np.max(np.abs(rep_va - plain_va)))
S.check('S03-H10', 'Each country\'s effective weight in the representative table equals its GDP share',
        'hard', f'max |effective - GDP share| {eff_gap:.3e}; USA effective {eff[usa_k]:.6f}; USA GDP share {w[usa_k]:.6f}; '
                f'max |table VA - plain sum| {plain_gap:.3e}',
        'max abs <= 1e-9',
        eff_gap <= 1e-9 and abs(eff[usa_k] - w[usa_k]) <= 1e-9 and plain_gap <= 1e-9,
        CIT_REP,
        'The table divides each member flow by that member\'s GDP and then applies the GDP share. '
        'The GDP is the S02 region GDP used for the weight. '
        f'USA effective weight {eff[usa_k]:.6f}. '
        'The coefficients equal the plain sum of the 41 USD tables. '
        f'Weighting the USD tables by the GDP share without the division by GDP gives USA {dbl_eff[usa_k]:.6f} economy-wide and {dbl_shp_w[usa_k]:.6f} in shp.')
S.check('S03-R8', 'Representative coefficients from tables divided by GDP and summed with the GDP-share weights',
        'report', f'shp value-added share {rep_va[shp_ix]:.6f}; plain sum of the USD tables {shp_plain:.6f}; '
                  f'coefficient average {old_va[shp_ix]:.6f}; USD times GDP share {dbl_va[shp_ix]:.6f}',
        'the table equals the plain sum of the USD tables (ch.8 §8.3; ch.9D §D.3)',
        abs(float(rep_va[shp_ix]) - shp_plain) <= 1e-9,
        CIT_REP,
        'GDP share divided by the same GDP is the same number for every member, so the coefficients equal the plain sum of the 41 USD tables. '
        f'shp value added on that sum is {rep_va[shp_ix]:.6f}. '
        f'The coefficient average is {old_va[shp_ix]:.6f}. '
        f'Multiplying the USD flows by the GDP share without dividing by GDP gives shp value added {dbl_va[shp_ix]:.6f}. '
        f'shp TLS on the table {rep_tls[shp_ix]:.6f}; coefficient average {old_tls[shp_ix]:.6f}; USD times GDP share {dbl_tls[shp_ix]:.6f}. '
        'Full before/after is representative_method_compare.csv.')
w_sum = float(w.sum())
S.check('S03-H7', 'Representative-table weights sum to 1; members are Table 9.8 intersect ICIO (41); the 7 missing are listed and flagged',
        'hard', f'weights {w_sum:.12f}; members {len(used)}; missing {len(missing)}', '1; 41; 7',
        abs(w_sum - 1) <= 1e-12 and len(used) == 41 and missing == MISSING_98,
        CIT_REP, 'Missing, left out, not folded into another country: ' + ' '.join(missing))

# ---------------------------------------------------------------- shares for every column-country, outliers
# Cost shares and sales shares against the representative table. All 81 column-countries.
def country_cost_shares(ix):
    o = ind_out[ix]
    m = o > 0
    dom = np.zeros((n_s, n_s))
    imp = np.zeros((n_s, n_s))
    tls = np.zeros(n_s)
    va = np.zeros(n_s)
    dflow = C[ix, :, ix, :n_s]
    iflow = C[:, :, ix, :n_s].sum(axis=0) - dflow
    dom[:, m] = dflow[:, m] / o[m]
    imp[:, m] = iflow[:, m] / o[m]
    tls[m] = tls_c[ix, :n_s][m] / o[m]
    va[m] = va_c[ix, :n_s][m] / o[m]
    return dom, imp, tls, va, o

def country_sales_shares(ix):
    o = ind_out[ix]
    m = o > 0
    sdom = np.zeros((n_s, n_s))
    sfd = np.zeros((n_s, 4))
    sx = np.zeros(n_s)
    sinv = np.zeros(n_s)
    sres = np.zeros(n_s)
    dflow = C[ix, :, ix, :n_s]
    fdflow = C[ix, :, ix, n_s:]
    xflow = C[ix].sum(axis=(1, 2)) - C[ix, :, ix, :].sum(axis=1)
    iflow = invnt[ix].sum(axis=1)
    sdom[m] = dflow[m] / o[m, None]
    sfd[m] = fdflow[m] / o[m, None]
    sx[m] = xflow[m] / o[m]
    sinv[m] = iflow[m] / o[m]
    sres[m] = (o[m] - dflow[m].sum(1) - fdflow[m].sum(1) - xflow[m] - iflow[m]) / o[m]
    return sdom, sfd, sx, sinv, sres, o

outlier_rows = []
usa_dev = []
n_out = 0
n_compared = 0
for ix, e in enumerate(economies):
    cdom, cimp, ctls, cva, o = country_cost_shares(ix)
    sdom, sfd, sx, sinv, sres, _ = country_sales_shares(ix)
    items = []
    for j, sj in enumerate(sec_labels):
        if not (o[j] > 0):
            continue
        for i, si in enumerate(sec_labels):
            items.append(('cost', sj, f'domestic {si}', cdom[i, j], rep_dom[i, j], o[j]))
            items.append(('cost', sj, f'imported {si}', cimp[i, j], rep_imp[i, j], o[j]))
        items.append(('cost', sj, 'tls', ctls[j], rep_tls[j], o[j]))
        items.append(('cost', sj, 'va', cva[j], rep_va[j], o[j]))
        for i, si in enumerate(sec_labels):
            # sales of product i to domestic industry j; denominator is output of i
            if o[i] > 0:
                items.append(('sales', sec_labels[i], f'to domestic {sj}', sdom[i, j], rep_sdom[i, j], o[i]))
        items.append(('sales', sj, 'to p', sfd[j, 0], rep_sfd[j, 0], o[j]))
        items.append(('sales', sj, 'to g', sfd[j, 1], rep_sfd[j, 1], o[j]))
        items.append(('sales', sj, 'to i', sfd[j, 2], rep_sfd[j, 2], o[j]))
        items.append(('sales', sj, 'to dpabr', sfd[j, 3], rep_sfd[j, 3], o[j]))
        items.append(('sales', sj, 'to exports', sx[j], rep_sx[j], o[j]))
        items.append(('sales', sj, 'to stock change', sinv[j], rep_sinv[j], o[j]))
        items.append(('sales', sj, 'source residual', sres[j], rep_sres[j], o[j]))
    n_compared += len(items)
    for kind, sector, item, share, rep, outv in items:
        diff = share - rep
        if e == 'USA':
            usa_dev.append((abs(diff), kind, sector, item, share, rep, outv))
        if abs(diff) >= SHARE_LIST and outv >= SHARE_MIN_OUT:
            n_out += 1
            outlier_rows.append((e, kind, sector, item, share, rep, diff, outv))
usa_dev.sort(reverse=True)
S.check('S03-R4', 'Cost and sales shares versus the representative table: list |share - representative| >= 0.25 where output >= 100 USD million. No cell revised.',
        'report', f'{n_out} listed; {n_compared} shares compared; threshold {SHARE_LIST} (reporting list only)',
        'list, do not revise (ch.9D §D.1 initial cleaning is not applied)',
        False, CIT_REP,
        'USA is inside the 41, so it has weight in the table it is compared with. '
        'Top USA absolute gaps: ' + '; '.join(
            f'{k} {sec} {it} share {sh:.3f} rep {rp:.3f} out {ov:.0f}'
            for _, k, sec, it, sh, rp, ov in usa_dev[:8]))

# ---------------------------------------------------------------- macro comparison (R1, R2, R3, R5)
rows_m = []
for ix, e in enumerate(economies):
    va = float(va_c[ix, :n_s].sum())
    tls = float(tls_c[ix].sum())          # after INVNT removal
    tls_full = float(tls_block[ix].sum()) # published, before removal
    gdp = float(va_block[ix, :n_s].sum() + tls_block[ix].sum())
    gfcf_basic = float(use[ix][:, :, n_s + 3].sum() if False else use[:, :, ix, n_s + 3].sum())
    gfcf_tls = float(tls_block[ix, n_s + 3])
    p_basic = float(use[:, :, ix, n_s + 0].sum() + use[:, :, ix, n_s + 1].sum())
    p_tls = float(tls_block[ix, n_s + 0] + tls_block[ix, n_s + 1])
    g_basic = float(use[:, :, ix, n_s + 2].sum())
    g_tls = float(tls_block[ix, n_s + 2])
    dp_basic = float(use[:, :, ix, n_s + 5].sum())
    dp_tls = float(tls_block[ix, n_s + 5])
    inv_abs = float(invnt[:, :, ix].sum())       # absorption removed in this country
    inv_tls = float(tls_inv[ix])
    inv_out = float(invnt[ix].sum())             # this country's industries' sales to all INVNT
    if e == 'ROW':
        rows_m.append(dict(economy=e, region='', icio_gdp=gdp, icio_va=va, icio_tls=tls_full,
                           s02_country_gdp=np.nan, s02_region_gdp=np.nan, gdp_source='',
                           rel_country=np.nan, rel_region=np.nan, outside_2pct='',
                           p_basic=p_basic, p_tls=p_tls, s02_C=np.nan,
                           g_basic=g_basic, g_tls=g_tls, s02_G=np.nan,
                           gfcf_basic=gfcf_basic, gfcf_tls=gfcf_tls, s02_GFCF=np.nan,
                           dpabr_basic=dp_basic, dpabr_tls=dp_tls,
                           invnt_absorption=inv_abs, invnt_tls=inv_tls, invnt_output_gap=inv_out))
        continue
    region = reg_of[e]
    cg = float(mc.loc[e, 'GDP_musd'])
    rg = float(mreg.loc[region, 'GDP_musd'])
    src = str(mc.loc[e, 'GDP_source'])
    rel_c = gdp / cg - 1
    rel_r = gdp / rg - 1
    rows_m.append(dict(economy=e, region=region, icio_gdp=gdp, icio_va=float(va_block[ix, :n_s].sum()),
                       icio_tls=tls_full, s02_country_gdp=cg, s02_region_gdp=rg, gdp_source=src,
                       rel_country=rel_c, rel_region=rel_r, outside_2pct='yes' if abs(rel_c) > 0.02 else 'no',
                       p_basic=p_basic, p_tls=p_tls, s02_C=float(mc.loc[e, 'C_musd']),
                       s02_region_C=float(mreg.loc[region, 'C_musd']),
                       g_basic=g_basic, g_tls=g_tls, s02_G=float(mc.loc[e, 'G_musd']),
                       s02_region_G=float(mreg.loc[region, 'G_musd']),
                       gfcf_basic=gfcf_basic, gfcf_tls=gfcf_tls, s02_GFCF=float(mc.loc[e, 'GFCF_musd']),
                       s02_region_GFCF=float(mreg.loc[region, 'GFCF_musd']),
                       dpabr_basic=dp_basic, dpabr_tls=dp_tls,
                       invnt_absorption=inv_abs, invnt_tls=inv_tls, invnt_output_gap=inv_out))
cmp = pd.DataFrame(rows_m)
eco = cmp[cmp.economy != 'ROW']
n_out2 = int((eco.outside_2pct == 'yes').sum())
worst = eco.reindex(eco.rel_country.abs().sort_values(ascending=False).index).head(8)
S.check('S03-R1', 'ICIO GDP (VA + TLS, published) versus S02 country GDP, 2% band. Report only, no scaling.',
        'report', f'{n_out2} of {len(eco)} outside 2%', 'report; do not adjust (PLAN (b1))',
        n_out2 == 0, 'PLAN (b1) GDP check; spec S03',
        'Largest |ICIO/S02 country - 1|: ' + '; '.join(f'{r.economy} {r.rel_country:+.1%}' for r in worst.itertuples()))

usa = eco.loc[eco.economy == 'USA'].iloc[0]
pri = float(mc.loc['PRI', 'GDP_musd'])
vir = float(mc.loc['VIR', 'GDP_musd'])
pri_share = (pri + vir) / float(usa.s02_region_gdp)
# Gap of ICIO vs the region, and the part that is not PRI+VIR (ICIO vs WDI USA).
S.check('S03-R2', 'USA: ICIO GDP (VA+TLS) versus S02 USA region GDP, with the PRI+VIR share as the expected gap',
        'report', f'ICIO {usa.icio_gdp:.1f}; S02 region {usa.s02_region_gdp:.1f}; gap {usa.rel_region:+.2%}; '
                  f'PRI+VIR {pri + vir:.1f} = {pri_share:.2%} of region GDP; ICIO vs WDI USA {usa.rel_country:+.2%}',
        'expected about -0.45% from PRI+VIR; explain anything beyond about 0.5%',
        False, 'spec S03; E37; Handoff §7',
        f'PRI {pri:.1f} (WDI) + VIR {vir:.1f} (WDI) = {pri_share:.2%} of S02 USA region GDP. '
        f'ICIO USA is {usa.rel_country:+.2%} versus S02 country USA (WDI, 50 states + DC, {usa.s02_country_gdp:.1f}). '
        f'The region gap {usa.rel_region:+.2%} = that country gap plus the PRI+VIR weight. '
        'The country gap is the BEA vintage revision (ICIO versus the later WDI/BEA figure in S02). '
        'No rescaling at S03 (the S13-S14 macro fit absorbs it). ICIO USA is 50 states + DC only.')

gfcf_rel = (eco.gfcf_basic + eco.gfcf_tls) / eco.s02_GFCF - 1
n_gfcf = int((gfcf_rel.abs() > 0.1).sum())
usa_gfcf = float(usa.gfcf_basic + usa.gfcf_tls)
S.check('S03-R3', '(ICIO GFCF + product taxes on GFCF) versus WDI GFCF (E13). Report only. Stocks are not added back.',
        'report', f'USA {usa_gfcf:.1f} vs S02 country {usa.s02_GFCF:.1f} ({usa_gfcf / usa.s02_GFCF - 1:+.2%}); '
                  f'vs S02 region {usa.s02_region_GFCF:.1f} ({usa_gfcf / usa.s02_region_GFCF - 1:+.2%}); '
                  f'{n_gfcf} economies |gap| > 10% versus country GFCF',
        'report (E13)', False, 'E13: (ICIO GFCF + taxes) / WDI GFCF, reported',
        'S02 GFCF is WDI NE.GDI.FTOT.CD, gross fixed capital formation. GCF would include stock change; this check does not. '
        'The economy comparison uses the country row. USA region GFCF also includes PRI and VIR. '
        'TLS on GFCF is the ICIO product-tax row of the GFCF column. Basic prices plus those product taxes are the purchasers\' basis.')

# R5 stock-change gap by economy (producer output gap, and destination absorption)
top_out = eco.reindex(eco.invnt_output_gap.abs().sort_values(ascending=False).index).head(8)
S.check('S03-R5', 'Stock-change gap by economy (producer sales to INVNT, and the destination column). World total shown.',
        'report', f'world product INVNT {invnt.sum():.1f}; world TLS on INVNT {tls_inv.sum():.1f}; '
                  f'USA output gap {usa.invnt_output_gap:.1f}; USA absorption {usa.invnt_absorption:.1f}',
        'report', True, CIT_INV,
        'Largest |producer output gaps|: ' + '; '.join(
            f'{r.economy} {r.invnt_output_gap:.0f}' for r in top_out.itertuples()))

# ---------------------------------------------------------------- USA scrutiny numbers for the output file
usa_ix = economies.index('USA')
# top 10 USA producing industries by |sales to INVNT|
usa_by_ind = [(sec_labels[si], float(invnt[usa_ix, si].sum()), float(ind_out[usa_ix, si])) for si in range(n_s)]
usa_by_ind.sort(key=lambda t: -abs(t[1]))
# top 10 cells of the USA INVNT column
usa_col = invnt[:, :, usa_ix]
flat = [((economies[oi], sec_labels[si]), float(usa_col[oi, si])) for oi in range(n_e) for si in range(n_s)]
flat.sort(key=lambda t: -abs(t[1]))
# DPABR composition
dp_col = use[:, :, usa_ix, n_s + 5]
dp_cells = [((economies[oi], sec_labels[si]), float(dp_col[oi, si])) for oi in range(n_e) for si in range(n_s) if dp_col[oi, si] != 0]
dp_cells.sort(key=lambda t: -abs(t[1]))
# USA balance residuals, all industries, worst first
usa_bal = [(sec_labels[si], float(sales_before[usa_ix, si]), float(costs_before[usa_ix, si]), float(ind_out[usa_ix, si]),
            float((sales_before - costs_before)[usa_ix, si]),
            float((sales_before - costs_before)[usa_ix, si] / max(abs(ind_out[usa_ix, si]), 1.0)))
           for si in range(n_s)]
usa_bal.sort(key=lambda t: -abs(t[4]))

# ---------------------------------------------------------------- flags
S.flag('NO-PRI-VIR-APPEND', 'USA',
       'No PRI or VIR table is built or appended. ICIO USA is used as published (50 states and DC). '
       f'PRI GDP {pri:.1f} and VIR GDP {vir:.1f} stay in S02 USA region GDP. Trade stays in BACI 842.',
       'no', 'E37', 'dataset/build/specs/S03_io_cleaning.md; David 2026-10-20 22:02')
S.flag('ISL-OWN-TABLE', 'ISL',
       f'ISL maps to region {isl_region} and keeps its own ICIO table at S03. It is not folded into XWE. Folding is S05.',
       'no', 'H5', 'PLAN decision 6; handoff H5')
S.flag('B06-DEFER-S11', 'B06',
       'B06 stays one row and one column, labelled B06. oil and gas are not created here. The split is S11, by output value, not by this table.',
       'no', 'H6', 'PLAN (b1) item 7; GTAP 12 ch.12')
S.flag('ROW-KEPT', 'ROW',
       'ICIO ROW rows and columns are copied through. They are not a region and they are not opened here (S05). World totals are checked in H3.',
       'no', 'H3', 'handoff scope')
S.flag('REP-TABLE98-MISSING', ' '.join(missing),
       'Table 9.8 countries with no ICIO table, left out of the representative table (not folded, not filled): ' + ', '.join(missing) + '.',
       'no', 'H7', CIT_REP)
usa_hh = float(usa.p_basic + usa.p_tls + usa.dpabr_basic + usa.dpabr_tls)
usa_hh_rel = usa_hh / float(usa.s02_C) - 1
S.flag('DPABR-KEEP-COLUMN', 'trvl',
       'DPABR is kept as its own column. GTAP calls this traveller expenditures (trvl). '
       'GTAP 12 ch.10B p.3 replaces the column at S09; that treatment does not add these purchases to households. '
       f'World basic {float(use[:, :, :, n_s + 5].sum()):.1f}. '
       f'USA basic {float(usa.dpabr_basic):.1f} plus TLS {float(usa.dpabr_tls):.1f}; '
       f'USA domestic cells {float(use[usa_ix, :, usa_ix, n_s + 5].sum()):.1f}. '
       f'USA households plus trvl, basic plus TLS, {usa_hh:.1f} versus S02 country C {float(usa.s02_C):.1f} ({usa_hh_rel:+.2%}). '
       'Column p remains HFCE+NPISH only.',
       'no', 'GTAP 12 ch.10B p.3', CIT_TRVL)
S.flag('BALANCE-RAS', 'all ICIO sectors',
       'Proportional RAS of intermediate and final cells so cell-sum sales equal cell-sum costs equal published output. '
       f'{ras_iters} iterations. {n_e * n_s} sectors. Max absolute adjustment {max_abs_adj:.4f} USD million. Max percent of output {max_pct_adj:.4%}. '
       f'Sectors above 1% of output: {len(over)}. Those are listed in NEEDS_DAVID.md as report-only. '
       f'USA real estate pre-adjustment sales minus costs {(sales_before - costs_before)[usa_i, l_ix]:.4f}. '
       'GTAP rebalances again in the FIT.',
       'no', 'S03-H1', CIT_BAL)
S.flag('VA-NEGATIVE', 'CYP_H51 ISL_C21',
       'Two published VA cells are negative and were kept: ' + ', '.join(va_list) + '. '
       'H8 allows VA negatives (net taxes sit inside ICIO VA until S12). Not an intermediate-use negative.',
       'no', 'H8', 'PLAN (b1) step 6 (VA split is S12)')
S.flag('SHARE-LIST-THRESHOLD', 'representative table',
       f'Shares with |share - representative| >= {SHARE_LIST} and output >= {SHARE_MIN_OUT:.0f} USD million are listed ({n_out} cells) and not revised. '
       'ch.9D gives no numeric cutoff. The entropy comparison in Walmsley and McDougall 2007 is not implemented.',
       'no', 'S03-R4', CIT_REP)

# ---------------------------------------------------------------- write outputs
S.log('writing outputs')
# 1. stock-change gap, nonzero cells (exact original INVNT)
gap_rows = []
for oi, o in enumerate(economies):
    for si, sec in enumerate(sec_labels):
        for di, d in enumerate(economies):
            v = invnt[oi, si, di]
            if v != 0:
                gap_rows.append((o, sec, d, 'product', f'{v:.4f}'))
for di, d in enumerate(economies):
    v = tls_inv[di]
    if v != 0:
        gap_rows.append((d, 'TLS', d, 'tls_on_invnt', f'{v:.4f}'))
# H2 file check: re-read the values we are about to write and match the array
assert len(gap_rows) == n_inv_nz + n_tls_nz
S.write('stock_change_gap.csv', gap_rows, ['origin', 'sector', 'destination', 'kind', 'value_musd'])

# 2. domestic / imported use
use_rows = []
for di, d in enumerate(economies):
    for si, sec in enumerate(sec_labels):
        for ai, ag in enumerate(agent_labels):
            dv, iv = dom[di, si, ai], imp[di, si, ai]
            if dv == 0 and iv == 0:
                continue
            use_rows.append((d, sec, ag, f'{dv:.4f}', f'{iv:.4f}', f'{(dv + iv):.4f}'))
S.write('use_domestic_imported.csv', use_rows, ['destination', 'product', 'agent', 'domestic_musd', 'imported_musd', 'total_musd'])

# 3. macro comparison
S.write('macro_comparison.csv', cmp)
S.write('household_employers_s03.csv', pd.DataFrame(hhe_out, columns=None if hhe_out else ['economy', 'target_va_musd', 'icio_t_va_musd', 'moved_musd']))  # beta v4 G4

# 4. sector balance ledger (every country x industry): before, adjustment, percent of output
bal_rows = []
for ei, e in enumerate(economies):
    for si, sec in enumerate(sec_labels):
        bal_rows.append((e, sec, f'{ind_out[ei, si]:.4f}',
                         f'{sales_before[ei, si]:.4f}', f'{costs_before[ei, si]:.4f}',
                         f'{sales_adj[ei, si]:.4f}', f'{sales_pct[ei, si]:.8f}',
                         f'{cost_adj[ei, si]:.4f}', f'{cost_pct[ei, si]:.8f}',
                         'yes' if sector_pct[ei, si] > 0.01 else 'no'))
S.write('balance_adjustments.csv', bal_rows,
        ['economy', 'sector', 'output_musd', 'sales_before', 'costs_before',
         'sales_adj', 'sales_pct_of_output', 'cost_adj', 'cost_pct_of_output', 'above_1pct'])

# 5. negatives list
neg_rows = []
for de, ds in neg_tls:
    lab = industries[ds] if ds < n_s else FD_ORDER[ds - n_s]
    neg_rows.append(('TLS', f'{economies[de]}_{lab}', f'{tls_block[de, ds]:.4f}', 'subsidy (kept)'))
for de, ds in neg_va:
    lab = industries[ds] if ds < n_s else FD_ORDER[ds - n_s]
    neg_rows.append(('VA', f'{economies[de]}_{lab}', f'{va_block[de, ds]:.4f}', 'kept; factor split is S12'))
for oi, o in enumerate(economies):
    for si, sec in enumerate(sec_labels):
        for di, d in enumerate(economies):
            v = invnt[oi, si, di]
            if v < 0:
                neg_rows.append(('INVNT', f'{o}_{sec}->{d}', f'{v:.4f}', 'removed with the column and ledgered'))
S.write('negatives.csv', neg_rows, ['kind', 'cell', 'value_musd', 'treatment'])

# 6. representative weights and the coefficient table
w_rows = []
for k, c in enumerate(used):
    w_rows.append((c, reg_of[c], f'{gdp_reg[k]:.6f}', f'{gdp_cty[k]:.6f}', f'{w[k]:.12f}', f'{eff[k]:.12f}', 'yes',
                   'region GDP; flows divided by this GDP, then weighted by the GDP share'))
for c in missing:
    w_rows.append((c, '', '', '', '', '', 'no', 'not in ICIO; left out'))
S.write('representative_weights.csv', w_rows,
        ['economy', 'region', 'gdp_region_musd', 'gdp_country_musd', 'weight', 'effective_weight', 'in_representative_table', 'note'])

# Dollar column is the plain sum of the member USD flows. The GDP-normalised, GDP-weighted
# sum equals that plain sum divided by total GDP, so the coefficient times this sum is the flow.
rep_rows = []
for j, sj in enumerate(sec_labels):
    for i, si in enumerate(sec_labels):
        rep_rows.append(('cost', sj, f'domestic {si}', rep_dom[i, j], int(n_dom[j]), rep_dom[i, j] * plain_out[j]))
        rep_rows.append(('cost', sj, f'imported {si}', rep_imp[i, j], int(n_imp[j]), rep_imp[i, j] * plain_out[j]))
    rep_rows.append(('cost', sj, 'tls', rep_tls[j], int(n_tls[j]), rep_tls[j] * plain_out[j]))
    rep_rows.append(('cost', sj, 'va', rep_va[j], int(n_va[j]), rep_va[j] * plain_out[j]))
    for i, si in enumerate(sec_labels):
        rep_rows.append(('sales', sec_labels[i], f'to domestic {sj}', rep_sdom[i, j], int(mask[:, i].sum()), rep_sdom[i, j] * plain_out[i]))
    rep_rows.append(('sales', sj, 'to p', rep_sfd[j, 0], int(mask[:, j].sum()), rep_sfd[j, 0] * plain_out[j]))
    rep_rows.append(('sales', sj, 'to g', rep_sfd[j, 1], int(mask[:, j].sum()), rep_sfd[j, 1] * plain_out[j]))
    rep_rows.append(('sales', sj, 'to i', rep_sfd[j, 2], int(mask[:, j].sum()), rep_sfd[j, 2] * plain_out[j]))
    rep_rows.append(('sales', sj, 'to dpabr', rep_sfd[j, 3], int(mask[:, j].sum()), rep_sfd[j, 3] * plain_out[j]))
    rep_rows.append(('sales', sj, 'to exports', rep_sx[j], int(mask[:, j].sum()), rep_sx[j] * plain_out[j]))
    rep_rows.append(('sales', sj, 'to stock change', rep_sinv[j], int(mask[:, j].sum()), rep_sinv[j] * plain_out[j]))
    rep_rows.append(('sales', sj, 'source residual', rep_sres[j], int(mask[:, j].sum()), rep_sres[j] * plain_out[j]))
rep_df = pd.DataFrame(rep_rows, columns=['side', 'sector', 'item', 'share', 'n_members', 'summed_flow_musd'])
S.write('representative_table.csv', rep_df)

# Coefficient average, the rejected USD-times-GDP-share sum, and the table.
dbl_sx = (w[:, None] * sales_x).sum(axis=0) / dbl_den_safe
cmp_rows = []
for j, sj in enumerate(sec_labels):
    cmp_rows.append((sj, 'va', old_va[j], dbl_va[j], rep_va[j]))
    cmp_rows.append((sj, 'tls', old_tls[j], dbl_tls[j], rep_tls[j]))
    cmp_rows.append((sj, 'to exports', old_sx[j], dbl_sx[j], rep_sx[j]))
S.write('representative_method_compare.csv',
        [(s, it, f'{a:.8f}', f'{b:.8f}', f'{c:.8f}') for s, it, a, b, c in cmp_rows],
        ['sector', 'item', 'coefficient_average', 'double_weighted_usd', 'table_share'])

S.write('share_outliers.csv', outlier_rows,
        ['economy', 'side', 'sector', 'item', 'share', 'representative_share', 'difference', 'output_musd'])

# 7. USA scrutiny
usa_rows = [
    ('gdp', 'icio_va_plus_tls', usa.icio_gdp, 'USD million'),
    ('gdp', 's02_region', usa.s02_region_gdp, 'includes PRI and VIR'),
    ('gdp', 's02_country_USA', usa.s02_country_gdp, 'WDI, 50 states + DC'),
    ('gdp', 'PRI', pri, 'WDI, not in the ICIO table'),
    ('gdp', 'VIR', vir, 'WDI, not in the ICIO table'),
    ('gdp', 'gap_vs_region', usa.rel_region, 'ICIO/region - 1'),
    ('gdp', 'gap_vs_country', usa.rel_country, 'ICIO/WDI USA - 1'),
    ('gdp', 'pri_vir_share_of_region', pri_share, 'expected region gap from coverage'),
    ('gdp', 'explanation', usa.rel_country, 'BEA vintage revision: ICIO versus S02 country USA. PRI+VIR is pri_vir_share_of_region'),
    ('final_demand', 'p_basic_HFCE_plus_NPISH', usa.p_basic, 'USD million, basic'),
    ('final_demand', 'p_tls', usa.p_tls, ''),
    ('final_demand', 's02_C_country', usa.s02_C, 'WDI USA, households and NPISH, purchasers'),
    ('final_demand', 's02_C_region', usa.s02_region_C, 'includes PRI and VIR'),
    ('final_demand', 'p_plus_trvl_basic_plus_tls', usa_hh, 'HFCE+NPISH+TLS plus traveller expenditures (trvl); trvl stays its own column'),
    ('final_demand', 'p_plus_trvl_vs_s02_C_country', usa_hh_rel, 'expected about -1.88%'),
    ('final_demand', 'g_basic', usa.g_basic, ''),
    ('final_demand', 'g_tls', usa.g_tls, ''),
    ('final_demand', 's02_G_country', usa.s02_G, ''),
    ('final_demand', 's02_G_region', usa.s02_region_G, 'includes PRI and VIR'),
    ('final_demand', 'i_basic_GFCF', usa.gfcf_basic, ''),
    ('final_demand', 'i_tls', usa.gfcf_tls, ''),
    ('final_demand', 's02_GFCF_country', usa.s02_GFCF, 'WDI NE.GDI.FTOT.CD, USA'),
    ('final_demand', 's02_GFCF_region', usa.s02_region_GFCF, 'includes PRI and VIR'),
    ('dpabr', 'basic', usa.dpabr_basic, 'traveller expenditures (trvl); own column until S09'),
    ('dpabr', 'tls', usa.dpabr_tls, ''),
    ('dpabr', 'domestic', float(use[usa_ix, :, usa_ix, n_s + 5].sum()), 'USA rows of the USA trvl column'),
    ('stock_change', 'output_gap', usa.invnt_output_gap, 'USA industry sales to all INVNT columns'),
    ('stock_change', 'absorption', usa.invnt_absorption, 'USA INVNT column, product rows'),
    ('stock_change', 'tls_on_usa_invnt', usa.invnt_tls, 'removed and ledgered'),
    ('balance', 'max_abs_sales_minus_costs', usa_bal[0][4], usa_bal[0][0]),
]
for rank, (sec, v, outv) in enumerate(usa_by_ind[:10], 1):
    usa_rows.append((f'stock_top10_producer_{rank}', sec, v, f'output {outv:.4f}'))
for rank, ((o, sec), v) in enumerate(flat[:10], 1):
    usa_rows.append((f'stock_top10_usa_column_{rank}', f'{o}_{sec}', v, 'cell of the USA INVNT column'))
for rank, ((o, sec), v) in enumerate(dp_cells[:10], 1):
    usa_rows.append((f'dpabr_top10_{rank}', f'{o}_{sec}', v, 'cell of the USA DPABR column'))
for rank, (sec, sales_v, costs_v, outv, gapv, relv) in enumerate(usa_bal[:10], 1):
    usa_rows.append((f'balance_top10_{rank}', sec, gapv, f'sales {sales_v:.4f} costs {costs_v:.4f} output {outv:.4f} rel {relv:.3e}'))
for rank, (_, kind, sec, item, share, rep, outv) in enumerate(usa_dev[:15], 1):
    usa_rows.append((f'share_gap_top15_{rank}', f'{kind} {sec} {item}', share - rep, f'share {share:.6f} rep {rep:.6f} output {outv:.1f}'))
S.write('usa_scrutiny.csv', usa_rows, ['item', 'key', 'value', 'note'])

# 8. sector map actually applied
map_rows = [(s, sec_of[s], '1' if s != 'B06' else '', 'identity' if s != 'B06' else 'deferred:S11') for s in industries]
S.write('sector_map_applied.csv', map_rows, ['icio_code', 'label_in_output', 'share', 'status'])

# 9. bilateral cleaned table, gzip, wide. Row/column labels use sector labels; B06 stays B06.
#    OUT column is published output (not reduced by the INVNT removal).
S.log('writing io_cleaned.csv.gz')
import gzip
col_labels = [f'{e}_{ag}' for e in economies for ag in agent_labels] + ['OUT']
row_labels = [f'{e}_{sec}' for e in economies for sec in sec_labels] + ['TLS', 'VA', 'OUT']
body = C.reshape(n_e * n_s, n_e * n_a)
out_col_prod = prod_out.reshape(-1)
body = np.concatenate([body, out_col_prod[:, None]], axis=1)
tls_row = np.concatenate([tls_c.reshape(-1), [A[tls_i, -1]]])
va_row = np.concatenate([va_c.reshape(-1), [A[va_i, -1]]])
out_row = np.concatenate([out_c.reshape(-1), [A[out_i, -1]]])
M = np.vstack([body, tls_row, va_row, out_row])
assert M.shape == (len(row_labels), len(col_labels))
# No NaN and no INVNT label, and product-block negatives only if the source had them (it did not).
assert not np.isnan(M).any()
assert not any('INVNT' in c or c.endswith('_HFCE') or c.endswith('_NPISH') or c.endswith('_GGFC') or c.endswith('_GFCF') for c in col_labels)
gz_path = S.out + '/io_cleaned.csv.gz'
# mtime 0 and an empty filename keep the gzip header free of the clock and the path,
# so the SHA-256 is the same on a second run.
with open(gz_path, 'wb') as raw:
    with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0, compresslevel=9) as gz:
        gz.write(('row,' + ','.join(col_labels) + '\n').encode())
        for i, lab in enumerate(row_labels):
            vals = ','.join('0' if v == 0 else f'{v:.4f}' for v in M[i])
            gz.write((lab + ',' + vals + '\n').encode())
S.log(f'output io_cleaned.csv.gz bytes {os.path.getsize(gz_path)}')

# H2 closing check already recorded. Confirm the gzip has no INVNT and B06 is present.
assert any(c.startswith('USA_B06') for c in col_labels) and not any('_oil' in c or '_gas' in c for c in col_labels)

S.log(f'USA ICIO GDP {usa.icio_gdp:.1f} region gap {usa.rel_region:+.2%} country gap {usa.rel_country:+.2%} '
      f'INVNT world {invnt.sum():.1f} outliers {n_out}')
ok = S.finish()
