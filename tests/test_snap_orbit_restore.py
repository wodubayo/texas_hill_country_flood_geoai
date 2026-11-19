import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from run_snap_pair import dataset_abstracted_metadata, named_child, restore_precise_orbit_metadata  # noqa: E402


def dimap(path: Path, orbit_file: str, times: list[str]) -> Path:
    vectors = "".join(
        f'<MDElem name="orbit_vector{i}"><MDATTR name="time">{t}</MDATTR><MDATTR name="x_pos">{i}.0</MDATTR></MDElem>'
        for i, t in enumerate(times, 1)
    )
    path.write_text(
        '<Dimap_Document><Dataset_Sources><MDElem name="metadata"><MDElem name="Abstracted_Metadata">'
        f'<MDATTR name="PRODUCT">p</MDATTR><MDATTR name="orbit_state_vector_file">{orbit_file}</MDATTR>'
        f'<MDElem name="Orbit_State_Vectors">{vectors}</MDElem><MDATTR name="after">x</MDATTR>'
        "</MDElem></MDElem></Dataset_Sources></Dimap_Document>",
        encoding="utf-8",
    )
    return path


def test_restores_precise_vectors(tmp_path):
    orbit = dimap(tmp_path / "orb.dim", "Sentinel Precise S1A_OPER_AUX_POEORB_X.EOF",
                  ["03-JUL-2025 23:00:00", "03-JUL-2025 23:00:10", "03-JUL-2025 23:00:20"])
    speckle = dimap(tmp_path / "spk.dim", "S1A_IW_GRDH_annotation", ["03-JUL-2025 23:00:00"])
    fixed, info = restore_precise_orbit_metadata(orbit, speckle)

    assert fixed.name == "spk_orbit_metadata_fixed.dim"
    assert info["orbit_vector_count"] == 3 and info["last_vector_time"] == "03-JUL-2025 23:00:20"
    meta = dataset_abstracted_metadata(ET.parse(fixed).getroot())
    assert named_child(meta, "MDATTR", "orbit_state_vector_file").text.startswith("Sentinel Precise")
    vectors = named_child(meta, "MDElem", "Orbit_State_Vectors")
    assert len(list(vectors)) == 3
    # element order preserved: vectors stay between orbit file attribute and trailing attribute
    names = [child.get("name") for child in meta]
    assert names == ["PRODUCT", "orbit_state_vector_file", "Orbit_State_Vectors", "after"]
    # original speckle checkpoint untouched
    assert len(list(named_child(dataset_abstracted_metadata(ET.parse(speckle).getroot()), "MDElem", "Orbit_State_Vectors"))) == 1


def test_refuses_non_precise_orbit(tmp_path):
    orbit = dimap(tmp_path / "orb.dim", "Sentinel Restituted X.EOF", ["t1"])
    speckle = dimap(tmp_path / "spk.dim", "annotation", ["t1"])
    with pytest.raises(ValueError, match="not marked as precise"):
        restore_precise_orbit_metadata(orbit, speckle)
