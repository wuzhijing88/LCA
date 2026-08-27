from ..parameter_panel_support import *
from utils.window.window_coordinate_common import (
    build_window_info,
    get_available_geometry_for_widget,
    get_qt_virtual_desktop_rect,
    get_window_client_qt_global_rect,
    resolve_qt_screen,
)
from utils.window.window_activation_utils import show_and_raise_widget

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

class ParameterPanelWindowMixin:

    def event(self, event):
        """重写事件处理，监听窗口激活事件"""
        if event.type() == event.Type.WindowActivate:
            # 当小窗口被激活时，不要自动激活主窗口，让用户能正常输入
            # 只有在用户明确需要时才激活主窗口
            pass
        return super().event(event)

    def changeEvent(self, event):
        """处理窗口状态变化事件"""
        if event.type() == QEvent.Type.ActivationChange:
            # 智能激活同步：保护输入框焦点
            if self.isActiveWindow() and self.parent_window and self._snap_to_parent_enabled:
                self._smart_activate_main_window()
        super().changeEvent(event)

    def closeEvent(self, event):
        """处理窗口关闭事件"""
        logger.debug(f"参数面板关闭事件 - card_id: {self.current_card_id}")
        self.manually_closed = True  # 标记为用户手动关闭
        self._stop_combo_key_sequence_recording()

        # 停止回放线程
        if hasattr(self, '_replay_thread') and self._replay_thread and self._replay_thread.isRunning():
            try:
                self._replay_thread.stop()
            except Exception:
                pass

        # 注销录制和回放快捷键
        self._unregister_record_hotkey()
        self._unregister_replay_hotkey()
        self._is_recording_panel_active = False
        self._clear_favorites_runtime_refs()

        self.panel_closed.emit()
        # 注意：不要在这里重置 current_card_id
        event.accept()

    def _is_interactive_child_widget(self, widget):
        interactive_types = (
            QLineEdit,
            QSpinBox,
            QDoubleSpinBox,
            QTextEdit,
            QPlainTextEdit,
            QComboBox,
            QPushButton,
        )
        current_widget = widget
        while current_widget and current_widget != self:
            if isinstance(current_widget, interactive_types):
                return True
            current_widget = current_widget.parent()
        return False

    def _is_close_button_clicked(self, event) -> bool:
        if not hasattr(self, 'close_button') or not hasattr(self, 'title_frame'):
            return False
        close_button_rect = self.close_button.geometry()
        close_button_global = self.title_frame.mapToParent(close_button_rect.topLeft())
        close_button_window_rect = QRect(close_button_global, close_button_rect.size())
        return close_button_window_rect.contains(event.pos())

    def _begin_panel_drag(self, event):
        self._mouse_pressed = True
        self._mouse_press_pos = event.globalPosition().toPoint()
        self._window_pos_before_move = self.pos()
        self._parent_pos_before_move = self.parent_window.pos() if self.parent_window else QPoint()
        self._panel_parent_offset = self._window_pos_before_move - self._parent_pos_before_move
        self._is_dragging = False
        event.accept()

    def _move_parent_window_with_panel(self, new_panel_pos):
        if not self.parent_window or not self._snap_to_parent_enabled:
            return
        panel_parent_offset = getattr(self, '_panel_parent_offset', QPoint(self.parent_window.width() + 2, 0))
        main_window_new_x = new_panel_pos.x() - panel_parent_offset.x()
        main_window_new_y = new_panel_pos.y() - panel_parent_offset.y()
        self.parent_window.move(main_window_new_x, main_window_new_y)

    def mousePressEvent(self, event):
        clicked_widget = self.childAt(event.pos())
        if clicked_widget and self._is_interactive_child_widget(clicked_widget):
            super().mousePressEvent(event)
            return

        if event.button() == Qt.MouseButton.LeftButton:
            if self._is_close_button_clicked(event):
                self.hide_panel()
                event.accept()
                return
            self._begin_panel_drag(event)
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._mouse_pressed and event.buttons() == Qt.MouseButton.LeftButton:
            if not self._is_dragging:
                self._is_dragging = True
                logger.debug('Start dragging parameter panel')
            global_pos = event.globalPosition().toPoint()
            delta = global_pos - self._mouse_press_pos
            new_panel_pos = self._window_pos_before_move + delta
            self.move(new_panel_pos)
            self._move_parent_window_with_panel(new_panel_pos)
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._is_dragging:
                logger.debug('Finish dragging parameter panel')
            self._mouse_pressed = False
            self._is_dragging = False
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def _auto_save_before_hide(self):
        if self.current_card_id is None or not hasattr(self, 'widgets') or not self.widgets:
            return
        try:
            self._apply_parameters(auto_close=False)
            logger.info(f"Auto-save parameter panel before hide: card_id={self.current_card_id}")
        except Exception as exc:
            logger.warning(f"隐藏前自动保存失败：{exc}")

    def hide_panel(self):
        logger.debug(f"Hide parameter panel - card_id: {self.current_card_id}")
        self._auto_save_before_hide()
        self.manually_closed = True
        self.hide()
        self.panel_closed.emit()

    def is_panel_open(self) -> bool:
        return self.isVisible() and self.current_card_id is not None

    def apply_and_close(self):
        if not self.is_panel_open():
            return
        logger.info(
            f"[Auto Apply] Apply parameter panel before workflow run (card_id={self.current_card_id})"
        )
        self._apply_parameters(auto_close=True)

    def set_editing_locked(self, locked: bool):
        logger.info(f"[Parameter Panel] set_editing_locked ignored (locked={locked})")

    def _detach_from_parent_snap(self):
        if not self.isVisible() or not self.parent_window:
            return
        try:
            client_geometry = self._get_parent_client_geometry()
            snapped_x = client_geometry.x() + client_geometry.width() + 2
            snapped_y = client_geometry.y()
            near_snapped_x = abs(self.x() - snapped_x) <= 40
            near_snapped_y = abs(self.y() - snapped_y) <= 80
            if near_snapped_x and near_snapped_y:
                self.move(self.x() + 32, self.y())
            client_height = int(client_geometry.height())
            if client_height > 0 and self.height() < client_height:
                self.resize(self.width(), client_height)
        except Exception:
            pass

    def set_snap_to_parent_enabled(self, enabled: bool):
        enabled = bool(enabled)
        self._snap_to_parent_enabled = enabled
        if enabled:
            if self.isVisible():
                self._position_panel()
            return

        self._release_panel_height_constraint()
        self._detach_from_parent_snap()

    def sync_window_state(self, parent_state):
        logger.debug(f"[Parameter Panel] sync_window_state: parent_state={parent_state}")
        if parent_state == Qt.WindowState.WindowMinimized:
            logger.debug('[Parameter Panel] Parent minimized, hide panel')
            self.main_window_minimized = True
            self.hide()
            return

        if parent_state in (Qt.WindowState.WindowNoState, Qt.WindowState.WindowMaximized):
            logger.debug(
                f"[Parameter Panel] Parent restored: manually_closed={self.manually_closed}, current_card_id={self.current_card_id}"
            )
            self.main_window_minimized = False
            if not self.manually_closed and self.current_card_id is not None:
                logger.debug('[Parameter Panel] Delay show and reposition panel')
                QTimer.singleShot(100, self.show)
                QTimer.singleShot(250, self._position_panel)

    def sync_activation(self, activated):
        if self._activation_in_progress:
            return
        if activated and self.isVisible():
            self._position_panel()
            self._smart_activate_parameter_panel()

    def _setup_ui(self):
        self._configure_panel_size()
        main_layout = self._create_panel_root_layout()
        self._build_panel_title_bar(main_layout)
        content_container = self._build_panel_content_container()
        main_layout.addWidget(content_container)
        self.status_label = None
        self.hide()

    def _configure_panel_size(self) -> None:
        self.setFixedWidth(440 + self._shadow_margin * 2)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)

    def _create_panel_root_layout(self) -> QVBoxLayout:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(
            self._shadow_margin,
            self._shadow_margin,
            self._shadow_margin,
            self._shadow_margin,
        )
        main_layout.setSpacing(0)
        return main_layout

    def _build_panel_title_bar(self, main_layout: QVBoxLayout) -> None:
        self.title_frame = QFrame()
        self.title_frame.setFrameStyle(QFrame.Shape.NoFrame)
        self.title_frame.setFixedHeight(36)

        title_layout = QHBoxLayout(self.title_frame)
        title_layout.setContentsMargins(8, 3, 4, 3)

        self.title_input = QLineEdit('\u53c2\u6570\u8bbe\u7f6e')
        self.title_input.setFont(QFont('Microsoft YaHei', 10, QFont.Weight.Bold))
        self.title_input.setFrame(False)
        self.title_input.setReadOnly(False)
        self.title_input.setStyleSheet(
            'QLineEdit { background: transparent; border: none; padding: 0px; }'
        )
        self.title_input.editingFinished.connect(self._on_title_edited)
        title_layout.addWidget(self.title_input)
        title_layout.addStretch()

        self.close_button = CloseButton()
        self.close_button.clicked.connect(self.hide_panel)
        title_layout.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignVCenter)
        main_layout.addWidget(self.title_frame)

    def _build_panel_content_container(self) -> QFrame:
        content_container = QFrame()
        content_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        content_layout = QVBoxLayout(content_container)
        content_layout.setContentsMargins(6, 4, 6, 6)
        content_layout.setSpacing(6)
        self._build_panel_scroll_area(content_layout)
        self._build_panel_footer_buttons(content_layout)
        return content_container

    def _build_panel_scroll_area(self, content_layout: QVBoxLayout) -> None:
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)

        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(4, 4, 4, 4)
        self.content_layout.setSpacing(6)

        self.scroll_area.setWidget(self.content_widget)
        content_layout.addWidget(self.scroll_area)

    def _build_panel_footer_buttons(self, content_layout: QVBoxLayout) -> None:
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.apply_button = QPushButton('\u5e94\u7528')
        self.apply_button.clicked.connect(lambda: self._apply_parameters(auto_close=True))
        button_layout.addWidget(self.apply_button)

        self.reset_button = QPushButton('\u91cd\u7f6e')
        self.reset_button.clicked.connect(self._reset_parameters)
        button_layout.addWidget(self.reset_button)

        content_layout.addLayout(button_layout)

    def _remove_combobox_shadow(self, combobox):
        return

    def _apply_force_down_popup(self, combobox):
        pass

    def _install_wheel_filter(self, widget, name):
        if not isinstance(widget, (QComboBox, QSpinBox, QDoubleSpinBox, QSlider)):
            return
        wheel_filter = WheelEventFilter(f"{type(widget).__name__}_{name}")
        widget.installEventFilter(wheel_filter)
        if not hasattr(self, '_wheel_filters'):
            self._wheel_filters = []
        self._wheel_filters.append(wheel_filter)
        logger.debug(f"Install wheel filter for widget {name} ({type(widget).__name__})")

    def _apply_styles(self):
        pass

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

    def _activate_main_window(self):
        """激活主窗口（仅在主窗口未被最小化时）"""

    def _smart_activate_main_window(self):
        """智能激活主窗口，保护输入框焦点"""
        # 关闭参数面板吸附时，不进行主窗口焦点联动
        if not self._snap_to_parent_enabled:
            return

        # 如果焦点保护处于激活状态，不进行激活同步
        if self._input_focus_protection_active:
            logger.debug("焦点保护激活中，跳过主窗口激活同步")
            return

        # 检查当前焦点控件
        focus_widget = QApplication.focusWidget()

        # 如果当前有输入控件获得焦点，不进行激活同步
        if focus_widget and isinstance(focus_widget, (QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit)):
            logger.debug(f"输入控件 {focus_widget} 获得焦点，跳过主窗口激活同步")
            return

        # 如果主窗口已经是激活状态，不需要重复激活
        if self.parent_window.isActiveWindow():
            return

        # 防止循环激活
        if self._activation_in_progress:
            return

        self._activation_in_progress = True
        try:
            # 保存当前焦点控件
            saved_focus = QApplication.focusWidget()

            # 仅提升层级，不主动抢焦点
            show_and_raise_widget(self.parent_window, log_prefix='主窗口激活同步')

            # 如果之前有焦点控件且仍然可用，尝试恢复焦点
            if saved_focus and saved_focus.isVisible() and saved_focus.isEnabled():
                # 使用定时器延迟恢复焦点，避免立即被覆盖
                QTimer.singleShot(50, lambda: self._restore_widget_focus(saved_focus))

            logger.debug("参数面板激活，智能同步主窗口（保护焦点）")
        finally:
            # 使用定时器重置标志
            QTimer.singleShot(200, lambda: setattr(self, '_activation_in_progress', False))

    def _restore_widget_focus(self, widget):

        """恢复焦点到指定控件（用于窗口激活同步）"""

        try:

            if widget and widget.isVisible() and widget.isEnabled():

                widget.setFocus()

                logger.debug(f"恢复焦点到控件: {widget}")

        except Exception as e:

            logger.debug(f"恢复焦点失败: {e}")

    def _smart_activate_parameter_panel(self):
        """智能激活参数面板，保护输入框焦点"""
        # 如果焦点保护处于激活状态，不进行激活同步
        if self._input_focus_protection_active:
            logger.debug("焦点保护激活中，跳过参数面板激活同步")
            return

        # 检查当前焦点控件
        focus_widget = QApplication.focusWidget()

        # 如果当前有输入控件获得焦点，不进行激活同步
        if focus_widget and isinstance(focus_widget, (QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit)):
            logger.debug(f"输入控件 {focus_widget} 获得焦点，跳过参数面板激活同步")
            return

        # 如果参数面板已经是激活状态，不需要重复激活
        if self.isActiveWindow():
            return

        # 防止循环激活
        if self._activation_in_progress:
            return

        self._activation_in_progress = True
        try:
            # 保存当前焦点控件
            saved_focus = QApplication.focusWidget()

            # 仅提升层级，不主动抢焦点
            show_and_raise_widget(self, log_prefix='参数面板激活同步')

            # 如果之前有焦点控件且仍然可用，尝试恢复焦点
            if saved_focus and saved_focus.isVisible() and saved_focus.isEnabled():
                # 使用定时器延迟恢复焦点，避免立即被覆盖
                QTimer.singleShot(50, lambda: self._restore_widget_focus(saved_focus))

            logger.debug("主窗口激活，智能同步参数面板（保护焦点）")
        finally:
            # 使用定时器重置标志
            QTimer.singleShot(200, lambda: setattr(self, '_activation_in_progress', False))

    def paintEvent(self, event):
        """绘制圆角背景（10px圆角，与主窗口保持一致）"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 创建圆角矩形路径
        path = QPainterPath()
        rect = self.rect()
        shadow_margin = max(0, int(getattr(self, "_shadow_margin", 0)))
        radius = 10  # 圆角半径，与主窗口保持一致
        content_rect = rect.adjusted(shadow_margin, shadow_margin, -shadow_margin, -shadow_margin)
        path.addRoundedRect(content_rect, radius, radius)

        # 从主题管理器获取背景颜色
        try:
            from themes import get_theme_manager
            theme_manager = get_theme_manager()
            bg_color = theme_manager.get_qcolor('background')
            bg_color.setAlpha(250)  # 略透明
            border_color = theme_manager.get_qcolor('border')
        except Exception:
            from themes import theme_color

            bg_color = QColor(theme_color("background", "#ffffff"))
            bg_color.setAlpha(250)
            border_color = QColor(theme_color("border", "#e0e0e0"))

        # 绘制阴影（内置阴影边框）
        if shadow_margin > 0 and not getattr(self, "_use_native_shadow", False):
            for i in range(shadow_margin, 0, -1):
                alpha = int(20 * (i / shadow_margin))
                shadow_rect = content_rect.adjusted(-i, -i, i, i)
                shadow_path = QPainterPath()
                shadow_path.addRoundedRect(shadow_rect, radius + i, radius + i)
                painter.fillPath(shadow_path, QBrush(QColor(0, 0, 0, alpha)))

        # 绘制背景
        painter.fillPath(path, QBrush(bg_color))

        # 绘制边框（2px粗边框，模拟系统边框效果）
        painter.setPen(QPen(border_color, 2))
        painter.drawPath(path)

    def _try_enable_native_shadow(self) -> None:
        """尝试启用系统级阴影（Windows 11 DWM 圆角）"""
        if os.name != "nt":
            return
        try:
            import ctypes
            from ctypes import wintypes

            hwnd = int(self.winId())
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            DWMWCP_ROUND = 2

            preference = wintypes.DWORD(DWMWCP_ROUND)
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd,
                DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(preference),
                ctypes.sizeof(preference),
            )
            if result == 0:
                self._use_native_shadow = True
                self._shadow_margin = 0
        except Exception:
            self._use_native_shadow = False
