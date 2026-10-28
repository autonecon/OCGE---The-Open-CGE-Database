# UN Comtrade 2022 imports by partner and HS2 as China and Mexico report them, for the S07 importer floor

- **Folder:** `data/un_comtrade_import_floor_2022/`
- **Source:** UN Comtrade public API, preview endpoint (keyless, at most 500 rows a call): `https://comtradeapi.un.org/public/v1/preview/C/A/HS?period=2022&customsCode=C00&motCode=0&partner2Code=0&flowCode=M&reporterCode=<156|484>&cmdCode=<HS2>` (every partner), and `cmdCode=TOTAL&partnerCode=0` for the all-goods total.
- **Files:** `M_<reporter>/M_<reporter>_<HS2>.json` for HS2 01-99 (77 is not used in the HS) and `M_<reporter>/M_<reporter>_TOTAL.json`; reporters 156 (China) and 484 (Mexico). Values are CIF, USD. `SHA256SUMS`; `fetch.log`.
- **Fetch:** `fetch_import_floor_2022.sh`. Fetched 2026-10-27 (UTC).
- **Licence:** UN Comtrade terms of use (free reuse of the public API data with attribution to UN Comtrade).
- **Year:** 2022.
- **Use:** S07 (choice `importer_floor`, beta v5 fix B, David approved the v5 package 2026-10-27 08:39 UTC): a listed importer's BACI imports outside HS 27, 71 and 99 are raised to its own customs total of those lines (CIF over its beta v4 VCIF/VFOB), by partner x HS2; config/s07/importer_floors.csv. Re-imports (partner = the reporter) are left out.
- **Key 2022 values:** China all goods 2,715,998 USD m CIF (partner World).
