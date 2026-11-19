"""Immutable-input provenance helpers: atomic JSON writes, SHA-256, manifest registration."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/acquisition/manifest.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_manifest(path: Path = MANIFEST) -> dict[str, Any]:
    if path.is_file():
        manifest = json.loads(path.read_text(encoding="utf-8"))
    else:
        manifest = {"schema_version": 1, "event_id": None, "assets": {}}
    manifest.setdefault("assets", {})
    return manifest


def asset_key(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def register(path: Path, source: str, manifest_path: Path = MANIFEST, **metadata: Any) -> dict[str, Any]:
    """Record a file's hash in the manifest. An existing entry may never change silently."""
    manifest = load_manifest(manifest_path)
    key = asset_key(path)
    entry = {
        "source": source,
        "registered_utc": utc_now(),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        **metadata,
    }
    previous = manifest["assets"].get(key)
    if previous is not None:
        if previous["sha256"] != entry["sha256"] or previous["source"] != source:
            raise RuntimeError(f"Manifest already holds a different {key}; inputs are immutable")
        return previous
    manifest["assets"][key] = entry
    manifest.pop("note", None)
    save_json(manifest_path, manifest)
    return entry


def verify_registered(path: Path, manifest_path: Path = MANIFEST) -> dict[str, Any] | None:
    """Return the manifest entry if the file matches it; raise if it exists but differs."""
    entry = load_manifest(manifest_path)["assets"].get(asset_key(path))
    if entry is None:
        return None
    if not path.is_file() or entry["sha256"] != sha256(path):
        raise RuntimeError(f"{asset_key(path)} does not match its manifest hash")
    return entry
