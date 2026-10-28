"""S05 composite and non-ICIO I-O tables (GTAP 12 ch.9D §D.3).

The donor rule is the one row in config/s05/donor_rule.csv. This script does not choose it.
David (2026-10-21 03:23 UTC+7) set gtap15_gdppc: nearest GDP per capita inside GTAP's
15 composite-construction regions (ch.9D §D.2 p.2 and §D.3 p.3).

Each donor table is divided by its own GDP and summed with S02 GDP-share weights
(ch.7 §7.2 p.3). Stock-change and Angola G-revision gaps are carried, not plugged.

B8 (David, 2026-10-24, card): the members in config/s05/oil_donors.csv keep their 9D donor for every
column except B06 (oil and gas, split at S11), which takes an ICIO oil producer's cost structure
(s05_composite/oil.py). That is our own choice, logged as a departure from the literal 9D rule.
"""
import gzip
import math
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/lib')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stagekit import BUILD, ROOT, STAGES, Stage, sha256  # noqa: E402
from s05_composite import oil as OIL  # noqa: E402
from s05_composite import guards as GD  # noqa: E402
from s05_composite import va_sections as VS  # noqa: E402

S = Stage('S05', 'composite')
I = S.inp
S01 = S.upstream(STAGES + '/S01_sets_registry')
S02 = S.upstream(STAGES + '/S02_macro')
S03 = S.upstream(STAGES + '/S03_io_cleaning')
S04 = S.upstream(STAGES + '/S04_disagg_gov')

CIT_D3 = ('GTAP 12 ch.9D §D.3 p.3 ("all the 251 standard countries are matched on the basis of '
          'similarity in GDP per capita with a primary region within the same geographic region"; '
          '"summed according to the GDP share weights")')
CIT_D2 = ('GTAP 12 ch.9D §D.2 p.2 ("a smaller set of 15 geographic regions is used in constructing '
          'the composite regions"; Caribbean, Central America and South America as Latin America; '
          '"Eastern Africa, Central Africa, Western Africa, and Southern Africa")')
CIT_D3_FIT = ('GTAP 12 ch.9D §D.3 p.3 ("The IOTs for the composite regions are then updated and adjusted '
              'to match aggregated regional data on macroeconomic aggregates, trade, protection, and energy '
              'in the FIT procedure documented in chapter 15.A.")')
CIT_CH7 = ('GTAP 12 ch.7 §7.2 p.3 ("Similar per capita GDP is used as a criterion for matching a member '
           'country in a composite region to one of the primary regions within the same geographic area"; '
           '"scaled-up by the ratio of gross domestic product (GDP) calculated from the I-O tables to '
           'external GDP data in current US dollars")')
CIT_CH7_ZERO = ('GTAP 12 ch.7 p.2 ("there was no data on GDP or sometimes population, so we assume and '
                'assigned a zero value for these territories")')
CIT_CH8 = ('GTAP 12 ch.8 §8.3 p.4 ("Finally, for each region where we have no contributed table, we calculate '
           'a composite table, as a linear combination of I-O tables for selected primary regions")')
CIT_CH8_AIM = ('GTAP 12 ch.8 §8.3 p.4 ("matching as closely as possible the composite region\'s income level '
               'and production pattern, as described in Chapter 9D")')
CIT_APT = ('GTAP 12 ch.9A p.2 ("The APT procedure is not applied to the composite regions in the GTAP Data Base")')
CIT_ORDER = ('GTAP 12 ch.8 §8.3 p.3 ("Second, agricultural production targets"; "Third" is the government '
             'check in Chapter 9C) and p.4 ("Finally" the composite table)')

TOL_ABS = 0.05
TOL_REL = 1e-9
GDPPC_RATIO_MAX = 3.0          # PR #71 gate, carried and not acted on
DONOR_TABLES_SHA = '2adaedabbe4b28dd411f1a3317298631c5d6f07aa6c0c61992fa9b5a92474377'
DONOR_CANDIDATES_SHA = '01b065b6a8d11e5668e4e5dc2966dc58db1e8e7a0fbbfc6b6af6354b48275ffa'
RULES = ('pr71_chosen', 'pr71_gtap9d', 'gtap15_gdppc')
# ch.9D §D.2 p.2. Applied for every member of these regions under gtap15_gdppc.
# Under the PR #71 rules the same groups are used only when the 19-region pool is empty.
GEO15_PARTS = {
    'LMAR': ('CARB', 'CAMR', 'SAMR'),
    'SSAF': ('EAFR', 'CAFR', 'WAFR', 'SAFR'),
}
GEO_TO_15 = {g: label for label, parts in GEO15_PARTS.items() for g in parts}
# Aliases PR #71 used where the S01 country map has no geographic code.
GEO_ALIAS = {'KSV': 'XKX', 'PAL': 'PSE'}
NAMED_EXCLUDED = ('PRI', 'VIR', 'CHI', 'GGY', 'JEY', 'IMN', 'SHN', 'ATF')

regions = pd.read_csv(I(S01 + '/output/regions.csv', 'S01 regions'))
comp_members = pd.read_csv(I(S01 + '/output/composite_members.csv', 'S01 composite members'))
crm = pd.read_csv(I(S01 + '/output/country_region_map.csv', 'S01 country-region map'))
geo_table = pd.read_csv(I(S01 + '/output/gtap_geo_regions_table910.csv', 'S01 Table 9.10 geographic regions'))
sectors = pd.read_csv(I(S01 + '/output/sectors.csv', 'S01 sectors'))
macro = pd.read_csv(I(S02 + '/output/macro_country.csv', 'S02 country macro'))
macro_reg = pd.read_csv(I(S02 + '/output/macro_regions.csv', 'S02 region macro')).set_index('region')
stock = pd.read_csv(I(S03 + '/output/stock_change_gap.csv', 'S03 stock-change gap'))
cmp = pd.read_csv(I(S03 + '/output/macro_comparison.csv', 'S03 macro comparison')).set_index('economy')
io_path = I(S04 + '/output/io_s04.csv.gz', 'S04 I-O table')
grev_src = pd.read_csv(I(S04 + '/output/gov_revision_gap.csv', 'S04 government-revision gap'))
rule_path = I(BUILD + '/config/s05/donor_rule.csv', 'S05 donor-rule decision')
oil_path = I(BUILD + '/config/s05/oil_check_codes.csv', 'S05 oil-check codes carried from the standing log')
oil_donor_path = I(BUILD + '/config/s05/oil_donors.csv', 'S05 B8 oil and gas donors for the B06 column (David 2026-10-24)')
guard_path = I(BUILD + '/config/s05/donor_guards.csv', 'S05 donor guards (beta v4 P33; default off)')
dt_path = I(ROOT + '/prep/donor_tables/donor_tables.csv', 'PR #71 donor tables')
dc_path = I(ROOT + '/prep/donor_tables/donor_candidates.csv', 'PR #71 donor candidates')


def blank(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ''
    s = str(v).strip()
    return '' if s.lower() == 'nan' else s


def abs_log(a, b):
    if a is None or b is None:
        return None
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return None
    if not (a > 0 and b > 0) or math.isnan(a) or math.isnan(b):
        return None
    return abs(math.log(a) - math.log(b))


def within(diff, ref):
    d = abs(diff)
    return d <= TOL_ABS or d <= TOL_REL * max(abs(ref), 1e-30)


def rel_close(a, b, tol=TOL_REL):
    return abs(a - b) <= tol * max(abs(a), abs(b), 1.0) or abs(a - b) <= 1e-8


def fmt_num(v, nd):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ''
    return f'{float(v):.{nd}f}'


def fmt_cell(v):
    if v == 0.0 or abs(v) < 5e-13:
        return '0'
    s = f'{float(v):.10f}'.rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s


# ---------------------------------------------------------------- the decision row
rule_df = pd.read_csv(rule_path, dtype=str).fillna('')
if len(rule_df) != 1:
    raise SystemExit(f'donor_rule.csv must have exactly one row, found {len(rule_df)}')
rule_row = {k: str(rule_df.iloc[0][k]).strip() for k in ('rule', 'decided_by', 'decided_at', 'note')}
RULE = rule_row['rule']
if RULE not in RULES or not rule_row['decided_by']:
    raise SystemExit(f'donor_rule.csv row is not a decided rule: {rule_row}')
try:
    oil_donors = OIL.read_oil_donors(oil_donor_path)
    oil_flag = OIL.read_oil_check(oil_path, oil_donors)
except ValueError as exc:
    raise SystemExit(str(exc))
S.log(f"donor rule {RULE} decided_by {rule_row['decided_by']} at {rule_row['decided_at']}")
try:
    GUARDS_ON, BLEND, _guard_rows = GD.read_guards(guard_path)
except ValueError as exc:
    raise SystemExit(str(exc))
VA_SEC = {r['guard']: r['value'] for r in _guard_rows}['donor_va_sections']
# beta v5 S1: the parameter column scopes P37 (blank = every donor-built member; v5: TLS only)
VA_SEC_MEMBERS = VS.members({r['guard']: r['parameter'] for r in _guard_rows}['donor_va_sections'])
S.log('donor guards on: ' + (', '.join(f'{n} ({p})' for n, p in GUARDS_ON) or 'none') + f'; donor_blend {BLEND}'
      + f'; donor_va_sections {VA_SEC}' + (f" for {' '.join(sorted(VA_SEC_MEMBERS))}" if VA_SEC_MEMBERS else ''))
# beta v4 P37 (donor_va_sections, default off): the member's own UN AMA 2022 VA by section group
ama = (VS.read_ama(I(ROOT + '/data/unsd_ama/gva_gdp_current_usd.csv', 'UN AMA 2022 GVA by ISIC group (beta v4 P37)'))
       if VA_SEC != 'off' else {})
guard_moves = {}      # member code -> (donor without guards, donor with guards, all candidates failed)
blend_of = {}         # P33 option C (donor_blend): member code -> [(donor, blend weight)], first = largest weight

if sha256(dt_path) != DONOR_TABLES_SHA:
    raise SystemExit('donor_tables.csv SHA-256 is not the PR #71 file named in the spec')
if sha256(dc_path) != DONOR_CANDIDATES_SHA:
    raise SystemExit('donor_candidates.csv SHA-256 is not the PR #71 file named in the spec')

dt = pd.read_csv(dt_path).rename(columns={'flags': 'flagstr'})
dt['code'] = dt['code'].astype(str)
if dt['code'].duplicated().any():
    raise SystemExit('duplicate code in donor_tables.csv')
dt = dt.set_index('code', drop=False)
dc = pd.read_csv(dc_path)
feat = dc.groupby('candidate', sort=False).agg(
    ppp=('candidate_gdppc_ppp', 'first'),
    mkt=('candidate_gdppc_mkt', 'first'),
    gdp=('candidate_gdp_usd', 'first')).copy()
# One candidate must not carry two income figures.
_nuniq = dc.groupby('candidate').agg(
    np_=('candidate_gdppc_ppp', 'nunique'),
    nm_=('candidate_gdppc_mkt', 'nunique'))
if int(((_nuniq.np_ > 1) | (_nuniq.nm_ > 1)).sum()) != 0:
    raise SystemExit('donor_candidates.csv has conflicting GDP per capita for one candidate')

# ---------------------------------------------------------------- registry: 88 targets, 79 primaries
primaries = []
targets = []
for _, r in regions.iterrows():
    if r['type'] == 'single' and r['icio_measured'] == 'yes':
        primaries.append(r['region'])
    elif r['type'] == 'composite' or (r['type'] == 'single' and r['icio_measured'] == 'no'):
        targets.append(r['region'])
if len(primaries) != 79 or len(targets) != 88:
    raise SystemExit(f'expected 79 primaries and 88 targets, got {len(primaries)} and {len(targets)}')
if 'ISL' in primaries or 'ISL' in targets or 'ROW' in primaries or 'ROW' in targets:
    raise SystemExit('ISL and ROW are not regions')
n_single_no = int(((regions.type == 'single') & (regions.icio_measured == 'no')).sum())
n_composite = int((regions.type == 'composite').sum())
if n_single_no != 80 or n_composite != 8:
    raise SystemExit(f'expected 80 non-ICIO singles and 8 composites, got {n_single_no} and {n_composite}')
all_regions = primaries + targets
# S01 file order, which is the order written to io_s05.
region_order = [r for r in regions['region'].tolist() if r in set(all_regions)]
if len(region_order) != 167:
    raise SystemExit(f'expected 167 regions, got {len(region_order)}')

crm_geo = {}
for _, r in crm.iterrows():
    g = blank(r['gtap_geo'])
    if g:
        crm_geo[str(r['code'])] = g
table_geo = {str(r['iso3']): str(r['gtap_geo']) for _, r in geo_table.iterrows()}
reg_geo = {str(r['region']): blank(r['gtap_geo']) for _, r in regions.iterrows()}


def geo_of_code(code, macro_geo):
    g = blank(macro_geo)
    if g:
        return g
    if code in crm_geo:
        return crm_geo[code]
    if code in table_geo:
        return table_geo[code]
    alias = GEO_ALIAS.get(code)
    if alias and alias in table_geo:
        return table_geo[alias]
    return ''


# ICIO donor geography. ISL is an economy table and not a region.
donor_geo = {}
for code in primaries:
    donor_geo[code] = reg_geo[code]
isl_rows = crm.loc[crm['code'] == 'ISL']
if isl_rows.empty or not blank(isl_rows.iloc[0]['gtap_geo']):
    raise SystemExit('ISL has no Table 9.10 geographic region')
donor_geo['ISL'] = blank(isl_rows.iloc[0]['gtap_geo'])
scored = []
for code, g in donor_geo.items():
    if code == 'TWN':
        continue
    if code not in feat.index or pd.isna(feat.loc[code, 'ppp']):
        continue
    if not g:
        raise SystemExit(f'scored donor {code} has no geographic region')
    scored.append(code)
if len(scored) != 79 or 'TWN' in scored or 'ISL' not in scored:
    raise SystemExit(f'expected 79 scored donors including ISL and excluding TWN, got {len(scored)}')
by_geo19 = {}
for code in scored:
    by_geo19.setdefault(donor_geo[code], []).append(code)
for g in by_geo19:
    by_geo19[g] = sorted(by_geo19[g])

macro = macro.copy()
macro['code'] = macro['code'].astype(str)
macro_by_code = macro.set_index('code', drop=False)
s02_gdppc = {}
s02_gdp = {}
for code in scored:
    row = macro_by_code.loc[code]
    gdp, pop = float(row['GDP_musd']), float(row['POP'])
    if not (gdp > 0 and pop > 0):
        raise SystemExit(f'scored donor {code} has no S02 GDP per capita')
    s02_gdppc[code] = gdp / pop
    s02_gdp[code] = gdp

# beta v4 P33: S02 GDP of members and scored donors for the donor guards (guards.py)
guard_ctx = {'gdp': {**{str(c): float(g) for c, g in zip(macro['code'], macro['GDP_musd']) if pd.notna(g)}, **s02_gdp}}


def pool_label(geo, rule):
    if not geo:
        return ''
    if rule == 'gtap15_gdppc':
        return GEO_TO_15.get(geo, geo)
    if by_geo19.get(geo):
        return geo
    if geo in GEO_TO_15:
        return GEO_TO_15[geo]
    return geo


def pool_codes(label, rule):
    if not label:
        return []
    if label in GEO15_PARTS and (rule == 'gtap15_gdppc' or not by_geo19.get(label)):
        geos = GEO15_PARTS[label]
    else:
        geos = (label,)
    out = []
    seen = set()
    for g in geos:
        for code in by_geo19.get(g, []):
            if code not in seen:
                seen.add(code)
                out.append(code)
    return out


def nearest(cands, target, value_of, size_of):
    best = None
    best_key = None
    for code in cands:
        dist = abs_log(target, value_of(code))
        if dist is None:
            continue
        key = (dist, -(size_of(code) or 0.0), code)
        if best_key is None or key < best_key:
            best_key = key
            best = code
    return best


def has_income(code):
    if code not in dt.index:
        return False
    return blank(dt.loc[code, 'income_concept']) in ('ppp', 'market')


def pr71_value(code, concept):
    if concept == 'ppp':
        return float(dt.loc[code, 'gdppc_ppp'])
    return float(dt.loc[code, 'gdppc_mkt'])


def blend_donor(code, cands, target, value_of, size_of, single):
    """P33 option C: record the member's donor blend (guards.blend over the whole pool, its own floor) and return its
    first donor, which stands for the member wherever one donor is named (flags, donor_weights, S12, S13)."""
    b = GD.blend(code, cands, target, value_of, size_of, BLEND, guard_ctx)
    if not b:
        return single
    blend_of[code] = b
    return b[0][0]


def assign_one(code, geo, rule):
    """Return donor, basis, income_concept, gdppc_used."""
    if code == 'ISL':
        return 'ISL', 'own ICIO table', 'own_icio', None
    if has_income(code) and rule == 'pr71_chosen':
        concept = blank(dt.loc[code, 'income_concept'])
        return (blank(dt.loc[code, 'chosen_donor']), 'PR #71 chosen_donor',
                concept, pr71_value(code, concept))
    if has_income(code) and rule == 'pr71_gtap9d':
        concept = blank(dt.loc[code, 'income_concept'])
        return (blank(dt.loc[code, 'gtap9d_nearest_gdppc']), 'PR #71 gtap9d_nearest_gdppc',
                concept, pr71_value(code, concept))
    label = pool_label(geo, rule)
    cands_all = pool_codes(label, rule)
    # beta v4 P33 (donor_guards.csv, default off): candidates failing a guard are skipped before the nearest is taken
    cands, none_pass = GD.allowed(code, cands_all, GUARDS_ON, guard_ctx) if rule == RULE else (cands_all, False)
    if has_income(code):
        concept = blank(dt.loc[code, 'income_concept'])
        target = pr71_value(code, concept)
        if concept == 'ppp':
            donor = nearest(cands, target, lambda d: feat.loc[d, 'ppp'], lambda d: feat.loc[d, 'gdp'])
            basis = 'nearest PPP GDP per capita'
        else:
            donor = nearest(cands, target, lambda d: feat.loc[d, 'mkt'], lambda d: feat.loc[d, 'gdp'])
            basis = 'nearest market GDP per capita'
        vo = (lambda d: feat.loc[d, 'ppp']) if concept == 'ppp' else (lambda d: feat.loc[d, 'mkt'])
        if GUARDS_ON and rule == RULE:
            guard_moves[code] = (nearest(cands_all, target, vo, lambda d: feat.loc[d, 'gdp']) or '', donor or '', none_pass)
        if BLEND != 'off' and rule == RULE:
            donor = blend_donor(code, cands_all, target, vo, lambda d: feat.loc[d, 'gdp'], donor)
        return donor or '', basis, concept, target
    row = macro_by_code.loc[code]
    pop = float(row['POP'])
    gdp = float(row['GDP_musd'])
    if not (pop > 0 and gdp > 0):
        return '', '', '', None
    target = gdp / pop
    donor = nearest(cands, target, lambda d: s02_gdppc[d], lambda d: s02_gdp[d])
    if GUARDS_ON and rule == RULE:
        guard_moves[code] = (nearest(cands_all, target, lambda d: s02_gdppc[d], lambda d: s02_gdp[d]) or '', donor or '', none_pass)
    if BLEND != 'off' and rule == RULE:
        donor = blend_donor(code, cands_all, target, lambda d: s02_gdppc[d], lambda d: s02_gdp[d], donor)
    return donor or '', 'nearest S02 GDP per capita', 's02_market', target


def ratio_for(donor, concept, target):
    if not donor or target is None or not (target > 0):
        return None
    if concept == 'ppp':
        return float(feat.loc[donor, 'ppp']) / float(target)
    if concept == 'market':
        return float(feat.loc[donor, 'mkt']) / float(target)
    if concept == 's02_market':
        return s02_gdppc[donor] / float(target)
    return None


def pr71_tokens(code):
    if code not in dt.index:
        return []
    raw = blank(dt.loc[code, 'flagstr'])
    tokens = [t for t in raw.split('|') if t]
    if blank(dt.loc[code, 'weak_match']) == 'yes':
        tokens.append('weak_match')
    return tokens


# ---------------------------------------------------------------- members of the 88
target_set = set(targets)
members_by_region = {r: [] for r in targets}
for _, row in macro.iterrows():
    if row['region'] in target_set:
        members_by_region[row['region']].append(row)
for r in members_by_region:
    members_by_region[r].sort(key=lambda rec: rec['code'])

assignments = []  # one dict per S02 code in the 88, S01 region order then code
for region in targets:
    for rec in members_by_region[region]:
        code = rec['code']
        gdp = float(rec['GDP_musd'])
        pop = float(rec['POP']) if pd.notna(rec['POP']) else 0.0
        geo = geo_of_code(code, rec['geo'])
        source = blank(rec['GDP_source'])
        if gdp > 0:
            donor, basis, concept, gdppc_used = assign_one(code, geo, RULE)
            weight_gdp = gdp
        else:
            donor, basis, concept, gdppc_used = '', '', '', None
            weight_gdp = 0.0
        # The other two rules, for the comparison file. Zeros stay blank.
        donors_abc = {}
        if gdp > 0:
            for alt in RULES:
                d_alt, _, _, _ = assign_one(code, geo, alt)
                donors_abc[alt] = d_alt
        else:
            donors_abc = {alt: '' for alt in RULES}
        ratio = ratio_for(donor, concept, gdppc_used) if donor else None
        gap_s05 = bool(ratio is not None and abs(math.log(ratio)) > math.log(GDPPC_RATIO_MAX))
        tokens = []

        def add(token):
            if token and token not in tokens:
                tokens.append(token)

        if gdp > 0:
            add(f'DONOR-{RULE}')
        else:
            add('ZERO-GDP-MEMBER')
        if basis == 'nearest S02 GDP per capita':
            add('DONOR-S02-GDPPC')
        if source.startswith('F1 per-capita fill'):
            add('F1-PER-CAPITA-FILL')
        if code == 'ISL':
            add('ISL-IN-XWE')
        if donor == 'AGO':
            add('AGO-GREV-CARRIED')
        oil_donor = oil_donors[code]['oil_donor'] if (code in oil_donors and gdp > 0) else ''
        if oil_donor:
            add(f'OIL-DONOR-B06-{oil_donor}')
        if code in oil_flag:
            add(oil_flag[code]['flag'].strip())
        if gap_s05:
            add('gdppc_gap')
        if code in guard_moves and guard_moves[code][0] != guard_moves[code][1]:
            add('DONOR-GUARD-MOVED')
        if code in guard_moves and guard_moves[code][2]:
            add('DONOR-GUARD-NONE-PASS')
        if code in blend_of:
            add('DONOR-BLEND')
        for token in pr71_tokens(code):
            add(token)
        assignments.append(dict(
            region=region, code=code, geo=geo, pool=pool_label(geo, RULE),
            pool_pr71=pool_label(geo, 'pr71_chosen'),
            s02_gdp=gdp, s02_pop=pop, gdppc=gdppc_used, income_concept=concept,
            donor=donor, donor_rule=RULE, donor_basis=basis, gdp_for_weight=weight_gdp,
            oil_donor=oil_donor, ratio=ratio, flags='|'.join(tokens), source=source,
            abc=donors_abc, pr71_chosen=blank(dt.loc[code, 'chosen_donor']) if code in dt.index else '',
            pr71_gtap9d=blank(dt.loc[code, 'gtap9d_nearest_gdppc']) if code in dt.index else '',
        ))

# beta v4 P33: what the donor guards changed (report; the guards are David's call and default off)
_moved = {c: m for c, m in guard_moves.items() if m[0] != m[1] or m[2]}
S.check('S05-Rguard', 'Donor guards (config/s05/donor_guards.csv; default off): members whose donor the guards changed, '
        'or for whom no candidate passed', 'report', len(_moved), 'n/a', True,
        'donor_guards (beta v4 P33; departure from the literal ch.9D rule when on)',
        ('guards on: ' + ', '.join(f'{n} ({p})' for n, p in GUARDS_ON) + '; ' if GUARDS_ON else 'no guard on; ')
        + '; '.join(f'{c} {o} -> {n}' + (' (none passed; nearest kept)' if x else '') for c, (o, n, x) in sorted(_moved.items())))
S.check('S05-Rblend', 'Donor blend (config/s05/donor_guards.csv donor_blend; P33 option C; default off): members and their donors '
        'with blend weights', 'report', len(blend_of), 'n/a', True, 'donor_blend (departure from the literal ch.9D rule when on; ch.7 §7.2 p.3)',
        f'donor_blend {BLEND}' + ('; ' + '; '.join(f'{c} ' + '/'.join(f'{d} {w:.2f}' for d, w in b) for c, b in sorted(blend_of.items()))
                                  if blend_of else ''))
# B8 oil donors: the config row must name the donor the 9D rule gives, so a rule change cannot pass silently.
_by_code = {a['code']: a for a in assignments}
_oil_bad = []
for code, r in sorted(oil_donors.items()):
    a = _by_code.get(code)
    if a is None or a['s02_gdp'] <= 0:
        _oil_bad.append(f'{code} is not a member with S02 GDP > 0')
    elif BLEND == 'off' and a['donor'] != r['base_donor']:
        _oil_bad.append(f"{code} 9D donor {a['donor']} is not base_donor {r['base_donor']}")
    elif BLEND != 'off' and ';'.join(d for d, _w in blend_of.get(code, [])) != r['blend_donors']:
        _oil_bad.append(f"{code} donor blend {';'.join(d for d, _w in blend_of.get(code, []))} is not blend_donors {r['blend_donors']!r}")
    if r['oil_donor'] not in scored or r['oil_donor'] in ('ROW', 'TWN', 'ISL'):
        _oil_bad.append(f"{code} oil donor {r['oil_donor']} is not a scored ICIO economy table")
if _oil_bad:
    raise SystemExit('oil_donors.csv: ' + '; '.join(_oil_bad))
S.log(f'B8 oil donors for the B06 column: {len(oil_donors)} members')

# Region GDP weights.
for region in targets:
    rows = [a for a in assignments if a['region'] == region]
    total = sum(a['gdp_for_weight'] for a in rows)
    reg_gdp = float(macro_reg.loc[region, 'GDP_musd'])
    for a in rows:
        a['region_gdp'] = reg_gdp
        a['member_gdp_sum'] = total
        a['weight'] = (a['gdp_for_weight'] / total) if total > 0 and a['gdp_for_weight'] > 0 else 0.0

S.log(f'{len(assignments)} S02 codes in the 88 regions; '
      f'{sum(a["s02_gdp"] > 0 for a in assignments)} with GDP > 0')

# ---------------------------------------------------------------- read io_s04
S.log(f'reading {io_path}')
with gzip.open(io_path, 'rt') as fh:
    header = fh.readline().rstrip('\n').split(',')
    row_labels = []
    data = []
    for line in fh:
        parts = line.rstrip('\n').split(',')
        row_labels.append(parts[0])
        data.append([0.0 if x in ('0', '') else float(x) for x in parts[1:]])
M = np.asarray(data, dtype=np.float64)
col_labels = header[1:]
assert col_labels[-1] == 'OUT' and row_labels[-3:] == ['TLS', 'VA', 'OUT']
del data

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
agents = sec + ['p', 'g', 'i', 'dpabr']
n_a = len(agents)
assert n_a == 54 and M.shape == (n_e * n_s + 3, n_e * n_a + 1), M.shape
for ai, ag in enumerate(agents):
    assert col_labels[ai] == f'{economies[0]}_{ag}'
eco_index = {e: i for i, e in enumerate(economies)}
assert 'ROW' in eco_index and 'ISL' in eco_index and 'TWN' in eco_index and 'AGO' in eco_index
P = M[:n_e * n_s, :n_e * n_a].reshape(n_e, n_s, n_e, n_a)
TLS = M[n_e * n_s, :n_e * n_a].reshape(n_e, n_a)
VA = M[n_e * n_s + 1, :n_e * n_a].reshape(n_e, n_a)
OUTC = M[:n_e * n_s, -1].reshape(n_e, n_s)
S.log(f'{n_e} blocks, {n_s} sectors, matrix {M.shape[0]} x {M.shape[1]}')

# ---------------------------------------------------------------- gaps
prod_stock = stock.loc[stock.kind == 'product']
stock_dom_s = prod_stock.groupby(['origin', 'sector'], sort=False)['value_musd'].sum()
stock_imp_s = (prod_stock.loc[prod_stock.origin != prod_stock.destination]
               .groupby(['destination', 'sector'], sort=False)['value_musd'].sum())
tls_inv_s = (stock.loc[stock.kind == 'tls_on_invnt']
             .groupby('destination', sort=False)['value_musd'].sum())
grev_prod = grev_src.loc[grev_src.kind == 'product']
grev_dom_s = grev_prod.groupby(['origin', 'sector'], sort=False)['gap_musd'].sum()
ago_tls_gap = float(grev_src.loc[grev_src.kind != 'product', 'gap_musd'].sum())
ago_i = eco_index['AGO']

stock_dom = np.zeros((n_e, n_s))
stock_imp = np.zeros((n_e, n_s))
grev_dom = np.zeros((n_e, n_s))
grev_imp = np.zeros((n_e, n_s))
tls_inv = np.zeros(n_e)
for (origin, sector), val in stock_dom_s.items():
    if origin in eco_index and sector in sec:
        stock_dom[eco_index[origin], sec.index(sector)] = float(val)
for (dest, sector), val in stock_imp_s.items():
    if dest in eco_index and sector in sec:
        stock_imp[eco_index[dest], sec.index(sector)] = float(val)
for (origin, sector), val in grev_dom_s.items():
    if origin in eco_index and sector in sec:
        grev_dom[eco_index[origin], sec.index(sector)] = float(val)
        if origin != 'AGO':
            grev_imp[ago_i, sec.index(sector)] += float(val)
for dest, val in tls_inv_s.items():
    if dest in eco_index:
        tls_inv[eco_index[dest]] = float(val)

X_C, ST_C, GR_C, OUT_C = n_a, n_a + 1, n_a + 2, n_a + 3
TLS_R, VA_R, OUT_R = 2 * n_s, 2 * n_s + 1, 2 * n_s + 2
N_ROWS, N_COLS = 2 * n_s + 3, n_a + 4
row_names = [f'dom_{s}' for s in sec] + [f'imp_{s}' for s in sec] + ['TLS', 'VA', 'OUT']
col_names = agents + ['X', 'stock_gap', 'grev_gap', 'OUT']
assert len(row_names) == N_ROWS and len(col_names) == N_COLS


def assemble(dom, imp, exports, tls_row, va_row, out_sec, ei):
    T = np.zeros((N_ROWS, N_COLS))
    T[:n_s, :n_a] = dom
    T[:n_s, X_C] = exports
    T[:n_s, ST_C] = stock_dom[ei]
    T[:n_s, GR_C] = grev_dom[ei]
    T[:n_s, OUT_C] = out_sec
    T[n_s:2 * n_s, :n_a] = imp
    T[n_s:2 * n_s, ST_C] = stock_imp[ei]
    T[n_s:2 * n_s, GR_C] = grev_imp[ei]
    T[TLS_R, :n_a] = tls_row
    T[TLS_R, ST_C] = tls_inv[ei]
    T[VA_R, :n_a] = va_row
    T[OUT_R, :n_s] = out_sec
    return T


def flows_numpy(ei):
    dom = np.array(P[ei, :, ei, :], copy=True)
    imp = P[:, :, ei, :].sum(axis=0) - dom
    exports = P[ei].sum(axis=(1, 2)) - dom.sum(axis=1)
    return dom, imp, exports


# Second path: long-format group-by, not the reshape sum. Index arrays are built once.
_si_imp = np.tile(np.repeat(np.arange(n_s), n_a), n_e)
_ai_imp = np.tile(np.arange(n_a), n_e * n_s)
_si_x = np.repeat(np.arange(n_s), n_e * n_a)
_di_x = np.tile(np.repeat(np.arange(n_e), n_a), n_s)


def flows_groupby(ei):
    block = np.ascontiguousarray(P[:, :, ei, :])
    grouped = (pd.DataFrame({'si': _si_imp, 'ai': _ai_imp, 'v': block.ravel()})
               .groupby(['si', 'ai'], sort=True)['v'].sum().unstack('ai'))
    total = grouped.reindex(index=range(n_s), columns=range(n_a), fill_value=0.0).to_numpy(dtype=np.float64)
    dom = np.array(P[ei, :, ei, :], copy=True)
    imp = total - dom
    own = _di_x != ei
    xframe = pd.DataFrame({'si': _si_x[own], 'v': np.ascontiguousarray(P[ei]).ravel()[own]})
    exports = (xframe.groupby('si', sort=True)['v'].sum()
               .reindex(range(n_s), fill_value=0.0).to_numpy(dtype=np.float64))
    return dom, imp, exports


def build_table(ei, flow_fn):
    dom, imp, exports = flow_fn(ei)
    return assemble(dom, imp, exports, TLS[ei], VA[ei], OUTC[ei], ei)


def table_gdp(T):
    return float(T[VA_R, :n_a].sum() + T[TLS_R, :n_a].sum() + T[TLS_R, ST_C])


S.log('building single-region donor tables, numpy path and group-by path')
donor_T = {}
donor_B = {}
donor_gdp = {}
for code in economies:
    ei = eco_index[code]
    donor_T[code] = build_table(ei, flows_numpy)
    donor_B[code] = build_table(ei, flows_groupby)
    donor_gdp[code] = table_gdp(donor_T[code])
    if not (donor_gdp[code] > 0):
        raise SystemExit(f'donor GDP is not positive for {code}')

# Member tables before the GDP scaling. Most members use their donor table as it is. A B8 member's table
# is its 9D donor's with the B06 column given the oil donor's cost structure (s05_composite/oil.py),
# built on both code paths so H5 still compares two independent flow sums.
B06_J = sec.index(OIL.SECTOR)
member_T = {}
member_B = {}
oil_info = {}
def base_table(a, tabs):
    """The member's table before the B8 swap and the GDP scaling: its donor's table, or under donor_blend (P33 option C)
    the blend of its donors' tables, each divided by its own GDP (the blend has GDP 1; ch.7 §7.2 p.3 'a combination of
    one or more primary region I-O tables')."""
    if a['code'] not in blend_of:
        return tabs[a['donor']]
    return sum(w * tabs[d] / donor_gdp[d] for d, w in blend_of[a['code']])


for a in assignments:
    if not a['donor']:
        continue
    if a['oil_donor']:
        try:
            member_T[a['code']], oil_info[a['code']] = OIL.swap_column(
                base_table(a, donor_T), donor_T[a['oil_donor']], B06_J, n_s, n_a)
            member_B[a['code']], _ = OIL.swap_column(
                base_table(a, donor_B), donor_B[a['oil_donor']], B06_J, n_s, n_a)
        except ValueError as exc:
            raise SystemExit(f"B8 swap for {a['code']}: {exc}")
    else:
        member_T[a['code']] = base_table(a, donor_T)
        member_B[a['code']] = base_table(a, donor_B)

# beta v4 P37 (donor_va_sections; labelled departure, s05_composite/va_sections.py): each member table's sector VA moved
# to the member's UN AMA 2022 VA by section group, columns scaled, product rows closed on final uses or imports. Both paths
# take the factors of the official one so H5 still compares the flow sums.
va_sec = {}           # member code -> dict(k, info, bounded, no_room (gap to exports), negative (held at 1), ks)
member_T0, member_B0 = dict(member_T), dict(member_B)     # before P37: H10 checks the B8 swap on these
if VA_SEC != 'off':
    VS.group_of(sec)
    FINAL_COLS = [agents.index(x) for x in ('p', 'g', 'i')] + [X_C]
    for a in assignments:
        if not a['donor'] or a['code'] not in ama or (VA_SEC_MEMBERS is not None and a['code'] not in VA_SEC_MEMBERS):
            continue
        k, info, bounded = VS.factors(member_T[a['code']][VA_R, :n_s], sec, ama[a['code']], VA_SEC)
        ks = VS.sector_factors(k, sec, VA_SEC)
        member_T[a['code']], ks, no_room, negative = VS.member_factors(member_T[a['code']], ks, n_s, n_a, FINAL_COLS, X_C,
                                                                       ST_C, GR_C, OUT_C, OUT_R)
        member_B[a['code']], _x, _o = VS.rescale(member_B[a['code']], ks, n_s, n_a, FINAL_COLS, X_C, ST_C, GR_C, OUT_C, OUT_R)
        va_sec[a['code']] = dict(k=k, info=info, bounded=bounded, no_room=[sec[j] for j in no_room],
                                 negative=[sec[j] for j in negative], ks=ks)
    # P37 identities on both paths: columns are the pre-P37 columns times the factor, rows keep their residual, every
    # sector's VA is its factor times the pre-P37 VA, and no product, export or OUT cell turns negative
    def _sales(M):
        return M[:n_s, :n_a].sum(axis=1) + M[:n_s, X_C] + M[:n_s, ST_C] - M[:n_s, GR_C]
    va_probs = []
    for code, v in va_sec.items():
        for lab, new, old in (('A', member_T[code], member_T0[code]), ('B', member_B[code], member_B0[code])):
            tol = 1e-9 * max(1.0, float(np.abs(old).max()))
            if np.abs(new[TLS_R:OUT_R + 1, :n_s] - old[TLS_R:OUT_R + 1, :n_s] * v['ks']).max() > tol:
                va_probs.append(f'{code} path {lab}: TLS, VA or OUT is not the factor times the pre-P37 cell')
            if np.abs(new[:2 * n_s, :n_s].sum(axis=0) - old[:2 * n_s, :n_s].sum(axis=0) * v['ks']).max() > tol * n_s:
                va_probs.append(f'{code} path {lab}: a column input total is not the factor times the pre-P37 total')
            if np.abs((_sales(new) - new[:n_s, OUT_C]) - (_sales(old) - old[:n_s, OUT_C])).max() > tol * n_s:
                va_probs.append(f'{code} path {lab}: a product row lost its residual')
            neg = int(((new[:2 * n_s, :n_a + 1] < -1e-9) & (old[:2 * n_s, :n_a + 1] >= -1e-9)).sum())
            if neg:
                va_probs.append(f'{code} path {lab}: {neg} use or export cells turned negative')

for a in assignments:
    if a['donor']:
        a['donor_gdp'] = table_gdp(member_T[a['code']])
        a['scale'] = a['gdp_for_weight'] / a['donor_gdp']
    else:
        a['donor_gdp'] = None
        a['scale'] = 0.0


def construct(region_members, tables):
    acc = np.zeros((N_ROWS, N_COLS))
    for a in region_members:
        if a['gdp_for_weight'] <= 0:
            continue
        acc += a['scale'] * tables[a['code']]
    return acc


tables = {}
tables_b = {}
for region in primaries:
    tables[region] = donor_T[region].copy()
    tables_b[region] = donor_B[region].copy()
for region in targets:
    rows = members_by_region_assign = [a for a in assignments if a['region'] == region]
    tables[region] = construct(rows, member_T)
    tables_b[region] = construct(rows, member_B)

# ---------------------------------------------------------------- H1 input balance
max_abs = 0.0
n_h1_fail = 0
n_h1 = 0
usa_h1 = []
ago_max = 0.0
usa_max = 0.0
worst = None
for ei, e in enumerate(economies):
    for si, name in enumerate(sec):
        n_h1 += 1
        sales = float(P[ei, si].sum()) + stock_dom[ei, si] - grev_dom[ei, si]
        costs = float(P[:, :, ei, si].sum() + TLS[ei, si] + VA[ei, si])
        outv = float(OUTC[ei, si])
        d_so, d_co = sales - outv, costs - outv
        mx = max(abs(d_so), abs(d_co))
        if mx > max_abs:
            max_abs = mx
            worst = (e, name, mx, sales, costs, outv, d_so, d_co)
        if e == 'AGO':
            ago_max = max(ago_max, mx)
        if not (within(d_so, outv) and within(d_co, outv)):
            n_h1_fail += 1
        if e == 'USA':
            usa_max = max(usa_max, mx)
            usa_h1.append((mx, name, sales, costs, outv, d_so, d_co))
usa_h1.sort(reverse=True)
worst_txt = (f'{worst[0]}_{worst[1]} residual {worst[2]:.4f} '
             f'(sales-OUT {worst[6]:+.4f}, costs-OUT {worst[7]:+.4f})')
usa_h1_txt = '; '.join(
    f'{name} {mx:.4f} (sales-OUT {dso:+.4f}, costs-OUT {dco:+.4f})'
    for mx, name, _sales, _costs, _out, dso, dco in usa_h1[:5])
S.check('S05-H1',
        'Input balance on io_s04: for every economy x sector, sales + stock_gap - grev_gap = OUT = costs. '
        'Tolerance abs <= 0.05 USD million or rel <= 1e-9, because the file is the 4-decimal S03 table '
        'with the Angola revision cells at 10 decimals. AGO and USA are shown separately.',
        'hard',
        f'max residual {max_abs:.4f} USD m ({worst_txt}); AGO max {ago_max:.4f}; USA max {usa_max:.4f}; '
        f'sectors {n_h1}; outside tolerance {n_h1_fail}',
        'abs <= 0.05 or rel <= 1e-9; outside tolerance 0',
        n_h1_fail == 0 and n_h1 == n_e * n_s,
        CIT_CH7,
        'Sales are the io_s04 product row. stock_gap adds the INVNT removal back. grev_gap subtracts the '
        'sales added by the Angola government revision, including the seller-side change on every origin '
        'that sells to AGO_g. USA top 5: ' + usa_h1_txt)

# ---------------------------------------------------------------- H2 coverage
weight_codes = {a['code'] for a in assignments if a['donor']}
icio_region_codes = set(macro.loc[macro['region'].isin(primaries), 'code'])
banned_hit = sorted(weight_codes & icio_region_codes)
named_hit = sorted(set(NAMED_EXCLUDED) & weight_codes)
regions_written = set(tables)
S.check('S05-H2',
        'Coverage: the 88 target regions (S01 composite, or single with icio_measured=no) get a constructed '
        'table; the 79 ICIO regions get a converted one; ISL and ROW are not regions. No code whose S01 '
        'region is an ICIO economy gets a donor or a weight (PRI, VIR to USA; CHI, GGY, JEY, IMN, SHN to '
        'GBR; ATF to FRA).',
        'hard',
        f'regions {len(regions_written)}; targets {len(targets)}; primaries {len(primaries)}; '
        f'named excluded with a donor {len(named_hit)}; any ICIO-region code with a donor {len(banned_hit)}',
        '167 regions; 88 targets; 79 primaries; named 0; ICIO-region codes 0',
        (regions_written == set(region_order) and len(named_hit) == 0 and len(banned_hit) == 0
         and 'ISL' not in regions_written and 'ROW' not in regions_written),
        'E37; S05 handoff H2',
        'Named hits: ' + (', '.join(named_hit) or 'none') + '. Other hits: ' + (', '.join(banned_hit) or 'none')
        + f'. composite_members.csv has {comp_members["member"].nunique()} member codes; '
        'S05 members are the S02 codes, territories with GDP included.')

# ---------------------------------------------------------------- H3 donors
tables_ok = sha256(dt_path) == DONOR_TABLES_SHA
cands_ok = sha256(dc_path) == DONOR_CANDIDATES_SHA
sha_ok = tables_ok and cands_ok
pos = [a for a in assignments if a['s02_gdp'] > 0]
zero = [a for a in assignments if a['s02_gdp'] <= 0]
bad_donor = []
bad_pool = []
bad_pr71 = []
for a in pos:
    d = a['donor']
    if d not in scored or d in ('ROW', 'TWN') or d not in donor_geo:
        bad_donor.append(f"{a['code']}->{d or 'NONE'}")
        continue
    label = pool_label(a['geo'], RULE)
    if d not in pool_codes(label, RULE) and not (a['code'] == 'ISL' and d == 'ISL'):
        bad_pool.append(f"{a['code']} geo {a['geo']} pool {label} donor {d}")
    if RULE == 'pr71_chosen' and has_income(a['code']) and d != a['pr71_chosen']:
        bad_pr71.append(a['code'])
    if RULE == 'pr71_gtap9d' and has_income(a['code']) and d != a['pr71_gtap9d']:
        bad_pr71.append(a['code'])
bad_zero = [a['code'] for a in zero if a['donor'] or a['weight'] != 0]
dup_codes = pd.Series([a['code'] for a in assignments]).duplicated().sum()
S.check('S05-H3',
        'Donors: donor_rule.csv has exactly one valid row with decided_by filled. Every code with S02 GDP > 0 '
        'has exactly one donor, an ICIO economy table (not ROW, not TWN, not a composite) inside the rule\'s '
        'pool. Under gtap15_gdppc the pools are the 15 regions. Under pr71_*, widening is only the empty '
        'Caribbean and Eastern Africa pools, and donors equal PR #71 for every PR #71 row that has one. '
        'Zero-GDP codes have weight 0 and no donor. donor_tables.csv and donor_candidates.csv are the PR #71 files.',
        'hard',
        f"rule {RULE}; decided_by {rule_row['decided_by']}; sha {'match' if sha_ok else 'MISMATCH'}; "
        f'positive {len(pos)}; bad donor {len(bad_donor)}; outside pool {len(bad_pool)}; '
        f'PR #71 mismatches {len(bad_pr71)}; zero-GDP with a donor {len(bad_zero)}; duplicate codes {int(dup_codes)}',
        'one decided row; sha match; 0 bad; 0 outside pool; 0 PR #71 mismatches when the rule is pr71_*; 0 zero-GDP donors',
        (sha_ok and RULE in RULES and bool(rule_row['decided_by']) and not bad_donor and not bad_pool
         and not bad_pr71 and not bad_zero and int(dup_codes) == 0 and len(pos) > 0),
        CIT_D3 + '; ' + CIT_D2,
        'Bad donors: ' + (', '.join(bad_donor[:12]) or 'none')
        + '. Outside pool: ' + (', '.join(bad_pool[:12]) or 'none')
        + '. PR #71 mismatches: ' + (', '.join(bad_pr71[:12]) or 'none')
        + f'. donor_tables.csv {"match" if tables_ok else "MISMATCH"}; '
        + f'donor_candidates.csv {"match" if cands_ok else "MISMATCH"}'
        + f". Note: {rule_row['note']}")

# ---------------------------------------------------------------- H4 weights
w_bad = []
gdp_bad = []
for region in targets:
    rows = [a for a in assignments if a['region'] == region]
    wsum = sum(a['weight'] for a in rows)
    if abs(wsum - 1.0) > 1e-12:
        w_bad.append(f'{region} {wsum:.16f}')
    total = rows[0]['member_gdp_sum'] if rows else 0.0
    reg_gdp = float(macro_reg.loc[region, 'GDP_musd'])
    if not rel_close(total, reg_gdp):
        gdp_bad.append(f'{region} members {total:.6f} region {reg_gdp:.6f}')
S.check('S05-H4',
        'Weights: for each of the 88 regions the member weights sum to 1 (1e-12), and the sum of member '
        'S02 GDP equals macro_regions.csv GDP (rel 1e-9). Zero-GDP members have weight 0.',
        'hard',
        f'weight failures {len(w_bad)}; GDP failures {len(gdp_bad)}',
        '0; 0',
        not w_bad and not gdp_bad,
        CIT_D3 + '; ' + CIT_CH7,
        'Weight: ' + ('; '.join(w_bad[:8]) or 'none') + '. GDP: ' + ('; '.join(gdp_bad[:8]) or 'none'))

# ---------------------------------------------------------------- H5 second path
max_p = 0.0
max_c = 0.0
n_p_fail = 0
n_c_fail = 0
worst_p = None
worst_c = None
for region in primaries:
    # beta v4: abs 1e-9 or rel 1e-12 per cell. The two paths sum the same flows in a different order, so
    # cells of 1e6+ USD million differ by float rounding (USA 1.03e-9 after G4; betav3 CHN 9.3e-10).
    d_abs = np.abs(tables[region] - tables_b[region])
    diff = np.max(d_abs)
    if diff > max_p:
        max_p = float(diff)
        worst_p = region
    if (d_abs > np.maximum(1e-9, 1e-12 * np.abs(tables[region]))).any():
        n_p_fail += 1
for region in targets:
    diff = np.max(np.abs(tables[region] - tables_b[region]))
    if diff > max_c:
        max_c = float(diff)
        worst_c = region
    if diff > 1e-6:
        n_c_fail += 1
S.check('S05-H5',
        'Construction, recomputed by a long-format group-by of io_s04 rather than the numpy reshape: '
        'every cell of each of the 88 tables equals sum over members of GDP_m x T_d / GDP_d (abs 1e-6 USD million). '
        'The 79 converted primaries equal their io_s04 aggregates (abs 1e-9 or rel 1e-12 per cell).',
        'hard',
        f'primaries max abs {max_p:.3e} ({worst_p}); outside abs 1e-9 / rel 1e-12 {n_p_fail}; '
        f'constructed max abs {max_c:.3e} ({worst_c}); outside 1e-6 {n_c_fail}',
        'primaries abs <= 1e-9 or rel <= 1e-12; constructed abs <= 1e-6',
        n_p_fail == 0 and n_c_fail == 0,
        CIT_CH7 + '; ' + CIT_D3,
        'The group-by sums origin blocks with pandas and subtracts the domestic block. '
        'The official table sums the reshaped array. Both then apply the same GDP_m / GDP_d weights.')

# ---------------------------------------------------------------- H6 balance
def row_parts(T, si):
    sales = float(T[si, :n_a].sum() + T[si, X_C] + T[si, ST_C] - T[si, GR_C])
    return sales, float(T[si, OUT_C])


def col_parts(T, si):
    costs = float(T[:2 * n_s, si].sum() + T[TLS_R, si] + T[VA_R, si])
    return costs, float(T[OUT_R, si])


# Donor residuals, so the 88 can be compared with the carried rounding.
donor_row_resid = {code: np.array([row_parts(donor_T[code], si)[0] - row_parts(donor_T[code], si)[1]
                                    for si in range(n_s)]) for code in economies}
donor_col_resid = {code: np.array([col_parts(donor_T[code], si)[0] - col_parts(donor_T[code], si)[1]
                                    for si in range(n_s)]) for code in economies}


def member_resid(a):
    """Expected row and column residuals of a member table before scaling. A B8 swap keeps the base donor's
    row residuals; each column residual moves with its output (the B06 column carries the oil donor's)."""
    d = a['donor']
    if a['code'] in blend_of:      # P33 option C: the residuals blend like the tables (each over its donor's GDP)
        row_r = sum(w * donor_row_resid[d_] / donor_gdp[d_] for d_, w in blend_of[a['code']])
        col_r = sum(w * donor_col_resid[d_] / donor_gdp[d_] for d_, w in blend_of[a['code']])
    else:
        row_r, col_r = donor_row_resid[d], donor_col_resid[d]
    if not a['oil_donor'] and a['code'] not in va_sec:
        return row_r, col_r
    x_new = member_T[a['code']][OUT_R, :n_s]
    x_old = base_table(a, donor_T)[OUT_R, :n_s]
    ratio = np.divide(x_new, x_old, out=np.ones(n_s), where=x_old > 0)   # a zero-output column is kept
    col = col_r * ratio
    if a['oil_donor']:
        col[B06_J] = donor_col_resid[a['oil_donor']][B06_J] * x_new[B06_J] / donor_T[a['oil_donor']][OUT_R, B06_J]
    return row_r, col  # P37 keeps each row's residual and scales each column's with its output


n_h6_fail = 0
max_inherited_rel = 0.0
max_arith = 0.0
worst_inherited = None
usa_h6 = []
for region in primaries:
    T = tables[region]
    for si, name in enumerate(sec):
        sales, outv = row_parts(T, si)
        costs, outc = col_parts(T, si)
        if not (within(sales - outv, outv) and within(costs - outc, outc)):
            n_h6_fail += 1
        if region == 'USA':
            usa_h6.append((max(abs(sales - outv), abs(costs - outc)), name, sales - outv, costs - outc, outv))
for region in targets:
    rows = [a for a in assignments if a['region'] == region and a['gdp_for_weight'] > 0]
    T = tables[region]
    resid = [(a['scale'],) + member_resid(a) for a in rows]
    for si, name in enumerate(sec):
        sales, outv = row_parts(T, si)
        costs, outc = col_parts(T, si)
        pred_r = sum(sc * rr[si] for sc, rr, _cc in resid)
        pred_c = sum(sc * cc[si] for sc, _rr, cc in resid)
        err = max(abs((sales - outv) - pred_r), abs((costs - outc) - pred_c))
        if err > max_arith:
            max_arith = err
        if not (rel_close(sales - outv, pred_r) and rel_close(costs - outc, pred_c)):
            n_h6_fail += 1
        rel = abs(sales - outv) / max(abs(outv), 1e-30)
        if rel > max_inherited_rel and abs(outv) >= 1.0:
            max_inherited_rel = rel
            worst_inherited = (region, name, sales - outv, outv, rel)
usa_h6.sort(reverse=True)
usa_h6_txt = '; '.join(
    f'{name} row {dr:+.4f} col {dc_:+.4f} on OUT {outv:,.1f}'
    for _mx, name, dr, dc_, outv in usa_h6[:5])
inh_txt = 'none'
if worst_inherited:
    inh_txt = (f'{worst_inherited[0]}_{worst_inherited[1]} residual {worst_inherited[2]:+.4f} '
               f'on OUT {worst_inherited[3]:,.1f} (rel {worst_inherited[4]:.3e})')
S.check('S05-H6',
        'Balance of all 167 tables. Domestic product rows: sum of use + exports + stock_gap - grev_gap = OUT. '
        'Sector columns: sum of domestic and imported use + TLS + VA = OUT. The 79 use the 4-decimal tolerance '
        '(abs <= 0.05 or rel <= 1e-9). On the 88 the residual equals the GDP-scaled donor residual within '
        'rel 1e-9, which is this stage\'s own arithmetic. The donor residual is the 4-decimal residual already '
        'passed in H1; a direct rel 1e-9 on the level would reject that inherited rounding on tiny sectors.',
        'hard',
        f'failures {n_h6_fail}; max |constructed residual - carried donor residual| {max_arith:.3e}; '
        f'max inherited |residual|/OUT on constructed sectors with OUT >= 1 {max_inherited_rel:.3e}',
        '0 failures; constructed arithmetic rel 1e-9 against the carried donor residual; 79 within abs 0.05 or rel 1e-9',
        n_h6_fail == 0,
        CIT_CH7,
        'USA top 5: ' + usa_h6_txt + '. Largest inherited relative residual among constructed sectors with OUT >= 1: '
        + inh_txt + '. Import rows are uses, not a supply identity.')

# ---------------------------------------------------------------- H7 GDP
gdp_fail_88 = []
gdp_fail_79 = []
for region in targets:
    got = table_gdp(tables[region])
    exp = float(macro_reg.loc[region, 'GDP_musd'])
    if not rel_close(got, exp):
        gdp_fail_88.append(f'{region} table {got:.4f} S02 {exp:.4f}')
for region in primaries:
    got = table_gdp(tables[region])
    exp = float(cmp.loc[region, 'icio_gdp'])
    if region == 'AGO':
        exp += ago_tls_gap
    if not rel_close(got, exp):
        gdp_fail_79.append(f'{region} table {got:.4f} expected {exp:.4f}')
usa_table_gdp = table_gdp(tables['USA'])
usa_s02 = float(macro_reg.loc['USA', 'GDP_musd'])
usa_country = float(macro_by_code.loc['USA', 'GDP_musd'])
S.check('S05-H7',
        'GDP. For the 88, sum of VA + sum of TLS + the TLS stock_gap equals S02 region GDP (rel 1e-9). '
        'For the 79 it equals S03 icio_gdp, and for AGO that figure plus the TLS revision on government consumption. '
        'The 79 are not scaled to S02; that is the FIT.',
        'hard',
        f'88 failures {len(gdp_fail_88)}; 79 failures {len(gdp_fail_79)}; '
        f'AGO donor GDP {donor_gdp["AGO"]:.2f}; AGO TLS revision {ago_tls_gap:.2f}; '
        f'USA table {usa_table_gdp:.2f} vs S02 region {usa_s02:.2f} ({usa_table_gdp / usa_s02 - 1:+.2%})',
        '0 failures',
        not gdp_fail_88 and not gdp_fail_79,
        CIT_CH7 + '; ' + CIT_D3_FIT,
        '88: ' + ('; '.join(gdp_fail_88[:6]) or 'none') + '. 79: ' + ('; '.join(gdp_fail_79[:6]) or 'none')
        + f'. USA country S02 {usa_country:.2f}; the region adds PRI and VIR. Report only, E37.')

# ---------------------------------------------------------------- H8 gap carry
def contrib_map(region):
    if region in primaries:
        return {region: 1.0}
    out = {}
    for a in assignments:
        if a['region'] == region and a['gdp_for_weight'] > 0:
            # P33 option C: a blended member carries each donor table at scale x weight / donor GDP
            for d, f in (((d_, w / donor_gdp[d_]) for d_, w in blend_of[a['code']]) if a['code'] in blend_of else ((a['donor'], 1.0),)):
                out[d] = out.get(d, 0.0) + a['scale'] * f
    return out


carry_fail = []
max_carry_rel = 0.0
ago_donor_regions = []
ago_sourced_regions = []
seller_side_regions = []
for region in region_order:
    cmap = contrib_map(region)
    T = tables[region]
    for kind, col in (('stock_gap', ST_C), ('grev_gap', GR_C)):
        got = float(T[:, col].sum())
        pred = 0.0
        for donor, scale in cmap.items():
            pred += scale * float(donor_T[donor][:, col].sum())
        rel = abs(got - pred) / max(abs(got), abs(pred), 1.0)
        if rel > max_carry_rel:
            max_carry_rel = rel
        if not rel_close(got, pred):
            carry_fail.append(f'{region} {kind} got {got:.6f} pred {pred:.6f}')
    ago_scale = cmap.get('AGO', 0.0)
    ago_sourced = ago_scale * float(donor_T['AGO'][:, GR_C].sum())
    total_grev = float(T[:, GR_C].sum())
    if region in targets and ago_scale > 0:
        ago_donor_regions.append(region)
    if region in targets and abs(ago_sourced) > 1e-8:
        ago_sourced_regions.append(region)
    if region in targets and abs(total_grev) > 1e-6 and ago_scale == 0:
        seller_side_regions.append(region)
ago_set_ok = set(ago_donor_regions) == set(ago_sourced_regions)
S.check('S05-H8',
        'Gap carry: for each region and gap kind, the carried total equals sum over members of '
        '(GDP_m / GDP_d) times the donor total (rel 1e-9). AGO\'s own gap, domestic products and the '
        'import side of the revised AGO table, is nonzero exactly in the constructed regions that use '
        'AGO as a donor. Seller-side residuals stay on the selling origin\'s own table so that origin\'s '
        'row identity holds; they are not AGO\'s gap spread onto a region that does not use AGO.',
        'hard',
        f'carry failures {len(carry_fail)}; max rel {max_carry_rel:.3e}; '
        f'AGO-donor regions {len(ago_donor_regions)} ({", ".join(ago_donor_regions) or "none"}); '
        f'AGO-sourced {len(ago_sourced_regions)}; seller-side-only constructed regions {len(seller_side_regions)}',
        '0 carry failures; AGO-donor set equals AGO-sourced set',
        not carry_fail and ago_set_ok,
        CIT_D3 + '; ' + CIT_ORDER,
        'AGO-donor regions: ' + (', '.join(ago_donor_regions) or 'none')
        + '. Seller-side-only: ' + (', '.join(seller_side_regions) or 'none')
        + '. The gap file records every origin that sells into the revised AGO_g column. '
        'Domestic rows take origin = donor. Import rows of the foreign origins are on the AGO table only.')

# ---------------------------------------------------------------- H9 negatives
if np.isnan(np.stack([tables[r] for r in region_order])).any():
    nan_n = int(sum(np.isnan(tables[r]).sum() for r in region_order))
else:
    nan_n = 0
va_donor_neg = []
for code in economies:
    if code == 'ROW':
        continue
    ei = eco_index[code]
    for si, name in enumerate(sec):
        if VA[ei, si] < -1e-9:
            va_donor_neg.append((code, name, float(VA[ei, si])))
va_expected = {('CYP', 'air'), ('ISL', 'pha')}
va_donor_bad = [f'{c}_{n}' for c, n, _v in va_donor_neg if (c, n) not in va_expected]
prod_neg = []
va_neg = []
tls_neg_regions = {}
for region in region_order:
    T = tables[region]
    cmap = contrib_map(region)
    for r in range(2 * n_s):
        for c in range(n_a):
            if T[r, c] < -1e-8:
                prod_neg.append(f'{region}:{row_names[r]}:{col_names[c]}={T[r, c]:.6f}')
        if r < n_s and T[r, X_C] < -1e-8:
            prod_neg.append(f'{region}:{row_names[r]}:X={T[r, X_C]:.6f}')
        if T[r, OUT_C] < -1e-8:
            prod_neg.append(f'{region}:{row_names[r]}:OUT={T[r, OUT_C]:.6f}')
    for si, name in enumerate(sec):
        if T[VA_R, si] < -1e-8:
            sources = [d for d, scale in cmap.items() if scale > 0 and donor_T[d][VA_R, si] < -1e-9]
            ok = sources and all((d, name) in va_expected for d in sources)
            va_neg.append((region, name, float(T[VA_R, si]), ','.join(sources) or 'none', ok))
    n_tls = int(np.sum(T[TLS_R, :n_a] < -1e-8))
    if n_tls:
        tls_neg_regions[region] = n_tls
va_bad = [f'{r}_{n}={v:.4f} from {src}' for r, n, v, src, ok in va_neg if not ok]
va_list = ', '.join(f'{r}_{n}={v:.4f} ({src})' for r, n, v, src, _ok in va_neg) or 'none'
tls_txt = ', '.join(f'{r}:{n}' for r, n in sorted(tls_neg_regions.items())) or 'none'
S.check('S05-H9',
        'No NaN. Negatives only where a donor has them: TLS subsidies, and VA in CYP air and ISL pha '
        '(ISL pha reaches XWE). Product, export and OUT negatives are counted. Listed by region.',
        'hard',
        f'NaN {nan_n}; product/X/OUT negatives {len(prod_neg)}; VA negatives {len(va_neg)} '
        f'of which not CYP air or ISL pha {len(va_bad)}; donor VA negatives {len(va_donor_neg)}; '
        f'regions with a TLS subsidy {len(tls_neg_regions)}',
        'NaN 0; product/X/OUT 0; VA only from CYP air and ISL pha; donor VA exactly those two cells',
        (nan_n == 0 and not prod_neg and not va_bad and not va_donor_bad
         and set((c, n) for c, n, _v in va_donor_neg) == va_expected),
        'S04-H8; ' + CIT_CH8,
        'VA cells: ' + va_list + '. TLS subsidy counts by region: ' + tls_txt
        + '. Donor VA: ' + ', '.join(f'{c}_{n}={v:.4f}' for c, n, v in va_donor_neg))

# ---------------------------------------------------------------- H10 B8 oil donor columns
oil_rows = []
oil_probs = []
for a in assignments:
    code = a['code']
    if not a['oil_donor']:
        if a['donor'] and code not in blend_of and member_T0[code] is not donor_T[a['donor']]:
            oil_probs.append(f'{code} has no oil donor but its table is not its donor table')
        if code in blend_of and not np.array_equal(member_T0[code], base_table(a, donor_T)):
            oil_probs.append(f'{code} has no oil donor but its table is not its donor blend')
        continue
    base, oil = base_table(a, donor_T), donor_T[a['oil_donor']]
    probs = OIL.check_swap(base, oil, member_T0[code], B06_J, n_s, n_a)
    probs += [f'path B: {p}' for p in OIL.check_swap(base_table(a, donor_B), donor_B[a['oil_donor']],
                                                     member_B0[code], B06_J, n_s, n_a)]
    oil_probs += [f'{code}: {p}' for p in probs]
    sh_base = OIL.cost_shares(base, B06_J, n_s, n_a)
    sh_new = OIL.cost_shares(member_T0[code], B06_J, n_s, n_a)
    scale_9d = a['gdp_for_weight'] / table_gdp(base)
    oil_rows.append(dict(
        region=a['region'], code=code, base_donor=a['donor'], oil_donor=a['oil_donor'],
        va_share_base=float(sh_base[VA_R]), va_share_new=float(sh_new[VA_R]),
        tls_share_base=float(sh_base[TLS_R]), tls_share_new=float(sh_new[TLS_R]),
        input_share_base=float(sh_base[:2 * n_s].sum()), input_share_new=float(sh_new[:2 * n_s].sum()),
        import_share_base=float(sh_base[n_s:2 * n_s].sum()), import_share_new=float(sh_new[n_s:2 * n_s].sum()),
        b06_out_base=scale_9d * float(base[OUT_R, B06_J]), b06_out_new=a['scale'] * float(member_T[code][OUT_R, B06_J]),
        scale_9d=scale_9d, scale=a['scale'], max_rel_out_change=oil_info[code]['max_rel_out_change'],
        problems=len(probs)))
cfg_missing = sorted(set(oil_donors) - {r['code'] for r in oil_rows})
S.check('S05-H10',
        'B8 oil and gas donors (David, 2026-10-24). For every member in config/s05/oil_donors.csv, on both code '
        'paths: the B06 column (oil and gas, split at S11) has the oil donor\'s cost shares (abs 1e-9); every '
        'other sector column keeps the 9D donor\'s cost shares; final demand, exports and both gap columns are '
        'the 9D donor\'s cells; every domestic product row keeps the 9D donor\'s residual; outputs are not '
        'negative. Every other member\'s table is its donor table. H5-H8 then apply to the swapped tables.',
        'hard',
        f'members switched {len(oil_rows)} of {len(oil_donors)} configured; problems {len(oil_probs)}',
        f'{len(oil_donors)} switched; 0 problems',
        not oil_probs and not cfg_missing and len(oil_rows) == len(oil_donors),
        'B8, David 2026-10-24 (card); our own choice, IMPROVEMENTS_LOG S05; ' + CIT_CH8_AIM,
        'Problems: ' + ('; '.join(oil_probs[:12]) or 'none') + '. Not switched: ' + (', '.join(cfg_missing) or 'none')
        + '. B06 VA share 9D donor -> oil donor: '
        + '; '.join(f"{r['code']} {r['base_donor']} {r['va_share_base']:.3f} -> {r['oil_donor']} {r['va_share_new']:.3f}"
                    for r in oil_rows))

# ---------------------------------------------------------------- reports
def region_donor_summary(region):
    rows = [a for a in assignments if a['region'] == region and a['gdp_for_weight'] > 0]
    by_d = {}
    for a in rows:
        for d, w in blend_of.get(a['code'], [(a['donor'], 1.0)]):
            by_d.setdefault(d, 0.0)
            by_d[d] += a['weight'] * w
    parts = [f'{d} {w:.3f}' for d, w in sorted(by_d.items(), key=lambda kv: -kv[1])]
    return '; '.join(parts)


s02_fill = [a for a in pos if 'DONOR-S02-GDPPC' in a['flags'].split('|')]
f1_fill = [a for a in s02_fill if 'F1-PER-CAPITA-FILL' in a['flags'].split('|')]
n_diff_a = sum(1 for a in pos if a['abc']['pr71_chosen'] != a['abc']['gtap15_gdppc'])
n_diff_b = sum(1 for a in pos if a['abc']['pr71_gtap9d'] != a['abc']['gtap15_gdppc'])
n_changed = 0
n_new = 0
for a in pos:
    if a['code'] == 'ISL':
        continue
    old = a['pr71_chosen']
    if old and old != a['donor']:
        n_changed += 1
    elif not old:
        n_new += 1
summary_lines = [f'{r}: {region_donor_summary(r)}' for r in targets]
S.check('S05-R1',
        'Donor and GDP weight for every S02 code in the 88 regions. DONOR-S02-GDPPC and zero-GDP codes '
        'are listed. Differences against pr71_chosen and pr71_gtap9d are counted. The full rows are '
        'donor_weights.csv, donor_rule_abc.csv and donor_changes_vs_pr71.csv.',
        'report',
        f'weighted {len(pos)}; zero-GDP {len(zero)}; differs from pr71_chosen {n_diff_a}; '
        f'differs from pr71_gtap9d {n_diff_b}; chosen_donor changed {n_changed}; '
        f'PR #71 had no donor and S05 assigns one {n_new}; S02-gdppc fills {len(s02_fill)}',
        'report',
        True,
        CIT_D3 + '; ' + CIT_CH8_AIM,
        'Per region: ' + ' | '.join(summary_lines)
        + '. S02-gdppc: ' + ', '.join(f"{a['code']}->{a['donor']}" for a in s02_fill)
        + '. F1 per-capita fills: ' + ', '.join(a['code'] for a in f1_fill)
        + '. Zero-GDP: ' + ', '.join(f"{a['code']} ({a['source']})" for a in zero))

# R2 ROW block. ISL's contribution is removed from the 88.
isl_assign = next(a for a in assignments if a['code'] == 'ISL')
isl_scale = isl_assign['scale']


def block_totals(T):
    p_i, g_i, i_i = agents.index('p'), agents.index('g'), agents.index('i')
    return {
        'GDP': table_gdp(T),
        'output': float(T[OUT_R, :n_s].sum()),
        'VA': float(T[VA_R, :n_a].sum()),
        'C': float(T[:2 * n_s, p_i].sum()),
        'G': float(T[:2 * n_s, g_i].sum()),
        'I': float(T[:2 * n_s, i_i].sum()),
        'X': float(T[:n_s, X_C].sum()),
        'M': float(T[n_s:2 * n_s, :n_a].sum()),
    }


sum88 = {k: 0.0 for k in ('GDP', 'output', 'VA', 'C', 'G', 'I', 'X', 'M')}
for region in targets:
    for k, v in block_totals(tables[region]).items():
        sum88[k] += v
isl_tot = block_totals(donor_T['ISL'])
ex_isl = {k: sum88[k] - isl_scale * isl_tot[k] for k in sum88}
row_tot = block_totals(donor_T['ROW'])
s02_ex_isl = sum(float(macro_reg.loc[r, 'GDP_musd']) for r in targets) - float(isl_assign['s02_gdp'])
row_lines = []
for k in ('GDP', 'output', 'VA', 'C', 'G', 'I', 'X', 'M'):
    ratio = ex_isl[k] / row_tot[k] - 1.0 if row_tot[k] else float('nan')
    row_lines.append(f'{k} {ex_isl[k]:,.0f} vs ROW {row_tot[k]:,.0f} ({ratio:+.2%})')
S.check('S05-R2',
        'The 88 regions minus ISL against the ICIO ROW block: GDP, output, VA, C, G, I, exports and imports. '
        'C, G and I are basic-price domestic plus imported use. Report only. The 88-to-ROW constraint is S13 (E41). '
        'GTAP has no ROW block.',
        'report',
        f'S02 GDP of the 88 minus ISL {s02_ex_isl:,.0f}; table GDP {ex_isl["GDP"]:,.0f}; '
        f'ROW GDP {row_tot["GDP"]:,.0f}; GDP gap {ex_isl["GDP"] / row_tot["GDP"] - 1:+.2%}',
        'report only',
        False,
        CIT_D3_FIT,
        '; '.join(row_lines) + '. ISL is removed at its S02 scale so XWE keeps its other members.')

# R3 AGO-derived regions
r3_bits = []
for region in ago_donor_regions:
    T = tables[region]
    grev_total = float(T[:, GR_C].sum())
    stock_total = float(T[:, ST_C].sum())
    ranked = []
    for si, name in enumerate(sec):
        outv = float(T[si, OUT_C])
        gap = float(T[si, GR_C])
        pct = gap / outv if outv else float('nan')
        ranked.append((abs(gap), name, gap, outv, pct))
    ranked.sort(reverse=True)
    top = '; '.join(f'{name} {gap:+,.1f} on OUT {outv:,.1f} ({pct:+.0%})'
                    for _a, name, gap, outv, pct in ranked[:5])
    scales = ', '.join(f"{a['code']} x {a['scale']:.5f}"
                       for a in assignments if a['region'] == region and a['donor'] == 'AGO')
    r3_bits.append(f'{region} grev {grev_total:,.1f} stock {stock_total:,.1f} ({scales}): {top}')
S.check('S05-R3',
        'Regions that use AGO as a donor: carried grev_gap and stock_gap, and the top domestic product rows '
        'as a percent of OUT. On a region whose only donor is AGO the percents are the AGO percents, because '
        'the ratio is scale-free. S13 clears the gap (E40). Nothing is spread or rebalanced here.',
        'report',
        f'{len(ago_donor_regions)} regions: ' + ' || '.join(r3_bits),
        'report only',
        False,
        CIT_D3 + '; ' + CIT_ORDER,
        ' || '.join(r3_bits))

# R4 and the USA file are filled with the other outputs below. The check is recorded after the numbers exist.
p_i, g_i = agents.index('p'), agents.index('g')
hea = sec.index('hea')
usa_T = tables['USA']
xna_T = tables['XNA']
hea_out = float(usa_T[hea, OUT_C])
hea_to_p = float(usa_T[hea, p_i]) / hea_out
hea_to_g = float(usa_T[hea, g_i]) / hea_out
xna_hea_out = float(xna_T[hea, OUT_C])
xna_hea_to_p = float(xna_T[hea, p_i]) / xna_hea_out if xna_hea_out else float('nan')
xna_hea_to_g = float(xna_T[hea, g_i]) / xna_hea_out if xna_hea_out else float('nan')
xna_rows = [a for a in assignments if a['region'] == 'XNA' and a['gdp_for_weight'] > 0]
xna_usa_weight = sum(a['weight'] for a in xna_rows if a['donor'] == 'USA')
bmu = next(a for a in xna_rows if a['code'] == 'BMU')
grl = next(a for a in xna_rows if a['code'] == 'GRL')
# Top 10 USA domestic-use cells by absolute dollars, as a share of that product's output, against XNA.
usa_cells = []
for si, name in enumerate(sec):
    outv = float(usa_T[si, OUT_C])
    for ai, ag in enumerate(agents):
        val = float(usa_T[si, ai])
        if outv == 0:
            continue
        usa_cells.append((abs(val), name, ag, val / outv, float(xna_T[si, ai]) / float(xna_T[si, OUT_C])
                          if xna_T[si, OUT_C] else float('nan'), val))
usa_cells.sort(reverse=True)
top_coef = usa_cells[:10]
max_share_gap = max(abs(us - xn) for _a, _n, _ag, us, xn, _v in top_coef)
pri_vir = float(macro_by_code.loc['PRI', 'GDP_musd']) + float(macro_by_code.loc['VIR', 'GDP_musd'])
S.check('S05-R4',
        'USA. The converted table equals the io_s04 USA aggregates (H5). No PRI or VIR member (E37). '
        'USA table GDP against S02 region USA, which includes PRI and VIR, is report only; S13-S14 absorb it. '
        'USA as a donor of XNA: the USA-derived weight, Bermuda and Greenland, and the top 10 domestic-use '
        'coefficients against XNA. Health sold to households and to government is the BEA convention seen at S04.',
        'report',
        f'USA table GDP {usa_table_gdp:,.2f}; S02 region {usa_s02:,.2f} ({usa_table_gdp / usa_s02 - 1:+.2%}); '
        f'PRI+VIR {pri_vir:,.1f}; XNA USA weight {xna_usa_weight:.3f}; BMU donor {bmu["donor"]} '
        f'weight {bmu["weight"]:.3f} scale {bmu["scale"]:.6f}; GRL donor {grl["donor"]} weight {grl["weight"]:.3f}; '
        f'hea to p {hea_to_p:.4f} to g {hea_to_g:.4f}; top-10 share gap vs XNA {max_share_gap:.3e}',
        'report only; USA columns unchanged; PRI and VIR not members',
        True,
        'E37; ' + CIT_D3_FIT,
        'USA H1 top 5: ' + usa_h1_txt + '. USA H6 top 5: ' + usa_h6_txt
        + '. Top 10 domestic coefficients (share of product OUT): '
        + '; '.join(f'{n}_{ag} USA {us:.4f} XNA {xn:.4f}' for _a, n, ag, us, xn, _v in top_coef))

# R6 scales and the 3x gate
scaled = [a for a in pos if a['scale']]
scaled_sorted = sorted(scaled, key=lambda a: a['scale'], reverse=True)
gap_members = [a for a in pos if 'gdppc_gap' in a['flags'].split('|') and a['ratio'] is not None
               and abs(math.log(a['ratio'])) > math.log(GDPPC_RATIO_MAX)]
# gdppc_gap may also be a carried PR #71 token. R6 lists members whose S05 ratio is past 3x.
s05_gap = [a for a in pos if a['ratio'] is not None and abs(math.log(a['ratio'])) > math.log(GDPPC_RATIO_MAX)]
top_scales = '; '.join(f"{a['code']}->{a['donor']} scale {a['scale']:.4f} (GDP {a['s02_gdp']:.0f} / {a['donor_gdp']:.0f})"
                       for a in scaled_sorted[:8])
gap_txt = ', '.join(f"{a['code']}->{a['donor']} x {a['ratio']:.2f}" for a in
                    sorted(s05_gap, key=lambda a: abs(math.log(a['ratio'])), reverse=True))
S.check('S05-R6',
        'Largest scale factors GDP_m / GDP_d, and members whose S05 donor is past PR #71\'s 3x GDP per capita '
        'gate. The gdppc_gap flag is carried. The stage does not change the donor.',
        'report',
        f'max scale {scaled_sorted[0]["scale"]:.4f} ({scaled_sorted[0]["code"]}->{scaled_sorted[0]["donor"]}); '
        f'members past 3x {len(s05_gap)}',
        'report only; do not act',
        False,
        'PR #71 GDPPC_RATIO_MAX = 3; ' + CIT_D3,
        'Largest scales: ' + top_scales + '. Past 3x: ' + (gap_txt or 'none'))

# ---------------------------------------------------------------- flags and ledger
S.flag('DONOR-RULE', RULE,
       f"{rule_row['decided_by']} {rule_row['decided_at']}. {rule_row['note']}",
       'no', 'GTAP12-9D-D3-p3', CIT_D3 + '; ' + CIT_D2)
S.flag('COUNT-80', 'non-ICIO singles',
       f'S01 has {n_single_no} non-ICIO single regions and {n_composite} composites, 88 tables. '
       'READINESS says 81 non-ICIO economies. That is an older count.',
       'no', 'E41', 'S01 regions.csv')
S.flag('E43-APT-ORDER', 'S05 before S06',
       'Log only. ch.8 §8.3 lists agricultural production targeting Second (p.3) and composite tables Finally (p.4). '
       'ch.9A p.2 targets all primary regions and does not apply APT to composite regions. '
       'These 88 tables are built from untargeted ICIO donors. S13 reconciles agricultural coefficients. '
       'Swapping S05 and S06 is the GTAP-order alternative. No cell was changed for this note.',
       'no', 'E43', CIT_ORDER + '; ' + CIT_APT)
S.flag('NO-PRI-VIR', 'USA',
       f'No PRI or VIR table. They are not members of an S05 region. PRI GDP '
       f'{float(macro_by_code.loc["PRI", "GDP_musd"]):.1f} and VIR GDP '
       f'{float(macro_by_code.loc["VIR", "GDP_musd"]):.1f} stay in S02 USA. E37.',
       'no', 'E37', 'S05 handoff §7')
S.flag('ISL-IN-XWE', 'ISL',
       f'ISL keeps its own ICIO table inside XWE, scaled to S02 GDP {isl_assign["s02_gdp"]:.2f} '
       f'(ICIO GDP {donor_gdp["ISL"]:.2f}).',
       'no', 'GTAP12-9D-D3-p3', 'S01 XWE partly: ISL')
S.flag('DONOR-S02-GDPPC', ' '.join(a['code'] for a in s02_fill),
       'No PR #71 income row. Nearest donor by S02 GDP per capita (market USD) inside the rule pool. '
       + ('; '.join(f"{a['code']}->{a['donor']} source {a['source']}" for a in s02_fill)),
       'no', 'GTAP12-9D-D3-p3', CIT_D3)
S.flag('ZERO-GDP-MEMBER', ' '.join(a['code'] for a in zero),
       'Weight 0, no donor. ' + '; '.join(f"{a['code']}: {a['source']}" for a in zero),
       'no', 'GTAP12-9D-D3-p3', CIT_CH7_ZERO)
S.flag('AGO-GREV-CARRIED', ' '.join(ago_donor_regions),
       'GTAP 12 ch.9D §D.3 p.3 applied as written; the Angola G-revision gap travels with the donor table to S13. '
       'Regions: ' + ', '.join(ago_donor_regions) + '.',
       'no', 'GTAP12-9D-D3-p3', CIT_D3 + '; ' + CIT_ORDER)
S.flag('GDPPC-GAP', ' '.join(a['code'] for a in s05_gap),
       f'{len(s05_gap)} members are past the 3x GDP per capita gate on the S05 donor. Flag carried, no action. '
       + gap_txt,
       'no', 'PR71-GDPPC-RATIO-MAX', CIT_D3)
for code, rec in sorted(oil_flag.items()):
    got = next((a['donor'] for a in assignments if a['code'] == code), '')
    bits = [f"{rec['decided_by'].strip()} {rec['decided_at'].strip()}.",
            f"Donor at S05 is {got or 'none'}.",
            rec['reason'].strip(), rec['evidence'].strip()]
    note = rec['note'].strip()
    if note and note not in bits:
        bits.append(note)
    if rec['flag'] == OIL.FLAG_RESOLVED:
        bits.append(f"Resolved by {rec['resolved_by']} {rec['resolved_at']}: {rec['resolution']} "
                    f"B06 column from {oil_donors[code]['oil_donor']}.")
        rule = 'B8-oil-donor'
    else:
        rule = 'no-oil-donor-override'
    S.flag(rec['flag'].strip(), code, ' '.join(bits), 'no', rule, 'config/s05/oil_check_codes.csv')
S.flag('OIL-DONOR-B8', ' '.join(r['code'] for r in oil_rows),
       'David 2026-10-24 (card): the B06 column (oil and gas) of these members takes an ICIO oil producer\'s '
       'cost structure; every other column keeps the 9D donor. Departure from the literal GTAP 9D rule '
       '(IMPROVEMENTS_LOG S05). ' + '; '.join(f"{r['code']}: {r['base_donor']} -> {r['oil_donor']}" for r in oil_rows),
       'no', 'B8-oil-donor', 'config/s05/oil_donors.csv')
for a in assignments:
    S.adjust(a['region'], a['code'], fmt_num(a['s02_gdp'], 4), a['donor'],
             'GTAP12-9D-D3-p3', CIT_D3, a['flags'])
# beta v4 P37 (donor_va_sections; default off): the group factors per member (report)
_vs_bound = sorted(c for c, v in va_sec.items() if v['bounded'])
_vs_neg = sorted(c for c, v in va_sec.items() if v['negative'] or v['no_room'])
_vs_noama = sorted(a['code'] for a in assignments if VA_SEC != 'off' and a['donor'] and a['code'] not in ama
                   and (VA_SEC_MEMBERS is None or a['code'] in VA_SEC_MEMBERS))
# beta v5 S1: every member named in the scope is a donor-built member with an AMA 2022 row, and was moved
_vs_scope_bad = sorted(VA_SEC_MEMBERS - set(va_sec)) if (VA_SEC != 'off' and VA_SEC_MEMBERS) else []
S.check('S05-Hvascope', 'Beta v5 S1 (donor_va_sections parameter): every member named in the scope is donor-built, has a UN AMA 2022 row and '
        'was moved; no other member was moved', 'hard', len(_vs_scope_bad) + (len(set(va_sec) - VA_SEC_MEMBERS) if VA_SEC_MEMBERS else 0), 0,
        not _vs_scope_bad and (not VA_SEC_MEMBERS or set(va_sec) <= VA_SEC_MEMBERS), 'donor_va_sections (s05_composite/va_sections.py)',
        f"scope {' '.join(sorted(VA_SEC_MEMBERS)) if VA_SEC_MEMBERS else ('all donor-built members' if VA_SEC != 'off' else 'off')}; moved "
        + (' '.join(sorted(va_sec)) or 'none') + ('; not moved: ' + ' '.join(_vs_scope_bad) if _vs_scope_bad else ''))
S.check('S05-Rvasec', 'Donor VA by section group (config/s05/donor_guards.csv donor_va_sections; beta v4 P37; default off; labelled '
        'departure, GTAP 12 ch.9D §D.3 p.3 adjusts composites only in the FIT and ch.9A p.2 does not target them): members '
        'moved to UN AMA 2022 VA shares by ISIC group, factors bounded to [1/' + f'{VS.K_CAP:g}, {VS.K_CAP:g}]', 'report',
        f'{len(va_sec)} members; bound hit {len(_vs_bound)}; members with a sector held at factor 1 (its row cannot take the '
        f'cut) or a gap sent to exports {len(_vs_neg)}; no AMA 2022 row {len(_vs_noama)}', 'n/a', True,
        'donor_va_sections (s05_composite/va_sections.py)',
        f'donor_va_sections {VA_SEC}' + ('; ' + '; '.join(
            f"{c} " + ' '.join(f'{g} {v["k"][g]:.2f}' for g in VS.GROUPS) for c, v in sorted(va_sec.items()))
            + '; bound: ' + (', '.join(_vs_bound) or 'none') + '; held at 1 or gap to exports: '
            + (', '.join(f"{c} ({' '.join(va_sec[c]['negative'] + va_sec[c]['no_room'])})" for c in _vs_neg) or 'none')
            + '; no AMA row (donor pattern kept): ' + (', '.join(_vs_noama) or 'none') if va_sec else ''))
if va_sec:
    S.check('S05-Hvasec', 'Donor VA by section group (P37, when on), on both code paths: each sector column\'s TLS, VA, OUT and '
            'input total are the pre-P37 column times its group factor (cost shares kept), each domestic product row keeps '
            'its residual, and no use or export cell turns negative (rows short of sales move use to imports)', 'hard',
            f'{len(va_sec)} members; problems {len(va_probs)}', '0 problems', not va_probs,
            'donor_va_sections (s05_composite/va_sections.py)', '; '.join(va_probs[:12]) or 'none')
    S.flag('DONOR-VA-SECTIONS', ' '.join(sorted(va_sec)),
           f'beta v4 P37 donor_va_sections {VA_SEC}: sector VA moved to UN AMA 2022 VA by ISIC group before the GDP scaling; '
           'labelled departure from GTAP 12 ch.9D §D.3 p.3 (FIT only) and ch.9A p.2 (no APT for composites).',
           'no', 'P37-donor-va-sections', 'config/s05/donor_guards.csv; data/unsd_ama/gva_gdp_current_usd.csv')

# ---------------------------------------------------------------- write outputs
S.log('writing outputs')
weight_rows = []
for a in assignments:
    weight_rows.append((
        a['region'], a['code'], a['geo'], a['pool'],
        fmt_num(a['s02_gdp'], 6), fmt_num(a['s02_pop'], 2),
        fmt_num(a['gdppc'], 6) if a['gdppc'] is not None else '',
        a['income_concept'], a['donor'], a['donor_rule'], a['donor_basis'],
        fmt_num(a['weight'], 12),
        fmt_num(a['donor_gdp'], 6) if a['donor_gdp'] is not None else '',
        fmt_num(a['scale'], 12) if a['donor'] else '',
        a['flags'], a['oil_donor'],
        ';'.join(f'{d}:{w:.6f}' for d, w in blend_of.get(a['code'], []))))
S.write('donor_weights.csv', weight_rows,
        ['region', 'code', 'geo', 'pool', 's02_gdp', 's02_pop', 'gdppc', 'income_concept',
         'donor', 'donor_rule', 'donor_basis', 'weight', 'donor_gdp', 'scale', 'flags', 'oil_donor', 'donor_blend'])

oil_cols = ['region', 'code', 'base_donor', 'oil_donor', 'va_share_base', 'va_share_new', 'tls_share_base',
            'tls_share_new', 'input_share_base', 'input_share_new', 'import_share_base', 'import_share_new',
            'b06_out_base', 'b06_out_new', 'scale_9d', 'scale', 'max_rel_out_change', 'problems']
S.write('oil_donor_columns.csv',
        [tuple(r[c] if isinstance(r[c], str) or c == 'problems' else fmt_num(r[c], 10) for c in oil_cols)
         for r in oil_rows], oil_cols)

abc_rows = []
for a in assignments:
    abc_rows.append((a['region'], a['code'], a['geo'], fmt_num(a['s02_gdp'], 4),
                     a['abc'].get('pr71_chosen', ''), a['abc'].get('pr71_gtap9d', ''),
                     a['abc'].get('gtap15_gdppc', ''), a['donor'],
                     'yes' if a['s02_gdp'] > 0 and a['abc'].get('pr71_chosen', '') != a['abc'].get('gtap15_gdppc', '') else 'no',
                     'yes' if a['s02_gdp'] > 0 and a['abc'].get('pr71_gtap9d', '') != a['abc'].get('gtap15_gdppc', '') else 'no'))
if va_sec:
    S.write('donor_va_sections.csv',
            [(c, a_['region'], g, fmt_num(v['info'][g][0], 6), fmt_num(v['info'][g][1], 6), fmt_num(v['info'][g][2], 6),
              fmt_num(v['k'][g], 6)) for c, v in sorted(va_sec.items()) for a_ in [_by_code[c]] for g in VS.GROUPS],
            ['code', 'region', 'group', 'donor_va_share', 'ama_va_share', 'factor_raw', 'factor'])
S.write('donor_rule_abc.csv', abc_rows,
        ['region', 'code', 'geo', 's02_gdp', 'donor_pr71_chosen', 'donor_pr71_gtap9d',
         'donor_gtap15_gdppc', 's05_donor', 'differs_from_pr71_chosen', 'differs_from_pr71_gtap9d'])

change_rows = []
for a in pos:
    if a['code'] == 'ISL':
        continue
    if a['pr71_chosen'] and a['pr71_chosen'] != a['donor']:
        kind = 'changed'
    elif not a['pr71_chosen']:
        kind = 'newly_assigned'
    else:
        continue
    change_rows.append((a['region'], a['code'], a['geo'], a['pool'], a['pool_pr71'],
                        a['pr71_chosen'], a['pr71_gtap9d'], a['donor'], kind,
                        a['income_concept'], fmt_num(a['s02_gdp'], 4)))
S.write('donor_changes_vs_pr71.csv', change_rows,
        ['region', 'code', 'geo', 'pool_s05', 'pool_pr71', 'pr71_chosen_donor', 'pr71_gtap9d_donor',
         's05_donor', 'change_type', 'income_concept', 's02_gdp_musd'])

gap_rows = []
for region in region_order:
    cmap = contrib_map(region)
    for donor, scale in sorted(cmap.items()):
        if scale == 0:
            continue
        src = donor_T[donor]
        for ri, rname in enumerate(row_names):
            for kind, col in (('stock_gap', ST_C), ('grev_gap', GR_C)):
                cell = float(src[ri, col])
                if cell == 0.0:
                    continue
                carried = scale * cell
                gap_rows.append((region, rname, kind, donor, fmt_num(scale, 12),
                                 fmt_num(cell, 6), fmt_num(carried, 6)))
S.write('carried_gaps.csv', gap_rows,
        ['region', 'row', 'gap_kind', 'donor', 'scale_sum', 'donor_cell_musd', 'carried_musd'])

row_cmp_rows = []
for k in ('GDP', 'output', 'VA', 'C', 'G', 'I', 'X', 'M'):
    ratio = ex_isl[k] / row_tot[k] if row_tot[k] else float('nan')
    note = 'basic prices, domestic plus imported use' if k in ('C', 'G', 'I') else ''
    if k == 'GDP':
        note = f'S02 GDP of the 88 minus ISL country GDP is {s02_ex_isl:.4f}'
    if k == 'M':
        note = 'sum of import-row agent columns'
    if k == 'X':
        note = 'sum of domestic-row export column'
    row_cmp_rows.append((k, fmt_num(ex_isl[k], 4), fmt_num(row_tot[k], 4),
                         fmt_num(ratio, 6), fmt_num(ratio - 1.0, 6), note))
S.write('row_comparison.csv', row_cmp_rows,
        ['item', 's05_ex_isl', 'icio_row_block', 'ratio', 'gap', 'note'])

usa_rows = [
    ('gdp', 'usa_table', fmt_num(usa_table_gdp, 4), 'VA + TLS + TLS on INVNT, io_s04 USA, unscaled'),
    ('gdp', 's02_region', fmt_num(usa_s02, 4), 'S02 USA region, country + PRI + VIR'),
    ('gdp', 's02_country', fmt_num(usa_country, 4), 'S02 USA country row'),
    ('gdp', 'pri_plus_vir', fmt_num(pri_vir, 4), 'not given a table; E37'),
    ('gdp', 'gap', fmt_num(usa_table_gdp / usa_s02 - 1.0, 6), 'table / S02 region - 1; S13-S14 absorb it'),
    ('members', 'pri_vir_donors', '0', 'H2; these codes are in region USA, which is not an S05 target'),
    ('xna', 'usa_weight', fmt_num(xna_usa_weight, 6), 'share of XNA S02 GDP whose donor is USA'),
    ('xna', 'bmu_donor', bmu['donor'], f"weight {bmu['weight']:.6f}; scale {bmu['scale']:.8f}; GDP {bmu['s02_gdp']:.4f}"),
    ('xna', 'grl_donor', grl['donor'], f"weight {grl['weight']:.6f}; scale {grl['scale']:.8f}; GDP {grl['s02_gdp']:.4f}"),
    ('hea', 'usa_share_to_p', fmt_num(hea_to_p, 6), 'domestic hea sold to p, over hea output'),
    ('hea', 'usa_share_to_g', fmt_num(hea_to_g, 6), 'domestic hea sold to g, over hea output'),
    ('hea', 'xna_share_to_p', fmt_num(xna_hea_to_p, 6), 'same coefficient in XNA'),
    ('hea', 'xna_share_to_g', fmt_num(xna_hea_to_g, 6), 'same coefficient in XNA'),
    ('hea', 'convention', 'BEA',
     'Health is mostly in household consumption, not government. S04 saw the same pattern. Report only.'),
]
for rank, (_a, name, ag, us, xn, val) in enumerate(top_coef, 1):
    usa_rows.append((f'coefficient_{rank:02d}', f'{name}_{ag}', fmt_num(us, 8),
                     f'USA share of product OUT; XNA share {xn:.8f}; USA USD m {val:.4f}'))
for rank, (mx, name, sales, costs, outv, dso, dco) in enumerate(usa_h1[:5], 1):
    usa_rows.append((f'h1_residual_{rank}', name, fmt_num(mx, 6),
                     f'sales {sales:.4f}; costs {costs:.4f}; OUT {outv:.4f}; '
                     f'sales-OUT {dso:+.4f}; costs-OUT {dco:+.4f}'))
for rank, (mx, name, drow, dcol, outv) in enumerate(usa_h6[:5], 1):
    usa_rows.append((f'h6_residual_{rank}', name, fmt_num(mx, 6),
                     f'row residual {drow:+.4f}; column residual {dcol:+.4f}; OUT {outv:.4f}'))
S.write('usa_scrutiny_s05.csv', usa_rows, ['item', 'key', 'value', 'note'])

# Deterministic gzip. mtime 0 and an empty filename keep the header free of the clock and the path.
S.log('writing io_s05.csv.gz')
gz_path = S.out + '/io_s05.csv.gz'
with open(gz_path, 'wb') as raw:
    with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0, compresslevel=9) as gz:
        gz.write(('region,row,' + ','.join(col_names) + '\n').encode())
        for region in region_order:
            T = tables[region]
            for ri, rname in enumerate(row_names):
                vals = ','.join(fmt_cell(v) for v in T[ri])
                gz.write(f'{region},{rname},{vals}\n'.encode())
S.log(f'output io_s05.csv.gz bytes {os.path.getsize(gz_path)}')

too_big = []
for fn in os.listdir(S.out):
    sz = os.path.getsize(S.out + '/' + fn)
    if sz >= 50 * 1024 * 1024:
        too_big.append(f'{fn} {sz}')
if too_big:
    raise SystemExit('output file at or over 50 MB: ' + ' '.join(too_big))

S.log(f'rule {RULE}; AGO-donor regions {",".join(ago_donor_regions) or "none"}; '
      f'changed vs PR #71 chosen {n_changed}; newly assigned {n_new}')
S.finish()
