"""Report-only comparisons: customs collections, Census duty for the USA, USA by HS chapter.

customs_check, us_duty_benchmark, usa_customs_compare, usa_chapter_far. Nothing here
changes a rate; booked duty is never scaled to a collection figure.
"""
import csv
from collections import defaultdict

from .util import fnum

CENSUS_CHINA_CTY = '5700'
USITC_BN = 90.101    # cited in the S10 handoff; not recomputed
# usa_chapter_far: named reasons for a chapter far from Census, ex-China.
CH_232 = (72, 73, 76)
CH_CRUDE = (27,)
CH_NOCAP = (3, 6, 10, 17, 22, 23, 24, 33)


def census(path):
    tot = {'cal': 0.0, 'con': 0.0, 'chn_cal': 0.0, 'chn_con': 0.0}
    by_ch = defaultdict(lambda: [0.0, 0.0])
    with open(path, newline='') as fh:
        for row in csv.DictReader(fh):
            cal, con = float(row['cal_dut'] or 0.0), float(row['con_val'] or 0.0)
            tot['cal'] += cal
            tot['con'] += con
            hs6 = (row.get('hs6') or '').zfill(6)
            china = row['cty'] == CENSUS_CHINA_CTY
            if hs6[:2].isdigit():
                by_ch[int(hs6[:2])][0] += cal
                if not china:
                    by_ch[int(hs6[:2])][1] += cal
            if china:
                tot['chn_cal'] += cal
                tot['chn_con'] += con
    return tot, by_ch


def usa_chapters(usa_ch, census_ch):
    """Rows for usa_chapter_s10.csv, the unexplained far chapters, and the China-only ones."""
    rows, far, china_only = [], [], []
    for ch in range(1, 98):
        b = usa_ch.get(ch) or [0.0, 0.0, 0.0, 0.0]
        c = census_ch.get(ch) or [0.0, 0.0]
        if b[1] <= 0 and c[0] <= 0:
            continue
        b_bn, bx_bn, c_bn, cx_bn = b[0] / 1e6, b[2] / 1e6, c[0] / 1e9, c[1] / 1e9
        rx = bx_bn / cx_bn if cx_bn > 1e-9 else ''
        ra = b_bn / c_bn if c_bn > 1e-9 else ''
        far_x = abs(bx_bn - cx_bn) >= 0.02 and (rx == '' or rx < 0.5 or rx > 2.0)
        far_all = abs(b_bn - c_bn) >= 0.02 and (ra == '' or ra < 0.5 or ra > 2.0)
        reason = ''
        if far_x:
            klass = 'gtap_rule'
            if ch in CH_232 and bx_bn < cx_bn:
                reason = 'section_232_not_in_baseline'
            elif ch in CH_CRUDE and bx_bn < cx_bn:
                reason = 'hts_specific_cents_per_barrel_not_scaled'
            elif ch in CH_NOCAP and bx_bn > cx_bn:
                reason = 'statutory_above_census_no_cap'
            else:
                klass, reason = 'unexplained', 'no_named_reason'
                far.append(ch)
        elif far_all:
            klass, reason = 'gtap_rule', 'china_301_not_in_baseline'
            china_only.append(ch)
        else:
            klass = 'within_bar'
        rows.append([f'{ch:02d}', fnum(b_bn), fnum(b[1] / 1e6), fnum(bx_bn), fnum(b[3] / 1e6), fnum(c_bn), fnum(cx_bn),
                     fnum(rx) if rx != '' else '', fnum(bx_bn - cx_bn), klass, reason])
    return rows, far, china_only


def customs_rows(path, duty_region, region_set, iso_region, census_duty_m):
    rows, causes = [], defaultdict(int)
    with open(path, newline='') as fh:
        for row in csv.DictReader(fh):
            iso, collected, src = row['iso'], float(row['collected_million_usd'] or 0.0), row['source']
            cause = []
            if iso == 'USA':
                src += ' | OECD GRS T_5123, not Census'
            if 'GRS' in src:
                cause.append('statutory vs cash (E3)')
            if '2021' in src:
                cause.append('year-rule')
            if 'federal' in src.lower():
                cause.append('federal-only')
            if iso not in region_set:
                cause.append('not an S10 region; booked duty is the parent region total, a different unit')
            if not cause:
                cause.append('cash collection, report only (E3)')
            text = '; '.join(cause)
            causes[text] += 1
            booked = duty_region.get(iso) if iso in region_set else None
            ratio = fnum(booked / collected) if booked is not None and collected else ''
            rows.append([iso, fnum(collected), src, fnum(booked) if booked is not None else '', ratio,
                         iso if iso in region_set else iso_region.get(iso, ''), text,
                         'cash USD million vs booked duty on VCIF', fnum(census_duty_m) if iso == 'USA' else ''])
    rows.sort(key=lambda r: r[0])
    return rows, causes
