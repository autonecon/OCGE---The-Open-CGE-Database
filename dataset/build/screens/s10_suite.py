"""S10 population screens (dataset/docs/SCREENS.md), rebuilt with the S10 tariff code.

The stage calls run() with the objects it built, so every screen sees the same schedules,
line rates and BACI flows the stamp booked. Reports go to dataset/reviews/screens/S10/.
Nothing is written under the stage output, so a screen run does not change SHA256SUMS.

Screens 1 (collections), 2 (high rates), 3 (year jumps), 8 (ceilings) and 10 (quota
overrides) need an explanation row in config/s10/screen_explanations.csv when they can
change a duty. Screens 4 (stale years), 6 (coverage) and 7 (moves) are diagnostics.
Screen 5 (identities) and 9 (group membership) are pass/fail lists. Screen 12 (FTA
population) is a diagnostic: each in-force pair with no preference row is listed with the
class of its named ruling.
"""
import csv
import io
import os
import sys
import zipfile
from collections import defaultdict

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET = os.path.dirname(BUILD)
if BUILD not in sys.path:
    sys.path.insert(0, BUILD)

from s10_tariffs.overrides import ZMB_ADVALOREM, ZMB_BOOK, korea_trq_rates  # noqa: E402
from screens.common import (  # noqa: E402
    join_explanations, load_explanations, material, read_dicts, unexplained_material, write_dicts, write_summary,
)

EXPLANATIONS = BUILD + '/config/s10/screen_explanations.csv'
FTA_PAIRS = BUILD + '/config/s10/fta_pairs_2022.csv'
# Named rulings for in-force FTA pairs with no preference row (screen 12).
ACP_EPA = {'CIV', 'GHA', 'CMR', 'TTO', 'MOZ', 'ZWE', 'KEN'}          # epa_acp_staging
PACIFIC_EPA = {'FJI', 'PNG', 'SLB'}                                   # epa_pacific_staging
COMESA_GENUINE = {'ETH', 'COD', 'SWZ', 'TUN'}                         # afcfta_comesa_genuine
PREF_FILE_ABSENT = {'COD', 'AGO', 'IRN', 'VEN'}                       # preference_gap_notes
PREF_FILE_ABSENT_PAIRS = {('ISR', 'UKR'), ('PNG', 'AUS')}
REPORT_DIR = DATASET + '/reviews/screens/S10'
HIGH_RATE = 100.0
CEILING_EXACT = 3000.0
CEILING_RAW = 1000.0
JUMP_FACTOR, JUMP_POINTS = 3.0, 50.0
WITS_DECIMALS = 0.006            # the WITS bulk prints simple averages to two decimals
STALE_BEFORE = 2019
MOVE_SHARE, MOVE_BN = 0.10, 0.1
EXPLAINED_SCREENS = ('collections', 'high_rate', 'year_jump', 'ceiling', 'trq')
COLUMNS = ['screen', 'importer', 'hs6/sector', 'rate_pct', 'earlier_rate', 'earlier_year', 'source_series',
           'duty_bn', 'importer_duty_bn', 'fob_bn', 'collected_bn', 'ratio', 'gap_bn', 'evidence class', 'material', 'detail']


def _bn(thousand):
    return thousand / 1e6


def wits_aves(zip_path, keys, max_year=2022):
    """(reporter, nomen) -> {year: {code: HS6 simple average}} from the WITS MFN AVE bulk, 2017 to
    max_year, only for the reporters asked. The bulk is read on its own, not through sources.py, so
    wits_rate_as_given compares the booked rate with a second read of WITS."""
    out = defaultdict(dict)
    with zipfile.ZipFile(zip_path) as outer:
        for name in outer.namelist():
            parts = os.path.basename(name).split('_')
            if len(parts) < 5 or parts[0] != 'AVEMFN' or not parts[3].isdigit() or int(parts[3]) > max_year:
                continue
            nomen, rep, year = parts[1], parts[2], int(parts[3])
            if (rep, nomen) not in keys:
                continue
            inner = zipfile.ZipFile(io.BytesIO(outer.read(name)))
            csvs = [n for n in inner.namelist() if n.lower().endswith('.csv')]
            if not csvs:
                continue
            rates = {}
            for row in csv.DictReader(io.StringIO(inner.read(csvs[0]).decode('utf-8', 'replace'))):
                code = (row.get('ProductCode') or '').strip().zfill(6)
                try:
                    rates[code] = float(row.get('SimpleAverage') or '')
                except ValueError:
                    continue
            out[(rep, nomen)][year] = rates
    return out


def fta_population(tb, duty_pair, imp_duty_bn, path=None):
    """12: WTO RTA pairs in force in 2022 (or entering in 2022) whose exporter has no preference
    row at the importer. Each hit gets the evidence class of its named ruling. Returns (hits, note)."""
    path = path or FTA_PAIRS
    if not os.path.exists(path):
        raise SystemExit('FTA pair list is missing: ' + path)
    eu = set(tb.unions.eu_territory) | {'GBR'}
    efta = {'CHE', 'NOR', 'ISL', 'LIE'}
    cover = tb.state['cover']
    lapsed = {(imp, ben) for imp, _c, ben, _n in tb.state['log'].get('lapses_applied', []) if ben not in ('', '*')}
    pairs = defaultdict(list)
    n_file = n_force = n_part = 0
    for row in read_dicts(path):
        n_file += 1
        force, entry = (row.get('in_force_all_2022') or '').strip(), (row.get('entry_into_force') or '').strip()
        part = force != 'True' and entry.startswith('2022')
        if force != 'True' and not part:
            continue
        n_force += force == 'True'
        n_part += part
        imp, exp = (row.get('importer') or '').strip(), (row.get('exporter') or '').strip()
        if imp and exp:
            pairs[(imp, exp)].append(((row.get('agreement') or '').strip(), part))
    hits, n_region = [], 0
    for (imp, exp), named in sorted(pairs.items()):
        if (imp, exp) not in duty_pair:
            continue
        n_region += 1
        duty_bn = duty_pair[(imp, exp)] / 1000.0
        blob = ' '.join(n for n, _p in named)
        part = any(p for _n, p in named)
        mat = material(duty_bn, imp_duty_bn(imp))
        if 'Türkiye - Syrian' in blob or ('Syrian Arab Republic' in blob and {imp, exp} == {'TUR', 'SYR'}):
            cause, klass, note = 'suspended', 'gtap_rule', 'The Türkiye-Syria agreement is suspended. MFN stays.'
        elif (imp, exp) in lapsed or (imp, exp) == ('RUS', 'UKR'):
            if duty_bn >= 0.005:
                continue
            cause, klass, note = 'reverse_zero', 'gtap_rule', 'A lapse or the Russia-Ukraine suspension; duty under 0.005 bn.'
        elif cover.get(imp, {}).get(exp) or not mat:
            continue
        elif {imp, exp} == {'ARE', 'IND'} and part:
            cause, klass, note = 'cepa_year_rule', 'gtap_rule', 'are_ind_cepa: the latest ARE file (2021) has no CEPA.'
        elif imp in ACP_EPA and exp in eu:
            cause, klass, note = 'epa_staging_data_absent', 'gtap_rule', 'epa_acp_staging: TRAINS used as held; an upper bound.'
        elif imp in PACIFIC_EPA and exp in eu:
            cause, klass, note = 'epa_pacific_staging', 'gtap_rule', 'epa_pacific_staging: same ruling as the ACP EPAs.'
        elif 'African Continental' in blob or (('COMESA' in blob or 'Common Market for Eastern' in blob)
                                               and (imp in COMESA_GENUINE or exp in COMESA_GENUINE)):
            cause, klass, note = 'genuine_not_a_source_gap', 'genuine_not_a_source_gap', 'afcfta_comesa_genuine: MFN stays.'
        else:
            cause = 'missing_preference_file' if not cover.get(imp) else 'missing_schedule_in_source'
            klass = 'missing_schedule_in_source'
            note = 'missing_schedule_in_source: MFN where the source has no schedule for the pair.'
            if imp == 'TUN' and exp in efta:
                note += ' TUN has no EFTA schedule.'
            elif imp == 'MYS' and exp in ('HKG', 'KHM', 'MMR'):
                note += ' Malaysia preference data stop in 2014.'
        if imp == 'IRQ':
            klass, note = 'gtap_rule', note + ' iraq_gafta_2022: GAFTA application not verified, not booked.'
        elif imp == 'KHM':
            klass, note = 'gtap_rule', note + ' khm_pan_2022_preferences: no 2022 Cambodia file.'
        elif imp == 'PAN':
            klass, note = 'gtap_rule', note + ' khm_pan_2022_preferences: no Panama file after 2013; the TPA overlay stays.'
        elif imp in PREF_FILE_ABSENT or (imp, exp) in PREF_FILE_ABSENT_PAIRS:
            klass, note = 'gtap_rule', note + ' preference_gap_notes: file absent, rate unchanged.'
        hits.append({'screen': 'fta_population', 'importer': imp, 'hs6/sector': exp, 'duty_bn': duty_bn,
                     'importer_duty_bn': imp_duty_bn(imp), 'evidence class': klass, 'material': 'yes' if mat else 'no',
                     'detail': f"{cause}; {'; '.join(n for n, _p in named if n)[:180]}. {note}"})
    counts = defaultdict(int)
    for h in hits:
        counts[h['detail'].split(';', 1)[0]] += 1
    note = (f'FTA pairs: {n_file} rows, {n_force} in force all of 2022, {n_part} entering in 2022, {n_region} on a region '
            f'pair with duty. Flags {len(hits)}: ' + ', '.join(f'{k} {v}' for k, v in sorted(counts.items())) + '.')
    return hits, note


def run(ctx, report_dir=REPORT_DIR, log=print):
    """ctx keys: build (TariffBuild), duty_region {region: musd}, customs_rows, census_usa_musd,
    prev_duty {(importer, sector): musd} or None, mfn_ave_zip. Returns the stage_check dict."""
    tb = ctx['build']
    acc, schedules, cm = tb.acc, tb.schedules, tb.cm
    duty_region = ctx['duty_region']

    def imp_duty_bn(iso):
        reg = 'EUN' if iso == 'EUN' else cm.region_of(iso) or iso
        if reg == 'EUN':
            return sum(duty_region.get(r, 0.0) for r in tb.unions.eu_territory) / 1000.0
        return duty_region.get(reg, 0.0) / 1000.0

    hits = defaultdict(list)
    notes, couldnt = [], []

    # 1 collections: booked duty against collected duty.
    collected = {r[0]: r for r in ctx['customs_rows']}
    for reg in sorted(duty_region):
        row = collected.get(reg)
        booked = duty_region[reg] / 1000.0
        if row is None:
            if booked >= 0.02:
                couldnt.append(f'{reg} has booked duty {booked:.3f} bn and no collections row')
            continue
        coll = float(row[1]) / 1000.0
        if reg == 'USA':
            coll = ctx['census_usa_musd'] / 1000.0
        gap = booked - coll
        hits['collections'].append({'screen': 'collections', 'importer': reg, 'hs6/sector': '', 'duty_bn': abs(gap),
                                    'importer_duty_bn': booked, 'collected_bn': coll, 'gap_bn': gap,
                                    'ratio': booked / coll if coll else '', 'detail': row[6]})

    # 2 high rates and 8 ceilings: one hit per schedule line; duty on imports that face the line.
    for (key, code), value in sorted(acc.facing.items()):
        sch = schedules.get(key)
        if sch is None or code not in sch.rate:
            continue
        rate = sch.rate[code]
        duty = _bn(acc.facing_duty[(key, code)])
        series = sch.how.get(code, '')
        base = {'importer': key, 'hs6/sector': code, 'rate_pct': rate, 'source_series': series,
                'duty_bn': duty, 'importer_duty_bn': imp_duty_bn(key), 'fob_bn': _bn(value)}
        if rate >= HIGH_RATE:
            hits['high_rate'].append(dict(base, screen='high_rate'))
        raw = sch.ave.get(code)
        if raw is not None and (abs(raw - CEILING_EXACT) < 1e-6 or raw >= CEILING_RAW) and code not in sch.reported:
            hits['ceiling'].append(dict(base, screen='ceiling', earlier_rate=raw, detail=f'raw AVE {raw}; used {rate} ({series})'))

    # 3 year jumps: an AVE-sourced line against the latest earlier year on the same nomenclature.
    keys = {(lab, schedules[k].nomen) for k, _c in acc.facing if k in schedules
            for lab in [k] + [a for a, t in getattr(cm, 'alias', {}).items() if t == k]}
    earlier = wits_aves(ctx['mfn_ave_zip'], keys)
    no_earlier = 0
    for (key, code), value in sorted(acc.facing.items()):
        sch = schedules.get(key)
        if sch is None or sch.how.get(code) != 'ave':
            continue
        years = earlier.get((key, sch.nomen), {})
        prior = [(y, r[code]) for y, r in years.items() if code in r and y < sch.year]
        if not prior:
            no_earlier += 1
            continue
        y0, r0 = max(prior)
        rate = sch.rate[code]
        if (r0 > 0 and rate > JUMP_FACTOR * r0) or rate > r0 + JUMP_POINTS:
            hits['year_jump'].append({'screen': 'year_jump', 'importer': key, 'hs6/sector': code, 'rate_pct': rate,
                                      'earlier_rate': r0, 'earlier_year': y0, 'source_series': 'ave',
                                      'duty_bn': _bn(acc.facing_duty[(key, code)]), 'importer_duty_bn': imp_duty_bn(key),
                                      'fob_bn': _bn(value),
                                      'detail': 'earlier-year conversion' if r0 < 1.0 else ''})
    notes.append(f'Year jumps: AVE-sourced lines with no earlier year on the same nomenclature: {no_earlier}.')

    # 4 stale years (diagnostic).
    for key, sch in sorted(schedules.items()):
        if sch.year and sch.year < STALE_BEFORE:
            hits['stale'].append({'screen': 'stale', 'importer': key, 'hs6/sector': '', 'rate_pct': '',
                                  'earlier_year': sch.year, 'importer_duty_bn': imp_duty_bn(key), 'detail': sch.source})

    # 5 identities.
    for imp, exp, hs, r, m in acc.above_mfn:
        hits['identities'].append({'screen': 'identities', 'importer': imp, 'hs6/sector': hs, 'rate_pct': r,
                                   'detail': f'from {exp} above MFN {m}'})
    for base, tm, vmsb, duty in tb.wedge_rows:
        if tm < 0 or abs(duty - base * tm) > 1e-6 * max(1.0, abs(base)) or vmsb + 1e-8 < base:
            hits['identities'].append({'screen': 'identities', 'importer': '', 'hs6/sector': '', 'detail': f'{base} {tm}'})

    # 6 coverage (diagnostic): share of goods imports with no rate, by importer ISO.
    no_rate = defaultdict(float)
    for (imp, _how), v in acc.no_rate_imp.items():
        no_rate[imp] += v
    for imp, total in sorted(acc.imp_total.items()):
        share = no_rate[imp] / total if total else 0.0
        if share > 0.05:
            hits['coverage'].append({'screen': 'coverage', 'importer': imp, 'hs6/sector': '', 'fob_bn': _bn(no_rate[imp]),
                                     'ratio': share, 'detail': ' '.join(f'{h} {_bn(v):.3f}' for (i, h), v in
                                                                        sorted(acc.no_rate_imp.items()) if i == imp)})

    # 7 moves (diagnostic) against the previous stamp.
    prev = ctx.get('prev_duty')
    if prev is not None:
        new = defaultdict(float)
        for (imp, _exp, short), (duty, _b) in tb.duty_cell.items():
            new[(imp, short)] += duty
        for key in sorted(set(prev) | set(new)):
            o, n = prev.get(key, 0.0), new.get(key, 0.0)
            if abs(n - o) / 1000.0 > MOVE_BN or (abs(o) > 0 and abs(n - o) / abs(o) > MOVE_SHARE and abs(n - o) / 1000.0 > 0.02):
                hits['moves'].append({'screen': 'moves', 'importer': key[0], 'hs6/sector': key[1],
                                      'duty_bn': (n - o) / 1000.0, 'detail': f'old {o / 1000:.4f} new {n / 1000:.4f}'})
    else:
        couldnt.append('No previous stamp was given, so screen 7 (moves) did not run.')

    # 9 group membership.
    for problem in tb.group_problems:
        hits['groups'].append({'screen': 'groups', 'importer': '', 'hs6/sector': '', 'detail': problem})
    for imp, code, year in tb.state['log'].get('unknown_group', []):
        hits['groups'].append({'screen': 'groups', 'importer': imp, 'hs6/sector': code, 'detail': f'no member list ({year})'})

    # 10 quota overrides: Korea TRQ lines, duty on imports that face them.
    kor = schedules['KOR']
    for code, how in sorted(kor.how.items()):
        if how != 'korea_trq':
            continue
        v = acc.facing.get(('KOR', code), 0.0)
        hits['trq'].append({'screen': 'trq', 'importer': 'KOR', 'hs6/sector': code, 'rate_pct': kor.rate[code],
                            'source_series': how, 'duty_bn': _bn(acc.facing_duty.get(('KOR', code), 0.0)),
                            'importer_duty_bn': imp_duty_bn('KOR'), 'fob_bn': _bn(v)})

    # 11 intra-union cells with a non-zero booked rate (report only; nothing is newly zeroed).
    unions = dict(tb.unions.fill)
    unions.update(tb.unions.screen_only)
    for uid, members in sorted(unions.items()):
        for (imp, exp, short), rate in sorted(tb.rate.items()):
            if imp in members and exp in members and imp != exp and rate > 1e-6:
                hits['intra_union'].append({'screen': 'intra_union', 'importer': imp, 'hs6/sector': f'{exp} {short}',
                                            'rate_pct': rate, 'duty_bn': tb.duty_cell[(imp, exp, short)][0] / 1000.0,
                                            'detail': uid})

    # 12 FTA population: in-force pairs with no preference row at the importer.
    duty_pair = defaultdict(float)
    for (imp, exp, _short), (duty, _b) in tb.duty_cell.items():
        duty_pair[(imp, exp)] += duty
    hits['fta_population'], fta_note = fta_population(tb, duty_pair, imp_duty_bn)
    notes.append(fta_note)

    # Explanations and the statutory_vs_collected rule for collections.
    by_key, _rows = load_explanations(EXPLANATIONS)
    explained = []
    for screen in EXPLAINED_SCREENS:
        join_explanations(hits[screen], by_key)
        explained.extend(hits[screen])
    # wits_rate_as_given (David 2026-10-22 20:12): a high-rate, year-jump or ceiling hit with no
    # explanation row is that class when the booked percent equals the WITS bulk HS6 simple average
    # for the schedule's own reporter, nomenclature and year (the bulk prints two decimals).
    # Korea TRQ lines are trq when the booked rate equals the trq_fill_rule rate recomputed here.
    trq_rates = korea_trq_rates(tb.C['trq_fill_measure'])
    trq_other = {(iso, code): rate for iso, code, rate in getattr(tb, 'trq_expect', [])}
    for screen in ('high_rate', 'year_jump', 'ceiling', 'trq'):
        for h in hits[screen]:
            if h['evidence class'] != 'unexplained':
                continue
            sch = schedules.get(h['importer'])
            code = h['hs6/sector']
            if sch is None or code not in sch.rate:
                continue
            booked = sch.rate[code]
            if sch.how.get(code) == 'korea_trq' and code in trq_rates and abs(booked - trq_rates[code]['rate']) <= 1e-9:
                h['evidence class'] = 'trq'
                h['detail'] = (h.get('detail') or '') + '; trq_fill_rule rate recomputed'
                continue
            # trq_outside_kor_pan (round-3 fix wE2): a quota heading at the fill-rule rate S10-Htrq checked
            if sch.how.get(code) == 'trq_fill' and (h['importer'], code) in trq_other and abs(booked - trq_other[(h['importer'], code)]) <= 1e-9:
                h['evidence class'] = 'trq'
                h['detail'] = (h.get('detail') or '') + '; trq_fill_rule on the WTO MA:2 2022 fill (trq_fill_s10.csv)'
                continue
            if sch.how.get(code) == 'class_a_ad_valorem' and h['importer'] == 'ZMB' and abs(booked - ZMB_ADVALOREM.get(code, -1)) <= 1e-9:
                h['evidence class'] = 'tariff_book'      # ave_outlier_rule, Zambia 2022 tariff book
                h['detail'] = (h.get('detail') or '') + '; ' + ZMB_BOOK.get(code, 'Zambia 2022 tariff book pp.396-401')
                continue
            labels = [h['importer']] + sorted(a for a, t in getattr(cm, 'alias', {}).items() if t == h['importer'])
            raw = next((earlier[(lab, sch.nomen)][sch.year][code] for lab in labels
                        if code in earlier.get((lab, sch.nomen), {}).get(sch.year, {})), None)
            if raw is not None and abs(raw - booked) <= WITS_DECIMALS:
                h['evidence class'] = 'wits_rate_as_given'
                h['detail'] = (h.get('detail') or '') + f'; WITS bulk {sch.year} simple average {raw}'
                continue
            # No bulk file for that reporter and year: compare with the value in the TRAINS file itself
            # (Reported with NBR_NA_LINES 0, else AVEEstimated), kept on the schedule before any override.
            file_value = sch.reported.get(code, sch.ave.get(code))
            if raw is None and file_value is not None and abs(file_value - booked) <= 1e-9:
                h['evidence class'] = 'wits_rate_as_given'
                h['detail'] = (h.get('detail') or '') + f'; TRAINS {sch.year} file value {file_value} (no WITS bulk file that year)'
                continue
            if screen == 'year_jump' and float(h.get('earlier_rate') or 99) < 1.0:     # earlier_year_conversion
                h['evidence class'] = 'earlier_year_conversion'
    drivers = defaultdict(float)
    for screen in ('high_rate', 'year_jump', 'ceiling', 'trq'):
        for h in hits[screen]:
            if h['evidence class'] == 'unexplained' and h['material'] == 'yes':
                drivers[cm.region_of(h['importer']) or h['importer']] += abs(float(h.get('duty_bn') or 0.0))
    for h in hits['collections']:
        if h['evidence class'] == 'unexplained' and drivers.get(h['importer'], 0.0) < 0.02:
            h['evidence class'] = 'gtap_rule'
            h['detail'] = (h.get('detail') or '') + '; statutory_vs_collected: no conversion, membership or stale driver above the bar'
    for h in hits['groups'] + hits['identities']:
        h['evidence class'], h['material'] = 'unexplained', 'yes'
    bad = unexplained_material(explained + hits['groups'] + hits['identities'])
    # screen_cross_dedupe: one material hit per importer and line across screens (the largest duty).
    seen, kept = set(), []
    for h in bad:
        key = (h.get('importer'), h.get('hs6/sector')) if h['screen'] in ('high_rate', 'year_jump', 'ceiling', 'trq') else id(h)
        if key not in seen:
            seen.add(key)
            kept.append(h)
    bad = kept

    names = [('1 collections', 'collections'), ('2 high rates', 'high_rate'), ('3 year jumps', 'year_jump'),
             ('4 stale years', 'stale'), ('5 identities', 'identities'), ('6 coverage', 'coverage'), ('7 moves', 'moves'),
             ('8 ceilings', 'ceiling'), ('9 group membership', 'groups'), ('10 quota overrides', 'trq'),
             ('11 intra-union non-zero', 'intra_union'), ('12 FTA population', 'fta_population')]
    os.makedirs(report_dir, exist_ok=True)
    counts = []
    for i, (title, key) in enumerate(names, 1):
        rows = sorted(hits[key], key=lambda h: -abs(float(h.get('duty_bn') or 0.0)))
        write_dicts(os.path.join(report_dir, f'screen_{i:02d}_{key}.csv'), rows, COLUMNS)
        counts.append((title, len(rows), len(rows)))
    notes.append('Screens 4, 6 and 7 are diagnostics and are not in the hard check. Screens 5 and 9 fail on any hit. '
                 'Screen 12 is a diagnostic (fta_population_screen): each pair carries the class of its named ruling.')
    notes.append('A collections gap is gtap_rule (statutory_vs_collected) when no high-rate, year-jump, ceiling or quota '
                 'hit of that importer is unexplained and material.')
    write_summary(os.path.join(report_dir, 'SUMMARY.md'), 'S10 population screens', counts, bad, couldnt, notes)
    log(f'screens: {sum(len(v) for v in hits.values())} hits; unexplained material {len(bad)}')
    return {'material_unexplained': len(bad),
            'detail': '; '.join(f"{h['screen']} {h['importer']} {h['hs6/sector']} {float(h.get('duty_bn') or 0):.4f}"
                                for h in bad[:12]) or 'none',
            'hits': {k: len(v) for k, v in hits.items()}}
