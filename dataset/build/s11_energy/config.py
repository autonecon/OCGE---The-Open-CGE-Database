"""S11 configuration, read strictly.

Every row of config/s11/s11_choices.csv must be a choice this code knows, with the value
the code implements (or, for a switchable rule in ALTERNATIVES, 'off'), a decided_by and a decided_at; every choice the code knows must be in
the file. A config table that is missing, empty or lacks a column stops the build. There is
no fallback copy of any file.
"""
import csv
import os

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BUILD, 'config', 's11')
CHOICES_PATH = os.path.join(CONFIG_DIR, 's11_choices.csv')
CHOICE_COLUMNS = ('choice', 'value', 'decided_by', 'decided_at', 'basis', 'gtap_status')
GTAP_STATUS = {'gtap', 'gtap_rule', 'not_in_gtap_text', 'departure_logged', 'n/a'}

# fix round w16 (GTAP 12 ch.12 §12.2.4): supply and measured use rescaled in opposite senses, jointly with world exports = imports
SUPPLY_USE_TWO_SIDED = 'two_sided_opposite_rescaling_measured_use_coa_oil_gas_joint_with_world_exports_eq_imports'
SUPPLY_USE_TWO_SIDED_OIL = 'two_sided_opposite_rescaling_measured_use_oil_only_joint_with_world_exports_eq_imports'
SUPPLY_USE_SURPLUS = 'opposite_rescaling_where_supply_exceeds_measured_use_coa_oil_gas_joint_with_world_exports_eq_imports'
# value -> (goods balanced, only regions whose supply exceeds measured use)
SUPPLY_USE_SCOPE = {SUPPLY_USE_TWO_SIDED: (('coa', 'oil', 'gas'), False), SUPPLY_USE_TWO_SIDED_OIL: (('oil',), False),
                    SUPPLY_USE_SURPLUS: (('coa', 'oil', 'gas'), True), 'off': ((), False)}

FUEL_SUBSIDIES_GAP_ROWS_ONLY = 'iea_price_gap_regions_at_reference_price_gap_booked_as_consumption_subsidy_s13_negative_purchase_tax'
# fix round w10 (David 2026-10-24 extension): every IEA row, the S11 price as the consumer price plus the IEA rate (kept for comparison)
FUEL_SUBSIDIES_ADD_ON_TOP = 'every_iea_subsidy_row_gap_rows_at_reference_others_at_consumer_price_plus_harmonised_iea_rate_s13_negative_purchase_tax'
# fix round wA (independent QA HIGH-1): every IEA row as a price gap, market price never above the reference
FUEL_SUBSIDIES_PRICE_GAP = ('every_iea_subsidy_row_as_a_price_gap_observed_price_plus_rate_else_reference_less_rate_rate_at_most_reference_'
                            'market_at_most_reference_s13_negative_purchase_tax')
ELY_REFERENCE_ADD_ON_TOP = 'iea_implied_consumer_price_plus_iea_rate_consumer_observed_else_2022_tariff_table_else_income_group_tariff_average'
# round 3 (final QA item 4): where no tariff is observed, the reference is the income-group average of the sourced tariffs
# (at least the IEA rate / 0.99, so the IEA money is kept) and the consumer price is reference - rate
ELY_REFERENCE = ('observed_or_sourced_tariff_plus_iea_rate_else_reference_at_income_group_tariff_average_'
                 'at_least_rate_over_0.99_consumer_reference_less_rate')
POWER_FUEL_CELLS = 'unsd_2022_siec46_power_burn_share_of_product_supply_of_listed_crude_users_on_s11_pet_domestic_sales_and_imports'
REFINERY_INTAKE_EI_FLOOR = 'ei_2022_refinery_throughput_where_energy_data_intake_below_70pct_of_ei_every_member_reported'
EI_INTAKE_FLOOR_SHARE = 0.70
S07_REEXPORT_HUBS = ('HKG', 'NLD', 'SGP')    # config/s07/trade_choices.csv reexport_hubs (F-07 report only)
POWER_FUEL_INPUTS = 'unsd_2022_088_burn_by_fuel_plus_gas_to_households_and_commerce_at_s11_prices_written_for_s13_ely_fuel_cells'
REGULATED_PRICE_FILL = ('gas_net_energy_exporters_with_iea_subsidy_consumer_observed_else_class_average_else_lowest_observed_market_consumer_plus_'
                        'iea_rate_capped_at_own_trade_price_only_where_consumer_stays_at_or_above_lowest_observed')
CRUDE_CELL_CAP = 'crude_part_of_listed_cell_at_most_value_share_unsd_crude_burn_at_s11_crude_price_vs_unsd_gas_burn_at_s11_gas_price'
# Fable QA D-02, D-04, C-03 (David 2026-10-25 "do all fixes")
REEXPORT_SAME_PROPENSITY = 'same_propensity_exports_and_imports_reduced_by_m_share'
REEXPORT_OBSERVED = 'comtrade_2022_rx_share_where_customs_report_reexports_else_same_propensity_same_volume_off_exports_and_imports'
EXPORT_TAX_HELD = 's10_subsidy_zero_checked_s10_export_tax_rate_held_on_s11_vfob'
EXPORT_TAX_BY_ROUTE = 's10_rate_by_route_eaeu_internal_exempt_line_rates_by_route_baci_line_mix_else_importer_mix_lng_at_lng_rate'
# beta v4 (2026-10-26; FIX_REGISTER P1, P6, P15)
ELY_TARGET = 'target_yes_electricity_at_s11_prices_after_the_ninety_rule_plus_network_gas_and_088_heat_share_resold_at_cost'
ELY_REPORT_ONLY = 'not_a_target_report_only'
# beta v4 P1 floor_only (David 2026-10-26 08:21 UTC): the S11 ely value only raises the S13 prior ely column (S13 target =
# max(prior column, S11 value)), so it adds output where the fuel bill needs it and never cuts it; the regions whose prior
# ely column is donor-scaled (S16 2026-10-26) take the S11 value
ELY_FLOOR = 'floor_only_s13_target_max_of_prior_ely_column_and_s11_value_after_the_ninety_rule_donor_scaled_regions_s11_value'
ELY_FLOOR_S11_VALUE_REGIONS = ('HND', 'ARM', 'SYR', 'YEM', 'PRK', 'SUR', 'NER')
# beta v4 P1 revised (S16 2026-10-26 08:33 UTC; David wants no distortion): the floor is the 90 percent rule as a minimum,
# max(prior ely column, (energy inputs + own use at S11 prices after the rule) / 0.9 + the pass-through resold at cost), so it
# does not depend on the (often class-average) electricity price; every region, the donor-scaled ones too
# S16 2026-10-26 (sector shocks item 4): the power industry's fuel bill and own use in the ely 90 percent rule and floor at
# purchaser prices, basic x (1 - the S11 IEA subsidy rate, at most S13's RHO_MAX 0.8); off: at basic prices
ELY_FUEL_PURCHASER = 'ely_rule_fuels_own_use_and_pass_through_at_basic_x_1_less_iea_subsidy_rate_at_most_0p8'
ELY_FUEL_RATE_CAP = 0.8
# S16 2026-10-26 (sector shocks item 4; David's card pending, S16 recommends on): the IEA electricity price gap is the IEA's
# estimate of the subsidy on fossil inputs to power, so the IEA ely subsidy is netted against the fuel subsidy booked on the
# power plants' burn (at most the smaller); off: both booked in full
ELY_SUBSIDY_NET = 'iea_ely_subsidy_less_iea_fuel_subsidy_on_the_088_power_burn_ely_share_rate_at_most_0p8_at_least_zero'
# beta v4 rescan N2 (S16 2026-10-26; labelled departure, not in the GTAP 12 text; David's call, default off): the floor_ninety
# floor sits at the 90 percent bound itself, so where it binds the power column keeps at most 10% of revenue for VA and its
# other inputs (UZB 3.4%, MDG 3.6%, MMR 4.1%, KWT 4.2% VA). When on, the floor rises toward the S11 value (generation x
# price, after the rule, plus pass-through) as far as a fuel share of ELY_FLOOR_HEADROOM_RATIO: floor = max(cost / 0.9 + pt,
# min(S11 value, cost / ratio + pt)). It never exceeds the S11 value and never falls below the 90 percent floor, so the
# regions whose tariff only just covers fuel (CYP, TLS, BFA, IRQ, SYR, YEM: raised by the rule) and hydro regions are unchanged
ELY_FLOOR_HEADROOM = 'floor_raised_toward_the_s11_value_up_to_a_fuel_share_of_0p8_never_above_the_s11_value'
ELY_FLOOR_HEADROOM_RATIO = 0.8
ELY_FLOOR90 = 'floor_ninety_s13_target_max_of_prior_ely_column_and_energy_inputs_plus_own_use_at_s11_prices_over_0_9_plus_pass_through'
NINETY_ELY = ('ely_in_the_rule_unsd_088_burn_times_electricity_share_of_8000t_7000t_output_energy_at_s11_prices_'
              'network_gas_and_heat_resold_at_cost_outside_the_rule')
NINETY_OWN_USE = 'unsd_2022_own_use_plus_losses_share_of_production_of_pet_and_ely_on_the_diagonal_at_the_domestic_price'
OWN_USE_SHARES_PET = 'unsd_2022_energy_industry_own_use_plus_losses_over_production_coa_oil_gas_pet_ely_median_of_reporters_fill'
OWN_USE_SHARES_V3 = 'unsd_2022_energy_industry_own_use_plus_losses_over_production_coa_oil_gas_ely_median_of_reporters_fill'
ELY_PRODUCTION_SUBSIDY = 'listed_2022_transfers_no_iea_ely_subsidy_at_most_the_ninety_rule_shortfall_s13_ely_output_subsidy'
ELY_SUBSIDY_COLUMNS = ('region', 'value_lcu_million', 'currency', 'fx_lcu_per_usd', 'value_usd_million', 'period', 'source', 'url', 'accessed',
                       'decided_by', 'decided_at', 'basis')
GAS_EXPORT_PARITY_CAP = 'regulated_gas_market_price_at_most_own_trade_price_observed_or_not_consumer_price_kept_rate_cut'
RAS_SEED_ROUTES = 'seed_only_routes_with_a_baci_hs17_flow_2017_2024_or_an_observed_route_release_rows_without_one_hard_gates'
ENERGY_ROUTE_OBSERVED = 'observed_pipeline_grid_routes_at_transaction_value_delivered_at_frontier_zero_margin_band_exempt_discount_reported'
ENERGY_ROUTE_COLUMNS = ('exporter', 'importer', 'commodity', 'volume', 'unit', 'price', 'price_unit', 'tier', 'price_basis', 'source',
                        'verified', 'decided_by', 'decided_at', 'basis')
RAS_GATE_MUSD = 100.0       # beta v4 P13: seeded routes and over-scaled priors above this value fail S11-Hseedgate / S11-Hscalegate
RAS_GATE_SCALE = 20.0
# beta v4 dry run on 165d46b (S11-Hseedgate, S11-Hscalegate, S11-Hras)
RAS_PRIOR_FLOOR_MUSD = 1.0   # a prior route below 1 USD m is customs noise: it enters as a seed (where feasible), not a prior
RAS_GATE_BASIS = 'share'     # S11-Hscalegate: the factor on the route's share of its importer's imports (method.route_gates)
ELY_GRID_MUSD = 10.0         # an off-grid BACI electricity route of at least 10 USD m in 2022 is kept (exchange-traded flows)
FEASIBLE_CUT_MAX = 0.02      # S11-Hfeascut: at most 2 percent of world trade volume of a good cut by the feasibility repair
ELY_GRID = 'grid_routes_land_borders_mledoze_countries_plus_listed_interconnectors_off_grid_baci_below_10musd_dropped'
FEASIBLE_VECTORS = 'max_flow_over_allowed_routes_prefer_data_routes_min_relative_cut_cut_to_absorption_forced_zero_routes_out'
RELABELLED = 'hub_prior_exports_above_own_volume_moved_to_listed_origins_by_unrecorded_export_volume_config_relabelled_routes'
ROUTE_REVIEW = 'reviewed_routes_feasible_block_accept_config_route_review'
GRID_COLUMNS = ('country_a', 'country_b', 'link', 'in_service_by_2022', 'decided_by', 'decided_at', 'basis')
RELABEL_COLUMNS = ('commodity', 'hub', 'destination', 'origins', 'decided_by', 'decided_at', 'basis')
REVIEW_COLUMNS = ('commodity', 'exporter', 'importer', 'action', 'prior_volume', 'decided_by', 'decided_at', 'basis')
REVIEW_ACTIONS = ('feasible', 'block', 'accept', 'only', 'hold', 'reference')  # beta v5 R: hold = fixed at its prior (or prior_volume); reference = priced at the exporter's reference
REEXPORT_NATIONAL = 'national_reexport_share_where_comtrade_has_no_rx_record_config_reexport_observed_national'
REEXPORT_NATIONAL_COLUMNS = ('region', 'commodity', 'share', 'source', 'url', 'decided_by', 'decided_at', 'basis')
GAS_LINE_MIX = 'at_reference_gas_exporters_route_price_eia_pipeline_and_lng_prices_by_baci_271121_271111_split'
# beta v4 P2 and P16 (David's calls, default off): domestic_price_sources.csv rows that apply only where their choice is on
ZAF_POWER_COAL = 'zaf_coal_basic_price_at_eskom_2022_primary_energy_coal_cost_per_tonne_burned_transcribed'
PRK_COAL = 'prk_coal_basic_price_at_the_nbs_2022_china_mine_unit_value_instead_of_the_class_average_fill'
# beta v4 G9 (Grok QA B8; decision package): CHN gas at the NBS 2022 oil and gas extraction revenue less crude, per kcm
CHN_GAS = 'chn_gas_basic_price_at_nbs_2022_oil_and_gas_extraction_revenue_less_crude_at_s11_price_over_nbs_gas_output'
# beta v4 G13 (decision package 15; fallback only, default off): energy route export-tax rates of the listed exporters
# scaled so that their energy export tax equals the collected duty of export_duty_collected_2022.csv
EXPORT_DUTY_COLLECTED = 'route_export_tax_rates_of_listed_exporters_scaled_to_collected_energy_export_duty_rate_cap_0p99'
EXPORT_DUTY_COLUMNS = ('region', 'collected_musd', 'source', 'url', 'decided_by', 'decided_at', 'basis')
EXPORT_DUTY_RATE_CAP = 0.99
EXPORT_DUTY_TOL = 0.05
# beta v4 dry run (S11-H90 on AFG and PAL ely) and Grok QA R2 (IRQ share 0.721): losses out of the ely own-use share
ELY_LOSSES_OUT = 'ely_own_use_share_without_distribution_losses_gtap12_table_12_3_special_treatment'
ELY_LOSSES_SPLIT = 'unsd_2022_ely_losses_times_production_over_production_plus_imports'
# beta v4 rescan N1 (S16 2026-10-26): the reexport_observed_national.csv rows behind their own switch
AUS_GAS_PROCESSING = 'aus_gas_imports_are_tls_bayu_undan_feed_gas_liquefied_at_darwin_re_export_share_0'
SWITCHED_RX_NATIONAL = {('AUS', 'gas'): 'aus_gas_processing'}
SWITCHED_PRICE_SOURCES = {('coa', 'ZAF'): 'zaf_power_coal_price', ('coa', 'PRK'): 'prk_coal_price', ('gas', 'CHN'): 'chn_gas_price'}
# beta v4 G10 (Grok QA B5; David 2026-10-26 08:15 UTC "fix those"): sourced 2022 industrial electricity prices for the
# regions that copied the US price through the GTAP 12 §12.3.6 class fill (rows marked used); the rest keep the class fill
ELY_CLASS_SOURCED = 'listed_used_2022_ely_prices_config_s11_ely_industrial_prices_2022_ahead_of_the_class_fill'
ELY_CLASS_COLUMNS = ('region', 'value', 'unit', 'fx_iso3', 'measure', 'used', 'source', 'url', 'accessed', 'confidence', 'decided_by', 'decided_at', 'basis')
# beta v4 P41 (David 2026-10-26 08:15 UTC): TTO gas exports at TTO's own customs FOB unit value instead of the importers' CIF mirror
GAS_REPORTER_FOB = 'listed_exporters_gas_reference_price_own_comtrade_2022_fob_value_over_net_weight_lng_1.36_bcm_per_mt'
GAS_REPORTER_HH = 'listed_exporters_gas_reference_price_ei_2022_henry_hub'
GAS_REPORTER_METHOD = 'reporter_comtrade_fob_unit_value'
GAS_LINE_COLUMNS = ('exporter', 'pipeline_price', 'lng_price', 'price_unit', 'source', 'url', 'decided_by', 'decided_at', 'basis')

# beta v5 (David 2026-10-27 08:39 UTC, decision package v2 approved as recommended)
# E1 + R: RAS with route bounds; oil and pet prior routes at most CAP_FACTOR x prior (or RAS_GATE_MUSD), a route with a
# mirror-only partner at most RAS_GATE_SCALE x prior, unless observed, reviewed, relabelled or grid
RAS_ROUTE_CAPS = 'oil_pet_prior_routes_at_most_3x_or_100musd_mirror_only_partner_routes_at_most_20x_capped_ras'
CAP_GOODS = ('oil', 'pet')
CAP_FACTOR = 3.0
# E3: electricity only on grid routes at any size; listed gas exporters only on their pipelines
PHYSICAL_ROUTES = 'ely_grid_routes_only_at_any_size_and_listed_pipeline_only_gas_exporters_config_gas_pipeline_only'
PIPELINE_ONLY_COLUMNS = ('exporter', 'commodity', 'importers', 'decided_by', 'decided_at', 'basis')
# E4: listed gas users with no gas use in the energy balance; their io_s11 gas cells go pro rata to the other industries
GAS_USERS_EXCLUDED = 'listed_users_gas_cells_moved_pro_rata_to_other_industries_config_energy_user_exclusions'
USER_EXCLUSION_COLUMNS = ('region', 'commodity', 'users', 'decided_by', 'decided_at', 'basis')
# A: the regulated-row cap of a net importer values its contract routes at the exporter's reference price
CONTRACT_PARITY = 'contract_routes_at_exporter_reference_price_in_the_net_importer_regulated_cap'
CONTRACT_PRICE_SHARE = 1.0 / 3.0         # an observed route priced below this share of the exporter's reference is a contract
# E2: US LNG import routes held at the US Census IMDB 2022 customs value
CENSUS_ROUTE_HOLD = 'listed_us_import_routes_held_at_census_imdb_2022_customs_value_config_census_route_hold'
CENSUS_HOLD_COLUMNS = ('exporter', 'importer', 'commodity', 'census_cty', 'hs_lines', 'decided_by', 'decided_at', 'basis')
# I: listed cells take the same-propensity re-export rule of §12.2.5 in place of their Comtrade RX share
RX_RULE_OVERRIDE = 'listed_cells_same_propensity_reexport_rule_config_reexport_rule_override'
RX_OVERRIDE_COLUMNS = ('region', 'commodity', 'rule', 'decided_by', 'decided_at', 'basis')
# N2: NGPL booked to pet gets a gas feedstock purchase where it is a large part of pet output
NGPL_FEEDSTOCK = 'ngpl_at_least_30pct_of_pet_output_value_gas_feedstock_eia_ngpl_energy_at_region_gas_prices'
NGPL_FEEDSTOCK_VALUE_SHARE = 'ngpl_at_least_30pct_of_pet_output_value_gas_feedstock_of_85pct_of_ngpl_value_in_refinery_gas'
NGPL_FEED_MIN_SHARE = 0.30
NGPL_FEED_SHARE = 0.85                    # NGPL_FEEDSTOCK_VALUE_SHARE only: the rest is the fractionation margin
GJ_PER_MMBTU = 1.055056
# E7 / E8: sourced rows, off until David's agent supplies the source (the code refuses an on switch without the row)
DZA_GAS_CREG = 'dza_gas_price_creg_2022_tariff_transcribed_item_dza_gas_creg_2022'
CHN_ELY_OWN_USE_CEC = 'chn_ely_own_use_share_cec_2022_config_own_use_overrides'
OWN_USE_OVERRIDE_COLUMNS = ('region', 'commodity', 'own_use_share', 'switch', 'source', 'decided_by', 'decided_at', 'basis')
# beta v5 E7: a price row that replaces the region's other row of the same commodity when its switch is on
SWITCHED_PRICE_REPLACEMENTS = {('gas', 'DZA', 'item:dza_gas_creg_2022'): 'dza_gas_price_creg'}

# choice -> the value this code implements
CHOICES = {
    'energy_volume_source': 'prep_energy_volumes_eia_intl_jodi_unsd',
    'tkm_gas_prep_h10': 'accepted_tkm_9.5pct_vs_ei_eia_kept',
    'electricity_basis': 'eia_net_generation',
    'crude_use': 'refinery_intake_plus_direct_use',
    'ngl_to_pet': 'ngpl_out_of_oil_and_gas_into_pet_output',
    'afg_gas': 'blank_flagged',
    'crude_price': 'ei_2022_marker_by_exporter_dubai_wti_forcados_brent',
    'product_price': 'ei_regional_marker_plus_ei_regional_refining_margin',
    'energy_trade_scope': 'all_regions_all_energy_ras_to_volume_vectors',
    'energy_output_scope': 'coa_oil_gas_pet_volume_times_basic_price_all_regions',
    'ely_output_value': ELY_FLOOR90,
    'trade_volume_fill': 'unsd_2022_crude_4100_products_siec46_tonnes_to_bbl_ei_factors',
    'trade_volume_last_resort': 'zero_flagged_s10_value_not_used',
    'supply_use_balance': 'opposite_rescaling_where_exports_exceed_production_plus_imports_and_with_world_balance',
    'energy_supply_use_balance': SUPPLY_USE_TWO_SIDED,
    'reexport_removal': REEXPORT_OBSERVED,
    'volume_balance': 'opposite_rescaling_world_exports_eq_world_imports_geometric',
    'gas_price': 'exporter_baci_2022_unit_value_gas_lines_1.36_bcm_per_mt',
    'gas_price_estimated_tonnes': 'baci_value_over_observed_volume_config_s11_gas_export_price_observed_csv',
    'export_price_by_route': 'baci_2022_route_unit_value_within_one_third_to_three_times_exporter_reference_else_reference_estimated_tonnes_exporters_at_reference',
    'gas_route_volume_observed': 'baci_route_value_over_baci_lng_tonnes_plus_ei_2022_pipeline_route_volume_config_s11_gas_route_volume_observed_csv',
    'gas_import_origin': 'eurostat_nrg_ti_gas_2022_named_partners_nsp_shared_by_partner_reported_mirror_excess_config_s11_gas_import_origin_csv',
    'coal_price': 'exporter_baci_2022_unit_value_s01_coa_lines',
    'ely_price': 'exporter_baci_hs271600_value_over_eia_export_twh',
    'price_missing': 'simple_average_of_available_exporters',
    'ras_seed': '1e-6_x_exporter_volume_x_importer_import_share_offdiagonal',
    'ei_bilateral_supplement': 'not_used_ei_2025_edition_has_2024_bilateral_only',
    'ely_trade_source': 'baci_hs271600_2022_fob_s01_map_single_country_diagonals_dropped',
    'ely_margins': 'zero',
    'ely_tariffs': 'zero_s10_did_not_price_hs271600_flagged',
    'travel_energy': 'travel_s09_outside_ras_s13_merges',
    'cif_after_override': 's08_pair_margin_rate_on_new_fob_mode_mix_kept_vst_rescaled',
    'duty_after_override': 's10_tm_on_new_cif_new_pairs_union_zero_else_importer_mfn',
    'export_tax_after_override': EXPORT_TAX_BY_ROUTE,
    'volume_units': 'natural_units_and_mtoe_ei_factors',
    'agent_use_volumes': 'not_built_no_balances',
    'basic_price': 'source_data_then_iea_price_gap_then_import_basic_price_then_simple_average',
    'purchasers_vs_import_price': 'import_basic_price_ahead_of_purchasers_price_for_gas_hub_and_mine_prices_keep_place_electricity_on_eurostat',
    'domestic_price_sources': 'ei_gas_hubs_usa_gbr_eurostat_x_tax_medium_bands_eia_us_coal_and_industrial_electricity',
    'domestic_price_source_canada': 'aer_st98_aeco_c_2022_hub_basic_price_wdi_cad',
    'domestic_price_source_us_petroleum': 'eia_2022_us_spot_products_weighted_by_refinery_output',
    'iea_gap_in_fill_averages': 'excluded_class_averages_use_observed_prices_only',
    'refinery_crude_intake_cap': 'jodi_refinobs_else_eia_consumption_else_unsd_4100_086_capped_at_s11_crude_supply',
    'crude_marker_map': 'config_s11_crude_markers_csv',
    'product_hub_map': 'config_s11_product_hubs_csv',
    'energy_volume_prep_rerun': 'prep_energy_volumes_rerun_on_s01_5ddbe4d_stamped_upstream',
    'china_coal_price': 'observed_2022_average_ahead_of_import_price_ndrc_range_not_used',
    'iea_price_gap': 'trade_parity_price_less_iea_2022_subsidy_per_unit_of_consumption_real2024_deflated_by_us_gdp_deflator',
    'iea_gap_reference': 'own_export_price_net_exporters_import_basic_price_net_importers_simple_average_export_price_no_trade_gap_ge_reference_not_used',
    'purchasers_to_basic': 'gtap_eq2_tax_zero_table_12_8_industrial_margin_gas_1.30_ely_0',
    'domestic_price_fill': 'gtap_12_3_6_four_classes_net_energy_exporter_importer_by_price_level_then_simple_average',
    'output_value': 'exports_at_export_price_plus_domestic_sales_at_basic_price',
    'ngpl_value': 'ngpl_volume_x_eia_mont_belvieu_propane_2022',
    'ninety_pct_rule': 'energy_inputs_le_90pct_revenue_raise_output_and_lower_domestic_input_prices_min_value_weighted_change_io_price_model',
    'smearing': 'not_applied_s13_reports_zero_share_cells',
    'b06_split': 'gas_to_pet_sized_by_refinery_gas_crude_only_to_refining_listed_direct_users_and_exports_rest_of_row_to_gas_columns_by_row_totals',
    'refinery_gas': 'unsd_2022_3000_0925_plus_086_at_s11_gas_prices_else_simple_average_tj_per_million_bbl_pet',
    'energy_taxes': 'none_beyond_io_s10',
    'fuel_subsidies': FUEL_SUBSIDIES_PRICE_GAP,
    'fuel_subsidy_unobserved_price': 'unobserved_s11_price_is_unsubsidised_market_at_reference_consumer_reference_less_rate',
    'fuel_subsidy_rate_cap': 'traded_fuels_rate_at_most_reference_99pct_on_unobserved_prices_observed_rows_at_most_reference_less_observed_price',
    'iea_reference_ely': ELY_REFERENCE_ADD_ON_TOP,
    'crude_direct_cell_cap': CRUDE_CELL_CAP,
    # round 3 (final QA 2 item 3): the refined fuel burnt by the listed crude users' power plants, for S13's power cell targets
    'power_fuel_cell_values': POWER_FUEL_CELLS,
    'bunkers': 'not_recorded_baci_basis',
    'volume_gate': 'e6_pm8pct_top15_gas_named_exceptions',
    'screen_materiality': '0.1bn_or_1pct_of_region_energy_trade',
    'domestic_price_transcribed': 'config_s11_transcribed_prices_2022_csv_ahead_of_the_class_average',
    'lignite_price': 'unsd_brown_coal_share_of_output_at_eia_acr_2022_us_lignite_mine_price',
    'exporter_price_cap': 'net_exporter_domestic_price_at_most_own_export_price_coa_oil_gas_pet',
    'energy_use_caps': 'refinery_crude_intake_value_and_unsd_gas_own_use_share_written_for_s13',
    # fix round wG (QA round 2 P5): own use + losses of coa, oil, gas, ely by their own industry, UNSD 2022, for S13's diagonal caps
    'own_use_shares': OWN_USE_SHARES_PET,
    'vpv_source_check': 'oil_pet_export_price_against_baci_2022_unit_value_coal_gas_against_ei_markers',
    # Fable QA D-06 (2026-10-25): the ely column's fuels from the UNSD balance at S11 prices, for S13's ely fuel cells
    'power_fuel_inputs': POWER_FUEL_INPUTS,
    # Fable QA C-02/B-03: a subsidising net exporter with no observed regulated price takes the class average of those prices
    'regulated_price_fill': REGULATED_PRICE_FILL,
    'refinery_intake_ei_floor': REFINERY_INTAKE_EI_FLOOR,
    # beta v4 P1 and P15 (GTAP 12 ch.12 §12.4.3): electricity and own use in the 90 percent rule
    'ninety_pct_ely': NINETY_ELY,
    'ninety_pct_own_use': NINETY_OWN_USE,
    # beta v4 P6 (David's call, default off): regulated gas rows capped at the own trade price
    'gas_export_parity_cap': GAS_EXPORT_PARITY_CAP,
    # beta v4 P4 (David's call, default off): a documented transfer to the power utilities as an ely production subsidy
    'ely_production_subsidy': ELY_PRODUCTION_SUBSIDY,
    # beta v4 P13: the RAS seeds only routes that carried the good in BACI 2017-2024 (or an observed route), with hard gates
    'ras_seed_routes': RAS_SEED_ROUTES,
    # beta v4 P13 (David approved 2026-10-26 03:45 UTC): observed pipeline and grid routes at their transaction value
    'energy_route_observed': ENERGY_ROUTE_OBSERVED,
    # beta v4 P14: a crude producer with no refinery has measured crude use 0; last-resort export volume from S10 VFOB
    'no_refinery_crude_use': 'zero_measured_crude_use_where_no_refinery_last_resort_export_volume_from_s10_vfob',
    # beta v4 P24: the D-04 observed re-export override extended to CAN (StatCan) and MEX (zero, labelled)
    'reexport_observed_national': REEXPORT_NATIONAL,
    # beta v4 P25: at-reference gas exporters priced by route line mix (EIA pipeline and LNG prices x BACI split)
    'gas_line_mix_price': GAS_LINE_MIX,
    # beta v4 P2 and P16 (David's calls, default off): ZAF coal at Eskom's cost, PRK coal at the China mine price
    'zaf_power_coal_price': ZAF_POWER_COAL,
    'prk_coal_price': PRK_COAL,
    'chn_gas_price': CHN_GAS,
    'export_duty_to_collected': EXPORT_DUTY_COLLECTED,
    'ely_fuel_purchaser_price': ELY_FUEL_PURCHASER,
    'ely_subsidy_net_power_fuel': ELY_SUBSIDY_NET,
    'aus_gas_processing': AUS_GAS_PROCESSING,
    'ely_floor_headroom': ELY_FLOOR_HEADROOM,
    # beta v4 dry run: the power industry carries only the grid losses on its own output, not on imported power
    'ely_losses_in_own_use': ELY_LOSSES_OUT,
    # beta v4 dry run (S11-Hras, S11-Hseedgate, S11-Hscalegate on 165d46b): grid-only electricity routes, the feasibility
    # repair before the RAS, relabelled crude, and the reviewed route list
    'ely_grid_routes': ELY_GRID,
    'ras_feasible_vectors': FEASIBLE_VECTORS,
    'relabelled_origin': RELABELLED,
    'route_review': ROUTE_REVIEW,
    # beta v4 G10 and P41 (David 2026-10-26 08:15 UTC)
    'ely_class_price': ELY_CLASS_SOURCED,
    'gas_reporter_fob': GAS_REPORTER_FOB,
    # beta v5 (David 2026-10-27 08:39 UTC package approval)
    'ras_route_caps': RAS_ROUTE_CAPS,
    'physical_energy_routes': PHYSICAL_ROUTES,
    'gas_users_excluded': GAS_USERS_EXCLUDED,
    'contract_routes_out_of_parity_cap': CONTRACT_PARITY,
    'census_route_hold': CENSUS_ROUTE_HOLD,
    'reexport_rule_override': RX_RULE_OVERRIDE,
    'ngpl_feedstock': NGPL_FEEDSTOCK,
    'dza_gas_price_creg': DZA_GAS_CREG,
    'chn_ely_own_use_cec': CHN_ELY_OWN_USE_CEC,
}
# choices that can be switched off from s11_choices.csv (David's card of 2026-10-24 on the A9 rules is pending):
# the value must be the implemented one or one of these alternatives
ALTERNATIVES = {
    'reexport_observed_national': ('off',),
    'gas_line_mix_price': ('off',),
    'no_refinery_crude_use': ('off',),
    'ras_seed_routes': ('off',),
    'energy_route_observed': ('off',),
    'lignite_price': ('off',),
    'exporter_price_cap': ('off',),
    # fix round wA: the w10 add-on-top rule; the B15 rule of w8 (IEA price-gap rows only, before David's 2026-10-24 extension); off: the pre-B15 rule (the IEA gap
    # lowers the basic price, nothing booked)
    'fuel_subsidies': (FUEL_SUBSIDIES_ADD_ON_TOP, FUEL_SUBSIDIES_GAP_ROWS_ONLY, 'off'),
    # fix round w16: crude only; only where supply exceeds measured use (USA-type use > supply left to the A10 cap); or off
    # (the rule before w16: only exports above production plus imports move)
    'energy_supply_use_balance': (SUPPLY_USE_TWO_SIDED_OIL, SUPPLY_USE_SURPLUS, 'off'),
    # round 3 (final QA item 4): the wA2 rule, an unobserved tariff as the consumer price with the IEA rate on top
    'iea_reference_ely': (ELY_REFERENCE,),
    # round 3 (final QA item 2): off = the A8 rule, the crude part of a listed cell capped by its row share alone
    'crude_direct_cell_cap': ('off',),
    # round 3 (final QA 2 item 3): off = no refined-fuel burn in crude_cell_split_s11.csv (S13 then holds crude and gas only)
    'power_fuel_cell_values': ('off',),
    # Fable QA C-02: off = the fix round wA rule, an unobserved price is unsubsidised (market at the trade-parity reference)
    'regulated_price_fill': ('off',),
    'refinery_intake_ei_floor': ('off',),
    # Fable QA D-02, D-04, C-03: the rules before (one exporter price on every route; BACI mirror seed; same propensity
    # everywhere; the S10 exporter rate on every route)
    'export_price_by_route': ('off',),
    'gas_import_origin': ('off',),
    'reexport_removal': (REEXPORT_SAME_PROPENSITY,),
    'export_tax_after_override': (EXPORT_TAX_HELD,),
    # beta v4: the beta v3 rules (ely report only; no ely and no own use in the 90 percent rule; no pet own-use share;
    # regulated gas rows uncapped where PM0 is observed)
    'ely_output_value': (ELY_FLOOR, ELY_TARGET, ELY_REPORT_ONLY),   # price-based floor; P1 as first coded (S11 value held); beta v3
    'ninety_pct_ely': ('off',),
    'ninety_pct_own_use': ('off',),
    'own_use_shares': (OWN_USE_SHARES_V3,),
    'gas_export_parity_cap': ('off',),
    'ely_production_subsidy': ('off',),
    'zaf_power_coal_price': ('off',),
    'prk_coal_price': ('off',),
    'chn_gas_price': ('off',),
    'export_duty_to_collected': ('off',),
    'ely_fuel_purchaser_price': ('off',),
    'ely_subsidy_net_power_fuel': ('off',),
    'aus_gas_processing': ('off',),
    'ely_floor_headroom': ('off',),
    'ely_losses_in_own_use': (ELY_LOSSES_SPLIT, 'off'),
    'ely_grid_routes': ('off',),
    'ras_feasible_vectors': ('off',),
    'relabelled_origin': ('off',),
    'route_review': ('off',),
    'ely_class_price': ('off',),
    'gas_reporter_fob': (GAS_REPORTER_HH, 'off'),
    'ras_route_caps': ('off',),
    'physical_energy_routes': ('off',),
    'gas_users_excluded': ('off',),
    'contract_routes_out_of_parity_cap': ('off',),
    'census_route_hold': ('off',),
    'reexport_rule_override': ('off',),
    'ngpl_feedstock': (NGPL_FEEDSTOCK_VALUE_SHARE, 'off'),
    'dza_gas_price_creg': ('off',),
    'chn_ely_own_use_cec': ('off',),
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
        if r['value'] != CHOICES[c] and r['value'] not in ALTERNATIVES.get(c, ()):
            bad.append(f'{c}: value {r["value"]!r} is not the implemented {CHOICES[c]!r}')
        if not r['decided_by'].strip() or not r['decided_at'].strip():
            bad.append(f'{c}: decided_by or decided_at is blank')
        if r['gtap_status'] not in GTAP_STATUS:
            bad.append(f'{c}: gtap_status {r["gtap_status"]!r}')
    bad += [f'{c}: row missing' for c in CHOICES if c not in seen]
    if bad:
        raise ConfigError(f'{path}: ' + '; '.join(bad))
    return seen


def switched_on(choices, name):
    """True where a switchable choice carries its implemented value, False where it is set to 'off'."""
    return choices[name]['value'] == CHOICES[name]


def price_source_rows(rows, choices):
    """Beta v4 P2/P16: drop the domestic_price_sources.csv rows whose switch (SWITCHED_PRICE_SOURCES) is off."""
    keep = [h for h in rows if (h['commodity'], h['region']) not in SWITCHED_PRICE_SOURCES
            or switched_on(choices, SWITCHED_PRICE_SOURCES[(h['commodity'], h['region'])])]
    # beta v5 E7: a replacement row is dropped while its switch is off, and replaces its region's other row when on
    out = []
    for h in keep:
        key = (h['commodity'], h['region'], h.get('series', ''))
        if key in SWITCHED_PRICE_REPLACEMENTS:
            if switched_on(choices, SWITCHED_PRICE_REPLACEMENTS[key]):
                out.append(h)
            continue
        if any(k[:2] == key[:2] and switched_on(choices, sw) for k, sw in SWITCHED_PRICE_REPLACEMENTS.items()):
            continue
        out.append(h)
    return out


def read_table(name, columns):
    """Read config/s11/<name>; stop if it is missing, empty, or lacks a column or an attribution."""
    path = os.path.join(CONFIG_DIR, name)
    if not os.path.exists(path):
        raise ConfigError(f'{path} is missing')
    with open(path, newline='') as fh:
        rd = csv.DictReader(fh)
        missing = [c for c in columns if c not in (rd.fieldnames or ())]
        rows = list(rd)
    if missing or not rows:
        raise ConfigError(f'{path}: missing columns {missing} or no rows')
    for r in rows:
        if 'decided_by' in r and (not r['decided_by'].strip() or not r['decided_at'].strip()):
            raise ConfigError(f'{path}: row {r} has no decided_by or decided_at')
    return rows
