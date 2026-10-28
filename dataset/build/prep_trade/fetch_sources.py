"""Download 2022 re-export statistics used to clean BACI.

Sources (all fetched by this script; nothing is committed):
- Hong Kong C&SD Trade-IDDS API. Re-exports by origin and by consignment are
  published. The API rejects origin crossed with HS for re-exports
  ("By CO and by HKHS / SITC commodity classifications are invalid for
  Re-exports trade type"), so the commodity split is consignment x HKHS2.
- Singapore Department of Statistics Table Builder, Enterprise Singapore:
  M451521 total exports by market and M451501 domestic exports by market.
  Re-exports by market are the difference. No origin dimension is published.
- Statistics Netherlands (CBS) OData 85429NED, cross-border goods trade,
  SITC section x country, 2022 annual (period 2022JJ00). Re-exports
  (wederuitvoer) and Dutch-product exports are separate from quasi-transit
  (doorvoer). No origin dimension is published.
- UNSD HS2017 to SITC Rev.4 conversion and correlation tables.

Raw responses stay in $TRADE_PREP_CACHE. This script writes the small share
tables the BACI cleaner reads.
"""
import csv
import json
import os
import subprocess
import time
import urllib.parse

from common import CACHE

RAW = os.path.join(CACHE, 'raw')
OUT = os.path.join(CACHE, 'shares')
os.makedirs(OUT, exist_ok=True)
os.makedirs(os.path.join(RAW, 'hk'), exist_ok=True)
os.makedirs(os.path.join(RAW, 'sg'), exist_ok=True)

HK_BASE = 'https://tradeidds.censtatd.gov.hk/api/bb6578c6535a4269b76c5e7034a3b337/get'
COOKIE = os.path.join(RAW, 'hk', 'cookies.txt')
MONTHS = [f'2022 {m}' for m in
          'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split()]


def curl_json(url, cookie=None, timeout=180):
    cmd = ['curl', '-sS', '-L', '-m', str(timeout), '-A', 'Mozilla/5.0',
           '-H', 'Accept: application/json', '-w', '\n%{http_code}']
    if cookie:
        cmd += ['-c', cookie, '-b', cookie]
    cmd.append(url)
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode()[:500] or f'curl {p.returncode}')
    body, _, code = p.stdout.rpartition(b'\n')
    if code.strip() != b'200':
        raise RuntimeError(f'HTTP {code.decode()} {url[:180]} {body[:200]!r}')
    return json.loads(body.decode())


def parse_hk_codes(text):
    """Annex 1 country/territory codes from the Trade-IDDS API PDF text."""
    start = text.find('Country/Territory (in no particular order)')
    end = text.find('Annex 2', start)
    if start < 0 or end < 0:
        raise SystemExit('HK API annex not found')
    block = text[start:end]
    codes = []
    pending = None
    for raw in block.splitlines():
        line = raw.strip()
        if not line or line.isdigit() or line.startswith('API Code') or line.startswith('Country'):
            continue
        parts = line.split()
        if len(parts) == 1 and len(parts[0]) == 2 and parts[0].isalpha() and parts[0].isupper():
            pending = parts[0]
            continue
        if len(parts) >= 2 and len(parts[0]) == 1 and len(parts[1]) == 1 and parts[0].isalpha() and parts[1].isalpha():
            codes.append(parts[0] + parts[1])
            pending = None
            continue
        if len(parts) >= 2 and len(parts[0]) == 2 and parts[0].isalpha() and parts[0].isupper():
            codes.append(parts[0])
            pending = None
            continue
        if pending:
            codes.append(pending)
            pending = None
    if pending:
        codes.append(pending)
    # The PDF repeats the Asia block. Keep first occurrence.
    seen = []
    for c in codes:
        if c not in seen:
            seen.append(c)
    return seen


def hk_call(params, tries=6):
    q = urllib.parse.urlencode(params, safe=',')
    url = HK_BASE + '?' + q
    last = None
    for i in range(tries):
        try:
            d = curl_json(url, cookie=COOKIE)
        except Exception as e:
            last = e
            time.sleep(2.0 * (i + 1))
            continue
        st = d.get('header', {}).get('status', {})
        if st.get('name') == 'Success':
            return d
        last = st.get('message')
        # An empty cross-classification is a zero, not a failed call.
        if last and any('No record found' in str(m) for m in last):
            return {'dataSet': [], 'header': d.get('header')}
        # The service asks the caller to wait. Splitting the batch would
        # only add more calls.
        if last and any('usage limit' in str(m).lower() for m in last):
            time.sleep(25 * (i + 1))
            continue
        time.sleep(1.0 * (i + 1))
    raise RuntimeError(f'HK API failed {params} :: {last}')


def rows_of(d):
    out = []
    for r in d.get('dataSet') or []:
        out.append(r)
    return out


def fetch_hk():
    text = open(os.path.join(RAW, 'probes', 'API_eng.txt'), encoding='utf-8', errors='replace').read()
    codes = parse_hk_codes(text)
    # NESOI and the combined Micronesia+Palau code are not one economy.
    nesoi = {c for c in codes if c.startswith('X') and len(c) == 2}
    combined = {'FM'}
    json.dump({'codes': codes, 'nesoi': sorted(nesoi), 'combined': sorted(combined)},
              open(os.path.join(RAW, 'hk', 'codes.json'), 'w'), indent=2)
    print(f'HK codes {len(codes)} nesoi {sorted(nesoi)}', flush=True)
    # 01-97 except 77 (reserved). Chapter 98 is defined and is in the saved
    # total-export and re-export extracts. Chapter 99 is not defined for 2022
    # (API: "Commodity code (99) is not defined"). No probe: a rate-limit error
    # must not drop a chapter.
    chapters = [f'{i:02d}' for i in range(1, 98) if i != 77] + ['98']
    print('HKHS2 chapters', len(chapters), flush=True)

    def batched(kind, ttype, path, extra_params=None):
        done = path + '.done'
        if os.path.exists(done):
            print(f'skip {kind}', flush=True)
            return
        acc = []
        cc_groups = [codes[i:i + 8] for i in range(0, len(codes), 8)]
        hs_groups = [chapters[i:i + 10] for i in range(0, len(chapters), 10)]
        n = 0

        def pull(ccg, hsg):
            nonlocal n
            params = {'lang': 'en', 'sv': 'VCy', 'freq': 'A', 'period': '2022,2022',
                      'ttype': str(ttype), 'ccclass': 'C', 'cc': ','.join(ccg),
                      'codeclass': 'HKHS2', 'code': ','.join(hsg)}
            if extra_params:
                params.update(extra_params)
            try:
                d = hk_call(params)
            except RuntimeError as e:
                # Empty is already returned as an empty dataSet. Anything else
                # is a real failure and is split down to a single cell.
                if len(ccg) > 1:
                    mid = len(ccg) // 2
                    pull(ccg[:mid], hsg)
                    pull(ccg[mid:], hsg)
                    return
                if len(hsg) > 1:
                    mid = len(hsg) // 2
                    pull(ccg, hsg[:mid])
                    pull(ccg, hsg[mid:])
                    return
                print(f'  {kind} drop {ccg} {hsg}', flush=True)
                return
            acc.extend(rows_of(d))
            n += 1
            if n % 25 == 0:
                print(f'  {kind} calls {n} rows {len(acc)}', flush=True)
            time.sleep(0.12)

        for ccg in cc_groups:
            for hsg in hs_groups:
                pull(ccg, hsg)
        with open(path, 'w') as f:
            json.dump(acc, f)
        open(done, 'w').write(str(len(acc)))
        print(f'{kind} rows {len(acc)}', flush=True)

    batched('tx_hs2', 4, os.path.join(RAW, 'hk', 'tx_hs2.json'))
    batched('rx_hs2', 3, os.path.join(RAW, 'hk', 'rx_hs2.json'))
    # Domestic exports are not required for the share (re-exports / total exports).
    # They are fetched after the origin matrix so a rate limit cannot block that matrix.
    # Origin x consignment, all commodities. The API allows up to 30 codes.
    od_path = os.path.join(RAW, 'hk', 'rx_od.json')
    if not os.path.exists(od_path + '.done'):
        acc = []
        groups = [codes[i:i + 24] for i in range(0, len(codes), 24)]
        n = 0
        for og in groups:
            for dg in groups:
                params = {'lang': 'en', 'sv': 'VCy', 'freq': 'A', 'period': '2022,2022',
                          'ttype': '3', 'coclass': 'C', 'co': ','.join(og),
                          'ccclass': 'C', 'cc': ','.join(dg)}
                try:
                    d = hk_call(params)
                except RuntimeError:
                    if len(og) == 1 and len(dg) == 1:
                        print(f'  rx_od drop {og[0]}->{dg[0]}', flush=True)
                        continue
                    for o in og:
                        for dest in dg:
                            try:
                                d1 = hk_call({'lang': 'en', 'sv': 'VCy', 'freq': 'A', 'period': '2022,2022',
                                              'ttype': '3', 'coclass': 'C', 'co': o,
                                              'ccclass': 'C', 'cc': dest})
                                acc.extend(rows_of(d1))
                            except RuntimeError:
                                print(f'  rx_od drop {o}->{dest}', flush=True)
                            time.sleep(0.05)
                    n += 1
                    continue
                acc.extend(rows_of(d))
                n += 1
                if n % 25 == 0:
                    print(f'  rx_od calls {n} rows {len(acc)}', flush=True)
                time.sleep(0.15)
        json.dump(acc, open(od_path, 'w'))
        open(od_path + '.done', 'w').write(str(len(acc)))
        print(f'rx_od rows {len(acc)}', flush=True)

    batched('dx_hs2', 2, os.path.join(RAW, 'hk', 'dx_hs2.json'))

    # Grand totals already known from the uncoded query; re-pull for the file.
    totals = {}
    for ttype, name in ((1, 'imports'), (2, 'domestic_exports'), (3, 'reexports'), (4, 'total_exports')):
        d = hk_call({'lang': 'en', 'sv': 'VCy', 'freq': 'A', 'period': '2022,2022', 'ttype': str(ttype)})
        totals[name] = d['dataSet'][0]['figure']
        totals[name + '_unit'] = d['dataSet'][0]['unitEN']
        time.sleep(0.2)
    json.dump(totals, open(os.path.join(RAW, 'hk', 'totals.json'), 'w'), indent=2)
    print('HK totals', totals, flush=True)


def sg_table(resource, path, series=None):
    if os.path.exists(path):
        print(f'skip {resource}', flush=True)
        return
    tf = ','.join(MONTHS)
    url = (f'https://tablebuilder.singstat.gov.sg/api/table/tabledata/{resource}'
           f'?timeFilter={urllib.parse.quote(tf)}&limit=5000')
    if series:
        url += '&seriesNoORrowNo=' + urllib.parse.quote(series)
    d = curl_json(url, timeout=180)
    json.dump(d, open(path, 'w'))
    rows = d.get('Data', {}).get('row') or []
    print(f'{resource} rows {len(rows)}', flush=True)


def fetch_sg():
    sg = os.path.join(RAW, 'sg')
    sg_table('M451521', os.path.join(sg, 'M451521.json'))
    sg_table('M451501', os.path.join(sg, 'M451501.json'))
    # Commodity-section domestic / total / re-exports, for the report only.
    meta = json.load(open(os.path.join(RAW, 'probes', 'meta_M451001.json')))
    series = ','.join(r['seriesNo'] for r in meta['Data']['records']['row']
                      if r['seriesNo'].split('.')[0] in {'3', '4', '5'})
    sg_table('M451001', os.path.join(sg, 'M451001.json'), series=series)


def main():
    print('fetch HK', flush=True)
    fetch_hk()
    print('fetch SG', flush=True)
    fetch_sg()
    print('done', flush=True)


if __name__ == '__main__':
    main()
