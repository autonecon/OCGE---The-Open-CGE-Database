#!/usr/bin/env python3
"""Fetch WDI services exports/imports 2022 (keyless World Bank API v2) in the long layout S09 reads.

Layout: iso3,series,year,value. Rows in API order, BX.GSR.NFSV.CD then BM.GSR.NFSV.CD.
Aggregates without an ISO3 code carry the API country id. Missing values are empty.
Values are Python repr of the API number.

Usage: python3 fetch_wdi_services_2022.py [out_path]
The script prints the SHA-256 and compares it with the MANIFEST row (a2b80fc3...).
The MANIFEST file was written on the S09 VM on 2026-10-21; this script reproduces its
content and size (20,255 bytes) but not, so far, its exact row order. If the SHA differs,
the file is written beside the MANIFEST path as wdi_services_2022.refetch.csv and is NOT
a substitute for IN1. S09's QA (report-fix-qa.md) showed the refetch gives identical S09 outputs.
"""
import hashlib, json, os, sys, urllib.request

MANIFEST_SHA = 'a2b80fc3bb134ea0322a2a3604062ff9d54c7231d147a5216fa6eff38ede3247'
SERIES = ['BX.GSR.NFSV.CD', 'BM.GSR.NFSV.CD']
URL = 'https://api.worldbank.org/v2/country/all/indicator/{s}?date=2022&format=json&per_page=30000'

here = os.path.dirname(os.path.abspath(__file__))
target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, 'wdi_services_2022.csv')
lines = ['iso3,series,year,value']
for s in SERIES:
    with urllib.request.urlopen(URL.format(s=s), timeout=120) as r:
        meta, rows = json.load(r)
    print(s, 'lastupdated', meta.get('lastupdated'), 'rows', len(rows))
    for row in rows:
        iso = row['countryiso3code'] or row['country']['id']
        val = '' if row['value'] is None else repr(row['value'])
        lines.append(f"{iso},{s},{row['date']},{val}")
data = ('\n'.join(lines) + '\n').encode()
sha = hashlib.sha256(data).hexdigest()
if sha != MANIFEST_SHA and os.path.basename(target) == 'wdi_services_2022.csv':
    target = os.path.join(os.path.dirname(target), 'wdi_services_2022.refetch.csv')
open(target, 'wb').write(data)
print(target, len(data), 'bytes', sha, 'MANIFEST match' if sha == MANIFEST_SHA else 'differs from MANIFEST a2b80fc3 (see docstring)')
