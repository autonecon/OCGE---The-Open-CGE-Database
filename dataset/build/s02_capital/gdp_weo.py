"""Beta v5 Y (S02 choice gdp_imputed_ama_to_weo): GDP from the IMF WEO where the UN AMA series is an imputation.

S02 takes WDI GDP, else UN AMA GDP (GTAP 12 ch.7 pp.1-2). WDI has no 2022 GDP for Yemen, and the UN AMA national-currency
series for Yemen is a UN imputation: it rises by the same 139.5 bn rial every year from 2020 to 2024 while rial prices rose
20-40% a year, and it is converted at the Aden market rate, so AMA puts 2022 GDP at 6.42 bn USD (168 USD per head, the
lowest in the world). With the choice on, a country whose GDP would come from UN AMA takes the IMF WEO current-USD GDP of
the base year when the AMA national-currency GDP series is an imputation (equal yearly increments over the last
IMPUTED_YEARS years) or AMA GDP per head is below PC_FLOOR USD, and WEO has a value. C, G and GFCF keep their UN AMA
shares of AMA GDP (the S02 rule for AMA components), times the WEO GDP. The tests and thresholds are ours; GTAP 12 ch.7
names WDI and UN sources and states no plausibility rule, so this is a labelled departure.

Value ON_RATE (the default from 2026-10-27 09:32 UTC; David approved South Sudan from the real-terms audit) adds a third
test: the AMA exchange rate (AMA national-currency GDP over AMA USD GDP) is more than RATE_TOL times off the WDI official
rate (PA.NUS.FCRF) in either direction. South Sudan: AMA about 2,139 SSP per USD (near the parallel rate), WDI 534.5, WEO
536, so AMA puts SSD at 4.36 bn against WEO's 7.53 bn.
"""
import csv
import math

CHOICE = 'gdp_imputed_ama_to_weo'
ON = 'weo_where_wdi_lacks_gdp_and_un_ama_is_imputed_or_below_250_usd_per_head'
ON_RATE = 'weo_where_wdi_lacks_gdp_and_un_ama_is_imputed_below_250_usd_per_head_or_off_the_wdi_official_rate'
VALUES = (ON_RATE, ON, 'off')
RATE_TOL = 1.5             # AMA rate / WDI official rate outside [1/1.5, 1.5]
IMPUTED_YEARS = 5          # 2020-2024 in the AMA file served 2026-10-20: four increments
IMPUTED_TOL = 1e-3         # range of the increments / their mean
PC_FLOOR = 250.0           # USD per head


def ama_imputed(values, tol=IMPUTED_TOL):
    """True when a run of yearly values (oldest first, no gaps) rises or falls by the same amount every year: the mark of
    a straight-line imputation (Yemen AMA 2020-2024: +139.5 bn rial a year). A series held exactly flat (zero increments)
    is not flagged: none is in the 2026-10-20 AMA file, and a flat nominal series would be caught by eye in S02-Rweo."""
    v = [float(x) for x in values]
    if len(v) < 3 or any(not math.isfinite(x) for x in v):
        return False
    d = [b - a for a, b in zip(v, v[1:])]
    m = sum(d) / len(d)
    return m != 0 and (max(d) - min(d)) / abs(m) < tol


def rate_off(ama_rate, wdi_rate, tol=RATE_TOL):
    """True when the AMA exchange rate is more than tol times off the WDI official rate (either way); False when either is
    missing (Cuba: no WDI rate)."""
    ok = [x is not None and math.isfinite(x) and x > 0 for x in (ama_rate, wdi_rate)]
    return all(ok) and not (1.0 / tol <= ama_rate / wdi_rate <= tol)


def applies(gdp_source, imputed, ama_pc, weo_musd, rate_mismatch=False):
    """The rule for one country: GDP from UN AMA (WDI lacks the year), the AMA series imputed, AMA GDP per head below the
    floor or (value ON_RATE) the AMA rate off the WDI official rate, and a WEO value to take."""
    low = ama_pc is not None and math.isfinite(ama_pc) and ama_pc < PC_FLOOR
    has = weo_musd is not None and math.isfinite(weo_musd) and weo_musd > 0
    return gdp_source == 'UNSD AMA' and (imputed or low or rate_mismatch) and has


BASIS_CHOICE = 'weo_gdp_basis'
BASIS_PC = 'weo_gdp_per_head_x_s02_population_estimate'
BASIS_TOTAL = 'weo_total'
BASIS_VALUES = (BASIS_PC, BASIS_TOTAL)


def target_musd(weo_total_musd, weo_pc_usd, s02_pop_million, basis):
    """The GDP a WEO-moved country takes (USD million). BASIS_PC (David 2026-10-27 10:00 UTC): WEO GDP per head x the S02
    population, because the Yemen WEO total implies 17.2 m people against WDI's 38.2 m (it likely covers only part of the
    country); falls back to the WEO total when per head or the population is missing. BASIS_TOTAL: the WEO total."""
    if basis == BASIS_PC and weo_pc_usd and s02_pop_million and s02_pop_million > 0:
        return float(weo_pc_usd) * float(s02_pop_million)
    return weo_total_musd


def read_weo(path, year):
    """{iso3: (GDP USD million, GDP per head USD or None)} for the year from the WEO extract csv."""
    out = {}
    with open(path, newline='') as fh:
        for r in csv.DictReader(fh):
            if int(r['year']) != year or not r['ngdpd_bn_usd']:
                continue
            out[r['iso3']] = (float(r['ngdpd_bn_usd']) * 1e3, float(r['ngdpdpc_usd']) if r['ngdpdpc_usd'] else None)
    return out
