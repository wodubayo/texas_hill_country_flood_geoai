# Phase 3: Independent validation

Phase 3 is not started. Design the reference collection before interpreting candidate maps. The July 2025 event has unusually promising leads—NASA UAVSAR products, NOAA NGS aerial imagery, USGS gauges/high-water marks, and NASA OPERA DSWx—but each has distinct timing and independence limits.

For every reference observation record source/product ID, acquisition time and timezone, geometry, location uncertainty, water/flood label, method, and relation to the Sentinel-1 overpass and flood wave. Keep later damage imagery distinct from peak inundation. Treat Sentinel-1-based OPERA DSWx-S1 as a product comparison rather than independent validation. Include confidently dry locations as well as flooded ones, preserve ambiguous/unobserved classes, and hold out evaluation samples from threshold selection.

Do not report confusion matrices, IoU, precision, or recall until spatial and temporal matching rules and a defensible sample are established. If independent labels cannot be established, report validation as incomplete and keep mapped candidates exploratory.
