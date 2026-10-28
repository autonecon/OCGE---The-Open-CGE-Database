"""HS6 line rates to region-pair sector rates with BACI weights (tariff_weights, ch.11B §B.3).

The weights are the 3-year average imports around the reference year, as MAcMap does for
GTAP (2021-2023 for 2022). 2022 and 2023 are BACI HS22. 2021 exists only as BACI HS17; each
HS17 flow goes to its HS22 codes by the UNSD HS2022-HS2017 correlation table, split over
several HS22 codes by their 2022 world imports (WeightYears).

Pass 1 reads BACI 2022 for totals: importer x HS6 imports, the Egypt 240220 unit value, the
HS lines outside the goods sectors and the export-subsidy base.
Pass 2 prices every BACI flow of the three years with Tariffs.line() and sums rate x value / 3
over member ISOs
into (importer region, exporter region, sector). A flow inside one composite region is
priced at its member-pair rate (composite_diagonal_tariffs). A flow with no rate (TKM,
a specific duty with no AVE, an importer with no schedule) or a preference with no MFN
is left out of both sums.

A cell that has trade in VCIF and no BACI weight takes the pair's own HS6 rates weighted
by the importer's total imports of each HS6 (missing_baci_weight, Guimbard et al. 2012
p.10). Importer ISOs with no schedule are left out of that weight, except the
territories that apply their parent's customs tariff (importer_without_schedule).
"""
import csv
import io
import zipfile
from collections import defaultdict

from .overrides import iraq_band


def _rows(fh):
    reader = csv.reader(fh)
    head = next(reader)
    idx = {name: i for i, name in enumerate(head)}
    ii, jj, kk, vv, qq = idx['i'], idx['j'], idx['k'], idx['v'], idx['q']
    for row in reader:
        v = float(row[vv] or 0.0)
        if v:
            yield row[ii], row[jj], row[kk].zfill(6), v, row[qq]


def read_baci(path, member=None):
    """Rows of one BACI year: a CSV on disk, or a member of a BACI zip."""
    if member is None:
        with open(path, newline='') as fh:
            yield from _rows(fh)
    else:
        with zipfile.ZipFile(path) as zf, zf.open(member) as raw:
            yield from _rows(io.TextIOWrapper(raw, encoding='utf-8', newline=''))


def hs17_to_hs22(xlsx_path):
    """UNSD HS2022-HS2017 conversion sheet: HS2017 code -> sorted HS2022 codes. Each HS2022 code has
    exactly one HS2017 source, so the HS2022 codes of one HS2017 code are a partition. (The correlation
    sheet is n:n: a new HS2022 heading such as 8524 or 8549 sits in the target list of hundreds of
    HS2017 codes, and splitting over it moves machinery and vehicle parts into electronics.)"""
    import openpyxl
    wb = openpyxl.load_workbook(xlsx_path, read_only=True)
    ws = wb['HS2022-HS2017 Conversions']
    out = defaultdict(set)
    seen = set()
    for row in ws.iter_rows(min_row=2, values_only=True):
        a, b = str(row[0] or '').strip(), str(row[1] or '').strip()
        if a.isdigit() and b.isdigit():
            if a in seen:
                raise ValueError(f'HS2022 {a} has two HS2017 sources in the conversion sheet')
            seen.add(a)
            out[b.zfill(6)].add(a.zfill(6))
    wb.close()
    return {k: sorted(v) for k, v in out.items()}


class WeightYears:
    """tariff_weights: the BACI flows of the weight years, each year with weight 1/n.

    sources: [(year, 'hs22' | 'hs17', path, zip member or None)]. world22: HS22 code -> 2022
    world imports, the split key for an HS17 code with several HS22 codes. stats[year] =
    [value read, value yielded, value dropped (HS17 code not in the table), value split equally].
    """

    def __init__(self, sources, corr, world22):
        self.sources, self.corr, self.world22 = sources, corr, world22
        self.weight = 1.0 / len(sources)
        self.stats = {}

    def flows(self):
        """(i, j, hs22, v, q, year, weight); v is the year's own value."""
        for year, nomen, path, member in self.sources:
            st = self.stats[year] = [0.0, 0.0, 0.0, 0.0]
            for i, j, hs, v, q in read_baci(path, member):
                st[0] += v
                if nomen == 'hs22':
                    st[1] += v
                    yield i, j, hs, v, q, year, self.weight
                    continue
                parts = self.convert(hs)
                if parts is None:
                    st[2] += v
                    continue
                if len(parts) > 1 and all(w == 1.0 / len(parts) for _t, w in parts) and \
                        sum(self.world22.get(t, 0.0) for t, _w in parts) <= 0:
                    st[3] += v
                for t, share in parts:
                    st[1] += v * share
                    yield i, j, t, v * share, '', year, self.weight

    def convert(self, hs17):
        """[(hs22, share)] for one HS17 code, or None when it has no HS22 code. Several HS22 codes are
        split by 2022 world imports (equally when none of them has any). BACI keeps a few codes outside
        the HS (271000) in both revisions: the same code."""
        targets = self.corr.get(hs17) or ([hs17] if hs17 in self.world22 else None)
        if not targets:
            return None
        if len(targets) == 1:
            return [(targets[0], 1.0)]
        base = sum(self.world22.get(t, 0.0) for t in targets)
        if base <= 0:
            return [(t, 1.0 / len(targets)) for t in targets]
        return [(t, self.world22.get(t, 0.0) / base) for t in targets if self.world22.get(t, 0.0) > 0]

    def conversion_test(self, path17, member17_2022, sector_of):
        """Convert BACI HS17 2022 with the same table and split, and total both 2022 files by GTAP
        sector: {sector: (converted HS17 value, HS22 value)}. sector_of: hs22 -> sector or None."""
        conv, direct = defaultdict(float), defaultdict(float)
        for hs22, v in self.world22.items():
            direct[sector_of(hs22)] += v
        for _i, _j, hs, v, _q in read_baci(path17, member17_2022):
            parts = self.convert(hs)
            for t, share in parts or ((None, 1.0),):
                conv[sector_of(t) if t else 'dropped'] += v * share
        return {k: (conv.get(k, 0.0), direct.get(k, 0.0)) for k in set(conv) | set(direct)}


def pass_totals(baci_path, codemap, nomen, goods):
    imp_hs = defaultdict(float)     # (importer ISO, hs22) thousand USD, partners other than itself
    exp_hs = defaultdict(float)     # (exporter ISO, hs22) thousand USD, every HS line (export-subsidy base)
    service = defaultdict(float)    # importer region -> value on HS lines outside the goods sectors
    egy = [0.0, 0.0]
    outside = defaultdict(float)    # (importer ISO, hs22) for HS lines outside the goods sectors
    unmapped = defaultdict(float)   # BACI code -> value whose ISO reaches no region
    world = defaultdict(float)      # hs22 -> 2022 world imports (the HS17 2021 split key)
    for i, j, hs, v, q in read_baci(baci_path):
        world[hs] += v
        exp, imp = codemap.baci.get(i, ''), codemap.baci.get(j, '')
        if not codemap.region_of(exp):
            unmapped[i] += v
        if not codemap.region_of(imp):
            unmapped[j] += v
        if exp:
            exp_hs[(exp, hs)] += v
        short = nomen.sector.get(hs)
        if short is not None and short not in goods:
            service[codemap.region_of(imp)] += v
        if not exp or not imp or exp == imp:
            continue
        if short not in goods:
            outside[(imp, hs)] += v
            continue
        imp_hs[(imp, hs)] += v
        if imp == 'EGY' and hs == '240220':
            egy[0] += v
            egy[1] += float(q or 0.0)
    return {'imp_hs': imp_hs, 'exp_hs': exp_hs, 'service': service, 'egy_v': egy[0], 'egy_q': egy[1],
            'outside': outside, 'unmapped': unmapped, 'world': world}


class Accumulator:
    def __init__(self):
        self.num = defaultdict(float)
        self.den = defaultdict(float)
        self.mnum = defaultdict(float)
        self.mden = defaultdict(float)
        self.region_hs = defaultdict(float)     # (importer region, hs22) value with a rate
        self.no_rate = defaultdict(float)       # how -> value
        self.no_ave = defaultdict(float)        # (importer ISO, hs22) value on specific lines with no AVE
        self.pref_only = [0, 0.0]
        self.above_mfn = []
        self.irq_over = 0
        self.how = defaultdict(float)           # how -> value with a rate
        self.usa_ch = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
        self.lines = 0
        self.imp_w = defaultdict(float)         # (importer ISO, hs22) weight-year average goods imports, the NB1 weight
        self.sample = []                        # every SAMPLE_EVERY-th priced line, for S10-Hbest
        self.pan = []                           # PAN<-USA lines (hs, applied, mfn), for S10-Hpanama
        self.parent = []                        # parent-territory lines (imp, hs, mfn, parent line, applied), S10-Hparent
        self.priced = 0.0                       # value of lines that carry a rate
        self.no_rate_imp = defaultdict(float)   # (importer ISO, how) -> value with no rate
        self.imp_total = defaultdict(float)     # importer ISO -> goods value
        self.facing = defaultdict(float)        # (schedule key, schedule code) -> value that faces the MFN line
        self.facing_duty = defaultdict(float)   # same key -> duty at that MFN line, thousand USD


SAMPLE_EVERY = 37
# Lines whose applied rate is not the importer's MFN line (screens: imports that face the rate).
FACING_NOT = {'preference', 'cu_forced', 'cu_fill', 'preference_only', 'tun', 'iraq', 'prk', 'ncl_eu_oct'}


def pass_rates(years, codemap, nomen, goods, tariffs, addon=None, ref_year=2022):
    """years: a WeightYears. Each flow adds its value x the year weight. The USA chapter
    comparison with Census, the Panama sample and the parent-territory lines use the
    reference year's own flows."""
    acc = Accumulator()
    for i, j, hs, v_year, _q, year, wgt in years.flows():
        exp, imp = codemap.baci.get(i, ''), codemap.baci.get(j, '')
        if not exp or not imp or exp == imp:
            continue
        short = nomen.sector.get(hs)
        ri, re_ = codemap.region_of(imp), codemap.region_of(exp)
        v = v_year * wgt
        if addon is not None and imp == 'USA' and re_ and re_ != 'USA':
            addon.add(exp, re_, short, hs, v, goods)
        if short not in goods or not ri or not re_:
            continue
        acc.imp_w[(imp, hs)] += v
        rate, mfn, how = tariffs.line(imp, exp, hs)
        acc.lines += 1
        acc.imp_total[imp] += v
        if acc.lines % SAMPLE_EVERY == 0:
            acc.sample.append((imp, exp, hs, rate, mfn, how))
        if year == ref_year:
            if imp == 'PAN' and exp == 'USA' and rate is not None:
                acc.pan.append((hs, rate, mfn))
            if imp in tariffs.parents:
                acc.parent.append((imp, hs, mfn, tariffs.parent_line(imp, hs), rate))
            if imp == 'USA':
                slot = acc.usa_ch[int(hs[:2])]
                slot[1] += v_year
                if exp != 'CHN':
                    slot[3] += v_year
                if rate is not None and how != 'preference_only':
                    slot[0] += rate / 100.0 * v_year
                    if exp != 'CHN':
                        slot[2] += rate / 100.0 * v_year
        if rate is None or how == 'preference_only':
            acc.no_rate[how] += v
            acc.no_rate_imp[(imp, how)] += v
            if how == 'preference_only':
                acc.pref_only[0] += 1
                acc.pref_only[1] += v
            elif how == 'specific_no_ave':
                acc.no_ave[(imp, hs)] += v
            continue
        if mfn is not None and rate > mfn + 1e-4:
            acc.above_mfn.append((imp, exp, hs, rate, mfn))
        if imp == 'IRQ':
            band = iraq_band(int(hs[:2]))
            if band is not None and rate > band + 1e-6:
                acc.irq_over += 1
        key = (ri, re_, short)
        acc.num[key] += rate * v
        acc.den[key] += v
        if mfn is not None:
            acc.mnum[key] += mfn * v
            acc.mden[key] += v
        acc.region_hs[(ri, hs)] += v
        acc.how[how] += v
        acc.priced += v
        if how not in FACING_NOT:
            sch = tariffs.schedule(imp)
            if sch is not None:
                code = nomen.code(sch.nomen, hs)
                acc.facing[(sch.iso, code)] += v
                acc.facing_duty[(sch.iso, code)] += rate / 100.0 * v
    return acc


class Reference:
    """missing_baci_weight: the pair's own HS6 rates, weighted by the importer's HS6 imports."""

    def __init__(self, codemap, nomen, goods, tariffs, imp_hs):
        self.codemap, self.tariffs, self.imp_hs = codemap, tariffs, imp_hs
        self.hs_of = defaultdict(list)
        for hs, short in nomen.sector.items():
            if short in goods:
                self.hs_of[short].append(hs)
        self.region_hs = defaultdict(float)
        for (iso, hs), v in imp_hs.items():
            reg = codemap.region_of(iso)
            if reg and tariffs.has_schedule(iso):
                self.region_hs[(reg, hs)] += v
        self._line = {}
        self._plain = {}

    def _rate(self, ii, pp, hs):
        key = (ii, pp, hs)
        if key not in self._line:
            rate, mfn, how = self.tariffs.line(ii, pp, hs)
            self._line[key] = None if rate is None or how == 'preference_only' else (rate, rate if mfn is None else mfn)
        return self._line[key]

    def _mfn(self, ii, hs):
        key = (ii, '', hs)
        if key not in self._line:
            rate, how = self.tariffs.mfn(ii, hs)
            self._line[key] = None if rate is None else (rate, rate)
        return self._line[key]

    def _pair_hs(self, i_set, p_set, hs, related):
        num_a = num_m = den = 0.0
        simple = []
        for ii in i_set:
            got = []
            for pp in p_set:
                if pp == ii:
                    continue
                g = self._rate(ii, pp, hs) if (ii, pp) in related else self._mfn(ii, hs)
                if g is not None:
                    got.append(g)
            if not got:
                continue
            a = sum(x[0] for x in got) / len(got)
            m = sum(x[1] for x in got) / len(got)
            simple.append((a, m))
            w = self.imp_hs.get((ii, hs), 0.0)
            if w > 0:
                num_a += a * w
                num_m += m * w
                den += w
        if den > 0:
            return num_a / den, num_m / den
        if simple:
            return sum(x[0] for x in simple) / len(simple), sum(x[1] for x in simple) / len(simple)
        return None

    def _sector(self, ri, short, i_set, p_set, related):
        items = [(hs, self.region_hs.get((ri, hs), 0.0)) for hs in self.hs_of[short]]
        weighted = [(hs, w) for hs, w in items if w > 0]
        num_a = num_m = den = 0.0
        for hs, w in weighted:
            got = self._pair_hs(i_set, p_set, hs, related)
            if got:
                num_a += got[0] * w
                num_m += got[1] * w
                den += w
        if den > 0:
            return num_a / den, num_m / den, 'nb1_reference_group'
        simple = [g for g in (self._pair_hs(i_set, p_set, hs, related) for hs, _w in items) if g]
        if simple:
            return (sum(g[0] for g in simple) / len(simple), sum(g[1] for g in simple) / len(simple),
                    'nb1_pair_simple')
        return None, None, 'missing'

    def cell(self, ri, rp, short):
        """(applied, mfn, rule) for a region-pair sector with no BACI weight."""
        i_set = sorted(i for i in self.codemap.members.get(ri, ()) if self.tariffs.has_schedule(i))
        p_set = sorted(self.codemap.members.get(rp, ()))
        if not i_set or not p_set:
            return None, None, 'missing'
        related = {(ii, pp) for ii in i_set for pp in p_set if ii != pp and self.tariffs.related(ii, pp)}
        if not related:
            key = (ri, short, tuple(p_set) if ri == rp else None)
            if key not in self._plain:
                self._plain[key] = self._sector(ri, short, i_set, p_set, related)
            return self._plain[key]
        return self._sector(ri, short, i_set, p_set, related)
