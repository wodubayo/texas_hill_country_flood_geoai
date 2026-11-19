"""Exploratory screen: where did VH darken pre->post while staying stable control->pre?

Viewing aid for directing visual review, NOT a flood map. Parameters are review settings,
not calibrated thresholds. Writes docs/acquisition/<run-id>_vh_darkening_hotspots.json
and outputs/qgis/<run-id>/vh_darkening_hotspots.geojson.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent))
from acquire_phase1 import LANDMARKS  # noqa: E402
from provenance import ROOT, save_json, utc_now  # noqa: E402

SMOOTH_PX = 5          # 5x5 mean (50 m) on dB before differencing, to suppress speckle
DROP_DB = -3.0         # pre->post VH change at or below this
STABLE_DB = 1.5        # |control->pre| VH change at or below this
MIN_PIXELS = 50        # 0.5 ha at 10 m
TOP_N = 15


def smoothed_db(path: Path) -> np.ndarray:
    with rasterio.open(path) as src:
        db = src.read(1)
    valid = np.isfinite(db)
    filled = np.where(valid, db, 0.0)
    num = ndimage.uniform_filter(filled, SMOOTH_PX)
    den = ndimage.uniform_filter(valid.astype("float32"), SMOOTH_PX)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = num / den
    out[~valid] = np.nan
    return out


def main() -> int:
    from pyproj import Transformer, Geod

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    src = ROOT / "outputs/qgis" / args.run_id
    with rasterio.open(src / "pre_Sigma0_VH_dB.tif") as ref:
        transform, crs = ref.transform, ref.crs
    control, pre, post = (smoothed_db(src / f"{r}_Sigma0_VH_dB.tif") for r in ("control", "pre", "post"))
    with rasterio.open(src / "pre_layoverShadowMask.tif") as m:
        terrain_ok = m.read(1) == 0

    change, baseline = post - pre, pre - control
    hit = (change <= DROP_DB) & (np.abs(baseline) <= STABLE_DB) & terrain_ok
    labels, count = ndimage.label(hit, structure=np.ones((3, 3)))
    sizes = ndimage.sum(hit, labels, index=np.arange(1, count + 1))
    keep = np.flatnonzero(sizes >= MIN_PIXELS) + 1

    to_wgs = Transformer.from_crs(crs, 4326, always_xy=True)
    geod = Geod(ellps="WGS84")
    objects = ndimage.find_objects(labels)
    clusters = []
    for label in keep:
        rows, cols = np.nonzero(labels[objects[label - 1]] == label)
        rows, cols = rows + objects[label - 1][0].start, cols + objects[label - 1][1].start
        x, y = rasterio.transform.xy(transform, rows.mean(), cols.mean())
        lon, lat = to_wgs.transform(x, y)
        nearest = min(LANDMARKS, key=lambda n: geod.inv(lon, lat, *LANDMARKS[n])[2])
        dist_km = geod.inv(lon, lat, *LANDMARKS[nearest])[2] / 1000
        clusters.append({
            "pixels": int(rows.size), "area_ha": round(rows.size * 0.01, 2),
            "length_m": round(10 * max(np.ptp(rows), np.ptp(cols)) + 10),
            "median_change_db": round(float(np.median(change[rows, cols])), 2),
            "median_pre_db": round(float(np.median(pre[rows, cols])), 2),
            "median_post_db": round(float(np.median(post[rows, cols])), 2),
            "centroid_utm14n": [round(x), round(y)], "centroid_lonlat": [round(lon, 5), round(lat, 5)],
            "nearest_landmark": nearest, "landmark_distance_km": round(dist_km, 1),
            "_bbox": [int(rows.min()), int(rows.max()), int(cols.min()), int(cols.max())],
        })
    clusters.sort(key=lambda c: c["pixels"], reverse=True)
    for rank, c in enumerate(clusters, 1):
        c["rank"] = rank

    features = []
    for c in clusters[:TOP_N]:
        r0, r1, c0, c1 = c.pop("_bbox")
        corners = [rasterio.transform.xy(transform, r, cc, offset="ul") for r, cc in ((r0, c0), (r0, c1 + 1), (r1 + 1, c1 + 1), (r1 + 1, c0))]
        ring = [list(to_wgs.transform(*xy)) for xy in corners]
        features.append({"type": "Feature", "properties": {k: v for k, v in c.items() if not k.startswith("centroid")},
                         "geometry": {"type": "Polygon", "coordinates": [ring + [ring[0]]]}})
    for c in clusters[TOP_N:]:
        c.pop("_bbox")
    (src / "vh_darkening_hotspots.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")

    total = int(hit.sum())
    baseline_false = int(((baseline <= DROP_DB) & terrain_ok).sum())
    save_json(ROOT / f"docs/acquisition/{args.run_id}_vh_darkening_hotspots.json", {
        "generated_utc": utc_now(), "run_id": args.run_id,
        "status": "exploratory review aid; not a flood map; parameters are uncalibrated review settings",
        "parameters": {"smooth_px": SMOOTH_PX, "drop_db": DROP_DB, "stable_db": STABLE_DB, "min_pixels": MIN_PIXELS},
        "flagged_pixels": total, "clusters_kept": len(clusters),
        "control_to_pre_pixels_at_same_drop": baseline_false,
        "note": "control_to_pre_pixels_at_same_drop counts pixels that darkened by the same amount with no flood in between (rough false-change reference).",
        "top_clusters": clusters[:TOP_N],
    })
    print(f"flagged {total:,} px in {len(clusters)} clusters >= {MIN_PIXELS} px; "
          f"no-flood pair at same drop: {baseline_false:,} px")
    for c in clusters[:TOP_N]:
        print(f"#{c['rank']:>2} {c['area_ha']:>6.1f} ha len~{c['length_m']:>5} m  dVH {c['median_change_db']:>5.1f} dB "
              f"(pre {c['median_pre_db']:.1f} -> post {c['median_post_db']:.1f})  "
              f"lon/lat {c['centroid_lonlat'][0]:.5f},{c['centroid_lonlat'][1]:.5f}  "
              f"UTM {c['centroid_utm14n'][0]},{c['centroid_utm14n'][1]}  {c['landmark_distance_km']} km from {c['nearest_landmark']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
