"""Tariff-rate quotas outside Korea and Panama: the MAcMap fill rule on the TRAINS HS6 averages
(trq_outside_kor_pan, round-3 fix wE2; GTAP 12 ch.11B uses MAcMap-HS6, whose TRQ rule is Guimbard,
Jean, Mimouni and Pichot 2012 pp.10-11, trq_fill_rule).

The national tariffs of Canada, Switzerland, Japan and China give an in-quota and an over-quota
national line for each quota line, and the TRAINS HS6 simple average counts both (Norway and Israel were
checked and do not have that structure, CHECKED_NOT_APPLIED). MAcMap
treats each quota line as one line at the regime rate: the in-quota rate when the fill is below 90
percent, the over-quota rate above 98 percent, the mean in between. This module replaces the HS6
average on the MFN schedule and on every bulk preference record of those importers by

    rate = (Sum - k (r_in + r_out) + sum of regime rates over the k quota lines) / (n - k)

where Sum and n are the TRAINS sum of rates and number of lines (WITS bulk AVE files, the same rows
S10 books), k is the number of in-quota national lines that the WTO notification lists in the HS6, and
r_in and r_out are the HS6 minimum and maximum line rates (trq_line_rates: the in-quota line is the
HS6 minimum and the over-quota line its maximum; the national line rates are not in the sources).

Fill: WTO AG-IMS Table MA:2 notifications, in-quota imports over the quota quantity, implementation
year 2022 (dataset/data/wto_agims_trq/). A national line in several quotas takes the summed imports
over the summed quantities. A quota with no notified imports takes the in-quota rate (trq_no_fill;
the BACI HS6 tonnage cannot separate quota lines from the other lines of a heading). A preference
record whose in-quota lines are below the MFN ones on the same nomenclature and year (HS6 minimum
below the MFN minimum, or the same maximum and line count with a lower sum) carries a bilateral quota
(CUSMA, CETA, CPTPP and the like) with its own preferential in-quota rate; no bilateral 2022 fill is in
the sources, so its quota lines take the in-quota rate (trq_bilateral_fill).

An HS6 is changed only where the line structure is a quota pair: no line without an AVE, minimum
below maximum, 1 <= k <= n/2, and the held rate equal to the bulk simple average. Every other TRQ
heading is left as held and listed with its reason (S10-Rtrq).
"""
import csv
import io
import zipfile
from collections import defaultdict

from .config import ConfigError

Q_TRQ = 'GTAP 12 ch.11B (MAcMap-HS6); Guimbard, Jean, Mimouni and Pichot 2012 pp.10-11'
# Importers whose national tariff prints an in-quota and an over-quota line for each quota line.
IMPORTERS = ('CAN', 'CHE', 'JPN', 'CHN')
# Checked and not applied: their TRAINS HS6 lines are not quota pairs. Norway prints the ordinary
# (over-quota) duty only (ISSUES 2026-10-22, Tolltariffen 2022): the notified quota lines are product lines,
# so removing them would book another product's rate. Israel: 25 of its 30 notified quota headings have one
# rate on every line (min = max) and 21 hold lines without an AVE.
CHECKED_NOT_APPLIED = {'NOR': 'quota lines are product lines; the in-quota rate is not a national line',
                       'ISR': 'quota headings carry one rate on every line or lines without an AVE'}
FILL_YEAR = 2022
IN_BELOW, OUT_ABOVE = 0.90, 0.98          # trq_fill_rule bands (overrides.trq_shadow)
TOL = 0.006                               # bulk SimpleAverage is printed to 2 decimals
REPORT_COLUMNS = ['importer', 'partner', 'nomen', 'hs6', 'tqids', 'k_quota_lines', 'lines', 'regimes', 'held_pct',
                  'new_pct', 'min_pct', 'max_pct', 'status', 'source']


def regime_of(fill):
    """trq_fill_rule on a fill (None: no notified imports -> in-quota, trq_no_fill)."""
    if fill is None:
        return 'in_quota_no_fill'
    if fill < IN_BELOW:
        return 'in_quota'
    if fill > OUT_ABOVE:
        return 'out_of_quota'
    return 'average'


def read_ma2(path, importers=IMPORTERS, year=FILL_YEAR):
    """{iso: {national line: [(tqid, quota, imports or None, unit, document)]}} for the implementation year."""
    out = defaultdict(lambda: defaultdict(list))
    seen = set()
    with open(path, newline='', encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            if r['iso3'] not in importers or int(r['implementation_year']) != year:
                continue
            seen.add(r['iso3'])
            quota = float(r['quota_qty']) if r['quota_qty'] else None
            imp = float(r['in_quota_imports_qty']) if r['in_quota_imports_qty'] and r['not_opened'] != 'yes' else None
            for line in (t.strip().replace('.', '') for t in r['tariff_lines'].split(',')):
                if line:
                    out[r['iso3']][line].append((r['tqid'], quota, imp, r['unit'], r['document']))
    missing = sorted(set(importers) - seen)
    if missing:
        raise ConfigError(f'{path}: no {year} MA:2 rows for {missing}')
    return {k: dict(v) for k, v in out.items()}


def line_fill(entries):
    """Fill of one national line over the quotas that list it (same unit), or None."""
    units = {e[3] for e in entries}
    if len(units) != 1 or any(e[1] is None or e[1] <= 0 or e[2] is None for e in entries):
        return None
    return sum(e[2] for e in entries) / sum(e[1] for e in entries)


def _stats_row(row, pref):
    """(sum, min, max, n valid lines, simple average, na lines) of a WITS bulk AVE row."""
    def f(k):
        v = (row.get(k) or '').strip()
        return float(v) if v else None
    s, mn, mx, avg = f('Sum_Of_Rates'), f('Min_Rate'), f('Max_Rate'), f('SimpleAverage')
    na = int((row.get('Nbr_NA_Lines') or '0').strip() or 0)
    if pref:
        n = int(row['TotalNoOfLines']) - na
    else:
        n = int((row.get('TotalNoOfValidLines') or '0').strip() or 0)
    return s, mn, mx, n, avg, na


def read_bulk(zip_path, prefix, iso, year, nomen):
    """{(partner, hs6): stats} from the WITS bulk file <prefix>_<nomen>_<iso>_<year>_U2.zip ('000' for MFN)."""
    name = f'{prefix}_{nomen}_{iso}_{year}_U2.zip'
    out = {}
    with zipfile.ZipFile(zip_path) as outer:
        if name not in outer.namelist():
            return None
        inner = zipfile.ZipFile(io.BytesIO(outer.read(name)))
        member = [m for m in inner.namelist() if m.lower().endswith('.csv')][0]
        text = inner.read(member).decode('utf-8-sig', 'replace')
    pref = prefix == 'AVEPref'
    for row in csv.DictReader(io.StringIO(text)):
        code = (row.get('ProductCode') or '').strip()
        partner = (row.get('Partner') or '000').strip() if pref else '000'
        if len(code) == 6:
            out[(partner, code)] = _stats_row(row, pref)
    return out


def coverage(lines_of_iso, hs6_universe):
    """{hs6: (k or 'all', [regime per quota line], [tqids])} from the notified national lines.
    An 8- or more-digit line counts one quota line in its HS6; a 6-digit line covers the HS6 and a 4-digit
    line every HS6 of the heading ('all': each line of the HS6 is in a pair). A line whose HS6 is not in the
    schedule's nomenclature covers the schedule HS6 under its first five digits."""
    per = defaultdict(lambda: [set(), set(), []])
    for line, entries in lines_of_iso.items():
        reg = regime_of(line_fill(entries))
        tq = {e[0] for e in entries}
        if len(line) >= 8 and line[:6] not in hs6_universe:
            # a line notified in an earlier HS (China wheat 1001.10, 1001.90 -> HS2022 1001.11/19, 1001.91/99):
            # every HS6 of the schedule under its 5-digit subheading is a quota heading
            line = line[:5]
        if len(line) >= 8:
            slot = per[line[:6]]
            if line not in slot[0]:
                slot[0].add(line)
                slot[2].append(reg)
            slot[1] |= tq
        elif len(line) in (4, 5, 6):
            for h in (c for c in hs6_universe if c.startswith(line)):
                slot = per[h]
                slot[0].add('all')
                slot[2].append(reg)
                slot[1] |= tq
    out = {}
    for h, (lines, tq, regs) in per.items():
        if 'all' in lines:
            out[h] = ('all', sorted(set(regs)), sorted(tq))
        else:
            out[h] = (len(lines), regs, sorted(tq))
    return out


def new_rate(st, k, regs, bilateral=False):
    """(new rate, status) for one HS6 from its bulk stats."""
    s, mn, mx, n, avg, na = st
    if s is None or mn is None or mx is None or avg is None or n <= 0:
        return None, 'no_rate'
    if na:
        return None, 'lines_without_ave'
    if not mn < mx - 1e-9:
        return None, 'no_pair_structure'
    if k == 'all':
        if n % 2:
            return None, 'odd_line_count'
        k = n // 2
        regs = [regs[0] if len(set(regs)) == 1 else 'average'] * k
    if not 1 <= k <= n / 2:
        return None, 'more_quota_lines_than_pairs'
    if bilateral:
        regs = ['in_quota_bilateral'] * k
    p = 0.0
    for r in regs:
        p += mn if r.startswith('in_quota') else mx if r == 'out_of_quota' else 0.5 * (mn + mx)
    rate = (s - k * (mn + mx) + p) / (n - k)
    return min(max(rate, mn), mx), 'applied'


def is_bilateral(st, ms):
    """trq_bilateral_fill: the preference stats st have in-quota lines below the MFN stats ms of the same
    nomenclature and year: a lower minimum, or the same maximum and line count with a lower sum."""
    if not st or not ms or None in (st[0], st[1], st[2], ms[0], ms[1], ms[2]):
        return False
    if st[1] < ms[1] - 1e-6:
        return True
    return abs(st[2] - ms[2]) <= 1e-6 and st[3] == ms[3] and st[0] < ms[0] - 1e-6


def _fill_text(regs):
    return ';'.join(sorted(set(regs)))


def apply(schedules, merged, ma2, mfn_zip, pref_zip, choice, log):
    """Apply the fill rule in place on the MFN schedules and the merged preference records.
    Returns (report rows, applied MFN expectations [(iso, code, rate)], applied preference count)."""
    rows, expect, n_pref = [], [], 0
    if choice != 'wto_ma2_2022_fill_rule_on_quota_line_pairs':
        return rows, expect, n_pref
    for iso in IMPORTERS:
        sch = schedules.get(iso)
        if sch is None:
            raise ConfigError(f'trq: {iso} has no MFN schedule')
        mfn = read_bulk(mfn_zip, 'AVEMFN', iso, sch.year, sch.nomen)
        if mfn is None:
            raise ConfigError(f'trq: no WITS bulk MFN file for {iso} {sch.year} {sch.nomen}')
        universe = {h for (_p, h) in mfn}
        cov = coverage(ma2.get(iso, {}), universe)
        for h, (k, regs, tq) in sorted(cov.items()):
            st = mfn.get(('000', h))
            src = f'WTO AG-IMS MA:2 {FILL_YEAR}; WITS AVEMFN {sch.nomen} {iso} {sch.year}'
            if st is None:
                rows.append([iso, '000', sch.nomen, h, ' '.join(tq), str(k), '', _fill_text(regs), '', '', '', '', '', 'not_in_schedule', src])
                continue
            held = sch.rate.get(h)
            rate, status = new_rate(st, k, regs)
            if status == 'applied' and (held is None or abs(held - st[4]) > TOL):
                rate, status = None, 'held_differs_from_bulk'
            if status == 'applied' and sch.how.get(h) not in ('reported', 'ave', 'blank'):
                rate, status = None, 'other_override'
            if status == 'applied':
                sch.set(h, rate, 'trq_fill')
                expect.append((iso, h, rate))
            rows.append([iso, '000', sch.nomen, h, ' '.join(tq), str(k), str(st[3]), _fill_text(regs), f'{held}' if held is not None else '',
                         '' if rate is None else f'{rate:.6f}', f'{st[1]}', f'{st[2]}', status, src])
        # preference records of the importer (bulk lines only)
        files, mfn_files = {}, {}
        for (piso, partner, nomen), rec in sorted(merged.items()):
            if piso != iso:
                continue
            for h in sorted(set(rec['rates']) & set(cov)):
                if rec['rate_source'].get(h) != 'bulk':
                    continue
                year = rec['rate_year'][h]
                key = (nomen, year)
                if key not in files:
                    files[key] = read_bulk(pref_zip, 'AVEPref', iso, year, nomen) or {}
                st = files[key].get((partner, h))
                if st is None:
                    continue
                k, regs, tq = cov[h]
                if key not in mfn_files:
                    mfn_files[key] = read_bulk(mfn_zip, 'AVEMFN', iso, year, nomen) or {}
                ms = mfn_files[key].get(('000', h))
                bilateral = is_bilateral(st, ms)
                held = rec['rates'][h]
                rate, status = new_rate(st, k, regs, bilateral=bilateral)
                if status == 'applied' and abs(held - st[4]) > TOL:
                    rate, status = None, 'held_differs_from_bulk'
                if status == 'applied':
                    rec['rates'][h] = rate
                    n_pref += 1
                rows.append([iso, partner, nomen, h, ' '.join(tq), str(k), str(st[3]),
                             'bilateral_in_quota' if bilateral else _fill_text(regs), f'{held}',
                             '' if rate is None else f'{rate:.6f}', f'{st[1]}', f'{st[2]}', status,
                             f'WTO AG-IMS MA:2 {FILL_YEAR}; WITS AVEPref {nomen} {iso} {year}'])
    log(f'trq fill rule: {len(expect)} MFN HS6 and {n_pref} preference HS6 lines changed; {len(rows)} TRQ rows')
    return rows, expect, n_pref


def check(rows, schedules, merged, expect):
    """S10-Htrq: every applied MFN line is on the schedule at its rule rate with how=trq_fill, every
    applied rate lies within the HS6 minimum and maximum, and every report row has a status."""
    bad = []
    for iso, h, rate in expect:
        sch = schedules.get(iso)
        if sch is None or abs(sch.rate.get(h, -1.0) - rate) > 1e-9 or sch.how.get(h) != 'trq_fill':
            bad.append(f'{iso} {h} not on the schedule at {rate}')
    for r in rows:
        if not r[12]:
            bad.append(f'{r[0]} {r[1]} {r[3]} no status')
        if r[12] == 'applied':
            new, mn, mx = float(r[9]), float(r[10]), float(r[11])
            if not mn - 1e-9 <= new <= mx + 1e-9:
                bad.append(f'{r[0]} {r[1]} {r[3]} {new} outside [{mn}, {mx}]')
            if r[1] != '000':
                rec = next((v for (i, p, n), v in merged.items() if i == r[0] and p == r[1] and n == r[2]), None)
                if rec is None or abs(rec['rates'].get(r[3], -1.0) - new) > 1e-5:
                    bad.append(f'{r[0]} {r[1]} {r[3]} preference not at {new}')
    applied = sum(1 for r in rows if r[12] == 'applied')
    return len(bad), not bad, (f'{applied} HS6 lines changed of {len(rows)} TRQ rows' if not bad else '; '.join(bad[:10]))
