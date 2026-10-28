"""Fetch OECD ITIC 2022 HS4 PT_IM_CIF and reduce it.

One SDMX call per importer. The key is public (no token). The reduced file keeps
importer, counterpart, commodity (HS4 or _T), the published percent of CIF, and
OBS_STATUS. It is not committed. The stage reads it and checks it against MANIFEST.
"""
import csv
import gzip
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'data', 'oecd_itic', 'hs4_2022', 'itic_hs4_pt_im_cif_2022.csv.gz')
PARTS = os.environ.get('ITIC_PARTS', '/tmp/itic_hs4_parts')
LIST = os.environ.get('ITIC_IMPORTERS', '/tmp/itic_importers.txt')
WORKERS = int(os.environ.get('ITIC_WORKERS', '8'))


def url_for(iso):
    return ('https://sdmx.oecd.org/sti-public/rest/data/OECD.SDD.TPS,DSD_ITIC@DF_ITIC,1.1/'
            f'{iso}..C_F.C..A.PT_IM_CIF?startPeriod=2022&endPeriod=2022&format=csv')


def reduce(iso, text):
    rows = []
    reader = csv.DictReader(text.splitlines())
    for row in reader:
        if row.get('TIME_PERIOD') != '2022':
            continue
        if row.get('UNIT_MEASURE') != 'PT_IM_CIF':
            continue
        comm = row['COMM_HS2017']
        if comm.startswith('HS17_'):
            comm = comm[5:]
        if comm != '_T' and (len(comm) != 4 or not comm.isdigit()):
            continue
        val = row.get('OBS_VALUE', '')
        if val == '':
            continue
        rows.append((row['REF_AREA'], row['COUNTERPART_AREA'], comm, val, row.get('OBS_STATUS', '')))
    return rows


def fetch(iso):
    dest = os.path.join(PARTS, iso + '.csv')
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return iso, 'cached', 0
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url_for(iso), headers={'User-Agent': 'gtap-s08-itic'})
            with urllib.request.urlopen(req, timeout=300) as resp:
                text = resp.read().decode('utf-8')
            rows = reduce(iso, text)
            with open(dest, 'w', newline='') as fh:
                w = csv.writer(fh, lineterminator='\n')
                w.writerows(rows)
            return iso, 'ok', len(rows)
        except Exception as exc:
            last = type(exc).__name__
            time.sleep(2 * (attempt + 1))
    return iso, 'FAIL ' + str(last), 0


def main():
    os.makedirs(PARTS, exist_ok=True)
    imps = [ln.strip() for ln in open(LIST) if ln.strip()]
    print(f'importers {len(imps)} workers {WORKERS}', flush=True)
    bad = []
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = [pool.submit(fetch, iso) for iso in imps]
        for fut in as_completed(futs):
            iso, status, n = fut.result()
            done += 1
            if status.startswith('FAIL'):
                bad.append((iso, status))
                print(f'{done}/{len(imps)} {iso} {status}', flush=True)
            elif done % 20 == 0 or status != 'cached':
                print(f'{done}/{len(imps)} {iso} {status} {n}', flush=True)
    if bad:
        print('FAILED', bad, flush=True)
        sys.exit(1)
    # Merge, drop exact duplicate keys, refuse conflicting values.
    seen = {}
    conflict = 0
    for iso in imps:
        with open(os.path.join(PARTS, iso + '.csv'), newline='') as fh:
            for imp, cp, comm, val, status in csv.reader(fh):
                key = (imp, cp, comm)
                prev = seen.get(key)
                if prev is None:
                    seen[key] = (val, status)
                elif prev[0] != val:
                    conflict += 1
    if conflict:
        print(f'conflicting duplicate ITIC keys {conflict}', flush=True)
        sys.exit(1)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + '.tmp'
    with open(tmp, 'wb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0, compresslevel=9) as gz:
            gz.write(b'importer,counterpart,comm,obs_value,obs_status\n')
            for key in sorted(seen):
                val, status = seen[key]
                gz.write(f'{key[0]},{key[1]},{key[2]},{val},{status}\n'.encode())
    os.replace(tmp, OUT)
    print(f'wrote {OUT} keys {len(seen)}', flush=True)


if __name__ == '__main__':
    main()
