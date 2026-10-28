# eia_foks: EIA Fuel Oil and Kerosene Sales by end use, U.S., annual (for S10, fix-round item A1)

- **Source:** U.S. Energy Information Administration, *Fuel Oil and Kerosene Sales* (dnav page
  `pet_cons_821use_dcu_nus_a`, thousand gallons, 2015-2020). The survey is suspended; the page was released
  2022-02-09 and 2020 is the last year published, so 2020 is the latest year at or before 2022.
  US government work, public domain.
- **Fetched:** 2026-10-24 by `fetch_eia_foks.sh`.
- **Use:** S10 `s10_tariffs/energy_tax.read_foks_latest`: the on-highway share of transportation distillate in 2020,
  series K2DVHNNUS1 (on-highway, 40,790,502) over KD0VTTNUS1 (total transportation: railroad, vessel bunkering,
  on-highway; 45,567,273), 0.8952. It takes rail and vessel bunkering diesel, which pays no road-fuel tax, out of the
  2022 MER transportation distillate (`../eia_us_motor_fuel_taxes/`).

| File | Bytes | SHA-256 |
|---|---|---|
| `eia_foks/fetch_eia_foks.sh` | 576 | `cf2649e8eba2f43a6cd4ac5204222ab3a2b84a4d6b3bd6bb7acda2abb69d7791` |
| `eia_foks/pet_cons_821use_dcu_nus_a.htm` | 53905 | `9a3293ea3cdbc907883626f1db6ed8ce1dbe700de96b92d28c8cb11ccef631f1` |
