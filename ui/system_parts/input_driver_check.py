"""启动后检查当前配置涉及的本地输入驱动（罗技运行时、Interception），必要时提示用户。"""

from __future__ import annotations

import logging

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

_LOGITECH_INSTALL_HINT = (
    "请安装指定版本后重启电脑和 LCA。\n"
    "指定版本：Logitech G HUB 2026.4，"
    "或 Logitech Gaming Software 9.02.65（二选一）。"
)


def _show_logitech_version_dialog(main_window, version_result) -> None:
    try:
        msg_box = QMessageBox(main_window)
        msg_box.setIcon(QMessageBox.Icon.Warning)
        msg_box.setWindowTitle("罗技输入驱动不可用")
        msg_box.setText(version_result.user_message())
        msg_box.setInformativeText(_LOGITECH_INSTALL_HINT)
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg_box.exec()
    except Exception as dialog_error:
        logging.error(f"显示罗技驱动版本提示失败: {dialog_error}")


def _show_driver_restart_dialog(main_window, prompt_config) -> None:
    try:
        title, message, informative_text = prompt_config
        msg_box = QMessageBox(main_window)
        msg_box.setIcon(QMessageBox.Icon.Information)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        msg_box.setInformativeText(informative_text)
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg_box.exec()
        logging.info("用户已确认重启提示")
    except Exception as e:
        logging.error(f"显示重启提示时出错: {e}")


def _check_logitech_runtime(main_window, config) -> None:
    from utils.input.logitech_runtime import (
        detect_logitech_runtime,
        is_logitech_ibinputsimulator_configured,
    )

    if not is_logitech_ibinputsimulator_configured(config):
        return
    logging.info("开始检查 Logitech 输入运行时...")
    version_result = detect_logitech_runtime()
    if version_result.compatible:
        logging.info(
            "罗技输入运行时检查通过: "
            f"type={version_result.send_type}, "
            f"version={version_result.detected_version}, "
            f"source={version_result.source}"
        )
        return
    logging.warning(version_result.user_message().replace("\n", " "))
    QTimer.singleShot(200, lambda: _show_logitech_version_dialog(main_window, version_result))


def _check_interception_driver(main_window, config) -> None:
    from utils.input_simulation.mode_utils import parse_foreground_backends, requires_interception_driver
    from utils.input.interception_installation_prompt import request_interception_installation

    execution_mode = str(config.get("execution_mode", "") or "").strip().lower()
    mouse_backend, keyboard_backend = parse_foreground_backends(config)

    logging.info("开始检查 Interception 驱动状态...")
    if not requires_interception_driver(
        execution_mode,
        mouse_backend=mouse_backend,
        keyboard_backend=keyboard_backend,
    ):
        logging.info(
            "当前启动配置不依赖 Interception，跳过驱动检查: "
            f"mode={execution_mode or 'unknown'}, mouse={mouse_backend}, keyboard={keyboard_backend}"
        )
        return

    # 未安装时只询问，不得在初始化链路中自动安装。
    try:
        from utils.input.interception_driver import get_driver

        driver = get_driver()
        if not driver.is_driver_registered():
            logging.info("Interception 驱动未安装，等待用户确认是否安装")
            QTimer.singleShot(1000, lambda: request_interception_installation(main_window, config))
            return

        if driver.initialize():
            # 保持驱动上下文，避免后续使用时重复初始化和DPI检测
            logging.info("Interception 驱动已安装且可用")
            return

        prompt_config = driver.get_restart_prompt_config()
        if prompt_config:
            logging.info("检测到驱动需要提示用户处理")
            QTimer.singleShot(2000, lambda: _show_driver_restart_dialog(main_window, prompt_config))
            logging.info("已安排显示驱动提示（延迟2秒）")
        else:
            logging.info("Interception 驱动未安装或初始化失败（未触发处理提示）")
    except Exception as driver_error:
        logging.info(f"驱动检查过程中出现异常: {driver_error}")


def check_input_driver_requirements(main_window) -> None:
    """检查罗技版本约束和 Interception 驱动状态；任何异常都不影响程序启动。"""
    try:
        config = getattr(main_window, "config", {}) or {}
        _check_logitech_runtime(main_window, config)
        _check_interception_driver(main_window, config)
    except Exception as e:
        logging.warning(f"检查 Interception 驱动时出错: {e}")


def schedule_input_driver_check(main_window, delay_ms: int = 500) -> None:
    """主窗口显示后延迟执行驱动检查，避免阻塞首屏。"""
    QTimer.singleShot(int(delay_ms), lambda: check_input_driver_requirements(main_window))
    logging.info(f"已安排输入驱动检查（延迟{int(delay_ms)}ms）")
