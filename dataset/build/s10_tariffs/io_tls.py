"""Duty out of the IO TLS row, and the split of what remains (duty_from_tls, tls_split).

Ported from the previous stage after review. The rules are unchanged:
- the effective duty rate of an importer and IO column is duty / VCIF over all partners
  (oil and gas fold into the IO column B06);
- duty removed from a column's TLS is that rate times the imported use, capped at the
  column's import share of TLS; any excess is reported and not netted (S13 FIT closes it);
- dom and imp basic rows are written byte-for-byte unchanged;
- the remaining TLS is split dom/imp pro rata to positive basic value; a column with no
  positive basic value keeps its TLS as unallocated.
"""
import csv
import gzip
import io
from collections import defaultdict

from .util import fnum, gz_write

FINAL_COLS = {'p', 'g', 'i', 'dpabr', 'X', 'stock_gap', 'grev_gap', 'OUT'}
TAIL_NOT_AGENT = {'X', 'stock_gap', 'grev_gap', 'OUT'}


class IOTable:
    def __init__(self, path):
        self.order = []
        self.tables = defaultdict(dict)
        with gzip.open(path, 'rt', newline='') as fh:
            self.header = fh.readline().rstrip('\r\n')
            self.cols = self.header.split(',')[2:]
            for line in fh:
                line = line.rstrip('\r\n')
                region, row, _rest = line.split(',', 2)
                self.tables[region][row] = next(csv.reader([line]))
                self.order.append((region, row, line))
        self.idx = {c: i for i, c in enumerate(['region', 'row'] + self.cols)}
        self.industries = [c for c in self.cols if c not in FINAL_COLS]
        self.agents = [c for c in self.cols if c not in TAIL_NOT_AGENT]
        self.use_cols = [c for c in self.cols if c != 'OUT']

    def get(self, region, row, col):
        text = self.tables[region][row][self.idx[col]]
        return float(text) if text not in ('', None) else 0.0

    def rows(self, region, prefix):
        return [r for r in self.tables[region] if r.startswith(prefix)]


def effective_rates(duty_cells, goods):
    """{(importer, sector): (duty, vcif)} -> {(importer, IO column): duty/vcif}."""
    duty, base = defaultdict(float), defaultdict(float)
    for (imp, sector), (d, v) in duty_cells.items():
        col = 'B06' if sector in ('oil', 'gas') else sector
        duty[(imp, col)] += d
        base[(imp, col)] += v
    return {k: duty[k] / v for k, v in base.items() if v > 0}


def remove_duty(table, regions, eff, goods):
    """Return (new_tls {region: {col: value}}, stats)."""
    taxed = set(goods) | {'B06'}
    stats = {'excess': 0.0, 'excess_cols': 0, 'removed': 0.0, 'neg_basic': 0, 'neg_tls': 0, 'new_neg_tls': 0}
    pre = {'gdp': {}, 'crp_out': {}, 'crp_va': {}, 'crp_inter': {}}
    new_tls = {}
    for region in regions:
        g = table.get
        pre['gdp'][region] = sum(g(region, 'VA', c) + g(region, 'TLS', c) for c in table.agents) + g(region, 'TLS', 'stock_gap')
        pre['crp_out'][region] = g(region, 'dom_crp', 'OUT')
        pre['crp_va'][region] = g(region, 'VA', 'crp')
        pre['crp_inter'][region] = sum(g(region, 'dom_crp', c) + g(region, 'imp_crp', c) for c in table.industries)
        dom_rows, imp_rows = table.rows(region, 'dom_'), table.rows(region, 'imp_')
        for row in dom_rows + imp_rows:
            stats['neg_basic'] += sum(1 for c in table.use_cols if g(region, row, c) < -1e-9)
        stats['neg_tls'] += sum(1 for c in table.use_cols if g(region, 'TLS', c) < -1e-9)
        new_tls[region] = {}
        for col in table.use_cols:
            uncapped = sum(eff.get((region, s), 0.0) * g(region, 'imp_' + s, col)
                           for s in table.industries if s in taxed and eff.get((region, s), 0.0))
            imp_sum = sum(g(region, r, col) for r in imp_rows)
            basic = imp_sum + sum(g(region, r, col) for r in dom_rows)
            tls = g(region, 'TLS', col)
            share = tls * imp_sum / basic if basic else 0.0
            cap = max(share, 0.0)
            removed = min(uncapped, cap) if uncapped > 0 else 0.0
            excess = uncapped - removed if uncapped > 0 else 0.0
            if excess > 1e-8:
                stats['excess'] += excess
                stats['excess_cols'] += 1
            stats['removed'] += removed
            new_tls[region][col] = tls - removed
            if new_tls[region][col] < -1e-9 and tls >= -1e-9:
                stats['new_neg_tls'] += 1
    return new_tls, stats, pre


def write_io(table, new_tls, path):
    out = [table.header + '\n']
    for region, row, line in table.order:
        if row != 'TLS':
            out.append(line + '\n')
            continue
        original = table.tables[region]['TLS']
        cells = [region, 'TLS'] + [original[table.idx[c]] if c == 'OUT' else fnum(new_tls[region][c]) for c in table.cols]
        buf = io.StringIO()
        csv.writer(buf, lineterminator='\n').writerow(cells)
        out.append(buf.getvalue())
    gz_write(path, b'', [line.encode() for line in out])


def non_tls_lines(path):
    out = []
    with gzip.open(path, 'rt', newline='') as fh:
        fh.readline()
        for raw in fh:
            text = raw.rstrip('\r\n')
            if text.split(',', 2)[1] != 'TLS':
                out.append(text)
    return out


def tls_split(table, new_tls, regions):
    rows, unallocated = [], 0
    for region in regions:
        dom_rows, imp_rows = table.rows(region, 'dom_'), table.rows(region, 'imp_')
        for col in table.use_cols:
            tls = new_tls[region][col]
            dv = [table.get(region, r, col) for r in dom_rows]
            iv = [table.get(region, r, col) for r in imp_rows]
            pos_dom, pos_imp = sum(v for v in dv if v > 0), sum(v for v in iv if v > 0)
            if pos_dom + pos_imp > 0:
                dom_tax = tls * pos_dom / (pos_dom + pos_imp)
                imp_tax, unalloc = tls - dom_tax, 0.0
            else:
                dom_tax = imp_tax = 0.0
                unalloc = tls
                if abs(tls) > 1e-9:
                    unallocated += 1
            rows.append([region, col, fnum(tls), fnum(sum(dv)), fnum(sum(iv)), fnum(dom_tax), fnum(imp_tax),
                         fnum(unalloc), 'basic'])
    return rows, unallocated
