"""Load secrets from the gitignored config/credentials.json. Never print returned values."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "config/credentials.json"
SECTIONS = {"earthdata": {"username", "password", "token"}}


def load_section(name: str, path: Path = DEFAULT) -> dict[str, str]:
    """Return the non-empty fields of one section; {} if the file is absent."""
    if name not in SECTIONS:
        raise KeyError(f"Unknown credentials section {name!r}")
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    section = data.get(name, {})
    unknown = set(section) - SECTIONS[name]
    if unknown:
        raise ValueError(f"{path.name}: unknown fields in {name}: {sorted(unknown)}")
    return {key: value.strip() for key, value in section.items() if isinstance(value, str) and value.strip()}


def earthdata(path: Path = DEFAULT) -> dict[str, str]:
    """Earthdata auth as {'token': ...} or {'username': ..., 'password': ...}, or {} if none.

    Precedence: EARTHDATA_TOKEN env, EARTHDATA_USERNAME/PASSWORD env, then the credentials file.
    """
    if os.environ.get("EARTHDATA_TOKEN"):
        return {"token": os.environ["EARTHDATA_TOKEN"]}
    if os.environ.get("EARTHDATA_USERNAME") and os.environ.get("EARTHDATA_PASSWORD"):
        return {"username": os.environ["EARTHDATA_USERNAME"], "password": os.environ["EARTHDATA_PASSWORD"]}
    section = load_section("earthdata", path)
    if section.get("token"):
        return {"token": section["token"]}
    if section.get("username") and section.get("password"):
        return {"username": section["username"], "password": section["password"]}
    if section.get("username") or section.get("password"):
        raise ValueError("config/credentials.json: Earthdata needs both username and password (or a token)")
    return {}
