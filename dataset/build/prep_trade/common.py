"""Shared paths and the S01 region map for the trade prep.

This prep may read the fixed S01 region and sector sets and the HS6 tie-break
concordance. It does not read any later stage's output.
"""
import csv
import hashlib
import os

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
DATA = os.path.join(REPO, 'dataset', 'data')
S01 = os.path.join(REPO, 'dataset', 'stages', 'S01_sets_registry', 'output')
CFG = os.path.join(os.path.dirname(__file__), 'config')
CACHE = os.environ.get('TRADE_PREP_CACHE', '/tmp/trade-prep')
ART = os.environ.get('TRADE_PREP_ART', 'build_cache/trade-baci-batis')

# Manifest hashes the prep must check (dataset/data/MANIFEST.csv).
MANIFEST_SHA = {
    'baci/BACI_HS17_V202601.zip': '16aaa22d3b000cc87744c2c28ac97ce44394c3adf315ec259451d5bb4fcae609',
    'oecd_wto_batis/ebops2022.csv': 'f2a3987df63ef21d93177187718fcefa7689e9be3e1bdc4fc11f328e41fda803',
    'oecd_wto_batis/tot2022.csv': '9e1739b6ae1444391117ff1f27c9f7fa6a27b0a4cc7ce929785347e85f7e949f',
}
MANIFEST_BYTES = {
    'baci/BACI_HS17_V202601.zip': 794583540,
    'oecd_wto_batis/ebops2022.csv': 111824019,
    'oecd_wto_batis/tot2022.csv': 3591490,
}


def sha256(path, buf=1 << 22):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def load_region_map():
    """ISO3 -> region, using S01 country_region_map and source aliases.

    Returns (iso3_to_region, region_set, alias_note).
    A code with an empty region is not an economy assignment.
    """
    alias = {}
    with open(os.path.join(REPO, 'dataset', 'build', 'config', 's01', 'source_aliases.csv')) as f:
        for r in csv.DictReader(f):
            alias[r['code']] = r['iso3']
    # S01 also folds these in code even when the alias file is source-specific.
    alias.setdefault('PSE', 'PAL')
    alias.setdefault('XKX', 'KSV')
    iso3_to_region = {}
    with open(os.path.join(S01, 'country_region_map.csv')) as f:
        for r in csv.DictReader(f):
            if r['region']:
                iso3_to_region[r['code']] = r['region']
    regions = set()
    with open(os.path.join(S01, 'regions.csv')) as f:
        for r in csv.DictReader(f):
            regions.add(r['region'])
    # Aliases point at an ISO3 that itself has a region.
    for src, iso in list(alias.items()):
        reg = iso3_to_region.get(iso) or iso3_to_region.get(alias.get(iso, ''), '')
        if reg:
            iso3_to_region[src] = reg
            iso3_to_region[iso] = reg
    missing = sorted(regions - set(iso3_to_region.values()))
    if missing:
        raise SystemExit(f'S01 regions with no member in country_region_map: {missing}')
    return iso3_to_region, regions


def load_aggregates():
    """Source codes that are not economies (world, EU, OECD, ...)."""
    out = {}
    with open(os.path.join(REPO, 'dataset', 'build', 'config', 's01', 'non_country_codes.csv')) as f:
        for r in csv.DictReader(f):
            out.setdefault(r['source'], set()).add(r['code'])
    return out
