"""Export taxes (fix-round item A2; PLAN.md:292; GTAP 12 ch.17A eq. 17.30: VFOB = VXSB x export-tax power).

A cited 2022 total is spread over the exporter's taxed products and booked as VFOB > VXSB.

- The total is OECD Global Revenue Statistics T_5124 (taxes on exports), 2022, in USD
  (`oecd_grs/grs_rsglobal_5121_5124_2017_2022.csv`).
- The taxed products and their statutory rates are the WTO Trade Policy Review lists in
  `config/s10/export_tax_products_2022.csv` (each row cites the report and page).
- Allocation (export_tax_allocation): each product's weight is its cited ad valorem rate times the
  exporter's BACI 2022 exports of its HS lines; a row whose duty is specific or set by formula takes the
  mean of that country's cited ad valorem rates as its weight. The sector rate is the sector's duty over
  the sector's VFOB (all destinations alike). An HS line takes the row with the longest matching prefix;
  sector '*' means the line's own S01 sector. A line whose sector has no S07 VFOB for the exporter
  carries no weight.
- A country with a GRS total but no product list, and a country with a product list but no 2022 total,
  is not booked and is reported as NEEDS-SOURCE (export_tax_unlisted).

Rates path (export_tax_rates; fix round A2 for RUS, IND and CHN, which have no GRS T_5124 2022 value):
- `config/s10/export_tax_rates_2022.csv` holds a 2022 annual ad valorem rate (percent of FOB) per exporter and
  HS prefix. Specific and formula duties are ad valorem equivalents on the BACI 2022 unit value, and duties in
  force for part of the year are time-weighted (`dataset/data/export_duty_schedules_2022/`,
  `derive_export_duty_aves_2022.py` writes `derived_aves_2022.csv`). Every row cites its legal basis or source,
  a URL and a retrieval date.
- The sector rate is the export-weighted mean of the line rates over all of the exporter's BACI 2022 lines of
  the sector (untaxed lines at zero); duty = rate x S07 VFOB of the sector, the same to every destination.
- Implied revenue is reported against IMF GFS G1152 (taxes on exports) where it exists (S10-Rxtaxrev).
"""
import csv
from collections import defaultdict

from .config import ConfigError, read_table
from .util import fnum

Q_XTAX = 'PLAN.md:292; GTAP 12 ch.17A eq. 17.30; fix list A2'
GRS_CODE = 'T_5124'
RATE_KINDS = ('ad_valorem', 'ave_time_weighted', 'ave_of_specific', 'ave_of_formula', 'cited_zero')
RATES_SOURCE = 'statutory 2022 rates (export_tax_rates_2022.csv)'


def read_grs_totals(path, year=2022):
    """{iso: USD million} for GRS T_5124 in the given year (UNIT_MULT gives the power of ten)."""
    out = {}
    with open(path, newline='') as fh:
        for row in csv.DictReader(fh):
            if row['STANDARD_REVENUE'] != GRS_CODE or row['UNIT_MEASURE'] != 'USD' or row['SECTOR'] != 'S13':
                continue
            if int(row['TIME_PERIOD']) != year or not row['OBS_VALUE']:
                continue
            mult = int(float(row.get('UNIT_MULT') or 0))
            out[row['REF_AREA']] = float(row['OBS_VALUE']) * 10 ** mult / 1e6
    return out


def load_products(path=None):
    """export_tax_products_2022.csv -> {iso: [(sector, hs prefixes, rate or None, source)]}."""
    cols = ('exporter', 'sector', 'hs_prefixes', 'rate_pct', 'rate_kind', 'product', 'source', 'page', 'decided_by', 'decided_at')
    rows = read_table('export_tax_products_2022.csv', cols, path=path)
    out = defaultdict(list)
    for row in rows:
        if not row['decided_by'] or not row['decided_at'] or not row['source'] or not row['page']:
            raise ConfigError(f'export_tax_products_2022.csv {row["exporter"]} {row["product"]}: source, page or decision blank')
        kind = row['rate_kind']
        if kind not in ('ad_valorem', 'specific_or_formula', 'cited_zero'):
            raise ConfigError(f'export_tax_products_2022.csv: rate_kind {kind!r}')
        prefixes = tuple(p for p in row['hs_prefixes'].split(';') if p)
        if not prefixes:
            raise ConfigError(f'export_tax_products_2022.csv {row["exporter"]} {row["product"]}: no HS prefix')
        rate = float(row['rate_pct']) if kind == 'ad_valorem' else (0.0 if kind == 'cited_zero' else None)
        out[row['exporter']].append((row['sector'], prefixes, rate, f"{row['source']} p.{row['page']}"))
    return dict(out)


def allocate(totals, products, exp_hs, hs_sector, vfob_sec, regions_single, skip=frozenset()):
    """Returns (rates {(region, sector): rate on VFOB}, rows for export_tax_s10.csv, report dict).

    exp_hs: {(iso, hs6): thousand USD} (BACI 2022); hs_sector: hs6 -> sector; vfob_sec: {(region, sector): USD m}.
    skip: exporters booked by the rates path (rates_booked), left out here."""
    rates, rows = {}, []
    not_booked = []
    by_iso = defaultdict(list)
    for (iso, hs), v in exp_hs.items():
        by_iso[iso].append((hs, v))
    for iso in sorted((set(totals) | set(products)) - set(skip)):
        total = totals.get(iso)
        plist = products.get(iso)
        if iso not in regions_single:
            if total:
                not_booked.append(f'{iso} GRS {total:.3f} USD m: not a single region of the build')
            continue
        if not plist:
            if total and total > 0:
                not_booked.append(f'{iso} GRS {total:.3f} USD m: NEEDS-SOURCE product list')
            continue
        if not total or total <= 0:
            if any(r is None or r > 0 for _s, _p, r, _src in plist):
                not_booked.append(f'{iso}: product list but no 2022 total, NEEDS-SOURCE revenue')
            continue
        cited = [r for _s, _p, r, _src in plist if r is not None and r > 0]
        fill = sum(cited) / len(cited) if cited else 1.0
        weight, srcs = defaultdict(float), defaultdict(set)
        for hs, v in by_iso.get(iso, ()):
            best = None
            for sector, prefixes, rate, src in plist:
                for pre in prefixes:
                    if hs.startswith(pre) and (sector == '*' or hs_sector.get(hs) == sector):
                        if best is None or len(pre) > best[0]:
                            best = (len(pre), rate, src)
            if best is None:
                continue
            r = fill if best[1] is None else best[1]
            sec = hs_sector.get(hs)
            if r <= 0 or sec is None or vfob_sec.get((iso, sec), 0.0) <= 0:
                continue          # no S07 VFOB in that sector to carry the duty (e.g. ely, priced by S11)
            weight[sec] += r / 100.0 * v / 1000.0
            srcs[sec].add(best[2])
        wsum = sum(weight.values())
        if wsum <= 0:
            not_booked.append(f'{iso} GRS {total:.3f} USD m: listed products have no 2022 BACI exports')
            continue
        for sector, w in sorted(weight.items()):
            duty = total * w / wsum
            base = vfob_sec.get((iso, sector), 0.0)
            rate = duty / base if base > 0 else float('inf')
            rates[(iso, sector)] = rate
            rows.append([iso, sector, fnum(total), fnum(duty), fnum(base), fnum(rate), fnum(w), 'OECD GRS T_5124 2022',
                         '; '.join(sorted(srcs[sector])), 'fob'])
    return rates, rows, dict(not_booked=not_booked)


def load_rates(path=None):
    """export_tax_rates_2022.csv -> {iso: [(sector, hs prefixes, rate as a share of FOB, source)]}."""
    cols = ('exporter', 'sector', 'hs_prefixes', 'rate_pct', 'rate_kind', 'product', 'derivation', 'source', 'source_url',
            'retrieved', 'decided_by', 'decided_at')
    rows = read_table('export_tax_rates_2022.csv', cols, path=path)
    out, seen = defaultdict(list), set()
    for row in rows:
        iso = row['exporter']
        for c in ('source', 'source_url', 'retrieved', 'decided_by', 'decided_at', 'derivation'):
            if not row[c]:
                raise ConfigError(f'export_tax_rates_2022.csv {iso} {row["hs_prefixes"]}: {c} blank')
        if row['rate_kind'] not in RATE_KINDS:
            raise ConfigError(f'export_tax_rates_2022.csv: rate_kind {row["rate_kind"]!r}')
        prefixes = tuple(p for p in row['hs_prefixes'].split(';') if p)
        if not prefixes:
            raise ConfigError(f'export_tax_rates_2022.csv {iso} {row["product"]}: no HS prefix')
        rate = float(row['rate_pct']) / 100.0
        if not 0.0 <= rate < 1.0 or (row['rate_kind'] == 'cited_zero') != (rate == 0.0):
            raise ConfigError(f'export_tax_rates_2022.csv {iso} {row["hs_prefixes"]}: rate {row["rate_pct"]} '
                              f'with kind {row["rate_kind"]}')
        for pre in prefixes:
            if (iso, row['sector'], pre) in seen:
                raise ConfigError(f'export_tax_rates_2022.csv {iso} {pre}: duplicate prefix')
            seen.add((iso, row['sector'], pre))
        out[iso].append((row['sector'], prefixes, rate, row['source']))
    return dict(out)


def read_gfs_export_taxes(path, fx_path, year=2022):
    """{iso: USD million} of IMF GFS G1152 (taxes on exports), general government (S13), national currency over
    the WDI PA.NUS.FCRF rate of the year. A country with no S13 value, or no rate, is left out."""
    fx = {}
    with open(fx_path, newline='') as fh:
        for row in csv.DictReader(fh):
            if row['series'] == 'PA.NUS.FCRF' and row['year'] == str(year) and row['value']:
                fx[row['iso3']] = float(row['value'])
    out = {}
    with open(path, newline='') as fh:
        for row in csv.DictReader(fh):
            if (row['INDICATOR'] == 'G1152_T' and row['SECTOR'] == 'S13' and row['TIME_PERIOD'] == str(year)
                    and row['OBS_VALUE'] and row['COUNTRY'] in fx):
                out[row['COUNTRY']] = float(row['OBS_VALUE']) / fx[row['COUNTRY']] / 1e6
    return out


def rates_booked(rates_tab, exp_hs, hs_sector, vfob_sec, regions_single, published=None):
    """Rates path. Returns (rates {(region, sector): rate on VFOB}, rows for export_tax_s10.csv, report dict).

    Each HS line takes the row with the longest matching prefix (sector '*' or the line's own sector); the sector
    rate is sum(line rate x BACI value) over the BACI value of all the exporter's lines of the sector; duty =
    rate x S07 VFOB. published: {iso: USD m} (IMF GFS G1152), for the revenue report only."""
    published = published or {}
    rates, rows, rep = {}, [], {'not_booked': [], 'revenue': []}
    by_iso = defaultdict(list)
    for (iso, hs), v in exp_hs.items():
        by_iso[iso].append((hs, v))
    for iso in sorted(rates_tab):
        if iso not in regions_single:
            rep['not_booked'].append(f'{iso}: rates table but not a single region of the build')
            continue
        num, den, srcs = defaultdict(float), defaultdict(float), defaultdict(set)
        for hs, v in by_iso.get(iso, ()):
            sec = hs_sector.get(hs)
            if sec is None:
                continue
            den[sec] += v
            best = None
            for sector, prefixes, rate, src in rates_tab[iso]:
                for pre in prefixes:
                    if hs.startswith(pre) and (sector == '*' or sector == sec):
                        if best is None or len(pre) > best[0]:
                            best = (len(pre), rate, src)
            if best is not None:
                num[sec] += best[1] * v
                srcs[sec].add(best[2])
        implied = 0.0
        for sec in sorted(num):
            base = vfob_sec.get((iso, sec), 0.0)
            if num[sec] <= 0 or base <= 0:
                continue          # untaxed, or no S07 VFOB in that sector to carry the duty (e.g. ely, priced by S11)
            rate = num[sec] / den[sec]
            duty = rate * base
            implied += duty
            rates[(iso, sec)] = rate
            rows.append([iso, sec, '', fnum(duty), fnum(base), fnum(rate), fnum(num[sec] / 1000.0), RATES_SOURCE,
                         '; '.join(sorted(srcs[sec])), 'fob'])
        rep['revenue'].append((iso, implied, published.get(iso)))
    return rates, rows, rep


# beta v4 G12 (Grok QA C3): export duties of a customs union's members do not apply to exports to other members (EAEU Treaty
# Art. 25(1), the rows of config/s11/export_tax_exempt_routes.csv). S11 applies this to coa, oil, gas and pet, which it
# re-prices; S10 applies it to every other sector.
UNION_EXEMPT = 'union_members_zero_duty_on_member_routes_non_energy_grs_total_respread_statutory_rate_kept'
ENERGY_SECTORS = ('coa', 'oil', 'gas', 'pet')


def load_union_routes(path):
    """config/s11/export_tax_exempt_routes.csv -> {iso: union} (columns union, members, decided_by, decided_at, basis)."""
    import csv
    with open(path, newline='') as fh:
        rows = list(csv.DictReader(fh))
    return {iso.strip(): r['union'] for r in rows for iso in r['members'].split(';') if iso.strip()}


def union_exempt(rates, rows, vfob_rows, union_of, rates_source=None, skip=ENERGY_SECTORS):
    """G12: take the routes between two members of one union out of the export-duty base of every sector not in skip.
    An exporter booked from a GRS total keeps that total, spread over its taxable (non-member) VFOB: rate = duty /
    taxable VFOB. An exporter on statutory rates (total_source = rates_source) keeps its rate and books duty = rate x
    taxable VFOB. rates and rows (export_tax_s10.csv rows) are changed in place; the row's vfob_musd becomes the
    taxable VFOB. Returns (exempt(exporter, importer, sector) -> bool, {(exporter, sector): exempt VFOB})."""
    def exempt(e, i, sec):
        u = union_of.get(e)
        return u is not None and e != i and union_of.get(i) == u and sec not in skip
    tot, ex = defaultdict(float), defaultdict(float)
    for sec, e, i, v in vfob_rows:
        if (e, sec) in rates:
            tot[(e, sec)] += v
            if exempt(e, i, sec):
                ex[(e, sec)] += v
    for r in rows:
        k = (r[0], r[1])
        if ex.get(k, 0.0) <= 0 or tot[k] <= 0:
            continue
        taxable = float(r[4]) * (1.0 - ex[k] / tot[k])
        if rates_source is not None and r[7] == rates_source:
            r[3] = fnum(rates[k] * taxable)
        else:
            rates[k] = float(r[3]) / taxable if taxable > 0 else float('inf')
            r[5] = fnum(rates[k])
        r[4] = fnum(taxable)
    return exempt, {k: v for k, v in ex.items() if v > 0}
