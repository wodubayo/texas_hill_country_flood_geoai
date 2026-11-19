# Phase 2: Sentinel-1 preprocessing and exploratory change mapping

This runbook is a Texas adaptation to be finalized after Phase 1 confirms the AOI, scene IDs, timing, and orbit compatibility. The Lagos implementation uses event-specific paths and must not be run unchanged here.

Planned sequence: SNAP Apply-Orbit-File, thermal-noise removal, Sigma0 calibration for VH/VV, Refined Lee filtering, then terrain correction to a documented UTM grid. Preserve precise-orbit metadata through filtering, a reproducibility fix established in the Lagos work. Record DEM source, pixel spacing, resampling, nodata, and SNAP version.

Implementation: `src/run_snap_pair.py --run-id <id>` runs `graphs/sentinel1_preprocess_intermediates.xml` (orbit, TNR, calibration, Refined Lee, checkpoints), restores precise-orbit vectors into the speckle-filtered DIMAP, then runs `graphs/sentinel1_terrain_correction_only.xml` (terrain correction to `processing.target_crs` with `alignToStandardGrid` on a 0,0-origin grid so all scenes share pixel edges; saves layover/shadow mask and local incidence angles; subsets to the AOI envelope). It refuses scenes not registered in the manifest and records SNAP version, graph hashes, config hash, and orbit-restore details in `outputs/snap_runs/<id>/run_report.json`.

### Trial `tx_trial_01` (2026-11-17): passed

SNAP 14.0.0, config and graph hashes in `outputs/snap_runs/tx_trial_01/run_report.json`. All three RO005 scenes (control 2025-06-21, pre 2025-07-03, post 2025-07-15 local) processed in ~50 min total (stage 1: 9-11 min; terrain correction: 6.5-9 min per scene). For each scene, the orbit fix restored 44 precise-orbit vectors from the matching POEORB file.

Output checks: all three products share an identical grid (EPSG:32614, 10131 x 7674 px, 10 m, origin 416665 E / 3361315 N), so pairs need no resampling. Valid Sigma0 covers 97.0% of the AOI envelope. Median backscatter: VH -17.4/-17.2/-16.6 dB, VV -11.2/-11.2/-10.6 dB (pre/control/post); the post scene being ~0.6 dB brighter fits wetter post-event soils and needs checking before any change threshold is set. Layover/shadow is negligible (705 layover + 68 shadow px, ~0.001%), but local incidence angle spans 25-76 deg (1st-99.99th percentile), so slope-dependent brightness must still be considered (terrain flattening or slope masking).

### Trial `tx_trial_02_ro107` (2026-11-17): passed, primary scene set

RO107 control 2025-06-16, pre 2025-06-28, post 2025-07-10 (local), ~48 min total; 44 precise-orbit vectors restored per scene. Because RO107 only partly covers the AOI, SNAP's AOI subset follows each scene's footprint, so the three extents differ by a few pixels (widths 6879-6885 px) while sharing the standard-grid lattice. `export_qgis_layers.py` now crops all products to their common extent after checking CRS and lattice agreement (refuses otherwise). Valid data cover 85.7% of the subset.

Scene-wide VH (50 m smoothing): pre→post median +0.19 dB (RO005: +0.76), 1.09% of pixels darker by 3 dB or more, 4.23% brighter by 3 dB or more; no-flood control→pre 2.88% darker by 3 dB or more. The smaller brightening than RO005 fits RO107 post predating the 13-15 July rain.

Cross-track check (`src/compare_track_hotspots.py`, `docs/acquisition/track_hotspot_agreement.json`): of 163 RO107 darkening clusters inside RO005 coverage, 66 (40%) lie within 30 m of an RO005 flag, against a chance area fraction of 0.65%. Agreeing clusters line the Guadalupe from near Hunt through Ingram, Kerrville and Center Point to Comfort, plus a Medina-basin group ~27 km south. Both post scenes follow the same 4 July flood, so agreement supports persistent change but cannot separate flood effects from other late-June to July change common to both tracks. Exploratory; not validated.

### Hotspot context: hydrography and land cover (2026-11-17)

`src/hotspot_context.py --primary tx_trial_02_ro107 --secondary tx_trial_01`; results in `docs/acquisition/tx_trial_02_ro107_hotspot_context.json`. Sources (registered): NHD High Resolution HU4 GeoPackages 1209/1210/1211 (19,415 flowlines, 5,887 waterbodies in the AOI box; the NHD MapServer query endpoint was too slow and was abandoned after 3 pages) and NLCD 2021 Land Cover via MRLC WCS (about 4 years before the event).

Share of pixels within 100 m of the Guadalupe main stem (incl. N/S forks; 0.5% of the area):

| Population | Share | Enrichment vs area |
|---|---|---|
| RO107 darkening clusters | 15.7% | 33x |
| Clusters also flagged on RO005 | 29.7% | 63x |
| No-flood control→pre darkening | 0.4% | 0.9x |

- The no-flood darkening shows **no** preference for the river corridor, so the corridor concentration is not something the method produces by itself.
- Cross-track agreement works as a filter: 43 of 66 agreeing clusters lie within 30 m of an NHD waterbody, against 4 of 99 primary-only clusters. Primary-only clusters are mostly shrub/scrub and evergreen forest far from the main stem, consistent with noise or non-flood change.
- **Most of the agreeing signal is on water that already existed**: 28% of agreeing pixels are NLCD open water (142x enrichment), and 45 of 66 agreeing clusters are on or next to waterbodies (20 on the corridor, 25 off-corridor ponds and reservoirs). With drought-low pre-event levels (Kerrville 7 cfs on 28 June vs 209 cfs on 10 July), this most plausibly reflects refilled or smoother water surfaces (river pools, channel impoundments, stock tanks), not new land inundation or damage.
- Agricultural land is enriched in both flagged and no-flood darkening (cultivated crops 14x vs 6x, pasture/hay 3.6x vs 4.3x), so harvest or cutting is a confounder there.
- **14 agreeing clusters (15.8 ha) are land within 300 m of the main stem**, the best candidates for persistent flood effects (scour, sediment, stripped vegetation). Nine of them group on the Kerrville→Center Point reach (UTM 14N ~491,200-493,600 E, 3,312,900-3,317,200 N), with NLCD barren, shrub, pasture/hay and woody wetland. NLCD "barren" next to the channel may be gravel bars or gravel workings, which need checking against imagery.

### Optical review of red boxes (2026-11-18 to 19, complete)

Visual comparison of Esri World Imagery (Feb 2024, pre-event) against NOAA NGS ERI aerial imagery (July 2025, post-event); results in `docs/acquisition/tx_trial_02_ro107_optical_review.json`. All 14 red boxes reviewed (9 sites): **9 boxes visible flood effects (64%)**, 1 agricultural change, 4 no visible change (one provisional):

| Site | Location | Observation | Boxes |
|---|---|---|---|
| 1 | TX 27 / Stoneleigh Rd | Entire structure gone | 104 |
| 2 | Sutherland Ln / Center Point River Rd | Fresh sediment | 103, 106 |
| 3 | Wharton Rd | Fresh sediment and retained (ponded) water | 93, 95 (one site) |
| 4 | Splitrock Rd | Cultivated, not flood (**other change**) | 91 |
| 5 | East of Comfort | No visible change (provisional: only July 21/22 imagery covers it) | 92 |
| 6 | South Fork, west of Hunt | No visible change (box straddles the channel) | 85 |
| 7 | Beside the Wharton Rd site | Significant sand deposit | 94, 96, 97, 98 |
| 8 | Comfort reach | No visible change | 107 |
| 9 | Comfort reach | No visible change | 105 |

All nine flood-effect boxes lie on the Kerrville→Center Point reach (UTM 491,200-496,900 E); three of the four no-change boxes are on or east of the Comfort reach. Land cover did not predict the verdict (NLCD "barren" boxes split 3 flood / 1 no change; one pasture/hay box was sand, another cultivation). The 64% is precision for the strictest group only; flood effects the screen missed (recall) were not assessed.

Rejected groups (qualitative scan): magenta single-track boxes are mostly away from the river with no visible change, supporting their rejection as noise. Cyan boxes around Ingram, however, show water/flooding along the stream network, so the "existing water" group is not purely refilled ponds and pools; it likely includes floodwater beyond the normal water edge and should be split rather than set aside.

Mechanisms fit the radar signal: a fresh sediment surface is smoother than the vegetation or bare ground it buried, ponded water reflects energy away like a mirror, and a destroyed building removes the bright wall-ground double-bounce. Each causes VH darkening. Ponding at site 3 six days after the peak shows that some land darkening is standing floodwater, not only deposits; the two cannot be separated from the radar signal alone. Site 4 confirms the agricultural confounder flagged in the land-cover analysis: a pasture/hay box 226 m from the river passed every filter, including cross-track agreement, because cultivation darkens both tracks alike. Sites were matched to boxes by geocoding road names (OSM Nominatim). One reviewer, not field-verified.

Before change analysis, verify scene overlap, acquisition timing, orbit direction/relative orbit, polarization, CRS, grid alignment, valid-data support, topographic layover/shadow, and permanent-water exclusions. Develop candidate changes as exploratory outputs and inspect them with hillshade, hydrography, and event imagery. Do not reuse Lagos thresholds without Texas-specific sensitivity analysis.

Phase 2 deliverables: SNAP graph and parameter record, pre/post analysis-ready rasters, alignment/coverage report, backscatter summaries, exploratory candidate raster/polygons, and reproducible QGIS styling. No confirmed flood extent is claimed at this stage.
