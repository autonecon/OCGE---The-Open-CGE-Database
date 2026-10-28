"""Read the S15 HAR files back with harpy (an independent GEMPACK reader, CoPS), for the S15 checks.

    <python with harpy> read_har.py <har dir> <dump dir>

Writes <dump dir>/<file>_<HEADER>.npy for every real or integer header, <file>_<HEADER>.txt (one element per
line) for every character header, and index.txt (file, header, type, shape, set names). harpy needs a
numpy older than 2.3 (requirements-s15-reader.txt), so it runs in its own environment.
"""
import os
import sys

import numpy as np
from harpy import HarFileObj

src, dump = sys.argv[1], sys.argv[2]
os.makedirs(dump, exist_ok=True)
with open(os.path.join(dump, 'index.txt'), 'w') as idx:
    for f in ('set', 'par', 'dat'):
        h = HarFileObj.loadFromDisk(os.path.join(src, f'gsdf{f}.har'))
        for name in h.getHeaderArrayNames():
            o = h.getHeaderArrayObj(name)
            a = np.asarray(o['array'])
            sets = [s['name'] for s in o.get('sets', [])] if 'sets' in o else []
            if a.dtype.kind in 'US':
                with open(os.path.join(dump, f'{f}_{name}.txt'), 'w') as t:
                    t.write('\n'.join(str(x).strip() for x in a.ravel()) + '\n')
                kind = 'char'
            else:
                np.save(os.path.join(dump, f'{f}_{name}.npy'), a.astype(np.float64))
                kind = 'real' if a.dtype.kind == 'f' else 'int'
            idx.write(f'{f}|{name}|{kind}|{"x".join(str(n) for n in a.shape)}|{",".join(sets)}\n')
print('harpy read done')
