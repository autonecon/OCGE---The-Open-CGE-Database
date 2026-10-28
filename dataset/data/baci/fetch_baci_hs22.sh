#!/usr/bin/env bash
# BACI HS22 v202601 (CEPII, Etalab 2.0). The zip is 301 MB, above GitHub's 100 MB limit, so the VM downloads it.
# Extracts the 2022 year file and the country codes that the S10 tariff builder reads.
set -euo pipefail
cd "$(dirname "$0")"
[ -f BACI_HS22_V202601.zip ] || curl -sfS -m 1800 -o BACI_HS22_V202601.zip https://www.cepii.fr/DATA_DOWNLOAD/baci/data/BACI_HS22_V202601.zip
echo "376f9b4cda53710a580f347b9bae69c5fb16911d0ae19b50896c109bd5dfb1f7  BACI_HS22_V202601.zip" | sha256sum -c -
unzip -o -q BACI_HS22_V202601.zip 'BACI_HS22_Y2022_V202601.csv' 'country_codes_V202601.csv'
ls -la BACI_HS22_Y2022_V202601.csv country_codes_V202601.csv
