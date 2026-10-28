"""Named overrides on the MFN schedules and on preference membership, as decided in s10_choices.csv.

Each block names its config row. The constants are copied from the sources the
rows cite (the ZRA 2022 tariff book, the EU GSP regulation annexes, the 2022
MAFRA TRQ plan and G/AG/N/KOR/93, Korea Customs Act article 71, HTS 2022,
Iraq Council of Ministers Resolution 393/2017). They are rules, not numbers
from an older build.
"""
import csv
import os

from .config import CONFIG_DIR, ConfigError

# Ad valorem alternatives on the class-A Zambia lines. ZRA 2022 First Schedule
# national lines, simple average inside the HS6 (ch.11B §B.2). The kwacha
# alternative is not used: a mixed duty takes the ad valorem part
# (Guimbard et al. 2012 p.8; David 2026-10-22 02:43 UTC+7).
# Ad valorem alternatives from the 2022 ZRA tariff book, printed pp. 396–401
# (dataset/data/zambia_customs_tariff/zm_tb_2022.pdf). The footnotes on those
# pages are the mixed duties:
#   *   25% or K2000 per vehicle, whichever is greater
#   **  15% or K2000 per vehicle, whichever is greater
#   *** 30% or K6000 per vehicle, whichever is greater (Act No. 18 of 2016)
# The HS6 figure is the simple average of the national-line ad valorem
# alternatives, which is the class-A rule for a mixed duty (Guimbard et al.
# 2012 p.8). 870380 is not here: the book prints a pure 15% on 8703.80.90 and
# the 2022 Reported line has NBR_NA_LINES 0.
ZMB_ADVALOREM = {
    '870210': 20.0,   # * and **
    '870220': 20.0,
    '870230': 20.0,
    '870240': 20.0,
    '870290': 20.0,
    '870310': 25.0,   # *
    '870321': 15.0,   # free, 15, 15, ***
    '870322': 15.0,
    '870323': 15.0,
    '870324': 15.0,
    '870331': 15.0,
    '870332': 15.0,
    '870333': 15.0,
    '870340': 15.0,
    '870350': 15.0,
    '870360': 15.0,
    '870370': 15.0,
    '870390': 15.0,
    '870421': 30.0,   # ***
    '870422': 15.0,   # **
    '870431': 30.0,
    '870432': 15.0,
    '870490': 22.5,   # *** and **
}
ZMB_BOOK = {
    '870210': '8702.10.10 * 25% or K2000; 8702.10.90 ** 15% or K2000',
    '870220': '8702.20.10 * 25% or K2000; 8702.20.90 ** 15% or K2000',
    '870230': '8702.30.10 * 25% or K2000; 8702.30.90 ** 15% or K2000',
    '870240': '8702.40.10 * 25% or K2000; 8702.40.90 ** 15% or K2000',
    '870290': '8702.90.10 * 25% or K2000; 8702.90.90 ** 15% or K2000',
    '870310': '8703.10.00 * 25% or K2000',
    '870321': '8703.21 free, 15, 15, and *** 30% or K6000',
    '870322': '8703.22 free, 15, 15, and *** 30% or K6000',
    '870323': '8703.23 free, 15, 15, and *** 30% or K6000',
    '870324': '8703.24 free, 15, 15, and *** 30% or K6000',
    '870331': '8703.31 free, 15, 15, and *** 30% or K6000',
    '870332': '8703.32 free, 15, 15, and *** 30% or K6000',
    '870333': '8703.33 free, 15, 15, and *** 30% or K6000',
    '870340': '8703.40 free, 15, 15, and *** 30% or K6000',
    '870350': '8703.50 free, 15, 15, and *** 30% or K6000',
    '870360': '8703.60 free, 15, 15, and *** 30% or K6000',
    '870370': '8703.70 free, 15, 15, and *** 30% or K6000',
    '870390': '8703.90 free, 15, 15, and *** 30% or K6000',
    '870421': '8704.21.00 *** 30% or K6000',
    '870422': '8704.22.00 ** 15% or K2000',
    '870431': '8704.31.00 *** 30% or K6000',
    '870432': '8704.32.00 ** 15% or K2000',
    '870490': '8704.90.10 *** 30% or K6000; 8704.90.90 ** 15% or K2000',
}

CAMBODIA_EBA = (
    '121293', '420100', '4202', '4203', '420500', '420600',
    '610341', '610343', '610349', '6105', '6107', '6109',
    '611510', '611521', '611522', '611529', '611595', '611596', '611599',
    '620341', '620343', '620349', '6205', '6207',
    '621132', '621133', '621139', '621142', '621143', '621149', '6212',
    '640319', '640320', '640340', '640351', '640359', '640391', '640399',
    '6405', '6406',
)
GSP_RULES = {
    'S-1a': (['0208', '020500', '01012990', '01013000', '01019000', '01042010', '01061410', '01063910', '02068091', '02069091', '02071491', '02072791', '02074595', '02075595', '02076091', '02089070', '02109910', '02109959', '02109985', '04031051', '04031053', '04031059', '04031091', '04031093', '04031099', '04039071', '04039073', '04039079', '04039091', '04039093', '04039099', '04052010', '04052030', '04071990', '04072990', '04079090', '04090000', '04100000', '05119939'], ['02084020']),
    'S-2a': (['06', '06031200', '06042040'], []),
    'S-3': (['1504', '1507', '1508', '1512', '1513', '1514', '1515', '1516', '1517', '151190', '151800', '15019000', '15021090', '15029090', '15030019', '15030090', '15050010', '15111090', '15162010', '15219099', '15220010', '15220091'], []),
    'S-5': (['27', '2522', '2523', '25199010'], []),
    'S-6a': (['2801', '2804', '2806', '2809', '2811', '2812', '2813', '2814', '2815', '2816', '2819', '2820', '2821', '2824', '2825', '2826', '2827', '2828', '2829', '2830', '2831', '2832', '2833', '2835', '2836', '2837', '2839', '2840', '2841', '2842', '2843', '2846', '2849', '2852', '2853', '2903', '2904', '2905', '2906', '2907', '2908', '2909', '2910', '2912', '2914', '2915', '2916', '2917', '2918', '2919', '2920', '2921', '2922', '2923', '2924', '2925', '2926', '2932', '2933', '2934', '2938', '280519', '280530', '281810', '283429', '285000', '291429', '293100', '28020000', '28070000', '28080000', '28100090', '28170000', '28182000', '28220000', '28230000', '28251000', '28258000', '28271000', '28273200', '28301000', '28341000', '28342100', '28362000', '28364000', '28366000', '28416100', '28443011', '28443051', '28459090', '28470000', '28492000', '28499030', '28500060', '29042000', '29054500', '29071590', '29072200', '29110000', '29124100', '29130000', '29141100', '29142200', '29161100', '29161200', '29161400', '29171100', '29171200', '29171400', '29173200', '29173500', '29173600', '29181400', '29181500', '29182100', '29182200', '29182900', '29242300', '29261000', '29270000', '29280090', '29291000', '29299000', '29302000', '29303000', '29304090', '29306000', '29307000', '29308000', '29309013', '29309016', '29309098', '29321200', '29321300', '29322090', '29336100', '29351000', '29352000', '29353000', '29354000', '29355000', '29359090', '29400000', '29412030', '29420000'], ['2937', '2939', '290544', '28046900', '29054300']),
    'S-9a': (['44', '4410', '4411', '4412', '441810', '44182010', '44187310', '44187400', '44201011', '44209010', '44209091'], []),
    'S-11a': (['50', '51', '52', '53', '54', '55', '56', '57', '58', '59', '60'], ['5105']),
    'S-14': (['71', '7117'], []),
    'S-15a': (['73', '7202'], []),
    'S-15b': (['74', '76', '78', '79', '81', '82', '83', '780199', '75051200', '75052200', '75062000', '75072000', '81019400', '81041100', '81041900', '81072000', '81082000', '81083000'], ['7601', '7801', '7901', '7903', '811292', '81011000', '81021000', '81029400', '81092000', '81101000', '81122190', '81125100', '81125900', '81130020']),
    'S-17a': (['86'], []),
    'S-17b': (['87', '88', '89', '8702', '8703', '8704', '8705', '8707', '8708', '8709', '8711', '8714', '870600', '871200'], []),
}
GRADUATED = {
    'IND': ('S-6a', 'S-11a', 'S-14', 'S-15a', 'S-15b', 'S-17a', 'S-17b'),
    'IDN': ('S-1a', 'S-3', 'S-5', 'S-9a'),
    'KEN': ('S-2a',),
}

# In-quota rate, out-of-quota rate, 2022 in-quota imports and quota, in tonnes
# and percent. Copied from an earlier internal build/build/v36_korea.py,
# the 2022 MAFRA WTO TRQ plan and G/AG/N/KOR/93 Table MA:2. A heading is here
# only when that source names every national line. Feed barley 100390 is not
# here: the v3.7 source left it because the annex names no subheading and
# there is no single out-of-quota rate.
KOREA_TRQ_PLAN = (
    ('100610', 'rice', 5.0, 513.0, 312586.0, 408700.0, 'KORQ041'),
    ('100620', 'rice', 5.0, 513.0, 312586.0, 408700.0, 'KORQ041'),
    ('100630', 'rice', 5.0, 513.0, 312586.0, 408700.0, 'KORQ041'),
    ('100640', 'rice', 5.0, 513.0, 312586.0, 408700.0, 'KORQ041'),
    ('091011', 'ginger', 20.0, 377.3, 0.0, 1860.0, 'KORQ034'),
    ('091012', 'ginger', 20.0, 377.3, 0.0, 1860.0, 'KORQ034'),
    ('090210', 'green tea', 40.0, 513.6, 5.86, 7.8, 'KORQ033'),
    ('090220', 'green tea', 40.0, 513.6, 5.86, 7.8, 'KORQ033'),
    ('010310', 'breeding swine', 0.0, 18.0, 0.0, 1850.0, 'KORQ002'),
    ('070110', 'seed potatoes', 0.0, 304.0, 0.0, 1898.0, 'KORQ018'),
    ('070190', 'potatoes', 30.0, 304.0, 10299.47, 18810.0, 'KORQ019'),
    ('100210', 'rye seed', 3.0, 108.7, 0.0, 1327.3, 'KORQ035'),
    ('100410', 'oat seed', 3.0, 554.8, 0.0, 597.3, 'KORQ038'),
    ('100710', 'sorghum seed', 3.0, 779.4, 0.0, 13.7, 'KORQ042'),
    ('100810', 'buckwheat', 3.0, 256.1, 1128.0, 1328.0, 'KORQ043'),
    ('100840', 'other cereals', 3.0, 800.3, 1128.0, 1328.0, 'KORQ043'),
    ('100850', 'other cereals', 3.0, 800.3, 1128.0, 1328.0, 'KORQ043'),
    ('100860', 'other cereals', 3.0, 800.3, 1128.0, 1328.0, 'KORQ043'),
    ('100890', 'other cereals', 3.0, 800.3, 1128.0, 1328.0, 'KORQ043'),
    ('080521', 'Korean citrus', 50.0, 144.0, 1106.0, 2097.0, 'KORQ031'),
    ('080590', 'Korean citrus', 50.0, 144.0, 1106.0, 2097.0, 'KORQ031'),
    ('010221', 'breeding cattle', 0.0, 89.1, 0.0, 1067.0, 'KORQ001'),
    ('010231', 'breeding cattle', 0.0, 89.1, 0.0, 1067.0, 'KORQ001'),
    ('040291', 'evaporated milk', 40.0, 89.0, 24.79, 130.0, 'KORQ009'),
    ('040299', 'evaporated milk', 40.0, 89.0, 24.79, 130.0, 'KORQ009'),
    ('040410', 'whey', 20.0, 49.5, 21947.55, 54233.0, 'KORQ010'),
    ('040510', 'butter', 40.0, 89.0, 19.17, 420.0, 'KORQ011'),
    ('040590', 'butter', 40.0, 89.0, 19.17, 420.0, 'KORQ011'),
    ('040900', 'natural honey', 20.0, 243.0, 271.46, 420.0, 'KORQ013'),
    ('151550', 'sesame oil', 40.0, 630.0, 636.3, 668.0, 'KORQ057'),
    ('500100', 'silk-worm cocoons', 2.0, 51.0, 0.0, 1143.0, 'KORQ066'),
    ('100510', 'seed maize', 0.0, 328.0, 181.27, 247.0, 'KORQ039'),
    ('070960', 'peppers', 50.0, 270.0, 999.8, 7185.0, 'KORQ022'),
    ('090421', 'peppers', 50.0, 270.0, 999.8, 7185.0, 'KORQ022'),
    ('090422', 'peppers', 50.0, 270.0, 999.8, 7185.0, 'KORQ022'),
    ('120740', 'sesame seed', 40.0, 630.0, 6731.0, 6731.0, 'KORQ054'),
    ('080241', 'chestnuts', 50.0, 219.4, 2170.0, 2170.0, 'KORQ028'),
    ('080242', 'chestnuts', 50.0, 219.4, 2170.0, 2170.0, 'KORQ028'),
    ('110510', 'potato flour', 5.4, 304.0, 10.0, 10.0, 'KORQ046'),
    ('110520', 'potato flour', 5.4, 304.0, 10.0, 10.0, 'KORQ046'),
    ('110814', 'manioc starch', 9.0, 455.0, 2400.0, 2400.0, 'KORQ050'),
    ('040221', 'whole milk powder', 40.0, 176.0, 573.0, 573.0, 'KORQ008'),
    ('040229', 'whole milk powder', 40.0, 176.0, 573.0, 573.0, 'KORQ008'),
)
# Article 71, annex table 3, amended 31 December 2021. Feed 11,000,000 t and
# processing 1,980,000 t, in-quota rate 0. KORUS imports are taken out of the
# numerator (Guimbard et al. 2012 p.11 fn.14). BACI 2022 HS 100590, importer
# 410: total 11,874,578.984 t, of which USA (842) is 1,488,019.593 t.
# KORQ040 is not added: it also covers maize starch and preparations.
# art71_only_fill keeps all-import / article-71 volume beside the rate.
# Soy 120190 stays on the v3.9 tonnage blend. Oats 100490 have no quantity cap.
MAIZE_BACI_T = 11874578.984
MAIZE_KORUS_T = 1488019.593
MAIZE_IMPORTS_T = MAIZE_BACI_T - MAIZE_KORUS_T
MAIZE_ART71_T = 11000000.0 + 1980000.0


# korea_article71: soy, crude and LNG legal blends (PR #73 sources; constants carried over from the retired builder).
# Soy: article 71 zero volume 1,200,000 t; the excess pays the in-quota 5 percent (KORQ052).
SOY_TONNES = 1_302_775.929
SOY_ZERO_TONNES = 1_200_000.0
SOY_IN_QUOTA = 5.0
# Crude: annex barrel ceilings against 1,031.28 million barrels imported in 2022.
CRUDE_BARRELS = 1_031.28e6
NAPHTHA_BARRELS = 206e6
LPG_CRUDE_BARRELS = 39.5e6
CRUDE_BASIC = 3.0
# LNG: January-April 0, May-September 3 (basic), October-December 2.
LNG_MONTHS = ((4, 0.0), (5, 3.0), (3, 2.0))
EMERGENCY_DAYS = {'long': 165, 'onion': 104, 'full': 365}   # 20 Jul-31 Dec 2022; 20 Jul-31 Oct 2022
MAIZE_ART71_T = 11000000.0 + 1980000.0


def soy_rate():
    return (SOY_TONNES - SOY_ZERO_TONNES) * SOY_IN_QUOTA / SOY_TONNES


def crude_rate():
    residual = CRUDE_BARRELS - NAPHTHA_BARRELS - LPG_CRUDE_BARRELS
    return (NAPHTHA_BARRELS * 0.5 + LPG_CRUDE_BARRELS * 2.0 + residual * CRUDE_BASIC) / CRUDE_BARRELS


def lng_rate():
    return sum(m * r for m, r in LNG_MONTHS) / sum(m for m, _r in LNG_MONTHS)


def korea_article71_lines(path=None):
    """config/s10/korea_article71_lines.csv -> {hs6: (legal percent, component)}."""
    path = path or os.path.join(CONFIG_DIR, 'korea_article71_lines.csv')
    out = {}
    with open(path, newline='', encoding='utf-8') as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise SystemExit('korea_article71_lines.csv is empty')
    for row in rows:
        hs = row['hs6'].zfill(6)
        if row['kind'] == 'partial_zero':
            frac = EMERGENCY_DAYS[row['window']] / 365.0
            legal = float(row['old_rate_pct']) * (1.0 - frac)
        else:
            legal = float(row['new_rate_pct'])
        if hs in out:
            raise SystemExit(f'korea_article71_lines.csv repeats {hs}')
        out[hs] = (legal, row['component'])
    return out


def trq_shadow(fill, tin, tout):
    """trq_fill_rule (Guimbard, Jean, Mimouni and Pichot 2012 pp.10-11): <90% in-quota, >98% out-of-quota, else the mean."""
    if fill < 0.90:
        return tin, 'in_quota'
    if tout is None:
        raise SystemExit('a TRQ fill at or above 90 percent needs one out-of-quota rate')
    if fill <= 0.98:
        return (tin + tout) / 2.0, 'midpoint'
    return tout, 'out_of_quota'


# trq_fill_measure alternative baci_2022_hs6_tonnes_over_quota (fix list B3): BACI HS22 2022 Korea (410)
# imports in tonnes, summed over the HS6 headings of each quota. Guimbard et al. 2012 p.10 measure the
# fill with observed imports. The HS6 can hold lines outside the quota (seed and table potatoes, starch),
# so this overstates the fill where the quota covers part of a heading. Not the decided measure.
KOREA_TRQ_BACI_T = {
    'KORQ001': 116.068, 'KORQ002': 125.573, 'KORQ008': 6890.84, 'KORQ009': 220.159, 'KORQ010': 35985.127,
    'KORQ011': 23535.935, 'KORQ013': 1335.869, 'KORQ018': 970.362, 'KORQ019': 40196.344, 'KORQ022': 10931.272,
    'KORQ028': 2842.898, 'KORQ031': 601.971, 'KORQ033': 57.05, 'KORQ034': 4391.868, 'KORQ035': 3782.9,
    'KORQ038': 140.553, 'KORQ039': 280.399, 'KORQ041': 483223.384, 'KORQ042': 592.843, 'KORQ043': 4665.955,
    'KORQ046': 5221.936, 'KORQ050': 35981.165, 'KORQ054': 84312.521, 'KORQ057': 770.007, 'KORQ066': 0.671,
}
TRQ_MEASURE_PLAN = 'plan_in_quota_utilisation_departure_from_imports_over_quota'


def korea_trq_rates(measure=TRQ_MEASURE_PLAN):
    """HS6 -> spec. korea_trq_full_fill: imports equal to the quota is a notified full fill (out-of-quota).
    trq_fill_measure: the MAFRA plan in-quota imports (decided), or BACI 2022 tonnes over the quota."""
    out = {}
    for hs, product, tin, tout, imported, quota, tqid in KOREA_TRQ_PLAN:
        if measure != TRQ_MEASURE_PLAN:
            imported = KOREA_TRQ_BACI_T[tqid]
        fill = imported / quota
        rate, regime = trq_shadow(fill, tin, tout)
        if hs in out:
            raise SystemExit(f'Korea TRQ plan repeats {hs}')
        out[hs] = dict(hs6=hs, product=product, rate=rate, regime=regime, fill=fill, in_quota=tin,
                       out_of_quota=tout, imports_t=imported, quota_t=quota, tqid=tqid,
                       source='mafra_2022_plan_and_g_ag_n_kor_93' if measure == TRQ_MEASURE_PLAN
                       else 'baci_2022_tonnes_and_g_ag_n_kor_93')
    # maize_trq_basis: article 71 volume, KORUS (USA) BACI tonnes taken out of the numerator.
    fill = MAIZE_IMPORTS_T / MAIZE_ART71_T
    rate, regime = trq_shadow(fill, 0.0, None)
    out['100590'] = dict(hs6='100590', product='maize', rate=rate, regime=regime, fill=fill, in_quota=0.0,
                         out_of_quota=None, imports_t=MAIZE_IMPORTS_T, quota_t=MAIZE_ART71_T, tqid='ART71',
                         source='article71_table3_baci2022_excluding_korus')
    # Oats 100490: article 71 zero with no quantity cap.
    out['100490'] = dict(hs6='100490', product='oats', rate=0.0, regime='applied_tariffs', fill=None, in_quota=0.0,
                         out_of_quota=None, imports_t=None, quota_t=None, tqid='',
                         source='article71_table3_all_imports_no_cap')
    return out


# iraq_tariffs and iraq_statutory_rates: Resolution 393/2017 chapter bands; food chapters 01-24
# at zero for 6.5 of 12 months in 2022, so the band times 5.5/12. No collections scaling.
def iraq_band(chapter):
    if 1 <= chapter <= 21 or chapter == 23:
        return 10.0
    if chapter in (22, 24, 85, 93, 97):
        return 30.0
    if chapter == 71:
        return 0.5
    if 25 <= chapter <= 27 or 41 <= chapter <= 70 or 86 <= chapter <= 92 or 94 <= chapter <= 96:
        return 15.0
    if 28 <= chapter <= 40 or 72 <= chapter <= 84:
        return 10.0
    return None


def iraq_rate(hs):
    chapter = int(hs[:2])
    band = iraq_band(chapter)
    if band is None:
        return None
    return band * 5.5 / 12.0 if chapter <= 24 else band


PRK_FLAT = 5.5               # prk_tariff: 2005 DPRK tariff manual average
KHM_GASOLINE = 10.2          # cambodia_271012
MOROCCO_WHEAT = ('100111', '100119', '100191', '100199')   # morocco_wheat
# ncl_schedule: Tarif des douanes de Nouvelle-Calédonie (1 January 2023), Dispositions particulières 2(b):
# goods originating in the EU member states and the associated OCTs are admitted free of DD. The OCTs
# are those of Council Decision (EU) 2021/1764 Annex II other than New Caledonia itself.
NCL_DD_EXEMPT = frozenset({
    'AUT', 'BEL', 'BGR', 'HRV', 'CYP', 'CZE', 'DNK', 'EST', 'FIN', 'FRA', 'DEU', 'GRC', 'HUN', 'IRL', 'ITA',
    'LVA', 'LTU', 'LUX', 'MLT', 'NLD', 'POL', 'PRT', 'ROU', 'SVK', 'SVN', 'ESP', 'SWE',
    'GRL', 'PYF', 'ATF', 'WLF', 'SPM', 'BLM', 'ABW', 'BES', 'CUW', 'SXM',
})
# tunisia_schedule: Finance Law 2018 art. 39 raises the 20 percent rate on chapters 25-97 to 30.
TUN_RAISE_FROM, TUN_RAISE_TO = 20.0, 30.0
# Tunisia-Turkey (v3.4 rule, tunisia_schedule row): chapters 25-97 free, except these chapters,
# which take min(base, 0.9 base, 25).
# tunisia_schedule: Finance Law 2018 (Loi 2017-66) art. 40, as amended by Finance Law 2020 (Loi 2019-78) art. 52:
# Turkish List II goods in these chapters pay up to 90% of the MFN rate from 1 January 2018 for four years, then the
# duty is removed over three years in equal annual steps. 2022 is the first step: two thirds of 90%.
TUN_TUR_LF2018_CHAPTERS = frozenset({33, 34, 40, 48, 61, 62, 63, 64, 72, 76, 84, 85})
TUN_TUR_LF2018_SHARE_2022 = 0.9 * 2.0 / 3.0
GAFTA = frozenset({'BHR', 'EGY', 'IRQ', 'JOR', 'KWT', 'LBN', 'LBY', 'MAR', 'OMN', 'QAT', 'SAU', 'SDN', 'SYR', 'ARE', 'YEM'})
# egypt_mixed_sublines (fix list B3): the HS6 rate is the non-alcoholic national line of Decree 218/2022.
# TRAINS (2019 H5, Reported, NBR_NA_LINES 0) gives the simple average of national lines that include the
# alcoholic compound preparations at 3000 percent. hs6 -> (rate, citation).
EGY_MIXED_SUBLINES = {
    '330210': (5.0, 'Decree 218/2022 PDF p.162: 3302.1010 alcoholic preparations for drinks 3000; 3302.1090 other 5'),
    '210690': (10.0, 'Decree 218/2022 PDF p.93: 2106.9010 medical food preparations exempt; 2106.9020 alcoholic '
                     'compound preparations 3000; 2106.9090 other 10'),
}
# Egypt 240220 (ave_outlier_rule class A): EGP 100 per kg net, Decree 419/2018 p.96 and Decree 218/2022 p.99.
EGY_240220_EGP_PER_KG = 100.0
# us_gsp_lapse
US_GSP_CODES = frozenset({'B11', 'C06', 'C53', 'C69', '01R', 'B15'})
CPTPP_DROP = frozenset({'CHL', 'BRN'})
RCEP_DROP = frozenset({'IDN', 'PHL', 'MMR'})


def _match(hs, prefix):
    return hs.startswith(prefix) or prefix.startswith(hs)


def in_section(hs, section):
    includes, excludes = GSP_RULES[section]
    hit = [p for p in includes if _match(hs, p)]
    if not hit:
        return False
    best = max(len(p) for p in hit)
    return not any(_match(hs, p) and len(p) > best for p in excludes)


def gsp_banned(hs, code, exp):
    """eu_gsp_graduation, cambodia_eba_withdrawal, eu_gsp_armenia: exporter barred from this EU offer on this line."""
    if code == '01T' and exp in GRADUATED and any(in_section(hs, s) for s in GRADUATED[exp]):
        return True
    if code in ('01T', '01U', '01W') and exp == 'KHM' and any(hs.startswith(p) for p in CAMBODIA_EBA):
        return True
    return code in ('01T', '01W') and exp == 'ARM'


def is_us_gsp(imp, code, name):
    if imp != 'USA':
        return False
    blob = (name or '').lower()
    return code in US_GSP_CODES or 'united states gsp' in blob or 'gsp beneficiaries: usa' in blob or 'gsp beneficiaries:usa' in blob


# beta v5 K and S5 (David 2026-10-27 package approval): sourced HS6 line overrides behind switches that are off until
# a source is on disk. config/s10/sourced_line_overrides.csv: iso, hs6, rate_pct, switch, how, source, note.
SOURCED_LINES_PATH = os.path.join(CONFIG_DIR, 'sourced_line_overrides.csv')
SOURCED_LINE_COLUMNS = ('iso', 'hs6', 'rate_pct', 'switch', 'how', 'source', 'note')


def sourced_lines(choices, path=SOURCED_LINES_PATH):
    """[(iso, hs6, rate_pct, how)] for the rows whose switch choice is not 'off'. A switch that is on must have rows,
    and every row must name a source that is not a placeholder."""
    with open(path, newline='', encoding='utf-8') as fh:
        rows = [{k: (v or '').strip() for k, v in r.items()} for r in csv.DictReader(fh)]
    out, by_switch = [], {}
    for r in rows:
        if any(c not in r for c in SOURCED_LINE_COLUMNS):
            raise ConfigError(f'{path} lacks columns {[c for c in SOURCED_LINE_COLUMNS if c not in r]}')
        if r['switch'] not in choices:
            raise ConfigError(f'{path}: {r["iso"]} {r["hs6"]} names unknown switch {r["switch"]}')
        by_switch.setdefault(r['switch'], []).append(r)
    for switch in SOURCED_LINE_SWITCHES:
        if choices.get(switch, 'off') == 'off':
            continue
        got = by_switch.get(switch, [])
        if not got:
            raise ConfigError(f'{switch} is on but {path} has no rows for it (source not transcribed)')
        for r in got:
            if not r['source'] or r['source'].lower().startswith('pending'):
                raise ConfigError(f'{switch} is on but {r["iso"]} {r["hs6"]} has no source ({r["source"] or "blank"})')
            out.append((r['iso'], r['hs6'], float(r['rate_pct']), r['how']))
    return out


SOURCED_LINE_SWITCHES = ('tariff_pak_lng_concession', 'tariff_bgd_nbr_fuel')
