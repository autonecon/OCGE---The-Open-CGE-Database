"""GEMPACK HAR writer (header array file), the standard GTAP record layout.

A port of earlier-build/build/write_har_2022.jl on main (its own writer, because HeaderArrayFile.jl is
read-only), which reads back in HeaderArrayFile.jl and in ViewHAR. Each record is a Fortran unformatted
record: int32 length, payload, int32 length. Reals are Float32 (PLAN §3(j): HAR Float32 is the canonical
artefact). A header is:
  - a 4-byte name record;
  - a description record: 4 blanks, type ('1C', 'RE', '2I'), 'FULL', 70-char description, then the
    dimensions;
  - for RE, a set-name record and one element record per distinct set, then the data records, at most
    8000 reals each, in column-major (Fortran) order.
Set elements are written in lower case, as GTAP does.
"""
import struct

import numpy as np

MAX_REALS = 8000
ELEMENT_WIDTH = 12


def _pad(s, n):
    b = str(s).encode('ascii')
    if len(b) > n:
        raise ValueError(f'label longer than {n}: {s}')
    return b + b' ' * (n - len(b))


def _i32(*xs):
    return struct.pack(f'<{len(xs)}i', *xs)


def _chunk(fh, payload):
    n = struct.pack('<i', len(payload))
    fh.write(n + payload + n)


def _name(fh, name):
    if len(name) > 4:
        raise ValueError(f'header name longer than 4: {name}')
    _chunk(fh, _pad(name.upper(), 4))


def _elements(elements):
    return b''.join(_pad(str(e).lower(), ELEMENT_WIDTH) for e in elements)


def write_1c(fh, name, description, elements):
    """A character header (a set)."""
    _name(fh, name)
    body = b'1CFULL' + _pad(description, 70) + _i32(2, len(elements), ELEMENT_WIDTH)
    _chunk(fh, b'    ' + body)
    _chunk(fh, b'    ' + _i32(1, len(elements), len(elements)) + _elements(elements))


def write_2i(fh, name, description, value):
    """A 1x1 integer header (RDLT)."""
    _name(fh, name)
    _chunk(fh, b'    ' + b'2IFULL' + _pad(description, 70) + _i32(2, 1, 1))
    _chunk(fh, b'    ' + _i32(1, 1, 1, 1, 1, 1, 1, int(value)))


def _real_chunks(sizes):
    """The ranges of each data record, as in write_har_2022.jl real_chunks."""
    if not sizes:
        return [[]]
    if len(sizes) == 1:
        return [[(1, sizes[0])]]
    plane = int(np.prod(sizes[:-1]))
    if plane <= MAX_REALS:
        step = min(sizes[-1], max(1, MAX_REALS // plane))
        out, start = [], 1
        while start <= sizes[-1]:
            stop = min(sizes[-1], start + step - 1)
            out.append([(1, n) for n in sizes[:-1]] + [(start, stop)])
            start = stop + 1
        return out
    leads = _real_chunks(sizes[:-1])
    return [lead + [(k, k)] for k in range(1, sizes[-1] + 1) for lead in leads]


def _span(sizes, ranges):
    offset, stride, count = 0, 1, 1
    for n, (a, b) in zip(sizes, ranges):
        offset += (a - 1) * stride
        stride *= n
        count *= b - a + 1
    return offset, count


def write_re(fh, name, description, dimlabels, sets, values):
    """A real header with set labels. values is a numpy array whose axes follow dimlabels.

    Axes of length 1 are kept (unlike write_har_2022.jl, which drops them): every set this stage writes has
    more than one element, and S15-Hdims checks the dimensions as read back."""
    values = np.asarray(values, dtype=np.float64)
    sizes = list(values.shape)
    if len(sizes) != len(dimlabels):
        raise ValueError(f'{name}: rank {len(sizes)} but {len(dimlabels)} labels')
    for n, lab in zip(sizes, dimlabels):
        if len(sets[lab]) != n:
            raise ValueError(f'{name}: set {lab} has {len(sets[lab])} elements, the array {n}')
    if len(sizes) > 7:
        raise ValueError(f'{name}: rank above 7')
    dims7 = sizes + [1] * (7 - len(sizes))
    _name(fh, name)
    _chunk(fh, b'    ' + b'REFULL' + _pad(description, 70) + _i32(7, *dims7))
    N = len(dimlabels)
    uniq = list(dict.fromkeys(dimlabels))
    nb = _i32(len(uniq), 1, N) + _pad(name.upper(), 12) + _i32(1) + b''.join(_pad(l.upper(), 12) for l in dimlabels)
    nb += b'k' * N + b'\x00' * (4 * (1 + N))
    _chunk(fh, b'    ' + nb)
    for lab in uniq:
        el = sets[lab]
        _chunk(fh, b'    ' + _i32(1, len(el), len(el)) + _elements(el))
    flat = values.astype(np.float32).ravel(order='F')
    chunks = _real_chunks(sizes)
    nchunks = len(chunks)
    _chunk(fh, b'    ' + _i32(2 * nchunks + 1, 7, *dims7))
    for i, ranges in enumerate(chunks):
        remaining = nchunks - i
        meta = [1] * 15
        meta[0] = 2 * remaining
        meta[1] = 1
        if not sizes:
            meta[2] = 1
            offset, count = 0, 1
        else:
            meta[2] = sizes[0]
            pos = 3
            for d in range(1, len(sizes)):
                meta[pos], meta[pos + 1] = ranges[d]
                pos += 2
            offset, count = _span(sizes, ranges)
        _chunk(fh, b'    ' + _i32(*meta))
        piece = flat[offset:offset + count]
        _chunk(fh, b'    ' + _i32(2 * remaining - 1) + piece.astype('<f4').tobytes())


def float32_relative_gap(a, b):
    """Largest |a - b| / max(1, |a|) over all cells: the HAR (Float32) against the Float64 source."""
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    if a.shape != b.shape:
        return np.inf
    if a.size == 0:
        return 0.0
    return float(np.max(np.abs(a - b) / np.maximum(1.0, np.abs(a))))
