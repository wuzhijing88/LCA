"""
统一多窗口执行器 - 现代异步执行架构
整合基础功能、高级功能、智能功能和可扩展功能于一体
支持 async/await、协程、流式处理和优雅的错误处理
"""

import asyncio
import logging
import time
import threading
from typing import Dict, List, Optional, Any, Callable, AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from collections import defaultdict, deque

from app_core.runtime.execution_coordinator import (
    ExecutionSource,
    create_coordinated_workflow_runtime,
)
from task_workflow.thread_start import THREAD_START_TASK_TYPE, is_thread_start_task_type

# PySide6 异步支持
from PySide6.QtCore import QObject, Signal, QThread
try:
    QTASYNCIO_AVAILABLE = True
except ImportError:
    QTASYNCIO_AVAILABLE = False
    logging.warning("PySide6.QtAsyncio 不可用，将使用传统异步模式")

# 增强停止管理器

logger = logging.getLogger(__name__)

# 执行模式枚举
class ExecutionMode(Enum):
    PARALLEL = "parallel"           # 并行执行（默认）
    SEQUENTIAL = "sequential"       # 顺序执行
    BATCH = "batch"                # 批处理执行
    SYNCHRONIZED = "synchronized"   # 同步执行
    STREAMING = "streaming"         # 流式执行（新增）
    ADAPTIVE = "adaptive"           # 自适应执行（新增）

# 同步点枚举
class SyncPoint(Enum):
    START = "start"
    WORKFLOW_READY = "workflow_ready"
    EXECUTION_BEGIN = "execution_begin"
    STEP_COMPLETE = "step_complete"
    FINISH = "finish"

# 任务状态枚举
class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"

# 执行结果数据类
@dataclass
class ExecutionResult:
    """异步执行结果"""
    success: bool
    window_title: str
    window_hwnd: int
    execution_time: float
    error: Optional[Exception] = None
    data: Optional[Dict[str, Any]] = None
    retry_count: int = 0
    status: TaskStatus = TaskStatus.COMPLETED

@dataclass
class WindowExecutionState:
    """窗口执行状态 - 增强版"""
    title: str
    hwnd: int
    enabled: bool = True
    thread: Optional[QThread] = None
    executor: Optional[Any] = None  # WorkflowExecutor
    current_step: str = "idle"
    progress: float = 0.0
    error_count: int = 0
    last_sync_point: Optional[SyncPoint] = None
    execution_data: Dict[str, Any] = field(default_factory=dict)
    execution_completed: bool = False
    last_message: str = ""
    last_result_success: Optional[bool] = None
    last_error_message: str = ""
    last_failed_card_id: Optional[int] = None

    # 异步执行增强字段
    task: Optional[asyncio.Task] = None
    status: TaskStatus = TaskStatus.PENDING
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    retry_count: int = 0
    last_error: Optional[Exception] = None
    cancellation_token: Optional[asyncio.Event] = field(default_factory=asyncio.Event)
    resource_locks: Dict[str, asyncio.Semaphore] = field(default_factory=dict)

    def reset(self):
        """重置窗口状态"""
        # 【内存泄漏修复】先清理executor的信号连接，防止内存泄漏
        if self.executor is not None:
            try:
                # 断开所有信号连接
                if hasattr(self.executor, 'execution_finished'):
                    try:
                        self.executor.execution_finished.disconnect()
                    except (RuntimeError, TypeError):
                        pass  # 信号可能已经断开或从未连接
                if hasattr(self.executor, 'execution_started'):
                    try:
                        self.executor.execution_started.disconnect()
                    except (RuntimeError, TypeError):
                        pass
                if hasattr(self.executor, 'card_executing'):
                    try:
                        self.executor.card_executing.disconnect()
                    except (RuntimeError, TypeError):
                        pass
                if hasattr(self.executor, 'card_finished'):
                    try:
                        self.executor.card_finished.disconnect()
                    except (RuntimeError, TypeError):
                        pass
                if hasattr(self.executor, 'step_details'):
                    try:
                        self.executor.step_details.disconnect()
                    except (RuntimeError, TypeError):
                        pass
                if hasattr(self.executor, 'error_occurred'):
                    try:
                        self.executor.error_occurred.disconnect()
                    except (RuntimeError, TypeError):
                        pass
                # 调用executor的deleteLater（如果是QObject）
                if hasattr(self.executor, 'deleteLater'):
                    try:
                        self.executor.deleteLater()
                    except (RuntimeError, AttributeError):
                        pass
            except Exception as e:
                import logging
                logging.getLogger(__name__).debug(f"清理executor信号时异常（可忽略）: {e}")

        self.thread = None
        self.executor = None
        self.current_step = "idle"
        self.progress = 0.0
        self.error_count = 0
        self.last_sync_point = None
        self.execution_data.clear()
        self.execution_completed = False
        self.last_message = ""
        self.last_result_success = None
        self.last_error_message = ""
        self.last_failed_card_id = None

        # 重置异步字段
        if self.task and not self.task.done():
            self.task.cancel()
        self.task = None
        self.status = TaskStatus.PENDING
        self.start_time = None
        self.end_time = None
        self.retry_count = 0
        self.last_error = None
        if self.cancellation_token:
            self.cancellation_token.clear()
        self.resource_locks.clear()

    @property
    def execution_time(self) -> Optional[float]:
        """计算执行时间"""
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        elif self.start_time:
            return time.time() - self.start_time
        return None

@dataclass
class SynchronizationConfig:
    """同步配置"""
    mode: ExecutionMode = ExecutionMode.PARALLEL
    sync_points: List[SyncPoint] = field(default_factory=lambda: [SyncPoint.START, SyncPoint.FINISH])
    timeout_seconds: float = 300.0
    enable_step_sync: bool = False
    batch_size: int = 3

class AsyncResourceManager:
    """现代异步资源管理器"""

    def __init__(self, max_concurrent_windows: int = 10, max_ocr_concurrent: int = 3):
        # 异步信号量控制
        self.window_semaphore = asyncio.Semaphore(max_concurrent_windows)
        self.ocr_semaphore = asyncio.Semaphore(max_ocr_concurrent)
        self.network_semaphore = asyncio.Semaphore(5)

        # 资源锁字典
        self._async_locks: Dict[str, asyncio.Lock] = {}
        self._counters: Dict[str, int] = defaultdict(int)
        self._main_lock = asyncio.Lock()

        # 背压控制
        self.task_queue = asyncio.Queue(maxsize=100)
        self.result_queue = asyncio.Queue(maxsize=50)

        # 资源使用统计
        self.resource_stats = {
            'windows_active': 0,
            'ocr_active': 0,
            'network_active': 0,
            'total_tasks_processed': 0,
            'failed_tasks': 0
        }

    async def get_async_lock(self, resource_name: str) -> asyncio.Lock:
        """获取异步资源锁"""
        async with self._main_lock:
            if resource_name not in self._async_locks:
                self._async_locks[resource_name] = asyncio.Lock()
            return self._async_locks[resource_name]

    async def get_window_lock(self, hwnd: int) -> asyncio.Lock:
        """获取窗口专用异步锁"""
        return await self.get_async_lock(f"window_{hwnd}")

    @asynccontextmanager
    async def acquire_window_resource(self, window_title: str):
        """异步获取窗口资源"""
        await self.window_semaphore.acquire()
        self.resource_stats['windows_active'] += 1
        try:
            logger.debug(f"获取窗口资源: {window_title}")
            yield
        finally:
            self.window_semaphore.release()
            self.resource_stats['windows_active'] -= 1
            logger.debug(f"释放窗口资源: {window_title}")

    @asynccontextmanager
    async def acquire_ocr_resource(self):
        """异步获取OCR资源"""
        await self.ocr_semaphore.acquire()
        self.resource_stats['ocr_active'] += 1
        try:
            yield
        finally:
            self.ocr_semaphore.release()
            self.resource_stats['ocr_active'] -= 1

    @asynccontextmanager
    async def acquire_network_resource(self):
        """异步获取网络资源"""
        await self.network_semaphore.acquire()
        self.resource_stats['network_active'] += 1
        try:
            yield
        finally:
            self.network_semaphore.release()
            self.resource_stats['network_active'] -= 1

    async def increment_counter(self, counter_name: str) -> int:
        """异步原子计数器"""
        async with self._main_lock:
            self._counters[counter_name] += 1
            return self._counters[counter_name]

    async def get_resource_stats(self) -> Dict[str, Any]:
        """获取资源使用统计"""
        return {
            **self.resource_stats,
            'queue_depth': self.task_queue.qsize(),
            'result_queue_depth': self.result_queue.qsize(),
            'active_locks': len(self._async_locks)
        }

    async def cleanup(self):
        """异步清理资源"""
        async with self._main_lock:
            self._async_locks.clear()
            self._counters.clear()

            # 清空队列
            while not self.task_queue.empty():
                try:
                    self.task_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

            while not self.result_queue.empty():
                try:
                    self.result_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

class SynchronizationManager:
    """同步管理器"""
    
    def __init__(self, config: SynchronizationConfig):
        self.config = config
        self._barriers = {}
        self._events = {}
        self._main_lock = threading.RLock()
        self._active_windows = 0
    
    def setup_synchronization(self, window_count: int):
        """设置同步机制"""
        with self._main_lock:
            self._active_windows = window_count
            
            # 为每个同步点创建屏障
            for sync_point in self.config.sync_points:
                barrier_name = f"barrier_{sync_point.value}"
                self._barriers[barrier_name] = threading.Barrier(window_count)
                
                event_name = f"event_{sync_point.value}"
                self._events[event_name] = threading.Event()
    
    def wait_at_sync_point(self, sync_point: SyncPoint, window_title: str, timeout: Optional[float] = None) -> bool:
        """在同步点等待"""
        if self.config.mode == ExecutionMode.PARALLEL:
            return True  # 并行模式不需要同步
        
        barrier_name = f"barrier_{sync_point.value}"
        timeout = timeout or self.config.timeout_seconds
        
        try:
            with self._main_lock:
                if barrier_name not in self._barriers:
                    logger.warning(f"同步点 {sync_point.value} 未设置，跳过同步")
                    return True
                
                barrier = self._barriers[barrier_name]
            
            logger.info(f"窗口 {window_title} 到达同步点: {sync_point.value}")
            barrier.wait(timeout)
            logger.info(f"窗口 {window_title} 通过同步点: {sync_point.value}")
            return True
            
        except threading.BrokenBarrierError:
            logger.error(f"窗口 {window_title} 同步点 {sync_point.value} 屏障被破坏")
            return False
        except Exception as e:
            logger.error(f"窗口 {window_title} 同步点 {sync_point.value} 等待失败: {e}")
            return False
    
    def cleanup(self):
        """清理同步资源"""
        with self._main_lock:
            for barrier in self._barriers.values():
                try:
                    barrier.abort()
                except Exception:
                    pass
            self._barriers.clear()
            self._events.clear()

class PerformanceMonitor:
    """性能监控器"""
    
    def __init__(self):
        self._metrics = {}
        self._start_times = {}
        self._lock = threading.Lock()
    
    def start_timing(self, operation: str):
        """开始计时"""
        with self._lock:
            self._start_times[operation] = time.time()
    
    def end_timing(self, operation: str) -> float:
        """结束计时并返回耗时"""
        with self._lock:
            if operation in self._start_times:
                duration = time.time() - self._start_times[operation]
                if operation not in self._metrics:
                    self._metrics[operation] = []
                self._metrics[operation].append(duration)
                del self._start_times[operation]
                return duration
            return 0.0
    
    def get_average_time(self, operation: str) -> float:
        """获取平均耗时"""
        with self._lock:
            if operation in self._metrics and self._metrics[operation]:
                return sum(self._metrics[operation]) / len(self._metrics[operation])
            return 0.0
    
    def cleanup(self):
        """清理监控数据"""
        with self._lock:
            self._metrics.clear()
            self._start_times.clear()

class AsyncErrorHandler:
    """异步错误处理器"""

    def __init__(self):
        self.retry_config = {
            'max_retries': 3,
            'backoff_factor': 2.0,
            'max_backoff': 60.0,
            'retryable_exceptions': (
                ConnectionError, TimeoutError, OSError,
                asyncio.TimeoutError, asyncio.CancelledError
            )
        }
        self.circuit_breaker_config = {
            'failure_threshold': 5,
            'recovery_timeout': 30.0,
            'half_open_max_calls': 3
        }
        self.circuit_breakers: Dict[str, 'CircuitBreaker'] = {}

    async def execute_with_retry(self, coro_func: Callable, context: str, *args, **kwargs) -> Any:
        """带重试机制的异步执行"""
        last_exception = None

        for attempt in range(self.retry_config['max_retries'] + 1):
            try:
                # 获取或创建熔断器
                circuit_breaker = self._get_circuit_breaker(context)

                async with circuit_breaker:
                    if asyncio.iscoroutinefunction(coro_func):
                        return await coro_func(*args, **kwargs)
                    else:
                        return coro_func(*args, **kwargs)

            except self.retry_config['retryable_exceptions'] as e:
                last_exception = e

                if attempt == self.retry_config['max_retries']:
                    logger.error(f"{context} 最终失败，已重试 {attempt} 次: {e}")
                    raise

                # 计算退避延迟
                delay = min(
                    self.retry_config['backoff_factor'] ** attempt,
                    self.retry_config['max_backoff']
                )

                logger.warning(f"{context} 失败 (尝试 {attempt + 1}/{self.retry_config['max_retries'] + 1})，{delay:.1f}秒后重试: {e}")
                await asyncio.sleep(delay)

            except Exception as e:
                # 非可重试异常，直接抛出
                logger.error(f"{context} 遇到不可重试异常: {e}")
                raise

        # 理论上不会到达这里
        if last_exception:
            raise last_exception

    def _get_circuit_breaker(self, context: str) -> 'CircuitBreaker':
        """获取或创建熔断器"""
        if context not in self.circuit_breakers:
            self.circuit_breakers[context] = CircuitBreaker(
                failure_threshold=self.circuit_breaker_config['failure_threshold'],
                recovery_timeout=self.circuit_breaker_config['recovery_timeout'],
                half_open_max_calls=self.circuit_breaker_config['half_open_max_calls']
            )
        return self.circuit_breakers[context]

class CircuitBreaker:
    """异步熔断器"""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0, half_open_max_calls: int = 3):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self.failure_count = 0
        self.last_failure_time = None
        self.state = 'closed'  # closed, open, half_open
        self.half_open_calls = 0
        self._lock = asyncio.Lock()

    async def __aenter__(self):
        async with self._lock:
            if self.state == 'open':
                if time.time() - self.last_failure_time > self.recovery_timeout:
                    self.state = 'half_open'
                    self.half_open_calls = 0
                    logger.info("熔断器进入半开状态")
                else:
                    raise Exception("熔断器处于开启状态，拒绝请求")

            elif self.state == 'half_open':
                if self.half_open_calls >= self.half_open_max_calls:
                    raise Exception("熔断器半开状态达到最大调用次数")
                self.half_open_calls += 1

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        async with self._lock:
            if exc_type is None:
                # 成功执行
                if self.state == 'half_open':
                    self.state = 'closed'
                    self.failure_count = 0
                    logger.info("熔断器恢复到关闭状态")
                elif self.state == 'closed':
                    self.failure_count = max(0, self.failure_count - 1)
            else:
                # 执行失败
                self.failure_count += 1
                self.last_failure_time = time.time()

                if self.failure_count >= self.failure_threshold:
                    self.state = 'open'
                    logger.warning(f"熔断器开启，失败次数: {self.failure_count}")
                elif self.state == 'half_open':
                    self.state = 'open'
                    logger.warning("熔断器从半开状态回到开启状态")

class DynamicThreadPool:
    """动态线程池 - 保持向后兼容"""

    def __init__(self, min_workers: int = 2, max_workers: int = 10):
        self.min_workers = min_workers
        self.max_workers = max_workers
        self._pool = None
        self._lock = threading.Lock()

    def get_pool(self, required_workers: int) -> ThreadPoolExecutor:
        """获取合适大小的线程池"""
        with self._lock:
            optimal_workers = min(max(required_workers, self.min_workers), self.max_workers)

            if self._pool is None or self._pool._max_workers != optimal_workers:
                if self._pool:
                    self._pool.shutdown(wait=False)
                self._pool = ThreadPoolExecutor(max_workers=optimal_workers)
                logger.info(f"创建动态线程池，工作线程数: {optimal_workers}")

            return self._pool

    def shutdown(self):
        """关闭线程池"""
        with self._lock:
            if self._pool:
                self._pool.shutdown(wait=True)
                self._pool = None

class AsyncStreamProcessor:
    """异步流式处理器"""

    def __init__(self, batch_size: int = 5, batch_timeout: float = 2.0):
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout
        self.task_stream = asyncio.Queue()
        self.result_stream = asyncio.Queue()
        self._processing = False
        self._processor_task = None

    async def submit_task(self, window: WindowExecutionState, workflow_data: dict):
        """提交任务到流式处理器"""
        await self.task_stream.put((window, workflow_data))

    async def start_processing(self, executor_instance):
        """启动流式处理"""
        if self._processing:
            return

        self._processing = True
        self._processor_task = asyncio.create_task(
            self._process_task_stream(executor_instance)
        )
        logger.info("异步流式处理器已启动")

    async def stop_processing(self):
        """停止流式处理"""
        self._processing = False
        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass
        logger.info("异步流式处理器已停止")

    async def _process_task_stream(self, executor_instance):
        """处理任务流"""
        while self._processing:
            try:
                # 收集批次任务
                batch = await self._collect_batch()
                if not batch:
                    continue

                logger.info(f"处理任务批次，大小: {len(batch)}")

                # 并行处理批次
                tasks = [
                    asyncio.create_task(
                        executor_instance._execute_window_async(window, workflow_data)
                    )
                    for window, workflow_data in batch
                ]

                # 等待批次完成
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # 将结果放入结果流
                for result in results:
                    await self.result_stream.put(result)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"流式处理错误: {e}", exc_info=True)

    async def _collect_batch(self) -> List[tuple]:
        """收集批次任务"""
        batch = []
        deadline = time.time() + self.batch_timeout

        while len(batch) < self.batch_size and time.time() < deadline:
            try:
                remaining_time = max(0, deadline - time.time())
                task_data = await asyncio.wait_for(
                    self.task_stream.get(),
                    timeout=remaining_time
                )
                batch.append(task_data)
            except asyncio.TimeoutError:
                break

        return batch

    async def get_results(self) -> AsyncGenerator[ExecutionResult, None]:
        """异步生成器获取结果"""
        while True:
            try:
                result = await self.result_stream.get()
                yield result
            except asyncio.CancelledError:
                break

class AsyncPerformanceMonitor:
    """异步性能监控器"""

    # 【内存泄漏修复】限制task_traces最大条目数，防止无限增长
    MAX_TASK_TRACES = 100

    def __init__(self):
        self.start_times = {}
        self.metrics = {
            'total_windows': 0,
            'successful_windows': 0,
            'failed_windows': 0,
            'cancelled_windows': 0,
            'total_execution_time': 0.0,
            'average_execution_time': 0.0,
            'peak_concurrent_tasks': 0,
            'current_active_tasks': 0
        }
        self.task_traces = {}
        self.performance_history = deque(maxlen=1000)
        self._lock = asyncio.Lock()

    async def start_timing(self, metric_name: str):
        """异步开始计时"""
        async with self._lock:
            self.start_times[metric_name] = time.time()
            self.metrics['current_active_tasks'] += 1
            self.metrics['peak_concurrent_tasks'] = max(
                self.metrics['peak_concurrent_tasks'],
                self.metrics['current_active_tasks']
            )

    async def end_timing(self, metric_name: str) -> float:
        """异步结束计时并返回耗时"""
        async with self._lock:
            if metric_name in self.start_times:
                elapsed = time.time() - self.start_times[metric_name]
                del self.start_times[metric_name]
                self.metrics['current_active_tasks'] -= 1

                # 更新性能历史
                self.performance_history.append({
                    'metric': metric_name,
                    'duration': elapsed,
                    'timestamp': time.time()
                })

                return elapsed
            return 0.0

    def _sync_end_timing(self, metric_name: str) -> float:
        """同步版本的结束计时（用于同步上下文）"""
        try:
            if metric_name in self.start_times:
                elapsed = time.time() - self.start_times[metric_name]
                del self.start_times[metric_name]

                # 更新性能历史（简化版，不使用锁）
                self.performance_history.append({
                    'metric': metric_name,
                    'duration': elapsed,
                    'timestamp': time.time()
                })

                return elapsed
            return 0.0
        except Exception as e:
            logger.warning(f"同步结束计时失败: {e}")
            return 0.0

    async def record_task_result(self, task_id: str, result: ExecutionResult):
        """记录任务结果"""
        async with self._lock:
            self.task_traces[task_id] = {
                'result': result,
                'timestamp': time.time(),
                'execution_time': result.execution_time
            }

            # 【内存泄漏修复】限制task_traces大小，清理最老的条目
            if len(self.task_traces) > self.MAX_TASK_TRACES:
                # 按时间戳排序，删除最老的条目
                sorted_keys = sorted(
                    self.task_traces.keys(),
                    key=lambda k: self.task_traces[k].get('timestamp', 0)
                )
                # 删除最老的一半
                keys_to_remove = sorted_keys[:len(sorted_keys) // 2]
                for key in keys_to_remove:
                    del self.task_traces[key]
                logger.debug(f"[内存优化] 清理了 {len(keys_to_remove)} 条旧的task_traces")

            # 更新统计
            if result.success:
                self.metrics['successful_windows'] += 1
            else:
                self.metrics['failed_windows'] += 1

            if result.status == TaskStatus.CANCELLED:
                self.metrics['cancelled_windows'] += 1

            self.metrics['total_windows'] += 1

            # 更新平均执行时间
            if result.execution_time:
                total_time = self.metrics['total_execution_time'] + result.execution_time
                self.metrics['total_execution_time'] = total_time
                self.metrics['average_execution_time'] = total_time / self.metrics['total_windows']

    async def get_metrics(self) -> Dict[str, Any]:
        """异步获取性能指标"""
        async with self._lock:
            return {
                **self.metrics.copy(),
                'active_timers': len(self.start_times),
                'trace_count': len(self.task_traces),
                'history_count': len(self.performance_history)
            }

    def reset(self):
        """【内存泄漏修复】重置监控器状态，清理所有累积数据"""
        self.start_times.clear()
        self.task_traces.clear()
        self.performance_history.clear()
        self.metrics = {
            'total_windows': 0,
            'successful_windows': 0,
            'failed_windows': 0,
            'cancelled_windows': 0,
            'total_execution_time': 0.0,
            'average_execution_time': 0.0,
            'peak_concurrent_tasks': 0,
            'current_active_tasks': 0
        }
        logger.debug("[内存优化] AsyncPerformanceMonitor已重置")

class CommunicationHub:
    """通信中心"""
    
    def __init__(self):
        self._message_handlers = {}
        self._lock = threading.Lock()
    
    def register_handler(self, message_type: str, handler: Callable):
        """注册消息处理器"""
        with self._lock:
            if message_type not in self._message_handlers:
                self._message_handlers[message_type] = []
            self._message_handlers[message_type].append(handler)
    
    def send_message(self, message_type: str, data: Any):
        """发送消息"""
        with self._lock:
            if message_type in self._message_handlers:
                for handler in self._message_handlers[message_type]:
                    try:
                        handler(data)
                    except Exception as e:
                        logger.error(f"消息处理器执行失败: {e}")
    
    def cleanup(self):
        """清理通信资源"""
        with self._lock:
            self._message_handlers.clear()

class UnifiedMultiWindowExecutor(QObject):
    """统一多窗口执行器 - 合并所有优秀特性"""

    # 信号定义
    execution_progress = Signal(str, float)  # 窗口标题, 进度
    execution_completed = Signal(bool, str)  # 成功状态, 消息
    # 工具 修复：信号格式与主窗口期望一致
    card_executing = Signal(int)            # 卡片ID (与单窗口执行器一致)
    card_finished = Signal(int, bool)       # 卡片ID, 成功状态 (与单窗口执行器一致)
    error_occurred = Signal(str, int, int, str)  # 窗口标题, 窗口句柄, 卡片ID, 错误信息
    show_warning = Signal(str, str)         # title, message

    def __init__(self, parent=None):
        super().__init__(parent)

        # 基础组件
        self.windows: Dict[str, WindowExecutionState] = {}
        self.sync_config = SynchronizationConfig()

        # 管理器组件 - 混合模式支持
        self.resource_manager = AsyncResourceManager()  # 使用异步资源管理器
        self.sync_manager = SynchronizationManager(self.sync_config)
        self.performance_monitor = AsyncPerformanceMonitor()  # 使用异步性能监控器
        self.thread_pool = DynamicThreadPool()  # 保持向后兼容
        self.communication_hub = CommunicationHub()

        # 异步组件
        self.error_handler = AsyncErrorHandler()
        self.stream_processor = AsyncStreamProcessor()

        # 异步执行状态
        self._async_mode = QTASYNCIO_AVAILABLE
        self._event_loop = None
        self._async_tasks: Dict[str, asyncio.Task] = {}
        self._cancellation_event = asyncio.Event()

        # 执行状态
        self.is_running = False
        self._orphaned_threads = []    # 线程无法停止时保留引用，避免闪退
        self._orphaned_executors = []  # 同上，避免QObject在线程运行中被销毁

        # 工具 多窗口完成策略配置
        self.auto_stop_on_first_completion = False  # 默认：等待所有窗口完成
        self._stop_requested = False
        self._execution_futures = []
        self._main_lock = threading.RLock()
        self._runtime_bound_windows: List[Dict[str, Any]] = []

        # 注册消息处理器
        self._setup_message_handlers()

        logger.info(f"统一多窗口执行器初始化完成 (异步模式: {'启用' if self._async_mode else '禁用'})")

    def _prune_orphaned_references(self) -> None:
        """仅保留仍在运行中的孤儿线程/执行器引用，避免列表长期累积。"""
        alive_threads = []
        for thread in self._orphaned_threads:
            if thread is None:
                continue
            try:
                if thread.isRunning():
                    alive_threads.append(thread)
            except RuntimeError:
                continue
        self._orphaned_threads = alive_threads

        alive_executors = []
        for executor in self._orphaned_executors:
            if executor is None:
                continue
            try:
                exec_thread = executor.thread() if hasattr(executor, "thread") else None
            except RuntimeError:
                continue
            try:
                if exec_thread is not None and exec_thread.isRunning():
                    alive_executors.append(executor)
            except RuntimeError:
                continue
        self._orphaned_executors = alive_executors

    def set_async_mode(self, enabled: bool = True):
        """设置异步模式"""
        if enabled and not QTASYNCIO_AVAILABLE:
            logger.warning("PySide6.QtAsyncio 不可用，无法启用异步模式")
            return False

        self._async_mode = enabled
        logger.info(f"异步模式已{'启用' if enabled else '禁用'}")
        return True

    def set_completion_strategy(self, auto_stop_on_first: bool = False):
        """
        设置多窗口完成策略

        Args:
            auto_stop_on_first: True=一个窗口完成就停止所有, False=等待所有窗口完成(默认)
        """
        self.auto_stop_on_first_completion = auto_stop_on_first
        strategy_name = "一个完成就停止所有" if auto_stop_on_first else "等待所有窗口完成"
        logger.info(f"多窗口完成策略已设置为: {strategy_name}")

    def _setup_message_handlers(self):
        """设置消息处理器"""
        self.communication_hub.register_handler("window_progress", self._handle_window_progress)
        self.communication_hub.register_handler("window_error", self._handle_window_error)
        self.communication_hub.register_handler("card_status", self._handle_card_status)

    def _handle_window_progress(self, data: Dict[str, Any]):
        """处理窗口进度消息"""
        window_title = data.get("window_title", "")
        progress = data.get("progress", 0.0)
        self.execution_progress.emit(window_title, progress)

    def _handle_window_error(self, data: Dict[str, Any]):
        """处理窗口错误消息"""
        window_title = data.get("window_title", "")
        window_hwnd = data.get("window_hwnd", 0)
        card_id = data.get("card_id", 0)
        error_msg = data.get("error", "")
        try:
            window_hwnd = int(window_hwnd)
        except (TypeError, ValueError):
            window_hwnd = 0
        try:
            card_id = int(card_id)
        except (TypeError, ValueError):
            card_id = 0

        window_key = f"{window_title}_{window_hwnd}"
        window_state = self.windows.get(window_key)
        if window_state is not None:
            window_state.error_count += 1
            window_state.last_error_message = str(error_msg or "").strip()
            window_state.last_failed_card_id = card_id if card_id > 0 else None

        self.error_occurred.emit(window_title, window_hwnd, card_id, error_msg)

    def _handle_card_status(self, data: Dict[str, Any]):
        """处理卡片状态消息"""
        window_title = data.get("window_title", "")
        card_id = data.get("card_id", "")
        status = data.get("status", "")
        success = data.get("success", True)
        try:
            card_id = int(card_id)
        except (TypeError, ValueError):
            pass

        # 工具 修复：发射正确格式的信号
        if status == "executing":
            self.card_executing.emit(card_id)  # 只发射卡片ID
        elif status == "finished":
            self.card_finished.emit(card_id, success)  # 发射卡片ID和成功状态

    def add_window(self, title: str, hwnd: int, enabled: bool = True) -> bool:
        """添加窗口到执行器"""
        try:
            with self._main_lock:
                # 工具 关键修复：使用HWND作为唯一键，避免同名窗口冲突
                window_key = f"{title}_{hwnd}"

                if window_key in self.windows:
                    logger.warning(f"窗口 '{window_key}' 已存在，更新状态")
                    self.windows[window_key].hwnd = hwnd
                    self.windows[window_key].enabled = enabled
                else:
                    self.windows[window_key] = WindowExecutionState(
                        title=title,  # 保持原始标题
                        hwnd=hwnd,
                        enabled=enabled
                    )
                    logger.info(f"添加窗口: '{title}' (HWND: {hwnd}, 启用: {enabled}, 键: {window_key})")

                return True
        except Exception as e:
            logger.error(f"添加窗口失败: {e}")
            return False

    def remove_window(self, title: str) -> bool:
        """移除窗口"""
        try:
            with self._main_lock:
                if title in self.windows:
                    window_state = self.windows[title]
                    if window_state.thread and window_state.thread.isRunning():
                        logger.warning(f"窗口 '{title}' 正在执行，无法移除")
                        return False

                    del self.windows[title]
                    logger.info(f"移除窗口: '{title}'")
                    return True
                else:
                    logger.warning(f"窗口 '{title}' 不存在")
                    return False
        except Exception as e:
            logger.error(f"移除窗口失败: {e}")
            return False

    def update_window_enabled_state(self, title: str, hwnd: int, enabled: bool):
        """更新窗口启用状态"""
        try:
            with self._main_lock:
                # 工具 修复：使用HWND作为唯一键
                window_key = f"{title}_{hwnd}"
                if window_key in self.windows:
                    self.windows[window_key].enabled = enabled
                    self.windows[window_key].hwnd = hwnd
                    logger.debug(f"更新窗口状态: '{window_key}' -> 启用: {enabled}")
                else:
                    # 如果窗口不存在，自动添加
                    self.add_window(title, hwnd, enabled)
        except Exception as e:
            logger.error(f"更新窗口状态失败: {e}")

    def get_enabled_windows(self) -> List[WindowExecutionState]:
        """获取启用的窗口列表"""
        with self._main_lock:
            return [window for window in self.windows.values() if window.enabled]

    @staticmethod
    def _window_thread_running(window: Optional[WindowExecutionState]) -> bool:
        if window is None:
            return False
        try:
            return bool(window.thread and window.thread.isRunning())
        except Exception:
            return False

    @staticmethod
    def _window_executor_running(window: Optional[WindowExecutionState]) -> bool:
        if window is None:
            return False
        executor = getattr(window, "executor", None)
        if executor is None or not hasattr(executor, "is_running"):
            return False
        try:
            return bool(executor.is_running())
        except Exception:
            return False

    @classmethod
    def _window_has_active_runtime(cls, window: Optional[WindowExecutionState]) -> bool:
        return cls._window_thread_running(window) or cls._window_executor_running(window)

    def get_pause_state(self) -> str:
        with self._main_lock:
            active_count = 0
            running_count = 0
            paused_count = 0

            for window in self.windows.values():
                if not self._window_has_active_runtime(window):
                    continue

                active_count += 1
                executor = getattr(window, "executor", None)
                if bool(getattr(executor, "_paused", False)):
                    paused_count += 1
                else:
                    running_count += 1

        if running_count > 0:
            return "running"
        if paused_count > 0:
            return "paused"
        if self.is_running and active_count == 0:
            return "running"
        return "idle"

    def pause_all(self):
        attempted_count = 0
        paused_count = 0

        with self._main_lock:
            windows = list(self.windows.values())

        for window in windows:
            if not self._window_has_active_runtime(window):
                continue

            executor = getattr(window, "executor", None)
            if executor is None or not hasattr(executor, "pause"):
                continue

            if bool(getattr(executor, "_paused", False)):
                continue

            attempted_count += 1
            try:
                result = executor.pause()
                if result is False:
                    continue
                paused_count += 1
            except Exception as exc:
                logger.warning("暂停多窗口执行器失败: window=%s, error=%s", getattr(window, "title", None), exc)

        logger.info("多窗口执行器已暂停 %s/%s 个活动窗口", paused_count, attempted_count)
        return attempted_count > 0 and paused_count == attempted_count

    def resume_all(self):
        attempted_count = 0
        resumed_count = 0

        with self._main_lock:
            windows = list(self.windows.values())

        for window in windows:
            if not self._window_has_active_runtime(window):
                continue

            executor = getattr(window, "executor", None)
            if executor is None or not hasattr(executor, "resume"):
                continue

            if not bool(getattr(executor, "_paused", False)):
                continue

            attempted_count += 1
            try:
                result = executor.resume()
                if result is False:
                    continue
                resumed_count += 1
            except Exception as exc:
                logger.warning("恢复多窗口执行器失败: window=%s, error=%s", getattr(window, "title", None), exc)

        logger.info("多窗口执行器已恢复 %s/%s 个活动窗口", resumed_count, attempted_count)
        return attempted_count > 0 and resumed_count == attempted_count

    def _select_optimal_strategy(self, mode: ExecutionMode, window_count: int) -> str:
        """智能选择执行策略"""
        # 工具 关键修复：检查总窗口数而不是启用窗口数
        total_windows = len(self.windows)

        logger.info(f"策略选择: 总窗口数={total_windows}, 启用窗口数={window_count}, 模式={mode.value}")

        # 如果有多个绑定窗口，强制使用并行模式
        if total_windows > 1:
            logger.info(f"检测到{total_windows}个绑定窗口，强制使用并行模式")
            return "simple_parallel"
        elif window_count <= 1:
            return "single_window"
        elif window_count <= 3:
            return "simple_parallel" if mode == ExecutionMode.PARALLEL else "sequential_safe"
        elif window_count > 10:
            return "batch_processing"
        elif mode == ExecutionMode.SEQUENTIAL:
            return "sequential_safe"
        elif mode == ExecutionMode.BATCH:
            return "batch_processing"
        elif mode == ExecutionMode.SYNCHRONIZED:
            return "synchronized_execution"
        else:
            return "simple_parallel"

    @staticmethod
    def _parse_sync_execution_mode(execution_mode: Any) -> Optional[ExecutionMode]:
        """解析多窗口调度模式（parallel/sequential/...）。"""
        if isinstance(execution_mode, ExecutionMode):
            return execution_mode

        mode_text = str(execution_mode or "").strip().lower()
        if not mode_text:
            return None

        mode_map = {
            "parallel": ExecutionMode.PARALLEL,
            "sequential": ExecutionMode.SEQUENTIAL,
            "batch": ExecutionMode.BATCH,
            "synchronized": ExecutionMode.SYNCHRONIZED,
            "streaming": ExecutionMode.STREAMING,
            "adaptive": ExecutionMode.ADAPTIVE,
        }
        return mode_map.get(mode_text)

    def _ensure_runtime_execution_mode(
        self,
        workflow_data: dict,
        execution_mode: Any,
        *,
        async_mode: bool,
    ) -> Optional[str]:
        """
        保证 workflow_data 内存在窗口执行模式（foreground/background）。
        不把并发调度模式写入 execution_mode，避免覆盖窗口执行模式。
        """
        if not isinstance(workflow_data, dict):
            return None

        runtime_mode = str(workflow_data.get("execution_mode") or "").strip()
        if runtime_mode:
            logger.info(
                "多窗口中控（%s）：沿用 workflow_data.execution_mode=%s",
                "异步" if async_mode else "同步",
                runtime_mode,
            )
            return runtime_mode

        if isinstance(execution_mode, str):
            raw_mode = str(execution_mode or "").strip()
            if raw_mode and self._parse_sync_execution_mode(raw_mode) is None:
                workflow_data["execution_mode"] = raw_mode
                logger.info(
                    "多窗口中控（%s）：补全窗口执行模式 execution_mode=%s",
                    "异步" if async_mode else "同步",
                    raw_mode,
                )
                return raw_mode

        return None

    async def start_execution_async(self, workflow_data: dict, delay_ms: int = 0,
                                   execution_mode: ExecutionMode = None, bound_windows: list = None) -> bool:
        """异步执行入口 - 现代异步模式"""
        if not self._async_mode:
            logger.warning("异步模式未启用，回退到同步执行")
            return self.start_execution(workflow_data, delay_ms, execution_mode, bound_windows)

        try:
            async with self.resource_manager._main_lock:
                if self.is_running:
                    logger.warning("多窗口执行器已在运行中")
                    return False

                sync_execution_mode = self._parse_sync_execution_mode(execution_mode)
                runtime_execution_mode = self._ensure_runtime_execution_mode(
                    workflow_data,
                    execution_mode,
                    async_mode=True,
                )

                if sync_execution_mode:
                    self.sync_config.mode = sync_execution_mode
                    logger.info(f"多窗口中控（异步）：同步调度模式={self.sync_config.mode.value}")
                elif execution_mode is not None and not runtime_execution_mode:
                    logger.warning(
                        "多窗口中控（异步）：无法识别 execution_mode=%s，沿用默认同步模式=%s",
                        execution_mode,
                        self.sync_config.mode.value,
                    )

                # 获取启用的窗口
                self._runtime_bound_windows = list(bound_windows or [])
                enabled_windows = self.get_enabled_windows()
                if not enabled_windows:
                    logger.error("没有启用的窗口可执行")
                    return False

                # 重置窗口状态
                for window in enabled_windows:
                    window.reset()

                # 选择最佳执行策略
                strategy = self._select_optimal_strategy(self.sync_config.mode, len(enabled_windows))
                logger.info(f"异步执行策略: {strategy}, 窗口数: {len(enabled_windows)}, 模式: {self.sync_config.mode.value}")

                # 标记开始执行
                self.is_running = True
                self._stop_requested = False
                self._execution_futures.clear()
                self._prune_orphaned_references()
                self._cancellation_event.clear()

                # 开始性能监控
                await self.performance_monitor.start_timing("total_execution")

                # 根据策略执行异步任务
                if strategy == "single_window":
                    success = await self._execute_single_window_async(enabled_windows[0], workflow_data, delay_ms)
                elif strategy == "simple_parallel":
                    success = await self._execute_parallel_async(enabled_windows, workflow_data, delay_ms)
                elif strategy == "sequential_safe":
                    success = await self._execute_sequential_async(enabled_windows, workflow_data, delay_ms)
                elif strategy == "batch_processing":
                    success = await self._execute_batch_async(enabled_windows, workflow_data, delay_ms)
                elif self.sync_config.mode == ExecutionMode.STREAMING:
                    success = await self._execute_streaming_async(enabled_windows, workflow_data, delay_ms)
                else:
                    # 回退到同步模式
                    success = self.start_execution(workflow_data, delay_ms, execution_mode, bound_windows)

                # 结束性能监控
                total_time = await self.performance_monitor.end_timing("total_execution")
                logger.info(f"多窗口执行完成，总耗时: {total_time:.2f}秒")

                final_success, final_message = self._build_execution_completed_payload(
                    default_success=success,
                    default_message="多窗口执行完成" if success else "多窗口执行失败",
                )
                self.execution_completed.emit(final_success, final_message)

                return success

        except Exception as e:
            logger.error(f"异步执行失败: {e}", exc_info=True)
            return False
        finally:
            self.is_running = False

    def start_execution(self, workflow_data: dict, delay_ms: int = 0,
                       execution_mode: ExecutionMode = None, bound_windows: list = None) -> bool:
        """统一的执行入口"""
        try:
            with self._main_lock:
                if self.is_running:
                    logger.warning("多窗口执行器已在运行中")
                    return False

                sync_execution_mode = self._parse_sync_execution_mode(execution_mode)
                runtime_execution_mode = self._ensure_runtime_execution_mode(
                    workflow_data,
                    execution_mode,
                    async_mode=False,
                )

                if sync_execution_mode:
                    self.sync_config.mode = sync_execution_mode
                    logger.info(f"多窗口中控：同步调度模式={self.sync_config.mode.value}")
                elif execution_mode is not None and not runtime_execution_mode:
                    logger.warning(
                        "多窗口中控：无法识别 execution_mode=%s，沿用默认同步模式=%s",
                        execution_mode,
                        self.sync_config.mode.value,
                    )

                # 获取启用的窗口
                self._runtime_bound_windows = list(bound_windows or [])
                enabled_windows = self.get_enabled_windows()
                if not enabled_windows:
                    logger.error("没有启用的窗口可执行")
                    return False

                # 重置窗口状态
                for window in enabled_windows:
                    window.reset()

                # 选择最佳执行策略
                strategy = self._select_optimal_strategy(self.sync_config.mode, len(enabled_windows))
                logger.info(f"选择执行策略: {strategy}, 窗口数: {len(enabled_windows)}, 模式: {self.sync_config.mode.value}")

                # 设置同步机制
                if strategy in ["synchronized_execution", "sequential_safe"]:
                    self.sync_manager.setup_synchronization(len(enabled_windows))

                # 标记开始执行
                self.is_running = True
                self._stop_requested = False
                self._execution_futures.clear()
                self._prune_orphaned_references()

                # 开始性能监控
                self.performance_monitor.start_timing("total_execution")

                # 工具 关键修复：根据策略选择窗口列表
                if strategy == "single_window":
                    success = self._execute_single_window(enabled_windows[0], workflow_data, delay_ms)
                elif strategy == "simple_parallel":
                    # 修复：只使用启用的窗口进行并行执行
                    logger.info(f"并行执行: 使用{len(enabled_windows)}个启用窗口")
                    success = self._execute_simple_parallel(enabled_windows, workflow_data, delay_ms)
                elif strategy == "sequential_safe":
                    success = self._execute_sequential_safe(enabled_windows, workflow_data, delay_ms)
                elif strategy == "batch_processing":
                    success = self._execute_batch_processing(enabled_windows, workflow_data, delay_ms)
                elif strategy == "synchronized_execution":
                    success = self._execute_synchronized(enabled_windows, workflow_data, delay_ms)
                else:
                    logger.error(f"未知的执行策略: {strategy}")
                    success = False

                if success:
                    logger.info(f"多窗口执行启动成功，策略: {strategy}")
                else:
                    self.is_running = False
                    logger.error(f"多窗口执行启动失败，策略: {strategy}")

                return success

        except Exception as e:
            logger.error(f"启动多窗口执行失败: {e}", exc_info=True)
            self.is_running = False
            return False

    def _execute_single_window(self, window: WindowExecutionState, workflow_data: dict, delay_ms: int) -> bool:
        """单窗口执行"""
        try:
            logger.info(f"开始单窗口执行: {window.title}")

            # 创建执行器
            executor = self._create_window_executor(window, workflow_data)
            if not executor:
                return False

            # 延迟启动
            if delay_ms > 0:
                time.sleep(delay_ms / 1000.0)

            # 工具 修复：正确的线程执行方式
            window.executor = executor

            # 生成窗口键值
            window_key = f"{window.title}_{window.hwnd}"

            # 获取线程句柄
            from PySide6.QtCore import QThread
            thread = getattr(executor, "_process_thread_handle", None)
            if thread is None:
                thread = QThread()
            window.thread = thread

            # 将执行器移动到线程中
            executor.moveToThread(thread)

            # 连接线程信号
            thread.started.connect(executor.run)
            thread.finished.connect(thread.deleteLater)

            # 连接执行器信号
            if hasattr(executor, 'execution_finished'):
                # 工具 修复闭包问题：使用默认参数捕获当前窗口信息
                def create_finished_handler(window_key, window_title, window_hwnd):
                    def handler(success, msg):
                        self._on_window_execution_finished_with_key(window_key, window_title, window_hwnd, success, msg)
                    return handler

                executor.execution_finished.connect(create_finished_handler(window_key, window.title, window.hwnd))

            # 启动线程
            thread.start()

            logger.info(f"单窗口执行启动成功: {window.title} (线程ID: {thread})")
            return True

        except Exception as e:
            logger.error(f"单窗口执行失败: {e}", exc_info=True)
            return False

    def _on_window_execution_finished(self, window_title: str, message: str):
        """处理窗口执行完成"""
        try:
            logger.info(f"窗口执行完成: {window_title} - {message}")

            # 工具 改进：通过线程对象精确识别窗口，而不是仅通过标题
            current_thread = self.sender()  # 获取发送信号的线程
            window_key = None
            matched_window = None

            # 方法1：通过线程对象匹配
            if current_thread:
                for key, window in self.windows.items():
                    if window.thread == current_thread:
                        window_key = key
                        matched_window = window
                        logger.info(f"通过线程对象匹配到窗口: {window_title} (Key: {key}, HWND: {window.hwnd})")
                        break

            # 方法2：如果线程匹配失败，尝试通过执行器对象匹配
            if not window_key and current_thread:
                executor_obj = getattr(current_thread, 'executor', None) if hasattr(current_thread, 'executor') else None
                if executor_obj:
                    for key, window in self.windows.items():
                        if window.executor == executor_obj:
                            window_key = key
                            matched_window = window
                            logger.info(f"通过执行器对象匹配到窗口: {window_title} (Key: {key}, HWND: {window.hwnd})")
                            break

            # 方法3：回退到标题匹配（但优先选择未完成的窗口）
            if not window_key:
                for key, window in self.windows.items():
                    if (window.title == window_title and
                        not (hasattr(window, 'execution_completed') and window.execution_completed)):
                        window_key = key
                        matched_window = window
                        logger.info(f"通过标题匹配到未完成窗口: {window_title} (Key: {key}, HWND: {window.hwnd})")
                        break

            # 标记窗口为已完成
            if matched_window:
                matched_window.execution_completed = True
                logger.info(f"成功 标记窗口已完成: {window_title} (Key: {window_key}, HWND: {matched_window.hwnd})")
            else:
                logger.warning(f"警告 无法找到对应的窗口来标记完成状态: {window_title}")

            # 清理窗口状态
            if window_key and window_key in self.windows:
                window = self.windows[window_key]
                if window.thread and window.thread.isRunning():
                    window.thread.quit()
                    window.thread.wait(3000)  # 等待3秒
                # 注意：不调用reset()，保持完成标记

            # 检查是否所有窗口都完成了
            self._check_all_windows_finished()

        except Exception as e:
            logger.error(f"处理窗口执行完成时出错: {e}")

    def _on_window_execution_finished_with_key(self, window_key: str, window_title: str, window_hwnd: int, success: bool, message: str):
        """处理窗口执行完成 - 使用精确的窗口键值"""
        try:
            logger.info(f"窗口执行完成: {window_title} (Key: {window_key}, HWND: {window_hwnd}) - success={success}, {message}")

            # 工具 直接使用窗口键值，避免匹配问题
            if window_key in self.windows:
                window = self.windows[window_key]
                window.execution_completed = True
                window.last_message = str(message or "").strip()
                window.last_result_success = bool(success)
                if not success:
                    window.last_error_message = window.last_message or window.last_error_message
                logger.info(f"成功 精确标记窗口已完成: {window_title} (Key: {window_key}, HWND: {window_hwnd})")

                # 【内存泄漏修复】立即断开executor的信号连接，防止内存泄漏
                if window.executor is not None:
                    try:
                        # 断开execution_finished信号（这是主要的泄漏源）
                        if hasattr(window.executor, 'execution_finished'):
                            try:
                                window.executor.execution_finished.disconnect()
                            except (RuntimeError, TypeError):
                                pass
                        # 断开其他信号
                        for signal_name in ['execution_started', 'card_executing', 'card_finished', 'step_details', 'error_occurred']:
                            if hasattr(window.executor, signal_name):
                                try:
                                    getattr(window.executor, signal_name).disconnect()
                                except (RuntimeError, TypeError):
                                    pass
                        logger.debug(f"已断开窗口 {window_key} 的executor信号连接")
                    except Exception as e:
                        logger.debug(f"断开executor信号时异常（可忽略）: {e}")

                # 工具 关键修复：优雅清理线程，避免死锁和闪退
                if window.thread and window.thread.isRunning():
                    logger.debug(f"请求停止窗口线程: {window_key}")

                    # 首先请求执行器停止
                    if window.executor and hasattr(window.executor, 'request_stop'):
                        window.executor.request_stop()

                    # 然后请求线程退出
                    window.thread.quit()

                    # 工具 闪退修复：使用弱引用和定时器，避免在线程槽函数中等待线程
                    from PySide6.QtCore import QTimer
                    import weakref

                    # 使用弱引用避免循环引用和内存泄漏
                    thread_ref = weakref.ref(window.thread) if window.thread else None
                    executor_ref = weakref.ref(window.executor) if window.executor else None
                    key_copy = str(window_key)  # 复制字符串避免闭包引用问题

                    def check_thread_later():
                        """延迟检查线程状态，避免死锁"""
                        thread = thread_ref() if thread_ref else None
                        if thread and thread.isRunning():
                            logger.error(f"线程未能正常退出（放弃terminate以避免闪退）: {key_copy}")
                            try:
                                if hasattr(thread, "requestInterruption"):
                                    thread.requestInterruption()
                                thread.quit()
                                thread.wait(1000)
                            except Exception as e:
                                logger.error(f"停止线程失败 {key_copy}: {e}")
                            self._orphaned_threads.append(thread)

                        # 【内存泄漏修复】线程退出后，调用executor的deleteLater
                        executor = executor_ref() if executor_ref else None
                        if executor and (thread is None or not thread.isRunning()) and hasattr(executor, 'deleteLater'):
                            try:
                                executor.deleteLater()
                                logger.debug(f"executor已标记为删除: {key_copy}")
                            except (RuntimeError, AttributeError):
                                pass
                        elif executor and thread and thread.isRunning():
                            self._orphaned_executors.append(executor)

                    QTimer.singleShot(2000, check_thread_later)  # 2秒后异步检查
                    logger.debug(f"窗口线程已请求退出（异步清理）: {window_key}")
                # 注意：不调用reset()，保持完成标记

            else:
                logger.warning(f"警告 窗口键值不存在: {window_key}")

            # 检查是否所有窗口都完成了
            self._check_all_windows_finished()

        except Exception as e:
            logger.error(f"处理窗口执行完成时出错 (精确方法): {e}")

    def _check_all_windows_finished(self):
        """检查是否所有窗口都完成了执行"""
        try:
            enabled_windows = self.get_enabled_windows()
            running_count = 0
            completed_count = 0

            # 工具 添加详细的窗口状态调试信息
            logger.debug(f"检查窗口状态，总共 {len(enabled_windows)} 个启用窗口")

            for window in enabled_windows:
                window_key = f"{window.title}_{window.hwnd}"
                is_thread_running = window.thread and window.thread.isRunning()
                is_completed = hasattr(window, 'execution_completed') and window.execution_completed

                logger.debug(f"窗口状态: {window_key} - 线程运行: {is_thread_running}, 已完成: {is_completed}")

                # 工具 修复：如果任务已完成，则不算作运行中，即使线程还在清理
                if is_thread_running and not is_completed:
                    running_count += 1
                if is_completed:
                    completed_count += 1

            if running_count == 0:
                final_success, final_message = self._build_execution_completed_payload(
                    default_success=True,
                    default_message=f"所有窗口执行完成（共 {len(enabled_windows)} 个）",
                )
                success_count = sum(1 for window in enabled_windows if window.last_result_success is True)
                failed_count = sum(1 for window in enabled_windows if window.last_result_success is False)
                logger.info(
                    "所有窗口执行完成 - 总计: %s, 成功: %s, 失败: %s, 已完成: %s",
                    len(enabled_windows),
                    success_count,
                    failed_count,
                    completed_count,
                )
                self.is_running = False

                self.execution_completed.emit(final_success, final_message)
            else:
                logger.debug(f"还有 {running_count} 个窗口在执行中")
                logger.info(f"当前状态: {completed_count} 个窗口已完成, {running_count} 个窗口仍在运行")

                # 只有在用户明确配置为"一个完成就停止"时才执行自动停止
                # 默认行为：让所有窗口都完成各自的任务
                auto_stop_on_first = getattr(self, 'auto_stop_on_first_completion', False)
                logger.debug(f" 多窗口完成策略检查: auto_stop_on_first={auto_stop_on_first}, completed_count={completed_count}, running_count={running_count}")

                if auto_stop_on_first and completed_count > 0:
                    logger.warning(f" 检测到一个完成就停止配置，自动停止所有窗口 (已完成:{completed_count}, 仍运行:{running_count})")
                    self.stop_all()
                    return
                else:
                    logger.info(f" 继续等待所有窗口完成 (已完成:{completed_count}, 仍运行:{running_count})")

        except Exception as e:
            logger.error(f"检查窗口完成状态时出错: {e}")

    def _build_execution_completed_payload(self, default_success: bool, default_message: str) -> tuple[bool, str]:
        enabled_windows = self.get_enabled_windows()
        success_count = 0
        failed_windows = []
        for window in enabled_windows:
            if window.last_result_success is True:
                success_count += 1
            elif window.last_result_success is False:
                failed_windows.append(window)

        if failed_windows:
            first_failed = failed_windows[0]
            failure_summary = f"多窗口执行失败: 成功 {success_count} 个, 失败 {len(failed_windows)} 个"
            if first_failed.title:
                failure_summary += f"\n失败窗口: {first_failed.title} (HWND: {first_failed.hwnd})"
            if first_failed.last_message:
                failure_summary += f"\n失败详情: {first_failed.last_message}"
            return False, failure_summary

        message = str(default_message or "").strip()
        if message:
            return bool(default_success), message
        if enabled_windows:
            return True, f"所有窗口执行完成（共 {len(enabled_windows)} 个）"
        return bool(default_success), ("多窗口执行完成" if default_success else "多窗口执行失败")

    def _finalize_execution(self):
        """完成执行时的清理工作"""
        try:
            logger.info("开始完成执行的清理工作")

            # 清理同步资源
            self.sync_manager.cleanup()

            # 清理执行futures
            with self._main_lock:
                self._execution_futures.clear()

            # 结束性能监控
            try:
                # 修复：检查是否为异步性能监控器
                if hasattr(self.performance_monitor, 'end_timing'):
                    if asyncio.iscoroutinefunction(self.performance_monitor.end_timing):
                        # 异步版本，但在同步上下文中，使用同步方法
                        if hasattr(self.performance_monitor, '_sync_end_timing'):
                            total_time = self.performance_monitor._sync_end_timing("total_execution")
                        else:
                            total_time = 0.0  # 回退值
                            logger.warning("异步性能监控器在同步上下文中，无法获取准确计时")
                    else:
                        # 同步版本
                        total_time = self.performance_monitor.end_timing("total_execution")
                    logger.info(f"多窗口执行完成，总耗时: {total_time:.2f}秒")
                else:
                    logger.info("多窗口执行完成")
            except Exception as e:
                logger.warning(f"结束性能监控时出错: {e}")
                logger.info("多窗口执行完成")

            logger.info("执行清理工作完成")

        except Exception as e:
            logger.error(f"完成执行清理工作失败: {e}")

    def _execute_simple_parallel(self, windows: List[WindowExecutionState], workflow_data: dict, delay_ms: int) -> bool:
        """简单并行执行"""
        try:
            logger.info(f"热门 开始简单并行执行，窗口数: {len(windows)}")

            # 详细记录每个窗口信息
            for i, window in enumerate(windows):
                logger.info(f"  窗口{i+1}: {window.title} (HWND: {window.hwnd}, enabled: {window.enabled})")

            # 获取线程池
            pool = self.thread_pool.get_pool(len(windows))
            logger.info(f"热门 获取线程池成功，池大小: {len(windows)}")

            # 提交所有窗口的执行任务
            futures = []
            for i, window in enumerate(windows):
                # 计算延迟
                window_delay = delay_ms + (i * 100)  # 每个窗口间隔100ms

                logger.info(f"热门 提交窗口{i+1}执行任务: {window.title}, 延迟: {window_delay}ms")
                future = pool.submit(self._execute_window_workflow, window, workflow_data, window_delay)
                futures.append((future, window))
                self._execution_futures.append(future)
                logger.info(f"热门 窗口{i+1}任务已提交: {window.title}")

            logger.info(f"热门 已提交 {len(futures)} 个并行执行任务")
            return True

        except Exception as e:
            logger.error(f"简单并行执行失败: {e}", exc_info=True)
            return False

    async def _execute_parallel_async(self, windows: List[WindowExecutionState], workflow_data: dict, delay_ms: int) -> bool:
        """异步并行执行"""
        try:
            logger.info(f"开始异步并行执行，窗口数: {len(windows)}")

            # 创建异步任务
            tasks = []
            logger.info(f"开始创建 {len(windows)} 个异步任务...")

            for i, window in enumerate(windows):
                window_delay = delay_ms + (i * 100)  # 错开启动时间
                logger.info(f"创建任务 {i+1}/{len(windows)}: {window.title} (HWND: {window.hwnd}, 延迟: {window_delay}ms)")

                task = asyncio.create_task(
                    self._execute_window_async(window, workflow_data, window_delay),
                    name=f"window_{window.title}_{window.hwnd}"
                )
                tasks.append(task)
                self._async_tasks[f"{window.title}_{window.hwnd}"] = task
                window.task = task

            logger.info(f"已创建 {len(tasks)} 个异步任务，开始并发执行...")

            # 并发执行所有任务
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 处理结果
            success_count = 0
            failed_count = 0
            exception_count = 0

            logger.info(f"开始处理 {len(results)} 个窗口执行结果...")

            for i, (window, result) in enumerate(zip(windows, results)):
                logger.info(f"处理窗口 {i+1}/{len(windows)}: {window.title} (HWND: {window.hwnd})")

                if isinstance(result, Exception):
                    exception_count += 1
                    logger.error(f"窗口 {window.title} 执行异常: {result}")
                    window.status = TaskStatus.FAILED
                    window.last_error = result
                elif isinstance(result, ExecutionResult):
                    logger.info(f"窗口 {window.title} 执行结果: success={result.success}, time={result.execution_time:.2f}s")
                    if result.success:
                        success_count += 1
                        window.status = TaskStatus.COMPLETED
                        logger.info(f"窗口 {window.title} 执行成功")
                    else:
                        failed_count += 1
                        window.status = TaskStatus.FAILED
                        window.last_error = result.error
                        logger.warning(f"窗口 {window.title} 执行失败: {result.error}")

                    # 记录性能数据
                    await self.performance_monitor.record_task_result(
                        f"window_{window.title}_{window.hwnd}", result
                    )
                else:
                    logger.error(f"❓ 窗口 {window.title} 返回未知结果类型: {type(result)}")

            logger.info(f"📈 异步并行执行统计: 成功={success_count}, 失败={failed_count}, 异常={exception_count}, 总计={len(windows)}")
            logger.info(f"异步并行执行完成: {success_count}/{len(windows)} 成功")
            return success_count > 0

        except Exception as e:
            logger.error(f"异步并行执行失败: {e}", exc_info=True)
            return False

    async def _execute_sequential_async(self, windows: List[WindowExecutionState], workflow_data: dict, delay_ms: int) -> bool:
        """异步顺序执行"""
        try:
            logger.info(f"开始异步顺序执行，窗口数: {len(windows)}")

            success_count = 0
            for i, window in enumerate(windows):
                if self._cancellation_event.is_set():
                    logger.info("收到取消信号，中断顺序执行")
                    break

                logger.info(f"顺序执行窗口 {i+1}/{len(windows)}: {window.title}")

                try:
                    result = await self._execute_window_async(window, workflow_data, delay_ms)

                    if isinstance(result, ExecutionResult) and result.success:
                        success_count += 1
                        window.status = TaskStatus.COMPLETED
                    else:
                        window.status = TaskStatus.FAILED
                        if isinstance(result, ExecutionResult):
                            window.last_error = result.error

                    # 记录性能数据
                    if isinstance(result, ExecutionResult):
                        await self.performance_monitor.record_task_result(
                            f"window_{window.title}_{window.hwnd}", result
                        )

                except Exception as e:
                    logger.error(f"窗口 {window.title} 执行失败: {e}")
                    window.status = TaskStatus.FAILED
                    window.last_error = e

            logger.info(f"异步顺序执行完成: {success_count}/{len(windows)} 成功")
            return success_count > 0

        except Exception as e:
            logger.error(f"异步顺序执行失败: {e}", exc_info=True)
            return False

    async def _execute_batch_async(self, windows: List[WindowExecutionState], workflow_data: dict, delay_ms: int) -> bool:
        """异步批处理执行"""
        try:
            batch_size = self.sync_config.batch_size
            logger.info(f"开始异步批处理执行，窗口数: {len(windows)}, 批大小: {batch_size}")

            total_success = 0
            for i in range(0, len(windows), batch_size):
                if self._cancellation_event.is_set():
                    logger.info("收到取消信号，中断批处理执行")
                    break

                batch = windows[i:i + batch_size]
                logger.info(f"执行批次 {i//batch_size + 1}, 窗口数: {len(batch)}")

                # 并行执行当前批次
                batch_tasks = [
                    asyncio.create_task(
                        self._execute_window_async(window, workflow_data, delay_ms + (j * 50))
                    )
                    for j, window in enumerate(batch)
                ]

                # 等待批次完成
                batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)

                # 处理批次结果
                batch_success = 0
                for window, result in zip(batch, batch_results):
                    if isinstance(result, ExecutionResult) and result.success:
                        batch_success += 1
                        window.status = TaskStatus.COMPLETED
                    else:
                        window.status = TaskStatus.FAILED
                        if isinstance(result, ExecutionResult):
                            window.last_error = result.error
                        elif isinstance(result, Exception):
                            window.last_error = result

                total_success += batch_success
                logger.info(f"批次 {i//batch_size + 1} 完成: {batch_success}/{len(batch)} 成功")

            logger.info(f"异步批处理执行完成: {total_success}/{len(windows)} 成功")
            return total_success > 0

        except Exception as e:
            logger.error(f"异步批处理执行失败: {e}", exc_info=True)
            return False

    def _execute_sequential_safe(self, windows: List[WindowExecutionState], workflow_data: dict, delay_ms: int) -> bool:
        """安全顺序执行"""
        try:
            logger.info(f"开始安全顺序执行，窗口数: {len(windows)}")

            # 顺序执行每个窗口
            for i, window in enumerate(windows):
                if self._stop_requested:
                    logger.info("收到停止请求，中断顺序执行")
                    break

                logger.info(f"顺序执行窗口 {i+1}/{len(windows)}: {window.title}")

                # 等待同步点
                if not self.sync_manager.wait_at_sync_point(SyncPoint.START, window.title):
                    logger.error(f"窗口 {window.title} 同步失败")
                    continue

                # 执行窗口工作流
                success = self._execute_window_workflow(window, workflow_data, delay_ms)
                if not success:
                    logger.error(f"窗口 {window.title} 执行失败")
                    window.error_count += 1

                # 等待完成同步点
                self.sync_manager.wait_at_sync_point(SyncPoint.FINISH, window.title)

            logger.info("安全顺序执行完成")
            return True

        except Exception as e:
            logger.error(f"安全顺序执行失败: {e}", exc_info=True)
            return False

    def _execute_batch_processing(self, windows: List[WindowExecutionState], workflow_data: dict, delay_ms: int) -> bool:
        """批处理执行"""
        try:
            batch_size = self.sync_config.batch_size
            logger.info(f"开始批处理执行，窗口数: {len(windows)}, 批大小: {batch_size}")

            # 分批执行
            for i in range(0, len(windows), batch_size):
                if self._stop_requested:
                    logger.info("收到停止请求，中断批处理执行")
                    break

                batch = windows[i:i + batch_size]
                logger.info(f"执行批次 {i//batch_size + 1}, 窗口数: {len(batch)}")

                # 并行执行当前批次
                pool = self.thread_pool.get_pool(len(batch))
                futures = []

                for j, window in enumerate(batch):
                    window_delay = delay_ms + (j * 50)  # 批内延迟较小
                    future = pool.submit(self._execute_window_workflow, window, workflow_data, window_delay)
                    futures.append((future, window))

                # 等待当前批次完成
                for future, window in futures:
                    try:
                        future.result(timeout=300)  # 5分钟超时
                    except Exception as e:
                        logger.error(f"批处理窗口 {window.title} 执行失败: {e}")
                        window.error_count += 1

                logger.info(f"批次 {i//batch_size + 1} 执行完成")

            logger.info("批处理执行完成")
            return True

        except Exception as e:
            logger.error(f"批处理执行失败: {e}", exc_info=True)
            return False

    def _execute_synchronized(self, windows: List[WindowExecutionState], workflow_data: dict, delay_ms: int) -> bool:
        """同步执行"""
        try:
            logger.info(f"开始同步执行，窗口数: {len(windows)}")

            # 获取线程池
            pool = self.thread_pool.get_pool(len(windows))

            # 提交同步执行任务
            futures = []
            for window in enumerate(windows):
                future = pool.submit(self._execute_window_workflow_synchronized, window, workflow_data, delay_ms)
                futures.append((future, window))
                self._execution_futures.append(future)

            logger.info(f"已提交 {len(futures)} 个同步执行任务")
            return True

        except Exception as e:
            logger.error(f"同步执行失败: {e}", exc_info=True)
            return False

    def _execute_window_workflow(self, window: WindowExecutionState, workflow_data: dict, delay_ms: int) -> bool:
        """执行单个窗口的工作流"""
        try:
            # 检查窗口是否启用
            if not window.enabled:
                logger.info(f"跳过禁用的窗口: {window.title}")
                return True  # 返回True表示"成功跳过"，不是执行失败

            # 工具 生成窗口键值
            window_key = f"{window.title}_{window.hwnd}"
            logger.info(f"启动 开始执行窗口工作流: {window.title} (Key: {window_key}, HWND: {window.hwnd})")

            # 延迟启动 - 在创建执行器之前执行，错开各窗口启动时间避免资源竞争
            if delay_ms > 0:
                logger.info(f"启动 窗口 {window.title} 延迟启动: {delay_ms}ms (线程内等待，不阻塞其他窗口)")
                time.sleep(delay_ms / 1000.0)

            # 创建执行器
            logger.info(f"启动 为窗口 {window.title} 创建执行器")
            executor = self._create_window_executor(window, workflow_data)
            if not executor:
                logger.error(f"错误 窗口 {window.title} 执行器创建失败")
                return False
            logger.info(f"启动 窗口 {window.title} 执行器创建成功")

            # 设置窗口执行器
            window.executor = executor
            window.current_step = "executing"
            logger.info(f"启动 窗口 {window.title} 状态设置为executing")

            # 工具 关键修复：使用正确的线程执行方式
            logger.info(f"启动 为窗口 {window.title} 创建执行线程")

            # 创建线程
            from PySide6.QtCore import QThread
            thread = QThread()
            window.thread = thread
            logger.info(f"启动 窗口 {window.title} 线程创建成功: {thread}")

            # 将执行器移动到线程中
            logger.info(f"启动 将窗口 {window.title} 的执行器移动到线程中")
            executor.moveToThread(thread)

            # 连接信号
            logger.info(f"启动 连接窗口 {window.title} 的线程信号")
            thread.started.connect(executor.run)
            thread.finished.connect(thread.deleteLater)

            # 工具 修复：确保执行器能够访问线程对象
            executor.thread = lambda: thread

            # 连接执行器信号
            if hasattr(executor, 'execution_finished'):
                # 工具 修复闭包问题：使用默认参数捕获当前窗口信息
                def create_finished_handler(window_key, window_title, window_hwnd):
                    def handler(success, msg):
                        self._on_window_execution_finished_with_key(window_key, window_title, window_hwnd, success, msg)
                    return handler

                executor.execution_finished.connect(create_finished_handler(window_key, window.title, window.hwnd))
                logger.info(f"启动 窗口 {window.title} (Key: {window_key}, HWND: {window.hwnd}) 执行器信号连接成功")

            # 启动线程
            logger.info(f"启动 启动窗口 {window.title} 的执行线程")
            thread.start()
            logger.info(f"启动 窗口 {window.title} 线程启动成功")

            logger.info(f"成功 窗口工作流启动成功: {window.title} (线程ID: {thread})")
            window.current_step = "running"
            return True

        except Exception as e:
            logger.error(f"执行窗口工作流失败 {window.title}: {e}", exc_info=True)
            window.current_step = "error"
            window.error_count += 1
            return False

    async def _execute_window_async(self, window: WindowExecutionState, workflow_data: dict, delay_ms: int) -> ExecutionResult:
        """异步执行单个窗口的工作流"""
        start_time = time.time()
        window.start_time = start_time
        window.status = TaskStatus.RUNNING

        try:
            # 检查窗口是否启用
            if not window.enabled:
                logger.warning(f"窗口 {window.title} (HWND: {window.hwnd}) 被禁用，跳过执行")
                result = ExecutionResult(
                    success=True,
                    window_title=window.title,
                    window_hwnd=window.hwnd,
                    execution_time=0.0,
                    status=TaskStatus.COMPLETED
                )
                window.end_time = time.time()
                return result

            window_key = f"{window.title}_{window.hwnd}"
            logger.warning(f"开始异步执行窗口: {window.title} (Key: {window_key}, HWND: {window.hwnd}, 启用状态: {window.enabled})")

            # 延迟启动 - 在获取资源之前执行，避免占用资源时阻塞其他窗口
            if delay_ms > 0:
                logger.info(f"窗口 {window.title} 延迟启动: {delay_ms}ms")
                await asyncio.sleep(delay_ms / 1000.0)

            # 获取窗口资源
            async with self.resource_manager.acquire_window_resource(window.title):
                # 使用错误处理器执行任务
                result = await self.error_handler.execute_with_retry(
                    self._execute_window_workflow_core,
                    f"window_{window.title}",
                    window, workflow_data
                )

                window.end_time = time.time()
                execution_time = window.end_time - window.start_time

                if result:
                    success, action, next_card_id = result
                    execution_result = ExecutionResult(
                        success=success,
                        window_title=window.title,
                        window_hwnd=window.hwnd,
                        execution_time=execution_time,
                        data={'action': action, 'next_card_id': next_card_id},
                        status=TaskStatus.COMPLETED if success else TaskStatus.FAILED
                    )
                else:
                    execution_result = ExecutionResult(
                        success=False,
                        window_title=window.title,
                        window_hwnd=window.hwnd,
                        execution_time=execution_time,
                        error=Exception("任务执行返回空结果"),
                        status=TaskStatus.FAILED
                    )

                window.status = execution_result.status
                logger.info(f"窗口 {window.title} 异步执行完成: {execution_result.success}")
                return execution_result

        except asyncio.CancelledError:
            logger.info(f"窗口 {window.title} 执行被取消")
            window.status = TaskStatus.CANCELLED
            window.end_time = time.time()
            return ExecutionResult(
                success=False,
                window_title=window.title,
                window_hwnd=window.hwnd,
                execution_time=time.time() - start_time,
                status=TaskStatus.CANCELLED
            )
        except Exception as e:
            logger.error(f"窗口 {window.title} 异步执行失败: {e}", exc_info=True)
            window.status = TaskStatus.FAILED
            window.last_error = e
            window.end_time = time.time()
            return ExecutionResult(
                success=False,
                window_title=window.title,
                window_hwnd=window.hwnd,
                execution_time=time.time() - start_time,
                error=e,
                status=TaskStatus.FAILED
            )

    async def _execute_window_workflow_core(self, window: WindowExecutionState, workflow_data: dict):
        """异步执行窗口工作流核心逻辑"""
        # 创建执行器
        executor = self._create_window_executor(window, workflow_data)
        if not executor:
            raise Exception(f"窗口 {window.title} 执行器创建失败")

        window.executor = executor
        window.current_step = "executing"

        # 在线程中执行同步的工作流逻辑
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,  # 使用默认线程池
            self._run_executor_sync,
            executor
        )

        return result

    def _run_executor_sync(self, executor):
        """在线程池中同步运行执行器"""
        try:
            # 直接调用执行器的run方法
            executor.run()
            # 假设执行成功，返回标准格式
            return True, "执行完成", None
        except Exception as e:
            logger.error(f"执行器运行失败: {e}")
            return False, f"执行失败: {e}", None

    async def _execute_streaming_async(self, windows: List[WindowExecutionState], workflow_data: dict, delay_ms: int) -> bool:
        """异步流式执行"""
        try:
            logger.info(f"开始异步流式执行，窗口数: {len(windows)}")

            # 启动流式处理器
            await self.stream_processor.start_processing(self)

            # 提交所有任务到流式处理器
            for window in windows:
                await self.stream_processor.submit_task(window, workflow_data)

            # 异步处理结果
            success_count = 0
            processed_count = 0

            async for result in self.stream_processor.get_results():
                processed_count += 1

                if isinstance(result, ExecutionResult):
                    if result.success:
                        success_count += 1

                    # 记录性能数据
                    await self.performance_monitor.record_task_result(
                        f"stream_{result.window_title}_{result.window_hwnd}", result
                    )

                # 检查是否处理完所有窗口
                if processed_count >= len(windows):
                    break

            # 停止流式处理器
            await self.stream_processor.stop_processing()

            logger.info(f"异步流式执行完成: {success_count}/{len(windows)} 成功")
            return success_count > 0

        except Exception as e:
            logger.error(f"异步流式执行失败: {e}", exc_info=True)
            await self.stream_processor.stop_processing()
            return False

    async def _execute_single_window_async(self, window: WindowExecutionState, workflow_data: dict, delay_ms: int) -> bool:
        """异步执行单个窗口"""
        try:
            result = await self._execute_window_async(window, workflow_data, delay_ms)
            return result.success
        except Exception as e:
            logger.error(f"单窗口异步执行失败: {e}", exc_info=True)
            return False

    def _execute_window_workflow_synchronized(self, window: WindowExecutionState, workflow_data: dict, delay_ms: int) -> bool:
        """执行同步窗口工作流"""
        try:
            # 等待开始同步点
            if not self.sync_manager.wait_at_sync_point(SyncPoint.START, window.title):
                logger.error(f"窗口 {window.title} 开始同步失败")
                return False

            # 执行工作流
            success = self._execute_window_workflow(window, workflow_data, delay_ms)

            # 等待完成同步点
            self.sync_manager.wait_at_sync_point(SyncPoint.FINISH, window.title)

            return success

        except Exception as e:
            logger.error(f"同步执行窗口工作流失败 {window.title}: {e}", exc_info=True)
            return False

    def _create_window_executor(self, window: WindowExecutionState, workflow_data: dict):
        """创建窗口执行器"""
        try:
            # 导入WorkflowExecutor

            # 创建执行器实例
            # 从workflow_data中提取必要的参数
            cards_data_raw = workflow_data.get('cards', {})
            connections_data = workflow_data.get('connections', [])
            if not isinstance(connections_data, list):
                logger.warning(f"connections 数据格式错误: {type(connections_data)}")
                connections_data = []
            else:
                safe_connections = []
                for conn in connections_data:
                    if isinstance(conn, dict):
                        safe_connections.append(conn)
                    else:
                        logger.warning(f"跳过无效连接条目: {type(conn)}")
                connections_data = safe_connections
            target_window_title = window.title
            images_dir = workflow_data.get('images_dir', None)

            # 工具 关键修复：优先使用全局execution_mode，如果没有则自动检测
            global_execution_mode = workflow_data.get('execution_mode', None)
            logger.info(f"从workflow_data获取全局execution_mode: {global_execution_mode}")

            # 工具 关键修复：转换cards_data格式并查找起始卡片ID
            start_card_id = None
            start_card_ids = []
            thread_labels = {}
            cards_data = {}  # WorkflowExecutor期望字典格式

            if isinstance(cards_data_raw, list):
                # cards_data是列表格式，转换为字典格式
                logger.debug(f"转换列表格式cards_data，共{len(cards_data_raw)}个卡片")
                for card in cards_data_raw:
                    if not isinstance(card, dict):
                        logger.warning(f"跳过无效卡片条目: {type(card)}")
                        continue
                    card_id = card.get('id')
                    if card_id is not None:
                        cards_data[card_id] = card
                        task_type_text = str(card.get('task_type') or '').strip()
                        if is_thread_start_task_type(task_type_text):
                            start_card_ids.append(card_id)
                            custom_name = str(card.get("custom_name") or "").strip()
                            if custom_name:
                                thread_labels[card_id] = custom_name
                            logger.debug(f"找到起点卡片: ID={card_id}, 类型={card.get('task_type')}")
            elif isinstance(cards_data_raw, dict):
                # cards_data已经是字典格式
                logger.debug(f"使用字典格式cards_data，共{len(cards_data_raw)}个卡片")
                cards_data = cards_data_raw
                for card_id, card in cards_data.items():
                    if not isinstance(card, dict):
                        logger.warning(f"跳过无效卡片条目: {type(card)}")
                        continue
                    task_type_text = str(card.get('task_type') or '').strip()
                    if is_thread_start_task_type(task_type_text):
                        start_card_ids.append(card_id)
                        custom_name = str(card.get("custom_name") or "").strip()
                        if custom_name:
                            thread_labels[card_id] = custom_name

            if start_card_ids:
                start_card_ids = sorted(set(start_card_ids))
                start_card_id = start_card_ids[0]

            if start_card_id is None:
                logger.error(f"未找到{THREAD_START_TASK_TYPE}，原始数据类型: {type(cards_data_raw)}")
                if isinstance(cards_data_raw, list) and len(cards_data_raw) > 0:
                    logger.debug(f"第一个卡片示例: {cards_data_raw[0]}")
                logger.debug(f"转换后cards_data: {list(cards_data.keys())}")
                return None

            logger.info(
                f"找到线程起点 {len(start_card_ids)} 个，默认线程起点ID: {start_card_id}，转换后cards_data包含{len(cards_data)}个卡片"
            )

            # Execution mode: prefer global execution_mode; default to background_sendmessage
            detected_execution_mode = "background_sendmessage"  # default background mode 1

            if global_execution_mode:
                detected_execution_mode = global_execution_mode
                logger.info(f"多窗口执行器使用全局execution_mode: {global_execution_mode}")
            else:
                logger.info("多窗口执行器未设置全局execution_mode，使用默认后台一模式")
            from utils.capture.screenshot_helper import get_screenshot_engine

            screenshot_engine = str(get_screenshot_engine() or "").strip().lower()
            workflow_id = f"window_{window.hwnd}_{id(window)}"
            workflow_filepath = (
                workflow_data.get("workflow_filepath")
                or workflow_data.get("file_path")
                or workflow_data.get("_workflow_filepath")
            )
            executor, process_thread = create_coordinated_workflow_runtime(
                source=ExecutionSource.MAIN_WINDOW,
                cards_data=cards_data,
                connections_data=connections_data,
                execution_mode=detected_execution_mode,
                screenshot_engine=screenshot_engine,
                images_dir=images_dir,
                workflow_id=workflow_id,
                workflow_filepath=workflow_filepath,
                start_card_ids=start_card_ids,
                target_window_title=target_window_title,
                target_hwnd=window.hwnd,
                thread_labels=thread_labels,
                bound_windows=self._runtime_bound_windows or [{"title": window.title, "hwnd": window.hwnd, "enabled": True}],
                parent=None,
            )

            if len(start_card_ids) > 1:
                logger.info(
                    "多窗口执行器启用多线程会话: window=%s, start_ids=%s",
                    window.title,
                    start_card_ids,
                )

            setattr(executor, "_process_thread_handle", process_thread)

            # 连接信号
            if hasattr(executor, 'progress_updated'):
                executor.progress_updated.connect(
                    lambda progress: self.communication_hub.send_message(
                        "window_progress",
                        {"window_title": window.title, "progress": progress}
                    )
                )

            if hasattr(executor, 'error_occurred'):
                executor.error_occurred.connect(
                    lambda card_id, error, window_title=window.title, window_hwnd=window.hwnd: self.communication_hub.send_message(
                        "window_error",
                        {
                            "window_title": window_title,
                            "window_hwnd": window_hwnd,
                            "card_id": card_id,
                            "error": error,
                        }
                    )
                )

            if hasattr(executor, 'card_executing'):
                executor.card_executing.connect(
                    lambda card_id: self.communication_hub.send_message(
                        "card_status",
                        {"window_title": window.title, "card_id": card_id, "status": "executing"}
                    )
                )

            if hasattr(executor, 'card_finished'):
                executor.card_finished.connect(
                    lambda card_id, success: self.communication_hub.send_message(
                        "card_status",
                        {"window_title": window.title, "card_id": card_id, "status": "finished", "success": success}
                    )
                )

            if hasattr(executor, 'show_warning'):
                executor.show_warning.connect(
                    lambda title, message, window_title=window.title: self.show_warning.emit(
                        f"{window_title} - {title}" if window_title else title,
                        message,
                    )
                )

            logger.debug(f"为窗口 {window.title} 创建执行器成功")
            return executor

        except Exception as e:
            logger.error(f"创建窗口执行器失败 {window.title}: {e}", exc_info=True)
            return None

    def stop_all(self, force: bool = False):
        """停止所有执行 - 增强版本"""
        try:
            # 使用增强停止管理器（如果可用）
            if hasattr(self, 'stop_integration') and self.stop_integration:
                logger.info("使用增强停止管理器停止所有窗口")
                return bool(self.stop_integration.request_stop_all(timeout=30.0, force=force))
            
            # 回退到原始实现
            with self._main_lock:
                if not self.is_running:
                    logger.info("多窗口执行器未在运行")
                    return

                logger.info("开始停止所有多窗口执行")
                self._stop_requested = True

                # 工具 修复：使用线程池优雅停止所有窗口
                from concurrent.futures import ThreadPoolExecutor, as_completed
                
                def stop_window_gracefully(window):
                    """优雅停止单个窗口"""
                    try:
                        window_key = f"{window.title}_{window.hwnd}"

                        # 停止执行器
                        if window.executor and hasattr(window.executor, 'request_stop'):
                            try:
                                window.executor.request_stop(force=bool(force))
                            except TypeError:
                                window.executor.request_stop()
                            logger.debug(f"已请求停止窗口执行器: {window.title}")

                        # 工具 闪退修复：不在停止线程池中等待QThread
                        # QThread.wait()必须在主线程或其他Qt线程中调用
                        if window.thread and window.thread.isRunning():
                            logger.debug(f"正在请求停止窗口线程: {window.title}")

                            # 优雅停止 - 只发送quit信号，不等待
                            if hasattr(window.thread, 'stop'):
                                window.thread.stop()

                            window.thread.quit()
                            # 工具 关键修复：不在这里wait()，避免死锁
                            logger.debug(f"已发送quit信号给窗口线程: {window.title}")

                        # 重置窗口状态（保留线程引用供后续清理）
                        # window.reset() # 不在这里重置，避免丢失线程引用
                        return True, window.title

                    except Exception as e:
                        logger.error(f"停止窗口失败 {window.title}: {e}")
                        return False, window.title

                # 并行停止所有窗口
                with ThreadPoolExecutor(max_workers=10, thread_name_prefix="window_stopper") as executor:
                    futures = []
                    for window in self.windows.values():
                        future = executor.submit(stop_window_gracefully, window)
                        futures.append(future)

                    # 等待所有窗口停止完成
                    success_count = 0
                    failed_count = 0
                    for future in as_completed(futures, timeout=15.0):
                        try:
                            success, window_title = future.result()
                            if success:
                                success_count += 1
                                logger.debug(f"窗口停止成功: {window_title}")
                            else:
                                failed_count += 1
                                logger.warning(f"窗口停止失败: {window_title}")
                        except Exception as e:
                            failed_count += 1
                            logger.error(f"窗口停止异常: {e}")

                # 取消所有Future
                for future in self._execution_futures:
                    try:
                        future.cancel()
                    except Exception:
                        pass

                # 清理同步资源
                self.sync_manager.cleanup()

                # 工具 闪退修复：使用定时器延迟清理所有线程，避免在stop_all中阻塞
                from PySide6.QtCore import QTimer
                import weakref

                # 收集需要清理的线程（使用弱引用）
                threads_to_clean = []
                for window in self.windows.values():
                    if window.thread:
                        threads_to_clean.append((
                            weakref.ref(window.thread),
                            f"{window.title}_{window.hwnd}"
                        ))

                def delayed_thread_cleanup():
                    """延迟清理线程，确保在主线程中安全执行"""
                    logger.info(f"开始延迟清理 {len(threads_to_clean)} 个窗口线程")
                    for thread_ref, window_key in threads_to_clean:
                        thread = thread_ref() if thread_ref else None
                        if thread and thread.isRunning():
                            logger.error(f"线程仍在运行（放弃terminate以避免闪退）: {window_key}")
                            try:
                                if hasattr(thread, "requestInterruption"):
                                    thread.requestInterruption()
                                thread.quit()
                                thread.wait(1000)
                            except Exception as e:
                                logger.error(f"停止线程失败 {window_key}: {e}")
                            self._orphaned_threads.append(thread)
                        elif thread:
                            logger.debug(f"线程已正常退出: {window_key}")

                    self._prune_orphaned_references()

                    # 清理完成后重置所有窗口状态
                    for window in self.windows.values():
                        try:
                            window.reset()
                        except Exception as e:
                            logger.error(f"重置窗口状态失败 {window.title}: {e}")

                    logger.info("延迟线程清理完成")

                # 3秒后在主线程中执行清理
                QTimer.singleShot(3000, delayed_thread_cleanup)
                logger.info("已启动延迟线程清理定时器（3秒后执行）")

                # 清理OCR上下文数据，防止影响下次执行
                try:
                    from task_workflow.workflow_context import clear_all_ocr_data
                    clear_all_ocr_data()
                    logger.info("多窗口执行停止，已清理所有OCR上下文数据")
                except Exception as e:
                    logger.warning(f"清理OCR上下文数据时发生错误: {e}")

                # 标记停止
                self.is_running = False

                # 结束性能监控
                if hasattr(self, 'performance_monitor'):
                    try:
                        # 修复：检查是否为异步性能监控器
                        if hasattr(self.performance_monitor, 'end_timing'):
                            if asyncio.iscoroutinefunction(self.performance_monitor.end_timing):
                                # 异步版本，但在同步上下文中，使用同步方法
                                if hasattr(self.performance_monitor, '_sync_end_timing'):
                                    total_time = self.performance_monitor._sync_end_timing("total_execution")
                                else:
                                    total_time = 0.0  # 回退值
                                    logger.warning("异步性能监控器在同步上下文中，无法获取准确计时")
                            else:
                                # 同步版本
                                total_time = self.performance_monitor.end_timing("total_execution")
                            logger.info(f"多窗口执行已停止，总耗时: {total_time:.2f}秒")
                        else:
                            logger.info("多窗口执行已停止")
                    except Exception as e:
                        logger.warning(f"结束性能监控时出错: {e}")
                        logger.info("多窗口执行已停止")

                # 生成停止消息
                total_windows = success_count + failed_count
                if failed_count == 0:
                    message = f"多窗口执行已停止 - 总计: {total_windows}, 成功: {success_count}, 耗时: {total_time:.1f}秒"
                else:
                    message = f"多窗口执行已停止 - 总计: {total_windows}, 成功: {success_count}, 失败: {failed_count}"

                # 【内存泄漏修复】停止后清理截图缓存和内存
                try:
                    from utils.capture.screenshot_helper import clear_screenshot_cache
                    clear_screenshot_cache()
                    logger.info("[停止清理] 已清理截图帧缓存")
                except Exception as e:
                    logger.debug(f"清理截图缓存失败: {e}")

                # 发送完成信号
                self.execution_completed.emit(True, message)
                logger.info(message)

        except Exception as e:
            logger.error(f"停止多窗口执行失败: {e}", exc_info=True)

            # 即使停止失败，也要清理OCR上下文数据
            try:
                from task_workflow.workflow_context import clear_all_ocr_data
                clear_all_ocr_data()
                logger.info("多窗口执行异常停止，已清理所有OCR上下文数据")
            except Exception as cleanup_e:
                logger.warning(f"异常停止时清理OCR上下文数据发生错误: {cleanup_e}")

            # 确保发送完成信号
            self.execution_completed.emit(False, f"停止失败: {str(e)}")

    async def stop_all_async(self, timeout: float = 30.0) -> bool:
        """异步停止所有执行"""
        try:
            logger.info("开始异步停止所有多窗口执行")

            # 设置取消事件
            self._cancellation_event.set()
            self._stop_requested = True

            # 取消所有异步任务
            cancel_tasks = []
            for task_name, task in self._async_tasks.items():
                if not task.done():
                    logger.debug(f"取消异步任务: {task_name}")
                    task.cancel()
                    cancel_tasks.append(task)

            # 等待所有任务取消完成
            if cancel_tasks:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*cancel_tasks, return_exceptions=True),
                        timeout=timeout
                    )
                    logger.info(f"成功取消 {len(cancel_tasks)} 个异步任务")
                except asyncio.TimeoutError:
                    logger.warning(f"取消异步任务超时 ({timeout}秒)")

            # 停止流式处理器
            await self.stream_processor.stop_processing()

            # 清理资源
            await self.resource_manager.cleanup()

            # 重置状态
            self._async_tasks.clear()
            for window in self.windows.values():
                if window.status == TaskStatus.RUNNING:
                    window.status = TaskStatus.CANCELLED
                window.reset()

            self.is_running = False
            logger.info("异步停止完成")

            # 【内存泄漏修复】异步停止后也要清理截图缓存和GC
            try:
                from utils.capture.screenshot_helper import clear_screenshot_cache
                clear_screenshot_cache()
                logger.info("[异步停止清理] 已清理截图帧缓存")
            except Exception as e:
                logger.debug(f"清理截图缓存失败: {e}")

            return True

        except Exception as e:
            logger.error(f"异步停止失败: {e}", exc_info=True)
            return False

    async def get_async_performance_stats(self) -> Dict[str, Any]:
        """获取异步性能统计"""
        try:
            performance_stats = await self.performance_monitor.get_metrics()
            resource_stats = await self.resource_manager.get_resource_stats()

            return {
                'performance': performance_stats,
                'resources': resource_stats,
                'async_tasks': {
                    'total': len(self._async_tasks),
                    'running': sum(1 for task in self._async_tasks.values() if not task.done()),
                    'completed': sum(1 for task in self._async_tasks.values() if task.done() and not task.cancelled()),
                    'cancelled': sum(1 for task in self._async_tasks.values() if task.cancelled()),
                },
                'windows': {
                    'total': len(self.windows),
                    'enabled': len([w for w in self.windows.values() if w.enabled]),
                    'running': len([w for w in self.windows.values() if w.status == TaskStatus.RUNNING]),
                    'completed': len([w for w in self.windows.values() if w.status == TaskStatus.COMPLETED]),
                    'failed': len([w for w in self.windows.values() if w.status == TaskStatus.FAILED]),
                    'cancelled': len([w for w in self.windows.values() if w.status == TaskStatus.CANCELLED]),
                }
            }
        except Exception as e:
            logger.error(f"获取异步性能统计失败: {e}")
            return {'error': str(e)}

    def cleanup(self):
        """清理资源 - 增强版"""
        try:
            logger.info("开始清理统一多窗口执行器资源")

            # 如果有异步任务在运行，尝试异步清理
            if self._async_tasks and any(not task.done() for task in self._async_tasks.values()):
                logger.warning("检测到运行中的异步任务，建议使用 stop_all_async() 进行清理")

            # 清理同步资源
            self.sync_manager.cleanup()
            self.thread_pool.shutdown()
            self.communication_hub.cleanup()

            # 【内存泄漏修复】清理性能监控器累积的数据
            if hasattr(self, 'performance_monitor') and self.performance_monitor:
                self.performance_monitor.reset()

            # 清理异步资源（同步方式）
            try:
                # 如果有事件循环，尝试异步清理
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 创建清理任务
                    cleanup_task = asyncio.create_task(self._async_cleanup())
                    logger.info("已创建异步清理任务")
                else:
                    # 运行异步清理
                    loop.run_until_complete(self._async_cleanup())
            except RuntimeError:
                # 没有事件循环，进行基本清理
                logger.info("没有事件循环，进行基本清理")
                self._basic_cleanup()

            # 重置状态
            self.windows.clear()
            self._async_tasks.clear()
            self.is_running = False
            self._prune_orphaned_references()

            logger.info("统一多窗口执行器资源清理完成")

        except Exception as e:
            logger.error(f"清理资源失败: {e}", exc_info=True)

    async def _async_cleanup(self):
        """异步清理内部方法"""
        try:
            await self.resource_manager.cleanup()
            await self.stream_processor.stop_processing()

            # 取消所有未完成的任务
            for task in self._async_tasks.values():
                if not task.done():
                    task.cancel()

            # 等待任务取消
            if self._async_tasks:
                await asyncio.gather(*self._async_tasks.values(), return_exceptions=True)

        except Exception as e:
            logger.error(f"异步清理失败: {e}")

    def _basic_cleanup(self):
        """基本清理方法"""
        try:
            # 取消所有异步任务
            for task in self._async_tasks.values():
                if not task.done():
                    task.cancel()

            # 清理其他资源
            self._async_tasks.clear()

        except Exception as e:
            logger.error(f"基本清理失败: {e}")
