# Eurostat natural gas imports and exports by partner, 2022, for the S11 gas route seed

- **Folder:** `data/eurostat_gas_trade/`
- **Source:** Eurostat dissemination API, SDMX 3.0, csvdata. `nrg_ti_gas` (imports of natural gas by partner country, https://ec.europa.eu/eurostat/databrowser/view/nrg_ti_gas/default/table) and `nrg_te_gas` (exports by partner country), annual, natural gas (`siec` G3000), million cubic metres (`unit` MIO_M3), 2022, every reporter.
- **Fetch:** `fetch_eurostat_gas_trade.sh` (keyless). Fetched 2026-10-25 (UTC); Eurostat update of nrg_ti_gas 2026-10-09. sha256 in `fetch.log` and `data/MANIFEST.csv`.
- **Licence:** Eurostat reuse policy: free reuse with acknowledgement (CC BY 4.0 equivalent, Commission Decision 2011/833/EU).
- **Year:** 2022.
- **Use:** S11 (choice `gas_import_origin`, Fable QA D-02, David 2026-10-25 "do all fixes"): the gas origin of an importer that declares imports without origin (`config/s11/gas_import_origin.csv`; Germany). Partner `NSP` is "not specified".
- **Key 2022 values (million m3):** DE imports 87,695: NSP 34,063, NO 27,690, RU 25,941. Partners' reports of exports to DE: NO 54,812, NL 9,978, BE 6,528.
