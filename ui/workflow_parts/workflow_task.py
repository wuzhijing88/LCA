#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工作流任务类
用于管理单个工作流任务的数据、状态和执行
"""

import logging
import os
from typing import Dict, Any, Optional
from threading import Lock
from PySide6.QtCore import QObject, Signal, QTimer, Qt, Slot

from task_workflow.process_proxy import (
    ProcessWorkflowExecutorProxy,
    ProcessWorkflowThreadHandle,
    create_process_workflow_runtime,
)
from utils.thread_start_utils import THREAD_START_TASK_TYPE, is_thread_start_task_type
from utils.window_binding_utils import get_bound_windows_for_mode

logger = logging.getLogger(__name__)

class WorkflowTask(QObject):
    """单个工作流任务"""

    # 信号定义
    status_changed = Signal(str)  # status: 'idle', 'running', 'paused', 'completed', 'failed', 'stopped'
    runtime_cleanup_finished = Signal()  # async runtime cleanup fully completed
    progress_updated = Signal(str)  # progress_message
    execution_finished = Signal(bool, str, str)  # success, message, stop_reason ('success', 'failed', 'no_next')
    card_executing = Signal(int)  # card_id - 卡片开始执行
    card_finished = Signal(int, bool)  # card_id, success - 卡片完成
    step_log = Signal(str, str, bool)  # card_type, message, success - 浮动窗口日志
    param_updated = Signal(int, str, object)  # card_id, param_name, new_value

    def __init__(self, task_id: int, name: str, filepath: str, workflow_data: dict,
                 task_modules: Dict[str, Any], images_dir: str, config: dict,
                 parent=None):
        """
        初始化工作流任务

        Args:
            task_id: 任务ID
            name: 任务名称（显示名）
            filepath: 任务文件路径
            workflow_data: 工作流数据（cards + connections）
            task_modules: 任务模块字典
            images_dir: 图片目录
            config: 全局配置
            parent: 父对象
        """
        super().__init__(parent)

        self.task_id = task_id
        self.name = name
        self.filepath = filepath
        self.source_ref = filepath
        self.workflow_data = workflow_data
        self.read_only_mode = False
        self.read_only_reason = ""
        self.task_modules = task_modules
        self.images_dir = images_dir
        self.config = config

        # 任务状态
        self._status = 'idle'  # 'idle', 'running', 'completed', 'failed', 'stopped'
        self.enabled = True  # 是否启用
        self.modified = False  # 是否已修改

        # 执行器相关
        self.executor: Optional[ProcessWorkflowExecutorProxy] = None
        self.executor_thread: Optional[ProcessWorkflowThreadHandle] = None
        self._last_runtime_variables: Optional[Dict[str, Any]] = None

        # 【修复】添加线程锁，防止重复启动/停止导致的竞态条件
        self._execution_lock = Lock()  # 执行锁（启动保护）
        self._stop_lock = Lock()  # 停止锁（停止保护）
        self._cleanup_lock = Lock()  # 清理锁（清理保护）
        self._status_lock = Lock()  # 状态锁（状态更新保护）
        self._overlay_hide_delay_ms = 180
        self._overlay_hide_request_token = 0

        # 执行配置（继承全局配置）
        self.execution_mode = config.get('execution_mode', 'foreground')

        # 窗口绑定配置（标签页专属）
        self.bound_window_id = None  # 绑定的窗口ID（在config['bound_windows']中的索引或唯一标识）
        self.target_window_title = ''  # 窗口标题
        self.target_hwnd = None  # 目标窗口句柄

        # 跳转配置（基于工作流停止类型的自动跳转）
        self.stop_reason = None  # 'success', 'failed', 'no_next' 停止原因
        self.jump_enabled = True  # 是否启用跳转
        self.auto_execute_after_jump = True  # 跳转后是否自动执行
        self.jump_rules = {}  # 跳转规则 {'success': target_task_id, 'failed': target_task_id}
        self.jump_delay = 0  # 跳转延迟（秒），0表示立即跳转
        self.first_execute = False  # 是否为首个执行的工作流
        self.max_jump_count = 0  # 最大跳转次数，0表示无限循环

        logger.info(f"创建任务: ID={task_id}, 名称='{name}'")

    @Slot(int)
    def _relay_card_executing(self, card_id: int):
        """跨线程中转：确保卡片执行中信号在 WorkflowTask 所在线程发出。"""
        self.card_executing.emit(card_id)

    @Slot(int, bool)
    def _relay_card_finished(self, card_id: int, success: bool):
        """跨线程中转：确保卡片完成信号在 WorkflowTask 所在线程发出。"""
        self.card_finished.emit(card_id, success)

    @Slot(str, str, bool)
    def _relay_step_log(self, card_type: str, message: str, success: bool):
        """跨线程中转：确保日志信号在 WorkflowTask 所在线程发出。"""
        self.step_log.emit(card_type, message, success)

    @Slot(int, str, object)
    def _relay_param_updated(self, card_id: int, param_name: str, new_value: Any):
        """跨线程中转：确保参数更新信号在 WorkflowTask 所在线程发出。"""
        self.param_updated.emit(card_id, param_name, new_value)

    @Slot(object)
    def _on_overlay_update_requested(self, payload: Any):
        """在主进程执行YOLO画框，避免子进程直接负责窗口绘制。"""
        if not isinstance(payload, dict):
            return

        self._overlay_hide_request_token += 1

        action = str(payload.get("action") or "update").strip().lower()
        try:
            from tasks.yolo_detection import draw_detections_on_window, hide_detections_overlay
        except Exception as exc:
            logger.debug(f"任务 '{self.name}' 加载YOLO画框模块失败: {exc}")
            return

        if action == "hide":
            hide_detections_overlay()
            return

        try:
            hwnd = int(payload.get("hwnd") or 0)
        except Exception:
            return
        if hwnd <= 0:
            return

        detections = payload.get("detections")
        if not isinstance(detections, list):
            detections = []

        frame_shape = payload.get("frame_shape")
        normalized_frame_shape = None
        if isinstance(frame_shape, (list, tuple)):
            try:
                normalized_frame_shape = tuple(int(v) for v in tuple(frame_shape)[:3])
            except Exception:
                normalized_frame_shape = None

        draw_detections_on_window(hwnd, detections, normalized_frame_shape)

    def _finalize_overlay_hide_request(self, request_token: int) -> None:
        if int(request_token) != int(self._overlay_hide_request_token):
            return
        try:
            from tasks.yolo_detection import hide_detections_overlay

            hide_detections_overlay()
        except Exception as exc:
            logger.debug(f"任务 '{self.name}' 清理YOLO画框失败: {exc}")

    def _hide_detection_overlay_in_main_process(self) -> None:
        self._overlay_hide_request_token += 1
        request_token = int(self._overlay_hide_request_token)
        QTimer.singleShot(
            max(0, int(self._overlay_hide_delay_ms)),
            lambda token=request_token, self_ref=self: self_ref._finalize_overlay_hide_request(token),
        )

    def _connect_overlay_update_signal(self) -> None:
        if self.executor is None:
            raise RuntimeError(f"任务 '{self.name}' 尚未创建执行器")
        self.executor.overlay_update_requested.connect(
            self._on_overlay_update_requested,
            Qt.ConnectionType.AutoConnection,
        )

    @property
    def status(self) -> str:
        """获取任务状态"""
        return self._status

    @status.setter
    def status(self, value: str):
        """设置任务状态并发送信号"""
        if self._status != value:
            old_status = self._status
            self._status = value
            logger.info(f"任务 '{self.name}' 状态变更: {old_status} -> {value}")
            self.status_changed.emit(value)

    def can_execute(self) -> bool:
        """只有完全停止的任务才能创建一次新的执行。"""
        return self.enabled and self.status in ['idle', 'completed', 'failed', 'stopped']

    def can_stop(self) -> bool:
        """检查是否可以停止"""
        return self.status in ['running', 'paused']

    @staticmethod
    def _is_start_task_type(task_type: Any) -> bool:
        """统一判定线程起点类型。"""
        return is_thread_start_task_type(task_type)

    def execute_sync(self) -> bool:
        """
        同步执行任务（阻塞直到完成）

        Returns:
            是否执行成功
        """
        # 【修复】使用非阻塞锁防止重复启动导致的竞态条件
        if not self._execution_lock.acquire(blocking=False):
            logger.error(f"任务 '{self.name}' 已经在启动中，拒绝重复启动请求")
            return False

        try:
            if self.status == 'paused':
                logger.error(f"任务 '{self.name}' 已暂停；启动命令不能代替恢复命令")
                return False

            if not self.can_execute():
                logger.warning(f"任务 '{self.name}' 当前状态 '{self.status}' 不允许执行")
                return False

            logger.info(f"开始同步执行任务: {self.name}")

            if self.executor is not None or self.executor_thread is not None:
                logger.error(f"任务 '{self.name}' 上一次运行尚未完成资源清理，拒绝启动")
                return False

            # 【修复】立即更新状态，缩小竞态条件时间窗口
            self.status = 'running'

            try:

                # 创建执行器
                self._create_executor()
                self._last_runtime_variables = None

                # 【性能优化】不使用QEventLoop阻塞主线程,改为使用标志位+processEvents
                # 这样可以让主线程保持响应,不会影响UI拖拽和动画
                from PySide6.QtCore import QCoreApplication

                # 创建线程执行（避免阻塞GUI）
                self.executor.moveToThread(self.executor_thread)

                # 记录执行结果
                execution_finished = [False]  # 是否执行完成
                execution_success = [False]  # 使用列表包装以便在闭包中修改
                execution_message = [""]

                def on_finished(success: bool, message: str):
                    execution_message[0] = message
                    execution_success[0] = success  # 直接使用传入的success布尔值
                    execution_finished[0] = True  # 标记为已完成
                    self._capture_runtime_variables_from_executor(self.executor)
                    logger.info(f"同步执行完成: success={success}, message={message}")

                # 连接信号
                self.executor_thread.started.connect(self.executor.run)
                self.executor.execution_finished.connect(on_finished)
                self.executor.step_details.connect(
                    self._on_step_details,
                    Qt.ConnectionType.QueuedConnection,
                )
                # 转发卡片执行状态信号
                self.executor.card_executing.connect(
                    self._relay_card_executing,
                    Qt.ConnectionType.QueuedConnection,
                )
                self.executor.card_finished.connect(
                    self._relay_card_finished,
                    Qt.ConnectionType.QueuedConnection,
                )
                # 转发浮动窗口日志信号
                self.executor.step_log.connect(
                    self._relay_step_log,
                    Qt.ConnectionType.QueuedConnection,
                )
                self.executor.param_updated.connect(
                    self._relay_param_updated,
                    Qt.ConnectionType.QueuedConnection,
                )
                self._connect_overlay_update_signal()

                # 启动线程
                self.executor_thread.start()
                logger.info(f"任务 '{self.name}' 开始在后台线程执行（同步等待）")

                # 【性能优化】使用processEvents代替QEventLoop.exec()
                # 这样主线程保持完全响应,不会影响UI操作
                # 所有延迟(包括成功和失败的100ms延迟)都在executor后台线程执行,不阻塞主线程
                while not execution_finished[0]:
                    # 处理所有类型的待处理事件,保持UI完全响应
                    # WaitForMoreEvents标志: 如果没有事件则等待,避免空转占用CPU
                    QCoreApplication.processEvents(
                        QCoreApplication.ProcessEventsFlag.AllEvents |
                        QCoreApplication.ProcessEventsFlag.WaitForMoreEvents,
                        1  # 最多等待1ms
                    )

                # 等待线程结束 - 优化版,减少等待时间
                if self.executor_thread.isRunning():
                    self.executor_thread.quit()
                    # 【优化】减少等待时间从5秒到0.5秒
                    if not self.executor_thread.wait(500):
                        logger.warning(f"任务 '{self.name}' 线程在0.5秒内未退出,继续处理")

                # 检测停止原因
                stop_reason = self._detect_stop_reason(execution_success[0], execution_message[0])
                self.stop_reason = stop_reason
                logger.info(f"任务 '{self.name}' 停止原因: {stop_reason}")

                # 更新状态
                if execution_success[0]:
                    self.status = 'completed'
                    self.execution_finished.emit(True, execution_message[0], stop_reason)
                    logger.info(f"任务 '{self.name}' 同步执行成功")
                    return True
                else:
                    self.status = 'failed'
                    self.execution_finished.emit(False, execution_message[0], stop_reason)
                    logger.error(f"任务 '{self.name}' 同步执行失败")
                    return False

            except Exception as e:
                logger.error(f"任务 '{self.name}' 执行失败: {e}", exc_info=True)
                self.status = 'failed'
                self.stop_reason = 'failed'
                self.execution_finished.emit(False, f"任务 '{self.name}' 执行失败: {e}", 'failed')
                return False
            finally:
                self._cleanup_executor()
                self._hide_detection_overlay_in_main_process()

        finally:
            # 【修复】释放执行锁
            self._execution_lock.release()

    def _detect_stop_reason(self, success: bool, message: str) -> str:
        """
        检测工作流停止的原因

        Args:
            success: 是否成功
            message: 执行结果消息

        Returns:
            stop_reason: 'success' (成功停止), 'failed' (失败停止), 'no_next' (无后续卡片), 'stopped' (用户停止)
        """
        message_text = str(message or "")
        if self.status == 'stopped':
            return 'stopped'
        if (
            '工作流被用户停止' in message_text
            or '用户停止' in message_text
            or '手动停止' in message_text
            or '任务已停止' in message_text
        ):
            return 'stopped'

        if success:
            # 检查是否是因为没有后续卡片而停止
            if '没有后续' in message_text or '无后续' in message_text or '流程结束' in message_text:
                return 'no_next'
            else:
                return 'success'
        else:
            return 'failed'

    def execute_async(self) -> Optional[ProcessWorkflowThreadHandle]:
        """
        异步执行任务（立即返回，后台运行）

        Returns:
            执行线程对象
        """
        # 【修复】使用非阻塞锁防止重复启动导致的竞态条件
        if not self._execution_lock.acquire(blocking=False):
            logger.error(f"任务 '{self.name}' 已经在启动中，拒绝重复启动请求")
            return None

        try:
            if self.status == 'paused':
                logger.error(f"任务 '{self.name}' 已暂停；启动命令不能代替恢复命令")
                return None

            if not self.can_execute():
                logger.warning(f"任务 '{self.name}' 当前状态 '{self.status}' 不允许执行")
                return None

            logger.info(f"开始执行任务: {self.name}")

            if self.executor is not None or self.executor_thread is not None:
                logger.error(f"任务 '{self.name}' 上一次运行尚未完成资源清理，拒绝启动")
                return None

            # 【修复】使用状态锁保护状态更新，缩小竞态条件时间窗口
            with self._status_lock:
                self.status = 'running'

            try:

                # 创建执行器
                self._create_executor()
                self._last_runtime_variables = None

                self.executor.moveToThread(self.executor_thread)

                # 连接信号
                self.executor_thread.started.connect(self.executor.run)
                self.executor.execution_finished.connect(self._on_async_execution_finished)
                # 异步执行完成后必须主动退出线程事件循环，否则线程会残留到下次启动。
                self.executor.execution_finished.connect(
                    self.executor_thread.quit,
                    Qt.ConnectionType.DirectConnection,
                )
                self.executor.step_details.connect(
                    self._on_step_details,
                    Qt.ConnectionType.QueuedConnection,
                )
                # 转发卡片执行状态信号
                self.executor.card_executing.connect(
                    self._relay_card_executing,
                    Qt.ConnectionType.QueuedConnection,
                )
                self.executor.card_finished.connect(
                    self._relay_card_finished,
                    Qt.ConnectionType.QueuedConnection,
                )
                # 转发浮动窗口日志信号
                self.executor.step_log.connect(
                    self._relay_step_log,
                    Qt.ConnectionType.QueuedConnection,
                )
                self.executor.param_updated.connect(
                    self._relay_param_updated,
                    Qt.ConnectionType.QueuedConnection,
                )
                self._connect_overlay_update_signal()

                # 关键修复：连接线程的finished信号来清理引用
                # 线程退出由 WorkflowExecutor.run 的收尾阶段主动请求，避免竞态导致执行器引用提前清空。
                self.executor_thread.finished.connect(self._cleanup_executor_thread)

                # 启动线程
                self.executor_thread.start()
                logger.info(f"任务 '{self.name}' 执行已启动")

                return self.executor_thread

            except Exception as e:
                logger.error(f"任务 '{self.name}' 启动失败: {e}", exc_info=True)
                # 【修复】使用状态锁保护状态更新
                with self._status_lock:
                    self.status = 'failed'
                    self.stop_reason = 'failed'
                self.execution_finished.emit(False, f"任务 '{self.name}' 启动失败: {e}", 'failed')
                self._cleanup_executor()
                return None

        finally:
            # 【修复】释放执行锁
            self._execution_lock.release()

    def stop(self):
        """停止任务执行"""
        # 【修复】使用非阻塞锁防止重复停止导致的竞态条件
        if not self._stop_lock.acquire(blocking=False):
            logger.error(f"任务 '{self.name}' 已经在停止中，拒绝重复停止请求")
            return False

        try:
            thread_running = bool(self.executor_thread and self.executor_thread.isRunning())

            # 不能只依赖status：状态可能先被改为stopped，但执行线程仍在跑。
            if not self.can_stop() and not thread_running:
                logger.warning(f"任务 '{self.name}' 当前状态 '{self.status}' 且无活动线程，忽略停止请求")
                return False

            logger.info(f"请求停止任务: {self.name}")

            if self.executor is None:
                logger.error(f"任务 '{self.name}' 存在活动线程但执行器引用缺失，无法按契约停止")
                return False

            stop_requested = self.executor.request_stop(force=True)
            if stop_requested is not True:
                logger.warning(f"任务 '{self.name}' 强制停止请求失败")
                return False

            with self._status_lock:
                self.status = 'stopped'
                self.stop_reason = 'stopped'  # 用户手动停止
            return True

        finally:
            # 【修复】释放停止锁
            self._stop_lock.release()

    def pause(self):
        """暂停任务执行"""
        # 【修复】使用状态锁保护状态更新
        with self._status_lock:
            if self.status != 'running':
                logger.warning(f"任务 '{self.name}' 当前状态 '{self.status}' 无法暂停")
                return False

            logger.info(f"暂停任务: {self.name}")

            if self.executor is None:
                logger.error(f"任务 '{self.name}' 缺少运行中的执行器")
                return False
            pause_result = self.executor.pause()
            if pause_result is not True:
                logger.warning(f"任务 '{self.name}' 暂停命令发送失败")
                return False

            self.status = 'paused'
            return True

    def resume(self):
        """恢复任务执行"""
        # 【修复】使用状态锁保护状态更新
        with self._status_lock:
            if self.status != 'paused':
                logger.warning(f"任务 '{self.name}' 当前状态 '{self.status}' 无法恢复")
                return False

            logger.info(f"恢复任务: {self.name}")

            if self.executor is None:
                logger.error(f"任务 '{self.name}' 缺少运行中的执行器")
                return False
            resume_result = self.executor.resume()
            if resume_result is not True:
                logger.warning(f"任务 '{self.name}' 恢复命令发送失败")
                return False

            self.status = 'running'
            return True

    def _create_executor(self):
        """创建工作流执行器"""
        if not isinstance(self.workflow_data, dict):
            raise ValueError(f"Task '{self.name}' workflow_data must be a dict")

        cards = self.workflow_data.get('cards', [])
        if not isinstance(cards, list):
            raise ValueError(f"Task '{self.name}' workflow cards must be a list")

        cards_dict: Dict[int, Dict[str, Any]] = {}
        for index, card in enumerate(cards):
            if not isinstance(card, dict):
                raise TypeError(f"任务 '{self.name}' 的卡片必须是字典，索引: {index}")
            card_id = card.get('id')
            if isinstance(card_id, bool) or not isinstance(card_id, int):
                raise TypeError(
                    f"任务 '{self.name}' 的卡片ID必须是整数，索引: {index}, value={card_id!r}"
                )
            if card_id in cards_dict:
                raise ValueError(f"任务 '{self.name}' 存在重复卡片ID: {card_id}")
            task_type = card.get('task_type')
            if not isinstance(task_type, str) or not task_type.strip():
                raise ValueError(f"任务 '{self.name}' 的卡片 {card_id} 缺少任务类型")
            cards_dict[card_id] = card

        connections_list = self.workflow_data.get('connections', [])
        if not isinstance(connections_list, list):
            raise TypeError(f"任务 '{self.name}' 的工作流连接必须是列表")

        seen_connections = set()
        for index, connection in enumerate(connections_list):
            if not isinstance(connection, dict):
                raise TypeError(f"任务 '{self.name}' 的连接必须是字典，索引: {index}")
            start_id = connection.get('start_card_id')
            end_id = connection.get('end_card_id')
            line_type = connection.get('type')
            if isinstance(start_id, bool) or not isinstance(start_id, int):
                raise TypeError(f"任务 '{self.name}' 的连接起点ID必须是整数，索引: {index}")
            if isinstance(end_id, bool) or not isinstance(end_id, int):
                raise TypeError(f"任务 '{self.name}' 的连接终点ID必须是整数，索引: {index}")
            if start_id not in cards_dict or end_id not in cards_dict:
                raise ValueError(
                    f"任务 '{self.name}' 的连接引用了不存在的卡片: {start_id}->{end_id}"
                )
            if not isinstance(line_type, str) or not line_type.strip():
                raise ValueError(f"任务 '{self.name}' 的连接类型不能为空，索引: {index}")
            connection_key = (start_id, end_id, line_type.strip())
            if connection_key in seen_connections:
                raise ValueError(
                    f"任务 '{self.name}' 存在重复连接: {start_id}->{end_id} ({line_type.strip()})"
                )
            seen_connections.add(connection_key)

        # 调试：打印连接数据以排查为什么不能跳转到下一个卡片
        logger.info(f"任务 '{self.name}' 加载了 {len(connections_list)} 个连接")
        if not connections_list:
            logger.warning(f"任务 '{self.name}' 没有任何连接数据！这会导致只执行第一个卡片就停止")

        # 查找线程起始卡片
        session_start_card_ids = []
        thread_labels = {}
        for card in cards:
            if not self._is_start_task_type(card.get('task_type')):
                continue
            start_card_id_value = card['id']
            session_start_card_ids.append(start_card_id_value)
            custom_name = str(card.get("custom_name") or "").strip()
            if custom_name:
                thread_labels[start_card_id_value] = custom_name

        if not session_start_card_ids:
            raise ValueError(f"任务 '{self.name}' 必须包含至少一个{THREAD_START_TASK_TYPE}")

        target_hwnd = self.target_hwnd
        target_window_title = self.target_window_title
        effective_bound_windows = get_bound_windows_for_mode(self.config)
        if not isinstance(effective_bound_windows, list):
            raise TypeError("bound_windows 必须是列表")

        # 验证标签页绑定的窗口是否仍在全局设置中
        if target_hwnd:
            bound_windows = effective_bound_windows
            hwnd_still_bound = any(
                isinstance(window, dict)
                and window.get('hwnd') == target_hwnd
                and window.get('enabled', True) is True
                for window in bound_windows
            )

            if not hwnd_still_bound:
                raise ValueError(
                    f"任务 '{self.name}' 绑定的窗口不在当前全局窗口配置中: "
                    f"'{target_window_title}' (HWND: {target_hwnd})"
                )

        if not target_hwnd:
            # 标签页没有绑定窗口，或绑定的窗口不在全局设置中
            bound_windows = effective_bound_windows
            if bound_windows:
                first_enabled_window = None
                for window in bound_windows:
                    if not isinstance(window, dict):
                        raise TypeError("bound_windows 中的窗口配置必须是字典")
                    enabled = window.get('enabled', True)
                    if not isinstance(enabled, bool):
                        raise TypeError("窗口配置 enabled 必须是布尔值")
                    if enabled:
                        first_enabled_window = window
                        break

                if first_enabled_window:
                    target_hwnd = first_enabled_window.get('hwnd')
                    target_window_title = first_enabled_window.get('title', '')

                    import win32gui
                    if not win32gui.IsWindow(target_hwnd):
                        raise ValueError(f"任务 '{self.name}' 执行失败：全局窗口已失效（标题: '{target_window_title}'，HWND: {target_hwnd}）")

                    logger.info("=" * 80)
                    logger.info(f"[使用全局窗口] 任务 '{self.name}' 使用全局配置的第一个启用窗口")
                    logger.info(f"  - 窗口标题: {target_window_title}")
                    logger.info(f"  - 窗口句柄: {target_hwnd}")
                    logger.info("=" * 80)
                else:
                    logger.warning("[跳过执行] 全局设置中没有启用的窗口")
                    raise ValueError(f"任务 '{self.name}' 执行失败：全局设置中没有启用的窗口，请先在窗口管理中绑定至少一个窗口")
            else:
                logger.warning("[跳过执行] 没有绑定任何窗口")
                raise ValueError(f"任务 '{self.name}' 执行失败：没有绑定任何窗口，请先在窗口管理中绑定窗口")
        else:
            import win32gui
            if not win32gui.IsWindow(target_hwnd):
                raise ValueError(f"任务 '{self.name}' 执行失败：标签页绑定窗口已失效（标题: '{target_window_title}'，HWND: {target_hwnd}）")

            logger.info("=" * 80)
            logger.info(f"[使用标签页绑定] 任务 '{self.name}' 使用标签页绑定的窗口")
            logger.info(f"  - 窗口标题: {target_window_title}")
            logger.info(f"  - 窗口句柄: {target_hwnd}")
            logger.info("=" * 80)

        # 创建执行器
        from task_workflow.workflow_vars import workflow_context_key
        workflow_id = workflow_context_key(self.task_id)
        if not workflow_id:
            raise ValueError(f"任务 '{self.name}' 无法生成运行上下文ID")
        self.executor, self.executor_thread = create_process_workflow_runtime(
            cards_data=cards_dict,
            connections_data=connections_list,
            execution_mode=self.execution_mode,
            screenshot_engine=self.config.get("screenshot_engine"),
            images_dir=self.images_dir,
            workflow_id=workflow_id,
            workflow_filepath=self.filepath,
            start_card_ids=session_start_card_ids,
            target_window_title=target_window_title,
            target_hwnd=target_hwnd,
            thread_labels=thread_labels,
            bound_windows=effective_bound_windows,
            parent=None,
        )

        if len(session_start_card_ids) > 1:
            logger.info(
                "任务 '%s' 使用多线程会话执行，起点数量=%d: %s",
                self.name,
                len(session_start_card_ids),
                session_start_card_ids,
            )

        logger.debug(f"任务 '{self.name}' 进程执行器创建成功")

    def _cleanup_executor(self):
        """清理执行器资源 - 优化版,不等待线程"""
        if self.executor_thread and self.executor_thread.isRunning():
            self.executor_thread.quit()
            # 【关键优化】不等待线程结束,让它自然退出
            # 线程会通过finished信号自动清理引用
            logger.debug(f"任务 '{self.name}' 请求线程退出,不等待")
        else:
            # 线程已经停止,直接清理引用
            thread = self.executor_thread
            self.executor = None
            self.executor_thread = None
            if thread is not None:
                try:
                    thread.deleteLater()
                except RuntimeError:
                    pass

    def _force_cleanup_executor(self) -> bool:
        """终止当前进程执行器并在确认退出后清理引用。"""
        if not self._cleanup_lock.acquire(blocking=False):
            logger.error(f"任务 '{self.name}' 清理操作已在进行中")
            return False

        try:
            executor = self.executor
            thread = self.executor_thread
            if executor is None and thread is None:
                return True
            if executor is None or thread is None:
                logger.error(f"任务 '{self.name}' 的执行器与线程句柄状态不一致")
                return False

            logger.warning(f"任务 '{self.name}' 正在终止进程执行器")
            executor.terminate()
            if not executor.wait_for_exit(3000):
                logger.error(f"任务 '{self.name}' 的进程执行器在3秒内未退出")
                return False

            self._capture_runtime_variables_from_executor(executor)
            self.executor = None
            self.executor_thread = None
            thread.deleteLater()
            self._hide_detection_overlay_in_main_process()
            logger.info(f"任务 '{self.name}' 强制清理完成")
            return True

        except Exception as e:
            logger.error(f"强制清理执行器时发生错误: {e}", exc_info=True)
            return False

        finally:
            self._cleanup_lock.release()

    def _capture_runtime_variables_from_executor(self, executor_obj) -> bool:
        """Capture runtime variables from an executor before references are cleared."""
        if executor_obj is None:
            return False
        runtime_vars = executor_obj._final_runtime_variables
        if not isinstance(runtime_vars, dict):
            raise TypeError("执行器运行时变量快照必须是字典")
        if not runtime_vars:
            return False
        if set(runtime_vars) != {"global_vars", "var_sources"}:
            raise ValueError("执行器运行时变量快照必须包含且仅包含 global_vars/var_sources")
        if not isinstance(runtime_vars["global_vars"], dict) or not isinstance(
            runtime_vars["var_sources"], dict
        ):
            raise TypeError("执行器运行时变量快照内容必须是字典")
        self._last_runtime_variables = {
            "global_vars": dict(runtime_vars["global_vars"]),
            "var_sources": dict(runtime_vars["var_sources"]),
        }
        return True

    def _cleanup_executor_thread(self):
        """清理执行器线程引用（从线程的finished信号调用）"""
        finished_thread = self.sender()
        should_emit_runtime_cleanup = False

        # 【修复】使用锁保护，防止与execute_async并发导致的竞态条件
        with self._cleanup_lock:
            current_thread = self.executor_thread

            # 防止旧线程的finished信号误清理当前正在运行的新执行器。
            if finished_thread is not None and current_thread is not None and finished_thread is not current_thread:
                logger.warning(f"任务 '{self.name}' 收到旧线程finished信号，忽略引用清理")
                thread = finished_thread
            else:
                logger.info(f"任务 '{self.name}' 线程已结束，清理线程引用")
                thread = current_thread
                self.executor = None
                self.executor_thread = None
                should_emit_runtime_cleanup = self.status in ('completed', 'failed', 'stopped')

        if thread is not None:
            try:
                thread.deleteLater()
            except RuntimeError:
                pass

        if should_emit_runtime_cleanup:
            self._hide_detection_overlay_in_main_process()
            self.runtime_cleanup_finished.emit()

    def _on_async_execution_finished(self, success: bool, message: str):
        """执行完成回调"""
        self._capture_runtime_variables_from_executor(self.executor)

        # 【修复】使用状态锁保护状态更新，防止与stop()并发导致的竞态条件
        with self._status_lock:
            # 检测停止原因
            stop_reason = self._detect_stop_reason(success, message)
            self.stop_reason = stop_reason

            logger.info(f"========== 任务 '{self.name}' 执行完成 ==========")
            logger.info(f"  success = {success}")
            logger.info(f"  message = {message}")
            logger.info(f"  stop_reason = {stop_reason}")
            logger.info(f"  jump_rules = {getattr(self, 'jump_rules', {})}")
            logger.info("============================================")

            if stop_reason == 'stopped' or self.status == 'stopped':
                self.status = 'stopped'
                logger.info(f"任务 '{self.name}' 已停止")
            elif success:
                self.status = 'completed'
                logger.info(f"任务 '{self.name}' 执行完成")
            else:
                self.status = 'failed'
                logger.error(f"任务 '{self.name}' 执行失败: {message}")

        # 【注意】信号发射放在锁外面，避免死锁
        self.execution_finished.emit(success, message, stop_reason)
        # 不在这里调用 _cleanup_executor()，让线程的finished信号处理清理

    @Slot(str)
    def _on_step_details(self, details: str):
        """步骤详情回调"""
        self.progress_updated.emit(details)

    def update_workflow_data(self, workflow_data: dict):
        """更新工作流数据（编辑后）"""
        self.workflow_data = workflow_data
        self.modified = True
        logger.debug(f"任务 '{self.name}' 工作流数据已更新")

    def save(self, workflow_data: dict = None) -> bool:
        """
        保存任务到文件

        Args:
            workflow_data: 可选的工作流数据，如果提供则使用此数据，否则使用self.workflow_data
        """
        # 如果没有文件路径（新建的空白工作流），返回False
        if self.read_only_mode:
            logger.info(f"任务 '{self.name}' 为只读运行态，跳过保存")
            self.modified = False
            return True

        if not self.filepath:
            logger.warning(f"任务 '{self.name}' 没有保存路径，需要先另存为")
            return False

        try:
            import json

            # 确保文件路径是绝对路径
            abs_filepath = os.path.abspath(self.filepath)
            logger.debug(f"保存任务 '{self.name}': 原始路径={self.filepath}, 绝对路径={abs_filepath}")

            # 确保目录存在
            file_dir = os.path.dirname(abs_filepath)
            if file_dir and not os.path.exists(file_dir):
                logger.info(f"创建目录: {file_dir}")
                os.makedirs(file_dir, exist_ok=True)

            # 创建保存数据，包含工作流和跳转配置
            # 如果提供了workflow_data，使用它；否则使用self.workflow_data
            save_data = (workflow_data if workflow_data is not None else self.workflow_data).copy()
            save_data.pop("variables", None)

            # 【关键修复】同时更新内存中的 workflow_data，确保执行器使用最新数据
            if workflow_data is not None:
                # 只更新 cards 和 connections，保留其他配置
                self.workflow_data['cards'] = workflow_data.get('cards', [])
                self.workflow_data['connections'] = workflow_data.get('connections', [])
                logger.info(f"任务 '{self.name}' 内存中的 workflow_data 已同步更新")

            # 添加跳转配置到保存数据
            save_data['jump_config'] = {
                'enabled': self.jump_enabled,
                'rules': self.jump_rules.copy(),
                'delay': self.jump_delay,
                'first_execute': self.first_execute
            }

            # 添加窗口绑定配置到保存数据
            save_data['window_binding'] = {
                'bound_window_id': self.bound_window_id,
                'target_window_title': self.target_window_title,
                'target_hwnd': self.target_hwnd
            }

            # 保存文件
            logger.debug(f"写入文件: {abs_filepath}")
            with open(abs_filepath, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)

            self.modified = False
            logger.info(f"✓ 任务 '{self.name}' 已保存到: {abs_filepath}")
            logger.debug(f"  跳转配置: enabled={self.jump_enabled}, rules={self.jump_rules}, delay={self.jump_delay}秒, first_execute={self.first_execute}")
            return True

        except Exception as e:
            logger.error(f"✗ 保存任务 '{self.name}' 失败: {e}", exc_info=True)
            return False

    def backup(self) -> bool:
        """
        备份任务到 backups 目录

        Returns:
            是否备份成功
        """
        if self.read_only_mode:
            logger.info(f"任务 '{self.name}' 为只读运行态，跳过保存")
            return True

        try:
            import shutil
            from datetime import datetime

            # 检查文件路径是否存在
            if not self.filepath:
                logger.warning(f"任务 '{self.name}' 没有文件路径，无法备份")
                return False

            # 确保文件路径是绝对路径
            abs_filepath = os.path.abspath(self.filepath)
            logger.debug(f"备份任务 '{self.name}': 原始路径={self.filepath}, 绝对路径={abs_filepath}")

            # 检查文件是否存在
            if not os.path.exists(abs_filepath):
                logger.warning(f"任务 '{self.name}' 文件不存在: {abs_filepath}，跳过备份")
                return False

            # 创建 backups 目录（如果不存在）
            base_dir = os.path.dirname(abs_filepath)
            backups_dir = os.path.join(base_dir, 'backups')

            logger.debug(f"创建备份目录: {backups_dir}")
            os.makedirs(backups_dir, exist_ok=True)

            # 生成备份文件名：原文件名_backup_时间戳.json
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = os.path.basename(abs_filepath)
            name_without_ext = os.path.splitext(filename)[0]
            backup_filename = f"{name_without_ext}_backup_{timestamp}.json"
            backup_filepath = os.path.join(backups_dir, backup_filename)

            # 复制文件到备份目录
            logger.debug(f"复制文件: {abs_filepath} -> {backup_filepath}")
            shutil.copy2(abs_filepath, backup_filepath)

            logger.info(f"✓ 任务 '{self.name}' 已备份到: {backup_filepath}")
            return True

        except Exception as e:
            logger.error(f"✗ 备份任务 '{self.name}' 失败: {e}", exc_info=True)
            return False

    def save_and_backup(self, workflow_data: dict = None) -> bool:
        """
        保存并备份任务

        对于未保存的工作流（没有filepath），会创建临时备份

        Args:
            workflow_data: 可选的工作流数据，如果提供则使用此数据，否则使用self.workflow_data

        Returns:
            是否全部成功
        """
        # 如果没有文件路径（新建的空白工作流），创建临时备份
        if self.read_only_mode:
            logger.info(f"任务 '{self.name}' 为只读运行态，跳过保存和备份")
            self.modified = False
            return True

        if not self.filepath:
            logger.info(f"任务 '{self.name}' 未保存，创建临时备份")
            try:
                import json
                import tempfile
                from datetime import datetime

                # 创建临时备份目录
                temp_dir = os.path.join(tempfile.gettempdir(), 'workflow_temp_backups')
                os.makedirs(temp_dir, exist_ok=True)

                # 生成临时备份文件名
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                # 清理文件名中的非法字符
                safe_name = "".join(c for c in self.name if c.isalnum() or c in (' ', '_', '-')).strip()
                temp_filename = f"{safe_name}_temp_backup_{timestamp}.json"
                temp_filepath = os.path.join(temp_dir, temp_filename)

                # 使用提供的数据或默认数据
                save_data = (workflow_data if workflow_data is not None else self.workflow_data).copy()
                save_data.pop("variables", None)

                # 添加跳转配置
                save_data['jump_config'] = {
                    'enabled': self.jump_enabled,
                    'rules': self.jump_rules.copy(),
                    'delay': self.jump_delay,
                    'first_execute': self.first_execute
                }

                # 保存到临时文件
                with open(temp_filepath, 'w', encoding='utf-8') as f:
                    json.dump(save_data, f, ensure_ascii=False, indent=2)

                # 更新任务的workflow_data，确保执行时使用最新数据
                if workflow_data is not None:
                    self.workflow_data = workflow_data.copy()
                    logger.info(f"任务 '{self.name}' 已更新内存中的 workflow_data")

                logger.info(f"任务 '{self.name}' 临时备份成功: {temp_filepath}")
                return True

            except Exception as e:
                logger.error(f"任务 '{self.name}' 临时备份失败: {e}")
                return False

        # 正常的保存和备份流程
        save_success = self.save(workflow_data=workflow_data)
        backup_success = self.backup()

        if save_success and backup_success:
            logger.info(f"任务 '{self.name}' 保存和备份成功")
            return True
        else:
            if not save_success:
                logger.error(f"任务 '{self.name}' 保存失败")
            if not backup_success:
                logger.warning(f"任务 '{self.name}' 备份失败")
            return False

    def bind_window(self, window_info: dict) -> bool:
        """
        绑定窗口到此任务

        Args:
            window_info: 窗口信息字典,包含:
                - hwnd: 窗口句柄
                - title: 窗口标题
                - enabled: 是否启用
                - window_id: 窗口唯一标识(可选)

        Returns:
            bool: 是否绑定成功
        """
        try:
            import win32gui
            
            hwnd = window_info.get('hwnd')
            if not hwnd or not win32gui.IsWindow(hwnd):
                logger.error(f"无效的窗口句柄: {hwnd}")
                return False

            # 绑定窗口
            logger.info(f"绑定窗口: {window_info.get('title')}")
            self.target_hwnd = hwnd

            # 保存窗口信息
            self.bound_window_id = window_info.get('window_id', hwnd)  # 使用window_id或hwnd作为标识
            self.target_window_title = window_info.get('title', '')

            # 标记为已修改
            self.modified = True

            logger.info(f"任务 '{self.name}' 成功绑定窗口: '{self.target_window_title}' (HWND: {self.target_hwnd})")
            return True

        except Exception as e:
            logger.error(f"绑定窗口失败: {e}", exc_info=True)
            return False

    def unbind_window(self):
        """解除窗口绑定"""
        self.bound_window_id = None
        self.target_hwnd = None
        self.target_window_title = ''
        self.modified = True
        logger.info(f"任务 '{self.name}' 已解除窗口绑定")

    def get_bound_window_info(self) -> dict:
        """
        获取绑定的窗口信息

        Returns:
            dict: 窗口信息
        """
        return {
            'bound_window_id': self.bound_window_id,
            'target_hwnd': self.target_hwnd,
            'target_window_title': self.target_window_title
        }

    def __repr__(self):
        return f"<WorkflowTask id={self.task_id} name='{self.name}' status='{self.status}'>"
