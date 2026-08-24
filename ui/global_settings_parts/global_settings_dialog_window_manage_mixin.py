import logging

from PySide6.QtWidgets import QInputDialog, QMessageBox

from utils.hwnd_utils import as_hwnd
from utils.window_identity import apply_window_identity

logger = logging.getLogger(__name__)


class GlobalSettingsDialogWindowManageMixin:

    def _build_bound_window_info(self, window_title: str, hwnd: int = 0):
        new_window = {
            'title': window_title,
            'enabled': True
        }
        if as_hwnd(hwnd):
            hwnd = as_hwnd(hwnd)
            apply_window_identity(new_window, hwnd)
            try:
                new_window['dpi_info'] = self._get_window_dpi_info(hwnd)
            except Exception as e:
                logger.debug(f"获取DPI信息失败: {e}")
        return new_window
    def _refresh_bound_window_ui(self, preferred_index=None, refresh_window_select: bool = False):
        self.window_binding_mode = 'multiple' if len(self.bound_windows) > 1 else 'single'
        if refresh_window_select:
            self._refresh_window_select_combo()
        self._refresh_bound_windows_combo()
        if (
            preferred_index is not None
            and hasattr(self, 'bound_windows_combo')
            and self.bound_windows
            and self.bound_windows_combo.count() > 0
        ):
            target_index = max(0, min(int(preferred_index), len(self.bound_windows) - 1))
            self.bound_windows_combo.setCurrentIndex(target_index)
        self._update_execution_mode_visibility()
    def _sync_parent_window_binding_preview(self):
        parent_window = self.parent()
        if not parent_window:
            return
        if hasattr(parent_window, 'bound_windows'):
            parent_window.bound_windows = self.bound_windows
        if hasattr(parent_window, 'window_binding_mode'):
            parent_window.window_binding_mode = self.window_binding_mode
        if hasattr(parent_window, 'current_target_window_title'):
            if self.window_binding_mode == 'single' and self.bound_windows:
                parent_window.current_target_window_title = self.bound_windows[0].get('title')
            else:
                parent_window.current_target_window_title = None
        if hasattr(parent_window, '_update_main_window_title'):
            parent_window._update_main_window_title()
    def _find_duplicate_bound_window(self, window_title: str, hwnd: int = 0):
        safe_title = str(window_title or '').strip()
        safe_hwnd = as_hwnd(hwnd)
        for window_info in self.bound_windows:
            existing_title = str(window_info.get('title', '') or '').strip()
            existing_hwnd = as_hwnd(window_info.get('hwnd', 0))
            if safe_hwnd and existing_hwnd == safe_hwnd:
                return window_info
            if existing_title == safe_title and existing_hwnd == safe_hwnd:
                return window_info
            if not safe_hwnd and safe_title and existing_title == safe_title:
                return window_info
        return None
    def _append_bound_window(
        self,
        window_title: str,
        hwnd: int = 0,
        refresh_ui: bool = True,
        refresh_window_select: bool = False,
        sync_parent: bool = True,
    ):
        new_window = self._build_bound_window_info(window_title, hwnd)
        self.bound_windows.append(new_window)
        if refresh_ui:
            self._refresh_bound_window_ui(
                preferred_index=len(self.bound_windows) - 1,
                refresh_window_select=refresh_window_select,
            )
        if sync_parent:
            self._sync_parent_window_binding_preview()
        return new_window
    def _add_selected_window_direct(self, selected_text):
        """直接添加选中的窗口（原有逻辑）"""
        # 查找窗口句柄
        hwnd = self._find_window_handle(selected_text)
        # 如果没有找到句柄（比如所有TheRender窗口都已绑定），给出提示
        if selected_text == "TheRender" and hwnd is None:
            QMessageBox.information(self, "提示", "所有TheRender窗口都已绑定")
            return
        self._add_window_if_not_exists(selected_text, hwnd)
    def _auto_detect_and_add_window(self, selected_text):
        """自动检测窗口类型并添加"""
        try:
            # 查找窗口句柄
            hwnd = self._find_window_handle(selected_text)
            if hwnd == "ALL_BOUND":
                QMessageBox.information(self, "提示", f"所有 {selected_text} 窗口都已被绑定")
                return
            elif not hwnd:
                QMessageBox.warning(self, "错误", f"未找到窗口: {selected_text}")
                return
            QMessageBox.information(self, "检测结果", "检测到普通窗口\n将使用标准模式添加")
            self._add_window_if_not_exists(selected_text, hwnd)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"自动检测失败: {e}")
    def _add_simulator_window(self):
        """添加窗口"""
        try:
            child_windows = self._enumerate_child_windows()
            if not child_windows:
                QMessageBox.information(self, "提示", "未找到可用窗口")
                return
            # 获取已绑定的窗口句柄，用于过滤
            bound_hwnds = set()
            for window_info in self.bound_windows:
                hwnd = as_hwnd(window_info.get('hwnd'))
                if hwnd:
                    bound_hwnds.add(hwnd)
            # 准备选择列表和映射，过滤已绑定的窗口
            dialog_items = []
            window_mapping = {}  # 映射显示文本到窗口信息
            available_windows = []
            for hwnd, title, class_name in child_windows:
                hwnd = as_hwnd(hwnd)
                if hwnd not in bound_hwnds:  # 只显示未绑定的窗口
                    display_text = f"{title} (类名: {class_name}, 句柄: {hwnd})"
                    dialog_items.append(display_text)
                    window_mapping[display_text] = (hwnd, title, class_name)
                    available_windows.append((hwnd, title, class_name))
            if not available_windows:
                QMessageBox.information(self, "提示", "所有窗口都已绑定")
                return
            selected_item, ok = QInputDialog.getItem(
                self, "选择窗口", "请选择要添加的窗口:",
                dialog_items, 0, False
            )
            if ok and selected_item:
                hwnd, title, class_name = window_mapping[selected_item]
                self._add_window_if_not_exists(title, hwnd)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"获取窗口失败:\n{e}")
    def _add_window_if_not_exists(self, window_title: str, hwnd: int = 0):
        """如果窗口不存在则添加"""
        hwnd = as_hwnd(hwnd)
        duplicate_window = self._find_duplicate_bound_window(window_title, hwnd)
        if duplicate_window:
            existing_title = duplicate_window.get('title', '')
            existing_hwnd = as_hwnd(duplicate_window.get('hwnd', 0))
            if hwnd and hwnd != 0 and existing_hwnd == hwnd:
                QMessageBox.information(self, "提示", f"窗口句柄 {hwnd} 已被绑定到 '{existing_title}'")
            elif hwnd and hwnd != 0:
                QMessageBox.information(self, "提示", f"窗口 '{window_title}' (句柄: {hwnd}) 已存在")
            else:
                QMessageBox.information(self, "提示", f"窗口 '{window_title}' 已存在")
            return
        self._append_bound_window(window_title, hwnd)
        if hasattr(self, "_schedule_wgc_desktop_engine_warning"):
            self._schedule_wgc_desktop_engine_warning()
        # 【性能优化】不预创建OCR服务，改为按需创建（避免绑定窗口时卡顿）
        # self._preregister_window_ocr_service(new_window)
        # 工具 修复：绑定窗口时不自动激活窗口，避免干扰用户操作
        # 注释掉自动激活逻辑，只在实际执行任务时才激活窗口
        # if hwnd and hwnd != 0:
        #     # 注意：这里需要调用父窗口（MainWindow）的激活方法
        #     if hasattr(self.parent(), '_activate_window_if_needed'):
        #         self.parent()._activate_window_if_needed(hwnd, window_title)
        logger.info(f"绑定窗口完成，未激活窗口: {window_title} (HWND: {hwnd})")
    def _add_window_silently(self, window_title: str, hwnd: int = 0):
        """静默添加窗口（不显示对话框，全面异常保护）"""
        try:
            hwnd = as_hwnd(hwnd)
            logger.info(f"[_add_window_silently] 开始添加窗口: {window_title}, hwnd={hwnd}")
            duplicate_window = self._find_duplicate_bound_window(window_title, hwnd)
            if duplicate_window:
                logger.info(f"跳过重复窗口: {window_title} (HWND: {hwnd})")
                return
            logger.info(f"成功添加窗口: {window_title} (HWND: {hwnd})")
            self._append_bound_window(window_title, hwnd)
            logger.info(f"窗口添加完成: {window_title} (HWND: {hwnd})")
        except Exception as e:
            logger.error(f"添加窗口时发生严重错误: {e}")
            import traceback
            logger.error(traceback.format_exc())
    def _add_window_silently_batch(self, window_title: str, hwnd: int = 0):
        """批量模式静默添加窗口（跳过UI刷新和分辨率调整，避免卡顿）"""
        try:
            hwnd = as_hwnd(hwnd)
            logger.info(f"[批量模式] 开始添加窗口: {window_title}, hwnd={hwnd}")
            duplicate_window = self._find_duplicate_bound_window(window_title, hwnd)
            if duplicate_window:
                logger.info(f"[批量模式] 跳过重复窗口: {window_title} (HWND: {hwnd})")
                return
            self._append_bound_window(window_title, hwnd, refresh_ui=False, sync_parent=False)
            logger.info(f"[批量模式] 成功添加窗口: {window_title} (HWND: {hwnd})")
            # 【批量模式优化】跳过UI刷新和分辨率调整，这些操作将在批量完成后统一执行
            logger.info(f"[批量模式] 窗口添加完成: {window_title} (HWND: {hwnd})")
        except Exception as e:
            logger.error(f"[批量模式] 添加窗口时发生严重错误: {e}")
            import traceback
            logger.error(traceback.format_exc())
    def _generate_unique_window_title(self, original_title: str, hwnd: int) -> str:
        """为窗口生成唯一的显示标题"""
        hwnd = as_hwnd(hwnd)
        try:
            # 检查是否有相同标题的窗口
            same_title_count = 0
            for window_info in self.bound_windows:
                existing_title = window_info.get('title', '')
                if original_title in existing_title:
                    same_title_count += 1
            # 如果有相同标题的窗口，添加编号
            if same_title_count > 0:
                return f"{original_title} #{same_title_count + 1} (HWND: {hwnd})"
            else:
                return f"{original_title} (HWND: {hwnd})"
        except Exception as e:
            logger.warning(f"生成唯一窗口标题失败: {e}")
            return f"{original_title} (HWND: {hwnd})"
    def _remove_selected_window(self):
        """移除选中的窗口（安全版本，防止崩溃）"""
        try:
            current_index = self.bound_windows_combo.currentIndex()
            if current_index < 0 or current_index >= len(self.bound_windows):
                QMessageBox.information(self, "提示", "请先选择要移除的窗口")
                return
            window_info = self.bound_windows[current_index]
            window_title = window_info.get('title', 'unknown')
            hwnd = window_info.get('hwnd', 0)
            reply = QMessageBox.question(
                self, "确认移除",
                f"确定要移除窗口 '{window_title}' 吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            logger.info(f"开始移除窗口: {window_title} (HWND: {hwnd})")
            # 【修复卡顿】在后台线程注销OCR服务，避免阻塞UI
            import threading
            def unregister_ocr_background():
                try:
                    self._unregister_window_ocr_service(window_info)
                except Exception as e:
                    logger.error(f"注销OCR服务时出错: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
            ocr_cleanup_thread = threading.Thread(target=unregister_ocr_background, daemon=True, name=f"UnregisterOCR-{window_title}")
            ocr_cleanup_thread.start()
            # 从列表中移除窗口
            try:
                self.bound_windows.pop(current_index)
                next_index = current_index if current_index < len(self.bound_windows) else len(self.bound_windows) - 1
                logger.debug(f"窗口已从列表移除: {window_title}")
            except Exception as e:
                logger.error(f"从列表移除窗口失败: {e}")
                raise
            window_count = len(self.bound_windows)
            self._refresh_bound_window_ui(preferred_index=next_index if next_index >= 0 else None)
            self._sync_parent_window_binding_preview()
            logger.info(f"删除窗口后自动更新绑定模式: {self.window_binding_mode} (窗口数量: {window_count})")
            # 更新执行模式可见性
            try:
                self._update_execution_mode_visibility()
            except Exception as e:
                logger.warning(f"更新执行模式可见性失败: {e}")
            # 显示成功消息
            try:
                QMessageBox.information(self, "成功", f"已移除窗口: {window_title}")
            except Exception as e:
                logger.warning(f"显示成功消息失败: {e}")
            logger.info(f"窗口移除完成: {window_title}")
        except Exception as e:
            logger.error(f"移除窗口过程中发生严重错误: {e}")
            import traceback
            logger.error(traceback.format_exc())
            try:
                QMessageBox.critical(self, "错误", f"移除窗口失败: {str(e)}")
            except Exception:
                pass
