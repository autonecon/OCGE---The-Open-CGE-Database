"""S16 checks of PLAN §3(k) on the finished data base. Each is a pure function returning (number of failures,
detail) or a report table, so tests/test_s16_checks.py can show that each one fails on a bad input.

The arrays are the S15 HAR files as read back by harpy (Float32): the data base a user receives. The identity,
sign and saving checks of S15 (s15_har/checks.py) are reused on them; the functions here add the rows of the
§3(k) table that S15 does not run: the stage roll-up, subsidy provenance, macro targets, held trade and tariff
rates, energy output, the region list, the ledger, the concept tags and the map results.
"""
import os
import re

import numpy as np
import pandas as pd

TOL = 1e-6
# The S11 and S13 files print USD million to 6 decimals: absolute floor for a comparison with them (USD 10)
ABS = 1e-5


def _detail(bad, k=10):
    return '; '.join(bad[:k]) + (f'; and {len(bad) - k} more' if len(bad) > k else '')


# ------------------------------------------------------------------ stage roll-up
def stamp_info(stage_dir, sha256):
    """STAMP lines of a stage: (present, stamped SHA256SUMS, actual SHA256SUMS, {upstream name: SHA256SUMS})."""
    p = os.path.join(stage_dir, 'STAMP')
    sums = os.path.join(stage_dir, 'output', 'SHA256SUMS')
    actual = sha256(sums) if os.path.exists(sums) else ''
    if not os.path.exists(p):
        return False, '', actual, {}
    lines = open(p).read().splitlines()
    stamped = next((l.rsplit(' ', 1)[1] for l in lines if l.startswith('output SHA256SUMS sha256 ')), '')
    ups = {l.split()[1]: l.split()[-1] for l in lines if l.startswith('upstream ')}
    return True, stamped, actual, ups


def rollup(stages_dir, names, sha256):
    """Every stage S01-S15 has a STAMP, its SHA256SUMS equals the one in its STAMP, its checks.json has no hard
    FAIL, and every upstream SHA256SUMS a STAMP names equals that upstream's current SHA256SUMS (the chain).
    Returns (failures, detail, table)."""
    info = {n: stamp_info(os.path.join(stages_dir, n), sha256) for n in names}
    rows, bad = [], []
    for n in names:
        present, stamped, actual, ups = info[n]
        import json
        cp = os.path.join(stages_dir, n, 'checks.json')
        checks = json.load(open(cp)) if os.path.exists(cp) else []
        fails = [c['id'] for c in checks if c['status'] == 'FAIL']
        hard = sum(c['kind'] == 'hard' for c in checks)
        # an upstream outside `names` (e.g. PREP_energy_volumes) is read from its own folder: never skipped
        for u in ups:
            if u not in info:
                info[u] = stamp_info(os.path.join(stages_dir, u), sha256)
        broken = [u for u, h in ups.items() if info[u][2] != h]
        ok = present and stamped == actual and bool(actual) and not fails and bool(checks) and not broken
        if not ok:
            bad.append(f'{n}: STAMP {"yes" if present else "NO"}, SHA256SUMS {"bound" if stamped == actual and actual else "NOT BOUND"}, '
                       f'hard FAIL {fails}, chain broken {broken}')
        rows.append(dict(stage=n, stamp=present, sums_bound=stamped == actual and bool(actual), checks=len(checks), hard=hard,
                         hard_fail=len(fails), report_note=sum(c['status'] == 'NOTE' for c in checks), upstreams=' '.join(sorted(ups)),
                         chain_broken=' '.join(broken), sha256sums=actual[:12]))
    return len(bad), _detail(bad), pd.DataFrame(rows)


def collected(stages_dir, ids):
    """Status of named upstream checks (the §3(k) rows that need source data the stage that built the item read).
    ids: [(stage dir name, check id)]. Returns (failures, detail, rows)."""
    import json
    rows, bad = [], []
    for st, cid in ids:
        checks = json.load(open(os.path.join(stages_dir, st, 'checks.json')))
        hit = [c for c in checks if c['id'] == cid]
        if not hit:
            bad.append(f'{st} {cid}: not found')
            continue
        c = hit[0]
        if c['status'] == 'FAIL':
            bad.append(f'{st} {cid}: FAIL')
        rows.append(dict(stage=st, id=cid, kind=c['kind'], status=c['status'], value=c['value'], description=c['description'][:200]))
    return len(bad), _detail(bad), pd.DataFrame(rows)


# ------------------------------------------------------------------ signs and subsidies
def vmsb_ge_vcif(D, regs, comm):
    bad = np.argwhere(D['VMSB'] < D['VCIF'] * (1 - TOL) - 1e-9)
    return len(bad), _detail([f'{comm[c]} {regs[s]}->{regs[d]}' for c, s, d in bad])


A13_SHIFT_MAX = 1e-4     # the A13 remainder-rate shift on a column the seed moved (S14 cell_powers), at most this rate
REMAINDER_MAX = 1e-5     # the S14 remainder rate on any other column (its tax held on the S14 flows), at most this rate


def negative_taxes(D, rel=TOL):
    """Cells where purchasers' value is below basic value (a subsidy), by tax type, beyond Float32 and S14 rounding
    (relative 1e-6 of the larger side). Returns {type: bool array}."""
    lt = lambda a, b: a < b - rel * np.maximum(np.abs(a), np.abs(b)) - 1e-9
    out = {'product_firm_dom': lt(D['VDFP'], D['VDFB']), 'product_firm_imp': lt(D['VMFP'], D['VMFB'])}
    for a in 'PGI':
        out[f'product_{a}_dom'] = lt(D[f'VD{a}P'], D[f'VD{a}B'])
        out[f'product_{a}_imp'] = lt(D[f'VM{a}P'], D[f'VM{a}B'])
    out['output'] = lt(D['MAKB'], D['MAKS'])
    out['factor_use'] = lt(D['EVFP'], D['EVFB'])
    out['income'] = lt(D['EVFB'], D['EVOS'])
    out['export'] = lt(D['VFOB'], D['VXSB'])
    out['import'] = lt(D['VMSB'], D['VCIF'])
    return out


def subsidy_provenance(D, sets, io13, support, exsub, rebal, seeded=frozenset(), io12_neg=frozenset(), energy_neg=frozenset(),
                       seed_cols=frozenset(), shift_max=A13_SHIFT_MAX):
    """Every negative tax cell traces to a cited subsidy source (PLAN §3(k) signs; TP01 §7):
      product taxes: a negative net product tax (TLS row) of the source I-O column in io_s13, or in io_s12 for a region
        with its own I-O table (io12_neg: {(region, column)}, the S05 donor regions left out: their donor subsidies are
        set to 0 in S13, S13-Hdonorsub), booked PSE input support on that column (io_s13 PSE_input row, negative; S10,
        OECD MONEVA), or a negative GTAP energy-tax rate or booked IEA fuel subsidy on that energy cell (energy_neg:
        {(region, column, commodity)} from energy_tax_rates_s13 and fuel_subsidy_columns_s13; GTAP 12 ch.12);
      output tax: a negative net production tax (PTAX row) in io_s13, booked PSE output support (S10), or an S14
        rounding move of at most 0.001 USD million (rebalance_s14, S14-Hrebalance) on a column with no PTAX, the
        cell itself at most 0.001;
      factor and income taxes: PSE payments based on that factor (land, capital, labour) or on all factors (S10)
        for that region and sector; a negative cell with neither has no source;
      export tax: a booked WTO export subsidy (S10) for that exporter and sector;
      import tariff: none may be negative.
    A column the A13 seed moved (seed_cols: {(region, column)} from seed_columns_s14.csv) keeps its tax value over
    one remainder rate on its new flows (S14 cell_powers), so a cell with no S13 rate can carry a shift of a few
    1e-6: a negative cell there with a rate above -shift_max traces to it (source S14-A13-shift). On every other
    column S14 holds the column's tax on its own flows (B14, re-balancing) over the same remainder rate, so a cell
    with a rate above -REMAINDER_MAX traces to that remainder (source S14-remainder).
    A column S14 seeded in a one-sided pair (fix list A13; seeded: {(region, comm)} from seeded_pairs_s14.csv) took
    a share of its suppliers' columns, taxes and subsidies included, so its negative product, output and factor
    taxes trace to theirs (source S14-A13-seed).
    io13: io_s13 long rows with columns region, row, column, value. Returns (failures, detail, table by type)."""
    regs, comm, endw = sets['REG'], sets['COMM'], sets['ENDW']
    cols_fd = {'P': 'p', 'G': 'g', 'I': 'i'}
    tls = {(r.region, r.column) for r in io13[(io13['row'] == 'TLS') & (io13['value'] < 0)].itertuples()}
    pse_in = {(r.region, r.column) for r in io13[(io13['row'] == 'PSE_input') & (io13['value'] < 0)].itertuples()}   # booked as a negative tax
    ptax = {(r.region, r.column) for r in io13[(io13['row'] == 'PTAX') & (io13['value'] < 0)].itertuples()}
    sup = support[support['value_musd'] > 0]
    out_sup = {(r.region, r.sector) for r in sup[sup['basis'] == 'output'].itertuples()}
    fsup = sup[sup['basis'].isin(['land', 'capital', 'labour', 'factors'])]
    fac_sup = {(r.region, s, r.basis) for r in fsup.itertuples() for s in (comm if r.sector in ('all', '*') else [r.sector])}
    fbasis = {e: ('land' if e == 'land' else 'capital' if e == 'capital' else 'natres' if e in ('natres', 'natlres') else 'labour') for e in endw}
    xs = {(r.region, r.sector) for r in exsub[exsub['booked'] == 'yes'].itertuples()}
    rb = rebal[(rebal['kind'] == 'output tax') & ((rebal['after'] - rebal['before']).abs() <= 1e-3)]
    rounding = {tuple(k.split()[::-1]) for k in rb['key']}   # 'JOR oil' -> ('oil', 'JOR')
    neg = negative_taxes(D)
    rows, bad = [], []
    for typ, mask in neg.items():
        idx = np.argwhere(mask)
        sources, miss = {}, []
        for i in idx:
            if typ.startswith('product_firm'):
                c, a, r = i
                key = (regs[r], comm[a])
                kb, kp = ('VDFB', 'VDFP') if typ.endswith('dom') else ('VMFB', 'VMFP')
                rate = D[kp][c, a, r] / D[kb][c, a, r] - 1.0
                src = ('IO-TLS' if key in tls or key in io12_neg else ('PSE-input' if key in pse_in else
                       ('IEA-energy-rate' if (regs[r], comm[a], comm[c]) in energy_neg else ('S14-A13-seed' if key in seeded else
                        ('S14-A13-shift' if key in seed_cols and rate > -shift_max else ('S14-remainder' if rate > -REMAINDER_MAX else ''))))))
                lab = f'{comm[c]} into {comm[a]} {regs[r]}'
            elif typ.startswith('product_'):
                c, r = i
                key = (regs[r], cols_fd[typ.split('_')[1]])
                ag, sd = typ.split('_')[1], typ.split('_')[2]
                rate = D[f'V{"D" if sd == "dom" else "M"}{ag}P'][c, r] / D[f'V{"D" if sd == "dom" else "M"}{ag}B'][c, r] - 1.0
                src = ('IO-TLS' if key in tls or key in io12_neg else ('IEA-energy-rate' if (*key, comm[c]) in energy_neg else
                       ('S14-A13-shift' if key in seed_cols and rate > -shift_max else ('S14-remainder' if rate > -REMAINDER_MAX else ''))))
                lab = f'{comm[c]} {typ.split("_")[1]} {regs[r]}'
            elif typ == 'output':
                c, a, r = i
                key = (regs[r], comm[a])
                small = abs(D['MAKB'][c, a, r] - D['MAKS'][c, a, r]) <= 1e-3 + ABS     # a rounding move leaves at most 0.001
                src = 'IO-PTAX' if key in ptax else ('PSE-output' if key in out_sup else ('S14-rounding' if small and (comm[a], regs[r]) in rounding else
                                                                                         ('S14-A13-seed' if key in seeded else '')))
                lab = f'{comm[a]} {regs[r]}'
            elif typ in ('factor_use', 'income'):
                e, a, r = i
                # support paid on this factor's basis, or on all factors
                src = 'PSE-factor' if {(regs[r], comm[a], fbasis[endw[e]]), (regs[r], comm[a], 'factors')} & fac_sup else ('S14-A13-seed' if (regs[r], comm[a]) in seeded else '')
                lab = f'{endw[e]} in {comm[a]} {regs[r]}'
            elif typ == 'export':
                c, s, d = i
                src = 'WTO-export-subsidy' if (regs[s], comm[c]) in xs else ''
                lab = f'{comm[c]} {regs[s]}->{regs[d]}'
            else:
                c, s, d = i
                src, lab = '', f'{comm[c]} {regs[s]}->{regs[d]}'
            sources[src or 'NONE'] = sources.get(src or 'NONE', 0) + 1
            if not src:
                miss.append(lab)
        rows.append(dict(tax=typ, negative_cells=len(idx), **{f'src_{k}': v for k, v in sorted(sources.items())}))
        if miss:
            bad.append(f'{typ}: {len(miss)} cells without a source, e.g. ' + ', '.join(miss[:4]))
    n = sum(int(r.get('src_NONE', 0)) for r in rows)
    return n, _detail(bad), pd.DataFrame(rows).fillna(0)


# ------------------------------------------------------------------ macro
def macro(acc, s02, s13, tol=TOL):
    """GDP (expenditure) of the data base equals the S02 target (C14), within 1e-6 relative after Float32.
    Returns (failures, detail, table with the C, G, I factor and the GFCF ratio)."""
    gdp = acc['C'] + acc['G'] + acc['I'] + acc['X'] - acc['M']
    t = pd.DataFrame(dict(GDP=gdp, GDP_S02=s02['GDP_musd'], C_G_I_factor=s13['factor'], I=acc['I'], GFCF_S02=s02['GFCF_musd']))
    t['gdp_rel_gap'] = (t['GDP'] - t['GDP_S02']).abs() / t['GDP_S02'].abs()
    t['I_over_GFCF'] = t['I'] / t['GFCF_S02']
    bad = t[t['gdp_rel_gap'] > tol]
    return len(bad), _detail([f'{r}: GDP {v.GDP:.6g} vs S02 {v.GDP_S02:.6g}' for r, v in bad.iterrows()]), t


# ------------------------------------------------------------------ trade and tariffs
def held_trade(D, sets, trade13, tol=TOL, moves=None, move_max=1e-3):
    """Exports (VXSB by exporter), imports (VMSB by importer) and VST equal what S13 held (S09 services, S10 goods,
    S11 energy, S08 margins), by region and commodity: within 1e-6 relative or ABS (the 6-decimal print), after the
    S14 trade rules (moves: trade_moves_s14.csv, region, sector, dX, dM, dVST, swap_musd: B14 cells below USD 1, the
    re-balancing VCIF = VFOB + VTWR and the A13 swap routes). Each move less its A13 swap is at most move_max USD
    million or tol of the value (B14 and the re-balancing move cents; a larger move is a failure)."""
    regs, comm, marg = sets['REG'], sets['COMM'], sets['MARG']
    t = trade13.set_index(['region', 'sector']).copy()
    bad = []
    if moves is not None and len(moves):
        mv = moves.set_index(['region', 'sector'])
        t = t.reindex(t.index.union(mv.index))
        t[['X', 'M', 'VST']] = t[['X', 'M', 'VST']].fillna(0.0)
        for lab in ('X', 'M', 'VST'):
            t[lab] = t[lab].add(mv['d' + lab], fill_value=0.0)
        for lab in ('X', 'M', 'VST'):
            held = t[lab].reindex(mv.index).fillna(0.0).abs()
            big = (mv['d' + lab] - (mv['swap_musd'] if lab != 'VST' else 0.0)).abs() > np.maximum(move_max, tol * held)
            bad += [f'S14 move {lab} {i[1]} {i[0]}: {mv.loc[i, "d" + lab]:.6g}' for i in mv.index[big]]
    X = pd.DataFrame(D['VXSB'].sum(axis=2), index=comm, columns=regs).stack().swaplevel()
    M = pd.DataFrame(D['VMSB'].sum(axis=1), index=comm, columns=regs).stack().swaplevel()
    X.index.names = M.index.names = ['region', 'sector']
    for lab, a, b in (('X', X, t['X']), ('M', M, t['M'])):
        a, b = a.align(b, fill_value=0.0)
        g = (a - b).abs() - np.maximum(tol * b.abs(), ABS)
        bad += [f'{lab} {i[1]} {i[0]}: {a[i]:.6g} vs held {b[i]:.6g}' for i in g[g > 0].index]
    vst = pd.DataFrame(D['VST'], index=marg, columns=regs).stack().swaplevel()
    vst.index.names = ['region', 'sector']
    h = t['VST'].reindex(vst.index).fillna(0.0)
    g = (vst - h).abs() - np.maximum(tol * h.abs(), ABS)
    bad += [f'VST {i[1]} {i[0]}: {vst[i]:.6g} vs held {h[i]:.6g}' for i in g[g > 0].index]
    return len(bad), _detail(bad)


def tariff_power(D, sets, routes, min_cif=1e-3, tol=1e-6, small=1e-6, swaps=None):
    """No rate scaling and no added value on a route (PLAN §3(k) tariffs). routes: the border values S14 merged,
    rebuilt from the sources (comm, src, dst, VFOB, VCIF, VMSB: S10 goods, S11 energy, S09 services and the travel
    rows S13 held, s14_assembly.method.bilateral). S14 then sets VCIF = VFOB + VTWR and keeps each route's power.
    So, on every route: the VFOB of the data base equals the rebuilt VFOB (relative tol, absolute floor ABS,
    Float32 rounding), and VMSB/VCIF equals the rebuilt VMSB/VCIF (a route without a border value has VMSB = VCIF).
    Routes with VCIF below min_cif USD million are left out of the power test (the source files carry 10 decimals,
    too few for a rate on them). Returns (failures, detail, routes checked)."""
    regs, comm = sets['REG'], sets['COMM']
    ri, ci = {r: i for i, r in enumerate(regs)}, {c: i for i, c in enumerate(comm)}
    if small and 'VXSB' in routes.columns:
        # B14: S14 sets the routes with VXSB below USD 1 to zero
        routes = routes[routes['VXSB'] >= small]
    if swaps is not None and len(swaps):
        # A13: two tax-free routes per swap, VFOB = VCIF = VMSB = musd
        swaps = swaps[swaps['partner'].fillna('') != '']
        sw = pd.concat([pd.DataFrame(dict(comm=swaps['comm'], src=a, dst=b, VFOB=swaps['musd'], VCIF=swaps['musd'], VMSB=swaps['musd']))
                        for a, b in ((swaps['region'], swaps['partner']), (swaps['partner'], swaps['region']))])
        routes = pd.concat([routes[['comm', 'src', 'dst', 'VFOB', 'VCIF', 'VMSB']], sw], ignore_index=True)
    vf, vc, vm = (np.zeros_like(D['VCIF']) for _ in range(3))
    idx = (routes['comm'].map(ci).to_numpy(), routes['src'].map(ri).to_numpy(), routes['dst'].map(ri).to_numpy())
    np.add.at(vf, idx, routes['VFOB'].to_numpy(float))
    np.add.at(vc, idx, routes['VCIF'].to_numpy(float))
    np.add.at(vm, idx, routes['VMSB'].to_numpy(float))
    gap = np.abs(D['VFOB'] - vf) - np.maximum((tol + 2.4e-7) * np.abs(vf), ABS)
    bad = [f'{comm[c]} {regs[s]}->{regs[d]}: VFOB {D["VFOB"][c, s, d]:.6g} vs rebuilt {vf[c, s, d]:.6g}' for c, s, d in np.argwhere(gap > 0)]
    want = np.where(vc > 0, vm / np.where(vc > 0, vc, 1.0), 1.0)
    have = D['VCIF'] >= min_cif
    got = np.where(have, D['VMSB'] / np.where(have, D['VCIF'], 1.0), 1.0)
    bad += [f'{comm[c]} {regs[s]}->{regs[d]}: power {got[c, s, d]:.7f} vs {want[c, s, d]:.7f}'
            for c, s, d in np.argwhere(have & (np.abs(got - want) > tol + 2.4e-7 * want))]
    return len(bad), _detail(bad), int(have.sum())


# ------------------------------------------------------------------ energy
SEED15_REFINED = 'pet'      # S15 P10 household crude seed: the refined output it funds the seed from (s15_har.method.seed_household_crude)
S14_OUTPUT_ITEM = re.compile(r'^(?:A13 output (\w+)|B14 output and (?:factor payments|output tax) of (\w+) )')


def energy_output(D, sets, ev11, tol=TOL, ledger14=None, rebal=None, seed15=None):
    """Output (MAKB summed over activities, basic prices) equals the target value wherever one was set (ev11: rows
    region, commodity, output_value, target; beta v4: S13's energy_targets_s13.csv) (S13-Henergy, re-run on the finished data base), after the S14 moves of that output
    in the S14 ledger (ledger14: B14 sales abroad below USD 1, A13 seeded output and the cost structure carved
    from the supplying columns, items 'B14 output ... of c' and 'A13 output c') and the re-balancing rounding
    (rebal: rebalance_s14 rows of kind output), and after the S15 P10 household crude seed (seed15: household_crude_seed_s15.csv;
    each seeded row lowers its region's refined output at basic prices by refined_basic_cut, cell by cell)."""
    regs, comm = sets['REG'], sets['COMM']
    out = pd.DataFrame(D['MAKB'].sum(axis=1), index=comm, columns=regs)
    d = {}
    if ledger14 is not None and len(ledger14):
        for x in ledger14.itertuples():
            m = S14_OUTPUT_ITEM.match(str(x.item))
            if m:
                k = (x.region, m.group(1) or m.group(2))
                d[k] = d.get(k, 0.0) + float(x.after) - float(x.before)
    if rebal is not None and len(rebal):
        for x in rebal[rebal['kind'] == 'output'].itertuples():
            k = tuple(x.key.split())
            d[k] = d.get(k, 0.0) + float(x.after - x.before)
    if seed15 is not None and len(seed15):
        for x in seed15[seed15['status'] == 'seeded'].itertuples():
            k = (x.region, SEED15_REFINED)
            d[k] = d.get(k, 0.0) - float(x.refined_basic_cut)
    bad, n = [], 0
    for r in ev11[ev11['target'] == 'yes'].itertuples():
        a, b = out.loc[r.commodity, r.region], r.output_value + d.get((r.region, r.commodity), 0.0)
        if abs(a - b) > max(tol * abs(b), ABS):
            n += 1
            bad.append(f'{r.commodity} {r.region}: {a:.6g} vs target {r.output_value:.6g} + S14 moves {d.get((r.region, r.commodity), 0.0):.3g}')
    return n, _detail(bad)


EI_ALIASES = {'US': 'USA', 'Russian Federation': 'RUS', 'Iran': 'IRN', 'Saudi Arabia': 'SAU', 'China': 'CHN', 'Canada': 'CAN',
              'Iraq': 'IRQ', 'United Arab Emirates': 'ARE', 'Brazil': 'BRA', 'Kuwait': 'KWT', 'Norway': 'NOR', 'Mexico': 'MEX',
              'Kazakhstan': 'KAZ', 'Qatar': 'QAT', 'Nigeria': 'NGA', 'Algeria': 'DZA', 'Libya': 'LBY', 'Angola': 'AGO', 'Oman': 'OMN',
              'Australia': 'AUS', 'India': 'IND', 'Indonesia': 'IDN', 'Turkmenistan': 'TKM', 'Egypt': 'EGY', 'Malaysia': 'MYS',
              'Argentina': 'ARG', 'Colombia': 'COL', 'Venezuela': 'VEN', 'United Kingdom': 'GBR', 'Azerbaijan': 'AZE', 'Uzbekistan': 'UZB',
              'Netherlands': 'NLD', 'Germany': 'DEU', 'Poland': 'POL', 'South Africa': 'ZAF', 'Turkey': 'TUR', 'Türkiye': 'TUR',
              'Vietnam': 'VNM', 'Viet Nam': 'VNM', 'Mongolia': 'MNG', 'Thailand': 'THA', 'Pakistan': 'PAK', 'Ukraine': 'UKR',
              'Czech Republic': 'CZE', 'Czechia': 'CZE', 'Serbia': 'SRB', 'Greece': 'GRC', 'Bulgaria': 'BGR', 'Romania': 'ROU',
              'Bangladesh': 'BGD', 'Trinidad & Tobago': 'TTO', 'Bahrain': 'BHR', 'Brunei': 'BRN', 'Ecuador': 'ECU', 'Peru': 'PER',
              'Bolivia': 'BOL', 'Myanmar': 'MMR', 'Thailand ': 'THA', 'Japan': 'JPN', 'South Korea': 'KOR', 'Italy': 'ITA',
              'Gabon': 'GAB', 'Congo': 'COG', 'Equatorial Guinea': 'GNQ', 'Chad': 'TCD', 'Sudan': 'SDN', 'South Sudan': 'SSD',
              'Syria': 'SYR', 'Yemen': 'YEM', 'Tunisia': 'TUN', 'Denmark': 'DNK', 'Italy ': 'ITA', 'Philippines': 'PHL'}


def ei_production(path, sheet, year=2022):
    """Country production from an EI Statistical Review sheet (the year column), with ISO codes for the names in
    EI_ALIASES. Returns a Series by ISO code."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows = list(wb[sheet].iter_rows(values_only=True))
    hdr = next(r for r in rows if r and isinstance(r[1], (int, float)) and r[1] > 1900)
    col = list(hdr).index(year)
    out = {}
    for r in rows:
        if r and isinstance(r[0], str) and r[0].strip() in EI_ALIASES and isinstance(r[col], (int, float)):
            out[EI_ALIASES[r[0].strip()]] = float(r[col])
    return pd.Series(out)


def ei_compare(vol11, ei, members, top=15, band=0.08):
    """Production volumes of the top producers against EI (PLAN §3(k) energy row, report-only; E6 named
    exceptions). vol11: S11 volumes (region, commodity, production); ei: {commodity: (Series by ISO, factor to
    the S11 unit, concept note)}; members: {region: [ISO members]}. Returns a table."""
    rows = []
    for com, (s, f, concept) in ei.items():
        v = vol11[vol11['commodity'] == com].set_index('region')['production']
        reg_ei = {r: sum(s.get(m, 0.0) for m in ms) * f for r, ms in members.items()}
        topr = v.sort_values(ascending=False).index[:top]
        for r in topr:
            e = reg_ei.get(r, 0.0)
            rows.append(dict(commodity=com, region=r, s11=v[r], ei=e, ratio=(v[r] / e) if e else np.nan,
                             outside_band=bool(e) and abs(v[r] / e - 1) > band, concept=concept))
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ region list, ledger, concepts
def region_list(regs, s01_regions, n=167):
    bad = []
    if len(regs) != n:
        bad.append(f'{len(regs)} regions, not {n}')
    s01 = list(s01_regions)
    if sorted(r.upper() for r in regs) != sorted(s01):
        bad.append(f'REG differs from the S01 list: extra {sorted(set(r.upper() for r in regs) - set(s01))[:5]}, '
                   f'missing {sorted(set(s01) - set(r.upper() for r in regs))[:5]}')
    return len(bad), _detail(bad)


PLUG = re.compile(r'unmatched|residual (plug|sink|to )|\bplug\b|slack', re.I)
NOT_PLUG = re.compile(r'\bnot an? [\w\s]*plug|no plug|without a plug', re.I)


def ledger(frames, rules):
    """Every ledger row of every stage has a rule (method ID) and a citation (source and page); every rule is on
    the allow-list `rules` (stage, rule, kind: method or absorbed; config/s16/ledger_rules.csv), so a new kind of
    adjustment cannot enter unreviewed; and no row books an unmatched residual, a plug or a slack. Rows of kind
    absorbed (a gap the FIT absorbs under a named GTAP step) are summed for the report.
    frames: {stage: DataFrame}. Returns (failures, detail, table)."""
    allowed = {(r.stage, r.rule): r.kind for r in rules.itertuples()}
    rows, bad = [], []
    for st, d in frames.items():
        if d.empty:
            rows.append(dict(stage=st, rows=0, no_rule=0, no_citation=0, plug_rows=0, unlisted_rules=0, absorbed_rows=0, absorbed_musd=0.0))
            continue
        nr = int((d['rule'].astype(str).str.strip() == '').sum())
        nc = int((d['citation'].astype(str).str.strip() == '').sum())
        txt = d['rule'].astype(str) + ' ' + d['flag'].astype(str)
        plug = txt.str.contains(PLUG) & ~txt.str.contains(NOT_PLUG)
        npl = int(plug.sum())
        kind = d['rule'].map(lambda r: allowed.get((st, r), ''))
        unl = sorted(set(d.loc[kind == '', 'rule']))
        ab = d[kind == 'absorbed']
        mv = (pd.to_numeric(ab['after'], errors='coerce').fillna(0) - pd.to_numeric(ab['before'], errors='coerce').fillna(0)).abs()
        rows.append(dict(stage=st, rows=len(d), no_rule=nr, no_citation=nc, plug_rows=npl, unlisted_rules=len(unl),
                         absorbed_rows=len(ab), absorbed_musd=round(float(mv.sum()), 3)))
        if nr or nc or npl or unl:
            bad.append(f'{st}: {nr} rows without a rule, {nc} without a citation, {npl} plug rows, rules not on the list: {unl[:5]}'
                       + (f' (e.g. {txt[plug].iloc[0][:80]})' if npl else ''))
    return len(bad), _detail(bad), pd.DataFrame(rows)


def rounding_moves(moves, cap=1e-3):
    """S14's re-balance moves (rebalance_s14: kind, key, before, after, change) are rounding only: every move at
    most `cap` USD million, so S14's empty ledger is right. Returns (failures, detail, n, largest)."""
    ch = pd.to_numeric(moves['change'], errors='coerce').abs()
    big = moves[ch > cap]
    return len(big), _detail([f'{r.kind} {r.key}: {r.change}' for r in big.head(20).itertuples()]), len(moves), float(ch.max() if len(ch) else 0.0)


CONCEPT = re.compile(r'\bC(0[1-9]|[12][0-9]|30)\b|\bidentity\b|\bsign\b|\bmodel\b|\bstage\b|\brepo\b')


def concept_tags(checks):
    """Every S16 check names its concept: a like-with-like concept ID C01-C30 for a comparison of two sources,
    or one of identity / sign / model / stage / repo; and a comparison that names a price basis names it on both
    sides ('basis A vs B' or 'basis same'). A comparison whose two sides have different bases is report-only.
    Returns (failures, detail)."""
    bad = []
    for c in checks:
        tag = c['concept']
        if not CONCEPT.search(tag):
            bad.append(f'{c["id"]}: no concept tag ({tag[:40]})')
            continue
        m = re.search(r'basis ([^;]+)', tag)
        if m and ' vs ' in m.group(1):
            a, b = [x.strip() for x in m.group(1).split(' vs ', 1)]
            if a != b and c['kind'] == 'hard':
                bad.append(f'{c["id"]}: hard check on a mixed basis ({a} vs {b})')
    return len(bad), _detail(bad)


# ------------------------------------------------------------------ maps
def map_results(lines, maps):
    """Parse the Julia result lines (map.key=value) into one row per map. A map with no status did not run."""
    res = {}
    for l in lines:
        k, _, v = l.partition('=')
        m, _, key = k.partition('.')
        res.setdefault(m, {})[key] = v
    rows = []
    for m in maps:
        r = res.get(m, {})
        rows.append(dict(map=m, status=r.get('status', 'NOT RUN'), **{k: v for k, v in r.items() if k != 'status'}))
    return pd.DataFrame(rows)
