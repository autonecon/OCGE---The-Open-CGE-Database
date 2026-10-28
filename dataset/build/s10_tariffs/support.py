"""Domestic support (OECD PSE) and export subsidies (WTO notifications). Ported after review.

PSE (pse_source, pse_F_G, pse_mapping, pse_aan_split, pse_commodity, pse_eu, pse_eu_mapping, pse_non_oecd):
MONEVA 2022 USD budgetary A2-E = PO+PIV+PIF+PIS+PC+PHR+PHNR, MPS and F/G excluded, all to crp.
C (PCAAN, PCRI) and D (PHR) by their MONEVA basis (area to land, animal numbers to capital, receipts and income to
labour; GTAP 12 ch.11A p.2), PCAAN by the FAOSTAT 2022 crop/livestock share only where MONEVA has no complete split.
E (PHNR) to all crp factors pro rata on crp value added (the standard formula, ch.13D §D.2). EU members (ch.13D §D.3):
E and the income-based C and D payments go to land only, one rate over the farm sector. EU MONEVA split over members
by FAOSTAT item 2051.

Export subsidies (export_subsidy, export_subsidy_year, export_subsidy_base): WTO notified
outlay over the notified product's own HS exports (BACI 2022); not booked below 0.05 USD
million of own exports, above a 100 percent rate, or above sector exports.
"""
import csv
import io
import re
import unicodedata
import zipfile
from collections import defaultdict

from .preferences import EU27
from .util import fnum

PSE_MEASURES = ('PSE', 'MPS', 'PM', 'PN', 'PO', 'PIV', 'PIF', 'PIS', 'PC', 'PCAAN', 'PCRI', 'PHR', 'PHNR', 'CO')
A2E_PARTS = ('PO', 'PIV', 'PIF', 'PIS', 'PC', 'PHR', 'PHNR')
D_BASIS = ('PHR_AREA', 'PHR_AN', 'PHR_R', 'PHR_INC')
C_AAN_BASIS = ('PC_AREA', 'PC_AN')       # PCAAN = area + animal numbers (MONEVA, national currency only)
C_RI_BASIS = ('PC_R', 'PC_INC')          # PCRI = receipts + income
XDC_MEASURES = ('PHR', 'PCAAN', 'PCRI') + D_BASIS + C_AAN_BASIS + C_RI_BASIS
Q_EU = 'GTAP 12 ch.13D §D.2-D.3'
# pse_eu_mapping values: EU members put E (PHNR) and income-based C and D payments on land (ch.13D), or the standard formula
EU_LAND_RULE = 'ch13d_e_phnr_and_income_based_c_d_to_land_one_rate'
# pse_aan_split values
AAN_BY_BASIS = 'pcaan_by_moneva_basis_area_land_animal_capital_else_faostat_share_flagged'
ANCHOR_M49 = {
    'CHN': 156, 'HKG': 344, 'MAC': 446, 'TWN': 158, 'USA': 840, 'GBR': 826,
    'KOR': 410, 'PRK': 408, 'COD': 180, 'NLD': 528, 'LAO': 418, 'IRN': 364,
    'ISL': 352, 'PRI': 630, 'ARE': 784, 'MMR': 104, 'STP': 678, 'VEN': 862,
}
ALIAS_FAO_NAME = {
    'China; mainland': 'CHN', 'China; Taiwan Province of': 'TWN', 'Bosnia and Herzegovina': 'BIH',
    'Central African Republic': 'CAF', 'Dominican Republic': 'DOM', 'Cook Islands': 'COK',
    'Solomon Islands': 'SLB', 'Marshall Islands': 'MHL', "Democratic People's Republic of Korea": 'PRK',
    'Democratic Republic of the Congo': 'COD', 'Iran (Islamic Republic of)': 'IRN',
    "Lao People's Democratic Republic": 'LAO', 'Micronesia (Federated States of)': 'FSM',
    'Netherlands (Kingdom of the)': 'NLD', 'Republic of Korea': 'KOR', 'Republic of Moldova': 'MDA',
    'Syrian Arab Republic': 'SYR', 'United Kingdom of Great Britain and Northern Ireland': 'GBR',
    'United Republic of Tanzania': 'TZA', 'United States of America': 'USA',
    'Venezuela (Bolivarian Republic of)': 'VEN',
}
WTO_NAME = {
    'korea republic of': 'KOR', 'republic of korea': 'KOR', 'mauritius': 'MUS', 'morocco': 'MAR',
    'pakistan': 'PAK', 'tunisia': 'TUN', 'turkiye': 'TUR', 'turkey': 'TUR',
}
Q_PSE = 'GTAP 12 ch.11A pp.1-3; Aguiar et al. 2025 p.12'
Q_XS = 'GTAP 12 ch.11C pp.1-2; Aguiar et al. 2025 p.12'
# USA MONEVA 2022 components as read in the S10 handoff preview (S10-Husa-pse).
USA_PREVIEW = {
    'PO': 87.1608, 'PIV': 3117.0869, 'PIF': 2109.0398, 'PIS': 6356.5834,
    'PC': 22414.1766, 'PHR': 324.3196, 'PHNR': 2203.777, 'PSE': 40974.2609, 'MPS': 2508.1668,
}


def norm_name(s):
    s = unicodedata.normalize('NFC', s).lower().replace(';', ' ').replace(',', ' ')
    s = ''.join(ch if ch.isalnum() or ch.isspace() else ' ' for ch in s)
    return ' '.join(s.split())


def parse_m49(raw):
    digits = ''.join(ch for ch in str(raw) if ch.isdigit())
    return int(digits) if digits else None


def close(booked, target):
    diff = abs(booked - target)
    return diff <= 1e-3 or diff <= 1e-6 * max(abs(target), 1e-3)


# ---------------------------------------------------------------- PSE

def fao_values(fao_zip, name_iso):
    """{(iso, item): 2022 gross production value} for items 2041 crops, 2044 livestock, 2051 agriculture."""
    area_to_iso, iso_to_m49 = {}, {}
    acc = defaultdict(float)
    with zipfile.ZipFile(fao_zip) as zf:
        for row in csv.DictReader(io.StringIO(zf.read('Value_of_Production_E_AreaCodes.csv').decode('utf-8'))):
            code, m49, name = int(row['Area Code']), parse_m49(row['M49 Code']), row['Area'].strip()
            if code >= 5000 or m49 == 159:
                continue
            iso = ALIAS_FAO_NAME.get(name)
            if iso is None:
                hits = name_iso.get(norm_name(name), set())
                if len(hits) > 1:
                    raise SystemExit(f'FAO area {name!r} matches {sorted(hits)}')
                iso = next(iter(hits)) if hits else None
            if iso:
                area_to_iso[code] = iso
                iso_to_m49[iso] = m49
        with zf.open('Value_of_Production_E_All_Data_(Normalized).csv') as raw:
            for row in csv.DictReader(io.TextIOWrapper(raw, encoding='utf-8', newline='')):
                if row['Element Code'] != '57' or row['Year'] != '2022' or row['Item Code'] not in ('2041', '2044', '2051'):
                    continue
                iso = area_to_iso.get(int(row['Area Code']))
                if iso and row['Value']:
                    acc[(iso, row['Item Code'])] += float(row['Value'])
    bad = [f'{c} got {iso_to_m49.get(c)} want {m}' for c, m in ANCHOR_M49.items() if iso_to_m49.get(c) != m]
    if bad:
        raise SystemExit('FAO area map failed anchors: ' + '; '.join(bad))
    return acc


def moneva(path):
    """USD measures, plus category D (PHR) and its basis split in national currency (key 'm@XDC').
    MONEVA publishes the basis split of D only in national currency."""
    out = defaultdict(dict)
    with open(path, newline='') as fh:
        for row in csv.DictReader(fh):
            if row.get('COMMODITY') != 'CPC_EX_TO' or row.get('TIME_PERIOD') != '2022':
                continue
            m, unit = row.get('MEASURE'), row.get('UNIT_MEASURE')
            if unit == 'USD' and m in PSE_MEASURES:
                key = m
            elif unit == 'XDC' and m in XDC_MEASURES:
                key = m + '@XDC'
            else:
                continue
            out[row['REF_AREA']][key] = out[row['REF_AREA']].get(key, 0.0) + float(row['OBS_VALUE'] or 0.0)
    return out


def d_by_basis(block):
    """pse_mapping: category D (PHR, USD) split land/capital/labour by its MONEVA basis shares in
    national currency (area to land, animal numbers to capital, receipts and income to labour).
    Returns (land, capital, labour) or None when D has no complete basis split."""
    phr = block.get('PHR', 0.0)
    total = block.get('PHR@XDC', 0.0)
    parts = {m: block.get(m + '@XDC', 0.0) for m in D_BASIS}
    if not phr:
        return 0.0, 0.0, 0.0
    if abs(total) < 1e-9 or abs(sum(parts.values()) - total) > 1e-6 * max(1.0, abs(total)):
        return None
    land = phr * parts['PHR_AREA'] / total
    capital = phr * parts['PHR_AN'] / total
    return land, capital, phr - land - capital


def basis_split(block, usd, parts):
    """pse_mapping, pse_aan_split: the USD measure `usd` split by the MONEVA basis shares of its parts, which MONEVA
    publishes in national currency only ({part: USD}). {} where the measure is zero; None where the parts are
    missing or do not add up to the measure in national currency."""
    val = block.get(usd, 0.0)
    total = block.get(usd + '@XDC')
    vals = {m: block.get(m + '@XDC') for m in parts}
    if not val:
        return {m: 0.0 for m in parts}
    if total is None or abs(total) < 1e-9 or any(v is None for v in vals.values()):
        return None
    if abs(sum(vals.values()) - total) > 1e-6 * max(1.0, abs(total)):
        return None
    return {m: val * v / total for m, v in vals.items()}


def a2e(block):
    return sum(block.get(m, 0.0) for m in A2E_PARTS)


def pse(S, C, mon, fao, regions, pre):
    """Book A2-E by region. Returns (support_rows, booked_by_region, region_pse, problems)."""
    eu_shares = {iso: fao[(iso, '2051')] for iso in sorted(EU27) if fao.get((iso, '2051'), 0) > 0}
    missing_eu = sorted(set(EU27) - set(eu_shares))
    if not eu_shares:
        raise SystemExit('no EU27 member has FAOSTAT 2022 item 2051')
    share_sum = sum(eu_shares.values())
    if missing_eu:
        S.flag('EU-FAO-MISSING', 'EU', 'FAOSTAT 2022 item 2051 is missing for ' + ','.join(missing_eu)
               + '. Shares are renormalized over the members that have it.', 'no', C['pse_eu'], 'departure')

    def allocate(total):
        keys = sorted(eu_shares)
        out, acc = {}, 0.0
        for k in keys[:-1]:
            out[k] = total * eu_shares[k] / share_sum
            acc += out[k]
        out[keys[-1]] = total - acc
        return out

    region_set = set(regions)
    region_pse = {}
    for area, block in mon.items():
        if area in ('OECD', 'EU'):
            continue
        if area not in region_set:
            S.flag('PSE-UNMAPPED', area, f'MONEVA area {area} is not an S01 region. A2-E {a2e(block):.4f} USD million is not booked.',
                   'no', C['pse_non_oecd'], 'not in GTAP text')
            continue
        region_pse[area] = dict(block)
    eu_block = mon.get('EU', {})
    for measure in A2E_PARTS + ('PSE', 'MPS', 'PN', 'PM', 'PCAAN', 'PCRI') + tuple(m + '@XDC' for m in XDC_MEASURES):
        if measure in eu_block:
            for iso, part in allocate(eu_block[measure]).items():
                region_pse.setdefault(iso, {})[measure] = region_pse.get(iso, {}).get(measure, 0.0) + part
    rows, booked_by, bad = [], {}, []
    for region in sorted(region_pse):
        b = region_pse[region]
        target = a2e(b)
        pcaan = b.get('PCAAN', 0.0)
        eu_land = region in EU27 and C['pse_eu_mapping'] == EU_LAND_RULE
        crops, live = fao.get((region, '2041')), fao.get((region, '2044'))
        fill_split = ''
        c_aan = basis_split(b, 'PCAAN', C_AAN_BASIS) if C['pse_aan_split'] == AAN_BY_BASIS else None
        if c_aan is not None:
            land, animal, unsplit = c_aan['PC_AREA'], c_aan['PC_AN'], 0.0
            fill_split = 'pcaan_moneva_basis'
            if pcaan:
                S.flag('PCAAN-BY-BASIS', region, f'PCAAN {pcaan:.4f} USD million split by its MONEVA basis shares in national currency: '
                       f'area to land {land:.4f}, animal numbers to capital {animal:.4f}.', 'no', C['pse_aan_split'], 'GTAP 12 ch.11A p.2')
        elif crops is None or live is None or crops + live <= 0:
            land = animal = 0.0
            unsplit = pcaan
            fill_split = 'pcaan_unsplit'
            if pcaan:
                S.flag('PCAAN-UNSPLIT', region, 'No complete MONEVA basis split and FAOSTAT 2022 crop or livestock output is missing. '
                       'PCAAN stays unsplit. No 50/50 plug.', 'no', C['pse_aan_split'], 'not in GTAP text')
        else:
            land_sh = crops / (crops + live)
            land = pcaan * land_sh
            animal = pcaan - land
            unsplit = 0.0
            fill_split = 'pcaan_faostat_share'
            if pcaan:
                S.flag('PCAAN-SPLIT', region, f'No complete MONEVA basis split for PCAAN. Land share {land_sh:.6f} from FAOSTAT 2041 crops '
                       'over 2041+2044.', 'no', C['pse_aan_split'], 'not in GTAP text')
        c_ri = basis_split(b, 'PCRI', C_RI_BASIS)
        if c_ri is None:
            if eu_land:
                bad.append(f'{region} PCRI has no complete basis split in MONEVA (needed for the ch.13D income rule)')
            c_ri = {'PC_R': b.get('PCRI', 0.0), 'PC_INC': 0.0}
        d = d_by_basis(b)
        if d is None:
            bad.append(f'{region} category D has no complete basis split in MONEVA')
            d = (0.0, 0.0, 0.0)
        d_land, d_cap, d_lab = d
        if b.get('PHR', 0.0):
            S.flag('PHR-BY-BASIS', region, f'Category D {b["PHR"]:.4f} USD million split by its MONEVA basis shares in national '
                   f'currency: land {d_land:.4f}, capital {d_cap:.4f}, labour {d_lab:.4f}.', 'no', C['pse_mapping'], 'GTAP 12 ch.11A p.2')
        factors = b.get('PHNR', 0.0)
        lab_c, inc_land = b.get('PCRI', 0.0) - c_ri['PC_INC'], 0.0
        if eu_land:
            # ch.13D §D.3: decoupled payments (BISS, CRISS, CIS-YF, eco-schemes; OECD OTP, category E) go to land only and are
            # spread uniformly over the farm sectors; payments based on farm income are an ACT payment on land
            d_inc = b.get('PHR', 0.0) * b.get('PHR_INC@XDC', 0.0) / b['PHR@XDC'] if b.get('PHR@XDC') else 0.0
            inc_land = c_ri['PC_INC'] + d_inc
            d_lab -= d_inc
            e_land, factors = factors, 0.0
            if e_land or inc_land:
                S.flag('PHNR-EU-LAND', region, f'EU member: E (PHNR) {e_land:.4f} and income-based C and D {inc_land:.4f} USD million '
                       'to land only, one rate on crp land (ch.13D §D.3).', 'no', C['pse_eu_mapping'], Q_EU)
        else:
            e_land = 0.0
            lab_c = b.get('PCRI', 0.0)
            if factors:
                S.flag('PHNR-PRORATA', region, 'PHNR (E) goes to all factors (ch.13D §D.2 standard formula), at one rate on crp '
                       'value added. GTAP takes the E factor proportions from the previous release, which this build does not have.',
                       'no', C['pse_mapping'], Q_EU)
        pieces = [
            ('output', 'crp_output', b.get('PO', 0.0), pre['crp_out'][region], 'crp_OUT'),
            ('input', 'crp_intermediate', b.get('PIV', 0.0) + b.get('PIS', 0.0), pre['crp_inter'][region], 'crp_intermediate_use'),
            ('capital', 'capital', b.get('PIF', 0.0) + animal + d_cap, pre['crp_va'][region], 'crp_VA_memo'),
            ('land', 'land', land + d_land + inc_land, pre['crp_va'][region], 'crp_VA_memo'),
            ('labour', 'labour', lab_c + d_lab, pre['crp_va'][region], 'crp_VA_memo'),
            ('factors', 'all_crp_factors', factors, pre['crp_va'][region], 'crp_VA'),
        ]
        if e_land:
            pieces.append(('land', 'land', e_land, pre['crp_va'][region], 'crp_VA_memo', 'phnr_eu_land_ch13d'))
        if unsplit:
            pieces.append(('pcaan_unsplit', 'unsplit_area_or_animal', unsplit, pre['crp_va'][region], 'crp_VA_memo'))
        booked = 0.0
        for basis, applies, value, denom, rate_on, *tag in pieces:
            if abs(value) < 5e-8:
                continue
            rate_s = fnum(value / denom) if denom > 0 else ''
            if denom <= 0:
                S.flag('PSE-RATE-UNDEFINED', region, f'{basis} value {value:.6f} has denominator {denom:.6f}. The value is booked and the rate is blank.',
                       'no', C['pse_mapping'], Q_PSE)
            fill = fill_split if basis in ('land', 'capital', 'pcaan_unsplit') else ''
            if basis == 'factors':
                fill = 'phnr_pro_rata'
            if tag:
                fill = tag[0]
            if basis in ('capital', 'land', 'labour', 'pcaan_unsplit'):
                fill = (fill + '+' if fill else '') + 'memo_rate_on_crp_va_factor_not_split'
            rows.append([region, basis, applies, 'crp', fnum(value), rate_s, rate_on,
                         'OECD MONEVA 2022 CPC_EX_TO USD million', '2022', fill, 'budgetary USD million'])
            booked += value
            if value < -1e-8:
                S.adjust(region, 'PSE ' + basis, '0', fnum(value), 'negative budgetary component kept; MPS PN and PM are not in this sum', Q_PSE, 'cited')
        residual = target - booked
        if abs(residual) > 1e-3:
            rows.append([region, 'pc_residual', 'crp_output', 'crp', fnum(residual), '', 'published_PC_minus_mapped_parts',
                         'OECD MONEVA 2022 CPC_EX_TO USD million', '2022', 'pc_not_equal_pcaan_plus_pcri', 'budgetary USD million'])
            booked += residual
            S.flag('PC-RESIDUAL', region, f'Published PC minus PCAAN minus PCRI is {residual:.6f} USD million. It is booked so A2-E is complete.',
                   'no', C['pse_mapping'], Q_PSE)
            if residual < -1e-8:
                S.adjust(region, 'PSE pc_residual', '0', fnum(residual), 'negative PC residual kept so A2-E matches the source', Q_PSE, 'cited')
        booked_by[region] = booked
        if not close(booked, target):
            bad.append(f'{region} booked {booked:.6f} A2-E {target:.6f}')
        S.adjust(region, 'PSE A2-E', '0', fnum(booked), 'MONEVA budgetary A2-E; MPS PN PM excluded; all to crp',
                 Q_PSE, 'no' if booked >= -1e-8 else 'cited')
    for region in regions:
        if region not in region_pse:
            S.flag('PSE-UNCOVERED', region, 'No OECD PSE. No domestic support is added. The IO is kept.',
                   'no', C['pse_non_oecd'], 'not in GTAP text')
    return rows, booked_by, region_pse, bad


# ---------------------------------------------------------------- export subsidies

def product_sector(product):
    p = (product or '').strip().lower()
    if not p:
        return 'crp', 'blank_product'
    if any(k in p for k in ('kimchi', 'processed', 'preserve', 'paste', 'liquor')):
        return 'fbt', ''
    if any(k in p for k in ('flower', 'fruit', 'vegetable', 'ginseng', 'livestock', 'egg', 'wheat', 'plant')):
        return 'crp', ''
    return 'crp', 'unmapped_product'


def parse_unit(unit):
    tok = (unit or '').replace(',', ' ').split()
    if not tok:
        return None, None
    scale = {'thousand': 1e3, 'million': 1e6, 'billion': 1e9}
    s = 1.0
    for t in tok[1:]:
        s = scale.get(t.lower(), s)
    return tok[0].upper(), s


def export_subsidies(S, C, wto_path, fx_path, products_path, exp_hs, vxsb_sec, name_iso, region_set):
    """Returns (rows, booked_outlay {(iso, sector): usd_m}, booked_total)."""
    fx = {}
    with open(fx_path, newline='') as fh:
        for row in csv.DictReader(fh):
            fx[(row['iso3'], int(row['year']))] = float(row['lcu_per_usd'])
    threshold = float(re.search(r'xt_below_([0-9.]+)_usd_million', C['export_subsidy_base']).group(1))
    products = []
    with open(products_path, newline='') as fh:
        for row in csv.DictReader(fh):
            products.append((row['product_norm'].strip(), tuple(p.strip() for p in row['hs_prefixes'].split(';') if p.strip()),
                             row['sector'].strip()))
    by_iso = defaultdict(list)
    for (iso, hs), v in exp_hs.items():
        by_iso[iso].append((hs, v))

    def own_exports(iso, prefixes):
        return sum(v for hs, v in by_iso.get(iso, ()) if hs.startswith(prefixes)) / 1000.0

    rows, booked_outlay, booked_total = [], defaultdict(float), 0.0
    unmapped, years, blanks, not_booked = [], set(), set(), []
    with open(wto_path, newline='') as fh:
        for row in csv.DictReader(fh):
            if row.get('positive') not in ('True', 'true', '1'):
                continue
            val = float(row['outlay'] or 0.0)
            if val <= 0:
                continue
            name = norm_name(row['member'])
            iso = WTO_NAME.get(name)
            if iso is None:
                hits = name_iso.get(name, set())
                iso = next(iter(hits)) if len(hits) == 1 else None
            if iso is None or iso not in region_set:
                unmapped.append(row['member'])
                continue
            product = (row.get('product') or '').strip()
            matched = next(((pre, sec) for key, pre, sec in products if norm_name(product) == key), None)
            year = int(row['year'])
            cur, scale = parse_unit(row['unit'])
            if cur is None:
                S.flag('SUBSIDY-UNIT', iso, f'Could not parse unit {row["unit"]!r}. Row not booked.', 'no', C['export_subsidy'], Q_XS)
                continue
            if cur == 'USD':
                usd_m = val * scale / 1e6
            else:
                rate = fx.get((iso, year))
                if not rate:
                    S.flag('SUBSIDY-FX', iso, f'No WDI PA.NUS.FCRF for {year}. Row not booked.', 'no', C['export_subsidy_year'], Q_XS)
                    continue
                usd_m = val * scale / rate / 1e6
            if year != 2022:
                years.add(f'{iso} {year}')
            why = ''
            if matched:
                sector = matched[1]
                xt, base = own_exports(iso, matched[0]), 'own_hs'
            else:
                sector, why = product_sector(product)
                if why == 'blank_product':
                    xt, base = vxsb_sec.get((iso, sector), 0.0), 'sector_vxsb_blank_product'
                    blanks.add(iso)
                else:
                    xt, base, why = 0.0, 'no_hs_list', why or 'unmapped_product'
            exports = vxsb_sec.get((iso, sector), 0.0)
            prate = usd_m / xt if xt > 0 else None
            reason = ''
            if base == 'no_hs_list':
                reason = 'no HS list for the notified product'
            elif xt < threshold:
                reason = f'own-product exports {xt:.6f} are below {threshold} USD million'
            elif prate is None or prate > 1.0:
                reason = f'rate {prate} exceeds 1 on own-product exports {xt:.6f}'
            elif exports <= 0 or usd_m > exports:
                reason = f'sector exports {exports:.6f} cannot hold the outlay'
            booked = not reason
            rows.append([iso, sector, str(year), fnum(usd_m), fnum(exports), fnum(xt), fnum(prate) if prate is not None else '',
                         'yes' if booked else 'no', base, why, product or '(blank)', 'fob'])
            if booked:
                booked_outlay[(iso, sector)] += usd_m
                booked_total += usd_m
                S.adjust(iso, 'export subsidy ' + (product or sector), '0', fnum(usd_m),
                         'WTO notified outlay over 2022 exports of the notified product', Q_XS, 'cited' if usd_m < 0 else 'no')
            else:
                not_booked.append(f'{iso} {product or "(blank)"} {reason}')
    if unmapped:
        S.flag('SUBSIDY-UNMAPPED', 'WTO', 'Positive notifications with no region: ' + ', '.join(sorted(set(unmapped))), 'no', C['export_subsidy'], Q_XS)
    if years:
        S.flag('EXPORT-SUBSIDY-YEAR', 'WTO', 'Notification year is not 2022: ' + ', '.join(sorted(years)) + '.', 'no', C['export_subsidy_year'], 'departure_logged')
    if blanks:
        S.flag('BLANK-PRODUCT', 'WTO', 'Blank product on an agricultural notification: XT is the sector VXSB. ' + ', '.join(sorted(blanks)), 'no', C['export_subsidy'], Q_XS)
    if not_booked:
        S.flag('SUBSIDY-NOT-BOOKED', 'WTO', 'Reported and not booked: ' + '; '.join(not_booked), 'no', C['export_subsidy_base'], Q_XS)
    return rows, dict(booked_outlay), booked_total


def vfob_lines(vfob_rows, booked_outlay, vxsb_sec, export_tax=None, exempt=None):
    """vxsb_from_vfob (GTAP 12 ch.17A eq. 17.30, VFOB = VXSB x export-tax power):
    VXSB = VFOB / (1 - s) - VFOB x t. s is the subsidy rate, outlay over (sector VFOB + outlay), so the
    subsidy wedge is the outlay; t is the export-tax rate on VFOB (export_taxes_other), so the tax wedge is
    the duty. exempt (beta v4 G12): (exporter, importer, sector) -> True where no export duty applies (t = 0).
    Returns (lines, subsidy wedge, tax wedge)."""
    export_tax = export_tax or {}
    rate_of = {k: u / (vxsb_sec.get(k, 0.0) + u) if vxsb_sec.get(k, 0.0) + u > 0 else 0.0 for k, u in booked_outlay.items()}
    lines, wedge, tax_wedge = [], 0.0, 0.0
    for sector, exp, imp, vfob in vfob_rows:
        rate = rate_of.get((exp, sector), 0.0)
        t = 0.0 if exempt is not None and exempt(exp, imp, sector) else export_tax.get((exp, sector), 0.0)
        subsidised = vfob / (1.0 - rate) if 0.0 < rate < 1.0 else vfob
        vxsb = subsidised - vfob * t
        wedge += subsidised - vfob
        tax_wedge += vfob * t
        lines.append(f'{sector},{exp},{imp},{fnum(vxsb)},{fnum(vfob)},{fnum(rate)},{fnum(t)},fob\n'.encode())
    lines.sort()
    return lines, wedge, tax_wedge
