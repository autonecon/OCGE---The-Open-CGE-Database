"""S11 source readers: EI prices and conversion factors, EIA spot prices, BACI energy lines, UNSD coal heat values.

Each reader takes a path the stage has already registered with Stage.inp (SHA checked against MANIFEST)
and returns plain Python structures. A missing value that the method needs stops the run.
"""
import csv
import io
import json
import zipfile

import numpy as np
import openpyxl
import pandas as pd

# Commodity names: S11 (S01 sector code) <-> prep (volumes_2022.csv).
COMMODITIES = ('coa', 'oil', 'gas', 'pet', 'ely')
PREP_NAME = {'coa': 'coal', 'oil': 'crude', 'gas': 'gas', 'pet': 'refined', 'ely': 'electricity'}
# Annual natural unit of each commodity in S11, and the factor from the prep unit.
UNIT = {'coa': 'Mt', 'oil': 'million bbl', 'gas': 'bcm', 'pet': 'million bbl', 'ely': 'TWh'}
PRICE_UNIT = {'coa': 'USD/t', 'oil': 'USD/bbl', 'gas': 'USD million/bcm', 'pet': 'USD/bbl', 'ely': 'USD/MWh'}
DAYS = 365
FROM_PREP = {'coa': 1.0, 'oil': DAYS / 1000.0, 'gas': 1.0, 'pet': DAYS / 1000.0, 'ely': 1.0}   # kb/d -> million bbl a year

GAS_HS = ('271111', '271121')
ELY_HS = ('271600',)
# fix-round B9: BACI HS17 lines for the independent unit-value check of the crude and product export prices
# (BACI publishes HS 2710 at four digits only, as 271000)
VPV_HS = ('270900', '271000')
VPV_COMMODITY = {'270900': 'oil', '271000': 'pet'}
LNG_BCM_PER_MT = 1.36            # EI 2025 'Approximate conversion factors': 1 million tonnes LNG = 1.36 bcm
TOE_PER_BBL_CRUDE = 0.1364       # EI: 1 barrel crude = 0.1364 tonnes; 1 tonne crude = 1 toe by definition
MTOE_PER_BCM = 0.8598452278589853    # EI: 1 bcm natural gas = 0.8598 Mtoe
MTOE_PER_TWH = 0.086             # EI: 1 kWh = 860 kcal
GJ_PER_TOE = 41.868
COAL_TJ_PER_KT_DEFAULT = 25.0    # EI: 1 EJ is about 40 million tonnes of hard coal


def _rows(ws):
    for r in ws.iter_rows(values_only=True):
        yield [x for x in r]


def ei_prices(path):
    """2022 crude markers (USD/bbl), refining margins (USD/bbl), product-basket toe/bbl, from the EI 2025 workbook."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out = {}
    for r in _rows(wb['Spot crude prices']):
        if r and r[0] == 2022:
            vals = [x for x in r[1:] if x is not None]
            out['dubai'], out['brent'], out['forcados'], out['wti'] = (float(v) for v in vals[:4])
    for r in _rows(wb['Oil - Regional refining margins']):
        if r and r[0] == 2022:
            vals = [x for x in r[1:] if x is not None]
            out['margin_usgc'], out['margin_nwe'], out['margin_singapore'] = (float(v) for v in vals[:3])
    for r in _rows(wb['Approximate conversion factors']):
        cells = [x for x in r if x is not None]
        if cells and isinstance(cells[0], str) and cells[0].strip().lower().startswith('product basket'):
            t_per_bbl, gj_per_t = float(cells[1]), float(cells[5])
            out['toe_per_bbl_products'] = t_per_bbl * gj_per_t / GJ_PER_TOE
            out['bbl_per_t_products'] = 1.0 / t_per_bbl
    need = ('dubai', 'brent', 'forcados', 'wti', 'margin_usgc', 'margin_nwe', 'margin_singapore', 'toe_per_bbl_products')
    miss = [k for k in need if k not in out]
    if miss:
        raise SystemExit(f'EI workbook: no 2022 value for {miss}')
    return out


def ei_coal_markers(path):
    """EI 2022 coal marker prices (USD/t), report only."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    head, out = None, {}
    for r in _rows(wb['Coal & Uranium - Prices']):
        cells = [x for x in r if x is not None]
        if cells and isinstance(cells[0], str) and cells[0].startswith('United States'):
            head = [str(c).rstrip('0123456789 ').strip() for c in cells]
        if head and cells and cells[0] == 2022:
            for name, v in zip(head, cells[1:]):
                if isinstance(v, (int, float)):
                    out[name] = float(v)
    return out


def eia_spot_2022(path):
    """EIA annual spot prices, 2022 row, by series name (USD per barrel or per gallon as published)."""
    sheets = pd.read_excel(path, sheet_name=None, header=2)
    out = {}
    for name, df in sheets.items():
        if name == 'Contents':
            continue
        row = df[df.iloc[:, 0].astype(str).str.startswith('2022')]
        if len(row) != 1:
            continue
        for col in df.columns[1:]:
            out[str(col)] = float(row.iloc[0][col])
    return out


def eia_annual_2022(path):
    """EIA annual series workbook (any sheet), 2022 row: {series name: value}."""
    out = {}
    for name, df in pd.read_excel(path, sheet_name=None, header=2).items():
        if name == 'Contents':
            continue
        row = df[df.iloc[:, 0].astype(str).str.startswith('2022')]
        if len(row) == 1:
            for col in df.columns[1:]:
                out[str(col)] = pd.to_numeric(row.iloc[0][col], errors='coerce')
    return out


def baci_energy(zip_path, member, codes_member, hs_lines):
    """BACI rows for the given HS6 lines: exporter iso3, importer iso3, hs6, value (thousand USD), quantity (tonnes)."""
    with zipfile.ZipFile(zip_path) as zf:
        cc = pd.read_csv(zf.open(codes_member), dtype=str)
        iso = dict(zip(cc['country_code'], cc['country_iso3']))
        keep = set(hs_lines)
        parts = []
        with zf.open(member) as fh:
            for ch in pd.read_csv(fh, dtype={'t': int, 'i': str, 'j': str, 'k': str, 'v': float, 'q': str},
                                  chunksize=2_000_000):
                ch['k'] = ch['k'].str.zfill(6)
                parts.append(ch[ch['k'].isin(keep)])
    d = pd.concat(parts, ignore_index=True)
    d['q'] = pd.to_numeric(d['q'].str.strip(), errors='coerce')
    d['exp_iso'] = d['i'].map(iso)
    d['imp_iso'] = d['j'].map(iso)
    return d[['t', 'exp_iso', 'imp_iso', 'k', 'v', 'q']]


def baci_energy_years(zip_path, codes_member, hs_lines, years=range(2017, 2025), vintage='V202601'):
    """Beta v4 P13 (choice ras_seed_routes): BACI rows of the given HS6 lines in every year file of the locked HS17 zip
    within years (the HS17 vintage starts in 2017). Same columns as baci_energy; years without a file are skipped and
    listed in the second return value."""
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
    parts, missing = [], []
    for y in years:
        member = f'BACI_HS17_Y{y}_{vintage}.csv'
        if member not in names:
            missing.append(y)
            continue
        parts.append(baci_energy(zip_path, member, codes_member, hs_lines))
    if not parts:
        raise SystemExit(f'{zip_path}: no BACI year file in {list(years)}')
    return pd.concat(parts, ignore_index=True), missing


def jodi_refinery_crude_2022(zip_path, alpha2_to_iso3, member='NewProcedure_Primary_CSV.csv'):
    """JODI-Oil 2022 crude oil refinery intake (CRUDEOIL REFINOBS), million bbl by iso3: the sum of the
    twelve monthly KBBL values. Countries without all twelve months are left out."""
    months = {}
    with zipfile.ZipFile(zip_path) as z, z.open(member) as f:
        f.readline()
        for raw in f:
            p = raw.decode('utf-8', 'replace').strip().split(',')
            if len(p) < 6 or not p[1].startswith('2022-') or p[2] != 'CRUDEOIL' or p[3] != 'REFINOBS' or p[4] != 'KBBL':
                continue
            try:
                v = float(p[5])
            except ValueError:
                continue
            months.setdefault(p[0], {})[p[1]] = v
    out = {}
    for a2, m in months.items():
        iso = alpha2_to_iso3.get(a2)
        if iso and len(m) == 12:
            out[iso] = sum(m.values()) / 1000.0
    return out


REFINERY_GAS_TRANSACTIONS = ('0925', '086')   # own use by oil refineries; transformation in oil refineries


def unsd_refinery_gas_2022(path, num_to_iso3):
    """UNSD 2022 natural gas (3000) used by oil refineries, TJ by iso3: own use (0925) plus
    transformation (086). Only countries that report either transaction are returned."""
    out = {}
    with open(path, newline='') as fh:
        for r in csv.DictReader(fh):
            if r['COMMODITY'] != '3000' or r['TRANSACTION'] not in REFINERY_GAS_TRANSACTIONS or r['UNIT_MEASURE'] != 'TJ':
                continue
            try:
                v = float(r['OBS_VALUE'])
            except ValueError:
                continue
            iso = num_to_iso3.get(r['REF_AREA'].zfill(3))
            if iso:
                out[iso] = out.get(iso, 0.0) + v
    return out


def unsd_coal_heat(path, num_to_iso3):
    """UNSD 2022 coal production heat value by iso3: TJ per thousand tonnes, weighted over 0100 and 0200."""
    tj = {}
    kt = {}
    with open(path, newline='') as fh:
        for r in csv.DictReader(fh):
            if r['COMMODITY'] not in ('0100', '0200') or r['TRANSACTION'] != '01' or r['UNIT_MEASURE'] != 'TN':
                continue
            try:
                q, f = float(r['OBS_VALUE']), float(r['CONVERSION_FACTOR'])
            except ValueError:
                continue
            iso = num_to_iso3.get(r['REF_AREA'].zfill(3))
            if not iso or q <= 0 or f <= 0:
                continue
            tj[iso] = tj.get(iso, 0.0) + q * f
            kt[iso] = kt.get(iso, 0.0) + q
    return {k: tj[k] / kt[k] for k in tj if kt[k] > 0}, kt


def _unsd_rows(path, commodity, transactions, unit, mult=None):
    """UNSD 2022 rows of one commodity: yields (REF_AREA numeric code, transaction, value) for the given transactions
    and unit (and SDMX UNIT_MULT if given); rows without a number are skipped."""
    with open(path, newline='') as fh:
        for r in csv.DictReader(fh):
            if r['COMMODITY'] != commodity or r['TRANSACTION'] not in transactions or r['UNIT_MEASURE'] != unit:
                continue
            if mult is not None and str(r['UNIT_MULT']).strip() != str(mult):
                continue
            try:
                v = float(r['OBS_VALUE'])
            except ValueError:
                continue
            yield r['REF_AREA'].zfill(3), r['TRANSACTION'], v


def unsd_coal_production_2022(path, num_to_iso3):
    """UNSD 2022 production (transaction 01) of 0100 hard coal and 0200 brown coal, thousand t:
    {(iso3, commodity code): kt} (fix-round A9 lignite rule)."""
    out = {}
    for code in ('0100', '0200'):
        for area, _, v in _unsd_rows(path, code, ('01',), 'TN', 3):
            iso = num_to_iso3.get(area)
            if iso:
                out[(iso, code)] = out.get((iso, code), 0.0) + v
    return out


def acr_us_lignite_2022(path):
    """EIA Annual Coal Report 2022 table 31: U.S. Total lignite average sales price at the mine, USD per short ton."""
    d = pd.read_csv(path, dtype=str)
    return float(d.loc[d['state'] == 'U.S. Total', 'lignite'].iloc[0])


def unsd_crude_direct_use_2022(path, num_to_iso3, transactions):
    """UNSD 2022 conventional crude oil (4100) used outside refineries, thousand t: {(iso3, transaction): kt}
    for the given transactions (config/s11/crude_direct_users.csv; fix-round A8)."""
    out = {}
    for area, tr, v in _unsd_rows(path, '4100', tuple(transactions), 'TN', 3):
        iso = num_to_iso3.get(area)
        if iso and v > 0:
            out[(iso, tr)] = out.get((iso, tr), 0.0) + v
    return out


def unsd_gas_by_transaction_2022(path, num_to_iso3, transactions):
    """UNSD 2022 natural gas (3000) in TJ: {(iso3, transaction): TJ} for the given transactions (round 3: the gas burnt
    by the users config/s11/crude_direct_users.csv lists, so their B06 cell is split by the value of both fuels)."""
    out = {}
    for area, tr, v in _unsd_rows(path, '3000', tuple(transactions), 'TJ'):
        iso = num_to_iso3.get(area)
        if iso and v > 0:
            out[(iso, tr)] = out.get((iso, tr), 0.0) + v
    return out


# SIEC 46 oil products, leaf codes only (as prep_energy_volumes.py UNSD_PRODUCT_CODES): the products that make up pet
UNSD_OIL_PRODUCT_CODES = ('4610', '4620', '4630', '4640', '4651', '4652', '4653', '4661', '4669', '4670', '4680',
                          '4691', '4692', '4693', '4694', '4695', '4699')


def unsd_products_by_transaction_2022(path, num_to_iso3, transactions):
    """UNSD 2022 oil products (SIEC 46 leaf codes) in thousand tonnes (round 3, final QA 2 item 3: the refined fuel burnt
    by the power plants of the listed crude users, so their power column holds crude, gas and refined fuel at the energy
    balance's volumes valued at S11 prices). Returns ({(iso3, transaction): kt} for the given transactions,
    {iso3: total energy supply (GA) kt})."""
    out, supply = {}, {}
    for code in UNSD_OIL_PRODUCT_CODES:
        for area, tr, v in _unsd_rows(path, code, tuple(transactions) + ('GA',), 'TN', 3):
            iso = num_to_iso3.get(area)
            if not iso:
                continue
            if tr == 'GA':
                supply[iso] = supply.get(iso, 0.0) + v
            elif v > 0:
                out[(iso, tr)] = out.get((iso, tr), 0.0) + v
    return out, supply


GAS_OWN_USE_TRANSACTIONS = ('0912', '0931', '0934')   # own use by oil and gas extraction, gas separation, LNG plants


def unsd_gas_own_use_2022(path, num_to_iso3):
    """UNSD 2022 natural gas (3000), TJ by iso3: own use of the gas industry (0912 + 0931 + 0934) and total energy
    supply (GA). Returns ({iso3: own-use TJ}, {iso3: supply TJ}); fix-round A10."""
    own, supply = {}, {}
    for area, tr, v in _unsd_rows(path, '3000', GAS_OWN_USE_TRANSACTIONS + ('GA',), 'TJ'):
        iso = num_to_iso3.get(area)
        if not iso:
            continue
        d = supply if tr == 'GA' else own
        d[iso] = d.get(iso, 0.0) + v
    return own, supply


# fix round wG (QA round 2 P5): energy-industry own use plus losses of each energy good, by the industry that makes it
# (GTAP 12 ch.12 Table 12.3: coal mines -> coa; oil and gas extraction -> oil (crude inflows) and gas (gas inflows); gas
# works -> gas; electricity, CHP and heat plants and pumped storage -> ely; LNG plants -> p_c, so not gas). UNSD SIEC
# commodity codes, units and IRES transaction codes (UNSD DF_UNDATA_ENERGY codelist: 0911 coal mines, 0912 oil and gas
# extraction, 0922 gas works, 0926 pump-storage plants, 0927 electricity, CHP and heat plants, 0931 natural gas separation,
# 101 losses). Losses count for coal, crude and electricity; gas losses are distribution losses of gas distribution (gdt),
# which this build keeps inside ely (fix list B7), not purchases of the gas (extraction) column.
OWN_USE_SPEC = {
    'coa': (('0100', '0200'), 'TN', ('0911',), True),
    'oil': (('4100',), 'TN', ('0912',), True),
    'gas': (('3000',), 'TJ', ('0912', '0922', '0931'), False),
    'ely': (('7000',), 'GWHR', ('0926', '0927'), True),
    # beta v4 P15 (own_use_shares, pet): oil products (SIEC 46 leaf codes, kt) used by oil refineries (0925) plus losses,
    # over product output; tonnes summed across products
    'pet': (UNSD_OIL_PRODUCT_CODES, 'TN', ('0925',), True),
}
# UNSD energy areas that combine an ISO country with a small territory (config/prep_energy/unsd_area_names.csv): for a
# share of own use in output they stand for the country, used only where UNSD has no row under the ISO code itself
OWN_USE_COMBINATION_AREAS = {'251': 'FRA', '382': 'ITA', '579': 'NOR', '757': 'CHE'}
LOSS_TRANSACTION = '101'
PRODUCTION_TRANSACTION = '01'
IMPORT_TRANSACTION = '03'      # beta v4 dry run: losses on imported supply (ely_losses_domestic_share)


def unsd_own_use_2022(path, num_to_iso3, spec=OWN_USE_SPEC, combos=OWN_USE_COMBINATION_AREAS):
    """UNSD 2022 own use, losses, production and imports of each energy good, by iso3: {good: {iso3: dict(own, losses,
    production, imports)}}, in TJ for coal (kt x the row's conversion factor; kt where it has none) and gas, kt for crude and
    GWh for electricity. A country is listed for a good where UNSD has any of the three transactions. A combination
    area (combos) stands for its country only where the country has no row of its own."""
    present = set()
    with open(path, newline='') as fh:
        for r in csv.DictReader(fh):
            present.add(r['REF_AREA'].zfill(3))
    num_to_iso3 = dict(num_to_iso3)
    iso_present = {num_to_iso3[a] for a in present if a in num_to_iso3}
    for a, iso in combos.items():
        if a in present and iso not in iso_present:
            num_to_iso3[a] = iso
    want = {}
    for g, (codes, unit, own_tr, losses) in spec.items():
        for code in codes:
            want[code] = (g, unit, set(own_tr), losses)
    out = {g: {} for g in spec}
    with open(path, newline='') as fh:
        for r in csv.DictReader(fh):
            w = want.get(r['COMMODITY'])
            if w is None or r['UNIT_MEASURE'] != w[1]:
                continue
            g, _, own_tr, with_losses = w
            tr = r['TRANSACTION']
            if tr in own_tr:
                key = 'own'
            elif tr == LOSS_TRANSACTION and with_losses:
                key = 'losses'
            elif tr == PRODUCTION_TRANSACTION:
                key = 'production'
            elif tr == IMPORT_TRANSACTION:
                key = 'imports'
            else:
                continue
            try:
                v = float(r['OBS_VALUE'])
            except ValueError:
                continue
            if g == 'coa':
                try:
                    f = float(r['CONVERSION_FACTOR'])
                except ValueError:
                    f = 0.0
                v = v * f if f > 0 else v
            iso = num_to_iso3.get(r['REF_AREA'].zfill(3))
            if not iso:
                continue
            d = out[g].setdefault(iso, dict(own=0.0, losses=0.0, production=0.0, imports=0.0))
            d[key] += v
    return out


def eia_ngpl_heat_2022(path):
    """Beta v5 N2: {geography: MMBtu per barrel} of 2022 NGPL production from the EIA international bulk file
    (product 58 activity 1: quadrillion Btu, 1e9 MMBtu, over thousand barrels per day x 365); 'WORL' is the world."""
    q, b = {}, {}
    with open(path) as fh:
        for line in fh:
            if '"INTL.58-1-' not in line or ('-QBTU.A"' not in line and '-TBPD.A"' not in line):
                continue
            d = json.loads(line)
            v = next((x[1] for x in d.get('data', []) if x[0] == '2022' and isinstance(x[1], (int, float))), None)
            if v is None:
                continue
            g = 'WORL' if d['series_id'].startswith('INTL.58-1-WORL-') else d['geography']
            (q if d['series_id'].endswith('-QBTU.A') else b)[g] = float(v)
    return {g: q[g] * 1e6 / (b[g] * 365.0) for g in q if b.get(g, 0) > 0}


def mer_annual(path, msn):
    """EIA Monthly Energy Review CSV: the 2022 annual value (YYYYMM 202213) of one series."""
    df = pd.read_csv(path, dtype=str)
    row = df[(df['MSN'] == msn) & (df['YYYYMM'] == '202213')]
    if len(row) != 1:
        return None, ''
    return float(row.iloc[0]['Value']), row.iloc[0]['Unit']


def ei_gas_hubs_2022(path):
    """EI 2025 'Gas Prices ' sheet, 2022 row: {column header: USD per million Btu}."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    head, out = None, {}
    for r in _rows(wb['Gas Prices ']):
        cells = [x for x in r if x is not None]
        if cells and cells[0] == 'Japan1':
            head = [str(c).split('\n')[0].rstrip('0123456789 ').strip() for c in cells]
        if head and cells and cells[0] == 2022:
            for name, v in zip(head, cells[1:]):
                if isinstance(v, (int, float)):
                    out[name] = float(v)
    return out


# EI country names that differ from the IEA names of iea_country_iso3.csv (refinery throughput sheet)
EI_NAME_ISO3 = {'US': 'USA', 'Canada': 'CAN', 'Brazil': 'BRA', 'Chile': 'CHL', 'Peru': 'PER', 'Trinidad & Tobago': 'TTO',
                'Belgium': 'BEL', 'Bulgaria': 'BGR', 'Czech Republic': 'CZE', 'Denmark': 'DNK', 'Finland': 'FIN', 'Germany': 'DEU',
                'Greece': 'GRC', 'Ireland': 'IRL', 'Italy': 'ITA', 'Lithuania': 'LTU', 'Netherlands': 'NLD', 'Norway': 'NOR',
                'Portugal': 'PRT', 'Romania': 'ROU', 'Slovakia': 'SVK', 'Spain': 'ESP', 'Sweden': 'SWE', 'Switzerland': 'CHE',
                'Turkey': 'TUR', 'Belarus': 'BLR', 'Russian Federation': 'RUS', 'Israel': 'ISR', 'Saudi Arabia': 'SAU',
                'United Arab Emirates': 'ARE', 'Morocco': 'MAR', 'South Africa': 'ZAF', 'Australia': 'AUS', 'Japan': 'JPN',
                'New Zealand': 'NZL', 'Philippines': 'PHL', 'Singapore': 'SGP', 'South Korea': 'KOR', 'Taiwan': 'TWN'}


def ei_refinery_throughput_2022(path, name_to_iso):
    """EI 2025 'Oil refinery - throughput' (thousand barrels daily): {iso3: 2022 million bbl}. Country rows only (the
    'Total', 'Other' and 'of which' aggregates have no iso3); names through EI_NAME_ISO3, then the IEA name table."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    col, out = None, {}
    for r in _rows(wb['Oil refinery - throughput']):
        if col is None:
            if r and 2022 in r:
                col = list(r).index(2022)
            continue
        if not (r and isinstance(r[0], str)) or len(r) <= col:
            continue
        iso = EI_NAME_ISO3.get(r[0]) or name_to_iso.get(r[0])
        if iso and isinstance(r[col], (int, float)) and r[col] > 0:
            out[iso] = float(r[col]) * DAYS / 1000.0
    return out


def ei_interregional_gas_2022(path, block, row):
    """EI 2025 'Gas - Trade movements' (inter-regional trade, bcm at 40 MJ/m3 GCV): the 2022 value of `row`
    inside the region block `block` (e.g. 'Other CIS', '  of which: China'). A missing cell stops the run."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    col, cur = None, None
    for r in _rows(wb['Gas - Trade movements']):
        if r and r[0] == 'Billion cubic metres':
            col = r.index(2022)
            continue
        if col is None or not r or not isinstance(r[0], str):
            continue
        if all(x is None for x in r[1:]):
            cur = r[0].strip()
        elif cur == block and r[0].replace('of which:', '').strip() == row.replace('of which:', '').strip():
            v = r[col]
            if not isinstance(v, (int, float)):
                break
            return float(v)
    raise SystemExit(f'EI Gas - Trade movements: no 2022 value for {block!r} / {row!r}')


def aer_aeco_2022(path):
    """AER ST98 'Tables' sheet, Table S1.2: 2022 AECO-C price, Cdn$ per GJ (actual, Canadian Gas Price Reporter)."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    col, head = None, None
    for r in _rows(wb['Tables']):
        r = list(r)
        if col is None:
            col = next((j for j, x in enumerate(r) if isinstance(x, str) and x.strip().startswith('Table S1.2')), None)
        elif head is None and 2022 in r[col:]:
            head = r
        elif head is not None and isinstance(r[col], str) and r[col].strip().startswith('AECO-C price (Cdn$/GJ)'):
            return float(r[head.index(2022, col)])
    raise SystemExit('AER ST98: no AECO-C 2022 value in Table S1.2')


IEA_PRODUCT = {'Oil': 'pet', 'Gas': 'gas', 'Coal': 'coa', 'Electricity': 'ely'}


def iea_subsidies_2022(path, name_to_iso):
    """IEA fossil-fuel subsidies 2022 by (S11 commodity, iso3), real 2024 USD million."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    col, out, unmapped = None, {}, set()
    for r in _rows(wb['Subsidies by country']):
        if col is None:
            if r and r[0] == 'Country':
                col = list(r).index(2022)
            continue
        if not (r and isinstance(r[0], str) and r[1] in IEA_PRODUCT):
            continue
        iso = name_to_iso.get(r[0])
        if not iso:
            unmapped.add(r[0])
            continue
        v = r[col]
        if isinstance(v, (int, float)) and v > 0:
            out[(IEA_PRODUCT[r[1]], iso)] = float(v)
    if unmapped:
        raise SystemExit(f'IEA subsidy countries without an iso3 in config/s11/iea_country_iso3.csv: {sorted(unmapped)}')
    return out


def wdi_us_deflator_ratio(path):
    """WDI API JSON (one indicator, USA): value(2022) / value(2024), which takes IEA real-2024 USD to nominal 2022."""
    import json
    rows = json.load(open(path))[1]
    v = {int(r['date']): r['value'] for r in rows if r['value'] is not None}
    if 2022 not in v or 2024 not in v:
        raise SystemExit(f'{path}: needs 2022 and 2024')
    return float(v[2022] / v[2024])


EUROSTAT_ALPHA2 = {'EL': 'GR', 'UK': 'GB'}


def eurostat_2022(path, band, unit, alpha2_to_iso3):
    """Eurostat nrg_pc_203 / nrg_pc_205: 2022 price excluding taxes and levies (X_TAX), EUR, one consumption
    band and unit, mean of the semesters reported. {iso3: (EUR per unit, semesters used)}."""
    d = pd.read_csv(path, dtype=str)
    d = d[(d['tax'] == 'X_TAX') & (d['currency'] == 'EUR') & (d['nrg_cons'] == band) & (d['unit'] == unit) & d['TIME_PERIOD'].str.startswith('2022')]
    d = d[pd.to_numeric(d['OBS_VALUE'], errors='coerce') > 0]
    out = {}
    for geo, g in d.groupby('geo'):
        iso = alpha2_to_iso3.get(EUROSTAT_ALPHA2.get(geo, geo))
        if iso:
            out[iso] = (float(pd.to_numeric(g['OBS_VALUE']).mean()), '+'.join(sorted(g['TIME_PERIOD'])))
    return out


def acr_us_coal_2022(path):
    """EIA Annual Coal Report 2022 table 28: U.S. total average sales price, USD per short ton."""
    d = pd.read_csv(path, dtype=str)
    return float(d.loc[d['state'] == 'U.S. Total', 'total_2022'].iloc[0])


def epa_us_industrial_2022(path):
    """EIA Electric Power Annual 2022 table 2.4, Total Electric Industry block: 2022 industrial price, US cents per kWh."""
    x = pd.read_excel(path, header=None)
    head = x.index[x[0].astype(str).str.strip() == 'Year'][0]
    cols = [str(c).strip() for c in x.loc[head]]
    for i in range(head + 1, len(x)):
        if str(x.loc[i, 0]).strip() == '2022':
            return float(x.loc[i, cols.index('Industrial')])
    raise SystemExit(f'{path}: no 2022 row')


def wdi_value(path, series, iso3, year):
    """One value from the WDI long extract (columns series, iso3, year, value)."""
    d = pd.read_csv(path, dtype={'series': str, 'iso3': str})
    v = d.loc[(d['series'] == series) & (d['iso3'] == iso3) & (d['year'] == year), 'value']
    if v.empty:
        raise SystemExit(f'{path}: no {series} {iso3} {year}')
    return float(v.iloc[0])


# ------------------------------------------------------------------ Fable QA D-02 / D-04 / C-03 (David 2026-10-25 "do all fixes")
EUROSTAT_NOT_A_PARTNER = ('TOTAL', 'NSP')


def eurostat_gas_partners_2022(ti_path, te_path, geo, alpha2_to_iso3):
    """Eurostat nrg_ti_gas / nrg_te_gas 2022, natural gas (G3000), million m3: the imports of `geo` by partner as it
    reports them, its imports reported without origin (NSP), and each partner's own report of exports to `geo` beyond
    what `geo` names from it (the mirror excess, at least zero). Partners are iso3; aggregates (AFR_OTH, ...) count
    with NSP. Returns (named, nsp, mirror_excess, total), volumes in bcm."""
    ti, te = pd.read_csv(ti_path, dtype={'OBS_VALUE': float}), pd.read_csv(te_path, dtype={'OBS_VALUE': float})
    ti, te = ti[(ti['siec'] == 'G3000') & (ti['unit'] == 'MIO_M3')], te[(te['siec'] == 'G3000') & (te['unit'] == 'MIO_M3')]
    imp = ti[ti['geo'] == geo].groupby('partner')['OBS_VALUE'].sum() / 1000.0
    if imp.empty or 'TOTAL' not in imp:
        raise SystemExit(f'{ti_path}: no 2022 G3000 imports for {geo}')

    def iso(a):
        return alpha2_to_iso3.get(EUROSTAT_ALPHA2.get(a, a)) if len(a) == 2 else None

    named, nsp = {}, float(imp.get('NSP', 0.0))
    for p, v in imp.items():
        if p in EUROSTAT_NOT_A_PARTNER or not v > 0:
            continue
        if iso(p):
            named[iso(p)] = named.get(iso(p), 0.0) + float(v)
        else:
            nsp += float(v)
    mirror = {}
    ex = te[te['partner'] == geo].groupby('geo')['OBS_VALUE'].sum() / 1000.0
    for g, v in ex.items():
        if iso(g) and g != geo:
            mirror[iso(g)] = max(float(v) - named.get(iso(g), 0.0), 0.0)
    return named, nsp, mirror, float(imp['TOTAL'])


COMTRADE_LINES = {'coa': ('2701',), 'oil': ('2709',), 'gas': ('271111', '271121'), 'pet': ('2710',), 'ely': ('2716',)}
COMTRADE_ISO = {'842': 'USA', '251': 'FRA', '699': 'IND', '757': 'CHE', '490': 'TWN', '579': 'NOR'}   # Comtrade codes off ISO 3166


def comtrade_reexport_shares_2022(folder, num_to_iso3, lines=COMTRADE_LINES):
    """UN Comtrade 2022 (public API, dataset/data/un_comtrade_rx_2022): for each reporter that reports re-exports at all
    (a 2022 RX total, cmdCode TOTAL) and each good, re-exports to the world over exports to the world of the good's lines
    (Comtrade X includes RX), by net weight where every row of both flows has one, else by value; a reporter of RX with
    exports and no RX row for the good has a share of zero. Returns {(iso3, good): dict(share, basis, x_musd, rx_musd)}."""
    import json

    def iso(c):
        return COMTRADE_ISO.get(str(c), num_to_iso3.get(str(c).zfill(3)))

    def load(name):
        d = json.load(open(f'{folder}/{name}'))
        if 'data' not in d:
            raise SystemExit(f'{folder}/{name}: no data ({str(d)[:120]})')
        return d['data']

    rep = {iso(r['reporterCode']) for r in load('comtrade_RX_TOTAL_2022.json') if (r.get('primaryValue') or 0) > 0} - {None}
    flows = {}
    for g, ls in lines.items():
        for l in ls:
            for f in ('X', 'RX'):
                for r in load(f'comtrade_{f}_{l}_2022.json'):
                    a = flows.setdefault((iso(r['reporterCode']), g), {'X': [0.0, 0.0, True], 'RX': [0.0, 0.0, True]})[f]
                    w = float(r.get('netWgt') or 0.0)
                    a[0] += float(r.get('primaryValue') or 0.0)
                    a[1] += w
                    a[2] &= w > 0
    out = {}
    for (r, g), a in flows.items():
        x, rx = a['X'], a['RX']
        if r not in rep or x[0] <= 0:
            continue
        s, b = (rx[1] / x[1], 'net_weight') if (x[2] and rx[2] and x[1] > 0 and rx[0] > 0) else (rx[0] / x[0], 'value')
        out[(r, g)] = dict(share=min(max(s, 0.0), 1.0), basis=b, x_musd=x[0] / 1e6, rx_musd=rx[0] / 1e6)
    return out


def export_tax_line_rates(path, sectors):
    """config/s10/export_tax_rates_2022.csv (exporter, sector '*', hs_prefixes, rate_pct): {exporter: {sector: {BACI line:
    rate}}} for the goods whose statutory rate differs between their BACI lines (RUS gas: LNG 271111 exempt, pipeline
    271121 30 percent). sectors: {sector: BACI lines}; a prefix of six digits names its line, a shorter one every line
    it starts. A good with one rate is left out (its rate is the S10 rate itself)."""
    d = pd.read_csv(path, dtype=str)
    out = {}
    for x in d.itertuples():
        for pre in str(x.hs_prefixes).split(';'):
            pre = pre.strip()
            for s, ls in sectors.items():
                for l in ls:
                    if l == pre or (len(pre) < 6 and l.startswith(pre)):
                        out.setdefault(x.exporter, {}).setdefault(s, {})[l] = float(x.rate_pct) / 100.0
    return {e: {s: r for s, r in g.items() if len(set(r.values())) > 1} for e, g in out.items()
            if any(len(set(r.values())) > 1 for r in g.values())}


def comtrade_energy_reporters_2022(folder, num_to_iso3, lines=COMTRADE_LINES):
    """Beta v5 R (choice ras_route_caps): the iso3 codes that report any 2022 export (X) of an energy line to UN Comtrade
    (dataset/data/un_comtrade_rx_2022). A region none of whose members is here is mirror-only: its energy trade is known
    only from its partners' records."""
    import json
    out = set()
    for ls in lines.values():
        for l in ls:
            with open(f'{folder}/comtrade_X_{l}_2022.json') as fh:
                d = json.load(fh)
            if 'data' not in d:
                raise SystemExit(f'{folder}/comtrade_X_{l}_2022.json: no data ({str(d)[:120]})')
            for r in d['data']:
                if (r.get('primaryValue') or 0) > 0:
                    out.add(COMTRADE_ISO.get(str(r['reporterCode']), num_to_iso3.get(str(r['reporterCode']).zfill(3))))
    return out - {None}


def census_imdb_values_2022(path):
    """Beta v5 E2 (choice census_route_hold): US imports for consumption, customs value (con_val, USD), from the Census IMDB
    2022 HS6 summary (dataset/data/census_imdb_2022/hs6_cty_rp_2022.csv), summed over rate provisions. Returns
    {(hs6, census country code): USD million}."""
    out = {}
    with open(path, newline='') as fh:
        for r in csv.DictReader(fh):
            k = (r['hs6'], r['cty'])
            out[k] = out.get(k, 0.0) + float(r['con_val'] or 0.0) / 1e6
    return out
