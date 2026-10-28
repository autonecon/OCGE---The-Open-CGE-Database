#!/usr/bin/env bash
# EIA Fuel Oil and Kerosene Sales (FOKS): distillate fuel oil and kerosene sales by end use, U.S., annual,
# thousand gallons. The survey is suspended; the last year published is 2020 (release 2022-02-09).
# Used by S10 (fix-round A1, energy_tax_usa) for the on-highway share of transportation distillate.
# www.eia.gov, keyless; US government work (public domain).
set -euo pipefail
cd "$(dirname "$0")"
curl -sfS -m 120 -o pet_cons_821use_dcu_nus_a.htm "https://www.eia.gov/dnav/pet/pet_cons_821use_dcu_nus_a.htm"
sha256sum pet_cons_821use_dcu_nus_a.htm
