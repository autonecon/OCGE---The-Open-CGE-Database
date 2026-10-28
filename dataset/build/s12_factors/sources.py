"""S12 source readers. Each returns a tidy frame; none of them fills a gap.

National-accounts compensation by industry: Eurostat FIGARO 2022 (D1, B2A3G, D29X39 rows of the
industry-by-industry table, domestic origin) and OECD Table 6 (S1, current prices). ILOSTAT employment
and earnings margins (GTAP 12 ch.14B Table 14.17 equivalents). USDA ERS agricultural cost shares
(the Fuglie compilation, ch.14A). WDI resource rents, arable land and GDP per capita.
"""
import gzip
import json
import re

import numpy as np
import pandas as pd

# FIGARO uses Eurostat two-letter codes; the two that are not ISO 3166 alpha-2 are EL and UK.
FIGARO_ISO2 = {
    'BE': 'BEL', 'BG': 'BGR', 'CZ': 'CZE', 'DK': 'DNK', 'DE': 'DEU', 'EE': 'EST', 'IE': 'IRL', 'EL': 'GRC',
    'ES': 'ESP', 'FR': 'FRA', 'HR': 'HRV', 'IT': 'ITA', 'CY': 'CYP', 'LV': 'LVA', 'LT': 'LTU', 'LU': 'LUX',
    'HU': 'HUN', 'MT': 'MLT', 'NL': 'NLD', 'AT': 'AUT', 'PL': 'POL', 'PT': 'PRT', 'RO': 'ROU', 'SI': 'SVN',
    'SK': 'SVK', 'FI': 'FIN', 'SE': 'SWE', 'NO': 'NOR', 'CH': 'CHE', 'UK': 'GBR', 'ME': 'MNE', 'MK': 'MKD',
    'AL': 'ALB', 'RS': 'SRB', 'TR': 'TUR', 'RU': 'RUS', 'ZA': 'ZAF', 'CA': 'CAN', 'US': 'USA', 'MX': 'MEX',
    'AR': 'ARG', 'BR': 'BRA', 'CN': 'CHN', 'JP': 'JPN', 'KR': 'KOR', 'IN': 'IND', 'ID': 'IDN', 'SA': 'SAU',
    'AU': 'AUS',
}
VA_ITEMS = ('D1', 'B2A3G', 'D29X39')


def _json_stat(path):
    """Flatten a Eurostat JSON-stat 2.0 dataset into a frame with one column per dimension."""
    d = json.load(open(path))
    ids, sizes = d['id'], d['size']
    cats = []
    for k in ids:
        idx = d['dimension'][k]['category']['index']
        cats.append(sorted(idx, key=idx.get))
    strides = np.cumprod([1] + sizes[::-1])[::-1][1:]
    rows = []
    for flat, v in d['value'].items():
        f = int(flat)
        rec = {}
        for k, s, c in zip(ids, strides, cats):
            rec[k] = c[f // s]
            f %= s
        rec['value'] = float(v)
        rows.append(rec)
    return pd.DataFrame(rows)


def figaro_va(path, year):
    """FIGARO value-added rows: iso3, activity (FIGARO code), item (D1, B2A3G, D29X39), value (EUR m), year."""
    df = _json_stat(path)
    df = df[(df['c_orig'] == 'DOM') & df['ind_ava'].isin(VA_ITEMS) & (df['time'] == str(year))]
    df = df[df['c_dest'].isin(FIGARO_ISO2)]
    out = pd.DataFrame({'iso3': df['c_dest'].map(FIGARO_ISO2), 'activity': df['ind_use'], 'item': df['ind_ava'],
                        'value': df['value'], 'year': int(year)})
    return out[out['activity'].str.match(r'^[A-U]')].reset_index(drop=True)


def _table6(path, base_year):
    """Table 6 rows at or before the base year, current prices (PRICE_BASE V), national currency.
    Where B2A3G is missing but B1G, D1 and D29X39 are published for the same cell, B2A3G = B1G - D1 - D29X39
    (the SNA identity for gross value added at basic prices; config derive_b2a3g). Returns (frame, derived) with
    derived the set of (iso3, year, activity) cells whose B2A3G was derived."""
    use = ['REF_AREA', 'TRANSACTION', 'ACTIVITY', 'UNIT_MEASURE', 'PRICE_BASE', 'TIME_PERIOD', 'OBS_VALUE']
    df = pd.read_csv(path, usecols=use)
    df = df[(df['PRICE_BASE'] == 'V') & (df['UNIT_MEASURE'] == 'XDC') & df['TRANSACTION'].isin(VA_ITEMS + ('B1G',))
            & (df['TIME_PERIOD'] <= base_year) & df['OBS_VALUE'].notna()]
    df = df.rename(columns={'REF_AREA': 'iso3', 'TRANSACTION': 'item', 'ACTIVITY': 'activity', 'TIME_PERIOD': 'year',
                            'OBS_VALUE': 'value'})[['iso3', 'activity', 'item', 'value', 'year']]
    piv = df.pivot_table(index=['iso3', 'year', 'activity'], columns='item', values='value', aggfunc='sum')
    for c in ('B1G', 'D1', 'D29X39', 'B2A3G'):
        if c not in piv.columns:
            piv[c] = np.nan
    m = piv['B2A3G'].isna() & piv[['B1G', 'D1', 'D29X39']].notna().all(axis=1)
    add = (piv.loc[m, 'B1G'] - piv.loc[m, 'D1'] - piv.loc[m, 'D29X39']).rename('value').reset_index().assign(item='B2A3G')
    df = pd.concat([df[df['item'] != 'B1G'], add[['iso3', 'activity', 'item', 'value', 'year']]], ignore_index=True)
    return df, set(map(tuple, add[['iso3', 'year', 'activity']].values))


def oecd_table6(path, base_year):
    """OECD Table 6: iso3, activity, item, value, year. For each country the year is the latest at or before the base
    year where D1 and B2A3G both exist (published or derived). Returns (frame, total-economy rows, derived cells)."""
    df, derived = _table6(path, base_year)
    both = df[df['item'].isin(('D1', 'B2A3G'))].groupby(['iso3', 'year', 'activity'])['item'].nunique()
    both = both[both == 2].reset_index().groupby(['iso3', 'year']).size().reset_index(name='n')
    both = both[both['n'] > 1]                            # more than the total-economy row
    pick = both.sort_values('year').groupby('iso3').tail(1)[['iso3', 'year']]
    totals = df[df['activity'] == '_T']
    return df.merge(pick, on=['iso3', 'year']).reset_index(drop=True), totals, derived


def oecd_table6_cfc(path_cfc, path_main, base_year):
    """Consumption of fixed capital as a share of B2A3G by activity, in the frame shape labour_shares_from_na reads:
    item D1 holds P51C and item B2A3G holds B2A3G - P51C, so the 'share' it returns is P51C / B2A3G. Latest year at
    or before the base year where both exist, per country."""
    use = ['REF_AREA', 'TRANSACTION', 'ACTIVITY', 'UNIT_MEASURE', 'PRICE_BASE', 'TIME_PERIOD', 'OBS_VALUE']
    c = pd.read_csv(path_cfc, usecols=use)
    c = c[(c['PRICE_BASE'] == 'V') & (c['UNIT_MEASURE'] == 'XDC') & (c['TRANSACTION'] == 'P51C')
          & (c['TIME_PERIOD'] <= base_year) & c['OBS_VALUE'].notna()]
    c = c.rename(columns={'REF_AREA': 'iso3', 'ACTIVITY': 'activity', 'TIME_PERIOD': 'year', 'OBS_VALUE': 'cfc'})
    m = _table6(path_main, base_year)[0]
    m = m[m['item'] == 'B2A3G'].rename(columns={'value': 'b2'})
    j = c[['iso3', 'activity', 'year', 'cfc']].merge(m[['iso3', 'activity', 'year', 'b2']], on=['iso3', 'activity', 'year'])
    n = j.groupby(['iso3', 'year']).size().reset_index(name='n')
    pick = n[n['n'] > 1].sort_values('year').groupby('iso3').tail(1)[['iso3', 'year']]
    j = j.merge(pick, on=['iso3', 'year'])
    out = pd.concat([j.assign(item='D1', value=j['cfc']), j.assign(item='B2A3G', value=j['b2'] - j['cfc'])])
    return out[['iso3', 'activity', 'item', 'value', 'year']].reset_index(drop=True)


def oecd_table6_cfc_fi(path_cfc, path_main, base_year):
    """Consumption of fixed capital as a share of factor income (D1 + B2A3G) by activity, the capital floor of fix
    round A6, in the frame shape labour_shares_from_na reads: item D1 holds P51C and item B2A3G holds
    D1 + B2A3G - P51C, so the 'share' it returns is P51C / (D1 + B2A3G). Latest year at or before the base year where
    P51C, D1 and B2A3G all exist, per country."""
    use = ['REF_AREA', 'TRANSACTION', 'ACTIVITY', 'UNIT_MEASURE', 'PRICE_BASE', 'TIME_PERIOD', 'OBS_VALUE']
    c = pd.read_csv(path_cfc, usecols=use)
    c = c[(c['PRICE_BASE'] == 'V') & (c['UNIT_MEASURE'] == 'XDC') & (c['TRANSACTION'] == 'P51C')
          & (c['TIME_PERIOD'] <= base_year) & c['OBS_VALUE'].notna()]
    c = c.rename(columns={'REF_AREA': 'iso3', 'ACTIVITY': 'activity', 'TIME_PERIOD': 'year', 'OBS_VALUE': 'cfc'})
    m = _table6(path_main, base_year)[0]
    m = m[m['item'].isin(('D1', 'B2A3G'))].pivot_table(index=['iso3', 'activity', 'year'], columns='item', values='value').reset_index()
    m = m.dropna(subset=['D1', 'B2A3G'])
    j = c[['iso3', 'activity', 'year', 'cfc']].merge(m, on=['iso3', 'activity', 'year'])
    n = j.groupby(['iso3', 'year']).size().reset_index(name='n')
    pick = n[n['n'] > 1].sort_values('year').groupby('iso3').tail(1)[['iso3', 'year']]
    j = j.merge(pick, on=['iso3', 'year'])
    fi = j['D1'] + j['B2A3G']
    out = pd.concat([j.assign(item='D1', value=j['cfc']), j.assign(item='B2A3G', value=fi - j['cfc'])])
    return out[['iso3', 'activity', 'item', 'value', 'year']].reset_index(drop=True)


def grs_payroll(path, base_year):
    """OECD Global Revenue Statistics, general government, % of GDP: T_3000 (taxes on payroll and workforce) and
    T_4000 (property), latest year at or before the base year with both, and T_4100 (recurrent taxes on immovable
    property) of that year. Returns {iso3: (t3000, t4000, year, t4100)}
    (fix round A3: the payroll part of S10's payroll_property, booked from D29 as a factor-use tax on labour)."""
    df = pd.read_csv(path, usecols=['REF_AREA', 'SECTOR', 'STANDARD_REVENUE', 'UNIT_MEASURE', 'TIME_PERIOD', 'OBS_VALUE'])
    df = df[(df['SECTOR'] == 'S13') & (df['UNIT_MEASURE'] == 'PT_B1GQ') & df['STANDARD_REVENUE'].isin(('T_3000', 'T_4000', 'T_4100'))
            & (df['TIME_PERIOD'] <= base_year) & df['OBS_VALUE'].notna()]
    p = df.pivot_table(index=['REF_AREA', 'TIME_PERIOD'], columns='STANDARD_REVENUE', values='OBS_VALUE', aggfunc='sum')
    if 'T_4100' not in p.columns:
        p['T_4100'] = np.nan
    p = p.dropna(subset=['T_3000', 'T_4000']).reset_index().sort_values('TIME_PERIOD').groupby('REF_AREA').tail(1)
    # Fable QA F-03: T_4100 (recurrent taxes on immovable property) is the property part inside D29; NaN where not published
    return {r.REF_AREA: (float(r.T_3000), float(r.T_4000), int(r.TIME_PERIOD), float(r.T_4100)) for r in p.itertuples()}


def ilostat_status(path, base_year):
    """ILOSTAT employment by status in employment and ISIC Rev.4 section (EMP_TEMP_SEX_STE_ECO), both sexes:
    employees (STE_AGGREGATE_EES) and self-employed (STE_AGGREGATE_SLF: employers, own-account workers, members of
    producers' cooperatives and contributing family workers). One year per country, the latest at or before the
    base year, and one source (the labour force survey, BA, first; then the most sections). Returns a frame
    iso3, section, ees, slf, year, source (fix round A5, Gollin 2002)."""
    df = pd.read_csv(path, usecols=ILO_COLS + ['classif2'], dtype={'time': int}, low_memory=False)
    df = df[(df['sex'] == 'SEX_T') & df['obs_value'].notna() & (df['time'] <= base_year)
            & df['classif1'].isin(('STE_AGGREGATE_EES', 'STE_AGGREGATE_SLF'))]
    e = df['classif2'].str.extract(r'^ECO_ISIC4_([A-U])$')[0]
    df = df.assign(section=e).dropna(subset=['section'])
    df = df.rename(columns={'ref_area': 'iso3', 'time': 'year'})
    last = df.groupby('iso3')['year'].max().rename('ymax')
    df = df.merge(last, left_on='iso3', right_index=True)
    df = df[df['year'] == df['ymax']]
    g = df.groupby(['iso3', 'source']).agg(n=('section', 'nunique')).reset_index()
    g['ba'] = g['source'].str.startswith('BA').astype(int)
    g = g.sort_values(['iso3', 'ba', 'n', 'source'], ascending=[True, False, False, True]).groupby('iso3').head(1)
    df = df.merge(g[['iso3', 'source']], on=['iso3', 'source'])
    p = df.pivot_table(index=['iso3', 'section', 'year', 'source'], columns='classif1', values='obs_value', aggfunc='sum').reset_index()
    p = p.rename(columns={'STE_AGGREGATE_EES': 'ees', 'STE_AGGREGATE_SLF': 'slf'})
    for c in ('ees', 'slf'):
        if c not in p.columns:
            p[c] = np.nan
    return p[['iso3', 'section', 'ees', 'slf', 'year', 'source']]


def pinksheet_annual(path, series):
    """World Bank Pink Sheet, annual nominal prices: {series name: {year: price}} for the named columns."""
    import openpyxl
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True)['Annual Prices (Nominal)']
    rows = list(ws.iter_rows(values_only=True))
    head = next(r for r in rows if r and r[1] == 'Crude oil, average')
    col = {n: head.index(n) for n in series}
    out = {n: {} for n in series}
    for r in rows:
        if isinstance(r[0], (int, float)) and not isinstance(r[0], bool):
            for n, k in col.items():
                if isinstance(r[k], (int, float)):
                    out[n][int(r[0])] = float(r[k])
    return out


def oecd_table6_all(path, base_year):
    """Every Table 6 row at or before the base year (B2A3G derived as in _table6), for the year-jump screen."""
    return _table6(path, base_year)[0]


# ------------------------------------------------------------------ ISIC activity codes
def _span(a, b):
    return [f'{i:02d}' for i in range(int(a), int(b) + 1)]


def activity_divisions(code, section_divs):
    """ISIC Rev.4 divisions (2-digit strings) covered by a FIGARO or OECD activity code; None if not a plain code.
    Handles 'C', 'C10', 'C10T12', 'C10-12', 'C31_32', 'L68A' (not a division set: None), 'BTE'-style section spans."""
    code = code.strip()
    if code in section_divs:
        return list(section_divs[code])
    m = re.fullmatch(r'([A-U])T([A-U])', code)
    if m:
        secs = [chr(c) for c in range(ord(m.group(1)), ord(m.group(2)) + 1)]
        return [d for s in secs for d in section_divs.get(s, [])]
    m = re.fullmatch(r'[A-U](\d{2})', code)
    if m:
        return [m.group(1)]
    m = re.fullmatch(r'[A-U](\d{2})(?:T|-)(\d{2})', code)
    if m:
        return _span(m.group(1), m.group(2))
    m = re.fullmatch(r'[A-U](\d{2})_(\d{2})', code)
    if m:
        return [m.group(1), m.group(2)] if int(m.group(2)) == int(m.group(1)) + 1 else _span(m.group(1), m.group(2))
    return None


# ------------------------------------------------------------------ ILOSTAT
ILO_COLS = ['ref_area', 'source', 'sex', 'classif1', 'time', 'obs_value']


def ilostat(path, prefix, usd=False):
    """ILOSTAT bulk file, both sexes, one classification family: iso3, source, code, year, value.
    prefix 'OCU_ISCO' keeps ISCO-08 and ISCO-88 major groups 1-9 (classification recorded);
    prefix 'ECO_ISIC4' keeps ISIC Rev.4 sections A-U. usd=True keeps the USD rows of an earnings file."""
    cols = ILO_COLS + (['classif2'] if usd else [])
    df = pd.read_csv(path, usecols=cols, dtype={'time': int})
    df = df[(df['sex'] == 'SEX_T') & df['obs_value'].notna()]
    if usd:
        df = df[df['classif2'] == 'CUR_TYPE_USD']
    if prefix == 'OCU_ISCO':
        m = df['classif1'].str.extract(r'^OCU_(ISCO08|ISCO88)_([1-9])$')
        df = df.assign(cls=m[0], code=m[1]).dropna(subset=['code'])
    else:
        m = df['classif1'].str.extract(r'^ECO_ISIC4_([A-U])$')
        df = df.assign(cls='ISIC4', code=m[0]).dropna(subset=['code'])
    return df.rename(columns={'ref_area': 'iso3', 'time': 'year', 'obs_value': 'value'})[
        ['iso3', 'source', 'cls', 'code', 'year', 'value']].reset_index(drop=True)


def ilostat_cross(path):
    """ILOSTAT employment by occupation x economic activity (EMP_TEMP_SEX_OCU_EC2), both sexes:
    iso3, source, cls, code (ISCO major group), section (ISIC Rev.4 section from the 2-digit code), year, value."""
    df = pd.read_csv(path, usecols=ILO_COLS + ['classif2'], dtype={'time': int})
    df = df[(df['sex'] == 'SEX_T') & df['obs_value'].notna()]
    m = df['classif1'].str.extract(r'^OCU_(ISCO08|ISCO88)_([1-9])$')
    e = df['classif2'].str.extract(r'^EC2_ISIC4_([A-U])\d{2}$')
    df = df.assign(cls=m[0], code=m[1], section=e[0]).dropna(subset=['code', 'section'])
    df = df.groupby(['ref_area', 'source', 'cls', 'code', 'section', 'time'], as_index=False)['obs_value'].sum()
    return df.rename(columns={'ref_area': 'iso3', 'time': 'year', 'obs_value': 'value'})


# ------------------------------------------------------------------ World Bank API files
def wb_series(path):
    """A World Bank API v2 JSON file: iso3, year, value (non-null only)."""
    d = json.load(open(path))
    rows = [(x['countryiso3code'], int(x['date']), float(x['value'])) for x in d[1]
            if x['value'] is not None and x['countryiso3code']]
    return pd.DataFrame(rows, columns=['iso3', 'year', 'value'])


def wb_meta(path):
    d = json.load(open(path))
    return d[0].get('lastupdated', '')


# ------------------------------------------------------------------ BEA supply-use tables (fix worker wD)
BEA_VA_ROWS = ('V001', 'T00OTOP', 'T00OSUB', 'V003', 'VABAS')


def bea_sut_va(path, year):
    """BEA summary Use table, supply-use framework (basic prices), value-added rows for one year: industry_code,
    industry, V001 (compensation), T00OTOP (other taxes on production), T00OSUB (less: other subsidies on production),
    V003 (gross operating surplus), VABAS (value added at basic prices), million USD. A blank tax cell (the government
    industries) is 0. Raises SystemExit if the year or a column is missing."""
    df = pd.read_csv(path)
    miss = [c for c in ('year', 'industry_code', 'industry') + BEA_VA_ROWS if c not in df.columns]
    if miss:
        raise SystemExit(f'{path}: columns {miss} missing')
    df = df[df['year'] == int(year)].copy()
    if df.empty:
        raise SystemExit(f'{path}: no rows for {year}')
    for c in BEA_VA_ROWS:
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0)
    return df.reset_index(drop=True)


# ------------------------------------------------------------------ OECD Table 14 sector accounts (fix worker wD)
def oecd_table14_d29_net(path, year):
    """OECD Table 14, national currency, one year: {iso3: dict(d29, d39, d3, sub, sub_item, net)}. d29 is other taxes
    on production paid by the total economy (S1, uses), else received by general government (S13, resources); the
    subsidy is D39 paid by general government (S13, uses) where reported, else all subsidies D3 (sub_item says which);
    net = d29 - sub. NaN where an item is not reported."""
    df = pd.read_csv(path, low_memory=False)
    df = df[(df['UNIT_MEASURE'] == 'XDC') & (df['TIME_PERIOD'] == int(year))]
    out = {}
    for c, g in df.groupby('REF_AREA'):
        def v(sec, ae, tr):
            x = g[(g['SECTOR'] == sec) & (g['ACCOUNTING_ENTRY'] == ae) & (g['TRANSACTION'] == tr)]['OBS_VALUE']
            return float(x.iloc[0]) if len(x) else np.nan
        d29 = v('S1', 'D', 'D29')
        if np.isnan(d29):
            d29 = v('S13', 'C', 'D29')
        d39, d3 = v('S13', 'D', 'D39'), v('S13', 'D', 'D3')
        sub, item = (d39, 'D39') if not np.isnan(d39) else (d3, 'D3')
        out[c] = dict(d29=d29, d39=d39, d3=d3, sub=sub, sub_item=item, net=d29 - sub)
    return out
