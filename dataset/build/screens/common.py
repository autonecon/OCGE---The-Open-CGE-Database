"""Shared screen helpers. Later stages import this; they do not import S10.

A screen reads a stage directory and writes a report directory. It does not
write into the stage output, so a screen run does not change SHA256SUMS.
"""
import csv
import gzip
import os

# A hit is material when its duty is at least this many USD billion, or at
# least this share of the importer's booked duty. The hard check fails on
# unexplained hits above either bar.
MATERIAL_DUTY_BN = 0.02
MATERIAL_SHARE = 0.001

EXPLANATION_COLUMNS = [
    'importer', 'hs6/sector', 'screen', 'evidence class',
    'source file and page', 'decided_by', 'date',
]
EVIDENCE_CLASSES = (
    'statute_confirmed', 'tariff_book', 'trq', 'gtap_rule', 'data_gap',
    'earlier_year_conversion', 'explained_by_definition',
    'missing_schedule_in_source', 'wits_rate_as_given', 'genuine_not_a_source_gap',
    'unexplained',
)


def open_text(path):
    if path.endswith('.gz'):
        return gzip.open(path, 'rt', newline='')
    return open(path, newline='')


def read_dicts(path):
    with open_text(path) as fh:
        return list(csv.DictReader(fh))


def write_dicts(path, rows, columns):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, lineterminator='\n', extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, '') for col in columns})


def material(duty_bn, importer_duty_bn, fob_bn=None):
    """True when a hit is large enough for the hard check.

    A blank duty is material when the FOB on that line is itself at or above
    the same bar. KOR 100390 is the case: feed barley has no out-of-quota rate
    and about 0.024 bn of FOB.
    """
    if duty_bn is None or duty_bn == '':
        if fob_bn in (None, ''):
            return False
        return material(fob_bn, importer_duty_bn)
    try:
        duty = abs(float(duty_bn))
    except (TypeError, ValueError):
        return False
    if duty >= MATERIAL_DUTY_BN:
        return True
    try:
        base = abs(float(importer_duty_bn))
    except (TypeError, ValueError):
        base = 0.0
    return base > 0 and duty >= MATERIAL_SHARE * base


def explanation_key(screen, importer, hs6_or_sector):
    return (screen, importer or '', hs6_or_sector or '')


def load_explanations(path):
    """Return (by key, rows). Missing file is an empty table."""
    if not path or not os.path.exists(path):
        return {}, []
    rows = read_dicts(path)
    by_key = {}
    for row in rows:
        key = explanation_key(row.get('screen', ''), row.get('importer', ''), row.get('hs6/sector', ''))
        by_key[key] = row
    return by_key, rows


def blank_explanation(screen, importer, hs6_or_sector):
    return {
        'importer': importer or '',
        'hs6/sector': hs6_or_sector or '',
        'screen': screen,
        'evidence class': 'unexplained',
        'source file and page': '',
        'decided_by': '',
        'date': '',
    }


def join_explanations(hits, by_key):
    """Attach evidence class to hits that require a row (caller filters screens)."""
    missing = []
    for hit in hits:
        key = explanation_key(hit['screen'], hit.get('importer', ''), hit.get('hs6/sector', ''))
        row = by_key.get(key)
        if row is None:
            row = blank_explanation(hit['screen'], hit.get('importer', ''), hit.get('hs6/sector', ''))
            missing.append(row)
            by_key[key] = row
        hit['evidence class'] = (row.get('evidence class') or 'unexplained').strip()
        if hit['evidence class'] not in EVIDENCE_CLASSES:
            hit['evidence class'] = 'unexplained'
            row['evidence class'] = 'unexplained'
        hit['material'] = 'yes' if material(
            hit.get('duty_bn'), hit.get('importer_duty_bn'), hit.get('fob_bn')) else 'no'
    return missing


def unexplained_material(hits):
    out = []
    for hit in hits:
        if hit.get('evidence class') != 'unexplained':
            continue
        if hit.get('material') != 'yes':
            continue
        out.append(hit)
    out.sort(key=lambda h: -abs(float(h.get('duty_bn') or 0)))
    return out


def write_summary(path, title, counts, unexplained, couldnt, notes):
    lines = [f'# {title}', '']
    lines.append('## Hit counts')
    lines.append('')
    lines.append('| Screen | Population | Hits |')
    lines.append('|---|---:|---:|')
    for name, pop, hits in counts:
        lines.append(f'| {name} | {pop} | {hits} |')
    lines.append('')
    lines.append('## Unexplained and material')
    lines.append('')
    lines.append(
        f'A hit is material at {MATERIAL_DUTY_BN} bn of duty or '
        f'{MATERIAL_SHARE:.1%} of the importer\'s booked duty. '
        f'{len(unexplained)} unexplained hits are above that bar.'
    )
    lines.append('')
    if unexplained:
        lines.append('| Screen | Importer | hs6/sector | Duty, bn | Importer duty, bn | Gap, bn | Ratio |')
        lines.append('|---|---|---|---:|---:|---:|---:|')
        for hit in unexplained:
            def _num(value):
                if value in ('', None):
                    return ''
                try:
                    return f'{float(value):.6f}'
                except (TypeError, ValueError):
                    return ''
            lines.append(
                f"| {hit.get('screen','')} | {hit.get('importer','')} | "
                f"{hit.get('hs6/sector','')} | {_num(hit.get('duty_bn'))} | "
                f"{_num(hit.get('importer_duty_bn'))} | {_num(hit.get('gap_bn'))} | "
                f"{_num(hit.get('ratio'))} |"
            )
    else:
        lines.append('None.')
    lines.append('')
    lines.append('## Could not check')
    lines.append('')
    if couldnt:
        for item in couldnt:
            lines.append(f'- {item}')
    else:
        lines.append('None.')
    lines.append('')
    if notes:
        lines.append('## Notes')
        lines.append('')
        for note in notes:
            lines.append(f'- {note}')
        lines.append('')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as fh:
        fh.write('\n'.join(lines))
