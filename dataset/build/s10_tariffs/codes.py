"""One country-code map for S10 (choice country_code_join).

Every source code is turned into a project ISO through this module only:
BACI numeric codes, BACI iso3 labels, WITS/TRAINS reporter codes, WITS numeric
partner codes and preference-group members. A project ISO is a code in the S01
country map; an "alias -> X" row resolves to X (PSE -> PAL, S19 -> TWN,
XKX -> KSV). The old build mapped trade through one table and preference
members through another, which is how Palestinian exports lost every
preference (QA blocker 1). join_report() lists every code that does not land
on a region, and the stage turns that list into a hard check.
"""
import csv
from collections import defaultdict

# TRAINS historical reporter codes used in file names (coverage note).
TRAINS_REPORTER = {'ZAR': 'COD', 'TMP': 'TLS', 'SER': 'SRB', 'SUD': 'SDN', 'MNT': 'MNE', 'ANT': 'CUW', 'EUN': 'EUN'}
# M49 numbers that BACI stores under another number or does not carry.
# 158 Taiwan (BACI 490), 412 Kosovo (BACI 895), 729/736 Sudan, 688 Serbia, 728 South Sudan,
# 918 the EU reporter. BACI keeps its own numbers for six countries whose UN M49 number
# WITS uses in partner and group lists: 840 USA (BACI 842), 356 India (699), 250 France (251),
# 578 Norway (579), 756 Switzerland (757), 438 Liechtenstein (not in BACI).
# 234 (Faroe Islands) and 732 (Western Sahara) are countries with no schedule region; they
# resolve to their ISO and then fail to reach a region, by design.
EXTRA_M49 = {
    '158': 'TWN', '412': 'KSV', '490': 'TWN', '729': 'SDN', '736': 'SDN', '688': 'SRB',
    '895': 'KSV', '728': 'SSD', '918': 'EUN', '234': 'FRO', '732': 'ESH',
    '840': 'USA', '356': 'IND', '250': 'FRA', '578': 'NOR', '756': 'CHE', '438': 'LIE',
}


class CodeMap:
    def __init__(self, country_map_path, composite_members_path, baci_countries_path):
        self.region = {}          # project ISO -> region
        self.alias = {}           # alias code -> project ISO
        self.no_region = {}       # ISO in the map with no region -> status
        with open(country_map_path, newline='', encoding='utf-8') as fh:
            for row in csv.DictReader(fh):
                code, status, region = row['code'], row['status'], row['region']
                if status.startswith('alias'):
                    self.alias[code] = status.split('->', 1)[1].strip()
                elif status.startswith('non-country'):
                    continue
                elif region:
                    self.region[code] = region
                else:
                    self.no_region[code] = status
        for code, target in self.alias.items():
            if target not in self.region:
                raise SystemExit(f'S01 alias {code} -> {target} does not reach a region')
        self.members = defaultdict(set)
        for iso, reg in self.region.items():
            self.members[reg].add(iso)
        with open(composite_members_path, newline='', encoding='utf-8') as fh:
            for row in csv.DictReader(fh):
                iso = self.iso(row['member'])
                if self.region.get(iso) != row['composite']:
                    raise SystemExit(f"composite member {row['member']} is not mapped to {row['composite']}")
        self.baci = {}            # BACI numeric code (str, no leading zeros) -> project ISO or ''
        self.baci_label = {}
        with open(baci_countries_path, newline='', encoding='utf-8') as fh:
            for row in csv.DictReader(fh):
                num = str(int(row['country_code']))
                self.baci_label[num] = row['country_iso3']
                self.baci[num] = self.iso(row['country_iso3'])

    def iso(self, code):
        """Project ISO for an iso3 label, or the label itself when unknown (the join check catches it)."""
        code = (code or '').strip()
        return self.alias.get(code, code)

    def from_m49(self, num):
        """Project ISO for a WITS/M49 numeric code, or '' when no country has that number."""
        num = str(int(num))
        if num in EXTRA_M49:
            return self.iso(EXTRA_M49[num])
        return self.baci.get(num, '')

    def from_reporter(self, code):
        return self.iso(TRAINS_REPORTER.get(code, code))

    def region_of(self, iso):
        return self.region.get(iso, '')


def join_report(codemap, baci_value_by_code, member_isos, reporter_isos, unmapped_numeric):
    """Codes that do not reach a region, by source. Each list must be empty or named.

    baci_value_by_code: BACI numeric code -> 2022 trade value (thousand USD).
    member_isos: every ISO in an applied preference member list.
    reporter_isos: every schedule reporter ISO (EUN excluded; it is copied to EU27).
    unmapped_numeric: WITS numeric partner codes that resolved to no ISO.
    """
    out = {'baci': [], 'members': [], 'reporters': [], 'numeric': sorted(unmapped_numeric)}
    for num, value in sorted(baci_value_by_code.items()):
        iso = codemap.baci.get(num, '')
        if value > 0 and not codemap.region_of(iso):
            out['baci'].append((num, codemap.baci_label.get(num, '?'), iso, value))
    for iso in sorted(member_isos):
        if not codemap.region_of(iso):
            out['members'].append(iso)
    for iso in sorted(reporter_isos):
        if iso != 'EUN' and not codemap.region_of(iso):
            out['reporters'].append(iso)
    return out
