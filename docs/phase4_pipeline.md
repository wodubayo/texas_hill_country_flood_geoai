# Phase 4: Reproducible processing pipeline

This phase will port the reproducibility approach from the Lagos project after the Texas-specific inputs and grids are fixed. Reuse code only after separating event configuration from paths, IDs, CRS, AOI, and output names. Preserve the raw-ZIP SNAP runner's precise-orbit metadata restoration and output comparison checks.

Planned pipeline: validate acquisition manifest and hashes; process SNAP scenes; align/prep data; calculate before/after backscatter and coverage; create parameter sensitivity outputs; audit candidate polygons; summarize by watershed/county; and rebuild into an isolated run directory with comparisons to reviewed outputs.

Reproducibility demonstrates that the analysis can be rerun. It does not validate flood labels or accuracy. Record each stage, software version, configuration hash, inputs, outputs, checksums, and scientific validation status.
