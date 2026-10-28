"""HS6 sector overrides for codes that are not ties (fix round B13).

The S01 HS17 rule is the dominant UNSD HS-CPC-ISIC link, with ties settled by config/s01/hs6_tiebreak.csv
(PLAN_ERRATA E33, E35). Some single-link codes land on a sector that GTAP does not use: the UNSD route sends
paper, ferrous, copper and aluminium waste and scrap (HS 4707, 7204, 7404, 7602) to ICIO E (water supply,
sewerage and waste), while GTAP 10 put them in PPP, I_S and NFM. FABLE QA F-12 adds precious-metal waste
and scrap (HS 7112, GTAP NFM) on the same basis. config/s01/hs6_sector_override.csv
lists those codes, one row per HS6, with the GTAP GSEC3 code it follows. The stage applies a row before
the link rules and checks the result here.
"""
import csv

COLUMNS = ('hs6', 'heading', 'sector', 'unsd_sector', 'gtap_gsec3', 'decided_by', 'decided_at', 'basis', 'gtap_status')


def load(path, sectors):
    """Read the override table strictly. Returns {hs6: row}. Raises SystemExit on any bad row."""
    with open(path, newline='') as fh:
        reader = csv.DictReader(fh)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise SystemExit(f'{path}: columns must be {",".join(COLUMNS)}')
        rows = list(reader)
    out = {}
    for n, r in enumerate(rows, start=2):
        empty = [c for c in COLUMNS if not (r.get(c) or '').strip()]
        if empty:
            raise SystemExit(f'{path} line {n}: empty {empty}')
        k, h = r['hs6'], r['heading']
        if not (len(k) == 6 and k.isdigit() and len(h) == 4 and h.isdigit() and k.startswith(h)):
            raise SystemExit(f'{path} line {n}: hs6 {k} must be six digits inside heading {h}')
        if r['sector'] not in sectors or r['unsd_sector'] not in sectors:
            raise SystemExit(f'{path} line {n}: sector {r["sector"]} or unsd_sector {r["unsd_sector"]} is not one of the 51 sectors')
        if r['sector'] == r['unsd_sector']:
            raise SystemExit(f'{path} line {n}: {k} already maps to {r["sector"]}; not an override')
        if r['gtap_status'] != 'gtap':
            raise SystemExit(f'{path} line {n}: gtap_status must be gtap (an override follows GTAP\'s own HS concordance)')
        if k in out:
            raise SystemExit(f'{path} line {n}: duplicate hs6 {k}')
        out[k] = r
    heads = {}
    for k, r in out.items():
        if heads.setdefault(r['heading'], r['sector']) != r['sector']:
            raise SystemExit(f'{path}: heading {r["heading"]} has more than one override sector')
    return out


def check(mapped, links, gtap_of, g2s, rows):
    """Problems with the applied overrides, as a list of strings (empty means pass).

    mapped:  {hs6: sector} after S01's rules (the concordance it writes)
    links:   {hs6: set of UNSD-linked sectors}
    gtap_of: {hs6: GTAP GSEC3 code, upper case without '_'}
    g2s:     {GSEC3 code: set of our sectors} (config/s01/gtap65_to_sector.csv)
    rows:    load() result
    """
    bad = []
    for k, r in sorted(rows.items()):
        if k not in mapped:
            bad.append(f'{k}: not an HS17 code in the link file')
            continue
        if mapped[k] != r['sector']:
            bad.append(f'{k}: mapped to {mapped[k]}, override says {r["sector"]}')
        if r['sector'] in links.get(k, set()):
            bad.append(f'{k}: {r["sector"]} is already a UNSD link (use the tie-break table)')
        if r['unsd_sector'] not in links.get(k, set()):
            bad.append(f'{k}: unsd_sector {r["unsd_sector"]} is not its UNSD link {sorted(links.get(k, set()))}')
        gs = gtap_of.get(k, '')
        want = r['gtap_gsec3'].upper().replace('_', '')
        if gs != want:
            bad.append(f'{k}: GTAP file says {gs or "nothing"}, override row says {want}')
        if r['sector'] not in g2s.get(want, set()):
            bad.append(f'{k}: {r["sector"]} is not our sector for GTAP {want}')
    # every HS17 code in an overridden heading ends in that heading's sector (no code left behind)
    heads = {r['heading']: r['sector'] for r in rows.values()}
    for k, sec in sorted(mapped.items()):
        h = k[:4]
        if h in heads and sec != heads[h]:
            bad.append(f'{k}: heading {h} goes to {heads[h]}, but {k} maps to {sec}')
    return bad
