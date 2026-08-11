from ..parameter_panel_support import *
from utils.window_coordinate_common import (
    build_window_info,
    get_available_geometry_for_widget,
    get_qt_virtual_desktop_rect,
    get_window_client_qt_global_rect,
    resolve_qt_screen,
)


def _is_native_client_geometry_usable(candidate_geometry, fallback_geometry) -> bool:
    if candidate_geometry is None or candidate_geometry.isEmpty():
        return False

    if fallback_geometry is None or fallback_geometry.isEmpty():
        return True

    try:
        candidate_width = max(1, int(candidate_geometry.width()))
        candidate_height = max(1, int(candidate_geometry.height()))
        fallback_width = max(1, int(fallback_geometry.width()))
        fallback_height = max(1, int(fallback_geometry.height()))

        # Docking uses Qt logical coordinates. If the native-derived rect is
        # noticeably larger than the Qt geometry, it is almost certainly a
        # physical-pixel rect from a packaged high-DPI runtime and must be
        # rejected.
        size_tolerance = 24
        if candidate_width > fallback_width + size_tolerance:
            return False
        if candidate_height > fallback_height + size_tolerance:
            return False

        min_width = max(120, int(round(fallback_width * 0.6)))
        min_height = max(160, int(round(fallback_height * 0.6)))
        if candidate_width < min_width or candidate_height < min_height:
            return False

        offset_tolerance = 48
        if abs(int(candidate_geometry.x()) - int(fallback_geometry.x())) > offset_tolerance:
            return False
        if abs(int(candidate_geometry.y()) - int(fallback_geometry.y())) > offset_tolerance:
            return False
    except Exception:
        return False

    return True


class ParameterPanelWindowPositionMixin:
    _PANEL_SNAP_GAP = 2

    def _get_parent_client_geometry(self):
        fallback_geometry = self.parent_window.geometry()

        try:
            parent_hwnd = int(self.parent_window.winId())
            if parent_hwnd:
                window_info = build_window_info(parent_hwnd)
                client_qt_rect = get_window_client_qt_global_rect(window_info)
                if _is_native_client_geometry_usable(client_qt_rect, fallback_geometry):
                    return client_qt_rect
        except Exception:
            pass

        return fallback_geometry

    def _sync_panel_target_screen(self, reference_geometry) -> None:
        try:
            if reference_geometry is None or reference_geometry.isEmpty():
                return

            screen = resolve_qt_screen(global_pos=reference_geometry.center())
            if screen is None:
                return

            self.winId()
            window_handle = self.windowHandle() if hasattr(self, "windowHandle") else None
            if window_handle is not None:
                window_handle.setScreen(screen)
        except Exception:
            pass

    def _ensure_panel_not_shorter_than_parent(self):
        try:
            client_height = int(self._get_parent_client_geometry().height())
            if client_height > 0 and self.height() < client_height:
                self.resize(self.width(), client_height)
        except Exception:
            pass

    def _get_panel_snap_width(self) -> int:
        width_candidates = []

        for getter_name in ("width", "minimumWidth"):
            try:
                getter = getattr(self, getter_name, None)
                if callable(getter):
                    width_candidates.append(int(getter()))
            except Exception:
                pass

        for hint_name in ("sizeHint", "minimumSizeHint"):
            try:
                hint_getter = getattr(self, hint_name, None)
                if callable(hint_getter):
                    size_hint = hint_getter()
                    if size_hint is not None:
                        width_candidates.append(int(size_hint.width()))
            except Exception:
                pass

        valid_widths = [width for width in width_candidates if width > 0]
        return max(valid_widths) if valid_widths else 440

    def _clamp_panel_vertical_geometry(self, panel_y: int, panel_height: int, available_geometry):
        safe_y = int(panel_y)
        safe_height = max(240, int(panel_height))

        try:
            if available_geometry is None or available_geometry.isEmpty():
                return safe_y, safe_height

            available_top = int(available_geometry.top())
            available_bottom_exclusive = int(available_geometry.top()) + int(available_geometry.height())
            available_height = max(1, available_bottom_exclusive - available_top)

            safe_height = min(safe_height, available_height)
            max_y = available_bottom_exclusive - safe_height
            if max_y < available_top:
                max_y = available_top
            safe_y = min(max(safe_y, available_top), max_y)
        except Exception:
            pass

        return safe_y, safe_height

    def _resolve_panel_snap_x(self, client_geometry, panel_width: int, horizontal_geometry) -> int:
        parent_x = int(client_geometry.x())
        parent_width = int(client_geometry.width())
        panel_x = parent_x + parent_width + self._PANEL_SNAP_GAP

        try:
            if horizontal_geometry is None or horizontal_geometry.isEmpty():
                return panel_x

            available_left = int(horizontal_geometry.left())
            available_right_exclusive = available_left + int(horizontal_geometry.width())
            max_panel_x = available_right_exclusive - int(panel_width)

            if max_panel_x < available_left:
                return available_left

            return min(max(panel_x, available_left), max_panel_x)
        except Exception:
            return panel_x

    def _get_panel_snap_geometry(self):
        client_geometry = self._get_parent_client_geometry()
        available_geometry = get_available_geometry_for_widget(global_pos=client_geometry.center())
        horizontal_geometry = get_qt_virtual_desktop_rect()

        panel_width = self._get_panel_snap_width()
        panel_x = self._resolve_panel_snap_x(client_geometry, panel_width, horizontal_geometry)
        panel_height = int(client_geometry.height())
        panel_y = int(client_geometry.y())

        panel_y, panel_height = self._clamp_panel_vertical_geometry(
            panel_y,
            panel_height,
            available_geometry,
        )
        return panel_x, panel_y, panel_height

    def _sync_panel_snap_geometry(self, panel_x: int, panel_y: int, panel_height: int):
        if self.x() != panel_x or self.y() != panel_y:
            self.move(panel_x, panel_y)
        if (
            self.height() != panel_height
            or self.minimumHeight() != panel_height
            or self.maximumHeight() != panel_height
        ):
            self.setFixedHeight(panel_height)

    def _position_panel(self):
        if not self.parent_window:
            return
        if not self._snap_to_parent_enabled:
            self._release_panel_height_constraint()
            self._ensure_panel_not_shorter_than_parent()
            return
        if self._is_dragging:
            logger.debug('Skip auto position while dragging panel')
            return

        panel_x, panel_y, panel_height = self._get_panel_snap_geometry()
        self._sync_panel_target_screen(self._get_parent_client_geometry())
        self._sync_panel_snap_geometry(panel_x, panel_y, panel_height)

    def _release_panel_height_constraint(self):
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
