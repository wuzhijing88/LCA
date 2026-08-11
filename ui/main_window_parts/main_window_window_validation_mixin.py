import logging

from PySide6.QtWidgets import QMessageBox

try:
    import win32gui
except ImportError:
    win32gui = None

logger = logging.getLogger(__name__)


class MainWindowWindowValidationMixin:
    def _check_window_binding(self) -> bool:

        """

        检查窗口绑定是否有效，包括验证窗口句柄的有效性

        Returns:

            是否有有效的窗口绑定

        """

        import win32gui

        # 检查是否有绑定窗口

        if not hasattr(self, 'bound_windows') or not self.bound_windows:

            QMessageBox.warning(

                self,

                "未绑定窗口",

                "还没有绑定任何窗口！\n\n请先在 '全局设置' 中绑定目标窗口。"

            )

            return False

        # 检查是否有启用的窗口

        enabled_windows = [w for w in self.bound_windows if w.get('enabled', True)]

        if not enabled_windows:

            QMessageBox.warning(

                self,

                "没有启用的窗口",

                "所有窗口都已禁用！\n\n请在 '全局设置' 中至少启用一个窗口。"

            )

            return False

        # 验证窗口句柄有效性并尝试自动恢复

        valid_windows = []

        invalid_windows = []

        recovered_windows = []

        for window_info in enabled_windows:

            window_title = window_info.get('title', '')

            hwnd = window_info.get('hwnd', 0)

            # 检查句柄是否有效

            is_valid = False

            if hwnd and hwnd != 0:

                try:

                    if win32gui.IsWindow(hwnd):

                        # 窗口存在，进一步验证

                        if win32gui.IsWindowVisible(hwnd):

                            is_valid = True

                            valid_windows.append(window_title)

                            logger.debug(f"窗口句柄有效: {window_title} (HWND: {hwnd})")

                        else:

                            # 窗口存在但不可见，可能最小化，仍视为有效

                            is_valid = True

                            valid_windows.append(window_title)

                            logger.debug(f"窗口句柄有效(不可见): {window_title} (HWND: {hwnd})")

                except Exception as e:

                    logger.warning(f"验证窗口句柄异常: {window_title} - {e}")

            # 句柄无效，尝试自动恢复

            if not is_valid:

                logger.warning(f"窗口句柄无效: {window_title} (HWND: {hwnd})，尝试自动恢复...")

                new_hwnd = self._try_recover_window_handle(window_info)

                if new_hwnd:

                    window_info['hwnd'] = new_hwnd

                    recovered_windows.append(window_title)

                    valid_windows.append(window_title)

                    logger.info(f"窗口句柄已恢复: {window_title} (新HWND: {new_hwnd})")

                else:

                    invalid_windows.append(window_title)

                    logger.error(f"窗口句柄恢复失败: {window_title}")

        # 如果有恢复的窗口，保存配置

        if recovered_windows:

            try:

                self._save_config_silent()

                logger.info(f"已保存恢复的窗口句柄配置: {recovered_windows}")

            except Exception as e:

                logger.warning(f"保存恢复的窗口配置失败: {e}")

        # 检查是否有有效窗口

        if not valid_windows:

            error_msg = "所有绑定窗口的句柄都已失效！\n\n"

            error_msg += "失效的窗口:\n"

            for w in invalid_windows:

                error_msg += f"  - {w}\n"

            error_msg += "\n请检查目标窗口是否已打开，然后在 '全局设置' 中重新绑定。"

            QMessageBox.warning(self, "窗口句柄失效", error_msg)

            return False

        # 部分窗口失效，给出警告但允许继续

        if invalid_windows:

            warning_msg = f"部分窗口句柄已失效:\n\n"

            for w in invalid_windows:

                warning_msg += f"  - {w}\n"

            warning_msg += f"\n有效窗口: {len(valid_windows)} 个\n"

            warning_msg += "是否继续执行？（仅在有效窗口上执行）"

            reply = QMessageBox.question(

                self, "部分窗口失效", warning_msg,

                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,

                QMessageBox.StandardButton.Yes

            )

            if reply != QMessageBox.StandardButton.Yes:

                return False

        return True

    def _try_recover_window_handle(self, window_info: dict) -> int:

        """

        尝试恢复失效的窗口句柄

        Args:

            window_info: 窗口信息字典

        Returns:

            新的窗口句柄，恢复失败返回0

        """

        import win32gui

        window_title = window_info.get('title', '')

        window_class = window_info.get('class_name', '')

        if not window_title:

            return 0

        try:

            # 方法1: 通过标题精确查找

            new_hwnd = self._find_window_by_title(window_title)

            if new_hwnd and win32gui.IsWindow(new_hwnd):

                logger.info(f"通过标题精确匹配恢复窗口: {window_title} -> {new_hwnd}")

                return new_hwnd

            logger.warning(f"未找到可唯一确认的目标窗口，拒绝模糊恢复: {window_title}")

        except Exception as e:

            logger.error(f"恢复窗口句柄异常: {e}")

        return 0

    def _save_config_silent(self):

        """静默保存配置（不显示提示）"""

        try:

            from app_core.config_store import save_config

            if hasattr(self, 'config'):

                self._store_runtime_bound_windows_to_config()

                save_config(self.config)

        except Exception as e:

            logger.warning(f"静默保存配置失败: {e}")

    def _start_window_monitor(self):

        """启动运行时窗口监控"""

        if self._window_monitor_enabled and not self._window_monitor_timer.isActive():

            self._window_invalid_count.clear()

            self._window_monitor_timer.start(self._window_monitor_interval)

            logger.info(f"[窗口监控] 已启动，间隔 {self._window_monitor_interval // 1000} 秒")

    def _stop_window_monitor(self):

        """停止运行时窗口监控"""

        if self._window_monitor_timer.isActive():

            self._window_monitor_timer.stop()

            self._window_invalid_count.clear()

            logger.info("[窗口监控] 已停止")

    def _check_window_validity_runtime(self):

        """运行时检查窗口有效性"""

        import win32gui

        if not hasattr(self, 'bound_windows') or not self.bound_windows:

            return

        # 检查是否有任务正在运行

        is_running = False

        if hasattr(self, 'task_state_manager') and self.task_state_manager:

            is_running = self.task_state_manager.is_running()

        if not is_running:

            # 任务未运行时不需要频繁检查

            return

        enabled_windows = [w for w in self.bound_windows if w.get('enabled', True)]

        windows_recovered = False

        windows_failed = []

        for window_info in enabled_windows:

            window_title = window_info.get('title', '')

            hwnd = window_info.get('hwnd', 0)

            if not hwnd or hwnd == 0:

                continue

            try:

                is_valid = win32gui.IsWindow(hwnd)

                if is_valid:

                    # 窗口有效，重置失效计数

                    if window_title in self._window_invalid_count:

                        del self._window_invalid_count[window_title]

                else:

                    # 窗口失效，增加计数

                    self._window_invalid_count[window_title] = self._window_invalid_count.get(window_title, 0) + 1

                    count = self._window_invalid_count[window_title]

                    if count == 1:

                        # 首次失效，尝试自动恢复

                        logger.warning(f"[窗口监控] 检测到窗口失效: {window_title} (HWND: {hwnd})，尝试恢复...")

                        new_hwnd = self._try_recover_window_handle(window_info)

                        if new_hwnd:

                            window_info['hwnd'] = new_hwnd

                            windows_recovered = True

                            del self._window_invalid_count[window_title]

                            logger.info(f"[窗口监控] 窗口已自动恢复: {window_title} (新HWND: {new_hwnd})")

                        else:

                            logger.warning(f"[窗口监控] 窗口恢复失败: {window_title}")

                    elif count >= 3:

                        # 连续3次失效，标记为失败

                        windows_failed.append(window_title)

                        logger.error(f"[窗口监控] 窗口连续失效: {window_title}，请检查目标窗口")

            except Exception as e:

                logger.warning(f"[窗口监控] 检查窗口异常: {window_title} - {e}")

        # 如果有窗口恢复，保存配置

        if windows_recovered:

            try:

                self._save_config_silent()

                logger.info("[窗口监控] 已保存恢复的窗口配置")

            except Exception as e:

                logger.warning(f"[窗口监控] 保存配置失败: {e}")

        # 如果有窗口持续失效，显示警告

        if windows_failed and len(windows_failed) == len(enabled_windows):

            # 所有窗口都失效，停止任务

            logger.critical(f"[窗口监控] 所有绑定窗口都已失效: {windows_failed}")

            self._handle_all_windows_lost()

    def _readjust_all_bound_windows(self):

        """重新调整所有绑定窗口"""

        try:

            logger.info("开始重新调整所有绑定窗口...")

            # 获取所有绑定的窗口

            bound_windows = []

            if hasattr(self, 'window_selector') and self.window_selector:

                bound_windows = self.window_selector.get_bound_windows()

            if not bound_windows:

                logger.info("没有绑定的窗口需要调整")

                self._update_step_details("没有绑定的窗口需要调整")

                return

            success_count = 0

            total_count = len(bound_windows)

            from utils.universal_window_manager import get_universal_window_manager

            window_manager = get_universal_window_manager()

            for window_info in bound_windows:

                try:

                    hwnd = window_info.get('hwnd')

                    title = window_info.get('title', '未知窗口')

                    if hwnd:

                        # 强制刷新窗口DPI信息

                        if hasattr(self, 'unified_dpi_handler'):

                            self.unified_dpi_handler.force_refresh_dpi(hwnd)

                        # 获取目标分辨率（从配置或默认0x0禁用）

                        target_width = self.custom_width if hasattr(self, 'custom_width') else 0

                        target_height = self.custom_height if hasattr(self, 'custom_height') else 0

                        # 只有配置了有效分辨率才调整

                        if target_width <= 0 or target_height <= 0:

                            logger.info(f"未配置自定义分辨率，跳过窗口调整: {title}")

                            continue

                        result = window_manager.adjust_single_window(

                            hwnd, target_width, target_height, async_mode=True

                        )

                        if result.success:

                            success_count += 1

                            logger.info(f"成功调整窗口: {title} (HWND: {hwnd})")

                        else:

                            logger.warning(f"调整窗口失败: {title} (HWND: {hwnd}) - {result.message}")

                except Exception as e:

                    logger.error(f"调整窗口失败: {e}")

            # 更新状态信息

            if success_count == total_count:

                message = f"成功重新调整所有 {total_count} 个绑定窗口"

                logger.info(message)

                self._update_step_details(message)

            else:

                message = f"重新调整窗口完成: {success_count}/{total_count} 个成功"

                logger.warning(message)

                self._update_step_details(message)

        except Exception as e:

            error_msg = f"重新调整绑定窗口失败: {e}"

            logger.error(error_msg)

            self._update_step_details(error_msg)

    def _handle_all_windows_lost(self):

        """处理所有窗口都失效的情况"""

        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QMessageBox

        try:

            # 停止任务执行

            if hasattr(self, 'safe_stop_tasks'):

                logger.warning("[窗口监控] 检测到所有窗口失效，正在停止任务...")

                self.safe_stop_tasks()

            # 在主线程中显示警告

            QTimer.singleShot(0, lambda: QMessageBox.warning(

                self,

                "窗口失效",

                "检测到所有绑定窗口都已失效！\n\n"

                "任务已自动停止。\n"

                "请检查目标窗口是否已关闭，然后在全局设置中重新绑定。"

            ))

        except Exception as e:

            logger.error(f"[窗口监控] 处理窗口失效异常: {e}")
