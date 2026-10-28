# Zambia customs tariff 2022 and Comtrade vehicle unit values

Inputs for the Zambia chapter 87 lines that the S10 rebuild has to treat as failed UNCTAD AVE conversions (see `dataset/stages/S10_tariffs_taxes/S10_REBUILD_HANDOFF.md`). Copied 2026-10-22 from `an internal working folder`, where they were fetched on 2026-10-19 for `ave_fix_research_2026-10-19.md`.

| File | What | Source |
|---|---|---|
| `zm_tb_2022.pdf` | ZRA Customs and Excise Tariff (HS Book), last updated 31/12/2021, the 2022 edition. First Schedule pp. 396–401 hold the new-vehicle alternate duties ("X% or K N per vehicle, whichever is the greater"). | https://www.zra.org.zm/wp-content/uploads/2022/01/2022-NATIONAL-TARIFF-BOOK-Jan-2022.pdf, via the Wayback Machine (ZRA blocks the box) |
| `zm_mv_2022.pdf` | ZRA specific-duty schedule for used motor vehicles. Its GRAND TOTAL columns bundle customs, excise, VAT and fees; do not read them as customs duty. | ZRA (see the research note §2) |
| `comtrade_2022/zm_*.json` | UN Comtrade public preview API, reporter 894, flow M, 2022, partner World, one file per HS4/HS6 in 8702–8704. Value and unit quantity for unit values. Most quantities are flagged estimated. | https://comtradeapi.un.org/public/v1/preview/ |
