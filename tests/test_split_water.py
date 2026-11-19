import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from split_water_hotspots import outside_components  # noqa: E402


def cluster(mask):
    return np.nonzero(mask)


def test_cluster_inside_normal_water_is_not_promoted():
    normal = np.zeros((20, 20), dtype=bool)
    normal[2:12, 2:12] = True
    c = np.zeros_like(normal)
    c[3:11, 3:11] = True
    assert outside_components(*cluster(c), normal, min_pixels=5) == []


def test_spill_onto_land_is_kept_and_small_slivers_dropped():
    normal = np.zeros((30, 30), dtype=bool)
    normal[5:15, 5:15] = True                      # a pond
    c = np.zeros_like(normal)
    c[6:14, 6:25] = True                           # darkening fills the pond and spills east 10 px
    c[16, 6] = True                                # isolated outside pixel: not 8-connected to the spill
    parts = outside_components(*cluster(c), normal, min_pixels=20)
    assert len(parts) == 1
    rows, cols = parts[0]
    assert rows.size == 8 * 10 and cols.min() == 15 and not normal[rows, cols].any()


def test_parts_are_split_by_water_and_sorted_largest_first():
    normal = np.zeros((10, 40), dtype=bool)
    normal[:, 10:14] = True                        # a channel crossing the cluster
    c = np.zeros_like(normal)
    c[2:8, 4:30] = True                            # 6 px west of channel, 16 px east
    parts = outside_components(*cluster(c), normal, min_pixels=10)
    assert [p[0].size for p in parts] == [6 * 16, 6 * 6]
