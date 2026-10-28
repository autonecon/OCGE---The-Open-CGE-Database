"""S13 product-tax money of representative-table regions from tax statistics (s13 choice product_tax_source;
round-3 final QA2 item 1).

A region whose I-O table is built from S05 donors (ch.9D representative tables, composite members) carries in io_s12
the donor's product-tax money pattern scaled to the region: for a region without a VAT that is a VAT it does not levy
(KWT from CYP). GTAP takes the I-O structure from the representative table (ch.9D: the structure of production,
intermediate usage and consumption) and the tax wedges from tax statistics: ch.8 Appendix A (Angola) puts the tax
rates on the I-O flows and scales the expected revenue to the actual revenue reported in the government accounts, and
ch.15 takes government revenue from the IMF GFS. So for these regions the general (non-energy-excise) part of the
product tax is set to the IMF GFS taxes on goods and services (G114, % of GDP; general government where reported,
else the central government series) times the region's S02 GDP, less the energy excise S13 books separately (fix
list A1, the positive energy-tax part on the io_s12 flows). Where no 2022 G114 value covers the region, its rates
are held (no money hold), not the donor's money.

The G114 source is the IMF World Revenue Longitudinal Data (data/imf_world, WoRLD), the IMF FAD compilation of GFS
revenue by GFS category (G114 is the GFS code). A composite takes the GDP-weighted mean of its members' G114 shares
when the members with a value cover at least G114_COVER_MIN of the members' S02 GDP.
"""
import numpy as np
import pandas as pd

G114_YEAR = 2022
G114_SECTORS = ('S13', 'S1311MIXED')       # general government first, else the WoRLD central-government series
G114_COVER_MIN = 0.90                      # our rule (not in the GTAP text): the members with a value cover 90% of GDP
NO_VAT_2022 = ('KWT', 'QAT', 'IRQ', 'LBY')  # no general sales tax or VAT in 2022 (S13-Rnovat)
NO_VAT_RATE_MAX = 0.02
EXCISE_CAP_G114 = 'positive_energy_excise_scaled_to_imf_gfs_g114_where_it_exceeds_it'   # beta v4 G15 (s13 choice excise_cap_g114)


def g114_shares(world, year=G114_YEAR, sectors=G114_SECTORS):
    """{country: (G114 % of GDP, sector)} for the year from the WoRLD csv frame (COUNTRY, GFS_STO, SECTOR,
    TIME_PERIOD, OBS_VALUE); the first sector of `sectors` with a finite value."""
    w = world[(world['GFS_STO'] == 'G114') & (pd.to_numeric(world['TIME_PERIOD'], errors='coerce') == year)]
    out = {}
    for sec in sectors:
        for x in w[w['SECTOR'] == sec].itertuples():
            v = pd.to_numeric(x.OBS_VALUE, errors='coerce')
            if x.COUNTRY not in out and np.isfinite(v):
                out[x.COUNTRY] = (float(v), sec)
    return out


def donor_regions_g114(weights, shares, gdp, cover_min=G114_COVER_MIN, statutory_zero=None):
    """The product-tax money source of every S05 donor region.

    weights: S05 donor_weights (region, code, s02_gdp, donor); shares: g114_shares; gdp: {region: S02 GDP, USD m}.
    Returns a DataFrame region, mode ('g114' or 'rates'), g114_pct_gdp, g114_musd, cover, sectors, members_missing,
    donors, note. statutory_zero {region: basis}: a region with no G114 value whose law levied no VAT, general sales tax
    or excise in the base year holds a general product-tax money of 0 (tax statistics, GTAP 12 ch.8 / ch.15), not the
    donor's rates."""
    rows = []
    statutory_zero = statutory_zero or {}
    for reg, g in weights.groupby('region', sort=True):
        g = g[pd.to_numeric(g['s02_gdp'], errors='coerce').fillna(0.0) > 0]
        tot = float(g['s02_gdp'].sum())
        have = g[g['code'].isin(shares)]
        cov = float(have['s02_gdp'].sum()) / tot if tot > 0 else 0.0
        miss = sorted(set(g['code']) - set(have['code']))
        donors = ' '.join(sorted({str(d) for d in g['donor'] if isinstance(d, str)}))
        secs = ' '.join(sorted({shares[c][1] for c in have['code']}))
        if reg in statutory_zero and not len(have) and np.isfinite(gdp.get(reg, np.nan)):
            rows.append(dict(region=reg, mode='g114', g114_pct_gdp=0.0, g114_musd=0.0, cover=1.0, sectors='statutory',
                             members_missing=' '.join(miss), donors=donors,
                             note='statutory: ' + statutory_zero[reg]))
        elif len(have) and cov >= cover_min and np.isfinite(gdp.get(reg, np.nan)):
            pct = float(sum(shares[c][0] * v for c, v in zip(have['code'], have['s02_gdp'])) / have['s02_gdp'].sum())
            rows.append(dict(region=reg, mode='g114', g114_pct_gdp=pct, g114_musd=pct / 100.0 * float(gdp[reg]), cover=cov,
                             sectors=secs, members_missing=' '.join(miss), donors=donors,
                             note='IMF GFS G114 (WoRLD) less the energy excise'))
        else:
            why = (f'no {G114_YEAR} G114 value' if not len(have) else f'G114 members cover {cov:.1%} of GDP (< {cover_min:.0%})')
            rows.append(dict(region=reg, mode='rates', g114_pct_gdp=np.nan, g114_musd=np.nan, cover=cov, sectors=secs,
                             members_missing=' '.join(miss), donors=donors, note=why + ': rates held, no money hold'))
    return pd.DataFrame(rows, columns=['region', 'mode', 'g114_pct_gdp', 'g114_musd', 'cover', 'sectors', 'members_missing', 'donors', 'note'])


def scale_general_to_total(cell_rate, general, b12, tls, total_musd, cap_excise=False):
    """Scale the general part of every cell rate of a region by one factor so that its money on the io_s12 flows b12
    equals max(total_musd - E, 0), E the positive energy-excise part on those flows (cell_rate - general > 0).
    tls moves with the money it loses or gains by column. cap_excise (beta v4 G15, s13 choice excise_cap_g114): where E
    exceeds total_musd, the positive energy-excise rates are first scaled by one factor so that E equals total_musd (the
    tax statistics' total bounds the excise a proxy fill gave; GTAP 12 ch.8 Appendix A scales expected to actual revenue).
    Returns (cell_rate, general, tls, info) or, where the general money on the io_s12 flows is not positive (nothing to
    scale) and no excise was capped, None."""
    emat = cell_rate - general
    pos = np.clip(emat, 0.0, None)
    E = float((pos * b12).sum())
    E0, k = E, 1.0
    if cap_excise and E > max(float(total_musd), 0.0):
        k = max(float(total_musd), 0.0) / E
        tls = tls - ((1.0 - k) * pos * b12).sum(axis=0)
        emat = emat - (1.0 - k) * pos
        E = E * k
    col0 = (general * b12).sum(axis=0)
    G0 = float(col0.sum())
    T = max(float(total_musd) - E, 0.0)
    info = dict(energy_excise_musd=E, energy_excise_before_cap_musd=E0, excise_cap_factor=k, donor_general_musd=G0, general_target_musd=T)
    if not G0 > 0:
        if k < 1.0:
            return emat + general, general, tls, dict(info, factor=np.nan)
        return None
    f = T / G0
    general = general * f
    tls = tls + (f - 1.0) * col0
    return emat + general, general, tls, dict(info, factor=f)


def zero_unsourced_general(cell_rate, general, b12, tls):
    """A representative-table region's negative general product-tax rates (cell rate less the energy-tax rate) are the
    donor's subsidies (e.g. a donor's farm input subsidy on crp), with no source for the region: GTAP books a
    subsidy only from a cited source (ch.11A, 11C: OECD PSE, IEA, WTO), so they are set to 0. The energy-tax rates
    (ch.12, IEA subsidies included) stay. tls moves with the money removed by column. Returns (cell_rate, general,
    tls, info with the cells and money removed)."""
    neg = general < 0
    money = (np.where(neg, general, 0.0) * b12).sum(axis=0)
    cell_rate = cell_rate - np.where(neg, general, 0.0)
    general = np.where(neg, 0.0, general)
    return cell_rate, general, tls - money, dict(unsourced_cells=int(neg.sum()), unsourced_musd=float(-money.sum()))


# ------------------------------------------------------------------ Fable QA C-09: VAT of the GCC VAT states on final demand
VAT_COLUMNS = ('region', 'statutory_rate_pct', 'in_force', 'excise_part', 'source', 'url', 'decided_by', 'decided_at', 'basis')
# excise_part: 'g1142' (the GCC states: G1142 is the selective excise on fbt, they levy no fuel excise) or 'g1142_less_energy'
# (beta v4 G14: G1142 includes the fuel excise S13 books on the energy rows, so only the rest goes on households' fbt)
EXCISE_PARTS = ('g1142', 'g1142_less_energy')
EXCISE_LESS_ENERGY = 'g1142_less_energy'
FD_RATE_MAX = 1.0                   # beta v4 G14: a representative-table region's non-energy household or government rate above 100%
VAT_FD = ('p', 'g')                 # VAT falls on final consumption; firms deduct their input VAT (ch.8 valuation layers)
VAT_EXCISE_ROW = 'fbt'              # the GCC selective excise (tobacco, sugary and energy drinks) on households' fbt
NON_ENERGY_EXCLUDED = ('coa', 'oil', 'gas', 'pet', 'ely')


def read_vat_regions(path):
    """config/s13/vat_final_demand_2022.csv: the VAT states whose VAT the fit books on final demand. Stop on a missing
    file or column, a blank attribution or a duplicate region. Returns {region: row}."""
    import csv
    import os
    if not os.path.exists(path):
        raise SystemExit(f'{path} is missing')
    with open(path, newline='') as fh:
        rd = csv.DictReader(fh)
        if tuple(rd.fieldnames or ()) != VAT_COLUMNS:
            raise SystemExit(f'{path}: columns {rd.fieldnames} are not {VAT_COLUMNS}')
        rows = list(rd)
    out = {}
    for r in rows:
        if not all(r[c].strip() for c in ('source', 'decided_by', 'decided_at')) or r['region'] in out:
            raise SystemExit(f'{path}: row {r["region"]} has no source or attribution, or is listed twice')
        float(r['statutory_rate_pct'])
        if r['excise_part'] not in EXCISE_PARTS:
            raise SystemExit(f'{path}: row {r["region"]} excise_part {r["excise_part"]!r} is not one of {EXCISE_PARTS}')
        out[r['region']] = r
    return out


def gfs_parts(world, year=G114_YEAR, codes=('G114', 'G1142'), sectors=G114_SECTORS):
    """{(country, code): % of GDP} for the year from the WoRLD frame; for each country the first sector of `sectors`
    that reports G114 is used for every code (so the parts come from one account)."""
    w = world[world['GFS_STO'].isin(codes) & (pd.to_numeric(world['TIME_PERIOD'], errors='coerce') == year)]
    out = {}
    for c, g in w.groupby('COUNTRY'):
        for sec in sectors:
            h = g[g['SECTOR'] == sec]
            v = {x.GFS_STO: pd.to_numeric(x.OBS_VALUE, errors='coerce') for x in h.itertuples()}
            if np.isfinite(v.get('G114', np.nan)):
                for k in codes:
                    if np.isfinite(v.get(k, np.nan)):
                        out[(c, k)] = float(v[k])
                break
    return out


VAT_EXEMPT_COLUMNS = ('region', 'rows', 'source', 'decided_by', 'decided_at', 'basis')
VAT_EXEMPT_ROWS = ('rle', 'fin', 'edu', 'hea', 'gov', 'hhe')   # beta v5 V: the rows a listed region's VAT law exempts may only be these


def read_vat_exempt(path, regions):
    """Beta v5 V: config/s13/vat_exempt_rows.csv, per VAT region the rows (space-separated) its VAT law exempts. Stop on a
    missing file or column, a blank source or attribution, a duplicate region, a region not in vat_final_demand_2022.csv
    (regions) or a row outside VAT_EXEMPT_ROWS. Returns {region: [rows]}."""
    import csv
    import os
    if not os.path.exists(path):
        raise SystemExit(f'{path} is missing')
    with open(path, newline='') as fh:
        rd = csv.DictReader(fh)
        if tuple(rd.fieldnames or ()) != VAT_EXEMPT_COLUMNS:
            raise SystemExit(f'{path}: columns {rd.fieldnames} are not {VAT_EXEMPT_COLUMNS}')
        rows = list(rd)
    out = {}
    for r in rows:
        if not all(r[c].strip() for c in ('source', 'decided_by', 'decided_at')) or r['region'] in out:
            raise SystemExit(f'{path}: row {r["region"]} has no source or attribution, or is listed twice')
        if r['region'] not in regions:
            raise SystemExit(f'{path}: {r["region"]} is not a vat_final_demand region')
        rr = r['rows'].split()
        if not rr or any(x not in VAT_EXEMPT_ROWS for x in rr):
            raise SystemExit(f'{path}: {r["region"]} rows {r["rows"]!r} must be among {VAT_EXEMPT_ROWS}')
        out[r['region']] = rr
    return out


def vat_final_demand(cell_rate, general, b12, tls, sectors, cols_all, vat_musd, excise_musd, zero_firms=False, exempt=(), rate_max=None):
    """Fable QA C-09: the VAT of a GCC VAT state on final demand (GTAP 12 ch.8: the product-tax wedge of each agent from
    the valuation layers; ch.15 and ch.8 Appendix A: the money from the government accounts). The household and
    government columns' general part becomes one VAT rate v on all their purchases (the GCC VAT covers fuel and
    electricity too), sum v x basic = vat_musd (IMF GFS G114 less the excises G1142, times S02 GDP); the excises
    (G1142 x GDP) go on households' fbt row on top. The energy rows keep their energy-tax rates under the VAT. zero_firms (a representative-table region): the firms' general part
    and investment general part (the donor's VAT pattern) is set to 0, since firms deduct input VAT; an ICIO region keeps
    its firms' and investment general part.
    exempt (beta v5 V, s13 choice vat_exemptions): rows the region's VAT law exempts (imputed and residential rent, finance,
    health, education, government's own output, household employers; EU Directive 2006/112 Arts 132 and 135 for the
    candidate states): their household and government rate is 0, and v is set on the other rows so the VAT money stays.
    rate_max (with exempt; the statutory rate): v is at most rate_max, and the VAT money v cannot carry goes on the exempt
    activities' own purchases of the taxable rows at one rate (the input VAT an exempt activity cannot deduct; beta v5 V,
    not in the GTAP 12 text). tls moves with the money by column. Returns (cell_rate, general, tls, info)."""
    n = len(sectors)
    emat = cell_rate - general
    ne = np.array([c not in NON_ENERGY_EXCLUDED for c in sectors])
    fd = [cols_all.index(c) for c in VAT_FD]
    before = (general * b12).sum(axis=0)
    g = general.copy()
    if zero_firms:
        g[:, :n] = 0.0
        g[:, cols_all.index('i')] = 0.0          # business investment deducts its VAT too
    ex = np.array([c in exempt for c in sectors])
    base = float(sum(b12[~ex, j].sum() for j in fd))
    v = float(vat_musd) / base if base > 0 else 0.0
    for j in fd:
        g[:, j] = np.where(ex, 0.0, v)
    u, over = 0.0, 0.0
    xa = [i for i in range(n) if ex[i]]          # the exempt activities' own columns
    base_x = float(b12[~ex][:, xa].sum()) if xa else 0.0
    if ex.any() and rate_max is not None and np.isfinite(rate_max) and v > rate_max and base_x > 0:
        over = float(vat_musd) - rate_max * base
        v, u = float(rate_max), over / base_x
        for j in fd:
            g[:, j] = np.where(ex, 0.0, v)
        for j in xa:
            g[~ex, j] += u
    jp = cols_all.index('p')
    ix = sectors.index(VAT_EXCISE_ROW)
    if excise_musd > 0 and b12[ix, jp] > 0:
        g[ix, jp] += float(excise_musd) / float(b12[ix, jp])
    after = (g * b12).sum(axis=0)
    info = dict(vat_rate=v, vat_musd=float(vat_musd), excise_musd=float(excise_musd), base_musd=base,
                general_before_musd=float(before.sum()), general_after_musd=float(after.sum()),
                household_general_rate=float((g[ne, jp] * b12[ne, jp]).sum() / b12[ne, jp].sum()) if b12[ne, jp].sum() > 0 else np.nan,
                firms_general_musd=float(after[:n].sum()), exempt_rows=' '.join(c for c in sectors if c in exempt),
                exempt_base_musd=float(sum(b12[ex, j].sum() for j in fd)), exempt_input_vat_musd=over, exempt_input_rate=u)
    return emat + g, g, tls + (after - before), info


def final_demand_rate_max(general, sectors, cols_all):
    """Beta v4 G14: the largest general (non-energy-tax) rate on households' and government's non-energy rows, households'
    fbt left out (it carries the selective excise). Returns dict(p_rate_max, g_rate_max)."""
    keep = np.array([c not in NON_ENERGY_EXCLUDED and c != VAT_EXCISE_ROW for c in sectors])
    keep_g = np.array([c not in NON_ENERGY_EXCLUDED for c in sectors])
    jp, jg = cols_all.index('p'), cols_all.index('g')
    return dict(p_rate_max=float(general[keep, jp].max()) if keep.any() else np.nan,
                g_rate_max=float(general[keep_g, jg].max()) if keep_g.any() else np.nan)
