import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import credentials  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_env(monkeypatch):
    for name in ("EARTHDATA_TOKEN", "EARTHDATA_USERNAME", "EARTHDATA_PASSWORD"):
        monkeypatch.delenv(name, raising=False)


def write(tmp_path, **earthdata):
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps({"earthdata": {"username": "", "password": "", "token": "", **earthdata}}))
    return path


def test_template_parses_to_no_credentials():
    assert credentials.earthdata(ROOT / "config/credentials.example.json") == {}


def test_missing_file_is_empty(tmp_path):
    assert credentials.earthdata(tmp_path / "absent.json") == {}


def test_token_wins_over_login(tmp_path):
    path = write(tmp_path, username="u", password="p", token="t")
    assert credentials.earthdata(path) == {"token": "t"}


def test_login_pair(tmp_path):
    assert credentials.earthdata(write(tmp_path, username="u", password="p")) == {"username": "u", "password": "p"}


def test_half_login_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="both username and password"):
        credentials.earthdata(write(tmp_path, username="u"))


def test_env_overrides_file(tmp_path, monkeypatch):
    monkeypatch.setenv("EARTHDATA_TOKEN", "env")
    assert credentials.earthdata(write(tmp_path, token="file")) == {"token": "env"}
