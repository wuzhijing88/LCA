# -*- coding: utf-8 -*-
"""虚拟鼠标运行态读写。"""

from __future__ import annotations

import logging
import threading
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_state_lock = threading.Lock()
_enabled = False
_coord_x: Optional[int] = None
_coord_y: Optional[int] = None


def is_virtual_mouse_enabled() -> bool:
    with _state_lock:
        return bool(_enabled)


def get_virtual_mouse_coords() -> Optional[Tuple[int, int]]:
    with _state_lock:
        if _coord_x is None or _coord_y is None:
            return None
        try:
            return int(_coord_x), int(_coord_y)
        except Exception:
            logger.debug("虚拟鼠标坐标类型无效: x=%r, y=%r", _coord_x, _coord_y)
            return None


def sync_virtual_mouse_position(
    x: int,
    y: int,
) -> None:
    with _state_lock:
        global _enabled, _coord_x, _coord_y
        _enabled = True
        _coord_x = int(x)
        _coord_y = int(y)
