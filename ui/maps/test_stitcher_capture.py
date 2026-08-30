# ui/maps/test_stitcher_capture.py
import numpy as np
from ui.maps.stitcher_capture import can_capture_minimap, crop_minimap

def test_can_capture_requires_hwnd_and_region():
    assert "窗口" in (can_capture_minimap(hwnd=None, minimap_x=0, minimap_y=0, minimap_width=10, minimap_height=10) or "")
    assert "小地图" in (can_capture_minimap(hwnd=1, minimap_x=0, minimap_y=0, minimap_width=0, minimap_height=10) or "")
    assert can_capture_minimap(hwnd=1, minimap_x=0, minimap_y=0, minimap_width=10, minimap_height=10) is None

def test_crop_minimap_returns_region():
    frame = np.zeros((40, 60, 3), dtype=np.uint8)
    frame[5:15, 10:30] = 80
    tile = crop_minimap(frame, x=10, y=5, width=20, height=10)
    assert tile is not None
    assert tile.shape == (10, 20, 3)
    assert int(tile[0, 0, 0]) == 80
    assert crop_minimap(frame, x=0, y=0, width=0, height=10) is None
