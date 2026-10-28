"""S10 configuration: the decision rows and the config tables, read strictly.

Every row in config/s10/s10_choices.csv must be a choice this code knows, with a
value in its allowed set, a decided_by and a decided_at. Every choice the code
knows must be in the file. A config table that is missing, empty, or lacks a
required column stops the build. There is no fallback copy of any file.

The first value in each allowed tuple is the one decided at the time of the
rebuild (2026-10-23). A second value is an alternative the code implements so
that a pending decision only needs a config edit; it is never used unless the
row says so.
"""
import csv
import os

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BUILD, 'config', 's10')
CHOICES_PATH = os.path.join(CONFIG_DIR, 's10_choices.csv')
CHOICE_COLUMNS = ('choice', 'value', 'decided_by', 'decided_at', 'basis', 'gtap_status')
GTAP_STATUS = {'gtap', 'gtap_rule', 'not_in_gtap_text', 'departure_logged', 'n/a'}


class ConfigError(SystemExit):
    pass


# choice -> allowed values. Grouped by the part of S10 that reads them.
CHOICES = {
    # --- tariff method (GTAP 12 ch.11B) ---
    'tariff_layer': ('hs6_best_applied_rebuild_from_wits_bulk_2017_2022',),
    'tariff_rate_rule': ('best_applied_min_mfn_general_pref_simple_avg_within_hs6',),
    'tariff_weights': ('baci_2021_2023_average_hs17_2021_by_unsd_conversion_table_split_by_2022_world_imports',),
    'hs6_min_of_simple_averages': ('min_over_agreements_of_wits_hs6_simple_averages',),
    'trains_ave_series': ('reported_when_nbr_na_lines_eq_0_else_aveestimated',),
    'specific_no_ave_lines_excluded_from_weight': ('left_out_of_the_weight_listed_with_trade_no_duty',),
    'preference_year_fallback': ('latest_year_per_agreement_family_then_min_across_families',),
    'agreement_families': ('successor_codes_share_a_family_then_latest_line_min_across_families',),
    'preference_groups': ('wits_pref_beneficiaries_full_with_v33_2022_membership_rules',),
    'preference_group_members': ('wits_beneficiary_table_and_xls_one_row_per_group',),
    'preference_exceptions': ('no_rate_filled_where_trains_bilateral_extract_empty',),
    'tariff_concordance': ('s01_5ddbe4d_reaggregated',),
    'service_tariffs': ('zero_hs6_lines_mapping_to_services_reported',),
    'new_sector_preference': ('wat_pub_art_pro_pst_same_overlay_as_other_goods',),
    'egypt_alcohol_rates': ('keep_statutory_reported_when_nbr_na_lines_is_zero',),
    'egypt_mixed_sublines': ('non_alcoholic_subline_rate_on_330210_and_210690', 'trains_hs6_simple_average'),
    'missing_baci_weight': ('pair_own_hs6_rates_weighted_by_importer_total_hs6_imports',),
    'composite_fold': ('cuw_to_xcb_ncl_pyf_to_xoc_baci2022_trade_weights',),
    'xnf_xsm_importer': ('members_reweighted_baci2022',),
    'composite_diagonal_tariffs': ('member_pair_rates_trade_weighted',),
    'importer_without_schedule': ('parent_schedule_for_customs_union_territories_else_left_out_of_weight',),
    'country_code_join': ('one_canonical_iso_map_from_s01_aliases_hard_checked',),
    'customs_unions': ('cet_unions_in_customs_unions_csv',),
    'legal_internal_zeros': ('eu_territory_gcc_sacu_eaeu_eac_mercosur_eea_che_lie',),
    'us_301_232': ('baseline_excludes_trade_remedies_301_232_scenario_file',),
    # preferences: membership, lapses and named rules
    'uk_continuity': ('gbr_kept_in_eu_group_where_continuity_in_force_in_2022',),
    'us_gsp_lapse': ('b11_c06_c53_c69_01r_b15_and_named_usa_gsp_not_applied_for_2022',),
    'us_gsp_single_country': ('excluded_from_lapsed_group_drops_2017_2021_single_country_row',),
    'lapse_cutoff': ('apply_lapse_only_on_or_before_2022_01_01',),
    'cis_ukraine_lapse': ('rus_suspends_cis_fta_for_ukraine_from_2016_01_01_decree_628',),
    'cis_other_ukraine': ('no_lapse_for_kaz_blr_arm_without_a_decree',),
    'rus_mda_736': ('no_hs_lapse_annex_not_in_files',),
    'eu_gsp_graduation': ('ind_idn_ken_sections_on_01T',),
    'eu_gsp_armenia': ('arm_dropped_from_01T_and_01W',),
    'cambodia_eba_withdrawal': ('khm_banned_on_listed_prefixes_of_01T_01U_01W',),
    'cptpp_membership': ('drop_chl_and_brn',),
    'rcep_membership': ('drop_idn_phl_mmr_except_chn_add_nzl_on_brn_sgp_01D',),
    'saudi_mfn_ceiling': ('preference_kept_only_below_2022_mfn',),
    'khm_acfta_partner': ('khm_2020_2021_partner_356_is_china',),
    'khm_pan_2022_preferences': ('khm_2022_file_absent_pan_2020_2021_list_no_preference',),
    'preference_gap_notes': ('cod_ago_irn_ven_isr_ukr_png_aus_files_absent_rates_unchanged',),
    'are_ind_cepa': ('year_rule_are_latest_file_2021_does_not_contain_cepa',),
    'missing_schedule_in_source': ('mfn_where_source_has_no_schedule',),
    'epa_acp_staging': ('unmodelled_trains_as_held',),
    'epa_pacific_staging': ('same_ruling_as_epa_acp_staging',),
    'eac_cet_first_half': ('one_rate_for_the_year_2022_trains_is_the_july_book_no_blend',),
    'mfn_zip_notes': ('cri_2021_and_mus_2021_empty_unused',),
    'ace57_vehicles': ('source_line_only_ury_arg_vehicles_not_rebooked',),
    'iraq_gafta_2022': ('imf_cr_2021_158_paragraph_21_book_nothing',),
    'near_schedule_notes': ('mrt_left_ecowas_in_december_2000_cok_not_a_customs_union',),
    # named schedule overrides
    'iraq_tariffs': ('legal_food_zero_6.5_of_12_no_0.159_scaling',),
    'iraq_statutory_rates': ('keep_resolution_393_2017',),
    'tkm_tariffs': ('named_exception_resolution_9925_rate_table_absent',),
    'lby_ven_importer': ('own_schedule_lby2021_ven2022_own_baci2022_weights_best_applied_where_a_preference_resolves',),
    'lby_ven_partner': ('pair_own_line_rate_same_as_nb1',),
    'panama_tpa': ('min_tpa_mfn_on_pan_usa',),
    'tunisia_schedule': ('trains_2016_reported_finance_law_2018_art39_turkey_fta_protocol1_lf2018_art40_list2_60pct_list3_mfn',
                         'trains_2016_reported_finance_law_2018_art39_turkey_mfn'),
    'morocco_wheat': ('hs6_100111_100119_100191_100199_suspended',),
    'cambodia_271012': ('regular_gasoline_ave_10_2_flagged',),
    'ncl_schedule': ('own_customs_tariff_2023_consolidation_2022_dd_restored_from_drdnc_notice_22001425_eu_and_oct_origin_exempt',),
    'mys_preference_schedules': ('own_2022_rates_bilaterals_acfta_ahkfta_atiga_akfta_rcep_cptpp_ajcep_members_by_table',),
    'prk_tariff': ('flat_5_5_from_2005_manual_flagged',),
    'pal_pse_schedule': ('pse_2017_schedule_joined_to_pal_tm',),
    'usa_pharma_appendix': ('hts_2022_special_k_and_l_erga_omnes_zero', 'no_overlay_trains_as_held'),
    'ave_outlier_rule': ('replace_only_if_statute_shows_failed_conversion_mixed_duty_uses_ad_valorem_alternative_specific_uses_fob_unit_value',),
    'korea_article71': ('hs6_legal_rate_before_min_with_preferences_day_weighted',),
    'trq_fill_rule': ('macmap_fill_below_90_in_quota_above_98_over_quota_else_average',),
    'trq_fill_measure': ('plan_in_quota_utilisation_departure_from_imports_over_quota', 'baci_2022_hs6_tonnes_over_quota'),
    'maize_trq_basis': ('article71_volume_with_korus_baci_imports_excluded',),
    'korea_trq_full_fill': ('fill_at_one_is_out_of_quota_notified',),
    'trq_outside_kor_pan': ('wto_ma2_2022_fill_rule_on_quota_line_pairs', 'ntl_in_out_average_where_no_fill_source'),
    'trq_line_rates': ('hs6_min_is_in_quota_max_is_over_quota_line',),
    'trq_no_fill': ('in_quota_rate_where_no_notified_imports',),
    'trq_bilateral_fill': ('in_quota_rate_on_preferential_quota_lines_no_bilateral_fill_in_sources',),
    # --- trade base and IO ---
    'tariff_base': ('vcif_eq_vxsb_s07_plus_vtwr_s08_vmsb_eq_vcif_times_1_plus_tm',),
    'vxsb_from_vfob': ('vxsb_equals_vfob_over_export_tax_power',),
    'oil_gas_tariffs': ('separate_rates_b06_duty_is_sum_for_io_removal',),
    'duty_from_tls': ('eff_rate_times_imp_use_per_column_excess_reported_not_netted',),
    'tls_split': ('remainder_dom_imp_pro_rata_basic_value',),
    'product_tax_pattern': ('vat_schedule_grs_vat_and_excise_layers_eurostat_product_control', 'vat_schedule_grs_vat_and_excise_layers', 'none'),
    'non_icio_tls': ('donor_tls_kept_statutory_vat_grs_5111_5121_report_only',),
    'production_taxes': ('pse_output_payments_only_oecd_d29x39_report_only',),
    'travel_rows': ('no_tariff_export_tax_or_margin_s13_merge_tm_diluted_revenue_kept',),
    # --- support (ch.11A), export subsidies (ch.11C), taxes (ch.15) ---
    'pse_source': ('oecd_moneva_2022_usd_budgetary_A2_to_E_mps_excluded',),
    'pse_F_G': ('pn_F_and_pm_G_excluded',),
    'pse_mapping': ('po_output_piv_pis_inputs_pif_and_animal_capital_area_land_receipts_income_labour_C_and_D_by_basis_E_factors_pro_rata',),
    'pse_aan_split': ('pcaan_by_moneva_basis_area_land_animal_capital_else_faostat_share_flagged',
                      'pcaan_phraan_land_capital_by_faostat_2022_crop_livestock_share_flagged'),
    'pse_commodity': ('all_to_crp',),
    'pse_eu': ('faostat_2022_member_output_split',),
    'pse_eu_mapping': ('ch13d_e_phnr_and_income_based_c_d_to_land_one_rate', 'standard_formula_as_non_eu'),
    'pse_non_oecd': ('none_io_kept',),
    'export_subsidy': ('wto_agims_notified_outlays_rate_per_ch11C_p2_else_none',),
    'export_subsidy_year': ('year_rule_latest_le2022_mus2021_tun2019_pak2017_flagged',),
    'export_subsidy_base': ('own_hs_lines_xt_below_0.05_usd_million_report_not_book_blank_product_uses_sector_vxsb_flagged',),
    'export_taxes_other': ('grs_t5124_2022_spread_by_wto_tpr_product_lists', 'none_beyond_io'),
    'export_tax_unlisted': ('not_booked_flagged_needs_source',),
    'export_tax_rates': ('statutory_2022_rates_ave_on_baci_unit_value_export_weighted', 'none'),
    # beta v4 G12 (Grok QA C3): EAEU members' export duties off on member routes outside energy (S11 handles energy)
    'export_tax_union_exempt': ('union_members_zero_duty_on_member_routes_non_energy_grs_total_respread_statutory_rate_kept', 'off'),
    # --- energy taxes on the fuel, power and gas rows (fix list A1) ---
    'energy_tax_rows': ('specific_rates_by_use_class_converted_to_ad_valorem_in_s13_at_s11_basic_prices', 'one_column_rate'),
    'energy_tax_year': ('neer_2021', 'neer_2023_latest', 'neer_mean_2021_2023'),
    # beta v5 E6 (David 2026-10-27 package approval): NEERS EUR values to base-year USD through the local currency
    'energy_tax_fx': ('lcu_neers_year_to_usd_base_year_wdi', 'eur_usd_of_the_neers_year'),
    # beta v5 S5 (labelled departure): listed importers' quota sectors scaled to OECD GRS 5123 collected duty
    'tariff_collected_scale': ('listed_importer_sectors_times_min1_collected_over_booked', 'off'),
    # beta v5 K and S5-BGD: sourced line overrides (config/s10/sourced_line_overrides.csv), off until a source is on disk
    'tariff_pak_lng_concession': ('off', 'fbr_fifth_schedule_rows'),
    'tariff_bgd_nbr_fuel': ('off', 'nbr_2022_schedule_rows'),
    'energy_subsidies': ('net_of_neer_subsidies', 'taxes_only'),
    'energy_tax_fill': ('same_energy_trade_direction_in_pool_else_zero', 'trade_weighted_s12_pool_average_else_world',
                        'world_trade_weighted_average'),
    'energy_tax_usa': ('eia_federal_plus_average_state_road_fuel_excise_2022_on_road_pet', 'pool_fill'),
    'pse_input_rows': ('needs_source_piv_by_input_kept_on_the_column',),
    'fuel_sales_taxes': ('ind_state_vat_bra_icms_on_road_pet_at_neers_road_share', 'none'),
    'income_tax_source': ('oecd_grs_2022_then_imf_world_s13_then_imf_gfs_soo_s13_then_world_central', 'oecd_grs_2022_then_imf_world_2022'),
    'gulf_zakat': ('sau_gfs_g116_other_taxes_incl_zakat_as_cit', 'not_booked'),
    'income_tax_aggregate': ('split_g111_else_g11_at_covered_shares_implied_zero_when_g111_equals_one_component',),
    'world_sector': ('s13_else_s1311mixed_flagged_central_government',),
    'ssc': ('total_ssc_T2000_to_labour_employer_shares_report_only',),
    'payroll_property': ('grs_T3000_plus_T4000_else_world_G113_all_factors_uniform',),
    'pit_cit': ('pit_to_labour_cit_to_capital_land_natres',),
    'tax_values': ('pct_gdp_times_io_gdp',),
    'tax_missing': ('simple_average_of_covered_ratios',),
    'bhr_kwt': ('zero_pit_cit_from_source',),
    # --- reports, screens, records ---
    'customs_check': ('report_only_vs_customs_collected_2022_with_cause_column',),
    'us_duty_benchmark': ('census_imdb_cy2022_report_only_89.763bn_china_57.43bn',),
    'usa_customs_compare': ('label_oecd_grs_t_5123_and_add_census_column',),
    'usa_chapter_far': ('kl_outside_bar_unexplained_232_and_nocap_named',),
    'statutory_vs_collected': ('ch11b_p2_b4_when_no_conversion_membership_or_stale_share_above_bar',),
    'statutory_vs_collected_cap': ('no_cap',),
    'statutory_vs_collected_below': ('no_cap_includes_booked_below_collected',),
    'screen_hard_check': ('fail_when_material_unexplained_or_screen_error',),
    'screen_duty_base': ('one_hit_per_common_schedule_line_duty_on_imports_facing_the_rate',),
    'screen_diagnostics': ('stale_coverage_and_moves_are_diagnostics',),
    'screen_cross_dedupe': ('one_material_hit_per_importer_hs6_across_screens',),
    'collections_materiality': ('gap_at_0_02_bn_or_0_1_pct_census_89_763_for_usa',),
    'collections_driver_cover': ('build_preference_state_lapses_uk_continuity_and_family_min',),
    'earlier_year_conversion': ('earlier_rate_below_1_pct_is_earlier_year_conversion',),
    'fta_population_screen': ('diagnostic_flags_for_material_pairs_with_no_preference_row',),
    'fta_pair_reparse': ('part_year_suspended_and_entry_date_only_in_screen_11',),
    'afcfta_comesa_genuine': ('not_a_source_gap',),
    'wits_rate_as_given': ('booked_equals_wits_trains_line_rate_or_ave',),
    'stamp_prev_output': ('record_previous_output_sha_and_commit_in_stamp',),
    'trains_outputs': ('committed_private_repo_marked_not_for_publication',),
    'io_s10_commit': ('yes_private_repo',),
    'tkm_gas_prep_h10': ('accepted_tkm_9.5pct_vs_ei_s11_binds_pr72',),
}


def load_choices(path=CHOICES_PATH):
    """Return {choice: value}. Raise ConfigError on any problem, listing all of them."""
    if not os.path.exists(path):
        raise ConfigError(f'{path} is missing')
    with open(path, newline='', encoding='utf-8') as fh:
        reader = csv.DictReader(fh)
        missing_cols = [c for c in CHOICE_COLUMNS if c not in (reader.fieldnames or ())]
        if missing_cols:
            raise ConfigError(f'{path} lacks columns {missing_cols}')
        rows = list(reader)
    problems = []
    values = {}
    for row in rows:
        name = (row['choice'] or '').strip()
        value = (row['value'] or '').strip()
        if name in values:
            problems.append(f'{name}: duplicate row')
            continue
        if name not in CHOICES:
            problems.append(f'{name}: not a choice this code implements')
            continue
        if value not in CHOICES[name]:
            problems.append(f'{name}: value {value!r} not in {CHOICES[name]}')
        if not (row['decided_by'] or '').strip() or not (row['decided_at'] or '').strip():
            problems.append(f'{name}: decided_by or decided_at is blank')
        if (row['gtap_status'] or '').strip() not in GTAP_STATUS:
            problems.append(f'{name}: gtap_status {row["gtap_status"]!r}')
        values[name] = value
    for name in CHOICES:
        if name not in values:
            problems.append(f'{name}: row missing')
    if problems:
        raise ConfigError(f'{path}: ' + '; '.join(problems))
    return values


def read_table(name, required, min_rows=1, path=None):
    """Read config/s10/<name>. Raise when the file, a column, or the rows are missing."""
    path = path or os.path.join(CONFIG_DIR, name)
    if not os.path.exists(path):
        raise ConfigError(f'config table {path} is missing')
    with open(path, newline='', encoding='utf-8') as fh:
        reader = csv.DictReader(fh)
        cols = reader.fieldnames or []
        lack = [c for c in required if c not in cols]
        if lack:
            raise ConfigError(f'{path} lacks columns {lack}')
        rows = [{k: (v or '').strip() for k, v in r.items()} for r in reader]
    if len(rows) < min_rows:
        raise ConfigError(f'{path} has {len(rows)} rows, needs at least {min_rows}')
    return rows
