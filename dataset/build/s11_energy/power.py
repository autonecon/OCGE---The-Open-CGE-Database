"""Fuel inputs of the electricity column from the energy balance (Fable QA D-06, 2026-10-25; GTAP 12 ch.12 §12.2.2 builds
the I-O energy rows from the energy balance, and ch.17A holds energy volumes by user, valued at prices).

UNSD 2022 transaction 088 (transformation in electricity, CHP and heat plants) by fuel: coal (0100 hard + 0200 brown coal,
kt), natural gas (3000, TJ), crude (4100, kt) and refined products (SIEC 46 leaf codes, kt); and the natural gas that
reaches households (1231) and commerce and public services (1235) through the distribution network, which this data
base keeps inside ely (gdt is part of ely, B7). Volumes go to S11 units and are valued at the S11 domestic basic price and
import basic price, split by the volume shares of domestic sales and imports in absorption. S13 can hold the ely column's
fuel cells at these values (power burn; gas: burn plus distribution).
"""
import numpy as np

from .domestic import GJ_PER_BCM
from .sources import _unsd_rows, UNSD_OIL_PRODUCT_CODES, TOE_PER_BBL_CRUDE

POWER_TRANSACTION = '088'
GAS_DISTRIBUTION_TRANSACTIONS = ('1231', '1235')
COAL_CODES = ('0100', '0200')
# beta v4 P1 (choice ninety_pct_ely): electricity (7000T, GWh) and heat (8000T, TJ) made from combustible fuels
THERMAL_ELY_CODE, THERMAL_HEAT_CODE = '7000T', '8000T'
TJ_PER_GWH = 3.6
RULE_FUELS = ('coa', 'oil', 'gas', 'pet')      # the 088 burn; gas_dist (households and commerce) is resold, not burnt


def unsd_power_fuels_2022(path, num_to_iso3, iso_region, bbl_per_t_products):
    """{region: {fuel: volume in S11 units}} with fuels coa (Mt), gas (bcm, power burn), gas_dist (bcm, households and
    commerce), oil (million bbl crude) and pet (million bbl); members of a composite region summed."""
    out = {}

    def add(iso, k, v):
        r = iso_region.get(iso)
        if r is not None and v > 0:
            d = out.setdefault(r, {})
            d[k] = d.get(k, 0.0) + v

    for code in COAL_CODES:
        for area, _, v in _unsd_rows(path, code, (POWER_TRANSACTION,), 'TN', 3):
            add(num_to_iso3.get(area), 'coa', v / 1e3)                                   # kt -> Mt
    for area, tr, v in _unsd_rows(path, '3000', (POWER_TRANSACTION,) + GAS_DISTRIBUTION_TRANSACTIONS, 'TJ'):
        add(num_to_iso3.get(area), 'gas' if tr == POWER_TRANSACTION else 'gas_dist', v * 1e3 / GJ_PER_BCM)   # TJ -> bcm
    for area, _, v in _unsd_rows(path, '4100', (POWER_TRANSACTION,), 'TN', 3):
        add(num_to_iso3.get(area), 'oil', v / TOE_PER_BBL_CRUDE / 1e3)                  # kt -> million bbl
    for code in UNSD_OIL_PRODUCT_CODES:
        for area, _, v in _unsd_rows(path, code, (POWER_TRANSACTION,), 'TN', 3):
            add(num_to_iso3.get(area), 'pet', v * bbl_per_t_products / 1e3)            # kt -> million bbl
    return out


def power_fuel_rows(R, fuels, V_i):
    """One row per (region, fuel): the volume, its share of S11 absorption (capped at 1) and the value at S11 prices,
    domestic and imported apart. V_i: S11 energy values indexed by (region, commodity)."""
    rows = []
    for r in R:
        for k, q in sorted(fuels.get(r, {}).items()):
            c = 'gas' if k == 'gas_dist' else k
            x = V_i.loc[(r, c)]
            ds, im = max(float(x['domestic_sales']), 0.0), max(float(x['imports']), 0.0)
            ab = ds + im
            q_ = min(q, ab) if ab > 0 else 0.0
            sd = ds / ab if ab > 0 else 1.0
            pd_, pm_ = (float(x['domestic_price']), float(x['import_basic_price']))
            pd_, pm_ = (pd_ if np.isfinite(pd_) else 0.0), (pm_ if np.isfinite(pm_) else pd_)
            rows.append(dict(region=r, fuel=k, commodity=c, io_column='ely', volume_unsd=q, volume=q_,
                             share_of_absorption=q_ / ab if ab > 0 else 0.0,
                             value_dom_musd=q_ * sd * pd_, value_imp_musd=q_ * (1.0 - sd) * pm_))
    return rows


def unsd_heat_share_2022(path, num_to_iso3, iso_region):
    """Beta v4 P1 (choice ninety_pct_ely): {region: heat share of the output energy of the plants that burn combustible
    fuels}, heat (8000T, TJ) over heat plus electricity (7000T, GWh x 3.6), production (01), UNSD 2022, members of a
    composite region summed. Transaction 088 (the S11 power burn) covers electricity, CHP and heat plants; the heat
    share of that burn is left out of the electricity side of the 90 percent rule. A region with no 8000T row has share 0."""
    heat, ely = {}, {}
    for code, unit, d, f in ((THERMAL_HEAT_CODE, 'TJ', heat, 1.0), (THERMAL_ELY_CODE, 'GWHR', ely, TJ_PER_GWH)):
        for area, _, v in _unsd_rows(path, code, ('01',), unit):
            r = iso_region.get(num_to_iso3.get(area))
            if r is not None and v > 0:
                d[r] = d.get(r, 0.0) + v * f
    out = {}
    for r in set(heat) | set(ely):
        h, e = heat.get(r, 0.0), ely.get(r, 0.0)
        out[r] = h / (h + e) if h + e > 0 else 0.0
    return out


def ninety_ely_inputs(R, PF, heat_share, fuels=RULE_FUELS):
    """Beta v4 P1 (GTAP 12 ch.12 §12.4.3 on the electricity industry): {region: {fuel: (domestic value, imported value)}},
    the 088 burn of power_fuel_rows (PF) times the electricity share (1 - heat share) of the plants' output energy, at the
    S11 prices PF was valued at. gas_dist and the heat share are resold by the industry (gdt and steam are inside ely, B7)
    and pass through at cost (pass_through_values), so they are on neither side of the rule (our choice)."""
    out = {r: {} for r in R}
    for x in PF.itertuples():
        if x.fuel not in fuels or x.region not in out:
            continue
        e = 1.0 - float(heat_share.get(x.region, 0.0))
        d, m = out[x.region].get(x.fuel, (0.0, 0.0))
        out[x.region][x.fuel] = (d + e * float(x.value_dom_musd), m + e * float(x.value_imp_musd))
    return out


def purchaser_factors(FS, cap, basis=None):
    """S16 2026-10-26 (choice ely_fuel_purchaser_price): {(region, commodity): 1 - min(rate, cap)}, the purchaser price of a
    subsidised energy good over its basic price; S13 books the subsidy as a negative purchase tax at a rate of at most cap
    (RHO_MAX). FS: the S11 fuel_subsidies frame. The rate is the IEA subsidy per unit over the market price; with basis
    {(region, commodity): domestic sales + imports, USD million} (beta v4 dry run 3, S13-H90fit SAU), a fuel's rate is the
    one S13 books, the S11 subsidy money over that basis, so the rule and floor use S13's rate. ely keeps the per-unit rate
    (its S13 basis is the floor itself). Goods with no row are absent (1)."""
    out = {}
    for x in FS.itertuples():
        p, s = float(x.market_price), float(x.subsidy_per_unit)
        if not (np.isfinite(p) and p > 0 and np.isfinite(s) and s > 0):
            continue
        b = float((basis or {}).get((x.region, x.commodity), 0.0)) if x.commodity != 'ely' else 0.0
        rate = float(x.subsidy_musd) / b if b > 0 and np.isfinite(b) else s / p
        out[(x.region, x.commodity)] = 1.0 - min(rate, cap)
    return out


def power_fuel_subsidy(fs_rows, fuels, heat_share, cap, burn=RULE_FUELS):
    """S16 2026-10-26 (choice ely_subsidy_net_power_fuel): {region: USD million}, the IEA fuel subsidy that falls on the
    electricity part of the power plants' burn: for each burnt fuel with a subsidy row, (1 - heat share) x the UNSD 088
    volume (at most the row's absorption volume) x the rate per unit, at most cap x the market price (S13's RHO_MAX).
    fs_rows: fuel_subsidy_rows; fuels: unsd_power_fuels_2022."""
    rate = {(x['region'], x['commodity']): (min(float(x['subsidy_per_unit']), cap * float(x['market_price'])), float(x['absorption_volume']))
            for x in fs_rows if x['commodity'] in burn}
    out = {}
    for r, d in fuels.items():
        v = 0.0
        for k, q in d.items():
            if k in burn and (r, k) in rate:
                s, ab = rate[(r, k)]
                v += (1.0 - heat_share.get(r, 0.0)) * min(max(q, 0.0), max(ab, 0.0) if np.isfinite(ab) else q) * max(s, 0.0)
        out[r] = v
    return out


def at_purchaser(PF, k):
    """power_fuel_rows (PF) with the values at purchaser prices: each row times k[(region, commodity)] (purchaser_factors)."""
    f = np.array([k.get((r, c), 1.0) for r, c in zip(PF['region'], PF['commodity'])])
    return PF.assign(value_dom_musd=PF['value_dom_musd'] * f, value_imp_musd=PF['value_imp_musd'] * f)


def pass_through_values(R, PF, heat_share, fuels=RULE_FUELS):
    """Beta v4 P1 (choice ely_output_value): {region: USD million} the ely industry resells at cost: the gas that reaches
    households and commerce through the network (gas_dist) plus the heat share of the 088 burn, at the S11 prices PF was
    valued at. Our choice: no distribution margin is added."""
    out = {r: 0.0 for r in R}
    for x in PF.itertuples():
        if x.region not in out:
            continue
        v = float(x.value_dom_musd) + float(x.value_imp_musd)
        if x.fuel == 'gas_dist':
            out[x.region] += v
        elif x.fuel in fuels:
            out[x.region] += float(heat_share.get(x.region, 0.0)) * v
    return out
