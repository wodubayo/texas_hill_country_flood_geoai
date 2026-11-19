"""Run the two-stage SNAP preprocessing for every scene selected in config/event.json.

Stage 1 (graphs/sentinel1_preprocess_intermediates.xml): orbit -> TNR -> Sigma0 -> Refined Lee,
writing an orbit checkpoint and a speckle-filtered checkpoint.
Between stages: copy precise-orbit state vectors from the orbit checkpoint into the
speckle-filtered DIMAP (fix carried over from the Lagos pipeline).
Stage 2 (graphs/sentinel1_terrain_correction_only.xml): terrain correction + AOI subset.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from event_config import DEFAULT as DEFAULT_CONFIG, load_config, primary_set, selected_scenes  # noqa: E402
from provenance import ROOT, save_json, sha256, utc_now, verify_registered  # noqa: E402

DEFAULT_GPT = Path(r"C:\Program Files\esa-snap\bin\gpt.exe")
INTERMEDIATE_GRAPH = ROOT / "graphs/sentinel1_preprocess_intermediates.xml"
TC_GRAPH = ROOT / "graphs/sentinel1_terrain_correction_only.xml"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def named_child(parent: ET.Element, tag: str, name: str) -> ET.Element | None:
    return next((item for item in list(parent) if local_name(item.tag) == tag and item.get("name") == name), None)


def dataset_abstracted_metadata(root: ET.Element) -> ET.Element:
    dataset_sources = next((node for node in root.iter() if local_name(node.tag) == "Dataset_Sources"), None)
    if dataset_sources is None:
        raise ValueError("DIMAP has no Dataset_Sources element")
    metadata = named_child(dataset_sources, "MDElem", "metadata")
    abstracted = named_child(metadata, "MDElem", "Abstracted_Metadata") if metadata is not None else None
    if abstracted is None:
        raise ValueError("DIMAP has no Dataset_Sources Abstracted_Metadata")
    return abstracted


def restore_precise_orbit_metadata(orbit_dim: Path, speckle_dim: Path) -> tuple[Path, dict[str, Any]]:
    """Copy Orbit_State_Vectors and orbit file name from the orbit checkpoint into the speckle DIMAP."""
    orbit_tree = ET.parse(orbit_dim)
    speckle_tree = ET.parse(speckle_dim)
    orbit_metadata = dataset_abstracted_metadata(orbit_tree.getroot())
    speckle_metadata = dataset_abstracted_metadata(speckle_tree.getroot())

    orbit_vectors = named_child(orbit_metadata, "MDElem", "Orbit_State_Vectors")
    speckle_vectors = named_child(speckle_metadata, "MDElem", "Orbit_State_Vectors")
    orbit_file = named_child(orbit_metadata, "MDATTR", "orbit_state_vector_file")
    speckle_file = named_child(speckle_metadata, "MDATTR", "orbit_state_vector_file")
    if any(node is None for node in (orbit_vectors, speckle_vectors, orbit_file, speckle_file)):
        raise ValueError("DIMAP is missing orbit provenance or orbit-vector metadata")

    vector_times = [
        next((child.text for child in vector if local_name(child.tag) == "MDATTR" and child.get("name") == "time"), None)
        for vector in list(orbit_vectors)
        if local_name(vector.tag) == "MDElem"
    ]
    vector_times = [value for value in vector_times if value]
    if not vector_times:
        raise ValueError("Orbit checkpoint contains no timestamped orbit vectors")
    if not orbit_file.text or "Sentinel Precise" not in orbit_file.text:
        raise ValueError(f"Orbit checkpoint is not marked as precise: {orbit_file.text!r}")

    index = next(i for i, child in enumerate(list(speckle_metadata))
                 if local_name(child.tag) == "MDElem" and child.get("name") == "Orbit_State_Vectors")
    speckle_metadata.remove(speckle_vectors)
    speckle_metadata.insert(index, copy.deepcopy(orbit_vectors))
    speckle_file.text = orbit_file.text

    fixed_dim = speckle_dim.with_name(f"{speckle_dim.stem}_orbit_metadata_fixed{speckle_dim.suffix}")
    speckle_tree.write(fixed_dim, encoding="UTF-8", xml_declaration=True)
    return fixed_dim, {
        "source_orbit_file": orbit_file.text.strip(),
        "orbit_vector_count": len(vector_times),
        "first_vector_time": vector_times[0],
        "last_vector_time": vector_times[-1],
        "fixed_dim": fixed_dim.name,
    }


def run_gpt(command: list[str], log_path: Path, label: str) -> float:
    print(f"[{label}] starting; log: {log_path.relative_to(ROOT)}", flush=True)
    started = time.monotonic()
    offset, last_percent = 0, None
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        while process.poll() is None:
            time.sleep(2)
            try:
                with log_path.open("r", encoding="utf-8", errors="replace") as reader:
                    reader.seek(offset)
                    chunk = reader.read()
                    offset = reader.tell()
                percentages = re.findall(r"(\d{1,3})%", chunk)
                if percentages and percentages[-1] != last_percent:
                    last_percent = percentages[-1]
                    print(f"[{label}] SNAP progress {last_percent}%", flush=True)
            except OSError:
                pass
    elapsed = time.monotonic() - started
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode, command)
    if not log_path.is_file() or log_path.stat().st_size == 0:
        raise RuntimeError(f"SNAP produced an empty log for {label}")
    print(f"[{label}] completed in {elapsed / 60:.1f} min", flush=True)
    return elapsed


def dim_complete(path: Path) -> bool:
    return path.is_file() and path.with_suffix(".data").is_dir()


def snap_version(gpt: Path) -> str | None:
    version_file = gpt.parent.parent / "VERSION.txt"
    return version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else None


def aoi_envelope_wkt(config: dict[str, Any]) -> str:
    import geopandas as gpd

    aoi = gpd.read_file(ROOT / config["aoi"]["path"]).to_crs(4326).union_all()
    return aoi.envelope.wkt  # Subset crops to the polygon's pixel bounding box anyway


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--scene-set", help="scene set from config/event.json (default: the primary set)")
    parser.add_argument("--roles", nargs="+", help="subset of configured roles to process (default: all)")
    parser.add_argument("--gpt", type=Path, default=DEFAULT_GPT)
    parser.add_argument("--resume", action="store_true", help="resume an existing run directory")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.run_id):
        parser.error("--run-id may contain only letters, digits, underscores, and hyphens")
    if not args.gpt.is_file() or not INTERMEDIATE_GRAPH.is_file() or not TC_GRAPH.is_file():
        raise FileNotFoundError("Check the SNAP GPT executable and both saved graph XML files.")

    config = load_config(args.config)
    scene_set = args.scene_set or primary_set(config)
    scenes = selected_scenes(config, scene_set)
    if args.roles:
        unknown = set(args.roles) - set(scenes)
        if unknown:
            parser.error(f"roles not selected in config: {sorted(unknown)}")
        scenes = {role: pid for role, pid in scenes.items() if role in args.roles}

    jobs = []
    for role, pid in scenes.items():
        source = ROOT / "data/raw/sentinel1" / f"{pid}.zip"
        if verify_registered(source) is None:
            raise RuntimeError(f"{source.relative_to(ROOT)} is not registered in the manifest; run acquire_phase1.py download")
        jobs.append((role, pid, source))

    proc = config["processing"]
    tc_params = {
        "mapProjection": proc["target_crs"],
        "pixelSpacing": str(float(proc["pixel_spacing_m"])),
        "demName": proc["dem"],
        "aoiWkt": aoi_envelope_wkt(config),
    }

    run = ROOT / "outputs/snap_runs" / args.run_id
    report_path = run / "run_report.json"
    if run.exists():
        if not args.resume:
            raise FileExistsError(f"Run directory already exists: {run}; choose a new --run-id or pass --resume")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("run_id") != args.run_id:
            raise ValueError("Existing run report id does not match --run-id")
        if report.get("config_sha256") != sha256(args.config) or report.get("scene_set") != scene_set:
            raise ValueError("Config or scene set changed since this run started; start a new --run-id")
        report["previous_error"] = report.pop("error", None)
        report["resumed_utc"] = utc_now()
        report["status"] = "running"
    else:
        run.mkdir(parents=True)
        report = {
            "run_id": args.run_id,
            "event_id": config["event"]["id"],
            "scene_set": scene_set,
            "started_utc": utc_now(),
            "status": "running",
            "snap_gpt": str(args.gpt),
            "snap_version": snap_version(args.gpt),
            "config_sha256": sha256(args.config),
            "graphs": {p.relative_to(ROOT).as_posix(): sha256(p) for p in (INTERMEDIATE_GRAPH, TC_GRAPH)},
            "terrain_correction_parameters": tc_params,
            "scenes": {},
        }

    def save_report() -> None:
        save_json(report_path, report)

    save_report()
    try:
        for role, pid, source in jobs:
            print(f"\n=== {role}: {pid} ===", flush=True)
            record = report["scenes"].setdefault(role, {"product_id": pid, "source_zip": source.relative_to(ROOT).as_posix(), "stages": {}})
            if record["product_id"] != pid:
                raise ValueError(f"Run report holds a different {role} scene")
            record["status"] = "running"
            save_report()
            stem = pid[:25]  # e.g. S1A_IW_GRDH_1SDV_20250704
            orbit_dim = run / f"{stem}_Orb.dim"
            spk_dim = run / f"{stem}_Orb_TNR_Cal_Spk.dim"
            if dim_complete(orbit_dim) and dim_complete(spk_dim):
                record["stages"].setdefault("intermediates", {"status": "recovered_existing_outputs"})
                print(f"[{role}] reusing Orbit and Refined Lee checkpoints", flush=True)
            else:
                command = [str(args.gpt), str(INTERMEDIATE_GRAPH), f"-Pinput={source}",
                           f"-PstageOrbit={orbit_dim}", f"-PstageSpk={spk_dim}", "-q", "4", "-c", "1G"]
                elapsed = run_gpt(command, run / f"{role}_intermediates.log", f"{role} intermediates")
                record["stages"]["intermediates"] = {"status": "passed", "minutes": round(elapsed / 60, 2), "log": f"{role}_intermediates.log"}
                if not (dim_complete(orbit_dim) and dim_complete(spk_dim)):
                    raise RuntimeError(f"Expected SNAP intermediates missing for {role}")
            save_report()

            fixed_dim, orbit_info = restore_precise_orbit_metadata(orbit_dim, spk_dim)
            record["orbit_metadata_restore"] = orbit_info
            record["stages"]["orbit_metadata_restore"] = {"status": "passed"}
            save_report()

            tc_dim = run / f"{stem}_Orb_TNR_Cal_Spk_TC_AOI.dim"
            command = [str(args.gpt), str(TC_GRAPH), f"-Pinput={fixed_dim}", f"-Poutput={tc_dim}",
                       *(f"-P{key}={value}" for key, value in tc_params.items()), "-q", "4", "-c", "1G"]
            elapsed = run_gpt(command, run / f"{role}_terrain_correction.log", f"{role} terrain correction")
            if not dim_complete(tc_dim):
                raise RuntimeError(f"Expected TC output missing: {tc_dim}")
            record["stages"]["terrain_correction"] = {"status": "passed", "minutes": round(elapsed / 60, 2), "log": f"{role}_terrain_correction.log"}
            record["output_dim"] = tc_dim.relative_to(ROOT).as_posix()
            record["status"] = "passed"
            save_report()
            print(f"=== {role}: complete ===", flush=True)

        report["status"] = "passed"
        report["finished_utc"] = utc_now()
        save_report()
        print(f"\nAll scenes finished. Run report: {report_path.relative_to(ROOT)}", flush=True)
        return 0
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["finished_utc"] = utc_now()
        save_report()
        raise


if __name__ == "__main__":
    raise SystemExit(main())
