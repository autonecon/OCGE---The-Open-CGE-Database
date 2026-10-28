# UN Comtrade 2022 energy exports and re-exports to the world, for the S11 re-export removal

- **Folder:** `data/un_comtrade_rx_2022/`
- **Source:** UN Comtrade public API, preview endpoint (keyless, at most 500 rows a call): `https://comtradeapi.un.org/public/v1/preview/C/A/HS?period=2022&partnerCode=0&customsCode=C00&motCode=0&partner2Code=0&cmdCode=<line>&flowCode=<X|RX>`.
- **Files:** `comtrade_<flow>_<line>_2022.json` for flows X (exports, which include re-exports) and RX (re-exports), lines 2701 (coal), 2709 (crude), 271111 (LNG), 271121 (pipeline gas), 2710 (petroleum products), 2716 (electricity), every reporter, partner World; `comtrade_RX_TOTAL_2022.json`, the reporters with any 2022 re-exports at all (57 reporters).
- **Fetch:** `fetch_comtrade_rx_2022.sh`. Fetched 2026-10-25 (UTC). sha256 in `fetch.log` and `data/MANIFEST.csv`.
- **Licence:** UN Comtrade terms of use (free reuse of the public API data with attribution to UN Comtrade).
- **Year:** 2022.
- **Use:** S11 (choice `reexport_removal`, Fable QA D-04, David 2026-10-25 "do all fixes"): where a region's customs report re-exports, its observed re-export share of exports (RX / X, net weight where reported, else value) replaces the same-propensity estimate of GTAP 12 ch.12 §12.2.5. Reporter 842 is the United States (Comtrade code).
- **Key 2022 values:** USA crude X 117.0 bn, RX 3.43 bn (3.1 percent by weight); USA products X 135.4 bn, RX 1.51 bn; ARE products X 47.6 bn, RX 8.70 bn (21.1 percent by weight). Belgium, the Netherlands and Singapore report no re-exports.
