# July 2025 Central Texas Hill Country flood

## Event record

- Event ID: `TX_HILL_COUNTRY_2025_07`
- Event date: July 4, 2025 (local Central Daylight Time; flooding began in the early hours)
- Initial focus: Guadalupe River headwaters, Kerr County, and the Camp Mystic / Hunt / Kerrville corridor
- Broader context: flooding affected multiple Central Texas basins and counties; the study AOI is not yet fixed.
- Objective: estimate event-related surface-water and inundation change with Sentinel-1 and compare it with available independent observations.

NASA describes catastrophic flooding beginning July 4, particularly in Kerr County, and notes response aircraft collected optical and UAVSAR imagery. NOAA's NGS collected aerial damage-assessment imagery after the event. These are valuable leads, but imagery acquisition dates must be matched to each location before they can label the July 4 satellite overpass.

## Satellite timing caution

The NASA OPERA event service lists Sentinel-1 DSWx dates of June 17, 19, 22, July 1, July 4, and July 11, 2025. It lists HLS optical dates of June 27, 29, July 2, and July 5-12. These are candidate source dates, not confirmed scene IDs or local acquisition times. Phase 1 must retrieve exact product metadata, coverage, orbit direction, and sensing time. A July 4 scene may precede, overlap, or follow local flood peaks at different locations.

Resolved 2026-11-16: the ASF granule dated 2025-07-04 over the AOI was sensed 00:43 UTC = 19:43 CDT on 3 July, before flood onset. No Sentinel-1 pass observed the event; the first full-AOI post-event pass is 15 July. See [the scene selection record](../acquisition/sentinel1_selection.md).

OPERA's event service describes its maps as preliminary and unvalidated. Its DSWx-S1 uses Sentinel-1 data, so it is useful as an algorithm/product comparison but is not an independent sensor observation for evaluating a Sentinel-1-derived map. NASA UAVSAR and date-stamped NOAA aerial imagery may provide more independent spatial evidence, subject to their exact coverage and timing.

## Primary sources

- [NASA Disasters: Texas Floods July 2025](https://science.data.nasa.gov/disasters/news-events-stories/texas-floods-july-2025)
- [NASA OPERA event DSWx map service](https://gis.earthdata.nasa.gov/portal/rest/services/DISASTERS_202507_FLOOD_TX/202507_opera_dswx_hls/ImageServer)
- [NOAA NGS: Texas Hill Country flooding aerial imagery](https://oceanservice.noaa.gov/news/jul25/ngs-texas-flooding.html)
- [NOAA repository: hydrometeorological analysis of the event](https://repository.library.noaa.gov/view/noaa/76031)
