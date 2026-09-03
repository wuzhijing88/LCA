"""独立 worker 子进程（OCR / 工作流）的命令行入口规格。

`main.py` 在加载任何 GUI 依赖之前先用这里的规格判断自己是否是 worker 进程；
规格集中在此处，避免多个入口各自复制一份。
"""

from __future__ import annotations

import logging
import os

from app_core.runtime.worker_entry import (
    StandaloneSubprocessSpec,
    get_cli_argument_value,
    get_cli_int_argument_value,
)

_WORKER_LOG_FORMAT = (
    "%(asctime)s - %(levelname)s - [pid=%(process)d] - [%(funcName)s:%(lineno)d] - %(message)s"
)
_FILE_LOG_FORMAT = (
    "%(asctime)s - %(levelname)s - [pid=%(process)d] - [%(module)s:%(lineno)d] - %(message)s"
)


def install_root_log_translator() -> None:
    try:
        from utils.log_message_translator import install_log_message_translator

        install_log_message_translator(logging.getLogger())
    except Exception:
        pass


def ensure_standalone_subprocess_file_logging(log_level: int = logging.INFO) -> None:
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return
    try:
        import datetime as _datetime
        from utils.app_paths import get_logs_dir

        log_dir = get_logs_dir("LCA")
        log_path = os.path.join(log_dir, f"app_{_datetime.date.today():%Y-%m-%d}.log")
        file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
        file_handler.setLevel(int(log_level))
        file_handler.setFormatter(logging.Formatter(_FILE_LOG_FORMAT))
        root_logger.setLevel(int(log_level))
        root_logger.addHandler(file_handler)
    except Exception:
        logging.basicConfig(level=int(log_level), format=_FILE_LOG_FORMAT)


def _build_ocr_subprocess_args(argv) -> tuple[str, int]:
    process_id = get_cli_argument_value(argv, "--process-id", "").strip()
    port = get_cli_int_argument_value(argv, "--port", 0)
    if not process_id:
        raise ValueError("--process-id is required for OCR worker")
    if port <= 0:
        raise ValueError("--port must be greater than zero for OCR worker")
    return process_id, port


def _build_workflow_subprocess_args(argv) -> tuple[int]:
    port = get_cli_int_argument_value(argv, "--port", 0)
    if port <= 0:
        raise ValueError("--port must be greater than zero for workflow worker")
    return (port,)


def _log_ocr_subprocess_start(logger, _argv, args) -> None:
    install_root_log_translator()
    process_id, port = args
    logger.info("=" * 80)
    logger.info("[OCR子进程-命令行检测] 检测到 --ocr-worker 参数")
    logger.info(f"[OCR子进程-命令行检测] 进程ID: {process_id}")
    logger.info(f"[OCR子进程-命令行检测] 通信端口: {port}")
    logger.info("=" * 80)


def _log_workflow_subprocess_start(logger, _argv, args) -> None:
    ensure_standalone_subprocess_file_logging(logging.INFO)
    install_root_log_translator()
    (port,) = args
    logger.info("=" * 80)
    logger.info("[工作流子进程][命令行检测] 检测到 --workflow-worker 参数")
    logger.info(f"[工作流子进程][命令行检测] 通信端口: {port}")
    logger.info("=" * 80)


STANDALONE_SUBPROCESS_SPECS = (
    StandaloneSubprocessSpec(
        flag="--ocr-worker",
        module_name="services.multiprocess_ocr_worker",
        callable_name="run_ocr_worker_standalone",
        logger_name="OCR_SUBPROCESS",
        error_label="OCR子进程",
        log_level=logging.DEBUG,
        log_format=_WORKER_LOG_FORMAT,
        args_factory=_build_ocr_subprocess_args,
        startup_hook=_log_ocr_subprocess_start,
    ),
    StandaloneSubprocessSpec(
        flag="--workflow-worker",
        module_name="task_workflow.process_worker",
        callable_name="run_workflow_worker_standalone",
        logger_name="WORKFLOW_SUBPROCESS",
        error_label="WORKFLOW子进程",
        log_level=logging.INFO,
        log_format=_WORKER_LOG_FORMAT,
        configure_root_logging=False,
        args_factory=_build_workflow_subprocess_args,
        startup_hook=_log_workflow_subprocess_start,
    ),
)
