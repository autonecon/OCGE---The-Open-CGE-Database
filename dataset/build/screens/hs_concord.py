"""HS nomenclature joins for the screen library.

The sheets are the ones the tariff builder already uses. Each forward step
is one code to one code. A step back to a finer nomenclature returns every
preimage. Two codes are not averaged, and an ambiguous preimage is not
picked.
"""

_RANK = {'H2': 2, 'H3': 3, 'H4': 4, 'H5': 5, 'H6': 6}
_ALIAS = {
    'H6': 'H6', 'HS2022': 'H6', 'HS22': 'H6',
    'H5': 'H5', 'HS2017': 'H5', 'HS17': 'H5',
    'H4': 'H4', 'HS2012': 'H4', 'HS12': 'H4',
    'H3': 'H3', 'HS2007': 'H3', 'HS07': 'H3',
    'H2': 'H2', 'HS2002': 'H2', 'HS02': 'H2',
}


def norm_nomen(value):
    return _ALIAS.get((value or '').strip().upper(), '')


def _inverse_lists(forward):
    """code -> every source that maps to it. The forward map stays one-to-one."""
    back = {}
    for src, dst in forward.items():
        if not src or not dst:
            continue
        back.setdefault(dst, []).append(src)
    return back


def build_maps(hs22_to_hs17, hs17_to_hs12, hs17_to_hs07, hs17_to_hs02):
    """Forward maps are one code to one code. Inverse maps are lists."""
    fwd = {
        ('H6', 'H5'): {k: v for k, v in hs22_to_hs17.items() if k and v},
        ('H5', 'H4'): {k: v for k, v in hs17_to_hs12.items() if k and v},
        ('H5', 'H3'): {k: v for k, v in hs17_to_hs07.items() if k and v},
        ('H5', 'H2'): {k: v for k, v in hs17_to_hs02.items() if k and v},
    }
    inv = {edge: _inverse_lists(table) for edge, table in fwd.items()}
    return {'fwd': fwd, 'inv': inv}


def _path(src, dst):
    """Edges to walk. Each edge is (forward_key, direction)."""
    if src == 'H6' and dst == 'H5':
        return [(('H6', 'H5'), 'forward')]
    if src == 'H5' and dst == 'H6':
        return [(('H6', 'H5'), 'inverse')]
    if src == 'H5' and dst in ('H4', 'H3', 'H2'):
        return [((src, dst), 'forward')]
    if src in ('H4', 'H3', 'H2') and dst == 'H5':
        return [((dst, src), 'inverse')]
    if src == 'H6' and dst in ('H4', 'H3', 'H2'):
        return [(('H6', 'H5'), 'forward'), (('H5', dst), 'forward')]
    if src in ('H4', 'H3', 'H2') and dst == 'H6':
        return [(( 'H5', src), 'inverse'), (('H6', 'H5'), 'inverse')]
    if src in ('H4', 'H3', 'H2') and dst in ('H4', 'H3', 'H2') and src != dst:
        return [(( 'H5', src), 'inverse'), (('H5', dst), 'forward')]
    return None


def images(code, src, dst, maps):
    """Codes in `dst` that `code` in `src` joins to.

    Returns (codes, status). status is same, concorded, unmapped, nomen_missing,
    or no_path. An empty inverse is unmapped. A list of preimages is a fan-out,
    not a choice among rates.
    """
    src_n = norm_nomen(src) if src not in _RANK else src
    dst_n = norm_nomen(dst) if dst not in _RANK else dst
    if not src_n or not dst_n:
        return [], 'nomen_missing'
    if src_n == dst_n:
        return [code], 'same'
    path = _path(src_n, dst_n)
    if path is None:
        return [], 'no_path'
    current = [code]
    for edge, direction in path:
        nxt = []
        table = maps['fwd'][edge] if direction == 'forward' else maps['inv'][edge]
        for item in current:
            found = table.get(item)
            if not found:
                continue
            if direction == 'forward':
                nxt.append(found)
            else:
                nxt.extend(found)
        if not nxt:
            return [], 'unmapped'
        current = nxt
    # Stable and unique.
    return sorted(set(current)), 'concorded'


def _self_check():
    hs22 = {'010121': '010121', '010129': '010121', '999999': '999999'}
    hs12 = {'010121': '010120', '999999': '999999'}
    maps = build_maps(hs22, hs12, {}, {})
    assert images('010121', 'H6', 'H6', maps) == (['010121'], 'same')
    assert images('010129', 'H6', 'H5', maps) == (['010121'], 'concorded')
    assert images('010121', 'H5', 'H6', maps)[0] == ['010121', '010129']
    assert images('010120', 'H4', 'H5', maps) == (['010121'], 'concorded')
    assert images('010129', 'H6', 'H4', maps) == (['010120'], 'concorded')
    assert images('010120', 'H4', 'H3', maps)[1] == 'unmapped'
    assert images('010121', '', 'H6', maps)[1] == 'nomen_missing'


_self_check()
