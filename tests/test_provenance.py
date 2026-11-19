import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import provenance  # noqa: E402


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(provenance, "ROOT", tmp_path)
    return tmp_path


def test_register_is_immutable(sandbox):
    manifest = sandbox / "manifest.json"
    raw = sandbox / "data/raw/a.bin"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"original")
    entry = provenance.register(raw, "https://example.test/a", manifest_path=manifest)
    assert provenance.register(raw, "https://example.test/a", manifest_path=manifest) == entry
    assert provenance.verify_registered(raw, manifest_path=manifest)["sha256"] == entry["sha256"]

    raw.write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="manifest hash"):
        provenance.verify_registered(raw, manifest_path=manifest)
    with pytest.raises(RuntimeError, match="immutable"):
        provenance.register(raw, "https://example.test/a", manifest_path=manifest)


def test_unregistered_returns_none(sandbox):
    raw = sandbox / "data/raw/b.bin"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"x")
    assert provenance.verify_registered(raw, manifest_path=sandbox / "manifest.json") is None
