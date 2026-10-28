# New Caledonia customs tariff (official text)

Public legal text from the Direction régionale des douanes de Nouvelle-Calédonie (DRDNC), fetched 2026-10-23. For the S10 rebuild of the New Caledonia schedule. `extracted/ncl_dd_lines_2023.csv` (2023 DD by 8-digit line) and `extracted/ncl_dd_2022_changed_hs6.csv` (the HS6 whose DD differed in 2022, from the notice below) are written by `build/tools/s10_extract_tariff_texts.py`.

| File | What | Source |
|---|---|---|
| `tarif_des_douanes_mj01012023.pdf` | *Tarif des douanes de Nouvelle-Calédonie*, consolidated version of 1 January 2023 (533 pages, HS2022). Each 8-digit line carries the DD (customs duty) rate and the TGC rate. PDF modified 2022-12-27. | https://douane.gouv.nc/sites/default/files/atoms/files/tarif_des_douanes_mj01012023.pdf, linked from https://douane.gouv.nc/le-tarif-douanier/generalites |
| `droits_et_taxes_percus_par_la_drdnc_v190526.pdf` | DRDNC sheet of the duties and taxes it collects, with legal bases. It gives the DD base as Délibération n° 294 of 27 December 2022 amending Délibération n° 208 of 14 January 2022 *portant tarif des douanes de Nouvelle-Calédonie*, with DD rates of 0, 5, 10, 15 and 20%. | https://douane.gouv.nc/sites/default/files/atoms/files/droits_et_taxes_percus_par_la_drdnc_v190526.pdf |

| `jonc_10500_20221230_delib294.pdf` | JONC n° 10500 (special issue, 30 December 2022, 643 pages). Délibération n° 294 of 27 December 2022 amending Délibération n° 208, from p. 25637, with the replacement tariff annex. Also has arrêtés 2022-3077/GNC (tariff 2023 application) and 2022-3083/GNC (TGC rates). | https://juridoc.gouv.nc/JuriDoc/JdJonc.nsf/0/3DBEA11E5FE294F04B25892800128D29/$File/10500.pdf (linked from douane.gouv.nc) |
| `drdnc_ao_22001425_tarif_2022_vs_2023.pdf` | DRDNC notice to operators 22001425 (PDF dated 30 December 2022, 84 pages). For each tariff line changed on 1 January 2023 it shows the "TARIF 2022" line next to the "COMEX 2023" line, with the DD, TSPA, TGC and other rates. Most changes merge 8-digit lines ("simplification par regroupement"). | https://douane.gouv.nc/sites/default/files/atoms/files/ao_22001425_-_entree_en_vigueur_du_tarif_des_douanes_modifie.pdf |

## Caveat for 2022

The consolidated tariff is the version in force from 1 January 2023 (Délibération 208 with its annex replaced by Délibération 294). No 2022-dated consolidated tariff is online. On juridoc, the only annex attached to Délibération 208 is the one "mise à jour le 27/12/2022", and douane.gouv.nc links only the 2023 file. To get the 2022 schedule, start from the 2023 file and undo the changed lines, using the 2022 columns of `drdnc_ao_22001425_tarif_2022_vs_2023.pdf` (with Délibération 294 in the JONC as the legal text).

## What is not here

- The original JONC of 20 January 2022 (Délibération 208 as first published, p. 496). juridoc.gouv.nc answers, but its JONC archive cannot be browsed without the document ID, and no search engine indexes that issue.
- The open-data tariff table on data.gouv.nc (connection reset again on 2026-10-23) and its Pacific Data Hub copy (pacificdata.org, refused by the proxy).

Licence: official tariff publication, public legal text; the pages state no open licence.
