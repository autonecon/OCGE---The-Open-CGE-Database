"""Domestic basic prices (GTAP 12 ch.12 §12.3.4-12.3.8; David 2026-10-23 19:12 UTC+7: source domestic prices).

Order, per commodity and region:
1. source data: a basic or wholesale price observed in the region (§12.3.4): EI gas hubs, Eurostat non-household
   prices excluding taxes, EIA US coal and electricity (config/s11/domestic_price_sources.csv);
2. IEA price gap: the region's trade-parity price less the IEA 2022 consumption subsidy per unit
   (subsidy / consumption volume), for the regions the IEA price-gap database covers (§12.3.6);
3. import basic price: net importers at CIF x (1 + duty) per unit of the new trade (§12.3.5, eq.1), for coal,
   crude, gas and products; it ranks ahead of a purchasers'-price source (§12.3.8; David 2026-10-23 20:13);
4. otherwise the simple average of the regions with an observation 1-3, within the GTAP fill class
   (net energy exporter or importer, prices above or below average; §12.3.6), else over all (§12.3.8).
Purchasers' prices from source data become basic prices by eq.(2) with the Table 12.8 margin rates.
Source data include transcribed 2022 producer prices where the price is regulated (config/s11/
transcribed_prices_2022.csv, fix-round item A9: Urals, Russian regulated gas, Saudi methane, Indian pit-head coal).

Two rules follow the order (fix-round A9; our choice in the spirit of §12.3.4 and §12.3.6; each can be
switched off in s11_choices.csv):
5. lignite: in a region with no coal source price of its own, the brown-coal share of coal output (UNSD 2022,
   0200 over 0100 + 0200 production) is priced at the US lignite mine price (EIA ACR 2022 table 31);
6. exporter cap: a net exporter's domestic price of coal, crude, gas or products is at most its own export
   price (export parity), except where the price is source data.

Fossil-fuel consumption subsidies (fix-round B15, David's card 2026-10-24; Chepeliev, McDougall and van der
Mensbrugghe 2018, JGEA 3(1) §3, used by GTAP 12 ch.3 §3.2.4): with book_subsidy, a region priced by rule 2 takes the
reference (trade-parity) price as its domestic basic price, and the gap (reference less the IEA end-user price) is a
consumption subsidy (fuel_subsidy_rows), which S13 books as a negative purchase tax with the tax-paid value kept.
Extension (David 2026-10-24, "stick to GTAP"): every other row with an IEA subsidy (A9 regulated source prices such as
RUS and SAU gas, rows whose gap was not used or had no consumption volume, e.g. IRN) books the IEA value harmonised
with our volumes (the paper's steps 1-2): its S11 price is the consumer price and the market price is consumer price +
subsidy per unit (PM1 = PM0 + VS/ED; apply_subsidy_prices, suffix +iea_subsidy, after rules 5 and 6).
Fix round wA (independent QA HIGH-1; Chepeliev et al. §2.1, step 2): the subsidy is a gap below the reference. Only an
observed price (rule 1, source data) is a subsidised consumer price PM0, so only there is the rate added on top of it, and
then at most up to the reference; a price that is not observed (the class-average fill, the import basic price) is
unsubsidised, so the market price is the reference and the consumer price is reference - rate; the rate is at most the
reference on every row; the electricity reference is at least the lowest observed electricity basic price
(fix round wA, since replaced). Fix round wA2 (coordinator 2026-10-24): electricity has no trade-parity
reference, so its IEA reference is IEA's implied supply cost, consumer price + IEA rate (no cap, no gap pricing by rule 2);
the consumer price is the observed S11 price, else a sourced 2022 end-user tariff (config/s11/electricity_tariffs_2022.csv),
else the income-group average of those tariffs (electricity_consumer_prices); an unobserved traded-fuel rate is at most 99% of
the reference, so every consumer price is positive. The w10 rule (the S11 price + the rate everywhere) is the add-on-top alternative.
With the gap-rows-only value only the rule-2 rows are booked; with 'off' the gap lowers the basic price and nothing is
booked (the pre-B15 rule).
"""
import numpy as np

from .sources import COMMODITIES

RULES = ('source_data', 'iea_price_gap', 'import_basic_price', 'simple_average', 'regulated_average')
# rules 5 and 6 add a suffix to the rule of the order (rule.split('+')[0] is always one of RULES)
LIGNITE_SUFFIX, CAP_SUFFIX = '+lignite', '+export_cap'
EXPORT_CAP_COMMODITIES = ('coa', 'oil', 'gas', 'pet')   # electricity export unit values are not export parity prices
# §12.3.5: import-price-based basic prices exist for coal, crude, gas (IEA) and oil products (OLADE), not electricity
IMPORT_PRICE_COMMODITIES = ('coa', 'oil', 'gas', 'pet')
GJ_PER_BCM = 40.0e6        # PREP gas volume basis: EI gas sheets standardise at a GCV of 40 MJ/m3
GJ_PER_MMBTU = 1.055056    # 1 Btu = 1.055056 kJ
T_PER_SHORT_TON = 0.90718474
# GTAP 12 ch.12 Table 12.8, industrial use (countries other than the US and Japan); gas fixed at 1.3 in the text
MARGIN_INDUSTRIAL = {'coa': 0.57, 'oil': 0.03, 'gas': 1.30, 'ely': 0.0}   # coa: steaming coal; pet has no single row


def usd_mmbtu_to_musd_bcm(p):
    return p * GJ_PER_BCM / GJ_PER_MMBTU / 1e6


def usd_gj_to_musd_bcm(p):
    return p * GJ_PER_BCM / 1e6


def usd_kwh_to_usd_mwh(p):
    return p * 1000.0


def usd_short_ton_to_usd_t(p):
    return p / T_PER_SHORT_TON


TRANSCRIBED_UNITS = {'USD/bbl': ('oil', 'pet'), 'USD/MMBtu': ('gas',), 'USD/t': ('coa',), 'LCU/t': ('coa',),
                     'USD million': ('gas',), 'bcm': ('gas',),
                     # Fable QA C-02/B-03/B-08 (2026-10-25): sourced 2022 regulated gas and electricity prices
                     'LCU/MMBtu': ('gas',), 'USD/GJ': ('gas',), 'USD/kcm': ('gas',), 'LCU/kcm': ('gas',),
                     'USD/MWh': ('ely',), 'LCU/MWh': ('ely',), 'LCU/kWh': ('ely',)}
# unit -> (to the S11 price unit before the exchange rate, text); a kcm is a thousand m3 at the PREP volume basis, so
# USD per kcm is USD million per bcm
TRANSCRIBED_CONVERSIONS = {'USD/MMBtu': (usd_mmbtu_to_musd_bcm, 'at 40 PJ per bcm'), 'LCU/MMBtu': (usd_mmbtu_to_musd_bcm, 'at 40 PJ per bcm'),
                           'USD/GJ': (usd_gj_to_musd_bcm, 'at 40 PJ per bcm'), 'USD/kcm': (lambda v: v, '(USD per kcm = USD million per bcm)'),
                           'LCU/kcm': (lambda v: v, '(per kcm = million per bcm)'), 'LCU/t': (lambda v: v, ''),
                           'USD/MWh': (lambda v: v, ''), 'LCU/MWh': (lambda v: v, ''), 'LCU/kWh': (usd_kwh_to_usd_mwh, 'x 1000 per MWh')}


def transcribed_price(commodity, series, items, fx):
    """A domestic price in S11 units (PRICE_UNIT) from transcribed items (config/s11/transcribed_prices_2022.csv).
    items: {item: row with value, unit, fx_iso3}; fx: {iso3: local currency per USD (WDI PA.NUS.FCRF 2022)}.
    series: 'item:<name>' (one price), or 'midpoint_value_over_volume:<low>;<high>:<volume>' (the mean of two
    values of the region's use, USD million, over that use in bcm). Returns (price, detail)."""
    kind, _, rest = series.partition(':')

    def get(name):
        if name not in items:
            raise SystemExit(f'transcribed_prices_2022.csv has no item {name!r}')
        it = items[name]
        if commodity not in TRANSCRIBED_UNITS.get(it['unit'], ()):
            raise SystemExit(f'transcribed item {name!r}: unit {it["unit"]!r} is not a {commodity} unit')
        return float(it['value']), it
    if kind == 'item':
        v, it = get(rest)
        u = it['unit']
        if u in ('USD/bbl', 'USD/t'):
            return v, f'{rest} {v:.4g} {u}'
        if u in TRANSCRIBED_CONVERSIONS:
            conv, how = TRANSCRIBED_CONVERSIONS[u]
            if not u.startswith('LCU/'):
                return conv(v), f'{rest} {v:.4g} {u} {how}'.rstrip()
            iso = it['fx_iso3']
            if iso not in fx:
                raise SystemExit(f'transcribed item {rest!r}: no exchange rate for {iso!r}')
            return (conv(v / fx[iso]), f'{rest} {v:.6g} {iso} currency {u[3:]} at {fx[iso]:.6g} per USD (WDI PA.NUS.FCRF {iso} 2022) '
                    f'{how}'.rstrip())
        raise SystemExit(f'transcribed item {rest!r}: unit {u!r} needs the midpoint_value_over_volume form')
    if kind == 'midpoint_value_over_volume':
        vals, vol = rest.split(':')
        lo, hi = vals.split(';')
        (a, ia), (b, ib), (q, iq) = get(lo), get(hi), get(vol)
        if (ia['unit'], ib['unit'], iq['unit']) != ('USD million', 'USD million', 'bcm') or not (0 < a <= b and q > 0):
            raise SystemExit(f'transcribed series {series!r}: needs two values in USD million (low <= high) and a volume in bcm')
        return (a + b) / 2.0 / q, f'midpoint of {lo} {a:.6g} and {hi} {b:.6g} USD million over {vol} {q:.4g} bcm'
    raise SystemExit(f'transcribed series {series!r}: unknown form {kind!r}')


def brown_coal_share(R, iso_region, production_kt):
    """Brown-coal share of coal output by region: UNSD 2022 production (transaction 01) of 0200 brown coal over
    0100 hard coal + 0200 brown coal, members of a composite region summed. production_kt: {(iso3, commodity
    code): thousand t}; iso_region: {iso3: region}. A region with no UNSD coal production gets 0."""
    hard, brown = {}, {}
    for (iso, code), kt in production_kt.items():
        r = iso_region.get(iso)
        if r is None or kt <= 0:
            continue
        d = brown if code == '0200' else hard
        d[r] = d.get(r, 0.0) + kt
    out = np.zeros(len(R))
    for i, r in enumerate(R):
        t = hard.get(r, 0.0) + brown.get(r, 0.0)
        if t > 0:
            out[i] = brown.get(r, 0.0) / t
    return out


def iea_gap_per_unit(R, regions_members, subsidy, consumption, deflator):
    """{(commodity, region): subsidy per unit}. subsidy: {(commodity, iso3): real-2024 USD m};
    consumption: {commodity: array over R} in S11 units; deflator: nominal 2022 / real 2024.
    A composite region carries its members' subsidies over the whole region's consumption."""
    out = {}
    for c in COMMODITIES:
        for i, r in enumerate(R):
            s = sum(subsidy.get((c, m), 0.0) for m in regions_members[r])
            q = consumption[c][i]
            if s > 0 and q > 0:
                out[(c, r)] = s * deflator / q
    return out


def basic_from_purchasers(pp, commodity):
    """GTAP 12 ch.12 eq.(2) with a known zero tax (prices excluding taxes): BP = PP / (1 + MR), MR the
    industrial margin rate of Table 12.8 (countries other than the US and Japan)."""
    return pp / (1.0 + MARGIN_INDUSTRIAL[commodity])


def price_class(R, observed):
    """+1 / -1 where a region's observed prices sit above / below the cross-region simple average
    (mean log ratio over the commodities it has), 0 where it has none (§12.3.6 fill classes)."""
    out = np.zeros(len(R), dtype=int)
    for i in range(len(R)):
        lr = [np.log(p[i] / np.nanmean(p)) for p in observed.values() if np.isfinite(p[i]) and p[i] > 0]
        if lr:
            out[i] = 1 if np.mean(lr) > 0 else -1
    return out


def contract_free_import_price(vmsb_c, vol_c, pxr_c, px_ref_c, contracts):
    """Beta v5 A (choice contract_routes_out_of_parity_cap): the import basic price by importer with each contract route
    (contracts: (i, j) pairs) valued at the exporter's reference price times the route's basic-over-FOB wedge, in place
    of the contract price. vmsb_c, vol_c, pxr_c: route basic values, volumes and FOB prices (n x n). Returns an array;
    NaN where the importer has no imports."""
    v = np.asarray(vmsb_c, float).copy()
    for i, j in contracts:
        fob = vol_c[i, j] * pxr_c[i, j]
        wedge = v[i, j] / fob if fob > 0 else 1.0
        v[i, j] = vol_c[i, j] * px_ref_c[i] * wedge
    mv = np.asarray(vol_c, float).sum(0)
    return np.divide(v.sum(0), mv, out=np.full(len(mv), np.nan), where=mv > 0)


def trade_parity_reference(px_c, pmb_c, xvol_c, mvol_c):
    """The IEA price-gap reference by region for one commodity (choice iea_gap_reference): the import basic price
    for a net importer, the export price for an exporter, and the exporters' simple average export price where the
    region has no trade in it (its own BACI unit value, if any, is not a trade price). Returns (price, basis) arrays."""
    n = len(px_c)
    net_imp = (mvol_c > 0) & (mvol_c > xvol_c)
    trade = xvol_c > 0
    px_avg = float(np.nanmean(px_c[trade])) if trade.any() else float(np.nanmean(px_c))
    ref = np.where(net_imp, pmb_c, np.where(trade, px_c, px_avg)).astype(float)
    basis = np.array(['import_basic_price' if net_imp[i] else 'export_price' if trade[i] else 'exporters_simple_average_export_price'
                      for i in range(n)], dtype=object)
    return ref, basis


COST_REFERENCE_COMMODITIES = ('ely',)    # fix round wA2: no trade-parity reference; the IEA reference is a supply cost
CONSUMER_FLOOR_SHARE = 0.01              # fix round wA2: a capped unobserved traded-fuel row keeps a consumer price of 1% of the reference


def electricity_consumer_prices(R, table, fx, observed=()):
    """Fix round wA2 (choice iea_reference_ely): the electricity end-user (consumer) price of each region in the tariff table
    (config/s11/electricity_tariffs_2022.csv), USD/MWh. table: rows with region, value, unit ('USD/MWh' or 'LCU/kWh'),
    fx_iso3, fx_lcu_per_usd, income_group, source; fx: {iso3: LCU per USD, WDI PA.NUS.FCRF 2022}. A row with a value is a
    sourced 2022 tariff; a row without one takes the simple average of the sourced tariffs of its income group (all
    sourced tariffs where the group has none). observed: regions whose S11 price is observed (left out: their own price is
    the consumer price). Returns {region: (price, basis, detail)}, basis 'end_user_tariff' or 'tariff_income_group_average'."""
    out, groups = {}, {}
    for t in table:
        r = t['region']
        if r in out:
            raise SystemExit(f'electricity_tariffs_2022.csv: two rows for {r}')
        if not str(t['value']).strip():
            out[r] = None
            continue
        v = float(t['value'])
        if t['unit'] == 'USD/MWh':
            p, d = v, f'{v:.4g} USD/MWh'
        elif t['unit'] == 'LCU/kWh':
            if str(t.get('fx_lcu_per_usd', '')).strip():
                k, ks = float(t['fx_lcu_per_usd']), 'the rate in the table'
            elif t['fx_iso3'] in fx:
                k, ks = float(fx[t['fx_iso3']]), f'WDI PA.NUS.FCRF {t["fx_iso3"]} 2022'
            else:
                raise SystemExit(f'electricity_tariffs_2022.csv: no exchange rate for {r}')
            p, d = v * 1000.0 / k, f'{v:.6g} LCU/kWh at {k:.6g} per USD ({ks})'
        else:
            raise SystemExit(f'electricity_tariffs_2022.csv: unknown unit {t["unit"]!r} for {r}')
        if not (np.isfinite(p) and p > 0):
            raise SystemExit(f'electricity_tariffs_2022.csv: tariff of {r} is not positive')
        out[r] = (p, 'end_user_tariff', f'{t["source"]}: {d} = {p:.4g} USD/MWh')
        groups.setdefault(t['income_group'], []).append(p)
    allv = [x for g in groups.values() for x in g]
    if not allv:
        raise SystemExit('electricity_tariffs_2022.csv: no sourced tariff')
    for t in table:
        r = t['region']
        if out[r] is None:
            g = groups.get(t['income_group']) or allv
            p = float(np.mean(g))
            out[r] = (p, 'tariff_income_group_average', f'simple average of {len(g)} sourced 2022 tariffs of income group '
                      f'{t["income_group"] if groups.get(t["income_group"]) else "(none: all groups)"} = {p:.4g} USD/MWh')
    keep, obs = set(R), set(observed)
    return {r: v for r, v in out.items() if r in keep and r not in obs}


def ely_class_prices(table, fx):
    """Beta v4 G10 (choice ely_class_price): sourced 2022 industrial electricity prices for the regions that took the US price
    through the GTAP 12 §12.3.6 class fill (config/s11/ely_industrial_prices_2022.csv). table: rows with region, value, unit
    ('USD/MWh', 'LCU/MWh' or 'LCU/kWh'), fx_iso3, measure, used ('yes' or 'no'), source; fx: {iso3: LCU per USD, WDI
    PA.NUS.FCRF 2022}. A used row is an observed end-user price (purchasers', the Table 12.8 electricity margin is 0, so also
    the basic price); a row not used (no official figure, or a sourced figure that is wholesale only or one tariff snapshot)
    keeps the class fill. Returns ({region: (USD/MWh, detail)}, [regions not used])."""
    out, pending = {}, []
    for t in table:
        r = t['region']
        if r in out or r in pending:
            raise SystemExit(f'ely_industrial_prices_2022.csv: two rows for {r}')
        if t['used'] not in ('yes', 'no') or not str(t['measure']).strip():
            raise SystemExit(f'ely_industrial_prices_2022.csv: {r} needs a measure and used yes or no')
        if t['used'] == 'no':
            pending.append(r)
            continue
        if not str(t['value']).strip():
            raise SystemExit(f'ely_industrial_prices_2022.csv: {r} is used and has no value')
        if not str(t['source']).strip():
            raise SystemExit(f'ely_industrial_prices_2022.csv: {r} has a value and no source')
        v, u = float(t['value']), t['unit']
        if u == 'USD/MWh':
            p, d = v, f'{v:.6g} USD/MWh'
        elif u in ('LCU/MWh', 'LCU/kWh'):
            if t['fx_iso3'] not in fx:
                raise SystemExit(f'ely_industrial_prices_2022.csv: no exchange rate for {r}')
            k = float(fx[t['fx_iso3']])
            p = v * (1000.0 if u == 'LCU/kWh' else 1.0) / k
            d = f'{v:.6g} {t["fx_iso3"]} currency {u[4:]} at {k:.6g} per USD (WDI PA.NUS.FCRF {t["fx_iso3"]} 2022)'
        else:
            raise SystemExit(f'ely_industrial_prices_2022.csv: unknown unit {u!r} for {r}')
        if not (np.isfinite(p) and p > 0):
            raise SystemExit(f'ely_industrial_prices_2022.csv: price of {r} is not positive')
        out[r] = (p, f'{t["source"]} ({t["measure"]}): {d} = {p:.4g} USD/MWh')
    return out, pending


def domestic_basic_prices(R, px, pmb, xvol, mvol, source, gap, net_exporter=None, lignite=None, export_cap=False, book_subsidy=False):
    """Return {commodity: (price array, rule array, detail array)} following the module order.
    lignite: None (rule 5 off) or dict(share=brown-coal share of coal output by region, price=USD/t);
    export_cap: rule 6 on or off. Both act after the fill, so the class averages use observed prices only.
    px: export prices; pmb: import basic prices (VMSB / import volume); xvol, mvol: balanced trade
    volumes; source: {(c, r): (basic price, label[, 'basic' | 'purchasers'])}; gap: {(c, r): subsidy per unit}; net_exporter:
    net energy exporter by region (value of all energy trade), the trade dimension of the fill classes.
    A region with no trade in the commodity takes the simple average of the exporters' prices as its
    trade-parity reference for the IEA price gap (its own BACI unit value, if any, is not a trade price).
    book_subsidy (fix-round B15, GTAP's booking): a region priced by the IEA gap takes the reference price itself;
    the gap is the consumption subsidy S13 books (fuel_subsidy_rows). Otherwise the price is reference less gap."""
    n = len(R)
    obs = {}
    for c in COMMODITIES:
        p = np.full(n, np.nan)
        rule = np.full(n, '', dtype=object)
        det = np.full(n, '', dtype=object)
        net_imp = (mvol[c] > 0) & (mvol[c] > xvol[c])
        refs, _ = trade_parity_reference(px[c], pmb[c], xvol[c], mvol[c])
        for i, r in enumerate(R):
            ref = refs[i]
            imp_ok = c in IMPORT_PRICE_COMMODITIES and net_imp[i] and np.isfinite(pmb[c][i])
            src = source.get((c, r))
            if src is not None and len(src) > 2 and src[2] == 'purchasers' and imp_ok:
                # §12.3.8: an import-price estimate ranks ahead of a purchasers'-price estimate (David 2026-10-23 20:13)
                p[i], rule[i] = pmb[c][i], 'import_basic_price'
                det[i] = f'import basic price ranks ahead of the purchasers\' price ({src[1]}; {src[0]:.4g})'
            elif src is not None:
                p[i], rule[i], det[i] = src[0], 'source_data', src[1]
            elif (c, r) in gap and np.isfinite(ref):
                v = ref - gap[(c, r)]
                if v > 0:
                    where = '' if net_imp[i] or xvol[c][i] > 0 else ' (no trade: simple-average export price)'
                    if book_subsidy:
                        # B15 (GTAP): the market price is the reference; the gap is a consumption subsidy booked by S13
                        p[i], rule[i] = ref, 'iea_price_gap'
                        det[i] = (f'trade-parity reference {ref:.4g}{where}; IEA subsidy per unit {gap[(c, r)]:.4g} booked as a '
                                  f'consumption subsidy (end-user price {v:.4g}; fuel_subsidies_s11.csv)')
                    else:
                        p[i], rule[i] = v, 'iea_price_gap'
                        det[i] = f'trade-parity {ref:.4g}{where} less IEA subsidy per unit {gap[(c, r)]:.4g}'
                else:
                    det[i] = f'IEA subsidy per unit {gap[(c, r)]:.4g} is not below the trade-parity price {ref:.4g}; not used'
            if not rule[i] and imp_ok:
                p[i], rule[i] = pmb[c][i], 'import_basic_price'
        obs[c] = (p, rule, det)
    hi = price_class(R, {c: np.where(obs[c][1] == 'iea_price_gap', np.nan, obs[c][0]) for c in COMMODITIES})
    nx = np.zeros(n, bool) if net_exporter is None else np.asarray(net_exporter, bool)
    out = {}
    for c in COMMODITIES:
        p, rule, det = obs[c]
        missing = ~np.isfinite(p)
        # the class averages use observed prices only (source data and import basic prices); an IEA price-gap
        # estimate prices its own region but is not an observation (Grok QA 2, 2026-10-23)
        have = ~missing & (rule != 'iea_price_gap')
        allavg = float(p[have].mean()) if have.any() else float(np.nanmean(px[c]))
        for i in np.where(missing)[0]:
            cls = have & (nx == nx[i]) & ((hi == hi[i]) if hi[i] else True)
            if net_exporter is not None and cls.any():
                v, what = float(p[cls].mean()), (f'simple average of {int(cls.sum())} net energy '
                                                 f'{"exporters" if nx[i] else "importers"}'
                                                 + {1: ' with above-average prices', -1: ' with below-average prices', 0: ''}[hi[i]])
            else:
                v, what = allavg, f'simple average of {int(have.sum())} regions'
            p[i], rule[i] = v, 'simple_average'
            det[i] = (det[i] + '; ' if det[i] else '') + what
        if c == 'coa' and lignite is not None:
            lignite_blend(R, p, rule, det, lignite['share'], lignite['price'], {r for (cc, r) in source if cc == 'coa'})
        if export_cap and c in EXPORT_CAP_COMMODITIES:
            cap_at_export_price(p, rule, det, px[c], xvol[c], mvol[c])
        out[c] = (p, rule, det)
    return out


def lignite_blend(R, p, rule, det, share, p_lig, own_source):
    """Rule 5, in place: a region with no coal source price of its own prices the brown-coal share of its coal
    output at the lignite price, p = (1 - s) p + s p_lig."""
    for i, r in enumerate(R):
        s = float(share[i])
        if s <= 0 or r in own_source or not np.isfinite(p[i]):
            continue
        old = p[i]
        p[i] = (1.0 - s) * old + s * p_lig
        rule[i] += LIGNITE_SUFFIX
        det[i] = (det[i] + '; ' if det[i] else '') + f'brown coal {s:.3f} of output at the US lignite mine price {p_lig:.4g} (was {old:.4g})'


def cap_at_export_price(p, rule, det, px, xvol, mvol):
    """Rule 6, in place: a net exporter (exports above imports) whose domestic price is not source data pays at
    most its own export price (export parity)."""
    for i in range(len(p)):
        if not (xvol[i] > 0 and xvol[i] > mvol[i]) or rule[i].split('+')[0] == 'source_data':
            continue
        if np.isfinite(px[i]) and px[i] > 0 and np.isfinite(p[i]) and p[i] > px[i]:
            old = p[i]
            p[i] = px[i]
            rule[i] += CAP_SUFFIX
            det[i] = (det[i] + '; ' if det[i] else '') + f'net exporter: capped at its export price {px[i]:.4g} (was {old:.4g})'


SUBSIDY_SUFFIX = '+iea_subsidy'     # fix-round B15 extension: a row priced by another rule that also books its IEA subsidy


def iea_subsidy_by_region(R, regions_members, subsidy, deflator):
    """{(commodity, region): the IEA 2022 consumption subsidy at 2022 prices, USD million}, members of a composite
    region summed. subsidy: {(commodity, iso3): real-2024 USD m}; deflator: nominal 2022 / real 2024 (as iea_gap_per_unit)."""
    out = {}
    for c in COMMODITIES:
        for r in R:
            s = sum(subsidy.get((c, m), 0.0) for m in regions_members[r])
            if s > 0:
                out[(c, r)] = s * deflator
    return out


SUBSIDY_PRICE_GAP, SUBSIDY_ADD_ON_TOP = 'price_gap', 'add_on_top'     # fuel_subsidy_rows modes (choice fuel_subsidies)
OBSERVED_PRICE_RULES = ('source_data', 'regulated_average')     # rule-1 prices observed in the region (§12.3.4, incl. the A9 regulated
# prices), and (Fable QA C-02) the class average of those regulated consumer prices where a subsidising exporter has none


ELY_UNOBSERVED_REFERENCE, ELY_UNOBSERVED_ADD_ON_TOP = 'reference', 'add_on_top'   # choice iea_reference_ely (round 3)
UNOBSERVED_TARIFF_BASES = ('tariff_income_group_average',)


REGULATED_AVERAGE, REGULATED_BASIS = 'regulated_average', 'regulated_class_average'
REGULATED_COMMODITIES = ('gas',)


def regulated_consumer_fill(R, price, rule, det, iea_value, net_exporter, consumption, xvol=None, mvol=None, geo=None,
                            commodities=REGULATED_COMMODITIES):
    """Fable QA C-02/B-03 (2026-10-25; choice regulated_price_fill; David 2026-10-25 after S16 and Fable reviews), in place,
    before fuel_subsidy_rows. The class is the net energy exporters and the net exporters of the fuel itself (xvol > mvol;
    Fable review: UZB) with an IEA consumption subsidy on a regulated fuel. A
    member with no observed price of its own takes as its consumer price PM0 the simple average of the observed (source
    data) prices of the class (GTAP 12 ch.12 §12.3.6 fills a missing domestic price with its class average), or the lowest
    observed price where its IEA rate alone is at least that average (an IEA gap of 130 to 320 USD/kcm means a near-free
    end-use price): the lowest observed price of the class in the region's own GTAP geographic group where one exists
    (geo: {region: gtap_geo}; ARE and KWT take Saudi Arabia's, the GCC price-setter), else the class minimum (Fable review). fuel_subsidy_rows then sets the reference from the IEA identity (regulated_reference).
    consumption: {c: PREP consumption volume}, the IEA rate's denominator (fuel_subsidy_rows).
    Returns {commodity: dict(average, lowest, n, filled=[regions], members={class regions incl. filled})}."""
    nx = np.asarray(net_exporter, bool)
    out = {}
    for c in commodities:
        base = np.array([str(x).split('+')[0] for x in rule[c]], dtype=object)
        sub = np.array([(c, r) in iea_value for r in R])
        nxc = nx | ((np.asarray(xvol[c]) > np.asarray(mvol[c])) if xvol is not None else False)
        cls = (base == 'source_data') & sub & nxc & np.isfinite(price[c])
        if not cls.any():
            continue
        avg, low = float(price[c][cls].mean()), float(price[c][cls].min())
        filled = []
        for i, r in enumerate(R):
            if sub[i] and nxc[i] and base[i] != 'source_data':
                q = float(consumption[c][i])
                rate = float(iea_value[(c, r)]) / q if q > 0 else np.nan
                if np.isfinite(rate) and rate >= avg:
                    grp = [j for j in np.where(cls)[0] if geo is not None and geo.get(R[j]) == geo.get(r)]
                    if grp:
                        j = min(grp, key=lambda k: price[c][k])
                        pm0, how = float(price[c][j]), (f'IEA rate {rate:.4g} at least the class average {avg:.4g}, so the lowest observed regulated '
                                                        f'price in its GTAP geographic group {geo.get(r)}, {R[j]} {float(price[c][j]):.4g}')
                    else:
                        pm0, how = low, (f'IEA rate {rate:.4g} at least the class average {avg:.4g} and no observed price in its GTAP group, so '
                                         f'the lowest observed regulated price of {int(cls.sum())} subsidising exporters {low:.4g}')
                else:
                    pm0, how = avg, f'simple average of the observed prices of {int(cls.sum())} subsidising net energy exporters {avg:.4g}'
                old, oldr = price[c][i], rule[c][i]
                price[c][i], rule[c][i] = pm0, REGULATED_AVERAGE
                det[c][i] = f'no observed regulated price: {how} (Fable QA C-02; was {old:.4g}, {oldr})'
                filled.append(r)
        out[c] = dict(average=avg, lowest=low, n=int(cls.sum()), filled=filled,
                      members={r for i, r in enumerate(R) if cls[i]} | set(filled))
    return out


EXPORT_PARITY_CAP = 'export_parity_cap'      # beta v4 P6 (fuel_subsidy_rows export_parity_cap)


def regulated_reference(p0, rate, ref, low):
    """Fable QA C-02 (David 2026-10-25): the market price (= reference) of a regulated-class row with consumer price p0 and
    IEA rate (uncapped, so the IEA money is kept). The reference is the IEA identity p0 + rate, capped at the region's own
    2022 trade price ref (export unit value, the netback; import basic price for a net importer) where that cap leaves a
    consumer price ref - rate at or above the lowest observed regulated price low; otherwise (IEA rate near or above ref:
    IRN, TKM) uncapped. fuel_subsidy_rows applies the cap to an unobserved PM0 only: an observed regulated price stays the
    consumer price (UZB, KAZ, uncapped). Returns (market, consumer, cap label)."""
    m = p0 + rate
    if np.isfinite(ref) and ref - rate >= low and m > ref:
        return ref, ref - rate, 'netback_reference'
    return m, m - rate, ('iea_reference_above_trade_price' if np.isfinite(ref) and m > ref else 'none')


def fuel_subsidy_rows(R, px, pmb, xvol, mvol, gap, consumption, rule, price, unit=None, absorption=None, iea_value=None,
                      mode=SUBSIDY_PRICE_GAP, consumer_price=None, ely_unobserved=ELY_UNOBSERVED_REFERENCE, regulated=None,
                      export_parity_cap=False, parity_pmb=None):
    """Fix-round B15: the consumption subsidy by (commodity, region), Chepeliev, McDougall and van der Mensbrugghe (2018) §3.2.

    1. Rows whose domestic price rule is the IEA price gap (rule.split('+')[0] == 'iea_price_gap'): reference =
       trade_parity_reference; consumer (end-user) price = reference - gap per unit; the market (domestic basic) price is
       the reference; subsidy (USD million) = (reference - consumer price) x domestic use.
    2. With iea_value ({(c, r): the region's IEA subsidy at 2022 prices, iea_subsidy_by_region}; David 2026-10-24, "stick
       to GTAP"): every other row with an IEA subsidy, i.e. a row priced from source data (A9 regulated prices) or one
       whose gap was not used. The IEA rate is the IEA value per unit of the consumption volume (the S11 absorption where
       PREP has no consumption volume), on domestic use = the smaller of the two (step 1).
       mode SUBSIDY_PRICE_GAP (fix-round wA, the default; independent QA HIGH-1): the subsidy is the gap between a
       subsidised consumer price and the reference (§2.1: only subsidies that lower the consumer price below the
       reference), so no row ends with its market price above the reference:
       - the rate is at most the reference (step 2's rescaling, applied to every row; rate_cap = 'reference');
       - an observed price (rule source_data, incl. the A9 regulated prices) is the consumer price PM0 and the market
         price is PM0 + rate (PM1 = PM0 + VS/ED), the rate at most the observed gap reference - PM0
         (rate_cap = 'observed_price_gap'); with PM0 at or above the reference there is no gap and no row;
       - a price that is not observed (the class-average fill, the import basic price) is an unsubsidised price, so the
         subsidy is not added on top of it: the market price is the reference and the consumer price is
         reference - rate (consumer_price_basis = 'reference_less_rate').
       mode SUBSIDY_ADD_ON_TOP (the w10 rule, kept for comparison): the S11 price stays the consumer price, step 2
       rescales the rate to the reference only where the rate exceeds it and imports exceed half of domestic use (Table 2
       rows 10-11), and the market price is consumer price + rate.
       The subsidy is rate x domestic use; the price-gap value (reference - consumer price) x domestic use is reported
       beside it (price_gap_subsidy_musd).

    The gap per unit is the IEA 2022 subsidy over the consumption volume; domestic use is that volume, or the S11
    absorption (production + imports - exports, the volume the data base holds) where it is smaller (the paper's step 1:
    the GTAP volume replaces the IMF volume where the IMF one is larger). absorption: {c: array} (None: the consumption
    volume). price: {c: domestic basic price array before the 90 percent rule and before this booking}.
    Electricity (fix round wA2, COST_REFERENCE_COMMODITIES; consumer_price: {region: (price, basis, detail)} from
    electricity_consumer_prices): electricity has no trade parity, and the IEA reference for it is a supply cost, so in
    mode SUBSIDY_PRICE_GAP the reference is IEA's implied one, consumer price + IEA rate (PM0 + VS/ED), with no cap; the
    consumer price is the observed S11 price, else the sourced 2022 tariff, else the income-group average of the tariffs
    (consumer_price_basis); the trade-parity price is reported beside it (trade_parity_price). Traded fuels: the rate is
    at most (1 - CONSUMER_FLOOR_SHARE) x reference on an unobserved price, so the consumer price stays positive.
    Round 3 (final QA item 4, choice iea_reference_ely; ely_unobserved): where the region has no tariff of its own (basis
    tariff_income_group_average), the income-group average of the sourced tariffs is not taken as its consumer price with the
    IEA rate added on top; it is the reference (the regional price, Chepeliev et al. 2018 §2.1: the subsidy is the gap below
    the reference), raised to rate / (1 - CONSUMER_FLOOR_SHARE) where the rate is larger, so the IEA money (rate x use) is
    kept and the consumer price is reference - rate (consumer_price_basis 'reference_less_rate_income_group_tariff').
    ely_unobserved = ELY_UNOBSERVED_ADD_ON_TOP keeps the wA2 rule (consumer = the group average, reference = it + rate). Every row has subsidy = (market price - consumer price) x domestic use.
    export_parity_cap (beta v4 P6, choice gas_export_parity_cap): a regulated-class row whose market price PM0 + IEA rate is
    above the region's own trade price, observed PM0 or not, has its market price capped at that price and keeps its
    consumer price, so the booked rate is own trade price - PM0, below the IEA rate (rate_cap 'export_parity_cap').
    Chepeliev, McDougall and van der Mensbrugghe (2018) pp.92-96 set an exporter's updated market price PM1 = PM0 + VS/ED
    equal to its export price and rescale agency money that clashes with GTAP's prices (p.96, written for importers); the
    exporter extension is ours. Returns a list of dicts; apply_subsidy_prices puts the market prices into the price arrays."""
    if mode not in (SUBSIDY_PRICE_GAP, SUBSIDY_ADD_ON_TOP):
        raise ValueError(f'fuel_subsidy_rows: unknown mode {mode!r}')
    rows = []
    for c in COMMODITIES:
        refs, basis = trade_parity_reference(px[c], pmb[c], xvol[c], mvol[c])
        # beta v5 A (choice contract_routes_out_of_parity_cap): the regulated-row cap of a net importer uses an import price
        # with its contract routes valued at the exporter's reference price (parity_pmb), not at the contract price
        refs_cap = refs if parity_pmb is None else trade_parity_reference(px[c], parity_pmb[c], xvol[c], mvol[c])[0]
        for i, r in enumerate(R):
            base = str(rule[c][i]).split('+')[0]
            qc = float(consumption[c][i])
            qa = max(float(absorption[c][i]), 0.0) if absorption is not None else qc
            ref = float(refs[i])
            common = dict(region=r, commodity=c, price_unit=(unit or {}).get(c, ''), reference_price=ref, reference_basis=basis[i],
                          consumption_volume=qc, absorption_volume=qa, imports_volume=float(mvol[c][i]), trade_parity_price=ref)
            if base == 'iea_price_gap' and (c, r) in gap:
                g = float(gap[(c, r)])
                q, vbasis = (qa, 's11_absorption') if qa < qc else (qc, 'consumption')
                cons = ref - g
                rows.append(dict(common, iea_subsidy_musd=g * qc, iea_subsidy_per_unit=g, step2_rescaled=False, subsidy_per_unit=g,
                                 consumer_price=cons, market_price=ref, domestic_use=q, domestic_use_basis=vbasis,
                                 subsidy_musd=(ref - cons) * q, price_gap_subsidy_musd=(ref - cons) * q,
                                 domestic_price_before_90pct=float(price[c][i]), domestic_price_rule=str(rule[c][i]), source_rule='iea_price_gap',
                                 consumer_price_basis='reference_less_iea_gap', rate_cap='none'))
                continue
            if iea_value is None or (c, r) not in iea_value:
                continue
            vs = float(iea_value[(c, r)])
            if qc > 0:
                s = vs / qc
                q, vbasis = (qa, 's11_absorption') if qa < qc else (qc, 'consumption')
            else:
                q, vbasis = qa, 's11_absorption_no_consumption_volume'
                s = vs / qa if qa > 0 else np.nan
            if not (q > 0 and np.isfinite(s) and s > 0):
                continue                                    # no domestic use to carry it (reported by S11-Rsubsidyunbooked)
            m = float(mvol[c][i])
            cost_ref = mode == SUBSIDY_PRICE_GAP and c in COST_REFERENCE_COMMODITIES
            src_rule = base + ('_gap_not_used' if (c, r) in gap and not cost_ref else '')
            p0 = float(price[c][i])
            observed = base in OBSERVED_PRICE_RULES
            if mode == SUBSIDY_ADD_ON_TOP:
                rescale = bool(np.isfinite(ref) and ref > 0 and s > ref and m > q - m)     # step 2: rate above the supply cost, imports > half
                rate, cap = (ref, 'reference') if rescale else (s, 'none')
                cons, market, cbasis = p0, p0 + rate, 'observed_s11_price' if observed else 's11_price'
            elif cost_ref:
                # wA2: electricity, IEA's implied reference = consumer price + IEA rate (no trade parity, no cap)
                rescale, rate, cap = False, s, 'none'
                if observed:
                    cons, cbasis = p0, 'observed_s11_price'
                else:
                    if consumer_price is None or r not in consumer_price:
                        raise SystemExit(f'fuel_subsidy_rows: no electricity end-user price for {r} (config/s11/electricity_tariffs_2022.csv)')
                    cons, cbasis = float(consumer_price[r][0]), consumer_price[r][1]
                if (not observed and cbasis in UNOBSERVED_TARIFF_BASES and ely_unobserved == ELY_UNOBSERVED_REFERENCE):
                    # round 3: no own tariff, so the regional (income-group) price is the reference and the subsidy lies below it
                    reg = cons
                    market = max(reg, rate / (1.0 - CONSUMER_FLOOR_SHARE))
                    cons, cbasis = market - rate, 'reference_less_rate_income_group_tariff'
                    cap = 'reference_raised_to_rate' if market > reg else 'none'
                    ref = market
                    common = dict(common, reference_price=market, reference_basis='income_group_tariff_average_at_least_rate_over_0.99')
                else:
                    market = cons + rate
                    ref = market
                    common = dict(common, reference_price=market, reference_basis='iea_implied_consumer_price_plus_iea_rate')
            elif mode == SUBSIDY_PRICE_GAP and regulated and c in regulated and r in regulated[c]['members']:
                # Fable QA C-02 (regulated_price_fill): reference from the IEA identity, the IEA rate uncapped
                rescale, rate = False, s
                # the netback cap moves only an unobserved PM0; an observed regulated price stays the consumer price (Fable review)
                ref = float(refs_cap[i])
                market, cons, cap = regulated_reference(p0, s, ref if base != 'source_data' else np.nan, regulated[c]['lowest'])
                if base == 'source_data' and np.isfinite(ref) and market > ref:
                    cap = 'iea_reference_above_trade_price'
                if export_parity_cap and np.isfinite(ref) and market > ref:
                    # beta v4 P6: the market price at most the own trade price, the consumer price kept, the rate cut
                    market, cap = ref, EXPORT_PARITY_CAP
                    rate = market - cons
                    if rate <= 0:
                        continue                            # consumer price at or above the own trade price: no gap
                cbasis = 'observed_s11_price' if base == 'source_data' else REGULATED_BASIS
                if cap == 'netback_reference':
                    cbasis = 'netback_reference_less_rate'
                common = dict(common, reference_price=market, reference_basis='regulated_price_plus_iea_rate_at_most_own_trade_price')
                ref = market
            else:
                if not (np.isfinite(ref) and ref > 0):
                    continue                                # no reference to measure a gap against (S11-Rsubsidyunbooked)
                top = ref if observed else (1.0 - CONSUMER_FLOOR_SHARE) * ref
                rescale = s > top
                rate, cap = (top, 'reference' if observed else 'reference_less_consumer_floor') if rescale else (s, 'none')
                if observed:
                    room = ref - p0
                    if room < rate:
                        rate, cap = max(room, 0.0), 'observed_price_gap'
                    if rate <= 0:
                        continue                            # observed price at or above the reference: no gap (S11-Rsubsidyunbooked)
                    cons, market = p0, p0 + rate
                    cbasis = 'observed_s11_price' if base == 'source_data' else REGULATED_BASIS
                else:
                    cons, market, cbasis = ref - rate, ref, 'reference_less_rate'
            rows.append(dict(common, iea_subsidy_musd=vs, iea_subsidy_per_unit=s, step2_rescaled=rescale, subsidy_per_unit=rate,
                             consumer_price=cons, market_price=market, domestic_use=q, domestic_use_basis=vbasis,
                             subsidy_musd=rate * q, price_gap_subsidy_musd=(ref - cons) * q if np.isfinite(ref) else np.nan,
                             domestic_price_before_90pct=market, domestic_price_rule=str(rule[c][i]) + SUBSIDY_SUFFIX,
                             source_rule=src_rule, consumer_price_basis=cbasis, rate_cap=cap))
    return rows


def unbooked_reason(R, rule, price, iea_value, rows, px, pmb, xvol, mvol):
    """{(c, r): why an IEA subsidy has no row} for S11-Rsubsidyunbooked (fix-round wA): an observed price at or above the
    reference (no price gap), or no domestic use volume or no reference. price, rule: before the booking."""
    have = {(x['commodity'], x['region']) for x in rows}
    ix = {r: i for i, r in enumerate(R)}
    refs = {c: trade_parity_reference(px[c], pmb[c], xvol[c], mvol[c])[0] for c in COMMODITIES}
    out = {}
    for (c, r) in iea_value:
        if (c, r) in have or r not in ix:
            continue
        i = ix[r]
        ref, p0 = float(refs[c][i]), float(price[c][i])
        if str(rule[c][i]).split('+')[0] in OBSERVED_PRICE_RULES and np.isfinite(ref) and p0 >= ref:
            out[(c, r)] = f'observed price {p0:.4g} at or above the reference {ref:.4g}: no price gap'
        else:
            out[(c, r)] = 'no domestic use volume or no reference'
    return out


def apply_subsidy_prices(rows, R, price, rule, det):
    """In place: each row booked under fix-round B15's extension (source_rule other than 'iea_price_gap') moves its
    region's domestic basic price to the market price and marks the rule: consumer price + subsidy per unit where the
    price is observed, the reference where it is not (fix-round wA)."""
    ix = {r: i for i, r in enumerate(R)}
    for x in rows:
        if x['source_rule'] == 'iea_price_gap':
            continue
        c, i = x['commodity'], ix[x['region']]
        price[c][i] = x['market_price']
        rule[c][i] = x['domestic_price_rule']
        cap = x.get('rate_cap', 'reference' if x['step2_rescaled'] else 'none')
        note = {'reference': f' (rate capped at the reference price, step 2; IEA {x["iea_subsidy_per_unit"]:.4g})',
                'reference_less_consumer_floor': f' (rate capped at 99% of the reference, step 2 with a 1% consumer price; IEA {x["iea_subsidy_per_unit"]:.4g})',
                'observed_price_gap': f' (rate capped at the observed price gap; IEA {x["iea_subsidy_per_unit"]:.4g})'}.get(cap, '')
        if x.get('reference_basis') == 'iea_implied_consumer_price_plus_iea_rate':
            how = (f'consumer price {x["consumer_price"]:.4g} ({x["consumer_price_basis"]}) + IEA rate {x["subsidy_per_unit"]:.4g} = IEA-implied '
                   f'reference and market price {x["market_price"]:.4g} (fix round wA2; trade-parity price {x["trade_parity_price"]:.4g} not used)')
        elif x.get('consumer_price_basis') == 'reference_less_rate':
            how = (f'the S11 price {x["domestic_price_rule"].split("+")[0]} is not observed, so the market price is the reference '
                   f'{x["reference_price"]:.4g} and the consumer price is reference - {x["subsidy_per_unit"]:.4g} per unit{note} = '
                   f'{x["consumer_price"]:.4g} (fix-round wA)')
        else:
            how = (f'consumer price {x["consumer_price"]:.4g} + {x["subsidy_per_unit"]:.4g} per unit{note} = market price '
                   f'{x["market_price"]:.4g} (reference {x["reference_price"]:.4g})')
        det[c][i] = (det[c][i] + '; ' if det[c][i] else '') + (
            f'IEA 2022 subsidy {x["iea_subsidy_musd"]:.6g} USD m booked as a consumption subsidy (fix-round B15, GTAP): {how}; '
            f'fuel_subsidies_s11.csv')
