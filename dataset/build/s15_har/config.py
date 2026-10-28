"""S15 configuration, read strictly (the S14 pattern).

Every row of config/s15/s15_choices.csv must be a choice this code knows, with the value the code implements,
a decided_by and a decided_at; every choice the code knows must be in the file. The parameter tables of both
editions (GTAP 12 ch.16, the default: gtap12_table16_2.csv, sector_gtap12.csv, cde_targets_gtap12.csv,
cde_target_rows_gtap12.csv; GTAP 7 ch.14, the alternative: gtap7_table14_2.csv, sector_gtap7.csv,
cde_targets_gtap7.csv, cde_target_rows.csv), s15_scalars.csv and the smoke map (maps/smoke_11x7_*.csv) must exist
with their columns. The choices parameters, cde_targets and sector_means must name the same edition. There is no
fallback copy of any file.
"""
import csv
import os

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BUILD, 'config', 's15')
CHOICES_PATH = os.path.join(CONFIG_DIR, 's15_choices.csv')
CHOICE_COLUMNS = ('choice', 'value', 'decided_by', 'decided_at', 'basis', 'gtap_status')
GTAP_STATUS = {'gtap', 'gtap_rule', 'not_in_gtap_text', 'departure_logged', 'n/a'}
TABLES = {
    'table16_2': ('gtap12_table16_2.csv', ('gtap12', 'name', 'esubd', 'esubm', 'esubva', 'cde_category', 'source')),
    'sector_map_gtap12': ('sector_gtap12.csv', ('sector', 'gtap12_members', 'cde_category', 'note')),
    'cde_targets_gtap12': ('cde_targets_gtap12.csv', ('gtap12_region', 'category', 'income_elasticity', 'compensated_own_price_magnitude', 'source')),
    'cde_rows_gtap12': ('cde_target_rows_gtap12.csv', ('region', 'target_row', 'note')),
    'table14_2': ('gtap7_table14_2.csv', ('gtap7', 'name', 'esubd', 'esubm', 'esubva', 'cde_category', 'source')),
    'sector_map': ('sector_gtap7.csv', ('sector', 'gtap7_members', 'cde_category', 'note')),
    'cde_targets': ('cde_targets_gtap7.csv', ('gtap7_region', 'category', 'income_elasticity', 'uncompensated_own_price_magnitude', 'source')),
    'cde_rows': ('cde_target_rows.csv', ('region', 'target_row', 'note')),
    'scalars': ('s15_scalars.csv', ('parameter', 'element', 'value', 'basis')),
    'smoke_regions': ('maps/smoke_11x7_regions.csv', ('region', 'group')),
    'smoke_sectors': ('maps/smoke_11x7_sectors.csv', ('sector', 'group')),
}

CHOICES = {
    'layout': ('gtapv7_har_three_files_sets_par_dat',),
    'precision': ('har_float32_jls_float64',),
    'jls': ('dict_of_sets_data_parameters_gzip',),
    'set_case': ('lowercase_elements',),
    'parameters': ('gtap12_ch16_standard', 'gtap7_ch14_standard'),
    'cde_targets': ('gtap12_tables_16_6_16_7_by_region', 'gtap7_tables_14_5_14_6_by_region'),
    'cde_fit': ('exact_then_sequential',),
    'sector_means': ('unweighted_mean_of_gtap12_members', 'unweighted_mean_of_gtap7_members'),
    'natres_mobility': ('fixed_by_sector',),
    'model_check': ('julia_headerarrayfile_load_and_smoke_map_solve',),
    'saving_share_maps': ('hard_on_each_map',),
    'model_run_prep': ('in_memory_armington_swap',),
    'cde_price_reading': ('table_16_7_compensated_as_titled', 'table_14_6_as_compensated'),
    'incp_floor': ('1e-6_after_normalisation',),
    # beta v4 P10 (David's call; 'off' is the default)
    'household_crude_seed': ('off', 'seed_1e-7_of_household_spending_on_crude_zero_tax_offset_by_refinery_crude_and_household_refined_product'),
    # beta v4 rescan (S16 2026-10-26): with the seed on, a near-zero fit residue is topped up to the seed share too
    'household_crude_top_up': ('household_crude_below_the_seed_share_topped_up_to_it_no_near_zero_cells', 'off'),
}
HOUSEHOLD_CRUDE_TOP_UP = 'household_crude_below_the_seed_share_topped_up_to_it_no_near_zero_cells'
HOUSEHOLD_CRUDE_SEED = 'seed_1e-7_of_household_spending_on_crude_zero_tax_offset_by_refinery_crude_and_household_refined_product'


# The two parameter editions. GTAP 12 ch.16 is the default (David 2026-10-24, "stick to GTAP"; QA finding #7);
# GTAP 7 ch.14 stays as the alternative. Each edition names its tables, its column names and its choice values.
EDITIONS = {
    'gtap12_ch16_standard': dict(
        label='GTAP 12 ch.16', table='table16_2', sector_map='sector_map_gtap12', targets='cde_targets_gtap12',
        rows='cde_rows_gtap12', code_col='gtap12', members_col='gtap12_members', region_col='gtap12_region',
        own_col='compensated_own_price_magnitude', cde_targets='gtap12_tables_16_6_16_7_by_region',
        sector_means='unweighted_mean_of_gtap12_members', cde_price_reading='table_16_7_compensated_as_titled',
        aliases={'PSE': 'PAL'}),
    'gtap7_ch14_standard': dict(
        label='GTAP 7 ch.14', table='table14_2', sector_map='sector_map', targets='cde_targets', rows='cde_rows',
        code_col='gtap7', members_col='gtap7_members', region_col='gtap7_region',
        own_col='uncompensated_own_price_magnitude', cde_targets='gtap7_tables_14_5_14_6_by_region',
        sector_means='unweighted_mean_of_gtap7_members', cde_price_reading='table_14_6_as_compensated',
        aliases={'ROA': 'ROU'}),
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
    ed = EDITIONS.get(seen.get('parameters', {}).get('value'))
    if ed:
        for c in ('cde_targets', 'sector_means', 'cde_price_reading'):
            if c in seen and seen[c]['value'] != ed[c]:
                bad.append(f'{c}: value {seen[c]["value"]!r} belongs to another edition than parameters ({ed[c]!r} expected)')
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


def edition_tables(choices, T):
    """The parameter tables of the chosen edition with common column names: table (code, esubd, esubm, esubva,
    cde_category), sector map (sector, members, cde_category), targets (target_region, category,
    income_elasticity, own_price_magnitude) and target rows (region, target_row, note); plus the edition dict."""
    ed = EDITIONS[choices['parameters']['value']]
    table = T[ed['table']].rename(columns={ed['code_col']: 'code'})
    smap = T[ed['sector_map']].rename(columns={ed['members_col']: 'members'})
    targets = T[ed['targets']].rename(columns={ed['region_col']: 'target_region', ed['own_col']: 'own_price_magnitude'})
    return ed, table, smap, targets, T[ed['rows']]
