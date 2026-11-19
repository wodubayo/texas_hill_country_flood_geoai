"""Phase 1 acquisition for the configured event (run from project root).

Subcommands:
  aoi       Download Census county boundaries, build the buffered provisional AOI.
  search    Query ASF for Sentinel-1 IW GRDH scenes; write an inventory with exact
            sensing times, orbits, footprints and AOI coverage.
  download  Download the scenes selected in config/event.json, verify MD5/size
            against ASF metadata, and register SHA-256 in the manifest.
"""
from __future__ import annotations

import argparse
import os
import sys
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from event_config import load_config, selected_scenes, utm_epsg  # noqa: E402
from provenance import ROOT, md5, register, save_json, utc_now, verify_registered  # noqa: E402

META = ROOT / "docs/acquisition"
RAW = ROOT / "data/raw"
COUNTY_URL = "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_county_500k.zip"
INVENTORY = META / "sentinel1_inventory.json"
USER_AGENT = "texas-hill-country-flood-geoai/phase1"
# Approximate town-centre coordinates (lon, lat) along the Guadalupe corridor, used only
# as a coarse footprint check; they are not evidence locations.
LANDMARKS = {
    "Hunt": (-99.334, 30.070),
    "Ingram": (-99.236, 30.077),
    "Kerrville": (-99.140, 30.047),
    "Center Point": (-99.036, 29.944),
    "Comfort": (-98.905, 29.968),
}


def fetch(url: str, path: Path, check=None, **metadata: Any) -> Path:
    """Download once; afterwards only accept the file if it matches the manifest.

    check: optional callable(tmp_path) that raises if the response is not the expected content
    (e.g. a service error page), so bad responses are never registered.
    """
    if path.exists():
        if verify_registered(path) is None:
            raise RuntimeError(f"Unregistered existing file {path}; move it aside before retrying")
        print(f"Cached {path.relative_to(ROOT)}", flush=True)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    print(f"Downloading {url}", flush=True)
    with requests.get(url, stream=True, timeout=(30, 300), headers={"User-Agent": USER_AGENT}) as response:
        response.raise_for_status()
        with tmp.open("wb") as stream:
            for chunk in response.iter_content(1024 * 1024):
                stream.write(chunk)
    if tmp.stat().st_size == 0:
        raise RuntimeError(f"Empty download: {url}")
    if check is not None:
        try:
            check(tmp)
        except Exception:
            tmp.unlink()
            raise
    tmp.replace(path)
    register(path, url, **metadata)
    return path


def build_aoi(config: dict[str, Any]) -> Path:
    import geopandas as gpd

    zip_path = fetch(COUNTY_URL, RAW / "boundaries/cb_2024_us_county_500k.zip",
                     publisher="US Census Bureau", product="Cartographic Boundary Files 2024, 1:500k counties",
                     license="Public domain (US federal government work)", crs="EPSG:4269")
    with zipfile.ZipFile(zip_path) as archive:
        shp = next(name for name in archive.namelist() if name.endswith(".shp"))
    counties = gpd.read_file(f"zip://{zip_path}!{shp}")
    selected = counties[counties["GEOID"].isin(config["aoi"]["county_geoids"])]
    if len(selected) != len(config["aoi"]["county_geoids"]) or not selected.is_valid.all():
        raise RuntimeError("Expected one valid boundary per configured county GEOID")

    epsg = utm_epsg(config)
    utm = selected.to_crs(epsg)
    shape_utm = utm.union_all().buffer(config["aoi"]["buffer_m"])
    aoi = gpd.GeoDataFrame(
        {"event_id": [config["event"]["id"]], "status": [config["aoi"]["status"]],
         "county_geoids": [",".join(config["aoi"]["county_geoids"])], "buffer_m": [config["aoi"]["buffer_m"]],
         "area_km2": [shape_utm.area / 1e6]},
        geometry=[shape_utm], crs=epsg,
    ).to_crs(4326)

    out = ROOT / config["aoi"]["path"]
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()  # derived product: rebuilt deterministically from the registered county file
    aoi.to_file(out, driver="GeoJSON")
    save_json(META / "aoi_summary.json", {
        "generated_utc": utc_now(),
        "aoi_path": config["aoi"]["path"],
        "status": config["aoi"]["status"],
        "source": "data/raw/boundaries/cb_2024_us_county_500k.zip",
        "counties": selected[["GEOID", "NAME", "STATE_NAME"]].to_dict("records"),
        "buffer_m": config["aoi"]["buffer_m"],
        "area_km2": round(shape_utm.area / 1e6, 2),
        "bounds_wgs84": [round(v, 6) for v in aoi.total_bounds],
        "area_crs": f"EPSG:{epsg}",
    })
    print(f"AOI written: {out.relative_to(ROOT)} ({shape_utm.area / 1e6:,.0f} km2)", flush=True)
    return out


def load_aoi(config: dict[str, Any]):
    import geopandas as gpd

    path = ROOT / config["aoi"]["path"]
    if not path.is_file():
        raise FileNotFoundError(f"{path} missing; run `acquire_phase1.py aoi` first")
    return gpd.read_file(path).to_crs(4326).union_all()


def reproject(geometry, transformer):
    import shapely

    return shapely.transform(geometry, lambda x, y: transformer.transform(x, y), interleaved=False)


def scene_record(product, aoi_utm, to_utm, tz: ZoneInfo, landmarks: dict[str, Any]) -> dict[str, Any]:
    from shapely.geometry import shape

    props = product.properties
    footprint = shape(product.geometry)
    covered = reproject(footprint, to_utm).intersection(aoi_utm).area / aoi_utm.area
    start = datetime.fromisoformat(props["startTime"].replace("Z", "+00:00"))
    stop = datetime.fromisoformat(props["stopTime"].replace("Z", "+00:00"))
    return {
        "product_id": props["sceneName"],
        "platform": props.get("platformName") or props["sceneName"][:3],
        "sensing_start_utc": start.isoformat(),
        "sensing_stop_utc": stop.isoformat(),
        "sensing_start_local": start.astimezone(tz).isoformat(),
        "flight_direction": props.get("flightDirection"),
        "relative_orbit": props.get("pathNumber"),
        "frame": props.get("frameNumber"),
        "absolute_orbit": props.get("orbit"),
        "polarization": props.get("polarization"),
        "processing_date": props.get("processingDate"),
        "bytes": props.get("bytes"),
        "md5sum": props.get("md5sum"),
        "url": props.get("url"),
        "aoi_coverage_fraction": round(covered, 4),
        "landmarks_covered": sorted(name for name, point in landmarks.items() if footprint.contains(point)),
        "footprint_wkt": footprint.wkt,
    }


def search(config: dict[str, Any]) -> Path:
    import asf_search as asf
    from pyproj import Transformer
    from shapely.geometry import Point

    aoi = load_aoi(config)
    to_utm = Transformer.from_crs(4326, utm_epsg(config), always_xy=True)
    aoi_utm = reproject(aoi, to_utm)
    landmarks = {name: Point(lon, lat) for name, (lon, lat) in LANDMARKS.items()}
    proc = config["processing"]
    query = {
        "platform": [asf.PLATFORM.SENTINEL1],
        "processingLevel": [asf.PRODUCT_TYPE.GRD_HD],
        "beamMode": [asf.BEAMMODE.IW],
        "polarization": ["VV+VH"],
        "intersectsWith": aoi.convex_hull.wkt,
        "start": proc["search_start_utc"],
        "end": proc["search_end_utc"],
    }
    asf.constants.INTERNAL.CMR_TIMEOUT = 120  # default 30 s times out intermittently
    print(f"Searching ASF {proc['search_start_utc']} .. {proc['search_end_utc']}", flush=True)
    results = asf.geo_search(**query)
    tz = ZoneInfo(config["event"]["timezone"])
    scenes = sorted((scene_record(p, aoi_utm, to_utm, tz, landmarks) for p in results),
                    key=lambda s: s["sensing_start_utc"])

    tracks: dict[str, list[str]] = defaultdict(list)
    for scene in scenes:
        tracks[f"{scene['flight_direction']}_RO{scene['relative_orbit']:03d}"].append(scene["product_id"])

    save_json(INVENTORY, {
        "generated_utc": utc_now(),
        "event_id": config["event"]["id"],
        "asf_search_version": asf.__version__,
        "query": {k: (v if k != "intersectsWith" else "convex hull of " + config["aoi"]["path"]) for k, v in query.items()},
        "aoi_status": config["aoi"]["status"],
        "scene_count": len(scenes),
        "tracks": dict(tracks),
        "landmarks_wgs84": LANDMARKS,
        "scenes": scenes,
        "note": "Inventory only. Selection requires same relative orbit, AOI coverage, and sensing time checked against local flood chronology.",
    })
    print(f"{len(scenes)} scenes -> {INVENTORY.relative_to(ROOT)}", flush=True)
    for scene in scenes:
        print(f"  {scene['sensing_start_local'][:16]} {scene['platform']:<4} {scene['flight_direction']:<10} "
              f"RO{scene['relative_orbit']:03d} cov={scene['aoi_coverage_fraction']:.2f} "
              f"pts={len(scene['landmarks_covered'])}/{len(LANDMARKS)} {scene['product_id']}", flush=True)
    return INVENTORY


def earthdata_session():
    import asf_search as asf

    import credentials

    session = asf.ASFSession()
    auth = credentials.earthdata()
    if "token" in auth:
        return session.auth_with_token(auth["token"])
    if auth:
        return session.auth_with_creds(auth["username"], auth["password"])
    if (Path.home() / "_netrc").is_file() or (Path.home() / ".netrc").is_file():
        return session  # requests applies netrc credentials for urs.earthdata.nasa.gov
    raise RuntimeError("No Earthdata credentials: fill config/credentials.json "
                       "(format: config/credentials.example.json), set EARTHDATA_TOKEN, or create ~/_netrc")


def download(config: dict[str, Any]) -> None:
    import json

    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    by_id = {scene["product_id"]: scene for scene in inventory["scenes"]}
    wanted = [(f"{name}:{role}", name, role, pid) for name in config["scene_sets"]
              if config["scene_sets"][name]["status"] != "not_selected"
              for role, pid in selected_scenes(config, name).items()]
    missing = [pid for *_, pid in wanted if pid not in by_id]
    if missing:
        raise RuntimeError(f"Selected scenes not in inventory (rerun search?): {missing}")
    session = None
    for label, scene_set, role, pid in wanted:
        scene = by_id[pid]
        path = RAW / "sentinel1" / f"{pid}.zip"
        if path.exists():
            if verify_registered(path) is None:
                raise RuntimeError(f"Unregistered existing file {path}; move it aside before retrying")
            print(f"[{label}] cached {path.name}", flush=True)
            continue
        session = session or earthdata_session()
        tmp = path.with_suffix(".zip.part")
        print(f"[{label}] downloading {pid} ({scene['bytes'] / 1e9:.2f} GB)", flush=True)
        with session.get(scene["url"], stream=True, timeout=(30, 600)) as response:
            response.raise_for_status()
            with tmp.open("wb") as stream:
                for chunk in response.iter_content(8 * 1024 * 1024):
                    stream.write(chunk)
        if scene["bytes"] and tmp.stat().st_size != scene["bytes"]:
            raise RuntimeError(f"Size mismatch for {pid}: {tmp.stat().st_size} != {scene['bytes']}")
        if scene["md5sum"] and md5(tmp) != scene["md5sum"]:
            raise RuntimeError(f"MD5 mismatch for {pid}")
        tmp.replace(path)
        register(path, scene["url"], scene_set=scene_set, role=role, product_id=pid, md5_verified=bool(scene["md5sum"]),
                 sensing_start_utc=scene["sensing_start_utc"], relative_orbit=scene["relative_orbit"],
                 flight_direction=scene["flight_direction"],
                 license="Copernicus Sentinel data, free and open (Copernicus data policy)")
        print(f"[{label}] registered {path.relative_to(ROOT)}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("aoi", "search", "download"))
    parser.add_argument("--config", type=Path, default=ROOT / "config/event.json")
    args = parser.parse_args()
    config = load_config(args.config)
    {"aoi": build_aoi, "search": search, "download": download}[args.command](config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
