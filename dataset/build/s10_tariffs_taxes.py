#!/usr/bin/env python3
"""S10 protection, support and taxes (stage entry).

The method lives in the s10_tariffs package; this file declares the inputs, runs the
build in the GTAP 12 ch.11B order (HS6 best-applied rate, then BACI weights, then the
named overrides, which sit on the schedules before the minimum with preferences), and
turns every result into a check, a flag or an output file.

Choices come from config/s10/s10_choices.csv (s10_tariffs/config.py). A missing or
mis-keyed choice row or config table stops the run before anything is written.

Tariffs: WITS/TRAINS HS6 schedules and preferences, BACI HS22 2022 weights (ch.11B).
Duty is removed from IO TLS up to the import share (ch.17A p.2). PSE budgetary A2-E,
MPS excluded (ch.11A). WTO export-subsidy notifications (ch.11C). Income and factor
taxes from OECD GRS, then IMF WoRLD (ch.15).

TRAINS-derived outputs are written for this private repository and listed in
output/NOT_FOR_PUBLICATION.md.
"""
import csv
import gzip
import hashlib
import os
import re
import subprocess
import sys
import traceback
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.stagekit import Stage, sha256, ROOT, DATA, BUILD, BASE_YEAR  # noqa: E402
from lib.private_files import private_paths  # noqa: E402
from s10_tariffs import checks as K  # noqa: E402
from s10_tariffs import energy_tax, export_tax, io_tls, product_tax, reports, support  # noqa: E402
from s10_tariffs import overrides as ov  # noqa: E402
from s10_tariffs import taxes as tax_mod  # noqa: E402
from s10_tariffs import trq as trq_mod  # noqa: E402
from s10_tariffs.build import FAMILY_SPOTS, NO_TRADE_MEMBERS, TariffBuild, known_outliers  # noqa: E402
from s10_tariffs.codes import CodeMap  # noqa: E402
from s10_tariffs.config import CHOICES, CHOICES_PATH, ConfigError, load_choices, read_table  # noqa: E402
from s10_tariffs.preferences import EU27, us_gsp_reached  # noqa: E402
from s10_tariffs.util import fnum, gz_write, write_csv  # noqa: E402

S09_STAMP_COMMIT = '14abcb6285a958a8098bb9ef797d393d5f5adf96'
S09_STAMP_TIME = '2026-10-27 23:22:29 UTC+7'
S09_SUMS = '02011b906893085f716642deaff058d2cd93daa9ec4cd344be2df22221a1ee9f'
S09_IO = 'e83facbfd23c2cb0f535cb52be976055da3179a44256c7e1c401020fc8b3a410'
S09_TRAVEL = '37c6971f75a328e137d199fee0d0038efbcdd2447e2649dbcf9d4249159a879d'
S08_SUMS = '9a3586c3e06b2bce68f8ea350f58d01794045dbfb03649c58e6abd091eb7fa74'
S07_SUMS = 'c5e753b863c1ccb9e95d3862980e1bf1c0ed45a9dbded8491d018ba6fdfeb556'
S01_SUMS = 'ff56cec81a4b7808a99d4c9b2cfb719a6cba75802979ca41aca34600da918392'
PRIOR_USA_WITH_REMEDIES_MUSD = 114872.7457011098    # snapshot 0626bda, 301/232 inside tm
PRIOR_CHINA_WITH_REMEDIES_MUSD = 77758.8473696033
PRIOR_WORLD_WITH_REMEDIES_BN = 557.393
# SHA-256 of a previous output SHA256SUMS file, and the commit that wrote it.
PREV_OUTPUT_COMMITS = {
    '3879645c467a65732ff91ed3334219abc2ddfd9a8cc250da35f923a5804577a2': '63f20e8',
    '3fa6b7b6f884b0e687ba0315462be9c97a09d03a0a3b088820c0afd7d4b4b336': '07093a3',
    '4e397a825a74b153286f86fa839f9dbea3a1e151448055743200530f01e8d7e4': '3b94538',
    '7ff15d775eb50f412f2d259176a063ab2671c0ff3f09b82caa29341524a0c1d1': '3e10cec',
    'a7467693f563a619609dfc15aaca23e0136aeb252a855577221bcfd5d44f0fa0': '7d7279c',
    '81a07aa6dfde1e143172bbad38acf3bf92530a19d40a1f697fdee482b0866bce': '826195d',
    '89f8b5a7378e519e472d4e3ea5f929f5c3d8248c041262553e4280b148930a4e': '460c6c7',
    '414954a699efd2cf2947190922cfaaeb6e22fd110d09ec26127af77e85e3eb00': 'c44290f',
    'bbef6b0d90c0eb25faa120d2df0a32d7c9ab4f110f682802e60e33ca30c7981c': '7998e62',
    'd044a1b977b207bb0bb80fdb1fe063b42122294c0330fbf9c3cd3408e858c378': '676a99f',
    'd83e5c2058f275e7da8d7f60228d12a66ced8f571c2dd382b0829b48c54dea66': '6b42ea7',
}

GOODS = ('crp', 'for', 'fsh', 'coa', 'oil', 'gas', 'ore', 'min', 'fbt', 'tal', 'wod', 'pap', 'pet', 'chm', 'pha', 'rpl',
         'nmm', 'stl', 'nfm', 'fmp', 'elc', 'eeq', 'mac', 'mvh', 'shp', 'tre', 'omf', 'wat', 'pub', 'art', 'pro', 'pst')
NEW_SECTORS = ('wat', 'pub', 'art', 'pro', 'pst')
SPOT_PAIRS = (('MEX', 'USA'), ('THA', 'MYS'), ('QAT', 'CHE'), ('ARG', 'BRA'))
N_REGIONS = 167
N_CUSTOMS_ROWS = 136

PRIVATE_OUTPUTS = (
    'hs6_applied_s10.csv.gz', 'tm_s10.csv.gz', 'vmsb_s10.csv.gz', 'duty_bilateral_s10.csv.gz', 'customs_compare_s10.csv',
    'usa_tariffs_s10.csv', 'io_s10.csv.gz', 'hs6_applied_delta_s10.csv', 'tls_split_s10.csv',
    'tariffs_301_232_addon_s10.csv', 'hs6_weight_diffs_s10.csv', 'preference_fill_s10.csv',
    'specific_duty_no_ave_s10.csv', 'rate_pattern_s10.csv', 'class_a_ave_s10.csv', 'korea_trq_s10.csv',
    'usa_chapter_s10.csv', 'energy_tax_s10.csv', 'trq_fill_s10.csv',
)
BASIS_ROWS = [
    ['io_s10.csv.gz', 'matrix', 'basic', 'TLS edited. Basic rows unchanged. Private.'],
    ['support_s10.csv', 'value_musd', 'budgetary USD million', 'PSE A2-E on crp.'],
    ['factor_tax_rates_s10.csv', 'value_musd', 'pre-removal io GDP, basic', 'Percent of GDP times io GDP.'],
    ['export_subsidy_s10.csv', 'outlay_usd_million', 'fob', 'WTO notifications.'],
    ['tls_split_s10.csv', 'tls_remaining_musd', 'basic', 'Private. Duty already removed.'],
    ['product_tax_pattern_s10.csv', 'vat_weight', 'statutory VAT rate (fraction) or indicator', 'VAT layer by region, agent and commodity '
     '(product_tax_pattern; S13 scales it to each column TLS).'],
    ['product_tax_layers_s10.csv', 'vat_musd', 'pre-removal io GDP, basic', 'OECD GRS VAT (or general consumption taxes) and excise, percent of GDP times io GDP.'],
    ['product_tax_control_s10.csv', 'share', 'share of non-energy product taxes', 'Eurostat naio_10_cp15 D21X31 by commodity group (EU-27, NOR, candidates).'],
    ['energy_tax_s10.csv', 'specific_usd_per_gj', 'specific (USD per GJ), not ad valorem', 'Private. Energy taxes by region, OECD NEERS use class and '
     'energy row (pet, coa, gas, ely): net tax, its base (TJ; USA road-fuel million bbl; electricity per S11 domestic use) and the specific rate; '
     'proxy rows for regions without data. S13 converts them to ad valorem at the S11 basic prices (GTAP 12 ch.12 §12.4.4).'],
    ['export_tax_s10.csv', 'rate', 'duty over VFOB', 'OECD GRS T_5124 2022 spread by WTO TPR product lists; RUS, IND and CHN from statutory 2022 rates '
     '(export_tax_rates_2022.csv). Booked as VFOB above VXSB.'],
    ['vfob_s10.csv.gz', 'vxsb_musd', 'basic', 'VFOB divided by one minus the booked export-subsidy rate, less VFOB times the export-tax rate. '
     'Cells with neither equal VFOB.'],
    ['hs6_applied_s10.csv.gz', 'rate_pct', 'applied rate', 'Private. One row per priced region-pair sector cell, BACI 2021-2023 average weight.'],
    ['tm_s10.csv.gz', 'tm', 'rate on cif', 'Private.'],
    ['vmsb_s10.csv.gz', 'vcif_musd', 'cif', 'Private. vmsb_musd is basic (tariff inclusive).'],
    ['duty_bilateral_s10.csv.gz', 'duty_musd', 'tariff wedge on cif', 'Private.'],
    ['customs_compare_s10.csv', 'collected_million_usd', 'cash', 'Private. Booked duty is on VCIF. USA collected_million_usd is OECD GRS T_5123. census_million_usd is Census IMDB CY2022, USA only.'],
    ['usa_tariffs_s10.csv', 'price_basis column', 'see column', 'Private.'],
    ['hs6_applied_delta_s10.csv', 'duty_new_musd', 'cif', 'Private. Importer x sector duty against S10_PREV_OUTPUT.'],
    ['tariffs_301_232_addon_s10.csv', 'implied_duty_musd', 'cif', 'Scenario only. Section 301 and 232 are not in baseline tm. Private.'],
    ['service_hs6_s10.csv', 'value_thousand_usd', 'baci', 'Lines with no tariff.'],
    ['hs6_weight_diffs_s10.csv', 'duty_delta_musd', 'cif', 'Private. Cells whose rate moved by more than 0.1 percentage points against S10_PREV_OUTPUT.'],
    ['preference_fill_s10.csv', 'bilateral_cells_lowered', 'applied rate against the cell MFN', 'Private.'],
    ['specific_duty_no_ave_s10.csv', 'trade_thousand_usd', 'baci thousand USD', 'Private. These lines add no duty.'],
    ['rate_pattern_s10.csv', 'new_rate', 'applied rate', 'Private. Cells above 100 percent.'],
    ['class_a_ave_s10.csv', 'statutory_ave', 'statute over unit value, or the ad valorem alternative', 'Private. BACI FOB where a unit value is used.'],
    ['korea_trq_s10.csv', 'rate_pct', 'in-quota, over-quota, or the average', 'Private. Korea TRQ headings with a volume and an in-quota rate.'],
    ['trq_fill_s10.csv', 'new_pct', 'HS6 average with each quota line at its fill-rule rate', 'Private. CAN, CHE, JPN and CHN quota '
     'headings (WTO AG-IMS MA:2 2022 fills) on the MFN schedule and the bulk preference lines; status says why a heading is left as held.'],
    ['usa_chapter_s10.csv', 'booked_duty_bn', 'baci fob line rate versus Census calculated duty', 'Private. Ex-China is the hard comparison.'],
    ['price_basis_s10.csv', 'price_basis', 'registry', 'This file.'],
]
# Choices with no branch of their own in the code: where each one is carried. Every other choice
# is read as C[...] where it acts (tests/test_s10_checks.py checks the two lists cover CHOICES).
DECISIONS_CARRIED = {
    'trq_line_rates': 'trq.new_rate: the in-quota line is the HS6 minimum line rate and the over-quota line its maximum',
    'trq_no_fill': 'trq.regime_of: a quota with no notified imports takes the in-quota rate',
    'trq_bilateral_fill': 'trq.apply: a preference line whose HS6 minimum is below the MFN minimum takes the in-quota rate on its quota lines',
    'egypt_alcohol_rates': 'sources.load_mfn keeps Reported lines with NBR_NA_LINES 0 (EGY 2203-2208); no ceiling',
    'composite_fold': 'weights.pass_rates sums member ISOs (CUW in XCB; NCL and PYF in XOC) with the BACI 2021-2023 average weights (the value name predates tariff_weights)',
    'xnf_xsm_importer': 'weights.pass_rates weights the XNF and XSM member ISOs by BACI 2022',
    'cis_ukraine_lapse': 'preference_lapses.csv row RUS B32 UKR 2016-01-01',
    'cis_other_ukraine': 'preference_lapses.csv has no KAZ, BLR or ARM row',
    'rus_mda_736': 'preference_lapses.csv has no RUS-MDA row (HS annex not in the files)',
    'saudi_mfn_ceiling': 'rates.Tariffs.line: applied is min(MFN, every usable preference)',
    'mfn_zip_notes': 'CRI and MUS 2021 MFN zips are empty and not read; their manifest years are 2022',
    'ace57_vehicles': 'WITS lines as given; nothing rebooked',
    'near_schedule_notes': 'customs_unions.csv: MRT not in ECOWAS, COK not in a union',
    'lby_ven_importer': 'sources.load_mfn: LBY 2021 and VEN 2022 own schedules; preferences where a group resolves',
    'lby_ven_partner': 'weights.Reference.cell: the pair own line rates, as for any cell with no BACI weight',
    'pal_pse_schedule': 'codes.CodeMap alias PSE -> PAL: the PSE schedule, trade and preference members are PAL',
    'tariff_base': 'build.TariffBuild.write: VCIF = S07 vfob + S08 vtwr; VMSB = VCIF x (1 + tm)',
    'oil_gas_tariffs': 'separate oil and gas cells; io_tls.effective_rates folds both into IO column B06',
    'non_icio_tls': 'donor TLS kept; the GRS VAT and excise shape its commodity structure only (product_tax_pattern)',
    'statutory_vs_collected_cap': 'screen 1: no cap',
    'statutory_vs_collected_below': 'screen 1: no cap below collections either',
    'screen_duty_base': 'weights.Accumulator.facing and facing_duty: duty on imports that face the line',
    'screen_diagnostics': 'screens 4, 6, 7, 11 and 12 are not in S10-Hscreens',
    'screen_cross_dedupe': 'screens.s10_suite.run: one material hit per importer and line across screens',
    'collections_materiality': 'screens.common.material: 0.02 bn or 0.1 percent of importer duty; USA uses Census',
    'collections_driver_cover': 'screen 1 drivers are screens 2, 3, 8 and 10 on the same build state',
    'fta_pair_reparse': 'screen 12 reads part-year 2022 entries',
    'stamp_prev_output': 'STAMP lines naming S10_PREV_OUTPUT and its SHA256SUMS',
    'io_s10_commit': 'io_s10.csv.gz is committed in this private repository',
    'earlier_year_conversion': 'screen 3: an earlier-year rate below 1 percent is marked earlier-year conversion',
    'wits_rate_as_given': 'sources.load_mfn and load_preferences: the booked line is the WITS/TRAINS rate or AVE',
}
Q_TARIFF = 'GTAP 12 ch.11B pp.1-2'
Q_POWER = 'GTAP 12 ch.2 p.5 and p.17'
Q_PSE = support.Q_PSE
Q_XS = support.Q_XS
Q_TAX = tax_mod.Q_TAX
Q_FIT = 'GTAP 12 ch.17A p.2'
Q_TLS = 'GTAP 12 ch.9D'
Q_TRAVEL = 'GTAP 12 ch.10B p.3'
Q_SIGN = 'TP01 rev2022 section 7 (printed p.9)'


def hard(S, cid, desc, result, threshold, concept):
    value, passed, detail = result
    S.check(cid, desc, 'hard', value, threshold, passed, concept, detail)


def output_sums_text(directory):
    lines = []
    for fn in sorted(os.listdir(directory)):
        if fn != 'SHA256SUMS':
            lines.append(f'{sha256(os.path.join(directory, fn))}  {fn}\n')
    return ''.join(lines)


def secret_hits(roots):
    pat = re.compile(br'(?i)(?:api[_-]?key|password)\s*[:=]\s*\S{12,}')
    hits = []
    for root in roots:
        if not os.path.exists(root):
            continue
        files = [root] if os.path.isfile(root) else [os.path.join(d, f) for d, dn, fs in os.walk(root)
                                                      for f in fs if 'archive' not in d and '__pycache__' not in d]
        for path in files:
            if path.endswith(('.gz', '.zip', '.xz', '.xlsx', '.pyc')) or os.path.getsize(path) > 8_000_000:
                continue
            if pat.search(open(path, 'rb').read()):
                hits.append(os.path.basename(path))
    return hits


def read_vcif(vxsb_path, vtwr_path):
    """VCIF = S07R vfob + S08 vtwr per (importer, exporter, sector); also the export-subsidy inputs."""
    vcif, vxsb_sec, vfob_rows = defaultdict(float), defaultdict(float), []
    bad = 0
    with gzip.open(vxsb_path, 'rt', newline='') as fh:
        for row in csv.DictReader(fh):
            if row['sector'] not in GOODS:
                continue
            vfob, vxsb = float(row['vfob_musd'] or 0.0), float(row['vxsb_musd'] or 0.0)
            if abs(vfob - vxsb) > 1e-6 or row.get('pre_tax') != 'yes':
                bad += 1
            vcif[(row['importer'], row['exporter'], row['sector'])] += vfob
            vxsb_sec[(row['exporter'], row['sector'])] += vfob
            vfob_rows.append((row['sector'], row['exporter'], row['importer'], vfob))
    with gzip.open(vtwr_path, 'rt', newline='') as fh:
        for row in csv.DictReader(fh):
            if row['sector'] in GOODS:
                vcif[(row['importer'], row['exporter'], row['sector'])] += float(row['vtwr_musd'] or 0.0)
    return vcif, vxsb_sec, vfob_rows, bad


def prev_duty(prev_dir):
    path = os.path.join(prev_dir, 'duty_bilateral_s10.csv.gz') if prev_dir else ''
    if not path or not os.path.exists(path):
        return None
    out = defaultdict(float)
    with gzip.open(path, 'rt', newline='') as fh:
        for row in csv.DictReader(fh):
            out[(row['importer'], row['sector'])] += float(row['duty_musd'] or 0.0)
    return out


def run(S, brief):
    s01 = S.upstream(ROOT + '/stages/S01_sets_registry')
    s02 = S.upstream(ROOT + '/stages/S02_macro')
    s07 = S.upstream(ROOT + '/stages/S07_trade')
    s08 = S.upstream(ROOT + '/stages/S08_margins')
    s09 = S.upstream(ROOT + '/stages/S09_services')
    cdir = BUILD + '/config/s10/'

    # ------------------------------------------------------------------ configuration
    cfg = S.inp(CHOICES_PATH, 'S10 choices')
    try:
        C = load_choices(cfg)
    except ConfigError as exc:
        S.check('S10-Hconfig', 's10_choices.csv has every implemented choice, each with an allowed value, decided_by and decided_at',
                'hard', 'stop', f'{len(CHOICES)} rows; 0 bad', False, 'S10 handoff section 1.3', str(exc))
        raise
    with open(cfg, newline='', encoding='utf-8') as fh:
        brief['choices'] = list(csv.DictReader(fh))
    S.check('S10-Hconfig', 's10_choices.csv has every implemented choice, each with an allowed value, decided_by and decided_at',
            'hard', f'{len(C)} rows; 0 bad', f'{len(CHOICES)} rows; 0 bad', True, 'S10 handoff section 1.3', '')
    for name, where in sorted(DECISIONS_CARRIED.items()):
        S.log(f'choice {name} = {C[name]}: {where}')
    for name, role in (
        ('preference_group_members.csv', '2022 member list for every WITS preference group code'),
        ('preference_partner_remap.csv', 'Cambodia 2020 and 2021 partner 356 is the China schedule'),
        ('agreement_families.csv', 'Successor codes of one agreement share a family'),
        ('uk_continuity.csv', 'UK continuity agreements in force in 2022'),
        ('preference_lapses.csv', 'Preference schemes lapsed by 2022, and the ones checked and kept'),
        ('preference_exceptions.csv', 'Importers with no TRAINS bilateral preference extract'),
        ('customs_unions.csv', 'Customs unions and legal internal zeros'),
        ('parent_customs_territory.csv', 'Territories without a schedule that apply a parent customs tariff'),
        ('korea_article71_lines.csv', 'Korea article 71 lines'),
        ('us_section232_calendar.csv', 'Section 232 calendar for the scenario file'),
        ('ave_outlier_lines.csv', 'AVE lines at or above 1,000 percent'),
        ('export_subsidy_products.csv', 'Export-subsidy HS lines'),
        ('fta_pairs_2022.csv', 'WTO RTA goods pairs in force in 2022, screen 12 only'),
        ('screen_explanations.csv', 'Evidence class per screen hit'),
        ('tariff_collected_scale.csv', 'beta v5 S5: importers and quota sectors scaled to collected duty'),
        ('sourced_line_overrides.csv', 'beta v5 K and S5-BGD: sourced HS6 line overrides behind switches'),
    ):
        S.inp(cdir + name, role)
    pref_exc = read_table('preference_exceptions.csv', ('importer', 'trains_preference_data', 'cause', 'source_checked',
                                                        'in_hpref_list'))

    # ------------------------------------------------------------------ inputs
    sectors_path = S.inp(s01 + '/output/sectors.csv', 'S01 sectors')
    regions_path = S.inp(s01 + '/output/regions.csv', 'S01 regions')
    map_path = S.inp(s01 + '/output/country_region_map.csv', 'S01 country map')
    members_path = S.inp(s01 + '/output/composite_members.csv', 'S01 composite members')
    concord = S.inp(s01 + '/output/concord_hs22_to_sector.csv', 'S01 HS22 concordance')
    macro_path = S.inp(s02 + '/output/macro_country.csv', 'S02 country GDP')
    vxsb_path = S.inp(s07 + '/output/vxsb_goods_s07r.csv.gz', 'S07 goods VXSB')
    vtwr_path = S.inp(s08 + '/output/vtwr_s08.csv.gz', 'S08 VTWR')
    io_path = S.inp(s09 + '/output/io_s09.csv.gz', 'S09 IO')
    travel_path = S.inp(s09 + '/output/travel_s09.csv.gz', 'S09 travel file, read only')
    baci_zip22 = S.inp(DATA + '/baci/BACI_HS22_V202601.zip', 'BACI HS22 zip (2023 weight year)')
    baci_zip17 = S.inp(DATA + '/baci/BACI_HS17_V202601.zip', 'BACI HS17 zip (2021 weight year)')
    baci_csv = DATA + '/baci/BACI_HS22_Y2022_V202601.csv'
    baci_countries = DATA + '/baci/country_codes_V202601.csv'
    if not os.path.exists(baci_csv) or not os.path.exists(baci_countries):
        raise SystemExit('BACI HS22 2022 extract is missing; run dataset/data/baci/fetch_baci_hs22.sh')
    bulk = DATA + '/wits_trains_bulk_2017_2022/'
    pref_root = DATA + '/wits_trains_pref_2022'
    tin = DATA + '/trains_internal/'
    earlier_dir = DATA + '/wits_trains_ave_earlier'
    P = {
        'mfn_manifest': S.inp(tin + 'trains_mfn_manifest.csv', 'TRAINS MFN manifest'),
        'mfn_tars': [S.inp(tin + f'trains_mfn_part{i}.tar.xz', f'TRAINS MFN part {i}') for i in (1, 2, 3, 4, 5)],
        'pref_zip': S.inp(bulk + 'trains_pref_ave_2017_2022.zip', 'WITS preferential AVE bulk 2017-2022'),
        'pref_dir': pref_root + '/sdmx',
        'supp_dir': DATA + '/trains_pref_2022_supp',
        'mys_pref': S.inp(DATA + '/malaysia_fta_schedules/extracted/mys_pref_lines_2022.csv',
                          'Malaysia 2022 preferential rates read from its own FTA schedules'),
        'tun_lists': S.inp(DATA + '/tunisia_turkey_fta/extracted/protocol1_lists.csv',
                           'Türkiye-Tunisia FTA Protocol I Lists I-III, Tunisian national lines'),
        'ncl_dd': S.inp(DATA + '/ncl_customs_tariff/extracted/ncl_dd_lines_2023.csv',
                        'New Caledonia DD by 8-digit line, tariff consolidated 1 January 2023'),
        'ncl_dd22': S.inp(DATA + '/ncl_customs_tariff/extracted/ncl_dd_2022_changed_hs6.csv',
                          'New Caledonia HS6 whose DD differed in 2022, from DRDNC notice 22001425'),
        'beneficiaries': S.inp(bulk + 'groups/wits_pref_beneficiaries_full.csv', 'WITS preference beneficiaries, full table'),
        'concord': concord,
        'earlier': {k: S.inp(DATA + f'/unsd_hs_correlation/hs2017_to_hs{y}.csv', f'UNSD HS2017 to HS{y} conversion')
                    for k, y in (('H4', '2012'), ('H3', '2007'), ('H2', '2002'))},
        'tun_xml': S.inp(DATA + '/wits_trains_sdmx/tun_mfn_2016_reported.xml', 'Tunisia TRAINS 2016 reported MFN'),
        'hts': S.inp(DATA + '/usitc_hts_2022/hts_2022_revision_12_json.json', 'HTS 2022 revision 12'),
        'tpa_hs22': S.inp(DATA + '/panama_tpa_2022/panama_tpa_2022_hs22.csv', 'Panama US-TPA HS2022 rates'),
        'tpa_lines': S.inp(DATA + '/panama_tpa_2022/panama_tpa_2022_lines.csv', 'Panama US-TPA national lines'),
        'trq': S.inp(DATA + '/panama_tpa_2022/trq_quota_vs_baci_2022.csv', 'Panama TPA quota against BACI 2022 tonnage'),
        'baci_csv': baci_csv,
        'baci_zip22': baci_zip22,
        'baci_zip17': baci_zip17,
        'hs_corr': S.inp(DATA + '/unsd_hs_correlation/HS2022toHS2017ConversionAndCorrelationTables.xlsx', 'UNSD HS2022-HS2017 correlation (2021 weight year)'),
        'egy_fx': S.inp(DATA + '/wdi/egy_pa_nus_fcrf_2019_2022.csv', 'Egypt WDI official exchange rate 2019-2022'),
        'mfn_ave_bulk': S.inp(bulk + 'trains_mfn_ave_2017_2022.zip', 'WITS MFN AVE bulk 2017-2022'),
        'ma2': S.inp(DATA + '/wto_agims_trq/agims_ma2_can_che_nor_jpn_isr_chn_2019_2023.csv',
                     'WTO AG-IMS Table MA:2 tariff-quota fills (trq_outside_kor_pan)'),
        'earlier_dir': earlier_dir,
    }
    for name in sorted(os.listdir(P['pref_dir'])):
        if name.endswith('.xml.gz'):
            S.inp(os.path.join(P['pref_dir'], name), 'WITS TRAINS preferential HS6 ' + name)
    for name in sorted(os.listdir(P['supp_dir'])):
        if name.endswith('.zip'):
            S.inp(os.path.join(P['supp_dir'], name), 'WITS TRAINS AVE preference zip ' + name)
    for name in sorted(os.listdir(earlier_dir)):
        if name.endswith('.xml'):
            S.inp(os.path.join(earlier_dir, name), 'Earlier UNCTAD AVE ' + name)
    tkm_html = S.inp(DATA + '/tkm_resolution_9925/resolution_9925.html', 'Resolution 9925 public page, no rate table')
    subsidy_hs = cdir + 'export_subsidy_products.csv'
    moneva_path = S.inp(DATA + '/oecd_pse/OECD_DF_MONEVA_2022.csv', 'OECD MONEVA 2022')
    fao_zip = S.inp(DATA + '/faostat_qv/Value_of_Production_E_All_Data_Normalized.zip', 'FAOSTAT value of production')
    grs_path = S.inp(DATA + '/oecd_grs/grs_rsglobal_2017_2022.csv', 'OECD GRS')
    grs_xt_path = S.inp(DATA + '/oecd_grs/grs_rsglobal_5121_5124_2017_2022.csv', 'OECD GRS T_5121 and T_5124 (export taxes)')
    vat_path = S.inp(DATA + '/vat_statutory/vat_statutory.csv', 'Statutory VAT schedules by commodity (OECD CTT 2024 Annex 2.A; product_tax_pattern)') \
        if C['product_tax_pattern'] != 'none' else None
    eurostat_pt_path = S.inp(DATA + '/eurostat_naio_product_taxes/naio_10_cp15_d21x31_2015_2022.csv',
                             'Eurostat supply tables, taxes less subsidies on products by CPA product (product_tax_pattern control)') \
        if C['product_tax_pattern'].endswith('eurostat_product_control') else None
    neer_path = S.inp(DATA + '/oecd_neer/neers_2021_2023.csv', 'OECD Net Effective Energy Rates 2021 and 2023')
    eurusd_path = S.inp(DATA + '/oecd_neer/eur_usd_ert_bil_eur_a.csv', 'Eurostat EUR/USD annual average')
    us_fuel_paths = (S.inp(DATA + '/eia_us_motor_fuel_taxes/pmm_fueltaxes.xlsx', 'EIA PMM federal and state motor fuel taxes (USA energy taxes)'),
                     S.inp(DATA + '/eia_us_motor_fuel_taxes/MER_T03.07C.csv', 'EIA MER T3.7c transportation petroleum consumption 2022'),
                     S.inp(DATA + '/eia_foks/pet_cons_821use_dcu_nus_a.htm', 'EIA FOKS distillate sales by end use (on-highway share)')) \
        if C['energy_tax_usa'] != 'pool_fill' else None
    eu_hh = {('gas', 'household'): S.inp(DATA + '/eurostat_energy_prices_households/nrg_pc_202_2022S1_2022S2.csv',
                                         'Eurostat household gas prices 2022, report only'),
             ('ely', 'household'): S.inp(DATA + '/eurostat_energy_prices_households/nrg_pc_204_2022S1_2022S2.csv',
                                         'Eurostat household electricity prices 2022, report only')}
    S.inp(cdir + 'energy_tax_classes.csv', 'NEERS sector to IO columns')
    S.inp(cdir + 'export_tax_products_2022.csv', 'Export-duty products and rates from WTO Trade Policy Reviews')
    S.inp(DATA + '/wto_tpr/README.md', 'WTO Trade Policy Review reports cited in export_tax_products_2022.csv')
    S.inp(cdir + 'export_tax_rates_2022.csv', 'Export-duty rates 2022 for RUS, IND and CHN (statutory, ad valorem equivalents)')
    for name, role in (('derived_aves_2022.csv', 'ad valorem equivalents behind export_tax_rates_2022.csv'),
                       ('export_duty_regimes_2022.csv', 'export-duty regimes 2022 (legal basis, dates, rates)'),
                       ('rus_crude_export_duty_2022.csv', 'Russian crude-oil export duty, monthly 2022'),
                       ('ind_saed_fuel_exports_2022.csv', 'India special additional excise duty on fuel exports 2022')):
        S.inp(DATA + '/export_duty_schedules_2022/' + name, role)
    S.inp(DATA + '/oecd_export_restrictions/oecd_export_restrictions_rus_ind_chn_2022.csv',
          'OECD Inventory of Export Restrictions on Industrial Raw Materials 2022 (CHN rates)')
    gfs_xt_path = S.inp(DATA + '/imf_gfs/gfs_soo_trade_taxes_rus_ind_chn_2017_2023.csv',
                        'IMF GFS G1152 taxes on exports (RUS revenue cross-check)')
    wdi_fx_path = S.inp(DATA + '/wdi/wdi_2017_2022_extract.csv', 'WDI PA.NUS.FCRF 2022 (GFS revenue to USD)')
    imf_path = S.inp(DATA + '/imf_world/imf_world_2017_2022.csv', 'IMF WoRLD refetch')
    gfs_tax_path = S.inp(DATA + '/imf_gfs/gfs_soo_income_ssc_gulf_2017_2023.csv',
                         'IMF GFS_SOO general government income taxes and social contributions, Gulf (income_tax_source)')
    fuel_sales_path = S.inp(cdir + 'fuel_sales_taxes_2022.csv', 'Fuel sales taxes outside VAT/GST and excise on the pet rows (fuel_sales_taxes)')
    wto_path = S.inp(DATA + '/wto_export_subsidies/export_subsidies_latest_le2022.csv', 'WTO export-subsidy notifications')
    fx_path = S.inp(DATA + '/wdi/pa_nus_fcrf_s10.csv', 'WDI PA.NUS.FCRF for subsidy years')
    customs_path = S.inp(DATA + '/customs_collected_internal/customs_collected_2022.csv', 'customs collections, report only')
    census_path = S.inp(DATA + '/census_imdb_2022/hs6_cty_rp_2022.csv', 'Census IMDB HS6, report only')

    # ------------------------------------------------------------------ binding to S09
    stamp_text = open(s09 + '/STAMP').read()
    repo_top = subprocess.run(['git', '-C', ROOT, 'rev-parse', '--show-toplevel'], capture_output=True, text=True).stdout.strip()
    touched = subprocess.run(['git', '-C', repo_top, 'log', '-1', '--format=%H', '--', 'dataset/stages/S09_services/STAMP'],
                             capture_output=True, text=True).stdout.strip()
    named = {k: (v in stamp_text) for k, v in (('S09 time', S09_STAMP_TIME), ('S08 sums', S08_SUMS), ('S07 sums', S07_SUMS),
                                                ('S01 sums', S01_SUMS))}
    hard(S, 'S10-G0bind', f'S09 snapshot commit {S09_STAMP_COMMIT[:7]}, its STAMP time, output SHA256SUMS, IO and travel hashes, and the '
         'S07, S08 and S01 sums named in that STAMP',
         K.bind({'S09 STAMP commit': (touched, S09_STAMP_COMMIT), 'S09 SHA256SUMS': (sha256(s09 + '/output/SHA256SUMS'), S09_SUMS),
                 'io_s09': (sha256(io_path), S09_IO), 'travel_s09': (sha256(travel_path), S09_TRAVEL),
                 **{k: (v, True) for k, v in named.items()}}), 'bound', 'stage kit G0')
    S.check('S10-Htravel', 'travel_s09 is read and not rewritten', 'hard', sha256(travel_path), S09_TRAVEL,
            sha256(travel_path) == S09_TRAVEL, Q_TRAVEL, '')
    S.flag('TRAVEL-S13', 'travel', 'Travel rows get no tariff, export tax or margin. S13 merges them.', 'no', C['travel_rows'], Q_TRAVEL)
    hard(S, 'S10-Hnov38', 'No input under trains_internal/v3.8 or v3.9, and the old-rate-plus-MFN-change token is gone',
         K.forbidden_inputs(list(S.inputs), open(cfg, encoding='utf-8').read()), 'clean', C['tariff_layer'])

    # ------------------------------------------------------------------ sets
    short_to_icio = {r['sector']: r['icio_code'] for r in csv.DictReader(open(sectors_path, newline=''))}
    if any(g not in short_to_icio for g in GOODS) or 'msp' not in short_to_icio:
        raise SystemExit('S01 sectors do not contain the 32 merchandise sectors plus msp')
    regions, region_type, region_geo = [], {}, {}
    for row in csv.DictReader(open(regions_path, newline='')):
        regions.append(row['region'])
        region_type[row['region']] = row['type']
        region_geo[row['region']] = row['gtap_geo']
    if len(regions) != N_REGIONS:
        raise SystemExit(f'expected {N_REGIONS} regions, got {len(regions)}')
    region_set = set(regions)
    cm = CodeMap(map_path, members_path, baci_countries)
    name_iso = defaultdict(set)
    for row in csv.DictReader(open(map_path, newline='', encoding='utf-8')):
        if row['code'] in cm.region and row['name']:
            name_iso[support.norm_name(row['name'])].add(row['code'])
    gdp_iso = {r['code']: float(r['GDP_musd'] or 0.0) for r in csv.DictReader(open(macro_path, newline=''))}
    sets = {'codemap': cm, 'goods': set(GOODS), 'short_to_icio': short_to_icio}

    # ------------------------------------------------------------------ tariffs: schedules, preferences, BACI
    tb = TariffBuild(S, C, P, sets)
    tb.load()
    tb.weigh()
    acc, sch = tb.acc, tb.schedules

    jr = tb.join()
    hard(S, 'S10-Hjoin', 'Every BACI code with trade, every schedule and preference reporter, every preference member and '
         'every numeric partner reaches a region through the one code map', K.join(jr, NO_TRADE_MEMBERS), 0,
         C['country_code_join'])
    hard(S, 'S10-Hgroups', 'preference_group_members.csv equals the WITS beneficiary table row by row',
         K.groups(tb.group_problems), 0, C['preference_group_members'])
    hard(S, 'S10-Hgroupmap', 'No preference row is dropped because its group code has no member list',
         K.unknown_groups(tb.state['log']), 0, C['preference_group_members'])
    hard(S, 'S10-Hkhm', "Cambodia's 2020-2021 partner 356 applies to China only", K.khm_partner(tb.state), 0, C['khm_acfta_partner'])
    hard(S, 'S10-Husgsp', 'No lapsed US GSP group or single-country row is applied',
         K.us_gsp(us_gsp_reached(tb.state, tb.lapses)), 0, C['us_gsp_lapse'])
    hard(S, 'S10-Hukcont', 'GBR is on an EU preference list only for an importer with a UK continuity agreement in force in 2022',
         K.uk_continuity(tb.state, tb.uk_applied, tb.uk_removed), 0, C['uk_continuity'])
    hard(S, 'S10-Hfamily-cover', 'Named pairs keep an agreement from each family in the cover',
         K.family_spots(tb.state, FAMILY_SPOTS), 0, C['agreement_families'])
    hard(S, 'S10-Hoverride', 'Each named override is on the schedule at its decided value: ZMB class A, Korea soy, crude, LNG, '
         'article 71 and TRQ, Morocco wheat, Cambodia 271012, Egypt 240220',
         K.schedule_values(sch, tb.nomen, tb.override_expect()), 0, C['ave_outlier_rule'])
    hard(S, 'S10-Htrq', 'TRQ fill rule outside KOR and PAN (trq_outside_kor_pan): every changed MFN quota heading is on the schedule '
         'at its rule rate, every changed preference line holds its rule rate, every rule rate lies within the HS6 minimum and '
         'maximum line rate, every quota heading has a status',
         trq_mod.check(tb.trq_rows, sch, tb.merged, tb.trq_expect), 0, C['trq_outside_kor_pan'])
    trq_status = defaultdict(int)
    for r in tb.trq_rows:
        trq_status[(r[0], 'mfn' if r[1] == '000' else 'pref', r[12])] += 1
    S.check('S10-Rtrq', 'TRQ headings of CAN, CHE, JPN and CHN by status (applied or the reason a heading is left as held); '
            'NOR and ISR checked and not applied', 'report', f'{sum(1 for r in tb.trq_rows if r[12] == "applied")} changed', 'report',
            True, trq_mod.Q_TRQ, '; '.join(f'{k[0]} {k[1]} {k[2]} {v}' for k, v in sorted(trq_status.items()))
            + '; not applied: ' + '; '.join(f'{k} ({v})' for k, v in sorted(trq_mod.CHECKED_NOT_APPLIED.items())))
    hard(S, 'S10-Have1000', 'Every AVE-sourced line at or above 1,000 percent with 2022 trade is in ave_outlier_lines.csv',
         K.ave_1000(tb.ave_1000(), known_outliers()), 0, C['ave_outlier_rule'])
    hard(S, 'S10-Habovemfn', 'No priced HS line sits above its MFN', K.above_mfn(acc.above_mfn), 0, C['tariff_rate_rule'])
    hard(S, 'S10-Hbest', 'On every 37th priced line the applied rate is at or below MFN and below the latest line of every usable '
         'agreement family, by a walk that does not call pref_rate; a forced union zero is 0',
         K.best_applied(acc.sample, tb.tariffs), 0, C['agreement_families'])
    hard(S, 'S10-Hiraq', 'No Iraq line is above its Resolution 393 chapter band', K.iraq(acc.irq_over), 0, C['iraq_tariffs'])
    hard(S, 'S10-Hweightyears', 'BACI 2021, 2022 and 2023 are all read for the weights, every HS17 2021 value reaches an '
         'HS22 code or is counted as dropped, and dropped value is under 0.1 percent', K.weight_years(tb.years.stats), 0,
         C['tariff_weights'])
    conv = tb.years.conversion_test(tb.P['baci_zip17'], 'BACI_HS17_Y2022_V202601.csv', lambda h: tb.nomen.sector.get(h))
    hard(S, 'S10-Hweightconv', 'BACI HS17 2022 converted with the 2021 conversion table and split matches BACI HS22 2022 '
         'by GTAP sector: misallocation under 2 percent of world trade, no sector of 1 percent or more off by over 10 percent',
         K.weight_conversion(conv), 0, C['tariff_weights'])
    hard(S, 'S10-Hparent', 'Territories on a parent customs tariff carry the parent schedule line as MFN on the goods '
         'the union covers, the applied rate is not above it, and lines outside the union have no rate',
         K.parent_territory(acc.parent, tb.tariffs.parents), 0, C['importer_without_schedule'])
    hard(S, 'S10-Hpanama', 'PAN<-USA lines with a TPA rate are at or below min(TPA, MFN)', K.panama(acc.pan, tb.tpa), 0,
         C['panama_tpa'])
    src_stats = {'TUN': len(sch['TUN'].rate), 'TUN_raised': tb.tun_raised, 'LBY': len(sch['LBY'].rate) if 'LBY' in sch else 0,
                 'VEN': len(sch['VEN'].rate) if 'VEN' in sch else 0, 'TKM_scheduled': tb.tariffs.has_schedule('TKM')}
    hard(S, 'S10-Hsources', 'Tunisia, Libya and Venezuela schedules are in the run and Turkmenistan has none (named exception)',
         K.sources_present(src_stats), 'each present', C['tunisia_schedule'])

    # ------------------------------------------------------------------ cells, tm, VMSB
    S.log('reading VFOB and VTWR')
    vcif, vxsb_sec, vfob_rows, vfob_bad = read_vcif(vxsb_path, vtwr_path)
    hard(S, 'S10-Hvfob', 'S07R goods VFOB equals VXSB and is pre-tax, so the duty base is that FOB plus VTWR',
         K.vfob_pretax(vfob_bad), 0, C['vxsb_from_vfob'])
    tb.cells(vcif)
    tb.collected_scale = {}
    if C['tariff_collected_scale'] != 'off':
        # beta v5 S5 (David 2026-10-27): a labelled departure from GTAP 12 ch.11B (applied rates times trade)
        collected = {}
        with open(customs_path, newline='') as fh:
            for row in csv.DictReader(fh):
                collected[row['iso']] = float(row['collected_million_usd'] or 0.0)
        scale_rows = read_table('tariff_collected_scale.csv', ('importer', 'sector', 'reason', 'source'))
        bad = [f"{r['importer']} {r['sector']}" for r in scale_rows if r['importer'] not in region_set or r['sector'] not in GOODS]
        if bad:
            raise ConfigError(f'tariff_collected_scale.csv: not an S10 region or goods sector: {bad}')
        scaled = tb.scale_to_collected(scale_rows, collected, vcif)
        S.check('S10-Rcollscale', 'tariff_collected_scale (beta v5 S5, departure from GTAP 12 ch.11B): listed quota sectors scaled by '
                'min(1, collected / booked duty); USD million', 'report', f'{len(scaled)} importers', 'report', True,
                C['tariff_collected_scale'], '; '.join(
                    f"{i} {'+'.join(d['sectors'])} factor {d['factor']:.4f}: booked {d['booked_before']:.1f} -> {d['booked_after']:.1f} "
                    f"(listed {d['listed_before']:.1f}), collected {d['collected']:.1f}" for i, d in scaled.items()))
        for imp, d in scaled.items():
            S.adjust(imp, f"{'+'.join(d['sectors'])} tm scaled x {d['factor']:.4f} to collected duty {d['collected']:.1f} USD m",
                     fnum(d['booked_before']), fnum(d['booked_after']), C['tariff_collected_scale'],
                     'beta v5 S5; departure from GTAP 12 ch.11B', 'no')
    prev_dir = os.environ.get('S10_PREV_OUTPUT', '').strip()
    tb.write(S.out, vcif, prev_dir)
    rules = defaultdict(lambda: [0, 0.0, 0.0])
    for key, rule in tb.rule.items():
        rules[rule][0] += 1
        rules[rule][1] += vcif[key]
        rules[rule][2] += tb.duty_cell[key][0]
    rule_text = '; '.join(f'{r} cells {n} vcif {v / 1000:.3f} bn duty {d / 1000:.3f} bn' for r, (n, v, d) in sorted(rules.items()))
    S.log('cells ' + rule_text)
    hard(S, 'S10-Hweight', 'The BACI weight inside the sector cells equals the BACI value of the priced lines',
         K.weights(sum(acc.den.values()), acc.priced), 0, C['tariff_weights'])
    # B9: against values the build did not write (identity part labelled in the detail)
    bilateral = {k: acc.num[k] / acc.den[k] * tb.collected_scale.get(k, 1.0) for k, d in acc.den.items() if d > 0}
    hard(S, 'S10-Hwedge', 'Written tm, VMSB and duty files against independent values: every VCIF cell written, VCIF re-read from '
         'S07 vfob plus S08 vtwr, bilateral tm equal to the BACI line accumulator; identity part: duty = VCIF x tm and VMSB >= VCIF',
         K.wedge_files(K.read_back_cells(S.out), K.vcif_independent(vxsb_path, vtwr_path, set(GOODS)), bilateral), 0, Q_POWER)
    hard(S, 'S10-Hcu', 'A cell between two regions that hold only EU customs-territory members carries no duty on any good',
         K.customs_union(tb.rate, tb.cu_cells), 0, C['legal_internal_zeros'])
    eu_outside = sorted({i for k in tb.rate if k[0] in EU27 and k[1] in EU27 for i in cm.members[k[1]] if i not in tb.unions.eu_territory})
    eu_duty = sum(tb.duty_cell[k][0] for k in tb.rate if k[0] in EU27 and k[1] in EU27)
    S.flag('EU-REGION-NON-EU-MEMBERS', ' '.join(eu_outside),
           f'EU region pairs carry {eu_duty:.6f} USD million of duty because these members of EU regions are outside the EU '
           'customs territory and are priced at their own line rates.', 'no', C['legal_internal_zeros'], 'GTAP 12 ch.11B §B.3')
    with_schedule = {cm.region_of(i) for i in cm.region if tb.tariffs.has_schedule(i)}
    hard(S, 'S10-Hcoverage', 'No importer with a schedule is missing on every goods cell',
         K.every_cell_rated(tb.rule, with_schedule), 0, C['missing_baci_weight'])
    hard(S, 'S10-Hspot', 'wat, pub, art, pro and pst show a preference on MEX<-USA, THA<-MYS, QAT<-CHE and ARG<-BRA',
         K.spots(tb.rate, tb.mfn_cell, SPOT_PAIRS, NEW_SECTORS), 0, C['new_sector_preference'])
    hard(S, 'S10-Hpref', 'An importer on the exception list has no preference cell; importers with a resolved preference do',
         K.pref_exceptions(pref_exc, tb.pref_importers), 0, C['preference_exceptions'])
    written = {}
    with gzip.open(S.out + '/tm_s10.csv.gz', 'rt', newline='') as fh:
        for row in csv.DictReader(fh):
            if row['importer'] == 'USA':
                written[(row['importer'], row['exporter'], row['sector'])] = float(row['rate_pct'])
    hard(S, 'S10-Hno301', 'Written USA tm equals the HS6 line-rate cells; the 301/232 layer is only in the scenario file',
         K.no_addon_in_tm(written, {k: float(fnum(v)) for k, v in tb.rate.items() if k[0] == 'USA'}), 0, C['us_301_232'])
    S.check('S10-Rv39', 'Rebuilt cells against S10_PREV_OUTPUT', 'report',
            f'cells with a rate move above 0.1 pp {tb.n_diffs}; previous world duty '
            f'{(tb.prev_duty_world or 0) / 1000:.3f} bn; this run {tb.world_duty / 1000:.3f} bn', 'report', True,
            C['tariff_layer'], f'pin {prev_dir or "not set"}. hs6_weight_diffs_s10.csv and hs6_applied_delta_s10.csv.')

    # ------------------------------------------------------------------ tariff flags
    usa_sch = sch['USA']
    c2709, c1701 = tb.nomen.code(usa_sch.nomen, '270900'), tb.nomen.code(usa_sch.nomen, '170199')
    changed = [(iso, code) for iso, s in sch.items() for code, how in s.how.items()
               if how == 'reported' and code in s.ave and abs(s.ave[code] - s.rate[code]) > 1e-9]
    S.flag('TRAINS-AVE-SERIES', 'MFN',
           f'Reported where NBR_NA_LINES is 0, else AVEEstimated. US 270900 AVE {usa_sch.ave.get(c2709)} used '
           f'{usa_sch.rate.get(c2709)}; US 170199 AVE {usa_sch.ave.get(c1701)} used {usa_sch.rate.get(c1701)}. Reported replaced '
           f'AVEEstimated on {len(changed)} lines in {len({i for i, _c in changed})} schedules '
           f'({sum(1 for i, _c in changed if i == "USA")} US). UNCTAD AVE, not a MAcMap AVE.',
           'no', C['trains_ave_series'], Q_TARIFF)
    no_ave_isos = {i for (i, _h), v in acc.no_ave.items() if v > 0}
    S.flag('SPECIFIC-DUTY-NO-AVE', 'TRAINS',
           f'{sum(1 for v in acc.no_ave.values() if v > 0)} importer x HS lines with 2022 trade in {len(no_ave_isos)} countries have a '
           f'specific duty and no AVE ({tb.no_ave_trade / 1e6:.3f} bn FOB). They are left out of the weight and add no duty.',
           'no', C['specific_no_ave_lines_excluded_from_weight'], Q_TARIFF)
    S.flag('PREFERENCE-ONLY', 'TRAINS',
           f'Lines with a preference and no MFN are left out of both averages ({acc.pref_only[0]} BACI lines, '
           f'{acc.pref_only[1] / 1e6:.3f} bn FOB). Lapses applied {len(tb.state["log"]["lapses_applied"])}; '
           f'single-country rows dropped {len(tb.state["log"].get("single_country_dropped", []))}.',
           'no', C['tariff_rate_rule'], 'Applied cannot exceed MFN.')
    if tb.state['log']['lapses_skipped']:
        S.flag('LAPSE-CUTOFF', 'preferences', 'Not applied for 2022 because lapsed_on is after 2022-01-01: '
               + '; '.join(' '.join(map(str, x)) for x in tb.state['log']['lapses_skipped']), 'no', C['lapse_cutoff'], 'David 2026-10-22')
    S.flag('CLASS-A-AVE', 'ZMB EGY',
           f'Zambia vehicle lines use the statutory ad valorem alternative of the mixed duty. Egypt 240220 is EGP 100/kg over the '
           f'BACI 2022 FOB unit value {tb.egy_uv:.4f} USD/kg at {tb.egy_fx:.4f} EGP/USD: AVE {tb.egy_ave:.4f} '
           f'(raw {tb.egy_before}). Details in class_a_ave_s10.csv. Decided by David 2026-10-22.',
           'no', C['ave_outlier_rule'], 'Guimbard, Jean, Mimouni and Pichot 2012 pp.8-9. Departure: BACI FOB, importer unit value.')
    maize = ov.korea_trq_rates()['100590']
    S.flag('KOREA-TRQ', 'KOR', f"Maize 100590 rate {maize['rate']} regime {maize['regime']} fill {maize['fill']}. "
           f"{len(ov.korea_trq_rates())} Korean TRQ headings take the fill rule. Rates in korea_trq_s10.csv.",
           'no', C['maize_trq_basis'], 'Guimbard et al. 2012 pp.10-11. ' + C['korea_trq_full_fill'])
    S.flag('TKM-EXCEPTION', 'TKM', f'Resolution 9925 ({os.path.basename(tkm_html)}) names the resolution and has no duty table. '
           f'No Turkmenistan rate is filled; TKM cells have tm 0 (tkm_exception). BACI value with no rate '
           f'{acc.no_rate.get("tkm", 0.0) / 1e6:.3f} bn.', 'no', C['tkm_tariffs'], 'not in GTAP text')
    S.flag('MYS-PREFERENCE-SCHEDULES', 'MYS', 'Malaysia 2022 preferences from its own schedules (national lines read, with an ad '
           'valorem rate): ' + '; '.join(f'{k} {v[0]}/{v[1]}' for k, v in sorted(tb.mys_stats.items())) + '. RCEP (from 18 '
           'March 2022) and CPTPP (from 29 November 2022) are applied as in force in 2022. AANZFTA keeps the 2014 TRAINS lines '
           '(no schedule among the sources); AIFTA is not read (MICECA covers India).', 'no', C['mys_preference_schedules'],
           'GTAP 12 ch.11B §B.2')
    S.flag('NCL-TARIFF-2023', 'NCL', 'New Caledonia DD from the tariff consolidated on 1 January 2023 (no 2022 consolidation is '
           'published), with the 2022 DD restored on the HS6 that DRDNC notice 22001425 shows changed on 1 January 2023 '
           '(ncl_dd_2022_changed_hs6.csv: 210500, 482390, 847989; the other changes merge 8-digit lines at the same DD). '
           'EU and OCT origin free of DD. TGC, TSPA, TRM and the other taxes are not tm.', 'no', C['ncl_schedule'],
           'GTAP 12 ch.11B §B.2')
    if C['usa_pharma_appendix'].startswith('hts_2022'):
        S.flag('US-PHARMA-KL', 'USA', f"HTS 2022 Special K and L are erga omnes zeros on the US MFN: {tb.kl_stats['hs6']} HS6 "
               f"({tb.kl_stats['kl_lines']} rate-bearing national lines). A mixed HS6 is the simple average of its national lines "
               'with K or L lines at zero. A rate-bearing 8-digit line counts even when its only children are statistical suffixes.',
               'no', C['usa_pharma_appendix'], 'HTS 2022 revision 12')
    else:
        S.flag('US-PHARMA-KL', 'USA', f"No K/L overlay: the US MFN is TRAINS as held. HTS 2022 marks {tb.kl_stats['hs6']} HS6 "
               f"({tb.kl_stats['kl_lines']} rate-bearing national lines) with Special K or L; the zero applies only to the "
               'products named in the Pharmaceutical Appendix, which TRAINS does not separate.',
               'no', C['usa_pharma_appendix'], 'HTS 2022 revision 12')
    no_sched = sorted({i for (i, h), v in acc.no_rate_imp.items() if h == 'no_schedule' and v > 0})
    S.flag('IMPORTER-WITHOUT-SCHEDULE', ' '.join(no_sched),
           f'These importer ISOs have no TRAINS schedule and are left out of the weight; their region rate comes from members with '
           f'a schedule ({acc.no_rate.get("no_schedule", 0.0) / 1e6:.3f} bn BACI value). '
           f'{" and ".join(sorted(tb.tariffs.parents))} apply the parent customs tariff on the goods their union covers '
           f'({acc.how.get("parent_schedule", 0.0) / 1e6:.3f} bn priced at the parent MFN line); their other lines are listed here.',
           'no', C['importer_without_schedule'], 'GTAP 12 ch.11B §B.3')
    diag = [(k, vcif[k], tb.duty_cell[k][0]) for k in tb.rate if k[0] == k[1]]
    S.flag('COMPOSITE-DIAGONAL', 'composites',
           f'{len(diag)} goods flows inside one composite region are priced at the member-pair rates, trade weighted '
           f'(VCIF {sum(v for _k, v, _d in diag) / 1000:.3f} bn, duty {sum(d for _k, _v, d in diag) / 1000:.3f} bn). '
           'Intra-EU members are zero.', 'no', C['composite_diagonal_tariffs'], 'GTAP 12 ch.11B §B.3')
    S.flag('CELL-RULES', 'tm', rule_text + '. nb1_reference_group and nb1_pair_simple are cells with VCIF and no BACI weight '
           '(pair own HS6 rates weighted by the importer total HS6 imports). missing has tm 0.',
           'no', C['missing_baci_weight'], 'Guimbard et al. 2012 p.10')
    if tb.above_100:
        S.flag('RATE-ABOVE-100', 'tm', f'{tb.above_100} cells have an applied rate above 100 percent. Reported, not capped.',
               'no', C['tariff_rate_rule'], 'rate_pattern_s10.csv')
    S.flag('NO-CENSUS-OVERRIDE', 'USA', 'Section 301 and 232 are not in the baseline rate; tariffs_301_232_addon_s10.csv holds them. '
           'Rates are not scaled to Census.', 'no', C['us_301_232'], 'GTAP 12 ch.11B §B.4')
    S.flag('THREE-YEAR-WEIGHTS', 'BACI', 'Weights are the BACI 2021-2023 average, each year 1/3, as in ch.11B. BACI 2021 (HS17) '
           'goes to HS22 through the UNSD conversion table (S10-Hweightconv).',
           'no', C['tariff_weights'], Q_TARIFF)
    S.flag('SERVICE-TARIFF-ZERO', 'services', 'HS lines outside the 32 merchandise sectors have no tariff.',
           'no', C['service_tariffs'], Q_TARIFF)
    S.flag('EAC-CET-H1', 'EAC', 'The 2022 TRAINS file is the July CET book used for the whole year. No blend.',
           'no', C['eac_cet_first_half'], 'David 2026-10-23')
    S.flag('PREP-H10', 'TKM', 'TKM gas 9.5 percent versus EI is accepted. S11 binds PR #72.', 'no', C['tkm_gas_prep_h10'],
           'David 2026-10-20')

    # ------------------------------------------------------------------ IO: duty out of TLS
    S.log('removing duty from IO TLS')
    duty_cells = defaultdict(lambda: [0.0, 0.0])
    for (imp, _exp, short), (duty, base) in tb.duty_cell.items():
        duty_cells[(imp, short)][0] += duty
        duty_cells[(imp, short)][1] += base
    eff = io_tls.effective_rates({k: tuple(v) for k, v in duty_cells.items()}, GOODS)
    table = io_tls.IOTable(io_path)
    new_tls, io_stats, pre = io_tls.remove_duty(table, regions, eff, GOODS)
    io_tls.write_io(table, new_tls, S.out + '/io_s10.csv.gz')
    hard(S, 'S10-Hbasic', 'Basic dom and imp rows are byte-identical to io_s09',
         K.identical(io_tls.non_tls_lines(io_path), io_tls.non_tls_lines(S.out + '/io_s10.csv.gz')), 0, Q_SIGN)
    S.check('S10-Rduty-excess', 'Duty above the column import share of TLS is reported and not netted', 'report',
            f"{io_stats['excess']:.6f} USD million across {io_stats['excess_cols']} columns; removed {io_stats['removed']:.6f}",
            'report; gap to S13 FIT', True, Q_FIT,
            f"pre-existing negative basic cells {io_stats['neg_basic']}; negative TLS cells {io_stats['neg_tls']}")
    if io_stats['excess'] > 0:
        S.flag('DUTY-EXCESS', 'TLS', f"Duty exceeded the import share of TLS by {io_stats['excess']:.6f} USD million on "
               f"{io_stats['excess_cols']} columns. Not netted; S13 FIT closes it.", 'no', C['duty_from_tls'], Q_FIT)
    if io_stats['neg_tls']:
        S.flag('NEGATIVE-TLS', 'IO', f"{io_stats['neg_tls']} TLS cells were already negative in io_s09 (upstream subsidies).",
               'no', Q_SIGN, 'upstream io_s09')
        S.adjust('ALL', 'negative TLS cells', str(io_stats['neg_tls']), str(io_stats['neg_tls']),
                 'inherited IO subsidy, not an S10 plug', 'upstream io_s09; ' + Q_SIGN, 'cited')
    split_rows, unallocated = io_tls.tls_split(table, new_tls, regions)
    write_csv(S.out + '/tls_split_s10.csv', ['region', 'column', 'tls_remaining_musd', 'dom_basic_musd', 'imp_basic_musd',
                                             'dom_tax_musd', 'imp_tax_musd', 'unallocated_musd', 'price_basis'], split_rows)
    if unallocated:
        S.flag('TLS-UNALLOCATED', 'split', f'{unallocated} columns had no positive basic flow; their TLS stays unallocated.',
               'no', C['tls_split'], 'PLAN (f) b1 step 5')
    # ------------------------------------------------------------------ energy taxes on the energy rows (fix list A1)
    S.log('energy taxes on the pet, coa, gas and ely rows')
    neer_raw = energy_tax.read_neer(neer_path)
    lcu_ratio = None
    if C['energy_tax_fx'] == 'lcu_neers_year_to_usd_base_year_wdi':
        # beta v5 E6 (David 2026-10-27): the NEERS-year EUR rate overstated 2022 USD revenues by 10-15% outside the USA
        lcu_ratio = energy_tax.lcu_ratios(wdi_fx_path, energy_tax.years_of(C['energy_tax_year']), BASE_YEAR)
    neer_rev = energy_tax.revenues(neer_raw, energy_tax.read_fx(eurusd_path), C['energy_tax_year'],
                                   C['energy_subsidies'], lcu_ratio=lcu_ratio)
    if lcu_ratio is not None:
        neer_isos = {k[1] for k in neer_raw if k[0] in energy_tax.years_of(C['energy_tax_year'])}
        lost = sorted(i for i in neer_isos if i in regions and region_type[i] == 'single' and i not in neer_rev)
        S.check('S10-Henergyfx', 'energy_tax_fx (beta v5 E6): every single-country region with NEERS rows has a WDI PA.NUS.FCRF '
                'ratio for the NEERS year and the base year', 'hard', len(lost), 0, not lost, C['energy_tax_fx'],
                'left out: ' + (', '.join(lost) or 'none'))
        y0 = energy_tax.years_of(C['energy_tax_year'])[0]
        moves = sorted(((lcu_ratio[(i, y0)], i) for i in neer_rev if (i, y0) in lcu_ratio))
        S.check('S10-Renergyfx', f'energy_tax_fx: NEERS revenue factor LCU/USD {y0} over {BASE_YEAR} (1 = USA; euro area about 0.89)',
                'report', f'{len(moves)} countries', 'report', True, C['energy_tax_fx'],
                '; '.join(f'{i} {f:.3f}' for f, i in moves)
                # composite regions take proxy rows (only single regions are NEERS sources), so members left out change no value
                + '. NEERS codes left out (no WDI ratio; aggregates or composite-region members, never a source): '
                + (', '.join(sorted(i for i in neer_isos if i not in neer_rev)) or 'none'))
    hard(S, 'S10-Hneeryear', 'Year rule: the OECD NEERS years used (energy_tax_year) are the oecd_neer year in config/source_years.csv, '
         'the latest at or before the base year', K.neer_year(energy_tax.years_of(C['energy_tax_year']), S.inputs[neer_path]['year_used'], BASE_YEAR),
         0, C['energy_tax_year'])
    energy_source_of = {}
    if us_fuel_paths:
        # fix-round A1: DF_NEERS has no US values; the USA is a source region from EIA road-fuel excise data
        us_rev, us_det = energy_tax.us_motor_fuel(*us_fuel_paths)
        neer_rev['USA'] = us_rev
        energy_source_of['USA'] = 'EIA PMM federal and average state motor fuel excise 2022 x MER volumes'
        S.check('S10-Rusafuel', 'USA road-fuel excise 2022 booked as the ROAD revenue on the pet row (energy_tax_usa; USD bn)', 'report',
                f"{sum(v[0] for v in us_rev.values()) / 1000:.3f}", 'report', True, C['energy_tax_usa'],
                f"gasoline {us_det['tax_musd']['gasoline'] / 1000:.3f} bn ({us_det['gallons']['gasoline'] / 1e9:.2f} bn gal at {us_det['rate_usd_per_gal']['gasoline']:.4f} USD/gal); "
                f"diesel {us_det['tax_musd']['diesel'] / 1000:.3f} bn ({us_det['gallons']['diesel'] / 1e9:.2f} bn gal at {us_det['rate_usd_per_gal']['diesel']:.4f} USD/gal; "
                f"on-highway share {us_det['onhighway_share']:.4f}, FOKS {us_det['onhighway_share_year']}); federal {us_det['federal_usd_per_gal']['gasoline']:.3f} and "
                f"{us_det['federal_usd_per_gal']['diesel']:.3f} USD/gal")
    # fuel_sales_taxes (round-3 fix wE2, QA round 2 P8): IND state VAT on POL products, BRA ICMS on fuels
    fuel_sales, sales_by_iso = {}, defaultdict(dict)
    if C['fuel_sales_taxes'] != 'none':
        fx_lcu = {}
        with open(wdi_fx_path, newline='') as fh:
            for row in csv.DictReader(fh):
                if row['series'] == 'PA.NUS.FCRF' and row['year'] == str(BASE_YEAR) and row['value']:
                    fx_lcu[row['iso3']] = float(row['value'])
        fuel_sales = energy_tax.fuel_sales_taxes(energy_tax.read_neer(neer_path), C['energy_tax_year'], fx_lcu, path=fuel_sales_path)
        for iso, d in sorted(fuel_sales.items()):
            slot = neer_rev.get(iso, {}).get((d['cls'], d['row']))
            if slot is None:
                raise ConfigError(f'fuel_sales_taxes {iso}: no NEERS {d["cls"]} {d["row"]} row to book on')
            slot[0] += d['booked_musd']
            sales_by_iso[iso][(d['cls'], d['row'])] = d['booked_musd']
            energy_source_of[iso] = f'OECD NEERS {iso} + ' + d['source'][:60]
    S.check('S10-Rfuelsales', 'Fuel sales taxes outside VAT/GST and excise booked on the pet ROAD row (fuel_sales_taxes; USD bn)', 'report',
            f"{sum(d['booked_musd'] for d in fuel_sales.values()) / 1000:.3f}", 'report', True, C['fuel_sales_taxes'],
            '; '.join(f"{i} total {d['total_musd'] / 1000:.3f} bn at {d['fx']:.4f} LCU/USD, {d['cls']} share {d['share']:.4f} of the NEERS "
                      f"{'+'.join(d['sources'])} base, booked {d['booked_musd'] / 1000:.3f} bn" for i, d in sorted(fuel_sales.items())))
    trade_weight, energy_net = defaultdict(float), defaultdict(float)
    for sector, exp, imp, vfob in vfob_rows:
        trade_weight[exp] += vfob
        trade_weight[imp] += vfob
        if sector in energy_tax.TRADED_ENERGY:
            energy_net[exp] += vfob
            energy_net[imp] -= vfob
    pool_of = {r: energy_tax.GEO15.get(region_geo[r], region_geo[r]) for r in regions}
    region_iso = {r: r for r in regions if region_type[r] == 'single'}
    energy_rows, energy_sum = energy_tax.build(regions, region_iso, pool_of, trade_weight, neer_rev, energy_tax.load_classes(), C,
                                               source_of=energy_source_of, energy_net=energy_net, sales=sales_by_iso)
    write_csv(S.out + '/energy_tax_s10.csv', energy_tax.FILE_COLUMNS, energy_rows)
    hard(S, 'S10-Henergy', 'energy_tax_s10 (GTAP 12 ch.12 §12.3.3, §12.3.10): every source region carries each of its NEERS/EIA class revenues '
         'once with its tax base and specific rate (tax / base), every other region one proxy row naming source regions, all values finite',
         K.energy_tax(energy_rows, neer_rev, region_iso, regions if C['energy_tax_rows'] != 'one_column_rate' else []), 0, C['energy_tax_rows'])
    et = energy_sum['totals']
    S.flag('ENERGY-TAX-ROWS', 'TLS', f"Energy taxes as specific rates ({C['energy_tax_rows']}, {C['energy_tax_year']}, {C['energy_subsidies']}): "
           f"source revenue pet {et.get('pet', 0) / 1000:.3f} bn, coa {et.get('coa', 0) / 1000:.3f}, gas {et.get('gas', 0) / 1000:.3f}, "
           f"ely {et.get('ely', 0) / 1000:.3f} bn. {len(energy_sum['own'])} source regions (OECD NEERS{', USA from EIA' if energy_source_of else ''}); "
           f"{len(energy_sum['filled'])} take the {C['energy_tax_fill']} fill, of which {len(energy_sum['zero'])} have no proxy and carry no energy tax. "
           'S13 converts the rates to ad valorem at the S11 basic prices and holds them (energy_tax_s10.csv); the column TLS moves.',
           'no', C['energy_tax_fill'], energy_tax.Q_ENERGY)
    eu = energy_tax.eurostat_rates(eu_hh)
    cmp_eu = [f'{energy_tax.EUROSTAT_ISO3[geo]} {rate:.3f}' for (geo, row, _who), rate in sorted(eu.items())
              if row == 'ely' and energy_tax.EUROSTAT_ISO3.get(geo) in region_iso]
    S.check('S10-Renergyeu', 'Eurostat 2022 household electricity non-VAT taxes and levies over the price before taxes (compare the S13 '
            'household ely energy_rate in energy_tax_rates_s13.csv, which is the NEERS electricity excise over the S11 basic price)', 'report',
            f'{len(cmp_eu)} countries', 'report', True, energy_tax.Q_ENERGY, 'Eurostat: ' + '; '.join(cmp_eu))
    S.flag('PSE-INPUT-ROWS-NEEDS-SOURCE', 'PSE', 'NEEDS-SOURCE: fertiliser and farm-power payments on the chm and ely rows need the '
           'OECD PSE country tables with PIV by input, 2022 (MONEVA gives PIV as one total). PIV stays on the crp column rate.',
           'no', C['pse_input_rows'], 'fix list A1 (QA#12)')
    S.adjust('ALL', 'tariff revenue removed from TLS', '0', fnum(io_stats['removed']),
             'effective duty rate times imported use, capped at the import share of TLS', Q_FIT + '; ' + C['duty_from_tls'], 'no')

    # ------------------------------------------------------------------ PSE
    S.log('reading FAOSTAT and MONEVA')
    fao = support.fao_values(fao_zip, name_iso)
    mon = support.moneva(moneva_path)
    support_rows, booked_by, region_pse, pse_bad = support.pse(S, C, mon, fao, regions, pre)
    write_csv(S.out + '/support_s10.csv', ['region', 'basis', 'applies_to', 'sector', 'value_musd', 'rate', 'rate_on', 'source',
                                           'year', 'fill', 'price_basis'], support_rows)
    hard(S, 'S10-Hpse', 'Booked support equals MONEVA budgetary A2-E (PO+PIV+PIF+PIS+PC+PHR+PHNR) per region',
         K.pse_total(pse_bad), 0, Q_PSE)
    hard(S, 'S10-Husa-pse', 'USA MONEVA components match the handoff preview within 0.05 USD million',
         K.preview(region_pse.get('USA', {}), support.USA_PREVIEW, 0.05), 0, Q_PSE)
    S.flag('PSE-MPS-EXCLUDED', 'PSE', 'MPS, PN (F) and PM (G) are excluded. OECD aggregate rows are skipped.', 'no', C['pse_source'], Q_PSE)
    S.flag('PSE-EU-SPLIT', 'EU27', 'EU MONEVA is split by FAOSTAT 2022 item 2051 member output (ch.13D CAP Strategic Plans and State Aid Scoreboard not in dataset/data).',
           'no', C['pse_eu'], 'departure_logged')
    S.flag('D29-NOT-BOOKED', 'production taxes', 'OECD D29-D39 is not booked. Erratum E48.', 'no', C['production_taxes'], 'erratum E48')

    # ------------------------------------------------------------------ export subsidies
    S.log('export subsidies')
    sub_rows, booked_outlay, booked_xs = support.export_subsidies(S, C, wto_path, fx_path, subsidy_hs, tb.tot['exp_hs'], vxsb_sec,
                                                                  name_iso, region_set)
    write_csv(S.out + '/export_subsidy_s10.csv', ['region', 'sector', 'year', 'outlay_usd_million', 'vxsb_musd', 'xt_musd', 'rate',
                                                  'booked', 'base', 'fill', 'products', 'price_basis'], sub_rows)
    hard(S, 'S10-Hxsrate', "Each booked export-subsidy rate is at most 100 percent of that product's own exports",
         K.xs_rate(sub_rows), 0, Q_XS)
    # export taxes (fix list A2): cited 2022 totals spread over cited products, VFOB above VXSB
    xt_totals = export_tax.read_grs_totals(grs_xt_path)
    xt_products = export_tax.load_products()
    xt_tab = export_tax.load_rates() if C['export_tax_rates'].startswith('statutory_2022') else {}
    regions_single = {r for r in regions if region_type[r] == 'single'}
    if C['export_taxes_other'].startswith('grs_t5124'):
        xt_rates, xt_rows, xt_rep = export_tax.allocate(xt_totals, xt_products, tb.tot['exp_hs'], tb.nomen.sector, vxsb_sec,
                                                        regions_single, skip=set(xt_tab))
    else:
        xt_rates, xt_rows, xt_rep = {}, [], {'not_booked': ['export_taxes_other none_beyond_io: nothing booked']}
    # rates path (export_tax_rates): RUS, IND, CHN have no GRS T_5124 2022 value; statutory 2022 rates on FOB
    gfs_xt = export_tax.read_gfs_export_taxes(gfs_xt_path, wdi_fx_path)
    r_rates, r_rows, r_rep = export_tax.rates_booked(xt_tab, tb.tot['exp_hs'], tb.nomen.sector, vxsb_sec, regions_single, gfs_xt)
    xt_rates.update(r_rates)
    xt_rows += r_rows
    xt_rep['not_booked'] += r_rep['not_booked']
    # beta v4 G12: member routes of a customs union out of the duty base outside energy (S11 does coa, oil, gas, pet)
    xt_exempt = None
    if C['export_tax_union_exempt'] == export_tax.UNION_EXEMPT:
        union_path = S.inp(BUILD + '/config/s11/export_tax_exempt_routes.csv', 'customs-union export-duty exemptions (EAEU), shared with S11')
        xt_exempt, xt_ex = export_tax.union_exempt(xt_rates, xt_rows, vfob_rows, export_tax.load_union_routes(union_path),
                                                   export_tax.RATES_SOURCE)
        S.flag('EXPORT-TAX-UNION', 'export tax', 'No export duty on routes between EAEU members outside energy: '
               + ('; '.join(f'{e} {s_} {v:.1f} USD m of VFOB' for (e, s_), v in sorted(xt_ex.items(), key=lambda kv: -kv[1])[:40]) or 'none')
               + '. GRS-booked exporters (KAZ, ARM, KGZ) keep their total on the taxable VFOB; statutory-rate exporters (RUS) keep their rates.',
               'no', C['export_tax_union_exempt'], export_tax.Q_XTAX)
    write_csv(S.out + '/export_tax_s10.csv', ['exporter', 'sector', 'grs_total_musd', 'duty_musd', 'vfob_musd', 'rate', 'weight',
                                              'total_source', 'product_sources', 'price_basis'], xt_rows)
    xt_booked = sum(float(r[3]) for r in xt_rows)
    hard(S, 'S10-Hxtax', 'Each GRS-booked exporter adds up to its GRS T_5124 2022 total and has a cited product list; each '
         'rates-booked exporter is in export_tax_rates_2022.csv with duty = rate x VFOB; no exporter on both paths; each sector '
         'rate is in [0, 1) of VFOB', K.export_tax(xt_rows, xt_totals, xt_products, xt_tab, export_tax.RATES_SOURCE), 0,
         C['export_taxes_other'] + '; ' + C['export_tax_rates'])
    rev_txt = '; '.join(f'{iso} implied {imp:.1f} USD m' + (f' vs IMF GFS G1152 {pub:.1f} ({imp / pub:.2f})' if pub else
                                                             ' (no published 2022 total)')
                        for iso, imp, pub in r_rep['revenue'])
    S.check('S10-Rxtaxrev', 'Rates path: export tax implied at S10 VFOB against the published 2022 taxes on exports (IMF GFS '
            'G1152, general government, at the WDI 2022 rate). Report only: S11 re-prices coa, oil, gas and pet, so their '
            'duty moves with the S11 VFOB', 'report', len(r_rep['revenue']), 'n/a', True, C['export_tax_rates'], rev_txt)
    lines, wedge, tax_wedge = support.vfob_lines(vfob_rows, booked_outlay, vxsb_sec, xt_rates, xt_exempt)
    gz_write(S.out + '/vfob_s10.csv.gz', b'sector,exporter,importer,vxsb_musd,vfob_musd,export_subsidy_rate,export_tax_rate,price_basis\n',
             lines)
    hard(S, 'S10-Hvxsb', 'Derived basic-price exports minus FOB equal the booked export-subsidy outlay less the booked export tax',
         K.vxsb(wedge, booked_xs, tax_wedge, xt_booked), '0', C['vxsb_from_vfob'])
    S.flag('EXPORT-TAX', 'export tax', f'{len({r[0] for r in xt_rows})} exporters book {xt_booked / 1000:.3f} bn of 2022 export tax '
           f"(OECD GRS T_5124 totals, and statutory 2022 rates for {', '.join(sorted(xt_tab))}) on {len(xt_rows)} sector cells: "
           + '; '.join(f'{r[0]} {r[1]} {float(r[5]):.4f}' for r in xt_rows[:80])
           + '. Energy cells (coa, oil, gas, pet) are re-priced by S11, which must carry the rate.', 'no',
           C['export_taxes_other'] + '; ' + C['export_tax_rates'], export_tax.Q_XTAX)
    S.flag('EXPORT-TAX-RATES', 'export tax', 'Rates path (export_tax_rates_2022.csv; ad valorem on FOB, specific and formula duties as '
           'equivalents on the BACI 2022 unit value, part-year duties time-weighted, the same rate to every destination; '
           'Russian duties do not apply within the EAEU and India\'s fuel levy is an excise on exports): ' + rev_txt
           + '. CHN reports zero taxes on exports to IMF GFS (export duties sit in customs revenue); IND reports none for 2022.',
           'no', C['export_tax_rates'], export_tax.Q_XTAX)
    S.flag('EXPORT-TAX-NEEDS-SOURCE', 'export tax', 'Not booked: ' + ('; '.join(xt_rep['not_booked']) or 'none') + '.', 'no',
           C['export_tax_unlisted'], export_tax.Q_XTAX)

    # ------------------------------------------------------------------ income and factor taxes
    S.log('income and factor taxes')
    grs = tax_mod.read_grs(grs_path)
    T = tax_mod.Taxes(S, C, grs, tax_mod.read_world(imf_path), cm.region, gfs=tax_mod.read_gfs(gfs_tax_path))
    T.country_rates()
    S.flag('GFS-GENERAL-GOV', 'income/factor taxes', 'IMF GFS_SOO general government (S13, incl. social security funds) used where GRS '
           'has no value and WoRLD has central government only: ' + ('; '.join(f'{i} {k} {T.tax[(i, k)][0]:.4f} pct GDP ({T.tax[(i, k)][1]})'
                                                                       for i, k in sorted(set(T.gfs_used))) or 'none')
           + '. QAT, KWT, BHR and OMN have no GFS_SOO series and stay as before.', 'no', C['income_tax_source'], Q_TAX)
    hard(S, 'S10-Htaxsource', 'No average fill is used for a region and tax where GRS or WoRLD has a value',
         K.tax_source(T.average_used_where_source()), 0, Q_TAX)
    hard(S, 'S10-Husa-grs', 'USA 2022 GRS PIT, CIT, SSC, payroll and property match the registered extract',
         K.preview({k: (grs[('USA', k)][1] if grs.get(('USA', k), (0,))[0] == 2022 else None) for k in tax_mod.USA_GRS},
                   tax_mod.USA_GRS, 1e-4), 0, Q_TAX)
    tax_rows, tax_total = T.region_rows(regions, region_type, cm.members, gdp_iso, pre['gdp'])
    write_csv(S.out + '/factor_tax_rates_s10.csv', ['region', 'tax_class', 'applies_to', 'rate_pct_gdp', 'io_gdp_musd', 'value_musd',
                                                    'source', 'year', 'fill', 'price_basis'], tax_rows)
    S.flag('EMPLOYER-SSC-REPORT-ONLY', 'SSC', 'Total T_2000 goes to labour; employer shares are not used. Erratum E48.',
           'no', C['ssc'], Q_TAX)
    S.flag('TAX-BASE', 'io GDP', 'Tax values use pre-removal io GDP (VA + TLS on agents + TLS on stock_gap).', 'no', C['tax_values'], Q_TAX)
    S.flag('IMF-REFETCH', 'WoRLD', 'S10 uses the WoRLD refetch sha 2d5f24a9 (SDMX-CSV); the extract window is 2017-2022.',
           'no', C['income_tax_source'], Q_TAX)
    cited = {(a['region'], a['item']) for a in S.ledger if a['flag'] == 'cited'}
    neg_rows = [(r[0], 'PSE ' + r[1] if r[1] != 'pc_residual' else 'PSE pc_residual', float(r[4])) for r in support_rows]
    neg_rows += [(r[0], 'export subsidy ' + (r[10] if r[10] != '(blank)' else r[1]), float(r[3])) for r in sub_rows if r[7] == 'yes']
    neg_rows += [(r[0], r[1], float(r[5])) for r in tax_rows]
    hard(S, 'S10-Hnegtax', 'No new negative tax without a cited subsidy, and no new negative TLS cell',
         K.negatives(io_stats['new_neg_tls'], neg_rows, cited), 0, Q_SIGN)
    within = compared = 0
    usa_prod = ''
    for region in regions:
        g = grs.get((region, 'T_5000'))
        if not g:
            continue
        customs_tax = grs.get((region, 'T_5123'))
        target = g[1] - (customs_tax[1] if customs_tax else 0.0)
        compared += 1
        tls_sum = sum(new_tls[region][c] for c in table.agents) + new_tls[region]['stock_gap']
        ratio = 100.0 * tls_sum / pre['gdp'][region] if pre['gdp'][region] else 0.0
        within += target == 0 or abs(ratio - target) / abs(target) <= 0.10
        if region == 'USA':
            usa_prod = f'USA remaining TLS {ratio:.4f} percent of GDP; GRS T_5000 {g[1]:.4f} minus T_5123 {customs_tax[1] if customs_tax else 0:.4f}'
    S.check('S10-Rproduct', 'Remaining TLS versus GRS T_5000 minus customs duties T_5123', 'report', f'{within} of {compared} within 10 percent',
            'report', True, Q_TLS, usa_prod)
    S.check('S10-Rvat', 'GRS T_5111 and T_5121 shape the commodity structure of the non-energy TLS only (product_tax_pattern); no total moves', 'report',
            f"USA T_5111 {grs.get(('USA', 'T_5111'))}; USA T_5121 {grs.get(('USA', 'T_5121'))}", 'pattern only', True,
            'erratum E48; ' + product_tax.Q_PATTERN, '')

    # ------------------------------------------------------------------ commodity structure of the non-energy TLS (QA round 2 P1)
    if C['product_tax_pattern'] != 'none':
        S.log('product-tax layers by commodity (VAT schedule, GRS VAT and excise, Eurostat product control)')
        vat = product_tax.read_vat(vat_path, BASE_YEAR)
        pt_rows, pt_used = product_tax.pattern_rows(regions, region_type, short_to_icio, vat)
        write_csv(S.out + '/product_tax_pattern_s10.csv', product_tax.PATTERN_COLUMNS, pt_rows)
        lay_rows = product_tax.layer_rows(regions, cm.members, gdp_iso, pre['gdp'], grs, product_tax.energy_excise(energy_rows))
        write_csv(S.out + '/product_tax_layers_s10.csv', product_tax.LAYER_COLUMNS, lay_rows)
        eu_ctl, eu_neg = (product_tax.control_rows(set(regions), region_type, product_tax.read_eurostat(eurostat_pt_path, BASE_YEAR))
                          if eurostat_pt_path else ([], []))
        write_csv(S.out + '/product_tax_control_s10.csv', product_tax.CONTROL_COLUMNS, eu_ctl)
        hard(S, 'S10-Hptpattern', 'product_tax_pattern: every region has a VAT weight in [0, 1] for each agent and commodity, the generic schedule '
             'puts 0 on the exempt and non-market services, the GRS layers are finite and non-negative, and the Eurostat control shares '
             'sum to 1 per region', K.product_tax(pt_rows, lay_rows, eu_ctl, regions, len(product_tax.AGENTS) * len(short_to_icio)), 0,
             C['product_tax_pattern'])
        n_stat = sum(1 for v in pt_used.values() if v == 'statutory')
        S.flag('PRODUCT-TAX-PATTERN', 'TLS', f'Non-energy TLS by commodity: {n_stat} regions on their statutory VAT schedule, {len(regions) - n_stat} '
               f"on the generic exemptions; {len({r[0] for r in eu_ctl})} regions with a Eurostat product control. Negative Eurostat groups "
               f"(product subsidies; zero in the control): {'; '.join(eu_neg) or 'none'}. S13 scales the layers to each column TLS.",
               'no', C['product_tax_pattern'], product_tax.Q_PATTERN)

    # ------------------------------------------------------------------ customs, Census and USA
    census_tot, census_ch = reports.census(census_path)
    ch_rows, far, china_only = reports.usa_chapters(acc.usa_ch, census_ch)
    write_csv(S.out + '/usa_chapter_s10.csv', ['chapter', 'booked_duty_bn', 'booked_fob_bn', 'booked_ex_china_duty_bn',
                                               'booked_ex_china_fob_bn', 'census_duty_bn', 'census_ex_china_duty_bn', 'ratio_ex_china',
                                               'gap_ex_china_bn', 'class', 'reason'], ch_rows)
    hard(S, 'S10-Huschapter', 'USA chapter duty, ex-China, is not far from Census without a named reason', K.usa_far(far), 0,
         C['usa_chapter_far'])
    census_duty_m = census_tot['cal'] / 1e6
    customs, causes = reports.customs_rows(customs_path, tb.duty_region, region_set, cm.region, census_duty_m)
    write_csv(S.out + '/customs_compare_s10.csv', ['iso', 'collected_million_usd', 'source', 'booked_duty_musd', 'booked_over_collected',
                                                   'region', 'cause', 'price_basis', 'census_million_usd'], customs)
    S.check('S10-Rcustoms', 'Customs collections are report-only, with a cause on every row (GTAP 12 builds import duties from applied tariff rates times trade, not from collected revenue, which is net of unused preferences, exemptions and drawback; Fable QA E-04)', 'report', f'{len(customs)} rows',
            f'{N_CUSTOMS_ROWS} rows; no scaling', len(customs) == N_CUSTOMS_ROWS, 'erratum E3',
            '; '.join(f'{k} ({v})' for k, v in sorted(causes.items())))
    usa_vcif = sum(vcif[k] for k in tb.rate if k[0] == 'USA')
    usa_duty = tb.duty_region['USA']
    chn_duty = sum(tb.duty_cell[k][0] for k in tb.rate if k[0] == 'USA' and k[1] == 'CHN')
    chn_vcif = sum(vcif[k] for k in tb.rate if k[0] == 'USA' and k[1] == 'CHN')
    baci_duty = sum(s[0] for s in acc.usa_ch.values()) / 1000.0
    baci_base = sum(s[1] for s in acc.usa_ch.values()) / 1000.0
    con_m, chn_cal_m, chn_con_m = census_tot['con'] / 1e6, census_tot['chn_cal'] / 1e6, census_tot['chn_con'] / 1e6
    rate_s10 = usa_duty / usa_vcif if usa_vcif else 0.0
    rate_census = census_duty_m / con_m if con_m else 0.0
    base_gap = usa_vcif / con_m - 1.0 if con_m else 0.0
    sc = tb.scenario
    usa_rows = [
        ['booked_duty_rate_x_vcif', fnum(usa_duty), 'USD million', 'cif', 'S10 tm times S07+S08 VCIF. Not scaled.'],
        ['vcif', fnum(usa_vcif), 'USD million', 'cif', 'S07R VFOB plus S08 VTWR.'],
        ['booked_duty_line_rate_x_baci', fnum(baci_duty), 'USD million', 'baci fob', 'HS6 line rates on BACI 2022 USA imports with a rate.'],
        ['baci_imports', fnum(baci_base), 'USD million', 'baci fob', 'Goods HS lines, importer USA.'],
        ['census_calculated_duty', fnum(census_duty_m), 'USD million', 'census calculated duty', 'IMDB CY2022 cal_dut.'],
        ['census_customs_value', fnum(con_m), 'USD million', 'census customs value', 'IMDB CY2022 con_val.'],
        ['usitc_duty', fnum(reports.USITC_BN * 1000.0), 'USD million', 'cited', 'Handoff section 7. Not recomputed.'],
        ['ratio_booked_to_census', fnum(usa_duty / census_duty_m), 'ratio', 'rate and base together', ''],
        ['base_gap', fnum(base_gap), 'fraction', 'S07+S08 versus Census customs value', 'Not scaled.'],
        ['effective_rate_on_vcif', fnum(rate_s10), 'rate', '', ''],
        ['effective_rate_census', fnum(rate_census), 'rate', '', ''],
        ['rate_effect_musd', fnum((rate_s10 - rate_census) * usa_vcif), 'USD million', 'rate gap times VCIF', ''],
        ['base_effect_musd', fnum(rate_census * (usa_vcif - con_m)), 'USD million', 'Census rate times the VCIF gap', 'S07 owns the base.'],
        ['china_booked_duty', fnum(chn_duty), 'USD million', 'cif', 'Baseline tm excludes Section 301.'],
        ['china_vcif', fnum(chn_vcif), 'USD million', 'cif', ''],
        ['china_census_duty', fnum(chn_cal_m), 'USD million', 'census', 'cty 5700.'],
        ['china_census_customs', fnum(chn_con_m), 'USD million', 'census customs value', ''],
        ['us_gap_ex_china_musd', fnum((usa_duty - chn_duty) - (census_duty_m - chn_cal_m)), 'USD million', '', ''],
        ['removal_vs_0626bda_musd', fnum(usa_duty - PRIOR_USA_WITH_REMEDIES_MUSD), 'USD million', 'cif', '301/232 were inside tm then.'],
        ['china_removal_vs_0626bda_musd', fnum(chn_duty - PRIOR_CHINA_WITH_REMEDIES_MUSD), 'USD million', 'cif', ''],
        ['world_removal_vs_0626bda_bn', fnum(tb.world_duty / 1000.0 - PRIOR_WORLD_WITH_REMEDIES_BN), 'USD billion', 'cif', ''],
        ['scenario_301_implied_duty', fnum(sc['301']), 'USD million', 'cif', 'Scenario file only.'],
        ['scenario_232_implied_duty', fnum(sc['232']), 'USD million', 'cif', 'Scenario file only.'],
        ['scenario_china_implied_duty', fnum(sc['china']), 'USD million', 'cif', 'Scenario file only.'],
        ['usa_pse_a2e', fnum(booked_by.get('USA', 0.0)), 'USD million', 'budgetary', ''],
        ['pri_vir', 'inside USA', '', 'S01', 'No own schedule; left out of the weight.'],
    ]
    write_csv(S.out + '/usa_tariffs_s10.csv', ['metric', 'value', 'unit', 'price_basis', 'note'], usa_rows)
    S.check('S10-Rusa', 'USA duty against Census and USITC, split into base and rate', 'report',
            f'booked {usa_duty / 1000:.3f} bn; VCIF {usa_vcif / 1000:.3f} bn; Census {census_duty_m / 1000:.3f} bn; base gap {base_gap:.3%}',
            'no scaling', True, C['us_duty_benchmark'],
            f'China booked {chn_duty / 1000:.3f} bn vs Census {chn_cal_m / 1000:.3f} bn. Scenario 301 {sc["301"] / 1000:.3f} bn, '
            f'232 {sc["232"] / 1000:.3f} bn, not in tm. China-only far chapters: {", ".join(f"{c:02d}" for c in china_only) or "none"}.')
    brief['usa'] = {'duty': usa_duty, 'vcif': usa_vcif, 'census_duty': census_duty_m, 'china_duty': chn_duty,
                    'china_census': chn_cal_m, 'base_gap': base_gap}
    service_usa = tb.tot['service'].get('USA', 0.0)
    write_csv(S.out + '/service_hs6_s10.csv', ['scope', 'value_thousand_usd', 'note', 'price_basis'], [
        ['world_baci_hs_outside_goods', fnum(sum(tb.tot['service'].values())), 'HS lines mapping outside the 32 goods', 'baci thousand USD'],
        ['usa_region_baci_hs_outside_goods', fnum(service_usa), 'importer maps to USA', 'baci thousand USD'],
        ['usa_301_232_lines_outside_goods', fnum(tb.addon.outside[1]), f'BACI lines {tb.addon.outside[0]}', 'baci thousand USD'],
    ])
    S.check('S10-Rservices', 'Value of HS lines that map outside the 32 merchandise sectors', 'report',
            f"world {sum(tb.tot['service'].values()) / 1e6:.3f} bn; USA {service_usa / 1e6:.3f} bn", 'reported, tm = 0', True, Q_TARIFF, '')

    # ------------------------------------------------------------------ headlines
    brief['world'] = {'duty': tb.world_duty, 'vcif': tb.world_vcif, 'xs': booked_xs, 'pse': sum(booked_by.values()),
                      'pit': tax_total['pit'], 'cit': tax_total['cit'], 'ssc': tax_total['ssc'], 'pay': tax_total['payroll_property']}
    w = brief['world']
    S.check('S10-Rhead', 'Headline totals', 'report',
            f"duty {w['duty'] / 1000:.3f} bn; export subsidies {w['xs'] / 1000:.3f} bn; farm support {w['pse'] / 1000:.3f} bn; "
            f"PIT {w['pit'] / 1000:.3f}; CIT {w['cit'] / 1000:.3f}; SSC {w['ssc'] / 1000:.3f}; payroll+property {w['pay'] / 1000:.3f} bn",
            'report', True, Q_POWER, 'USD billion.')

    # ------------------------------------------------------------------ screens (reports outside output/)
    import screens.s10_suite as suite
    try:
        result = suite.run({'build': tb, 'duty_region': tb.duty_region, 'customs_rows': customs, 'census_usa_musd': census_duty_m,
                            'prev_duty': prev_duty(prev_dir), 'mfn_ave_zip': P['mfn_ave_bulk']}, log=S.log)
    except Exception as exc:
        result = {'error': f'{type(exc).__name__}: {exc}'}
        S.log('screens ERROR\n' + traceback.format_exc())
    hard(S, 'S10-Hscreens', 'Population screens fail when a material hit is unexplained or the screen run raises',
         K.screens(result), 0, C['screen_hard_check'])

    # ------------------------------------------------------------------ registry, privacy, licensing
    write_csv(S.out + '/price_basis_s10.csv', ['file', 'column', 'price_basis', 'note'], BASIS_ROWS)
    present = sorted(fn for fn in os.listdir(S.out) if fn not in ('SHA256SUMS', 'NOT_FOR_PUBLICATION.md'))
    hard(S, 'S10-Hbasis', 'Every output file has a price-basis tag', K.listed(present, {r[0] for r in BASIS_ROWS}, 'a price-basis tag'),
         0, Q_POWER)
    public = [f for f in present if f not in PRIVATE_OUTPUTS]
    notice = ['# NOT FOR PUBLICATION', '', 'Private repository only. These files are derived from WITS/TRAINS or from customs collections.',
              'Do not publish them. Decision of David, 2026-10-21.', '', 'TRAINS-derived or customs-derived files in this output directory:', '']
    notice += [f'- `{n}`' for n in PRIVATE_OUTPUTS]
    notice += ['', 'The stage `checks.md`, `checks.json`, `adjustments_ledger.csv`, `flags.csv`, `REVIEW_BRIEF.md` and `build.log` quote duty '
               'levels and are not for publication. So are the S10 screen reports in `dataset/reviews/screens/S10/`.', '',
               'Public in this directory: ' + ', '.join(f'`{f}`' for f in public + ['SHA256SUMS']) + '.', '']
    open(S.out + '/NOT_FOR_PUBLICATION.md', 'w').write('\n'.join(notice))
    listed_text = open(S.out + '/NOT_FOR_PUBLICATION.md').read()
    hard(S, 'S10-Hprivate', 'Every TRAINS-derived output exists and is listed in NOT_FOR_PUBLICATION.md',
         K.listed(PRIVATE_OUTPUTS, {n for n in PRIVATE_OUTPUTS if f'`{n}`' in listed_text and os.path.exists(S.out + '/' + n)},
                  'a listing'), 0, C['trains_outputs'])
    tracked = subprocess.run(['git', '-C', repo_top, 'ls-files'], capture_output=True, text=True).stdout.splitlines()
    private = private_paths(tracked)
    S.check('S10-Hlic', 'No private file (credentials, licensed GTAP database values) is tracked in git. Rule: config/repo_rules.csv '
            'committed_data_rule (David 2026-10-23)', 'hard', len(private), 0, not private, 'config/repo_rules.csv private_path_patterns',
            ' '.join(private[:20]))
    hits = secret_hits([S.out, S.dir + '/build.log', BUILD + '/s10_tariffs_taxes.py', BUILD + '/s10_tariffs',
                        BUILD + '/screens/s10_suite.py'])
    S.check('S10-Hsecret', 'Password and api_key assignment scan of the stage code and outputs', 'hard', len(hits), 0, not hits,
            'licensing', ' '.join(hits))

    # ------------------------------------------------------------------ two-run check and the previous output pin
    mine = output_sums_text(S.out)
    other_path = os.environ.get('S10_R6_SHA256SUMS', '').strip()
    if other_path and os.path.exists(other_path):
        other = open(other_path).read()
        r6 = (f'match {mine == other}; this {hashlib.sha256(mine.encode()).hexdigest()}', mine == other,
              'this run\n' + mine + 'other run\n' + other)
    else:
        r6 = (f'this {hashlib.sha256(mine.encode()).hexdigest()}; other run not supplied', False,
              'Set S10_R6_SHA256SUMS to a second run.\n' + mine)
    brief['r6'] = r6[0]
    S.check('S10-R6', 'Two runs write the same output SHA256SUMS', 'report', r6[0], 'the two SHA256SUMS match', r6[1], 'GTAP_STAGES_DIR', r6[2])
    sums_path = os.path.join(prev_dir, 'SHA256SUMS') if prev_dir else ''
    prev_sha = sha256(sums_path) if sums_path and os.path.exists(sums_path) else ''
    if prev_sha:
        S.log(f'previous output SHA256SUMS sha256 {prev_sha} commit {PREV_OUTPUT_COMMITS.get(prev_sha, "")} pin {prev_dir}')
    if not S.finish():
        return
    if prev_sha and os.path.exists(S.dir + '/STAMP'):
        lines = [f'previous output SHA256SUMS sha256 {prev_sha}', f'S10_PREV_OUTPUT {prev_dir}']
        if PREV_OUTPUT_COMMITS.get(prev_sha):
            lines.insert(1, f'previous output commit {PREV_OUTPUT_COMMITS[prev_sha]}')
        with open(S.dir + '/STAMP', 'a') as fh:
            fh.write('\n'.join(lines) + '\n')


def write_notes(S, brief):
    open(S.dir + '/NEEDS_DAVID.md', 'w').write('# NEEDS_DAVID\n\nNone.\n')
    md = ['# S10 review brief', '',
          'Protection, domestic support and income and factor taxes. Every choice is the value in '
          '`dataset/build/config/s10/s10_choices.csv`. The method is in `dataset/build/s10_tariffs/`.', '',
          f'Bound S09 snapshot commit `{S09_STAMP_COMMIT}`, STAMP {S09_STAMP_TIME}, output SHA256SUMS `{S09_SUMS}`.', '',
          '## Choices', '', '| choice | value | decided_by | decided_at | gtap_status |', '|---|---|---|---|---|']
    for row in brief.get('choices') or []:
        md.append(f'| {row["choice"]} | `{row["value"]}` | {row["decided_by"]} | {row["decided_at"]} | {row["gtap_status"]} |')
    md += ['', '## Hard checks', '', '| ID | Status | Value |', '|---|---|---|']
    md += [f'| {c["id"]} | {c["status"]} | {c["value"]} |' for c in S.checks if c['kind'] == 'hard']
    md += ['', '## Report checks', '']
    for c in S.checks:
        if c['kind'] == 'report':
            md += [f'### {c["id"]} {c["status"]}', '', c['description'], '', f'Value: {c["value"]}', '', c.get('detail') or '', '']
    w = brief.get('world') or {}
    if w:
        md += ['## Headlines (USD billion)', '', f'- Tariff revenue {w["duty"] / 1000:.3f}', f'- Export subsidies booked {w["xs"] / 1000:.3f}',
               f'- Farm support A2-E {w["pse"] / 1000:.3f}',
               f'- PIT {w["pit"] / 1000:.3f}; CIT {w["cit"] / 1000:.3f}; SSC {w["ssc"] / 1000:.3f}; payroll and property {w["pay"] / 1000:.3f}', '']
    u = brief.get('usa') or {}
    if u:
        md += ['## USA', '', f'- Booked duty {u["duty"] / 1000:.3f} bn on VCIF {u["vcif"] / 1000:.3f} bn; Census {u["census_duty"] / 1000:.3f} bn; '
               f'base gap {u["base_gap"]:.1%}. Not scaled.',
               f'- China booked {u["china_duty"] / 1000:.3f} bn vs Census {u["china_census"] / 1000:.3f} bn. Section 301 is not in tm.', '']
    counts = defaultdict(int)
    for fl in S.flags:
        counts[fl['id']] += 1
    md += ['## Flags', ''] + [f'- `{fid}`: {n}' for fid, n in sorted(counts.items())]
    md += ['', '## Two-run SHA256SUMS', '', brief.get('r6', 'not run'), '']
    if os.path.exists(S.dir + '/STAMP'):
        md += ['## STAMP', '', '```', open(S.dir + '/STAMP').read().rstrip(), '```', '']
    open(S.dir + '/REVIEW_BRIEF.md', 'w').write('\n'.join(md) + '\n')


def main():
    brief = {}
    stage = None
    try:
        stage = Stage('S10', 'tariffs_taxes')
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
