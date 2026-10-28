"""Income and factor taxes (income_tax_source, ssc, payroll_property, pit_cit, tax_values,
tax_missing, bhr_kwt, world_sector, income_tax_aggregate). Ported after review.

OECD GRS 2022 (latest year <= 2022) first, then IMF WoRLD general government, then central
government. G111 or G11 is split PIT/CIT at the covered-country shares when no component is
published. A class with no source takes the simple average of the covered ratios. Values are
percent of GDP times the pre-removal IO GDP.
"""
import csv
from collections import defaultdict

from .util import fnum

GRS_CLASS = {'pit': ('T_1100',), 'cit': ('T_1200',), 'ssc': ('T_2000',), 'payroll_property': ('T_3000', 'T_4000')}
IMF_READ = {'G1111_POGDP_PT_R', 'G1112_POGDP_PT_R', 'G121_POGDP_PT_R', 'G113_POGDP_PT_R', 'G11_POGDP_PT_R', 'G111_POGDP_PT_R'}
IMF_SECTORS = ('S13', 'S1311MIXED')
EMPLOYER_SSC = ('T_2100', 'T_2200', 'T_2300')
APPLIES = {'pit': 'labour', 'cit': 'capital_land_natres', 'ssc': 'labour', 'payroll_property': 'all_factors'}
WORLD_COMPONENT = {'pit': 'G1111_POGDP_PT_R', 'cit': 'G1112_POGDP_PT_R', 'ssc': 'G121_POGDP_PT_R'}
Q_TAX = 'GTAP 12 ch.15 pp.1-3'
# USA 2022 GRS percent of GDP as registered (S10-Husa-grs).
USA_GRS = {'T_1100': 12.429842, 'T_1200': 2.168112, 'T_2000': 5.997122, 'T_3000': 0.013928, 'T_4000': 2.901172}


def read_grs(path):
    best = {}
    with open(path, newline='') as fh:
        for row in csv.DictReader(fh):
            if row['UNIT_MEASURE'] != 'PT_B1GQ' or row['SECTOR'] != 'S13' or not row['OBS_VALUE']:
                continue
            year = int(row['TIME_PERIOD'])
            key = (row['REF_AREA'], row['STANDARD_REVENUE'])
            if year <= 2022 and (key not in best or year >= best[key][0]):
                best[key] = (year, float(row['OBS_VALUE']))
    return best


def read_world(path):
    obs = {}
    with open(path, newline='') as fh:
        for row in csv.DictReader(fh):
            if row.get('INDICATOR') not in IMF_READ or row.get('SECTOR') not in IMF_SECTORS or row.get('UNIT') != 'PT':
                continue
            ys = row.get('TIME_PERIOD') or ''
            if not ys.isdigit() or not row.get('OBS_VALUE') or int(ys) > 2022:
                continue
            key = (row['COUNTRY'], row['INDICATOR'], row['SECTOR'])
            if key not in obs or int(ys) >= obs[key][0]:
                obs[key] = (int(ys), float(row['OBS_VALUE']))
    return obs


GFS_COMPONENT = {'pit': ('G1111',), 'cit': ('G1112',), 'ssc': ('G121',), 'payroll_property': ('G112', 'G113')}
# gulf_zakat: Saudi GFS G116 'other taxes' is zakat (MoF FY2022 end-of-year budget report: 'other taxes
# (including zakat)'), a levy on the zakat base of firms, booked with CIT on capital, land and natural resources.
ZAKAT_AS_CIT = {'SAU': 'G116'}


def read_gfs(path):
    """IMF GFS_SOO, general government S13, percent of GDP: {(iso, indicator): (year, value)}, latest year <= 2022."""
    best = {}
    with open(path, newline='') as fh:
        for row in csv.DictReader(fh):
            if row.get('SECTOR') != 'S13' or row.get('TYPE_OF_TRANSFORMATION') != 'POGDP_PT' or not row.get('OBS_VALUE'):
                continue
            year = int(row['TIME_PERIOD'])
            key = (row['COUNTRY'], row['INDICATOR'].replace('_T', ''))
            if year <= 2022 and (key not in best or year >= best[key][0]):
                best[key] = (year, float(row['OBS_VALUE']))
    return best


class Taxes:
    def __init__(self, S, C, grs, world, countries, gfs=None):
        self.S, self.C, self.grs, self.world = S, C, grs, world
        self.gfs = gfs or {}
        self.gfs_used = []
        self.countries = sorted(countries)
        self.tax = {}
        self.averages = {}

    def best_world(self, iso, ind):
        for sector in IMF_SECTORS:
            got = self.world.get((iso, ind, sector))
            if got is not None:
                return got[1], got[0], sector
        return None

    def best_gfs(self, iso, klass):
        """General-government GFS_SOO value (percent of GDP, year) of a class, or None (income_tax_source: used where
        GRS has no value and WoRLD has no general-government S13 value; GTAP 12 ch.15 uses general government)."""
        if not self.C['income_tax_source'].endswith('then_imf_gfs_soo_s13_then_world_central'):
            return None
        parts = [self.gfs.get((iso, c)) for c in GFS_COMPONENT[klass]]
        if klass == 'cit' and iso in ZAKAT_AS_CIT and self.C['gulf_zakat'] == 'sau_gfs_g116_other_taxes_incl_zakat_as_cit':
            parts.append(self.gfs.get((iso, ZAKAT_AS_CIT[iso])))
        if not parts or any(p is None for p in parts):
            return None
        self.gfs_used.append((iso, klass))
        return sum(p[1] for p in parts), max(p[0] for p in parts)

    def world_or_gfs(self, iso, ind, klass):
        """WoRLD S13, else GFS_SOO S13, else WoRLD central government: (value, year, sector, source)."""
        w = self.best_world(iso, ind)
        if w and w[2] == 'S13':
            return w[0], w[1], w[2], 'IMF WoRLD'
        g = self.best_gfs(iso, klass)
        if g:
            src = 'IMF GFS_SOO S13 ' + '+'.join(GFS_COMPONENT[klass] + ((ZAKAT_AS_CIT[iso],) if klass == 'cit' and iso in ZAKAT_AS_CIT
                                                                        and self.C['gulf_zakat'].startswith('sau_gfs') else ()))
            return g[0], g[1], 'S13', src
        if w:
            return w[0], w[1], w[2], 'IMF WoRLD'
        return None

    @staticmethod
    def world_fill(sector, extra=''):
        if sector == 'S1311MIXED':
            return (extra + '+' if extra else '') + 'central_government'
        return extra

    def country_rates(self):
        S, C, tax, grs = self.S, self.C, self.tax, self.grs
        for iso in self.countries:
            for klass, codes in GRS_CLASS.items():
                if klass == 'payroll_property':
                    continue
                got = [grs.get((iso, c)) for c in codes]
                if all(g is not None for g in got):
                    tax[(iso, klass)] = (sum(g[1] for g in got), 'OECD GRS', max(g[0] for g in got), '')
                elif iso not in ('BHR', 'KWT'):
                    w = self.world_or_gfs(iso, WORLD_COMPONENT[klass], klass)
                    if w:
                        tax[(iso, klass)] = (w[0], w[3], w[1], self.world_fill(w[2]))
                else:
                    w = self.best_world(iso, WORLD_COMPONENT[klass])
                    if w:
                        tax[(iso, klass)] = (w[0], 'IMF WoRLD', w[1], self.world_fill(w[2]))
            parts = [g for g in (grs.get((iso, 'T_3000')), grs.get((iso, 'T_4000'))) if g is not None]
            if parts:
                fill = '' if len(parts) == 2 else 'partial_grs'
                tax[(iso, 'payroll_property')] = (sum(g[1] for g in parts), 'OECD GRS', max(g[0] for g in parts), fill)
            else:
                w = self.best_world(iso, 'G113_POGDP_PT_R')
                g = self.best_gfs(iso, 'payroll_property') if not (w and w[2] == 'S13') else None
                if g:
                    tax[(iso, 'payroll_property')] = (g[0], 'IMF GFS_SOO S13 G112+G113', g[1], '')
                elif w:
                    tax[(iso, 'payroll_property')] = (w[0], 'IMF WoRLD G113', w[1], self.world_fill(w[2], 'property_stands_in'))
        pits, cits = [], []
        for iso in self.countries:
            if iso in ('BHR', 'KWT'):
                continue
            if tax.get((iso, 'pit')) and tax.get((iso, 'cit')):
                pits.append(tax[(iso, 'pit')][0])
                cits.append(tax[(iso, 'cit')][0])
        mp = sum(pits) / len(pits) if pits else 0.0
        mc = sum(cits) / len(cits) if cits else 0.0
        share_pit = mp / (mp + mc) if mp + mc else 0.5
        share_cit = 1.0 - share_pit
        S.log(f'income-tax split shares PIT {share_pit:.6f} CIT {share_cit:.6f} from {len(pits)} covered countries')
        for iso in self.countries:
            if iso in ('BHR', 'KWT'):
                continue
            g111 = self.best_world(iso, 'G111_POGDP_PT_R')
            if (iso, 'pit') not in tax and (iso, 'cit') in tax and g111 and abs(g111[0] - tax[(iso, 'cit')][0]) <= 1e-4:
                tax[(iso, 'pit')] = (0.0, 'IMF WoRLD G111 minus G1112', g111[1], self.world_fill(g111[2], 'implied_zero'))
            if (iso, 'cit') not in tax and (iso, 'pit') in tax and g111 and abs(g111[0] - tax[(iso, 'pit')][0]) <= 1e-4:
                tax[(iso, 'cit')] = (0.0, 'IMF WoRLD G111 minus G1111', g111[1], self.world_fill(g111[2], 'implied_zero'))
            if (iso, 'pit') in tax or (iso, 'cit') in tax:
                continue
            total = g111 or self.best_world(iso, 'G11_POGDP_PT_R')
            if total is None:
                continue
            which = 'G111' if g111 else 'G11'
            fill = self.world_fill(total[2], 'G11-SPLIT')
            tax[(iso, 'pit')] = (total[0] * share_pit, f'IMF WoRLD {which} split', total[1], fill)
            tax[(iso, 'cit')] = (total[0] * share_cit, f'IMF WoRLD {which} split', total[1], fill)
            S.flag('G11-SPLIT', iso, f'{which} {total[0]:.6f} percent of GDP is split PIT {share_pit:.6f} / CIT {share_cit:.6f} at the covered-country shares. Logged fill.',
                   'no', C['income_tax_aggregate'], Q_TAX)
        for iso in ('BHR', 'KWT'):
            g11 = self.best_world(iso, 'G11_POGDP_PT_R')
            tax[(iso, 'pit')] = (0.0, 'bhr_kwt source', g11[1] if g11 else 2022, 'bhr_kwt_zero_pit')
            S.flag('BHR-KWT-PIT', iso, 'PIT is 0. Total income tax is booked as CIT.', 'no', C['bhr_kwt'], 'not in GTAP text')
            if g11:
                tax[(iso, 'cit')] = (g11[0], 'IMF WoRLD G11', g11[1], self.world_fill(g11[2], 'bhr_kwt_g11_as_cit'))
            if iso == 'KWT':
                g121 = self.best_world(iso, 'G121_POGDP_PT_R')
                if g121:
                    tax[(iso, 'ssc')] = (g121[0], 'IMF WoRLD G121', g121[1], self.world_fill(g121[2], 'bhr_kwt_own_ssc'))
        for klass in APPLIES:
            pool = [tax[(iso, klass)][0] for iso in self.countries if (iso, klass) in tax
                    and 'G11-SPLIT' not in tax[(iso, klass)][3] and tax[(iso, klass)][3] != 'bhr_kwt_zero_pit']
            self.averages[klass] = sum(pool) / len(pool) if pool else 0.0
            S.log(f'average {klass} {self.averages[klass]:.6f} from {len(pool)} countries')
        for iso in self.countries:
            for klass in APPLIES:
                tax.setdefault((iso, klass), (self.averages[klass], 'simple average of covered ratios', 2022, 'TAX-AVERAGE'))

    def average_used_where_source(self):
        """S10-Htaxsource: (iso, class) pairs on the average while GRS or WoRLD has a value."""
        tax, grs, bw = self.tax, self.grs, self.best_world
        bad = []
        for iso in self.countries:
            for klass in APPLIES:
                rec = tax.get((iso, klass))
                if not rec or 'TAX-AVERAGE' not in rec[3]:
                    continue
                other = tax.get((iso, 'cit' if klass == 'pit' else 'pit'))
                g111 = bw(iso, 'G111_POGDP_PT_R')
                present = False
                if klass == 'pit':
                    present = grs.get((iso, 'T_1100')) is not None or bw(iso, 'G1111_POGDP_PT_R') is not None
                elif klass == 'cit':
                    present = grs.get((iso, 'T_1200')) is not None or bw(iso, 'G1112_POGDP_PT_R') is not None
                if klass in ('pit', 'cit') and g111 and other and 'TAX-AVERAGE' not in other[3] and abs(g111[0] - other[0]) <= 1e-4:
                    present = True
                if klass in ('pit', 'cit') and other and 'TAX-AVERAGE' in other[3] and (g111 or bw(iso, 'G11_POGDP_PT_R')):
                    present = True
                elif klass == 'ssc':
                    present = grs.get((iso, 'T_2000')) is not None or bw(iso, 'G121_POGDP_PT_R') is not None
                elif klass == 'payroll_property':
                    present = (grs.get((iso, 'T_3000')) is not None or grs.get((iso, 'T_4000')) is not None
                               or bw(iso, 'G113_POGDP_PT_R') is not None)
                if present:
                    bad.append(f'{iso} {klass}')
        return bad

    def region_rows(self, regions, region_type, members, gdp_iso, pre_gdp):
        S, C, tax = self.S, self.C, self.tax
        rows, total = [], defaultdict(float)
        for region in regions:
            mem = sorted(members.get(region, set())) or ([region] if any((region, k) in tax for k in APPLIES) else [])
            for klass, applies in APPLIES.items():
                host = tax.get((region, klass))
                if region_type.get(region) == 'single' and host and host[3] != 'TAX-AVERAGE':
                    pct, source, year, fill = host
                else:
                    num = den = 0.0
                    fills, sources, years, used_territory = set(), set(), set(), False
                    for iso in mem:
                        rec = tax.get((iso, klass))
                        if not rec:
                            continue
                        g = max(gdp_iso.get(iso, 0.0), 0.0)
                        num += rec[0] * g
                        den += g
                        fills.add(rec[3] or rec[1])
                        sources.add(rec[1])
                        years.add(str(rec[2]))
                        if iso != region and rec[3] != 'TAX-AVERAGE':
                            used_territory = True
                    if den > 0:
                        pct = num / den
                    elif mem:
                        pct = sum(tax[(i, klass)][0] for i in mem if (i, klass) in tax) / max(1, len(mem))
                    else:
                        pct = self.averages[klass]
                    source = '+'.join(sorted(sources)) or 'simple average of covered ratios'
                    year = ','.join(sorted(years)) if len(years) <= 3 else 'mixed'
                    fill = '+'.join(t for t in ('TAX-AVERAGE', 'G11-SPLIT', 'central_government') if any(t in f for f in fills))
                    if used_territory and region_type.get(region) == 'single':
                        fill = (fill + '+' if fill else '') + 'territory_fold'
                if 'TAX-AVERAGE' in fill:
                    S.flag('TAX-AVERAGE', region, f'{klass} uses the simple average of covered countries, {self.averages[klass]:.6f} percent of GDP.',
                           'no', C['tax_missing'], Q_TAX)
                if 'central_government' in fill:
                    S.flag('WORLD-CENTRAL-GOV', region, f'{klass} uses central government S1311MIXED because general government S13 is missing.',
                           'no', C['world_sector'], Q_TAX)
                value = pct / 100.0 * pre_gdp[region]
                total[klass] += value
                rows.append([region, klass, applies, fnum(pct), fnum(pre_gdp[region]), fnum(value), source, str(year), fill,
                             'pre-removal io GDP, basic'])
                if value < -1e-6:
                    S.adjust(region, klass, '0', fnum(value), 'negative rate is the source observation, not a plug', Q_TAX, 'cited')
        return rows, total
