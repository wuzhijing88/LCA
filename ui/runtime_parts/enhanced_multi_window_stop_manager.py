"""
增强的多窗口停止管理器
基于网上最佳实践，实现完善的多窗口任务停止机制
"""
import logging
import threading
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Callable, Any, Set
from PySide6.QtCore import QObject, Signal, QTimer

logger = logging.getLogger(__name__)

# 导入OCR停止管理器
try:
    from services.enhanced_ocr_pool_stop_manager import get_ocr_stop_manager
    OCR_STOP_MANAGER_AVAILABLE = True
except ImportError:
    OCR_STOP_MANAGER_AVAILABLE = False
    logger.warning("OCR停止管理器不可用")


class StopState(Enum):
    """停止状态枚举"""
    RUNNING = "running"
    STOP_REQUESTED = "stop_requested"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FORCE_STOPPED = "force_stopped"
    ERROR = "error"


@dataclass
class StopRequest:
    """停止请求"""
    request_id: str
    timestamp: float
    timeout_seconds: float = 30.0
    force_after_timeout: bool = True
    callback: Optional[Callable] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WindowStopContext:
    """窗口停止上下文"""
    window_id: str
    title: str
    hwnd: int
    thread: Optional[object] = None
    executor: Optional[object] = None
    state: StopState = StopState.RUNNING
    stop_event: Optional[threading.Event] = None
    stop_requested_at: Optional[float] = None
    stopped_at: Optional[float] = None
    error_message: Optional[str] = None
    cleanup_callbacks: List[Callable] = field(default_factory=list)


class EnhancedStopSignalManager:
    """增强的停止信号管理器"""
    
    def __init__(self):
        self._global_stop_event = threading.Event()
        self._window_stop_events: Dict[str, threading.Event] = {}
        self._stop_callbacks: Dict[str, List[Callable]] = {}
        self._lock = threading.RLock()
        
    def create_window_stop_event(self, window_id: str) -> threading.Event:
        """为窗口创建停止事件"""
        with self._lock:
            if window_id not in self._window_stop_events:
                self._window_stop_events[window_id] = threading.Event()
            return self._window_stop_events[window_id]
    
    def register_stop_callback(self, window_id: str, callback: Callable):
        """注册停止回调"""
        with self._lock:
            if window_id not in self._stop_callbacks:
                self._stop_callbacks[window_id] = []
            self._stop_callbacks[window_id].append(callback)
    
    def request_stop(self, window_id: Optional[str] = None):
        """请求停止"""
        with self._lock:
            if window_id:
                # 停止特定窗口
                if window_id in self._window_stop_events:
                    self._window_stop_events[window_id].set()
                    self._execute_callbacks(window_id)
            else:
                # 停止所有窗口
                self._global_stop_event.set()
                for event in self._window_stop_events.values():
                    event.set()
                for window_id in self._window_stop_events.keys():
                    self._execute_callbacks(window_id)
    
    def _execute_callbacks(self, window_id: str):
        """执行停止回调"""
        callbacks = self._stop_callbacks.get(window_id, [])
        for callback in callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"执行停止回调失败 {window_id}: {e}")
    
    def is_stop_requested(self, window_id: Optional[str] = None) -> bool:
        """检查是否请求停止"""
        if self._global_stop_event.is_set():
            return True
        if window_id and window_id in self._window_stop_events:
            return self._window_stop_events[window_id].is_set()
        return False
    
    def cleanup(self):
        """清理资源"""
        with self._lock:
            self._global_stop_event.clear()
            self._window_stop_events.clear()
            self._stop_callbacks.clear()


class GracefulThreadStopper:
    """优雅的线程停止器"""
    
    @staticmethod
    def stop_thread_gracefully(thread, timeout: float = 5.0) -> bool:
        """优雅停止线程"""
        if not thread or not thread.isRunning():
            return True
        
        try:
            # 1. 请求停止
            if hasattr(thread, 'request_stop'):
                thread.request_stop()
            elif hasattr(thread, 'stop'):
                thread.stop()
            if hasattr(thread, 'requestInterruption'):
                thread.requestInterruption()
            
            # 2. 等待线程自然结束
            thread.quit()
            if thread.wait(int(timeout * 1000)):
                logger.debug(f"线程优雅停止成功")
                return True
            
            # 3. 不使用 terminate()（可能导致闪退）；保留引用并报告失败
            logger.error(f"线程未在 {timeout}s 内停止（已放弃强制终止，避免闪退）")
            return False
            
        except Exception as e:
            logger.error(f"停止线程失败: {e}")
            return False
    
    @staticmethod
    def stop_executor_gracefully(executor, timeout: float = 5.0) -> bool:
        """优雅停止执行器"""
        if not executor:
            return True
        
        try:
            # 1. 请求停止
            if hasattr(executor, 'request_stop'):
                try:
                    executor.request_stop(force=True)
                except TypeError:
                    executor.request_stop()
            
            # 2. 等待完成
            start_time = time.time()
            while hasattr(executor, '_is_running') and executor._is_running:
                if time.time() - start_time > timeout:
                    logger.warning(f"执行器未在 {timeout}s 内停止")
                    return False
                time.sleep(0.1)
            
            return True
            
        except Exception as e:
            logger.error(f"停止执行器失败: {e}")
            return False


class ResourceCleanupManager:
    """资源清理管理器"""
    
    def __init__(self):
        self._cleanup_tasks: List[Callable] = []
        self._lock = threading.Lock()
    
    def register_cleanup(self, cleanup_func: Callable):
        """注册清理函数"""
        with self._lock:
            self._cleanup_tasks.append(cleanup_func)
    
    def cleanup_all(self, timeout: float = 10.0):
        """清理所有资源"""
        with self._lock:
            cleanup_tasks = self._cleanup_tasks.copy()
        
        # 使用线程池并行清理
        with ThreadPoolExecutor(max_workers=5, thread_name_prefix="cleanup") as executor:
            futures = []
            for cleanup_func in cleanup_tasks:
                future = executor.submit(self._safe_cleanup, cleanup_func)
                futures.append(future)
            
            # 等待所有清理任务完成
            completed = 0
            for future in as_completed(futures, timeout=timeout):
                try:
                    future.result()
                    completed += 1
                except Exception as e:
                    logger.error(f"清理任务失败: {e}")
        
        logger.info(f"资源清理完成: {completed}/{len(cleanup_tasks)}")
        
        # 清空任务列表
        with self._lock:
            self._cleanup_tasks.clear()
    
    @staticmethod
    def _safe_cleanup(cleanup_func: Callable):
        """安全执行清理函数"""
        try:
            cleanup_func()
        except Exception as e:
            logger.error(f"清理函数执行失败: {e}")
            raise


class EnhancedMultiWindowStopManager(QObject):
    """增强的多窗口停止管理器"""
    
    # 信号定义
    stop_requested = Signal(str)  # window_id
    stop_progress = Signal(str, str)  # window_id, status
    stop_completed = Signal(str, bool)  # window_id, success
    all_stopped = Signal(bool, str)  # success, message
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 核心组件
        self.signal_manager = EnhancedStopSignalManager()
        self.thread_stopper = GracefulThreadStopper()
        self.cleanup_manager = ResourceCleanupManager()

        # OCR服务池停止管理器
        self.ocr_stop_manager = None
        if OCR_STOP_MANAGER_AVAILABLE:
            try:
                self.ocr_stop_manager = get_ocr_stop_manager()
                logger.info("已集成OCR服务池停止管理器")
            except Exception as e:
                logger.warning(f"初始化OCR停止管理器失败: {e}")
        else:
            logger.info("OCR停止管理器不可用，跳过集成")
        
        # 窗口上下文管理
        self.window_contexts: Dict[str, WindowStopContext] = {}
        self._main_lock = threading.RLock()
        
        # 停止请求管理
        self.current_request: Optional[StopRequest] = None
        self._stop_in_progress = False
        
        # 监控定时器
        self.monitor_timer = QTimer(self)
        self.monitor_timer.timeout.connect(self._monitor_stop_progress)
        
        # 统计信息
        self.stop_stats = {
            'total_requests': 0,
            'successful_stops': 0,
            'forced_stops': 0,
            'failed_stops': 0,
            'average_stop_time': 0.0
        }

    def register_window(self, window_id: str, title: str, hwnd: int,
                       thread=None, executor=None) -> WindowStopContext:
        """注册窗口"""
        with self._main_lock:
            context = WindowStopContext(
                window_id=window_id,
                title=title,
                hwnd=hwnd,
                thread=thread,
                executor=executor,
                stop_event=self.signal_manager.create_window_stop_event(window_id)
            )
            self.window_contexts[window_id] = context

            # 注册清理回调
            if thread:
                self.cleanup_manager.register_cleanup(
                    lambda: self.thread_stopper.stop_thread_gracefully(thread)
                )
            if executor:
                self.cleanup_manager.register_cleanup(
                    lambda: self.thread_stopper.stop_executor_gracefully(executor)
                )

            logger.info(f"注册窗口: {title} ({window_id})")
            return context

    def request_stop_all(self, timeout: float = 30.0,
                        callback: Optional[Callable] = None,
                        force: bool = False) -> str:
        """请求停止所有窗口"""
        with self._main_lock:
            if self._stop_in_progress:
                logger.info("停止操作已在进行中，但仍然允许新的停止请求")
                # 删除限制：不再阻止重复停止请求
                self._stop_in_progress = False  # 重置状态，允许重新停止

            request_id = f"stop_all_{int(time.time() * 1000)}"
            self.current_request = StopRequest(
                request_id=request_id,
                timestamp=time.time(),
                timeout_seconds=timeout,
                callback=callback
            )
            self._force_stop_all = bool(force)

            self._stop_in_progress = True
            self.stop_stats['total_requests'] += 1

            logger.info(f"开始停止所有窗口 (请求ID: {request_id})")

            # 启动停止流程
            self._start_stop_process()

            return request_id

    def request_stop_window(self, window_id: str, timeout: float = 15.0) -> bool:
        """请求停止特定窗口"""
        with self._main_lock:
            if window_id not in self.window_contexts:
                logger.warning(f"窗口不存在: {window_id}")
                return False

            context = self.window_contexts[window_id]
            if context.state != StopState.RUNNING:
                logger.info(f"窗口已在停止流程中: {window_id}")
                return True

            # 更新状态
            context.state = StopState.STOP_REQUESTED
            context.stop_requested_at = time.time()

            # 发送停止信号
            self.signal_manager.request_stop(window_id)
            self.stop_requested.emit(window_id)

            # 启动单窗口停止
            self._stop_single_window(context, timeout)

            return True

    def _start_stop_process(self):
        """启动停止流程"""
        # 发送全局停止信号
        self.signal_manager.request_stop()

        # 启动监控
        self.monitor_timer.start(500)  # 每500ms检查一次

        # 在后台线程中执行停止操作
        stop_thread = threading.Thread(
            target=self._execute_stop_all,
            name="MultiWindowStopper",
            daemon=True
        )
        stop_thread.start()

    def _execute_stop_all(self):
        """执行停止所有窗口的操作"""
        start_time = time.time()
        success_count = 0
        force_count = 0
        failed_count = 0
        force_stop_all = bool(getattr(self, "_force_stop_all", False))

        try:
            # 第一阶段：并行请求所有窗口停止
            logger.info("第一阶段：请求所有窗口停止")
            with self._main_lock:
                windows_to_stop = list(self.window_contexts.values())

            for context in windows_to_stop:
                if context.state == StopState.RUNNING:
                    context.state = StopState.STOP_REQUESTED
                    context.stop_requested_at = time.time()
                    self.stop_progress.emit(context.window_id, "请求停止")

            # 第二阶段：优雅停止（并行）
            logger.info("第二阶段：优雅停止执行器和线程")
            with ThreadPoolExecutor(max_workers=10, thread_name_prefix="graceful_stop") as executor:
                futures = []
                for context in windows_to_stop:
                    if context.state == StopState.STOP_REQUESTED:
                        future = executor.submit(self._graceful_stop_window, context, force_stop_all)
                        futures.append((future, context))

                # 等待优雅停止完成
                timeout = self.current_request.timeout_seconds * 0.7  # 70%时间用于优雅停止
                for future, context in futures:
                    try:
                        if future.result(timeout=timeout / len(futures)):
                            success_count += 1
                            context.state = StopState.STOPPED
                            context.stopped_at = time.time()
                            self.stop_progress.emit(context.window_id, "已停止")
                            self.stop_completed.emit(context.window_id, True)
                        else:
                            context.state = StopState.STOPPING
                    except Exception as e:
                        logger.error(f"优雅停止窗口失败 {context.window_id}: {e}")
                        context.state = StopState.STOPPING
                        context.error_message = str(e)

            # 第三阶段：强制停止未完成的窗口
            remaining_windows = [ctx for ctx in windows_to_stop
                               if ctx.state == StopState.STOPPING]

            if remaining_windows:
                logger.info(f"第三阶段：强制停止 {len(remaining_windows)} 个窗口")
                for context in remaining_windows:
                    try:
                        if self._force_stop_window(context):
                            force_count += 1
                            context.state = StopState.FORCE_STOPPED
                            self.stop_progress.emit(context.window_id, "强制停止")
                            self.stop_completed.emit(context.window_id, True)
                        else:
                            failed_count += 1
                            context.state = StopState.ERROR
                            self.stop_progress.emit(context.window_id, "停止失败")
                            self.stop_completed.emit(context.window_id, False)
                    except Exception as e:
                        logger.error(f"强制停止窗口失败 {context.window_id}: {e}")
                        failed_count += 1
                        context.state = StopState.ERROR
                        context.error_message = str(e)

            # 第四阶段：OCR服务池清理
            logger.info("第四阶段：清理OCR服务池")
            if self.ocr_stop_manager:
                try:
                    # 同步OCR服务池状态
                    from services.multiprocess_ocr_pool import get_multi_ocr_pool
                    ocr_pool = get_multi_ocr_pool()
                    self.ocr_stop_manager.sync_with_ocr_pool(ocr_pool)

                    # 收集需要停止的窗口句柄
                    window_hwnds = [ctx.hwnd for ctx in windows_to_stop]

                    # 停止对应的OCR服务
                    if window_hwnds:
                        logger.info(f"停止 {len(window_hwnds)} 个窗口的OCR服务")
                        self.ocr_stop_manager.request_stop_services_for_windows(
                            window_hwnds, timeout=5.0
                        )

                except Exception as e:
                    logger.error(f"OCR服务池清理失败: {e}")

            # 第五阶段：其他资源清理
            logger.info("第五阶段：清理其他资源")
            self.cleanup_manager.cleanup_all(timeout=5.0)

        except Exception as e:
            logger.error(f"停止流程执行失败: {e}", exc_info=True)
            failed_count = len(windows_to_stop)

        finally:
            # 完成停止流程
            self._finalize_stop_process(start_time, success_count, force_count, failed_count)

    def _graceful_stop_window(self, context: WindowStopContext, force: bool = False) -> bool:
        """优雅停止单个窗口"""
        try:
            self.stop_progress.emit(context.window_id, "正在停止执行器")

            # 停止执行器
            if context.executor:
                if not self.thread_stopper.stop_executor_gracefully(context.executor, 3.0 if not force else 1.0):
                    logger.warning(f"执行器停止超时: {context.window_id}")
                    return False

            self.stop_progress.emit(context.window_id, "正在停止线程")

            # 停止线程
            if context.thread:
                if not self.thread_stopper.stop_thread_gracefully(context.thread, 3.0):
                    logger.warning(f"线程停止超时: {context.window_id}")
                    return False

            return True

        except Exception as e:
            logger.error(f"优雅停止窗口失败 {context.window_id}: {e}")
            context.error_message = str(e)
            return False

    def _force_stop_window(self, context: WindowStopContext) -> bool:
        """强制停止单个窗口"""
        try:
            self.stop_progress.emit(context.window_id, "强制停止中")

            # 不使用 terminate()（可能导致闪退）；尽可能请求停止并等待
            if context.thread and context.thread.isRunning():
                logger.warning(f"线程仍在运行，尝试强制请求退出: {context.window_id}")
                try:
                    if hasattr(context.thread, 'request_stop'):
                        context.thread.request_stop()
                    elif hasattr(context.thread, 'stop'):
                        context.thread.stop()
                    if hasattr(context.thread, 'requestInterruption'):
                        context.thread.requestInterruption()
                    context.thread.quit()
                    if not context.thread.wait(3000):
                        logger.error(f"线程未能停止（放弃terminate以避免闪退）: {context.window_id}")
                        return False
                except Exception as e:
                    logger.error(f"停止线程失败 {context.window_id}: {e}")
                    return False

            # 强制停止执行器
            if context.executor:
                if hasattr(context.executor, 'request_stop'):
                    try:
                        context.executor.request_stop(force=True)
                    except TypeError:
                        context.executor.request_stop()
                    except Exception as e:
                        logger.error(f"强制停止执行器失败 {context.window_id}: {e}")
                        return False
                if hasattr(context.executor, '_is_running'):
                    context.executor._is_running = False

            return True

        except Exception as e:
            logger.error(f"强制停止窗口失败 {context.window_id}: {e}")
            context.error_message = str(e)
            return False

    def _stop_single_window(self, context: WindowStopContext, timeout: float):
        """停止单个窗口（后台线程）"""
        def stop_worker():
            try:
                if self._graceful_stop_window(context):
                    context.state = StopState.STOPPED
                    context.stopped_at = time.time()
                    self.stop_completed.emit(context.window_id, True)
                else:
                    # 尝试强制停止
                    if self._force_stop_window(context):
                        context.state = StopState.FORCE_STOPPED
                        context.stopped_at = time.time()
                        self.stop_completed.emit(context.window_id, True)
                    else:
                        context.state = StopState.ERROR
                        self.stop_completed.emit(context.window_id, False)
            except Exception as e:
                logger.error(f"停止窗口失败 {context.window_id}: {e}")
                context.state = StopState.ERROR
                context.error_message = str(e)
                self.stop_completed.emit(context.window_id, False)

        thread = threading.Thread(target=stop_worker, name=f"StopWindow_{context.window_id}")
        thread.daemon = True
        thread.start()

    def _finalize_stop_process(self, start_time: float, success_count: int,
                              force_count: int, failed_count: int):
        """完成停止流程"""
        try:
            # 停止监控
            self.monitor_timer.stop()
            self._force_stop_all = False

            # 更新统计
            total_time = time.time() - start_time
            self.stop_stats['successful_stops'] += success_count
            self.stop_stats['forced_stops'] += force_count
            self.stop_stats['failed_stops'] += failed_count

            # 更新平均停止时间
            total_stops = self.stop_stats['successful_stops'] + self.stop_stats['forced_stops']
            if total_stops > 0:
                self.stop_stats['average_stop_time'] = (
                    (self.stop_stats['average_stop_time'] * (total_stops - success_count - force_count) +
                     total_time * (success_count + force_count)) / total_stops
                )

            # 生成结果消息
            total_windows = success_count + force_count + failed_count
            success = failed_count == 0

            if success:
                message = f"多窗口停止完成 - 总计: {total_windows}, 成功: {success_count}"
                if force_count > 0:
                    message += f", 强制停止: {force_count}"
                message += f", 耗时: {total_time:.1f}秒"
            else:
                message = f"多窗口停止部分失败 - 总计: {total_windows}, 成功: {success_count}, 强制: {force_count}, 失败: {failed_count}"

            logger.info(message)

            # 执行回调
            if self.current_request and self.current_request.callback:
                try:
                    self.current_request.callback(success, message)
                except Exception as e:
                    logger.error(f"执行停止回调失败: {e}")

            # 发送完成信号
            self.all_stopped.emit(success, message)

        finally:
            # 重置状态
            with self._main_lock:
                self._stop_in_progress = False
                self.current_request = None

    def _monitor_stop_progress(self):
        """监控停止进度"""
        if not self.current_request:
            self.monitor_timer.stop()
            return

        elapsed = time.time() - self.current_request.timestamp

        # 检查超时
        if elapsed > self.current_request.timeout_seconds:
            logger.warning(f"停止操作超时 ({elapsed:.1f}s)")
            self.monitor_timer.stop()

            # 强制完成
            if self.current_request.force_after_timeout:
                self._force_complete_stop()

        # 检查是否所有窗口都已停止
        with self._main_lock:
            all_stopped = all(
                ctx.state in [StopState.STOPPED, StopState.FORCE_STOPPED, StopState.ERROR]
                for ctx in self.window_contexts.values()
            )

            if all_stopped:
                logger.info("所有窗口已停止，结束监控")
                self.monitor_timer.stop()

    def _force_complete_stop(self):
        """强制完成停止操作"""
        logger.warning("强制完成停止操作")

        with self._main_lock:
            for context in self.window_contexts.values():
                if context.state not in [StopState.STOPPED, StopState.FORCE_STOPPED, StopState.ERROR]:
                    context.state = StopState.FORCE_STOPPED
                    context.stopped_at = time.time()

        # 强制清理资源
        self.cleanup_manager.cleanup_all(timeout=2.0)

        # 发送完成信号
        self.all_stopped.emit(False, "停止操作超时，已强制完成")

        self._stop_in_progress = False
        self.current_request = None

    def get_stop_status(self) -> Dict[str, Any]:
        """获取停止状态"""
        with self._main_lock:
            status = {
                'stop_in_progress': self._stop_in_progress,
                'current_request': self.current_request.request_id if self.current_request else None,
                'window_states': {
                    window_id: {
                        'state': ctx.state.value,
                        'title': ctx.title,
                        'stop_requested_at': ctx.stop_requested_at,
                        'stopped_at': ctx.stopped_at,
                        'error_message': ctx.error_message
                    }
                    for window_id, ctx in self.window_contexts.items()
                },
                'statistics': self.stop_stats.copy()
            }

            return status

    def cleanup(self):
        """清理管理器资源"""
        logger.info("清理多窗口停止管理器")

        # 停止监控
        self.monitor_timer.stop()

        # 清理OCR停止管理器
        if self.ocr_stop_manager:
            try:
                self.ocr_stop_manager.cleanup()
                logger.debug("OCR停止管理器已清理")
            except Exception as e:
                logger.error(f"清理OCR停止管理器失败: {e}")

        # 清理信号管理器
        self.signal_manager.cleanup()

        # 清理资源管理器
        self.cleanup_manager.cleanup_all(timeout=3.0)

        # 清理窗口上下文
        with self._main_lock:
            self.window_contexts.clear()
            self._stop_in_progress = False
            self.current_request = None
