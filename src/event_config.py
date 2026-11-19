"""Load and validate config/event.json. Every script reads event parameters from here."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "config/event.json"

SCENE_ID = re.compile(r"S1[ABCD]_IW_GRDH_1SDV_\d{8}T\d{6}_\d{8}T\d{6}_\d{6}_[0-9A-F]{6}_[0-9A-F]{4}")
# control: an earlier same-track pre-event scene; control->pre is a no-flood pair that
# measures the false-change rate of the method.
ROLES = ("control", "pre", "event", "post")
TOP_KEYS = {"schema_version", "event", "aoi", "processing", "scene_sets", "validation"}
SET_KEYS = {"status", "priority", "rationale", *ROLES}


class ConfigError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigError(message)


def _keys(section: dict[str, Any], name: str, required: set[str]) -> None:
    _require(isinstance(section, dict), f"{name} must be an object")
    missing, extra = required - set(section), set(section) - required
    _require(not missing and not extra, f"{name}: missing {sorted(missing)} unexpected {sorted(extra)}")


def _utc(value: str, name: str) -> datetime:
    _require(isinstance(value, str) and value.endswith("Z"), f"{name} must be an ISO UTC string ending in Z")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _validate_scene_set(name: str, scenes: dict[str, Any]) -> None:
    label = f"scene_sets.{name}"
    _keys(scenes, label, SET_KEYS)
    _require(scenes["status"] in ("not_selected", "selected", "frozen"), f"{label}.status invalid")
    _require(scenes["priority"] in ("primary", "secondary"), f"{label}.priority must be primary or secondary")
    _require(isinstance(scenes["rationale"], str), f"{label}.rationale must be a string")
    for role in ROLES:
        value = scenes[role]
        _require(value is None or (isinstance(value, str) and SCENE_ID.fullmatch(value)),
                 f"{label}.{role} must be null or a full Sentinel-1 IW GRDH 1SDV product ID")
    if scenes["status"] != "not_selected":
        _require(scenes["pre"] is not None and (scenes["event"] or scenes["post"]),
                 f"{label}: selected scenes need a pre scene and at least one event/post scene")
        dates = [scene_start(scenes[r]) for r in ROLES if scenes[r]]
        _require(dates == sorted(dates) and len(set(dates)) == len(dates),
                 f"{label}: scenes must be in time order control < pre < event < post")
        tracks = {absolute_to_relative_orbit(scenes[r]) for r in ROLES if scenes[r]}
        _require(len(tracks) == 1, f"{label}: all scenes must share one relative orbit")


def validate(config: dict[str, Any]) -> dict[str, Any]:
    _keys(config, "config", TOP_KEYS)
    _require(config["schema_version"] == 3, "Unsupported schema_version (expected 3)")

    event = config["event"]
    _keys(event, "event", {"id", "name", "event_date_local", "timezone"})
    _require(re.fullmatch(r"[A-Z0-9_]+", event["id"] or "") is not None, "event.id must be UPPER_SNAKE")
    datetime.strptime(event["event_date_local"], "%Y-%m-%d")
    ZoneInfo(event["timezone"])

    aoi = config["aoi"]
    _keys(aoi, "aoi", {"status", "description", "county_geoids", "buffer_m", "path"})
    _require(aoi["status"] in ("provisional", "final"), "aoi.status must be provisional or final")
    _require(isinstance(aoi["county_geoids"], list) and aoi["county_geoids"]
             and all(re.fullmatch(r"\d{5}", g) for g in aoi["county_geoids"]), "aoi.county_geoids must be 5-digit FIPS")
    _require(type(aoi["buffer_m"]) in (int, float) and 0 <= aoi["buffer_m"] <= 50000, "aoi.buffer_m must be 0-50000")
    _require(aoi["path"].startswith("data/interim/") and aoi["path"].endswith(".geojson"), "aoi.path must be a data/interim GeoJSON")

    proc = config["processing"]
    _keys(proc, "processing", {"sensor", "polarizations", "pixel_spacing_m", "target_crs", "dem",
                               "search_start_utc", "search_end_utc"})
    _require(proc["polarizations"] == ["VH", "VV"], "Only dual-pol VH/VV is supported")
    _require(type(proc["pixel_spacing_m"]) in (int, float) and proc["pixel_spacing_m"] > 0, "pixel_spacing_m must be > 0")
    match = re.fullmatch(r"EPSG:326(\d\d)", proc["target_crs"])
    _require(match is not None and 1 <= int(match.group(1)) <= 60, "target_crs must be a northern UTM WGS84 EPSG code")
    _require(_utc(proc["search_start_utc"], "search_start_utc") < _utc(proc["search_end_utc"], "search_end_utc"),
             "search window is empty")

    sets = config["scene_sets"]
    _require(isinstance(sets, dict) and sets, "scene_sets must be a non-empty object")
    for name, scenes in sets.items():
        _require(re.fullmatch(r"[a-z0-9_]+", name) is not None, f"scene set name {name!r} must be lower_snake")
        _validate_scene_set(name, scenes)
    _require(sum(s["priority"] == "primary" for s in sets.values()) == 1, "exactly one scene set must be primary")

    _keys(config["validation"], "validation", {"status", "candidate_products_are_exploratory"})
    return config


def scene_start(product_id: str) -> datetime:
    return datetime.strptime(product_id.split("_")[4], "%Y%m%dT%H%M%S")


def absolute_to_relative_orbit(product_id: str) -> int:
    """Relative orbit (track) from the product ID's absolute orbit, per ESA's S1A/S1B formulas."""
    platform, absolute = product_id[:3], int(product_id.split("_")[6])
    offsets = {"S1A": 73, "S1B": 27}
    if platform not in offsets:
        raise ConfigError(f"No verified relative-orbit formula for {platform}; add one before selecting it")
    return (absolute - offsets[platform]) % 175 + 1


def primary_set(config: dict[str, Any]) -> str:
    return next(name for name, s in config["scene_sets"].items() if s["priority"] == "primary")


def selected_scenes(config: dict[str, Any], scene_set: str | None = None) -> dict[str, str]:
    """Return {role: product_id} for one scene set (default: the primary); refuse if none selected."""
    name = scene_set or primary_set(config)
    if name not in config["scene_sets"]:
        raise ConfigError(f"Unknown scene set {name!r}; configured: {sorted(config['scene_sets'])}")
    scenes = config["scene_sets"][name]
    if scenes["status"] == "not_selected":
        raise ConfigError(f"Scene set {name!r} has no scenes selected; finish the Phase 1 inventory first")
    return {role: scenes[role] for role in ROLES if scenes[role]}


def utm_epsg(config: dict[str, Any]) -> int:
    return int(config["processing"]["target_crs"].split(":")[1])


def load_config(path: Path = DEFAULT) -> dict[str, Any]:
    return validate(json.loads(Path(path).read_text(encoding="utf-8")))
