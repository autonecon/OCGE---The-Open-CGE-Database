"""S12 configuration, read strictly (the S11 pattern).

Every row of config/s12/s12_choices.csv must be a choice this code knows, with the value the code
implements, a decided_by and a decided_at; every choice the code knows must be in the file. A config
table that is missing, empty or lacks a column stops the build. There is no fallback copy of any file.
"""
import csv
import os

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BUILD, 'config', 's12')
CHOICES_PATH = os.path.join(CONFIG_DIR, 's12_choices.csv')
CHOICE_COLUMNS = ('choice', 'value', 'decided_by', 'decided_at', 'basis', 'gtap_status')
NATRES_TARGETS_PATH = os.path.join(CONFIG_DIR, 'natres_targets.csv')
NATRES_TARGET_COLUMNS = ('sector', 'gtap_sector', 'target_class', 'eta_target', 'sigma_va', 'source', 'decided_by', 'decided_at')
NATRES_TARGET_SECTORS = ('for', 'fsh', 'coa', 'oil', 'gas', 'ore', 'min', 'msp')
# natres_guard value -> the floor on theta_VA (value added over the activity's cost) at which the natural-resource share
# of value added is held (our choice; ch.12.A p.2 accepts large shares where the VA share is very low and gives no cap)
NATRES_GUARD_FLOOR = {'theta_va_floor_0_10_natres_share_of_va_at_most_its_value_there': 0.10}
# ag_shares_choice default (fix round w13, GTAP 12 ch.14A Table 14.2): KF shares except the KF outliers GTAP rejects, which
# take the ch.14A SUR prediction (Table 14.16 coefficients) in place of the old GTAP shares
AG_KF_OUTLIER_SUR = 'fuglie_except_ch14a_table14_2_kf_outliers_ch14a_table14_16_sur_prediction'
# fix worker wD (independent QA MEDIUM-5): the earlier GTAP shares ch.14A prefers are published in the chapter itself
# (Table 14.1 'Current GTAP Build' columns, repeated in Table 14.2), so the KF outliers take those, land the residual
AG_KF_OUTLIER_GTAP = 'fuglie_except_ch14a_table14_2_kf_outliers_ch14a_table14_1_gtap_shares'
AG_OUTLIERS_PATH = os.path.join(CONFIG_DIR, 'ag_kf_outliers.csv')
AG_OUTLIER_COLUMNS = ('iso3', 'table_14_2_preferred', 'gtap_labour_pct', 'gtap_capital_pct', 'reason', 'decided_by', 'decided_at')
# usa_other_production_taxes default (fix worker wD, independent QA MEDIUM-1): the USA D29X39 share of VA from BEA
USA_D29_BEA = 'bea_sut_2022_other_taxes_less_other_subsidies_on_production_by_industry_group_over_io_va'
BEA_MAP_PATH = os.path.join(CONFIG_DIR, 'bea_sut_to_sector.csv')
BEA_MAP_COLUMNS = ('industry_code', 'sectors', 'note')
# d29x39_national_total default (fix worker wD): listed economies' activity D29X39 brought to the national D29 less D39
D29_NATIONAL = 'oecd_table14_d29_less_d39_else_d3_listed_economies_positive_figaro_cells_scaled'
D29_NATIONAL_PATH = os.path.join(CONFIG_DIR, 'd29_national_total.csv')
D29_NATIONAL_COLUMNS = ('iso3', 'reason', 'decided_by', 'decided_at')
AG_SUR_PATH = os.path.join(CONFIG_DIR, 'ag_sur_ch14a.csv')
AG_SUR_COLUMNS = ('equation', 'const', 'log_gdp_pc', 'log_arable_pc', 'unit', 'source', 'decided_by', 'decided_at')
# msp_natres_target default (fix round w13, QA finding #10)
MSP_BLEND = 'isic0910_part_fossil_fuel_target_by_oil_gas_share_of_extraction_output_rest_other_mining_target'
# payroll_property default (fix round w13, GTAP 12 ch.15 pp.2-3; David 2026-10-24: follow the ch.15 text)
PAYROLL_CH15 = 'ch15_grs_payroll_plus_property_all_factors_one_rate_d29_part_moved_from_output_tax'
# next round (David 2026-10-25, with the Gollin labour): where the Gollin step leaves a region's capital income (sum EVOS
# capital) below VDEP_FLOOR x VDEP (S02, 4% of VKB), the self-employed income it added goes back to capital, pro rata
# over the cells, until the floor holds or the region is back at D1 (our choice, not in the GTAP text)
VDEP_FLOOR = 'gollin_addition_returned_to_capital_until_capital_evos_at_least_1_25_vdep'
VDEP_FLOOR_RATIO = 1.25
# beta v4 G2/P40 (S16 country stress CS-7): global Gollin overshoots the ILO SDG 10.4.1 labour income share in 34 regions
# (DOM, PAN, CIV, BWA ...); the Gollin addition goes back to capital, pro rata over the cells, until the region's labour
# income is at most the ILO share of S02 GDP, never below D1 (our choice, not in the GTAP text)
GOLLIN_ILO_CAP = 'gollin_addition_returned_to_capital_until_labour_at_most_ilo_sdg_10_4_1_share_of_gdp_d1_floor'
ILO_MIN_COVER = 0.5           # the members with an ILO value hold at least half the region's S02 GDP
# beta v4 G1 (Grok QA, report D N1): the capital floor never cuts labour below observed compensation of employees (D1);
# a cell whose D1 is above 1 - floor keeps D1 and capital takes the rest (GTAP takes D1 as observed; the floor is ours)
LABOUR_AT_LEAST_D1 = 'labour_share_max_of_d1_and_capped_gollin_capital_floor_gives_way_to_observed_d1'
# labour_definition and mixed_income are one decision: these pairs go together
MIXED_INCOME_OF = {'d1_plus_gollin_self_employed_at_employee_wage': 'self_employed_part_of_b2a3g_to_labour_gollin_rest_capital',
                   'compensation_of_employees_d1': 'operating_surplus_and_mixed_income_b2a3g_to_capital'}
# fix worker wF (QA round 2 P2): crp D29X39 beyond the PSE where the source is a FIGARO estimate outside the EU or a donor
CRP_BEYOND_PSE = 'non_eu_figaro_crp_output_tax_capped_at_zero_after_pse_addback'
# fix worker wF (QA round 2 P2b): a donor (ch.9D) supplies structure, not a policy wedge, so it never passes a net subsidy
DONOR_D29_SIGN = 'donor_passes_max_of_zero_and_its_d29x39_share'
# fix worker wF (QA round 2 P6): listed FIGARO-estimated non-EU cells whose D29X39 share of VA is a balancing artefact
D29_CELLS = 'listed_cells_export_duty_out_then_national_source_sector_median_if_outside_p5_p95_crp_zero'
D29_CELLS_PATH = os.path.join(CONFIG_DIR, 'd29_outlier_cells.csv')
D29_CELLS_COLUMNS = ('iso3', 'sector', 'export_duty_out', 'reason', 'decided_by', 'decided_at')
# fix worker wF (QA round 2 P3): members of a USDA ERS group row that GTAP 12 ch.14A Table 14.2 does not use take the
# Table 14.2 row that covers them (the chapter's published shares)
AG_T142 = 'usda_group_members_take_ch14a_table14_2_row_listed'
AG_T142_PATH = os.path.join(CONFIG_DIR, 'ag_table14_2_rows.csv')
AG_T142_COLUMNS = ('iso3', 'table_14_2_row', 'preferred_source', 'labour_pct', 'capital_pct', 'reason', 'decided_by', 'decided_at')
AG_T142_SOURCES = ('GTAP', 'Fuglie')
# the EU members (2022), as s10_tariffs.preferences.EU27 (a unit test keeps the two equal)
EU27 = frozenset({'AUT', 'BEL', 'BGR', 'HRV', 'CYP', 'CZE', 'DNK', 'EST', 'FIN', 'FRA', 'DEU', 'GRC', 'HUN', 'IRL', 'ITA',
                  'LVA', 'LTU', 'LUX', 'MLT', 'NLD', 'POL', 'PRT', 'ROU', 'SVK', 'SVN', 'ESP', 'SWE'})
# Fable QA B-02 (GTAP 12 ch.14B rule F16a): national occupation x industry employment tables for the listed economies
LABOUR_NATIONAL = 'f16a_listed_national_tables_ilostat_latest_le_base_year_wages_else_regional_wage_profile'
NATIONAL_SOURCES_PATH = os.path.join(CONFIG_DIR, 'national_labour_sources.csv')
NATIONAL_SOURCES_COLUMNS = ('iso3', 'source', 'files', 'occ_controls', 'citation', 'decided_by', 'decided_at')
NATIONAL_OCC_CONTROLS = ('none', 'ilostat_isco08_base_year')
NATIONAL_SHIFT = 0.15   # S12-Rnational: a skilled-share move larger than this is flagged LAB-NATIONAL-SHIFT
NATIONAL_MAP_PATH = os.path.join(CONFIG_DIR, 'national_labour_map.csv')
NATIONAL_MAP_COLUMNS = ('source', 'dim', 'source_code', 'target', 'basis')
# Fable QA F-05 / A-06: land-based PSE support (OECD categories on current and non-current area, incl. the ch.13D EU
# decoupled payments) as a land factor-use subsidy; capital-, labour- and all-factor-based support a negative income tax
SUPPORT_LAND_FACTOR_USE = 's10_crp_land_support_factor_use_subsidy_ch13d_capital_labour_factors_support_negative_income_tax_fbep_memo'
# Fable QA F-03: the ch.15 payroll and property taxes netted out of D29 (the part D29 holds), not booked twice
PAYROLL_NETTED = 'part_of_payroll_property_up_to_region_positive_d29x39_moved_from_output_tax_pro_rata_to_positive_d29_excess_stays_in_factor_payments'
GTAP_STATUS = {'gtap', 'gtap_rule', 'not_in_gtap_text', 'departure_logged', 'n/a'}
HHE_ALL_LABOUR = 'hhe_labour_share_one_every_region'

# choice -> the values this code implements (the first is the default; a choice with two values is a switch)
CHOICES = {
    'labour_capital_source': ('figaro_2022_then_oecd_table6_latest_le_base_year_finest_activity',),
    'labour_definition': ('d1_plus_gollin_self_employed_at_employee_wage', 'compensation_of_employees_d1'),
    'mixed_income': ('self_employed_part_of_b2a3g_to_labour_gollin_rest_capital', 'operating_surplus_and_mixed_income_b2a3g_to_capital'),
    'other_production_taxes': ('d29x39_out_of_va_payroll_part_factor_use_tax_on_labour_rest_output_tax', 'd29x39_in_va_split_pro_rata_by_d1_over_d1_plus_b2a3g'),
    'labour_share_bounds': ('clip_to_0_1_then_cap_at_one_less_cfc_floor_hhe_crp_exempt', 'clip_to_0_1_ledger'),
    'partial_source': ('accept_up_to_5_missing_sectors_filled_under_unobserved_sector',),
    'derive_b2a3g': ('b1g_minus_d1_minus_d29x39_where_b2a3g_missing',),
    'extraction_no_surplus': ('coa_oil_gas_ore_min_source_share_at_or_above_1_treated_as_unobserved',),
    'unobserved_sector': ('nearest_s02_gdppc_donor_observing_the_sector_same_gtap15_pool_else_world',),
    'va_no_source_rule': ('gtap9d_nearest_s02_gdppc_in_gtap15_pool_among_regions_with_source_else_world',),
    'non_icio_va': ('own_national_accounts_else_s05_donor_weighted_by_weight_x_donor_sector_va',),
    'negative_va': ('whole_va_to_capital_flagged_for_s13',),
    'ag_factor_shares': ('usda_ers_fuglie_2022_land_labour_capital_normalised_crp',),
    'ag_shares_choice': (AG_KF_OUTLIER_GTAP, AG_KF_OUTLIER_SUR, 'fuglie_only_old_gtap_shares_unavailable'),
    'usa_other_production_taxes': (USA_D29_BEA, 'figaro_2022_d29x39_as_other_economies'),
    'd29x39_national_total': (D29_NATIONAL, 'source_activity_d29x39_as_published'),
    'ag_fill': ('sur_lab_kap_on_log_gdppc_log_arable_pc_fuglie_2011_2020_predict_2022_else_geo_average',),
    'land_rent_reallocation': ('not_applied_no_lulc_database',),
    'forestry_land': ('no_land_forest_rent_is_natres',),
    'natres_source': ('wdi_rents_pct_gdp_2021_x_s02_gdp_members_summed',),
    'natres_map': ('oil_petr_gas_ngas_coa_coal_minr_to_ore_first_then_min_for_frst', 'oil_petr_gas_ngas_coa_coal_ore_min_minr_by_capital_income_for_frst'),
    'natres_cap': ('capped_at_net_operating_surplus_nonlabour_less_cfc_excess_flagged',),
    'cfc_source': ('oecd_table6_p51c_over_b2a3g_own_else_gtap15_pool_median_else_all_median', 'oecd_table6_p51c_over_b2a3g_by_activity_else_nearest_gdppc_economy_reporting_the_sector'),
    'natres_scale': ('coa_oil_gas_rent_share_of_nonlabour_at_s11_output_value',),
    'fishing_natres': ('gtap_ch12a_target_elasticity_under_natres_rule', 'zero_flagged_no_flow_source'),
    'natres_rule': ('gtap_ch12a_target_supply_elasticity_share_out_of_all_va', 'wdi_rents_a7_capped_at_net_operating_surplus'),
    'msp_natres_target': (MSP_BLEND, 'other_mining_target_whole_msp'),
    'natres_guard': ('theta_va_floor_0_10_natres_share_of_va_at_most_its_value_there',),
    'labour_matrix': ('eq14_1_all_countries', 'observed_cross_table_where_in_window_else_eq14_1'),
    'ilostat_series': ('committed_emp_temp_sex_ocu_eco_and_ear_emta_sex_ocu_eco_usd',),
    'ilostat_source_pick': ('lfs_ba_first_then_most_categories_then_total',),
    'isco88_harmonisation': ('major_groups_one_to_one',),
    'labour_year_window': ('base_year_else_three_latest_consecutive_else_two_latest_le_base_year',),
    'wage_weight': ('beta_mean_over_mean_plus_abs_distance',),
    'wage_missing': ('occupation_prior_country_mean_industry_constraint_dropped_flagged',),
    'labour_minimum_data': ('6_occupations_5_occupation_wages_5_industry_wages',),
    'labour_no_data': ('f16c_geo_region_average_shares_else_world',),
    'labour_national_tables': (LABOUR_NATIONAL, 'off_ilostat_and_f16c_only'),
    'labour_groups': ('five_groups_table_14_18_two_group_exact_aggregation',),
    'composite_shares': ('members_weighted_by_s05_weight',),
    'factor_tax_values': ('s10_factor_tax_rates_value_musd',),
    'ssc': ('labour_cells_one_rate',),
    'payroll_property': (PAYROLL_CH15, 'd29_payroll_part_grs_t3000_share_on_labour_one_rate_rest_in_output_tax', 'all_factor_cells_one_rate'),
    # our rule (E48), not in the ch.15 text: recorded on its own so the payroll_property tag can stay with the ch.15 booking
    'payroll_d29_netting': ('none_d29x39_stays_output_tax_payroll_property_inside_factor_payments',
                            PAYROLL_NETTED),
    'income_tax': ('pit_labour_cit_land_capital_natres_pro_rata_evfb',),
    'parent_split': ('figaro_parent_code_split_by_own_oecd_table6_divisions',),
    'uniform_block': ('figaro_imputed_uniform_section_own_d1_total_nearest_donor_pattern',),
    'capital_floor': ('oecd_table6_p51c_over_d1_plus_b2a3g_own_else_gtap15_pool_median_else_world_median',),
    'gollin_source': ('ilostat_emp_temp_sex_ste_eco_latest_le_base_year_lfs_first_else_nearest_gdppc_pool',),
    'capital_vdep_floor': (VDEP_FLOOR, 'off'),
    'gollin_ilo_cap': ('off', GOLLIN_ILO_CAP),          # beta v4 G2/P40
    'labour_at_least_d1': (LABOUR_AT_LEAST_D1, 'off'),
    'natres_price_year': ('wdi_2021_oil_gas_rents_scaled_by_pinksheet_2022_over_2021_regional_gas', 'wdi_latest_year_unscaled'),
    'natres_zero_rent': ('ore_min_pool_median_natres_share_of_net_surplus', 'zero'),
    'oil_donor_split': ('s05_oil_donor_split_for_oil_and_gas', 'ch9d_donor_for_every_sector'),
    'crp_d29_beyond_pse': (CRP_BEYOND_PSE, 'source_d29x39_as_published'),
    'donor_d29_sign': (DONOR_D29_SIGN, 'donor_share_as_published'),
    'd29_outlier_cells': (D29_CELLS, 'source_d29x39_as_published'),
    'ag_table14_2_rows': (AG_T142, 'usda_group_rows_as_published'),
    'factor_support': ('s10_crp_factor_support_as_factor_use_subsidy_evfb_above_evfp_evos_unchanged', 's10_crp_land_capital_labour_factors_support_negative_income_tax_fbep_memo',
                       SUPPORT_LAND_FACTOR_USE),
    # round-3 final QA item 7: land income tax at most 99% of land rent (the S13 EVOS floor), the excess dropped and ledgered
    'land_income_tax_cap': ('land_income_tax_at_most_99pct_of_land_rent_less_factor_use_tax_excess_dropped_ledgered', 'off'),
    # beta v4 G4 (David 2026-10-26): households as employers are all labour (paid domestic work is valued at its compensation)
    'hhe_labour_share': (HHE_ALL_LABOUR, 'off'),
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
    ld, mi = seen.get('labour_definition'), seen.get('mixed_income')
    if ld and mi and MIXED_INCOME_OF.get(ld['value']) not in (None, mi['value']):
        bad.append(f'mixed_income {mi["value"]!r} does not go with labour_definition {ld["value"]!r} '
                   f'(expected {MIXED_INCOME_OF[ld["value"]]!r})')
    if bad:
        raise ConfigError(f'{path}: ' + '; '.join(bad))
    return seen


def load_natres_targets(path=NATRES_TARGETS_PATH):
    """Fix round B16: {sector: dict(eta, sigma, gtap_sector, target_class, source)} from config/s12/natres_targets.csv.
    Raise ConfigError unless the file has exactly the eight resource sectors, each once, with positive eta and sigma_va,
    a source and a decided_by and decided_at."""
    if not os.path.exists(path):
        raise ConfigError(f'{path} is missing')
    with open(path, newline='') as fh:
        rd = csv.DictReader(fh)
        if tuple(rd.fieldnames or ()) != NATRES_TARGET_COLUMNS:
            raise ConfigError(f'{path}: columns {rd.fieldnames} are not {NATRES_TARGET_COLUMNS}')
        rows = list(rd)
    out, bad = {}, []
    for r in rows:
        s = r['sector']
        if s in out:
            bad.append(f'{s}: duplicate row')
        if s not in NATRES_TARGET_SECTORS:
            bad.append(f'{s}: not a natural-resource sector ({NATRES_TARGET_SECTORS})')
        try:
            eta, sig = float(r['eta_target']), float(r['sigma_va'])
        except ValueError:
            bad.append(f'{s}: eta_target or sigma_va is not a number')
            continue
        if not (eta > 0 and sig > 0):
            bad.append(f'{s}: eta_target and sigma_va must be positive')
        if not r['source'].strip() or not r['decided_by'].strip() or not r['decided_at'].strip():
            bad.append(f'{s}: source, decided_by or decided_at is blank')
        out[s] = dict(eta=eta, sigma=sig, gtap_sector=r['gtap_sector'], target_class=r['target_class'], source=r['source'])
    bad += [f'{s}: row missing' for s in NATRES_TARGET_SECTORS if s not in out]
    if bad:
        raise ConfigError(f'{path}: ' + '; '.join(bad))
    return out


def _strict_rows(path, columns):
    if not os.path.exists(path):
        raise ConfigError(f'{path} is missing')
    with open(path, newline='') as fh:
        rd = csv.DictReader(fh)
        if tuple(rd.fieldnames or ()) != columns:
            raise ConfigError(f'{path}: columns {rd.fieldnames} are not {columns}')
        rows = list(rd)
    if not rows:
        raise ConfigError(f'{path} is empty')
    return rows


def load_ag_outliers(path=AG_OUTLIERS_PATH):
    """Fix round w13 (GTAP 12 ch.14A Table 14.2): {iso3: reason} for the countries whose KF shares GTAP rejects.
    Raise ConfigError on a duplicate, a preferred source other than GTAP, or a blank reason or attribution."""
    out, bad = {}, []
    for r in _strict_rows(path, AG_OUTLIER_COLUMNS):
        c = r['iso3'].strip()
        if len(c) != 3 or not c.isupper():
            bad.append(f'{c!r}: not an ISO3 code')
        if c in out:
            bad.append(f'{c}: duplicate row')
        if r['table_14_2_preferred'] != 'GTAP':
            bad.append(f'{c}: table_14_2_preferred must be GTAP (only the countries where ch.14A rejects KF are listed)')
        if not r['reason'].strip() or not r['decided_by'].strip() or not r['decided_at'].strip():
            bad.append(f'{c}: reason, decided_by or decided_at is blank')
        try:
            lab, kap = float(r['gtap_labour_pct']), float(r['gtap_capital_pct'])
            if not (lab > 0 and kap > 0 and lab + kap < 100):
                bad.append(f'{c}: GTAP labour and capital shares must be positive and leave land above zero')
        except ValueError:
            bad.append(f'{c}: gtap_labour_pct or gtap_capital_pct is not a number')
        out[c] = r['reason']
    if bad:
        raise ConfigError(f'{path}: ' + '; '.join(bad))
    return out


def load_ag_outlier_gtap_shares(path=AG_OUTLIERS_PATH):
    """Fix worker wD (independent QA MEDIUM-5): {iso3: dict(land, labour, capital)} from the ch.14A Table 14.1 GTAP
    labour and capital shares of the Table 14.2 KF outliers (percent), land the residual (ch.14A p.2: the land
    equation is the residual). Validated by load_ag_outliers."""
    load_ag_outliers(path)
    out = {}
    for r in _strict_rows(path, AG_OUTLIER_COLUMNS):
        lab, kap = float(r['gtap_labour_pct']) / 100.0, float(r['gtap_capital_pct']) / 100.0
        out[r['iso3'].strip()] = dict(land=1.0 - lab - kap, labour=lab, capital=kap)
    return out


def load_bea_map(path=BEA_MAP_PATH):
    """Fix worker wD: {BEA summary industry code: tuple of our sectors} ('none' -> empty tuple, for the government
    industries BEA gives no other taxes on production). Raise ConfigError on a duplicate, a blank row or no rows."""
    out, bad = {}, []
    for r in _strict_rows(path, BEA_MAP_COLUMNS):
        c = r['industry_code'].strip()
        if not c or c in out:
            bad.append(f'{c!r}: blank or duplicate')
        sec = r['sectors'].split()
        if not sec or not r['note'].strip():
            bad.append(f'{c}: sectors or note blank')
        out[c] = () if sec == ['none'] else tuple(sec)
    if bad:
        raise ConfigError(f'{path}: ' + '; '.join(bad))
    return out


def load_d29_national(path=D29_NATIONAL_PATH):
    """Fix worker wD: {iso3: reason} for the economies whose activity-level D29X39 is brought to the national total.
    Raise ConfigError on a duplicate, a bad code or a blank field."""
    out, bad = {}, []
    for r in _strict_rows(path, D29_NATIONAL_COLUMNS):
        c = r['iso3'].strip()
        if len(c) != 3 or not c.isupper() or c in out:
            bad.append(f'{c!r}: not an ISO3 code, or duplicate')
        if not r['reason'].strip() or not r['decided_by'].strip() or not r['decided_at'].strip():
            bad.append(f'{c}: reason, decided_by or decided_at is blank')
        out[c] = r['reason']
    if bad:
        raise ConfigError(f'{path}: ' + '; '.join(bad))
    return out


def load_ag_sur(path=AG_SUR_PATH):
    """Fix round w13: the ch.14A Table 14.16 (2) SUR coefficients, {'capital': (const, gdp, land), 'labour': (...)}, as
    shares (the table is in percent). Raise ConfigError unless exactly the two equations are present with numbers."""
    out, bad = {}, []
    for r in _strict_rows(path, AG_SUR_COLUMNS):
        e = r['equation']
        if e not in ('capital', 'labour') or e in out:
            bad.append(f'{e!r}: not capital or labour, or duplicate')
            continue
        try:
            b = tuple(float(r[k]) / 100.0 for k in ('const', 'log_gdp_pc', 'log_arable_pc'))
        except ValueError:
            bad.append(f'{e}: coefficient is not a number')
            continue
        if r['unit'] != 'percent of agricultural value added' or not r['source'].strip() or not r['decided_by'].strip():
            bad.append(f'{e}: unit, source or decided_by')
        out[e] = b
    bad += [f'{e}: row missing' for e in ('capital', 'labour') if e not in out]
    if bad:
        raise ConfigError(f'{path}: ' + '; '.join(bad))
    return out


def load_d29_cells(path=D29_CELLS_PATH):
    """Fix worker wF (QA round 2 P6): {(iso3, sector): dict(export_duty_out, reason)} for the listed FIGARO-estimated
    cells. Raise ConfigError on a bad code, a duplicate, an export_duty_out other than yes/no or a blank field."""
    out, bad = {}, []
    for r in _strict_rows(path, D29_CELLS_COLUMNS):
        c, s = r['iso3'].strip(), r['sector'].strip()
        if len(c) != 3 or not c.isupper() or not s or (c, s) in out:
            bad.append(f'{c!r} {s!r}: not an ISO3 code and sector, or duplicate')
        if r['export_duty_out'] not in ('yes', 'no'):
            bad.append(f'{c} {s}: export_duty_out must be yes or no')
        if not r['reason'].strip() or not r['decided_by'].strip() or not r['decided_at'].strip():
            bad.append(f'{c} {s}: reason, decided_by or decided_at is blank')
        out[(c, s)] = dict(export_duty_out=r['export_duty_out'] == 'yes', reason=r['reason'])
    if bad:
        raise ConfigError(f'{path}: ' + '; '.join(bad))
    return out


def load_ag_table14_2(path=AG_T142_PATH):
    """Fix worker wF (QA round 2 P3): {iso3: dict(land, labour, capital, row, source, reason)} from the GTAP 12 ch.14A
    Table 14.2 rows (percent of agricultural value added, land the residual, ch.14A p.2). Raise ConfigError on a bad
    code, a duplicate, a source other than GTAP or Fuglie, shares that leave no land, or a blank field."""
    out, bad = {}, []
    for r in _strict_rows(path, AG_T142_COLUMNS):
        c = r['iso3'].strip()
        if len(c) != 3 or not c.isupper() or c in out:
            bad.append(f'{c!r}: not an ISO3 code, or duplicate')
        if r['preferred_source'] not in AG_T142_SOURCES:
            bad.append(f'{c}: preferred_source must be one of {AG_T142_SOURCES}')
        if not r['table_14_2_row'].strip() or not r['reason'].strip() or not r['decided_by'].strip() or not r['decided_at'].strip():
            bad.append(f'{c}: table_14_2_row, reason, decided_by or decided_at is blank')
        try:
            lab, kap = float(r['labour_pct']), float(r['capital_pct'])
        except ValueError:
            bad.append(f'{c}: labour_pct or capital_pct is not a number')
            continue
        if not (lab > 0 and kap > 0 and lab + kap < 100):
            bad.append(f'{c}: labour and capital shares must be positive and leave land above zero')
        out[c] = dict(land=1.0 - lab / 100.0 - kap / 100.0, labour=lab / 100.0, capital=kap / 100.0,
                      row=r['table_14_2_row'], source=r['preferred_source'], reason=r['reason'])
    if bad:
        raise ConfigError(f'{path}: ' + '; '.join(bad))
    return out


def load_national_sources(path=NATIONAL_SOURCES_PATH, readers=()):
    """Fable QA B-02: {iso3: dict(source, files (list of data-relative paths), citation)}. Raise ConfigError on a bad
    code, a duplicate, an unknown reader, no file or a blank field."""
    out, bad = {}, []
    for r in _strict_rows(path, NATIONAL_SOURCES_COLUMNS):
        c, src = r['iso3'].strip(), r['source'].strip()
        if len(c) != 3 or not c.isupper() or c in out:
            bad.append(f'{c!r}: not an ISO3 code, or duplicate')
        if readers and src not in readers:
            bad.append(f'{c}: source {src!r} is not one of {sorted(readers)}')
        files = [f.strip() for f in r['files'].split(';') if f.strip()]
        if not files or not r['citation'].strip() or not r['decided_by'].strip() or not r['decided_at'].strip():
            bad.append(f'{c}: files, citation, decided_by or decided_at is blank')
        if r['occ_controls'] not in NATIONAL_OCC_CONTROLS:
            bad.append(f'{c}: occ_controls {r["occ_controls"]!r} not in {NATIONAL_OCC_CONTROLS}')
        out[c] = dict(source=src, files=files, citation=r['citation'], occ_controls=r['occ_controls'])
    if bad:
        raise ConfigError(f'{path}: ' + '; '.join(bad))
    return out


def load_national_map(path=NATIONAL_MAP_PATH, sections=(), occ_codes=tuple(str(i) for i in range(1, 10))):
    """Fable QA B-02: {source: {'occ': {code: [ISCO groups]}, 'ind': {code: [sections]}}}; an empty target leaves the
    code out (totals, armed forces, not classified, section U). Raise ConfigError on an unknown dim or target, a
    duplicate code or a blank basis."""
    out, bad = {}, []
    for r in _strict_rows(path, NATIONAL_MAP_COLUMNS):
        src, dim, code = r['source'].strip(), r['dim'].strip(), r['source_code'].strip()
        tg = [t.strip() for t in r['target'].split('+') if t.strip()]
        ok = occ_codes if dim == 'occ' else sections
        if dim not in ('occ', 'ind'):
            bad.append(f'{src} {code}: dim {dim!r}')
            continue
        if ok and any(t not in ok for t in tg):
            bad.append(f'{src} {dim} {code}: target {r["target"]!r} not in {list(ok)}')
        d = out.setdefault(src, {'occ': {}, 'ind': {}})[dim]
        if code in d:
            bad.append(f'{src} {dim} {code}: duplicate')
        if not r['basis'].strip():
            bad.append(f'{src} {dim} {code}: basis is blank')
        d[code] = tg
    if bad:
        raise ConfigError(f'{path}: ' + '; '.join(bad))
    return out
