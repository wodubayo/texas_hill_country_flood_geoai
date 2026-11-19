# Transfer plan: Lagos pipeline to Texas Hill Country

## What transfers

- Repository organization and phase runbooks.
- Sentinel-1 SNAP graph design and the fix preserving precise orbit metadata across Thermal Noise Removal / speckle filtering.
- Immutable inputs, SHA-256 provenance, isolated rebuilds, support/coverage checks, and explicit exploratory status.
- Candidate review and evidence registers with time, geometry, uncertainty, source dependence, and held-out evaluation separation.

## What must be redesigned

- Event date, AOI, watershed/county summaries, scene IDs, relative orbit, UTM zone, and reference-grid transform.
- Permanent-water source and treatment (the Lagos JRC layer and thresholds do not transfer automatically).
- Thresholds and minimum mapping unit, with sensitivity analysis informed by Texas land cover, terrain, river morphology, and canopy.
- Validation targets: NASA UAVSAR/OPERA and NOAA imagery have different independence, timing, and class semantics; they are not interchangeable labels.
- Code currently hardcodes Lagos event dates, file names, CRS, boundaries, outputs, and LGA summaries. Port it behind a validated event configuration before running Texas processing.

## First milestone

Complete Phase 1: define the AOI, retrieve a scene inventory with exact sensing times/orbits, check independent and same-sensor reference coverage, and freeze a provenance manifest. Then implement the first Texas-specific acquisition/preprocessing run in this repository.
