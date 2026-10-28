#!/usr/bin/env python3
"""WTO AG-IMS export-subsidy notifications (keyless public search + 'Export to Excel').

Table ES:1 (members with reduction commitments) and Supporting Table ES:2 (developing members,
Article 9.4), all members, all products, implementation years 2015-2024.
Writes the two .xls exports and export_subsidies_latest_le2022.csv (each member's latest
notification year <= 2022, both tables, one row per notified product line).
"""
import os, re, subprocess, sys, urllib.parse
import pandas as pd

BASE = 'https://agims.wto.org/en/ExportSubsidies/'
here = os.path.dirname(os.path.abspath(__file__))
ck = os.path.join(here, '.agims_cookies')

def curl(args):
    subprocess.run(['curl', '-sfS', '-m', '180', '-b', ck, '-c', ck] + args, check=True)

page = os.path.join(here, '.agims_search.html')
curl(['-o', page, BASE + 'SearchResults'])
h = open(page, encoding='utf-8', errors='ignore').read()
prods = re.search(r"\$\('#hdnproducts'\)\.val\('([^']*)'", h).group(1)
members = re.findall(r'<option value="(C\d+)">', re.search(r'<select id="e9".*?</select>', h, re.S).group(0))
jobs = [('ES1MemberRC', 'ExportToExcelSearchMembersWithRCReport', 'agims_es1_members_rc_2015_2024.xls'),
        ('ES2DevlopingCRA', 'ExportToExcelSearchDevlopingCRAReport', 'agims_es2_developing_art94_2015_2024.xls')]
for rt, export, name in jobs:
    form = [('ExportSubsidiesReportType', rt), ('ProductCode', prods), ('ProductSelectedList', prods),
            ('IsAllMembersSelected', 'true')] + [('MembersSelectedList', m) for m in members] + \
           [('ImplementationYearsSelectedList', str(y)) for y in range(2015, 2025)] + [('IsAllImpYearSelected', 'false')]
    curl(['-X', 'POST', '--data', urllib.parse.urlencode(form), '-o', os.devnull, BASE + 'ViewResults'])
    curl(['-X', 'POST', '-d', '', '-o', os.path.join(here, name), BASE + export + '?Length=15'])
for f in ('.agims_cookies', '.agims_search.html'):
    os.remove(os.path.join(here, f))

d = pd.read_excel(os.path.join(here, jobs[0][2])); e = pd.read_excel(os.path.join(here, jobs[1][2]))
rows = [dict(table='ES1', member=r['Member Name'], year=r['Implementation Year'], doc=r['Doc Symbols'],
             product=r['Product Description(CTS)'], category=r['AgProdCat_Broad'], unit=r['Commitment Budgetary Outlay Unit'],
             outlay=r['Notified Budgetary Outlay'], qty=r['Notified Qty'], qty_unit=r['Commitment Qty Unit']) for _, r in d.iterrows()]
rows += [dict(table='ES2_art9.4', member=r['Member'], year=r['Implementation Year'], doc=r['Symbol'], product=r['Product Description'],
              category='', unit=r['Budgetary Outlay Unit'], outlay=r['Total Budgetary outlay'], qty=r['Quantity'],
              qty_unit=r['Quantity Unit']) for _, r in e.iterrows()]
a = pd.DataFrame(rows); a = a[a.year <= 2022]
a = a.merge(a.groupby('member').year.max().rename('latest_year_le2022'), left_on='member', right_index=True)
a = a[a.year == a.latest_year_le2022]; a['positive'] = a.outlay.fillna(0) > 0
a.sort_values(['member', 'table', 'product']).to_csv(os.path.join(here, 'export_subsidies_latest_le2022.csv'), index=False)
print(a[a.positive].groupby(['member', 'year', 'unit']).outlay.sum())
