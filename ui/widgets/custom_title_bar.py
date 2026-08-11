# -*- coding: utf-8 -*-
import sys
from typing import List
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QStyle, QApplication, QSizePolicy, QToolButton,
    QSpacerItem # Import QSpacerItem
)
# Import QIcon explicitly if needed for size setting
from PySide6.QtCore import Qt, QPoint, QSize 
from PySide6.QtGui import QMouseEvent, QAction, QIcon, QFontMetrics
from utils.window_activation_utils import show_and_raise_widget

class MainWindow: pass

class CustomTitleBar(QWidget):
    """A custom title bar where title is manually centered."""
    def __init__(self, parent: 'MainWindow', actions: List[QAction]):
        super().__init__(parent)
        self.setAutoFillBackground(False) 

        self.parent_window = parent 
        self._mouse_pressed = False
        self._mouse_press_pos = QPoint()
        self._window_pos_before_move = QPoint()
        
        # 初始化action_widgets字典和toolbar
        self.action_widgets = {}
        self.toolbar = QWidget(self)

        self.setFixedHeight(36)
        self.setObjectName("CustomTitleBar")

        # Stylesheet - 由主题管理器统一管理，不再使用硬编码样式
        # 标题栏样式现在由全局主题控制
        pass

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(8, 0, 0, 0) 
        main_layout.setSpacing(2)

        # --- Left Actions --- 
        self.action_buttons = {} 
        self.file_actions_container = QWidget(self) 
        container_layout = QHBoxLayout(self.file_actions_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(2)

        toggle_button = None
        if actions:
            toggle_action = actions[0]
            toggle_button = QToolButton(self)
            toggle_button.setDefaultAction(toggle_action)
            toggle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            toggle_button.setFixedSize(28, 28)
            main_layout.addWidget(toggle_button)
            self.action_buttons[toggle_action] = toggle_button

            for action in actions[1:]:
                button = QToolButton(self.file_actions_container)
                button.setDefaultAction(action)
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
                button.setFixedSize(28, 28)
                container_layout.addWidget(button)
                self.action_buttons[action] = button 
            
            main_layout.addWidget(self.file_actions_container)
        
        # --- Spacer between left and right buttons --- 
        # Remove previous stretch
        main_layout.addStretch(1) # Keep stretch to push right buttons

        # --- Title Label (Created but NOT added to layout) ---
        self.title_label = QLabel(self) # Parent is self (the title bar)
        self.title_label.setObjectName("titleLabel")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setMouseTracking(True) # Keep mouse tracking for tooltips
        self._full_title = "" # Store the full title text
        # We will set its geometry manually

        # --- Window Buttons (Right) ---
        self.window_button_container = QWidget(self) # Store container reference
        window_button_layout = QHBoxLayout(self.window_button_container)
        window_button_layout.setContentsMargins(0,0,4,0)
        style = self.style()
        def create_window_button(text, tooltip):
            button = QPushButton(text, self.window_button_container)
            button.setObjectName("windowButton")
            button.setToolTip(tooltip)
            return button
        # 置顶按钮
        self._window_topmost = False
        self.topmost_button = create_window_button("⊼", "窗口置顶")
        self.topmost_button.setCheckable(True)
        self.topmost_button.clicked.connect(self._toggle_topmost)
        window_button_layout.addWidget(self.topmost_button)
        self.minimize_button = create_window_button("−", "最小化")
        self.minimize_button.clicked.connect(self._on_minimize_clicked)
        window_button_layout.addWidget(self.minimize_button)
        self.maximize_char = "□"; self.restore_char = "❐"
        self.maximize_button = create_window_button(self.maximize_char, "最大化")
        self.maximize_button.setCheckable(True); self.maximize_button.clicked.connect(self._toggle_maximize)
        window_button_layout.addWidget(self.maximize_button)
        self.close_button = create_window_button("✕", "关闭")
        self.close_button.setObjectName("closeButton"); self.close_button.clicked.connect(self.parent_window.close)
        window_button_layout.addWidget(self.close_button)

        main_layout.addWidget(self.window_button_container)

        self.setLayout(main_layout)
        # Restore connection for title update
        self.parent_window.windowTitleChanged.connect(self.setWindowTitle)
        # Initial positioning of title
        self.title_label.adjustSize() # Get initial size hint

    # Visibility method (no change needed)
    def set_file_actions_visible(self, visible: bool):
        if hasattr(self, 'file_actions_container'):
             self.file_actions_container.setVisible(visible)
             self.layout().update()

    # --- Add resizeEvent for manual title positioning ---
    def resizeEvent(self, event):
        """Manually center the title label when the title bar is resized."""
        super().resizeEvent(event)
        # --- MODIFIED: Call helper to update elided title and position ---
        self._update_elided_title()
        # -----------------------------------------------------------------

    def showEvent(self, event):
        """在窗口显示时更新标题位置"""
        super().showEvent(event)
        # 使用QTimer延迟调用，确保布局已完成
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._update_elided_title)
        # if hasattr(self, 'title_label'):
        #     title_width = self.title_label.sizeHint().width()
        #     title_height = self.title_label.sizeHint().height()
        #     bar_width = self.width()
        #     bar_height = self.height()
        #     
        #     # Calculate position
        #     x = (bar_width - title_width) / 2
        #     y = (bar_height - title_height) / 2
        #     
        #     self.title_label.setGeometry(int(x), int(y), title_width, title_height)

    # --- Restore setWindowTitle --- 
    def setWindowTitle(self, title):
         if hasattr(self, 'title_label'):
             # --- UPDATED: Store full title and call update helper --- 
             self._full_title = title
             self._update_elided_title()
             # -------------------------------------------------------
             # self.title_label.setText(title) # Set the potentially long text
             # self.title_label.setToolTip(title) # Set the full text as tooltip
             # # Reposition after text change affects size hint
             # self.title_label.adjustSize()
             # self.resizeEvent(None) # Trigger repositioning logic

    # --- ADDED: Helper method to update elided title and position ---
    def _update_elided_title(self):
        if not hasattr(self, 'title_label') or not hasattr(self, '_full_title'):
            return

        bar_width = self.width()
        bar_height = self.height()

        # 计算左侧所有元素的总宽度
        left_width = 8  # main_layout的左边距

        # 加上toggle按钮宽度
        toggle_button = next(iter(self.action_buttons.values()), None)
        if toggle_button and toggle_button.isVisible():
            left_width += toggle_button.width() + 2  # 加上spacing

        # 加上file_actions_container宽度
        if hasattr(self, 'file_actions_container') and self.file_actions_container.isVisible():
            left_width += self.file_actions_container.width() + 2

        # 获取window_button_container的左边界位置
        right_width = 0
        if hasattr(self, 'window_button_container'):
            right_width = bar_width - self.window_button_container.x()

        # 标题在整个标题栏居中时，左右两边需要留出的空间
        # 取左右两边占用宽度的最大值，确保对称
        margin = max(left_width, right_width)

        # 可用于显示标题的最大宽度
        padding = 20
        available_width = bar_width - margin * 2 - padding

        # 如果可用宽度太小，隐藏标题避免遮挡按钮
        if available_width < 50:
            self.title_label.hide()
            return
        else:
            self.title_label.show()

        # Get font metrics and elide the text
        fm = QFontMetrics(self.title_label.font())
        elided_text = fm.elidedText(self._full_title, Qt.TextElideMode.ElideMiddle, available_width)

        # Set the text and tooltip
        self.title_label.setText(elided_text)
        self.title_label.setToolTip(self._full_title)

        # Adjust size and reposition
        self.title_label.adjustSize()
        title_width = self.title_label.width()
        title_height = self.title_label.height()

        # 在整个标题栏宽度内居中
        x = (bar_width - title_width) / 2
        y = (bar_height - title_height) / 2

        self.title_label.setGeometry(int(x), int(y), title_width, title_height)
    # ----------------------------------------------------------------

    def _start_system_move(self) -> bool:
        try:
            if self.parent_window.isMaximized():
                return False

            window_handle = self.parent_window.windowHandle()
            if window_handle is None:
                self.parent_window.winId()
                window_handle = self.parent_window.windowHandle()

            if window_handle is None:
                return False

            return bool(window_handle.startSystemMove())
        except Exception:
            return False

    def mousePressEvent(self, event: QMouseEvent):
        # Ignore drag handling when pressing interactive child widgets.
        child = self.childAt(event.position().toPoint())

        # Let button-like children handle their own mouse press events.
        if child is not None and isinstance(child, (QPushButton, QToolButton)):
            event.ignore()  # Delegate to child widget.
            return

        # Start system move first; fall back to manual drag logic.
        if event.button() == Qt.MouseButton.LeftButton:
            if self._start_system_move():
                self._mouse_pressed = False
                event.accept()
                return

            self._mouse_pressed = True
            self._mouse_press_pos = event.globalPosition().toPoint()
            self._window_pos_before_move = self.parent_window.pos()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._mouse_pressed and event.buttons() == Qt.MouseButton.LeftButton:
            try:
                global_pos = event.globalPosition().toPoint()
                delta = global_pos - self._mouse_press_pos
                self.parent_window.move(self._window_pos_before_move + delta)
                event.accept()
            except Exception as e:
                # 防止拖动时发生异常导致卡死
                self._mouse_pressed = False
                event.ignore()
        else:
            event.ignore()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._mouse_pressed = False
            event.accept()
        else:
            event.ignore()
            
    def _on_minimize_clicked(self):
        """处理最小化按钮点击"""
        # 先同步参数面板状态
        if hasattr(self.parent_window, 'parameter_panel'):
            from PySide6.QtCore import Qt
            self.parent_window.parameter_panel.sync_window_state(Qt.WindowState.WindowMinimized)
        # 再最小化窗口
        self.parent_window.showMinimized()

    def _toggle_maximize(self):
        # 简单直接的切换逻辑
        if self.parent_window.isMaximized():
            self.parent_window.showNormal()
        else:
            self.parent_window.showMaximized()

        # 立即更新图标，然后再用定时器确保状态同步
        self._update_maximize_icon(self.parent_window.windowState())

        # 使用定时器再次确保状态同步
        from PySide6.QtCore import QTimer
        QTimer.singleShot(100, lambda: self._update_maximize_icon(self.parent_window.windowState()))

    def _update_maximize_icon(self, state):
        # 直接检查窗口是否最大化
        is_maximized = self.parent_window.isMaximized()

        if is_maximized:
            self.maximize_button.setText(self.restore_char)
            self.maximize_button.setToolTip("向下还原")
        else:
            self.maximize_button.setText(self.maximize_char)
            self.maximize_button.setToolTip("最大化")

        # 强制刷新按钮显示
        self.maximize_button.update()

    def _toggle_topmost(self):
        """切换窗口置顶状态"""
        self._window_topmost = not self._window_topmost
        if self._window_topmost:
            self.parent_window.setWindowFlags(self.parent_window.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
            self.topmost_button.setToolTip("取消置顶")
        else:
            self.parent_window.setWindowFlags(self.parent_window.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint)
            self.topmost_button.setToolTip("窗口置顶")
        show_and_raise_widget(self.parent_window, log_prefix='标题栏置顶切换')

    def create_toolbar_button(self, action):
        """创建工具栏按钮"""
        button = QToolButton(self)
        button.setDefaultAction(action)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setFixedSize(28, 28)
        return button

    def setup_toolbar(self, main_window):
        """Sets up the custom toolbar with actions from main window."""
        # Create layout for the toolbar
        toolbar_layout = QHBoxLayout()
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(2)  # Compact spacing
        
        # Access actions from main window
        toggle_action = getattr(main_window, 'toggle_action', None)
        save_action = getattr(main_window, 'save_action', None)
        load_action = getattr(main_window, 'load_action', None)
        run_action = getattr(main_window, 'run_action', None)
        settings_action = getattr(main_window, 'global_settings_action', None)
        publish_action = getattr(main_window, 'publish_action', None)
        view_published_action = getattr(main_window, 'view_published_action', None)
        
        # Remove previous actions from their widgets (if any)
        for key, widget in self.action_widgets.items():
            if isinstance(widget, QAction):
                widget.setParent(None)
        # Clear the map
        self.action_widgets.clear()
        
        # Clear existing widgets (if any) from the toolbar layout
        while toolbar_layout.count():
            item = toolbar_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Create toggle button first (always visible)
        if toggle_action:
            toggle_btn = self.create_toolbar_button(toggle_action)
            toolbar_layout.addWidget(toggle_btn)
            self.action_widgets['toggle'] = toggle_btn
        
        # --- Add a spacer between toggle and file actions ---
        horizontal_spacer = QWidget()
        horizontal_spacer.setFixedWidth(8)  # 8px spacer
        toolbar_layout.addWidget(horizontal_spacer)
        
        # Create container for file actions (can be hidden)
        self.action_container = QWidget()
        action_container_layout = QHBoxLayout(self.action_container)
        action_container_layout.setContentsMargins(0, 0, 0, 0)
        action_container_layout.setSpacing(2)
        
        # Add save, load actions to container
        if save_action:
            save_btn = self.create_toolbar_button(save_action)
            action_container_layout.addWidget(save_btn)
            self.action_widgets['save'] = save_btn
        
        if load_action:
            load_btn = self.create_toolbar_button(load_action)
            action_container_layout.addWidget(load_btn)
            self.action_widgets['load'] = load_btn
        
        # Add container to toolbar
        toolbar_layout.addWidget(self.action_container)
        # Set initial visibility based on main_window.file_actions_visible
        self.action_container.setVisible(getattr(main_window, 'file_actions_visible', True))
        
        # Add a spacer to separate action groups
        horizontal_spacer2 = QWidget()
        horizontal_spacer2.setFixedWidth(15)  # 15px spacer
        toolbar_layout.addWidget(horizontal_spacer2)
        
        # Add publish and view published tasks actions
        if publish_action:
            publish_btn = self.create_toolbar_button(publish_action)
            toolbar_layout.addWidget(publish_btn)
            self.action_widgets['publish'] = publish_btn
        
        if view_published_action:
            view_published_btn = self.create_toolbar_button(view_published_action)
            toolbar_layout.addWidget(view_published_btn)
            self.action_widgets['view_published'] = view_published_btn
            
        # Add a spacer to separate action groups
        horizontal_spacer3 = QWidget()
        horizontal_spacer3.setFixedWidth(15)  # 15px spacer
        toolbar_layout.addWidget(horizontal_spacer3)
        
        # Add run action (always visible)
        if run_action:
            run_btn = self.create_toolbar_button(run_action)
            toolbar_layout.addWidget(run_btn)
            self.action_widgets['run'] = run_btn
        
        # Add global settings action
        if settings_action:
            settings_btn = self.create_toolbar_button(settings_action)
            toolbar_layout.addWidget(settings_btn)
            self.action_widgets['settings'] = settings_btn
        
        # Add spring to push everything to the left
        toolbar_layout.addStretch(1)
        
        # Set the toolbar layout
        self.toolbar.setLayout(toolbar_layout)
