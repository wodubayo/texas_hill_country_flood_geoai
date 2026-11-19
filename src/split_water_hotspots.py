"""Split cross-track "water" hotspots into darkening inside normal water vs floodwater beyond it.

hotspot_context.py labels a cross-track cluster "water" when it touches (within 30 m) an NHD
waterbody or is mostly NLCD open water. Optical review (2026-11-19, around Ingram) showed that some
of these are water spread onto land along streams, not only refilled ponds and pools. This script
builds a "normal water" mask and keeps the part of each water-group cluster that lies outside it:

  normal water = NHD waterbodies (lake/pond, reservoir) + NHD areas (stream/river, canal, rapids)
                 + NLCD 2021 open water + NHD flowlines widened by FLOWLINE_PAD_PX (narrow creeks),
                 then grown by EDGE_TOL_PX for positional error.

Connected outside-water parts of at least MIN_PIXELS become "floodwater beyond normal extent"
candidates. Exploratory; not validation. Normal-water sources predate the event (NLCD 2021) and
drought-low pre-event levels mean some refill inside mapped water is expected and stays rejected.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent))
from acquire_phase1 import LANDMARKS  # noqa: E402
from compare_track_hotspots import compute  # noqa: E402
from hotspot_context import (MAINSTEM, NLCD_CLASSES, distance_m, fetch_nhd, fetch_nlcd,  # noqa: E402
                             lines_mask, write_interim)
from provenance import ROOT, save_json, utc_now  # noqa: E402
from screen_change_hotspots import MIN_PIXELS  # noqa: E402

WATERBODY_FTYPES = {390, 436}          # LakePond, Reservoir (not SwampMarsh 466, Playa 361)
AREA_FTYPES = {460, 336, 431}          # StreamRiver, CanalDitch, Rapids (not Inundation Area 403)
FLOWLINE_PAD_PX = 1                    # flowline raster (all_touched) grown by 1 px for narrow channels
EDGE_TOL_PX = 1                        # whole normal-water mask grown by 1 px (10 m) for position error
CORRIDOR_M = 300                       # same corridor width as hotspot_context
WATERBODY_NEAR_PX = 3                  # same 30 m waterbody proximity as hotspot_context
CONNECTIVITY = np.ones((3, 3), dtype=bool)


def outside_components(rows: np.ndarray, cols: np.ndarray, normal: np.ndarray, min_pixels: int):
    """Connected parts (8-neighbour) of a cluster lying outside `normal`, keeping those >= min_pixels.

    Returns a list of (rows, cols) arrays in full-grid indices, largest first.
    """
    r0, c0 = rows.min(), cols.min()
    local = np.zeros((rows.max() - r0 + 1, cols.max() - c0 + 1), dtype=bool)
    outside = ~normal[rows, cols]
    local[rows[outside] - r0, cols[outside] - c0] = True
    labels, n = ndimage.label(local, structure=CONNECTIVITY)
    parts = []
    for i in range(1, n + 1):
        rr, cc = np.nonzero(labels == i)
        if rr.size >= min_pixels:
            parts.append((rr + r0, cc + c0))
    return sorted(parts, key=lambda p: -p[0].size)


def ftype_in(gdf, codes):
    return gdf["ftype"].astype("Int64").isin(codes) if "ftype" in gdf.columns else np.ones(len(gdf), bool)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--primary", required=True)
    parser.add_argument("--secondary", required=True)
    parser.add_argument("--flowline-pad-px", type=int, default=FLOWLINE_PAD_PX)
    parser.add_argument("--edge-tol-px", type=int, default=EDGE_TOL_PX)
    parser.add_argument("--tag", default="", help="suffix for outputs (sensitivity runs)")
    args = parser.parse_args()
    pad_px, tol_px, tag = args.flowline_pad_px, args.edge_tol_px, args.tag

    import geopandas as gpd
    import shapely
    from pyproj import Geod, Transformer
    from rasterio.features import shapes
    from shapely.geometry import Point, shape

    flowlines, waterbodies, areas = fetch_nhd(("NHDFlowline", "NHDWaterbody", "NHDArea"))
    write_interim("nhd_areas_aoi.geojson", areas[ftype_in(areas, AREA_FTYPES)])
    nlcd_path = fetch_nlcd()

    result = compute(args.primary, args.secondary)
    p = result["primary"]
    transform, crs, grid = p["transform"], p["crs"], p["hit"].shape
    pixel_m = transform.a

    nlcd = np.zeros(grid, dtype="uint8")
    with rasterio.open(nlcd_path) as src:
        reproject(rasterio.band(src, 1), nlcd, dst_transform=transform, dst_crs=crs, resampling=Resampling.nearest)

    # Same "water" definition as hotspot_context, to select the cyan group
    all_water = lines_mask(waterbodies, grid, transform, crs)
    water_near = ndimage.binary_dilation(all_water, iterations=WATERBODY_NEAR_PX)
    del all_water
    main_dist = distance_m(lines_mask(flowlines, grid, transform, crs, keep=flowlines["gnis_name"].isin(MAINSTEM)), pixel_m)

    lines = lines_mask(flowlines, grid, transform, crs)
    if pad_px:
        lines = ndimage.binary_dilation(lines, iterations=pad_px)
    normal = (lines_mask(waterbodies, grid, transform, crs, keep=ftype_in(waterbodies, WATERBODY_FTYPES))
              | lines_mask(areas, grid, transform, crs, keep=ftype_in(areas, AREA_FTYPES))
              | (nlcd == 11) | lines)
    del lines
    if tol_px:
        normal = ndimage.binary_dilation(normal, iterations=tol_px)
    mask_path = ROOT / "outputs/qgis" / args.primary / f"normal_water_mask{tag}.tif"
    with rasterio.open(mask_path, "w", driver="GTiff", width=grid[1], height=grid[0], count=1, dtype="uint8",
                       crs=crs, transform=transform, nodata=0, compress="deflate", tiled=True) as dst:
        dst.write(normal.astype("uint8"), 1)

    named_utm = flowlines[flowlines["gnis_name"].fillna("").str.len() > 0].to_crs(crs)
    to_wgs = Transformer.from_crs(crs, 4326, always_xy=True)
    geod = Geod(ellps="WGS84")

    def where(rr, cc):
        x, y = rasterio.transform.xy(transform, rr.mean(), cc.mean())
        lon, lat = to_wgs.transform(x, y)
        landmark = min(LANDMARKS, key=lambda n: geod.inv(lon, lat, *LANDMARKS[n])[2])
        stream = named_utm.iloc[named_utm.sindex.nearest(Point(x, y), return_all=False)[1][0]]["gnis_name"]
        return {"centroid_utm14n": f"{round(x)},{round(y)}", "nearest_landmark": landmark,
                "landmark_distance_km": round(geod.inv(lon, lat, *LANDMARKS[landmark])[2] / 1000, 1),
                "nearest_named_stream": stream,
                "dist_guadalupe_m": int(round(float(main_dist[rr, cc].min())))}

    def dominant(rr, cc):
        cls, n = np.unique(nlcd[rr, cc], return_counts=True)
        return NLCD_CLASSES.get(int(cls[n.argmax()]), str(int(cls[n.argmax()])))

    reviewed, features = [], []
    for c in result["clusters"]:
        if not c["cross_track_agree"]:
            continue
        r, k = c["rows"], c["cols"]
        near_main = bool(main_dist[r, k].min() <= CORRIDOR_M)
        cls, n = np.unique(nlcd[r, k], return_counts=True)
        wet = bool(water_near[r, k].any()) or int(cls[n.argmax()]) == 11
        if not wet:
            continue  # land clusters are the red boxes, reviewed separately
        group = "corridor, water" if near_main else "off corridor, water"
        parts = outside_components(r, k, normal, MIN_PIXELS)
        outside_px = int(np.count_nonzero(~normal[r, k]))
        info = where(r, k)
        reviewed.append({**info, "context_group": group, "area_ha": round(r.size * 0.01, 2),
                         "outside_normal_water_fraction": round(outside_px / r.size, 3),
                         "beyond_normal_parts": len(parts),
                         "beyond_normal_ha": round(sum(pp[0].size for pp in parts) * 0.01, 2),
                         "verdict": "floodwater beyond normal extent" if parts else "inside normal water"})
        for rr, cc in parts:
            mask = np.zeros((rr.max() - rr.min() + 1, cc.max() - cc.min() + 1), dtype="uint8")
            mask[rr - rr.min(), cc - cc.min()] = 1
            win_transform = transform * transform.translation(cc.min(), rr.min())
            geom = [shape(g) for g, v in shapes(mask, mask=mask.astype(bool), transform=win_transform) if v == 1]
            features.append({**where(rr, cc), "parent_cluster": info["centroid_utm14n"],
                             "context_group": group, "area_ha": round(rr.size * 0.01, 2),
                             "dominant_nlcd": dominant(rr, cc), "geometry": shapely.union_all(geom)})

    promoted = [c for c in reviewed if c["beyond_normal_parts"]]
    by_landmark = {}
    for f in features:
        by_landmark[f["nearest_landmark"]] = by_landmark.get(f["nearest_landmark"], 0) + 1
    save_json(ROOT / f"docs/acquisition/{args.primary}_water_split{tag}.json", {
        "generated_utc": utc_now(), "primary_run": args.primary, "secondary_run": args.secondary,
        "status": "exploratory; not validation",
        "params": {"waterbody_ftypes": sorted(WATERBODY_FTYPES), "area_ftypes": sorted(AREA_FTYPES),
                   "nlcd_open_water": 11, "flowline_pad_px": pad_px, "edge_tol_px": tol_px,
                   "min_pixels": MIN_PIXELS, "pixel_m": pixel_m},
        "motivation": "Optical review 2026-11-19: cyan boxes around Ingram show water/flooding along streams.",
        "summary": {"water_group_clusters": len(reviewed), "with_floodwater_beyond_normal": len(promoted),
                    "floodwater_parts": len(features),
                    "floodwater_ha": round(sum(f["area_ha"] for f in features), 2),
                    "parts_by_nearest_landmark": dict(sorted(by_landmark.items(), key=lambda kv: -kv[1]))},
        "clusters": reviewed,
        "floodwater_parts": [{k: v for k, v in f.items() if k != "geometry"} for f in features],
    })
    out = ROOT / "outputs/qgis" / args.primary / f"floodwater_beyond_normal{tag}.geojson"
    if features:
        gpd.GeoDataFrame(features, geometry="geometry", crs=crs).to_crs(4326).to_file(out, driver="GeoJSON")
    print(f"water-group clusters: {len(reviewed)}; with floodwater beyond normal: {len(promoted)}; "
          f"parts: {len(features)} ({sum(f['area_ha'] for f in features):.2f} ha)")
    print("parts by nearest landmark:", by_landmark)
    for f in sorted(features, key=lambda f: -f["area_ha"]):
        print(f"  {f['centroid_utm14n']:>16}  {f['area_ha']:5.2f} ha  {f['context_group']:<20} {f['dominant_nlcd']:<18} "
              f"{f['nearest_landmark']} {f['landmark_distance_km']} km, {f['nearest_named_stream']}, {f['dist_guadalupe_m']} m to Guadalupe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
