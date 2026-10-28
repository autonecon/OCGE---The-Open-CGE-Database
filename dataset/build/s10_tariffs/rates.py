"""The applied rate of one HS6 line for one importer and one exporter (ch.11B best-applied).

applied = min(MFN, every usable preference), at the HS6 simple averages WITS gives.
The schedule is the importer's own TRAINS schedule on its own nomenclature, after the
named overrides in s10_choices.csv. Each override names its row.
"""
import csv
from collections import defaultdict

from . import overrides as ov
from .config import ConfigError, read_table
from .preferences import EU27, pref_rate
from .sources import Schedule, parse_mfn_sdmx

EARLIER_NOMEN = {'H4': 'H4', 'HS2012': 'H4', 'H3': 'H3', 'HS2007': 'H3', 'H2': 'H2', 'HS2002': 'H2'}


class Nomen:
    """HS2022 line -> schedule code on another nomenclature (tariff_concordance).

    H6 keeps the HS2022 code; H5 uses the S01 HS2017 code; H4/H3/H2 use the UNSD HS2017
    conversion sheets. A code the sheet does not carry is kept only when the schedule has
    that same line; a neighbour is never borrowed.
    """

    def __init__(self, concord_path, earlier_paths):
        self.hs17 = {}
        self.sector = {}
        with open(concord_path, newline='') as fh:
            for row in csv.DictReader(fh):
                if row['share'] and row['sector']:
                    self.hs17[row['hs22']] = row['hs17']
                    self.sector[row['hs22']] = row['sector']
        self.earlier = {}
        for key, path in earlier_paths.items():
            with open(path, newline='') as fh:
                self.earlier[key] = {r['hs2017']: r['hs_earlier'] for r in csv.DictReader(fh)}
        self._cache = {}

    def code(self, nomen, hs22, has=None):
        key = (nomen, hs22)
        if key in self._cache:
            hit = self._cache[key]
            if hit is not None or has is None:
                return hit
        if nomen in ('H6', 'HS2022', ''):
            out = hs22
        elif nomen in ('H5', 'HS2017'):
            out = self.hs17.get(hs22) or None
        else:
            table = self.earlier.get(EARLIER_NOMEN.get(nomen, ''), {})
            out = table.get(self.hs17.get(hs22, '')) or None
            if out is None and has is not None and has(hs22):
                out = hs22
        self._cache[key] = out
        return out


# ---------------------------------------------------------------- customs unions (legal_internal_zeros)

class Unions:
    """customs_unions.csv for the full unions; the partial EU arrangements are rules here.

    forced: EU customs territory (EU27 + Monaco) is zero on every good, even over a preference.
    fill: the other unions are zero only where no preference line wins. Mercosur keeps
    chapter 87 and sugar 1701-1703. EU-Turkey covers industrial goods but not coal or steel;
    EU-Andorra chapters 25-97; EU-San Marino all but coal and steel; EEA chapters 25-97;
    Switzerland-Liechtenstein all goods.
    """
    EEA_EFTA = frozenset({'ISL', 'NOR', 'LIE'})
    COAL = ('2701', '2702', '2704')
    SUGAR = ('1701', '1702', '1703')

    def __init__(self, path=None):
        rows = read_table('customs_unions.csv', ('union_id', 'members', 'booking', 'decided_by', 'decided_on'), path=path)
        self.fill = {}
        self.screen_only = {}
        eu = None
        for row in rows:
            members = frozenset(m for m in row['members'].split(';') if m)
            if row['booking'] == 'forced':
                eu = members
            elif row['booking'] == 'fill':
                self.fill[row['union_id']] = members
            elif row['booking'] == 'screen_only':
                self.screen_only[row['union_id']] = members
            else:
                raise ConfigError(f'customs_unions.csv {row["union_id"]}: booking {row["booking"]!r}')
        if eu != EU27:
            raise ConfigError('customs_unions.csv: the forced union is not the EU27')
        self.eu_territory = EU27 | {'MCO'}

    def kind(self, imp, exp, hs):
        if imp == exp:
            return None
        eu = self.eu_territory
        if imp in eu and exp in eu:
            return 'forced'
        ch = int(hs[:2])
        pair = {imp, exp}
        if 'SMR' in pair and (pair - {'SMR'}) <= eu:
            return None if ch in (72, 73) or hs[:4] in self.COAL else 'fill'
        if 'AND' in pair and (pair - {'AND'}) <= eu:
            return 'fill' if ch >= 25 else None
        if 'TUR' in pair and (pair - {'TUR'}) <= eu:
            return 'fill' if ch >= 25 and ch not in (72, 73) and hs[:4] not in self.COAL else None
        for uid, members in self.fill.items():
            if imp in members and exp in members:
                if uid == 'MERCOSUR' and (ch == 87 or hs[:4] in self.SUGAR):
                    return None
                return 'fill'
        if ((imp in eu and exp in self.EEA_EFTA) or (exp in eu and imp in self.EEA_EFTA)) and ch >= 25:
            return 'fill'
        if pair == {'CHE', 'LIE'}:
            return 'fill'
        return None

    def related(self, imp, exp):
        """True when some line of this pair can carry a union zero."""
        eu = self.eu_territory
        if imp in eu and exp in eu:
            return True
        pair = {imp, exp}
        for x in ('SMR', 'AND', 'TUR'):
            if x in pair and (pair - {x}) <= eu:
                return True
        if any(imp in m and exp in m for m in self.fill.values()):
            return True
        if (imp in eu and exp in self.EEA_EFTA) or (exp in eu and imp in self.EEA_EFTA):
            return True
        return pair == {'CHE', 'LIE'}


# ---------------------------------------------------------------- Panama (panama_tpa)

def _tpa_line(row, decisions):
    para = row['trq_paragraph'].strip()
    tpa_text = row['tpa_rate_2022_pct'].strip()
    if not para:
        return float(tpa_text) if tpa_text else None
    kind = decisions.get(para, 'published')
    in_rate = float(row['trq_in_quota_rate_2022_pct'] or 0.0)
    over_text = row['trq_over_quota_rate_2022_pct'].strip()
    if over_text:
        over = float(over_text)
    elif 'MFN' in row['trq_over_quota_staging']:
        over = float(row['base_rate_pct']) if row['base_rate_pct'].strip() else None
    else:
        over = float(tpa_text) if tpa_text else None
    if kind == 'in':
        return in_rate
    if kind == 'over':
        return over
    if kind == 'avg':
        return in_rate if over is None else (in_rate + over) / 2.0
    return float(tpa_text) if tpa_text else None


def panama_tpa(hs22_csv, lines_csv, trq_csv):
    """HS2022 -> US-Panama TPA 2022 rate. National lines averaged inside the HS6; a TRQ line
    takes the trq_fill_rule from the quota-vs-BACI fill. Only rates below the file's MFN."""
    decisions = {}
    with open(trq_csv, newline='') as fh:
        for row in csv.DictReader(fh):
            fill = (row['baci_t_over_quota'] or '').strip()
            if not fill:
                kind = 'published'
            else:
                v = float(fill)
                kind = 'in' if v < 0.90 else ('over' if v > 0.98 else 'avg')
            decisions[row['appendix_para'].strip()] = kind
    by02 = defaultdict(list)
    with open(lines_csv, newline='') as fh:
        for row in csv.DictReader(fh):
            row = {k: (v or '') for k, v in row.items()}
            rate = _tpa_line(row, decisions)
            if rate is not None:
                by02[row['hs02_6']].append(rate)
    out = {}
    with open(hs22_csv, newline='') as fh:
        for row in csv.DictReader(fh):
            vals = [r for code in (row['hs02_6_linked'] or '').replace(';', ' ').split() for r in by02.get(code, ())]
            if vals:
                rate = sum(vals) / len(vals)
            elif (row['tpa_rate_2022_pct_inquota_basis'] or '').strip():
                rate = float(row['tpa_rate_2022_pct_inquota_basis'])
            else:
                continue
            mfn = (row['mfn_2022_trains_pct'] or '').strip()
            if mfn and rate >= float(mfn) - 1e-9:
                continue
            out[row['hs22_6'].zfill(6)] = rate
    return out


# ---------------------------------------------------------------- schedules and overrides

def tunisia_schedule(path):
    """tunisia_schedule: TRAINS 2016 Reported (H4); Finance Law 2018 art. 39 raises 20 to 30 on ch.25-97."""
    with open(path, 'rb') as fh:
        lines = parse_mfn_sdmx(fh.read())
    sch = Schedule('TUN', 'H4', 2016, 'tun_trains2016_lf2018')
    raised = 0
    for code, (_y, value, _na, _nom, datatype) in lines.items():
        if datatype != 'Reported':
            continue
        if 25 <= int(code[:2]) <= 97 and abs(value - ov.TUN_RAISE_FROM) < 0.005:
            sch.set(code, ov.TUN_RAISE_TO, 'tun_art39')
            raised += 1
        else:
            sch.set(code, value, 'reported')
    return sch, raised


def apply_overrides(schedules, nomen, hts_kl, log, kl_overlay=True, trq_measure=ov.TRQ_MEASURE_PLAN, egy_sublines=True,
                    sourced=()):
    """The named schedule overrides, before the minimum with preferences. Returns the raw values replaced."""
    raw = {}

    def put(iso, hs22, value, how):
        sch = schedules.get(iso)
        if sch is None:
            raise ConfigError(f'{iso} has no MFN schedule for override {how}')
        code = nomen.code(sch.nomen, hs22) or hs22
        raw[(iso, hs22)] = sch.rate.get(code)
        sch.set(code, value, how)

    # ave_outlier_rule class A: Zambia mixed duties take the ad valorem alternative.
    for hs, rate in ov.ZMB_ADVALOREM.items():
        put('ZMB', hs, rate, 'class_a_ad_valorem')
    # korea_article71 and the Korea blends.
    put('KOR', '120190', ov.soy_rate(), 'korea_soy')
    for hs in ('271111', '271121'):
        put('KOR', hs, ov.lng_rate(), 'korea_lng')
    put('KOR', '270900', ov.crude_rate(), 'korea_crude')
    for hs, (legal, component) in ov.korea_article71_lines().items():
        put('KOR', hs, legal, component)
    for hs, spec in ov.korea_trq_rates(trq_measure).items():
        prior = schedules['KOR'].how.get(hs, '')
        if prior.startswith('korea_'):
            raise ConfigError(f'Korea TRQ {hs} collides with {prior}')
        put('KOR', hs, spec['rate'], 'korea_trq')
    # usa_pharma_appendix: HTS 2022 Special K and L are erga omnes zeros (unless the row says no overlay).
    if kl_overlay:
        if schedules['USA'].nomen not in ('H6', 'HS2022'):
            raise ConfigError('USA K/L overlay needs an HS2022 schedule')
        for hs, rate in hts_kl.items():
            put('USA', hs, rate, 'hts_pharma_kl')
    # morocco_wheat, cambodia_271012.
    for hs in ov.MOROCCO_WHEAT:
        put('MAR', hs, 0.0, 'morocco_wheat')
    put('KHM', '271012', ov.KHM_GASOLINE, 'cambodia_271012')
    # egypt_mixed_sublines: the non-alcoholic national line on two mixed HS6 (Decree 218/2022).
    if egy_sublines:
        for hs, (rate, _cite) in ov.EGY_MIXED_SUBLINES.items():
            put('EGY', hs, rate, 'egypt_mixed_subline')
    # beta v5 K / S5 BGD: sourced line overrides whose switch is on (overrides.sourced_lines)
    for iso, hs, rate, how in sourced:
        put(iso, hs, rate, how)
    log(f'overrides: {len(raw)} lines')
    return raw


def egypt_240220(schedules, nomen, uv_usd_per_kg, fx):
    """ave_outlier_rule class A: EGP 100 per kg net over the BACI 2022 FOB unit value."""
    ave = ov.EGY_240220_EGP_PER_KG / (fx * uv_usd_per_kg) * 100.0
    sch = schedules['EGY']
    code = nomen.code(sch.nomen, '240220') or '240220'
    before = sch.rate.get(code)
    sch.set(code, ave, 'class_a_specific')
    return ave, before


def egypt_fx(path):
    with open(path, newline='') as fh:
        for row in csv.DictReader(fh):
            if row['iso3'] == 'EGY' and row['year'] == '2022':
                return float(row['lcu_per_usd'])
    raise ConfigError('Egypt 2022 exchange rate is not in the WDI file')


# ---------------------------------------------------------------- parent customs territories

def load_parent_territories(path=None):
    """territory -> (parent schedule key, preference reporter, first chapter, excluded prefixes)
    (importer_without_schedule). The territory applies the parent's customs tariff on those goods."""
    rows = read_table('parent_customs_territory.csv', ('territory', 'parent_schedule', 'preference_reporter',
                                                       'first_chapter', 'excluded_prefixes', 'legal_basis',
                                                       'decided_by', 'decided_on'), path=path)
    out = {}
    for row in rows:
        t = row['territory']
        if t in out:
            raise ConfigError(f'parent_customs_territory.csv: {t} appears twice')
        if not row['decided_by'] or not row['decided_on'] or not row['legal_basis'] or not row['parent_schedule']:
            raise ConfigError(f'parent_customs_territory.csv {t}: decision, basis or parent is blank')
        if not row['first_chapter'].isdigit() or not 1 <= int(row['first_chapter']) <= 97:
            raise ConfigError(f'parent_customs_territory.csv {t}: first_chapter {row["first_chapter"]!r}')
        excl = tuple(x for x in row['excluded_prefixes'].split(';') if x)
        out[t] = (row['parent_schedule'], row['preference_reporter'], int(row['first_chapter']), excl)
    return out


def load_tun_lists(path):
    """HS2002 6-digit code -> (List I, List II, List III) counts of the Tunisian national lines of Protocol I
    that fall in it. The HS6 rate averages the national lines (as MAcMap), so a partly listed HS6 takes
    the listed share of the rate."""
    out = {}
    with open(path, newline='') as fh:
        for row in csv.DictReader(fh):
            lst, hs6 = row['list'], row['hs6_2002']
            if lst not in ('I', 'II', 'III'):
                raise ConfigError(f'{path}: list {lst!r}')
            n = out.setdefault(hs6, [0, 0, 0])
            n[('I', 'II', 'III').index(lst)] += 1
    if not any(n[1] or n[2] for n in out.values()):
        raise ConfigError(f'{path}: no List II or III line')
    return {k: tuple(v) for k, v in out.items()}


def parent_covers(entry, hs22):
    _key, _rep, first, excl = entry
    return int(hs22[:2]) >= first and not any(hs22.startswith(x) for x in excl)


# ---------------------------------------------------------------- the line rate

class Tariffs:
    """applied(imp, exp, hs22) -> (applied, mfn, how). applied None means no rate for the line."""

    def __init__(self, schedules, state, nomen, unions, tpa, uk_applied, turkey_rule=True, parents=None, tun_lists=None):
        self.turkey_rule = turkey_rule
        self.tun_lists = tun_lists or {}
        self.parents = parents or {}
        self.schedules = schedules
        self.state = state
        self.nomen = nomen
        self.unions = unions
        self.tpa = tpa
        self.uk_applied = uk_applied
        self._mfn = {}

    def schedule(self, iso):
        if iso in EU27:
            return self.schedules.get('EUN')
        return self.schedules.get(iso)

    def has_schedule(self, iso):
        return iso in ('IRQ', 'PRK') or iso in self.parents or self.schedule(iso) is not None

    def parent_line(self, iso, hs22):
        """The parent schedule's own line rate for a covered territory line, else None (S10-Hparent)."""
        entry = self.parents.get(iso)
        if entry is None or not parent_covers(entry, hs22):
            return None
        sch = self.schedules[entry[0]]
        code = self.nomen.code(sch.nomen, hs22, has=lambda c: c in sch.rate)
        return sch.rate.get(code)

    def pref_reporter(self, iso, hs22):
        """The ISO whose preferences apply on the line: the parent's for a covered territory line."""
        entry = self.parents.get(iso)
        if entry is not None and parent_covers(entry, hs22):
            rep = entry[1]
            return next(iter(sorted(EU27))) if rep == 'EUN' else rep
        return iso

    def sched_code(self, nomen, hs22):
        return self.nomen.code(nomen, hs22)

    def _own(self, sch, hs22):
        code = self.nomen.code(sch.nomen, hs22, has=lambda c: c in sch.rate)
        if not code or code not in sch.rate:
            return None, 'specific_no_ave' if code in sch.specific else 'none', code
        return sch.rate[code], sch.how[code], code

    def mfn(self, iso, hs22):
        key = (iso, hs22)
        hit = self._mfn.get(key)
        if hit is not None:
            return hit
        if iso == 'IRQ':                      # iraq_tariffs
            out = (ov.iraq_rate(hs22), 'iraq')
        elif iso == 'PRK':                    # prk_tariff
            out = (ov.PRK_FLAT, 'prk')
        elif iso in self.parents:             # importer_without_schedule: parent customs tariff
            entry = self.parents[iso]
            if not parent_covers(entry, hs22):
                out = (None, 'no_schedule')
            else:
                rate, _how = self._own(self.schedules[entry[0]], hs22)[:2]
                out = (rate, 'parent_schedule' if rate is not None else _how)
        else:
            sch = self.schedule(iso)
            out = (None, 'no_schedule') if sch is None else self._own(sch, hs22)[:2]
        self._mfn[key] = out
        return out

    def _tunisia(self, exp, hs22):
        sch = self.schedules['TUN']
        base, _how, _code = self._own(sch, hs22)
        ch = int(hs22[:2])
        rate = base
        if (exp in EU27 or (exp == 'GBR' and 'TUN' in self.uk_applied)) and ch >= 25:
            rate = 0.0
        elif exp == 'TUR' and self.turkey_rule and base is not None and 25 <= ch <= 97:
            # Türkiye-Tunisia FTA Protocol I: zero since 2014 except List III (never reduced, MFN) and the List II goods
            # that the 2018 Finance Law brought back in its chapters (60% of MFN in 2022).
            n1, n2, n3 = self.tun_lists.get(self.nomen.code('H2', hs22) or '', (0, 0, 0))
            share2 = ov.TUN_TUR_LF2018_SHARE_2022 if ch in ov.TUN_TUR_LF2018_CHAPTERS else 0.0
            rate = base * (n3 + n2 * share2) / (n1 + n2 + n3) if n1 + n2 + n3 else 0.0
        elif exp in ov.GAFTA:
            rate = 0.0
        else:
            kind = self.unions.kind('TUN', exp, hs22)
            if kind == 'forced' or (kind == 'fill' and rate is None):
                rate = 0.0
        return rate, base, 'tun'

    def line(self, imp, exp, hs22):
        if imp == 'TKM':                      # tkm_tariffs
            return None, None, 'tkm_exception'
        if imp == 'TUN':                      # tunisia_schedule
            return self._tunisia(exp, hs22)
        mfn, how = self.mfn(imp, hs22)
        pref = None
        if imp not in ('IRQ', 'PRK'):
            rep = self.pref_reporter(imp, hs22)
            if exp != rep:
                pref, code, _fam = pref_rate(self.state, rep, exp, hs22, self.sched_code)
        if imp == 'PAN' and exp == 'USA':     # panama_tpa
            tpa = self.tpa.get(hs22)
            if tpa is not None:
                pref = tpa if pref is None else min(pref, tpa)
        if imp == 'NCL' and exp in ov.NCL_DD_EXEMPT and mfn is not None:   # ncl_schedule
            return 0.0, mfn, 'ncl_eu_oct'
        kind = self.unions.kind(imp, exp, hs22)
        if kind == 'forced':
            return 0.0, mfn, 'cu_forced'
        if mfn is None and pref is None:
            return (0.0, None, 'cu_fill') if kind == 'fill' else (None, None, how)
        if mfn is None:
            return pref, None, 'preference_only'
        if pref is None:
            return (0.0, mfn, 'cu_fill') if kind == 'fill' else (mfn, mfn, how)
        if pref < mfn - 1e-9:
            return pref, mfn, 'preference'
        return mfn, mfn, how

    def related(self, imp, exp):
        """True when the pair can differ from the importer's MFN on some line."""
        if imp in ('TUN', 'NCL') or (imp == 'PAN' and exp == 'USA'):
            return True
        if exp in self.state['cover'].get(imp, {}):
            return True
        if imp in self.parents and exp in self.state['cover'].get(self.pref_reporter(imp, '999999'), {}):
            return True
        return self.unions.related(imp, exp)
