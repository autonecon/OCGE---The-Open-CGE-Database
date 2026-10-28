# GTAP-method CGE database (base year 2022; 2017 validation build): build code

Code only. No data, no stage outputs. Local commits only.

- `lib/stagekit.py`: the stage snapshot kit.
  - Writes outputs + SHA256SUMS, checks, ledger, flags, log, inputs.lock, and STAMP only if there is no hard FAIL and the code is committed.
  - **Base year:** `GTAP_BASE_YEAR` (default 2022). For 2017 the snapshots go to `../stages_2017/`.
  - **Reruns archive the previous snapshot** to `stages/<Snn>/archive/<timestamp>/`; nothing is deleted.
  - **Inputs:** the kit refuses a missing input or a SHA mismatch against MANIFEST. It records the year used (`config/source_years.csv`) and adds hard checks `<Snn>-IN1` (own data inputs in MANIFEST, SHA match) and `<Snn>-IN2` (year rule).
  - `GTAP_STAGES_DIR` is for code smoke tests in a scratch folder only.
- `sNN_<name>.py`: one script per GTAP stage, in GTAP 12 ch.17B order. Run: `python3 s01_sets_registry.py` (or `GTAP_BASE_YEAR=2017 python3 ...`).
- `check_manifest.py`: global audit of `../data/MANIFEST.csv` (every file exists, SHA recomputes, nothing on disk is unlisted). It is not a stage gate and writes `../MANIFEST_AUDIT.md`.
- `config/sNN/`: cited decision and concordance tables used by each stage. `config/source_years.csv` gives the year used per source and base year.
- `specs/`: spec additions for stages not yet built (e.g. S03 PRI append).
- Snapshots: `../stages/<Snn_name>/`. Inputs: `../data/` (MANIFEST.csv holds every SHA-256).

## Full build on a fresh clone: data prep and upstream pins (beta v4)

- `bash tools/prepare_data.sh` joins the split `.partNN` data files, extracts EIA `INTL.txt`, extracts the BACI HS22 2022 file that S10 reads, and links the GTAP 12 PDFs that S01 reads. Then run S01 once, because S07 reads S01's uncommitted `concord_hs17_to_sector.csv`.
- S06, S08, S09 and S10 pin their upstream by constants: the io checksum, and for S07-S09 the STAMP commit, time, SHA256SUMS and the hashes of the files read. After you build and commit S05, S07, S08 or S09, run `python3 tools/update_pins.py --after SNN` and commit the code before the next stage. `--check` lists the pins that differ. The pins hold the commit that touched the STAMP, so commit the stage outputs first.
