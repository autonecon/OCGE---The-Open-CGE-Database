# Statistics Canada CIMT 2022: energy re-export shares (beta v4 P24)

- **Source:** Statistics Canada, Canadian International Merchandise Trade Web Application (71-607-X2021004), bulk files on a customs basis, Jan-Dec 2022, revised 2025-01-09.
  - Domestic exports (HS6 file ODPFN018): https://www150.statcan.gc.ca/n1/pub/71-607-x/2021004/zip/CIMT-CICM_Dom_Exp_2022.zip (sha256 27530e496992e7f9c0c3bd5e0321a1265785f228eb114f42cb4ca70e875e3ea2)
  - Total exports (HS6 file ODPFN019): https://www150.statcan.gc.ca/n1/pub/71-607-x/2021004/zip/CIMT-CICM_Tot_Exp_2022.zip (sha256 e348821e861d707665a376261528a7fb23872c18374c449a4a173888d7a69e5e)
- **Licence:** Statistics Canada Open Licence (https://www.statcan.gc.ca/en/reference/licence); attribution required.
- **Kept here:** only `can_energy_reexport_share_2022.csv`, the HS6 sums (the two zips are 45 MB; download them from the URLs above).
- **Method:** re-exports = total exports - domestic exports (StatCan: total = domestic + re-exports). Shares: crude 2709 2.6e-8, natural gas 271111+271121 0, all 2711 8.4e-6, refined products 2710 0.00118, all goods 0.0667.
