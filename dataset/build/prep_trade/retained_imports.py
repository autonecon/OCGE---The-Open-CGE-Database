"""Hub imports become retained imports (Aguiar et al. 2025 p.12; GTAP 7 ch.9A p.2).

The re-export step in baci_reexports.py takes re-exports off the hub's BACI exports and
the same funded value off the origin's exports to the hub. BACI already books most hub
re-exports to their origin, because importers record the country of origin. So that step
finds little to fund, and the hub's imports keep the goods it re-exports. Those goods are
then counted twice: origin to hub, and origin to final destination.

GTAP converts total imports into retained imports. Here each origin x HS6 import of the
hub is set to the official retained-import ratio times its gross BACI value, and never
raised:

    final = min(current, ratio x gross)

gross is the cell before the hub's own re-export step, plus whatever later hubs moved into
it. Only cells with the hub as importer change. Nothing is added anywhere.

Ratios (national statistics give ratios, not dollar levels, as in baci_reexports.py):

- HKG. C&SD derives retained imports as imports minus the import value of re-exports,
  which is re-exports less a survey margin (Annual Digest of Statistics 2023, notes 3.7,
  Table 3.1). The margin rates are not published. The import-value factor is therefore one
  number, a = (imports - retained imports) / re-exports from Table 3.1, applied to every
  cell. The import value of re-exports by origin x HKHS2 is RAS-fitted to two published
  margins (re-exports by origin, re-exports by HKHS2, both times a), with Trade-IDDS
  imports by origin x HKHS2 as the seed and as the cap. Then
  ratio(origin, HS2) = 1 - fitted / imports.
- SGP. SingStat M451001 publishes imports and re-exports by commodity section, not by
  origin. ratio(category) = 1 - re-exports / imports. SingStat publishes no re-export
  margin, so none is removed (factor 1). The ratio is the same for every origin.
- NLD. CBS 85429NED publishes, by SITC section, total cross-border imports, the incoming
  transit inside them, and re-exports. National imports are total imports less incoming
  transit (CBS's own national concept). ratio(section) = 1 - re-exports / national imports.
  CBS publishes no re-export margin, so none is removed (as SGP). The ratio is the same for
  every origin (Fable QA D-01: NLD imports kept the goods it re-exports).

HKG re-export margin (hk_margin). BACI books most Hong Kong re-exports from the origin to
the final destination at the re-export value, so the Hong Kong middlemen's margin sits in
the origin's goods exports. C&SD gives the import value of re-exports as a times re-exports
(Table 3.1), so the margin is (1 - a) times re-exports. It is taken off the origin's goods
exports to each destination (Trade-IDDS re-exports by origin x consignment) and booked as
a Hong Kong export of trade services (trd) to that destination (Fable QA D-01: keep hub
margins as services exports).
"""
import json
import os
from collections import defaultdict

import openpyxl

HK_NOT_ECONOMY = {f'X{c}' for c in 'ABCDEFGH'} | {'FM'}
HUBS = ('HKG', 'SGP', 'NLD')
SOURCE = {
    'HKG': 'C&SD Annual Digest of Statistics 2023 Table 3.1; Trade-IDDS 2022 imports by origin x HKHS2, re-exports by origin and by HKHS2',
    'SGP': 'SingStat M451001 2022 imports (series 2) and re-exports (series 5) by commodity section',
    'NLD': 'CBS 85429NED 2022 total imports, incoming transit and re-exports by SITC section (world rows)',
}
CBS_WORLD = 'T001047'
CBS_TOTAL = 'T001082'
# SingStat M451001 categories by SITC Rev.4. Oil is division 33. The non-oil
# "Miscellaneous (Excluding Oil Bunkers)" row holds sections 3 (other than 33) and 9.
SG_CATEGORY = {
    'oil': ('2.1', '5.1'), '0': ('2.2.1', '5.2.1'), '1': ('2.2.2', '5.2.2'), '2': ('2.2.3', '5.2.3'),
    '4': ('2.2.5', '5.2.5'), '5': ('2.2.6', '5.2.6'), '6': ('2.2.7', '5.2.7'), '7': ('2.2.8', '5.2.8'),
    '8': ('2.2.9', '5.2.9'), 'misc': ('2.2.999', '5.2.999'),
}


def _num(x):
    return int(str(x).replace(',', ''))


def _annual(row):
    tot = 0.0
    n = 0
    for c in row['columns']:
        if str(c.get('key', '')).startswith('2022 '):
            n += 1
            if c.get('value') not in ('', '-', 'na', 'NA', None):
                tot += float(c['value'])
    return tot, n


def capped_ras(seed, row_t, col_t, tol=1e-9, max_iter=200):
    """Fit x <= seed with row sums row_t and column sums col_t (bi-proportional, capped).

    seed: dict (r, c) -> positive value. Returns (x, iterations, max relative margin gap).
    Cells at the cap stay there; the rest are scaled. A margin that the caps cannot reach
    is left short and reported through the gap.
    """
    x = dict(seed)
    rows = defaultdict(list)
    cols = defaultdict(list)
    for k in seed:
        rows[k[0]].append(k)
        cols[k[1]].append(k)

    def scale(groups, target):
        # Scale each group to its target. A cell whose scaled value would pass its cap
        # is held at the cap and the rest of the group is scaled again.
        for g, keys in groups.items():
            want = target.get(g, 0.0)
            fixed = set()
            for _ in range(len(keys) + 1):
                held = sum(seed[k] for k in fixed)
                free = sum(x[k] for k in keys if k not in fixed)
                if free <= 0:
                    for k in fixed:
                        x[k] = seed[k]
                    break
                f = max(0.0, want - held) / free
                over = [k for k in keys if k not in fixed and x[k] * f > seed[k]]
                if not over:
                    for k in keys:
                        if k not in fixed:
                            x[k] *= f
                    for k in fixed:
                        x[k] = seed[k]
                    break
                fixed.update(over)
            else:
                for k in keys:
                    x[k] = seed[k]

    def gap():
        g = 0.0
        for groups, target in ((rows, row_t), (cols, col_t)):
            for key, keys in groups.items():
                t = target.get(key, 0.0)
                s = sum(x[k] for k in keys)
                if t > 0:
                    g = max(g, abs(s - t) / t)
        return g

    it = 0
    for it in range(1, max_iter + 1):
        scale(rows, row_t)
        scale(cols, col_t)
        if gap() < tol:
            break
    return x, it, gap()


def load_hk_ratios(con, raw, cfg, iso2, iso_to_region, checks):
    """Register hk_ret(origin, hs2, ratio), hk_ret_hs2(hs2, ratio) and return the overall ratio."""
    def add(cid, kind, desc, value, threshold, passed):
        checks.append(dict(id=cid, kind=kind, desc=desc, value=str(value), threshold=str(threshold), passed=bool(passed)))

    totals = json.load(open(os.path.join(raw, 'hk', 'totals.json')))
    imports_k = _num(totals['imports'])
    reexports_k = _num(totals['reexports'])
    dig = cfg['HKG']
    # Table 3.1 is in HK$ million; Trade-IDDS in HK$ thousand.
    add('PREP-R-HK-TOTALS', 'hard',
        "Annual Digest Table 3.1 imports equal the Trade-IDDS 2022 import total (HK$ million)",
        f"digest {dig['imports']:.0f}; IDDS {imports_k / 1000:.3f}", 'difference below 1 HK$ million',
        abs(dig['imports'] - imports_k / 1000) < 1)
    # Import value of re-exports / re-exports. Table 3.1 has no re-export row; the
    # re-export total is the Trade-IDDS published total.
    a = (dig['imports'] - dig['retained']) / (reexports_k / 1000)

    def region(code):
        if code in HK_NOT_ECONOMY or code not in iso2:
            return ''
        return iso_to_region.get(iso2[code], '')

    seed = defaultdict(float)
    dup = set()
    n_dup = 0
    for r in json.load(open(os.path.join(raw, 'hk', 'm_co_hs2.json'))):
        if r.get('unitEN', "HK$ '000") != "HK$ '000" or str(r.get('period')) != '2022':
            raise SystemExit('unexpected unit or period in m_co_hs2.json')
        key = (r['co'], str(r['code']).zfill(2))
        if key in dup:
            n_dup += 1
        dup.add(key)
        o = region(r['co']) or 'UNMAPPED'
        seed[(o, key[1])] += _num(r['figure'])
    m_sum = sum(seed.values())
    rx_o = defaultdict(float)
    for r in json.load(open(os.path.join(raw, 'hk', 'rx_od.json'))):
        rx_o[region(r['co']) or 'UNMAPPED'] += _num(r['figure'])
    rx_k = defaultdict(float)
    for r in json.load(open(os.path.join(raw, 'hk', 'rx_hs2.json'))):
        rx_k[str(r['code']).zfill(2)] += _num(r['figure'])
    ch71 = sum(v for (o, k), v in seed.items() if k == '71')
    add('PREP-R-HK-SEED', 'hard',
        "Trade-IDDS imports by origin x HKHS2 have no duplicate cell (HK$ '000). Their sum against the published "
        "import total is reported: the chapter table carries more chapter 71 (pearls, precious metals) than the "
        "cumulative total, and is not rescaled (same rule as PREP-A-HK-TX)",
        f'duplicates {n_dup}; sum {m_sum:.0f}; published {imports_k}; gap {m_sum - imports_k:.0f}; chapter 71 {ch71:.0f}',
        'no duplicates', n_dup == 0)
    # The seed is the chapter table, so the column margin is the re-export chapter table
    # (same basis: both carry more chapter 71 than the cumulative totals). The origin
    # margin (origin x consignment, which matches the published re-export total to 0.1%
    # under PREP-A-HK-OD) is scaled to that total.
    ksum = sum(rx_k.values())
    col_t = {k: a * v for k, v in rx_k.items()}
    tot = a * ksum
    osum = sum(rx_o.values())
    row_t = {o: v / osum * tot for o, v in rx_o.items()}
    seed_pos = {k: v for k, v in seed.items() if v > 0}
    fit, iters, g = capped_ras(seed_pos, row_t, col_t)
    fitted = sum(fit.values())
    unmet_rows = sum(max(0.0, t - sum(v for (o, _k), v in seed_pos.items() if o == r)) for r, t in row_t.items())
    unmet_cols = sum(max(0.0, t - sum(v for (_o, k), v in seed_pos.items() if k == c)) for c, t in col_t.items())
    add('PREP-R-HK-RAS', 'report',
        'Capped RAS (200 sweeps) of the import value of re-exports onto imports by origin x HKHS2. A margin above '
        'its imports cannot be met; the caps also bind jointly, so the fit stays short by the reported amount',
        f'sweeps {iters}; largest relative margin gap {g:.2e}; fitted {fitted:.0f} of {tot:.0f} HK$ thousand '
        f'({fitted / tot:.4%}); margins above imports: origins {unmet_rows:.0f}, chapters {unmet_cols:.0f}; a {a:.6f}',
        'report; the shortfall stays in retained imports (cells are never raised above imports)', True)
    by_k_m = defaultdict(float)
    by_k_r = defaultdict(float)
    rows = []
    for (o, k), m in seed_pos.items():
        r_ = fit.get((o, k), 0.0)
        by_k_m[k] += m
        by_k_r[k] += r_
        if o != 'UNMAPPED' and o != 'HKG':
            rows.append((o, k, m, r_, max(0.0, 1.0 - r_ / m)))
    con.execute('CREATE TABLE hk_ret(origin VARCHAR, hs2 VARCHAR, imports DOUBLE, reexp_import_value DOUBLE, ratio DOUBLE)')
    con.executemany('INSERT INTO hk_ret VALUES (?, ?, ?, ?, ?)', rows)
    con.execute('CREATE TABLE hk_ret_hs2(hs2 VARCHAR, ratio DOUBLE)')
    con.executemany('INSERT INTO hk_ret_hs2 VALUES (?, ?)',
                    [(k, max(0.0, 1.0 - by_k_r[k] / m)) for k, m in by_k_m.items() if m > 0])
    overall = 1.0 - fitted / m_sum
    published = dig['retained'] / dig['imports']
    # On the cumulative-total basis: take the chapter-table excess out of both sides.
    ret_total_basis = (m_sum - fitted) - ((m_sum - imports_k) - a * (ksum - reexports_k))
    add('PREP-R-HK-RATIO', 'report',
        "Accounting check of the fit (it holds by construction when the RAS meets its margins; the test against "
        "Table 3.1 on BACI values is S07-R10). Retained imports implied by the fit, moved to the cumulative-total basis (chapter-table excess of imports "
        "and of re-exports taken out at factor a), equal Table 3.1 retained imports within 0.5% (HK$ '000). "
        "The all-goods ratio on the chapter basis is reported beside it",
        f'implied {ret_total_basis:.0f}; Table 3.1 {dig["retained"] * 1000:.0f}; RAS shortfall {tot - fitted:.0f}; '
        f'chapter-basis ratio {overall:.5f}; Table 3.1 ratio {published:.5f}',
        'implied - Table 3.1 between -0.5% and the RAS shortfall + 0.5% (the cap shortfall can only raise retained imports)',
        -0.005 * dig['retained'] * 1000 <= ret_total_basis - dig['retained'] * 1000 <= (tot - fitted) + 0.005 * dig['retained'] * 1000)
    return overall, a, published


def load_sg_ratios(con, raw, xlsx, checks, margin_factor):
    """Register sg_ret(cat, ratio) and hs_sgcat(hs6, cat); return the overall ratio."""
    def add(cid, kind, desc, value, threshold, passed):
        checks.append(dict(id=cid, kind=kind, desc=desc, value=str(value), threshold=str(threshold), passed=bool(passed)))

    rows = {}
    for path in ('M451001.json', 'M451001_imports.json'):
        for r in json.load(open(os.path.join(raw, 'sg', path)))['Data']['row']:
            rows[r['seriesNo']] = r
    bad_months = [s for s, r in rows.items() if _annual(r)[1] != 12]
    m_tot = _annual(rows['2'])[0]
    rx_tot = _annual(rows['5'])[0]
    m_leaf = sum(_annual(rows[m])[0] for m, _r in SG_CATEGORY.values())
    rx_leaf = sum(_annual(rows[x])[0] for _m, x in SG_CATEGORY.values())
    add('PREP-R-SG-SECTIONS', 'hard',
        'SingStat M451001 2022: 12 months per series; category imports and re-exports add to their totals within 0.1% (thousand SGD)',
        f'imports {m_leaf:.0f} vs {m_tot:.0f}; re-exports {rx_leaf:.0f} vs {rx_tot:.0f}; series short of 12 months {bad_months}',
        'gap <= 0.1%', not bad_months and abs(m_leaf - m_tot) <= 1e-3 * m_tot and abs(rx_leaf - rx_tot) <= 1e-3 * rx_tot)
    # Re-export share of total exports by category over the all-goods share (SingStat
    # M451001 series 3 and 5). It scales the destination share of the SGP funded step,
    # which SingStat publishes by market only.
    # Oil bunkers (3.1.2, no re-exports) are not in BACI, so oil and the total use exports
    # without bunkers: oil is petroleum (3.1.1, 5.1.1).
    tx_tot = _annual(rows['3'])[0] - _annual(rows['3.1.2'])[0]
    rx_factor = []
    for cat, (_m, x) in SG_CATEGORY.items():
        xs = '5.1.1' if cat == 'oil' else x
        tv, xv = _annual(rows['3' + xs[1:]])[0], _annual(rows[xs])[0]
        if tv > 0:
            rx_factor.append((cat, tv, xv, (xv / tv) / (rx_tot / tx_tot)))
    con.execute('CREATE TABLE sg_rx_factor(cat VARCHAR, exports DOUBLE, reexports DOUBLE, f DOUBLE)')
    con.executemany('INSERT INTO sg_rx_factor VALUES (?, ?, ?, ?)', rx_factor)
    add('PREP-R-SG-RXSHARE', 'report',
        'SingStat 2022 re-exports / total exports by category, and over the all-goods share, oil bunkers '
        'excluded (category margin of the SGP funded re-export fit, PREP-R-SG-FIT)',
        '; '.join(f'{c} {x / t:.3f} (x{f:.3f})' for c, t, x, f in rx_factor) + f'; all goods {rx_tot / tx_tot:.3f}',
        'report', True)
    ratios = []
    bad = []
    for cat, (m, x) in SG_CATEGORY.items():
        mv, xv = _annual(rows[m])[0], _annual(rows[x])[0]
        if mv <= 0 or xv > mv:
            bad.append(cat)
            continue
        ratios.append((cat, mv, xv, 1.0 - margin_factor * xv / mv))
    add('PREP-R-SG-RATIO', 'hard', 'Every SingStat category has re-exports <= imports', bad or 'ok', 'none', not bad)
    con.execute('CREATE TABLE sg_ret(cat VARCHAR, imports DOUBLE, reexports DOUBLE, ratio DOUBLE)')
    con.executemany('INSERT INTO sg_ret VALUES (?, ?, ?, ?)', ratios)
    # HS6 -> one SingStat category through the UNSD HS2017-SITC Rev.4 conversion table
    # (one SITC subgroup per HS6; the correlation sheet splits codes such as integrated
    # circuits 854231-39 over several sections).
    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    ws = wb['Conversion HS17-SITC4']
    linked = defaultdict(set)
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i < 1 or row[0] is None or row[1] is None:
            continue
        s = str(row[1]).strip()
        hs6 = str(row[0]).strip().zfill(6)
        if not s or not s[0].isdigit():
            linked[hs6].add('BAD')
        elif s.startswith('33'):
            linked[hs6].add('oil')
        elif s[0] in ('3', '9'):
            linked[hs6].add('misc')
        else:
            linked[hs6].add(s[0])
    wb.close()
    one = [(h, next(iter(c))) for h, c in linked.items() if len(c) == 1 and 'BAD' not in c]
    con.execute('CREATE TABLE hs_sgcat(hs6 VARCHAR, cat VARCHAR)')
    con.executemany('INSERT INTO hs_sgcat VALUES (?, ?)', one)
    # BACI residual codes (e.g. 271000) are not HS2017 codes. They take the category of their
    # HS4 heading when every HS2017 code under it has the same one.
    by4 = defaultdict(set)
    for h, c in one:
        by4[h[:4]].add(c)
    four = [(h4, next(iter(c))) for h4, c in by4.items() if len(c) == 1]
    con.execute('CREATE TABLE hs4_sgcat(hs4 VARCHAR, cat VARCHAR)')
    con.executemany('INSERT INTO hs4_sgcat VALUES (?, ?)', four)
    add('PREP-R-SG-HS', 'report',
        'HS2017 codes with one SingStat category in the UNSD conversion table; HS4 headings with one category '
        '(used for BACI codes outside HS2017). Value coverage is in S07-R9',
        f'HS6 {len(one)} of {len(linked)}; HS4 {len(four)} of {len(by4)}', 'report', True)
    return 1.0 - margin_factor * rx_tot / m_tot


def load_nl_ratios(con, raw, checks):
    """Register nl_ret(section, ratio) from the CBS world rows; return (overall ratio, totals in million EUR)."""
    def add(cid, kind, desc, value, threshold, passed):
        checks.append(dict(id=cid, kind=kind, desc=desc, value=str(value), threshold=str(threshold), passed=bool(passed)))

    typed = json.load(open(os.path.join(raw, 'cbs', 'typed_2022.json')))['value']
    sitc = {r['Key']: (r.get('Title') or '').strip() for r in json.load(open(os.path.join(raw, 'cbs', 'sitc.json')))['value']}
    rows = {}
    for r in typed:
        if r['Perioden'] != '2022JJ00' or r['Landen'] != CBS_WORLD:
            continue
        key = 'TOTAL' if r['SITC'] == CBS_TOTAL else sitc.get(r['SITC'], '')[:1]
        rows[key] = (float(r['TotaleInvoerwaarde_1'] or 0), float(r['DoorvoerwaardeInkomend_2'] or 0),
                     float(r['Wederuitvoerwaarde_4'] or 0))
    sections = sorted(k for k in rows if k.isdigit())
    tot = rows.get('TOTAL', (0.0, 0.0, 0.0))
    sums = [sum(rows[k][i] for k in sections) for i in range(3)]
    # Whole million EUR per cell: ten sections can miss the total by a few units.
    add('PREP-R-NL-SECTIONS', 'hard',
        'CBS 85429NED 2022 world rows: ten SITC sections, and the sections add to the total imports, incoming transit '
        'and re-exports within 10 million EUR',
        f'sections {len(sections)}; imports {sums[0]:.0f} vs {tot[0]:.0f}; transit {sums[1]:.0f} vs {tot[1]:.0f}; '
        f're-exports {sums[2]:.0f} vs {tot[2]:.0f}',
        '10 sections; gaps <= 10', len(sections) == 10 and all(abs(a - b) <= 10 for a, b in zip(sums, tot)))
    ratios, bad = [], []
    for k in sections:
        imp, door, rx = rows[k]
        nat = imp - door
        if nat <= 0 or rx > nat:
            bad.append(k)
            continue
        ratios.append((k, imp, door, rx, 1.0 - rx / nat))
    add('PREP-R-NL-RATIO', 'hard', 'Every CBS section has re-exports <= national imports (total imports less incoming transit)',
        bad or 'ok', 'none', not bad)
    con.execute('CREATE TABLE nl_ret(section VARCHAR, imports DOUBLE, transit_in DOUBLE, reexports DOUBLE, ratio DOUBLE)')
    con.executemany('INSERT INTO nl_ret VALUES (?, ?, ?, ?, ?)', ratios)
    overall = 1.0 - tot[2] / (tot[0] - tot[1])
    add('PREP-R-NL-OVERALL', 'report',
        'CBS all-goods retained / national imports (million EUR): 1 - re-exports / (imports - incoming transit). '
        'Section ratios: ' + ', '.join(f'{k} {r:.3f}' for k, _i, _d, _x, r in ratios),
        f'imports {tot[0]:.0f}; incoming transit {tot[1]:.0f}; re-exports {tot[2]:.0f}; ratio {overall:.4f}',
        'report', True)
    return overall, dict(imports=tot[0], transit_in=tot[1], reexports=tot[2])


def hk_margin(con, raw, a, usd_hkd, iso2, iso_to_region, checks):
    """Move the Hong Kong re-export margin from the origin's goods exports to HKG trd exports.

    margin(o, d) = (1 - a) x re-exports(o, d) / usd_hkd (Trade-IDDS rx_od, HK$ thousand -> USD thousand).
    Each origin -> destination BACI flow is scaled down by the margin over its value, never below zero.
    Re-exports back to the origin (o = d) have no BACI flow to take from (S07 drops single-country
    diagonals) and are reported, not booked. Writes hk_margin(dest, value) in thousand USD.
    """
    def add(cid, kind, desc, value, threshold, passed):
        checks.append(dict(id=cid, kind=kind, desc=desc, value=str(value), threshold=str(threshold), passed=bool(passed)))

    def region(code):
        if code in HK_NOT_ECONOMY or code not in iso2:
            return ''
        return iso_to_region.get(iso2[code], '')

    want = defaultdict(float)
    skipped = defaultdict(float)
    total_rx = 0.0
    for r in json.load(open(os.path.join(raw, 'hk', 'rx_od.json'))):
        if r.get('unitEN', "HK$ '000") != "HK$ '000" or str(r.get('period')) != '2022':
            raise SystemExit('unexpected unit or period in rx_od.json')
        v = _num(r['figure'])
        total_rx += v
        o, d = region(r['co']), region(r['cc'])
        m = (1.0 - a) * v / usd_hkd
        if not o or not d:
            skipped['unmapped'] += m
        elif o == d:
            skipped['to_origin'] += m
        elif 'HKG' in (o, d):
            skipped['hkg'] += m
        else:
            want[(o, d)] += m
    con.execute('CREATE TABLE hkm_want(exporter VARCHAR, importer VARCHAR, margin DOUBLE)')
    con.executemany('INSERT INTO hkm_want VALUES (?, ?, ?)', [(o, d, m) for (o, d), m in want.items()])
    con.execute("""
        CREATE TABLE hkm AS
        SELECT w.exporter, w.importer, w.margin, COALESCE(t.total, 0) AS total,
               LEAST(w.margin, COALESCE(t.total, 0)) AS applied,
               CASE WHEN COALESCE(t.total, 0) > 0 THEN GREATEST(0, 1 - w.margin / t.total) ELSE 1 END AS factor
        FROM hkm_want w
        LEFT JOIN (SELECT exporter, importer, SUM(value) AS total FROM flows WHERE value > 0 GROUP BY 1, 2) t
          USING (exporter, importer)
    """)
    before = con.execute('SELECT COALESCE(SUM(value), 0) FROM flows').fetchone()[0]
    con.execute("""
        UPDATE flows SET value = flows.value * h.factor, qty = NULL, qty_ok = FALSE
        FROM hkm h
        WHERE flows.exporter = h.exporter AND flows.importer = h.importer AND flows.value > 0 AND h.factor < 1
    """)
    after = con.execute('SELECT COALESCE(SUM(value), 0) FROM flows').fetchone()[0]
    applied, wanted, short = con.execute(
        'SELECT COALESCE(SUM(applied), 0), COALESCE(SUM(margin), 0), COALESCE(SUM(margin - applied), 0) FROM hkm').fetchone()
    con.execute('CREATE TABLE hk_margin AS SELECT importer AS dest, SUM(applied) AS value FROM hkm WHERE applied > 0 GROUP BY 1')
    add('PREP-R-HK-MARGIN', 'hard',
        'HKG re-export margin: the BACI origin -> destination flows fall by exactly the margin booked as HKG trd exports '
        '(thousand USD, tolerance 1), and no flow turns negative',
        f'flows {before:.0f} -> {after:.0f} (change {before - after:.3f}); booked {applied:.3f}',
        'change = booked', abs((before - after) - applied) <= 1.0)
    add('PREP-R-HK-MARGIN-R', 'report',
        'HKG re-export margin (1 - a) x Trade-IDDS re-exports by origin x consignment, USD thousand',
        f'a {a:.6f}; HK$/USD {usd_hkd}; re-exports {total_rx:.0f} HK$ thousand; margin wanted on mapped pairs {wanted:.0f}; '
        f'booked {applied:.0f}; short (flow below margin) {short:.0f}; not booked: back to origin {skipped["to_origin"]:.0f}, '
        f'HKG partner {skipped["hkg"]:.0f}, unmapped {skipped["unmapped"]:.0f}',
        'report', True)
    return dict(applied=applied, wanted=wanted, short=short, to_origin=skipped['to_origin'],
                hkg=skipped['hkg'], unmapped=skipped['unmapped'], a=a, usd_hkd=usd_hkd)


def fit_sg_identified(con, checks):
    """SGP re-export share by destination x SingStat category, fitted to both SingStat margins.

    SingStat publishes the re-export share of SGP exports by market (M451521/M451501) and by
    category (M451001), not the two together. Capped RAS on current BACI SGP exports by
    destination x category (seed and cap): destination totals are share(dest) x exports(dest),
    category totals are re-exports/total exports(cat) x exports(cat), scaled to the same total
    (the destination basis, as in the uniform step). Writes sg_ident(dest, cat, factor).
    """
    def add(cid, kind, desc, value, threshold, passed):
        checks.append(dict(id=cid, kind=kind, desc=desc, value=str(value), threshold=str(threshold), passed=bool(passed)))

    rows = con.execute("""
        SELECT f.importer, COALESCE(c.cat, c4.cat, 'none'), SUM(f.value), MAX(s.share)
        FROM flows f
        JOIN sg_share s ON s.dest = f.importer
        LEFT JOIN hs_sgcat c ON c.hs6 = f.hs6
        LEFT JOIN hs4_sgcat c4 ON c4.hs4 = substr(f.hs6, 1, 4) AND c.hs6 IS NULL
        WHERE f.exporter = 'SGP' AND f.value > 0 AND s.share > 0
        GROUP BY 1, 2
    """).fetchall()
    share = {d: sh for d, _c, _x, sh in rows}
    seed = {(d, c): x for d, c, x, _sh in rows if x > 0}
    x_d = defaultdict(float)
    x_c = defaultdict(float)
    for (d, c), x in seed.items():
        x_d[d] += x
        x_c[c] += x
    r_c = {c: xv / tv for c, tv, xv, _f in con.execute('SELECT cat, exports, reexports, f FROM sg_rx_factor').fetchall()}
    unmapped = x_c.get('none', 0.0)
    row_t = {d: share[d] * x for d, x in x_d.items()}
    tot = sum(row_t.values())
    col_raw = {c: r_c.get(c, 0.0) * x for c, x in x_c.items()}
    k = tot / sum(col_raw.values())
    col_t = {c: v * k for c, v in col_raw.items()}
    fit, iters, g = capped_ras(seed, row_t, col_t)
    con.execute('CREATE TABLE sg_ident(dest VARCHAR, cat VARCHAR, factor DOUBLE)')
    con.executemany('INSERT INTO sg_ident VALUES (?, ?, ?)', [(d, c, fit[(d, c)] / x) for (d, c), x in seed.items()])
    by_c = defaultdict(float)
    for (d, c), v in fit.items():
        by_c[c] += v
    add('PREP-R-SG-FIT', 'report',
        'SGP re-exports by destination x category: capped RAS on BACI SGP exports to the SingStat destination '
        'shares and the SingStat category shares (category margin scaled to the destination total). '
        'Fitted category share against SingStat',
        f'sweeps {iters}; largest relative margin gap {g:.2e}; fitted {sum(fit.values()):.0f} of {tot:.0f} kUSD; '
        f'category scale {k:.4f}; unmapped exports {unmapped:.0f}; '
        + '; '.join(f'{c} {by_c[c] / x_c[c]:.3f} vs {r_c.get(c, 0.0):.3f}' for c in sorted(x_c)),
        'report', True)
    add('PREP-R-SG-FIT-H', 'hard', 'Every SGP export cell is categorised and the fit leaves no cell above its export',
        f'unmapped {unmapped:.0f}; above cap {sum(1 for kk, v in fit.items() if v > seed[kk] * (1 + 1e-9))}', '0; 0',
        unmapped == 0 and all(v <= seed[kk] * (1 + 1e-9) for kk, v in fit.items()))


def identified_sg_fitted():
    """SGP re-exports identified per destination x HS6 at the fitted destination x category factor."""
    return """
        SELECT f.importer AS dest, f.hs6, f.value AS export_value, f.value * i.factor AS identified
        FROM flows f
        LEFT JOIN hs_sgcat c ON c.hs6 = f.hs6
        LEFT JOIN hs4_sgcat c4 ON c4.hs4 = substr(f.hs6, 1, 4) AND c.hs6 IS NULL
        JOIN sg_ident i ON i.dest = f.importer AND i.cat = COALESCE(c.cat, c4.cat, 'none')
        WHERE f.exporter = 'SGP' AND f.value > 0 AND i.factor > 0
    """


def ratio_sql(hub):
    """Ratio per gross hub-import cell (exporter, hs6), with the fallbacks named in a basis column."""
    if hub == 'HKG':
        return """
            SELECT g.exporter, g.hs6, g.gross,
                   COALESCE(r.ratio, k.ratio, (SELECT ratio FROM overall WHERE hub = 'HKG')) AS ratio,
                   CASE WHEN r.ratio IS NOT NULL THEN 'origin_hs2'
                        WHEN k.ratio IS NOT NULL THEN 'hs2_all_origins'
                        ELSE 'all_goods' END AS basis
            FROM gross g
            LEFT JOIN hk_ret r ON r.origin = g.exporter AND r.hs2 = substr(g.hs6, 1, 2)
            LEFT JOIN hk_ret_hs2 k ON k.hs2 = substr(g.hs6, 1, 2)
        """
    if hub == 'NLD':
        # hs_section is the UNSD HS2017-SITC section table of the NLD re-export step.
        return """
            SELECT g.exporter, g.hs6, g.gross,
                   COALESCE(n.ratio, (SELECT ratio FROM overall WHERE hub = 'NLD')) AS ratio,
                   CASE WHEN n.ratio IS NOT NULL THEN 'section' ELSE 'all_goods' END AS basis
            FROM gross g
            LEFT JOIN hs_section h ON h.hs6 = g.hs6
            LEFT JOIN nl_ret n ON n.section = h.section
        """
    return """
        SELECT g.exporter, g.hs6, g.gross,
               COALESCE(s.ratio, s4.ratio, (SELECT ratio FROM overall WHERE hub = 'SGP')) AS ratio,
               CASE WHEN s.ratio IS NOT NULL THEN 'category'
                    WHEN s4.ratio IS NOT NULL THEN 'category_hs4'
                    ELSE 'all_goods' END AS basis
        FROM gross g
        LEFT JOIN hs_sgcat c ON c.hs6 = g.hs6
        LEFT JOIN sg_ret s ON s.cat = c.cat
        LEFT JOIN hs4_sgcat c4 ON c4.hs4 = substr(g.hs6, 1, 4) AND c.hs6 IS NULL
        LEFT JOIN sg_ret s4 ON s4.cat = c4.cat
    """


def snapshot(con, hub, tag):
    con.execute(f'DROP TABLE IF EXISTS ri_{tag}_{hub}')
    con.execute(f"""
        CREATE TABLE ri_{tag}_{hub} AS
        SELECT exporter, hs6, value FROM flows WHERE importer = '{hub}' AND exporter <> '{hub}'
    """)


def apply(con, hub):
    """Set hub import cells to min(current, ratio x gross). Returns totals in thousand USD."""
    for t in ('gross', 'target'):
        con.execute(f'DROP TABLE IF EXISTS {t}')
    # gross = before the hub's own step + what later hubs moved in (current - after own step).
    con.execute(f"""
        CREATE TABLE gross AS
        SELECT exporter, hs6,
               COALESCE(p.value, 0) + COALESCE(c.value, 0) - COALESCE(a.value, 0) AS gross,
               COALESCE(c.value, 0) AS current
        FROM ri_pre_{hub} p
        FULL JOIN ri_post_{hub} a USING (exporter, hs6)
        FULL JOIN (SELECT exporter, hs6, value FROM flows WHERE importer = '{hub}' AND exporter <> '{hub}') c
          USING (exporter, hs6)
    """)
    con.execute(f"""
        CREATE TABLE target AS
        SELECT r.exporter, r.hs6, r.gross, g.current, r.ratio, r.basis,
               LEAST(g.current, GREATEST(r.ratio, 0) * GREATEST(r.gross, 0)) AS final
        FROM ({ratio_sql(hub)}) r
        JOIN gross g USING (exporter, hs6)
    """)
    con.execute(f"""
        UPDATE flows SET value = t.final, qty = NULL, qty_ok = FALSE
        FROM target t
        WHERE flows.importer = '{hub}' AND flows.exporter = t.exporter AND flows.hs6 = t.hs6
          AND t.final < flows.value
    """)
    st = con.execute("""
        SELECT SUM(gross), SUM(current), SUM(final), SUM(current - final),
               COUNT(*) FILTER (WHERE final < current),
               SUM(current - final) FILTER (WHERE basis NOT IN ('origin_hs2', 'category')),
               COUNT(*) FILTER (WHERE final > current + 1e-9)
        FROM target
    """).fetchone()
    by_basis = {b: (g or 0.0, f or 0.0) for b, g, f in con.execute(
        'SELECT basis, SUM(gross), SUM(final) FROM target GROUP BY basis ORDER BY basis').fetchall()}
    return dict(gross=st[0] or 0.0, before=st[1] or 0.0, after=st[2] or 0.0, removed=st[3] or 0.0,
                cells=st[4] or 0, fallback_removed=st[5] or 0.0, raised=st[6] or 0, by_basis=by_basis)
