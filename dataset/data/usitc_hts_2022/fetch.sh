#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
curl -sfS -m 300 -o hts_2022_revision_12_json.json https://www.usitc.gov/sites/default/files/tata/hts/hts_2022_revision_12_json.json
echo "e88cff9e5bc3c80f0e9dd3a3fde5f4e61d8a8ae325c70bb369cdeb5aae442fe5  hts_2022_revision_12_json.json" | sha256sum -c -
