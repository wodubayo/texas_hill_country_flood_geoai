"""Phase 1 chronology check: USGS stream gauges at each selected Sentinel-1 sensing time.

Downloads (once, registered in the manifest) the NWIS site list for the AOI bounding box
and instantaneous discharge (00060) / gage height (00065) for the search window, then reports
per gauge: value at each scene time, event peak and its local time, the pre-event median
baseline, and how far the post scene is from baseline. Writes
docs/acquisition/usgs_gauge_scene_check.json. NWIS IV data may be provisional; qualifiers kept.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from acquire_phase1 import fetch  # noqa: E402
from event_config import load_config, scene_start, selected_scenes  # noqa: E402
from provenance import ROOT, save_json, utc_now  # noqa: E402

NWIS = "https://waterservices.usgs.gov/nwis"
RAW = ROOT / "data/raw/reference/usgs_nwis"
PARAMS = {"00060": "discharge_cfs", "00065": "gage_height_ft"}
MATCH_TOLERANCE = timedelta(minutes=60)


def bbox(config) -> str:
    summary = json.loads((ROOT / "docs/acquisition/aoi_summary.json").read_text(encoding="utf-8"))
    w, s, e, n = summary["bounds_wgs84"]
    return f"{w:.4f},{s:.4f},{e:.4f},{n:.4f}"


def sites(config) -> dict[str, dict]:
    url = (f"{NWIS}/site/?format=rdb&bBox={bbox(config)}&parameterCd=00060,00065"
           "&siteType=ST&hasDataTypeCd=iv&siteStatus=all")
    path = fetch(url, RAW / "sites_aoi_bbox.rdb", publisher="USGS NWIS", license="Public domain (USGS)")
    rows = [line.split("\t") for line in path.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]
    header, rows = rows[0], rows[2:]  # second row holds RDB field widths
    out = {}
    for row in rows:
        rec = dict(zip(header, row))
        out[rec["site_no"]] = {"name": rec["station_nm"], "lat": float(rec["dec_lat_va"]), "lon": float(rec["dec_long_va"])}
    return out


def instantaneous(config, site_ids) -> dict:
    proc = config["processing"]
    start, end = proc["search_start_utc"][:16] + "Z", proc["search_end_utc"][:16] + "Z"
    url = (f"{NWIS}/iv/?format=json&sites={','.join(sorted(site_ids))}&parameterCd={','.join(PARAMS)}"
           f"&startDT={start}&endDT={end}&siteStatus=all")
    path = fetch(url, RAW / f"iv_{start[:10]}_{end[:10]}.json", publisher="USGS NWIS",
                 license="Public domain (USGS)", note="NWIS IV data may be provisional")
    return json.loads(path.read_text(encoding="utf-8"))


def series(payload) -> dict[tuple[str, str], list[tuple[datetime, float, list]]]:
    out = {}
    for ts in payload["value"]["timeSeries"]:
        site = ts["sourceInfo"]["siteCode"][0]["value"]
        param = ts["variable"]["variableCode"][0]["value"]
        nodata = ts["variable"]["noDataValue"]
        points = []
        for block in ts["values"]:
            for v in block["value"]:
                value = float(v["value"])
                if nodata is not None and value == nodata:
                    continue
                points.append((datetime.fromisoformat(v["dateTime"]).astimezone(timezone.utc), value, v.get("qualifiers", [])))
        if points:
            out.setdefault((site, param), []).extend(points)
    return {k: sorted(v) for k, v in out.items()}


def nearest(points, when):
    best = min(points, key=lambda p: abs(p[0] - when))
    return best if abs(best[0] - when) <= MATCH_TOLERANCE else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args()
    config = load_config()
    tz = ZoneInfo(config["event"]["timezone"])
    scenes = {f"{name}:{role}": scene_start(pid).replace(tzinfo=timezone.utc)
              for name, s in config["scene_sets"].items() if s["status"] != "not_selected"
              for role, pid in selected_scenes(config, name).items()}
    onset = datetime.fromisoformat(config["event"]["event_date_local"]).replace(tzinfo=tz).astimezone(timezone.utc)
    baseline_end = min(t for key, t in scenes.items() if key.endswith(":pre"))

    meta = sites(config)
    data = series(instantaneous(config, meta))
    results = []
    for (site, param), points in sorted(data.items()):
        pre_event = [v for t, v, _ in points if t < baseline_end]
        peak_t, peak_v, _ = max(points, key=lambda p: p[1])
        base = median(pre_event) if pre_event else None
        record = {
            "site": site, "name": meta.get(site, {}).get("name"), "parameter": PARAMS[param],
            "lon": meta.get(site, {}).get("lon"), "lat": meta.get(site, {}).get("lat"),
            "points": len(points), "first_utc": points[0][0].isoformat(), "last_utc": points[-1][0].isoformat(),
            "pre_event_median": base,
            "peak": peak_v, "peak_local": peak_t.astimezone(tz).isoformat(),
            "provisional": any("P" in q for _, _, q in points),
            "longest_gap_hours": round(max(((b[0] - a[0]).total_seconds() / 3600 for a, b in zip(points, points[1:])), default=0), 1),
            "at_scenes": {},
        }
        for role, when in scenes.items():
            hit = nearest(points, when)
            record["at_scenes"][role] = None if hit is None else {
                "value": hit[1], "time_local": hit[0].astimezone(tz).isoformat(),
                "ratio_to_pre_event_median": round(hit[1] / base, 2) if base and param == "00060" else None,
                "above_pre_event_median": round(hit[1] - base, 2) if base is not None else None,
            }
        for key, at in record["at_scenes"].items():
            if key.endswith(":post") and at and base is not None and peak_v > base:
                at["recession_fraction"] = round((peak_v - at["value"]) / (peak_v - base), 3)
        record["peak_after_onset"] = peak_t >= onset - timedelta(hours=12)
        results.append(record)

    out = ROOT / "docs/acquisition/usgs_gauge_scene_check.json"
    save_json(out, {
        "generated_utc": utc_now(), "event_id": config["event"]["id"],
        "scene_times_utc": {r: t.isoformat() for r, t in scenes.items()},
        "match_tolerance_minutes": MATCH_TOLERANCE.total_seconds() / 60,
        "definitions": {
            "pre_event_median": "median of all values before the earliest pre scene time in the search window",
            "recession_fraction": "(peak - value at post scene) / (peak - pre_event_median); 1.0 = fully back to baseline",
        },
        "gauges": results,
    })

    print(f"{len(results)} series -> {out.relative_to(ROOT)}\n")
    keys = list(scenes)
    print(f"{'site':<11}{'base':>7}{'peak':>9}  {'peak local':<12}" + "".join(f"{k:>15}" for k in keys) + "  name")
    for r in results:
        if r["parameter"] != "discharge_cfs":
            continue
        cells = "".join(f"{r['at_scenes'][k]['value']:>15.0f}" if r["at_scenes"][k] else f"{'gap':>15}" for k in keys)
        print(f"{r['site']:<11}{(r['pre_event_median'] or 0):>7.0f}{r['peak']:>9.0f}  {r['peak_local'][5:16]:<12}{cells}  {r['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
