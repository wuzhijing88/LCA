import logging
import threading
import time

from PySide6.QtCore import QTimer

from utils.universal_window_manager import get_universal_window_manager

logger = logging.getLogger(__name__)


class GlobalSettingsDialogRuntimeMixin:





    def _check_and_adjust_window_resolution(self, hwnd: int, title: str):

        """绑定窗口成功后检查并调整分辨率"""

        try:

            # 获取自定义分辨率配置

            target_width = self.get_custom_width()

            target_height = self.get_custom_height()

            # 检查是否配置了自定义分辨率

            if target_width <= 0 or target_height <= 0:

                logger.debug(f"未配置自定义分辨率，跳过窗口 {title} 的分辨率调整")

                return

            # 检查窗口是否有效

            import win32gui

            if not win32gui.IsWindow(hwnd):

                logger.warning(f"窗口句柄无效，跳过分辨率调整: {title} (HWND: {hwnd})")

                return

            # 获取当前窗口客户区大小

            try:

                left, top, right, bottom = win32gui.GetClientRect(hwnd)

                current_width = right - left

                current_height = bottom - top

            except Exception as e:

                logger.warning(f"获取窗口客户区大小失败: {e}")

                return

            # 检查分辨率是否已经符合

            if current_width == target_width and current_height == target_height:

                logger.info(f"窗口 {title} 分辨率已符合 ({current_width}x{current_height})，跳过调整")

                return

            # 分辨率不符合，进行调整

            logger.info(f"窗口 {title} 分辨率不符合 ({current_width}x{current_height} -> {target_width}x{target_height})，开始调整")

            from utils.universal_window_manager import get_universal_window_manager

            window_manager = get_universal_window_manager()

            result = window_manager.adjust_single_window(hwnd, target_width, target_height, async_mode=True)

            if result.success:

                logger.info(

                    f"窗口分辨率调整成功: {title} "

                    f"({result.before_size[0]}x{result.before_size[1]} -> {result.after_size[0]}x{result.after_size[1]})"

                )

            else:

                logger.warning(f"窗口分辨率调整失败: {title} - {result.message}")

        except Exception as e:

            logger.error(f"检查并调整窗口分辨率失败: {e}")




    def _batch_resize_all_windows(self):

        """批量调整所有窗口的分辨率（异步执行，避免阻塞UI）"""

        try:

            logger.info(f"[批量调整] 开始批量调整所有窗口分辨率...")

            target_width = self.get_custom_width()

            target_height = self.get_custom_height()

            if target_width <= 0 or target_height <= 0:

                logger.info(f"[批量调整] 未配置自定义分辨率，跳过调整")

                return

            # 获取需要调整的窗口

            windows_to_resize = []

            for window_info in self.bound_windows:

                hwnd = window_info.get('hwnd', 0)

                if hwnd and hwnd != 0:

                    windows_to_resize.append(window_info)

            if not windows_to_resize:

                logger.info(f"[批量调整] 没有需要调整的窗口")

                return

            logger.info(f"[批量调整] 共需调整 {len(windows_to_resize)} 个窗口")

            # 使用通用窗口管理器批量调整

            try:

                from utils.universal_window_manager import get_universal_window_manager

                window_manager = get_universal_window_manager()

                success_count = 0

                fail_count = 0

                for window_info in windows_to_resize:

                    hwnd = window_info.get('hwnd')

                    title = window_info.get('title', 'Unknown')

                    try:

                        # 检查当前分辨率是否已符合

                        import win32gui

                        if win32gui.IsWindow(hwnd):

                            left, top, right, bottom = win32gui.GetClientRect(hwnd)

                            current_width = right - left

                            current_height = bottom - top

                            if current_width == target_width and current_height == target_height:

                                logger.info(f"[批量调整] - {title}: 分辨率已符合，跳过")

                                success_count += 1

                                continue

                        # 使用异步模式避免阻塞

                        result = window_manager.adjust_single_window(

                            hwnd, target_width, target_height, async_mode=True

                        )

                        if result.success:

                            logger.info(f"[批量调整] ✓ {title}: {result.before_size} -> {result.after_size}")

                            success_count += 1

                        else:

                            logger.warning(f"[批量调整] ✗ {title}: {result.message}")

                            fail_count += 1

                    except Exception as e:

                        logger.error(f"[批量调整] ✗ {title}: {e}")

                        fail_count += 1

                logger.info(f"[批量调整] 完成: 成功 {success_count} 个, 失败 {fail_count} 个")

            except ImportError as e:

                logger.error(f"[批量调整] 导入窗口管理器失败: {e}")

            except Exception as e:

                logger.error(f"[批量调整] 批量调整失败: {e}")

                import traceback

                logger.error(traceback.format_exc())

        except Exception as e:

            logger.error(f"[批量调整] 批量调整分辨率过程异常: {e}")

            import traceback

            logger.error(traceback.format_exc())


    def _preregister_window_ocr_service(self, window_info):

        """为窗口预注册OCR服务"""

        try:

            logger.debug(f"开始为窗口预注册OCR服务: {window_info}")

            from services.multiprocess_ocr_pool import get_multi_ocr_pool

            window_title = window_info['title']

            window_hwnd = window_info.get('hwnd')

            if window_hwnd:

                logger.debug(f"获取多OCR池实例...")

                multi_ocr_pool = get_multi_ocr_pool()

                logger.debug(f"调用预注册方法: {window_title} (HWND: {window_hwnd})")

                success = multi_ocr_pool.preregister_window(window_title, window_hwnd)

                if success:

                    logger.info(f"成功 为窗口预创建OCR服务成功: {window_title} (HWND: {window_hwnd})")

                else:

                    logger.warning(f"警告 为窗口预创建OCR服务失败: {window_title} (HWND: {window_hwnd})")

            else:

                logger.warning(f"窗口无有效句柄，跳过OCR服务预创建: {window_title}")

        except ImportError as e:

            logger.error(f"导入OCR服务模块失败: {e}")

        except Exception as e:

            logger.error(f"预注册OCR服务异常: {e}", exc_info=True)

    def _register_windows_to_handle_manager(self):

        """将绑定的窗口注册到句柄管理器"""

        try:

            from utils.window_handle_manager import get_window_handle_manager

            handle_manager = get_window_handle_manager()

            # 启用自动监控，检测窗口句柄变化

            handle_manager.start_monitoring(interval=10.0)

            # 添加用户通知回调

            handle_manager.add_user_notification_callback(self._handle_window_invalid_notification)

            logger.info("窗口句柄管理器已注册并启动自动监控（间隔10秒）")

            for i, window_info in enumerate(self.bound_windows):

                hwnd = window_info.get('hwnd')

                title = window_info.get('title', '')

                if hwnd and title:

                    # 注册窗口

                    key = f"bound_window_{i}"

                    handle_manager.register_window(

                        key=key,

                        hwnd=hwnd,

                        title=title

                    )

                    # 添加更新回调

                    handle_manager.add_update_callback(

                        key,

                        lambda old_hwnd, new_hwnd, idx=i: self._handle_window_hwnd_update(idx, old_hwnd, new_hwnd)

                    )

                    logger.info(f"注册窗口到句柄管理器: {title} (HWND: {hwnd})")

        except Exception as e:

            logger.error(f"注册窗口到句柄管理器失败: {e}")

    def _handle_window_hwnd_update(self, window_index: int, old_hwnd: int, new_hwnd: int):

        """处理窗口句柄更新 - 使用Qt信号确保线程安全"""

        try:

            # 使用QTimer.singleShot确保在主线程中执行UI更新

            from PySide6.QtCore import QTimer

            def update_in_main_thread():

                try:

                    if window_index < len(self.bound_windows):

                        window_info = self.bound_windows[window_index]

                        old_title = window_info.get('title', '')

                        # 更新句柄

                        window_info['hwnd'] = new_hwnd

                        # 同步OCR服务的句柄绑定，避免旧句柄残留导致OCR进程堆积

                        try:

                            import threading

                            ocr_unregister_info = dict(window_info)

                            ocr_unregister_info['hwnd'] = old_hwnd

                            ocr_register_info = dict(window_info)

                            def update_ocr_services():

                                try:

                                    self._unregister_window_ocr_service(ocr_unregister_info)

                                    self._preregister_window_ocr_service(ocr_register_info)

                                except Exception as e:

                                    logger.error(f"OCR服务句柄更新失败: {e}")

                            threading.Thread(

                                target=update_ocr_services,

                                daemon=True,

                                name=f"OCR-HWND-Update-{old_title}"

                            ).start()

                        except Exception as e:

                            logger.error(f"启动OCR句柄更新线程失败: {e}")

                        logger.info(f"窗口句柄已更新: {old_title} -> {old_hwnd} => {new_hwnd}")

                        # 刷新界面显示 - 在主线程中安全执行

                        if hasattr(self, '_refresh_bound_windows_combo'):

                            self._refresh_bound_windows_combo()

                        # 使用状态栏通知，避免阻塞

                        if hasattr(self, 'status_bar') and self.status_bar:

                            self.status_bar.showMessage(f"窗口句柄已更新: {old_title}", 3000)

                        logger.info(f"窗口句柄更新完成: {old_title} ({old_hwnd} => {new_hwnd})")

                except Exception as e:

                    logger.error(f"主线程中处理窗口句柄更新失败: {e}")

            # 使用QTimer.singleShot在主线程中执行更新

            QTimer.singleShot(0, update_in_main_thread)

        except Exception as e:

            logger.error(f"处理窗口句柄更新失败: {e}")

    def _handle_window_invalid_notification(self, key: str, window_info):

        """处理窗口句柄失效通知"""

        try:

            from PySide6.QtCore import QTimer

            from PySide6.QtWidgets import QMessageBox

            def show_notification_in_main_thread():

                try:

                    window_title = window_info.title if hasattr(window_info, 'title') else '未知窗口'

                    # 显示状态栏消息

                    if hasattr(self, 'status_bar') and self.status_bar:

                        self.status_bar.showMessage(f"窗口句柄失效: {window_title}，请重新绑定", 10000)

                    # 显示弹窗通知（可选，避免过于打扰用户）

                    # reply = QMessageBox.warning(

                    #     self,

                    #     "窗口句柄失效",

                    #     f"检测到窗口 '{window_title}' 的句柄已失效。\n\n"

                    #     f"这通常是因为模拟器重启或窗口关闭导致的。\n"

                    #     f"请重新绑定窗口以继续使用工作流功能。",

                    #     QMessageBox.StandardButton.Ok

                    # )

                    logger.warning(f"用户通知: 窗口 '{window_title}' 句柄失效，需要重新绑定")

                except Exception as e:

                    logger.error(f"显示窗口失效通知失败: {e}")

            # 使用QTimer.singleShot确保在主线程中执行UI更新

            QTimer.singleShot(0, show_notification_in_main_thread)

        except Exception as e:

            logger.error(f"处理窗口失效通知失败: {e}")

    def _check_and_update_window_handles(self):

        """手动检查并更新窗口句柄 - 在任务执行前调用"""

        try:

            from utils.window_handle_manager import get_window_handle_manager

            handle_manager = get_window_handle_manager()

            # 手动检查所有注册的窗口

            for i, window_info in enumerate(self.bound_windows):

                key = f"bound_window_{i}"

                old_hwnd = window_info.get('hwnd')

                if old_hwnd:

                    # 检查窗口是否仍然有效

                    new_hwnd = handle_manager.get_current_hwnd(key)

                    if new_hwnd and new_hwnd != old_hwnd:

                        logger.info(f"检测到窗口句柄变化: {window_info.get('title')} -> {old_hwnd} => {new_hwnd}")

                        # 直接更新，不触发回调避免UI阻塞

                        window_info['hwnd'] = new_hwnd

        except Exception as e:

            logger.error(f"手动检查窗口句柄失败: {e}")

    def _unregister_window_ocr_service(self, window_info):

        """注销窗口的OCR服务（安全版本，防止崩溃）"""

        try:

            from services.multiprocess_ocr_pool import get_multi_ocr_pool, _global_multiprocess_ocr_pool

            window_title = window_info.get('title', 'unknown')

            window_hwnd = window_info.get('hwnd', 0)

            if not window_hwnd or window_hwnd == 0:

                logger.warning(f"窗口无有效句柄，跳过OCR服务注销: {window_title}")

                return

            if _global_multiprocess_ocr_pool is None:

                logger.debug(f"OCR池未初始化，无需注销: {window_title}")

                return

            logger.debug(f"开始注销窗口OCR服务: {window_title} (HWND: {window_hwnd})")

            multi_ocr_pool = get_multi_ocr_pool()

            success = multi_ocr_pool.unregister_window(window_hwnd)

            if success:

                logger.info(f"✓ 注销窗口OCR服务成功: {window_title} (HWND: {window_hwnd})")

            else:

                logger.debug(f"窗口无对应OCR服务: {window_title} (HWND: {window_hwnd})")

        except Exception as e:

            logger.error(f"注销OCR服务异常: {window_title if 'window_title' in locals() else 'unknown'}, 错误: {e}")

            import traceback

            logger.error(traceback.format_exc())


    def _check_and_cleanup_closed_windows(self):

        """检查并清理已关闭的窗口（已禁用自动检测）"""

        # 自动检测已禁用

        # 所有常规检测方法都无法准确判断窗口是否真正关闭

        logger.debug("自动窗口检测已禁用，需要手动清理无效窗口")



    def _get_window_dpi_info(self, hwnd: int) -> dict:

        """获取窗口DPI信息并保存到配置"""

        try:
            from utils.unified_dpi_handler import get_unified_dpi_handler, serialize_window_dpi_info

            dpi_handler = get_unified_dpi_handler()
            return serialize_window_dpi_info(hwnd, dpi_handler=dpi_handler)

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

            return saved_dpi_info

        except Exception as e:

            # 返回默认DPI信息

            return {

                'dpi': 96,

                'scale_factor': 1.0,

                'method': 'Default',

                'recorded_at': time.time()

            }
