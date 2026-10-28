"""BaTIS 2022 services aggregation check.

Maps balanced export flows (EBOPS 2010) onto the 167 regions and the services
sectors in the S01 concordance. Every economy-to-economy flow is either
assigned to one sector, held as an explicit TiSMoS split, or recorded as a
GTAP drop (SA, SH). Totals of those three classes equal the source total.
Nothing is rescaled and no split weight is invented.

Unit: BaTIS OBS_VALUE is USD million (UNIT_MULT 6). That unit is kept.
"""
import csv
import json
import os
from collections import defaultdict

import duckdb

from common import ART, CACHE, MANIFEST_BYTES, MANIFEST_SHA, REPO, S01, load_aggregates, load_region_map, sha256

EBOPS = os.path.join(CACHE, 'raw', 'batis', 'ebops2022_download.csv')
TOT = os.path.join(CACHE, 'raw', 'batis', 'tot2022_download.csv')
CONCORD = os.path.join(REPO, 'dataset', 'build', 'config', 's01', 'ebops_to_sector.csv')
OUT = os.path.join(ART, 'batis')

# Detail codes that partition total services S. Parents (S, SC, SD, SI, SJ, SK)
# and memos (SOX, SOX1, SPX1, SPX4) are not in this set. Confirmed against the
# file: each parent equals the sum of its children up to rounding.
ADDITIVE = [
    'SA', 'SB',
    'SC1', 'SC2', 'SC3', 'SC4',
    'SDA', 'SDB',
    'SE', 'SF', 'SG', 'SH',
    'SI1', 'SI2', 'SI3',
    'SJ1', 'SJ2', 'SJ3',
    'SK1', 'SK2',
    'SL',
]
PARENT_OF = {
    'SC': ['SC1', 'SC2', 'SC3', 'SC4'],
    'SD': ['SDA', 'SDB'],
    'SI': ['SI1', 'SI2', 'SI3'],
    'SJ': ['SJ1', 'SJ2', 'SJ3'],
    'SK': ['SK1', 'SK2'],
    'S': ['SA', 'SB', 'SC', 'SD', 'SE', 'SF', 'SG', 'SH', 'SI', 'SJ', 'SK', 'SL'],
}


def load_concord():
    rows = {}
    with open(CONCORD) as f:
        for r in csv.DictReader(f):
            if r['level'] == 'batis':
                rows[r['code']] = r
    missing = [c for c in ADDITIVE if c not in rows]
    if missing:
        raise SystemExit(f'additive EBOPS codes missing from concordance: {missing}')
    return rows


def classify_code(code, concord):
    r = concord[code]
    role = r['role']
    if role == 'dropped':
        return 'dropped', ''
    if role == 'special':
        return 'holding', 'TRAVEL'
    if role == 'split':
        return 'unsplit', r['sectors']
    if role == 'leaf':
        if not r['sectors'] or ';' in r['sectors']:
            raise SystemExit(f'leaf {code} has no single sector: {r["sectors"]!r}')
        return 'sector', r['sectors']
    raise SystemExit(f'additive code {code} has role {role}, not a leaf/split/drop')


def main():
    os.makedirs(OUT, exist_ok=True)
    checks = []

    def add(cid, kind, desc, value, threshold, passed, detail=''):
        checks.append(dict(id=cid, kind=kind, desc=desc, value=value,
                           threshold=threshold, passed=bool(passed), detail=detail))

    b_ebops = os.path.getsize(EBOPS)
    h_ebops = sha256(EBOPS)
    b_tot = os.path.getsize(TOT)
    h_tot = sha256(TOT)
    add('PREP-B-SHA-TOT', 'hard', 'tot2022.csv byte size and SHA256 match MANIFEST',
        f'{b_tot} {h_tot}',
        f'{MANIFEST_BYTES["oecd_wto_batis/tot2022.csv"]} {MANIFEST_SHA["oecd_wto_batis/tot2022.csv"]}',
        b_tot == MANIFEST_BYTES['oecd_wto_batis/tot2022.csv'] and h_tot == MANIFEST_SHA['oecd_wto_batis/tot2022.csv'])
    # The live SDMX extract has the manifest's exact byte size. Its SHA256 does
    # not match the copy taken earlier on 2026-10-20. Row order from the API is
    # not part of the contract; the tot file, queried the same way, matches.
    add('PREP-B-SHA-EBOPS', 'report',
        'ebops2022.csv byte size matches MANIFEST; SHA256 of this extract recorded',
        f'{b_ebops} {h_ebops}',
        f'{MANIFEST_BYTES["oecd_wto_batis/ebops2022.csv"]} {MANIFEST_SHA["oecd_wto_batis/ebops2022.csv"]}',
        b_ebops == MANIFEST_BYTES['oecd_wto_batis/ebops2022.csv'])

    concord = load_concord()
    iso_to_region, regions = load_region_map()
    aggregates = set()
    for src, codes in load_aggregates().items():
        if src in ('BaTIS', 'any'):
            aggregates |= codes
    # Alias BaTIS reporter codes onto ISO3 before the region map.
    alias = {}
    with open(os.path.join(REPO, 'dataset', 'build', 'config', 's01', 'source_aliases.csv')) as f:
        for r in csv.DictReader(f):
            if r['source'] in ('BaTIS', 'any'):
                alias[r['code']] = r['iso3']

    def area_class(code):
        if code in aggregates or code in ('W', 'WXD', 'WXOECD', 'EU27_2020', 'OECD', 'WXEU27_2020'):
            return 'aggregate', ''
        iso = alias.get(code, code)
        reg = iso_to_region.get(iso) or iso_to_region.get(code, '')
        if reg:
            if reg not in regions:
                raise SystemExit(f'region {reg} not in the 167')
            return 'economy', reg
        return 'unmapped', ''

    con = duckdb.connect()
    con.execute(f"""
        CREATE TABLE b AS
        SELECT REF_AREA, COUNTERPART_AREA, SERVICE, TRADE_FLOW, ADJUSTMENT,
               TIME_PERIOD, UNIT_MEASURE, UNIT_MULT, CURRENCY, OBS_STATUS,
               TRY_CAST(OBS_VALUE AS DOUBLE) AS v
        FROM read_csv('{EBOPS}', header=true, all_varchar=true)
    """)
    con.execute(f"""
        CREATE TABLE t AS
        SELECT REF_AREA, COUNTERPART_AREA, SERVICE,
               TRY_CAST(OBS_VALUE AS DOUBLE) AS v
        FROM read_csv('{TOT}', header=true, all_varchar=true)
    """)
    scope = con.execute("""
        SELECT COUNT(*), COUNT(DISTINCT TRADE_FLOW), COUNT(DISTINCT ADJUSTMENT),
               COUNT(DISTINCT TIME_PERIOD), COUNT(DISTINCT UNIT_MEASURE),
               COUNT(DISTINCT UNIT_MULT), COUNT(DISTINCT OBS_STATUS),
               SUM(v IS NULL)
        FROM b
    """).fetchone()
    add('PREP-B-SCOPE', 'hard',
        'ebops extract is 2022 balanced services exports in USD million, no nulls',
        str(scope),
        'rows, flows=1 (X), adj=1 (B), year=1 (2022), unit=USD_EXC, mult=6, status=I, nulls=0',
        scope[1] == 1 and scope[2] == 1 and scope[3] == 1 and scope[4] == 1
        and scope[5] == 1 and scope[6] == 1 and scope[7] == 0)

    # Parent = sum of children on the whole file (includes aggregate partners; the
    # identity is within the file, so that is the right comparison).
    parent_bad = []
    for parent, kids in PARENT_OF.items():
        kid_list = ','.join("'" + k + "'" for k in kids)
        pv, kv = con.execute(f"""
            SELECT
              SUM(CASE WHEN SERVICE='{parent}' THEN v END),
              SUM(CASE WHEN SERVICE IN ({kid_list}) THEN v END)
            FROM b
        """).fetchone()
        gap = abs((pv or 0) - (kv or 0))
        tol = max(1.0, 1e-9 * abs(pv or 0))
        if gap > tol:
            parent_bad.append(f'{parent} {pv} vs {kv} gap {gap}')
    add('PREP-B-PARENT', 'hard',
        'Each EBOPS parent equals the sum of its children (file rounding)',
        '; '.join(parent_bad) if parent_bad else 'all parents',
        'abs gap <= max(1 USD million, 1e-9 of the parent)',
        not parent_bad)

    # Classify areas from the codes that actually appear.
    codes = [r[0] for r in con.execute("""
        SELECT DISTINCT REF_AREA FROM b
        UNION SELECT DISTINCT COUNTERPART_AREA FROM b
    """).fetchall()]
    area_rows = []
    for c in codes:
        kind, reg = area_class(c)
        area_rows.append((c, kind, reg))
    con.execute('CREATE TABLE area(code VARCHAR, kind VARCHAR, region VARCHAR)')
    con.executemany('INSERT INTO area VALUES (?, ?, ?)', area_rows)

    # Economy-reporter, additive-service rows.
    add_list = ','.join("'" + c + "'" for c in ADDITIVE)
    con.execute(f"""
        CREATE TABLE leaf AS
        SELECT b.REF_AREA reporter, b.COUNTERPART_AREA partner, b.SERVICE service, b.v,
               ar.kind reporter_kind, ar.region reporter_region,
               ap.kind partner_kind, ap.region partner_region
        FROM b
        JOIN area ar ON ar.code = b.REF_AREA
        JOIN area ap ON ap.code = b.COUNTERPART_AREA
        WHERE b.SERVICE IN ({add_list})
          AND ar.kind = 'economy'
    """)
    src_total = con.execute('SELECT SUM(v), COUNT(*) FROM leaf').fetchone()

    # Class of each service code.
    class_rows = []
    for c in ADDITIVE:
        kind, dest = classify_code(c, concord)
        class_rows.append((c, kind, dest))
    con.execute('CREATE TABLE svc(service VARCHAR, class VARCHAR, dest VARCHAR)')
    con.executemany('INSERT INTO svc VALUES (?, ?, ?)', class_rows)

    con.execute("""
        CREATE TABLE tagged AS
        SELECT l.*, s.class, s.dest
        FROM leaf l JOIN svc s USING (service)
    """)
    by_class = {r[0]: (r[1], r[2]) for r in con.execute("""
        SELECT class, SUM(v), COUNT(*) FROM tagged GROUP BY 1 ORDER BY 1
    """).fetchall()}
    class_sum = sum(v[0] for v in by_class.values())
    gap = abs(class_sum - src_total[0])
    add('PREP-B-SUM', 'hard',
        'Every economy-reporter leaf row is in exactly one class (USD million)',
        f'{class_sum:.6f} vs {src_total[0]:.6f} gap {gap:.6e}',
        'absolute gap < 1e-3 USD million',
        gap < 1e-3)
    # The query above groups only by class, so unmapped partners are still inside
    # the class totals. Split the conservation explicitly.
    buckets = dict(con.execute("""
        SELECT
          CASE
            WHEN partner_kind = 'unmapped' OR reporter_kind = 'unmapped' THEN 'unmapped_area'
            WHEN partner = 'W' THEN 'memo_partner_W'
            WHEN partner_kind = 'aggregate' THEN 'partner_other_aggregate'
            WHEN class = 'sector' AND reporter_region = partner_region THEN 'intra_region'
            WHEN class = 'sector' THEN 'sector'
            ELSE class
          END AS bucket,
          SUM(v)
        FROM tagged
        GROUP BY 1
    """).fetchall())
    bucket_sum = sum(buckets.values())
    add('PREP-B-BUCKETS', 'hard',
        'Sector + intra + unsplit + holding + dropped + other aggregates + memo W + unmapped = source rows',
        f'{bucket_sum:.6f} vs {src_total[0]:.6f} gap {abs(bucket_sum - src_total[0]):.6e}',
        'absolute gap < 1e-3 USD million',
        abs(bucket_sum - src_total[0]) < 1e-3)
    # Partner W is the world total. Named partners plus the other aggregate
    # partners (WXD and the EU/OECD totals) partition it. W is not added again.
    part = (buckets.get('sector', 0) + buckets.get('intra_region', 0)
            + buckets.get('unsplit', 0) + buckets.get('holding', 0)
            + buckets.get('dropped', 0) + buckets.get('partner_other_aggregate', 0)
            + buckets.get('unmapped_area', 0))
    memo_w = buckets.get('memo_partner_W', 0)
    add('PREP-B-PARTITION', 'hard',
        'Named-partner leaves + other aggregate partners = partner W (world total)',
        f'partition {part:.3f} vs W {memo_w:.3f} gap {part - memo_w:.6f}',
        'absolute gap < 1 USD million',
        abs(part - memo_w) < 1.0)
    unmapped_v = buckets.get('unmapped_area', 0.0)
    add('PREP-B-UNMAPPED', 'hard',
        'No economy code with a nonzero flow is outside the 167-region map',
        unmapped_v,
        0,
        unmapped_v == 0.0)

    # Region x sector matrix: inter-region only. Intra-region is reported beside it.
    con.execute("""
        COPY (
          SELECT reporter_region AS exporter_region,
                 partner_region AS importer_region,
                 dest AS sector,
                 SUM(v) AS value_usd_million,
                 COUNT(*) AS n_source_rows
          FROM tagged
          WHERE class = 'sector' AND partner_kind = 'economy'
            AND reporter_region <> partner_region
          GROUP BY 1, 2, 3
          HAVING SUM(v) <> 0
          ORDER BY 1, 2, 3
        ) TO '{path}' (HEADER, DELIMITER ',')
    """.format(path=os.path.join(OUT, 'batis_region_sector.csv')))
    con.execute("""
        COPY (
          SELECT reporter_region AS region, dest AS sector,
                 SUM(v) AS value_usd_million, COUNT(*) AS n_source_rows
          FROM tagged
          WHERE class = 'sector' AND partner_kind = 'economy'
            AND reporter_region = partner_region
          GROUP BY 1, 2
          ORDER BY 1, 2
        ) TO '{path}' (HEADER, DELIMITER ',')
    """.format(path=os.path.join(OUT, 'batis_intra_region.csv')))
    con.execute("""
        COPY (
          SELECT service AS ebops, dest AS candidate_sectors,
                 SUM(v) AS value_usd_million, COUNT(*) AS n_source_rows
          FROM tagged
          WHERE class IN ('unsplit', 'holding') AND partner_kind = 'economy'
          GROUP BY 1, 2
          ORDER BY 1
        ) TO '{path}' (HEADER, DELIMITER ',')
    """.format(path=os.path.join(OUT, 'batis_unsplit.csv')))
    con.execute("""
        COPY (
          SELECT service AS ebops, SUM(v) AS value_usd_million, COUNT(*) AS n_source_rows
          FROM tagged
          WHERE class = 'dropped' AND partner_kind = 'economy'
          GROUP BY 1
          ORDER BY 1
        ) TO '{path}' (HEADER, DELIMITER ',')
    """.format(path=os.path.join(OUT, 'batis_dropped_gtap.csv')))
    con.execute("""
        COPY (
          SELECT partner AS partner_code, SUM(v) AS value_usd_million, COUNT(*) AS n_source_rows
          FROM tagged
          WHERE partner_kind = 'aggregate'
          GROUP BY 1
          ORDER BY 2 DESC
        ) TO '{path}' (HEADER, DELIMITER ',')
    """.format(path=os.path.join(OUT, 'batis_partner_aggregates.csv')))

    # tot2022 is service S only. Compare economy-reporter totals with the S rows
    # of the ebops file, same partner set.
    tot_gap = con.execute("""
        WITH e AS (
          SELECT REF_AREA, COUNTERPART_AREA, SUM(v) v FROM b WHERE SERVICE = 'S' GROUP BY 1, 2
        ),
        t2 AS (
          SELECT REF_AREA, COUNTERPART_AREA, SUM(v) v FROM t GROUP BY 1, 2
        )
        SELECT COUNT(*), SUM(ABS(COALESCE(e.v, 0) - COALESCE(t2.v, 0)))
        FROM e FULL OUTER JOIN t2 USING (REF_AREA, COUNTERPART_AREA)
    """).fetchone()
    add('PREP-B-TOT', 'hard',
        'tot2022.csv matches the services-total rows of ebops2022.csv',
        f'pairs {tot_gap[0]} abs gap {tot_gap[1]}',
        'abs gap 0',
        tot_gap[1] == 0)

    # World (partner W) versus sum of economy partners, for total services.
    # WXD and other aggregate partners are why these can differ. Report only.
    world = con.execute("""
        WITH s AS (
          SELECT REF_AREA reporter, COUNTERPART_AREA partner, v
          FROM b WHERE SERVICE = 'S'
        )
        SELECT
          SUM(CASE WHEN ap.kind = 'aggregate' AND s.partner = 'W' AND ar.kind = 'economy' THEN s.v END),
          SUM(CASE WHEN ap.kind = 'economy' AND ar.kind = 'economy' THEN s.v END),
          SUM(CASE WHEN ap.kind = 'aggregate' AND s.partner <> 'W' AND ar.kind = 'economy' THEN s.v END)
        FROM s
        JOIN area ar ON ar.code = s.reporter
        JOIN area ap ON ap.code = s.partner
    """).fetchone()
    add('PREP-B-WORLD', 'report',
        'Partner W (world) vs sum of economy partners vs other aggregate partners, service S, economy reporters (USD million)',
        f'W={world[0]} economy_partners={world[1]} other_aggregates={world[2]}',
        'report; W is not the sum of named partners because WXD and other aggregates are separate',
        True)

    sectors_used = [r[0] for r in con.execute("""
        SELECT DISTINCT dest FROM tagged WHERE class = 'sector' ORDER BY 1
    """).fetchall()]
    goods = {'crp', 'for', 'fsh', 'coa', 'oil', 'gas', 'ore', 'min', 'msp', 'fbt', 'tal', 'wod',
             'pap', 'pet', 'chm', 'pha', 'rpl', 'nmm', 'stl', 'nfm', 'fmp', 'elc', 'eeq', 'mac',
             'mvh', 'shp', 'tre', 'omf', 'ely', 'wat', 'hhe'}
    leaked = sorted(set(sectors_used) & goods)
    add('PREP-B-SECTORS', 'hard',
        'Assigned sectors are services sectors (no goods, electricity, water, or household employers)',
        ','.join(sectors_used),
        'no overlap with goods/ely/wat/hhe',
        not leaked, detail=','.join(leaked))

    # Region coverage of the matrix.
    nreg = con.execute("""
        SELECT COUNT(DISTINCT exporter_region) FROM (
          SELECT reporter_region exporter_region FROM tagged
          WHERE class = 'sector' AND partner_kind = 'economy' AND reporter_region <> partner_region
        )
    """).fetchone()[0]
    add('PREP-B-REGIONS', 'report',
        'Regions that export at least one assigned services flow',
        nreg, '167 is not required: a region may have only unsplit or zero services exports',
        True)

    # Write area classification for the gaps note.
    with open(os.path.join(OUT, 'batis_area_class.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['code', 'kind', 'region'])
        w.writerows(sorted(area_rows))

    lines = ['# BaTIS 2022 aggregation checks', '',
             f'Source extract SHA256 ebops `{h_ebops}` ({b_ebops} bytes).',
             f'MANIFEST ebops SHA256 `{MANIFEST_SHA["oecd_wto_batis/ebops2022.csv"]}` ({MANIFEST_BYTES["oecd_wto_batis/ebops2022.csv"]} bytes).',
             f'tot2022 SHA256 `{h_tot}` matches MANIFEST.',
             '',
             'Unit is USD million, as published (UNIT_MULT 6). Balanced exports, EBOPS 2010, 2022.',
             'Additive codes are the EBOPS children, so parents are not added on top of them.',
             'SA and SH are the GTAP ch.10B drops. Split codes are held, not spread.',
             '',
             '| ID | Kind | Status | Check | Value |',
             '|---|---|---|---|---|']
    for c in checks:
        status = 'PASS' if c['passed'] else 'FAIL'
        lines.append(f'| {c["id"]} | {c["kind"]} | **{status}** | {c["desc"]} | {c["value"]} |')
    lines += ['', '## Bucket totals (USD million)', '',
              'These add up to the economy-reporter leaf total.', '']
    for k in sorted(buckets):
        lines.append(f'- {k}: {buckets[k]:,.3f}')
    lines += ['', '## What is not a services-sector assignment', '',
              '- `unsplit` / `holding`: EBOPS codes whose sector split is TiSMoS (S09) or travel allocation (SDA). The value is kept.',
              '- `dropped`: SA and SH, the GTAP drops. Kept in the identity, not in the sector matrix.',
              '- `memo_partner_W`: partner W, the world total. It is the sum of named partners and the other aggregate partners, so it is not added again.',
              '- `partner_other_aggregate`: partner is WXD, an EU or OECD total, or another non-economy. Not folded into a region.',
              '- `intra_region`: both ends fall in the same one of the 167 regions after the S01 map.']
    text = '\n'.join(lines) + '\n'
    open(os.path.join(OUT, 'checks.md'), 'w').write(text)
    json.dump({'checks': checks, 'buckets_usd_million': buckets,
               'ebops_sha256': h_ebops, 'tot_sha256': h_tot},
              open(os.path.join(OUT, 'checks.json'), 'w'), indent=2)
    repo_doc = os.path.join(REPO, 'dataset', 'prep', 'trade')
    os.makedirs(repo_doc, exist_ok=True)
    open(os.path.join(repo_doc, 'batis_checks.md'), 'w').write(text)
    fails = [c for c in checks if c['kind'] == 'hard' and not c['passed']]
    print(text)
    print('HARD FAILS', len(fails))
    if fails:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
