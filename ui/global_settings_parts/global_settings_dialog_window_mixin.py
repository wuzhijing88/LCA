import ctypes
import logging
import os

try:
    import win32gui
    WIN32_AVAILABLE_FOR_LIST = True
except ImportError:
    win32gui = None
    WIN32_AVAILABLE_FOR_LIST = False

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QMessageBox
from utils.window_binding_utils import sync_runtime_window_binding_state
from utils.window_activation_utils import (
    schedule_overlay_activation_boost,
    show_and_activate_overlay,
    show_and_raise_widget,
)

logger = logging.getLogger(__name__)


class GlobalSettingsDialogWindowMixin:
    def _refresh_window_select_combo(self):

        """使用 Win32 API 刷新窗口选择下拉框。"""

        if not WIN32_AVAILABLE_FOR_LIST:

            self.window_select_combo.addItem("需要安装 pywin32")

            self.window_select_combo.setEnabled(False)

            return

        try:

            logger.info("使用Win32 API枚举窗口列表")

            pc_windows = self._find_all_pc_windows()

            filtered_windows = [(title, title) for title, hwnd in pc_windows]

            self.window_select_combo.clear()

            self.window_select_combo.addItem("-- 选择窗口 --")

            if filtered_windows:

                # filtered_windows 现在是 (display_title, original_title) 的元组列表

                for display_title, original_title in filtered_windows:

                    self.window_select_combo.addItem(display_title)

                    # 将原始标题存储为item data

                    index = self.window_select_combo.count() - 1

                    self.window_select_combo.setItemData(index, original_title)

                    # 如果是分割线，设置为不可选择

                    if display_title.startswith("─"):

                        item = self.window_select_combo.model().item(index)

                        if item:

                            item.setFlags(item.flags() & ~Qt.ItemIsSelectable & ~Qt.ItemIsEnabled)

            else:

                self.window_select_combo.addItem("未找到任何窗口")

        except Exception as e:

            logger.error(f"刷新窗口选择列表失败: {e}")

            self.window_select_combo.clear()

            self.window_select_combo.addItem("获取窗口列表失败")

    def _get_friendly_window_title(self, title):

        """获取友好的窗口标题显示"""

        if not title:

            return "未知窗口"

        # 如果标题包含路径，提取文件名

        if '\\' in title:

            # 尝试提取路径中的可执行文件名

            import os

            parts = title.split(' ')

            for part in parts:

                if '\\' in part and ('.exe' in part.lower() or '.py' in part.lower()):

                    # 提取文件名（不包含扩展名）

                    filename = os.path.basename(part)

                    name_without_ext = os.path.splitext(filename)[0]

                    # 如果还有其他部分，组合显示

                    remaining = title.replace(part, '').strip()

                    if remaining:

                        return f"{name_without_ext} - {remaining}"

                    else:

                        return name_without_ext

        # 如果标题太长，截断显示

        if len(title) > 50:

            return title[:47] + "..."

        return title

    def _refresh_bound_windows_combo(self):

        """刷新已绑定窗口下拉框"""

        self.bound_windows_combo.clear()

        if not self.bound_windows:

            self.bound_windows_combo.addItem("-- 无绑定窗口 --")

            self.bound_windows_combo.setEnabled(False)

            self.remove_window_button.setEnabled(False)

            return

        self.bound_windows_combo.setEnabled(True)

        self.remove_window_button.setEnabled(True)

        for i, window_info in enumerate(self.bound_windows):

            title = window_info['title']

            hwnd = window_info.get('hwnd', 0)

            # 构建显示文本

            if hwnd and hwnd != 0:

                display_text = f"✓ {title} (句柄: {hwnd})"

            else:

                display_text = f"✓ {title}"

            self.bound_windows_combo.addItem(display_text)

            # 保存窗口信息到item data

            self.bound_windows_combo.setItemData(i, window_info)

    def _on_window_selected(self, index):

        """当用户从下拉框选择窗口时，自动绑定该单个窗口"""

        if not WIN32_AVAILABLE_FOR_LIST:

            return

        # 跳过第一个选项（"-- 选择窗口 --"）和分隔线

        if index == 0:

            return

        selected_text = self.window_select_combo.currentText()

        # 检查是否选择了分隔线

        if selected_text.startswith("─"):

            return

        # 获取itemData，可能是窗口标题或窗口句柄

        item_data = self.window_select_combo.itemData(index)

        try:

            # 判断itemData是句柄还是标题

            if isinstance(item_data, int):

                # itemData 可以直接保存窗口句柄

                window_hwnd = item_data

                original_title = selected_text

                logger.info(f"[插件模式] 直接使用窗口句柄: {window_hwnd}, 标题: {original_title}")

            else:

                # itemData 是原始标题时需要查找句柄

                original_title = item_data if item_data else selected_text

                logger.info(f"[Win32模式] 使用标题查找窗口: {original_title}")

                # 查找窗口句柄

                window_hwnd = self._find_window_handle(original_title)

                if not window_hwnd:

                    logger.warning(f"无法找到窗口句柄: {original_title}")

                    QMessageBox.warning(self, "错误", f"无法找到窗口: {original_title}")

                    self.window_select_combo.setCurrentIndex(0)

                    return

            # 检查是否已经绑定

            if self._is_window_already_bound(original_title, window_hwnd):

                logger.info(f"窗口已绑定，跳过: {original_title}")

                QMessageBox.information(self, "提示", f"窗口已经绑定: {selected_text}")

                self.window_select_combo.setCurrentIndex(0)

                return

            # 添加窗口

            self._add_window_silently(original_title, window_hwnd)

            self._save_bound_windows_config()

            logger.info(f"成功绑定单个窗口: {original_title} (HWND: {window_hwnd})")

            QMessageBox.information(self, "绑定成功", f"已成功绑定窗口:\n{selected_text}")

        except Exception as e:

            logger.error(f"绑定窗口失败: {e}")

            QMessageBox.warning(self, "错误", f"绑定窗口失败: {e}")

        # 重置选择

        self.window_select_combo.setCurrentIndex(0)

    def _smart_add_window(self):

        """智能添加窗口"""

        if not WIN32_AVAILABLE_FOR_LIST:

            QMessageBox.warning(self, "错误", "需要安装 pywin32 才能使用此功能")

            return

        selected_text = self.window_select_combo.currentText()

        if not selected_text or selected_text == "-- 选择窗口 --":

            QMessageBox.information(self, "提示", "请先选择要添加的窗口")

            return

        # 检查是否选择了分隔线

        if selected_text.startswith("─"):

            QMessageBox.information(self, "提示", "请选择一个有效的窗口，而不是分隔线")

            return

        # 获取原始窗口标题

        current_index = self.window_select_combo.currentIndex()

        original_title = self.window_select_combo.itemData(current_index)

        if not original_title:

            original_title = selected_text  # 回退到显示文本

        # 自动检测并添加窗口

        self._auto_detect_and_add_window(original_title)

        # 重置选择

        self.window_select_combo.setCurrentIndex(0)

    def _start_window_picker(self, window_selected_handler=None):

        """启动窗口选择工具"""

        if not WIN32_AVAILABLE_FOR_LIST:

            QMessageBox.warning(self, "错误", "需要安装 pywin32 才能使用此功能")

            return

        try:

            from ui.selectors.window_picker import WindowPickerOverlay

            logger.info("启动窗口选择工具")
            # 隐藏主窗口及其所有子窗口

            main_window = self.parent()

            # 【关键】在隐藏窗口之前记录原始可见状态

            main_window_was_visible = main_window.isVisible() if main_window else False

            parent_was_visible = self.isVisible()

            # 记录参数面板可见状态，便于窗口选择工具期间隐藏并在结束后恢复

            parameter_panel = None

            parameter_panel_was_visible = False

            if main_window and hasattr(main_window, 'parameter_panel'):

                parameter_panel = getattr(main_window, 'parameter_panel', None)

                if parameter_panel:

                    parameter_panel_was_visible = parameter_panel.isVisible()

            if main_window:

                logger.info("隐藏主窗口以便选择目标窗口")

                main_window.hide()

            # 也隐藏设置对话框自身

            self.hide()

            # 创建窗口选择器覆盖层，传入主窗口引用和原始可见状态

            self.window_picker_overlay = WindowPickerOverlay(

                self, main_window,

                parent_was_visible=parent_was_visible,

                main_window_was_visible=main_window_was_visible,

            )

            # 将参数面板纳入统一隐藏/恢复管理，避免遮挡窗口选择工具

            if parameter_panel and hasattr(self.window_picker_overlay, 'window_hider'):

                self.window_picker_overlay.window_hider.add_window(

                    parameter_panel,

                    "参数面板",

                    was_visible=parameter_panel_was_visible

                )

            # 连接信号

            selected_handler = window_selected_handler or self._on_window_picked

            self.window_picker_overlay.window_selected.connect(selected_handler)

            if show_and_activate_overlay(
                self.window_picker_overlay,
                log_prefix='全局设置窗口选择覆盖层',
                focus=True,
            ):
                logger.info("已使用统一覆盖层激活链启动窗口选择器")
            schedule_overlay_activation_boost(
                self.window_picker_overlay,
                log_prefix='全局设置窗口选择覆盖层',
                intervals_ms=(50, 150, 300),
                focus=True,
            )

        except Exception as e:

            logger.error(f"启动窗口选择工具失败: {e}")

            import traceback

            logger.error(f"错误详情: {traceback.format_exc()}")

            # 出错时恢复显示窗口

            show_and_activate_overlay(self, log_prefix='全局设置窗口恢复', focus=True)

            main_window = self.parent()

            if main_window:

                show_and_raise_widget(main_window, log_prefix='主窗口恢复')

            QMessageBox.critical(self, "错误", f"启动窗口选择工具失败: {e}")

    def _on_window_picked(self, hwnd: int, title: str):

        """窗口选择完成的回调"""

        try:

            safe_title = title.strip() if isinstance(title, str) else ""

            if not safe_title and hwnd:

                try:

                    import win32gui

                    safe_title = win32gui.GetWindowText(hwnd).strip()

                except Exception as e:

                    logger.debug(f"获取窗口标题失败: {e}")

            if not safe_title:

                safe_title = f"窗口_{hwnd}" if hwnd else "未知窗口"

            title = safe_title

            logger.info(f"选择了窗口: {title} (句柄: {hwnd})")

            if self._update_bound_window_from_picker(title, hwnd):

                self._save_bound_windows_config()

                if hasattr(self, '_refresh_bound_window_ui'):

                    self._refresh_bound_window_ui(refresh_window_select=True)

                else:

                    self._refresh_window_select_combo()

                    self._refresh_bound_windows_combo()

                if hasattr(self, '_sync_parent_window_binding_preview'):

                    self._sync_parent_window_binding_preview()

                logger.info(f"已更新绑定窗口信息: {title} (句柄: {hwnd})")

            # 检查窗口是否已经绑定

                self._check_and_adjust_window_resolution(hwnd, title)

                return

            if self._is_window_already_bound(title, hwnd):

                logger.info(f"窗口已经绑定: {title}，检查分辨率")

                # 已绑定的窗口也检查分辨率

                self._check_and_adjust_window_resolution(hwnd, title)

                return

            # 添加窗口到绑定列表

            self._add_window_silently(title, hwnd)

            self._save_bound_windows_config()

            if hasattr(self, '_refresh_bound_window_ui'):

                self._refresh_bound_window_ui(refresh_window_select=True)

            else:

                self._refresh_window_select_combo()

                self._refresh_bound_windows_combo()

            logger.info(f"自动更新窗口绑定模式: {self.window_binding_mode} (窗口数量: {len(self.bound_windows)})")

            # 通知主窗口更新标题（显示绑定窗口数量）

            if hasattr(self, '_sync_parent_window_binding_preview'):

                self._sync_parent_window_binding_preview()

            logger.info(f"窗口绑定成功：{title}")

            # 【新增】绑定成功后检查并调整分辨率

            self._check_and_adjust_window_resolution(hwnd, title)

            # 注意：窗口恢复显示由 WindowPickerOverlay.closeEvent 自动处理

        except Exception as e:

            logger.error(f"处理窗口选择失败: {e}")

            import traceback

            logger.error(f"错误详情: {traceback.format_exc()}")

    def _batch_add_same_type_windows(self):

        """一键绑定所有同类型窗口"""

        if not WIN32_AVAILABLE_FOR_LIST:

            QMessageBox.warning(self, "错误", "需要安装 pywin32 才能使用此功能")

            return

        # 批量绑定前先清理失效的窗口

        logger.info("批量绑定开始：准备清理失效窗口")

        self._cleanup_invalid_windows()

        logger.info("批量绑定：失效窗口清理完成")

        selected_text = self.window_select_combo.currentText()

        if not selected_text or selected_text == "-- 无可用窗口 --":

            QMessageBox.information(self, "提示", "请先选择一个窗口作为参考")

            return

        # 获取选中窗口的原始标题

        current_index = self.window_select_combo.currentIndex()

        original_title = self.window_select_combo.itemData(current_index)

        if not original_title:

            original_title = selected_text

        try:

            # 查找选中窗口的句柄

            reference_hwnd = self._find_window_handle(original_title)

            if not reference_hwnd:

                QMessageBox.warning(self, "错误", f"无法找到参考窗口: {original_title}")

                return

            # 检测参考窗口的类型

            window_type = self._detect_window_type(reference_hwnd, original_title)

            # 根据窗口类型查找所有同类型窗口

            same_type_windows = self._find_all_same_type_windows(window_type, reference_hwnd)

            logger.info(f"查找到 {len(same_type_windows)} 个{window_type}类型的窗口")

            if not same_type_windows:

                # 修复：如果没有找到其他窗口，尝试绑定当前选择的窗口

                logger.info(f"未找到其他{window_type}类型窗口，尝试绑定当前选择的窗口")

                # 检查当前窗口是否已经绑定

                if not self._is_window_already_bound(original_title, reference_hwnd):

                    reply = QMessageBox.question(

                        self, "绑定当前窗口",

                        f"未找到其他{window_type}类型的窗口。\n\n是否绑定当前选择的窗口：\n• {original_title}",

                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,

                        QMessageBox.StandardButton.Yes

                    )

                    if reply == QMessageBox.StandardButton.Yes:

                        self._add_window_if_not_exists(original_title, reference_hwnd)

                        self._save_bound_windows_config()

                        QMessageBox.information(self, "绑定完成", f"成功绑定窗口：{original_title}")

                    return

                else:

                    QMessageBox.information(self, "提示", f"当前窗口已经绑定，未找到其他{window_type}类型的窗口")

                    return

            # 显示确认对话框

            window_list_items = []

            for item in same_type_windows:

                if isinstance(item, (tuple, list)) and len(item) >= 2:

                    window_list_items.append(f"• {item[0]}")

                elif isinstance(item, int):

                    # 如果是句柄，尝试获取窗口标题

                    try:

                        import win32gui

                        title = win32gui.GetWindowText(item)

                        if not title:

                            title = f"窗口_{item}"

                        window_list_items.append(f"• {title}")

                    except:

                        window_list_items.append(f"• 窗口_{item}")

                else:

                    window_list_items.append(f"• {str(item)}")

            window_list = "\n".join(window_list_items)

            reply = QMessageBox.question(

                self, "确认批量绑定",

                f"检测到 {len(same_type_windows)} 个{window_type}类型的窗口:\n\n{window_list}\n\n是否一键绑定所有这些窗口？",

                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,

                QMessageBox.StandardButton.Yes

            )

            if reply == QMessageBox.StandardButton.Yes:

                # 批量添加窗口 - 性能优化版本

                added_count = 0

                skipped_count = 0

                # 安全解包：检查数据格式

                logger.info(f"批量绑定: 准备处理 {len(same_type_windows)} 个同类型窗口")

                # 【性能优化1】延迟UI刷新 - 只在最后刷新一次

                windows_to_add = []

                for i, item in enumerate(same_type_windows):

                    try:

                        # 检查item的类型和格式

                        if isinstance(item, (tuple, list)) and len(item) >= 2:

                            window_title, window_hwnd = item[0], item[1]

                        elif isinstance(item, int):

                            # 如果是单个整数（句柄），尝试获取窗口标题

                            import win32gui

                            window_hwnd = item

                            try:

                                window_title = win32gui.GetWindowText(window_hwnd)

                                if not window_title:

                                    window_title = f"窗口_{window_hwnd}"

                            except:

                                window_title = f"窗口_{window_hwnd}"

                        else:

                            logger.warning(f"跳过格式错误的项目 {i}: {type(item)} = {item}")

                            continue

                        # 检查是否已存在

                        if self._is_window_already_bound(window_title, window_hwnd):

                            skipped_count += 1

                            continue

                        # 收集待添加窗口

                        windows_to_add.append((window_title, window_hwnd))

                    except Exception as e:

                        logger.error(f"处理窗口项目失败: {e}")

                # 【性能优化2】批量添加窗口，延迟UI刷新和分辨率调整

                for window_title, window_hwnd in windows_to_add:

                    try:

                        self._add_window_silently_batch(window_title, window_hwnd)

                        added_count += 1

                    except Exception as e:

                        logger.warning(f"添加窗口失败: {window_title} - {e}")

                # 【性能优化3】批量完成后统一刷新UI

                if added_count > 0:

                    try:

                        if hasattr(self, '_refresh_bound_window_ui'):

                            self._refresh_bound_window_ui(
                                preferred_index=len(self.bound_windows) - 1,
                                refresh_window_select=True,
                            )

                        else:

                            self._refresh_window_select_combo()

                            self._refresh_bound_windows_combo()

                        if hasattr(self, '_sync_parent_window_binding_preview'):

                            self._sync_parent_window_binding_preview()

                        logger.info(f"批量绑定完成，已刷新UI")

                    except Exception as e:

                        logger.error(f"刷新UI失败: {e}")

                # 【性能优化4】批量完成后统一调整所有窗口分辨率（异步）

                if added_count > 0 and self.get_custom_width() > 0 and self.get_custom_height() > 0:

                    try:

                        logger.info(f"开始批量调整 {added_count} 个窗口的分辨率...")

                        # 使用QTimer异步执行，避免阻塞UI

                        QTimer.singleShot(100, self._batch_resize_all_windows)

                    except Exception as e:

                        logger.warning(f"批量调整窗口分辨率失败: {e}")

                # 批量绑定完成后保存配置

                if added_count > 0:

                    self._save_bound_windows_config()

                    QMessageBox.information(

                        self, "批量绑定完成",

                        f"成功绑定 {added_count} 个{window_type}窗口\n跳过已绑定的 {skipped_count} 个窗口\n配置已保存到文件\n\n窗口分辨率将在后台自动调整"

                    )

                else:

                    QMessageBox.information(self, "提示", "所有同类型窗口都已绑定")

        except Exception as e:

            QMessageBox.warning(self, "错误", f"批量绑定失败: {e}")

    def _detect_window_type(self, hwnd: int, title: str) -> str:

        """检测窗口类型"""

        try:

            logger.info(f"检测窗口类型: {title} (HWND: {hwnd})")

            # 基于窗口标题进行检测（仅支持PC窗口）

            logger.info(f"识别为PC窗口: {title}")

            return "PC窗口"

        except Exception as e:

            logger.warning(f"检测窗口类型失败: {e}")

            return "PC窗口"

    def _find_all_same_type_windows(self, window_type: str, reference_hwnd: int) -> list:

        """查找所有同类型的窗口"""

        try:

            same_type_windows = []

            # 仅支持PC窗口

            same_type_windows = self._find_all_pc_windows()

            return same_type_windows

        except Exception as e:

            logger.error(f"查找同类型窗口失败: {e}")

            return []

    def _find_all_pc_windows(self) -> list:

        """查找所有PC应用窗口（排除启动器）"""

        try:

            import win32gui

            pc_windows = []

            def enum_windows_callback(hwnd, _):

                try:

                    if win32gui.IsWindowVisible(hwnd):

                        title = win32gui.GetWindowText(hwnd)

                        if title and len(title.strip()) > 0:

                            # 排除启动器窗口

                            if ("启动器" not in title and

                                "系列启动器" not in title and

                                "launcher" not in title.lower()):

                                pc_windows.append((title, hwnd))

                except:

                    pass

                return True

            win32gui.EnumWindows(enum_windows_callback, None)

            logger.info(f"找到 {len(pc_windows)} 个PC窗口")

            return pc_windows

        except Exception as e:

            logger.error(f"查找PC窗口失败: {e}")

            return []

    def _update_bound_window_from_picker(self, title: str, hwnd: int) -> bool:

        """窗口选择工具：更新已绑定窗口的句柄或标题"""

        if not self.bound_windows or not hwnd or hwnd == 0:

            return False

        # 先按句柄匹配，更新标题/DPI信息

        for window_info in self.bound_windows:

            existing_title = str(window_info.get('title', '') or '').strip()

            existing_hwnd = window_info.get('hwnd', 0)

            if existing_hwnd == hwnd:

                updated = False

                if title and window_info.get('title') != title:

                    window_info['title'] = title

                    updated = True

                if updated:

                    try:

                        window_info['dpi_info'] = self._get_window_dpi_info(hwnd)

                    except Exception as e:

                        logger.debug(f"更新DPI信息失败: {e}")

                return updated

        # 再按唯一标题匹配，仅在旧句柄缺失或失效时更新句柄

        if title:

            same_title_windows = [w for w in self.bound_windows if w.get('title') == title]

            if len(same_title_windows) == 1:

                target = same_title_windows[0]

                existing_hwnd = target.get('hwnd', 0)

                should_update = not existing_hwnd or existing_hwnd == 0

                if not should_update:

                    try:

                        import win32gui

                        should_update = not win32gui.IsWindow(existing_hwnd)

                    except Exception:

                        should_update = False

                updated = False

                if should_update and existing_hwnd != hwnd:

                    target['hwnd'] = hwnd

                    updated = True

                if updated:

                    try:

                        target['dpi_info'] = self._get_window_dpi_info(hwnd)

                    except Exception as e:

                        logger.debug(f"更新DPI信息失败: {e}")

                return updated

        return False

    def _is_window_already_bound(self, title: str, hwnd: int) -> bool:

        """检查窗口是否已经绑定"""

        for window_info in self.bound_windows:

            existing_title = str(window_info.get('title', '') or '').strip()
            existing_hwnd = window_info.get('hwnd', 0)

            if hwnd and hwnd != 0 and existing_hwnd == hwnd:

                return True

            if (not hwnd or hwnd == 0) and title and existing_title == title:

                return True

        return False

    def _save_bound_windows_config(self):

        """保存绑定窗口配置到文件"""

        try:

            self.current_config['bound_windows'] = self.bound_windows

            self.current_config['window_binding_mode'] = self.window_binding_mode

            sync_runtime_window_binding_state(self.current_config)

            # 确保自定义分辨率也被保存

            if hasattr(self, 'width_spinbox') and hasattr(self, 'height_spinbox'):

                self.current_config['custom_width'] = self.width_spinbox.value()

                self.current_config['custom_height'] = self.height_spinbox.value()

            # 通过父窗口保存配置

            parent_window = self.parent()

            if parent_window and hasattr(parent_window, 'save_config_func'):

                parent_window.save_config_func(self.current_config)

                logger.info(f"已通过父窗口保存配置，共 {len(self.bound_windows)} 个窗口")

            else:

                # 备用方案：直接调用main模块的save_config

                from app_core.config_store import save_config

                save_config(self.current_config)

                logger.info(f"已直接保存配置，共 {len(self.bound_windows)} 个窗口")

        except Exception as e:

            logger.error(f"保存配置失败: {e}")

    def _cleanup_invalid_windows(self):

        """清理失效的窗口（句柄无效或窗口不可见）"""

        try:

            import win32gui

            logger.info(f"开始清理失效窗口，当前绑定窗口数量: {len(self.bound_windows)}")

            valid_windows = []

            removed_count = 0

            for window_info in self.bound_windows:

                window_title = window_info.get('title', '')

                hwnd = window_info.get('hwnd', 0)

                # 检查窗口是否仍然有效

                is_valid = False

                try:

                    if hwnd and hwnd != 0:

                        # 更严格的窗口验证

                        window_exists = win32gui.IsWindow(hwnd)

                        window_visible = win32gui.IsWindowVisible(hwnd) if window_exists else False

                        # 尝试获取窗口标题来进一步验证

                        current_title = ""

                        if window_exists:

                            try:

                                current_title = win32gui.GetWindowText(hwnd)

                            except:

                                pass

                        # PC窗口验证：只要窗口存在就认为有效，不要求特定窗口标题，允许最小化

                        if window_exists:

                            is_valid = True

                            if window_visible:

                                logger.debug(f"窗口有效(可见): {window_title} (HWND: {hwnd})")

                            else:

                                logger.debug(f"窗口有效(最小化): {window_title} (HWND: {hwnd})")

                        else:

                            logger.info(f"窗口失效: {window_title} (HWND: {hwnd}) - 窗口不存在")

                    else:

                        logger.info(f"窗口失效: {window_title} - 无有效句柄")

                except Exception as e:

                    logger.warning(f"检查窗口失败: {window_title} (HWND: {hwnd}) - {e}")

                    # 检查失败也认为是失效窗口

                    is_valid = False

                if is_valid:

                    valid_windows.append(window_info)

                else:

                    removed_count += 1

                    logger.info(f"移除失效窗口: {window_title} (HWND: {hwnd})")

            # 更新绑定窗口列表

            self.bound_windows = valid_windows

            logger.info(f"清理完成: 移除 {removed_count} 个失效窗口，剩余 {len(valid_windows)} 个有效窗口")

            # 如果有窗口被移除，刷新界面并保存配置

            if removed_count > 0:

                self._refresh_bound_windows_combo()

                self._save_bound_windows_config()

                logger.info(f"已保存清理后的配置")

        except Exception as e:

            logger.error(f"清理失效窗口失败: {e}")
