# Texas Hill Country Flood Mapping

An independent project to map the July 2025 Central Texas / Hill Country flood using a reproducible Sentinel-1 change-mapping workflow, then compare results with available event observations and reference products. This repository follows the structure of the Lagos project while keeping its data, configuration, outputs, and event assumptions separate.

## Study status

The project is at Phase 1: source and event-window assessment. The initial focus is the Guadalupe River headwaters and Kerr County, with the AOI to be finalized from hydrologic boundaries and the available satellite and aerial coverage. This is an exploratory mapping study; candidate detections will not be described as validated flood extent until reference evidence supports that claim.

## Repository structure

```text
config/                 Event and processing configuration
data/raw/                Original satellite and reference data (not committed)
data/interim/            Prepared boundaries and SNAP intermediates (not committed)
data/processed/          Analysis-ready rasters (not committed)
docs/                    Phase methods, evidence, and acquisition records
graphs/                  Saved ESA SNAP graphs
models/                  Future model artifacts (not committed)
notebooks/               Exploratory notebooks
outputs/                 Run reports, maps, and metrics (not committed)
qgis/                    QGIS project files
src/                     Acquisition, preprocessing, analysis, and validation tools
tests/                   Unit and integration tests
docker/                  Optional reproducible runtime definitions
```

## Event and first data leads

The event began on July 4, 2025, with the greatest reported impacts in Kerr County and the Guadalupe River basin. NASA's event response page describes airborne optical and UAVSAR collection. NASA also published OPERA DSWx-HLS and DSWx-S1 map services for this event; the service lists pre-event and event/post-event source dates, but describes results as preliminary and unvalidated. NOAA's National Geodetic Survey collected aerial damage-assessment imagery beginning after the event. See [the event record](docs/events/TX_HILL_COUNTRY_2025_07.md), [data catalog](docs/data_catalog.md), and [Phase 1 plan](docs/phase1_acquisition.md).

## Workflow

1. Finalize the hydrologic AOI and acquire source data with complete provenance.
2. Preprocess Sentinel-1 scenes with ESA SNAP and assess coverage, timing, and terrain effects.
3. Develop exploratory change candidates and review them against independent observations.
4. Rebuild the analytical stages from a clean run and compare outputs for reproducibility.
5. Consider GeoAI only if suitable independent labels and an evaluation design are available.

The Lagos pipeline code is event-specific in several places and will be ported/configured here only after the Texas AOI, scene pair, and data availability are verified. No Lagos input or result is copied into this project.

## Setup

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

ESA SNAP is a separate desktop/GPT installation. Its version and GPT path will be recorded in the Phase 2/4 run reports.
