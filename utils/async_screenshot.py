#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
异步截图管道
提供非阻塞的截图请求机制，提高工作流执行效率
"""

import logging
import time
import uuid
import threading
from typing import Optional, Dict
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import numpy as np

logger = logging.getLogger(__name__)


class AsyncScreenshotPipeline:
    """
    异步截图管道

    功能：
    1. 接收截图请求，返回Future对象
    2. 后台工作线程处理截图队列
    3. 避免阻塞主线程

    使用场景：
    - 图片识别任务可以先提交截图请求，然后处理其他事情
    - 多个识别任务可以并行提交截图请求
    """

    def __init__(self, max_workers: int = 2):
        """
        初始化异步截图管道

        Args:
            max_workers: 最大工作线程数（默认2个足够）
        """
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ScreenshotWorker")
        self.request_futures: Dict[str, Future] = {}
        self._stats = {
            'total_requests': 0,
            'total_success': 0,
            'total_failed': 0,
            'total_time_ms': 0.0
        }
        self._lock = threading.Lock()
        self._running = True

        logger.info(f"异步截图管道已启动 (workers={max_workers})")

    def _on_future_done(self, request_id: str, future: Future) -> None:
        """统一回收请求索引，覆盖取消/异常/正常完成三种路径。"""
        with self._lock:
            tracked = self.request_futures.get(request_id)
            if tracked is future:
                self.request_futures.pop(request_id, None)

    def request_screenshot(self, hwnd: int, use_cache: bool = False,
                          client_area_only: bool = True) -> Future:
        """
        提交截图请求（非阻塞）

        Args:
            hwnd: 窗口句柄
            use_cache: 是否使用缓存（默认False，获取最新帧）
            client_area_only: 是否只截取客户区

        Returns:
            Future对象，可用于异步获取截图结果
        """
        with self._lock:
            if not self._running:
                raise RuntimeError("截图管道已关闭")

            request_id = str(uuid.uuid4())
            self._stats['total_requests'] += 1

            # 提交到线程池执行
            future = self.executor.submit(
                self._capture_worker,
                request_id,
                hwnd,
                use_cache,
                client_area_only
            )

            self.request_futures[request_id] = future
            future.add_done_callback(
                lambda done_future, rid=request_id: self._on_future_done(rid, done_future)
            )
            if future.done():
                self._on_future_done(request_id, future)
        logger.debug(f"截图请求已提交: {request_id} (hwnd={hwnd})")

        return future

    def _capture_worker(self, request_id: str, hwnd: int,
                       use_cache: bool, client_area_only: bool) -> Optional[np.ndarray]:
        """
        工作线程：执行实际截图

        Args:
            request_id: 请求ID
            hwnd: 窗口句柄
            use_cache: 是否使用缓存
            client_area_only: 是否只截取客户区

        Returns:
            截图数组或None
        """
        start_time = time.time()

        try:
            # 延迟导入，避免循环依赖
            from utils.screenshot_helper import _capture_with_engine, get_screenshot_engine

            # 获取当前截图引擎
            engine = get_screenshot_engine()

            # 执行截图
            frame = _capture_with_engine(
                hwnd=hwnd,
                client_area_only=client_area_only,
                engine=engine
            )

            elapsed_ms = (time.time() - start_time) * 1000

            if frame is not None:
                with self._lock:
                    self._stats['total_success'] += 1
                    self._stats['total_time_ms'] += elapsed_ms
                logger.debug(f"截图请求完成: {request_id} ({elapsed_ms:.1f}ms)")
            else:
                with self._lock:
                    self._stats['total_failed'] += 1
                logger.warning(f"截图请求失败: {request_id}")

            return frame

        except Exception as e:
            with self._lock:
                self._stats['total_failed'] += 1
            logger.error(f"截图请求异常 {request_id}: {e}", exc_info=True)
            return None

        finally:
            # 清理请求记录
            with self._lock:
                self.request_futures.pop(request_id, None)

    def request_screenshot_sync(self, hwnd: int, timeout: float = 2.0,
                               use_cache: bool = False,
                               client_area_only: bool = True) -> Optional[np.ndarray]:
        """
        提交截图请求并等待结果（同步接口）

        Args:
            hwnd: 窗口句柄
            timeout: 超时时间（秒）
            use_cache: 是否使用缓存（默认False，获取最新帧）
            client_area_only: 是否只截取客户区

        Returns:
            截图数组或None
        """
        future = self.request_screenshot(hwnd, use_cache, client_area_only)

        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            try:
                cancelled = future.cancel()
                if cancelled:
                    with self._lock:
                        for request_id, tracked_future in list(self.request_futures.items()):
                            if tracked_future is future:
                                self.request_futures.pop(request_id, None)
                                break
            except Exception:
                pass
            logger.error(f"截图请求超时 (hwnd={hwnd}, timeout={timeout}s)")
            return None
        except Exception as e:
            logger.error(f"获取截图结果失败: {type(e).__name__}: {e}")
            return None

    def shutdown(self, wait: bool = True):
        """
        关闭截图管道

        Args:
            wait: 是否等待所有任务完成
        """
        with self._lock:
            if not self._running:
                return
            self._running = False
            futures_snapshot = list(self.request_futures.values())

        logger.info(f"正在关闭异步截图管道 (wait={wait})...")
        # wait=False 时尽量取消未开始执行的任务
        if not wait:
            for future in futures_snapshot:
                try:
                    if not future.done():
                        future.cancel()
                except Exception:
                    pass

        try:
            self.executor.shutdown(wait=wait, cancel_futures=(not wait))
        except TypeError:
            # 兼容旧版本Python
            self.executor.shutdown(wait=wait)

        with self._lock:
            pending_count = len(self.request_futures)
            self.request_futures.clear()
        if pending_count > 0:
            logger.warning(f"还有 {pending_count} 个截图请求未完成")

        logger.info(f"异步截图管道已关闭. 统计: {self.get_stats()}")

    def get_stats(self) -> dict:
        """获取统计信息"""
        with self._lock:
            stats = self._stats.copy()
            pending_requests = len(self.request_futures)

        if stats['total_success'] > 0:
            stats['avg_time_ms'] = stats['total_time_ms'] / stats['total_success']
        else:
            stats['avg_time_ms'] = 0

        stats['pending_requests'] = pending_requests

        return stats

    def __del__(self):
        """析构时确保关闭"""
        self.shutdown(wait=False)


# 全局单例
_global_pipeline: Optional[AsyncScreenshotPipeline] = None
_global_lock = threading.Lock()


def get_global_pipeline() -> AsyncScreenshotPipeline:
    """获取全局异步截图管道"""
    global _global_pipeline
    if _global_pipeline is None:
        with _global_lock:
            if _global_pipeline is None:
                _global_pipeline = AsyncScreenshotPipeline(max_workers=2)
    return _global_pipeline


def shutdown_global_pipeline():
    """关闭全局管道"""
    global _global_pipeline
    with _global_lock:
        pipeline = _global_pipeline
        _global_pipeline = None
    if pipeline is not None:
        pipeline.shutdown(wait=True)


# 简化的API
