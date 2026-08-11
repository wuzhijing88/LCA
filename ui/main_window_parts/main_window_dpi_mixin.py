import logging
import time

from PySide6.QtWidgets import QMessageBox

logger = logging.getLogger(__name__)


class MainWindowDpiMixin:
    def _setup_dpi_monitoring(self):

        """设置DPI监控"""

        try:

            # 初始化统一DPI处理器

            from utils.unified_dpi_handler import get_unified_dpi_handler

            self.unified_dpi_handler = get_unified_dpi_handler()

            # 设置DPI变化回调

            def on_dpi_change(hwnd, old_dpi_info, new_dpi_info, window_title=""):

                old_dpi = old_dpi_info.get('dpi', 96)

                new_dpi = new_dpi_info.get('dpi', 96)

                old_scale = old_dpi_info.get('scale_factor', 1.0)

                new_scale = new_dpi_info.get('scale_factor', 1.0)

                logger.info(f"检测到DPI变化: {old_dpi} DPI ({old_scale:.2f}x) -> {new_dpi} DPI ({new_scale:.2f}x) (窗口: {window_title})")

                # 显示DPI变化通知

                if hasattr(self, 'dpi_notification'):

                    self.dpi_notification.show_notification(old_dpi, new_dpi)

                # 更新状态栏信息

                self._update_step_details(f"检测到DPI变化: {old_scale:.0%} -> {new_scale:.0%}，请重新选择OCR区域以确保准确性")

                # 如果有OCR区域选择器正在运行，提醒用户重新选择

                try:

                    from PySide6.QtWidgets import QMessageBox

                    reply = QMessageBox.question(

                        self,

                        "DPI变化检测",

                        f"检测到系统DPI从 {old_scale:.0%} 变更为 {new_scale:.0%}。\n\n"

                        f"为确保OCR区域选择和识别的准确性，建议重新选择OCR区域。\n\n"

                        f"是否现在重新调整所有绑定窗口？",

                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,

                        QMessageBox.StandardButton.Yes

                    )

                    if reply == QMessageBox.StandardButton.Yes:

                        # 重新调整所有绑定窗口

                        self._readjust_all_bound_windows()

                except Exception as e:

                    logger.error(f"显示DPI变化对话框失败: {e}")

            self.unified_dpi_handler.add_dpi_change_callback(on_dpi_change)

            # 启用DPI监控

            self.unified_dpi_handler.enable_monitoring()

            logger.info("DPI监控已设置")

        except Exception as e:

            logger.error(f"设置DPI监控失败: {e}")

    def _get_window_dpi_info(self, hwnd: int) -> dict:

        """获取窗口DPI信息并保存到配置"""

        try:
            from utils.unified_dpi_handler import get_unified_dpi_handler, serialize_window_dpi_info

            dpi_handler = getattr(self, 'unified_dpi_handler', None)
            if dpi_handler is None:
                dpi_handler = get_unified_dpi_handler()

            saved_dpi_info = serialize_window_dpi_info(hwnd, dpi_handler=dpi_handler)
            logger.info(f"保存窗口DPI信息: HWND={hwnd}, DPI={saved_dpi_info['dpi']}, 缩放={saved_dpi_info['scale_factor']:.2f}")
            return saved_dpi_info

            if hasattr(self, 'unified_dpi_handler'):

                dpi_info = self.unified_dpi_handler.get_window_dpi_info(hwnd, check_changes=False)

            else:

                # 如果DPI处理器未初始化，创建临时实例

                from utils.unified_dpi_handler import get_unified_dpi_handler

                dpi_handler = get_unified_dpi_handler()

                dpi_info = dpi_handler.get_window_dpi_info(hwnd, check_changes=False)

            # 只保存必要的DPI信息到配置文件

            saved_dpi_info = {

                'dpi': dpi_info.get('dpi', 96),

                'scale_factor': dpi_info.get('scale_factor', 1.0),

                'method': dpi_info.get('method', 'Default'),

                'recorded_at': time.time()  # 记录时间戳

            }

            logger.info(f"保存窗口DPI信息: HWND={hwnd}, DPI={saved_dpi_info['dpi']}, 缩放={saved_dpi_info['scale_factor']:.2f}")

            return saved_dpi_info

        except Exception as e:

            logger.warning(f"获取窗口DPI信息失败 (HWND: {hwnd}): {e}")

            # 返回默认DPI信息

            return {

                'dpi': 96,

                'scale_factor': 1.0,

                'method': 'Default',

                'recorded_at': time.time()

            }

    def _apply_saved_dpi_info(self, window_info: dict, hwnd: int):

        """应用保存的DPI信息"""

        try:

            saved_dpi_info = window_info.get('dpi_info')

            if not saved_dpi_info:

                logger.debug(f"窗口没有保存的DPI信息: HWND={hwnd}")

                return

            # 获取当前DPI信息

            current_dpi_info = self._get_window_dpi_info(hwnd)

            saved_dpi = saved_dpi_info.get('dpi', 96)

            current_dpi = current_dpi_info.get('dpi', 96)

            # 检查DPI是否发生变化

            if abs(saved_dpi - current_dpi) > 1:

                logger.warning(f"检测到DPI变化: 保存时={saved_dpi}, 当前={current_dpi} (HWND: {hwnd})")

                # 显示DPI变化通知

                if hasattr(self, 'dpi_notification'):

                    self.dpi_notification.show_notification(saved_dpi, current_dpi)

                # 更新保存的DPI信息

                window_info['dpi_info'] = current_dpi_info

                # 保存更新后的配置

                self._save_config_with_updated_dpi()

            else:

                logger.debug(f"DPI无变化: {current_dpi} (HWND: {hwnd})")

        except Exception as e:

            logger.error(f"应用DPI信息失败 (HWND: {hwnd}): {e}")

    def _force_refresh_dpi_info(self, window_info: dict, hwnd: int):

        """强制刷新DPI信息，不使用缓存的旧信息"""

        try:

            logger.info(f"强制刷新窗口DPI信息 (HWND: {hwnd})")

            # 清除DPI缓存

            if hasattr(self, 'unified_dpi_handler'):

                self.unified_dpi_handler.clear_cache(hwnd)

                logger.debug(f"已清除窗口 {hwnd} 的DPI缓存")

            # 重新检测当前DPI信息

            current_dpi_info = self._get_window_dpi_info(hwnd)

            # 更新窗口信息中的DPI数据

            old_dpi_info = window_info.get('dpi_info', {})

            window_info['dpi_info'] = current_dpi_info

            # 记录DPI变化

            old_dpi = old_dpi_info.get('dpi', 96)

            current_dpi = current_dpi_info.get('dpi', 96)

            if abs(old_dpi - current_dpi) > 1:

                logger.info(f"检测到DPI变化: {old_dpi} -> {current_dpi} (HWND: {hwnd})")

                # 保存更新后的配置

                self._save_config_with_updated_dpi()

            else:

                logger.debug(f"DPI无变化: {current_dpi} (HWND: {hwnd})")

        except Exception as e:

            logger.error(f"强制刷新DPI信息失败 (HWND: {hwnd}): {e}")

    def _save_config_with_updated_dpi(self):

        """保存更新后的DPI配置"""

        try:

            # 更新配置字典

            self._store_runtime_bound_windows_to_config()

            # 保存到文件

            from app_core.config_store import save_config

            save_config(self.config)

            logger.info("已更新配置文件中的DPI信息")

        except Exception as e:

            logger.error(f"保存DPI配置失败: {e}")

    def _save_bound_windows_config(self):

        """保存绑定窗口配置到文件"""

        try:

            # 更新配置字典中的绑定窗口信息

            self._store_runtime_bound_windows_to_config()

            # 保存到文件

            from app_core.config_store import save_config

            save_config(self.config)

            logger.info(f"已保存绑定窗口配置到文件，共 {len(self.bound_windows)} 个窗口")

        except Exception as e:

            logger.error(f"保存绑定窗口配置失败: {e}")

    def start_dpi_monitoring(self):

        """启动DPI监控"""

        try:

            if hasattr(self, 'unified_dpi_handler'):

                self.unified_dpi_handler.enable_monitoring(True)

                logger.info("DPI监控已启动")

            else:

                logger.warning("统一DPI处理器未初始化，无法启动监控")

        except Exception as e:

            logger.error(f"启动DPI监控失败: {e}")

    def stop_dpi_monitoring(self):

        """停止DPI监控"""

        try:

            if hasattr(self, 'unified_dpi_handler'):

                self.unified_dpi_handler.disable_monitoring()

                logger.info("DPI监控已停止")

        except Exception as e:

            logger.error(f"停止DPI监控失败: {e}")

    def _handle_dpi_recalibration(self):

        """处理DPI重新校准请求"""

        from PySide6.QtWidgets import QMessageBox

        try:

            logger.info("用户请求DPI重新校准")

            # 重新校准所有绑定窗口的DPI

            if hasattr(self, 'bound_windows') and self.bound_windows:

                for window_info in self.bound_windows:

                    if window_info.get('enabled', True):

                        hwnd = window_info.get('hwnd')

                        title = window_info.get('title', '')

                        if hwnd:

                            # 清除DPI缓存，强制重新检测

                            if hasattr(self, 'unified_dpi_handler'):

                                self.unified_dpi_handler.clear_cache(hwnd)

                            logger.info(f"重新校准窗口DPI: {title} (HWND: {hwnd})")

                QMessageBox.information(self, "DPI校准", "DPI重新校准完成")

            else:

                QMessageBox.information(self, "DPI校准", "没有绑定的窗口需要校准")

        except Exception as e:

            logger.error(f"DPI重新校准失败: {e}")

            QMessageBox.warning(self, "错误", f"DPI重新校准失败:\n{str(e)}")

    def _handle_dpi_auto_adjust(self):

        """处理DPI自动调整请求"""

        try:

            logger.info("用户请求DPI自动调整")

            # 触发多窗口分辨率调整

            if hasattr(self, 'bound_windows') and self.bound_windows:

                enabled_windows = [w for w in self.bound_windows if w.get('enabled', True)]

                if enabled_windows:

                    logger.info(f"开始自动调整 {len(enabled_windows)} 个窗口")

                    self._apply_multi_window_resize()

                else:

                    logger.info("没有启用的窗口需要调整")

            else:

                logger.info("没有绑定的窗口需要调整")

        except Exception as e:

            logger.error(f"DPI自动调整失败: {e}")

    def _handle_dpi_dismiss(self):

        """处理DPI通知关闭请求"""

        try:

            logger.info("用户关闭DPI变化通知")

            if hasattr(self, 'dpi_notification'):

                self.dpi_notification.hide()

        except Exception as e:

            logger.error(f"关闭DPI通知失败: {e}")
