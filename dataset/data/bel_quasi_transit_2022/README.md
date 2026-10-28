# Belgium quasi-transit share of exports by HS2, 2022 (beta v4 P26, option usa_bel)

- **What:** share = 1 - national-concept exports / community-concept exports, Belgium to World, 2022, by HS2 (97 chapters, none clipped).
- **Community concept:** Eurostat Comext DS-045409, reporter BE, partner WORLD, exports, 2022 (EUR 607.03 bn). Raw extract `comext_DS045409_BE_X_HS2_2022.json`. Licence: Eurostat reuse policy (free with attribution).
- **National concept:** UN Comtrade public API, reporter 56, flow X, partner World, HS2, 2022 (EUR 430.08 bn at Comtrade's conversion factor), data supplied by NBB. Only the derived values are kept here (column national_concept_eur); the Comtrade raw file stays outside git. Licence: UN Comtrade terms of use (attribution).
- **Assumption, not confirmed:** that Belgium's Comtrade submission is the NBB national concept (inferred from the 29% gap to Comext). NBB and Statbel were not reachable to confirm it.
- **Caution:** the gap is quasi-transit (non-resident goods passing through), not residents' re-exports. BACI's Belgian exports (USD 493.8 bn) sit between the two concepts, so applying the full share to BACI removes too much.
- **Built by:** `build_bel_share.py` (provenance in `bel_quasi_transit_share_hs2_2022.provenance.txt`).
