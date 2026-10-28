"""Donor guards (beta v4 P33; config/s05/donor_guards.csv). David's call; every guard defaults to off.

GTAP 12 ch.9D §D.3 p.3 matches each member to the primary region with the nearest GDP per capita in its geographic
pool, with no test of size or structure. A guard drops candidate donors that fail a test before the nearest one is
taken, so the member gets the next nearest that passes. Turning a guard on is a labelled departure from the literal 9D
rule (David, 2026-10-21) and means rerunning from S05.

To add a guard: write a test(member, donor, parameter, ctx) -> bool below, add it to GUARDS, and add a row to the
config file. ctx holds the S02 GDP of members and donors ('gdp': {code: USD m}); extend it when a guard needs more.

donor_blend (P33 option C, row in the same file, default off): with gdppc_k3 each member takes the three nearest
candidates by the 9D income measure in its pool, among those with at least 1/BLEND_FLOOR of its GDP, blended with the
weights BLEND_WEIGHTS (renormalised where the pool has fewer than three). GTAP 12 ch.7 §7.2 p.3: "A combination of one
or more primary region I-O tables"; the floor, k = 3 and the weights (P33 audit, leave-one-out on 75 ICIO tables) are
ours. To add a blend: a name in BLENDS with its k, weights and floor.
"""
import csv
import math

GUARD_COLUMNS = ('guard', 'value', 'parameter', 'decided_by', 'decided_at', 'basis')
ON = 'on'


def donor_size(member, donor, parameter, ctx):
    """donor_size_guard: the donor's S02 GDP is at least 1/parameter of the member's, so its table is scaled up at most
    parameter times (KEN on STP: 208 times)."""
    g = ctx['gdp']
    return g.get(donor, 0.0) * float(parameter) >= g.get(member, 0.0)


GUARDS = {'donor_size_guard': donor_size}
BLENDS = {'gdppc_k3': dict(k=3, weights=(0.55, 0.27, 0.18), floor=20.0)}
# donor_va_sections (beta v4 P37, s05_composite/va_sections.py VALUES) is read by S05 from the rows
CHOICE_VALUES = {'donor_size_guard': ('off', ON), 'donor_blend': ('off',) + tuple(BLENDS),
                 'donor_va_sections': ('off', 'ama_7', 'ama_ex_energy')}


def rank(cands, target, value_of, size_of):
    """Candidates ordered as S05's nearest(): absolute log distance of the income measure, then the larger GDP, then
    the code; a candidate with no positive measure is left out."""
    keyed = []
    for c in cands:
        try:
            v, t = float(value_of(c)), float(target)
        except (TypeError, ValueError):
            continue
        if not (v > 0 and t > 0) or math.isnan(v) or math.isnan(t):
            continue
        keyed.append(((abs(math.log(t) - math.log(v)), -(size_of(c) or 0.0), c), c))
    return [c for _k, c in sorted(keyed)]


def blend(member, cands, target, value_of, size_of, name, ctx):
    """The donor blend [(donor, weight)] of one member (weights sum to 1), or [] when no candidate has a measure.
    Candidates below 1/floor of the member's GDP are left out unless none is left."""
    b = BLENDS[name]
    big = [d for d in cands if donor_size(member, d, b['floor'], ctx)] or list(cands)
    top = rank(big, target, value_of, size_of)[:b['k']]
    w = b['weights'][:len(top)]
    return [(d, x / sum(w)) for d, x in zip(top, w)]


def read_guards(path):
    """Returns ([(name, parameter)] of the guards that are on, the donor_blend value ('off' or a BLENDS name), all rows).
    Raises ValueError on a malformed file."""
    with open(path, newline='') as fh:
        rd = csv.DictReader(fh)
        if tuple(rd.fieldnames or ()) != GUARD_COLUMNS:
            raise ValueError(f'{path}: columns {rd.fieldnames} are not {GUARD_COLUMNS}')
        rows = list(rd)
    names = [r['guard'] for r in rows]
    if sorted(names) != sorted(CHOICE_VALUES) or len(set(names)) != len(names):
        raise ValueError(f'{path}: rows {names} are not {sorted(CHOICE_VALUES)}')
    on, blend_value = [], 'off'
    for r in rows:
        if r['value'] not in CHOICE_VALUES[r['guard']] or not r['decided_by'].strip() or not r['basis'].strip():
            raise ValueError(f'{path}: row {r["guard"]} needs a value in {CHOICE_VALUES[r["guard"]]}, decided_by and basis')
        if r['guard'] == 'donor_blend':
            blend_value = r['value']
        elif r['value'] == ON:
            float(r['parameter'])
            on.append((r['guard'], r['parameter']))
    return on, blend_value, rows


def allowed(member, cands, guards, ctx):
    """The candidates that pass every guard that is on; the full list if none passes (the caller flags it)."""
    keep = [d for d in cands if all(GUARDS[n](member, d, p, ctx) for n, p in guards)]
    return keep or list(cands), not keep and bool(guards) and bool(cands)
