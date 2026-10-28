# NDRC Notice 303 (2022): regulated range for medium/long-term contract thermal coal prices, for S11 domestic basic prices

- **Folder:** `data/ndrc_coal_contract_2022/`
- **Source:** National Development and Reform Commission, 国家发展改革委关于进一步完善煤炭市场价格形成机制的通知 (发改价格〔2022〕303号), issued 2022-02-24, published 2022-02-25 by the Price Department. Notice https://www.ndrc.gov.cn/xxgk/zcfb/tz/202202/t20220225_1317003.html; annex 重点地区煤炭出矿环节中长期交易价格合理区间 https://www.ndrc.gov.cn/xxgk/zcfb/tz/202202/P020220225550328647794.pdf.
- **Fetch:** `fetch_ndrc_coal_contract_2022.sh` (keyless). Fetched 2026-10-23 (UTC). sha256 in `fetch.log` and `data/MANIFEST.csv`.
- **Licence:** official government document; PRC Copyright Law art. 5 excludes laws, regulations and official documents of state organs from copyright protection. Cite NDRC.
- **Year:** 2022. In force from 2022-05-01 (covers May-December 2022); not a 2017 source.
- **What it is:** a policy *range* for contract prices, not an observed average. Prices are per tonne, **VAT-inclusive** (含税), for thermal coal (动力煤). Imported coal is excluded.
- **Port benchmark (notice text, section 2):** Qinhuangdao port FOB-to-ship (秦皇岛港下水煤) 5500 kcal/kg NAR, medium/long-term contract: **570-770 RMB/t** incl. VAT.
- **Mine-gate ranges (annex, scanned; transcribed here):**

  | Region | Calorific basis | Range, RMB/t incl. VAT |
  |---|---|---|
  | Shanxi 山西 | 5500 kcal/kg | 370-570 |
  | Shaanxi 陕西 | 5500 kcal/kg | 320-520 |
  | Inner Mongolia west 蒙西 | 5500 kcal/kg | 260-460 |
  | Inner Mongolia east 蒙东 | 3500 kcal/kg | 200-300 |

  Annex notes: (1) all prices include tax; (2) other calorific values scale by the calorific ratio; (3) other regions set local mine-gate ranges so that local and imported-from-other-province coal cost about the same delivered to power plants.
- **Conversions (for the build, not in the source):** 5500 kcal/kg = 23.03 GJ/t; 3500 kcal/kg = 14.65 GJ/t. VAT on coal in 2022 was 13%, so ex-VAT = incl. / 1.13. Port midpoint 670 RMB/t -> 592.9 ex-VAT -> 25.7 RMB/GJ. Shanxi mine-gate midpoint 470 -> 415.9 ex-VAT -> 18.1 RMB/GJ.
- **Gap:** the observed 2022 average contract price (e.g. CCTD's 5500 kcal Qinhuangdao long-term contract index) and NBS mine-gate prices were not downloaded; CCTD series appear to need a subscription.
