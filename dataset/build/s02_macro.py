"""S02 macroeconomic data (GTAP 12 ch.7; PLAN v2 (h) step 1 + capital).
Per country (GTAP 251-country universe as mapped at S01): GDP, C, G, GFCF (current USD million), POP,
capital stock VKB and depreciation VDEP = 4% VKB; then summed to the 167 regions.
Base year Y = GTAP_BASE_YEAR (default 2022; a 2017 validation build uses the same code).
Sources in order (rule F1, GTAP 12 ch.7 pp.1-2): WDI Y -> UNSD AMA Y (as shares of AMA GDP, for parity)
-> DGBAS + CBC for TWN -> geographic-region average shares x GDP; GDP missing: geographic-region average
per-capita GDP x POP; no data at all: zero + flag (GTAP ch.7 p.2).
Capital (GTAP 12 ch.7 s7.3; fix round 2, David 2026-10-20 22:02; replaces the PWT method of E30): IMF ICSD K/GDP in its
latest year, rolled forward to Y by perpetual inventory (WDI LCU GFCF, revalued by the implicit GFCF deflator, else the GDP deflator,
4%; re-based to the ICSD ratio beyond a 25% band; config/s02/s02_choices.csv) x GDP used -> perpetual inventory over
the country's own WDI real GFCF (>= 30 years) -> GDP x geo-average K/GDP of ICSD countries. PWT K/Y is report-only (S02-P6).
SAVE needs reconciled X-M and is built at assembly (S14); here only the pre-solve parts computable now.
No scaling to trade here (GTAP ch.7 p.2: done after trade reconciliation)."""
import os, sys, json, collections
import pandas as pd, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/lib')
from stagekit import Stage, DATA, STAGES, BASE_YEAR
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s02_capital import pim as PIM
from s02_capital import gdp_weo as GW
from s02_capital import gdp_official as GO
Y = BASE_YEAR

CFG = os.path.dirname(os.path.abspath(__file__)) + '/config/s02'
S = Stage('S02', 'macro')
I = S.inp
S01 = S.upstream(STAGES + '/S01_sets_registry')   # G0 (STAMP + output SHAs vs S01 SHA256SUMS) is checked in S.finish() (review FR-M2)
cmap = pd.read_csv(I(S01 + '/output/country_region_map.csv', 'S01 country -> region'))
regions = pd.read_csv(I(S01 + '/output/regions.csv', 'S01 regions'))
geo = pd.read_csv(I(S01 + '/output/gtap_geo_regions_table910.csv', 'S01 GTAP Table 9.10'))
par = pd.read_csv(I(CFG + '/concept_parity.csv', 'config: concept parity per source'))
cont = pd.read_csv(I(CFG + '/contained_in.csv', 'config: codes contained in another country'))
tfold = pd.read_csv(I(os.path.dirname(CFG) + '/s01/territory_folds.csv', 'config: inherited territory folds (independent membership)'))
NONC = set(pd.read_csv(I(os.path.dirname(CFG) + '/s01/non_country_codes.csv', 'config: non-country aggregates')).code)
wdi = pd.read_csv(I(DATA + '/wdi/wdi_2017_2022_extract.csv', 'WDI 2017-2022 extract'))
wacc = pd.read_csv(I(DATA + '/wdi/wdi_accounts.csv', 'WDI accounts (X, M, BoP memo)'))
ama = pd.read_csv(I(DATA + f'/unsd_ama/expenditure_{Y}.csv', f'UNSD AMA expenditure {Y}'))
amag = pd.read_csv(I(DATA + '/unsd_ama/gva_gdp_current_usd.csv', 'UNSD AMA GDP and per-capita GDP'))
dg = pd.read_csv(I(DATA + f'/dgbas_twn/dgbas_gdp_expenditure_{Y}_extract.csv', f'DGBAS TWN {Y} expenditure'))
# review S02-L4: check the CBC rate against DGBAS's own rate for the base year when that file is on disk, else the prior year
_rf = [f'{DATA}/dgbas_twn/dgbas_twn_gni_{y}.csv' for y in (Y, Y - 1) if os.path.exists(f'{DATA}/dgbas_twn/dgbas_twn_gni_{y}.csv')]
if not _rf: raise SystemExit(f'no DGBAS rate file for {Y} or {Y - 1}')
dgr = pd.read_csv(I(_rf[0], 'DGBAS exchange rate (parity check)'))
PY = int(dgr.year.max())
cbc = json.load(open(I(DATA + '/cbc_twn_fx/cbc_BP01Y01_annual_fx.json', 'CBC NT$/US$ annual')))
pwt = pd.read_csv(I(DATA + '/pwt/pwt110_ky_labsh.csv', 'PWT 11.0 cn, pl_n, pop'))
icsd = pd.read_excel(I(DATA + '/imf_icsd/IMFInvestmentandCapitalStockDataset2021.xlsx', 'IMF ICSD 2021'), sheet_name='Dataset')

# ---------------------------------------------------------------- universe
C = cmap[cmap.region.notna() & ~cmap.status.str.startswith('alias') & ~cmap.status.str.startswith('non-country')].copy()
GEO9 = dict(zip(geo.iso3, geo.gtap_geo))
C['geo'] = [g if isinstance(g, str) else GEO9.get({'KSV': 'XKX', 'PAL': 'PSE'}.get(c, c)) for c, g in zip(C.code, C.gtap_geo)]
SRC = {'PAL': 'PSE', 'KSV': 'XKX'}           # region code -> code used by WDI/AMA/PWT
C['sc'] = C.code.map(lambda x: SRC.get(x, x))
C = C.set_index('code')
S.log(f'countries in universe: {len(C)} mapped to {C.region.nunique()} regions')
S.check('S02-U1', 'Universe covers all 167 regions', 'hard', C.region.nunique(), 167, C.region.nunique() == 167)
CONT = dict(zip(cont.code, cont.parent))

w22 = wdi[wdi.year == Y].pivot_table(index='iso3', columns='series', values='value')
WS = {'GDP': 'NY.GDP.MKTP.CD', 'C': 'NE.CON.PRVT.CD', 'G': 'NE.CON.GOVT.CD', 'I': 'NE.GDI.FTOT.CD', 'POP': 'SP.POP.TOTL'}
A = ama.set_index('iso3'); AS = {'GDP': 'gdp_million_usd', 'C': 'hh_million_usd', 'G': 'gov_million_usd', 'I': 'gfcf_million_usd'}
ag = amag[amag.year == Y].set_index('iso3')
def wv(c, k):
    v = w22.loc[c, WS[k]] if c in w22.index and WS[k] in w22.columns else np.nan
    return v / 1e6 if k != 'POP' else v
VAR = ['GDP', 'C', 'G', 'I', 'POP']
val = {k: {} for k in VAR}; src = {k: {} for k in VAR}

# TWN
ntd = {r[0]: float(r[1]) for r in cbc['data']['dataSets']}
fx22, fx21 = ntd[str(Y)], ntd[str(PY)]   # fx22 = base-year rate used; fx21 = rate of the DGBAS check year
dg21 = float(dgr.loc[dgr.year == PY, 'exchange_rate_ntd_per_usd'].iloc[0])
S.check('S02-P1', f'CBC NT$/US$ is the rate DGBAS uses ({PY}: CBC vs DGBAS file' + ('' if PY == Y else f'; DGBAS {Y} rate not on disk') + ')', 'hard', f'{fx21} vs {dg21}', '|diff| <= 0.05%', abs(fx21 / dg21 - 1) <= 5e-4, 'C14 concept parity')
dgv = {}
LAB = {'1.民間消費': 'C', '2.政府消費': 'G', '3.資本形成:3.1--3.2合計': 'CF', '3.1固定資本形成': 'I', '3.2存貨變動': 'INV',
       '4.商品及服務輸出:4.1--4.2合計': 'X', '5.商品及服務輸入:5.1--5.2合計': 'M', '8.GDP': 'GDPpub'}
for _, r in dg[(dg.TIME_PERIOD == Y) & dg.Item.str.startswith('當期價格(新臺幣百萬元)、')].iterrows():
    lab = r.Item.split('、', 1)[1]
    if lab in LAB: dgv[LAB[lab]] = float(r.Item_VALUE)
dgv['GDP'] = dgv['C'] + dgv['G'] + dgv['CF'] + dgv['X'] - dgv['M']
S.log(f'TWN DGBAS {Y} GDP (C+G+CF+X-M) NT$ m {dgv["GDP"]:,.0f}; CBC {Y} rate {fx22}')
S.check('S02-P2', 'TWN DGBAS: C+G+capital formation+X-M = published GDP (current NT$ m)', 'hard', dgv['GDP'], dgv['GDPpub'], abs(dgv['GDP'] - dgv['GDPpub']) <= 1, 'identity')
dgv['GDP'] = dgv['GDPpub']

# ---------------------------------------------------------------- observed values
for c, r in C.iterrows():
    sc = r.sc
    if c in CONT:
        for k in VAR: val[k][c] = 0.0; src[k][c] = f'zero: contained in {CONT[c]}'
        continue
    if c == 'TWN':
        for k in ['GDP', 'C', 'G', 'I']: val[k][c] = dgv[k] / fx22; src[k][c] = 'DGBAS/CBC'
        p = pwt[(pwt.countrycode == 'TWN') & (pwt.year == Y)].pop_millions.iloc[0] * 1e6
        val['POP'][c] = p; src['POP'][c] = 'PWT 11.0 pop (UN WPP-based)'
        continue
    g = wv(sc, 'GDP')
    if not np.isnan(g): val['GDP'][c] = g; src['GDP'][c] = 'WDI'
    elif sc in A.index and not np.isnan(A.loc[sc, 'gdp_million_usd']): val['GDP'][c] = A.loc[sc, 'gdp_million_usd']; src['GDP'][c] = 'UNSD AMA'
    for k in ['C', 'G', 'I']:
        v = wv(sc, k)
        if not np.isnan(v): val[k][c] = v; src[k][c] = 'WDI'
        elif c in val['GDP'] and sc in A.index and not np.isnan(A.loc[sc, AS[k]]) and A.loc[sc, 'gdp_million_usd'] > 0:
            sh = A.loc[sc, AS[k]] / A.loc[sc, 'gdp_million_usd']
            val[k][c] = sh * val['GDP'][c]; src[k][c] = 'UNSD AMA share x ' + src['GDP'][c] + ' GDP' if src['GDP'][c] == 'WDI' else 'UNSD AMA'
    p = wv(sc, 'POP')
    if not np.isnan(p): val['POP'][c] = p; src['POP'][c] = 'WDI'
    elif sc in ag.index and ag.loc[sc, 'gdp_per_capita_usd'] > 0:
        val['POP'][c] = ag.loc[sc, 'gdp_usd'] / ag.loc[sc, 'gdp_per_capita_usd']; src['POP'][c] = 'UNSD AMA (GDP / GDP per capita)'

# beta v5 Y (choice gdp_imputed_ama_to_weo, s02_capital/gdp_weo.py; David 2026-10-27 08:39 UTC, package v2; labelled departure):
# where GDP came from UN AMA and the AMA national-currency GDP series is a straight-line imputation, or AMA GDP per head is
# below 250 USD, the country takes IMF WEO GDP (current USD, base year); C, G and GFCF keep their AMA shares of AMA GDP
KCHY = PIM.load_choices(I(PIM.CHOICES_PATH, 'config: S02 choices (gdp_imputed_ama_to_weo)'))
WEO_BASIS = KCHY[GW.BASIS_CHOICE]['value']
weo_on = KCHY[GW.CHOICE]['value'] != 'off'
weo = GW.read_weo(I(DATA + '/imf_weo/weo_2026oct_ngdpd_2017_2023.csv', 'IMF WEO October 2026 GDP current USD (beta v5 Y)'), Y)
amanc = pd.read_excel(I(DATA + '/unsd_ama_nc/Download-GDPcurrent-NCU-countries.xlsx', 'UN AMA GDP in national currency (beta v5 Y imputation test)'), header=2)
amanc = amanc[amanc.IndicatorName == 'Gross Domestic Product (GDP)'].set_index('CountryID')
M49 = ag['m49'].to_dict()
yrs_nc = [y for y in amanc.columns if isinstance(y, int)]
last_nc = max(yrs_nc)
weo_rate = KCHY[GW.CHOICE]['value'] == GW.ON_RATE
_fmt = lambda x, d=0: f'{x:,.{d}f}' if x is not None and np.isfinite(x) else 'none'
weo_rows = []
for c, r in C.iterrows():
    if src['GDP'].get(c) != 'UNSD AMA':
        continue
    m49 = M49.get(r.sc)
    imp = m49 in amanc.index and GW.ama_imputed([amanc.loc[m49, y] for y in range(last_nc - GW.IMPUTED_YEARS + 1, last_nc + 1)])
    pc = float(ag.loc[r.sc, 'gdp_per_capita_usd']) if r.sc in ag.index else None
    wtot, wpc = weo.get(r.sc, (None, None))
    wpop = wtot / wpc if wtot and wpc else None                                  # WEO-implied population, million
    pop = val['POP'].get(c, 0.0) / 1e6                                           # S02 population, million
    # beta v5 Y basis (choice weo_gdp_basis; David 2026-10-27 10:00 UTC): WEO GDP per head x the S02 population (an estimate:
    # the Yemen WEO total implies 17.2 m people against WDI's 38.2 m, so it likely covers only part of the country)
    w = GW.target_musd(wtot, wpc, pop, WEO_BASIS)
    # value ON_RATE (South Sudan, 2026-10-27 09:32 UTC): the AMA exchange rate against the WDI official rate
    ama_rate = (float(amanc.loc[m49, Y]) / (A.loc[r.sc, 'gdp_million_usd'] * 1e6)
                if m49 in amanc.index and r.sc in A.index and A.loc[r.sc, 'gdp_million_usd'] > 0 else None)
    wdi_rate = w22.loc[r.sc, 'PA.NUS.FCRF'] if r.sc in w22.index and 'PA.NUS.FCRF' in w22.columns else None
    roff = weo_rate and GW.rate_off(ama_rate, wdi_rate)
    hit = GW.applies('UNSD AMA', imp, pc, wtot, rate_mismatch=roff)
    why = ('imputed' if imp else (f'below {GW.PC_FLOOR:.0f} USD per head' if pc is not None and pc < GW.PC_FLOOR else
           f'rate {_fmt(ama_rate, 1)} against WDI official {_fmt(wdi_rate, 1)} LCU per USD'))
    weo_rows.append((r.region, c, val['GDP'][c], pc, imp, ama_rate, wdi_rate, w, (wtot, wpc, wpop, pop), hit and weo_on))
    if hit and weo_on:
        f = w / val['GDP'][c]
        S.adjust(r.region, f'{c} GDP', round(val['GDP'][c], 3), round(w, 3), GW.CHOICE,
                 f'beta v5 Y (labelled departure): UN AMA GDP ' + ('series imputed (equal yearly increments '
                 f'{last_nc - GW.IMPUTED_YEARS + 1}-{last_nc})' if imp else why) +
                 f'; IMF WEO (October 2026 edition) {Y} GDP, ' + ('ESTIMATE: GDP per head {:,.1f} USD x S02 population {:,.2f} m '
                 '(WEO total {:,.0f} USD m implies {:,.2f} m people)'.format(wpc, pop, wtot, wpop) if WEO_BASIS == GW.BASIS_PC else 'WEO total') +
                 f'; C, G, GFCF keep their AMA shares (x{f:.3f})', 'GDP-WEO')
        val['GDP'][c] = w
        src['GDP'][c] = f'IMF WEO October 2026 edition, {Y} ' + ('GDP per head x S02 population, estimate' if WEO_BASIS == GW.BASIS_PC else 'GDP') + f' (beta v5 Y: UN AMA {why})'
        for k in ['C', 'G', 'I']:
            if src[k].get(c) == 'UNSD AMA':
                val[k][c] *= f
                src[k][c] = 'UNSD AMA share x IMF WEO GDP'
S.check('S02-Rweo', 'Beta v5 Y (choice gdp_imputed_ama_to_weo): countries whose GDP comes from UN AMA, with the imputation test '
        f'(equal yearly increments in the AMA national-currency series {last_nc - GW.IMPUTED_YEARS + 1}-{last_nc}), AMA GDP per head, '
        'the AMA and WDI official exchange rates, the WEO total, per head and implied population against the S02 population, the value used '
        '(weo_gdp_basis), and whether WEO replaced AMA', 'report', sum(x[-1] for x in weo_rows), 'n/a', True, GW.CHOICE,
        f"{KCHY[GW.CHOICE]['value']}; basis {WEO_BASIS}; " + '; '.join(f'{c} AMA {g:,.0f} USD m, per head {_fmt(p)}, imputed {"yes" if i else "no"}, '
        f'rate AMA {_fmt(ar, 2)} WDI {_fmt(wr, 2)}, WEO total {_fmt(wb[0])} per head {_fmt(wb[1], 1)} implied population '
        f'{_fmt(wb[2], 2)} m vs S02 {_fmt(wb[3], 2)} m, value {_fmt(w)}' + (' -> WEO' if h else ' kept') for _r, c, g, p, i, ar, wr, w, wb, h in weo_rows))
weo_bad = [c for _r, c, g, p, i, ar, wr, w, wb, h in weo_rows if h and (abs(val['GDP'][c] - w) > 1e-6 or any(
    abs(val[k][c] / val['GDP'][c] - A.loc[C.loc[c, 'sc'], AS[k]] / A.loc[C.loc[c, 'sc'], 'gdp_million_usd']) > 1e-9
    for k in ['C', 'G', 'I'] if src[k].get(c) == 'UNSD AMA share x IMF WEO GDP'))]
S.check('S02-Hweo', 'Beta v5 Y (choice gdp_imputed_ama_to_weo): every country moved to WEO GDP carries the WEO value and keeps its UN AMA '
        'C, G and GFCF shares of GDP', 'hard', len(weo_bad), 0, not weo_bad, GW.CHOICE, ' '.join(weo_bad) or 'none')

# beta v5 Cuba (choice gdp_lcu_official_rate, s02_capital/gdp_official.py; David 2026-10-27 09:32 UTC; labelled departure):
# the listed economies take GDP, C, G and GFCF from the statistics office's own national-currency accounts (UN SNA table
# 1.1) at the listed official rate, in place of UN AMA (which converts Cuba at the old 1:1 peg)
KCHO = KCHY[GO.CHOICE]['value']
off_cfg = GO.load_rows(I(CFG + '/gdp_official_rate_2022.csv', 'config: official-rate GDP (beta v5 Cuba)')) if KCHO != 'off' else {}
off_rows = []
for c, r in C.iterrows():
    row = off_cfg.get(r.sc)
    if row is None:
        continue
    if int(row['year']) != Y or src['GDP'].get(c) != 'UNSD AMA':
        raise SystemExit(f'gdp_official_rate_2022.csv: {r.sc} is listed for {row["year"]} but S02 takes its {Y} GDP from {src["GDP"].get(c)}')
    lcu = GO.read_table(I(DATA + '/' + row['data_file'], f'{r.sc} official national accounts (beta v5 gdp_lcu_official_rate)'), r.sc, Y)
    usd = GO.to_musd(lcu, row['lcu_per_usd'])
    old = {k: val[k][c] for k in ['GDP', 'C', 'G', 'I']}
    for k in ['GDP', 'C', 'G', 'I']:
        val[k][c] = usd[k]
        src[k][c] = f'Official LCU accounts at {float(row["lcu_per_usd"]):g} LCU per USD (beta v5 {GO.CHOICE})'
    S.adjust(r.region, f'{c} GDP', round(old['GDP'], 3), round(usd['GDP'], 3), GO.CHOICE,
             f'beta v5 (labelled departure): {row["data_file"]} GDP {lcu["GDP"]:,.0f} LCU at {row["lcu_per_usd"]} per USD ({row["rate_source"]}); '
             'C, G and GFCF from the same table', 'GDP-OFFICIAL')
    off_rows.append((r.region, c, old, usd, lcu, float(row['lcu_per_usd'])))
off_bad = [c for _r, c, o, u, l, fx in off_rows if any(abs(val[k][c] * 1e6 * fx - l[k]) > 1e-3 * max(1.0, abs(l[k])) for k in l)]
S.check('S02-Hofficial', 'Beta v5 Cuba (choice gdp_lcu_official_rate): every listed economy carries the official national-currency GDP, C, G '
        'and GFCF divided by its listed rate', 'hard', len(off_bad), 0, not off_bad, GO.CHOICE,
        f'{KCHO}; ' + ('; '.join(f'{c}: GDP {o["GDP"]:,.0f} -> {u["GDP"]:,.0f} USD m (C/GDP {u["C"] / u["GDP"]:.3f}, G/GDP {u["G"] / u["GDP"]:.3f}, '
                                  f'GFCF/GDP {u["I"] / u["GDP"]:.3f}) at {fx:g}' for _r, c, o, u, l, fx in off_rows) or 'none') + (' ' + ' '.join(off_bad) if off_bad else ''))

# beta v4 G16a (choice gfcf_wdi_outlier; S16 region gates 2026-10-26; David 08:26 UTC: AMA for LBN and VEN, an estimate):
# where WDI GFCF is implausibly low against UN AMA (below 5% of GDP and AMA more than twice the share), the listed
# countries take the AMA GFCF share x WDI GDP, as the C, G and I gap rule above does where WDI has no value; the
# alternative gives LBN its own WDI 2019 GFCF share of GDP (current LCU), the last year before the WDI series collapses
KCH0 = PIM.load_choices(I(PIM.CHOICES_PATH, 'config: S02 choices (capital, gfcf_wdi_outlier)'))
g16 = KCH0['gfcf_wdi_outlier']['value']
g16_regs = PIM.GFCF_REGIONS[g16]
lbn19 = None
if g16 == PIM.GFCF_LBN_2019:
    wk0 = pd.read_csv(I(DATA + '/wdi/wdi_capital_series_1960_2022.csv', 'WDI GFCF and GDP LCU (gfcf_wdi_outlier LBN 2019 share)'))
    w19 = wk0[(wk0.iso3 == 'LBN') & (wk0.year == 2019)].set_index('series')['value']
    lbn19 = float(w19['NE.GDI.FTOT.CN'] / w19['NY.GDP.MKTP.CN'])
gfcf_rows = []
for c, r in C.iterrows():
    sc = r.sc
    if c in CONT or src['I'].get(c) != 'WDI' or src['GDP'].get(c) != 'WDI' or sc not in A.index or not val['GDP'].get(c):
        continue
    if not (A.loc[sc, 'gdp_million_usd'] > 0) or np.isnan(A.loc[sc, 'gfcf_million_usd']):
        continue
    sh_w, sh_a = val['I'][c] / val['GDP'][c], A.loc[sc, 'gfcf_million_usd'] / A.loc[sc, 'gdp_million_usd']
    if PIM.gfcf_outlier(sh_w, sh_a):
        on = g16_regs is None or c in g16_regs
        sh, how = (lbn19, 'WDI 2019 GFCF share of GDP (LCU)') if (on and c == 'LBN' and lbn19 is not None) else (sh_a, 'UN AMA GFCF share')
        gfcf_rows.append((r.region, c, sh_w, sh_a, on, sh))
        if on:
            S.adjust(r.region, f'{c} I (GFCF)', round(val['I'][c], 3), round(sh * val['GDP'][c], 3), 'gfcf_wdi_outlier',
                     f'beta v4 G16a (estimate): WDI GFCF {sh_w:.3f} of GDP against UN AMA {sh_a:.3f}; {how} {sh:.3f} x WDI GDP', 'GFCF-AMA')
            val['I'][c] = sh * val['GDP'][c]
            src['I'][c] = f'estimate: {how} x WDI GDP (G16a: WDI GFCF {sh_w:.3f} of GDP)'
S.check('S02-Rgfcf', 'Beta v4 G16a (choice gfcf_wdi_outlier): countries whose WDI GFCF is below 5% of GDP with the UN AMA share above twice it '
        '(replaced by the AMA share x WDI GDP when the choice is on)', 'report', len(gfcf_rows), 0, True, 'gfcf_wdi_outlier',
        f"{g16}; " + ('; '.join(f'{c} ({g}) WDI {w:.3f} AMA {a:.3f}' + (f' -> {u:.3f}' if o else ' kept') for g, c, w, a, o, u in gfcf_rows) or 'none'))

# ---------------------------------------------------------------- fills (rule F1, GTAP 12 ch.7 pp.1-2)
obs = [c for c in C.index if src['GDP'].get(c) in ('WDI', 'UNSD AMA', 'DGBAS/CBC') or src['GDP'].get(c, '').startswith(('IMF WEO', 'Official LCU'))]
def geomean(fn, members):
    xs = [fn(c) for c in members]; xs = [x for x in xs if x is not None and np.isfinite(x)]
    return (float(np.mean(xs)), len(xs)) if xs else (np.nan, 0)
CIT1 = 'GTAP 12 ch.7 p.1 (geo-region average share x GDP); READINESS F1'
CIT2 = 'GTAP 12 ch.7 p.2 (geo-region average per-capita GDP x population); READINESS F1'
for c, r in C.iterrows():
    if c in CONT: continue
    if c not in val['GDP']:
        if c in val['POP'] and val['POP'][c] > 0:
            peers = [x for x in obs if C.loc[x, 'geo'] == r.geo and val['POP'].get(x, 0) > 0]
            pc, n = geomean(lambda x: val['GDP'][x] / val['POP'][x], peers)
            val['GDP'][c] = pc * val['POP'][c]; src['GDP'][c] = f'F1 per-capita fill ({r.geo}, n={n})'
            S.adjust(r.region, f'{c} GDP', '(missing)', round(val['GDP'][c], 3), 'F1', CIT2, 'fill')
        else:
            for k in VAR:
                val[k].setdefault(c, 0.0); src[k].setdefault(c, 'zero: no GDP and no population (GTAP ch.7 p.2)')
            S.adjust(r.region, f'{c} GDP, C, G, I, POP', '(missing)', 0, 'F1', 'GTAP 12 ch.7 p.2: no data -> zero', 'zero+flag')
            continue
    for k in ['C', 'G', 'I']:
        if c not in val[k]:
            peers = [x for x in obs if C.loc[x, 'geo'] == r.geo and src[k].get(x, '').startswith(('WDI', 'UNSD', 'DGBAS', 'Official LCU')) and val['GDP'][x] > 0]
            sh, n = geomean(lambda x: val[k][x] / val['GDP'][x], peers)
            val[k][c] = sh * val['GDP'][c]; src[k][c] = f'F1 geo-share fill ({r.geo}, n={n}, share {sh:.3f})'
            S.adjust(r.region, f'{c} {k}', '(missing)', round(val[k][c], 3), 'F1', CIT1, 'fill')
    if c not in val['POP']:
        val['POP'][c] = 0.0; src['POP'][c] = 'zero: no population source'
        S.adjust(r.region, f'{c} POP', '(missing)', 0, 'F1', 'no population in WDI, AMA or PWT', 'zero+flag')

# ---------------------------------------------------------------- capital (GTAP 12 ch.7 s7.3; fix round 2, David 2026-10-20 22:02)
# Order, as GTAP 12 ch.7 s7.3: (1) IMF ICSD, latest year, rolled forward to Y by the perpetual inventory method (GTAP: "for 2023,
# we relied on our own estimates of capital stock that follow the perpetual inventory method"); (2) where ICSD has no capital
# (missing, or kgov_n + kpriv_n = 0, which ICSD uses for "no data"), a perpetual inventory over the country's own real GFCF
# history (David 22:02); (3) GDP x the average K/GDP of ICSD countries in the Table 9.10 geographic region. Depreciation 4%.
# PWT is kept only as a report-only comparison (check S02-P6).
DELTA = 0.04
PIM_MIN_YEARS = 30   # tier 2 needs >= 30 consecutive years of real GFCF ending in Y, so the initial stock keeps <= 0.96^30 = 29% weight
CITK1 = 'GTAP 12 ch.7 s7.3 (IMF ICSD, perpetual inventory to the reference year); IMF (2021) ICSD; David 2026-10-20 22:02'
CITK2 = 'GTAP 12 ch.7 s7.3 (own perpetual-inventory estimates); WDI NE.GDI.FTOT.KD; David 2026-10-20 22:02'
CITK3 = 'GTAP 12 ch.7 s7.3 (geographic-region average K/GDP x GDP); READINESS F2'
wk = pd.read_csv(I(DATA + '/wdi/wdi_capital_series_1960_2022.csv', 'WDI GFCF (CD, KD, CN), GDP deflator, GDP LCU, 1960-2022 (capital)'))
wl = wk.pivot_table(index=['iso3', 'year'], columns='series', values='value')
wx = wdi.pivot_table(index=['iso3', 'year'], columns='series', values='value')   # PA.NUS.FCRF (2017-2022) for the CN-missing case
def _w(tab, c, t, ser):
    return tab.loc[(c, t), ser] if (c, t) in tab.index and ser in tab.columns else np.nan
VKB, ksrc, kinfo = {}, {}, {}
# Fix round 3 (P10, worker wH): revaluation deflator and re-base band from config/s02/s02_choices.csv (s02_capital/pim.py)
KCH = PIM.load_choices(I(PIM.CHOICES_PATH, 'config: S02 capital choices (revaluation deflator, re-base band)'))
KREVAL = KCH['capital_revaluation']['value']
KBAND = PIM.band_value(KCH['capital_rebase_band']['value'])
REBASED = {}
# Roll-forward fallback sources (David 2026-10-20 22:31): where WDI lacks a series needed to roll ICSD forward, an official
# national-accounts series listed in config/s02/capital_roll_sources.csv replaces that WDI series for that country (whole series).
# Same rule as every other country; only the source of the series changes. Loaders are per file format, not per country.
def _load_dgbas_xml(path, sel):
    import xml.etree.ElementTree as ET
    out = {}
    for o in ET.parse(path).getroot().findall('Obs'):
        if o.findtext('Item') == sel and o.findtext('TYPE') == '原始值':
            out[int(o.findtext('TIME_PERIOD'))] = float(o.findtext('Item_VALUE'))
    if not out: raise SystemExit(f'roll source: {path} selector {sel} matched no rows')
    return out
def _load_unsd_ama_xlsx(path, sel):
    cid, ind = sel.split('|', 1)
    x = pd.read_excel(path, header=2)
    row = x[(x.CountryID.astype(str) == cid) & (x.IndicatorName == ind)]
    if len(row) != 1: raise SystemExit(f'roll source: {path} selector {sel} matched {len(row)} rows')
    return {int(k): float(v) for k, v in row.iloc[0].items() if isinstance(k, (int, float)) and pd.notna(v)}
LOADERS = {'dgbas_xml': _load_dgbas_xml, 'unsd_ama_xlsx': _load_unsd_ama_xlsx}
VAR2WDI = {'gdp_lcu': 'NY.GDP.MKTP.CN', 'gfcf_lcu': 'NE.GDI.FTOT.CN', 'gdp_deflator': 'NY.GDP.DEFL.ZS'}
rsrc = pd.read_csv(I(CFG + '/capital_roll_sources.csv', 'config: capital roll-forward fallback sources (David 22:31)'), dtype=str)
ROLL = collections.defaultdict(dict)   # iso3 -> WDI series code -> {year: value in LCU units}
for r in rsrc.itertuples():
    if r.approved_by != 'David': continue
    ser = LOADERS[r.source_kind](I(DATA + '/' + r.file, f'capital roll source {r.iso3} {r.variable}'), r.selector)
    ROLL[r.iso3][VAR2WDI[r.variable]] = {t: v * float(r.to_lcu_units) for t, v in ser.items()}
def _wr(c, t, ser):
    # WDI series, or the configured official fallback series for this country
    if ser in ROLL.get(c, {}): return ROLL[c][ser].get(t, np.nan)
    return _w(wl, c, t, ser)
# David 2026-10-20 22:31: listed ICSD capital is unusable -> the country takes the geographic average and is excluded from every
# average pool (explicit, ledgered list; no automatic screen)
NOROLL = {}   # ICSD present but not rollable to Y -> tier 3 (David 22:31)
unus = pd.read_csv(I(CFG + '/capital_icsd_unusable.csv', 'config: ICSD capital marked unusable (David 22:31)'))
UNUS = {r.iso3: r for r in unus.itertuples() if r.approved_by == 'David'}
icsd_ok = icsd[icsd.kgov_n.notna() & icsd.kpriv_n.notna() & icsd.GDP_n.notna() & ((icsd.kgov_n + icsd.kpriv_n) > 0) & (icsd.GDP_n > 0) & (icsd.year <= Y)]
icsd_zero = sorted(set(icsd[icsd.kgov_n.notna() & icsd.kpriv_n.notna() & ((icsd.kgov_n + icsd.kpriv_n) <= 0)].isocode))
for c, r in C.iterrows():
    sc = r.sc
    if val['GDP'][c] == 0: VKB[c] = 0.0; ksrc[c] = 'zero (no GDP)'; continue
    if sc in UNUS:
        S.adjust(r.region, f'{c} VKB ICSD', 'ICSD', 'unusable', 'K0', f'David {UNUS[sc].approved_date_utc7}: {UNUS[sc].reason}', 'capital_icsd_unusable')
        S.flag('KAPITAL-UNUSABLE-' + c, c, f'{UNUS[sc].reason}. {UNUS[sc].evidence}. Takes the geographic-average K/GDP; excluded from every average pool.', 'no', 'K0', f'David {UNUS[sc].approved_date_utc7}; config/s02/capital_icsd_unusable.csv')
        continue
    x = icsd_ok[icsd_ok.isocode == sc]
    if x.empty: continue
    x = x[x.year == x.year.max()].iloc[0]; y0 = int(x.year)
    ky0 = (x.kgov_n + x.kpriv_n + (0 if np.isnan(x.kppp_n) else x.kppp_n)) / x.GDP_n   # ICSD's own K/GDP in its latest year (review FR-L2)
    g0 = _wr(sc, y0, 'NY.GDP.MKTP.CN')
    ok = bool(np.isfinite(g0) and g0 > 0)
    steps, rvb = [], set()
    for t in range(y0 + 1, Y + 1):
        if not ok: break
        # revaluation (fix round 3, P10): the implicit GFCF deflator (WDI current / constant-price GFCF), as ICSD's own
        # current-cost stocks use the investment price (P_K = P_I in ICSD); GDP deflator where no constant-price GFCF
        own = 'NE.GDI.FTOT.CN' not in ROLL.get(sc, {})   # a configured official GFCF series has no matching WDI KD
        rv, rb = PIM.revaluation(KREVAL, _w(wl, sc, t, 'NE.GDI.FTOT.CN') if own else np.nan, _w(wl, sc, t, 'NE.GDI.FTOT.KD'),
                                 _w(wl, sc, t - 1, 'NE.GDI.FTOT.CN') if own else np.nan, _w(wl, sc, t - 1, 'NE.GDI.FTOT.KD'),
                                 _wr(sc, t, 'NY.GDP.DEFL.ZS'), _wr(sc, t - 1, 'NY.GDP.DEFL.ZS'))
        inv = _wr(sc, t, 'NE.GDI.FTOT.CN')
        if not np.isfinite(inv) and own: inv = _w(wl, sc, t, 'NE.GDI.FTOT.CD') * _w(wx, sc, t, 'PA.NUS.FCRF')
        if not (np.isfinite(rv) and np.isfinite(inv)): ok = False; break
        steps.append((rv, inv)); rvb.add(rb)
    K = PIM.roll(ky0 * g0, steps, DELTA) if ok else np.nan
    gY = _wr(sc, Y, 'NY.GDP.MKTP.CN')
    rs = ', '.join(f'{k} from {rsrc[(rsrc.iso3 == sc) & (rsrc.variable == v)].file.iloc[0]}' for v, k in VAR2WDI.items() if k in ROLL.get(sc, {}))
    if ok and np.isfinite(gY) and gY > 0:
        kyr = K / gY
        kyu, reb = PIM.rebase(kyr, ky0, KBAND)
        if reb:
            REBASED[c] = (y0, ky0, kyr)
            S.flag('KAPITAL-REBASE-' + c, c, f'Rolled K/GDP {kyr:.3f} moves {kyr / ky0 - 1:+.0%} from the ICSD {y0} ratio {ky0:.3f}, beyond the '
                   f'{KBAND:.0%} band: re-based to the ICSD ratio.', 'no', 'K1', 'config/s02/s02_choices.csv capital_rebase_band; fix round 3 (P10)')
        VKB[c] = kyu * val['GDP'][c]; kinfo[c] = (1, y0, ky0)
        rvs = '+'.join(sorted(rvb)) or '-'
        ksrc[c] = f'IMF ICSD {y0} K/GDP {ky0:.3f}' + (f', rolled to {Y} (PIM, 4%, revalued by {rvs} deflator)' if y0 < Y else '') + \
            (f': rolled K/GDP {kyr:.3f} re-based to the ICSD ratio' if reb else f': K/GDP {kyr:.3f}') + ' x GDP used' + (f' [roll source: {rs}]' if rs else '')
        S.adjust(r.region, f'{c} VKB', f'ICSD {y0} K/GDP {ky0:.4f}', round(VKB[c], 3), 'K1', CITK1 + (f'; roll source (David 22:31, config/s02/capital_roll_sources.csv): {rs}' if rs else '') +
                 (f'; re-based (band {KBAND:.0%})' if reb else ''), 'capital_pim_rollforward' if y0 < Y else 'capital_icsd')
    else:
        # David 2026-10-20 22:31: ICSD that cannot be carried to the base year -> geographic average, as GTAP does (its 2023
        # Table 7.1 shows capital 0, i.e. a regional fill, for these countries); not tier 2, since ICSD exists
        NOROLL[c] = y0
# tier 2: perpetual inventory over the country's own real GFCF (constant 2015 USD), revalued with the GFCF used in Y
for c, r in C.iterrows():
    sc = r.sc
    if c in VKB or sc in UNUS or c in NOROLL: continue
    if not src['I'].get(c, '').startswith(('WDI', 'UNSD', 'DGBAS', 'Official LCU')): continue   # beta v5: official-rate GFCF (CUB) is observed
    kd = {t: _w(wl, sc, t, 'NE.GDI.FTOT.KD') for t in range(1960, Y + 1)}
    run = []
    t = Y
    while t >= 1960 and np.isfinite(kd[t]) and kd[t] > 0: run.append(t); t -= 1
    if len(run) < PIM_MIN_YEARS: continue
    run = sorted(run); s0 = [kd[t] for t in run]
    g = max(0.0, (s0[10] / s0[0]) ** (1 / 10) - 1)   # initial stock I0 / (g + delta), g = real GFCF growth over the first 10 years, floored at 0
    K = s0[0] / (g + DELTA)
    for v in s0[1:]: K = (1 - DELTA) * K + v
    VKB[c] = K / kd[Y] * val['I'][c]; kinfo[c] = (2, run[0], g)
    ksrc[c] = f'PIM own GFCF {run[0]}-{Y} (WDI KD, 4%, g {g:.3f}): K/GDP {VKB[c] / val["GDP"][c]:.3f} x GDP used'
    S.adjust(r.region, f'{c} VKB', '(ICSD missing)', round(VKB[c], 3), 'K2', CITK2, 'fill')
kyobs = [c for c in VKB if ksrc[c].startswith('IMF ICSD') and val['GDP'][c] > 0 and C.loc[c, 'sc'] not in UNUS]
for c, r in C.iterrows():
    if c in VKB: continue
    peers = [x for x in kyobs if C.loc[x, 'geo'] == r.geo]
    ky, n = geomean(lambda x: VKB[x] / val['GDP'][x], peers)
    VKB[c] = ky * val['GDP'][c]; kinfo[c] = (3, r.geo, n)
    ksrc[c] = f'F2 geo K/GDP ({r.geo}, n={n} ICSD countries, K/Y {ky:.2f})' + (' [ICSD unusable, David 22:31]' if r.sc in UNUS else '') + \
        (f' [ICSD {NOROLL[c]} cannot be rolled to {Y}, David 22:31]' if c in NOROLL else '')
    S.adjust(r.region, f'{c} VKB', f'ICSD {NOROLL[c]} not rollable' if c in NOROLL else ('ICSD unusable' if r.sc in UNUS else '(missing)'), round(VKB[c], 3), 'F2', CITK3, 'fill')
# PWT, report-only comparison (previous method, E30)
P = pwt[pwt.year == Y].set_index('countrycode')
KPWT = {}
for c, r in C.iterrows():
    sc = r.sc
    if sc in P.index and all(np.isfinite(P.loc[sc, v]) for v in ('cn', 'pl_n', 'cgdpo', 'pl_gdpo')) and P.loc[sc, 'cgdpo'] * P.loc[sc, 'pl_gdpo'] > 0:
        KPWT[c] = (P.loc[sc, 'cn'] * P.loc[sc, 'pl_n']) / (P.loc[sc, 'cgdpo'] * P.loc[sc, 'pl_gdpo']) * val['GDP'][c]

# ---------------------------------------------------------------- country table and regions
ct = pd.DataFrame({'code': C.index, 'region': C.region.values, 'geo': C.geo.values})
for k in VAR:
    ct[k] = ct.code.map(val[k]); ct[k + '_source'] = ct.code.map(src[k])
ct['VKB'] = ct.code.map(VKB); ct['VKB_source'] = ct.code.map(ksrc); ct['VDEP'] = 0.04 * ct.VKB
ct['capital_tier'] = ct.code.map(lambda c: kinfo.get(c, (0,))[0])   # 1 ICSD, 2 own-GFCF PIM, 3 geo average, 0 zero GDP
ct['memo_PWT_KY_x_GDP_musd'] = ct.code.map(KPWT)   # previous method (E30), report-only comparison
ct = ct.rename(columns={'GDP': 'GDP_musd', 'C': 'C_musd', 'G': 'G_musd', 'I': 'GFCF_musd', 'VKB': 'VKB_musd', 'VDEP': 'VDEP_musd'})
num = ['GDP_musd', 'C_musd', 'G_musd', 'GFCF_musd', 'POP', 'VKB_musd', 'VDEP_musd']
S.check('S02-C1', 'No missing values in the country table', 'hard', int(ct[num].isna().sum().sum()), 0, ct[num].isna().sum().sum() == 0)
filled = lambda col: ~ct[col + '_source'].str.startswith(('WDI', 'UNSD', 'DGBAS', 'IMF ICSD', 'IMF WEO', 'Official LCU'))
rg = ct.groupby('region')[num].sum()
fshare = ct.assign(f=np.where(filled('GDP'), ct.GDP_musd, 0)).groupby('region').f.sum() / rg.GDP_musd
rg['GDP_filled_share'] = fshare
rg['K_over_GDP'] = rg.VKB_musd / rg.GDP_musd
rg['VDEP_over_GFCF'] = rg.VDEP_musd / rg.GFCF_musd
rg['implied_NX_musd'] = rg.GDP_musd - rg.C_musd - rg.G_musd - rg.GFCF_musd
rg = regions[['region', 'name', 'type']].set_index('region').join(rg)
S.write('macro_country.csv', ct)
S.write('macro_regions.csv', rg.reset_index())
# Independent region membership (review S02-L1): from S01 regions.csv (members, territories) plus the inherited
# territory folds in config/s01/territory_folds.csv, not from the region column used for the groupby above.
MEM = {r.region: set(str(r.members).split()) | set(str(r.territories).split() if isinstance(r.territories, str) else []) for r in regions.itertuples()}
changed = True
while changed:
    changed = False
    for t in tfold.itertuples():
        for g, ms in MEM.items():
            if t.into in ms and t.code not in ms: ms.add(t.code); changed = True
owner = collections.defaultdict(list)
for g, ms in MEM.items():
    for m in ms: owner[m].append(g)
nomem = [c for c in ct.code if len(owner.get(c, [])) != 1 or owner[c][0] != ct.set_index('code').region[c]]
S.check('S02-A0', 'Every country belongs to exactly one region by the independent membership lists, and it is the region used', 'hard', len(nomem), 0, not nomem, 'P4 independent check', ' '.join(nomem))
# reverse direction (review FR-L3): every member named in the S01 membership lists is in the S02 country table
memx = sorted({m for ms in MEM.values() for m in ms} - set(ct.code))
S.check('S02-A0r', 'Every member in the S01 membership lists is in the S02 country table (reverse of A0)', 'hard', len(memx), 0, not memx, 'review FR-L3', ' '.join(memx))
cti = ct.set_index('code')
for k in num:
    ind_sum = pd.Series({g: cti.reindex([m for m in ms if m in cti.index])[k].sum() for g, ms in MEM.items()})
    dmax = (ind_sum.reindex(rg.index) - rg[k]).abs().max()
    S.check(f'S02-A-{k}', f'Region totals equal an independent sum over S01 member lists ({k})', 'hard', f'max abs diff {dmax:.3g}', '<= 1e-9 x world',
            dmax <= 1e-9 * max(1, abs(ct[k].sum())), 'P4 independent check')
neg = rg[(rg[['GDP_musd', 'C_musd', 'G_musd', 'GFCF_musd', 'POP', 'VKB_musd']] <= 0).any(axis=1)]
S.check('S02-H1', 'Every region has GDP, C, G, GFCF, POP and VKB > 0', 'hard', len(neg), 0, neg.empty, 'sign', ' '.join(neg.index))
# H2 (review S02-L1): the ledger must have exactly one row per fill or zeroing event, counted from the source columns
ev = {'GDP per-capita fill': ct.GDP_source.str.startswith('F1 per-capita').sum(),
      'zero, no data': ct.GDP_source.str.startswith('zero: no GDP and no population').sum(),
      'C/G/I geo-share fills': sum(ct[k + '_source'].str.startswith('F1 geo-share').sum() for k in ['C', 'G', 'I']),
      'POP zero': ct.POP_source.str.startswith('zero: no population source').sum(),
      'VKB rows (ICSD, own-GFCF PIM, F2)': ct.VKB_source.str.startswith(('IMF ICSD', 'PIM own', 'F2')).sum(),
      'ICSD unusable (David 22:31)': ct.VKB_source.str.contains('ICSD unusable', regex=False).sum(),
      'G16a AMA GFCF (gfcf_wdi_outlier)': ct.I_source.str.contains('(G16a:', regex=False).sum(),
      'v5 Y WEO GDP (gdp_imputed_ama_to_weo)': ct.GDP_source.str.startswith('IMF WEO').sum(),
      'v5 official-rate GDP (gdp_lcu_official_rate)': ct.GDP_source.str.startswith('Official LCU').sum()}
exp_rows = int(sum(ev.values())); got = len(S.ledger)
led_codes = {a['item'].split()[0] for a in S.ledger}
miss_led = sorted(set(ct[filled('GDP') | filled('C') | filled('G') | filled('I') | ~ct.VKB_source.str.startswith('IMF ICSD')].code) - led_codes - set(CONT) - set(ct[ct.VKB_source == 'zero (no GDP)'].code))
S.check('S02-H2', 'Every filled or zeroed value has a ledger row (rows = fill events counted from the source columns)', 'hard', f'{got} rows; {exp_rows} expected; {len(miss_led)} codes missing', 'equal; 0',
        got == exp_rows and not miss_led, 'P2', '; '.join(f'{k} {v}' for k, v in ev.items()) + '. Contained codes carry a zero by containment, recorded in macro_country.csv sources. ' + ' '.join(miss_led))
bad = rg[rg.VDEP_over_GFCF >= 1]
# David 2026-10-20 19:25 (UTC+7): option C. VDEP < GFCF is report-only, as in GTAP (its own Table 7.1 has VDEP > GFCF, e.g. LBN).
# The hard S-I items (SAVE > 0 etc.) stay at S14. Standard: "as long as depreciation doesn't break the model" -> carried flag.
S.check('S02-H3', 'VDEP (4% of VKB) < GFCF in every region (report-only per David 19:25, option C; GTAP does not gate this)', 'report', len(bad), 0, bad.empty,
        'E12 (PLAN (h) step 3), E28',
        '; '.join(f'{r}: VDEP/GFCF {v.VDEP_over_GFCF:.2f}, K/GDP {v.K_over_GDP:.1f} ({ct[ct.region == r].VKB_source.iloc[0]})' for r, v in bad.iterrows()))
h4 = rg[(rg.VKB_musd <= 0) | (rg.GFCF_musd <= 0) | rg.VKB_musd.isna() | rg.GFCF_musd.isna()]
S.check('S02-H4', 'Every region has capital stock VKB > 0 and gross investment GFCF > 0 (strict, review S02-L5)', 'hard', len(h4), 0, h4.empty, 'E28 (David 19:25)', ' '.join(h4.index))
S.adjust('ALL', 'check S02-H3 (VDEP < GFCF)', 'hard', 'report-only', 'decision',
         'David 2026-10-20 19:25 UTC+7 (option C); PLAN_ERRATA E28; GTAP 12 ch.7 Table 7.1', 'gate_kind_change')
S.flag('CARRY-VDEP', 'VDEP >= GFCF in ' + str(len(bad)) + ' regions: ' + ' '.join(bad.sort_values('VDEP_over_GFCF', ascending=False).index),
       'Carried flag. David\'s standard: "as long as depreciation doesn\'t break the model". Must be tested in the aggregation calibrate-and-solve checks (S14-S16): '
       'the model must calibrate and solve with these VDEP values, and SAVE > 0 must hold at S14. Values are not changed at S02.',
       'no', 'E28', 'David 2026-10-20 19:25; GTAP 12 ch.7 p.3')
prio = set(regions[regions.priority.fillna('').str.len() > 0].region)
fp = ct[ct.region.isin(prio) & (filled('GDP') | filled('C') | filled('G') | filled('I'))]
S.check('S02-R1', 'Priority economies (top 50, Gulf, OPEC) with any filled macro value', 'report', len(fp), 0, fp.empty, '', ' '.join(fp.code))
# ---------------------------------------------------------------- concept parity (report-only comparisons)
srcs_used = {'WDI', 'UNSD_AMA', 'DGBAS', 'CBC', 'PWT', 'IMF_ICSD', 'UNSD_AMA_NC'} | ({'IMF_WEO'} if (ct.GDP_source.str.startswith('IMF WEO')).any() else set()) | ({'UNSD_SNA_OFFICIAL'} if (ct.GDP_source.str.startswith('Official LCU')).any() else set())
S.check('S02-P3', 'Every source merged at S02 has a concept-parity entry', 'hard', sorted(srcs_used - set(par.source)), '[]', srcs_used <= set(par.source), 'concepts.md')
both = [c for c in C.index if not np.isnan(wv(C.loc[c, 'sc'], 'GDP')) and C.loc[c, 'sc'] in A.index and c not in CONT]
rat = pd.Series({c: wv(C.loc[c, 'sc'], 'GDP') / A.loc[C.loc[c, 'sc'], 'gdp_million_usd'] for c in both})
out = rat[(rat - 1).abs() > 0.05].sort_values()
S.check('S02-P4', 'WDI / UNSD AMA GDP ratio (both present): countries off by > 5%', 'report', f'{len(out)} of {len(rat)}; median {rat.median():.4f}', '0',
        out.empty, 'C14', ' '.join(f'{c} {v:.3f}' for c, v in out.items()))
pp = [c for c in C.index if C.loc[c, 'sc'] in P.index and val['GDP'][c] > 0 and np.isfinite(P.loc[C.loc[c, 'sc'], 'pl_gdpo'])]
pr = pd.Series({c: P.loc[C.loc[c, 'sc'], 'cgdpo'] * P.loc[C.loc[c, 'sc'], 'pl_gdpo'] / val['GDP'][c] for c in pp})
po = pr[(pr - 1).abs() > 0.10].sort_values()
S.check('S02-P5', 'PWT nominal output (cgdpo x pl_gdpo) / GDP used: off by > 10%', 'report', f'{len(po)} of {len(pr)}; median {pr.median():.4f}', '0', po.empty, 'E9',
        ' '.join(f'{c} {v:.2f}' for c, v in po.items()))
cmpk = ct.dropna(subset=['memo_PWT_KY_x_GDP_musd'])
rk = (cmpk.VKB_musd / cmpk.memo_PWT_KY_x_GDP_musd)
offk = cmpk[(rk - 1).abs() > 0.10]
S.check('S02-P6', 'VKB (GTAP order: ICSD, own-GFCF PIM, geo average) vs PWT K/Y x GDP used (previous method, report-only): countries off by > 10%', 'report',
        f'{len(offk)} of {len(cmpk)}; median ratio {rk.median():.3f}', '0', offk.empty, 'fix round 2 (David 22:02)',
        ' '.join(f'{c} {v:.2f}' for c, v in zip(offk.code, rk[offk.index])))
tiers = ct[ct.GDP_musd > 0].capital_tier.value_counts().to_dict()
S.check('S02-K1', 'Capital tiers (GTAP 12 ch.7 s7.3): 1 IMF ICSD, 2 own-GFCF perpetual inventory, 3 geographic-average K/GDP', 'report',
        f'tier1 {tiers.get(1, 0)}, tier2 {tiers.get(2, 0)}, tier3 {tiers.get(3, 0)}', '-', True, 'GTAP 12 ch.7 s7.3',
        'ICSD zero capital treated as missing: ' + ' '.join(icsd_zero) + '. ICSD unusable (David 22:31): ' + ' '.join(sorted(UNUS)) + '. ICSD not rollable to the base year -> tier 3 (David 22:31): ' +
        ' '.join(f'{c} (ICSD {y})' for c, y in sorted(NOROLL.items())) + '. Rolled with a configured official source: ' +
        ' '.join(f'{c} {VKB[c] / val["GDP"][c]:.3f}' for c in ct.code if 'roll source' in str(ksrc.get(c, ''))) + '. Tier 2: ' + ' '.join(f'{c} {VKB[c] / val["GDP"][c]:.2f}' for c in ct[ct.capital_tier == 2].code) +
        '. Tier 3: ' + ' '.join(f'{c} {VKB[c] / val["GDP"][c]:.2f}' for c in ct[(ct.capital_tier == 3)].code))
kyc = ct[ct.GDP_musd > 0].assign(ky=lambda d: d.VKB_musd / d.GDP_musd)
implaus = kyc[(kyc.ky < 0.5) | (kyc.ky > 8)]
S.check('S02-K2', 'Country K/GDP outside 0.5-8 (plausibility, review FR-H1)', 'report', len(implaus), 0, implaus.empty, '',
        ' '.join(f'{r.code} {r.ky:.2f} (tier {r.capital_tier})' for r in implaus.itertuples()))
usa = rg.loc['USA']
S.check('S02-K3', 'USA region K/GDP (closer US scrutiny; GTAP 12 Table 7.1 2023 USA 2.44 is an internal QA comparison only)', 'report',
        f'USA region {usa.K_over_GDP:.3f}; ' + '; '.join(f'{c} {VKB[c] / val["GDP"][c]:.3f} ({ksrc[c]})' for c in ct[ct.region == 'USA'].code), '-', True, 'GTAP 12 ch.7 Table 7.1 (QA only)')
t1 = [c for c in ct.code if kinfo.get(c, (0,))[0] == 1]
mv = pd.Series({c: VKB[c] / val['GDP'][c] / kinfo[c][2] - 1 for c in t1}).sort_values()
nrv = {b: sum(f'revalued by {b} deflator' in ksrc[c] for c in t1) for b in ('gfcf', 'gdp', 'gdp+gfcf')}
S.check('S02-K4', f'ICSD roll-forward: K/GDP used against the latest ICSD ratio; re-base beyond the band ({KCH["capital_rebase_band"]["value"]}), '
        f'revaluation {KREVAL} (fix round 3, P10)', 'report',
        f'{len(REBASED)} re-based; move median {mv.median():+.3f}, min {mv.min():+.3f} ({mv.index[0]}), max {mv.max():+.3f} ({mv.index[-1]})', '-', True,
        'GTAP 12 ch.7 s7.3; config/s02/s02_choices.csv',
        f'revaluation basis (countries): gfcf {nrv["gfcf"]}, gdp {nrv["gdp"]}, mixed {nrv["gdp+gfcf"]}. Re-based: ' +
        (' '.join(f'{c} (ICSD {y} {k0:.2f}, rolled {kr:.2f})' for c, (y, k0, kr) in sorted(REBASED.items())) or 'none'))
ky = rg.K_over_GDP
S.check('S02-R2', 'Region K/GDP outside 1-6', 'report', int(((ky < 1) | (ky > 6)).sum()), 0, ((ky >= 1) & (ky <= 6)).all(), '',
        ' '.join(f'{r} {v:.2f}' for r, v in ky[(ky < 1) | (ky > 6)].items()))
cg = (rg.C_musd + rg.G_musd + rg.GFCF_musd) / rg.GDP_musd
S.check('S02-R3', 'Region (C+G+GFCF)/GDP outside 0.6-1.4 (implied net exports + inventories large)', 'report', int(((cg < .6) | (cg > 1.4)).sum()), 0,
        ((cg >= .6) & (cg <= 1.4)).all(), '', ' '.join(f'{r} {v:.2f}' for r, v in cg[(cg < .6) | (cg > 1.4)].items()))
wa = wacc[wacc.year == Y].set_index('countrycode')
wld = w22.loc['WLD', WS['GDP']] / 1e6 if 'WLD' in w22.index else np.nan
r4 = rg.GDP_musd.sum() / wld if np.isfinite(wld) else np.nan
S.check('S02-R4', 'World GDP (sum of 167 regions) / WDI world GDP', 'report', f'{r4:.5f}', '|1 - ratio| <= 0.001', bool(np.isfinite(r4) and abs(1 - r4) <= 1e-3), 'C14',
        'WLD includes World Bank estimates for economies without published GDP, so a small residual is expected.')
# H5 (review S01-M5 / S02-M2): no WDI economy with base-year GDP is dropped
wdi_econ = {c for c in w22.index if c not in NONC and np.isfinite(w22.loc[c, WS['GDP']])}
drop = sorted(c for c in wdi_econ if c not in set(C.sc))
S.check('S02-H5', f'Every WDI economy with {Y} GDP is in the universe (none dropped without David)', 'hard', len(drop), 0, not drop, 'P8',
        ' '.join(f'{c} {w22.loc[c, WS["GDP"]] / 1e6:,.0f}' for c in drop))
# BoP memo (GTAP 12 ch.7 p.3, eq.7.2) - WDI has only NET primary income and NET secondary income
memo = []
for c, r in C.iterrows():
    sc = r.sc
    if sc in wa.index:
        memo.append((c, r.region, wa.loc[sc, 'BN.GSR.FCTY.CD'] / 1e6 if pd.notna(wa.loc[sc, 'BN.GSR.FCTY.CD']) else np.nan,
                     wa.loc[sc, 'BN.TRF.CURR.CD'] / 1e6 if pd.notna(wa.loc[sc, 'BN.TRF.CURR.CD']) else np.nan))
S.write('memo_bop_net_flows.csv', memo, ['code', 'region', 'net_primary_income_musd', 'net_secondary_income_musd'])
S.flag('BOP', 'BoP flows (GTAP 12 ch.7 eq.7.2)', 'GTAP 12 reports gross FY (IMF), AID (OECD) and RM (World Bank). Only WDI NET primary and NET secondary income are on disk: written as a memo, not used. Not needed by GTAPv7 calibration (eq.7.1 S-I = X-M).', 'no', '', 'GTAP 12 ch.7 p.3')
S.flag('SAVE', 'SAVE and the full S-I gate', 'SAVE is the residual GDP - C - G and needs reconciled X - M (S07-S09); built and gated at S14. S02 gates only VDEP < GFCF.', 'no', '', 'PLAN (h) step 3; GTAP 12 ch.7 p.2')
S.flag('EAZ', 'EAZ (Zanzibar, in XEF)', 'Macro set to zero: WDI TZA already covers the United Republic incl. Zanzibar (parity). XEF keeps EAZ as a nominal member with no accounts.', 'no', 'concept parity', 'contained_in.csv')
S.flag('S07-GIB-FLK', 'GIB and FLK trade vs GDP', 'GIB (F1 per-capita GDP fill; BACI X+M about 12.6 bn USD, mostly fuel re-exports) and FLK (zero GDP; BACI about 0.5 bn, mostly fish) carry trade inside XWE and XSM with zero or small GDP. S07 must net their trade into the composites knowingly. Gibraltar official GDP (HMGoG) is an optional cited replacement for the fill.', 'no', '', 'review S02-L2')
S.flag('PRK-SHARES', 'PRK expenditure shares and K/GDP', 'PRK C, G and I shares and K/GDP come from the unweighted EAAS geographic mean, whose observed members are high-income neighbours (CHN, JPN, KOR, HKG, MAC, MNG, TWN).', 'no', 'F1/F2', 'GTAP 12 ch.7 pp.1-3; review S02-L3')
S.flag('PRI-S03', 'PRI and VIR inside USA', 'USA macro includes PRI and VIR (WDI). Per David 2026-10-20 22:02 (replaces E31 of 19:40), S03 does NOT append PRI or VIR I-O tables to ICIO USA: their GDP and trade stay in USA macro and BACI 842; the S13-S14 macro fit absorbs the gap (about 0.5% of USA GDP). Logged as a known flaw and an improvement in docs/ISSUES_AND_DECISIONS.md.', 'no', 'fix round 2', 'David 22:02; specs/S03_io_cleaning.md')
S.flag('KAPITAL-METHOD', 'Capital stock method', 'GTAP 12 ch.7 s7.3 order (David 2026-10-20 22:02, amended 22:31): IMF ICSD K/GDP in its latest year, rolled forward to the base year by perpetual inventory (4%; revalued by the implicit GFCF deflator, else the GDP deflator, and re-based to the ICSD ratio where the roll moves K/GDP beyond the band in config/s02/s02_choices.csv, flags KAPITAL-REBASE-*; fix round 3, P10), using an official series from config/s02/capital_roll_sources.csv where WDI lacks one (TWN DGBAS, ARE UN AMA); ICSD that cannot be rolled forward, and ICSD listed as unusable in config/s02/capital_icsd_unusable.csv (VEN, SYR, LBY), take the geographic average (flags KAPITAL-NOROLL, KAPITAL-UNUSABLE-*); else a perpetual inventory over the country\'s own WDI real GFCF (>= 30 years); else the geographic-average K/GDP of rolled ICSD countries, unusable values excluded. PWT K/Y x GDP is kept as memo_PWT_KY_x_GDP_musd (check S02-P6), report-only.', 'no', 'K1-K3', 'GTAP 12 ch.7 s7.3; David 22:02 and 22:31')
S.flag('KAPITAL-NOROLL', 'ICSD capital not rollable to the base year', f'{len(NOROLL)} countries have IMF ICSD capital but WDI (and config/s02/capital_roll_sources.csv) lack a series needed to roll it forward to {Y}; they take the geographic-average K/GDP, as GTAP does (David 2026-10-20 22:31): ' + ', '.join(f'{c} (ICSD {y})' for c, y in sorted(NOROLL.items())) + '.', 'no', 'F2', 'GTAP 12 ch.7 s7.3; David 22:31')
S.flag('MEAN', 'Geographic-average shares', 'GTAP ch.7 says "average share"; implemented as the unweighted mean over observed countries in the Table 9.10 geographic region.', 'no', 'F1/F2', 'GTAP 12 ch.7 pp.1-3')
for c in ct[ct.GDP_musd.eq(0) & ~ct.code.isin(CONT)].code:
    S.flag('ZERO-' + c, c, f'No GDP and no population in any source: zero (GTAP ch.7 p.2 practice). Region {C.loc[c, "region"]}.', 'no', 'F1', 'GTAP 12 ch.7 p.2')
# ---------------------------------------------------------------- items for David
md = ['# S02: items for David - RESOLVED', '',
      'Status: **resolved by David, 2026-10-20 19:25 (UTC+7): option C.**', '',
      '- Check S02-H3 (VDEP = 4% of VKB below GFCF) is now report-only, as in GTAP, whose own Table 7.1 has VDEP > GFCF (e.g. LBN).',
      '- New hard check S02-H4: every region has VKB > 0 and GFCF > 0 (strict since fix round 1).',
      '- The hard savings-investment items (SAVE > 0 and the other E12 items) stay at S14.',
      '- Carried flag CARRY-VDEP: the regions below must be tested in the aggregation calibrate-and-solve checks ("as long as depreciation doesn\'t break the model").',
      '- Logged in adjustments_ledger.csv (gate_kind_change) and PLAN_ERRATA E28.', '',
      'Options that were offered: A (keep the hard gate, cited fixes region by region), B (IMF ICSD as primary capital source), C (report-only, chosen).', '',
      '| Region | VDEP/GFCF | K/GDP |', '|---|---|---|']
for r, v in bad.sort_values('VDEP_over_GFCF', ascending=False).iterrows():
    md.append(f'| {r} | {v.VDEP_over_GFCF:.2f} | {v.K_over_GDP:.2f} |')
open(S.dir + '/NEEDS_DAVID.md', 'w').write('\n'.join(md) + '\n')
ok = S.finish()
print('HARD PASS' if ok else 'HARD FAIL (no STAMP)')
