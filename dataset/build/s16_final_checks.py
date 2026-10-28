#!/usr/bin/env python3
"""S16 final checks (PLAN §3(k) and §4; READINESS §1 S16: the full §3(k) table, the build stops on any hard FAIL).

The finished data base is the S15 HAR files. S16 reads them back with an independent reader (harpy, Float32) and
runs every row of the §3(k) table on them:
  - the stage roll-up: S01-S15 each stamped, SHA256SUMS bound, no hard FAIL, the stamp chain unbroken;
  - identities, signs (with subsidy provenance), macro targets, the pre-solve S-I gate, VDEP < I, held trade,
    tariff rates, energy output, the region list, the ledger of every stage and the concept tags;
  - the rows that need the source data the producing stage read are collected from that stage's checks;
  - QA against GTAP 10 shares (internal, report-only, kept outside git);
  - the map suite (PLAN §4): every map of config/s16/maps.csv is resolved, pre-checked (one-sided Armington pairs,
    S-I gate), then aggregated, prepared, calibrated, solved unshocked and with a numeraire x 1.1 in
    GlobalTradeAnalysisProjectModelV7 (s16_final/julia/map_suite.jl).
S16 changes no number of the data base; its ledger is header-only.

Environment: S15_HARPY_PYTHON (requirements-s15-reader.txt), S15_JULIA (julia 1.12; s15_har/julia project),
S16_JOBS (parallel Julia processes for the maps with fewer than S16_HEAVY_REGIONS regions, default 3 and 10; larger
maps run one at a time), S16_GTAP10_DIR (a GTAP 10 gsdf*.har folder; the
comparison is skipped without it) and S16_PRIVATE_DIR (where the GTAP comparison table is written, outside git).
"""
import gc as _gc
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

for _v in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_v, '1')

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.stagekit import Stage, ROOT, BUILD, STAGES, DATA, sha256  # noqa: E402
from lib.private_files import private_paths  # noqa: E402
from lib import macro_external as MX  # noqa: E402
from lib import screen_review as SRV  # noqa: E402
from s12_factors.checks import secret_scan  # noqa: E402
from s13_fit import method as M13  # noqa: E402
from s14_assembly import method as M14  # noqa: E402
from s14_assembly.checks import chain  # noqa: E402
from s15_har import method as M15  # noqa: E402
from s15_har import checks as K15  # noqa: E402
from s16_final import config as C  # noqa: E402
from s16_final import checks as K  # noqa: E402
from s16_final import maps as MP  # noqa: E402
from s16_final import gtap_compare as G  # noqa: E402
from s16_final import betav5 as B5  # noqa: E402

STAGE_NAMES = ['S01_sets_registry', 'S02_macro', 'S03_io_cleaning', 'S04_disagg_gov', 'S05_composite', 'S06_apt', 'S07_trade',
               'S08_margins', 'S09_services', 'S10_tariffs_taxes', 'S11_energy', 'S12_factors', 'S13_fit', 'S14_final_assembly', 'S15_har_jls']
UP = {k: f'{STAGES}/{k}' for k in ('S01_sets_registry', 'S02_macro', 'S09_services', 'S10_tariffs_taxes', 'S11_energy', 'S12_factors', 'S13_fit',
                                    'S14_final_assembly', 'S15_har_jls')}
JULIA_DIR = os.path.join(BUILD, 's15_har', 'julia')
SUITE = os.path.join(BUILD, 's16_final', 'julia', 'map_suite.jl')
ENERGY = ('coa', 'oil', 'gas', 'pet', 'ely')
# §3(k) rows that need the source data the producing stage read: collected from that stage's checks (hard rows must PASS)
COLLECTED = [
    ('S07_trade', 'S07-H6'), ('S07_trade', 'S07-H5'), ('S07_trade', 'S07-R1'), ('S07_trade', 'S07-R3'),
    ('S09_services', 'S09-H4'), ('S09_services', 'S09-H13'), ('S09_services', 'S09-R2'),
    ('S10_tariffs_taxes', 'S10-Hwedge'), ('S10_tariffs_taxes', 'S10-Hnegtax'), ('S10_tariffs_taxes', 'S10-Rcustoms'), ('S10_tariffs_taxes', 'S10-Hbasis'),
    ('S11_energy', 'S11-Hvpv'), ('S11_energy', 'S11-Hcif'), ('S11_energy', 'S11-Hbal'), ('S11_energy', 'S11-Hneg'),
    ('S02_macro', 'S02-P3'), ('S02_macro', 'S02-R4'), ('S13_fit', 'S13-Hfit'), ('S13_fit', 'S13-Hzeros'),
]


def listed_upstreams(stage_dir):
    p = stage_dir + '/STAMP'
    out = {}
    if os.path.exists(p):
        for line in open(p).read().splitlines():
            if line.startswith('upstream '):
                parts = line.split()
                out[parts[1]] = parts[-1]
    return out


def read_har(S, harpy_python, src, tmp):
    """harpy dump of gsdf{set,par,dat}.har in src: ({header: array}, {header: shape}, {set: elements})."""
    dump = os.path.join(tmp, os.path.basename(src.rstrip('/')) + '_harpy')
    r = subprocess.run([harpy_python, '-I', os.path.join(BUILD, 's15_har', 'read_har.py'), src, dump], capture_output=True, text=True)
    S.log(f'harpy {src}: {r.stdout.strip()} {r.stderr.strip()[-300:]}')
    if r.returncode:
        raise RuntimeError('harpy read failed: ' + r.stderr[-500:])
    arrays, shapes, chars = {}, {}, {}
    for line in open(os.path.join(dump, 'index.txt')):
        f, name, kind, shp, _ = line.rstrip('\n').split('|')
        shapes[name] = tuple(int(x) for x in shp.split('x')) if shp else ()
        if kind == 'char':
            chars[name] = open(os.path.join(dump, f'{f}_{name}.txt')).read().split('\n')[:-1]
        else:
            arrays[name] = np.load(os.path.join(dump, f'{f}_{name}.npy'))
    return arrays, shapes, chars


def _peak_gb(pid):
    try:
        for l in open(f'/proc/{pid}/status'):
            if l.startswith('VmHWM:'):
                return int(l.split()[1]) / 1e6
    except OSError:
        pass
    return 0.0


def _launch(julia, mapdir, tmp, tag, part):
    res = os.path.join(tmp, f'suite_{tag}.txt')
    log = open(os.path.join(tmp, f'suite_{tag}.log'), 'w')
    p = subprocess.Popen([julia, '--startup-file=no', f'--project={JULIA_DIR}', SUITE, UP['S15_har_jls'] + '/output', mapdir, res] + part,
                         stdout=log, stderr=subprocess.STDOUT, env=dict(os.environ, JULIA_PROJECT=JULIA_DIR))
    return p, res, log, part


def _wait(procs):
    """Wait for every process, sampling its peak resident memory (log only)."""
    peak = {id(p): 0.0 for p, *_ in procs}
    while any(p.poll() is None for p, *_ in procs):
        for p, *_ in procs:
            if p.poll() is None:
                peak[id(p)] = max(peak[id(p)], _peak_gb(p.pid))
        time.sleep(2)
    return peak


def run_suite(S, julia, mapdir, names, jobs, heavy, tmp):
    """Run map_suite.jl over the maps. `names` maps each map to its number of region groups. Memory grows with the
    region count (about 4 GB at 5 regions, 9 GB at 18), so maps with fewer than `heavy` regions run in `jobs`
    parallel processes, and each larger map then runs alone in a fresh process. A process the system kills (out of
    memory) leaves its unfinished maps without a status line; each is retried once alone, and a map still without
    one is NOT RUN in S16-Hmaps. Returns result lines in map order."""
    light = sorted((m for m in names if names[m] < heavy), key=lambda m: -names[m])
    big = sorted((m for m in names if names[m] >= heavy), key=lambda m: names[m])
    lines = {}

    def collect(procs):
        peak = _wait(procs)
        for p, res, log, part in procs:
            log.close()
            for l in open(log.name).read().splitlines():
                if '.' in l.split('=')[0] and l.split('.')[0] in names and '=' in l:
                    S.log('map_suite: ' + l)
            if os.path.exists(res):
                for l in open(res).read().splitlines():
                    lines.setdefault(l.split('.', 1)[0], []).append(l)
            S.log(f'map_suite process {"+".join(part)}: exit {p.returncode}, peak memory {peak[id(p)]:.1f} GB')

    collect([_launch(julia, mapdir, tmp, f'l{i}', light[i::jobs]) for i in range(jobs) if light[i::jobs]])
    for i, m in enumerate(big):
        collect([_launch(julia, mapdir, tmp, f'h{i}', [m])])
    # a map with no status line lost its process (killed, out of memory): retry it once, alone
    for i, m in enumerate([m for m in names if not any(l.startswith(m + '.status=') for l in lines.get(m, []))]):
        S.log(f'map_suite: {m} has no result; retried alone')
        lines.pop(m, None)
        collect([_launch(julia, mapdir, tmp, f'r{i}', [m])])
    return [l for m in names for l in lines.get(m, [])]


def main():
    choices = C.load_choices()
    S = Stage('S16', 'final_checks')
    I = S.inp
    S.check('S16-Hconfig', f'config/s16/s16_choices.csv has the {len(C.CHOICES)} choices this code implements, each with decided_by and decided_at',
            'hard', len(choices), len(C.CHOICES), len(choices) == len(C.CHOICES), 'repo; s16_choices',
            'Choices not in the GTAP text: ' + ', '.join(k for k, r in choices.items() if r['gtap_status'] in ('departure_logged', 'not_in_gtap_text')))
    for k in UP.values():
        S.upstream(k)
    I(C.CHOICES_PATH, 'S16 choices')
    T = {k: C.load_table(k) for k in C.TABLES}
    for k in C.TABLES:
        I(C.table_path(k), f'S16 config {C.TABLES[k][0]}')
    for f in (SUITE, os.path.join(JULIA_DIR, 'prepare_for_solve.jl'), os.path.join(JULIA_DIR, 'Manifest.toml')):
        I(f, f'S16 Julia {os.path.basename(f)}')

    out = lambda st, fn: I(UP[st] + '/output/' + fn, f'{st[:3]} {fn}')
    for fn in ('gsdfset.har', 'gsdfpar.har', 'gsdfdat.har'):
        out('S15_har_jls', fn)
    sets = M15.read_sets(pd.read_csv(out('S14_final_assembly', 'sets_s14.csv')))
    regs, comm, endw = sets['REG'], sets['COMM'], sets['ENDW']
    flags = pd.read_csv(I(UP['S14_final_assembly'] + '/flags.csv', 'S14 flags (CARRY-SAVE, CARRY-VDEP, NEG-SAVE)'))
    carry = sorted(flags.loc[flags['id'] == 'CARRY-SAVE', 'subject'])
    sums = {u['name']: (u['actual_sums'], listed_upstreams(p)) for p, u in S.upstreams.items()}
    n, det = chain(sums)
    S.check('S16-Hchain', 'Each upstream read here is the one the other upstreams were stamped on (SHA256SUMS listed in their STAMPs)', 'hard',
            n, 0, n == 0, 'stage; 17B p.5-6 staged hand-off', det)

    # ------------------------------------------------------------- roll-up of every stage
    n, det, roll = K.rollup(STAGES, STAGE_NAMES, sha256)
    S.check('S16-Hrollup', 'Stages S01-S15: each has a STAMP, its SHA256SUMS equals the one in the STAMP, its checks.json has no hard FAIL, and every upstream SHA256SUMS a STAMP names is that upstream\'s current SHA256SUMS', 'hard',
            n, 0, n == 0, 'stage; GTAP 12 ch.17B pp.5-6 stamp artefacts', det or f'{int(roll["hard"].sum())} hard checks, {int(roll["report_note"].sum())} report NOTEs over 15 stages')
    S.write('stage_rollup_s16.csv', roll)
    n, det, col = K.collected(STAGES, COLLECTED)
    S.check('S16-Hcollected', '§3(k) rows that need the source data their stage read (trade against BaTIS and BACI, duty wedge, energy volume x price, concept parity, FIT residual) are collected from that stage: each is present and no hard one FAILs. S11-Hvpv, S11-Hcif and S09-H13 are identities inside their stage (they confirm the stage arithmetic, not the source; Grok review F1). S10-Hwedge is not (fix-round item B9): it reads the written tm, VMSB and duty files back and compares them with VCIF re-read from the S07 vfob and S08 vtwr files and with the BACI line accumulator on every bilateral cell; only its duty = VCIF x tm and VMSB >= VCIF part is an identity. The report-only rows (S07-R*, S09-R2, S10-Rcustoms) cannot FAIL', 'hard',
            n, 0, n == 0, 'stage; C01, C02, C04, C24', det or '; '.join(f'{r.id} {r.status}' for r in col.itertuples()))
    S.write('collected_checks_s16.csv', col)

    # ------------------------------------------------------------- the finished data base, read back
    hp = os.environ.get('S15_HARPY_PYTHON', '')
    if not hp:
        raise SystemExit('S15_HARPY_PYTHON is not set (requirements-s15-reader.txt)')
    tmp = tempfile.mkdtemp(prefix='s16_')
    try:
        arrays, shapes, chars = read_har(S, hp, UP['S15_har_jls'] + '/output', tmp)
        n, det = K15.dims(shapes, M15.expected_dims(sets))
        S.check('S16-Hdims', 'harpy reads every header of the three S15 files with the expected dimensions, and no other header', 'hard',
                n, 0, n == 0, 'repo; model_requirements §1', det)
        n, det = K15.sets_match({k: chars.get(k, []) for k in sets}, sets)
        S.check('S16-Hsets', 'Set elements as read back equal the S14 sets (lower case, same order), ACTS = COMM', 'hard', n, 0, n == 0, 'repo; model_requirements §1a', det)
        R = {h: arrays[h] for h, *_ in M15.DATA_HEADERS}
        n, det = K.region_list(regs, pd.read_csv(out('S01_sets_registry', 'regions.csv'))['region'])
        S.check('S16-Hregions', 'Region list: 167 regions, the S01 list exactly (no fold or drop without David)', 'hard', n, 0, n == 0, 'stage; PLAN §3(k) region list', det)

        # identities
        marg_idx = [comm.index(m) for m in sets['MARG']]
        n, det = K15.identities(R, marg_idx, regs, comm)
        S.check('S16-Hidentities', 'Zero profit, domestic and import market clearing, VCIF = VFOB + VTWR, world VST = world VTWR (1e-6 relative, Float32 values)', 'hard',
                n, 0, n == 0, 'identity; basis basic vs basic', det)
        acc = M15.regional_accounts(R, endw.index('capital'))
        acc.index = regs
        n, det = K15.saving(acc)
        S.check('S16-Hsave', 'SAVE = Y - C - G in every region and world SAVE = world (I - VDEP) (1e-6 relative)', 'hard', n, 0, n == 0, 'identity; GTAP 12 eq. 7.1', det)
        g = ((acc['SAVE'] - (acc['I'] - acc['VDEP'])) - (acc['X'] - acc['M'])).abs() / acc['Y'].abs()
        S.check('S16-Hsixm', 'S - I = X - M: SAVE - (I - VDEP) = (VFOB + VST) - VCIF in every region (1e-6 of Y)', 'hard',
                int((g > 1e-6).sum()), 0, bool((g <= 1e-6).all()), 'identity; GTAP 12 eq. 7.1-7.2', '; '.join(f'{r} {v:.2e}' for r, v in g[g > 1e-6].head(10).items()))

        # signs
        n, det = K15.signs(R)
        S.check('S16-Hsign', 'All flows non-negative: no negative cell in any header except SAVE', 'hard', n, 0, n == 0, 'sign; TP01 §7', det)
        n, det = K.vmsb_ge_vcif(R, regs, comm)
        S.check('S16-Hvmsb', 'VMSB >= VCIF on every route (no negative import tariff)', 'hard', n, 0, n == 0, 'sign; tariff wedge VMSB - VCIF', det)
        n, det = K15.factor_payment(R, regs, comm)
        S.check('S16-Hva', 'No negative value added: every activity with output has EVFP > 0 (and EVFP >= 0 everywhere by S16-Hsign)', 'hard', n, 0, n == 0, 'sign; model identity 8', det)
        io13 = pd.read_csv(out('S13_fit', 'io_s13.csv.gz'))
        io13 = io13[io13['row'].isin(['TLS', 'PTAX', 'PSE_input'])].melt(id_vars=['region', 'row'], var_name='column', value_name='value').fillna(0.0)
        support = pd.read_csv(out('S10_tariffs_taxes', 'support_s10.csv'))
        exsub = pd.read_csv(out('S10_tariffs_taxes', 'export_subsidy_s10.csv'))
        rebal = pd.read_csv(out('S14_final_assembly', 'rebalance_s14.csv.gz'))
        sp = UP['S14_final_assembly'] + '/output/seeded_pairs_s14.csv'      # fix list A13 (absent before the rerun)
        seeded = {(r.region, r.comm) for r in pd.read_csv(out('S14_final_assembly', 'seeded_pairs_s14.csv')).itertuples()} if os.path.exists(sp) else set()
        io12 = pd.read_csv(out('S12_factors', 'io_s12.csv.gz'))
        donors = set(pd.read_csv(out('S13_fit', 'product_tax_source_s13.csv'))['region'])     # the S05 representative-table regions
        io12 = io12[(io12['row'] == 'TLS') & ~io12['region'].isin(donors)].melt(id_vars=['region', 'row'], var_name='column', value_name='value')
        io12_neg = {(x.region, x.column) for x in io12[io12['value'] < 0].itertuples()}
        etr = pd.read_csv(out('S13_fit', 'energy_tax_rates_s13.csv'))
        fsc = pd.read_csv(out('S13_fit', 'fuel_subsidy_columns_s13.csv'))
        energy_neg = ({(x.region, x.column, x.commodity) for x in etr[etr['energy_rate'] < 0].itertuples()}
                      | {(x.region, x.column, x.commodity) for x in fsc[fsc['rate'] < 0].itertuples()})
        scp = UP['S14_final_assembly'] + '/output/seed_columns_s14.csv'
        seed_cols = {(x.region, x.column) for x in pd.read_csv(scp).itertuples()} if os.path.exists(scp) else set()
        n, det, prov = K.subsidy_provenance(R, sets, io13, support, exsub, rebal, seeded, io12_neg, energy_neg, seed_cols)
        S.check('S16-Hsubsidy', 'No negative tax without a cited subsidy source: each subsidy cell traces to a negative net tax of its source I-O column (TLS, PTAX), booked OECD PSE support (input, output, factor), a booked WTO export subsidy, a GTAP ch.12 energy-tax rate or IEA fuel subsidy, the source I-O table of an own-table region, an S14 rounding move (<= 0.001 USD million), the suppliers of an S14 A13 seeded column, or the A13 remainder shift (above -1e-4) on a column the seed moved', 'hard',
                n, 0, n == 0, 'sign; TP01 §7; GTAP 12 ch.11A, 11C', det or '; '.join(f'{r.tax} {int(r.negative_cells)}' for r in prov.itertuples() if r.negative_cells))
        S.write('subsidy_provenance_s16.csv', prov)
        vdk = acc['VDEP'] >= acc['capital_income']
        S.check('S16-Hvdepk', 'VDEP below capital income in every region', 'hard', int(vdk.sum()), 0, not vdk.any(), 'sign; E12', ' '.join(acc.index[vdk]))

        # macro
        s02 = pd.read_csv(out('S02_macro', 'macro_regions.csv')).set_index('region').reindex(regs)
        s13 = pd.read_csv(out('S13_fit', 'macro_s13.csv')).set_index('region').reindex(regs)
        n, det, mac = K.macro(acc, s02, s13)
        S.check('S16-Hgdp', 'GDP = C + G + I + X - M of the data base equals the S02 target (WDI/AMA) in every region (1e-6 relative)', 'hard',
                n, 0, n == 0, 'C14; basis purchasers vs purchasers', det)
        band = mac[(mac['C_G_I_factor'] - 1).abs() > 0.10]
        S.check('S16-Rfactor', 'C, G and I scale factor (S13) outside 1 ± 10% (PLAN gate, report-only by decision)', 'report', len(band), 0, band.empty,
                'C26; basis purchasers vs purchasers', '; '.join(f'{r} {v:.3f}' for r, v in band['C_G_I_factor'].sort_values().items()))
        gf = mac['I_over_GFCF']
        gfo = gf[(gf < 0.8) | (gf > 1.25)].sort_values()
        S.check('S16-Rgfcf', 'Investment of the data base (purchasers\' prices, stocks removed) over S02 GFCF (E13; report-only): regions outside 0.8-1.25', 'report',
                f'{len(gfo)} of {gf.notna().sum()}; min {gf.min():.3f} ({gf.idxmin()}), median {gf.median():.3f}, max {gf.max():.3f} ({gf.idxmax()})', '0.8-1.25', gfo.empty,
                'C13; basis purchasers vs purchasers', '; '.join(f'{r} {v:.3f}' for r, v in gfo.items()))
        S.write('macro_s16.csv', mac.reset_index(names='region'))

        # pre-solve S-I and VDEP < I
        si = [f'{r}: VKB {v.VKB:.4g} I {v.I:.4g} Y {v.Y:.4g}' for r, v in acc.iterrows() if not (v.VKB > 0 and v.I > 0 and v.Y > 0)]
        S.check('S16-Hsi', 'Pre-solve S-I gate (E12, E28, E50): VKB > 0, I > 0 and Y > 0 in every region (VDEP below capital income: S16-Hvdepk)', 'hard',
                len(si), 0, not si, 'C27; E50', '; '.join(si[:10]))
        neg = sorted(acc.index[acc['SAVE'] <= 0])
        negf = sorted(flags.loc[flags['id'] == 'NEG-SAVE', 'subject'])
        S.check('S16-Hnegsave', 'Every region with SAVE <= 0 carries flag NEG-SAVE from S14 (the GTAP eq. 7.1 residual, report-only by decision), and no flag is stale', 'hard',
                len(set(neg) ^ set(negf)), 0, neg == negf, 'model; E50 (3)', f'{len(neg)} regions with SAVE <= 0')
        sh = acc['SAVE'] / acc['Y']
        out_b = sorted(acc.index[sh.abs() > 1])
        S.check('S16-Hcarry', 'Regions whose saving share SAVE/Y is outside [-1, 1] are exactly the CARRY-SAVE regions (each must stay pooled on every map: S16-Hmapdef)', 'hard',
                len(set(out_b) ^ set(carry)), 0, out_b == carry, 'model; E50 (1)', '; '.join(f'{r} {sh[r]:.3f}' for r in out_b))
        vd = sorted(acc.index[acc['VDEP'] >= acc['I']])
        vdf = sorted(flags.loc[flags['id'] == 'CARRY-VDEP', 'subject'])
        S.check('S16-Rvdep', 'Regions with VDEP >= I (report-only as in GTAP; E28; hard for the large economies at S16-Hmacro, Fable QA E-04), against the CARRY-VDEP flags', 'report',
                len(vd), 0, vd == vdf, 'model; E28', ' '.join(vd) + ('' if vd == vdf else f' (flags: {" ".join(vdf)})'))

        # Fable QA E-03/E-04: S16-Hsave and S16-Hsixm restate eq. 7.1; the saving and macro structure against WDI 2022
        wdi_r = MX.wdi_by_region(pd.read_csv(S.inp(DATA + '/wdi/wdi_accounts.csv', 'WDI national accounts 2022 (macro structure check, Fable QA E-03)')),
                                 pd.read_csv(out('S01_sets_registry', 'regions.csv')))
        mx_exc = MX.read_exceptions(S.inp(BUILD + '/config/macro_external_exceptions.csv', 'open macro findings excepted from S16-Hmacro (Fable QA E-04)'))
        mxt, mx_fail, mx_hit = MX.compare(acc.assign(GDP_expenditure=acc['C'] + acc['G'] + acc['I'] + acc['X'] - acc['M']), wdi_r, mx_exc)
        S.check('S16-Hmacro', f'Macro structure of the HAR against WDI 2022 (Fable QA E-03, E-04; GTAP 12 ch.3, ch.7): in every large economy (at least '
                f'{MX.LARGE_SHARE:.0%} of world GDP) the trade balance and gross saving (SAVE + VDEP) over GDP are within {MX.BAND:.0%} and {MX.SAVE_BAND:.0%} '
                'of GDP of WDI, and VDEP is below I; the open findings in config/macro_external_exceptions.csv are listed, not failed', 'hard',
                len(mx_fail), 0, not mx_fail, 'C26; basis national accounts vs national accounts', MX.summary(mxt, mx_fail, mx_hit))
        S.write('macro_wdi_s16.csv', mxt.reset_index(names='region').round(9))
        # beta v4 G19 (Grok QA C4, D N8): every other region outside the trade band, in full (S16-Hmacro lists the 12 largest);
        # trace rows over 10 points (LBY, TKM: likely S11 volume x price; ARE, SGP, CHE, LUX, HKG: BoP-vs-customs concept)
        sm = mxt[(~mxt['large']) & (mxt['status_trade'] == 'report')].assign(g=lambda d: d['gap_trade'].abs()).sort_values('g', ascending=False)
        S.check('S16-Rmacrosmall', f'Beta v4 G19: regions below {MX.LARGE_SHARE:.0%} of world GDP whose trade balance is more than {MX.BAND:.0%} of GDP '
                'from WDI 2022 (points of GDP; over 10 points need a traced cause)', 'report', len(sm), 0, True, 'C26; basis national accounts',
                f'{int((sm["g"] > 0.10).sum())} over 10 points: ' + '; '.join(f'{r} {x.gap_trade:+.3f}' for r, x in sm.iterrows()))
        # Fable QA E-05: the screen explanation rows the builder wrote, for an independent reviewer's signature
        srows, s_uns, s_dis = SRV.review(SRV.builder_rows(BUILD), SRV.read_signoff(S.inp(BUILD + '/config/s16/screen_explanation_signoff.csv',
                                                                                    'reviewer sign-off of the screen explanation rows (Fable QA E-05)')))
        s_rel = os.environ.get('GTAP_RELEASE', '') == '1'
        rg = choices['release_gates']['value'] == C.RELEASE_GATES
        # beta v5 RG: builder rows dated before the cutoff are void at release (re-screen and re-date them, then sign)
        s_void = B5.stale_screen_rows(srows, C.SCREEN_CUTOFF) if rg else []
        S.check('S16-Hscreenreview', 'Screen explanation rows written by the builder (config/s10-s13/screen_explanations.csv, decided_by Claude), which clear the '
                'S10-S13 -Hscreens hits, are signed by a reviewer in config/s16/screen_explanation_signoff.csv: none disagreed, and at release '
                f'(GTAP_RELEASE=1) none unsigned and (beta v5 RG, choice release_gates) none dated before {C.SCREEN_CUTOFF} (Fable QA E-05)', 'hard',
                f'{len(srows)} rows; {s_uns} unsigned; {len(s_dis)} disagreed; {len(s_void)} dated before {C.SCREEN_CUTOFF}',
                '0 disagreed; 0 unsigned and 0 void at release', not s_dis and ((s_uns == 0 and not s_void) or not s_rel), 'reviewer sign-off',
                ('disagreed: ' + '; '.join(s_dis) + '. ' if s_dis else '') + 'By stage: ' +
                ', '.join(f'{k} {v}' for k, v in srows['stage'].value_counts().sort_index().items()) + '. The list is screen_explanations_review_s16.csv.'
                + (f' Void (before {C.SCREEN_CUTOFF}): ' + '; '.join(s_void[:20]) + (f'; and {len(s_void) - 20} more' if len(s_void) > 20 else '') if s_void else ''))
        S.write('screen_explanations_review_s16.csv', srows.assign(void_at_release=srows['date'].astype(str).str[:10] < C.SCREEN_CUTOFF) if rg else srows)

        # beta v5 TC (choice betav5_report_checks): report checks that would have caught the round-3 oddities (s16_final/betav5.py)
        if choices['betav5_report_checks']['value'] == C.BETAV5_REPORTS:
            regions_b5 = pd.read_csv(out('S01_sets_registry', 'regions.csv'))
            gdp_b5 = pd.read_csv(out('S02_macro', 'macro_regions.csv')).set_index('region')['GDP_musd'].to_dict()
            mb = B5.macro_bn(R, comm, regs, pd.read_csv(I(DATA + '/wdi_bop/wdi_bop_goods_services_2022.csv', 'WDI BoP goods and services 2022 (beta v5 TC)')), regions_b5)
            mbo = mb.assign(a=mb['nx_gap_bn'].abs()).sort_values('a', ascending=False)
            S.check('S16-Rmacrobn', 'Beta v5 TC: trade balance against WDI BoP 2022 in USD bn, goods (crp..ely) and services (the rest and VST) apart; the 15 largest gaps '
                    '(report-only; S16-Hmacro checks the large economies in points of GDP)', 'report', f'{int((mb["nx_gap_bn"].abs() > 10).sum())} regions above 10 bn', '', True,
                    'C26; basis national accounts vs BoP',
                    '; '.join(f'{r} {x.nx_gap_bn:+.1f} (goods {x.nx_goods_gap_bn:+.1f}, services {x.nx_serv_gap_bn:+.1f})' for r, x in mbo.head(15).iterrows() if np.isfinite(x.nx_gap_bn)))
            S.write('macro_bn_s16.csv', mb.reset_index().round(6))
            sv = B5.sector_vs_ama(R, comm, regs, pd.read_csv(I(DATA + '/unsd_ama/gva_gdp_current_usd.csv', 'UN AMA GVA by ISIC group (beta v5 TC)')), regions_b5, gdp_b5)
            svf = sv[sv['flag']].sort_values('gap_share_gdp', ascending=False)
            S.check('S16-Rsectorsize', f'Beta v5 TC: value added by UN AMA ISIC group against UN AMA 2022 (ratio outside 1/{B5.AMA_BAND:g}-{B5.AMA_BAND:g} and a gap above '
                    f'{B5.AMA_MIN_GDP:.0%} of GDP; report-only, AMA is ISIC rev.3 and our VA is at agents\' prices)', 'report', len(svf), 0, True, 'C14; basis national accounts vs national accounts',
                    '; '.join(f'{x.region} {x.group[4:]} {x.ratio:.2f}' for x in svf.head(30).itertuples()))
            S.write('sector_vs_ama_s16.csv', sv.round(6))
            pp = B5.power_price(R, comm, regs, pd.read_csv(out('S11_energy', 'volumes_s11.csv')))
            ppf = pp[pp['flag']].sort_values('usd_per_mwh')
            S.check('S16-Rpowerprice', f'Beta v5 TC: ely output over S11 generation in USD per MWh outside {B5.ELY_PRICE_BAND[0]:g}-{B5.ELY_PRICE_BAND[1]:g} '
                    '(report-only; ely carries gas distribution, ICIO D35)', 'report', len(ppf), 0, True, 'C06; basis value vs volume',
                    f'world {pp["ely_output_musd"].sum() / pp["generation_twh"].sum():.0f} USD/MWh; ' + '; '.join(f'{x.region} {x.usd_per_mwh:.0f}' for x in ppf.itertuples()))
            S.write('power_price_s16.csv', pp.round(6))
            ew = B5.energy_wedge(R, comm, regs)
            ewf = ew[ew['flag']].sort_values('ratio')
            S.check('S16-Renergywedge', f'Beta v5 TC (GHA/KAZ trace): energy rows where buyers pay under {B5.WEDGE_MIN:g} of the basic value across all users, '
                    f'or the net subsidy is above {B5.SUBSIDY_MAX:.0%} of output (the single-region calibration fails below about 0.10-0.20; report-only)', 'report',
                    len(ewf), 0, True, 'identity; basis purchasers vs basic',
                    '; '.join(f'{x.region} {x.good} {x.ratio:.2f} (subsidy {x.subsidy_share_output:.0%})' for x in ewf.itertuples()))
            S.write('energy_wedge_s16.csv', ew.round(6))
            mx_ = B5.metal_exports(R, comm, regs)
            S.check('S16-Rmetalx', f'Beta v5 TC (gold mirror exports, round-3 oddity 3): ore and nfm cells with exports above {B5.METAL_X_SHARE:.0%} and imports above '
                    f'{B5.METAL_M_SHARE:.0%} of output (pass-through hubs or mirror exports; report-only)', 'report', len(mx_), 0, True, 'C01; basis basic vs basic',
                    '; '.join(f'{x.region} {x.good} out {x.output_musd / 1e3:.1f} X {x.exports_musd / 1e3:.1f} M {x.imports_musd / 1e3:.1f} bn' for x in mx_.sort_values('exports_musd', ascending=False).itertuples()))
            S.write('metal_exports_s16.csv', mx_.round(6))
            af = pd.read_csv(I(f'{STAGES}/S07_trade/output/absent_pairs_filled_s07r.csv', 'S07 country pairs filled from an earlier year (P13; beta v5 TC)'))
            fr = B5.filled_routes(R, comm, regs, {(str(a).upper(), str(b).upper()) for a, b in zip(af.iloc[:, 0], af.iloc[:, 1])})
            S.check('S16-Rnonreporter', f'Beta v5 TC (package R): energy routes of at least USD {B5.ROUTE_MIN_MUSD:g} m whose country pair had no 2022 BACI row '
                    '(neither partner reported; filled from an earlier year by S07 P13; report-only)', 'report', len(fr), 0, True, 'C01; basis fob vs fob',
                    '; '.join(f'{x.good} {x.src}>{x.dst} {x.vfob_musd / 1e3:.2f} bn' for x in fr.sort_values('vfob_musd', ascending=False).itertuples()))
            br = B5.blocked_routes(R, comm, regs, T['route_blocks'])
            S.check('S16-Rrouteblock', 'Beta v5 TC (package R): routes listed in config/s16/route_blocks.csv that still carry trade (the block itself is upstream; report-only)',
                    'report', len(br), 0, br.empty, 'C01; basis fob vs fob', '; '.join(f'{x.good} {x.src}>{x.dst} {x.vfob_musd / 1e3:.2f} bn' for x in br.itertuples()))
            prev = os.environ.get('S16_PREV_RELEASE_DIR', '')
            if prev:
                pa, _, pc = read_har(S, hp, prev, tmp)
                summ, vd = B5.version_diff(R, {h: pa[h] for h, *_ in M15.DATA_HEADERS if h in pa}, comm, regs,
                                           [x.upper() for x in pc.get('REG', [])], [x.lower() for x in pc.get('COMM', [])])
                S.check('S16-Rversiondiff', f'Beta v5 TC: this data base against the previous release ({prev}): world totals, and moves of output by region and '
                        f'commodity above {B5.DIFF_REL:.0%} and USD {B5.DIFF_MUSD:g} m (report-only)', 'report', 0 if summ is None else len(vd), '', True, 'stage; version diff',
                        vd if summ is None else (f'world output {summ["world_output_bn"][0]:,.0f} -> {summ["world_output_bn"][1]:,.0f} bn; VXSB {summ["world_vxsb_bn"][0]:,.0f} -> '
                                                 f'{summ["world_vxsb_bn"][1]:,.0f}; factor income {summ["world_factor_income_bn"][0]:,.0f} -> {summ["world_factor_income_bn"][1]:,.0f}; '
                                                 'world commodities moved over 5%: ' + ', '.join(f'{c} {a:,.0f}->{b:,.0f}' for c, (a, b) in summ['world_by_commodity'].items())
                                                 + f'; {len(vd)} region cells (version_diff_s16.csv)'))
                if summ is not None:
                    S.write('version_diff_s16.csv', vd.round(6))
                pa = None
            else:
                S.check('S16-Rversiondiff', 'Beta v5 TC: version diff against the previous release not run (S16_PREV_RELEASE_DIR unset)', 'report', 'not run', '', False, 'stage; version diff')

        # trade and tariffs
        trade13 = pd.read_csv(out('S13_fit', 'trade_s13.csv.gz'))
        tmv = pd.read_csv(out('S14_final_assembly', 'trade_moves_s14.csv.gz'))
        swaps = pd.read_csv(out('S14_final_assembly', 'swapped_pairs_s14.csv'), keep_default_na=False)
        n, det = K.held_trade(R, sets, trade13, moves=tmv)
        S.check('S16-Htrade', 'Exports, imports and VST of the data base equal the trade S13 held (S08 margins, S09 services, S10 goods, S11 energy) by region and commodity (1e-6 relative), after the S14 trade moves (B14 cells below USD 1, the VCIF re-balancing, A13 swaps; each move less its swap at most USD 1,000)', 'hard',
                n, 0, n == 0, 'identity; basis basic vs basic', det)
        # the route border values S14 merged, rebuilt from the sources with the travel rows S13 held (as S14 does)
        gx, gm = pd.read_csv(out('S10_tariffs_taxes', 'vfob_s10.csv.gz')), pd.read_csv(out('S10_tariffs_taxes', 'vmsb_s10.csv.gz'))
        ex, em = pd.read_csv(out('S11_energy', 'vfob_energy_s11.csv.gz')), pd.read_csv(out('S11_energy', 'vmsb_energy_s11.csv.gz'))
        svc, trv = pd.read_csv(out('S09_services', 'vxsb_services_s09.csv.gz')), pd.read_csv(out('S09_services', 'travel_s09.csv.gz'))
        # beta v4: the targets S13 used (S11 after the P1 ely floor and P38), as S14 reads them (S16-Htariff, S16-Henergy)
        tg13 = pd.read_csv(out('S13_fit', 'energy_targets_s13.csv')).assign(target='yes')
        tout = {(r.region, r.commodity): float(r.output_value) for r in tg13.itertuples()}
        sectors = pd.read_csv(out('S01_sets_registry', 'sectors.csv'))['sector'].tolist()
        nonen = ~gx['sector'].isin(M13.ENERGY_TRADE), ~gm['sector'].isin(M13.ENERGY_TRADE)
        _, travel_used, _ = M13.assemble_trade(gx[nonen[0]], gm[nonen[1]], ex, em, svc, trv, pd.read_csv(out('S11_energy', 'vst_s11.csv')),
                                               M13.b06_split(pd.read_csv(out('S12_factors', 'io_s12.csv.gz')), sectors), tout)
        routes = M14.bilateral(gx, gm, ex, em, svc, travel_used)
        n, det, nr = K.tariff_power(R, sets, routes, small=M14.SMALL_TRADE, swaps=swaps)
        S.check('S16-Htariff', 'No rate scaling and no added value on a route: VFOB equals the route value rebuilt from S10 goods, S11 energy, S09 services and the travel S13 held (s14 bilateral), and on every route with VCIF >= USD 1,000 VMSB/VCIF equals the rebuilt power (1e-6, Float32)', 'hard',
                n, 0, n == 0, 'identity; basis fob vs fob', det or f'{len(routes)} routes rebuilt; {nr} powers tested')
        cc = pd.read_csv(out('S10_tariffs_taxes', 'customs_compare_s10.csv'))
        off = cc[(cc['booked_over_collected'] - 1).abs() > 0.25]
        S.check('S16-Rcustoms', 'Booked duty against collected customs revenue: regions outside ±25%, each with its cause (E3; report-only: GTAP 12 builds duties from applied rates times trade, not from collections)', 'report',
                f'{len(off)} of {len(cc)}; {int((off["cause"].fillna("") == "").sum())} without a cause', 0, bool((off['cause'].fillna('') != '').all()),
                'C04, C23; basis booked vs cash', '; '.join(f'{r.region} {r.booked_over_collected:.2f}' for r in off.sort_values('booked_over_collected').itertuples())[:1500])

        # energy
        led14 = pd.read_csv(UP['S14_final_assembly'] + '/adjustments_ledger.csv', keep_default_na=False, low_memory=False)
        sp15 = UP['S15_har_jls'] + '/output/household_crude_seed_s15.csv'
        seed15 = pd.read_csv(I(sp15, 'S15 household crude seed (P10 refined cut)')) if os.path.exists(sp15) else None
        n, det = K.energy_output(R, sets, tg13, ledger14=led14, rebal=rebal, seed15=seed15)
        S.check('S16-Henergy', 'Output of every energy good S13 targeted (coa, oil, gas, pet and, with energy_targets, ely; MAKB, basic prices) equals the target S13 used (energy_targets_s13.csv: the S11 value after the P1 ely floor and P38; 1e-6 relative), after the S14 output moves in its ledger (B14 sales abroad below USD 1, A13 seed and carve), the re-balancing rounding and the S15 P10 refined cut that funds the household crude seed (household_crude_seed_s15.csv, by region)', 'hard',
                n, 0, n == 0, 'identity; basis basic vs basic', det)
        vol = pd.read_csv(out('S11_energy', 'volumes_s11.csv'))
        regions = pd.read_csv(out('S01_sets_registry', 'regions.csv'))
        members = {r.region: str(r.members).split() for r in regions.itertuples()}
        eip = I(DATA + '/ei_statistical_review/EI-Stats-Review-ALL-data.xlsx', 'EI Statistical Review 2025 (volume cross-check)')
        ei = {'oil': (K.ei_production(eip, 'Oil Production - barrels'), 0.365, 'C07: EI crude, condensate and NGL in kb/d x 0.365; S11 oil excludes NGPL (E29), so EI is above by the NGL share'),
              'gas': (K.ei_production(eip, 'Gas Production - Bcm'), 1.0, 'C06: EI marketed gas, bcm'),
              'coa': (K.ei_production(eip, 'Coal Production - mt'), 1.0, 'no concept row: EI coal production, Mt (hard and brown coal) vs EIA Mt')}
        eic = K.ei_compare(vol, ei, members)
        o = eic[eic['outside_band']]
        S.check('S16-Rei', 'Production of the 15 largest producers of oil, gas and coal against EI 2022 (±8%, report-only; E6 named exceptions; oil differs by NGLs by concept)', 'report',
                f'{len(o)} of {len(eic)} outside ±8%', 0, o.empty, 'C06, C07; basis volume vs volume',
                '; '.join(f'{r.commodity} {r.region} {r.ratio:.3f}' for r in o.itertuples()))
        S.check('S16-Reiexports', 'Energy exports against EI (±10%): not run, the EI 2025 edition has bilateral trade for 2024 only (S11 choice ei_bilateral_supplement); S11 exports are checked against BACI and EIA at S11', 'report',
                'not available for 2022', '', True, 'C06, C07; basis volume vs volume')
        S.write('ei_compare_s16.csv', eic)

        # ledger
        frames = {n_: pd.read_csv(f'{STAGES}/{n_}/adjustments_ledger.csv', keep_default_na=False, low_memory=False) for n_ in STAGE_NAMES}
        n, det, led = K.ledger(frames, T['ledger_rules'])
        S.check('S16-Hledger', 'Ledger of S01-S15: every row has a rule (method ID) and a citation (source and page), every rule is on config/s16/ledger_rules.csv, and no row books an unmatched residual, a plug or a slack', 'hard',
                n, 0, n == 0, 'stage; PLAN §3(k) ledger', det or f'{int(led["rows"].sum())} rows')
        ab = led[led['absorbed_rows'] > 0]
        S.check('S16-Rabsorbed', 'Gaps the FIT absorbs under a named GTAP step (ledger rules of kind absorbed: io_s12 row and column imbalances, stock-change and G-revision gaps), rows and USD million moved', 'report',
                int(ab['absorbed_rows'].sum()), 'report', True, 'stage; GTAP 12 ch.17A', '; '.join(f'{r.stage} {r.absorbed_rows} rows {r.absorbed_musd:,.1f} USD m' for r in ab.itertuples()))
        S.write('ledger_summary_s16.csv', led)
        n, det, nm, mx = K.rounding_moves(pd.read_csv(out('S14_final_assembly', 'rebalance_s14.csv.gz')))
        S.check('S16-Hrounding', 'S14 re-balance moves (rebalance_s14) are rounding only, each at most 0.001 USD million; the S14 ledger holds only the B14, A13 and B16 rows', 'hard',
                n, 0, n == 0, 'stage; S14 spec', det or f'{nm} moves, largest {mx:.3g}')

        # QA vs GTAP (internal, report-only, outside git)
        if choices['gtap_benchmark']['value'] == 'gtap10_shares_outside_git' and os.environ.get('S16_GTAP10_DIR'):
            g10 = os.environ['S16_GTAP10_DIR']
            ga, _, gc = read_har(S, hp, g10, tmp)
            conc = pd.read_csv(I(BUILD + '/config/s01/gtap65_to_sector.csv', 'GTAP 65 sectors -> our sectors (S01)'))
            large20 = list(s02['GDP_musd'].sort_values(ascending=False).index[:20])
            tab, summ = G.full_compare(R, sets, ga, gc, conc, regions, large20)
            pdir = os.environ.get('S16_PRIVATE_DIR', '')
            if pdir:
                os.makedirs(pdir, exist_ok=True)
                with gzip.GzipFile(os.path.join(pdir, 'gtap10_compare_s16.csv.gz'), 'wb', mtime=0) as fh:
                    fh.write(tab.to_csv(index=False).encode())
            S.write('gtap10_compare_summary_s16.csv', summ)     # counts and item names only
            fl = tab[tab['flag']]
            S.check('S16-Rgtap', 'Internal QA against GTAP 10 (2014), every measure (macro ratios, tax mix, output, VA, I-O coefficients, factor shares, budgets, import shares by agent, exports, import mix and partners, tariff, margin and export tax rates, product, output, factor and income tax rates) for each single economy in both; each gap screened against the reference year (median move of that measure and item) and for materiality (item >= 1% of its base). Flagged: not explained, material, 20 largest economies, over 5 points (report-only; never an input; the table with GTAP values is written outside git)', 'report',
                    f'{len(fl)} flagged of {int(summ["material"].sum())} material rows', 'report', True, 'model; internal QA, never an input; basis basic vs basic (shares and rates)',
                    'by measure: ' + ', '.join(f'{r.measure} {r.flagged_large}' for r in summ.itertuples() if r.flagged_large)
                    + f'; table outside git: {pdir or "not written (S16_PRIVATE_DIR unset)"}'
                    + (f'; sha256 {sha256(os.path.join(pdir, "gtap10_compare_s16.csv.gz"))[:12]}' if pdir else ''))
            # product tax rates far below GTAP 10 in the large economies (IMPROVEMENTS_LOG S13-2: one rate per column)
            low = tab[(tab['measure'] == 'product_tax_rate') & tab['large_economy'] & tab['material'] & (tab['gap_pts'] < -10) & ~tab['year_explained']]
            S.check('S16-Rtaxcol', 'Product tax rates of the 20 largest economies more than 10 points below GTAP 10, material and not explained by the 2014-2022 move (fix list A1 puts the energy taxes on the energy rows from S13 on; IMPROVEMENTS_LOG S13-2)', 'report',
                    len(low), 0, low.empty, 'model; internal QA; basis basic vs basic (rates)',
                    'sectors: ' + ', '.join(f'{g} {n}' for g, n in low['item'].value_counts().items()))
            if len(low):
                S.flag('NEEDS-FIX', 'product tax rates by commodity', f'{len(low)} sector rates of the 20 largest economies are more than 10 points below GTAP 10 '
                       f'(sectors {", ".join(low["item"].value_counts().index[:8])}): each I-O column carries one net tax rate (S10 tls_split), so excise on fuel, '
                       'power and gas is spread over every product the column buys. Column totals are right.', needs_david='yes',
                       rule='upstream_fix_round', citation='IMPROVEMENTS_LOG S13-2; GTAP 12 ch.15; OECD GRS T_5121')
        else:
            S.check('S16-Rgtap', 'Internal QA against GTAP: not run (choice gtap_benchmark, or S16_GTAP10_DIR unset)', 'report', 'not run', 'report', False, 'model; report-only')

        # ------------------------------------------------------------- map suite
        dom = R['VDFB'].sum(axis=1) + R['VDPB'] + R['VDGB'] + R['VDIB']
        imp = R['VMFB'].sum(axis=1) + R['VMPB'] + R['VMGB'] + R['VMIB']
        acc_m = acc.assign(saving_share=sh)
        schemes = T['schemes'].set_index('sector')
        lst, rrows, srows, rep, gates = MP.resolve(T['maps'], schemes, acc_m, regs, comm, dom, imp, carry)
        unresolved = rep[rep['scheme'] == '']
        alone = rep[rep['carry_save_named'] != '']
        S.check('S16-Hmapdef', 'Every map resolves: on its scheme every named region buys every sector group from domestic producers wherever it buys it (no one-sided pair without an Armington donor, S15 carry-in), and no CARRY-SAVE region stands alone', 'hard',
                len(unresolved) + len(alone), 0, unresolved.empty and alone.empty, 'model; S15 spec; E50',
                '; '.join([f'{r.map}: {r.refused_schemes}' for r in unresolved.itertuples()] + [f'{r.map}: {r.carry_save_named} alone' for r in alone.itertuples()]))
        moved = rep[rep['refused_schemes'] != '']
        S.check('S16-Rmapscheme', 'Maps whose first sector scheme was refused by the one-sided pre-check, and the scheme used (choice one_sided_pairs)', 'report',
                len(moved), 0, True, 'model; S15 spec', '; '.join(f'{r.map} uses {r.scheme} ({r.refused_schemes})' for r in moved.itertuples()))
        gb, gx = MP.gate_split(pd.DataFrame(gates, columns=['map', 'group', 'SAVE', 'Y', 'sigma_save', 'sigma_qinv']), T['gate_exceptions'])
        gx_hits = gx[['map', 'group']].copy() if len(gx) else pd.DataFrame(columns=['map', 'group'])
        S.check('S16-Hmapgate', 'Pre-solve S-I gate on every map (E50): σsave = SAVE/Y and σ_qinv = SAVE/world SAVE of every group in [-1, 1], '
                'except the documented cases in config/s16/map_gate_exceptions.csv (S16-Rmapgate)', 'hard',
                len(gb), 0, gb.empty, 'model; E50; src/solve_model.jl', '; '.join(f'{r.map}: {r.group} {r.measure} {r.value:.6f}' for r in gb.itertuples()))
        S.check('S16-Rmapgate', 'Gate values past [-1, 1] accepted as documented exceptions (negative-saving limit: a map that isolates a NEG-SAVE region '
                'leaves the rest of the world saving more than world SAVE, so its σ_qinv is just above 1); each must still solve (S16-Hmaps)', 'report',
                len(gx), 0, True, 'model; E50; departure from the [-1, 1] gate, labelled',
                '; '.join(f'{r.map}: {r.group} {r.measure} {r.value:.6f}' for r in gx.itertuples()) or 'none')
        # CARRY-VDEP on each map (E28, choice vdep_vs_i): groups whose VDEP is at or above their investment
        gv = rrows.merge(acc[['VDEP', 'I']], left_on='region', right_index=True).groupby(['map', 'group'])[['VDEP', 'I']].sum()
        gv = gv[gv['VDEP'] >= gv['I']]
        S.check('S16-Rvdepmaps', 'Region groups with VDEP >= I on each map (CARRY-VDEP carried to the maps; report-only as in GTAP, E28)', 'report',
                len(gv), 0, gv.empty, 'model; E28', '; '.join(f'{m_} {g_}' for m_, g_ in gv.index[:40]))
        mapdir = os.path.join(tmp, 'maps')
        os.makedirs(mapdir)
        lst.to_csv(os.path.join(mapdir, 'maps_list.csv'), index=False)
        rrows.assign(region=rrows['region'].str.lower()).to_csv(os.path.join(mapdir, 'maps_regions.csv'), index=False)
        srows.to_csv(os.path.join(mapdir, 'maps_sectors.csv'), index=False)
        S.write('maps_resolved_s16.csv', rep)
        S.write('map_gate_s16.csv', gates)
        with gzip.GzipFile(f'{S.out}/maps_regions_s16.csv.gz', 'wb', mtime=0) as fh:
            fh.write(rrows.to_csv(index=False).encode())
        S.write('maps_sectors_s16.csv', srows)

        # free the data base and source tables before the suite (the Julia processes need the memory)
        arrays = R = io13 = rebal = frames = gx = gm = ex = em = svc = trv = routes = travel_used = prov = trade13 = dom = imp = None
        ga = tab = None
        _gc.collect()
        julia = os.environ.get('S15_JULIA', 'julia')
        jv = subprocess.run([julia, '--version'], capture_output=True, text=True).stdout.strip()
        S.log(f'julia: {jv}')
        size = {r.map: r.n_regions for r in rep.itertuples() if r.scheme}
        only = [m for m in os.environ.get('S16_ONLY_MAPS', '').split(',') if m]
        S.check('S16-Hfullsuite', 'The whole map suite runs (S16_ONLY_MAPS, a development switch, is unset)', 'hard',
                len(only) or 'all', 'all', not only, 'repo', ' '.join(only))
        if only:
            size = {m: v for m, v in size.items() if m in only}
        lines = run_suite(S, julia, mapdir, size, int(os.environ.get('S16_JOBS', '3')),
                          int(os.environ.get('S16_HEAVY_REGIONS', '10')), tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    open(f'{S.out}/map_suite_s16.txt', 'w').write('\n'.join(lines) + '\n')
    res = K.map_results(lines, list(size))
    S.write('map_results_s16.csv', res)
    failed, excused = MP.failure_split(res, T['map_exceptions'])
    S.check('S16-Hmaps', f'GTAPv7-Julia on every map ({len(res)}): aggregate, prepare, calibrate, solve unshocked (qo moves <= 1e-6), solve with every nominal variable x 1.1 (prices x 1.1 and quantities unchanged within 1e-6; psave equal to the package\'s own e_psave), and the smoke-map tariff shock (qxs falls, Walras gap <= 1e-6). Each solve solved and feasible, except the documented model-limit failures in config/s16/map_failure_exceptions.csv (S16-Rmapexcept)', 'hard',
            f'{len(res) - len(failed) - len(excused)} of {len(res)} PASS; {len(excused)} excepted', f'{len(res)} PASS', failed.empty, 'model; PLAN §4; READINESS §1 S16',
            '; '.join(f'{r.map}: {getattr(r, "error", "") or r.status}' for r in failed.itertuples()))
    S.check('S16-Rmapexcept', 'Maps that fail with exactly the error a reviewed, dated entry of config/s16/map_failure_exceptions.csv accepts (model-limit failures: aggregation_B, alone_ken; beta v4 S16 2026-10-27)', 'report',
            len(excused), 0, True, 'model; config/s16/map_failure_exceptions.csv',
            '; '.join(f'{r.map}: {getattr(r, "error", "")}' for r in excused.itertuples()))
    # beta v5 RG (choice release_gates): waivers that no longer excuse anything, and the release run itself
    rg = choices['release_gates']['value'] == C.RELEASE_GATES
    rel = B5.release_mode()
    stale = B5.stale_waivers(T['map_exceptions'], res, T['gate_exceptions'], gx_hits) if rg else []
    S.check('S16-Hwaivers', 'Beta v5 RG: every map failure exception still matches a failing map and every map gate exception a gate value past [-1, 1] '
            '(a stale waiver fails at release, GTAP_RELEASE=1; a NOTE otherwise)', B5.release_kind(rg, rel), len(stale), 0, not stale,
            'repo; config/s16 exceptions', '; '.join(stale) or 'none')
    S.check('S16-Hrelease', 'Beta v5 RG: this S16 run is a release run (GTAP_RELEASE=1, so S16-Grepro and the sign-off are hard); tools/release_gate.py refuses '
            'to release a data base whose S16 did not pass this check', B5.release_kind(rg, rel), 'GTAP_RELEASE=1' if rel else 'not a release run',
            'GTAP_RELEASE=1', rel, 'repo; release gate', 'A non-release run is a NOTE here and the release gate stops on it.' if rg and not rel else '')
    if 'homogeneity_psave_sum_w' in res:
        hw = pd.to_numeric(res['homogeneity_psave_sum_w'], errors='coerce')
        rmin = pd.to_numeric(res['homogeneity_psave_ratio_min'], errors='coerce')
        S.check('S16-Rpsave', 'psave under the numeraire x 1.1: the package\'s e_psave moves psave off x 1.1 unless Σw = 0 (the check predicts the move by a fixed point), Σw = (world net investment - world qsave) / world net investment in model quantities (S15 QA N7; not the data base)', 'report',
                f'Σw from {hw.min():.3g} to {hw.max():.3g}; psave ratio from {rmin.min():.7f}', '1.1', True, 'model; build_model!.jl e_psave',
                '; '.join(f'{r.map} Σw {float(r.homogeneity_psave_sum_w):.3g}' for r in res.itertuples() if isinstance(r.homogeneity_psave_sum_w, str)))

    # ------------------------------------------------------------- concepts, private files
    n, det = K.concept_tags(S.checks)
    S.check('S16-Hconcepts', 'Every S16 check names its concept (C01-C30 for a comparison of two sources, else identity, sign, model, stage or repo), and no hard check compares two price bases', 'hard',
            n, 0, n == 0, 'repo; decision 10; concepts.md', det)
    tracked = subprocess.run(['git', '-C', BUILD, 'ls-files', '--full-name', ROOT.rsplit('/', 1)[0]], capture_output=True, text=True).stdout.split()
    priv = private_paths(tracked)
    S.check('S16-Hprivate', 'No private file (credentials, GTAP database values) is tracked in git (lib/private_files.py)', 'hard',
            len(priv), 0, not priv, 'repo; committed_data_rule', ' '.join(priv[:10]))
    sec = secret_scan([BUILD + '/s16_final_checks.py', BUILD + '/s16_final', C.CONFIG_DIR])
    S.check('S16-Hsecret', 'Key and password scan of the S16 code and config (count only)', 'hard', sec, 0, sec == 0, 'repo; never commit credentials')
    S.finish()


if __name__ == '__main__':
    main()
