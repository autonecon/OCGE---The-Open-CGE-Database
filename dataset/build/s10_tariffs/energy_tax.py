"""Energy taxes on the fuel, power and gas rows (fix-round item A1; GTAP 12 ch.12 §12.3.3, §12.3.9, §12.3.10, §12.4.4).

GTAP 12 ch.12 collects energy excise taxes as specific rates by commodity, use class and country (§12.3.3: the IEA
excise rate, not VAT; an unknown rate is zero), aggregates them to the energy commodities with volume weights
(§12.3.9), gives countries without data the rates of a proxy country matched by geography and net energy trade
direction (§12.3.10), and, once the prices are final, converts the specific rates (per TOE) into ad valorem rates on
the basic price (§12.4.4). FIT then holds those rates (ch.17A items 4-5): the tax totals move with the flows.

S10 runs before S11, which sets the energy basic prices, so the work is split (fix-round w12, David 2026-10-24
"stick to GTAP"). S10 writes the specific rates (`energy_tax_s10.csv`): per region, NEERS sector (use class) and
energy row (pet, coa, gas, ely), the net tax in USD million and its tax base, so the rate per GJ is tax / base, and,
for a region with no source data, its proxy countries. S13, which reads the S11 basic prices and volumes, converts
them to ad valorem rates and places them on the cells (s13_fit.method.energy_ad_valorem, place_column_taxes).

Source: OECD Net Effective Energy Rates (DF_NEERS), energy_tax_year, by NEERS sector and energy source: fuel excise +
carbon tax + electricity excise (TOTTAX) and, when energy_subsidies says so, the fossil-fuel and electricity
subsidies (TOTSUBS), each in EUR per GJ, times the tax base in TJ. EUR are converted at the Eurostat ert_bil_eur_a
annual average of the same year. ETS permit prices are not a tax on products and are left out. The rates of the
energy sources of one row (gasoline, diesel, kerosene, fuel oil, LPG and road biofuels -> pet) are combined with
their NEERS tax bases as weights (§12.3.9). NEERS records the electricity excise per GJ of the power sector's fuel
inputs; it is a tax on electricity sales, so S10 writes its revenue (class ALL, base_unit electricity_s11) and S13
divides it by the S11 domestic use of electricity. The USA, which DF_NEERS does not cover, is a source region from EIA
data (energy_tax_usa, us_motor_fuel): federal and average state road-fuel excise on the ROAD class pet row, with the
2022 road-fuel barrels as the base (base_unit million_bbl; S13 converts barrels to GJ with the S11 petroleum factor).

File rows (energy_tax_s10.csv): region, class, commodity, columns (the IO columns of the class, ';'-joined, or ALL),
tax_musd and subsidy_musd (the NEERS subsidy part, <= 0, fix-round B15; the net tax is their sum), base and
base_unit, specific_usd_per_gj and neer_subsidy_usd_per_gj (when the base is in TJ), source, year, fill, proxies.
A region with no source data has one row (class and commodity '*') naming its proxies with their trade weights
(energy_tax_fill): by default the S12 pool members on the same side of energy trade (GTAP 12 ch.12 §12.3.10, David's
card 2026-10-24 14:34 UTC); with none, the region carries no energy tax (§12.3.3).
"""
import csv
from collections import defaultdict

from .config import ConfigError, read_table
from .util import fnum

Q_ENERGY = 'GTAP 12 ch.12 §12.3.3 (excise rates by commodity and use), §12.3.10 (proxies), §12.4.4 (specific to ad valorem); fix list A1 (David 2026-10-24)'
COMMODITIES = ('pet', 'coa', 'gas', 'ely')
TRADED_ENERGY = ('coa', 'oil', 'gas', 'pet')     # S10 goods sectors that set a region's net energy trade direction
FUEL_ROW = {'GASO': 'pet', 'DIES': 'pet', 'KERO': 'pet', 'FOIL': 'pet', 'LPG': 'pet', 'COAL': 'coa', 'NGAS': 'gas'}
BIOFUEL_SECTORS = ('ROAD', 'OFFROAD')          # biofuels there are blended into road and transport fuels
NEER_SECTORS = ('AGRIFISH', 'ELEC', 'INDUSTRY', 'OFFROAD', 'RESCOM', 'ROAD')
ALL_BUYERS = 'ALL'
BASE_TJ, BASE_BBL, BASE_ELY = 'TJ', 'million_bbl', 'electricity_s11'
FILL_ROW = '*'
FILE_COLUMNS = ['region', 'class', 'commodity', 'columns', 'tax_musd', 'subsidy_musd', 'base', 'base_unit', 'specific_usd_per_gj',
                'neer_subsidy_usd_per_gj', 'source', 'year', 'fill', 'proxies', 'price_basis', 'fuel_sales_tax_musd']
# S12 region pools: GTAP geographic regions with the American and African groups merged (s12_factors.py GEO15).
GEO15 = {'CARB': 'LMAR', 'CAMR': 'LMAR', 'SAMR': 'LMAR', 'EAFR': 'SSAF', 'CAFR': 'SSAF', 'WAFR': 'SSAF', 'SAFR': 'SSAF'}
NOT_TAXED_COLUMNS = ('dpabr',)          # purchases abroad by residents: no domestic energy tax
# Eurostat geo codes of the EU and EEA reporters -> ISO3 (Eurostat uses EL for Greece).
EUROSTAT_ISO3 = {'AT': 'AUT', 'BE': 'BEL', 'BG': 'BGR', 'CY': 'CYP', 'CZ': 'CZE', 'DE': 'DEU', 'DK': 'DNK', 'EE': 'EST',
                 'EL': 'GRC', 'ES': 'ESP', 'FI': 'FIN', 'FR': 'FRA', 'HR': 'HRV', 'HU': 'HUN', 'IE': 'IRL', 'IT': 'ITA',
                 'LT': 'LTU', 'LU': 'LUX', 'LV': 'LVA', 'MT': 'MLT', 'NL': 'NLD', 'PL': 'POL', 'PT': 'PRT', 'RO': 'ROU',
                 'SE': 'SWE', 'SI': 'SVN', 'SK': 'SVK', 'NO': 'NOR', 'IS': 'ISL', 'LI': 'LIE', 'TR': 'TUR', 'RS': 'SRB',
                 'ME': 'MNE', 'MK': 'MKD', 'AL': 'ALB', 'BA': 'BIH', 'MD': 'MDA', 'UA': 'UKR', 'GE': 'GEO', 'XK': 'XKX'}


def read_fx(path):
    """Eurostat ert_bil_eur_a: {year: USD per EUR}."""
    out = {}
    with open(path, newline='') as fh:
        for row in csv.DictReader(fh):
            if row.get('currency') == 'USD' and row.get('statinfo') == 'AVG' and row.get('OBS_VALUE'):
                out[int(row['TIME_PERIOD'])] = float(row['OBS_VALUE'])
    if not out:
        raise ConfigError(f'{path}: no EUR/USD rate')
    return out


def read_neer(path):
    """{(year, iso, sector, source): {measure: value}} for observed values (OBS_STATUS A)."""
    out = defaultdict(dict)
    with open(path, newline='') as fh:
        for row in csv.DictReader(fh):
            if row.get('PRICE_BASE') != 'V' or row.get('OBS_STATUS') == 'O' or row.get('OBS_VALUE') in ('', None):
                continue
            key = (int(row['TIME_PERIOD']), row['REF_AREA'], row['SECTOR'], row['ENERGY_SOURCE'])
            out[key][row['MEASURE']] = float(row['OBS_VALUE'])
    return out


def years_of(choice):
    return {'neer_2023_latest': (2023,), 'neer_2021': (2021,), 'neer_mean_2021_2023': (2021, 2023)}[choice]


def lcu_ratios(wdi_path, years, base_year):
    """energy_tax_fx (beta v5 E6): {(iso, year): LCU per USD in the NEERS year / LCU per USD in the base year}, WDI
    PA.NUS.FCRF. NEERS states rates in EUR at the NEERS-year exchange rate; times this ratio, the NEERS-year USD value
    becomes the same local-currency rate converted at the base-year USD rate."""
    fx = {}
    with open(wdi_path, newline='') as fh:
        for row in csv.DictReader(fh):
            if row['series'] == 'PA.NUS.FCRF' and row['value']:
                fx[(row['iso3'], int(row['year']))] = float(row['value'])
    out = {}
    for (iso, year), v in fx.items():
        if year in years and (iso, base_year) in fx and v > 0:
            out[(iso, year)] = v / fx[(iso, base_year)]
    return out


def revenues(neer, fx, year_choice, subsidy_choice, lcu_ratio=None):
    """{iso: {(class, row): [tax_musd, subsidy_musd, base, base_unit]}}, averaged over the chosen years.

    lcu_ratio (energy_tax_fx, beta v5 E6): {(iso, year): ratio} from lcu_ratios. When given, each NEERS-year USD value
    is scaled to the base-year exchange rate, and a country with no ratio for a chosen year is left out (NEERS
    aggregates such as OECD00 and G20 have none; S10-Henergyfx checks that no region country is left out).

    class is a NEERS sector, or ALL for the electricity excise (a tax on every ely buyer; base_unit electricity_s11,
    base 0: S13 divides by the S11 domestic use of electricity). Otherwise the base is the NEERS tax base in TJ of
    the energy sources of that row, so tax / base is the volume-weighted specific rate (GTAP 12 ch.12 §12.3.9)."""
    years = years_of(year_choice)
    net = subsidy_choice == 'net_of_neer_subsidies'
    acc = defaultdict(dict)
    seen = defaultdict(set)

    def slot(iso, key, unit):
        if key not in acc[iso]:
            acc[iso][key] = [0.0, 0.0, 0.0, unit]
        return acc[iso][key]
    for (year, iso, sector, source), m in neer.items():
        if year not in years or sector not in NEER_SECTORS:
            continue
        tj = m.get('TAXBTJ')
        if not tj:
            continue
        seen[iso].add(year)
        usd = fx[year] * tj * 1000.0 / 1e6 / len(years)     # EUR per GJ x TJ -> USD million
        if lcu_ratio is not None:
            if (iso, year) not in lcu_ratio:
                continue
            usd *= lcu_ratio[(iso, year)]
        if sector == 'ELEC':
            s = slot(iso, (ALL_BUYERS, 'ely'), BASE_ELY)
            s[0] += m.get('ELETAX', 0.0) * usd
            if net:
                s[1] += m.get('ELESUBSID', 0.0) * usd
            row = FUEL_ROW.get(source)
            if row:
                s = slot(iso, (sector, row), BASE_TJ)
                s[0] += (m.get('FUETAX', 0.0) + m.get('CARBTAX', 0.0)) * usd
                if net:
                    s[1] += m.get('SUBSID', 0.0) * usd
                s[2] += tj / len(years)
            continue
        row = FUEL_ROW.get(source) or ('pet' if source == 'BIOF' and sector in BIOFUEL_SECTORS else None)
        if row is None:
            continue
        s = slot(iso, (sector, row), BASE_TJ)
        s[0] += m.get('TOTTAX', 0.0) * usd
        if net:
            s[1] += m.get('TOTSUBS', 0.0) * usd
        s[2] += tj / len(years)
    # a country must have every chosen year to be used
    return {iso: dict(v) for iso, v in acc.items() if seen[iso] >= set(years)}


def fuel_sales_taxes(neer, year_choice, lcu_per_usd, path=None):
    """fuel_sales_taxes (round-3 fix wE2): fuel-specific sales taxes that NEERS (excise and carbon taxes only) does not
    hold: India's state sales tax/VAT on petroleum products outside GST, Brazil's ICMS on fuels. GTAP 12 ch.12 §12.3
    books energy-specific taxes on the energy rows. Each config row is booked on its class and row at the class share
    of the NEERS tax base (TJ, the chosen years) of the named energy sources; the rest is not booked and stays in the
    column remainder. Returns {iso: dict(cls, row, total_musd, share, booked_musd, sources, source)}.
    lcu_per_usd: {iso: WDI PA.NUS.FCRF of the base year}."""
    rows = read_table('fuel_sales_taxes_2022.csv', ('region', 'commodity', 'booked_class', 'base_sources', 'value_lcu', 'currency',
                                                    'period', 'source', 'url', 'retrieved', 'basis', 'decided_by', 'decided_at'), path=path)
    years = years_of(year_choice)
    out = {}
    for r in rows:
        iso, cls, row = r['region'], r['booked_class'], r['commodity']
        if iso in out or cls not in NEER_SECTORS or row not in COMMODITIES:
            raise ConfigError(f'fuel_sales_taxes_2022.csv {iso}: repeated, or class {cls} / row {row} unknown')
        if not r['decided_by'] or not r['decided_at'] or not r['basis'] or not r['url']:
            raise ConfigError(f'fuel_sales_taxes_2022.csv {iso}: decision, basis or source URL blank')
        fx = lcu_per_usd.get(iso)
        if not fx:
            raise ConfigError(f'fuel_sales_taxes_2022.csv {iso}: no WDI exchange rate')
        sources = tuple(s for s in r['base_sources'].split(';') if s)
        tj = defaultdict(float)
        for (year, i, sector, source), m in neer.items():
            if i == iso and year in years and source in sources and sector in NEER_SECTORS:
                tj[sector] += m.get('TAXBTJ', 0.0) or 0.0
        total_tj = sum(tj.values())
        if not tj.get(cls, 0.0) > 0 or not total_tj > 0:
            raise ConfigError(f'fuel_sales_taxes_2022.csv {iso}: no NEERS {cls} base for {sources}')
        share = tj[cls] / total_tj
        total = float(r['value_lcu']) / fx / 1e6
        out[iso] = dict(cls=cls, row=row, total_musd=total, share=share, booked_musd=total * share, sources=sources,
                        source=r['source'], fx=fx)
    return out


def load_classes(path=None):
    """energy_tax_classes.csv -> {NEERS sector: tuple of IO columns}."""
    rows = read_table('energy_tax_classes.csv', ('neer_sector', 'io_columns', 'basis', 'decided_by', 'decided_at'), path=path)
    out = {}
    for row in rows:
        s = row['neer_sector']
        if s not in NEER_SECTORS or s in out:
            raise ConfigError(f'energy_tax_classes.csv: sector {s!r} unknown or repeated')
        if not row['decided_by'] or not row['decided_at'] or not row['basis']:
            raise ConfigError(f'energy_tax_classes.csv {s}: decision or basis blank')
        out[s] = tuple(c for c in row['io_columns'].split(';') if c)
    missing = set(NEER_SECTORS) - set(out)
    if missing:
        raise ConfigError(f'energy_tax_classes.csv lacks {sorted(missing)}')
    return out


def specific(tax, sub, base, unit):
    """(net USD per GJ, NEERS subsidy USD per GJ) for a TJ base, else (None, None): S13 converts the other bases."""
    if unit != BASE_TJ or not base > 0:
        return None, None
    return (tax + sub) * 1000.0 / base, sub * 1000.0 / base       # USD million / TJ = 1000 USD / GJ


def proxies_of(region, members, trade_weight, energy_net, fill_choice):
    """GTAP 12 ch.12 §12.3.10 proxies of a region with no source data: [(member, trade weight)] and a fill text.

    members: the source regions of its S12 pool (fill by pool) or all source regions (world fill)."""
    if fill_choice == 'same_energy_trade_direction_in_pool_else_zero':
        side = (energy_net or {}).get(region, 0.0) > 0
        same = [m for m in members if ((energy_net or {}).get(m, 0.0) > 0) == side]
        word = 'exporters' if side else 'importers'
        if not same:
            return [], f"no pool net {word[:-1]} with data: zero (GTAP 12 ch.12 §12.3.3)"
        return [(m, max(trade_weight.get(m, 0.0), 0.0)) for m in same], f'pool net {word}'
    return [(m, max(trade_weight.get(m, 0.0), 0.0)) for m in members], 'pool' if fill_choice.startswith('trade_weighted_s12_pool') else 'world'


def build(regions, region_iso, pool_of, trade_weight, rev_by_iso, classes, C, source_of=None, energy_net=None, sales=None):
    """All regions. Returns (rows for energy_tax_s10.csv, summary dict).

    region_iso: {region: ISO with source data or None}; pool_of: {region: pool}; trade_weight: {region: USD m};
    source_of: {ISO: source label} for revenue that is not from NEERS (the USA, energy_tax_usa);
    energy_net: {region: energy exports less imports, USD m} for the same-direction fill."""
    enabled = C['energy_tax_rows'] != 'one_column_rate'
    rows, own, filled = [], [], []
    totals = defaultdict(float)
    if not enabled:
        return rows, dict(own=own, filled=filled, totals=dict(totals), zero=[])
    for region in regions:
        iso = region_iso.get(region)
        if iso and iso in rev_by_iso:
            own.append(region)
    if not own:
        raise ConfigError('no region has OECD NEERS energy-tax data')
    zero = []
    for region in regions:
        if region in own:
            iso = region_iso[region]
            src = (source_of or {}).get(iso, f'OECD NEERS {iso}')
            for (cls, row), (tax, sub, base, unit) in sorted(rev_by_iso[iso].items()):
                if tax == 0.0 and sub == 0.0:
                    continue
                cols = ALL_BUYERS if cls == ALL_BUYERS else ';'.join(c for c in classes[cls] if c not in NOT_TAXED_COLUMNS)
                sp, ss = specific(tax, sub, base, unit)
                totals[row] += tax + sub
                rows.append([region, cls, row, cols, fnum(tax), fnum(sub), fnum(base), unit, '' if sp is None else fnum(sp),
                             '' if ss is None else fnum(ss), src, C['energy_tax_year'], '', '', 'specific (per GJ)',
                             fnum((sales or {}).get(iso, {}).get((cls, row), 0.0))])
            continue
        pool = pool_of.get(region)
        if C['energy_tax_fill'] == 'world_trade_weighted_average':
            members = sorted(own)
        else:
            members = sorted(m for m in own if pool and pool_of.get(m) == pool)
            if not members and C['energy_tax_fill'] == 'trade_weighted_s12_pool_average_else_world':
                members = sorted(own)
        prox, how = proxies_of(region, members, trade_weight, energy_net, C['energy_tax_fill'])
        prox = [(m, w) for m, w in prox if w > 0]
        if not prox:
            zero.append(region)
        fill = (f'{how} {pool}: ' + ' '.join(m for m, _w in prox)) if prox else how
        rows.append([region, FILL_ROW, FILL_ROW, '', '0', '0', '0', '', '', '', 'fill', C['energy_tax_year'], fill,
                     ';'.join(f'{m}:{fnum(w)}' for m, w in prox), 'specific (per GJ)', '0'])
        filled.append(region)
    return rows, dict(own=sorted(own), filled=filled, totals=dict(totals), zero=zero)


# ------------------------------------------------------------------ USA (fix-round A1: DF_NEERS has no US values)
US_SHEETS = ('January 2022', 'July 2022 (revised)')      # PMM rates in effect on 1 January and 1 July 2022
GAL_PER_BBL = 42.0
US_MER_SERIES = {'gasoline': 'MGACPUS', 'diesel': 'DFACPUS'}  # MER T3.7c, consumed by the transportation sector, kb/d
US_FOKS_SERIES = {'on_highway': 'K2DVHNNUS1', 'transportation': 'KD0VTTNUS1'}   # EIA FOKS distillate sales, thousand gallons


def _norm(x):
    return ' '.join(str(x or '').split()).lower()


def read_pmm_motor_fuel(path, sheets=US_SHEETS):
    """EIA Petroleum Marketing Monthly, Federal and state motor fuel taxes. Per sheet: federal total (excise +
    LUST fee) and the EIA average of state excise ('State tax', the unweighted average over the states), for
    gasoline and diesel, USD per gallon. Returns {sheet: dict(fed_gasoline, fed_diesel, state_gasoline, state_diesel)}.
    The layout is checked (the column headers), so a moved column stops the stage."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out = {}
    for name in sheets:
        if name not in wb.sheetnames:
            raise ConfigError(f'{path}: sheet {name!r} missing')
        rows = [list(r) for r in wb[name].iter_rows(min_row=1, max_row=12, values_only=True)]
        fed = next((r for r in rows if _norm(r[0]) == 'federal'), None)
        avg = next((r for r in rows if _norm(r[0]).startswith('average state tax')), None)
        tot_hdr = next((r for r in rows if _norm(r[1]) == 'excise' and _norm(r[4]) == 'total'), None)
        st_hdr = next((r for r in rows if _norm(r[1]) == 'state tax'), None)
        if not (fed and avg and tot_hdr and st_hdr) or _norm(tot_hdr[9]) != 'total' or _norm(st_hdr[6]) != 'state tax':
            raise ConfigError(f'{path} {name}: layout differs from the PMM fuel-tax table (Federal / Average state tax rows, Total and State tax columns)')
        out[name] = dict(fed_gasoline=float(fed[4]), fed_diesel=float(fed[9]), state_gasoline=float(avg[1]), state_diesel=float(avg[6]))
    wb.close()
    return out


def read_mer_annual(path, series, year):
    """EIA MER browser CSV: {key: value} of the annual rows (YYYYMM = year13) for {key: MSN}."""
    want = {v: k for k, v in series.items()}
    out = {}
    with open(path, newline='') as fh:
        for row in csv.DictReader(fh):
            if row['MSN'] in want and row['YYYYMM'] == f'{year}13':
                out[want[row['MSN']]] = float(row['Value'])
    if set(out) != set(series):
        raise ConfigError(f'{path}: {year} annual rows missing for {sorted(set(series) - set(out))}')
    return out


def read_foks_latest(path, series):
    """EIA dnav FOKS page (distillate sales by end use, thousand gallons): the latest-year cell (class Current2)
    of each series {key: series id}, and that year. Returns ({key: value}, year)."""
    import re
    t = open(path, encoding='utf-8', errors='replace').read()
    years = re.findall(r'<th class="Series5">(\d{4})</th>', t)
    if not years:
        raise ConfigError(f'{path}: no year header')
    out = {}
    for key, sid in series.items():
        m = re.search(r'class="Current2">\s*([\d,]+)\s*</td>\s*<td[^>]*class="DataHist"><a href="[^"]*s=' + sid + r'&', t)
        if not m:
            raise ConfigError(f'{path}: series {sid} not found')
        out[key] = float(m.group(1).replace(',', ''))
    return out, int(years[-1])


def us_motor_fuel(pmm_path, mer_path, foks_path, year=2022):
    """USA road-fuel excise revenue, USD million, as a NEERS-like revenue {(ROAD, pet): [tax, 0, million bbl,
    'million_bbl']} (energy_tax_usa): the base is the taxed road-fuel volume, so tax / base is the specific rate per
    barrel; S13 converts barrels to GJ with the S11 petroleum-products factor (GTAP 12 ch.12 §12.4.4).

    Rate per gallon: federal excise and LUST fee (26 USC 4081, 4041(d): 18.4 c gasoline, 24.4 c diesel) plus the
    EIA average state excise, each the mean of the rates in effect on 1 January and 1 July of the year (PMM).
    Volume: MER T3.7c motor gasoline consumed by the transportation sector, and distillate consumed by the
    transportation sector times the on-highway share of transportation distillate sales (FOKS, latest year:
    rail and vessel bunkering do not pay road-fuel tax). Returns (revenue dict, detail dict)."""
    pmm = read_pmm_motor_fuel(pmm_path)
    rate = {f: sum(v[f'{k}_{f}'] for v in pmm.values() for k in ('fed', 'state')) / len(pmm) for f in ('gasoline', 'diesel')}
    fed = {f: sum(v[f'fed_{f}'] for v in pmm.values()) / len(pmm) for f in ('gasoline', 'diesel')}
    kbd = read_mer_annual(mer_path, US_MER_SERIES, year)
    foks, foks_year = read_foks_latest(foks_path, US_FOKS_SERIES)
    share = foks['on_highway'] / foks['transportation']
    if not 0.0 < share <= 1.0:
        raise ConfigError(f'{foks_path}: on-highway share {share}')
    gal = {'gasoline': kbd['gasoline'] * 1000.0 * GAL_PER_BBL * 365.0, 'diesel': kbd['diesel'] * 1000.0 * GAL_PER_BBL * 365.0 * share}
    tax = {f: gal[f] * rate[f] / 1e6 for f in gal}
    detail = dict(rate_usd_per_gal=rate, federal_usd_per_gal=fed, gallons=gal, tax_musd=tax, onhighway_share=share,
                  onhighway_share_year=foks_year, pmm=pmm)
    bbl = (gal['gasoline'] + gal['diesel']) / GAL_PER_BBL / 1e6
    detail['million_bbl'] = bbl
    return {(ROAD_SECTOR, 'pet'): [tax['gasoline'] + tax['diesel'], 0.0, bbl, BASE_BBL]}, detail


ROAD_SECTOR = 'ROAD'


BANDS = ('GJ20-199', 'KWH2500-4999')      # Eurostat medium household bands (gas D2, electricity DC)


def eurostat_rates(paths):
    """Report-only cross-check (S10-Renergyeu): Eurostat 2022 non-VAT taxes and levies over the price
    excluding taxes, medium household band (BANDS), EUR, mean of 2022-S1 and S2. {(geo, product, consumer): rate}."""
    out = {}
    for (product, consumer), path in paths.items():
        val = defaultdict(dict)
        with open(path, newline='') as fh:
            for row in csv.DictReader(fh):
                if row.get('currency') != 'EUR' or not row.get('OBS_VALUE'):
                    continue
                if row.get('nrg_cons') not in BANDS or row.get('unit') not in ('KWH', 'GJ_GCV'):
                    continue
                if row['nrg_cons'] in ('GJ20-199',) and row['unit'] != 'GJ_GCV':
                    continue
                if not row['TIME_PERIOD'].startswith('2022'):
                    continue
                val[(row['geo'], row['TIME_PERIOD'])][row['tax']] = float(row['OBS_VALUE'])
        acc = defaultdict(list)
        for (geo, _p), v in val.items():
            if v.get('X_TAX') and 'X_VAT' in v:
                acc[geo].append((v['X_VAT'] - v['X_TAX']) / v['X_TAX'])
        for geo, xs in acc.items():
            out[(geo, product, consumer)] = sum(xs) / len(xs)
    return out
