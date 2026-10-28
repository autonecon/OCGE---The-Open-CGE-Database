# EIA US energy 2022 (keyless), for S11 US scrutiny

- **Folder:** `data/eia_us_2022/`
- **Source:** US Energy Information Administration. Monthly Energy Review (https://www.eia.gov/totalenergy/data/monthly/) CSV tables, and petroleum / natural gas annual series (https://www.eia.gov/dnav/).
- **Fetch:** `fetch_eia_us_2022.sh` (no API key). Fetched 2026-10-21 (UTC+7). sha256 in `data/MANIFEST.csv`.
- **Licence:** US government work, public domain; cite EIA.
- **Year:** 2022 (MER annual rows are `YYYYMM = 202213`).
- **Use:** report-only US checks at S11 (production, trade and consumption of crude, NGPL, dry gas, coal, electricity). Not a volume source: S11 volumes stay the PR #72 EIA International series.
- **Key 2022 values (MER):** crude 12,026.5 kb/d (T03.01 PAPRPUS); NGPL 5,933.1 kb/d (NLPRPUS); dry gas 36,254.9 bcf = 1,026.6 bcm (T04.01 NGPRPUS); gas imports 3,024.1 bcf, exports 6,906.4 bcf; coal 594.2 million short tons = 539.0 Mt (T06.01), exports 85.96 Mst; electricity net generation 4,230.7 TWh, imports 56.97, exports 15.76 TWh (T07.01).
