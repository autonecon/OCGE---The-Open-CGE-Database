"""Commodity structure of the non-energy product taxes in each column's TLS (s10 choice product_tax_pattern; QA round 2 P1).

GTAP holds a product-tax rate by commodity, source and agent (GTAP 12 ch.2 Table 2.3, VDFP/VDFB ... VMPP/VMPB), and
the rates come from the contributed national I-O valuation layers (ch.8). The ICIO gives one TLS per column. S10 writes
the layers S13 uses to place each column's non-energy TLS on its commodities; S13 scales them back to the column TLS
(the column totals, revenue and GDP do not move):

- VAT layer (product_tax_pattern_s10.csv): the statutory VAT schedule by commodity (data/vat_statutory: OECD Consumption
  Tax Trends 2024 Annex Tables 2.A.1-2.A.3, the EC VAT-rate compilation, the Chinese VAT regulations), latest year at or
  before the base year. Without a schedule, rate 1 on every commodity outside the common exemptions (OECD CTT 2024
  Annex Table 2.A.3 note 2: financial services, letting of immovable property, education, hospital and medical care,
  postal services) and outside the non-market services (public administration, household employers). Agents:
    p, g: the schedule (households and government are final consumers); households' real estate (rle) 0, as it is
          mostly the imputed rent of owner-occupied dwellings, which is not a sale;
    i: the schedule (non-deductible VAT on dwellings and on government and exempt-sector investment);
    firm_exempt: the schedule, for an activity whose own output is exempt (it cannot deduct its input VAT);
    firm: an indicator 1 on the non-exempt commodities (input VAT is deducted; what remains of the column TLS is other
          product taxes, which do not fall on the exempt services).
- Revenue levels (product_tax_layers_s10.csv): the GRS T_5111 VAT (else T_5000 less T_5121, T_5123 and T_5124, the
  general and other consumption taxes, for a region with no VAT such as the USA) and T_5121 excises, latest year at or
  before the base year, percent of GDP times the pre-removal IO GDP; a composite takes its members' GDP-weighted mean.
  S13 puts the excise less the energy excise it already holds on the energy rows on households' fbt (alcohol and
  tobacco).
- Product control (product_tax_control_s10.csv): the Eurostat supply table at basic prices, taxes less subsidies on
  products (naio_10_cp15, D21X31) by CPA product for the EU-27, Norway and the candidates, latest year at or before
  the base year, by commodity group; S13 RASes the column-scaled layers towards these shares on the non-energy rows.
"""
import csv
from collections import defaultdict

from .util import fnum

AGENTS = ('p', 'g', 'i', 'firm_exempt', 'firm')
EXEMPT_ICIO = ('K', 'L', 'P', 'Q', 'H53')      # OECD CTT 2024 Annex Table 2.A.3 note 2 (common exemptions)
NON_MARKET_ICIO = ('O', 'T')                    # outside the scope of VAT: public administration, household employers
IMPUTED_RENT_ICIO = 'L'                          # rle holds the imputed rent of owner-occupied dwellings (S01 sectors note)
GRS_VAT, GRS_EXCISE, GRS_ALL = 'T_5111', 'T_5121', 'T_5000'
GRS_NOT_GENERAL = ('T_5121', 'T_5123', 'T_5124')
Q_PATTERN = 'GTAP 12 ch.2 Table 2.3 (rates by commodity, source and agent); ch.8 (national I-O valuation layers)'
PATTERN_COLUMNS = ['region', 'agent', 'commodity', 'vat_weight', 'schedule', 'schedule_year']
LAYER_COLUMNS = ['region', 'vat_musd', 'vat_basis', 'excise_musd', 'excise_basis', 'energy_excise_musd', 'io_gdp_musd', 'grs_year',
                 'price_basis']
CONTROL_COLUMNS = ['region', 'group', 'commodities', 'tax_meur', 'share', 'geo', 'year', 'source']
# Eurostat CPA products (naio_10_cp15 prd_amo) -> commodity groups; a group holds one or more S01 sectors.
# The energy products (B05, B06, C19, D) are left out: S13 holds the energy excise on those rows.
CPA_GROUPS = {
    'crp': ('CPA_A01',), 'for': ('CPA_A02',), 'fsh': ('CPA_A03',), 'ore': ('CPA_B07',), 'min': ('CPA_B08',), 'msp': ('CPA_B09',),
    'fbt': ('CPA_C10-12',), 'tal': ('CPA_C13-15',), 'wod': ('CPA_C16',), 'pap': ('CPA_C17', 'CPA_C18'), 'chm': ('CPA_C20',),
    'pha': ('CPA_C21',), 'rpl': ('CPA_C22',), 'nmm': ('CPA_C23',), 'stl;nfm': ('CPA_C24',), 'fmp': ('CPA_C25',), 'elc': ('CPA_C26',),
    'eeq': ('CPA_C27',), 'mac': ('CPA_C28',), 'mvh': ('CPA_C29',), 'shp;tre': ('CPA_C30',), 'omf': ('CPA_C31_32', 'CPA_C33'),
    'wat': ('CPA_E36', 'CPA_E37-39'), 'con': ('CPA_F',), 'trd': ('CPA_G45', 'CPA_G46', 'CPA_G47'), 'rdt': ('CPA_H49',),
    'sea': ('CPA_H50',), 'air': ('CPA_H51',), 'whs': ('CPA_H52',), 'pst': ('CPA_H53',), 'hos': ('CPA_I',),
    'pub': ('CPA_J58', 'CPA_J59_60'), 'tel': ('CPA_J61',), 'its': ('CPA_J62_63',), 'fin': ('CPA_K64', 'CPA_K65', 'CPA_K66'),
    'rle': ('CPA_L68A', 'CPA_L68B'), 'pro': ('CPA_M69_70', 'CPA_M71', 'CPA_M72', 'CPA_M73', 'CPA_M74_75'),
    'adm': ('CPA_N77', 'CPA_N78', 'CPA_N79', 'CPA_N80-82'), 'gov': ('CPA_O',), 'edu': ('CPA_P',), 'hea': ('CPA_Q86', 'CPA_Q87_88'),
    'art': ('CPA_R90-92', 'CPA_R93'), 'ots': ('CPA_S94', 'CPA_S95', 'CPA_S96'), 'hhe': ('CPA_T',),
}
EUROSTAT_ISO3 = {
    'AT': 'AUT', 'BE': 'BEL', 'BG': 'BGR', 'CY': 'CYP', 'CZ': 'CZE', 'DE': 'DEU', 'DK': 'DNK', 'EE': 'EST', 'EL': 'GRC', 'ES': 'ESP',
    'FI': 'FIN', 'FR': 'FRA', 'HR': 'HRV', 'HU': 'HUN', 'IE': 'IRL', 'IT': 'ITA', 'LT': 'LTU', 'LU': 'LUX', 'LV': 'LVA', 'MT': 'MLT',
    'NL': 'NLD', 'PL': 'POL', 'PT': 'PRT', 'RO': 'ROU', 'SE': 'SWE', 'SI': 'SVN', 'SK': 'SVK', 'NO': 'NOR', 'AL': 'ALB', 'RS': 'SRB',
    'MK': 'MKD', 'ME': 'MNE', 'TR': 'TUR', 'IS': 'ISL', 'CH': 'CHE',
}


def read_vat(path, base_year):
    """{iso: (year, {icio code or '*': rate fraction})}: each country's latest schedule year at or before base_year."""
    by = defaultdict(lambda: defaultdict(dict))
    with open(path, newline='', encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            y = int(r['year'])
            if y <= base_year:
                by[r['country']][y][r['commodity']] = float(r['rate_percent']) / 100.0
    return {iso: (max(ys), ys[max(ys)]) for iso, ys in by.items()}


def schedule_of(sector_icio, sched):
    """{sector: rate} from one schedule ({icio code or '*': rate}); a sector with no own row takes '*'.
    sched None: the generic schedule (1 outside the common exemptions and the non-market services)."""
    out = {}
    for s, code in sector_icio.items():
        if sched is None:
            out[s] = 0.0 if code in EXEMPT_ICIO + NON_MARKET_ICIO else 1.0
        else:
            out[s] = sched.get(code, 0.0 if code in NON_MARKET_ICIO else sched.get('*', 0.0))
    return out


def pattern_rows(regions, region_type, sector_icio, vat):
    """product_tax_pattern_s10 rows: the VAT weight of every (region, agent, commodity). A single region uses its own
    statutory schedule where data/vat_statutory has one; every other region the generic schedule."""
    rows, used = [], {}
    for reg in regions:
        own = vat.get(reg) if region_type.get(reg) == 'single' else None
        rates = schedule_of(sector_icio, own[1] if own else None)
        label, year = ('statutory', str(own[0])) if own else ('generic_exemptions', '')
        used[reg] = label
        for agent in AGENTS:
            for s in sector_icio:
                if agent == 'firm':
                    w = 1.0 if schedule_of({s: sector_icio[s]}, None)[s] > 0 else 0.0
                elif agent == 'p' and sector_icio[s] == IMPUTED_RENT_ICIO:
                    w = 0.0          # households' real estate is mostly the imputed rent of owner-occupied dwellings: not a sale
                else:
                    w = rates[s]
                rows.append([reg, agent, s, fnum(w), label, year])
    return rows, used


def _member_pct(grs, iso_list, gdp_iso, code):
    num = den = 0.0
    years = set()
    for iso in iso_list:
        g = grs.get((iso, code))
        w = max(gdp_iso.get(iso, 0.0), 0.0)
        if g is None or w <= 0:
            continue
        num += g[1] * w
        den += w
        years.add(g[0])
    return (num / den, years) if den > 0 else (None, years)


def energy_excise(energy_rows):
    """{region: USD million}: the energy taxes (tax_musd, before subsidies) of each source region in energy_tax_s10
    rows (energy_tax.FILE_COLUMNS); a fill region (class '*') has none here (S13 uses its excise on the flows)."""
    out = {}
    for r in energy_rows:
        if r[1] != '*':
            out[r[0]] = out.get(r[0], 0.0) + float(r[4])
    return out


def layer_rows(regions, members, gdp_iso, pre_gdp, grs, energy_src=None):
    """product_tax_layers_s10 rows: VAT and excise revenue (USD million) at percent of GDP times the IO GDP, and the
    region's source energy taxes (energy_excise; blank for a fill region)."""
    energy_src = energy_src or {}
    rows = []
    for reg in regions:
        mem = sorted(members.get(reg, set())) or [reg]
        vat, ys = _member_pct(grs, mem, gdp_iso, GRS_VAT)
        basis = 'GRS T_5111'
        if not vat:
            allc, ys2 = _member_pct(grs, mem, gdp_iso, GRS_ALL)
            if allc is not None:
                rest = sum((_member_pct(grs, mem, gdp_iso, c)[0] or 0.0) for c in GRS_NOT_GENERAL)
                vat, ys, basis = max(allc - rest, 0.0), ys | ys2, 'GRS T_5000 less T_5121, T_5123, T_5124 (no VAT)'
            else:
                vat, basis = None, 'none'
        exc, ys3 = _member_pct(grs, mem, gdp_iso, GRS_EXCISE)
        g = pre_gdp.get(reg, 0.0)
        years = sorted(ys | ys3)
        rows.append([reg, fnum(vat / 100.0 * g) if vat is not None else '', basis,
                     fnum(exc / 100.0 * g) if exc is not None else '', 'GRS T_5121' if exc is not None else 'none',
                     fnum(energy_src[reg]) if reg in energy_src else '', fnum(g), ','.join(str(y) for y in years), 'basic'])
    return rows


def read_eurostat(path, base_year):
    """{geo: (year, {cpa: MEUR})}: D21X31 by product, each country's latest year at or before base_year with a
    CPA_TOTAL value."""
    by = defaultdict(lambda: defaultdict(dict))
    with open(path, newline='', encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            if r['ind_impv'] != 'D21X31' or r['unit'] != 'MIO_EUR' or not r['OBS_VALUE']:
                continue
            y = int(r['TIME_PERIOD'])
            if y <= base_year:
                by[r['geo']][y][r['prd_amo']] = float(r['OBS_VALUE'])
    out = {}
    for geo, ys in by.items():
        ok = [y for y, v in ys.items() if 'CPA_TOTAL' in v]
        if ok:
            out[geo] = (max(ok), ys[max(ok)])
    return out


def control_rows(regions, region_type, eurostat):
    """product_tax_control_s10 rows: each group's share of the non-energy product taxes (negative groups at zero:
    S13's RAS needs non-negative targets; their value is reported)."""
    rows, negatives = [], []
    for geo, (year, v) in sorted(eurostat.items()):
        reg = EUROSTAT_ISO3.get(geo)
        if reg not in regions or region_type.get(reg) != 'single':
            continue
        vals = {g: sum(v.get(c, 0.0) for c in cpas) for g, cpas in CPA_GROUPS.items()}
        if not any(all(c in v for c in cpas) for cpas in CPA_GROUPS.values()):
            continue
        for g, x in vals.items():
            if x < 0:
                negatives.append(f'{reg} {g} {x:.1f} MEUR')
        pos = sum(max(x, 0.0) for x in vals.values())
        if pos <= 0:
            continue
        for g, x in vals.items():
            rows.append([reg, g, g.replace(';', ' '), fnum(x), fnum(max(x, 0.0) / pos), geo, str(year),
                         'Eurostat naio_10_cp15 D21X31'])
    return rows, negatives
