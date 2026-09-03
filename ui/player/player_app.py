from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

from app_core.app_runtime_bootstrap import (
    configure_application_icon,
    connect_main_window_runtime_bindings,
    run_qt_event_loop,
)
from app_core.config_store import save_config
from app_core.player.loader import load_player_package
from app_core.player.runtime_config import apply_player_runtime_config
from ui.player.player_window import PlayerWindow
from utils.app_paths import get_resource_path

logger = logging.getLogger(__name__)


def _player_overlay_qss(is_dark: bool) -> str:
    """运行窗内容区样式；外框/标题栏由 player_chrome.player_shell_qss 负责。"""
    # 注意：自定义界面按钮不要在此强制 min-height/字号，否则会比预览/设计尺寸大一圈。
    # 默认模板按钮挂在 #PlayerBodyLegacy 下，仍可保留较大触控尺寸。
    if is_dark:
        return """
#PlayerAbout { color: #b0b0b0; font-size: 10pt; }
#PlayerStatusDot { font-size: 14pt; color: #8a8a8a; }
#PlayerStatusDot[state="running"] { color: #4caf50; }
#PlayerStatusDot[state="paused"] { color: #ffb74d; }
#PlayerStatusDot[state="idle"] { color: #8a8a8a; }
#PlayerStatusLabel { font-size: 13pt; font-weight: 600; }
#PlayerLogTitle { color: #b0b0b0; font-size: 10pt; }
#PlayerLogView {
    border: none;
    border-radius: 4px;
    padding: 4px;
    background: transparent;
    min-height: 80px;
}
#PlayerHotkeyHint { color: #888888; font-size: 9pt; }
#PlayerBodyLegacy #PlayerStartButton,
#PlayerBodyLegacy #PlayerPauseButton,
#PlayerBodyLegacy #PlayerStopButton,
#PlayerBodyLegacy #PlayerBindButton {
    min-height: 36px;
    font-size: 11pt;
    border-radius: 6px;
}
#PlayerBindButtonFloating {
    padding: 2px 10px;
    font-size: 9pt;
    border-radius: 4px;
    background: rgba(40, 40, 40, 0.75);
    color: #e0e0e0;
    border: 1px solid rgba(255, 255, 255, 0.18);
}
"""
    return """
#PlayerAbout { color: #666666; font-size: 10pt; }
#PlayerStatusDot { font-size: 14pt; color: #9e9e9e; }
#PlayerStatusDot[state="running"] { color: #2e7d32; }
#PlayerStatusDot[state="paused"] { color: #ef6c00; }
#PlayerStatusDot[state="idle"] { color: #9e9e9e; }
#PlayerStatusLabel { font-size: 13pt; font-weight: 600; }
#PlayerLogTitle { color: #666666; font-size: 10pt; }
#PlayerLogView {
    border: none;
    border-radius: 4px;
    padding: 4px;
    background: transparent;
    min-height: 80px;
}
#PlayerHotkeyHint { color: #888888; font-size: 9pt; }
#PlayerBodyLegacy #PlayerStartButton,
#PlayerBodyLegacy #PlayerPauseButton,
#PlayerBodyLegacy #PlayerStopButton,
#PlayerBodyLegacy #PlayerBindButton {
    min-height: 36px;
    font-size: 11pt;
    border-radius: 6px;
}
#PlayerBindButtonFloating {
    padding: 2px 10px;
    font-size: 9pt;
    border-radius: 4px;
    background: rgba(255, 255, 255, 0.88);
    color: #333333;
    border: 1px solid rgba(0, 0, 0, 0.12);
}
"""


def run_player(
    *,
    app,
    package_dir,
    config,
    tooltip_manager,
    system_tray,
    task_state_manager,
    log_maintenance_loop_factory,
    cleanup_runtime_state_variables_cb,
    exit_cleanup_join_timeout_sec: float,
) -> int:
    package = load_player_package(package_dir)
    from app_core.player.package import resolve_player_layout

    if resolve_player_layout(package.ui) == "tray":
        # 托盘形态由播放器自己建图标，避免再挂一层编辑器托盘。
        system_tray = None
    config = apply_player_runtime_config(config, package.runtime_config)
    if package.runtime_config:
        try:
            save_config(config)
        except Exception:
            logger.warning("写入独立程序执行配置失败", exc_info=True)
        logger.info(
            "独立程序已套用导出时的执行配置: engine=%s mode=%s",
            config.get("screenshot_engine"),
            config.get("execution_mode"),
        )
    logger.info("独立程序包已加载: %s", package.package_dir)

    try:
        from themes import get_theme_manager

        theme_manager = get_theme_manager()
        theme_name = str(package.ui.get("theme") or "auto")
        theme_manager.apply_theme(app, theme_name)
        if tooltip_manager is not None:
            tooltip_manager.set_theme(theme_manager.get_current_theme())
        app.setStyleSheet(app.styleSheet() + "\n" + _player_overlay_qss(theme_manager.is_dark_mode()))
    except Exception as exc:
        logger.warning("独立程序应用主题失败: %s", exc)

    icon_path = get_resource_path("icon.ico")
    if Path(icon_path).is_file():
        app.setWindowIcon(QIcon(icon_path))
    else:
        configure_application_icon(app)

    window = PlayerWindow(package, config)
    connect_main_window_runtime_bindings(
        task_state_manager=task_state_manager,
        main_window=window,
        system_tray=system_tray,
        queued_connection=Qt.ConnectionType.QueuedConnection,
    )
    window.maybe_auto_start()

    from app_core.app_runtime_bootstrap import start_log_maintenance_loop

    log_maintenance_loop = start_log_maintenance_loop(app, log_maintenance_loop_factory)
    return run_qt_event_loop(
        app=app,
        log_maintenance_loop=log_maintenance_loop,
        task_state_manager=task_state_manager,
        main_window=window,
        system_tray=system_tray,
        cleanup_runtime_state_variables_cb=cleanup_runtime_state_variables_cb,
        exit_cleanup_join_timeout_sec=exit_cleanup_join_timeout_sec,
    )
