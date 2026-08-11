import logging

from utils.window_finder import (
    find_all_exact_window_hwnds,
    find_window_with_parent_info,
    resolve_exact_window_match,
    sanitize_window_lookup_title,
)

logger = logging.getLogger(__name__)


class GlobalSettingsDialogWindowLookupMixin:

    def _load_bound_windows(self):

        """加载已绑定的窗口列表，验证窗口是否真实存在"""

        logger.info(f"开始加载绑定窗口，配置中有 {len(self.bound_windows)} 个窗口")

        # 首先清理失效的窗口

        logger.info("加载绑定窗口前先清理失效窗口")

        self._cleanup_invalid_windows()

        logger.info(f"清理后剩余 {len(self.bound_windows)} 个窗口")

        # 验证并过滤存在的窗口

        valid_windows = []

        for i, window_info in enumerate(self.bound_windows):

            window_title = window_info.get('title', '')

            hwnd = window_info.get('hwnd', 0)

            logger.info(f"验证窗口 {i+1}: {window_title} (配置中的HWND: {hwnd})")

            if window_title:

                # 如果原来有句柄，先验证原句柄是否仍然有效

                if hwnd and hwnd != 0:

                    try:

                        import win32gui

                        # 修复：更灵活的窗口验证，不要求标题完全匹配

                        if (win32gui.IsWindow(hwnd) and

                            win32gui.IsWindowVisible(hwnd)):

                            # 窗口存在且可见即可，不要求标题完全匹配

                            # 因为保存的标题可能包含额外信息（如HWND）

                            # 检查是否已经有相同句柄的窗口

                            duplicate_found = False

                            for existing_window in valid_windows:

                                existing_hwnd = existing_window.get('hwnd', 0)

                                if existing_hwnd == hwnd:

                                    logger.warning(f"发现重复句柄 {hwnd}，跳过窗口: {window_title}")

                                    duplicate_found = True

                                    break

                            if not duplicate_found:

                                # 原句柄仍然有效且窗口可见，保留

                                valid_windows.append(window_info)

                                logger.info(f"原句柄仍然有效: {window_title} (HWND: {hwnd})")

                            else:

                                logger.warning(f"原句柄重复，已跳过: {window_title} (HWND: {hwnd})")

                            continue

                        else:

                            logger.warning(f"原句柄已失效或窗口不可见: {window_title} (HWND: {hwnd})")

                    except Exception as e:

                        logger.warning(f"验证窗口句柄时出错: {e}")

                # 原句柄无效或不存在，尝试重新查找

                # 临时清空bound_windows以避免智能查找时的冲突

                temp_bound_windows = self.bound_windows

                self.bound_windows = []

                current_hwnd = self._find_window_handle(window_title)

                # 恢复bound_windows

                self.bound_windows = temp_bound_windows

                logger.info(f"重新查找结果: {current_hwnd}")

                if current_hwnd:

                    # 检查是否已经有相同句柄的窗口

                    duplicate_found = False

                    for existing_window in valid_windows:

                        existing_hwnd = existing_window.get('hwnd', 0)

                        if existing_hwnd == current_hwnd:

                            logger.warning(f"发现重复句柄 {current_hwnd}，跳过窗口: {window_title}")

                            duplicate_found = True

                            break

                    if not duplicate_found:

                        # 窗口存在且无重复，更新句柄

                        window_info['hwnd'] = current_hwnd

                        valid_windows.append(window_info)

                        logger.info(f"重新查找到窗口: {window_title} (HWND: {current_hwnd})")

                    else:

                        logger.warning(f"窗口句柄重复，已跳过: {window_title} (HWND: {current_hwnd})")

                else:

                    logger.warning(f"配置中的窗口不存在，已跳过: {window_title}")

            else:

                logger.warning(f"窗口信息无效，已跳过: {window_info}")

        logger.info(f"验证完成，有效窗口数量: {len(valid_windows)}")

        # 更新绑定窗口列表为验证后的列表

        self.bound_windows = valid_windows

        # 刷新界面显示

        self._refresh_bound_windows_combo()

        # 【性能优化】不在打开全局设置时预创建OCR服务，改为按需创建

        # 预创建OCR服务会导致打开全局设置时卡顿（特别是打包后的exe）

        # OCR服务会在首次使用时自动创建

        # for window_info in self.bound_windows:

        #     if window_info.get('hwnd'):

        #         self._preregister_window_ocr_service(window_info)

        # 注册窗口到句柄管理器

        self._register_windows_to_handle_manager()

    def _enum_windows_callback(self, hwnd, results_list: list):

        """Callback function for EnumWindows"""

        if win32gui.IsWindowVisible(hwnd):

            title = win32gui.GetWindowText(hwnd)

            if title:

                results_list.append(title)

        return True # Continue enumeration

    def _find_window_handle(self, window_title: str):

        """查找窗口句柄（智能处理多个相同标题的窗口）"""

        try:

            # 处理带有类型标注的窗口标题

            clean_title = sanitize_window_lookup_title(window_title)

            exact_hwnds = find_all_exact_window_hwnds(clean_title)
            bound_hwnds = {
                int(window_info.get('hwnd'))
                for window_info in self.bound_windows or []
                if window_info.get('hwnd')
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
