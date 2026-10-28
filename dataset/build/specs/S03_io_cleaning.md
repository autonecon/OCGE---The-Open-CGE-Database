# S03 I-O cleaning and the representative table: spec additions (fix rounds 1 and 2)

The base spec is PLAN.md §3(b1) (item 1b as amended by erratum E37: no PRI or VIR append) and GTAP 12 ch.8 and ch.9D §D.1. This file adds the items decided at fix rounds 1 and 2. S03 has not been built yet.

## Puerto Rico and the US Virgin Islands: NOT appended to ICIO USA (David 2026-10-20 22:02 UTC+7; replaces E31 of 19:40)

- **Decision:** S03 does not build or append PRI or VIR I-O tables. ICIO USA is used as OECD publishes it (50 states and DC).
- **Why:** GTAP keeps PRI as its own region, so appending it was our own extension, and doing it properly needs a territorial adjustment (mainland-PR shipments sit in ICIO USA trade with ROW, while BACI 842 already contains PR's and USVI's foreign trade). David's rule for this build: stay with GTAP's method and keep it simple.
- **What this means:**
  - PRI and VIR stay in region USA (S01). Their GDP, C, G, GFCF and capital stay in S02 USA macro (WDI 2022 GDP: PRI 113.8 bn, VIR 4.7 bn USD, about 0.45% of USA region GDP).
  - Their trade with foreign countries stays inside BACI USA (842) and BaTIS USA.
  - The ICIO USA table is about 0.5% smaller than USA macro. The normal macro fit at S13-S14 (PLAN stage (i): the I-O table is fitted to the macro and trade controls, with C, G and I scaled to GDP) absorbs this; no PRI-specific step and no plug.
- **Checks at S03:**
  - Report: ICIO USA GDP (VA + net product taxes) against S02 USA region GDP, with the PRI + VIR share shown as the expected gap.
  - Report: ICIO GDP against WDI GDP for every ICIO economy (review S02-M3).
- **Logged:** known flaw and improvement (add PRI/VIR structure with a territorial adjustment, or make PRI its own region as GTAP does) in `docs/ISSUES_AND_DECISIONS.md`.

## Base year

Every input path and year filter uses `BASE_YEAR` from `lib/stagekit.py`. For 2017 the ICIO file is `2017_SML.csv`, which is on disk.
