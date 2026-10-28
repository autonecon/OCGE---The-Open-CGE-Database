"""S07R merchandise trade. Reconciled BACI for every pair. No I-O cell changes.

Rules are the rows of config/s07/trade_choices.csv. This script does not choose.
goods_source=baci_all_pairs is built. pri_vir_trade=in_baci_842 retires the carve.
"""
import csv
import gc
import gzip
import hashlib
import json
import os
import re
import shutil
import sys
import unicodedata
import zipfile
from collections import defaultdict

import duckdb
import pandas as pd

os.environ.setdefault('TRADE_PREP_CACHE', '/tmp/trade-prep')
os.environ.setdefault('TRADE_PREP_ART', '/tmp/trade-prep-art')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/lib')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/prep_trade')
from stagekit import BUILD, DATA, ROOT, STAGES, Stage, sha256
import baci_reexports as BR
import retained_imports as RI

# Quotes used on ledger and flag rows. Chapter, section, PDF page.
Q_BAL = ('Aguiar et al. 2022 p.6 ("the initial trade data is not balanced, i.e., world exports differ from world imports")')
Q_RET = ('Aguiar et al. 2025 p.12 ("converting total imports into retained imports"); GTAP 7 ch.9A p.2; '
         'C&SD Annual Digest of Statistics 2023 Table 3.1 p.67 and note 3.7 p.60')
Q_REEX = ('Aguiar et al. 2025 p.12 §3.2.6 ("re-exports are reassigned to the country of origin" and "only domestically-produced exports are recorded")')
Q_GTAP7 = ('GTAP 7 ch.9A p.1 ("Indirect trade is not permitted in the GTAP Data Base and it must be dealt with")')
Q_HS = ('Aguiar et al. 2022 p.11 §3.2.6 ("We use a concordance between the HS6 and GTAP sectors to aggregate the HS6 flows")')
Q_FIT = ('GTAP 12 ch.17B §B.9 p.7 ("there is a trade module where merchandise and services trade data is prepared"; FIT reconciles the I-O table with trade)')
Q_TRADE_WINS = ('GTAP 12 ch.9A p.3 ("it is the production targets, not the export targets, that must give way")')
Q_TRAVEL = ('GTAP 12 ch.10B p.3 ("traveler\'s expenditures are allocated as trade among countries using information about private consumption")')
Q_ENERGY = ('Aguiar et al. 2025 p.14 ("energy trade data is constructed using data from IEA")')
Q_VFOB = ('GTAP 12 ch.02 p.5 ("Export Duties VFOB / VXSB")')
Q_SELECT = ('GTAP 7 ch.9A p.6 §9.A.4 ("the actual trade flow is more likely represented by one of the country\'s reports rather than by an adjusted average of the both reports")')
Q_LIE = ('GTAP 12 ch.10A resource 7646 abstract ("Liechtenstein is reported within Switzerland"); not in the public chapter text on disk')

GOODS = (
    'crp for fsh coa oil gas ore min fbt tal wod pap pet chm pha rpl nmm stl nfm fmp elc eeq mac mvh shp tre omf '
    'wat pub art pro pst'
).split()
MOVED = ('wat', 'pub', 'art', 'pro', 'pst')
ICIO_GOODS = []
for _s in GOODS:
    if _s in MOVED:
        ICIO_GOODS.append(_s)
        continue
    _ic = 'B06' if _s in ('oil', 'gas') else _s
    if _ic not in ICIO_GOODS:
        ICIO_GOODS.append(_ic)
ELY = 'ely'
OIL_HS = ('270900', '271410')
GAS_HS = ('271111', '271121')
# beta v4 P26 tier 1 (choice reexport_comtrade_rx): Comtrade 2022 RX / X by HS2 for every single-country region that reports
# re-exports (not HKG, NLD, SGP, which have their own rule; not the USA or BEL unless reexport_rx_usa_bel), energy lines (HS 27)
# left to S11, each region x sector removal capped at its BACI exports above the prior's exports
RX_TIER1 = 'comtrade_rx_x_hs2_single_country_reporters_capped_at_baci_exports_above_prior_exports_energy_to_s11'
RX_OWN_RULE = ('HKG', 'NLD', 'SGP')
RX_EXTRA = {'off': (), 'usa': ('USA',), 'usa_bel': ('USA', 'BEL'), 'usa_bel_nbb': ('USA', 'BEL')}
BEL_SHARE_FILE = 'bel_quasi_transit_2022/bel_quasi_transit_share_hs2_2022.csv'    # Comext community less Comtrade (NBB) national concept
# beta v4 P18 (choice transit_import_cap): importer-total cap for the traced transit regions
TRANSIT_CAP = 'importer_goods_imports_capped_at_wto_merchandise_imports_excluding_energy_and_precious_metal_lines'
TRANSIT_CAP_COLUMNS = ('region', 'goods_imports_musd', 'excluded_hs_prefixes', 'source', 'url', 'decided_by', 'decided_at', 'basis')
# beta v4 P39 (choice gold_reexport): exports of a listed gold line above recorded imports plus mine output are re-exports of
# unrecorded dore, rerouted to the destinations from the listed origin
GOLD_RX = 'listed_exporters_hs7108_exports_above_recorded_imports_plus_usgs_mine_output_rerouted_from_listed_origin'
GOLD_RX_COLUMNS = ('region', 'hs_prefix', 'mine_output_kg', 'origin', 'source', 'url', 'decided_by', 'decided_at', 'basis')
GOLD_PRICE_SHEET = 'wb_pinksheet/CMO-Historical-Data-Annual.xlsx'
TROY_OZ_KG = 0.0311034768
# beta v5 G (choice gold_reexport = METAL_RX): P39 generalised. Each row of config/s07/metal_reexport_2022.csv caps the
# region's BACI exports on its HS prefix at max(own customs exports, mine output + recorded imports); the excess is
# rerouted from the origin (as P39) or, with origin `drop`, removed from both sides (the importers' reports of smuggled
# artisanal gold that the exporter's customs and national accounts never record)
METAL_RX = 'metal_reexport_excess_above_max_own_customs_or_mine_plus_imports_dropped_or_rerouted'
METAL_RX_COLUMNS = ('region', 'hs_prefix', 'mine_output_kg', 'price', 'own_customs', 'origin', 'source', 'url',
                    'decided_by', 'decided_at', 'basis')
METAL_CUSTOMS_DIR = 'un_comtrade_metals_2022'      # Comtrade 2022 exports to World by reporter, comtrade_X_<prefix>_2022.json
METAL_CEILING_TOL_MUSD = 200.0                     # S07-H23: no listed row ends more than 0.2 bn above its ceiling
# beta v5 T1 (three choices, Aguiar et al. 2025 p.12; GTAP 7 ch.9A p.9A-2): re-exports the v4 tier-1 cap kept
RX_HIGH = 'rx_share_at_least_0.90_capped_at_baci_less_comtrade_domestic_exports_not_at_the_prior'
RX_HIGH_SHARE = 0.9
RX_SURPLUS = 'listed_non_reporters_sector_exports_above_prior_capped_at_imports_where_imports_exceed_exports'
RX_SURPLUS_COLUMNS = ('region', 'source', 'decided_by', 'decided_at', 'basis')
HKG_DX_CAP = 'hkg_exports_above_csd_domestic_exports_by_destination_and_hs2_to_the_origin'
# beta v5 T2 (choice reexport_rx_usa_bel = usa_bel_nbb): BEL from NBB's own national and community concept tables
NBB_BEL_FILE = 'nbb_bel_trade_2022/bel_nbb_concepts_hs2_2022.csv'   # hs2, national_eur, community_eur (exports)
# beta v5 B (choice importer_floor): the mirror of the transit cap. A listed importer's BACI imports outside energy (S11)
# and precious metals are raised to its own customs total (UN Comtrade, CIF over the importer's beta v4 VCIF/VFOB), the
# top-up placed on the partner x HS2 cells where the importer reports more than BACI holds
IMPORTER_FLOOR = 'listed_importers_baci_imports_raised_to_own_customs_by_partner_hs2_excluding_energy_precious_and_reimports'
IMPORTER_FLOOR_COLUMNS = ('region', 'reporter_code', 'cif_fob', 'excluded_hs_prefixes', 'source', 'url', 'decided_by',
                          'decided_at', 'basis')
FLOOR_DIR = 'un_comtrade_import_floor_2022'        # M_<code>/M_<code>_<hs2>.json, M_<code>_TOTAL.json
# beta v5 B follow-up (choice importer_floor_partner_cap; build-thread rebuild QA 2026-10-27: TWN exports 540.9 bn after the
# floor against 477.8 bn in its own customs): a partner's top-up is cut so its BACI goods exports stay at most its own
# UN Comtrade 2022 total exports (FOB), single-country regions only; the cut part is not placed elsewhere
FLOOR_PARTNER_CAP = 'partner_topup_capped_at_own_comtrade_total_exports'
PARTNER_X_FILE = 'un_comtrade_partner_x_2022/comtrade_X_TOTAL_2022.json'
# beta v5 B2, M1, M2 (choice transit_import_cap = TRANSIT_CAP_V5): the v4 rows plus POL and KEN, and KGZ tightened to
# retained imports; cap_scope all_lines caps all goods lines with the excluded lines' BACI value inside the total
TRANSIT_CAP_V5 = 'importer_goods_imports_capped_at_wto_merchandise_imports_v5_rows_with_pol_ken_and_kgz_retained_imports'
TRANSIT_CAP_V5_COLUMNS = TRANSIT_CAP_COLUMNS + ('cap_scope', 'cif_fob', 'fix')
CHOICE_ORDER = (
    'goods_source', 'icio_compare', 'goods_sectors', 'mixed_sectors', 'dpabr_excluded',
    'reexport_hubs', 'baci_vintage', 'mirror_reconciliation', 'row_row_level', 'intra_composite',
    'valuation', 'b06_split', 'energy_override', 'hub_cap', 'pri_vir_trade', 'pri_vir_source',
    'flag_registry_ships', 'hub_margins', 'absent_pairs_fill', 'currency_lines', 'reexport_comtrade_rx', 'reexport_rx_usa_bel',
    'transit_import_cap', 'gold_reexport',
    'reexport_high_share', 'reexport_import_surplus', 'hkg_domestic_export_cap', 'importer_floor',
    'importer_floor_partner_cap',
)
ALLOWED = {
    'goods_source': {'baci_all_pairs'},
    'icio_compare': {'icio_goods_compare_s07r_report_only'},
    'goods_sectors': {' '.join(GOODS)},
    'mixed_sectors': {'ely_to_S11_only'},
    'dpabr_excluded': {'yes'},
    'reexport_hubs': {'HKG,NLD,SGP'},
    'baci_vintage': {'BACI HS17 V202601 year 2022'},
    'mirror_reconciliation': {'baci_cepii_as_published'},
    'row_row_level': {'baci_fob'},
    'intra_composite': {'diagonal'},
    'valuation': {'fob_pre_export_tax'},
    'b06_split': {'baci_hs_direct'},
    'energy_override': {'defer_to_S11'},
    'hub_cap': {'report_only'},
    'pri_vir_trade': {'in_baci_842'},
    'pri_vir_source': {'census_intltrade_statehs_2022_hs6'},
    'flag_registry_ships': {'drop_hs8901_8906_open_registries'},
    'hub_margins': {'hkg_reexport_margin_to_trd_services'},
    # beta v4 P13 and P22 (2026-10-26)
    'absent_pairs_fill': {'baci_2021_hs6_times_world_hs2_growth_where_the_country_pair_is_absent_on_every_2022_line', 'off'},
    'currency_lines': {'drop_hs490700_banknotes_and_securities', 'off'},
    # beta v4 P26 (tier 1 on; USA and BEL are David's call) and P18
    'reexport_comtrade_rx': {RX_TIER1, 'off'},
    'reexport_rx_usa_bel': set(RX_EXTRA),
    'transit_import_cap': {TRANSIT_CAP, TRANSIT_CAP_V5, 'off'},
    'gold_reexport': {GOLD_RX, METAL_RX, 'off'},
    # beta v5 (David approved the v5 package 2026-10-27 08:39 UTC): T1, B
    'reexport_high_share': {RX_HIGH, 'off'},
    'reexport_import_surplus': {RX_SURPLUS, 'off'},
    'hkg_domestic_export_cap': {HKG_DX_CAP, 'off'},
    'importer_floor': {IMPORTER_FLOOR, 'off'},
    'importer_floor_partner_cap': {FLOOR_PARTNER_CAP, 'off'},
}
ABSENT_FILL = 'baci_2021_hs6_times_world_hs2_growth_where_the_country_pair_is_absent_on_every_2022_line'
CURRENCY_DROP = 'drop_hs490700_banknotes_and_securities'
CURRENCY_HS6 = ('490700',)
FILL_YEAR = 2021
GTAP_STATUS = {'gtap', 'approved_departure', 'departure_logged', 'not_in_gtap_text'}
# The 27 merchandise industries. wat pub art pro pst stay in VXSB but are not in the ICIO goods residual.
GOODS_27 = tuple(s for s in GOODS if s not in MOVED)
ICIO_INDUSTRIES = []
for _s in GOODS_27:
    _ic = 'B06' if _s in ('oil', 'gas') else _s
    if _ic not in ICIO_INDUSTRIES:
        ICIO_INDUSTRIES.append(_ic)
# Concordance still labels these ely. They are not electricity. Remap before the DuckDB sum.
# 220190 is GTAP BT (links split fbt/ely/wat); the whole line goes to fbt.
# 270500 is GTAP GDT, which S01 merges into ely; it is booked as gas and flagged.
# 284450 is GTAP CHM. 271600 stays ely.
ELY_NOT_ELEC = {'220190': 'fbt', '270500': 'gas', '284450': 'chm'}
CENSUS_CONTROL_ITEMS = (
    'PR_exports', 'PR_imports', 'VI_exports', 'VI_imports', 'excluded_sectors', 'excluded_limit',
)
CENSUS_JSON_FILES = (
    ('PR', 'exports', 'pr_exports_statehs_hs6_2022.json'),
    ('PR', 'imports', 'pr_imports_statehs_hs6_2022.json'),
    ('VI', 'exports', 'vi_exports_statehs_hs6_2022.json'),
    ('VI', 'imports', 'vi_imports_statehs_hs6_2022.json'),
)
DROP = 1e-12
SIZE_LIMIT = 50 * 1024 * 1024


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


def link(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.lexists(dst):
        if os.path.realpath(dst) == os.path.realpath(src):
            return
        os.remove(dst)
    os.symlink(src, dst)


def ensure_cache(paths, fill_year=None):
    """Point the prep's cache at the MANIFEST files, and extract the 2022 BACI year (and fill_year, beta v4 P13). Returns the
    fill year's CSV path, or None."""
    raw = os.path.join(os.environ['TRADE_PREP_CACHE'], 'raw')
    link(paths['baci_zip'], os.path.join(raw, 'BACI_HS17_V202601.zip'))
    link(paths['xlsx'], os.path.join(raw, 'ref', 'HS2017toSITC4.xlsx'))
    link(paths['countries'], os.path.join(raw, 'ref', 'countries.json'))
    link(paths['api_txt'], os.path.join(raw, 'probes', 'API_eng.txt'))
    for name in ('tx_hs2.json', 'rx_hs2.json', 'rx_od.json', 'dx_hs2.json', 'totals.json', 'm_co_hs2.json'):
        link(paths[name], os.path.join(raw, 'hk', name))
    for name in ('M451521.json', 'M451501.json', 'M451001.json', 'M451001_imports.json'):
        link(paths[name], os.path.join(raw, 'sg', name))
    for name in ('typed_2022.json', 'landen.json', 'sitc.json'):
        link(paths[name], os.path.join(raw, 'cbs', name))
    dest = os.path.join(raw, 'baci')
    os.makedirs(dest, exist_ok=True)
    csv_path = os.path.join(dest, 'BACI_HS17_Y2022_V202601.csv')
    cc_path = os.path.join(dest, 'country_codes_V202601.csv')
    if not (os.path.exists(csv_path) and os.path.getsize(csv_path) > 300_000_000 and os.path.exists(cc_path)):
        with zipfile.ZipFile(paths['baci_zip']) as zf:
            zf.extract('BACI_HS17_Y2022_V202601.csv', dest)
            zf.extract('country_codes_V202601.csv', dest)
    if fill_year is not None:
        # beta v4 P13 (choice absent_pairs_fill): the 2021 year file of the same locked zip
        name = f'BACI_HS17_Y{fill_year}_V202601.csv'
        if not (os.path.exists(os.path.join(dest, name)) and os.path.getsize(os.path.join(dest, name)) > 300_000_000):
            with zipfile.ZipFile(paths['baci_zip']) as zf:
                zf.extract(name, dest)
        return os.path.join(dest, name)
    return None


def load_choices(path):
    rows = list(csv.DictReader(open(path)))
    return {r['choice']: r for r in rows}


def apply_hub_slim(con, hub, identified_sql, weight_sql, debit_imports=True):
    """The prep's hub update without the HS6 ledger (that table is tens of millions of rows).

    Totals are the same identities as baci_reexports.apply_hub: funded removal, the
    origin-to-destination addition, and the intra-region addition.
    """
    for table in ('identified', 'claim', 'scale', 'funded', 'delta'):
        con.execute(f'DROP TABLE IF EXISTS {table}')
    con.execute(f'CREATE TABLE identified AS {identified_sql}')
    con.execute(f'CREATE TABLE claim AS {weight_sql}')
    stats = settle_claim(con, hub, debit_imports=debit_imports)
    for table in ('identified', 'claim'):
        con.execute(f'DROP TABLE IF EXISTS {table}')
    return {'funded': stats[0], 'added': stats[1], 'intra': stats[2]}


def settle_claim(con, hub, imports=None, debit_imports=True):
    """Fund the claim table from the hub's imports and move the funded value to origin -> destination.

    imports: a table of the hub's imports (origin, hs6, value) to read in place of flows; same rows for these HS6.
    debit_imports False (beta v5 T1, HKG domestic-export cap): the origin -> hub imports are not lowered, because the
    retained-import step (retained_imports.apply) later sets them to the published retained imports, which already
    leave out every re-export. The funding cap by origin x HS6 still applies.
    Returns (funded, added, intra) in thousand USD.
    """
    src = (f"{imports} m ON m.origin = c.origin AND m.hs6 = c.hs6" if imports else
           f"flows m ON m.exporter = c.origin AND m.importer = '{hub}' AND m.hs6 = c.hs6")
    con.execute(f"""
        CREATE TABLE scale AS
        SELECT c.origin, c.hs6,
               SUM(c.claim) AS claim_sum,
               COALESCE(m.value, 0) AS available,
               CASE
                 WHEN SUM(c.claim) <= COALESCE(m.value, 0) THEN 1.0
                 WHEN COALESCE(m.value, 0) <= 0 THEN 0.0
                 ELSE COALESCE(m.value, 0) / SUM(c.claim)
               END AS scale
        FROM claim c
        LEFT JOIN {src}
        GROUP BY c.origin, c.hs6, m.value
    """)
    con.execute("""
        CREATE TABLE funded AS
        SELECT c.dest, c.hs6, c.origin, c.claim * s.scale AS funded
        FROM claim c
        JOIN scale s USING (origin, hs6)
        WHERE c.claim * s.scale > 0
    """)
    con.execute(f"""
        CREATE TABLE delta AS
        SELECT exporter, importer, hs6, SUM(d_value) AS d_value
        FROM (
            SELECT '{hub}' AS exporter, dest AS importer, hs6, -SUM(funded) AS d_value
            FROM funded GROUP BY dest, hs6
            UNION ALL
            SELECT origin AS exporter, '{hub}' AS importer, hs6, -SUM(funded) AS d_value
            FROM funded WHERE {'TRUE' if debit_imports else 'FALSE'} GROUP BY origin, hs6
            UNION ALL
            SELECT origin AS exporter, dest AS importer, hs6, SUM(funded) AS d_value
            FROM funded WHERE origin <> dest GROUP BY origin, dest, hs6
        )
        GROUP BY 1, 2, 3
    """)
    con.execute(f"""
        INSERT INTO intra_add
        SELECT '{hub}', origin, hs6, SUM(funded)
        FROM funded WHERE origin = dest
        GROUP BY origin, hs6
    """)
    con.execute("""
        UPDATE flows
        SET value = flows.value + delta.d_value, qty = NULL, qty_ok = FALSE
        FROM delta
        WHERE flows.exporter = delta.exporter
          AND flows.importer = delta.importer
          AND flows.hs6 = delta.hs6
    """)
    con.execute("""
        INSERT INTO flows
        SELECT d.exporter, d.importer, d.hs6, d.d_value, NULL, FALSE
        FROM delta d
        ANTI JOIN flows f USING (exporter, importer, hs6)
    """)
    stats = con.execute("""
        SELECT COALESCE(SUM(funded), 0),
               COALESCE(SUM(funded) FILTER (WHERE origin <> dest), 0),
               COALESCE(SUM(funded) FILTER (WHERE origin = dest), 0)
        FROM funded
    """).fetchone()
    for table in ('scale', 'funded', 'delta'):
        con.execute(f'DROP TABLE IF EXISTS {table}')
    return stats


# Claim rows per chunk in apply_rx_chunked. A Comtrade RX region's claim is destination x HS6 x origin; whole, the
# first region's claim and the UPDATE of flows from it spilled past the container disk (S16 dry run 2, 26 Oct).
CLAIM_CHUNK_ROWS = 2_000_000


def apply_rx_chunked(con, hub, identified_sql, budget=CLAIM_CHUNK_ROWS, debit_imports=True):
    """apply_hub_slim with baci_reexports.claim_import_share, settled in HS2 chunks of at most `budget` claim rows.

    The same result: identified is built once over all HS6 (the sector cap in identified_rx needs every HS6), and every
    later table and the flows update are per HS6. A chunk changes only its own HS6 cells, so the hub's imports read once
    at the start are the imports each later chunk would have read. A single HS2 above the budget is its own chunk.
    """
    for table in ('identified_all', 'hub_m', 'hub_t', 'identified', 'claim'):
        con.execute(f'DROP TABLE IF EXISTS {table}')
    con.execute(f'CREATE TABLE identified_all AS {identified_sql}')
    con.execute(f"""
        CREATE TABLE hub_m AS
        SELECT exporter AS origin, hs6, value FROM flows
        WHERE importer = '{hub}' AND exporter <> '{hub}' AND value > 0
    """)
    con.execute('CREATE TABLE hub_t AS SELECT hs6, SUM(value) AS total_import FROM hub_m GROUP BY hs6')
    sizes = con.execute("""
        SELECT substr(i.hs6, 1, 2) AS hs2, SUM(i.k * m.n) AS rows
        FROM (SELECT hs6, COUNT(*) AS k FROM identified_all GROUP BY hs6) i
        JOIN (SELECT hs6, COUNT(*) AS n FROM hub_m GROUP BY hs6) m USING (hs6)
        GROUP BY 1 ORDER BY 1
    """).fetchall()
    chunks, cur, n = [], [], 0
    for hs2, rows in sizes:
        if cur and n + rows > budget:
            chunks.append(cur)
            cur, n = [], 0
        cur.append(hs2)
        n += rows
    if cur:
        chunks.append(cur)
    tot = [0.0, 0.0, 0.0]
    for chunk in chunks:
        keys = ', '.join(f"'{h}'" for h in chunk)
        con.execute(f'CREATE TABLE identified AS SELECT * FROM identified_all WHERE substr(hs6, 1, 2) IN ({keys})')
        con.execute("""
            CREATE TABLE claim AS
            SELECT i.dest, i.hs6, m.origin, i.identified * m.value / t.total_import AS claim
            FROM identified i
            JOIN hub_m m ON m.hs6 = i.hs6
            JOIN hub_t t ON t.hs6 = i.hs6
        """)
        st = settle_claim(con, hub, imports='hub_m', debit_imports=debit_imports)
        tot = [a + b for a, b in zip(tot, st)]
        for table in ('identified', 'claim'):
            con.execute(f'DROP TABLE {table}')
    for table in ('identified_all', 'hub_m', 'hub_t'):
        con.execute(f'DROP TABLE {table}')
    return {'funded': tot[0], 'added': tot[1], 'intra': tot[2], 'chunks': len(chunks),
            'claim_rows': sum(r for _h, r in sizes)}


def run_prep(S, hs_rows, composite_regions, retained_cfg, flag_isos, fill_csv=None, drop_cash=False, rx_dir=None, rx_extra=(),
             prior_x=None, transit_caps=None, bel_csv=None, gold_rows=None, rx_high=None, bel_nbb=False, surplus_regions=(),
             hkg_dx=False, floor=None, metal=None):
    """Run the prep cleaner in memory and return sector aggregates. Thousand USD inside DuckDB.

    Beta v5: rx_high (T1 reexport_high_share), surplus_regions (T1 reexport_import_surplus), hkg_dx (T1
    hkg_domestic_export_cap), floor = (rows, floor_dir, partner exports file or None) (B importer_floor, importer_floor_partner_cap), metal = (rows, customs_dir, gold USD per kg)
    (G gold_reexport = METAL_RX, in place of gold_rows), bel_nbb (T2). Off (None, (), False) is beta v4."""
    prep_checks = []
    iso_to_region, regions = BR.load_region_map()
    if len(regions) != 167:
        raise SystemExit(f'expected 167 regions, got {len(regions)}')
    overrides = BR.load_overrides()
    iso2, names, _ambiguous = BR.load_iso2_to_iso3()
    con = duckdb.connect()
    con.execute("SET preserve_insertion_order = false")
    # One thread so the SUM of 11 million BACI rows is the same on the second run.
    con.execute("SET threads = 1")
    con.execute("SET memory_limit = '3GB'")
    duck_dir = os.path.join(os.environ['TRADE_PREP_CACHE'], 'duck')
    os.makedirs(duck_dir, exist_ok=True)
    os.makedirs(BR.OUT, exist_ok=True)
    con.execute(f"SET temp_directory = '{duck_dir}'")
    con.execute("SET max_temp_directory_size = '80GB'")
    S.log('prep: loading HK, SG and NL shares')
    BR.load_hk_shares(con, iso2, iso_to_region, prep_checks)
    BR.load_sg_shares(con, names, overrides, iso_to_region, prep_checks)
    BR.load_nl_shares(con, iso2, overrides, iso_to_region, prep_checks)
    hk_overall, hk_a, hk_published = RI.load_hk_ratios(con, BR.RAW, retained_cfg, iso2, iso_to_region, prep_checks)
    sg_overall = RI.load_sg_ratios(con, BR.RAW, BR.HS_SITC, prep_checks, retained_cfg['SGP']['margin_factor'])
    nl_overall, nl_totals = RI.load_nl_ratios(con, BR.RAW, prep_checks)
    ri_overall = {'HKG': hk_overall, 'SGP': sg_overall, 'NLD': nl_overall}
    # Published all-goods retained/imports ratios: Table 3.1 for HKG; SingStat totals for SGP
    # (the SGP fit ratio is the published one, margin factor 1); CBS national-concept totals for NLD.
    ri_published = {'HKG': hk_published, 'SGP': sg_overall, 'NLD': nl_overall}
    con.execute('CREATE TABLE overall(hub VARCHAR, ratio DOUBLE)')
    con.executemany('INSERT INTO overall VALUES (?, ?)', sorted(ri_overall.items()))
    con.execute('CREATE TABLE hs(hs6 VARCHAR, sector VARCHAR, agrees VARCHAR)')
    con.executemany('INSERT INTO hs VALUES (?, ?, ?)', hs_rows)
    S.log('prep: loading BACI')
    BR.load_baci(con, iso_to_region)
    # beta v4 P13 and P22: fill the country pairs absent in 2022 from BACI 2021; drop the currency line (before the ships
    # drop, which rebuilds flows and intra from mapped)
    fill = fill_absent_pairs(con, fill_csv) if fill_csv else dict(rows=0, value_kusd=0.0, value_year_kusd=0.0, pairs=[])
    cash = drop_currency_lines(con) if drop_cash else dict(rows=0, value_kusd=0.0, top=[], left=0)
    ships = drop_flag_ships(con, flag_isos)
    S.log(f'flag-registry ships (HS 8901-8906) dropped: {ships["value"]:.3f} kUSD in {ships["rows"]} rows')
    # Coverage and the raw geography, saved before the big tables are dropped.
    unmapped_value, unmapped_rows = con.execute(
        'SELECT COALESCE(SUM(value), 0), COUNT(*) FROM unmapped').fetchone()
    neg_raw = con.execute('SELECT COALESCE(SUM(value < 0), 0) FROM raw').fetchone()[0]
    hs_gap, hs_n = con.execute("""
        SELECT COALESCE(SUM(m.value), 0), COUNT(DISTINCT m.hs6)
        FROM mapped m ANTI JOIN hs h ON m.hs6 = h.hs6
    """).fetchone()
    s19_region = con.execute("SELECT COALESCE(MAX(region), '') FROM reg WHERE iso3 = 'S19'").fetchone()[0]
    f6_value = con.execute("""
        SELECT COALESCE(SUM(value), 0) FROM mapped WHERE exp_iso = 'S19' OR imp_iso = 'S19'
    """).fetchone()[0]
    disagree = con.execute("""
        SELECT COALESCE(SUM(m.value), 0) FROM mapped m JOIN hs h USING (hs6) WHERE h.agrees <> 'yes'
    """).fetchone()[0]
    con.execute("""
        CREATE TABLE raw_bi AS
        SELECT exp_region AS e, imp_region AS i, h.sector AS sector, SUM(m.value) / 1000.0 AS musd
        FROM mapped m JOIN hs h ON m.hs6 = h.hs6
        WHERE exp_region IS NOT NULL AND imp_region IS NOT NULL AND exp_region <> imp_region
        GROUP BY 1, 2, 3
    """)
    con.execute("""
        CREATE TABLE raw_xwe_to AS
        SELECT exp_region AS e,
               CASE WHEN imp_iso = 'ISL' THEN 'ISL' ELSE 'XWEr' END AS i,
               h.sector AS sector, SUM(m.value) / 1000.0 AS musd
        FROM mapped m JOIN hs h ON m.hs6 = h.hs6
        WHERE imp_region = 'XWE' AND exp_region IS NOT NULL AND exp_region <> 'XWE'
        GROUP BY 1, 2, 3
    """)
    con.execute("""
        CREATE TABLE raw_xwe_from AS
        SELECT CASE WHEN exp_iso = 'ISL' THEN 'ISL' ELSE 'XWEr' END AS e,
               CASE WHEN imp_iso = 'ISL' THEN 'ISL' WHEN imp_region = 'XWE' THEN 'XWEr' ELSE imp_region END AS i,
               h.sector AS sector, SUM(m.value) / 1000.0 AS musd
        FROM mapped m JOIN hs h ON m.hs6 = h.hs6
        WHERE exp_region = 'XWE' AND imp_region IS NOT NULL
        GROUP BY 1, 2, 3
    """)
    raw_bi = con.execute('SELECT e, i, sector, musd FROM raw_bi').fetchdf()
    raw_to = con.execute('SELECT e, i, sector, musd FROM raw_xwe_to').fetchdf()
    raw_from = con.execute('SELECT e, i, sector, musd FROM raw_xwe_from').fetchdf()
    pre_hub = {}
    for code in ('HKG', 'NLD', 'SGP', 'BEL', 'ARE', 'PAN'):
        pre_hub[code] = con.execute(
            'SELECT COALESCE(SUM(value), 0) FROM flows WHERE exporter = ?', [code]).fetchone()[0]
    raw_bilateral = con.execute('SELECT COALESCE(SUM(value), 0) FROM flows').fetchone()[0]
    raw_intra = con.execute('SELECT COALESCE(SUM(value), 0) FROM intra').fetchone()[0]
    baci_usa_codes = con.execute("""
        SELECT ce.code, ce.iso3 FROM cc ce
        JOIN reg re ON re.iso3 = ce.iso3
        WHERE re.region = 'USA'
        ORDER BY ce.code
    """).fetchall()
    baci_can_codes = con.execute("""
        SELECT ce.code, ce.iso3 FROM cc ce
        JOIN reg re ON re.iso3 = ce.iso3
        WHERE re.region = 'CAN'
        ORDER BY ce.code
    """).fetchall()
    # beta v4 P26 tier 1: Comtrade RX / X shares by HS2, read while BACI's country codes are loaded
    rx_regions, rx_left = [], []
    if rx_dir:
        single = {iso: reg for iso, reg in iso_to_region.items() if iso == reg and reg not in composite_regions}
        rx_regions, rx_left = load_rx_shares(con, rx_dir, single, rx_extra, bel_csv, high=rx_high, bel_nbb=bel_nbb)
    if rx_dir or surplus_regions:
        con.execute('CREATE TABLE prior_x(region VARCHAR, sector VARCHAR, x DOUBLE)')
        con.executemany('INSERT INTO prior_x VALUES (?, ?, ?)', [(r, s, v * 1000.0) for (r, s), v in (prior_x or {}).items()])
    # beta v5 B and G: the importer's own Comtrade imports and the exporters' own Comtrade metal exports, read while
    # BACI's country codes are loaded
    floor_stats = load_floor_imports(con, floor[1], floor[0]) if floor else {}
    partner_caps, partner_left = load_partner_caps(con, floor[2], composite_regions) if floor and floor[2] else (None, [])
    metal_rows = []
    if metal:
        codes = dict(con.execute('SELECT code, iso3 FROM cc').fetchall())
        own_by = {}
        for reg, prefix, kg, price, own_key, origin in metal[0]:
            if own_key == 'comtrade' and prefix not in own_by:
                own_by[prefix] = metal_own_customs(os.path.join(metal[1], f'comtrade_X_{prefix}_2022.json'), codes)
            own = own_by[prefix].get(reg, 0.0) if own_key == 'comtrade' else 0.0
            metal_rows.append((reg, prefix, kg, metal[2] if price == 'gold' else 0.0, own, origin))
    for table in ('raw', 'mapped', 'unmapped', 'cc', 'raw_bi', 'raw_xwe_to', 'raw_xwe_from'):
        con.execute(f'DROP TABLE IF EXISTS {table}')
    gc.collect()
    con.execute('CREATE TABLE intra_add(hub VARCHAR, region VARCHAR, hs6 VARCHAR, value DOUBLE)')
    flows_before = {}
    hub_stats = {}
    for hub, ident, claim in (
        ('HKG', BR.identified_hk(), BR.claim_hk()),
        ('NLD', BR.identified_nl(), BR.claim_import_share('NLD')),
        ('SGP', RI.identified_sg_fitted(), BR.claim_import_share('SGP')),
    ):
        flows_before[hub] = con.execute('SELECT COALESCE(SUM(value), 0) FROM flows').fetchone()[0]
        S.log(f'prep: removing {hub} re-exports')
        if hub in RI.HUBS:
            RI.snapshot(con, hub, 'pre')
        if hub == 'SGP':
            RI.fit_sg_identified(con, prep_checks)
        stats = apply_hub_slim(con, hub, ident, claim)
        if hub in RI.HUBS:
            RI.snapshot(con, hub, 'post')
        stats['flows_after'] = con.execute('SELECT COALESCE(SUM(value), 0) FROM flows').fetchone()[0]
        stats['flows_before'] = flows_before[hub]
        stats['exports_after'] = con.execute(
            'SELECT COALESCE(SUM(value), 0) FROM flows WHERE exporter = ?', [hub]).fetchone()[0]
        hub_stats[hub] = stats
        S.log(f'{hub} funded {stats["funded"]:.3f} kUSD; bilateral sum {stats["flows_before"]:.3f} -> {stats["flows_after"]:.3f}')
    # beta v5 T1 (choice hkg_domestic_export_cap): HKG exports above C&SD domestic exports by destination x HS2 go to the
    # origin; HKG imports are left to the retained-import step (no debit)
    hkg_dx_stats = {}
    if hkg_dx:
        x0 = con.execute("SELECT COALESCE(SUM(value), 0) FROM flows WHERE exporter = 'HKG'").fetchone()[0]
        w0 = con.execute('SELECT COALESCE(SUM(value), 0) FROM flows').fetchone()[0]
        hkg_dx_stats = apply_hub_slim(con, 'HKG', identified_hk_dx(retained_cfg['HKG']['usd_hkd']), BR.claim_hk(), debit_imports=False)
        hkg_dx_stats['exports_before'] = x0
        hkg_dx_stats['exports_after'] = con.execute("SELECT COALESCE(SUM(value), 0) FROM flows WHERE exporter = 'HKG'").fetchone()[0]
        hkg_dx_stats['world_before'] = w0
        hkg_dx_stats['world_after'] = con.execute('SELECT COALESCE(SUM(value), 0) FROM flows').fetchone()[0]
        hkg_dx_stats['by_hs2'] = con.execute("""
            SELECT substr(hs6, 1, 2), SUM(value) FROM flows WHERE exporter = 'HKG' AND value > 0 GROUP BY 1 ORDER BY 2 DESC LIMIT 10
        """).fetchall()
        S.log(f'T1 HKG domestic-export cap: funded {hkg_dx_stats["funded"]:.3f} kUSD; HKG exports {x0:.3f} -> {hkg_dx_stats["exports_after"]:.3f}')
    # beta v4 P26 tier 1 (choice reexport_comtrade_rx; Aguiar et al. 2025 p.12, GTAP 7 ch.9A p.9A-2): every other Comtrade RX
    # reporter's re-exports leave its exports and its imports and go to the origin -> destination flow, as for NLD and SGP
    rx_stats = {}
    for reg in rx_regions:
        x0 = con.execute('SELECT COALESCE(SUM(value), 0) FROM flows WHERE exporter = ?', [reg]).fetchone()[0]
        st = apply_rx_chunked(con, reg, identified_rx(reg, rx_high))
        st['exports_before'] = x0
        st['exports_after'] = con.execute('SELECT COALESCE(SUM(value), 0) FROM flows WHERE exporter = ?', [reg]).fetchone()[0]
        rx_stats[reg] = st
        S.log(f'P26 tier 1 {reg}: funded {st["funded"]:.3f} kUSD; {st["claim_rows"]} claim rows in {st["chunks"]} chunks')
    if rx_regions:
        S.log(f'P26 tier 1: {len(rx_regions)} Comtrade RX regions, removed {sum(s["funded"] for s in rx_stats.values()) / 1e6:.3f} bn')
    # beta v5 T1 (choice reexport_import_surplus): the listed non-reporters' re-export sectors by the import-surplus test
    surplus_stats = {}
    for reg in surplus_regions:
        x0 = con.execute('SELECT COALESCE(SUM(value), 0) FROM flows WHERE exporter = ?', [reg]).fetchone()[0]
        st = apply_rx_chunked(con, reg, identified_surplus(reg))
        st['exports_before'] = x0
        st['exports_after'] = con.execute('SELECT COALESCE(SUM(value), 0) FROM flows WHERE exporter = ?', [reg]).fetchone()[0]
        surplus_stats[reg] = st
        S.log(f'T1 import surplus {reg}: funded {st["funded"]:.3f} kUSD')
    # beta v4 P18 (choice transit_import_cap): the transit regions' imports capped at their national merchandise imports
    transit = transit_cap(con, transit_caps) if transit_caps else []
    # beta v5 B (choice importer_floor): the listed importers' imports raised to their own customs totals
    floor_out = importer_floor(con, [r[0] for r in floor[0]], {r[0]: r[3] for r in floor[0]}, partner_caps) if floor else []
    for rec in floor_out:
        rec.update(floor_stats.get(rec['region'], {}))
        S.log(f'B importer floor {rec["region"]}: {rec["before"]:.3f} -> target {rec["target"]:.3f} kUSD; added {rec["added"]:.3f}'
              + (f'; held back by partner caps {rec["capped"]:.3f} (' + ', '.join(f'{p} {r:.0f} room' for p, _x, _c, _a, r in rec['capped_by']) + ')'
                 if rec['capped_by'] else ''))
    # beta v4 P39 (choice gold_reexport): unrecorded dore re-exported from the listed regions, rerouted from the origin;
    # beta v5 G (gold_reexport = METAL_RX): the generalised rule with the drop mode
    gold = gold_reexport(con, gold_rows[0], gold_rows[1]) if gold_rows else []
    metal_out = metal_reexport(con, metal_rows) if metal else []
    # Hub imports become retained imports (retained_imports.py). Hub import cells only.
    retained = {}
    for hub in RI.HUBS:
        S.log(f'prep: {hub} imports to retained imports')
        before_other = con.execute(
            f"SELECT COALESCE(SUM(value), 0), COUNT(*) FROM flows WHERE importer <> '{hub}' OR exporter = '{hub}'").fetchone()
        retained[hub] = RI.apply(con, hub)
        after_other = con.execute(
            f"SELECT COALESCE(SUM(value), 0), COUNT(*) FROM flows WHERE importer <> '{hub}' OR exporter = '{hub}'").fetchone()
        retained[hub]['other_before'] = before_other
        retained[hub]['other_after'] = after_other
        retained[hub]['overall'] = ri_overall[hub]
        retained[hub]['published'] = ri_published[hub]
        if hub == 'SGP':
            retained[hub]['oil_ratio'] = con.execute("SELECT ratio FROM sg_ret WHERE cat = 'oil'").fetchone()[0]
        retained[hub]['chn'] = con.execute(
            "SELECT COALESCE(SUM(gross), 0), COALESCE(SUM(current), 0), COALESCE(SUM(final), 0) FROM target WHERE exporter = 'CHN'"
        ).fetchone()
        retained[hub]['by_origin_sector'] = con.execute("""
            SELECT t.exporter, h.sector, SUM(t.gross) / 1000.0, SUM(t.current) / 1000.0, SUM(t.final) / 1000.0,
                   SUM(t.current - t.final) FILTER (WHERE t.basis NOT IN ('origin_hs2', 'category')) / 1000.0
            FROM target t JOIN hs h ON h.hs6 = t.hs6
            GROUP BY 1, 2 ORDER BY 1, 2
        """).fetchall()
        S.log(f'{hub} retained: gross {retained[hub]["gross"]:.3f} kUSD; before {retained[hub]["before"]:.3f}; '
              f'after {retained[hub]["after"]:.3f}; removed {retained[hub]["removed"]:.3f} in {retained[hub]["cells"]} cells')
    S.log('prep: HKG re-export margin to HKG trd exports')
    hkm = RI.hk_margin(con, BR.RAW, hk_a, retained_cfg['HKG']['usd_hkd'], iso2, iso_to_region, prep_checks)
    hkm['by_dest'] = con.execute('SELECT dest, value / 1000.0 FROM hk_margin ORDER BY dest').fetchall()
    hkm['by_pair'] = con.execute(
        'SELECT exporter, importer, applied / 1000.0 FROM hkm WHERE applied > 0 ORDER BY applied DESC LIMIT 10').fetchall()
    neg_n, neg_min = con.execute(
        'SELECT COUNT(*), COALESCE(MIN(value), 0) FROM flows WHERE value < -1e-6').fetchone()
    post_hub = {}
    for code in ('HKG', 'NLD', 'SGP', 'BEL', 'ARE', 'PAN'):
        post_hub[code] = con.execute(
            'SELECT COALESCE(SUM(value), 0) FROM flows WHERE exporter = ?', [code]).fetchone()[0]
    S.log('prep: aggregating cleaned flows to sectors')
    clean_bi = con.execute("""
        SELECT f.exporter AS e, f.importer AS i, h.sector AS sector,
               SUM(CASE WHEN f.value < 0 AND f.value > -1e-6 THEN 0 ELSE f.value END) / 1000.0 AS musd
        FROM flows f JOIN hs h ON f.hs6 = h.hs6
        WHERE f.exporter <> f.importer
        GROUP BY 1, 2, 3
    """).fetchdf()
    clean_intra = con.execute("""
        SELECT t.region AS r, h.sector AS sector, SUM(t.value) / 1000.0 AS musd
        FROM (
            SELECT region, hs6, value FROM intra
            UNION ALL
            SELECT region, hs6, value FROM intra_add
        ) t JOIN hs h ON t.hs6 = h.hs6
        GROUP BY 1, 2
    """).fetchdf()
    clean_bilateral = con.execute('SELECT COALESCE(SUM(value), 0) FROM flows').fetchone()[0]
    clean_intra_sum = con.execute("""
        SELECT COALESCE((SELECT SUM(value) FROM intra), 0) + COALESCE((SELECT SUM(value) FROM intra_add), 0)
    """).fetchone()[0]
    h5_gap = con.execute("""
        WITH bi AS (
            SELECT f.exporter AS e, f.importer AS i, h.sector AS sector,
                   SUM(CASE WHEN f.value < 0 AND f.value > -1e-6 THEN 0 ELSE f.value END) / 1000.0 AS musd
            FROM flows f JOIN hs h ON f.hs6 = h.hs6
            WHERE f.exporter <> f.importer
            GROUP BY 1, 2, 3
        ),
        og AS (
            SELECT f.exporter AS e, f.importer AS i,
                   SUM(CASE WHEN f.hs6 IN ('270900', '271410')
                            THEN CASE WHEN f.value < 0 AND f.value > -1e-6 THEN 0 ELSE f.value END
                            ELSE 0 END) / 1000.0 AS oil,
                   SUM(CASE WHEN f.hs6 IN ('271111', '271121', '270500')
                            THEN CASE WHEN f.value < 0 AND f.value > -1e-6 THEN 0 ELSE f.value END
                            ELSE 0 END) / 1000.0 AS gas
            FROM flows f
            WHERE f.exporter <> f.importer
            GROUP BY 1, 2
        )
        SELECT COALESCE(MAX(ABS(COALESCE(bo.musd, 0) - COALESCE(og.oil, 0))), 0),
               COALESCE(MAX(ABS(COALESCE(bg.musd, 0) - COALESCE(og.gas, 0))), 0)
        FROM og
        LEFT JOIN bi bo ON bo.e = og.e AND bo.i = og.i AND bo.sector = 'oil'
        LEFT JOIN bi bg ON bg.e = og.e AND bg.i = og.i AND bg.sector = 'gas'
    """).fetchone()
    wrong_parent = con.execute("""
        SELECT COALESCE(SUM(CASE WHEN f.value < 0 AND f.value > -1e-6 THEN 0 ELSE f.value END), 0)
        FROM flows f JOIN hs h ON f.hs6 = h.hs6
        WHERE (f.hs6 IN ('270900', '271410') AND h.sector <> 'oil')
           OR (f.hs6 IN ('271111', '271121', '270500') AND h.sector <> 'gas')
    """).fetchone()[0]
    usa_isos = [r[0] for r in con.execute(
        "SELECT DISTINCT iso3 FROM reg WHERE region = 'USA' ORDER BY 1").fetchall()]
    can_isos = [r[0] for r in con.execute(
        "SELECT DISTINCT iso3 FROM reg WHERE region = 'CAN' ORDER BY 1").fetchall()]
    # Independent of the Python cell dict. Goods only: bilateral plus composite diagonals, ely excluded.
    con.execute('CREATE TABLE composite_regions(region VARCHAR)')
    if composite_regions:
        con.executemany('INSERT INTO composite_regions VALUES (?)', [(r,) for r in sorted(composite_regions)])
    clip = 'CASE WHEN f.value < 0 AND f.value > -1e-6 THEN 0 ELSE f.value END'
    goods_bi_kusd = con.execute(f"""
        SELECT COALESCE(SUM({clip}), 0)
        FROM flows f JOIN hs h ON f.hs6 = h.hs6
        WHERE f.exporter <> f.importer AND h.sector <> 'ely'
    """).fetchone()[0]
    composite_intra_goods_kusd = con.execute("""
        SELECT COALESCE(SUM(CASE WHEN t.value < 0 AND t.value > -1e-6 THEN 0 ELSE t.value END), 0)
        FROM (
            SELECT region, hs6, value FROM intra
            UNION ALL
            SELECT region, hs6, value FROM intra_add
        ) t
        JOIN hs h ON t.hs6 = h.hs6
        JOIN composite_regions c ON t.region = c.region
        WHERE h.sector <> 'ely'
    """).fetchone()[0]
    sec_x = dict(con.execute(f"""
        SELECT h.sector, COALESCE(SUM({clip}), 0)
        FROM flows f JOIN hs h ON f.hs6 = h.hs6
        WHERE f.exporter <> f.importer AND h.sector <> 'ely'
        GROUP BY 1
    """).fetchall())
    sec_m = dict(con.execute(f"""
        SELECT h.sector, COALESCE(SUM({clip}), 0)
        FROM flows f JOIN hs h ON f.hs6 = h.hs6
        WHERE f.exporter <> f.importer AND h.sector <> 'ely'
        GROUP BY 1
    """).fetchall())
    sec_intra = dict(con.execute("""
        SELECT h.sector, COALESCE(SUM(CASE WHEN t.value < 0 AND t.value > -1e-6 THEN 0 ELSE t.value END), 0)
        FROM (
            SELECT region, hs6, value FROM intra
            UNION ALL
            SELECT region, hs6, value FROM intra_add
        ) t
        JOIN hs h ON t.hs6 = h.hs6
        JOIN composite_regions c ON t.region = c.region
        WHERE h.sector <> 'ely'
        GROUP BY 1
    """).fetchall())
    usa_can_mvh_kusd = con.execute(f"""
        SELECT COALESCE(SUM({clip}), 0)
        FROM flows f JOIN hs h ON f.hs6 = h.hs6
        WHERE f.exporter = 'USA' AND f.importer = 'CAN' AND h.sector = 'mvh'
    """).fetchone()[0]
    ely_moved = {}
    for hs6 in sorted(ELY_NOT_ELEC):
        bi_k, intra_k, single_k = con.execute("""
            SELECT
              COALESCE((
                SELECT SUM(CASE WHEN f.value < 0 AND f.value > -1e-6 THEN 0 ELSE f.value END)
                FROM flows f WHERE f.hs6 = ? AND f.exporter <> f.importer
              ), 0),
              COALESCE((
                SELECT SUM(t.value) FROM (
                    SELECT region, value FROM intra WHERE hs6 = ?
                    UNION ALL
                    SELECT region, value FROM intra_add WHERE hs6 = ?
                ) t JOIN composite_regions c ON t.region = c.region
              ), 0),
              COALESCE((
                SELECT SUM(t.value) FROM (
                    SELECT region, value FROM intra WHERE hs6 = ?
                    UNION ALL
                    SELECT region, value FROM intra_add WHERE hs6 = ?
                ) t ANTI JOIN composite_regions c ON t.region = c.region
              ), 0)
        """, [hs6, hs6, hs6, hs6, hs6]).fetchone()
        ely_moved[hs6] = {'bilateral_kusd': bi_k, 'composite_kusd': intra_k, 'single_kusd': single_k}
    con.close()
    return dict(
        prep_checks=prep_checks, unmapped_value=unmapped_value, unmapped_rows=unmapped_rows,
        neg_raw=neg_raw, hs_gap=hs_gap, hs_n=hs_n, s19_region=s19_region, f6_value=f6_value,
        disagree=disagree, raw_bi=raw_bi, raw_to=raw_to, raw_from=raw_from, pre_hub=pre_hub,
        post_hub=post_hub, hub_stats=hub_stats, neg_n=neg_n, neg_min=neg_min,
        clean_bi=clean_bi, clean_intra=clean_intra, raw_bilateral=raw_bilateral, raw_intra=raw_intra,
        clean_bilateral=clean_bilateral, clean_intra_sum=clean_intra_sum,
        h5_oil_gap=h5_gap[0], h5_gas_gap=h5_gap[1], wrong_parent_kusd=wrong_parent,
        usa_isos=usa_isos, can_isos=can_isos,
        baci_usa_codes=baci_usa_codes, baci_can_codes=baci_can_codes,
        goods_bi_kusd=goods_bi_kusd, composite_intra_goods_kusd=composite_intra_goods_kusd,
        sec_x_kusd=sec_x, sec_m_kusd=sec_m, sec_intra_kusd=sec_intra,
        usa_can_mvh_kusd=usa_can_mvh_kusd, ely_moved=ely_moved, retained=retained,
        ships=ships, hk_margin=hkm, nl_totals=nl_totals, fill=fill, cash=cash,
        rx_stats=rx_stats, rx_left=rx_left, transit=transit, gold=gold,
        hkg_dx=hkg_dx_stats, surplus=surplus_stats, floor=floor_out, metal=metal_out,
    )


SHIP_HS4 = ('8901', '8902', '8903', '8904', '8905', '8906')


def fill_absent_pairs(con, csv_fill, year=FILL_YEAR):
    """Beta v4 P13 (choice absent_pairs_fill; labelled departure: GTAP 12's merchandise-trade method is not public and GTAP 7
    ch.9A only selects between two reports). BACI is a mirror database, so a country pair where neither partner reported in
    2022 is missing on every HS line (RUS and BLR: 36.5 bn in 2021). For every country pair with no 2022 row in mapped
    and rows in the year file (BACI HS17 V202601, the same locked zip), the year's HS6 rows enter mapped at value x the
    world 2022/year growth of the HS2 chapter (all BACI rows of both years), tonnes as in that year (S11 then prices energy
    from them and RASes the volumes to 2022). Called before flows and intra are rebuilt (drop_flag_ships).
    Returns dict(rows, value_kusd, value_year_kusd, pairs: [(exp_region, imp_region, kUSD, energy kUSD)])."""
    con.execute(f"""
        CREATE TABLE raw_fill AS
        SELECT lpad(CAST(k AS VARCHAR), 6, '0') AS hs6, CAST(i AS INTEGER) AS exp_code, CAST(j AS INTEGER) AS imp_code,
               CAST(v AS DOUBLE) AS value, CAST(q AS DOUBLE) AS qty
        FROM read_csv('{csv_fill}', header=true, all_varchar=true)
        WHERE CAST(t AS INTEGER) = {int(year)}
    """)
    con.execute("""
        CREATE TABLE fill_growth AS
        SELECT a.ch, CASE WHEN b.v > 0 THEN a.v / b.v ELSE 1.0 END AS g
        FROM (SELECT substr(hs6, 1, 2) AS ch, SUM(value) AS v FROM raw GROUP BY 1) a
        JOIN (SELECT substr(hs6, 1, 2) AS ch, SUM(value) AS v FROM raw_fill GROUP BY 1) b USING (ch)
    """)
    con.execute("""
        CREATE TABLE fill_rows AS
        SELECT f.hs6, f.value * COALESCE(g.g, 1.0) AS value, f.qty, f.value AS value_year,
               ce.iso3 AS exp_iso, ci.iso3 AS imp_iso, re.region AS exp_region, ri.region AS imp_region
        FROM raw_fill f
        ANTI JOIN (SELECT DISTINCT exp_code, imp_code FROM raw) p ON p.exp_code = f.exp_code AND p.imp_code = f.imp_code
        LEFT JOIN fill_growth g ON g.ch = substr(f.hs6, 1, 2)
        LEFT JOIN cc ce ON ce.code = f.exp_code
        LEFT JOIN cc ci ON ci.code = f.imp_code
        LEFT JOIN reg re ON re.iso3 = ce.iso3
        LEFT JOIN reg ri ON ri.iso3 = ci.iso3
        WHERE re.region IS NOT NULL AND ri.region IS NOT NULL AND ce.iso3 <> ci.iso3
    """)
    rows, v, v0 = con.execute('SELECT COUNT(*), COALESCE(SUM(value), 0), COALESCE(SUM(value_year), 0) FROM fill_rows').fetchone()
    pairs = con.execute("""
        SELECT exp_region, imp_region, SUM(value), SUM(CASE WHEN substr(hs6, 1, 2) = '27' THEN value ELSE 0 END)
        FROM fill_rows WHERE exp_region <> imp_region GROUP BY 1, 2 ORDER BY 3 DESC
    """).fetchall()
    con.execute("""
        INSERT INTO mapped (hs6, value, qty, exp_iso, imp_iso, exp_region, imp_region)
        SELECT hs6, value, qty, exp_iso, imp_iso, exp_region, imp_region FROM fill_rows
    """)
    for t in ('raw_fill', 'fill_growth', 'fill_rows'):
        con.execute(f'DROP TABLE {t}')
    return dict(rows=rows, value_kusd=v, value_year_kusd=v0, pairs=pairs)


def drop_currency_lines(con, hs6=CURRENCY_HS6):
    """Beta v4 P22 (choice currency_lines; labelled departure, GTAP is silent): HS 490700 (banknotes, unused stamps, cheque forms,
    share and bond certificates) leaves the BACI table before the region sums. IMTS 2010 excludes currency in circulation and
    securities from merchandise trade; ARE to ARM was 1.45 bn for 13.7 t, cash shipments. Called before flows and intra are
    rebuilt (drop_flag_ships). Returns dict(rows, value_kusd, top: [(exp_iso, imp_iso, kUSD)])."""
    lines = ','.join(f"'{h}'" for h in hs6)
    rows, v = con.execute(f'SELECT COUNT(*), COALESCE(SUM(value), 0) FROM mapped WHERE hs6 IN ({lines})').fetchone()
    top = con.execute(f"""SELECT exp_iso, imp_iso, SUM(value) FROM mapped WHERE hs6 IN ({lines})
                         GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 15""").fetchall()
    con.execute(f'DELETE FROM mapped WHERE hs6 IN ({lines})')
    left = con.execute(f'SELECT COUNT(*) FROM mapped WHERE hs6 IN ({lines})').fetchone()[0]
    return dict(rows=rows, value_kusd=v, top=top, left=left)


def load_rx_shares(con, rx_dir, regions, extra=(), bel_csv=None, high=None, bel_nbb=False):
    """Beta v4 P26 tier 1: table rx_share(region, hs2, share) from UN Comtrade 2022 RX and X by HS2 to World
    (rx_dir: RX_<code>_HS2.json and X_<code>_HS2.json), share = RX / X clipped to [0, 1]. Reporter codes map to ISO3
    through BACI's country codes (table cc; the same Comtrade codes); a reporter enters only where it is a region of its own
    (regions: {iso3: region} of single-member regions), and not HKG, NLD, SGP (own rule) or the USA unless extra names it.
    BEL (extra) takes the NBB national-concept quasi-transit share file bel_csv (hs2, share). Returns the regions used and the
    reporters left out with a reason.

    high (beta v5 T1, reexport_high_share): every other reporter also gets rx_dom rows (BACI-side cap at Comtrade X - RX)
    for its chapters with RX / X >= high. bel_nbb (beta v5 T2, usa_bel_nbb): bel_csv holds NBB's own tables (hs2,
    national_eur, community_eur; exports, 2022) and the share is 1 - national / community, clipped to [0, 1]."""
    con.execute('DROP TABLE IF EXISTS rx_hs2')
    con.execute('CREATE TABLE rx_hs2(code INTEGER, flow VARCHAR, hs2 VARCHAR, value DOUBLE)')
    rows = []
    for name in sorted(os.listdir(rx_dir)):
        m = re.match(r'^(RX|X)_(\d+)_HS2\.json$', name)
        if not m:
            continue
        for d in json.load(open(os.path.join(rx_dir, name))).get('data', []):
            rows.append((int(m.group(2)), m.group(1), str(d['cmdCode']).zfill(2), float(d['primaryValue'] or 0.0)))
    con.executemany('INSERT INTO rx_hs2 VALUES (?, ?, ?, ?)', rows)
    codes = con.execute('SELECT DISTINCT r.code, c.iso3 FROM rx_hs2 r LEFT JOIN cc c ON c.code = r.code').fetchall()
    used, left = {}, []
    for code, iso in codes:
        reg = regions.get(iso)
        if reg is None:
            left.append((code, iso or '?', 'not a single-country region'))
        elif reg in RX_OWN_RULE:
            left.append((code, iso, 'own re-export rule'))
        elif reg in ('USA', 'BEL') and reg not in extra:
            left.append((code, iso, 'reexport_rx_usa_bel off'))
        else:
            used[code] = reg
    con.execute('DROP TABLE IF EXISTS rx_share')
    con.execute('CREATE TABLE rx_share(region VARCHAR, hs2 VARCHAR, share DOUBLE)')
    for code, reg in used.items():
        con.execute("""
            INSERT INTO rx_share
            SELECT ?, x.hs2, LEAST(GREATEST(COALESCE(r.value, 0) / x.value, 0), 1)
            FROM rx_hs2 x LEFT JOIN rx_hs2 r ON r.code = x.code AND r.hs2 = x.hs2 AND r.flow = 'RX'
            WHERE x.code = ? AND x.flow = 'X' AND x.value > 0
        """, [reg, code])
    # USA (extra): BACI's US rows already hold part of the US re-exports, so the removal in each HS2 is capped at BACI US
    # exports less Comtrade US domestic exports (X - RX), thousand USD (S16 2026-10-26; identified_rx)
    con.execute('DROP TABLE IF EXISTS rx_dom')
    con.execute('CREATE TABLE rx_dom(region VARCHAR, hs2 VARCHAR, dom DOUBLE)')
    for code, reg in used.items():
        if reg == 'USA':
            con.execute("""
                INSERT INTO rx_dom
                SELECT ?, x.hs2, GREATEST(x.value - COALESCE(r.value, 0), 0) / 1000.0
                FROM rx_hs2 x LEFT JOIN rx_hs2 r ON r.code = x.code AND r.hs2 = x.hs2 AND r.flow = 'RX'
                WHERE x.code = ? AND x.flow = 'X'
            """, [reg, code])
        elif high is not None:
            con.execute("""
                INSERT INTO rx_dom
                SELECT ?, x.hs2, GREATEST(x.value - COALESCE(r.value, 0), 0) / 1000.0
                FROM rx_hs2 x LEFT JOIN rx_hs2 r ON r.code = x.code AND r.hs2 = x.hs2 AND r.flow = 'RX'
                WHERE x.code = ? AND x.flow = 'X' AND x.value > 0 AND COALESCE(r.value, 0) / x.value >= ?
            """, [reg, code, float(high)])
    if 'BEL' in extra:
        if not (bel_csv and os.path.exists(bel_csv)):
            raise SystemExit(f'reexport_rx_usa_bel with BEL needs the share file {bel_csv}')
        for r in csv.DictReader(open(bel_csv)):
            if bel_nbb:
                nat, com = float(r['national_eur']), float(r['community_eur'])
                share = 1.0 - nat / com if com > 0 else 0.0
            else:
                share = float(r['share'])
            con.execute('INSERT INTO rx_share VALUES (?, ?, ?)', ['BEL', str(r['hs2']).zfill(2), min(max(share, 0.0), 1.0)])
        used[-56] = 'BEL'
    con.execute('DROP TABLE rx_hs2')
    return sorted(set(used.values())), sorted(left)


def identified_rx(region, high=None):
    """Beta v4 P26 tier 1: the region's exports times its Comtrade RX / X share of the HS2 chapter, energy (HS 27) left to S11,
    scaled down by sector so the sector's removal is at most its BACI exports above the prior's exports (table prior_x,
    thousand USD): what BACI already credits to the origin is not removed twice. A region in table rx_dom (the USA) is first
    capped by HS2 at its BACI exports less its Comtrade domestic exports (X - RX): only the re-exports BACI holds come out.

    high (beta v5 T1, choice reexport_high_share): an HS2 chapter whose RX / X is at least `high` is mostly re-exports in
    the national data, so the prior (whose exports include them) is no guard there. Such a chapter is capped by HS2 at
    BACI exports less Comtrade domestic exports (rx_dom rows for the chapter) and not at the prior; its removal uses up
    the sector's prior room first, and the other chapters of the sector share what room is left. None = beta v4."""
    if high is None:
        return f"""
        WITH base0 AS (
            SELECT f.importer AS dest, f.hs6, f.value, f.value * s.share AS ident0, h.sector, s.hs2
            FROM flows f
            JOIN hs h ON h.hs6 = f.hs6
            JOIN rx_share s ON s.region = '{region}' AND s.hs2 = substr(f.hs6, 1, 2)
            WHERE f.exporter = '{region}' AND f.value > 0 AND s.share > 0 AND substr(f.hs6, 1, 2) <> '27'
        ),
        h2 AS (
            SELECT substr(f.hs6, 1, 2) AS hs2, SUM(f.value) AS x2 FROM flows f
            WHERE f.exporter = '{region}' AND f.value > 0 GROUP BY 1
        ),
        i2 AS (SELECT hs2, SUM(ident0) AS it2 FROM base0 GROUP BY 1),
        base AS (
            SELECT b.dest, b.hs6, b.value, b.sector,
                   b.ident0 * CASE WHEN d.dom IS NULL THEN 1.0
                                   ELSE LEAST(1.0, GREATEST(h2.x2 - d.dom, 0) / i2.it2) END AS ident
            FROM base0 b JOIN h2 USING (hs2) JOIN i2 USING (hs2)
            LEFT JOIN rx_dom d ON d.region = '{region}' AND d.hs2 = b.hs2
        ),
        xb AS (
            SELECT h.sector, SUM(f.value) AS x FROM flows f JOIN hs h ON h.hs6 = f.hs6
            WHERE f.exporter = '{region}' AND f.value > 0 GROUP BY 1
        ),
        room AS (
            SELECT xb.sector, GREATEST(xb.x - COALESCE(p.x, 0), 0) AS room
            FROM xb LEFT JOIN prior_x p ON p.region = '{region}' AND p.sector = xb.sector
        ),
        tot AS (SELECT sector, SUM(ident) AS it FROM base GROUP BY 1)
        SELECT b.dest, b.hs6, b.value AS export_value, b.ident * LEAST(1.0, r.room / t.it) AS identified
        FROM base b JOIN tot t USING (sector) JOIN room r USING (sector)
        WHERE t.it > 0 AND r.room > 0
    """
    return f"""
        WITH base0 AS (
            SELECT f.importer AS dest, f.hs6, f.value, f.value * s.share AS ident0, h.sector, s.hs2,
                   s.share >= {float(high)!r} AS hi
            FROM flows f
            JOIN hs h ON h.hs6 = f.hs6
            JOIN rx_share s ON s.region = '{region}' AND s.hs2 = substr(f.hs6, 1, 2)
            WHERE f.exporter = '{region}' AND f.value > 0 AND s.share > 0 AND substr(f.hs6, 1, 2) <> '27'
        ),
        h2 AS (
            SELECT substr(f.hs6, 1, 2) AS hs2, SUM(f.value) AS x2 FROM flows f
            WHERE f.exporter = '{region}' AND f.value > 0 GROUP BY 1
        ),
        i2 AS (SELECT hs2, SUM(ident0) AS it2 FROM base0 GROUP BY 1),
        base AS (
            SELECT b.dest, b.hs6, b.value, b.sector, b.hi,
                   b.ident0 * CASE WHEN d.dom IS NULL THEN 1.0
                                   ELSE LEAST(1.0, GREATEST(h2.x2 - d.dom, 0) / i2.it2) END AS ident
            FROM base0 b JOIN h2 USING (hs2) JOIN i2 USING (hs2)
            LEFT JOIN rx_dom d ON d.region = '{region}' AND d.hs2 = b.hs2
        ),
        xb AS (
            SELECT h.sector, SUM(f.value) AS x FROM flows f JOIN hs h ON h.hs6 = f.hs6
            WHERE f.exporter = '{region}' AND f.value > 0 GROUP BY 1
        ),
        room AS (
            SELECT xb.sector, GREATEST(xb.x - COALESCE(p.x, 0), 0) AS room
            FROM xb LEFT JOIN prior_x p ON p.region = '{region}' AND p.sector = xb.sector
        ),
        tot AS (
            SELECT sector, COALESCE(SUM(ident) FILTER (WHERE NOT hi), 0) AS it,
                   COALESCE(SUM(ident) FILTER (WHERE hi), 0) AS ih
            FROM base GROUP BY 1
        )
        SELECT b.dest, b.hs6, b.value AS export_value,
               CASE WHEN b.hi THEN b.ident
                    ELSE b.ident * LEAST(1.0, GREATEST(COALESCE(r.room, 0) - t.ih, 0) / t.it) END AS identified
        FROM base b JOIN tot t USING (sector) LEFT JOIN room r USING (sector)
        WHERE b.ident > 0 AND (b.hi OR (t.it > 0 AND COALESCE(r.room, 0) - t.ih > 0))
    """


def identified_surplus(region):
    """Beta v5 T1 (choice reexport_import_surplus; Aguiar et al. 2025 p.12, GTAP 7 ch.9A p.9A-2): for a listed region with no
    Comtrade RX report (the Gulf non-reporters, config/s07/reexport_surplus_regions.csv), a sector whose BACI imports are at
    least its BACI exports and whose exports are above the prior's (S06) is a re-export sector: the exports above the prior,
    at most the imports, are re-exports. Energy (HS 27, S11) and precious metals (HS 71, a caveat) are left out. Spread over
    the sector's HS6 x destination cells by export value; origins by claim_import_share, as for tier 1."""
    return f"""
        WITH xs AS (
            SELECT f.importer AS dest, f.hs6, f.value, h.sector FROM flows f JOIN hs h ON h.hs6 = f.hs6
            WHERE f.exporter = '{region}' AND f.value > 0 AND substr(f.hs6, 1, 2) NOT IN ('27', '71')
        ),
        xsec AS (SELECT sector, SUM(value) AS x FROM xs GROUP BY 1),
        msec AS (
            SELECT h.sector, SUM(f.value) AS m FROM flows f JOIN hs h ON h.hs6 = f.hs6
            WHERE f.importer = '{region}' AND f.exporter <> '{region}' AND f.value > 0 AND substr(f.hs6, 1, 2) NOT IN ('27', '71')
            GROUP BY 1
        ),
        rx AS (
            SELECT x.sector, x.x, LEAST(GREATEST(x.x - COALESCE(p.x, 0), 0), m.m) AS r
            FROM xsec x JOIN msec m USING (sector)
            LEFT JOIN prior_x p ON p.region = '{region}' AND p.sector = x.sector
            WHERE m.m >= x.x AND x.x > 0
        )
        SELECT s.dest, s.hs6, s.value AS export_value, s.value * r.r / r.x AS identified
        FROM xs s JOIN rx r USING (sector)
        WHERE r.r > 0
    """


def identified_hk_dx(usd_hkd):
    """Beta v5 T1 (choice hkg_domestic_export_cap; Aguiar et al. 2025 p.12, GTAP 7 ch.9A §9.A.6): after the HKG hub step,
    HKG's BACI exports to a destination in an HS2 chapter above C&SD domestic exports to it (Trade-IDDS dx, HK$ thousand
    over HK$ per USD = thousand USD; table hk_share) are re-exports that BACI books to Hong Kong. Only cells with a
    Trade-IDDS row are touched. Spread over the cell's HS6 lines by value; origins by claim_hk."""
    return f"""
        WITH x AS (
            SELECT f.importer AS dest, substr(f.hs6, 1, 2) AS hs2, SUM(f.value) AS x2 FROM flows f
            WHERE f.exporter = 'HKG' AND f.value > 0 GROUP BY 1, 2
        ),
        ex AS (
            SELECT x.dest, x.hs2, x.x2, GREATEST(x.x2 - s.dx / {float(usd_hkd)!r}, 0) AS excess
            FROM x JOIN hk_share s ON s.dest = x.dest AND s.hs2 = x.hs2
        )
        SELECT f.importer AS dest, f.hs6, f.value AS export_value, f.value * e.excess / e.x2 AS identified
        FROM flows f JOIN ex e ON e.dest = f.importer AND e.hs2 = substr(f.hs6, 1, 2)
        WHERE f.exporter = 'HKG' AND f.value > 0 AND e.excess > 0
    """


def transit_cap(con, caps):
    """Beta v4 P18 (choice transit_import_cap; GTAP 7 ch.9A pp.9A-1 to 9A-3, choose the more reliable report): for each listed
    importer, its BACI imports outside the excluded HS prefixes (energy, which S11 rebuilds from volumes, and precious metals,
    a caveat) are scaled down to the national merchandise-imports total where they exceed it; both sides of each flow fall
    (the exporter's mirror report is the transit). caps: [(region, total USD million, [prefixes])], or (beta v5 B2, M1, M2)
    [(region, total, [prefixes], scope, cif_fob)]: the total is divided by cif_fob (CIF to the FOB basis of BACI), and with
    scope all_lines it caps all goods lines, the excluded lines' BACI value counting inside it (they are not scaled).
    Returns [(region, before kUSD, cap kUSD, factor, excluded kUSD)]; for all_lines, before and cap are the non-excluded
    lines' values."""
    out = []
    for row in caps:
        reg, total, prefixes = row[:3]
        scope, cif_fob = (row[3], float(row[4])) if len(row) > 3 else ('non_excluded', 1.0)
        excl = ' OR '.join(f"hs6 LIKE '{p}%'" for p in prefixes) or 'FALSE'
        before, ex = con.execute(f"""
            SELECT COALESCE(SUM(value) FILTER (WHERE NOT ({excl})), 0), COALESCE(SUM(value) FILTER (WHERE {excl}), 0)
            FROM flows WHERE importer = ? AND value > 0
        """, [reg]).fetchone()
        cap = total * 1000.0 / cif_fob
        if scope == 'all_lines':
            cap = max(cap - ex, 0.0)
        elif scope != 'non_excluded':
            raise SystemExit(f'transit_cap: {reg} scope {scope}')
        k = cap / before if before > cap else 1.0
        if k < 1.0:
            con.execute(f"""
                UPDATE flows SET value = value * {k!r}, qty = qty * {k!r}
                WHERE importer = ? AND value > 0 AND NOT ({excl})
            """, [reg])
        out.append((reg, before, cap, k, ex))
    return out


def read_transit_v5(path, regions):
    """config/s07/transit_import_caps_v5.csv -> [(region, total USD million, [prefixes], scope, cif_fob)]; stop on a blank
    attribution, an unknown region or scope, or a CIF/FOB ratio outside [1, 1.3)."""
    with open(path, newline='') as fh:
        rd = csv.DictReader(fh)
        if tuple(rd.fieldnames or ()) != TRANSIT_CAP_V5_COLUMNS:
            raise SystemExit(f'{path}: columns {rd.fieldnames} are not {TRANSIT_CAP_V5_COLUMNS}')
        rows = list(rd)
    out = []
    for r in rows:
        if (any(not r[c].strip() for c in TRANSIT_CAP_V5_COLUMNS if c != 'excluded_hs_prefixes') or r['region'] not in regions
                or r['cap_scope'] not in ('non_excluded', 'all_lines') or not 1.0 <= float(r['cif_fob']) < 1.3
                or not float(r['goods_imports_musd']) > 0):
            raise SystemExit(f'{path}: bad row {r}')
        out.append((r['region'], float(r['goods_imports_musd']), [x for x in r['excluded_hs_prefixes'].split(';') if x],
                    r['cap_scope'], float(r['cif_fob'])))
    if len({r[0] for r in out}) != len(out):
        raise SystemExit(f'{path}: a region is listed twice')
    return out


def load_floor_imports(con, floor_dir, rows):
    """Beta v5 B: table floor_m(region, partner, hs2, value) in thousand USD, FOB basis, from the importer's own Comtrade 2022
    imports by partner and HS2 (floor_dir/M_<code>/M_<code>_<hs2>.json; CIF / cif_fob). Partners map to regions through
    BACI's country codes (table cc; the same UN codes) and table reg; re-imports (partner in the importer's own region),
    World and partners with no region are left out and counted. The excluded HS2 chapters are left out. rows: [(region,
    code, cif_fob, [prefixes])]. Returns {region: dict(total, own, unmapped, kept)} in thousand USD."""
    con.execute('DROP TABLE IF EXISTS floor_m')
    con.execute('CREATE TABLE floor_m(region VARCHAR, partner VARCHAR, hs2 VARCHAR, value DOUBLE)')
    pmap = dict(con.execute('SELECT c.code, r.region FROM cc c JOIN reg r ON r.iso3 = c.iso3').fetchall())
    stats = {}
    for reg, code, cif_fob, prefixes in rows:
        tot_path = os.path.join(floor_dir, f'M_{code}', f'M_{code}_TOTAL.json')
        total = sum(float(d['primaryValue'] or 0) for d in json.load(open(tot_path))['data'] if int(d['partnerCode']) == 0)
        acc = defaultdict(float)
        own = unmapped = chapters = 0.0
        for ch in range(1, 100):
            hs2 = f'{ch:02d}'
            path = os.path.join(floor_dir, f'M_{code}', f'M_{code}_{hs2}.json')
            if not os.path.exists(path):
                continue
            for d in json.load(open(path))['data']:
                if str(d['cmdCode']).zfill(2) != hs2 or d['flowCode'] != 'M' or int(d['reporterCode']) != int(code):
                    raise SystemExit(f'{path}: unexpected row {d}')
                pc = int(d['partnerCode'])
                v = float(d['primaryValue'] or 0) / cif_fob / 1000.0
                if pc == 0:
                    chapters += v
                    continue
                if hs2 in prefixes:
                    continue
                pr = pmap.get(pc)
                if pr is None:
                    unmapped += v
                elif pr == reg:
                    own += v
                else:
                    acc[(pr, hs2)] += v
        con.executemany('INSERT INTO floor_m VALUES (?, ?, ?, ?)', [(reg, p, h, v) for (p, h), v in sorted(acc.items())])
        stats[reg] = dict(total=total / cif_fob / 1000.0, chapters=chapters, own=own, unmapped=unmapped, kept=sum(acc.values()))
    return stats


def importer_floor(con, rows, excluded, partner_cap=None):
    """Beta v5 B (choice importer_floor; GTAP 7 ch.9A pp.9A-1 to 9A-3, choose the more reliable report; the mirror of the P18
    transit cap): for each listed importer, its BACI imports from other regions outside the excluded prefixes are raised to
    its own customs total of those lines (table floor_m, FOB basis) where they fall short. The shortfall goes to the partner x
    HS2 cells where the importer reports more than BACI holds, each cell's gap scaled by one factor so the total lands on the
    customs figure; inside a cell, by the cell's HS6 values, else by the importer's HS6 imports of that chapter, else by the
    partner's HS6 exports of the chapter (new rows, no tonnes). The exporter's mirror figure rises with it. rows: [region];
    excluded: {region: [prefixes]}. Returns [dict(region, before, target, added, factor, unplaced, capped, capped_by)] in
    thousand USD.

    partner_cap (choice importer_floor_partner_cap): {partner region: own customs total exports, thousand USD}. A listed
    partner's top-up is scaled down so its goods exports (all lines, to every other region, at this step) stay at most that
    total; the value cut (capped) is not moved to other partners, so the importer lands below its target by it."""
    out = []
    for reg in rows:
        prefixes = excluded[reg]
        excl = ' OR '.join(f"f.hs6 LIKE '{p}%'" for p in prefixes) or 'FALSE'
        before = con.execute(f"""
            SELECT COALESCE(SUM(f.value), 0) FROM flows f
            WHERE f.importer = ? AND f.exporter <> ? AND f.value > 0 AND NOT ({excl})
        """, [reg, reg]).fetchone()[0]
        target = con.execute('SELECT COALESCE(SUM(value), 0) FROM floor_m WHERE region = ?', [reg]).fetchone()[0]
        need = target - before
        rec = dict(region=reg, before=before, target=target, added=0.0, factor=0.0, unplaced=0.0, capped=0.0, capped_by=[])
        if need <= 0:
            out.append(rec)
            continue
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE fl_b AS
            SELECT f.exporter AS partner, substr(f.hs6, 1, 2) AS hs2, SUM(f.value) AS v FROM flows f
            WHERE f.importer = '{reg}' AND f.exporter <> '{reg}' AND f.value > 0 AND NOT ({excl}) GROUP BY 1, 2
        """)
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE fl_gap AS
            SELECT m.partner, m.hs2, m.value - COALESCE(b.v, 0) AS gap, COALESCE(b.v, 0) AS baci
            FROM floor_m m LEFT JOIN fl_b b USING (partner, hs2)
            WHERE m.region = '{reg}' AND m.value > COALESCE(b.v, 0)
        """)
        gsum = con.execute('SELECT COALESCE(SUM(gap), 0) FROM fl_gap').fetchone()[0]
        fct = min(1.0, need / gsum) if gsum > 0 else 0.0
        # HS6 weights per (partner, hs2): the cell's own lines, else the importer's lines of the chapter, else the partner's
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE fl_w AS
            WITH own AS (
                SELECT g.partner, g.hs2, f.hs6, f.value AS w FROM fl_gap g
                JOIN flows f ON f.exporter = g.partner AND f.importer = '{reg}' AND substr(f.hs6, 1, 2) = g.hs2 AND f.value > 0
                WHERE g.baci > 0
            ),
            imp AS (
                SELECT g.partner, g.hs2, f.hs6, SUM(f.value) AS w FROM fl_gap g
                JOIN flows f ON f.importer = '{reg}' AND f.exporter <> '{reg}' AND substr(f.hs6, 1, 2) = g.hs2 AND f.value > 0
                WHERE g.baci <= 0 GROUP BY 1, 2, 3
            ),
            ex AS (
                SELECT g.partner, g.hs2, f.hs6, SUM(f.value) AS w FROM fl_gap g
                JOIN flows f ON f.exporter = g.partner AND substr(f.hs6, 1, 2) = g.hs2 AND f.value > 0
                WHERE g.baci <= 0 AND NOT EXISTS (SELECT 1 FROM imp i WHERE i.partner = g.partner AND i.hs2 = g.hs2)
                GROUP BY 1, 2, 3
            ),
            w AS (SELECT * FROM own UNION ALL SELECT * FROM imp UNION ALL SELECT * FROM ex)
            SELECT w.partner, w.hs2, w.hs6, w.w / SUM(w.w) OVER (PARTITION BY w.partner, w.hs2) AS share
            FROM w
        """)
        con.execute('CREATE OR REPLACE TEMP TABLE fl_cap(partner VARCHAR, scale DOUBLE)')
        capped, capped_by = 0.0, []
        if partner_cap:
            adds = con.execute('SELECT partner, SUM(gap) FROM fl_gap GROUP BY 1').fetchall()
            for partner, gap in adds:
                cap = partner_cap.get(partner)
                add = gap * fct
                if cap is None or add <= 0:
                    continue
                x_now = con.execute('SELECT COALESCE(SUM(value), 0) FROM flows WHERE exporter = ? AND importer <> ? AND value > 0',
                                    [partner, partner]).fetchone()[0]
                room = max(cap - x_now, 0.0)
                if room < add:
                    con.execute('INSERT INTO fl_cap VALUES (?, ?)', [partner, room / add])
                    capped += add - room
                    capped_by.append((partner, x_now, cap, add, room))
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE fl_add AS
            SELECT w.partner, w.hs6, g.gap * {fct!r} * w.share * COALESCE(c.scale, 1.0) AS add
            FROM fl_w w JOIN fl_gap g USING (partner, hs2) LEFT JOIN fl_cap c USING (partner)
        """)
        added = con.execute('SELECT COALESCE(SUM(add), 0) FROM fl_add').fetchone()[0]
        con.execute(f"""
            UPDATE flows SET value = flows.value + a.add,
                             qty = CASE WHEN flows.value > 0 THEN flows.qty * (flows.value + a.add) / flows.value ELSE flows.qty END
            FROM fl_add a WHERE flows.exporter = a.partner AND flows.importer = '{reg}' AND flows.hs6 = a.hs6
        """)
        con.execute(f"""
            INSERT INTO flows (exporter, importer, hs6, value, qty, qty_ok)
            SELECT a.partner, '{reg}', a.hs6, a.add, NULL, FALSE FROM fl_add a
            WHERE NOT EXISTS (SELECT 1 FROM flows f WHERE f.exporter = a.partner AND f.importer = '{reg}' AND f.hs6 = a.hs6)
        """)
        # with partner caps: each partner that received a top-up, with its goods exports after it and its cap (S07-H27)
        topped = []
        if partner_cap:
            for partner, add in con.execute('SELECT partner, SUM(add) FROM fl_add GROUP BY 1 HAVING SUM(add) > 0').fetchall():
                if partner in partner_cap:
                    x_after = con.execute('SELECT COALESCE(SUM(value), 0) FROM flows WHERE exporter = ? AND importer <> ? AND value > 0',
                                          [partner, partner]).fetchone()[0]
                    topped.append((partner, x_after, partner_cap[partner], add))
        for t in ('fl_b', 'fl_gap', 'fl_w', 'fl_add', 'fl_cap'):
            con.execute(f'DROP TABLE {t}')
        rec.update(added=added, factor=fct, unplaced=gsum * fct - capped - added, capped=capped, capped_by=capped_by, topped=topped)
        out.append(rec)
    return out


def load_partner_caps(con, path, composite_regions):
    """Beta v5 B follow-up (choice importer_floor_partner_cap): {region: total exports, thousand USD} from UN Comtrade 2022
    total exports to World as each reporter records them (FOB; path: comtrade_X_TOTAL_2022.json). Reporter codes map to
    regions through BACI's country codes (table cc; 490 is S19, TWN) and table reg; composite regions are left out, since
    one member's total is not the region's. Returns (caps, left) where left lists the unmapped or composite reporters."""
    pmap = dict(con.execute('SELECT c.code, r.region FROM cc c JOIN reg r ON r.iso3 = c.iso3').fetchall())
    caps, left = {}, []
    for d in json.load(open(path))['data']:
        if str(d['cmdCode']) != 'TOTAL' or d['flowCode'] != 'X' or int(d['partnerCode']) != 0:
            raise SystemExit(f'{path}: unexpected row {d}')
        code = int(d['reporterCode'])
        reg = pmap.get(code)
        if reg is None or reg in composite_regions:
            left.append((code, reg or '?'))
            continue
        if reg in caps:
            raise SystemExit(f'{path}: two reporters map to {reg}')
        caps[reg] = float(d['primaryValue'] or 0) / 1000.0
    return caps, left


def read_floor_rows(path, regions):
    """config/s07/importer_floors.csv -> [(region, Comtrade code, cif_fob, [prefixes])]; stop on a blank attribution, an
    unknown region or a CIF/FOB ratio outside [1, 1.3)."""
    with open(path, newline='') as fh:
        rd = csv.DictReader(fh)
        if tuple(rd.fieldnames or ()) != IMPORTER_FLOOR_COLUMNS:
            raise SystemExit(f'{path}: columns {rd.fieldnames} are not {IMPORTER_FLOOR_COLUMNS}')
        rows = list(rd)
    out = []
    for r in rows:
        if (any(not r[c].strip() for c in IMPORTER_FLOOR_COLUMNS) or r['region'] not in regions
                or not 1.0 <= float(r['cif_fob']) < 1.3 or not r['reporter_code'].isdigit()
                or any(len(x) != 2 for x in r['excluded_hs_prefixes'].split(';') if x)):
            raise SystemExit(f'{path}: bad row {r}')    # the Comtrade side is by HS2, so exclusions are whole chapters
        out.append((r['region'], int(r['reporter_code']), float(r['cif_fob']), [x for x in r['excluded_hs_prefixes'].split(';') if x]))
    return out


def gold_reexport(con, rows, usd_per_kg):
    """Beta v4 P39 (choice gold_reexport; labelled departure, in the style of P26): for each listed region, its BACI exports on
    the listed HS prefix above its recorded imports on that prefix plus its own mine output (kg x usd_per_kg) are taken as
    re-exports of unrecorded dore. They leave the region's exports to every destination but the origin in one proportion and
    go to the same destination and HS line from the origin (value and tonnes). The region's imports are not changed (the
    dore was never recorded). rows: [(region, prefix, mine kg, origin)]. Returns [dict(region, origin, exports, imports,
    mine, moved, factor)] in thousand USD."""
    out = []
    for reg, prefix, kg, origin in rows:
        like = f"hs6 LIKE '{prefix}%'"
        x, xo, m = con.execute(f"""
            SELECT COALESCE(SUM(value) FILTER (WHERE exporter = ?), 0),
                   COALESCE(SUM(value) FILTER (WHERE exporter = ? AND importer = ?), 0),
                   COALESCE(SUM(value) FILTER (WHERE importer = ?), 0)
            FROM flows WHERE {like} AND value > 0
        """, [reg, reg, origin, reg]).fetchone()
        mine = float(kg) * float(usd_per_kg) / 1000.0
        base = x - xo                                   # exports that can move (not those to the origin itself)
        moved = min(max(x - m - mine, 0.0), base)
        k = (base - moved) / base if base > 0 else 1.0
        if moved > 0:
            con.execute(f"""
                CREATE OR REPLACE TEMP TABLE gold_mv AS
                SELECT importer, hs6, value * {1.0 - k!r} AS v, COALESCE(qty, 0) * {1.0 - k!r} AS q
                FROM flows WHERE exporter = ? AND importer <> ? AND {like} AND value > 0
            """, [reg, origin])
            con.execute(f"UPDATE flows SET value = value * {k!r}, qty = qty * {k!r} WHERE exporter = ? AND importer <> ? AND {like} AND value > 0",
                        [reg, origin])
            con.execute("""
                UPDATE flows SET value = flows.value + g.v, qty = COALESCE(flows.qty, 0) + g.q
                FROM gold_mv g WHERE flows.exporter = ? AND flows.importer = g.importer AND flows.hs6 = g.hs6
            """, [origin])
            con.execute("""
                INSERT INTO flows (exporter, importer, hs6, value, qty, qty_ok)
                SELECT ?, g.importer, g.hs6, g.v, g.q, TRUE FROM gold_mv g
                WHERE NOT EXISTS (SELECT 1 FROM flows f WHERE f.exporter = ? AND f.importer = g.importer AND f.hs6 = g.hs6)
            """, [origin, origin])
            con.execute('DROP TABLE gold_mv')
        out.append(dict(region=reg, origin=origin, exports=x, imports=m, mine=mine, moved=moved, factor=k))
    return out


def metal_reexport(con, rows):
    """Beta v5 G (choice gold_reexport = METAL_RX; labelled departure: our application of GTAP 7 ch.9A pp.9A-1 to 9A-3, the
    more reliable report, P39 generalised). For each row, the region's BACI exports on the HS prefix are capped at
    ceiling = max(own customs exports, mine output + recorded imports), where own customs is the exporter's own Comtrade
    2022 export figure (0 where it does not report) and mine output is kg x the row's price (USD per kg). The excess leaves
    the region's exports to every destination but the origin in one proportion (value and tonnes) and, for a listed origin,
    goes to the same destination and HS line from the origin (as P39); with origin `drop` it is removed, so the importers'
    imports fall too (gold that the exporter's customs and national accounts never record). Rows run in file order.
    rows: [(region, prefix, mine kg, USD per kg, own customs kUSD, origin)]. Returns [dict(region, origin, prefix,
    exports, imports, mine, own, ceiling, moved, factor, after)] in thousand USD."""
    out = []
    for reg, prefix, kg, usd_kg, own, origin in rows:
        like = f"hs6 LIKE '{prefix}%'"
        keep_dest = origin if origin != 'drop' else ''
        x, xo, m = con.execute(f"""
            SELECT COALESCE(SUM(value) FILTER (WHERE exporter = ?), 0),
                   COALESCE(SUM(value) FILTER (WHERE exporter = ? AND importer = ?), 0),
                   COALESCE(SUM(value) FILTER (WHERE importer = ?), 0)
            FROM flows WHERE {like} AND value > 0
        """, [reg, reg, keep_dest, reg]).fetchone()
        mine = float(kg) * float(usd_kg) / 1000.0
        ceiling = max(float(own), mine + m)
        base = x - xo
        moved = min(max(x - ceiling, 0.0), base)
        k = (base - moved) / base if base > 0 else 1.0
        if moved > 0:
            if origin != 'drop':
                con.execute(f"""
                    CREATE OR REPLACE TEMP TABLE metal_mv AS
                    SELECT importer, hs6, value * {1.0 - k!r} AS v, COALESCE(qty, 0) * {1.0 - k!r} AS q
                    FROM flows WHERE exporter = ? AND importer <> ? AND {like} AND value > 0
                """, [reg, origin])
            con.execute(f"UPDATE flows SET value = value * {k!r}, qty = qty * {k!r} WHERE exporter = ? AND importer <> ? AND {like} AND value > 0",
                        [reg, keep_dest])
            if origin != 'drop':
                con.execute("""
                    UPDATE flows SET value = flows.value + g.v, qty = COALESCE(flows.qty, 0) + g.q
                    FROM metal_mv g WHERE flows.exporter = ? AND flows.importer = g.importer AND flows.hs6 = g.hs6
                """, [origin])
                con.execute("""
                    INSERT INTO flows (exporter, importer, hs6, value, qty, qty_ok)
                    SELECT ?, g.importer, g.hs6, g.v, g.q, TRUE FROM metal_mv g
                    WHERE NOT EXISTS (SELECT 1 FROM flows f WHERE f.exporter = ? AND f.importer = g.importer AND f.hs6 = g.hs6)
                """, [origin, origin])
                con.execute('DROP TABLE metal_mv')
        after = con.execute(f'SELECT COALESCE(SUM(value), 0) FROM flows WHERE {like} AND value > 0 AND exporter = ?', [reg]).fetchone()[0]
        out.append(dict(region=reg, origin=origin, prefix=prefix, exports=x, imports=m, mine=mine, own=float(own), ceiling=ceiling,
                        moved=moved, factor=k, after=after))
    return out


def metal_own_customs(path, codes):
    """Comtrade 2022 exports to World by reporter (comtrade_X_<prefix>_2022.json) -> {iso3: kUSD}; codes: {UN code: iso3}
    (BACI's country codes)."""
    out = {}
    for d in json.load(open(path))['data']:
        if d.get('flowCode') != 'X' or int(d.get('partnerCode', -1)) != 0:
            raise SystemExit(f'{path}: unexpected row {d}')
        iso = codes.get(int(d['reporterCode']))
        if iso:
            out[iso] = out.get(iso, 0.0) + float(d['primaryValue'] or 0) / 1000.0
    return out


def read_metal_rows(path, regions):
    """config/s07/metal_reexport_2022.csv -> [(region, prefix, mine kg, price key, own_customs key, origin)]; stop on a blank
    source or attribution, an unknown region or origin, a price other than gold or none (none needs mine 0), or an
    own_customs other than comtrade or none."""
    with open(path, newline='') as fh:
        rd = csv.DictReader(fh)
        if tuple(rd.fieldnames or ()) != METAL_RX_COLUMNS:
            raise SystemExit(f'{path}: columns {rd.fieldnames} are not {METAL_RX_COLUMNS}')
        rows = list(rd)
    out = []
    for r in rows:
        if (not all(r[c].strip() for c in ('source', 'decided_by', 'decided_at', 'hs_prefix', 'basis')) or r['region'] not in regions
                or (r['origin'] != 'drop' and (r['origin'] not in regions or r['origin'] == r['region']))
                or not float(r['mine_output_kg']) >= 0 or r['price'] not in ('gold', 'none')
                or (r['price'] == 'none' and float(r['mine_output_kg']) != 0) or r['own_customs'] not in ('comtrade', 'none')
                or not r['hs_prefix'].isdigit()):
            raise SystemExit(f'{path}: bad row {r}')
        out.append((r['region'], r['hs_prefix'], float(r['mine_output_kg']), r['price'], r['own_customs'], r['origin']))
    if len({(r[0], r[1]) for r in out}) != len(out):
        raise SystemExit(f'{path}: a region and prefix is listed twice')
    return out


def gold_price_2022(path):
    """World Bank Pink Sheet (CMO annual, nominal) 2022 gold price, USD per troy ounce."""
    import pandas as pd
    d = pd.read_excel(path, sheet_name='Annual Prices (Nominal)', header=None)
    col = [j for j in range(d.shape[1]) if 'Gold' in str(d.iloc[6, j])]
    row = [i for i in range(d.shape[0]) if str(d.iloc[i, 0]).strip() == '2022']
    if len(col) != 1 or len(row) != 1:
        raise SystemExit(f'{path}: no single 2022 gold price')
    return float(d.iloc[row[0], col[0]])


def read_gold_rows(path, regions):
    """config/s07/gold_reexport_2022.csv -> [(region, prefix, mine kg, origin)]; stop on a blank source or attribution or an
    unknown region."""
    with open(path, newline='') as fh:
        rd = csv.DictReader(fh)
        if tuple(rd.fieldnames or ()) != GOLD_RX_COLUMNS:
            raise SystemExit(f'{path}: columns {rd.fieldnames} are not {GOLD_RX_COLUMNS}')
        rows = list(rd)
    out = []
    for r in rows:
        if (not all(r[c].strip() for c in ('source', 'decided_by', 'decided_at', 'hs_prefix')) or r['region'] not in regions
                or r['origin'] not in regions or r['origin'] == r['region'] or not float(r['mine_output_kg']) >= 0):
            raise SystemExit(f'{path}: bad row {r}')
        out.append((r['region'], r['hs_prefix'], float(r['mine_output_kg']), r['origin']))
    return out


def drop_flag_ships(con, flag_isos):
    """Vessel trade (HS 8901-8906) to or from an open registry is a change of flag, not a purchase by that economy.

    GTAP 12 ch.10B treatment of ships (Fable QA D-01 / C-06): the rows leave the BACI table before
    the region sums, and flows and intra are rebuilt from what is left (same SQL as baci_reexports.load_baci).
    """
    con.execute('CREATE TABLE flagreg(iso3 VARCHAR)')
    con.executemany('INSERT INTO flagreg VALUES (?)', [(c,) for c in sorted(flag_isos)])
    hs = ','.join(f"'{h}'" for h in SHIP_HS4)
    cond = (f"substr(hs6, 1, 4) IN ({hs}) AND (exp_iso IN (SELECT iso3 FROM flagreg) "
            f"OR imp_iso IN (SELECT iso3 FROM flagreg))")
    value, rows = con.execute(f'SELECT COALESCE(SUM(value), 0), COUNT(*) FROM mapped WHERE {cond}').fetchone()
    by_iso = con.execute(f"""
        SELECT iso, SUM(v) FROM (
            SELECT imp_iso AS iso, value AS v FROM mapped WHERE {cond} AND imp_iso IN (SELECT iso3 FROM flagreg)
            UNION ALL
            SELECT exp_iso AS iso, value AS v FROM mapped WHERE {cond} AND exp_iso IN (SELECT iso3 FROM flagreg)
              AND imp_iso NOT IN (SELECT iso3 FROM flagreg)
        ) GROUP BY 1 ORDER BY 2 DESC
    """).fetchall()
    con.execute(f'DELETE FROM mapped WHERE {cond}')
    con.execute('DROP TABLE flows')
    con.execute('DROP TABLE intra')
    con.execute("""
        CREATE TABLE flows AS
        SELECT exp_region AS exporter, imp_region AS importer, hs6,
               SUM(value) AS value, SUM(qty) AS qty, TRUE AS qty_ok
        FROM mapped
        WHERE exp_region IS NOT NULL AND imp_region IS NOT NULL
          AND exp_region <> imp_region
        GROUP BY 1, 2, 3
    """)
    con.execute("""
        CREATE TABLE intra AS
        SELECT exp_region AS region, hs6, SUM(value) AS value, SUM(qty) AS qty
        FROM mapped
        WHERE exp_region IS NOT NULL AND imp_region IS NOT NULL
          AND exp_region = imp_region
        GROUP BY 1, 2
    """)
    left = con.execute(f'SELECT COUNT(*) FROM mapped WHERE {cond}').fetchone()[0]
    return dict(value=value, rows=rows, by_iso=by_iso, left=left)


def frame_records(df, cols):
    if df is None or len(df) == 0:
        return
    for row in df.itertuples(index=False):
        yield tuple(getattr(row, c) for c in cols)



def norm_name(text):
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    text = text.upper().replace('&', ' AND ')
    return re.sub(r'[^A-Z0-9]+', ' ', text).strip()


def load_census_controls(path):
    rows = list(csv.DictReader(open(path)))
    by_item = {}
    for rec in rows:
        for col in ('item', 'value', 'decided_by', 'decided_at', 'basis'):
            if not rec.get(col, '').strip():
                raise SystemExit('census_controls.csv row missing ' + col)
        by_item[rec['item'].strip()] = rec
    if set(by_item) != set(CENSUS_CONTROL_ITEMS):
        raise SystemExit('census_controls.csv items must be ' + ' '.join(CENSUS_CONTROL_ITEMS))
    totals = {
        ('PR', 'exports'): float(by_item['PR_exports']['value']),
        ('PR', 'imports'): float(by_item['PR_imports']['value']),
        ('VI', 'exports'): float(by_item['VI_exports']['value']),
        ('VI', 'imports'): float(by_item['VI_imports']['value']),
    }
    excluded = tuple(by_item['excluded_sectors']['value'].split())
    limit = float(by_item['excluded_limit']['value'])
    return totals, excluded, limit


def load_name_bridge(alias_path, override_path, map_rows, region_rows):
    aliases = {}
    for rec in csv.DictReader(open(alias_path)):
        for col in ('census_name', 'iso3', 'decided_by', 'decided_at', 'basis'):
            if not rec.get(col, '').strip():
                raise SystemExit('census_schedule_c_aliases.csv row missing ' + col)
        aliases[norm_name(rec['census_name'])] = rec['iso3'].strip()
    overrides = {}
    for rec in csv.DictReader(open(override_path)):
        for col in ('iso3', 'partner', 'decided_by', 'decided_at', 'basis'):
            if not rec.get(col, '').strip():
                raise SystemExit('census_partner_overrides.csv row missing ' + col)
        overrides[rec['iso3'].strip()] = rec['partner'].strip()
    by_code = {rec['code']: rec for rec in map_rows if rec['code']}
    by_norm = {}
    for rec in map_rows:
        if rec['code'] and rec['name']:
            by_norm.setdefault(norm_name(rec['name']), rec['code'])
    icio = {rec['region'] for rec in region_rows if rec['icio_measured'] == 'yes'}
    return aliases, overrides, by_code, by_norm, icio


def census_partner(name, aliases, overrides, by_norm, by_code, icio):
    iso = aliases.get(norm_name(name)) or by_norm.get(norm_name(name))
    if not iso:
        return None, None
    iso = overrides.get(iso, iso)
    if iso == 'ISL' or iso in icio:
        return iso, 'yes'
    rec = by_code.get(iso)
    if rec is None or not rec.get('region'):
        return None, None
    region = rec['region']
    flag = 'yes' if region in icio or region == 'ISL' else 'no'
    return region, flag


def rederive_census(json_paths, concord_rows, aliases, overrides, by_norm, by_code, icio):
    """Partner x sector USD million from the raw statehs JSON.

    Country rows are Schedule C codes 1000-7999. The dash rows are the
    per-HS total and are checked against those country rows. Group rows
    are dropped. HS2022 uses the S01 concordance, share-weighted. A code
    with no sector, including chapter 98, is unmapped.
    """
    concord = {}
    for rec in concord_rows:
        sector = rec['sector'].strip()
        share = rec['share'].strip()
        if not sector or not share:
            continue
        concord.setdefault(rec['hs22'].strip().zfill(6), []).append((sector, float(share)))
    derived = defaultdict(float)
    flags = {}
    dash = defaultdict(int)
    country = defaultdict(int)
    unmapped = []
    for state, direction, path in json_paths:
        data = json.load(open(path))
        header = data[0]
        code_i = header.index('CTY_CODE')
        name_i = header.index('CTY_NAME')
        comm = 'E_COMMODITY' if direction == 'exports' else 'I_COMMODITY'
        valn = 'ALL_VAL_YR' if direction == 'exports' else 'GEN_VAL_YR'
        ci, vi = header.index(comm), header.index(valn)
        for row in data[1:]:
            code = row[code_i]
            val = int(row[vi] or 0)
            if code == '-':
                dash[(state, direction)] += val
                continue
            try:
                ncode = int(code)
            except ValueError:
                continue
            if not 1000 <= ncode <= 7999:
                continue
            country[(state, direction)] += val
            partner, flag = census_partner(row[name_i], aliases, overrides, by_norm, by_code, icio)
            if partner is None:
                unmapped.append(row[name_i])
                continue
            parts = concord.get(str(row[ci]).zfill(6)) or [('unmapped', 1.0)]
            for sector, share in parts:
                derived[(state, direction, partner, sector)] += val * share / 1e6
            flags[(state, direction, partner)] = flag
    return dict(derived=derived, flags=flags, dash=dict(dash), country=dict(country), unmapped=sorted(set(unmapped)))



def bn(x):
    return float(x) / 1000.0


def old_vxsb_path(S):
    """The previous Decision-1 file, for the report. Not an input of the new values."""
    canon = ROOT + '/stages/S07_trade'
    live = canon + '/output/vxsb_goods_s07.csv.gz'
    if os.path.abspath(S.out) != os.path.abspath(canon + '/output'):
        return live if os.path.exists(live) else ''
    arch = canon + '/archive'
    found = []
    if os.path.isdir(arch):
        for name in sorted(os.listdir(arch)):
            p = os.path.join(arch, name, 'output', 'vxsb_goods_s07.csv.gz')
            if os.path.exists(p):
                found.append(p)
    return found[-1] if found else ''


def sum_vxsb(path):
    if not path or not os.path.exists(path):
        return None
    total = 0.0
    with gzip.open(path, 'rt', newline='') as fh:
        for row in csv.DictReader(fh):
            total += float(row['vxsb_musd'])
    return total


def secret_hits(paths):
    """Pattern scan, plus the env value when CENSUS_API_KEY is set. The value is never printed."""
    pat = re.compile(br'(?i)(?:api[_-]?key|key=)[A-Za-z0-9]{20,}')
    env_key = os.environ.get('CENSUS_API_KEY', '')
    env_blob = env_key.encode('utf-8') if env_key else b''
    env_set = bool(env_blob)
    skip_ext = ('.zip', '.xlsx', '.xls', '.gz', '.pdf', '.rar', '.jls', '.png', '.jpg')
    hits = []
    for root in paths:
        if not os.path.exists(root):
            continue
        files = [root] if os.path.isfile(root) else []
        if not files:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if d != 'archive']
                files.extend(os.path.join(dirpath, fn) for fn in filenames)
        for path in files:
            if path.endswith(skip_ext):
                continue
            try:
                if os.path.getsize(path) > 8_000_000:
                    continue
                blob = open(path, 'rb').read()
            except OSError:
                continue
            matched = pat.search(blob) is not None
            if env_set and env_blob in blob:
                matched = True
            if matched:
                hits.append(os.path.basename(path))
    return hits, env_set


def main():
    S = Stage('S07', 'trade')
    I = S.inp
    S01 = S.upstream(STAGES + '/S01_sets_registry')
    S02 = S.upstream(STAGES + '/S02_macro')
    S04 = S.upstream(STAGES + '/S04_disagg_gov')
    S06 = S.upstream(STAGES + '/S06_apt')
    S09 = STAGES + '/S09_services'

    paths = {
        'baci_zip': I(DATA + '/baci/BACI_HS17_V202601.zip', 'BACI HS17 V202601 (Etalab 2.0); year file 2022 is read from the zip'),
        'tx_hs2.json': I(DATA + '/hk_trade_idds/tx_hs2.json', 'HK Trade-IDDS 2022 total exports by consignment and HKHS2'),
        'rx_hs2.json': I(DATA + '/hk_trade_idds/rx_hs2.json', 'HK Trade-IDDS 2022 re-exports by consignment and HKHS2'),
        'rx_od.json': I(DATA + '/hk_trade_idds/rx_od.json', 'HK Trade-IDDS 2022 re-exports by origin and consignment'),
        'dx_hs2.json': I(DATA + '/hk_trade_idds/dx_hs2.json', 'HK Trade-IDDS 2022 domestic exports by consignment and HKHS2'),
        'totals.json': I(DATA + '/hk_trade_idds/totals.json', 'HK Trade-IDDS 2022 published totals'),
        'api_txt': I(DATA + '/hk_trade_idds/API_eng.txt', 'HK Trade-IDDS API annex, country codes'),
        'M451521.json': I(DATA + '/singstat/M451521.json', 'SingStat M451521 merchandise exports by market, 2022'),
        'M451501.json': I(DATA + '/singstat/M451501.json', 'SingStat M451501 domestic exports by market, 2022'),
        'M451001.json': I(DATA + '/singstat/M451001.json', 'SingStat M451001 commodity sections, diagnostic only'),
        'typed_2022.json': I(DATA + '/cbs_85429ned/typed_2022.json', 'CBS 85429NED typed data, 2022JJ00'),
        'landen.json': I(DATA + '/cbs_85429ned/landen.json', 'CBS 85429NED country dimension'),
        'sitc.json': I(DATA + '/cbs_85429ned/sitc.json', 'CBS 85429NED SITC dimension'),
        'xlsx': I(DATA + '/unsd_hs_correlation/HS2017toSITC4ConversionAndCorrelationTables.xlsx', 'UNSD HS2017 to SITC Rev.4 correlation'),
        'countries': I(DATA + '/restcountries/countries.json', 'Country names for the SingStat partner match'),
        'm_co_hs2.json': I(DATA + '/hk_trade_idds/m_co_hs2.json', 'HK Trade-IDDS 2022 imports by origin and HKHS2'),
        'M451001_imports.json': I(DATA + '/singstat/M451001_imports.json', 'SingStat M451001 imports by commodity section, 2022'),
    }
    I(DATA + '/hk_csd_digest/B10100032023AN23B0100.pdf', 'C&SD Hong Kong Annual Digest of Statistics 2023 (Table 3.1 retained imports)')
    retained_path = I(BUILD + '/config/s07/retained_imports.csv', 'S07 retained-import totals, cited')
    flags_path = I(BUILD + '/config/s07/flag_registries.csv', 'S07 open ship registries (HS 8901-8906 dropped)')
    choices_path = I(BUILD + '/config/s07/trade_choices.csv', 'S07 choice rows')
    controls_path = I(BUILD + '/config/s07/census_controls.csv', 'Census API totals, the exclusion list and the 650 USD million cap')
    alias_path = I(BUILD + '/config/s07/census_schedule_c_aliases.csv', 'Census Schedule C display names to ISO3')
    override_path = I(BUILD + '/config/s07/census_partner_overrides.csv', 'Census partners folded into FRA or ITA before the S01 lookup')
    census_path = I(
        DATA + '/census_statehs_2022/census_pr_vi_2022_by_partner_sector.csv',
        'US Census CY2022 PR and VI merchandise trade by partner and sector, USD million',
    )
    census_json_dir = DATA + '/census_state_trade_2022'
    census_json = []
    for state, direction, fn in CENSUS_JSON_FILES:
        census_json.append((
            state, direction,
            I(census_json_dir + '/' + fn, f'US Census CY2022 {state} {direction} statehs HS6, time=2022-12'),
        ))
    I(census_json_dir + '/fetch_census_2022.py',
      'Census fetch script. Reads CENSUS_API_KEY from the environment only. This stage does not run it.')
    I(census_json_dir + '/README.md', 'Provenance for the raw Census statehs extracts')
    I(BUILD + '/config/s05/oil_check_codes.csv', 'S05 oil-check list, carried onto the export report')
    I(ROOT + '/prep/trade/adjustment_summary.csv', 'Prep adjustment_summary.csv at 1fcc7ab, the R3 reference')
    regions_path = I(S01 + '/output/regions.csv', 'S01 regions')
    sectors_path = I(S01 + '/output/sectors.csv', 'S01 sectors')
    map_path = I(S01 + '/output/country_region_map.csv', 'S01 country-to-region map')
    members_path = I(S01 + '/output/composite_members.csv', 'S01 composite members')
    concord_path = I(S01 + '/output/concord_hs17_to_sector.csv', 'S01 HS17 concordance (not committed)')
    concord_hs22_path = I(S01 + '/output/concord_hs22_to_sector.csv', 'S01 HS22 concordance, Census IMDB and the PR/VI extract')
    macro_path = I(S02 + '/output/macro_regions.csv', 'S02 region macro, USA output')
    io04_path = I(S04 + '/output/io_s04.csv.gz', 'S04 I-O table, ICIO comparison only')
    io06_path = I(S06 + '/output/io_s06.csv.gz', 'S06 I-O table, byte-copied')
    s09_compare = I(S09 + '/output/icio_services_compare_s09.csv.gz', 'S09 trd and rdt margin excess, report only')
    imdb_path = I(DATA + '/census_imdb_2022/hs6_cty_rp_2022.csv', 'Census IMDB CY2022 HS6, report only')
    charges_path = I(
        DATA + '/census_imports_hs_2022/imports_hs_hs2_cty_charges_2022.json',
        'Census HS2 partner names for the IMDB top-partner report',
    )

    choices = load_choices(choices_path)
    missing = [k for k in CHOICE_ORDER if k not in choices]
    bad_value, bad_status, blank_who = [], [], []
    for key in CHOICE_ORDER:
        row = choices.get(key)
        if row is None:
            continue
        if not row.get('decided_by', '').strip() or not row.get('decided_at', '').strip() or not row.get('value', '').strip():
            blank_who.append(key)
        if row.get('gtap_status') not in GTAP_STATUS:
            bad_status.append(key)
        if row.get('value', '') not in ALLOWED[key]:
            bad_value.append(f'{key}={row.get("value", "")}')
    n_choices = len(CHOICE_ORDER)
    h2_ok = not (missing or bad_value or bad_status or blank_who or len(choices) != n_choices)
    detail = []
    if missing:
        detail.append('missing ' + ' '.join(missing))
    if blank_who:
        detail.append('blank decided_by, decided_at or value: ' + ' '.join(blank_who))
    if bad_status:
        detail.append('gtap_status: ' + ' '.join(bad_status))
    if bad_value:
        detail.append('value: ' + '; '.join(bad_value))
    if len(choices) != n_choices:
        detail.append(f'row count {len(choices)}')
    S.check(
        'S07-H2',
        f'trade_choices.csv has the {n_choices} choices, each with decided_by, decided_at and a value in its allowed set. '
        'goods_source=baci_all_pairs and pri_vir_trade=in_baci_842 are both required',
        'hard',
        f'{len(choices)} rows; bad {len(bad_value) + len(missing) + len(blank_who) + len(bad_status)}',
        f'{n_choices} rows; 0 bad',
        h2_ok and choices.get('goods_source', {}).get('value') == 'baci_all_pairs'
        and choices.get('pri_vir_trade', {}).get('value') == 'in_baci_842',
        'goods_source; pri_vir_trade', ' '.join(detail),
    )
    if not h2_ok:
        S.finish()
        return

    goods = choices['goods_sectors']['value'].split()
    if goods != GOODS:
        raise SystemExit('goods_sectors token does not match the implemented 32-sector list')
    goods_set = set(goods)
    regions = list(csv.DictReader(open(regions_path)))
    region_order = [r['region'] for r in regions]
    region_ok = set(region_order)
    icio79 = [r['region'] for r in regions if r['icio_measured'] == 'yes']
    row88 = [r['region'] for r in regions if r['type'] == 'composite' or r['icio_measured'] == 'no']
    if len(region_order) != 167 or len(icio79) != 79 or len(row88) != 88:
        raise SystemExit(f'region counts {len(region_order)} {len(icio79)} {len(row88)}')
    row_set = set(row88)
    icio_set = set(icio79)
    oil_check = set()
    with open(BUILD + '/config/s05/oil_check_codes.csv') as fh:
        for r in csv.DictReader(fh):
            if r['flag'] == 'OIL-CHECK-POST-ENERGY':
                oil_check.add(r['code'])

    composite_set = {r['region'] for r in regions if r['type'] == 'composite'}
    single_set = {r['region'] for r in regions if r['type'] == 'single'}
    concord = pd.read_csv(concord_path, dtype=str, keep_default_na=False)
    seen_hs, dup_hs, bad_share = {}, [], []
    hs_rows = []
    ely_src_bad = []
    for rec in concord.itertuples(index=False):
        hs6 = str(rec.hs6).strip().zfill(6)
        share = float(rec.share)
        if hs6 in seen_hs:
            dup_hs.append(hs6)
        seen_hs[hs6] = rec.sector
        if abs(share - 1.0) > 1e-12:
            bad_share.append(hs6)
        sector = rec.sector
        if hs6 in ELY_NOT_ELEC:
            if rec.sector != ELY:
                ely_src_bad.append(f'{hs6}={rec.sector}')
            sector = ELY_NOT_ELEC[hs6]
        hs_rows.append((hs6, sector, rec.agrees_with_gtap))
    missing_ely = sorted(set(ELY_NOT_ELEC) - set(seen_hs))
    if missing_ely or ely_src_bad or seen_hs.get('271600') != ELY:
        raise SystemExit(
            'ely remap: missing ' + ' '.join(missing_ely)
            + '; not ely ' + ' '.join(ely_src_bad)
            + f'; 271600={seen_hs.get("271600")}'
        )
    oil_codes = {h for h, s, _a in hs_rows if s == 'oil'}
    gas_codes = {h for h, s, _a in hs_rows if s == 'gas'}
    oil_ok = set(OIL_HS) <= oil_codes and set(GAS_HS) <= gas_codes
    outside = sorted({s for _h, s, _a in hs_rows if s not in goods_set and s != ELY})

    fill_on = choices['absent_pairs_fill']['value'] == ABSENT_FILL if 'absent_pairs_fill' in choices else False
    fill_csv = ensure_cache(paths, FILL_YEAR if fill_on else None)
    retained_cfg = defaultdict(dict)
    for rec in csv.DictReader(open(retained_path)):
        for col in ('hub', 'item', 'value', 'source', 'decided_by', 'decided_at', 'basis'):
            if not rec.get(col, '').strip():
                raise SystemExit('retained_imports.csv row missing ' + col)
        retained_cfg[rec['hub']][rec['item']] = float(rec['value'])
    flag_isos = [r['iso3'] for r in csv.DictReader(open(flags_path))]
    # beta v4 P26 tier 1 and P18
    rx_on = choices['reexport_comtrade_rx']['value'] == RX_TIER1
    rx_extra = RX_EXTRA[choices['reexport_rx_usa_bel']['value']]
    rx_dir = DATA + '/un_comtrade_rx_2022/hs2'
    prior_x = {}
    if rx_on:
        sums = I(rx_dir + '/SHA256SUMS', 'UN Comtrade 2022 RX and X by HS2 to World, 57 RX reporters (beta v4 P26; public preview API)')
        for line in open(sums):
            h, name = line.split()
            if sha256(os.path.join(rx_dir, name)) != h:
                raise SystemExit(f'{rx_dir}/{name}: SHA256 does not match SHA256SUMS')
        with gzip.open(io06_path, 'rt', newline='') as fh:
            for rec in csv.DictReader(fh):
                if rec['row'].startswith('dom_'):
                    prior_x[(rec['region'], rec['row'][4:])] = float(rec['X'] or 0.0)
    bel_nbb = choices['reexport_rx_usa_bel']['value'] == 'usa_bel_nbb'
    if bel_nbb:
        # beta v5 T2: only once NBB's national- and community-concept 2022 tables are on disk (the stage stops without them)
        bel_csv = I(DATA + '/' + NBB_BEL_FILE, 'beta v5 T2 NBB 2022 goods exports by HS2, national and community concept (EUR)')
    elif 'BEL' in rx_extra:
        bel_csv = I(DATA + '/' + BEL_SHARE_FILE, 'beta v4 P26 BEL quasi-transit share by HS2 (Comext less Comtrade national concept)')
    else:
        bel_csv = None
    region_set = {x['region'] for x in regions}
    tcap_path = I(BUILD + '/config/s07/transit_import_caps.csv', 'beta v4 P18 transit-region merchandise import totals (WTO via WDI)')
    tcap_rows = list(csv.DictReader(open(tcap_path)))
    for rec in tcap_rows:
        if any(not rec.get(c, '').strip() for c in TRANSIT_CAP_COLUMNS if c != 'excluded_hs_prefixes') or rec['region'] not in region_set:
            raise SystemExit(f'transit_import_caps.csv: bad row {rec}')
    transit_caps = ([(r['region'], float(r['goods_imports_musd']), [x for x in r['excluded_hs_prefixes'].split(';') if x])
                     for r in tcap_rows] if choices['transit_import_cap']['value'] == TRANSIT_CAP else None)
    if choices['transit_import_cap']['value'] == TRANSIT_CAP_V5:
        # beta v5 B2 (POL), M1 (KEN), M2 (KGZ tightened to retained imports)
        transit_caps = read_transit_v5(I(BUILD + '/config/s07/transit_import_caps_v5.csv',
                                         'beta v5 transit caps: the v4 rows, POL and KEN, KGZ at retained imports (WDI)'), region_set)
    gold_path = I(BUILD + '/config/s07/gold_reexport_2022.csv', 'beta v4 P39 gold re-export regions, mine output (USGS MYB 2022) and origin')
    gold_rows = read_gold_rows(gold_path, region_set)
    gold_usd_oz = gold_price_2022(I(DATA + '/' + GOLD_PRICE_SHEET, 'World Bank Pink Sheet 2022 gold price (beta v4 P39 mine output value)'))
    gold_on = choices['gold_reexport']['value'] == GOLD_RX
    metal = None
    if choices['gold_reexport']['value'] == METAL_RX:
        metal_rows = read_metal_rows(I(BUILD + '/config/s07/metal_reexport_2022.csv',
                                       'beta v5 G metal re-export rows: ceiling basis, USGS MYB 2022 mine output, origin or drop'), region_set)
        mdir = DATA + '/' + METAL_CUSTOMS_DIR
        for line in open(I(mdir + '/SHA256SUMS', 'UN Comtrade 2022 HS 7108 and 7403 exports to World by reporter (beta v5 G; public preview API)')):
            h, name = line.split()
            if sha256(os.path.join(mdir, name)) != h:
                raise SystemExit(f'{mdir}/{name}: SHA256 does not match SHA256SUMS')
        metal = (metal_rows, mdir, gold_usd_oz / TROY_OZ_KG)
    rx_high = RX_HIGH_SHARE if choices['reexport_high_share']['value'] == RX_HIGH else None
    if rx_high is not None and not rx_on:
        raise SystemExit('reexport_high_share needs reexport_comtrade_rx on')
    surplus_regions = ()
    if choices['reexport_import_surplus']['value'] == RX_SURPLUS:
        sp = I(BUILD + '/config/s07/reexport_surplus_regions.csv', 'beta v5 T1 Gulf non-reporters for the import-surplus re-export test')
        with open(sp, newline='') as fh:
            rd = csv.DictReader(fh)
            if tuple(rd.fieldnames or ()) != RX_SURPLUS_COLUMNS:
                raise SystemExit(f'{sp}: columns {rd.fieldnames} are not {RX_SURPLUS_COLUMNS}')
            srows = list(rd)
        if any(not all(r[c].strip() for c in RX_SURPLUS_COLUMNS) or r['region'] not in single_set for r in srows):
            raise SystemExit(f'{sp}: bad row')
        surplus_regions = tuple(r['region'] for r in srows)
        if not prior_x:
            with gzip.open(io06_path, 'rt', newline='') as fh:
                for rec in csv.DictReader(fh):
                    if rec['row'].startswith('dom_'):
                        prior_x[(rec['region'], rec['row'][4:])] = float(rec['X'] or 0.0)
    floor = None
    if choices['importer_floor']['value'] == IMPORTER_FLOOR:
        frows = read_floor_rows(I(BUILD + '/config/s07/importer_floors.csv', 'beta v5 B importer floors: Comtrade reporter, CIF/FOB, exclusions'), region_set)
        fdir = DATA + '/' + FLOOR_DIR
        for line in open(I(fdir + '/SHA256SUMS', 'UN Comtrade 2022 imports by partner and HS2, CHN and MEX (beta v5 B; public preview API)')):
            h, name = line.split()
            if sha256(os.path.join(fdir, name)) != h:
                raise SystemExit(f'{fdir}/{name}: SHA256 does not match SHA256SUMS')
        pcap = None
        if choices['importer_floor_partner_cap']['value'] == FLOOR_PARTNER_CAP:
            pcap = I(DATA + '/' + PARTNER_X_FILE, 'UN Comtrade 2022 total exports to World by reporter (beta v5 B partner cap; public preview API)')
        floor = (frows, fdir, pcap)
    prep = run_prep(S, hs_rows, composite_set, retained_cfg, flag_isos, fill_csv=fill_csv,
                    drop_cash=choices.get('currency_lines', {}).get('value') == CURRENCY_DROP,
                    rx_dir=rx_dir if rx_on else None, rx_extra=rx_extra, prior_x=prior_x, transit_caps=transit_caps, bel_csv=bel_csv,
                    gold_rows=(gold_rows, gold_usd_oz / TROY_OZ_KG) if gold_on else None,
                    rx_high=rx_high, bel_nbb=bel_nbb, surplus_regions=surplus_regions,
                    hkg_dx=choices['hkg_domestic_export_cap']['value'] == HKG_DX_CAP, floor=floor, metal=metal)
    S.log('aggregating cleaned BACI to the 32 goods sectors')

    cells = defaultdict(float)
    ely_world = 0.0
    ely_usa_im = 0.0
    other_value = 0.0
    for e, i, sector, musd in frame_records(prep['clean_bi'], ('e', 'i', 'sector', 'musd')):
        musd = float(musd)
        if sector == ELY:
            ely_world += musd
            if i == 'USA' and e != 'USA':
                ely_usa_im += musd
        elif sector in goods_set:
            cells[(sector, e, i)] += musd
        else:
            other_value += musd
    dropped_rows = []
    for r, sector, musd in frame_records(prep['clean_intra'], ('r', 'sector', 'musd')):
        musd = float(musd)
        if r in composite_set:
            if sector == ELY:
                ely_world += musd
            elif sector in goods_set:
                cells[(sector, r, r)] += musd
            else:
                other_value += musd
            continue
        dropped_rows.append((r, sector, musd))
        if sector == ELY:
            ely_world += musd
        elif sector not in goods_set:
            other_value += musd

    rows_out = []
    exp_by, imp_by = defaultdict(float), defaultdict(float)
    neg_n = nan_n = 0
    bad_region = []
    world = 0.0
    single_diag = 0.0
    single_diag_n = 0
    for (sector, e, i), v in sorted(cells.items()):
        if abs(v) < DROP:
            continue
        source = 'intra_composite' if e == i else 'baci_all_pairs'
        rows_out.append((sector, e, i, v, v, 'yes', source, 'fob'))
        world += v
        exp_by[sector] += v
        imp_by[sector] += v
        if e == i and e in single_set:
            single_diag += v
            single_diag_n += 1
        if e not in region_ok or i not in region_ok:
            bad_region.append(f'{e}->{i}')
        if v != v:
            nan_n += 1
        elif v < -1e-9:
            neg_n += 1
    duck_world = (prep['goods_bi_kusd'] + prep['composite_intra_goods_kusd']) / 1000.0
    h6_rel = abs(world - duck_world) / abs(duck_world) if duck_world else 1.0
    h6_xm = h6_xr = 0.0
    for s in goods:
        duck_x = (prep['sec_x_kusd'].get(s, 0.0) + prep['sec_intra_kusd'].get(s, 0.0)) / 1000.0
        duck_m = (prep['sec_m_kusd'].get(s, 0.0) + prep['sec_intra_kusd'].get(s, 0.0)) / 1000.0
        h6_xm = max(h6_xm, abs(exp_by[s] - duck_x), abs(imp_by[s] - duck_m))
        # relative to the sector total (at least 1 USD m): the chunked RX step (P26) sums in another order
        h6_xr = max(h6_xr, abs(exp_by[s] - duck_x) / max(abs(duck_x), 1.0), abs(imp_by[s] - duck_m) / max(abs(duck_m), 1.0))

    out_dir = S.out
    shutil.copyfile(io06_path, out_dir + '/io_s07.csv.gz')
    S.log('copied io_s06.csv.gz to io_s07.csv.gz without re-gzipping')
    vx_path = out_dir + '/vxsb_goods_s07r.csv.gz'
    raw_io = open(vx_path, 'wb')
    with gzip.GzipFile(filename='', mode='wb', fileobj=raw_io, mtime=0, compresslevel=9) as gz:
        gz.write(b'sector,exporter,importer,vxsb_musd,vfob_musd,pre_tax,source,basis\n')
        for sector, e, i, vx, vf, pre, source, basis in rows_out:
            gz.write(f'{sector},{e},{i},{fnum(vx)},{fnum(vf)},{pre},{source},{basis}\n'.encode())
    raw_io.close()
    S.log(f'output vxsb_goods_s07r.csv.gz rows {len(rows_out)} bytes {os.path.getsize(vx_path)}')

    # ICIO comparison. Not used to set a value.
    S.log(f'reading {io04_path} for the comparison file')
    df = pd.read_csv(io04_path, index_col=0)
    groups = defaultdict(list)
    for col in df.columns:
        if col == 'OUT' or str(col).endswith('_dpabr'):
            continue
        groups[str(col).split('_', 1)[0]].append(col)
    agg = pd.DataFrame({d: df[cs].sum(axis=1) for d, cs in groups.items()})
    del df
    gc.collect()
    econ = icio79 + ['ISL']
    baci_lookup = defaultdict(float)
    for (sector, e, i), v in cells.items():
        if sector in ('oil', 'gas'):
            baci_lookup[('B06', e, i)] += v
        baci_lookup[(sector, e, i)] += v

    def gz_rows(path, header, records):
        raw = open(path, 'wb')
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0, compresslevel=9) as gz:
            gz.write(header)
            for rec in records:
                gz.write(rec)
        raw.close()

    compare_path = out_dir + '/icio_goods_compare_s07r.csv.gz'
    compare_n = 0
    raw = open(compare_path, 'wb')
    with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0, compresslevel=9) as gz:
        gz.write(b'sector,exporter,importer,icio_basic_musd,baci_fob_musd\n')
        for s in ICIO_GOODS:
            for e in econ:
                series = agg.loc[f'{e}_{s}']
                ee = 'XWE' if e == 'ISL' else e
                for d in econ:
                    if d == e:
                        continue
                    v = float(series[d])
                    if v == 0.0:
                        continue
                    dd = 'XWE' if d == 'ISL' else d
                    baci_v = baci_lookup[(s, ee, dd)]
                    gz.write(f'{s},{ee},{dd},{fnum(v)},{fnum(baci_v)}\n'.encode())
                    compare_n += 1
                row_v = float(series['ROW'])
                if row_v != 0.0:
                    baci_row = sum(baci_lookup[(s, ee, r)] for r in row88)
                    gz.write(f'{s},{ee},ROW,{fnum(row_v)},{fnum(baci_row)}\n'.encode())
                    compare_n += 1
            series = agg.loc[f'ROW_{s}']
            for e in econ:
                v = float(series[e])
                if v == 0.0:
                    continue
                ee = 'XWE' if e == 'ISL' else e
                baci_row = sum(baci_lookup[(s, r, ee)] for r in row88)
                gz.write(f'{s},ROW,{ee},{fnum(v)},{fnum(baci_row)}\n'.encode())
                compare_n += 1
    raw.close()
    del agg
    gc.collect()
    S.log(f'comparison rows {compare_n}')

    # trd_icio, rdt_icio, built. Net margin is ICIO trd+rdt minus BaTIS built, same rows.
    margin = defaultdict(lambda: [0.0, 0.0, 0.0])
    with gzip.open(s09_compare, 'rt', newline='') as fh:
        for row in csv.DictReader(fh):
            if row['sector'] not in ('trd', 'rdt'):
                continue
            if row['kind'] not in ('icio_pair', 'row_export'):
                continue
            slot = 0 if row['sector'] == 'trd' else 1
            margin[row['exporter']][slot] += float(row['icio_musd'])
            margin[row['exporter']][2] += float(row['built_musd'])
    margin_rows = []
    for exporter in sorted(margin):
        trd, rdt, built = margin[exporter]
        margin_rows.append(dict(
            exporter=exporter, trd_icio_musd=fnum(trd), rdt_icio_musd=fnum(rdt),
            excess_musd=fnum(trd + rdt), built_musd=fnum(built), net_musd=fnum(trd + rdt - built),
            note='Net is ICIO trd+rdt minus BaTIS built on icio_pair and row_export. Not subtracted from VXSB.',
        ))

    def write_csv(name, recs, cols):
        path = out_dir + '/' + name
        with open(path, 'w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=cols, lineterminator='\n')
            w.writeheader()
            w.writerows(recs)
        S.log(f'output {name}: {len(recs)} rows')

    goods_27 = set(GOODS_27)
    ind_set = set(ICIO_INDUSTRIES)
    icio_goods = defaultdict(float)
    with gzip.open(compare_path, 'rt', newline='') as fh:
        for row in csv.DictReader(fh):
            if row['exporter'] == 'ROW' or row['sector'] not in ind_set:
                continue
            icio_goods[row['exporter']] += float(row['icio_basic_musd'])
    baci_27 = defaultdict(float)
    for (sector, e, _i), v in cells.items():
        if abs(v) < DROP or sector not in goods_27:
            continue
        baci_27[e] += v
    # ISL is inside XWE in BACI and is labeled XWE in the goods comparison. Its margin row stays ISL.
    residual_keys = set(region_order) | set(icio_goods) | set(margin) | set(baci_27)
    residual_rows = []
    for e in sorted(residual_keys):
        group = 'icio' if e in icio_set else 'no_icio'
        b = baci_27.get(e, 0.0)
        ic = icio_goods.get(e, 0.0)
        trd, rdt, built = margin.get(e, (0.0, 0.0, 0.0))
        gross = trd + rdt
        net = gross - built
        note = ''
        if e == 'XWE':
            note = 'ICIO goods on this row are ISL, labeled XWE. BACI is the whole XWE composite.'
        elif e == 'ISL':
            note = 'ISL is not an S01 region. Its goods are inside XWE. Margin only.'
        residual_rows.append(dict(
            exporter=e, group=group, baci_fob_musd=b, icio_goods_musd=ic,
            margin_icio_musd=gross, margin_built_musd=built, margin_net_musd=net,
            residual_musd=b - ic - net, note=note,
        ))
    icio_residual = [r for r in residual_rows if r['group'] == 'icio']
    icio_residual_sorted = sorted(icio_residual, key=lambda r: -r['residual_musd'])
    no_icio_residual = sum(r['residual_musd'] for r in residual_rows if r['group'] == 'no_icio')
    icio_residual_sum = sum(r['residual_musd'] for r in icio_residual)
    write_csv(
        'reexport_residual_s07r.csv',
        [dict(
            exporter=r['exporter'], group=r['group'],
            baci_fob_musd=fnum(r['baci_fob_musd']), icio_goods_musd=fnum(r['icio_goods_musd']),
            margin_icio_musd=fnum(r['margin_icio_musd']), margin_built_musd=fnum(r['margin_built_musd']),
            margin_net_musd=fnum(r['margin_net_musd']), residual_musd=fnum(r['residual_musd']),
            note=r['note'],
        ) for r in residual_rows],
        ['exporter', 'group', 'baci_fob_musd', 'icio_goods_musd', 'margin_icio_musd',
         'margin_built_musd', 'margin_net_musd', 'residual_musd', 'note'],
    )
    dropped_goods = [(r, s, v) for r, s, v in dropped_rows if s in goods_set and abs(v) >= DROP]
    dropped_by = defaultdict(float)
    for r, _s, v in dropped_goods:
        dropped_by[r] += v
    dropped_total = sum(dropped_by.values())
    write_csv(
        'reimport_dropped_s07r.csv',
        [dict(region=r, sector=s, musd=fnum(v), reason='single-country diagonal dropped')
         for r, s, v in sorted(dropped_rows, key=lambda t: (t[0], t[1])) if abs(v) >= DROP],
        ['region', 'sector', 'musd', 'reason'],
    )
    write_csv(
        'margin_excess_s07r.csv', margin_rows,
        ['exporter', 'trd_icio_musd', 'rdt_icio_musd', 'excess_musd', 'built_musd', 'net_musd', 'note'],
    )

    # ---------------------------------------------------------------- checks
    h1_ok = (abs(prep['hs_gap']) < 1e-6 and prep['hs_n'] == 0 and not dup_hs and not bad_share
             and prep['unmapped_value'] == 0 and prep['s19_region'] == 'TWN' and oil_ok
             and not outside and abs(other_value) < 1e-6)
    S.check(
        'S07-H1',
        'Every BACI HS6 maps to one of the 32 goods sectors or to ely, with share 1. No unmapped value',
        'hard',
        f'unmapped HS value {prep["hs_gap"]:.3f} kUSD across {prep["hs_n"]} codes; unmapped country {prep["unmapped_value"]:.3f} kUSD; '
        f'outside sectors {len(outside)}; other value {other_value:.6f}',
        '0 unmapped; share 1; S19 = TWN; ely is the only non-goods sector',
        h1_ok, 'goods_sectors; mixed_sectors',
        f'S19 -> {prep["s19_region"] or "UNMAPPED"}. Outside {outside[:8]}',
    )
    h5_gap = max(prep['h5_oil_gap'], prep['h5_gas_gap'])
    b06_left = sum(1 for sector, _e, _i, _v, _vf, _p, _s, _b in rows_out if sector == 'B06')
    S.check(
        'S07-H5',
        'Oil equals HS 270900 and 271410, and gas equals HS 271111, 271121 and the remapped 270500, on every pair, to 1e-6. No B06 sector is written',
        'hard',
        f'max abs gap {h5_gap:.3e}; wrong-parent kUSD {prep["wrong_parent_kusd"]:.3e}; B06 rows {b06_left}',
        '1e-6 USD million; 0 B06 rows',
        h5_gap <= 1e-6 and prep['wrong_parent_kusd'] == 0 and b06_left == 0,
        'b06_split', 'Oil HS 270900 and 271410. Gas HS 271111, 271121 and 270500.',
    )
    S.check(
        'S07-H6',
        'World VXSB equals the DuckDB sum of cleaned bilateral goods plus composite-only intra, with ely excluded, '
        'and each sector export and import equals that DuckDB sector sum',
        'hard',
        f'written {world:.6f}; duckdb {duck_world:.6f}; relative gap {h6_rel:.3e}; max sector gap {h6_xm:.3e} USD million, '
        f'relative {h6_xr:.3e}',
        'relative 1e-9, world and each sector (sector total at least 1 USD million)',
        h6_rel <= 1e-9 and h6_xr <= 1e-9, Q_BAL,
        'The sector figure is an HS-level DuckDB sum against the pair-level sum. Summation order moves the last digits (beta v4 dry run 2: '
        '1.6e-5 USD million after the chunked P26 RX step, about 1e-11 of the sector); a dropped HS line would be far above 1e-9.',
    )
    prep_fail = [c for c in prep['prep_checks'] if c['kind'] == 'hard' and not c['passed']]
    h7_hub = True
    h7_bits = []
    for hub in ('HKG', 'NLD', 'SGP'):
        st = prep['hub_stats'][hub]
        change = st['flows_after'] - st['flows_before']
        formula = -(st['funded'] + st['funded'] - st['added'])
        gap = abs(change - formula)
        h7_bits.append(f'{hub} gap {gap:.6f} kUSD')
        if gap > 1.0:
            h7_hub = False
    h7_ok = h7_hub and prep['neg_n'] == 0 and not prep_fail
    S.check(
        'S07-H7',
        'No negative cleaned BACI cell; each hub conserves value within 1 thousand USD',
        'hard',
        f'negative cells {prep["neg_n"]} min {prep["neg_min"]:.3e}; ' + '; '.join(h7_bits) + f'; prep hard fails {len(prep_fail)}',
        '0 negative cells below -1e-6 kUSD; hub gap < 1 kUSD',
        h7_ok, Q_REEX + '; ' + Q_GTAP7,
        'Prep hard failures: ' + ('; '.join(c['id'] + ' ' + c['value'] for c in prep_fail) if prep_fail else 'none'),
    )
    # Retained imports: only hub import cells move, none is raised, everything else is untouched.
    ri_rows = []
    h11_bits = []
    h11_ok = True
    for hub in RI.HUBS:
        st = prep['retained'][hub]
        same_other = st['other_before'] == st['other_after']
        h11_ok = h11_ok and same_other and st['raised'] == 0 and st['removed'] >= 0
        h11_bits.append(
            f'{hub} cells lowered {st["cells"]}, raised {st["raised"]}, other flows sum/count '
            f'{"unchanged" if same_other else "CHANGED"}; imports {bn(st["before"] / 1000.0):.3f} -> {bn(st["after"] / 1000.0):.3f} bn '
            f'(gross {bn(st["gross"] / 1000.0):.3f}; after/gross {st["after"] / st["gross"]:.4f}; '
            f'fitted all-goods ratio {st["overall"]:.4f}; published ratio {st["published"]:.4f})')
        for exp_, sec_, g_, c_, f_, fb_ in st['by_origin_sector']:
            ri_rows.append(dict(hub=hub, exporter=exp_, sector=sec_, gross_musd=fnum(g_), before_musd=fnum(c_),
                                after_musd=fnum(f_), removed_musd=fnum(c_ - f_), fallback_removed_musd=fnum(fb_ or 0)))
    write_csv('retained_imports_s07r.csv', ri_rows,
              ['hub', 'exporter', 'sector', 'gross_musd', 'before_musd', 'after_musd', 'removed_musd', 'fallback_removed_musd'])
    S.check(
        'S07-H15',
        'Hub imports become retained imports: only cells with HKG, SGP or NLD as importer change, none is raised, '
        'and the sum and count of every other BACI flow are unchanged',
        'hard', '; '.join(h11_bits), '0 raised; other flows identical', h11_ok, Q_RET,
        'Per-cell detail by hub, exporter and sector in retained_imports_s07r.csv. fallback_removed_musd is the part '
        'removed with an HS2-wide (HKG) or all-goods ratio because the finer cell had no published import.',
    )
    ships = prep['ships']
    S.check(
        'S07-H16',
        'Vessel trade (HS 8901-8906) to or from an open registry (config/s07/flag_registries.csv) is out of the BACI table',
        'hard', f'dropped {bn(ships["value"] / 1000.0):.3f} bn in {ships["rows"]} rows; rows left {ships["left"]}', '0 rows left',
        ships['left'] == 0, 'GTAP 12 ch.10B (ships); Fable QA D-01, C-06',
        'By registry, bn: ' + ', '.join(f'{c} {bn(v / 1000.0):.3f}' for c, v in ships['by_iso']),
    )
    for c, v in ships['by_iso']:
        S.adjust(c, 'shp (HS 8901-8906, USD million)', '', fnum(-v / 1000.0), 'FLAG-REGISTRY-SHIPS',
                 'GTAP 12 ch.10B (ships); Fable QA D-01', 'flag_registry_ships')
    # beta v4 P13: country pairs absent from BACI 2022 on every line, filled from BACI 2021 (choice absent_pairs_fill)
    fill = prep['fill']
    write_csv('absent_pairs_filled_s07r.csv',
              [dict(exporter=e, importer=m, musd=fnum(v / 1000.0), hs27_musd=fnum(v27 / 1000.0)) for e, m, v, v27 in fill['pairs']],
              ['exporter', 'importer', 'musd', 'hs27_musd'])
    S.check(
        'S07-R18', 'Beta v4 P13 (choice absent_pairs_fill; labelled departure): country pairs with no BACI 2022 row on any HS line and rows in '
        'BACI 2021 (both partners non-reporting), entered at 2021 HS6 value x the world 2022/2021 growth of the HS2 chapter; region pairs by '
        'value (absent_pairs_filled_s07r.csv)', 'report',
        f'{len(fill["pairs"])} region pairs, {bn(fill["value_kusd"] / 1000.0):.3f} bn (2021 value {bn(fill["value_year_kusd"] / 1000.0):.3f} bn) in {fill["rows"]} rows',
        '', True, 'absent_pairs_fill; GTAP 7 ch.9A p.6 (selects reports, silent on gaps)',
        '; '.join(f'{e}->{m} {bn(v / 1000.0):.2f} (HS27 {bn(v27 / 1000.0):.2f})' for e, m, v, v27 in fill['pairs'][:25]),
    )
    for e, m, v, _v27 in fill['pairs']:
        if v / 1000.0 >= 100.0:
            S.adjust(f'{e}->{m}', 'all goods (BACI 2021 x HS2 growth, USD million)', '0', fnum(v / 1000.0), 'ABSENT-PAIR-FILL',
                     'beta v4 P13; labelled departure', 'absent_pairs_fill')
    # beta v4 P22: the currency line HS 490700 out of merchandise trade (choice currency_lines)
    cash = prep['cash']
    S.check(
        'S07-H19', 'Beta v4 P22 (choice currency_lines; IMTS 2010 excludes currency in circulation and securities): HS 490700 is out of the BACI '
        'table', 'hard' if cash['rows'] else 'report', f'dropped {bn(cash["value_kusd"] / 1000.0):.3f} bn in {cash["rows"]} rows; rows left {cash["left"]}',
        '0 rows left', cash['left'] == 0, 'currency_lines; labelled departure (GTAP silent)',
        'Largest pairs, USD m: ' + ', '.join(f'{a}->{b} {v / 1000.0:.1f}' for a, b, v in cash['top']),
    )
    for a, b, v in cash['top']:
        if v / 1000.0 >= 100.0:
            S.adjust(f'{a}->{b}', 'pap (HS 490700, USD million)', fnum(v / 1000.0), '0', 'CURRENCY-HS490700',
                     'beta v4 P22; IMTS 2010', 'currency_lines')
    # beta v4 P26 tier 1: Comtrade RX reporters' re-exports reassigned to the origin (choice reexport_comtrade_rx)
    rxs = prep['rx_stats']
    write_csv('reexport_rx_tier1_s07r.csv',
              [dict(region=r, exports_before_musd=fnum(s['exports_before'] / 1000.0), removed_musd=fnum(s['funded'] / 1000.0),
                    origin_to_dest_musd=fnum(s['added'] / 1000.0), back_to_origin_region_musd=fnum(s['intra'] / 1000.0),
                    exports_after_musd=fnum(s['exports_after'] / 1000.0)) for r, s in sorted(rxs.items(), key=lambda kv: -kv[1]['funded'])],
              ['region', 'exports_before_musd', 'removed_musd', 'origin_to_dest_musd', 'back_to_origin_region_musd', 'exports_after_musd'])
    rx_bad = [r for r, s in rxs.items() if abs((s['exports_before'] - s['exports_after']) - s['funded']) > 1e-6 * max(1.0, s['exports_before'])]
    S.check('S07-H20', 'Beta v4 P26 tier 1 (choice reexport_comtrade_rx; Aguiar et al. 2025 p.12, GTAP 7 ch.9A p.9A-2; Comtrade RX as the national '
            'data is our choice of source): each reporter\'s exports fall by exactly the re-exports funded from its imports (removal capped by '
            'sector at BACI exports above the prior\'s exports; HS 27 left to S11)', 'hard' if rxs else 'report',
            f'{len(rxs)} regions; removed {bn(sum(s["funded"] for s in rxs.values()) / 1000.0):.3f} bn; {len(rx_bad)} mismatches',
            '0 mismatches', not rx_bad, 'reexport_comtrade_rx; reexport_rx_usa_bel',
            '; '.join(f'{r} {bn(s["funded"] / 1000.0):.2f}' for r, s in sorted(rxs.items(), key=lambda kv: -kv[1]['funded'])[:20])
            + ('; left out: ' + ', '.join(f'{iso} ({why})' for _c, iso, why in prep['rx_left']) if prep['rx_left'] else ''))
    for r, s in rxs.items():
        if s['funded'] / 1000.0 >= 100.0:
            S.adjust(r, 'goods exports (Comtrade RX re-exports to the origin, USD million)', fnum(s['exports_before'] / 1000.0),
                     fnum(s['exports_after'] / 1000.0), 'REEXPORT-RX-TIER1', 'beta v4 P26; Aguiar et al. 2025 p.12', 'reexport_comtrade_rx')
    # beta v4 P18: transit regions' imports capped at national merchandise imports (choice transit_import_cap)
    tr = prep['transit']
    S.check('S07-R21', 'Beta v4 P18 (choice transit_import_cap; GTAP 7 ch.9A pp.9A-1 to 9A-3, the more reliable report): transit regions\' '
            'BACI imports outside energy and precious-metal lines capped at WTO merchandise imports (WDI TM.VAL.MRCH.CD.WT, CIF)', 'report',
            f'{sum(1 for x in tr if x[3] < 1)} of {len(tr)} capped; {bn(sum(b - min(b, c) for _r, b, c, _k, _e in tr) / 1000.0):.3f} bn removed', '', True,
            'transit_import_cap', '; '.join(f'{r} {bn(b / 1000.0):.2f} -> {bn(min(b, c) / 1000.0):.2f} (x{k:.3f}; excluded lines {bn(e / 1000.0):.2f})'
                                            for r, b, c, k, e in tr))
    for r, b, c, k, e in tr:
        if k < 1:
            S.adjust(r, 'goods imports outside energy and precious metals (USD million)', fnum(b / 1000.0), fnum(c / 1000.0),
                     'TRANSIT-IMPORT-CAP', 'beta v4 P18; GTAP 7 ch.9A pp.9A-1 to 9A-3', 'transit_import_cap')
    # beta v4 P39: unrecorded dore re-exports rerouted from the origin (choice gold_reexport)
    gd = prep['gold']
    S.check('S07-R22', f'Beta v4 P39 (choice gold_reexport; labelled departure, P26 style): gold exports above recorded imports plus mine output '
            f'(USGS MYB 2022 kg at the Pink Sheet 2022 price {gold_usd_oz:.2f} USD/oz) rerouted from the listed origin', 'report',
            f'{bn(sum(g["moved"] for g in gd) / 1000.0):.3f} bn moved', '', True, 'gold_reexport',
            '; '.join(f'{g["region"]} exports {bn(g["exports"] / 1000.0):.3f} bn, imports {bn(g["imports"] / 1000.0):.3f}, mine {bn(g["mine"] / 1000.0):.3f}, '
                      f'{bn(g["moved"] / 1000.0):.3f} bn moved to {g["origin"]} (x{g["factor"]:.3f})' for g in gd) or 'off')
    for g in gd:
        if g['moved'] > 0:
            S.adjust(g['region'], 'gold exports (HS 7108, USD million)', fnum(g['exports'] / 1000.0), fnum((g['exports'] - g['moved']) / 1000.0),
                     'GOLD-REEXPORT', 'beta v4 P39; labelled departure', 'gold_reexport')
    # beta v5 G: metal re-exports capped at max(own customs, mine + imports), dropped or rerouted (choice gold_reexport)
    md = prep['metal']
    write_csv('metal_reexport_s07r.csv',
              [dict(region=g['region'], hs_prefix=g['prefix'], origin=g['origin'], exports_musd=fnum(g['exports'] / 1000.0),
                    imports_musd=fnum(g['imports'] / 1000.0), mine_musd=fnum(g['mine'] / 1000.0), own_customs_musd=fnum(g['own'] / 1000.0),
                    ceiling_musd=fnum(g['ceiling'] / 1000.0), moved_musd=fnum(g['moved'] / 1000.0), exports_after_musd=fnum(g['after'] / 1000.0))
               for g in md],
              ['region', 'hs_prefix', 'origin', 'exports_musd', 'imports_musd', 'mine_musd', 'own_customs_musd', 'ceiling_musd',
               'moved_musd', 'exports_after_musd'])
    m_bad = [g for g in md if g['after'] - g['ceiling'] > METAL_CEILING_TOL_MUSD * 1000.0
             and not (g['origin'] != 'drop' and g['after'] - g['ceiling'] <= g['exports'] - g['moved'] - g['ceiling'] + 1e-6)]
    S.check('S07-H23', 'Beta v5 G (choice gold_reexport = metal re-export; labelled departure, our application of GTAP 7 ch.9A pp.9A-1 to 9A-3): '
            'after the step, no listed region\'s exports on its HS prefix are more than 0.2 bn above its ceiling, max(own customs exports '
            '(UN Comtrade 2022), mine output (USGS MYB 2022 kg at the Pink Sheet 2022 price) + recorded imports); exports to a reroute origin stay',
            'hard' if md else 'report',
            f'{len(md)} rows; {bn(sum(g["moved"] for g in md) / 1000.0):.3f} bn moved ({bn(sum(g["moved"] for g in md if g["origin"] == "drop") / 1000.0):.3f} dropped); '
            f'{len(m_bad)} above ceiling', '0 above ceiling + 0.2 bn', not m_bad, 'gold_reexport (metal_reexport_2022.csv)',
            '; '.join(f'{g["region"]} {g["prefix"]} {bn(g["exports"] / 1000.0):.2f} -> {bn(g["after"] / 1000.0):.2f} bn (ceiling {bn(g["ceiling"] / 1000.0):.2f}; '
                      f'{"dropped" if g["origin"] == "drop" else "to " + g["origin"]})' for g in md) or 'off')
    for g in md:
        if g['moved'] > 0:
            S.adjust(g['region'], f'exports HS {g["prefix"]} (USD million)', fnum(g['exports'] / 1000.0), fnum((g['exports'] - g['moved']) / 1000.0),
                     'METAL-REEXPORT-DROP' if g['origin'] == 'drop' else 'METAL-REEXPORT-REROUTE', 'beta v5 G; labelled departure', 'gold_reexport')
    # beta v5 T1: the HKG domestic-export cap, the high-share relaxation and the import-surplus test
    hd = prep['hkg_dx']
    S.check('S07-R24', 'Beta v5 T1 (choice hkg_domestic_export_cap; Aguiar et al. 2025 p.12, GTAP 7 ch.9A §9.A.6): HKG exports above C&SD '
            'domestic exports (Trade-IDDS, by destination and HS2) moved to the origin by the HK origin weights; HKG imports left to the '
            'retained-import step', 'report',
            (f'HKG exports {bn(hd["exports_before"] / 1000.0):.3f} -> {bn(hd["exports_after"] / 1000.0):.3f} bn; funded {bn(hd["funded"] / 1000.0):.3f} bn '
             f'(back to the origin region {bn(hd["intra"] / 1000.0):.3f})') if hd else 'off', '', True, 'hkg_domestic_export_cap',
            ('Largest HKG chapters left, bn: ' + ', '.join(f'{h} {bn(v / 1000.0):.3f}' for h, v in hd['by_hs2'])) if hd else '')
    if hd:
        S.adjust('HKG', 'goods exports above C&SD domestic exports (USD million)', fnum(hd['exports_before'] / 1000.0),
                 fnum(hd['exports_after'] / 1000.0), 'HKG-DOMESTIC-EXPORT-CAP', 'beta v5 T1; Aguiar et al. 2025 p.12', 'hkg_domestic_export_cap')
    sp = prep['surplus']
    sp_bad = [r for r, st in sp.items() if abs((st['exports_before'] - st['exports_after']) - st['funded']) > 1e-6 * max(1.0, st['exports_before'])]
    S.check('S07-H25', 'Beta v5 T1 (choice reexport_import_surplus; GTAP 7 ch.9A p.9A-2): each listed non-reporter\'s exports fall by exactly the '
            're-exports funded from its imports (sectors with imports at least exports; exports above the prior, at most the imports; HS 27 and 71 out)',
            'hard' if sp else 'report', f'{len(sp)} regions; removed {bn(sum(st["funded"] for st in sp.values()) / 1000.0):.3f} bn; {len(sp_bad)} mismatches',
            '0 mismatches', not sp_bad, 'reexport_import_surplus', '; '.join(f'{r} {bn(st["funded"] / 1000.0):.3f}' for r, st in sp.items()) or 'off')
    for r, st in sp.items():
        if st['funded'] / 1000.0 >= 50.0:
            S.adjust(r, 'goods exports (import-surplus re-exports to the origin, USD million)', fnum(st['exports_before'] / 1000.0),
                     fnum(st['exports_after'] / 1000.0), 'REEXPORT-IMPORT-SURPLUS', 'beta v5 T1; Aguiar et al. 2025 p.12', 'reexport_import_surplus')
    # beta v5 B: the importer floor at own customs totals
    fo = prep['floor']
    write_csv('importer_floor_s07r.csv',
              [dict(region=f['region'], baci_before_musd=fnum(f['before'] / 1000.0), customs_target_musd=fnum(f['target'] / 1000.0),
                    added_musd=fnum(f['added'] / 1000.0), gap_factor=fnum(f['factor']), unplaced_musd=fnum(f['unplaced'] / 1000.0),
                    customs_total_fob_musd=fnum(f.get('total', 0.0) / 1000.0), reimports_musd=fnum(f.get('own', 0.0) / 1000.0),
                    unmapped_partners_musd=fnum(f.get('unmapped', 0.0) / 1000.0), partner_capped_musd=fnum(f.get('capped', 0.0) / 1000.0),
                    capped_partners='; '.join(f'{p} exports {x / 1e3:.1f} own customs {c / 1e3:.1f} top-up {a / 1e3:.1f} kept {r / 1e3:.1f}'
                                              for p, x, c, a, r in f.get('capped_by', []))) for f in fo],
              ['region', 'baci_before_musd', 'customs_target_musd', 'added_musd', 'gap_factor', 'unplaced_musd', 'customs_total_fob_musd',
               'reimports_musd', 'unmapped_partners_musd', 'partner_capped_musd', 'capped_partners'])
    # a row passes when it was not short, or lands on its target (the partner x HS2 gaps cover the shortfall: factor < 1),
    # or every gap is filled (factor 1); the value with no HS6 line to sit on (unplaced) may be at most 0.1% of the target
    f_bad = [f['region'] for f in fo
             if not (f['before'] >= f['target']
                     or (abs(f['unplaced']) <= 1e-3 * f['target']
                         and (f['factor'] >= 1.0 - 1e-12
                              or abs(f['before'] + f['added'] + f['unplaced'] + f.get('capped', 0.0) - f['target']) <= 1e-6 * f['target'])))]
    S.check('S07-H26', 'Beta v5 B (choice importer_floor; GTAP 7 ch.9A pp.9A-1 to 9A-3, the more reliable report; the mirror of P18): each listed '
            'importer\'s BACI imports outside energy and precious metals reach its own customs total of those lines (UN Comtrade 2022, by partner '
            'and HS2, CIF over its beta v4 VCIF/VFOB, re-imports out) where they fell short, less what the partner caps hold back '
            '(importer_floor_partner_cap: no partner\'s goods exports above its own Comtrade total)', 'hard' if fo else 'report',
            '; '.join(f'{f["region"]} {bn(f["before"] / 1000.0):.2f} -> {bn((f["before"] + f["added"]) / 1000.0):.2f} bn (target {bn(f["target"] / 1000.0):.2f}; '
                      f'+{bn(f["added"] / 1000.0):.2f}' + (f'; {bn(f["capped"] / 1000.0):.2f} held back by partner caps' if f.get('capped') else '') + ')'
                      for f in fo) or 'off', 'at the target (to 1e-6) where the gaps allow', not f_bad,
            'importer_floor (importer_floors.csv)', ' '.join(sorted(set(f_bad))))
    # beta v5 B follow-up (choice importer_floor_partner_cap): no partner the floor tops up ends above its own customs exports
    # (a partner already above them before the floor gets no top-up and is left as BACI has it)
    pc_on = choices['importer_floor_partner_cap']['value'] == FLOOR_PARTNER_CAP
    topped = [t for f in fo for t in f.get('topped', [])]
    t_bad = [t for t in topped if t[1] - t[2] > 1e-6 * max(1.0, t[2])]
    S.check('S07-H27', 'Beta v5 B follow-up (choice importer_floor_partner_cap; ours, on GTAP 7 ch.9A pp.9A-1 to 9A-3): every partner the '
            'importer floor tops up ends with goods exports (at the floor step, all lines, to other regions) at most its own UN Comtrade '
            '2022 total exports; partners already above them get no top-up', 'hard' if pc_on and fo else 'report',
            (f'{len(topped)} partners topped up; {len(t_bad)} above own customs; held back {bn(sum(f.get("capped", 0.0) for f in fo) / 1000.0):.2f} bn'
             if pc_on and fo else 'off'), '0 above own customs (rel 1e-6)', not t_bad, 'importer_floor_partner_cap (un_comtrade_partner_x_2022)',
            '; '.join(f'{p} {bn(x / 1000.0):.2f} > {bn(c / 1000.0):.2f}' for p, x, c, _a in t_bad))
    for f in fo:
        if f['added'] > 0:
            S.adjust(f['region'], 'goods imports outside energy and precious metals (USD million)', fnum(f['before'] / 1000.0),
                     fnum((f['before'] + f['added']) / 1000.0), 'IMPORTER-FLOOR', 'beta v5 B; GTAP 7 ch.9A pp.9A-1 to 9A-3', 'importer_floor')
    hkm = prep['hk_margin']
    margin_rows = [dict(sector='trd', exporter='HKG', importer=d, musd=fnum(v), source='hkg_reexport_margin')
                   for d, v in hkm['by_dest'] if v > 0]
    write_csv('hub_margin_s07r.csv', margin_rows, ['sector', 'exporter', 'importer', 'musd', 'source'])
    hkm_sum = sum(v for _d, v in hkm['by_dest'])
    S.check(
        'S07-H17',
        'HKG re-export margin: the origin goods flows fall by the margin written to hub_margin_s07r.csv (trd, HKG to the '
        'destination), to 1e-3 USD million',
        'hard', f'booked {hkm_sum:.6f} USD m; prep {hkm["applied"] / 1000.0:.6f}',
        'equal', abs(hkm_sum - hkm['applied'] / 1000.0) <= 1e-3, 'GTAP 7 ch.9A §9.A.6; Fable QA D-01',
        f'a {hkm["a"]:.6f}; wanted {bn(hkm["wanted"] / 1000.0):.3f} bn; short {bn(hkm["short"] / 1000.0):.3f}; '
        f'not booked: re-exports back to the origin {bn(hkm["to_origin"] / 1000.0):.3f} bn, unmapped {bn(hkm["unmapped"] / 1000.0):.3f}. '
        'Largest origin -> destination cuts, bn: ' + ', '.join(f'{o}->{d} {bn(v):.3f}' for o, d, v in hkm['by_pair']),
    )
    S.adjust('HKG', 'trd exports, re-export margin (USD million)', '0', fnum(hkm_sum), 'HKG-REEXPORT-MARGIN',
             'GTAP 7 ch.9A §9.A.6; Fable QA D-01', 'hub_margins')
    r9_bits = []
    r10_bits = []
    for hub in RI.HUBS:
        st = prep['retained'][hub]
        r9_bits.append(f'{hub}: ' + ', '.join(
            f'{b} gross {bn(g / 1000.0):.3f} bn ({g / st["gross"]:.2%}) -> {bn(f / 1000.0):.3f}'
            for b, (g, f) in st['by_basis'].items()))
        r10_bits.append(
            f'{hub}: after/gross {st["after"] / st["gross"]:.4f} vs published {st["published"]:.4f} '
            f'(after {bn(st["after"] / 1000.0):.3f} bn; at the published ratio {bn(st["published"] * st["gross"] / 1000.0):.3f} bn; '
            f'gap {(st["after"] / st["gross"]) / st["published"] - 1:+.2%})')
    S.check(
        'S07-R9',
        'Retained-import ratio basis by gross value: HKG origin x HS2, HS2 all origins, all goods; '
        'SGP SingStat category by HS6, by HS4 heading (BACI codes outside HS2017), all goods; NLD CBS SITC section, all goods',
        'report', ' | '.join(r9_bits), 'report', True, Q_RET,
        'gross is the hub import before re-export cleaning; the value after it is the retained import',
    )
    S.check(
        'S07-R10',
        'Retained imports over gross BACI imports against the published all-goods ratio (HKG Annual Digest 2023 '
        'Table 3.1 retained / imports; SGP SingStat M451001 1 - re-exports / imports; NLD CBS 85429NED 1 - re-exports / '
        '(imports - incoming transit))',
        'report', ' | '.join(r10_bits), 'report', True, Q_RET,
        'The ratios need not match: the per-cell ratios are weighted by the BACI import mix, not the national one; '
        'BACI hub imports differ from the national totals (mirror values, CIF/FOB); and no cell is raised above its '
        'current value, so where the hub funded re-export step already cut a cell below ratio x gross, that cut stays '
        '(see flag SGP-FUNDED-PET). HKG also keeps the RAS shortfall of PREP-R-HK-RAS in retained imports.',
    )
    ri_prep = [c for c in prep['prep_checks'] if c['id'].startswith('PREP-R-')]
    S.check(
        'S07-R8',
        'Retained-import ratio inputs (prep checks PREP-R-*; their hard checks also gate S07-H7)',
        'report', '; '.join(f'{c["id"]} {"PASS" if c["passed"] else "FAIL"}' for c in ri_prep), 'report', True, Q_RET,
        ' | '.join(f'{c["id"]} ({c["kind"]}): {c["value"]}' for c in ri_prep),
    )
    same_io = sha256(out_dir + '/io_s07.csv.gz') == sha256(io06_path)
    S.check('S07-H8', 'io_s07.csv.gz is a byte copy of io_s06.csv.gz',
            'hard', sha256(out_dir + '/io_s07.csv.gz'), sha256(io06_path), same_io, Q_FIT, 'cmp by SHA-256')
    sizes = {fn: os.path.getsize(out_dir + '/' + fn) for fn in os.listdir(out_dir)}
    too_big = [f'{fn} {sz}' for fn, sz in sizes.items() if sz >= SIZE_LIMIT]
    bad_sector = [s for s, _e, _i, _v, _vf, _p, _so, _b in rows_out if s not in goods_set]
    h9_ok = neg_n == 0 and nan_n == 0 and not bad_region and not bad_sector and not too_big
    S.check(
        'S07-H9',
        'No negative or NaN VXSB; exporters and importers are the 167 regions; 32 sectors; each output file is under 50 MB',
        'hard',
        f'negative {neg_n}; NaN {nan_n}; bad regions {len(bad_region)}; bad sectors {len(bad_sector)}; files over 50 MB {len(too_big)}',
        '0; 167 regions; 32 sectors; 50 MB',
        h9_ok, 'goods_sectors', ' '.join(too_big[:6]),
    )
    usa_can = cells.get(('mvh', 'USA', 'CAN'), 0.0)
    usa_can_duck = prep['usa_can_mvh_kusd'] / 1000.0
    usa_can_gap = abs(usa_can - usa_can_duck)
    # country_codes is read all_varchar, so the BACI code is the text "842", not an int.
    def as_codes(pairs):
        return [(str(code), iso) for code, iso in pairs]
    code_ok = as_codes(prep['baci_usa_codes']) == [('842', 'USA')] and as_codes(prep['baci_can_codes']) == [('124', 'CAN')]
    S.check(
        'S07-H10',
        'The USA to CAN motor-vehicle cell equals a separate DuckDB sum of cleaned USA to CAN mvh, and the only reporters are BACI 842 and 124',
        'hard',
        f'cell {usa_can:.6f}; duckdb {usa_can_duck:.6f}; gap {usa_can_gap:.3e}; codes USA {prep["baci_usa_codes"]} CAN {prep["baci_can_codes"]}',
        'gap 1e-6 USD million; BACI 842 is the only USA reporter and 124 is the only CAN reporter',
        code_ok and usa_can_gap <= 1e-6, 'goods_source',
        'The cleaner aggregates to S01 regions before the hubs, so the DuckDB sum is exporter USA and importer CAN. PRI and VIR are not BACI reporters.',
    )
    S.check(
        'S07-H14',
        'No single-country region has a diagonal VXSB cell',
        'hard',
        f'{single_diag_n} cells; {bn(single_diag):.6f} bn; dropped goods {bn(dropped_total):.3f} bn across {len(dropped_by)} regions',
        '0 USD million on (r, r) for type=single',
        single_diag_n == 0 and abs(single_diag) <= 1e-9, 'intra_composite',
        'Top dropped: ' + ', '.join(f'{r} {bn(v):.2f}' for r, v in sorted(dropped_by.items(), key=lambda kv: -kv[1])[:8]),
    )
    sources = {source for _s, _e, _i, _v, _vf, _p, source, _b in rows_out}
    icio_src = [s for s in sources if s.startswith('icio_')]
    S.check(
        'S07-H12',
        'No icio_* source in vxsb_goods_s07r.csv.gz',
        'hard', f'sources {sorted(sources)}; icio sources {len(icio_src)}', '0',
        not icio_src, 'goods_source', '',
    )
    h13 = 0.0
    for sector in MOVED:
        booked = exp_by[sector]
        raw_s = sum(v for (s, _e, _i), v in cells.items() if s == sector)
        h13 = max(h13, abs(booked - raw_s))
    S.check(
        'S07-H13',
        'wat, pub, art, pro and pst VXSB equal cleaned BACI for their HS6, to 1e-6',
        'hard', f'max abs gap {h13:.3e}', '1e-6 USD million', h13 <= 1e-6, 'goods_sectors',
        ' '.join(f'{s} {bn(exp_by[s]):.3f} bn' for s in MOVED),
    )
    n_keys = len({(s, e, i, source) for s, e, i, _v, _vf, _p, source, _b in rows_out})
    S.check(
        'S07-H11',
        'Each sector, exporter, importer and source key is written once',
        'hard', f'rows {len(rows_out)}; keys {n_keys}', 'one row per key',
        n_keys == len(rows_out), 'goods_source', '',
    )

    # Census extract stays report-only, with the key scan hard.
    census_totals, _excluded, _limit = load_census_controls(controls_path)
    census_rows = list(csv.DictReader(open(census_path)))
    map_rows = list(csv.DictReader(open(map_path)))
    concord22 = list(csv.DictReader(open(concord_hs22_path)))
    aliases, overrides, by_code, by_norm, icio_codes = load_name_bridge(alias_path, override_path, map_rows, regions)
    derived = rederive_census(census_json, concord22, aliases, overrides, by_norm, by_code, icio_codes)
    country_gap = 0.0
    for key, target in census_totals.items():
        country_gap = max(country_gap, abs(derived['country'].get(key, 0) / 1e6 - target))
    S.check(
        'S07-HC1',
        'Census country rows sum to the API total for all countries, by state and direction',
        'hard', f'max gap {country_gap:.4f} USD million', '0.5 USD million',
        country_gap <= 0.5, 'pri_vir_source', '',
    )
    secret_paths, census_key_set = secret_hits([
        out_dir, BUILD + '/config', DATA + '/census_statehs_2022', DATA + '/census_state_trade_2022',
        S.dir + '/build.log', BUILD + '/s07_trade.py', BUILD + '/specs/S07_trade.md',
    ])
    S.check(
        'S07-HC7',
        'No Census API key is written. The scan is a key= or api_key pattern, plus CENSUS_API_KEY when that variable is set. The value is never printed. The check passes when the variable is absent',
        'hard', f'{len(secret_paths)} hits; env var {"set" if census_key_set else "absent"}', '0 hits',
        not secret_paths, 'US Census International Trade API',
        'Matching text is not printed. Files over 8 MB and compressed outputs are not scanned. ' + ' '.join(secret_paths[:8]),
    )
    csv_cells = {}
    for rec in census_rows:
        key = (rec['state'].strip(), rec['direction'].strip(), rec['partner_s01'].strip(), rec['sector'].strip())
        csv_cells[key] = float(rec['census_musd'])
    cell_gap = 0.0
    n_cell_bad = 0
    for key, val in csv_cells.items():
        got = derived['derived'].get(key)
        if got is None or abs(got - val) > 0.0001 + 1e-9:
            n_cell_bad += 1
            cell_gap = max(cell_gap, abs((got or 0.0) - val))
    only_big = sum(1 for key, val in derived['derived'].items() if key not in csv_cells and val >= 0.0005 - 1e-12)
    dash_gap = 0.0
    for key, target in census_totals.items():
        dash_gap = max(dash_gap, abs(derived['dash'].get(key, 0) / 1e6 - target))
    hc8_ok = n_cell_bad == 0 and only_big == 0 and dash_gap <= 0.5 and not derived['unmapped']
    S.check(
        'S07-HC8',
        'The committed Census CSV equals a re-derivation from the raw JSON, within 0.0001 USD million on every cell',
        'hard',
        f'bad cells {n_cell_bad}; gap {cell_gap:.6f}; JSON-only >= 0.0005 {only_big}; dash vs config {dash_gap:.4f}',
        '0.0001 USD million per cell',
        hc8_ok, 'pri_vir_source', ' '.join(derived['unmapped'][:8]),
    )

    # ---------------------------------------------------------------- reports
    old_path = old_vxsb_path(S)
    old_total = sum_vxsb(old_path)
    old_txt = 'missing' if old_total is None else f'{bn(old_total):.3f} bn'
    S.check(
        'S07-R0',
        'World goods VXSB against the Decision-1 file',
        'report',
        f'new {bn(world):.3f} bn; previous {old_txt}',
        'report', True, 'goods_source', old_path or 'no previous file',
    )
    # Blocks on the 27 goods industries. Moved sectors are merchandise in VXSB and are not in this comparison.
    baci_ii = baci_ir = baci_ri = baci_rr = 0.0
    for (sector, e, i), v in cells.items():
        if sector not in goods_27 or e == i:
            continue
        if e in icio_set and i in icio_set:
            baci_ii += v
        elif e in icio_set and i in row_set:
            baci_ir += v
        elif e in row_set and i in icio_set:
            baci_ri += v
        elif e in row_set and i in row_set:
            baci_rr += v
    icio_ii = icio_ir = icio_ri = 0.0
    with gzip.open(compare_path, 'rt', newline='') as fh:
        for row in csv.DictReader(fh):
            if row['sector'] not in ind_set:
                continue
            v = float(row['icio_basic_musd'])
            if row['exporter'] != 'ROW' and row['importer'] != 'ROW':
                icio_ii += v
            elif row['importer'] == 'ROW' and row['exporter'] != 'ROW':
                icio_ir += v
            elif row['exporter'] == 'ROW':
                icio_ri += v
    margin_net_icio = 0.0
    for e, (trd, rdt, built) in margin.items():
        if e in icio_set:
            margin_net_icio += trd + rdt - built
    S.check(
        'S07-R1',
        'Blocks on the 27 goods industries, BACI against ICIO, and ICIO trd/rdt net of BaTIS built',
        'report',
        f'BACI II {bn(baci_ii):.1f} IR {bn(baci_ir):.1f} RI {bn(baci_ri):.1f} RR {bn(baci_rr):.1f}; '
        f'ICIO II {bn(icio_ii):.1f} IR {bn(icio_ir):.1f} RI {bn(icio_ri):.1f}; net margin of ICIO exporters {bn(margin_net_icio):.1f} bn',
        'report', True, 'icio_compare',
        f'ICIO-exporter residual (27 sectors, net margin) {bn(icio_residual_sum):.1f} bn. '
        f'Non-ICIO residual {bn(no_icio_residual):.1f} bn. The comparison file is not used to set a value.',
    )
    # R2: output is the OUT row of io_s06, not a REG_SEC label. B06 is the oil and gas output.
    out_by = {}
    with gzip.open(io06_path, 'rt', newline='') as fh:
        hdr = fh.readline().rstrip('\n').split(',')
        col_i = {name: i for i, name in enumerate(hdr)}
        for need in ('region', 'row', 'B06'):
            if need not in col_i:
                raise SystemExit('io_s06 missing column ' + need)
        for sec in goods:
            if sec not in ('oil', 'gas') and sec not in col_i:
                raise SystemExit('io_s06 missing sector column ' + sec)
        seen_out = set()
        for line in fh:
            parts = line.rstrip('\n').split(',')
            if parts[col_i['row']] != 'OUT':
                continue
            reg = parts[col_i['region']]
            seen_out.add(reg)
            b06 = float(parts[col_i['B06']])
            for sec in goods:
                if sec in ('oil', 'gas'):
                    out_by[(reg, sec)] = (b06, 'B06')
                else:
                    out_by[(reg, sec)] = (float(parts[col_i[sec]]), sec)
    missing_out = [r for r in region_order if r not in seen_out]
    exp_reg = defaultdict(float)
    for (sector, e, _i), v in cells.items():
        if abs(v) >= DROP:
            exp_reg[(sector, e)] += v
    above = []
    r2_rows = []
    for reg in region_order:
        for sec in goods:
            ex = exp_reg.get((sec, reg), 0.0)
            outv, out_row = out_by.get((reg, sec), (0.0, 'missing'))
            gap = ex - outv
            exceeds = ex > outv
            counted = exceeds and ex > 10.0
            if counted:
                above.append((gap, reg, sec, ex, outv))
            r2_rows.append(dict(
                region=reg, sector=sec, exports_musd=fnum(ex), out_musd=fnum(outv), out_row=out_row,
                x_minus_out=fnum(gap), exceeds='yes' if exceeds else 'no',
                counted='yes' if counted else 'no',
                oil_check='yes' if sec == 'oil' and reg in oil_check else 'no',
            ))
    above.sort(reverse=True)
    write_csv(
        'exports_vs_output_s07r.csv', r2_rows,
        ['region', 'sector', 'exports_musd', 'out_musd', 'out_row', 'x_minus_out', 'exceeds', 'counted', 'oil_check'],
    )
    oil_note = []
    for code in sorted(oil_check):
        ex = exp_reg.get(('oil', code), 0.0)
        outv = out_by.get((code, 'oil'), (0.0, 'missing'))[0]
        oil_note.append(f'{code} oil {bn(ex):.1f} vs B06 output {bn(outv):.2f}')
    chn_elc_ex = exp_reg.get(('elc', 'CHN'), 0.0)
    chn_elc_out = out_by.get(('CHN', 'elc'), (0.0, 'missing'))[0]
    S.check(
        'S07-R2',
        'Exports above S06 output, read from the OUT row. Counted when exports exceed output and 10 USD million. Oil and gas use the B06 OUT cell',
        'report', f'{len(above)} region-sectors; missing OUT rows {len(missing_out)}', 'report', True, Q_TRADE_WINS,
        f'CHN elc exports {bn(chn_elc_ex):.1f} bn vs output {bn(chn_elc_out):.1f} bn. '
        'Largest: ' + '; '.join(f'{r} {s} {bn(ex):.1f} vs {bn(o):.2f}' for _g, r, s, ex, o in above[:8])
        + '. ' + '; '.join(oil_note)
        + ('. Missing OUT: ' + ' '.join(missing_out) if missing_out else ''),
    )
    top20 = icio_residual_sorted[:20]
    S.check(
        'S07-R3',
        'Like-for-like residual, ICIO exporters only: 27 goods sectors, cleaned BACI minus ICIO goods industries minus net margin. Non-ICIO regions are reported separately and are not in this ranking',
        'report',
        f'ICIO residual {bn(icio_residual_sum):.1f} bn; non-ICIO {bn(no_icio_residual):.1f} bn; '
        f'top {top20[0]["exporter"]} {bn(top20[0]["residual_musd"]):.1f}',
        '27 goods industries, 79 ICIO exporters, net of BaTIS built',
        True, 'reexport_hubs',
        '; '.join(f'{r["exporter"]} {bn(r["residual_musd"]):.0f}' for r in top20),
    )
    pri_x = sum(float(r['census_musd']) for r in census_rows if r['direction'] == 'exports')
    pri_m = sum(float(r['census_musd']) for r in census_rows if r['direction'] == 'imports')
    usa_im_off = sum(v for (_s, e, i), v in cells.items() if i == 'USA' and e != 'USA')
    S.check(
        'S07-R4',
        'Census PR and VI foreign trade against BACI 842, record only. USA to USA is excluded. The carve is retired',
        'report',
        f'Census exports {bn(pri_x):.3f} bn; imports {bn(pri_m):.3f} bn; USA BACI imports excluding USA to USA {bn(usa_im_off):.3f} bn',
        'report', True, 'pri_vir_trade',
        'BACI 842 already includes PR and VI. The share of code 842 that is PR or VI is not computable: '
        '842 is one customs territory and BACI has no PR or VI reporter. Census is not added. E37 is met by code 842.',
    )
    # R6 USA vs Census IMDB
    hs22 = {}
    for rec in concord22:
        if rec.get('sector') and rec.get('share'):
            hs22[rec['hs22'].zfill(6)] = rec['sector']
    names = {}
    try:
        blob = json.load(open(charges_path))
    except json.JSONDecodeError:
        blob = []
    # The charges extract is a list of lists, or a dict. Accept both.
    if isinstance(blob, dict):
        rows_j = blob.get('data') or blob.get('dataset') or []
    else:
        rows_j = blob
    if rows_j and isinstance(rows_j[0], list):
        header = [str(x) for x in rows_j[0]]
        if 'CTY_CODE' in header and 'CTY_NAME' in header:
            ic, nc = header.index('CTY_CODE'), header.index('CTY_NAME')
            for rec in rows_j[1:]:
                names.setdefault(str(rec[ic]), str(rec[nc]))
    cen_sec = defaultdict(float)
    cen_partner = defaultdict(float)
    cen_goods = cen_all = 0.0
    with open(imdb_path, newline='') as fh:
        for rec in csv.DictReader(fh):
            con_val = float(rec['con_val'] or 0)
            cen_all += con_val
            sec = hs22.get(rec['hs6'].zfill(6), '')
            if sec not in goods_set:
                continue
            cen_goods += con_val
            cen_sec[sec] += con_val
            cen_partner[rec['cty']] += con_val
    usa_im = sum(v for (_s, _e, i), v in cells.items() if i == 'USA' and _e != 'USA')
    usa_ex = sum(v for (_s, e, _i), v in cells.items() if e == 'USA' and _i != 'USA')
    top_baci = defaultdict(float)
    for (_s, e, i), v in cells.items():
        if i == 'USA' and e != 'USA':
            top_baci[e] += v
    top_baci_s = sorted(top_baci.items(), key=lambda kv: -kv[1])[:10]
    top_cen = sorted(cen_partner.items(), key=lambda kv: -kv[1])[:10]
    sec_lines = []
    for sec in goods:
        baci_s = sum(v for (s, _e, i), v in cells.items() if s == sec and i == 'USA' and _e != 'USA')
        sec_lines.append(f'{sec} BACI {bn(baci_s):.2f} Census {cen_sec[sec]/1e9:.2f}')
    write_csv(
        'usa_scrutiny_s07r.csv',
        [dict(item='imports', baci_musd=fnum(usa_im), census_usd=fnum(cen_goods / 1e6), note='Census con_val on the 32 goods sectors, dollars in the source file, here USD million via /1e6')]
        + [dict(item=f'baci_partner_{e}', baci_musd=fnum(v), census_usd='', note='cleaned BACI imports') for e, v in top_baci_s]
        + [dict(item=f'census_cty_{c}', baci_musd='', census_usd=fnum(v / 1e6), note=names.get(c, '')) for c, v in top_cen],
        ['item', 'baci_musd', 'census_usd', 'note'],
    )
    S.check(
        'S07-R6',
        'USA BACI 842 imports and exports by sector and top partner, against Census IMDB con_val mapped with S01 HS22',
        'report',
        f'cleaned imports {bn(usa_im):.3f} bn; exports {bn(usa_ex):.3f} bn; Census goods con_val {cen_goods/1e9:.3f} bn; all-HS con_val {cen_all/1e9:.3f} bn',
        'about 3,153 bn cleaned against Census about 3,075 bn on goods',
        True, 'goods_source',
        'Top BACI partners: ' + ', '.join(f'{e} {bn(v):.1f}' for e, v in top_baci_s)
        + '. Top Census cty: ' + ', '.join(f'{c} {names.get(c, "")} {v/1e9:.1f}' for c, v in top_cen)
        + '. Sectors: ' + '; '.join(sec_lines),
    )
    moved_world = sum(exp_by[s] for s in MOVED)
    moved_usa = sum(v for (s, e, i), v in cells.items() if s in MOVED and i == 'USA' and e != 'USA')
    census_moved_bn = sum(cen_sec[s] for s in MOVED) / 1e9
    S.check(
        'S07-R7',
        'Moved-out goods booked as merchandise. USA imports are BACI and Census con_val',
        'report',
        f'world {bn(moved_world):.3f} bn; USA BACI imports {bn(moved_usa):.3f} bn; USA Census con_val {census_moved_bn:.3f} bn',
        'BACI and Census con_val, both reported',
        True, 'goods_sectors',
        ' '.join(f'{s} {bn(exp_by[s]):.2f}' for s in MOVED),
    )
    other_sha = os.environ.get('S07_R5_SHA256SUMS', '')
    if other_sha and os.path.exists(other_sha):
        same = open(out_dir + '/SHA256SUMS').read() == open(other_sha).read() if os.path.exists(out_dir + '/SHA256SUMS') else False
        # SHA256SUMS is written in finish(), after this check. Compare by hashing outputs except the sums file.
        def tree_hash(directory):
            h = hashlib.sha256()
            for fn in sorted(os.listdir(directory)):
                if fn == 'SHA256SUMS':
                    continue
                h.update(fn.encode())
                h.update(sha256(os.path.join(directory, fn)).encode())
            return h.hexdigest()
        other_dir = os.path.dirname(other_sha)
        same = tree_hash(out_dir) == tree_hash(other_dir)
        S.check('S07-R5', 'Two runs write the same output bytes',
                'report', f'match {same}', 'match', same, 'stage kit', other_sha)
    else:
        S.check('S07-R5', 'Two runs write the same output bytes',
                'report', 'other run not set', 'S07_R5_SHA256SUMS', True, 'stage kit',
                'Set S07_R5_SHA256SUMS to the other run output/SHA256SUMS. The canonical run compares it.')

    # flags and ledger
    ely_bits = []
    for hs6, dest in sorted(ELY_NOT_ELEC.items()):
        part = prep['ely_moved'][hs6]
        booked = (part['bilateral_kusd'] + part['composite_kusd']) / 1000.0
        ely_bits.append(
            f'{hs6}->{dest} booked {bn(booked):.3f} bn, single-country diagonal {part["single_kusd"] / 1e6:.3f} bn not booked'
        )
    S.flag(
        'ELY-HS-MOVED', '220190 270500 284450',
        'Three non-electricity lines leave ely before the sector sum. ' + '; '.join(ely_bits)
        + '. 220190 (GTAP BT) goes to fbt. 270500 (GTAP GDT; S01 maps GDT to ely) goes to gas. 284450 (GTAP CHM) goes to chm. 271600 stays ely.',
        'no', 'mixed_sectors', 'GTAP sector column BT, GDT, CHM',
    )
    S.flag('ELY-TO-S11', 'ely', f'HS 271600 stays out of VXSB. Cleaned value {bn(ely_world):.3f} bn, USA imports {bn(ely_usa_im):.3f} bn.',
           'no', 'mixed_sectors', 'Aguiar et al. 2025 pp.9, 14')
    S.flag('F6-TWN-490', 'TWN', 'BACI 490 (ISO3 S19) is TWN.', 'no', 'baci_vintage', 'S01 source_aliases')
    S.flag('REEXPORT-NOT-ADJUSTED', 'BEL ARE PAN', 'Three hubs are cleaned. BEL, ARE and PAN are not adjusted.',
           'no', 'reexport_hubs', Q_REEX)
    S.flag('RETAINED-IMPORTS', 'HKG SGP NLD',
           'HKG, SGP and NLD imports are set to their official retained-import ratios (HKG C&SD Annual Digest 2023 Table 3.1; '
           'SGP SingStat M451001 by section; NLD CBS 85429NED by SITC section, national concept: imports less incoming '
           'transit, Fable QA D-01). ARE is not converted: no UAE statistics host '
           'was reachable from the build machine (FCSC, Dubai Statistics Center). '
           'Ratio fills, in order: HKG origin x HS2 (RAS fit), else HS2 across origins, else all goods; '
           'SGP SingStat category of the HS6 code (UNSD HS2017-SITC Rev.4 conversion), else the category of its HS4 '
           'heading when unique (BACI codes outside HS2017, e.g. 271000), else all goods; NLD SITC section of the HS6 code '
           '(UNSD correlation), else all goods. Value by fill in S07-R9; '
           'gap to the published ratios in S07-R10.',
           'no', 'reexport_hubs', Q_RET)
    sg = prep['retained']['SGP']
    pet_g = sum(g for _e, sec, g, _c, _f, _fb in sg['by_origin_sector'] if sec == 'pet')
    pet_c = sum(c for _e, sec, _g, c, _f, _fb in sg['by_origin_sector'] if sec == 'pet')
    S.flag('SGP-FUNDED-PET', 'SGP pet',
           f'SGP pet imports before the retained-import step are {bn(pet_c):.3f} bn of {bn(pet_g):.3f} bn gross '
           f'({pet_c / pet_g:.3f}); SingStat oil retained/imports is {sg["oil_ratio"]:.3f}. The SGP funded re-export '
           f'step identifies re-exports by destination x category, fitted to the SingStat destination and category '
           f're-export shares (PREP-R-SG-FIT, retained_imports.fit_sg_identified). The earlier uniform destination share '
           f'cut pet imports to 35.164 bn (0.554). David chose to fix it (decision card, 2026-10-23 22:20 UTC).',
           'no', 'reexport_hubs', Q_REEX)
    chn_g, chn_c, chn_f = prep['retained']['HKG']['chn']
    S.flag('HKG-MARGIN-CHN', 'HKG CHN',
           f'C&SD does not publish re-export margins by origin, so one factor (imports - retained) / re-exports from '
           f'Table 3.1 is used for every origin. Most HKG re-exports are of Chinese origin, so CHN->HKG imports fall '
           f'from {bn(chn_c / 1000.0):.3f} to {bn(chn_f / 1000.0):.3f} bn (gross {bn(chn_g / 1000.0):.3f}); '
           f'chapters 84, 85, 71 and 90 from China are close to zero. '
           f'If Chinese goods carry a larger Hong Kong re-export markup '
           f'than others (Feenstra and Hanson 2004 study this), the uniform factor removes too much from CHN and too '
           f'little from other origins. Decided: David chose to keep the published single margin '
           f'(decision card, 2026-10-23 22:17 UTC).',
           'no', 'reexport_hubs', Q_RET)
    S.flag('MIRROR-BACI', 'BACI', 'Mirrors stay as CEPII published them. GTAP 7 selects the more reliable report. GTAP 12 method is not public.',
           'no', 'mirror_reconciliation', Q_SELECT)
    S.flag('INTRA-COMPOSITE-DIAGONAL', 'composites',
           'Trade between members of one composite region is VXSB(r, r). A single country has no diagonal.',
           'no', 'intra_composite', 'not in GTAP text')
    S.flag(
        'REIMPORT-DROPPED', 'single regions',
        f'Single-country diagonals after hub cleaning are not VXSB. Goods dropped {bn(dropped_total):.3f} bn '
        f'across {len(dropped_by)} regions. Logged in reimport_dropped_s07r.csv.',
        'no', 'intra_composite', 'Aguiar et al. 2025 p.12',
    )
    S.flag('PRI-VIR-IN-BACI-842', 'USA', 'The PR/VI carve is retired. BACI 842 includes them. Census is report-only.',
           'no', 'pri_vir_trade', 'E37')
    for hub in ('HKG', 'NLD', 'SGP'):
        st = prep['hub_stats'][hub]
        S.adjust('world', f'REEXPORT-HUB-{hub}', '', fnum(st['funded'] / 1000.0), f'REEXPORT-HUB-{hub}', Q_REEX, '')
    for hub in RI.HUBS:
        st = prep['retained'][hub]
        S.adjust(hub, 'goods imports (USD million)', fnum(st['before'] / 1000.0), fnum(st['after'] / 1000.0),
                 f'RETAINED-IMPORTS-{hub}', Q_RET, 'RETAINED-IMPORTS')
    for sector in goods:
        S.adjust('world', sector, '', fnum(exp_by[sector]), 'BACI-ALL-PAIRS', Q_HS, '')
    moved_flag = ' '.join(f'{s} {bn(exp_by[s]):.2f}' for s in MOVED)
    S.flag('MERCHANDISE-MOVED', 'wat pub art pro pst', f'Booked from BACI. World bn: {moved_flag}.',
           'no', 'goods_sectors', 'Aguiar et al. 2022 p.11')

    write_notes(S, choices, dict(
        world_bn=bn(world), old_bn=None if old_total is None else bn(old_total),
        usa_im_bn=bn(usa_im), usa_ex_bn=bn(usa_ex),
        census_goods_bn=cen_goods / 1e9, census_all_bn=cen_all / 1e9,
        moved_world_bn=bn(moved_world), moved_usa_bn=bn(moved_usa), census_moved_bn=census_moved_bn,
        ely_bn=bn(ely_world), residual_bn=bn(icio_residual_sum), no_icio_bn=bn(no_icio_residual),
        dropped_bn=bn(dropped_total),
        top='; '.join(f'{r["exporter"]} {bn(r["residual_musd"]):.0f}' for r in top20[:8]),
        pri_x_bn=bn(pri_x), pri_m_bn=bn(pri_m),
        baci_ii_bn=bn(baci_ii), icio_ii_bn=bn(icio_ii), margin_bn=bn(margin_net_icio),
    ))
    S.finish()


def write_notes(S, choices, summary):
    lines = [
        '# S07R merchandise trade',
        '',
        f'Build commit `{S.head}`. Goods source `{choices["goods_source"]["value"]}` '
        f'({choices["goods_source"]["decided_by"]}, {choices["goods_source"]["decided_at"]}).',
        '',
        f'World VXSB {summary["world_bn"]:.3f} bn. Previous Decision-1 file '
        f'{summary["old_bn"] if summary["old_bn"] is not None else "not on this run"} bn.',
        f'USA imports {summary["usa_im_bn"]:.3f} bn. USA exports {summary["usa_ex_bn"]:.3f} bn. '
        f'Census IMDB goods con_val {summary["census_goods_bn"]:.3f} bn. All-HS con_val {summary["census_all_bn"]:.3f} bn.',
        f'Moved-out goods {summary["moved_world_bn"]:.3f} bn world. USA BACI imports {summary["moved_usa_bn"]:.3f} bn. '
        f'USA Census con_val {summary["census_moved_bn"]:.3f} bn. ely (HS 271600) left for S11: {summary["ely_bn"]:.3f} bn. '
        f'HS 220190, 270500 and 284450 are booked as fbt, gas and chm.',
        f'Single-country diagonals dropped: {summary["dropped_bn"]:.3f} bn. Composite diagonals stay.',
        f'Like-for-like residual (27 goods, 79 ICIO exporters, net of BaTIS built) {summary["residual_bn"]:.1f} bn. '
        f'Non-ICIO residual {summary["no_icio_bn"]:.1f} bn. Top ICIO: {summary["top"]}.',
        f'BACI ICIO-to-ICIO on the 27 goods {summary["baci_ii_bn"]:.1f} bn. ICIO goods-industry pairs {summary["icio_ii_bn"]:.1f} bn. '
        f'Net margin of ICIO exporters {summary["margin_bn"]:.1f} bn.',
        f'Census PR+VI exports {summary["pri_x_bn"]:.3f} bn, imports {summary["pri_m_bn"]:.3f} bn. Not added to USA. '
        f'The PR/VI share of BACI 842 is not computable.',
        '',
        'VXSB equals VFOB. pre_tax is yes. S10 divides by the export-tax power.',
        'io_s07.csv.gz is a byte copy of io_s06.csv.gz.',
        '',
        '## Open points',
        '',
        '- Re-export cleaning is still three hubs. R3 is the like-for-like residual.',
        '- HKG, SGP and NLD imports are converted to retained imports (S07-H15, retained_imports_s07r.csv). '
        'NLD, BEL, ARE and PAN imports are not converted.',
        '- S09 wording that there is no wat trade should say no wat services, once S09 is rerun. Not started here.',
        '- BACI mirror averaging is used as published.',
        '- The tariff concordance move waits for the S10 rerun. David confirmed 2026-10-21 14:01 UTC+7 that S10 will use S01 at 5ddbe4d.',
        '- S13 removes the ICIO trd/rdt export-margin cells in FIT.',
    ]
    open(S.dir + '/REVIEW_BRIEF.md', 'w').write('\n'.join(lines) + '\n')
    asks = [f for f in S.flags if f['needs_david'] == 'yes']
    open(S.dir + '/NEEDS_DAVID.md', 'w').write(
        '# NEEDS_DAVID\n\n'
        + (''.join(f'- **{f["id"]}** ({f["subject"]}): {f["text"]}\n' for f in asks) if asks else 'None.\n')
        + '\nEarlier decisions: David, 2026-10-21 13:52 UTC+7, reversed Decision 1. '
        'Timmy, 2026-10-21 14:00 UTC+7, retired the Puerto Rico carve.\n'
    )


if __name__ == '__main__':
    main()
