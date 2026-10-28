# China Statistical Yearbook 2023: coal mining and washing revenue and raw coal output (2022), for S11 domestic basic prices

- **Folder:** `data/nbs_yearbook_2023_coal/`
- **Source:** National Bureau of Statistics of China, China Statistical Yearbook 2023 (中国统计年鉴2023), https://www.stats.gov.cn/sj/ndsj/2023/indexch.htm. Table 13-2 https://www.stats.gov.cn/sj/ndsj/2023/html/C13-02.jpg and table 13-12 https://www.stats.gov.cn/sj/ndsj/2023/html/C13-12.jpg. The yearbook web edition has these tables only as images (no xls); values below are transcribed by hand.
- **Fetch:** `fetch_nbs_yearbook_2023_coal.sh` (keyless). Fetched 2026-10-23 (UTC). sha256 in `fetch.log` and `data/MANIFEST.csv`.
- **Licence:** NBS public statistical publication; small extracts with citation; not redistributed publicly (same terms as `data/nbs_census_chn/`).
- **Year:** 2022. 2017 would need the 2018 yearbook (not fetched).

## Transcribed values

Table 13-2, 按行业分规模以上工业企业主要指标 (2022), unit 100 million yuan (亿元), row 煤炭开采和洗选业 (coal mining and washing):

| Indicator | Value |
|---|---|
| Enterprises (个) | 4,814 |
| Operating revenue 营业收入 | **40,729.4** |
| Operating cost 营业成本 | 24,298.8 |
| Total profit 利润总额 | 10,415.6 |
| Average employment (10,000 persons) | 266.5 |

Table 13-12, 工业产品产量: raw coal 原煤 2022 = **45.59 亿吨** (4,559 Mt); 2021 = 41.26.

## Derived unit value (for the build, not in the source)

- Revenue / raw coal output = 40,729.4e8 RMB / 45.59e8 t = **893 RMB/t**.
- At the NBS raw-coal conversion factor 0.7143 tce/t (20.93 GJ/t), that is about **42.7 RMB/GJ**.
- Basis: operating revenue is ex-VAT and is at the producer (mine-gate / plant-gate, including washing). It is an observed average, unlike the NDRC Notice 303 policy range in `data/ndrc_coal_contract_2022/`.
- Caveats: revenue covers enterprises above designated size only (output covers all, but above-scale mines produce nearly all coal), includes washed and coking coal at higher value per tonne than raw thermal coal, and includes non-coal revenue of coal firms. 2022 was a high-price year (profit 26% of revenue). Treat the unit value as an upper bound for thermal coal at the mine.
