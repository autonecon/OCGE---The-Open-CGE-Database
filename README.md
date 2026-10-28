# OCGE Data Base

**Beta v5.5, work in progress (28 October 2026).** A Matra project.

The OCGE (Open CGE) Data Base is a global, balanced data base for computable general equilibrium (CGE) analysis: production, consumption, trade, taxes, factor incomes and energy for **2022**, in **167 regions and 51 sectors**. It is built by the published method of the GTAP Data Base (GTAP 12 documentation chapters) from open, cited sources, and it is meant as a complement to GTAP. The files use the standard GTAP version 7 layout, so GTAP-style models can read them. They are tested with the GTAPv7 model in Julia (Ivanic 2025).

This is a beta. The numbers are usable for macro, trade and terms-of-trade work. Sector results in regions that borrow their structure from a donor table are indicative. Read the known caveats in the release notes before you use them.

## Getting the data base

Download the data base from the **Releases** page (tag `v0.5.5-beta`), not from the git tree:

| File | What it is |
|---|---|
| `gsdfset.har`, `gsdfpar.har`, `gsdfdat.har` | The data base in GTAP v7 HAR format (sets, parameters, data) |
| `gtap_s15.jls.gz` | The same data as a gzipped Julia serialisation for GTAPv7-Julia |
| `cde_calibration_s15.csv.gz`, `cde_target_rows_s15.csv`, `parameters_by_sector_s15.csv` | Demand-system calibration and parameter tables |
| `s16_report/` | The final checks: identities, macro checks against WDI, and the calibration and shock tests on 49 aggregation maps |
| `SHA256SUMS` | Checksums of every release file |
| `OCGE_documentation_betav5_5.pdf` | Full documentation: every stage, source, decision and known issue |

To solve with GTAPv7-Julia: the data base keeps one-sided Armington agents (an agent that buys a commodity only from domestic producers or only from imports). The Julia levels model cannot take these as they stand, so run `dataset/build/s15_har/julia/prepare_for_solve.jl` (`armington_swap!`) on each aggregated data base before calibration, as `model_check.jl` does.

## What is in this repository

```
dataset/
  build/          the build pipeline, stages S01-S16 in GTAP construction order
    sNN_*.py      one script per stage; sNN_*/ hold each stage's modules
    config/       every decision, concordance and hand-transcribed value, with its source and who decided it
    specs/        a plain-English specification of each stage
    tests/        unit and mutation tests (python3 -m unittest discover -s tests -t .)
    tools/        data preparation, pin updates, release gate
  data/
    MANIFEST.csv  every raw input file: URL, version, download date, size, SHA-256, licence, redistribution status
    <source>/     a README per source and, where there is one, its fetch script
  prep/           donor-table choices for economies without an OECD ICIO table
  SOURCES.md      the list of sources in plain words
NOTICE.md         credits and terms for every source
```

## Rebuilding from the sources

Raw source files are **not** in this repository. Many sources do not allow redistribution, and the rest are too large for git. To rebuild:

1. Download each file listed in `dataset/data/MANIFEST.csv` into `dataset/data/<path>`, from the URL given there (or with the folder's fetch script). Every stage checks each input against its SHA-256 in the MANIFEST and stops on a mismatch, so you need the exact version listed.
2. Some sources need an account or have terms that restrict use (for example UNCTAD TRAINS through WITS). Their MANIFEST rows say so. You must obtain them yourself under the publisher's terms.
3. S01 reads three GTAP 12 documentation chapters, which the GTAP Center publishes and which are not shipped here. Download them from the GTAP website into `dataset/docs/literature/gtap12/` as `GTAP12_ch09D_representative_table_composite_regions.pdf`, `GTAP12_ch10B_services_trade.pdf` and `GTAP12_ch14B_labor_payments.pdf`.
4. Run `bash dataset/build/tools/prepare_data.sh`, then the stages in order (`cd dataset/build && python3 s01_sets_registry.py`, then S02 to S16). See `dataset/build/README.md` and the stage specs. After you commit each of S01, S05, S07, S08 and S09, run `python3 tools/update_pins.py --after SNN`, because later stages pin the upstream snapshots they read.

Stage snapshots contain values from sources with restrictive terms. Rebuild in a **private** fork and do not publish the snapshots.

Tested with Python 3.13 (`numpy`, `pandas`, `scipy`, `duckdb`, `openpyxl`, `xlrd`; S15 pins its versions in `dataset/build/requirements-s15-build.txt`) and Julia 1.12 (`dataset/build/s15_har/julia/Project.toml`).

## Licences

- **Code:** MIT (`LICENSE`).
- **Data base files (release assets):** CC BY 4.0 (`DATA_LICENSE.md`).
- **Sources:** each keeps its own terms; see `NOTICE.md`.

## Citing

See `CITATION.cff`. The documentation PDF on the release page describes the method in full.

## Status

This is the first public beta. Planned for the next version: the China import gap against China customs, natural gas liquids, power prices for four countries, and real input-output tables for more economies. The full list is in the release notes and the documentation.
