"""S14 configuration, read strictly (the S11 and S13 pattern).

Every row of config/s14/s14_choices.csv must be a choice this code knows, with the value the code
implements, a decided_by and a decided_at; every choice the code knows must be in the file. A config
table that is missing, empty or lacks a column stops the build. There is no fallback copy of any file.
"""
import csv
import os

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BUILD, 'config', 's14')
CHOICES_PATH = os.path.join(CONFIG_DIR, 's14_choices.csv')
CHOICE_COLUMNS = ('choice', 'value', 'decided_by', 'decided_at', 'basis', 'gtap_status')
GTAP_STATUS = {'gtap', 'gtap_rule', 'not_in_gtap_text', 'departure_logged', 'n/a'}

# choice -> the values this code implements (the first is the default; a choice with two values is a switch)
CHOICES = {
    'layout': ('gtapv7_31_headers_long_csv_nonzero_rows',),
    'trade_merge': ('bilateral_s10_goods_s11_energy_s09_services_and_travel_as_held_in_s13',),
    'vtwr': ('s08_goods_s11_energy_by_route',),
    'capital': ('s02_vkb_vdep_pop',),
    'save': ('gtap_residual_income_less_c_less_g_net_of_depreciation',),
    'purchaser_split': ('s13_cell_rates_dom_and_imp_same_remainder_holds_column_tax', 'one_tax_power_per_column_dom_and_imp_from_s13'),
    'make_matrix': ('diagonal_makb_output_maks_output_less_output_tax',),
    'rebalance': ('rounding_only_cif_vst_imports_output_and_output_tax_bound_1e-3_musd',),
    'negative_save': ('report_only_gtap_residual', 'hard_save_positive'),
    'saving_share_gate': ('report_carry_save_to_aggregation_maps', 'hard_per_region'),
    'vdep_gate': ('report_only_carry_vdep',),
    'precision': ('csv_12_significant_digits',),
    'small_trade': ('zero_vxsb_routes_and_vtwr_cells_below_1e-6_musd', 'keep_all'),
    'one_sided_seed': ('seed_1e-4_of_imports_cost_from_supplying_columns', 'none'),
    'capital_floor': ('seed_at_least_1e-5_musd_and_capital_at_least_1e-6_musd_or_half_of_va', 'off'),
    'natres_final': ('gtap_ch12a_target_elasticity_on_s14_data_labour_capital_pro_rata', 'as_s13_s12_prior_shares'),
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
