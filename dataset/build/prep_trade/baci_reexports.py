"""Remove re-exports from BACI HS17 2022 for the merchandise-trade prep.

National statistics supply shares. They are not copied on as dollar levels:
BACI is FOB, mirror-reconciled and HS2017, in thousand USD. Hong Kong is in
thousand HKD, Singapore in million SGD, the Netherlands in million EUR.

Hubs, in this order (finer published grain first, so a later hub's import
shares see the earlier retained-import reduction):

- HKG. C&SD Trade-IDDS 2022. Re-export share = re-exports / total exports by
  consignment country and HKHS2. Origin mix is origin x consignment, all
  commodities, applied uniformly across HKHS2 (the API refuses origin crossed
  with HS for re-exports). NESOI and the combined Micronesia+Palau code are
  not mapped onto real countries.
- NLD. CBS 85429NED, 2022JJ00, cross-border goods. Re-export share =
  wederuitvoer / (wederuitvoer + Dutch product) by partner and SITC section.
  Outgoing quasi-transit (doorvoer) is not removed and is not in the
  denominator. An HS6 is adjusted only when every SITC Rev.4 code in the UNSD
  HS2017 correlation sits in that one section. Origin is the same-HS6 BACI
  import share.
- SGP. SingStat M451521 total exports and M451501 domestic exports, 2022
  monthly, summed. Re-export share = (total - domestic) / total by partner,
  all goods, applied uniformly across HS6. Origin is the same-HS6 BACI import
  share.

Funding, for every hub: the re-export value taken off the hub's export of an
HS6 is limited to what the named origin exported to the hub in that same HS6.
Any excess stays on the hub and is flagged. Nothing is rescaled to a target,
and no missing share is treated as 0 or as 1.

BEL, ARE and PAN are not adjusted. No official bilateral re-export file was
verified for them.

The stage-(b2) cap of hub exports at domestic output is not applied. This
prep does not read stage b2.
"""
import csv
import json
import os
import re
import unicodedata
from collections import defaultdict

import duckdb
import openpyxl

from common import ART, CACHE, MANIFEST_BYTES, MANIFEST_SHA, REPO, S01, load_region_map, sha256

RAW = os.path.join(CACHE, 'raw')
OUT = os.path.join(ART, 'baci')
CFG = os.path.join(os.path.dirname(__file__), 'config')
OVERRIDES = os.path.join(CFG, 'partner_overrides.csv')
COUNTRIES = os.path.join(RAW, 'ref', 'countries.json')
HS_SITC = os.path.join(RAW, 'ref', 'HS2017toSITC4.xlsx')
BACI_ZIP = os.path.join(RAW, 'BACI_HS17_V202601.zip')
BACI_CSV = os.path.join(RAW, 'baci', 'BACI_HS17_Y2022_V202601.csv')
BACI_CC = os.path.join(RAW, 'baci', 'country_codes_V202601.csv')

# Published HK codes that are not one economy. Not allocated to a region.
HK_NOT_ECONOMY = {f'X{c}' for c in 'ABCDEFGH'} | {'FM'}

HUBS = ('HKG', 'NLD', 'SGP')
NOT_ADJUSTED = ('BEL', 'ARE', 'PAN')

SOURCE = {
    'HKG': 'HK-CSD-TradeIDDS-2022',
    'NLD': 'CBS-85429NED-2022JJ00',
    'SGP': 'SingStat-M451521-M451501-2022',
}
METHOD = {
    'HKG': 'rx/tx by consignment x HKHS2; origin mix all commodities x consignment, uniform across HS2; same-HS6 import cap',
    'NLD': 'wederuitvoer/(wederuitvoer+Dutch product) by partner x SITC section; doorvoer excluded; HS6 only if one SITC section; origin = same-HS6 BACI import share',
    'SGP': '(total-domestic)/total by partner, all goods, uniform across HS6; origin = same-HS6 BACI import share',
}
FILLS = {
    'HKG': 'FILL-HS2-UNIFORM;FILL-ORIGIN-ALL-COMMODITIES;MARGIN-IN-GOODS;CAP-SAME-HS6',
    'NLD': 'FILL-ORIGIN-IMPORT-SHARE;DOORVOER-EXCLUDED;HS-SECTION-GATE;MARGIN-IN-GOODS;CAP-SAME-HS6',
    'SGP': 'FILL-PARTNER-UNIFORM-HS6;FILL-ORIGIN-IMPORT-SHARE;MARGIN-IN-GOODS;CAP-SAME-HS6',
}


def norm(s):
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.upper().replace('&', ' AND ').replace("'", '')
    s = re.sub(r'[^A-Z0-9]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def load_overrides():
    out = defaultdict(dict)
    with open(OVERRIDES) as f:
        for r in csv.DictReader(f):
            out[r['source']][r['key']] = r['iso3']
    return out


def load_iso2_to_iso3():
    countries = json.load(open(COUNTRIES))
    iso2 = {}
    names = {}
    ambiguous = {}
    for c in countries:
        iso2[c['cca2']] = c['cca3']
        labels = [c['name']['common'], c['name']['official']]
        for alt in c.get('altSpellings') or []:
            if len(alt) <= 3 and alt.isalpha() and alt.isupper():
                continue
            labels.append(alt)
        for lab in labels:
            key = norm(lab)
            if not key:
                continue
            names.setdefault(key, set()).add(c['cca3'])
    clean = {}
    for key, isos in names.items():
        if len(isos) == 1:
            clean[key] = next(iter(isos))
        else:
            ambiguous[key] = sorted(isos)
    return iso2, clean, ambiguous


def english_name_to_iso3(name, names, overrides):
    if name in overrides:
        return overrides[name], 'override'
    key = norm(name)
    if key in names:
        return names[key], 'name'
    return '', 'unmatched'


def region_of(iso3, iso_to_region):
    return iso_to_region.get(iso3, '')


def hk_figure(row):
    return int(str(row['figure']).replace(',', ''))


def load_hk_shares(con, iso2, iso_to_region, checks):
    """Return nothing. Register hk_share(dest, hs2, share) and hk_origin weights."""
    def add(cid, kind, desc, value, threshold, passed):
        checks.append(dict(id=cid, kind=kind, desc=desc, value=str(value),
                           threshold=str(threshold), passed=bool(passed)))

    totals = json.load(open(os.path.join(RAW, 'hk', 'totals.json')))
    published = {k: int(str(totals[k]).replace(',', ''))
                 for k in ('imports', 'domestic_exports', 'reexports', 'total_exports')}
    add('PREP-A-HK-IDENTITY', 'hard',
        "HK published domestic exports + re-exports = total exports (HK$ '000)",
        f"{published['domestic_exports']} + {published['reexports']} = "
        f"{published['domestic_exports'] + published['reexports']}",
        published['total_exports'],
        published['domestic_exports'] + published['reexports'] == published['total_exports'])

    def cells(path, code_field):
        data = json.load(open(path))
        acc = defaultdict(int)
        dup = 0
        seen = set()
        for row in data:
            unit = row.get('unitEN', '')
            if unit and unit != "HK$ '000":
                raise SystemExit(f'unexpected HK unit {unit} in {path}')
            if str(row.get('period')) != '2022':
                raise SystemExit(f'unexpected HK period in {path}')
            key = (row['cc'], row.get('co', ''), str(row.get(code_field, '')).zfill(2) if code_field == 'code' else '')
            if code_field == 'code':
                key = (row['cc'], str(row['code']).zfill(2))
            else:
                key = (row['co'], row['cc'])
            if key in seen:
                dup += 1
            seen.add(key)
            acc[key] += hk_figure(row)
        return acc, dup, len(data)

    tx, tx_dup, tx_n = cells(os.path.join(RAW, 'hk', 'tx_hs2.json'), 'code')
    rx, rx_dup, rx_n = cells(os.path.join(RAW, 'hk', 'rx_hs2.json'), 'code')
    dx_path = os.path.join(RAW, 'hk', 'dx_hs2.json')
    if os.path.exists(dx_path):
        dx, dx_dup, dx_n = cells(dx_path, 'code')
    else:
        dx, dx_dup, dx_n = {}, 0, 0
    od, od_dup, od_n = cells(os.path.join(RAW, 'hk', 'rx_od.json'), 'co')
    add('PREP-A-HK-DUP', 'hard', 'HK API responses have no duplicate classification cells',
        f'tx {tx_dup} rx {rx_dup} dx {dx_dup} origin {od_dup}', 0,
        tx_dup == rx_dup == dx_dup == od_dup == 0)

    def grand(acc, idx):
        return sum(v for k, v in acc.items())

    # Trade-IDDS: adjustments are put into the cumulative total only, and the
    # footnote says parts need not equal that total. Chapter cells are not
    # rescaled onto the cumulative total. A gap above 20% means the extract
    # is not the chapter table (for example a double count), which is a hard fail.
    def chapter_gap(acc, published_value, cid, label):
        got = grand(acc, 0)
        gap = got - published_value
        rel = abs(gap) / published_value if published_value else 1
        add(cid, 'hard',
            f"Sum of consignment x HKHS2 {label} is within 20% of the published cumulative total (HK$ '000). Not rescaled.",
            f'chapters {got}; published {published_value}; gap {gap}',
            'absolute gap / published <= 0.20',
            rel <= 0.20)
    chapter_gap(tx, published['total_exports'], 'PREP-A-HK-TX', 'total exports')
    chapter_gap(rx, published['reexports'], 'PREP-A-HK-RX', 're-exports')
    if dx:
        got = grand(dx, 0)
        add('PREP-A-HK-DX', 'report',
            "Sum of consignment x HKHS2 domestic exports versus the published cumulative total (HK$ '000). Not rescaled; the share uses re-exports / total exports.",
            f'chapters {got}; published {published["domestic_exports"]}; gap {got - published["domestic_exports"]}',
            'report only; cumulative-total adjustments sit in this small residual', True)
    else:
        add('PREP-A-HK-DX', 'report',
            'Domestic-export chapter file was not required for the share and is absent. Implied domestic = total exports - re-exports at each cell.',
            'absent', 'share = re-exports / total exports', True)
    od_sum = grand(od, 0)
    od_gap = od_sum - published['reexports']
    od_rel = abs(od_gap) / published['reexports']
    add('PREP-A-HK-OD', 'hard',
        "Sum of origin x consignment re-exports is within 0.1% of the published re-export total (HK$ '000). Not rescaled.",
        f'matrix {od_sum}; published {published["reexports"]}; gap {od_gap}',
        'absolute gap / published <= 0.001',
        od_rel <= 0.001)

    keys = set(tx) | set(rx) | set(dx)
    bad = []
    bad_value = 0
    n_round = 0
    good_rows = []
    for cc, hs2 in keys:
        t, r = tx.get((cc, hs2), 0), rx.get((cc, hs2), 0)
        d = dx.get((cc, hs2), 0) if dx else t - r
        # HK$ '000 is an integer. A gap of 1 is the published rounding.
        gap = abs(t - (r + d)) if dx else 0
        if gap == 1:
            n_round += 1
        if (dx and gap > 1) or r > t or t < 0 or r < 0:
            bad.append((cc, hs2, t, r, d))
            bad_value += gap
            continue
        if t <= 0:
            continue
        share = r / t
        if share < 0 or share > 1:
            bad.append((cc, hs2, t, r, d))
            continue
        good_rows.append((cc, hs2, t, r, d, share))
    add('PREP-A-HK-CELL', 'hard',
        'Every consignment x HKHS2 cell has re-exports <= total exports, and total exports = domestic + re-exports within 1 HK$ thousand',
        f'{len(bad)} cells beyond rounding; {n_round} cells off by 1; absolute gap {bad_value}',
        '0 cells beyond a gap of 1', not bad)

    # Map consignment and origin codes onto regions. Unmapped codes stay aside.
    unknown = sorted({cc for cc, _ in keys} - set(iso2) - HK_NOT_ECONOMY)
    add('PREP-A-HK-CODES', 'hard',
        'Every HK country code is ISO alpha-2, a listed non-economy code, or absent from the extract',
        ','.join(unknown) if unknown else 'none', 'none', not unknown)

    # Region x HS2: sum countries, then share. Unmapped consignments are not in a region.
    reg = defaultdict(lambda: [0, 0, 0])  # tx, rx, dx
    unmapped_tx = 0
    for cc, hs2, t, r, d, _share in good_rows:
        if cc in HK_NOT_ECONOMY or cc not in iso2:
            unmapped_tx += t
            continue
        region = region_of(iso2[cc], iso_to_region)
        if not region:
            unmapped_tx += t
            continue
        cell = reg[(region, hs2)]
        cell[0] += t
        cell[1] += r
        cell[2] += d
    share_rows = []
    for (region, hs2), (t, r, d) in reg.items():
        if t <= 0 or r < 0 or r > t:
            continue
        share_rows.append((region, hs2, t, r, d, r / t))
    con.execute('CREATE TABLE hk_share(dest VARCHAR, hs2 VARCHAR, tx BIGINT, rx BIGINT, dx BIGINT, share DOUBLE)')
    con.executemany('INSERT INTO hk_share VALUES (?, ?, ?, ?, ?, ?)', share_rows)

    # Origin weights by destination region. Unmapped origins stay in the denominator.
    w_mapped = defaultdict(int)
    w_unmapped = defaultdict(int)
    unmapped_origin_value = 0
    unmapped_dest_value = 0
    for (co, cc), v in od.items():
        dest_iso = '' if cc in HK_NOT_ECONOMY or cc not in iso2 else iso2[cc]
        dest = region_of(dest_iso, iso_to_region) if dest_iso else ''
        if not dest:
            unmapped_dest_value += v
            continue
        orig_iso = '' if co in HK_NOT_ECONOMY or co not in iso2 else iso2[co]
        orig = region_of(orig_iso, iso_to_region) if orig_iso else ''
        if not orig or orig == 'HKG':
            w_unmapped[dest] += v
            unmapped_origin_value += v
            continue
        w_mapped[(orig, dest)] += v
    dest_total = defaultdict(int)
    for (orig, dest), v in w_mapped.items():
        dest_total[dest] += v
    for dest, v in w_unmapped.items():
        dest_total[dest] += v
    origin_rows = []
    for (orig, dest), v in w_mapped.items():
        if dest_total[dest] <= 0:
            continue
        origin_rows.append((orig, dest, v, dest_total[dest]))
    unmapped_rows = [(dest, v, dest_total[dest]) for dest, v in w_unmapped.items() if dest_total[dest] > 0]
    con.execute('CREATE TABLE hk_origin(origin VARCHAR, dest VARCHAR, weight BIGINT, dest_total BIGINT)')
    con.executemany('INSERT INTO hk_origin VALUES (?, ?, ?, ?)', origin_rows)
    con.execute('CREATE TABLE hk_origin_unmapped(dest VARCHAR, weight BIGINT, dest_total BIGINT)')
    con.executemany('INSERT INTO hk_origin_unmapped VALUES (?, ?, ?)', unmapped_rows)
    add('PREP-A-HK-UNMAPPED', 'report',
        "HK value left off the region map (HK$ '000): consignment x HS2 total exports, origin of re-exports, destination of re-exports",
        f'hs2_tx {unmapped_tx}; origin {unmapped_origin_value}; dest {unmapped_dest_value}',
        'reported, not allocated to a region', True)
    print(f'HK shares {len(share_rows)} region-HS2; origin pairs {len(origin_rows)}; '
          f'api rows tx {tx_n} rx {rx_n} dx {dx_n} od {od_n}', flush=True)


def annual_sg(row):
    total = 0.0
    n = 0
    for col in row['columns']:
        if not str(col.get('key', '')).startswith('2022 '):
            continue
        n += 1
        v = col.get('value')
        if v in ('', '-', 'na', 'NA', None):
            continue
        total += float(v)
    return total, n


def load_sg_shares(con, names, overrides, iso_to_region, checks):
    def add(cid, kind, desc, value, threshold, passed):
        checks.append(dict(id=cid, kind=kind, desc=desc, value=str(value),
                           threshold=str(threshold), passed=bool(passed)))

    tx_rows = json.load(open(os.path.join(RAW, 'sg', 'M451521.json')))['Data']['row']
    dx_rows = json.load(open(os.path.join(RAW, 'sg', 'M451501.json')))['Data']['row']
    dx_by_no = {r['seriesNo']: r for r in dx_rows}
    leaves = [r for r in tx_rows if r['seriesNo'].count('.') == 2]
    total_row = next(r for r in tx_rows if r['seriesNo'] == '1')
    if total_row['uoM'] != 'Million Dollars':
        raise SystemExit(f"unexpected SG unit {total_row['uoM']}")
    leaf_sum = 0.0
    region_tx = defaultdict(float)
    region_dx = defaultdict(float)
    unmatched = []
    unmapped = []
    incomplete = []
    for r in leaves:
        tx, nmo = annual_sg(r)
        dxr = dx_by_no.get(r['seriesNo'])
        if dxr is None or dxr['rowText'] != r['rowText']:
            raise SystemExit(f"M451501 has no matching row for {r['seriesNo']} {r['rowText']}")
        dx, _n = annual_sg(dxr)
        leaf_sum += tx
        if nmo != 12:
            incomplete.append(r['rowText'])
        iso, how = english_name_to_iso3(r['rowText'], names, overrides['SG'])
        if not iso:
            unmatched.append((r['rowText'], tx, dx))
            continue
        region = region_of(iso, iso_to_region)
        if not region:
            unmapped.append((r['rowText'], iso, tx, dx))
            continue
        region_tx[region] += tx
        region_dx[region] += dx
    published = annual_sg(total_row)[0]
    gap = abs(leaf_sum - published)
    add('PREP-A-SG-TOTAL', 'hard',
        'Sum of SingStat market rows equals Total All Markets (million SGD, monthly values summed)',
        f'leaves {leaf_sum:.4f} vs total {published:.4f} gap {gap:.4f}',
        'gap <= 2 (published at 0.1 million SGD per month)',
        gap <= 2.0)
    add('PREP-A-SG-MONTHS', 'hard', 'Every market row has 12 months of 2022',
        ','.join(incomplete) if incomplete else '12', '12', not incomplete)
    share_rows = []
    invalid = []
    for region in sorted(set(region_tx) | set(region_dx)):
        t, d = region_tx[region], region_dx[region]
        if t <= 0:
            continue
        if d < 0 or d > t + 1e-6:
            invalid.append((region, t, d))
            continue
        rx = t - d
        share_rows.append((region, t, d, rx, rx / t))
    add('PREP-A-SG-SHARE', 'hard', 'Domestic exports do not exceed total exports for any mapped region',
        str(invalid) if invalid else 'ok', 'none', not invalid)
    con.execute('CREATE TABLE sg_share(dest VARCHAR, tx DOUBLE, dx DOUBLE, rx DOUBLE, share DOUBLE)')
    con.executemany('INSERT INTO sg_share VALUES (?, ?, ?, ?, ?)', share_rows)
    # Diagnostic commodity sections. Not crossed with partners, not used to adjust.
    comm = json.load(open(os.path.join(RAW, 'sg', 'M451001.json')))['Data']['row']
    diag = []
    for r in comm:
        if r['seriesNo'] in ('3', '4', '5') or (r['seriesNo'].count('.') == 1 and r['seriesNo'].split('.')[0] in ('3', '4', '5')):
            diag.append((r['seriesNo'], r['rowText'], r.get('uoM', ''), annual_sg(r)[0]))
    con.execute('CREATE TABLE sg_commodity_diag(series VARCHAR, label VARCHAR, unit VARCHAR, value_2022 DOUBLE)')
    con.executemany('INSERT INTO sg_commodity_diag VALUES (?, ?, ?, ?)', diag)
    open(os.path.join(OUT, 'sg_unmatched.csv'), 'w', newline='').write('')
    with open(os.path.join(OUT, 'sg_unmatched.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['row_text', 'total_exports_million_sgd', 'domestic_exports_million_sgd', 'note'])
        for name, tx, dx in sorted(unmatched, key=lambda x: -x[1]):
            note = 'partner aggregate' if name.startswith('Other Markets') else 'no ISO match; not allocated'
            w.writerow([name, f'{tx:.4f}', f'{dx:.4f}', note])
        for name, iso, tx, dx in sorted(unmapped, key=lambda x: -x[2]):
            w.writerow([name, f'{tx:.4f}', f'{dx:.4f}', f'ISO {iso} has no S01 region; not allocated'])
    add('PREP-A-SG-UNMATCHED', 'report',
        'SingStat partner rows not applied to a region (million SGD of total exports)',
        f"unmatched {sum(t for _, t, _ in unmatched):.1f}; no-region {sum(t for *_, t, _d in unmapped):.1f}",
        'reported in sg_unmatched.csv; not spread over other partners', True)
    print(f'SG region shares {len(share_rows)}; unmatched rows {len(unmatched)}; no-region {len(unmapped)}', flush=True)


def load_nl_shares(con, iso2, overrides, iso_to_region, checks):
    def add(cid, kind, desc, value, threshold, passed):
        checks.append(dict(id=cid, kind=kind, desc=desc, value=str(value),
                           threshold=str(threshold), passed=bool(passed)))

    typed = json.load(open(os.path.join(RAW, 'cbs', 'typed_2022.json')))['value']
    landen = json.load(open(os.path.join(RAW, 'cbs', 'landen.json')))['value']
    sitc_dim = json.load(open(os.path.join(RAW, 'cbs', 'sitc.json')))['value']
    land_by = {r['Key']: r for r in landen}
    sitc_by = {r['Key']: r for r in sitc_dim}
    section_of = {}
    for key, r in sitc_by.items():
        title = (r.get('Description') or r.get('Title') or '').strip()
        if key == 'T001082' or title.lower().startswith('totaal'):
            section_of[key] = 'TOTAL'
            continue
        digit = title[0] if title and title[0].isdigit() else ''
        section_of[key] = digit
    missing_section = [k for k, s in section_of.items() if s == '']
    add('PREP-A-NL-SITC', 'hard', 'Every CBS SITC key is the total or a numbered section',
        ','.join(missing_section) if missing_section else 'ok', 'none', not missing_section)

    world = [r for r in typed if r['Landen'] == 'T001047' and r['SITC'] == 'T001082']
    if len(world) != 1:
        raise SystemExit(f'expected one CBS world total row, got {len(world)}')
    w = world[0]
    parts = w['Wederuitvoerwaarde_4'] + w['UitvoerwaardeProductNL_5'] + w['DoorvoerwaardeUitgaand_6']
    # The table is published in whole million EUR, so the parts can miss the total by one unit.
    add('PREP-A-NL-IDENTITY', 'hard',
        'CBS world total exports = Dutch product + re-exports + outgoing quasi-transit (million EUR)',
        f"{w['UitvoerwaardeProductNL_5']} + {w['Wederuitvoerwaarde_4']} + {w['DoorvoerwaardeUitgaand_6']} = {parts}",
        f"{w['TotaleUitvoerwaarde_3']} (gap at most 1, the published unit)",
        abs(parts - w['TotaleUitvoerwaarde_3']) <= 1)

    # HS6 -> one SITC section, or blank if the correlation disagrees.
    wb = openpyxl.load_workbook(HS_SITC, read_only=True, data_only=True)
    ws = wb['Correlation HS17-SITC4']
    linked = defaultdict(set)
    n_links = 0
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i < 2:
            continue
        hs, sitc = row[0], row[1]
        if hs is None or sitc is None:
            continue
        hs6 = str(hs).strip().zfill(6)
        sitc_s = str(sitc).strip()
        if not sitc_s or not sitc_s[0].isdigit():
            linked[hs6].add('BAD')
        else:
            linked[hs6].add(sitc_s[0])
        n_links += 1
    wb.close()
    hs_rows = []
    n_amb = 0
    for hs6, sections in linked.items():
        if len(sections) == 1 and 'BAD' not in sections:
            hs_rows.append((hs6, next(iter(sections))))
        else:
            n_amb += 1
    con.execute('CREATE TABLE hs_section(hs6 VARCHAR, section VARCHAR)')
    con.executemany('INSERT INTO hs_section VALUES (?, ?)', hs_rows)
    add('PREP-A-NL-HS', 'report',
        'HS2017 codes with a single SITC section in the UNSD correlation (others are not adjusted)',
        f'links {n_links}; unambiguous {len(hs_rows)}; ambiguous {n_amb}',
        'ambiguous HS6 stay at the BACI value', True)

    alpha_of = {}
    for key, r in land_by.items():
        m = re.search(r'GEO code alfa2:\s*([A-Z0-9]{2})', r.get('Description') or '')
        if m:
            alpha_of[key] = m.group(1)
    # Aggregate value weights by region x section. Unmapped partners are reported.
    # Category groups 1, 2 and 4 are the world, the continents and EU / non-EU.
    # They repeat the country rows. Group 11 and the EU "not specified" rows are
    # residuals, not countries, and stay unmapped.
    AGGREGATE_GROUPS = {1, 2, 4}
    weights = defaultdict(lambda: [0.0, 0.0])  # reexport, dutch
    unmapped_rows = []
    bad_cells = []
    country_tx = 0.0
    for r in typed:
        if r['Perioden'] != '2022JJ00':
            continue
        land = land_by.get(r['Landen'])
        if land is None or land['CategoryGroupID'] in AGGREGATE_GROUPS:
            continue
        if r['SITC'] == 'T001082':
            country_tx += float(r['TotaleUitvoerwaarde_3'] or 0)
        section = section_of.get(r['SITC'], '')
        if section in ('', 'TOTAL'):
            continue
        alpha = alpha_of.get(r['Landen'], '')
        iso = overrides['CBS'].get(alpha) or iso2.get(alpha, '')
        region = region_of(iso, iso_to_region) if iso else ''
        rx = float(r['Wederuitvoerwaarde_4'] or 0)
        dutch = float(r['UitvoerwaardeProductNL_5'] or 0)
        door = float(r['DoorvoerwaardeUitgaand_6'] or 0)
        total = float(r['TotaleUitvoerwaarde_3'] or 0)
        # Integer million EUR: a gap of 1 is the published rounding, not a break.
        if abs((rx + dutch + door) - total) > 1:
            bad_cells.append((r['Landen'], section, total, rx + dutch + door))
        if not region or region == 'NLD':
            if rx or dutch:
                unmapped_rows.append((land['Title'], alpha or r['Landen'], section, rx, dutch))
            continue
        weights[(region, section)][0] += rx
        weights[(region, section)][1] += dutch
    add('PREP-A-NL-CELL', 'hard',
        'Partner x section: Dutch product + re-exports + outgoing quasi-transit = total exports, within 1 million EUR',
        len(bad_cells), 0, not bad_cells)
    share_rows = []
    invalid = []
    for (region, section), (rx, dutch) in weights.items():
        denom = rx + dutch
        if denom <= 0:
            continue
        if rx < 0 or dutch < 0 or rx > denom:
            invalid.append((region, section, rx, dutch))
            continue
        share_rows.append((region, section, rx, dutch, denom, rx / denom))
    add('PREP-A-NL-SHARE', 'hard', 'Re-export shares lie in [0, 1]',
        str(invalid[:5]) if invalid else 'ok', 'none', not invalid)
    con.execute('''CREATE TABLE nl_share(
        dest VARCHAR, section VARCHAR, rx DOUBLE, dutch DOUBLE, denom DOUBLE, share DOUBLE)''')
    con.executemany('INSERT INTO nl_share VALUES (?, ?, ?, ?, ?, ?)', share_rows)
    with open(os.path.join(OUT, 'nl_unmapped.csv'), 'w', newline='') as f:
        wri = csv.writer(f)
        wri.writerow(['cbs_title', 'code', 'sitc_section', 'reexports_million_eur', 'dutch_product_million_eur'])
        for row in sorted(unmapped_rows, key=lambda x: -x[3]):
            wri.writerow(row)
    add('PREP-A-NL-UNMAPPED', 'report',
        'CBS partner x section re-exports with no S01 region (million EUR), not allocated',
        f'{sum(r[3] for r in unmapped_rows):.1f} across {len(unmapped_rows)} rows',
        'reported in nl_unmapped.csv', True)
    add('PREP-A-NL-RESIDUAL', 'report',
        'World total exports minus the sum of non-aggregate partners (million EUR). The gap is the unpublished partner residual inside the continent totals; it is not spread.',
        f'world {w["TotaleUitvoerwaarde_3"]}; partners {country_tx:.0f}; gap {w["TotaleUitvoerwaarde_3"] - country_tx:.0f}',
        'not allocated', True)
    print(f'NL region-section shares {len(share_rows)}; unmapped rows {len(unmapped_rows)}; '
          f'HS6 unambiguous {len(hs_rows)}', flush=True)


def load_baci(con, iso_to_region):
    con.execute(f"""
        CREATE TABLE cc AS
        SELECT CAST(country_code AS INTEGER) AS code, country_iso3 AS iso3, country_name AS name
        FROM read_csv('{BACI_CC}', header=true, all_varchar=true)
    """)
    con.execute('CREATE TABLE reg(iso3 VARCHAR, region VARCHAR)')
    con.executemany('INSERT INTO reg VALUES (?, ?)', list(iso_to_region.items()))
    # i and j are numeric in the file. k is already 6 characters (checked) but padded anyway.
    con.execute(f"""
        CREATE TABLE raw AS
        SELECT lpad(CAST(k AS VARCHAR), 6, '0') AS hs6,
               CAST(i AS INTEGER) AS exp_code,
               CAST(j AS INTEGER) AS imp_code,
               CAST(v AS DOUBLE) AS value,
               CAST(q AS DOUBLE) AS qty
        FROM read_csv('{BACI_CSV}', header=true, all_varchar=true)
        WHERE CAST(t AS INTEGER) = 2022
    """)
    con.execute("""
        CREATE TABLE mapped AS
        SELECT r.hs6, r.value, r.qty,
               ce.iso3 AS exp_iso, ci.iso3 AS imp_iso,
               re.region AS exp_region, ri.region AS imp_region
        FROM raw r
        LEFT JOIN cc ce ON ce.code = r.exp_code
        LEFT JOIN cc ci ON ci.code = r.imp_code
        LEFT JOIN reg re ON re.iso3 = ce.iso3
        LEFT JOIN reg ri ON ri.iso3 = ci.iso3
    """)
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
    con.execute("""
        CREATE TABLE unmapped AS
        SELECT COALESCE(ce.iso3, 'code:' || CAST(r.exp_code AS VARCHAR)) AS exp_iso,
               COALESCE(ci.iso3, 'code:' || CAST(r.imp_code AS VARCHAR)) AS imp_iso,
               r.hs6, SUM(r.value) AS value
        FROM raw r
        LEFT JOIN cc ce ON ce.code = r.exp_code
        LEFT JOIN cc ci ON ci.code = r.imp_code
        LEFT JOIN reg re ON re.iso3 = ce.iso3
        LEFT JOIN reg ri ON ri.iso3 = ci.iso3
        WHERE re.region IS NULL OR ri.region IS NULL
        GROUP BY 1, 2, 3
    """)


def apply_hub(con, hub, identified_sql, weight_sql, weight_cols):
    """weight_sql yields origin, dest, hs6, weight, base where claim = identified * weight/base.

    For a destination-only origin mix, hs6 in the weight query is the identified hs6
    (the SQL joins it). weight_cols documents the grain.
    """
    con.execute('DROP TABLE IF EXISTS identified')
    con.execute('DROP TABLE IF EXISTS claim')
    con.execute('DROP TABLE IF EXISTS scale')
    con.execute('DROP TABLE IF EXISTS funded')
    con.execute('DROP TABLE IF EXISTS delta')
    con.execute(f'CREATE TABLE identified AS {identified_sql}')
    con.execute(f'CREATE TABLE claim AS {weight_sql}')
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
        LEFT JOIN flows m
          ON m.exporter = c.origin AND m.importer = '{hub}' AND m.hs6 = c.hs6
        GROUP BY c.origin, c.hs6, m.value
    """)
    con.execute("""
        CREATE TABLE funded AS
        SELECT c.dest, c.hs6, c.origin, c.claim * s.scale AS funded, s.scale, c.claim
        FROM claim c
        JOIN scale s USING (origin, hs6)
        WHERE c.claim * s.scale > 0
    """)
    # Net change of each bilateral cell from this hub.
    con.execute(f"""
        CREATE TABLE delta AS
        SELECT exporter, importer, hs6, SUM(d_value) AS d_value, '{hub}' AS hub
        FROM (
            SELECT '{hub}' AS exporter, dest AS importer, hs6, -SUM(funded) AS d_value
            FROM funded GROUP BY dest, hs6
            UNION ALL
            SELECT origin AS exporter, '{hub}' AS importer, hs6, -SUM(funded) AS d_value
            FROM funded GROUP BY origin, hs6
            UNION ALL
            SELECT origin AS exporter, dest AS importer, hs6, SUM(funded) AS d_value
            FROM funded WHERE origin <> dest GROUP BY origin, dest, hs6
        )
        GROUP BY 1, 2, 3
    """)
    con.execute(f"""
        INSERT INTO ledger
        SELECT '{hub}' AS hub,
               CASE
                 WHEN d.exporter = '{hub}' THEN 'hub_export_removal'
                 WHEN d.importer = '{hub}' THEN 'hub_import_reduction'
                 ELSE 'origin_export_addition'
               END AS leg,
               d.exporter, d.importer, d.hs6,
               COALESCE(f.value, 0) AS before,
               d.d_value AS delta,
               COALESCE(f.value, 0) + d.d_value AS after,
               '{SOURCE[hub]}' AS source_id,
               '{METHOD[hub]}' AS method,
               '{FILLS[hub]}' AS fill_flags
        FROM delta d
        LEFT JOIN flows f USING (exporter, importer, hs6)
    """)
    con.execute(f"""
        INSERT INTO intra_add
        SELECT '{hub}' AS hub, origin AS region, hs6, SUM(funded) AS value
        FROM funded
        WHERE origin = dest
        GROUP BY origin, hs6
    """)
    con.execute("""
        UPDATE flows
        SET value = flows.value + delta.d_value,
            qty = NULL,
            qty_ok = FALSE
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
    # Funding components stay for the artifact, one hub at a time appended.
    con.execute(f"""
        INSERT INTO funding
        SELECT '{hub}' AS hub, origin, dest, hs6, funded, claim, scale
        FROM funded
    """)
    stats = con.execute(f"""
        SELECT
          (SELECT COALESCE(SUM(value), 0) FROM flows WHERE exporter = '{hub}'),
          (SELECT COALESCE(SUM(identified), 0) FROM identified),
          (SELECT COALESCE(SUM(funded), 0) FROM funded),
          (SELECT COUNT(*) FROM funded),
          (SELECT COALESCE(SUM(funded), 0) FROM funded WHERE scale < 1 - 1e-12)
    """).fetchone()
    print(f'{hub} ({weight_cols}) exports_after {stats[0]:.3f} identified {stats[1]:.3f} '
          f'funded {stats[2]:.3f} legs {stats[3]} funded_under_cap {stats[4]:.3f}', flush=True)
    return stats


def identified_hk():
    return """
        SELECT s.dest, f.hs6, f.value AS export_value, f.value * s.share AS identified
        FROM flows f
        JOIN hk_share s ON s.dest = f.importer AND s.hs2 = substr(f.hs6, 1, 2)
        WHERE f.exporter = 'HKG' AND f.value > 0 AND s.share > 0
    """


def claim_hk():
    # Origin weights do not depend on HS6. dest_total includes unmapped origins.
    return """
        SELECT i.dest, i.hs6, o.origin,
               i.identified * o.weight / o.dest_total AS claim
        FROM identified i
        JOIN hk_origin o ON o.dest = i.dest
        WHERE o.weight > 0 AND o.dest_total > 0
    """


def identified_sg():
    return """
        SELECT s.dest, f.hs6, f.value AS export_value, f.value * s.share AS identified
        FROM flows f
        JOIN sg_share s ON s.dest = f.importer
        WHERE f.exporter = 'SGP' AND f.value > 0 AND s.share > 0
    """


def claim_import_share(hub):
    """Origin weight is this HS6's remaining import from that origin. Same for every destination."""
    return f"""
        SELECT i.dest, i.hs6, m.exporter AS origin,
               i.identified * m.value / t.total_import AS claim
        FROM identified i
        JOIN flows m ON m.importer = '{hub}' AND m.hs6 = i.hs6 AND m.exporter <> '{hub}' AND m.value > 0
        JOIN (
            SELECT hs6, SUM(value) AS total_import
            FROM flows
            WHERE importer = '{hub}' AND exporter <> '{hub}' AND value > 0
            GROUP BY hs6
        ) t ON t.hs6 = i.hs6
    """


def identified_nl():
    return """
        SELECT s.dest, f.hs6, f.value AS export_value, f.value * s.share AS identified
        FROM flows f
        JOIN hs_section h ON h.hs6 = f.hs6
        JOIN nl_share s ON s.dest = f.importer AND s.section = h.section
        WHERE f.exporter = 'NLD' AND f.value > 0 AND s.share > 0
    """


def publish(tmp_path, name):
    """Write on local disk, then copy into the artifact folder.

    A direct DuckDB export of the full table into the artifact folder has
    come back with no file. Staging on local disk avoids that.
    """
    import shutil
    os.makedirs(OUT, exist_ok=True)
    if not os.path.exists(tmp_path):
        raise SystemExit(f'missing staged file {tmp_path}')
    dest = os.path.join(OUT, name)
    shutil.copy2(tmp_path, dest)
    print(f'wrote {name} {os.path.getsize(dest)} bytes', flush=True)
    return dest


def export_parts(con, select_sql, staged_prefix, art_stem, nparts):
    """The artifact folder rejects a single file of a few hundred MB (EINVAL).

    Parts are a hash split of the same rows, not a sample.
    """
    for k in range(nparts):
        tmp = f'{staged_prefix}_{k:02d}.parquet'
        con.execute(f"""
            COPY (
                SELECT * EXCLUDE (part_key) FROM ({select_sql}) t
                WHERE abs(hash(part_key)) % {nparts} = {k}
            ) TO '{tmp}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)
        sz = os.path.getsize(tmp)
        print(f'staged {art_stem} part {k} {sz} bytes', flush=True)
        if sz > 90_000_000:
            raise SystemExit(f'{tmp} is {sz} bytes; the artifact folder rejects files near this size')
        publish(tmp, f'{art_stem}_{k:02d}.parquet')


def write_outputs(con, checks):
    os.makedirs(OUT, exist_ok=True)
    staged = os.path.join(CACHE, 'out')
    os.makedirs(staged, exist_ok=True)
    export_parts(con, """
        SELECT exporter AS exporter_region, importer AS importer_region, hs6,
               value AS value_kusd,
               CASE WHEN qty_ok THEN qty ELSE NULL END AS qty_tons,
               NOT qty_ok AS adjusted,
               exporter || '|' || importer || '|' || hs6 AS part_key
        FROM flows
        WHERE exporter <> importer AND abs(value) > 1e-9
    """, os.path.join(staged, 'bilateral'), 'baci_hs6_bilateral', 8)
    export_parts(con, """
        SELECT hub, leg, exporter, importer, hs6, before, delta, after,
               source_id, method, fill_flags,
               hub || '|' || exporter || '|' || importer || '|' || hs6 || '|' || leg AS part_key
        FROM ledger
    """, os.path.join(staged, 'ledger'), 'adjustment_ledger', 16)
    con.execute(f"""
        COPY (
            SELECT hub, exporter, importer,
                   SUM(delta) AS delta_kusd,
                   COUNT(*) AS n_hs6,
                   ANY_VALUE(source_id) AS source_id,
                   ANY_VALUE(method) AS method,
                   ANY_VALUE(fill_flags) AS fill_flags
            FROM ledger
            GROUP BY 1, 2, 3
            ORDER BY 1, 2, 3
        ) TO '{os.path.join(OUT, 'adjustment_by_partner.csv')}' (HEADER, DELIMITER ',')
    """)
    con.execute(f"""
        COPY (
            SELECT hub,
                   SUM(CASE WHEN leg = 'hub_export_removal' THEN -delta ELSE 0 END) AS removed_from_hub_exports_kusd,
                   SUM(CASE WHEN leg = 'hub_import_reduction' THEN -delta ELSE 0 END) AS removed_from_hub_imports_kusd,
                   SUM(CASE WHEN leg = 'origin_export_addition' THEN delta ELSE 0 END) AS added_to_origin_exports_kusd,
                   COUNT(*) AS n_ledger_rows
            FROM ledger
            GROUP BY 1
            ORDER BY 1
        ) TO '{os.path.join(OUT, 'adjustment_summary.csv')}' (HEADER, DELIMITER ',')
    """)
    # Small summary also lands in the repo docs.
    summary_src = os.path.join(OUT, 'adjustment_summary.csv')
    repo_doc = os.path.join(REPO, 'dataset', 'prep', 'trade')
    os.makedirs(repo_doc, exist_ok=True)
    open(os.path.join(repo_doc, 'adjustment_summary.csv'), 'w').write(open(summary_src).read())


def main():
    os.makedirs(OUT, exist_ok=True)
    checks = []

    def add(cid, kind, desc, value, threshold, passed):
        checks.append(dict(id=cid, kind=kind, desc=desc, value=str(value),
                           threshold=str(threshold), passed=bool(passed)))

    zsize = os.path.getsize(BACI_ZIP)
    zsha = sha256(BACI_ZIP)
    add('PREP-A-SHA', 'hard', 'BACI_HS17_V202601.zip byte size and SHA256 match MANIFEST',
        f'{zsize} {zsha}',
        f'{MANIFEST_BYTES["baci/BACI_HS17_V202601.zip"]} {MANIFEST_SHA["baci/BACI_HS17_V202601.zip"]}',
        zsize == MANIFEST_BYTES['baci/BACI_HS17_V202601.zip']
        and zsha == MANIFEST_SHA['baci/BACI_HS17_V202601.zip'])

    for req in ('hk/tx_hs2.json', 'hk/rx_hs2.json', 'hk/rx_od.json',
                'hk/totals.json', 'sg/M451521.json', 'sg/M451501.json', 'sg/M451001.json',
                'cbs/typed_2022.json', 'cbs/landen.json', 'cbs/sitc.json'):
        if not os.path.exists(os.path.join(RAW, req)):
            raise SystemExit(f'missing {req}; fetch_sources.py has not finished')

    iso_to_region, regions = load_region_map()
    if len(regions) != 167:
        raise SystemExit(f'expected 167 regions, got {len(regions)}')
    overrides = load_overrides()
    iso2, names, ambiguous = load_iso2_to_iso3()
    add('PREP-A-NAMES', 'report',
        'English country names that match more than one ISO3 were not used automatically',
        len(ambiguous), 'overrides cover the SingStat labels that hit this set', True)

    con = duckdb.connect()
    con.execute("SET preserve_insertion_order = false")
    os.makedirs(os.path.join(CACHE, 'duck'), exist_ok=True)
    con.execute(f"SET temp_directory = '{os.path.join(CACHE, 'duck')}'")
    con.execute("SET max_temp_directory_size = '80GB'")
    load_hk_shares(con, iso2, iso_to_region, checks)
    load_sg_shares(con, names, overrides, iso_to_region, checks)
    load_nl_shares(con, iso2, overrides, iso_to_region, checks)

    print('loading BACI', flush=True)
    load_baci(con, iso_to_region)
    raw_sum, raw_n, raw_neg = con.execute(
        'SELECT SUM(value), COUNT(*), SUM(value < 0) FROM raw').fetchone()
    bil_sum = con.execute('SELECT COALESCE(SUM(value), 0) FROM flows').fetchone()[0]
    intra_sum = con.execute('SELECT COALESCE(SUM(value), 0) FROM intra').fetchone()[0]
    un_sum = con.execute('SELECT COALESCE(SUM(value), 0) FROM unmapped').fetchone()[0]
    add('PREP-A-SPLIT', 'hard',
        'BACI value = bilateral regions + intra-region + unmapped (thousand USD)',
        f'{bil_sum + intra_sum + un_sum:.6f} vs {raw_sum:.6f}',
        'absolute gap < 1 thousand USD (sum of 11.7 million doubles)',
        abs((bil_sum + intra_sum + un_sum) - raw_sum) < 1.0)
    add('PREP-A-RAW-SIGN', 'hard', 'BACI 2022 has no negative values', raw_neg, 0, raw_neg == 0)
    nreg = con.execute('SELECT COUNT(DISTINCT exporter) + 0 FROM flows').fetchone()[0]
    both = con.execute('''
        SELECT COUNT(*) FROM (
          SELECT exporter AS r FROM flows UNION SELECT importer FROM flows
        ) t WHERE r NOT IN (SELECT DISTINCT region FROM reg)
    ''').fetchone()[0]
    add('PREP-A-REGIONS', 'hard', 'Bilateral exporters and importers are among the 167 regions',
        f'exporters {nreg}; outside {both}', 'outside 0', both == 0)
    print(f'BACI rows {raw_n} value {raw_sum:.3f} bilateral {bil_sum:.3f} intra {intra_sum:.3f} unmapped {un_sum:.3f}',
          flush=True)

    con.execute('''CREATE TABLE ledger(
        hub VARCHAR, leg VARCHAR, exporter VARCHAR, importer VARCHAR, hs6 VARCHAR,
        before DOUBLE, delta DOUBLE, after DOUBLE,
        source_id VARCHAR, method VARCHAR, fill_flags VARCHAR)''')
    con.execute('CREATE TABLE intra_add(hub VARCHAR, region VARCHAR, hs6 VARCHAR, value DOUBLE)')
    con.execute('''CREATE TABLE funding(
        hub VARCHAR, origin VARCHAR, dest VARCHAR, hs6 VARCHAR,
        funded DOUBLE, claim DOUBLE, scale DOUBLE)''')

    before = {}
    for hub in HUBS:
        before[hub] = con.execute(
            'SELECT COALESCE(SUM(value), 0) FROM flows WHERE exporter = ?', [hub]).fetchone()[0]

    # Imports of every region, to test the destination identity after each hub.
    con.execute('CREATE TABLE imports_before AS SELECT importer AS region, SUM(value) AS value FROM flows GROUP BY 1')

    apply_hub(con, 'HKG', identified_hk(), claim_hk(), 'origin x dest, all commodities')
    apply_hub(con, 'NLD', identified_nl(), claim_import_share('NLD'), 'same-HS6 import share')
    apply_hub(con, 'SGP', identified_sg(), claim_import_share('SGP'), 'same-HS6 import share')

    funded_sum = con.execute('SELECT COALESCE(SUM(funded), 0) FROM funding').fetchone()[0]
    bil_after = con.execute('SELECT COALESCE(SUM(value), 0) FROM flows').fetchone()[0]
    intra_add = con.execute('SELECT COALESCE(SUM(value), 0) FROM intra_add').fetchone()[0]
    # Grand total falls by the funded double-count only.
    gap = (bil_after + intra_sum + intra_add + un_sum + funded_sum) - raw_sum
    add('PREP-A-IDENTITY', 'hard',
        'Cleaned bilateral + intra + unmapped + funded double-count = original BACI (thousand USD)',
        f'gap {gap:.6f}; funded {funded_sum:.3f}',
        'absolute gap < 1 thousand USD',
        abs(gap) < 1.0)

    neg = con.execute('SELECT COUNT(*), COALESCE(MIN(value), 0) FROM flows WHERE value < -1e-6').fetchone()
    add('PREP-A-NONEG', 'hard', 'No bilateral cell is negative after the cap',
        f'n {neg[0]} min {neg[1]}', 'none below -1e-6 thousand USD', neg[0] == 0)
    intra_bil = con.execute(
        'SELECT COUNT(*) FROM flows WHERE exporter = importer AND abs(value) > 1e-9').fetchone()[0]
    add('PREP-A-NO-INTRA', 'hard', 'The bilateral table has no exporter = importer cell',
        intra_bil, 0, intra_bil == 0)
    outside = con.execute(f'''
        SELECT COUNT(*) FROM flows f
        WHERE abs(f.value) > 1e-9 AND (
            f.exporter NOT IN (SELECT region FROM reg)
            OR f.importer NOT IN (SELECT region FROM reg))
    ''').fetchone()[0]
    add('PREP-A-OUTSIDE', 'hard', 'No adjusted flow uses a region outside the 167',
        outside, 0, outside == 0)

    # Import change of region R equals:
    #   -funded where R is the hub (those goods were not retained),
    #   -funded where R is the destination (the hub's export is removed),
    #   +funded where R is the destination and the origin is a different region.
    # A destination that is not the origin therefore does not change.
    dest_gap = con.execute('''
        WITH imp_after AS (
            SELECT importer AS region, SUM(value) AS value FROM flows GROUP BY 1
        ),
        observed AS (
            SELECT COALESCE(b.region, a.region) AS region,
                   COALESCE(a.value, 0) - COALESCE(b.value, 0) AS d_import
            FROM imports_before b
            FULL OUTER JOIN imp_after a USING (region)
        ),
        expected AS (
            SELECT region, SUM(d) AS d_import FROM (
                SELECT hub AS region, -SUM(funded) AS d
                FROM funding GROUP BY 1
                UNION ALL
                SELECT dest AS region, -SUM(funded) AS d
                FROM funding GROUP BY 1
                UNION ALL
                SELECT dest AS region, SUM(funded) AS d
                FROM funding WHERE origin <> dest GROUP BY 1
            )
            GROUP BY 1
        )
        SELECT COALESCE(MAX(ABS(o.d_import - COALESCE(e.d_import, 0))), 0),
               COUNT(*) FILTER (WHERE ABS(o.d_import - COALESCE(e.d_import, 0)) > 0.01)
        FROM observed o
        LEFT JOIN expected e USING (region)
    ''').fetchone()
    add('PREP-A-DEST', 'hard',
        'Each region\'s import change equals retained-import removal plus returns to the same region (thousand USD)',
        f'max abs gap {dest_gap[0]:.6e}; regions off by more than 0.01 {dest_gap[1]}',
        'max gap < 0.01 thousand USD (floating-point dust on the summed legs)',
        dest_gap[0] < 0.01)

    # Flows touched by a hub carry a source. Untouched flows are not in the ledger.
    unsourced = con.execute('''
        SELECT COUNT(*) FROM ledger WHERE source_id IS NULL OR source_id = '' OR method = ''
    ''').fetchone()[0]
    add('PREP-A-SOURCE', 'hard', 'Every ledger row names a source and a method',
        unsourced, 0, unsourced == 0)
    adj_qty = con.execute('''
        SELECT COUNT(*) FROM flows WHERE NOT qty_ok AND qty IS NOT NULL
    ''').fetchone()[0]
    add('PREP-A-QTY', 'hard', 'Adjusted cells do not keep a BACI quantity (re-export statistics are values)',
        adj_qty, 0, adj_qty == 0)

    # Hubs that were deliberately not adjusted have a zero ledger.
    for hub in NOT_ADJUSTED:
        n = con.execute('SELECT COUNT(*) FROM ledger WHERE exporter = ? AND hub = ?', [hub, hub]).fetchone()[0]
        # They can still appear as origins or destinations of another hub. They must not appear as the hub.
        n_as_hub = con.execute('SELECT COUNT(*) FROM funding WHERE hub = ?', [hub]).fetchone()[0]
        add(f'PREP-A-SKIP-{hub}', 'hard',
            f'{hub} is not a re-export hub in this prep (no verified bilateral re-export file)',
            n_as_hub, 0, n_as_hub == 0)

    # Shares used were inside [0, 1]. Already gated at load. Report the mass.
    lines_summary = []
    for hub in HUBS:
        exp_after = con.execute(
            'SELECT COALESCE(SUM(value), 0) FROM flows WHERE exporter = ?', [hub]).fetchone()[0]
        funded = con.execute(
            'SELECT COALESCE(SUM(funded), 0) FROM funding WHERE hub = ?', [hub]).fetchone()[0]
        lines_summary.append((hub, before[hub], exp_after, funded))
        add(f'PREP-A-HUB-{hub}', 'report',
            f'{hub} exports before and after, and funded double-count removed (thousand USD)',
            f'before {before[hub]:.3f}; after {exp_after:.3f}; funded {funded:.3f}',
            SOURCE[hub], True)

    # Not-adjusted mass: hub exports with no share, plus (NLD) ambiguous HS6.
    no_hk = con.execute('''
        SELECT COALESCE(SUM(f.value), 0)
        FROM flows f
        ANTI JOIN hk_share s ON s.dest = f.importer AND s.hs2 = substr(f.hs6, 1, 2)
        WHERE f.exporter = 'HKG'
    ''').fetchone()[0]
    # This is AFTER adjustment, so it is the remaining flow to destinations/HS2 we never had a share for
    # plus domestic-only HS2 (share 0 is a share; those were joined and not identified).
    # Rebuild the "never joined" set from the original? Flows to share-0 dests were not changed
    # except when they were origins. Report from hk_share coverage of current HKG exports is muddy.
    # Use ledger absence plus a stored identified. Report identified vs before instead.
    add('PREP-A-COVERAGE', 'report',
        'HKG exports currently sitting on a destination x HS2 with no HK share row (thousand USD, after adjustment)',
        f'{no_hk:.3f}',
        'not adjusted; missing share is not treated as 0 or 1', True)

    write_outputs(con, checks)
    # Unmapped BACI bucket, small enough to list by ISO pair summed.
    con.execute(f"""
        COPY (
            SELECT exp_iso, imp_iso, SUM(value) AS value_kusd, COUNT(*) AS n_hs6
            FROM unmapped
            GROUP BY 1, 2
            ORDER BY 3 DESC
        ) TO '{os.path.join(OUT, 'baci_unmapped.csv')}' (HEADER, DELIMITER ',')
    """)
    con.execute(f"""
        COPY (
            SELECT * FROM sg_commodity_diag ORDER BY series
        ) TO '{os.path.join(OUT, 'sg_commodity_diagnostic.csv')}' (HEADER, DELIMITER ',')
    """)

    n_ledger = con.execute('SELECT COUNT(*) FROM ledger').fetchone()[0]
    n_flows = con.execute("SELECT COUNT(*) FROM flows WHERE abs(value) > 1e-9 AND exporter <> importer").fetchone()[0]
    n_adj = con.execute('SELECT COUNT(*) FROM flows WHERE NOT qty_ok AND abs(value) > 1e-9').fetchone()[0]
    add('PREP-A-SIZE', 'report', 'Bilateral HS6 cells and cells whose value changed',
        f'cells {n_flows}; adjusted {n_adj}; ledger rows {n_ledger}',
        'ledger is the flow-level adjustment, one row per changed cell per hub', True)

    text = render(checks, zsha, raw_sum, funded_sum, un_sum, intra_sum, intra_add)
    open(os.path.join(OUT, 'checks.md'), 'w').write(text)
    json.dump({'checks': checks, 'funded_kusd': funded_sum, 'baci_sha256': zsha,
               'raw_kusd': raw_sum}, open(os.path.join(OUT, 'checks.json'), 'w'), indent=2)
    repo_doc = os.path.join(REPO, 'dataset', 'prep', 'trade')
    open(os.path.join(repo_doc, 'baci_checks.md'), 'w').write(text)
    print(text)
    fails = [c for c in checks if c['kind'] == 'hard' and not c['passed']]
    print('HARD FAILS', len(fails), flush=True)
    if fails:
        raise SystemExit(1)


def render(checks, zsha, raw_sum, funded_sum, un_sum, intra_sum, intra_add):
    lines = ['# BACI 2022 re-export removal checks', '',
             f'BACI zip SHA256 `{zsha}` matches MANIFEST.',
             'Year 2022. Classification HS2017 as published in BACI_HS17_V202601. Unit: thousand USD, FOB.',
             'National re-export statistics are used as shares only.',
             f'Original BACI total {raw_sum:,.3f} thousand USD.',
             f'Funded double-count removed {funded_sum:,.3f}.',
             f'Intra-region before {intra_sum:,.3f}; added because origin region = destination region {intra_add:,.3f}.',
             f'Unmapped (no S01 region) {un_sum:,.3f}.',
             '',
             'Order of hubs: HKG, then NLD, then SGP.',
             'BEL, ARE and PAN are not adjusted.',
             '',
             '| ID | Kind | Status | Check | Value |',
             '|---|---|---|---|---|']
    for c in checks:
        status = 'PASS' if c['passed'] else 'FAIL'
        lines.append(f'| {c["id"]} | {c["kind"]} | **{status}** | {c["desc"]} | {c["value"]} |')
    lines += ['',
              '## Accounting',
              '',
              'For a funded amount f on origin O, hub H, destination D, HS6 k:',
              '',
              '- H→D falls by f (the re-export is not a domestic export of the hub);',
              '- O→H falls by f (it was not retained in the hub);',
              '- O→D rises by f when O and D are different regions;',
              '- when O and D are the same region the f is intra-region, not bilateral.',
              '',
              'The world total of bilateral plus intra falls by f. A destination that is not the origin keeps the same import total.',
              'Quantity is cleared on every cell this changes. The re-export sources publish values, not a quantity split.',
              '']
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    main()
