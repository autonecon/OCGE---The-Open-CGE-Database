# 2022 electricity prices of the class-fill regions (beta v4 G10)

- **Folder:** `data/ely_prices_2022/`
- **Source:** official publications gathered by David's agent on 2026-10-26 (URLs in `data/MANIFEST.csv`). `.txt` files are pdftotext extracts or transcribed excerpts of web pages that could not be saved whole. The Oman APSR report PDF (35 MB) is not kept; its extract is.
- **Licence:** per file in `data/MANIFEST.csv`. Files marked not redistributable are build inputs only; users are pointed to the source.
- **Year:** 2022.
- **Use:** S11 choice `ely_class_price`, through the transcribed rows in `build/config/s11/ely_industrial_prices_2022.csv`; not read by the build.
  - **Used:** OMN, APSR Annual Report 2022, MIS customer revenue per kWh 20.4 baisa (= 20.4 OMR/MWh, about 53 USD/MWh), revenue per MWh of all customers. BRA, MME Informativo Gestão do Setor Elétrico 2022, Tabela 7, October 2022 average billed industrial tariff 577.14 BRL/MWh (about 112 USD/MWh; txt line 1300).
  - **Recorded, not used:** AUS, AEMO NEM demand-weighted spot price 2022, 193.29 AUD/MWh (wholesale; derived by `AU_AEMO_vwa_2022.py` from the 60 AEMO monthly regional files, which are not kept). COL, XM 2022 weighted contract price 269.51 COP/kWh (wholesale). CAN, Hydro-Québec large-power bill comparison at 1 April 2022 (one tariff snapshot).
  - **Context only:** CMR, ENEO annual report 2022 (turnover, no MWh sold, so no price).

## Files

| File | Bytes | SHA-256 |
|---|---|---|
| `ely_prices_2022/BR_MME_informativo_gestao_setor_eletrico_2022.pdf` | 1,636,349 | `44e62aae18dccd9c0e8c995d4132543fb16f86698415000a3db9fe412b67d2bb` |
| `ely_prices_2022/BR_MME_informativo_gestao_setor_eletrico_2022.txt` | 117,885 | `3730bbb4f118417b1d83db39e021b77277055c4fa5cd92c459cec85507cbf144` |
| `ely_prices_2022/OM_APSR_annual_report_2022_ar.txt` | 595,313 | `8cd33694d328cbcf8e51b0c5c5a2c52a1f71492240649a0539827b50e94f8781` |
| `ely_prices_2022/CA_HydroQuebec_comparison_prices_2022_excerpt.txt` | 1,666 | `1f1f0a3224343399c8891cf612ad215001503d57bdfacad429db996cd86da23b` |
| `ely_prices_2022/CO_XM_reporte_integral_2023_excerpt.txt` | 1,106 | `72afe344ee6a6ace022e7f6868cad3e728061f91fd7b1d445efd1252908a9662` |
| `ely_prices_2022/AU_AEMO_vwa_2022.csv` | 235 | `48d7db58b1fa6dec9fbb02dbb6c644e93b5e7d98945b903626d9395d998dd657` |
| `ely_prices_2022/AU_AEMO_vwa_2022.py` | 1,056 | `4a8fe3ee5842767ac2c621d5583d9d32c880628ba52904a2b2cef2057e0c32df` |
| `ely_prices_2022/CM_ENEO_annual_report_2022_ENG.txt` | 65,949 | `718b497d42fa00b728e99a6285ec139885c7a41fdc5a2d4b9de6720c694da547` |

