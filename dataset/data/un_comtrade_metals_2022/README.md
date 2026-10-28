# UN Comtrade 2022 gold and refined-copper exports by reporter, for the S07 metal re-export ceiling

- **Folder:** `data/un_comtrade_metals_2022/`
- **Source:** UN Comtrade public API, preview endpoint (keyless, at most 500 rows a call): `https://comtradeapi.un.org/public/v1/preview/C/A/HS?period=2022&partnerCode=0&customsCode=C00&motCode=0&partner2Code=0&cmdCode=<7108|7403>&flowCode=X`.
- **Files:** `comtrade_X_7108_2022.json` (gold, non-monetary, unwrought, semi-manufactured or powder; 128 reporters) and `comtrade_X_7403_2022.json` (refined copper and copper alloys, unwrought; 119 reporters), exports to World as each exporter's own customs reports them; `SHA256SUMS`; `fetch.log`.
- **Fetch:** `fetch_metals_2022.sh`. Fetched 2026-10-27 (UTC).
- **Licence:** UN Comtrade terms of use (free reuse of the public API data with attribution to UN Comtrade).
- **Year:** 2022.
- **Use:** S07 (choice `gold_reexport` = `metal_reexport_...`, beta v5 fix G, David approved the v5 package 2026-10-27 08:39 UTC): a listed region's BACI exports on the line are capped at max(own customs exports, mine output + recorded imports); config/s07/metal_reexport_2022.csv.
- **Key 2022 values (USD m, HS 7108):** GHA 6,541; MLI 3,051; BFA 3,365; ZWE 1,992; MRT 1,169; MNG 1,104; NAM 439; NER 71; ZMB 55; COD 2.7. Guinea, Togo and Uganda do not report. HS 7403: COD 12,528; ZMB 1,886; COG 76.9.
