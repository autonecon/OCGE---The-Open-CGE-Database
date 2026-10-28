"""S13 configuration, read strictly (the S11 pattern).

Every row of config/s13/s13_choices.csv must be a choice this code knows, with the value the code
implements, a decided_by and a decided_at; every choice the code knows must be in the file. A config
table that is missing, empty or lacks a column stops the build. There is no fallback copy of any file.
"""
import csv
import os

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BUILD, 'config', 's13')
CHOICES_PATH = os.path.join(CONFIG_DIR, 's13_choices.csv')
CHOICE_COLUMNS = ('choice', 'value', 'decided_by', 'decided_at', 'basis', 'gtap_status')
GTAP_STATUS = {'gtap', 'gtap_rule', 'not_in_gtap_text', 'departure_logged', 'n/a'}

# choice -> the values this code implements (the first is the default; a choice with two values is a switch)
TINY_ENERGY = 'target_below_10_musd_and_2pct_of_output_plus_imports_or_below_1_musd_exports_at_most_1k_usd_target_falls_to_exports'   # beta v4 P38
EXCISE_AT_SOURCE = 'fbt_excise_at_source_revenue_vat_seed_scaled_to_column_general_part_less_excise'   # beta v4 G16 (method.EXCISE_AT_SOURCE)
VAT_EXEMPTIONS = 'listed_exempt_rows_no_vat_on_households_and_government_rate_on_the_rest_keeps_g114_less_g1142'   # beta v5 V
OWN_USE_LISTED = 'listed_non_energy_diagonals_at_most_the_listed_share_of_output_domestic_excess_netted_out_of_row_and_column'   # beta v5 N1
OWN_USE_LISTED_PATH = os.path.join(CONFIG_DIR, 'own_use_cap_listed.csv')
OWN_USE_LISTED_COLUMNS = ('region', 'commodity', 'own_use_share', 'source', 'decided_by', 'decided_at', 'basis')
ELY_SUB_TARIFF = 'tariff_level_hold_ely_subsidy_rate_at_most_0p5_of_basic_value_excess_not_booked'   # beta v5.5
CHOICES = {
    'objective': ('gtap_eq17_1_plus_17_2_unit_weights_as_column_share_cross_entropy',),
    'solver': ('newton_gtap_17_41_17_46_free_outputs_from_market_clearing',),
    'tolerance': ('1e-9_relative_on_every_held_row',),
    'macro_scale': ('one_factor_on_s02_c_g_gfcf_gdp_equals_s02_with_trade_fixed',),
    'macro_gate': ('factor_positive_hard_band_10pct_report',),
    'trade_held': ('vxsb_goods_s10_energy_s11_services_and_travel_s09_vmsb_same_vst_s11',),
    'b06_travel_split': ('host_household_oil_gas_shares_else_s11_output_targets',),
    'energy_travel': ('within_s11_output_less_exports_excess_dropped_ledgered',),
    # beta v4 P1: electricity's S11 output value is held too where S11 sets it (s11 choice ely_output_value)
    'energy_targets': ('every_s11_target_yes_row_coa_oil_gas_pet_and_ely_where_s11_sets_it', 's11_output_values_coa_oil_gas_pet_target_yes'),
    'tax_rates': ('energy_rows_at_gtap_ad_valorem_rates_held_general_rate_column_remainder_not_below_min_io_rate_0',
                  'energy_rows_at_ad_valorem_rates_capped_at_column_tls_column_total_fixed',
                  'energy_rows_at_ad_valorem_rates_plus_io_column_rate_on_every_row',
                  'one_net_product_tax_power_per_column_dom_and_imp_held'),
    'non_energy_rates': ('s10_product_tax_layers_ras_to_the_column_general_part', 'one_general_rate_per_column'),
    # beta v4 G16 (Grok QA A7): the households' fbt excise stays at its source revenue; only the VAT seed is scaled
    'excise_at_source': (EXCISE_AT_SOURCE, 'off'),
    # beta v4 P38 (S16 country stress CS-5, CS-9): an S11 energy activity this small, with no exports, is shut (method.tiny_energy)
    'tiny_energy_activity': ('off', TINY_ENERGY),
    'farm_support': ('pse_output_and_input_as_fixed_rates_on_crp',),
    'factor_composition': ('s12_evfp_shares_within_va_taxes_scaled_with_evfp',),
    'new_activity_factors': ('world_s12_composition_of_the_sector_region_average_factor_tax_rates',),
    'stock_change': ('removed_absorbed_by_fit',),
    'grev_gap': ('removed_absorbed_by_fit',),
    'dpabr': ('residents_purchases_abroad_join_households',),
    'negative_cells': ('negative_purchases_set_to_zero_ledgered',),
    'negative_va': ('held_fixed_in_the_fit',),
    'prior_without_va': ('representative_column_when_needed', 'keep_prior_column'),
    'zero_output_column': ('s03_representative_table_column',),
    'shut_activity': ('zero_target_or_no_output_and_no_exports_shut_row_and_column',),
    'all_exported_energy': ('target_equal_to_exports_no_domestic_sales',),
    'zero_imports': ('import_row_removed_where_held_imports_zero',),
    'import_no_buyer': ('smear_1_32_from_domestic_purchases_else_households',),
    'domestic_no_buyer': ('smear_1_32_from_imported_purchases_excluding_own_use_else_households',),
    'energy_smear': ('31_32_own_row_1_32_world_io_structure_activities_and_households',),
    'gov_inv_energy': ('removed_ch17a_footnote_4',),
    'row_block': ('icio_row_total_report_only',),
    'icio_gate': ('report_total_absolute_change_over_intermediate_use_2pct_band',),
    'benchmark': ('gtap10_only',),
    'screen_outliers': ('explanation_row_required', 'report_only'),
    # fix round 2026-10-24 (s13_fit/energy.py)
    'energy_use_caps': ('refinery_crude_at_s11_measured_intake_gas_own_use_at_unsd_share_excess_to_other_buyers', 'off'),
    'energy_import_shares': ('import_proportionality_energy_goods_after_fit', 'icio_agent_split'),
    # fix round B15 (David's card 2026-10-24): fossil-fuel consumption subsidies as GTAP books them
    'fuel_subsidies': ('iea_price_gap_subsidy_negative_purchase_tax_firms_households_government_purchasers_value_kept', 'off'),
    # fix round wC (independent QA MEDIUM-3): own-use (diagonal) shares move by GTAP's cross-entropy like every other
    # cost share; the alternatives hold them at the prior share (fit.Column share groups) and are not GTAP
    'own_use_share': ('cross_entropy_free', 'energy_activities_own_use_share_held_at_prior', 'every_activity_own_use_share_held_at_prior'),
    'fuel_subsidy_neer_overlap': ('iea_subsidy_net_of_the_neer_subsidy_on_the_row', 'iea_subsidy_in_full_overlap_reported'),
    # independent QA (fix round): GTAP 12 ch.15 sets the income and factor taxes in money (revenue / GDP x GDP)
    'factor_tax_totals': ('s12_money_held_by_region_and_factor', 's12_rates_on_fitted_evfp'),
    # fix round wG (QA round 2 P5): energy diagonals at most the S11 UNSD own use + losses share of output
    # beta v4 P15: the refinery's (pet) diagonal too
    'own_use_cap': ('unsd_own_use_plus_losses_share_of_output_coa_oil_gas_pet_ely_excess_to_other_buyers_ely_netted',
                    'unsd_own_use_plus_losses_share_of_output_coa_oil_gas_ely_excess_to_other_buyers_ely_netted', 'off'),
    # fix round wG (QA round 2 P7): PSE B1 variable-input payments on the input they pay for (config/s13/pse_input_items_2022.csv)
    # round-3 QA item 9: the remainder on the OECD B1 rows of the region (config/s13/pse_input_remainder_2022.csv), else every input
    'pse_input_items': ('listed_items_on_their_row_remainder_on_the_listed_b1_rows_else_pro_rata_on_every_crp_input_purchasers_value_kept',
                        'listed_pse_input_items_on_their_row_purchasers_value_kept_remainder_pro_rata_on_every_crp_input', 'off'),
    # round-3 QA item 3: the general part of each column's product tax held in money through the fit (method.hold_product_taxes)
    'product_tax_totals': ('general_part_money_held_by_column_rates_rescaled_after_each_fit_pass', 'cell_rates_held_revenue_moves_with_the_fit'),
    # round-3 final QA item 4: the subsidy on a good S11 does not hold (electricity) held in money at the S11 amount through the fit
    'electricity_subsidy_money': ('s11_money_held_through_the_fit_rate_reset_after_each_pass', 'prior_rate_moves_with_the_fit'),
    # round-3 final QA2 item 1: representative-table regions' product-tax money from IMF GFS G114, not the donor's money (s13_fit/ptax_source.py)
    # round-3 final QA2 item 6: the IEA electricity subsidy on crp's ely cell and the PSE electricity item are one support
    'pse_iea_overlap': ('pse_ely_remainder_netted_against_the_whole_iea_electricity_subsidy_at_most_the_smaller',   # beta v4 G11
                        'farm_part_of_the_iea_electricity_subsidy_netted_off_the_pse_ely_remainder', 'reported_not_netted'),
    'product_tax_source': ('representative_table_regions_imf_gfs_g114_less_energy_excise_else_rates_held', 'io_s12_money_every_region'),
    # round 3 final QA 2 item 2: the IEA consumption subsidy on final consumption and non-energy users only (money held)
    'fuel_subsidy_users': ('final_consumption_and_non_energy_users_energy_industry_own_use_and_transformation_excluded_money_held',
                           'every_firm_household_government'),
    # round 3 final QA 2 item 2: the own-use cap measured on the diagonal's basic value
    'own_use_cap_valuation': ('basic_value_of_the_diagonal_over_output', 'purchasers_value_share_of_column'),
    # round 3 final QA 2 item 3: the crude-burning power columns' crude, gas and pet cells held at the S11 values
    'power_fuel_cells': ('s11_power_fuel_values_coal_crude_gas_pet_held_as_cell_targets_of_every_power_column',
                         's11_unsd_crude_gas_pet_burn_values_held_as_cell_targets_of_crude_burning_power_columns', 'off'),
    # round 3 final QA 2 item 5: crude smear structure and no-buyer fills on the crude users only
    'crude_smear_users': ('crude_only_to_refining_own_use_and_listed_direct_users_other_b06_weight_to_refining_no_buyer_fill_on_refining',
                          'b06_row_every_buyer'),
    # fix round S16 (Fable QA C-01, C-02, F-01, F-02): the held energy rows split across their users at the prior shares
    'energy_user_cells': ('held_at_prior_user_shares_refining_and_power_free_else_free_fit_flagged', 'off'),
    # fix round S16 (Fable QA C-02, B-03): the fuel subsidy rate capped at 0.8 (power floor 0.2)
    'fuel_subsidy_rate_cap': ('rate_at_most_0p8_of_basic_value_excess_not_booked', 'off'),
    # Fable QA fix round F-04: energy-tax rates scaled to the S10 source revenue before the fit, rates held in the fit
    'energy_tax_revenue': ('source_revenue_on_the_s11_valued_rows_rates_held_in_the_fit', 'specific_rates_at_s11_prices'),
    # Fable QA fix round C-09: the GCC VAT states' VAT on final demand at the IMF GFS money (config/s13/vat_final_demand_2022.csv)
    # Fable QA fix round F-08 and F-06: the power fuel mix at a level the fit carries; the extraction columns' energy shares when
    # the held energy user cells cannot be carried
    'power_cells_scaled': ('s11_mix_held_at_the_highest_level_the_fit_carries_0p75_0p5_0p35_0p25_else_free', 'off'),
    'energy_users_fallback': ('extraction_columns_energy_cells_held_at_prior_row_shares', 'free_fit'),
    'vat_final_demand': ('listed_vat_states_households_and_government_at_imf_gfs_g114_less_g1142_firms_deduct', 'off'),
    # beta v4 G15 (Grok QA A6): a representative-table region's energy excise scaled down to its IMF GFS G114 total where above it
    'excise_cap_g114': ('positive_energy_excise_scaled_to_imf_gfs_g114_where_it_exceeds_it', 'off'),
    # beta v4 P15: the refining column's share of each held energy row at the S11 measured inputs, not split by the fit
    'energy_user_pool_split': ('refining_cells_at_s11_measured_inputs_crude_intake_refinery_gas_own_use_rest_of_the_pool_at_prior_shares',
                               'pool_split_by_the_fit'),
    # beta v4 P5 (David's call; 'off' is the default): the F-08 power ladder also fires when a converged fit leaves power VA below 3% of output
    'power_va_trigger': ('off', 'f08_ladder_when_converged_ely_va_below_3pct_of_output_flag_3_to_5pct'),
    # beta v4 P14: a crude row with no refinery and no prior buyer goes to the oil industry's own use, never to households
    'no_refinery_crude_use': ('no_household_crude_fill_oil_own_use_takes_a_no_buyer_crude_row', 'households_take_a_no_buyer_row'),
    # beta v4 dry run 3 (S16; David's purchaser-price convention, s11 ely_fuel_purchaser_price): S13-H90fit values the held
    # energy inputs at basic x (1 - the fitted fuel subsidy rate), the basis of the S11 rule and floor; basic: the rule before
    'ninety_fit_price': ('purchaser_basic_x_1_less_fitted_fuel_subsidy_rate_pass_through_at_the_same_factor', 'basic'),
    # beta v4 rescan N3 (YEM crude buying products, a reversion of Fable F-06): where the fallback frees the users of a row
    # (USER_DROP_GOODS, petroleum products), the extraction columns still keep their pre-smear prior share of that row
    'partial_users_extraction': ('extraction_columns_keep_prior_presmear_share_of_the_rows_whose_users_the_fallback_frees', 'off'),
    # beta v4 P1 as a lower bound (S16 2026-10-26 19:13 UTC; David's "floor only"): held at the floor only where the floor is
    # above the prior ely column; otherwise the ely row fits free (as in v3) and a region whose free fit lands below the
    # floor (or does not fit) is refitted with the row held at the floor. hold: the earlier max(prior, floor) hold
    'ely_floor_mode': ('lower_bound_free_fit_then_hold_below_floor', 'hold_at_max_prior_floor'),
    # beta v4 H2 (S16 2026-10-27, ely output trace; default off): with the hold, the prior is taken net of the domestic ely own
    # use the own-use cap removes (intra-D35 resale, netted out of row and column), and in the IEA electricity-subsidy
    # regions the held value is at least the S11 value (method.ely_floor, energy.cap_own_use net_held)
    'ely_hold_net_own_use': ('off', 'prior_less_netted_own_use_at_least_the_floor_and_the_s11_value_in_iea_ely_subsidy_regions'),
    # beta v5.5 (David 2026-10-27 22:14 UTC): in the IEA electricity-subsidy regions the H2 hold no longer lifts ely output to
    # the S11 value (tariff + IEA subsidy per MWh); the row keeps the tariff-level hold (prior less netted own use, floor, net
    # exports, as in beta v4) and the booked ely subsidy rate is at most ELY_SUB_RHO_MAX, the money above it not booked
    # (method.book_fuel_subsidies capped_musd), so the subsidy fits inside that output instead of being counted twice
    'ely_subsidy_region_hold': ('s11_value', ELY_SUB_TARIFF),
    # beta v4 H2 add-on (S16 2026-10-27; default off): the held ely value at most the S11 value marked up by m on its domestic
    # electricity sales (the S11 price is a non-household delivered price before taxes), never below the floor (method.ely_floor)
    # beta v4 anchor B (S16 2026-10-27, David's "is there no more empirical way"; default off): in the regions of
    # ely_output_anchor_2022.csv the ely hold is the measured value, use-class prices x volumes (GTAP 12 ch.12 §12.3.6-12.4.3),
    # plus any 2022 price-shield payments of ely_price_shield_2022.csv, never below the floor (method.ely_anchor_values)
    'ely_output_anchor': ('off', 'measured_use_class_prices_x_s11_volumes_plus_price_shield_held_in_the_listed_regions'),
    'ely_hold_cap': ('off',) + tuple(f'held_at_most_the_s11_value_plus_{t}_of_its_domestic_electricity_sales_never_below_the_floor'
                                     for t in ('0p25', '0p5', '1p0')),
    # beta v5 C (David 2026-10-27, package v2; our rule, not in the GTAP text): construction keeps its io_s12 share of the
    # investment column in the fit (method.investment_con_groups), no floor and no new data
    'investment_con_share': ('off', 'construction_share_of_investment_held_at_the_source_table_prior_share'),
    # beta v5 N1 (David 2026-10-27, package v2; our rule, not in the GTAP text): the listed non-energy diagonals of
    # config/s13/own_use_cap_listed.csv (NGA fbt at the fbt world 90th percentile) capped like the energy diagonals,
    # the domestic excess netted out of row and column (energy.cap_own_use net_out)
    'own_use_cap_listed': ('off', OWN_USE_LISTED),
    # beta v5 F (David 2026-10-27, package v2, includes S2; our rule, not in the GTAP text): a non-energy activity's held
    # fuel cell at most max(2 x prior share, prior share + 5 points) of its fitted output (method.fuel_share_caps)
    # beta v5 V (David 2026-10-27, package v2; a straight extension of G14): the listed VAT regions' exempt rows carry no VAT
    # on households and government, the rate on the rest raised to keep G114 less G1142 (ptax_source.vat_final_demand)
    'vat_exemptions': ('off', VAT_EXEMPTIONS),
    'fuel_share_cap': ('off', 'non_energy_activity_fuel_cell_at_most_max_2x_prior_share_or_prior_plus_5pt_of_fitted_output_excess_to_other_held_users'),
}
ELY_FLOOR_LOWER = 'lower_bound_free_fit_then_hold_below_floor'
ELY_HOLD_NET = 'prior_less_netted_own_use_at_least_the_floor_and_the_s11_value_in_iea_ely_subsidy_regions'
PARTIAL_USERS_EXTRACTION = 'extraction_columns_keep_prior_presmear_share_of_the_rows_whose_users_the_fallback_frees'
NINETY_FIT_PURCHASER = 'purchaser_basic_x_1_less_fitted_fuel_subsidy_rate_pass_through_at_the_same_factor'
NO_REFINERY_CRUDE = 'no_household_crude_fill_oil_own_use_takes_a_no_buyer_crude_row'
OWN_USE_CAP_V3 = 'unsd_own_use_plus_losses_share_of_output_coa_oil_gas_ely_excess_to_other_buyers_ely_netted'
POWER_VA_TRIGGER = 'f08_ladder_when_converged_ely_va_below_3pct_of_output_flag_3_to_5pct'

PSE_ITEM_COLUMNS = ('region', 'pse_item', 'input_row', 'value_lcu_million', 'currency', 'fx_lcu_per_usd', 'fx_source', 'period', 'source',
                    'url', 'accessed', 'decided_by', 'decided_at', 'basis')
PSE_ITEM_ROWS = {'fertiliser': ('chm',), 'energy': ('ely', 'pet'), 'irrigation': ('wat',), 'credit': ('fin',)}
PSE_REMAINDER_COLUMNS = ('region', 'rows', 'pse_items', 'source', 'url', 'accessed', 'decided_by', 'decided_at', 'basis')
PSE_REMAINDER_ROWS = {r for v in PSE_ITEM_ROWS.values() for r in v} | {'crp'}      # crp: seeds


def read_pse_remainder(path=os.path.join(CONFIG_DIR, 'pse_input_remainder_2022.csv')):
    """config/s13/pse_input_remainder_2022.csv (round-3 QA item 9): per region, the input rows (space-separated) of the
    PSE B1 items the OECD lists for it whose amounts are not listed in pse_input_items_2022.csv; the region's remainder of
    PSE input support goes there instead of every crp input. Stop on a missing file or column, a blank attribution, a
    duplicate region or a row that is not a B1 input row. Returns {region: [rows]}."""
    if not os.path.exists(path):
        raise ConfigError(f'{path} is missing')
    with open(path, newline='') as fh:
        rd = csv.DictReader(fh)
        if tuple(rd.fieldnames or ()) != PSE_REMAINDER_COLUMNS:
            raise ConfigError(f'{path}: columns {rd.fieldnames} are not {PSE_REMAINDER_COLUMNS}')
        rows = list(rd)
    out = {}
    for r in rows:
        if not r['decided_by'].strip() or not r['decided_at'].strip() or not r['source'].strip():
            raise ConfigError(f'{path}: row {r["region"]} has no source, decided_by or decided_at')
        if r['region'] in out:
            raise ConfigError(f'{path}: region {r["region"]} listed twice')
        rr = r['rows'].split()
        bad = [x for x in rr if x not in PSE_REMAINDER_ROWS]
        if not rr or bad:
            raise ConfigError(f'{path}: row {r["region"]}: rows {r["rows"]!r} must be B1 input rows {sorted(PSE_REMAINDER_ROWS)}')
        out[r['region']] = rr
    return out


ELY_ANCHOR = 'measured_use_class_prices_x_s11_volumes_plus_price_shield_held_in_the_listed_regions'
ANCHOR_COLUMNS = ('region', 'household_share', 'household_price_usd_mwh', 'nonhousehold_price_usd_mwh', 'share_source',
                  'household_price_source', 'nonhousehold_price_source', 'decided_by', 'decided_at', 'basis')
SHIELD_COLUMNS = ('region', 'payment_lcu_million', 'currency', 'fx_lcu_per_usd', 'fx_source', 'scheme', 'period', 'source', 'url',
                  'decided_by', 'decided_at', 'basis')


def _read_table(path, columns):
    if not os.path.exists(path):
        raise ConfigError(f'{path} is missing')
    with open(path, newline='') as fh:
        rd = csv.DictReader(fh)
        if tuple(rd.fieldnames or ()) != columns:
            raise ConfigError(f'{path}: columns {rd.fieldnames} are not {columns}')
        return list(rd)


def read_ely_anchor(path=os.path.join(CONFIG_DIR, 'ely_output_anchor_2022.csv')):
    """config/s13/ely_output_anchor_2022.csv (beta v4 anchor B): per region the households' share of electricity final
    consumption and the 2022 household and non-household prices before taxes (USD/MWh), each with its source; stop on a
    blank source or attribution, a share outside [0, 1], a price not above 0 or a repeated region. Returns
    {region: (share, household price, non-household price)}."""
    out = {}
    for r in _read_table(path, ANCHOR_COLUMNS):
        if not all(r[k].strip() for k in ('share_source', 'household_price_source', 'nonhousehold_price_source', 'decided_by', 'decided_at')):
            raise ConfigError(f'{path}: row {r["region"]} has a blank source, decided_by or decided_at')
        sh, ph, pn = float(r['household_share']), float(r['household_price_usd_mwh']), float(r['nonhousehold_price_usd_mwh'])
        if not (0.0 <= sh <= 1.0 and ph > 0 and pn > 0) or r['region'] in out:
            raise ConfigError(f'{path}: row {r["region"]}: share, prices or a repeated region')
        out[r['region']] = (sh, ph, pn)
    return out


def read_ely_shield(path=os.path.join(CONFIG_DIR, 'ely_price_shield_2022.csv')):
    """config/s13/ely_price_shield_2022.csv (beta v4 anchor B): 2022 government payments to electricity suppliers on top of
    what consumers paid (France's bouclier tarifaire, the UK Energy Price Guarantee), with their sources; the file may hold
    no rows. Returns {region: USD million}."""
    out = {}
    for r in _read_table(path, SHIELD_COLUMNS):
        if not all(r[k].strip() for k in ('source', 'decided_by', 'decided_at', 'scheme')):
            raise ConfigError(f'{path}: row {r["region"]} {r["scheme"]} has a blank source, scheme, decided_by or decided_at')
        v, fx = float(r['payment_lcu_million']), float(r['fx_lcu_per_usd'])
        if not (v >= 0 and fx > 0):
            raise ConfigError(f'{path}: row {r["region"]} {r["scheme"]}: payment or exchange rate')
        out[r['region']] = out.get(r['region'], 0.0) + v / fx
    return out


class ConfigError(SystemExit):
    pass


def read_pse_items(path=os.path.join(CONFIG_DIR, 'pse_input_items_2022.csv')):
    """config/s13/pse_input_items_2022.csv: one row per region and PSE B1 item with its source; stop on a missing file
    or column, a blank attribution, an unknown item or a row the item does not map to. Returns
    {region: {input_row: USD million}}."""
    if not os.path.exists(path):
        raise ConfigError(f'{path} is missing')
    with open(path, newline='') as fh:
        rd = csv.DictReader(fh)
        if tuple(rd.fieldnames or ()) != PSE_ITEM_COLUMNS:
            raise ConfigError(f'{path}: columns {rd.fieldnames} are not {PSE_ITEM_COLUMNS}')
        rows = list(rd)
    out = {}
    for r in rows:
        if not r['decided_by'].strip() or not r['decided_at'].strip() or not r['source'].strip():
            raise ConfigError(f'{path}: row {r["region"]} {r["pse_item"]} has no source, decided_by or decided_at')
        if r['input_row'] not in PSE_ITEM_ROWS.get(r['pse_item'], ()):
            raise ConfigError(f'{path}: item {r["pse_item"]!r} does not map to row {r["input_row"]!r} ({PSE_ITEM_ROWS})')
        v, fx = float(r['value_lcu_million']), float(r['fx_lcu_per_usd'])
        if not (v >= 0 and fx > 0):
            raise ConfigError(f'{path}: row {r["region"]} {r["pse_item"]} value or exchange rate')
        d = out.setdefault(r['region'], {})
        d[r['input_row']] = d.get(r['input_row'], 0.0) + v / fx
    return out


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


def read_own_use_listed(path=OWN_USE_LISTED_PATH, energy=('coa', 'oil', 'gas', 'pet', 'ely')):
    """Beta v5 N1: config/s13/own_use_cap_listed.csv, one row per (region, non-energy commodity) whose own-use (diagonal)
    share of output is capped at own_use_share. Stop on a missing file or column, a blank source or attribution, a duplicate
    cell, an energy good (those take the S11 UNSD share, own_use_cap) or a share outside (0, 1). Returns {region: {good: share}}."""
    if not os.path.exists(path):
        raise ConfigError(f'{path} is missing')
    with open(path, newline='') as fh:
        rd = csv.DictReader(fh)
        if tuple(rd.fieldnames or ()) != OWN_USE_LISTED_COLUMNS:
            raise ConfigError(f'{path}: columns {rd.fieldnames} are not {OWN_USE_LISTED_COLUMNS}')
        rows = list(rd)
    out = {}
    for r in rows:
        if not all(r[c].strip() for c in ('source', 'decided_by', 'decided_at')):
            raise ConfigError(f'{path}: row {r["region"]} {r["commodity"]} has no source, decided_by or decided_at')
        if r['commodity'] in energy:
            raise ConfigError(f'{path}: {r["commodity"]} is an energy good (its own-use cap is the S11 UNSD share)')
        s = float(r['own_use_share'])
        if not 0.0 < s < 1.0:
            raise ConfigError(f'{path}: row {r["region"]} {r["commodity"]} share {s} is not in (0, 1)')
        if r['commodity'] in out.get(r['region'], {}):
            raise ConfigError(f'{path}: {r["region"]} {r["commodity"]} listed twice')
        out.setdefault(r['region'], {})[r['commodity']] = s
    return out
