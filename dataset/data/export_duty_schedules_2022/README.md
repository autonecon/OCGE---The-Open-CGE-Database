# export_duty_schedules_2022: 2022 export-duty regimes for RUS, IND and CHN (for S10, fix-round item A2)

Compiled 2026-10-24 (UTC+7) by worker wB for QA finding HIGH-2: OECD GRS T_5124 has no 2022 export-tax total for
Russia, India or China, so S10 books their export taxes from 2022 rates (GTAP: an ad valorem rate on the FOB value by
commodity, ch.2 Table 2.3 and ch.17A eq. 17.30).

| File | What |
|---|---|
| `export_duty_regimes_2022.csv` | One row per duty regime: exporter, HS prefix, group (grade, national line or product the HS6 line cannot separate), kind, value, dates in force, legal basis or source, URL, retrieval date. |
| `rus_crude_export_duty_2022.csv` | Russian crude-oil export duty by month 2022, USD per tonne (set monthly by the Ministry of Finance under Government Resolution No. 276 of 29 March 2013). Mean 49.91 USD/t. |
| `ind_saed_fuel_exports_2022.csv` | India special additional excise duty on exports of diesel, ATF and petrol, INR per litre by effective date, from 1 July 2022 (the "windfall" levy, revised fortnightly). Column `confirmed` marks values seen in two sources. |
| `derive_export_duty_aves_2022.py` | Derives the annual ad valorem rates (rules in its docstring) from these files, the OECD inventory (`../oecd_export_restrictions/`, CHN), WDI PA.NUS.FCRF 2022 (`../wdi/wdi_2017_2022_extract.csv`) and BACI HS22 2022 (`../baci/`, unit values). Run: `python3 -I derive_export_duty_aves_2022.py ../baci/BACI_HS22_Y2022_V202601.csv`. |
| `derived_aves_2022.csv` | Its output. `dataset/build/config/s10/export_tax_rates_2022.csv` carries the same rates (a test checks they agree). |

**Rules.** Part-year duties count for their days in force over 365. A specific duty is divided by the exporter's BACI
2022 unit value (FOB, USD per tonne) of the same HS prefix; a floating "70 percent of (indicative price - base)" duty
takes the BACI unit value as the indicative price. Groups within one HS prefix (e.g. iron ore above and below 58% Fe,
rice parboiled, basmati and other, Russian product classes inside BACI's single 271000 line) take their simple mean,
as a simple average of national tariff lines.

**Retrieval.** The build box reaches WTO, OECD, IMF and World Bank hosts only; Russian and Indian government hosts
(minfin.gov.ru, economy.gov.ru, cbic.gov.in, indiabudget.gov.in, pib.gov.in) and most news hosts could not be opened.
Values marked with those URLs were read from search-engine extracts of the pages on 2026-10-24 and are cross-checked
where a second source exists (columns `second_source`, `confirmed`). No page copy is stored for them.

**Known limits (for David).**
- Russian duties do not apply to EAEU partners (Armenia, Belarus, Kazakhstan, Kyrgyzstan); the build applies one
  rate to every destination. BACI 2022 shows almost no Russian crude or gas to the EAEU, so the effect is small.
- Russian grain duties: two cited weekly points (17 August and 28 December 2022), at the annual RUB/USD rate; the
  higher first-half USD-denominated rates are not in the sources reached, so wheat (16.9%) is likely low.
- Russian product duty: BACI aggregates HS 2710 into 271000; the rate is the simple mean of the four Resolution 276
  product coefficients (30, 30, 55, 100 percent of the crude duty).
- India: the steel duty covered named eight-digit lines of the headings booked; the iron-ore 30% on grades above
  58% Fe outside 22 May-18 November is booked on the "above 58" group only. The fuel levy is an excise duty on
  exports, booked as an export tax (it is collected only on exported fuel).
- India fuel levy 17 September 2022 values are from one source only.
- Sunflower meal and LPG duties and Russian wood duties (coniferous logs were banned from export in 2022) are not
  booked.
