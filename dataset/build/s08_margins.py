"""S08 international transport margins (VTWR, VST).

Reads margin_choices.csv for every choice. The goods list is the S07
goods_sectors token. Bound S07 snapshot: head dce1d9c, STAMP 2026-10-24
05:53:59 UTC+7, output SHA256SUMS 709e0963…, goods file 25277e01….
margin_base must be s07r_vfob_baci. The base column is vfob_musd in
vxsb_goods_s07r.csv.gz. The retired s07_vxsb_value path is not accepted.
Rows that repeat by source are summed first. io_s08 is a byte copy of io_s07.
"""
import csv
import gzip
import hashlib
import os
import re
import shutil
import statistics
import subprocess
import sys
import traceback
import zipfile
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/lib')
from stagekit import BUILD, DATA, ROOT, InputError, Stage, sha256
from private_files import is_private, load_rules
import s09_services as S9   # BaTIS and TiSMoS readers, so the VST key is the freight S09 removes

# Filled in run() from the S07 goods_sectors token. This stage does not keep a second list.
GOODS = ()
GOODS_SET = set()
MODES = ('rdt', 'sea', 'air')
MODE_I = {m: i for i, m in enumerate(MODES)}
# importer_world_total is the importer's own `_T` (counterpart W). It is not a new
# config choice: margin_fallback still names pair_total, and this label keeps that
# total distinct from the route's bilateral `_T`.
LEVELS = ('pair_hs4', 'importer_world_hs4', 'pair_total', 'importer_world_total', 'F7')
LEVEL_I = {name: i for i, name in enumerate(LEVELS)}
SC_TISMOS = {'sea': 'SC12', 'air': 'SC22', 'rdt': 'SC32'}
SC_BATIS = {'sea': 'SC1', 'air': 'SC2', 'rdt': 'SC3'}
ROW_MODE = {'dom_rdt': 'rdt', 'dom_sea': 'sea', 'dom_air': 'air'}

# Upstream binding (S07R snapshot). Not a margin choice.
S07_HEAD = '94c1e585c94b7c70a308cbce3c012b7b24c40d32'
S07_STAMP_TIME = '2026-10-27 23:10:35 UTC+7'
S07_SHA256SUMS = 'c5e753b863c1ccb9e95d3862980e1bf1c0ed45a9dbded8491d018ba6fdfeb556'
S07_VXSB_SHA = '5021c15f3627a1907a70cb9b73cfc6c8544328300d0fd86c33e7154ba891d2c7'
S07_IO_SHA = 'e83facbfd23c2cb0f535cb52be976055da3179a44256c7e1c401020fc8b3a410'
REPEATED_TRIPLES_NOTE = 0
# The preview CSV is not an input. These are the figures the brief used to quote.
PREVIEW_WORLD_VTWR_BN = 1050.8
PREVIEW_PCT = 6.23

# beta v4 P7 (lng_sea_rate, David's call; 'itic' is the default): the LNG part of gas routes not into the USA at a 2022
# voyage cost over the exporter's BACI LNG FOB price (config/s08/lng_voyage.csv, lng_routes.csv); routes without a listed
# distance take ITIC x LNG_FALLBACK_SCALE. LNG_SCALED: every LNG part at ITIC x LNG_FALLBACK_SCALE
LNG_VOYAGE = 'voyage_cost_2022_listed_routes_else_itic_x_0p52'
FILL_SAME_CLASS = 'fill_same_distance_class'     # beta v4 P27 (itic_zero_rate)
LNG_SCALED = 'itic_x_0p52'
LNG_FALLBACK_SCALE = 0.52      # the 2022 build-up over ITIC on the 24 largest LNG routes (5.3% vs 10.2% of FOB)
MMBTU_PER_T_LNG = 52.0
LNG_PARAMS = ('charter_usd_day', 'speed_knots', 'cargo_mmbtu', 'port_days', 'port_fees_usd', 'boiloff_laden_per_day',
              'fuel_ballast_per_day', 'insurance_share', 'canal_days', 'toll_suez_usd', 'toll_panama_usd')
# beta v4 P21 (David's call, default off): a listed region with no seaport keeps no sea VST key; its BaTIS SC1 freight
# key goes to road (config/s08/no_seaport_regions.csv)
NO_SEAPORT_TO_ROAD = 'listed_no_seaport_regions_sea_key_moved_to_road'
NO_SEAPORT_FILE = 'no_seaport_regions.csv'

# beta v4 G5 (Grok QA, Cursor 3): the Census import charge (con_cif - con_val) is the cost of the whole route to the USA in
# every mode (GTAP 7 ch.9A p.3: "aggregate cost of all freight, insurance and other related transport costs"), not a
# sea-only rate. Under this value the route's margin outside crude pipelines is the Census rate itself, split over the
# modes by the prior shares; the crude pipeline part (the rdt share of oil) keeps ITIC.
CENSUS_WHOLE_ROUTE = 'us_census_exporter_hs4_whole_route'
CHOICE_ORDER = (
    'margin_source', 'margin_unit', 'margin_aggregation', 'margin_fallback', 'margin_base',
    'composite_diagonal_margins', 'mode_split', 'vst_allocation', 'vst_vs_output',
    'freight_double_count', 'services_margins', 'energy_sea_rate', 'lng_sea_rate', 'itic_zero_rate',
    'no_seaport_sea_key',
)
ALLOWED = {
    'margin_source': {'itic_2022_hs4_pt_im_cif'},
    'margin_unit': {'cif_share_to_fob_rate'},
    'margin_aggregation': {'baci_hs6_pair_fob_weights'},
    'margin_fallback': {'pair_hs4,importer_world_hs4,pair_total,F7_region_median'},
    'margin_base': {'s07r_vfob_baci'},
    'composite_diagonal_margins': {'member_pair_rates'},
    'mode_split': {'us_census_charges_by_sector', 'tismos_world_freight', 'us_census_charges_by_sector_energy_by_route'},
    'vst_allocation': {'tismos_2022_mode1_freight_exports', 'tismos_2022_mode1_freight_exports_f8_where_zero',
                       'tismos_2022_mode1_freight_exports_f8_where_zero_capped',
                       'batis_freight_plus_own_carrier_imports_capped'},
    'vst_vs_output': {'report_only'},
    'freight_double_count': {'remove_at_S09'},
    'services_margins': {'zero'},
    'energy_sea_rate': {'itic', 'us_census_exporter_hs4', CENSUS_WHOLE_ROUTE},
    'itic_zero_rate': {'off', 'missing', FILL_SAME_CLASS},
    'lng_sea_rate': {'itic', LNG_VOYAGE, LNG_SCALED},
    'no_seaport_sea_key': {'off', NO_SEAPORT_TO_ROAD},
}
# energy_sea_rate (next round, Gulf margins check 2026-10-25): the tanker part of crude (HS 2709) and the sea part of
# petroleum products (HS 2710) take the exporter's US Census 2022 import charges on that heading
ENERGY_HS4 = {'2709': 'oil', '2710': 'pet'}
CENSUS_MIN_VALUE = 1e8      # USD: an exporter with less US customs value of the heading takes the fallback rate
# An exporter's US rate reflects its haul to the USA; on a route to an importer outside the Americas it is floored at the
# fallback (the average over every exporter but Canada), so short-haul and overland US suppliers (CAN, MEX, Caribbean)
# do not carry a short-haul rate to Europe or Asia (S16 review of 5fe5abe; our choice)
AMERICAS_GEO = {'NAMR', 'CAMR', 'SAMR', 'CARB'}
# Census country names the S01 map spells differently (energy_sea_rate only; MARTINIQUE has no S01 region and stays out)
CENSUS_ENERGY_ALIAS = {'TURKEY': 'TUR', 'DEMOCRATICREPUBLICOFTHECONGO': 'COD', 'COTEDIVOIRE': 'CIV', 'CURACAO': 'CUW',
                       'DOMINICANREPUBLIC': 'DOM', 'HONGKONG': 'HKG', 'MARSHALLISLANDS': 'MHL'}
NAME_ALIAS = {
    'KOREASOUTH': 'KOR', 'SOUTHKOREA': 'KOR', 'REPUBLICOFKOREA': 'KOR', 'REPOFKOREA': 'KOR',
    'TAIWAN': 'TWN', 'CHINESETAIPEI': 'TWN',
    'VIETNAM': 'VNM', 'RUSSIA': 'RUS', 'RUSSIANFEDERATION': 'RUS',
    'BOLIVIA': 'BOL', 'TANZANIA': 'TZA', 'MOLDOVA': 'MDA', 'LAOS': 'LAO',
    'SYRIA': 'SYR', 'IRAN': 'IRN', 'VENEZUELA': 'VEN', 'BRUNEI': 'BRN',
    'CZECHIA': 'CZE', 'CZECHREPUBLIC': 'CZE',
}
Q_CIF = 'GTAP 7 ch.9A p.3'
Q_AGG = 'GTAP 7 ch.9A p.6 §9.A.4'
Q_MODE = 'GTAP 12 ch.02 p.16'
Q_ARRAY = 'GTAP 12 ch.02 p.17'
Q_SC = 'GTAP 12 ch.10B p.3 Table 10.2'
Q_FIT = 'GTAP 12 ch.17A p.2'
Q_ASM = 'GTAP 12 ch.17B §B.2 p.3'


def fnum(x):
    x = float(x)
    if x != x:
        return 'nan'
    if abs(x) < 5e-13:
        return '0'
    s = f'{x:.10f}'
    if '.' in s:
        s = s.rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s


def f12(x):
    return f'{float(x):.12f}'


def norm_name(s):
    return re.sub(r'[^A-Z0-9]', '', (s or '').upper())


def repo_root():
    r = subprocess.run(['git', '-C', BUILD, 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    return r.stdout.strip() or os.path.dirname(ROOT)


def sql_path(path):
    return path.replace("'", "''")


def read_csv(path):
    with open(path, newline='') as fh:
        return list(csv.DictReader(fh))


def gz_write(path, header, lines):
    raw = open(path, 'wb')
    with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0, compresslevel=9) as gz:
        gz.write(header)
        for line in lines:
            gz.write(line)
    raw.close()


def write_csv(path, cols, rows):
    with open(path, 'w', newline='') as fh:
        w = csv.writer(fh, lineterminator='\n')
        w.writerow(cols)
        w.writerows(rows)


def dominant(ws):
    best = 0
    for i in range(1, len(ws)):
        if ws[i] > ws[best]:
            best = i
    return LEVELS[best]


def as_float(x):
    return 0.0 if x is None else float(x)


def shares_of(rec):
    w = rec['w']
    ws = [rec['w1'], rec['w2'], rec['w3'], rec['w4'], rec['w5']]
    if w > 0:
        return [x / w for x in ws], dominant(ws)
    return [0.0, 0.0, 0.0, 0.0, 0.0], dominant(ws)


def load_goods_sectors():
    """The S07 goods_sectors token is the only goods list."""
    goods = None
    for row in read_csv(BUILD + '/config/s07/trade_choices.csv'):
        if row['choice'].strip() == 'goods_sectors':
            goods = tuple(row['value'].split())
    if not goods:
        raise InputError('s07 trade_choices.csv has no goods_sectors value')
    return goods


def load_vxsb(path, value_col):
    sums = {}
    n_src = {}
    n = 0
    neg = 0
    other = 0.0
    with gzip.open(path, 'rt', newline='') as fh:
        for row in csv.DictReader(fh):
            n += 1
            key = (row['sector'], row['exporter'], row['importer'])
            v = float(row[value_col])
            sums[key] = sums.get(key, 0.0) + v
            n_src[key] = n_src.get(key, 0) + 1
            if v < -1e-9:
                neg += 1
            if row['sector'] not in GOODS_SET:
                other += v
    n_rep = sum(1 for c in n_src.values() if c > 1)
    extra = sum(c - 1 for c in n_src.values() if c > 1)
    return sums, n, n_rep, extra, neg, other


def load_choices(path):
    rows = read_csv(path)
    by = {r['choice'].strip(): r for r in rows}
    bad = []
    if set(by) != set(CHOICE_ORDER) or len(rows) != len(CHOICE_ORDER):
        bad.append(f'rows {len(rows)} names {sorted(by)}')
    for name in CHOICE_ORDER:
        r = by.get(name)
        if not r:
            continue
        if not r.get('decided_by', '').strip() or not r.get('decided_at', '').strip() or not r.get('gtap_status', '').strip():
            bad.append(name + ' missing decided_by, decided_at or gtap_status')
        if r.get('value', '').strip() not in ALLOWED[name]:
            bad.append(name + ' value ' + r.get('value', ''))
    return {name: by[name]['value'].strip() for name in CHOICE_ORDER if name in by}, rows, bad


def bind_s07(vx_name):
    stamp_path = ROOT + '/stages/S07_trade/STAMP'
    sums_path = ROOT + '/stages/S07_trade/output/SHA256SUMS'
    vx_path = ROOT + '/stages/S07_trade/output/' + vx_name
    io_path = ROOT + '/stages/S07_trade/output/io_s07.csv.gz'
    stamp = open(stamp_path).read() if os.path.exists(stamp_path) else ''
    head = subprocess.run(
        ['git', '-C', repo_root(), 'log', '-1', '--format=%H', '--', 'dataset/stages/S07_trade/STAMP'],
        capture_output=True, text=True).stdout.strip()
    sums = sha256(sums_path) if os.path.exists(sums_path) else ''
    vx = sha256(vx_path) if os.path.exists(vx_path) else ''
    io = sha256(io_path) if os.path.exists(io_path) else ''
    ok = (S07_STAMP_TIME in stamp and head == S07_HEAD and sums == S07_SHA256SUMS
          and vx == S07_VXSB_SHA and io == S07_IO_SHA)
    detail = f'head {head or "-"} stamp_time {"yes" if S07_STAMP_TIME in stamp else "NO"} SHA256SUMS {sums} VXSB {vx} io {io}'
    return ok, detail


def extract_baci(zip_path, log):
    dest = '/tmp/s08_baci'
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        year = next(n for n in names if n.endswith('BACI_HS17_Y2022_V202601.csv'))
        ctry = next(n for n in names if 'country_codes' in n and n.endswith('.csv'))
        ypath = dest + '/y2022.csv'
        cpath = dest + '/country_codes.csv'
        if not os.path.exists(ypath) or os.path.getsize(ypath) < 100_000_000:
            log(f'extract {year}')
            with z.open(year) as src, open(ypath, 'wb') as dst:
                shutil.copyfileobj(src, dst)
        if not os.path.exists(cpath) or os.path.getsize(cpath) < 1000:
            with z.open(ctry) as src, open(cpath, 'wb') as dst:
                shutil.copyfileobj(src, dst)
    log(f'BACI year bytes {os.path.getsize(ypath)}')
    return ypath, cpath


def build_weights(paths, log, zero_rate='off'):
    import duckdb
    os.makedirs('/tmp/s08duck', exist_ok=True)
    con = duckdb.connect()
    # Below the free RAM on this box. threads=1 keeps the sums stable when DuckDB spills.
    con.execute("PRAGMA memory_limit='4GB'")
    con.execute("PRAGMA temp_directory='/tmp/s08duck'")
    # One thread. A parallel sum moved the 12th decimal of m between runs.
    con.execute('PRAGMA threads=1')
    goods_sql = ','.join("'" + s + "'" for s in GOODS)
    con.execute(f"""
        CREATE TABLE concord AS
        SELECT hs6, sector, CAST(share AS DOUBLE) AS share
        FROM read_csv('{sql_path(paths["hs17"])}', header=true, all_varchar=true)
        WHERE share IS NOT NULL AND share <> '' AND CAST(share AS DOUBLE) > 0
          AND sector IN ({goods_sql})
    """)
    con.execute(f"""
        CREATE TABLE cmap AS
        SELECT code AS iso, region, gtap_geo AS geo
        FROM read_csv('{sql_path(paths["cmap"])}', header=true, all_varchar=true)
        WHERE region IS NOT NULL AND region <> ''
    """)
    con.execute(f"""
        CREATE TABLE alias AS
        SELECT code AS src, iso3 AS dst
        FROM read_csv('{sql_path(paths["alias"])}', header=true, all_varchar=true)
        WHERE code NOT LIKE 'TiSMoS:%'
    """)
    ypath, cpath = extract_baci(paths['baci'], log)
    con.execute(f"""
        CREATE TABLE ctry AS
        SELECT country_code, country_iso2, country_iso3
        FROM read_csv('{sql_path(cpath)}', header=true, all_varchar=true)
    """)
    con.execute("""
        CREATE TABLE baci_iso AS
        SELECT TRY_CAST(c.country_code AS INTEGER) AS code,
               COALESCE(a.dst, CASE WHEN c.country_iso3 = 'S19' OR c.country_code IN ('490', '0490') THEN 'TWN'
                                    ELSE NULLIF(c.country_iso3, '') END) AS iso,
               NULLIF(c.country_iso2, '') AS iso2
        FROM ctry c
        LEFT JOIN alias a ON a.src = c.country_iso3
        WHERE TRY_CAST(c.country_code AS INTEGER) IS NOT NULL
    """)
    # One iso per numeric code. A conflict is dropped and counted.
    n_code_conflict = con.execute("""
        SELECT count(*) FROM (
          SELECT code FROM baci_iso WHERE iso IS NOT NULL GROUP BY code HAVING count(DISTINCT iso) > 1
        )
    """).fetchone()[0]
    con.execute("""
        CREATE TABLE baci_iso_u AS
        SELECT code, any_value(iso) AS iso
        FROM baci_iso
        WHERE iso IS NOT NULL
        GROUP BY code
        HAVING count(DISTINCT iso) = 1
    """)
    log('read ITIC')
    con.execute(f"""
        CREATE TABLE itic_raw AS
        SELECT trim(importer) AS importer, trim(counterpart) AS counterpart, trim(comm) AS comm,
               CAST(obs_value AS DOUBLE) AS obs, trim(obs_status) AS obs_status
        FROM read_csv('{sql_path(paths["itic"])}', header=true, all_varchar=true)
    """)
    status_rows = con.execute("SELECT COALESCE(obs_status, ''), count(*) FROM itic_raw GROUP BY 1 ORDER BY 2 DESC").fetchall()
    con.execute("""
        CREATE TABLE itic AS
        SELECT COALESCE(ai.dst, r.importer) AS importer,
               CASE WHEN r.counterpart = 'W' THEN 'W' ELSE COALESCE(ac.dst, r.counterpart) END AS counterpart,
               r.comm,
               r.obs / 100.0 AS r
        FROM itic_raw r
        LEFT JOIN alias ai ON ai.src = r.importer
        LEFT JOIN alias ac ON ac.src = r.counterpart
        WHERE r.obs IS NOT NULL
    """)
    n_conflict = con.execute("""
        SELECT count(*) FROM (
          SELECT importer, counterpart, comm FROM itic GROUP BY 1, 2, 3 HAVING count(DISTINCT r) > 1
        )
    """).fetchone()[0]
    if n_conflict:
        con.close()
        return {'conflict': n_conflict, 'status': status_rows, 'code_conflict': n_code_conflict}
    con.execute("""
        CREATE TABLE itic_u AS
        SELECT importer, counterpart, comm, min(r) AS r
        FROM itic GROUP BY 1, 2, 3
    """)
    con.execute("""
        CREATE TABLE pair_hs4 AS
        SELECT importer, counterpart AS exporter, comm AS hs4, r FROM itic_u
        WHERE counterpart <> 'W' AND length(comm) = 4 AND comm SIMILAR TO '[0-9]{4}' AND r >= 0 AND r < 1
    """)
    # beta v4 P27 (choice itic_zero_rate): a published ITIC zero on a pair is not a rate (GTAP 7 ch.9A p.9A-3: margins from
    # US import charges, which are never zero); 'missing' drops it to the next rung, fill_same_distance_class fills it first
    con.execute("""
        CREATE TABLE pair_zero AS
        SELECT importer, exporter, hs4 FROM pair_hs4 WHERE r = 0
    """)
    if zero_rate != 'off':
        con.execute('DELETE FROM pair_hs4 WHERE r = 0')
    con.execute("""
        CREATE TABLE world_hs4 AS
        SELECT importer, comm AS hs4, r FROM itic_u
        WHERE counterpart = 'W' AND length(comm) = 4 AND comm SIMILAR TO '[0-9]{4}' AND r >= 0 AND r < 1
    """)
    con.execute("""
        CREATE TABLE pair_tot AS
        SELECT importer, counterpart AS exporter, r FROM itic_u
        WHERE counterpart <> 'W' AND counterpart <> importer AND comm = '_T' AND r >= 0 AND r < 1
    """)
    if zero_rate != 'off':
        con.execute('DELETE FROM pair_tot WHERE r = 0')
    con.execute("""
        CREATE TABLE world_tot AS
        SELECT importer, r FROM itic_u
        WHERE counterpart = 'W' AND comm = '_T' AND r >= 0 AND r < 1
    """)
    log('F7 medians')
    con.execute("""
        CREATE TABLE f7_pair AS
        SELECT c.geo, p.hs4, median(p.r) AS r
        FROM pair_hs4 p
        JOIN cmap c ON c.iso = p.importer
        WHERE c.geo <> ''
        GROUP BY 1, 2
    """)
    con.execute("""
        CREATE TABLE f7_world AS
        SELECT c.geo, w.hs4, median(w.r) AS r
        FROM world_hs4 w
        JOIN cmap c ON c.iso = w.importer
        WHERE c.geo <> ''
        GROUP BY 1, 2
    """)
    con.execute("""
        CREATE TABLE f7 AS
        SELECT geo, hs4, r FROM f7_pair
        UNION ALL
        SELECT w.geo, w.hs4, w.r FROM f7_world w
        ANTI JOIN f7_pair p ON p.geo = w.geo AND p.hs4 = w.hs4
    """)
    log('BACI flows')
    con.execute(f"""
        CREATE TABLE flow AS
        SELECT ei.iso AS exp_iso, ii.iso AS imp_iso,
               er.region AS exp_reg, ir.region AS imp_reg, COALESCE(ir.geo, '') AS imp_geo,
               substr(b.k, 1, 4) AS hs4, c.sector, b.v * c.share AS w
        FROM (
            SELECT TRY_CAST(i AS INTEGER) AS i, TRY_CAST(j AS INTEGER) AS j, k, CAST(v AS DOUBLE) AS v
            FROM read_csv('{sql_path(ypath)}', header=true, all_varchar=true,
                          columns={{'t':'VARCHAR','i':'VARCHAR','j':'VARCHAR','k':'VARCHAR','v':'VARCHAR','q':'VARCHAR'}})
            WHERE CAST(v AS DOUBLE) > 0
        ) b
        JOIN baci_iso_u ei ON ei.code = b.i
        JOIN baci_iso_u ii ON ii.code = b.j
        JOIN concord c ON c.hs6 = b.k
        LEFT JOIN cmap er ON er.iso = ei.iso
        LEFT JOIN cmap ir ON ir.iso = ii.iso
        WHERE ei.iso <> ii.iso
    """)
    log(f"flow rows {con.execute('SELECT count(*) FROM flow').fetchone()[0]}")
    # Fable QA C-05: gas by route. HS 271121 is natural gas in the gaseous state (pipeline), 271111 is LNG.
    gas_pipe = {}
    for er, ir, pipe, lng in con.execute(f"""
        SELECT er.region, ir.region,
               sum(CASE WHEN b.k = '271121' THEN b.v ELSE 0 END), sum(CASE WHEN b.k = '271111' THEN b.v ELSE 0 END)
        FROM (
            SELECT TRY_CAST(i AS INTEGER) AS i, TRY_CAST(j AS INTEGER) AS j, k, CAST(v AS DOUBLE) AS v
            FROM read_csv('{sql_path(ypath)}', header=true, all_varchar=true,
                          columns={{'t':'VARCHAR','i':'VARCHAR','j':'VARCHAR','k':'VARCHAR','v':'VARCHAR','q':'VARCHAR'}})
            WHERE k IN ('271111', '271121') AND CAST(v AS DOUBLE) > 0
        ) b
        JOIN baci_iso_u ei ON ei.code = b.i
        JOIN baci_iso_u ii ON ii.code = b.j
        JOIN cmap er ON er.iso = ei.iso
        JOIN cmap ir ON ir.iso = ii.iso
        WHERE ei.iso <> ii.iso
        GROUP BY 1, 2
    """).fetchall():
        gas_pipe[(er, ir)] = (as_float(pipe), as_float(lng))
    # beta v4 P7 (lng_sea_rate): the exporter's LNG FOB price, BACI 271111 value over tonnes, USD per MMBtu
    lng_fob = {}
    for er, v, q in con.execute(f"""
        SELECT er.region, sum(CAST(b.v AS DOUBLE)), sum(TRY_CAST(trim(b.q) AS DOUBLE))
        FROM (
            SELECT TRY_CAST(i AS INTEGER) AS i, TRY_CAST(j AS INTEGER) AS j, v, q
            FROM read_csv('{sql_path(ypath)}', header=true, all_varchar=true,
                          columns={{'t':'VARCHAR','i':'VARCHAR','j':'VARCHAR','k':'VARCHAR','v':'VARCHAR','q':'VARCHAR'}})
            WHERE k = '271111' AND CAST(v AS DOUBLE) > 0 AND TRY_CAST(trim(q) AS DOUBLE) > 0
        ) b
        JOIN baci_iso_u ei ON ei.code = b.i
        JOIN baci_iso_u ii ON ii.code = b.j
        JOIN cmap er ON er.iso = ei.iso
        WHERE ei.iso <> ii.iso
        GROUP BY 1
    """).fetchall():
        if as_float(q) > 0:
            lng_fob[er] = as_float(v) * 1000.0 / (as_float(q) * MMBTU_PER_T_LNG)
    log('aggregate pair and importer baskets')
    # beta v4 P27 fill_same_distance_class: the importer's FOB-weighted positive pair rate for the sector over its partners in
    # the importer's own GTAP geographic region (European partners for a European importer); our choice, labelled departure
    con.execute("""
        CREATE TABLE zfill AS
        SELECT f.imp_iso, f.sector, f.imp_geo AS cls, sum(f.w * p.r / (1 - p.r)) / sum(f.w) AS m
        FROM flow f
        JOIN pair_hs4 p ON p.importer = f.imp_iso AND p.exporter = f.exp_iso AND p.hs4 = f.hs4
        JOIN cmap ge ON ge.iso = f.exp_iso
        WHERE f.imp_geo <> '' AND ge.geo = f.imp_geo AND p.r > 0
        GROUP BY 1, 2, 3
    """)
    if zero_rate != FILL_SAME_CLASS:
        con.execute('DELETE FROM zfill')
    zero_fill = con.execute("""
        SELECT COALESCE(sum(f.w), 0), COALESCE(sum(f.w) FILTER (WHERE zf.m IS NOT NULL), 0)
        FROM flow f
        JOIN pair_zero z ON z.importer = f.imp_iso AND z.exporter = f.exp_iso AND z.hs4 = f.hs4
        LEFT JOIN cmap ge ON ge.iso = f.exp_iso
        LEFT JOIN zfill zf ON zf.imp_iso = f.imp_iso AND zf.sector = f.sector AND zf.cls = ge.geo AND ge.geo = f.imp_geo
        WHERE f.exp_reg IS NOT NULL AND f.imp_reg IS NOT NULL
    """).fetchone()
    con.execute("""
        CREATE TABLE pair_agg AS
        SELECT exp_reg, imp_reg, sector,
               sum(w) AS w,
               sum(CASE WHEN m IS NOT NULL THEN w ELSE 0 END) AS wok,
               sum(CASE WHEN m IS NOT NULL THEN w * m ELSE 0 END) AS wm,
               sum(CASE WHEN lvl = 1 THEN w ELSE 0 END) AS w1,
               sum(CASE WHEN lvl = 2 THEN w ELSE 0 END) AS w2,
               sum(CASE WHEN lvl = 3 THEN w ELSE 0 END) AS w3,
               0.0 AS w4,
               sum(CASE WHEN lvl = 4 THEN w ELSE 0 END) AS w5
        FROM (
            SELECT f.exp_reg, f.imp_reg, f.sector, f.w,
                   CASE WHEN p.r IS NOT NULL THEN p.r / (1 - p.r)
                        WHEN z.hs4 IS NOT NULL AND zf.m IS NOT NULL THEN zf.m
                        WHEN h.r IS NOT NULL THEN h.r / (1 - h.r)
                        WHEN t.r IS NOT NULL THEN t.r / (1 - t.r)
                        WHEN g.r IS NOT NULL THEN g.r / (1 - g.r) END AS m,
                   CASE WHEN p.r IS NOT NULL THEN 1
                        WHEN z.hs4 IS NOT NULL AND zf.m IS NOT NULL THEN 2
                        WHEN h.r IS NOT NULL THEN 2
                        WHEN t.r IS NOT NULL THEN 3
                        WHEN g.r IS NOT NULL THEN 4 END AS lvl
            FROM flow f
            LEFT JOIN pair_hs4 p ON p.importer = f.imp_iso AND p.exporter = f.exp_iso AND p.hs4 = f.hs4
            LEFT JOIN pair_zero z ON z.importer = f.imp_iso AND z.exporter = f.exp_iso AND z.hs4 = f.hs4
            LEFT JOIN cmap ge ON ge.iso = f.exp_iso
            LEFT JOIN zfill zf ON zf.imp_iso = f.imp_iso AND zf.sector = f.sector AND zf.cls = ge.geo AND ge.geo = f.imp_geo
            LEFT JOIN world_hs4 h ON h.importer = f.imp_iso AND h.hs4 = f.hs4
            LEFT JOIN pair_tot t ON t.importer = f.imp_iso AND t.exporter = f.exp_iso
            LEFT JOIN f7 g ON g.geo = f.imp_geo AND g.hs4 = f.hs4
            WHERE f.exp_reg IS NOT NULL AND f.imp_reg IS NOT NULL
        ) q
        GROUP BY 1, 2, 3
    """)
    def agg_row(w, wok, wm, w1, w2, w3, w4, w5):
        return dict(w=as_float(w), wok=as_float(wok), wm=as_float(wm),
                    w1=as_float(w1), w2=as_float(w2), w3=as_float(w3), w4=as_float(w4), w5=as_float(w5))

    pair = {}
    for exp, imp, sec, w, wok, wm, w1, w2, w3, w4, w5 in con.execute('SELECT * FROM pair_agg').fetchall():
        pair[(exp, imp, sec)] = agg_row(w, wok, wm, w1, w2, w3, w4, w5)
    # Bilateral _T at region level. Used when a route has no HS6 basket. Weighted by
    # any-sector BACI member-pair flows when those exist; otherwise the unweighted mean.
    con.execute("""
        CREATE TABLE pair_tot_reg AS
        SELECT er.region AS exp_reg, ir.region AS imp_reg,
               sum(CASE WHEN COALESCE(iw.w, 0) > 0 THEN iw.w ELSE 0 END) AS w,
               sum(CASE WHEN COALESCE(iw.w, 0) > 0 THEN iw.w * p.r / (1 - p.r) ELSE 0 END) AS wm,
               avg(p.r / (1 - p.r)) AS m_unw
        FROM pair_tot p
        JOIN cmap er ON er.iso = p.exporter
        JOIN cmap ir ON ir.iso = p.importer
        LEFT JOIN (
            SELECT exp_iso, imp_iso, sum(w) AS w FROM flow GROUP BY 1, 2
        ) iw ON iw.exp_iso = p.exporter AND iw.imp_iso = p.importer
        GROUP BY 1, 2
    """)
    pair_tot_reg = {}
    for exp_r, imp_r, w, wm, m_unw in con.execute('SELECT * FROM pair_tot_reg').fetchall():
        w, wm, m_unw = as_float(w), as_float(wm), as_float(m_unw)
        m = wm / w if w > 0 else m_unw
        if m == m and m >= 0:
            pair_tot_reg[(exp_r, imp_r)] = m
    member_w = {iso: as_float(w) for iso, w in con.execute(
        "SELECT imp_iso, sum(w) FROM flow WHERE imp_reg IS NOT NULL GROUP BY 1").fetchall()}
    world_tot = {iso: as_float(r) for iso, r in con.execute('SELECT importer, r FROM world_tot').fetchall()}
    f7sec = {(geo, sec): as_float(r) for geo, sec, r in con.execute("""
        SELECT g.geo, c.sector, median(g.r)
        FROM f7 g
        JOIN (SELECT DISTINCT substr(hs6, 1, 4) AS hs4, sector FROM concord) c ON c.hs4 = g.hs4
        GROUP BY 1, 2
    """).fetchall()}
    meta = {
        'conflict': 0,
        'code_conflict': n_code_conflict,
        'status': status_rows,
        'n_pair': con.execute('SELECT count(*) FROM pair_hs4').fetchone()[0],
        'n_importers': con.execute('SELECT count(DISTINCT importer) FROM itic_u').fetchone()[0],
        'prk': con.execute("SELECT count(*) FROM itic_u WHERE importer = 'PRK'").fetchone()[0],
        'gnq': con.execute("SELECT count(*) FROM itic_u WHERE importer = 'GNQ'").fetchone()[0],
        'che_partners': con.execute("SELECT count(DISTINCT exporter) FROM pair_hs4 WHERE importer = 'CHE'").fetchone()[0],
        'kor_sau_2709': con.execute(
            "SELECT r FROM pair_hs4 WHERE importer = 'KOR' AND exporter = 'SAU' AND hs4 = '2709'").fetchone(),
        'pair_tot_q': con.execute(
            "SELECT quantile_cont(r, 0.01), quantile_cont(r, 0.50), quantile_cont(r, 0.99), count(*) FROM pair_tot").fetchone(),
        'lpg': con.execute("""
            SELECT hs6, sector, share FROM concord WHERE hs6 LIKE '2711%' ORDER BY 1, 2
        """).fetchall(),
    }
    log(f'pair baskets {len(pair)} bilateral totals {len(pair_tot_reg)}')
    return dict(pair=pair, member_w=member_w, world_tot=world_tot, f7sec=f7sec,
                pair_tot_reg=pair_tot_reg, meta=meta, con=con, gas_pipe=gas_pipe, lng_fob=lng_fob,
                zero_fill=dict(zero_w=as_float(zero_fill[0]), filled_w=as_float(zero_fill[1])))


def route_importer_rates(con, keys, log):
    """Routes with no BACI pair basket keep the importer's HS4 weights.

    Each weight takes the route's own ITIC rate in the configured order:
    pair HS4, importer-world HS4, pair `_T`, importer-world `_T`, then F7.
    A composite exporter with no flow on the route uses the unweighted mean
    of the member rates that exist. threads=1 keeps the mean stable.
    """
    log(f'no-BACI routes {len(keys)}')
    con.execute("SET memory_limit='4GB'")
    con.execute("""
        CREATE TABLE imp_hs AS
        SELECT imp_reg, sector, imp_iso, hs4, any_value(imp_geo) AS imp_geo, sum(w) AS w
        FROM flow
        WHERE imp_reg IS NOT NULL
        GROUP BY 1, 2, 3, 4
    """)
    log('importer HS4 weights ready')
    con.execute("""
        CREATE TABLE exp_hs AS
        SELECT e.region AS exp_reg, p.importer AS imp_iso, p.hs4,
               avg(p.r / (1 - p.r) ORDER BY p.exporter) AS m
        FROM pair_hs4 p
        JOIN cmap e ON e.iso = p.exporter
        WHERE p.r >= 0 AND p.r < 1
        GROUP BY 1, 2, 3
    """)
    con.execute("""
        CREATE TABLE exp_tot AS
        SELECT e.region AS exp_reg, p.importer AS imp_iso,
               avg(p.r / (1 - p.r) ORDER BY p.exporter) AS m
        FROM pair_tot p
        JOIN cmap e ON e.iso = p.exporter
        WHERE p.r >= 0 AND p.r < 1
        GROUP BY 1, 2
    """)
    log('route ITIC rates ready')
    rows = {}
    bad = 0
    step = 8000
    for start in range(0, max(len(keys), 1), step):
        part = keys[start:start + step]
        if not part and keys:
            continue
        con.execute('DROP TABLE IF EXISTS need')
        con.execute('DROP TABLE IF EXISTS route_cell')
        con.execute('CREATE TABLE need (exp_reg VARCHAR, imp_reg VARCHAR, sector VARCHAR)')
        if part:
            con.executemany('INSERT INTO need VALUES (?, ?, ?)', part)
        con.execute("""
            CREATE TABLE route_cell AS
            SELECT n.exp_reg, n.imp_reg, n.sector, i.imp_iso, i.hs4, i.w,
                   CASE WHEN ph.m IS NOT NULL THEN ph.m
                        WHEN h.r IS NOT NULL THEN h.r / (1 - h.r)
                        WHEN pt.m IS NOT NULL THEN pt.m
                        WHEN wt.r IS NOT NULL THEN wt.r / (1 - wt.r)
                        WHEN g.r IS NOT NULL AND g.r >= 0 AND g.r < 1 THEN g.r / (1 - g.r) END AS m,
                   CASE WHEN ph.m IS NOT NULL THEN 1
                        WHEN h.r IS NOT NULL THEN 2
                        WHEN pt.m IS NOT NULL THEN 3
                        WHEN wt.r IS NOT NULL THEN 4
                        WHEN g.r IS NOT NULL AND g.r >= 0 AND g.r < 1 THEN 5 END AS lvl,
                   CASE WHEN ph.m IS NOT NULL OR h.r IS NOT NULL OR pt.m IS NOT NULL OR wt.r IS NOT NULL THEN 1 ELSE 0 END AS has_itic
            FROM need n
            JOIN imp_hs i ON i.imp_reg = n.imp_reg AND i.sector = n.sector
            LEFT JOIN exp_hs ph ON ph.exp_reg = n.exp_reg AND ph.imp_iso = i.imp_iso AND ph.hs4 = i.hs4
            LEFT JOIN world_hs4 h ON h.importer = i.imp_iso AND h.hs4 = i.hs4
            LEFT JOIN exp_tot pt ON pt.exp_reg = n.exp_reg AND pt.imp_iso = i.imp_iso
            LEFT JOIN world_tot wt ON wt.importer = i.imp_iso
            LEFT JOIN f7 g ON g.geo = i.imp_geo AND g.hs4 = i.hs4
        """)
        bad += con.execute('SELECT count(*) FROM route_cell WHERE lvl = 5 AND has_itic = 1').fetchone()[0]
        for exp, imp, sec, w, wok, wm, w1, w2, w3, w4, w5 in con.execute("""
            SELECT exp_reg, imp_reg, sector,
                   sum(w ORDER BY imp_iso, hs4) AS w,
                   sum(CASE WHEN m IS NOT NULL THEN w ELSE 0 END ORDER BY imp_iso, hs4) AS wok,
                   sum(CASE WHEN m IS NOT NULL THEN w * m ELSE 0 END ORDER BY imp_iso, hs4) AS wm,
                   sum(CASE WHEN lvl = 1 THEN w ELSE 0 END ORDER BY imp_iso, hs4) AS w1,
                   sum(CASE WHEN lvl = 2 THEN w ELSE 0 END ORDER BY imp_iso, hs4) AS w2,
                   sum(CASE WHEN lvl = 3 THEN w ELSE 0 END ORDER BY imp_iso, hs4) AS w3,
                   sum(CASE WHEN lvl = 4 THEN w ELSE 0 END ORDER BY imp_iso, hs4) AS w4,
                   sum(CASE WHEN lvl = 5 THEN w ELSE 0 END ORDER BY imp_iso, hs4) AS w5
            FROM route_cell
            GROUP BY 1, 2, 3
        """).fetchall():
            rows[(exp, imp, sec)] = dict(
                w=as_float(w), wok=as_float(wok), wm=as_float(wm),
                w1=as_float(w1), w2=as_float(w2), w3=as_float(w3), w4=as_float(w4), w5=as_float(w5))
        if start and start % 40000 == 0:
            log(f'no-BACI progress {start} of {len(keys)}')
    log(f'importer-weighted routes {len(rows)}; F7 cells with an earlier ITIC rate {bad}')
    return rows, int(bad)


def rescue_bare(con, bare, log):
    """A route with no product weights still must not take F7 while an ITIC rate exists.

    The rate is the unweighted mean of the member rates, in the same order:
    pair HS4 in the sector, importer-world HS4, pair total, importer-world total.
    """
    if not bare:
        return {}
    con.execute('DROP TABLE IF EXISTS bare')
    con.execute('CREATE TABLE bare (exp_reg VARCHAR, imp_reg VARCHAR, sector VARCHAR)')
    con.executemany('INSERT INTO bare VALUES (?, ?, ?)', bare)
    found = {}
    order = (
        ('pair_hs4', 'sector_pair_hs4', [1.0, 0.0, 0.0, 0.0, 0.0], 'm1'),
        ('importer_world_hs4', 'sector_world_hs4', [0.0, 1.0, 0.0, 0.0, 0.0], 'm2'),
        ('pair_total', 'sector_pair_total', [0.0, 0.0, 1.0, 0.0, 0.0], 'm3'),
        ('importer_world_total', 'sector_world_total', [0.0, 0.0, 0.0, 1.0, 0.0], 'm4'),
    )
    for exp, imp, sec, m1, m2, m3, m4 in con.execute("""
        SELECT b.exp_reg, b.imp_reg, b.sector,
          (SELECT avg(p.r / (1 - p.r) ORDER BY p.exporter, p.hs4)
           FROM pair_hs4 p
           JOIN cmap e ON e.iso = p.exporter AND e.region = b.exp_reg
           JOIN cmap i ON i.iso = p.importer AND i.region = b.imp_reg
           JOIN (SELECT DISTINCT substr(hs6, 1, 4) AS hs4, sector FROM concord) c
             ON c.hs4 = p.hs4 AND c.sector = b.sector),
          (SELECT avg(w.r / (1 - w.r) ORDER BY w.hs4)
           FROM world_hs4 w
           JOIN cmap i ON i.iso = w.importer AND i.region = b.imp_reg
           JOIN (SELECT DISTINCT substr(hs6, 1, 4) AS hs4, sector FROM concord) c
             ON c.hs4 = w.hs4 AND c.sector = b.sector),
          (SELECT avg(p.r / (1 - p.r) ORDER BY p.exporter)
           FROM pair_tot p
           JOIN cmap e ON e.iso = p.exporter AND e.region = b.exp_reg
           JOIN cmap i ON i.iso = p.importer AND i.region = b.imp_reg),
          (SELECT avg(w.r / (1 - w.r) ORDER BY w.importer)
           FROM world_tot w
           JOIN cmap i ON i.iso = w.importer AND i.region = b.imp_reg)
        FROM bare b
    """).fetchall():
        vals = {'m1': m1, 'm2': m2, 'm3': m3, 'm4': m4}
        chosen = None
        for level, basis, sh, key in order:
            m = vals[key]
            if m is None:
                continue
            m = as_float(m)
            if m == m and m >= 0:
                chosen = (m, level, sh, basis)
                break
        if chosen:
            found[(exp, imp, sec)] = chosen
            log(f'rescued bare route {exp}->{imp} {sec} at {chosen[1]} m {chosen[0]:.6f}')
    return found


def census_shares(hs6_path, concord_path):
    conc = {}
    with open(concord_path, newline='') as fh:
        for row in csv.DictReader(fh):
            if not row.get('share'):
                continue
            share = float(row['share'])
            if share <= 0 or not row.get('sector'):
                continue
            conc.setdefault(row['hs22'].zfill(6), []).append((row['sector'], share))
    acc = {s: [0.0, 0.0, 0.0, 0.0] for s in GOODS}  # val, cha, air, ves
    un_val = un_cha = 0.0
    n = 0
    import json
    data = json.load(open(hs6_path))
    header = data[0]
    ix = {name: i for i, name in enumerate(header)}
    for rec in data[1:]:
        n += 1
        hs = rec[ix['I_COMMODITY']].zfill(6)
        val = float(rec[ix['GEN_VAL_YR']] or 0)
        cha = float(rec[ix['GEN_CHA_YR']] or 0)
        air = float(rec[ix['AIR_CHA_YR']] or 0)
        ves = float(rec[ix['VES_CHA_YR']] or 0)
        hits = conc.get(hs)
        if not hits:
            un_val += val
            un_cha += cha
            continue
        for sector, share in hits:
            if sector not in acc:
                continue
            acc[sector][0] += val * share
            acc[sector][1] += cha * share
            acc[sector][2] += air * share
            acc[sector][3] += ves * share
    shares = {}
    missing = []
    for sector, (val, cha, air, ves) in acc.items():
        if cha <= 0:
            missing.append(sector)
            continue
        sea = ves / cha
        air_s = air / cha
        rdt = 1.0 - sea - air_s
        shares[sector] = (rdt, sea, air_s, val, cha)
    world_cha = sum(v[1] for v in acc.values())
    world_ves = sum(v[3] for v in acc.values())
    world_air = sum(v[2] for v in acc.values())
    return shares, missing, dict(rows=n, un_val=un_val, un_cha=un_cha,
                                 world_cha=world_cha, world_ves=world_ves, world_air=world_air,
                                 world_val=sum(v[0] for v in acc.values()))


def census_partners(path):
    import json
    data = json.load(open(path))
    ix = {name: i for i, name in enumerate(data[0])}
    acc = {}
    for rec in data[1:]:
        comm = rec[ix['I_COMMODITY']]
        if not (len(comm) == 2 and comm.isdigit()):
            continue
        code = rec[ix['CTY_CODE']].strip()
        name = rec[ix['CTY_NAME']].strip()
        if code in ('', '-') or 'X' in code.upper() or code.startswith('00') or 'TOTAL' in name.upper():
            continue
        val = float(rec[ix['GEN_VAL_YR']] or 0)
        cha = float(rec[ix['GEN_CHA_YR']] or 0)
        slot = acc.setdefault(code, [name, 0.0, 0.0])
        slot[1] += val
        slot[2] += cha
    ranked = sorted(acc.items(), key=lambda kv: -kv[1][1])
    return ranked[:15]


def census_energy_rates(imdb_hs6_path, hs2_json_path, by_norm, iso_region, min_val=CENSUS_MIN_VALUE):
    """energy_sea_rate: US Census IMDB 2022, m = (con_cif - con_val) / con_val by exporter region for HS 2709 (oil) and
    2710 (pet). Import charges over customs value are a margin rate on FOB (GTAP 7 ch.9A p.3: the aggregate cost of
    freight, insurance and other transport costs in the US import data). An exporter region with less than min_val of
    customs value takes the fallback: the value-weighted rate of every exporter except Canada (pipeline and rail).
    Returns (rates {(sector, region): m}, fallback {sector: m}, value {(sector, region): con_val}, unmatched countries)."""
    import json
    with open(hs2_json_path) as fh:
        hs2 = json.load(fh)
    ix = {n: i for i, n in enumerate(hs2[0])}
    name_of = {r[ix['CTY_CODE']].strip(): r[ix['CTY_NAME']].strip() for r in hs2[1:]}
    acc = defaultdict(lambda: [0.0, 0.0])
    fb = defaultdict(lambda: [0.0, 0.0])
    unmatched = set()
    for r in read_csv(imdb_hs6_path):
        sec = ENERGY_HS4.get(r['hs6'][:4])
        if not sec:
            continue
        val = float(r['con_val'])
        cha = float(r['con_cif']) - val
        if val <= 0:
            continue
        nm = name_of.get(r['cty'].strip(), '')
        iso = match_partner(nm, by_norm) or CENSUS_ENERGY_ALIAS.get(norm_name(nm), '')
        if not iso:
            unmatched.add(r['cty'].strip())
            continue
        reg = iso_region.get(iso, iso)
        acc[(sec, reg)][0] += val
        acc[(sec, reg)][1] += cha
        if iso != 'CAN':
            fb[sec][0] += val
            fb[sec][1] += cha
    rates = {k: c / v for k, (v, c) in acc.items() if v >= min_val}
    fallback = {s_: c / v for s_, (v, c) in fb.items() if v > 0}
    value = {k: v for k, (v, _c) in acc.items()}
    return rates, fallback, value, sorted(unmatched)


def census_route_parts(m_itic, m_census, mode):
    """energy_sea_rate on one route: the sea part takes the Census rate, rdt and air keep the ITIC rate.
    mode: (rdt, sea, air) shares of the route's margin. Returns (m, (rdt, sea, air)) with m = sea x m_census +
    (rdt + air) x m_itic and the shares of the new margin by mode."""
    rdt, sea, air = mode
    parts = (rdt * m_itic, sea * m_census, air * m_itic)
    m = sum(parts)
    if m <= 0:
        return m_itic, mode
    return m, tuple(x / m for x in parts)


def census_route_whole(m_itic, m_census, mode, pipe):
    """beta v4 G5 (energy_sea_rate = us_census_exporter_hs4_whole_route): the Census charge is the whole-route margin
    outside crude pipelines. mode: (rdt, sea, air) prior shares of the route's margin; pipe: the pipeline share (the rdt
    share of crude, 0 for products). Returns (m, (rdt, sea, air), census_share) with m = pipe x m_itic +
    (1 - pipe) x m_census, the Census part spread over the non-pipeline modes by their prior shares."""
    rdt, sea, air = mode
    rest = (rdt - pipe, sea, air)
    tot = sum(rest)
    if tot <= 0:
        return m_itic, mode, 0.0
    parts = (pipe * m_itic + (1.0 - pipe) * m_census * rest[0] / tot, (1.0 - pipe) * m_census * sea / tot,
             (1.0 - pipe) * m_census * air / tot)
    m = sum(parts)
    if m <= 0:
        return m_itic, mode, 0.0
    return m, tuple(x / m for x in parts), 1.0 - pipe


def lng_voyage_cost(nm, canal, price, P):
    """beta v4 P7: 2022 LNG voyage cost, USD per MMBtu delivered, for a round trip of nm nautical miles each way:
    charter x days + port fees + canal toll + (laden boil-off + ballast fuel) x sea days x cargo value + insurance x cargo value,
    over the cargo. price: the exporter's FOB price (USD/MMBtu). P: config/s08/lng_voyage.csv values."""
    sea = nm / (P['speed_knots'] * 24.0)
    days = 2.0 * sea + P['port_days'] + (P['canal_days'] if canal else 0.0)
    val = P['cargo_mmbtu'] * price
    toll = {'suez': P['toll_suez_usd'], 'panama': P['toll_panama_usd']}.get(canal, 0.0)
    c = (P['charter_usd_day'] * days + P['port_fees_usd'] + toll
         + (P['boiloff_laden_per_day'] + P['fuel_ballast_per_day']) * sea * val + P['insurance_share'] * val)
    return c / P['cargo_mmbtu']


def lng_route_parts(m_itic, lng_share, m_lng):
    """beta v4 P7 on one gas route: the pipeline part keeps ITIC (rdt), the LNG part takes m_lng (sea).
    Returns (m, (rdt, sea, air)) with the shares of the new margin by mode."""
    parts = ((1.0 - lng_share) * m_itic, lng_share * m_lng, 0.0)
    m = sum(parts)
    if m <= 0:
        return m_itic, (1.0 - lng_share, lng_share, 0.0)
    return m, tuple(x / m for x in parts)


def match_partner(name, by_norm):
    key = norm_name(name)
    if key in NAME_ALIAS:
        return NAME_ALIAS[key]
    return by_norm.get(key, '')


def read_tismos(zip_path, iso2_map):
    """Mode-1 world freight exports. Values are USD million. A zero row is a present reporter."""
    by = {}  # iso -> {mode: value}
    present = set()
    unmapped = {}
    world = {m: 0.0 for m in MODES}
    world_reporter = {m: 0.0 for m in MODES}
    indicator = {v: k for k, v in SC_TISMOS.items()}
    with zipfile.ZipFile(zip_path) as z:
        with z.open('TiSMoS - Exports.csv') as raw:
            text = (line.decode('utf-8-sig') for line in raw)
            for row in csv.DictReader(text):
                if row.get('YEAR') != '2022' or row.get('MODE') != 'Mode 1' or row.get('PARTNER') != 'World':
                    continue
                mode = indicator.get(row.get('INDICATOR', ''))
                if not mode:
                    continue
                val_s = (row.get('VALUE') or '').strip().replace(',', '')
                if val_s == '':
                    continue
                val = float(val_s)
                world[mode] += val
                code = (row.get('REPORTER_CODE') or '').strip()
                if code == 'WL':
                    world_reporter[mode] += val
                iso = iso2_map.get(code)
                if not iso:
                    unmapped[code] = unmapped.get(code, 0.0) + val
                    continue
                present.add(iso)
                slot = by.setdefault(iso, {m: 0.0 for m in MODES})
                slot[mode] += val
    return by, present, unmapped, world, world_reporter


def iso2_map(ctry_path, alias_rows):
    out = {}
    for row in alias_rows:
        if row['source'] == 'TiSMoS' and row['code'].startswith('TiSMoS:'):
            out[row['code'].split(':', 1)[1]] = row['iso3']
    general = {row['code']: row['iso3'] for row in alias_rows if not row['code'].startswith('TiSMoS:')}
    with open(ctry_path, newline='') as fh:
        for row in csv.DictReader(fh):
            i2 = (row.get('country_iso2') or '').strip()
            i3 = (row.get('country_iso3') or '').strip()
            if not i2 or not i3:
                continue
            i3 = general.get(i3, i3)
            if i2 not in out:
                out[i2] = i3
    for code, iso in list(out.items()):
        out[code] = general.get(iso, iso)
    return out


def read_batis(path, general_alias):
    out = {}
    with open(path, newline='') as fh:
        for row in csv.DictReader(fh):
            iso = general_alias.get(row['ref_area'], row['ref_area'])
            mode = next((m for m, sc in SC_BATIS.items() if sc == row['service']), None)
            if not mode:
                continue
            out[(iso, mode)] = out.get((iso, mode), 0.0) + float(row['obs_value'])
    return out


def load_output(path, col='OUT'):
    out = {m: {} for m in MODES}
    with gzip.open(path, 'rt', newline='') as fh:
        for row in csv.DictReader(fh):
            mode = ROW_MODE.get(row['row'])
            if mode:
                out[mode][row['region']] = float(row[col])
    return out


def pipeline_share(sector, exp, imp, oil_cfg, gas_pipe, gas_exp_tot):
    """Pipeline share of an energy route's margin (Fable QA C-05); the rest goes by sea. Crude: the configured
    pipeline routes, else tanker. Gas: BACI HS 271121 (pipeline gas) over 271121 + 271111 (LNG) on the route,
    else the exporter's, else all pipeline. Returns (share, source)."""
    if sector == 'oil':
        return oil_cfg.get((exp, imp), 0.0), ('oil_pipeline_route' if (exp, imp) in oil_cfg else 'oil_tanker')
    pl = gas_pipe.get((exp, imp))
    et = gas_exp_tot.get(exp)
    if pl and pl[0] + pl[1] > 0:
        return pl[0] / (pl[0] + pl[1]), 'gas_baci_route'
    if et and et[0] + et[1] > 0:
        return et[0] / (et[0] + et[1]), 'gas_baci_exporter'
    return 1.0, 'gas_no_hs6_pipeline'


def own_carrier_key(fx, fm, into, out):
    """VST key of one region and mode (Fable QA D-03): BoP freight exports fx plus the freight on its own
    imports (VTWR into the region) that foreign carriers' freight exports to it (fm) do not cover, capped at
    the region's output of the mode (out) left after fx, since resident carriers supply it from that output.
    Returns (key, own-carrier part)."""
    own = min(max(0.0, into - fm), max(0.0, out - fx))
    return fx + own, own


def batis_freight(ebops_path, tismos_path, region_order, log):
    """BoP freight by region and mode, USD m: fx[mode][exporter] and fm[mode][importer] are BaTIS SC1/SC2/SC3
    bilateral exports times the exporter's TiSMoS freight leaf share (SC12, SC22, SC32), chosen as S09 does
    (own TiSMoS row, else the GTAP geographic region, else the world). share_src[(region, mode)] is that source."""
    (iso_to_region, _status, regions, _members, iso_geo, alias_iso, tismos_alias, aggregates, tismos_agg,
     _wdi_agg, region_isos) = S9.load_maps()
    flows = S9.load_batis(ebops_path, {'SC1', 'SC2', 'SC3'}, set(), iso_to_region, alias_iso, aggregates, log)[0]
    by_iso, tis_world, _names, _unmapped = S9.load_tismos(tismos_path, tismos_alias, tismos_agg, log)
    share = {}
    share_src = {}
    parent_mode = {parent: mode for mode, (parent, _leaf) in S9.FREIGHT_LEAF.items()}
    for region in region_order:
        geos = [g for g in (regions.get(region, {}).get('gtap_geo') or '').split('+') if g]
        own, any_row = S9.region_tismos(region, region_isos, by_iso)
        for mode, (parent, leaf) in S9.FREIGHT_LEAF.items():
            shares, source, _vals = S9.choose_shares(region, parent, S9.SPLIT_LEAVES[parent], own, any_row, geos,
                                                     iso_geo, by_iso, tis_world)
            share[(region, mode)] = shares[leaf] if shares else 0.0
            share_src[(region, mode)] = source
    fx = {m: defaultdict(float) for m in MODES}
    fm = {m: defaultdict(float) for m in MODES}
    for (exp, imp, svc), val in flows.items():
        mode = parent_mode[svc]
        f = val * share.get((exp, mode), 0.0)
        fx[mode][exp] += f
        fm[mode][imp] += f
    return fx, fm, share_src


def no_seaport_keys(keys, mode_source, regions):
    """Beta v4 P21 (choice no_seaport_sea_key): a listed region with no seaport cannot carry sea freight on its own
    ships' behalf at the scale BaTIS SC1 implies, so its sea key moves to its road key (keys are shares, so the sea VST
    goes to the other sea carriers). Returns {region: sea key moved}."""
    moved = {}
    for region in regions:
        k = keys['sea'].get(region, 0.0)
        if region in keys['sea']:
            keys['rdt'][region] = keys['rdt'].get(region, 0.0) + k
            keys['sea'][region] = 0.0
            mode_source[(region, 'sea')] = 'no_seaport_zero'
            moved[region] = k
    return moved


F8_FLOOR_MUSD = 0.01


def cap_filled(vst, filled, cap, total, iters=100):
    """Cap each filled (F8) cell at cap[region] (the region's own I-O exports of the mode), with a floor of
    F8_FLOOR_MUSD, and give the excess to the other cells in proportion, so the mode still adds up to total.
    Water-filling: a filled cell that the rescaling pushes above its cap is capped in the next round."""
    v = dict(vst)
    fixed = {}
    for _ in range(iters):
        for r in filled:
            if r not in fixed and v[r] > max(cap.get(r, 0.0), F8_FLOOR_MUSD):
                fixed[r] = max(cap.get(r, 0.0), F8_FLOOR_MUSD)
        for r in filled:
            if r not in fixed and v[r] < F8_FLOOR_MUSD:
                fixed[r] = F8_FLOOR_MUSD
        free = [r for r in v if r not in fixed]
        rest = sum(v[r] for r in free)
        scale = (total - sum(fixed.values())) / rest if rest > 0 else 0.0
        new = {r: fixed[r] if r in fixed else v[r] * scale for r in v}
        if all(abs(new[r] - v[r]) <= 1e-12 * max(1.0, abs(v[r])) for r in v) and \
           not any(new[r] > max(cap.get(r, 0.0), F8_FLOOR_MUSD) * (1 + 1e-12) for r in filled if r not in fixed):
            return new, fixed
        v = new
    return v, fixed


def wpercentile(pairs, p):
    total = sum(w for _r, w in pairs)
    if total <= 0:
        return None
    target = p * total
    acc = 0.0
    last = pairs[-1][0]
    for r, w in pairs:
        acc += w
        last = r
        if acc >= target:
            return r
    return last


def load_preview():
    paths = [os.environ.get('S08_PREVIEW_CSV', '').strip(), '/tmp/s08_preview.csv',]
    for path in paths:
        if path and os.path.exists(path):
            got = {}
            with open(path, newline='') as fh:
                for row in csv.DictReader(fh):
                    got[(row['scope'], row['sector'], row['item'])] = float(row['value'])
            got['_path'] = path
            return got
    return {}


def forbidden(path):
    """Private paths only (config/repo_rules.csv, David 2026-10-23). Raw data is committed."""
    return is_private(path)


def git_names():
    """Paths this branch adds. H9 is the diff, not files already in the parent."""
    root = repo_root()
    names = []
    for args in (
        ['git', '-C', root, 'diff', '--name-only', S07_HEAD],
        ['git', '-C', root, 'diff', '--cached', '--name-only', S07_HEAD],
        ['git', '-C', root, 'status', '--porcelain'],
    ):
        out = subprocess.run(args, capture_output=True, text=True).stdout
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            if args[-1] == '--porcelain':
                line = line[3:] if len(line) > 3 else line
                if ' -> ' in line:
                    line = line.split(' -> ', 1)[1]
            names.append(line.strip().strip('"'))
    stat = subprocess.run(['git', '-C', root, 'diff', '--stat', S07_HEAD], capture_output=True, text=True).stdout
    return names, stat


def output_sums_text(directory):
    parts = []
    for fn in sorted(os.listdir(directory)):
        if fn == 'SHA256SUMS':
            continue
        parts.append(f'{sha256(directory + "/" + fn)}  {fn}\n')
    return ''.join(parts)


def freeze_mode_share(rdt, sea, air):
    sea_s = float(f'{sea:.12f}')
    air_s = float(f'{air:.12f}')
    rdt_s = 1.0 - sea_s - air_s
    return rdt_s, sea_s, air_s


def run(S, brief):
    choice_path = BUILD + '/config/s08/margin_choices.csv'
    S.inp(choice_path, 'S08 margin choices; the stage reads every value from this file')
    choices, choice_rows, choice_bad = load_choices(choice_path)
    brief['choices'] = choice_rows
    brief['choice_values'] = choices
    h1_ok = not choice_bad and len(choice_rows) == len(CHOICE_ORDER)
    S.check('S08-H1', f'margin_choices.csv has the {len(CHOICE_ORDER)} choices, each with decided_by, decided_at and a value in its allowed set',
            'hard', f'{len(choice_rows)} rows; {len(choice_bad)} problems', f'{len(CHOICE_ORDER)} rows; 0 problems', h1_ok,
            'config/s08/margin_choices.csv', '; '.join(choice_bad))
    if not h1_ok:
        S.finish()
        return

    global GOODS, GOODS_SET
    GOODS = load_goods_sectors()
    GOODS_SET = set(GOODS)
    S.inp(BUILD + '/config/s07/trade_choices.csv', 'S07 goods_sectors token; S08 does not keep a second goods list')
    # s07_vxsb_value is retired. H1 rejects it because it is not in ALLOWED.
    vx_name = 'vxsb_goods_s07r.csv.gz'
    value_col = 'vfob_musd'
    brief['value_col'] = value_col
    brief['vx_name'] = vx_name

    s07 = S.upstream(ROOT + '/stages/S07_trade')
    s01 = S.upstream(ROOT + '/stages/S01_sets_registry')
    bind_ok, bind_detail = bind_s07(vx_name)
    S.check('S08-G0bind',
            f'S07 upstream is head {S07_HEAD[:7]}, STAMP {S07_STAMP_TIME}, SHA256SUMS {S07_SHA256SUMS[:8]}, goods file {S07_VXSB_SHA[:8]}',
            'hard', 'bound' if bind_ok else 'NOT BOUND', 'bound', bind_ok, 'S07R snapshot', bind_detail)
    vxsb_path = S.inp(s07 + '/output/' + vx_name, f'S07 goods base column {value_col}; summed over source on the triple')
    io_path = S.inp(s07 + '/output/io_s07.csv.gz', 'S07 I-O, copied byte for byte to io_s08')
    regions_path = S.inp(s01 + '/output/regions.csv', 'S01 region list')
    cmap_path = S.inp(s01 + '/output/country_region_map.csv', 'S01 country to region and GTAP geographic region')
    comp_path = S.inp(s01 + '/output/composite_members.csv', 'S01 composite members')
    geo_path = S.inp(s01 + '/output/gtap_geo_regions_table910.csv', 'S01 GTAP geographic regions')
    hs17_path = S.inp(s01 + '/output/concord_hs17_to_sector.csv', 'S01 HS17 to sector concordance')
    hs22_path = S.inp(s01 + '/output/concord_hs22_to_sector.csv', 'S01 HS22 to sector concordance')
    sectors_path = S.inp(s01 + '/output/sectors.csv', 'S01 sector order')
    alias_path = S.inp(BUILD + '/config/s01/source_aliases.csv', 'S01 source aliases (BACI 490/S19, PSE, TiSMoS, BaTIS)')
    baci_path = S.inp(DATA + '/baci/BACI_HS17_V202601.zip', 'BACI HS17 V202601, 2022 FOB weights')
    itic_path = S.inp(DATA + '/oecd_itic/hs4_2022/itic_hs4_pt_im_cif_2022.csv.gz', 'OECD ITIC 2022 HS4 PT_IM_CIF, reduced')
    tismos_path = S.inp(DATA + '/wto_tismos/gstdh_mode_supply_e.zip', 'WTO TiSMoS mode-1 freight exports')
    batis_path = S.inp(DATA + '/oecd_wto_batis/sc123_exports_world_2022.csv', 'BaTIS SC1 SC2 SC3 world exports, 2022, for F8')
    batis_key = choices['vst_allocation'] == 'batis_freight_plus_own_carrier_imports_capped'
    ebops_path = S.inp(DATA + '/oecd_wto_batis/ebops2022.csv', 'BaTIS EBOPS 2022 bilateral SC1 SC2 SC3, freight key') if batis_key else ''
    route_cfg = S.inp(BUILD + '/config/s08/energy_route_modes.csv', 'S08 crude pipeline routes (Fable QA C-05)')
    no_seaport = []
    if choices['no_seaport_sea_key'] == NO_SEAPORT_TO_ROAD:
        np_rows = read_csv(S.inp(BUILD + '/config/s08/' + NO_SEAPORT_FILE, 'beta v4 P21 regions with no seaport'))
        no_seaport = [r['region'].strip() for r in np_rows]
    if choices['mode_split'].startswith('us_census_charges_by_sector'):
        cen6 = S.inp(DATA + '/census_imports_hs_2022/imports_hs_hs6_charges_2022.json', 'US Census 2022 HS6 import charges')
        cen2 = S.inp(DATA + '/census_imports_hs_2022/imports_hs_hs2_cty_charges_2022.json', 'US Census 2022 HS2 import charges by country')
    else:
        cen6 = cen2 = ''

    sums, n_rows, n_rep, n_extra, n_neg, other_sector = load_vxsb(vxsb_path, value_col)
    brief['vxsb_rows'] = n_rows
    brief['n_rep'] = n_rep
    brief['n_extra'] = n_extra
    brief['n_triples'] = len(sums)
    S.log(f'VXSB source rows {n_rows}; triples {len(sums)}; triples with more than one source {n_rep}; extra source rows {n_extra} (bound note {REPEATED_TRIPLES_NOTE} repeating triples); negative rows {n_neg}; non-goods {other_sector}')

    weights = build_weights({
        'hs17': hs17_path, 'cmap': cmap_path, 'alias': alias_path, 'baci': baci_path, 'itic': itic_path,
    }, S.log, zero_rate=choices['itic_zero_rate'])
    if weights.get('conflict'):
        S.check('S08-H3', 'ITIC keys do not conflict and every rate satisfies 0 <= r < 1',
                'hard', f'{weights["conflict"]} conflicting ITIC keys', '0', False, Q_CIF, str(weights.get('status')))
        S.finish()
        return
    zf = weights['zero_fill']
    S.check('S08-R15', f'itic_zero_rate (beta v4 P27; David\'s call, default off) = {choices["itic_zero_rate"]}: BACI weight on routes whose ITIC '
            'pair HS4 rate is a published zero, and the part filled from the importer\'s same-region partners (the rest falls to the next rung '
            'unless the choice is off)', 'report', f'{zf["zero_w"] / 1e9:.1f} bn at zero; {zf["filled_w"] / 1e9:.1f} bn filled', '', True,
            'itic_zero_rate; GTAP 7 ch.9A p.9A-3 (US import charges are never zero); fill rule our choice', '')
    meta = weights['meta']
    brief['meta'] = {
        'status': meta['status'], 'n_importers': meta['n_importers'], 'prk': meta['prk'], 'gnq': meta['gnq'],
        'che_partners': meta['che_partners'], 'code_conflict': meta['code_conflict'], 'n_pair': meta['n_pair'],
        'pair_tot_q': meta['pair_tot_q'], 'lpg': meta['lpg'],
    }
    kor = meta['kor_sau_2709']
    brief['kor_raw_r'] = None if not kor else float(kor[0])
    S.log(f"ITIC importers {meta['n_importers']}; PRK rows {meta['prk']}; GNQ rows {meta['gnq']}; CHE partners {meta['che_partners']}; KOR<-SAU 2709 r {brief['kor_raw_r']}")

    regions = read_csv(regions_path)
    region_order = [r['region'] for r in regions]
    region_set = set(region_order)
    reg_i = {r: i for i, r in enumerate(region_order)}
    comps = {}
    comp_rows = read_csv(comp_path)
    for row in sorted(comp_rows, key=lambda r: (r['composite'], int(r['order']))):
        comps.setdefault(row['composite'], []).append(row['member'])
    members = {}
    for row in regions:
        if row['type'] == 'composite':
            members[row['region']] = comps.get(row['region'], row['members'].split())
        else:
            members[row['region']] = [row['region']]
    cmap_rows = read_csv(cmap_path)
    iso_geo = {}
    by_norm = {}
    for row in cmap_rows:
        if not row['region']:
            continue
        iso_geo[row['code']] = row['gtap_geo']
        key = norm_name(row['name'])
        if key and key not in by_norm:
            by_norm[key] = row['code']
    known_geo = {r['gtap_geo'] for r in read_csv(geo_path)}
    # The country-map row for the region code can be blank while the region
    # registry records one geographic region. PAL is WEAS there (and on the PSE
    # alias). A composite's joined string (CAMR+CARB) is not a median group.
    reg_geo = {row['region']: row['gtap_geo'] for row in regions if row['gtap_geo'] and '+' not in row['gtap_geo']}
    filled_geo = []
    for code in list(iso_geo):
        if iso_geo[code]:
            continue
        g = reg_geo.get(code, '')
        if g and g in known_geo:
            iso_geo[code] = g
            filled_geo.append(code + '=' + g)
    brief['geo_filled'] = filled_geo
    if filled_geo:
        S.log('country-map geo filled from the region registry: ' + ' '.join(filled_geo))
    odd_geo = sorted({g for g in iso_geo.values() if g and g not in known_geo})
    if odd_geo:
        S.log('country geos not in the Table 9.10 list: ' + ' '.join(odd_geo))
    sec_order = [r['sector'] for r in read_csv(sectors_path) if r['sector'] in GOODS_SET]
    for s in GOODS:
        if s not in sec_order:
            sec_order.append(s)
    sec_i = {s: i for i, s in enumerate(sec_order)}

    # Mode shares from the choice, not from a hard-coded mix.
    if choices['mode_split'].startswith('us_census_charges_by_sector'):
        cen_shares, cen_missing, cen_info = census_shares(cen6, hs22_path)
        brief['census'] = cen_info
        brief['cen_missing'] = cen_missing
        mode_of = {}
        for sector, (rdt, sea, air, _val, _cha) in cen_shares.items():
            mode_of[sector] = freeze_mode_share(rdt, sea, air)
        mode_flag = 'MODE-SPLIT-US-CHARGES'
    else:
        cen_missing = []
        brief['census'] = {}
        alias_rows = read_csv(alias_path)
        _iso2 = iso2_map('/tmp/s08_baci/country_codes.csv', alias_rows)
        _by, _present, _unmapped, world_fr, _wl = read_tismos(tismos_path, _iso2)
        tot = sum(world_fr.values())
        sea = world_fr['sea'] / tot
        air = world_fr['air'] / tot
        frozen = freeze_mode_share(1 - sea - air, sea, air)
        mode_of = {s: frozen for s in GOODS}
        mode_flag = 'MODE-SPLIT-TISMOS-WORLD'
        brief['tismos_world_for_split'] = world_fr
    brief['mode_of'] = {s: mode_of.get(s) for s in GOODS}
    brief['mode_flag'] = mode_flag

    def world_total_m(imp):
        num = den = 0.0
        for iso in members.get(imp, [imp]):
            w = weights['member_w'].get(iso, 0.0)
            r = weights['world_tot'].get(iso)
            if w > 0 and r is not None and 0 <= r < 1:
                num += w * (r / (1.0 - r))
                den += w
        if den <= 0:
            return None
        return num / den

    def f7_m(imp, sector):
        rates = []
        seen = set()
        for iso in members.get(imp, [imp]):
            geo = iso_geo.get(iso, '')
            if not geo or geo in seen:
                continue
            seen.add(geo)
            r = weights['f7sec'].get((geo, sector))
            if r is not None and 0 <= r < 1:
                rates.append(r)
        if not rates:
            return None
        r = statistics.median(rates)
        if not (0 <= r < 1):
            return None
        return r / (1.0 - r)

    con = weights.pop('con')
    need = []
    for (sector, exp, imp), vx in sums.items():
        if vx <= 0 or sector not in GOODS_SET:
            continue
        rec = weights['pair'].get((exp, imp, sector))
        if not (rec and rec['wok'] > 0):
            need.append((exp, imp, sector))
    try:
        weights['route_imp'], f7_cell_bad = route_importer_rates(con, need, S.log)
    except Exception:
        con.close()
        raise
    brief['f7_cell_bad'] = f7_cell_bad

    routes = []
    missing = []
    basis_value = {}
    level_value = {lv: 0.0 for lv in LEVELS}
    level_n = {lv: 0 for lv in LEVELS}
    level_by_imp = {}
    for (sector, exp, imp), vx in sums.items():
        if vx <= 0 or sector not in GOODS_SET:
            continue
        rec = weights['pair'].get((exp, imp, sector))
        basis = None
        m = None
        sh = None
        level = None
        if rec and rec['wok'] > 0:
            m = rec['wm'] / rec['wok']
            sh, level = shares_of(rec)
            basis = 'pair_baci'
        else:
            # No BACI flow on this route. Keep the importer's product weights and
            # apply this route's ITIC rates before F7.
            rec2 = weights['route_imp'].get((exp, imp, sector))
            if rec2 and rec2['wok'] > 0:
                m = rec2['wm'] / rec2['wok']
                sh, level = shares_of(rec2)
                basis = 'importer_baci'
        if m is None:
            m = weights['pair_tot_reg'].get((exp, imp))
            if m is not None:
                level = 'pair_total'
                sh = [0.0, 0.0, 1.0, 0.0, 0.0]
                basis = 'pair_total_bilateral'
        if m is None:
            m = world_total_m(imp)
            if m is not None:
                level = 'importer_world_total'
                sh = [0.0, 0.0, 0.0, 1.0, 0.0]
                basis = 'importer_world_total'
        if m is None:
            m = f7_m(imp, sector)
            if m is not None:
                level = 'F7'
                sh = [0.0, 0.0, 0.0, 0.0, 1.0]
                basis = 'f7_sector'
        if m is None or level not in LEVEL_I or sector not in mode_of:
            missing.append((sector, exp, imp, vx))
            continue
        routes.append((sector, exp, imp, vx, m, level, sh, basis))
        basis_value[basis] = basis_value.get(basis, 0.0) + vx
        level_value[level] += vx
        level_n[level] += 1
        if level != 'pair_hs4':
            level_by_imp[(imp, level)] = level_by_imp.get((imp, level), 0.0) + vx
    brief['missing'] = missing
    brief['basis_value'] = basis_value
    brief['level_value'] = level_value
    brief['level_n'] = level_n
    brief['level_by_imp'] = level_by_imp
    brief['n_routes'] = len(routes)
    bare = [(exp, imp, sector) for sector, exp, imp, _vx, _m, _lv, _sh, basis in routes if basis == 'f7_sector']
    try:
        fixes = rescue_bare(con, bare, S.log)
    finally:
        con.close()
    for n, (sector, exp, imp, vx, _m, level, _sh, basis) in enumerate(routes):
        hit = fixes.get((exp, imp, sector))
        if not hit:
            continue
        new_m, new_level, new_sh, new_basis = hit
        level_value[level] -= vx
        level_n[level] -= 1
        key = (imp, level)
        if key in level_by_imp:
            level_by_imp[key] -= vx
            if abs(level_by_imp[key]) < 1e-9:
                del level_by_imp[key]
        basis_value[basis] = basis_value.get(basis, 0.0) - vx
        level_value[new_level] += vx
        level_n[new_level] += 1
        if new_level != 'pair_hs4':
            level_by_imp[(imp, new_level)] = level_by_imp.get((imp, new_level), 0.0) + vx
        basis_value[new_basis] = basis_value.get(new_basis, 0.0) + vx
        routes[n] = (sector, exp, imp, vx, new_m, new_level, new_sh, new_basis)
    bare_bad = sum(1 for sector, exp, imp, _vx, _m, _lv, _sh, basis in routes
                   if basis == 'f7_sector' and (exp, imp, sector) in fixes)
    brief['f7_bare_bad'] = bare_bad
    S.log(f'routes {len(routes)}; missing {len(missing)}; bare F7 still holding an ITIC rate {bare_bad}; rescued {len(fixes)}; levels { {k: (level_n[k], round(level_value[k], 1)) for k in LEVELS} }')

    # Build the strings that are written, then check those strings.
    rate_lines = []
    vtwr_lines = []
    parsed = []
    max_ident = 0.0
    n_bad_r = 0
    n_neg_v = 0
    n_nan = 0
    h4_gap = 0.0
    mode_vtwr = {m: 0.0 for m in MODES}
    into = {m: {} for m in MODES}
    sec_vtwr = {s: 0.0 for s in GOODS}
    sec_vx = {s: 0.0 for s in GOODS}
    oilgas_vt = 0.0
    oilgas_rdt = 0.0
    share_gap = 0.0
    for sector in GOODS:
        if sector not in mode_of:
            share_gap = max(share_gap, 1.0)
            continue
        rdt_s, sea_s, air_s = mode_of[sector]
        if rdt_s < -1e-9 or sea_s < -1e-9 or air_s < -1e-9:
            share_gap = max(share_gap, 1.0)
        share_gap = max(share_gap, abs((rdt_s + sea_s + air_s) - 1.0))
    routes.sort(key=lambda r: (sec_i.get(r[0], 999), reg_i.get(r[1], 999), reg_i.get(r[2], 999)))
    # energy_sea_rate (next round, Gulf margins check 2026-10-25): ITIC's 2022 crude and product rates are imputed and
    # on non-US routes run about 3x the US Census charges for the same exporters. The tanker part of crude and the sea
    # part of petroleum products take the exporter's Census 2022 rate on HS 2709 / 2710 (GTAP 7 ch.9A p.3: margins from
    # US import charges); crude pipelines, the road and air parts, gas and every route into the USA (already ITIC =
    # Census) keep ITIC. Using the exporter's US rate on its routes to every importer is our choice, not in GTAP text.
    census_mode = {}
    sea_rows = []
    if choices['energy_sea_rate'] in ('us_census_exporter_hs4', CENSUS_WHOLE_ROUTE):
        imdb6 = S.inp(DATA + '/census_imdb_2022/hs6_cty_rp_2022.csv', 'US Census IMDB 2022 HS6 x country (CIF and customs value), energy_sea_rate')
        cen2_e = cen2 or S.inp(DATA + '/census_imports_hs_2022/imports_hs_hs2_cty_charges_2022.json', 'US Census 2022 HS2 import charges by country (country names)')
        iso_region = {iso: reg for reg, isos in members.items() for iso in isos}
        cen_rate, cen_fb, cen_val, cen_unmatched = census_energy_rates(imdb6, cen2_e, by_norm, iso_region)
        oil_pipe = {(r['exporter'], r['importer']): float(r['pipeline_share']) for r in read_csv(route_cfg) if r['sector'] == 'oil'}
        by_route_mode = choices['mode_split'] == 'us_census_charges_by_sector_energy_by_route'
        americas = {row['region']: bool(set(row['gtap_geo'].split('+')) & AMERICAS_GEO) for row in regions}
        for n, (sector, exp, imp, vx, m, level, sh, basis) in enumerate(routes):
            if sector not in ENERGY_HS4.values() or imp == 'USA' or sector not in mode_of:
                continue
            if sector == 'oil' and by_route_mode:
                p_ = oil_pipe.get((exp, imp), 0.0)
                mode = freeze_mode_share(p_, 1.0 - p_, 0.0)
            else:
                mode = mode_of[sector]
            own = (sector, exp) in cen_rate
            m_c = cen_rate[(sector, exp)] if own else cen_fb[sector]
            src = 'census_exporter' if own else 'census_fallback'
            if own and not americas.get(imp, False) and m_c < cen_fb[sector]:
                m_c, src = cen_fb[sector], 'census_floor_outside_americas'
            if choices['energy_sea_rate'] == CENSUS_WHOLE_ROUTE:
                new_m, parts, c_share = census_route_whole(m, m_c, mode, mode[0] if sector == 'oil' else 0.0)
            else:
                (new_m, parts), c_share = census_route_parts(m, m_c, mode), mode[1]
            census_mode[(sector, exp, imp)] = freeze_mode_share(parts[0], parts[1], parts[2])
            routes[n] = (sector, exp, imp, vx, new_m, level, sh, basis)
            sea_rows.append([sector, exp, imp, vx, m, m_c, src,
                             c_share, new_m, vx * m, vx * new_m])
        brief['energy_sea'] = dict(rates=cen_rate, fallback=cen_fb, value=cen_val, unmatched=cen_unmatched, n=len(sea_rows))
        S.log(f'energy_sea_rate: {len(sea_rows)} oil and pet routes re-rated; Census fallback oil {cen_fb["oil"]:.4f}, pet {cen_fb["pet"]:.4f}; '
              f'{len([k for k in cen_rate if k[0] == "oil"])} oil and {len([k for k in cen_rate if k[0] == "pet"])} pet exporter rates; '
              f'unmatched Census countries {len(cen_unmatched)}')
    # Fable QA C-05: oil and gas take their mode by route, not the US commodity mix (Canadian pipelines).
    # Gas: pipeline (rdt, GTAP otp) share = BACI HS 271121 / (271111 + 271121) on the route, else the exporter's
    # share over all its routes; the rest is LNG by sea. Crude: config/s08/energy_route_modes.csv pipeline routes,
    # every other route by tanker (sea). The rate stays ITIC's own.
    route_mode = {}
    route_src = defaultdict(float)
    if choices['mode_split'] == 'us_census_charges_by_sector_energy_by_route':
        oil_cfg = {(r['exporter'], r['importer']): float(r['pipeline_share'])
                   for r in read_csv(route_cfg) if r['sector'] == 'oil'}
        gp = weights['gas_pipe']
        exp_tot = defaultdict(lambda: [0.0, 0.0])
        for (e_, _i), (p_, l_) in gp.items():
            exp_tot[e_][0] += p_
            exp_tot[e_][1] += l_
        for sector, exp, imp, vx, m, _lv, _sh, _b in routes:
            if sector not in ('oil', 'gas'):
                continue
            p, src = pipeline_share(sector, exp, imp, oil_cfg, gp, exp_tot)
            route_mode[(sector, exp, imp)] = freeze_mode_share(p, 1.0 - p, 0.0)
            route_src[src] += vx * m
        cfg_bad = [k for k in oil_cfg if not (0.0 <= oil_cfg[k] <= 1.0)]
        S.check('S08-H12', 'Energy route modes: every oil and gas route has a pipeline share in [0, 1]; the crude pipeline '
                'table names S01 regions only',
                'hard', f'routes {len(route_mode)}; bad config rows {len(cfg_bad)}; unknown regions '
                f'{sum(1 for e_, i_ in oil_cfg if e_ not in region_set or i_ not in region_set)}', '0; 0',
                not cfg_bad and all(e_ in region_set and i_ in region_set for e_, i_ in oil_cfg)
                and all(0.0 <= v[0] <= 1.0 + 1e-12 for v in route_mode.values()),
                'GTAP 12 ch.02 p.16 (otp carries pipelines); Fable QA C-05',
                'VTWR by mode source, bn: ' + '; '.join(f'{k} {v / 1000:.2f}' for k, v in sorted(route_src.items())))
    # beta v4 P7 (lng_sea_rate, David's call; default itic): ITIC's 2022 LNG rates are imputed and flat with distance (10.2%
    # of FOB on the 24 largest routes against a 5.3% voyage-cost build-up). GTAP's margin source (US import charges, GTAP 7
    # ch.9A p.3) has almost no LNG, so any LNG rule is a labelled departure. Routes into the USA keep ITIC
    lng_rows = []
    if choices['lng_sea_rate'] != 'itic':
        lcfg = S.inp(BUILD + '/config/s08/lng_voyage.csv', 'beta v4 P7 LNG voyage-cost parameters (2022)')
        rcfg = S.inp(BUILD + '/config/s08/lng_routes.csv', 'beta v4 P7 LNG route distances (nautical miles, canal)')
        P = {r['parameter']: float(r['value']) for r in read_csv(lcfg)}
        if set(P) != set(LNG_PARAMS):
            raise SystemExit(f'lng_voyage.csv: parameters {sorted(P)} are not {sorted(LNG_PARAMS)}')
        dist = {(r['exporter'], r['importer']): (float(r['nm']), r['canal'].strip() or None) for r in read_csv(rcfg)}
        gp = weights['gas_pipe']
        exp_tot = defaultdict(lambda: [0.0, 0.0])
        for (e_, _i), (p_, l_) in gp.items():
            exp_tot[e_][0] += p_
            exp_tot[e_][1] += l_
        for n, (sector, exp, imp, vx, m, level, sh, basis) in enumerate(routes):
            if sector != 'gas' or imp == 'USA':
                continue
            p_, _src = pipeline_share('gas', exp, imp, {}, gp, exp_tot)
            s_ = 1.0 - p_
            if s_ <= 0:
                continue
            price = weights['lng_fob'].get(exp)
            if choices['lng_sea_rate'] == LNG_VOYAGE and (exp, imp) in dist and price:
                m_l, src = lng_voyage_cost(dist[(exp, imp)][0], dist[(exp, imp)][1], price, P) / price, 'voyage_cost'
            else:
                m_l, src = LNG_FALLBACK_SCALE * m, 'itic_scaled'
            new_m, parts = lng_route_parts(m, s_, m_l)
            route_mode[('gas', exp, imp)] = freeze_mode_share(parts[0], parts[1], parts[2])
            routes[n] = (sector, exp, imp, vx, new_m, level, sh, basis)
            lng_rows.append([sector, exp, imp, vx, m, s_, m_l, src, new_m, vx * m, vx * new_m])
        write_csv(S.out + '/lng_sea_rates_s08.csv',
                  ['sector', 'exporter', 'importer', 'vxsb_musd', 'itic_m', 'lng_share', 'lng_m', 'lng_source', 'm', 'vtwr_itic_musd', 'vtwr_musd'],
                  [r[:3] + [fnum(x) for x in r[3:7]] + [r[7]] + [fnum(x) for x in r[8:]] for r in lng_rows])
        bad_l = [r for r in lng_rows if abs(r[8] - ((1.0 - r[5]) * r[4] + r[5] * r[6])) > 1e-12 or r[2] == 'USA']
        by_key = {(s_, e_, i_): m_ for s_, e_, i_, _v, m_, _l, _s, _b in routes}
        bad_l += [r for r in lng_rows if by_key[(r[0], r[1], r[2])] != r[8]]
        S.check('S08-H14', 'lng_sea_rate (beta v4 P7; labelled departure): each re-rated gas route not into the USA has m = pipeline share x ITIC '
                '+ LNG share x the LNG rate (2022 voyage cost / exporter BACI LNG FOB price on listed routes, else ITIC x '
                f'{LNG_FALLBACK_SCALE}), and that m is the one written', 'hard', len(bad_l), 0, not bad_l, 'lng_sea_rate; GTAP 7 ch.9A p.3',
                f'{len(lng_rows)} routes ({sum(1 for r in lng_rows if r[7] == "voyage_cost")} at voyage cost); VTWR gas '
                f'{sum(r[9] for r in lng_rows) / 1000:.2f} -> {sum(r[10] for r in lng_rows) / 1000:.2f} bn')
        S.flag('LNG-SEA-RATE', 'LNG part of gas margins on routes not into the USA',
               f'{len(lng_rows)} routes re-rated ({choices["lng_sea_rate"]}); pipeline parts and USA routes keep ITIC', 'no',
               'our choice (beta v4 P7); GTAP 7 ch.9A p.3', Q_CIF)
    brief['route_src'] = dict(route_src)
    route_mode.update(census_mode)
    for sector, exp, imp, vx, m, level, sh, basis in routes:
        m_p = float(f12(m))
        r_p = float(f12(m_p / (1.0 + m_p)))
        if not (0 <= r_p < 1) or m_p != m_p or m_p < 0:
            n_bad_r += 1
        else:
            max_ident = max(max_ident, abs(m_p - r_p / (1.0 - r_p)))
        total = m_p * vx
        rdt_s, sea_s, air_s = route_mode.get((sector, exp, imp), mode_of[sector])
        sea_line = fnum(total * sea_s)
        air_line = fnum(total * air_s)
        rdt_v = total - float(sea_line) - float(air_line)
        if -1e-8 < rdt_v < 0:
            rdt_v = 0.0
        rdt_line = fnum(rdt_v)
        lines = {'rdt': rdt_line, 'sea': sea_line, 'air': air_line}
        got = 0.0
        for mode in MODES:
            val = float(lines[mode])
            got += val
            if val < -1e-12:
                n_neg_v += 1
            if val != val:
                n_nan += 1
            mode_vtwr[mode] += val
            into[mode][imp] = into[mode].get(imp, 0.0) + val
            vtwr_lines.append(f'{mode},{sector},{exp},{imp},{lines[mode]}\n'.encode())
        h4_gap = max(h4_gap, abs(got - total), abs(got - m_p * vx))
        sec_vtwr[sector] += got
        sec_vx[sector] += vx
        if sector in ('oil', 'gas'):
            oilgas_vt += got
            oilgas_rdt += float(lines['rdt'])
        rate_lines.append(
            f'{sector},{exp},{imp},{f12(r_p)},{f12(m_p)},{level},{fnum(sh[0])},{fnum(sh[1])},{fnum(sh[2])},{fnum(sh[3])},{fnum(sh[4])}\n'.encode())
        parsed.append((sector, exp, imp, vx, m_p, r_p, got))
    brief['mode_vtwr'] = mode_vtwr
    brief['sec_vtwr'] = sec_vtwr
    brief['sec_vx'] = sec_vx
    brief['parsed'] = parsed
    world_vx = sum(vx for _s, _e, _i, vx, _m, _r, _g in parsed)
    world_vt = sum(mode_vtwr.values())
    brief['world_vx'] = world_vx
    brief['world_vt'] = world_vt
    brief['oilgas_vt'] = oilgas_vt
    brief['oilgas_rdt'] = oilgas_rdt

    # VST keys.
    alias_rows = read_csv(alias_path)
    general_alias = {r['code']: r['iso3'] for r in alias_rows if not r['code'].startswith('TiSMoS:')}
    ctry_path = '/tmp/s08_baci/country_codes.csv'
    tismos_by, tismos_present, tismos_unmapped, tismos_world, tismos_wl = read_tismos(tismos_path, iso2_map(ctry_path, alias_rows))
    brief['tismos_wl'] = tismos_wl
    batis = read_batis(batis_path, general_alias)
    brief['tismos_world'] = tismos_world
    brief['tismos_unmapped'] = tismos_unmapped
    # Geographic ratio over reporters that have a TiSMoS row. Under f8_where_zero only reporters with positive
    # TiSMoS freight in the mode enter it: a zero TiSMoS freight cell is treated as missing (TiSMoS is modelled,
    # status I, and BaTIS shows transport exports for every one of them), so it takes F8 too.
    zero_missing = choices['vst_allocation'].startswith('tismos_2022_mode1_freight_exports_f8_where_zero')
    tis_ok = lambda iso, mode: iso in tismos_present and (not zero_missing or tismos_by.get(iso, {}).get(mode, 0.0) > 0)
    geo_num = {}
    geo_den = {}
    for iso in tismos_present:
        geo = iso_geo.get(iso, '')
        if not geo:
            continue
        for mode in MODES:
            if not tis_ok(iso, mode):
                continue
            geo_num[(geo, mode)] = geo_num.get((geo, mode), 0.0) + tismos_by.get(iso, {}).get(mode, 0.0)
            geo_den[(geo, mode)] = geo_den.get((geo, mode), 0.0) + batis.get((iso, mode), 0.0)
    ratio = {}
    for (geo, mode), num in geo_num.items():
        den = geo_den.get((geo, mode), 0.0)
        if den > 0 and (num > 0 or not zero_missing):
            ratio[(geo, mode)] = num / den
    # Under f8_where_zero, a geographic region with no positive TiSMoS freight in the mode (Central America sea)
    # takes the world ratio over all reporters with positive freight in the mode.
    world_ratio = {}
    if zero_missing:
        for mode in MODES:
            num = sum(v for (g, m), v in geo_num.items() if m == mode)
            den = sum(v for (g, m), v in geo_den.items() if m == mode)
            if den > 0:
                world_ratio[mode] = num / den
    keys = {m: {} for m in MODES}
    key_source = {}
    mode_source = {}
    f8_regions = []
    f8_gap = []
    for region in region_order:
        tis = {m: 0.0 for m in MODES}
        f8 = {m: 0.0 for m in MODES}
        any_tis = False
        any_f8 = False
        f8_modes = set()
        for iso in members.get(region, [region]):
            for mode in MODES:
                if tis_ok(iso, mode):
                    any_tis = True
                    tis[mode] += tismos_by.get(iso, {}).get(mode, 0.0)
                    continue
                any_f8 = True
                f8_modes.add(mode)
                geo = iso_geo.get(iso, '')
                b = batis.get((iso, mode), 0.0)
                rto = ratio.get((geo, mode)) if geo else None
                if rto is None and zero_missing:
                    rto = world_ratio.get(mode)
                if rto is None:
                    if b > 0 or not geo:
                        f8_gap.append((region, iso, geo, mode, b))
                else:
                    f8[mode] += b * rto
        for mode in MODES:
            keys[mode][region] = tis[mode] + f8[mode]
            mode_source[(region, mode)] = ('F8' if tis[mode] == 0 else 'tismos+F8') if (mode in f8_modes and f8[mode] > 0) else 'tismos'
        if any_f8 and (not any_tis or sum(f8.values()) > 0):
            key_source[region] = 'F8'
            f8_regions.append(region)
        else:
            key_source[region] = 'tismos'
    key_parts = {}
    if batis_key:
        # Fable QA D-03: the TiSMoS mode-1 key books freight to the carrier's residence, so a flag or operator
        # economy (DNK sea 132 bn) takes VST that its BoP does not show. The key is each region's BoP freight
        # exports (BaTIS SCx times the TiSMoS freight leaf share, the freight S09 removes) plus the freight on
        # its own imports that no foreign carrier's exports cover (resident carriers, which BoP does not record
        # as trade), up to the region's own output of the mode left after its freight exports:
        # key = Fx + min(max(0, VTWR into - Fm), max(0, OUT - Fx)).
        fx, fm, share_src = batis_freight(ebops_path, tismos_path, region_order, S.log)
        out_key = load_output(io_path)
        f8_regions = []
        key_source = {}
        for region in region_order:
            filled = False
            for mode in MODES:
                keys[mode][region], own = own_carrier_key(fx[mode].get(region, 0.0), fm[mode].get(region, 0.0),
                                                          into[mode].get(region, 0.0), out_key[mode].get(region, 0.0))
                key_parts[(region, mode)] = (fx[mode].get(region, 0.0), fm[mode].get(region, 0.0), own)
                src = share_src.get((region, mode), '')
                if fx[mode].get(region, 0.0) > 0 and src in ('F8', 'world'):
                    mode_source[(region, mode)] = 'batis_freight_' + src
                    filled = True
                elif fx[mode].get(region, 0.0) > 0:
                    mode_source[(region, mode)] = 'batis_freight'
                else:
                    mode_source[(region, mode)] = 'own_carrier'
            key_source[region] = 'F8' if filled else 'batis'
            if filled:
                f8_regions.append(region)
        f8_gap = []
    brief['no_seaport'] = {}
    if choices.get('no_seaport_sea_key', 'off') == NO_SEAPORT_TO_ROAD:
        brief['no_seaport'] = no_seaport_keys(keys, mode_source, no_seaport)
    brief['key_parts'] = key_parts
    brief['f8_regions'] = f8_regions
    brief['f8_gap'] = f8_gap
    key_sum = {m: sum(keys[m].values()) for m in MODES}
    vst = {m: {} for m in MODES}
    for mode in MODES:
        den = key_sum[mode]
        for region in region_order:
            vst[mode][region] = 0.0 if den <= 0 else mode_vtwr[mode] * keys[mode][region] / den
    vst_capped = {}
    if choices['vst_allocation'] in ('tismos_2022_mode1_freight_exports_f8_where_zero_capped',
                                     'batis_freight_plus_own_carrier_imports_capped'):
        # David's S08 card (S15 thread, 2026-10-24): a filled cell may not exceed the region's own I-O exports of
        # the mode (io_s07 row dom_<m>, column X); the floor keeps log(VST) finite in the model. Under the BaTIS
        # key a filled cell is one whose freight share comes from F8 or the world, or that has no freight exports.
        x_cells = load_output(io_path, 'X')
        for mode in MODES:
            filled = [r for r in region_order if mode_source[(r, mode)] not in ('tismos', 'batis_freight')]
            vst[mode], fixed = cap_filled(vst[mode], filled, x_cells[mode], mode_vtwr[mode])
            vst_capped[mode] = fixed
    brief['vst'] = vst
    brief['vst_capped'] = vst_capped
    brief['keys'] = keys
    brief['key_source'] = key_source
    brief['key_sum'] = key_sum

    output_cells = load_output(io_path)
    above = []
    for mode in MODES:
        for region in region_order:
            out_v = output_cells[mode].get(region, 0.0)
            if vst[mode][region] > out_v + 1e-6:
                above.append((vst[mode][region] - out_v, region, mode, vst[mode][region], out_v))
    above.sort(reverse=True)
    brief['above'] = above

    out_dir = S.out
    gz_write(out_dir + '/margin_rates_s08.csv.gz',
             b'sector,exporter,importer,r_cif,m_fob,level,share_pair_hs4,share_importer_world_hs4,share_pair_total,share_importer_world_total,share_f7\n',
             rate_lines)
    gz_write(out_dir + '/vtwr_s08.csv.gz',
             b'margin,sector,exporter,importer,vtwr_musd\n',
             vtwr_lines)
    vst_rows = []
    for region in region_order:
        for mode in MODES:
            vst_rows.append([mode, region, fnum(vst[mode][region]), fnum(keys[mode][region]), mode_source[(region, mode)]])
    write_csv(out_dir + '/vst_s08.csv', ['margin', 'region', 'vst_musd', 'key_musd', 'key_source'], vst_rows)
    freight_rows = []
    for region in region_order:
        for mode in MODES:
            freight_rows.append(['vst', mode, region, fnum(vst[mode][region])])
            freight_rows.append(['vtwr_into', mode, region, fnum(into[mode].get(region, 0.0))])
    freight_rows.sort(key=lambda r: (0 if r[0] == 'vst' else 1, MODE_I[r[1]], reg_i[r[2]]))
    write_csv(out_dir + '/freight_for_s09.csv', ['record', 'margin', 'region', 'musd'], freight_rows)
    shutil.copyfile(io_path, out_dir + '/io_s08.csv.gz')
    S.log('copied io_s07.csv.gz to io_s08.csv.gz without re-gzipping')

    usa_rows = usa_table(sums, parsed, mode_vtwr, vst, output_cells, tismos_by, cen6, cen2, hs22_path, by_norm, brief)
    write_csv(out_dir + '/usa_margins_s08.csv',
              ['record', 'margin', 'sector', 'partner_s01', 'partner_name', 'cty_code', 'itic_m', 'census_m',
               'diff_pp', 'vxsb_musd', 'vtwr_musd', 'output_musd', 'tismos_musd', 'census_val_usd', 'census_cha_usd',
               'gap_above_1_5pp', 'note'],
              usa_rows)

    if choices['energy_sea_rate'] in ('us_census_exporter_hs4', CENSUS_WHOLE_ROUTE):
        whole = choices['energy_sea_rate'] == CENSUS_WHOLE_ROUTE
        write_csv(out_dir + '/energy_sea_rates_s08.csv',
                  ['sector', 'exporter', 'importer', 'vxsb_musd', 'itic_m', 'census_m', 'census_source', 'census_share',
                   'm', 'vtwr_itic_musd', 'vtwr_musd'], [r[:3] + [fnum(x) for x in r[3:6]] + [r[6]] + [fnum(x) for x in r[7:]] for r in sea_rows])
        es = brief['energy_sea']
        by_exp = defaultdict(lambda: [0.0, 0.0])
        for sector, exp, _imp, _vx, _m, _mc, _src, _sea, _nm, v0, v1 in sea_rows:
            by_exp[(sector, exp)][0] += v0
            by_exp[(sector, exp)][1] += v1
        for (sector, exp), (v0, v1) in sorted(by_exp.items(), key=lambda kv: (sec_i.get(kv[0][0], 999), reg_i.get(kv[0][1], 999))):
            S.adjust(exp, f'{sector} export margins (VTWR, routes not into the USA): ' + ('route outside pipelines' if whole else 'sea part') + ' at the US Census rate',
                     fnum(v0), fnum(v1), 'energy_sea_rate', 'GTAP 7 ch.9A p.3 (US import charges); exporter rate on every route: our choice, not in GTAP text',
                     'ENERGY-SEA-CENSUS' if (sector, exp) in es['rates'] else 'ENERGY-SEA-CENSUS-FALLBACK')
        what = ('crude outside pipelines and petroleum products take the exporter\'s US Census 2022 charge as the whole-route margin'
                if whole else 'the tanker part of crude and the sea part of petroleum products take the exporter\'s US Census 2022 charges')
        keep = 'crude pipelines' if whole else 'crude pipelines, road and air parts'
        S.flag('ENERGY-SEA-CENSUS', 'oil and pet margins on routes not into the USA',
               f'{es["n"]} routes: {what} on HS 2709 / 2710 (fallback, the non-Canada average: oil {es["fallback"]["oil"]:.4f}, pet {es["fallback"]["pet"]:.4f}); '
               'an exporter\'s own rate is floored at the fallback on routes to importers outside the Americas; '
               f'{keep}, gas and USA routes keep ITIC', 'no', 'our choice; GTAP 7 ch.9A p.3', Q_CIF)
        # the written rates are the re-rated ones: m = sea x census + rest x ITIC, shares by mode sum to 1, USA routes untouched
        bad_e = [r for r in sea_rows
                 if abs(r[8] - (r[7] * r[5] + (1.0 - r[7]) * r[4])) > 1e-12
                 or r[2] == 'USA' or r[0] not in ENERGY_HS4.values()]
        by_key = {(s_, e_, i_): m_ for s_, e_, i_, _v, m_, _l, _s, _b in routes}
        bad_e += [r for r in sea_rows if by_key[(r[0], r[1], r[2])] != r[8]]
        # beta v4 G5: the Census rate on each row is re-read from the IMDB file (own rate, fallback or the floor), not taken
        # from the rate table the re-rating used
        rr, rfb, _v2, _u2 = census_energy_rates(imdb6, cen2_e, by_norm, iso_region)
        want = {'census_exporter': lambda r: rr.get((r[0], r[1])), 'census_fallback': lambda r: rfb[r[0]],
                'census_floor_outside_americas': lambda r: rfb[r[0]]}
        bad_e += [r for r in sea_rows if want[r[6]](r) is None or abs(want[r[6]](r) - r[5]) > 1e-12]
        S.check('S08-H13', 'energy_sea_rate: each re-rated oil and pet route not into the USA has m = Census share x the exporter\'s Census rate '
                '(re-read from the IMDB file) + the rest x its ITIC rate, and that m is the one written',
                'hard', len(bad_e), 0, not bad_e, 'energy_sea_rate; GTAP 7 ch.9A p.3',
                f'{len(sea_rows)} routes; VTWR oil and pet {sum(r[9] for r in sea_rows) / 1000:.2f} -> '
                f'{sum(r[10] for r in sea_rows) / 1000:.2f} bn; unmatched Census countries {len(es["unmatched"])}')

    # Checks on the values just written.
    h2_ok = len(missing) == 0 and all(level in LEVEL_I for _s, _e, _i, _vx, _m, level, _sh, _b in routes)
    S.check('S08-H2', 'Every positive goods VXSB triple has a rate, and the level is one of the five labels',
            'hard', f'missing {len(missing)}; routes {len(routes)}; repeated triples {n_rep}',
            '0 missing; level in pair_hs4, importer_world_hs4, pair_total, importer_world_total, F7',
            h2_ok, Q_AGG,
            'Summed over source. ' + ' '.join(f'{s} {e}->{i} {v:.3f}' for s, e, i, v in missing[:12]))
    f7_cell_bad = brief.get('f7_cell_bad') or 0
    f7_bare_bad = brief.get('f7_bare_bad') or 0
    h10_ok = f7_cell_bad == 0 and f7_bare_bad == 0
    S.check('S08-H10', 'No route or cell uses F7 when an ITIC pair or importer-world rate exists',
            'hard', f'no-BACI cells {f7_cell_bad}; bare routes {f7_bare_bad}',
            '0', h10_ok, Q_AGG,
            'A route with no BACI pair flow keeps the importer HS4 weights and tries pair HS4, importer-world HS4, pair total, then importer-world total before F7. '
            'A route with no basket at all tries the unweighted mean in that same order. '
            'Pair-basket cells, which already follow pair HS4, importer-world HS4 and pair total, are unchanged.')
    h3_ok = n_bad_r == 0 and n_neg_v == 0 and n_nan == 0 and max_ident <= 1e-6
    S.check('S08-H3', '0 <= r < 1 and m = r/(1-r) on the stored rates. No negative or NaN VTWR',
            'hard', f'bad r {n_bad_r}; negative {n_neg_v}; nan {n_nan}; max |m - r/(1-r)| {max_ident:.3e}',
            '0 bad; identity within 1e-6', h3_ok, 'E18; C03',
            f'OBS_STATUS counts {meta["status"]}. BACI code conflicts {meta["code_conflict"]}.' )
    h4_ok = h4_gap <= 1e-6 and share_gap <= 1e-9 and not cen_missing
    S.check('S08-H4', 'VTWR equals m times summed VXSB, the mode lines sum to that VTWR, and mode shares are non-negative and sum to 1',
            'hard', f'max gap {h4_gap:.3e}; share gap {share_gap:.3e}; sectors without a share {len(cen_missing)}',
            '1e-6 USD million; shares sum to 1', h4_ok, Q_MODE,
            'rdt is the residual of the formatted sea and air lines. Missing sectors: ' + ' '.join(cen_missing))
    h5_gap = 0.0
    h5_bits = []
    for mode in MODES:
        den = abs(mode_vtwr[mode]) or 1.0
        got = sum(vst[mode].values())
        rel = abs(got - mode_vtwr[mode]) / den
        h5_gap = max(h5_gap, rel)
        h5_bits.append(f'{mode} vst {got:.6f} vtwr {mode_vtwr[mode]:.6f} rel {rel:.3e}')
    h5_ok = h5_gap <= 1e-6 and all(key_sum[m] > 0 for m in MODES)
    S.check('S08-H5', 'Margin supply equals margin use for each margin commodity',
            'hard', f'max relative gap {h5_gap:.3e}', '1e-6 relative', h5_ok, 'READINESS S08 gate', '; '.join(h5_bits))
    bad_region = [r for r in region_order if r not in region_set]
    share_err = 0.0
    for mode in MODES:
        den = key_sum[mode]
        share_err = max(share_err, abs(sum(keys[mode].values()) / den - 1.0) if den else 1.0)
    neg_vst = sum(1 for mode in MODES for r in region_order if vst[mode][r] < -1e-12)
    h6_ok = neg_vst == 0 and not bad_region and share_err <= 1e-9
    S.check('S08-H6', 'VST is non-negative, every VST region is an S01 region, and key shares sum to 1',
            'hard', f'negative {neg_vst}; bad regions {len(bad_region)}; key-share gap {share_err:.3e}',
            '0; 0; 0', h6_ok, Q_SC, f'F8 regions {len(f8_regions)}')
    vx_now = sha256(vxsb_path)
    io_now = sha256(out_dir + '/io_s08.csv.gz')
    io_src = sha256(io_path)
    h7_ok = vx_now == S07_VXSB_SHA and io_now == io_src == S07_IO_SHA
    S.check('S08-H7', 'io_s08 is a byte copy of io_s07 and S08 does not rewrite VXSB',
            'hard', f'io match {io_now == io_src}; vxsb unchanged {vx_now == S07_VXSB_SHA}',
            'byte copy; VXSB hash unchanged', h7_ok, Q_FIT, f'io {io_now} vxsb {vx_now}')
    # Re-read the S09 file so H8 is on the written bytes.
    h8_gap = 0.0
    got_vst = {m: 0.0 for m in MODES}
    got_into = {m: {} for m in MODES}
    with open(out_dir + '/freight_for_s09.csv', newline='') as fh:
        for row in csv.DictReader(fh):
            val = float(row['musd'])
            if row['record'] == 'vst':
                got_vst[row['margin']] += val
            else:
                got_into[row['margin']][row['region']] = val
    for mode in MODES:
        h8_gap = max(h8_gap, abs(got_vst[mode] - sum(vst[mode].values())))
        for region in region_order:
            h8_gap = max(h8_gap, abs(got_into[mode].get(region, 0.0) - into[mode].get(region, 0.0)))
    S.check('S08-H8', 'freight_for_s09 equals VST by mode and VTWR into each importer',
            'hard', f'max abs gap {h8_gap:.3e}', '1e-6 USD million', h8_gap <= 1e-6, 'E46; PLAN §3(e)', '')
    names, stat = git_names()
    bad_files = sorted({n for n in names if forbidden(n)})
    load_rules()
    S.check('S08-H9', 'No private file (credentials, licensed GTAP database values) in the git diff. Rule: config/repo_rules.csv committed_data_rule (David 2026-10-23)',
            'hard', f'{len(bad_files)} forbidden paths', '0', not bad_files, 'licensing',
            (stat[-1500:] if stat else '') + ' ' + ' '.join(bad_files[:20]))
    single = {r['region'] for r in regions if r['type'] == 'single'}
    diag_n = 0
    diag_vt = 0.0
    for _sector, exp, imp, _vx, _m, _r, got in parsed:
        if exp == imp and exp in single:
            diag_n += 1
            diag_vt += got
    S.check('S08-H11', 'No VTWR on (r, r) for a single-country region',
            'hard', f'{diag_n} routes; {diag_vt / 1000:.6f} bn',
            '0 USD million', diag_n == 0 and abs(diag_vt) <= 1e-6,
            'composite_diagonal_margins',
            'Composite diagonals may carry a member-pair rate. A single country has no diagonal in the S07 file.')

    # Report checks.
    preview = load_preview()
    brief['preview'] = {k: preview[k] for k in preview if k != '_path'}
    pct = 100.0 * world_vt / world_vx if world_vx else 0.0
    pv = preview.get(('world', 'all', 'vtwr_musd_preview'))
    pp = preview.get(('world', 'all', 'margin_pct_of_fob'))
    preview_src = preview.get('_path') or 'committed constants'
    if pv is None:
        pv = PREVIEW_WORLD_VTWR_BN * 1000.0
    if pp is None:
        pp = PREVIEW_PCT
    sec_bits = []
    for sector in GOODS:
        own = 100.0 * sec_vtwr[sector] / sec_vx[sector] if sec_vx[sector] else 0.0
        prev = preview.get(('world', sector, 'margin_pct_of_fob'))
        if prev is not None:
            sec_bits.append(f'{sector} {own:.2f} (preview {prev:.2f})')
    mode_bits = []
    for mode in MODES:
        mode_bits.append(f'{mode} {mode_vtwr[mode] / 1000:.2f} bn ({100.0 * mode_vtwr[mode] / world_vt if world_vt else 0:.2f}%)')
    S.check('S08-R1', 'World VTWR against the preview. The preview is not a target',
            'report', f'{world_vt / 1000:.2f} bn; {pct:.2f}% of FOB',
            f'preview {((pv or 0) / 1000):.1f} bn; {(pp or 0):.2f}% of FOB',
            True, Q_ARRAY,
            'By mode: ' + '; '.join(mode_bits) + '. By sector, % of FOB: ' + '; '.join(sec_bits)
            + f'. World FOB {world_vx / 1000:.2f} bn. Repeated source triples {n_rep}. Preview source: {preview_src}.')
    oil = next((row for row in parsed if row[0] == 'oil' and row[1] == 'SAU' and row[2] == 'KOR'), None)
    oil_pct = None if oil is None else 100.0 * oil[4]
    raw_r = brief['kor_raw_r']
    raw_m = None if raw_r is None else 100.0 * raw_r / (1.0 - raw_r)
    raw_cif = None if raw_r is None else 100.0 * raw_r
    S.check('S08-R2', 'Korean crude imports from Saudi Arabia',
            'report',
            f'sector oil {oil_pct:.4f}% of FOB' if oil_pct is not None else 'no SAU->KOR oil row',
            'preview 7.10% of FOB; ITIC 2709 6.63% of CIF; old build 8.6%',
            True, Q_AGG,
            f'Raw ITIC 2709 KOR<-SAU {"" if raw_cif is None else f"{raw_cif:.4f}% of CIF, {raw_m:.4f}% of FOB"}. The oil sector rate is the BACI-weighted HS4 rate, including any other oil headings on the route.')
    che_levels = {}
    for sector, exp, imp, vx, _m, level, _sh, _b in ((a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7]) for a in routes):
        if imp in ('CHE', 'PRK', 'GNQ', 'PAN', 'IRQ'):
            che_levels[(imp, level)] = che_levels.get((imp, level), 0.0) + vx
    brief['focus_levels'] = che_levels
    top_imp = sorted(((v, i, lv) for (i, lv), v in level_by_imp.items()), reverse=True)[:12]

    def route_note(sector, exp, imp):
        for row in routes:
            if row[0] == sector and row[1] == exp and row[2] == imp:
                r = row[4] / (1.0 + row[4])
                return f'{exp}->{imp} {sector} level {row[5]} {100 * r:.2f}% of CIF ({100 * row[4]:.2f}% of FOB) on {row[3] / 1000:.2f} bn'
        return f'{exp}->{imp} {sector} absent'
    blr_vx = sum(row[3] for row in routes if row[1] == 'BLR' and row[2] == 'RUS')
    blr_f7 = sum(row[3] for row in routes if row[1] == 'BLR' and row[2] == 'RUS' and row[5] == 'F7')
    S.check('S08-R3', 'Fallback levels: route counts and VXSB value. CHE is expected mostly at importer-world',
            'report',
            '; '.join(f'{lv} n {level_n[lv]} {level_value[lv] / 1000:.2f} bn' for lv in LEVELS),
            'five labels; CHE mostly importer-world; PRK and GNQ at F7',
            True, 'F7',
            'Basis (how the rate was reached): ' + '; '.join(f'{k} {v / 1000:.2f} bn' for k, v in sorted(basis_value.items()))
            + '. Focus importers: ' + '; '.join(f'{i} {lv} {v / 1000:.2f} bn' for (i, lv), v in sorted(che_levels.items()))
            + '. Largest non-pair routes: ' + '; '.join(f'{i} {lv} {v / 1000:.2f} bn' for v, i, lv in top_imp)
            + '. No-BACI examples: ' + route_note('oil', 'SAU', 'TUR') + '; ' + route_note('oil', 'RUS', 'TUR')
            + f'; BLR->RUS {blr_vx / 1000:.2f} bn of which F7 {blr_f7 / 1000:.2f} bn.')
    usa_imp = brief.get('usa_imp_pct')
    usa_exp = brief.get('usa_exp_pct')
    S.check('S08-R4', 'USA import and export margins, Census charges, and USA VST',
            'report',
            f'imports {usa_imp:.2f}% of FOB; exports {usa_exp:.2f}% of FOB' if usa_imp is not None else 'see usa file',
            'preview imports 4.12% of FOB; exports 7.32%',
            True, Q_CIF, brief.get('usa_detail', ''))
    tw = sum(tismos_wl.values())
    above_txt = '; '.join(f'{r} {m} VST {v:.0f} output {o:.0f}' for _d, r, m, v, o in above[:8])
    S.check('S08-R5', 'VST against TiSMoS freight exports and against ICIO transport output',
            'report',
            f'{len(above)} VST-above-output cells; TiSMoS world freight {tw / 1000:.2f} bn; VTWR {world_vt / 1000:.2f} bn',
            'preview about 39 cells; freight exports below VTWR; report only',
            True, Q_FIT,
            f'World reporter WL SC12/SC22/SC32 {tismos_wl["sea"] / 1000:.2f} / {tismos_wl["air"] / 1000:.2f} / {tismos_wl["rdt"] / 1000:.2f} bn '
            f'(handoff cross-check 555.9 / 107.9 / 227.0). All-reporter sum {sum(tismos_world.values()) / 1000:.2f} bn includes regional aggregates and is not the allocation key. '
            f'Unmapped reporter codes {len(tismos_unmapped)}. '
            f'Largest cells: {above_txt}. F8 regions {len(f8_regions)}.')
    mine = output_sums_text(out_dir)
    mine_digest = hashlib.sha256(mine.encode()).hexdigest()
    other_path = os.environ.get('S08_R6_SHA256SUMS', '').strip()
    if other_path and os.path.exists(other_path):
        other = open(other_path).read()

        def parse_sums(text):
            got = {}
            for line in text.splitlines():
                digest, _, fn = line.partition('  ')
                if fn:
                    got[fn] = digest
            return got

        mine_map, other_map = parse_sums(mine), parse_sums(other)
        bad = [fn for fn in sorted(set(mine_map) | set(other_map)) if mine_map.get(fn) != other_map.get(fn)]
        r6_ok = not bad
        r6_value = f'this {hashlib.sha256(mine.encode()).hexdigest()}; other {hashlib.sha256(other.encode()).hexdigest()}'
        r6_detail = 'this run\n' + mine + 'other run\n' + other + ('mismatch ' + ', '.join(bad) if bad else '')
    else:   # no second run: NOTE, not PASS (Grok S15 QA N10), as S10 does
        r6_ok = False
        r6_value = f'this {mine_digest}; other run not supplied'
        r6_detail = 'Set S08_R6_SHA256SUMS to the other run output/SHA256SUMS.\nthis run\n' + mine
    brief['r6'] = r6_value
    S.check('S08-R6', 'Two runs write the same output SHA256SUMS',
            'report', r6_value, 'the two SHA256SUMS match', r6_ok, 'stage kit; GTAP_STAGES_DIR', r6_detail)
    weighted = sorted((r, vx) for _s, _e, _i, vx, _m, r, _g in parsed)
    p1 = wpercentile(weighted, 0.01)
    p50 = wpercentile(weighted, 0.50)
    p99 = wpercentile(weighted, 0.99)
    q = meta['pair_tot_q']
    S.check('S08-R7', 'Trade-weighted distribution of the margin. VCIF/VFOB here is 1 + m on the margin base, before S10 export taxes',
            'report',
            f'r % of CIF p1 {100 * p1:.2f} p50 {100 * p50:.2f} p99 {100 * p99:.2f}',
            'ITIC pair-total preview p1 0.70 median 8.49 p99 14.85; report only',
            True, Q_CIF,
            f'Unweighted ITIC pair-total r, percent of CIF: p1 {100 * q[0]:.2f} p50 {100 * q[1]:.2f} p99 {100 * q[2]:.2f} on {q[3]} pairs. '
            'Trade-weighted 1+m is the S08 stand-in for VCIF/VFOB.')

    # Ledger and flags.
    level_flag = {
        'pair_hs4': '',
        'importer_world_hs4': 'ITIC-IMPORTER-WORLD',
        'pair_total': 'ITIC-PAIR-TOTAL',
        'importer_world_total': 'ITIC-IMPORTER-WORLD-TOTAL',
        'F7': 'ITIC-F7',
    }
    for level in LEVELS:
        S.adjust('WORLD', level, '0', fnum(level_value[level]), 'dominant fallback level on summed VXSB', Q_AGG, level_flag[level])
    for (imp, level), val in sorted(level_by_imp.items()):
        S.adjust(imp, level, '0', fnum(val), 'dominant fallback level on summed VXSB', 'F7' if level == 'F7' else Q_AGG, level_flag[level])
    for _d, region, mode, v, o in above:
        S.adjust(region, mode, fnum(o), fnum(v), 'report only; no cap', Q_FIT, 'VST-GT-OUTPUT')
    for region in f8_regions:
        for mode in MODES:
            if mode_source[(region, mode)] not in ('tismos', 'batis_freight'):
                S.adjust(region, mode, '0', fnum(keys[mode][region]),
                         'F8 geographic freight ratio on BaTIS' if not batis_key else
                         f'BaTIS freight share from {mode_source[(region, mode)]} (no own TiSMoS split) or own-carrier part only',
                         'READINESS F8', 'VST-F8')
    for mode, fixed in brief.get('vst_capped', {}).items():
        for region, val in sorted(fixed.items()):
            S.adjust(region, mode, '', fnum(val), 'F8 fill capped at the region\'s own I-O exports of the mode (floor 0.01 USD m)', "David's S08 card (S15 thread)", 'VST-F8-CAP')
    st = {k: int(v) for k, v in meta['status']}
    n_st = sum(st.values()) or 1
    S.flag('ITIC-MODELLED', 'ITIC 2022',
           f'ITIC is a modelled dataset (C03); {100 * st.get("I", 0) / n_st:.0f}% status I, {100 * st.get("A", 0) / n_st:.0f}% status A. Counts {meta["status"]}.',
           'no', 'C03', Q_CIF)
    if level_value['importer_world_hs4'] > 0:
        S.flag('ITIC-IMPORTER-WORLD', 'importer x world HS4',
               f'{level_n["importer_world_hs4"]} routes, {level_value["importer_world_hs4"] / 1000:.2f} bn FOB. CHE partners in the HS4 pair file: {meta["che_partners"]}.',
               'no', 'not in GTAP text', Q_AGG)
    if level_value['pair_total'] > 0:
        S.flag('ITIC-PAIR-TOTAL', 'bilateral pair total _T',
               f'{level_n["pair_total"]} routes, {level_value["pair_total"] / 1000:.2f} bn FOB. This is the route total, not the importer-world total.',
               'no', 'not in GTAP text', Q_AGG)
    if level_value['importer_world_total'] > 0:
        S.flag('ITIC-IMPORTER-WORLD-TOTAL', 'importer x world total _T',
               f'{level_n["importer_world_total"]} routes, {level_value["importer_world_total"] / 1000:.2f} bn FOB.',
               'no', 'not in GTAP text', Q_AGG)
    if level_value['F7'] > 0:
        composites = {row['region'] for row in regions if row['type'] == 'composite'}
        prk_gnq = level_by_imp.get(('PRK', 'F7'), 0.0) + level_by_imp.get(('GNQ', 'F7'), 0.0)
        che_f7 = level_by_imp.get(('CHE', 'F7'), 0.0)
        comp_f7 = sum(v for (i, lv), v in level_by_imp.items() if lv == 'F7' and i in composites)
        other_f7 = level_value['F7'] - prk_gnq - che_f7 - comp_f7
        filled = brief.get('geo_filled') or []
        fill_txt = (' Country-map geo taken from the region registry: ' + ', '.join(filled) + '.') if filled else ''
        S.flag('ITIC-F7', 'PRK GNQ and HS4 gaps',
               f'{level_n["F7"]} routes, {level_value["F7"] / 1000:.2f} bn FOB. '
               f'Only {prk_gnq / 1000:.2f} bn is PRK and GNQ (ITIC rows {meta["prk"]} and {meta["gnq"]}). '
               f'The rest is HS4 codes missing at pair HS4, importer-world HS4, pair total and importer-world total: '
               f'CHE {che_f7 / 1000:.2f} bn, composites {comp_f7 / 1000:.2f} bn, and {other_f7 / 1000:.2f} bn elsewhere.{fill_txt}',
               'no', 'READINESS F7', Q_AGG)
    moved = [s for s in ('wat', 'pub', 'art', 'pro', 'pst') if s in GOODS_SET]
    moved_f7_n = sum(1 for row in routes if row[0] in moved and row[5] == 'F7')
    moved_f7_v = sum(row[3] for row in routes if row[0] in moved and row[5] == 'F7')
    moved_all = sum(row[3] for row in routes if row[0] in moved)
    S.log(f'moved goods {moved_all / 1000:.2f} bn; F7 routes {moved_f7_n}; F7 value {moved_f7_v / 1000:.2f} bn')
    if moved_f7_v > 0:
        S.flag('ITIC-F7-MOVED-GOODS', 'wat pub art pro pst',
               f'{moved_f7_n} routes and {moved_f7_v / 1000:.2f} bn of the moved-out goods take F7. '
               f'Their base is {moved_all / 1000:.2f} bn. The ladder is the same HS4 order as the other goods.',
               'no', 'READINESS F7', Q_AGG)
    share_txt = []
    if choices['mode_split'] == 'us_census_charges_by_sector' and brief.get('census'):
        info = brief['census']
        cha = info['world_cha'] or 1.0
        share_txt.append(f'mapped charges sea {100 * info["world_ves"] / cha:.2f}% air {100 * info["world_air"] / cha:.2f}% rdt {100 * (cha - info["world_ves"] - info["world_air"]) / cha:.2f}%')
        share_txt.append(f'unmapped HS6 value {info["un_val"] / 1e9:.2f} bn charges {info["un_cha"] / 1e9:.3f} bn')
    og = ''
    if brief.get('oilgas_vt'):
        og = (f' Oil and gas put {brief["oilgas_rdt"] / 1000:.1f} bn of their {brief["oilgas_vt"] / 1000:.1f} bn margin into rdt'
              f' ({100 * brief["oilgas_rdt"] / mode_vtwr["rdt"] if mode_vtwr["rdt"] else 0:.0f}% of world rdt).')
    route_txt = ''
    if brief.get('route_src'):
        route_txt = (' Oil and gas take their mode by route (Fable QA C-05): gas pipeline share from BACI HS 271121 vs 271111, '
                     'crude by tanker except the pipeline routes in config/s08/energy_route_modes.csv. VTWR by source, bn: '
                     + '; '.join(f'{k} {v / 1000:.2f}' for k, v in sorted(brief['route_src'].items())) + '.')
    S.flag(mode_flag, 'mode split',
           'One US mix is applied on every route for goods other than oil and gas. It is driven by US land imports, so rdt may be understated for manufactures.'
           + route_txt + og + ' This is the configured choice. Not rescaled. ' + ' '.join(share_txt),
           'no', 'not in GTAP text', Q_CIF)
    if above:
        S.flag('VST-GT-OUTPUT', 'VST above transport output',
               f'{len(above)} region-mode cells. Largest: ' + '; '.join(f'{r} {m} {v:.0f} vs {o:.0f}' for _d, r, m, v, o in above[:6]),
               'no', 'report only', Q_FIT)
    capped = brief.get('vst_capped', {})
    if any(capped.values()):
        n_cap = sum(len(v) for v in capped.values())
        S.flag('VST-F8-CAP', 'F8 fills capped at own I-O exports',
               f'{n_cap} filled margin-region cells capped at io_s07 X of the mode or floored at {F8_FLOOR_MUSD} USD m: '
               + '; '.join(f'{m} {len(v)}' for m, v in capped.items()) + '. The excess goes to the other cells in proportion.',
               'no', "David's S08 card (S15 thread, 2026-10-24)", Q_SC)
    if batis_key:
        kp = brief['key_parts']
        S.flag('VST-KEY-BATIS', 'VST key from BoP freight (Fable QA D-03)',
               'Key = BaTIS SC1/SC2/SC3 exports times the exporter\'s TiSMoS freight leaf share (the freight S09 removes) '
               'plus own-carrier freight on imports, max(0, VTWR into the region - BaTIS freight exports to it), capped at the region\'s '
               'output of the mode less its freight exports. World parts, bn: '
               + '; '.join(f'{m} Fx {sum(v[0] for (r, mm), v in kp.items() if mm == m) / 1000:.1f} '
                           f'own {sum(v[2] for (r, mm), v in kp.items() if mm == m) / 1000:.1f}' for m in MODES)
               + '. Was the TiSMoS mode-1 freight key, which follows the carrier operator (DNK sea 132.5 bn against BoP sea transport about 61 bn).',
               'no', 'GTAP 12 ch.17B §B.4 (BoP transport exports); Fable QA D-03', Q_SC)
    if f8_regions or f8_gap:
        n_f8 = len(f8_regions)
        S.flag('VST-F8', 'no TiSMoS freight row, or zero TiSMoS freight (f8_where_zero; world ratio where the geographic region has none)' if zero_missing else 'no TiSMoS freight row',
               f'{n_f8} {"region" if n_f8 == 1 else "regions"}. ' + ('A geographic region with no positive reporter takes the world ratio.' if zero_missing else 'Reporters with BaTIS and no geographic ratio stay at key 0.') + f' Gaps {len(f8_gap)}.',
               'no', 'READINESS F8', Q_SC)
    S.flag('FREIGHT-DOUBLE-COUNT-TO-S09', 'freight in ICIO services trade',
           'The same freight is removed at S09. io_s08 is unchanged. freight_for_s09.csv carries VST and VTWR into each importer.',
           'no', 'E46; PLAN §3(e)', Q_ASM)
    lpg = [f'{hs} {sec} {share}' for hs, sec, share in meta['lpg']]
    S.flag('LPG-IN-2711', 'HS 2711',
           '2711 is the rate on gas (271111, 271121) and on LPG headings the concordance puts in pet. ' + '; '.join(lpg),
           'no', 'concordance', Q_AGG)
    gaps = brief.get('usa_gaps') or []
    if gaps:
        S.flag('USA-IMPORT-CENSUS-GAP', 'USA import margin vs Census charges',
               '|ITIC - Census| > 1.5 pp on ' + ', '.join(gaps),
               'no', 'report only', Q_CIF)

    brief['max_ident'] = max_ident
    brief['h4_gap'] = h4_gap
    brief['above_n'] = len(above)
    S.finish()


def usa_table(sums, parsed, mode_vtwr, vst, output_cells, tismos_by, cen6, cen2, hs22_path, by_norm, brief):
    imp_vx = {}
    imp_vt = {}
    exp_vx = exp_vt = 0.0
    oil_vx = oil_vt = gas_vx = gas_vt = 0.0
    for sector, exp, imp, vx, m, _r, got in parsed:
        if exp == imp:
            continue
        if imp == 'USA':
            imp_vx[sector] = imp_vx.get(sector, 0.0) + vx
            imp_vt[sector] = imp_vt.get(sector, 0.0) + got
        if exp == 'USA':
            exp_vx += vx
            exp_vt += got
            if sector == 'oil':
                oil_vx += vx
                oil_vt += got
            elif sector == 'gas':
                gas_vx += vx
                gas_vt += got
    rows = []
    gaps = []
    cen_shares = {}
    if cen6:
        cen_shares, _missing, info = census_shares(cen6, hs22_path)
    else:
        info = {}

    def add(record, **kw):
        base = {'record': record, 'margin': '', 'sector': '', 'partner_s01': '', 'partner_name': '', 'cty_code': '',
                'itic_m': '', 'census_m': '', 'diff_pp': '', 'vxsb_musd': '', 'vtwr_musd': '', 'output_musd': '',
                'tismos_musd': '', 'census_val_usd': '', 'census_cha_usd': '', 'gap_above_1_5pp': '', 'note': ''}
        base.update(kw)
        rows.append([base[c] for c in (
            'record', 'margin', 'sector', 'partner_s01', 'partner_name', 'cty_code', 'itic_m', 'census_m', 'diff_pp',
            'vxsb_musd', 'vtwr_musd', 'output_musd', 'tismos_musd', 'census_val_usd', 'census_cha_usd', 'gap_above_1_5pp', 'note')])

    usa_vx = sum(imp_vx.values())
    usa_vt = sum(imp_vt.values())
    for sector in GOODS:
        vx = imp_vx.get(sector, 0.0)
        vt = imp_vt.get(sector, 0.0)
        itic = vt / vx if vx else None
        cen = cen_shares.get(sector)
        # census_shares tuple is (rdt, sea, air, customs value, charges). m = charges / customs value.
        census_m = cen[4] / cen[3] if cen and cen[3] else None
        diff = None if itic is None or census_m is None else (itic - census_m) * 100.0
        gap = 'yes' if diff is not None and abs(diff) > 1.5 else 'no'
        if gap == 'yes':
            gaps.append(f'{sector} {diff:.2f}')
        add('import_sector', sector=sector,
            itic_m='' if itic is None else f12(itic),
            census_m='' if census_m is None else f12(census_m),
            diff_pp='' if diff is None else fnum(diff),
            vxsb_musd=fnum(vx), vtwr_musd=fnum(vt),
            census_val_usd='' if not cen else fnum(cen[3]),
            census_cha_usd='' if not cen else fnum(cen[4]),
            gap_above_1_5pp=gap,
            note='Census cha/val is charges per customs value, the same units as m')
    itic_tot = usa_vt / usa_vx if usa_vx else None
    add('import_total', itic_m='' if itic_tot is None else f12(itic_tot),
        vxsb_musd=fnum(usa_vx), vtwr_musd=fnum(usa_vt),
        census_val_usd=fnum(info.get('world_val', 0.0)) if info else '',
        census_cha_usd=fnum(info.get('world_cha', 0.0)) if info else '',
        note='ITIC on all USA goods imports. Census figures are mapped HS6 dollars, not the all-HS6 total.')
    brief['usa_imp_pct'] = 100.0 * itic_tot if itic_tot is not None else None
    brief['usa_exp_pct'] = 100.0 * exp_vt / exp_vx if exp_vx else None
    if cen2:
        ranked = census_partners(cen2)
        # Partner ITIC rate: imports into USA from that region.
        by_exp = {}
        for sector, exp, imp, vx, _m, _r, got in parsed:
            if imp == 'USA' and exp != 'USA':
                slot = by_exp.setdefault(exp, [0.0, 0.0])
                slot[0] += vx
                slot[1] += got
        for code, (name, val, cha) in ranked:
            partner = match_partner(name, by_norm)
            census_m = cha / val if val else None
            itic = None
            vx = vt = 0.0
            if partner and partner in by_exp:
                vx, vt = by_exp[partner]
                itic = vt / vx if vx else None
            diff = None if itic is None or census_m is None else (itic - census_m) * 100.0
            gap = 'yes' if diff is not None and abs(diff) > 1.5 else ('no' if diff is not None else '')
            add('partner', partner_s01=partner, partner_name=name, cty_code=code,
                itic_m='' if itic is None else f12(itic),
                census_m='' if census_m is None else f12(census_m),
                diff_pp='' if diff is None else fnum(diff),
                vxsb_musd=fnum(vx), vtwr_musd=fnum(vt),
                census_val_usd=fnum(val), census_cha_usd=fnum(cha),
                gap_above_1_5pp=gap,
                note='Name match to S01 is report-only. Census is all HS2 for that country.')
    add('export_total', itic_m='' if not exp_vx else f12(exp_vt / exp_vx),
        vxsb_musd=fnum(exp_vx), vtwr_musd=fnum(exp_vt),
        note='USA exports at the USA-to-partner rate. BACI 842 already includes Puerto Rico and the Virgin Islands.')
    add('export_oil', sector='oil', itic_m='' if not oil_vx else f12(oil_vt / oil_vx),
        vxsb_musd=fnum(oil_vx), vtwr_musd=fnum(oil_vt),
        note='USA oil exports. The rate is the BACI-weighted 2709 and other oil HS4 rates.')
    add('export_gas', sector='gas', itic_m='' if not gas_vx else f12(gas_vt / gas_vx),
        vxsb_musd=fnum(gas_vx), vtwr_musd=fnum(gas_vt),
        note='USA gas exports. HS 2711 also covers LPG, which the concordance puts in pet.')
    usa_tis = tismos_by.get('USA', {m: 0.0 for m in MODES})
    for mode in MODES:
        add('vst', margin=mode, vtwr_musd=fnum(vst[mode].get('USA', 0.0)),
            output_musd=fnum(output_cells[mode].get('USA', 0.0)),
            tismos_musd=fnum(usa_tis.get(mode, 0.0)),
            note='vtwr_musd column holds USA VST. tismos_musd is USA mode-1 freight exports.')
    brief['usa_gaps'] = gaps
    imp_pct = brief['usa_imp_pct']
    exp_pct = brief['usa_exp_pct']
    brief['usa_detail'] = (
        f"import {imp_pct if imp_pct is None else f'{imp_pct:.2f}'}% of FOB ({usa_vt / 1000:.2f} bn on {usa_vx / 1000:.2f} bn); "
        f"export {exp_pct if exp_pct is None else f'{exp_pct:.2f}'}% of FOB ({exp_vt / 1000:.2f} bn on {exp_vx / 1000:.2f} bn); "
        f"oil export rate {100 * oil_vt / oil_vx if oil_vx else 0:.2f}%; gas export rate {100 * gas_vt / gas_vx if gas_vx else 0:.2f}%. "
        f"Census gaps over 1.5 pp: {', '.join(gaps) if gaps else 'none'}."
    )
    return rows


def write_notes(S, brief):
    needs = brief.get('missing') or []
    lines = ['# NEEDS_DAVID', '']
    if needs:
        lines.append(f'{len(needs)} positive goods routes have no rate at any of the four fallbacks.')
        lines += [f'- {s} {e} -> {i}: {v:.8f} USD million' for s, e, i, v in needs[:50]]
        lines.append(f'Sum of listed routes {sum(v for _s, _e, _i, v in needs):.8f} USD million.')
    else:
        lines.append('None.')
    lines.append('')
    open(S.dir + '/NEEDS_DAVID.md', 'w').write('\n'.join(lines))

    checks = getattr(S, 'checks', [])
    choice_rows = brief.get('choices') or []
    md = [
        '# S08 review brief',
        '',
        'International transport margins. VTWR is m times the S07 base named by margin_base, summed over source. VST allocates that margin with TiSMoS mode-1 freight exports. `io_s08.csv.gz` is a byte copy of `io_s07.csv.gz`.',
        '',
        f'Bound S07 head `{S07_HEAD[:12]}`, STAMP {S07_STAMP_TIME}, output SHA256SUMS `{S07_SHA256SUMS}`, VXSB `{S07_VXSB_SHA}`.',
        f'VXSB source rows {brief.get("vxsb_rows", "-")}; triples {brief.get("n_triples", "-")}; triples repeating by source {brief.get("n_rep", "-")} (the bound snapshot has {REPEATED_TRIPLES_NOTE}).',
        '',
        '## Choices',
        '',
        '| choice | value | decided_by | decided_at | gtap_status |',
        '|---|---|---|---|---|',
    ]
    for row in choice_rows:
        md.append(f'| {row["choice"]} | {row["value"]} | {row["decided_by"]} | {row["decided_at"]} | {row["gtap_status"]} |')
    md += ['', '## Hard checks', '', '| ID | Status | Value |', '|---|---|---|']
    for c in checks:
        if c['kind'] == 'hard':
            md.append(f'| {c["id"]} | {c["status"]} | {c["value"]} |')
    md += ['', '## Report checks', '']
    for c in checks:
        if c['kind'] == 'report':
            md += [f'### {c["id"]} {c["status"]}', '', c['description'], '', f'Value: {c["value"]}', '', f'Threshold: {c["threshold"]}', '']
            if c.get('detail'):
                md += [c['detail'], '']
    world_vt = brief.get('world_vt') or 0.0
    world_vx = brief.get('world_vx') or 0.0
    md += [
        '## Against the preview',
        '',
        f'World VTWR {world_vt / 1000:.2f} bn, {100 * world_vt / world_vx if world_vx else 0:.2f}% of FOB. Preview {PREVIEW_WORLD_VTWR_BN:,.1f} bn and {PREVIEW_PCT:.2f}%. The stage uses HS4 rates and BACI weights; the preview used pair totals. The difference is expected.',
        f'USA imports {brief.get("usa_imp_pct")}% of FOB (preview 4.12). USA exports {brief.get("usa_exp_pct")}% of FOB (preview 7.32).',
        f'VST above output: {brief.get("above_n", "-")} cells (preview about 39).',
        '',
        '## Flags',
        '',
    ]
    for fl in getattr(S, 'flags', []):
        md.append(f'- `{fl["id"]}` ({fl["subject"]}): {fl["text"]}')
    md += [
        '',
        '## Quotes',
        '',
        f'- {Q_CIF}: CIF minus FOB. US import charges are freight, insurance and other transport costs.',
        f'- {Q_AGG}: reapply the margin before aggregating to the sector.',
        f'- {Q_MODE}: otp, wtp, atp are rdt, sea, air. {Q_ARRAY}: VCIF, VST, VTWR, VFOB.',
        f'- {Q_SC}: SC12 sea, SC22 air, SC32 other.',
        f'- {Q_FIT}: FIT holds trade at border prices. {Q_ASM}: margins are incorporated at assembly.',
        '',
        '## Departures, log only',
        '',
        '- ITIC replaces GTAP\'s US-based margin estimates.',
        '- The margin is applied to the S07 base named by margin_base. With s07r_vfob_baci that column is vfob_musd. VCIF is still S10 (E46).',
        '- The US mode mix is applied on every route. rdt is overstated for oil and gas and likely understated for manufactures. The mix is not rescaled.',
        '- The VST key is TiSMoS freight exports. VST above output is report-only.',
        '- Insurance is inside the margin.',
        '- The freight double count is removed at S09.',
        '- CHE is mostly at the importer-world rate. LPG sits inside HS 2711.',
        '',
        '## Two-run SHA256SUMS',
        '',
        brief.get('r6', 'not run'),
        '',
    ]
    stamp = S.dir + '/STAMP'
    if os.path.exists(stamp):
        md += ['## STAMP', '', '```', open(stamp).read().rstrip(), '```', '']
    open(S.dir + '/REVIEW_BRIEF.md', 'w').write('\n'.join(md) + '\n')


def main():
    brief = {}
    stage = None
    try:
        stage = Stage('S08', 'margins')
        run(stage, brief)
    except SystemExit:
        raise
    except Exception:
        if stage is not None:
            stage.log('ERROR\n' + traceback.format_exc())
        raise
    finally:
        if stage is not None:
            try:
                write_notes(stage, brief)
            except Exception:
                traceback.print_exc()


if __name__ == '__main__':
    main()
