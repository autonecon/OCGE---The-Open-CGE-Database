"""Macro structure of the data base against WDI 2022, by region (Fable QA E-03 and E-04).

The saving checks (S14-Hsave, S15-Hsave, S16-Hsave, S16-Hsixm) recompute SAVE = Y - C - G from the writer's own
expression, so they cannot fail on wrong data. GTAP 12 ch.3 and ch.7 build the macro side from national accounts; the
comparison here is with an independent figure, the WDI national accounts of 2022 (data/wdi/wdi_accounts.csv, the S02
source, aggregated over a composite's members):

    absorption   (C + G + I) / GDP              vs  NE.CON.PRVT.ZS + NE.CON.GOVT.ZS + NE.GDI.TOTL.ZS
    trade        (X - M) / GDP                  vs  (NE.EXP.GNFS.CD - NE.IMP.GNFS.CD) / NY.GDP.MKTP.CD
    saving       (SAVE + VDEP) / GDP            vs  NY.GNS.ICTR.ZS (gross national saving over GNI; GTAP has no
                                                    primary income or transfers, GTAP 12 ch.7 eq. 7.2, so the gap
                                                    also holds the net income from abroad)
    net investment  VDEP / I                    below 1 (GTAP's net investment I - VDEP is positive)

A large economy (at least LARGE_SHARE of world GDP) must have a trade balance within BAND points of GDP of WDI, a gross
saving within SAVE_BAND points, and VDEP below I; the others are reported. Absorption is reported only: with GDP held at
S02 (WDI) GDP its gap is the trade balance gap with the sign reversed. A region listed in
config/macro_external_exceptions.csv (region, measure, finding, basis, decided_by, decided_at) is reported as an open
finding instead of failing; S16 lists every exception for review (E-05).
"""
import csv
import os

import numpy as np
import pandas as pd

LARGE_SHARE = 0.01          # a region with at least 1% of world GDP is a large economy (about the 20 largest)
BAND = 0.05                 # absorption and trade balance: within 5 points of GDP of WDI
SAVE_BAND = 0.08            # gross saving: within 8 points (net income from abroad is not in GTAP; A-04)
COVER_MIN = 0.9             # a composite needs WDI values for members with at least 90% of the members' GDP
MEASURES = ('absorption', 'trade', 'saving', 'net_investment')
HARD = ('trade', 'saving', 'net_investment')
EXCEPTION_COLUMNS = ('region', 'measure', 'finding', 'basis', 'decided_by', 'decided_at')
WDI_SERIES = ('NY.GDP.MKTP.CD', 'NE.CON.PRVT.ZS', 'NE.CON.GOVT.ZS', 'NE.GDI.TOTL.ZS', 'NE.EXP.GNFS.CD', 'NE.IMP.GNFS.CD',
              'NY.GNS.ICTR.ZS')


def wdi_by_region(wdi, regions, year=2022):
    """WDI shares of GDP by model region. wdi: wdi_accounts.csv (countrycode, year, series columns); regions: S01
    regions.csv (region, members as space- or semicolon-separated ISO3). Amounts are summed over a composite's members
    with a value; a share needs members covering COVER_MIN of the members' GDP. Returns a frame indexed by region."""
    w = wdi[wdi['year'] == year].set_index('countrycode')
    gdp = w['NY.GDP.MKTP.CD']
    amt = pd.DataFrame({
        'gdp': gdp,
        'absorption': gdp * (w['NE.CON.PRVT.ZS'] + w['NE.CON.GOVT.ZS'] + w['NE.GDI.TOTL.ZS']) / 100.0,
        'trade': w['NE.EXP.GNFS.CD'] - w['NE.IMP.GNFS.CD'],
        'saving': gdp * w['NY.GNS.ICTR.ZS'] / 100.0,
    })
    rows = []
    for x in regions.itertuples():
        mem = [m for m in str(x.members).replace(';', ' ').replace(',', ' ').split() if m]
        mem = mem or [x.region]
        a = amt.reindex(mem)
        tot = a['gdp'].sum()
        out = dict(region=x.region, wdi_gdp_musd=tot / 1e6 if tot > 0 else np.nan)
        for m in ('absorption', 'trade', 'saving'):
            ok = a[m].notna() & a['gdp'].notna()
            cover = a.loc[ok, 'gdp'].sum() / tot if tot > 0 else 0.0
            out[f'wdi_{m}'] = a.loc[ok, m].sum() / a.loc[ok, 'gdp'].sum() if cover >= COVER_MIN and a.loc[ok, 'gdp'].sum() > 0 else np.nan
        rows.append(out)
    return pd.DataFrame(rows).set_index('region')


def read_exceptions(path):
    """{(region, measure): row}; stop on a missing column, an unknown measure or a blank finding or attribution."""
    if not os.path.exists(path):
        raise SystemExit(f'{path} is missing')
    with open(path, newline='') as fh:
        rd = csv.DictReader(fh)
        if tuple(rd.fieldnames or ()) != EXCEPTION_COLUMNS:
            raise SystemExit(f'{path}: columns {rd.fieldnames} are not {EXCEPTION_COLUMNS}')
        rows = list(rd)
    out = {}
    for r in rows:
        if r['measure'] not in HARD or not all(r[c].strip() for c in ('finding', 'basis', 'decided_by', 'decided_at')):
            raise SystemExit(f'{path}: row {r} needs a known measure, a finding, a basis and an attribution')
        out[(r['region'], r['measure'])] = r
    return out


def compare(acc, wdi_r, exceptions=None, large_share=LARGE_SHARE, band=BAND, save_band=SAVE_BAND):
    """acc: regional accounts indexed by region with GDP (GDP_expenditure or GDP), C, G, I, X, M, SAVE, VDEP (USD m).
    Returns (table, failures, exceptions_hit): the table has the data base and WDI shares, gaps in points of GDP,
    large and the per-measure status (ok, fail, exception, report, no_wdi); failures lists 'region measure gap' for
    the large economies outside their band and not excepted."""
    exceptions = exceptions or {}
    a = acc.copy()
    gdp = a['GDP_expenditure'] if 'GDP_expenditure' in a else a['GDP']
    t = pd.DataFrame(index=a.index)
    t['gdp_musd'] = gdp
    t['large'] = gdp / gdp.sum() >= large_share
    t['absorption'] = (a['C'] + a['G'] + a['I']) / gdp
    t['trade'] = (a['X'] - a['M']) / gdp
    t['saving'] = (a['SAVE'] + a['VDEP']) / gdp
    t['net_investment'] = a['VDEP'] / a['I'].where(a['I'] > 0)
    w = wdi_r.reindex(t.index)
    fails, hit = [], []
    for m, bd in (('absorption', band), ('trade', band), ('saving', save_band), ('net_investment', None)):
        if m != 'net_investment':
            t[f'wdi_{m}'] = w[f'wdi_{m}']
            t[f'gap_{m}'] = t[m] - t[f'wdi_{m}']
            bad = t[f'gap_{m}'].abs() > bd
            nowdi = t[f'wdi_{m}'].isna()
        else:
            bad = ~(t[m] < 1.0)
            nowdi = pd.Series(False, index=t.index)
        st = pd.Series('ok', index=t.index)
        st[bad & ~nowdi] = 'report'
        st[nowdi] = 'no_wdi'
        for r in (t.index[bad & ~nowdi & t['large']] if m in HARD else []):
            gap = t.loc[r, f'gap_{m}'] if m != 'net_investment' else t.loc[r, m]
            if (r, m) in exceptions:
                st[r] = 'exception'
                hit.append(f'{r} {m} {gap:+.3f} ({exceptions[(r, m)]["finding"]})')
            else:
                st[r] = 'fail'
                fails.append(f'{r} {m} {gap:+.3f}')
        t[f'status_{m}'] = st
    stale = [f'{r} {m}' for (r, m) in exceptions if r in t.index and t.loc[r, f'status_{m}'] != 'exception']
    if stale:
        hit.append('stale exceptions (now within the band or not large; remove them): ' + ', '.join(stale))
    return t, fails, hit


def summary(t, fails, hit, top=12):
    """One detail line for a check: failures, exceptions and the largest reported gaps of the other regions."""
    parts = []
    if fails:
        parts.append('FAIL: ' + '; '.join(fails))
    if hit:
        parts.append(f'open findings (config/macro_external_exceptions.csv): ' + '; '.join(hit))
    for m in ('trade', 'saving', 'absorption'):
        r = t[t[f'status_{m}'] == 'report']
        if len(r):
            g = r[f'gap_{m}'].abs().sort_values(ascending=False).head(top)
            parts.append(f'{m} outside the band in {len(r)} {"other " if m in HARD else ""}regions ({r["gdp_musd"].sum() / t["gdp_musd"].sum():.1%} of world GDP): '
                         + ', '.join(f'{k} {t.loc[k, f"gap_{m}"]:+.3f}' for k in g.index))
    ni = t[t['status_net_investment'] == 'report']
    if len(ni):
        parts.append(f'VDEP >= I in {len(ni)} other regions: ' + ', '.join(f'{k} {t.loc[k, "net_investment"]:.2f}' for k in ni.index))
    nw = t[(t[[f'status_{m}' for m in ('absorption', 'trade', 'saving')]] == 'no_wdi').any(axis=1)]
    if len(nw):
        parts.append(f'no WDI value for {len(nw)} regions: ' + ' '.join(nw.index))
    return '. '.join(parts)
