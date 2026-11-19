import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from export_qgis_layers import common_windows, read  # noqa: E402


def tif(path, x0, y0, width, height, fill):
    with rasterio.open(path, "w", driver="GTiff", width=width, height=height, count=1, dtype="float32",
                       crs="EPSG:32614", transform=from_origin(x0, y0, 10, 10)) as dst:
        dst.write(np.full((height, width), fill, dtype="float32"), 1)
    return path


def test_crops_to_shared_extent_on_same_lattice(tmp_path):
    paths = {"pre": tif(tmp_path / "a.tif", 1005, 2005, 10, 8, 1),
             "post": tif(tmp_path / "b.tif", 1035, 1995, 9, 8, 2)}
    windows, profile = common_windows(paths)
    assert (profile["width"], profile["height"]) == (7, 7)
    assert profile["transform"].c == 1035 and profile["transform"].f == 1995
    assert windows["pre"].col_off == 3 and windows["pre"].row_off == 1
    assert windows["post"].col_off == 0 and windows["post"].row_off == 0
    assert read(paths["post"], windows["post"]).shape == (7, 7)


def test_refuses_offset_lattice(tmp_path):
    paths = {"pre": tif(tmp_path / "a.tif", 1005, 2005, 10, 8, 1),
             "post": tif(tmp_path / "b.tif", 1008, 2005, 10, 8, 2)}
    with pytest.raises(RuntimeError, match="lattice"):
        common_windows(paths)
