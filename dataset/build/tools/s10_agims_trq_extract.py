"""Extract WTO AG-IMS Table MA:2 tariff-quota fill records for the S10 TRQ fill rule (trq_outside_kor_pan).

Input: the JSON array that https://agims.wto.org/en/TariffandOtherQuotas/GetResultsMA2 returns after a
ViewResults search with TRQReportType MA2 (dataset/data/wto_agims_trq/fetch_agims_ma2.sh saves it). The
service returns every member's MA:2 rows with Spanish member names. Output: one CSV row per member, year and
tariff quota for the members and years asked, with the notified quota quantity, the in-quota imports and the
national tariff lines exactly as notified.

Usage: python3 -I s10_agims_trq_extract.py <dump.json> <out.csv> <first_year> <last_year>
"""
import csv
import json
import sys

# AG-IMS (Spanish) member name -> ISO3. The members whose TRAINS HS6 averages hold in- and over-quota lines.
MEMBERS = {'Canadá': 'CAN', 'Suiza': 'CHE', 'Noruega': 'NOR', 'Japón': 'JPN', 'Israel': 'ISR', 'China': 'CHN'}
COLUMNS = ['iso3', 'member_agims', 'implementation_year', 'document', 'tqid', 'description', 'tariff_lines', 'unit',
           'quota_qty', 'in_quota_imports_qty', 'not_opened', 'reporting_year_type']


def main(dump, out, first, last):
    rows = json.load(open(dump, encoding='utf-8'))
    keep = []
    for r in rows:
        iso = MEMBERS.get(r.get('Member'))
        year = int(r.get('ImplementationYear') or 0)
        if iso is None or not first <= year <= last:
            continue
        lines = ', '.join(t.strip() for t in (r.get('TariffLines') or '').replace('\n', ',').replace(';', ',').split(',') if t.strip())
        qty, imp = r.get('NotifiedTRQQTY'), r.get('NotifiedImportQty')
        keep.append([iso, r['Member'], str(year), r.get('DocumentSymbol') or '', r.get('TQID') or '',
                     ' '.join((r.get('Description') or '').split()), lines, ' '.join((r.get('Unit') or '').split()),
                     '' if qty is None else repr(float(qty)), '' if imp is None else repr(float(imp)),
                     'yes' if r.get('NotOpened') else 'no', ' '.join((r.get('ReportingYearTypeName') or '').split())])
    keep.sort(key=lambda x: (x[0], int(x[2]), x[4], x[3]))
    with open(out, 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh, lineterminator='\n')
        w.writerow(COLUMNS)
        w.writerows(keep)
    print(f'{len(keep)} rows written to {out}')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))
