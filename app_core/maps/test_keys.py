from app_core.maps.keys import DEFAULT_KEYS_4, DEFAULT_KEYS_8, key_for_step, normalize_key_map


def test_absolute_wasd_when_no_heading():
    keys = normalize_key_map("四向", None)
    assert key_for_step((10, 10), (10, 0), mode="四向", key_map=keys, heading_deg=None) == "w"
    assert key_for_step((10, 10), (20, 10), mode="四向", key_map=keys, heading_deg=None) == "d"


def test_relative_heading_turns_right():
    keys = normalize_key_map("四向", {"up": "w", "down": "s", "left": "a", "right": "d"})
    # 人朝上(0)，目标在右侧 → d
    assert key_for_step((10, 10), (20, 10), mode="四向", key_map=keys, heading_deg=0.0) == "d"
    # 人朝右(90)，目标在右侧（地图东）→ 相对前方 → w
    assert key_for_step((10, 10), (20, 10), mode="四向", key_map=keys, heading_deg=90.0) == "w"


def test_eight_way_defaults():
    keys = normalize_key_map("八向", None)
    assert keys["up_right"] == DEFAULT_KEYS_8["up_right"]
    assert set(normalize_key_map("四向", None)) == set(DEFAULT_KEYS_4)
