"""Task state management and runtime cleanup."""

from __future__ import annotations

import logging
import os
import sys
import threading
import time

from PySide6.QtCore import QObject, Signal


def _trim_main_process_memory() -> float:
    """尽量回收主进程工作集，返回估算释放量（MB）。"""
    memory_before = None
    memory_after = None
    process = None

    try:
        import psutil
        process = psutil.Process()
        memory_before = process.memory_info().rss / 1024 / 1024
    except Exception:
        process = None

    try:
        import gc
        gc.collect()
    except Exception:
        pass

    if os.name == "nt":
        try:
            import ctypes

            try:
                msvcrt = ctypes.CDLL("msvcrt")
                if hasattr(msvcrt, "_heapmin"):
                    msvcrt._heapmin()
            except Exception:
                pass

            try:
                kernel32 = ctypes.windll.kernel32
                psapi = ctypes.windll.psapi
                current_process = kernel32.GetCurrentProcess()
                psapi.EmptyWorkingSet(current_process)
            except Exception:
                pass
        except Exception:
            pass

    if process is not None:
        try:
            memory_after = process.memory_info().rss / 1024 / 1024
        except Exception:
            memory_after = None

    if memory_before is not None and memory_after is not None:
        return memory_before - memory_after
    return 0.0


def _shutdown_existing_async_screenshot_pipeline() -> bool:
    """Stop the async screenshot pipeline without importing it during cleanup."""
    async_module = sys.modules.get("utils.async_screenshot")
    shutdown_pipeline = getattr(async_module, "shutdown_global_pipeline", None)
    if not callable(shutdown_pipeline):
        return False
    shutdown_pipeline()
    return True


def cleanup_yolo_runtime_resources(
    release_process: bool = True,
    compact_memory: bool = True,
) -> bool:
    """清理YOLO运行时资源（仅清理已存在实例，不创建新实例）。"""
    cleaned = False
    try:
        from utils.runtime_image_cleanup import cleanup_yolo_runtime_on_stop

        cleanup_result = cleanup_yolo_runtime_on_stop(
            release_engine=bool(release_process),
            compact_memory=bool(compact_memory),
        )
        cleaned = bool(
            cleanup_result.get("runtime")
            or cleanup_result.get("overlay_only")
            or cleanup_result.get("engine")
        )
    except Exception as e:
        logging.debug(f"清理YOLO运行时资源时出错: {e}")
    return cleaned


class TaskStateManager(QObject):
    """任务状态管理器，防止重复操作和状态冲突"""
    task_state_changed = Signal(str)  # "starting", "running", "stopping", "stopped"

    def __init__(self):
        super().__init__()
        self._current_state = "stopped"
        self._state_lock = False
        self._stop_request_pending = False
        self._ocr_cleanup_timer = None  # 【OCR延迟清理】30秒延迟清理定时器
        self._ocr_hot_reset_timer = None  # 【OCR热重置】3秒延迟热重置定时器
        self._ocr_cleanup_cancelled = False  # 【修复】防止已触发的清理执行
        self._ocr_cleanup_generation = 0  # 清理代际号，用于失效旧停止周期的清理任务
        self._ocr_cleanup_idle_threshold_sec = 3.0  # 清理前要求OCR连续空闲秒数
        self._ocr_cleanup_recheck_min_sec = 0.2  # 空闲不足时的最小重试间隔
        self._background_threads = []
        self._background_threads_lock = threading.Lock()

    def get_current_state(self):
        return self._current_state

    def is_state_changing(self):
        return self._state_lock

    def is_running(self):
        """检查任务是否正在运行"""
        return self._current_state in ["starting", "running"]

    def _is_cleanup_context_valid(self, generation: int) -> bool:
        """检查清理上下文是否仍然有效（防止旧清理任务干扰新任务）"""
        if self._ocr_cleanup_cancelled:
            return False
        if generation != self._ocr_cleanup_generation:
            return False
        if self._current_state in ["starting", "running"]:
            return False
        return True

    def _get_ocr_cleanup_remaining_idle_sec(self, idle_seconds: float) -> float:
        """返回OCR达到空闲阈值还需等待的秒数（0表示可清理）"""
        try:
            target_idle = float(idle_seconds)
        except (TypeError, ValueError):
            target_idle = 3.0
        if target_idle < 0:
            target_idle = 0.0

        from services.multiprocess_ocr_pool import get_existing_multiprocess_ocr_pool
        pool = get_existing_multiprocess_ocr_pool()
        if pool is None or not pool.is_running:
            return 0.0

        remaining_idle = max(
            0.0,
            float(pool.get_hot_reset_remaining_idle_sec(target_idle)),
        )
        if remaining_idle >= target_idle:
            stats = pool.get_stats()
            if int(stats["total_processes"]) <= 0:
                return 0.0
        return remaining_idle

    def _prune_background_threads(self):
        with self._background_threads_lock:
            alive_threads = []
            for thread_ref in self._background_threads:
                if thread_ref is None:
                    continue
                try:
                    if thread_ref.is_alive():
                        alive_threads.append(thread_ref)
                except Exception:
                    continue
            self._background_threads = alive_threads

    def _start_background_thread(self, target, name: str, daemon: bool = True):
        thread_ref = threading.Thread(target=target, daemon=daemon, name=name)
        with self._background_threads_lock:
            alive_threads = []
            for existing_thread in self._background_threads:
                if existing_thread is None:
                    continue
                try:
                    if existing_thread.is_alive():
                        alive_threads.append(existing_thread)
                except Exception:
                    continue
            alive_threads.append(thread_ref)
            self._background_threads = alive_threads
        thread_ref.start()
        return thread_ref

    def _wait_background_threads(self, timeout: float = 2.0):
        try:
            wait_timeout = max(0.0, float(timeout))
        except (TypeError, ValueError):
            wait_timeout = 2.0
        deadline = time.time() + wait_timeout
        current_thread = threading.current_thread()
        while True:
            with self._background_threads_lock:
                join_candidates = []
                for thread_ref in self._background_threads:
                    if thread_ref is None:
                        continue
                    if thread_ref is current_thread:
                        continue
                    try:
                        if thread_ref.is_alive():
                            join_candidates.append(thread_ref)
                    except Exception:
                        continue
                self._background_threads = join_candidates
            if not join_candidates:
                return
            remaining = deadline - time.time()
            if remaining <= 0:
                return
            join_slice = min(0.2, remaining)
            for thread_ref in join_candidates:
                try:
                    thread_ref.join(join_slice)
                except Exception:
                    continue

    def _stop_and_delete_timer(self, timer_ref):
        if timer_ref is None:
            return None
        try:
            if timer_ref.isActive():
                timer_ref.stop()
        except Exception:
            pass
        try:
            timer_ref.timeout.disconnect()
        except Exception:
            pass
        try:
            timer_ref.deleteLater()
        except Exception:
            pass
        return None

    def shutdown(self, timeout: float = 2.0):
        """应用退出时停止内部清理定时器和后台线程。"""
        self._ocr_cleanup_cancelled = True
        self._ocr_cleanup_generation += 1
        self._ocr_cleanup_timer = self._stop_and_delete_timer(self._ocr_cleanup_timer)
        self._ocr_hot_reset_timer = self._stop_and_delete_timer(self._ocr_hot_reset_timer)
        self._wait_background_threads(timeout=timeout)

    def request_start(self):
        """请求启动任务"""
        logging.info(f"收到启动请求 - 当前状态: {self._current_state}, 状态锁: {self._state_lock}, 停止请求: {self._stop_request_pending}")

        # 【OCR延迟清理】如果有待执行的OCR清理定时器，取消它（30秒内重新启动）
        if self._ocr_cleanup_timer is not None:
            self._ocr_cleanup_timer = self._stop_and_delete_timer(self._ocr_cleanup_timer)
            logging.info("[OCR延迟清理] 检测到30秒内重新启动，取消OCR子进程清理定时器")

        # 【OCR热重置】如果有待执行的3秒热重置，启动新任务时取消
        if self._ocr_hot_reset_timer is not None:
            self._ocr_hot_reset_timer = self._stop_and_delete_timer(self._ocr_hot_reset_timer)
            logging.info("[OCR热重置] 检测到重新启动，取消3秒延迟热重置定时器")

        # 【修复】设置取消标志并推进代际，失效所有待执行清理
        self._ocr_cleanup_cancelled = True
        self._ocr_cleanup_generation += 1
        self._wait_background_threads(timeout=0.3)
        logging.debug("[OCR延迟清理] 设置取消标志并推进清理代际，防止任何待执行的清理")

        # 如果任务已经停止，强制重置所有锁定标志
        if self._current_state == "stopped":
            if self._state_lock or self._stop_request_pending:
                logging.info("任务已停止，强制重置所有锁定标志以允许启动")
                self._state_lock = False
                self._stop_request_pending = False

        if self._state_lock:
            logging.warning(f"任务状态正在改变中，忽略启动请求 (状态: {self._current_state}, 锁: {self._state_lock})")
            return False

        if self._current_state in ["starting", "running"]:
            logging.warning(f"任务已在运行状态 ({self._current_state})，忽略启动请求")
            return False

        self._state_lock = True
        self._current_state = "starting"
        self.task_state_changed.emit("starting")
        logging.info("任务状态: 正在启动...")
        return True

    def request_stop(self):
        """请求停止任务"""
        # 幂等处理：已停止/停止中时不再重复进入停止流程，避免重复触发重清理
        if self._current_state == "stopped":
            self._state_lock = False
            self._stop_request_pending = False
            logging.info("任务已停止，忽略重复停止请求")
            return True

        if self._current_state == "stopping" and self._stop_request_pending:
            logging.info("停止请求已在处理中，忽略重复停止请求")
            return True

        self._state_lock = True
        self._stop_request_pending = True
        self._current_state = "stopping"
        self.task_state_changed.emit("stopping")
        logging.info("任务状态: 正在停止...")
        return True

    def confirm_stopped(self):
        """确认任务已停止"""
        from PySide6.QtCore import QTimer, QThread

        # 跨线程调用时，切回对象所属线程执行，避免 QTimer(parent=self) 线程不匹配
        if QThread.currentThread() != self.thread():
            QTimer.singleShot(0, self, self.confirm_stopped)
            return

        # 无论当前状态如何，都强制重置到停止状态
        old_state = self._current_state
        self._current_state = "stopped"
        self._state_lock = False
        self._stop_request_pending = False

        # 幂等处理：若已处于停止态，仅同步状态，不重复触发重量级清理链路
        if old_state == "stopped":
            logging.debug("任务状态: 已处于停止态，跳过重复停止清理")
            return

        # 停止后立即释放YOLO推理会话，防止无任务时长期占用内存
        if cleanup_yolo_runtime_resources(release_process=False, compact_memory=False):
            logging.info("停止任务后已释放YOLO模型资源")

        # 【OCR延迟清理】取消之前的定时器（如果有）
        if self._ocr_cleanup_timer is not None:
            self._ocr_cleanup_timer = self._stop_and_delete_timer(self._ocr_cleanup_timer)
            logging.debug("[OCR延迟清理] 已清理之前的OCR清理定时器")

        # 【OCR热重置】取消之前的3秒热重置定时器（如果有）
        if self._ocr_hot_reset_timer is not None:
            self._ocr_hot_reset_timer = self._stop_and_delete_timer(self._ocr_hot_reset_timer)
            logging.debug("[OCR热重置] 已清理之前的3秒热重置定时器")

        # 清理Qt像素图全局缓存，释放大量卡片渲染缓存占用
        try:
            from PySide6.QtGui import QPixmapCache
            QPixmapCache.clear()
            logging.debug("[诊断清理] 已清理 QPixmapCache")
        except Exception as e:
            logging.debug(f"[诊断清理] 清理 QPixmapCache 失败: {e}")

        # 【修复】重置取消标志并推进代际，开启新的停止清理周期
        self._ocr_cleanup_cancelled = False
        self._ocr_cleanup_generation += 1
        cleanup_generation = self._ocr_cleanup_generation
        idle_threshold_sec = self._ocr_cleanup_idle_threshold_sec
        idle_recheck_min_sec = self._ocr_cleanup_recheck_min_sec

        def is_cleanup_context_valid():
            return self._is_cleanup_context_valid(cleanup_generation)

        def get_remaining_idle_sec():
            return self._get_ocr_cleanup_remaining_idle_sec(idle_threshold_sec)

        # 停止任务后按“连续空闲阈值”触发OCR热重置（期间有OCR活动则重置计时）
        def hot_reset_ocr_background():
            try:
                if not is_cleanup_context_valid():
                    return
                if get_remaining_idle_sec() > 0:
                    return

                from services.multiprocess_ocr_pool import get_existing_multiprocess_ocr_pool
                pool = get_existing_multiprocess_ocr_pool()
                if pool is None:
                    logging.debug("[OCR热重置] OCR池未初始化，跳过热重置")
                    return
                reset_ok = bool(pool.hot_reset_all_idle_workers())
                if reset_ok:
                    logging.debug("[OCR热重置] 已完成空闲子进程热重置")
                else:
                    logging.debug("[OCR热重置] 当前无空闲子进程可热重置或重置未执行")
            except Exception as e:
                logging.warning(f"[OCR热重置] 停止任务后热重置失败: {e}")

        def schedule_hot_reset_timer(delay_sec: float):
            if not is_cleanup_context_valid():
                return

            delay_ms = max(1, int(max(0.0, float(delay_sec)) * 1000))
            if self._ocr_hot_reset_timer is not None:
                try:
                    if self._ocr_hot_reset_timer.isActive():
                        self._ocr_hot_reset_timer.stop()
                    try:
                        self._ocr_hot_reset_timer.timeout.disconnect()
                    except Exception:
                        pass
                    self._ocr_hot_reset_timer.deleteLater()
                except Exception:
                    pass
                finally:
                    self._ocr_hot_reset_timer = None

            self._ocr_hot_reset_timer = QTimer(self)
            self._ocr_hot_reset_timer.setSingleShot(True)
            self._ocr_hot_reset_timer.timeout.connect(delayed_hot_reset)
            self._ocr_hot_reset_timer.start(delay_ms)

        def delayed_hot_reset():
            timer_ref = self._ocr_hot_reset_timer
            self._ocr_hot_reset_timer = None
            if timer_ref is not None:
                try:
                    timer_ref.deleteLater()
                except Exception:
                    pass

            if not is_cleanup_context_valid():
                logging.debug("[OCR热重置] 清理上下文已失效，跳过热重置")
                return

            remaining_idle_sec = get_remaining_idle_sec()
            if remaining_idle_sec > 0:
                next_delay_sec = max(idle_recheck_min_sec, remaining_idle_sec)
                schedule_hot_reset_timer(next_delay_sec)
                logging.debug(
                    "[OCR热重置] 检测到近期仍有OCR活动，"
                    f"将在空闲倒计时后重试（剩余约 {remaining_idle_sec:.2f}s）"
                )
                return

            self._start_background_thread(
                target=hot_reset_ocr_background,
                daemon=True,
                name="OCR-HotReset-OnStop",
            )
            logging.debug(f"[OCR热重置] OCR已连续空闲{idle_threshold_sec:.1f}秒，已启动后台热重置线程")

        schedule_hot_reset_timer(idle_threshold_sec)
        logging.debug(f"[OCR热重置] 已启动“空闲{idle_threshold_sec:.1f}秒后热重置”检测（期间有OCR活动会自动重置计时）")

        # 【OCR延迟清理】启动延迟清理定时器，如果仍空闲才执行OCR子进程清理
        def schedule_ocr_cleanup_timer(delay_sec: float):
            if not is_cleanup_context_valid():
                return

            delay_ms = max(1, int(max(0.0, float(delay_sec)) * 1000))
            if self._ocr_cleanup_timer is not None:
                try:
                    if self._ocr_cleanup_timer.isActive():
                        self._ocr_cleanup_timer.stop()
                    try:
                        self._ocr_cleanup_timer.timeout.disconnect()
                    except Exception:
                        pass
                    self._ocr_cleanup_timer.deleteLater()
                except Exception:
                    pass
                finally:
                    self._ocr_cleanup_timer = None

            self._ocr_cleanup_timer = QTimer(self)
            self._ocr_cleanup_timer.setSingleShot(True)
            self._ocr_cleanup_timer.timeout.connect(delayed_ocr_cleanup)
            self._ocr_cleanup_timer.start(delay_ms)

        def delayed_ocr_cleanup():
            """延迟后执行OCR清理（停止后立即强制回收）"""
            timer_ref = self._ocr_cleanup_timer
            self._ocr_cleanup_timer = None
            if timer_ref is not None:
                try:
                    timer_ref.deleteLater()
                except Exception:
                    pass

            if not is_cleanup_context_valid():
                logging.debug("[OCR延迟清理] 清理上下文已失效，跳过OCR清理")
                return

            def cleanup_ocr_background():
                """后台清理OCR子进程，避免卡住UI"""
                try:
                    if not is_cleanup_context_valid():
                        logging.debug("[后台清理] OCR清理上下文失效，取消本次清理")
                        return

                    from services.multiprocess_ocr_pool import (
                        cleanup_registered_ocr_subprocesses,
                        get_existing_multiprocess_ocr_pool,
                    )
                    logging.debug("[后台清理] 开始强制清理所有OCR子进程...")
                    pool = get_existing_multiprocess_ocr_pool()
                    if pool is not None:
                        stats = pool.get_stats()
                        logging.debug(f"[后台清理] 当前OCR进程数: {stats.get('total_processes', 0)}")
                        pool.cleanup_all_processes()
                        stats = pool.get_stats()
                        logging.debug(f"[后台清理] 清理后OCR进程数: {stats.get('total_processes', 0)}")

                    cleaned_count = int(cleanup_registered_ocr_subprocesses() or 0)
                    if cleaned_count > 0:
                        logging.info(f"[后台清理] OCR登记子进程已清理: {cleaned_count}")
                    else:
                        logging.debug("[后台清理] 未发现需要清理的OCR登记子进程")
                except Exception as e:
                    logging.error(f"[后台清理] OCR进程清理失败: {e}")
                    import traceback
                    logging.error(traceback.format_exc())

            self._start_background_thread(
                target=cleanup_ocr_background,
                daemon=True,
                name="OCR-Cleanup",
            )
            logging.debug("[后台清理] OCR清理线程已启动，不阻塞UI")

        schedule_ocr_cleanup_timer(0.2)
        logging.debug("[OCR延迟清理] 已启动立即清理定时器（停止后强制回收OCR子进程）")

        # 【后台清理】将所有耗时的清理操作放到后台线程，且仅在OCR空闲后执行
        def cleanup_resources_background():
            """后台清理所有资源，避免卡住UI"""
            try:
                import time

                while True:
                    if not is_cleanup_context_valid():
                        logging.debug("[后台清理] 清理上下文已失效，跳过资源清理")
                        return
                    remaining_idle_sec = get_remaining_idle_sec()
                    if remaining_idle_sec <= 0:
                        break
                    sleep_sec = max(idle_recheck_min_sec, min(1.0, remaining_idle_sec))
                    time.sleep(sleep_sec)

                # 【优化】记录清理前的内存占用
                memory_before = 0
                try:
                    import psutil
                    process = psutil.Process()
                    memory_before = process.memory_info().rss / 1024 / 1024
                    logging.debug(f"[后台清理] 清理前内存占用: {memory_before:.1f} MB")
                except Exception:
                    pass

                if not is_cleanup_context_valid():
                    logging.debug("[后台清理] 资源清理开始前检测到上下文失效，跳过")
                    return

                # 1. 先关闭异步截图管道，避免清理引擎时仍有任务占用
                try:
                    _shutdown_existing_async_screenshot_pipeline()
                except Exception as e:
                    logging.warning(f"[后台清理] 关闭异步截图管道失败: {e}")

                # 2. 释放截图引擎资源（包含WGC捕获器/线程/帧池）
                try:
                    from utils.capture.screenshot_helper import cleanup_all_screenshot_engines
                    cleanup_all_screenshot_engines()
                except Exception as e:
                    logging.warning(f"[后台清理] 截图引擎资源释放失败: {e}")

                # 3. 清理图片识别缓存（并行识别器缓存）
                try:
                    try:
                        from tasks.parallel_image_recognition import get_existing_parallel_recognizer
                        parallel_recognizer = get_existing_parallel_recognizer()
                        if parallel_recognizer and hasattr(parallel_recognizer, 'cleanup'):
                            parallel_recognizer.cleanup()
                            logging.debug("[后台清理] 已清理并行识别器缓存")
                    except ImportError:
                        pass
                    except Exception as e:
                        logging.warning(f"[后台清理] 并行识别器缓存清理失败: {e}")
                except Exception as e:
                    logging.warning(f"[后台清理] 图片识别缓存清理失败: {e}")

                # 4. 尝试清理numpy数组缓存（如果有）
                try:
                    import numpy as np
                    if hasattr(np, '_clear_internal_caches'):
                        np._clear_internal_caches()
                        logging.debug("[后台清理] numpy缓存已清理")
                except Exception:
                    pass

                # 5. 清理OpenCV缓存（如果有）
                try:
                    import cv2
                    if hasattr(cv2, 'destroyAllWindows'):
                        cv2.destroyAllWindows()
                except Exception:
                    pass

                # 6. 主动触发GC，尽快回收可释放对象
                try:
                    import gc
                    gc.collect()
                except Exception:
                    pass

                # 6.1 主进程工作集修剪（不改业务逻辑，仅做内存回收）
                try:
                    trimmed_mb = _trim_main_process_memory()
                    if trimmed_mb > 1.0:
                        logging.debug(f"[后台清理] 主进程内存修剪完成，释放约 {trimmed_mb:.1f} MB")
                except Exception as e:
                    logging.debug(f"[后台清理] 主进程内存修剪失败: {e}")

                # 7. 输出内存使用统计
                try:
                    import psutil
                    process = psutil.Process()
                    memory_after = process.memory_info().rss / 1024 / 1024

                    if memory_before > 0:
                        memory_freed = memory_before - memory_after
                        if memory_freed > 0:
                            logging.debug(f"[后台清理] 内存清理效果: 释放 {memory_freed:.1f} MB")
                        elif memory_freed < -5:
                            logging.warning(f"[后台清理] 清理期间内存增加了 {abs(memory_freed):.1f} MB")
                        else:
                            logging.debug(f"[后台清理] 当前内存占用: {memory_after:.1f} MB (变化: {memory_freed:+.1f} MB)")
                    else:
                        logging.debug(f"[后台清理] 当前内存占用: {memory_after:.1f} MB")
                except Exception:
                    pass

                logging.debug("[后台清理] 资源清理完成")
            except Exception as e:
                logging.error(f"[后台清理] 资源清理失败: {e}")
                import traceback
                logging.error(traceback.format_exc())

        self._start_background_thread(
            target=cleanup_resources_background,
            daemon=True,
            name="Resource-Cleanup",
        )
        logging.debug("[后台清理] 资源清理线程已启动，不阻塞UI")

        # 发出状态变化信号
        self.task_state_changed.emit("stopped")

        if old_state != "stopped":
            logging.info(f"任务状态: {old_state} -> stopped (已完全停止)")
        else:
            logging.info("任务状态: 确认已停止，重置所有锁定标志")

    def confirm_started(self):
        """确认任务已启动"""
        if self._current_state == "starting":
            self._current_state = "running"
            self._state_lock = False  # 启动完成后释放锁
            self.task_state_changed.emit("running")
            logging.info("任务状态: 已成功启动并运行")

    def reset_state(self):
        """重置状态 (应急使用)"""
        logging.warning("强制重置任务状态管理器")
        self.shutdown(timeout=0.5)
        self._current_state = "stopped"
        self._state_lock = False
        self._stop_request_pending = False
        self.task_state_changed.emit("stopped")

