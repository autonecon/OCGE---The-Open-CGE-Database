#!/usr/bin/env python3
"""S15 HAR and JLS in the GTAPv7 layout (PLAN §3(j); READINESS §1 S15 gate).

The S14 header tables become the three GEMPACK HAR files the Julia GTAPv7 model reads (gsdfset.har,
gsdfpar.har, gsdfdat.har; notes/model_requirements.md §1) and a JLS copy. No data value changes. The
parameter file follows GTAP 12 ch.16 by default, GTAP 7 ch.14 as the alternative (choice parameters;
s15_har/params.py). The gate:
  - an independent reader (harpy) reads every header back with the expected dimensions and the Float32 values
    of the S14 tables, and the model identities hold to 1e-6 on those values (PLAN §3(i), §3(j));
  - the Julia check (s15_har/julia/model_check.jl) reads the files with HeaderArrayFile, compares the JLS with
    the HAR, and aggregates, calibrates and solves the smoke map in GlobalTradeAnalysisProjectModelV7;
  - the saving and investment shares of every group of the smoke map are inside [-1, 1] (E50, CARRY-SAVE).
Choices come from config/s15/s15_choices.csv (s15_har/config.py).

Environment: S15_HARPY_PYTHON is the python of an environment with requirements-s15-reader.txt; S15_JULIA is
the julia 1.12 binary (default `julia`), run with --project=s15_har/julia (Manifest.toml pins the packages).
"""
import gzip
import os
import shutil
import subprocess
import sys
import tempfile

# One BLAS thread, set before numpy loads, so sums do not depend on the machine's thread count (Grok QA N1).
for _v in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_v, '1')

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.stagekit import Stage, ROOT, BUILD, STAGES  # noqa: E402
from lib.private_files import private_paths  # noqa: E402
from s12_factors.checks import secret_scan  # noqa: E402
from s14_assembly.checks import chain  # noqa: E402
from s15_har import config as C  # noqa: E402
from s15_har import method as M  # noqa: E402
from s15_har import params as P  # noqa: E402
from s15_har import checks as K  # noqa: E402

UP = {'S01': STAGES + '/S01_sets_registry', 'S14': STAGES + '/S14_final_assembly'}
JULIA_DIR = os.path.join(BUILD, 's15_har', 'julia')
FLOAT = '%.12g'


CDE_LARGE_SHARE = 0.01     # large economy: at least 1% of world GDP (as lib/macro_external.LARGE_SHARE)
CDE_LARGE_INCOME = 0.06    # largest income gap in a large economy (KOR 0.052 at the 2026-10-25 data)
CDE_LARGE_OWN = 0.05       # largest compensated own-price gap (AUS 0.036)


def listed_upstreams(stage_dir):
    p = stage_dir + '/STAMP'
    out = {}
    if os.path.exists(p):
        for line in open(p).read().splitlines():
            if line.startswith('upstream '):
                parts = line.split()
                out[parts[1]] = parts[-1]
    return out


def gzcsv(S, name, df):
    with gzip.GzipFile(f'{S.out}/{name}', 'wb', mtime=0) as fh:
        fh.write(df.to_csv(index=False, float_format=FLOAT).encode())
    S.log(f'output {name}: {len(df)} rows')


def read_back(S, harpy_python, tmp):
    """harpy dump of the three files: ({header: array}, {header: shape}, {set: elements})."""
    dump = os.path.join(tmp, 'harpy')
    r = subprocess.run([harpy_python, '-I', os.path.join(BUILD, 's15_har', 'read_har.py'), S.out, dump], capture_output=True, text=True)
    S.log(f'harpy: {r.stdout.strip()} {r.stderr.strip()[-300:]}')
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


def main():
    choices = C.load_choices()
    S = Stage('S15', 'har_jls')
    I = S.inp
    S.check('S15-Hconfig', f'config/s15/s15_choices.csv has the {len(C.CHOICES)} choices this code implements, each with decided_by and decided_at',
            'hard', len(choices), len(C.CHOICES), len(choices) == len(C.CHOICES), 's15_choices',
            'Choices not in the GTAP text: ' + ', '.join(k for k, r in choices.items() if r['gtap_status'] in ('departure_logged', 'not_in_gtap_text')))
    pins = dict(l.split('==') for l in open(os.path.join(BUILD, 'requirements-s15-build.txt')).read().split('\n') if '==' in l and not l.startswith('#'))
    used = {'numpy': np.__version__, 'pandas': pd.__version__}
    S.check('S15-Renv', 'Python packages of the build against requirements-s15-build.txt (a different numpy or pandas can move a last bit of the Float64 JLS copy; the Float32 HAR does not move)', 'report',
            '; '.join(f'{k} {v}' for k, v in used.items()), '; '.join(f'{k} {pins.get(k)}' for k in used), all(pins.get(k) == v for k, v in used.items()),
            'Grok QA N1')
    for k in UP.values():
        S.upstream(k)
    I(C.CHOICES_PATH, 'S15 choices')
    T = {k: C.load_table(k) for k in C.TABLES}
    for k in C.TABLES:
        I(C.table_path(k), f'S15 config {C.TABLES[k][0]}')
    for f in ('Project.toml', 'Manifest.toml', 'write_jls.jl', 'model_check.jl', 'prepare_for_solve.jl'):
        I(os.path.join(JULIA_DIR, f), f'S15 Julia {f}')

    regions = pd.read_csv(I(UP['S01'] + '/output/regions.csv', 'S01 regions (single or composite)'))
    tables = {k: pd.read_csv(I(UP['S14'] + '/output/' + fn, f'S14 {k}')) for k, fn in M.TABLE_FILES.items()}
    sets = M.read_sets(pd.read_csv(I(UP['S14'] + '/output/sets_s14.csv', 'S14 sets')))
    sums = {u['name']: (u['actual_sums'], listed_upstreams(p)) for p, u in S.upstreams.items()}
    n, det = chain(sums)
    S.check('S15-Hchain', 'Each upstream read here is the one the other upstreams were stamped on (SHA256SUMS listed in their STAMPs)', 'hard',
            n, 0, n == 0, 'P7; 17B p.5-6 staged hand-off', det)
    s14sum = S.upstreams[UP['S14']]['actual_sums']
    drel = ['ocge_gtapv7', 'y2022', f's14_{s14sum[:8]}']
    regs, comm = sets['REG'], sets['COMM']

    # ------------------------------------------------------------- data arrays
    D = M.data_arrays(tables, sets)
    n, det = K.dense_totals(D, tables, M.DATA_HEADERS)
    S.check('S15-Hdense', 'Each of the 31 dense arrays sums to its S14 long table and has the same number of non-zero cells', 'hard',
            n, 0, n == 0, 'no value changes at S15', det)

    # beta v4 P10 (choice household_crude_seed, David's call; default off): households that buy no crude get a 1e-7 seed so the
    # CDE has no zero cell (the Julia model takes logs of qpa); offset by the refinery's crude and households' refined product
    if choices['household_crude_seed']['value'] == C.HOUSEHOLD_CRUDE_SEED:
        seed_rows = M.seed_household_crude(D, comm, sets['ACTS'], regs, top_up=choices['household_crude_top_up']['value'] == C.HOUSEHOLD_CRUDE_TOP_UP)
        done = [x for x in seed_rows if x['status'] == 'seeded']
        S.check('S15-Rhhseed', 'Beta v4 P10 (household_crude_seed; our choice, GTAP 12 has no zero-cell rule): households with no crude get '
                f'{M.HH_SEED_SHARE:g} of their spending at zero tax, offset by the refinery\'s crude and households\' refined product (SAVE '
                'unchanged; S15-Hidentities and S15-Hsave re-check the identities on the written values)', 'report',
                f'{len(done)} seeded; {len(seed_rows) - len(done)} skipped', '', True, 'household_crude_seed',
                '; '.join(f'{x["region"]} {x["status"]}' for x in seed_rows if x['status'] != 'seeded')[:1200])
        S.write('household_crude_seed_s15.csv', pd.DataFrame(seed_rows, columns=['region', 'source', 'eps', 'refined_basic_cut', 'status']))

    # ------------------------------------------------------------- parameters (GTAP 12 ch.16 by default; GTAP 7 ch.14)
    ed, ptable, smap, targets, trows = C.edition_tables(choices, T)
    S.log(f'parameters: {ed["label"]} ({choices["parameters"]["value"]})')
    el = P.sector_elasticities(smap, ptable)
    if sorted(el.index) != sorted(comm):
        raise SystemExit(f'{C.TABLES[ed["sector_map"]][0]} does not list exactly the S14 sectors')
    rows = P.target_regions(regions, targets, trows, ed['aliases'])
    hh = D['VDPP'] + D['VMPP']
    reading = {'table_16_7_compensated_as_titled': 'compensated', 'table_14_6_as_compensated': 'compensated'}[choices['cde_price_reading']['value']]
    incp, subp, cde = P.calibrate_cde(hh, comm, el.loc[comm, 'cde_category'].tolist(), regs, rows, targets, reading)
    par, rdlt = M.parameter_arrays(sets, el, T['scalars'], incp, subp)
    n, det = K.parameters(par, sets)
    S.check('S15-Hparams', 'Parameter ranges the model needs (elasticities > 0, SUBP in (0, 1], INCP > 0, one mobility type per factor, capital mobile, sluggish ETRE < 0)', 'hard',
            n, 0, n == 0, f'{ed["label"]}; model_requirements §1c', det)
    n, det = K.incp_floor(incp, P.INCP_FLOOR)
    fl = cde[cde['incp_floored']]
    S.check('S15-Hincpfloor', f'INCP at least {P.INCP_FLOOR:g} after normalisation (fix list A11; our choice, no GTAP rule)', 'hard',
            n, 0, n == 0, 'incp_floor; fix list A11',
            det or (f'{len(fl)} category cells floored: ' + ', '.join(f'{r.region} {r.category}' for r in fl.head(30).itertuples())))

    # ------------------------------------------------------------- write HAR, bundle, JLS
    paths = M.write_har(S.out, sets, D, par, rdlt, drel)
    for k, p in paths.items():
        S.log(f'output {os.path.basename(p)}: {os.path.getsize(p)} bytes')
    tmp = tempfile.mkdtemp(prefix='s15_')
    try:
        M.write_bundle(os.path.join(tmp, 'bundle'), sets, D, par, rdlt, drel)
        julia = os.environ.get('S15_JULIA', 'julia')
        jv = subprocess.run([julia, '--version'], capture_output=True, text=True).stdout.strip()
        S.log(f'julia: {jv}')
        r = subprocess.run([julia, '--startup-file=no', os.path.join(JULIA_DIR, 'write_jls.jl'), os.path.join(tmp, 'bundle'), f'{S.out}/gtap_s15.jls.gz'],
                           capture_output=True, text=True)
        S.log(f'write_jls: {r.stdout.strip()} {r.stderr.strip()[-300:]}')
        S.check('S15-Hjls', 'The JLS copy is written by Julia 1.12 (Serialization, gzip -9 -n)', 'hard', r.returncode, 0,
                r.returncode == 0 and jv.startswith('julia version 1.12'), 'PLAN §3(j) pin Julia 1.12', jv)

        # ------------------------------------------------------------- read back (harpy) and check
        hp = os.environ.get('S15_HARPY_PYTHON', '')
        if not hp:
            raise SystemExit('S15_HARPY_PYTHON is not set (requirements-s15-reader.txt)')
        arrays, shapes, chars = read_back(S, hp, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    exp = M.expected_dims(sets)
    n, det = K.dims(shapes, exp)
    S.check('S15-Hdims', 'harpy reads every header of the three files with the expected dimensions, and no other header', 'hard',
            n, 0, n == 0, 'PLAN §3(j) checks; model_requirements §1', det)
    n, det = K.sets_match({k: chars.get(k, []) for k in sets}, sets)
    S.check('S15-Hsets', 'Set elements as read back equal the S14 sets (lower case, same order), ACTS = COMM', 'hard',
            n, 0, n == 0 and sets['ACTS'] == sets['COMM'], 'model_requirements §1a', det)
    src = dict(D)
    src.update(par)
    n, det = K.float32_match(arrays, src)
    S.check('S15-Hfloat32', 'Every cell read back equals the Float64 source rounded to Float32 (relative gap <= 1.2e-7 of max(1, |value|))', 'hard',
            n, 0, n == 0, 'PLAN §3(j) round trip', det)
    R = {h: arrays[h] for h in D}
    marg_idx = [comm.index(m) for m in sets['MARG']]
    n, det = K.identities(R, marg_idx, regs, comm)
    S.check('S15-Hidentities', 'On the Float32 values: VCIF = VFOB + VTWR, world VST = VTWR, market clearing, import clearing, zero profit (1e-6 relative)', 'hard',
            n, 0, n == 0, 'PLAN §3(i) tolerances; model identities 1, 3, 4, 6, 7', det)
    acc = M.regional_accounts(R, sets['ENDW'].index('capital'))
    acc.index = regs
    n, det = K.saving(acc)
    S.check('S15-Hsave', 'On the Float32 values: SAVE = Y - C - G in every region and world SAVE = world (I - VDEP) (1e-6 relative)', 'hard',
            n, 0, n == 0, 'GTAP 12 ch.7 eq. 7.1; model identities 10, 11', det)
    n, det = K.signs(R)
    S.check('S15-Hsign', 'On the Float32 values: no negative cell in any header except SAVE', 'hard', n, 0, n == 0, 'PLAN §3(k) signs', det)
    n, det = K.factor_payment(R, regs, comm)
    S.check('S15-Hevfp', 'On the Float32 values: every activity with output has EVFP > 0', 'hard', n, 0, n == 0, 'model identity 8', det)
    if int(arrays['RDLT'].ravel()[0]) != rdlt:
        S.check('S15-Hrdlt', 'RDLT reads back', 'hard', int(arrays['RDLT'].ravel()[0]), rdlt, False, 'GTAP 12 ch.16.D; GTAP 7 ch.14.4')

    # ------------------------------------------------------------- smoke map: pre-solve S-I gate (E50)
    groups = M.map_groups(regs, T['smoke_regions'])
    gate = M.map_saving_gate(acc, regs, groups)
    n, det = K.map_gate(gate)
    S.check('S15-Hmapsave', 'Smoke map: the saving share SAVE/Y and the investment share SAVE/world SAVE of every group are in [-1, 1] (Julia σsave, σ_qinv)', 'hard',
            n, 0, n == 0, 'E50; src/solve_model.jl', det or '; '.join(f'{g} {r.sigma_save:.3f}/{r.sigma_qinv:.3f}' for g, r in gate.iterrows()))
    flags = pd.read_csv(I(UP['S14'] + '/flags.csv', 'S14 flags (CARRY-SAVE)'))
    carry = sorted(flags.loc[flags['id'] == 'CARRY-SAVE', 'subject'])
    where = {r: g for r, g in zip(regs, groups)}
    alone = [r for r in carry if sum(1 for g in groups if g == where[r]) == 1]
    S.check('S15-Rcarry', 'CARRY-SAVE regions (S14) on the smoke map: each sits in a pooled group (a region alone would need its own bound)', 'report',
            len(alone), 0, True, 'E50 CARRY-SAVE', '; '.join(f'{r} in {where[r]}' for r in carry))
    for r in carry:
        S.flag('CARRY-SAVE', r, f'smoke map group {where[r]}: σsave {gate.loc[where[r], "sigma_save"]:.3f}; still to be checked on every S16 map', rule='hard_on_each_map')

    # ------------------------------------------------------------- report-only checks
    rep = cde.dropna(subset=['eta_model'])
    eg = (rep['eta_model'] - rep['eta_scaled']).abs()
    cg = (rep['comp_model'] - rep['comp_target']).abs()
    meth = cde.groupby('region')['method'].first()
    worst = rep.assign(cg=cg).groupby('region')['cg'].max().sort_values(ascending=False)
    S.check('S15-Rcde', 'CDE fit: largest gaps to the income targets (Engel-scaled) and to the compensated own-price targets; regions fitted exactly or inside the bounds', 'report',
            f'income {eg.max():.2e}; own-price {cg.max():.3f}; exact {int((meth == "exact").sum())}, sequential {int((meth == "sequential").sum())}', '',
            True, f'{ed["label"]} CDE calibration, fuzzy constraints (ch.16.E.1; ch.14.6)', 'largest own-price gaps: ' + '; '.join(f'{r} {v:.3f}' for r, v in worst.head(10).items()))
    # Fable QA E-04: in the large economies (at least 1% of world GDP, S14 accounts) the CDE fit must stay close to its targets
    acc14 = pd.read_csv(I(UP['S14'] + '/output/accounts_s14.csv', 'S14 regional accounts (GDP shares for S15-Hcdelarge)')).set_index('region')['GDP_expenditure']
    big = acc14.index[acc14 / acc14.sum() >= CDE_LARGE_SHARE]
    gb = rep.assign(eg=eg, cg=cg).groupby('region')[['eg', 'cg']].max().reindex(big).dropna()
    badb = gb[(gb['eg'] > CDE_LARGE_INCOME) | (gb['cg'] > CDE_LARGE_OWN)]
    S.check('S15-Hcdelarge', f'CDE fit in the large economies (at least {CDE_LARGE_SHARE:.0%} of world GDP): income gap at most {CDE_LARGE_INCOME} and compensated '
            f'own-price gap at most {CDE_LARGE_OWN} in every category (Fable QA E-04; the fuzzy constraints of ch.16.E.1 bound the miss, they do not remove it)', 'hard',
            len(badb), 0, badb.empty, f'{ed["label"]} CDE calibration (ch.16.E.1; ch.14.6)',
            f'{len(gb)} large economies; worst income {gb["eg"].max():.3f} ({gb["eg"].idxmax()}), own-price {gb["cg"].max():.3f} ({gb["cg"].idxmax()}). '
            + ' '.join(f'{r} {x.eg:.3f}/{x.cg:.3f}' for r, x in badb.iterrows()))
    eng = cde.groupby('region')['engel_factor'].first()
    S.check('S15-Rengel', 'Engel factor sum(s x eta target) on 2022 shares before scaling (1 means the published targets already aggregate to 1 on these shares)', 'report',
            f'min {eng.min():.3f} ({eng.idxmin()}), max {eng.max():.3f} ({eng.idxmax()})', '', True, ed['label'])
    S.check('S15-Rtargets', f'CDE target rows ({ed["label"]}): regions with their own row, a GTAP composite row, or the mean of member rows', 'report',
            '; '.join(f'{k} {v}' for k, v in rows['rule'].value_counts().items()), '', True, C.TABLES[ed['rows']][0])
    nb = int(((cde['incpar'] <= P.INCP_FLOOR * 1.0001) | (cde['subpar'] <= 1e-6 * 1.0001) | (cde['subpar'] >= 1 - 1e-6 * 1.0001)).sum())
    S.check('S15-Rbounds', 'CDE category cells at a bound (INCP at the floor, SUBP at 1e-6 or 1 - 1e-6) and regions fitted inside the bounds (fix list B6)', 'report',
            f'{nb} cells; INCP < 0.05 in {int((cde["incpar"] < 0.05).sum())}', '', True, 'fix list B6; IMPROVEMENTS_LOG S15-4')
    S.check('S15-Rsizes', 'File sizes, bytes', 'report', '; '.join(f'{os.path.basename(p)} {os.path.getsize(p)}' for p in list(paths.values()) + [f'{S.out}/gtap_s15.jls.gz']),
            '< 100 MB each (GitHub)', True, 'repo rule')
    imp = (D['VMFB'].sum(axis=1) + D['VMPB'] + D['VMGB'] + D['VMIB'])
    nosrc = int(((imp > 0) & ~(D['VMSB'] > 0).any(axis=1)).sum())
    noimp = int(((D['VMSB'].sum(axis=1) == 0)).sum())
    S.check('S15-Rnosource', 'Commodity-destination pairs with no positive import source (model_requirements §1d item 13; the aggregation must give each a source)', 'report',
            f'{noimp} pairs with no source; {nosrc} of them with import demand', '', True, 'model_requirements §1d item 13')

    one = []
    for lab, d, m in (('firm', 'VDFB', 'VMFB'), ('household', 'VDPB', 'VMPB'), ('government', 'VDGB', 'VMGB'), ('investment', 'VDIB', 'VMIB')):
        one.append(f'{lab} domestic only {int(((D[d] > 0) & (D[m] <= 0)).sum())}, imported only {int(((D[d] <= 0) & (D[m] > 0)).sum())}')
    zvst = D['VST'] <= 0
    S.check('S15-Rprep', 'One-sided Armington agents, which the Julia levels model cannot take as they stand (log of zero) and which are prepared in memory on each map (choice model_run_prep). GTAP 10 has none', 'report',
            '; '.join(one), '0 (GTAP)', True, 'model_requirements §1d; IMPROVEMENTS_LOG S15-1')
    S.check('S15-Hvst', 'Every region supplies every margin (VST > 0), as in GTAP 10; the Julia levels model takes log of qst (S08 spec §7)', 'hard',
            f'VST = 0 in {int(zvst.sum())} margin-region cells ({int(zvst.any(axis=0).sum())} regions)', 0, not zvst.any(),
            'IMPROVEMENTS_LOG S15-2', 'regions: ' + ' '.join(r for r, z in zip(regs, zvst.any(axis=0)) if z))

    # ------------------------------------------------------------- Julia: load and smoke-map solve
    res = f'{S.out}/model_check_s15.txt'
    env = dict(os.environ, JULIA_PROJECT=JULIA_DIR)
    r = subprocess.run([julia, '--startup-file=no', f'--project={JULIA_DIR}', os.path.join(JULIA_DIR, 'model_check.jl'), S.out,
                        os.path.join(C.CONFIG_DIR, 'maps'), res], capture_output=True, text=True, env=env)
    for line in r.stdout.splitlines():
        if line.startswith(('smoke.', 'jls.', 'status', 'package', 'julia', 'order')):
            S.log('model_check: ' + line)
    if r.returncode and r.stderr:
        S.log('model_check stderr: ' + r.stderr.strip()[-1500:])
    lines = dict(l.split('=', 1) for l in open(res).read().splitlines()) if os.path.exists(res) else {}
    S.check('S15-Hjulia', 'GTAPv7-Julia: HeaderArrayFile reads the three files, the JLS equals the HAR within Float32, and the smoke map aggregates, calibrates, solves unshocked (qo moves <= 1e-6), and solves a 5% tariff shock on mfr from the rest to USA (qxs falls, Walras gap <= 1e-6)', 'hard',
            lines.get('status', 'did not run'), 'PASS', lines.get('status') == 'PASS' and r.returncode == 0, 'READINESS §1 S15 gate',
            '; '.join(f'{k} {v}' for k, v in lines.items() if k.startswith(('smoke.', 'jls.'))))

    # ------------------------------------------------------------- reports
    S.write('parameters_by_sector_s15.csv', el.reset_index())
    S.write('cde_target_rows_s15.csv', rows.reset_index())
    gzcsv(S, 'cde_calibration_s15.csv.gz', cde)
    S.write('smoke_map_gate_s15.csv', gate.reset_index())
    tracked = subprocess.run(['git', '-C', BUILD, 'ls-files', '--full-name', ROOT.rsplit('/', 1)[0]], capture_output=True, text=True).stdout.split()
    priv = private_paths(tracked)
    S.check('S15-Hprivate', 'No private file (credentials, GTAP database values) is tracked in git (lib/private_files.py)', 'hard',
            len(priv), 0, not priv, 'repo_rules committed_data_rule', ' '.join(priv[:10]))
    sec = secret_scan([BUILD + '/s15_har_jls.py', BUILD + '/s15_har', C.CONFIG_DIR])
    S.check('S15-Hsecret', 'Key and password scan of the S15 code and config (count only)', 'hard', sec, 0, sec == 0, 'never commit credentials')
    with open(S.out + '/NOT_FOR_PUBLICATION.md', 'w') as f:
        f.write('# Not for publication\n\nThe S15 HAR and JLS files carry the S10 tariff wedge (TRAINS-derived) in VMSB and in the purchaser '
                'values, as the S14 tables do. Keep them out of any public release.\n\n'
                '## Solving with stock GTAPv7-Julia\n\nThe data base keeps one-sided Armington agents (an agent that buys a commodity only domestically or '
                'only from imports), which the Julia levels model cannot take (log of zero). Run `s15_har/julia/prepare_for_solve.jl` '
                '(`armington_swap!`) on each aggregated data base before calibration, as `model_check.jl` does, or use a map with no such cells.\n')
    S.finish()


if __name__ == '__main__':
    main()
