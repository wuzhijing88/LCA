import logging

try:
    import win32gui
    PYWIN32_AVAILABLE = True
except ImportError:
    win32gui = None
    PYWIN32_AVAILABLE = False

from utils.window_finder import (
    find_all_exact_window_hwnds,
    find_window_with_parent_info,
    resolve_exact_window_match,
    sanitize_window_lookup_title,
)

logger = logging.getLogger(__name__)


class MainWindowWindowBindingLookupMixin:

    def _get_bound_hwnds_for_title(self, title):
        """获取当前绑定列表中与标题匹配的 HWND 集合。"""
        bound_hwnds = []

        for window_info in getattr(self, 'bound_windows', []) or []:
            if window_info.get('title') != title:
                continue
            hwnd = int(window_info.get('hwnd', 0) or 0)
            if hwnd:
                bound_hwnds.append(hwnd)

        return bound_hwnds

    def _find_window_by_title(self, title):

        """查找窗口，支持顶级窗口和子窗口。"""

        if not PYWIN32_AVAILABLE or win32gui is None:
            return None

        exact_top_level_hwnds = find_all_exact_window_hwnds(title)
        hwnd = resolve_exact_window_match(
            title,
            exact_top_level_hwnds,
            preferred_hwnds=self._get_bound_hwnds_for_title(title),
            prefer_preferred=True,
        )
        if hwnd:
            return hwnd

        if exact_top_level_hwnds:
            return None

        hwnd, _, _ = find_window_with_parent_info(title)
        if hwnd:
            logger.info(f"通过公共窗口查找找到窗口: {title} (HWND: {hwnd})")
        return hwnd

    def _find_window_with_parent_info(self, title):

        """查找窗口并返回父窗口信息。"""

        if not PYWIN32_AVAILABLE or win32gui is None:
            return None, False, None

        clean_title = title
        if title:
            clean_title = sanitize_window_lookup_title(title)
        if clean_title != title:
            logger.info(f"清理窗口标题: '{title}' -> '{clean_title}'")

        hwnd, is_child, parent_hwnd = find_window_with_parent_info(
            clean_title,
            preferred_hwnds=self._get_bound_hwnds_for_title(clean_title),
            prefer_preferred=True,
        )
        if hwnd:
            logger.info(
                f"通过公共窗口查找找到窗口: {clean_title} "
                f"(HWND: {hwnd}, 是否为子窗口: {is_child})"
            )
        return hwnd, is_child, parent_hwnd
