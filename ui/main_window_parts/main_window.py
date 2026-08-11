from typing import Any, Dict

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMainWindow

from ..global_settings_parts.global_settings_dialog import GlobalSettingsDialog
from .main_window_support import (
    CenteredTextDelegate,
    CustomDropdown,
    FullBleedListWidget,
    NoWheelDoubleSpinBox,
    NoWheelSpinBox,
    QComboBox,
    RoundedPopupFrame,
    _safe_get_win_msg,
    create_hourglass_icon,
    create_media_control_icon,
    format_time_display,
    get_disabled_text_color,
    get_error_color,
    get_info_color,
    get_secondary_text_color,
    get_success_color,
    get_theme_color,
    is_dark_theme,
    native_point_to_qt_global,
    normalize_execution_mode,
    normalize_execution_mode_setting,
    parse_execution_mode,
)
from .main_window_timer_dialog_mixin import MainWindowTimerDialogMixin
from .main_window_timer_runtime_mixin import MainWindowTimerRuntimeMixin
from .main_window_hotkey_mixin import MainWindowHotkeyMixin
from .main_window_global_settings_mixin import MainWindowGlobalSettingsMixin
from .main_window_execution_state_mixin import MainWindowExecutionStateMixin
from .main_window_save_mixin import MainWindowSaveMixin
from .main_window_parameter_panel_mixin import MainWindowParameterPanelMixin
from .main_window_workflow_switch_mixin import MainWindowWorkflowSwitchMixin
from .main_window_multi_window_runtime_mixin import MainWindowMultiWindowRuntimeMixin
from .main_window_run_workflow_mixin import MainWindowRunWorkflowMixin
from .main_window_execution_helper_mixin import MainWindowExecutionHelperMixin
from .main_window_init_state_mixin import MainWindowInitStateMixin
from .main_window_close_mixin import MainWindowCloseMixin
from .main_window_ui_setup_mixin import MainWindowUiSetupMixin
from .main_window_actions_mixin import MainWindowActionsMixin
from .main_window_window_binding_mixin import MainWindowWindowBindingMixin
from .main_window_window_validation_mixin import MainWindowWindowValidationMixin
from .main_window_execution_flow_mixin import MainWindowExecutionFlowMixin
from .main_window_dialog_mixin import MainWindowDialogMixin
from .main_window_platform_mixin import MainWindowPlatformMixin
from .main_window_executor_cleanup_mixin import MainWindowExecutorCleanupMixin
from .main_window_workflow_canvas_mixin import MainWindowWorkflowCanvasMixin
from .main_window_favorites_mixin import MainWindowFavoritesMixin
from .main_window_screenshot_engine_mixin import MainWindowScreenshotEngineMixin
from .main_window_favorites_batch_mixin import MainWindowFavoritesBatchMixin
from .main_window_dpi_mixin import MainWindowDpiMixin
from .main_window_status_mixin import MainWindowStatusMixin
from .main_window_floating_status_mixin import MainWindowFloatingStatusMixin


class MainWindow(
    MainWindowTimerDialogMixin,
    MainWindowTimerRuntimeMixin,
    MainWindowHotkeyMixin,
    MainWindowGlobalSettingsMixin,
    MainWindowExecutionStateMixin,
    MainWindowSaveMixin,
    MainWindowParameterPanelMixin,
    MainWindowWorkflowSwitchMixin,
    MainWindowMultiWindowRuntimeMixin,
    MainWindowRunWorkflowMixin,
    MainWindowExecutionHelperMixin,
    MainWindowInitStateMixin,
    MainWindowCloseMixin,
    MainWindowUiSetupMixin,
    MainWindowActionsMixin,
    MainWindowWindowBindingMixin,
    MainWindowWindowValidationMixin,
    MainWindowExecutionFlowMixin,
    MainWindowDialogMixin,
    MainWindowPlatformMixin,
    MainWindowExecutorCleanupMixin,
    MainWindowWorkflowCanvasMixin,
    MainWindowFavoritesMixin,
    MainWindowScreenshotEngineMixin,
    MainWindowFavoritesBatchMixin,
    MainWindowDpiMixin,
    MainWindowStatusMixin,
    MainWindowFloatingStatusMixin,
    QMainWindow,
):
    """Main application window."""

    hotkey_start_signal = Signal()
    hotkey_stop_signal = Signal()
    windowShown = Signal()

    def __init__(
        self,
        task_modules: Dict[str, Any],
        initial_config: dict,
        save_config_func,
        images_dir: str,
        task_state_manager=None,
    ):
        super().__init__()

        self._verify_main_window_registration()
        self._initialize_main_window_core_state(
            task_modules=task_modules,
            initial_config=initial_config,
            save_config_func=save_config_func,
            images_dir=images_dir,
            task_state_manager=task_state_manager,
        )
        self._setup_main_window_ui()
        self._finalize_main_window_startup()
