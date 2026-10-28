# hk_trade_idds: Hong Kong C&SD Trade-IDDS API, 2022 annual

Used by the S07 re-export prep (`dataset/build/prep_trade/`). DATA.GOV.HK terms of use (free reuse with attribution).

- `API_eng.txt`: `pdftotext -layout` of https://tradeidds.censtatd.gov.hk/MetadataLink/ApiSpec/API_eng.pdf (country code annex).
- `tx_hs2.json`, `rx_hs2.json`, `dx_hs2.json`: total exports, re-exports and domestic exports by consignment x HKHS2.
  `rx_od.json`: re-exports by origin x consignment, all commodities. `totals.json`: published 2022 totals.
- `m_co_hs2.json`: imports by country of origin x HKHS2 (added 2026-10-23 for the S07 retained-import step).

Refetched 2026-10-23 (S07 HKG retained-import fix round). The API now allows 30 countries x 20 chapters a
call, so the pull used larger batches, and the rows were put back in the original batch order (8 countries x 10
chapters; 24 x 24 for `rx_od`), sorted by country name within a batch, as the API returns them. `totals.json`
reproduces its 2026-10-21 pin byte for byte. The other four files have exactly the pinned byte length, but not
the pinned SHA-256: row order inside some original batches differs, probably because the 2026-10-21 pull split
batches when it hit the usage limit. MANIFEST holds the new SHA-256. The S07 stamp of 2026-10-21 (output
SHA256SUMS `1a52be59...`) was rerun from these files on 2026-10-23 and every output file is byte-identical.
