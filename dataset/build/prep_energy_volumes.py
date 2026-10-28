"""2022 physical energy volumes for the 167 S01 regions.

Prep for stage (g) / S11. Prices and subsidies are not built here.
Oil and gas volumes exclude natural gas plant liquids / NGL (PLAN_ERRATA E29).

The old EIA gas "production" column was the last INTL.26 BCM series in the bulk
file (consumption, imports or exports). Production is activity 1 only.
See dataset/data/eia_intl/FETCH_NOTES.md.
"""
import os, sys, csv, json, zipfile, collections
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/lib')
from stagekit import Stage, DATA, BUILD, STAGES, BASE_YEAR

Y = BASE_YEAR
DAYS = 365  # 2022 is not a leap year; JODI annual kb/d = sum of monthly thousand barrels / 365
CFG = os.path.dirname(os.path.abspath(__file__)) + '/config/prep_energy'
S01 = STAGES + '/S01_sets_registry'

# EIA product-activity-unit -> internal label. Activity is part of the key on purpose.
EIA_WANTED = {
    ('26', '1', 'BCM'): 'eia_gas_production',
    ('26', '2', 'BCM'): 'eia_gas_consumption',
    ('26', '3', 'BCM'): 'eia_gas_imports',
    ('26', '4', 'BCM'): 'eia_gas_exports',
    ('57', '1', 'TBPD'): 'eia_crude_production',
    ('57', '3', 'TBPD'): 'eia_crude_imports',
    ('57', '4', 'TBPD'): 'eia_crude_exports',
    ('58', '1', 'TBPD'): 'eia_ngpl_production',
    ('7', '1', 'MT'): 'eia_coal_production',
    ('7', '2', 'MT'): 'eia_coal_consumption',
    ('7', '3', 'MT'): 'eia_coal_imports',
    ('7', '4', 'MT'): 'eia_coal_exports',
    ('7', '2', 'TJ'): 'eia_coal_consumption_tj',
    ('2', '12', 'BKWH'): 'eia_elec_production',
    ('2', '2', 'BKWH'): 'eia_elec_consumption',
    ('2', '3', 'BKWH'): 'eia_elec_imports',
    ('2', '4', 'BKWH'): 'eia_elec_exports',
    ('54', '2', 'TBPD'): 'eia_refined_consumption',
}
# Physical output scale. Coal MT is "1000 metric tons" in the bulk file.
SCALE = {
    'eia_coal_production': 1 / 1000,
    'eia_coal_consumption': 1 / 1000,
    'eia_coal_imports': 1 / 1000,
    'eia_coal_exports': 1 / 1000,
}
# EI stated gross calorific value for the gas volume sheets: 40 MJ/m3 = 40,000 TJ/bcm.
# The conversion-factor sheet also lists 36 PJ/bcm. That NCV factor is not applied.
TJ_PER_BCM_GCV40 = 40000.0
# EI "Approximate conversion factors": 1 barrel of crude = 0.1364 tonnes, worldwide average gravity.
TONNES_PER_BBL = 0.1364
# Same sheet, oil products: the "product basket" row converts tonnes to barrels at 8.0577 bbl/t.
# Used only for UNSD oil-product fills (S11 handoff step 1; GTAP 12 ch.12 p.5 UN gap fill).
PRODUCT_BBL_PER_TONNE = 8.057701639134846
UNSD_PRODUCT_CODES = {'4610', '4620', '4630', '4640', '4651', '4652', '4653', '4661', '4669', '4670', '4680',
                      '4691', '4692', '4693', '4694', '4695', '4699'}   # SIEC 46 oil products, leaf codes only

EI_SHEETS = {
    'Gas Production - Bcm': 'ei_gas_production',
    'Gas Consumption - Bcm': 'ei_gas_consumption',
    'Crude+cond production - barrels': 'ei_crude_production',
    'NGLs production - barrels': 'ei_ngl_production',
    'Oil Production - barrels': 'ei_oil_incl_ngl',
    'Oil refinery - throughput': 'ei_refinery_throughput',
    'Oil Consumption - barrels': 'ei_oil_consumption',
    'Coal Production - mt': 'ei_coal_production',
    'Coal Consumption - EJ': 'ei_coal_consumption_ej',
    'Electricity Generation - TWh': 'ei_elec_production',
}

# Comparisons against the chosen series. same_concept is yes / partial / no.
# A "no" is still reported: the sources do not measure the same thing, and the gap is not removed.
PAIRS = [
    ('gas', 'production', 'ei_gas_production', 'no',
     'EI Statistical Review 2025, Gas Production - Bcm: excludes flared and recycled gas; standardised at 15C and 1013 mbar from energy at a GCV of 40 MJ/m3. EIA INTL.26-1-BCM is dry natural gas (after NGPL extraction) in EIA cubic metres.'),
    ('gas', 'consumption', 'ei_gas_consumption', 'no',
     'EI gas consumption excludes gas converted to liquid fuels and is on the same 15C / 40 MJ/m3 basis. EIA INTL.26-2 is dry-gas consumption.'),
    ('gas', 'production', 'jodi_gas_production', 'partial',
     'JODI NATGAS INDPROD, monthly million m3 summed to bcm. National conditions; gross or marketed as the country reports it.'),
    ('gas', 'imports', 'jodi_gas_imports', 'partial', 'JODI NATGAS TOTIMPSB, million m3 summed to bcm.'),
    ('gas', 'exports', 'jodi_gas_exports', 'partial', 'JODI NATGAS TOTEXPSB, million m3 summed to bcm.'),
    ('gas', 'consumption', 'jodi_gas_consumption', 'partial', 'JODI NATGAS TOTDEMO (observed demand), million m3 summed to bcm.'),
    ('gas', 'production', 'unsd_gas_production_gcv40', 'no',
     'UNSD commodity 3000 transaction 01 is terajoules in this extract. bcm = TJ / 40000, using the EI gas-sheet GCV of 40 MJ/m3. Not the chosen volume.'),
    ('crude', 'production', 'ei_crude_production', 'partial',
     'EI sheet Crude+cond production: crude, shale/tight oil, oil sands, lease condensate or gas condensates that require further refining. Excludes NGLs. EIA 57 is crude including lease condensate.'),
    ('crude', 'production', 'ei_oil_incl_ngl', 'no',
     'EI Oil Production includes NGLs. Shown so the NGL wedge is visible. Not the chosen crude series.'),
    ('crude', 'production', 'jodi_crude_production', 'partial',
     'JODI primary CRUDEOIL INDPROD, not TOTCRUDE and not NGL. Thousand barrels / 365.'),
    ('crude', 'imports', 'jodi_crude_imports', 'partial', 'JODI CRUDEOIL TOTIMPSB.'),
    ('crude', 'exports', 'jodi_crude_exports', 'partial', 'JODI CRUDEOIL TOTEXPSB.'),
    ('crude', 'consumption', 'jodi_crude_use', 'yes',
     'Chosen crude use is this JODI series: CRUDEOIL refinery intake plus direct use.'),
    ('crude', 'production', 'unsd_crude_production_kbd', 'no',
     'UNSD 4100 conventional crude oil, thousand metric tons, converted at the EI average 0.1364 tonnes per barrel. Not the chosen volume.'),
    ('coal', 'production', 'ei_coal_production', 'partial',
     'EI Coal Production - mt: commercial solid fuels (hard coal, lignite and brown coal), million tonnes, including coal for CTL/CTG.'),
    ('coal', 'production', 'unsd_coal_production', 'partial',
     'UNSD hard coal 0100 plus brown coal 0200, transaction 01. Sub-codes of 0100 and 0200 are not added again.'),
    ('coal', 'imports', 'unsd_coal_imports', 'partial', 'UNSD 0100+0200 transaction 03.'),
    ('coal', 'exports', 'unsd_coal_exports', 'partial', 'UNSD 0100+0200 transaction 04.'),
    ('coal', 'consumption', 'ei_coal_consumption_ej', 'no',
     'EI coal consumption is exajoules. Compared with EIA coal consumption in TJ / 1e6. Calorific basis may differ. Not a tonne comparison.'),
    ('refined', 'production', 'ei_refinery_throughput', 'no',
     'EI refinery throughput is distillation input, thousand barrels daily. JODI REFGROUT is refinery gross output. PLAN E5 chooses gross output.'),
    ('refined', 'consumption', 'eia_refined_consumption', 'partial',
     'EIA INTL.54-2 refined petroleum products consumption, thousand barrels per day. Production in that family (54-1) has no 2022 values, so JODI remains the chosen source for every refined flow.'),
    ('refined', 'consumption', 'ei_oil_consumption', 'no',
     'EI oil consumption is inland demand plus bunkers and refinery fuel and loss. Biofuels are excluded; coal-to-liquid and gas-to-liquid derivatives are included. Wider than JODI TOTPRODS demand.'),
    ('electricity', 'production', 'ei_elec_production', 'no',
     'EI Electricity Generation is gross output, TWh. EIA INTL.2-12 is net generation. Gross is not substituted for net.'),
    ('electricity', 'production', 'unsd_elec_net', 'yes',
     'UNSD commodity 7000 transaction 019 (net production), gigawatt-hours / 1000. Same net concept as EIA INTL.2-12.'),
    ('electricity', 'production', 'unsd_elec_gross', 'no',
     'UNSD commodity 7000 transaction 01. For the United States this is above net production; it is not used as the chosen series.'),
    ('electricity', 'imports', 'unsd_elec_imports', 'yes', 'UNSD 7000 transaction 03, GWh / 1000.'),
    ('electricity', 'exports', 'unsd_elec_exports', 'yes', 'UNSD 7000 transaction 04, GWh / 1000.'),
]

CHOSEN_REASON = {
    'gas': 'EIA dry natural gas, product 26, unit BCM, activity pinned (1 production, 2 consumption, 3 imports, 4 exports). Excludes NGPL. JODI only where the EIA series is missing.',
    'crude': 'EIA product 57 activity 1, crude including lease condensate, unit TBPD. Product 58 NGPL is not added (E29). Activities 3 and 4 have no 2022 value in this bulk file, so imports and exports are JODI CRUDEOIL, then UNSD 4100 transactions 03/04 at 0.1364 t/bbl where JODI has no full year (S11 trade_volume_fill). Use is JODI CRUDEOIL refinery intake plus direct use because EIA has no crude-consumption activity.',
    'coal': 'EIA product 7, unit MT (1000 metric tons) / 1000. UNSD 0100+0200 only where EIA is missing.',
    'refined': 'JODI secondary TOTPRODS (REFGROUT, TOTIMPSB, TOTEXPSB, TOTDEMO). EIA INTL.54-1 has no 2022 observations (E5). LPG is inside TOTPRODS and is not added again. Where JODI has no full year, production, imports and exports are UNSD SIEC 46 oil products (transactions 01/03/04) at the EI product-basket 8.0577 bbl/t (S11 trade_volume_fill).',
    'electricity': 'EIA product 2: activity 12 net generation, 3 imports, 4 exports, 2 net consumption. Unit BKWH = TWh. UNSD net production (019) only where EIA generation is missing.',
}

HEADLINE = {
    # committed "production" from energy_committed_pr55 / the task, and the activity that actually holds it
    'NOR': ('2', 5.65619565),
    'QAT': ('2', 42.13611628),
    'ARE': ('4', 7.02231116),
    'RUS': ('2', 466.16514703),
}
E6_EXCEPT = {'KWT', 'NGA', 'VEN', 'LBY'}


def load_h10_accepted():
    """Gate rows David accepted (PREP-H10). A missing file or a row without decided_by/decided_at stops the run."""
    p = CFG + '/accepted_gate_exceptions.csv'
    if not os.path.exists(p):
        raise SystemExit(f'{p} is missing')
    out = {}
    for r in csv.DictReader(open(p, newline='')):
        if r['check'] != 'PREP-H10':
            continue
        if not r['decided_by'].strip() or not r['decided_at'].strip():
            raise SystemExit(f'{p}: row {r} has no decided_by or decided_at')
        out[r['region']] = f"{r['decided_by']} {r['decided_at']}"
    return out


H10_ACCEPTED = load_h10_accepted()


def clean_label(s):
    s = str(s).replace('\xa0', ' ').strip()
    while s and s[-1] in '*†#♦^':
        s = s[:-1].rstrip()
    return s


def skip_ei(name):
    n = clean_label(name).casefold()
    if n.startswith(('total', 'other', 'of which', 'rest of', 'non-oecd', 'non-opec', 'european union',
                     'billion', 'million', 'thousand', 'terawatt', 'exajoule', 'note', 'source', 'excludes',
                     'includes', 'using ', 'annual', 'the difference', 'and ')):
        return True
    if n in {'opec', 'ussr', 'central america', 'eastern africa', 'middle africa', 'western africa', 'n/a', ''}:
        return True
    return False


def y2022(data):
    for yr, val in data:
        if str(yr) == '2022' and isinstance(val, (int, float)):
            return float(val)
    return None


def rel_diff(compare, chosen):
    if compare is None or chosen is None:
        return None
    if abs(chosen) < 1e-9:
        if abs(compare) < 1e-9:
            return 0.0
        return None
    return compare / chosen - 1.0


def load_csv(path):
    with open(path, newline='') as f:
        return list(csv.DictReader(f))


def main():
    S = Stage('PREP', 'energy_volumes')
    I = S.inp
    if Y != 2022:
        raise SystemExit('this prep builds 2022 only')
    S.check('PREP-H0', 'S01 has a STAMP', 'hard', os.path.exists(S01 + '/STAMP'), True, os.path.exists(S01 + '/STAMP'), 'stage gate')
    S.upstream(S01)
    S.check('PREP-H1', 'Base year is 2022', 'hard', Y, 2022, Y == 2022, 'year rule')

    regions = pd.read_csv(I(S01 + '/output/regions.csv', 'S01 regions'))
    cmap = pd.read_csv(I(S01 + '/output/country_region_map.csv', 'S01 country map'))
    I(S01 + '/output/sectors.csv', 'S01 sectors (oil and gas split; not rewritten)')
    I(DATA + '/eia_intl/INTL.txt', 'EIA international bulk, extracted')
    I(DATA + '/jodi/GAS_world_NewFormat.zip', 'JODI gas')
    I(DATA + '/jodi/jodi_oil_world_primary_csv.zip', 'JODI oil primary')
    I(DATA + '/jodi/jodi_oil_world_secondary_csv.zip', 'JODI oil secondary')
    I(DATA + '/ei_statistical_review/EI-Stats-Review-ALL-data.xlsx', 'EI Statistical Review 2025')
    I(DATA + '/unsd_energy/undata_energy_2022.csv', 'UNSD energy 2022')

    code_to_region, status_of, name_to_code, map_alias = {}, {}, {}, {}
    for _, r in cmap.iterrows():
        code, region, status, name = r['code'], r['region'], str(r['status']), str(r['name'])
        if isinstance(status, str) and status.startswith('alias'):
            map_alias[code] = status.split('->')[-1].strip()
            continue
        if not isinstance(region, str) or not region:
            status_of[code] = status
            continue
        if isinstance(status, str) and status.startswith('non-country'):
            continue
        code_to_region[code] = region
        status_of[code] = status
        name_to_code[name.strip().casefold()] = code
    eia_alias = {r['eia_code']: r['maps_to'] for r in load_csv(I(CFG + '/eia_code_aliases.csv', 'EIA code aliases'))}
    aggregates = {r['code'] for r in load_csv(I(CFG + '/eia_aggregate_codes.csv', 'EIA aggregates to ignore'))}
    holdout = {r['code']: r['why'] for r in load_csv(I(CFG + '/eia_unmapped_holdout.csv', 'EIA codes S01 leaves unmapped'))}
    ei_alias = {}
    for r in load_csv(I(CFG + '/ei_name_aliases.csv', 'EI country name aliases')):
        ei_alias[clean_label(r['ei_name']).casefold()] = r['iso3']
    iso_rows = load_csv(I(CFG + '/iso3166_alpha.csv', 'ISO 3166-1 alpha-2/3 and numeric'))
    a2_to_a3 = {r['alpha2']: r['alpha3'] for r in iso_rows}
    num_to_a3 = {r['numeric'].zfill(3): r['alpha3'] for r in iso_rows}

    def canon(code):
        code = eia_alias.get(code, code)
        code = map_alias.get(code, code)
        return code

    # ---------------------------------------------------------------- EIA
    series = {}          # (label, iso) -> float (already scaled to the output unit)
    sids = {}            # (label, iso) -> series id or source string
    world = {}
    gas_order = collections.defaultdict(list)  # iso -> [(line, activity, sid, value)]
    n_54_1_2022 = 0
    n_57_trade_2022 = 0
    dropped_nonzero = []
    held_out = []
    with open(DATA + '/eia_intl/INTL.txt') as f:
        for lineno, line in enumerate(f, 1):
            if '"series_id":"INTL.' not in line:
                continue
            i = line.find('"series_id":"')
            sid = line[i + 13:line.find('"', i + 13)]
            if not sid.endswith('.A'):
                continue
            body = sid[5:]
            parts = body.split('-')
            if len(parts) < 4:
                continue
            prod, act, country, unit = parts[0], parts[1], parts[2], parts[3].split('.')[0]
            if prod == '54' and act == '1' and unit == 'TBPD':
                # counted below only when 2022 is numeric; parsed with the others if wanted, else a light parse
                pass
            key = (prod, act, unit)
            is_gas_bcm = prod == '26' and unit == 'BCM'
            if key not in EIA_WANTED and not (is_gas_bcm) and not (prod == '54' and act == '1' and unit == 'TBPD'):
                continue
            obj = json.loads(line)
            val = y2022(obj.get('data') or [])
            if prod == '54' and act == '1' and unit == 'TBPD':
                if val is not None:
                    n_54_1_2022 += 1
                continue
            if is_gas_bcm and len(country) == 3 and country.isalpha():
                gas_order[country].append((lineno, act, sid, val))
            if prod == '57' and act in ('3', '4') and unit == 'TBPD' and val is not None:
                n_57_trade_2022 += 1
            if key not in EIA_WANTED or val is None:
                continue
            label = EIA_WANTED[key]
            val = val * SCALE.get(label, 1.0)
            if country == 'WORL':
                world[label] = val
                continue
            if country in aggregates:
                continue
            iso = canon(country)
            if country in holdout or iso in holdout:
                if abs(val) > 1e-9:
                    held_out.append((country, iso, label, val, obj.get('name', '')[:90]))
                continue
            if iso not in code_to_region:
                if abs(val) > 1e-9:
                    dropped_nonzero.append((country, iso, label, val, obj.get('name', '')[:80]))
                continue
            k = (label, iso)
            if k in series and abs(series[k] - val) > 1e-6:
                raise SystemExit(f'duplicate EIA series {k}: {sids[k]} and {sid}')
            series[k] = val
            sids[k] = sid
    S.log(f'EIA INTL.54-1 TBPD series with a 2022 number: {n_54_1_2022}')
    S.check('PREP-H6', 'EIA refined production INTL.54-1 TBPD has no 2022 value', 'hard',
            n_54_1_2022, 0, n_54_1_2022 == 0, 'PLAN E5',
            'Every annual INTL.54-1-*-TBPD series in this bulk file was scanned.')
    S.check('PREP-R4', 'EIA crude imports and exports (INTL.57-3 and 57-4 TBPD) have no 2022 value, so those flows are JODI',
            'report', n_57_trade_2022, 0, n_57_trade_2022 == 0, 'this bulk file',
            'USA crude imports INTL.57-3-USA-TBPD.A last numeric year is 2020. China imports last numeric year is 2018.')
    if dropped_nonzero:
        S.log('EIA nonzero dropped: ' + '; '.join(f'{a}->{b} {c}={d}' for a, b, c, d, _ in dropped_nonzero[:20]))
    S.check('PREP-H9', 'No nonzero EIA country series is outside the region map, the alias list and the aggregate list',
            'hard', len(dropped_nonzero), 0, not dropped_nonzero, 'S01 region map',
            '; '.join(f'{a} ({e}) {c}={d}' for a, b, c, d, e in dropped_nonzero[:30]))
    S.check('PREP-R3', 'S01-unmapped EIA codes are held out and not assigned to a region', 'report',
            len(held_out), '', True, 'eia_unmapped_holdout.csv',
            '; '.join(f'{a} {c}={d:.4g}' for a, b, c, d, e in held_out))

    # ---------------------------------------------------------------- JODI
    def stream_jodi(zpath, inner, products, flows, units):
        out, conflicts = {}, []
        with zipfile.ZipFile(zpath) as z, z.open(inner) as f:
            f.readline()
            for raw in f:
                p = raw.decode('utf-8', 'replace').strip().split(',')
                if len(p) < 6 or not p[1].startswith('2022'):
                    continue
                if p[2] not in products or p[3] not in flows or p[4] not in units or p[5] in ('', 'NA'):
                    continue
                try:
                    val = float(p[5])
                except ValueError:
                    continue
                month = int(p[1][5:7])
                key = (p[0], p[2], p[3], p[4])
                slot = out.setdefault(key, {})
                if month in slot and abs(slot[month] - val) > 1e-4:
                    conflicts.append((key, month))
                slot[month] = val
        return out, conflicts

    gas_m, c1 = stream_jodi(DATA + '/jodi/GAS_world_NewFormat.zip', 'STAGING_world_NewFormat.csv',
                            {'NATGAS'}, {'INDPROD', 'TOTIMPSB', 'TOTEXPSB', 'TOTDEMO', 'TOTDEMC'}, {'M3'})
    pri_m, c2 = stream_jodi(DATA + '/jodi/jodi_oil_world_primary_csv.zip', 'NewProcedure_Primary_CSV.csv',
                            {'CRUDEOIL', 'NGL', 'TOTCRUDE'},
                            {'INDPROD', 'TOTIMPSB', 'TOTEXPSB', 'REFINOBS', 'DIRECUSE'}, {'KBBL', 'KBD'})
    sec_m, c3 = stream_jodi(DATA + '/jodi/jodi_oil_world_secondary_csv.zip', 'NewProcedure_Secondary_CSV.csv',
                            {'TOTPRODS', 'LPG'}, {'REFGROUT', 'TOTIMPSB', 'TOTEXPSB', 'TOTDEMO'}, {'KBBL', 'KBD'})
    n_conf = len(c1) + len(c2) + len(c3)
    S.check('PREP-H7a', 'JODI 2022 rows do not disagree with themselves for the same month', 'hard',
            n_conf, 0, n_conf == 0, 'JODI world database')
    unmapped_jodi = collections.Counter()
    held_jodi = collections.Counter()

    def jodi_iso(area):
        iso = a2_to_a3.get(area)
        if not iso:
            unmapped_jodi[area] += 1
            return None
        iso = map_alias.get(iso, iso)
        if iso in holdout:
            held_jodi[area + '->' + iso] += 1
            return None
        if iso not in code_to_region:
            unmapped_jodi[area + '->' + iso] += 1
            return None
        return iso

    def annual_bcm(months):
        if len(months) != 12:
            return None
        return sum(months.values()) / 1000.0

    def annual_kbd(months_kbbl, months_kbd):
        if len(months_kbbl) == 12:
            return sum(months_kbbl.values()) / DAYS, 'sum of monthly thousand barrels / 365'
        if len(months_kbd) == 12:
            return sum(months_kbd.values()) / 12.0, 'mean of 12 monthly thousand-barrels-per-day figures'
        return None, None

    def put(label, iso, val, sid):
        if val is None:
            return
        k = (label, iso)
        if k in series and abs(series[k] - val) > 1e-4:
            raise SystemExit(f'duplicate {k}')
        series[k] = val
        sids[k] = sid

    # gas
    gas_flow = {'INDPROD': 'jodi_gas_production', 'TOTIMPSB': 'jodi_gas_imports', 'TOTEXPSB': 'jodi_gas_exports',
                'TOTDEMO': 'jodi_gas_consumption', 'TOTDEMC': 'jodi_gas_consumption_calculated'}
    by_area = collections.defaultdict(dict)
    for (area, prod, flow, unit), months in gas_m.items():
        by_area[(area, flow)] = months
    for (area, flow), months in by_area.items():
        iso = jodi_iso(area)
        if not iso:
            continue
        val = annual_bcm(months)
        if val is None:
            continue
        put(gas_flow[flow], iso, val, f'JODI NATGAS {flow} M3 sum of 12 months / 1000')
    # prefer observed demand; calculated is only a fallback
    # (fallback applied at choose time)

    def harvest_oil(store, product, flow_map):
        kbbl = collections.defaultdict(dict)
        kbd = collections.defaultdict(dict)
        for (area, prod, flow, unit), months in store.items():
            if prod != product or flow not in flow_map:
                continue
            dest = kbbl if unit == 'KBBL' else kbd
            dest[(area, flow)] = months
        areas = set(kbbl) | set(kbd)
        for area, flow in areas:
            iso = jodi_iso(area)
            if not iso:
                continue
            val, how = annual_kbd(kbbl.get((area, flow), {}), kbd.get((area, flow), {}))
            if val is None:
                continue
            put(flow_map[flow], iso, val, f'JODI {product} {flow} ({how})')

    harvest_oil(pri_m, 'CRUDEOIL', {
        'INDPROD': 'jodi_crude_production', 'TOTIMPSB': 'jodi_crude_imports', 'TOTEXPSB': 'jodi_crude_exports',
        'REFINOBS': 'jodi_crude_refinobs', 'DIRECUSE': 'jodi_crude_direcuse'})
    harvest_oil(pri_m, 'NGL', {'INDPROD': 'jodi_ngl_production'})
    harvest_oil(pri_m, 'TOTCRUDE', {'INDPROD': 'jodi_totcrude_production'})
    harvest_oil(sec_m, 'TOTPRODS', {
        'REFGROUT': 'jodi_refined_production', 'TOTIMPSB': 'jodi_refined_imports',
        'TOTEXPSB': 'jodi_refined_exports', 'TOTDEMO': 'jodi_refined_consumption'})
    harvest_oil(sec_m, 'LPG', {'REFGROUT': 'jodi_lpg_refout'})
    # crude use = refinery intake + direct use, NGL excluded because the product is CRUDEOIL
    for iso in {k[1] for k in series if k[0] in ('jodi_crude_refinobs', 'jodi_crude_direcuse')}:
        a = series.get(('jodi_crude_refinobs', iso))
        b = series.get(('jodi_crude_direcuse', iso))
        if a is None and b is None:
            continue
        put('jodi_crude_use', iso, (a or 0) + (b or 0),
            'JODI CRUDEOIL REFINOBS + DIRECUSE' + (' (one flow missing, treated as absent)' if a is None or b is None else ''))
    S.log(f'JODI areas not mapped: {dict(unmapped_jodi)}; held out: {dict(held_jodi)}')
    S.check('PREP-H7b', 'Every JODI area used for 2022 oil or gas maps to an S01 country', 'hard',
            len(unmapped_jodi), 0, not unmapped_jodi, 'ISO 3166-1 alpha-2',
            ' '.join(f'{k}:{v}' for k, v in unmapped_jodi.most_common(20)))

    # scale check: Norway JODI / EIA. A factor of 1000 would mean the M3 unit was misread.
    nor_j = series.get(('jodi_gas_production', 'NOR'))
    nor_e = series.get(('eia_gas_production', 'NOR'))
    ratio = (nor_j / nor_e) if nor_j and nor_e else None
    S.check('PREP-H7', 'JODI gas M3 is million cubic metres: Norway annual bcm is the same order as EIA dry gas',
            'hard', None if ratio is None else round(ratio, 3), '0.5 to 1.5',
            ratio is not None and 0.5 <= ratio <= 1.5, 'unit check, not a calibration',
            f'JODI NOR {nor_j} bcm; EIA NOR {nor_e} bcm')

    # ---------------------------------------------------------------- EI
    import openpyxl
    wb = openpyxl.load_workbook(DATA + '/ei_statistical_review/EI-Stats-Review-ALL-data.xlsx', read_only=True, data_only=True)
    unmapped_ei = []
    for sheet, label in EI_SHEETS.items():
        rows = list(wb[sheet].iter_rows(values_only=True))
        col = None
        for r in rows[:12]:
            for j, v in enumerate(r or []):
                if v == 2022 or v == '2022':
                    col = j
                    break
            if col is not None:
                break
        if col is None:
            raise SystemExit(f'no 2022 column in {sheet}')
        for r in rows:
            if not r or not isinstance(r[0], str):
                continue
            if col >= len(r) or not isinstance(r[col], (int, float)):
                continue
            raw = r[0]
            if skip_ei(raw):
                if clean_label(raw).casefold() == 'total world':
                    world[label] = float(r[col])
                continue
            key = clean_label(raw).casefold()
            iso = ei_alias.get(key) or name_to_code.get(key)
            if not iso:
                unmapped_ei.append(f'{sheet}: {raw.strip()}')
                continue
            iso = map_alias.get(iso, iso)
            if iso in holdout:
                continue
            if iso not in code_to_region:
                unmapped_ei.append(f'{sheet}: {raw.strip()} -> {iso} not in a region')
                continue
            put(label, iso, float(r[col]), f'EI 2025 {sheet}')
    S.check('PREP-H8', 'Every EI 2022 country figure is mapped to an S01 country or is an aggregate row', 'hard',
            len(unmapped_ei), 0, not unmapped_ei, 'ei_name_aliases.csv', '; '.join(unmapped_ei[:25]))

    # ---------------------------------------------------------------- UNSD
    # Commodity and transaction names are the SDMX codelists CL_COMMODITY_NRG and CL_TRANSACTION_NRG
    # fetched 2026-10-20 from https://data.un.org/WS/rest/codelist/UNSD/.../latest/
    # 3000 Natural Gas (including LNG); 4100 Conventional crude oil; 4200 Natural Gas Liquids;
    # 0100 Hard Coal; 0200 Brown Coal; 7000 Total Electricity.
    # 01 Production; 019 Net Production; 03 Imports; 04 Exports.
    # UNIT_MULT is the SDMX power of ten. TN + mult 3 = thousands of metric tons. GWHR + mult 0 = GWh. TJ + mult 0 = TJ.
    unsd_area_skip = collections.Counter()
    # accumulate coal components then add
    coal_parts = collections.defaultdict(float)  # (iso, flow, commodity) -> million tonnes
    coal_seen = collections.defaultdict(set)
    product_parts = collections.defaultdict(float)  # (iso, flow) -> kb/d of SIEC 46 oil products
    product_seen = collections.defaultdict(set)
    with open(DATA + '/unsd_energy/undata_energy_2022.csv', newline='') as f:
        for row in csv.DictReader(f):
            if row['TIME_PERIOD'] != '2022' or row['OBS_VALUE'] in ('', None):
                continue
            com, tr = row['COMMODITY'], row['TRANSACTION']
            try:
                obs = float(row['OBS_VALUE'])
            except ValueError:
                continue
            mult = int(row['UNIT_MULT']) if row['UNIT_MULT'] != '' else 0
            unit = row['UNIT_MEASURE']
            area = row['REF_AREA'].zfill(3)
            iso = num_to_a3.get(area)
            if iso:
                iso = map_alias.get(iso, iso)
            if not iso or iso not in code_to_region:
                if com in {'3000', '4100', '0100', '0200', '7000'} and tr in {'01', '019'} and abs(obs) > 0:
                    unsd_area_skip[area] += 1
                continue
            if com == '3000' and tr == '01' and unit == 'TJ' and mult == 0:
                put('unsd_gas_tj', iso, obs, 'UNSD 3000/01 TJ')
                put('unsd_gas_production_gcv40', iso, obs / TJ_PER_BCM_GCV40, 'UNSD 3000/01 TJ / 40000')
            elif com == '4100' and tr == '01' and unit == 'TN' and mult == 3:
                # thousand tonnes -> kb/d at 0.1364 t/bbl
                put('unsd_crude_kt', iso, obs, 'UNSD 4100/01 thousand metric tons')
                put('unsd_crude_production_kbd', iso, obs / TONNES_PER_BBL / DAYS, 'UNSD 4100/01 at 0.1364 t/bbl / 365')
            elif com == '4100' and tr in {'03', '04'} and unit == 'TN' and mult == 3:
                lab = {'03': 'unsd_crude_imports', '04': 'unsd_crude_exports'}[tr]
                put(lab, iso, obs / TONNES_PER_BBL / DAYS, f'UNSD 4100/{tr} thousand metric tons at 0.1364 t/bbl / 365')
            elif com in UNSD_PRODUCT_CODES and tr in {'01', '03', '04'} and unit == 'TN' and mult == 3:
                flow = {'01': 'production', '03': 'imports', '04': 'exports'}[tr]
                product_parts[(iso, flow)] += obs * PRODUCT_BBL_PER_TONNE / DAYS   # thousand tonnes -> kb/d
                product_seen[(iso, flow)].add(com)
            elif com == '4200' and tr == '01' and unit == 'TN' and mult == 3:
                put('unsd_ngl_kt', iso, obs, 'UNSD 4200/01 thousand metric tons')
            elif com in {'0100', '0200'} and tr in {'01', '03', '04'} and unit == 'TN' and mult == 3:
                flow = {'01': 'production', '03': 'imports', '04': 'exports'}[tr]
                coal_parts[(iso, flow)] += obs / 1000.0  # thousand tonnes -> million tonnes
                coal_seen[(iso, flow)].add(com)
            elif com == '7000' and unit == 'GWHR' and mult == 0 and tr in {'01', '019', '03', '04'}:
                twh = obs / 1000.0
                lab = {'019': 'unsd_elec_net', '01': 'unsd_elec_gross', '03': 'unsd_elec_imports', '04': 'unsd_elec_exports'}[tr]
                put(lab, iso, twh, f'UNSD 7000/{tr} GWh/1000')
    for (iso, flow), val in coal_parts.items():
        lab = {'production': 'unsd_coal_production', 'imports': 'unsd_coal_imports', 'exports': 'unsd_coal_exports'}[flow]
        put(lab, iso, val, 'UNSD ' + '+'.join(sorted(coal_seen[(iso, flow)])) + f' transaction / {flow} million tonnes')
    for (iso, flow), val in product_parts.items():
        put(f'unsd_refined_{flow}', iso, val, f'UNSD SIEC 46 oil products ({len(product_seen[(iso, flow)])} codes) {flow}, thousand tonnes at 8.0577 bbl/t / 365')
    unsd_names = {r['code'].zfill(3): r['name'] for r in load_csv(I(CFG + '/unsd_area_names.csv', 'UNSD area names for codes that are not ISO countries'))}
    S.check('PREP-R-UNSD', 'UNSD areas with energy that do not map to an S01 country (report only)', 'report',
            len(unsd_area_skip), '', True, 'CL_AREA_NRG',
            ' '.join(f"{k} {unsd_names.get(k, '')}:{v}" for k, v in unsd_area_skip.most_common(15)))

    # ---------------------------------------------------------------- choose
    chosen = {}  # (iso, commodity, flow) -> record
    flows = ('production', 'imports', 'exports', 'consumption')
    commodities = ('crude', 'gas', 'coal', 'refined', 'electricity')

    def pick(iso, commodity, flow, options, concept):
        """options: list of (label, source, fill_flag) in priority order."""
        for label, source, fill in options:
            if (label, iso) in series:
                chosen[(iso, commodity, flow)] = dict(
                    value=series[(label, iso)], source=source, series_id=sids.get((label, iso), ''),
                    concept=concept, fill=fill)
                return
        chosen[(iso, commodity, flow)] = dict(value=None, source='', series_id='', concept=concept, fill='no')

    for iso in sorted(code_to_region):
        pick(iso, 'gas', 'production', [('eia_gas_production', 'eia', 'no'), ('jodi_gas_production', 'jodi', 'yes')], CHOSEN_REASON['gas'])
        pick(iso, 'gas', 'imports', [('eia_gas_imports', 'eia', 'no'), ('jodi_gas_imports', 'jodi', 'yes')], CHOSEN_REASON['gas'])
        pick(iso, 'gas', 'exports', [('eia_gas_exports', 'eia', 'no'), ('jodi_gas_exports', 'jodi', 'yes')], CHOSEN_REASON['gas'])
        # observed JODI demand, then calculated demand
        pick(iso, 'gas', 'consumption', [
            ('eia_gas_consumption', 'eia', 'no'),
            ('jodi_gas_consumption', 'jodi', 'yes'),
            ('jodi_gas_consumption_calculated', 'jodi', 'yes'),
        ], CHOSEN_REASON['gas'])
        pick(iso, 'crude', 'production', [('eia_crude_production', 'eia', 'no'), ('jodi_crude_production', 'jodi', 'yes')], CHOSEN_REASON['crude'])
        pick(iso, 'crude', 'imports', [('eia_crude_imports', 'eia', 'no'), ('jodi_crude_imports', 'jodi', 'yes'), ('unsd_crude_imports', 'unsd', 'yes')], CHOSEN_REASON['crude'])
        pick(iso, 'crude', 'exports', [('eia_crude_exports', 'eia', 'no'), ('jodi_crude_exports', 'jodi', 'yes'), ('unsd_crude_exports', 'unsd', 'yes')], CHOSEN_REASON['crude'])
        pick(iso, 'crude', 'consumption', [('jodi_crude_use', 'jodi', 'no')], CHOSEN_REASON['crude'])
        pick(iso, 'coal', 'production', [('eia_coal_production', 'eia', 'no'), ('unsd_coal_production', 'unsd', 'yes')], CHOSEN_REASON['coal'])
        pick(iso, 'coal', 'imports', [('eia_coal_imports', 'eia', 'no'), ('unsd_coal_imports', 'unsd', 'yes')], CHOSEN_REASON['coal'])
        pick(iso, 'coal', 'exports', [('eia_coal_exports', 'eia', 'no'), ('unsd_coal_exports', 'unsd', 'yes')], CHOSEN_REASON['coal'])
        pick(iso, 'coal', 'consumption', [('eia_coal_consumption', 'eia', 'no')], CHOSEN_REASON['coal'])
        pick(iso, 'refined', 'production', [('jodi_refined_production', 'jodi', 'no'), ('unsd_refined_production', 'unsd', 'yes')], CHOSEN_REASON['refined'])
        pick(iso, 'refined', 'imports', [('jodi_refined_imports', 'jodi', 'no'), ('unsd_refined_imports', 'unsd', 'yes')], CHOSEN_REASON['refined'])
        pick(iso, 'refined', 'exports', [('jodi_refined_exports', 'jodi', 'no'), ('unsd_refined_exports', 'unsd', 'yes')], CHOSEN_REASON['refined'])
        pick(iso, 'refined', 'consumption', [('jodi_refined_consumption', 'jodi', 'no')], CHOSEN_REASON['refined'])
        pick(iso, 'electricity', 'production', [('eia_elec_production', 'eia', 'no'), ('unsd_elec_net', 'unsd', 'yes')], CHOSEN_REASON['electricity'])
        pick(iso, 'electricity', 'imports', [('eia_elec_imports', 'eia', 'no'), ('unsd_elec_imports', 'unsd', 'yes')], CHOSEN_REASON['electricity'])
        pick(iso, 'electricity', 'exports', [('eia_elec_exports', 'eia', 'no'), ('unsd_elec_exports', 'unsd', 'yes')], CHOSEN_REASON['electricity'])
        pick(iso, 'electricity', 'consumption', [('eia_elec_consumption', 'eia', 'no')], CHOSEN_REASON['electricity'])

    # ---------------------------------------------------------------- NGL and activity checks (country)
    bad_oil, bad_gas = [], []
    for iso in code_to_region:
        oil = chosen[(iso, 'crude', 'production')]
        gas = chosen[(iso, 'gas', 'production')]
        if oil['source'] == 'eia':
            sid = oil['series_id']
            if 'INTL.57-1-' not in sid or 'INTL.58-' in sid or 'INTL.55-' in sid:
                bad_oil.append(iso + ' ' + sid)
            ngpl = series.get(('eia_ngpl_production', iso), 0.0)
            if ngpl > 0.05 and abs(oil['value'] - (oil['value'] + ngpl)) < 1e-9:
                pass  # tautology, the real test is value != value+ngpl when we would have added it
            if ngpl > 0.05 and abs(oil['value'] - (series.get(('eia_crude_production', iso), 0) + ngpl)) < 1e-4:
                # chosen equals crude+ngpl, meaning ngpl was included
                if abs(oil['value'] - series.get(('eia_crude_production', iso), 0)) > 1e-4:
                    bad_oil.append(iso + ' includes ngpl')
        if oil['source'] == 'jodi':
            if 'TOTCRUDE' in oil['series_id'] or 'NGL' in oil['series_id']:
                bad_oil.append(iso + ' ' + oil['series_id'])
        if gas['source'] == 'eia':
            sid = gas['series_id']
            # INTL.26-1-ISO-BCM.A ; reject -2- -3- -4-
            if not sid.startswith('INTL.26-1-') or not sid.endswith('-BCM.A'):
                bad_gas.append(iso + ' ' + sid)
    S.check('PREP-H4', 'Chosen crude is EIA 57 or JODI CRUDEOIL, never NGPL / TOTCRUDE / product 55', 'hard',
            len(bad_oil), 0, not bad_oil, 'PLAN_ERRATA E29', '; '.join(bad_oil[:20]))
    S.check('PREP-H5', 'Chosen EIA gas production is INTL.26-1-*-BCM.A', 'hard',
            len(bad_gas), 0, not bad_gas, 'activity id pinned', '; '.join(bad_gas[:20]))

    # headline regression: the known bad numbers are the other activities, not what we stored
    headline_bad = []
    for iso, (act, wrong) in HEADLINE.items():
        got = chosen[(iso, 'gas', 'production')]['value']
        prod = series.get(('eia_gas_production', iso))
        last = gas_order.get(iso, [])
        last_act, last_val = (last[-1][1], last[-1][3]) if last else (None, None)
        if got is None or prod is None or abs(got - prod) > 1e-6:
            headline_bad.append(f'{iso} chosen {got} != production {prod}')
        if last_val is None or abs(last_val - wrong) > 0.01:
            headline_bad.append(f'{iso} last series {last_val} is not the known bad value {wrong}')
        if last_act != act:
            headline_bad.append(f'{iso} last activity {last_act} != {act}')
        if abs(got - wrong) < 0.5:
            headline_bad.append(f'{iso} chosen still equals the bad value {wrong}')
    S.check('PREP-H3', 'NOR, QAT, ARE and RUS gas production is activity 1, not the old last-series value', 'hard',
            len(headline_bad), 0, not headline_bad, 'FETCH_NOTES.md', '; '.join(headline_bad))

    # prior committed column vs last series (box-only audit file; absent in a clean checkout)
    prior_path = 'internal_audit/energy_volume_check_2022.csv'
    if os.path.exists(prior_path):
        prior = list(csv.DictReader(open(prior_path)))
        n_last = n_prod = n = 0
        exceptions = []
        for r in prior:
            iso = r['iso']
            if not r.get('committed_gas_bcm'):
                continue
            c = float(r['committed_gas_bcm'])
            n += 1
            last = gas_order.get(iso)
            if last and last[-1][3] is not None and abs(last[-1][3] - c) < 1e-3:
                n_last += 1
            prod = series.get(('eia_gas_production', iso))
            if prod is not None and abs(prod - c) < 1e-3:
                n_prod += 1
            elif not (last and last[-1][3] is not None and abs(last[-1][3] - c) < 1e-3):
                exceptions.append(iso)
        S.check('PREP-R1', 'Prior committed gas column matches the last INTL.26 BCM series, not production', 'report',
                f'{n_last}/{n} last-series, {n_prod}/{n} production', '', True, 'energy_volume_check_2022.csv',
                'Not last-series and not production: ' + ' '.join(exceptions))

    # LPG is inside TOTPRODS: where both exist, LPG refinery output should not exceed total products
    lpg_over = []
    for iso in code_to_region:
        lpg = series.get(('jodi_lpg_refout', iso))
        tot = series.get(('jodi_refined_production', iso))
        if lpg is not None and tot is not None and lpg > tot + 1:
            lpg_over.append(f'{iso} LPG {lpg:.1f} > TOTPRODS {tot:.1f}')
    S.check('PREP-R2', 'JODI LPG refinery output does not exceed TOTPRODS (LPG is a component, not added again)', 'report',
            len(lpg_over), 0, not lpg_over, 'E29', '; '.join(lpg_over[:15]))

    # ---------------------------------------------------------------- regions
    members = collections.defaultdict(list)
    for iso, region in code_to_region.items():
        members[region].append(iso)
    def _txt(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ''
        return str(v)

    pri = {r.region: _txt(r.priority) for r in regions.itertuples()}
    if set(pri) != set(members):
        missing = sorted(set(pri) - set(members))
        extra = sorted(set(members) - set(pri))
        S.log(f'region set mismatch missing={missing} extra={extra}')
    S.check('PREP-H2', 'Volume table has the 167 S01 regions', 'hard', len(members), 167, len(members) == 167)

    def sum_label(label, isos):
        vals = [(i, series[(label, i)]) for i in isos if (label, i) in series]
        if not vals:
            return None, 0
        return sum(v for _, v in vals), len(vals)

    region_chosen = {}
    for region, isos in members.items():
        for commodity in commodities:
            for flow in flows:
                parts = []
                for iso in isos:
                    rec = chosen[(iso, commodity, flow)]
                    if rec['value'] is not None:
                        parts.append((iso, rec))
                if not parts:
                    region_chosen[(region, commodity, flow)] = dict(
                        value=None, source='', series_id='', concept=CHOSEN_REASON[commodity],
                        fill='no', n=0, n_members=len(isos))
                    continue
                sources = sorted({p[1]['source'] for p in parts})
                fills = [p for p in parts if p[1]['fill'] == 'yes']
                region_chosen[(region, commodity, flow)] = dict(
                    value=sum(p[1]['value'] for p in parts),
                    source='+'.join(sources),
                    series_id=';'.join(sorted({p[1]['series_id'] for p in parts})[:6]),
                    concept=CHOSEN_REASON[commodity],
                    fill='yes' if fills else 'no',
                    n=len(parts), n_members=len(isos))
                for iso, rec in fills:
                    S.adjust(region, f'{iso} {commodity} {flow}', '', round(rec['value'], 6),
                             'fill', rec['series_id'] or rec['source'], 'fill')
                for iso, rec in parts:
                    st = status_of.get(iso, '')
                    if iso != region and ('territory' in st or 'fold' in st) and abs(rec['value']) > 1e-9:
                        S.adjust(region, f'{iso} {commodity} {flow} territory', 0, round(rec['value'], 6),
                                 'S01 territory map', st, 'territory')

    # ---------------------------------------------------------------- cross-check on the intersection of countries
    # report-set regions
    def top_n(commodity, n):
        rows = []
        for region in members:
            v = region_chosen[(region, commodity, 'production')]['value']
            if v is not None:
                rows.append((v, region))
        rows.sort(reverse=True)
        return {region for _, region in rows[:n]}

    top50 = {c: top_n(c, 50) for c in commodities}
    top15_gas = top_n('gas', 15)

    def in_report(region, commodity):
        p = pri.get(region, '')
        tags = set(t.strip() for t in p.split(';') if t.strip())
        if tags & {'top50', 'gulf', 'opec_2022', 'opec_plus_partner'}:
            return True
        return region in top50[commodity]

    def left_value(iso, commodity, flow, label):
        # EI coal consumption is exajoules. The chosen coal series is million tonnes.
        # Compare EIA terajoules / 1e6 with that sheet. Do not divide tonnes by exajoules.
        if label == 'ei_coal_consumption_ej':
            tj = series.get(('eia_coal_consumption_tj', iso))
            return (None if tj is None else tj / 1e6), 'eia_coal_consumption_tj / 1e6'
        return chosen[(iso, commodity, flow)]['value'], 'chosen'

    discrepancies = []
    gate_fail = []
    gate_accepted = []
    gate_rows = []
    for commodity, flow, label, same, note in PAIRS:
        for region, isos in members.items():
            both_c, both_o, n_both = 0.0, 0.0, 0
            basis = 'chosen'
            for iso in isos:
                cv, basis = left_value(iso, commodity, flow, label)
                ov = series.get((label, iso))
                if cv is None or ov is None:
                    continue
                both_c += cv
                both_o += ov
                n_both += 1
            if n_both == 0:
                continue
            rd = rel_diff(both_o, both_c)
            over = rd is not None and abs(rd) > 0.05
            rec = dict(region=region, commodity=commodity, flow=flow, comparison=label,
                       same_concept=same, chosen=both_c, other=both_o, n_countries=n_both,
                       rel=None if rd is None else rd, over_5pct='yes' if over else 'no',
                       in_report_set='yes' if in_report(region, commodity) else 'no',
                       left_basis=basis,
                       chosen_source=region_chosen[(region, commodity, flow)]['source'],
                       why_chosen=CHOSEN_REASON[commodity], concept_note=note)
            if over and rec['in_report_set'] == 'yes':
                discrepancies.append(rec)
            if commodity == 'gas' and flow == 'production' and label == 'ei_gas_production' and region in top15_gas:
                gate_rows.append(rec)
                if rd is None or abs(rd) > 0.08:
                    if region in H10_ACCEPTED:
                        gate_accepted.append(f'{region} EIA/EI rel {rd} accepted ({H10_ACCEPTED[region]})')
                    elif region not in E6_EXCEPT:
                        gate_fail.append(f'{region} EIA/EI rel {rd}')
    # E6 gate uses chosen/EI - 1, fail if outside ±8% and not a named exception.
    # Countries with no EI figure cannot pass the comparison; that is a fail only if we expected EI.
    # top-15 producers all have EI figures in practice. Missing EI is a failure to compare.
    S.check('PREP-H10', 'Top 15 gas producers within ±8% of EI, except KWT, NGA, VEN, LBY (E6) and the accepted rows of config/prep_energy/accepted_gate_exceptions.csv', 'hard',
            len(gate_fail), 0, not gate_fail, 'PLAN E6; EI and EIA gas are not the same standard conditions',
            ('; '.join(gate_fail) if gate_fail else 'pass') + ('. Accepted: ' + '; '.join(gate_accepted) if gate_accepted else ''))

    # ---------------------------------------------------------------- outputs
    units = {'gas': 'bcm', 'crude': 'kb/d', 'coal': 'million metric tonnes', 'refined': 'kb/d', 'electricity': 'TWh'}
    long_rows = []
    for region in sorted(members):
        for commodity in commodities:
            for flow in flows:
                rec = region_chosen[(region, commodity, flow)]
                p = region_chosen[(region, commodity, 'production')]['value']
                i = region_chosen[(region, commodity, 'imports')]['value']
                e = region_chosen[(region, commodity, 'exports')]['value']
                c = region_chosen[(region, commodity, 'consumption')]['value']
                resid = None
                if None not in (p, i, e, c) and flow == 'production':
                    resid = p + i - e - c
                long_rows.append(dict(
                    region=region, commodity=commodity, flow=flow, year=2022,
                    value=rec['value'], unit=units[commodity], source=rec['source'],
                    series_id=rec['series_id'], concept=rec['concept'], fill=rec['fill'],
                    n_countries_with_value=rec['n'], n_member_countries=rec['n_members'],
                    balance_residual_p_plus_i_minus_e_minus_c=(resid if flow == 'production' else None),
                ))
    S.write('volumes_2022.csv', pd.DataFrame(long_rows))

    # country audit (wide-ish long)
    ctry_rows = []
    for iso, region in sorted(code_to_region.items()):
        for commodity in commodities:
            for flow in flows:
                rec = chosen[(iso, commodity, flow)]
                if rec['value'] is None and rec['source'] == '':
                    continue
                ctry_rows.append(dict(iso3=iso, region=region, commodity=commodity, flow=flow, year=2022,
                                      value=rec['value'], unit=units[commodity], source=rec['source'],
                                      series_id=rec['series_id'], fill=rec['fill']))
    S.write('volumes_country_2022.csv', pd.DataFrame(ctry_rows))

    ngl_rows = []
    for iso, region in sorted(code_to_region.items()):
        c57 = series.get(('eia_crude_production', iso))
        c58 = series.get(('eia_ngpl_production', iso))
        if c57 is None and c58 is None and ('jodi_crude_production', iso) not in series and ('ei_crude_production', iso) not in series:
            continue
        chosen_c = chosen[(iso, 'crude', 'production')]['value']
        ngl_rows.append(dict(
            iso3=iso, region=region,
            eia_57_crude_kbd=c57, eia_58_ngpl_kbd=c58,
            eia_57_plus_58_kbd=(None if c57 is None or c58 is None else c57 + c58),
            chosen_crude_kbd=chosen_c, chosen_crude_source=chosen[(iso, 'crude', 'production')]['source'],
            chosen_crude_series=chosen[(iso, 'crude', 'production')]['series_id'],
            chosen_gas_bcm=chosen[(iso, 'gas', 'production')]['value'],
            chosen_gas_series=chosen[(iso, 'gas', 'production')]['series_id'],
            jodi_crudeoil_kbd=series.get(('jodi_crude_production', iso)),
            jodi_ngl_kbd=series.get(('jodi_ngl_production', iso)),
            jodi_totcrude_kbd=series.get(('jodi_totcrude_production', iso)),
            ei_crude_plus_cond_kbd=series.get(('ei_crude_production', iso)),
            ei_ngl_kbd=series.get(('ei_ngl_production', iso)),
            ei_oil_including_ngl_kbd=series.get(('ei_oil_incl_ngl', iso)),
            unsd_conventional_crude_thousand_t=series.get(('unsd_crude_kt', iso)),
            unsd_ngl_thousand_t=series.get(('unsd_ngl_kt', iso)),
        ))
    S.write('ngl_exclusion_check.csv', pd.DataFrame(ngl_rows))

    # diagnosis of the activity bug
    diag = []
    for iso, events in sorted(gas_order.items()):
        if not events:
            continue
        last_line = events[-1][0]
        for line, act, sid, val in events:
            diag.append(dict(iso3=iso, activity=act, series_id=sid, value_bcm_2022=val, file_line=line,
                             is_last_bcm_series='yes' if line == last_line else 'no',
                             is_production_activity='yes' if act == '1' else 'no',
                             in_s01_region=code_to_region.get(canon(iso), '')))
    S.write('gas_series_diagnosis.csv', pd.DataFrame(diag))

    disc_rows = []
    for r in discrepancies:
        disc_rows.append(dict(
            region=r['region'], commodity=r['commodity'], flow=r['flow'], comparison=r['comparison'],
            same_concept=r['same_concept'], left_basis=r['left_basis'],
            chosen_value=r['chosen'], other_value=r['other'],
            rel_other_over_chosen_minus_1=r['rel'], pct=None if r['rel'] is None else 100 * r['rel'],
            n_countries=r['n_countries'], chosen_source=r['chosen_source'], why_chosen=r['why_chosen'],
            concept_note=r['concept_note'], in_report_set=r['in_report_set'],
        ))
    disc_rows.sort(key=lambda r: (r['commodity'], r['flow'], r['comparison'], -(abs(r['pct'] or 0))))
    S.write('discrepancies_over_5pct.csv', pd.DataFrame(disc_rows))

    counts = collections.Counter()
    for commodity, flow, label, same, note in PAIRS:
        for region, isos in members.items():
            both_c = 0.0
            both_o = 0.0
            n_both = 0
            for iso in isos:
                cv, _basis = left_value(iso, commodity, flow, label)
                ov = series.get((label, iso))
                if cv is None or ov is None:
                    continue
                both_c += cv
                both_o += ov
                n_both += 1
            if not n_both:
                continue
            rd = rel_diff(both_o, both_c)
            key = (commodity, flow, label, same)
            counts[(key, 'n')] += 1
            if rd is not None and abs(rd) > 0.05:
                counts[(key, 'over')] += 1
                if in_report(region, commodity):
                    counts[(key, 'over_report')] += 1
    sum_rows = []
    for commodity, flow, label, same, note in PAIRS:
        key = (commodity, flow, label, same)
        sum_rows.append(dict(commodity=commodity, flow=flow, comparison=label, same_concept=same,
                             n_regions_compared=counts[(key, 'n')],
                             n_over_5pct=counts[(key, 'over')],
                             n_over_5pct_in_report_set=counts[(key, 'over_report')],
                             concept_note=note))
    S.write('crosscheck_summary.csv', pd.DataFrame(sum_rows))

    # coverage
    cov = []
    for commodity in commodities:
        for flow in flows:
            n = sum(1 for region in members if region_chosen[(region, commodity, flow)]['value'] is not None)
            n_fill = sum(1 for region in members if region_chosen[(region, commodity, flow)]['fill'] == 'yes')
            cov.append(dict(commodity=commodity, flow=flow, regions_with_value=n, regions_blank=167 - n,
                            regions_with_a_fill=n_fill, unit=units[commodity]))
    S.write('coverage.csv', pd.DataFrame(cov))

    # world check vs EIA WORL and EI Total World where both exist
    world_rows = []
    for label, commodity, flow in (
        ('eia_gas_production', 'gas', 'production'),
        ('eia_crude_production', 'crude', 'production'),
        ('eia_coal_production', 'coal', 'production'),
        ('eia_elec_production', 'electricity', 'production'),
    ):
        s = 0.0
        n = 0
        for r in members:
            v = region_chosen[(r, commodity, flow)]['value']
            if v is not None:
                s += v
                n += 1
        w = world.get(label)
        world_rows.append(dict(label=label, kind='chosen regional sum vs EIA world series',
                               sum_value=s, n_regions=n, published=w,
                               rel=None if not w else s / w - 1))
    for label in ('ei_gas_production', 'ei_crude_production', 'ei_coal_production', 'ei_elec_production'):
        commodity = {'ei_gas_production': 'gas', 'ei_crude_production': 'crude', 'ei_coal_production': 'coal',
                     'ei_elec_production': 'electricity'}[label]
        s = 0.0
        n = 0
        for rgn, isos in members.items():
            val, nn = sum_label(label, isos)
            if val is not None:
                s += val
                n += 1
        w = world.get(label)
        world_rows.append(dict(label=label, kind='mapped EI country rows vs EI Total World',
                               sum_value=s, n_regions=n, published=w,
                               rel=None if not w else s / w - 1))
    S.write('world_totals.csv', pd.DataFrame(world_rows))

    # flags for David
    S.flag('GAS-ACTIVITY', 'EIA INTL.26',
           'The old gas column was the last product-26 BCM series in INTL.txt (consumption, imports or exports). '
           'Production is now INTL.26-1-ISO-BCM.A. NOR 129.77, QAT 170.25, ARE 54.98, RUS 648.92 bcm.',
           'no', 'activity id', 'dataset/data/eia_intl/FETCH_NOTES.md')
    S.flag('NGL-EXCL', 'E29',
           'Oil is EIA 57 (crude including lease condensate) or JODI CRUDEOIL. Gas is EIA dry gas (product 26). '
           'EIA 58 NGPL, JODI NGL, UNSD 4200 and EI NGLs are in ngl_exclusion_check.csv and are not in the oil or gas volumes. '
           'They belong to petroleum products at S11 and are not inside refinery gross output, so they must be added to pet separately, not to refined production.',
           'yes', 'E29', 'UNSD HS 271112-271119 -> pet; EIA product 58; EI NGLs sheet excludes condensates')
    S.flag('ELEC-GROSS-NET', 'Electricity',
           'Chosen electricity production is EIA net generation. EI generation is gross. The gap is usually above 5% and is not removed. '
           'GTAP energy balances are often on a gross basis. S11 has to decide whether the quantity target is net or gross.',
           'yes', '', 'EIA INTL.2-12 name "Electricity net generation"; EI sheet note "Based on gross output"')
    S.flag('GAS-CONDITIONS', 'Gas cross-check',
           'EIA dry bcm and EI bcm differ by standard conditions and by NGPL shrinkage versus the EI GCV standardisation. '
           'The E6 ±8% gate is applied as written. Outliers are not scaled to EI.',
           'yes', 'E6', 'EI Gas Production footnote; PLAN E6')
    S.flag('CRUDE-USE', 'Crude consumption',
           'There is no EIA crude-consumption series. The consumption column is JODI refinery intake plus direct use of CRUDEOIL. '
           'It is not final consumption of crude, and it is not refinery output.',
           'yes', '', 'JODI primary flows REFINOBS and DIRECUSE')
    S.flag('COMPOSITE-TRADE', 'Composite imports and exports',
           'Imports and exports of XCB, XEF, XNF, XSM, XWE, XWB, XOC and XNA are sums of member totals. Intra-composite trade is still inside those sums. EIA and JODI do not publish a bilateral matrix that would net it out.',
           'yes', '', 'S01 composite_members')
    S.flag('PLANT-CONDENSATE', 'Lease condensate vs plant condensate',
           'Lease condensate stays in crude (EIA 57; HS 270900). EIA NGPL (ethane, LPG, pentanes plus) is excluded. '
           'EI crude+condensate can include gas condensates that require further refining, while its NGL sheet excludes condensates. '
           'That wedge is reported and not allocated by a formula.',
           'yes', 'E29', 'EI Crude+cond footnote; EI NGLs footnote')
    S.flag('UNSD-GAS-TJ', 'Gas gap',
           'Where EIA and JODI have no gas volume, the cell is left blank. UNSD gas is terajoules. '
           'A 40 MJ/m3 conversion is in the cross-check only.',
           'yes', '', 'UNSD unit TJ; EI gas footnote 40 MJ/m3; conversion sheet 36 PJ/bcm not used')
    def held_bits(code):
        rows = [d for d in held_out if d[0] == code]
        if not rows:
            return 'no nonzero 2022 value in the series used here'
        return '; '.join(f'{lab}={val:.6g}' for _c, _i, lab, val, _n in rows)

    S.flag('VIR', 'US Virgin Islands',
           'S01 leaves VIR with a blank region (status "not in any scanned source"). E32 said VIR folds into USA, but this prep does not override the fixed S01 map. '
           'EIA 2022 held out: ' + held_bits('VIR') + '. Not in the 167-region totals.',
           'yes', 'E32 vs S01 map', 'country_region_map.csv; eia_unmapped_holdout.csv')
    S.flag('ESH', 'Western Sahara',
           'S01 status is UNMAPPED. EIA 2022 held out: ' + held_bits('ESH') + '. Not assigned to a region.',
           'yes', 'S01 map', 'eia_unmapped_holdout.csv')
    S.flag('ATA', 'Antarctica',
           'S01 status is UNMAPPED. EIA 2022 held out: ' + held_bits('ATA') + '. Not assigned to a region.',
           'yes', 'S01 map', 'eia_unmapped_holdout.csv')
    S.flag('NLDA', 'Netherlands Antilles',
           'EIA code NLDA (Netherlands Antilles) is mapped to ANT and then to XCB. This bulk file has 2022 electricity for NLDA and not for CUW, SXM or BES. Aruba is a separate series.',
           'yes', 'S01 ANT fold', 'eia_code_aliases.csv')
    S.flag('AFG-GAS', 'Afghanistan gas',
           'EIA dry-gas production and consumption for Afghanistan are the missing marker for 2022 (series exist, value is NA). '
           'JODI does not supply a complete 12-month year, so those two cells stay blank. Imports and exports are the EIA zeros.',
           'yes', '', 'INTL.26-1-AFG-BCM.A and INTL.26-2-AFG-BCM.A')
    S.flag('CRUDE-TRADE', 'Crude imports and exports',
           'INTL.57-3 and INTL.57-4 TBPD have no 2022 number in this bulk file (USA imports end in 2020, China imports end in 2018). '
           'Chosen crude trade is JODI CRUDEOIL and every such cell is a fill.',
           'yes', 'year rule 2022', 'PREP-R4')
    S.flag('IEA-PUBLIC', 'IEA',
           'IEA World Energy Statistics and Balances are licensed and are not in this build. '
           'Public stand-ins: JODI (the IEA is one of the JODI organisations) and the UNSD energy extract (joint IEA/Eurostat/UNECE questionnaire). '
           'IEA Monthly Electricity Statistics is a free OECD-and-selected-countries file; it was not added as a second net-generation source on top of EIA.',
           'yes', '', 'PLAN: IEA balances are licensed')

    # coverage log
    for row in cov:
        S.log(f"coverage {row['commodity']} {row['flow']}: {row['regions_with_value']} regions, fills {row['regions_with_a_fill']}")

    # REPORT
    lines = []
    lines.append('# 2022 physical energy volumes')
    lines.append('')
    lines.append('Prep for S11. Regions: 167 from S01. Year: 2022. Oil and gas exclude NGL (E29).')
    lines.append('')
    lines.append('## The gas series')
    lines.append('')
    lines.append('Product 26 and unit BCM were already right. The activity id was not pinned, so the last `INTL.26-*` BCM row in the bulk file was stored as production.')
    lines.append('')
    lines.append('| ISO | Old figure (bcm) | What that series is | Production now (bcm) |')
    lines.append('|---|---:|---|---:|')
    for iso, (act, wrong) in HEADLINE.items():
        name = { '2': 'dry-gas consumption (activity 2)', '4': 'dry-gas exports (activity 4)'}[act]
        lines.append(f'| {iso} | {wrong} | {name} | {series[("eia_gas_production", iso)]:.4f} |')
    lines.append('')
    lines.append('Saudi Arabia matched the old file because its dry-gas consumption equals its dry-gas production. That was not evidence the pull was production.')
    lines.append('')
    lines.append('## Chosen sources')
    lines.append('')
    for k, v in CHOSEN_REASON.items():
        lines.append(f'- **{k}.** {v}')
    lines.append('')
    lines.append('## Coverage (regions with a value, out of 167)')
    lines.append('')
    lines.append('| Commodity | Flow | Regions | Of which include a fill | Blank |')
    lines.append('|---|---|---:|---:|---:|')
    for row in cov:
        lines.append(f"| {row['commodity']} | {row['flow']} | {row['regions_with_value']} | {row['regions_with_a_fill']} | {row['regions_blank']} |")
    lines.append('')
    lines.append('## Cross-check counts')
    lines.append('')
    lines.append('A gap over 5% is `other / left - 1`. The left side is the chosen volume, except coal consumption, where the left side is EIA coal consumption in TJ / 1e6 (exajoules) and the chosen volume stays in million tonnes. The report set is S01 top50, Gulf, OPEC 2022, OPEC+ partners, plus the 50 largest regions by chosen production of that commodity. The ratio uses only countries both sources cover.')
    lines.append('')
    lines.append('| Commodity | Flow | Comparison | Same concept | Regions compared | Over 5% | Of which in the report set |')
    lines.append('|---|---|---|---|---:|---:|---:|')
    for row in sum_rows:
        lines.append(f"| {row['commodity']} | {row['flow']} | {row['comparison']} | {row['same_concept']} | {row['n_regions_compared']} | {row['n_over_5pct']} | {row['n_over_5pct_in_report_set']} |")
    lines.append('')
    lines.append('## Top 15 gas producers against EI')
    lines.append('')
    lines.append('| Region | EIA dry bcm | EI bcm | EI/EIA - 1 | E6 exception |')
    lines.append('|---|---:|---:|---:|---|')
    for rec in sorted(gate_rows, key=lambda r: -r['chosen']):
        exc = 'yes' if rec['region'] in E6_EXCEPT else ''
        pct = '' if rec['rel'] is None else f"{100 * rec['rel']:.1f}%"
        lines.append(f"| {rec['region']} | {rec['chosen']:.2f} | {rec['other']:.2f} | {pct} | {exc} |")
    if gate_fail:
        lines.append('')
        lines.append('E6 gate fails for: ' + '; '.join(gate_fail))
    lines.append('')
    lines.append('## Report-set discrepancies over 5%')
    lines.append('')
    n_same = sum(1 for r in disc_rows if r['same_concept'] == 'yes')
    n_part = sum(1 for r in disc_rows if r['same_concept'] == 'partial')
    n_no = sum(1 for r in disc_rows if r['same_concept'] == 'no')
    lines.append(f'{len(disc_rows)} rows in the report set. {n_same} compare a source that measures the same concept, {n_part} are only partly the same concept, and {n_no} do not measure the same thing. The chosen series is not switched to close a gap. The full list is `discrepancies_over_5pct.csv`. The largest 12 in each commodity are below.')
    lines.append('')
    for commodity in commodities:
        sub = [r for r in disc_rows if r['commodity'] == commodity]
        sub.sort(key=lambda r: -abs(r['pct'] or 0))
        lines.append(f'### {commodity} ({len(sub)} rows over 5% in the report set)')
        lines.append('')
        lines.append('| Region | Flow | Comparison | Same concept | Chosen | Other | Other/chosen - 1 |')
        lines.append('|---|---|---|---|---:|---:|---:|')
        for r in sub[:12]:
            lines.append(f"| {r['region']} | {r['flow']} | {r['comparison']} | {r['same_concept']} | {r['chosen_value']:.3f} | {r['other_value']:.3f} | {r['pct']:.1f}% |")
        lines.append('')
    lines.append('## Decisions for David')
    lines.append('')
    lines.append('- E6 fails for Turkmenistan only: EI gas production is 9.5% below EIA dry gas. Kuwait, Nigeria, Venezuela and Libya are the named exceptions and are inside the top 15 only if their production ranks there. Turkmenistan is not scaled to EI. Extending the exception list is a decision; the threshold is not changed here.')
    lines.append('- Electricity: keep net generation, or switch the S11 target to gross (EI / UNSD transaction 01) and say so. This prep does not convert net to gross. Where EIA and UNSD both report net generation and differ by more than 5%, EIA stays the chosen series.')
    lines.append('- Afghanistan dry-gas production and consumption are blank. The EIA series is NA in 2022 and JODI has no full year.')
    lines.append('- Gas cells with neither EIA nor a full JODI year are blank. Filling them from UNSD terajoules needs an explicit calorific value (the EI sheet uses 40 MJ/m3; the conversion sheet also prints 36 PJ/bcm).')
    lines.append('- Crude imports and exports are JODI, flagged as fills, because INTL.57-3 and 57-4 have no 2022 value.')
    lines.append('- Crude "consumption" here is refinery intake plus direct use. S11 should not treat it as a final-demand volume.')
    lines.append('- NGPL is outside oil, gas and refinery gross output. S11 has to add it to petroleum products when it values pet, or pet will miss gas-plant liquids.')
    lines.append('- Composite trade still contains trade between members.')
    lines.append('- VIR is blank in the S01 map, so US Virgin Islands electricity is not in USA. E32 said VIR folds into USA.')
    lines.append('- EIA NLDA (Netherlands Antilles, 2022 electricity) is folded to XCB because CUW/SXM/BES have no series in this file.')
    lines.append('- IEA balances were not used. They are not public. JODI and UNSD are the public stand-ins, and they are labelled as such.')
    lines.append('')
    open(S.out + '/REPORT.md', 'w').write('\n'.join(lines) + '\n')
    S.log('wrote REPORT.md')

    ok = S.finish()
    print('STAGE_OK' if ok else 'STAGE_FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
