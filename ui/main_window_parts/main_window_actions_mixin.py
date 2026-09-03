import logging

from PySide6.QtGui import QAction

logger = logging.getLogger(__name__)

_TOOLBAR_ICON_SIZE = 22


class MainWindowActionsMixin:
    def _create_actions(self):
        """Creates all QAction instances."""
        from .main_window_support import (
            create_copy_toolbar_icon,
            create_export_standalone_icon,
            create_hourglass_icon,
            create_media_control_icon,
            create_monitor_toolbar_icon,
            create_new_toolbar_icon,
            create_open_toolbar_icon,
            create_save_toolbar_icon,
            create_settings_toolbar_icon,
            create_toggle_toolbar_icon,
        )

        self.file_actions_visible = True
        icon_size = _TOOLBAR_ICON_SIZE

        self.toggle_action = QAction(create_toggle_toolbar_icon(icon_size), "选项", self)
        self.toggle_action.setToolTip("显示/隐藏功能按钮")
        self.toggle_action.triggered.connect(self.toggle_file_actions_visibility)

        self.save_action = QAction(create_save_toolbar_icon(icon_size), "保存配置", self)
        self.save_action.setToolTip("保存当前工作流配置 (Ctrl+S)")
        self.save_action.setShortcut("Ctrl+S")
        self.save_action.triggered.connect(self._handle_save_action)
        self.save_action.setVisible(self.file_actions_visible)

        self.load_action = QAction(create_open_toolbar_icon(icon_size), "加载配置", self)
        self.load_action.setToolTip("从文件加载工作流配置")
        self.load_action.triggered.connect(self.load_workflow)
        self.load_action.setVisible(self.file_actions_visible)

        self.new_workflow_action = QAction(create_new_toolbar_icon(icon_size), "新建工作流", self)
        self.new_workflow_action.setToolTip("创建空白工作流 (Ctrl+N)")
        self.new_workflow_action.setShortcut("Ctrl+N")
        self.new_workflow_action.triggered.connect(self.create_blank_workflow)
        self.new_workflow_action.setVisible(self.file_actions_visible)

        self.export_standalone_action = QAction(
            create_export_standalone_icon(icon_size),
            "制作独立程序",
            self,
        )
        self.export_standalone_action.setToolTip("把当前工作流做成可双击运行的独立程序")
        self.export_standalone_action.triggered.connect(self.open_export_standalone_dialog)
        self.export_standalone_action.setVisible(self.file_actions_visible)

        self.run_action = QAction(create_media_control_icon("play", icon_size), "运行所有任务", self)
        self.run_action.setToolTip("开始执行所有工作流 (F9)")
        self.run_action.triggered.connect(self._on_run_stop_button_clicked)
        self.run_action.setEnabled(True)
        self.run_action.setVisible(True)

        self.debug_run_action = QAction(create_monitor_toolbar_icon(icon_size), "调试运行", self)
        self.debug_run_action.setToolTip("启动中控软件进行调试运行")
        self.debug_run_action.triggered.connect(self.open_control_center)
        self.debug_run_action.setVisible(True)

        self.global_settings_action = QAction(
            create_settings_toolbar_icon(icon_size),
            "全局设置",
            self,
        )
        self.global_settings_action.setToolTip("配置目标窗口、执行模式和自定义分辨率等全局选项")
        self.global_settings_action.triggered.connect(self.open_global_settings)

        self.timer_action = QAction(create_hourglass_icon(icon_size), "定时设置", self)
        self.timer_action.setToolTip("定时停止 - 设置定时器，时间到后自动停止所有工作流")
        self.timer_action.triggered.connect(self.open_timer_dialog)

        self.clear_action = QAction(create_new_toolbar_icon(icon_size), "清空工作流", self)
        self.clear_action.setToolTip("清空当前所有步骤和连接")
        self.clear_action.triggered.connect(self.confirm_and_clear_workflow)

        self.copy_action = QAction(create_copy_toolbar_icon(icon_size), "复制卡片", self)
        self.copy_action.setToolTip("复制选中的卡片")
        self.copy_action.triggered.connect(
            lambda: self.workflow_view.copy_selected_card() if self.workflow_view else None
        )

        self._refresh_theme_sensitive_action_icons()

    def _refresh_theme_sensitive_action_icons(self):
        """刷新标题栏中依赖主题色的动作图标。"""
        from .main_window_support import (
            create_export_standalone_icon,
            create_hourglass_icon,
            create_media_control_icon,
            create_monitor_toolbar_icon,
            create_new_toolbar_icon,
            create_open_toolbar_icon,
            create_save_toolbar_icon,
            create_settings_toolbar_icon,
            create_toggle_toolbar_icon,
        )

        icon_size = _TOOLBAR_ICON_SIZE
        mapping = (
            ("toggle_action", lambda: create_toggle_toolbar_icon(icon_size)),
            ("save_action", lambda: create_save_toolbar_icon(icon_size)),
            ("load_action", lambda: create_open_toolbar_icon(icon_size)),
            ("new_workflow_action", lambda: create_new_toolbar_icon(icon_size)),
            ("export_standalone_action", lambda: create_export_standalone_icon(icon_size)),
            ("debug_run_action", lambda: create_monitor_toolbar_icon(icon_size)),
            ("global_settings_action", lambda: create_settings_toolbar_icon(icon_size)),
            ("timer_action", lambda: create_hourglass_icon(icon_size)),
        )
        for attr, factory in mapping:
            action = getattr(self, attr, None)
            if action is not None:
                action.setIcon(factory())

        if not (hasattr(self, "run_action") and self.run_action):
            return
        button_text = (self.run_action.text() or "").strip()
        if button_text == "恢复":
            icon_type = "pause"
        elif "停止" in button_text or "运行中" in button_text:
            icon_type = "stop"
        else:
            icon_type = "play"
        self.run_action.setIcon(create_media_control_icon(icon_type, icon_size))

    def toggle_file_actions_visibility(self):
        """Toggles the visibility of Add, Save and Load actions container in the custom title bar."""
        self.file_actions_visible = not self.file_actions_visible
        if self.save_action:
            self.save_action.setVisible(self.file_actions_visible)
        if self.load_action:
            self.load_action.setVisible(self.file_actions_visible)
        if hasattr(self, "new_workflow_action") and self.new_workflow_action:
            self.new_workflow_action.setVisible(self.file_actions_visible)
        if hasattr(self, "export_standalone_action") and self.export_standalone_action:
            self.export_standalone_action.setVisible(self.file_actions_visible)
        if hasattr(self, "title_bar") and self.title_bar:
            self.title_bar.set_file_actions_visible(self.file_actions_visible)
        logger.debug(f"功能按钮可见性设置为: {self.file_actions_visible}")
