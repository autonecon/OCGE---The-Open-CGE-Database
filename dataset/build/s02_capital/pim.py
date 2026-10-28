"""Perpetual-inventory roll-forward of the IMF ICSD capital stock to the base year (GTAP 12 ch.7 s7.3).

GTAP 12 ch.7 s7.3: capital stock from the IMF ICSD (to 2019); for the reference year, "our own estimates of capital stock
that follow the perpetual inventory method"; depreciation 4% of the stock. The text does not name the price index that
revalues the stock between years. A current-cost stock is the constant-price stock times the price of the assets, so the
roll-forward revalues with the price of investment goods (the implicit GFCF deflator, current over constant-price GFCF),
which is how ICSD itself turns constant-price stocks into its current-cost (_n) stocks. The GDP deflator is the fallback
where the country has no constant-price GFCF series (and was the rule before fix round 3, worker wH).

The re-base band (fix round 3, P10): where the rolled K/GDP moves more than the band from the ICSD ratio of the latest
ICSD year, the roll-forward is not trusted and the country keeps the ICSD ratio (re-based), with a flag.

Configuration: config/s02/s02_choices.csv, read strictly (the S11, S13, S14 pattern).
"""
import csv
import math
import os

BUILD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHOICES_PATH = os.path.join(BUILD, 'config', 's02', 's02_choices.csv')
CHOICE_COLUMNS = ('choice', 'value', 'decided_by', 'decided_at', 'basis', 'gtap_status')
GTAP_STATUS = {'gtap', 'gtap_rule', 'not_in_gtap_text', 'departure_logged', 'n/a'}

# choice -> the values this code implements (the first is the default)
# beta v4 G16a (S16 region gates, 2026-10-26; default off, David's call): WDI GFCF implausibly low against UN AMA
GFCF_AMA = 'wdi_gfcf_below_5pct_of_gdp_and_un_ama_share_above_twice_it_take_the_ama_share_x_wdi_gdp'
GFCF_LOW, GFCF_RATIO = 0.05, 2.0
# David 2026-10-26 08:26 UTC accepted the AMA share for LBN and VEN, labelled an estimate (the default); LBN at its own WDI
# 2019 GFCF share of GDP (before the 2020-2022 collapse in the WDI series) is kept as an alternative
GFCF_AMA_LBN_VEN = 'lbn_ven_un_ama_gfcf_share_x_wdi_gdp_estimate'
GFCF_LBN_2019 = 'ven_un_ama_gfcf_share_lbn_wdi_2019_gfcf_share_x_wdi_gdp_estimate'
# beta v5 (David 2026-10-27, package v2 via S13 item C notes): SDN (region XNF; WDI 2.2% of GDP, AMA 8.7%) joins LBN and VEN
GFCF_AMA_LBN_VEN_SDN = 'lbn_ven_sdn_un_ama_gfcf_share_x_wdi_gdp_estimate'
GFCF_REGIONS = {GFCF_AMA_LBN_VEN_SDN: ('LBN', 'VEN', 'SDN'), GFCF_AMA_LBN_VEN: ('LBN', 'VEN'), GFCF_LBN_2019: ('LBN', 'VEN'),
                GFCF_AMA: None, 'off': ()}
CHOICES = {
    'capital_revaluation': ('gfcf_implicit_deflator_else_gdp_deflator', 'gdp_deflator'),
    'capital_rebase_band': ('0.25', 'none'),
    'gfcf_wdi_outlier': (GFCF_AMA_LBN_VEN_SDN, GFCF_AMA_LBN_VEN, GFCF_LBN_2019, GFCF_AMA, 'off'),
    # beta v5 Y (s02_capital/gdp_weo.py; David 2026-10-27 08:39 UTC, package v2)
    'gdp_imputed_ama_to_weo': ('weo_where_wdi_lacks_gdp_and_un_ama_is_imputed_below_250_usd_per_head_or_off_the_wdi_official_rate',
                               'weo_where_wdi_lacks_gdp_and_un_ama_is_imputed_or_below_250_usd_per_head', 'off'),
    # beta v5 Y basis (s02_capital/gdp_weo.py target_musd; David 2026-10-27 10:00 UTC)
    'weo_gdp_basis': ('weo_gdp_per_head_x_s02_population_estimate', 'weo_total'),
    # beta v5 Cuba (s02_capital/gdp_official.py; David 2026-10-27 09:32 UTC, real-terms audit)
    'gdp_lcu_official_rate': ('listed_economies_official_lcu_gdp_and_expenditure_at_the_listed_official_rate', 'off'),
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


def _pos(x):
    return x is not None and math.isfinite(x) and x > 0


def revaluation(rule, gfcf_cn, gfcf_kd, gfcf_cn_prev, gfcf_kd_prev, defl, defl_prev):
    """Price change of the stock from t-1 to t. Returns (factor, basis) with basis 'gfcf' or 'gdp', or (nan, '') when
    neither index is available. gfcf_* are current- and constant-price GFCF in t and t-1; defl* the GDP deflator."""
    if rule == 'gfcf_implicit_deflator_else_gdp_deflator' and all(_pos(v) for v in (gfcf_cn, gfcf_kd, gfcf_cn_prev, gfcf_kd_prev)):
        return (gfcf_cn / gfcf_kd) / (gfcf_cn_prev / gfcf_kd_prev), 'gfcf'
    if rule not in CHOICES['capital_revaluation']:
        raise ValueError(f'unknown capital_revaluation {rule!r}')
    if _pos(defl) and _pos(defl_prev):
        return defl / defl_prev, 'gdp'
    return float('nan'), ''


def roll(k0, steps, delta=0.04):
    """K_t = (1 - delta) K_{t-1} x revaluation_t + GFCF_t (current prices). steps: [(revaluation, gfcf), ...]."""
    k = k0
    for rv, inv in steps:
        k = (1 - delta) * k * rv + inv
    return k


def rebase(ky_rolled, ky0, band):
    """Apply the re-base band. Returns (K/GDP used, rebased?). band None means no band."""
    if band is None or not (math.isfinite(ky_rolled) and ky0 > 0):
        return ky_rolled, False
    if abs(ky_rolled / ky0 - 1) > band:
        return ky0, True
    return ky_rolled, False


def band_value(value):
    return None if value == 'none' else float(value)


def gfcf_outlier(wdi_share, ama_share, low=GFCF_LOW, ratio=GFCF_RATIO):
    """Beta v4 G16a (gfcf_wdi_outlier): True where WDI GFCF is below `low` of GDP and the UN AMA GFCF share of GDP is more
    than `ratio` times it (LBN 2022: WDI 1.2%, AMA 31.1%; VEN: 4.7%, 14.1%)."""
    return bool(math.isfinite(wdi_share) and math.isfinite(ama_share) and wdi_share < low and ama_share > ratio * wdi_share)
