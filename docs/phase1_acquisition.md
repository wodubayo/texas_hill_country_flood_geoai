# Phase 1: Event and data acquisition

## Objective

Acquire and document a temporally suitable Sentinel-1 pair plus ancillary data for the July 2025 Central Texas Hill Country flood. The provisional focus is the Guadalupe River headwaters and Kerr County. Fix the AOI only after comparing watershed boundaries with NASA/NOAA coverage and selecting the study question (riverine flood extent, broader regional change, or both).

## Current status

Repository scaffold and source inventory started 2026-10-21.

2026-11-16: provisional AOI built (Kerr County + 10 km, from registered Census 2024 county boundaries) and the Sentinel-1 inventory retrieved from ASF (`docs/acquisition/sentinel1_inventory.json`). The "July 4" scene was sensed 19:43 CDT on 3 July, before the flood; no Sentinel-1 pass observed the event. RO005 control/pre/post scenes are selected in `config/event.json` (see `docs/acquisition/sentinel1_selection.md`). Scene download requires Earthdata credentials and is pending.

Commands (from project root):

```powershell
.\.venv\Scripts\python.exe src\acquire_phase1.py aoi       # county boundaries -> provisional AOI
.\.venv\Scripts\python.exe src\acquire_phase1.py search    # ASF inventory
$env:EARTHDATA_TOKEN = "<token>"                            # or ~/_netrc
.\.venv\Scripts\python.exe src\acquire_phase1.py download  # selected scenes, MD5 + SHA-256 registered
```

## Search procedure

1. Load the Guadalupe River basin / relevant HUC watershed polygons and the NOAA/NASA event coverage in QGIS. Choose an AOI that captures the flood corridor without expanding the Sentinel-1 search to all of Texas.
2. Search ASF DAAC or Copernicus for Sentinel-1 IW GRD scenes intersecting the AOI from June 15 through July 15, 2025. Record exact product IDs, sensing start/end, orbit direction, relative orbit, polarizations, footprint, and processing baseline.
3. Verify whether a July 4 scene's local sensing time is before, during, or after the flood wave for the AOI. Do not use calendar date alone as event-time evidence. Prefer a pre-event scene on the same relative orbit, and inspect July 11 as a possible recession/persistence view.
4. Query the NASA OPERA event service and download only relevant DSWx-HLS / DSWx-S1 products after checking metadata and footprints. Keep DSWx-S1 as a same-sensor product comparison, not independent accuracy truth.
5. Locate downloadable NASA UAVSAR classifications and NOAA NGS image acquisition dates/footprints. Use them as validation candidates only after matching place and time. Add USGS gauges/high-water marks and NOAA precipitation for event chronology.
6. Save original files under `data/raw/`, metadata and search manifests under `docs/acquisition/`, and SHA-256 hashes in the event manifest. Do not overwrite source files.

## Acquisition gate

Phase 1 is ready to hand off when the AOI, exact pre/event/post product IDs, acquisition times, orbit matching, source provenance, and licensing/access conditions are documented. If no useful July 4 Sentinel-1 scene exists at the desired time, revise the question around what the available acquisition can actually observe.
