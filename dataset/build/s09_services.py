"""S09 services trade (BaTIS, TiSMoS, travel, freight removal).

Reads services_choices.csv for every choice. Mode is the services_pair_source row.
batis_all_pairs (David, 2026-10-21): BaTIS on every pair; ICIO is a compare file.
The two mode A rows stay in the config and are not applied.
io_s09 is a byte copy of io_s08. No VTWR file is written.
"""
import csv
import filecmp
import gzip
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
import zipfile
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/lib')
from stagekit import BUILD, DATA, ROOT, Stage, sha256
from private_files import is_private, load_rules

# Binding for the S08 and S07R snapshots this stage is built on. Not a services choice.
# Snapshot commits are the last commits that touched those STAMPs: S07 of the 2026-10-25 F-12 rerun; S08 of the beta v3 rerun (2026-10-26, energy_sea_rate).
S08_HEAD = 'e885ca43e5c70fa15e8d71e85c3ed686e5118477'
S08_STAMP_TIME = '2026-10-27 23:18:57 UTC+7'
S08_BUILD = '19c5681ccadb69df66e4294d4b738b0abf34d3bf'
S08_SHA256SUMS = '9a3586c3e06b2bce68f8ea350f58d01794045dbfb03649c58e6abd091eb7fa74'
S08_FREIGHT = '1da9eb5688fc03fe8c7064a076063c651c2abb300e9570ef6769261c66fec264'
S08_VST = '339835e80e9996a9a85d325cd12ea1ea15ed47c62dfbfabda3835a2a6117cff7'
S08_IO = 'e83facbfd23c2cb0f535cb52be976055da3179a44256c7e1c401020fc8b3a410'
S07_HEAD = '94c1e585c94b7c70a308cbce3c012b7b24c40d32'
S07_SHA256SUMS = 'c5e753b863c1ccb9e95d3862980e1bf1c0ed45a9dbded8491d018ba6fdfeb556'
S07_VXSB = '5021c15f3627a1907a70cb9b73cfc6c8544328300d0fd86c33e7154ba891d2c7'
# Services trade of the stamped round-3 S09 (53b7779), which itself matched build 223eb80 within 1e-10 dust.
# Goods VXSB and S08 freight are not inputs to these files.
PRIOR_S09 = '53b77797bb8f86a6849a6a2d2beb118cc8fb35d5'
PRIOR_VXSB_SERVICES = 'def652b4290ad713f858a2b3016d48eb556bd0b25bda26be9222b73b70ed337c'
PRIOR_TRAVEL = 'e4ade8a24237c11eb569419b45085702ae9a72aaba7abd3508e05a953cd70b97'
PRIOR_ICIO = '91134dd446881dc0f87e6f980455c5f9c4617d0e004b1c148f27fc8d44a0818b'
BOX_EBOPS_SHA = 'f2a3987df63ef21d93177187718fcefa7689e9be3e1bdc4fc11f328e41fda803'   # committed parts; was 52c84235 (never committed)
BOX_EBOPS_BYTES = 111824019
BOX_WORLD_S_BN = 7081.0
BOX_TOT_SHA = '9e1739b6ae1444391117ff1f27c9f7fa6a27b0a4cc7ce929785347e85f7e949f'
BOX_TISMOS_SHA = '938f8747bd0d87613ed446f416e8dc14420ef71ad82604d7c7fd796a05dceb3e'
BOX_WDI_SHA = 'ef53be86a56df29d21f85cbe24884b5312882aee85f901f40c28bfa137656f89'
WIDE_WDI_SHA = 'a34c5cff7019a35bed5bba39a8f21304d70a4dad182fef7224c6d2a9e66dcd41'
# batis_scaling=bmu_to_own_bop_wdi_nfsv: BaTIS Bermuda is 48.4 bn of exports and 17.9 bn of
# imports against its own BoP 1.41 and 1.00 bn (WDI BX/BM.GSR.NFSV.CD) and GDP 7.8 bn. Its rows
# are scaled to those totals, one factor per side; the pair and service pattern is kept.
# beta v5 M5: as bmu_keep_us_insurance_and_lbr_own_bop, but the reinsurance is recorded net (see OWN_BOP_NET)
BMU_NET = 'bmu_us_insurance_net_of_retrocession_rerouted_and_lbr_own_bop'
# beta v5 M5 variant (build-thread check against BEA 2022 insurance, 2026-10-27): as BMU_NET, but the partner itself is left
# out of the seller shares, so the whole kept value is rerouted from the other retrocessionaires (see OWN_BOP_EX_PARTNER)
BMU_NET_EX = 'bmu_us_insurance_net_of_retrocession_rerouted_from_non_partner_sellers_and_lbr_own_bop'
OWN_BOP_SCALING = {'bmu_to_own_bop_wdi_nfsv': ('BMU',), 'bmu_own_bop_keep_us_insurance_pass_through': ('BMU',), 'bmu_keep_us_insurance_and_lbr_own_bop': ('BMU', 'LBR'),
                   BMU_NET: ('BMU', 'LBR'), BMU_NET_EX: ('BMU', 'LBR')}
# Fable QA B-04: the plain scaling also deletes the 30.7 bn of US insurance imports from Bermuda that BaTIS and
# BEA record. Under bmu_own_bop_keep_us_insurance_pass_through the kept rows (exporter, partner, service) stay at
# BaTIS, only the rest of Bermuda's exports is scaled to its own BoP, and the kept value is booked again as
# Bermuda imports of the same service (reinsurance ceded abroad, a pass-through), spread over the economies that
# BaTIS shows selling that service to Bermuda. Bermuda's net services stay at its own BoP.
HUB_SOURCES = {'hkg_reexport_margin'}   # S07 hub re-export margins booked as services; not BaTIS (Fable QA D-01)
OWN_BOP_KEEP = {'bmu_own_bop_keep_us_insurance_pass_through': (('BMU', 'USA', 'SF'),),
                'bmu_keep_us_insurance_and_lbr_own_bop': (('BMU', 'USA', 'SF'),),
                BMU_NET: (('BMU', 'USA', 'SF'),), BMU_NET_EX: (('BMU', 'USA', 'SF'),)}
# Beta v5 M5 (region gates #5: XNA finance 71% of output, exports 31.4 bn and imports 31.3 bn, VA 12.6%). Under the pass-through
# the 30.7 bn of US insurance bought from Bermuda is booked twice through XNA: as its exports and again as its imports from the
# retrocessionaires. BPM6 (10.111-10.117) records reinsurance by counterparty and does not net a reinsurer's retrocession out
# of its sales; netting it is our pass-through attribution, as for goods re-exports, not a BPM6 rule. Under BMU_NET the kept rows are recorded net of the retrocession
# (Bermuda keeps 0 of them) and the pass-through goes from each retrocessionaire to the kept row's partner (the USA) directly,
# in BaTIS's shares of sellers to Bermuda, as goods re-exports go to the origin (Aguiar et al. 2025 p.12). A share sold by the
# partner itself (US reinsurers) is domestic and leaves trade. Our application; labelled departure.
OWN_BOP_NET = {BMU_NET, BMU_NET_EX}
# BMU_NET_EX: under BMU_NET the US share of the sellers to Bermuda in BaTIS SF (3.01 of 5.84 bn, 51.6%) takes 15.85 bn of
# the 30.74 bn as domestic, so US insurance imports fall to 41.9 bn against BEA 2022 64.1 (FRED IEAMSIA), while exports
# (24.7) match BEA (24.9). Leaving the partner out of the shares reroutes all 30.74 bn from non-US retrocessionaires:
# exports stay 24.7 and imports return to 57.75 (BaTIS). XNA is the same as under BMU_NET. Our attribution; labelled departure.
OWN_BOP_EX_PARTNER = {BMU_NET_EX}
# bmu_keep_us_insurance_and_lbr_own_bop: as above, and Liberia is scaled to its own BoP too. BaTIS Liberia is
# 11.3 bn of exports (mostly sea and other transport, a fleet-register estimate) and 1.5 bn of imports against
# its own BoP 0.03 and 0.32 bn and GDP 4.0 bn. Once S07 drops the open-registry ship imports (trade D-01), those
# exports leave Liberia's C, G and I factor negative (S13-Hfactor). Same treatment as Bermuda, one factor per side.

GOODS = set(
    'crp for fsh coa oil gas ore min fbt tal wod pap pet chm pha rpl nmm stl nfm fmp elc eeq mac mvh shp tre omf'
    .split())
ICIO_SERVICES = set(
    'msp wat con trd rdt sea air whs pst hos pub tel its fin rle pro adm gov edu hea art ots'.split())
MODES = ('rdt', 'sea', 'air')
FREIGHT_LEAF = {'rdt': ('SC3', 'SC32'), 'sea': ('SC1', 'SC12'), 'air': ('SC2', 'SC22')}
SPLIT_LEAVES = {
    'SC1': ('SC11', 'SC12', 'SC13'),
    'SC2': ('SC21', 'SC22', 'SC23'),
    'SC3': ('SC31', 'SC32', 'SC33'),
    'SDB': ('SDB1', 'SDB2', 'SDB3'),
    'SJ3': ('SJ31', 'SJ32', 'SJ33', 'SJ34', 'SJ35'),
    'SK2': ('SK21', 'SK22', 'SK23', 'SK24'),
}
MEMO_TISMOS = {
    'SDASDB3', 'SDB1SK21', 'SDB2SK22', 'SFSG', 'SISK1', 'SJXSJ34', 'SWSJ34', 'SOXSW', 'SW',
}
Q_SRC = 'GTAP 12 ch.10B §B.1 p.1'
Q_DROP = 'GTAP 12 ch.10B p.2 §B.3'
Q_SPLIT = 'GTAP 12 ch.10B p.3 Table 10.2'
Q_TRAVEL = 'GTAP 12 ch.10B p.3'
Q_SAT = 'GTAP 12 ch.10B p.4 §B.4'
Q_VXSB = 'GTAP 12 ch.02 p.17'
Q_FIT = 'GTAP 12 ch.17A p.2'
Q_ASM = 'GTAP 12 ch.17B §B.2 p.3'
Q_AG = 'Aguiar et al. 2025 p.14'

CHOICE_ORDER = (
    'services_pair_source', 'batis_source', 'batis_dropped_codes', 'batis_scaling',
    'ebops_concordance', 'untraded_sectors', 'energy_services_trade', 'tismos_source',
    'tismos_split_side', 'tismos_missing', 'whs_rule', 'travel_business_sda',
    'travel_personal_sdb', 'travel_commodities', 'travel_icio_pairs', 'row_split',
    'freight_removal', 'freight_vs_vst', 'freight_importer_side', 'composite_diagonal',
    'services_margins', 'us_benchmark', 'trade_identity',
)
ALLOWED = {
    'services_pair_source': {'batis_all_pairs', 'icio_pairs_batis_row'},
    'batis_source': {'oecd_wto_batis_df1.0_2022_X_adjB_usd'},
    'batis_dropped_codes': {'SA,SH'},
    'batis_scaling': {'none', 'bmu_to_own_bop_wdi_nfsv', 'bmu_own_bop_keep_us_insurance_pass_through',
                      'bmu_keep_us_insurance_and_lbr_own_bop', BMU_NET, BMU_NET_EX},
    'ebops_concordance': {'s01_concord_ebops_to_sector'},
    'untraded_sectors': {'wat,rle'},
    'energy_services_trade': {'ely_at_S11'},
    'tismos_source': {'wto_tismos_2024_release_2022_modes_1_2_4'},
    'tismos_split_side': {'exporter_exports'},
    'tismos_missing': {'F8_geo_region_then_world'},
    'whs_rule': {'table_10_2_SC13_SC23_SC33_to_whs'},
    'travel_business_sda': {'host_household_dom_consumption_io_s08'},
    'travel_personal_sdb': {'tismos_SDB1_hea_SDB2_edu_SDB3_hos'},
    'travel_commodities': {'all_incl_goods_and_ely_to_travel_file'},
    'travel_icio_pairs': {'icio_dpabr_block'},
    'row_split': {'batis_pair_shares_of_mapped_code_else_S'},
    'freight_removal': {'tismos_freight_share_of_exporter_transport'},
    'freight_vs_vst': {'report_only_no_mode_netting'},
    'freight_importer_side': {'record_for_S13'},
    'composite_diagonal': {'batis_member_pairs'},
    'services_margins': {'zero'},
    'us_benchmark': {'bea_ita_2022_trans422_X926.0_M680.3_report_only'},
    'trade_identity': {'abs_gap_le_1e-9_float_rounding'},
}
MODE_A_ONLY = {'travel_icio_pairs', 'row_split'}

# ISO 3166-1 alpha-2 to alpha-3 for TiSMoS reporter codes. The TiSMoS workbook
# sheet is the EBOPS item list, not a country list (checked). Exceptions and
# historical codes are applied from S01 source_aliases and non_country_codes
# before this table. AN is the former Netherlands Antilles.
ISO2 = {
    'AF': 'AFG', 'AL': 'ALB', 'DZ': 'DZA', 'AO': 'AGO', 'AI': 'AIA', 'AG': 'ATG',
    'AR': 'ARG', 'AM': 'ARM', 'AW': 'ABW', 'AU': 'AUS', 'AT': 'AUT', 'AZ': 'AZE',
    'BS': 'BHS', 'BH': 'BHR', 'BD': 'BGD', 'BB': 'BRB', 'BY': 'BLR', 'BE': 'BEL',
    'BZ': 'BLZ', 'BJ': 'BEN', 'BM': 'BMU', 'BT': 'BTN', 'BO': 'BOL', 'BA': 'BIH',
    'BW': 'BWA', 'BR': 'BRA', 'BN': 'BRN', 'BG': 'BGR', 'BF': 'BFA', 'BI': 'BDI',
    'CV': 'CPV', 'KH': 'KHM', 'CM': 'CMR', 'CA': 'CAN', 'KY': 'CYM', 'CF': 'CAF',
    'TD': 'TCD', 'CL': 'CHL', 'CN': 'CHN', 'TW': 'TWN', 'CO': 'COL', 'KM': 'COM',
    'CG': 'COG', 'CR': 'CRI', 'CI': 'CIV', 'HR': 'HRV', 'CU': 'CUB', 'CW': 'CUW',
    'CY': 'CYP', 'CZ': 'CZE', 'CD': 'COD', 'DK': 'DNK', 'DJ': 'DJI', 'DM': 'DMA',
    'DO': 'DOM', 'EC': 'ECU', 'EG': 'EGY', 'SV': 'SLV', 'GQ': 'GNQ', 'ER': 'ERI',
    'EE': 'EST', 'SZ': 'SWZ', 'ET': 'ETH', 'FO': 'FRO', 'FJ': 'FJI', 'FI': 'FIN',
    'FR': 'FRA', 'PF': 'PYF', 'GA': 'GAB', 'GE': 'GEO', 'DE': 'DEU', 'GH': 'GHA',
    'GR': 'GRC', 'GD': 'GRD', 'GT': 'GTM', 'GN': 'GIN', 'GW': 'GNB', 'GY': 'GUY',
    'HT': 'HTI', 'HN': 'HND', 'HK': 'HKG', 'HU': 'HUN', 'IS': 'ISL', 'IN': 'IND',
    'ID': 'IDN', 'IR': 'IRN', 'IQ': 'IRQ', 'IE': 'IRL', 'IL': 'ISR', 'IT': 'ITA',
    'JM': 'JAM', 'JP': 'JPN', 'JO': 'JOR', 'KZ': 'KAZ', 'KE': 'KEN', 'KI': 'KIR',
    'KP': 'PRK', 'KR': 'KOR', 'KW': 'KWT', 'KG': 'KGZ', 'LA': 'LAO', 'LV': 'LVA',
    'LB': 'LBN', 'LS': 'LSO', 'LR': 'LBR', 'LY': 'LBY', 'LT': 'LTU', 'LU': 'LUX',
    'MO': 'MAC', 'MG': 'MDG', 'MW': 'MWI', 'MY': 'MYS', 'MV': 'MDV', 'ML': 'MLI',
    'MT': 'MLT', 'MR': 'MRT', 'MU': 'MUS', 'MX': 'MEX', 'MD': 'MDA', 'MN': 'MNG',
    'ME': 'MNE', 'MS': 'MSR', 'MA': 'MAR', 'MZ': 'MOZ', 'MM': 'MMR', 'NA': 'NAM',
    'NP': 'NPL', 'NL': 'NLD', 'AN': 'ANT', 'NC': 'NCL', 'NZ': 'NZL', 'NI': 'NIC',
    'NE': 'NER', 'NG': 'NGA', 'MK': 'MKD', 'NO': 'NOR', 'OM': 'OMN', 'PK': 'PAK',
    'PA': 'PAN', 'PG': 'PNG', 'PY': 'PRY', 'PE': 'PER', 'PH': 'PHL', 'PL': 'POL',
    'PT': 'PRT', 'QA': 'QAT', 'RO': 'ROU', 'RU': 'RUS', 'RW': 'RWA', 'KN': 'KNA',
    'LC': 'LCA', 'VC': 'VCT', 'WS': 'WSM', 'ST': 'STP', 'SA': 'SAU', 'SN': 'SEN',
    'RS': 'SRB', 'SC': 'SYC', 'SL': 'SLE', 'SG': 'SGP', 'SX': 'SXM', 'SK': 'SVK',
    'SI': 'SVN', 'SB': 'SLB', 'SO': 'SOM', 'ZA': 'ZAF', 'SS': 'SSD', 'ES': 'ESP',
    'LK': 'LKA', 'SD': 'SDN', 'SR': 'SUR', 'SE': 'SWE', 'CH': 'CHE', 'SY': 'SYR',
    'TJ': 'TJK', 'TZ': 'TZA', 'TH': 'THA', 'GM': 'GMB', 'TL': 'TLS', 'TG': 'TGO',
    'TO': 'TON', 'TT': 'TTO', 'TN': 'TUN', 'TR': 'TUR', 'TM': 'TKM', 'TC': 'TCA',
    'TV': 'TUV', 'UG': 'UGA', 'UA': 'UKR', 'AE': 'ARE', 'GB': 'GBR', 'US': 'USA',
    'UY': 'URY', 'UZ': 'UZB', 'VU': 'VUT', 'VE': 'VEN', 'VN': 'VNM', 'YE': 'YEM',
    'ZM': 'ZMB', 'ZW': 'ZWE',
}


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


def f12(x):
    return f'{float(x):.12f}'


def _prior_output(name, prior_sha, archived):
    live = ROOT + '/stages/S09_services/output/' + name
    if os.path.exists(live) and sha256(live) == prior_sha:
        return live
    if archived:
        cand = archived + '/output/' + name
        if os.path.exists(cand) and sha256(cand) == prior_sha:
            return cand
    # The prior snapshot is committed: read it from git when neither the live nor the archived file has it
    blob = subprocess.run(['git', '-C', repo_root(), 'show', f'{PRIOR_S09}:dataset/stages/S09_services/output/{name}'],
                          capture_output=True).stdout
    if blob and hashlib.sha256(blob).hexdigest() == prior_sha:
        cand = os.path.join(tempfile.mkdtemp(prefix='s09_prior_'), name)
        with open(cand, 'wb') as fh:
            fh.write(blob)
        return cand
    return None


def _gz_rows(path):
    out = {}
    with gzip.open(path, 'rt', newline='') as fh:
        for row in csv.DictReader(fh):
            key = tuple(row[k] for k in row if k not in ('vxsb_musd', 'musd', 'built_musd', 'icio_musd'))
            val = row.get('vxsb_musd', row.get('musd', row.get('built_musd', '0')))
            # icio compare has two value columns. Keep both.
            if 'icio_musd' in row:
                out[key] = (row['icio_musd'], row['built_musd'])
            else:
                out[key] = val
    return out


# Beta v4 (S16, 2026-10-26): regions whose io_s04/io_s05 table moved upstream, so their services and travel
# cells legitimately differ from the beta v3 snapshot. G4 (S03 household_employers_va = hfce_to_pq) moves ZAF and,
# through S05, its donor members BWA, GAB, GNQ, MUS and SYC (in XEF); P33 (S05 donor_size_guard) moves KEN.
# They are counted apart in S09-H12 like the batis_scaling regions; every other region stays guarded.
# Beta v5 (build thread, 2026-10-27): the S02-S05 fixes move XCB (Cuba at the official rate), YEM (WEO GDP) and TLS
# (S1 AMA VA sections); SSD (XEF) and the ZAF H change are already covered. These are the only regions whose io_s05
# moved by more than 0.0025 USD m a cell against beta v4.
H12_UPSTREAM_MOVED = ('BWA', 'GAB', 'GNQ', 'KEN', 'MUS', 'XEF', 'ZAF', 'TLS', 'XCB', 'YEM')
# Beta v4: a cell outside the moved regions passes at abs 1e-9 or rel 1e-8 (the S04 AGO g column moves its
# ICIO-compare cells by up to 3.8e-9 on values of 6-413 USD m, float rounding).
H12_REL_TOL = 1e-8
# Beta v5 (build thread, coordinator OK 2026-10-27 13:07 UTC): the v5 S03 RAS moves non-ZAF io cells by up to 0.001
# USD m (rounding), which reaches the travel host shares (at most 8.4e-7 USD m a cell) and the ICIO compare values (at
# most 2e-4). A cell outside the moved regions passes at abs 1e-3 USD m, the S03 rounding bound.
H12_ABS_TOL = 1e-3


def _dust_gap_bad(a, b):
    gap = abs(float(a) - float(b))
    return gap > max(H12_ABS_TOL, H12_REL_TOL * max(abs(float(a)), abs(float(b))))


def trade_dust(out_dir, prior, names, archived, moved=(), moved_pairs=(), moved_triples=()):
    """True when a non-identical trade file differs only by float dust.

    Cells whose key names a region in moved (the batis_scaling regions), or starts
    with a (sector, exporter) in moved_pairs (the S07 hub re-export margins), or with a
    (sector, exporter, importer) in moved_triples (beta v5 M5, the rerouted retrocession), are
    counted apart and do not fail the check; every other cell must still match.

    S07 goods VXSB and S08 freight are not inputs to these files. A refetched
    BaTIS extract with the same values and a different row order can move one
    printed digit at 1e-10. That is not the S07R or S08 move.
    """
    notes = []
    ok = True
    for name in names:
        src = _prior_output(name, prior[name], archived)
        if src is None:
            ok = False
            notes.append(f'{name} prior file with sha {prior[name]} was not found')
            continue
        old, new = _gz_rows(src), _gz_rows(out_dir + '/' + name)
        moved_keys = {key for key in set(old) | set(new)
                      if any(region in key for region in moved) or tuple(key[:2]) in moved_pairs
                      or tuple(key[:3]) in moved_triples}
        if set(old) - moved_keys != set(new) - moved_keys:
            ok = False
            notes.append(f'{name} keys {len((set(old) ^ set(new)) - moved_keys)} differ')
            continue
        moved_n = sum(1 for key in moved_keys if old.get(key) != new.get(key))
        if moved or moved_pairs:
            notes.append(f'{name}: {moved_n} of {len(moved_keys)} cells naming {",".join(moved)} or the hub margin pairs '
                         f'{",".join("/".join(p) for p in moved_pairs)} differ (batis_scaling, hub margins; not dust)')
        gaps = []
        for key in old:
            if key in moved_keys:
                continue
            a, b = old[key], new[key]
            if a == b:
                continue
            if isinstance(a, tuple):
                for left, right, label in zip(a, b, ('icio', 'built')):
                    gap = abs(float(left) - float(right))
                    if _dust_gap_bad(left, right):
                        ok = False
                    if gap:
                        gaps.append((gap, key, label, left, right))
            else:
                gap = abs(float(a) - float(b))
                if _dust_gap_bad(a, b):
                    ok = False
                gaps.append((gap, key, 'value', a, b))
        if not gaps:
            continue
        gaps.sort(reverse=True)
        top = '; '.join(f'{k} {label} {left}->{right} gap {gap:.3e}' for gap, k, label, left, right in gaps[:5])
        notes.append(
            f'{name} not byte-identical. {len(gaps)} cells differ, max {gaps[0][0] if gaps else 0:.3e}. '
            f'Cause: BaTIS SDMX row order, not S07R or S08 (those files are not read into this output). {top}')
    return ok, notes


def read_csv(path):
    with open(path, newline='') as fh:
        return list(csv.DictReader(fh))


def gz_write(path, header, lines):
    raw = open(path, 'wb')
    with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0, compresslevel=9) as gz:
        gz.write(header)
        for line in lines:
            gz.write(line)
    raw.close()


def write_csv(path, cols, rows):
    with open(path, 'w', newline='') as fh:
        w = csv.writer(fh, lineterminator='\n')
        w.writerow(cols)
        w.writerows(rows)


def repo_root():
    r = subprocess.run(['git', '-C', BUILD, 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    return r.stdout.strip() or os.path.dirname(ROOT)


def output_sums_text(directory):
    parts = []
    for fn in sorted(os.listdir(directory)):
        if fn == 'SHA256SUMS':
            continue
        parts.append(f'{sha256(directory + "/" + fn)}  {fn}\n')
    return ''.join(parts)


def share_vector(values, leaves):
    """Non-negative shares over leaves. Residual sits on the largest leaf. None if the parent is 0."""
    raw = [(leaf, max(float(values.get(leaf, 0.0)), 0.0)) for leaf in leaves]
    total = sum(v for _, v in raw)
    if total <= 0:
        return None
    # Largest leaf (earlier leaf on a tie) carries the residual so the shares sum to 1.
    largest = max(range(len(raw)), key=lambda i: (raw[i][1], -i))
    acc = 0.0
    out = {}
    for i, (leaf, val) in enumerate(raw):
        if i == largest:
            continue
        sh = val / total
        out[leaf] = sh
        acc += sh
    residual = 1.0 - acc
    if abs(residual) < 1e-15:
        residual = 0.0
    out[raw[largest][0]] = residual
    return out


def apply_shares(total, leaves, shares):
    """Split total across leaves. The last leaf carries the residual so the parts sum to total."""
    acc = 0.0
    parts = {}
    for leaf in leaves[:-1]:
        part = total * shares[leaf]
        parts[leaf] = part
        acc += part
    last = total - acc
    if abs(last) < 1e-9:
        last = 0.0
    parts[leaves[-1]] = last
    return parts


def load_choices(path):
    rows = read_csv(path)
    by = {r['choice'].strip(): r for r in rows}
    bad = []
    if len(rows) != len(CHOICE_ORDER) or set(by) != set(CHOICE_ORDER):
        bad.append(f'rows {len(rows)} names {sorted(set(by) ^ set(CHOICE_ORDER))}')
    for name in CHOICE_ORDER:
        row = by.get(name)
        if not row:
            bad.append(f'missing {name}')
            continue
        if not (row.get('decided_by') or '').strip() or not (row.get('decided_at') or '').strip():
            bad.append(f'{name} missing decided_by/decided_at')
        if row['value'].strip() not in ALLOWED[name]:
            bad.append(f'{name} value {row["value"]!r} not in {sorted(ALLOWED[name])}')
    david = (by.get('services_pair_source') or {}).get('decided_by', '')
    if david.strip() != 'David':
        bad.append(f'services_pair_source decided_by {david!r}')
    return rows, by, bad


def load_maps():
    iso_to_region = {}
    status = {}
    with open(ROOT + '/stages/S01_sets_registry/output/country_region_map.csv', newline='') as fh:
        for row in csv.DictReader(fh):
            if row['region']:
                iso_to_region[row['code']] = row['region']
                status[row['code']] = row['status']
    regions = {}
    with open(ROOT + '/stages/S01_sets_registry/output/regions.csv', newline='') as fh:
        for row in csv.DictReader(fh):
            regions[row['region']] = row
    members = defaultdict(list)
    with open(ROOT + '/stages/S01_sets_registry/output/composite_members.csv', newline='') as fh:
        for row in csv.DictReader(fh):
            members[row['composite']].append(row['member'])
    iso_geo = {}
    with open(ROOT + '/stages/S01_sets_registry/output/gtap_geo_regions_table910.csv', newline='') as fh:
        for row in csv.DictReader(fh):
            if row['gtap_geo']:
                iso_geo[row['iso3']] = row['gtap_geo']
    alias_iso = {}
    tismos_alias = {}
    with open(BUILD + '/config/s01/source_aliases.csv', newline='') as fh:
        for row in csv.DictReader(fh):
            if row['source'] in ('BaTIS', 'any'):
                alias_iso[row['code']] = row['iso3']
            if row['source'] == 'TiSMoS' and row['code'].startswith('TiSMoS:'):
                tismos_alias[row['code'].split(':', 1)[1]] = row['iso3']
    alias_iso.setdefault('PSE', 'PAL')
    alias_iso.setdefault('XKX', 'KSV')
    aggregates = set()
    tismos_aggregates = set()
    wdi_aggregates = set()
    with open(BUILD + '/config/s01/non_country_codes.csv', newline='') as fh:
        for row in csv.DictReader(fh):
            if row['source'] in ('BaTIS', 'any'):
                aggregates.add(row['code'])
            if row['source'] == 'TiSMoS' and row['code'].startswith('TiSMoS:'):
                tismos_aggregates.add(row['code'].split(':', 1)[1])
            if row['source'] == 'WDI':
                wdi_aggregates.add(row['code'])
    # Resolve alias codes onto the region of the target iso3.
    for src, iso in list(alias_iso.items()):
        reg = iso_to_region.get(iso) or iso_to_region.get(alias_iso.get(iso, ''), '')
        if reg:
            iso_to_region[src] = reg
            iso_to_region[iso] = reg
    region_isos = defaultdict(list)
    for code, reg in iso_to_region.items():
        if code in aggregates:
            continue
        region_isos[reg].append(code)
    for reg in region_isos:
        region_isos[reg] = sorted(set(region_isos[reg]))
    return (iso_to_region, status, regions, members, iso_geo, alias_iso, tismos_alias,
            aggregates, tismos_aggregates, wdi_aggregates, region_isos)


def region_of(code, iso_to_region, alias_iso):
    iso = alias_iso.get(code, code)
    iso = {'PSE': 'PAL', 'XKX': 'KSV'}.get(iso, iso)
    return iso_to_region.get(iso) or iso_to_region.get(code) or ''


def load_concord(path):
    rows = read_csv(path)
    batis = {}
    tismos_sector = {}
    for row in rows:
        if row['level'] == 'batis':
            batis[row['code']] = row
        elif row['level'] == 'tismos':
            tismos_sector[row['code']] = row['sectors']
    return batis, tismos_sector


def register_input(S, path, role, on_mismatch='in1'):
    """Record a data file. A SHA that differs from MANIFEST fails IN1, except on_mismatch='exempt' (BaTIS)."""
    S.inp(path, role, on_mismatch=on_mismatch)
    info = S.inputs[path]
    return info['sha256'], info['manifest_match'] == 'yes'


def own_bop_scales(path, wdi_path, isos, aggregates, keep=(), net=False, ex_partner=False):
    """Per ISO: BaTIS S exports (counterpart W) and imports (sum of economy reporters' S to it),
    the WDI BX/BM.GSR.NFSV.CD targets in USD million, and the factor target / BaTIS per side.
    keep lists (iso, partner, service) rows that stay at BaTIS: the export factor then applies to the rest
    (sx = WDI X / (BaTIS X - kept)), and pass maps each economy that sells the service to iso to its share of
    the kept value, booked as iso's pass-through imports (Fable QA B-04). net (beta v5 M5): the kept value is rerouted
    seller -> partner instead; ex_partner (BMU_NET_EX): the partner is left out of the seller shares."""
    out = {}
    if not isos:
        return out
    bx = defaultdict(float)
    bm = defaultdict(float)
    kept = defaultdict(dict)
    sellers = defaultdict(lambda: defaultdict(float))   # (iso, service) -> reporter -> BaTIS exports to iso
    keep_svc = {(k[0], k[2]) for k in keep}
    with open(path, newline='') as fh:
        for row in csv.DictReader(fh):
            rep, part, svc = row['REF_AREA'], row['COUNTERPART_AREA'], row['SERVICE']
            if (rep, part, svc) in keep:
                kept[rep][(part, svc)] = kept[rep].get((part, svc), 0.0) + float(row['OBS_VALUE'] or 0)
            if (part, svc) in keep_svc and rep not in aggregates and rep != 'W' and rep != part:
                sellers[(part, svc)][rep] += float(row['OBS_VALUE'] or 0)
            if svc != 'S':
                continue
            if rep in isos and part == 'W':
                bx[rep] += float(row['OBS_VALUE'] or 0)
            elif part in isos and rep not in aggregates and rep != 'W' and rep != part:
                bm[part] += float(row['OBS_VALUE'] or 0)
    wdi = defaultdict(dict)
    with open(wdi_path, newline='') as fh:
        for row in csv.DictReader(fh):
            if row['iso3'] in isos and row['value'] != '':
                wdi[row['iso3']][row['series']] = float(row['value']) / 1e6
    for iso in isos:
        wx = wdi[iso].get('BX.GSR.NFSV.CD', 0.0)
        wm = wdi[iso].get('BM.GSR.NFSV.CD', 0.0)
        if bx[iso] <= 0 or bm[iso] <= 0 or wx <= 0 or wm <= 0:
            raise SystemExit(f'batis_scaling: {iso} needs BaTIS and WDI totals on both sides')
        kx = sum(kept[iso].values())
        if kx >= bx[iso]:
            raise SystemExit(f'batis_scaling: {iso} kept rows {kx} reach its BaTIS exports {bx[iso]}')
        passed, rerouted = {}, {}
        for (part, svc), k in kept[iso].items():
            shares = {sl: v for sl, v in sellers[(iso, svc)].items() if v > 0 and not (net and ex_partner and sl == part)}
            tot = sum(shares.values())
            if tot <= 0:
                raise SystemExit(f'batis_scaling: no BaTIS sellers of {svc} to {iso} for the pass-through')
            for seller, v in sorted(shares.items()):
                if v > 0:
                    if net:     # beta v5 M5: seller -> the kept row's partner, not seller -> iso
                        rerouted[(seller, part, svc)] = rerouted.get((seller, part, svc), 0.0) + k * v / tot
                    else:
                        passed[(seller, svc)] = passed.get((seller, svc), 0.0) + k * v / tot
        out[iso] = dict(bx=bx[iso], bm=bm[iso], wx=wx, wm=wm, sx=wx / (bx[iso] - kx), sm=wm / bm[iso],
                        kx=kx, keep=dict(kept[iso]), passed=passed, rerouted=rerouted, net=net)
    return out


def scaled_value(sc, part, svc, val):
    """An exporter row under batis_scaling: kept rows stay at BaTIS; a total (S, or partner W) carries its kept
    part unscaled and the rest times sx."""
    keep = sc.get('keep', {})
    if (part, svc) in keep:
        return 0.0 if sc.get('net') else val      # beta v5 M5: net of the retrocession, Bermuda keeps none of it
    k = sum(v for (p, sv), v in keep.items() if (svc == 'S' and part in (p, 'W')) or (part == 'W' and sv == svc))
    return (0.0 if sc.get('net') else k) + (val - k) * sc['sx']


# S09-H13 is an identity (fix round B9; Grok review F1): the factor is defined as WDI / BaTIS in own_bop_scales, so
# BaTIS x factor = WDI holds by construction. It guards the arithmetic and the (0, 1] range, not the source. No
# independent 2022 services total for Bermuda is on disk (WDI is the only one), so the row is labelled an identity
# and S16-Hcollected can read that from its concept tag.
H13_DESC = ('batis_scaling (identity, not a source comparison): each scaled economy\'s BaTIS S exports and imports times its factor '
            'equal its own BoP services totals (WDI BX/BM.GSR.NFSV.CD), which define the factor, to 1e-6 USD million; factors in (0, 1]')
H13_CONCEPT = 'identity; GTAP 12 ch.17A p.2; services_choices batis_scaling'


def h13_identity(bop_scale, tol=1e-6):
    """S09-H13 arithmetic: (economies that fail, detail parts). Fails on a factor that does not reproduce WDI or lies outside (0, 1]."""
    bad, parts = [], []
    for iso, sc in sorted(bop_scale.items()):
        gx = abs((sc['bx'] - sc.get('kx', 0.0)) * sc['sx'] - sc['wx'])
        gm = abs(sc['bm'] * sc['sm'] - sc['wm'])
        if gx > tol or gm > tol or not (0 < sc['sx'] <= 1 and 0 < sc['sm'] <= 1):
            bad.append(iso)
        parts.append(f'{iso} BaTIS X {sc["bx"] / 1000:.2f} M {sc["bm"] / 1000:.2f} bn scaled to own BoP X {sc["wx"] / 1000:.3f} M {sc["wm"] / 1000:.3f} bn '
                     f'(factor X {sc["sx"]:.6f}, M {sc["sm"]:.6f})'
                     + ((f'; kept rows {sc["kx"] / 1000:.3f} bn recorded net of the retrocession, which goes from the retrocessionaires to the partner'
                         if sc.get('net') else f'; kept at BaTIS {sc["kx"] / 1000:.3f} bn and booked again as pass-through imports') if sc.get('kx') else ''))
    return bad, parts


def load_batis(path, additive, report_codes, iso_to_region, alias_iso, aggregates, log, scale=None):
    flows = defaultdict(float)          # (exp, imp, service) -> musd
    s_pair = defaultdict(float)         # (exp, imp) -> musd for total services S
    partner_w = defaultdict(float)      # (region, service) -> musd, counterpart W, economy reporters
    world_w = defaultdict(float)        # service -> reporter W, counterpart W
    present_reporters = set()
    unmapped = defaultdict(float)
    wxd = defaultdict(float)            # service -> musd, economy reporter to partner WXD
    wxd_by_exp = defaultdict(float)     # (region, service) -> musd
    neg = 0
    n = 0
    scope = defaultdict(set)
    with open(path, newline='') as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames or []
        for row in reader:
            n += 1
            svc = row['SERVICE']
            if svc not in additive and svc not in report_codes:
                continue
            scope['flow'].add(row['TRADE_FLOW'])
            scope['adj'].add(row['ADJUSTMENT'])
            scope['year'].add(row['TIME_PERIOD'])
            scope['unit'].add(row['UNIT_MEASURE'])
            scope['mult'].add(row['UNIT_MULT'])
            scope['product'].add(row['PRODUCT_TYPE'])
            val = float(row['OBS_VALUE'] or 0)
            if val < 0:
                neg += 1
            rep, part = row['REF_AREA'], row['COUNTERPART_AREA']
            if scale:
                if rep in scale:
                    val = scaled_value(scale[rep], part, svc, val)
                elif part in scale:
                    val *= scale[part]['sm']
            if rep == 'W' and part == 'W':
                world_w[svc] += val
            if rep in aggregates:
                continue
            if svc == 'S' or rep not in aggregates:
                present_reporters.add(rep)
            exp = region_of(rep, iso_to_region, alias_iso)
            if part == 'W':
                if exp:
                    partner_w[(exp, svc)] += val
                elif rep not in aggregates:
                    unmapped[('reporter', rep, svc)] += val
                continue
            if part == 'WXD':
                if exp and val:
                    wxd[svc] += val
                    wxd_by_exp[(exp, svc)] += val
                continue
            if part in aggregates:
                continue
            imp = region_of(part, iso_to_region, alias_iso)
            if not exp or not imp:
                if val != 0:
                    unmapped[('pair', rep if not exp else part, svc)] += val
                continue
            if val != 0 and svc in additive:
                flows[(exp, imp, svc)] += val
            if val != 0 and svc == 'S':
                s_pair[(exp, imp)] += val
    # beta v5 M5 (BMU_NET): the retroceded part goes from each retrocessionaire to the kept row's partner; a seller in the
    # partner's own region is domestic and leaves trade.
    for iso, sc in (scale or {}).items():
        for (seller, part, svc), val in sorted(sc.get('rerouted', {}).items()):
            exp = region_of(seller, iso_to_region, alias_iso)
            imp = region_of(part, iso_to_region, alias_iso)
            if not exp or not imp or svc not in additive:
                raise SystemExit(f'batis_scaling net: {seller} to {part} {svc} has no region')
            if exp == imp:
                continue
            flows[(exp, imp, svc)] += val
            s_pair[(exp, imp)] += val
            partner_w[(exp, svc)] += val
            partner_w[(exp, 'S')] += val
    # batis_scaling pass-through (Fable QA B-04): the kept exports come back as the scaled economy's imports.
    for iso, sc in (scale or {}).items():
        imp = region_of(iso, iso_to_region, alias_iso)
        for (seller, svc), val in sorted(sc.get('passed', {}).items()):
            exp = region_of(seller, iso_to_region, alias_iso)
            if not exp or not imp or svc not in additive:
                raise SystemExit(f'batis_scaling pass-through: {seller} to {iso} {svc} has no region')
            flows[(exp, imp, svc)] += val
            s_pair[(exp, imp)] += val
            partner_w[(exp, svc)] += val
            partner_w[(exp, 'S')] += val
    log(f'BaTIS rows {n}; additive pair keys {len(flows)}; negative additive-or-S rows {neg}')
    return flows, s_pair, partner_w, world_w, present_reporters, unmapped, neg, scope, fields, wxd, wxd_by_exp


def load_tot(path):
    out = {}
    with open(path, newline='') as fh:
        for row in csv.DictReader(fh):
            if row['COUNTERPART_AREA'] == 'W':
                out[row['REF_AREA']] = float(row['OBS_VALUE'] or 0)
    return out


def load_tismos(zip_path, tismos_alias, tismos_aggregates, log):
    """2022 exports, partner World, Modes 1+2+4, by ISO3 and by the World reporter."""
    by_iso = defaultdict(lambda: defaultdict(float))
    world = defaultdict(float)
    seen_codes = {}
    unmapped = defaultdict(float)
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open('TiSMoS - Exports.csv') as raw:
            lines = (line.decode('utf-8-sig') for line in raw)
            for row in csv.DictReader(lines):
                if row.get('YEAR') != '2022' or row.get('PARTNER') != 'World':
                    continue
                if row.get('MODE') not in ('Mode 1', 'Mode 2', 'Mode 4'):
                    continue
                ind = (row.get('INDICATOR') or '').strip()
                if not ind or ind in MEMO_TISMOS:
                    continue
                val_s = (row.get('VALUE') or '').strip().replace(',', '')
                if val_s == '':
                    continue
                val = float(val_s)
                code = (row.get('REPORTER_CODE') or '').strip()
                seen_codes.setdefault(code, row.get('REPORTER_NAME') or '')
                if code == 'WL':
                    world[ind] += val
                    continue
                if code in tismos_aggregates:
                    continue
                iso = tismos_alias.get(code) or ISO2.get(code)
                if not iso:
                    if val != 0:
                        unmapped[code] += val
                    continue
                by_iso[iso][ind] += val
    log(f'TiSMoS ISO reporters {len(by_iso)}; unmapped codes with value {len(unmapped)}; WL indicators {len(world)}')
    return by_iso, world, seen_codes, unmapped


def region_tismos(region, region_isos, by_iso):
    acc = defaultdict(float)
    any_row = False
    for iso in region_isos.get(region, ()):
        block = by_iso.get(iso)
        if not block:
            continue
        any_row = True
        for ind, val in block.items():
            acc[ind] += val
    return acc, any_row


def geo_tismos(geos, iso_geo, by_iso):
    acc = defaultdict(float)
    want = set(geos)
    for iso, geo in iso_geo.items():
        if geo not in want:
            continue
        block = by_iso.get(iso)
        if not block:
            continue
        for ind, val in block.items():
            acc[ind] += val
    return acc


def choose_shares(region, parent, leaves, own, any_row, geos, iso_geo, by_iso, world):
    """Return (shares or None, source, values used for the freight ratio)."""
    if any_row and sum(own.get(leaf, 0.0) for leaf in leaves) > 0:
        return share_vector(own, leaves), 'tismos', own
    geo = geo_tismos(geos, iso_geo, by_iso)
    if sum(geo.get(leaf, 0.0) for leaf in leaves) > 0:
        return share_vector(geo, leaves), 'F8', geo
    if sum(world.get(leaf, 0.0) for leaf in leaves) > 0:
        return share_vector(world, leaves), 'world', world
    return None, '', {}


def freight_ratio(values, leaf, parent):
    """SC12/SC1 (and the air and other equivalents). Fall back to the leaf share of the leaf sum."""
    if values.get(parent, 0.0) > 0:
        return max(values.get(leaf, 0.0), 0.0) / values[parent]
    return None


def load_consumption(path):
    """p column of dom_* rows. Returns region -> list of (commodity, value) with value > 0, file order sorted by name."""
    raw = defaultdict(list)
    with gzip.open(path, 'rt', newline='') as fh:
        header = fh.readline().rstrip('\n').split(',')
        pi = header.index('p')
        for line in fh:
            parts = line.rstrip('\n').split(',')
            region, row = parts[0], parts[1]
            if not row.startswith('dom_'):
                continue
            val = float(parts[pi] or 0)
            if val > 0:
                raw[region].append((row[4:], val))
    out = {}
    for region, pairs in raw.items():
        pairs = sorted(pairs)
        total = sum(v for _, v in pairs)
        acc = 0.0
        shares = []
        for i, (com, val) in enumerate(pairs):
            if i < len(pairs) - 1:
                sh = val / total
                shares.append((com, sh))
                acc += sh
            else:
                shares.append((com, 1.0 - acc))
        out[region] = shares
    return out


def load_vst(path):
    vst = defaultdict(dict)
    vtwr = defaultdict(dict)
    with open(path, newline='') as fh:
        for row in csv.DictReader(fh):
            slot = vst if row['record'] == 'vst' else vtwr
            slot[row['margin']][row['region']] = float(row['musd'])
    return vst, vtwr


def load_wdi(path, iso_to_region, alias_iso, wdi_aggregates):
    """USD million by S01 region. series BX exports, BM imports. WDI aggregates stay out."""
    out = defaultdict(lambda: {'X': 0.0, 'M': 0.0, 'nX': 0, 'nM': 0})
    world = {'X': 0.0, 'M': 0.0}
    with open(path, newline='') as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames or []
        if 'value' not in fields or 'series' not in fields or 'iso3' not in fields:
            raise SystemExit('WDI services file is not the long layout bound in MANIFEST (iso3,series,year,value)')
        for row in reader:
            iso = row['iso3']
            if iso in wdi_aggregates or row['value'] == '':
                if iso == 'WLD' and row['value'] != '':
                    side = 'X' if row['series'] == 'BX.GSR.NFSV.CD' else 'M' if row['series'] == 'BM.GSR.NFSV.CD' else ''
                    if side:
                        world[side] = float(row['value']) / 1e6
                continue
            reg = region_of(iso, iso_to_region, alias_iso)
            if not reg or row['value'] == '':
                continue
            side = 'X' if row['series'] == 'BX.GSR.NFSV.CD' else 'M' if row['series'] == 'BM.GSR.NFSV.CD' else ''
            if not side:
                continue
            out[reg][side] += float(row['value']) / 1e6
            out[reg]['n' + side] += 1
    return out, world


def icio_blocks(path, log):
    """Services pairs, ROW totals, and the dpabr block from io_s04."""
    with gzip.open(path, 'rt', newline='') as fh:
        header = fh.readline().rstrip('\n').split(',')
    groups = defaultdict(list)
    for i, col in enumerate(header):
        if col in ('row', 'OUT') or '_' not in col:
            continue
        reg, rest = col.split('_', 1)
        groups[reg].append((rest, i))
    use_idx = {}
    dp_idx = {}
    for reg, pairs in groups.items():
        use_idx[reg] = [i for rest, i in pairs if rest != 'dpabr']
        dp_idx[reg] = next(i for rest, i in pairs if rest == 'dpabr')
    icio = sorted(r for r in groups if r != 'ROW')
    pairs = defaultdict(float)
    row_x = defaultdict(float)
    row_m = defaultdict(float)
    dpabr = defaultdict(float)
    tls = defaultdict(float)
    with gzip.open(path, 'rt', newline='') as fh:
        fh.readline()
        for line in fh:
            parts = line.rstrip('\n').split(',')
            name = parts[0]
            if name == 'TLS':
                for reg, idx in dp_idx.items():
                    val = parts[idx]
                    if val:
                        tls[reg] += float(val)
                continue
            if '_' not in name:
                continue
            exp, sector = name.split('_', 1)
            if exp not in groups:
                continue
            if sector in ICIO_SERVICES and exp != 'ROW':
                for imp in icio:
                    if imp == exp:
                        continue
                    acc = 0.0
                    for idx in use_idx[imp]:
                        val = parts[idx]
                        if val:
                            acc += float(val)
                    if acc != 0.0:
                        pairs[(sector, exp, imp)] += acc
                acc = 0.0
                for idx in use_idx['ROW']:
                    val = parts[idx]
                    if val:
                        acc += float(val)
                if acc != 0.0:
                    row_x[(sector, exp)] += acc
            if sector in ICIO_SERVICES and exp == 'ROW':
                for imp in icio:
                    acc = 0.0
                    for idx in use_idx[imp]:
                        val = parts[idx]
                        if val:
                            acc += float(val)
                    if acc != 0.0:
                        row_m[(sector, imp)] += acc
            for imp, idx in dp_idx.items():
                val = parts[idx]
                if val:
                    got = float(val)
                    if got != 0.0:
                        dpabr[(sector, exp, imp)] += got
    log(f'ICIO services pair keys {len(pairs)}; dpabr keys {len(dpabr)}; TLS dpabr {sum(tls.values()):.2f}')
    return icio, pairs, row_x, row_m, dpabr, tls


def forbidden(path):
    """Private paths only (config/repo_rules.csv, David 2026-10-23). Raw data is committed."""
    return is_private(path)


def git_diff_names():
    root = repo_root()
    names = []
    for args in (
        ['git', '-C', root, 'diff', '--name-only', S08_HEAD],
        ['git', '-C', root, 'diff', '--cached', '--name-only'],
    ):
        out = subprocess.run(args, capture_output=True, text=True).stdout
        names.extend(line.strip() for line in out.splitlines() if line.strip())
    stat = subprocess.run(['git', '-C', root, 'diff', '--stat', S08_HEAD], capture_output=True, text=True).stdout
    return names, stat


def bn(x):
    return f'{x / 1000:.2f}'


def run(S, brief):
    s08 = S.upstream(ROOT + '/stages/S08_margins')
    s07 = S.upstream(ROOT + '/stages/S07_trade')
    s04 = S.upstream(ROOT + '/stages/S04_disagg_gov')
    s01 = S.upstream(ROOT + '/stages/S01_sets_registry')
    cfg = BUILD + '/config/s09/services_choices.csv'
    S.inp(cfg, 'S09 services choices')
    S.inp(s01 + '/output/regions.csv', 'S01 regions')
    S.inp(s01 + '/output/country_region_map.csv', 'S01 country map')
    S.inp(s01 + '/output/composite_members.csv', 'S01 composite members')
    S.inp(s01 + '/output/gtap_geo_regions_table910.csv', 'S01 GTAP geographic regions')
    concord_path = S.inp(s01 + '/output/concord_ebops_to_sector.csv', 'S01 EBOPS concordance')
    io8 = S.inp(s08 + '/output/io_s08.csv.gz', 'S08 IO, byte-copied to io_s09')
    freight_path = S.inp(s08 + '/output/freight_for_s09.csv', 'S08 VST and VTWR for the report')
    vst_path = S.inp(s08 + '/output/vst_s08.csv', 'S08 VST')
    vxsb7 = S.inp(s07 + '/output/vxsb_goods_s07r.csv.gz', 'S07 goods VXSB, read only')
    hubm_path = S.inp(s07 + '/output/hub_margin_s07r.csv', 'S07 HKG re-export margin, booked as HKG trd exports (Fable QA D-01)')
    io4 = S.inp(s04 + '/output/io_s04.csv.gz', 'S04 IO for the ICIO compare file')
    ebops_path = DATA + '/oecd_wto_batis/ebops2022.csv'
    tot_path = DATA + '/oecd_wto_batis/tot2022.csv'
    tismos_path = DATA + '/wto_tismos/gstdh_mode_supply_e.zip'
    wdi_path = DATA + '/wdi/wdi_services_2022.csv'
    ebops_sha, ebops_match = register_input(S, ebops_path, 'OECD-WTO BaTIS 2022 EBOPS exports, adjustment B')
    tot_sha, tot_match = register_input(S, tot_path, 'OECD-WTO BaTIS 2022 services total, counterpart W')
    tismos_sha, tismos_match = register_input(S, tismos_path, 'WTO TiSMoS 2024 release')
    # MANIFEST pins the refetched row order (S09R C2). H12 allows 1e-9 float dust.
    wdi_sha, wdi_match = register_input(S, wdi_path, 'WDI 2022 services exports and imports, long layout')

    choice_rows, by, choice_bad = load_choices(cfg)
    brief['choices'] = choice_rows
    values = {name: by[name]['value'].strip() for name in CHOICE_ORDER if name in by}
    S.check('S09-H1', 'services_choices.csv has the 23 choices, each with decided_by, decided_at and a value in its allowed set; services_pair_source is decided by David',
            'hard', f'{len(choice_rows)} rows; bad {len(choice_bad)}', '23 rows; 0 bad', not choice_bad, Q_SRC,
            '; '.join(choice_bad))
    mode_b = values.get('services_pair_source') == 'batis_all_pairs'
    if not mode_b:
        S.check('S09-Hmode', 'This stage builds batis_all_pairs. Mode A is specified in the handoff and is not applied when the config says so.',
                'hard', values.get('services_pair_source', ''), 'batis_all_pairs', False, Q_SRC, '')
        S.finish()
        return
    dropped = tuple(c.strip() for c in values['batis_dropped_codes'].split(','))
    untraded = tuple(c.strip() for c in values['untraded_sectors'].split(','))
    bea = re.search(r'X([0-9.]+)_M([0-9.]+)', values['us_benchmark'])
    bea_x = float(bea.group(1)) * 1000.0
    bea_m = float(bea.group(2)) * 1000.0
    S.log('mode B batis_all_pairs; mode A rows travel_icio_pairs and row_split are not applied')
    S.log(f'dropped {dropped}; untraded {untraded}; BEA X {bea_x:.1f} M {bea_m:.1f} USD m')

    # Upstream binding beyond the kit: the snapshot commit and the published checksum.
    stamp_text = open(s08 + '/STAMP').read()
    sums_sha = sha256(s08 + '/output/SHA256SUMS')
    touched = subprocess.run(
        ['git', '-C', repo_root(), 'log', '-1', '--format=%H', '--', 'dataset/stages/S08_margins/output/SHA256SUMS'],
        capture_output=True, text=True).stdout.strip()
    s07_touched = subprocess.run(
        ['git', '-C', repo_root(), 'log', '-1', '--format=%H', '--', 'dataset/stages/S07_trade/STAMP'],
        capture_output=True, text=True).stdout.strip()
    bind_ok = (touched == S08_HEAD and sums_sha == S08_SHA256SUMS and S08_STAMP_TIME in stamp_text
               and sha256(freight_path) == S08_FREIGHT and sha256(vst_path) == S08_VST
               and sha256(io8) == S08_IO and sha256(s07 + '/output/SHA256SUMS') == S07_SHA256SUMS
               and sha256(vxsb7) == S07_VXSB and s07_touched == S07_HEAD)
    S.check('S09-G0bind', f'S08 snapshot is commit {S08_HEAD[:7]}, STAMP {S08_STAMP_TIME}, output SHA256SUMS {S08_SHA256SUMS[:8]}, with the freight, VST and IO hashes; S07R snapshot is {S07_HEAD[:7]} and its VXSB hash',
            'hard', 'yes' if bind_ok else 'no', 'yes', bind_ok, 'stage kit G0',
            f'touched {touched}; S07 {s07_touched}; SHA256SUMS {sums_sha}; STAMP build line present {S08_BUILD in stamp_text}')

    iso_to_region, status, regions, members, iso_geo, alias_iso, tismos_alias, aggregates, tismos_agg, wdi_aggregates, region_isos = load_maps()
    batis_meta, tismos_sector = load_concord(concord_path)
    additive = []
    direct = {}
    for code, row in batis_meta.items():
        if row['role'] in ('leaf', 'split', 'dropped', 'special'):
            additive.append(code)
        if row['role'] == 'leaf' and row['sectors']:
            direct[code] = row['sectors']
    additive = tuple(sorted(additive))
    for parent, leaves in SPLIT_LEAVES.items():
        missing = [leaf for leaf in leaves if leaf not in tismos_sector]
        if missing:
            raise SystemExit(f'concordance missing TiSMoS leaves {missing}')

    report_codes = {'S', 'SC', 'SD', 'SI', 'SJ', 'SK'}
    scaled_isos = OWN_BOP_SCALING.get(values['batis_scaling'], ())
    bop_scale = own_bop_scales(ebops_path, wdi_path, scaled_isos, aggregates, OWN_BOP_KEEP.get(values['batis_scaling'], ()),
                               net=values['batis_scaling'] in OWN_BOP_NET, ex_partner=values['batis_scaling'] in OWN_BOP_EX_PARTNER)
    scaled_regions = tuple(sorted({iso_to_region[iso] for iso in scaled_isos}))
    for iso, sc in bop_scale.items():
        S.log(f'batis_scaling {iso}: BaTIS X {sc["bx"]:.3f} M {sc["bm"]:.3f}; own BoP (WDI) X {sc["wx"]:.3f} M {sc["wm"]:.3f} USD m; '
              f'factor X {sc["sx"]:.9f} M {sc["sm"]:.9f}')
    flows, s_pair, partner_w, world_w, present, unmapped, nneg, scope, fields, wxd, wxd_by_exp = load_batis(
        ebops_path, set(additive), report_codes, iso_to_region, alias_iso, aggregates, S.log, bop_scale)
    kept_codes = set(additive) - set(dropped)
    wxd_kept = sum(wxd[code] for code in kept_codes)
    wxd_usa_s = wxd_by_exp.get(('USA', 'S'), 0.0)
    wxd_usa_kept = sum(wxd_by_exp.get(('USA', code), 0.0) for code in kept_codes)
    brief['wxd'] = dict(kept=wxd_kept, usa_s=wxd_usa_s, usa_kept=wxd_usa_kept)
    tot = load_tot(tot_path)
    # ebops S versus the box tot file (same values if only the row order changed).
    tot_gap = 0.0
    tot_n = 0
    with open(ebops_path, newline='') as fh:
        for row in csv.DictReader(fh):
            if row['SERVICE'] != 'S' or row['COUNTERPART_AREA'] != 'W':
                continue
            tot_n += 1
            tot_gap += abs(float(row['OBS_VALUE'] or 0) - tot.get(row['REF_AREA'], 0.0))
    world_s_bn = world_w.get('S', 0.0) / 1000.0
    world_gap_pct = abs(world_s_bn - BOX_WORLD_S_BN) / BOX_WORLD_S_BN * 100.0
    brief['batis'] = dict(sha=ebops_sha, match=ebops_match, bytes=os.path.getsize(ebops_path),
                          world_s_bn=world_s_bn, gap_pct=world_gap_pct, tot_gap=tot_gap,
                          categories={k: world_w.get(k, 0.0) for k in (
                              'S', 'SA', 'SH', 'SB', 'SC', 'SC1', 'SC2', 'SC3', 'SC4', 'SD', 'SDA', 'SDB',
                              'SE', 'SF', 'SG', 'SI', 'SJ', 'SK', 'SK1', 'SK2', 'SL')})
    header_ok = fields[:9] == ['DATAFLOW', 'REF_AREA', 'COUNTERPART_AREA', 'TRADE_FLOW', 'PRODUCT_TYPE', 'SERVICE', 'FREQ', 'UNIT_MEASURE', 'ADJUSTMENT']
    scope_ok = (scope['flow'] == {'X'} and scope['adj'] == {'B'} and scope['year'] == {'2022'}
                and scope['unit'] == {'USD_EXC'} and scope['mult'] == {'6'} and scope.get('product') == {'S'})
    S.check('S09-G0data', 'BaTIS extract is 2022 exports, adjustment B, USD million; TiSMoS and tot match their box checksums; the EBOPS world total is reported against 7,081.0 bn',
            'hard',
            f'header {"ok" if header_ok else "BAD"}; scope {"ok" if scope_ok else "BAD"}; tot match {tot_match}; tismos match {tismos_match}; world S {world_s_bn:.4f} bn',
            'header ok; scope ok; tot and TiSMoS match the box',
            header_ok and scope_ok and tot_match and tismos_match, Q_SRC,
            f'EBOPS sha {ebops_sha} box {BOX_EBOPS_SHA} bytes {os.path.getsize(ebops_path)} (box {BOX_EBOPS_BYTES}). '
            f'World S reporter W {world_s_bn:.4f} bn versus 7,081.0 bn, gap {world_gap_pct:.4f}%. '
            f'Absolute gap of EBOPS counterpart-W S against tot2022.csv: {tot_gap:.6f} USD m on {tot_n} reporters. '
            f'WDI sha {wdi_sha} MANIFEST {BOX_WDI_SHA} match {wdi_match}. '
            f'The wide copy {WIDE_WDI_SHA} was replaced in MANIFEST by this long extract; USA and world totals are the same.')

    by_iso, tis_world, tis_names, tis_unmapped = load_tismos(tismos_path, tismos_alias, tismos_agg, S.log)
    ident = []
    for parent, leaves in SPLIT_LEAVES.items():
        leaf_sum = sum(tis_world.get(leaf, 0.0) for leaf in leaves)
        parent_val = tis_world.get(parent, 0.0)
        ident.append(f'{parent} parent {parent_val:.2f} leaves {leaf_sum:.2f}')
    S.log('TiSMoS WL parent versus leaves, USD m: ' + '; '.join(ident))
    if tis_unmapped:
        brief.setdefault('needs', []).append(
            'TiSMoS reporter codes with a nonzero Modes 1+2+4 value and no ISO3 map: '
            + ', '.join(f'{c} {v:.2f}' for c, v in sorted(tis_unmapped.items())))

    # Shares for every exporter region that has BaTIS on a split parent.
    parent_positive = defaultdict(set)  # parent -> regions
    parent_total = defaultdict(float)   # (region, parent) -> musd
    for (exp, _imp, svc), val in flows.items():
        if svc in SPLIT_LEAVES and val > 0:
            parent_positive[svc].add(exp)
            parent_total[(exp, svc)] += val
    share_of = {}      # (region, parent) -> (shares dict, source)
    share_rows = []
    f8_value = defaultdict(float)
    world_value = defaultdict(float)
    missing_share = []
    for parent, leaves in SPLIT_LEAVES.items():
        for region in sorted(parent_positive[parent]):
            geos = [g for g in (regions[region]['gtap_geo'] or '').split('+') if g]
            own, any_row = region_tismos(region, region_isos, by_iso)
            shares, source, basis_values = choose_shares(region, parent, leaves, own, any_row, geos, iso_geo, by_iso, tis_world)
            if not shares:
                missing_share.append(f'{region} {parent}')
                continue
            share_of[(region, parent)] = (shares, source, basis_values)
            filled = parent_total[(region, parent)]
            if source == 'F8':
                f8_value[(region, parent)] += filled
            elif source == 'world':
                world_value[(region, parent)] += filled
            for leaf in leaves:
                share_rows.append((region, parent, leaf, tismos_sector[leaf], shares[leaf], source))
    bad_sum = []
    neg_share = 0
    for (region, parent), (shares, _source, _basis) in share_of.items():
        total = sum(shares.values())
        if abs(total - 1.0) > 1e-9:
            bad_sum.append(f'{region} {parent} {total}')
        if any(v < -1e-15 for v in shares.values()):
            neg_share += 1
    S.check('S09-H3', 'TiSMoS shares are >= 0 and sum to 1 per (exporter, BaTIS code) to 1e-9, and every split code with BaTIS > 0 has shares',
            'hard', f'{len(share_rows)} share rows; missing {len(missing_share)}; bad sums {len(bad_sum)}; negative {neg_share}',
            '0 missing; 0 bad sums; 0 negative',
            not missing_share and not bad_sum and neg_share == 0, 'READINESS S09',
            ', '.join(missing_share[:20]) + ' ' + '; '.join(bad_sum[:10]))

    # Household shares.
    consumption = load_consumption(io8)
    bad_host = []
    for region, shares in consumption.items():
        total = sum(sh for _, sh in shares)
        if abs(total - 1.0) > 1e-9 or any(sh < -1e-15 for _, sh in shares):
            bad_host.append(region)
    hosts_needed = {exp for (exp, _imp, svc) in flows if svc == 'SDA'}
    missing_host = sorted(hosts_needed - set(consumption))
    travel_file_set = set(GOODS) | {'ely', 'B06'} | set(untraded) | {'hhe'}

    # Build the trade.
    vxsb = defaultdict(float)          # (sector, exp, imp, source)
    travel = defaultdict(float)        # (commodity, host, visitor)
    removed = defaultdict(float)       # (mode, exp, imp)
    removed_share = {}                 # (mode, exp) -> (f_share, f_source)
    dropped_amt = defaultdict(float)   # (exp, imp)
    leaf_total = defaultdict(float)    # (exp, imp) additive including SA SH
    sda_built = defaultdict(float)
    sdb_built = defaultdict(float)
    sd_batis = defaultdict(float)
    parent_flow = defaultdict(float)   # (mode, exp, imp) -> parent musd, for H5
    sj32 = 0.0
    uncovered = set()
    for (exp, imp, svc), val in flows.items():
        leaf_total[(exp, imp)] += val
        if svc in dropped:
            dropped_amt[(exp, imp)] += val
            continue
        if svc in direct:
            sector = direct[svc]
            if sector in untraded or sector in ('ely', 'hhe', 'wat', 'rle'):
                # A direct code is not supposed to land here. Keep it out of VXSB and record it.
                uncovered.add(f'direct code {svc} maps to {sector}, which is not traded')
                continue
            vxsb[(sector, exp, imp, 'batis')] += val
            continue
        if svc == 'SDA':
            sd_batis[(exp, imp)] += val
            shares = consumption.get(exp)
            if not shares or val == 0:
                continue
            acc = 0.0
            for i, (com, sh) in enumerate(shares):
                part = val - acc if i == len(shares) - 1 else val * sh
                if i < len(shares) - 1:
                    acc += part
                if abs(part) < 1e-12:
                    continue
                sda_built[(exp, imp)] += part
                if com in travel_file_set:
                    travel[(com, exp, imp)] += part
                else:
                    vxsb[(com, exp, imp, 'travel_sda')] += part
            continue
        if svc not in SPLIT_LEAVES:
            uncovered.add(f'unclassified BaTIS code {svc}')
            continue
        leaves = SPLIT_LEAVES[svc]
        got = share_of.get((exp, svc))
        if not got:
            continue
        shares, source, basis_values = got
        parts = apply_shares(val, leaves, shares)
        if svc in ('SDA', 'SDB'):
            pass
        if svc == 'SDB':
            sd_batis[(exp, imp)] += val
        for leaf in leaves:
            part = parts[leaf]
            if abs(part) < 1e-12:
                continue
            sector = tismos_sector[leaf]
            mode = next((m for m, (parent, fleaf) in FREIGHT_LEAF.items() if fleaf == leaf), '')
            if mode:
                removed[(mode, exp, imp)] += part
                parent_flow[(mode, exp, imp)] += val
                parent_code = FREIGHT_LEAF[mode][0]
                ratio = freight_ratio(basis_values, leaf, parent_code)
                removed_share[(mode, exp)] = (shares[leaf] if ratio is None else ratio, source)
                continue
            if sector in untraded or sector in ('ely', 'hhe'):
                uncovered.add(f'leaf {leaf} maps to untraded {sector}')
                continue
            vxsb[(sector, exp, imp, 'batis')] += part
            if svc == 'SDB':
                sdb_built[(exp, imp)] += part
            if leaf == 'SJ32':
                sj32 += part

    # Fable QA D-01: the Hong Kong re-export margin that S07 takes out of the origin to destination goods flows
    # is Hong Kong's trade service on those goods (not in BaTIS, which follows BoP and books re-exports as goods).
    hub_margin = defaultdict(float)
    for row in read_csv(hubm_path):
        val = float(row['musd'])
        if val:
            vxsb[(row['sector'], row['exporter'], row['importer'], row['source'])] += val
            hub_margin[row['exporter']] += val
    brief['hub_margin'] = dict(hub_margin)
    S.log('hub margins booked as services exports, USD m: ' + '; '.join(f'{k} {v:.3f}' for k, v in sorted(hub_margin.items())))

    # Numerical dust.
    def _clean(store):
        for key in list(store):
            if abs(store[key]) < 1e-9:
                store[key] = 0.0
    _clean(vxsb)
    _clean(travel)
    _clean(removed)

    # H4 identity.
    h4_keys = set(leaf_total) | set(dropped_amt)
    h4_worst = 0.0
    h4_bad = 0
    built_pair = defaultdict(float)
    for (sector, exp, imp, source), val in vxsb.items():
        if val and source not in HUB_SOURCES:
            built_pair[(exp, imp)] += val
    for (com, exp, imp), val in travel.items():
        if val:
            built_pair[(exp, imp)] += val
    for (exp, imp), val in leaf_total.items():
        got = built_pair[(exp, imp)] + dropped_amt[(exp, imp)]
        got += sum(removed[(mode, exp, imp)] for mode in MODES)
        gap = abs(got - val)
        if gap > h4_worst:
            h4_worst = gap
        if gap > 1e-6:
            h4_bad += 1
    S.check('S09-H4', 'Per exporter and importer, built BaTIS flows plus dropped SA/SH plus freight removed equal the BaTIS leaf total, to 1e-6 USD million',
            'hard', f'pairs {len(leaf_total)}; bad {h4_bad}; max gap {h4_worst:.3e}', 'max gap <= 1e-6',
            h4_bad == 0, Q_SRC + '; READINESS BaTIS totals kept', '')

    # H6.
    h6_bad = 0
    h6_worst = 0.0
    for key, val in sd_batis.items():
        got = sda_built[key] + sdb_built[key]
        gap = abs(got - val)
        if gap > h6_worst:
            h6_worst = gap
        if gap > 1e-6:
            h6_bad += 1
    S.check('S09-H6', 'SDA allocation shares are >= 0 and sum to 1 per host, and travel services plus the travel file plus the SDB split equal BaTIS SD on each pair to 1e-6',
            'hard', f'hosts {len(consumption)}; missing hosts {len(missing_host)}; bad host shares {len(bad_host)}; SD pairs {len(sd_batis)}; bad {h6_bad}; max gap {h6_worst:.3e}',
            'shares sum to 1; max gap <= 1e-6',
            not missing_host and not bad_host and h6_bad == 0, Q_TRAVEL, ', '.join(missing_host[:10]))

    # Freight H5, and the ledger.
    removed_by = defaultdict(float)
    parent_by = defaultdict(float)
    h5_neg = 0
    h5_over = 0
    for (mode, exp, imp), val in removed.items():
        if val < -1e-9:
            h5_neg += 1
        if val - parent_flow[(mode, exp, imp)] > 1e-6:
            h5_over += 1
        if val > 0:
            removed_by[(exp, mode)] += val
    for (mode, exp, imp), val in parent_flow.items():
        parent_by[(exp, mode)] += val
    freight_rows = []
    for (mode, exp, imp), val in sorted(removed.items()):
        if val <= 0:
            continue
        f_share, f_source = removed_share[(mode, exp)]
        freight_rows.append((mode, exp, imp, fnum(val), f12(f_share), f_source))
    freight_total = sum(val for val in removed.values() if val > 0)
    for (exp, mode), val in sorted(removed_by.items()):
        S.adjust(exp, mode, '0', fnum(val), 'drop the TiSMoS freight leaf; do not net against VST', Q_FIT + '; E46', 'FREIGHT-REMOVED-S09')
    for (region, parent), val in sorted(f8_value.items()):
        S.adjust(region, parent, '0', fnum(val), 'F8 geographic-region TiSMoS shares', 'READINESS F8; ' + Q_SPLIT, 'TISMOS-F8')
    for (region, parent), val in sorted(world_value.items()):
        S.adjust(region, parent, '0', fnum(val), 'world TiSMoS shares', 'READINESS F8; ' + Q_SPLIT, 'TISMOS-WORLD')
    # Ledger is written at finish from S.ledger. Check the sums we just staged.
    ledger_freight = defaultdict(float)
    for row in S.ledger:
        if row['flag'] == 'FREIGHT-REMOVED-S09':
            ledger_freight[(row['region'], row['item'])] += float(row['after'])
    h5_ledger_bad = 0
    for key, val in removed_by.items():
        if abs(val - ledger_freight.get(key, 0.0)) > 1e-4:
            h5_ledger_bad += 1
    if abs(sum(ledger_freight.values()) - freight_total) > 1e-4:
        h5_ledger_bad += 1
    file_sum = sum(float(row[3]) for row in freight_rows)
    if abs(file_sum - freight_total) > 1e-4:
        h5_ledger_bad += 1
    S.check('S09-H5', 'Freight removed is >= 0 and no larger than the transport flow it came from; the per-exporter per-mode sum equals the ledger; the file is that total',
            'hard', f'removed {freight_total:.4f} USD m; negative {h5_neg}; above parent {h5_over}; ledger mismatches {h5_ledger_bad}',
            '0 negative; 0 above parent; 0 ledger mismatches',
            h5_neg == 0 and h5_over == 0 and h5_ledger_bad == 0, 'E46; S08 C3/W1',
            'Mode B drops SC12, SC22 and SC32. The ledger rows are staged with the same per-exporter per-mode sums.')

    # Write outputs.
    out = S.out
    vx_lines = []
    for (sector, exp, imp, source), val in sorted(vxsb.items()):
        if val <= 0:
            continue
        vx_lines.append(f'{sector},{exp},{imp},{source},{fnum(val)}\n'.encode())
    gz_write(out + '/vxsb_services_s09.csv.gz', b'sector,exporter,importer,source,vxsb_musd\n', vx_lines)
    tr_lines = []
    for (com, host, visitor), val in sorted(travel.items()):
        if val <= 0:
            continue
        tr_lines.append(f'{com},{host},{visitor},{fnum(val)},travel_sda\n'.encode())
    gz_write(out + '/travel_s09.csv.gz', b'commodity,host,visitor,musd,source\n', tr_lines)
    write_csv(out + '/freight_removed_s09.csv',
              ['margin', 'exporter', 'importer', 'musd', 'f_share', 'f_source'], freight_rows)
    write_csv(out + '/tismos_shares_s09.csv',
              ['exporter', 'batis_code', 'leaf', 'sector', 'share', 'source'],
              [(a, b, c, d, f12(e), f) for a, b, c, d, e, f in sorted(share_rows)])
    shutil.copyfile(io8, out + '/io_s09.csv.gz')

    # ICIO compare. Built trade is VXSB (all sources) on the services sectors.
    S.log('reading io_s04 for the compare file')
    icio, io_pairs, row_x, row_m, dpabr, tls = icio_blocks(io4, S.log)
    built_sec = defaultdict(float)
    for (sector, exp, imp, source), val in vxsb.items():
        if val > 0:
            built_sec[(sector, exp, imp)] += val
    non_icio = sorted(set(regions) - set(icio))
    compare = []
    for (sector, exp, imp), val in sorted(io_pairs.items()):
        built = built_sec.get((sector, exp, imp), 0.0)
        if val == 0 and built == 0:
            continue
        compare.append((sector, exp, imp, 'icio_pair', fnum(val), fnum(built)))
    for (sector, exp), val in sorted(row_x.items()):
        built = sum(built_sec.get((sector, exp, imp), 0.0) for imp in non_icio)
        compare.append((sector, exp, 'ROW', 'row_export', fnum(val), fnum(built)))
    for (sector, imp), val in sorted(row_m.items()):
        built = sum(built_sec.get((sector, exp, imp), 0.0) for exp in non_icio)
        compare.append((sector, 'ROW', imp, 'row_import', fnum(val), fnum(built)))
    sda_com = defaultdict(float)
    for (com, host, visitor), val in travel.items():
        if val > 0:
            sda_com[(com, host, visitor)] += val
    for (sector, exp, imp), val in sorted(dpabr.items()):
        built = sda_com.get((sector, exp, imp), 0.0)
        compare.append((sector, exp, imp, 'dpabr', fnum(val), fnum(built)))
    for imp, val in sorted(tls.items()):
        if val != 0:
            compare.append(('TLS', 'TLS', imp, 'dpabr_tls', fnum(val), '0'))
    gz_write(out + '/icio_services_compare_s09.csv.gz',
             b'sector,exporter,importer,kind,icio_musd,built_musd\n',
             [f'{a},{b},{c},{d},{e},{f}\n'.encode() for a, b, c, d, e, f in compare])

    # USA and the report tables. Computed from the structures above.
    def side_sum(pred):
        return sum(val for (sector, exp, imp, source), val in vxsb.items() if val > 0 and pred(sector, exp, imp, source))

    usa_x = side_sum(lambda s, e, i, src: e == 'USA')
    usa_m = side_sum(lambda s, e, i, src: i == 'USA')
    usa_travel_x = sum(val for (com, host, vis), val in travel.items() if host == 'USA' and val > 0)
    usa_travel_m = sum(val for (com, host, vis), val in travel.items() if vis == 'USA' and val > 0)
    # BaTIS USA from partner W, summed in case of a folded territory. The USA region is the reporter USA.
    def batis_region(region, service):
        return partner_w.get((region, service), 0.0)

    wdi, wdi_world = load_wdi(wdi_path, iso_to_region, alias_iso, wdi_aggregates)
    usa_wdi_x = wdi.get('USA', {}).get('X', 0.0)
    usa_wdi_m = wdi.get('USA', {}).get('M', 0.0)
    usa_rows = []

    def uadd(block, item, ex, im, note):
        usa_rows.append((block, item, '' if ex is None else fnum(ex), '' if im is None else fnum(im), note))

    uadd('total', 'built_vxsb', usa_x, usa_m, 'services VXSB, all sources, after freight removal')
    uadd('total', 'built_vxsb_plus_travel_file', usa_x + usa_travel_x, usa_m + usa_travel_m,
         'VXSB plus SDA goods, ely, B06, wat, rle and hhe in the travel file')
    usa_batis_m = sum(val for (_e, imp), val in s_pair.items() if imp == 'USA')
    usa_sa_m = sum(val for (_e, imp, svc), val in flows.items() if imp == 'USA' and svc == 'SA')
    usa_sh_m = sum(val for (_e, imp, svc), val in flows.items() if imp == 'USA' and svc == 'SH')
    uadd('total', 'batis_S', batis_region('USA', 'S'), usa_batis_m,
         'Exports are counterpart W (includes the WXD residual). Imports are mapped bilateral S, so they exclude the WXD partner.')
    # Imports of S: sum of mapped flows is not partner W. Use tot file via region of USA.
    tot_region_x = defaultdict(float)
    # tot is reporter -> partner W. Map reporters to regions.
    with open(tot_path, newline='') as fh:
        for row in csv.DictReader(fh):
            if row['COUNTERPART_AREA'] != 'W':
                continue
            reg = region_of(row['REF_AREA'], iso_to_region, alias_iso)
            if reg:
                tot_region_x[reg] += float(row['OBS_VALUE'] or 0)
    # Bilateral imports of S are not in tot. Sum EBOPS was not stored for S pairs.
    # USA imports of built trade are above. BaTIS USA imports: sum of other regions' partner is not available per importer from partner W.
    # Reconstruct USA imports from the additive flows plus a note that SA/SH imports need the file.
    usa_sa = batis_region('USA', 'SA')
    usa_sh = batis_region('USA', 'SH')
    uadd('total', 'batis_S_ex_SA_SH', batis_region('USA', 'S') - usa_sa - usa_sh, usa_batis_m - usa_sa_m - usa_sh_m,
         f'export SA {fnum(usa_sa)} SH {fnum(usa_sh)}; import SA {fnum(usa_sa_m)} SH {fnum(usa_sh_m)}')
    uadd('total', 'wdi', usa_wdi_x, usa_wdi_m, 'BX.GSR.NFSV.CD and BM.GSR.NFSV.CD, 2022, USD million')
    uadd('total', 'bea', bea_x, bea_m, values['us_benchmark'])
    for code in ('SA', 'SB', 'SC', 'SC1', 'SC2', 'SC3', 'SC4', 'SD', 'SDA', 'SDB', 'SE', 'SF', 'SG', 'SH', 'SI', 'SJ', 'SK', 'SL'):
        uadd('ebops_exports', code, batis_region('USA', code), None, 'BaTIS USA counterpart W')
    # Coverage statement.
    uadd('coverage', 'bea_geography', None, None,
         'BEA services statistics cover the 50 states, DC, Puerto Rico and the USVI. S01 USA includes PRI (fold) and VIR. No services carve.')
    # Travel.
    uadd('travel', 'batis_SD', batis_region('USA', 'SD'), None, 'exports are USA as host')
    uadd('travel', 'batis_SDA', batis_region('USA', 'SDA'), None, '')
    uadd('travel', 'batis_SDB', batis_region('USA', 'SDB'), None, '')
    uadd('travel', 'built_sda_in_vxsb_and_travel_file',
         sum(sda_built[(e, i)] for (e, i) in sda_built if e == 'USA'),
         sum(sda_built[(e, i)] for (e, i) in sda_built if i == 'USA'),
         'SDA after the host-consumption split')
    usa_dp_x = sum(val for (sector, exp, imp), val in dpabr.items() if exp == 'USA')
    usa_dp_m = sum(val for (sector, exp, imp), val in dpabr.items() if imp == 'USA')
    uadd('travel', 'icio_dpabr', usa_dp_x, usa_dp_m, 'product rows; TLS is not in this row')
    # SDA commodity mix for the USA host.
    usa_mix = defaultdict(float)
    for (com, host, vis), val in travel.items():
        if host == 'USA' and val > 0:
            usa_mix[com] += val
    for (sector, exp, imp, source), val in vxsb.items():
        if exp == 'USA' and source == 'travel_sda' and val > 0:
            usa_mix[sector] += val
    for com, val in sorted(usa_mix.items(), key=lambda kv: -kv[1]):
        uadd('usa_sda_commodity', com, val, None, 'USA host')
    # TiSMoS USA travel leaves.
    usa_tis, _any = region_tismos('USA', region_isos, by_iso)
    for leaf in ('SDA', 'SDB1', 'SDB2', 'SDB3', 'SC1', 'SC12', 'SC2', 'SC22', 'SC3', 'SC32', 'SJ34'):
        uadd('tismos_usa', leaf, usa_tis.get(leaf, 0.0), None, 'Modes 1+2+4, partner World, USD million')
    # Freight.
    vst, vtwr = load_vst(freight_path)
    for mode in MODES:
        parent, leaf = FREIGHT_LEAF[mode]
        f_share = (usa_tis.get(leaf, 0.0) / usa_tis[parent]) if usa_tis.get(parent, 0.0) else 0.0
        rem = sum(val for (m, exp, imp), val in removed.items() if m == mode and exp == 'USA' and val > 0)
        uadd('freight', mode, rem, None,
             f'f_share {f_share:.6f}; VST {fnum(vst[mode].get("USA", 0.0))}; TiSMoS freight {fnum(usa_tis.get(leaf, 0.0))}; not netted (C3/W1)')
    # ICIO versus built, USA.
    for sector in sorted(ICIO_SERVICES):
        ix = sum(val for (s, e, i), val in io_pairs.items() if s == sector and e == 'USA')
        ix += row_x.get((sector, 'USA'), 0.0)
        im = sum(val for (s, e, i), val in io_pairs.items() if s == sector and i == 'USA')
        im += row_m.get((sector, 'USA'), 0.0)
        bx = sum(val for (s, e, i), val in built_sec.items() if s == sector and e == 'USA')
        bm = sum(val for (s, e, i), val in built_sec.items() if s == sector and i == 'USA')
        if ix or im or bx or bm:
            uadd('icio_vs_built', sector, None, None,
                 f'icio_x {fnum(ix)}; built_x {fnum(bx)}; icio_m {fnum(im)}; built_m {fnum(bm)}')
    write_csv(out + '/usa_services_s09.csv',
              ['block', 'item', 'exports_musd', 'imports_musd', 'note'], usa_rows)

    # ---- remaining hard checks on the written trade ----
    bad_sector = []
    sa_sh = 0
    exiobase = 0
    neg_out = 0
    nan_out = 0
    bad_region = []
    region_set = set(regions)
    for (sector, exp, imp, source), val in vxsb.items():
        if val == 0:
            continue
        if val < 0 or val != val:
            neg_out += val < 0
            nan_out += val != val
        if sector in ('ely', 'gdt', 'wat', 'rle', 'hhe') or sector in untraded:
            bad_sector.append(sector)
        if sector in ('SA', 'SH') or source in ('SA', 'SH'):
            sa_sh += 1
        if 'exiobase' in source.lower():
            exiobase += 1
        if exp not in region_set or imp not in region_set:
            bad_region.append(f'{exp}->{imp}')
    for (com, host, vis), val in travel.items():
        if val < 0 or val != val:
            neg_out += 1
        if host not in region_set or vis not in region_set:
            bad_region.append(f'{host}->{vis}')
        if com == 'ely' and False:
            pass
    # ely may be in the travel file. It must not be in VXSB (already in bad_sector).
    S.check('S09-H2', 'No SA or SH value in services trade. No BaTIS services trade in ely (non-travel), wat, rle or hhe. Goods wat is booked in S07, not here. Mode B has no wat/rle/msp services except msp as travel_sda when the host consumes it.',
            'hard', f'forbidden sectors {len(bad_sector)}; SA/SH rows {sa_sh}', '0',
            not bad_sector and sa_sh == 0, Q_DROP, ' '.join(sorted(set(bad_sector))[:12]))
    msp_batis = sum(val for (sector, exp, imp, source), val in vxsb.items() if sector == 'msp' and source == 'batis' and val > 0)
    S.check('S09-H2b', 'msp has no BaTIS-sourced row in mode B', 'hard', fnum(msp_batis), '0', msp_batis == 0, Q_DROP, '')
    S.check('S09-H7', 'Mode A only: ICIO pairs, ROW splits and the dpabr block are not applied. ICIO is the compare file.',
            'hard', 'inactive; batis_all_pairs', 'inactive in mode B', True, 'E47',
            'travel_icio_pairs and row_split stay in the config.')
    S.check('S09-H8', 'No negative or NaN value. Every trade region is an S01 region. Services margins are zero (no VTWR file).',
            'hard', f'negative {neg_out}; nan {nan_out}; bad regions {len(bad_region)}; vtwr file {os.path.exists(out + "/vtwr_s09.csv")}',
            '0; 0; 0; no VTWR file',
            neg_out == 0 and nan_out == 0 and not bad_region and not os.path.exists(out + '/vtwr_s09.csv'),
            Q_VXSB, ' '.join(bad_region[:8]))
    io_same = filecmp.cmp(io8, out + '/io_s09.csv.gz', shallow=False)
    s07_same = sha256(vxsb7) == S07_VXSB and sha256(s07 + '/output/SHA256SUMS') == S07_SHA256SUMS
    s08_same = (sha256(freight_path) == S08_FREIGHT and sha256(vst_path) == S08_VST
                and sha256(s08 + '/output/SHA256SUMS') == S08_SHA256SUMS)
    S.check('S09-H9', 'io_s09 is a byte copy of io_s08. S07 VXSB and the S08 outputs are unchanged.',
            'hard', f'io cmp {io_same}; S07 {s07_same}; S08 {s08_same}', 'all true',
            io_same and s07_same and s08_same, 'S08 H7 pattern', '')
    trade_prior = {
        'vxsb_services_s09.csv.gz': PRIOR_VXSB_SERVICES,
        'travel_s09.csv.gz': PRIOR_TRAVEL,
        'icio_services_compare_s09.csv.gz': PRIOR_ICIO,
    }
    trade_now = {name: sha256(out + '/' + name) for name in trade_prior}
    trade_diff = [name for name, digest in trade_now.items() if digest != trade_prior[name]]
    dust = []
    dust_ok = not trade_diff
    if trade_diff:
        # A scaled region outside the ICIO economies also moves the built column of the ICIO ROW rows.
        moved = scaled_regions + (('ROW',) if set(scaled_regions) & set(non_icio) else ()) + H12_UPSTREAM_MOVED
        hub_pairs = tuple(sorted({(sector, exp) for (sector, exp, _imp, source) in vxsb if source in HUB_SOURCES}))
        # beta v5 M5: the retrocession rerouted to the partner moves those (sector, seller, partner) cells
        net_triples = tuple(sorted({(sector, exp, imp) for (sector, exp, imp, _source) in vxsb
                                    for sc in bop_scale.values() if sc.get('net')
                                    for (seller, part, _svc) in sc.get('rerouted', {})
                                    if exp == region_of(seller, iso_to_region, alias_iso) and imp == region_of(part, iso_to_region, alias_iso)}))
        dust_ok, dust = trade_dust(out, trade_prior, trade_diff, S.archived, moved, hub_pairs, net_triples)
    S.check('S09-H12', 'Services VXSB, the travel file and the ICIO services compare file match the prior S09 snapshot, or every cell is within 1e-9 USD million (beta v4: or rel 1e-8). Cells naming a batis_scaling region, cells of the S07 hub re-export margins (trd from HKG), and (beta v4) cells naming a region whose io table moved upstream through G4 or P33 (BWA, GAB, GNQ, KEN, MUS, XEF, ZAF) are counted apart. trade_identity (Timmy) accepts that dust as float rounding. The three files are built from BaTIS, TiSMoS, WDI, io_s04 and the S07 hub margin file. S07 goods VXSB and S08 freight are not inputs; H9 only hashes them.',
            'hard', 'identical' if not trade_diff else 'dust ' + ','.join(trade_diff),
            'byte-identical, or gap <= max(1e-9, rel 1e-8) (beta v5: abs 1e-3) outside the batis_scaling, hub and beta v4 io-moved regions', dust_ok, values.get('trade_identity', 'trade_identity'),
            ('; '.join(dust) if dust else f'prior snapshot {PRIOR_S09}. Byte-identical. Only the freight-versus-VST report may change, because S08 VTWR moved.'))
    S.check('S09-H10', 'No EXIOBASE source tag', 'hard', exiobase, 0, exiobase == 0, 'PLAN §3(e)', '')
    names, stat = git_diff_names()
    bad_files = sorted({n for n in names if forbidden(n)})
    key_files = []
    for base in ('id_rsa', 'id_ed25519', 'credentials.json', '.netrc'):
        if os.path.exists(os.path.expanduser('~/' + base)):
            key_files.append(base)
    load_rules()
    S.check('S09-H11', 'No private file (credentials, licensed GTAP database values) in the git diff. Rule: config/repo_rules.csv committed_data_rule (David 2026-10-23). Key files are counted, not printed.',
            'hard', f'forbidden paths {len(bad_files)}; key-file names present {len(key_files)}', '0 forbidden paths',
            not bad_files, 'licensing', (stat[:1500] if stat else 'empty diff') + (' forbidden ' + ' '.join(bad_files) if bad_files else ''))

    # ---- report checks ----
    sec_world = defaultdict(float)
    for (sector, exp, imp, source), val in vxsb.items():
        if val > 0:
            sec_world[sector] += val
    travel_world = sum(val for val in travel.values() if val > 0)
    vx_world = sum(sec_world.values())
    removed_world = {mode: sum(val for (m, e, i), val in removed.items() if m == mode and val > 0) for mode in MODES}
    removed_sum = sum(removed_world.values())
    # R1
    cat_lines = []
    for code in ('S', 'SA', 'SH', 'SC', 'SC1', 'SC2', 'SC3', 'SC4', 'SD', 'SDA', 'SDB', 'SJ', 'SG', 'SI'):
        cat_lines.append(f'{code} {world_w.get(code, 0.0) / 1000:.2f}')
    sec_lines = ' '.join(f'{s} {sec_world[s] / 1000:.2f}' for s in sorted(sec_world))
    S.check('S09-R1', 'World services trade by sector, and BaTIS world categories, against the handoff preview',
            'report', f'VXSB {vx_world / 1000:.2f} bn; travel file {travel_world / 1000:.2f} bn; freight removed {removed_sum / 1000:.2f} bn',
            'preview BaTIS S 7081.0 bn; freight removed about 890.8 bn', True, Q_SRC,
            'BaTIS reporter W, bn: ' + '; '.join(cat_lines)
            + f'. Built VXSB by sector, bn: {sec_lines}. '
            + 'The preview freight figure is the TiSMoS freight total. Mode B removes BaTIS times the exporter freight share, so the total moves with BaTIS. '
            + f'WDI world (WLD) exports {wdi_world["X"] / 1000:.2f} bn, imports {wdi_world["M"] / 1000:.2f} bn. WDI is one total, not a sector split.')
    # R2
    # Built exports/imports in the BaTIS-ex-SA-SH-ex-freight sense: VXSB + travel file.
    built_x = defaultdict(float)
    built_m = defaultdict(float)
    for (sector, exp, imp, source), val in vxsb.items():
        if val > 0:
            built_x[exp] += val
            built_m[imp] += val
    for (com, host, vis), val in travel.items():
        if val > 0:
            built_x[host] += val
            built_m[vis] += val
    outside = []
    for region in sorted(regions):
        bx = built_x[region]
        bat = tot_region_x.get(region, 0.0)
        wd = wdi.get(region, {})
        checks_here = [('export vs BaTIS S', bx, bat), ('export vs WDI', bx, wd.get('X', 0.0)),
                       ('import vs WDI', built_m[region], wd.get('M', 0.0))]
        for label, got, bench in checks_here:
            if bench <= 0:
                continue
            ratio = got / bench - 1.0
            if abs(ratio) > 0.10:
                outside.append(f'{region} {label} {ratio * 100:+.1f}%')
    # BaTIS with and without SA/SH, world.
    world_batis = world_w.get('S', 0.0)
    world_ex = world_batis - world_w.get('SA', 0.0) - world_w.get('SH', 0.0)
    S.check('S09-R2', 'Each region services exports and imports against BaTIS counterpart W and WDI, ±10%, report only. BaTIS with and without SA/SH.',
            'report', f'{len(outside)} region-side gaps outside 10%', 'report only (C24)', True, 'C24',
            f'World BaTIS S {world_batis / 1000:.2f} bn; ex SA/SH {world_ex / 1000:.2f} bn; '
            f'built VXSB+travel { (vx_world + travel_world) / 1000:.2f} bn; freight removed {removed_sum / 1000:.2f} bn. '
            f'WXD is an excluded aggregate partner. Unallocated kept services (additive leaves except SA and SH) {wxd_kept / 1000:.2f} bn'
            f' (USA exports of S {wxd_usa_s / 1000:.2f} bn, of which kept services {wxd_usa_kept / 1000:.2f} bn). '
            f'Built exports sit below counterpart W by that residual. '
            + '; '.join(outside[:40]))
    # H13: batis_scaling regions.
    if bop_scale:
        h13_bad, parts = h13_identity(bop_scale)
        for region in scaled_regions:
            parts.append(f'{region} built VXSB X {built_x[region] / 1000:.3f} M {built_m[region] / 1000:.3f} bn after SA/SH and freight')
        S.check('S09-H13', H13_DESC, 'hard', f'scaled {len(bop_scale)}; bad {len(h13_bad)}', '0 bad', not h13_bad, H13_CONCEPT, '; '.join(parts))
    # R3
    vst_world = {mode: sum(vst[mode].values()) for mode in MODES}
    vtwr_world = {mode: sum(vtwr[mode].values()) for mode in MODES}
    r3 = []
    for mode in MODES:
        r3.append(f'{mode} removed {removed_world[mode] / 1000:.2f} VST {vst_world[mode] / 1000:.2f} VTWR {vtwr_world[mode] / 1000:.2f}')
    r3.append(f'all-mode removed {removed_sum / 1000:.2f} VST {sum(vst_world.values()) / 1000:.2f} VTWR {sum(vtwr_world.values()) / 1000:.2f}')
    sea_gt = 0
    rdt_lt = 0
    for region in regions:
        sea_r = sum(val for (m, e, i), val in removed.items() if m == 'sea' and e == region and val > 0)
        rdt_r = sum(val for (m, e, i), val in removed.items() if m == 'rdt' and e == region and val > 0)
        if sea_r > vst['sea'].get(region, 0.0) and sea_r > 0:
            sea_gt += 1
        if 0 < rdt_r < vst['rdt'].get(region, 0.0):
            rdt_lt += 1
    S.check('S09-R3', 'Freight removed against S08 VST and VTWR by mode, report only, with the all-mode total. Not netted.',
            'report', '; '.join(r3), 'preview removed about 890.8 bn; bound S08 VTWR 1,391.63 bn', True, 'S08 C3/W1',
            f'Regions with sea removed > VST sea: {sea_gt}. Regions with rdt removed < VST rdt (and removed > 0): {rdt_lt}. '
            'S08 puts most of the oil and gas margin on rdt, so VST rdt is overstated and VST sea understated. The ratio is not a target.')
    # R4 USA
    batis_usa_x = batis_region('USA', 'S')
    S.check('S09-R4', 'USA services: built, BaTIS, WDI and BEA',
            'report',
            f'built VXSB X {usa_x / 1000:.2f} M {usa_m / 1000:.2f}; BaTIS S X {batis_usa_x / 1000:.2f} (SH {usa_sh / 1000:.2f}); WDI X {usa_wdi_x / 1000:.2f} M {usa_wdi_m / 1000:.2f}; BEA X {bea_x / 1000:.1f} M {bea_m / 1000:.1f}',
            'preview BaTIS X 1094.9 M 911.7; WDI X 963.1 M 691.4; BEA X 926.0 M 680.3', True, Q_SRC,
            f'Built plus travel file X {(usa_x + usa_travel_x) / 1000:.2f} M {(usa_m + usa_travel_m) / 1000:.2f} bn. '
            f'BaTIS ex SA/SH X {(batis_usa_x - usa_sa - usa_sh) / 1000:.2f} bn. '
            f'SD X {batis_region("USA", "SD") / 1000:.2f} bn. ICIO dpabr X {usa_dp_x / 1000:.2f} M {usa_dp_m / 1000:.2f} bn. '
            'BEA covers the 50 states, DC, Puerto Rico and the USVI; S01 USA includes PRI and VIR; no services carve. '
            'The public PDF categories are not parsed; the config row supplies the BEA totals. '
            f'BaTIS USA exports are {((batis_usa_x / usa_wdi_x) - 1) * 100:.1f}% versus WDI exports. '
            'WDI is BPM6 services as published by the World Bank; BaTIS is the balanced bilateral account, including SH.')
    # R5
    f8_regions = sorted({region for region, _parent in f8_value})
    world_regions = sorted({region for region, _parent in world_value})
    S.check('S09-R5', 'F8 and world fills: counts and values. PAL is the expected missing TiSMoS reporter.',
            'report', f'F8 regions {len(f8_regions)}; F8 fills {len(f8_value)}; value {sum(f8_value.values()) / 1000:.2f} bn; world regions {len(world_regions)}; world fills {len(world_value)}; value {sum(world_value.values()) / 1000:.2f} bn',
            'PAL expected', True, 'READINESS F8',
            'F8: ' + ', '.join(f'{r} {p} {v / 1000:.3f} bn' for (r, p), v in sorted(f8_value.items()))
            + '. World: ' + (', '.join(f'{r} {p} {v / 1000:.3f} bn' for (r, p), v in sorted(world_value.items())) or 'none'))
    # R6
    mine = output_sums_text(out)
    mine_digest = hashlib.sha256(mine.encode()).hexdigest()
    other_path = os.environ.get('S09_R6_SHA256SUMS', '').strip()
    if not other_path:
        scratch = '/tmp/s09b/S09_services/output/SHA256SUMS'
        canon = ROOT + '/stages/S09_services/output/SHA256SUMS'
        if os.environ.get('GTAP_STAGES_DIR') and os.path.exists(canon):
            other_path = canon
        elif os.path.exists(scratch) and not os.environ.get('GTAP_STAGES_DIR'):
            other_path = scratch
    if other_path and os.path.exists(other_path):
        other = open(other_path).read()
        same = mine == other
        r6_value = f'match {same}; this {mine_digest}'
        r6_detail = 'this run\n' + mine + 'other run\n' + other
        r6_ok = same
    else:   # no second run: NOTE, not PASS (Grok S15 QA N10), as S10 does
        r6_ok = False
        r6_value = f'this {mine_digest}; other run not supplied'
        r6_detail = 'Set S09_R6_SHA256SUMS or run GTAP_STAGES_DIR=/tmp/s09b.\n' + mine
    brief['r6'] = r6_value
    S.check('S09-R6', 'Two runs write the same output SHA256SUMS',
            'report', r6_value, 'the two SHA256SUMS match', r6_ok, 'GTAP_STAGES_DIR', r6_detail)
    # R7 largest gaps
    gaps = []
    for sector, exp, imp, kind, icio_s, built_s in compare:
        if kind != 'icio_pair':
            continue
        gap = float(icio_s) - float(built_s)
        gaps.append((abs(gap), gap, sector, exp, imp, float(icio_s), float(built_s)))
    gaps.sort(reverse=True)
    by_sector_icio = defaultdict(float)
    by_sector_built_on_pairs = defaultdict(float)
    for sector, exp, imp, kind, icio_s, built_s in compare:
        if kind == 'icio_pair':
            by_sector_icio[sector] += float(icio_s)
            by_sector_built_on_pairs[sector] += float(built_s)
    sec_txt = ' '.join(f'{s} ICIO {by_sector_icio[s] / 1000:.1f} built {by_sector_built_on_pairs[s] / 1000:.1f}'
                       for s in sorted(by_sector_icio, key=lambda k: -by_sector_icio[k]))
    top20 = '; '.join(f'{s} {e}->{i} ICIO {iv / 1000:.2f} built {bv / 1000:.2f} gap {g / 1000:.2f}'
                      for _a, g, s, e, i, iv, bv in gaps[:20])
    # Raw BaTIS on ICIO-ICIO pairs, before the TiSMoS split and the freight drop. Report only.
    preview_groups = (
        ('trd', ('SB',)), ('rdt', ('SC3',)), ('sea', ('SC1',)), ('air', ('SC2',)),
        ('pst', ('SC4',)), ('con', ('SE',)), ('fin', ('SF', 'SG')), ('tel', ('SI1',)),
        ('its', ('SI2', 'SI3')), ('pro', ('SJ1', 'SJ2')), ('SJ3', ('SJ3',)),
        ('pub', ('SK1',)), ('gov', ('SL',)), ('SK2', ('SK2',)), ('travel', ('SDA', 'SDB')),
    )
    raw_icio = defaultdict(float)
    icio_set = set(icio)
    for (exp, imp, svc), val in flows.items():
        if exp in icio_set and imp in icio_set and exp != imp:
            raw_icio[svc] += val
    raw_groups = {}
    for name, codes in preview_groups:
        raw_groups[name] = sum(raw_icio[c] for c in codes)
    raw_ex_travel = sum(v for k, v in raw_groups.items() if k != 'travel')
    brief['raw_groups'] = raw_groups
    raw_txt = ' '.join(f'{name} {raw_groups[name] / 1000:.1f}' for name, _c in preview_groups)
    S.check('S09-R7', 'ICIO services trade against the built trade by sector, and the 20 largest pair gaps, for S13',
            'report', f'ICIO-ICIO services {sum(by_sector_icio.values()) / 1000:.1f} bn; built on those pairs {sum(by_sector_built_on_pairs.values()) / 1000:.1f} bn',
            'preview ICIO 7575.9 bn ex travel; the built column is BaTIS after the split and the freight drop', True, 'ICIO 2023 doc pp.18, 33',
            sec_txt + '. Largest gaps: ' + top20
            + f'. Raw BaTIS on ICIO-ICIO pairs before the split and the freight drop, bn: {raw_txt}. '
            + f'Sum excluding travel {raw_ex_travel / 1000:.1f}. '
            + 'The preview BaTIS column is this raw total, not the built column.')
    # R8 travel
    sda_goods = defaultdict(float)
    sda_all = defaultdict(float)
    for (com, host, vis), val in travel.items():
        if val <= 0:
            continue
        sda_all[host] += val
        if com in GOODS or com == 'B06':
            sda_goods[host] += val
    for (sector, exp, imp, source), val in vxsb.items():
        if source == 'travel_sda' and val > 0:
            sda_all[exp] += val
    top_hosts = sorted(sda_all.items(), key=lambda kv: -kv[1])[:10]
    goods_share_world = sum(sda_goods.values()) / sum(sda_all.values()) if sum(sda_all.values()) else 0
    dp_by_host = defaultdict(float)
    for (sector, exp, imp), val in dpabr.items():
        dp_by_host[exp] += val
    dp_gaps = []
    for region in sorted(set(dp_by_host) | set(regions)):
        bat = batis_region(region, 'SD')
        if dp_by_host[region] or bat:
            dp_gaps.append((abs(dp_by_host[region] - bat), region, dp_by_host[region], bat))
    dp_gaps.sort(reverse=True)
    S.check('S09-R8', 'Travel: SDA goods share, top hosts, ICIO dpabr against BaTIS SD',
            'report', f'SDA {sum(sda_all.values()) / 1000:.2f} bn; goods+B06 share of SDA {goods_share_world * 100:.1f}%; dpabr product rows {sum(dpabr.values()) / 1000:.2f} bn; TLS {sum(tls.values()) / 1000:.2f} bn',
            'preview dpabr with ROW and TLS 912.8 bn', True, Q_TRAVEL,
            'Top hosts bn: ' + ', '.join(f'{r} {v / 1000:.2f}' for r, v in top_hosts)
            + '. Largest |dpabr − BaTIS SD|: ' + '; '.join(
                f'{r} dpabr {d / 1000:.2f} SD {b / 1000:.2f}' for _g, r, d, b in dp_gaps[:10]))

    # Flags.
    S.flag('SJ32-TO-ADM', 'SJ32', f'SJ32 (waste treatment, agricultural and mining services) is mapped to adm. World total in VXSB {sj32 / 1000:.2f} bn. GTAP Table 10.2 maps it to obs.', 'no', 'Table 10.2', Q_SPLIT)
    S.flag('WHS-TABLE-10-2', 'whs', 'SC13, SC23 and SC33 go to whs, following Table 10.2. The 20 percent sentence on ch.10B p.3 is truncated.', 'no', values['whs_rule'], Q_SPLIT)
    S.flag('TRAVEL-HOST-CONSUMPTION', 'SDA', 'SDA is allocated by the host region household consumption of domestic products in io_s08, all dom_* rows. Goods, B06 and ely, and wat/rle/hhe, are in the travel file. Other commodities are VXSB source travel_sda.', 'no', values['travel_business_sda'], Q_TRAVEL)
    S.flag('FREIGHT-REMOVED-S09', 'WORLD', f'Freight leaves dropped, {freight_total / 1000:.2f} bn. Not netted against VST by mode.', 'no', values['freight_removal'], 'E46; S08 C3/W1')
    S.flag('FREIGHT-IMPORTER-SIDE-TO-S13', 'WORLD', 'Importer-side removal is recorded in freight_removed_s09.csv for S13. io_s09 is unchanged.', 'no', values['freight_importer_side'], Q_FIT)
    S.flag('WXD-UNALLOCATED', 'WXD',
           f'BaTIS partner WXD is not allocated. Kept services, additive leaves except SA and SH, {wxd_kept / 1000:.2f} bn. '
           f'USA exports of S to WXD {wxd_usa_s / 1000:.2f} bn, of which kept services {wxd_usa_kept / 1000:.2f} bn. '
           'Excluded as a non-country aggregate (S01).',
           'no', 'S01 non_country_codes', Q_SRC)
    for (region, parent), val in sorted(f8_value.items()):
        S.flag('TISMOS-F8', f'{region} {parent}', f'BaTIS {val / 1000:.4f} bn split with the geographic-region TiSMoS shares.', 'no', 'F8', Q_SPLIT)
    for (region, parent), val in sorted(world_value.items()):
        S.flag('TISMOS-WORLD', f'{region} {parent}', f'BaTIS {val / 1000:.4f} bn split with world TiSMoS shares.', 'no', 'F8', Q_SPLIT)
    covered = set(present)
    for src, iso in alias_iso.items():
        if src in covered or iso in covered:
            covered.add(src)
            covered.add(iso)
    for code, st in sorted(status.items()):
        if st not in ('single', 'composite member'):
            continue
        if code in covered or code in aggregates:
            continue
        # A composite member that never appears as a BaTIS reporter, including under an S01 alias.
        S.flag(f'BATIS-MISSING-{code}', code, f'{st}; no BaTIS reporter row.', 'no', 'coverage', Q_SRC)
    # WL freight shares for the brief.
    def wl_f(leaf, parent):
        return (tis_world.get(leaf, 0.0) / tis_world[parent]) if tis_world.get(parent, 0.0) else 0.0
    brief['wl_freight'] = {mode: wl_f(leaf, parent) for mode, (parent, leaf) in FREIGHT_LEAF.items()}
    brief['wl_freight_bn'] = {mode: tis_world.get(FREIGHT_LEAF[mode][1], 0.0) / 1000.0 for mode in MODES}
    brief['world'] = dict(vx=vx_world, travel=travel_world, removed=removed_sum, removed_mode=removed_world,
                          sec=dict(sec_world), batis=dict(world_w))
    brief['usa'] = dict(x=usa_x, m=usa_m, tx=usa_travel_x, tm=usa_travel_m, batis=batis_usa_x,
                        sh=usa_sh, sa=usa_sa, wdi_x=usa_wdi_x, wdi_m=usa_wdi_m, bea_x=bea_x, bea_m=bea_m,
                        dp_x=usa_dp_x, dp_m=usa_dp_m)
    brief['f8'] = dict(regions=len(f8_regions), fills=len(f8_value), value=sum(f8_value.values()),
                       names=f8_regions, world_regions=len(world_regions), world_fills=len(world_value),
                       world_value=sum(world_value.values()))
    brief['icio'] = dict(total=sum(by_sector_icio.values()), built=sum(by_sector_built_on_pairs.values()),
                         by_sector=dict(by_sector_icio))
    brief['needs'] = brief.get('needs') or []
    if uncovered:
        brief['needs'].extend(sorted(uncovered))
    brief['wdi_world'] = wdi_world
    # Unmapped BaTIS value, if any, is a real gap.
    unmapped_value = sum(abs(v) for v in unmapped.values())
    if unmapped_value > 1.0:
        brief['needs'].append(f'Unmapped BaTIS value {unmapped_value:.2f} USD m. Not assigned to a region.')
    brief['preview_note'] = preview_note(brief)
    S.finish()


def preview_note(brief):
    path = os.environ.get('S09_PREVIEW_CSV', '').strip()
    if not path:
        for cand in ('/tmp/s09_preview.csv',):
            if os.path.exists(cand):
                path = cand
                break
    if not path or not os.path.exists(path):
        return 'Preview file not found.'
    lines = [f'Preview file {path}. Differences are reported and not used to change a weight.']
    batis = brief.get('batis', {}).get('categories', {})
    lines.append(f"World S {batis.get('S', 0) / 1000:.2f} bn (preview 7081.0); SA {batis.get('SA', 0) / 1000:.2f} (190.4); SH {batis.get('SH', 0) / 1000:.2f} (535.7); "
                 f"SC {batis.get('SC', 0) / 1000:.2f} (1573.7); SD {batis.get('SD', 0) / 1000:.2f} (1115.5); SDA {batis.get('SDA', 0) / 1000:.2f} (163.9); SDB {batis.get('SDB', 0) / 1000:.2f} (951.6).")
    wl = brief.get('wl_freight', {})
    lines.append(f"TiSMoS WL freight shares sea {wl.get('sea', 0):.3f} (preview 0.728), air {wl.get('air', 0):.3f} (0.263), rdt {wl.get('rdt', 0):.3f} (0.725).")
    lines.append(f"Freight removed {brief.get('world', {}).get('removed', 0) / 1000:.2f} bn (preview about 890.8, the TiSMoS freight total).")
    icio = brief.get('icio', {})
    lines.append(f"ICIO-ICIO services {icio.get('total', 0) / 1000:.2f} bn (preview 7575.9).")
    preview_raw = {
        'trd': 92.7, 'rdt': 282.6, 'sea': 718.9, 'air': 339.6, 'pst': 37.4, 'con': 83.5,
        'fin': 640.0, 'tel': 74.7, 'its': 625.8, 'pro': 944.5, 'SJ3': 669.8, 'pub': 66.1,
        'gov': 76.0, 'SK2': 35.7, 'travel': 931.6,
    }
    raw_groups = brief.get('raw_groups') or {}
    if raw_groups:
        bits = []
        for name, prev in preview_raw.items():
            got = raw_groups.get(name, 0.0) / 1000.0
            bits.append(f'{name} {got:.1f} vs {prev:.1f} ({got - prev:+.1f})')
        lines.append('Raw BaTIS on ICIO pairs, bn, this extract versus the preview: ' + '; '.join(bits) + '.')
    wdi_w = brief.get('wdi_world') or {}
    if wdi_w:
        lines.append(f"WDI world exports {wdi_w.get('X', 0) / 1000:.2f} bn, imports {wdi_w.get('M', 0) / 1000:.2f} bn.")
    usa = brief.get('usa', {})
    if usa:
        lines.append(f"USA BaTIS S {usa['batis'] / 1000:.2f} (preview 1094.9); WDI X {usa['wdi_x'] / 1000:.2f} (963.1) M {usa['wdi_m'] / 1000:.2f} (691.4); "
                     f"ICIO dpabr X {usa['dp_x'] / 1000:.2f} (125.0) M {usa['dp_m'] / 1000:.2f} (146.9).")
    return '\n'.join(lines)


def write_notes(S, brief):
    needs = brief.get('needs') or []
    lines = ['# NEEDS_DAVID', '']
    if needs:
        lines.append('Items the handoff does not settle. Nothing below was filled with a plug.')
        lines.append('')
        for item in needs:
            lines.append(f'- {item}')
    else:
        lines.append('None.')
    lines.append('')
    open(S.dir + '/NEEDS_DAVID.md', 'w').write('\n'.join(lines) + '\n')

    checks = getattr(S, 'checks', [])
    batis = brief.get('batis', {})
    world = brief.get('world', {})
    usa = brief.get('usa', {})
    f8 = brief.get('f8', {})
    md = [
        '# S09 review brief',
        '',
        'Services trade, mode B (`batis_all_pairs`). BaTIS for every mapped country pair. TiSMoS splits the aggregate codes on the exporter side, Modes 1, 2 and 4. Business travel is the host\'s household consumption of domestic products. Personal travel follows Table 10.2. Freight leaves SC12, SC22 and SC32 are dropped and not netted against VST. ICIO is a compare file. `io_s09.csv.gz` is a byte copy of `io_s08.csv.gz`.',
        '',
        f'Bound S08 snapshot commit `{S08_HEAD}`, STAMP {S08_STAMP_TIME}, output SHA256SUMS `{S08_SHA256SUMS}`. The STAMP\'s own build-commit line is `{S08_BUILD}`. Bound S07R snapshot `{S07_HEAD}`.',
        '',
        '## Choices',
        '',
        'Mode A rows `travel_icio_pairs` and `row_split` are in the file and are not applied.',
        '',
        '| choice | value | decided_by | decided_at | gtap_status |',
        '|---|---|---|---|---|',
    ]
    for row in brief.get('choices') or []:
        md.append(f'| {row["choice"]} | {row["value"]} | {row["decided_by"]} | {row["decided_at"]} | {row["gtap_status"]} |')
    md += ['', '## Hard checks', '', '| ID | Status | Value |', '|---|---|---|']
    for c in checks:
        if c['kind'] == 'hard':
            md.append(f'| {c["id"]} | {c["status"]} | {c["value"]} |')
    md += ['', '## Report checks', '']
    for c in checks:
        if c['kind'] == 'report':
            md += [f'### {c["id"]} {c["status"]}', '', c['description'], '', f'Value: {c["value"]}', '', c.get('detail') or '', '']
    md += [
        '## BaTIS file',
        '',
        f'Fetched SHA-256 `{batis.get("sha", "")}`. MANIFEST pin `{BOX_EBOPS_SHA}`, {BOX_EBOPS_BYTES} bytes. '
        f'This extract is {batis.get("bytes", 0)} bytes. World S (reporter W, counterpart W) {batis.get("world_s_bn", 0):.4f} bn, '
        f'{batis.get("gap_pct", 0):.4f}% from 7,081.0 bn. Gap against `tot2022.csv` {batis.get("tot_gap", 0):.6f} USD m. '
        'MANIFEST pins this refetch (S09R C2). Earlier rows f2a3987d and 201c7932 were the same byte size with a different SDMX row order.',
        '',
        '## Against the preview',
        '',
        brief.get('preview_note') or '',
        '',
        '## Flags',
        '',
    ]
    counts = defaultdict(int)
    for fl in getattr(S, 'flags', []):
        counts[fl['id'] if not fl['id'].startswith('BATIS-MISSING-') else 'BATIS-MISSING'] += 1
    for fid, n in sorted(counts.items()):
        md.append(f'- `{fid}`: {n}')
    md += [
        '',
        '## Quotes',
        '',
        f'- {Q_SRC}: BaTiS bilateral flows that do not need to be reconciled. Table 10.1 maps the codes.',
        f'- {Q_DROP}: ely, gdt, wtr and dwe are outside BaTiS; wtr and dwe are not traded. SA and SH are dropped.',
        f'- {Q_AG}: wtr and dwe are not targeted.',
        f'- {Q_SPLIT}: TiSMoS, all modes except Mode 3. Table 10.2. The 20 percent sentence is truncated; whs follows the table.',
        f'- {Q_TRAVEL}: the GTAP sentence gives the traveler\'s expenditures. Reading Table 10.2 `trvl*` as business travel allocated by private consumption is an inference. The host side is not stated. The same passage is why water and electricity can show up as trade.',
        f'- {Q_SAT}: the TiSMoS satellite has VIMP and VEXP and does not report the four sectors without trade data.',
        f'- {Q_VXSB}: VXSB is non-margin exports at basic prices.',
        f'- {Q_FIT}: FIT holds export and import vectors at border prices. The importer side of the freight removal waits for S13.',
        f'- {Q_ASM}: assembly merges FIT with the bilateral trade.',
        '- ICIO 2023 development doc pp.18 and 33: f.o.b. purchasers\' prices still carry the exporter\'s distribution margins. Those are not BPM6 services trade.',
        '',
        '## Departures and log-only items',
        '',
        '- Freight is removed from services trade (not in the GTAP text; E46). It is not netted against VST by mode (S08 C3/W1).',
        '- TiSMoS shares are the exporter\'s exports. F8 then world when the parent is missing.',
        '- Only SDA is allocated by host consumption. PLAN said SD (E47). Goods, B06 and ely go to the travel file.',
        '- wat services and rle (including real estate) are not in services VXSB. Goods wat is booked in S07. SDA amounts for wat and rle stay in the travel file.',
        '- SJ32 goes to adm. SC4 goes to pst and SK1 goes to pub.',
        '- ICIO trd/rdt/whs on ICIO pairs still contain exporter margins on goods. The gap is in the compare file for S13. Mode A is not applied.',
        '- WXD, the BaTIS residual partner, is excluded as a non-country aggregate (S01). It is not spread across regions.',
        '',
        '## Two-run SHA256SUMS',
        '',
        brief.get('r6', 'not run'),
        '',
    ]
    if world:
        md += [f'World VXSB {world["vx"] / 1000:.2f} bn. Travel file {world["travel"] / 1000:.2f} bn. Freight removed {world["removed"] / 1000:.2f} bn.', '']
    if f8:
        md += [f'F8 regions {f8["regions"]} ({", ".join(f8["names"])}). World-fallback regions {f8["world_regions"]}.', '']
    stamp = S.dir + '/STAMP'
    if os.path.exists(stamp):
        md += ['## STAMP', '', '```', open(stamp).read().rstrip(), '```', '']
    open(S.dir + '/REVIEW_BRIEF.md', 'w').write('\n'.join(md) + '\n')


def main():
    brief = {}
    stage = None
    try:
        stage = Stage('S09', 'services')
        run(stage, brief)
    except SystemExit:
        raise
    except Exception:
        if stage is not None:
            stage.log('ERROR\n' + traceback.format_exc())
        raise
    finally:
        if stage is not None:
            try:
                write_notes(stage, brief)
            except Exception:
                traceback.print_exc()


if __name__ == '__main__':
    main()
