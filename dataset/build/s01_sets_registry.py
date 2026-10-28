"""S01 sets and registry (GTAP 12 ch.17B pp.1-3: stage 1 = sets, mappings, input registry).
Builds: final 167-region list, country->region map, GTAP geographic regions (ch.9D Table 9.10),
51 sectors, concordances (ICIO50->51, HS17->51, HS22->51, EBOPS->51, ISIC->51, ISCO->labour groups),
and an input manifest with SHA-256. No numbers are changed at S01; flags go to flags.csv.
Region rule (David): never fold or drop a country without asking. Unmapped source codes = hard FAIL."""
import os, sys, re, csv, io, zipfile, subprocess, collections
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/lib')
from stagekit import Stage, DATA, ROOT, BUILD, BASE_YEAR, sha256
Y = BASE_YEAR

CFG = os.path.dirname(os.path.abspath(__file__)) + '/config/s01'
LIT = ROOT + '/docs/literature'
S = Stage('S01', 'sets_registry')
I = S.inp

# ---------------------------------------------------------------- inputs
cl = DATA + '/classifications'
countries = pd.read_csv(I(cl + '/countries_2022.csv', 'inherited 168-region list (an earlier internal build)'))
rest = pd.read_csv(I(cl + '/rest_of_locked.csv', 'inherited composite membership (an earlier internal build)'))
I(cl + '/rest_of_notes.md', 'reasons for inherited folds (cited)')
ind = pd.read_csv(I(cl + '/industry_codes.csv', '51 sectors = ICIO 2025 50 + B06 split'))
hs17 = pd.read_csv(I(cl + '/hs6_to_icio51.csv', 'HS6 -> 51 sector links (pr54, UNSD HS-CPC-ISIC)'), dtype=str)
tieb = pd.read_csv(I(CFG + '/hs6_tiebreak.csv', 'config: HS6 tie-break (one-to-one, David 19:40)'), dtype=str).fillna('')
ovr = pd.read_csv(I(CFG + '/hs6_override_codes.csv', 'config: explicit list of HS6 override codes (David 22:02; review FR-L2/L4)'), dtype=str).fillna('')
OVR = {r.hs6: r.sector for r in ovr.itertuples() if r.approved_by == 'David'}
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s01_sets import hs_override, hs22_parents  # noqa: E402
SOV_PATH = I(CFG + '/hs6_sector_override.csv', 'config: HS6 sector overrides of single-link codes that follow GTAP HS->GSEC3 (fix round B13 and QA F-12: waste and scrap)')
g65 = pd.read_csv(I(CFG + '/gtap65_to_sector.csv', 'config: GTAP 65 -> our 51 (data-round/sectors_vs_gtap.md)'))
gtapc = I(DATA + '/gtap_hs_concordance/GTAP_HS_to_GSEC3_concordance_11723.xlsx', 'GTAP HS6 -> GSEC3 concordance (report-only comparison)')
cont = pd.read_csv(I(BUILD + '/config/s02/contained_in.csv', 'config: codes whose accounts are contained in another country'))
dec = pd.read_csv(I(CFG + '/region_decisions.csv', 'config: David decisions 2026-10-20'))
tf = pd.read_csv(I(CFG + '/territory_folds.csv', 'config: inherited territory folds'))
ali = pd.read_csv(I(CFG + '/source_aliases.csv', 'config: source code aliases'))
ncc = pd.read_csv(I(CFG + '/non_country_codes.csv', 'config: non-country aggregates'))
pri = pd.read_csv(I(CFG + '/priority_lists.csv', 'config: priority lists'))
tdec = pd.read_csv(I(CFG + '/territory_decisions.csv', 'config: David territory assignments 2026-10-20 19:03 and 19:40'))
TERR = tdec.groupby('into').code.apply(list).to_dict()
gpar = pd.read_csv(I(CFG + '/geo_parent.csv', 'config: geo parent for codes not in Table 9.10'))
isco = pd.read_csv(I(CFG + '/isco_labour_groups.csv', 'config: ISCO -> labour groups'), dtype=str)
ebops = pd.read_csv(I(CFG + '/ebops_to_sector.csv', 'config: EBOPS -> sectors'), dtype=str).fillna('')
pdf910 = I(LIT + '/gtap12/GTAP12_ch09D_representative_table_composite_regions.pdf', 'GTAP 12 ch.9D Table 9.10 (geographic regions)')
I(LIT + '/gtap12/GTAP12_ch10B_services_trade.pdf', 'GTAP 12 ch.10B Tables 10.1-10.2 (cited)')
I(LIT + '/gtap12/GTAP12_ch14B_labor_payments.pdf', 'GTAP 12 ch.14B Table 14.18 (cited)')
baci17 = I(DATA + '/baci/BACI_HS17_V202601.zip', f'BACI HS17 ({Y} year file, codes)')
baci22 = I(DATA + '/baci/BACI_HS22_V202601.zip', 'BACI HS22 (product codes)')
conv = I(DATA + '/unsd_hs_correlation/HS2022toHS2017ConversionAndCorrelationTables.xlsx', 'UNSD HS2022->HS2017 conversion')
batis = I(DATA + f'/oecd_wto_batis/ebops{Y}.csv', f'BaTIS {Y} EBOPS detail (codes, world total)')
itic = I(DATA + f'/oecd_itic/ITIC_total_{Y}.csv', f'ITIC {Y} (codes)')
icio = I(DATA + f'/oecd_icio/{Y}_SML.csv', f'OECD ICIO 2025 {Y} (codes)')
ama = I(DATA + f'/unsd_ama/expenditure_{Y}.csv', f'UNSD AMA {Y} GDP (top-50 ranking; code scan)')
wdi = I(DATA + '/wdi/wdi_2017_2022_extract.csv', 'WDI extract (code scan: economies with GDP)')
pwtf = I(DATA + '/pwt/pwt110_ky_labsh.csv', 'PWT 11.0 (code scan)')
dgx = I(DATA + f'/dgbas_twn/dgbas_gdp_expenditure_{Y}_extract.csv', f'DGBAS TWN {Y} GDP (top-50 ranking incl. TWN)')
cbcf = I(DATA + '/cbc_twn_fx/cbc_BP01Y01_annual_fx.json', 'CBC NT$/US$ (TWN ranking)')
tismos = I(DATA + '/wto_tismos/gstdh_mode_supply_e.zip', 'TiSMoS (codes)')
mani = DATA + '/MANIFEST.csv'   # read for this stage's own rows only (review S01-M1); the global audit is build/check_manifest.py

# ---------------------------------------------------------------- GTAP Table 9.10
txt = subprocess.run(['pdftotext', '-layout', '-f', '3', '-l', '9', pdf910, '-'], capture_output=True, text=True).stdout
txt = txt[txt.index('Table 9.10:'):]
geo, cur = [], None
for line in txt.splitlines():
    m = re.match(r'^\s*([A-Z]{4})\s+\S', line)
    if m and m.group(1) not in ('CODE',):
        cur = m.group(1)
    m2 = re.search(r'\s([a-z]{3})\s*$', line)
    if m2 and cur:
        name = re.sub(r'^\s*[A-Z]{4}\s+\S+(\s\S+)*?\s{2,}', '', line[:m2.start()]).strip()
        geo.append((m2.group(1).upper(), cur, name))
geo = pd.DataFrame(geo, columns=['iso3', 'gtap_geo', 'name_gtap']).drop_duplicates('iso3')
S.log(f'Table 9.10 parsed: {len(geo)} codes in {geo.gtap_geo.nunique()} geographic regions')
S.check('S01-G1', 'GTAP Table 9.10 parsed: 19 geographic regions', 'hard', geo.gtap_geo.nunique(), 19, geo.gtap_geo.nunique() == 19, 'ch.9D p.2 Table 9.9')
S.check('S01-G2', 'GTAP Table 9.10 country count vs 251 in text', 'report', len(geo), 251, len(geo) == 251, 'ch.9D p.2',
        'The text says 251 standard countries; the table as printed lists %d distinct 3-letter codes. Sark is printed with the 4-letter code "sark", which the 3-letter parser skips by design (no Sark data in any source), so 250 is expected.' % len(geo))
GEO = dict(zip(geo.iso3, geo.gtap_geo))
for _, g in gpar.iterrows():
    GEO[g.code] = GEO[g.parent]; S.log(f'geo: {g.code} takes {GEO[g.parent]} from parent {g.parent}')

# ---------------------------------------------------------------- regions (apply decisions)
members = collections.OrderedDict()
for g, m in rest.values:
    members.setdefault(g, []).append(m)
singles = [c for c in countries.code if c not in members]
for _, d in dec.iterrows():
    if d.action == 'split_out':
        members[d.from_group].remove(d.code); singles.append(d.code)
        S.log(f'decision: split {d.code} out of {d.from_group} ({d.decided_by} {d.date_utc7})')
    elif d.action == 'fold':
        singles.remove(d.code); members[d.into].append(d.code)
        S.log(f'decision: fold {d.code} into {d.into} ({d.decided_by} {d.date_utc7})')
names = {k: (v if isinstance(v, str) and v else '') for k, v in zip(countries.code, countries.name)}
bcc = pd.read_csv(zipfile.ZipFile(baci17).open('country_codes_V202601.csv'), keep_default_na=False)
def _fixenc(x):
    try: return x.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError): return x
bcc['country_name'] = bcc.country_name.map(_fixenc)   # review S01-L8: file holds double-encoded UTF-8
GNAME910 = dict(zip(geo.iso3, geo.name_gtap))
bname = dict(zip(bcc.country_iso3, bcc.country_name))
for k, v in GNAME910.items():
    if k not in bname or not bname[k] or '...' in bname[k]: bname[k] = v   # e.g. 'Sudan (...2011)' -> Table 9.10 name
names_extra = {'EAZ': 'Zanzibar', 'CHI': 'Channel Islands', 'KSV': 'Kosovo', 'LIE': 'Liechtenstein', 'MCO': 'Monaco', 'FRO': 'Faroe Islands'}
for k, v in names_extra.items(): bname.setdefault(k, v); bname[k] = bname[k] or v
for c in singles:
    names[c] = names.get(c) or bname.get(c, c)
icio_codes = sorted({x.split('_')[0] for x in pd.read_csv(icio, usecols=[0]).iloc[:, 0] if '_' in x})
icio_set = set(icio_codes) - {'ROW'}
GNAME = {'XCB': 'Rest of Caribbean', 'XEF': 'Rest of Eastern Africa', 'XNA': 'Rest of North America', 'XNF': 'Rest of North Africa (Sudan)',
         'XOC': 'Rest of Oceania', 'XSM': 'Rest of South America', 'XWB': 'Rest of Western Balkans', 'XWE': 'Rest of Western Europe'}
# alias region code -> iso3 used in GTAP table
REG_ISO = {'PAL': 'PSE', 'KSV': 'XKX'}
reg_rows = []
for c in sorted(singles):
    iso = REG_ISO.get(c, c)
    reg_rows.append(dict(region=c, name=names[c], type='single', n_members=1, members=c, gtap_geo=GEO.get(iso, ''),
                         icio_measured=('yes' if c in icio_set else 'no'), territories=' '.join(TERR.get(c, []))))
for g, ms in members.items():
    geos = sorted({GEO.get(REG_ISO.get(m, m), '?') for m in ms})
    reg_rows.append(dict(region=g, name=GNAME[g], type='composite', n_members=len(ms), members=' '.join(ms), gtap_geo='+'.join(geos),
                         icio_measured=('partly: ' + ' '.join(m for m in ms if m in icio_set)) if any(m in icio_set for m in ms) else 'no',
                         territories=' '.join(TERR.get(g, []))))
regions = pd.DataFrame(reg_rows)
# priority flags
gdp = pd.read_csv(ama)
gdp = gdp[gdp.iso3.str.len() == 3]
# review S01-L6: TWN has no AMA row; add DGBAS GDP / CBC rate so the ranking covers it
import json as _json
_fx = {r[0]: float(r[1]) for r in _json.load(open(cbcf))['data']['dataSets']}[str(Y)]
_dg = pd.read_csv(dgx)
_twn = float(_dg[(_dg.TIME_PERIOD == Y) & (_dg.Item == '當期價格(新臺幣百萬元)、8.GDP')].Item_VALUE.iloc[0]) / _fx
rank = pd.concat([gdp[['iso3', 'gdp_million_usd']], pd.DataFrame({'iso3': ['TWN'], 'gdp_million_usd': [_twn]})]).sort_values('gdp_million_usd', ascending=False)
top50 = list(rank.iso3.head(50))
S.log(f'top 50 by UNSD AMA {Y} GDP plus TWN (DGBAS/CBC {_twn:,.0f} USD m): ' + ' '.join(top50))
pl = pri.groupby('code').group.apply(lambda s: ';'.join(sorted(s))).to_dict()
regions['priority'] = [';'.join(filter(None, [('top50' if r in top50 else ''), pl.get(r, '')])) for r in regions.region]
regions.loc[regions.region == 'PRK', 'flag'] = 'kept single; data very thin (David 2026-10-20)'
regions.loc[regions.region == 'TWN', 'flag'] = 'BACI code 490/S19 (F6); absent from WDI/AMA; DGBAS controls'
regions['flag'] = regions['flag'].fillna('')
n_s, n_c = (regions.type == 'single').sum(), (regions.type == 'composite').sum()
S.check('S01-R1', 'Final region count = 167 (David)', 'hard', len(regions), 167, len(regions) == 167 and regions.region.is_unique, 'P8')
S.check('S01-R2', 'Singles / composites', 'report', f'{n_s} / {n_c}', '159 / 8', (n_s, n_c) == (159, 8))
allm = [m for ms in members.values() for m in ms]
S.check('S01-R3', 'Composite members disjoint and not also single regions', 'hard', len(allm) - len(set(allm)) + len(set(allm) & set(singles)), 0,
        len(allm) == len(set(allm)) and not (set(allm) & set(singles)))
nogeo = list(regions[regions.gtap_geo.str.contains(r'\?|^$', regex=True)].region)
S.check('S01-R4', 'Every region has a GTAP geographic region (Table 9.10)', 'hard', len(nogeo), 0, not nogeo, 'ch.9D Table 9.10', ' '.join(nogeo))
mixed = regions[(regions.type == 'composite') & regions.gtap_geo.str.contains(r'\+')]
S.check('S01-R5', 'Composites whose members span several GTAP geographic regions', 'report', len(mixed), 0, mixed.empty, 'ch.9D D.3',
        '; '.join(f'{r.region}: {r.gtap_geo}' for r in mixed.itertuples()) + ' (inherited groups, approved as they stand; matters for the S05 composite I-O donor choice)')
must = set(top50) | set(pri[pri.group.isin(['gulf', 'opec_2022'])].code)
must_alias = {REG_ISO_inv: k for k, REG_ISO_inv in REG_ISO.items()}
bad = sorted(c for c in must if must_alias.get(c, c) not in set(singles))
S.check('S01-R6', f'Top-50 economies (AMA {Y} + TWN), Gulf 8 and OPEC-2022 members are single regions', 'hard', len(bad), 0, not bad, 'standing rule', ' '.join(bad))
pp = sorted(c for c in pri[pri.group == 'opec_plus_partner'].code if c not in singles)
S.check('S01-R7', 'OPEC+ partner countries inside composites', 'report', ' '.join(pp) or 'none', 'none', not pp, 'standing rule',
        'Inside composites: ' + ', '.join(f'{c} ({next(g for g, ms in members.items() if c in ms)})' for c in pp) + '. These are approved inherited folds; listed for David\'s information.')
S.check('S01-R8', 'ICIO 2025 economies all map to a region (ROW excluded)', 'hard',
        len([c for c in icio_set if c not in singles and c not in allm]), 0, all(c in singles or c in allm for c in icio_set))
S.write('regions.csv', regions)
S.write('composite_members.csv', [(g, i + 1, m, names.get(m, bname.get(m, '')), GEO.get(REG_ISO.get(m, m), ''), 'host' if i == 0 else '')
                                   for g, ms in members.items() for i, m in enumerate(ms)] +
        [(g, len(members[g]) + k + 1, t, bname.get(t, ''), GEO.get(t, ''), 'territory (David 2026-10-20 19:03)') for g in members for k, t in enumerate(TERR.get(g, []))],
        ['composite', 'order', 'member', 'name', 'gtap_geo', 'role'])
geo['in_region'] = ''
S.write('gtap_geo_regions_table910.csv', geo[['iso3', 'gtap_geo', 'name_gtap']])

# ---------------------------------------------------------------- country -> region map and source scan
R = {c: c for c in singles}
for g, ms in members.items():
    for m in ms: R[m] = g
basis = {c: 'single' for c in singles}
basis.update({m: 'composite member' for m in allm})
for _, t in tf.iterrows():
    tgt = R[t['into']]; R[t.code] = tgt; basis[t.code] = f'territory fold -> {t["into"]} -> {tgt}'
for _, t in tdec.iterrows():
    assert t.code not in R, t.code
    R[t.code] = t['into']; basis[t.code] = f'territory assigned -> {t["into"]} (David {t.date_utc7})'
    S.adjust(t['into'], f'region membership: {t.code}', 'unmapped', t['into'], f'P8 decision by David {t.date_utc7}',
             f'{t.reference}; GTAP 12 ch.9D Table 9.10 (p.3-9)', 'territory_assignment')
    S.log(f'territory: {t.code} -> {t["into"]} (David {t.date_utc7})')
AL = {}
for _, a in ali.iterrows():
    AL[a.code] = a.iso3
NONC = set(ncc.code) | {''}
CONTAINED = dict(zip(cont.code, cont.parent))
def to_region(code):
    c = AL.get(code, code)
    c = {'PSE': 'PAL', 'XKX': 'KSV'}.get(c, c)
    return R.get(c), c

seen = collections.defaultdict(set)
vol = collections.Counter()
# BACI HS17 base year
z = zipfile.ZipFile(baci17)
BFILE = f'BACI_HS17_Y{Y}_V202601.csv'
if BFILE not in z.namelist(): raise SystemExit(f'{BFILE} not in {baci17} (base year {Y})')
b = pd.read_csv(z.open(BFILE), usecols=['i', 'j', 'k', 'v'], dtype={'k': str})
num2iso = dict(zip(bcc.country_code, bcc.country_iso3))
S.log(f'BACI HS17 {Y} rows {len(b):,}; total {b.v.sum()/1e6:,.0f} USD bn')
for col in ('i', 'j'):
    s = b.groupby(col).v.sum()
    for n, v in s.items():
        iso = num2iso.get(n, f'BACI#{n}'); seen[iso].add('BACI'); vol[iso] += v
bat = pd.read_csv(batis, usecols=['REF_AREA', 'COUNTERPART_AREA', 'OBS_VALUE'])
for col in ('REF_AREA', 'COUNTERPART_AREA'):
    for c in bat[col].unique(): seen[c].add('BaTIS')
it = pd.read_csv(itic, usecols=['REF_AREA', 'COUNTERPART_AREA'])
for col in ('REF_AREA', 'COUNTERPART_AREA'):
    for c in it[col].unique(): seen[c].add('ITIC')
for c in icio_codes: seen[c].add('ICIO')
for c in gdp.iso3: seen[c].add('AMA')
# review S01-M5: scan WDI and PWT too, so no economy with GDP is silently dropped
wd = pd.read_csv(wdi, keep_default_na=False)
wg = wd[(wd.series == 'NY.GDP.MKTP.CD') & (wd.year == Y) & (wd.value != '')]
WDI_GDP = dict(zip(wg.iso3, pd.to_numeric(wg.value)))
for c in set(wd.iso3) - {''}: seen[c].add('WDI')
pw = pd.read_csv(pwtf)
PWT_GDP = pw[pw.year == Y].set_index('countrycode').eval('cgdpo * pl_gdpo').to_dict()
for c in pw.countrycode.unique(): seen[c].add('PWT')
AMA_GDP = dict(zip(gdp.iso3, gdp.gdp_million_usd))
iso2 = dict(zip(bcc.country_iso2, bcc.country_iso3))
with zipfile.ZipFile(tismos) as tz:
    trep = pd.read_csv(tz.open('TiSMoS - Exports.csv'), usecols=['REPORTER_CODE', 'YEAR', 'INDICATOR'], encoding='utf-8-sig', keep_default_na=False, dtype={'REPORTER_CODE': str})
tis_codes = set(trep.INDICATOR)
for c in trep[trep.YEAR == Y].REPORTER_CODE.unique():
    seen[iso2.get(c, f'TiSMoS:{c}')].add('TiSMoS')
universe = sorted(set(geo.iso3) | set(R) | set(seen))
rows = []
for c in universe:
    reg, canon = to_region(c)
    srcs = seen.get(c, set())
    if c in NONC: st = 'non-country aggregate (excluded)'
    elif reg: st = basis.get(canon, 'alias') if canon == c else f'alias -> {canon}'
    elif srcs & {'BACI', 'BaTIS', 'WDI', 'PWT', 'AMA', 'ICIO'}: st = 'UNMAPPED (in sources; needs David)'
    elif srcs: st = 'ITIC/TiSMoS-only; reported inside the parent or absent in BACI/BaTIS; rates unused'   # review S01-L4
    else: st = 'not in any scanned source'
    if c in CONTAINED and reg: st = f'contained in {CONTAINED[c]} (accounts zero; nominal member of {reg})'   # review S01-L3
    rows.append(dict(code=c, name=bname.get(c, names.get(c, dict(zip(geo.iso3, geo.name_gtap)).get(c, ''))), gtap_geo=GEO.get(c, GEO.get(canon, '')),
                     region=reg or '', status=st, sources=';'.join(sorted(seen.get(c, []))), baci_x_plus_m_kusd=round(vol.get(c, 0), 1)))
cmap = pd.DataFrame(rows)
S.write('country_region_map.csv', cmap)
un = cmap[(cmap.region == '') & ~cmap.status.str.startswith(('non-country', 'not in any'))].sort_values('baci_x_plus_m_kusd', ascending=False)
for src, kind in [('BACI', 'hard'), ('BaTIS', 'hard'), ('ITIC', 'report'), ('TiSMoS', 'report'), ('AMA', 'hard'), ('WDI', 'hard'), ('PWT', 'hard')]:
    u = un[un.sources.str.contains(src)]
    if src in ('WDI', 'PWT', 'AMA'):   # an economy with GDP in any of these must map (review S01-M5)
        G = {'WDI': WDI_GDP, 'PWT': PWT_GDP, 'AMA': AMA_GDP}[src]
        u = u[u.code.map(lambda x: G.get(x, 0) or 0) != 0]
    det = '; '.join(f'{r.code} {r.name} [{r.gtap_geo}] BACI {r.baci_x_plus_m_kusd/1000:,.2f} USD m' for r in u.itertuples())
    S.check(f'S01-M-{src}', f'Every {src} {Y} country code' + (' with nonzero GDP' if src in ('WDI', 'PWT', 'AMA') else '') + ' maps to a region (or is a listed non-country aggregate)', kind, len(u), 0, u.empty, 'P8: no fold without David', det)
tot = sum(vol.values()); share = un.baci_x_plus_m_kusd.sum() / tot if tot else 0
S.check('S01-M-size', f'Share of BACI {Y} trade (X+M) in unmapped codes', 'report', f'{share:.5%}', '0', share == 0)
nis = cmap[cmap.status == 'not in any scanned source']
S.check('S01-M-gtap', 'GTAP Table 9.10 codes found in no scanned source (reported inside parent country by the sources, or no data)', 'report', len(nis), 0, nis.empty,
        'ch.9D Table 9.10', ' '.join(nis.code))

# ---------------------------------------------------------------- sectors
ind = ind.rename(columns={'code': 'sector', 'oecd_code': 'icio_code'})
ind['note'] = ind.sector.map({'ely': 'ICIO D = ISIC 35: electricity AND gas manufacture/distribution (GTAP ely + gdt)', 'rle': 'includes ownership of dwellings (GTAP dwe)'}).fillna('')
S.write('sectors.csv', ind)
SECT = set(ind.sector); OECD2S = dict(zip(ind.icio_code, ind.sector))
S.check('S01-S1', 'Sector count = 51, unique', 'hard', len(ind), 51, len(ind) == 51 and ind.sector.is_unique)
icio_ind = sorted({x.split('_', 1)[1] for x in pd.read_csv(icio, usecols=[0]).iloc[:, 0] if '_' in x} - {'OUT', 'TLS', 'VA'})
crow = []
for c in icio_ind:
    if c == 'B06':
        crow += [(c, 'oil', '', 'deferred:S11', 'output value split at S11 (GTAP 12 ch.12; PLAN (b1) item 7)'), (c, 'gas', '', 'deferred:S11', 'output value split at S11')]
    else:
        crow.append((c, OECD2S[c], 1.0, 'set', 'identity'))
cic = pd.DataFrame(crow, columns=['icio_code', 'sector', 'share', 'share_status', 'basis'])
S.write('concord_icio_to_sector.csv', cic)
S.check('S01-S2', 'ICIO 2025 industries (50) all map; every sector reached', 'hard', f'{len(icio_ind)} ind, {cic.sector.nunique()} sectors', '50, 51',
        len(icio_ind) == 50 and set(cic.sector) == SECT and set(cic[cic.share == ''].icio_code) == {'B06'} and (cic[cic.share == ''].share_status == 'deferred:S11').all(),
        '', 'Only B06 (oil, gas) has no share; its status is deferred:S11 (review S01-L1).')
S.flag('B06', 'B06 Mining of energy products', 'Split into oil and gas by output value at S11; shares not set at S01.', 'no', 'plan (g)', 'GTAP 12 ch.12')

# HS17: one-to-one mapping (David 2026-10-20 19:40; GTAP practice: Aguiar et al. 2025 p.13 and fn.11)
# Rule 1: the dominant UNSD HS-CPC-ISIC link (largest link share). Rule 2: ties -> config/s01/hs6_tiebreak.csv,
# used only where status == 'approved'. Any HS6 still multi-sector is a hard FAIL (no even splits).
hs17['split_share'] = hs17.split_share.astype(float)
hs17['sector'] = hs17.sector_code.map(lambda x: OECD2S.get(x, x))
bads = set(hs17.sector) - SECT
ssum = hs17.groupby('hs6').split_share.sum()
S.check('S01-H1', 'HS6 link file: every row has a valid sector; link shares sum to 1 per HS6', 'hard', f'{len(bads)} bad sectors; {(abs(ssum-1)>1e-6).sum()} bad sums', 0,
        not bads and (abs(ssum - 1) <= 1e-6).all())
SOV = hs_override.load(SOV_PATH, SECT)   # fix round B13: applied before the link rules, checked in S01-H1f
TB = {r.hs6: r for r in tieb.itertuples()}
S2OECD = {v: k for k, v in OECD2S.items()}
one, unres = [], []
TIE_TOL = 1e-4   # fix round 2 (David 2026-10-20 22:02): compare link shares with a tolerance, not exact float equality
for k, d in hs17.groupby('hs6', sort=True):
    links = ';'.join(f'{x}:{v:.3f}' for x, v in zip(d.sector, d.split_share))
    if k in SOV:   # fix round B13: a sector override of a non-tie code, following GTAP HS->GSEC3
        o = SOV[k]
        one.append((k, d.hs6_description.iloc[0], o['sector'], S2OECD[o['sector']], 1.0, f'override (fix round B13, {o["decided_at"]}): GTAP {o["gtap_gsec3"]} in place of the UNSD link {o["unsd_sector"]}', links, d.source.iloc[0], d.notes.iloc[0])); continue
    if len(d) == 1:
        one.append((k, d.hs6_description.iloc[0], d.sector.iloc[0], d.sector_code.iloc[0], 1.0, 'single link', links, d.source.iloc[0], d.notes.iloc[0])); continue
    # links within TIE_TOL of the largest share are tied (fix round 2: three-way splits are stored 0.333334/0.333333/0.333333)
    top = d[d.split_share >= d.split_share.max() - TIE_TOL]
    if len(top) == 1:
        one.append((k, d.hs6_description.iloc[0], top.sector.iloc[0], top.sector_code.iloc[0], 1.0, f'dominant link ({top.split_share.iloc[0]:.3f} of {len(d)} links)', links, d.source.iloc[0], d.notes.iloc[0])); continue
    t = TB.get(k)
    # an override (sector outside the tied links) is accepted only for codes on the explicit David list, with the listed sector
    if t is not None and t.status == 'approved' and t.approved_by == 'David' and t.sector in SECT and (t.sector in set(top.sector) or OVR.get(k) == t.sector):
        one.append((k, d.hs6_description.iloc[0], t.sector, S2OECD[t.sector], 1.0, f'tie-break (approved {t.approved_by} {t.approved_date_utc7}): {t.rule}', links, d.source.iloc[0], d.notes.iloc[0]))
    else:
        unres.append((k, links, t.status if t is not None else 'no tie-break row'))
h1 = pd.DataFrame(one, columns=['hs6', 'hs6_description', 'sector', 'icio_code', 'share', 'basis', 'links', 'source', 'notes'])
p17 = pd.read_csv(z.open('product_codes_HS17_V202601.csv'), dtype=str)
k22 = set(b.k)
miss_p = sorted(set(p17.code) - set(hs17.hs6)); miss_k = sorted(k22 - set(hs17.hs6))
S.check('S01-H2', f'Every HS6 code traded in the BACI HS17 {Y} file is in the concordance', 'hard', len(miss_k), 0, not miss_k, '', ' '.join(miss_k[:50]))
S.check('S01-H2b', f'BACI HS17 product-list codes not in the concordance (no {Y} trade)', 'report', len(miss_p), 0, not miss_p, '',
        ' '.join(miss_p[:50]) + f' (999999 is the BACI residual code; it carries no {Y} trade in the HS17 file)')
multi = hs17.groupby('hs6').size(); multi = multi[multi > 1].index
kv = b.groupby('k').v.sum()
S.check('S01-H1b', 'One-to-one: every HS6 maps to exactly one sector with share 1 (no even splits; ties need an approved tie-break)', 'hard',
        f'{len(unres)} unresolved of {len(multi)} multi-link codes', 0, not unres and h1.hs6.is_unique and len(h1) == hs17.hs6.nunique(),
        'David 2026-10-20 19:40; READINESS S01 gate; Aguiar et al. 2025 p.13 fn.11',
        '; '.join(f'{k} [{l}] {st}' for k, l, st in unres) + (' -> see config/s01/hs6_tiebreak.csv and NEEDS_DAVID.md' if unres else ''))
# fix round 2: no code labelled 'dominant' may have its top two link shares within TIE_TOL (independent recount)
gap = hs17[hs17.hs6.isin(multi)].groupby('hs6').split_share.apply(lambda v: sorted(v, reverse=True)[0] - sorted(v, reverse=True)[1])
domc = set(h1[h1.basis.str.startswith('dominant')].hs6)
neardom = sorted(c for c in domc if gap[c] < TIE_TOL)
S.check('S01-H1c', f'No dominant-link code has its top two link shares within {TIE_TOL:g} (ties go to the approved tie-break)', 'hard', len(neardom), 0, not neardom,
        'fix round 2 (David 22:02)', f'dominant {len(domc)}, ties {int((gap < TIE_TOL).sum())} ' + ' '.join(neardom))
nb = h1.basis.str.split(' ').str[0].value_counts().to_dict()
S.check('S01-H3', 'HS6 codes with several UNSD HS-CPC-ISIC links, resolved one-to-one', 'report', len(multi), '-', True, '',
        f'{len(multi)} codes with several links ({kv.reindex(multi).fillna(0).sum()/kv.sum():.2%} of BACI {Y} value). Resolution: ' + ', '.join(f'{x}: {v}' for x, v in nb.items()))
# report-only comparison with GTAP's own HS6 concordance (GTAP GSEC3_rev), mapped through gtap65_to_sector
def _g(sheet, col):
    g = pd.read_excel(gtapc, sheet_name=sheet, header=1, dtype=str)
    return dict(zip(g.iloc[:, 1], g.iloc[:, col].str.upper().str.replace('_', '')))
GT = [_g('H5', 5), _g('H6', 4), _g('H4', 5)]
G2S = dict(zip(g65.gtap_code.str.upper().str.replace('_', ''), g65.sectors))
def _gs(k):
    return next((g[k] for g in GT if k in g), '')
h1['gtap_gsec3'] = h1.hs6.map(_gs)
h1['agrees_with_gtap'] = [('n/a' if not gs else ('yes' if sec in G2S.get(gs, '').split(';') else 'no')) for sec, gs in zip(h1.sector, h1.gtap_gsec3)]
dis = h1[h1.agrees_with_gtap == 'no']
# fix round 2 (review FR-L2/L4): the override rows equal the explicit list, every override follows GTAP's list, and no tie-break row is unused
ovr_used = {r.hs6: r.sector for r in h1.itertuples() if r.basis.startswith('tie-break') and r.sector not in {x.split(':')[0] for x in r.links.split(';')}}
ovr_bad = sorted(set(ovr_used.items()) ^ set(OVR.items())) + sorted(c for c, sct in OVR.items() if sct not in G2S.get(_gs(c), '').split(';'))
S.check('S01-H1d', 'HS6 overrides (sector outside the UNSD links) equal config/s01/hs6_override_codes.csv and each follows GTAP HS->GSEC3', 'hard', len(ovr_bad), 0, not ovr_bad,
        'David 22:02; review FR-L2', 'overrides: ' + ' '.join(f'{c}->{v}' for c, v in sorted(ovr_used.items())) + ('; mismatches: ' + str(ovr_bad) if ovr_bad else ''))
sov_bad = hs_override.check(dict(zip(h1.hs6, h1.sector)), hs17.groupby('hs6').sector.apply(set).to_dict(), {k: _gs(k) for k in h1.hs6},
                             {k: set(v.split(';')) for k, v in G2S.items()}, SOV)
S.check('S01-H1f', 'HS6 sector overrides of non-tie codes (config/s01/hs6_sector_override.csv, fix round B13 and QA F-12): each row is applied, replaces its UNSD link, follows GTAP HS->GSEC3, and every HS17 code of an overridden heading maps to that sector', 'hard',
        len(sov_bad), 0, not sov_bad, 'fix round B13 (QA#17); GTAP HS->GSEC3 (Aguiar et al. 2025 fn.11)',
        'overrides: ' + ' '.join(f'{k}->{r["sector"]}' for k, r in sorted(SOV.items())) + (f'; world BACI {Y} value moved {kv.reindex(list(SOV)).fillna(0).sum()/1e6:,.1f} bn' ) + ('; problems: ' + '; '.join(sov_bad) if sov_bad else ''))
tused = set(h1[h1.basis.str.startswith('tie-break')].hs6)
tunused = sorted(set(tieb.hs6) - tused)
S.check('S01-H1e', 'Every tie-break row is used (no row for a code that is not a tie)', 'hard', len(tunused), 0, not tunused, 'review FR-L2', ' '.join(tunused))
S.check('S01-H3g', 'HS6 -> sector differs from GTAP HS->GSEC3 (mapped through sectors_vs_gtap.md)', 'report', len(dis), 0, dis.empty, 'Aguiar et al. 2025 fn.11',
        f'{len(dis)} of {len(h1)} codes ({kv.reindex(dis.hs6).fillna(0).sum()/kv.sum():.2%} of BACI {Y} value); {(h1.agrees_with_gtap == "n/a").sum()} codes not in the GTAP file. Largest by value: ' +
        ', '.join(f'{r.hs6} ours {r.sector} / GTAP {r.gtap_gsec3}' for r in dis.assign(v=dis.hs6.map(kv).fillna(0)).sort_values('v', ascending=False).head(15).itertuples()))
oilgas = h1[h1.sector.isin(['oil', 'gas'])][['hs6', 'sector']].values.tolist()
S.check('S01-H4', 'Only HS 270900 and 271410 (crude; oil shale and tar sands, ISIC 0610) -> oil; 271111/271121 (natural gas, ISIC 0620) -> gas; LPG/NGL (271112-271119) -> pet', 'hard', oilgas,
        "[['270900','oil'],['271111','gas'],['271121','gas'],['271410','oil']]",
        sorted(map(tuple, oilgas)) == [('270900', 'oil'), ('271111', 'gas'), ('271121', 'gas'), ('271410', 'oil')], 'PLAN_ERRATA E29; GTAP 12 Table A.7 (oil 061, gas 062)')
S.flag('HS-NGL', 'HS 271112-271119 (LPG, NGL)', 'Mapped to pet (C19), following the UNSD correspondence (refinery and gas-plant output). S11 has a hard concept-parity check that the oil and gas volumes used to split B06 exclude NGL/LPG (PLAN_ERRATA E29).', 'no', '', 'UNSD HS2017-CPC2.1-ISIC4; PLAN_ERRATA E29')
S.write('concord_hs17_to_sector.csv', h1)
S.check('S01-H5', f'BACI HS17 file contains {Y} (preferred route: no HS conversion; recorded only: the stage stops earlier if the file is missing)', 'hard', BFILE, 'present', True, 'C01')
# ---------------------------------------------------------------- world totals unchanged by the mapping (review S01-M2; PLAN (a) checks)
HS1 = dict(zip(h1.hs6, h1.sector))
bb = b.assign(ri=b.i.map(lambda n: to_region(num2iso.get(n, ''))[0]), rj=b.j.map(lambda n: to_region(num2iso.get(n, ''))[0]), sec=b.k.map(HS1))
after = bb.dropna(subset=['ri', 'rj', 'sec']).groupby(['ri', 'rj', 'sec']).v.sum().sum()
S.check('S01-T1', f'BACI {Y} world total unchanged by the region map and HS6 concordance', 'hard', f'{b.v.sum():.6f} vs {after:.6f} kUSD', 'rel 1e-9',
        abs(after / b.v.sum() - 1) <= 1e-9, 'PLAN (a) checks')
intra = bb[(bb.ri == bb.rj) & (bb.i != bb.j)].groupby('ri').v.sum().sort_values(ascending=False)
S.check('S01-T1i', f'BACI {Y} trade that becomes intra-region by the folds (own-region trade at S07)', 'report', f'{intra.sum()/1e6:,.3f} USD bn', '-', True, '',
        ', '.join(f'{r} {v/1e6:,.3f}' for r, v in intra.items()))
EB = ebops[(ebops.level == 'batis') & ~ebops.role.isin(['aggregate', 'dropped'])]
bt = pd.read_csv(batis, usecols=['REF_AREA', 'COUNTERPART_AREA', 'SERVICE', 'OBS_VALUE'])
bt = bt[bt.SERVICE.isin(set(EB.code)) & ~bt.REF_AREA.isin(NONC) & ~bt.COUNTERPART_AREA.isin(NONC)]
bt = bt.assign(ri=bt.REF_AREA.map(lambda c: to_region(c)[0]), rj=bt.COUNTERPART_AREA.map(lambda c: to_region(c)[0]))
aft2 = bt.dropna(subset=['ri', 'rj']).groupby(['ri', 'rj', 'SERVICE']).OBS_VALUE.sum().sum()
S.check('S01-T2', f'BaTIS {Y} world total (country pairs, mapped EBOPS leaves) unchanged by the region map', 'hard', f'{bt.OBS_VALUE.sum():.6f} vs {aft2:.6f} USD m', 'rel 1e-9',
        abs(aft2 / bt.OBS_VALUE.sum() - 1) <= 1e-9, 'PLAN (a) checks', 'Excluded by design: non-country partners (WXD etc.), aggregates, SA and SH (GTAP Table 10.1).')

# HS22 via UNSD conversion
cv = pd.read_excel(conv, sheet_name='HS2022-HS2017 Conversions', dtype=str).iloc[:, :2]
cv.columns = ['hs22', 'hs17']
resid = sorted(c for c in set(hs17.hs6) if c.endswith('000') or c == '999999')
cv = pd.concat([cv, pd.DataFrame({'hs22': [c for c in resid if c not in set(cv.hs22)], 'hs17': [c for c in resid if c not in set(cv.hs22)]})])
c22 = cv.merge(h1[['hs6', 'sector', 'share']], left_on='hs17', right_on='hs6', how='left')
p22 = pd.read_csv(zipfile.ZipFile(baci22).open([n for n in zipfile.ZipFile(baci22).namelist() if n.startswith('product_codes')][0]), dtype=str)
m22 = sorted(set(p22.code) - set(cv.hs22) - {'999999'}); nom = [c for c in c22[c22.sector.isna()].hs22 if c != '999999']
S.check('S01-H6', 'HS2022 -> HS2017 (UNSD conversion; BACI residual codes such as 271000 kept as is) -> sector covers every BACI HS22 product code except 999999', 'hard',
        f'{len(m22)} not in conversion; {len(nom)} conversion targets unmapped', 0, not m22 and not nom, '', ' '.join(m22[:40] + nom[:40]) + ' (HS22 route is a fallback; S07 uses BACI HS17)')
S.check('S01-H6b', 'HS2022 -> sector is one-to-one', 'hard', int(c22.dropna(subset=['sector']).hs22.duplicated().sum()), 0, not c22.dropna(subset=['sector']).hs22.duplicated().any())
S.write('concord_hs22_to_sector.csv', c22[['hs22', 'hs17', 'sector', 'share']])
# QA B-09: HS22 codes whose UNSD correlation sources (HS17) fall in several sectors keep the conversion-sheet source's
# sector; where that is not the largest-value source's sector, GTAP's own HS2022 list (GTAP H6) must agree
cr = pd.read_excel(conv, sheet_name='HS2022-HS2017 Correlations', dtype=str, header=1).iloc[:, :2].dropna()
amb = hs22_parents.ambiguous(zip(cr.iloc[:, 0], cr.iloc[:, 1]), HS1, dict(zip(c22.hs22, c22.sector)), _g('H6', 4),
                             {k: set(v.split(';')) for k, v in G2S.items()}, kv.to_dict())
amb_bad = hs22_parents.problems(amb)
amb_off = [r for r in amb if r['sector'] != r['largest_parent_sector']]
S.check('S01-H6c', 'HS22 codes with HS17 sources in several sectors (UNSD correlation sheet): a sector other than the largest-value source\'s is the GTAP HS2022 (sheet H6) sector', 'hard',
        len(amb_bad), 0, not amb_bad, 'QA B-09; GTAP HS->GSEC3 (Aguiar et al. 2025 fn.11)',
        f'{len(amb)} such codes. Sector differs from the largest-value HS17 source (BACI {Y} world value of the whole source code), kept because GTAP H6 agrees: ' +
        ', '.join(f'{r["hs22"]} {r["sector"]} (GTAP {r["gtap22"]}; largest source {r["largest_parent_sector"]})' for r in amb_off) +
        ('; problems: ' + '; '.join(amb_bad) if amb_bad else ''))
amb_g = hs22_parents.gtap_differs(amb)
S.check('S01-H6d', 'HS22 codes with HS17 sources in several sectors whose sector (the conversion-sheet source\'s) differs from GTAP HS2022 (sheet H6)', 'report',
        len(amb_g), 0, not amb_g, 'QA B-09; GTAP HS->GSEC3 (Aguiar et al. 2025 fn.11)',
        'S01 follows the HS17 source; GTAP H6 sectors new HS2022 headings on its own: ' + ', '.join(f'{r["hs22"]} ours {r["sector"]} / GTAP {r["gtap22"]}' for r in amb_g))

# EBOPS
bat_codes = set(pd.read_csv(batis, usecols=['SERVICE']).SERVICE)
eb_codes = set(ebops.code)
miss = sorted((bat_codes | tis_codes) - eb_codes)
dup = ebops.code[ebops.code.duplicated()].tolist()
badsec = sorted({s for x in ebops.sectors for s in x.split(';') if s} - SECT - {'TRAVEL'})
S.check('S01-E1', 'Every BaTIS and TiSMoS service code is classified exactly once; all sectors valid', 'hard', f'{len(miss)} missing, {len(dup)} dup, {len(badsec)} bad', 0,
        not miss and not dup and not badsec, 'ch.10B', ' '.join(miss + dup + badsec))
S.write('concord_ebops_to_sector.csv', ebops)
S.flag('EBOPS-SJ32-SJ33', 'SJ32, SJ33, SJ35', 'Follow GTAP Table 10.2 (obs / rsa). In ICIO terms placed in adm (N); by ISIC, SJ32 sits partly in E/A/B09 and SJ35 partly in M. Concept note C15.', 'no', '', 'GTAP 12 ch.10B Table 10.2 p.3')
S.flag('EBOPS-whs', 'Warehousing from transport', 'Table 10.2 sends SC13/SC23/SC33 to whs; the p.3 text also says 20% of other transport goes to whs. S09 will apply Table 10.2 and report the 20% reading; no choice made at S01.', 'no', '', 'GTAP 12 ch.10B p.3')
S.flag('EBOPS-trvl', 'SDA business travel', 'Not a sector: allocated across commodities by the private-consumption pattern at S09 (GTAP practice).', 'no', '', 'GTAP 12 ch.10B p.3')

# ISIC -> sector (division level and section level)
DIV = {}
spec = {'crp': '01', 'for': '02', 'fsh': '03', 'coa': '05', 'oil|gas': '06', 'ore': '07', 'min': '08', 'msp': '09', 'fbt': '10-12', 'tal': '13-15', 'wod': '16',
        'pap': '17-18', 'pet': '19', 'chm': '20', 'pha': '21', 'rpl': '22', 'nmm': '23', 'stl|nfm': '24', 'fmp': '25', 'elc': '26', 'eeq': '27', 'mac': '28',
        'mvh': '29', 'shp|tre': '30', 'omf': '31-33', 'ely': '35', 'wat': '36-39', 'con': '41-43', 'trd': '45-47', 'rdt': '49', 'sea': '50', 'air': '51',
        'whs': '52', 'pst': '53', 'hos': '55-56', 'pub': '58-60', 'tel': '61', 'its': '62-63', 'fin': '64-66', 'rle': '68', 'pro': '69-75', 'adm': '77-82',
        'gov': '84', 'edu': '85', 'hea': '86-88', 'art': '90-93', 'ots': '94-96', 'hhe': '97-98'}
SEC = [('A', 1, 3), ('B', 5, 9), ('C', 10, 33), ('D', 35, 35), ('E', 36, 39), ('F', 41, 43), ('G', 45, 47), ('H', 49, 53), ('I', 55, 56), ('J', 58, 63), ('K', 64, 66),
       ('L', 68, 68), ('M', 69, 75), ('N', 77, 82), ('O', 84, 84), ('P', 85, 85), ('Q', 86, 88), ('R', 90, 93), ('S', 94, 96), ('T', 97, 98), ('U', 99, 99)]
CLASS = {'06': [('0610', 'oil'), ('0620', 'gas')], '24': [('241', 'stl'), ('2431', 'stl'), ('242', 'nfm'), ('2432', 'nfm')],
         '30': [('301', 'shp'), ('302', 'tre'), ('303', 'tre'), ('304', 'tre'), ('309', 'tre')]}   # review S01-L1; ISIC Rev.4 structure; GTAP 12 Table A.7
drows = []
for sec, rng in spec.items():
    a_, _, bb_ = rng.partition('-'); bb_ = bb_ or a_
    for d in range(int(a_), int(bb_) + 1):
        dd = f'{d:02d}'; sx = next(x for x, lo, hi in SEC if lo <= d <= hi)
        if '|' in sec:
            for code, sct in CLASS[dd]:
                drows.append((code, 'class' if len(code) == 4 else 'group', sx, sct, 1.0, 'set', 'ISIC Rev.4 class/group level'))
        else:
            drows.append((dd, 'division', sx, sec, 1.0, 'set', 'identity'))
drows.append(('99', 'division', 'U', '', '', 'excluded', 'extraterritorial organisations: no ICIO industry; excluded'))
dv = pd.DataFrame(drows, columns=['isic4_code', 'level', 'isic4_section', 'sector', 'share', 'share_status', 'basis'])
S.write('concord_isic4_to_sector.csv', dv)
S.check('S01-I1', 'ISIC Rev.4 01-98 map to sectors with share 1 (division, or class/group for 06, 24, 30); every sector reached; only 99 excluded', 'hard', dv[dv.sector != ''].sector.nunique(), 51,
        set(dv[dv.sector != ''].sector) == SECT and set(dv[dv.share == ''].isic4_code) == {'99'}, 'ch.14B Table 14.19')
S.write('labour_isco_groups.csv', isco)
g5 = sorted(set(isco.group5) - {'EXCLUDED'})
agg = isco[isco.group5 != 'EXCLUDED'].groupby('group5').group2.nunique()
S.check('S01-L1', 'Labour: 5 groups; the 2-group split is an exact aggregation of the 5', 'hard', f'{len(g5)} groups; max 2-group per 5-group {agg.max()}', '5; 1',
        len(g5) == 5 and agg.max() == 1, 'decision 10; C30', 'skilled = off_mgr_pros + tech_aspros; unskilled = clerks + service_shop + ag_othlowsk')
S.flag('ISCO0', 'ISCO 0 armed forces', 'Excluded from occupation shares (GTAP ch.14B uses major groups 1-9 and drops X); armed-forces pay is spread with the O84 labour bill at S12.', 'no', '', 'GTAP 12 ch.14B p.5, Table 14.18')

# ---------------------------------------------------------------- flags for regions
S.flag('PRK', 'PRK', 'Kept as a single region; data very thin. Every fill for PRK will be logged and flagged.', 'no', 'decision', 'David 2026-10-20 18:46')
S.flag('TWN', 'TWN', 'BACI code 490 (iso3 S19, "Other Asia, nes") read as TWN.', 'no', 'F6', 'READINESS.md F6')
S.flag('XNF', 'XNF', 'After splitting out LBY, XNF has one member (Sudan). Kept as code XNF.', 'no', '', 'region_decisions.csv')
S.flag('ANT', 'ANT', 'Inherited fold ANT -> CUW now resolves to XCB because CUW folds into XCB.', 'no', '', 'territory_folds.csv')
for r in un[un.sources.str.contains('BACI|BaTIS|WDI|PWT|AMA')].itertuples():
    S.flag('UNMAPPED-' + r.code, r.code, f'{r.name} [{r.gtap_geo}] appears in {r.sources}; BACI {Y} X+M {r.baci_x_plus_m_kusd/1000:,.2f} USD m. Not assigned: needs David.', 'yes', 'P8', 'GTAP 12 ch.9D Table 9.10')

tp = pd.read_csv(I(CFG + '/territory_proposals.csv', 'config: territory proposals shown to David'))
res = tp.merge(tdec, on='code', how='outer').merge(cmap[['code', 'name', 'gtap_geo', 'sources', 'baci_x_plus_m_kusd']], on='code', how='left')
unh = un[un.sources.str.contains('BACI|BaTIS|WDI|PWT|AMA')]
md = ['# S01: decisions needed from David', '', 'Territories: **resolved by David, 2026-10-20 19:03 and 19:40 (UTC+7)**. Region count stays 167. Each assignment is logged in `adjustments_ledger.csv` (flag territory_assignment).',
      f'Open items left after applying the decisions: {len(unh)}.', '',
      f'| Code | Name | GTAP geo | Sources | BACI {Y} X+M (USD m) | Recommended | David decided | Same as recommended |', '|---|---|---|---|---|---|---|---|']
for r in res.itertuples():
    md.append(f'| {r.code} | {r.name} | {r.gtap_geo} | {r.sources} | {r.baci_x_plus_m_kusd/1000:,.2f} | {r.recommended} | **{r.into}** | {"yes" if r.recommended == r.into else "NO"} |')
oth = un[~un.sources.str.contains('BACI|BaTIS|WDI|PWT|AMA')]
md += ['', 'No decision needed (report only): codes seen only in ITIC or TiSMoS, which BACI and BaTIS report inside the parent country or not at all: ' + (' '.join(oth.code) or 'none') + '. Their ITIC rates are not used.', '']
md += ['## HS6 one-to-one tie-breaks (David 19:40: one sector per HS6 as in GTAP practice; dominant UNSD link, ties by GTAP HS->GSEC3)', '',
       f'Codes with several links: {len(multi)}. Resolved by the dominant link: {(h1.basis.str.startswith("dominant")).sum()}. Ties needing an approved tie-break: {len(unres)}.',
       'Proposed rule for ties: the GTAP HS->GSEC3 assignment (Aguiar, GTAP resource 5111, cited in Aguiar et al. 2025 fn.11) where it falls in exactly one linked sector. Codes where GTAP picks none of the linked sectors are listed as open.',
       'Approve by setting status=approved in `build/config/s01/hs6_tiebreak.csv`. Until then S01-H1b fails (no STAMP).', '',
       '| HS6 | Links | Status |', '|---|---|---|'] + [f'| {k} | {l} | {st} |' for k, l, st in unres] + ['']
open(S.dir + '/NEEDS_DAVID.md', 'w').write('\n'.join(md) + '\n')
S.check('S01-M-dec', 'Every territory decision matches a code that was unmapped and a valid region', 'hard', int(res.into.isna().sum() + (~res.into.isin(set(regions.region))).sum()), 0,
        res.into.notna().all() and res.into.isin(set(regions.region)).all())

# ---------------------------------------------------------------- this stage's own inputs (review S01-M1)
# The stage kit adds S01-IN1 (each data input in MANIFEST with matching SHA) and S01-IN2 (year rule).
# The global MANIFEST audit (every file on disk, every SHA) is build/check_manifest.py, so data added for later
# stages no longer invalidates S01.
man = pd.read_csv(mani)
own = {v['manifest_path'] for v in S.inputs.values() if v['manifest_path']}
mo = man[man.path.isin(own)].merge(pd.DataFrame([(v['manifest_path'], v['year_used']) for v in S.inputs.values() if v['manifest_path']], columns=['path', 'year_used']), on='path', how='left')
mo.to_csv(S.out + '/inputs_manifest.csv', index=False); S.log(f'output inputs_manifest.csv: {len(mo)} rows (this stage\'s data inputs)')
gi = open(os.path.dirname(os.path.abspath(__file__)) + '/.gitignore').read()
tracked = subprocess.run(['git', '-C', os.path.dirname(os.path.abspath(__file__)), 'ls-files'], capture_output=True, text=True).stdout.split()
leak = [t for t in tracked if not t.endswith('.py') and re.search(r'trains|iea_subsid|BACI_|\.zip$|\.xlsx$|secret', t, re.I)]  # code files name sources, they hold no data
S.check('S01-F3', 'No restricted or raw data tracked in the build repo', 'hard', len(leak), 0, not leak, 'standing rule', ' '.join(leak))
ok = S.finish()
print('HARD PASS' if ok else 'HARD FAIL (no STAMP)')
