"""Section 301 and 232 scenario layer (us_301_232). Not in the baseline power of the tariff.

GTAP 12 ch.11B §B.4 leaves trade remedies out of the baseline. The layer is written as
a separate file for a scenario. HTS 2022 revision 12 footnotes give the 301 list and the
232 steel (note 16) and aluminium (note 19) lines; each HS6 is the unweighted share of
its 8- and 10-digit leaves. us_section232_calendar.csv gives the months each partner
faced the 232 duty in 2022.
"""
import json
import re
from collections import defaultdict

from .config import ConfigError, read_table
from .preferences import EU27

# The leaf counts the HTS reading must reproduce (PR #73 review).
US_EXPECTED = {'hs6_with_301': 5162, 'hs6_with_steel': 171, 'hs6_with_aluminium': 24}
LIST_1_3 = ('9903.88.01', '9903.88.02', '9903.88.03', '9903.88.04')
LIST_4A = '9903.88.15'
EXCLUDED = ('9903.88.66', '9903.88.67')


def _flags(notes):
    low = notes.lower()
    rate = 0.0
    if not any(x in notes for x in EXCLUDED):
        if any(x in notes for x in LIST_1_3):
            rate = 25.0
        elif LIST_4A in notes:
            rate = 7.5
    return rate, 'note 16 to subchapter' in low, 'note 19 to subchapter' in low


def us_extra(path):
    """HS6 -> (301 percent, steel leaf share, aluminium leaf share)."""
    with open(path, encoding='utf-8') as fh:
        data = json.load(fh)
    notes = {}
    for row in data:
        code = re.sub(r'\D', '', row.get('htsno') or '')
        if len(code) not in (8, 10) or code.startswith('99'):
            continue
        text = ' '.join((fn.get('value') or '') for fn in (row.get('footnotes') or []))
        notes[code] = (notes.get(code, '') + ' ' + text).strip()
    parents = {c[:8] for c in notes if len(c) == 10}
    own_markers = LIST_1_3 + (LIST_4A,) + EXCLUDED

    def resolved(code):
        rate, steel, alum = _flags(notes.get(code, ''))
        if len(code) == 10:
            p_rate, p_steel, p_alum = _flags(notes.get(code[:8], ''))
            text = notes.get(code, '')
            if not any(x in text for x in own_markers):
                rate = p_rate
            if 'note 16 to subchapter' not in text.lower():
                steel = p_steel
            if 'note 19 to subchapter' not in text.lower():
                alum = p_alum
        return rate, steel, alum

    leaves = defaultdict(list)
    for code in notes:
        if len(code) == 10 or code not in parents:
            leaves[code[:6]].append(code)
    out = {}
    stats = {'hs6_with_301': 0, 'hs6_with_steel': 0, 'hs6_with_aluminium': 0}
    for hs, codes in leaves.items():
        got = [resolved(c) for c in codes]
        n = float(len(got))
        rec = (sum(g[0] for g in got) / n, sum(1.0 for g in got if g[1]) / n, sum(1.0 for g in got if g[2]) / n)
        if any(rec):
            out[hs] = rec
            stats['hs6_with_301'] += rec[0] > 0
            stats['hs6_with_steel'] += rec[1] > 0
            stats['hs6_with_aluminium'] += rec[2] > 0
    if stats != US_EXPECTED:
        raise ConfigError(f'HTS leaf counts {stats} differ from {US_EXPECTED}')
    return out


def calendar(path=None):
    """partner ISO -> (steel share of 2022, aluminium share), and the default."""
    out, default = {}, None
    for row in read_table('us_section232_calendar.csv', ('group', 'members', 'steel_months_on', 'aluminium_months_on'), path=path):
        pair = (int(row['steel_months_on']) / 12.0, int(row['aluminium_months_on']) / 12.0)
        if row['group'] == 'default':
            default = pair
            continue
        for iso in row['members'].split(';'):
            if iso in out:
                raise ConfigError(f'{iso} is in two Section 232 groups')
            out[iso] = pair
    if default is None or EU27 - set(out):
        raise ConfigError('Section 232 calendar lacks the default or an EU member')
    return out, default


class AddonAccumulator:
    """Per (partner region, sector): BACI-weighted 301 and 232 add-on percent on USA imports."""

    def __init__(self, extra, cal, default):
        self.extra, self.cal, self.default = extra, cal, default
        self.n301 = defaultdict(float)
        self.n232 = defaultdict(float)
        self.den = defaultdict(float)
        self.outside = [0, 0.0]

    def add(self, exp_iso, partner_region, short, hs, v, goods):
        rec = self.extra.get(hs)
        if short not in goods:
            if rec:
                self.outside[0] += 1
                self.outside[1] += v
            return
        key = (partner_region, short)
        self.den[key] += v
        if not rec:
            return
        r301, steel, alum = rec
        steel_on, alum_on = self.cal.get(exp_iso, self.default)
        if exp_iso == 'CHN' and r301:
            self.n301[key] += r301 * v
        if steel and steel_on:
            self.n232[key] += 25.0 * steel_on * steel * v
        if alum and alum_on:
            self.n232[key] += 10.0 * alum_on * alum * v

    def rates(self):
        out = {}
        for key, den in self.den.items():
            if den > 0 and (self.n301[key] > 1e-12 or self.n232[key] > 1e-12):
                out[key] = (self.n301[key] / den, self.n232[key] / den)
        return out
