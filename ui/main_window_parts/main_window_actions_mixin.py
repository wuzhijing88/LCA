import logging

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QStyle

logger = logging.getLogger(__name__)


class MainWindowActionsMixin:
    def _create_actions(self):
        """Creates all QAction instances."""
        from .main_window_support import create_hourglass_icon, create_media_control_icon
        self.file_actions_visible = True # Initial state for toggled actions
        style = self.style() # Get style to access standard icons
        # --- Toggle Action (Icon + Text) ---
        toggle_icon = style.standardIcon(QStyle.StandardPixmap.SP_ToolBarHorizontalExtensionButton)
        self.toggle_action = QAction(toggle_icon, "选项", self)
        self.toggle_action.setToolTip("显示/隐藏功能按钮")
        self.toggle_action.triggered.connect(self.toggle_file_actions_visibility)
        # --- Save Action (Icon + Text) ---
        save_icon = style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        self.save_action = QAction(save_icon, "保存配置", self)
        self.save_action.setToolTip("保存当前工作流配置 (Ctrl+S)")
        self.save_action.setShortcut("Ctrl+S")
        self.save_action.triggered.connect(self._handle_save_action)
        self.save_action.setVisible(self.file_actions_visible)
        # --- Load Action (Icon + Text) ---
        load_icon = style.standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton)
        self.load_action = QAction(load_icon, "加载配置", self)
        self.load_action.setToolTip("从文件加载工作流配置")
        self.load_action.triggered.connect(self.load_workflow)
        self.load_action.setVisible(self.file_actions_visible)
        # --- New Blank Workflow Action (Icon + Text) ---
        new_icon = style.standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        self.new_workflow_action = QAction(new_icon, "新建工作流", self)
        self.new_workflow_action.setToolTip("创建空白工作流 (Ctrl+N)")
        self.new_workflow_action.setShortcut("Ctrl+N")
        self.new_workflow_action.triggered.connect(self.create_blank_workflow)
        self.new_workflow_action.setVisible(self.file_actions_visible)
        # --- Run Workflow Action (Icon + Text) ---
        # 这个按钮有三种状态：停止→运行→暂停
        # 停止状态：▶运行 → 点击启动
        # 运行状态：■停止 → 点击停止
        # 暂停状态：⏸恢复 → 点击恢复
        run_icon = create_media_control_icon('play', 20)
        self.run_action = QAction(run_icon, "运行所有任务", self)
        self.run_action.setToolTip("开始执行所有工作流 (F9)")
        self.run_action.triggered.connect(self._on_run_stop_button_clicked)
        self.run_action.setEnabled(True)
        self.run_action.setVisible(True)
        # --- Debug Run Action (Icon + Text) ---
        debug_icon = style.standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.debug_run_action = QAction(debug_icon, "调试运行", self)
        self.debug_run_action.setToolTip("启动中控软件进行调试运行")
        self.debug_run_action.triggered.connect(self.open_control_center)
        self.debug_run_action.setVisible(True)
        # --- Global Settings Action ---
        settings_icon = style.standardIcon(QStyle.StandardPixmap.SP_FileDialogListView)
        self.global_settings_action = QAction(settings_icon, "全局设置", self)
        self.global_settings_action.setToolTip("配置目标窗口、执行模式和自定义分辨率等全局选项")
        self.global_settings_action.triggered.connect(self.open_global_settings)
        # --- Global Timer Action ---
        self.timer_action = QAction(create_hourglass_icon(20), "定时设置", self)
        self.timer_action.setToolTip("定时停止 - 设置定时器，时间到后自动停止所有工作流")
        self.timer_action.triggered.connect(self.open_timer_dialog)
        # --- MODIFIED: Connect clear action to a confirmation method ---
        self.clear_action = QAction(QIcon.fromTheme("document-new", self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)), "清空工作流", self)
        self.clear_action.setToolTip("清空当前所有步骤和连接")
        # self.clear_action.triggered.connect(self.workflow_view.clear_scene) # OLD direct connection
        self.clear_action.triggered.connect(self.confirm_and_clear_workflow) # NEW connection
        # --- END MODIFICATION ---
        self.copy_action = QAction(QIcon.fromTheme("edit-copy"), "复制卡片", self)
        self.copy_action.setToolTip("复制选中的卡片")
        # 动态连接：通过lambda调用当前workflow_view的方法
        self.copy_action.triggered.connect(lambda: self.workflow_view.copy_selected_card() if self.workflow_view else None)
        # <<< END ADDED >>>
        self._refresh_theme_sensitive_action_icons()
    def _refresh_theme_sensitive_action_icons(self):
        """刷新标题栏中依赖主题色的动作图标。"""
        from .main_window_support import create_hourglass_icon, create_media_control_icon
        if hasattr(self, 'timer_action') and self.timer_action:
            self.timer_action.setIcon(create_hourglass_icon(20))
        if not (hasattr(self, 'run_action') and self.run_action):
            return
        button_text = (self.run_action.text() or "").strip()
        if button_text == "恢复":
            icon_type = 'pause'
        elif "停止" in button_text or "运行中" in button_text:
            icon_type = 'stop'
        else:
            icon_type = 'play'
        self.run_action.setIcon(create_media_control_icon(icon_type, 20))
    def toggle_file_actions_visibility(self):
        """Toggles the visibility of Add, Save and Load actions container in the custom title bar."""
        self.file_actions_visible = not self.file_actions_visible
        # Update visibility of QActions themselves (good practice)
        if self.save_action:
            self.save_action.setVisible(self.file_actions_visible)
        if self.load_action:
            self.load_action.setVisible(self.file_actions_visible)
        if hasattr(self, 'new_workflow_action') and self.new_workflow_action:
            self.new_workflow_action.setVisible(self.file_actions_visible)
        # Run action visibility is handled separately (always visible for now)
        # if self.run_action:
        #     self.run_action.setVisible(self.file_actions_visible)
        # Update visibility of the container in the title bar
        if hasattr(self, 'title_bar') and self.title_bar:
             self.title_bar.set_file_actions_visible(self.file_actions_visible)
        logger.debug(f"功能按钮可见性设置为: {self.file_actions_visible}")
