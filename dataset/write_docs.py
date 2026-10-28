"""Regenerate dataset/SOURCES.md and the Sources table of dataset/README.md, and keep data/MANIFEST.csv complete.

Every folder under data/ is a source: it has a README.md (title line, then "- **Key:** value" bullets) and rows in
MANIFEST.csv. This script
  1. adds a MANIFEST row for each file in a source folder that has none (metadata copied from the folder's own
     rows, or from FOLDER_DEFAULTS for a folder that has no row yet), except git-ignored files and the
     <name>.partNN chunks of files listed in SPLIT_FILES.sha256 (the rebuilt original has the row);
  2. refreshes bytes and SHA-256 of README.md rows (documentation, edited after the row was written);
  3. writes SOURCES.md and the README Sources table from MANIFEST.csv and the folder READMEs.
It never opens a raw data file except to hash it, and never changes the row of a data file.
Exits 1 if a folder has no README.md or no MANIFEST row, or a MANIFEST folder is missing.
Then run build/check_manifest.py (writes MANIFEST_AUDIT.md).

Run from anywhere:  python3 dataset/write_docs.py
"""
import collections, csv, datetime, hashlib, io, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = ROOT + '/data'
MAN = DATA + '/MANIFEST.csv'
COLS = ['path', 'source', 'url', 'version', 'downloaded_or_origin', 'bytes', 'sha256', 'licence', 'redistributable']
NOW = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=7))).strftime('%Y-%m-%d %H:%M')

# folders whose files had no MANIFEST row at all, so there is no row to copy metadata from
FOLDER_DEFAULTS = {
    'raw_external': dict(source='raw_external', url='(an internal working folder; see raw_external/README.md)',
                         version='box copy 2026-10-19', licence='private repo; TRAINS-derived and national-source files are not for publication',
                         redistributable='private repo only; NOT FOR PUBLICATION'),
}


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as fh:
        for b in iter(lambda: fh.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def read_manifest():
    """Records as (raw text, dict). The raw text is written back unchanged unless the row changes."""
    out, buf = [], ''
    with open(MAN, newline='') as fh:
        lines = fh.read().splitlines(keepends=True)
    for ln in lines:
        buf += ln
        if buf.count('"') % 2:
            continue   # a quoted field spans lines
        rec = next(csv.reader(io.StringIO(buf)), [])
        if not rec:   # a stray blank line is dropped
            buf = ''
            continue
        if len(rec) != len(COLS):
            raise SystemExit(f'{MAN}: record with {len(rec)} fields: {buf[:120]!r}')
        out.append((buf, rec))
        buf = ''
    head = out.pop(0)[1]
    if head != COLS:
        raise SystemExit(f'{MAN}: columns must be {",".join(COLS)}')
    return [(raw, dict(zip(COLS, r))) for raw, r in out]


def row_text(d):
    o = io.StringIO()
    csv.writer(o, lineterminator='\n').writerow([d[c] for c in COLS])
    return o.getvalue()


def ignored(paths):
    """Paths (relative to DATA) that git ignores."""
    if not paths:
        return set()
    r = subprocess.run(['git', '-C', DATA, 'check-ignore', '--stdin'], input='\n'.join(paths), capture_output=True, text=True)
    return {os.path.relpath(os.path.join(DATA, p.strip()), DATA) for p in r.stdout.splitlines() if p.strip()}


def readme(folder):
    """Title and {key: value} of the '- **Key:** value' bullets of data/<folder>/README.md."""
    txt = open(f'{DATA}/{folder}/README.md', encoding='utf-8').read()
    lines = txt.splitlines()
    title = lines[0][2:].strip() if lines and lines[0].startswith('# ') else folder
    keys = {}
    for ln in lines:
        m = re.match(r'- \*\*(.+?):?\*\*:?\s*(.*)', ln)
        if m and m.group(1).strip(':') not in keys:
            keys[m.group(1).strip(':').strip()] = m.group(2).strip()
    para, started = [], False   # first plain paragraph after the title
    for ln in lines[1:]:
        if ln.strip() and not ln.startswith(('#', '-', '|', '`')):
            para.append(ln.strip()); started = True
        elif started:
            break
    para = ' '.join(para)
    return title, keys, para


def pick(keys, *names):
    for n in names:
        for k, v in keys.items():
            if k.lower().startswith(n.lower()) and v:
                return v
    return ''


def common(rows, col):
    c = collections.Counter(r[col] for r in rows if r[col])
    return c.most_common(1)[0][0] if c else ''


def main():
    recs = read_manifest()
    folders = sorted(d for d in os.listdir(DATA) if os.path.isdir(os.path.join(DATA, d)))
    split = {ln.split()[1] for ln in open(DATA + '/SPLIT_FILES.sha256') if ln.strip()}
    listed = {r['path'] for _, r in recs}
    by_folder = collections.defaultdict(list)
    for _, r in recs:
        by_folder[r['path'].replace('(not downloaded) ', '').split('/')[0]].append(r)
    problems = []
    # 1. rows for files that have none
    on_disk = sorted(os.path.relpath(os.path.join(rt, f), DATA) for d in folders for rt, _, fs in os.walk(os.path.join(DATA, d)) for f in fs)
    cand = [p for p in on_disk if p not in listed and os.path.basename(p) != 'README.md' and not (re.sub(r'\.part\d\d$', '', p) in split and p != re.sub(r'\.part\d\d$', '', p))]
    ign = ignored(cand)
    added = []
    for p in cand:
        if p in ign:
            print(f'skipped (git-ignored, add its row by hand if a stage reads it): {p}')
            continue
        f = p.split('/')[0]
        base = by_folder.get(f) or ([FOLDER_DEFAULTS[f]] if f in FOLDER_DEFAULTS else [])
        if not base:
            problems.append(f'{p}: folder {f} has no MANIFEST row and no FOLDER_DEFAULTS entry')
            continue
        # metadata of the folder row whose file name shares the longest stem (wdi_services_2022.refetch.csv -> wdi_services_2022.csv), else the folder's most common
        near = max(base, key=lambda r: len(os.path.commonprefix([os.path.basename(r.get('path', '')), os.path.basename(p)])))
        if len(os.path.commonprefix([os.path.basename(near.get('path', '')), os.path.basename(p)])) >= 8:
            d = {c: near[c] for c in ('source', 'url', 'version', 'licence', 'redistributable')}
        else:
            d = {c: common(base, c) for c in ('source', 'url', 'version', 'licence', 'redistributable')}
        d.update(path=p, downloaded_or_origin=f'committed without a MANIFEST row; row added by write_docs.py {NOW[:10]} (metadata as the folder)',
                 bytes=str(os.path.getsize(DATA + '/' + p)), sha256=sha(DATA + '/' + p))
        recs.append((row_text(d), d)); by_folder[f].append(d); added.append(p)
    # 2. README rows: refresh bytes and SHA-256
    refreshed = []
    for i, (raw, r) in enumerate(recs):
        p = DATA + '/' + r['path']
        if os.path.basename(r['path']) == 'README.md' and os.path.exists(p) and r['sha256'] != sha(p):
            r = dict(r, bytes=str(os.path.getsize(p)), sha256=sha(p))
            recs[i] = (row_text(r), r); refreshed.append(r['path'])
    with open(MAN, 'w', newline='') as fh:
        fh.write(','.join(COLS) + '\n')
        fh.writelines(raw for raw, _ in recs)
    # 3. SOURCES.md and the README table
    for f in folders:
        if not os.path.exists(f'{DATA}/{f}/README.md'):
            problems.append(f'{f}: no README.md')
        if not by_folder.get(f):
            problems.append(f'{f}: no MANIFEST row')
    problems += [f'{f}: in MANIFEST, no folder' for f in sorted(set(by_folder) - set(folders))]
    entries, table = [], []
    for f in folders:
        if not os.path.exists(f'{DATA}/{f}/README.md') or not by_folder.get(f):
            continue
        rows = by_folder[f]
        title, keys, para = readme(f)
        n = sum(1 for r in rows if not r['path'].startswith('(') and os.path.basename(r['path']) != 'README.md')
        version = pick(keys, 'Version') or common(rows, 'version')
        page = pick(keys, 'Source page', 'Source')
        m = re.search(r'\((https?://[^)\s`]+)\)', page) or re.search(r'(https?://[^\s,;)`"]+)', page) or re.search(r'(https?://[^\s,;)`"]+)', common(rows, 'url'))
        link = m.group(1) if m else ''
        lic = pick(keys, 'Licence', 'License') or common(rows, 'licence')
        use = pick(keys, 'How it is used', 'Use') or para
        redis = sorted({r['redistributable'] for r in rows if r['redistributable']})
        e = f'- **{title}**' + (f' ({version})' if version else '') + '.'
        e += f' [Source page]({link}).' if link else ''
        e += f' Licence: {lic.rstrip(".")}.' if lic else ''
        e += f' Redistributable: {"; ".join(redis)}.' if redis else ''
        e += f' Use: {use.rstrip(".")}.' if use else ''
        e += f' Folder: `data/{f}/` ({n} file{"" if n == 1 else "s"}).'
        entries.append(e)
        table.append(f'| [`{f}`](data/{f}/README.md) | {title.replace("|", "/")} | {n} | {(lic.split(";")[0] if lic else "").replace("|", "/")} |')
    md = ['# Data sources', '',
          f'Every data source the 2022 GTAP-method database uses or keeps for audit: one entry per folder under `data/` ({len(entries)} folders, '
          f'{len(recs)} MANIFEST rows). Generated by `write_docs.py` from `data/MANIFEST.csv` and the folder READMEs; re-run it whenever a source '
          f'or a file is added or dropped. Last generated: {NOW} (UTC+7).', '',
          'Redistribution: raw files are not part of this repository. Each source keeps its own terms (the Licence and '
          'Redistributable fields below); fetch the files from the publisher with the link, version and SHA-256 in '
          'data/MANIFEST.csv.', ''] + entries
    open(ROOT + '/SOURCES.md', 'w', encoding='utf-8').write('\n'.join(md) + '\n')
    rd = open(ROOT + '/README.md', encoding='utf-8').read()
    i = rd.index('## Sources\n'); j = rd.find('\n## ', i + 1)
    new = '## Sources\n\n| Folder | Source | Files | Licence |\n|---|---|---|---|\n' + '\n'.join(table) + '\n'
    rd = rd[:i] + new + (rd[j:] if j >= 0 else '')
    open(ROOT + '/README.md', 'w', encoding='utf-8').write(rd)
    print(f'{len(folders)} folders; {len(entries)} in SOURCES.md; MANIFEST rows {len(recs)} ({len(added)} added, {len(refreshed)} README rows refreshed)')
    for p in added:
        print('added', p)
    for p in refreshed:
        print('refreshed', p)
    for p in problems:
        print('PROBLEM', p)
    sys.exit(1 if problems else 0)


if __name__ == '__main__':
    main()
