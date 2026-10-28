"""Beta v5 Cuba (S02 choice gdp_lcu_official_rate): GDP from the national statistics office's own national-currency
accounts, converted at a listed official rate.

UN AMA converts Cuban GDP at the old 1 CUP = 1 USD peg (AMA 147.1 bn USD in 2022), and its national-currency series (147.1
bn CUP) is not the series ONEI reports after the 2021 currency unification: ONEI's own 2022 GDP, as reported to UNSD
(UN SNA table 1.1, series 300), is 633.4 bn CUP. Neither WDI nor the IMF WEO publishes a USD GDP for Cuba. With the
choice on, each economy in config/s02/gdp_official_rate_2022.csv takes GDP, household consumption, government consumption
and GFCF from the official table, divided by the listed official rate (Cuba: 24 CUP per USD, the Banco Central de Cuba rate
for 2022). The choice of rate is ours (labelled departure; GTAP 12 ch.7 takes GDP from WDI, then UN sources).
"""
import csv

CHOICE = 'gdp_lcu_official_rate'
ON = 'listed_economies_official_lcu_gdp_and_expenditure_at_the_listed_official_rate'
VALUES = (ON, 'off')
COLUMNS = ('iso3', 'year', 'lcu_per_usd', 'rate_source', 'data_file', 'decided_by', 'decided_at', 'basis')
# S02 variable -> (SNA code, item text) in UN SNA table 1.1
ITEMS = {'GDP': ('B.1*g', 'Equals: GROSS DOMESTIC PRODUCT'), 'C': ('P.3', 'Household final consumption expenditure'),
         'G': ('P.3', 'General government final consumption expenditure'), 'I': ('P.51', 'Gross fixed capital formation')}


def load_rows(path):
    """config/s02/gdp_official_rate_2022.csv -> {iso3: row}; stop on a missing column, source or attribution or a rate <= 0."""
    with open(path, newline='') as fh:
        rd = csv.DictReader(fh)
        if tuple(rd.fieldnames or ()) != COLUMNS:
            raise SystemExit(f'{path}: columns {rd.fieldnames} are not {COLUMNS}')
        rows = list(rd)
    out = {}
    for r in rows:
        if r['iso3'] in out or not all(r[c].strip() for c in ('rate_source', 'data_file', 'decided_by', 'decided_at')):
            raise SystemExit(f'{path}: row {r["iso3"]} is listed twice or has no source or attribution')
        if not float(r['lcu_per_usd']) > 0:
            raise SystemExit(f'{path}: {r["iso3"]} rate must be positive')
        out[r['iso3']] = r
    return out


def read_table(path, iso3, year):
    """{S02 variable: value in national currency} from a UN SNA table 1.1 extract (columns iso3, item, code, year, value_lcu).
    Stops when an item is missing or listed twice."""
    got = {}
    with open(path, newline='') as fh:
        for r in csv.DictReader(fh):
            if r['iso3'] != iso3 or int(r['year']) != year:
                continue
            for k, (code, item) in ITEMS.items():
                if r['code'] == code and r['item'].strip() == item:
                    if k in got:
                        raise SystemExit(f'{path}: {iso3} {year} {item} listed twice')
                    got[k] = float(r['value_lcu'])
    miss = [k for k in ITEMS if k not in got]
    if miss:
        raise SystemExit(f'{path}: {iso3} {year} has no {miss}')
    return got


def to_musd(values, lcu_per_usd):
    """National currency units -> USD million."""
    return {k: v / float(lcu_per_usd) / 1e6 for k, v in values.items()}
