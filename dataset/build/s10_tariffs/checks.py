"""S10 hard checks as pure functions. Each returns (value, passed, detail).

The stage calls these on the objects it built; tests/test_s10_checks.py calls each one on a
good input and on a mutated input, and the mutated input must fail. A check that cannot
fail on its mutation is not a check.
"""
from .preferences import family_rates_independent


def _out(bad, detail_ok='', limit=12):
    bad = list(bad)
    return len(bad), not bad, ('; '.join(str(b) for b in bad[:limit]) if bad else detail_ok)


def join(report, allowed_members, allowed_numeric=('234', '732')):
    """S10-Hjoin: every BACI code with trade, every schedule reporter and every applied member
    list ISO reaches a region. Allowed members are historic codes with no 2022 trade."""
    bad = [f'baci {num} {label} {value:.0f}' for num, label, _iso, value in report['baci']]
    bad += [f'reporter {iso}' for iso in report['reporters']]
    bad += [f'member {iso}' for iso in report['members'] if iso not in allowed_members]
    bad += [f'numeric {code}' for code in report['numeric'] if code not in allowed_numeric]
    return _out(bad, 'every code reaches a region')


def groups(problems):
    """S10-Hgroups: preference_group_members.csv equals the WITS beneficiary table row by row."""
    return _out(problems, 'all groups match WITS')


def unknown_groups(log):
    """S10-Hgroupmap: no preference row is dropped because its group code has no member list."""
    return _out(f'{i} {c} {y}' for i, c, y in log.get('unknown_group', []))


def above_mfn(lines):
    """S10-Habovemfn: no priced HS line above its MFN."""
    return _out(f'{i}<-{e} {hs} {r:.3f}>{m:.3f}' for i, e, hs, r, m in lines)


def best_applied(sample, tariffs):
    """S10-Hbest: on a sample of priced lines, the applied rate is at or below MFN and at or
    below the latest line of every usable agreement family, by a walk that does not call
    pref_rate. A forced customs-union zero must be 0."""
    bad = []
    for imp, exp, hs, rate, mfn, how in sample:
        if how == 'cu_forced':
            if rate != 0.0:
                bad.append(f'{imp}<-{exp} {hs} forced {rate}')
            continue
        if imp in ('TKM', 'TUN', 'IRQ', 'PRK') or rate is None:
            continue
        if mfn is not None and rate > mfn + 1e-9:
            bad.append(f'{imp}<-{exp} {hs} {rate}>{mfn} mfn')
        fam = family_rates_independent(tariffs.state, imp, exp, hs, tariffs.sched_code)
        if fam and mfn is not None and rate > min(fam.values()) + 1e-9:
            bad.append(f'{imp}<-{exp} {hs} {rate}>{min(fam.values())} family')
    return _out(bad, f'{len(sample)} sampled lines')


def family_spots(state, spots):
    """S10-Hfamily-cover: named pairs keep an agreement from each family in the cover."""
    bad = []
    for imp, exp, need in spots:
        have = {a['partner'] for a in state['cover'].get(imp, {}).get(exp, ())}
        miss = [c for c in need if c not in have]
        if miss:
            bad.append(f'{imp}<-{exp} lacks {" ".join(miss)}')
    return _out(bad, 'every spot pair keeps both families')


def khm_partner(state):
    """S10-Hkhm: Cambodia's 2020-2021 partner 356 applies to China only (khm_acfta_partner)."""
    cover = state['cover'].get('KHM', {})
    chn = any(a['partner'] == '356' for a in cover.get('CHN', ()))
    ind = any(a['partner'] == '356' for a in cover.get('IND', ()))
    bad = ([] if chn else ['CHN lacks 356']) + (['IND still has 356'] if ind else [])
    return _out(bad, '356 is China')


def us_gsp(reached):
    """S10-Husgsp: no lapsed US GSP row is still applied."""
    return reached, reached == 0, 'B11 C06 C53 C69 01R B15 and named USA GSP groups emptied'


def uk_continuity(state, uk_applied, uk_removed):
    """S10-Hukcont: GBR is on an EU list only for an importer with a continuity agreement in force."""
    bad = []
    for imp, agrs in state['agreements'].items():
        for a in agrs:
            if a['partner'] in uk_removed and 'GBR' in a['members'] and imp not in uk_applied:
                bad.append(f'{imp} {a["partner"]}')
    if 'DZA' in uk_applied:
        bad.append('DZA applied')
    return _out(sorted(set(bad)), 'GBR restored only for ' + ' '.join(sorted(uk_applied)))


def schedule_values(schedules, nomen, expected):
    """S10-Hoverride: each named override is on the schedule at its decided value.
    expected: [(iso, hs22, value, how)]."""
    bad = []
    for iso, hs, value, how in expected:
        sch = schedules.get(iso)
        code = nomen.code(sch.nomen, hs) if sch else None
        got = sch.rate.get(code) if sch and code else None
        if got is None or abs(got - value) > 1e-9 or sch.how.get(code) != how:
            bad.append(f'{iso} {hs} {got} want {value} {how}')
    return _out(bad, f'{len(expected)} override lines')


def iraq(over):
    """S10-Hiraq: no Iraq line above its Resolution 393 chapter band."""
    return over, over == 0, 'food chapters at band x 5.5/12'


def weight_years(stats, years=(2021, 2022, 2023), max_dropped=0.001):
    """S10-Hweightyears: every weight year was read, the value yielded plus the value dropped is
    the value read, and the HS17 value with no HS22 code is under max_dropped of its year."""
    bad = []
    for y in years:
        st = stats.get(y)
        if not st or st[0] <= 0:
            bad.append(f'{y} not read')
            continue
        read, used, dropped, _equal = st
        if abs(used + dropped - read) > 1e-6 * read:
            bad.append(f'{y} used {used:.0f} + dropped {dropped:.0f} != read {read:.0f}')
        if dropped > max_dropped * read:
            bad.append(f'{y} dropped {dropped / read:.4%}')
    bad += [f'{y} is not a weight year' for y in sorted(set(stats) - set(years))]
    detail = '; '.join(f'{y} {stats[y][0] / 1e9:.3f} tn' for y in sorted(stats) if stats[y][0] > 0)
    return _out(bad, detail)


def weight_conversion(sectors, max_misallocation=0.02, big_share=0.01, max_sector_gap=0.10):
    """S10-Hweightconv: BACI HS17 2022 converted to HS22 with the 2021 table and split lands on the GTAP
    sectors as BACI HS22 2022 does. Half the sum of absolute sector gaps is under max_misallocation of
    world trade, and no sector with at least big_share of world trade is off by more than max_sector_gap.
    sectors: {sector: (converted HS17 value, HS22 value)}."""
    world = sum(d for _c, d in sectors.values())
    if world <= 0:
        return _out(['no HS22 2022 value'], '')
    mis = sum(abs(c - d) for c, d in sectors.values()) / 2
    bad = [f'misallocation {mis / world:.2%} of world'] if mis > max_misallocation * world else []
    for k, (c, d) in sorted(sectors.items(), key=lambda kv: str(kv[0])):
        if d >= big_share * world and abs(c - d) > max_sector_gap * d:
            bad.append(f'{k} {c / d - 1:+.1%}')
    top = sorted(((k, c / d - 1) for k, (c, d) in sectors.items() if d >= big_share * world),
                 key=lambda kv: -abs(kv[1]))[:3]
    return _out(bad, f'misallocation {mis / world:.2%}; largest ' + ', '.join(f'{k} {g:+.1%}' for k, g in top))


def parent_territory(lines, territories):
    """S10-Hparent: a parent-territory line carries the parent schedule's line as its MFN, the applied
    rate is not above it, an uncovered line has no rate, and every territory has a priced line."""
    bad, priced = [], set()
    for imp, hs, mfn, parent, rate in lines:
        if parent is None:
            if mfn is not None:
                bad.append(f'{imp} {hs} outside the union has MFN {mfn}')
            continue
        if mfn is None or abs(mfn - parent) > 1e-9:
            bad.append(f'{imp} {hs} MFN {mfn} != parent {parent}')
        elif rate is not None and rate > mfn + 1e-9:
            bad.append(f'{imp} {hs} applied {rate} > {mfn}')
        else:
            priced.add(imp)
    bad += [f'{t} has no priced line' for t in sorted(set(territories) - priced)]
    return _out(bad, f'{len(lines)} lines; territories {" ".join(sorted(priced))}')


def panama(sample_pan, tpa):
    """S10-Hpanama: PAN<-USA lines with a TPA rate are at or below min(TPA, MFN)."""
    bad, n = [], 0
    for hs, rate, mfn in sample_pan:
        t = tpa.get(hs)
        if t is None or mfn is None:
            continue
        n += 1
        if rate > min(t, mfn) + 1e-9:
            bad.append(f'{hs} {rate} > {min(t, mfn)}')
    if n == 0:
        bad.append('no PAN<-USA TPA line was priced')
    return _out(bad, f'{n} lines')


def ave_1000(lines, known):
    """S10-Have1000: an AVE-sourced line at or above 1,000 percent with trade is in ave_outlier_lines.csv."""
    return _out(f'{i} {c} {v:.1f}' for i, c, v, t in lines if (i, c) not in known)


def customs_union(cells, cu_cells):
    """S10-Hcu: a cell between two regions that hold only EU customs-territory members carries no duty."""
    bad = [f'{k} {cells[k]}' for k in sorted(cu_cells) if abs(cells.get(k, 0.0)) > 1e-12]
    return _out(bad, f'{len(cu_cells)} union cells')


def no_addon_in_tm(tm_rates, base_rates):
    """S10-Hno301: tm is the baseline rate; nothing from the 301/232 layer is added."""
    return _out(f'{k} {tm_rates[k]} vs {base_rates.get(k)}' for k in tm_rates
                if abs(tm_rates[k] - base_rates.get(k, 0.0)) > 1e-12)


def weights(den_total, priced_value):
    """S10-Hweight: the BACI weight in the sector cells equals the priced BACI value."""
    gap = den_total - priced_value
    return f'{gap:.6f}', abs(gap) <= 1e-6 * max(1.0, priced_value), f'cells {den_total:.3f}; priced lines {priced_value:.3f}'


def every_cell_rated(cells_rule, with_schedule):
    """S10-Hcoverage: no importer with a schedule is missing on every goods cell."""
    by = {}
    for (imp, _exp, _s), rule in cells_rule.items():
        slot = by.setdefault(imp, [0, 0])
        slot[0] += 1
        slot[1] += rule == 'missing'
    return _out(sorted(i for i, (n, m) in by.items() if n and m == n and i in with_schedule), 'none')


def read_back_cells(out_dir):
    """S10-Hwedge: the written tm, vmsb and duty files read back. {key: [tm, rate_pct, vcif, vmsb, duty]}."""
    import csv
    import gzip
    cells = {}
    with gzip.open(out_dir + '/tm_s10.csv.gz', 'rt', newline='') as fh:
        for r in csv.DictReader(fh):
            cells[(r['importer'], r['exporter'], r['sector'])] = [float(r['tm']), float(r['rate_pct']), None, None, None]
    for name, cols in (('vmsb_s10.csv.gz', (('vcif_musd', 2), ('vmsb_musd', 3))), ('duty_bilateral_s10.csv.gz', (('duty_musd', 4),))):
        with gzip.open(out_dir + '/' + name, 'rt', newline='') as fh:
            for r in csv.DictReader(fh):
                cell = cells.setdefault((r['importer'], r['exporter'], r['sector']), [None] * 5)
                for col, i in cols:
                    cell[i] = float(r[col])
    return cells


def vcif_independent(vxsb_path, vtwr_path, goods):
    """S10-Hwedge: VCIF re-read from the S07 vfob and S08 vtwr files, apart from the stage reader."""
    import csv
    import gzip
    out = {}
    for path, col in ((vxsb_path, 'vfob_musd'), (vtwr_path, 'vtwr_musd')):
        with gzip.open(path, 'rt', newline='') as fh:
            for r in csv.DictReader(fh):
                if r['sector'] in goods:
                    k = (r['importer'], r['exporter'], r['sector'])
                    out[k] = out.get(k, 0.0) + float(r[col] or 0.0)
    return out


def wedge_files(written, vcif, bilateral):
    """S10-Hwedge (fix list B9): the written files against values the build did not write.

    Source comparisons: every cell with VCIF is written, and nothing else; the written VCIF equals
    S07 vfob + S08 vtwr re-read from the input files; on a cell with a BACI weight the written rate
    equals the BACI line accumulator (sum of line rate x weight over the weight). Identity part,
    labelled as such: duty = VCIF x tm and VMSB = VCIF x (1 + tm) >= VCIF on the written rows.
    written: read_back_cells(); vcif: vcif_independent(); bilateral: {key: rate_pct}."""
    src, ident = [], []
    live = {k for k, v in vcif.items() if v != 0.0}
    src += [f'{k} VCIF {vcif[k]:.6f} not written' for k in sorted(live - set(written))]
    src += [f'{k} written without VCIF' for k in sorted(set(written) - live)]
    for k in sorted(set(written) & live):
        tm, pct, base, vmsb, duty = written[k]
        if None in (tm, pct, base, vmsb, duty):
            src.append(f'{k} missing from a written file')
            continue
        if abs(base - vcif[k]) > 1e-6 * max(1.0, abs(vcif[k])):
            src.append(f'{k} written VCIF {base:.6f} against S07+S08 {vcif[k]:.6f}')
        if k in bilateral and abs(pct - bilateral[k]) > 1e-7 * max(1.0, abs(bilateral[k])):
            src.append(f'{k} written rate {pct:.6f} against the BACI accumulator {bilateral[k]:.6f}')
        if abs(duty - base * tm) > 1e-6 * max(1.0, abs(base)) or abs(vmsb - base * (1.0 + tm)) > 1e-6 * max(1.0, abs(base)) \
                or vmsb + 1e-8 < base:
            ident.append(f'{k} identity: duty {duty} VCIF {base} tm {tm} VMSB {vmsb}')
    bad = src + ident
    n_bil = len(set(bilateral) & set(written))
    return len(bad), not bad, ('; '.join(bad[:12]) if bad else
                               f'{len(written)} cells; source: VCIF re-read from S07+S08, {n_bil} bilateral rates against '
                               f'the BACI accumulator; identity: duty = VCIF x tm, VMSB >= VCIF')


def identical(a_lines, b_lines):
    """S10-Hbasic: the non-TLS IO lines are byte-identical."""
    if len(a_lines) != len(b_lines):
        return abs(len(a_lines) - len(b_lines)), False, 'line count differs'
    n = sum(x != y for x, y in zip(a_lines, b_lines))
    return n, n == 0, f'{len(a_lines)} lines compared'


def pse_total(problems):
    """S10-Hpse: booked support equals MONEVA A2-E per region."""
    return _out(problems, 'A2-E booked in full')


def preview(got, expect, tol):
    """S10-Husa-pse and S10-Husa-grs: registered values reproduce."""
    return _out(f'{k} {got.get(k)} want {v}' for k, v in expect.items()
                if got.get(k) is None or abs(got[k] - v) > tol)


def xs_rate(rows):
    """S10-Hxsrate: booked export-subsidy rate at most 1 on own-product exports."""
    return _out(f'{r[0]} {r[10]} {r[6]}' for r in rows if r[7] == 'yes' and r[6] != '' and float(r[6]) > 1.0 + 1e-9)


def vxsb(wedge_value, booked, tax_wedge=0.0, tax_booked=0.0):
    """S10-Hvxsb: derived VXSB minus VFOB equals the booked subsidy outlay minus the booked export tax."""
    gap = (wedge_value - tax_wedge) - (booked - tax_booked)
    return f'{gap:.6f}', abs(gap) <= 1e-3, (f'subsidy wedge {wedge_value:.6f}; booked {booked:.6f}; '
                                           f'tax wedge {tax_wedge:.6f}; booked {tax_booked:.6f}')


def export_tax(rows, totals, products, rates_tab=None, rates_source='statutory 2022 rates (export_tax_rates_2022.csv)'):
    """S10-Hxtax: each sector rate is in [0, 1) of VFOB and no exporter is booked twice. An exporter booked from a
    GRS total adds up to its GRS T_5124 2022 total and has a cited product list; an exporter booked from the rates
    table (total_source = rates_source) is in that table and each of its cells has duty = rate x VFOB.
    rows: export_tax_s10.csv rows; rates_tab: export_tax.load_rates() (None: no rates path)."""
    rates_tab = rates_tab or {}
    bad, by_iso, path = [], {}, {}
    for r in rows:
        iso, duty, base, rate = r[0], float(r[3]), float(r[4]), float(r[5])
        kind = 'rates' if r[7] == rates_source else 'grs'
        if path.setdefault(iso, kind) != kind:
            bad.append(f'{iso} booked by both the GRS and the rates path')
        if not 0.0 <= rate < 1.0:
            bad.append(f'{iso} {r[1]} rate {rate}')
        if kind == 'rates':
            if iso not in rates_tab:
                bad.append(f'{iso} booked from rates with no row in export_tax_rates_2022.csv')
            if abs(duty - rate * base) > 1e-6 * max(1.0, duty):
                bad.append(f'{iso} {r[1]} duty {duty:.6f} is not rate x VFOB {rate * base:.6f}')
            continue
        by_iso[iso] = by_iso.get(iso, 0.0) + duty
        if iso not in products:
            bad.append(f'{iso} booked with no product list')
    for iso, d in sorted(by_iso.items()):
        t = totals.get(iso)
        if t is None or abs(d - t) > 1e-6 * max(1.0, t):
            bad.append(f'{iso} duty {d:.6f} against GRS {t}')
    n_rates = sorted(i for i, k in path.items() if k == 'rates')
    return _out(bad, f'{len(by_iso)} exporters on GRS totals, {sum(by_iso.values()):.3f} USD million; '
                     f'{len(n_rates)} on statutory rates ({", ".join(n_rates)})')


def energy_tax(rows, rev_by_iso, region_iso, regions, tol=1e-6):
    """S10-Henergy (fix list A1, GTAP 12 ch.12 §12.3.3 and §12.3.10): energy_tax_s10.csv holds, for every source
    region, each non-zero NEERS (or EIA) class revenue exactly once, with its tax base, and a TJ base gives
    specific_usd_per_gj = (tax + subsidy) / base and neer_subsidy_usd_per_gj = subsidy / base; every other region has
    one fill row whose proxies are source regions with positive weights; every value is finite.
    rows: energy_tax_s10.csv rows (energy_tax.FILE_COLUMNS)."""
    bad, seen, kinds = [], set(), {}

    def num(x):
        v = float(x)
        if v != v or abs(v) == float('inf'):
            raise ValueError(x)
        return v
    for r in rows:
        region, cls, com = r[0], r[1], r[2]
        try:
            tax, sub, base = num(r[4]), num(r[5]), num(r[6])
            sp = num(r[8]) if r[8] != '' else None
            ss = num(r[9]) if r[9] != '' else None
        except ValueError as e:
            bad.append(f'{region} {cls} {com}: value {e}')
            continue
        kind = 'fill' if cls == '*' else 'source'
        if kinds.setdefault(region, kind) != kind:
            bad.append(f'{region}: both source and fill rows')
        if (region, cls, com) in seen:
            bad.append(f'{region} {cls} {com}: repeated')
        seen.add((region, cls, com))
        if kind == 'fill':
            for p in (q for q in r[13].split(';') if q):
                m, _, w = p.partition(':')
                if kinds.get(m, 'source' if region_iso.get(m) in rev_by_iso else None) != 'source' or not float(w or 0) > 0:
                    bad.append(f'{region}: proxy {p} is not a source region with a positive weight')
            continue
        want = rev_by_iso.get(region_iso.get(region), {}).get((cls, com))
        if want is None or abs(tax - want[0]) > tol * max(1.0, abs(want[0])) or abs(sub - want[1]) > tol * max(1.0, abs(want[1])):
            bad.append(f'{region} {cls} {com}: tax {tax} subsidy {sub} against the source {want}')
            continue
        if r[7] != want[3] or abs(base - want[2]) > tol * max(1.0, abs(want[2])):
            bad.append(f'{region} {cls} {com}: base {base} {r[7]} against {want[2]} {want[3]}')
        if r[7] == 'TJ':
            if not base > 0 or sp is None or abs(sp - (tax + sub) * 1000.0 / base) > tol * max(1.0, abs(sp)) \
                    or ss is None or abs(ss - sub * 1000.0 / base) > tol * max(1.0, abs(ss)):
                bad.append(f'{region} {cls} {com}: specific {sp}/{ss} is not (tax + subsidy) / base on {base} TJ')
        elif sp is not None:
            bad.append(f'{region} {cls} {com}: a specific rate on a {r[7]} base (S13 converts it)')
    for region in regions:
        if region not in kinds:
            bad.append(f'{region}: no row')
        elif kinds[region] == 'source':
            have = {(c, k) for (g, c, k) in seen if g == region}
            miss = [k for k, v in rev_by_iso.get(region_iso.get(region), {}).items() if (v[0] or v[1]) and k not in have]
            if miss:
                bad.append(f'{region}: source revenue not written {miss[:3]}')
    n_src = sum(1 for v in kinds.values() if v == 'source')
    return _out(bad, f'{n_src} source regions, {len(kinds) - n_src} fill rows')


def listed(items, have, what):
    """S10-Hbasis and S10-Hprivate: every output file is listed."""
    return _out((i for i in items if i not in have), f'every file has {what}')


def bind(facts):
    """S10-G0bind: the S09 snapshot this stage is bound to. facts: {name: (got, want)}."""
    return _out([f'{k} {g} want {w}' for k, (g, w) in sorted(facts.items()) if g != w], 'bound')


def forbidden_inputs(inputs, choice_text, banned=('old_plus_mfn' + '_change',), paths=('/v3.8', '/v3.9/')):
    """S10-Hnov38: no input under trains_internal/v3.8 or v3.9 and no old-rate-plus-MFN-change token."""
    bad = [p for p in inputs if any(x in p for x in paths)]
    bad += [f'token {b}' for b in banned if b in choice_text]
    return _out(bad, 'clean')


def vfob_pretax(n_bad):
    """S10-Hvfob: S07R goods VFOB equals VXSB and is pre-tax."""
    return n_bad, n_bad == 0, 'VCIF = vfob_musd + S08 vtwr_musd'


def sources_present(stats):
    """S10-Hsources: Tunisia, Libya, Venezuela and the Turkmenistan exception are in the run.
    stats: {'TUN': lines, 'TUN_raised': n, 'LBY': lines, 'VEN': lines, 'TKM_scheduled': bool}."""
    bad = [k for k in ('TUN', 'LBY', 'VEN') if stats.get(k, 0) <= 0]
    if stats.get('TUN', 0) <= 1000:
        bad.append('TUN lines <= 1000')
    if stats.get('TUN_raised', 0) <= 0:
        bad.append('TUN none raised by the 2018 finance law')
    if stats.get('TKM_scheduled'):
        bad.append('TKM has a schedule; the named exception expects none')
    return _out(bad, ' '.join(f'{k} {v}' for k, v in sorted(stats.items())))


def spots(cells, mfn, pairs, sectors, gap=0.05):
    """S10-Hspot: the new goods sectors show a preference on named pairs: at least one sector cell
    of each pair sits below its MFN by more than gap points."""
    bad = []
    for imp, exp in pairs:
        if not any(mfn.get((imp, exp, s)) is not None and (imp, exp, s) in cells
                   and cells[(imp, exp, s)] < mfn[(imp, exp, s)] - gap for s in sectors):
            bad.append(f'{imp}<-{exp}')
    return _out(bad, ' '.join(f'{i}<-{e}' for i, e in pairs))


def pref_exceptions(rows, pref_importers):
    """S10-Hpref: an importer on the exception list has no preference cell; every exception row has a
    cause and a source; some importers do have preference cells."""
    listed = {r['importer'] for r in rows if (r.get('in_hpref_list') or 'yes') != 'no'}
    bad = [f'{r["importer"]} row incomplete' for r in rows if not r.get('cause') or not r.get('source_checked')
           or ((r.get('in_hpref_list') or 'yes') != 'no' and (r.get('trains_preference_data') or '') != 'no')]
    bad += [f'{i} has preference cells' for i in sorted(listed & set(pref_importers))]
    if not pref_importers:
        bad.append('no importer has a preference cell')
    return _out(bad, f'{len(listed)} exceptions; {len(pref_importers)} importers with preference cells')


def tax_source(bad_pairs):
    """S10-Htaxsource: no average fill where GRS or WoRLD has a value."""
    return _out(bad_pairs, 'none')


def negatives(new_neg_tls, rows, cited):
    """S10-Hnegtax: no new negative TLS cell and no negative booked item without a cited ledger row.
    rows: [(region, ledger item, value)]; cited: {(region, item)}."""
    bad = [f'{new_neg_tls} new negative TLS cells'] if new_neg_tls else []
    bad += [f'{r} {item} {v}' for r, item, v in rows if v < -1e-6 and (r, item) not in cited]
    return _out(bad, 'none')


def usa_far(far_chapters):
    """S10-Huschapter: no USA chapter is far from Census ex-China without a named reason."""
    return _out(f'{c:02d}' for c in far_chapters)


def screens(result):
    """S10-Hscreens: the suite ran and no material hit is unexplained."""
    if result is None or 'error' in result:
        return 'error', False, (result or {}).get('error', 'screen run raised')
    n = result['material_unexplained']
    return n, n == 0, result['detail']


def neer_year(years, year_used, base_year):
    """S10-Hneeryear (year rule): the NEERS years energy_tax_year takes are the one oecd_neer year recorded in
    config/source_years.csv (year_used), and none is after the base year."""
    bad = [f'NEERS year {y} after the {base_year} base' for y in years if y > base_year]
    bad += [f'NEERS year {y} is not the source_years year used {year_used!r}' for y in years if str(y) != str(year_used)]
    return _out(bad, f'NEERS {",".join(map(str, years))} = source_years year used')


def product_tax(pattern, layers, control, regions, per_region, tol=1e-9):
    """S10-Hptpattern (product_tax_pattern; QA round 2 P1): every region has per_region pattern rows (agent x commodity)
    with a VAT weight in [0, 1]; the generic schedule puts 0 on the exempt and non-market services (financial services,
    real estate, education, health, postal, public administration, household employers) for households and government;
    the GRS layers are finite and non-negative; each region's Eurostat control shares are in [0, 1] and sum to 1."""
    bad, n = [], {}
    zero = ('fin', 'rle', 'edu', 'hea', 'pst', 'gov', 'hhe')
    for r in pattern:
        n[r[0]] = n.get(r[0], 0) + 1
        w = float(r[3])
        if not 0.0 <= w <= 1.0:
            bad.append(f'{r[0]} {r[1]} {r[2]}: VAT weight {w}')
        if r[4] == 'generic_exemptions' and r[1] in ('p', 'g') and r[2] in zero and w != 0.0:
            bad.append(f'{r[0]} {r[1]} {r[2]}: exempt service with weight {w}')
    bad += [f'{reg}: {n.get(reg, 0)} pattern rows, expected {per_region}' for reg in regions if n.get(reg, 0) != per_region]
    seen = set()
    for r in layers:
        seen.add(r[0])
        for k in (1, 3, 5):
            if r[k] != '' and not 0.0 <= float(r[k]) < float('inf'):
                bad.append(f'{r[0]}: layer value {r[k]}')
    bad += [f'{reg}: no layer row' for reg in regions if reg not in seen]
    tot = {}
    for r in control:
        s = float(r[4])
        if not 0.0 <= s <= 1.0:
            bad.append(f'{r[0]} {r[1]}: control share {s}')
        tot[r[0]] = tot.get(r[0], 0.0) + s
    bad += [f'{reg}: control shares sum to {t:.12g}' for reg, t in tot.items() if abs(t - 1.0) > tol]
    return _out(bad, f'{len(n)} regions, {len(tot)} with a Eurostat control')
