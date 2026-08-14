import logging

from utils.hwnd_utils import as_hwnd
from utils.window_finder import (
    find_all_exact_window_hwnds,
    find_window_with_parent_info,
    resolve_exact_window_match,
    sanitize_window_lookup_title,
)

logger = logging.getLogger(__name__)


class GlobalSettingsDialogWindowLookupMixin:

    def _load_bound_windows(self):
        """加载已绑定的窗口列表，句柄失效时按窗口特征重连，不删除绑定。"""
        logger.info(f"开始加载绑定窗口，配置中有 {len(self.bound_windows)} 个窗口")
        from utils.window_identity import refresh_bound_windows
        changed = refresh_bound_windows(self.bound_windows)
        logger.info(f"句柄刷新后仍保留 {len(self.bound_windows)} 个绑定窗口")
        if changed:
            self._save_bound_windows_config()
        self._refresh_bound_windows_combo()
        # 【性能优化】不在打开全局设置时预创建OCR服务，改为按需创建
        # 预创建OCR服务会导致打开全局设置时卡顿（特别是打包后的exe）
        # OCR服务会在首次使用时自动创建
        # for window_info in self.bound_windows:
        #     if window_info.get('hwnd'):
        #         self._preregister_window_ocr_service(window_info)
        # 注册窗口到句柄管理器
        self._register_windows_to_handle_manager()
    def _find_window_handle(self, window_title: str):
        """查找窗口句柄（智能处理多个相同标题的窗口）"""
        try:
            # 处理带有类型标注的窗口标题
            clean_title = sanitize_window_lookup_title(window_title)
            exact_hwnds = find_all_exact_window_hwnds(clean_title)
            bound_hwnds = {
                as_hwnd(window_info.get('hwnd'))
                for window_info in self.bound_windows or []
                if as_hwnd(window_info.get('hwnd'))
            }
            if exact_hwnds:
                found_hwnd = resolve_exact_window_match(
                    clean_title,
                    exact_hwnds,
                    preferred_hwnds=bound_hwnds,
                    prefer_unpreferred=True,
                )
                if not found_hwnd:
                    return None
            else:
                found_hwnd, _, _ = find_window_with_parent_info(clean_title)
            # 返回找到的窗口
            if found_hwnd:
                return found_hwnd
        except ImportError:
            logger.warning("无法导入窗口查找工具")
            return None
        except Exception as e:
            logger.error(f"查找窗口句柄失败: {e}")
            return None
