# -*- coding: utf-8 -*-
"""工作流执行子进程入口。"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import socket
import sys
import threading
from typing import Any, Dict, Optional

from services.ocr_socket_message_utils import recv_message, send_message
from utils.app_paths import get_config_path, get_logs_dir
from utils.log_runtime_control import configure_noisy_logger_levels, install_runtime_log_filters
from utils.worker_entry import bootstrap_current_process_virtual_environment

logger = logging.getLogger(__name__)
_FAULT_HANDLER_STREAM = None
_WORKFLOW_LOGGING_CONFIGURED = False
MAX_WORKER_LOG_MESSAGE_CHARS = 512


def _resolve_worker_screenshot_engine(payload: Dict[str, Any]) -> str:
    valid_engines = {"wgc", "printwindow", "gdi", "dxgi"}

    requested_engine = str(payload.get("screenshot_engine") or "").strip().lower()
    if requested_engine in valid_engines:
        return requested_engine

    try:
        config_path = get_config_path("LCA")
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as fp:
                config_data = json.load(fp) or {}
            requested_engine = str(config_data.get("screenshot_engine") or "").strip().lower()
            if requested_engine in valid_engines:
                return requested_engine
    except Exception as exc:
        logger.warning("工作流子进程读取截图引擎配置失败: %s", exc)

    return ""


def _apply_worker_runtime_preferences(payload: Dict[str, Any]) -> None:
    requested_engine = _resolve_worker_screenshot_engine(payload)
    if not requested_engine:
        return

    actual_engine = ""
    try:
        from utils.screenshot_helper import get_screenshot_engine, set_screenshot_engine

        set_screenshot_engine(requested_engine)
        actual_engine = str(get_screenshot_engine() or "").strip().lower()
        logger.info("工作流子进程截图引擎已应用: requested=%s, actual=%s", requested_engine, actual_engine)
    except Exception as exc:
        try:
            from utils.screenshot_helper import get_screenshot_engine

            actual_engine = str(get_screenshot_engine() or "").strip().lower()
        except Exception:
            actual_engine = ""
        logger.warning(
            "工作流子进程切换截图引擎失败: requested=%s, actual=%s, error=%s",
            requested_engine,
            actual_engine or "unknown",
            exc,
        )


def _configure_logging() -> None:
    global _WORKFLOW_LOGGING_CONFIGURED
    if _WORKFLOW_LOGGING_CONFIGURED:
        return

    root_logger = logging.getLogger()

    log_dir = get_logs_dir("LCA")
    log_filename = f"app_{datetime.date.today().strftime('%Y-%m-%d')}.log"
    log_path = os.path.join(log_dir, log_filename)

    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - [pid=%(process)d] - [%(module)s:%(lineno)d] - %(message)s"
    )
    root_logger.setLevel(logging.INFO)
    handlers_to_filter = list(root_logger.handlers)
    managed_file_handler = None

    for existing_handler in root_logger.handlers:
        handler_path = getattr(existing_handler, "baseFilename", "")
        if handler_path and os.path.abspath(str(handler_path)) == os.path.abspath(log_path):
            managed_file_handler = existing_handler
            break

    if managed_file_handler is None:
        try:
            managed_file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
            managed_file_handler.setLevel(logging.INFO)
            managed_file_handler.setFormatter(formatter)
            root_logger.addHandler(managed_file_handler)
            handlers_to_filter.append(managed_file_handler)
        except Exception:
            managed_file_handler = None

    if not root_logger.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - [pid=%(process)d] - [%(module)s:%(lineno)d] - %(message)s",
        )
        handlers_to_filter = list(root_logger.handlers)
    elif not handlers_to_filter:
        handlers_to_filter = list(root_logger.handlers)

    install_runtime_log_filters(handlers_to_filter or root_logger.handlers, MAX_WORKER_LOG_MESSAGE_CHARS)
    configure_noisy_logger_levels()

    try:
        from utils.log_message_translator import install_log_message_translator
        install_log_message_translator(root_logger)
    except Exception:
        pass
    _WORKFLOW_LOGGING_CONFIGURED = True


def _configure_faulthandler() -> None:
    global _FAULT_HANDLER_STREAM
    try:
        import faulthandler

        log_dir = get_logs_dir("LCA")
        fault_log_path = os.path.join(log_dir, f"workflow_worker_fault_{os.getpid()}.log")
        _FAULT_HANDLER_STREAM = open(fault_log_path, "a", encoding="utf-8")
        faulthandler.enable(file=_FAULT_HANDLER_STREAM, all_threads=True)
        logger.info(f"工作流子进程已启用崩溃诊断: {fault_log_path}")
    except Exception as exc:
        logger.warning(f"启用工作流子进程崩溃诊断失败: {exc}")


class _SocketSignalBridge:
    """将执行器信号桥接到父进程 socket。"""

    _FORWARDED_SIGNALS = (
        "execution_started",
        "card_executing",
        "card_finished",
        "overlay_update_requested",
        "error_occurred",
        "path_updated",
        "param_updated",
        "path_resolution_failed",
        "step_details",
        "show_warning",
        "step_log",
    )

    def __init__(self, sock: socket.socket):
        self._sock = sock
        self._send_lock = threading.Lock()
        self._handlers = []
        self._finished_sent = False

    def _send(self, payload: Dict[str, Any]) -> bool:
        with self._send_lock:
            return bool(send_message(self._sock, payload, logger=logger))

    def send_ready(self) -> bool:
        return self._send({"type": "ready"})

    def send_runtime_variables(self, runtime_variables: Optional[Dict[str, Any]]) -> bool:
        if not isinstance(runtime_variables, dict):
            runtime_variables = {}
        return self._send({"type": "runtime_variables", "data": runtime_variables})

    def send_execution_finished(self, success: bool, message: str, runtime_variables: Optional[Dict[str, Any]]) -> bool:
        if self._finished_sent:
            return True
        self._finished_sent = True
        self.send_runtime_variables(runtime_variables)
        return self._send(
            {
                "type": "signal",
                "name": "execution_finished",
                "args": [bool(success), str(message or "")],
            }
        )

    def bind_executor(self, executor_obj: Any) -> None:
        for signal_name in self._FORWARDED_SIGNALS:
            signal_obj = getattr(executor_obj, signal_name, None)
            if signal_obj is None:
                continue

            def _make_handler(name: str):
                def _handler(*args):
                    self._send({"type": "signal", "name": name, "args": list(args)})

                return _handler

            handler = _make_handler(signal_name)
            try:
                signal_obj.connect(handler)
                self._handlers.append((signal_obj, handler))
            except Exception as exc:
                logger.warning("绑定子进程信号失败: %s -> %s", signal_name, exc)

        finished_signal = getattr(executor_obj, "execution_finished", None)
        if finished_signal is not None:

            def _on_finished(success: bool, message: str):
                runtime_variables = getattr(executor_obj, "_final_runtime_variables", None)
                self.send_execution_finished(success, message, runtime_variables)

            try:
                finished_signal.connect(_on_finished)
                self._handlers.append((finished_signal, _on_finished))
            except Exception as exc:
                logger.warning("绑定 execution_finished 失败: %s", exc)


def _create_executor(payload: Dict[str, Any]):
    from tasks import get_task_modules
    from task_workflow.executor import WorkflowExecutor
    from task_workflow.multi_thread_session import WorkflowMultiThreadSession

    session_mode = str(payload.get("session_mode") or "single").strip().lower()
    cards_data = payload.get("cards_data") or {}
    connections_data = payload.get("connections_data") or []
    common_kwargs = dict(
        task_modules=get_task_modules(),
        target_window_title=payload.get("target_window_title"),
        execution_mode=payload.get("execution_mode") or "foreground",
        images_dir=payload.get("images_dir"),
        target_hwnd=payload.get("target_hwnd"),
        workflow_id=payload.get("workflow_id"),
        workflow_filepath=payload.get("workflow_filepath"),
        get_image_data=None,
    )

    if session_mode == "multi_thread":
        return WorkflowMultiThreadSession(
            cards_data=cards_data,
            connections_data=connections_data,
            start_card_ids=payload.get("start_card_ids") or [],
            thread_labels=payload.get("thread_labels") or {},
            thread_window_configs=payload.get("thread_window_configs") or {},
            **common_kwargs,
        )

    return WorkflowExecutor(
        cards_data=cards_data,
        connections_data=connections_data,
        start_card_id=payload.get("start_card_id"),
        test_mode=payload.get("test_mode"),
        **common_kwargs,
    )


def _control_loop(sock: socket.socket, executor_obj: Any, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            message = recv_message(sock, timeout=0.2, logger=logger)
        except Exception as exc:
            logger.warning("控制消息接收失败: %s", exc)
            break

        if message is None:
            continue

        command = str(message.get("command") or "").strip().lower()
        if command == "request_stop":
            force = bool(message.get("force"))
            try:
                executor_obj.request_stop(force=force)
            except Exception as exc:
                logger.warning("子进程 request_stop 失败: %s", exc)
        elif command == "pause":
            try:
                executor_obj.pause()
            except Exception as exc:
                logger.warning("子进程 pause 失败: %s", exc)
        elif command == "resume":
            try:
                executor_obj.resume()
            except Exception as exc:
                logger.warning("子进程 resume 失败: %s", exc)
        elif command == "ping":
            try:
                send_message(sock, {"type": "pong"}, logger=logger)
            except Exception:
                break
        elif command == "shutdown":
            try:
                executor_obj.request_stop(force=True)
            except Exception:
                pass
            break


def run_workflow_worker_standalone(port: int) -> int:
    _configure_logging()
    bootstrap_current_process_virtual_environment(
        project_root=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        runtime_label="工作流子进程",
        logger=logger,
    )
    _configure_faulthandler()

    if not port:
        logger.error("工作流子进程缺少端口参数")
        return 2

    sock: Optional[socket.socket] = None
    control_thread: Optional[threading.Thread] = None
    stop_event = threading.Event()

    try:
        sock = socket.create_connection(("127.0.0.1", int(port)), timeout=8.0)
        bridge = _SocketSignalBridge(sock)
        if not bridge.send_ready():
            logger.error("工作流子进程发送 ready 失败")
            return 3

        init_message = recv_message(sock, timeout=20.0, logger=logger)
        if not isinstance(init_message, dict) or str(init_message.get("command") or "") != "init":
            logger.error("工作流子进程未收到 init 消息: %s", init_message)
            return 4

        payload = init_message.get("payload")
        if not isinstance(payload, dict):
            logger.error("工作流子进程收到的 payload 非法")
            return 5

        _apply_worker_runtime_preferences(payload)

        executor_obj = _create_executor(payload)
        bridge.bind_executor(executor_obj)

        control_thread = threading.Thread(
            target=_control_loop,
            args=(sock, executor_obj, stop_event),
            daemon=True,
            name="WorkflowWorkerControl",
        )
        control_thread.start()

        try:
            executor_obj.run()
        except Exception as exc:
            logger.exception("工作流子进程执行失败: %s", exc)
            runtime_variables = getattr(executor_obj, "_final_runtime_variables", None)
            bridge.send_execution_finished(False, f"执行错误: {exc}", runtime_variables)
            return 6

        if not bridge._finished_sent:
            runtime_variables = getattr(executor_obj, "_final_runtime_variables", None)
            bridge.send_execution_finished(False, "执行器异常结束", runtime_variables)
        return 0
    finally:
        global _FAULT_HANDLER_STREAM
        stop_event.set()
        if control_thread is not None and control_thread.is_alive():
            try:
                control_thread.join(timeout=1.0)
            except Exception:
                pass
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
        if _FAULT_HANDLER_STREAM is not None:
            try:
                _FAULT_HANDLER_STREAM.flush()
            except Exception:
                pass
            try:
                _FAULT_HANDLER_STREAM.close()
            except Exception:
                pass
            _FAULT_HANDLER_STREAM = None


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="LCA 工作流执行子进程")
    parser.add_argument("--workflow-worker-standalone", action="store_true", help="作为工作流子进程运行")
    parser.add_argument("--port", type=int, default=0, help="父进程监听端口")
    args = parser.parse_args(argv)
    if not args.workflow_worker_standalone:
        return 1
    return run_workflow_worker_standalone(args.port)


if __name__ == "__main__":
    sys.exit(main())
