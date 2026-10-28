"""S10 tariff build: sources -> schedules -> line rates -> BACI-weighted region cells -> tm.

Order of the method (GTAP 12 ch.11B): HS6 best-applied rate, then BACI weights, then the
named overrides, which sit on the schedules before the minimum with preferences.
"""
import csv
import gzip
import io
import os
import re
import zipfile
from collections import defaultdict

from . import addon as addon_mod
from . import overrides as ov
from . import preferences as prefs
from . import rates as R
from . import sources
from . import trq as trq_mod
from . import weights as W
from .codes import join_report
from .config import ConfigError, read_table
from .preferences import EU27
from .util import fnum, gz_write, write_csv

HEADER = ['importer', 'partner', 'sector_code', 'sector_name', 'rate_pct', 'mfn_rate_pct', 'rate_pct_simple_mfn',
          'regime', 'agreement', 'weight_rule', 'customs_rule', 'weight_thousand_usd', 'schedule_year', 'fill_source',
          'quota_rent_thousand_usd']
FAMILY_SPOTS = (('BIH', 'DEU', ('A36', 'A84')), ('BIH', 'SRB', ('B30', 'C35')),
                ('VNM', 'IDN', ('N52', 'C02')), ('CHN', 'LAO', ('A94', 'N52')))
# Members with no 2022 trade and no region (historic BACI labels on WITS group lists).
NO_TRADE_MEMBERS = {'MYT', 'PUS', 'SCG', 'CSK', 'SUN', 'ZA1', 'ESH', 'FRO'}
ADDON_NOTE = ('Scenario shock. Not in baseline tm. David 2026-10-21. GTAP 12 ch.11B §B.4. A post-S16 variant '
              'may scale this file to assessed collections.')


def _earlier_ave(path):
    blob = open(path, 'rb').read()
    m = re.search(br'OBS_VALUE="([0-9.]+)"', blob) or re.search(br'<generic:ObsValue[^>]*value="([0-9.]+)"', blob)
    return float(m.group(1)) if m else None


def _zmb_bulk(zip_path, codes):
    out = {hs: [] for hs in codes}
    with zipfile.ZipFile(zip_path) as outer:
        for year in ('2020', '2021'):
            inner = zipfile.ZipFile(io.BytesIO(outer.read(f'AVEMFN_H5_ZMB_{year}_U2.zip')))
            name = [n for n in inner.namelist() if n.lower().endswith('.csv')][0]
            for row in csv.DictReader(io.StringIO(inner.read(name).decode('utf-8', 'replace'))):
                code = (row.get('ProductCode') or '').strip().zfill(6)
                if code in out and (row.get('SimpleAverage') or '').strip():
                    out[code].append((year, float(row['SimpleAverage'])))
    return out


class TariffBuild:
    """Holds every object the checks and reports read."""

    def __init__(self, S, C, P, sets):
        self.S, self.C, self.P, self.sets = S, C, P, sets
        self.cm = sets['codemap']

    # ------------------------------------------------------------ sources and schedules
    def load(self):
        S, C, P, cm = self.S, self.C, self.P, self.cm
        S.log('reading TRAINS MFN schedules')
        self.schedules, missing_files = sources.load_mfn(P['mfn_manifest'], P['mfn_tars'], cm)
        if missing_files:
            raise ConfigError('MFN manifest files not found in the tars: ' + ' '.join(missing_files[:8]))
        S.log('reading WITS preference files')
        national, self.mys_stats = sources.national_preferences(P['mys_pref'], prefs.load_national_agreements(cm))  # mys_preference_schedules
        self.merged, self.pref_counts = sources.load_preferences(P['pref_zip'], P['pref_dir'], P['supp_dir'], cm, national)
        # trq_outside_kor_pan: the MAcMap fill rule on the quota-line pairs of CAN, CHE, JPN and CHN, on the MFN
        # schedule and the bulk preference lines, before the minimum with preferences (round-3 fix wE2)
        self.trq_rows, self.trq_expect, self.trq_pref = trq_mod.apply(
            self.schedules, self.merged, trq_mod.read_ma2(P['ma2']), P['mfn_ave_bulk'], P['pref_zip'],
            C['trq_outside_kor_pan'], S.log)
        self.groups, self.uk_removed, self.group_problems = prefs.load_groups(P['beneficiaries'], cm)
        self.uk_applied = prefs.load_uk_continuity()
        self.lapses = prefs.load_lapses(cm)
        self.state = prefs.build_state(self.merged, self.groups, self.uk_removed, self.uk_applied, self.lapses,
                                       prefs.load_families(), prefs.load_remap(cm), cm)
        self.nomen = R.Nomen(P['concord'], P['earlier'])
        self.schedules['NCL'] = sources.ncl_schedule(P['ncl_dd'], P['ncl_dd22'])                       # ncl_schedule
        tun, self.tun_raised = R.tunisia_schedule(P['tun_xml'])
        self.schedules['TUN'] = tun
        self.kl, self.kl_stats = sources.hts_kl_rates(P['hts'])
        self.raw_before = R.apply_overrides(self.schedules, self.nomen, self.kl, S.log,
                                            kl_overlay=C['usa_pharma_appendix'].startswith('hts_2022'),
                                            trq_measure=C['trq_fill_measure'],
                                            egy_sublines=C['egypt_mixed_sublines'].startswith('non_alcoholic'),
                                            sourced=ov.sourced_lines(C))
        self.tpa = R.panama_tpa(P['tpa_hs22'], P['tpa_lines'], P['trq'])
        self.unions = R.Unions()
        self.tariffs = R.Tariffs(self.schedules, self.state, self.nomen, self.unions, self.tpa, self.uk_applied,
                                 turkey_rule='turkey_fta_protocol1' in C['tunisia_schedule'],
                                 parents=R.load_parent_territories(), tun_lists=R.load_tun_lists(P['tun_lists']))
        S.log(f"schedules {len(self.schedules)}; preference files {self.pref_counts}; agreements "
              f"{sum(len(v) for v in self.state['agreements'].values())}; TPA lines {len(self.tpa)}; "
              f"Tunisia lines raised {self.tun_raised}; US K/L HS6 {self.kl_stats['hs6']}")

    # ------------------------------------------------------------ BACI
    def weigh(self):
        S, P, cm, goods = self.S, self.P, self.cm, self.sets['goods']
        S.log('BACI pass 1: totals')
        self.tot = W.pass_totals(P['baci_csv'], cm, self.nomen, goods)
        self.egy_uv = self.tot['egy_v'] / self.tot['egy_q'] if self.tot['egy_q'] > 0 else None
        if not self.egy_uv:
            raise ConfigError('Egypt 240220 has no BACI quantity; class A cannot be applied')
        self.egy_fx = R.egypt_fx(P['egy_fx'])
        self.egy_ave, self.egy_before = R.egypt_240220(self.schedules, self.nomen, self.egy_uv, self.egy_fx)
        extra = addon_mod.us_extra(P['hts'])
        cal, default = addon_mod.calendar()
        self.addon = addon_mod.AddonAccumulator(extra, cal, default)
        S.log('BACI pass 2: line rates on the 2021-2023 weight years')
        # tariff_weights: 3-year average imports around 2022 (ch.11B §B.2-B.3)
        self.years = W.WeightYears([(2021, 'hs17', P['baci_zip17'], 'BACI_HS17_Y2021_V202601.csv'),
                                    (2022, 'hs22', P['baci_csv'], None),
                                    (2023, 'hs22', P['baci_zip22'], 'BACI_HS22_Y2023_V202601.csv')],
                                   W.hs17_to_hs22(P['hs_corr']), self.tot['world'])
        self.acc = W.pass_rates(self.years, cm, self.nomen, goods, self.tariffs, self.addon)
        self.ref = W.Reference(cm, self.nomen, goods, self.tariffs, self.acc.imp_w)
        S.log(f'priced BACI lines {self.acc.lines}; value with a rate {self.acc.priced / 1e6:.3f} bn')

    # ------------------------------------------------------------ cells
    def cells(self, vcif):
        """Rate per VCIF key (importer region, exporter region, sector). Cells with a BACI weight are
        bilateral; the rest take the NB1 reference rate; a cell with neither is missing (tm 0)."""
        acc = self.acc
        self.rate, self.mfn_cell, self.rule = {}, {}, {}
        for key in sorted(vcif):
            if vcif[key] == 0.0:
                continue
            if acc.den.get(key, 0.0) > 0:
                r = acc.num[key] / acc.den[key]
                m = acc.mnum[key] / acc.mden[key] if acc.mden.get(key, 0.0) > 0 else None
                rule = 'bilateral'
            else:
                r, m, rule = self.ref.cell(*key)
            if key[0] == 'TKM':
                rule = 'tkm_exception'
            self.rate[key] = 0.0 if r is None else r
            self.mfn_cell[key] = m
            self.rule[key] = rule if r is not None else ('tkm_exception' if key[0] == 'TKM' else 'missing')
        # A cell whose two regions hold only EU customs-territory members is a forced zero on every
        # good. Region FRA also holds ATF, which is outside the EU customs territory, so FRA as a
        # partner is priced by member ISO like any other region.
        eu = self.unions.eu_territory
        inside = {r for r in {k[0] for k in self.rate} | {k[1] for k in self.rate} if self.cm.members.get(r) and self.cm.members[r] <= eu}
        self.cu_cells = {k for k in self.rate if k[0] in inside and k[1] in inside}
        return self.rate

    # ------------------------------------------------------------ beta v5 S5
    def scale_to_collected(self, rows, collected, vcif):
        """tariff_collected_scale (beta v5 S5, a labelled departure: GTAP 12 ch.11B builds duties from applied rates
        times trade). For each listed importer, the listed sectors' cell rates are multiplied by
        min(1, collected duty / booked duty over all its goods cells). Returns {importer: detail} and keeps
        self.collected_scale {cell key: factor} for the S10-Hwedge independent values."""
        self.collected_scale, detail = {}, {}
        by_imp = defaultdict(set)
        for r in rows:
            by_imp[r['importer']].add(r['sector'])
        for imp, secs in sorted(by_imp.items()):
            if imp not in collected or collected[imp] <= 0:
                raise ConfigError(f'tariff_collected_scale {imp}: no collected customs duty row')
            booked = sum(vcif[k] * self.rate[k] / 100.0 for k in self.rate if k[0] == imp)
            listed = sum(vcif[k] * self.rate[k] / 100.0 for k in self.rate if k[0] == imp and k[2] in secs)
            if listed <= 0:
                raise ConfigError(f'tariff_collected_scale {imp}: no booked duty on {sorted(secs)}')
            f = min(1.0, collected[imp] / booked)
            for k in self.rate:
                if k[0] == imp and k[2] in secs:
                    self.rate[k] *= f
                    self.collected_scale[k] = f
            detail[imp] = {'sectors': sorted(secs), 'collected': collected[imp], 'booked_before': booked,
                           'listed_before': listed, 'factor': f, 'booked_after': booked - listed * (1.0 - f)}
        return detail

    # ------------------------------------------------------------ outputs
    def write(self, out, vcif, prev_dir):
        sets, acc = self.sets, self.acc
        s2i = sets['short_to_icio']
        tm_lines, vmsb_lines, duty_lines = [], [], []
        self.duty_region = defaultdict(float)
        self.duty_cell = {}
        self.wedge_rows = []
        for key in sorted(self.rate):
            imp, exp, short = key
            base = vcif[key]
            pct = self.rate[key]
            tm = pct / 100.0
            vmsb = base * (1.0 + tm)
            duty = base * tm
            self.duty_region[imp] += duty
            self.duty_cell[key] = (duty, base)
            self.wedge_rows.append((base, tm, vmsb, duty))
            tm_lines.append(f'{imp},{exp},{short},{fnum(tm)},{fnum(pct)},{self.rule[key]},cif\n'.encode())
            vmsb_lines.append(f'{imp},{exp},{short},{fnum(base)},{fnum(vmsb)},cif,basic\n'.encode())
            duty_lines.append(f'{imp},{exp},{short},{fnum(duty)},{fnum(base)},tariff wedge on cif\n'.encode())
        gz_write(out + '/tm_s10.csv.gz', b'importer,exporter,sector,tm,rate_pct,fill,price_basis\n', tm_lines)
        gz_write(out + '/vmsb_s10.csv.gz', b'importer,exporter,sector,vcif_musd,vmsb_musd,vcif_basis,vmsb_basis\n', vmsb_lines)
        gz_write(out + '/duty_bilateral_s10.csv.gz', b'importer,exporter,sector,duty_musd,vcif_musd,price_basis\n', duty_lines)
        self.world_duty = sum(d for d, _b in self.duty_cell.values())
        self.world_vcif = sum(b for _d, b in self.duty_cell.values())

        # hs6_applied: one row per cell priced (bilateral with weight, or NB1 for a VCIF cell).
        rows, lowered, above_100 = [], defaultdict(lambda: [set(), 0, set(), set()]), []
        for key in sorted(self.rate):
            imp, exp, short = key
            r, m, rule = self.rate[key], self.mfn_cell.get(key), self.rule[key]
            if rule in ('missing', 'tkm_exception'):
                continue
            regime = 'mfn'
            if key in self.cu_cells:
                regime = 'customs_union_internal'
            elif m is not None and r < m - 1e-4:
                regime = 'preference'
                lowered[imp][0].add(exp)
                lowered[imp][1] += 1
            sch = self.tariffs.schedule(imp)
            year = sch.year if sch is not None else ''
            if sch is not None:
                lowered[imp][2].add(str(sch.year))
                lowered[imp][3].add(sch.nomen)
            w = acc.den.get(key, 0.0)
            row = [imp, exp, s2i[short], short, fnum(r), fnum(m) if m is not None else '', '', regime, '',
                   rule, 'customs_union' if key in self.cu_cells else 'mfn', fnum(w), year,
                   sch.source if sch is not None else 'members', '0']
            rows.append(row)
            if r > 100.0:
                above_100.append([imp, exp, s2i[short], rule, '', fnum(r), '', fnum(m) if m is not None else '', fnum(w), regime])
        rows.sort(key=lambda r: (r[0], r[1], r[2]))
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator='\n')
        writer.writerow(HEADER)
        writer.writerows(rows)
        gz_write(out + '/hs6_applied_s10.csv.gz', b'', [buf.getvalue().encode()])
        self.applied_rows = rows
        write_csv(out + '/rate_pattern_s10.csv', ['importer', 'partner', 'sector', 'weight_rule', 'old_rate', 'new_rate',
                                                  'old_mfn', 'new_mfn', 'weight_thousand_usd', 'regime'], above_100)
        self.above_100 = len(above_100)
        pref_rows = []
        for imp in sorted({r[0] for r in rows}):
            slot = lowered[imp]
            pref_rows.append([imp, ' '.join(sorted(slot[2])), ' '.join(sorted(slot[3])), str(len(slot[0])), str(slot[1]),
                              'BACI 2021-2023 average weights; best applied at HS6'])
        write_csv(out + '/preference_fill_s10.csv', ['importer', 'source_years', 'nomenclature', 'partners',
                                                     'bilateral_cells_lowered', 'price_basis'], pref_rows)
        self.pref_importers = {r[0] for r in pref_rows if r[4] != '0'}

        # 301/232 scenario layer, priced on the baseline VCIF.
        add_rates = self.addon.rates()
        add_rows, self.scenario = [], {'301': 0.0, '232': 0.0, 'china': 0.0}
        for key in sorted(self.rate):
            imp, exp, short = key
            if imp != 'USA' or (exp, short) not in add_rates:
                continue
            a301, a232 = add_rates[(exp, short)]
            base = vcif[key]
            implied = base * (a301 + a232) / 100.0
            self.scenario['301'] += base * a301 / 100.0
            self.scenario['232'] += base * a232 / 100.0
            if exp == 'CHN':
                self.scenario['china'] += implied
            add_rows.append(['USA', exp, short, fnum(a301), fnum(a232), fnum(a301 + a232), fnum(base), fnum(implied), 'cif', ADDON_NOTE])
        write_csv(out + '/tariffs_301_232_addon_s10.csv', ['importer', 'partner', 'sector', 'addon_301_pct', 'addon_232_pct',
                                                           'addon_rate_pct', 'vcif_musd', 'implied_duty_musd', 'price_basis', 'note'],
                  add_rows)

        # Specific duties with no AVE (listed, no duty).
        spec = []
        for iso, sch in sorted(self.schedules.items()):
            for code, (value, na) in sorted(sch.specific.items()):
                trade = sum(v for (i, hs), v in acc.no_ave.items() if i == iso and self.nomen.code(sch.nomen, hs) == code) \
                    if iso != 'EUN' else sum(v for (i, hs), v in acc.no_ave.items() if i in EU27 and hs == code)
                spec.append((iso, code, str(sch.year), sch.nomen, fnum(value), str(na), fnum(trade)))
        spec.sort(key=lambda r: (-float(r[6]), r[0], r[1]))
        write_csv(out + '/specific_duty_no_ave_s10.csv', ['importer', 'hs6', 'year', 'nomen', 'reported_simple_average',
                                                          'nbr_na_lines', 'trade_thousand_usd'], spec)
        self.no_ave_trade = sum(acc.no_ave.values())

        # Korea TRQ and class A.
        trq = []
        for spec_ in ov.korea_trq_rates(self.C['trq_fill_measure']).values():
            def f(x):
                return fnum(x) if x not in (None, '') else ''
            trq.append([spec_['hs6'], spec_['product'], f(spec_['rate']), spec_['regime'], f(spec_['fill']), '',
                        f(spec_['in_quota']), f(spec_['out_of_quota']), f(spec_['imports_t']), f(spec_['quota_t']),
                        spec_['tqid'], spec_['source']])
        trq.sort()
        write_csv(out + '/korea_trq_s10.csv', ['hs6', 'product', 'rate_pct', 'regime', 'fill', 'article71_only_fill',
                                               'in_quota_pct', 'out_of_quota_pct', 'imports_tonnes', 'quota_tonnes', 'tqid',
                                               'source'], trq)
        write_csv(out + '/trq_fill_s10.csv', trq_mod.REPORT_COLUMNS, self.trq_rows)
        bulk = _zmb_bulk(self.P['mfn_ave_bulk'], set(ov.ZMB_ADVALOREM))
        cls = []
        for hs, stat in sorted(ov.ZMB_ADVALOREM.items()):
            earlier = [(y, _earlier_ave(os.path.join(self.P['earlier_dir'], f'ZMB_{hs}_{y}_aveestimated.xml')))
                       for y in ('2014', '2016') if os.path.exists(os.path.join(self.P['earlier_dir'], f'ZMB_{hs}_{y}_aveestimated.xml'))]
            earlier += bulk.get(hs, [])
            raw = self.raw_before.get(('ZMB', hs))
            cls.append(['ZMB', hs, fnum(stat), 'ad_valorem_alternative_simple_average', '', 'not_used_mixed_duty', '',
                        fnum(raw) if raw is not None else '', ' '.join(f'{y}:{v}' for y, v in earlier), ov.ZMB_BOOK[hs],
                        'baci fob where a unit value is used'])
        egy_earlier = [(y, _earlier_ave(os.path.join(self.P['earlier_dir'], f'EGY_240220_{y}_aveestimated.xml')))
                       for y in ('2014', '2015', '2016') if os.path.exists(os.path.join(self.P['earlier_dir'], f'EGY_240220_{y}_aveestimated.xml'))]
        cls.append(['EGY', '240220', fnum(self.egy_ave), 'specific_100_egp_per_kg_over_importer_unit_value', fnum(self.egy_uv),
                    'baci_2022_fob', fnum(self.egy_fx), fnum(self.egy_before) if self.egy_before is not None else '',
                    ' '.join(f'{y}:{v}' for y, v in egy_earlier),
                    'Decree 419/2018 p.96 and Decree 218/2022 p.99: EGP 100 per kg net', 'baci fob where a unit value is used'])
        write_csv(out + '/class_a_ave_s10.csv', ['importer', 'hs6', 'statutory_ave', 'method', 'unit_value_usd', 'unit_value_basis',
                                                 'fx_lcu_per_usd', 'raw_ave', 'earlier_unctad', 'book_rate', 'price_basis'], cls)

        # Comparison with the previous output: cell rate moves and importer x sector duty.
        self.compare(out, prev_dir)

    def compare(self, out, prev_dir):
        diffs, delta = [], []
        prev_tm = os.path.join(prev_dir, 'tm_s10.csv.gz') if prev_dir else ''
        prev_vm = os.path.join(prev_dir, 'vmsb_s10.csv.gz') if prev_dir else ''
        self.prev_duty_world = None
        if prev_dir and os.path.exists(prev_tm) and os.path.exists(prev_vm):
            old = {}
            with gzip.open(prev_tm, 'rt', newline='') as fh:
                for row in csv.DictReader(fh):
                    old[(row['importer'], row['exporter'], row['sector'])] = (float(row['rate_pct']), row['fill'])
            old_duty, new_duty = defaultdict(float), defaultdict(float)
            world = 0.0
            with gzip.open(prev_vm, 'rt', newline='') as fh:
                for row in csv.DictReader(fh):
                    key = (row['importer'], row['exporter'], row['sector'])
                    base = float(row['vcif_musd'])
                    o = old.get(key, (0.0, ''))
                    world += base * o[0] / 100.0
                    old_duty[(key[0], key[2])] += base * o[0] / 100.0
                    n = self.rate.get(key, 0.0)
                    if abs(n - o[0]) > 0.1:
                        diffs.append([key[0], key[1], key[2], o[1], self.rule.get(key, ''), fnum(o[0]), fnum(n), fnum(base),
                                      fnum((n - o[0]) / 100.0 * base)])
            for key, (duty, _b) in self.duty_cell.items():
                new_duty[(key[0], key[2])] += duty
            for k in sorted(set(old_duty) | set(new_duty)):
                if abs(new_duty[k] - old_duty[k]) > 0.5:
                    delta.append([k[0], k[1], fnum(old_duty[k]), fnum(new_duty[k]), fnum(new_duty[k] - old_duty[k])])
            self.prev_duty_world = world
        diffs.sort(key=lambda r: (-abs(float(r[8])), r[0], r[1], r[2]))
        write_csv(out + '/hs6_weight_diffs_s10.csv', ['importer', 'partner', 'sector', 'old_fill', 'new_fill', 'old_rate_pct',
                                                      'new_rate_pct', 'vcif_musd', 'duty_delta_musd'], diffs)
        write_csv(out + '/hs6_applied_delta_s10.csv', ['importer', 'sector', 'duty_old_musd', 'duty_new_musd', 'delta_musd'], delta)
        self.n_diffs = len(diffs)

    # ------------------------------------------------------------ check inputs
    def join(self):
        reporters = {iso for iso in self.schedules} | {rec['iso'] for rec in self.merged.values()}
        unmapped = sorted({c for _i, c, _y in self.state['log'].get('unmapped_numeric', []) if c not in ('234', '732')})
        baci_value = defaultdict(float)
        for code, v in self.tot['unmapped'].items():
            baci_value[code] += v
        rep = join_report(self.cm, baci_value, prefs.member_isos(self.state), reporters, unmapped)
        rep['reporters'] = [r for r in rep['reporters'] if r not in ('WLF',)]
        return rep

    def override_expect(self):
        exp = [('ZMB', hs, v, 'class_a_ad_valorem') for hs, v in ov.ZMB_ADVALOREM.items()]
        exp += [('KOR', '120190', ov.soy_rate(), 'korea_soy'), ('KOR', '270900', ov.crude_rate(), 'korea_crude'),
                ('KOR', '271111', ov.lng_rate(), 'korea_lng'), ('KOR', '271121', ov.lng_rate(), 'korea_lng')]
        exp += [('KOR', hs, legal, comp) for hs, (legal, comp) in ov.korea_article71_lines().items()]
        exp += [('KOR', hs, spec['rate'], 'korea_trq') for hs, spec in ov.korea_trq_rates(self.C['trq_fill_measure']).items()]
        exp += [('MAR', hs, 0.0, 'morocco_wheat') for hs in ov.MOROCCO_WHEAT]
        exp += [('KHM', '271012', ov.KHM_GASOLINE, 'cambodia_271012'), ('EGY', '240220', self.egy_ave, 'class_a_specific')]
        if self.C['egypt_mixed_sublines'].startswith('non_alcoholic'):
            exp += [('EGY', hs, rate, 'egypt_mixed_subline') for hs, (rate, _c) in ov.EGY_MIXED_SUBLINES.items()]
        exp += list(ov.sourced_lines(self.C))
        return exp

    def ave_1000(self):
        """AVE-sourced lines at or above 1,000 percent with 2022 trade (before the class A replacement)."""
        traded = defaultdict(float)
        for (iso, hs), v in self.tot['imp_hs'].items():
            sch = self.tariffs.schedule(iso)
            if sch is not None:
                code = self.nomen.code(sch.nomen, hs)
                if code:
                    traded[(iso, code)] += v
        out = []
        for iso, sch in self.schedules.items():
            for member in (sorted(EU27) if iso == 'EUN' else [iso]):
                for code, value in sch.ave.items():
                    if value >= 1000.0 and code not in sch.reported and traded.get((member, code), 0.0) > 0:
                        out.append((member, code, value, traded[(member, code)]))
        return sorted(out)


def known_outliers():
    return {(r['importer'], r['hs6']) for r in read_table('ave_outlier_lines.csv', ('importer', 'hs6', 'class'))}
