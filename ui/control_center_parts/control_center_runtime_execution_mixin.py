import copy
import logging

from PySide6.QtCore import Qt
from app_core.runtime.execution_coordinator import (
    ExecutionSource,
    create_coordinated_workflow_runtime,
)
from utils.thread_start_utils import THREAD_START_TASK_TYPE

from .control_center_runtime_types import TaskState

logger = logging.getLogger(__name__)


class WindowTaskRunnerExecutionMixin:
    def _get_effective_execution_mode(self) -> str:
        execution_mode = self._configured_execution_mode or "background_sendmessage"
        if self._configured_execution_mode:
            logger.info(f"中控使用显式 execution_mode: {execution_mode}")
        else:
            logger.info(f"中控未显式提供 execution_mode，使用默认值: {execution_mode}")
        return execution_mode

    def run(self):
        """运行工作流 - QThread的主运行方法"""
        try:
            if self._abort_if_stop_requested("启动前收到停止请求"):
                return

            # 检查是否可以启动
            if not self.can_start:
                logger.warning(f"窗口{self.window_id}当前状态{self._current_state.value}不允许启动")
                return

            # 设置启动状态
            self._set_state(TaskState.STARTING, "正在初始化工作流")
            self._is_running = True

            if self._abort_if_stop_requested("初始化阶段收到停止请求"):
                return

            if not self._acquire_execution_slot():
                if self._should_stop:
                    self._set_state(TaskState.STOPPED, "等待执行槽位时已取消")
                else:
                    self._set_state(TaskState.FAILED, "获取执行槽位失败", force=True)
                self._emit_task_completed_once(False)
                return

            window_title = self.window_info.get('title', '未知窗口')
            window_hwnd = self.window_info.get('hwnd', 0)

            if not self.workflow_data:
                self._set_state(TaskState.FAILED, "错误: 未分配工作流")
                self._emit_task_completed_once(False)
                return

            if not isinstance(self.workflow_data, dict):
                self._set_state(TaskState.FAILED, "错误: 工作流数据格式不正确")
                self._emit_task_completed_once(False)
                return

            # 检查工作流格式
            if 'cards' not in self.workflow_data:
                self._set_state(TaskState.FAILED, "错误: 工作流格式不正确")
                self._emit_task_completed_once(False)
                return

            cards = self.workflow_data.get('cards', [])
            if not isinstance(cards, list):
                self._set_state(TaskState.FAILED, "错误: 工作流卡片数据格式不正确")
                self._emit_task_completed_once(False)
                return
            cards = copy.deepcopy(cards)

            # 基础校验：卡片必须包含有效ID，避免后续KeyError导致崩溃
            invalid_cards = []
            for index, card in enumerate(cards):
                if not isinstance(card, dict) or card.get('id') is None:
                    invalid_cards.append(index)
            if invalid_cards:
                self._set_state(TaskState.FAILED, f"错误: 卡片数据缺少ID，索引: {invalid_cards}")
                self._emit_task_completed_once(False)
                return

            # 转换数据格式并识别起点（兼容字符串/整数ID）
            cards_dict = {}
            start_card_id = None
            start_card_ids = []
            session_start_card_ids = []
            thread_labels = {}
            for card in cards:
                card_id = card['id']
                cards_dict[card_id] = card
                cards_dict[str(card_id)] = card
                normalized_card_id = self._parse_card_id_as_int(card_id)
                if normalized_card_id is not None:
                    cards_dict[normalized_card_id] = card

                if not self._is_start_task_type(card.get('task_type')):
                    continue

                start_card_ids.append(card_id)
                if normalized_card_id is not None and normalized_card_id not in session_start_card_ids:
                    session_start_card_ids.append(normalized_card_id)
                    custom_name = str(card.get("custom_name") or "").strip()
                    if custom_name:
                        thread_labels[normalized_card_id] = custom_name

            self._rebuild_card_step_labels(cards)

            connections_list = self.workflow_data.get('connections', [])
            if not isinstance(connections_list, list):
                logger.warning(f"Window {self.window_id} workflow connections must be a list, got {type(connections_list)}")
                connections_list = []
            else:
                safe_connections = []
                for conn in connections_list:
                    if isinstance(conn, dict):
                        safe_connections.append(copy.deepcopy(conn))
                    else:
                        logger.warning(f"Window {self.window_id} skipping invalid connection entry: {type(conn)}")
                connections_list = safe_connections

            if session_start_card_ids:
                start_card_id = session_start_card_ids[0]

            start_card_id_for_executor = start_card_id

            if start_card_id_for_executor is None:
                self._set_state(TaskState.FAILED, f"错误: 工作流必须包含至少一个{THREAD_START_TASK_TYPE}")
                self._emit_task_completed_once(False)
                return

            if self._abort_if_stop_requested("创建执行器前收到停止请求"):
                return

            logger.info(
                "窗口%s线程起点识别完成: 线程起点总数=%d, 并发线程=%d, 默认线程起点=%s",
                self.window_id,
                len(start_card_ids),
                len(session_start_card_ids),
                start_card_id_for_executor,
            )

            # 窗口句柄只通过 WorkflowExecutor 的 target_hwnd 传入，不写进程级 HWND。
            execution_mode = self._get_effective_execution_mode()

            workflow_id = self._build_workflow_id()
            images_dir = self.workflow_data.get('images_dir', None)

            self.executor, self.executor_thread = create_coordinated_workflow_runtime(
                source=ExecutionSource.CONTROL_CENTER,
                cards_data=cards_dict,
                connections_data=connections_list,
                execution_mode=execution_mode,
                screenshot_engine=self._runtime_config.get("screenshot_engine"),
                images_dir=images_dir,
                workflow_id=workflow_id,
                workflow_filepath=self.workflow_file_path,
                start_card_ids=session_start_card_ids,
                target_window_title=window_title,
                target_hwnd=window_hwnd,
                thread_labels=thread_labels,
                bound_windows=self.bound_windows,
                parent=None,
            )

            if len(session_start_card_ids) > 1:
                logger.info(
                    "窗口%s启用多线程会话，线程起点=%s",
                    self.window_id,
                    session_start_card_ids,
                )


            # 连接信号 - 使用Qt.QueuedConnection确保跨线程安全
            self.executor.execution_started.connect(
                self._on_execution_started,
                Qt.ConnectionType.QueuedConnection
            )
            self.executor.execution_finished.connect(
                self._on_execution_finished,
                Qt.ConnectionType.QueuedConnection
            )
            self.executor.step_details.connect(
                self._on_step_details,
                Qt.ConnectionType.QueuedConnection
            )
            self.executor.card_executing.connect(
                self._on_card_executing,
                Qt.ConnectionType.QueuedConnection
            )
            self.executor.card_finished.connect(
                self._on_card_finished,
                Qt.ConnectionType.QueuedConnection
            )
            self._set_state(TaskState.RUNNING, "工作流启动中")
            logger.info(f"窗口工作流已启动: {window_title} (HWND: {window_hwnd})")

            if self._start_gate_event is not None and hasattr(self.executor, "_start_gate_event"):
                self.executor._start_gate_event = self._start_gate_event

            if self._abort_if_stop_requested("执行前收到停止请求"):
                try:
                    self.executor.request_stop(force=True)
                except Exception:
                    pass
                return

            self.executor.execution_finished.connect(self.quit, Qt.ConnectionType.DirectConnection)
            logger.info("进入QThread事件循环，等待执行完成")
            self.executor.run()
            self.exec()

        except Exception as e:
            logger.error(f"窗口工作流执行失败: {e}", exc_info=True)
            self._last_execution_message = f"错误: {str(e)}"
            self._last_execution_success = False
            self._set_state(TaskState.FAILED, f"错误: {str(e)}", force=True)
            self._emit_task_completed_once(False)
        finally:
            self._release_execution_slot()
            self._is_running = False
            logger.info(f"QThread运行完成: {self.window_id}")

    def _on_execution_started(self):
        """工作流开始执行回调"""
        logger.info(f"_on_execution_started 被调用: window_id={self.window_id}")
        self._set_state(TaskState.RUNNING, "工作流已启动")
        logger.info("已发出状态更新信号: 正在运行, 步骤: 工作流已启动")

    def _on_step_details(self, details):
        """步骤详情更新回调"""
        self._emit_step(details)

    def _on_card_executing(self, card_id):
        """卡片开始执行回调"""
        step_info = self._card_step_labels.get(str(card_id))
        if step_info:
            self._emit_step(step_info)
            return

        # 如果没有工作流数据或找不到卡片，至少显示卡片ID
        self._emit_step(f"执行卡片{card_id}")

    def _on_card_finished(self, card_id, success):
        """卡片执行完成回调"""
        if success:
            self._emit_step("步骤执行成功")
        else:
            self._emit_step("步骤执行失败")

    def _on_execution_finished(self, success: bool, message: str):
        """工作流执行完成回调"""
        try:
            self._last_execution_message = str(message or "").strip()
            self._last_execution_success = bool(success)
            # 区分不同的完成状态
            if "被用户停止" in message or "用户停止" in message:
                self._set_state(TaskState.STOPPED, "工作流被中断", force=True)
                success = False
            elif success:
                self._set_state(TaskState.COMPLETED, "工作流已完成", force=True)
            else:
                self._set_state(TaskState.FAILED, "工作流执行失败", force=True)

            logger.info(f"窗口{self.window_id}工作流执行完成: {self._current_state.value} - success={success}, {message}")

            # 发送任务完成信号
            self._emit_task_completed_once(success)

            # 只在线程真正退出后清理，避免停止竞态下提前释放运行中资源。
            if self.isRunning():
                self._defer_cleanup_until_thread_finished()
            else:
                self._cleanup_thread()

        except Exception as e:
            logger.error(f"执行完成回调处理失败: {e}")
            self._last_execution_message = f"错误: {str(e)}"
            self._last_execution_success = False
            self._set_state(TaskState.FAILED, f"错误: {str(e)}", force=True)
            self._emit_task_completed_once(False)
