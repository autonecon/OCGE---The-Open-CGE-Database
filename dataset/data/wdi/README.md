# World Bank World Development Indicators extracts

- **Folder:** `data/wdi/`
- **Source page:** [https://datacatalog.worldbank.org/search/dataset/0037712/world-development-indicators](https://datacatalog.worldbank.org/search/dataset/0037712/world-development-indicators)
- **Download URL / API:** https://api.worldbank.org/v2/ (see PROVENANCE files)
- **Version:**
- **Download date / origin:** `wdi_services_2022.csv` was refetched 2026-10-21 (UTC+7) from the World Bank API v2 (BX.GSR.NFSV.CD and BM.GSR.NFSV.CD, 2022, long layout). It replaces the 2026-10-20 wide copy `a34c5cff` (16,749 bytes). USA and world services totals are the same. The other files in this folder were copied 2026-10-20 from an earlier internal build, earlier-build/sources/wdi.
- **Licence:** CC BY 4.0
- **Coverage (2022 or year-rule fallback):** all WB members
- **Units:** current USD, percent
- **Valuation basis / concept:** purchasers prices (GFCF), market prices (GDP)
- **How it is used (PLAN.md stage):** Fix round 2 (2026-10-20 22:02): `wdi_capital_series_1960_2022.csv` (GFCF current USD, constant 2015 USD and current LCU; GDP deflator; GDP current LCU; 1960-2022) builds S02 capital per GTAP 12 ch.7 s7.3 (ICSD rolled forward; own-investment perpetual inventory where ICSD is missing); see `FETCH_NOTES_capital_series.md`. Stage (h): GDP, C, G, GFCF controls; rents 2021 (NY.GDP.PETR/NGAS/COAL.RT.ZS). TM.TAX.* tariff averages are NOT used for tariffs (old defect). wdi_2017_2022_extract.csv (fetched 2026-10-20 from the WB API v2): GFCF, inventories, C, G current USD, LCU GDP, deflator, exchange rates, labour force, services X/M, import duties, rents, depreciation, population.

## Files

| File | Bytes | SHA-256 |
|---|---|---|
| `wdi/PROVENANCE.txt` | 1,066 | `072fd49b0bb78778bea5091d4592ce4a907e93a14e90cd96b9c74f2f8f70afee` |
| `wdi/PROVENANCE_ACCOUNTS.txt` | 4,308 | `52391d5010427b1fc49296ef11b0467be0fb56d85f8822fdca5aa2652643d2a1` |
| `wdi/PROVENANCE_ENERGY_RENTS_2021.txt` | 1,793 | `0ea15a5600fd9d8658ac6f82e2bf65bb9dd44cfc86ccf42fe8a5d17e0d032e5e` |
| `wdi/TM.TAX.MANF.WM.AR.ZS.csv` | 15,534 | `1de0473ada45be865208ca31586c885682ac3e8286a9dcfa8775d0266cd717df` |
| `wdi/TM.TAX.MANF.WM.AR.ZS.zip` | 21,127 | `68c1d3798d7e9e5dc977c5e3493e28051e78c21b8cde9467a3ef2188c20e9816` |
| `wdi/TM.TAX.MRCH.WM.AR.ZS.csv` | 15,535 | `2c677ccc64cceea6b65743af2561f6df9276d22bf835ab9f0cf6d3e9ba54b996` |
| `wdi/TM.TAX.MRCH.WM.AR.ZS.zip` | 21,158 | `7f5529e78b1ec9469b2a9258cc42387c54e41ae6f894ab41bbc6edfaaf19ec62` |
| `wdi/TM.TAX.TCOM.WM.AR.ZS.csv` | 15,634 | `1b40090143084a0b03df048380d3f96c47c0199d565b1b0922d22b6f9a4df7f1` |
| `wdi/TM.TAX.TCOM.WM.AR.ZS.zip` | 21,397 | `053211ead1a90c7807ad094e0da81c999155e7aab3c7d8506d25c19c154d7f76` |
| `wdi/ny_gdp_pcap_pp_cd.csv` | 12,600 | `53150b7ac8587cfd858757db7c4bb778fad71d9a5fd0e9610fa97426fcef3123` |
| `wdi/ny_gdp_pcap_pp_cd_PROVENANCE.txt` | 633 | `16170a91292857d6d3705551a8bddf55fa54fe71c2857178eaf19ad7bd84fe6c` |
| `wdi/wdi_2017_2022_extract.csv` | 1,275,782 | `fa02eeef09d3dc683904f14fb4cfe44aa019b30c440fb5b53c2a0f2fdb4f328c` |
| `wdi/wdi_accounts.csv` | 111,166 | `bac045b373e5ca162a476428d9af1490472fbc2e0d1b4f01653e773d5504d83c` |
| `wdi/wdi_energy_rents_2021.csv` | 7,156 | `ac87942df8521582ac0a931d881df58a04a285beb32b95fc9c00a5e2e8930956` |
| `wdi/wdi_gfcf.csv` | 30,619 | `5608bb398e63368a393d488561665e259e81700ef085f5cfd776681e88939f73` |
| `wdi/wdi_services_2022.csv` | 20,255 | `a2b80fc3bb134ea0322a2a3604062ff9d54c7231d147a5216fa6eff38ede3247` |
| `wdi/wdi_social.csv` | 10,031 | `db0ab6826e6d4edfb404ce1c502c2120b827ce08221430a93409bd76ff8659a9` |
| `wdi/FETCH_NOTES_capital_series.md` | 1,478 | `b62fb2355c7195100b3c8e813b8187ec71f895706d3206c873c9b0e036b94609` |
| `wdi/wdi_capital_series_1960_2022.csv` | 1,874,078 | `3c8d1202b314fc16a4da86ea140c9576902a2e17e4a9779de493ce7458cdac48` |

Per-file URLs are in `data/MANIFEST.csv`.
