# UN National Accounts Official Country Data, table 3.2: household final consumption by purpose (COICOP), South Africa 2022

Used by S03 (beta v5 H, choice `household_employers_va` = `listed_economies_t_va_at_domestic_workers_x_median_pay_rest_to_p_q_by_figaro_d1_up_to_the_hfce_by_coicop_share_rest_to_other_household_services`): the cap on household
purchases of education (ISIC P, COICOP 10) and health (ISIC Q, COICOP 06) in South Africa.

- Source: UNdata, SNA dataset, table 3.2 "Final consumption expenditure by purpose at current prices", South Africa
  (country code 710), series 1100, SNA 2008, rand, as reported to UNSD by Statistics South Africa (the Stats SA HFCE by
  purpose table published with P0441).
- Fetched 2026-10-27 08:47 UTC from
  `https://data.un.org/Data.aspx?d=SNA&f=group_code%3a302%3bcountry_code%3a710` (HTML table; the Stats SA site itself
  is not reachable from the build box). `zaf_table32_hfce_by_purpose_2022.csv` holds the 2022 household rows as
  published (value in rand); nothing is transformed.
- 2022 shares of HFCE (R 4,222.9 bn): education 3.53%, health 6.84%. COICOP 06 includes medical products bought from
  pharmaceutical and other goods industries, so 6.84% is an upper bound for health services (ISIC Q).
- Licence: UN data terms of use (free reuse with attribution: "UNSD, National Accounts Official Country Data").
