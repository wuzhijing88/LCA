"""
工作流执行器模块
"""
import logging
import os
import re
import time
import threading
from typing import Callable, Dict, List, Any, Optional, Set, Tuple
from PySide6.QtCore import QObject, Signal, QThread
from task_workflow.card_display import find_card_by_id, format_step_detail
from task_workflow.graph_engine import GraphEngine
from task_workflow.run_context import RunContext
from task_workflow.window_adapter import WindowBinding, get_window_adapter
from task_workflow.workflow_identity import (
    normalize_workflow_filepath,
    normalize_workflow_id,
)
from task_workflow.task_result import normalize_task_result
from utils.input.input_guard import (
    acquire_input_guard,
    get_input_lock_timeout_seconds,
    get_input_lock_wait_warn_ms,
    resolve_input_lock_resource,
    task_requires_input_lock,
)
from utils.runtime_control import install_global_sleep_patch, thread_control_context
from task_workflow.thread_start import is_thread_start_task_type

logger = logging.getLogger(__name__)

install_global_sleep_patch()


class _ThreadErrorCaptureHandler(logging.Handler):
    """捕获当前执行线程的失败语义日志，用于汇总失败详情。"""

    def __init__(self, owner, thread_id: int):
        super().__init__(level=logging.INFO)
        self._owner = owner
        self._thread_id = thread_id

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if getattr(record, "thread", None) != self._thread_id:
                return
            if int(getattr(record, "levelno", 0)) < logging.INFO:
                return
            message = record.getMessage()
            if not message:
                return
            self._owner._on_captured_error_log(message, int(getattr(record, "levelno", logging.ERROR)))
        except Exception:
            return

# 安全导入 win32gui
try:
    import win32gui
    WIN32GUI_AVAILABLE = True
except ImportError:
    WIN32GUI_AVAILABLE = False
    logger.warning("win32gui 不可用，部分窗口激活功能将被禁用")


class WorkflowExecutor(QObject):
    """工作流执行器类"""

    _OCR_TASK_TYPES = {"OCR文字识别"}

    # 信号定义 - 与 main_window.py 中期望的信号保持一致
    execution_started = Signal()
    execution_finished = Signal(bool, str)  # success, status_message
    card_executing = Signal(int)  # card_id
    card_finished = Signal(int, bool)  # card_id, success
    error_occurred = Signal(int, str)  # card_id, error_message
    path_updated = Signal(int, str, str)  # card_id, param_name, new_path
    param_updated = Signal(int, str, object)  # card_id, param_name, new_value
    path_resolution_failed = Signal(int, str)  # card_id, original_path
    step_details = Signal(str)  # step_details
    show_warning = Signal(str, str)  # title, message - 用于显示警告对话框
    # 浮动窗口日志信号
    step_log = Signal(str, str, bool)  # card_type, message, success
    overlay_update_requested = Signal(object)  # YOLO画框请求，由主进程统一绘制
    def __init__(self, cards_data: Dict[str, Any], connections_data: List[Dict[str, Any]],
                 task_modules: Dict[str, Any], target_window_title: str = None,
                 execution_mode: str = 'foreground', start_card_id: str = None,
                 images_dir: str = None, target_hwnd: int = None, test_mode: str = None,
                 workflow_id: Optional[str] = None, workflow_filepath: Optional[str] = None,
                 get_image_data=None, parent=None,
                 workflow_context=None,
                 allowed_card_ids: Optional[Set[int]] = None,
                 disallowed_task_types: Optional[Set[str]] = None,
                 max_execution_steps: Optional[int] = None,
                 default_step_log_scope: str = "main",
                 default_step_log_name: Optional[str] = None,
                 external_stop_checker: Optional[Callable[[], bool]] = None,
                 external_pause_checker: Optional[Callable[[], bool]] = None,
                 cleanup_runtime_image_on_finish: bool = True,
                 clear_runtime_state_on_start: bool = True,
                 infinite_loop_guard_enabled: bool = False):
        """
        初始化工作流执行器

        Args:
            cards_data: 卡片数据字典
            connections_data: 连接数据列表
            task_modules: 任务模块字典
            target_window_title: 目标窗口标题
            execution_mode: 执行模式 ('foreground' 或 'background')
            start_card_id: 起始卡片ID
            images_dir: 图片目录
            target_hwnd: 目标窗口句柄
            test_mode: 测试模式 ('single_card' 或 'flow')
            workflow_id: 工作流上下文ID
            workflow_filepath: 主工作流文件路径（用于子工作流相对路径解析）
            workflow_context: 可选的执行上下文覆盖
            allowed_card_ids: 允许执行/跳转的卡片ID集合
            disallowed_task_types: 禁止执行的任务类型集合
            max_execution_steps: 最大执行步数限制
            cleanup_runtime_image_on_finish: 执行结束时是否清理全局识图运行态
            clear_runtime_state_on_start: 执行开始时是否清理当前上下文运行态
            infinite_loop_guard_enabled: 是否启用无出口循环逻辑保护
            parent: 父对象
        """
        super().__init__(parent)

        # 【修复闪退】确保传入的数据不为 None，防止后续调用 .items()/.get() 时闪退
        self.cards_data = cards_data if cards_data is not None else {}
        self.connections_data = connections_data if connections_data is not None else []
        self.task_modules = task_modules if task_modules is not None else {}
        self.target_hwnd = target_hwnd  # 目标窗口句柄（主要使用）
        self.target_window_title = target_window_title  # 窗口标题（仅用于日志显示）
        self.execution_mode = execution_mode or 'foreground'  # 【修复闪退】确保执行模式不为 None
        self.window_adapter = get_window_adapter(
            str(os.getenv("LCA_WINDOW_ADAPTER", "default") or "default")
        )
        self.start_card_id = start_card_id
        self.images_dir = images_dir
        self.get_image_data = get_image_data
        self.test_mode = test_mode  # 测试模式
        self.workflow_id = self._normalize_workflow_id(workflow_id)
        self.workflow_filepath = self._normalize_workflow_filepath(workflow_filepath)
        self.run_context = RunContext(
            workflow_id=self.workflow_id,
            start_card_id=self._normalize_card_id_value(start_card_id),
            window_hwnd=self._normalize_card_id_value(target_hwnd),
        )
        self._workflow_context_override = workflow_context
        self._allowed_card_ids = self._normalize_allowed_card_ids(allowed_card_ids)
        self._disallowed_task_types = {
            str(task_type or "").strip()
            for task_type in (disallowed_task_types or set())
            if str(task_type or "").strip()
        }
        self._max_execution_steps = self._normalize_positive_int(max_execution_steps)
        self._default_step_log_scope = str(default_step_log_scope or "main").strip() or "main"
        self._default_step_log_name = str(default_step_log_name or "").strip() or None
        self._external_stop_checker = external_stop_checker if callable(external_stop_checker) else None
        self._external_pause_checker = external_pause_checker if callable(external_pause_checker) else None
        self._cleanup_runtime_image_on_finish = bool(cleanup_runtime_image_on_finish)
        self._clear_runtime_state_on_start = bool(clear_runtime_state_on_start)
        self._infinite_loop_guard_enabled = bool(infinite_loop_guard_enabled)

        if isinstance(self.cards_data, list):
            converted_cards = {}
            for index, card in enumerate(self.cards_data):
                if isinstance(card, dict) and card.get('id') is not None:
                    converted_cards[card['id']] = card
                else:
                    logger.warning(f"跳过无效卡片数据(索引 {index}): {type(card)}")
            self.cards_data = converted_cards
        elif not isinstance(self.cards_data, dict):
            logger.error(f"cards_data 格式错误: {type(self.cards_data)}")
            self.cards_data = {}

        if not isinstance(self.connections_data, list):
            logger.error(f"connections_data 格式错误: {type(self.connections_data)}")
            self.connections_data = []

        self._stop_requested = False
        self._is_running = False
        self._current_card_id = None
        self._last_execution_success = False
        self._last_execution_message = ""
        self._last_failure_card_id = None
        self._last_failure_task_type = ""
        self._last_failure_detail = ""
        self._current_card_error_detail = ""
        self._current_card_error_detail_level = logging.NOTSET
        self._current_card_issue_logs: List[Dict[str, Any]] = []
        self._error_capture_handler = None
        self._capture_card_issue_logs = False
        self._paused = False  # 暂停标志
        self._is_retrying = False  # 重试进行中标志，防止并发重试
        self._force_stop = False  # 强制停止标志（不等待当前任务完成）
        self._start_gate_event = None

        # 工具 修复：添加持久计数器字典
        self._persistent_counters = {}
        # OCR热重置线程节流，避免高频切卡时线程堆积造成主进程内存上涨
        self._ocr_hot_reset_lock = threading.Lock()
        self._ocr_hot_reset_inflight = False
        self._ocr_hot_reset_last_ts = 0.0
        self._ocr_hot_reset_min_interval_sec = 1.0

        # 【测试流程】环路检测相关变量
        self._visited_cards = set()  # 记录已访问的卡片ID
        self._cycle_detected = False  # 是否检测到循环

        # 【新架构】附加条件映射：{被监控卡片ID: 附加条件卡片ID}
        self._monitor_card_map = {}  # 用于快速查找哪个卡片被哪个附加条件监控
        self._workflow_context = None  # 工作流上下文，存储附加条件配置

        # 创建连接映射以便查找下一个卡片
        self._connections_map = self._build_connections_map()

        # 【新架构】构建附加条件映射
        self._build_monitor_card_map()
        logger.info(f"WorkflowExecutor 初始化完成，起始卡片ID: {start_card_id}, test_mode: {test_mode}")

    @staticmethod
    def _normalize_workflow_id(workflow_id: Optional[str]) -> str:
        return normalize_workflow_id(workflow_id)

    @staticmethod
    def _normalize_workflow_filepath(workflow_filepath: Optional[str]) -> Optional[str]:
        return normalize_workflow_filepath(workflow_filepath)

    @staticmethod
    def _normalize_positive_int(value: Optional[int]) -> Optional[int]:
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            return None
        return normalized if normalized > 0 else None

    @staticmethod
    def _normalize_card_id_value(card_id: Any) -> Optional[int]:
        if card_id is None or isinstance(card_id, bool):
            return None
        try:
            return int(card_id)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _normalize_allowed_card_ids(cls, card_ids: Optional[Set[int]]) -> Optional[Set[int]]:
        if not card_ids:
            return None
        normalized = {
            card_id
            for card_id in (cls._normalize_card_id_value(item) for item in card_ids)
            if card_id is not None
        }
        return normalized or None

    def _get_workflow_context(self):
        if self._workflow_context_override is not None:
            return self._workflow_context_override
        from task_workflow.workflow_context import get_workflow_context
        return get_workflow_context(self.workflow_id)

    def _prepare_execution_context(self):
        context = self._get_workflow_context()
        try:
            context.executor = self
        except Exception:
            pass
        try:
            context.workflow_id = self.workflow_id
        except Exception:
            pass
        try:
            context.run_state = self.run_context
            context._monitor_configs = self.run_context.monitor_configs
        except Exception:
            pass
        try:
            context._should_stop_workflow = self.run_context.should_stop_workflow
        except Exception:
            pass
        return context

    def _resolve_runtime_params(self, card_id: int, card_params: Dict[str, Any]) -> Dict[str, Any]:
        context = self._get_workflow_context()
        store = getattr(context, "get_runtime_store", None)
        runtime_store = store() if callable(store) else getattr(context, "runtime_store", None)
        if runtime_store is None:
            return dict(card_params) if isinstance(card_params, dict) else {}
        runtime_store.bind_counters(self._persistent_counters)
        runtime_store.set_current_card_id(card_id)
        from task_workflow.expr import resolve_params

        return resolve_params(card_params, runtime_store)

    def _is_allowed_card_id(self, card_id: Any) -> bool:
        if self._allowed_card_ids is None or card_id is None:
            return True
        normalized = self._normalize_card_id_value(card_id)
        if normalized is None:
            return False
        return normalized in self._allowed_card_ids

    def _build_connections_map(self) -> Dict[int, List[Dict[str, Any]]]:
        """构建连接映射，方便查找下一个卡片"""
        valid_connections = []
        for connection in self.connections_data:
            if not isinstance(connection, dict):
                logger.warning(f"跳过无效连接数据: {type(connection)}")
                continue
            start_id = connection.get('start_card_id')
            end_id = connection.get('end_card_id')
            if start_id is None or end_id is None:
                logger.warning("跳过缺少 start_card_id/end_card_id 的连接数据")
                continue
            valid_connections.append(connection)
        self._graph_engine = GraphEngine(valid_connections)
        return self._graph_engine.as_connection_map()

    def _build_monitor_card_map(self):
        """【新架构】构建附加条件映射，识别哪个卡片被哪个附加条件监控"""
        self._monitor_card_map = {}

        logger.info(f"[附加条件映射] 开始构建，卡片总数: {len(self.cards_data)}")

        for card_id, card in self.cards_data.items():
            # 检查是否是附加条件卡片
            if hasattr(card, 'task_type'):
                task_type = card.task_type
            elif isinstance(card, dict):
                task_type = card.get('task_type', '')
            else:
                logger.warning(f"[附加条件映射] 跳过无效卡片数据: {type(card)}")
                continue

            # 兼容旧的"监控卡片"和新的"附加条件"
            if task_type == '附加条件':
                logger.info(f"[附加条件映射] 发现附加条件卡片: {card_id}")
                # 查找附加条件卡片的sequential连接，找出被监控的卡片
                connections = self._connections_map.get(card_id, [])
                for conn in connections:
                    if not isinstance(conn, dict):
                        continue
                    if conn.get('type') == 'sequential':
                        target_card_id = conn.get('end_card_id')
                        if target_card_id is not None and target_card_id != "":
                            self._monitor_card_map[target_card_id] = card_id
                            logger.info(f"[附加条件映射] 卡片 {target_card_id} 被附加条件卡片 {card_id} 监控")
                            break

        if self._monitor_card_map:
            logger.info(f"[附加条件映射] 构建完成，共 {len(self._monitor_card_map)} 个卡片被监控")
            logger.info(f"[附加条件映射] 映射详情: {self._monitor_card_map}")
        else:
            logger.info("[附加条件映射] 无附加条件卡片")

    def _auto_register_additional_conditions(self):
        """【关键】自动执行所有附加条件卡片以注册配置"""
        # 通过显式访问入口取任务模块，避免调用方依赖包内字典细节。
        try:
            from tasks import get_task_module
        except ImportError as e:
            raise RuntimeError(f"无法导入附加条件任务模块: {e}") from e

        registered_count = 0
        for card_id, card in self.cards_data.items():
            task_type = card.task_type if hasattr(card, 'task_type') else card.get('task_type', '')

            if task_type == '附加条件':
                logger.info(f"[自动注册] 执行附加条件卡片 {card_id}")

                # 获取卡片参数
                # 【修复闪退】确保 card_params 不为 None，防止调用 .get() 时闪退
                if hasattr(card, 'parameters'):
                    card_params = card.parameters if card.parameters is not None else {}
                else:
                    card_params = card.get('parameters', {}) or {}

                logger.info(f"[自动注册] 卡片 {card_id} 参数: monitor_type={card_params.get('monitor_type')}, count_threshold={card_params.get('count_threshold')}, monitor_mode={card_params.get('monitor_mode')}")

                # 执行附加条件卡片
                task_module = get_task_module(task_type)
                if task_module is None or not hasattr(task_module, 'execute_card'):
                    raise RuntimeError(f"附加条件卡片 {card_id} 缺少执行模块")
                try:
                    result = task_module.execute_card(
                        card_id=card_id,
                        parameters=card_params,
                        context=self._workflow_context,
                        connections=self.connections_data
                    )
                except Exception as exc:
                    raise RuntimeError(
                        f"附加条件卡片 {card_id} 注册异常: {exc}"
                    ) from exc
                if not isinstance(result, (tuple, list)) or len(result) < 2:
                    raise RuntimeError(f"附加条件卡片 {card_id} 返回结果无效: {result!r}")
                success, message = result[:2]
                if not success:
                    raise RuntimeError(f"附加条件卡片 {card_id} 注册失败: {message}")
                registered_count += 1
                logger.info(f"[自动注册] 附加条件卡片 {card_id} 注册成功: {message}")

        if registered_count > 0:
            logger.info(f"[自动注册] 完成，共注册 {registered_count} 个附加条件")
        else:
            logger.info("[自动注册] 没有附加条件需要注册")
        return registered_count

    def _check_monitor_trigger(self, target_card_id: int, target_card_result: bool):
        """检查附加条件是否触发"""
        if target_card_id not in self._monitor_card_map:
            return None

        monitor_card_id = self._monitor_card_map[target_card_id]
        logger.info(f"[附加条件检查] 卡片 {target_card_id} 被附加条件 {monitor_card_id} 监控")

        # 获取上下文中的监控配置
        if not hasattr(self, '_workflow_context') or self._workflow_context is None:
            logger.warning("[附加条件检查] 工作流上下文不存在，跳过监控检查")
            return None

        # 【修复闪退】检查 _monitor_configs 属性是否存在且不为 None
        if not hasattr(self._workflow_context, '_monitor_configs') or self._workflow_context._monitor_configs is None:
            logger.warning("[附加条件检查] 没有监控配置属性或为空，跳过监控检查")
            return None

        logger.info(f"[附加条件检查] 所有监控配置: {self._workflow_context._monitor_configs.keys()}")

        monitor_config = self._workflow_context._monitor_configs.get(target_card_id)
        if monitor_config is None:
            logger.warning(f"[附加条件检查] 卡片 {target_card_id} 没有监控配置")
            logger.warning(f"[附加条件检查] 可用的配置键: {list(self._workflow_context._monitor_configs.keys())}")
            return None

        logger.info(f"[附加条件检查] 找到监控配置: {monitor_config}")

        # 调用监控检查函数
        try:
            from tasks.watchdog_monitor import check_monitor_trigger
            result = check_monitor_trigger(monitor_config, target_card_result, self._workflow_context)
            if result:
                logger.warning(f"[附加条件触发] 附加条件 {monitor_card_id} 触发: {result}")
            return result
        except ImportError as e:
            logger.error(f"[附加条件检查] 无法导入 watchdog_monitor 模块: {e}")
            return None
        except Exception as e:
            logger.error(f"[附加条件检查] 检查触发时发生错误: {e}", exc_info=True)
            return None

    def _build_step_log_details(self, card_id: int, card_params: Dict[str, Any], include_results: bool) -> str:
        """
        构建步骤日志详情，用于悬浮窗显示
        只显示核心信息：卡片ID
        """
        return f"卡片ID={card_id}"

    def _get_card_object(self, card_id: Any) -> Any:
        return find_card_by_id(self.cards_data, card_id)

    def _format_step_detail_for_card(
        self,
        prefix: str,
        card_id: Any,
        card_obj: Any = None,
        task_type: Any = None,
    ) -> str:
        if card_obj is None:
            card_obj = self._get_card_object(card_id)
        return format_step_detail(
            prefix,
            card=card_obj,
            card_id=card_id,
            task_type=task_type,
        )

    def _reset_current_card_issue_state(self) -> None:
        self._current_card_error_detail = ""
        self._current_card_error_detail_level = logging.NOTSET
        self._current_card_issue_logs = []

    def _begin_card_issue_capture(self) -> None:
        self._reset_current_card_issue_state()
        self._capture_card_issue_logs = True

    def _end_card_issue_capture(self) -> None:
        self._capture_card_issue_logs = False

    def _reset_failure_context(self) -> None:
        self._last_failure_card_id = None
        self._last_failure_task_type = ""
        self._last_failure_detail = ""
        self._reset_current_card_issue_state()

    def _remember_failure(self, card_id: Any, task_type: Any, detail: str = "") -> None:
        normalized_card_id = self._normalize_card_id_value(card_id)
        clean_task_type = str(task_type or "").strip()
        clean_detail = str(detail or "").strip()
        if not clean_detail:
            clean_detail = str(self._current_card_error_detail or "").strip()

        self._last_failure_card_id = normalized_card_id if normalized_card_id is not None else card_id
        self._last_failure_task_type = clean_task_type
        self._last_failure_detail = clean_detail

    def _compose_failure_message(self, summary: str) -> str:
        summary_text = str(summary or "工作流执行失败").strip() or "工作流执行失败"
        lines = [summary_text]

        if self._last_failure_card_id is not None or self._last_failure_task_type:
            if self._last_failure_card_id is not None:
                step_text = f"失败步骤: {self._last_failure_card_id}"
                if self._last_failure_task_type:
                    step_text += f"（{self._last_failure_task_type}）"
            else:
                step_text = f"失败步骤: {self._last_failure_task_type}"
            lines.append(step_text)

        detail_text = str(self._last_failure_detail or "").strip() or "该步骤返回失败，但没有提供更具体原因"
        lines.append(f"错误详情: {detail_text}")
        return "\n".join(lines)

    def _get_card_failure_detail(self, card_id: Any) -> str:
        current_detail = str(self._current_card_error_detail or "").strip()
        if current_detail:
            return current_detail

        normalized_card_id = self._normalize_card_id_value(card_id)
        remembered_card_id = self._normalize_card_id_value(self._last_failure_card_id)
        if (
            normalized_card_id is not None
            and remembered_card_id is not None
            and normalized_card_id == remembered_card_id
        ):
            return str(self._last_failure_detail or "").strip()
        return ""

    @staticmethod
    def _looks_generic_issue_message(message: str) -> bool:
        text = str(message or "").strip()
        if not text:
            return True

        generic_fragments = (
            "继续执行下一步",
            "继续执行本步骤",
            "跳转到步骤",
            "停止工作流",
            "执行失败",
            "点击失败",
            "识别失败",
        )
        for fragment in generic_fragments:
            if fragment in text and len(text) <= 24:
                return True
        return False

    _MATCH_SCORE_PATTERNS = (
        re.compile(r"分数:\s*([0-9.]+)\s*,\s*阈值:\s*([0-9.]+)"),
        re.compile(r"模板匹配分数\s*([0-9.]+)\s*[，,]\s*要求至少\s*([0-9.]+)"),
        re.compile(r"置信度\s*([0-9.]+)\s*[<＜>=≤≥]?\s*阈值\s*([0-9.]+)"),
    )

    @classmethod
    def _parse_match_score_pair(cls, message: str) -> Optional[Tuple[float, float]]:
        text = str(message or "").strip()
        if not text:
            return None
        for pattern in cls._MATCH_SCORE_PATTERNS:
            matched = pattern.search(text)
            if not matched:
                continue
            try:
                return float(matched.group(1)), float(matched.group(2))
            except (TypeError, ValueError):
                return None
        return None

    @classmethod
    def _is_passing_match_diagnostic(cls, message: str) -> bool:
        pair = cls._parse_match_score_pair(message)
        if pair is None:
            return False
        score, threshold = pair
        return score >= threshold

    @classmethod
    def _is_capturable_issue_log(cls, message: str, levelno: int) -> bool:
        text = str(message or "").strip()
        if not text:
            return False
        if text.startswith("跳转参数:"):
            return False
        ignored_fragments = (
            "Input size override ignored: static model input shape",
            "输入 size override ignored: static model 输入 shape",
        )
        if any(fragment in text for fragment in ignored_fragments):
            return False

        if cls._is_passing_match_diagnostic(text) and int(levelno) < logging.WARNING:
            return False

        if int(levelno) >= logging.WARNING:
            return True

        failure_keywords = (
            "失败",
            "错误",
            "异常",
            "未找到",
            "无效",
            "不匹配",
            "超时",
            "不存在",
            "不可用",
            "无结果",
            "已关闭",
            "已最小化",
            "无法",
        )
        diagnostic_keywords = (
            "置信度",
            "阈值",
            "分数",
            "得分",
            "score",
            "匹配度",
        )
        success_keywords = (
            "成功",
            "开始执行",
            "执行下一步",
            "跳转参数",
            "模板预加载完成",
            "工作流结束",
        )

        if any(keyword in text for keyword in success_keywords) and not any(keyword in text for keyword in failure_keywords):
            return False

        return (
            any(keyword in text for keyword in failure_keywords)
            or any(keyword in text for keyword in diagnostic_keywords)
        )

    @classmethod
    def _issue_message_score(cls, message: str, levelno: int) -> int:
        text = str(message or "").strip()
        score = int(levelno) * 1000
        score += min(len(text), 400)

        if not cls._looks_generic_issue_message(text):
            score += 200

        specificity_keywords = (
            "阈值",
            "置信度",
            "句柄",
            "窗口",
            "坐标",
            "模板",
            "匹配",
            "OCR",
            "图片",
            "元素",
            "数字",
            "文本",
            "客户区",
        )
        for keyword in specificity_keywords:
            if keyword in text:
                score += 30

        return score

    @staticmethod
    def _is_diagnostic_issue_message(message: str) -> bool:
        text = str(message or "").strip()
        diagnostic_keywords = (
            "置信度",
            "阈值",
            "分数",
            "得分",
            "score",
            "匹配度",
        )
        return any(keyword in text for keyword in diagnostic_keywords)

    @classmethod
    def _normalize_issue_message_for_display(cls, message: str) -> str:
        text = str(message or "").strip()
        if not text:
            return ""
        if cls._is_passing_match_diagnostic(text):
            return ""
        text = re.sub(r"^\[(?:前台一|前台二|前台|后台)[^\]]*\]\s*", "", text).strip()
        if "target window is not" in text.lower() and ("foreground" in text.lower() or "前台" in text):
            return "要点的窗口不在最前面，已取消点击"
        if text.startswith("Target not detected"):
            return "未检测到目标"
        if (
            text.startswith("跳转参数:")
            or text.startswith("[条件控制返回]")
            or "Return Debug" in text
        ):
            return ""

        if "执行失败操作" in text and "on_failure=" in text:
            if "条件不满足" in text:
                return "条件不满足"
            return ""

        template_match = re.search(r"分数:\s*([0-9.]+)\s*,\s*阈值:\s*([0-9.]+)", text)
        if text.startswith("[模板匹配]") and template_match:
            return f"模板匹配分数 {template_match.group(1)}，要求至少 {template_match.group(2)}"

        text = re.sub(r"[，,]\s*方法:\s*[\w.\-]+", "", text)
        text = re.sub(r"\s*方法:\s*[\w.\-]+", "", text)

        image_click_match = re.search(
            r"任务\s+'图片点击'\s+\(图片:\s+'([^']+)'\)\s+执行失败\s+\((.+?)\)。?$",
            text,
        )
        if image_click_match:
            image_name = image_click_match.group(1).strip()
            reason = image_click_match.group(2).strip()
            return f"图片点击失败：{image_name}，原因：{reason}"

        generic_task_match = re.search(
            r"任务\s+'([^']+)'\s+执行失败[:：]?\s*(.+?)$",
            text,
        )
        if generic_task_match:
            task_name = generic_task_match.group(1).strip()
            reason = generic_task_match.group(2).strip()
            if reason:
                return f"{task_name}失败：{reason}"
            return f"{task_name}失败"

        text = text.replace("[统一后台识别]", "图片识别")
        return text.strip()

    def _refresh_current_card_error_detail(self) -> None:
        issue_logs = list(getattr(self, "_current_card_issue_logs", []) or [])
        if not issue_logs:
            self._current_card_error_detail = ""
            self._current_card_error_detail_level = logging.NOTSET
            return

        failure_entries = [
            entry for entry in issue_logs
            if not self._is_diagnostic_issue_message(entry.get("message"))
        ]
        diagnostic_entries = [
            entry for entry in issue_logs
            if self._is_diagnostic_issue_message(entry.get("message"))
            and not self._is_passing_match_diagnostic(entry.get("message"))
        ]

        latest_match_entry = None
        other_diagnostic_entries = []
        for entry in diagnostic_entries:
            if self._parse_match_score_pair(entry.get("message")) is not None:
                latest_match_entry = entry
            else:
                other_diagnostic_entries.append(entry)
        diagnostic_entries = other_diagnostic_entries
        if latest_match_entry is not None:
            diagnostic_entries.append(latest_match_entry)

        if any(not self._looks_generic_issue_message(entry.get("message")) for entry in failure_entries):
            failure_entries = [
                entry for entry in failure_entries
                if not self._looks_generic_issue_message(entry.get("message"))
            ]

        selected_messages: List[str] = []

        def _append_entry(entry: Optional[Dict[str, Any]]) -> None:
            if not entry:
                return
            message = self._normalize_issue_message_for_display(entry.get("message"))
            if not message or message in selected_messages:
                return
            selected_messages.append(message)

        ranked_failures = sorted(
            enumerate(failure_entries),
            key=lambda item: (
                self._issue_message_score(item[1].get("message"), int(item[1].get("levelno", logging.INFO))),
                item[0],
            ),
            reverse=True,
        )
        ranked_diagnostics = sorted(
            enumerate(diagnostic_entries),
            key=lambda item: (
                self._issue_message_score(item[1].get("message"), int(item[1].get("levelno", logging.INFO))),
                item[0],
            ),
            reverse=True,
        )
        ranked_failures = [entry for _, entry in ranked_failures]
        ranked_diagnostics = [entry for _, entry in ranked_diagnostics]

        _append_entry(ranked_failures[0] if ranked_failures else None)
        _append_entry(ranked_diagnostics[0] if ranked_diagnostics else None)

        for entry in ranked_failures[1:]:
            _append_entry(entry)
            if len(selected_messages) >= 3:
                break

        for entry in ranked_diagnostics[1:]:
            _append_entry(entry)
            if len(selected_messages) >= 3:
                break

        if not selected_messages:
            fallback_candidates = [
                entry for entry in issue_logs
                if not self._is_passing_match_diagnostic(entry.get("message"))
            ] or list(issue_logs)
            fallback_entry = max(
                fallback_candidates,
                key=lambda entry: self._issue_message_score(entry.get("message"), int(entry.get("levelno", logging.INFO))),
            )
            _append_entry(fallback_entry)

        best_entry = max(
            issue_logs,
            key=lambda entry: self._issue_message_score(entry.get("message"), int(entry.get("levelno", logging.INFO))),
        )
        self._current_card_error_detail = "\n".join(selected_messages[:3])
        self._current_card_error_detail_level = int(best_entry.get("levelno", logging.INFO))

    def _on_captured_error_log(self, message: str, levelno: int = logging.ERROR) -> None:
        if not getattr(self, "_capture_card_issue_logs", False):
            return
        clean_message = str(message or "").strip()
        if not clean_message:
            return
        if clean_message.startswith("Traceback (most recent call last):"):
            return
        if not self._is_capturable_issue_log(clean_message, levelno):
            return

        issue_logs = getattr(self, "_current_card_issue_logs", None)
        if not isinstance(issue_logs, list):
            issue_logs = []
            self._current_card_issue_logs = issue_logs

        if any(str(entry.get("message") or "").strip() == clean_message for entry in issue_logs):
            return

        issue_logs.append({
            "message": clean_message,
            "levelno": int(levelno),
        })
        if len(issue_logs) > 8:
            del issue_logs[0:len(issue_logs) - 8]

        self._refresh_current_card_error_detail()

    def _attach_error_capture_handler(self) -> None:
        if self._error_capture_handler is not None:
            return
        try:
            handler = _ThreadErrorCaptureHandler(self, threading.get_ident())
            logging.getLogger().addHandler(handler)
            self._error_capture_handler = handler
        except Exception as exc:
            logger.debug("安装错误详情捕获器失败: %s", exc)

    def _detach_error_capture_handler(self) -> None:
        handler = self._error_capture_handler
        if handler is None:
            return
        try:
            logging.getLogger().removeHandler(handler)
            handler.close()
        except Exception:
            pass
        finally:
            self._error_capture_handler = None

    @staticmethod
    def _format_workflow_scope_label(workflow_scope: Any = "main", workflow_name: Optional[str] = None) -> str:
        """统一格式化主/子工作流标签，避免悬浮窗侧重复拼接。"""
        scope_key = str(workflow_scope or "main").strip().lower()
        if scope_key in {"sub", "sub_workflow", "child", "child_workflow"}:
            clean_name = str(workflow_name or "").strip()
            return f"子工作流:{clean_name}" if clean_name else "子工作流"
        return "主工作流"

    def emit_step_log(
        self,
        card_type: str,
        message: str,
        success: bool,
        workflow_scope: Any = None,
        workflow_name: Optional[str] = None,
    ) -> None:
        """发射带工作流作用域的步骤日志，供悬浮窗统一展示。"""
        if workflow_scope is None:
            workflow_scope = self._default_step_log_scope
        if workflow_name is None:
            workflow_name = self._default_step_log_name
        scope_label = self._format_workflow_scope_label(workflow_scope, workflow_name)
        clean_card_type = str(card_type or "").strip()

        if (
            clean_card_type.startswith("主工作流 / ")
            or clean_card_type.startswith("子工作流 / ")
            or clean_card_type.startswith("子工作流:")
        ):
            display_card_type = clean_card_type
        elif clean_card_type:
            display_card_type = f"{scope_label} / {clean_card_type}"
        else:
            display_card_type = scope_label

        self.step_log.emit(display_card_type, message, success)

    @classmethod
    def _is_ocr_task_type(cls, task_type: Any) -> bool:
        """判断任务类型是否为OCR任务。"""
        return str(task_type or "").strip() in cls._OCR_TASK_TYPES

    def _get_card_task_type(self, card_id: Any) -> str:
        """根据卡片ID获取任务类型。"""
        card_obj = self._get_card_object(card_id)
        if card_obj is None:
            return ""

        if hasattr(card_obj, "task_type"):
            return str(getattr(card_obj, "task_type") or "").strip()
        if isinstance(card_obj, dict):
            return str(card_obj.get("task_type", "") or "").strip()
        return ""

    @staticmethod
    def _is_same_card_id(left: Any, right: Any) -> bool:
        """判断两个卡片ID是否指向同一卡片（兼容 int/str）。"""
        if left == right:
            return True
        try:
            return int(left) == int(right)
        except (TypeError, ValueError):
            return str(left).strip() == str(right).strip()

    @staticmethod
    def _is_continue_action(action: Any) -> bool:
        """统一判断“继续本步骤”动作。"""
        try:
            from tasks.task_utils import normalize_step_action

            return normalize_step_action(action) == "继续执行本步骤"
        except Exception:
            action_text = str(action or "").strip()
            return action_text in ("继续执行本步骤", "继续本步骤")

    @staticmethod
    def _normalize_graph_card_id(card_id: Any) -> Optional[int]:
        if card_id is None or isinstance(card_id, bool):
            return None
        try:
            return int(card_id)
        except (TypeError, ValueError):
            text = str(card_id or "").strip()
            if not text:
                return None
            try:
                return int(float(text))
            except (TypeError, ValueError):
                return None

    @staticmethod
    def _normalize_step_action_text(action: Any) -> str:
        try:
            from tasks.task_utils import normalize_step_action

            return normalize_step_action(action)
        except Exception:
            action_text = str(action or "").strip()
            if action_text in ("继续执行本步骤", "继续本步骤"):
                return "继续执行本步骤"
            if action_text in ("跳转到步骤", "跳转到指定步骤"):
                return "跳转到步骤"
            if action_text in ("停止工作流", "结束工作流", "结束流程", "终止流程"):
                return "停止工作流"
            return "执行下一步"

    @classmethod
    def _normalize_jump_target_for_graph(cls, value: Any) -> Optional[int]:
        return cls._normalize_graph_card_id(value)

    def _get_card_params_for_graph(self, card_obj: Any) -> Dict[str, Any]:
        if isinstance(card_obj, dict):
            params = card_obj.get("parameters", {}) or {}
        else:
            params = getattr(card_obj, "parameters", {}) or {}
        return params if isinstance(params, dict) else {}

    def _get_card_type_for_graph(self, card_obj: Any) -> str:
        if isinstance(card_obj, dict):
            return str(card_obj.get("task_type", "") or "").strip()
        return str(getattr(card_obj, "task_type", "") or "").strip()

    def _build_card_id_lookup_for_graph(self) -> Dict[int, Any]:
        lookup: Dict[int, Any] = {}
        for raw_key, card_obj in (self.cards_data or {}).items():
            normalized_key = self._normalize_graph_card_id(raw_key)
            if normalized_key is not None:
                lookup.setdefault(normalized_key, card_obj)
            if isinstance(card_obj, dict):
                normalized_id = self._normalize_graph_card_id(card_obj.get("id", raw_key))
            else:
                normalized_id = self._normalize_graph_card_id(getattr(card_obj, "card_id", raw_key))
            if normalized_id is not None:
                lookup[normalized_id] = card_obj
        return lookup

    def _build_connection_map_for_graph(self) -> Dict[int, List[Dict[str, Any]]]:
        connection_map: Dict[int, List[Dict[str, Any]]] = {}
        for connection in self.connections_data or []:
            if not isinstance(connection, dict):
                continue
            start_id = self._normalize_graph_card_id(connection.get("start_card_id"))
            end_id = self._normalize_graph_card_id(connection.get("end_card_id"))
            if start_id is None or end_id is None:
                continue
            conn_type = str(connection.get("type") or "sequential").strip().lower() or "sequential"
            connection_map.setdefault(start_id, []).append(
                {
                    "start_card_id": start_id,
                    "end_card_id": end_id,
                    "type": conn_type,
                }
            )
        return connection_map

    def _resolve_next_edges_for_graph(
        self,
        card_id: int,
        success: bool,
        connection_map: Dict[int, List[Dict[str, Any]]],
        valid_card_ids: Set[int],
    ) -> Set[int]:
        connections = connection_map.get(card_id, [])
        targets: Set[int] = set()

        random_connections = [c for c in connections if c.get("type") == "random"]
        if random_connections:
            for connection in random_connections:
                end_id = self._normalize_graph_card_id(connection.get("end_card_id"))
                if end_id in valid_card_ids:
                    targets.add(end_id)
            return targets

        preferred_type = "success" if success else "failure"
        preferred_connections = [c for c in connections if c.get("type") == preferred_type]
        if preferred_connections:
            for connection in preferred_connections:
                end_id = self._normalize_graph_card_id(connection.get("end_card_id"))
                if end_id in valid_card_ids:
                    targets.add(end_id)
            return targets

        for connection in connections:
            if connection.get("type") != "sequential":
                continue
            end_id = self._normalize_graph_card_id(connection.get("end_card_id"))
            if end_id in valid_card_ids:
                targets.add(end_id)
        return targets

    def _resolve_action_edges_for_graph(
        self,
        card_id: int,
        card_params: Dict[str, Any],
        success: bool,
        connection_map: Dict[int, List[Dict[str, Any]]],
        valid_card_ids: Set[int],
    ) -> tuple[Set[int], bool]:
        action_key = "on_success" if success else "on_failure"
        target_key = "success_jump_target_id" if success else "failure_jump_target_id"
        action = self._normalize_step_action_text(card_params.get(action_key, "执行下一步"))

        if action == "停止工作流":
            return set(), True
        if action == "继续执行本步骤":
            return {card_id}, False
        if action == "跳转到步骤":
            target_id = self._normalize_jump_target_for_graph(card_params.get(target_key))
            if target_id in valid_card_ids:
                return {target_id}, False
            return set(), True

        next_targets = self._resolve_next_edges_for_graph(card_id, success, connection_map, valid_card_ids)
        return next_targets, not bool(next_targets)

    def _build_possible_flow_graph(self) -> tuple[Dict[int, Set[int]], Set[int]]:
        card_lookup = self._build_card_id_lookup_for_graph()
        valid_card_ids = set(card_lookup.keys())
        connection_map = self._build_connection_map_for_graph()
        graph: Dict[int, Set[int]] = {card_id: set() for card_id in valid_card_ids}
        terminal_possible: Set[int] = set()

        for card_id, card_obj in card_lookup.items():
            params = self._get_card_params_for_graph(card_obj)
            task_type = self._get_card_type_for_graph(card_obj)

            outcomes = [True]
            if not is_thread_start_task_type(task_type):
                outcomes.append(False)

            for success in outcomes:
                edges, can_end = self._resolve_action_edges_for_graph(
                    card_id,
                    params,
                    success,
                    connection_map,
                    valid_card_ids,
                )
                graph[card_id].update(edges)
                if can_end:
                    terminal_possible.add(card_id)

        return graph, terminal_possible

    def _detect_infinite_loop_logic(self, start_card_id: Any = None) -> Optional[Dict[str, Any]]:
        """检测从起点可达、没有任何可能出口的闭合循环。"""
        graph, terminal_possible = self._build_possible_flow_graph()
        start_id = self._normalize_graph_card_id(start_card_id if start_card_id is not None else self.start_card_id)
        return GraphEngine.detect_closed_cycle(graph, terminal_possible, start_id)

    def _emit_infinite_loop_warning(self, message: str) -> None:
        try:
            self.show_warning.emit("检测到无限循环", message)
        except Exception as exc:
            logger.debug(f"发出无限循环警告失败: {exc}")

    def _format_infinite_loop_message(self, loop_info: Dict[str, Any]) -> str:
        loop_cards = loop_info.get("cards") if isinstance(loop_info, dict) else []
        card_text = "、".join(str(card_id) for card_id in (loop_cards or [])) or "未知"
        return (
            "当前工作流存在没有出口的循环逻辑，继续执行会陷入无限循环。\n\n"
            f"涉及卡片: {card_text}\n\n"
            "请为该循环添加至少一个可跳出的成功/失败分支、停止工作流动作，或调整跳转目标后再运行。"
        )

    def _maybe_hot_reset_ocr_by_next_card(self, current_card_id: int, current_task_type: str, next_card_id: Any):
        """
        OCR热重置策略：
        - 当前卡片是OCR，且下一张不是OCR -> 立即热重置
        - 当前卡片是OCR，且下一张仍是OCR -> 不热重置
        """
        if not self._is_ocr_task_type(current_task_type):
            return

        # 继续本步骤/跳回本步骤不应触发热重置
        if self._is_same_card_id(current_card_id, next_card_id):
            logger.debug(
                f"[OCR热重置策略] 卡片 {current_card_id} 下一张仍是本步骤 ({next_card_id})，跳过热重置"
            )
            return

        next_task_type = self._get_card_task_type(next_card_id)
        if self._is_ocr_task_type(next_task_type):
            logger.debug(
                f"[OCR热重置策略] 卡片 {current_card_id} 下一张仍是OCR ({next_card_id})，跳过热重置"
            )
            return

        now = time.monotonic()
        with self._ocr_hot_reset_lock:
            if self._ocr_hot_reset_inflight:
                logger.debug(
                    f"[OCR热重置策略] 卡片 {current_card_id} 热重置任务仍在执行，跳过重复触发"
                )
                return
            if (now - self._ocr_hot_reset_last_ts) < self._ocr_hot_reset_min_interval_sec:
                logger.debug(
                    "[OCR热重置策略] 热重置触发过于频繁，已节流: %.3fs",
                    now - self._ocr_hot_reset_last_ts,
                )
                return
            self._ocr_hot_reset_inflight = True
            self._ocr_hot_reset_last_ts = now

        def _hot_reset_worker():
            try:
                from services.multiprocess_ocr_pool import get_multiprocess_ocr_pool
                pool = get_multiprocess_ocr_pool()
                ok = bool(pool.hot_reset_all_idle_workers(force=True))

                if ok:
                    logger.info(
                        f"[OCR热重置策略] 卡片 {current_card_id} -> 下一张 {next_card_id} ({next_task_type or '无'})，已热重置并清理空闲资源"
                    )
                else:
                    logger.debug(
                        f"[OCR热重置策略] 卡片 {current_card_id} -> 下一张 {next_card_id} ({next_task_type or '无'})，当前无可处理的空闲OCR进程"
                    )
            except Exception as e:
                logger.warning(f"[OCR热重置策略] 立即热重置失败: {e}")
            finally:
                with self._ocr_hot_reset_lock:
                    self._ocr_hot_reset_inflight = False

        try:
            threading.Thread(
                target=_hot_reset_worker,
                daemon=True,
                name=f"OCR-HotReset-{current_card_id}",
            ).start()
        except Exception as exc:
            with self._ocr_hot_reset_lock:
                self._ocr_hot_reset_inflight = False
            logger.warning(f"[OCR热重置策略] 启动热重置线程失败: {exc}")

    def _wait_for_start_gate(self):
        gate = getattr(self, "_start_gate_event", None)
        if gate is None:
            return
        try:
            while not gate.is_set():
                if self._stop_requested or self._force_stop:
                    break
                gate.wait(0.01)
        finally:
            self._start_gate_event = None

    def run(self):
        """主执行方法，在线程中运行"""
        if self._is_running:
            logger.warning("工作流已在运行中")
            return

        self._is_running = True
        self._stop_requested = False
        self._paused = False  # 重置暂停标志
        self._wait_for_start_gate()
        if self._stop_requested or self._force_stop:
            self._is_running = False
            self._last_execution_success = False
            self._last_execution_message = "工作流被用户停止"
            self.execution_finished.emit(False, "工作流被用户停止")
            return
        self._attach_error_capture_handler()
        previous_thread_context = None
        context_bound = False
        preflight_error = None
        try:
            from task_workflow.workflow_context import (
                get_current_workflow_context,
                set_current_workflow_context,
            )
            previous_thread_context = get_current_workflow_context()
            set_current_workflow_context(self._get_workflow_context())
            context_bound = True
        except Exception as bind_exc:
            preflight_error = f"绑定执行线程上下文失败: {bind_exc}"
            logger.error(preflight_error)

        # 每次执行前清理上次运行态，避免串数据影响本次流程。
        if self._clear_runtime_state_on_start and preflight_error is None:
            try:
                from task_workflow.workflow_context import clear_runtime_state_for_new_run

                clear_runtime_state_for_new_run(workflow_id=self.workflow_id)
            except Exception as clear_exc:
                preflight_error = f"执行前运行态清理失败: {clear_exc}"
                logger.error(preflight_error)

        # 线程起点资源路由键：用于截图/OCR资源按 lane 做粘性分配。
        try:
            from task_workflow.workflow_context import set_workflow_resource_lane

            lane_key = set_workflow_resource_lane(
                workflow_id=self.workflow_id,
                start_card_id=self.start_card_id,
                window_hwnd=self.target_hwnd,
            )
            if lane_key:
                logger.debug(
                    "[资源路由] lane=%s workflow=%s start=%s hwnd=%s",
                    lane_key,
                    self.workflow_id,
                    self.start_card_id,
                    self.target_hwnd,
                )
        except Exception as lane_exc:
            logger.debug("初始化资源路由键失败: %s", lane_exc)

        # 【性能优化】预加载模板图片到内存
        try:
            from utils.match.template_preloader import get_global_preloader
            preloader = get_global_preloader()
            workflow_data = {'cards': list(self.cards_data.values())}
            loaded_count = preloader.preload_workflow_templates(workflow_data)
            if loaded_count > 0:
                logger.info(f"[性能优化] 已预加载 {loaded_count} 个模板图片到内存")
        except Exception as e:
            logger.warning(f"[性能优化] 模板预加载失败: {e}")

        # 重置全局停止标志 - 已删除有问题的导入
        logger.debug("工作流执行器启动，跳过InputPlayer全局停止标志重置")

        # 工具 修复：不在WorkflowExecutor中设置环境变量，避免与多窗口执行器冲突
        # 环境变量应该由调用方（单窗口执行器或多窗口执行器）负责设置
        logger.info(f"WorkflowExecutor启动: 窗口='{self.target_window_title}', 模式={self.execution_mode}, HWND={self.target_hwnd}")

        if WIN32GUI_AVAILABLE and self.target_hwnd and not win32gui.IsWindow(self.target_hwnd):
            recovered_hwnd = self._try_recover_window_handle()
            if recovered_hwnd:
                logger.info(f"启动时重连目标窗口: {self.target_hwnd} => {recovered_hwnd}")
                self.target_hwnd = recovered_hwnd

        logger.info("开始执行工作流")
        # 在前台模式下激活目标窗口
        # [闪退修复] 标准化执行模式以支持新的模式
        # 【修复闪退】确保 execution_mode 不为 None，防止调用 .startswith() 时闪退
        exec_mode = self.execution_mode or 'foreground'
        normalized_mode = exec_mode
        if exec_mode.startswith('foreground'):
            normalized_mode = 'foreground'
        elif exec_mode.startswith('background'):
            normalized_mode = 'background'
        # 只在前台模式下激活窗口。
        if normalized_mode == 'foreground' and self.target_hwnd:
            self._activate_target_window()

        # 可选窗口适配策略：部分目标需要在后台输入前发送一次点击激活。
        background_activation = str(
            os.getenv("LCA_BACKGROUND_ACTIVATION", "") or ""
        ).strip().lower()
        if (
            normalized_mode == 'background'
            and self.target_hwnd
            and WIN32GUI_AVAILABLE
            and background_activation == "click"
        ):
            try:
                logger.info("[后台激活] WindowAdapter 请求点击激活")
                self._send_background_click_activation()
            except Exception as e:
                logger.warning(f"[后台激活] 点击激活失败: {e}")

        if preflight_error is None:
            try:
                # 【新架构】复用工作流上下文对象，用于存储附加条件配置
                self._workflow_context = self._prepare_execution_context()

                # 【关键】自动注册所有附加条件卡片
                if self._monitor_card_map:
                    self._auto_register_additional_conditions()

            except Exception as exc:
                preflight_error = f"执行前预检失败: {exc}"
                logger.error(preflight_error, exc_info=True)

        self.execution_started.emit()

        try:
            if preflight_error is not None:
                success, message = False, preflight_error
            else:
                success, message = self._execute_workflow()
            self._last_execution_success = bool(success)
            self._last_execution_message = str(message or "")
            self.execution_finished.emit(success, message)

        except Exception as e:
            logger.error(f"工作流执行过程中发生错误: {e}", exc_info=True)
            # 【修复闪退】安全发射信号，避免在对象销毁后发射
            try:
                self._last_execution_success = False
                self._last_execution_message = f"执行错误: {str(e)}"
                self.execution_finished.emit(False, f"执行错误: {str(e)}")
            except (RuntimeError, AttributeError) as signal_err:
                logger.debug(f"发射execution_finished信号失败（对象可能已销毁）: {signal_err}")
        finally:
            self._detach_error_capture_handler()

            # 工作流结束时释放所有按键
            self._release_all_keys()

            # 清理OCR上下文数据，防止影响下次执行
            try:
                from task_workflow.workflow_context import clear_all_ocr_data
                clear_all_ocr_data(workflow_id=self.workflow_id)
                logger.info("工作流结束，已清理所有OCR上下文数据")
            except Exception as e:
                logger.warning(f"清理OCR上下文数据时发生错误: {e}")

            # 统一清理图片相关缓存（覆盖异常/停止等路径）
            if self._cleanup_runtime_image_on_finish:
                try:
                    from utils.runtime_image_cleanup import cleanup_runtime_image_memory
                    cleanup_runtime_image_memory(
                        reason="workflow_run_finally",
                        cleanup_screenshot_engines=False,
                        cleanup_template_cache=False,
                    )
                except Exception as cleanup_err:
                    logger.warning(f"工作流收尾图片缓存清理失败: {cleanup_err}")

            # 环境变量由调用方负责清理
            if context_bound:
                try:
                    from task_workflow.workflow_context import set_current_workflow_context
                    set_current_workflow_context(previous_thread_context)
                except Exception as restore_exc:
                    logger.warning(f"恢复执行线程上下文失败: {restore_exc}")
            self._is_running = False

            # 工具 修复：主动请求线程退出
            logger.debug(f"WorkflowExecutor执行完成，请求线程退出: {self.target_window_title}")
            # 【修复闪退】安全地请求线程退出，避免访问已销毁的QThread对象
            try:
                current_thread = self.thread()
                if current_thread is not None and current_thread.isRunning():
                    current_thread.quit()
            except (RuntimeError, AttributeError) as e:
                logger.debug(f"请求线程退出时发生异常（可忽略）: {e}")

    def request_stop(self, force: bool = False):
        """请求停止执行

        Args:
            force: 是否强制停止（不等待当前任务完成）
        """
        logger.warning("======================================")
        logger.warning(f"=== request_stop() 被调用 (force={force}) ===")
        logger.warning(f"=== 当前 _stop_requested = {self._stop_requested} ===")
        logger.warning("======================================")

        self._stop_requested = True
        self.run_context.request_stop("force_stop" if force else "stop_requested")
        if force:
            self._force_stop = True
            logger.warning("=== 强制停止模式已启用 ===")

        logger.warning(f"=== 设置后 _stop_requested = {self._stop_requested} ===")

        # 停止请求时先清理YOLO运行态，避免残留。
        try:
            from utils.runtime_image_cleanup import cleanup_yolo_runtime_on_stop
            cleanup_yolo_runtime_on_stop(
                release_engine=True,
                compact_memory=True,
                cleanup_subprocess=True,
            )
        except Exception as e:
            logger.debug(f"清理YOLO运行态资源时出错: {e}")

        # 释放所有可能正在按下的按键
        self._release_all_keys()

        # 设置全局停止标志 - 已删除有问题的导入
        logger.debug("工作流执行器停止，跳过InputPlayer全局停止标志设置")

    def pause(self):
        """暂停执行"""
        logger.info("暂停工作流执行")
        self._paused = True

    def resume(self):
        """恢复执行"""
        logger.info("恢复工作流执行")
        self._paused = False

    def _is_pause_requested(self) -> bool:
        """统一读取本地/外部暂停状态，避免任务模块与执行器判断不一致。"""
        if self._paused:
            return True
        if self._external_pause_checker is not None:
            try:
                return bool(self._external_pause_checker())
            except Exception as exc:
                logger.debug(f"外部暂停检查失败: {exc}")
        return False

    def _task_runtime_stop_checker(self) -> bool:
        """供任务模块使用的控制检查：暂停时阻塞，停止时返回 True。"""
        return self._check_pause_and_stop()

    def _check_pause_and_stop(self):
        """检查暂停和停止请求，实现无延迟响应"""
        if self.run_context.is_stop_requested():
            self._stop_requested = True
            return True
        if self._external_stop_checker is not None:
            try:
                if self._external_stop_checker():
                    self._stop_requested = True
                    return True
            except Exception as exc:
                logger.debug(f"外部停止检查失败: {exc}")
        # 检查强制停止 - 立即返回
        if self._force_stop:
            logger.warning("[_check_pause_and_stop] 检测到强制停止请求，立即中断")
            return True

        # WGC完整销毁重建期间，阻塞任务执行，直到重建完成
        try:
            from utils.capture.wgc_hwnd_capture import (
                is_wgc_rebuilding,
                wait_wgc_rebuild_complete,
            )
            if is_wgc_rebuilding():
                while is_wgc_rebuilding():
                    if self._force_stop or self._stop_requested:
                        return True
                    wait_wgc_rebuild_complete(timeout=0.05)
        except Exception:
            pass

        # 检查暂停 - 快速响应
        pause_requested = self._is_pause_requested()
        while pause_requested and not self._stop_requested and not self._force_stop:
            if self._external_stop_checker is not None:
                try:
                    if self._external_stop_checker():
                        self._stop_requested = True
                        return True
                except Exception as exc:
                    logger.debug(f"外部停止检查失败: {exc}")
            time.sleep(0.01)
            pause_requested = self._is_pause_requested()

        # 检查停止
        if self._stop_requested:
            logger.debug(f"[_check_pause_and_stop] 检测到停止请求，_stop_requested={self._stop_requested}")
            return True  # 需要停止
        return False  # 继续执行

    def _release_all_keys(self):
        """释放所有可能正在按下的按键"""
        try:
            defer_global_input_release = False
            try:
                thread_session = getattr(self, "thread_session", None)
                if thread_session is not None and hasattr(thread_session, "should_defer_input_release"):
                    current_thread_id = getattr(self, "thread_id", None)
                    defer_global_input_release = bool(
                        thread_session.should_defer_input_release(thread_id=current_thread_id)
                    )
            except Exception as defer_check_error:
                logger.debug(f"检查输入释放延迟策略失败: {defer_check_error}")

            # 先统一释放前台输入驱动中记录的按键/鼠标按下状态
            if not defer_global_input_release:
                try:
                    from utils.input.foreground_input_manager import get_foreground_input_manager

                    fg_manager = get_foreground_input_manager()
                    if fg_manager is not None:
                        fg_manager.release_all_inputs()
                except Exception as fg_release_error:
                    logger.debug(f"前台输入驱动统一释放失败: {fg_release_error}")
            else:
                logger.debug("多线程会话仍有活跃线程，延迟本线程全局输入释放")

            # 释放找色任务可能按下的移动按键
            find_color_key = self._persistent_counters.get('__find_color_last_pressed_key__')
            if find_color_key:
                logger.info(f"工作流停止，释放找色任务按键: {find_color_key}")

                # 标准化执行模式
                # 【修复闪退】确保 execution_mode 不为 None，防止调用 .startswith() 时闪退
                exec_mode = self.execution_mode or 'foreground'
                normalized_mode = exec_mode
                if exec_mode.startswith('background'):
                    normalized_mode = 'background'
                elif exec_mode.startswith('foreground'):
                    normalized_mode = 'foreground'

                if normalized_mode == 'background' and self.target_hwnd:
                    # 后台模式释放按键
                    self._release_key_background(find_color_key)
                elif normalized_mode == 'foreground':
                    # 前台模式释放按键
                    # 【修复闪退】安全导入 pyautogui
                    try:
                        import pyautogui
                    except ImportError as e:
                        logger.warning(f"前台释放按键失败: pyautogui 不可用: {e}")
                        return

                    if "+" in find_color_key:
                        # 处理组合键
                        keys = find_color_key.split("+")
                        for key in keys:
                            key = key.strip()
                            try:
                                pyautogui.keyUp(key)
                                logger.debug(f"  释放组合键: {key}")
                            except Exception as e:
                                logger.warning(f"释放按键 {key} 失败: {e}")
                    else:
                        # 单个按键
                        try:
                            pyautogui.keyUp(find_color_key)
                            logger.debug(f"  释放按键: {find_color_key}")
                        except Exception as e:
                            logger.warning(f"释放按键 {find_color_key} 失败: {e}")

                # 清除按键状态
                self._persistent_counters['__find_color_last_pressed_key__'] = None
                logger.info("找色任务按键状态已清除")

            # 可以在这里添加其他任务的按键释放逻辑

        except Exception as e:
            logger.error(f"释放按键时发生错误: {e}")

    def _release_key_background(self, key_str: str):
        """后台模式释放按键"""
        # 【修复闪退】检查 key_str 是否为 None 或空字符串
        if not key_str:
            return

        try:
            # 【修复闪退】安全导入 win32api 和 win32con
            try:
                import win32api
                import win32con
            except ImportError as e:
                logger.warning(f"后台释放按键失败: win32api/win32con 不可用: {e}")
                return

            # 简单的按键映射
            key_map = {
                'w': 0x57, 's': 0x53, 'a': 0x41, 'd': 0x44,
                'up': win32con.VK_UP, 'down': win32con.VK_DOWN,
                'left': win32con.VK_LEFT, 'right': win32con.VK_RIGHT,
                'space': win32con.VK_SPACE, 'enter': win32con.VK_RETURN,
                'shift': win32con.VK_SHIFT, 'ctrl': win32con.VK_CONTROL,
                'alt': win32con.VK_MENU
            }

            if "+" in key_str:
                # 处理组合键
                keys = key_str.split("+")
                for key in keys:
                    key = key.strip().lower()
                    if key in key_map:
                        vk_code = key_map[key]
                        win32api.PostMessage(self.target_hwnd, win32con.WM_KEYUP, vk_code, 0)
                        logger.debug(f"  后台释放组合键: {key}")
            else:
                # 单个按键
                key = key_str.strip().lower()
                if key in key_map:
                    vk_code = key_map[key]
                    win32api.PostMessage(self.target_hwnd, win32con.WM_KEYUP, vk_code, 0)
                    logger.debug(f"  后台释放按键: {key}")

        except Exception as e:
            logger.warning(f"后台释放按键 {key_str} 失败: {e}")

    def _try_recover_window_handle(self) -> int:
        """
        尝试恢复失效的窗口句柄

        Returns:
            新的窗口句柄，恢复失败返回0
        """
        if not WIN32GUI_AVAILABLE:
            return 0

        window_title = self.target_window_title
        if not window_title and not self.target_hwnd:
            return 0

        try:
            resolved = self.window_adapter.resolve(
                WindowBinding(
                    title=str(window_title or ""),
                    hwnd=int(self.target_hwnd or 0),
                )
            )
            new_hwnd = resolved.hwnd
            if new_hwnd and win32gui.IsWindow(new_hwnd):
                logger.info(f"[Executor] 通过窗口特征恢复窗口: {window_title} -> {new_hwnd}")
                return new_hwnd

            logger.warning(f"[Executor] 未找到可确认的目标窗口，拒绝模糊恢复: {window_title}")
        except Exception as e:
            logger.error(f"[Executor] 恢复窗口句柄异常: {e}")

        return 0

    def _activate_target_window(self):
        """激活目标窗口（前台模式）"""
        try:
            if not WIN32GUI_AVAILABLE:
                logger.warning("win32gui 不可用，无法激活窗口")
                return False

            if not self.target_hwnd:
                logger.warning("前台模式但未提供目标窗口句柄，无法激活窗口")
                return False

            # 检查窗口是否有效
            if not win32gui.IsWindow(self.target_hwnd):
                logger.warning(f"目标窗口句柄无效: {self.target_hwnd}")
                return False
            if self.window_adapter.activate_foreground(self.target_hwnd):
                logger.info("WindowAdapter 已激活目标窗口: HWND=%s", self.target_hwnd)
                return True

            # 获取窗口标题用于日志
            try:
                window_title = win32gui.GetWindowText(self.target_hwnd)
            except Exception:
                window_title = f"HWND:{self.target_hwnd}"

            logger.info(f"前台模式：激活目标窗口 {window_title} (HWND: {self.target_hwnd})")

            # 检查窗口是否已经是前台窗口
            current_foreground = win32gui.GetForegroundWindow()
            if current_foreground == self.target_hwnd:
                logger.info(f"窗口已是前台窗口，无需激活: {window_title}")
                return True

            # 检查窗口是否最小化
            if win32gui.IsIconic(self.target_hwnd):
                logger.info(f"窗口已最小化，正在恢复: {window_title}")
                win32gui.ShowWindow(self.target_hwnd, 9)  # SW_RESTORE = 9
                time.sleep(0.2)  # 等待窗口恢复

            # 激活窗口
            win32gui.SetForegroundWindow(self.target_hwnd)
            time.sleep(0.1)  # 等待窗口激活

            # 验证激活是否成功
            new_foreground = win32gui.GetForegroundWindow()
            if new_foreground == self.target_hwnd:
                logger.info(f"窗口激活成功: {window_title}")
                return True
            else:
                logger.warning(f"窗口激活可能失败: 期望={self.target_hwnd}, 实际={new_foreground}")
                # 尝试备用方法
                try:
                    win32gui.BringWindowToTop(self.target_hwnd)
                    logger.info(f"使用备用方法将窗口置顶: {window_title}")
                    return True
                except Exception as e:
                    logger.error(f"备用激活方法失败: {e}")
                    return False

        except Exception as e:
            logger.error(f"激活目标窗口时出错: {e}")
            return False

    def _send_background_click_activation(self):
        """
        为需要点击预热的 WindowAdapter 发送后台激活。
        """
        try:
            if not WIN32GUI_AVAILABLE:
                logger.debug("win32gui 不可用，跳过后台点击激活")
                return False

            if not self.target_hwnd:
                logger.warning("未提供目标窗口句柄，无法发送激活")
                return False

            # 检查窗口是否有效
            if not win32gui.IsWindow(self.target_hwnd):
                logger.warning(f"目标窗口句柄无效: {self.target_hwnd}")
                return False

            logger.info(f"[后台激活] 发送点击激活消息 (HWND: {self.target_hwnd})")

            # 获取窗口中心坐标作为激活点击位置
            try:
                rect = win32gui.GetClientRect(self.target_hwnd)
                center_x = rect[2] // 2
                center_y = rect[3] // 2
            except Exception:
                # 如果获取失败，使用默认坐标
                center_x, center_y = 100, 100
                logger.debug(f"[后台激活] 无法获取窗口客户区，使用默认坐标: ({center_x}, {center_y})")

            # 使用增强激活器发送点击激活
            try:
                from utils.window.enhanced_window_activator import get_window_activator
                activator = get_window_activator(enable_logging=False)

                # 发送一次点击激活序列
                result = activator.activate_for_click(
                    parent_hwnd=self.target_hwnd,
                    child_hwnd=self.target_hwnd,
                    client_x=center_x,
                    client_y=center_y,
                    button='left'
                )

                if result:
                    logger.info("[后台激活] 窗口激活成功，已就绪接收后台输入")
                    time.sleep(0.05)  # 短暂等待激活生效
                    return True
                else:
                    logger.warning("[后台激活] 激活序列返回失败")
                    return False

            except Exception as e:
                logger.error(f"[后台激活] 发送激活序列时发生错误: {e}")
                return False

        except Exception as e:
            logger.error(f"[后台激活] 激活窗口时发生错误: {e}")
            return False

    def _execute_workflow(self) -> tuple[bool, str]:
        """执行工作流的核心逻辑"""
        try:
            self._reset_failure_context()

            if self.start_card_id is None:
                error_msg = "未指定起始卡片ID"
                logger.error(error_msg)
                return False, error_msg

            if self.start_card_id not in self.cards_data:
                error_msg = f"找不到起始卡片: {self.start_card_id}"
                logger.error(error_msg)
                return False, error_msg

            if self._infinite_loop_guard_enabled:
                loop_info = self._detect_infinite_loop_logic(self.start_card_id)
                if loop_info:
                    error_msg = self._format_infinite_loop_message(loop_info)
                    logger.error(error_msg)
                    self._emit_infinite_loop_warning(error_msg)
                    return False, error_msg

            # 开始执行工作流
            self.step_details.emit("开始执行工作流...")

            current_card_id = self.start_card_id
            execution_count = 0
            # 工具 用户要求：删除无限循环限制，允许任务真正无限执行
            retry_counts = {}  # 记录每个卡片的重试次数
            last_card_success = True  # 记录最后一个卡片的执行状态

            while current_card_id is not None:
                execution_count += 1
                if self._max_execution_steps is not None and execution_count > self._max_execution_steps:
                    error_msg = (
                        f"工作流执行步数超过限制: {self._max_execution_steps}\n\n"
                        "这通常表示当前逻辑进入了无法结束的循环，已自动停止工作流。"
                    )
                    logger.error(error_msg)
                    self._emit_infinite_loop_warning(error_msg)
                    return False, error_msg

                # 【重试标志重置】每轮循环开始时清除重试标志
                if self._is_retrying:
                    logger.debug("[重试标志] 新轮次开始，清除 _is_retrying")
                    self._is_retrying = False

                # 1. 循环开始立即检查暂停和停止
                if self._check_pause_and_stop():
                    logger.info("检测到停止请求，终止工作流执行")
                    self._release_all_keys()
                    try:
                        from task_workflow.workflow_context import clear_all_ocr_data, clear_multi_image_memory
                        clear_all_ocr_data(workflow_id=self.workflow_id)
                        clear_multi_image_memory(workflow_id=self.workflow_id)
                        logger.info("工作流停止，已清理上下文数据")
                    except Exception as e:
                        logger.warning(f"停止时清理上下文数据发生错误: {e}")

                    return True, "工作流被用户停止"

                # 2. 检查目标窗口是否仍然存在（防止窗口关闭后继续执行导致卡死）
                if self.target_hwnd and WIN32GUI_AVAILABLE:
                    try:
                        if not win32gui.IsWindow(self.target_hwnd):
                            logger.warning("目标窗口已关闭，自动停止工作流")
                            self._stop_requested = True
                            self._release_all_keys()
                            try:
                                from task_workflow.workflow_context import clear_all_ocr_data, clear_multi_image_memory
                                clear_all_ocr_data(workflow_id=self.workflow_id)
                                clear_multi_image_memory(workflow_id=self.workflow_id)
                            except Exception:
                                pass
                            return True, "目标窗口已关闭"
                    except Exception as e:
                        logger.warning(f"窗口状态检查异常: {e}")
                        # 检查失败时也停止，避免后续操作出错
                        self._stop_requested = True
                        return True, "窗口状态检查失败"

                # 检查卡片是否存在
                if current_card_id not in self.cards_data:
                    error_msg = f"找不到步骤 {current_card_id}"
                    logger.error(error_msg)
                    return False, error_msg
                if not self._is_allowed_card_id(current_card_id):
                    error_msg = f"工作流跳转到非法卡片: {current_card_id}"
                    logger.error(error_msg)
                    return False, error_msg

                # 获取当前卡片信息
                current_card = self.cards_data[current_card_id]
                # 检查是否是 TaskCard 对象还是字典
                if hasattr(current_card, 'task_type'):
                    # TaskCard 对象
                    task_type = current_card.task_type
                    # 【修复闪退】安全获取 parameters，防止为 None 时调用 .copy() 失败
                    params = current_card.parameters
                    card_params = dict(params) if isinstance(params, dict) else {}
                else:
                    # 字典格式
                    # 【修复闪退】确保 card_params 不为 None
                    task_type = current_card.get('task_type', '未知')
                    raw_parameters = current_card.get('parameters', {}) or {}
                    card_params = dict(raw_parameters) if isinstance(raw_parameters, dict) else {}

                if self._disallowed_task_types and str(task_type or "").strip() in self._disallowed_task_types:
                    error_msg = f"当前工作流禁止执行任务类型: {task_type}"
                    logger.error(error_msg)
                    return False, error_msg

                # 2. 卡片执行前再次检查
                if self._check_pause_and_stop():
                    logger.info("卡片执行前检测到停止请求")
                    self._release_all_keys()
                    return True, "工作流被用户停止"

                # 【性能优化】只在卡片ID变化时才发送executing信号
                # 如果是循环执行同一个卡片，不重复发送executing信号，避免UI频繁重绘
                if self._current_card_id != current_card_id:
                    # 发送卡片开始执行信号（仅当切换到不同卡片时）
                    self._current_card_id = current_card_id

                    self.card_executing.emit(current_card_id)
                    self.step_details.emit(
                        self._format_step_detail_for_card(
                            "正在执行",
                            current_card_id,
                            card_obj=current_card,
                            task_type=task_type,
                        )
                    )
                    # 发送浮动窗口日志 - 卡片开始执行
                    details = self._build_step_log_details(current_card_id, card_params, include_results=False)
                    log_message = "开始执行"
                    if details:
                        log_message = f"{log_message} | {details}"
                    self.emit_step_log(task_type, log_message, True)
                    logger.debug(f"执行卡片 {current_card_id}: {task_type}")
                    # 【UI响应优化】发送信号后让出CPU，让主线程处理UI事件
                    time.sleep(0)
                else:
                    # 循环执行同一卡片，不发送信号
                    logger.debug(f"卡片 {current_card_id} 循环执行中，跳过executing信号")


                # 执行卡片逻辑
                self._reset_current_card_issue_state()
                success, next_card_id, task_detail = self._execute_card(current_card_id, task_type, card_params)

                # 更新最后一个卡片的执行状态
                last_card_success = success

                # 【新架构】处理附加条件触发的跳转
                monitor_jump_triggered = False
                if isinstance(success, tuple) and success[0] == 'MONITOR_JUMP':
                    monitor_jump_triggered = True
                    actual_success = success[1]  # 提取原始的success值
                    success = actual_success  # 恢复原始success用于UI显示
                    last_card_success = success  # 更新最后卡片状态
                    logger.info(f"[附加条件跳转] 检测到附加条件触发，保持卡片原始状态: success={success}, 跳转到 {next_card_id}")

                # 3. 卡片执行完成后立即检查（关键！）
                if self._check_pause_and_stop():
                    logger.info("卡片执行后检测到停止请求")
                    self._release_all_keys()
                    return True, "工作流被用户停止"

                # 【关键修复】检查是否是停止工作流的特殊返回值
                if next_card_id == '工作流执行完成':
                    logger.info("任务返回停止工作流")
                    if not success:
                        return False, self._compose_failure_message(
                            f"工作流在步骤 {current_card_id} ({task_type}) 处失败并停止"
                        )
                    return success, '工作流执行完成'

                # 4. 处理结果前检查
                if self._check_pause_and_stop():
                    logger.info("处理结果时检测到停止请求")
                    self._release_all_keys()
                    return True, "工作流被用户停止"

                # 处理特殊返回值
                if next_card_id == 'STOP_WORKFLOW':
                    if not success:
                        return False, self._compose_failure_message(
                            f"工作流在步骤 {current_card_id} ({task_type}) 处失败并停止"
                        )
                    return True, "工作流执行完成"

                # 【测试卡片】单卡片测试模式：执行完当前卡片后立即返回，不执行任何跳转
                # 注意：跳过虚拟起点（ID为负数），只在真正的测试卡片执行完后才停止
                if self.test_mode == 'single_card' and current_card_id >= 0:
                    logger.info(f"[测试卡片] 卡片 {current_card_id} 执行完成，测试结束")
                    self.card_finished.emit(current_card_id, success)
                    # 【修复】等待一小段时间确保主线程能处理card_finished信号并更新UI
                    time.sleep(0.05)  # 等待50ms让UI完成状态更新
                    logger.info("[测试卡片] card_finished信号已发送并等待UI更新")
                    return success, f"[测试卡片] 执行{'成功' if success else '失败'}"

                # 【新架构】如果是附加条件触发的跳转，立即跳转，不走后续处理逻辑（包括UI信号）
                if monitor_jump_triggered:
                    logger.info(f"[附加条件快速跳转] 直接跳转到 {next_card_id}，跳过UI信号发送")
                    # 只发送被监控卡片的完成信号（显示原始状态），不发送step_details
                    self.card_finished.emit(current_card_id, success)
                    self._maybe_hot_reset_ocr_by_next_card(current_card_id, task_type, next_card_id)
                    current_card_id = next_card_id
                    retry_counts[current_card_id] = 0  # 重置目标卡片的重试计数
                    continue

                # 【性能优化】只在卡片真正完成（跳转到其他卡片）时才发送完成信号
                # 如果是跳转回自己（循环执行），不发送完成信号，避免频繁的状态切换导致UI卡顿
                # 【修复】不管success是True还是False，只要next_card_id等于当前卡片，就是循环执行
                will_loop_to_self = self._is_same_card_id(next_card_id, current_card_id)
                will_loop_by_connection = False
                if not will_loop_to_self and next_card_id is None:
                    connections = self._connections_map.get(current_card_id, [])
                    # random 连接会在查找下一卡片时随机决策，这里不提前推断，避免改变原有行为
                    if not any(c.get('type') == 'random' for c in connections):
                        preferred_types = ['success', 'sequential'] if success else ['failure', 'sequential']
                        for connection_type in preferred_types:
                            matched_connection = next(
                                (c for c in connections if c.get('type') == connection_type),
                                None,
                            )
                            if matched_connection is not None:
                                candidate_next = matched_connection.get('end_card_id')
                                will_loop_by_connection = self._is_same_card_id(candidate_next, current_card_id)
                                break

                if not (will_loop_to_self or will_loop_by_connection):
                    # 发送卡片完成信号（仅当不是循环到自己时）
                    self.card_finished.emit(current_card_id, success)

                    if success:
                        self.step_details.emit(
                            self._format_step_detail_for_card(
                                "执行成功",
                                current_card_id,
                                card_obj=current_card,
                                task_type=task_type,
                            )
                        )
                        # 发送浮动窗口日志
                        details = self._build_step_log_details(current_card_id, card_params, include_results=True)
                        log_message = "执行成功"
                        if details:
                            log_message = f"{log_message} | {details}"
                        self.emit_step_log(task_type, log_message, True)
                    else:
                        self.step_details.emit(
                            self._format_step_detail_for_card(
                                "执行失败",
                                current_card_id,
                                card_obj=current_card,
                                task_type=task_type,
                            )
                        )
                        # 发送浮动窗口日志
                        details = self._build_step_log_details(current_card_id, card_params, include_results=True)
                        log_message = "执行失败"
                        if details:
                            log_message = f"{log_message} | {details}"
                        self.emit_step_log(task_type, log_message, False)

                    # 【UI响应优化】发送信号后等待一小段时间，确保UI能处理完成信号
                    # 特别是对于起点等快速执行的卡片，需要确保UI有足够时间从蓝色切换到绿色
                    time.sleep(0.01)
                else:
                    # 循环到自己时，只记录日志，不发送UI信号
                    logger.debug(f"卡片 {current_card_id} 循环执行中，跳过完成信号")

                # 处理失败时的操作
                # 【修复】如果已经确定要循环回自己，跳过失败处理逻辑
                if not success and not will_loop_to_self:
                    # 【修复闪退】安全获取失败时的操作设置，防止 card_params 为 None
                    failure_action = '执行下一步'
                    if card_params is not None:
                        failure_action = card_params.get('on_failure', '执行下一步')

                    if failure_action == '停止工作流':
                        logger.info(f"{task_type} 执行失败，停止工作流")
                        return False, self._compose_failure_message(
                            f"工作流在步骤 {current_card_id} ({task_type}) 处失败并停止"
                        )
                    elif failure_action == '跳转到步骤':
                        # 【修复闪退】安全获取跳转目标，防止 card_params 为 None
                        jump_target = None
                        if card_params is not None:
                            jump_target = card_params.get('failure_jump_target_id')
                        if jump_target is not None and jump_target != "" and next_card_id is None:
                            logger.info(f"{task_type} 执行失败，跳转到步骤 {jump_target}")
                            next_card_id = jump_target
                    elif self._is_continue_action(failure_action):
                        # 【防止并发重试】检查是否已有重试在进行中
                        if self._is_retrying:
                            self._maybe_hot_reset_ocr_by_next_card(current_card_id, task_type, current_card_id)
                            logger.warning("检测到重复的'继续执行本步骤'信号，上一轮次尚未完成，跳过本次")
                            # 【关键修复】使用continue跳过本次，而不是break退出循环
                            # 这样可以继续等待下一轮，而不是直接终止工作流
                            continue

                        # 【关键检查】在决定继续执行前,必须先确认没有停止信号
                        if self._check_pause_and_stop():
                            logger.info("'继续执行本步骤'判断时检测到停止请求,立即终止")
                            self._release_all_keys()
                            return False, '工作流被用户停止'

                        # 【标记重试开始】
                        self._is_retrying = True
                        logger.debug("[重试标志] 设置 _is_retrying = True")

                        # 双重重试机制：
                        # 1. 任务内部重试（如图片查找3次）
                        # 2. 工作流级别重试（重新执行整个步骤）

                        current_retry_count = retry_counts.get(current_card_id, 0)
                        retry_counts[current_card_id] = current_retry_count + 1

                        # 【修复闪退】安全获取重试间隔设置，防止 card_params 为 None
                        workflow_retry_interval = 0.1  # 默认100ms
                        if card_params is not None:
                            workflow_retry_interval = card_params.get('workflow_retry_interval',
                                                                   card_params.get('retry_interval', 0.1))

                        # 确保转换为浮点数
                        try:
                            workflow_retry_interval = float(workflow_retry_interval)
                        except (ValueError, TypeError):
                            workflow_retry_interval = 0.1  # 默认100ms

                        logger.info(f"{task_type} 任务内部重试已完成，开始工作流级重试 (第 {retry_counts[current_card_id]} 次)")

                        # 添加工作流重试间隔，并在等待期间检查停止和暂停请求
                        if workflow_retry_interval > 0:
                            logger.debug(f"工作流重试间隔: {workflow_retry_interval} 秒...")

                            # 在等待期间以更高频率检查停止和暂停请求
                            sleep_time = 0
                            while sleep_time < workflow_retry_interval:
                                if self._check_pause_and_stop():
                                    logger.info("重试等待期间检测到停止请求")
                                    self._release_all_keys()
                                    self._is_retrying = False  # 【清除重试标志】
                                    logger.debug("[重试标志] 停止时清除 _is_retrying = False")
                                    return False, '工作流被用户停止'
                                time.sleep(0.01)  # 从0.1秒改为0.01秒，更快响应
                                sleep_time += 0.01
                        else:
                            # 【智能自适应延迟】根据上次OCR耗时动态调整延迟
                            # 目标：保持总周期不低于150ms，降低WGC截图频率，避免鼠标闪烁
                            target_cycle_ms = 150  # 目标周期150ms
                            # 【修复闪退】使用 _persistent_counters 而不是不存在的 _counters
                            last_ocr_time_ms = self._persistent_counters.get('__last_ocr_time_ms__', 100)  # 默认100ms

                            # 计算需要的延迟时间
                            required_delay_ms = max(0, target_cycle_ms - last_ocr_time_ms)
                            required_delay_sec = required_delay_ms / 1000.0

                            if required_delay_sec > 0:
                                logger.debug(f"智能延迟: OCR耗时{last_ocr_time_ms:.0f}ms，补充延迟{required_delay_ms:.0f}ms以达到{target_cycle_ms}ms周期")
                                time.sleep(required_delay_sec)
                            else:
                                logger.debug(f"智能延迟: OCR耗时{last_ocr_time_ms:.0f}ms已超过目标周期，无需延迟")

                            if self._check_pause_and_stop():
                                logger.info("智能延迟后检测到停止请求")
                                self._release_all_keys()
                                self._is_retrying = False
                                logger.debug("[重试标志] 停止时清除 _is_retrying = False")
                                return False, '工作流被用户停止'

                        # 【关键】在重新执行当前步骤前，最后一次检查停止信号
                        if self._check_pause_and_stop():
                            logger.info("'继续执行本步骤'循环开始前检测到停止请求")
                            self._release_all_keys()
                            self._is_retrying = False  # 【清除重试标志】
                            logger.debug("[重试标志] 停止时清除 _is_retrying = False")
                            return False, '工作流被用户停止'

                        # 【注意】不在这里清除标志，而是在循环开头清除
                        # 这样可以防止在continue后立即再次进入重试逻辑

                        # 重新执行当前步骤（允许无限重试）
                        self._maybe_hot_reset_ocr_by_next_card(current_card_id, task_type, current_card_id)
                        continue
                else:
                    # 执行成功，重置重试计数器
                    if current_card_id in retry_counts:
                        del retry_counts[current_card_id]

                # 5. 查找下一个卡片前检查
                if self._check_pause_and_stop():
                    logger.info("查找下一卡片时检测到停止请求")
                    self._release_all_keys()
                    return True, "工作流被用户停止"

                # 如果没有指定下一个卡片，根据连接查找
                if next_card_id is None:
                    next_card_id = self._find_next_card(
                        current_card_id,
                        success,
                    )

                if next_card_id is not None and not self._is_allowed_card_id(next_card_id):
                    error_msg = f"工作流跳转到非法卡片: {next_card_id}"
                    logger.error(error_msg)
                    return False, error_msg

                # OCR热重置策略：根据“最终下一张卡片类型”决定是否立即热重置
                self._maybe_hot_reset_ocr_by_next_card(current_card_id, task_type, next_card_id)

                # 【修复】如果跳转回本卡片（不管是成功还是失败），直接continue循环执行
                # 这包括：条件控制的"继续执行本步骤"、移动检测等需要循环检测的场景
                if self._is_same_card_id(next_card_id, current_card_id):
                    logger.debug(f"检测到跳转回本卡片 {current_card_id}，继续循环执行 (success={success})")

                    if self._check_pause_and_stop():
                        logger.info("跳转回本卡片时检测到停止请求")
                        self._release_all_keys()
                        return True, "工作流被用户停止"

                    # 保持 current_card_id 不变，直接继续循环
                    continue

                # 6. 切换到下一个卡片前检查（关键！卡片间隙立即响应）
                if self._check_pause_and_stop():
                    logger.info("切换卡片时检测到停止请求")
                    self._release_all_keys()
                    return True, "工作流被用户停止"

                current_card_id = next_card_id

                # 启动 优化：移除步骤间延迟，提高执行速度
                # 原来的延迟会累积影响整个工作流的执行效率

                # 【UI响应优化】让出CPU时间片，防止快速循环时UI卡顿
                # time.sleep(0) 会触发操作系统线程调度，让主线程有机会处理UI事件
                # 这不会显著影响执行速度，但能防止信号队列堆积导致的UI无响应
                time.sleep(0)

            # 工具 用户要求：删除无限循环限制检查，允许任务真正无限执行
            # if execution_count >= max_executions:
            #     error_msg = "工作流执行次数超过限制，可能存在无限循环"
            #     logger.error(error_msg)
            #     return False, error_msg

            # 工作流自然结束，执行清理
            logger.info("[工作流完成] 自然结束，执行资源清理")

            # 2. 清理图片相关缓存
            if self._cleanup_runtime_image_on_finish:
                try:
                    from utils.runtime_image_cleanup import cleanup_runtime_image_memory
                    cleanup_runtime_image_memory(
                        reason="workflow_natural_finish",
                        cleanup_screenshot_engines=False,
                        cleanup_template_cache=False,
                    )
                    logger.info("[工作流完成] 已执行图片缓存清理")
                except Exception as e:
                    logger.warning(f"[工作流完成] 图片缓存清理失败: {e}")

            # 工作流自然结束，返回最后一个卡片的执行状态
            if last_card_success:
                return True, "工作流执行完成"
            else:
                return False, self._compose_failure_message("工作流执行完成（最后一个步骤失败）")

        except Exception as e:
            self._remember_failure(
                self._current_card_id,
                self._get_card_task_type(self._current_card_id),
                str(e),
            )
            error_msg = f"工作流执行失败: {str(e)}"
            logger.error(error_msg, exc_info=True)
            # 【修复闪退】安全发射错误信号，避免在对象销毁后发射
            try:
                if self._current_card_id is not None:
                    self.error_occurred.emit(self._current_card_id, str(e))
            except (RuntimeError, AttributeError) as signal_err:
                logger.debug(f"发射错误信号失败（对象可能已销毁）: {signal_err}")
            return False, self._compose_failure_message("工作流执行失败")

    def _execute_card(self, card_id: int, task_type: str, card_params: Dict[str, Any]) -> tuple[Any, Any, str]:
        """执行单个卡片的逻辑"""
        try:
            def _finalize_failure(action: str = '执行下一步', next_id=None, detail: str = "", remember_failure: bool = True):
                if remember_failure:
                    self._remember_failure(card_id, task_type, detail)
                return False, next_id, str(detail or "").strip()

            # 获取对应的任务模块 - 使用实例变量而不是全局导入
            task_module = self.task_modules.get(task_type)
            if not task_module:
                detail = f"找不到任务类型 '{task_type}' 对应的模块"
                logger.error(detail)
                return _finalize_failure(detail=detail)

            # 准备执行环境参数
            # 工具 修复：使用持久计数器字典而不是每次创建新的
            counters = self._persistent_counters  # 使用持久计数器
            execution_mode = self.execution_mode  # 执行模式
            window_region = None  # 窗口区域

            # 工具 关键修复：优先使用构造函数传入的target_hwnd，避免重新查找导致窗口混乱
            target_hwnd = self.target_hwnd

            # 验证预设的窗口句柄是否有效，失效时尝试自动恢复
            if target_hwnd:
                try:
                    if not WIN32GUI_AVAILABLE:
                        logger.warning("win32gui 不可用，无法验证窗口句柄")
                        # 继续执行，因为任务模块可能不需要 win32gui
                    else:
                        # 检查窗口有效性（带超时保护）
                        window_valid = False
                        try:
                            # 快速检查窗口是否存在且可见
                            window_valid = win32gui.IsWindow(target_hwnd)
                        except Exception as check_error:
                            logger.warning(f"窗口有效性检查失败: {check_error}")
                            window_valid = False

                        if window_valid:
                            # 窗口存在，尝试获取标题（可能失败）
                            try:
                                actual_title = win32gui.GetWindowText(target_hwnd)
                                logger.debug(f"成功 使用预设窗口句柄: {target_hwnd} -> '{actual_title}'")
                            except Exception:
                                # 获取标题失败但窗口存在，继续执行
                                logger.debug(f"成功 使用预设窗口句柄: {target_hwnd} (无法获取标题)")
                        else:
                            logger.warning(f"目标窗口已关闭 (HWND: {target_hwnd})，尝试按窗口特征重连")
                            recovered_hwnd = self._try_recover_window_handle()
                            if recovered_hwnd and win32gui.IsWindow(recovered_hwnd):
                                self.target_hwnd = recovered_hwnd
                                target_hwnd = recovered_hwnd
                                logger.info(f"目标窗口句柄已重连: {recovered_hwnd}")
                            else:
                                detail = "目标窗口不存在或已关闭"
                                logger.error(f"工作流已自动停止：{detail}")
                                self._stop_requested = True
                                return _finalize_failure(detail=detail)
                except Exception as e:
                    logger.error(f"错误 验证预设窗口句柄时出错: {e}")
                    # 发生异常时也停止工作流，避免继续执行导致卡死
                    self._stop_requested = True
                    return _finalize_failure(detail=str(e))

            # 如果没有有效的预设句柄，返回失败
            if not target_hwnd:
                detail = "没有有效的窗口句柄，请先绑定窗口"
                logger.error(f"错误 {detail}")
                return _finalize_failure(detail=detail)

            # 记录最终使用的窗口句柄
            if target_hwnd:
                source = "预设" if self.target_hwnd else "查找"
                logger.debug(f"靶心 最终使用窗口句柄: {target_hwnd} (来源: {source})")
            else:
                logger.error("错误 没有有效的窗口句柄，任务可能失败")

            def _invoke_task_module():
                # 工具 修复：简化任务执行逻辑，不再区分多窗口模式
                # 多窗口模式应该由环境变量MULTI_WINDOW_MODE来标识，而不是在这里判断
                if hasattr(task_module, 'execute_task'):
                    # 统一使用标准方法执行任务
                    logger.debug(f"执行任务 '{task_type}': 窗口='{self.target_window_title}' (HWND: {target_hwnd}), 模式={execution_mode}")
                    try:
                        resolved_params = self._resolve_runtime_params(card_id, card_params)
                    except Exception as resolve_error:
                        detail = str(resolve_error or "参数引用无法解析")
                        logger.error("卡片 %s 参数插值失败: %s", card_id, detail)
                        return False, '执行下一步', None, detail
                    with thread_control_context(self._task_runtime_stop_checker):
                        result = task_module.execute_task(
                            params=resolved_params,
                            counters=counters,
                            execution_mode=execution_mode,
                            target_hwnd=target_hwnd,
                            window_region=window_region,
                            card_id=card_id,
                            get_image_data=self.get_image_data,
                            stop_checker=self._task_runtime_stop_checker,
                            pause_checker=self._is_pause_requested,
                            executor=self  # 传递executor自身，用于发射信号
                        )

                    # 工具 修复：检查返回值是否为None，防止解包错误
                    if result is None:
                        detail = f"任务 '{task_type}' 未返回执行结果"
                        logger.error(detail)
                        return False, '执行下一步', None, detail
                    return result

                detail = f"任务 '{task_type}' 缺少 execute_task 实现"
                logger.error(detail)
                return False, '执行下一步', None, detail

            task_result = None
            requires_input_lock = task_requires_input_lock(
                task_type=task_type,
                params=card_params,
                task_module=task_module,
            )
            if requires_input_lock:
                lock_resource = resolve_input_lock_resource(
                    execution_mode=execution_mode,
                    target_hwnd=target_hwnd,
                    task_type=task_type,
                )
                lock_owner = f"card={card_id}, task={task_type}, thread={threading.get_ident()}, resource={lock_resource}"
                # 缩短单次等待切片，避免停止时被输入锁长时间阻塞。
                wait_slice = max(0.05, min(0.2, get_input_lock_timeout_seconds()))
                total_wait_ms = 0.0
                while True:
                    if self._check_pause_and_stop():
                        return _finalize_failure("停止工作流", None, remember_failure=False)

                    with acquire_input_guard(owner=lock_owner, timeout=wait_slice, resource=lock_resource) as (acquired, wait_ms):
                        total_wait_ms += max(0.0, float(wait_ms))
                        if acquired:
                            wait_warn_ms = get_input_lock_wait_warn_ms()
                            if total_wait_ms >= wait_warn_ms:
                                logger.warning("[输入调度] 等待输入锁 %.1fms (告警阈值 %.1fms): %s", total_wait_ms, wait_warn_ms, lock_owner)
                            elif total_wait_ms > 20:
                                logger.debug("[输入调度] 等待输入锁 %.1fms: %s", total_wait_ms, lock_owner)
                            self._begin_card_issue_capture()
                            try:
                                task_result = _invoke_task_module()
                            finally:
                                self._end_card_issue_capture()
                            break
            else:
                self._begin_card_issue_capture()
                try:
                    task_result = _invoke_task_module()
                finally:
                    self._end_card_issue_capture()

            if task_result is None:
                return _finalize_failure(detail="任务执行没有返回结果")
            try:
                normalized_result = normalize_task_result(task_result)
            except (TypeError, ValueError) as result_error:
                detail = f"任务 '{task_type}' 返回结果格式无效: {result_error}"
                logger.error(detail)
                return _finalize_failure(detail=detail)
            success, action, next_card_id, task_detail = normalized_result.as_legacy_tuple()

            if not success and not str(task_detail or "").strip():
                task_detail = str(self._current_card_error_detail or "").strip()

            if not success:
                self._remember_failure(card_id, task_type, task_detail)

            # 【新架构】在处理action之前，先检查附加条件
            # 这样无论卡片返回什么action，附加条件都能立即触发
            if card_id in self._monitor_card_map:
                monitor_triggered = self._check_monitor_trigger(card_id, success)
                # 【修复闪退】确保 monitor_triggered 是字典类型，防止调用 .get() 时闪退
                if monitor_triggered and isinstance(monitor_triggered, dict):
                    # 附加条件触发，覆盖卡片的原始action
                    trigger_action = monitor_triggered.get('action')
                    monitor_card_id = self._monitor_card_map[card_id]

                    if trigger_action == 'stop':
                        logger.warning(f"[附加条件触发] 停止工作流: {monitor_triggered.get('reason')}")
                        # 发送附加条件卡片的成功信号
                        self.card_finished.emit(monitor_card_id, True)
                        return True, '工作流执行完成', str(task_detail or "").strip()
                    elif trigger_action == 'jump':
                        jump_target = monitor_triggered.get('target_card_id')
                        logger.warning(f"[附加条件触发] 跳转到卡片 {jump_target}: {monitor_triggered.get('reason')}")
                        # 发送附加条件卡片的成功信号
                        self.card_finished.emit(monitor_card_id, True)
                        # 返回特殊值表示附加条件触发的跳转
                        return ('MONITOR_JUMP', success), jump_target, str(task_detail or "").strip()

            # 延迟规则：继续本步骤始终延迟；跳转/下一步只有有连线才延迟
            try:
                from tasks.task_utils import handle_next_step_delay
                should_delay = False
                if self._is_continue_action(action):
                    should_delay = True
                elif action == '跳转到步骤':
                    should_delay = next_card_id is not None
                elif action != '停止工作流':
                    if next_card_id is not None:
                        should_delay = True
                    else:
                        should_delay = self._has_next_connection(
                            card_id,
                            success,
                        )
                if should_delay:
                    handle_next_step_delay(card_params, stop_checker=self._task_runtime_stop_checker)
            except Exception as exc:
                logger.debug("延迟处理失败: %s", exc)

            # 处理返回的动作（如果附加条件没有触发）
            if action == '停止工作流':
                # 【修复】在停止工作流前，发送卡片完成信号以更新UI状态
                self.card_finished.emit(card_id, success)
                if success:
                    self.step_details.emit(
                        f"{self._format_step_detail_for_card('执行成功', card_id, task_type=task_type)}，停止工作流"
                    )
                else:
                    self.step_details.emit(
                        f"{self._format_step_detail_for_card('执行失败', card_id, task_type=task_type)}，停止工作流"
                    )
                return success, '工作流执行完成', str(task_detail or "").strip()
            elif action == '跳转到步骤' and next_card_id is not None:
                return success, next_card_id, str(task_detail or "").strip()
            elif self._is_continue_action(action):
                return success, card_id, str(task_detail or "").strip()
            else:
                # 默认执行下一步，返回 None 让连接查找逻辑处理
                return success, None, str(task_detail or "").strip()

        except Exception as e:
            logger.error(f"执行卡片 {card_id} ({task_type}) 时发生错误: {e}", exc_info=True)
            # 【修复闪退】安全发射错误信号，避免在对象销毁后发射
            try:
                self.error_occurred.emit(card_id, str(e))
            except (RuntimeError, AttributeError) as signal_err:
                logger.debug(f"发射卡片错误信号失败（对象可能已销毁）: {signal_err}")
            return _finalize_failure(detail=str(e))

        finally:
            # 【内存泄漏修复】不要每个卡片都清理WGC！
            # WGC捕获器应该保持运行并复用，只在停止任务时清理
            # 频繁清理和重建会导致：
            # 1. 性能下降（每次都要重新创建后台线程和D3D设备）
            # 2. 内存碎片（频繁分配和释放大块内存）
            # 3. 资源泄漏（清理不完全）
            #
            # WGC捕获器有LRU机制，会自动管理内存（最多10个）
            # 真正的清理在 main.py:confirm_stopped() 中执行
            pass



    def _find_next_card(
        self,
        current_card_id: int,
        success: bool,
    ) -> int:
        """根据连接查找下一个卡片"""
        connections = list(self._graph_engine.connections_from(current_card_id))

        # 调试：记录查找过程（改为debug级别，避免快速循环时阻塞）
        logger.debug(f"查找卡片 {current_card_id} 的下一个卡片 (success={success})")
        logger.debug(f"  当前卡片的连接数: {len(connections)}")
        if connections:
            for conn in connections:
                logger.debug(f"    -> 连接: {conn.get('start_card_id')} -> {conn.get('end_card_id')} (类型: {conn.get('type')})")
        else:
            logger.debug(f"  卡片 {current_card_id} 没有任何出向连接！")
            # 打印完整的连接映射以帮助诊断
            logger.debug(f"  完整连接映射: {self._connections_map}")

        random_connections = [c for c in connections if c.get('type') == 'random']
        if random_connections:
            from tasks.random_jump import get_branch_weight

            current_card = self.cards_data.get(current_card_id)
            current_params = {}
            if isinstance(current_card, dict):
                current_params = current_card.get('parameters', {}) or {}
            elif current_card is not None:
                current_params = getattr(current_card, 'parameters', {}) or {}

            weights_config = current_params.get('random_weights')
            next_card = self._graph_engine.next_card(
                current_card_id,
                success,
                random_weight=lambda conn: get_branch_weight(
                    weights_config,
                    conn.get('end_card_id'),
                ),
            )
            logger.info(f"  [随机跳转] 从 {len(random_connections)} 个随机连接中按卡片权重选择 -> 卡片 {next_card}")
            return next_card

        next_card = self._graph_engine.next_card(current_card_id, success)
        if next_card is None:
            logger.warning("  ✗ 没有找到下一个卡片，工作流将结束")
        return next_card


    def _has_next_connection(
        self,
        current_card_id: int,
        success: bool,
    ) -> bool:
        return self._graph_engine.has_next(current_card_id, success)

    def is_running(self) -> bool:
        """检查是否正在运行"""
        return self._is_running

    def moveToThread(self, thread: QThread):
        """移动到指定线程"""
        super().moveToThread(thread)
        logger.debug(f"WorkflowExecutor 已移动到线程: {thread}")
