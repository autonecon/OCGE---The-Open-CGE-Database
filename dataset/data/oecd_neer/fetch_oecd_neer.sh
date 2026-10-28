#!/usr/bin/env bash
# OECD Net Effective Energy Rates (Taxing Energy Use / Effective Carbon Rates family), keyless SDMX.
# Dataflow OECD.CTP.TPS,DSD_NEER@DF_NEERS,1.1. Base sectors and base energy sources only (no aggregates),
# the tax and subsidy measures in EUR per GJ at current prices, and the tax base in TJ. Years 2021 and 2023
# (the dataflow has 2018, 2021 and 2023; 2023 is the latest).
# Also the Eurostat EUR/USD annual average (ert_bil_eur_a) used to convert EUR to USD.
set -euo pipefail
cd "$(dirname "$0")"
SECTORS=AGRIFISH+ELEC+INDUSTRY+OFFROAD+RESCOM+ROAD
SOURCES=BIOF+COAL+DIES+FOIL+GASO+KERO+LPG+NGAS+OFFS+GEO+HYDR+NUCL+OEHS+SWO
MEASURES=FUETAX+CARBTAX+ELETAX+TOTTAX+SUBSID+ELESUBSID+TOTSUBS+TAXBTJ
curl -sfS -m 600 -H "Accept: application/vnd.sdmx.data+csv; charset=utf-8" -o neers_2021_2023.csv \
 "https://sdmx.oecd.org/public/rest/data/OECD.CTP.TPS,DSD_NEER@DF_NEERS,1.1/.${SECTORS}.${SOURCES}.${MEASURES}.EUR_GJ+TJ..V.A?startPeriod=2021&endPeriod=2023"
curl -sfS -m 120 -o eur_usd_ert_bil_eur_a.csv \
 "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/ert_bil_eur_a/A.AVG.NAC.USD?format=SDMX-CSV&startPeriod=2021&endPeriod=2023"
sha256sum neers_2021_2023.csv eur_usd_ert_bil_eur_a.csv
