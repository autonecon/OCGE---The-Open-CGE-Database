#!/usr/bin/env python3
"""S11 energy volumes, prices and the energy override (GTAP 12 ch.12).

The method is in the s11_energy package (method.py, in the ch.12 order); this file declares the
inputs, runs the steps, and turns every result into a check, a flag, a ledger row or an output file.

1. Volumes: the stamped PREP_energy_volumes (EIA International, JODI, UNSD fills), annualised.
   Where no volume source exists, the trade volume is zero (flagged BLANK-TRADE-VOLUME; GTAP §12.4.2).
2. Re-exports out (ch.12 §12.2.5), world balance (§12.2.4).
3. Export prices (§12.3): EI crude markers and product markers + margins (E7), BACI unit values
   for gas and coal, BACI HS 271600 / EIA TWh for electricity; simple average where missing.
   Gas exporters whose BACI tonnes are a Comtrade estimate take BACI value over an observed volume
   of the same flows (config/s11/gas_export_price_observed.csv).
4. Energy trade (§12.4.2): FOB / export price, seeds, RAS to the volume vectors, x export price.
   CIF by the S08 margin rates and mode mix, VMSB by the S10 tm; VST rescaled.
5. Output values (§12.4.3): exports at export prices, domestic sales at basic prices; 90 percent rule.
6. B06 split into oil and gas (PLAN b1 item 7). io_s10 is otherwise unchanged; S13 fits it.

Choices come from config/s11/s11_choices.csv (s11_energy/config.py). Outputs derived from TRAINS
(S10 tm) or from io_s10 are listed in output/NOT_FOR_PUBLICATION.md.
"""
import gzip
import json
import os
import re
import subprocess
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.stagekit import Stage, sha256, ROOT, DATA, BUILD, STAGES  # noqa: E402
from lib.private_files import private_paths  # noqa: E402
from s11_energy import config as C  # noqa: E402
from s11_energy import method as M  # noqa: E402
from s11_energy import sources as SRC  # noqa: E402
from s11_energy import domestic as DOM  # noqa: E402
from s11_energy import checks as K  # noqa: E402
from s11_energy import power as PWR  # noqa: E402
import screens.s11_suite as SCR  # noqa: E402
from s11_energy.sources import COMMODITIES, PREP_NAME, UNIT, PRICE_UNIT, FROM_PREP  # noqa: E402

UP = {
    'S01': STAGES + '/S01_sets_registry',
    'PREP': STAGES + '/PREP_energy_volumes',
    'S07': STAGES + '/S07_trade',
    'S08': STAGES + '/S08_margins',
    'S09': STAGES + '/S09_services',
    'S10': STAGES + '/S10_tariffs_taxes',
}
TRADE_SECTORS = ('coa', 'oil', 'gas', 'pet')   # in S10 VFOB; ely comes from BACI HS 271600
TARGETS = ('coa', 'oil', 'gas', 'pet')          # output values written as S13 targets (ely joins with choice ely_output_value)
MODES = ('rdt', 'sea', 'air')
PI_MISMATCH = 10.0                 # a 90 percent rule factor beyond 10x either way marks an io/volume mismatch
SEED_EPS = 1e-6
S09_TRAVEL_SHA = '37c6971f75a328e137d199fee0d0038efbcdd2447e2649dbcf9d4249159a879d'  # S09 travel_s09.csv.gz (beta v4; moved by tools/update_pins.py --after S09)
SEED_REPORT_MUSD = 100.0
NGPL_SERIES = 'Mont Belvieu, TX Propane Spot Price FOB (Dollars per Gallon)'


def bn(x):
    return x / 1000.0


def main():
    choices = C.load_choices()          # stops before anything is written if a row is missing or off
    markers_cfg = C.read_table('crude_markers.csv', ('region', 'marker', 'decided_by', 'decided_at', 'basis'))
    hubs_cfg = C.read_table('product_hubs.csv', ('gtap_geo', 'crude_marker', 'margin_hub', 'decided_by', 'decided_at', 'basis'))
    gas_obs_cfg = C.read_table('gas_export_price_observed.csv', ('region', 'method', 'route_exporters', 'route_importer', 'ei_block',
                                                                  'ei_row', 'ei_importer_block', 'decided_by', 'decided_at', 'basis'))

    S = Stage('S11', 'energy')
    I = S.inp
    S.check('S11-Hconfig', f'config/s11/s11_choices.csv has the {len(C.CHOICES)} choices this code implements, each with decided_by and decided_at',
            'hard', len(choices), len(C.CHOICES), len(choices) == len(C.CHOICES), 's11_choices',
            'Departures and choices not in the GTAP text: ' + ', '.join(k for k, r in choices.items() if r['gtap_status'] in ('departure_logged', 'not_in_gtap_text')))
    for k in UP.values():
        S.upstream(k)
    I(C.CHOICES_PATH, 'S11 choices')
    I(C.CONFIG_DIR + '/crude_markers.csv', 'crude marker of each exporter')
    I(C.CONFIG_DIR + '/product_hubs.csv', 'product hub of each GTAP geographic region')
    I(C.CONFIG_DIR + '/gas_export_price_observed.csv', 'gas exporters priced from an observed volume (BACI tonnes estimated)')
    # Fable QA D-02, D-04, C-03 (David 2026-10-25 "do all fixes"): route prices, gas origins, observed re-exports, route export tax
    gas_rv_cfg = C.read_table('gas_route_volume_observed.csv', ('exporter', 'importer', 'hs_line', 'ei_block', 'ei_row', 'decided_by', 'decided_at', 'basis'))
    gas_org_cfg = C.read_table('gas_import_origin.csv', ('importer', 'eurostat_geo', 'decided_by', 'decided_at', 'basis'))
    xt_exempt_cfg = C.read_table('export_tax_exempt_routes.csv', ('union', 'members', 'decided_by', 'decided_at', 'basis'))
    for f, what in (('gas_route_volume_observed.csv', 'gas routes whose pipeline tonnes the importer did not report (EI route volume)'),
                    ('gas_import_origin.csv', 'gas importers seeded by origin from Eurostat'),
                    ('export_tax_exempt_routes.csv', 'routes exempt from export duties (EAEU internal trade)')):
        I(C.CONFIG_DIR + '/' + f, what)

    # ------------------------------------------------------------- inputs
    regions = pd.read_csv(I(UP['S01'] + '/output/regions.csv', 'S01 regions'))
    cmap = pd.read_csv(I(UP['S01'] + '/output/country_region_map.csv', 'S01 country map'))
    hsmap = pd.read_csv(I(UP['S01'] + '/output/concord_hs22_to_sector.csv', 'S01 HS22 to sector'), dtype=str)
    vol_raw = pd.read_csv(I(UP['PREP'] + '/output/volumes_2022.csv', 'energy volumes by region'))
    ngl_raw = pd.read_csv(I(UP['PREP'] + '/output/ngl_exclusion_check.csv', 'NGPL by country (E29)'))
    vfob10 = pd.read_csv(I(UP['S10'] + '/output/vfob_s10.csv.gz', 'S10 VXSB/VFOB'))
    xt10 = pd.read_csv(I(UP['S10'] + '/output/export_tax_s10.csv', 'S10 export-tax rates on VFOB (fix list A2)'))
    tm10 = pd.read_csv(I(UP['S10'] + '/output/tm_s10.csv.gz', 'S10 tm'))
    vmsb10 = pd.read_csv(I(UP['S10'] + '/output/vmsb_s10.csv.gz', 'S10 VCIF/VMSB'))
    hs6app = pd.read_csv(I(UP['S10'] + '/output/hs6_applied_s10.csv.gz', 'S10 pair-sector rates (MFN for new pairs)'),
                         usecols=['importer', 'partner', 'sector_name', 'mfn_rate_pct', 'weight_thousand_usd'])
    io10 = pd.read_csv(I(UP['S10'] + '/output/io_s10.csv.gz', 'io_s10'))
    vtwr8 = pd.read_csv(I(UP['S08'] + '/output/vtwr_s08.csv.gz', 'S08 VTWR'))
    mr8 = pd.read_csv(I(UP['S08'] + '/output/margin_rates_s08.csv.gz', 'S08 margin rates'), usecols=['sector', 'exporter', 'importer', 'm_fob'])
    vst8 = pd.read_csv(I(UP['S08'] + '/output/vst_s08.csv', 'S08 VST'))
    travel_path = I(UP['S09'] + '/output/travel_s09.csv.gz', 'S09 travel (hash only; not in the RAS)')
    vxsb7 = pd.read_csv(I(UP['S07'] + '/output/vxsb_goods_s07r.csv.gz', 'S07R VXSB (non-energy identity check)'))
    unions = pd.read_csv(I(BUILD + '/config/s10/customs_unions.csv', 'S10 customs unions (new-pair duty)'))
    iso_num = pd.read_csv(I(BUILD + '/config/prep_energy/iso3166_alpha.csv', 'ISO 3166 numeric codes'), dtype=str, keep_default_na=False)
    ei_path = I(DATA + '/ei_statistical_review/EI-Stats-Review-ALL-data.xlsx', 'EI 2025: crude markers, margins, factors, 2022 inter-regional gas trade')
    ei = SRC.ei_prices(ei_path)
    ei_coal = SRC.ei_coal_markers(DATA + '/ei_statistical_review/EI-Stats-Review-ALL-data.xlsx')
    spot = SRC.eia_spot_2022(I(DATA + '/eia_prices/EIA_PET_PRI_SPT_S1_A.xls', 'EIA spot prices 2022'))
    baci_zip = I(DATA + '/baci/BACI_HS17_V202601.zip', 'BACI HS17 V202601 2022, the S07 release: energy unit values and HS 271600')
    jodi_zip = I(DATA + '/jodi/jodi_oil_world_primary_csv.zip', 'JODI-Oil primary 2022: crude refinery intake (REFINOBS) for the 90 percent rule')
    unsd_path = I(DATA + '/unsd_energy/undata_energy_2022.csv', 'UNSD 2022: coal heat values; natural gas used by oil refineries')
    mer = {t: I(f'{DATA}/eia_us_2022/MER_{t}.csv', f'EIA MER {t} (US scrutiny, report only)') for t in ('T03.01', 'T04.01', 'T06.01', 'T07.01')}
    iea_path = I(DATA + '/iea_subsidies/Subsidies 2010-2024.xlsx', 'IEA subsidies 2022: price gaps for domestic basic prices (David 2026-10-23 19:12)')
    es_ti = I(DATA + '/eurostat_gas_trade/nrg_ti_gas_2022.csv', 'Eurostat nrg_ti_gas 2022 gas imports by partner (Fable QA D-02)')
    es_te = I(DATA + '/eurostat_gas_trade/nrg_te_gas_2022.csv', 'Eurostat nrg_te_gas 2022 gas exports by partner (Fable QA D-02)')
    ct_dir = DATA + '/un_comtrade_rx_2022'
    for f in sorted(os.listdir(ct_dir)):
        if f.endswith('.json'):
            I(f'{ct_dir}/{f}', 'UN Comtrade 2022 exports and re-exports to the world (Fable QA D-04)')
    xt_lines_path = I(BUILD + '/config/s10/export_tax_rates_2022.csv', 'S10 statutory export-tax rates by HS line (Fable QA C-03)')
    hubs = SRC.ei_gas_hubs_2022(DATA + '/ei_statistical_review/EI-Stats-Review-ALL-data.xlsx')
    iea_map = {r['iea_name']: r['iso3'] for r in C.read_table('iea_country_iso3.csv', ('iea_name', 'iso3', 'basis', 'decided_by', 'decided_at'))}
    I(C.CONFIG_DIR + '/iea_country_iso3.csv', 'IEA country names to iso3')
    I(C.CONFIG_DIR + '/domestic_price_sources.csv', 'source-data domestic prices')
    iea_sub = SRC.iea_subsidies_2022(iea_path, iea_map)
    deflator = SRC.wdi_us_deflator_ratio(I(DATA + '/wdi_us_deflator/USA_NY.GDP.DEFL.ZS_2015_2024.json', 'WDI USA GDP deflator (IEA real 2024 -> 2022)'))
    eur_per_usd = SRC.wdi_value(I(DATA + '/wdi/wdi_2017_2022_extract.csv', 'WDI PA.NUS.FCRF DEU 2022 (EUR per USD)'), 'PA.NUS.FCRF', 'DEU', 2022)
    eurostat_path = {'nrg_pc_203': I(DATA + '/eurostat_energy_prices/nrg_pc_203_2017S1_2022S2.csv', 'Eurostat non-household gas prices'),
                     'nrg_pc_205': I(DATA + '/eurostat_energy_prices/nrg_pc_205_2017S1_2022S2.csv', 'Eurostat non-household electricity prices')}
    us_coal = SRC.acr_us_coal_2022(I(DATA + '/eia_us_prices_2022/acr2022_table28_price_by_state_minetype.csv', 'EIA ACR 2022 table 28 (US coal sales price)'))
    aeco = SRC.aer_aeco_2022(I(DATA + '/aer_st98_prices/st98-2024-prices-and-capital-expenditure-data.xlsx', 'AER ST98 2024 Table S1.2 AECO-C 2022 (Canada gas hub price)'))
    cad_per_usd = SRC.wdi_value(DATA + '/wdi/wdi_2017_2022_extract.csv', 'PA.NUS.FCRF', 'CAN', 2022)
    for f in ('C13-02.jpg', 'C13-12.jpg'):
        I(DATA + '/nbs_yearbook_2023_coal/' + f, f'NBS China Statistical Yearbook 2023 {f[:-4]} (China coal unit value; transcribed in config/s11/nbs_coal_2022.csv)')
    I(C.CONFIG_DIR + '/nbs_coal_2022.csv', 'NBS 2022 coal revenue and raw coal output, transcribed')
    nbs = {r['item']: float(r['value']) for r in C.read_table('nbs_coal_2022.csv', ('item', 'table', 'row', 'value', 'unit', 'decided_by', 'decided_at', 'basis'))}
    cny_per_usd = SRC.wdi_value(DATA + '/wdi/wdi_2017_2022_extract.csv', 'PA.NUS.FCRF', 'CHN', 2022)
    # fix-round A9: transcribed 2022 producer prices where the domestic price is regulated (David's fact-check, 2026-10-24)
    I(C.CONFIG_DIR + '/transcribed_prices_2022.csv', 'transcribed 2022 regulated and producer prices (fix-round A9)')
    transcribed = {r['item']: r for r in C.read_table('transcribed_prices_2022.csv', ('item', 'commodity', 'region', 'value', 'unit', 'fx_iso3',
                                                                                     'decided_by', 'decided_at', 'basis'))}
    n_ty, d_ty = K.transcribed_years(transcribed)
    S.check('S11-Htransyear', 'Beta v4 G7: every transcribed price dated by its item name is from 2022 or earlier (latest year at or before the base year)',
            'hard', n_ty, 0, n_ty == 0, 'transcribed_prices_2022.csv; year rule', d_ty)
    tr_fx = {r['fx_iso3']: SRC.wdi_value(DATA + '/wdi/wdi_2017_2022_extract.csv', 'PA.NUS.FCRF', r['fx_iso3'], 2022)
             for r in transcribed.values() if r['fx_iso3']}
    lignite_on, cap_on = C.switched_on(choices, 'lignite_price'), C.switched_on(choices, 'exporter_price_cap')
    subsidy_on = choices['fuel_subsidies']['value'] != 'off'      # fix-round B15 (GTAP's booking)
    # beta v4 P1: electricity in the 90 percent rule, and the ely output value as an S13 target
    ely_rule_on = C.switched_on(choices, 'ninety_pct_ely')
    ely_target_on = choices['ely_output_value']['value'] in (C.ELY_TARGET, C.ELY_FLOOR, C.ELY_FLOOR90)
    ely_floor_on = choices['ely_output_value']['value'] == C.ELY_FLOOR        # David 2026-10-26: floor only (price-based)
    ely_floor90_on = choices['ely_output_value']['value'] == C.ELY_FLOOR90    # S16 08:33 UTC: the 90 percent rule as the floor
    if ely_floor90_on and not ely_rule_on:
        raise SystemExit('ely_output_value floor_ninety needs ninety_pct_ely: the floor is the electricity side of the 90 percent rule')
    # B15 extension (David 2026-10-24): every IEA subsidy row; fix round wA (independent QA HIGH-1): booked as a price gap,
    # the w10 add-on-top rule kept as an alternative
    subsidy_all = choices['fuel_subsidies']['value'] in (C.FUEL_SUBSIDIES_PRICE_GAP, C.FUEL_SUBSIDIES_ADD_ON_TOP)
    subsidy_mode = DOM.SUBSIDY_ADD_ON_TOP if choices['fuel_subsidies']['value'] == C.FUEL_SUBSIDIES_ADD_ON_TOP else DOM.SUBSIDY_PRICE_GAP
    # fix round wA2 (choice iea_reference_ely): electricity end-user prices for the IEA reference = consumer price + IEA rate
    I(C.CONFIG_DIR + '/electricity_tariffs_2022.csv', 'electricity end-user tariffs 2022 (fix round wA2)')
    tariff_tab = C.read_table('electricity_tariffs_2022.csv', ('region', 'value', 'unit', 'fx_iso3', 'fx_lcu_per_usd', 'income_group', 'source',
                                                               'url', 'accessed', 'tax_basis', 'decided_by', 'decided_at', 'basis'))
    tariff_fx = {t['fx_iso3']: SRC.wdi_value(DATA + '/wdi/wdi_2017_2022_extract.csv', 'PA.NUS.FCRF', t['fx_iso3'], 2022)
                 for t in tariff_tab if t['fx_iso3']}
    us_lignite = SRC.acr_us_lignite_2022(I(DATA + '/eia_us_prices_2022/acr2022_table31_price_by_state_rank.csv', 'EIA ACR 2022 table 31 (US lignite mine price, fix-round A9)'))
    I(C.CONFIG_DIR + '/crude_direct_users.csv', 'crude oil users outside refining, UNSD transactions (fix-round A8)')
    direct_cfg = C.read_table('crude_direct_users.csv', ('transaction', 'io_column', 'unsd_name', 'decided_by', 'decided_at', 'basis'))
    us_ely = SRC.epa_us_industrial_2022(I(DATA + '/eia_us_prices_2022/EPA2022_epa_02_04.xlsx', 'EIA EPA 2022 table 2.4 (US industrial electricity price)'))
    intl_path = I(DATA + '/eia_intl/INTL.txt', 'EIA international bulk (screen 3: 2021 volumes)')
    for f in ('discrepancies_over_5pct.csv', 'crosscheck_summary.csv', 'volumes_country_2022.csv'):
        I(UP['PREP'] + '/output/' + f, f'PREP {f} (screens 1, 3, 4)')
    if os.path.exists(SCR.EXPLANATIONS):
        I(SCR.EXPLANATIONS, 'S11 screen explanations')

    R = sorted(regions['region'])
    n = len(R)
    ix = {r: i for i, r in enumerate(R)}
    single = regions.set_index('region')['type'].reindex(R).eq('single').to_numpy()
    geo = regions.set_index('region')['gtap_geo'].reindex(R)
    iso_region = {r['code']: r['region'] for _, r in cmap.iterrows() if isinstance(r['region'], str) and r['region']}
    members = {r: str(m).split() for r, m in zip(regions['region'], regions['members'])}
    num_iso = dict(zip(iso_num['numeric'].str.zfill(3), iso_num['alpha3']))
    su_value = choices['energy_supply_use_balance']['value']
    su_scope, su_surplus = C.SUPPLY_USE_SCOPE[su_value]   # fix round w16: goods balanced two-sided (GTAP 12 ch.12 §12.2.4)

    # ------------------------------------------------------------- 1. volumes
    vol = {c: {} for c in COMMODITIES}
    vsrc = {c: {} for c in COMMODITIES}
    for c in COMMODITIES:
        sub = vol_raw[vol_raw['commodity'] == PREP_NAME[c]]
        for flow in ('production', 'imports', 'exports', 'consumption'):
            f = sub[sub['flow'] == flow].set_index('region').reindex(R)
            vol[c][flow] = f['value'].to_numpy(float) * FROM_PREP[c]
            vsrc[c][flow] = f['source'].fillna('').to_numpy(str)
    ngpl = ngl_raw.groupby('region')['eia_58_ngpl_kbd'].sum().reindex(R).fillna(0).to_numpy(float) * SRC.DAYS / 1000.0

    # crude use from the energy data (million bbl): refinery intake and the direct users of crude_direct_users.csv.
    # refinery intake: JODI CRUDEOIL REFINOBS (full 2022, every member), else PREP crude use, else (fix-round A10) UNSD 2022
    # crude oil transformed in oil refineries (4100 / 086, every member reporting); else not measured (a zero is a blank)
    a2_iso = dict(zip(iso_num['alpha2'], iso_num['alpha3']))
    jodi_ref = SRC.jodi_refinery_crude_2022(jodi_zip, a2_iso)
    unsd_ref = {iso: kt / (SRC.TOE_PER_BBL_CRUDE * 1000.0) for (iso, _), kt in SRC.unsd_crude_direct_use_2022(unsd_path, num_iso, ('086',)).items()}
    crude_raw, crude_src, crude_meas = {}, {}, np.zeros(n, bool)
    for i, r in enumerate(R):
        have = [m for m in members[r] if m in jodi_ref]
        use = float(np.nan_to_num(vol['oil']['consumption'][i]))
        mem = [iso for iso, rr in iso_region.items() if rr == r]
        if have and len(have) == len(members[r]):
            crude_raw[r], crude_src[r], crude_meas[i] = sum(jodi_ref[m] for m in have), 'jodi_refinobs', True
        elif use > 0:
            crude_raw[r], crude_src[r], crude_meas[i] = use, 's11_crude_use', True
        elif mem and all(m in unsd_ref for m in mem):
            crude_raw[r], crude_src[r], crude_meas[i] = sum(unsd_ref[m] for m in mem), 'unsd_4100_086', True
        else:
            crude_raw[r], crude_src[r] = use, 's11_crude_use'
    # Fable QA D-08 (2026-10-25): where the energy-data intake is below 70% of EI 2022 refinery throughput (every member
    # reported), EI throughput is the intake (ARE: UNSD 212 vs EI 348 million bbl); GTAP 12 ch.12 §12.2 takes energy
    # volumes from the energy statistics, and EI is the throughput series of the refinery industry itself
    ei_ref = SRC.ei_refinery_throughput_2022(ei_path, iea_map)
    ei_floor_rows = []
    for i, r in enumerate(R):
        mem = [iso for iso, rr in iso_region.items() if rr == r]
        if not (mem and all(m in ei_ref for m in mem)):
            continue
        ei_v = sum(ei_ref[m] for m in mem)
        low = crude_raw[r] < C.EI_INTAKE_FLOOR_SHARE * ei_v
        ei_floor_rows.append((r, crude_raw[r], ei_v, crude_src[r], low))
        if low and C.switched_on(choices, 'refinery_intake_ei_floor'):
            crude_raw[r], crude_src[r], crude_meas[i] = ei_v, 'ei_refinery_throughput', True
    direct_col = {row['transaction']: row['io_column'] for row in direct_cfg}
    direct_mbbl = {}
    for (iso, tr), kt in SRC.unsd_crude_direct_use_2022(unsd_path, num_iso, direct_col).items():
        rr = iso_region.get(iso)
        if rr in ix:
            d_ = direct_mbbl.setdefault(rr, {})
            d_[direct_col[tr]] = d_.get(direct_col[tr], 0.0) + kt / (SRC.TOE_PER_BBL_CRUDE * 1000.0)   # kt -> million bbl
    # fix round w16 (GTAP 12 ch.12 §12.2.4): measured domestic use of each good balanced two-sided. Crude: refinery intake
    # plus direct use, where the intake is measured; coal and gas: EIA total consumption. pet and ely are not balanced:
    # JODI product demand counts NGL and biofuels that PREP refinery output leaves out, and EIA electricity net
    # consumption leaves out losses and own use, so neither is a total use (S11-Rsupuseexcl reports their gaps)
    use_vol, use_meas = {}, {}
    for c in COMMODITIES:
        if c == 'oil':
            use_vol[c] = np.array([crude_raw[r] + sum(direct_mbbl.get(r, {}).values()) for r in R])
            use_meas[c] = crude_meas.copy()
        else:
            use_vol[c] = np.nan_to_num(vol[c]['consumption'])
            use_meas[c] = np.isfinite(vol[c]['consumption'])
    # beta v4 P14 (choice no_refinery_crude_use): a crude producer with no refinery (no measured intake, no refinery output
    # of pet, no listed direct user) has measured domestic crude use 0, so §12.2.4 sends its supply to exports; where its export
    # volume is blank, the S10 VFOB over the export price is the last-resort volume (TLS, MNG: crude went to households in S13)
    no_ref_on = C.switched_on(choices, 'no_refinery_crude_use')
    no_ref = np.zeros(n, bool)
    if no_ref_on:
        pet_out = np.nan_to_num(vol['pet']['production'])
        no_ref = (~use_meas['oil']) & (use_vol['oil'] <= 0) & (pet_out <= 0) & (np.nan_to_num(vol['oil']['production']) > 0)
        use_meas['oil'] = use_meas['oil'] | no_ref
        for i in np.where(no_ref)[0]:
            crude_src[R[i]] = 'no_refinery_zero_use'

    # trade values before S11 (USD million), exporter x importer, per commodity
    def matrix(df, val, sector, exp='exporter', imp='importer'):
        A = np.zeros((n, n))
        d = df[df['sector'] == sector]
        np.add.at(A, (d[exp].map(ix).to_numpy(), d[imp].map(ix).to_numpy()), d[val].to_numpy(float))
        return A

    old_fob = {c: matrix(vfob10, 'vfob_musd', c) for c in TRADE_SECTORS}
    rates = vfob10[vfob10['sector'].isin(TRADE_SECTORS)]['export_subsidy_rate']
    S.check('S11-Hxs', 'S10 export subsidy rates on coa, oil, gas and pet are all zero, so VXSB = VFOB less the S10 export tax', 'hard',
            int((rates != 0).sum()), 0, bool((rates == 0).all()), 'export_tax_after_override')
    # fix list A2: the S10 export-tax rate on VFOB of each exporter and energy good, held on the S11 routes (VXSB = VFOB x (1 - t))
    xrate = K.export_tax_rates(xt10, R, COMMODITIES)

    # BACI energy lines
    coa_hs = tuple(sorted(hsmap.loc[hsmap['sector'] == 'coa', 'hs22']))
    baci = SRC.baci_energy(baci_zip, 'BACI_HS17_Y2022_V202601.csv', 'country_codes_V202601.csv',
                           coa_hs + SRC.GAS_HS + SRC.ELY_HS + SRC.VPV_HS)
    baci['exp'] = baci['exp_iso'].map(iso_region)
    baci['imp'] = baci['imp_iso'].map(iso_region)
    # crude and products lines: read only for the source check S11-Hvpv (fix-round B9), not for any price
    baci_vpv = baci[baci['k'].isin(SRC.VPV_HS) & baci['exp'].notna() & baci['imp'].notna() & (baci['exp'] != baci['imp'])]
    baci = baci[~baci['k'].isin(SRC.VPV_HS)]
    unmapped = baci[baci['exp'].isna() | baci['imp'].isna()]
    S.check('S11-Rbaci', 'BACI energy rows whose exporter or importer is outside the S01 map (dropped)', 'report',
            f'{len(unmapped)} rows; {unmapped["v"].sum() / 1e6:.3f} bn', '', True, 'ely_trade_source',
            ' '.join(sorted(set(unmapped['exp_iso'].fillna('?')) | set(unmapped['imp_iso'].fillna('?'))))[:400])
    baci = baci.dropna(subset=['exp', 'imp'])
    baci = baci[~((baci['exp'] == baci['imp']) & baci['exp'].map(lambda r: single[ix[r]]))]
    ely = baci[baci['k'] == '271600']
    old_fob['ely'] = np.zeros((n, n))
    np.add.at(old_fob['ely'], (ely['exp'].map(ix).to_numpy(), ely['imp'].map(ix).to_numpy()), ely['v'].to_numpy() / 1000.0)
    S.check('S11-Rely', 'BACI HS 271600 2022 FOB on the S01 map, single-country diagonals dropped (S07R left 132.139 bn for S11)', 'report',
            f'{bn(old_fob["ely"].sum()):.3f} bn', '132.139 bn', abs(bn(old_fob['ely'].sum()) - 132.139) < 1.0, 'ely_trade_source')

    # ------------------------------------------------------------- 3. export prices (USD per natural unit = USD million per million units)
    px, psrc = {}, {}
    mk = {r['region']: r['marker'] for r in markers_cfg}
    star = mk.pop('*')
    px['oil'] = np.array([ei[mk.get(r, star)] for r in R])
    psrc['oil'] = np.array([f'EI 2022 {mk.get(r, star)}' for r in R], dtype=object)
    hub = {r['gtap_geo']: (r['crude_marker'], r['margin_hub']) for r in hubs_cfg}
    miss_hub = sorted(set(geo) - set(hub))
    if miss_hub:
        raise SystemExit(f'product_hubs.csv has no row for {miss_hub}')
    px['pet'] = np.array([ei[hub[g][0]] + ei['margin_' + hub[g][1]] for g in geo])
    psrc['pet'] = np.array([f'EI 2022 {hub[g][0]} + {hub[g][1]} margin' for g in geo], dtype=object)

    def unit_value(lines):
        d = baci[baci['k'].isin(lines) & baci['q'].notna() & (baci['q'] > 0) & (baci['exp'] != baci['imp'])]
        g = d.groupby('exp')[['v', 'q']].sum()
        uv = (g['v'] * 1000.0 / g['q']).reindex(R)     # USD per tonne
        return uv.to_numpy(float), g['v'].reindex(R).fillna(0).to_numpy(float) / 1000.0

    uv_coa, _ = unit_value(coa_hs)
    uv_gas, _ = unit_value(SRC.GAS_HS)
    px['coa'], psrc['coa'] = uv_coa, np.array(['BACI 2022 unit value, S01 coa lines'] * n, dtype=object)
    px['gas'], psrc['gas'] = uv_gas / SRC.LNG_BCM_PER_MT, np.array(['BACI 2022 unit value 271111+271121 / 1.36 bcm per Mt'] * n, dtype=object)
    # gas where the BACI tonnes are a Comtrade estimate: BACI value over an observed volume of the same flows
    gas_baci = baci[baci['k'].isin(SRC.GAS_HS)]
    gas_tonnes = M.gas_tonnes_screen(gas_baci, R, vol['gas']['exports'], SRC.LNG_BCM_PER_MT)
    route_vol, route_chk = {}, []
    for row in gas_obs_cfg:
        if row['method'] == 'baci_route_value_over_ei_route_volume':
            key = (row['route_exporters'], row['route_importer'])
            route_vol[key] = SRC.ei_interregional_gas_2022(ei_path, row['ei_block'], row['ei_row'])
            # the same flow read from the importer's block of the EI table
            route_chk.append((key, route_vol[key], SRC.ei_interregional_gas_2022(ei_path, row['ei_importer_block'], row['ei_block'])))
    gas_obs = M.observed_gas_export_prices(gas_baci, gas_obs_cfg, R, vol['gas']['exports'], route_vol)
    # beta v4 P41 (choice gas_reporter_fob): listed exporters at their own customs' FOB unit value (or the Henry Hub price)
    gas_rep_cfg = C.read_table('gas_export_price_reporter.csv', ('region', 'reporter_code', 'hs_lines', 'decided_by', 'decided_at', 'basis'))
    I(C.CONFIG_DIR + '/gas_export_price_reporter.csv', 'beta v4 P41: gas exporters priced from their own Comtrade FOB report')
    gas_rep_mode = choices['gas_reporter_fob']['value']
    gas_rep = {}
    if gas_rep_mode == C.GAS_REPORTER_FOB:
        lines = sorted({x for row in gas_rep_cfg for x in row['hs_lines'].split(';')})
        ct = {}
        for x in lines:
            f = f'{ct_dir}/comtrade_X_{x}_2022.json'
            I(f, f'UN Comtrade 2022 exports, HS {x} (beta v4 P41)')
            ct[x] = json.load(open(f)).get('data', [])
        gas_rep = M.reporter_fob_gas_prices(gas_rep_cfg, ct, SRC.LNG_BCM_PER_MT)
    elif gas_rep_mode == C.GAS_REPORTER_HH:
        hh = hubs['US Henry Hub']
        p_hh = DOM.usd_mmbtu_to_musd_bcm(hh)
        for row in gas_rep_cfg:
            v_ = float(np.nan_to_num(vol['gas']['exports'][ix[row['region']]])) if row['region'] in ix else 0.0
            gas_rep[row['region']] = dict(price=p_hh, value_musd=p_hh * v_, volume_bcm=v_,
                                          source=f'EI 2025 Gas Prices US Henry Hub 2022, {hh:.4g} USD/MMBtu (beta v4 P41)')
    for r, o in gas_rep.items():
        if r not in ix or r in gas_obs:
            raise SystemExit(f'gas_export_price_reporter.csv: {r} is not a region or is already in gas_export_price_observed.csv')
        gas_obs[r] = o
    for r, o in gas_obs.items():
        px['gas'][ix[r]], psrc['gas'][ix[r]] = o['price'], o['source']
    gas_tonnes['observed_price'] = gas_tonnes['region'].isin(list(gas_obs))
    ely_x_val = old_fob['ely'].sum(1)
    ely_x_twh = np.nan_to_num(vol['ely']['exports'])
    px['ely'] = np.divide(ely_x_val, ely_x_twh, out=np.full(n, np.nan), where=(ely_x_twh > 0) & (ely_x_val > 0))
    psrc['ely'] = np.array(['BACI 2022 HS 271600 value / EIA export TWh'] * n, dtype=object)
    # Fable QA D-02 (choice export_price_by_route): BACI route unit values, USD per natural unit; gas routes whose pipeline
    # tonnes the importer did not report take the EI route volume for that line (choice gas_route_volume_observed)
    gas_rv, gas_rv_rows = {}, []
    gas_uv_rows = gas_baci.copy()
    for row in gas_rv_cfg:
        key = (row['exporter'], row['importer'])
        if not (key[0] in ix and key[1] in ix and row['hs_line'] in SRC.GAS_HS):
            raise SystemExit(f'gas_route_volume_observed.csv: bad row {row}')
        m_ = (gas_uv_rows['exp'] == key[0]) & (gas_uv_rows['imp'] == key[1]) & (gas_uv_rows['k'] == row['hs_line'])
        gas_rv[key] = SRC.ei_interregional_gas_2022(ei_path, row['ei_block'], row['ei_row'])
        gas_rv_rows.append(f'{key[0]}->{key[1]} {row["hs_line"]}: BACI {gas_uv_rows.loc[m_, "q"].sum() / 1e6 * SRC.LNG_BCM_PER_MT:.2f} bcm '
                           f'replaced by EI {gas_rv[key]:.2f} bcm')
        gas_uv_rows.loc[m_, 'q'] = 0.0
    route_uv = {'coa': M.route_unit_values(baci[baci['k'].isin(coa_hs)], R, 1.0),
                'gas': M.route_unit_values(gas_uv_rows, R, 1.0 / SRC.LNG_BCM_PER_MT, gas_rv),
                'oil': M.route_unit_values(baci_vpv[baci_vpv['k'] == '270900'], R, SRC.TOE_PER_BBL_CRUDE),
                'pet': M.route_unit_values(baci_vpv[baci_vpv['k'] == '271000'], R, 1.0 / ei['bbl_per_t_products']),
                'ely': np.full((n, n), np.nan)}       # BACI HS 271600 quantities are not a TWh basis: exporter price only
    route_on = choices['export_price_by_route']['value'] != 'off'
    # beta v4 P13 (choice ras_seed_routes): routes that carried each good in any BACI HS17 year 2017-2024; (choice
    # energy_route_observed, David's call, default off) pipeline and grid routes BACI never records, at their transaction value
    seed_routes_on = C.switched_on(choices, 'ras_seed_routes')
    obs_on = C.switched_on(choices, 'energy_route_observed')
    I(C.CONFIG_DIR + '/energy_route_observed.csv', 'observed pipeline and grid routes with transaction prices (beta v4 P13)')
    obs_cfg = C.read_table('energy_route_observed.csv', C.ENERGY_ROUTE_COLUMNS)
    for row in obs_cfg:
        if row['exporter'] not in ix or row['importer'] not in ix or row['commodity'] not in COMMODITIES or not row['source'].strip() \
                or float(row['volume']) <= 0 or float(row['price']) <= 0 or row['price_unit'] != PRICE_UNIT[row['commodity']]:
            raise SystemExit(f'energy_route_observed.csv: bad row {row}')
    obs_routes = {(ix[r['exporter']], ix[r['importer']], r['commodity']): r for r in obs_cfg} if obs_on else {}
    feasible, baci_years_missing = {}, []
    if seed_routes_on:
        hist, baci_years_missing = SRC.baci_energy_years(baci_zip, 'country_codes_V202601.csv', coa_hs + SRC.GAS_HS + SRC.ELY_HS + SRC.VPV_HS)
        hist['exp'] = hist['exp_iso'].map(iso_region)
        hist['imp'] = hist['imp_iso'].map(iso_region)
        hs_of = {'coa': coa_hs, 'gas': SRC.GAS_HS, 'ely': SRC.ELY_HS, 'oil': ('270900',), 'pet': ('271000',)}
        for c in COMMODITIES:
            feasible[c] = M.baci_feasible_routes(hist[hist['k'].isin(hs_of[c])], R)
        for (i, j, c) in obs_routes:
            feasible[c][i, j] = True

    # Fable QA D-04 (choice reexport_removal): the region's own re-export record, UN Comtrade 2022 RX / X, where its customs
    # report re-exports (every member of a composite; value-weighted), else NaN and the same propensity of §12.2.5
    rx_obs_on = choices['reexport_removal']['value'] == C.REEXPORT_OBSERVED
    ct_rx = SRC.comtrade_reexport_shares_2022(ct_dir, num_iso) if rx_obs_on else {}
    # beta v4 P24 (choice reexport_observed_national; extends D-04): regions outside Comtrade's RX reporters with a national
    # re-export record (CAN: StatCan CIMT) or a labelled zero (MEX), where Comtrade has no row
    I(C.CONFIG_DIR + '/reexport_observed_national.csv', 'national re-export shares of energy exports (beta v4 P24)')
    rx_nat_cfg = C.read_table('reexport_observed_national.csv', C.REEXPORT_NATIONAL_COLUMNS)
    rx_nat = []
    if rx_obs_on and C.switched_on(choices, 'reexport_observed_national'):
        for row in rx_nat_cfg:
            sh = float(row['share'])
            if row['region'] not in ix or row['commodity'] not in COMMODITIES or not 0.0 <= sh <= 1.0 or not row['source'].strip():
                raise SystemExit(f'reexport_observed_national.csv: bad row {row}')
            key = (row['region'], row['commodity'])
            if key in C.SWITCHED_RX_NATIONAL and not C.switched_on(choices, C.SWITCHED_RX_NATIONAL[key]):
                continue          # beta v4 rescan N1: a row behind its own switch, off
            if key not in ct_rx:
                ct_rx[key] = dict(share=sh, basis='national_' + row['region'].lower(), x_musd=np.nan, rx_musd=np.nan)
                rx_nat.append(f'{key[0]} {key[1]} {sh:g}')
    S.check('S11-Rrxnational', 'Beta v4 P24 (choice reexport_observed_national; extends D-04): energy re-export shares from national records '
            'where Comtrade has no RX row (CAN StatCan CIMT; MEX a labelled zero); GTAP 12 ch.12 §12.2.5 warns the same propensity may over-adjust',
            'report', len(rx_nat), '', True, 'reexport_observed_national', '; '.join(rx_nat))
    rx_share = {c: np.full(n, np.nan) for c in COMMODITIES}
    rx_basis = {c: np.array([''] * n, dtype=object) for c in COMMODITIES}
    for c in COMMODITIES:
        for i, r in enumerate(R):
            got = [ct_rx.get((m, c)) for m in members[r]]
            if got and all(g_ is not None for g_ in got):
                rx_share[c][i] = (got[0]['share'] if len(got) == 1 else
                                  sum(g_['rx_musd'] for g_ in got) / max(sum(g_['x_musd'] for g_ in got), 1e-300))
                rx_basis[c][i] = 'comtrade_rx_' + (got[0]['basis'] if len(got) == 1 else 'value')

    # beta v5 I (choice reexport_rule_override): listed cells take the same-propensity rule (§12.2.5) in place of their
    # Comtrade RX share (ITA gas: a share of 0 let the balance lift transit and reverse-flow exports to all of production)
    I(C.CONFIG_DIR + '/reexport_rule_override.csv', 're-export rule overrides (beta v5 I)')
    rx_over = []
    if C.switched_on(choices, 'reexport_rule_override'):
        for row in C.read_table('reexport_rule_override.csv', C.RX_OVERRIDE_COLUMNS):
            if row['region'] not in ix or row['commodity'] not in COMMODITIES or row['rule'] != 'same_propensity':
                raise SystemExit(f'reexport_rule_override.csv: bad row {row}')
            i = ix[row['region']]
            rx_over.append(f"{row['region']} {row['commodity']}: Comtrade share {rx_share[row['commodity']][i]:.4g} -> same propensity")
            rx_share[row['commodity']][i] = np.nan
            rx_basis[row['commodity']][i] = ''
    S.check('S11-Rrxoverride', 'Beta v5 I (choice reexport_rule_override): cells on the same-propensity re-export rule of GTAP 12 ch.12 §12.2.5 '
            'in place of their Comtrade RX share', 'report', len(rx_over), '', True, 'reexport_rule_override', '; '.join(rx_over))

    # ------------------------------------------------------------- 1b. last-resort volumes, 2. re-exports and balance
    fill_rows, rx_rows, bal_rows, sup_rows = [], [], [], []
    su_rows, su_iter, dvol, dmeas = [], {}, {}, {}
    vx, vm, rx = {}, {}, {}
    pfill = {}
    for c in COMMODITIES:
        prod = vol[c]['production'].copy()
        exp, imp = vol[c]['exports'].copy(), vol[c]['imports'].copy()
        # price for an exporter without one: the simple average (needed before the volume fill)
        p_tmp, filled, avg = M.fill_missing_prices(px[c], np.ones(n, bool))
        rowv, colv = old_fob[c].sum(1), (old_fob[c] / np.where(np.isfinite(p_tmp), p_tmp, avg)[:, None]).sum(0)
        for arr, name, implied in ((exp, 'exports', rowv / p_tmp), (imp, 'imports', colv)):
            for i in np.where(np.isnan(arr))[0]:
                val = rowv[i] if name == 'exports' else (old_fob[c][:, i]).sum()
                arr[i] = 0.0          # §12.4.2: the total comes from the energy balance; trade gives only the pattern
                if c == 'oil' and name == 'exports' and no_ref[i] and val > 0 and np.isfinite(implied[i]):
                    arr[i] = implied[i]   # beta v4 P14: the last-resort volume of a producer with no refinery
                    fill_rows.append(dict(region=R[i], commodity=c, flow=name, volume=arr[i], unit=UNIT[c],
                                          value_musd=val, implied_volume=implied[i], flag='LAST-RESORT-EXPORT-VOLUME'))
                    S.flag('LAST-RESORT-EXPORT-VOLUME', f'{R[i]} {c} {name}', f'no volume source and no refinery: S10 VFOB {val:.1f} USD m '
                           f'over the export price, {implied[i]:.4g} {UNIT[c]}', rule='no_refinery_crude_use', citation='GTAP 12 ch.12 §12.2.4')
                    continue
                if val > 0:
                    fill_rows.append(dict(region=R[i], commodity=c, flow=name, volume=0.0, unit=UNIT[c],
                                          value_musd=val, implied_volume=implied[i], flag='BLANK-TRADE-VOLUME'))
                    S.flag('BLANK-TRADE-VOLUME', f'{R[i]} {c} {name}', f'no volume source: booked zero; S10 VFOB {val:.1f} USD m '
                           f'(implied {implied[i]:.4g} {UNIT[c]}) is not used', rule='trade_volume_last_resort', citation='GTAP 12 ch.12 §12.4.2')
        for i in np.where(np.isnan(prod))[0]:
            prod[i] = 0.0
            if (exp[i] > 0) or (old_fob[c][i].sum() > 0):
                S.flag('NO-PRODUCTION-VOLUME', f'{R[i]} {c}', 'production volume blank in every source; booked zero',
                       rule='afg_gas' if (R[i], c) == ('AFG', 'gas') else 'energy_volume_source')
        vol[c]['production_raw'] = prod.copy()
        p0, m0, x0, g, nosup = M.supply_use(prod, imp, exp)
        # the rule before fix round w16 (energy_supply_use_balance off), kept for the before/after report
        xo1, mo1, _ = M.remove_reexports(p0, m0, x0)
        xo2, mo2, _, po2 = M.balance(xo1, mo1, p0)
        two = c in su_scope
        if two:
            # fix round w16, GTAP 12 ch.12 §12.2.4: supply and measured use in opposite senses (regional step)
            p0, m0, x0, d0, a0, nosup, meas = M.supply_use_two_sided(prod, imp, exp, use_vol[c], use_meas[c], surplus_only=su_surplus)
            g = np.where(meas, 1.0, a0)        # the one-sided factor of unmeasured regions, flagged below as before
        for i in np.where((g > 1) | nosup)[0]:
            what = (f'exports {exp[i]:.4g} with no production or imports: set to zero' if nosup[i] else
                    f'exports {exp[i]:.4g} > P {prod[i]:.4g} + M {imp[i]:.4g}: P, M x {g[i]:.4f}, X / {g[i]:.4f}')
            sup_rows.append(dict(region=R[i], commodity=c, unit=UNIT[c], production=prod[i], imports=imp[i], exports=exp[i],
                                 factor=g[i], production_after=p0[i], imports_after=m0[i], exports_after=x0[i],
                                 step='no_supply_exports_zero' if nosup[i] else 'opposite_rescaling'))
            S.flag('SUPPLY-USE-RESCALE', f'{R[i]} {c}', what, rule='supply_use_balance', citation='GTAP 12 ch.12 §12.2.4')
        r_sp = M.remove_reexports(p0, m0, x0)[2]          # the same propensity, reported beside the rule used
        x1, m1, r1, r_obs = M.remove_reexports_observed(p0, m0, x0, rx_share[c])
        if two:
            # both rescalings at once (§12.2.4): world exports = world imports and supply = use in measured regions
            x2, m2, f, p2, d2, a1, su_it = M.balance_joint(x1, m1, p0, d0, meas)
            su_iter[c] = su_it
            dvol[c], dmeas[c] = d2, meas
            for i in range(n):
                su_rows.append(dict(region=R[i], commodity=c, unit=UNIT[c], measured_use=bool(meas[i]),
                                    production_raw=prod[i], imports_raw=imp[i], exports_raw=exp[i], domestic_use_raw=use_vol[c][i] if use_meas[c][i] else np.nan,
                                    regional_factor=a0[i] if meas[i] else np.nan, joint_factor=a1[i] if meas[i] else np.nan,
                                    supply_use_factor=a0[i] * a1[i] if meas[i] else np.nan, world_export_factor=f, reexports=r1[i],
                                    production_before=po2[i], imports_before=mo2[i], exports_before=xo2[i], absorption_before=po2[i] + mo2[i] - xo2[i],
                                    production_after=p2[i], imports_after=m2[i], exports_after=x2[i], absorption_after=p2[i] + m2[i] - x2[i],
                                    domestic_use_after=d2[i]))
            bound = (~meas) & (np.abs(p2 - p0) > 1e-12 * np.maximum(p0, 1))
        else:
            x2, m2, f, p2 = M.balance(x1, m1, p0)
            bound = np.abs(p2 - p0) > 1e-12 * np.maximum(p0, 1)
        for i in np.where(bound)[0]:
            sup_rows.append(dict(region=R[i], commodity=c, unit=UNIT[c], production=p0[i], imports=m1[i], exports=x1[i],
                                 factor=p2[i] / p0[i], production_after=p2[i], imports_after=m2[i], exports_after=x2[i],
                                 step='world_balance_bound_domestic_exports_le_production'))
        vol[c]['production'] = prod = p2
        vx[c], vm[c], rx[c] = x2, m2, r1
        for i in range(n):
            if r1[i] > 0 or r_sp[i] > 0:
                rx_rows.append(dict(region=R[i], commodity=c, unit=UNIT[c], production=p0[i], imports=m0[i], exports=x0[i],
                                    reexports=r1[i], exports_domestic=x1[i], imports_net=m1[i],
                                    basis=rx_basis[c][i] if r_obs[i] else 'same_propensity', observed_share=rx_share[c][i],
                                    reexports_same_propensity=r_sp[i]))
        bal_rows.append(dict(commodity=c, unit=UNIT[c], world_exports_raw=np.nansum(exp), world_imports_raw=np.nansum(imp),
                             world_exports_supply_use=x0.sum(), world_imports_supply_use=m0.sum(),
                             reexports_removed=r1.sum(), world_exports_before=x1.sum(), world_imports_before=m1.sum(),
                             export_factor=f, import_factor=1 / f, world_after=x2.sum(),
                             world_production_raw=np.nansum(vol[c]['production_raw']), world_production_after=p2.sum()))
        vol[c]['exports'], vol[c]['imports'] = exp, imp
        px[c], pfill[c], _ = M.fill_missing_prices(px[c], x2 > 0)
        for i in np.where(pfill[c])[0]:
            psrc[c][i] = 'simple average of exporters (ch.12 p.19)'

    # ------------------------------------------------------------- 4. RAS
    # Fable QA D-02: each route at its own BACI unit value where it has one (choice export_price_by_route), so the S10
    # values survive the RAS where the volumes agree; gas origin of the gas_import_origin importers from Eurostat
    obs_gas = np.array([r in gas_obs for r in R])
    pxr, at_uv, px_ref = {}, {}, {c: px[c].copy() for c in COMMODITIES}
    for c in COMMODITIES:
        if route_on:
            pxr[c], at_uv[c] = M.route_prices(px[c], route_uv[c], at_reference=obs_gas if c == 'gas' else None)
        else:
            pxr[c], at_uv[c] = np.repeat(px[c][:, None], n, axis=1), np.zeros((n, n), bool)
    # beta v4 P25 (choice gas_line_mix_price; extends D-02): an at-reference gas exporter with EIA prices by line takes, route
    # by route, the pipeline and LNG prices weighted by the route's BACI 271121 / 271111 value split
    I(C.CONFIG_DIR + '/gas_line_prices_2022.csv', 'EIA 2022 gas export prices by line (beta v4 P25)')
    line_cfg = C.read_table('gas_line_prices_2022.csv', C.GAS_LINE_COLUMNS)
    line_rep = []
    if route_on and C.switched_on(choices, 'gas_line_mix_price'):
        for row in line_cfg:
            e = row['exporter']
            if e not in ix or row['price_unit'] != PRICE_UNIT['gas']:
                raise SystemExit(f'gas_line_prices_2022.csv: bad row {row}')
            if not obs_gas[ix[e]]:
                continue                  # only exporters priced at their reference on every route
            pr, w = M.line_mix_route_prices(gas_uv_rows, R, e, float(row['pipeline_price']), float(row['lng_price']))
            i = ix[e]
            keep = np.isfinite(pr)
            pxr['gas'][i, keep], at_uv['gas'][i, keep] = pr[keep], True
            line_rep.append(f'{e}: pipeline {row["pipeline_price"]}, LNG {row["lng_price"]} {PRICE_UNIT["gas"]}; reference {px["gas"][i]:.4g}; '
                            + ' '.join(f'{R[j]} {pr[j]:.0f} (pipe {w[j]:.2f})' for j in np.argsort(-old_fob['gas'][i])[:6]))
    S.check('S11-Rgasline', 'Beta v4 P25 (choice gas_line_mix_price; extends D-02): at-reference gas exporters priced by route at the EIA 2022 '
            'pipeline and LNG export prices weighted by the route\'s BACI 271121 / 271111 value split (largest S10 routes)', 'report',
            len(line_rep), '', True, 'gas_line_mix_price', '; '.join(line_rep))
    # beta v4 P13 (choice energy_route_observed): the observed routes at their transaction value, outside the band
    for (i, j, c), row in obs_routes.items():
        pxr[c][i, j], at_uv[c][i, j] = float(row['price']), True
    org_rows = []
    org_on = choices['gas_import_origin']['value'] != 'off'
    for row in (gas_org_cfg if org_on else []):
        j = ix[row['importer']]
        named, nsp, mirror, tot = SRC.eurostat_gas_partners_2022(es_ti, es_te, row['eurostat_geo'], a2_iso)
        seed = M.eurostat_origin_seed(named, nsp, mirror)
        col = np.zeros(n)
        for iso_, v in seed.items():
            rr = iso_region.get(iso_)
            if rr in ix and rr != row['importer']:
                col[ix[rr]] += v
        org_rows.append(dict(importer=row['importer'], total_bcm=tot, named_bcm=sum(named.values()), nsp_bcm=nsp,
                             seed=' '.join(f'{R[i]} {col[i]:.3f}' for i in np.argsort(-col) if col[i] > 0)))
        old_fob_col = old_fob['gas'][:, j].copy()
        org_rows[-1]['baci_seed_before'] = ' '.join(f'{R[i]} {old_fob_col[i] / pxr["gas"][i, j]:.3f}'
                                                    for i in np.argsort(-old_fob_col)[:6] if old_fob_col[i] > 0)
        org_rows[-1]['col'] = col
    # beta v4 dry run on 165d46b (S11-Hras, S11-Hseedgate, S11-Hscalegate): electricity trades only over a grid link (choice
    # ely_grid_routes), reviewed routes are added, blocked or accepted (route_review), crude relabelled at sea is moved to
    # its origin (relabelled_origin), and the vectors are made consistent with the allowed routes before the RAS
    # (ras_feasible_vectors). Each is our choice: GTAP 12 §12.4.2 p.25 seeds every zero, so it never meets these limits.
    grid_on = seed_routes_on and C.switched_on(choices, 'ely_grid_routes')
    review_on = seed_routes_on and C.switched_on(choices, 'route_review')
    relabel_on = C.switched_on(choices, 'relabelled_origin')
    fv_on = seed_routes_on and C.switched_on(choices, 'ras_feasible_vectors')
    # beta v5 E1 + R (choice ras_route_caps): RAS with route bounds; mirror-only regions are those none of whose members
    # reports any 2022 energy export to UN Comtrade (their energy trade is known only from partners' mirror records)
    caps_on = seed_routes_on and C.switched_on(choices, 'ras_route_caps')
    reporters = SRC.comtrade_energy_reporters_2022(ct_dir, num_iso)
    mirror_only = np.array([not any(m in reporters for m in members[r]) for r in R])
    # beta v5 E3 (choice physical_energy_routes): electricity only over grid links at any size; listed pipeline-only exporters
    phys_on = seed_routes_on and C.switched_on(choices, 'physical_energy_routes')
    I(C.CONFIG_DIR + '/gas_pipeline_only.csv', 'pipeline-only gas exporters (beta v5 E3)')
    pipe_only = {}
    if phys_on:
        for row in C.read_table('gas_pipeline_only.csv', C.PIPELINE_ONLY_COLUMNS):
            dests = [d for d in row['importers'].split(';') if d]
            if row['exporter'] not in ix or row['commodity'] not in COMMODITIES or any(d not in ix for d in dests):
                raise SystemExit(f'gas_pipeline_only.csv: bad row {row}')
            pipe_only[(ix[row['exporter']], row['commodity'])] = {ix[d] for d in dests}
    # beta v5 E2 (choice census_route_hold): listed US import routes held at the Census IMDB 2022 customs value
    I(C.CONFIG_DIR + '/census_route_hold.csv', 'US import routes held at Census customs value (beta v5 E2)')
    census_hold = {}
    if seed_routes_on and C.switched_on(choices, 'census_route_hold'):
        census_val = SRC.census_imdb_values_2022(I(DATA + '/census_imdb_2022/hs6_cty_rp_2022.csv',
                                                   'US Census IMDB 2022 imports by HS6 and country (beta v5 E2)'))
        for row in C.read_table('census_route_hold.csv', C.CENSUS_HOLD_COLUMNS):
            if row['exporter'] not in ix or row['importer'] != 'USA' or row['commodity'] not in COMMODITIES:
                raise SystemExit(f'census_route_hold.csv: bad row {row}')
            v_ = sum(census_val.get((h, row['census_cty']), 0.0) for h in row['hs_lines'].split(';'))
            if v_ <= 0:
                raise SystemExit(f'census_route_hold.csv: no Census value for {row}')
            census_hold[(ix[row['exporter']], ix['USA'], row['commodity'])] = v_
    grid = None
    if grid_on:
        rc_path = I(DATA + '/restcountries/countries.json', 'land borders (mledoze/countries) for electricity grid routes')
        borders = {x['cca3']: x.get('borders', []) for x in json.load(open(rc_path))}
        I(C.CONFIG_DIR + '/ely_cable_links.csv', 'listed electricity interconnectors (beta v4 dry run)')
        links = [(x['country_a'], x['country_b']) for x in C.read_table('ely_cable_links.csv', C.GRID_COLUMNS)]
        grid = M.grid_routes(R, members, borders, links)
        listed_links = M.grid_routes(R, members, {}, links)
    review = {}
    if review_on:
        I(C.CONFIG_DIR + '/route_review.csv', 'reviewed energy routes: feasible, block or accept (beta v4 dry run)')
        for row in C.read_table('route_review.csv', C.REVIEW_COLUMNS):
            if row['exporter'] not in ix or row['importer'] not in ix or row['commodity'] not in COMMODITIES \
                    or row['action'] not in C.REVIEW_ACTIONS or not row['basis'].strip():
                raise SystemExit(f'route_review.csv: bad row {row}')
            review[(ix[row['exporter']], ix[row['importer']], row['commodity'])] = row
    relabel_cfg = []
    if relabel_on:
        I(C.CONFIG_DIR + '/relabelled_routes.csv', 'crude relabelled in ship-to-ship transfers (beta v4 dry run)')
        relabel_cfg = C.read_table('relabelled_routes.csv', C.RELABEL_COLUMNS)
        for row in relabel_cfg:
            if row['hub'] not in ix or row['destination'] not in ix or row['commodity'] not in COMMODITIES \
                    or any(o not in ix for o in row['origins'].split(';')):
                raise SystemExit(f'relabelled_routes.csv: bad row {row}')
    exi, new_fob, seeded, ras_rows, prior, released = {}, {}, {}, [], {}, {}
    gate_ok, noise_rows, grid_rows, fv_rows, relabel_rows, review_rows = {}, [], [], [], [], []
    cap_rows, spill_rows, hold_rows, pipe_rows, capfix, capseed_rows = [], [], [], [], {}, []
    for c in COMMODITIES:
        A0 = old_fob[c] / pxr[c]
        if c == 'gas':
            for o in org_rows:
                A0[:, ix[o['importer']]] = o['col']
        for (i, j, cc_), row in obs_routes.items():
            if cc_ == c:
                A0[i, j] = max(A0[i, j], float(row['volume']))
        ok_gate = {(i, j) for (i, j, cc_) in obs_routes if cc_ == c}
        fmask = None
        hold = np.zeros((n, n), bool)
        blocked = np.zeros((n, n), bool)
        if seed_routes_on:
            F = feasible[c].copy()
            fob0 = A0 * pxr[c]
            prefer = F | (A0 > 0)
            # a prior below RAS_PRIOR_FLOOR_MUSD is customs noise (NLD to AUT gas 0.4 m): it competes as a seed, not a prior
            noise = (A0 > 0) & (fob0 < C.RAS_PRIOR_FLOOR_MUSD) & ~np.eye(n, dtype=bool)
            for (i, j) in ok_gate:
                noise[i, j] = False
            noise_rows.append((c, int(noise.sum()), float(fob0[noise].sum())))
            A0 = np.where(noise, 0.0, A0)
            if grid_on and c == 'ely':
                off = (~grid) & (A0 > 0) & ~np.eye(n, dtype=bool)
                keep = off & (fob0 >= C.ELY_GRID_MUSD) & (not phys_on)     # beta v5 E3: no off-grid route at any size
                for (i, j) in ok_gate:                      # an observed route (ISR to PAL) is a grid link by observation
                    keep[i, j] = keep[i, j] or bool(off[i, j])
                grid_rows.append((int((off & ~keep).sum()), float(fob0[off & ~keep].sum()),
                                  [f'{R[i]}->{R[j]} {fob0[i, j]:.0f}' for i, j in np.argwhere(keep)]))
                A0 = np.where(off & ~keep, 0.0, A0)
                F = grid | keep
                prefer = (feasible[c] & grid) | listed_links | (A0 > 0)
                ok_gate |= {(i, j) for i, j in np.argwhere(grid)}
                blocked |= ~F
            for (i, cc_), dests in pipe_only.items():      # beta v5 E3: a pipeline-only exporter ships only to its listed importers
                if cc_ == c:
                    rest = np.array([k not in dests for k in range(n)]) & (np.arange(n) != i)
                    pipe_rows.append(f'{c} {R[i]}: dropped {float((A0[i, rest] * pxr[c][i, rest]).sum()):.1f} USD m of priors, '
                                     f'{int((F[i, rest] & ~(A0[i, rest] > 0)).sum())} feasible seeds; only to {" ".join(R[k] for k in sorted(dests)) or "none"}')
                    A0[i, rest], F[i, rest], prefer[i, rest] = 0.0, False, False
                    blocked[i, rest] = True
            only = {}
            for (i, j, cc_), row in review.items():
                if cc_ == c and row['action'] == 'only':
                    only.setdefault(j, set()).add(i)
            for j, src in only.items():         # the importer takes this good only from the listed exporters
                rest = np.array([k not in src for k in range(n)]) & (np.arange(n) != j)
                A0[rest, j], F[rest, j], prefer[rest, j] = 0.0, False, False
                blocked[rest, j] = True
            for (i, j, cc_), row in review.items():
                if cc_ != c:
                    continue
                act = row['action']
                if act == 'only':
                    F[i, j] = prefer[i, j] = True
                    ok_gate.add((i, j))
                elif act == 'block':
                    A0[i, j], F[i, j], prefer[i, j] = 0.0, False, False
                    blocked[i, j] = True
                elif act == 'reference':
                    # beta v5 R: a route whose BACI unit value is a quantity defect inside the band is priced at the
                    # exporter's reference; gate-exempt like accept
                    pxr[c][i, j], at_uv[c][i, j] = px[c][i], False
                    ok_gate.add((i, j))
                elif act == 'hold':
                    # beta v5 R: the route fixed at its prior volume (or prior_volume) through the RAS
                    v_ = float(row['prior_volume']) if (row['prior_volume'] or '').strip() else A0[i, j]
                    if not v_ > 0:
                        raise SystemExit(f'route_review.csv: hold {c} {R[i]}->{R[j]} has no prior volume')
                    hold_rows.append(f'{c} {R[i]}->{R[j]} held at {v_:.4g} {UNIT[c]} ({v_ * pxr[c][i, j]:.1f} USD m; prior {A0[i, j]:.4g})')
                    A0[i, j], F[i, j], prefer[i, j], hold[i, j] = v_, True, True, True
                    ok_gate.add((i, j))
                elif act == 'feasible':
                    F[i, j] = prefer[i, j] = True
                    if float(row['prior_volume'] or 0) > 0:
                        A0[i, j] = max(A0[i, j], float(row['prior_volume']))
                    ok_gate.add((i, j))
                else:
                    ok_gate.add((i, j))
                review_rows.append(f'{c} {R[i]}->{R[j]} {act}')
            for (i, j, cc_), v_ in census_hold.items():    # beta v5 E2: held at the Census customs value over the route price
                if cc_ == c:
                    vol_ = v_ / pxr[c][i, j]
                    hold_rows.append(f'{c} {R[i]}->{R[j]} held at Census {v_:.1f} USD m = {vol_:.4g} {UNIT[c]} (prior {A0[i, j] * pxr[c][i, j]:.1f} USD m)')
                    A0[i, j], F[i, j], prefer[i, j], hold[i, j] = vol_, True, True, True
                    ok_gate.add((i, j))
            if relabel_on:
                for row in relabel_cfg:
                    if row['commodity'] == c:
                        h, d = ix[row['hub']], ix[row['destination']]
                        orig = [ix[o] for o in row['origins'].split(';')]
                        moved = M.relabelled_origin(A0, h, d, orig, vx[c])
                        for o, v in moved.items():
                            F[o, d] = prefer[o, d] = True
                            ok_gate.add((o, d))
                        relabel_rows.append(f'{c} {row["hub"]}->{row["destination"]}: ' + (', '.join(f'{R[o]} {v:.3g}' for o, v in moved.items()) or 'nothing moved')
                                            + f' {UNIT[c]}')
            # beta v5 E1 + R + E2: the route bounds, known before the feasibility repair so it cuts what they cannot carry
            cap = (M.route_caps(A0, pxr[c], c, C.CAP_GOODS, C.CAP_FACTOR, C.RAS_GATE_MUSD, mirror_only, C.RAS_GATE_SCALE, ok_gate)
                   if caps_on else np.full((n, n), np.inf))
            cap = np.where(hold, A0, cap)
            if fv_on:
                sup = F | (A0 > 0) | np.diag(~single)
                x2, m2, Z = M.feasible_vectors(sup, vx[c], vm[c], prefer=prefer, lower=np.where(hold, A0, 0.0),
                                               upper=cap if (caps_on or hold.any()) else None)
                cx, cm = vx[c] - x2, vm[c] - m2
                fv_rows.append(dict(commodity=c, cut=float(cx.sum()), world=float(vx[c].sum()), forced_zero=int(Z.sum()),
                                    forced_zero_musd=float((A0 * pxr[c])[Z].sum()),
                                    exporters=', '.join(f'{R[i]} {cx[i]:.3g}' for i in np.argsort(-cx)[:8] if cx[i] > 1e-9),
                                    importers=', '.join(f'{R[j]} {cm[j]:.3g}' for j in np.argsort(-cm)[:8] if cm[j] > 1e-9)))
                for i in np.where(cx > 1e-9)[0]:
                    S.flag('RAS-FEASIBLE-CUT', f'{c} {R[i]} exports', f'{cx[i]:.4g} {UNIT[c]} no allowed route can carry; kept at home', rule='ras_feasible_vectors')
                for j in np.where(cm > 1e-9)[0]:
                    S.flag('RAS-FEASIBLE-CUT', f'{c} {R[j]} imports', f'{cm[j]:.4g} {UNIT[c]} no allowed route can supply; absorption lower', rule='ras_feasible_vectors')
                if c in dvol:
                    dvol[c] = dvol[c] + cx - cm          # the cut stays in (leaves) domestic use, so supply = use still holds
                vx[c], vm[c] = x2, m2
                A0 = np.where(Z, 0.0, A0)
                F = F & ~Z
            fmask, rel_r, rel_c = M.feasible_seed_mask(A0, vx[c], vm[c], F, ~single)
            released[c] = ([R[i] for i in rel_r], [R[j] for j in rel_c])
        gate_ok[c] = ok_gate
        A, sd = M.seed_matrix(A0, vx[c], vm[c], allow_diag=~single, eps=SEED_EPS, feasible=fmask)
        if caps_on or hold.any():
            # beta v5 E1 + R + E2: bounded RAS; held routes fixed, capped routes at most their bound, spills to plain seeds
            hold_ = hold & (A > 0)
            A = np.where(hold_, A0, A)
            spill_ok = ~blocked & ~(np.eye(n, dtype=bool) & single[:, None])
            seed_all = SEED_EPS * np.outer(vx[c], vm[c] / max(vm[c].sum(), 1e-300))
            A1, fixed, spilled, it, err = M.capped_ras(A, vx[c], vm[c], cap, spill_ok=spill_ok, seed=seed_all, hold=hold_)
            capfix[c] = fixed & ~hold_
            sd = sd | spilled
            for i, j in np.argwhere(capfix[c]):
                cap_rows.append((c, R[i], R[j], float(A0[i, j] * pxr[c][i, j]), float(A1[i, j] * pxr[c][i, j]), float(A1[i, j] / A0[i, j])))
            for i, j in np.argwhere(spilled & (A1 * pxr[c] > SEED_REPORT_MUSD)):
                spill_rows.append((c, R[i], R[j], float(A1[i, j] * pxr[c][i, j])))
            ok_gate |= {(i, j) for i, j in np.argwhere(spilled)}
            # a seed above the gate in the row or column of a capped or held route carries volume the bound took off a
            # recorded route (E2: the US gas import residual of the world balance beyond the Census routes); it is on a route
            # with BACI 2017-2024 trade (the seed mask), reported in S11-Rcapped, not failed
            rc_, cc_ = (capfix[c] | hold_).any(1), (capfix[c] | hold_).any(0)
            for i, j in np.argwhere(sd & ~spilled & (rc_[:, None] | cc_[None, :]) & (A1 * pxr[c] > C.RAS_GATE_MUSD)):
                capseed_rows.append((c, R[i], R[j], float(A1[i, j] * pxr[c][i, j])))
                ok_gate.add((i, j))
        else:
            A1, it, err = M.ras(A, vx[c], vm[c])
        exi[c], seeded[c], prior[c] = A1, sd, A0
        new_fob[c] = A1 * pxr[c]
        px[c] = M.realised_export_price(new_fob[c], A1, px[c])
        ras_rows.append(dict(commodity=c, iterations=it, max_rel_error=err, seeded_cells=int(sd.sum()),
                             seeded_value_musd=float(new_fob[c][sd].sum()), old_fob_musd=old_fob[c].sum(), new_fob_musd=new_fob[c].sum()))
        big = np.argwhere(sd & (new_fob[c] > SEED_REPORT_MUSD))
        for i, j in big:
            S.flag('RAS-SEED', f'{c} {R[i]}->{R[j]}', f'{new_fob[c][i, j]:.1f} USD m from a seed', rule='ras_seed')
    # beta v4 P13 (choice ras_seed_routes): hard gates on the RAS result. A seeded route above RAS_GATE_MUSD, or a prior route
    # above it that the RAS scaled more than RAS_GATE_SCALE times, fails unless it is an observed route
    gate_s, gate_x = [], []
    col_scaled = []
    for c in COMMODITIES:
        expl = gate_ok[c]
        sb, xb = M.route_gates(prior[c], exi[c], new_fob[c], seeded[c], expl, C.RAS_GATE_MUSD, C.RAS_GATE_SCALE,
                               basis=C.RAS_GATE_BASIS if seed_routes_on else 'volume')
        _sv, xv = M.route_gates(prior[c], exi[c], new_fob[c], seeded[c], expl, C.RAS_GATE_MUSD, C.RAS_GATE_SCALE)
        hit = {(i, j) for i, j, *_ in xb}
        col_scaled += [(c, R[i], R[j], v, f) for i, j, v, f in xv if (i, j) not in hit]
        gate_s += [(c, R[i], R[j], v) for i, j, v, _f in sb]
        gate_x += [(c, R[i], R[j], v, f) for i, j, v, f in xb]
    gate_kind = 'hard' if seed_routes_on else 'report'
    if caps_on:
        vc = []
        for c in COMMODITIES:
            vc += [(c, R[i], R[j], v, f) for i, j, v, f in M.volume_cap_breaches(
                prior[c], exi[c], new_fob[c], gate_ok[c], C.RAS_GATE_MUSD, C.CAP_GOODS, c, C.CAP_FACTOR, mirror_only, C.RAS_GATE_SCALE)]
        S.check('S11-Hvolcap', f'Beta v5 E1 + R (choice ras_route_caps): no oil or pet prior route above {C.RAS_GATE_MUSD:g} USD m whose volume the '
                f'RAS raised more than {C.CAP_FACTOR:g} times, and no route with a mirror-only partner (no 2022 Comtrade energy report: '
                f'{" ".join(r for r, mo in zip(R, mirror_only) if mo)}) above it raised more than {C.RAS_GATE_SCALE:g} times, unless observed, '
                'reviewed, relabelled, grid or spilled', 'hard', len(vc), '0', not vc, 'ras_route_caps',
                '; '.join(f'{c} {a}->{b} {v:.0f} (x{f:.1f})' for c, a, b, v, f in sorted(vc, key=lambda x: -x[3])[:40]))
        S.check('S11-Rcapped', 'Beta v5 E1 + R: prior routes the bounded RAS held at their bound, USD m prior -> after (largest 40), and routes '
                'opened by a spill (an exporter or importer whose capped routes could not carry its volume)', 'report', len(cap_rows), '', True,
                'ras_route_caps', f'{len(cap_rows)} capped, {sum(r[4] for r in cap_rows) / 1e3:.1f} bn after; '
                + '; '.join(f'{c} {a}->{b} {p_:.0f} -> {q_:.0f} (x{f:.1f})' for c, a, b, p_, q_, f in sorted(cap_rows, key=lambda x: -x[4])[:40])
                + ('; spilled: ' + '; '.join(f'{c} {a}->{b} {v:.0f}' for c, a, b, v in sorted(spill_rows, key=lambda x: -x[3])[:30]) if spill_rows else '; no spill')
                + (f'; seeds above {C.RAS_GATE_MUSD:g} USD m in a capped or held row or column (BACI 2017-2024 routes, exempt from S11-Hseedgate): '
                   + '; '.join(f'{c} {a}->{b} {v:.0f}' for c, a, b, v in sorted(capseed_rows, key=lambda x: -x[3])) if capseed_rows else ''))
    if hold_rows or census_hold:
        S.check('S11-Rhold', 'Beta v5 R and E2: routes held through the RAS (route_review hold rows at the exporter\'s own record; US import '
                'routes at the Census IMDB 2022 customs value)', 'report', len(hold_rows), '', True, 'census_route_hold',
                '; '.join(hold_rows) + '; after RAS: ' + '; '.join(
                    f'{c} {R[i]}->{R[j]} {new_fob[c][i, j]:.1f} USD m' for (i, j, c) in census_hold))
    if phys_on:
        S.check('S11-Rphysical', 'Beta v5 E3 (choice physical_energy_routes): electricity only over a land border or a listed interconnector at any '
                'size; pipeline-only gas exporters ship only to their listed importers (config/s11/gas_pipeline_only.csv)', 'report',
                len(pipe_rows), '', True, 'physical_energy_routes', '; '.join(pipe_rows) + '; after RAS: ' + '; '.join(
                    f'{c} {R[i]} exports {exi[c][i].sum():.4g} {UNIT[c]}' for (i, c) in pipe_only))
    S.check('S11-Hseedgate', f'Beta v4 P13 (choice ras_seed_routes): no RAS-seeded energy route above {C.RAS_GATE_MUSD:g} USD m (seeds only on '
            'routes with a BACI HS17 flow in 2017-2024 or an observed route; exporters or importers with no such route are released '
            'to the plain seed and listed)', gate_kind, len(gate_s), '0', len(gate_s) == 0, 'ras_seed_routes',
            '; '.join(f'{c} {a}->{b} {v:.0f}' for c, a, b, v in sorted(gate_s, key=lambda x: -x[3])[:30])
            + ('; released: ' + '; '.join(f'{c} exporters {" ".join(r[0]) or "-"} importers {" ".join(r[1]) or "-"}'
                                          for c, r in released.items() if r[0] or r[1]) if released else '')
            + (f'; BACI years missing from the zip: {baci_years_missing}' if baci_years_missing else ''))
    S.check('S11-Hscalegate', f'Beta v4 P13 (choice ras_seed_routes): no prior energy route above {C.RAS_GATE_MUSD:g} USD m after the RAS whose '
            f'share of its importer\'s imports the RAS raised more than {C.RAS_GATE_SCALE:g} times (beta v4 dry run: the share, not the volume, '
            'so an importer whose customs under-record every supplier passes; observed, reviewed and grid routes exempt)', gate_kind, len(gate_x), '0',
            len(gate_x) == 0, 'ras_seed_routes',
            '; '.join(f'{c} {a}->{b} {v:.0f} (x{f:.0f})' for c, a, b, v, f in sorted(gate_x, key=lambda x: -x[3])[:40]))
    if seed_routes_on:
        S.check('S11-Rcolscale', f'Prior routes above {C.RAS_GATE_MUSD:g} USD m scaled more than {C.RAS_GATE_SCALE:g} times in volume but not in '
                'importer share (the importer\'s recorded imports cover a small part of its volume; the RAS scales its suppliers alike, '
                'GTAP 12 §12.4.2)', 'report', len(col_scaled), '', True, 'ras_seed_routes',
                '; '.join(f'{c} {a}->{b} {v:.0f} (x{f:.0f})' for c, a, b, v, f in sorted(col_scaled, key=lambda x: -x[3])[:40]))
        S.check('S11-Rnoise', f'Prior routes below {C.RAS_PRIOR_FLOOR_MUSD:g} USD m entered as seeds, not priors (beta v4 dry run)', 'report',
                sum(r[1] for r in noise_rows), '', True, 'ras_seed_routes',
                '; '.join(f'{c} {k} cells {v:.1f} USD m' for c, k, v in noise_rows))
    if grid_on:
        S.check('S11-Relygrid', 'Electricity routes (beta v4 dry run; choice ely_grid_routes): only between regions with a land border or a listed '
                f'interconnector; off-grid BACI routes below {C.ELY_GRID_MUSD:g} USD m dropped, larger ones kept', 'report',
                grid_rows[0][0] if grid_rows else 0, '', True, 'ely_grid_routes',
                (f'dropped {grid_rows[0][0]} routes, {grid_rows[0][1]:.1f} USD m; kept: ' + ', '.join(grid_rows[0][2])) if grid_rows else '')
    if review_on:
        S.check('S11-Rreview', 'Reviewed routes (beta v4 dry run; choice route_review; config/s11/route_review.csv): feasible (seeded and '
                'gate-exempt), block (no trade), accept (gate-exempt)', 'report', len(review_rows), '', True, 'route_review', '; '.join(review_rows))
    if relabel_on:
        S.check('S11-Rrelabel', 'Relabelled crude (beta v4 dry run; choice relabelled_origin; labelled departure): the hub\'s prior exports above its '
                'own export volume moved to the listed origins', 'report', len(relabel_rows), '', True, 'relabelled_origin', '; '.join(relabel_rows))
    if fv_on:
        worst = max((r['cut'] / r['world'] for r in fv_rows if r['world'] > 0), default=0.0)
        S.check('S11-Hfeascut', f'Feasibility repair (beta v4 dry run; choice ras_feasible_vectors): export and import volume no allowed route can '
                f'carry, cut and kept in domestic use, at most {C.FEASIBLE_CUT_MAX:.0%} of world trade of each good; routes that no consistent '
                'flow can use are left out of the RAS', 'hard', f'{worst:.4f}', f'{C.FEASIBLE_CUT_MAX}', worst <= C.FEASIBLE_CUT_MAX,
                'ras_feasible_vectors',
                '; '.join(f'{r["commodity"]} cut {r["cut"]:.4g} of {r["world"]:.4g} {UNIT[r["commodity"]]} (exporters {r["exporters"] or "-"}; '
                          f'importers {r["importers"] or "-"}); {r["forced_zero"]} routes out ({r["forced_zero_musd"]:.1f} USD m)' for r in fv_rows))
    if obs_on:
        S.check('S11-Robsroute', 'Beta v4 P13 (choice energy_route_observed): observed pipeline and grid routes at their transaction value; the '
                'discount against the exporter reference price is reported, not booked (BPM6 3.79; GTAP 12 ch.7 has no transfer account)',
                'report', len(obs_routes), '', True, 'energy_route_observed',
                '; '.join(f'{c} {R[i]}->{R[j]}: {exi[c][i, j]:.3g} {UNIT[c]} at {pxr[c][i, j]:.4g} = {new_fob[c][i, j]:.0f} USD m, '
                          f'discount {(px_ref[c][i] - pxr[c][i, j]) * exi[c][i, j]:.0f} USD m (reference {px_ref[c][i]:.4g})'
                          for (i, j, c) in obs_routes))
    S.check('S11-Hras', 'RAS bilateral volumes match the balanced export and import vectors (1e-6 relative) for every commodity', 'hard',
            max(r['max_rel_error'] for r in ras_rows), '1e-6',
            all(r['max_rel_error'] < 1e-6 for r in ras_rows), 'energy_trade_scope',
            '; '.join(f'{r["commodity"]} {r["iterations"]} it, err {r["max_rel_error"]:.1e}' for r in ras_rows))
    # Fable QA D-02: the export price is now the exporter's VFOB over its volume; the reference (§12.3) prices the routes
    # without a BACI unit value
    route_rep = []
    for c in COMMODITIES:
        own = float(new_fob[c][at_uv[c]].sum())
        route_rep.append(f'{c} {bn(own):.1f} of {bn(new_fob[c].sum()):.1f} bn at route unit values')
        for i in range(n):
            if (exi[c][i] > 0).any() and at_uv[c][i][exi[c][i] > 0].any():
                psrc[c][i] = (f'VFOB / volume over its routes: BACI 2022 route unit values on {bn(new_fob[c][i][at_uv[c][i]].sum()):.3f} of '
                              f'{bn(new_fob[c][i].sum()):.3f} bn, the rest at {psrc[c][i]} ({px_ref[c][i]:.4g})')
    S.check('S11-Rroute', 'Fable QA D-02 (choice export_price_by_route): routes valued at their own BACI 2022 unit value (within '
            f'{M.ROUTE_BAND[0]:.3g}-{M.ROUTE_BAND[1]:g} x the exporter reference price), the rest at the reference; RUS before -> after', 'report',
            '; '.join(route_rep), '', True, 'export_price_by_route',
            '; '.join(f'RUS {c} {bn(float(exi[c][ix["RUS"]].sum() * px_ref[c][ix["RUS"]])):.1f} -> {bn(float(new_fob[c][ix["RUS"]].sum())):.1f} bn '
                      f'(S10 {bn(float(old_fob[c][ix["RUS"]].sum())):.1f})' for c in COMMODITIES)
            + ('; gas route volumes: ' + '; '.join(gas_rv_rows) if gas_rv_rows else ''))
    S.check('S11-Rgasorigin', 'Fable QA D-02 (choice gas_import_origin): gas importers seeded by origin from Eurostat nrg_ti_gas 2022, the volume '
            'reported without origin shared over the partners\' own reports of exports to them (bcm, before the RAS)', 'report',
            len(org_rows), '', True, 'gas_import_origin',
            '; '.join(f'{o["importer"]}: Eurostat total {o["total_bcm"]:.2f}, named {o["named_bcm"]:.2f}, NSP {o["nsp_bcm"]:.2f}; seed {o["seed"]}; '
                      f'BACI-mirror seed was {o["baci_seed_before"]}; after RAS ' + ' '.join(
                          f'{R[i]} {exi["gas"][i, ix[o["importer"]]]:.2f}' for i in np.argsort(-exi['gas'][:, ix[o['importer']]])[:5])
                      for o in org_rows))

    # Fable QA C-03 (choice export_tax_after_override): the export-tax rate by route. Exporters whose statutory rate differs
    # by HS line (RUS gas: LNG exempt, pipeline 30 percent) take the route's own BACI line mix, else the importer's; routes
    # inside a union of export_tax_exempt_routes.csv (EAEU) carry none; every other route the S10 rate of its exporter
    xt_route_on = choices['export_tax_after_override']['value'] == C.EXPORT_TAX_BY_ROUTE
    # Fable QA C-03 follow-up: routes whose physical line is known and BACI does not record (RUS to TUR is pipeline gas)
    I(C.CONFIG_DIR + '/export_tax_route_lines.csv', 'export-tax line of routes BACI does not record (Fable QA C-03)')
    xt_lines_cfg = C.read_table('export_tax_route_lines.csv', ('exporter', 'importer', 'commodity', 'hs_line', 'decided_by', 'decided_at', 'basis'))
    line_rates = SRC.export_tax_line_rates(xt_lines_path, {'gas': SRC.GAS_HS, 'oil': ('270900',), 'pet': ('271000',), 'coa': coa_hs})
    xt_exempt = np.zeros((n, n), bool)
    for u in xt_exempt_cfg:
        mem = [ix[m] for m in u['members'].split(';') if m in ix]
        for a in mem:
            for b in mem:
                xt_exempt[a, b] = a != b
    line_src = {'gas': gas_baci, 'oil': baci_vpv[baci_vpv['k'] == '270900'], 'pet': baci_vpv[baci_vpv['k'] == '271000'],
                'coa': baci[baci['k'].isin(coa_hs)], 'ely': baci.iloc[0:0]}
    xtm = {}
    for c in COMMODITIES:
        if not xt_route_on:
            xtm[c] = np.repeat(xrate[c][:, None], n, axis=1)
            continue
        lr = {ix[e]: g[c] for e, g in line_rates.items() if c in g and e in ix}
        lines = sorted({l for g in lr.values() for l in g})
        rl, il = {}, {}
        for l in lines:
            d = line_src[c][(line_src[c]['k'] == l) & (line_src[c]['exp'] != line_src[c]['imp'])]
            A_ = np.zeros((n, n))
            np.add.at(A_, (d['exp'].map(ix).to_numpy(), d['imp'].map(ix).to_numpy()), d['v'].to_numpy(float) / 1000.0)
            rl[l], il[l] = A_, A_.sum(0)
        forced = {(ix[f['exporter']], ix[f['importer']]): f['hs_line'] for f in xt_lines_cfg
                  if f['commodity'] == c and f['exporter'] in ix and f['importer'] in ix}
        xtm[c] = M.route_export_tax(xrate[c], lr, rl, il, xt_exempt, forced)
    xt_rep = []
    for c in COMMODITIES:
        for i in np.where((new_fob[c] * np.repeat(xrate[c][:, None], n, axis=1)).sum(1) > 0)[0]:
            xt_rep.append(f'{R[i]} {c} {bn(float((new_fob[c][i] * xrate[c][i]).sum())):.2f} -> {bn(float((new_fob[c][i] * xtm[c][i]).sum())):.2f} bn')
    n_xr, d_xr = K.export_route_rate_rule(xtm, R, xrate, line_rates if xt_route_on else {}, xt_exempt if xt_route_on else np.zeros((n, n), bool))
    S.check('S11-Hxtroute', 'Fable QA C-03: every route export-tax rate is 0 inside the EAEU, between the lowest and highest line rate for an exporter '
            'with line rates (RUS gas: LNG 0, pipeline 0.30), else the S10 exporter rate', 'hard', n_xr, 0, n_xr == 0, 'export_tax_after_override', d_xr)
    S.check('S11-Rxtroute', 'Fable QA C-03: export tax by route (EAEU internal routes exempt; RUS gas by the route\'s BACI line mix, LNG exempt): '
            'export tax at the S10 exporter rate -> by route, on the S11 VFOB', 'report', len(xt_rep), '', True, 'export_tax_after_override',
            '; '.join(xt_rep) + '; RUS gas route rates: ' + ', '.join(f'{R[j]} {xtm["gas"][ix["RUS"], j]:.3f}' for j in np.argsort(-new_fob['gas'][ix['RUS']])[:12]))
    # beta v4 G13 (choice export_duty_to_collected, fallback, off by default): the listed exporters' route rates scaled
    # to the collected duty (decision package 15: fix the base first; this only if the base fix leaves a gap)
    if C.switched_on(choices, 'export_duty_to_collected'):
        I(C.CONFIG_DIR + '/export_duty_collected_2022.csv', 'collected energy export duty 2022 (beta v4 G13)')
        xd_cfg = C.read_table('export_duty_collected_2022.csv', C.EXPORT_DUTY_COLUMNS)
        xtm, xd_rows = M.scale_export_tax_to_collected(xtm, new_fob, {ix[r['region']]: float(r['collected_musd']) for r in xd_cfg},
                                                       C.EXPORT_DUTY_RATE_CAP)
        want = {ix[r['region']]: float(r['collected_musd']) for r in xd_cfg}
        bad = [f'{R[i]} {bn(a):.2f} bn vs collected {bn(want[i]):.2f}' for i, b, f, a in xd_rows if abs(a - want[i]) > C.EXPORT_DUTY_TOL * want[i]]
        S.check('S11-Hxtcollected', 'beta v4 G13: the scaled energy export tax of each listed exporter is within 5 percent of its collected duty',
                'hard', len(bad), 0, not bad, 'export_duty_to_collected',
                '; '.join(bad) or '; '.join(f'{R[i]} {bn(b):.2f} -> {bn(a):.2f} bn (x{f:.3f})' for i, b, f, a in xd_rows))
        S.flag('EXPORT-DUTY-COLLECTED', 'beta v4 G13: route export-tax rates scaled to the collected duty (labelled departure from the statutory rate)',
               '; '.join(f'{R[i]} x{f:.3f}' for i, b, f, a in xd_rows))

    # ------------------------------------------------------------- 4b. CIF, margins, duty
    eng = TRADE_SECTORS
    v8 = vtwr8[vtwr8['sector'].isin(eng)]
    tw = {}
    for c in eng:
        T = np.zeros((len(MODES), n, n))
        d = v8[v8['sector'] == c]
        np.add.at(T, (d['margin'].map({m: k for k, m in enumerate(MODES)}).to_numpy(), d['exporter'].map(ix).to_numpy(),
                      d['importer'].map(ix).to_numpy()), d['vtwr_musd'].to_numpy(float))
        tw[c] = T
    mrate, mshare, msrc = {}, {}, {}
    for c in eng:
        T = tw[c]
        tot = T.sum(0)
        fob = old_fob[c]
        rate = np.divide(tot, fob, out=np.full((n, n), np.nan), where=fob > 0)
        shr = np.divide(T, tot[None], out=np.full_like(T, np.nan), where=tot[None] > 0)
        imp_rate = np.divide(tot.sum(0), fob.sum(0), out=np.full(n, np.nan), where=fob.sum(0) > 0)
        imp_shr = np.divide(T.sum(1), tot.sum(0)[None], out=np.full((len(MODES), n), np.nan), where=tot.sum(0)[None] > 0)
        w_rate = tot.sum() / fob.sum()
        w_shr = T.sum((1, 2)) / tot.sum()
        src = np.where(np.isfinite(rate), 'pair', np.where(np.isfinite(imp_rate)[None, :], 'importer_sector', 'world_sector'))
        rate = np.where(np.isfinite(rate), rate, np.where(np.isfinite(imp_rate)[None, :], imp_rate[None, :], w_rate))
        for k in range(len(MODES)):
            s_k = shr[k]
            s_k = np.where(np.isfinite(s_k), s_k, np.where(np.isfinite(imp_shr[k])[None, :], imp_shr[k][None, :], w_shr[k]))
            shr[k] = s_k
        mrate[c], mshare[c], msrc[c] = rate, shr, src
    mrate['ely'] = np.zeros((n, n))
    mshare['ely'] = np.zeros((len(MODES), n, n))
    msrc['ely'] = np.full((n, n), 'ely_zero', dtype=object)
    # check: S08 pair rates reproduce S08 VTWR on old FOB
    rep = max(float(np.abs(np.where(old_fob[c] > 0, mrate[c] * old_fob[c], 0) - tw[c].sum(0)).max()) for c in eng)
    S.check('S11-Hmrate', 'S08 pair margin rates times S10 VFOB reproduce S08 VTWR on every existing energy cell (1e-6 USD m)', 'hard',
            f'{rep:.2e}', '1e-6', rep < 1e-6, 'cif_after_override')
    # beta v4 P13 (choice energy_route_observed): pipeline and grid routes are delivered at the frontier, CIF = FOB (BPM6 10.34)
    for (i, j, c) in obs_routes:
        msrc[c] = msrc[c].astype(object)
        mrate[c][i, j], msrc[c][i, j] = 0.0, 'observed_route_delivered_at_frontier'

    # duty
    tmd = {c: np.full((n, n), np.nan) for c in COMMODITIES}
    for c in eng:
        d = tm10[tm10['sector'] == c]
        tmd[c][d['exporter'].map(ix).to_numpy(), d['importer'].map(ix).to_numpy()] = d['tm'].to_numpy(float)
    in_union = np.zeros((n, n), bool)
    for _, u in unions.iterrows():
        if str(u['booking']).strip() not in ('forced', 'fill'):
            continue
        mem = [ix[m] for m in str(u['members']).split(';') if m in ix]
        for a in mem:
            for b in mem:
                in_union[a, b] = True
    h = hs6app[hs6app['sector_name'].isin(eng)].copy()
    h['w'] = h['weight_thousand_usd'].fillna(0)
    mfn = {}
    for (imp_r, c), g in h.groupby(['importer', 'sector_name']):
        w = g['w'].to_numpy(float)
        r_ = g['mfn_rate_pct'].to_numpy(float) / 100.0
        mfn[(imp_r, c)] = float((r_ * w).sum() / w.sum()) if w.sum() > 0 else float(np.nanmean(r_))
    tsrc = {}
    for c in COMMODITIES:
        T = tmd[c]
        src = np.where(np.isfinite(T), 's10_pair', '').astype(object)
        if c == 'ely':
            T[:] = 0.0
            src[:] = 'ely_zero_not_priced_by_s10'
        else:
            for j in range(n):
                fb = mfn.get((R[j], c), np.nan)
                for i in range(n):
                    if np.isfinite(T[i, j]):
                        continue
                    if in_union[i, j]:
                        T[i, j], src[i, j] = 0.0, 'new_pair_customs_union_zero'
                    elif np.isfinite(fb):
                        T[i, j], src[i, j] = fb, 'new_pair_importer_mfn'
                    else:
                        T[i, j], src[i, j] = 0.0, 'new_pair_no_rate_zero'
        tmd[c], tsrc[c] = T, src

    new_cif, new_vmsb, new_tw = {}, {}, {}
    for c in COMMODITIES:
        new_cif[c] = new_fob[c] * (1 + mrate[c])
        new_tw[c] = (new_cif[c] - new_fob[c])[None] * mshare[c]
        new_vmsb[c] = new_cif[c] * (1 + tmd[c])

    # VST: each mode's supply rescaled by the change in world demand of that mode
    all_tw = vtwr8.groupby('margin')['vtwr_musd'].sum()
    old_eng = {m: sum(tw[c][k].sum() for c in eng) for k, m in enumerate(MODES)}
    new_eng = {m: sum(new_tw[c][k].sum() for c in COMMODITIES) for k, m in enumerate(MODES)}
    vst = vst8.copy()
    vst['factor'] = vst['margin'].map({m: (all_tw[m] - old_eng[m] + new_eng[m]) / all_tw[m] for m in MODES})
    vst['vst_musd_s11'] = vst['vst_musd'] * vst['factor']
    vst_gap = max(abs(vst.loc[vst['margin'] == m, 'vst_musd'].sum() - all_tw[m]) for m in MODES)
    S.check('S11-Rvst8', 'S08 VST by mode equals S08 world VTWR by mode (basis of the rescaling)', 'report',
            f'{vst_gap:.3f} USD m', '1 USD m', vst_gap < 1.0, 'cif_after_override')

    # ------------------------------------------------------------- 5. output values, basic prices
    vals = []
    # domestic basic prices (§12.3.4-12.3.8): source data, IEA price gap, import basic price, simple average
    pmb, pdet = {}, {}
    XV = {c: exi[c].sum(1) for c in COMMODITIES}
    MV = {c: exi[c].sum(0) for c in COMMODITIES}
    for c in COMMODITIES:
        pmb[c] = np.divide(new_vmsb[c].sum(0), MV[c], out=np.full(n, np.nan), where=MV[c] > 0)
    # beta v5 A (choice contract_routes_out_of_parity_cap): the import price of the regulated-row cap with the contract
    # routes (observed routes priced below CONTRACT_PRICE_SHARE of the exporter's reference) at the exporter's reference
    parity_pmb, contract_rows = None, []
    if obs_on and C.switched_on(choices, 'contract_routes_out_of_parity_cap'):
        parity_pmb = {}
        for c in COMMODITIES:
            con = [(i, j) for (i, j, cc_) in obs_routes if cc_ == c and exi[c][i, j] > 0
                   and pxr[c][i, j] < C.CONTRACT_PRICE_SHARE * px_ref[c][i]]
            parity_pmb[c] = DOM.contract_free_import_price(new_vmsb[c], exi[c], pxr[c], px_ref[c], con)
            for i, j in con:
                contract_rows.append(f'{c} {R[i]}->{R[j]} at {pxr[c][i, j]:.4g} against reference {px_ref[c][i]:.4g}: {R[j]} import price '
                                     f'{pmb[c][j]:.4g} -> {parity_pmb[c][j]:.4g} {PRICE_UNIT[c]} (cap only)')
    S.check('S11-Rcontract', 'Beta v5 A (choice contract_routes_out_of_parity_cap): contract routes left out of the net-importer regulated-row cap '
            '(the cap uses the import price with these routes at the exporter\'s reference price; booked import prices unchanged)', 'report',
            len(contract_rows), '', True, 'contract_routes_out_of_parity_cap', '; '.join(contract_rows))
    members = {r: str(m).split() for r, m in zip(regions['region'], regions['members'])}
    single = {m[0]: r for r, m in members.items() if len(m) == 1}
    a2_to_iso3 = dict(zip(iso_num['alpha2'], iso_num['alpha3']))
    source = {}
    # beta v4 P2/P16: the ZAF and PRK coal rows apply only where their choice is on
    for h in C.price_source_rows(C.read_table('domestic_price_sources.csv', ('commodity', 'region', 'source', 'series', 'price_level', 'decided_by', 'decided_at', 'basis')), choices):
        c, r, kind, ser = h['commodity'], h['region'], h['source'], h['series']
        if h['price_level'] not in ('basic', 'purchasers_industrial'):
            raise SystemExit(f'domestic_price_sources.csv: unknown price_level {h["price_level"]!r}')
        if kind == 'ei_gas_hub':
            if ser not in hubs:
                raise SystemExit(f'domestic_price_sources.csv: EI gas series {ser!r} has no 2022 value')
            got = {r: (DOM.usd_mmbtu_to_musd_bcm(hubs[ser]), f'EI 2025 Gas Prices {ser} 2022, {hubs[ser]:.4g} USD/MMBtu')}
        elif kind == 'eurostat':
            table, band, unit = ser.split(':')
            conv = DOM.usd_gj_to_musd_bcm if c == 'gas' else DOM.usd_kwh_to_usd_mwh
            obs = SRC.eurostat_2022(eurostat_path[table], band, unit, a2_to_iso3)
            got = {single[iso]: (conv(v / eur_per_usd), f'Eurostat {table} {band} X_TAX {sem}, {v:.4g} EUR/{unit}')
                   for iso, (v, sem) in obs.items() if iso in single}
        elif kind == 'aer_aeco':
            got = {r: (DOM.usd_gj_to_musd_bcm(aeco / cad_per_usd), f'AER ST98 2024 Table S1.2 AECO-C 2022, {aeco:.4g} CAD/GJ at {cad_per_usd:.4g} CAD per USD (WDI)')}
        elif kind == 'nbs_unit_value':
            rmb_t = nbs['revenue'] / nbs['raw_coal_output']          # both in units of 1e8: RMB per tonne, ex VAT
            got = {r: (rmb_t / cny_per_usd, f'NBS 2022 coal mining and washing revenue {nbs["revenue"]:.6g} / raw coal {nbs["raw_coal_output"]:.4g} (1e8 RMB, 1e8 t) = {rmb_t:.4g} RMB/t ex VAT at {cny_per_usd:.4g} CNY per USD (WDI)')}
        elif kind == 'eia_spot':
            # §12.3.9: products share-weighted by volume; weights are 2022 US refinery and blender net production, the
            # output this price values (gas-plant propane is the separately priced NGPL add-on)
            sup = SRC.eia_annual_2022(I(DATA + '/eia_us_2022/PET_SUM_SND_D_NUS_MBBL_A_CUR.xls', 'EIA 2022 US refinery and blender net production (weights for US petroleum)'))
            pr = [(spot[sk] * K.GAL_PER_BBL, sup[wk]) for sk, wk in K.US_PRODUCTS]
            v = sum(a * w for a, w in pr) / sum(w for _, w in pr)
            got = {r: (v, f'EIA 2022 spot (Gulf Coast gasoline, ULSD, jet; Mont Belvieu propane) weighted by 2022 US refinery output, {v:.4g} USD/bbl')}
        elif kind == 'eia_acr':
            got = {r: (DOM.usd_short_ton_to_usd_t(us_coal), f'EIA ACR 2022 table 28 US total, {us_coal:.4g} USD/short ton')}
        elif kind == 'eia_epa':
            got = {r: (DOM.usd_kwh_to_usd_mwh(us_ely / 100.0), f'EIA EPA 2022 table 2.4 industrial, {us_ely:.4g} US cents/kWh')}
        elif kind == 'transcribed':
            # fix-round A9: config/s11/transcribed_prices_2022.csv; each item names its own commodity and region
            for nm in re.split('[:;]', ser.partition(':')[2]):
                if nm in transcribed and (transcribed[nm]['commodity'], transcribed[nm]['region']) != (c, r):
                    raise SystemExit(f'domestic_price_sources.csv: transcribed item {nm!r} is for {transcribed[nm]["commodity"]} {transcribed[nm]["region"]}, not {c} {r}')
            v, d_ = DOM.transcribed_price(c, ser, transcribed, tr_fx)
            got = {r: (v, f'transcribed 2022 (config/s11/transcribed_prices_2022.csv): {d_} = {v:.4g} {PRICE_UNIT[c]}')}
        else:
            raise SystemExit(f'domestic_price_sources.csv: unknown source {kind!r}')
        if h['price_level'] == 'purchasers_industrial':
            got = {k: (DOM.basic_from_purchasers(v, c), f'{d}; basic = purchasers / (1 + {DOM.MARGIN_INDUSTRIAL[c]:g}) (Table 12.8)', 'purchasers')
                   for k, (v, d) in got.items()}
        for rr, v in got.items():
            if (c, rr) in source:
                raise SystemExit(f'domestic_price_sources.csv: two source prices for {c} {rr}')
            source[(c, rr)] = v
    # beta v4 G10 (choice ely_class_price): sourced 2022 industrial electricity prices for the regions on the US-only class fill
    ely_cls_tab = C.read_table('ely_industrial_prices_2022.csv', C.ELY_CLASS_COLUMNS)
    I(C.CONFIG_DIR + '/ely_industrial_prices_2022.csv', 'beta v4 G10: sourced 2022 industrial electricity prices of the class-fill regions')
    ely_cls_fx = {t['fx_iso3']: SRC.wdi_value(DATA + '/wdi/wdi_2017_2022_extract.csv', 'PA.NUS.FCRF', t['fx_iso3'], 2022)
                  for t in ely_cls_tab if t['fx_iso3'] and str(t['value']).strip()}
    ely_cls_on = choices['ely_class_price']['value'] != 'off'
    ely_cls_price, ely_cls_pending = DOM.ely_class_prices(ely_cls_tab, ely_cls_fx)
    bad_cls = [t['region'] for t in ely_cls_tab if t['region'] not in ix]
    if bad_cls:
        raise SystemExit(f'ely_industrial_prices_2022.csv: unknown regions {bad_cls}')
    if ely_cls_on:
        for rr, (v, d_) in ely_cls_price.items():
            if ('ely', rr) in source:
                raise SystemExit(f'ely_industrial_prices_2022.csv: ely {rr} already has a source price')
            source[('ely', rr)] = (DOM.basic_from_purchasers(v, 'ely'), f'beta v4 G10 (config/s11/ely_industrial_prices_2022.csv): {d_}; '
                                   'basic = purchasers / (1 + 0) (Table 12.8)', 'purchasers')
    consumption = {c: np.nan_to_num(vol[c]['consumption']) for c in COMMODITIES}
    gap = DOM.iea_gap_per_unit(R, members, iea_sub, consumption, deflator)
    # fix round wA2: electricity has no trade-parity reference, so its IEA gap does not price it (rule 2); its subsidy is booked
    # against IEA's implied reference (fuel_subsidy_rows)
    cost_ref_on = subsidy_on and subsidy_all and subsidy_mode == DOM.SUBSIDY_PRICE_GAP
    gap_price = {k: v for k, v in gap.items() if not (cost_ref_on and k[0] in DOM.COST_REFERENCE_COMMODITIES)}
    net_x = sum(new_fob[c].sum(1) - new_cif[c].sum(0) for c in COMMODITIES) > 0     # §12.3.6 fill classes
    # fix-round A9 rule 5: brown-coal share of coal output (UNSD 2022, members summed) at the US lignite mine price
    num_iso = dict(zip(iso_num['numeric'].str.zfill(3), iso_num['alpha3']))
    brown = DOM.brown_coal_share(R, iso_region, SRC.unsd_coal_production_2022(unsd_path, num_iso))
    p_lig = DOM.usd_short_ton_to_usd_t(us_lignite)
    lig = dict(share=brown, price=p_lig) if lignite_on else None
    # Fable QA D-02: the domestic-price rules keep the §12.3 reference export price as the trade-parity price (px_ref);
    # the realised VFOB / volume is the export price of energy_values
    dom = DOM.domestic_basic_prices(R, px_ref, pmb, XV, MV, source, gap_price, net_x, lignite=lig, export_cap=cap_on, book_subsidy=subsidy_on)
    pdom = {c: dom[c][0] for c in COMMODITIES}
    prule = {c: dom[c][1] for c in COMMODITIES}
    pdet = {c: dom[c][2] for c in COMMODITIES}
    base_rule = {c: np.array([x.split('+')[0] for x in prule[c]], dtype=object) for c in COMMODITIES}
    S.check('S11-Rdomrule', 'Domestic basic price rule by commodity (source data / IEA price gap / import basic price / simple average)', 'report',
            '; '.join(f'{c} ' + '/'.join(str(int((base_rule[c] == k).sum())) for k in DOM.RULES) for c in COMMODITIES), '', True, 'basic_price')
    tr_rows = [(c, rr) for (c, rr), v in source.items() if v[1].startswith('transcribed')]
    tr_bad = [f'{c} {rr}' for c, rr in tr_rows if prule[c][ix[rr]].split('+')[0] != 'source_data']
    S.check('S11-Htranscribed', 'Every transcribed 2022 price (fix-round A9) is the domestic price of its region before the 90 percent rule', 'hard',
            len(tr_bad), 0, not tr_bad, 'domestic_price_transcribed',
            ' '.join(tr_bad) or '; '.join(f'{c} {rr} {pdom[c][ix[rr]]:.4g} {PRICE_UNIT[c]}' for c, rr in sorted(tr_rows)))
    # beta v4 G10: every used row is the region's source price; the rows not used keep the class fill (all stay S13 ely targets)
    cls_bad = [rr for rr in ely_cls_price if ely_cls_on and prule['ely'][ix[rr]].split('+')[0] != 'source_data']
    S.check('S11-Helyclass', 'Beta v4 G10 (choice ely_class_price): every sourced 2022 industrial electricity price in config/s11/ely_industrial_prices_2022.csv '
            'is its region\'s ely domestic price (GTAP 12 ch.12 §12.3.4, source data ahead of the §12.3.6 class fill)', 'hard', len(cls_bad), 0, not cls_bad,
            'ely_class_price', ' '.join(cls_bad) or '; '.join(f'{rr} {pdom["ely"][ix[rr]]:.4g} USD/MWh' for rr in sorted(ely_cls_price) if ely_cls_on))
    S.check('S11-Relyclass', 'Beta v4 G10 (choice ely_class_price): class-fill regions listed in config/s11/ely_industrial_prices_2022.csv whose ely '
            'price stays the GTAP 12 §12.3.6 class fill (no official 2022 price, or a sourced price not used: wholesale only or one city)', 'report',
            len(ely_cls_pending), '', True, 'ely_class_price',
            '; '.join(f'{rr} {pdom["ely"][ix[rr]]:.4g} ({prule["ely"][ix[rr]]})' for rr in ely_cls_pending) or 'none')
    lig_hit = [i for i in range(n) if prule['coa'][i].find(DOM.LIGNITE_SUFFIX) >= 0]
    S.check('S11-Rlignite', f'Coal regions with brown coal and no coal source price, priced in part at the US lignite mine price {p_lig:.4g} USD/t '
            f'(EIA ACR 2022 table 31, {us_lignite:.4g} USD/short ton; rule {"on" if lignite_on else "off"})', 'report',
            len(lig_hit), '', True, 'lignite_price', '; '.join(f'{R[i]} {brown[i]:.2f} {pdom["coa"][i]:.4g}' for i in lig_hit))
    cap_hit = [(c, i) for c in COMMODITIES for i in range(n) if prule[c][i].find(DOM.CAP_SUFFIX) >= 0]
    S.check('S11-Rcap', f'Net exporters whose domestic price is capped at their export price (rule {"on" if cap_on else "off"})', 'report',
            len(cap_hit), '', True, 'exporter_price_cap', '; '.join(f'{c} {R[i]} {pdom[c][i]:.4g}' for c, i in cap_hit))
    cap_over = [(c, R[i]) for c, i in cap_hit if pdom[c][i] > px_ref[c][i] * (1 + 1e-12)]
    S.check('S11-Hcap', 'A capped domestic price equals the export price (none above it)', 'hard', len(cap_over), 0, not cap_over, 'exporter_price_cap')
    # fix-round B15 (David's card 2026-10-24; Chepeliev et al. 2018 §3): where the domestic price is the IEA price gap,
    # the basic price is the reference and the gap is a consumption subsidy, booked by S13 as a negative purchase tax.
    # Extension (David 2026-10-24, "stick to GTAP"): every other row with an IEA subsidy (A9 regulated source prices, gaps
    # not used) keeps its price as the consumer price and books the IEA value harmonised with our volumes (step 2)
    absorption = {c: np.nan_to_num(vol[c]['production'] + MV[c] - XV[c]) for c in COMMODITIES}
    iea_val = DOM.iea_subsidy_by_region(R, members, iea_sub, deflator)
    # Fable QA C-02/B-03 (choice regulated_price_fill): a subsidising net exporter with no observed regulated gas price takes the
    # class average of the observed ones as its consumer price, so its market price is consumer + IEA rate, not export parity
    reg_fill = (DOM.regulated_consumer_fill(R, pdom, prule, pdet, iea_val, net_x, consumption, XV, MV, geo.to_dict())
                if subsidy_on and subsidy_all and subsidy_mode == DOM.SUBSIDY_PRICE_GAP and C.switched_on(choices, 'regulated_price_fill') else {})
    S.check('S11-Rregfill', 'Subsidising net energy exporters with no observed regulated price (Fable QA C-02; choice regulated_price_fill): '
            'consumer price at the simple average of the observed regulated prices of their class', 'report',
            sum(len(v['filled']) for v in reg_fill.values()), '', True, 'regulated_price_fill',
            '; '.join(f'{c} average {v["average"]:.4g}, lowest {v["lowest"]:.4g} {PRICE_UNIT[c]} of {v["n"]} observed; filled '
                      f'{" ".join(v["filled"])}; class {" ".join(sorted(v["members"]))}' for c, v in reg_fill.items()))
    FS_COLS = ['region', 'commodity', 'price_unit', 'reference_price', 'reference_basis', 'iea_subsidy_musd', 'iea_subsidy_per_unit',
               'step2_rescaled', 'subsidy_per_unit', 'consumer_price', 'market_price', 'consumption_volume', 'absorption_volume',
               'imports_volume', 'domestic_use', 'domestic_use_basis', 'subsidy_musd', 'price_gap_subsidy_musd',
               'domestic_price_before_90pct', 'domestic_price_rule', 'source_rule', 'consumer_price_basis', 'rate_cap', 'trade_parity_price']
    ely_obs = [r for i, r in enumerate(R) if str(prule['ely'][i]).split('+')[0] in DOM.OBSERVED_PRICE_RULES]
    ely_cons = DOM.electricity_consumer_prices(R, tariff_tab, tariff_fx, observed=ely_obs) if cost_ref_on else None
    fs_rows = (DOM.fuel_subsidy_rows(R, px_ref, pmb, XV, MV, gap, consumption, prule, pdom, unit=PRICE_UNIT, absorption=absorption,
                                     iea_value=iea_val if subsidy_all else None, mode=subsidy_mode, consumer_price=ely_cons, regulated=reg_fill,
                                     ely_unobserved=(DOM.ELY_UNOBSERVED_REFERENCE if choices['iea_reference_ely']['value'] == C.ELY_REFERENCE
                                                     else DOM.ELY_UNOBSERVED_ADD_ON_TOP),
                                     export_parity_cap=C.switched_on(choices, 'gas_export_parity_cap'), parity_pmb=parity_pmb) if subsidy_on else [])
    # S16 2026-10-26 (choice ely_subsidy_net_power_fuel; IEA Global Energy and Climate Model documentation 2023 and the Fossil
    # Fuel Subsidy Tracker methodology: the electricity price gap is the subsidy on the fossil inputs to power; Chepeliev 2018
    # p.88 on double counting): the IEA ely money less the fuel subsidy booked on the electricity part of the 088 burn, at least 0
    ely_net = []
    if subsidy_on and subsidy_all and C.switched_on(choices, 'ely_subsidy_net_power_fuel'):
        pf_sub = PWR.power_fuel_subsidy(fs_rows, PWR.unsd_power_fuels_2022(unsd_path, num_iso, iso_region, ei['bbl_per_t_products']),
                                        PWR.unsd_heat_share_2022(unsd_path, num_iso, iso_region), C.ELY_FUEL_RATE_CAP)
        for (c_, r_), v_ in sorted(iea_val.items()):
            if c_ == 'ely' and v_ > 0 and pf_sub.get(r_, 0.0) > 0:
                ely_net.append((r_, v_, pf_sub[r_], max(v_ - pf_sub[r_], 0.0)))
                iea_val[(c_, r_)] = max(v_ - pf_sub[r_], 0.0)
        iea_val = {k_: v_ for k_, v_ in iea_val.items() if not (k_[0] == 'ely' and v_ <= 0)}
        fs_rows = DOM.fuel_subsidy_rows(R, px_ref, pmb, XV, MV, gap, consumption, prule, pdom, unit=PRICE_UNIT, absorption=absorption,
                                        iea_value=iea_val, mode=subsidy_mode, consumer_price=ely_cons, regulated=reg_fill,
                                        ely_unobserved=(DOM.ELY_UNOBSERVED_REFERENCE if choices['iea_reference_ely']['value'] == C.ELY_REFERENCE
                                                        else DOM.ELY_UNOBSERVED_ADD_ON_TOP),
                                        export_parity_cap=C.switched_on(choices, 'gas_export_parity_cap'), parity_pmb=parity_pmb)
        S.check('S11-Relynet', 'S16 2026-10-26 (choice ely_subsidy_net_power_fuel): IEA electricity subsidy, the IEA fuel subsidy on the electricity '
                'part of the 088 burn (rate at most 0.8 of the market price), and the ely subsidy booked (the difference, at least 0), USD bn',
                'report', len(ely_net), '', True, 'ely_subsidy_net_power_fuel',
                f'{sum(x[1] for x in ely_net) / 1e3:.1f} -> {sum(x[3] for x in ely_net) / 1e3:.1f} bn; ' + '; '.join(
                    f'{r_} {a_ / 1e3:.2f} - {f_ / 1e3:.2f} = {n_ / 1e3:.2f}' for r_, a_, f_, n_ in sorted(ely_net, key=lambda t: t[3] - t[1])[:30]))
        for r_, a_, f_, n_ in ely_net:
            S.flag('ELY-SUBSIDY-NETTED', r_, f'IEA ely subsidy {a_:.1f} USD m less power-fuel subsidy {f_:.1f} = {n_:.1f}',
                   rule='ely_subsidy_net_power_fuel', citation='IEA GEC Model documentation 2023; Chepeliev 2018 p.88')
    unbooked_why = (DOM.unbooked_reason(R, prule, pdom, iea_val, fs_rows, px_ref, pmb, XV, MV)
                    if subsidy_on and subsidy_all else {})
    DOM.apply_subsidy_prices(fs_rows, R, pdom, prule, pdet)
    if cost_ref_on:
        ely_rows = [x for x in fs_rows if x['commodity'] == 'ely']
        S.check('S11-Rtariff', 'Electricity IEA rows (choice iea_reference_ely): consumer price (observed, or the sourced 2022 tariff of '
                'config/s11/electricity_tariffs_2022.csv) + IEA rate = market price; with no own tariff (round 3) market = reference = the income-group '
                'tariff average, at least rate / 0.99, and consumer = reference - rate; USD/MWh',
                'report', len(ely_rows), '', True, 'iea_reference_ely', '; '.join(
                    f'{x["region"]} {x["consumer_price"]:.4g} ({x["consumer_price_basis"]}) + {x["subsidy_per_unit"]:.4g} = {x["market_price"]:.4g}'
                    f' (trade parity {x["trade_parity_price"]:.4g})' for x in ely_rows))
        # round 3 (final QA item 4): the IEA money of every electricity row is kept (rate x use; use is the smaller of the PREP
        # consumption and the S11 absorption, Chepeliev et al. 2018 step 1), whatever the reference rule
        money_bad = [f'{x["region"]} {x["subsidy_musd"]:.6g} vs {x["iea_subsidy_per_unit"] * x["domestic_use"]:.6g}' for x in ely_rows
                     if abs(x['subsidy_musd'] - x['iea_subsidy_per_unit'] * x['domestic_use']) > 1e-9 * max(1.0, x['subsidy_musd'])]
        S.check('S11-Hsubelymoney', 'Electricity subsidy rows keep the IEA money: booked = IEA rate x domestic use on every row (1e-9; round 3, '
                'final QA item 4)', 'hard', len(money_bad), 0, not money_bad, 'iea_reference_ely',
                '; '.join(money_bad[:20]) or f'{len(ely_rows)} rows, {sum(x["subsidy_musd"] for x in ely_rows) / 1e3:.1f} bn')
    FS = pd.DataFrame(fs_rows, columns=FS_COLS)
    reg_rows = [x for x in fs_rows if x.get('reference_basis') == 'regulated_price_plus_iea_rate_at_most_own_trade_price']
    above = [x for x in reg_rows if x['rate_cap'] == 'iea_reference_above_trade_price']
    S.check('S11-Rregref', 'Regulated-class gas rows (Fable QA C-02; choice regulated_price_fill): market = consumer + IEA rate (IEA money kept), '
            'capped at the own 2022 trade price where the consumer price stays at or above the lowest observed regulated price; rows above '
            'their own trade price (logged departure: the IEA reference is a hub netback above contract export prices)', 'report',
            len(above), '', True, 'regulated_price_fill',
            '\n\n| region | consumer price PM0 | basis | IEA rate | market = reference | own trade price | cap | IEA money kept (USD m) |\n'
            '|---|---|---|---|---|---|---|---|\n' + '\n'.join(
                f'| {x["region"]} | {x["consumer_price"]:.4g} | {x["consumer_price_basis"]} | {x["subsidy_per_unit"]:.4g} | {x["market_price"]:.4g} | '
                f'{x["trade_parity_price"]:.4g} | {x["rate_cap"]} | {x["subsidy_musd"]:.6g} |' for x in reg_rows))
    if subsidy_on:
        n_fs, det_fs = K.fuel_subsidy_check(fs_rows, prule, R, price=pdom, mode=subsidy_mode, consumer_floor=DOM.CONSUMER_FLOOR_SHARE)
        S.check('S11-Hsubsidy', 'Fuel consumption subsidies (fix-round B15, GTAP\'s booking; Chepeliev et al. 2018 §3.2): subsidy = (market - '
                'consumer price) x domestic use on every row (1e-9); IEA-gap rows at the reference price; other IEA rows (fix round wA) at the observed '
                'S11 price + the IEA rate, or at the reference where the S11 price is not observed, the rate at most the reference (99% on an '
                'unobserved price; and the observed gap); electricity (wA2) at consumer price + the IEA rate = the IEA-implied reference; never '
                'above the IEA value; one row per IEA-gap or +iea_subsidy price', 'hard',
                n_fs, 0, n_fs == 0, 'fuel_subsidies',
                det_fs or (f'{len(FS)} rows, {FS["subsidy_musd"].sum() / 1e3:.1f} bn: ' + ', '.join(
                    f'{c} {v / 1e3:.1f}' for c, v in FS.groupby('commodity')['subsidy_musd'].sum().items())))
        ext = FS[FS['source_rule'] != 'iea_price_gap']
        S.check('S11-Rsubsidyext', 'IEA subsidies booked on rows not priced by the IEA gap (David 2026-10-24: regulated source prices, gaps not '
                'used): IEA value, booked value, price-gap value (reference - consumer price) x use, and the step 2 rescalings', 'report',
                len(ext), '', True, 'fuel_subsidies', '; '.join(
                    f'{x.region} {x.commodity} IEA {x.iea_subsidy_musd / 1e3:.2f} bn booked {x.subsidy_musd / 1e3:.2f} gap {x.price_gap_subsidy_musd / 1e3:.2f}'
                    + (' step2' if x.step2_rescaled else '') for x in ext.itertuples()))
        miss = sorted(f'{r} {c} {v / 1e3:.2f} bn' + (f' ({unbooked_why[(c, r)]})' if (c, r) in unbooked_why else '')
                      for (c, r), v in iea_val.items() if not ((FS['region'] == r) & (FS['commodity'] == c)).any())
        S.check('S11-Rsubsidyunbooked', 'IEA 2022 subsidies (at 2022 prices) with no row in fuel_subsidies_s11.csv (no domestic use volume, an '
                'observed price at or above the reference, or fuel_subsidies set to the gap-rows-only rule)', 'report', len(miss), '', True,
                'fuel_subsidies', '; '.join(miss))
        # fix round wA (independent QA HIGH-1): the subsidy is a price gap below the reference, never on top of it
        n_ref, det_ref = K.fuel_subsidy_reference_check(fs_rows)
        S.check('S11-Hsubref', 'Fuel subsidies are price gaps below the reference (fix round wA; Chepeliev et al. 2018 §2.1 and step 2): on every '
                'booked row the market price and the subsidy per unit are at most the reference price and the consumer price is not negative',
                'hard' if subsidy_mode == DOM.SUBSIDY_PRICE_GAP else 'report', n_ref, 0, n_ref == 0, 'fuel_subsidies',
                det_ref or (f'{len(FS)} rows; {int((FS["consumer_price_basis"] == "reference_less_rate").sum())} unobserved prices at the reference, '
                            f'{int((FS["rate_cap"] == "reference").sum())} rates capped at the reference, '
                            f'{int((FS["rate_cap"] == "observed_price_gap").sum())} at the observed price gap, '
                            f'{int((FS["rate_cap"] == "reference_less_consumer_floor").sum())} at 99% of the reference'))
        # fix round wA2 (coordinator 2026-10-24): no booked consumer price is 0 or negative
        n_pos, det_pos = K.fuel_subsidy_consumer_positive(fs_rows, DOM.CONSUMER_FLOOR_SHARE)
        S.check('S11-Hsubcons', 'No booked consumer price is 0 or negative (fix round wA2); a traded-fuel rate capped at the reference keeps '
                f'{DOM.CONSUMER_FLOOR_SHARE:.0%} of the reference as the consumer price', 'hard' if subsidy_mode == DOM.SUBSIDY_PRICE_GAP else 'report',
                n_pos, 0, n_pos == 0, 'fuel_subsidy_rate_cap', det_pos or (f'lowest consumer price / reference: ' + ', '.join(
                    f'{x["region"]} {x["commodity"]} {x["consumer_price"] / x["reference_price"]:.3f}'
                    for x in sorted(fs_rows, key=lambda x: x['consumer_price'] / x['reference_price'])[:6])))
    unused = [f'{c} {R[i]}' for c in COMMODITIES for i in range(n) if 'not used' in pdet[c][i]]
    S.check('S11-Rgapunused', 'IEA price gaps not used because the subsidy per unit is not below the trade-parity price', 'report',
            len(unused), '', True, 'basic_price', ' '.join(unused))
    p_ngpl = spot[NGPL_SERIES] * 42.0
    for c in COMMODITIES:
        prod = vol[c]['production']
        xvol, mvol = exi[c].sum(1), exi[c].sum(0)
        dom = prod - xvol
        # fix round w16: where the balance leaves no domestic sales (P = X: no measured domestic use, or the X <= P bound),
        # the RAS row sum differs from X by float noise (1e-10 of world trade); that noise is zero, not a sale S13 must place
        dom = np.where(np.abs(dom) <= 1e-9 * np.maximum(prod, xvol), 0.0, dom)
        xtax = (new_fob[c] * xtm[c]).sum(1)          # fix list A2: export tax, VFOB above VXSB; by route (Fable QA C-03)
        xr_eff = np.divide(xtax, new_fob[c].sum(1), out=xrate[c].copy(), where=new_fob[c].sum(1) > 0)
        for i in range(n):
            out = xvol[i] * px[c][i] - xtax[i] + max(dom[i], 0) * pdom[c][i]
            ngpl_v = ngpl[i] * p_ngpl if c == 'pet' else 0.0
            vals.append(dict(region=R[i], commodity=c, unit=UNIT[c], price_unit=PRICE_UNIT[c],
                             production=prod[i], exports=xvol[i], imports=mvol[i], domestic_sales=dom[i],
                             absorption=prod[i] + mvol[i] - xvol[i], ngpl_mbbl=ngpl[i] if c == 'pet' else 0.0,
                             export_price=px[c][i], export_price_source=psrc[c][i],
                             import_cif_price=new_cif[c].sum(0)[i] / mvol[i] if mvol[i] > 0 else np.nan,
                             import_basic_price=pmb[c][i], domestic_price=pdom[c][i], domestic_price_rule=prule[c][i], domestic_price_detail=pdet[c][i],
                             vfob_exports=new_fob[c].sum(1)[i], vcif_imports=new_cif[c].sum(0)[i], vmsb_imports=new_vmsb[c].sum(0)[i],
                             domestic_sales_value=max(dom[i], 0) * pdom[c][i] + ngpl_v, export_value=xvol[i] * px[c][i],
                             export_tax=xtax[i], export_tax_rate=xr_eff[i], output_value=out + ngpl_v, ngpl_value=ngpl_v, pass_through_value=0.0,
                             target='yes' if c in TARGETS or (c == 'ely' and ely_target_on) else 'no (report only)',
                             ely_target_rule=('' if c != 'ely' or not ely_target_on else
                                              'floor_ninety' if ely_floor90_on else
                                              'value' if not ely_floor_on or R[i] in C.ELY_FLOOR_S11_VALUE_REGIONS else 'floor'),
                             ely_floor_value=np.nan))
    V = pd.DataFrame(vals)
    over = [(R[i], c, vx[c][i], vol[c]['production'][i]) for c in COMMODITIES for i in range(n)
            if vx[c][i] > vol[c]['production'][i] * (1 + 1e-12) + 1e-15]
    S.check('S11-Hdx', 'Domestic exports are at most production for every region and commodity after the supply-use rescaling, the re-export removal and the balance', 'hard',
            len(over), 0, not over, 'supply_use_balance', '; '.join(f'{r} {c} X {x:.6g} > P {p:.6g}' for r, c, x, p in over[:20]))

    # ------------------------------------------------------------- B06 split and the 90 percent rule
    io = io10.copy()
    users = [c for c in io.columns if c not in ('region', 'row')]
    V_i = V.set_index(['region', 'commodity'])
    # gas used by refineries (UNSD 3000, 0925 + 086), valued at the gas prices: sizes the gas part of B06 -> pet
    ref_tj = SRC.unsd_refinery_gas_2022(unsd_path, dict(zip(iso_num['numeric'].str.zfill(3), iso_num['alpha3'])))
    pet_prod = dict(zip(R, vol['pet']['production']))
    own = {r: ref_tj[members[r][0]] for r in R if len(members[r]) == 1 and members[r][0] in ref_tj}
    coef = [own[r] / pet_prod[r] for r in own if pet_prod[r] > 0]
    coef_avg = float(np.mean(coef))
    gas_pet, gp_rows = {}, []
    ngpl_mode, ngpl_rows = choices['ngpl_feedstock']['value'], []
    ngpl_feed_on = ngpl_mode != 'off'
    if ngpl_mode == C.NGPL_FEEDSTOCK:
        ngpl_heat = SRC.eia_ngpl_heat_2022(intl_path)
        V_ngpl = dict(zip(R, ngpl))
    for r in R:
        tj, how = (own[r], 'unsd_0925_086') if r in own else (coef_avg * pet_prod[r], f'simple average of {len(coef)} reporters, TJ per million bbl of pet output')
        bcm = tj / DOM.GJ_PER_BCM * 1e3          # TJ -> bcm: 1 bcm = 40e6 GJ = 40,000 TJ
        dsv, imv = max(float(V_i.loc[(r, 'gas'), 'domestic_sales']), 0.0), float(V_i.loc[(r, 'gas'), 'imports'])
        sh = dsv / (dsv + imv) if dsv + imv > 0 else 1.0
        pd_, pm_ = float(V_i.loc[(r, 'gas'), 'domestic_price']), float(V_i.loc[(r, 'gas'), 'import_basic_price'])
        gas_pet[r] = {'dom': bcm * sh * pd_, 'imp': bcm * (1 - sh) * (pm_ if np.isfinite(pm_) else 0.0)}
        # beta v5 N2 (choice ngpl_feedstock): NGPL booked to pet buys its gas where it is a large part of pet output, so pet's
        # cost follows the gas it is separated from (NGA: 79% of pet output is NGPL with no input behind it)
        feed = 0.0
        if ngpl_feed_on:
            ngv, outv = float(V_i.loc[(r, 'pet'), 'ngpl_value']), float(V_i.loc[(r, 'pet'), 'output_value'])
            if ngv > 0 and ngv >= C.NGPL_FEED_MIN_SHARE * outv:
                if ngpl_mode == C.NGPL_FEEDSTOCK:
                    # the gas the NGPL is separated from, in volume: EIA 2022 NGPL energy (the region's members' MMBtu per
                    # barrel, else the world's) at the GCV basis of the gas volumes, valued at the region's gas prices
                    mm = [ngpl_heat[m] for m in members[r] if m in ngpl_heat]
                    hb, hsrc = (float(np.mean(mm)), 'EIA 2022') if mm else (ngpl_heat['WORL'], 'EIA 2022 world')
                    fbcm = V_ngpl[r] * 1e6 * hb * C.GJ_PER_MMBTU / DOM.GJ_PER_BCM
                    fd, fm = fbcm * sh * pd_, fbcm * (1 - sh) * (pm_ if np.isfinite(pm_) else 0.0)
                    how_ = f'{V_ngpl[r]:.2f} m bbl x {hb:.3f} MMBtu/bbl ({hsrc}) = {fbcm:.3f} bcm at the gas prices'
                    # never above the value-share rule: the separation margin stays non-negative (GNQ gas at its export price)
                    cap_ = C.NGPL_FEED_SHARE * ngv
                    if fd + fm > cap_:
                        how_ += f', capped at {C.NGPL_FEED_SHARE:.0%} of the NGPL value (was {fd + fm:.1f})'
                        fd, fm = fd * cap_ / (fd + fm), fm * cap_ / (fd + fm)
                    feed = fd + fm
                else:
                    feed = C.NGPL_FEED_SHARE * ngv
                    fd, fm = feed * sh, feed * (1 - sh)
                    how_ = f'{C.NGPL_FEED_SHARE:.0%} of the NGPL value'
                gas_pet[r]['dom'] += fd
                gas_pet[r]['imp'] += fm
                ngpl_rows.append(f'{r} NGPL {ngv:.1f} of pet {outv:.1f} USD m ({ngv / outv:.0%}): gas feedstock {feed:.1f} ({how_})')
        gp_rows.append(dict(region=r, refinery_gas_tj=tj, basis=how, refinery_gas_bcm=bcm, domestic_share=sh,
                            value_dom_musd=gas_pet[r]['dom'], value_imp_musd=gas_pet[r]['imp'], ngpl_feedstock_musd=feed))
    # fix-round A8: crude goes to refining and to the users the energy balance lists (UNSD 2022 crude used outside
    # refineries, config/s11/crude_direct_users.csv); each listed column's share of the oil row = its crude use over
    # the region's crude absorption (P + M - X), members summed
    bad_col = sorted(set(direct_col.values()) - set(users))
    if bad_col:
        raise SystemExit(f'crude_direct_users.csv: io columns {bad_col} are not io_s10 columns')
    # fix round w16: in a region whose crude use is measured, refinery intake and direct use carry the supply-use
    # factor of the two-sided balance (use / a), so intake + direct use = absorption (S11-Hsupuse)
    crude_k = np.ones(n)
    if 'oil' in dvol:
        okk = dmeas['oil'] & (use_vol['oil'] > 0)
        crude_k[okk] = dvol['oil'][okk] / use_vol['oil'][okk]
    direct_mbbl = {r: {u: q * crude_k[ix[r]] for u, q in d_.items()} for r, d_ in direct_mbbl.items()}
    oil_users = {}
    for r in R:
        ab = max(float(V_i.loc[(r, 'oil'), 'absorption']), 0.0)
        sh = {u: (q / ab if ab > 0 else 0.0) for u, q in direct_mbbl.get(r, {}).items()}
        tot = sum(sh.values())
        oil_users[r] = {u: q / tot for u, q in sh.items()} if tot > 1 else sh     # direct use cannot exceed absorption
    # round 3 (final QA item 2; choice crude_direct_cell_cap; GTAP 12 ch.17A: energy volumes held at the energy balance,
    # valued at prices): a listed user's B06 cell is shared between crude and gas by the value of what it burns, the UNSD
    # crude burn at the S11 crude price against the UNSD natural gas burn of the same transaction at the S11 gas price,
    # domestic and imported product apart (value shares, so the share applies to the io_s10 cell, which is not at S11 scale)
    cell_cap_on = C.switched_on(choices, 'crude_direct_cell_cap')
    gas_tj = SRC.unsd_gas_by_transaction_2022(unsd_path, num_iso, direct_col) if cell_cap_on else {}
    # round 3 (final QA 2 item 3; choice power_fuel_cell_values; GTAP 12 ch.12 §12.4 and ch.17A: energy volumes by user
    # valued at prices): the refined fuel the power plants of a listed crude user burn (UNSD SIEC 46 products, the power
    # transaction of crude_direct_users.csv), tonnes to barrels at the EI product basket, for S13's power-column cell targets
    power_on = C.switched_on(choices, 'power_fuel_cell_values')
    ely_tr = [tr for tr, col in direct_col.items() if col == 'ely']
    # The burn enters as the UNSD power share of the region's product supply (power burn over total energy supply GA, both
    # SIEC 46 kt, members of the burning countries summed) applied to the S11 pet domestic sales and imports, as the crude
    # direct use carries the S11 supply-use factor: S11's pet balance and UNSD's product balance differ (NGL, re-exports)
    pet_kt, pet_ga = SRC.unsd_products_by_transaction_2022(unsd_path, num_iso, ely_tr) if (cell_cap_on and power_on) else ({}, {})
    pet_burn, pet_supply = {}, {}
    for (iso, tr), kt in pet_kt.items():
        rr = iso_region.get(iso)
        if rr in ix:
            d_ = pet_burn.setdefault(rr, {})
            d_[direct_col[tr]] = d_.get(direct_col[tr], 0.0) + kt * ei['bbl_per_t_products'] / 1e3      # kt -> million bbl
            if (iso, rr) not in pet_supply:
                pet_supply[(iso, rr)] = max(pet_ga.get(iso, 0.0), 0.0) * ei['bbl_per_t_products'] / 1e3
    pet_ga_r = {}
    for (iso, rr), q in pet_supply.items():
        pet_ga_r[rr] = pet_ga_r.get(rr, 0.0) + q
    gas_burn = {}
    for (iso, tr), tj in gas_tj.items():
        rr = iso_region.get(iso)
        if rr in ix:
            d_ = gas_burn.setdefault(rr, {})
            d_[direct_col[tr]] = d_.get(direct_col[tr], 0.0) + tj / DOM.GJ_PER_BCM * 1e3      # TJ -> bcm

    def split_values(r, c):
        dsv, imv = max(float(V_i.loc[(r, c), 'domestic_sales_value']), 0.0), max(float(V_i.loc[(r, c), 'vmsb_imports']), 0.0)
        sh = dsv / (dsv + imv) if dsv + imv > 0 else 1.0
        pd_, pm_ = float(V_i.loc[(r, c), 'domestic_price']), float(V_i.loc[(r, c), 'import_basic_price'])
        return sh, (pd_ if np.isfinite(pd_) else 0.0), (pm_ if np.isfinite(pm_) else 0.0)

    cell_share, cell_rows = {}, []
    for r in R:
        cell_share[r] = {}
        if not cell_cap_on:
            continue
        so, po_d, po_m = split_values(r, 'oil')
        sg, pg_d, pg_m = split_values(r, 'gas')
        for u, q in sorted(direct_mbbl.get(r, {}).items()):
            gb = gas_burn.get(r, {}).get(u, 0.0)
            if gb <= 0:
                continue                         # no gas burn reported: the row-share cap alone (A8)
            vals = {'dom': (q * so * po_d, gb * sg * pg_d), 'imp': (q * (1 - so) * po_m, gb * (1 - sg) * pg_m)}
            f = {k: (cv / (cv + gv) if cv + gv > 0 else 1.0) for k, (cv, gv) in vals.items()}
            cell_share[r][u] = f
            pb = pet_burn.get(r, {}).get(u, 0.0)
            ga = pet_ga_r.get(r, 0.0)
            psh = min(pb / ga, 1.0) if (pb > 0 and ga > 0) else 0.0
            pdv, pmv = max(float(V_i.loc[(r, 'pet'), 'domestic_sales_value']), 0.0), max(float(V_i.loc[(r, 'pet'), 'vmsb_imports']), 0.0)
            cell_rows.append(dict(region=r, column=u, crude_mbbl=q, gas_bcm=gb, crude_value_dom_musd=vals['dom'][0],
                                  gas_value_dom_musd=vals['dom'][1], crude_value_imp_musd=vals['imp'][0], gas_value_imp_musd=vals['imp'][1],
                                  crude_share_dom=f['dom'], crude_share_imp=f['imp'], pet_mbbl_unsd=pb, pet_supply_share_unsd=psh,
                                  pet_value_dom_musd=psh * pdv, pet_value_imp_musd=psh * pmv))
    new_blocks, split_rows = [], []
    for r in R:
        blk = io[io['region'] == r].set_index('row')[users]
        g = lambda c, k: float(V_i.loc[(r, c), k])
        out, info = M.split_b06(blk, g('oil', 'domestic_sales_value'), g('gas', 'domestic_sales_value'),
                                g('oil', 'export_value'), g('gas', 'export_value'),
                                g('oil', 'vmsb_imports'), g('gas', 'vmsb_imports'), gas_pet=gas_pet[r], oil_users=oil_users[r],
                                crude_value_share=cell_share[r])
        info['crude_direct_users'] = ' '.join(f'{u}:{q:.4f}' for u, q in sorted(oil_users[r].items()))
        info['crude_cell_share'] = ' '.join(f'{u}:{f["dom"]:.4f}/{f["imp"]:.4f}' for u, f in sorted(cell_share[r].items()))
        for u in sorted(direct_mbbl.get(r, {})):
            uc = 'oil' if u == 'B06' else u
            if uc in out.columns:
                for kind in ('dom', 'imp'):
                    info[f'{u}_{kind}_oil'] = float(out.loc[f'{kind}_oil', uc])
                    info[f'{u}_{kind}_gas'] = float(out.loc[f'{kind}_gas', uc] if u != 'B06' else out.loc[f'{kind}_gas', 'gas'])
        for kind in ('dom', 'imp'):
            gp_rows[R.index(r)][f'b06_pet_cell_{kind}'] = float(blk.loc[f'{kind}_B06', 'pet'])
            gp_rows[R.index(r)][f'gas_to_pet_{kind}'] = float(out.loc[f'{kind}_gas', 'pet'])
        out.insert(0, 'region', r)
        new_blocks.append(out)
        split_rows.append(dict(region=r, b06_out=float(blk.loc['OUT', 'B06']), oil_out=float(out.loc['OUT', 'oil']),
                               gas_out=float(out.loc['OUT', 'gas']), **info))
    io11 = pd.concat(new_blocks).rename_axis('row').reset_index()
    sec_order = [c for c in io10.columns if c not in ('region', 'row')]
    sec_order = sec_order[:sec_order.index('B06')] + ['oil', 'gas'] + sec_order[sec_order.index('B06') + 1:]
    row_order = []
    for rr in io10['row'].drop_duplicates():
        row_order += ([rr.replace('B06', 'oil'), rr.replace('B06', 'gas')] if rr.endswith('_B06') else [rr])
    io11['row'] = pd.Categorical(io11['row'], row_order, ordered=True)
    io11 = io11.sort_values(['region', 'row'])[['region', 'row'] + sec_order]
    io11['row'] = io11['row'].astype(str)
    B = pd.DataFrame(split_rows)
    b06_err = K.b06_identity(io10, io11)
    S.check('S11-Hb06', 'B06 split: oil + gas rows and columns equal B06 cell by cell (1e-6 relative); no negative cell', 'hard',
            f'max gap {b06_err["max_gap"]:.2e}; negative {b06_err["negative"]}', '1e-6; 0',
            b06_err['max_gap'] < 1e-6 and b06_err['negative'] == 0, 'b06_split', b06_err['detail'])
    gp_bad, gp_det = K.gas_pet_share(B)
    S.check('S11-Hgaspet', 'io_s11 gas row into pet: share of the io gas row = refinery gas / S11 gas domestic sales (imports for imp), at most the pet cell (1e-6)', 'hard',
            gp_bad, 0, gp_bad == 0, 'b06_split', gp_det)
    crude_bad, crude_det = K.crude_users(io11, oil_users, R)
    S.check('S11-Hcrude', 'io_s11 oil rows go only to refining, the listed direct users (crude_direct_users.csv) and exports (fix-round A8)', 'hard',
            crude_bad, 0, crude_bad == 0, 'b06_split', crude_det)
    S.check('S11-Rcrude', 'B06 oil share moved to gas because no listed user takes it, and oil to listed direct users, io_s10 scale, world (bn)', 'report',
            f'to gas {bn(B["oil_share_to_gas_dom"].sum() + B["oil_share_to_gas_imp"].sum()):.1f}; direct '
            f'{bn(B["oil_direct_dom"].sum() + B["oil_direct_imp"].sum()):.1f}', '', True, 'b06_split',
            '; '.join(f'{x.region} {x.crude_direct_users}' for x in B.itertuples() if x.crude_direct_users))
    CS = pd.DataFrame(cell_rows, columns=['region', 'column', 'crude_mbbl', 'gas_bcm', 'crude_value_dom_musd', 'gas_value_dom_musd',
                                          'crude_value_imp_musd', 'gas_value_imp_musd', 'crude_share_dom', 'crude_share_imp',
                                          'pet_mbbl_unsd', 'pet_supply_share_unsd', 'pet_value_dom_musd', 'pet_value_imp_musd'])
    cs_bad, cs_det = K.crude_cell_share(io10, io11, cell_share, R)
    S.check('S11-Hcrudecell', 'Listed crude users (round 3, final QA item 2; choice crude_direct_cell_cap): the crude part of each listed '
            'io_s11 cell is at most its value share of the cell (UNSD crude burn at the S11 crude price against UNSD gas burn at the S11 '
            'gas price), domestic and imported rows apart (1e-9)', 'hard' if cell_cap_on else 'report', cs_bad, 0, cs_bad == 0,
            'crude_direct_cell_cap', cs_det)
    if ngpl_feed_on:
        S.check('S11-Rngplfeed', f'Beta v5 N2 (choice ngpl_feedstock; labelled departure): where NGPL is at least {C.NGPL_FEED_MIN_SHARE:.0%} of pet '
                f'output value, pet buys the gas the NGPL is separated from ('
                + ('EIA 2022 NGPL energy in bcm at the region\'s gas prices' if ngpl_mode == C.NGPL_FEEDSTOCK
                   else f'worth {C.NGPL_FEED_SHARE:.0%} of the NGPL value') + '), split '
                'domestic/imported as the region\'s gas supply, added to the refinery gas of the B06 split (capped at the gas row there)',
                'report', len(ngpl_rows), '', True, 'ngpl_feedstock', '; '.join(ngpl_rows) + '; io_s11 gas into pet: ' + '; '.join(
                    f'{x.region} {(x.gas_to_pet_dom + x.gas_to_pet_imp):.1f} (asked {(x.value_dom_musd + x.value_imp_musd):.1f})'
                    for x in pd.DataFrame(gp_rows).itertuples() if x.ngpl_feedstock_musd > 0))
    # beta v5 E4 (choice gas_users_excluded): listed users that the energy balance shows with no use of the good; their io_s11
    # cells (domestic and imported rows) go pro rata to the region's other industries that already buy it (pet excluded:
    # its gas cell is the refinery gas of the B06 split)
    I(C.CONFIG_DIR + '/energy_user_exclusions.csv', 'energy users with no use of the good in the energy balance (beta v5 E4)')
    excl_rows = []
    if C.switched_on(choices, 'gas_users_excluded'):
        users11 = [u for u in io11.columns if u not in ('region', 'row')]
        for row in C.read_table('energy_user_exclusions.csv', C.USER_EXCLUSION_COLUMNS):
            us_ = row['users'].split(';')
            if row['region'] not in ix or row['commodity'] not in COMMODITIES or any(u not in users11 for u in us_):
                raise SystemExit(f'energy_user_exclusions.csv: bad row {row}')
            excl_rows.append(M.move_user_cells(io11, row['region'], row['commodity'], us_, users11))
        S.check('S11-Ruserexcl', 'Beta v5 E4 (choice gas_users_excluded): io_s11 cells of listed users with no use in the energy balance moved pro '
                'rata to the other buying industries (row totals kept), USD m', 'report', len(excl_rows), '', True, 'gas_users_excluded',
                '; '.join(f"{x['region']} {x['commodity']}: {x['moved']:.1f} moved from {x['from']} to {x['to']}" for x in excl_rows))
        bad_x = [f"{x['region']} {x['commodity']} gap {x['row_gap']:.2e}" for x in excl_rows if x['row_gap'] > 1e-6 * max(x['row_total'], 1.0)]
        S.check('S11-Huserexcl', 'Beta v5 E4: each moved row keeps its total (1e-6 relative) and the listed users hold no cell of it', 'hard',
                len(bad_x), 0, not bad_x, 'gas_users_excluded', '; '.join(bad_x))
    Bi = B.set_index('region')

    def into(r, u, c):
        return sum(float(Bi.loc[r].get(f'{u}_{k}_{c}', 0.0) or 0.0) for k in ('dom', 'imp')) / 1e3

    S.check('S11-Rcrudecell', 'Listed crude users with a UNSD gas burn: crude value share of the cell (UNSD crude and gas burn at S11 prices), '
            'and crude and gas into the cell after the split, io_s10 scale (bn)', 'report', len(CS), '', True, 'crude_direct_cell_cap',
            '; '.join(f'{x.region} {x.column} crude share {x.crude_share_dom:.2f} (crude {x.crude_value_dom_musd / 1e3:.2f} vs gas '
                      f'{x.gas_value_dom_musd / 1e3:.2f} bn); io oil {into(x.region, x.column, "oil"):.2f} gas {into(x.region, x.column, "gas"):.2f}'
                      for x in CS.itertuples() if x.crude_value_dom_musd + x.crude_value_imp_musd > 50))
    S.check('S11-Rpowerpet', 'Listed crude users\' power columns (round 3, final QA 2 item 3; choice power_fuel_cell_values): UNSD refined fuel '
            'burnt in power plants (SIEC 46 products) as a share of UNSD product supply, applied to the S11 pet domestic sales and imports, with '
            'the crude and gas values beside it, S11 scale (bn); S13 holds these power cells', 'report', int((CS['pet_supply_share_unsd'] > 0).sum()), '', True,
            'power_fuel_cell_values',
            '; '.join(f'{x.region} crude {(x.crude_value_dom_musd + x.crude_value_imp_musd) / 1e3:.2f} gas {(x.gas_value_dom_musd + x.gas_value_imp_musd) / 1e3:.2f} '
                      f'pet {(x.pet_value_dom_musd + x.pet_value_imp_musd) / 1e3:.2f} (UNSD share {x.pet_supply_share_unsd:.3f})'
                      for x in CS.itertuples() if x.column == 'ely' and x.crude_value_dom_musd + x.crude_value_imp_musd > 50))
    # Fable QA D-06 (2026-10-25; GTAP 12 ch.12 §12.2.2, ch.17A): the ely column's fuels from the energy balance, UNSD 2022
    # power, CHP and heat plants (088) by fuel plus the gas that reaches households and commerce (gdt is inside ely), at
    # S11 prices, written for S13 (power_fuels_s11.csv)
    PF_COLS = ['region', 'fuel', 'commodity', 'io_column', 'volume_unsd', 'volume', 'share_of_absorption', 'value_dom_musd', 'value_imp_musd']
    pfuels = PWR.unsd_power_fuels_2022(unsd_path, num_iso, iso_region, ei['bbl_per_t_products'])
    PF = pd.DataFrame(PWR.power_fuel_rows(R, pfuels, V_i), columns=PF_COLS)
    pf_v = PF.assign(v=PF['value_dom_musd'] + PF['value_imp_musd']).pivot_table(index='region', columns='fuel', values='v', aggfunc='sum').fillna(0.0)
    S.check('S11-Rpowerfuel', 'Electricity column fuels from the energy balance (Fable QA D-06): UNSD 2022 transaction 088 burn by fuel and '
            'gas to households and commerce (1231, 1235) at S11 prices, S11 scale (bn), largest regions; S13 holds them', 'report',
            len(PF), '', True, 'power_fuel_inputs',
            '; '.join(f'{r} ' + ' '.join(f'{k} {pf_v.loc[r, k] / 1e3:.1f}' for k in pf_v.columns if pf_v.loc[r, k] > 0)
                      for r in pf_v.sum(1).sort_values(ascending=False).index[:12]))
    nonb06 = K.io_unchanged_outside_b06(io10, io11)
    S.check('S11-Hio', 'Every io_s11 cell outside the B06 rows and column equals io_s10 exactly', 'hard',
            nonb06, 0, nonb06 == 0, 'b06_split')

    # refinery crude intake (read with the volumes): JODI REFINOBS, else PREP crude use, else UNSD 4100 / 086 (fix-round A10),
    # times the supply-use factor where the balance moved it (fix round w16)
    crude_in = {}
    for i, r in enumerate(R):
        crude_in[r] = crude_raw[r] * crude_k[i]
        if abs(crude_k[i] - 1) > 1e-12:
            crude_src[r] += '_supply_use_balanced'
        supply = max(float(V_i.loc[(r, 'oil'), 'absorption']), 0.0)     # refineries cannot run more crude than S11 supplies
        if crude_in[r] > supply * (1 + 1e-6):     # 1e-6: the RAS noise on a balanced absorption (w16)
            crude_in[r], crude_src[r] = supply, crude_src[r] + '_capped_at_s11_crude_supply'
    ei_low = [x for x in ei_floor_rows if x[4]]
    S.check('S11-Reiintake', 'Refinery crude intake below 70% of EI 2022 refinery throughput (Fable QA D-08): energy-data intake, '
            'EI throughput and the intake used (million bbl); EI replaces the intake there', 'report',
            len(ei_low), '', True, 'refinery_intake_ei_floor',
            '; '.join(f'{r} {src} {a:.0f} EI {e:.0f} used {crude_in[r]:.0f}' for r, a, e, src, _ in ei_low))
    # beta v4 P1 (choice ninety_pct_ely; GTAP 12 ch.12 §12.4.3, Table 12.13 has USA and Iraq ely): electricity joins the rule,
    # its inputs the electricity share of the UNSD 088 burn at S11 prices; gas distribution and heat are resold at cost
    heat_sh = PWR.unsd_heat_share_2022(unsd_path, num_iso, iso_region) if (ely_rule_on or ely_target_on) else {}
    # S16 2026-10-26 (choice ely_fuel_purchaser_price; labelled departure, GTAP 12 §12.4.3 does not say which price): the power
    # industry pays purchaser prices, so its fuels and own use enter the rule net of the IEA subsidy S13 books on them
    ely_purch = C.switched_on(choices, 'ely_fuel_purchaser_price') and ely_rule_on
    # beta v4 dry run 3 (S13-H90fit SAU 0.9027): a fuel's rate is the one S13 books, the subsidy money over domestic sales plus
    # imports (S13 fuel_subsidy basis 'held basic purchases'), not the IEA per-unit rate (SAU pet 0.302 against 0.221 booked)
    k_basis = {(x.region, x.commodity): float(x.domestic_sales_value) + float(x.vmsb_imports) for x in V.itertuples()}
    k_purch = PWR.purchaser_factors(FS, C.ELY_FUEL_RATE_CAP, basis=k_basis) if ely_purch else {}
    ely_in = PWR.ninety_ely_inputs(R, PWR.at_purchaser(PF, k_purch) if ely_purch else PF, heat_sh) if ely_rule_on else None
    # beta v4 P1 and P15 (choice ninety_pct_own_use): the refinery's and the power industry's own use + losses (UNSD 2022)
    unsd_own = SRC.unsd_own_use_2022(unsd_path, num_iso)
    # beta v4 dry run and Grok QA R2 (choice ely_losses_in_own_use): GTAP 12 ch.12 Table 12.3 puts distribution losses under
    # special treatment, so they leave the ely own-use share (default); domestic_share charges the industry only the losses
    # on its own output; off charges all losses (the P1 rule that failed S11-H90 on AFG and PAL)
    loss_rule = choices['ely_losses_in_own_use']['value']
    loss_drop = ('ely',) if loss_rule == C.CHOICES['ely_losses_in_own_use'] else ()
    loss_split = ('ely',) if loss_rule == C.ELY_LOSSES_SPLIT else ()
    own_in = None
    # beta v5 E8 (choice chn_ely_own_use_cec): sourced own-use shares in place of UNSD, off until the source row is filled
    I(C.CONFIG_DIR + '/own_use_overrides.csv', 'sourced own-use shares (beta v5 E8)')
    own_over = M.own_use_override_rows(C.read_table('own_use_overrides.csv', C.OWN_USE_OVERRIDE_COLUMNS), choices, C.switched_on)
    if C.switched_on(choices, 'ninety_pct_own_use'):
        OU0 = M.own_use_shares(V, R, iso_region, unsd_own, goods=('pet', 'ely') if ely_rule_on else ('pet',), loss_split=loss_split, loss_drop=loss_drop)
        own_in = {}
        if own_over:
            OU0 = M.apply_own_use_overrides(OU0, own_over)
        for x in OU0.dropna(subset=['own_use_share']).itertuples():
            own_in.setdefault(x.region, {})[x.commodity] = float(x.own_use_share)
    # the rule's own use: ely at its purchaser price where ely_fuel_purchaser_price is on (the shares stay as written)
    own_rule = ({r_: {k_: v_ * (k_purch.get((r_, 'ely'), 1.0) if k_ == 'ely' else 1.0) for k_, v_ in d_.items()} for r_, d_ in own_in.items()}
                if own_in is not None and ely_purch else own_in)
    nin_rows, pi_all = K.ninety_rule(V, R, crude_in, gas_pet, M.ninety_pct_both, ely_in=ely_in, own_in=own_rule)
    # beta v4 P4 (choice ely_production_subsidy; GTAP 12 ch.12 §12.4.3 p.29: "where we believe that there is a large production
    # subsidy, but the energy tax data set provides no estimate, we also adjust the production subsidy"): a listed region with a
    # documented 2022 transfer to its power utilities and no IEA 2022 electricity subsidy books the transfer, at most the rule's
    # shortfall, as revenue of the ely industry; the price rule covers the rest, and S13 books it as an ely output subsidy
    ely_sub, ES = {}, pd.DataFrame()
    if C.switched_on(choices, 'ely_production_subsidy'):
        if not ely_rule_on:
            raise SystemExit('ely_production_subsidy needs ninety_pct_ely: the shortfall is the electricity side of the 90 percent rule')
        es_rows = C.read_table('ely_production_subsidy_2022.csv', C.ELY_SUBSIDY_COLUMNS)
        I(C.CONFIG_DIR + '/ely_production_subsidy_2022.csv', 'documented 2022 transfers to power utilities (beta v4 P4)')
        iea_ely = set(FS.loc[FS['commodity'] == 'ely', 'region'])
        ES = pd.DataFrame(K.ely_subsidy_rows(es_rows, nin_rows, iea_ely, R))
        ely_sub = {x.region: x.booked_musd for x in ES.itertuples() if x.booked_musd > 0}
        for x in ES.itertuples():
            S.flag('ELY-PRODUCTION-SUBSIDY', x.region, f'transfer {x.transfer_musd:.1f} USD m, shortfall {x.shortfall_musd:.1f}, booked {x.booked_musd:.1f} '
                   f'({x.status})', rule='ely_production_subsidy', citation='GTAP 12 ch.12 §12.4.3 p.29')
        if ely_sub:
            nin_rows, pi_all = K.ninety_rule(V, R, crude_in, gas_pet, M.ninety_pct_both, ely_in=ely_in, own_in=own_rule, ely_subsidy=ely_sub)
        S.check('S11-Relysub', 'Electricity production subsidy (beta v4 P4; choice ely_production_subsidy): listed transfers, the 90 percent rule\'s '
                'shortfall before any price change, and the amount booked (at most the shortfall; none where the IEA has a 2022 electricity subsidy)',
                'report', len(ES), '', True, 'ely_production_subsidy',
                '; '.join(f'{x.region} {x.booked_musd:.1f} of {x.transfer_musd:.1f} ({x.status})' for x in ES.itertuples()))
    if ely_rule_on:
        ely_nin = [x for x in nin_rows if x['industry'] == 'ely' and x['revenue_before'] > 0]
        S.check('S11-R90ely', 'Electricity in the 90 percent rule (beta v4 P1; choice ninety_pct_ely): the electricity part of the UNSD 088 burn '
                '(1 - the 8000T heat share of the plants\' output energy) at S11 prices, plus own use and losses, against electricity revenue; '
                'industries above 0.9 before the rule, largest 25 (ratio before -> factor on the domestic ely price)', 'report',
                sum(1 for x in ely_nin if x['ratio_before'] > K.NINETY), '', True, 'ninety_pct_ely',
                '; '.join(f'{x["region"]} {x["ratio_before"]:.3f} -> pi {x["pi"]:.4g}' for x in
                          sorted((x for x in ely_nin if x['ratio_before'] > K.NINETY), key=lambda x: -x['ratio_before'])[:25]))
    for row in nin_rows:
        if row['industry'] == 'pet':
            row['crude_intake_source'] = crude_src[row['region']]
    NIN = pd.DataFrame(nin_rows)
    adj = NIN[np.isfinite(NIN['pi']) & (np.abs(NIN['pi'] - 1) > 1e-12)]
    for rr in adj.itertuples():
        S.adjust(rr.region, f'{rr.industry} domestic price', rr.domestic_price, rr.domestic_price * rr.pi,
                 'ninety_pct_rule', 'GTAP 12 ch.12 §12.4.3 pp.28-29', 'NINETY-PCT')
    inf = NIN[~np.isfinite(NIN['pi'])]
    S.check('S11-H90', 'The 90 percent rule has a finite solution for every energy industry with domestic sales (own use below 90 percent of domestic revenue)', 'hard',
            len(inf), 0, len(inf) == 0, 'ninety_pct_rule', ' '.join(f'{r.region} {r.industry}' for r in inf.itertuples()))
    nods = NIN[NIN['status'] == 'no_domestic_sales_cannot_adjust']
    for rr in nods.itertuples():
        S.flag('NINETY-PCT-NO-DOMESTIC-SALES', f'{rr.region} {rr.industry}',
               f'energy inputs {rr.energy_cost_before:.1f} USD m are {rr.ratio_before:.2f} x revenue {rr.revenue_before:.1f}, and the industry has no '
               'domestic sales whose price could rise; io_s11 inputs of an industry S11 gives no domestic output (ch.12 §12.2.6), for S13',
               rule='ninety_pct_rule', citation='GTAP 12 ch.12 §12.2.6, §12.4.3')
    S.check('S11-R90nods', 'Energy industries above the 90 percent bound with no domestic sales to reprice (flagged for S13)', 'report',
            len(nods), '', True, 'ninety_pct_rule', ' '.join(f'{r.region} {r.industry}' for r in nods.itertuples()))
    wild = NIN[np.isfinite(NIN['pi']) & ((NIN['pi'] > PI_MISMATCH) | (NIN['pi'] < 1 / PI_MISMATCH))]
    for rr in wild.itertuples():
        S.flag('NINETY-PCT-IO-VOLUME-MISMATCH', f'{rr.region} {rr.industry}',
               f'90 percent rule factor {rr.pi:.3g} on the domestic price: io_s10 energy inputs {rr.energy_cost_before:.1f} USD m against '
               f'S11 revenue {rr.revenue_before:.1f}; an io/volume mismatch (ch.12 §12.2.6), for S13', rule='ninety_pct_rule',
               citation='GTAP 12 ch.12 §12.2.6, §12.4.3')
    S.check('S11-R90wild', f'Domestic price factors from the 90 percent rule above {PI_MISMATCH:g} or below 1/{PI_MISMATCH:g} (io/volume mismatch, flagged for S13)', 'report',
            len(wild), '', True, 'ninety_pct_rule', ' '.join(f'{r.region} {r.industry} {r.pi:.3g}' for r in wild.itertuples()))
    # apply pi to domestic prices and output values (export and import prices fixed)
    for rr in adj.itertuples():
        m = (V['region'] == rr.region) & (V['commodity'] == rr.industry)
        old = float(V.loc[m, 'domestic_sales_value'].iloc[0]) - float(V.loc[m, 'ngpl_value'].iloc[0]) - float(V.loc[m, 'pass_through_value'].iloc[0])
        V.loc[m, 'domestic_price'] *= rr.pi
        V.loc[m, 'domestic_price_rule'] = V.loc[m, 'domestic_price_rule'] + '+ninety_pct'
        V.loc[m, 'domestic_sales_value'] = old * rr.pi + float(V.loc[m, 'ngpl_value'].iloc[0]) + float(V.loc[m, 'pass_through_value'].iloc[0])
        V.loc[m, 'output_value'] = V.loc[m, 'export_value'] - V.loc[m, 'export_tax'] + V.loc[m, 'domestic_sales_value']
    if ely_rule_on:
        # the power fuels S13 holds, at the prices after the rule (the rule may lower a domestic fuel price)
        PF = pd.DataFrame(PWR.power_fuel_rows(R, pfuels, V.set_index(['region', 'commodity'])), columns=PF_COLS)
    if ely_target_on:
        # beta v4 P1 (choice ely_output_value): the ely industry's sales include the gas it resells through the network and the
        # heat of the 088 plants (gdt and steam are inside ely, B7), at cost; the ely output value is then an S13 target
        pt = PWR.pass_through_values(R, PF, heat_sh)
        for r_, v_ in pt.items():
            m = (V['region'] == r_) & (V['commodity'] == 'ely')
            V.loc[m, 'pass_through_value'] = v_
            V.loc[m, 'domestic_sales_value'] = V.loc[m, 'domestic_sales_value'] + v_
            V.loc[m, 'output_value'] = V.loc[m, 'output_value'] + v_
        top_pt = sorted(pt.items(), key=lambda kv: -kv[1])[:12]
        S.check('S11-Relypass', 'Electricity output targets (beta v4 P1; choice ely_output_value): network gas to households and commerce plus the heat '
                'share of the 088 burn, resold at cost and added to ely domestic sales (USD bn, largest 12)', 'report',
                f'{sum(pt.values()) / 1e3:.1f} bn', '', True, 'ely_output_value', '; '.join(f'{r_} {v_ / 1e3:.2f}' for r_, v_ in top_pt))
    if ely_floor90_on:
        # S16 2026-10-26 (P1 revised): the ely floor S13 holds against the prior column is the 90 percent rule as a minimum,
        # (energy inputs + own use at S11 prices after the rule) / 0.9 + the pass-through resold at cost; not price x generation
        cost90 = NIN[NIN['industry'] == 'ely'].set_index('region')['energy_cost_after'].to_dict()
        m = V['commodity'] == 'ely'
        pt_floor = (PWR.pass_through_values(R, PWR.at_purchaser(PF, k_purch), heat_sh) if ely_purch else
                    dict(zip(V.loc[m, 'region'], V.loc[m, 'pass_through_value'])))
        # beta v4 rescan N2 (choice ely_floor_headroom, default off): the floor rises toward the S11 value up to a fuel share of 0.8
        hr = C.ELY_FLOOR_HEADROOM_RATIO if C.switched_on(choices, 'ely_floor_headroom') else None
        fl90 = {r_: K.ely_ninety_floor(cost90.get(r_, 0.0), pt_floor.get(r_, 0.0)) for r_ in V.loc[m, 'region']}
        V.loc[m, 'ely_floor_value'] = [K.ely_ninety_floor(cost90.get(r_, 0.0), pt_floor.get(r_, 0.0), value=v_, headroom=hr)
                                       for r_, v_ in zip(V.loc[m, 'region'], V.loc[m, 'output_value'])]
        up = sorted(((r_, fl90[r_], f_) for r_, f_ in zip(V.loc[m, 'region'], V.loc[m, 'ely_floor_value']) if f_ > fl90[r_] + 1e-9),
                    key=lambda x: x[1] - x[2])
        S.check('S11-Relyheadroom', 'Beta v4 rescan N2 (choice ely_floor_headroom): ely floors raised from the 90 percent bound toward the S11 '
                f'value, up to a fuel share of {C.ELY_FLOOR_HEADROOM_RATIO:g} (USD million; the S13 target is max(prior column, floor))', 'report',
                len(up), '', True, 'ely_floor_headroom',
                (f'{choices["ely_floor_headroom"]["value"]}; +{sum(b - a for _, a, b in up) / 1e3:.2f} bn; '
                 + '; '.join(f'{r_} {a:.0f} -> {b:.0f}' for r_, a, b in up[:25])) if up else f'{choices["ely_floor_headroom"]["value"]}; none')
        if ely_purch:
            S.check('S11-Relypurch', 'S16 2026-10-26 (choice ely_fuel_purchaser_price): the ely 90 percent rule and floor take the power fuels, own '
                    'use and pass-through at purchaser prices, basic x (1 - IEA subsidy rate, at most 0.8); largest cuts (factor)', 'report',
                    sum(1 for (r_, c_), f_ in k_purch.items() if c_ in PWR.RULE_FUELS + ('ely',)), '', True, 'ely_fuel_purchaser_price',
                    '; '.join(f'{r_} {c_} {f_:.3f}' for (r_, c_), f_ in sorted(k_purch.items(), key=lambda kv: kv[1])[:25]))
    # fix round w16 (GTAP 12 ch.12 §12.2.4): supply = use in every region whose use is measured, after the balance
    if su_scope:
        nb, det = 0, []
        for c in su_scope:
            b_, d_ = K.supply_use_balanced(R, vol[c]['production'], vm[c], vx[c], dvol[c], dmeas[c])
            nb += b_
            if d_:
                det.append(f'{c}: {d_}')
        ob = dmeas['oil'] & (use_vol['oil'] > 0) if 'oil' in dvol else np.zeros(n, bool)
        b_, d_ = K.crude_use_absorbed(V, R, crude_in, direct_mbbl, ob)
        nb += b_
        if d_:
            det.append(f'oil absorption: {d_}')
        S.check('S11-Hsupuse', 'Fix round w16 (GTAP 12 ch.12 §12.2.4): production + imports = measured domestic use + exports in every region '
                'whose use is measured, per balanced good (1e-9 relative), and refinery crude intake + direct use = the oil absorption '
                'of energy_values (1e-6)', 'hard', nb, 0, nb == 0, 'energy_supply_use_balance',
                '; '.join(det) or ', '.join(f'{c} {int(dmeas[c].sum())} measured regions, {su_iter[c]} iterations' for c in su_scope))
        SU = pd.DataFrame(su_rows)
        Vk = V.set_index(['region', 'commodity'])
        for when in ('before', 'after'):
            xp = np.array([float(Vk.loc[(r.region, r.commodity), 'export_price']) for r in SU.itertuples()])
            dp = np.array([float(Vk.loc[(r.region, r.commodity), 'domestic_price']) for r in SU.itertuples()])
            SU[f'export_value_{when}'] = SU[f'exports_{when}'] * xp
            SU[f'domestic_sales_value_{when}'] = np.maximum(SU[f'production_{when}'] - SU[f'exports_{when}'], 0) * dp
            SU[f'output_value_{when}'] = SU[f'export_value_{when}'] + SU[f'domestic_sales_value_{when}']
        SU['moved'] = SU['measured_use'] & ((SU['supply_use_factor'] - 1).abs() > 1e-6)
        mv = SU[SU['moved']].assign(dv=lambda d: d['output_value_after'] - d['output_value_before'])
        for x in mv.itertuples():
            S.flag('SUPPLY-USE-TWO-SIDED', f'{x.region} {x.commodity}',
                   f'supply x {x.supply_use_factor:.4f}, use / {x.supply_use_factor:.4f}: production {x.production_before:.4g} -> {x.production_after:.4g}, '
                   f'exports {x.exports_before:.4g} -> {x.exports_after:.4g}, absorption {x.absorption_before:.4g} -> {x.absorption_after:.4g} {x.unit}; '
                   f'output value at S11 prices {x.output_value_before:.1f} -> {x.output_value_after:.1f} USD m',
                   rule='energy_supply_use_balance', citation='GTAP 12 ch.12 §12.2.4')
        top = mv.reindex(mv['dv'].abs().sort_values(ascending=False).index).head(25)
        S.check('S11-Rsupuse', 'Fix round w16: regions and goods moved by the two-sided supply-use balance (supply x a, use / a, with world '
                'exports = imports); output value at the S11 prices before -> after, largest 25 by change (supply_use_balance_s11.csv)', 'report',
                ', '.join(f'{c} {int(mv["commodity"].eq(c).sum())}' for c in su_scope), '', True, 'energy_supply_use_balance',
                '; '.join(f'{x.region} {x.commodity} a {x.supply_use_factor:.3f} P {x.production_before:.4g}->{x.production_after:.4g} '
                          f'X {x.exports_before:.4g}->{x.exports_after:.4g} {x.unit}, value {x.output_value_before / 1e3:.2f}->{x.output_value_after / 1e3:.2f} bn'
                          for x in top.itertuples()))
    else:
        SU = pd.DataFrame()
    excl = []
    for c in COMMODITIES:
        if c in su_scope:
            continue
        cons = vol[c]['consumption']
        ok = np.isfinite(cons)
        sup_ = np.nan_to_num(vol[c]['production_raw']) + np.nan_to_num(vol[c]['imports']) + (ngpl if c == 'pet' else 0.0)
        use_ = np.nan_to_num(cons) + np.nan_to_num(vol[c]['exports'])
        gap_ = np.where(ok, sup_ - use_, 0.0)
        big = np.argsort(-np.abs(gap_))[:5]
        excl.append(f'{c}: {int(ok.sum())} regions with a use volume, world |P + M - C - X| {np.abs(gap_).sum():.4g} {UNIT[c]} '
                    f'(largest {", ".join(f"{R[i]} {gap_[i]:.4g}" for i in big)})' + (' (pet supply includes NGPL)' if c == 'pet' else ''))
    S.check('S11-Rsupuseexcl', 'Goods not balanced two-sided (energy_supply_use_balance): supply less use where the PREP use volume exists '
            '(pet: JODI demand includes NGL and biofuels; ely: EIA net consumption excludes losses and own use)', 'report',
            len(excl), '', True, 'energy_supply_use_balance', '; '.join(excl))

    # fix-round A10: the S11 energy-balance caps S13 applies to the refinery crude cell and the gas own-use cell
    g_own, g_sup = SRC.unsd_gas_own_use_2022(unsd_path, num_iso)
    CAPS = M.energy_use_caps(V, R, crude_in, crude_src, iso_region, g_own, g_sup, gas_pet=gas_pet, pi=pi_all,
                             own_share={r_: d_['pet'] for r_, d_ in (own_in or {}).items() if 'pet' in d_}, ely_subsidy=ely_sub)
    S.check('S11-Rcaps', 'Energy-balance caps written for S13 (fix-round A10): regions with a measured refinery crude intake, and with a UNSD gas own-use share', 'report',
            f'{int(CAPS["intake_measured"].sum())} intake; {int(CAPS["gas_own_use_share"].notna().sum())} gas own use', '', True, 'energy_use_caps',
            '; '.join(f'{x.region} {x.gas_own_use_share:.3f}' for x in CAPS.itertuples() if x.region in ('IRN', 'SAU', 'RUS', 'QAT', 'USA')))
    # fix round wG (QA round 2 P5): own use plus losses of each energy good by its own industry, UNSD 2022, for S13's diagonal caps
    ou_goods = M.OWN_USE_GOODS_PET if choices['own_use_shares']['value'] == C.CHOICES['own_use_shares'] else M.OWN_USE_GOODS
    OU = M.own_use_shares(V, R, iso_region, unsd_own, goods=ou_goods, loss_split=loss_split, loss_drop=loss_drop)
    if own_over:
        OU = M.apply_own_use_overrides(OU, own_over)
    n_ou, d_ou = K.own_use_shares_ok(OU, V, goods=ou_goods)
    S.check('S11-Hownuse', 'Own-use shares for S13 (fix round wG): every region and good (coa, oil, gas, ely; pet with own_use_shares, beta v4 P15) with S11 output has a UNSD 2022 '
            'own use + losses share of production in [0, 1] (or the median of reporters) and its value at the S11 output value', 'hard',
            n_ou, 0, n_ou == 0, 'own_use_shares', d_ou)
    big = [('GBR', 'ely'), ('FRA', 'ely'), ('DEU', 'ely'), ('RUS', 'ely'), ('CHN', 'ely'), ('USA', 'ely'), ('MEX', 'gas'), ('DEU', 'gas'), ('ESP', 'gas')]
    OUi = OU.set_index(['region', 'commodity'])
    S.check('S11-Rownuse', 'Own use + losses as a share of production (UNSD 2022) written for S13 (own_use_s11.csv), by basis', 'report',
            '; '.join(f'{k} {v}' for k, v in OU.groupby('basis').size().items()), '', True, 'own_use_shares',
            '; '.join(f'{r} {c} {OUi.loc[(r, c), "own_use_share"]:.3f}' for r, c in big if (r, c) in OUi.index))
    nin_after = K.ninety_after(NIN)
    S.check('S11-H90b', 'After the price change, energy-input cost is at most 90 percent of revenue for every energy industry (1e-9)', 'hard',
            nin_after, 0, nin_after == 0, 'ninety_pct_rule')
    pfix = K.prices_fixed(V, px, pmb, R)
    S.check('S11-Hpfix', 'Export and import prices are the same before and after the 90 percent rule; only domestic prices moved, each with a ledger row', 'hard',
            pfix, 0, pfix == 0 and len(S.ledger) == len(adj), 'ninety_pct_rule', f'{len(adj)} ledger rows')

    # ------------------------------------------------------------- identities
    ident = K.identities(R, COMMODITIES, exi, pxr, new_fob, new_cif, new_vmsb, mrate, tmd, new_tw, V)
    # fix-round B9 (Grok-F1): S11-Hvpv compares S11's export prices with an independent unit value; the arithmetic
    # identity it used to be is S11-Hvpvid
    I(C.CONFIG_DIR + '/vpv_reviewed.csv', 'exporters whose BACI crude or product quantity is reviewed as wrong (beta v4 dry run 3)')
    vpv_rev = C.read_table('vpv_reviewed.csv', ('region', 'commodity', 'decided_by', 'decided_at', 'basis'))
    vpv = K.vpv_source(V, baci_vpv, {'oil': SRC.TOE_PER_BBL_CRUDE, 'pet': 1.0 / ei['bbl_per_t_products']},
                       reviewed={(x['region'], x['commodity']) for x in vpv_rev})
    S.check('S11-Hvpv', f'Crude and product export prices (EI markers) against the BACI 2022 unit value of HS 270900 and 271000: world value-weighted '
            f'ratio within {K.VPV_WORLD[0]}-{K.VPV_WORLD[1]} and every exporter above {K.VPV_BIG_MUSD / 1e3:g} bn within {K.VPV_EXPORTER[0]}-{K.VPV_EXPORTER[1]}', 'hard',
            vpv['summary'], f'{K.VPV_WORLD}; {K.VPV_EXPORTER}', vpv['ok'], 'vpv_source_check',
            vpv['detail'] + '. Coal and gas export prices are BACI unit values themselves (coal_price, gas_price); their outside check is S11-Rcoal (EI markers).')
    # Fable QA E-08: coal and gas export prices are BACI unit values; their outside comparison is the EI 2022 marker of each exporter
    bench = C.read_table('export_price_benchmarks.csv', ('region', 'commodity', 'marker', 'basis', 'decided_by', 'decided_at', 'open_finding'))
    I(C.CONFIG_DIR + '/export_price_benchmarks.csv', 'EI marker of each large coal and gas exporter (Fable QA E-08)')
    pb = K.price_benchmarks(V, bench, ei_coal, hubs)
    S.check('S11-Hpricebench', f'Coal and gas export prices (BACI unit values) against the EI 2022 marker mapped to each exporter above {K.BENCH_BIG_MUSD / 1e3:g} bn '
            f'(config/s11/export_price_benchmarks.csv): each within {K.BENCH_EXPORTER[0]}-{K.BENCH_EXPORTER[1]} x its marker, value-weighted within '
            f'{K.BENCH_WORLD[0]}-{K.BENCH_WORLD[1]}; the ±{K.BENCH_REPORT:.0%} band is reported (coking coal in the mix, oil-linked contracts against hub prices)', 'hard',
            pb['summary'], f'{K.BENCH_EXPORTER}; {K.BENCH_WORLD}', pb['ok'], 'coal_price, gas_price; GTAP 12 ch.12 §12.4; Fable QA E-08', pb['detail'])
    S.write('export_price_benchmarks_s11.csv', pb['table'])
    S.check('S11-Hvpvid', 'Volume x price = value for bilateral FOB, export and output values (1e-9 relative); an identity inside S11', 'hard',
            f'{ident["vpv"]:.2e}', '1e-9', ident['vpv'] < 1e-9, 'output_value')
    S.check('S11-Hcif', 'CIF = FOB x (1 + margin rate) per route, VTWR by mode sums to CIF - FOB, VMSB = CIF x (1 + tm) (1e-9 relative)', 'hard',
            f'{ident["cif"]:.2e}', '1e-9', ident['cif'] < 1e-9, 'cif_after_override')
    S.check('S11-Hneg', 'No negative or non-finite price, volume or value in the S11 energy arrays', 'hard',
            ident['neg'], 0, ident['neg'] == 0, 'output_value', ident['neg_detail'])
    # beta v4 dry run 3: world exports against world imports as written, after the balance and the ras_feasible_vectors cut
    # (S11-Hfeascut; the max flow cuts both sides by the same volume), not against the balance's world_after before the cut
    S.check('S11-Hbal', 'World exports = world imports per commodity after the balance and the feasible-route cut (1e-9 relative)', 'hard',
            f'{max(abs(vx[r["commodity"]].sum() - vm[r["commodity"]].sum()) / max(r["world_after"], 1e-300) for r in bal_rows):.2e}', '1e-9',
            all(abs(vx[r['commodity']].sum() - vm[r['commodity']].sum()) <= 1e-9 * max(r['world_after'], 1) for r in bal_rows), 'volume_balance',
            '; '.join(f'{r["commodity"]} balance {r["world_after"]:.6g} -> written {vx[r["commodity"]].sum():.6g} {r["unit"]}' for r in bal_rows))
    S.check('S11-Hsrc', 'Every export price has a source ID; none is a calibration result', 'hard',
            int(sum((psrc[c] == '').sum() for c in COMMODITIES)), 0, all((psrc[c] != '').all() for c in COMMODITIES), 'price_missing')
    S.check('S11-Hngl', 'NGL parity (E29): oil volumes are EIA 57 or JODI CRUDEOIL without NGPL; NGPL is booked to pet only', 'hard',
            K.ngl_parity(ngl_raw), 0, K.ngl_parity(ngl_raw) == 0, 'ngl_to_pet')
    gas_bad = K.gas_balance(V, ('IRQ', 'IRN'))
    S.check('S11-Hgasbal', 'Gas balance for IRQ and IRN: production >= domestic use + exports - imports (PLAN §3(g))', 'hard',
            gas_bad or 'every region passes', 0, gas_bad == '', 'energy_volume_source', (gas_bad + '. ' if gas_bad else '') + K.gas_balance_values(V, ('IRQ', 'IRN')))
    # pinned to the S09 snapshot adf13a8 of the F-12 rerun (S09-H12 dust); it was e4ade8a2 at the S09 Bermuda restamp 225ad2d
    trav_ok = sha256(travel_path) == S09_TRAVEL_SHA
    S.check('S11-Htravel', f'travel_s09 is read for its hash only and equals the pinned S09 travel file ({S09_TRAVEL_SHA[:8]}...)', 'hard',
            sha256(travel_path)[:12], S09_TRAVEL_SHA[:12], trav_ok, 'travel_energy')

    # ------------------------------------------------------------- outputs
    def rnd(df):
        # 1e-6 (one USD in million USD): RAS and QP noise in near-zero cells differs across machines
        df = df.copy()
        fl = df.select_dtypes('float').columns
        df[fl] = df[fl].round(6) + 0.0
        return df

    def write(name, df):
        S.write(name, rnd(df))

    def gzcsv(name, df):
        p = f'{S.out}/{name}'
        with gzip.GzipFile(p, 'wb', mtime=0) as fh:
            fh.write(rnd(df).to_csv(index=False, float_format='%.10g').encode())
        S.log(f'output {name}: {len(df)} rows')

    def long(mats, name):
        recs = []
        for c in COMMODITIES:
            A = mats[c]
            ii, jj = np.nonzero(A)
            recs.append(pd.DataFrame({'sector': c, 'exporter': np.array(R)[ii], 'importer': np.array(R)[jj], name: A[ii, jj]}))
        return pd.concat(recs, ignore_index=True)

    vf = long(new_fob, 'vfob_musd')
    vf['export_tax_rate'] = [xtm[c][ix[e], ix[i_]] for c, e, i_ in zip(vf['sector'], vf['exporter'], vf['importer'])]
    vf['vxsb_musd'] = vf['vfob_musd'] * (1.0 - vf['export_tax_rate'])
    of = long(old_fob, 'vfob_s10_musd')
    vf = vf.merge(of, on=['sector', 'exporter', 'importer'], how='left').fillna({'vfob_s10_musd': 0.0})
    sd_l = long({c: seeded[c].astype(float) for c in COMMODITIES}, 'seeded')
    vf = vf.merge(sd_l, on=['sector', 'exporter', 'importer'], how='left').fillna({'seeded': 0.0})
    vf['seeded'] = vf['seeded'].map({1.0: 'yes', 0.0: 'no'})
    vf = vf[['sector', 'exporter', 'importer', 'vxsb_musd', 'vfob_musd', 'export_tax_rate', 'vfob_s10_musd', 'seeded']]
    # fix round w16: S13 sums the written routes into each exporter's X. Routes are rounded to 1e-6 so that they add up to
    # the rounded total; where a good has no domestic sales (all exported) that total is the output value S13 holds, so
    # the target and the exports S13 reads agree exactly (summed independent roundings left 4e-6 USD m at GNQ crude)
    key = vf['sector'] + ' ' + vf['exporter']
    allx = {f'{x.commodity} {x.region}': x.output_value for x in V.itertuples() if x.domestic_sales_value == 0 and x.output_value > 0}
    vf['vxsb_musd'] = M.round_to_total(vf['vxsb_musd'], key, allx)
    vf['vfob_musd'] = M.round_to_total(vf['vfob_musd'], key)
    gzcsv('vfob_energy_s11.csv.gz', vf)
    rr_idx = pd.MultiIndex.from_product([COMMODITIES, R, R], names=['sector', 'exporter', 'importer'])
    rr = pd.Series(np.concatenate([xtm[c].ravel() for c in COMMODITIES]), index=rr_idx)
    n_xt, det_xt = K.energy_export_tax(pd.read_csv(f'{S.out}/vfob_energy_s11.csv.gz'), xt10, vfob10, V, TRADE_SECTORS, route_rate=rr)
    xt_by = V[V['export_tax'] > 0].groupby('region')['export_tax'].sum().sort_values(ascending=False)
    S.check('S11-Hxtax', 'Fix list A2: on every energy route as written, VXSB = VFOB x (1 - t) with t the route rate (Fable QA C-03: the S10 export-tax '
            'rate of the exporter and good, except EAEU internal routes and the line mix of RUS gas), the S10 vfob_s10 export_tax_rate agrees with '
            'export_tax_s10.csv, and the export tax in energy_values_s11 is VFOB - VXSB summed by region and good', 'hard',
            n_xt, 0, n_xt == 0, 'export_tax_after_override; GTAP 12 ch.17A eq. 17.30',
            det_xt or f'{bn(V["export_tax"].sum()):.3f} bn on S11 VFOB: ' + '; '.join(f'{r} {bn(v):.3f}' for r, v in xt_by.items()))
    ex = long(exi, 'volume')
    ex['unit'] = ex['sector'].map(UNIT)
    mtoe_f = K.mtoe_factors(R, ei, SRC.unsd_coal_heat(unsd_path, dict(zip(iso_num['numeric'].str.zfill(3), iso_num['alpha3']))), cmap, vol)
    ex['mtoe'] = ex['volume'] * [mtoe_f[(r.sector, r.exporter)] for r in ex.itertuples()]
    gzcsv('exi_s11.csv.gz', ex)
    tl = []
    for c in COMMODITIES:
        for k, m in enumerate(MODES):
            A = new_tw[c][k]
            ii, jj = np.nonzero(A)
            tl.append(pd.DataFrame({'margin': m, 'sector': c, 'exporter': np.array(R)[ii], 'importer': np.array(R)[jj], 'vtwr_musd': A[ii, jj]}))
    gzcsv('vtwr_energy_s11.csv.gz', pd.concat(tl, ignore_index=True))
    ms = []
    for c in COMMODITIES:
        ii, jj = np.nonzero(new_cif[c])
        ms.append(pd.DataFrame({'importer': np.array(R)[jj], 'exporter': np.array(R)[ii], 'sector': c,
                                'vcif_musd': new_cif[c][ii, jj], 'vmsb_musd': new_vmsb[c][ii, jj], 'tm': tmd[c][ii, jj],
                                'tm_source': tsrc[c][ii, jj], 'margin_rate_fob': mrate[c][ii, jj], 'margin_source': msrc[c][ii, jj]}))
    MS = pd.concat(ms, ignore_index=True)
    gzcsv('vmsb_energy_s11.csv.gz', MS)
    write('vst_s11.csv', vst[['margin', 'region', 'vst_musd', 'factor', 'vst_musd_s11']].rename(columns={'vst_musd': 'vst_musd_s08'}))
    V['mtoe_per_unit'] = [mtoe_f[(r.commodity, r.region)] for r in V.itertuples()]
    for k in ('production', 'exports', 'imports', 'absorption'):
        V[f'{k}_mtoe'] = V[k] * V['mtoe_per_unit']
    write('energy_values_s11.csv', V)
    vsum = []
    for c in COMMODITIES:
        for i, r in enumerate(R):
            vsum.append(dict(region=r, commodity=c, unit=UNIT[c], production_raw=vol[c]['production_raw'][i], production=vol[c]['production'][i],
                             production_source=vsrc[c]['production'][i], imports_raw=vol[c]['imports'][i], imports_source=vsrc[c]['imports'][i],
                             exports_raw=vol[c]['exports'][i], exports_source=vsrc[c]['exports'][i], reexports=rx[c][i],
                             exports_balanced=vx[c][i], imports_balanced=vm[c][i], mtoe_per_unit=mtoe_f[(c, r)]))
    write('volumes_s11.csv', pd.DataFrame(vsum))
    write('prices_s11.csv', V[['region', 'commodity', 'price_unit', 'export_price', 'export_price_source', 'import_cif_price',
                                 'import_basic_price', 'domestic_price', 'domestic_price_rule']])
    write('reexports_s11.csv', pd.DataFrame(rx_rows))
    write('balance_s11.csv', pd.DataFrame(bal_rows))
    write('supply_use_s11.csv', pd.DataFrame(sup_rows, columns=['region', 'commodity', 'unit', 'production', 'imports', 'exports', 'factor',
                                                                 'production_after', 'imports_after', 'exports_after', 'step']))
    write('ras_s11.csv', pd.DataFrame(ras_rows))
    if su_scope:
        write('supply_use_balance_s11.csv', SU)
    write('volume_fills_s11.csv', pd.DataFrame(fill_rows, columns=['region', 'commodity', 'flow', 'volume', 'unit', 'value_musd', 'implied_volume', 'flag']))
    gzcsv('io_s11.csv.gz', io11)
    write('b06_split_s11.csv', B)
    write('crude_cell_split_s11.csv', CS)
    write('power_fuels_s11.csv', PF)
    GP = pd.DataFrame(gp_rows)
    write('refinery_gas_s11.csv', GP)
    S.check('S11-Rrefgas', 'Gas into refining from UNSD refinery gas: value at S11 gas prices (the 90 percent rule) and the io_s11 B06 -> pet gas cells (io_s10 scale), world, and the regions that report', 'report',
            f'{(GP["value_dom_musd"] + GP["value_imp_musd"]).sum() / 1e3:.1f} bn at S11 prices; io_s11 cells {(GP["gas_to_pet_dom"] + GP["gas_to_pet_imp"]).sum() / 1e3:.1f} bn; '
            f'{int((GP["basis"] == "unsd_0925_086").sum())} reporting regions; '
            f'fill {coef_avg:.1f} TJ per million bbl', '', True, 'refinery_gas')
    write('ninety_pct_s11.csv', NIN)
    write('energy_use_caps_s11.csv', CAPS)
    write('own_use_s11.csv', OU)
    booked = None
    if subsidy_on:
        # each IEA country's share of its region's booked subsidy (booked over the region's IEA value: the volume harmonisation and step 2)
        fs_share = {(x.commodity, x.region): x.subsidy_musd / x.iea_subsidy_musd if x.iea_subsidy_musd > 0 else 0.0 for x in FS.itertuples()}
        booked = {(nm, pr): v * deflator * fs_share[(c, iso_region.get(iso))] for nm, iso in iea_map.items() for pr, c in SRC.IEA_PRODUCT.items()
                  for v in [iea_sub.get((c, iso), 0.0)] if v > 0 and (c, iso_region.get(iso)) in fs_share}
    sub = K.subsidies(R, iea_path, booked)
    write('subsidy_s11.csv', sub)
    # written (empty) when fuel_subsidies is off too, so S13 always finds it; the price after the 90 percent rule is for
    # reference (the subsidy is measured before it)
    FS = FS.merge(V[['region', 'commodity', 'domestic_price']].rename(columns={'domestic_price': 'domestic_price_final'}),
                  on=['region', 'commodity'], how='left')
    write('fuel_subsidies_s11.csv', FS)
    tc = K.trade_change(R, COMMODITIES, old_fob, new_fob)
    write('trade_change_s11.csv', tc)
    # Fable QA F-07 (2026-10-25): the S07 re-export hubs keep S07's retained imports for every good but energy; S11
    # values hub energy trade by volume x price after the ch.12 §12.2.5 re-export removal, as it does for every region
    rx_df = pd.DataFrame(rx_rows)
    hub_tc = tc[tc['region'].isin(C.S07_REEXPORT_HUBS) & ((tc['exports_s10_musd'].abs() + tc['imports_s10_musd'].abs()) > 100)]
    S.check('S11-Rhubenergy', 'Energy trade of the S07 re-export hubs (Fable QA F-07): S10 and S11 exports and imports (bn) and the '
            're-export volume and basis (GTAP 12 ch.12 §12.2.5); S07 retained imports of energy are replaced by S11 by design', 'report',
            len(hub_tc), '', True, 'reexport_removal',
            '; '.join(f'{x.region} {x.commodity} X {x.exports_s10_musd / 1e3:.1f}->{x.exports_s11_musd / 1e3:.1f} '
                      f'M {x.imports_s10_musd / 1e3:.1f}->{x.imports_s11_musd / 1e3:.1f}'
                      + ''.join(f' rx {y.reexports:.1f} {y.unit} {y.basis}' for y in rx_df[(rx_df['region'] == x.region)
                                & (rx_df['commodity'] == x.commodity)].itertuples())
                      for x in hub_tc.itertuples()))
    usa = K.usa_table(V, vol, mer, spot, io10)
    write('usa_energy_s11.csv', usa)
    oc = K.oil_check(V, io10, R)
    write('oil_check_s11.csv', oc)
    open(S.out + '/NOT_FOR_PUBLICATION.md', 'w').write(
        '# Not for publication\n\nThese S11 outputs carry TRAINS-derived duty (S10 tm) or are built on io_s10, which is private for the '
        'same reason. They are committed to this private repository only (David, 2026-10-21 11:55 and 2026-10-23).\n\n'
        '- `vmsb_energy_s11.csv.gz` (S10 tm on the new CIF)\n- `energy_values_s11.csv` (import basic prices use VMSB)\n'
        '- `prices_s11.csv` (import basic prices)\n- `ninety_pct_s11.csv` (io_s11 inputs, VMSB prices)\n'
        '- `energy_use_caps_s11.csv` (refinery crude intake at VMSB import prices)\n'
        '- `own_use_s11.csv` (own-use values at S11 output values, whose domestic prices can be VMSB import basic prices)\n'
        '- `fuel_subsidies_s11.csv` (reference prices of net importers are VMSB import basic prices)\n'
        '- `io_s11.csv.gz` and `b06_split_s11.csv` (io_s10 split)\n- `oil_check_s11.csv`, `usa_energy_s11.csv` (io_s10 output values)\n')

    # ------------------------------------------------------------- report checks
    for r in ras_rows:
        S.check(f'S11-Rtrade-{r["commodity"]}', f'World {r["commodity"]} FOB before and after the override (GTAP Table 12.10 style)', 'report',
                f'{bn(r["old_fob_musd"]):.1f} -> {bn(r["new_fob_musd"]):.1f} bn', '', True, 'energy_trade_scope')
    nonen = K.non_energy_unchanged(vxsb7, vfob10)
    S.check('S11-Hnonen', 'S11 writes energy trade only: no non-energy sector in the S11 trade files, and S10 VFOB equals S07R VFOB on the energy cells it priced', 'hard',
            nonen, 0, nonen == 0 and set(vf['sector']) <= set(COMMODITIES), 'energy_trade_scope')
    tot = {c: V.loc[V['commodity'] == c, 'output_value'].sum() for c in COMMODITIES}
    S.check('S11-Rhead', 'Headline: world output value by energy commodity (bn), S13 targets coa/oil/gas/pet', 'report',
            '; '.join(f'{c} {bn(v):.1f}' for c, v in tot.items()), '', True, 'energy_output_scope')
    fb = MS[MS['tm_source'].str.startswith('new_pair')]
    S.check('S11-Rnewpair', 'Duty on pairs S10 never priced (new-pair fallback)', 'report',
            f'{len(fb)} cells; VCIF {bn(fb["vcif_musd"].sum()):.3f} bn; duty {bn((fb["vmsb_musd"] - fb["vcif_musd"]).sum()):.3f} bn', '', True, 'duty_after_override')
    hub_chk = K.hub_check(ei, spot)
    S.check('S11-Rhub', 'Product price check: WTI + USGC margin against EIA US Gulf Coast spot (gasoline, diesel, jet)', 'report',
            hub_chk, '', True, 'product_price')
    S.check('S11-Rcoal', 'EI 2022 coal markers (report only) against the BACI export unit values', 'report',
            '; '.join(f'{k} {v:.0f}' for k, v in ei_coal.items()), '', True, 'coal_price',
            'BACI exporter unit values: ' + ', '.join(f'{r} {px["coa"][ix[r]]:.0f}' for r in ('AUS', 'IDN', 'RUS', 'USA', 'ZAF', 'COL') if r in ix))

    # beta v4 dry run (P13, P25): the observed price is the exporter's §12.3 reference (px_ref); its realised VFOB / volume
    # differs once routes are priced by line mix (P25) or at an observed transaction value (P13), and is reported beside it
    nobs, dobs = K.observed_gas_prices(px_ref['gas'], R, gas_obs)
    ei_off = max([abs(a - b) for _, a, b in route_chk] or [0.0])
    S.check('S11-Hgasobs', 'Gas exporters in gas_export_price_observed.csv carry BACI value / observed volume as their reference export price '
            '(the realised VFOB / volume after route pricing is shown beside it); each EI route volume equals the same flow in the importer block', 'hard',
            nobs + int(ei_off > 1e-9), 0, nobs == 0 and ei_off <= 1e-9, 'gas_price_estimated_tonnes',
            dobs or '; '.join(f'{r} {o["price"]:.1f} USD m/bcm ({o["value_musd"]:.1f} USD m / {o["volume_bcm"]:.3f} bcm), realised '
                              f'{px["gas"][ix[r]]:.1f}' for r, o in gas_obs.items() if r in ix))
    flagged = gas_tonnes[(gas_tonnes['bcm_ratio'] < SCR.TONNES_SHARE) & (gas_tonnes['baci_value_musd'] > 0)]
    S.check('S11-Rgastonnes', f'Gas exporters whose BACI tonnes give under {SCR.TONNES_SHARE:.2f} of their volume-source exports (screen 9)', 'report',
            len(flagged), '', True, 'gas_price_estimated_tonnes',
            ', '.join(f'{t.region} {t.bcm_ratio:.2f}{" observed" if t.observed_price else ""}' for t in flagged.itertuples()))

    # licence and secrets
    tracked = subprocess.run(['git', '-C', BUILD, 'ls-files', '--full-name', ROOT.rsplit('/', 1)[0]], capture_output=True, text=True).stdout.split()
    priv = private_paths(tracked)
    S.check('S11-Hprivate', 'No private file (credentials, GTAP database values) is tracked in git (lib/private_files.py)', 'hard',
            len(priv), 0, not priv, 'repo_rules committed_data_rule', ' '.join(priv[:10]))
    sec = K.secret_scan([BUILD + '/s11_energy.py', BUILD + '/s11_energy', BUILD + '/screens/s11_suite.py', C.CONFIG_DIR, S.out])
    S.check('S11-Hsecret', 'Key and password scan of the S11 code, config and outputs (count only)', 'hard', sec, 0, sec == 0, 'never commit credentials')

    # ------------------------------------------------------------- screens
    ctx = dict(R=R, V=V, comms=COMMODITIES, px=px, psrc=psrc, pfill=pfill, exi=exi, old_fob=old_fob, new_fob=new_fob,
               new_cif=new_cif, new_vmsb=new_vmsb, tmd=tmd, mrate=mrate, seeded=seeded, fill_rows=fill_rows,
               prep_dir=UP['PREP'] + '/output', intl_path=intl_path, from_prep=FROM_PREP, unit=UNIT, price_unit=PRICE_UNIT,
               gas_tonnes=gas_tonnes)
    try:
        scr = SCR.run(ctx, log=S.log)
        S.check('S11-Hscreens', 'Population screens (SCREENS.md seven questions plus RAS seeds and gas tonnes): no material unexplained hit', 'hard',
                scr['material_unexplained'], 0, scr['material_unexplained'] == 0, 'screen_materiality', scr['summary'])
    except Exception as e:   # a screen that raises fails the stage
        S.check('S11-Hscreens', 'Population screens ran', 'hard', repr(e)[:200], 'no exception', False, 'screen_materiality')
        raise
    S.finish()


if __name__ == '__main__':
    main()
