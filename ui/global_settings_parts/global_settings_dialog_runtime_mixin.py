import logging


logger = logging.getLogger(__name__)


class GlobalSettingsDialogRuntimeMixin:

    def _check_and_adjust_window_resolution(self, hwnd: int, title: str):
        """在界面线程读取配置，只将数据快照交给后台。"""
        width, height = self.get_custom_width(), self.get_custom_height()
        if width > 0 and height > 0 and hwnd:
            self._window_resize_jobs.submit(((hwnd, title),), width, height)

    def _batch_resize_all_windows(self):
        """整批调整在后台串行执行，重复请求按句柄合并。"""
        width, height = self.get_custom_width(), self.get_custom_height()
        if width <= 0 or height <= 0:
            return
        windows = tuple((item['hwnd'], str(item.get('title') or '未知窗口'))
                        for item in self.bound_windows if item.get('hwnd'))
        self._window_resize_jobs.submit(windows, width, height)

    def _register_windows_to_handle_manager(self):
        """按当前绑定列表同步句柄管理器，已移除的窗口立即注销。"""
        try:
            from utils.window.window_handle_manager import get_window_handle_manager
            import weakref

            self._release_window_handle_callbacks()
            handle_manager = get_window_handle_manager()
            owner_ref = weakref.ref(self)

            def notify(key, info):
                owner = owner_ref()
                if owner is not None:
                    owner._handle_window_invalid_notification(key, info)

            updates = {}
            self._window_handle_subscription = (handle_manager, updates, notify)
            handle_manager.add_user_notification_callback(notify)
            keep_keys = set()
            for i, window_info in enumerate(self.bound_windows):
                hwnd = window_info.get('hwnd')
                title = window_info.get('title', '')
                if hwnd and title:
                    key = f"bound_window_{i}"
                    keep_keys.add(key)
                    handle_manager.register_window(
                        key=key,
                        hwnd=hwnd,
                        title=title
                    )
                    def update(old_hwnd, new_hwnd, idx=i):
                        owner = owner_ref()
                        if owner is not None:
                            owner._handle_window_hwnd_update(idx, old_hwnd, new_hwnd)

                    updates[key] = update
                    handle_manager.add_update_callback(key, update)
                    logger.info(f"注册窗口到句柄管理器: {title} (HWND: {hwnd})")
            for key in list(handle_manager.get_all_registered_windows()):
                if key not in keep_keys:
                    handle_manager.unregister_window(key)
            if keep_keys:
                handle_manager.start_monitoring(interval=10.0)
                logger.info("窗口句柄管理器已注册并启动自动监控（间隔10秒）")
            else:
                handle_manager.stop_monitoring()
                logger.info("已注销全部绑定窗口的句柄监控")
        except Exception as e:
            logger.error(f"注册窗口到句柄管理器失败: {e}")
            self._release_window_handle_callbacks()

    def _release_window_handle_callbacks(self):
        subscription = getattr(self, '_window_handle_subscription', None)
        self._window_handle_subscription = None
        if subscription is None:
            return
        manager, updates, notify = subscription
        manager.remove_user_notification_callback(notify)
        for key, callback in updates.items():
            manager.remove_update_callback(key, callback=callback)
            manager.unregister_window(key)
        if not manager.get_all_registered_windows():
            manager.stop_monitoring()

    def _handle_window_hwnd_update(self, window_index: int, old_hwnd: int, new_hwnd: int):
        """处理窗口句柄更新 - 使用Qt信号确保线程安全"""
        try:
            # 使用QTimer.singleShot确保在主线程中执行UI更新
            from PySide6.QtCore import QTimer
            subscription = self._window_handle_subscription
            if subscription is None:
                return
            def update_in_main_thread():
                if self._window_handle_subscription is not subscription:
                    return
                try:
                    if window_index < len(self.bound_windows):
                        window_info = self.bound_windows[window_index]
                        old_title = window_info.get('title', '')
                        # 更新句柄
                        window_info['hwnd'] = new_hwnd
                        try:
                            from utils.window.window_identity import apply_window_identity
                            apply_window_identity(window_info, new_hwnd)
                        except Exception as e:
                            logger.debug(f"更新窗口特征失败: {e}")
                        if hasattr(self, '_save_bound_windows_config'):
                            self._save_bound_windows_config()
                        # 注销只修改池内映射；新句柄会由正式 OCR 请求入口登记。
                        ocr_unregister_info = dict(window_info)
                        ocr_unregister_info['hwnd'] = old_hwnd
                        self._unregister_window_ocr_service(ocr_unregister_info)
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
            QTimer.singleShot(0, self, update_in_main_thread)
        except Exception as e:
            logger.error(f"处理窗口句柄更新失败: {e}")
    def _handle_window_invalid_notification(self, key: str, window_info):
        """处理窗口句柄失效通知"""
        try:
            from PySide6.QtCore import QTimer
            subscription = self._window_handle_subscription
            if subscription is None:
                return

            def show_notification_in_main_thread():
                if self._window_handle_subscription is not subscription:
                    return
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
            QTimer.singleShot(0, self, show_notification_in_main_thread)
        except Exception as e:
            logger.error(f"处理窗口失效通知失败: {e}")
    def _check_and_update_window_handles(self):
        """手动检查并更新窗口句柄 - 在任务执行前调用"""
        try:
            from utils.window.window_handle_manager import get_window_handle_manager
            handle_manager = get_window_handle_manager()
            # 手动检查所有注册的窗口
            for i, window_info in enumerate(self.bound_windows):
                key = f"bound_window_{i}"
                old_hwnd = window_info.get('hwnd')
                if old_hwnd:
                    # 检查窗口是否仍然有效
                    new_hwnd = handle_manager.get_window_hwnd(key)
                    if new_hwnd and new_hwnd != old_hwnd:
                        logger.info(f"检测到窗口句柄变化: {window_info.get('title')} -> {old_hwnd} => {new_hwnd}")
                        # 直接更新，不触发回调避免UI阻塞
                        window_info['hwnd'] = new_hwnd
        except Exception as e:
            logger.error(f"手动检查窗口句柄失败: {e}")
    def _unregister_window_ocr_service(self, window_info):
        """注销窗口的OCR服务（安全版本，防止崩溃）"""
        try:
            from services.multiprocess_ocr_pool import get_existing_multiprocess_ocr_pool
            window_title = window_info.get('title', 'unknown')
            window_hwnd = window_info.get('hwnd', 0)
            if not window_hwnd or window_hwnd == 0:
                logger.warning(f"窗口无有效句柄，跳过OCR服务注销: {window_title}")
                return
            multi_ocr_pool = get_existing_multiprocess_ocr_pool()
            if multi_ocr_pool is None:
                logger.debug(f"OCR池未初始化，无需注销: {window_title}")
                return
            logger.debug(f"开始注销窗口OCR服务: {window_title} (HWND: {window_hwnd})")
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
        from utils.unified_dpi_handler import get_unified_dpi_handler, serialize_window_dpi_info
        dpi_handler = get_unified_dpi_handler()
        return serialize_window_dpi_info(hwnd, dpi_handler=dpi_handler)
