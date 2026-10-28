"""HS22 codes with several HS17 sources in different sectors (QA finding B-09).

S01 maps an HS22 code through the UNSD conversion sheet (one HS17 source per HS22 code) to the sector of that
HS17 code. The UNSD correlation sheet lists every HS17 source of an HS22 code. Where those sources fall in more
than one sector, the choice is checked against GTAP's own HS2022 list (GTAP HS->GSEC3, sheet H6). The value
of the largest HS17 source is only reported: an HS17 parent's world value includes trade that goes to other
HS22 codes, so it does not decide the sector of a split code.
"""


def ambiguous(corr, sec17, chosen, gtap22, g2s, value17):
    """HS22 codes whose HS17 sources fall in several sectors, one dict per code, sorted by code.

    corr:    iterable of (hs22, hs17) pairs from the UNSD correlation sheet
    sec17:   {hs17: sector} (the S01 HS17 concordance)
    chosen:  {hs22: sector} (the S01 HS22 concordance)
    gtap22:  {hs22: GTAP GSEC3 code, upper case without '_'} (sheet H6)
    g2s:     {GSEC3 code: set of our sectors} (config/s01/gtap65_to_sector.csv)
    value17: {hs17: world value} (BACI HS17, the base year)
    """
    src = {}
    for h22, h17 in corr:
        src.setdefault(h22, set()).add(h17)
    out = []
    for h22 in sorted(src):
        secs = {sec17.get(p, '') for p in src[h22]}
        if len(secs) < 2 or h22 not in chosen:
            continue
        by = {}
        for p in src[h22]:
            by[sec17.get(p, '')] = by.get(sec17.get(p, ''), 0.0) + float(value17.get(p, 0.0))
        largest = max(sorted(by), key=by.get)
        gs = gtap22.get(h22, '')
        out.append(dict(hs22=h22, sector=chosen[h22], largest_parent_sector=largest, by_sector=by, gtap22=gs,
                        gtap_sectors=sorted(g2s.get(gs, set())),
                        agrees_with_gtap=('n/a' if not gs else ('yes' if chosen[h22] in g2s.get(gs, set()) else 'no'))))
    return out


def problems(rows):
    """Ambiguous HS22 codes whose sector is neither the largest-value HS17 source's sector nor GTAP's HS2022 sector,
    as a list of strings (empty means pass). A sector other than the largest source's needs GTAP H6 behind it."""
    return [f'{r["hs22"]}: mapped to {r["sector"]}, largest HS17 source {r["largest_parent_sector"]}, GTAP H6 {r["gtap22"] or "nothing"} ({";".join(r["gtap_sectors"]) or "no sector"})'
            for r in rows if r['sector'] != r['largest_parent_sector'] and r['agrees_with_gtap'] != 'yes']


def gtap_differs(rows):
    """Ambiguous HS22 codes whose sector differs from GTAP's HS2022 sector (report only)."""
    return [r for r in rows if r['agrees_with_gtap'] == 'no']
