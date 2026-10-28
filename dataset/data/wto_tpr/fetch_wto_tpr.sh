#!/usr/bin/env bash
# WTO Trade Policy Review, Secretariat reports (public PDFs on www.wto.org). Used for the export-duty
# product lists of fix-round item A2 (S10 config/s10/export_tax_products_2022.csv).
set -euo pipefail
cd "$(dirname "$0")"
for s in 412 459 401 436 439 458 416 403; do
  curl -sfS -m 300 -o wt_tpr_s${s}.pdf "https://www.wto.org/english/tratop_e/tpr_e/s${s}_e.pdf"
done
sha256sum wt_tpr_s*.pdf
