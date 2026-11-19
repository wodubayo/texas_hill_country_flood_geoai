import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import event_config as ec  # noqa: E402

RO005_0622 = "S1A_IW_GRDH_1SDV_20250622T004326_20250622T004351_059752_076B95_0EE8"
RO005_0704 = "S1A_IW_GRDH_1SDV_20250704T004325_20250704T004350_059927_0771B0_35D4"
RO005_0716 = "S1A_IW_GRDH_1SDV_20250716T004324_20250716T004349_060102_0777B4_7382"
RO107_0629 = "S1A_IW_GRDH_1SDV_20250629T003512_20250629T003537_059854_076F22_367F"
RO107_0711 = "S1A_IW_GRDH_1SDV_20250711T003512_20250711T003537_060029_07752C_40BE"


@pytest.fixture
def config():
    return ec.load_config()


def test_repository_config_is_valid(config):
    assert ec.primary_set(config) == "ro107"
    assert ec.selected_scenes(config)["post"] == RO107_0711
    assert ec.selected_scenes(config, "ro005")["pre"] == RO005_0704


@pytest.mark.parametrize("pid, track", [(RO005_0622, 5), (RO005_0704, 5), (RO005_0716, 5), (RO107_0629, 107), (RO107_0711, 107)])
def test_relative_orbit_matches_asf(pid, track):
    assert ec.absolute_to_relative_orbit(pid) == track


def test_rejects_mixed_tracks_within_a_set(config):
    bad = copy.deepcopy(config)
    bad["scene_sets"]["ro005"]["post"] = RO107_0711
    with pytest.raises(ec.ConfigError, match="relative orbit"):
        ec.validate(bad)


def test_rejects_out_of_order(config):
    bad = copy.deepcopy(config)
    s = bad["scene_sets"]["ro005"]
    s["pre"], s["post"] = RO005_0716, RO005_0704
    with pytest.raises(ec.ConfigError, match="time order"):
        ec.validate(bad)


def test_requires_exactly_one_primary(config):
    bad = copy.deepcopy(config)
    bad["scene_sets"]["ro005"]["priority"] = "primary"
    with pytest.raises(ec.ConfigError, match="primary"):
        ec.validate(bad)


def test_rejects_unknown_keys_and_bad_crs(config):
    bad = copy.deepcopy(config)
    bad["processing"]["threshold_db"] = -18
    with pytest.raises(ec.ConfigError):
        ec.validate(bad)
    bad = copy.deepcopy(config)
    bad["processing"]["target_crs"] = "EPSG:4326"
    with pytest.raises(ec.ConfigError, match="UTM"):
        ec.validate(bad)


def test_unknown_or_unselected_set_blocks_processing(config):
    with pytest.raises(ec.ConfigError, match="Unknown scene set"):
        ec.selected_scenes(config, "ro999")
    cfg = copy.deepcopy(config)
    cfg["scene_sets"]["ro005"].update(status="not_selected", control=None, pre=None, post=None)
    ec.validate(cfg)
    with pytest.raises(ec.ConfigError, match="no scenes selected"):
        ec.selected_scenes(cfg, "ro005")
