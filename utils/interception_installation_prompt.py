"""User-consented installation flow for the Interception system driver."""

from __future__ import annotations

import logging
from typing import Mapping, Optional

from utils.input_simulation.mode_utils import (
    parse_foreground_backends,
    requires_interception_driver,
)


logger = logging.getLogger(__name__)

# Confirmed by the Interception maintainer's public device-index discussions.
INTERCEPTION_DEVICE_RISK_TEXT = (
    "重要风险提示：\n"
    "Interception 是系统级键盘/鼠标过滤驱动。其公开版本只处理 Windows 内部编号 "
    "KbdClass0–9 和 MouClass0–9。\n\n"
    "蓝牙键鼠休眠或重连、USB 设备反复插拔、无线接收器断连以及 KVM 切换，"
    "都可能让 Windows 继续增加内部设备编号。超过驱动限制后，键盘或鼠标可能显示已连接，"
    "但完全没有输入，通常需要重启电脑才能恢复；若重启后仍未恢复，需要卸载该驱动并再次重启。\n\n"
    "使用蓝牙键鼠或经常断连、热插拔输入设备时，不建议安装 Interception。"
)


def is_interception_required_by_config(config: Optional[Mapping[str, object]]) -> bool:
    values = dict(config or {})
    execution_mode = str(values.get("execution_mode", "") or "").strip().lower()
    mouse_backend, keyboard_backend = parse_foreground_backends(values)
    return requires_interception_driver(
        execution_mode,
        mouse_backend=mouse_backend,
        keyboard_backend=keyboard_backend,
    )


def request_interception_installation(parent, config: Optional[Mapping[str, object]]) -> str:
    """Ask for explicit consent and install only after the user chooses Install."""
    if not is_interception_required_by_config(config):
        return "not_required"

    from PySide6.QtWidgets import QMessageBox
    from utils.interception_driver import INSTALLER_PATH, get_driver

    driver = get_driver()
    if driver.is_driver_registered():
        return "already_installed"

    import os

    if not os.path.isfile(INSTALLER_PATH):
        QMessageBox.warning(
            parent,
            "缺少 Interception 安装程序",
            "当前配置选择了 Interception，但本地安装程序不存在。\n\n"
            f"缺少文件：{INSTALLER_PATH}\n\n"
            "驱动不会被安装，请改用其他前台输入驱动。",
        )
        return "installer_missing"

    message_box = QMessageBox(parent)
    message_box.setIcon(QMessageBox.Icon.Warning)
    message_box.setWindowTitle("是否安装 Interception 驱动？")
    message_box.setText(
        "当前前台输入配置选择了 Interception，但系统尚未安装该驱动。\n"
        "只有你明确同意后，LCA 才会启动驱动安装程序。"
    )
    message_box.setInformativeText(INTERCEPTION_DEVICE_RISK_TEXT)
    message_box.setStandardButtons(
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )
    message_box.setButtonText(QMessageBox.StandardButton.Yes, "安装")
    message_box.setButtonText(QMessageBox.StandardButton.No, "取消")
    message_box.setDefaultButton(QMessageBox.StandardButton.No)
    message_box.setEscapeButton(QMessageBox.StandardButton.No)

    if message_box.exec() != QMessageBox.StandardButton.Yes:
        logger.info("用户拒绝安装 Interception 驱动")
        return "declined"

    logger.info("用户已同意安装 Interception 驱动")
    install_result = driver.install_driver()
    if install_result in ("installed", "already_installed"):
        restart_box = QMessageBox(parent)
        restart_box.setIcon(QMessageBox.Icon.Information)
        restart_box.setWindowTitle("Interception 安装完成")
        restart_box.setText("驱动安装程序已执行完成，重启计算机后才能生效。")
        restart_box.setInformativeText(
            "请先保存当前工作，然后重启 Windows。\n"
            "重启前 LCA 不会尝试使用新安装的 Interception 驱动。\n\n"
            "再次提醒：蓝牙键鼠休眠或反复重连可能触发设备编号限制，造成键鼠无输入。"
        )
        restart_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        restart_box.exec()
        return install_result

    if install_result == "cancelled":
        QMessageBox.information(
            parent,
            "已取消安装",
            "管理员授权已取消，Interception 驱动没有安装。",
        )
        return install_result

    if install_result == "timeout":
        detail = "等待安装程序完成超时。请确认安装窗口是否仍在运行；不要重复安装。"
    elif install_result == "installer_missing":
        detail = f"本地安装程序不存在：{INSTALLER_PATH}"
    else:
        detail = "安装程序执行失败，Interception 驱动没有完成安装。"

    QMessageBox.critical(parent, "Interception 安装失败", detail)
    return install_result


__all__ = [
    "INTERCEPTION_DEVICE_RISK_TEXT",
    "is_interception_required_by_config",
    "request_interception_installation",
]
