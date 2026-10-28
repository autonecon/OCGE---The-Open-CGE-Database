"""S16 map suite: resolve the aggregation maps of config/s16/maps.csv on the finished data base (PLAN §4).

A map names its regions (the rest pool into `row`) and a sector scheme of config/s16/sector_schemes.csv. Three
map kinds take their regions from the data, as the closure test on main did:
  - `saving_tails` (aggregation B): the ten lowest saving shares, then the largest savers by SAVE until the pool
    holds at most world SAVE (σ_qinv <= 1). CARRY-SAVE regions (S14, saving share below -1) are never picked: the
    model bounds σsave to [-1, 1], so they stay pooled (E50).
  - `smallest` (aggregation C): the twenty smallest regions by Y, CARRY-SAVE regions left pooled, plus the listed ones.
  - `fixed`: the listed regions.
A map lists its sector schemes in order ("s7_smoke|s7_fuels"). The first scheme on which every named region buys
every sector group from domestic producers wherever it buys it at all is used (pre-check below); the scheme used and
why the earlier ones were refused are reported. A map with no such scheme is refused.

Pre-checks on the aggregated values (no solve):
  - one-sided pairs: a (region group, sector group) with purchases from imports and none from domestic producers
    (or the reverse) cannot be prepared by the S15 swap (no donor) and the Julia levels model takes log(0);
  - S-I gate (E50): σsave = SAVE/Y and σ_qinv = SAVE / world SAVE of every group in [-1, 1].
"""
import numpy as np
import pandas as pd

KINDS = ('fixed', 'saving_tails', 'smallest')


def group_regions(regs, named):
    """A token REG names a region alone; NAME=REG+REG+... pools those regions into group name."""
    g = {}
    for t in named:
        if '=' in t:
            name, members = t.split('=')
            g.update({r.upper(): name.lower() for r in members.split('+')})
        else:
            g[t.upper()] = t.lower()
    return [g.get(r, 'row') for r in regs]


def members(named):
    return [r for t in named for r in (t.split('=')[1].split('+') if '=' in t else [t])]


def saving_tails(acc, carry, n_low=10):
    ok = acc.drop(index=[r for r in carry if r in acc.index])
    low = list(ok['saving_share'].sort_values().index[:n_low])
    W = acc['SAVE'].sum()
    picked = acc.loc[low, 'SAVE'].sum()
    for r in acc['SAVE'].sort_values(ascending=False).index:
        if (W - picked) / W <= 1:
            break
        if r in low or r in carry:
            continue
        low.append(r)
        picked += acc.loc[r, 'SAVE']
    return low


def smallest(acc, carry, n=20):
    ok = acc.drop(index=[r for r in carry if r in acc.index])
    return list(ok['Y'].sort_values().index[:n])


def one_sided(dom, imp, rgroup, sgroup):
    """dom, imp: arrays (comm, reg) of total domestic and imported purchases at basic prices.
    Returns [(region group, sector group, missing side)]."""
    d = pd.DataFrame(dom).T.groupby(np.array(rgroup)).sum().T.groupby(np.array(sgroup)).sum()
    m = pd.DataFrame(imp).T.groupby(np.array(rgroup)).sum().T.groupby(np.array(sgroup)).sum()
    out = []
    for s in d.index:
        for r in d.columns:
            if (d.loc[s, r] > 0) != (m.loc[s, r] > 0):
                out.append((r, s, 'domestic' if d.loc[s, r] <= 0 else 'imported'))
    return out


def saving_gate(acc, rgroup):
    g = acc[['SAVE', 'Y']].groupby(np.array(rgroup)).sum()
    g['sigma_save'] = g['SAVE'] / g['Y']
    g['sigma_qinv'] = g['SAVE'] / acc['SAVE'].sum()
    g.index.name = 'group'
    return g


def gate_split(gates, exc):
    """Split the out-of-bound gate rows into (fails, excepted). An exception names a map, group and measure
    (sigma_save or sigma_qinv) and the largest absolute value it accepts; anything past it still fails."""
    ok = {(e.map, e.group, e.measure): float(e.limit) for e in exc.itertuples()}
    fails, excepted = [], []
    for g in gates.itertuples():
        for m_ in ('sigma_save', 'sigma_qinv'):
            v = float(getattr(g, m_))
            if abs(v) <= 1:
                continue
            lim = ok.get((g.map, g.group, m_))
            (excepted if lim is not None and abs(v) <= lim else fails).append(dict(map=g.map, group=g.group, measure=m_, value=v))
    return pd.DataFrame(fails, columns=['map', 'group', 'measure', 'value']), pd.DataFrame(excepted, columns=['map', 'group', 'measure', 'value'])


def failure_split(res, exc):
    """Split the failed maps of map_results into (fails, excepted). An exception (config/s16/map_failure_exceptions.csv)
    names a map and the exact error it accepts; the same map failing in any other way still fails."""
    ok = {(e.map, str(e.error).strip()) for e in exc.itertuples()}
    bad = res[res['status'] != 'PASS']
    err = bad['error'].fillna('').astype(str).str.strip().str.strip('"') if 'error' in bad else pd.Series('', index=bad.index)
    hit = [(m, e) in ok for m, e in zip(bad['map'], err)]
    return bad[[not h for h in hit]], bad[hit]


def resolve(maps, schemes, acc, regs, comm, dom, imp, carry):
    """Return (list rows, region rows, sector rows, report rows, gate rows)."""
    lst, rrows, srows, rep, gates = [], [], [], [], []
    for m in maps.itertuples():
        listed = [x for x in m.regions.split() if x]
        if m.kind == 'saving_tails':
            named = saving_tails(acc, carry) + listed
        elif m.kind == 'smallest':
            named = smallest(acc, carry) + listed
        else:
            named = listed
        missing = [r for r in members(named) if r not in regs]
        if missing:
            raise SystemExit(f'map {m.map}: regions not in the data base: {missing}')
        rgroup = group_regions(regs, named)
        tried, used, refused = m.schemes.split('|'), None, []
        for sc in tried:
            sg = [schemes.loc[c, sc] for c in comm]
            bad = one_sided(dom, imp, rgroup, sg)
            if not bad:
                used = sc
                break
            refused.append(f'{sc}: ' + ', '.join(f'{s} in {r} ({miss} side zero)' for r, s, miss in bad[:6]) + (' ...' if len(bad) > 6 else ''))
        gate = saving_gate(acc, rgroup)
        out_of_bound = gate[(gate['sigma_save'].abs() > 1) | (gate['sigma_qinv'].abs() > 1)]
        carry_alone = [r for r in carry if (rgroup.count(rgroup[regs.index(r)]) == 1)]
        rep.append(dict(map=m.map, kind=m.kind, n_regions=len(set(rgroup)), named=' '.join(x.lower() for x in named),
                        scheme=used or '', n_sectors=len(set(schemes[used])) if used else 0, refused_schemes='; '.join(refused),
                        tariff_shock=m.tariff_shock, gate_fail=' '.join(out_of_bound.index), carry_save_named=' '.join(carry_alone),
                        purpose=m.purpose))
        for gname, r in gate.iterrows():
            gates.append(dict(map=m.map, group=gname, SAVE=r['SAVE'], Y=r['Y'], sigma_save=r['sigma_save'], sigma_qinv=r['sigma_qinv']))
        if used is None:
            continue
        lst.append(dict(map=m.map, tariff_shock=m.tariff_shock))
        rrows += [dict(map=m.map, region=r, group=g) for r, g in zip(regs, rgroup)]
        srows += [dict(map=m.map, sector=c, group=schemes.loc[c, used]) for c in comm]
    return (pd.DataFrame(lst, columns=['map', 'tariff_shock']), pd.DataFrame(rrows), pd.DataFrame(srows),
            pd.DataFrame(rep), pd.DataFrame(gates))
