"""Extract line rates from the official tariff texts that WITS does not carry (S10).

Writes, beside each source folder, an extracted/ CSV of national lines with the 2022 rate
as printed. The stage reads the CSVs; this script needs pdftotext (poppler) and openpyxl.

    python3 dataset/build/tools/s10_extract_tariff_texts.py

New Caledonia: Tarif des douanes, consolidated 1 January 2023, DD column; the HS6 whose DD differed in 2022,
from the 2022 columns of DRDNC notice 22001425.
Tunisia: Lists I-III of Protocol I of the Türkiye-Tunisia FTA (needs LibreOffice for the .doc files).
Malaysia: the preferential schedules and gazetted orders whose 2022 rate can be read off a year
column, a "2019 and subsequent years" column or the last staging column (the final rate holds
after it): the bilateral FTAs, ACFTA, AHKFTA, ATIGA (P.U.(A) 199/2022), AKFTA (P.U.(A) 286/2015),
RCEP (P.U.(A) 64/2022, 2022 column) and CPTPP (P.U.(A) 406/2022, 2022 column). AJCEP is read from
Malaysia's schedule of categories: every staging category has reached its end rate by 2022.
A rate printed as specific, mixed, TRQ, unbound (U), excluded or not offered is kept as text with
pct blank. A line whose rate columns cannot be read is left out, so the line stays at MFN. Not
read: AIFTA (MICECA covers India) and AANZFTA (the only order here, P.U.(A) 220/2015, carries
rules of origin, not a schedule).
"""
import csv
import os
import re
import subprocess
import sys

import openpyxl

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data')
NUM = re.compile(r'^(\d+(?:[.,]\d+)?)%?$')


def pdf_lines(path):
    out = subprocess.run(['pdftotext', '-layout', path, '-'], capture_output=True, text=True, check=True).stdout
    return out.splitlines()


def pct(text):
    t = (text or '').strip()
    if t.lower() in ('nil', 'ex', 'free'):
        return 0.0
    m = NUM.match(t.replace(' ', ''))
    return float(m.group(1).replace(',', '.')) if m else None


# ------------------------------------------------------------------ New Caledonia

NCL_COLS = ['UC', 'DD', 'TCI', 'TSPA', 'TAT', 'TAP', 'TPP', 'TAPP', 'TGC', 'TTE', 'TRM']


# New Caledonia keeps a few subheadings of earlier HS editions in its HS2022 tariff. Each is put on the
# HS2022 subheading(s) that hold the same goods: the UNSD correlation (3603, 8507.40, 8519.50) or the
# subheading text (2206 national splits, 7003.11 coloured sheets, 7009.90 other mirrors, 2835.21
# triammonium phosphate, 2930.50 captafol and methamidophos). Chapter 98 and 99 numbers are not HS
# codes (annex numbering read as codes) and are left out.
NCL_HS22 = {'220610': ('220600',), '220691': ('220600',), '220699': ('220600',),
            '360300': ('360310', '360320', '360330', '360340', '360350', '360360'),
            '700311': ('700312',), '700990': ('700991', '700992'), '283521': ('283529',),
            '293050': ('293080',), '850740': ('850780',), '851950': ('851981',)}


def ncl_hs22(rows):
    out = []
    for r in rows:
        if r['hs6'][:2] in ('98', '99'):
            continue
        for h in NCL_HS22.get(r['hs6'], (r['hs6'],)):
            out.append(dict(r, hs6=h))
    return out


def ncl(path):
    hdr, rows = None, []
    for line in pdf_lines(path):
        if re.search(r'\bUC\b.*\bDD\b.*\bTGC\b', line):
            hdr = {m.group(0): (m.start() + m.end()) / 2 for m in re.finditer(r'[A-Z]{2,4}', line) if m.group(0) in NCL_COLS}
            continue
        m = re.match(r'^(\s+)(\d{4}\.\d{2}\.\d{2})(\s.*)?$', line)
        if not m or hdr is None:
            continue
        start = m.end(2)
        rest = line[start:]
        if re.search(r'[a-zà-ü]{4}', rest):
            continue
        merged = []
        for t in re.finditer(r'\S+', rest):
            tok, a, b = t.group(0), start + t.start(), start + t.end()
            if tok == '%' and merged:
                merged[-1] = (merged[-1][0] + '%', merged[-1][1], b)
            else:
                merged.append((tok, a, b))
        row = {}
        for tok, a, b in merged:
            col = min(hdr, key=lambda k: abs(hdr[k] - (a + b) / 2))
            row[col] = (row.get(col, '') + ' ' + tok).strip()
        code = m.group(2).replace('.', '')
        dd = row.get('DD', '')
        rows.append({'code8': code, 'hs6': code[:6], 'dd_text': dd, 'dd_pct': '' if pct(dd) is None else pct(dd),
                     'tgc_text': row.get('TGC', ''), 'other_taxes': ' '.join(f'{k}={v}' for k, v in row.items()
                                                                            if k not in ('UC', 'DD', 'TGC'))})
    return rows


NCL_START = re.compile(r'^\s{0,14}(\d{4}\s?\d{2}\s?\d{2})\b')
NCL_CODE = re.compile(r'(\d{4}\s?\d{2}\s?\d{2})')
NCL_NUM = re.compile(r'(?<!\S)(ex|EX|\d+(?:,\d+)?)(?!\S)')


def ncl_2022(notice_path, rows_2023):
    """DRDNC notice 22001425: each tariff line changed on 1 January 2023, 'TARIF 2022' on the left and
    'Simplification COMEX 2023' on the right. A 2022 line's DD is the number printed under the left DD
    heading (a line with only a TGC figure has no DD: exempt, as EX lines in the tariff). For every HS6
    that the notice touches, the 2022 HS6 average is taken over its 2022 lines in the notice plus the
    2023 lines of that HS6 that the notice does not name (unchanged). Returns the HS6 whose 2022 average
    differs from the 2023 one."""
    lines = pdf_lines(notice_path)
    old, new_side, cols = {}, set(), None
    for i, line in enumerate(lines):
        if 'TARIF 2022' in line:
            tds = [m.start() for m in re.finditer(r'\bTD\b', line)]
            cols = (tds[1], line.index(' DD ') + 1, [m.start() for m in re.finditer(r'\bTGC\b', line)][0])
            continue
        if cols is None:
            continue
        right, dd, tgc = cols
        for t in NCL_CODE.finditer(line[right - 8:]):
            new_side.add(t.group(1).replace(' ', ''))
        m = NCL_START.match(line)
        if not m:
            continue
        val = None
        for k in range(3):
            if i + k >= len(lines) or (k and NCL_START.match(lines[i + k])):
                break
            toks = list(NCL_NUM.finditer(lines[i + k][:right - 3]))
            hit = [t for t in toks if abs(t.start() - dd) <= 4 and t.start() < tgc - 2]
            if hit:
                val = hit[0].group(1)
                break
            if any(abs(t.start() - tgc) <= 6 for t in toks):
                val = 'EX'
                break
        old[m.group(1).replace(' ', '')] = val
    d23 = {r['code8']: float(r['dd_pct']) for r in rows_2023}
    out = []
    for h6 in sorted({c[:6] for c in old}):
        vals, detail = [], []
        for c in sorted(c for c in old if c[:6] == h6 and old[c] is not None):
            vals.append(0.0 if old[c].upper() == 'EX' else float(old[c].replace(',', '.')))
            detail.append(f'{c}={old[c]}')
        for c in sorted(d23):
            if c[:6] == h6 and c not in new_side and c not in old:
                vals.append(d23[c])
                detail.append(f'{c}={d23[c]:g} (2023 tariff, line not changed)')
        now = [v for c, v in d23.items() if c[:6] == h6]
        if vals and now and abs(sum(vals) / len(vals) - sum(now) / len(now)) > 1e-9:
            out.append({'hs6': h6, 'dd_2022_pct': round(sum(vals) / len(vals), 6),
                        'dd_2023_pct': round(sum(now) / len(now), 6), 'lines_2022': len(vals), 'lines': '; '.join(detail)})
    return out


# ------------------------------------------------------------------ Malaysia

def ahtn_full(path):
    """ACFTA layout: 'dddd.dd.dd dd  description  unit  rate' with one rate column (2019 and subsequent)."""
    rows = []
    for line in pdf_lines(path):
        m = re.match(r'^\s*(\d{4})\.(\d{2})\.(\d{2})\s(\d{2})\s+(.*)$', line.rstrip())
        if not m:
            continue
        parts = re.split(r'\s{2,}', m.group(5).strip())
        text = parts[-1] if len(parts) >= 3 else ''
        rows.append((''.join(m.groups()[:4]), text))
    return rows


RATE_TOK = re.compile(r'^(\d+(?:[.,]\d+)?%?|Excl\.?|EXCL|X|E|-|N\.[O0]\.)$')


def year_columns(path, ncols, pick):
    """Layouts with a 6-digit heading line ('dddd.dd', 'dddd.  dd', 'dddd .dd', 'dddd   .dd') and national
    suffix lines; a line is a rate line when it ends with ncols rate tokens. pick: column index (-1 last)."""
    rows, hs6 = [], None
    for line in pdf_lines(path):
        s = line.rstrip()
        m = re.match(r'^\s*(\d{4})\s*\.\s*(\d{2})(?:\s*\.\s*(\d{2}))?\b(.*)$', s)
        suffix = ''
        if m:
            hs6 = m.group(1) + m.group(2)
            rest = m.group(4)
            sm = re.match(r'^\s*(\d{2,4})?\s', (m.group(3) or '') + rest) if m.group(3) else re.match(r'^\s+(\d{3,4})\s', rest)
            suffix = (m.group(3) or '') + (sm.group(1) if sm and sm.group(1) and not m.group(3) else '')
            body = rest
        else:
            sm = re.match(r'^\s+(\d{3,4})\s+(.*)$', s)
            if not sm or hs6 is None:
                continue
            suffix, body = sm.group(1), sm.group(2)
        toks = body.split()
        tail = []
        for t in reversed(toks):
            if RATE_TOK.match(t) and len(tail) < ncols:
                tail.append(t)
            else:
                break
        if len(tail) < ncols:
            continue
        tail.reverse()
        rows.append((hs6 + suffix, tail[pick]))
    return rows


AHTN_CODE = re.compile(r'^\s*(\d{4})\.(\d{2})\.(\d{2})\s(\d{2})\b(.*)$')
ORDER_TOK = re.compile(r'^(\d+(?:[.,]\d+)?%?|N\.O\.?|Excl\.?|EXCL|X|TRQ|U)$')
RATE_COL = 70          # a one-column order prints its rate right of this; wrapped text ends before it


def _order_tail(text, ncols, continuation=False):
    tail = []
    for t in reversed(text.split()):
        if ORDER_TOK.match(t) and len(tail) < ncols:
            tail.append(t)
        else:
            break
    if len(tail) != ncols:
        return None
    if continuation and ncols == 1 and text.rstrip().rfind(tail[0]) < RATE_COL:
        return None
    return tail[::-1]


def _page_furniture(lines, j):
    """The page number, the 'P.U. (A) n' running head and the repeated column headings, which can sit
    between a code line and its wrapped rate."""
    if re.search(r'P\.U\.|Heading|Quantity|\(1\)|subsequent|years', lines[j]):
        return True
    nxt = [x for x in lines[j + 1:j + 4] if x.strip()]
    return bool(nxt) and 'P.U.' in nxt[0] and re.fullmatch(r'\s*\d+\s*', lines[j]) is not None


def ahtn_order(path, ncols, pick):
    """Gazetted Customs Duties orders: 'dddd.dd.dd dd  description  unit  rate columns'. The rate is
    on the code line or, when the description wraps or the page breaks, on the first later line
    before the next code that ends with ncols rate tokens. pick: column index."""
    lines = pdf_lines(path)
    idx = [i for i, x in enumerate(lines) if AHTN_CODE.match(x)]
    rows = []
    for k, i in enumerate(idx):
        m = AHTN_CODE.match(lines[i])
        got = _order_tail(m.group(5), ncols)
        end = min(idx[k + 1] if k + 1 < len(idx) else len(lines), i + 30)
        j = i + 1
        while got is None and j < end:
            if not _page_furniture(lines, j):
                got = _order_tail(lines[j], ncols, continuation=True)
            j += 1
        if got is not None:
            rows.append((''.join(m.groups()[:4]), got[pick]))
    return rows


AJCEP_LINE = re.compile(r'^\s*(Chapter\s+\d{1,2}|\d{2}\.\d{2}|\d{4}\.\d{2}|\d{4}\.\d{5})\s')
AJCEP_CAT = re.compile(r'\s(A|B\d+\*?|C|R|X)(?:\s+\(([a-d])\))?\s*$')
AJCEP_R_END = {'a': 5.0, 'b': 10.0, 'c': 20.0, 'd': 20.0}      # Part 6 Section 1 note 2, end rates


def ajcep(path, hs02):
    """AJCEP Schedule of Malaysia (HS 2002 based: 8528.21 is listed, 8528.72 is not; Base Rate and Category columns). Entry into force for
    Malaysia 1 February 2009, so 2022 is year 14: A and every B category are free; C stays at the
    Base Rate; R takes the end rate of its note (a) 5, (b) 10, (c) 20, (d) 20 percent; X is excluded.
    A category set on a chapter, a heading (dd.dd) or a subheading (dddd.dd) covers the HS 2002 subheadings under it
    that have no national line of their own. Returns (code, rate text): a 9-digit national line, or a
    6-digit subheading filled from a heading or subheading entry."""
    lines = pdf_lines(path)
    idx = [i for i, x in enumerate(lines) if AJCEP_LINE.match(x)]
    entries = []
    for k, i in enumerate(idx):
        code = AJCEP_LINE.match(lines[i]).group(1).replace('.', '')
        if code.startswith('Chapter'):
            code = code.split()[1].zfill(2)
        end = idx[k + 1] if k + 1 < len(idx) else len(lines)
        for j in range(i, min(end, i + 6)):
            m = AJCEP_CAT.search(lines[j])
            if m:
                cat, note = m.group(1), m.group(2)
                base = lines[j][:m.start()].split()
                base = base[-1] if base and re.fullmatch(r'\d+(?:\.\d+)?%', base[-1]) and \
                    not re.search(r'(AND|OR)\s*$', lines[j][:m.start()]) else ''
                if cat == 'A' or cat.startswith('B'):
                    text = '0'
                elif cat == 'C':
                    text = base or 'C (specific base rate)'
                elif cat == 'R':
                    text = str(AJCEP_R_END[note]) if note in AJCEP_R_END else 'R'
                else:
                    text = 'X'
                entries.append((code, text))
                break
    lines9 = {c: t for c, t in entries if len(c) == 9}
    have6 = {c[:6] for c in lines9}
    rows = sorted(lines9.items())
    sub = {c: t for c, t in entries if len(c) == 6}
    head = {c: t for c, t in entries if len(c) == 4}
    chap = {c: t for c, t in entries if len(c) == 2}
    for h6 in sorted(hs02):
        if h6 in have6:
            continue
        text = sub.get(h6) or head.get(h6[:4]) or chap.get(h6[:2])
        if text is not None:
            rows.append((h6, text))
    return rows


def hs2002_subheadings():
    with open(os.path.join(DATA, 'unsd_hs_correlation', 'hs2017_to_hs2002.csv'), newline='') as fh:
        return {r['hs_earlier'] for r in csv.DictReader(fh)}


def ahkfta(path):
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb.worksheets[0]
    col, rows = None, []
    for r in ws.iter_rows(values_only=True):
        if col is None and 2022 in r:
            col = list(r).index(2022)
            continue
        if col is None or not r[1]:
            continue
        code = re.sub(r'\D', '', str(r[1]))
        if len(code) == 10:
            v = r[col]
            if isinstance(v, (int, float)):         # cells are formatted '0%': 0.12 is 12 percent
                v = round(v * 100.0, 6)
            rows.append((code, '' if v is None else str(v)))
    wb.close()
    return rows


MYS = [
    # agreement, file, partner (WITS code), nomenclature of the 6-digit code, reader, rate column read
    ('ACFTA', 'acfta_malaysia_trs_ahtn2017.pdf', '156', 'H5', lambda p: ahtn_full(p), '2019 and subsequent years'),
    ('AHKFTA', 'ahkfta_malaysia_trs_hs2017.xlsx', '344', 'H5', lambda p: ahkfta(p), '2022'),
    ('MICECA', 'miceca_malaysia_jadual_tarif.pdf', '356', 'H3', lambda p: year_columns(p, 15, -1), '31-12-2019 onward'),
    ('MJEPA', 'mjepa_malaysia_schedule.pdf', '392', 'H2', lambda p: year_columns(p, 11, -1), 'last staging column (2016)'),
    ('MPCEPA', 'mpcepa_malaysia_schedule.pdf', '586', 'H3', lambda p: year_columns(p, 8, -1), 'last staging column (2015)'),
    ('MAFTA', 'mafta_perintah_duti_kastam_2012.pdf', '036', 'H4', lambda p: year_columns(p, 8, -1), '2020 and subsequent'),
    ('MNZFTA', 'mnzfta_malaysia_schedule.pdf', '554', 'H3', lambda p: year_columns(p, 7, -1), '2016 and subsequent'),
    ('MCFTA', 'mcfta_perintah_duti_kastam.pdf', '152', 'H4', lambda p: year_columns(p, 5, -1), '2016 and subsequent'),
    ('MTFTA', 'mtfta_malaysia_schedule_ahtn10.pdf', '792', 'H4', lambda p: year_columns(p, 9, 7), '2022'),
    ('ATIGA', 'pua199_2022_atiga_ahtn2022.pdf', 'N44', 'H6', lambda p: ahtn_order(p, 1, 0), 'P.U.(A) 199/2022 column (5)'),
    ('AKFTA', 'akfta_pua286_2015_3rd_protocol.pdf', '410', 'H4', lambda p: ahtn_order(p, 1, 0), '2016 and subsequent years'),
    ('RCEP', 'pua64_2022_rcep.pdf', 'B39', 'H5', lambda p: ahtn_order(p, 23, 0), '2022'),
    ('CPTPP', 'pua406_2022_cptpp.pdf', '01B', 'H6', lambda p: ahtn_order(p, 12, 0), '2022 (29 Nov - 31 Dec)'),
    ('AJCEP', 'ajcep_malaysia_schedule.pdf', 'AJCEP', 'H2', lambda p: ajcep(p, hs2002_subheadings()), 'category end rate (year 14)'),
]


# ------------------------------------------------------------------ Tunisia (Türkiye FTA, Protocol I)

def tunisia_lists(zip_path, work):
    """Lists I-III of Protocol I (Tunisian 11-digit lines, HS2002 basis), read from the RTA 35 annex .doc files
    with LibreOffice."""
    import zipfile
    os.makedirs(work, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if re.search(r'Protocol I LIST (I|II|III)\.doc$', n, re.I)]
        zf.extractall(work, names)
    subprocess.run(['soffice', '--headless', '--convert-to', 'txt:Text', '--outdir', work] +
                   [os.path.join(work, n) for n in names], capture_output=True, check=True)
    rows = []
    for n in sorted(names):
        lst = re.search(r'LIST (I{1,3})\.doc$', n, re.I).group(1).upper()
        with open(os.path.join(work, n[:-4] + '.txt'), encoding='utf-8', errors='replace') as fh:
            for line in fh:
                code = line.strip()
                if re.fullmatch(r'\d{11}', code):
                    rows.append({'list': lst, 'national_code': code, 'hs6_2002': code[:6], 'source_file': n})
    return rows


def main():
    out_ncl = os.path.join(DATA, 'ncl_customs_tariff', 'extracted')
    os.makedirs(out_ncl, exist_ok=True)
    rows = ncl_hs22(ncl(os.path.join(DATA, 'ncl_customs_tariff', 'tarif_des_douanes_mj01012023.pdf')))
    with open(os.path.join(out_ncl, 'ncl_dd_lines_2023.csv'), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print('NCL lines', len(rows))
    changed = ncl_2022(os.path.join(DATA, 'ncl_customs_tariff', 'drdnc_ao_22001425_tarif_2022_vs_2023.pdf'), rows)
    with open(os.path.join(out_ncl, 'ncl_dd_2022_changed_hs6.csv'), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=['hs6', 'dd_2022_pct', 'dd_2023_pct', 'lines_2022', 'lines'])
        w.writeheader()
        w.writerows(changed)
    print('NCL HS6 with a different 2022 DD', len(changed))
    import tempfile
    out_tun = os.path.join(DATA, 'tunisia_turkey_fta', 'extracted')
    os.makedirs(out_tun, exist_ok=True)
    rows = tunisia_lists(os.path.join(DATA, 'tunisia_turkey_fta', 'rta35_turkey_tunisia_annexes_en.zip'), tempfile.mkdtemp())
    with open(os.path.join(out_tun, 'protocol1_lists.csv'), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print('TUN list lines', len(rows))
    out_mys = os.path.join(DATA, 'malaysia_fta_schedules', 'extracted')
    os.makedirs(out_mys, exist_ok=True)
    with open(os.path.join(out_mys, 'mys_pref_lines_2022.csv'), 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['agreement', 'partner', 'nomen', 'national_code', 'hs6', 'rate_text', 'rate_pct', 'column', 'source_file'])
        for agr, files, partner, nomen, reader, column in MYS:
            n = 0
            seen = set()
            for f in files.split(';'):
                for code, text in reader(os.path.join(DATA, 'malaysia_fta_schedules', f)):
                    if code in seen:
                        continue
                    seen.add(code)
                    p = pct(text)
                    w.writerow([agr, partner, nomen, code, code[:6], text, '' if p is None else p, column, f])
                    n += 1
            print(agr, n)


if __name__ == '__main__':
    sys.exit(main())
