# cbs_85867ned: Statistics Netherlands production and income components by industry (B06, 2020-2022)

The beta v5 L check (NLD oil and gas subsidy). Not read by any stage: it records the CBS confirmation of the OECD
Table 6 NLD 2022 B06 D29X39 value that S12 reads. Licence CC BY 4.0 (Statistics Netherlands).

| File | Query |
|---|---|
| b06_2020_2022.json | `https://opendata.cbs.nl/ODataApi/OData/85867NED/TypedDataSet?$format=json&$filter=BedrijfstakkenBranchesSBI2008 eq '305800 ' and (Perioden eq '2020JJ00' or Perioden eq '2021JJ00' or Perioden eq '2022JJ00')` (current table, 2021-2025) |
| b06_2020_2022_84088ned.json | the same query on 84088NED (the discontinued 1995-2022 table, the first 2022 estimate) |

Result (mln euro, SBI 06 "Winning van aardolie en aardgas"): other subsidies on production
(NietProductgebondenSubsidies_21) 4,147 in 2022 and 1 in 2021 (85867NED); 3,996 in 2022 and 0 in 2021 (84088NED).
Other taxes on production 17 (12 in 2021). So D29 - D39 = 17 - 4,147 = -4,130, exactly the OECD Table 6 value.
Fetched 2026-10-27.
