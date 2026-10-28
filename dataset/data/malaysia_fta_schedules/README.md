# Malaysia preferential tariff schedules and customs duty orders (official text)

Public legal and treaty text, fetched 2026-10-23 from MITI's FTA portal (https://fta.miti.gov.my, one page per agreement under `/index.php/pages/view/<fta>`). For the S10 rebuild of Malaysia's 2022 preferences, because WITS stops at the 2014 preference file. `extracted/mys_pref_lines_2022.csv` holds the national lines with their 2022 rate, written by `build/tools/s10_extract_tariff_texts.py`; which agreements are read and their 2022 members are in `build/config/s10/mys_national_agreements.csv`.

Each file is Malaysia's own import schedule (or the gazetted Customs Duties order that carries it) under one agreement. Exact URLs and SHA-256 are in `../MANIFEST.csv`.

| File | Agreement | What |
|---|---|---|
| `atiga_malaysia_annex2_ahtn2017.pdf` | ATIGA | Annex 2 schedule, AHTN 2017 |
| `acfta_malaysia_trs_ahtn2017.pdf` | ACFTA | Tariff reduction schedule, AHTN 2017 |
| `ahkfta_malaysia_trs_hs2017.xlsx`, `ahkfta_malaysia_appendixA_trq.pdf` | AHKFTA | Schedule (HS2017) and TRQ appendix |
| `aifta_pua492_2009_part{1,2,3}.pdf` | AIFTA | P.U.(A) 492/2009 Customs Duties order, three parts |
| `ajcep_malaysia_schedule.pdf`, `ajcep_malaysia_schedule_notes.pdf` | AJCEP | Schedule of Malaysia and its notes |
| `akfta_pua381_2013.pdf`, `akfta_pua286_2015_3rd_protocol.pdf` | AKFTA | P.U.(A) 381/2013 and P.U.(A) 286/2015 (third protocol) |
| `aanzfta_pua220_2015_1st_protocol.pdf` | AANZFTA | P.U.(A) 220/2015 amendment order (first protocol) |
| `mafta_perintah_duti_kastam_2012.pdf` | MAFTA (Australia) | P.U.(A) 487/2012 |
| `mcfta_perintah_duti_kastam.pdf` | MCFTA (Chile) | P.U.(A) 51/2012 |
| `miceca_malaysia_jadual_tarif.pdf` | MICECA (India) | Malaysia schedule |
| `mjepa_malaysia_schedule.pdf`, `mjepa_malaysia_schedule_notes.pdf`, `mjepa_annex1_general_notes.pdf` | MJEPA (Japan) | Schedule, notes, general notes |
| `mnzfta_malaysia_schedule.pdf` | MNZFTA (New Zealand) | Malaysia schedule |
| `mpcepa_malaysia_schedule.pdf` | MPCEPA (Pakistan) | Malaysia schedule |
| `mtfta_malaysia_schedule_ahtn10.pdf` | MTFTA (Türkiye) | Malaysia schedule, AHTN 10-digit |
| `rcep_malaysia_schedule.pdf`, `rcep_malaysia_schedule_trq.pdf`, `rcep_malaysia_headnotes.pdf`, `rcep_annex1_general_headnotes.pdf` | RCEP | Malaysia schedule (HS2012), TRQ table, headnotes, general notes |
| `cptpp_malaysia_tariff_elimination_schedule.pdf`, `cptpp_malaysia_general_notes.pdf`, `cptpp_malaysia_appendixA_trq.pdf` | TPP/CPTPP | Annex 2-D (TPPA text of 2016-05-16, HS2012), general notes, TRQs |

## 2022 HS2022 orders (added 2026-10-23, second pass)

Fetched from the Royal Malaysian Customs Department (www.customs.gov.my, "Warta Kerajaan" page, folder `images/06-prosedur/perintah-kastam/`), the Laws of Malaysia portal (lom.agc.gov.my) and www.miti.gov.my. Exact URLs and SHA-256 are in `../MANIFEST.csv`.

| File | What | Nomenclature |
|---|---|---|
| `pua199_2022_atiga_ahtn2022.pdf` | P.U.(A) 199/2022, ATIGA Order 2022, in force 1 June 2022 (1,713 pages). Replaces the earlier ATIGA order. | AHTN 2022 |
| `pua118_2022_atiga_amendment.pdf`, `pua255_2022_atiga_amendment.pdf` | ATIGA amendment orders 2022: 118 (18 April 2022, rules-of-origin annexes) and 255 (in force 5 August 2022, description fixes to 199). | |
| `pua92_2023_atiga_amendment.pdf`, `pua138_2023_atiga_amendment_no3.pdf` | ATIGA amendments to 199 in force 1 April 2023 and 1 May 2023 (after 2022, kept for the chain). | |
| `pua64_2022_rcep.pdf` | P.U.(A) 64/2022, RCEP Order 2022, in force 18 March 2022 (957 pages). | AHTN 2017 (keyed to the 2017 order; no HS2022-only codes such as 8549) |
| `pua68_2023_rcep_amendment.pdf` | RCEP (Amendment) Order 2023, gazetted 14 March 2023: HS 2022 product-specific rules. | HS 2022 |
| `pua406_2022_cptpp.pdf` | P.U.(A) 406/2022, CPTPP Order 2022, in force 29 November 2022 (1,109 pages). | AHTN 2022 |
| `pua139_2023_cptpp_amendment.pdf` | CPTPP amendment, in force 1 May 2023. | |
| `pua52_2023_ajcep_amendment.pdf` | AJCEP (Amendment) Order 2023 to the AJCEP Order 2020, in force 1 March 2023 (replaces Appendix B). | |
| `pua114_2022_customs_duties_order.pdf` | P.U.(A) 114/2022, Customs Duties Order 2022 (MFN), in force 1 June 2022. | AHTN 2022 |
| `pua216_2022_customs_duties_amendment.pdf` | Amendment to 114/2022, in force 1 July 2022. | |
| `miti_notice_*.pdf` | MITI notices on HS 2022 in preferential certificates of origin (January, 2 June and 7 June 2022; ATIGA PSR in AHTN 2022 from 10 April 2023). They say the HS 2022 transposition of several FTAs was not complete in 2022. | |

## What is not here

- HS2022 orders for the other agreements (ACFTA, AKFTA, AIFTA, AANZFTA, AHKFTA and the bilateral FTAs). The customs department lists none dated 2022, and MITI's 2022 notices say those transpositions were not finished, so in 2022 these preferences most likely still ran on the AHTN 2017 orders in the first table. This is a reading of the notices, not a confirmed fact.
- The 2019 AANZFTA (P.U.(A) 266/2019), ACFTA (P.U.(A) 212/2019) and AHKFTA (P.U.(A) 209/2019) orders. They are only on federalgazette.agc.gov.my, which the proxy still refused (502) on 2026-10-23. lom.agc.gov.my serves PDFs by direct link, but its search returns encrypted responses, so the 2019 orders could not be found there.

Licence: Malaysian government publication; official treaty and gazette text; the portal states no open licence. Kept in the private repo.
