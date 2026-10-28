# eia_us_motor_fuel_taxes: US federal and state motor fuel taxes and road-fuel volumes, 2022 (for S10, fix-round item A1)

OECD DF_NEERS has no US values, so before this folder the USA took its S12 pool's average energy-tax rates
(household petroleum about 41%). These EIA files make the USA a source region for road-fuel excise.

- **Source:** U.S. Energy Information Administration (www.eia.gov), keyless. US government work, public domain.
- **Fetched:** 2026-10-24 by `fetch_eia_us_motor_fuel_taxes.sh`.
- `pmm_fueltaxes.xlsx`: EIA *Petroleum Marketing Monthly*, "Federal and state motor fuel taxes", every half-year
  vintage 2015-2026. S10 reads the sheets `January 2022` and `July 2022 (revised)` (rates in effect on 1 January and
  1 July 2022): the federal total (excise plus the LUST fee: 18.4 c/gal gasoline, 24.4 c/gal diesel; statutory,
  26 USC 4081 and 4041(d)) and the EIA "Average state tax" row, column "State tax" (state excise, the unweighted
  average over the states and DC: gasoline 26.06 and 26.65 c/gal, diesel 27.64 and 28.19 c/gal). The "Other taxes
  & fees" column (it may include sales and use taxes, which are general product taxes) and county and local taxes are
  not used.
- `MER_T03.07C.csv`: EIA *Monthly Energy Review* Table 3.7c, petroleum consumption by the transportation sector
  (browser CSV, all years). S10 reads the 2022 annual rows (YYYYMM 202213): MGACPUS motor gasoline 8,421.19 kb/d and
  DFACPUS distillate fuel oil 3,031.609 kb/d.
- The on-highway share of transportation distillate is in `../eia_foks/` (EIA FOKS, last published year 2020).
- **Use:** S10 `s10_tariffs/energy_tax.us_motor_fuel` (choice `energy_tax_usa`): revenue = (federal + average state
  excise, mean of 1 January and 1 July 2022) x 2022 gallons (gasoline: transportation motor gasoline; diesel:
  transportation distillate x the on-highway share), booked as the NEERS ROAD-sector revenue on the pet row of the USA.
  About 79.5 bn USD (federal 33.9, state 45.6).
- **Limits:** the state rate is EIA's unweighted average, not a volume-weighted one; motor gasoline consumed by the
  transportation sector includes some untaxed uses (refunds are not netted); state utility, gross-receipts and
  electricity or gas excise taxes are not sourced, so the other US energy rows carry no energy tax.

| File | Bytes | SHA-256 |
|---|---|---|
| `eia_us_motor_fuel_taxes/fetch_eia_us_motor_fuel_taxes.sh` | 918 | `8486dce8bf7ae14967c668ce75e0a0384a4e992d224360a5c4a0a16c3a6ed818` |
| `eia_us_motor_fuel_taxes/pmm_fueltaxes.xlsx` | 308831 | `c67fa0d3ab9e86448164ffd1f995b1afc1f337d1de34d6e446a160706e0b310e` |
| `eia_us_motor_fuel_taxes/MER_T03.07C.csv` | 1092098 | `77095f1c831bdc6a3a0fd0e254ec0b8a9472cb396ce3ba5a9b9bb114cde84a06` |
