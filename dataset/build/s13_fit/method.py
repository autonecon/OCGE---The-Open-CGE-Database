"""S13 FIT method (GTAP 12 ch.17A): the held targets, the prior table of each region and the fitted table.

Targets held in the fit (ch.17A p.2, items 1-6):
  1. C, G and I: S02 values scaled by one common factor per region so that GDP = S02 GDP with trade fixed
     (decision 2; Aguiar et al. 2022 p.6).
  2. Exports at basic prices (VXSB) and border prices (VFOB), imports at border (VCIF) and basic prices
     (VMSB), by commodity: goods from S10, energy from S11, services from S09, travel goods from S09.
  3. Stock change: eliminated (footnote 2).
  4-5. Tax rates: the net product-tax rate of each cell. The energy rows (pet, coa, gas, ely) carry the
     GTAP ad valorem energy-tax rates (S10 specific rates over the S11 basic price; GTAP 12 ch.12 §12.4.4, fix list A1)
     on top of the column's general part, which the other rows carry by commodity from the S10 VAT and excise layers
     (pattern_rates; non_energy_rates, QA round 2 P1) or at one general rate (place_column_taxes), the same on domestic
     and imported purchases; export
     taxes in VXSB/VFOB; and (by choice) the S10 PSE output and input payments as an output tax and an input
     tax on crp.
  6. Energy: the S11 coal, oil, gas and petroleum output values (erratum E49; GTAP holds IEA balances).
  Fossil-fuel consumption subsidies (fix-round B15; Chepeliev et al. 2018 §3): the S11 IEA subsidy (price-gap rows and the
  extension rows of David's 2026-10-24 decision) is a
  negative purchase tax on the region's purchases of the good by firms, households and government, domestic and
  imported, with the prior purchasers' value of each cell kept (book_fuel_subsidies).
Factor prices are fixed and each activity's factor composition is the S12 one (eq. 17.27).
"""
import numpy as np
import pandas as pd

from .fit import Column, Problem, solve, information
from . import energy as EN
from . import ptax_source as PS

FD = ('p', 'g', 'i')
FACTORS = ('land', 'off_mgr_pros', 'tech_aspros', 'clerks', 'service_shop', 'ag_othlowsk', 'capital', 'natres')
ENERGY_TARGETS = ('coa', 'oil', 'gas', 'pet')
ENERGY_TRADE = ('coa', 'oil', 'gas', 'pet', 'ely')
# beta v4 P1 (s13 choice energy_targets): every S11 target row is held, electricity too where S11 sets one
ENERGY_TARGETS_ELY = 'every_s11_target_yes_row_coa_oil_gas_pet_and_ely_where_s11_sets_it'
ENERGY_TARGETS_V3 = 's11_output_values_coa_oil_gas_pet_target_yes'


def output_targets(rule):
    """The goods whose S11 output value S13 holds (s13 choice energy_targets)."""
    return ENERGY_TARGETS + (('ely',) if rule == ENERGY_TARGETS_ELY else ())
TINY_MAX_MUSD = 10.0          # beta v4 P38: output value below 10 USD million ...
TINY_MAX_SHARE = 0.02         # ... and below 2 percent of output plus imports (VMSB) ...
TINY_MAX_EXPORT = 1e-3        # ... with exports at most 1 thousand USD
TINY_ABS_MUSD = 1.0           # ... or below 1 USD million outright (dry run 3: MAR crude 0.92 m with no imports)


def ely_netted_own_use(io, shares):
    """Beta v4 H2 (s13 choice ely_hold_net_own_use): by region, the domestic ely own use (USD million) that the own-use cap
    (energy.cap_own_use) nets out of the ely row and column, estimated on io_s12: d = dom_ely + imp_ely in the ely column,
    col = its output (OUT), s = the S11 UNSD own use + losses share; k d = s (col - (1 - k) d), and the domestic part
    dom_ely (1 - k) leaves. shares: {region: {good: share}}. The cap itself runs later on the prior at agents' prices, so
    the two can differ by the taxes on the diagonal."""
    out = {}
    if 'ely' not in io.columns:
        return out
    t = io[io['row'].isin(['dom_ely', 'imp_ely', 'OUT'])].pivot_table(index='region', columns='row', values='ely', aggfunc='sum')
    for reg, x in t.iterrows():
        s = (shares.get(reg) or {}).get('ely')
        dom, imp, col = (float(x.get(k, 0.0)) for k in ('dom_ely', 'imp_ely', 'OUT'))
        d = dom + imp
        if s is None or not np.isfinite(s) or s >= 1.0 or d <= 0 or col <= 0 or d <= s * col:
            continue
        k = min(max(s * (col - d) / (d - s * d), 0.0), 1.0)
        if dom * (1.0 - k) > 0:
            out[reg] = dom * (1.0 - k)
    return out


def ely_anchor_values(evs, table, shield=None):
    """Beta v4 anchor B (s13 choice ely_output_anchor; GTAP 12 ch.12 §12.3.6-12.3.9 and §12.4.3: energy output values are
    volumes priced by use class at basic prices): for each region of table {region: (households' share, household price,
    non-household price)}, the S11 domestic electricity sales (TWh) at the households' share times the household price
    and the rest at the non-household price (USD/MWh, before taxes), plus the S11 exports, the gas and heat the industry
    resells at cost (pass_through_value) and any 2022 price-shield payment to suppliers (shield, USD million). Returns
    {region: USD million}."""
    shield = shield or {}
    out = {}
    e = evs[evs['commodity'] == 'ely'].set_index('region')
    for reg, (sh, ph, pn) in table.items():
        if reg not in e.index:
            continue
        x = e.loc[reg]
        pas = float(x['pass_through_value']) if 'pass_through_value' in e.columns and np.isfinite(x['pass_through_value']) else 0.0
        out[reg] = (float(x['domestic_sales']) * (sh * ph + (1.0 - sh) * pn) + float(x['export_value']) + pas
                    + shield.get(reg, 0.0))
    return out


def ely_floor(evs, io, lower_bound=False, net_own=None, s11_min=(), cap_m=None, anchor=None):
    """Beta v4 P1 floor (s11 choice ely_output_value; David 2026-10-26, revised by S16 08:33 UTC): an ely row S11 marks
    ely_target_rule = floor_ninety is held at max(the region's prior ely column total (io_s12 row OUT), its 90 percent rule
    floor ely_floor_value, its exports net of export tax); a row marked floor (the price-based alternative) at max(prior,
    its S11 output value). The domestic sales move by the difference. Returns (evs with output_value and
    domestic_sales_value set, [(region, S11 value, prior, floor, held)] for every floor row).
    lower_bound (s13 choice ely_floor_mode, beta v4 P1 as David's "floor only"): a row is held only where its floor
    (max of the 90 percent floor and net exports) is above the prior; elsewhere held is NaN, the row keeps the S11 value
    in evs and the caller fits it free, holding it at the floor (the 4th element) only if the free fit lands below.
    net_own, s11_min (beta v4 H2, s13 choice ely_hold_net_own_use; the hold only): the prior is taken less net_own[region],
    the own use the cap nets out (ely_netted_own_use), and a region in s11_min (an IEA electricity subsidy) is held at
    least at its S11 value.
    cap_m (beta v4 H2 add-on, s13 choice ely_hold_cap; the hold only): a floor_ninety row held from its prior is held at
    most at its S11 value plus (cap_m - 1) times its domestic electricity sales at the S11 price (domestic sales less the
    gas and heat resold at cost, pass_through_value), so exports and resale are not marked up; never below the floor or
    net exports.
    anchor (beta v4 anchor B, s13 choice ely_output_anchor; the hold only): a floor_ninety row of a listed region is held at
    its measured value (ely_anchor_values) instead, never below the floor or net exports."""
    evs = evs.copy()
    net_own = {} if lower_bound else (net_own or {})
    s11_min = set() if lower_bound else set(s11_min)
    cap_m = None if lower_bound else cap_m
    anchor = {} if lower_bound else (anchor or {})
    if 'ely_target_rule' not in evs.columns:
        return evs, []
    out = io[io['row'] == 'OUT'].set_index('region')['ely'] if 'ely' in io.columns else pd.Series(dtype=float)
    rows = []
    m = (evs['commodity'] == 'ely') & (evs['target'] == 'yes') & evs['ely_target_rule'].isin(['floor', 'floor_ninety'])
    for k in evs.index[m]:
        reg = evs.at[k, 'region']
        v = float(evs.at[k, 'output_value'])
        prior = float(out.get(reg, 0.0))
        prior_h = prior - net_own.get(reg, 0.0)
        smin = v if reg in s11_min else -np.inf
        if evs.at[k, 'ely_target_rule'] == 'floor_ninety':
            fl = float(evs.at[k, 'ely_floor_value'])
            xnet = float(evs.at[k, 'export_value']) - float(evs.at[k, 'export_tax'])
            held = max(prior_h, fl, xnet, smin)
            if cap_m is not None:
                pas = float(evs.at[k, 'pass_through_value']) if 'pass_through_value' in evs.columns else 0.0
                dsell = float(evs.at[k, 'domestic_sales_value']) - (pas if np.isfinite(pas) else 0.0)
                held = max(min(held, v + (cap_m - 1.0) * max(dsell, 0.0)), fl, xnet)
            if reg in anchor:
                held = max(anchor[reg], fl, xnet)
            if lower_bound:
                fl = max(fl, xnet) if np.isfinite(fl) else xnet
        else:
            fl = v
            held = max(v, prior_h)
        if lower_bound and not fl > prior:
            rows.append((reg, v, prior, fl, np.nan))
            continue
        if lower_bound:
            held = fl
        if held != v:
            evs.at[k, 'domestic_sales_value'] = float(evs.at[k, 'domestic_sales_value']) + held - v
            evs.at[k, 'output_value'] = held
        rows.append((reg, v, prior, fl, held))
    return evs, rows


def tiny_energy(evs_t, max_musd=TINY_MAX_MUSD, max_share=TINY_MAX_SHARE, max_export=TINY_MAX_EXPORT, abs_musd=TINY_ABS_MUSD):
    """Beta v4 P38 (s13 choice tiny_energy_activity; not in the GTAP 12 text, a labelled departure): the S11 target rows
    (region, commodity, output value, imports) of energy activities too small for the model to calibrate (CHL coal 3.0 m
    on 1,657 m of imports, KHM coal 2.6 m): below max_musd and max_share of output plus imports, or below abs_musd
    outright (MAR crude 0.92 m with no imports or refinery), with exports of at most max_export. Their output target falls
    to their exports: with none the activity is shut like any zero target (row and column) and the domestic use goes to
    the held imports; the S11 volumes are not changed."""
    v = evs_t['output_value']
    t = evs_t[(v > 0) & (((v < max_musd) & (v < max_share * (v + evs_t['vmsb_imports']))) | (v < abs_musd))
              & (evs_t['export_value'] <= max_export)]
    return [(r.region, r.commodity, float(r.output_value), float(r.vmsb_imports)) for r in t.itertuples()]


MARGINS = ('rdt', 'sea', 'air')
SMEAR = 1.0 / 32.0          # GTAP 12 ch.12 §12.4.1: 31/32 original, 1/32 I-O structure
# s13 choice own_use_share -> the activities whose own-use share (domestic plus imported own good, at agents' prices)
# keeps its prior share of the column in the fit (fit.Column share groups); None: no such group
OWN_USE_RULE = {
    'energy_activities_own_use_share_held_at_prior': ENERGY_TRADE,
    'every_activity_own_use_share_held_at_prior': 'all',
    'cross_entropy_free': None,
}


def own_use_held(sectors, rule):
    """The activities whose own-use cells form a held share group under s13 choice own_use_share."""
    sel = OWN_USE_RULE[rule]
    if sel is None:
        return set()
    return set(sectors) if sel == 'all' else {c for c in sectors if c in sel}


EXTRACTION = ('coa', 'oil', 'gas')
ENERGY_USERS_FALLBACK = 'extraction_columns_energy_cells_held_at_prior_row_shares'


def extraction_ely_groups(sectors, j, groups, prior):
    """Fable QA F-06: the electricity row is not held (no S11 target), so in the energy_users_fallback the electricity
    cells (domestic and imported) of extraction column j are one more held share group: their prior share of the column
    (fit.Column groups). A column with no prior electricity keeps its groups."""
    n = len(sectors)
    if 'ely' not in sectors or sectors[j] == 'ely':
        return groups
    i = sectors.index('ely')
    if prior[2 * i] + prior[2 * i + 1] <= 0:
        return groups
    g = np.zeros(2 * n + 1, int) if groups is None else np.asarray(groups, int).copy()
    g[2 * i] = g[2 * i + 1] = 1 + int(g.max())
    return g


INVESTMENT_CON_SHARE = 'construction_share_of_investment_held_at_the_source_table_prior_share'   # beta v5 C (s13 investment_con_share)


def investment_con_groups(n, idx, prior):
    """Beta v5 C (s13 choice investment_con_share; our rule, not in the GTAP text): the investment column's construction
    cells (domestic and imported, cells ordered dom_0, imp_0, ...) are one held share group, so construction keeps its
    io_s12 (source-table) share of investment and the held imports of capital goods take their room from the other
    domestic goods, not from construction alone. None where there is no construction or no prior construction."""
    if 'con' not in idx:
        return None
    i = idx['con']
    if prior[2 * i] + prior[2 * i + 1] <= 0:
        return None
    g = np.zeros(2 * n, int)
    g[2 * i] = g[2 * i + 1] = 1
    return g


def own_use_groups(n, j):
    """Share groups of activity column j (cells ordered dom_0, imp_0, dom_1, ..., then VA): its own good's
    domestic and imported cells are group 1, every other cell group 0."""
    g = np.zeros(2 * n + 1, int)
    g[2 * j] = g[2 * j + 1] = 1
    return g


# ------------------------------------------------------------------ product taxes by cell (fix list A1)
ENERGY_TAX_ROWS = ('pet', 'coa', 'gas', 'ely')          # energy_tax_s10 commodity = io_s12 row (S10 gas, on B06 there, is the gas row here)
S10_COLUMN = {'oil': 'B06', 'gas': 'B06'}                # io_s12 column -> the S10 IO column whose class it is in
GJ_PER_TOE = 41.868                                      # as S11 (s11_energy/sources.py): GTAP 12 ch.12 prices and taxes per TOE
FILL_ROW = '*'
# the electricity excise falls on every ely buyer but the power sector itself: its own purchases of electricity
# (transmission and distribution buying wholesale power) are the electricity-generation use class, whose NEERS taxes
# are on fuel inputs, so its electricity excise is unknown, i.e. zero (GTAP 12 ch.12 §12.3.3)
ALL_NOT_BUYERS = ('ely',)
INFEASIBLE_RATE = -1.0                                   # a cell power 1 + rate at or below 0 cannot be priced
ADVAL_COLUMNS = ['region', 'column', 'commodity', 'energy_rate', 'neer_subsidy_rate', 'basic_musd', 'specific_usd_per_gj',
                 'neer_subsidy_usd_per_gj', 'price_usd_per_gj', 'source', 'fill']


def s11_unit_factors(ev):
    """{(region, commodity): (basic price USD per GJ, GJ per natural unit, domestic use in natural units)} from
    energy_values_s11 (domestic_price per natural unit, mtoe_per_unit, absorption). The price per TOE is the price over
    the TOE per unit (the S11 units are scaled so Mtoe per million units = TOE per unit), as GTAP 12 ch.12 §12.3.1."""
    out = {}
    for x in ev.itertuples():
        f = float(x.mtoe_per_unit)
        pr = float(x.domestic_price)
        if f > 0 and pr > 0 and np.isfinite(pr):
            out[(x.region, x.commodity)] = (pr / f / GJ_PER_TOE, f * GJ_PER_TOE * 1e6, float(x.absorption))
    return out


def _region_specific(rows, units, region):
    """{(S10 column or ALL, commodity): [net USD m, subsidy USD m, base TJ]} of one source region: the class rates on
    the class's columns, the classes that share a column combined with their tax bases as weights (GTAP 12 ch.12 §12.3.9).
    A barrel base (USA) becomes TJ with the S11 pet factor, the electricity excise base is the S11 domestic use of
    electricity (it is a tax on power sales). A row whose base cannot be converted is returned in 'missing'."""
    acc, missing = {}, []
    for x in rows:
        tax, sub, base, unit = float(x.tax_musd), float(x.subsidy_musd), float(x.base), str(x.base_unit)
        if unit == 'TJ':
            tj = base
        elif unit in ('million_bbl', 'electricity_s11'):
            f = units.get((region, x.commodity))
            tj = (base if unit == 'million_bbl' else (f[2] if f else 0.0)) * (f[1] if f else 0.0) / 1000.0
        else:
            tj = 0.0
        if not tj > 0:
            missing.append(f'{region} {x.commodity} {x.cls} ({unit})')
            continue
        cols = ('ALL',) if x.columns == 'ALL' else tuple(c for c in str(x.columns).split(';') if c)
        for col in cols:
            a = acc.setdefault((col, x.commodity), [0.0, 0.0, 0.0])
            a[0] += tax + sub
            a[1] += sub
            a[2] += tj
    return acc, missing


def energy_ad_valorem(spec, ev, io, sectors):
    """GTAP 12 ch.12 §12.4.4: the S10 specific energy-tax rates (energy_tax_s10.csv) as ad valorem rates on the S11
    basic price of the commodity in the region, on every io_s12 column of the class.

    rate = specific (USD per GJ) / S11 domestic basic price (USD per GJ), the same on domestic and imported purchases.
    A region without source data takes the trade-weighted mean of its S10 proxies' specific rates (USD per GJ, member
    by member where the member taxes that cell; GTAP 12 ch.12 §12.3.10 copies the proxy's rates) and converts them with
    its own price. io_s12 oil and gas columns take the S10 B06 class. Returns (DataFrame ADVAL_COLUMNS, notes list).
    neer_subsidy_rate is the NEERS-subsidy part of energy_rate (<= 0; fix-round B15, S13 fuel_subsidy_neer_overlap)."""
    units = s11_unit_factors(ev)
    cols_all = list(sectors) + ['p', 'g', 'i']
    spec = spec.rename(columns={'class': 'cls'})
    for c in ('tax_musd', 'subsidy_musd', 'base'):
        spec[c] = pd.to_numeric(spec[c], errors='coerce').fillna(0.0)
    src = spec[spec['cls'] != FILL_ROW]
    sales = (pd.to_numeric(spec['fuel_sales_tax_musd'], errors='coerce').fillna(0.0) if 'fuel_sales_tax_musd' in spec.columns
             else pd.Series(0.0, index=spec.index))
    per, per_proxy, label, notes = {}, {}, {}, []
    for reg, g in src.groupby('region'):
        acc, miss = _region_specific(list(g.itertuples()), units, reg)
        notes += [f'no S11 base to convert: {m}' for m in miss]
        per[reg] = {k: (v[0] * 1000.0 / v[2], v[1] * 1000.0 / v[2]) for k, v in acc.items()}
        # S10 fuel_sales_taxes are a country's own sales tax, not an excise rate a proxy region copies (§12.3.10)
        gx = g.assign(tax_musd=g['tax_musd'] - sales.loc[g.index])
        acc_x, _m = _region_specific(list(gx.itertuples()), units, reg)
        per_proxy[reg] = {k: (v[0] * 1000.0 / v[2], v[1] * 1000.0 / v[2]) for k, v in acc_x.items()}
        label[reg] = (str(g['source'].iloc[0]), '')
    for x in spec[spec['cls'] == FILL_ROW].itertuples():
        prox = [(m, float(w)) for m, w in (p.split(':') for p in str(x.proxies).split(';') if p and p != 'nan')]
        num, den = {}, {}
        for m, w in prox:
            for k, (t, s) in per_proxy.get(m, {}).items():
                n = num.setdefault(k, [0.0, 0.0])
                n[0] += w * t
                n[1] += w * s
                den[k] = den.get(k, 0.0) + w
        per[x.region] = {k: (n[0] / den[k], n[1] / den[k]) for k, n in num.items() if den[k] > 0}
        label[x.region] = ('fill', str(x.fill) if str(x.fill) != 'nan' else '')
    io = io[io['region'].isin(per)]
    rows = []
    for reg, r in io.groupby('region'):
        r = r.set_index('row')
        rates = per.get(reg, {})
        for c in ENERGY_TAX_ROWS:
            u = units.get((reg, c))
            for col in cols_all:
                k = rates.get((S10_COLUMN.get(col, col), c))
                if k is None and not (c == 'ely' and col in ALL_NOT_BUYERS):
                    k = rates.get(('ALL', c))
                if k is None:
                    continue
                if u is None:
                    notes.append(f'{reg} {c}: no S11 basic price; energy tax on {col} left at zero')
                    continue
                b = sum(float(r.loc[f'{kind}_{c}', col]) for kind in ('dom', 'imp') if f'{kind}_{c}' in r.index)
                t, ts = k[0] / u[0], k[1] / u[0]
                if t <= INFEASIBLE_RATE:
                    # a net subsidy per GJ at or above the basic price per GJ gives no positive purchasers' price: the
                    # rate is treated as unknown, i.e. zero (GTAP 12 ch.12 §12.3.3), and named (S13-Renergyrates)
                    notes.append(f'{reg} {c} {col}: rate {t:.3f} ({k[0]:.3f} USD/GJ on a basic price of {u[0]:.3f} USD/GJ, basic {b:.3f} USD m) '
                                 'gives no positive purchasers\' price: set to zero (unknown rate, ch.12 §12.3.3)')
                    t = ts = 0.0
                rows.append([reg, col, c, t, ts, b, k[0], k[1], u[0], label[reg][0], label[reg][1]])
    return pd.DataFrame(rows, columns=ADVAL_COLUMNS), sorted(set(notes))


ENERGY_TAX_REVENUE = 'source_revenue_on_the_s11_valued_rows_rates_held_in_the_fit'
ENERGY_REVENUE_BOUND = 4.0      # a region's energy-tax rates on one row move at most this factor (or its inverse)


def scale_energy_rates_to_source(te, spec, ev, io, sectors, bound=ENERGY_REVENUE_BOUND, targets=ENERGY_TARGETS):
    """Fable QA F-04 (s13 choice energy_tax_revenue): the ad valorem energy-tax rates of a source region, one factor per
    energy row, so that the revenue they give on the row's expected fitted purchases equals the S10 source revenue
    (NEERS or EIA, net of the NEERS subsidies). GTAP 12 ch.8 Appendix A scales the expected tax revenue on the I-O flows
    to the revenue government reports; ch.17A items 4-5 then hold the rates in the FIT. The fit holds the coa, gas and pet
    rows at their S11 values (domestic sales value plus VMSB), so a class column's expected purchase is its io_s12 cell
    times the row's S11 value over its io_s12 total; electricity is not held, so its io_s12 cells are the base. A fill
    region (proxies) has no source revenue and keeps its rates. The factor stays within [1 / bound, bound]; a row whose
    implied revenue is zero or of the other sign keeps its rates (noted). targets (beta v4 P34): the rows the fit holds,
    output_targets of the s13 choice energy_targets; with P1 on, ely is held where S11 sets its value (target yes), so its
    expected purchases are the S11 value too (BFA ely: 313 m against 88.6 m of io_s12 cells). Returns (te with energy_rate,
    neer_subsidy_rate scaled and revenue_scale, report DataFrame, notes)."""
    te = te.copy()
    te['revenue_scale'] = 1.0
    cols_all = list(sectors) + ['p', 'g', 'i']
    s = spec[spec['class'] != FILL_ROW]
    src = (pd.to_numeric(s['tax_musd'], errors='coerce').fillna(0.0) + pd.to_numeric(s['subsidy_musd'], errors='coerce').fillna(0.0)
           ).groupby([s['region'], s['commodity']]).sum()
    evx = ev.set_index(['region', 'commodity'])
    rows, notes = [], []
    for (reg, c), g in te[te['source'] != 'fill'].groupby(['region', 'commodity']):
        if (reg, c) not in src.index:
            continue
        target = float(src.loc[(reg, c)])
        kappa = 1.0
        if c in targets and (reg, c) in evx.index and (c != 'ely' or str(evx.loc[(reg, c)].get('target', '')) == 'yes'):
            r = io[(io['region'] == reg) & io['row'].isin([f'dom_{c}', f'imp_{c}'])]
            tot = float(r[cols_all].to_numpy(float).sum())
            x = evx.loc[(reg, c)]
            held = float(pd.to_numeric(x.get('domestic_sales_value'), errors='coerce') or 0.0) + float(pd.to_numeric(x.get('vmsb_imports'), errors='coerce') or 0.0)
            if tot > 0 and held > 0:
                kappa = held / tot
        implied = float((g['energy_rate'] * g['basic_musd']).sum()) * kappa
        k, why = 1.0, ''
        if target == 0 or implied == 0 or np.sign(target) != np.sign(implied):
            why = 'implied revenue zero or of the other sign: rates kept'
        else:
            k = target / implied
            if k > bound or k < 1.0 / bound:
                why = f'factor {k:.3f} outside [1/{bound:g}, {bound:g}]: set to the bound'
                k = float(np.clip(k, 1.0 / bound, bound))
        # a scaled net subsidy at or below -100% gives no positive purchasers' price: keep the largest feasible factor
        lo = g['energy_rate'].min()
        if lo < 0 and k * lo <= INFEASIBLE_RATE:
            k = 0.99 * INFEASIBLE_RATE / lo
            why = (why + '; ' if why else '') + f'factor capped at {k:.3f} (a cell power would reach zero)'
        te.loc[g.index, 'energy_rate'] = g['energy_rate'] * k
        te.loc[g.index, 'neer_subsidy_rate'] = g['neer_subsidy_rate'] * k
        te.loc[g.index, 'revenue_scale'] = k
        rows.append(dict(region=reg, commodity=c, source_musd=target, implied_io12_musd=float((g['energy_rate'] * g['basic_musd']).sum()),
                         row_value_factor=kappa, implied_expected_musd=implied, scale=k, expected_after_musd=implied * k, note=why))
        if why:
            notes.append(f'{reg} {c}: {why}')
    return te, pd.DataFrame(rows, columns=['region', 'commodity', 'source_musd', 'implied_io12_musd', 'row_value_factor', 'implied_expected_musd',
                                           'scale', 'expected_after_musd', 'note']), notes


def energy_rates_of(tls_energy, region, cols_all):
    """{(row, io_s12 column): energy-tax rate} for one region from the energy_ad_valorem table (energy rows only)."""
    t = tls_energy[(tls_energy['region'] == region) & (tls_energy['commodity'] != '_rest')]
    by = {(r.commodity, r.column): float(r.energy_rate) for r in t.itertuples()}
    out = {}
    for col in cols_all:
        for c in ENERGY_TAX_ROWS:
            k = (c, col) if (c, col) in by else (c, S10_COLUMN.get(col, col))
            if k in by:
                out[(c, col)] = by[k]
    return out


SUBSIDY_COLUMNS_FD = ('p', 'g')       # Chepeliev et al. (2018) §3.1: firms (tfd, tfm), government (tgd, tgm), private (tpd, tpm)
SUBSIDY_COMMODITIES = ('coa', 'gas', 'pet', 'ely')      # S11 IEA products: Coal, Gas, Oil -> pet, Electricity
# round 3 (final QA 2 item 2; s13 choice fuel_subsidy_users): the IEA price gap is measured on final consumption and on
# non-energy users, so the energy industries' purchases of energy (own use on the diagonal, transformation inputs to power
# and refining, and energy-industry own use) carry no IEA consumption subsidy
SUBSIDY_EXCLUDED_ACTIVITIES = ENERGY_TRADE
FUEL_SUBSIDY_NON_ENERGY = 'final_consumption_and_non_energy_users_energy_industry_own_use_and_transformation_excluded_money_held'


def book_pse_input(basic, tau_cell, tau_tls_cell, idx, jc, pse_in, items, remainder_rows=None, net=None):
    """S10 PSE input support on the crp column jc, in place (fix round wG, QA round 2 P7; GTAP 12 ch.11A Figure 11.1:
    B1 variable input use is support to inputs). items: {row good: USD million}, the PSE B1 sub-items whose input is
    known (config/s13/pse_input_items_2022.csv). Their sum is at most pse_in (scaled down pro rata otherwise).
      - The remainder R = pse_in - sum(items) is one rate R / B on every crp purchase at its io_s12 basic value B (the
        rule before this round, pse_input_rows).
      - Each listed item F goes on its row's crp cells (domestic and imported pro rata): the purchasers' value of the
        cell is kept, as the farmer pays it, and the basic value rises by F (the subsidy is paid to the supplier, as
        GTAP books a consumption subsidy, ch.3 §3.2.4): basic x r, r = (b + F) / b, the cell power falls by 1 / r and its
        other product taxes keep their amount, so the cell's support rate is -(R b / B + F) / (b + F) on the new basic.
    An item whose row has no crp purchase joins the remainder.
    remainder_rows (round-3 QA item 9; config/s13/pse_input_remainder_2022.csv): the rows of the PSE B1 items the OECD
    names for the region whose amounts are not listed (India: electricity and irrigation water). Then the remainder goes
    on those rows instead of every input, split by the crp column's basic purchases of them (one support rate on the
    rows) and booked as an item (purchasers' value kept); with no purchase on any of them it stays on every input.
    net ({row good: USD million}; s13 choice pse_iea_overlap, round-3 final QA2 item 6): support another source books on
    the crp cell already (the farm part of the IEA electricity subsidy, B15); it is taken off the remainder's part on
    that row (never below 0) and not booked twice (netted_musd).
    Returns {row good: dict(value_musd, rate, basic_before, basic_after, part, netted_musd)} for the booked items (part:
    listed, remainder, or listed+remainder)."""
    out = {}
    tot = sum(max(v, 0.0) for v in items.values())
    k = min(1.0, pse_in / tot) if tot > 0 else 0.0
    book = {}
    for c, v in items.items():
        if c not in idx or v <= 0:
            continue
        b = basic['dom'][idx[c], jc] + basic['imp'][idx[c], jc]
        if b > 0:
            book[c] = (v * k, b)
    part = {c: 'listed' for c in book}
    netted = {}
    rest = pse_in - sum(f for f, _ in book.values())
    if remainder_rows and rest > 0:
        rb = {c: basic['dom'][idx[c], jc] + basic['imp'][idx[c], jc] for c in remainder_rows if c in idx}
        rb = {c: b for c, b in rb.items() if b > 0}
        tb = sum(rb.values())
        if tb > 0:
            for c, b in rb.items():
                f0 = book[c][0] if c in book else 0.0
                share = rest * b / tb
                d = min(max(float((net or {}).get(c, 0.0)), 0.0), share)
                if d > 0:
                    netted[c] = d
                book[c] = (f0 + share - d, b)
                part[c] = 'listed+remainder' if c in part else 'remainder'
            rest = 0.0
    bc = basic['dom'][:, jc].sum() + basic['imp'][:, jc].sum()
    if bc > 0:
        tau_cell[:, jc] -= rest / bc
    for c, (f, b) in book.items():
        i = idx[c]
        r = (b + f) / b
        tau_cell[i, jc] /= r
        tau_tls_cell[i, jc] = 1.0 + (tau_tls_cell[i, jc] - 1.0) / r
        for kind in ('dom', 'imp'):
            basic[kind][i, jc] *= r
        out[c] = dict(value_musd=float(f), rate=float(tau_cell[i, jc] - tau_tls_cell[i, jc]), basic_before=float(b), basic_after=float(b + f),
                      part=part[c], netted_musd=float(netted.get(c, 0.0)))
    return out


def subsidy_columns(cols_all, sectors, exclude_energy=False):
    """Mask of the columns that carry a fuel subsidy: every activity, households and government (not investment);
    with exclude_energy (s13 choice fuel_subsidy_users) not the energy activities (SUBSIDY_EXCLUDED_ACTIVITIES)."""
    return np.array([(j < len(sectors) or c in SUBSIDY_COLUMNS_FD) and not (exclude_energy and c in SUBSIDY_EXCLUDED_ACTIVITIES)
                     for j, c in enumerate(cols_all)])


ELY_SUB_RHO_MAX = 0.5   # beta v5.5 (s13 choice ely_subsidy_region_hold): ely subsidy rate cap in the IEA ely-subsidy regions held at tariff level
RHO_MAX = 0.8      # fix round S16 (Fable QA C-02): a fuel subsidy rate at most 80% of the basic value


def book_fuel_subsidies(pv, tau_cell, tau_tls_cell, idx, cols_all, sectors, tgt, X, M, subsidies, hold_money=False, exclude_energy=False,
                        rho_max=None, rho_max_good=None):
    """Fix-round B15 (GTAP's booking; Chepeliev, McDougall and van der Mensbrugghe 2018 §3.1-3.2), in place.

    subsidies: {good: USD million} to book. The tax-paid (purchasers') value of every prior cell is kept; the basic
    value rises and the tax falls by the same amount. The subsidy is one ad valorem rate rho on the new basic value of
    the good's purchases by firms, households and government, domestic and imported alike, so it falls on each buyer
    in proportion to its purchases: the cell power becomes tau (1 - rho), i.e. the cell's other taxes keep their amount
    and the subsidy rate -rho is added (rate_new = (1 - rho) rate_old - rho on the new basic).
    rho = S / B. For a good whose domestic sales and imports S13 holds (an S11 target), B is the held basic purchases
    (target less exports, plus imports), which the subsidised columns buy in full once government and investment
    energy is removed (ch.17A footnote 4), so the fitted table books exactly S. Otherwise (electricity) B is the prior
    basic value after the booking, B0 + S, so the prior books exactly S; with hold_money (s13 choice
    electricity_subsidy_money) such a good is marked money_held and hold_product_taxes resets rho after each fit pass so
    that the fitted table books exactly S as well (else the fit moves it with the purchases).
    exclude_energy (s13 choice fuel_subsidy_users, round 3 final QA 2 item 2): the energy activities' purchases are left
    out (subsidy_columns), so the held row is no longer the subsidised base: every good is booked on its prior base
    (B0 + S) and its money held through the fit (money_held). A good that only energy activities buy is booked on every
    buyer as before (basis says so).
    rho_max (s13 choice fuel_subsidy_rate_cap, fix round S16, Fable QA C-02: IRN gas power 0.039, TKM 0.029): the rate is at
    most rho_max; the money above it is not booked (capped_musd) and the booked amount is the subsidy_musd the checks use.
    rho_max_good (beta v5.5, s13 choice ely_subsidy_region_hold): {good: rate} a tighter cap for one good in this region
    (electricity in the IEA electricity-subsidy regions held at tariff level), applied as for rho_max.
    Returns {good: dict(rho, basis, booked_prior, basic_prior_before, basic_prior_after, status, mask)}."""
    out = {}
    for c, S in sorted(subsidies.items()):
        if c not in idx or not np.isfinite(S) or S <= 0:
            continue
        i = idx[c]
        t_old = tau_cell[i, :].copy()
        mask = subsidy_columns(cols_all, sectors, exclude_energy)
        b0 = sum(np.where(mask, pv[k][i, :], 0.0) for k in ('dom', 'imp')) / t_old
        excl = exclude_energy
        if exclude_energy and b0.sum() <= 0:
            mask, excl = subsidy_columns(cols_all, sectors), False
            b0 = sum(np.where(mask, pv[k][i, :], 0.0) for k in ('dom', 'imp')) / t_old
        B0 = float(b0.sum())
        prior_base = not (not excl and not exclude_energy and np.isfinite(tgt[i]))     # B = B0 + S (else the held purchases)
        if excl:
            B, basis = B0 + S, 'prior basic purchases of final and non-energy users after the booking (money held)'
        elif exclude_energy:
            B, basis = B0 + S, 'no final or non-energy buyer: every buyer, prior basic purchases after the booking (money held)'
        elif np.isfinite(tgt[i]):
            B, basis = max(tgt[i] - X[i], 0.0) + M[i], 'held basic purchases (target - exports + imports)'
        else:
            B, basis = B0 + S, 'prior basic purchases after the booking'
        if B <= 0 or B0 <= 0:
            out[c] = dict(rho=0.0, basis=basis, booked_prior=0.0, basic_prior_before=B0, basic_prior_after=B0, status='no_purchases', mask=mask)
            continue
        rho = S / B
        S_req, capped = S, 0.0
        rm = min([x for x in (rho_max, (rho_max_good or {}).get(c)) if x is not None], default=None)
        if rm is not None and rho > rm:
            # held base: S' = rm B; prior base (B = B0 + S): S' / (B0 + S') = rm
            S = rm * B0 / (1.0 - rm) if prior_base else rm * B
            capped, rho = S_req - S, rm
        if rho >= 1.0:
            out[c] = dict(rho=rho, basis=basis, booked_prior=0.0, basic_prior_before=B0, basic_prior_after=B0, status='rho_not_below_1', mask=mask)
            continue
        tau_cell[i, mask] *= (1.0 - rho)
        tau_tls_cell[i, mask] *= (1.0 - rho)
        b1 = sum(np.where(mask, pv[k][i, :], 0.0) for k in ('dom', 'imp')) / tau_cell[i, :]
        out[c] = dict(rho=rho, basis=basis, booked_prior=float(rho * b1.sum()), basic_prior_before=B0, basic_prior_after=float(b1.sum()),
                      status='booked', subsidy_musd=float(S), capped_musd=float(capped), rho_max=rm, money_held=bool((hold_money and not np.isfinite(tgt[i])) or exclude_energy), mask=mask)
    return out


GENERAL_RATE_RULES = ('held', 'cap', 'io_rate')
TAX_RATE_RULE = {          # s13 choice tax_rates -> place_column_taxes rule
    'energy_rows_at_gtap_ad_valorem_rates_held_general_rate_column_remainder_not_below_min_io_rate_0': 'held',
    'energy_rows_at_ad_valorem_rates_capped_at_column_tls_column_total_fixed': 'cap',
    'energy_rows_at_ad_valorem_rates_plus_io_column_rate_on_every_row': 'io_rate',
}


PT_EXCISE_ROW, PT_EXCISE_COLUMNS = 'fbt', ('p',)      # alcohol and tobacco excise: households' fbt purchases
EXCISE_AT_SOURCE = 'fbt_excise_at_source_revenue_vat_seed_scaled_to_column_general_part_less_excise'   # beta v4 G16
RAS_ITER, RAS_TOL = 200, 1e-10


def product_tax_layers(pattern, layers, control, sectors):
    """{region: dict(V, levelled, vat_musd, excise_musd, groups)} from the S10 product_tax files (s13 choice
    non_energy_rates; QA round 2 P1). V is the n x J VAT weight of every (commodity, column): households, government
    and investment take their agent rows, an activity whose own output has government weight 0 (exempt or non-market) the
    firm_exempt row, every other activity the firm row (an indicator; deductible VAT). levelled marks the columns whose
    weights are VAT rates (levelled to the GRS VAT); groups: [(row indices, share)] of the Eurostat control."""
    idx = {c: i for i, c in enumerate(sectors)}
    cols_all = list(sectors) + list(FD)
    n, J = len(sectors), len(cols_all)
    out = {}
    pw = {}
    for x in pattern.itertuples():
        if x.commodity in idx:
            pw.setdefault(x.region, {}).setdefault(x.agent, np.zeros(n))[idx[x.commodity]] = float(x.vat_weight)
    lay = {x.region: x for x in layers.itertuples()}
    grp = {}
    for x in control.itertuples():
        rows = [idx[c] for c in str(x.commodities).split() if c in idx]
        if rows:
            grp.setdefault(x.region, []).append((rows, float(x.share)))
    for reg, a in pw.items():
        V = np.zeros((n, J))
        levelled = np.zeros(J, bool)
        for j, col in enumerate(cols_all):
            if col in FD:
                agent = col
            else:
                agent = 'firm_exempt' if a['g'][idx[col]] == 0.0 else 'firm'
            V[:, j] = a[agent]
            levelled[j] = agent != 'firm'
        L = lay.get(reg)

        def num(v):
            try:
                v = float(v)
            except (TypeError, ValueError):
                return None
            return v if v == v else None
        out[reg] = dict(V=V, levelled=levelled, vat_musd=num(L.vat_musd) if L is not None else None,
                        excise_musd=num(L.excise_musd) if L is not None else None,
                        energy_excise_musd=num(getattr(L, 'energy_excise_musd', None)) if L is not None else None, groups=grp.get(reg, []))
    return out


def pattern_rates(b, G, E_pos, lay, sectors, cols_all, excise_fixed=False):
    """QA round 2 P1: the general part of each column's tax on its commodities.

    b: n x J basic purchases; G: the general part of each column's tax (g x B, from place_column_taxes); E_pos: the
    region's positive energy excise on the io_s12 flows, used where S10 has no source energy excise.
    Seed s (n x J): the VAT weights V, on the levelled columns times c_V = GRS VAT / sum(V b) over them (the VAT
    revenue), plus on households' fbt x = max(GRS T_5121 - energy excise, 0) over households' fbt purchases (the
    alcohol and tobacco excise; the energy excise, S10's source revenue (NEERS, EIA) or else E_pos, is on the energy
    rows already). Each column with G > 0 and a positive seed is scaled to G by k_j; a government, investment or
    exempt-activity column is scaled at most as far as households (k_j <= k_p: no agent pays more VAT on a good than
    households), and the rest of its G goes on all its purchases at one rate u_j (product taxes the layers do not
    place). With a Eurostat control the scaled seed is RASed on the non-energy rows (row factor a by commodity group)
    towards the control shares of their total, the columns re-scaled after each row step, so every column holds G
    exactly. rate = s a k + u. excise_fixed (beta v4 G16, s13 choice excise_at_source; GTAP 12 ch.8 App. A.4 item 1:
    rates and bases from the tax law, then scaled): the households' fbt excise x stays at its source revenue and only the
    VAT seed is scaled, to G less the column's excise (the excise is cut to G only where it alone exceeds G); the RAS
    row factors act on the VAT part, towards each group's control share less its excise. Returns (rate n x J, mask of
    the columns placed, info dict)."""
    n, J = b.shape
    V = lay['V']
    s = V.copy()
    lev = lay['levelled']
    den = float((V[:, lev] * b[:, lev]).sum())
    cV = lay['vat_musd'] / den if lay.get('vat_musd') and den > 0 else 1.0
    s[:, lev] *= cV
    idx = {c: i for i, c in enumerate(sectors)}
    X, x = 0.0, 0.0
    sx = np.zeros((n, J))
    e_ref = lay.get('energy_excise_musd')
    e_ref = E_pos if e_ref is None else e_ref
    if lay.get('excise_musd') is not None and PT_EXCISE_ROW in idx:
        X = max(lay['excise_musd'] - e_ref, 0.0)
        jj = [cols_all.index(c) for c in PT_EXCISE_COLUMNS if c in cols_all]
        base = float(sum(b[idx[PT_EXCISE_ROW], j] for j in jj))
        if X > 0 and base > 0:
            x = X / base
            for j in jj:
                (sx if excise_fixed else s)[idx[PT_EXCISE_ROW], j] += x
        else:
            X = 0.0
    B = b.sum(axis=0)
    jp = cols_all.index('p') if 'p' in cols_all else None
    capc = lev.copy()
    if jp is not None:
        capc[jp] = False
    XB = (sx * b).sum(axis=0)
    xs = np.where(XB > G, np.where(XB > 0, np.maximum(G, 0.0) / np.where(XB > 0, XB, 1.0), 0.0), 1.0)   # excise above G: cut to G
    Gv = np.maximum(G - xs * XB, 0.0)
    on = (G > 0) & (((s + sx) * b).sum(axis=0) > 0)
    a = np.ones(n)

    def scale():
        sb = (s * b * a[:, None]).sum(axis=0)
        k = np.where(on, Gv / np.where(sb > 0, sb, 1.0), 0.0)
        if jp is not None and on[jp]:
            k = np.where(capc & on, np.minimum(k, k[jp]), k)
        u = np.where(on, (Gv - k * sb) / np.where(B > 0, B, 1.0), 0.0)
        return k, u
    k, u = scale()
    Tx = sx * b * xs[None, :]
    Tx[:, ~on] = 0.0
    groups = [(rows, sh) for rows, sh in lay.get('groups', [])]
    ne = np.zeros(n, bool)
    for rows, _ in groups:
        ne[rows] = True
    gap, it = 0.0, 0
    if groups and on.any():
        for it in range(1, RAS_ITER + 1):
            T = s * b * a[:, None] * k[None, :]
            T[:, ~on] = 0.0
            cur = [float(T[rows, :].sum()) for rows, _ in groups]
            fix = [float(Tx[rows, :].sum()) for rows, _ in groups]      # the excise held at source (0 unless excise_fixed)
            live = [g for g, c in enumerate(cur) if c > 0]
            N = sum(cur[g] + fix[g] for g in live)
            tot = sum(groups[g][1] for g in live)
            if N <= 0 or tot <= 0:
                break
            gap = 0.0
            for g in live:
                rows, sh = groups[g]
                f = max(sh / tot * N - fix[g], 0.0) / cur[g]
                gap = max(gap, abs(f - 1.0))
                a[rows] *= f
            k, u = scale()
            if gap < RAS_TOL:
                break
    rate = s * a[:, None] * k[None, :] + sx * xs[None, :] + u[None, :]
    rate[:, ~on] = 0.0
    capped = [cols_all[j] for j in np.where(on & (u > 1e-12))[0]]
    return rate, on, dict(c_vat=cV, excise_musd=X, excise_rate=x, energy_excise_musd=e_ref, columns=int(on.sum()),
                          capped_columns=' '.join(capped), uniform_musd=float((u * B)[on].sum()), ras_iter=it, ras_gap=gap,
                          controlled=bool(groups))


def place_column_taxes(basic, tls, cols_all, sectors, energy, rule='held', layers=None, excise_fixed=False):
    """tax_rates (fix list A1): the net product-tax rate of every cell, the same on dom and imp purchases.

    The energy rows of a column carry their ad valorem energy-tax rates (energy: {(row, column): rate}; GTAP 12 ch.12
    §12.4.4) on top of the column's general rate g (the VAT that is not deducted and the other product taxes, which fall
    on energy as on any purchase); every other row carries g. E is the energy part on the io_s12 flows, B the column's
    basic purchases, g0 = TLS / B the io_s12 column rate.
    - 'held' (default; GTAP 12 ch.17A items 4-5, FIT holds rates): the energy rates are held as GTAP converts them.
      io_s12 has one TLS per column, and that TLS already contains the energy excise on the column's own energy
      purchases, so the IO's own rate on the other purchases is g = (TLS - E) / B. Where that would be below
      min(g0, 0), i.e. the excise is larger than the IO column's tax, g = min(g0, 0): a column whose IO rate is
      positive gets no negative general rate and a net-subsidised column keeps its IO rate. There the column total
      moves (to E, or TLS + E) instead of the energy rates; elsewhere it is unchanged at the prior.
    - 'cap' (the pre-w12 rule, not GTAP): the energy part is scaled down to at most max(TLS, 0) and g = (TLS - E) / B,
      so every column keeps its TLS.
    - 'io_rate': g = g0 on every row, energy rows g0 plus their rate; the column total rises by E (counts the excise
      that is inside TLS a second time; for comparison).
    A column with no purchases has rate 0. With no energy rates every rule gives the one rate per column of tls_split.
    layers (s13 choice non_energy_rates; QA round 2 P1): one region's product_tax_layers entry, or None. With it, the
    general part g B of every column with g > 0 is placed on the commodities by pattern_rates (VAT and excise layers,
    the Eurostat product control) instead of one rate g on every row; the column total is the same.
    Returns (rate n x J, dict(capped=[(column, factor)], floored=[(column, g_net, g)], moved=[(column, tls, new total)],
    pattern=pattern_rates info or None, general=the general (non-energy-rate) part of every cell's rate, n x J)).
    """
    if rule not in GENERAL_RATE_RULES:
        raise ValueError(f'place_column_taxes rule {rule!r}')
    idx = {c: i for i, c in enumerate(sectors)}
    b = basic['dom'] + basic['imp']
    n, J = b.shape
    rate = np.zeros((n, J))
    emat = np.zeros((n, J))
    gen = np.zeros(J)
    E_pos = 0.0
    capped, floored, moved = [], [], []
    for j, col in enumerate(cols_all):
        bj = b[:, j]
        bsum = bj.sum()
        if bsum <= 0:
            continue
        e = np.zeros(n)
        for c in ENERGY_TAX_ROWS:
            if (c, col) in energy and c in idx:
                e[idx[c]] = energy[(c, col)]
        E = float((e * bj).sum())
        g0 = tls[j] / bsum
        if rule == 'cap':
            if E > 1e-9 and E > max(tls[j], 0.0):
                k = max(tls[j], 0.0) / E
                e *= k
                E *= k
                capped.append((col, k))
            g = (tls[j] - E) / bsum
        elif rule == 'io_rate':
            g = g0
        else:
            g = (tls[j] - E) / bsum
            lo = min(g0, 0.0)
            if g < lo:
                floored.append((col, g, lo))
                g = lo
        rate[:, j] = e + g
        emat[:, j] = e
        gen[j] = g * bsum
        E_pos += max(float((e * bj).sum()), 0.0)
        total = float((rate[:, j] * bj).sum())
        if abs(total - tls[j]) > 1e-9 * max(1.0, abs(tls[j])):
            moved.append((col, float(tls[j]), total))
    pinfo = None
    if layers is not None:
        prate, on, pinfo = pattern_rates(b, gen, E_pos, layers, sectors, cols_all, excise_fixed)
        for j in np.where(on)[0]:
            g = gen[j] / b[:, j].sum()
            rate[:, j] += prate[:, j] - g          # the general part on the commodities; the energy rates stay
    return rate, dict(capped=capped, floored=floored, moved=moved, pattern=pinfo, general=rate - emat)


# ------------------------------------------------------------------ trade
def b06_split(io, sectors):
    """Share of oil in the host's household purchases of domestic oil + gas (io_s12 p column)."""
    p = io[io['row'].isin(['dom_oil', 'dom_gas'])].pivot(index='region', columns='row', values='p').fillna(0.0)
    tot = p['dom_oil'] + p['dom_gas']
    return (p['dom_oil'] / tot.where(tot > 0)).rename('oil_share')


def assemble_trade(goods_x, goods_m, en_x, en_m, svc, travel, vst, oil_share, target_out):
    """Region x commodity export and import vectors. Returns (trade, bilateral travel rows used, dropped travel rows).

    goods_x/goods_m: S10 vfob/vmsb without the energy sectors; en_x/en_m: S11 energy; svc: S09 services VXSB;
    travel: S09 travel file (goods, ely, B06, rle, wat, hhe); vst: S11 VST by margin."""
    tr = travel.rename(columns={'commodity': 'sector', 'host': 'exporter', 'visitor': 'importer', 'musd': 'v'})
    b06 = tr[tr['sector'] == 'B06']
    sh = b06['exporter'].map(oil_share)
    # a host with no household oil or gas purchases splits B06 travel by its S11 output targets
    alt = b06['exporter'].map(lambda r: _tshare(target_out, r))
    sh = sh.fillna(alt).fillna(0.5)
    tr = pd.concat([tr[tr['sector'] != 'B06'],
                    b06.assign(sector='oil', v=b06['v'] * sh), b06.assign(sector='gas', v=b06['v'] * (1 - sh))], ignore_index=True)
    # travel on an energy commodity comes out of the domestic sales that S11 leaves (output target less S11
    # exports); a host with no such room (S11 output zero, or all of it exported) cannot supply it, and travel
    # beyond the room is scaled down to it. What is removed is dropped from both host exports and visitor imports.
    enx = en_x.groupby(['exporter', 'sector'])['vxsb_musd'].sum()
    tsum = tr.groupby(['exporter', 'sector'])['v'].sum()

    def keep(x):
        if x['sector'] not in ENERGY_TRADE:       # ely has a target only with s13 choice energy_targets (beta v4 P1)
            return 1.0
        t = target_out.get((x['exporter'], x['sector']), np.nan)
        if not np.isfinite(t):
            return 1.0
        room = max(t - enx.get((x['exporter'], x['sector']), 0.0), 0.0)
        tot = tsum.get((x['exporter'], x['sector']), 0.0)
        return 1.0 if tot <= room else (room / tot if tot > 0 else 0.0)
    k = tr.apply(keep, axis=1) if len(tr) else pd.Series(dtype=float)
    dropped = tr[(k < 1.0) & (tr['v'] > 0)].assign(v=lambda d: d['v'] * (1.0 - k[d.index]))
    tr = tr.assign(v=tr['v'] * k)
    tr = tr[tr['v'] > 0]
    rows = []
    rows.append(goods_x[['exporter', 'sector', 'vxsb_musd', 'vfob_musd']].rename(columns={'exporter': 'region', 'vxsb_musd': 'X', 'vfob_musd': 'XFOB'}).assign(src='goods_s10'))
    rows.append(en_x[['exporter', 'sector', 'vxsb_musd', 'vfob_musd']].rename(columns={'exporter': 'region', 'vxsb_musd': 'X', 'vfob_musd': 'XFOB'}).assign(src='energy_s11'))
    rows.append(svc[['exporter', 'sector', 'vxsb_musd']].rename(columns={'exporter': 'region', 'vxsb_musd': 'X'}).assign(XFOB=svc['vxsb_musd'].values, src='services_s09'))
    rows.append(tr[['exporter', 'sector', 'v']].rename(columns={'exporter': 'region', 'v': 'X'}).assign(XFOB=tr['v'].values, src='travel_s09'))
    X = pd.concat(rows, ignore_index=True)
    rows = []
    rows.append(goods_m[['importer', 'sector', 'vcif_musd', 'vmsb_musd']].rename(columns={'importer': 'region', 'vcif_musd': 'MCIF', 'vmsb_musd': 'M'}).assign(src='goods_s10'))
    rows.append(en_m[['importer', 'sector', 'vcif_musd', 'vmsb_musd']].rename(columns={'importer': 'region', 'vcif_musd': 'MCIF', 'vmsb_musd': 'M'}).assign(src='energy_s11'))
    rows.append(svc[['importer', 'sector', 'vxsb_musd']].rename(columns={'importer': 'region', 'vxsb_musd': 'M'}).assign(MCIF=svc['vxsb_musd'].values, src='services_s09'))
    rows.append(tr[['importer', 'sector', 'v']].rename(columns={'importer': 'region', 'v': 'M'}).assign(MCIF=tr['v'].values, src='travel_s09'))
    M = pd.concat(rows, ignore_index=True)
    xs = X.pivot_table(index=['region', 'sector'], columns='src', values='X', aggfunc='sum', fill_value=0.0)
    ms = M.pivot_table(index=['region', 'sector'], columns='src', values='M', aggfunc='sum', fill_value=0.0)
    t = pd.concat([
        X.groupby(['region', 'sector'])[['X', 'XFOB']].sum(),
        M.groupby(['region', 'sector'])[['M', 'MCIF']].sum(),
        xs.add_prefix('X_'), ms.add_prefix('M_')], axis=1).fillna(0.0)
    v = vst.rename(columns={'margin': 'sector', 'vst_musd_s11': 'VST'}).set_index(['region', 'sector'])['VST']
    t = t.join(v, how='outer').fillna(0.0)
    t.index.names = ['region', 'sector']
    return t.reset_index(), tr, dropped


def _tshare(target_out, r):
    o, g = target_out.get((r, 'oil'), 0.0), target_out.get((r, 'gas'), 0.0)
    return o / (o + g) if (o + g) > 0 else np.nan


def macro_targets(macro, trade):
    """GDP = C + G + I + (VFOB + VST) - VCIF with one factor on S02 C, G and GFCF (decision 2)."""
    nx = trade.groupby('region').apply(lambda t: t['XFOB'].sum() + t['VST'].sum() - t['MCIF'].sum(), include_groups=False).rename('NX')
    m = macro.set_index('region')[['GDP_musd', 'C_musd', 'G_musd', 'GFCF_musd']].join(nx)
    m['NX'] = m['NX'].fillna(0.0)
    m['factor'] = (m['GDP_musd'] - m['NX']) / (m['C_musd'] + m['G_musd'] + m['GFCF_musd'])
    m['C'] = m['C_musd'] * m['factor']
    m['G'] = m['G_musd'] * m['factor']
    m['I'] = m['GFCF_musd'] * m['factor']
    return m.reset_index()


# ------------------------------------------------------------------ prior
class RegionPrior:
    """The prior of one region in purchaser values, plus every change made to it (for the ledger)."""

    def __init__(self, region, sectors):
        self.region, self.sectors = region, sectors
        self.notes = []          # (item, before, after, rule, flag)


B06_GOODS = ('oil', 'gas')      # one I-O commodity (ISIC B06) in the source tables; S11 splits its rows
B06_IO_STRUCTURE = ('oil',)     # goods whose smear structure is the B06 row (world_energy_structure)
CRUDE_REFINERY = 'pet'          # round 3 (final QA 2 item 5): the crude buyer of last resort is refining
CRUDE_SMEAR_USERS = 'crude_only_to_refining_own_use_and_listed_direct_users_other_b06_weight_to_refining_no_buyer_fill_on_refining'
POWER_FUEL_CELLS = 's11_unsd_crude_gas_pet_burn_values_held_as_cell_targets_of_crude_burning_power_columns'
POWER_COLUMN = 'ely'
POWER_FUELS = ('oil', 'gas', 'pet')
POWER_FUELS_ALL = ('coa', 'oil', 'gas', 'pet')
# Fable QA D-06: every region's power column holds its S11 power fuel values (coal, crude, gas incl. gas_dist, pet)
POWER_FUEL_CELLS_ALL = 's11_power_fuel_values_coal_crude_gas_pet_held_as_cell_targets_of_every_power_column'
POWER_CRUDE_MIN_SHARE = 0.05    # a power column is a crude burner when crude is at least 5% of its listed fuel value
POWER_ROW_MAX = 0.9             # held power cells take at most this share of the held row (domestic sales, imports)
OWN_USE_BASIC = 'basic_value_of_the_diagonal_over_output'
ELY_ANCHOR = 'measured_use_class_prices_x_s11_volumes_plus_price_shield_held_in_the_listed_regions'   # s13 config ELY_ANCHOR
ELY_HOLD_NET = 'prior_less_netted_own_use_at_least_the_floor_and_the_s11_value_in_iea_ely_subsidy_regions'   # s13 config ELY_HOLD_NET
# s13 choice ely_hold_cap -> m: the held ely value at most the S11 value plus (m - 1) x its domestic electricity sales
ELY_HOLD_CAP = {f'held_at_most_the_s11_value_plus_{t}_of_its_domestic_electricity_sales_never_below_the_floor': m
                for t, m in (('0p25', 1.25), ('0p5', 1.5), ('1p0', 2.0))}


def world_energy_structure(io, sectors, crude_cols=None):
    """The world I-O structure of each energy good: its purchaser value shares over the agent columns, summed
    over every region (GTAP 12 ch.12 §12.4.1 smears toward 'a structure derived from the I-O tables').

    coa, gas and pet: the good's own io_s12 rows. oil: the source I-O tables have one commodity, B06, and S11 gives
    the oil rows only the energy balance's crude users (fix-round A8: refining and the UNSD direct users; the rest of
    the B06 row is gas), so the io_s12 oil rows are the energy data's structure, not an I-O one. The I-O structure of
    crude is the B06 row: the oil and gas rows added (S11-Hb06: cell by cell the io_s10 B06 row), with the B06
    industry's own purchases on the oil column (ch.12 §12.2.2: crude into oil and gas extraction is the oil
    industry's). The gas rows keep every B06 buyer but the refinery (whose gas is the measured refinery gas), so they
    stay an I-O structure and are used as they are.
    crude_cols (round 3, final QA 2 item 5; s13 choice crude_smear_users): crude is used only by refining, the oil
    industry itself and the energy balance's listed direct users (config/s11/crude_direct_users.csv), so the B06 weight of
    every other buyer goes to the refinery column (pet), not to air transport or households.
    Returns {good: array over sectors + FD}."""
    cols = list(sectors) + list(FD)
    ix = {c: j for j, c in enumerate(cols)}

    def rows_sum(goods):
        return io[io['row'].isin([f'{k}_{c}' for c in goods for k in ('dom', 'imp')])][cols].to_numpy(float).clip(min=0.0).sum(axis=0)

    out = {}
    for c in ENERGY_TARGETS:
        if c in B06_IO_STRUCTURE and all(g in ix for g in B06_GOODS):
            v = rows_sum(B06_GOODS)
            own = sum(v[ix[g]] for g in B06_GOODS)
            for g in B06_GOODS:
                v[ix[g]] = own if g == c else 0.0
            if crude_cols is not None and CRUDE_REFINERY in ix:
                keep = np.array([col in crude_cols or col == CRUDE_REFINERY for col in cols])
                v[ix[CRUDE_REFINERY]] += float(v[~keep].sum())
                v[~keep] = 0.0
        else:
            v = rows_sum((c,))
        t = v.sum()
        out[c] = v / t if t > 0 else np.full(len(cols), 1.0 / len(cols))
    return out


def _crude_buyer(c, crude_cols, idx, status, own=True):
    """Round 3 (final QA 2 item 5): the column that takes a crude row with no prior buyer: refining (pet) if it produces,
    else (imports only) the oil industry's own use; None for any other good or when neither produces."""
    if c != 'oil':
        return None
    for col in (CRUDE_REFINERY,) + (('oil',) if own else ()):
        if col in idx and status.get(col) not in ('zero_target', 'none', None):
            return idx[col]
    return None


def power_cell_targets(cs, regions, enabled=True, min_share=POWER_CRUDE_MIN_SHARE):
    """Round 3 (final QA 2 item 3): {region: {(kind, good): basic USD million}} from S11 crude_cell_split_s11.csv, for the
    power columns (column ely) whose listed crude burn is at least min_share of the column's listed crude, gas and pet
    value: crude (oil), gas and pet, domestic and imported, at S11 prices (GTAP 12 ch.12 §12.4, ch.17A)."""
    out = {}
    if not enabled or cs is None or not len(cs):
        return out
    for x in cs.to_dict('records'):
        if x['column'] != POWER_COLUMN or x['region'] not in regions:
            continue
        v = {('dom', 'oil'): x['crude_value_dom_musd'], ('imp', 'oil'): x['crude_value_imp_musd'],
             ('dom', 'gas'): x['gas_value_dom_musd'], ('imp', 'gas'): x['gas_value_imp_musd'],
             ('dom', 'pet'): x.get('pet_value_dom_musd', 0.0), ('imp', 'pet'): x.get('pet_value_imp_musd', 0.0)}
        v = {k: (max(float(a), 0.0) if np.isfinite(float(a)) else 0.0) for k, a in v.items()}
        tot = sum(v.values())
        crude = v[('dom', 'oil')] + v[('imp', 'oil')]
        if tot > 0 and crude >= min_share * tot:
            out[x['region']] = v
    return out


def power_cell_targets_all(pf, regions):
    """Fable QA D-06 (s13 choice power_fuel_cells = POWER_FUEL_CELLS_ALL): {region: {(kind, good): basic USD million}} from
    S11 power_fuels_s11.csv for every region's power column (io_column ely): coal, crude, gas (fuels gas and gas_dist, both
    on the gas row) and pet, domestic and imported, at S11 prices (GTAP 12 ch.12 §12.4, ch.17A)."""
    out = {}
    if pf is None or not len(pf):
        return out
    for x in pf.to_dict('records'):
        if x['io_column'] != POWER_COLUMN or x['region'] not in regions or x['commodity'] not in POWER_FUELS_ALL:
            continue
        d = out.setdefault(x['region'], {})
        for kind in ('dom', 'imp'):
            a = float(x[f'value_{kind}_musd'])
            d[(kind, x['commodity'])] = d.get((kind, x['commodity']), 0.0) + (max(a, 0.0) if np.isfinite(a) else 0.0)
    # beta v4 dry run 3 (S13-H90fit LBR ely 0.929): a fuel the region's 088 plants do not burn is held at 0, not left to the
    # fit (the prior gave 38 power columns coal that UNSD does not record, NGA 337 USD m; LBR's 1.5 m broke the 90% check)
    for v in out.values():
        for c in POWER_FUELS_ALL:
            for kind in ('dom', 'imp'):
                v.setdefault((kind, c), 0.0)
    return {r: v for r, v in out.items() if sum(v.values()) > 0}


POWER_CELL_SCALES = (0.75, 0.5, 0.35, 0.25)      # Fable QA F-08: levels tried, the S11 fuel mix kept, before the free column
POWER_CELLS_SCALED = 's11_mix_held_at_the_highest_level_the_fit_carries_0p75_0p5_0p35_0p25_else_free'


def hold_power_cells(pv, tau_cell, idx, status, tgt, X, M, power_cells, row_max=POWER_ROW_MAX):
    """Round 3 (final QA 2 item 3; s13 choice power_fuel_cells), in place on the prior pv: the power column's crude, gas
    and pet cells are held at their S11 basic values (fit.Column fixed_basic), as the S11 energy targets hold the rows.
    Each held row (domestic sales = target - exports, imports) keeps at least 1 - row_max for its other buyers; a cell
    above that is scaled down (reported). Returns ({(kind, i, j): basic}, report rows)."""
    held, rows = {}, []
    if not power_cells or POWER_COLUMN not in idx or status.get(POWER_COLUMN) not in ('prior', 'representative'):
        return held, rows
    j = idx[POWER_COLUMN]
    lam = float(power_cells.get('scale', 1.0))      # Fable QA F-08: the S11 mix at a level the column can carry
    for c in POWER_FUELS_ALL:
        if c not in idx or (c not in POWER_FUELS and not any((k, c) in power_cells for k in ('dom', 'imp'))):
            continue
        i = idx[c]
        for kind in ('dom', 'imp'):
            v = float(power_cells.get((kind, c), 0.0))
            room = (tgt[i] - X[i]) if kind == 'dom' else M[i]
            room = float(room) if np.isfinite(room) else 0.0
            h = min(v * lam, row_max * max(room, 0.0))
            st = 'held' if lam == 1.0 else f'held at {lam:g} of S11 (mix kept)'
            rows.append(dict(good=c, kind=kind, s11_musd=v, held_musd=h, row_musd=room,
                             status=st if h == v * lam else ('held at the row limit' if h > 0 else 'no room: cell shut')))
            held[(kind, i, j)] = h
            pv[kind][i, j] = h * tau_cell[i, j]
    return held, rows


ENERGY_USER_CELLS = 'held_at_prior_user_shares_refining_and_power_free_else_free_fit_flagged'
ENERGY_USER_POOL = ('pet', 'ely')      # refining and power: output free, their share of a held row is split by the fit


HOLD_COLUMN_MAX = 0.5    # a fixed-total column holds at most this share of its total in energy user cells (else its cells stay free)
ENERGY_USER_GOODS = ENERGY_TARGETS
PARTIAL_USERS_EXTRACTION = 'extraction_columns_keep_prior_presmear_share_of_the_rows_whose_users_the_fallback_frees'
USER_DROP_GOODS = (('pet',),)     # fit fallback after USER_SKIP_ROUNDS: rows whose users are left free (our choice)
USER_SKIP_ROUNDS = 4        # fit fallback: rounds of activities whose energy cells are freed before the whole region fits free (our choice)


POOL_SPLIT = 'refining_cells_at_s11_measured_inputs_crude_intake_refinery_gas_own_use_rest_of_the_pool_at_prior_shares'
NO_REFINERY_CRUDE = 'no_household_crude_fill_oil_own_use_takes_a_no_buyer_crude_row'   # beta v4 P14 (choice no_refinery_crude_use)


def pool_measured(energy_caps, own_caps, tgt, X, M, idx):
    """Beta v4 P15 (s13 choice energy_user_pool_split; GTAP 12 ch.17A eq. 17.8-17.9, energy use of the energy activities held
    at the energy balance; ch.12 Table 12.3, own use from the balance): {(good, column): (domestic, imported) basic USD
    million} of the refining column's measured energy inputs, the values S11's 90 percent rule priced (S11 energy_use_caps):
    crude intake, refinery gas and its own use + losses of products (where own_caps caps the pet diagonal, s13 choice
    own_use_cap), the last split domestic and imported by the held row. A good with no measurement is left out."""
    out = {}
    ec = energy_caps or {}
    if ec.get('intake_measured'):
        out[('oil', 'pet')] = (float(ec.get('intake_value_dom_musd', 0.0)), float(ec.get('intake_value_imp_musd', 0.0)))
    gd, gm = ec.get('refinery_gas_value_dom_musd'), ec.get('refinery_gas_value_imp_musd')
    if gd is not None and gm is not None and np.isfinite(float(gd)) and np.isfinite(float(gm)):
        out[('gas', 'pet')] = (float(gd), float(gm))
    v = ec.get('pet_own_use_value_musd')
    if 'pet' in idx and (own_caps or {}).get('pet') is not None and v is not None and np.isfinite(float(v)) and np.isfinite(tgt[idx['pet']]):
        i = idx['pet']
        d, m = max(tgt[i] - X[i], 0.0), max(M[i], 0.0)
        v = float(v)
        out[('pet', 'pet')] = (v * d / (d + m), v * m / (d + m)) if d + m > 0 else (0.0, 0.0)
    return out


def hold_energy_users(pv, tau_cell, idx, status, tgt, X, M, held, cols_all, pool=ENERGY_USER_POOL, caps=None, totals=None, skip=(), goods=None,
                      only=None, base=None, pool_held=None, share_caps=None):
    """Fix round S16 (Fable QA C-01; s13 choice energy_user_cells; GTAP 12 ch.17A eq. 17.8-17.9, energy use by agent held
    at the energy balance), in place on the prior pv and the held cells: every held energy row (ENERGY_TARGETS; domestic
    sales = target - exports, imports) is split across its buyers at their prior basic shares and the cells are held
    (fit.Column fixed_basic), after the cells already held (power fuel cells). The refining and power columns (pool) are
    not held: together they take their prior share of the row, which the fit splits between them. caps: {(good, column):
    USD million} on a column's domestic plus imported cell at basic value (C-03: gas into pipeline transport at the UNSD
    flow); the excess goes to the row's other held users pro rata. totals: the fixed column totals at purchasers' values (a free
    activity: its prior column, purchases plus value added); a column whose held cells would take more than HOLD_COLUMN_MAX of its total (a small
    extraction column buying its prior share of revalued rows: ESP oil, ALB gas) keeps its prior cells, free,
    and every column in skip (the fit's fallback: an activity whose own market row binds with its cells held) keeps
    its prior cells as in the free fit. goods: the held rows (None: every ENERGY_TARGETS row; the fallback drops pet). only (Fable QA F-06, s13 choice energy_users_fallback): hold only these columns'
    cells, each at its prior share of the whole row (not of the own good's diagonal), every other buyer free; the
    fallback for a region that cannot carry every held user cell. base: the prior the shares are read from (default
    pv); the fallback passes the prior before the ch.12 §12.4.1 smears, which put 1/32 of a row's world structure on a
    tiny extraction cell. pool_held (beta v4 P15, s13 choice energy_user_pool_split; pool_measured): {(good, column): (domestic,
    imported)} measured values of a pool column, held at that value (at most what the row leaves after the cells already
    held, scaled down pro rata where they would pass it); the rest of the row goes to the held users and the other pool
    column at their prior shares, as before. A pool column with a measured value is held even where it had no prior cell,
    and it is never freed by HOLD_COLUMN_MAX (refining's crude is most of its cost). share_caps (beta v5 F, s13 choice
    fuel_share_cap; fuel_share_caps): {(good, column): basic USD million} on a non-energy activity's held fuel cell (domestic
    plus imported), applied after caps; the excess goes pro rata to the row's other held users that are not share-capped
    (households among them), domestic to domestic and imported to imported. Returns report rows."""
    rows = []
    allnew, pinned_all = {}, {}
    J = len(cols_all)
    pj = [idx[c] for c in pool if c in idx]
    caps = caps or {}
    for c in ENERGY_TARGETS:
        if c not in idx or (goods is not None and c not in goods):
            continue
        i = idx[c]
        new = {}
        for kind in ('dom', 'imp'):
            room = (tgt[i] - X[i]) if kind == 'dom' else M[i]
            room = float(room) if np.isfinite(room) else 0.0
            if room <= 0:
                continue
            src = pv if base is None else base
            b = np.divide(src[kind][i], tau_cell[i], out=np.zeros(J), where=tau_cell[i] > 0)
            fixed = {j: v for (k, ii, j), v in held.items() if k == kind and ii == i}
            left = room - sum(fixed.values())
            pinned = {}
            for col in (pool if pool_held else ()):
                v = (pool_held or {}).get((c, col))
                if v is None or col not in idx or idx[col] in fixed or status.get(col) in ('zero_target', 'none', None):
                    continue
                pinned[idx[col]] = max(float(v[0] if kind == 'dom' else v[1]), 0.0)
            cand = [j for j in range(J) if j not in fixed and j not in pinned and b[j] > 0]
            tot_all = float(sum(b[j] for j in cand))
            tp = sum(pinned.values())
            if pinned and (tp > left or tot_all <= 0):
                # the measured cells cannot pass what the row leaves; with no other buyer they take all of it
                f = (max(left, 0.0) / tp) if tp > 0 else 0.0
                pinned = {j: v * f for j, v in pinned.items()}
                tp = sum(pinned.values())
            users = [j for j in cand if j not in pj and (only is None or (j in only and j != i))]
            tot = float(sum(b[j] for j in users))
            if left <= 0 or (tot <= 0 and not pinned):
                continue
            rest = left - tp
            left_users = rest * tot / tot_all if tot_all > 0 else 0.0
            new[kind] = {j: left_users * b[j] / tot for j in users} if tot > 0 else {}
            for j, v in pinned.items():
                pinned_all[(kind, i, j)] = v
            rows.append(dict(good=c, kind=kind, row_musd=room, held_musd=left_users, pool_musd=left - left_users,
                             cells=len(users), pool_prior_share=1.0 - tot / tot_all if tot_all > 0 else 0.0,
                             scale=left_users / tot if tot > 0 else np.nan, capped_column='', capped_musd=0.0,
                             pool_held_musd=tp, pool_held_columns=' '.join(cols_all[j] for j in pinned)))
        for (g, col), cap in caps.items():
            if g != c or col not in cols_all:
                continue
            j = cols_all.index(col)
            have = sum(new.get(k, {}).get(j, 0.0) for k in ('dom', 'imp'))
            if have <= cap:
                continue
            f = cap / have
            for k, cells in new.items():
                if j not in cells:
                    continue
                cut = cells[j] * (1.0 - f)
                cells[j] *= f
                others = [jj for jj in cells if jj != j]
                ot = sum(cells[jj] for jj in others)
                if ot <= 0:
                    cells[j] += cut          # no other held user: the cap cannot bind on this row
                    continue
                for jj in others:
                    cells[jj] += cut * cells[jj] / ot
                for r_ in rows:
                    if r_['good'] == c and r_['kind'] == k:
                        r_.update(capped_column=col, capped_musd=r_['capped_musd'] + cut)
        capped_j = {cols_all.index(col) for (g, col) in (share_caps or {}) if g == c and col in cols_all}
        for (g, col), cap in (share_caps or {}).items():
            if g != c or col not in cols_all:
                continue
            j = cols_all.index(col)
            have = sum(new.get(k, {}).get(j, 0.0) for k in ('dom', 'imp'))
            if have <= cap:
                continue
            f = max(cap, 0.0) / have
            for k, cells in new.items():
                if j not in cells:
                    continue
                others = [jj for jj in cells if jj not in capped_j]
                ot = sum(cells[jj] for jj in others)
                if ot <= 0:
                    continue             # no uncapped held user of this row: the cap cannot bind on it
                cut = cells[j] * (1.0 - f)
                cells[j] *= f
                for jj in others:
                    cells[jj] += cut * cells[jj] / ot
                for r_ in rows:
                    if r_['good'] == c and r_['kind'] == k:
                        r_['share_capped_columns'] = (r_.get('share_capped_columns', '') + ' ' + col).strip()
                        r_['share_capped_musd'] = r_.get('share_capped_musd', 0.0) + cut
        for kind, cells in new.items():
            for j, h in cells.items():
                allnew[(kind, i, j)] = h
    over = set()
    if totals is not None:
        load = np.zeros(J)
        for (kind, i, j), h in list(allnew.items()) + list(held.items()):
            if (kind, i, j) in pinned_all:
                continue
            load[j] += h * tau_cell[i, j]
        over = {j for j in range(J) if np.isfinite(totals[j]) and load[j] > HOLD_COLUMN_MAX * max(totals[j], 0.0)}
    skipped = {cols_all.index(c) for c in skip if c in cols_all}
    over |= skipped
    for (kind, i, j), h in allnew.items():
        if j in over:
            # a skipped column, or one whose held cells would pass HOLD_COLUMN_MAX of its total, keeps its prior cells as in
            # the free fit (final round 2026-10-25: at the split value BHR air, a representative-table column, and ALB gas
            # bought crude and gas equal to their whole output and the fit left them no value added, S14-Hzerodiv)
            continue
        pv[kind][i, j] = h * tau_cell[i, j]
        held[(kind, i, j)] = h
    for (kind, i, j), h in pinned_all.items():
        # beta v4 P15: the refining column's measured inputs are held, whatever HOLD_COLUMN_MAX says (not in skip)
        if j in skipped:
            continue
        pv[kind][i, j] = h * tau_cell[i, j]
        held[(kind, i, j)] = h
    for r_ in rows:
        r_['free_columns'] = ' '.join(cols_all[j] for j in sorted(over))
    return rows


FUEL_SHARE_CAP = 'non_energy_activity_fuel_cell_at_most_max_2x_prior_share_or_prior_plus_5pt_of_fitted_output_excess_to_other_held_users'
FUEL_CAP_GOODS = ('coa', 'oil', 'gas', 'pet')     # beta v5 F: the fuels (electricity is not a fuel input here)
FUEL_CAP_FACTOR, FUEL_CAP_POINTS = 2.0, 0.05      # cap = max(2 x prior share, prior share + 5 points) (our choice, labelled)
FUEL_CAP_MIN_MUSD = 1.0                           # an excess below USD 1 million is left alone
FUEL_CAP_PASSES = 4                               # refits; each pass re-reads the fitted output
FUEL_CAP_REMAINDER_FLAG = 0.25                    # flag a row whose capped excess is above this share of the row


def fuel_share_caps(R, info, sectors, caps=None, energy=ENERGY_TARGETS + ('ely',), goods=FUEL_CAP_GOODS, factor=FUEL_CAP_FACTOR,
                    points=FUEL_CAP_POINTS, min_musd=FUEL_CAP_MIN_MUSD):
    """Beta v5 F (s13 choice fuel_share_cap; our rule, not in the GTAP text): the fitted fuel cells (coal, crude, gas,
    products; domestic plus imported, basic) of every non-energy activity whose share of the fitted output is above
    max(factor x its io_s12 share, io_s12 share + points). The held cells are money (hold_energy_users), so when the fit
    shrinks a column its fuel share grows (MAR road transport 80% of cost, RUS air 60%, GMB cement 53%). caps: the caps
    already set, {(good, column): basic USD million}; a new cap is the smaller of the two. Returns (caps, rows)."""
    caps = dict(caps or {})
    idx = {c: i for i, c in enumerate(sectors)}
    b0, out0 = info['basic0'], info['out0']
    rows = []
    for j, a in enumerate(sectors):
        if a in energy or info['status'].get(a) in ('zero_target', 'none', 'representative') or out0[j] <= 0 or R['out'][j] <= 0:
            continue
        for c in goods:
            if c not in idx:
                continue
            i = idx[c]
            s0 = float(b0['dom'][i, j] + b0['imp'][i, j]) / float(out0[j])
            have = float(R['dom'][i, j] + R['imp'][i, j])
            s1 = have / float(R['out'][j])
            cap_s = max(factor * s0, s0 + points)
            cap = cap_s * float(R['out'][j])
            if have - cap <= min_musd:
                continue
            k = (c, a)
            caps[k] = min(caps.get(k, np.inf), cap)
            rows.append(dict(good=c, column=a, prior_share=s0, fitted_share=s1, cap_share=cap_s, fitted_musd=have, cap_musd=caps[k]))
    return caps, rows


def hold_freed_rows_extraction(pv, tau_cell, idx, status, tgt, X, M, held, cols_all, goods, base, caps=None, totals=None):
    """Beta v4 rescan N3 (s13 choice partial_users_extraction), in place: the rows whose users the fallback frees (goods,
    USER_DROP_GOODS) keep the extraction columns (coa, oil, gas) at their prior share of the row before the ch.12 §12.4.1
    smears (base), as hold_energy_users does in the F-06 fallback; an extraction cell with no pre-smear prior also loses the
    smear (it stays 0, free). Every other buyer of the row stays free. Returns the report rows."""
    only = {idx[c] for c in EXTRACTION if c in idx and status.get(c) not in ('zero_target', 'none')}
    rows = hold_energy_users(pv, tau_cell, idx, status, tgt, X, M, held, cols_all, caps=caps, totals=totals, goods=goods, base=base, only=only)
    for c in goods:
        if c not in idx:
            continue
        i = idx[c]
        for kind in ('dom', 'imp'):
            for j in only:
                if j != i and (kind, i, j) not in held and base[kind][i, j] <= 0:
                    pv[kind][i, j] = 0.0
    return rows


def build_problem(region, r, sectors, trade_r, targets_fd, target_out, rep, rep_b06, support, world_energy, choices, energy=None,
                  energy_caps=None, subsidies=None, own_caps=None, hold_own=(), product_layers=None, ptax_source=None, power_cells=None, crude_cols=None, hold_users=True, user_caps=None, user_skip=(), user_goods=None,
                  vat=None, hold_extraction=False, user_share_caps=None):
    """r: io_s12 rows of one region indexed by row; energy: {(row, column): rate} from energy_rates_of (None or
    empty: one rate per column); energy_caps: the region's S11 energy_use_caps row (fix-round A10,
    s13_fit/energy.py), or None; subsidies: {good: USD million} of fuel subsidy to book (fix-round B15,
    book_fuel_subsidies), or None; own_caps: {good: UNSD own use + losses share of output} (fix round wG,
    energy.cap_own_use), or None; hold_own: goods whose own-use share is a held share group in this fit (fix round
    wG second pass, where the free fit took a capped diagonal above its cap); power_cells: {(kind, good): basic USD
    million} held on the power column (round 3, final QA 2 item 3, s13 choice power_fuel_cells), or None; crude_cols:
    the crude users for the no-buyer fills (s13 choice crude_smear_users), or None; hold_users: the held energy user cells
    (s13 choice energy_user_cells, hold_energy_users) apply; user_caps: their caps by (good, column); vat: {'g114_pct', 'g1142_pct', 'gdp_musd'} of a GCC VAT
    state (Fable QA C-09, s13 choice vat_final_demand, ptax_source.vat_final_demand), or None; hold_extraction: the
    extraction columns' (coa, oil, gas) cells of the held energy rows are held at their prior share of the row, every
    other buyer free (hold_energy_users only=), and their electricity cells keep their prior share of the column
    (extraction_ely_groups; Fable QA F-06, s13 choice energy_users_fallback). support may carry 'input_items' ({row good: USD million}, fix round wG,
    book_pse_input). Returns (Problem, info dict). info['tau_cell'] is the n x J tax power held on every
    cell; info['tau'] and info['tau_tls'] are the column powers at the prior (TLS and support over basic purchases)."""
    n = len(sectors)
    idx = {c: i for i, c in enumerate(sectors)}
    notes = []
    cols_all = list(sectors) + list(FD)
    basic = {}
    for kind in ('dom', 'imp'):
        a = r.loc[[f'{kind}_{c}' for c in sectors], cols_all + ['dpabr']].to_numpy(float).copy()
        basic[kind] = a
    tls = r.loc['TLS', cols_all + ['dpabr']].to_numpy(float).copy()
    evfp = r.loc[[f'EVFP_{f}' for f in FACTORS], list(sectors)].to_numpy(float)
    va = evfp.sum(axis=0)
    out0 = r.loc['OUT', list(sectors)].to_numpy(float)
    # io_s12 is not exactly balanced; S13 sets output to cost (eq. 17.22) and sales (eq. 17.28), so the gaps are ledgered
    allc = [c for c in r.columns if c not in ('OUT', 'region')]
    domr = [f'dom_{c}' for c in sectors]
    otax_rows = ['OTAX'] if 'OTAX' in r.index else []      # S12 fix round A3: D29 booked as an output tax
    cost0 = r.loc[domr + [f'imp_{c}' for c in sectors] + ['TLS'] + [f'EVFP_{f}' for f in FACTORS] + otax_rows, list(sectors)].to_numpy(float).sum(axis=0)
    otax = r.loc['OTAX', list(sectors)].to_numpy(float) if otax_rows else np.zeros(n)
    sales0 = r.loc[domr, allc].to_numpy(float).sum(axis=1)
    rowout0 = r.loc[domr, 'OUT'].to_numpy(float) if 'OUT' in r.columns else out0
    io12_gap = dict(column=float(np.abs(out0 - cost0).sum()), row=float(np.abs(rowout0 - sales0).sum()))
    for j, c in enumerate(sectors):
        if abs(out0[j] - cost0[j]) > 1.0:          # ledger the material cells; S13-Rio12gap reports the totals
            notes.append(('OUT less column cost', c, float(out0[j]), float(cost0[j]), 'io12_column_imbalance', 'IO12-IMBALANCE'))
        if abs(rowout0[j] - sales0[j]) > 1.0:
            notes.append((f'dom_{c} OUT less sales', 'row', float(rowout0[j]), float(sales0[j]), 'io12_row_imbalance', 'IO12-IMBALANCE'))
    # dpabr (residents' purchases abroad) joins households: GTAP 12 ch.10B p.3 trvl treatment
    jp = len(sectors)
    for kind in ('dom', 'imp'):
        if np.abs(basic[kind][:, -1]).sum() > 0:
            notes.append(('dpabr', f'{kind} rows', float(basic[kind][:, -1].sum()), 0.0, 'dpabr_to_households', 'DPABR-TO-P'))
        basic[kind][:, jp] += basic[kind][:, -1]
        basic[kind] = basic[kind][:, :-1]
    if tls[-1] != 0:
        notes.append(('dpabr', 'TLS', float(tls[-1]), 0.0, 'dpabr_to_households', 'DPABR-TO-P'))
    tls[jp] += tls[-1]
    tls = tls[:-1]
    # negative purchases are cleaned to zero (GTAP 12 ch.8 §8.3 p.3)
    for kind in ('dom', 'imp'):
        neg = basic[kind] < 0
        for i, j in zip(*np.where(neg)):
            notes.append((f'{kind}_{sectors[i]}', cols_all[j], float(basic[kind][i, j]), 0.0, 'negative_cells', 'NEG-CELL-ZERO'))
        basic[kind][neg] = 0.0
    # tax powers by cell: energy rows at the GTAP ad valorem energy rates plus the column's general rate (tax_rates)
    bsum = basic['dom'].sum(axis=0) + basic['imp'].sum(axis=0)
    cell_rate, placed = place_column_taxes(basic, tls, cols_all, sectors, energy or {}, TAX_RATE_RULE.get(choices.get('tax_rates'), 'held'),
                                           layers=product_layers, excise_fixed=choices.get('excise_at_source') == EXCISE_AT_SOURCE)
    # s13 choice product_tax_source (round-3 final QA2 item 1; s13_fit/ptax_source.py): a representative-table region's
    # general product-tax money at the IMF GFS G114 total less the energy excise ('g114'), or its rates held ('rates')
    ptax_src = dict(ptax_source) if ptax_source else None
    if ptax_src:
        # the donor's negative general rates (its subsidies) have no source for this region (ptax_source.zero_unsourced_general)
        cell_rate, placed['general'], tls, zinfo = PS.zero_unsourced_general(cell_rate, placed['general'], basic['dom'] + basic['imp'], tls)
        ptax_src.update(zinfo)
        if zinfo['unsourced_cells']:
            notes.append(('donor negative general product-tax rates', 'all columns', -zinfo['unsourced_musd'], 0.0, 'product_tax_source', 'DONOR-SUBSIDY-ZERO'))
    if ptax_src and ptax_src.get('mode') == 'g114':
        sc = PS.scale_general_to_total(cell_rate, placed['general'], basic['dom'] + basic['imp'], tls, ptax_src['g114_musd'],
                                       cap_excise=choices.get('excise_cap_g114') == PS.EXCISE_CAP_G114)
        if sc is None:
            ptax_src.update(mode='rates', note='no positive general money on the io_s12 flows to scale: rates held')
        else:
            cell_rate, placed['general'], tls, sinfo = sc
            ptax_src.update(sinfo)
            notes.append(('general product-tax money (donor pattern)', 'all columns', sinfo['donor_general_musd'], sinfo['general_target_musd'],
                          'product_tax_source', 'PTAX-G114'))
    vat_info = None
    if vat:
        # Fable QA C-09: a GCC VAT state's VAT on final demand (households, government) at the IMF GFS money; firms deduct
        # input VAT, so a representative-table region's firms lose the donor's general part
        b12_ = basic['dom'] + basic['imp']
        E_ = float((np.clip(cell_rate - placed['general'], 0.0, None) * b12_).sum())
        excise = max(float(vat.get('g1142_pct') or 0.0), 0.0) / 100.0 * float(vat['gdp_musd'])
        if vat.get('excise_part') == PS.EXCISE_LESS_ENERGY:
            excise = max(excise - E_, 0.0)      # beta v4 G14: G1142 holds the fuel excise booked on the energy rows
        vat_money = max(float(vat['g114_pct']) / 100.0 * float(vat['gdp_musd']) - excise - E_, 0.0)
        cell_rate, placed['general'], tls, vat_info = PS.vat_final_demand(cell_rate, placed['general'], b12_, tls, sectors, cols_all,
                                                                          vat_money, excise, zero_firms=bool(ptax_src), exempt=tuple(vat.get('exempt_rows') or ()),
                                                                          rate_max=float(vat.get('statutory_rate_pct', np.nan)) / 100.0)
        vat_info['energy_excise_musd'] = E_
        vat_info['statutory_rate'] = float(vat.get('statutory_rate_pct', np.nan)) / 100.0
        vat_info.update(PS.final_demand_rate_max(placed['general'], sectors, cols_all))
        notes.append(('general product-tax money on final demand (VAT)', 'p g', vat_info['general_before_musd'], vat_info['general_after_musd'],
                      'vat_final_demand', 'VAT-FINAL-DEMAND'))
        if ptax_src and ptax_src.get('mode') == 'g114':
            ptax_src['general_target_musd'] = float((placed['general'] * b12_).sum())
    tau_cell = 1.0 + cell_rate
    tau_tls_cell = tau_cell.copy()          # the io_s12 net product-tax power, before farm support
    # s13 choice product_tax_totals (round-3 QA item 3): the general part of each column's product tax (every cell's rate
    # less its energy-tax rate) in money on the io_s12 flows, the amount the fit holds; and the column's net product tax
    # there (io_s12 TLS, or the A1 moved total where the energy excise exceeds it)
    b12 = basic['dom'] + basic['imp']
    general = placed['general'].copy()
    gen_target = (general * b12).sum(axis=0)
    ptax_prior = (cell_rate * b12).sum(axis=0)
    tau = np.where(bsum > 0, 1.0 + tls / np.where(bsum > 0, bsum, 1.0), 1.0)
    tau_tls = tau.copy()
    pi = np.ones(n)
    pse_in = pse_out = 0.0
    pse_items = {}
    if choices['farm_support'] == 'pse_output_and_input_as_fixed_rates_on_crp':
        jc = idx['crp']
        pse_in, pse_out = support.get('input', 0.0), support.get('output', 0.0)
        bc = basic['dom'][:, jc].sum() + basic['imp'][:, jc].sum()
        if pse_in and bc > 0:
            # s13 choice pse_iea_overlap (round-3 final QA2 item 6): the farm part of the IEA electricity subsidy B15 books
            # on crp's ely cell (S11 money x crp's share of the subsidised columns' io_s12 ely purchases) is netted off the
            # PSE electricity remainder, so the same support is booked once
            net = {}
            if choices.get('pse_iea_overlap') == PSE_IEA_NET and subsidies and 'ely' in (support.get('remainder_rows') or ()):
                ie = idx['ely']
                be = (basic['dom'][ie, :] + basic['imp'][ie, :])[subsidy_columns(cols_all, sectors)]
                if be.sum() > 0 and subsidies.get('ely', 0.0) > 0:
                    net['ely'] = float(subsidies['ely']) * float(basic['dom'][ie, jc] + basic['imp'][ie, jc]) / float(be.sum())
            elif choices.get('pse_iea_overlap') == PSE_IEA_NET_FULL and subsidies and 'ely' in (support.get('remainder_rows') or ()):
                # beta v4 G11: the whole IEA electricity money; book_pse_input nets at most the PSE remainder's ely share
                if subsidies.get('ely', 0.0) > 0:
                    net['ely'] = float(subsidies['ely'])
            pse_items = book_pse_input(basic, tau_cell, tau_tls_cell, idx, jc, pse_in, support.get('input_items', {}),
                                       remainder_rows=support.get('remainder_rows'), net=net)
            for c, f in pse_items.items():          # the item cell's TLS rate falls by basic_before / basic_after, its money stays
                general[idx[c], jc] *= f['basic_before'] / f['basic_after']
            tau_tls[jc] = 1.0 + tls[jc] / (basic['dom'][:, jc].sum() + basic['imp'][:, jc].sum())
            pse_net = sum(f.get('netted_musd', 0.0) for f in pse_items.values())
            tau[jc] = tau_tls[jc] - (pse_in - pse_net) / (basic['dom'][:, jc].sum() + basic['imp'][:, jc].sum())
            for c, f in pse_items.items():
                notes.append((f'dom_{c} and imp_{c} basic value', 'crp', f['basic_before'], f['basic_after'], 'pse_input_items', 'PSE-INPUT-ITEM'))
        if pse_out and out0[jc] > 0:
            pi[jc] = 1.0 - pse_out / out0[jc]
    # S12 output tax (A3): the activity's cost excludes it and its basic sales include it, so the output power is
    # (OUT - PSE output support) / (OUT - output tax); with no output tax this is the PSE rate above
    for j in range(n):
        if otax[j] != 0 and out0[j] - otax[j] > 0:
            pse_j = pse_out if (choices['farm_support'] == 'pse_output_and_input_as_fixed_rates_on_crp' and sectors[j] == 'crp') else 0.0
            pi[j] = (out0[j] - pse_j) / (out0[j] - otax[j])
    bad_tau = [cols_all[j] for j in range(len(cols_all)) if tau[j] <= 0 or (tau_cell[:, j] <= 0).any()]
    # trade vectors
    X = np.array([trade_r.get(('X', c), 0.0) + trade_r.get(('VST', c), 0.0) for c in sectors])
    M = np.array([trade_r.get(('M', c), 0.0) for c in sectors])
    tgt = np.array([target_out.get((region, c), np.nan) if c in output_targets(choices.get('energy_targets')) else np.nan for c in sectors])
    # beta v4 P4 (s11 choice ely_production_subsidy; GTAP 12 ch.12 §12.4.3 p.29): a documented 2022 transfer to the power
    # utilities, at most the 90 percent rule's shortfall, booked by S11 on energy_use_caps; here an output subsidy on ely: the
    # column's cost is the target plus the subsidy, so the output power falls (PTAX = output - cost < 0 on the column)
    ely_sub = float((energy_caps or {}).get('ely_output_subsidy_musd', 0.0) or 0.0)
    if 'ely' in idx and ely_sub > 0 and np.isfinite(tgt[idx['ely']]) and tgt[idx['ely']] > 0:
        je = idx['ely']
        p_old = pi[je]
        pi[je] = tgt[je] / (tgt[je] / p_old + ely_sub)
        notes.append(('output power', 'ely', float(p_old), float(pi[je]), 'ely_production_subsidy', 'ELY-OUTPUT-SUBSIDY'))
    # prior purchaser values
    pv = {k: basic[k] * tau_cell for k in ('dom', 'imp')}
    vapr = va.copy()
    fixed_va = np.zeros(n)
    negva = va < 0
    for j in np.where(negva)[0]:
        notes.append(('VA', sectors[j], float(va[j]), float(va[j]), 'negative_va', 'NEG-VA-HELD'))
        fixed_va[j] = va[j]
        vapr[j] = 0.0
    # which activities can produce
    status = {}
    for j, c in enumerate(sectors):
        has_prior = out0[j] > 0 and (pv['dom'][:, j].sum() + pv['imp'][:, j].sum() + max(vapr[j], 0)) > 0
        if choices.get('prior_without_va') == 'representative_column_when_needed' and has_prior and va[j] <= 0:
            has_prior = False          # a prior column with no positive value added cannot be fitted (eq. 17.27)
        need = X[j] > 0 or (np.isfinite(tgt[j]) and tgt[j] > 0)
        if np.isfinite(tgt[j]) and tgt[j] == 0:
            status[c] = 'zero_target'
        elif has_prior:
            status[c] = 'prior'
        elif need:
            status[c] = 'representative'
        else:
            status[c] = 'none'
    for j, c in enumerate(sectors):
        if status[c] == 'representative' and out0[j] > 0:          # a prior column replaced by prior_without_va
            if fixed_va[j] != 0:
                notes[:] = [x for x in notes if not (x[5] == 'NEG-VA-HELD' and x[1] == c)]
                notes.append(('VA', c, float(fixed_va[j]), 0.0, 'prior_without_va', 'NEG-VA-REP-COLUMN'))
                fixed_va[j] = 0.0
            if tls[j] != 0:          # the representative column carries no product tax (REP-TLS-IN-VA)
                notes.append(('TLS', c, float(tls[j]), 0.0, 'prior_without_va', 'REP-COLUMN-TLS-DROPPED'))
    # a commodity with no output has no domestic sales
    for j, c in enumerate(sectors):
        if status[c] in ('zero_target', 'none'):
            s = pv['dom'][j, :].sum()
            if s > 0:
                notes.append((f'dom_{c}', 'all agents', float(s / 1.0), 0.0, 'zero_output_no_domestic_sales', 'ZERO-OUTPUT-ROW'))
            pv['dom'][j, :] = 0.0
    # an energy target that S11 sets equal to exports leaves no domestic sales (ch.12 §12.4.1 targets)
    for j, c in enumerate(sectors):
        if status[c] == 'zero_target' or not np.isfinite(tgt[j]):
            continue
        if tgt[j] - X[j] <= 1e-9 * max(1.0, abs(tgt[j])):
            s = pv['dom'][j, :].sum()
            if s > 0:
                notes.append((f'dom_{c}', 'all agents', float(s), 0.0, 'target_all_exported_no_domestic_sales',
                              'ALL-EXPORTED-ROW'))
            pv['dom'][j, :] = 0.0
    # representative-table cost structure for an activity with exports or a target and no prior column
    for j, c in enumerate(sectors):
        if status[c] != 'representative':
            continue
        rc = rep.get(c if c not in ('oil', 'gas') else 'B06', {})
        for i, cc in enumerate(sectors):
            for kind in ('dom', 'imp'):
                key = f"{'domestic' if kind == 'dom' else 'imported'} {cc if cc not in ('oil', 'gas') else 'B06'}"
                sh = rc.get(key, 0.0)
                if cc in ('oil', 'gas'):
                    sh *= rep_b06[(kind, cc)]
                pv[kind][i, j] = sh
        vapr[j] = rc.get('va', 0.0) + rc.get('tls', 0.0)
        if rc.get('tls', 0.0):
            notes.append(('TLS share (a fraction of the column, not USD m)', c, float(rc.get('tls', 0.0)), 0.0, 'rep_column_tls_in_va', 'REP-TLS-IN-VA'))
        tau[j] = 1.0
        tau_tls[j] = 1.0             # no io_s12 rate is held on a representative column (QA S14 B1)
        tau_cell[:, j] = 1.0
        tau_tls_cell[:, j] = 1.0
        general[:, j] = 0.0
        gen_target[j] = ptax_prior[j] = 0.0
        notes.append(('column', c, 0.0, 1.0, 'zero_output_column_prior', 'REP-TABLE-COLUMN'))
    # a shut activity buys nothing
    for j, c in enumerate(sectors):
        if status[c] in ('zero_target', 'none'):
            s = pv['dom'][:, j].sum() + pv['imp'][:, j].sum() + max(vapr[j], 0.0)
            if s > 0:
                notes.append(('column', c, float(s), 0.0, 'shut_column', 'SHUT-COLUMN'))
            pv['dom'][:, j] = 0.0
            pv['imp'][:, j] = 0.0
            vapr[j] = 0.0
            gen_target[j] = ptax_prior[j] = 0.0
    # energy use by government and investment is eliminated in FIT (GTAP 12 ch.17A footnote 4)
    for jf in (cols_all.index('g'), cols_all.index('i')):
        for c in ENERGY_TRADE:
            for kind in ('dom', 'imp'):
                v = pv[kind][idx[c], jf]
                if v > 0:
                    notes.append((f'{kind}_{c}', cols_all[jf], float(v), 0.0, 'gov_inv_energy_removed', 'GOV-INV-ENERGY'))
                    pv[kind][idx[c], jf] = 0.0
    # fix-round A10: refinery crude and gas own use capped at the S11 energy balance (s13_fit/energy.py)
    cap_rows = []
    if energy_caps is not None:
        can_buy = np.array([j >= n or status[sectors[j]] not in ('zero_target', 'none') for j in range(len(cols_all))])
        cap_notes, cap_rows = EN.cap_prior(pv, tau, idx, cols_all, tgt, X, M, energy_caps, can_buy, crude_cols)
        notes.extend(cap_notes)
    smears = []
    pv_presmear = {k: pv[k].copy() for k in ('dom', 'imp')}     # before any smear: what S13-Rsmearfill measures against
    # GTAP 12 ch.12 §12.4.1 smears the IEA energy volume data toward the I-O structure: the usage structure becomes
    # 31/32 of the energy data's own structure plus 1/32 of a structure derived from the I-O tables, so that FIT
    # never sees a zero or tiny share of domestic product in total usage. S13 has no IEA volume data, so the same
    # weights are applied to the I-O prior row of each energy good whose domestic sales or imports S11 holds:
    # row = 31/32 row + 1/32 (row total) (that good's world I-O structure over the live agents; for crude the B06
    # row, world_energy_structure). Government and
    # investment are left out (ch.17A footnote 4). A row with no buyer at all is left to the no-buyer smears below.
    live = np.array([(j >= n or status[sectors[j]] not in ('zero_target', 'none')) and cols_all[j] not in ('g', 'i')
                     for j in range(len(cols_all))])
    for c in ENERGY_TARGETS:
        i = idx[c]
        for kind, need in (('dom', np.isfinite(tgt[i]) and tgt[i] - X[i] > 1e-9 * max(1.0, abs(tgt[i]))), ('imp', M[i] > 0)):
            row = pv[kind][i, :].copy()
            if not need or row.sum() <= 0:
                continue
            w = world_energy[c] * live
            if kind == 'dom':
                w[i] = 0.0            # not the industry's own output
            if w.sum() <= 0:
                continue
            new = (1 - SMEAR) * row + SMEAR * row.sum() * w / w.sum()
            pv[kind][i, :] = new
            smears.append((f'{kind}_{c}', 'energy smear: 31/32 own row, 1/32 world I-O structure of the good',
                           float(np.clip(new - row, 0.0, None).sum())))
    # imports: zero target removes the cells; a target with no prior buyer is smeared
    for i, c in enumerate(sectors):
        if M[i] <= 0:
            s = pv['imp'][i, :].sum()
            if s > 0:
                notes.append((f'imp_{c}', 'all agents', float(s), 0.0, 'zero_imports', 'ZERO-IMPORT-ROW'))
            pv['imp'][i, :] = 0.0
            continue
        if pv['imp'][i, :].sum() <= 0:
            d = pv['dom'][i, :].copy()
            if d.sum() > 0:
                pv['imp'][i, :] = d * SMEAR
                pv['dom'][i, :] = d * (1 - SMEAR)
                smears.append((f'imp_{c}', 'from domestic purchases', float(M[i])))
            else:
                jb = _crude_buyer(c, crude_cols, idx, status) if crude_cols is not None else None
                if jb is not None:
                    pv['imp'][i, jb] = M[i]
                    smears.append((f'imp_{c}', f'{cols_all[jb]} (no buyer in the prior; crude only to refining)', float(M[i])))
                else:
                    pv['imp'][i, jp] = M[i]
                    smears.append((f'imp_{c}', 'households (no buyer in the prior)', float(M[i])))
    # domestic sales a target requires, with no prior domestic buyer: smear from imports
    for i, c in enumerate(sectors):
        if not (np.isfinite(tgt[i]) and tgt[i] > 0):
            continue
        need = tgt[i] - X[i]
        other = np.ones(len(cols_all), bool)
        other[i] = False            # an industry's own use cannot absorb its whole output
        if need > 1e-9 * max(1.0, tgt[i]) and pv['dom'][i, other].sum() <= 0:
            m = np.where(other, pv['imp'][i, :], 0.0)
            if m.sum() > 0:
                pv['dom'][i, other] += m[other] * SMEAR
                pv['imp'][i, other] -= m[other] * SMEAR
                smears.append((f'dom_{c}', 'from imported purchases', float(need)))
            else:
                # beta v4 P14 (choice no_refinery_crude_use): with no refinery the oil industry's own use takes the row
                own_ok = choices.get('no_refinery_crude_use') == NO_REFINERY_CRUDE
                jb = _crude_buyer(c, crude_cols, idx, status, own=own_ok) if crude_cols is not None else None
                if jb is not None:
                    pv['dom'][i, jb] = need
                    smears.append((f'dom_{c}', f'{cols_all[jb]} (no buyer in the prior; crude only to refining)', float(need)))
                else:
                    pv['dom'][i, jp] = need
                    smears.append((f'dom_{c}', 'households (no buyer in the prior)', float(need)))
    # fix round wG: energy diagonals at most the UNSD own use + losses share of output (s13_fit/energy.py), after the
    # smears, which would otherwise put 1/32 of the import row's world structure (for crude the B06 diagonal) back on it
    own_cap_rows = []
    if own_caps:
        can_buy = np.array([j >= n or status[sectors[j]] not in ('zero_target', 'none') for j in range(len(cols_all))])
        oc = {c: v for c, v in own_caps.items() if c in idx and status.get(c) == 'prior'}
        # beta v5 N1 (s13 choice own_use_cap_listed): a listed non-energy diagonal is netted out like ely, not moved to other buyers
        oc_notes, own_cap_rows = EN.cap_own_use(pv, tau_cell, idx, cols_all, tgt, vapr, oc, can_buy,
                                                net_out=EN.OWN_USE_NET_OUT + tuple(c for c in oc if c not in EN.ENERGY),
                                                basic=choices.get('own_use_cap_valuation') == OWN_USE_BASIC,
                                                net_held=('ely',) if choices.get('ely_hold_net_own_use') == ELY_HOLD_NET else ())
        notes.extend(oc_notes)
    # fix-round B15: fuel subsidies as a negative purchase tax, the prior purchasers' values kept (after every prior change)
    tau_tls_nosub = tau_tls_cell.copy()
    general_nosub = general.copy()
    fuel = book_fuel_subsidies(pv, tau_cell, tau_tls_cell, idx, cols_all, sectors, tgt, X, M, subsidies or {},
                               hold_money=choices.get('electricity_subsidy_money') == ELY_SUBSIDY_HOLD,
                               exclude_energy=choices.get('fuel_subsidy_users') == FUEL_SUBSIDY_NON_ENERGY,
                               rho_max=RHO_MAX if choices.get('fuel_subsidy_rate_cap') == 'rate_at_most_0p8_of_basic_value_excess_not_booked' else None,
                               rho_max_good={'ely': ELY_SUB_RHO_MAX} if region in choices.get('ely_subsidy_rate_cap_regions', ()) else None)
    # a subsidised cell's power is tau (1 - rho): its general part is general (1 - rho) (the subsidy rate stays rho)
    general = general_nosub * np.divide(tau_tls_cell, tau_tls_nosub, out=np.ones_like(tau_tls_cell), where=tau_tls_nosub != 0)
    for c, f in fuel.items():
        if f['status'] == 'booked':
            notes.append((f'dom_{c} and imp_{c} basic value (firms, households, government)', 'subsidy', f['basic_prior_before'],
                          f['basic_prior_after'], 'fuel_subsidies', 'FUEL-SUBSIDY'))
    if ptax_src and ptax_src.get('mode') == 'g114':
        # the G114 money less the energy excise is the region's held total; the columns a representative or shut column
        # zeroed above pass their part to the others (in proportion to their money)
        s_ = float(gen_target.sum())
        if s_ > 0 and ptax_src['general_target_musd'] > 0:
            gen_target = gen_target * (ptax_src['general_target_musd'] / s_)
    # round 3 (final QA 2 item 3): the power column's crude, gas and pet cells held at their S11 values (basic), each held
    # row keeping room for its other buyers; the prior shows the held value (structural zeros, reports)
    if crude_cols is not None and 'oil' in idx:
        # final round 2026-10-25 (s13 choice crude_smear_users): crude cells outside refining, own use and the listed
        # direct users are shut in the prior, so the fit cannot grow them (BHR air, a representative-table column with
        # a dust crude cell, took 1.45 bn of crude, its whole output, once the power column held its S11 fuels)
        shut = [j for j, a in enumerate(cols_all) if a not in crude_cols and a != CRUDE_REFINERY]
        for kind in ('dom', 'imp'):
            pv[kind][idx['oil'], shut] = 0.0
    held_basic, power_rows = hold_power_cells(pv, tau_cell, idx, status, tgt, X, M, power_cells)
    user_rows = []
    if choices.get('energy_user_cells') == ENERGY_USER_CELLS and hold_users:
        fdtot0 = {'p': targets_fd['C'], 'g': targets_fd['G'], 'i': targets_fd['I']}
        # a free activity's reference total is its prior column (purchases at agents' prices plus value added)
        prior_col = pv['dom'][:, :n].sum(axis=0) + pv['imp'][:, :n].sum(axis=0) + np.maximum(vapr, 0.0)
        totals = np.array([(tgt[j] / pi[j] if np.isfinite(tgt[j]) else prior_col[j]) if j < n else fdtot0[cols_all[j]] for j in range(len(cols_all))])
        ph = (pool_measured(energy_caps, own_caps, tgt, X, M, idx) if choices.get('energy_user_pool_split') == POOL_SPLIT else None)
        user_rows = hold_energy_users(pv, tau_cell, idx, status, tgt, X, M, held_basic, cols_all, caps=user_caps, totals=totals, skip=user_skip,
                                      goods=user_goods, pool_held=ph, share_caps=user_share_caps)
        # beta v4 rescan N3 (s13 choice partial_users_extraction): the rows whose users the fallback frees (petroleum
        # products) keep the extraction columns at their pre-smear prior share of the row (as in the F-06 fallback); without
        # it the ch.12 §12.4.1 smear put a world share of YEM's products on its crude column, which the fit grew to 69% of cost
        if user_goods is not None and choices.get('partial_users_extraction') == PARTIAL_USERS_EXTRACTION:
            dropped = tuple(c for c in ENERGY_USER_GOODS if c not in user_goods)
            if dropped:
                user_rows += hold_freed_rows_extraction(pv, tau_cell, idx, status, tgt, X, M, held_basic, cols_all, dropped, pv_presmear,
                                                        caps=user_caps, totals=totals)
    elif hold_extraction:
        fdtot0 = {'p': targets_fd['C'], 'g': targets_fd['G'], 'i': targets_fd['I']}
        prior_col = pv['dom'][:, :n].sum(axis=0) + pv['imp'][:, :n].sum(axis=0) + np.maximum(vapr, 0.0)
        totals = np.array([(tgt[j] / pi[j] if np.isfinite(tgt[j]) else prior_col[j]) if j < n else fdtot0[cols_all[j]] for j in range(len(cols_all))])
        user_rows = hold_energy_users(pv, tau_cell, idx, status, tgt, X, M, held_basic, cols_all, caps=user_caps, totals=totals,
                                      only={idx[c] for c in EXTRACTION if c in idx and status.get(c) not in ('zero_target', 'none')},
                                      base=pv_presmear)
    # ------------------------------------------------------------------ problem
    rows = [f'MC_{c}' for c in sectors] + [f'IM_{c}' for c in sectors]
    d = np.concatenate([X, -M])
    columns = []
    fdtot = {'p': targets_fd['C'], 'g': targets_fd['G'], 'i': targets_fd['I']}
    held_own = own_use_held(sectors, choices.get('own_use_share', 'cross_entropy_free'))
    for j, a in enumerate(cols_all):
        rws, cf, pr, fb = [], [], [], []
        for i in range(n):
            for kind, off in (('dom', 0), ('imp', n)):
                rws.append(off + i)
                cf.append(1.0 / tau_cell[i, j])
                h = held_basic.get((kind, i, j))
                pr.append(0.0 if h is not None else max(pv[kind][i, j], 0.0))
                fb.append(h if h is not None else 0.0)
        if j < n:
            rws.append(-1); cf.append(0.0); pr.append(max(vapr[j], 0.0)); fb.append(0.0)
            st = status[a]
            if st in ('zero_target', 'none'):
                total = 0.0
                pr = [0.0] * len(pr)
            elif np.isfinite(tgt[j]):
                total = tgt[j] / pi[j]
            else:
                total = None
            grp = own_use_groups(n, j) if (a in held_own or a in hold_own) and pr[2 * j] + pr[2 * j + 1] > 0 else None
            if hold_extraction and a in EXTRACTION:
                grp = extraction_ely_groups(sectors, j, grp, pr)
            columns.append(Column(a, rws, cf, pr, fixed=fixed_va[j], total=total, own_row=j, own_coef=-pi[j], groups=grp,
                                  fixed_basic=[0.0] * len(pr) if st in ('zero_target', 'none') else fb))
        else:
            grp = investment_con_groups(n, idx, pr) if a == 'i' and choices.get('investment_con_share') == INVESTMENT_CON_SHARE else None
            columns.append(Column(a, rws, cf, pr, total=fdtot[a], fixed_basic=fb, groups=grp))
    P = Problem(rows, d, columns)
    info = dict(tau=tau, tau_tls=tau_tls, tau_cell=tau_cell, tau_tls_cell=tau_tls_cell, tau_tls_nosub=tau_tls_nosub, fuel=fuel, placed=placed, pi=pi, status=status, notes=notes, smears=smears, X=X, M=M, tgt=tgt, out0=out0, va0=va, energy_caps=cap_rows,
                evfp0=evfp, bad_tau=bad_tau, pse_in=pse_in, pse_out=pse_out, pse_items=pse_items, own_caps=own_cap_rows, basic0=basic, tls0=tls, pv0=pv, pv_presmear=pv_presmear, io12_gap=io12_gap,
                vapr=vapr, fixed_va=fixed_va, otax0=otax, power_cells=power_rows, energy_users=user_rows, vat=vat_info,
                ptax=dict(hold=choices.get('product_tax_totals') == PTAX_HOLD and not (ptax_src and ptax_src.get('mode') == 'rates'),
                          target=gen_target, prior=ptax_prior, general=general,
                          general_nosub=general_nosub, general0=general.copy(), source=ptax_src))
    return P, info


PTAX_HOLD = 'general_part_money_held_by_column_rates_rescaled_after_each_fit_pass'
PSE_IEA_NET = 'farm_part_of_the_iea_electricity_subsidy_netted_off_the_pse_ely_remainder'
# beta v4 G11 (Grok QA B9; S16 2026-10-26, decision package): the PSE farm-power support and the IEA electricity subsidy are
# the same money (Chepeliev et al. 2018 p.88), so the PSE electricity remainder is netted against the whole IEA amount,
# at most the smaller of the two (India: PSE 13.07 bn, IEA 18.05 bn)
PSE_IEA_NET_FULL = 'pse_ely_remainder_netted_against_the_whole_iea_electricity_subsidy_at_most_the_smaller'
ELY_SUBSIDY_HOLD = 's11_money_held_through_the_fit_rate_reset_after_each_pass'
PTAX_TOL, PTAX_PASSES, PTAX_K_MAX = 1e-9, 1000, 1e6   # passes: KWT ely subsidy money needs 390 (final round 2026-10-25)
PTAX_SCALE_BOUND = 2.0      # a column's general rates move by at most this factor (or its inverse) from the io_s12 pattern


def ptax_money(pv, tau, gen, k):
    """General product-tax money of a column at purchasers' values pv kept when its general rates gen are scaled by k."""
    live = (pv > 0) & (gen != 0)
    return float((pv[live] * k * gen[live] / (tau[live] + (k - 1.0) * gen[live])).sum())


def ptax_scale(pv, tau, gen, target, tol=1e-13, maxit=60):
    """The factor k on a column's general rates (gen) that gives general money = target at purchasers' values pv kept:
    sum_i pv_i k gen_i / (tau_i + (k - 1) gen_i) = target (Newton from k = 1; the cell powers stay positive).
    Returns k, or None where it cannot be met (no general base, opposite signs, or a power at or below 0)."""
    live = (pv > 0) & (gen != 0)
    if not live.any():
        return None if abs(target) > 1e-9 else 1.0
    p, t, g = pv[live], tau[live], gen[live]
    k = 1.0
    f = np.inf
    for _ in range(maxit):
        d = t + (k - 1.0) * g
        if (d <= 0).any():
            return None
        f = float((p * k * g / d).sum()) - target
        if abs(f) <= tol * max(1.0, abs(target)):
            return k
        with np.errstate(over='ignore', invalid='ignore'):
            df = float((p * g * (t - g) / d ** 2).sum())
        if df == 0 or not np.isfinite(df):
            return None
        k_new = k - f / df
        if not np.isfinite(k_new) or k_new > PTAX_K_MAX:
            return None
        if k_new <= 0:
            k_new = k / 2.0
        k = k_new
    return k if abs(f) <= 1e-9 * max(1.0, abs(target)) else None


def ptax_plan(pvs, taus, gens, target, scale, clamped, bound=PTAX_SCALE_BOUND, rep=None):
    """One pass of the product-tax hold at purchasers' values kept. pvs, taus, gens: per column arrays; target: the
    io_s12 general money by column; scale: each column's cumulative scale on its general rates so far; clamped
    {column index: 'up', 'down' or 'no base'}: columns held at their bound (sticky across passes). A column whose
    (effective) target needs a cumulative scale outside [1 / bound, bound], or cannot be met with positive powers, is
    put at the bound ('no base': kept as it is) and the money it cannot carry is shared by the region's other columns in
    proportion to their |target|, so the region's general money stays at its io_s12 total. When every column is at its
    bound, one region factor moves the columns of the gap's sign, each within its bound too (round-3 final QA2 item 4),
    and what none can carry is dropped: rep (a dict, optional) gets 'dropped', USD m (target total less the money held).
    Returns (k: this pass's factor by column, eff: the effective targets, clamped)."""
    J = len(target)
    clamped = dict(clamped)

    def k_at(j):
        return {'up': bound / scale[j], 'down': 1.0 / (bound * scale[j])}.get(clamped[j], 1.0)
    while True:
        k = np.ones(J)
        pool = 0.0
        for j in clamped:
            k[j] = k_at(j)
            pool += target[j] - ptax_money(pvs[j], taus[j], gens[j], k[j])
        free = [j for j in range(J) if j not in clamped]
        W = float(sum(abs(target[j]) for j in free))
        eff = np.array(target, float).copy()
        if W > 0:
            for j in free:
                eff[j] = target[j] + pool * abs(target[j]) / W
        new = False
        for j in free:
            live = bool(((pvs[j] > 0) & (gens[j] != 0)).any())
            if not live:
                if abs(eff[j]) > 1e-9:
                    clamped[j], new = 'no base', True
                continue
            kj = ptax_scale(pvs[j], taus[j], gens[j], eff[j])
            lo, hi = 1.0 / (bound * scale[j]), bound / scale[j]
            if kj is None or kj > hi:
                # no positive solution: the target asks for more than the base can carry at positive powers (or the
                # opposite sign); the bound in the direction of the target
                up = (eff[j] - ptax_money(pvs[j], taus[j], gens[j], 1.0)) * np.sign(ptax_money(pvs[j], taus[j], gens[j], 1.0) or 1.0) > 0
                clamped[j], new = ('up' if (kj is not None or up) else 'down'), True
                continue
            if kj < lo:
                clamped[j], new = 'down', True
                continue
            k[j] = kj
        if not new:
            break
    # every column at its bound (or the free ones without io_s12 money) and the region still off its total: one common
    # factor c on the general rates of the columns whose money has the sign of the gap (all columns if none has), each
    # column's cumulative scale still within [1 / bound, bound] (round-3 final QA2 item 4: the fallback is bounded as the
    # columns are, so no column, a subsidy column above all, is scaled beyond 2x); what no column can carry at its bound
    # is dropped (rep['dropped'], ledgered by S13 as PTAX-DROPPED)
    tot = float(np.sum(target))
    got = sum(ptax_money(pvs[j], taus[j], gens[j], k[j]) for j in range(J))
    dropped = 0.0
    if abs(got - tot) > 1e-10 * max(1.0, abs(tot)) and not any(j not in clamped and abs(target[j]) > 0 for j in range(J)):
        m = np.array([ptax_money(pvs[j], taus[j], gens[j], k[j]) for j in range(J)])
        livej = np.array([bool(((pvs[j] > 0) & (gens[j] != 0)).any()) for j in range(J)])
        sel = (np.sign(m) == np.sign(tot - got)) & livej
        if not sel.any():
            sel = livej.copy()
        lo_j = np.array([1.0 / (bound * scale[j]) for j in range(J)])
        hi_j = np.array([bound / scale[j] for j in range(J)])

        def kk(c):
            return np.where(sel, np.clip(k * c, lo_j, hi_j), k)

        def total(c):
            kc = kk(c)
            s_ = 0.0
            for j in range(J):
                live = (pvs[j] > 0) & (gens[j] != 0)
                if (taus[j][live] + (kc[j] - 1.0) * gens[j][live] <= 0).any():
                    return np.nan                  # a cell power at or below 0
                s_ += ptax_money(pvs[j], taus[j], gens[j], kc[j])
            return s_ - tot
        if sel.any():
            kp = np.where(k[sel] > 0, k[sel], 1.0)
            c_lo, c_hi = min(1.0, float((lo_j[sel] / kp).min())), max(1.0, float((hi_j[sel] / kp).max()))
            ends = []
            for c_end in (c_lo, c_hi):
                f_end = total(c_end)
                for _ in range(60):                # a power at or below 0 at the end: move the end towards c = 1
                    if np.isfinite(f_end):
                        break
                    c_end = np.sqrt(c_end)
                    f_end = total(c_end)
                ends.append((c_end, f_end))
            (a_, fa), (b_, fb) = ends
            if np.isfinite(fa) and np.isfinite(fb) and (fa > 0) != (fb > 0):
                la, lb = np.log(a_), np.log(b_)
                for _ in range(200):
                    mid = 0.5 * (la + lb)
                    fm = total(np.exp(mid))
                    if not np.isfinite(fm):
                        break
                    if (fm > 0) == (fa > 0):
                        la, fa = mid, fm
                    else:
                        lb = mid
                    if lb - la <= 1e-15:
                        break
                c = float(np.exp(0.5 * (la + lb)))
            else:
                fins = [(abs(f_), c_) for c_, f_ in ends if np.isfinite(f_)]
                c = min(fins)[1] if fins else 1.0
            k = kk(c)
            for j in range(J):
                if sel[j]:
                    clamped[j] = clamped.get(j, 'region scale') if clamped.get(j) != 'no base' else 'no base'
            eff = np.array([ptax_money(pvs[j], taus[j], gens[j], k[j]) for j in range(J)])
        dropped = tot - float(sum(ptax_money(pvs[j], taus[j], gens[j], k[j]) for j in range(J)))
        if abs(dropped) <= 1e-10 * max(1.0, abs(tot)):
            dropped = 0.0
    if rep is not None:
        rep['dropped'] = dropped
    return k, eff, clamped


def hold_product_taxes(P, R, info, sectors, log=None):
    """s13 choice product_tax_totals (round-3 QA item 3; GTAP 12 ch.8 Appendix A and ch.15: tax revenue held at the
    reported total). After a fit pass, the general part of every column's cell rates (the rate less its energy-tax rate;
    VAT and excise layers and the non_energy_rates pattern) is scaled by one factor per column so that its money on the
    fitted purchases equals info['ptax']['target'], the general money on the io_s12 flows; the energy-tax rates, the fuel
    subsidy rate rho and the PSE input rates stay. A column whose rates would move by more than PTAX_SCALE_BOUND (a
    column the fit shrank or grew many times) stays at the bound and the region's other columns carry what it cannot
    (ptax_plan), so the region's general money is held in any case. The fit is solved again with the new powers
    (warm start), until every column holds its effective target (PTAX_TOL) or PTAX_PASSES passes. In place on info
    (tau_cell, tau_tls_cell, tau_tls_nosub, ptax) and on the Problem's coefficients. Returns (R, report dict)."""
    n = len(sectors)
    pt = info['ptax']
    tau_c, tau_t, tau_ns = info['tau_cell'], info['tau_tls_cell'], info['tau_tls_nosub']
    gen, gen_ns, target = pt['general'], pt['general_nosub'], pt['target']
    cols = {c.name: c for c in P.columns}
    names = list(sectors) + list(FD)
    J = len(names)
    scale = np.ones(J)
    clamped = {}
    free_fit, eff = None, np.array(target, float).copy()
    passes = 0

    def column_pv(R_, a):
        v = R_['vals'][a]
        return v[0:2 * n:2] + v[1:2 * n:2]

    hold_pt = bool(pt.get('hold'))
    held_fuel = {c: f for c, f in info.get('fuel', {}).items() if f.get('status') == 'booked' and f.get('money_held')}
    idx = {c: i for i, c in enumerate(sectors)}
    plan = dict(dropped=0.0)
    for passes in range(1, PTAX_PASSES + 1):
        pvs = [column_pv(R, a) for a in names]
        moved = False
        # s13 choice electricity_subsidy_money: the subsidy money on a good not held by S11 (electricity) is held at the
        # S11 amount S on the fitted purchases (purchasers' values kept): rho_new / (1 - rho_new) A = S, A the purchases
        # at the cell powers without the subsidy, so rho_new = S / (A + S); every subsidised cell's power is tau_nosub (1 - rho_new)
        touched = set()
        for c, f in held_fuel.items():
            smask = f['mask']          # the good's subsidised columns (fuel_subsidy_users)
            sj = np.flatnonzero(smask)
            i, S_, rho = idx[c], f['subsidy_musd'], f['rho']
            A = float(sum(pvs[j][i] * (1.0 - rho) / tau_c[i, j] for j in sj))
            if abs(rho / (1.0 - rho) * A - S_) <= PTAX_TOL * max(1.0, S_) or A <= 0:
                continue
            rho_new = S_ / (A + S_)
            if f.get('rho_max') is not None and rho_new > f['rho_max']:
                rho_new = f['rho_max']          # the cap holds through the fit; the money above it is reported as capped
                f['capped_musd'] = f.get('capped_musd', 0.0) + S_ - rho_new / (1.0 - rho_new) * A
                f['capped_fit_musd'] = f.get('capped_fit_musd', 0.0) + S_ - rho_new / (1.0 - rho_new) * A
                f['subsidy_musd'] = rho_new / (1.0 - rho_new) * A
            q = (1.0 - rho_new) / (1.0 - rho)
            tau_c[i, smask] *= q
            tau_t[i, smask] *= q
            gen[i, smask] = gen_ns[i, smask] * (1.0 - rho_new)
            f['rho'] = rho_new
            touched.update(sj.tolist())
            moved = True
        for j in touched:
            col = cols[names[j]]
            col.coefs[0:2 * n:2] = 1.0 / tau_c[:, j]
            col.coefs[1:2 * n:2] = 1.0 / tau_c[:, j]
        cur = np.array([float((pvs[j] * gen[:, j] / tau_c[:, j]).sum()) for j in range(J)])
        if free_fit is None:
            free_fit = cur.copy()
        if hold_pt:
            k, eff, clamped = ptax_plan(pvs, [tau_c[:, j] for j in range(J)], [gen[:, j] for j in range(J)], target, scale, clamped, rep=plan)
        else:
            k = np.ones(J)
        for j, a in enumerate(names):
            if abs(k[j] - 1.0) <= 1e-12:
                continue
            if j not in clamped and abs(cur[j] - eff[j]) <= PTAX_TOL * max(1.0, abs(eff[j])):
                continue
            d = (k[j] - 1.0) * gen[:, j]
            if (tau_c[:, j] + d <= 0).any() or (tau_t[:, j] + d <= 0).any():
                clamped[j] = 'no base'          # a cell power would reach 0: the column keeps its rates
                continue
            tau_c[:, j] += d
            tau_t[:, j] += d
            tau_ns[:, j] += (k[j] - 1.0) * gen_ns[:, j]
            gen[:, j] *= k[j]
            gen_ns[:, j] *= k[j]
            scale[j] *= k[j]
            col = cols[a]
            col.coefs[0:2 * n:2] = 1.0 / tau_c[:, j]
            col.coefs[1:2 * n:2] = 1.0 / tau_c[:, j]
            moved = True
        if not moved:
            break
        R = solve(P, log=log, start=(R['lam'], R['lnE']))
        if not R['ok']:
            break
    final = np.array([float((column_pv(R, a) * gen[:, j] / tau_c[:, j]).sum()) for j, a in enumerate(names)])
    return R, dict(passes=passes, free_fit=free_fit, final=final, effective=eff, scale=scale, dropped=float(plan['dropped']),
                   unheld={names[j]: why for j, why in clamped.items()})


def fit_region(P, info, sectors, log=None):
    R = solve(P, log=log)
    if R['ok'] and (info.get('ptax', {}).get('hold') or any(f.get('money_held') and f.get('status') == 'booked'
                                                                for f in info.get('fuel', {}).values())):
        R, rep = hold_product_taxes(P, R, info, sectors, log=log)
        info['ptax']['report'] = rep
    n = len(sectors)
    cols_all = list(sectors) + list(FD)
    dom = np.zeros((n, len(cols_all)))
    imp = np.zeros((n, len(cols_all)))
    tax = np.zeros(len(cols_all))
    va = np.zeros(n)
    for j, a in enumerate(cols_all):
        v = R['vals'][a]
        dv, iv = v[0:2 * n:2], v[1:2 * n:2]
        tc = info['tau_cell'][:, j]
        dom[:, j] = dv / tc
        imp[:, j] = iv / tc
        tax[j] = float((dv * (1 - 1 / tc)).sum() + (iv * (1 - 1 / tc)).sum())
        if j < n:
            va[j] = v[-1] + info['fixed_va'][j]
    R['dom'], R['imp'], R['tax'], R['va'] = dom, imp, tax, va
    R['cost'] = dom.sum(axis=0)[:n] + imp.sum(axis=0)[:n] + tax[:n] + va
    R['out'] = R['cost'] * info['pi']
    R['I'] = information(P, R['vals'], R['tots'])
    return R


# ------------------------------------------------------------------ fitted table
def world_composition(evfp12, sectors):
    """Sector factor shares over all regions' positive-VA cells (a new activity's composition, config
    new_activity_factors). evfp12: region, sector, factor, evfp (S12)."""
    e = evfp12.copy()
    va = e.groupby(['region', 'sector'])['evfp'].transform('sum')
    e = e[va > 0]
    w = e.groupby(['sector', 'factor'])['evfp'].sum()
    t = w.groupby(level=0).transform('sum')
    sh = (w / t).unstack().reindex(index=list(sectors), columns=list(FACTORS)).fillna(0.0)
    return sh


def region_table(region, R, info, sectors, trade_r, evfp12_r, world_sh):
    """io_s13 rows of one region from the fit. evfp12_r: S12 EVFP, factors x sectors (array).
    Returns (DataFrame in the io_s13 layout, composition source per sector)."""
    n = len(sectors)
    cols_all = list(sectors) + list(FD)
    dom, imp = R['dom'], R['imp']
    basic = dom + imp
    tls = (basic * (info['tau_tls_cell'] - 1.0)).sum(axis=0)
    pse = (basic * (info['tau_cell'] - info['tau_tls_cell'])).sum(axis=0)
    va = R['va']
    va12 = evfp12_r.sum(axis=0)
    evfp = np.zeros((len(FACTORS), n))
    comp = {}
    for j, c in enumerate(sectors):
        if info['fixed_va'][j] != 0:
            evfp[:, j] = evfp12_r[:, j]          # held negative VA: the S12 cells as they are
            comp[c] = 'held'
        elif va12[j] > 0:
            evfp[:, j] = va[j] * evfp12_r[:, j] / va12[j]
            comp[c] = 's12'
        elif va[j] != 0:
            evfp[:, j] = va[j] * world_sh.loc[c].to_numpy()
            comp[c] = 'world'
        else:
            comp[c] = 'none'
    out = R['out']
    cost = R['cost']
    ptax = out - cost
    X = np.array([trade_r.get(('X', c), 0.0) for c in sectors])
    VST = np.array([trade_r.get(('VST', c), 0.0) for c in sectors])
    M = np.array([trade_r.get(('M', c), 0.0) for c in sectors])
    rows = []
    z3 = np.zeros(len(FD))
    for i, c in enumerate(sectors):
        rows.append([f'dom_{c}', *dom[i], X[i], VST[i], 0.0, out[i]])
    for i, c in enumerate(sectors):
        rows.append([f'imp_{c}', *imp[i], 0.0, 0.0, M[i], 0.0])
    rows.append(['TLS', *tls, 0.0, 0.0, 0.0, 0.0])
    rows.append(['PSE_input', *pse, 0.0, 0.0, 0.0, 0.0])
    for k, f in enumerate(FACTORS):
        rows.append([f'EVFP_{f}', *evfp[k], *z3, 0.0, 0.0, 0.0, 0.0])
    rows.append(['PTAX', *ptax, *z3, 0.0, 0.0, 0.0, 0.0])
    rows.append(['OUT', *out, *z3, 0.0, 0.0, 0.0, 0.0])
    df = pd.DataFrame(rows, columns=['row'] + cols_all + ['X', 'VST', 'M', 'OUT'])
    df.insert(0, 'region', region)
    return df, comp


def negative_surplus(region, R, info, sectors, trade_r, evfp12_r, world_sh, fac12, hold_money=False, tol=1e-6):
    """Factor cells of one region's fit whose operating surplus (EVOS = EVFP - ftax - itax, factor_table) is negative
    (GTAP 12 ch.17B p.3: no sign violation). fix round wG: a second-pass own-use refit is kept only if it adds none."""
    tab, _ = region_table(region, R, info, sectors, trade_r, evfp12_r, world_sh)
    f = factor_table(tab, fac12[fac12['region'] == region], sectors, hold_money=hold_money)
    return sorted(f'{x.sector} {x.factor}' for x in f[f['evos'] < -tol].itertuples())


EVOS_FLOOR_SHARE = 0.01   # a capped cell keeps 1% of its payment as operating surplus (S14-Hfactors: EVOS > 0 when EVFB > 0)
HELD_RATE_MAX = 0.5       # our choice (fix round S16, Fable QA C-07): the held-money scaling never takes a cell's tax above half its payment unless S12's own rate is higher


def cap_held_factor_taxes(m, reg, passes=50, ceiling=None):
    """Held factor-tax money (factor_tax_totals) on a cell whose fitted EVFP shrank can exceed the payment and leave
    EVOS < 0 (GTAP 12 ch.17B p.3: no sign violation). A cell's positive taxes (ftax + itax, with fbep scaled with
    itax) are capped at (1 - EVOS_FLOOR_SHARE) of its EVFP, and the money above the cap moves to the other cells of the same region and
    factor in proportion to their taxes, so the S12 total still holds while there is room; what no cell can carry
    is dropped (the S13 factor-money report shows the shortfall). ceiling (fix round S16, Fable QA C-07): a tax share
    of EVFP per cell, below (1 - EVOS_FLOOR_SHARE), that caps it instead (LBY crp land had EVOS at 2% of its payment)."""
    m = m.copy()
    share = (1.0 - EVOS_FLOOR_SHARE) if ceiling is None else np.minimum(1.0 - EVOS_FLOOR_SHARE, np.asarray(ceiling, float))
    for _ in range(passes):
        tax = m['ftax'] + m['itax']
        cap = share * m['evfp']
        over = (tax > cap * (1 + 1e-12)) & (tax > 1e-12)
        if not over.any():
            break
        s_ = np.where(over, cap / tax.where(over, 1.0), 1.0)
        for c in ('ftax', 'itax', 'fbep'):
            m[c] = m[c] * s_
        for c in ('ftax', 'itax', 'fbep'):
            want = pd.MultiIndex.from_frame(m[['region', 'factor']]).map(reg[c]).to_numpy(float)
            want = np.nan_to_num(want)
            free = ~over
            got_cap = m[c].where(over, 0.0).groupby([m['region'], m['factor']]).transform('sum')
            got_free = m[c].where(free, 0.0).groupby([m['region'], m['factor']]).transform('sum')
            ok = free & (np.abs(got_free) > 1e-9)
            k = np.where(ok, (want - got_cap) / np.where(np.abs(got_free) > 1e-9, got_free, 1.0), 1.0)
            # only scale up toward the held total, never flip a sign
            k = np.where(k > 0, k, 1.0)
            m[c] = m[c] * k
    tax = m['ftax'] + m['itax']
    cap = share * m['evfp']
    over = (tax > cap * (1 + 1e-12)) & (tax > 1e-12)
    if over.any():
        s_ = np.where(over, cap / tax.where(over, 1.0), 1.0)
        for c in ('ftax', 'itax', 'fbep'):
            m[c] = m[c] * s_
    return m


def factor_table(io13, fac12, sectors, hold_money=False):
    """factors_s13: the io_s13 EVFP cells with S12's factor taxes scaled by the EVFP ratio of each cell; a cell
    with no S12 EVFP (new activity) takes its region's average ftax/EVFP and itax/EVFB of that factor.
    hold_money (choice factor_tax_totals, GTAP 12 ch.15: the taxes are revenue / GDP x GDP, a money amount, and
    the S02 GDP is the fit's target): then ftax, itax and fbep are scaled again, by region and factor, so each
    total equals S12's (the cell pattern stays the EVFP-ratio one)."""
    e = io13[io13['row'].str.startswith('EVFP_')].melt(id_vars=['region', 'row'], value_vars=list(sectors),
                                                         var_name='sector', value_name='evfp')
    e['factor'] = e['row'].str[5:]
    e = e.drop(columns='row')
    f12 = fac12.rename(columns={c: c + '12' for c in ('evfp', 'ftax', 'evfb', 'itax', 'fbep', 'evos')})
    m = e.merge(f12, on=['region', 'sector', 'factor'], how='left').fillna(0.0)
    reg = fac12.groupby(['region', 'factor'])[['evfp', 'ftax', 'evfb', 'itax', 'fbep']].sum()
    has = m['evfp12'] != 0
    ratio = np.where(has, m['evfp'] / m['evfp12'].where(has, 1.0), 0.0)
    m['ftax'] = np.where(has, m['ftax12'] * ratio, 0.0)
    m['itax'] = np.where(has, m['itax12'] * ratio, 0.0)
    m['fbep'] = np.where(has, m['fbep12'] * ratio, 0.0)
    new = (~has) & (m['evfp'] != 0)
    for k in np.where(new)[0]:
        r, f = m.at[k, 'region'], m.at[k, 'factor']
        t = reg.loc[(r, f)] if (r, f) in reg.index else None
        rf = t['ftax'] / t['evfp'] if t is not None and t['evfp'] != 0 else 0.0
        ri = t['itax'] / t['evfb'] if t is not None and t['evfb'] != 0 else 0.0
        rb = t['fbep'] / t['evfb'] if t is not None and t['evfb'] != 0 else 0.0
        m.at[k, 'ftax'] = m.at[k, 'evfp'] * rf
        evfb = m.at[k, 'evfp'] - m.at[k, 'ftax']
        m.at[k, 'itax'] = evfb * ri
        m.at[k, 'fbep'] = evfb * rb
    if hold_money:
        # the cell's own rate before the held totals are imposed (the S12 rate, or the region average for a new cell)
        rate0 = np.where(m['evfp'] > 0, (m['ftax'] + m['itax']) / m['evfp'].where(m['evfp'] > 0, 1.0), 0.0)
        for c in ('ftax', 'itax', 'fbep'):
            got = m.groupby(['region', 'factor'])[c].transform('sum')
            want = pd.MultiIndex.from_frame(m[['region', 'factor']]).map(reg[c]).to_numpy(float)
            want = np.nan_to_num(want)
            k = np.where(np.abs(got) > 1e-9, want / np.where(np.abs(got) > 1e-9, got, 1.0), 1.0)
            m[c] = m[c] * k
        m = cap_held_factor_taxes(m, reg, ceiling=np.maximum(HELD_RATE_MAX, rate0))
    m['evfb'] = m['evfp'] - m['ftax']
    m['evos'] = m['evfb'] - m['itax']
    m['composition'] = np.where(has, 's12', np.where(new, 'world_sector_region_rates', 'zero'))
    return m[['region', 'sector', 'factor', 'evfp', 'ftax', 'evfb', 'itax', 'fbep', 'evos', 'composition']]
