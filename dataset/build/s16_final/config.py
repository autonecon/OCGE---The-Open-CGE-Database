"""S16 configuration, read strictly (the S15 pattern).

Every row of config/s16/s16_choices.csv must be a choice this code knows, with the value the code implements,
a decided_by and a decided_at; every choice the code knows must be in the file. The map suite
(config/s16/maps.csv), the sector schemes (config/s16/sector_schemes.csv) and the ledger rule list
(config/s16/ledger_rules.csv: every rule a stage ledger may carry, kind method or absorbed) must exist with their columns.
"""
import csv
import os

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BUILD, 'config', 's16')
CHOICES_PATH = os.path.join(CONFIG_DIR, 's16_choices.csv')
CHOICE_COLUMNS = ('choice', 'value', 'decided_by', 'decided_at', 'basis', 'gtap_status')
GTAP_STATUS = {'gtap', 'gtap_rule', 'not_in_gtap_text', 'departure_logged', 'n/a'}
TABLES = {
    'maps': ('maps.csv', ('map', 'kind', 'regions', 'schemes', 'tariff_shock', 'purpose')),
    'schemes': ('sector_schemes.csv', ('sector', 's7_smoke', 's6', 's4', 's7_nocrude', 's24')),
    'route_blocks': ('route_blocks.csv', ('good', 'src', 'dst', 'decided_by', 'decided_at', 'basis')),
    'ledger_rules': ('ledger_rules.csv', ('stage', 'rule', 'kind', 'note')),
    'gate_exceptions': ('map_gate_exceptions.csv', ('map', 'group', 'measure', 'limit', 'decided_by', 'decided_at', 'basis')),
    'map_exceptions': ('map_failure_exceptions.csv', ('map', 'error', 'decided_by', 'decided_at', 'basis')),
}

RELEASE_GATES = 'builder_explanations_before_2026_10_26_void_stale_waivers_fail_release_run_recorded_hard_at_release'
SCREEN_CUTOFF = '2026-10-26'      # beta v5 RG: explanations written before beta v3 and v4 (most on 23 Oct, before beta v2) are void
BETAV5_REPORTS = 'macro_bn_goods_services_sector_size_ama_power_price_energy_wedge_metal_exports_filled_and_blocked_routes_version_diff'
CHOICES = {
    'check_table': ('plan_3k_full_table_on_s15_har',),
    'data_read': ('harpy_float32_read_back',),
    'stage_rollup': ('every_stamp_bound_chained_no_hard_fail',),
    'map_suite': ('closure_maps_isolating_maps_and_large_20', 'closure_maps_and_isolating_maps', 'smoke_and_isolating_maps'),
    'one_sided_pairs': ('scheme_ladder_pool_primary_fuels', 'upstream_fix_first'),
    'model_run_prep': ('in_memory_armington_swap',),
    'homogeneity': ('numeraire_x1.1_psave_against_package_e_psave',),
    'saving_share_maps': ('hard_on_each_map',),
    'neg_save': ('report_only',),
    'vdep_vs_i': ('report_only_carry_vdep',),
    'customs_collected': ('report_only_with_cause',),
    'gtap_benchmark': ('gtap10_shares_outside_git', 'not_run'),
    # beta v5 RG (David 2026-10-27, package v2): at release (GTAP_RELEASE=1) builder screen explanations dated before the
    # cutoff are void, stale waivers fail, and S16-Hrelease records the release run; tools/release_gate.py reads them
    'release_gates': (RELEASE_GATES, 'off'),
    # beta v5 TC (David 2026-10-27, package v2): the report checks of s16_final/betav5.py
    'betav5_report_checks': (BETAV5_REPORTS, 'off'),
}


class ConfigError(SystemExit):
    pass


def load_choices(path=CHOICES_PATH):
    """Return {choice: row}. Raise ConfigError on any missing, unknown, mis-valued or unattributed row."""
    if not os.path.exists(path):
        raise ConfigError(f'{path} is missing')
    with open(path, newline='') as fh:
        rd = csv.DictReader(fh)
        if tuple(rd.fieldnames or ()) != CHOICE_COLUMNS:
            raise ConfigError(f'{path}: columns {rd.fieldnames} are not {CHOICE_COLUMNS}')
        rows = list(rd)
    seen, bad = {}, []
    for r in rows:
        c = r['choice']
        if c in seen:
            bad.append(f'{c}: duplicate row')
        seen[c] = r
        if c not in CHOICES:
            bad.append(f'{c}: not a choice this code knows')
            continue
        if r['value'] not in CHOICES[c]:
            bad.append(f'{c}: value {r["value"]!r} is not one of the implemented {CHOICES[c]}')
        if not r['decided_by'].strip() or not r['decided_at'].strip():
            bad.append(f'{c}: decided_by or decided_at is blank')
        if r['gtap_status'] not in GTAP_STATUS:
            bad.append(f'{c}: gtap_status {r["gtap_status"]!r}')
    bad += [f'{c}: row missing' for c in CHOICES if c not in seen]
    if bad:
        raise ConfigError(f'{path}: ' + '; '.join(bad))
    return seen


def table_path(key):
    return os.path.join(CONFIG_DIR, TABLES[key][0])


def load_table(key):
    import pandas as pd
    p = table_path(key)
    if not os.path.exists(p):
        raise ConfigError(f'{p} is missing')
    df = pd.read_csv(p, keep_default_na=False)
    if tuple(df.columns) != TABLES[key][1]:
        raise ConfigError(f'{p}: columns {tuple(df.columns)} are not {TABLES[key][1]}')
    if df.empty:
        raise ConfigError(f'{p} is empty')
    return df
