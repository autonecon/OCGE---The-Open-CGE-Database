# US Census imports/hs, 2022 annual

Public extract for S08 transport-mode shares and the USA margin comparison. No API key is stored.

- **Source:** US Census Bureau International Trade API, `imports/hs`, time `2022-12` (annual).
- **Date fetched:** 2026-10-21.
- **Licence:** US government work, public domain.
- **Fetch:** `fetch_census_2022.py` reads `CENSUS_API_KEY` from the environment only. The URL is not logged.

Queries (the key is not part of the recorded query):

- HS6, world: `get=I_COMMODITY,GEN_VAL_YR,GEN_CHA_YR,AIR_VAL_YR,AIR_CHA_YR,VES_VAL_YR,VES_CHA_YR&time=2022-12&COMM_LVL=HS6`
- HS2, by country: the same measures plus `CTY_CODE,CTY_NAME`, `COMM_LVL=HS2`

`GEN_VAL_YR` is general customs value and `GEN_CHA_YR` is general import charges (freight, insurance and other transport charges). `AIR_*` and `VES_*` are the air and vessel parts. Dollars.

Sanity on the HS6 file: `GEN_VAL_YR` sums to 3,239.7 billion USD and `GEN_CHA_YR` to 129.3 billion USD (3.99 percent). `mode_split=us_census_charges_by_sector` uses this extract.
