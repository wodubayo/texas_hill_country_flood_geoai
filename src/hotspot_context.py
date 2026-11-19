"""Where do the exploratory VH-darkening hotspots fall? Hydrography and land-cover context.

Downloads (once, registered) USGS NHD large-scale flowlines and waterbodies and NLCD 2021 land
cover for the AOI, places them on the primary run's grid, and compares four pixel populations:
  area      all jointly valid pixels (reference)
  flagged   pre->post darkening clusters on the primary track
  agree     flagged clusters that the secondary track also flags (cross-track)
  baseline  no-flood control->pre darkening at the same drop (false-change reference)
by distance to the Guadalupe main stem, to any named stream, to any NHD flowline, by NHD
waterbody overlap, and by NLCD class. Enrichment = share of population / share of area.
Exploratory context only; not validation.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.warp import Resampling, reproject
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent))
from acquire_phase1 import fetch  # noqa: E402
from compare_track_hotspots import compute  # noqa: E402
from provenance import ROOT, save_json, utc_now  # noqa: E402

NHD_STAGED = "https://prd-tnm.s3.amazonaws.com/StagedProducts/Hydrography/NHD/HU4/GPKG"
NHD_HU4 = ("1209", "1210", "1211")  # Lower Colorado-San Bernard, Central Texas Coastal, Nueces-SW Texas Coastal
NLCD_WCS = "https://www.mrlc.gov/geoserver/mrlc_download/wcs"
NLCD_COVERAGE = "mrlc_download__NLCD_2021_Land_Cover_L48"
RAW = ROOT / "data/raw/reference"
INTERIM = ROOT / "data/interim/reference"
MAINSTEM = {"Guadalupe River", "North Fork Guadalupe River", "South Fork Guadalupe River"}
BANDS_M = (100, 300, 1000)
NLCD_CLASSES = {
    11: "Open water", 21: "Developed, open", 22: "Developed, low", 23: "Developed, medium", 24: "Developed, high",
    31: "Barren", 41: "Deciduous forest", 42: "Evergreen forest", 43: "Mixed forest", 52: "Shrub/scrub",
    71: "Grassland/herbaceous", 81: "Pasture/hay", 82: "Cultivated crops", 90: "Woody wetlands", 95: "Herbaceous wetlands",
}


def aoi_bounds() -> list[float]:
    return json.loads((ROOT / "docs/acquisition/aoi_summary.json").read_text(encoding="utf-8"))["bounds_wgs84"]


def check_geojson(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("type") != "FeatureCollection" or "error" in data:
        raise RuntimeError(f"NHD query did not return a FeatureCollection: {str(data)[:200]}")


def check_tiff(path: Path) -> None:
    if path.read_bytes()[:4] not in (b"II*\x00", b"MM\x00*", b"II+\x00"):
        raise RuntimeError(f"NLCD WCS did not return a GeoTIFF: {path.read_bytes()[:300]!r}")


def check_zip(path: Path) -> None:
    import zipfile

    if not zipfile.is_zipfile(path):
        raise RuntimeError(f"Expected a ZIP archive: {path.read_bytes()[:200]!r}")


def fetch_nhd(layers=("NHDFlowline", "NHDWaterbody")):
    """NHD High Resolution HU4 GeoPackages (staged bulk products) clipped to the AOI bounding box.

    The NHD MapServer query endpoint was too slow (2-4 min per 1000-feature page) for this AOI.
    Returns one 2D GeoDataFrame in EPSG:4326 per requested layer, in order (default: flowlines, waterbodies).
    """
    import zipfile

    import geopandas as gpd
    import pandas as pd
    import shapely
    from shapely.geometry import box

    w, s, e, n = aoi_bounds()
    frames = {layer: [] for layer in layers}
    for hu4 in NHD_HU4:
        url = f"{NHD_STAGED}/NHD_H_{hu4}_HU4_GPKG.zip"
        zip_path = fetch(url, RAW / "nhd" / f"NHD_H_{hu4}_HU4_GPKG.zip", check=check_zip,
                         publisher="USGS National Hydrography Dataset High Resolution (HU4 staged product)",
                         license="Public domain (USGS)", hu4=hu4)
        with zipfile.ZipFile(zip_path) as archive:
            member = next(m for m in archive.namelist() if m.lower().endswith(".gpkg"))
        for layer in frames:
            gdf = gpd.read_file(f"zip://{zip_path}!{member}", layer=layer, bbox=(w, s, e, n))
            gdf.columns = [c.lower() if c != gdf.geometry.name else c for c in gdf.columns]
            keep = [c for c in ("permanent_identifier", "gnis_name", "ftype", "fcode") if c in gdf.columns]
            gdf = gdf[keep + [gdf.geometry.name]].to_crs(4326)
            gdf = gdf.set_geometry(shapely.force_2d(gdf.geometry.values))
            frames[layer].append(gdf)
            print(f"  HU4 {hu4} {layer}: {len(gdf):,}", flush=True)
    clip = box(w, s, e, n)
    out = []
    for layer, parts in frames.items():
        gdf = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=4326)
        gdf = gdf.drop_duplicates("permanent_identifier")
        out.append(gdf[gdf.intersects(clip)].reset_index(drop=True))
    return tuple(out)


def fetch_nlcd() -> Path:
    from pyproj import Transformer

    w, s, e, n = aoi_bounds()
    to_albers = Transformer.from_crs(4326, 5070, always_xy=True)
    xs, ys = zip(*(to_albers.transform(x, y) for x in (w, e) for y in (s, n)))
    pad = 1000
    x0, x1 = int((min(xs) - pad) // 30 * 30), int((max(xs) + pad) // 30 * 30 + 30)
    y0, y1 = int((min(ys) - pad) // 30 * 30), int((max(ys) + pad) // 30 * 30 + 30)
    url = (f"{NLCD_WCS}?service=WCS&version=2.0.1&request=GetCoverage&coverageid={NLCD_COVERAGE}"
           f"&subset=X({x0},{x1})&subset=Y({y0},{y1})&format=image/geotiff")
    return fetch(url, RAW / "nlcd" / "nlcd_2021_land_cover_aoi.tif", check=check_tiff,
                 publisher="MRLC / USGS", product="NLCD 2021 Land Cover (L48)", license="Public domain (USGS)",
                 crs="EPSG:5070")


def write_interim(name: str, gdf) -> Path:
    INTERIM.mkdir(parents=True, exist_ok=True)
    path = INTERIM / name
    if path.exists():
        return path  # derived deterministically from registered raw inputs (and may be open in QGIS)
    gdf.to_file(path, driver="GeoJSON")
    return path


def lines_mask(gdf, shape, transform, crs, keep=None):
    """Rasterise (all_touched) the geometries of gdf, optionally filtered by a boolean Series."""
    subset = gdf if keep is None else gdf[keep]
    subset = subset[subset.geometry.notna() & ~subset.geometry.is_empty]
    if subset.empty:
        return np.zeros(shape, dtype=bool)
    geoms = subset.to_crs(crs).geometry
    return rasterize(((g, 1) for g in geoms), out_shape=shape, transform=transform,
                     all_touched=True, dtype="uint8").astype(bool)


def distance_m(mask: np.ndarray, pixel_m: float) -> np.ndarray:
    """Distance (m, float32) from each pixel to the nearest mask pixel."""
    return ndimage.distance_transform_edt(~mask).astype("float32") * pixel_m


def distance_band(dist: np.ndarray) -> np.ndarray:
    """0..len(BANDS_M): index of the distance band."""
    return np.digitize(dist, BANDS_M).astype("uint8")


def band_labels() -> list[str]:
    edges = (0, *BANDS_M)
    return [f"{a}-{b} m" for a, b in zip(edges, edges[1:])] + [f">{BANDS_M[-1]} m"]


def share(values: np.ndarray, population: np.ndarray, categories) -> dict:
    v = values[population]
    total = max(v.size, 1)
    return {str(c): round(float(np.count_nonzero(v == c)) / total, 4) for c in categories}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--primary", required=True)
    parser.add_argument("--secondary", required=True)
    args = parser.parse_args()

    flowlines, waterbodies = fetch_nhd()
    nlcd_path = fetch_nlcd()
    write_interim("nhd_flowlines_aoi.geojson", flowlines)
    write_interim("nhd_waterbodies_aoi.geojson", waterbodies)
    print(f"NHD: {len(flowlines):,} flowlines, {len(waterbodies):,} waterbodies; NLCD: {nlcd_path.name}", flush=True)

    result = compute(args.primary, args.secondary)
    p = result["primary"]
    transform, crs, shape = p["transform"], p["crs"], p["hit"].shape
    pixel_m = transform.a

    nlcd = np.zeros(shape, dtype="uint8")
    with rasterio.open(nlcd_path) as src:
        reproject(rasterio.band(src, 1), nlcd, dst_transform=transform, dst_crs=crs, resampling=Resampling.nearest)

    any_line = lines_mask(flowlines, shape, transform, crs)
    named = lines_mask(flowlines, shape, transform, crs, keep=flowlines["gnis_name"].fillna("").str.len() > 0)
    main_stem = lines_mask(flowlines, shape, transform, crs, keep=flowlines["gnis_name"].isin(MAINSTEM))
    print(f"main-stem flowlines: {int(flowlines['gnis_name'].isin(MAINSTEM).sum())}, "
          f"named: {int((flowlines['gnis_name'].fillna('').str.len() > 0).sum())}", flush=True)
    water = lines_mask(waterbodies, shape, transform, crs)  # polygons rasterise the same way
    water_near = ndimage.binary_dilation(water, iterations=3)
    dists = {"guadalupe_mainstem": distance_m(main_stem, pixel_m), "named_stream": distance_m(named, pixel_m),
             "any_flowline": distance_m(any_line, pixel_m)}
    bands = {name: distance_band(d) for name, d in dists.items()}
    del any_line, named, main_stem
    named_utm = flowlines[flowlines["gnis_name"].fillna("").str.len() > 0].to_crs(crs)

    valid = p["valid"]
    in_cluster = np.zeros(shape, dtype=bool)
    in_agree = np.zeros(shape, dtype=bool)
    for c in result["clusters"]:
        in_cluster[c["rows"], c["cols"]] = True
        if c["cross_track_agree"]:
            in_agree[c["rows"], c["cols"]] = True
    populations = {"area": valid, "flagged": in_cluster & valid, "agree": in_agree & valid,
                   "baseline": p["baseline_dark"] & valid}
    counts = {k: int(v.sum()) for k, v in populations.items()}

    summary = {"distance_bands": {}, "waterbody_within_30m": {}, "nlcd": {}}
    labels = band_labels()
    for name, band in bands.items():
        summary["distance_bands"][name] = {
            pop: dict(zip(labels, share(band, mask, range(len(labels))).values())) for pop, mask in populations.items()}
    for pop, mask in populations.items():
        summary["waterbody_within_30m"][pop] = round(float(water_near[mask].mean()) if mask.any() else 0.0, 4)
    classes = sorted(NLCD_CLASSES)
    for pop, mask in populations.items():
        summary["nlcd"][pop] = {NLCD_CLASSES[c]: v for c, v in zip(classes, share(nlcd, mask, classes).values())}

    def enrichment(table):
        area = table["area"]
        return {pop: {k: (round(v / area[k], 2) if area[k] else None) for k, v in vals.items()}
                for pop, vals in table.items() if pop != "area"}

    enrich = {"distance_bands": {n: enrichment(t) for n, t in summary["distance_bands"].items()},
              "nlcd": enrichment(summary["nlcd"])}

    from shapely.geometry import Point

    per_cluster = []
    for c in result["clusters"]:
        r, k = c["rows"], c["cols"]
        cls, n = np.unique(nlcd[r, k], return_counts=True)
        x, y = rasterio.transform.xy(transform, r.mean(), k.mean())
        nearest_idx = named_utm.sindex.nearest(Point(x, y), return_all=False)[1][0]
        nearest = named_utm.iloc[nearest_idx]
        near_main = bool(dists["guadalupe_mainstem"][r, k].min() <= 300)
        wet = bool(water_near[r, k].any()) or int(cls[n.argmax()]) == 11
        per_cluster.append({
            "centroid_utm14n": [round(x), round(y)], "area_ha": round(r.size * 0.01, 2),
            "cross_track_agree": c["cross_track_agree"],
            "dist_guadalupe_m": int(round(float(dists["guadalupe_mainstem"][r, k].min()))),
            "dist_named_stream_m": int(round(float(dists["named_stream"][r, k].min()))),
            "nearest_named_stream": nearest["gnis_name"],
            "dist_any_flowline_m": int(round(float(dists["any_flowline"][r, k].min()))),
            "mainstem_band": labels[int(bands["guadalupe_mainstem"][r, k].min())],
            "named_stream_band": labels[int(bands["named_stream"][r, k].min())],
            "any_flowline_band": labels[int(bands["any_flowline"][r, k].min())],
            "waterbody_within_30m": bool(water_near[r, k].any()),
            "dominant_nlcd": NLCD_CLASSES.get(int(cls[n.argmax()]), str(int(cls[n.argmax()]))),
            "context_group": ("corridor, water" if near_main and wet else "corridor, land" if near_main
                              else "off corridor, water" if wet else "off corridor, land"),
            "_box": (int(r.min()), int(r.max()), int(k.min()), int(k.max())),
        })
    del dists

    def tally(rows, key):
        out = {}
        for row in rows:
            out[row[key]] = out.get(row[key], 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    agree_rows = [c for c in per_cluster if c["cross_track_agree"]]
    other_rows = [c for c in per_cluster if not c["cross_track_agree"]]
    cluster_summary = {group: {"clusters": len(rows),
                               "mainstem_band": tally(rows, "mainstem_band"),
                               "named_stream_band": tally(rows, "named_stream_band"),
                               "waterbody_within_30m": sum(r["waterbody_within_30m"] for r in rows),
                               "dominant_nlcd": tally(rows, "dominant_nlcd")}
                       for group, rows in (("agree", agree_rows), ("primary_only", other_rows))}

    boxes = [c.pop("_box") for c in per_cluster]
    save_json(ROOT / f"docs/acquisition/{args.primary}_hotspot_context.json", {
        "generated_utc": utc_now(), "primary_run": args.primary, "secondary_run": args.secondary,
        "status": "exploratory context; not validation",
        "sources": {"nhd": f"{NHD_STAGED} HU4 {list(NHD_HU4)} (NHDFlowline, NHDWaterbody)", "nlcd": NLCD_COVERAGE,
                    "note": "NLCD 2021 predates the event by ~4 years; NHD flowline positions are approximate at 10 m"},
        "mainstem_names": sorted(MAINSTEM), "pixel_counts": counts,
        "pixel_shares": summary, "enrichment_vs_area": enrich,
        "cluster_summary": cluster_summary, "clusters": per_cluster,
    })

    features = []
    from pyproj import Transformer
    to_wgs = Transformer.from_crs(crs, 4326, always_xy=True)
    for c, (r0, r1, c0, c1) in zip(per_cluster, boxes):
        ring = [list(to_wgs.transform(*rasterio.transform.xy(transform, r, k, offset="ul")))
                for r, k in ((r0, c0), (r0, c1 + 1), (r1 + 1, c1 + 1), (r1 + 1, c0))]
        props = {k: v for k, v in c.items() if k != "centroid_utm14n"}
        props["centroid_utm14n"] = f"{c['centroid_utm14n'][0]},{c['centroid_utm14n'][1]}"
        features.append({"type": "Feature", "properties": props,
                         "geometry": {"type": "Polygon", "coordinates": [ring + [ring[0]]]}})
    (ROOT / "outputs/qgis" / args.primary / "hotspots_context_boxes.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")

    print(f"\npixels: {counts}")
    for name in bands:
        print(f"\nDistance to {name}  (share of pixels; enrichment vs area in brackets)")
        print(f"  {'band':<12}" + "".join(f"{pop:>18}" for pop in populations))
        for lab in labels:
            row = "".join(
                f"{summary['distance_bands'][name][pop][lab]:>10.1%}"
                + (f" [{enrich['distance_bands'][name][pop][lab] or 0:>4.1f}x]" if pop != "area" else " " * 8)
                for pop in populations)
            print(f"  {lab:<12}{row}")
    print("\nWithin 30 m of an NHD waterbody: " + ", ".join(f"{k} {v:.1%}" for k, v in summary["waterbody_within_30m"].items()))
    print("\nNLCD 2021 (share; enrichment)")
    for cls in NLCD_CLASSES.values():
        if summary["nlcd"]["area"][cls] < 0.002:
            continue
        print(f"  {cls:<22}" + "".join(
            f"{summary['nlcd'][pop][cls]:>9.1%}" + (f" [{enrich['nlcd'][pop][cls] or 0:>4.1f}x]" if pop != "area" else " " * 8)
            for pop in populations))
    print("\nClusters:", json.dumps(cluster_summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
