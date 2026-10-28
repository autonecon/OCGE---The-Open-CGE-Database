#!/usr/bin/env python3
"""Fable QA A-02: which S13 holds move the ICIO intermediate structure (S13-Ricio, median 37% against a 2% gate)?

Runs s13_fit.py once per variant on a subset of regions in a scratch stages folder (the upstream snapshots are
symlinked, S13 is written fresh; S13_ANALYSIS_* marks every run dirty, so nothing is stamped), each variant switching
one hold off (or all of them), and tabulates the ICIO gate per region: the total absolute change of intermediate cells
over io_s12 intermediate use, its composition part (cells against the io_s12 cells scaled with their column's output)
and whether the region fitted.

    python3 tools/s13_hold_ablation.py OUT_DIR [--regions USA,CHN,...] [--jobs 4] [--variants base,ptax,...]

OUT_DIR gets ablation_s13.csv (variant x region), ablation_s13.md (summary) and the run logs. The numbers are S13
data (not for publication, as io_s13): keep OUT_DIR outside git.
"""
import argparse
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGES = os.path.join(os.path.dirname(BUILD), 'stages')
UPSTREAM = ('PREP_energy_volumes', 'S01_sets_registry', 'S02_macro', 'S03_io_cleaning', 'S04_disagg_gov', 'S05_composite',
            'S06_apt', 'S07_trade', 'S08_margins', 'S09_services', 'S10_tariffs_taxes', 'S11_energy', 'S12_factors')
REGIONS = ('USA,CHN,JPN,DEU,IND,GBR,FRA,ITA,BRA,CAN,RUS,KOR,AUS,MEX,ESP,IDN,SAU,NLD,CHE,TUR,'
           'KHM,ARE,SGP,BEL,IRL,KAZ,HKG')
# one hold off per variant: (s13 choice, the value that switches the hold off); 'none' switches every one of them off
HOLDS = {
    'ptax_money': ('product_tax_totals', 'cell_rates_held_revenue_moves_with_the_fit'),
    'ely_subsidy_money': ('electricity_subsidy_money', 'prior_rate_moves_with_the_fit'),
    'energy_users': ('energy_user_cells', 'off'),
    'power_cells': ('power_fuel_cells', 'off'),
    'own_use_cap': ('own_use_cap', 'off'),
    'refinery_gas_caps': ('energy_use_caps', 'off'),
    'crude_users': ('crude_smear_users', 'b06_row_every_buyer'),
    'fuel_subsidies': ('fuel_subsidies', 'off'),
    'factor_tax_money': ('factor_tax_totals', 's12_rates_on_fitted_evfp'),
}


def variants(names):
    out = {'base': {}}
    out.update({k: dict([v]) for k, v in HOLDS.items()})
    out['none'] = dict(HOLDS[k] for k in HOLDS if k != 'fuel_subsidies')
    return {k: v for k, v in out.items() if not names or k in names}


def run(out, name, choices, regions):
    st = os.path.join(out, 'stages_' + name)
    os.makedirs(st, exist_ok=True)
    for u in UPSTREAM:
        p = os.path.join(st, u)
        if not os.path.lexists(p):
            os.symlink(os.path.join(STAGES, u), p)
    env = dict(os.environ, GTAP_STAGES_DIR=st, S13_ANALYSIS_REGIONS=regions,
               S13_ANALYSIS_CHOICES=','.join(f'{k}={v}' for k, v in choices.items()))
    env.pop('S13_PREV_OUTPUT', None)
    with open(os.path.join(out, f'{name}.log'), 'w') as log:
        subprocess.run([sys.executable, os.path.join(BUILD, 's13_fit.py')], cwd=BUILD, env=env, stdout=log, stderr=subprocess.STDOUT)
    o = os.path.join(st, 'S13_fit', 'output')
    if not os.path.exists(os.path.join(o, 'fit_report_s13.csv')):
        return pd.DataFrame([dict(variant=name, region='-', ok=False, note='run stopped; see log')])
    fit = pd.read_csv(os.path.join(o, 'fit_report_s13.csv'))[['region', 'ok', 'iterations']]
    gate = pd.read_csv(os.path.join(o, 'icio_gate_s13.csv'))
    df = fit.merge(gate, on='region', how='left')
    df.insert(0, 'variant', name)
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--regions', default=REGIONS)
    ap.add_argument('--jobs', type=int, default=4)
    ap.add_argument('--variants', default='')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    V = variants([x for x in a.variants.split(',') if x])
    with ThreadPoolExecutor(a.jobs) as ex:
        res = list(ex.map(lambda kv: run(a.out, kv[0], kv[1], a.regions), V.items()))
    df = pd.concat(res, ignore_index=True)
    df.to_csv(os.path.join(a.out, 'ablation_s13.csv'), index=False)
    base = df[df['variant'] == 'base'].set_index('region')
    lines = ['# S13 hold ablation (Fable QA A-02)', '',
             f'Regions: {a.regions}. Share = total absolute change of intermediate cells over io_s12 intermediate use (S13-Ricio); '
             'composition = change against the io_s12 cells scaled with their column output, over the same use. Median over the '
             'regions that fit in both the variant and the base.', '',
             '| Variant | Hold switched off | Regions fitted | Median share | Median composition | Median change vs base (points) |',
             '|---|---|---|---|---|---|']
    for name, choices in V.items():
        g = df[df['variant'] == name].set_index('region')
        ok = g[g['ok'].astype(bool)] if 'ok' in g else g.iloc[0:0]
        both = ok.index.intersection(base[base['ok'].astype(bool)].index)
        comp = ok['composition_part_musd'] / ok['intermediate_s12_musd']
        d = (ok.loc[both, 'share'] - base.loc[both, 'share']) * 100
        lines.append(f'| {name} | {", ".join(f"{k}={v}" for k, v in choices.items()) or "-"} | {len(ok)} of {len(g)} | '
                     f'{ok["share"].median():.1%} | {comp.median():.1%} | {d.median():+.1f} |')
    lines += ['', '## By region (share; composition in brackets)', '']
    piv = df.pivot_table(index='region', columns='variant', values='share')
    pc = (df['composition_part_musd'] / df['intermediate_s12_musd']).groupby([df['region'], df['variant']]).first().unstack()
    cols = list(V)
    lines += ['| Region | ' + ' | '.join(cols) + ' |', '|---|' + '---|' * len(cols)]
    for r in piv.index:
        lines.append(f'| {r} | ' + ' | '.join(f'{piv.loc[r, c]:.1%} ({pc.loc[r, c]:.1%})' if c in piv.columns and pd.notna(piv.loc[r, c])
                                              else 'not fitted' for c in cols) + ' |')
    open(os.path.join(a.out, 'ablation_s13.md'), 'w').write('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
