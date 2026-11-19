"""Cross-track agreement of exploratory VH-darkening hotspots (primary vs secondary scene set).

Both runs are terrain-corrected onto the same 10 m standard-grid lattice, so flagged masks can be
compared directly on their overlap. A primary-track cluster "agrees" if it lies within
TOLERANCE_PX of a pixel flagged on the other track. Agreement between independent acquisitions
(different orbits and dates) is supporting evidence, not validation.
Writes docs/acquisition/track_hotspot_agreement.json and outputs/qgis/<primary>/hotspots_cross_track.geojson.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.windows import from_bounds
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent))
from acquire_phase1 import LANDMARKS  # noqa: E402
from provenance import ROOT, save_json, utc_now  # noqa: E402
from screen_change_hotspots import DROP_DB, MIN_PIXELS, SMOOTH_PX, STABLE_DB, smoothed_db  # noqa: E402

TOLERANCE_PX = 3


def flagged(run_id: str) -> dict[str, Any]:
    src = ROOT / "outputs/qgis" / run_id
    control, pre, post = (smoothed_db(src / f"{r}_Sigma0_VH_dB.tif") for r in ("control", "pre", "post"))
    with rasterio.open(src / "pre_layoverShadowMask.tif") as m:
        ok = m.read(1) == 0
    with rasterio.open(src / "pre_Sigma0_VH_dB.tif") as ref:
        transform, crs, bounds = ref.transform, ref.crs, ref.bounds
    change, base = post - pre, pre - control
    valid = np.isfinite(change) & np.isfinite(base)
    return {
        "hit": (change <= DROP_DB) & (np.abs(base) <= STABLE_DB) & ok,
        "baseline_dark": (base <= DROP_DB) & ok,  # no-flood pair darkening at the same drop
        "valid": valid, "transform": transform, "crs": crs, "bounds": bounds,
        "stats": {"median_pre_to_post_db": round(float(np.median(change[valid])), 2),
                  "pct_darker_3db_pre_to_post": round(float(np.mean(change[valid] <= -3) * 100), 2),
                  "pct_brighter_3db_pre_to_post": round(float(np.mean(change[valid] >= 3) * 100), 2),
                  "pct_darker_3db_control_to_pre": round(float(np.mean(base[valid] <= -3) * 100), 2)},
    }


def compute(primary: str, secondary: str) -> dict[str, Any]:
    """Primary-grid cluster labels plus per-cluster cross-track agreement."""
    p, s = flagged(primary), flagged(secondary)
    tp, ts = p["transform"], s["transform"]
    if p["crs"] != s["crs"] or (tp.a, tp.e) != (ts.a, ts.e) or ((tp.c - ts.c) / tp.a) % 1 or ((tp.f - ts.f) / tp.e) % 1:
        raise RuntimeError("Runs are not on the same CRS/pixel lattice")
    bp, bs = p["bounds"], s["bounds"]
    box = (max(bp.left, bs.left), max(bp.bottom, bs.bottom), min(bp.right, bs.right), min(bp.top, bs.top))
    wp = from_bounds(*box, tp).round_offsets().round_lengths()
    ws = from_bounds(*box, ts).round_offsets().round_lengths()
    rp, cp = slice(wp.row_off, wp.row_off + wp.height), slice(wp.col_off, wp.col_off + wp.width)
    rs, cs = slice(ws.row_off, ws.row_off + ws.height), slice(ws.col_off, ws.col_off + ws.width)
    other = np.zeros_like(p["hit"])
    other_valid = np.zeros_like(p["valid"])
    other[rp, cp] = s["hit"][rs, cs]
    other_valid[rp, cp] = s["valid"][rs, cs]
    near_other = ndimage.binary_dilation(other, iterations=TOLERANCE_PX)
    chance = float(near_other[p["valid"] & other_valid].mean())

    labels, count = ndimage.label(p["hit"], structure=np.ones((3, 3)))
    sizes = ndimage.sum(p["hit"], labels, index=np.arange(1, count + 1))
    clusters = []
    for label, obj in enumerate(ndimage.find_objects(labels), 1):
        if sizes[label - 1] < MIN_PIXELS:
            continue
        rows, cols = np.nonzero(labels[obj] == label)
        rows, cols = rows + obj[0].start, cols + obj[1].start
        clusters.append({"label": label, "rows": rows, "cols": cols,
                         "observed_by_secondary": bool(other_valid[rows, cols].mean() > 0.5),
                         "cross_track_agree": bool(near_other[rows, cols].any())})
    return {"primary": p, "secondary": s, "labels": labels, "clusters": clusters, "chance_area_fraction": chance}


def main() -> int:
    from pyproj import Geod, Transformer

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--primary", required=True)
    parser.add_argument("--secondary", required=True)
    args = parser.parse_args()
    result = compute(args.primary, args.secondary)
    tp, crs = result["primary"]["transform"], result["primary"]["crs"]
    to_wgs = Transformer.from_crs(crs, 4326, always_xy=True)
    geod = Geod(ellps="WGS84")

    clusters = []
    for c in result["clusters"]:
        rows, cols = c["rows"], c["cols"]
        x, y = rasterio.transform.xy(tp, rows.mean(), cols.mean())
        lon, lat = to_wgs.transform(x, y)
        nearest = min(LANDMARKS, key=lambda n: geod.inv(lon, lat, *LANDMARKS[n])[2])
        clusters.append({
            "area_ha": round(rows.size * 0.01, 2), "observed_by_secondary": c["observed_by_secondary"],
            "cross_track_agree": c["cross_track_agree"],
            "centroid_utm14n": [round(x), round(y)], "centroid_lonlat": [round(lon, 5), round(lat, 5)],
            "nearest_landmark": nearest, "landmark_distance_km": round(geod.inv(lon, lat, *LANDMARKS[nearest])[2] / 1000, 1),
            "_box": (int(rows.min()), int(rows.max()), int(cols.min()), int(cols.max())),
        })
    clusters.sort(key=lambda c: (not c["cross_track_agree"], -c["area_ha"]))

    features = []
    for c in clusters:
        r0, r1, c0, c1 = c.pop("_box")
        if not c["cross_track_agree"]:
            continue
        ring = [list(to_wgs.transform(*rasterio.transform.xy(tp, r, cc, offset="ul")))
                for r, cc in ((r0, c0), (r0, c1 + 1), (r1 + 1, c1 + 1), (r1 + 1, c0))]
        features.append({"type": "Feature", "properties": {k: v for k, v in c.items() if k != "centroid_lonlat"},
                         "geometry": {"type": "Polygon", "coordinates": [ring + [ring[0]]]}})
    (ROOT / "outputs/qgis" / args.primary / "hotspots_cross_track.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")

    observed = [c for c in clusters if c["observed_by_secondary"]]
    agreeing = [c for c in observed if c["cross_track_agree"]]
    chance = result["chance_area_fraction"]
    save_json(ROOT / "docs/acquisition/track_hotspot_agreement.json", {
        "generated_utc": utc_now(), "primary_run": args.primary, "secondary_run": args.secondary,
        "status": "exploratory; cross-track agreement is supporting evidence, not validation",
        "parameters": {"smooth_px": SMOOTH_PX, "drop_db": DROP_DB, "stable_db": STABLE_DB,
                       "min_pixels": MIN_PIXELS, "tolerance_px": TOLERANCE_PX},
        "scene_stats": {args.primary: result["primary"]["stats"], args.secondary: result["secondary"]["stats"]},
        "primary_clusters": len(clusters), "primary_clusters_observed_by_secondary": len(observed),
        "agreeing_clusters": len(agreeing),
        "chance_area_fraction": round(chance, 4),
        "chance_note": "Fraction of jointly observed area within tolerance of any secondary flag; a randomly placed point "
                       "would agree this often (clusters have extent, so their true chance rate is somewhat higher).",
        "agreeing": agreeing,
    })
    for run in (args.primary, args.secondary):
        print(run, result["primary" if run == args.primary else "secondary"]["stats"])
    print(f"\n{len(clusters)} primary clusters; {len(observed)} inside secondary coverage; {len(agreeing)} agree within "
          f"{TOLERANCE_PX * 10} m; chance area fraction {chance:.2%}")
    for c in agreeing[:20]:
        print(f"  {c['area_ha']:>5.1f} ha  UTM {c['centroid_utm14n'][0]},{c['centroid_utm14n'][1]}  "
              f"{c['landmark_distance_km']:>5.1f} km from {c['nearest_landmark']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
