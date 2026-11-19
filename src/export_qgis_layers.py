"""Export a SNAP run's terrain-corrected products as display-ready GeoTIFFs for QGIS.

Writes to outputs/qgis/<run-id>/ (derived, not committed):
  <role>_Sigma0_<pol>_dB.tif           10*log10(Sigma0), nodata = NaN
  <role>_layoverShadowMask.tif          0 none, 1 layover, 2 shadow, 3 both
  <role>_localIncidenceAngle.tif        degrees
  change_VH_<a>_to_<b>_dB.tif           dB difference b - a (negative = darker after)
  rgb_VH_<a>_<b>.tif                    R = a, G = b, B = b (VH dB, byte-scaled -25..-10)
                                        red = darker after (candidate new water/smoothing),
                                        cyan = brighter after
Exploratory visualisation only; no thresholds are applied.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
import rasterio.windows
from rasterio.windows import Window

sys.path.insert(0, str(Path(__file__).resolve().parent))
from provenance import ROOT, save_json, utc_now  # noqa: E402

PAIRS = (("control", "pre"), ("pre", "post"))
RGB_RANGE_DB = (-25.0, -10.0)


def common_windows(paths: dict[str, Path]) -> tuple[dict[str, Window], dict]:
    """Windows cropping every product to the shared extent; products must share CRS and pixel lattice.

    SNAP's AOI subset follows each scene's footprint, so partial-coverage scenes on one track can
    differ by a few pixels in extent while sharing the alignToStandardGrid lattice.
    """
    infos = {}
    for role, path in paths.items():
        with rasterio.open(path) as src:
            infos[role] = (src.crs, src.transform, src.width, src.height, src.profile)
    crs0, t0 = next(iter(infos.values()))[:2]
    for role, (crs, t, *_ ) in infos.items():
        lattice_ok = (crs == crs0 and (t.a, t.b, t.d, t.e) == (t0.a, t0.b, t0.d, t0.e)
                      and abs(((t.c - t0.c) / t0.a) % 1) < 1e-6 and abs(((t.f - t0.f) / t0.e) % 1) < 1e-6)
        if not lattice_ok:
            raise RuntimeError(f"{role} is not on the same CRS/pixel lattice as the others; resampling would be needed")
    left = max(t.c for _, t, *_ in infos.values())
    top = min(t.f for _, t, *_ in infos.values())
    right = min(t.c + w * t.a for _, t, w, *_ in infos.values())
    bottom = max(t.f + h * t.e for _, t, _, h, _ in infos.values())
    if right <= left or bottom >= top:
        raise RuntimeError("Products do not overlap")
    windows = {}
    for role, (_, t, *_ ) in infos.items():
        col, row = round((left - t.c) / t.a), round((top - t.f) / t.e)
        windows[role] = Window(col, row, round((right - left) / t0.a), round((bottom - top) / t0.e))
    first = next(iter(infos))
    profile = {**infos[first][4], "transform": rasterio.windows.transform(windows[first], infos[first][1]),
               "width": windows[first].width, "height": windows[first].height}
    return windows, profile


def read(path: Path, window: Window):
    with rasterio.open(path) as src:
        return src.read(1, window=window).astype("float32")


def to_db(linear: np.ndarray) -> np.ndarray:
    out = np.full(linear.shape, np.nan, dtype="float32")
    good = np.isfinite(linear) & (linear > 0)
    out[good] = 10.0 * np.log10(linear[good])
    return out


def write(path: Path, profile: dict, *bands: np.ndarray, dtype="float32", nodata=np.nan) -> None:
    profile = {**profile, "driver": "GTiff", "count": len(bands), "dtype": dtype, "nodata": nodata,
               "compress": "deflate", "predictor": 3 if dtype == "float32" else 2, "tiled": True,
               "blockxsize": 512, "blockysize": 512, "BIGTIFF": "IF_SAFER"}
    with rasterio.open(path, "w", **profile) as dst:
        for index, band in enumerate(bands, 1):
            dst.write(band.astype(dtype), index)
        dst.build_overviews([2, 4, 8, 16, 32], rasterio.enums.Resampling.average)


def byte_scale(db: np.ndarray) -> np.ndarray:
    lo, hi = RGB_RANGE_DB
    scaled = np.clip((db - lo) / (hi - lo), 0, 1) * 254 + 1
    return np.where(np.isfinite(db), scaled, 0).astype("uint8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    run = ROOT / "outputs/snap_runs" / args.run_id
    report = json.loads((run / "run_report.json").read_text(encoding="utf-8"))
    if report.get("status") != "passed":
        raise RuntimeError(f"Run {args.run_id} has status {report.get('status')!r}; export only passed runs")

    out = ROOT / "outputs/qgis" / args.run_id
    out.mkdir(parents=True, exist_ok=True)
    data_dirs = {role: ROOT / Path(rec["output_dim"]).with_suffix(".data") for role, rec in report["scenes"].items()}
    windows, profile = common_windows({role: d / "Sigma0_VH.img" for role, d in data_dirs.items()})
    vh_db, written = {}, []
    for role, data in data_dirs.items():
        window = windows[role]
        for pol in ("VH", "VV"):
            db = to_db(read(data / f"Sigma0_{pol}.img", window))
            if pol == "VH":
                vh_db[role] = db
            path = out / f"{role}_Sigma0_{pol}_dB.tif"
            write(path, profile, db)
            written.append(path.name)
            print(f"wrote {path.relative_to(ROOT)}", flush=True)
        mask = read(data / "layoverShadowMask.img", window)
        write(out / f"{role}_layoverShadowMask.tif", profile, mask, dtype="uint8", nodata=255)
        lia = read(data / "localIncidenceAngle.img", window)
        write(out / f"{role}_localIncidenceAngle.tif", profile, np.where(lia > 0, lia, np.nan))
        written += [f"{role}_layoverShadowMask.tif", f"{role}_localIncidenceAngle.tif"]

    for a, b in PAIRS:
        if a in vh_db and b in vh_db:
            name = f"change_VH_{a}_to_{b}_dB.tif"
            write(out / name, profile, vh_db[b] - vh_db[a])
            rgb = f"rgb_VH_{a}_{b}.tif"
            write(out / rgb, profile, byte_scale(vh_db[a]), byte_scale(vh_db[b]), byte_scale(vh_db[b]),
                  dtype="uint8", nodata=0)
            written += [name, rgb]
            print(f"wrote {name}, {rgb}", flush=True)

    save_json(out / "export_report.json", {
        "generated_utc": utc_now(), "run_id": args.run_id, "files": written,
        "common_grid": {"crs": str(profile["crs"]), "transform": list(profile["transform"])[:6],
                        "width": profile["width"], "height": profile["height"],
                        "windows": {r: [w.col_off, w.row_off, w.width, w.height] for r, w in windows.items()}},
        "rgb_range_db": RGB_RANGE_DB, "status": "exploratory visualisation; no thresholds applied",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
