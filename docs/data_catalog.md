# Data catalog

This catalog records potential sources. Nothing is considered acquired or validated until product identifiers, coverage, timestamps, licenses, and checksums are entered in the acquisition manifest.

| Theme | Candidate source | Role | Known limitations / next check |
|---|---|---|---|
| SAR event/pre-event | Sentinel-1 IW GRD via ASF DAAC or Copernicus | Primary change signal | Search exact dates and full provisional AOI; select matched relative orbit where possible; record acquisition time versus local flood wave. |
| SAR comparison | NASA OPERA DSWx-S1 event service | Product comparison / candidate reference | Uses Sentinel-1 and is described as preliminary and unvalidated; not independent validation. Service lists Jun 17/19/22, Jul 1/4/11. |
| Optical water | NASA OPERA DSWx-HLS event service; Landsat/Sentinel-2 HLS | Cloud-permitting water comparison | Event service lists Jun 27/29, Jul 2 and Jul 5-12. Clouds, temporal offset, and shared algorithm assumptions limit interpretation. |
| Airborne radar | NASA UAVSAR event response products | Potential independent spatial reference | Verify flight dates, coverage, classification method, downloadable raster/vector format, and timing relative to flood recession. |
| Aerial imagery | NOAA NGS Emergency Response Imagery | Geolocation and damage / water context | Post-event survey dates vary by area; imagery documents later conditions and damage, not automatically July 4 peak inundation. **Located 2026-11-17:** viewer `storms.ngs.noaa.gov/storms/2025_eri`; service index registered at `data/raw/reference/noaa_ngs/eri_2025_services_index.json`. Flights over the AOI: Maxar 2025-07-08 (Hunt-Kerrville); NOAA RGB 07-11 (two blocks), 07-12 (Kerrville-Comfort), all between the RO107 post pass (07-10) and the second pulse (07-13); NOAA 07-19 to 07-22 after the second pulse. XYZ tiles are streamed into the QGIS project, not downloaded. Maxar layer: commercial imagery shown via NOAA, so attribute and do not redistribute. |
| Basemap imagery | Esri World Imagery | Pre-event visual reference | Capture date checked with Esri's metadata service at five corridor points: "Kerrville2024" collection, 6-8 Feb 2024 (leaf-off), 17 months before the event. |
| Precipitation | NOAA MRMS, NCEI, NASA IMERG | Event timing and forcing | Preserve temporal resolution and distinguish basin rainfall from flood footprint. |
| Hydrology | USGS NWIS streamgages and high-water marks; NOAA/NWS reports | Timing and independent event context | Gauges may fail or exceed range; point stages are not areal flood labels. |
| Elevation / hydrography | USGS 3DEP, NHDPlus HR, watershed boundaries | Terrain, drainage, AOI, permanent-water context | Record product dates, resolution, vertical datum, and licenses. |
| Land cover / built-up | NLCD, HLS, OSM | Stratification and interpretation | Do not treat current OSM or land cover as flood reference truth. |

## Manifest requirements

For each source record a stable product ID, provider, download date, source URL, event/acquisition time and timezone, spatial footprint, processing level, license/terms, file size, SHA-256, and any exclusions. Keep raw downloads immutable; put derivatives in `data/interim/` or `data/processed/`.
