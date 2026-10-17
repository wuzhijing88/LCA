# -*- coding: utf-8 -*-
"""桌面分身会话：启用 Child Session、连接 RDP。"""

from __future__ import annotations

import logging
from typing import Any, Callable, Mapping, Optional

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from utils.child_session import native as child_native
from utils.child_session.launcher import launch_elevated
from utils.child_session.rdp_host import (
    ChildSessionConnectionFailedEventArgs,
    RdpActiveXHost,
)
from utils.child_session.ownership import ChildSessionLease
from utils.child_session.settings import (
    copy_child_session_config,
    normalize_child_session_config,
    position_dict,
)
logger = logging.getLogger(__name__)

CONNECTION_TIMEOUT_MS = 60_000
INITIAL_CONNECTION_RETRY_COUNT = 3
RDP_SETTINGS_RECONNECT_RETRY_COUNT = 2
ERROR_TIMEOUT = 1460
STATUS_TICK_MS = 500

RDP_SETTING_NONE = 0
RDP_SETTING_SHORTCUTS = 1
RDP_SETTING_AUDIO = 2


class _PrepareWorker(QThread):
    prepared = Signal()
    failed = Signal(str)
    status = Signal(str)

    def cancel(self) -> None:
        self.requestInterruption()

    def run(self) -> None:
        try:
            self.status.emit("正在启用 Child Session")
            child_native.enable_child_sessions()
            if self.isInterruptionRequested():
                return
            logger.info("Child Session 已启用=%s", child_native.is_child_sessions_enabled())
            leftover = child_native.try_get_child_session_id()
            if leftover is not None:
                if self.isInterruptionRequested():
                    return
                self.status.emit("正在注销上次留下的桌面分身")
                try:
                    child_native.terminate_child_session(wait=True)
                except Exception as exc:
                    self.failed.emit("上次桌面分身未正常注销，无法重新连接：" + str(exc))
                    return
            self.prepared.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class _LogoffWorker(QThread):
    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.session_id = None
        self.error = ""

    def run(self) -> None:
        try:
            self.session_id = child_native.terminate_child_session(wait=True)
        except Exception as exc:
            self.error = str(exc)


class ChildSessionService(QObject):
    state_changed = Signal()
    connection_failed = Signal(object)
    start_failed = Signal(str)
    system_shortcuts_reconnect_completed = Signal()
    audio_reconnect_completed = Signal()
    logoff_finished = Signal(object)
    logoff_failed = Signal(str)

    def __init__(
        self,
        rdp_host: RdpActiveXHost,
        config: dict[str, Any],
        save_config: Callable[[Mapping[str, Any]], None],
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._rdp_host = rdp_host
        self._config = config
        self._save_config = save_config
        self._settings = copy_child_session_config(config)
        self._status_text = "桌面分身尚未启动"
        self._last_operation_message: Optional[str] = None
        self._initial_retries_remaining = 0
        self._connection_retry_in_progress = False
        self._pending_rdp_setting_changes = RDP_SETTING_NONE
        self._rdp_settings_retries_remaining = 0
        self._rdp_settings_retry_in_progress = False
        self._status_tick_in_progress = False
        self._disposed = False
        self._launch_busy = False
        self._waiting_for_connection = False
        self._retry_kind = ""
        self._logoff_requested = False
        self._logoff_disconnect_sent = False
        self._logoff_worker_started = False
        self._dispose_after_logoff = False
        self._exit_watch_started = False
        self._prepare_worker: Optional[_PrepareWorker] = None
        self._logoff_worker: Optional[_LogoffWorker] = None
        self._session_lease = ChildSessionLease()

        self._status_timer = QTimer(self)
        self._status_timer.setInterval(STATUS_TICK_MS)
        self._status_timer.timeout.connect(self._on_status_timer_tick)
        self._status_timer.start()

        self._connection_timeout_timer = QTimer(self)
        self._connection_timeout_timer.setSingleShot(True)
        self._connection_timeout_timer.timeout.connect(self._on_connection_timeout)

        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._on_retry_timer)

        self._rdp_host.connection_failed.connect(self._on_rdp_connection_failed)
        self._rdp_host.login_completed.connect(self._on_rdp_login_completed)
        self._rdp_host.desktop_update_failed.connect(self._on_desktop_update_failed)
        self._rdp_host.desktop_update_succeeded.connect(self._on_desktop_update_succeeded)
        self._rdp_host.transport_connected.connect(self._on_transport_connected)
        self.refresh_state()

    @property
    def status_text(self) -> str:
        return self._status_text

    @property
    def settings(self) -> dict[str, Any]:
        return self._settings

    @property
    def connected_state(self) -> int:
        return int(self._rdp_host.connected_state)

    @property
    def child_session_id(self) -> Optional[int]:
        session_id = child_native.try_get_child_session_id()
        if session_id is None:
            return None
        if not self._session_lease.held and not self._session_lease.acquire():
            return None
        return session_id

    @property
    def send_system_shortcuts_to_remote(self) -> bool:
        return bool(self._settings["send_system_shortcuts_to_remote"])

    @property
    def audio_muted(self) -> bool:
        return bool(self._settings["audio_muted"])

    @property
    def smart_sizing_enabled(self) -> bool:
        return bool(self._settings["smart_sizing_enabled"])

    @property
    def keep_aspect_ratio(self) -> bool:
        return bool(self._settings["keep_aspect_ratio"])

    @property
    def topmost_enabled(self) -> bool:
        return bool(self._settings["topmost_enabled"])

    @property
    def block_physical_mouse(self) -> bool:
        return bool(self._settings["block_physical_mouse"])

    @property
    def desktop_width(self) -> int:
        return int(self._settings["desktop_width"])

    @property
    def desktop_height(self) -> int:
        return int(self._settings["desktop_height"])

    def is_rdp_wrapper_enabled(self) -> bool:
        return child_native.is_rdp_wrapper_enabled()

    def start(self) -> None:
        self._throw_if_disposed()
        if self.connected_state in (1, 2):
            return
        worker = self._prepare_worker
        if worker is not None and worker.isRunning():
            return
        if not self._session_lease.acquire():
            raise RuntimeError("当前已有其他 LCA 实例正在使用桌面分身。")
        self._waiting_for_connection = True
        self.refresh_state("正在准备桌面分身")
        worker = _PrepareWorker(self)
        worker.prepared.connect(self._on_prepare_finished)
        worker.failed.connect(self._on_prepare_failed)
        worker.status.connect(self.refresh_state)
        worker.finished.connect(self._on_prepare_worker_finished)
        self._prepare_worker = worker
        try:
            worker.start()
        except Exception:
            self._prepare_worker = None
            self._session_lease.release()
            raise

    def set_desktop_resolution(self, width: int, height: int) -> None:
        self._throw_if_disposed()
        from utils.child_session.settings import normalize_child_session_config

        current = {
            "desktop_width": self.desktop_width,
            "desktop_height": self.desktop_height,
        }
        updated = normalize_child_session_config(
            {"desktop_width": width, "desktop_height": height}
        )
        if (
            updated["desktop_width"] == current["desktop_width"]
            and updated["desktop_height"] == current["desktop_height"]
        ):
            return
        self._settings["desktop_width"] = updated["desktop_width"]
        self._settings["desktop_height"] = updated["desktop_height"]
        self._settings["smart_sizing_enabled"] = True
        label = f"{updated['desktop_width']} × {updated['desktop_height']}"
        if self.connected_state == 0:
            self._rdp_host.set_smart_sizing(True)
            self.refresh_state(f"桌面分辨率已设为 {label}，将在下次连接时生效")
        else:
            self.refresh_state(f"正在将桌面分辨率调整为 {label}")
            self._rdp_host.apply_desktop_size(updated["desktop_width"], updated["desktop_height"])
        self._remember_settings()

    def set_smart_sizing(self, enabled: bool) -> None:
        self._throw_if_disposed()
        self._rdp_host.set_smart_sizing(bool(enabled))
        self._settings["smart_sizing_enabled"] = bool(enabled)
        self.refresh_state("窗口显示模式已切换为自适应" if enabled else "窗口显示模式已切换为 1:1")
        self._remember_settings()

    def set_keep_aspect_ratio(self, enabled: bool) -> None:
        self._throw_if_disposed()
        self._settings["keep_aspect_ratio"] = bool(enabled)
        self.refresh_state("桌面分身窗口将保持宽高比" if enabled else "桌面分身窗口不再保持宽高比")
        self._remember_settings()

    def set_topmost(self, enabled: bool) -> None:
        self._throw_if_disposed()
        self._settings["topmost_enabled"] = bool(enabled)
        self.refresh_state("桌面分身窗口已置顶" if enabled else "桌面分身窗口已取消置顶")
        self._remember_settings()

    def set_block_physical_mouse(self, enabled: bool) -> None:
        self._throw_if_disposed()
        enabled = bool(enabled)
        self._settings["block_physical_mouse"] = enabled
        self._rdp_host.set_block_physical_mouse(enabled)
        if enabled:
            message = "已屏蔽物理鼠标"
        else:
            message = "已恢复物理鼠标操作，当前使用普通鼠标"
        self.refresh_state(message)
        self._remember_settings()

    def set_send_system_shortcuts_to_remote(self, enabled: bool) -> bool:
        self._throw_if_disposed()
        if self.send_system_shortcuts_to_remote == bool(enabled):
            return False
        self._settings["send_system_shortcuts_to_remote"] = bool(enabled)
        self._rdp_host.set_send_system_shortcuts_to_remote(bool(enabled))
        target = "桌面分身" if enabled else "本机"
        applied = self._reconnect_for_rdp_setting(
            RDP_SETTING_SHORTCUTS,
            f"系统组合键已改为在{target}生效",
        )
        self._remember_settings()
        return applied

    def set_audio_muted(self, muted: bool) -> bool:
        self._throw_if_disposed()
        if self.audio_muted == bool(muted):
            return False
        self._settings["audio_muted"] = bool(muted)
        self._rdp_host.set_audio_muted(bool(muted))
        self.refresh_state("桌面分身声音已关闭" if muted else "桌面分身声音已开启")
        self._remember_settings()
        return True

    def store_window_position(self, key: str, left: int, top: int) -> None:
        self._throw_if_disposed()
        if key not in ("normal_window_position", "small_window_position"):
            raise ValueError(f"未知的窗口位置键: {key}")
        self._settings[key] = position_dict(left, top)
        self._persist_settings()

    def launch_executable(self, executable_path: str) -> None:
        self._throw_if_disposed()
        session_id = self._require_child_session_id()
        if self._launch_busy:
            raise RuntimeError("正在启动子进程，请稍候。")
        self._launch_busy = True
        try:
            import os

            self.refresh_state(f"正在以管理员权限启动 {os.path.basename(executable_path)}")
            launch_elevated(session_id, executable_path)
            self.refresh_state(
                f"已在桌面分身中以管理员权限启动 {os.path.basename(executable_path)}"
            )
        finally:
            self._launch_busy = False

    def logoff_and_disconnect(self) -> None:
        self._throw_if_disposed()
        if self._logoff_requested:
            return
        if self.child_session_id is None:
            raise RuntimeError("当前桌面分身由其他 LCA 实例使用，不能注销。")
        self._logoff_requested = True
        self._logoff_disconnect_sent = False
        self._initial_retries_remaining = 0
        self._pending_rdp_setting_changes = RDP_SETTING_NONE
        self._rdp_settings_retries_remaining = 0
        self._waiting_for_connection = False
        self._connection_timeout_timer.stop()
        self._retry_timer.stop()
        self._rdp_host.expect_disconnect()
        self.refresh_state("正在注销 LCA 桌面分身，完成前请勿关闭窗口")
        # 先断开 RDP 控件，再等待 Windows 注销会话。否则 ActiveX 会一直停在“正在注销”，
        # 直到后台注销线程完成，关闭窗口看起来就像卡死。
        QTimer.singleShot(0, self._disconnect_for_logoff)
        self._logoff_worker_started = True
        worker = _LogoffWorker(self)
        worker.finished.connect(self._on_logoff_thread_finished)
        self._logoff_worker = worker
        worker.start()

    def _disconnect_for_logoff(self) -> None:
        if self._disposed or not self._logoff_requested:
            return
        if self._logoff_disconnect_sent:
            return
        self._logoff_disconnect_sent = True
        try:
            self._rdp_host.disconnect_session()
        except Exception as exc:
            logger.debug("注销前断开 RDP 控件失败: %s", exc)

    def refresh_state(self, operation_message: Optional[str] = None) -> None:
        if self._disposed:
            return
        if operation_message:
            self._last_operation_message = operation_message
        try:
            enabled = "是" if child_native.is_child_sessions_enabled() else "否"
            connected = self.connected_state
            connection_text = {0: "未连接", 1: "已连接", 2: "正在连接"}.get(
                connected, f"未知连接状态 {connected}"
            )
            main_text = self._last_operation_message or connection_text
            self._status_text = (
                f"{main_text} | RDP：{connection_text} | 功能已启用：{enabled}"
            )
        except Exception as exc:
            self._status_text = str(exc)
        self.state_changed.emit()

    def dispose(self) -> None:
        if self._disposed:
            return
        worker = self._logoff_worker
        if worker is not None and worker.isRunning():
            self._dispose_after_logoff = True
            return
        self._finish_dispose()

    def _finish_dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self._dispose_after_logoff = False
        self._status_timer.stop()
        self._connection_timeout_timer.stop()
        self._retry_timer.stop()
        self._waiting_for_connection = False
        try:
            self._rdp_host.connection_failed.disconnect(self._on_rdp_connection_failed)
        except Exception:
            pass
        try:
            self._rdp_host.login_completed.disconnect(self._on_rdp_login_completed)
        except Exception:
            pass
        try:
            self._rdp_host.desktop_update_failed.disconnect(self._on_desktop_update_failed)
        except Exception:
            pass
        try:
            self._rdp_host.desktop_update_succeeded.disconnect(self._on_desktop_update_succeeded)
        except Exception:
            pass
        try:
            self._rdp_host.transport_connected.disconnect(self._on_transport_connected)
        except Exception:
            pass
        if not self._logoff_disconnect_sent:
            try:
                self._rdp_host.disconnect_session()
            except Exception:
                pass
        self._detach_prepare_worker()
        self._detach_logoff_worker()
        if self._session_lease.held:
            # Python 是 Child Session 注销的唯一责任方。宿主进程退出时只负责
            # 关闭 RDP 控件，不再从 stdin EOF 路径重复调用 WTSLogoffSession。
            try:
                child_native.terminate_child_session(wait=False)
            except Exception as exc:
                logger.warning("应用退出时注销桌面分身失败: %s", exc)
            self._session_lease.release()
        self._rdp_host.dispose()

    def _on_prepare_finished(self) -> None:
        if self._disposed or self._logoff_requested:
            return
        self._waiting_for_connection = True
        self._connection_timeout_timer.start(CONNECTION_TIMEOUT_MS)
        try:
            self._connect_core("正在启动 LCA 桌面分身")
        except Exception as exc:
            logger.error("启动桌面分身连接失败: %s", exc)
            self._on_prepare_failed(str(exc))

    def _on_prepare_failed(self, message: str) -> None:
        self._waiting_for_connection = False
        self._connection_timeout_timer.stop()
        self._session_lease.release()
        self.refresh_state("无法启动桌面分身")
        self.start_failed.emit(message)

    def _on_prepare_worker_finished(self) -> None:
        worker = self._prepare_worker
        self._prepare_worker = None
        if worker is None:
            return
        for signal, slot in (
            (worker.prepared, self._on_prepare_finished),
            (worker.failed, self._on_prepare_failed),
            (worker.status, self.refresh_state),
            (worker.finished, self._on_prepare_worker_finished),
        ):
            try:
                signal.disconnect(slot)
            except Exception:
                pass
        worker.deleteLater()

    def _detach_prepare_worker(self) -> None:
        worker = self._prepare_worker
        self._prepare_worker = None
        if worker is None:
            return
        if worker.isRunning():
            worker.cancel()
            worker.wait()
        for signal, slot in (
            (worker.prepared, self._on_prepare_finished),
            (worker.failed, self._on_prepare_failed),
            (worker.status, self.refresh_state),
            (worker.finished, self._on_prepare_worker_finished),
        ):
            try:
                signal.disconnect(slot)
            except Exception:
                pass
        self._detach_thread(worker)

    def _detach_logoff_worker(self) -> None:
        worker = self._logoff_worker
        self._logoff_worker = None
        self._logoff_worker_started = False
        if worker is None:
            return
        try:
            worker.finished.disconnect(self._on_logoff_thread_finished)
        except Exception:
            pass
        self._detach_thread(worker)

    def _detach_thread(self, worker: QThread) -> None:
        if worker.isRunning():
            worker.setParent(None)
            worker.finished.connect(worker.deleteLater)
            return
        worker.deleteLater()

    def _on_logoff_thread_finished(self) -> None:
        worker = self._logoff_worker
        self._logoff_worker = None
        self._logoff_worker_started = False
        error = ""
        session_id = None
        if worker is not None:
            error = worker.error
            session_id = worker.session_id
            worker.deleteLater()
        if error:
            if self._dispose_after_logoff:
                self._finish_dispose()
                return
            if self._disposed:
                return
            self._logoff_requested = False
            self._logoff_disconnect_sent = False
            self.refresh_state("注销失败")
            self.logoff_failed.emit(error)
            return
        if self._disposed:
            return
        if not self._logoff_disconnect_sent:
            self._disconnect_for_logoff()
        self._logoff_requested = False
        self.refresh_state("桌面分身已注销" if session_id is not None else "当前没有桌面分身")
        self.logoff_finished.emit(session_id)
        if self._dispose_after_logoff:
            self._finish_dispose()

    def _connect_core(self, operation_message: str) -> None:
        existing = child_native.try_get_child_session_id()
        if self.connected_state == 0:
            self._initial_retries_remaining = (
                INITIAL_CONNECTION_RETRY_COUNT if existing is None else 0
            )
            self._rdp_host.set_block_physical_mouse(self.block_physical_mouse)
            self._rdp_host.connect_to_child_session(self.desktop_width, self.desktop_height)
        self.refresh_state(operation_message)

    def _require_child_session_id(self) -> int:
        session_id = child_native.try_get_child_session_id()
        if session_id is None:
            raise RuntimeError("当前没有可用的桌面分身，请先启动桌面分身。")
        return session_id

    def _persist_settings(self) -> None:
        self._config["child_session"] = normalize_child_session_config(self._settings)
        self._save_config(self._config)

    def _remember_settings(self) -> None:
        try:
            self._persist_settings()
        except Exception:
            logger.exception("保存桌面分身设置失败")

    def _on_status_timer_tick(self) -> None:
        if self._status_tick_in_progress or self._disposed:
            return
        self._status_tick_in_progress = True
        try:
            self.refresh_state()
        finally:
            self._status_tick_in_progress = False

    def _on_rdp_connection_failed(self, event) -> None:
        if self._logoff_requested:
            return
        if self._pending_rdp_setting_changes != RDP_SETTING_NONE:
            if self._rdp_settings_retry_in_progress:
                return
            if self._rdp_settings_retries_remaining > 0:
                self._schedule_rdp_settings_retry(event)
                return
            self._pending_rdp_setting_changes = RDP_SETTING_NONE
        if (
            self._initial_retries_remaining > 0
            and not self._connection_retry_in_progress
        ):
            self._schedule_initial_retry(event)
            return
        self._complete_connection_failure(event)

    def _on_transport_connected(self) -> None:
        if self._disposed or self.connected_state == 1:
            return
        if self._waiting_for_connection:
            self._connection_timeout_timer.start(CONNECTION_TIMEOUT_MS)
        self.refresh_state("已连上桌面分身，正在进入桌面")

    def _on_desktop_update_succeeded(self, width: int, height: int) -> None:
        if self._disposed:
            return
        self._rdp_host.set_smart_sizing(self.smart_sizing_enabled)
        self.refresh_state(f"桌面分辨率已调整为 {int(width)} × {int(height)}")

    def _on_desktop_update_failed(self, message: str) -> None:
        if self._disposed:
            return
        logger.warning("直接调整桌面分辨率失败: %s", message)
        self.refresh_state("未能调整分辨率，桌面分身保持当前登录")

    def _on_rdp_login_completed(self) -> None:
        if self._disposed:
            return
        if not self._exit_watch_started:
            from utils.child_session.exit_watch import start_exit_watch

            self._exit_watch_started = True
            start_exit_watch()
        self._initial_retries_remaining = 0
        self._connection_retry_in_progress = False
        self._waiting_for_connection = False
        self._connection_timeout_timer.stop()
        completed = self._pending_rdp_setting_changes
        if completed != RDP_SETTING_NONE:
            self._pending_rdp_setting_changes = RDP_SETTING_NONE
            self._rdp_settings_retries_remaining = 0
            self._rdp_settings_retry_in_progress = False
            self.refresh_state("自动重新连接完成，RDP 设置已生效")
            if completed & RDP_SETTING_SHORTCUTS:
                self.system_shortcuts_reconnect_completed.emit()
            if completed & RDP_SETTING_AUDIO:
                self.audio_reconnect_completed.emit()
        else:
            if self.block_physical_mouse:
                self.refresh_state("桌面分身登录初始化完成")
            else:
                self.refresh_state("桌面分身登录初始化完成，当前使用普通鼠标")

    def _schedule_initial_retry(self, event) -> None:
        self._connection_timeout_timer.stop()
        self._connection_retry_in_progress = True
        retry_number = INITIAL_CONNECTION_RETRY_COUNT - self._initial_retries_remaining + 1
        self._initial_retries_remaining -= 1
        delay_ms = (1 << (retry_number - 1)) * 1000
        logger.warning(
            "桌面分身首次初始化连接失败，将在 %s 秒后进行第 %s 次重试。错误：%s",
            delay_ms / 1000,
            retry_number,
            getattr(event, "message", event),
        )
        self.refresh_state(
            f"桌面分身首次初始化尚未完成，{delay_ms / 1000:.0f} 秒后自动重试"
            f"（{retry_number}/{INITIAL_CONNECTION_RETRY_COUNT}）"
        )
        self._retry_kind = "initial"
        self._retry_timer.start(delay_ms)

    def _schedule_rdp_settings_retry(self, event) -> None:
        self._rdp_settings_retry_in_progress = True
        retry_number = (
            RDP_SETTINGS_RECONNECT_RETRY_COUNT - self._rdp_settings_retries_remaining + 1
        )
        self._rdp_settings_retries_remaining -= 1
        delay_ms = (1 << retry_number) * 1000
        logger.warning(
            "RDP 设置切换后的自动重连失败，将在 %s 秒后进行第 %s 次重试。错误：%s",
            delay_ms / 1000,
            retry_number,
            getattr(event, "message", event),
        )
        self.refresh_state(
            f"RDP 自动重连暂未成功，{delay_ms / 1000:.0f} 秒后重试"
            f"（{retry_number}/{RDP_SETTINGS_RECONNECT_RETRY_COUNT}）"
        )
        self._retry_kind = "settings"
        self._retry_timer.start(delay_ms)

    def _on_retry_timer(self) -> None:
        if self._disposed:
            return
        kind = getattr(self, "_retry_kind", "")
        if kind == "settings":
            if self._pending_rdp_setting_changes == RDP_SETTING_NONE:
                return
            self._rdp_settings_retry_in_progress = False
            self._waiting_for_connection = True
            self._connection_timeout_timer.start(CONNECTION_TIMEOUT_MS)
            self.refresh_state("正在重试 RDP 自动连接")
            self._rdp_host.reconnect_to_child_session(self.desktop_width, self.desktop_height)
            return
        self._connection_retry_in_progress = False
        self._waiting_for_connection = True
        self._connection_timeout_timer.start(CONNECTION_TIMEOUT_MS)
        self.refresh_state("正在重试桌面分身连接")
        self._rdp_host.reconnect_to_child_session(self.desktop_width, self.desktop_height)

    def _complete_connection_failure(self, event) -> None:
        self._initial_retries_remaining = 0
        self._waiting_for_connection = False
        self._connection_timeout_timer.stop()
        logger.error("桌面分身 RDP 连接失败：%s", getattr(event, "message", event))
        self.refresh_state("连接失败")
        self.connection_failed.emit(event)

    def _on_connection_timeout(self) -> None:
        if self._disposed or not self._waiting_for_connection:
            return
        if self.connected_state == 1:
            return
        self._initial_retries_remaining = 0
        last = self._rdp_host.last_connection_diagnostic
        timeout_message = (
            f"桌面分身连接及登录初始化未能在 {CONNECTION_TIMEOUT_MS / 1000:.0f} 秒内完成。"
        )
        if last is None:
            event = ChildSessionConnectionFailedEventArgs(
                f"{timeout_message}\n\nRDP ActiveX 未报告更具体的失败原因。",
                ERROR_TIMEOUT,
            )
        else:
            event = ChildSessionConnectionFailedEventArgs(
                f"{timeout_message}\n\nRDP ActiveX 最后报告：\n{last.message}",
                last.error_code,
                last.extended_error_code,
            )
        try:
            self._rdp_host.disconnect_session()
        except Exception:
            pass
        self._complete_connection_failure(event)

    def _reconnect_for_rdp_setting(self, setting_change: int, operation_message: str) -> bool:
        self.refresh_state()
        if self.connected_state == 0 and self.child_session_id is None:
            self.refresh_state(f"{operation_message}，将在下次 RDP 连接后应用")
            return False
        previous = self._pending_rdp_setting_changes
        self._pending_rdp_setting_changes |= setting_change
        self._rdp_settings_retries_remaining = RDP_SETTINGS_RECONNECT_RETRY_COUNT
        self._waiting_for_connection = True
        self._connection_timeout_timer.start(CONNECTION_TIMEOUT_MS)
        try:
            self._rdp_host.reconnect_to_child_session(self.desktop_width, self.desktop_height)
        except Exception:
            self._pending_rdp_setting_changes = previous
            if self._pending_rdp_setting_changes == RDP_SETTING_NONE:
                self._rdp_settings_retries_remaining = 0
            self._waiting_for_connection = False
            self._connection_timeout_timer.stop()
            raise
        self.refresh_state(f"{operation_message}，正在自动重新连接 RDP")
        return True

    def _throw_if_disposed(self) -> None:
        if self._disposed:
            raise RuntimeError("桌面分身服务已关闭。")
