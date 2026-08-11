import datetime
import glob
import logging
import os
import sys
import threading
import time
from typing import Callable, Optional

from utils.app_paths import get_logs_dir
from utils.log_runtime_control import configure_noisy_logger_levels, install_runtime_log_filters

LOG_DIR = get_logs_dir("LCA")
LOG_FILENAME_FORMAT = "app_%Y-%m-%d.log"
MAX_LOG_FILE_SIZE_MB = 15
MAX_LOG_BACKUP_COUNT = 0
LOG_RETENTION_DAYS = 7
MAX_LOG_MESSAGE_CHARS = 512
MAX_LOG_DIR_SIZE_MB = 50
LOG_MAINTENANCE_INTERVAL_SEC = 300

logger = logging.getLogger(__name__)


def _truncate_log_file_if_oversized(filepath: str, max_bytes: int, verbose: bool = False) -> int:
    if max_bytes <= 0:
        return 0

    try:
        file_size = os.path.getsize(filepath)
    except OSError:
        return 0

    if file_size <= max_bytes:
        return 0

    try:
        with open(filepath, "w", encoding="utf-8"):
            pass

        if verbose:
            logger.info(
                f"日志文件 {os.path.basename(filepath)} 超限({file_size // 1024 // 1024}MB)，已截断"
            )
        return file_size
    except (OSError, PermissionError) as e:
        if verbose:
            logger.warning(f"截断日志文件失败 {filepath}: {e}")
        return 0


def cleanup_log_files_and_temp(
    cleanup_temp_files_cb: Optional[Callable[[], None]] = None,
    verbose: bool = False,
):
    log_pattern = os.path.join(LOG_DIR, "app_*.log*")
    current_time = time.time()
    deleted_count = 0
    deleted_size = 0
    truncated_count = 0
    max_log_dir_size = MAX_LOG_DIR_SIZE_MB * 1024 * 1024

    for filepath in glob.glob(log_pattern):
        try:
            file_stat = os.stat(filepath)
            file_mtime = file_stat.st_mtime
            file_size = file_stat.st_size
            file_age_days = (current_time - file_mtime) / (24 * 60 * 60)
            if file_age_days > LOG_RETENTION_DAYS:
                os.remove(filepath)
                deleted_count += 1
                deleted_size += file_size
                if verbose:
                    logger.info(
                        f"日志文件 {os.path.basename(filepath)} 已保留{file_age_days:.1f}天，超过保留期限 {LOG_RETENTION_DAYS} 天，已删除"
                    )
        except OSError as e:
            if verbose:
                logger.warning(f"检查或删除日志文件 {filepath} 时出错: {e}")

    log_files_with_time = []
    for filepath in glob.glob(log_pattern):
        try:
            file_stat = os.stat(filepath)
            log_files_with_time.append((filepath, file_stat.st_mtime, file_stat.st_size))
        except OSError:
            pass

    current_total = sum(item[2] for item in log_files_with_time)
    if current_total > max_log_dir_size:
        if verbose:
            logger.info(
                f"日志目录总大小({current_total // 1024 // 1024}MB)超过限制({MAX_LOG_DIR_SIZE_MB}MB)，清理最旧文件"
            )
        log_files_with_time.sort(key=lambda x: x[1])
        for filepath, _, file_size in log_files_with_time:
            if current_total <= max_log_dir_size:
                break
            try:
                os.remove(filepath)
                current_total -= file_size
                deleted_count += 1
                deleted_size += file_size
                if verbose:
                    logger.info(f"已清理过大日志 {os.path.basename(filepath)} ({file_size // 1024 // 1024}MB)")
            except OSError as e:
                if verbose:
                    logger.warning(f"清理失败: {os.path.basename(filepath)}: {e}")

    if callable(cleanup_temp_files_cb):
        cleanup_temp_files_cb()

    if verbose and (deleted_count > 0 or truncated_count > 0):
        logger.info(
            f"日志清理完成：删除 {deleted_count} 个文件，截断 {truncated_count} 个文件，释放 {deleted_size // 1024 // 1024}MB"
        )


class LogMaintenanceLoop:
    def __init__(
        self,
        interval_sec: float = LOG_MAINTENANCE_INTERVAL_SEC,
        cleanup_temp_files_cb: Optional[Callable[[], None]] = None,
    ):
        self._interval_sec = max(60.0, float(interval_sec or LOG_MAINTENANCE_INTERVAL_SEC))
        self._cleanup_temp_files_cb = cleanup_temp_files_cb
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        thread_ref = self._thread
        if thread_ref is not None and thread_ref.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="LogMaintenanceLoop")
        self._thread.start()

    def stop(self, timeout: float = 1.5):
        self._stop_event.set()
        thread_ref = self._thread
        if (
            thread_ref is not None
            and thread_ref.is_alive()
            and thread_ref is not threading.current_thread()
        ):
            thread_ref.join(max(0.1, float(timeout)))

    def _run(self):
        while not self._stop_event.wait(self._interval_sec):
            try:
                cleanup_log_files_and_temp(
                    cleanup_temp_files_cb=self._cleanup_temp_files_cb,
                    verbose=False,
                )
            except Exception as e:
                logging.warning(f"[日志维护] 周期清理失败: {e}")


def setup_logging_and_cleanup(cleanup_temp_files_cb: Optional[Callable[[], None]] = None):
    cleanup_log_files_and_temp(
        cleanup_temp_files_cb=cleanup_temp_files_cb,
        verbose=True,
    )

    current_log_filename = datetime.date.today().strftime(LOG_FILENAME_FORMAT)
    current_log_filepath = os.path.join(LOG_DIR, current_log_filename)

    logger_instance = logging.getLogger()
    if logger_instance.hasHandlers():
        logger_instance.handlers.clear()

    logger_instance.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - [pid=%(process)d] - [%(module)s:%(lineno)d] - %(message)s"
    )
    handlers_to_filter = []

    try:
        from logging.handlers import RotatingFileHandler

        class SafeRotatingFileHandler(RotatingFileHandler):
            def doRollover(self):
                try:
                    if self.stream:
                        self.stream.close()
                        self.stream = None
                    original_mode = self.mode
                    try:
                        self.mode = "w"
                        stream = self._open()
                        stream.close()
                    finally:
                        self.mode = original_mode
                    if not self.delay:
                        self.stream = self._open()
                except (OSError, PermissionError):
                    pass

        file_handler = SafeRotatingFileHandler(
            current_log_filepath,
            mode="a",
            maxBytes=MAX_LOG_FILE_SIZE_MB * 1024 * 1024,
            backupCount=MAX_LOG_BACKUP_COUNT,
            encoding="utf-8",
            delay=False,
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        logger_instance.addHandler(file_handler)
        handlers_to_filter.append(file_handler)
    except Exception as e:
        logger.error(f"无法设置日志文件处理器 {current_log_filepath}: {e}")

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)
    logger_instance.addHandler(stream_handler)
    handlers_to_filter.append(stream_handler)

    install_runtime_log_filters(handlers_to_filter, MAX_LOG_MESSAGE_CHARS)
    configure_noisy_logger_levels()

    try:
        from utils.log_message_translator import install_log_message_translator

        install_log_message_translator(logger_instance)
    except Exception:
        pass
