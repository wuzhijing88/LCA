# -*- coding: utf-8 -*-
"""设置页「验证授权」：在后台线程起一个临时插件宿主做 Ver + Reg，结果通过信号回到 UI 线程。"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal

from utils.plugin.runtime import AuthProbeResult, probe_plugin_authorization

logger = logging.getLogger(__name__)


class PluginAuthProbeBridge(QObject):
    finished = Signal(bool, str)


def start_plugin_auth_probe(
    owner,
    reg_code: str,
    extra_code: str,
    on_finished: Callable[[bool, str], None],
) -> Optional[threading.Thread]:
    """异步验证注册码；同一 owner 上未完成的验证会被忽略，避免重复注册。"""
    running = getattr(owner, "_plugin_auth_probe_thread", None)
    if running is not None and running.is_alive():
        return None

    bridge = getattr(owner, "_plugin_auth_probe_bridge", None)
    if bridge is None:
        bridge = PluginAuthProbeBridge(owner)
        owner._plugin_auth_probe_bridge = bridge
    try:
        bridge.finished.disconnect()
    except (TypeError, RuntimeError):
        pass
    bridge.finished.connect(on_finished)

    def _worker() -> None:
        try:
            result: AuthProbeResult = probe_plugin_authorization(reg_code, extra_code)
        except Exception as exc:  # noqa: BLE001
            logger.debug("插件授权验证异常", exc_info=True)
            result = AuthProbeResult(False, f"{exc.__class__.__name__}: {exc}")
        bridge.finished.emit(bool(result.ok), str(result.message or ""))

    worker = threading.Thread(target=_worker, name="plugin-auth-probe", daemon=True)
    owner._plugin_auth_probe_thread = worker
    worker.start()
    return worker
