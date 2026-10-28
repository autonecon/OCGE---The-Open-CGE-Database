"""Preference membership and the preferential rate of one line (choices preference_groups,
preference_group_members, uk_continuity, agreement_families, preference_year_fallback,
us_gsp_lapse, us_gsp_single_country, lapse_cutoff, cptpp_membership, rcep_membership,
eu_gsp_armenia, eu_gsp_graduation, cambodia_eba_withdrawal, khm_acfta_partner).

ch.11B: the applied rate of a line is the lowest of MFN and every preference the exporter
can use. WITS gives one HS6 simple average per agreement, so the preferential rate of an
HS6 is the minimum over agreements (hs6_min_of_simple_averages). Within one agreement
family the latest line is used; across families the minimum wins.

Every member code goes through the one CodeMap, so PSE members are PAL, the region that
holds Palestinian trade, and EUN on a member list is the EU27.
"""
import csv
import re
from collections import defaultdict

from .config import ConfigError, read_table
from .overrides import CPTPP_DROP, RCEP_DROP, US_GSP_CODES, gsp_banned, is_us_gsp

EU27 = frozenset({
    'AUT', 'BEL', 'BGR', 'HRV', 'CYP', 'CZE', 'DNK', 'EST', 'FIN', 'FRA', 'DEU', 'GRC',
    'HUN', 'IRL', 'ITA', 'LVA', 'LTU', 'LUX', 'MLT', 'NLD', 'POL', 'PRT', 'ROU', 'SVK',
    'SVN', 'ESP', 'SWE',
})
# UK left the EU on 2020-01-31. WITS group lists that are EU lists still carry GBR. A list is
# an EU list when its name says so, or when it holds 14+ EU members and nothing outside the EU
# area (preference_groups).
EU_LIST_NAME = re.compile(
    r'european union|\beuropean communit(?:y|ies)\b|\beuropean economic area\b|\bEEA\b|\bEU[-\s]?(15|25|27|28)\b',
    re.IGNORECASE)
ALLOWED_WITH_EU = frozenset({
    'EUN', 'CHE', 'ISL', 'NOR', 'LIE', 'AND', 'SMR', 'MCO',
    'GUF', 'GLP', 'MTQ', 'REU', 'MYT', 'SPM', 'MAF',
    'FRO', 'GRL', 'GIB', 'SJM', 'VAT',
})
# lapse_cutoff: a lapse dated after 1 Jan 2022 does not apply to the whole of 2022.
LAPSE_CUTOFF = '2022-01-01'
# Numeric partner codes with a WITS country row and no schedule region (Faroe Islands, Western
# Sahara). Not group codes; left off member lists and logged when they are a partner.
UNMAPPED_NUMERIC_OK = {'234', '732'}


def _expand(isos):
    out = set()
    for iso in isos:
        if iso == 'EUN':
            out |= EU27
        else:
            out.add(iso)
    return out


# ---------------------------------------------------------------- group membership

def live_groups(beneficiaries_path, codemap):
    """Group code -> (name, members) from the WITS beneficiary table, with the UK rule. Raw labels."""
    raw = defaultdict(lambda: ['', []])
    with open(beneficiaries_path, newline='', encoding='utf-8') as fh:
        for row in csv.DictReader(fh):
            code = (row.get('RegionCode') or '').strip()
            raw[code][0] = (row.get('RegionName') or '').strip()
            raw[code][1].append((row.get('Partner') or '').strip())
    groups, uk_removed = {}, set()
    for code, (name, nums) in raw.items():
        members = {codemap.from_m49(n) for n in nums if n.isdigit() and str(int(n)) not in UNMAPPED_NUMERIC_OK} - {''}
        if 'GBR' in members:
            others = members - EU27 - {'GBR'}
            if EU_LIST_NAME.search(name) or (len(members & EU27) >= 14 and others <= ALLOWED_WITH_EU):
                members.discard('GBR')
                uk_removed.add(code)
        groups[code] = (name, frozenset(members))
    return groups, uk_removed


def load_groups(beneficiaries_path, codemap, config_path=None):
    """The decided group table (preference_group_members.csv), checked row by row against WITS.

    Returns (groups, uk_removed, problems). groups: code -> (name, frozenset of project ISOs).
    A beneficiaries_full row must equal the live WITS list; a trains_xls row is a group the
    full table does not carry. Any mismatch is returned as a problem and stops the stage.
    """
    rows = read_table('preference_group_members.csv',
                      ('group_code', 'table', 'group_name', 'members', 'n_members', 'uk_removed',
                       'source', 'decided_by', 'decided_at'), min_rows=100, path=config_path)
    live, live_uk = live_groups(beneficiaries_path, codemap)
    groups, uk_removed, problems = {}, set(), []
    for row in rows:
        code = row['group_code']
        if not code or code in groups:
            raise ConfigError(f'preference_group_members.csv: blank or duplicate group {code!r}')
        if not row['decided_by'] or not row['decided_at'] or not row['source']:
            raise ConfigError(f'preference_group_members.csv {code}: decided_by, decided_at or source is blank')
        if row['table'] not in ('beneficiaries_full', 'trains_xls'):
            raise ConfigError(f'preference_group_members.csv {code}: table {row["table"]!r}')
        listed = row['members'].split()
        if int(row['n_members'] or -1) != len(set(listed)):
            raise ConfigError(f'preference_group_members.csv {code}: n_members does not match the list')
        members = frozenset(codemap.iso(m) for m in listed)
        groups[code] = (row['group_name'], members)
        if row['uk_removed'] == 'yes':
            uk_removed.add(code)
        if row['table'] == 'beneficiaries_full':
            slot = live.get(code)
            if slot is None:
                problems.append(f'{code} not in the WITS table')
            elif slot != (row['group_name'], members):
                problems.append(f'{code} differs from the WITS table')
        elif code in live:
            problems.append(f'{code} is marked trains_xls but is in the WITS table')
    missing = sorted(set(live) - set(groups))
    if missing:
        problems.append('WITS groups with no config row: ' + ' '.join(missing[:8]))
    if uk_removed != live_uk:
        problems.append('uk_removed differs from the UK rule: ' + ' '.join(sorted(uk_removed ^ live_uk)[:8]))
    return groups, uk_removed, problems


def load_remap(codemap, path=None):
    """(importer, partner code, year) -> (members, name). preference_partner_remap.csv."""
    out = {}
    for row in read_table('preference_partner_remap.csv',
                          ('importer', 'partner_code', 'year', 'members', 'agreement_name', 'source',
                           'decided_by', 'decided_at'), path=path):
        if not row['year'].isdigit() or not row['members'] or not row['decided_by'] or not row['decided_at']:
            raise ConfigError(f'preference_partner_remap.csv row {row}')
        key = (codemap.iso(row['importer']), row['partner_code'], int(row['year']))
        out[key] = (frozenset(codemap.iso(m) for m in row['members'].split()), row['agreement_name'])
    return out


def load_national_agreements(codemap, path=None):
    """mys_preference_schedules: agreement -> (partner code, members in 2022). mys_national_agreements.csv."""
    out = {}
    for row in read_table('mys_national_agreements.csv', ('agreement', 'partner_code', 'members_2022',
                                                          'entry_into_force_for_mys', 'source', 'decided_by',
                                                          'decided_at'), min_rows=1, path=path):
        if not row['agreement'] or not row['partner_code'] or not row['members_2022'] or row['agreement'] in out \
                or not row['decided_by'] or not row['decided_at'] or not row['entry_into_force_for_mys'] <= '2022-12-31':
            raise ConfigError(f'mys_national_agreements.csv row {row}')
        members = frozenset(codemap.iso(m) for m in row['members_2022'].split())
        if not all(members):
            raise ConfigError(f'mys_national_agreements.csv members do not map: {row["members_2022"]}')
        out[row['agreement']] = (row['partner_code'], members)
    return out


def load_families(path=None):
    """Partner code -> family id (agreement_families.csv). An unlisted code is its own family."""
    fam = {}
    for row in read_table('agreement_families.csv', ('partner_code', 'family_id', 'source'), min_rows=10, path=path):
        if not row['partner_code'] or not row['family_id'] or row['partner_code'] in fam:
            raise ConfigError(f'agreement_families.csv row {row}')
        fam[row['partner_code']] = row['family_id']
    return fam


def load_uk_continuity(path=None):
    """Importers with a UK continuity agreement in force in 2022 (status applied)."""
    rows = read_table('uk_continuity.csv', ('importer', 'agreement_name', 'entry_into_force', 'source_url',
                                            'decided_by', 'decided_on', 'status'), path=path)
    applied = set()
    for row in rows:
        if row['status'] not in ('applied', 'no_agreement', 'unconfirmed'):
            raise ConfigError(f'uk_continuity.csv {row["importer"]}: status {row["status"]!r}')
        if not row['decided_by'] or not row['decided_on'] or not row['source_url']:
            raise ConfigError(f'uk_continuity.csv {row["importer"]}: decision or source is blank')
        if row['status'] == 'applied':
            if not row['agreement_name'] or not row['entry_into_force'] or row['entry_into_force'] > '2022-12-31':
                raise ConfigError(f'uk_continuity.csv {row["importer"]}: applied but not in force in 2022')
            applied.add(row['importer'])
    return applied


def load_lapses(codemap, path=None):
    rows = read_table('preference_lapses.csv', ('importer', 'scheme', 'group_code', 'beneficiary', 'lapsed_on',
                                                'status', 'source_url'), path=path)
    for row in rows:
        row['importer'] = codemap.iso(row['importer'])
        if row['beneficiary'] not in ('', '*'):
            row['beneficiary'] = codemap.iso(row['beneficiary'])
    return rows


# ---------------------------------------------------------------- 2022 membership rules

def adjust_members(imp, code, name, members):
    """cptpp_membership, rcep_membership, eu_gsp_armenia, us_gsp_lapse. Returns a new set."""
    out = set(members)
    blob = name.lower()
    if 'cptpp' in blob:
        out -= CPTPP_DROP
    if 'rcep' in blob:
        drop = set(RCEP_DROP)
        if imp == 'CHN':
            drop.discard('MMR')
        out -= drop
        if (imp, code) in {('BRN', '01D'), ('SGP', '01D')}:
            out.add('NZL')
    if (imp in EU27 or imp == 'EUN') and code in ('01T', '01W'):
        out.discard('ARM')
    if is_us_gsp(imp, code, name):
        return set()
    out.discard(imp)
    return out


def _lapse_in_force(rec):
    return rec['status'] == 'lapsed' and bool(rec['lapsed_on']) and rec['lapsed_on'] <= LAPSE_CUTOFF


def _lapse_matches(agr, rec):
    if rec['group_code']:
        return agr['partner'] == rec['group_code']
    scheme = rec['scheme'].lower()
    return bool(scheme) and scheme in agr['name'].lower()


def apply_lapses(agreements, lapses):
    applied, skipped = [], []
    for rec in lapses:
        if rec['status'] != 'lapsed' or not rec['importer']:
            continue
        if not _lapse_in_force(rec):
            skipped.append((rec['importer'], rec['group_code'] or rec['scheme'], rec['beneficiary'], rec['lapsed_on']))
            continue
        for agr in agreements.get(rec['importer'], []):
            if not _lapse_matches(agr, rec):
                continue
            ben = rec['beneficiary']
            if ben in ('', '*'):
                if agr['members']:
                    applied.append((rec['importer'], agr['partner'], '*', len(agr['members'])))
                    agr['members'].clear()
            elif ben in agr['members']:
                agr['members'].discard(ben)
                applied.append((rec['importer'], agr['partner'], ben, 1))
    for iso in list(agreements):
        agreements[iso] = [a for a in agreements[iso] if a['members']]
    return applied, skipped


def _excluded_groups(agr):
    named = set()
    for marks in agr['excluded'].values():
        named |= marks
    return named


def lapsed_scheme_row(iso, agr, lapses):
    """us_gsp_single_country: a 2017-2021 single-country row whose ExcludedFrom names a lapsed group."""
    if agr['year'] > 2021 or len(agr['members']) != 1:
        return False
    named = _excluded_groups(agr)
    if not named:
        return False
    if iso == 'USA' and named & US_GSP_CODES:
        return True
    member = next(iter(agr['members']))
    for rec in lapses:
        if not _lapse_in_force(rec) or rec['importer'] not in ('', iso):
            continue
        if rec['group_code'] and rec['group_code'] in named and rec['beneficiary'] in ('', '*', member):
            return True
    return False


# ---------------------------------------------------------------- state

def build_state(merged, groups, uk_removed, uk_applied, lapses, families, remap, codemap):
    """Agreements per importer, the exporter cover, and the ExcludedFrom index.

    merged: {(iso, partner code, nomen): record} from sources.load_preferences.
    """
    agreements = defaultdict(list)
    log = defaultdict(list)
    for rec in merged.values():
        iso, code = rec['iso'], rec['partner']
        if rec.get('members'):                          # national schedule: members set by its agreement row
            name, members = rec['agreement'], set(rec['members'])
        elif code in groups:
            name, members = groups[code][0], set(groups[code][1])
        elif code.isdigit():
            member = '' if str(int(code)) in UNMAPPED_NUMERIC_OK else codemap.from_m49(code)
            if not member:
                log['unmapped_numeric'].append((iso, code, rec['year']))
                continue
            name, members = code, {member}
        else:
            log['unknown_group'].append((iso, code, rec['year']))
            continue
        override = remap.get((iso, code, rec['year']))
        if override:
            members = set(override[0])
            name = override[1] or name
            log['remap'].append((iso, code, rec['year'], ' '.join(sorted(members))))
        members = _expand(adjust_members(iso, code, name, members))
        members.discard(iso)
        if iso in uk_applied and code in uk_removed:
            members.add('GBR')
            log['uk_restored'].append((iso, code, rec['year']))
        if not members:
            continue
        agreements[iso].append({
            'iso': iso, 'partner': code, 'name': name, 'year': rec['year'], 'nomen': rec['nomen'],
            'rates': rec['rates'], 'rate_year': rec['rate_year'], 'members': members,
            'excluded': rec['excluded'], 'family': families.get(code, code),
        })
    log['lapses_applied'], log['lapses_skipped'] = apply_lapses(agreements, lapses)
    for iso, agrs in list(agreements.items()):
        kept = []
        for agr in agrs:
            if lapsed_scheme_row(iso, agr, lapses):
                log['single_country_dropped'].append((iso, agr['partner'], agr['year']))
            else:
                kept.append(agr)
        agreements[iso] = kept
    # The EU files are reported by EUN; each member state applies them.
    eun = agreements.pop('EUN', [])
    for iso in EU27:
        agreements[iso] = agreements.get(iso, []) + [dict(a, members=a['members'] - {iso}) for a in eun]
    cover, excl = {}, {}
    for iso, agrs in agreements.items():
        by_exp = defaultdict(list)
        for agr in agrs:
            for exp in agr['members']:
                by_exp[exp].append(agr)
            for hs, marks in agr['excluded'].items():
                for exp in agr['members']:
                    excl.setdefault((iso, exp), {}).setdefault(hs, set()).update(marks)
        cover[iso] = dict(by_exp)
    return {'agreements': agreements, 'cover': cover, 'excl': excl, 'log': log}


def member_isos(state):
    out = set()
    for agrs in state['agreements'].values():
        for agr in agrs:
            out |= agr['members']
    return out


def us_gsp_reached(state, lapses):
    """USA agreements still applied that are a lapsed GSP group or a single-country row from one."""
    n = 0
    for agr in state['agreements'].get('USA', []):
        if is_us_gsp('USA', agr['partner'], agr['name']) or lapsed_scheme_row('USA', agr, lapses):
            n += 1
    return n


def _usable(agr, code, hs6, banned_slot, exp):
    """Rate of one agreement on one line, or None when the exporter cannot use it."""
    if banned_slot:
        banned = banned_slot.get(code) or banned_slot.get(hs6) or ()
        if agr['partner'] in banned:
            return None
    if gsp_banned(code, agr['partner'], exp):
        return None
    return agr['rates'].get(code)


def pref_rate(state, imp, exp, hs6, sched_code):
    """(rate, agreement code, family) or (None, None, None).

    sched_code(nomen, hs6) gives the schedule code in that agreement's nomenclature.
    Latest line inside a family; the minimum across families; ties go to the later year,
    then the lower code.
    """
    agrs = state['cover'].get(imp, {}).get(exp)
    if not agrs:
        return None, None, None
    banned_slot = state['excl'].get((imp, exp))
    best = {}
    for agr in agrs:
        code = sched_code(agr['nomen'], hs6)
        if not code:
            continue
        rate = _usable(agr, code, hs6, banned_slot, exp)
        if rate is None:
            continue
        year = agr['rate_year'].get(code, agr['year'])
        prev = best.get(agr['family'])
        if prev is None or year > prev[0] or (year == prev[0] and rate < prev[1]):
            best[agr['family']] = (year, rate, agr['partner'])
    if not best:
        return None, None, None
    fam, (_y, rate, code) = min(best.items(), key=lambda kv: (kv[1][1], -kv[1][0], kv[1][2]))
    return rate, code, fam


def family_rates_independent(state, imp, exp, hs6, sched_code):
    """Second walk for the Hfamily check: every usable line, grouped by family after the fact."""
    lines = []
    for agr in state['cover'].get(imp, {}).get(exp, ()):
        code = sched_code(agr['nomen'], hs6)
        if not code or code not in agr['rates']:
            continue
        banned = (state['excl'].get((imp, exp)) or {})
        marks = banned.get(code) or banned.get(hs6) or ()
        if agr['partner'] in marks or gsp_banned(code, agr['partner'], exp):
            continue
        lines.append((agr['family'], agr['rate_year'].get(code, agr['year']), agr['rates'][code]))
    out = {}
    for fam in {f for f, _y, _r in lines}:
        top = max(y for f, y, _r in lines if f == fam)
        out[fam] = min(r for f, y, r in lines if f == fam and y == top)
    return out


def _self_test():
    agr_old = {'partner': 'A36', 'family': 'eu', 'year': 2020, 'nomen': 'H5',
               'rates': {'111111': 0.0, '222222': 27.0}, 'rate_year': {'111111': 2020, '222222': 2020}}
    agr_new = {'partner': 'A84', 'family': 'eu', 'year': 2022, 'nomen': 'H6',
               'rates': {'222222': 91.0}, 'rate_year': {'222222': 2022}}
    agr_other = {'partner': 'A94', 'family': 'ldc', 'year': 2021, 'nomen': 'H5',
                 'rates': {'333333': 0.0, '222222': 5.0}, 'rate_year': {'333333': 2021, '222222': 2021}}
    state = {'cover': {'IMP': {'EXP': [agr_old, agr_new, agr_other]}}, 'excl': {}}
    same = lambda nomen, hs: hs
    assert pref_rate(state, 'IMP', 'EXP', '222222', same)[:2] == (5.0, 'A94')
    assert pref_rate(state, 'IMP', 'EXP', '111111', same)[:2] == (0.0, 'A36')
    assert family_rates_independent(state, 'IMP', 'EXP', '222222', same) == {'eu': 91.0, 'ldc': 5.0}
    state['excl'] = {('IMP', 'EXP'): {'222222': {'A94'}}}
    assert pref_rate(state, 'IMP', 'EXP', '222222', same)[:2] == (91.0, 'A84')
    assert adjust_members('USA', 'B11', 'x', {'IND'}) == set()
    assert 'NZL' in adjust_members('SGP', '01D', 'RCEP', {'CHN', 'IDN'})
    assert 'MMR' in adjust_members('CHN', '01D', 'RCEP', {'MMR'})


_self_test()
