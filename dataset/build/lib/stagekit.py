"""Stage snapshot kit (GTAP 12 ch.17B pp.1-3, 5-7: staged pipeline, staging dirs, STAMP).
Each stage writes dataset/stages/<Snn_name>/ with output/ + SHA256SUMS, checks.json/.md,
adjustments_ledger.csv, flags.csv, build.log (UTC+7), inputs.lock, and STAMP only if no hard FAIL."""
import os, csv, json, hashlib, shutil, subprocess, datetime
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # dataset/ (this file is dataset/build/lib/stagekit.py)
DATA = ROOT + '/data'
BUILD = ROOT + '/build'
# Base year is a parameter (David 2026-10-20 19:29: a 2017 validation build runs through the same stages).
# Set GTAP_BASE_YEAR=2017 to build 2017; its snapshots go to stages_2017/ so the 2022 snapshots are never touched.
BASE_YEAR = int(os.environ.get('GTAP_BASE_YEAR', '2022'))
STAGES = ROOT + '/stages' if BASE_YEAR == 2022 else ROOT + f'/stages_{BASE_YEAR}'
# Code smoke tests only: GTAP_STAGES_DIR points the snapshots at a scratch folder (never used for a real build).
STAGES = os.environ.get('GTAP_STAGES_DIR', STAGES)
SOURCE_YEARS = BUILD + '/config/source_years.csv'
# Fable QA E-03: checks that recompute the stage's own expression or re-check a constraint the stage imposed are code
# guards, not data checks. A hard check listed in config/check_guards.csv is recorded as kind 'guard': it still stops
# the STAMP when it fails, and checks.md counts it apart from the hard data checks.
GUARDS_PATH = BUILD + '/config/check_guards.csv'
GUARDS = {r['check_id']: r for r in csv.DictReader(open(GUARDS_PATH))} if os.path.exists(GUARDS_PATH) else {}

class InputError(RuntimeError):
    pass
TZ = datetime.timezone(datetime.timedelta(hours=7))

def now():
    return datetime.datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S UTC+7')

def sha256(path, buf=1 << 22):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(buf)
            if not b: break
            h.update(b)
    return h.hexdigest()

def git_state():
    head = subprocess.run(['git', '-C', BUILD, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(['git', '-C', BUILD, 'status', '--porcelain', '--', '.'], capture_output=True, text=True).stdout.strip()   # build code only, also when build/ sits inside a larger repo
    return head, dirty

class Stage:
    def __init__(self, sid, name):
        self.sid, self.name = sid, name
        self.dir = f'{STAGES}/{sid}_{name}'
        self.out = self.dir + '/output'
        self.archived = None
        if os.path.isdir(self.dir):
            # Archive the previous snapshot instead of deleting it (review S01-M1): stages/<Snn>/archive/<timestamp>/
            # S10_REBUILD_HANDOFF.md is a tracked note. A stage run must not archive it away.
            keep = {'archive', 'S10_REBUILD_HANDOFF.md'}
            old = [f for f in os.listdir(self.dir) if f not in keep]
            if old:
                ts = datetime.datetime.now(TZ).strftime('%Y%m%d-%H%M%S')
                dest, n = f'{self.dir}/archive/{ts}', 1
                while os.path.exists(dest):   # review FR-L5(a): two runs in one clock second
                    n += 1; dest = f'{self.dir}/archive/{ts}-{n}'
                os.makedirs(dest)
                for f in old:
                    shutil.move(f'{self.dir}/{f}', f'{dest}/{f}')
                self.archived = dest
        os.makedirs(self.out)
        self.logf = open(self.dir + '/build.log', 'w')
        self.checks, self.ledger, self.flags, self.inputs = [], [], [], {}
        head, dirty = git_state()
        self.head = head
        self.log(f'stage {sid}_{name} start; base year {BASE_YEAR}; build commit {head}')
        if self.archived:
            self.log(f'previous snapshot archived to {self.archived}')
        self._years = {}
        if os.path.exists(SOURCE_YEARS):
            for r in csv.DictReader(open(SOURCE_YEARS)):
                if int(r['base_year']) == BASE_YEAR:
                    self._years[r['source_folder']] = r
        if dirty:
            self.log('WARNING: build repo has uncommitted changes:\n' + dirty)
        self._manifest = {}
        mp = DATA + '/MANIFEST.csv'
        if os.path.exists(mp):
            for r in csv.DictReader(open(mp)):
                self._manifest[r['path']] = r['sha256']
        self.dirty = bool(dirty)
        self.upstreams = {}
        self.in1_exempt = set()

    def upstream(self, path):
        """Declare an upstream stage snapshot this stage reads (review FR-M2). Reads its STAMP and output/SHA256SUMS.
        At finish(), hard check <sid>-G0 requires the STAMP and that every file this stage read from <path>/output
        has the SHA-256 listed in the upstream SHA256SUMS; the upstream STAMP commit and time go into this STAMP."""
        st = path + '/STAMP'
        lines = open(st).read().splitlines() if os.path.exists(st) else []
        commit = next((l.split(' ', 1)[1] for l in lines if l.startswith('commit ')), '')
        when = next((l for l in lines if l.endswith('UTC+7')), '')
        stamped_sums = next((l.rsplit(' ', 1)[1] for l in lines if l.startswith('output SHA256SUMS sha256 ')), '')
        sums = {}
        sp = path + '/output/SHA256SUMS'
        actual_sums = sha256(sp) if os.path.exists(sp) else ''
        if os.path.exists(sp):
            for l in open(sp):
                h, _, fn = l.strip().partition('  ')
                if fn: sums[fn] = h
        self.upstreams[path] = dict(name=os.path.basename(path), stamp=bool(lines), commit=commit, time=when, sums=sums,
                                    stamped_sums=stamped_sums, actual_sums=actual_sums)
        self.log(f'upstream {path}: STAMP {"present" if lines else "MISSING"}; commit {commit or "-"}; {when or "-"}; {len(sums)} output SHAs')
        return path

    def log(self, msg):
        line = f'[{now()}] {msg}'
        print(line, flush=True)
        self.logf.write(line + '\n'); self.logf.flush()

    def inp(self, path, role, on_mismatch='raise'):
        """Register an input; record SHA, MANIFEST match and the year used (config/source_years.csv).
        A missing file still refuses to run. on_mismatch='raise' refuses a SHA mismatch (P6; review S01-L2).
        on_mismatch='in1' records the mismatch and lets IN1 fail. on_mismatch='exempt' records it, keeps the
        file, and leaves it out of the IN1 failure list so the difference can be reported (S09 BaTIS)."""
        if on_mismatch not in ('raise', 'in1', 'exempt'):
            raise InputError(f'unknown on_mismatch {on_mismatch}')
        if not os.path.exists(path):
            raise InputError(f'input missing for base year {BASE_YEAR}: {path} (see config/source_years.csv)')
        s = sha256(path)
        rel = os.path.relpath(path, DATA) if path.startswith(DATA) else None
        man = self._manifest.get(rel) if rel else None
        match = 'yes' if man == s else ('NOT IN MANIFEST' if man is None else 'MISMATCH')
        folder = rel.split('/')[0] if rel else ''
        yr = self._years.get(folder, {}).get('year_used', 'NOT RECORDED') if rel else 'n/a (not a data file)'
        la = self._years.get(folder, {}).get('latest_available', '') if rel else ''
        self.inputs[path] = dict(path=path, role=role, sha256=s, bytes=os.path.getsize(path),
                                 manifest_path=rel or '', manifest_sha256=man or '', manifest_match=match,
                                 source_folder=folder, year_used=yr, latest_available=la)
        self.log(f'input {path} sha256={s[:12]}.. manifest={match} year_used={yr}')
        if match == 'MISMATCH' and on_mismatch == 'exempt':
            self.in1_exempt.add(path)
            self.inputs[path]['manifest_match'] = 'SHA DIFFERS FROM MANIFEST (exempt; reported)'
            self.log(f'IN1 exempt {rel or path}: sha {s} manifest {man}')
        elif match == 'MISMATCH' and on_mismatch == 'raise':
            raise InputError(f'SHA mismatch against data/MANIFEST.csv: {path}')
        elif match == 'MISMATCH' and on_mismatch == 'in1':
            self.log(f'SHA mismatch left for IN1: {rel}')
        return path

    def check(self, cid, desc, kind, value, threshold, passed, concept='', detail=''):
        assert kind in ('hard', 'report', 'guard')
        if kind == 'hard' and cid in GUARDS:
            kind = 'guard'
        st = 'PASS' if passed else ('FAIL' if kind in ('hard', 'guard') else 'NOTE')
        self.checks.append(dict(id=cid, description=desc, kind=kind, value=str(value), threshold=str(threshold),
                                status=st, concept=concept, detail=detail))
        self.log(f'check {cid} [{kind}] {st}: {desc} value={value} threshold={threshold}')

    def adjust(self, region, item, before, after, rule, citation, flag):
        self.ledger.append(dict(stage=self.sid, region=region, item=item, before=before, after=after,
                                rule=rule, citation=citation, flag=flag))

    def flag(self, fid, subject, text, needs_david='no', rule='', citation=''):
        self.flags.append(dict(stage=self.sid, id=fid, subject=subject, text=text, needs_david=needs_david,
                               rule=rule, citation=citation))

    def write(self, fname, rows, cols=None):
        import pandas as pd
        df = rows if hasattr(rows, 'to_csv') else pd.DataFrame(rows, columns=cols)
        p = f'{self.out}/{fname}'
        df.to_csv(p, index=False)
        self.log(f'output {fname}: {len(df)} rows')
        return p

    def _repro(self):
        """Fable QA E-06: <sid>-Grepro compares this run's output/SHA256SUMS with the other run's, read from
        $GTAP_OTHER_STAGES_DIR/<stage>/output/SHA256SUMS (a second run of the same commit in another stages folder).
        With GTAP_RELEASE=1 the check is hard: a release STAMP needs the other run and identical sums. Otherwise it is
        report-only and a missing other run is a NOTE. Outside a git checkout (no commit) the run is marked dirty, so no
        STAMP is written with an empty commit line."""
        if not self.head:
            self.dirty = True
            self.log('no git commit (not a checkout): no STAMP')
        release = os.environ.get('GTAP_RELEASE', '') == '1'
        other_dir = os.environ.get('GTAP_OTHER_STAGES_DIR', '').strip()
        mine = open(self.out + '/SHA256SUMS').read()
        other_p = os.path.join(other_dir, os.path.basename(self.dir), 'output', 'SHA256SUMS') if other_dir else ''
        if other_p and os.path.abspath(other_p) == os.path.abspath(self.out + '/SHA256SUMS'):
            other_p = ''            # the other run must be another folder
        if other_p and os.path.exists(other_p):
            other = open(other_p).read()
            pm = lambda t: {fn: d for d, _, fn in (ln.partition('  ') for ln in t.splitlines()) if fn}
            a, b = pm(mine), pm(other)
            bad = sorted(fn for fn in set(a) | set(b) if a.get(fn) != b.get(fn))
            ok, value = not bad, f'{len(a)} files; {len(bad)} differ'
            detail = f'other run {other_p}. ' + ' '.join(bad)
        else:
            ok, value = False, 'other run not supplied'
            detail = 'Set GTAP_OTHER_STAGES_DIR to the stages folder of a second run of the same commit.'
        self.check(f'{self.sid}-Grepro', 'Two runs of the same commit write the same output SHA256SUMS (hard at release, GTAP_RELEASE=1)',
                   'hard' if release else 'report', value, 'every file identical', ok, 'stage kit; Fable QA E-06', detail)

    def finish(self):
        # upstream gate (review FR-M2): STAMP present and every upstream output read here matches the upstream SHA256SUMS
        for up, u in self.upstreams.items():
            read = {os.path.basename(k): v['sha256'] for k, v in self.inputs.items() if os.path.dirname(k) == up + '/output'}
            bad = sorted(fn for fn, h in read.items() if u['sums'].get(fn) != h)
            # fix round 3 (Opus FR2-L2): the SHA256SUMS file itself must equal the checksum written in the upstream STAMP
            sums_ok = bool(u['stamped_sums']) and u['stamped_sums'] == u['actual_sums']
            self.check(f'{self.sid}-G0', f'Upstream {u["name"]} has a STAMP, its output/SHA256SUMS matches the checksum in that STAMP, and every file read from its output/ matches SHA256SUMS', 'hard',
                       f'STAMP {"yes" if u["stamp"] else "NO"}; SHA256SUMS {"bound" if sums_ok else "NOT BOUND"}; {len(read)} files read; {len(bad)} mismatched', 'STAMP yes; bound; >= 1 read; 0',
                       u['stamp'] and sums_ok and bool(read) and not bad, 'P7; reviews FR-M2, FR2-L2',
                       f'upstream commit {u["commit"]}, {u["time"]}; SHA256SUMS stamped {u["stamped_sums"][:12] or "-"} actual {u["actual_sums"][:12] or "-"}. ' + ' '.join(bad))
            if u['commit'] and self.head:
                chg = subprocess.run(['git', '-C', BUILD, 'diff', '--name-only', u['commit'], self.head], capture_output=True, text=True).stdout.split()
                self.check(f'{self.sid}-G0c', f'Build code changed since upstream {u["name"]} was stamped (rerun upstream first if its own code changed)', 'report',
                           len(chg), 0, not chg, 'review FR-M2 (optional warning)', ' '.join(chg))
        if git_state()[1] and not self.dirty:   # review FR-L5(b): re-check for edits made during the run
            self.dirty = True
            self.log('WARNING: build repo changed during the run')
        # automatic checks on the stage's own data inputs (review S01-M1: each stage checks only its own inputs)
        di = [v for v in self.inputs.values() if v['manifest_path']]
        exempt = self.in1_exempt
        nm = [v['manifest_path'] for v in di if v['manifest_match'] != 'yes' and v['path'] not in exempt]
        reported = [f"{v['manifest_path']} sha {v['sha256']} manifest {v['manifest_sha256']}"
                    for v in di if v['path'] in exempt]
        detail = ' '.join(nm)
        if reported:
            detail = (detail + '. ' if detail else '') + 'Exempt and reported: ' + '; '.join(reported) + '.'
        self.check(f'{self.sid}-IN1', 'Every data input of this stage is in MANIFEST and its SHA-256 matches', 'hard', len(nm), 0, not nm, 'P6', detail)
        def _ok(y, la):
            # review FR-L1 / Grok L1: the year used must equal the recorded latest available year at or before the base year
            if y.startswith('n/a'): return la in ('', 'n/a')
            return y.isdigit() and la.isdigit() and int(la) <= BASE_YEAR and int(y) == int(la)
        by = [f"{v['manifest_path']} (used {v['year_used']}, latest {v['latest_available'] or '-'})" for v in di if not _ok(v['year_used'], v['latest_available'])]
        self.check(f'{self.sid}-IN2', f'Year rule: every data input has a recorded year used, equal to the latest available year at or before {BASE_YEAR} (config/source_years.csv, per source folder)', 'hard', len(by), 0, not by,
                   'standing year rule; config/source_years.csv', ' '.join(by))
        # outputs SHA
        with open(self.out + '/SHA256SUMS', 'w') as f:
            for fn in sorted(os.listdir(self.out)):
                if fn == 'SHA256SUMS': continue
                f.write(f'{sha256(self.out + "/" + fn)}  {fn}\n')
        self._repro()
        json.dump(self.checks, open(self.dir + '/checks.json', 'w'), indent=1)
        hard_fail = [c for c in self.checks if c['status'] == 'FAIL']
        md = [f'# {self.sid} {self.name}: checks', '', f'Run {now()}; build commit `{self.head}`' + (' (UNCOMMITTED CHANGES)' if self.dirty else ''), '',
              f'Hard checks: {sum(c["kind"]=="hard" for c in self.checks)}; guards (identities and re-checks of the stage\'s own output, '
              f'config/check_guards.csv): {sum(c["kind"]=="guard" for c in self.checks)}; FAIL: {len(hard_fail)}; report-only: {sum(c["kind"]=="report" for c in self.checks)}', '',
              '| ID | Kind | Status | Check | Value | Threshold | Concept |', '|---|---|---|---|---|---|---|']
        for c in self.checks:
            md.append(f'| {c["id"]} | {c["kind"]} | **{c["status"]}** | {c["description"]} | {c["value"]} | {c["threshold"]} | {c["concept"]} |')
        md.append('')
        for c in self.checks:
            if c['detail']:
                md += [f'### {c["id"]} detail', '', c['detail'], '']
        open(self.dir + '/checks.md', 'w').write('\n'.join(md) + '\n')
        for fn, rows, cols in [('adjustments_ledger.csv', self.ledger, ['stage', 'region', 'item', 'before', 'after', 'rule', 'citation', 'flag']),
                               ('flags.csv', self.flags, ['stage', 'id', 'subject', 'text', 'needs_david', 'rule', 'citation'])]:
            with open(self.dir + '/' + fn, 'w', newline='') as f:
                w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
        with open(self.dir + '/inputs.lock', 'w', newline='') as f:
            cols = ['path', 'role', 'bytes', 'sha256', 'manifest_path', 'manifest_sha256', 'manifest_match', 'source_folder', 'year_used', 'latest_available']
            w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(self.inputs.values())
        stamp = self.dir + '/STAMP'
        if hard_fail or self.dirty:
            why = ', '.join(c['id'] for c in hard_fail) + (' + uncommitted code' if self.dirty else '')
            self.log(f'NO STAMP: {why}')
        else:
            ups = ''.join(f'upstream {u["name"]} commit {u["commit"]} stamped {u["time"]} SHA256SUMS {u["actual_sums"]}\n' for u in self.upstreams.values())
            open(stamp, 'w').write(f'{self.sid}_{self.name}\nbase year {BASE_YEAR}\ncommit {self.head}\n{now()}\nall hard checks PASS\n{ups}stages dir {STAGES}\n'
                                   f'output SHA256SUMS sha256 {sha256(self.out + "/SHA256SUMS")}\n')
            self.log('STAMP written')
        self.log('stage end')
        self.logf.close()
        if hard_fail: raise SystemExit('HARD FAIL (no STAMP): ' + ', '.join(c['id'] for c in hard_fail))   # non-zero exit (review FR3)
        return True
