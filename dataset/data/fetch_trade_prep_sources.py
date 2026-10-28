#!/usr/bin/env python3
"""Refetch the small S07/S08 public inputs that MANIFEST.csv pins.

Written 2026-10-23 to restore files that were in MANIFEST but in no git
commit. Each recipe below reproduces the pinned sha256 byte for byte (checked
2026-10-23). The script checks every file against MANIFEST.csv and exits 1 on
a mismatch.

    python3 dataset/data/fetch_trade_prep_sources.py            # all
    python3 dataset/data/fetch_trade_prep_sources.py cbs sc123  # some

Not covered here (long, batched runs):
  * hk_trade_idds/*.json: dataset/build/prep_trade/fetch_sources.py fetch_hk()
    (needs hk_trade_idds/API_eng.txt, made here, copied to
    $TRADE_PREP_CACHE/raw/probes/API_eng.txt).
  * oecd_itic/hs4_2022/: dataset/build/s08_fetch_itic.py, with the importer
    list from REF_AREA of the ITIC total query (see `itic_importers` below).
  * oecd_wto_batis/ebops2022.csv: see oecd_wto_batis/README.md (the OECD API
    returns rows in an unstable order).
"""
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

DATA = os.path.dirname(os.path.abspath(__file__))
UA = {'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}


def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or UA)
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def write(rel, data):
    path = os.path.join(DATA, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as fh:
        fh.write(data)
    return rel


def cbs():
    # ODataApi (not ODataFeed) with $format=json. Landen and SITC are the raw
    # bytes. TypedDataSet is re-serialised as {"value": [...]} with
    # json.dumps defaults (the odata.metadata key dropped).
    base = 'https://opendata.cbs.nl/ODataApi/odata/85429NED/{}?$format=json'
    out = [write('cbs_85429ned/landen.json', get(base.format('Landen'))),
           write('cbs_85429ned/sitc.json', get(base.format('SITC')))]
    raw = get(base.format('TypedDataSet') +
              "&$filter=Perioden%20eq%20'2022JJ00'")
    obj = json.loads(raw)
    out.append(write('cbs_85429ned/typed_2022.json',
                     json.dumps({'value': obj['value']}).encode()))
    return out


def singstat():
    # tablebuilder tabledata, 12 months of 2022, re-serialised with json.dump
    # defaults. M451001 keeps only series 3.x/4.x/5.x (domestic exports,
    # re-exports, imports by section), as fetch_sources.fetch_sg() does.
    # The response carries the server's "dateGenerated" stamp. The pinned
    # files were fetched on 21/10/2026; with that stamp restored the
    # 2026-10-23 responses are byte-identical to the pins (the data did not
    # change). Set SINGSTAT_DATE_GENERATED='' to keep today's stamp.
    stamp = os.environ.get('SINGSTAT_DATE_GENERATED', '21/10/2026')
    months = ','.join(f'2022 {m}' for m in
                      'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split())
    q = '?timeFilter=' + urllib.parse.quote(months) + '&limit=5000'
    base = 'https://tablebuilder.singstat.gov.sg/api/table/'
    meta = json.loads(get(base + 'metadata/M451001'))
    series = ','.join(r['seriesNo'] for r in meta['Data']['records']['row']
                      if r['seriesNo'].split('.')[0] in {'3', '4', '5'})
    extra = {'M451001': '&seriesNoORrowNo=' + urllib.parse.quote(series)}
    out = []
    for t in ('M451521', 'M451501', 'M451001'):
        d = json.loads(get(base + f'tabledata/{t}' + q + extra.get(t, '')))
        if stamp:
            d['Data']['dateGenerated'] = stamp
        out.append(write(f'singstat/{t}.json', json.dumps(d).encode()))
    return out


def sc123():
    # The MANIFEST url key (.W.X.SC1+SC2+SC3..) returns 404; the dimension
    # order is PRODUCT_TYPE then SERVICE. Reduced to 4 columns, sorted by
    # (REF_AREA, SERVICE).
    url = ('https://sdmx.oecd.org/public/rest/data/OECD.SDD.TPS,'
           'DSD_BATIS@DF_BATIS,1.0/.W.X.S.SC1+SC2+SC3.A.USD_EXC.B'
           '?startPeriod=2022&endPeriod=2022&dimensionAtObservation='
           'AllDimensions&format=csvfile')
    body = get(url, {'User-Agent': 'Mozilla/5.0',
                     'Accept': 'application/vnd.sdmx.data+csv;charset=utf-8'})
    rows = list(csv.DictReader(io.StringIO(body.decode('utf-8'))))
    rows.sort(key=lambda r: (r['REF_AREA'], r['SERVICE']))
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator='\n')
    w.writerow(['ref_area', 'service', 'obs_value', 'obs_status'])
    for r in rows:
        w.writerow([r['REF_AREA'], r['SERVICE'], r['OBS_VALUE'],
                    r['OBS_STATUS']])
    return [write('oecd_wto_batis/sc123_exports_world_2022.csv',
                  buf.getvalue().encode())]


def restcountries():
    # The pinned copy is mledoze/countries at c2ac0049 (2026-09-29), the
    # master head on 2026-10-21. Master moved on 2026-10-22.
    url = ('https://raw.githubusercontent.com/mledoze/countries/'
           'c2ac0049c14edcf2436c7aa1b2493222a020b462/countries.json')
    return [write('restcountries/countries.json', get(url))]


def unsd():
    url = ('https://unstats.un.org/unsd/trade/conversions/'
           'HS2017toSITC4ConversionAndCorrelationTables.xlsx')
    return [write('unsd_hs_correlation/'
                  'HS2017toSITC4ConversionAndCorrelationTables.xlsx',
                  get(url, {'User-Agent': 'Mozilla/5.0', 'Accept': '*/*'}))]


def hk_api():
    # Text of the Trade-IDDS API annex: pdftotext -layout (poppler).
    pdf = get('https://tradeidds.censtatd.gov.hk/MetadataLink/ApiSpec/'
              'API_eng.pdf', {'User-Agent': 'Mozilla/5.0', 'Accept': '*/*'})
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, 'API_eng.pdf')
        open(p, 'wb').write(pdf)
        subprocess.check_call(['pdftotext', '-layout', p,
                               os.path.join(tmp, 'API_eng.txt')])
        txt = open(os.path.join(tmp, 'API_eng.txt'), 'rb').read()
    return [write('hk_trade_idds/API_eng.txt', txt)]


def itic_importers(path='/tmp/itic_importers.txt'):
    # Importer list for s08_fetch_itic.py: REF_AREA of the ITIC total query
    # (205 economies on 2026-10-21 and 2026-10-23).
    url = ('https://sdmx.oecd.org/sti-public/rest/data/OECD.SDD.TPS,'
           'DSD_ITIC@DF_ITIC,1.1/..C_F.C._T.A.PT_IM_CIF'
           '?startPeriod=2022&endPeriod=2022&format=csv')
    body = get(url, {'User-Agent': 'gtap-s08-itic'}).decode('utf-8')
    v = sorted({r['REF_AREA'] for r in csv.DictReader(io.StringIO(body))})
    open(path, 'w').write('\n'.join(v) + '\n')
    print(f'wrote {len(v)} importers to {path}')
    return []


RECIPES = {'cbs': cbs, 'singstat': singstat, 'sc123': sc123,
           'restcountries': restcountries, 'unsd': unsd, 'hk_api': hk_api,
           'itic_importers': itic_importers}


def manifest():
    with open(os.path.join(DATA, 'MANIFEST.csv'), newline='') as fh:
        return {r['path']: r for r in csv.DictReader(fh)}


def main(names):
    pins = manifest()
    bad = 0
    for n in names or [k for k in RECIPES if k != 'itic_importers']:
        for rel in RECIPES[n]():
            h = hashlib.sha256(open(os.path.join(DATA, rel), 'rb').read())
            want = pins.get(rel, {}).get('sha256', '')
            ok = h.hexdigest() == want
            bad += not ok
            print(f"{'OK  ' if ok else 'DIFF'} {rel} {h.hexdigest()[:12]}"
                  f" (pinned {want[:12]})")
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main(sys.argv[1:])
