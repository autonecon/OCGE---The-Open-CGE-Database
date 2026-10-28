"""S06 agricultural production targeting (GTAP 12 ch.9A). Report only.

The rule is the one row in config/s06/apt_rule.csv. This script does not choose it.
David (2026-10-21T04:50+07:00) set report_only: compute the ch.9A target, change no cell.
gtap9a_target is not built at S06.
"""
import csv
import gzip
import io
import math
import os
import shutil
import sys
import unicodedata
import zipfile

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/lib')
from stagekit import BASE_YEAR, BUILD, ROOT, STAGES, Stage, sha256

S = Stage('S06', 'apt')
I = S.inp
S01 = S.upstream(STAGES + '/S01_sets_registry')
S02 = S.upstream(STAGES + '/S02_macro')
S03 = S.upstream(STAGES + '/S03_io_cleaning')
S04 = S.upstream(STAGES + '/S04_disagg_gov')
S05 = S.upstream(STAGES + '/S05_composite')

CIT_A1 = ('GTAP 12 ch.9A §A.1 p.2 ("The GTAP 12 Data Base targets agricultural production data '
          'from Food and Agriculture Organization (FAO) of the United Nations 2022 for all primary '
          'regions"; "The APT procedure is not applied to the composite regions")')
CIT_A2 = ('GTAP 12 ch.9A §A.2 p.3 ("we deem a soft inconsistency to exist if the production target '
          'is less than the export target plus one quarter of the initial level of domestic absorption"; '
          '"it is the production targets, not the export targets, that must give way")')
CIT_ORDER = ('GTAP 12 ch.8 §8.3 p.3 ("Second, agricultural production targets are applied to the '
             'majority of I-O tables before the main data construction phase") and p.4 ("Finally" the composite table)')
CIT_B6 = ('GTAP 12 ch.17B §B.6 p.6 ("The final run then restarts the construction workflow using the '
          'APT-adjusted regional tables as the authoritative inputs: it re-executes upstream steps as needed")')
CIT_CH7 = ('GTAP 12 ch.7 §7.2 p.3 ("scaled-up by the ratio of gross domestic product (GDP) calculated '
           'from the I-O tables to external GDP data in current US dollars")')

IO_S05_SHA = 'e83facbfd23c2cb0f535cb52be976055da3179a44256c7e1c401020fc8b3a410'  # S05 beta v4 (G4 hfce_to_pq ZAF household employers, P33 KEN donor size guard), 2026-10-26
# ISO 3166-1 numeric codes, which are the UN M49 codes for these areas.
# CHN is 156 (China, mainland), not 159 (China, including HKG, MAC and TWN). Handoff H4.
ANCHOR_M49 = {
    'CHN': 156, 'HKG': 344, 'MAC': 446, 'TWN': 158, 'USA': 840, 'GBR': 826,
    'KOR': 410, 'PRK': 408, 'COD': 180, 'NLD': 528, 'LAO': 418, 'IRN': 364,
    'ISL': 352, 'PRI': 630, 'ARE': 784, 'MMR': 104, 'STP': 678, 'VEN': 862,
}
# FAO area names whose S01 name is shorter or punctuated differently.
# Concordance only. China (M49 159) is skipped below and is not in this table.
ALIAS_FAO_NAME = {
    'China; mainland': 'CHN',
    'China; Taiwan Province of': 'TWN',
    'Bosnia and Herzegovina': 'BIH',
    'Central African Republic': 'CAF',
    'Dominican Republic': 'DOM',
    'Cook Islands': 'COK',
    'Solomon Islands': 'SLB',
    'Marshall Islands': 'MHL',
    "Democratic People's Republic of Korea": 'PRK',
    'Democratic Republic of the Congo': 'COD',
    'Iran (Islamic Republic of)': 'IRN',
    "Lao People's Democratic Republic": 'LAO',
    'Micronesia (Federated States of)': 'FSM',
    'Netherlands (Kingdom of the)': 'NLD',
    'Republic of Korea': 'KOR',
    'Republic of Moldova': 'MDA',
    'Syrian Arab Republic': 'SYR',
    'United Kingdom of Great Britain and Northern Ireland': 'GBR',
    'United Republic of Tanzania': 'TZA',
    'United States of America': 'USA',
    'Venezuela (Bolivarian Republic of)': 'VEN',
}
# GTAP 12 ch.9A Table 9.3 p.7 (2023, USD million): domestic absorption, exports,
# initial production target, adjusted production target. Twenty rows.
TABLE_93 = (
    ('aus', 'ocr', 13110, 791, 17, 4068),
    ('nld', 'ocr', 3070, 9986, 1196, 10753),
    ('irq', 'vf', 33407, 120, 1735, 8472),
    ('pak', 'wol', 9682, 1, 35, 2422),
    ('can', 'ocr', 4250, 1386, 183, 2449),
    ('nld', 'vf', 1316, 14566, 7273, 14895),
    ('irq', 'gro', 8046, 205, 247, 2217),
    ('ind', 'ocr', 103188, 4211, 19973, 30008),
    ('irq', 'wht', 19534, 22, 1511, 4905),
    ('ken', 'osd', 6285, 7, 115, 1578),
    ('isr', 'ocr', 1001, 120, 0, 370),
    ('nld', 'osd', 156, 679, 4, 718),
    ('col', 'ocr', 3856, 5093, 2252, 6057),
    ('sau', 'wht', 13236, 4, 770, 3313),
    ('bra', 'wol', 4567, 9, 51, 1151),
    ('are', 'ocr', 11, 471, 0, 474),
    ('are', 'vf', 260, 1976, 356, 2041),
    ('irq', 'pdr', 2614, 0, 8, 654),
    ('irq', 'ocr', 5457, 8, 170, 1372),
    ('hti', 'vf', 3297, 1, 37, 825),
)
F5_EXPECT = ('ARE', 'COD', 'MMR', 'STP', 'TWN')
CHOICE_KEYS = (
    'fao_series', 'fao_year', 'export_target', 'gdp_scale', 'domestic_absorption', 'soft_fraction',
)
TAIL = ('X', 'stock_gap', 'grev_gap', 'OUT')
KEEP_ROWS = ('dom_crp', 'imp_crp', 'TLS', 'VA', 'OUT')
FAO_INNER = 'Value_of_Production_E_All_Data_(Normalized).csv'
FAO_AREAS = 'Value_of_Production_E_AreaCodes.csv'


def blank(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ''
    s = str(v).strip()
    return '' if s.lower() == 'nan' else s


def cell(v, nd=10):
    if v is None or v == '':
        return ''
    if isinstance(v, str):
        return v
    x = float(v)
    if math.isnan(x):
        return ''
    s = f'{x:.{nd}f}'
    if '.' in s:
        s = s.rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s


def norm_name(s):
    s = unicodedata.normalize('NFC', s).lower().replace(';', ' ').replace(',', ' ')
    s = ''.join(ch if ch.isalnum() or ch.isspace() else ' ' for ch in s)
    return ' '.join(s.split())


def parse_m49(raw):
    digits = ''.join(ch for ch in str(raw) if ch.isdigit())
    if not digits:
        raise ValueError(f'M49 code has no digits: {raw!r}')
    return int(digits)


def percentile(xs, p):
    xs = sorted(float(x) for x in xs)
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * p / 100.0
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def gtap_adjust(fao, exports, domestic_absorption, frac):
    """ch.9A §A.2 p.3, in the max form written in the S06 handoff.

    exports and domestic_absorption are in the same units as fao.
    Hard: the export target exceeds the production target.
    Soft: the production target is below exports + frac * domestic absorption.
    Adjusted target = max(FAO, exports + frac * domestic absorption).
    """
    threshold = exports + frac * domestic_absorption
    if fao < exports:
        kind = 'hard'
    elif fao < threshold:
        kind = 'soft'
    else:
        kind = 'none'
    return kind, threshold, max(fao, threshold)


def arith_primary(out, x, m, gdp, s02, fao, frac):
    s = s02 / gdp
    da = s * (out - x)
    da_alt = s * (out - x + m)
    if fao is None:
        thr = s * (x + frac * (out - x))
        return s, da, da_alt, thr, None, None, 'no FAO'
    kind, thr, tgt = gtap_adjust(fao, s * x, s * (out - x), frac)
    implied = (tgt / (s * out) - 1.0) * 100.0
    return s, da, da_alt, thr, tgt, implied, kind


def arith_second(out, x, m, gdp, s02, fao, frac):
    """Same quantities as arith_primary, written out again for H6."""
    scale = s02 / gdp
    domestic = scale * (out - x)
    domestic_alt = scale * ((out - x) + m)
    threshold = scale * x + frac * scale * (out - x)
    if fao is None:
        return scale, domestic, domestic_alt, threshold, None
    target = max(fao, threshold)
    return scale, domestic, domestic_alt, threshold, target


# ---------------------------------------------------------------- config
rule_path = I(BUILD + '/config/s06/apt_rule.csv', 'S06 APT rule decision')
choice_path = I(BUILD + '/config/s06/apt_choices.csv', 'S06 APT choice rows')
usa_path = BUILD + '/config/s06/usa_crosscheck.csv'
if os.path.exists(usa_path):
    I(usa_path, 'S06 USA cross-check constants (report only)')

rule_df = pd.read_csv(rule_path, dtype=str).fillna('')
choice_df = pd.read_csv(choice_path, dtype=str).fillna('')
rule_row = {k: str(rule_df.iloc[0][k]).strip() for k in rule_df.columns} if len(rule_df) == 1 else {}
RULE = rule_row.get('rule', '')
choices = {}
if list(choice_df.columns) == ['choice', 'value', 'decided_by', 'decided_at', 'basis']:
    choices = {str(r['choice']).strip(): r for _, r in choice_df.iterrows()}

h2_problems = []
if len(rule_df) != 1:
    h2_problems.append(f'apt_rule.csv rows {len(rule_df)}')
if RULE not in ('report_only', 'gtap9a_target'):
    h2_problems.append(f'rule {RULE!r}')
if not rule_row.get('decided_by', '').strip():
    h2_problems.append('decided_by empty')
if set(choices) != set(CHOICE_KEYS):
    h2_problems.append(f'choices {sorted(choices)}')
for key in CHOICE_KEYS:
    row = choices.get(key)
    if row is None:
        continue
    if not str(row['decided_by']).strip() or not str(row['decided_at']).strip():
        h2_problems.append(f'{key} missing decided_by or decided_at')
FRAC = None
if 'soft_fraction' in choices:
    try:
        FRAC = float(str(choices['soft_fraction']['value']).strip())
    except ValueError:
        h2_problems.append('soft_fraction is not a number')
fao_text = str(choices.get('fao_series', {}).get('value', '')) if choices else ''
year_text = str(choices.get('fao_year', {}).get('value', '')) if choices else ''
if '57' not in fao_text or '2051' not in fao_text or '1000' not in fao_text:
    h2_problems.append('fao_series does not state element 57, item 2051, divide by 1000')
if str(BASE_YEAR) not in year_text or '1998' not in year_text:
    h2_problems.append('fao_year does not state the base year and 1998')
TOO_OLD = 1998

if RULE == 'gtap9a_target':
    S.check('S06-H2',
            'apt_rule.csv is one decided row and apt_choices.csv has the six choices; gtap9a_target is not built',
            'hard', RULE, 'report_only', False, 'decision 10; E4; C18',
            "not built at S06; see ISSUES 'S06 GTAP-literal APT'")
    S.finish()

# ---------------------------------------------------------------- registry
regions = pd.read_csv(I(S01 + '/output/regions.csv', 'S01 regions'), dtype=str).fillna('')
sectors = pd.read_csv(I(S01 + '/output/sectors.csv', 'S01 sectors'), dtype=str).fillna('')
crm = pd.read_csv(I(S01 + '/output/country_region_map.csv', 'S01 country-region map'), dtype=str).fillna('')
macro_reg = pd.read_csv(I(S02 + '/output/macro_regions.csv', 'S02 region macro'))
macro_cty = pd.read_csv(I(S02 + '/output/macro_country.csv', 'S02 country macro'))
stock_path = I(S03 + '/output/stock_change_gap.csv', 'S03 stock-change gap (ISL TLS on stock change)')
io_s04 = I(S04 + '/output/io_s04.csv.gz', 'S04 I-O table (ISL)')
io_s05 = I(S05 + '/output/io_s05.csv.gz', 'S05 I-O table')
weights_path = I(S05 + '/output/donor_weights.csv', 'S05 donor weights')
fao_zip = I(ROOT + '/data/faostat_qv/Value_of_Production_E_All_Data_Normalized.zip',
            'FAOSTAT QV element 57')

primaries = [r['region'] for _, r in regions.iterrows()
             if r['type'] == 'single' and r['icio_measured'] == 'yes']
constructed = [r['region'] for _, r in regions.iterrows()
               if r['type'] == 'composite' or (r['type'] == 'single' and r['icio_measured'] == 'no')]
region_order = [r for r in regions['region'].tolist() if r in set(primaries) | set(constructed)]
if len(primaries) != 79 or len(constructed) != 88 or len(region_order) != 167:
    raise SystemExit(f'expected 79 primaries, 88 constructed, 167 regions; '
                     f'got {len(primaries)}, {len(constructed)}, {len(region_order)}')
if 'ISL' in primaries or 'ROW' in primaries or 'ISL' in constructed:
    raise SystemExit('ISL and ROW are not S01 regions')

a01 = sectors.loc[sectors['icio_code'] == 'A01', 'sector'].tolist()
s02_region = dict(zip(macro_reg['region'], macro_reg['GDP_musd'].astype(float)))
s02_country = dict(zip(macro_cty['code'], macro_cty['GDP_musd'].astype(float)))
weights = pd.read_csv(weights_path, dtype=str).fillna('')
members = {}
for _, r in weights.iterrows():
    members.setdefault(r['region'], []).append(r)

# ---------------------------------------------------------------- FAO area map
by_name = {}
for _, r in crm.iterrows():
    if r['code'] and r['name']:
        by_name.setdefault(norm_name(r['name']), set()).add(r['code'])

m49_to_iso = {}
iso_to_m49 = {}
alias_used = []
with zipfile.ZipFile(fao_zip) as zf:
    area_text = zf.read(FAO_AREAS).decode('utf-8')
for row in csv.DictReader(io.StringIO(area_text)):
    area_code = int(row['Area Code'])
    m49 = parse_m49(row['M49 Code'])
    name = row['Area'].strip()
    if area_code >= 5000 or m49 == 159:
        continue
    iso = ALIAS_FAO_NAME.get(name)
    if iso is not None:
        alias_used.append(f'{name} -> {iso} (M49 {m49})')
    else:
        hits = by_name.get(norm_name(name), set())
        if len(hits) == 1:
            iso = next(iter(hits))
        elif len(hits) > 1:
            raise SystemExit(f'FAO area {name!r} matches more than one S01 code: {sorted(hits)}')
    if iso is None:
        continue
    if iso in iso_to_m49 and iso_to_m49[iso] != m49:
        raise SystemExit(f'{iso} mapped to both M49 {iso_to_m49[iso]} and {m49}')
    m49_to_iso[m49] = iso
    iso_to_m49[iso] = m49

anchor_bad = [f'{code} got {iso_to_m49.get(code)} want {m49}'
              for code, m49 in ANCHOR_M49.items() if iso_to_m49.get(code) != m49]
if anchor_bad:
    raise SystemExit('M49 anchors failed: ' + '; '.join(anchor_bad))
if m49_to_iso.get(159) or iso_to_m49.get('CHN') == 159:
    raise SystemExit('M49 159 (China, including HKG, MAC and TWN) must not map to CHN')

# ---------------------------------------------------------------- FAO values
# (m49, item) -> {year: value in thousand USD}
fao = {}
fao_dup = []
unit_57 = ''
seen_2051 = False
n_kept = 0
with zipfile.ZipFile(fao_zip) as zf:
    with zf.open(FAO_INNER) as raw:
        text = io.TextIOWrapper(raw, encoding='latin1', newline='')
        reader = csv.reader(text)
        header = next(reader)
        col = {name: i for i, name in enumerate(header)}
        need = ['Area Code (M49)', 'Item Code', 'Element Code', 'Year', 'Unit', 'Value']
        missing_cols = [c for c in need if c not in col]
        if missing_cols:
            raise SystemExit('FAO CSV missing columns: ' + ' '.join(missing_cols))
        i_m49, i_item, i_el, i_year, i_unit, i_val = (col[c] for c in need)
        for n, rec in enumerate(reader, 1):
            if n % 2000000 == 0:
                S.log(f'FAO rows read {n}; kept {n_kept}')
            if len(rec) <= i_val:
                continue
            if rec[i_el] != '57':
                continue
            if rec[i_item] not in ('2051', '2041', '2044'):
                continue
            year = int(rec[i_year])
            if year > BASE_YEAR:
                continue
            if not unit_57:
                unit_57 = rec[i_unit]
            if rec[i_item] == '2051':
                seen_2051 = True
            if rec[i_val] == '':
                continue
            m49 = parse_m49(rec[i_m49])
            key = (m49, rec[i_item])
            bucket = fao.setdefault(key, {})
            val = float(rec[i_val])
            if year in bucket and bucket[year] != val:
                fao_dup.append(f'{m49} item {rec[i_item]} {year}')
            bucket[year] = val
            n_kept += 1
S.log(f'FAO element 57 items 2051/2041/2044, years <= {BASE_YEAR}: {n_kept} values; unit {unit_57!r}')


def series_for(iso, item):
    m49 = iso_to_m49.get(iso)
    if m49 is None:
        return None
    return fao.get((m49, item))


def select_year(year_map):
    """Return (year or None, status) under the fao_year row.

    status is 'ok' (base year), 'old' (latest earlier year, not 1998),
    '1998', or 'missing'.
    """
    if not year_map:
        return None, 'missing'
    years = [y for y in year_map if y <= BASE_YEAR]
    if not years:
        return None, 'missing'
    year = max(years)
    if year == TOO_OLD:
        return None, '1998'
    if year == BASE_YEAR:
        return year, 'ok'
    return year, 'old'


def fao_musd(iso, item, year):
    year_map = series_for(iso, item)
    if year_map is None or year not in year_map:
        return None
    return year_map[year] / 1000.0


def fao_status(iso):
    year, status = select_year(series_for(iso, '2051'))
    if status in ('missing', '1998'):
        return None, None, status
    return year, fao_musd(iso, '2051', year), status


# ---------------------------------------------------------------- io_s05, two paths
S.log(f'reading {io_s05}')
wide = {code: {} for code in primaries}
with gzip.open(io_s05, 'rt') as fh:
    header05 = fh.readline().rstrip('\n').split(',')
    for line in fh:
        region, _, rest = line.partition(',')
        if region not in wide:
            continue
        row = rest.split(',', 1)[0]
        if row in KEEP_ROWS:
            wide[region][row] = line.rstrip('\n').split(',')
agents = [c for c in header05 if c not in ('region', 'row') and c not in TAIL]
idx05 = {c: i for i, c in enumerate(header05)}
if 'crp' not in agents or 'dom_crp' not in KEEP_ROWS:
    raise SystemExit('io_s05 has no crp column')


def metrics_wide(code):
    rows = wide[code]
    if set(KEEP_ROWS) - set(rows):
        raise SystemExit(f'{code} is missing a crp, TLS, VA or OUT row in io_s05')

    def f(row, col):
        return float(rows[row][idx05[col]] or 0.0)

    out = f('dom_crp', 'OUT')
    x = f('dom_crp', 'X')
    m = sum(f('imp_crp', a) for a in agents)
    gdp = sum(f('VA', a) for a in agents) + sum(f('TLS', a) for a in agents) + f('TLS', 'stock_gap')
    out_col = f('OUT', 'crp')
    return out, x, m, gdp, out_col


S.log('second path: pandas group-by of io_s05')
df05 = pd.read_csv(io_s05, dtype=str)
sub = df05[df05['region'].isin(primaries) & df05['row'].isin(['dom_crp', 'imp_crp', 'TLS', 'VA', 'OUT'])]
long = sub.melt(id_vars=['region', 'row'], var_name='col', value_name='v')
long['v'] = pd.to_numeric(long['v'], errors='coerce').fillna(0.0)
grouped = long.groupby(['region', 'row', 'col'], sort=False)['v'].sum()


def metrics_long(code):
    def g(row, col):
        return float(grouped[(code, row, col)])

    out = g('dom_crp', 'OUT')
    x = g('dom_crp', 'X')
    m = sum(g('imp_crp', a) for a in agents)
    gdp = sum(g('VA', a) for a in agents) + sum(g('TLS', a) for a in agents) + g('TLS', 'stock_gap')
    return out, x, m, gdp


# ---------------------------------------------------------------- ISL from io_s04, two paths
S.log(f'reading {io_s04} for ISL')
with gzip.open(io_s04, 'rt') as fh:
    header04 = fh.readline().rstrip('\n').split(',')
    row_labels = []
    data = []
    for line in fh:
        parts = line.rstrip('\n').split(',')
        row_labels.append(parts[0])
        data.append([0.0 if x in ('0', '') else float(x) for x in parts[1:]])
M = np.asarray(data, dtype=np.float64)
col_labels = header04[1:]
del data
assert col_labels[-1] == 'OUT' and row_labels[-3:] == ['TLS', 'VA', 'OUT']
economies = []
for lab in col_labels[:-1]:
    eco = lab.split('_', 1)[0]
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
n_a = 54
assert 'crp' in sec and 'ISL' in economies
assert M.shape == (n_e * n_s + 3, n_e * n_a + 1), M.shape
eco_index = {e: i for i, e in enumerate(economies)}
si = sec.index('crp')
ei = eco_index['ISL']
P = M[:n_e * n_s, :n_e * n_a].reshape(n_e, n_s, n_e, n_a)
TLS = M[n_e * n_s, :n_e * n_a].reshape(n_e, n_a)
VA = M[n_e * n_s + 1, :n_e * n_a].reshape(n_e, n_a)
OUTC = M[:n_e * n_s, -1].reshape(n_e, n_s)
del M

isl_tls_inv = 0.0
with open(stock_path, newline='') as fh:
    for row in csv.DictReader(fh):
        if row['kind'] == 'tls_on_invnt' and row['destination'] == 'ISL':
            isl_tls_inv += float(row['value_musd'])
S.log(f'ISL tls_on_invnt {isl_tls_inv:.4f} USD million (S03, S05-H7 definition)')


def isl_numpy():
    dom = P[ei, si, ei, :]
    imp = P[:, si, ei, :].sum(axis=0) - dom
    exports = float(P[ei, si].sum() - dom.sum())
    out = float(OUTC[ei, si])
    m = float(imp.sum())
    gdp = float(VA[ei].sum() + TLS[ei].sum() + isl_tls_inv)
    return out, exports, m, gdp


def isl_groupby():
    """Long-format group-by of ISL's crp row and of the import block. Not the numpy sum."""
    imp_block = np.ascontiguousarray(P[:, si, ei, :]).ravel()
    origins = np.repeat(np.arange(n_e), n_a)
    agent = np.tile(np.arange(n_a), n_e)
    imp_df = pd.DataFrame({'origin': origins, 'agent': agent, 'v': imp_block})
    by_agent = (imp_df.groupby('agent', sort=True)['v'].sum()
                .reindex(range(n_a), fill_value=0.0).to_numpy(dtype=np.float64))
    dom = np.array(P[ei, si, ei, :], copy=True)
    m = float((by_agent - dom).sum())
    x_block = np.ascontiguousarray(P[ei, si, :, :]).ravel()
    dest = np.repeat(np.arange(n_e), n_a)
    xdf = pd.DataFrame({'dest': dest, 'v': x_block})
    exports = float(xdf.loc[xdf['dest'] != ei, 'v'].sum())
    out = float(pd.Series([OUTC[ei, si]]).sum())
    gdp = float(pd.Series(VA[ei]).sum() + pd.Series(TLS[ei]).sum() + isl_tls_inv)
    return out, exports, m, gdp


isl_a = isl_numpy()
isl_b = isl_groupby()

# ---------------------------------------------------------------- primary records
primary_order = list(primaries) + ['ISL']
records = []
path_gap = []
for code in primaries:
    out, x, m, gdp, out_col = metrics_wide(code)
    out2, x2, m2, gdp2 = metrics_long(code)
    if abs(out - out_col) > 1e-6:
        raise SystemExit(f'{code} dom_crp OUT {out} differs from OUT row crp {out_col}')
    year, gpv, status = fao_status(code)
    s02 = s02_region[code]
    s, da, da_alt, thr, tgt, implied, kind = arith_primary(out, x, m, gdp, s02, gpv, FRAC)
    s2, da2, da_alt2, thr2, tgt2 = arith_second(out2, x2, m2, gdp2, s02, gpv, FRAC)
    for label, a, b in (('s', s, s2), ('X', x, x2), ('DA', da, da2),
                        ('threshold', thr, thr2), ('target', tgt, tgt2)):
        if a is None and b is None:
            continue
        path_gap.append((code, label, abs(float(a) - float(b))))
    crops = fao_musd(code, '2041', year) if year else None
    live = fao_musd(code, '2044', year) if year else None
    records.append(dict(
        region=code, table='io_s05', out=out, x=x, m=m, gdp=gdp, s02=s02,
        s=s, da=da, da_alt=da_alt, thr=thr, tgt=tgt, implied=implied, kind=kind,
        year=year, gpv=gpv, status=status, crops=crops, live=live,
    ))

out, x, m, gdp = isl_a
year, gpv, status = fao_status('ISL')
s02 = s02_country['ISL']
s, da, da_alt, thr, tgt, implied, kind = arith_primary(out, x, m, gdp, s02, gpv, FRAC)
s2, da2, da_alt2, thr2, tgt2 = arith_second(*isl_b, s02, gpv, FRAC)
for label, a, b in (('s', s, s2), ('X', x, isl_b[1]), ('DA', da, da2),
                    ('threshold', thr, thr2), ('target', tgt, tgt2)):
    if a is None and b is None:
        continue
    path_gap.append(('ISL', label, abs(float(a) - float(b))))
crops = fao_musd('ISL', '2041', year) if year else None
live = fao_musd('ISL', '2044', year) if year else None
records.append(dict(
    region='ISL', table='io_s04', out=out, x=x, m=m, gdp=gdp, s02=s02,
    s=s, da=da, da_alt=da_alt, thr=thr, tgt=tgt, implied=implied, kind=kind,
    year=year, gpv=gpv, status=status, crops=crops, live=live,
))
by_region = {r['region']: r for r in records}

# ---------------------------------------------------------------- ratio file, all 167 + ISL
def member_fao(code):
    y, g, st = fao_status(code)
    return y, g, st


ratio_rows = []
old_year_flags = []  # (code, year) wherever an earlier year is used
for rec in records:
    if rec['status'] == 'old':
        old_year_flags.append((rec['region'], rec['year']))
    ratio = (rec['out'] / rec['gpv']) if rec['gpv'] else None
    cshare = (rec['crops'] / rec['gpv']) if rec['gpv'] and rec['crops'] is not None else None
    lshare = (rec['live'] / rec['gpv']) if rec['gpv'] and rec['live'] is not None else None
    missing = rec['region'] if rec['gpv'] is None else ''
    ratio_rows.append(dict(
        region=rec['region'], kind='primary', crp_OUT=rec['out'], fao_sum=rec['gpv'],
        members_missing_fao=missing, icio_over_fao=ratio,
        crops_share=cshare, livestock_share=lshare,
    ))

constructed_detail = []
for region in constructed:
    rows = members.get(region, [])
    fao_sum = 0.0
    crops_sum = 0.0
    live_sum = 0.0
    have = 0
    missing_codes = []
    gdp_have = 0.0
    gdp_all = 0.0
    for row in rows:
        code = row['code']
        gdp_m = float(row['s02_gdp']) if row['s02_gdp'] else 0.0
        gdp_all += gdp_m
        y, g, st = member_fao(code)
        if st == 'old':
            old_year_flags.append((code, y))
        if g is None:
            missing_codes.append(code)
            continue
        have += 1
        fao_sum += g
        gdp_have += gdp_m
        c = fao_musd(code, '2041', y)
        lv = fao_musd(code, '2044', y)
        if c is not None:
            crops_sum += c
        if lv is not None:
            live_sum += lv
    # crp output of the constructed table, from the same wide read if present,
    # else one more pass is unnecessary: io_s05 was not stored for constructed.
    constructed_detail.append(dict(
        region=region, fao_sum=fao_sum if have else None, missing=sorted(missing_codes),
        crops=crops_sum if have else None, live=live_sum if have else None,
        n=len(rows), n_have=have, gdp_all=gdp_all, gdp_have=gdp_have,
    ))

# crp OUT for constructed regions: one pass over io_s05
cons_out = {}
with gzip.open(io_s05, 'rt') as fh:
    fh.readline()
    want = set(constructed)
    out_i = idx05['OUT']
    for line in fh:
        region, row, _rest = line.split(',', 2)
        if region in want and row == 'dom_crp':
            cons_out[region] = float(line.rstrip('\n').split(',')[out_i] or 0.0)
if set(cons_out) != set(constructed):
    raise SystemExit(f'constructed crp rows missing: {sorted(set(constructed) - set(cons_out))}')

for d in constructed_detail:
    out = cons_out[d['region']]
    fao_sum = d['fao_sum']
    ratio = (out / fao_sum) if fao_sum else None
    cshare = (d['crops'] / fao_sum) if fao_sum else None
    lshare = (d['live'] / fao_sum) if fao_sum else None
    ratio_rows.append(dict(
        region=d['region'], kind='constructed', crp_OUT=out, fao_sum=fao_sum,
        members_missing_fao='|'.join(d['missing']), icio_over_fao=ratio,
        crops_share=cshare, livestock_share=lshare,
    ))

# ---------------------------------------------------------------- targets CSV rows
target_rows = []
for rec in records:
    flag = ''
    if rec['status'] in ('missing', '1998'):
        flag = 'APT-F5-NO-TARGET'
    elif rec['status'] == 'old':
        flag = f"FAO-YEAR-{rec['year']}"
    target_rows.append(dict(
        region=rec['region'], table=rec['table'], crp_OUT=cell(rec['out']), crp_X=cell(rec['x']),
        crp_M=cell(rec['m']), table_gdp=cell(rec['gdp']), s02_gdp=cell(rec['s02']),
        gdp_scale=cell(rec['s']), fao_gpv=cell(rec['gpv']),
        fao_year='' if rec['year'] is None else str(rec['year']), fao_flag=flag,
        DA=cell(rec['da']), DA_alt=cell(rec['da_alt']), soft_threshold=cell(rec['thr']),
        inconsistency=rec['kind'], target_adj=cell(rec['tgt']),
        implied_change_pct=cell(rec['implied']), applied='no',
    ))

# ---------------------------------------------------------------- USA and XNA
usa = by_region['USA']
pri_year, pri_gpv, pri_status = fao_status('PRI')
xna = next(d for d in constructed_detail if d['region'] == 'XNA')
xna_rows = {r['code']: r for r in members['XNA']}
usa_country = s02_country['USA']
pri_gdp = s02_country.get('PRI', float('nan'))
vir_gdp = s02_country.get('VIR', float('nan'))

usa_cfg = {}
if os.path.exists(usa_path):
    udf = pd.read_csv(usa_path, dtype=str).fillna('')
    for _, r in udf.iterrows():
        usa_cfg[r['item'].strip()] = r

def usda(item):
    row = usa_cfg.get(item)
    return float(row['value_musd']) if row is not None and row['value_musd'] else None

census = usda('farm_sales_total')
census_c = usda('farm_sales_crops')
census_l = usda('farm_sales_livestock')
support = usda('ag_support_services')
fao_over_census = (usa['gpv'] / census) if usa['gpv'] and census else None
census_support = (census + support) if census is not None and support is not None else None
support_over_icio = (census_support / usa['out']) if census_support else None

usa_lines = [
    ('output', 'crp_OUT', cell(usa['out']), 'io_s05 USA dom_crp OUT, unscaled USD million'),
    ('trade', 'crp_X', cell(usa['x']), 'dom_crp X, the export target'),
    ('trade', 'crp_M', cell(usa['m']), 'sum of imp_crp over domestic agents'),
    ('gdp', 'table', cell(usa['gdp']), 'VA + TLS + TLS on stock change, S05-H7, unscaled'),
    ('gdp', 's02_region', cell(usa['s02']), 'S02 USA region, country + PRI + VIR (E37)'),
    ('gdp', 's02_country', cell(usa_country), 'S02 USA country row'),
    ('gdp', 'pri', cell(pri_gdp), 'in S02 USA GDP, not in the ICIO US table'),
    ('gdp', 'vir', cell(vir_gdp), 'in S02 USA GDP, not in the ICIO US table'),
    ('gdp', 'scale', cell(usa['s']), 's = S02 region GDP / table GDP; the table is not scaled'),
    ('fao', 'gpv', cell(usa['gpv']), f"item 2051 element 57, M49 840, year {usa['year']}, USD million"),
    ('fao', 'crops_share', cell(usa['crops'] / usa['gpv'] if usa['crops'] is not None else None),
     'item 2041 / item 2051, same year'),
    ('fao', 'livestock_share', cell(usa['live'] / usa['gpv'] if usa['live'] is not None else None),
     'item 2044 / item 2051, same year'),
    ('fao', 'icio_over_fao', cell(usa['out'] / usa['gpv']), 'unscaled crp OUT / FAO'),
    ('fao', 'pri', cell(pri_gpv),
     f"M49 630, year {pri_year if pri_year else pri_status}; FAO United States of America excludes PRI"),
    ('target', 'DA', cell(usa['da']), 'GDP-scaled OUT - X'),
    ('target', 'DA_alt', cell(usa['da_alt']), 'GDP-scaled OUT - X + M; not used in T*'),
    ('target', 'soft_threshold', cell(usa['thr']), 's*(X + 0.25*(OUT-X))'),
    ('target', 'inconsistency', usa['kind'], 'ch.9A §A.2 p.3'),
    ('target', 'target_adj', cell(usa['tgt']), 'max(FAO, soft threshold); not applied'),
    ('target', 'implied_change_pct', cell(usa['implied']), '100*(T*/(s*OUT) - 1)'),
    ('target', 'applied', 'no', 'H5: no USA cell changes'),
    ('usda', 'farm_sales_total', cell(census, 0), blank(usa_cfg.get('farm_sales_total', {}).get('source', ''))),
    ('usda', 'farm_sales_crops', cell(census_c, 0), 'Census of Agriculture 2022 Vol.1 US Table 2'),
    ('usda', 'farm_sales_livestock', cell(census_l, 0), 'Census of Agriculture 2022 Vol.1 US Table 2'),
    ('usda', 'ag_support_services', cell(support, 0), 'ERS Chart of Note 109259, 2022 Economic Census'),
    ('usda', 'fao_over_census_sales', cell(fao_over_census),
     'FAO item 2051 / census farm sales. Census sales are not production (inventory change, on-farm use). Approximate.'),
    ('usda', 'census_plus_support_over_icio', cell(support_over_icio),
     '(census sales + support-service receipts) / ICIO A01. Approximate, same reason.'),
    ('xna', 'crp_OUT', cell(cons_out['XNA']), 'donor-derived crp, io_s05, report only (ch.9A p.2)'),
    ('xna', 'fao_sum', cell(xna['fao_sum']), 'sum of member FAO values with a usable year'),
    ('xna', 'icio_over_fao', cell((cons_out['XNA'] / xna['fao_sum']) if xna['fao_sum'] else None), ''),
    ('xna', 'members_missing_fao', '|'.join(xna['missing']), f"{len(xna['missing'])} of {xna['n']} members"),
    ('xna', 'bmu_donor', xna_rows['BMU']['donor'],
     f"weight {xna_rows['BMU']['weight']}; USA is the XNA donor for Bermuda"),
    ('xna', 'grl_donor', xna_rows['GRL']['donor'],
     f"weight {xna_rows['GRL']['weight']}; USA is the XNA donor for Greenland"),
]

# ---------------------------------------------------------------- copy and write
S.log('copying io_s05.csv.gz to io_s06.csv.gz without re-gzipping')
shutil.copyfile(io_s05, S.out + '/io_s06.csv.gz')
target_cols = ['region', 'table', 'crp_OUT', 'crp_X', 'crp_M', 'table_gdp', 's02_gdp', 'gdp_scale',
               'fao_gpv', 'fao_year', 'fao_flag', 'DA', 'DA_alt', 'soft_threshold', 'inconsistency',
               'target_adj', 'implied_change_pct', 'applied']
S.write('apt_targets.csv', target_rows, target_cols)
# Ratio file follows S01 order, then ISL, then is already in that order for primaries
# only if records were. Rebuild in region_order + ISL.
ratio_by = {r['region']: r for r in ratio_rows}
ratio_out = []
for code in region_order + ['ISL']:
    r = ratio_by[code]
    ratio_out.append(dict(
        region=r['region'], kind=r['kind'], crp_OUT=cell(r['crp_OUT']), fao_sum=cell(r['fao_sum']),
        members_missing_fao=r['members_missing_fao'], icio_over_fao=cell(r['icio_over_fao']),
        crops_share=cell(r['crops_share']), livestock_share=cell(r['livestock_share']),
    ))
ratio_cols = ['region', 'kind', 'crp_OUT', 'fao_sum', 'members_missing_fao', 'icio_over_fao',
              'crops_share', 'livestock_share']
S.write('apt_ratio_all.csv', ratio_out, ratio_cols)
S.write('usa_scrutiny_s06.csv',
        [dict(item=a, key=b, value=c, note=d) for a, b, c, d in usa_lines],
        ['item', 'key', 'value', 'note'])

too_big = [f'{fn} {os.path.getsize(S.out + "/" + fn)}' for fn in os.listdir(S.out)
           if os.path.getsize(S.out + '/' + fn) >= 50 * 1024 * 1024]
if too_big:
    raise SystemExit('output file at or over 50 MB: ' + ' '.join(too_big))

# ---------------------------------------------------------------- hard checks
h1_ok = a01 == ['crp'] and seen_2051 and '1000' in unit_57 and not fao_dup and n_kept > 0
usa_raw = None
if usa['year'] is not None:
    usa_raw = series_for('USA', '2051')[usa['year']]
h1_conv = usa_raw is not None and abs(usa_raw / 1000.0 - usa['gpv']) <= 1e-9
S.check('S06-H1',
        'crp is the only ICIO A01 sector; FAO element 57 item 2051 is present; thousand USD divided by 1000',
        'hard', f"A01 sectors {a01}; unit {unit_57!r}; kept {n_kept}; duplicate conflicts {len(fao_dup)}",
        'crp only; element 57; item 2051; /1000; 0 conflicts',
        h1_ok and h1_conv, 'ch.9A Table 9.1 p.2; C18',
        f"USA raw {usa_raw} thousand USD / 1000 = {None if usa_raw is None else usa_raw / 1000.0:.6f}; "
        f"stored {usa['gpv']}. " + ' '.join(fao_dup[:8]))

S.check('S06-H2',
        'apt_rule.csv is one decided row and apt_choices.csv has the six choices; gtap9a_target is not built',
        'hard', f"{RULE}; decided_by {rule_row.get('decided_by', '')}; choices {len(choices)}; soft_fraction {FRAC}",
        'one row; decided_by filled; six choices; report_only',
        not h2_problems and RULE == 'report_only', 'decision 10; E4; C18',
        ' '.join(h2_problems) + f" decided_at {rule_row.get('decided_at', '')}")

# ISL is not an ICIO economy. F5 for H3 is the ICIO set.
f5_icio = tuple(sorted(r['region'] for r in records if r['region'] in primaries and r['kind'] == 'no FAO'))
in_targets = {r['region'] for r in records}
cons_in_targets = sorted(in_targets & set(constructed))
S.check('S06-H3',
        '80 primary tables (79 ICIO regions + ISL); F5 is the ICIO set with no usable FAO year; no constructed target',
        'hard', f"{len(records)} rows; F5 {','.join(f5_icio) or 'none'}; constructed in targets {len(cons_in_targets)}",
        '80; ARE,COD,MMR,STP,TWN; 0 constructed',
        len(records) == 80 and f5_icio == tuple(sorted(F5_EXPECT)) and not cons_in_targets,
        CIT_A1,
        'ISL status ' + records[-1]['status'] + f"; ISL inconsistency {records[-1]['kind']}")

year_bad = []
for rec in records:
    if rec['year'] is None:
        continue
    year_map = series_for(rec['region'], '2051')
    latest = max(y for y in year_map if y <= BASE_YEAR)
    if rec['year'] != latest or latest == TOO_OLD:
        year_bad.append(rec['region'])
unmapped_prim = [c for c in primaries if c not in iso_to_m49 and c not in f5_icio]
S.check('S06-H4',
        'fao_year is the latest year at or before the base year; CHN is M49 156, not 159; every ICIO economy is mapped or in F5',
        'hard', f"year mismatches {len(year_bad)}; CHN M49 {iso_to_m49.get('CHN')}; unmapped primaries not in F5 {len(unmapped_prim)}",
        '0 mismatches; CHN 156; 0 unmapped outside F5',
        not year_bad and iso_to_m49.get('CHN') == 156 and 159 not in m49_to_iso and not unmapped_prim,
        'handoff H4; ISO 3166-1 numeric = UN M49',
        'aliases used: ' + '; '.join(alias_used))

sha_s06 = sha256(S.out + '/io_s06.csv.gz')
sha_s05 = sha256(io_s05)
S.check('S06-H5',
        'io_s06.csv.gz is a byte copy of io_s05.csv.gz (E43 closed: no cell changed)',
        'hard', sha_s06, IO_S05_SHA,
        sha_s06 == sha_s05 == IO_S05_SHA, CIT_ORDER,
        f'io_s05 {sha_s05}')

max_gap = max((g for _, _, g in path_gap), default=0.0)
gap_where = max(path_gap, key=lambda t: t[2]) if path_gap else ('', '', 0.0)
below = [r['region'] for r in records if r['gpv'] is not None and r['tgt'] + 1e-9 < r['gpv']]
S.check('S06-H6',
        'Second path recomputes s, X, DA, the threshold and target_adj within 1e-6; target_adj >= FAO',
        'hard', f"max abs {max_gap:.3e} at {gap_where[0]} {gap_where[1]}; below FAO {len(below)}",
        'max abs <= 1e-6; 0 below FAO',
        max_gap <= 1e-6 and not below, 'ch.9A §A.2 p.3',
        'path A reads io_s05 by column and ISL by a numpy sum; path B is a pandas group-by')

h7_err = []
for reg, sector, da, ex, init, adj in TABLE_93:
    _kind, _thr, got = gtap_adjust(init, ex, da, FRAC)
    err = abs(got - adj)
    h7_err.append((err, reg, sector, got, adj))
h7_max = max(e[0] for e in h7_err)
S.check('S06-H7',
        'The coded rule reproduces all 20 adjusted targets of ch.9A Table 9.3 (p.7) within ±1 USD million',
        'hard', f"20 rows; max abs error {h7_max:.4f}", '20; max abs <= 1',
        len(TABLE_93) == 20 and h7_max <= 1.0, 'GTAP 12 ch.9A Table 9.3 p.7; §A.2 p.3',
        'largest: ' + '; '.join(f'{r} {s} got {g:.2f} table {a}' for e, r, s, g, a in sorted(h7_err, reverse=True)[:5]))

required = ('crp_OUT', 'crp_X', 'crp_M', 'table_gdp', 's02_gdp', 'gdp_scale', 'DA', 'DA_alt', 'soft_threshold')
nan_cells = []
neg_fao = []
for row in target_rows:
    for col in required:
        if row[col] == '' or row[col] is None:
            nan_cells.append(f"{row['region']}.{col}")
    if row['fao_gpv'] != '' and float(row['fao_gpv']) < 0:
        neg_fao.append(row['region'])
    if row['inconsistency'] != 'no FAO':
        for col in ('fao_gpv', 'fao_year', 'target_adj', 'implied_change_pct'):
            if row[col] == '':
                nan_cells.append(f"{row['region']}.{col}")
isl_x_gap = abs(isl_a[1] - isl_b[1])
S.check('S06-H8',
        'No NaN in required columns; no negative FAO value; ISL crp exports are the row summed over every other economy',
        'hard', f"blank required {len(nan_cells)}; negative FAO {len(neg_fao)}; ISL X path gap {isl_x_gap:.3e}",
        '0; 0; gap <= 1e-6',
        not nan_cells and not neg_fao and isl_x_gap <= 1e-6, 'ch.9A §A.1 p.2 (primaries, ISL included as an IOT)',
        f"ISL X {isl_a[1]:.6f} from the numpy path and {isl_b[1]:.6f} from the group-by of other economies' columns. "
        + ' '.join(nan_cells[:12]))

# ---------------------------------------------------------------- report checks
with_fao = [r for r in records if r['gpv'] is not None and r['region'] != 'ISL']
with_fao_isl = [r for r in records if r['gpv'] is not None]
ratios = [r['out'] / r['gpv'] for r in with_fao]
agg_den = sum(r['s'] * r['out'] for r in with_fao)
agg_num = sum(r['tgt'] for r in with_fao)
net = agg_num / agg_den - 1.0
agg_den_i = sum(r['s'] * r['out'] for r in with_fao_isl)
agg_num_i = sum(r['tgt'] for r in with_fao_isl)
net_i = agg_num_i / agg_den_i - 1.0
hard = [r for r in records if r['kind'] == 'hard']
soft = [r for r in records if r['kind'] == 'soft']
order_ratio = sorted(with_fao, key=lambda r: r['out'] / r['gpv'])
low10 = ', '.join(f"{r['region']} {r['out'] / r['gpv']:.3f}" for r in order_ratio[:10])
high10 = ', '.join(f"{r['region']} {r['out'] / r['gpv']:.3f}" for r in order_ratio[-10:][::-1])


def kind_alt(rec):
    if rec['gpv'] is None:
        return 'no FAO'
    thr_alt = rec['s'] * rec['x'] + FRAC * rec['da_alt']
    kind, _, _ = gtap_adjust(rec['gpv'], rec['s'] * rec['x'], rec['da_alt'], FRAC)
    return kind, thr_alt


alt_kinds = {}
for rec in records:
    if rec['gpv'] is None:
        alt_kinds[rec['region']] = 'no FAO'
        continue
    # DA_alt is already scaled, so pass it as domestic absorption and scaled exports.
    alt_kinds[rec['region']] = gtap_adjust(rec['gpv'], rec['s'] * rec['x'], rec['da_alt'], FRAC)[0]
flipped = [r['region'] for r in records if alt_kinds[r['region']] != r['kind']]
soft_alt = [c for c, k in alt_kinds.items() if k == 'soft']
hard_alt = [c for c, k in alt_kinds.items() if k == 'hard']

def list_incons(rows):
    bits = []
    for r in rows:
        bits.append(f"{r['region']} FAO {r['gpv']:.2f} X {r['x']:.2f} threshold {r['thr']:.2f} "
                    f"T* {r['tgt']:.2f} change {r['implied']:.2f}%")
    return '; '.join(bits) if bits else 'none'

S.check('S06-R1',
        'Primary ICIO/FAO distribution, net implied change beside Table 9.2, and the hard and soft lists',
        'report',
        f"n {len(with_fao)} median {percentile(ratios, 50):.3f} IQR {percentile(ratios, 25):.3f}-{percentile(ratios, 75):.3f} "
        f"net {net:.1%} (with ISL {net_i:.1%}); hard {len(hard)} soft {len(soft)}",
        'report; Table 9.2 net −6.89% (2023) and −9.52% (2017)',
        True, 'ch.9A Table 9.2 p.4; C18',
        f"Lowest 10: {low10}. Highest 10: {high10}. "
        f"Hard: {list_incons(hard)}. Soft: {list_incons(soft)}. "
        f"Under DA_alt, hard {len(hard_alt)} ({', '.join(sorted(hard_alt)) or 'none'}), "
        f"soft {len(soft_alt)} ({', '.join(sorted(soft_alt)) or 'none'}); "
        f"regions whose label changes: {', '.join(flipped) or 'none'}. "
        f"Percentiles are linear in the order statistics. The net is sum(T*)/sum(s*OUT)-1 over ICIO primaries with a FAO value, "
        f"not the median of the country percent changes. Preview on the handoff was median 1.29, IQR 1.13-1.51, net −26.1%, "
        f"1 hard (LUX) and 3 soft (AGO, ARG, NLD), on the 74 of 79 with 2022 data.")

cons_ratios = []
full_ratios = []
for d in constructed_detail:
    if not d['fao_sum']:
        continue
    ratio = cons_out[d['region']] / d['fao_sum']
    cons_ratios.append(ratio)
    if not d['missing']:
        full_ratios.append(ratio)
n_miss_regions = sum(1 for d in constructed_detail if d['missing'])
S.check('S06-R2',
        'Constructed regions: crp against the sum of members with a usable FAO value; missing members are not filled',
        'report',
        f"88 regions; ratio on {len(cons_ratios)}; median {percentile(cons_ratios, 50):.3f}; "
        f"full coverage ratio on {len(full_ratios)}; median {percentile(full_ratios, 50):.3f}; "
        f"regions with a missing member {n_miss_regions}",
        'report only; ch.9A p.2; all-regions median beside full-coverage median (no missing member)',
        True, CIT_A1,
        'Missing members are left out of the sum. They are not entered as zero. '
        'Full coverage is the constructed regions with a ratio and no missing member. '
        + '; '.join(f"{d['region']} missing {'|'.join(d['missing'])} "
                    f"FAO GDP share {d['gdp_have'] / d['gdp_all']:.3f}" if d['gdp_all'] else f"{d['region']} no GDP"
                    for d in constructed_detail if d['missing'])[:4000])

S.check('S06-R3',
        'USA crp, FAO, USDA census cross-check, Puerto Rico, and XNA',
        'report',
        f"OUT {usa['out']:.2f}; FAO {usa['gpv']:.2f}; ratio {usa['out'] / usa['gpv']:.4f}; "
        f"s {usa['s']:.6f}; T* {usa['tgt']:.2f}; change {usa['implied']:.2f}%; "
        f"FAO/census {fao_over_census:.3f}; census+support/ICIO {support_over_icio:.3f}",
        'report; no cell change',
        True, 'C18; E37',
        f"PRI FAO {pri_gpv} ({pri_status}, year {pri_year}). "
        f"Census sales are not production. XNA crp {cons_out['XNA']:.2f}, member FAO {xna['fao_sum']}, "
        f"BMU donor {xna_rows['BMU']['donor']}, GRL donor {xna_rows['GRL']['donor']}.")

crop_shares = [r['crops'] / r['gpv'] for r in with_fao_isl if r['crops'] is not None and r['gpv']]
live_shares = [r['live'] / r['gpv'] for r in with_fao_isl if r['live'] is not None and r['gpv']]
S.check('S06-R4',
        'FAO crops (item 2041) and livestock (item 2044) shares of item 2051; composition only, no sub-sector in the table',
        'report',
        f"crops share n {len(crop_shares)} median {percentile(crop_shares, 50):.3f}; "
        f"livestock share n {len(live_shares)} median {percentile(live_shares, 50):.3f}",
        'report only; E4',
        True, 'E4; C18',
        'USA crops share ' + cell(usa['crops'] / usa['gpv'] if usa['crops'] is not None else None))

S.check('S06-R6',
        'E43 closed: S06 changes no cell, so the S05-then-S06 order equals GTAP APT-then-composites order',
        'report', sha_s06 == IO_S05_SHA, True, sha_s06 == IO_S05_SHA, CIT_ORDER + '; ' + CIT_B6,
        'H5 is the proof. Under report_only the APT-adjusted primaries are the untargeted ones. '
        'Switching to gtap9a_target later requires the composite rebuild from targeted primaries.')

# ---------------------------------------------------------------- ledger and flags
for rec in records:
    bits = ['APT-REPORT-ONLY']
    if rec['kind'] == 'no FAO':
        bits.append('APT-F5-NO-TARGET')
    elif rec['kind'] == 'soft':
        bits.append('APT-SOFT')
    elif rec['kind'] == 'hard':
        bits.append('APT-HARD')
    if rec['status'] == 'old':
        bits.append(f"FAO-YEAR-{rec['year']}")
    if rec['region'] == 'ISL':
        bits.append('ISL-IN-XWE')
    before = cell(rec['s'] * rec['out'], 4)
    after = '' if rec['tgt'] is None else cell(rec['tgt'], 4)
    S.adjust(rec['region'], 'crp', before, after, 'GTAP12-9A-A2-p3-report', CIT_A2, '|'.join(bits))
    S.flag('APT-REPORT-ONLY', rec['region'],
           'ch.9A target computed and not applied. Decision 10 / E4: FAO level is report-only (C18).',
           'no', 'report_only', CIT_A1)
    if rec['kind'] == 'no FAO':
        why = '1998 only' if rec['status'] == '1998' else 'no FAO row at or before the base year'
        S.flag('APT-F5-NO-TARGET', rec['region'],
               f'{why}. No target. TWN yearbook not fetched.',
               'no', 'F5', 'READINESS F5 (approved): 1998 only, treat as missing')
    elif rec['kind'] == 'soft':
        S.flag('APT-SOFT', rec['region'],
               f"FAO {rec['gpv']:.2f} is below the threshold {rec['thr']:.2f} and above scaled exports {rec['s'] * rec['x']:.2f}. Not applied.",
               'no', 'GTAP12-9A-A2-p3-report', CIT_A2)
    elif rec['kind'] == 'hard':
        S.flag('APT-HARD', rec['region'],
               f"FAO {rec['gpv']:.2f} is below scaled exports {rec['s'] * rec['x']:.2f}. Threshold {rec['thr']:.2f}. Not applied.",
               'no', 'GTAP12-9A-A2-p3-report', CIT_A2)
    if rec['region'] == 'ISL':
        S.flag('ISL-IN-XWE', 'ISL',
               'ISL is not a region. Its table is io_s04. It is a member of XWE. APT is computed for the ISL table and not applied to XWE.',
               'no', 'report_only', CIT_A1)

# Member (and any primary already covered) year flags. One row per code.
seen_year = set()
for code, year in old_year_flags:
    if (code, year) in seen_year:
        continue
    seen_year.add((code, year))
    S.flag(f'FAO-YEAR-{year}', code,
           f'Latest FAO item 2051 year at or before {BASE_YEAR} is {year}. Used, and flagged. 1998 would have been F5.',
           'no', 'fao_year', 'READINESS year rule; apt_choices.csv fao_year')

# Constructed regions with a gap in member FAO. Report only. The ratio leaves those members out.
for d in constructed_detail:
    if not d['missing']:
        continue
    S.flag('FAO-MEMBER-MISSING', d['region'],
           f"{len(d['missing'])} of {d['n']} members have no usable FAO value ({'|'.join(d['missing'])}). "
           'Left out of the FAO sum. Not filled with zero. Report only.',
           'no', 'fao_year', CIT_A1)

S.log(f"rule {RULE}; primaries with FAO {len(with_fao_isl)}; F5 {','.join(f5_icio)}; "
      f"hard {len(hard)}; soft {len(soft)}; net {net:.2%}")
S.finish()
