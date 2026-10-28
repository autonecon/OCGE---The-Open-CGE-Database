"""National occupation x industry employment tables (GTAP 12 ch.14B, rule F16a; Fable QA B-02).

ch.14B ranks a national cross table above the ILOSTAT margins and far above a regional average. The readers here
return the source's own codes; config/s12/national_labour_map.csv maps them to ISCO-08 major groups and ISIC Rev.4
sections, and to_matrix() turns them into the (9 x sections) employment matrix the ch.14B calibration takes.

Each reader returns dict(kind, year, cross) for a cross table (frame occ, ind, value) or dict(kind, year, occ, ind)
for margins only (two Series indexed by the source code). Counts are persons or thousands: only shares are used.
None of the readers fills a gap; a missing cell is a zero ('-' and unreleased cells in the sources).
"""
import csv
import io
import re
import zipfile

import numpy as np
import pandas as pd

from .method import SECTIONS

OCC9 = [str(i) for i in range(1, 10)]


def _num(v):
    try:
        x = float(str(v).replace(',', '').strip())
    except (TypeError, ValueError):
        return 0.0
    return x if np.isfinite(x) else 0.0


def _norm(s):
    return re.sub(r'\s+', '', str(s))


# ------------------------------------------------------------------ Taiwan: DGBAS Manpower Survey 2022, Table 49
def dgbas_table49(path, base_year):
    """Employed persons by industry section x occupation group, 2022 annual average, thousand persons (first block:
    both sexes). Rows are matched by their English label (column 1), columns by the header English labels (row 7)."""
    if base_year < 2022:
        return None
    x = pd.read_excel(path, header=None)
    head = {c: str(x.iloc[7, c]).strip() for c in range(2, x.shape[1]) if pd.notna(x.iloc[7, c])}
    rows = []
    for r in range(9, x.shape[0]):
        lab = str(x.iloc[r, 1])
        if 'TABLE' in lab.upper() or '續' in lab:
            break                                        # the male and female blocks follow
        eng = ' '.join(re.findall(r'[A-Za-z&;,]+', lab))
        if not eng:
            continue
        for c, h in head.items():
            if h == 'Total':
                continue
            rows.append(dict(occ=' '.join(h.split()), ind=' '.join(eng.split()), value=_num(x.iloc[r, c])))
    return dict(kind='cross', year=2022, cross=pd.DataFrame(rows))


# ------------------------------------------------------------------ Hong Kong: C&SD table 210-06308
def censtatd_210_06308(path, base_year):
    """Employed persons by industry group x occupation of main employment, annual, thousand persons; the latest year at
    or before the base year. Leaf industry groups only (the 4 and 6 subtotals are split into 4.1/4.2 and 6.1/6.2)."""
    import json
    d = pd.DataFrame(json.load(open(path))['dataSet'])
    d = d[(d['freq'] == 'Y') & (d['sv'] == 'EM')]
    d['year'] = d['period'].astype(int)
    d = d[d['year'] <= base_year]
    if d.empty:
        return None
    y = int(d['year'].max())
    d = d[(d['year'] == y) & (d['MIND'].astype(str) != '') & (d['MOCC'].astype(str) != '')]
    d = d[~d['MIND'].astype(str).isin(('4', '6'))]
    out = pd.DataFrame(dict(occ=d['MOCC'].astype(str), ind=d['MIND'].astype(str), value=[_num(v) for v in d['figure']]))
    return dict(kind='cross', year=y, cross=out)


# ------------------------------------------------------------------ Korea: KOSIS DT_1ES3B33S (LALFS)
def kosis_dt_1es3b33s(path, base_year):
    """Employed persons by KSIC section x KSCO major group, both sexes, mean of the two half-years of the base year
    (else the latest year at or before it with both halves), thousand persons."""
    d = pd.read_csv(path)
    d = d[(d['성별'] == '계') & (d['항목'].astype(str).str.startswith('취업자'))]
    years = sorted({int(c[:4]) for c in d.columns if re.match(r'^\d{4}\.[12]/2$', str(c))})
    ys = [y for y in years if y <= base_year and f'{y}.1/2' in d.columns and f'{y}.2/2' in d.columns]
    if not ys:
        return None
    y = ys[-1]
    d = d[(d['산업별'] != '계') & (d['직업별'] != '계')]
    val = (d[f'{y}.1/2'].map(_num) + d[f'{y}.2/2'].map(_num)) / 2.0
    out = pd.DataFrame(dict(occ=d['직업별'].str.extract(r'^(\d)\.')[0], ind=d['산업별'].str.extract(r'^([A-U])\.')[0], value=val))
    return dict(kind='cross', year=y, cross=out.dropna(subset=['occ', 'ind']))


# ------------------------------------------------------------------ Qatar: PSA LFS (data.gov.qa)
def qatar_lfs(path, base_year):
    """Economically active population 15+ by economic activity (ISIC Rev.4 section names) x occupation (ISCO-88 major
    group names), persons; the base year, else the latest year at or before it."""
    d = pd.read_csv(path, sep=None, engine='python', encoding='utf-8-sig')
    d = d[d['year'] <= base_year]
    if d.empty:
        return None
    y = int(d['year'].max())
    d = d[d['year'] == y]
    out = pd.DataFrame(dict(occ=d['occupation'].str.strip(), ind=d['economic_activity'].str.strip(), value=d['number'].map(_num)))
    return dict(kind='cross', year=y, cross=out)


# ------------------------------------------------------------------ Saudi Arabia: GASTAT LMS Q4 2022
def gastat_lms(path, base_year):
    """Social-insurance participants by main occupation group (table 3-5) and by main economic activity (table 3-8),
    all nationalities and both sexes (the last column), Q4 2022. Margins only."""
    if base_year < 2022:
        return None
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)

    def table(name):
        s = {}
        for row in wb[name].iter_rows(values_only=True):
            vals = [v for v in row if v is not None]
            if len(vals) >= 4 and isinstance(vals[0], str) and all(isinstance(v, (int, float)) for v in vals[1:]):
                s[' '.join(vals[0].split())] = float(vals[-1])
        return pd.Series(s)
    return dict(kind='margins', year=2022, occ=table('3-5'), ind=table('3-8'))


# ------------------------------------------------------------------ China: 2020 census long form, tables 4-4 and 4-6
def _nbs_columns(x, name_row, sub_row):
    """(column, 'group|subgroup') for the header rows of an NBS long-form table; the group name is carried right."""
    grp, out = '', []
    for c in range(1, x.shape[1]):
        g = x.iloc[name_row, c]
        if pd.notna(g) and _norm(g):
            grp = _norm(g)
        s = x.iloc[sub_row, c]
        if pd.notna(s) and _norm(s):
            out.append((c, f'{grp}|{_norm(s)}'))
    return out


def nbs_census_2020(path_ind, path_occ, base_year):
    """Employed persons by industry division (B0404) and occupation middle group (B0406), China total, both sexes,
    2020 census long-form sample counts. Margins only (the census has no cross table)."""
    if base_year < 2020:
        return None
    res = {}
    for key, path in (('ind', path_ind), ('occ', path_occ)):
        x = pd.read_excel(path, header=None)
        r0 = next(r for r in range(x.shape[0]) if _norm(x.iloc[r, 0]) == '全国')
        cols = _nbs_columns(x, 3, 4)
        res[key] = pd.Series({k: _num(x.iloc[r0, c]) for c, k in cols})
    return dict(kind='margins', year=2020, occ=res['occ'], ind=res['ind'])


# ------------------------------------------------------------------ Canada: 2021 Census 98-10-0456-01 and LFS 14-10-0416-01
NOC_BROAD_MGMT = {'10': '1', '20': '2', '30': '3', '40': '4', '50': '5', '60': '6', '70': '7', '80': '8', '90': '9'}


def _noc_codes(label):
    """'Professional occupations in finance and business [11]' -> ['11']; '[82-83]' -> ['82', '83'];
    '[10, 20, 30, 40, 50]' -> those codes."""
    m = re.search(r'\[([^\]]+)\]$', label.strip())
    if not m:
        return []
    out = []
    for part in m.group(1).split(','):
        part = part.strip()
        if '-' in part:
            a, b = part.split('-')
            out += [str(k) for k in range(int(a), int(b) + 1)]
        else:
            out.append(part)
    return out


def statcan_census_lfs(path_census, path_lfs, base_year):
    """Canada occupation x industry, NOC 2021 two-digit major groups x NAICS 2017 sectors.
    The 2021 Census (98-10-0456-01, Canada, total gender, total place of work status, counts) gives broad category
    (one digit) x sector; the LFS (14-10-0416-01, Canada, employment, total gender) gives the two-digit major groups
    in the base year. Within a broad category the census column is shared out by the LFS major-group mix of that
    category (the two-digit mix is taken the same in every sector, our assumption). The LFS publishes the middle
    managers of categories 1-5 and 7-9 as two bundles; a bundle is shared out over its categories by the census
    category total (scaled to the LFS total) less the category's other LFS groups, floored at zero."""
    if base_year < 2021:
        return None
    zc = zipfile.ZipFile(path_census)
    cen = {}
    with zc.open('98100456.csv') as f:
        r = csv.reader(io.TextIOWrapper(f, encoding='utf-8-sig'))
        h = next(r)
        i_geo, i_occ, i_g, i_st, i_ind = 1, 3, 4, 5, 6
        i_v = h.index(next(c for c in h if c.startswith('Place of work status (5):Total')))
        for row in r:
            if row[i_geo] != 'Canada':
                break
            if row[i_g] != 'Total - Gender' or row[i_st] != 'Count':
                continue
            o, j = row[i_occ], row[i_ind]
            if o.startswith('Total') or j.startswith('Total'):
                continue
            cen[(o.split(' ')[0], j.split(' ')[0])] = _num(row[i_v])
    zl = zipfile.ZipFile(path_lfs)
    lfs = pd.read_csv(zl.open('14100416.csv'), encoding='utf-8-sig', usecols=['REF_DATE', 'GEO', 'Labour force characteristics',
                                                                             'National Occupational Classification (NOC)', 'Gender', 'VALUE'])
    lfs = lfs[(lfs['GEO'] == 'Canada') & (lfs['Labour force characteristics'] == 'Employment') & (lfs['Gender'] == 'Total - Gender')
              & (lfs['REF_DATE'] <= base_year)]
    y = int(lfs['REF_DATE'].max())
    lfs = lfs[lfs['REF_DATE'] == y]
    # the two-digit groups and bundles: a label whose codes are all two-digit (or '0') and not a broad-category total
    groups = {}
    for lab, v in zip(lfs['National Occupational Classification (NOC)'], lfs['VALUE']):
        cs = _noc_codes(lab)
        if not cs or lab.startswith(('Total', 'Management occupations')) or ', except management' in lab:
            continue
        if any(len(c) != 2 and c != '0' for c in cs):
            continue
        groups['+'.join(cs)] = float(v)
    cats = sorted({k for k, _ in cen})
    sectors = sorted({j for _, j in cen})
    cat_tot = {k: sum(cen[(k, j)] for j in sectors if (k, j) in cen) for k in cats}
    scale = sum(groups.values()) / sum(cat_tot.values())
    mix = {k: {} for k in cats}
    bundles = {}
    for g, v in groups.items():
        cs = g.split('+')
        ks = sorted({'0' if c == '0' else c[0] for c in cs})
        if len(ks) == 1:
            mix[ks[0]][g] = mix[ks[0]].get(g, 0.0) + v
        else:
            bundles[g] = (ks, v)
    for g, (ks, v) in bundles.items():
        room = {k: max(cat_tot[k] * scale - sum(mix[k].values()), 0.0) for k in ks}
        t = sum(room.values())
        for k in ks:
            mix[k][g] = v * (room[k] / t if t > 0 else 1.0 / len(ks))
    rows = []
    for k in cats:
        tk = sum(mix[k].values())
        for g, v in mix[k].items():
            for j in sectors:
                rows.append(dict(occ=g, ind=j, value=cen.get((k, j), 0.0) * (v / tk if tk > 0 else 0.0)))
    return dict(kind='cross', year=y, cross=pd.DataFrame(rows), note=f'census 2021 broad category x sector, LFS {y} major-group mix')


READERS = {
    'dgbas_table49': dgbas_table49,
    'censtatd_210_06308': censtatd_210_06308,
    'kosis_dt_1es3b33s': kosis_dt_1es3b33s,
    'qatar_lfs': qatar_lfs,
    'gastat_lms': gastat_lms,
    'nbs_census_2020': nbs_census_2020,
    'statcan_census_lfs': statcan_census_lfs,
}


# ------------------------------------------------------------------ concordance to ISCO x ISIC section
def to_matrix(tab, occ_map, ind_map, occ_split):
    """tab: a reader result. occ_map: {source occ code: [ISCO major groups]} ([] = left out: armed forces, not
    classified); ind_map: {source industry code: [ISIC sections]} ([] = left out). A '*' row with an empty target
    leaves out every code not listed (the NBS tables carry both subtotals and their parts). occ_split: (9,) employment
    profile used to share a source group over several ISCO groups (the country's own ILOSTAT occupation employment,
    else its geographic region's). A source industry over several sections gives each section the same occupation mix
    with the column shared equally. Returns (N (9 x sections) or None, N_occ (9,), N_ind (sections,), unmapped codes).
    For margins N is None (eq.14.1 builds it)."""
    unm = set()
    prof = np.asarray(occ_split, float)

    def occ_vec(code, v):
        isc = occ_map.get(code, occ_map.get('*'))
        if isc is None:
            unm.add(f'occ {code}')
            return np.zeros(9)
        out = np.zeros(9)
        if not isc:
            return out
        idx = [OCC9.index(i) for i in isc]
        w = prof[idx]
        w = w / w.sum() if w.sum() > 0 else np.full(len(idx), 1.0 / len(idx))
        out[idx] = v * w
        return out

    def ind_vec(code, v):
        secs = ind_map.get(code, ind_map.get('*'))
        if secs is None:
            unm.add(f'ind {code}')
            return np.zeros(len(SECTIONS))
        out = np.zeros(len(SECTIONS))
        for s in secs:
            out[SECTIONS.index(s)] += v / len(secs)
        return out
    if tab['kind'] == 'cross':
        N = np.zeros((9, len(SECTIONS)))
        for o, i, v in zip(tab['cross']['occ'], tab['cross']['ind'], tab['cross']['value']):
            if v:
                N += np.outer(occ_vec(o, 1.0), ind_vec(i, 1.0)) * v
        return N, N.sum(axis=1), N.sum(axis=0), sorted(unm)
    n_occ = sum((occ_vec(o, v) for o, v in tab['occ'].items()), np.zeros(9))
    n_ind = sum((ind_vec(i, v) for i, v in tab['ind'].items()), np.zeros(len(SECTIONS)))
    return None, n_occ, n_ind, sorted(unm)
