"""Beta v5 S16 report checks (package v2 items TC and RG; David 2026-10-27 08:39 UTC). Each function is pure on the
data base as read back (harpy arrays, dims as s15_har/method.DATA_HEADERS) and returns a table or (failures, detail),
so tests/test_betav5_fixes.py can show each one on a hand-made case. Every check here is report-only: it lists what a
reader should look at, it does not change a number. Thresholds are ours (labelled), not GTAP's.
"""
import os

import numpy as np
import pandas as pd

GOODS_LAST = 'ely'          # crp ... ely are goods in the BoP split (electricity trade is goods); wat onward are services
AMA_GROUPS = {               # UN AMA ISIC rev.3 groups (data/unsd_ama/gva_gdp_current_usd.csv) -> our sectors
    'gva_10_ag': ('crp', 'for', 'fsh'),
    'gva_13_f': ('con',),
    'gva_14_gh': ('trd', 'hos'),
    'gva_15_i': ('rdt', 'sea', 'air', 'whs', 'pst', 'tel'),
    'gva_16_jp': ('pub', 'its', 'fin', 'rle', 'pro', 'adm', 'gov', 'edu', 'hea', 'art', 'ots', 'hhe'),
}
AMA_CE = 'gva_11_ce'         # mining, manufacturing and utilities (C-E): every other sector
AMA_BAND, AMA_MIN_GDP = 2.0, 0.01            # ratio outside [1/2, 2] and a gap above 1% of GDP
ELY_PRICE_BAND = (40.0, 400.0)               # USD per MWh of ely output over generation (ely carries gas supply: wide band)
WEDGE_MIN, SUBSIDY_MAX = 0.25, 0.75          # coordinator 2026-10-27 (GHA/KAZ trace): purchaser/basic and subsidy/output
WEDGE_MIN_MUSD = 50.0                        # rows below USD 50 million of purchases are left out
METAL_GOODS = ('ore', 'nfm')
METAL_X_SHARE, METAL_M_SHARE, METAL_MIN_MUSD = 0.90, 0.50, 1000.0
DIFF_REL, DIFF_MUSD = 0.5, 1000.0            # version diff: a move above 50% and USD 1 bn
ROUTE_MIN_MUSD = 500.0
ENERGY_ROUTE_GOODS = ('coa', 'oil', 'gas', 'pet')


def _ix(names):
    return {c: i for i, c in enumerate(names)}


def goods_mask(comm):
    k = comm.index(GOODS_LAST)
    return np.array([i <= k for i in range(len(comm))])


def macro_bn(D, comm, regs, bop, regions):
    """S16-Rmacrobn (TC): exports, imports and the trade balance of the data base against WDI BoP 2022, in USD bn, goods
    and services apart (data/wdi_bop). bop: frame countrycode, BX/BM.GSR.MRCH.CD, BX/BM.GSR.NFSV.CD (USD); regions: the
    S01 regions (region, members). A composite region sums its members with data; a region with no member in WDI is NaN.
    Ours: goods X = VFOB of crp..ely, services X = VFOB of the rest + VST; M = VCIF likewise. Returns a frame by region."""
    g = goods_mask(comm)
    fob, cif = D['VFOB'], D['VCIF']
    xg = fob[g].sum(axis=(0, 2)); xs = fob[~g].sum(axis=(0, 2)) + D['VST'].sum(axis=0)
    mg = cif[g].sum(axis=(0, 1)); ms = cif[~g].sum(axis=(0, 1))
    b = bop.set_index('countrycode')
    cols = ('BX.GSR.MRCH.CD', 'BM.GSR.MRCH.CD', 'BX.GSR.NFSV.CD', 'BM.GSR.NFSV.CD')
    mem = {r.region: str(r.members).split() for r in regions.itertuples()}
    rows = []
    for k, r in enumerate(regs):
        m = [x for x in mem.get(r.upper(), [r.upper()]) if x in b.index]
        w = {c: (b.loc[m, c].sum(min_count=1) / 1e6 if m else np.nan) for c in cols}
        rows.append(dict(region=r, x_goods=xg[k], m_goods=mg[k], x_serv=xs[k], m_serv=ms[k],
                         wdi_x_goods=w[cols[0]], wdi_m_goods=w[cols[1]], wdi_x_serv=w[cols[2]], wdi_m_serv=w[cols[3]]))
    t = pd.DataFrame(rows).set_index('region')
    t['nx_goods_gap_bn'] = ((t['x_goods'] - t['m_goods']) - (t['wdi_x_goods'] - t['wdi_m_goods'])) / 1e3
    t['nx_serv_gap_bn'] = ((t['x_serv'] - t['m_serv']) - (t['wdi_x_serv'] - t['wdi_m_serv'])) / 1e3
    t['nx_gap_bn'] = t['nx_goods_gap_bn'] + t['nx_serv_gap_bn']
    return t


def sector_vs_ama(D, comm, regs, ama, regions, gdp, year=2022, band=AMA_BAND, min_gdp=AMA_MIN_GDP):
    """S16-Rsectorsize (TC): value added (EVFP, agents' prices) by UN AMA ISIC group against UN AMA 2022 GVA (current USD),
    by region (composites sum their members). Flagged: ratio outside [1/band, band] with a gap above min_gdp of GDP.
    gdp: {region: USD million}. Returns (frame region, group, ours, ama, ratio, gap_share, flag)."""
    va = D['EVFP'].sum(axis=0)          # acts x region
    ci = _ix(comm)
    a = ama[ama['year'] == year].set_index('iso3')
    mem = {r.region: str(r.members).split() for r in regions.itertuples()}
    listed = {c for v in AMA_GROUPS.values() for c in v}
    groups = dict(AMA_GROUPS, **{AMA_CE: tuple(c for c in comm if c not in listed)})
    rows = []
    for k, r in enumerate(regs):
        m = [x for x in mem.get(r.upper(), [r.upper()]) if x in a.index]
        if not m:
            continue
        for gname, secs in groups.items():
            ours = float(sum(va[ci[c], k] for c in secs if c in ci))
            ref = float(a.loc[m, gname].sum(min_count=1)) / 1e6 if gname in a.columns else np.nan
            if not np.isfinite(ref) or ref <= 0:
                continue
            ratio = ours / ref
            gap = abs(ours - ref) / max(gdp.get(r.upper(), np.nan), 1e-9)
            rows.append(dict(region=r, group=gname, ours_musd=ours, ama_musd=ref, ratio=ratio, gap_share_gdp=gap,
                             flag=bool((ratio > band or ratio < 1 / band) and gap > min_gdp)))
    return pd.DataFrame(rows, columns=['region', 'group', 'ours_musd', 'ama_musd', 'ratio', 'gap_share_gdp', 'flag'])


def power_price(D, comm, regs, vol, band=ELY_PRICE_BAND):
    """S16-Rpowerprice (TC): ely output at basic prices (MAKB) over S11 generation (volumes_s11 production, TWh) in USD per
    MWh, by region. Our ely includes gas distribution (ICIO D35), so the band is wide. Returns a frame with flag."""
    e = comm.index('ely')
    out = D['MAKB'][e].sum(axis=0)
    v = vol[(vol['commodity'] == 'ely')].set_index('region')['production']
    rows = []
    for k, r in enumerate(regs):
        twh = float(v.get(r.upper(), np.nan))
        p = out[k] / twh if twh > 0 else np.nan
        rows.append(dict(region=r, ely_output_musd=float(out[k]), generation_twh=twh, usd_per_mwh=p,
                         flag=bool(np.isfinite(p) and (p < band[0] or p > band[1]))))
    return pd.DataFrame(rows)


def energy_wedge(D, comm, regs, goods=('coa', 'oil', 'gas', 'pet', 'ely'), wedge_min=WEDGE_MIN, sub_max=SUBSIDY_MAX, min_musd=WEDGE_MIN_MUSD):
    """S16-Renergywedge (TC; coordinator 2026-10-27 from the GHA/KAZ trace): for each energy row, purchaser over basic value
    across all users (firms, households, government, investment; domestic and imported), and the net subsidy (basic less
    purchaser where positive) over the row's output (MAKB). Flagged: purchaser/basic below wedge_min, or the subsidy above
    sub_max of output. In beta v4 GHA and KAZ ely (0.16 and 0.155; the 24-group single-region calibration fails below
    about 0.10-0.20). Returns a frame region, good, basic, purchaser, ratio, subsidy_share, flag."""
    ci = _ix(comm)
    rows = []
    for c in goods:
        if c not in ci:
            continue
        i = ci[c]
        b = (D['VDFB'][i].sum(axis=0) + D['VMFB'][i].sum(axis=0) + D['VDPB'][i] + D['VMPB'][i] + D['VDGB'][i] + D['VMGB'][i]
             + D['VDIB'][i] + D['VMIB'][i])
        p = (D['VDFP'][i].sum(axis=0) + D['VMFP'][i].sum(axis=0) + D['VDPP'][i] + D['VMPP'][i] + D['VDGP'][i] + D['VMGP'][i]
             + D['VDIP'][i] + D['VMIP'][i])
        out = D['MAKB'][i].sum(axis=0)
        for k, r in enumerate(regs):
            if b[k] < min_musd:
                continue
            ratio = float(p[k] / b[k])
            sub = max(float(b[k] - p[k]), 0.0)
            ss = sub / float(out[k]) if out[k] > 0 else np.nan
            rows.append(dict(region=r, good=c, basic_musd=float(b[k]), purchaser_musd=float(p[k]), ratio=ratio, subsidy_share_output=ss,
                             flag=bool(ratio < wedge_min or (np.isfinite(ss) and ss > sub_max))))
    return pd.DataFrame(rows, columns=['region', 'good', 'basic_musd', 'purchaser_musd', 'ratio', 'subsidy_share_output', 'flag'])


def metal_exports(D, comm, regs, goods=METAL_GOODS, xs=METAL_X_SHARE, ms=METAL_M_SHARE, min_musd=METAL_MIN_MUSD):
    """S16-Rmetalx (TC; round-3 oddity 3, G gold mirror exports): ore and nfm cells whose exports (VXSB) are above xs of
    output and whose imports (VCIF) are above ms of output, with exports of at least min_musd: pass-through hubs or mirror
    exports not in the national accounts. Returns a frame region, good, output, exports, imports."""
    ci = _ix(comm)
    rows = []
    for c in goods:
        if c not in ci:
            continue
        i = ci[c]
        out = D['MAKB'][i].sum(axis=0)
        x = D['VXSB'][i].sum(axis=1)
        m = D['VCIF'][i].sum(axis=0)
        for k, r in enumerate(regs):
            if out[k] > 0 and x[k] >= min_musd and x[k] > xs * out[k] and m[k] > ms * out[k]:
                rows.append(dict(region=r, good=c, output_musd=float(out[k]), exports_musd=float(x[k]), imports_musd=float(m[k])))
    return pd.DataFrame(rows, columns=['region', 'good', 'output_musd', 'exports_musd', 'imports_musd'])


def filled_routes(D, comm, regs, filled, goods=ENERGY_ROUTE_GOODS, min_musd=ROUTE_MIN_MUSD):
    """S16-Rnonreporter (TC; package R): energy routes (VFOB) of at least min_musd whose country pair had no 2022 BACI row
    (neither partner reported; S07 absent_pairs_filled_s07r.csv, beta v4 P13 fill from an earlier year). filled: set of
    (exporter region, importer region) upper case. Returns a frame good, src, dst, vfob_musd."""
    ci, ri = _ix(comm), _ix([r.upper() for r in regs])
    rows = []
    for s_, d_ in sorted(filled):
        if s_ not in ri or d_ not in ri:
            continue
        for c in goods:
            v = float(D['VFOB'][ci[c], ri[s_], ri[d_]]) if c in ci else 0.0
            if v >= min_musd:
                rows.append(dict(good=c, src=s_, dst=d_, vfob_musd=v))
    return pd.DataFrame(rows, columns=['good', 'src', 'dst', 'vfob_musd'])


def blocked_routes(D, comm, regs, blocks):
    """S16-Rrouteblock (TC; package R, IRN to TWN): routes listed in config/s16/route_blocks.csv (good, src, dst; good '*'
    is every energy good) that still carry trade. Returns a frame good, src, dst, vfob_musd."""
    ci, ri = _ix(comm), _ix([r.upper() for r in regs])
    rows = []
    for b in blocks.itertuples():
        gs = ENERGY_ROUTE_GOODS if b.good == '*' else (b.good,)
        for c in gs:
            if c in ci and b.src in ri and b.dst in ri:
                v = float(D['VFOB'][ci[c], ri[b.src], ri[b.dst]])
                if v > 0:
                    rows.append(dict(good=c, src=b.src, dst=b.dst, vfob_musd=v))
    return pd.DataFrame(rows, columns=['good', 'src', 'dst', 'vfob_musd'])


def version_diff(D, P, comm, regs, prev_regs, prev_comm, rel=DIFF_REL, musd=DIFF_MUSD):
    """S16-Rversiondiff (TC): aggregates of this data base against the previous release (S16_PREV_RELEASE_DIR): world
    output by commodity, regional GDP at factor cost (EVFB) and output by region and commodity (MAKB), with moves above
    rel and musd. P: the previous release's arrays. Returns (summary dict, frame of the large moves) or (None, reason)
    where the sets differ."""
    if list(prev_regs) != list(regs) or list(prev_comm) != list(comm):
        return None, 'the previous release has other sets: not compared'
    o1, o0 = D['MAKB'].sum(axis=1), P['MAKB'].sum(axis=1)          # comm x region
    w1, w0 = o1.sum(axis=1), o0.sum(axis=1)
    va1, va0 = D['EVFB'].sum(axis=(0, 1)), P['EVFB'].sum(axis=(0, 1))
    rows = []
    for k, r in enumerate(regs):
        for i, c in enumerate(comm):
            a, b = float(o1[i, k]), float(o0[i, k])
            if abs(a - b) > musd and abs(a - b) > rel * max(abs(b), 1e-9):
                rows.append(dict(region=r, item=f'output {c}', previous_musd=b, current_musd=a))
        if abs(va1[k] - va0[k]) > musd and abs(va1[k] - va0[k]) > 0.05 * abs(va0[k]):
            rows.append(dict(region=r, item='factor income', previous_musd=float(va0[k]), current_musd=float(va1[k])))
    summ = dict(world_output_bn=(float(o0.sum()) / 1e3, float(o1.sum()) / 1e3),
                world_vxsb_bn=(float(P['VXSB'].sum()) / 1e3, float(D['VXSB'].sum()) / 1e3),
                world_factor_income_bn=(float(va0.sum()) / 1e3, float(va1.sum()) / 1e3),
                world_by_commodity={c: (float(w0[i]) / 1e3, float(w1[i]) / 1e3) for i, c in enumerate(comm)
                                    if abs(w1[i] - w0[i]) > 0.05 * abs(w0[i]) and abs(w1[i] - w0[i]) > musd})
    return summ, pd.DataFrame(rows, columns=['region', 'item', 'previous_musd', 'current_musd'])


# ------------------------------------------------------------------ RG release gates
def stale_screen_rows(rows, cutoff):
    """RG: builder-written screen explanation rows (lib/screen_review.builder_rows) dated before cutoff (YYYY-MM-DD): void at
    release until re-screened and re-dated (beta v4 released with 237 of 301 explanations dated 23 Oct, before beta v2).
    Returns the list 'STAGE importer item screen date'."""
    d = rows[rows['date'].astype(str).str[:10] < cutoff]
    return [f'{x.stage} {x.importer} {x.item} {x.screen} {x.date}' for x in d.itertuples()]


def stale_waivers(map_exceptions, map_results, gate_exceptions, gate_hits):
    """RG: waivers that no longer match what they excuse: a map failure exception whose map passes (or is not run), and a
    map gate exception with no gate value past [-1, 1] on that map and group. map_results: map, status, error; gate_hits:
    the excepted gate rows (map, group). Returns the list of stale waivers."""
    out = []
    res = {r.map: r for r in map_results.itertuples()} if len(map_results) else {}
    for e in map_exceptions.itertuples():
        r = res.get(e.map)
        if r is None or str(getattr(r, 'status', '')).upper() == 'PASS':
            out.append(f'map_failure_exceptions {e.map}: ' + ('not run' if r is None else 'passes'))
    hit = {(h.map, h.group) for h in gate_hits.itertuples()} if len(gate_hits) else set()
    for e in gate_exceptions.itertuples():
        key = (e.map, getattr(e, 'group', ''))
        if key not in hit and e.map not in {h[0] for h in hit}:
            out.append(f'map_gate_exceptions {e.map}: no gate value past [-1, 1]')
    return out


def release_gate(checks, required=('S16-Hrelease', 'S16-Grepro', 'S16-Hscreenreview', 'S16-Hwaivers', 'S16-Hmaps')):
    """RG (tools/release_gate.py): a stage's checks.json may be released only if it was run at release (S16-Hrelease PASS,
    which needs GTAP_RELEASE=1) and every required check is present, hard and PASS. Returns the list of problems."""
    by = {c['id']: c for c in checks}
    bad = []
    for k in required:
        c = by.get(k)
        if c is None:
            bad.append(f'{k}: missing')
        elif c.get('status') != 'PASS' or c.get('kind') != 'hard':
            bad.append(f'{k}: {c.get("kind")} {c.get("status")} ({c.get("value")})')
    bad += [f'{c["id"]}: hard FAIL' for c in checks if c.get('kind') == 'hard' and c.get('status') == 'FAIL' and c['id'] not in required]
    return bad


def release_kind(rg, rel):
    """RG: the kind of the release-gate checks (S16-Hrelease, S16-Hwaivers): hard only in a release run with the gates on
    (GTAP_RELEASE=1), a report NOTE otherwise, so a development S16 run still stamps; release_gate() refuses any S16 whose
    S16-Hrelease is not a hard PASS."""
    return 'hard' if (rg and rel) else 'report'


def release_mode():
    return os.environ.get('GTAP_RELEASE', '') == '1'
