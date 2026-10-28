# UN Comtrade 2022 total exports by reporter

- **Folder:** `data/un_comtrade_partner_x_2022/`
- **Source:** UN Comtrade public preview API, https://comtradeapi.un.org/public/v1/preview/C/A/HS?period=2022&cmdCode=TOTAL&flowCode=X&partnerCode=0 (no key)
- **Download date:** 2026-10-27 (fetch_partner_x_2022.sh)
- **Coverage:** 168 reporters, 2022 annual, total exports to World as each reporter records them (FOB). Taiwan is reporter 490 ("Other Asia, nes"; BACI ISO3 S19 = TWN).
- **Units:** USD
- **Licence:** UN Comtrade terms of use (public API data, attribution)
- **Used by:** S07 choice `importer_floor_partner_cap` (beta v5 B follow-up). A partner's importer-floor top-up is capped so its goods exports stay at most this total.
