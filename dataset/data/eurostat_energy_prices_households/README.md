# eurostat_energy_prices_households: household gas and electricity prices, 2022 (for S10, fix-round item A1)

- **Source:** Eurostat `nrg_pc_202` (gas prices for household consumers) and `nrg_pc_204` (electricity prices for household consumers), bi-annual, SDMX 2.1 dissemination API (ec.europa.eu/eurostat). Keyless.
- **Fetched:** 2026-10-24 by `fetch_eurostat_household_prices.sh`: 2022-S1 and 2022-S2, all consumption bands, all tax levels (I_TAX, X_VAT, X_TAX), all currencies.
- **Licence:** Eurostat reuse policy (CC BY 4.0). Redistributable with attribution.
- **Use:** S10 report check S10-Renergyeu: (X_VAT - X_TAX) / X_TAX on the medium household bands (gas GJ20-199, electricity KWH2500-4999), EUR, mean of the two halves, is the non-VAT tax-and-levy rate on household gas and power; it is compared with the booked household rates on the gas and ely rows. Not booked. The non-household tables are in `eurostat_energy_prices/`.

| File | Bytes | SHA-256 |
|---|---|---|
| `eurostat_energy_prices_households/fetch_eurostat_household_prices.sh` | 568 | `6587c91d60dbe3fe546fee93a291c4a9e9366f9187a2caa5883d0a08526096d5` |
| `eurostat_energy_prices_households/nrg_pc_202_2022S1_2022S2.csv` | 320140 | `3e3d7cf2ef1819be1aeac0a0e7519cacf33da88fe8d0aef722ef9c632aac2a2a` |
| `eurostat_energy_prices_households/nrg_pc_204_2022S1_2022S2.csv` | 396183 | `48afaf4b32a40ecd61a2cde7896edfe32f15bb22cfc0655845bc8fa3f35ce364` |
