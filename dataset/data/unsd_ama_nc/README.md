# UN National Accounts Main Aggregates, national currency (current, constant 2020, implicit deflators)

- **Folder:** `data/unsd_ama_nc/`
- **Source page:** [https://unstats.un.org/unsd/snaama/downloads](https://unstats.un.org/unsd/snaama/downloads)
- **Download URL / API:** https://unstats.un.org/unsd/amaapi/api/file/1 , /file/5 , /file/15
- **Version:** as served 2026-10-20 (data to 2024)
- **Download date / origin:** 2026-10-20 22:33 UTC+7, curl from the box, TLS verified
- **Licence:** UN data terms; attribution "UNSD, National Accounts Main Aggregates Database"
- **Coverage:** all UN members, 1970-2024; no TWN
- **Units:** national currency units (not millions); deflators 2020 = 100
- **Valuation basis / concept:** SNA expenditure aggregates at market prices
- **How it is used:** S02 capital, for rolling forward countries whose investment WDI lacks. Currently that means UAE (ICSD 2019 to 2022); see reviews/FIXROUND2/are_twn_capital.md. Read by S02 through `build/config/s02/capital_roll_sources.csv` (ARE GFCF, fix round 3, David 22:31).

## Files

| File | SHA-256 |
|---|---|
| `unsd_ama_nc/Download-GDPconstant-NCU-countries.xlsx` | `ef57043aaf1e6af0256f7de2274526e1da85eb45536aba3efe403b8f9285255f` |
| `unsd_ama_nc/Download-GDPcurrent-NCU-countries.xlsx` | `2434ffdbcfc527314cf5bae6e3530cc8be8138cfeae96c1aea6a979a213ee29f` |
| `unsd_ama_nc/Download-IPD-countries.xlsx` | `ecb90ad39af2751059f36f8c930ca03090236ccb15aef2fb2a627ed01c7b0c2e` |
| `unsd_ama_nc/are_gfcf_gdp_deflator_2008_2023_extract.csv` | `e0a08daa8e13c810176375754ff4c95eaf600ef9a17ff84a5e5d67c7b959b581` |

Per-file URLs are in `data/MANIFEST.csv`.
