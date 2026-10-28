"""Readers for the S10 tariff sources. No rule is applied here beyond the series choice.

MFN: the TRAINS SDMX schedules in trains_internal/ (partner 000), one reporter
and year per file as the manifest lists them. Series choice (trains_ave_series):
the Reported simple average when NBR_NA_LINES is 0, else the AVEEstimated
simple average, else a Reported line with a blank NBR_NA_LINES. A Reported line
with NBR_NA_LINES above 0 and no AVEEstimated line is a specific duty with no
AVE; it is listed and left out of the weight.

Preferences: the WITS bulk AVEPref files 2017-2022, the public SDMX extract,
and the job 3187139 supplement. Each record is one importer, one partner code
(a country number or a group code), one nomenclature. Within that key the
latest year that has a line wins the line (preference_year_fallback). In the
same year the bulk file wins over the API extract and the supplement.
"""
import csv
import gzip
import io
import json
import os
import re
import tarfile
import zipfile
from collections import defaultdict

from .config import ConfigError

SERIES_RE = re.compile(br'<Series\b([^>]*?)>(.*?)</Series>', re.DOTALL)
OBS_RE = re.compile(br'<Obs\b([^>]*)/?>')
ATTR_RE = re.compile(br'([A-Za-z0-9_]+)="([^"]*)"')
GEN_SERIES_RE = re.compile(br'<generic:Series>(.*?)</generic:Series>', re.DOTALL)
GEN_VAL_RE = re.compile(br'<generic:Value id="([^"]+)" value="([^"]*)"')
GEN_OBSVAL_RE = re.compile(br'<generic:ObsValue value="([^"]*)"')
GEN_DIM_RE = re.compile(br'<generic:ObsDimension id="TIME_PERIOD" value="([^"]*)"')
MAX_YEAR = 2022
SOURCE_RANK = {'national': 4, 'bulk': 3, 'api': 2, 'supp': 1}


def _attrs(blob):
    return {k.decode(): v.decode() for k, v in ATTR_RE.findall(blob)}


def _int_or_none(text):
    text = (text or '').strip()
    return int(text) if text.lstrip('-').isdigit() else None


def parse_mfn_sdmx(blob):
    """HS6 -> (year, value, na_lines, nomen, datatype). Partner 000, MFN simple average, latest year <= 2022."""
    out = {}

    def keep(code, year, value, na, nomen, datatype):
        if len(code) != 6 or not code.isdigit() or datatype not in ('Reported', 'AVEEstimated') or year > MAX_YEAR:
            return
        prev = out.get(code)
        if prev is None or year >= prev[0]:
            out[code] = (year, value, na, nomen, datatype)

    if b'generic:Series' in blob:
        for body in GEN_SERIES_RE.findall(blob):
            vals = {k.decode(): v.decode() for k, v in GEN_VAL_RE.findall(body)}
            if vals.get('PARTNER') not in (None, '', '000'):
                continue
            if vals.get('TARIFFTYPE') not in (None, 'MFN') or vals.get('OBS_VALUE_MEASURE') not in (None, 'SimpleAverage'):
                continue
            obs = GEN_OBSVAL_RE.search(body)
            if not obs or not obs.group(1):
                continue
            dim = GEN_DIM_RE.search(body)
            year = _int_or_none(dim.group(1).decode() if dim else '') or 0
            keep(vals.get('PRODUCTCODE') or '', year, float(obs.group(1)), _int_or_none(vals.get('NBR_NA_LINES')),
                 vals.get('NOMENCODE') or '', vals.get('DATATYPE') or '')
        return out
    for series_blob, body in SERIES_RE.findall(blob):
        series = _attrs(series_blob)
        if series.get('PARTNER') not in (None, '', '000'):
            continue
        for obs_blob in OBS_RE.findall(body):
            obs = _attrs(obs_blob)
            if obs.get('TARIFFTYPE') != 'MFN' or obs.get('OBS_VALUE_MEASURE') != 'SimpleAverage':
                continue
            if obs.get('OBS_VALUE') in (None, ''):
                continue
            keep(series.get('PRODUCTCODE') or '', _int_or_none(obs.get('TIME_PERIOD')) or 0, float(obs['OBS_VALUE']),
                 _int_or_none(obs.get('NBR_NA_LINES')), obs.get('NOMENCODE') or '', series.get('DATATYPE') or '')
    return out


class Schedule:
    """One reporter's MFN schedule on its own nomenclature."""

    def __init__(self, iso, nomen, year, source):
        self.iso, self.nomen, self.year, self.source = iso, nomen, year, source
        self.rate = {}      # schedule code -> percent used
        self.how = {}       # schedule code -> reported | ave | blank | <override token>
        self.ave = {}       # schedule code -> AVEEstimated value (before any override)
        self.reported = {}  # schedule code -> Reported value with NBR_NA_LINES 0
        self.specific = {}  # schedule code -> (reported value, na lines) with no AVE

    def set(self, code, value, how):
        self.rate[code] = value
        self.how[code] = how


def load_mfn(manifest_path, tar_paths, codemap):
    """Return ({iso: Schedule}, problems). EU members share the EUN schedule object."""
    jobs = defaultdict(list)
    with open(manifest_path, newline='') as fh:
        for row in csv.DictReader(fh):
            if not row.get('file'):
                continue
            if row['role'] == 'EU':
                isos = ['EUN']
            else:
                isos = [codemap.from_reporter(row['iso3'])]
            jobs[row['file']].append((isos, int(row['year_used'] or 0)))
    seen = set()
    raw = defaultdict(lambda: {'Reported': {}, 'AVEEstimated': {}, 'nomen': '', 'year': 0})
    for tar_path in tar_paths:
        with tarfile.open(tar_path, 'r:xz') as tf:
            for member in tf:
                base = os.path.basename(member.name)
                if base not in jobs:
                    continue
                seen.add(base)
                lines = parse_mfn_sdmx(tf.extractfile(member).read())
                for isos, year in jobs[base]:
                    for iso in isos:
                        slot = raw[iso]
                        slot['year'] = max(slot['year'], year)
                        for code, (_y, value, na, nomen, datatype) in lines.items():
                            slot[datatype][code] = (value, na)
                            if nomen:
                                slot['nomen'] = nomen
    problems = sorted(set(jobs) - seen)
    schedules = {}
    for iso, slot in raw.items():
        sch = Schedule(iso, slot['nomen'] or 'H6', slot['year'], 'trains_mfn')
        for code, (value, _na) in slot['AVEEstimated'].items():
            sch.ave[code] = value
        for code, (value, na) in slot['Reported'].items():
            if na == 0:
                sch.reported[code] = value
                sch.set(code, value, 'reported')
        for code, value in sch.ave.items():
            if code not in sch.rate:
                sch.set(code, value, 'ave')
        for code, (value, na) in slot['Reported'].items():
            if code in sch.rate:
                continue
            if na is None:
                sch.set(code, value, 'blank')
            elif na > 0:
                sch.specific[code] = (value, na)
        schedules[iso] = sch
    return schedules, problems


def _parse_pref_csv(text, iso, year, nomen, source):
    """Bulk or supplement AVEPref CSV -> list of records, one per partner code."""
    rates = defaultdict(dict)
    excluded = defaultdict(lambda: defaultdict(set))
    for row in csv.DictReader(io.StringIO(text)):
        partner = (row.get('Partner') or '').strip()
        code = (row.get('ProductCode') or '').strip()
        if not partner or len(code) != 6 or not code.isdigit():
            continue
        try:
            value = float((row.get('SimpleAverage') or '').strip())
        except ValueError:
            continue
        if value != value:
            continue
        row_year = _int_or_none(row.get('Year'))
        if row_year is not None and row_year > MAX_YEAR:
            continue
        rates[partner][code] = value
        excl = (row.get('ExcludedFrom') or '').strip()
        if excl:
            excluded[partner][code].add(excl)
    return [{'iso': iso, 'partner': p, 'year': year, 'nomen': nomen, 'rates': r, 'source': source,
             'excluded': {c: set(s) for c, s in excluded.get(p, {}).items()}} for p, r in rates.items()]


def _avepref_name(name):
    """AVEPref_H6_USA_2022_U2.zip -> (nomen, reporter, year) or None."""
    parts = os.path.basename(name).split('_')
    if len(parts) < 5 or not parts[0].startswith('AVEPref') or not parts[3].isdigit():
        return None
    return parts[1], parts[2], int(parts[3])


def _inner_csv(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as inner:
        csvs = [n for n in inner.namelist() if n.lower().endswith('.csv')]
        if len(csvs) != 1:
            raise SystemExit(f'AVEPref zip has {len(csvs)} csv members')
        return inner.read(csvs[0]).decode('utf-8-sig', 'replace')


def parse_pref_sdmx_gz(path):
    """API extract file -> (rates, nomen). Reported PREF simple average, latest year <= 2022."""
    with gzip.open(path, 'rb') as fh:
        blob = fh.read()
    rates, nomen = {}, ''
    for series_blob, body in SERIES_RE.findall(blob):
        series = _attrs(series_blob)
        if (series.get('DATATYPE') or '') not in ('', 'Reported'):
            continue
        code = series.get('PRODUCTCODE') or ''
        if len(code) != 6 or not code.isdigit():
            continue
        best = None
        for obs_blob in OBS_RE.findall(body):
            obs = _attrs(obs_blob)
            if obs.get('TARIFFTYPE') != 'PREF' or obs.get('OBS_VALUE_MEASURE') != 'SimpleAverage':
                continue
            try:
                value = float(obs.get('OBS_VALUE') or '')
            except ValueError:
                continue
            year = _int_or_none(obs.get('TIME_PERIOD')) or 0
            if value != value or year > MAX_YEAR:
                continue
            if best is None or year >= best[0]:
                best = (year, value, obs.get('NOMENCODE') or '')
        if best:
            rates[code] = best[1]
            nomen = best[2] or nomen
    return rates, nomen


def national_preferences(path, agreements, iso='MYS', year=2022):
    """mys_preference_schedules: the extracted 2022 rates of Malaysia's own preferential schedules.
    HS6 rate = simple average of the national lines with an ad valorem rate (as MAcMap). agreements:
    {agreement: (partner code, members)} from mys_national_agreements.csv; an agreement in the extract
    without a row, a row without lines, or a partner code that differs stops the run. Returns raw
    preference records, one per (partner, nomenclature), and per-agreement line counts."""
    lines = defaultdict(list)
    stats = defaultdict(lambda: [0, 0])
    with open(path, newline='') as fh:
        for row in csv.DictReader(fh):
            spec = agreements.get(row['agreement'])
            if spec is None or spec[0] != row['partner']:
                raise ConfigError(f'Malaysia schedule {row["agreement"]} partner {row["partner"]} has no matching '
                                  'mys_national_agreements.csv row')
            st = stats[row['agreement']]
            st[0] += 1
            if row['rate_pct'] == '':
                continue
            st[1] += 1
            lines[(row['agreement'], row['nomen'], row['hs6'])].append(float(row['rate_pct']))
    missing = sorted(set(agreements) - {k for k, v in stats.items() if v[1] > 0})
    if missing:
        raise ConfigError('mys_national_agreements.csv rows with no rate-bearing extracted line: ' + ' '.join(missing))
    recs = {}
    for (agr, nomen, hs6), vals in lines.items():
        partner, members = agreements[agr]
        rec = recs.setdefault((agr, nomen), {'iso': iso, 'partner': partner, 'year': year, 'nomen': nomen,
                                             'rates': {}, 'source': 'national', 'excluded': {},
                                             'agreement': agr, 'members': members})
        rec['rates'][hs6] = sum(vals) / len(vals)
    return list(recs.values()), {k: tuple(v) for k, v in stats.items()}


def ncl_schedule(path, changed_2022_path):
    """ncl_schedule: New Caledonia DD by HS6, the simple average of its 8-digit lines (EX = 0), from the
    tariff consolidated on 1 January 2023; an HS6 whose lines had another DD in 2022 takes its 2022
    average (DRDNC notice 22001425, ncl_dd_2022_changed_hs6.csv). A 2022 row whose 2023 average does
    not match the tariff file, or an HS6 the tariff does not have, stops the run."""
    lines = defaultdict(list)
    with open(path, newline='') as fh:
        for row in csv.DictReader(fh):
            if row['dd_pct'] == '':
                raise ValueError(f'NCL line {row["code8"]} has no DD rate: {row["dd_text"]!r}')
            lines[row['hs6']].append(float(row['dd_pct']))
    sch = Schedule('NCL', 'H6', 2022, 'ncl_customs_tariff')
    for hs6, vals in lines.items():
        sch.set(hs6, sum(vals) / len(vals), 'reported')
    with open(changed_2022_path, newline='') as fh:
        for row in csv.DictReader(fh):
            hs6 = row['hs6']
            if hs6 not in sch.rate or abs(sch.rate[hs6] - float(row['dd_2023_pct'])) > 1e-6:
                raise ValueError(f'NCL 2022 row {hs6} does not match the 2023 tariff file')
            sch.set(hs6, float(row['dd_2022_pct']), 'reported')
    for hs6 in sch.rate:
        sch.reported[hs6] = sch.rate[hs6]
    return sch


def load_preferences(pref_zip, api_dir, supp_dir, codemap, national=()):
    """Return {(iso, partner_code, nomen): record} after the latest-year-per-line merge, and file counts.
    national: extra raw records from national schedules (national_preferences)."""
    raw = list(national)
    counts = defaultdict(int)
    counts['national'] = len(raw)
    with zipfile.ZipFile(pref_zip) as outer:
        for name in outer.namelist():
            meta = _avepref_name(name)
            if not meta or meta[2] > MAX_YEAR:
                continue
            nomen, rep, year = meta
            raw.extend(_parse_pref_csv(_inner_csv(outer.read(name)), codemap.from_reporter(rep), year, nomen, 'bulk'))
            counts['bulk'] += 1
    for name in sorted(os.listdir(api_dir)):
        if not name.endswith('.xml.gz'):
            continue
        rep, year_s, partner = name[:-7].split('_')
        if int(year_s) > MAX_YEAR:
            continue
        rates, nomen = parse_pref_sdmx_gz(os.path.join(api_dir, name))
        if rates:
            raw.append({'iso': codemap.from_reporter(rep), 'partner': partner, 'year': int(year_s),
                        'nomen': nomen or 'H6', 'rates': rates, 'source': 'api', 'excluded': {}})
            counts['api'] += 1
    for name in sorted(os.listdir(supp_dir)):
        if not name.endswith(('.zip', '.ZIP')):
            continue
        path = os.path.join(supp_dir, name)
        with zipfile.ZipFile(path) as zf:
            members = zf.namelist()
            if any(m.lower().endswith('.csv') for m in members):
                meta = _avepref_name(name)
                if meta and meta[2] <= MAX_YEAR:
                    csv_name = next(m for m in members if m.lower().endswith('.csv'))
                    text = zf.read(csv_name).decode('utf-8-sig', 'replace')
                    raw.extend(_parse_pref_csv(text, codemap.from_reporter(meta[1]), meta[2], meta[0], 'supp'))
                    counts['supp'] += 1
                continue
            for member in members:
                meta = _avepref_name(member)
                if not member.lower().endswith('.zip') or not meta or meta[2] > MAX_YEAR:
                    continue
                raw.extend(_parse_pref_csv(_inner_csv(zf.read(member)), codemap.from_reporter(meta[1]),
                                           meta[2], meta[0], 'supp'))
                counts['supp'] += 1
    # Latest year per line within (importer, partner code, nomenclature). Same year: bulk > api > supp.
    raw.sort(key=lambda r: (r['iso'], r['partner'], r['nomen'], r['year'], SOURCE_RANK[r['source']]))
    merged = {}
    for rec in raw:
        key = (rec['iso'], rec['partner'], rec['nomen'])
        slot = merged.get(key)
        if slot is None:
            slot = {'iso': rec['iso'], 'partner': rec['partner'], 'nomen': rec['nomen'], 'year': rec['year'],
                    'source': rec['source'], 'rates': {}, 'rate_year': {}, 'rate_source': {}, 'excluded': {}}
            merged[key] = slot
        if rec.get('members'):
            slot['members'], slot['agreement'] = rec['members'], rec['agreement']
        # Records arrive oldest first, lowest-ranked first: a later record overwrites the line.
        for code, value in rec['rates'].items():
            slot['rates'][code] = value
            slot['rate_year'][code] = rec['year']
            slot['rate_source'][code] = rec['source']
            if code in rec['excluded']:
                slot['excluded'][code] = set(rec['excluded'][code])
            else:
                slot['excluded'].pop(code, None)
        slot['year'] = rec['year']
        slot['source'] = rec['source']
    return merged, dict(counts)


def hts_kl_rates(path):
    """HS6 -> simple average of HTS 2022 national tariff lines, with a Special K or L line at zero.

    A national tariff line is a row that carries a General rate (8- or 10-digit). A
    10-digit statistical suffix with no rate of its own is not a separate line. A line's
    Special column is its own, or its 8-digit parent's when its own is blank. A line whose
    General rate is a specific or compound duty is left out of the average and counted.
    Only HS6 codes that hold at least one K or L line are returned.
    """
    rows = json.load(open(path, encoding='utf-8'))
    special_of, rated = {}, []
    for rec in rows:
        digits = re.sub(r'\D', '', rec.get('htsno') or '')
        if len(digits) not in (8, 10):
            continue
        special = (rec.get('special') or '').strip()
        if special:
            special_of[digits] = special
        general = (rec.get('general') or '').strip()
        if general:
            rated.append((digits, general))

    def kl(digits):
        text = special_of.get(digits) or special_of.get(digits[:8]) or ''
        tokens = set()
        for match in re.finditer(r'\(([^)]*)\)', text):
            tokens.update(t.strip().strip('+*') for t in match.group(1).split(','))
        return bool(tokens & {'K', 'L'})

    by_hs6 = defaultdict(list)
    for digits, general in rated:
        by_hs6[digits[:6]].append((digits, general, kl(digits)))
    out = {}
    stats = {'hs6': 0, 'kl_lines': 0, 'specific_left_out': 0}
    for hs6, lines in by_hs6.items():
        if not any(k for _d, _g, k in lines):
            continue
        vals = []
        for _digits, general, is_kl in sorted(lines):
            if is_kl:
                vals.append(0.0)
                stats['kl_lines'] += 1
            elif general.lower() == 'free':
                vals.append(0.0)
            else:
                m = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)\s*%', general)
                if m:
                    vals.append(float(m.group(1)))
                else:
                    stats['specific_left_out'] += 1
        if vals:
            out[hs6] = sum(vals) / len(vals)
    stats['hs6'] = len(out)
    return out, stats
