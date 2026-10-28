"""Number formatting and writers shared by the S10 modules (same formats as the stage kit outputs)."""
import csv
import gzip


def fnum(x):
    x = float(x)
    if x != x or x in (float('inf'), float('-inf')):
        return 'nan'
    if abs(x) < 5e-13:
        return '0'
    s = f'{x:.10f}'
    if '.' in s:
        s = s.rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s


def write_csv(path, cols, rows):
    with open(path, 'w', newline='') as fh:
        w = csv.writer(fh, lineterminator='\n')
        w.writerow(cols)
        w.writerows(rows)


def gz_write(path, header, lines):
    """Deterministic gzip: no file name, mtime 0, level 9."""
    with open(path, 'wb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0, compresslevel=9) as gz:
            gz.write(header)
            for line in lines:
                gz.write(line)
