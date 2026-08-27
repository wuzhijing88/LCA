import logging

from PySide6.QtCore import QTimer
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QTabWidget, QVBoxLayout

from utils.window.window_coordinate_common import center_window_on_widget_screen
from utils.window.hwnd_utils import normalize_bound_windows_hwnds
from .global_settings_dialog_tabs_mixin import GlobalSettingsDialogTabsMixin
from .global_settings_dialog_window_mixin import GlobalSettingsDialogWindowMixin
from .global_settings_dialog_visibility_mixin import GlobalSettingsDialogVisibilityMixin
from .global_settings_dialog_save_mixin import GlobalSettingsDialogSaveMixin
from .global_settings_dialog_runtime_mixin import GlobalSettingsDialogRuntimeMixin
from .global_settings_dialog_window_crud_mixin import GlobalSettingsDialogWindowCrudMixin

logger = logging.getLogger(__name__)


class GlobalSettingsDialog(GlobalSettingsDialogTabsMixin, GlobalSettingsDialogVisibilityMixin, GlobalSettingsDialogWindowMixin, GlobalSettingsDialogSaveMixin, GlobalSettingsDialogWindowCrudMixin, GlobalSettingsDialogRuntimeMixin, QDialog):

    """A dialog for editing global application settings with modern styling."""
    MODE_DISPLAY_MAP = {
        'foreground_driver': "前台一模式",
        'foreground_py': "前台二模式",
        'background_sendmessage': "后台一模式",
        'background_postmessage': "后台二模式"
    }
    MODE_INTERNAL_MAP = {v: k for k, v in MODE_DISPLAY_MAP.items()}
    FOREGROUND_DRIVER_BACKEND_MAP = {
        "Interception": "interception",
        "IbInputSimulator": "ibinputsimulator",
    }
    FOREGROUND_DRIVER_BACKEND_REVERSE_MAP = {v: k for k, v in FOREGROUND_DRIVER_BACKEND_MAP.items()}
    IB_DRIVER_MAP = {
        "Logitech": "Logitech",
        "Razer": "Razer",
    }
    IB_DRIVER_REVERSE_MAP = {v: k for k, v in IB_DRIVER_MAP.items()}
    def __init__(self, current_config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("全局设置")
        self.setMinimumWidth(585)
        self.setMaximumWidth(712)
        self.setMinimumHeight(300)
        self.setMaximumHeight(680)  # 放宽高度上限，避免新增驱动下拉后裁切
        self.resize(638, 460)  # 提高初始高度，减少首次显示不全
        self.current_config = current_config
        # 窗口行为默认值兜底（旧配置缺失键时默认启用）
        self.current_config.setdefault('enable_canvas_grid', True)
        self.current_config.setdefault('enable_card_snap', True)
        self.current_config.setdefault('enable_parameter_panel_snap', True)
        self.current_config.setdefault('enable_floating_status_window', True)
        self.current_config.setdefault('enable_connection_line_animation', True)
        self.bound_windows = current_config.get('bound_windows', [])  # 绑定的窗口列表
        if not isinstance(self.bound_windows, list):
            self.bound_windows = []
        normalize_bound_windows_hwnds(self.bound_windows)
        self.window_binding_mode = current_config.get('window_binding_mode', 'single')  # 'single' 或 'multiple'
        # 调试：记录初始化时的绑定窗口信息
        logger.info(f"GlobalSettingsDialog初始化: 加载了 {len(self.bound_windows)} 个绑定窗口")
        for i, window in enumerate(self.bound_windows):
            title = window.get('title', 'Unknown')
            hwnd = window.get('hwnd', 'N/A')
            logger.info(f"  {i+1}. {title} (HWND: {hwnd})")
        # --- Main Layout ---
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(10, 10, 10, 10)
        # 创建标签页控件
        self.tab_widget = QTabWidget()
        self.tab_widget.setObjectName("globalSettingsTabs")
        self.tab_widget.setDocumentMode(True)
        self.tab_widget.tabBar().setDrawBase(False)
        self.tab_widget.setStyleSheet("""
            QTabWidget#globalSettingsTabs::pane {
                border: none;
                top: 0px;
                margin-top: 0px;
            }
            QTabWidget#globalSettingsTabs QTabBar::tab {
                padding: 5px 14px;
                min-width: 68px;
                font-weight: 400;
            }
            QTabWidget#globalSettingsTabs QTabBar::tab:selected {
                font-weight: 400;
            }
            QTabWidget#globalSettingsTabs QTabBar::tab:!selected {
                margin-top: 1px;
            }
        """)
        main_layout.addWidget(self.tab_widget)
        # --- 创建各个标签页 ---
        self._create_window_tab()
        self._create_execution_tab()
        self._create_hotkey_tab()
        self._create_other_tab()
        self._create_about_tab()
        # --- Dialog Buttons ---
        button_box = QDialogButtonBox()
        button_layout = QHBoxLayout()
        button_layout.addStretch(1)
        ok_button = button_box.addButton("确定", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_button = button_box.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        button_layout.addWidget(button_box)
        main_layout.addLayout(button_layout)
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        # 设置按钮对象名称用于样式
        ok_button.setObjectName("ok_button")
        cancel_button.setObjectName("cancel_button")
        # --- Connect signals ---
        # 窗口选择下拉框信号 - 选择窗口后自动绑定单个窗口
        self.window_select_combo.activated.connect(self._on_window_selected)
        # 延迟加载窗口列表 - 只在用户点击下拉框时加载
        def on_combo_pressed():
            if not self._window_list_loaded:
                self._refresh_window_select_combo()
                self._window_list_loaded = True
        # 使用 showPopup 事件来触发加载
        original_showPopup = self.window_select_combo.showPopup
        def delayed_showPopup():
            if not self._window_list_loaded:
                self._refresh_window_select_combo()
                self._window_list_loaded = True
            original_showPopup()
        self.window_select_combo.showPopup = delayed_showPopup
        # 多个窗口模式信号
        self.batch_add_button.clicked.connect(self._start_window_picker)  # 启动窗口选择工具
        self.remove_window_button.clicked.connect(self._remove_selected_window)
        # 初始化窗口选择下拉框 - 只显示提示文本，不加载窗口列表
        self.window_select_combo.clear()
        self.window_select_combo.addItem("-- 点击展开选择窗口 --")
        # 初始化界面状态
        self._load_bound_windows()
        # 在初始化时检查窗口状态
        self._check_and_cleanup_closed_windows()
        self._update_execution_mode_visibility()
        # 强制刷新布局，使用延迟确保Qt事件循环完成布局计算
        def force_layout_refresh():
            if hasattr(self, 'exec_tab'):
                # 强制父布局重新计算
                self.exec_tab.layout().activate()
                self.exec_tab.layout().update()
                # 更新所有相关控件的几何形状
                self.exec_tab.updateGeometry()
                self.exec_tab.update()
                # 调整对话框大小
                self.adjustSize()
        QTimer.singleShot(100, force_layout_refresh)
        QTimer.singleShot(0, self._recenter_to_parent_screen)
        # --- 样式由主题管理器统一管理，不再使用硬编码样式 ---

    def _recenter_to_parent_screen(self) -> None:
        center_window_on_widget_screen(self, self.parentWidget())
    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._recenter_to_parent_screen)

            # 不抛出异常，避免崩溃

            # 不抛出异常，避免崩溃

    # 添加兼容方法，对应open_global_settings调用

    # 删除不再需要的单窗口相关方法
    # 删除不再需要的_get_child_windows方法
