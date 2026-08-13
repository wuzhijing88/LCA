"""
输入模拟器工厂类
根据配置和窗口类型创建合适的输入模拟器
"""

import win32gui
import logging
import threading
import time
import os
from typing import Optional, Dict, Tuple, List
from .base import BaseInputSimulator, InputSimulatorType
from .mode_utils import get_foreground_driver, is_foreground_mode

logger = logging.getLogger(__name__)


class SimulatorBackend:
    """模拟器后端类型"""
    AUTO = "auto"        # 自动选择（当前默认行为）
    NATIVE = "native"    # 强制原生模式（Win32/驱动级）


class BackendNotAvailableError(Exception):
    """指定的后端不可用异常"""


class InputSimulatorFactory:
    """输入模拟器工厂类"""

    @staticmethod
    def create_simulator(
        hwnd: int,
        operation_mode: str = "auto",
        execution_mode: str = "background",
        backend: str = SimulatorBackend.AUTO,
        device_id: Optional[str] = None
    ) -> Optional[BaseInputSimulator]:
        """
        创建输入模拟器

        Args:
            hwnd: 窗口句柄
            operation_mode: 操作模式 ("standard_window", "emulator_window", "auto")
            execution_mode: 执行模式 (支持: "foreground", "foreground_*", "background", "background_*", "emulator_*")
            backend: 后端类型
                - "auto": 使用原生输入实现
                - "native": 强制使用原生输入实现
            device_id: 目标设备ID (多设备支持)

        Returns:
            BaseInputSimulator: 输入模拟器实例

        Raises:
            BackendNotAvailableError: 指定的后端不可用
        """
        # 延迟导入避免循环依赖

        if not hwnd:
            logger.error("窗口句柄无效（为空）")
            return None

        try:
            if not win32gui.IsWindow(hwnd):
                logger.error(f"窗口句柄{hwnd}无效或窗口已关闭")
                return None
        except Exception as e:
            logger.error(f"验证窗口句柄时出错: {e}")
            return None

        if backend not in (SimulatorBackend.AUTO, SimulatorBackend.NATIVE):
            raise BackendNotAvailableError(f"不支持的输入后端: {backend!r}")

        return InputSimulatorFactory._create_native_simulator(
            hwnd, operation_mode, execution_mode, device_id=device_id
        )

    @staticmethod
    def _create_native_simulator(
        hwnd: int,
        operation_mode: str,
        execution_mode: str,
        device_id: Optional[str] = None
    ) -> Optional[BaseInputSimulator]:
        """
        创建原生模式模拟器

        Args:
            hwnd: 窗口句柄
            operation_mode: 操作模式
            execution_mode: 执行模式
            device_id: 目标设备ID (多设备支持)

        Returns:
            原生模式模拟器实例
        """
        from .standard_window import StandardWindowInputSimulator

        # 始终使用标准窗口模式
        use_foreground = is_foreground_mode(execution_mode)
        foreground_driver = get_foreground_driver(execution_mode)
        return StandardWindowInputSimulator(
            hwnd,
            use_foreground=use_foreground,
            foreground_driver=foreground_driver,
            enable_deep_child_search=True,
            enable_activation_sequence=True,
            enable_message_guard=True,
            execution_mode=execution_mode
        )
    


class GlobalInputSimulatorManager:
    """
    全局输入模拟器管理器

    支持多线程并发：每个线程使用独立的模拟器实例，避免状态冲突
    """

    def __init__(self):
        self._default_operation_mode = "auto"
        self._default_execution_mode = "background"  # 恢复默认值
        self._simulators: Dict[Tuple[int, int, str, str, Optional[str]], BaseInputSimulator] = {}
        self._simulator_access_ts: Dict[Tuple[int, int, str, str, Optional[str]], float] = {}
        self._lock = threading.Lock()  # 线程锁，保护缓存字典
        self._enable_cache = True  # 是否启用缓存（可在并发场景禁用）
        self._max_cache_size = self._read_int_env(
            "LCA_INPUT_SIM_CACHE_MAX_SIZE",
            64,
            8,
            1024,
        )
        self._cache_cleanup_interval = self._read_float_env(
            "LCA_INPUT_SIM_CACHE_CLEANUP_INTERVAL_SEC",
            1.0,
            0.1,
            60.0,
        )
        self._simulator_idle_ttl_seconds = self._read_float_env(
            "LCA_INPUT_SIM_CACHE_IDLE_TTL_SEC",
            45.0,
            5.0,
            3600.0,
        )
        self._last_cache_cleanup_ts = 0.0

    @staticmethod
    def _read_int_env(name: str, default: int, min_value: int, max_value: int) -> int:
        raw_value = os.environ.get(name)
        if raw_value is None:
            return default
        try:
            parsed_value = int(raw_value)
        except (TypeError, ValueError):
            return default
        if parsed_value < min_value:
            return min_value
        if parsed_value > max_value:
            return max_value
        return parsed_value

    @staticmethod
    def _read_float_env(name: str, default: float, min_value: float, max_value: float) -> float:
        raw_value = os.environ.get(name)
        if raw_value is None:
            return default
        try:
            parsed_value = float(raw_value)
        except (TypeError, ValueError):
            return default
        if parsed_value < min_value:
            return min_value
        if parsed_value > max_value:
            return max_value
        return parsed_value

    @staticmethod
    def _safe_close_simulator(simulator: BaseInputSimulator) -> None:
        close_fn = getattr(simulator, "close", None)
        if callable(close_fn):
            try:
                close_fn()
            except Exception:
                pass

    def _close_simulators(self, simulators: List[BaseInputSimulator]) -> None:
        for simulator in simulators:
            self._safe_close_simulator(simulator)

    @staticmethod
    def _is_window_valid(hwnd: int) -> bool:
        try:
            return bool(hwnd) and bool(win32gui.IsWindow(hwnd))
        except Exception:
            return False

    def _drain_cache_unlocked(self) -> List[BaseInputSimulator]:
        simulators = list(self._simulators.values())
        self._simulators.clear()
        self._simulator_access_ts.clear()
        self._last_cache_cleanup_ts = time.monotonic()
        return simulators

    def _evict_cache_keys_unlocked(self, keys: List[Tuple[int, int, str, str, Optional[str]]]) -> List[BaseInputSimulator]:
        removed: List[BaseInputSimulator] = []
        for key in keys:
            simulator = self._simulators.pop(key, None)
            self._simulator_access_ts.pop(key, None)
            if simulator is not None:
                removed.append(simulator)
        return removed

    def _prune_cache_unlocked(self, now: Optional[float] = None, force: bool = False) -> List[BaseInputSimulator]:
        if not self._simulators:
            return []

        current = now if now is not None else time.monotonic()
        if not force and (current - self._last_cache_cleanup_ts) < self._cache_cleanup_interval:
            return []

        self._last_cache_cleanup_ts = current
        stale_keys = set()

        alive_thread_ids = {thread.ident for thread in threading.enumerate() if thread.ident is not None}
        for key in list(self._simulators.keys()):
            thread_id, hwnd = key[0], key[1]
            if thread_id not in alive_thread_ids:
                stale_keys.add(key)
                continue
            if not self._is_window_valid(hwnd):
                stale_keys.add(key)
                continue
            last_access = self._simulator_access_ts.get(key, current)
            if (current - last_access) > self._simulator_idle_ttl_seconds:
                stale_keys.add(key)

        survivors = [key for key in self._simulators.keys() if key not in stale_keys]
        overflow = len(survivors) - self._max_cache_size
        if overflow > 0:
            ordered = sorted(survivors, key=lambda key: self._simulator_access_ts.get(key, 0.0))
            stale_keys.update(ordered[:overflow])

        if not stale_keys:
            return []
        return self._evict_cache_keys_unlocked(list(stale_keys))

    def set_enable_cache(self, enable: bool):
        """
        设置是否启用缓存

        Args:
            enable: True启用缓存，False每次创建新实例
        """
        simulators_to_close: List[BaseInputSimulator] = []
        with self._lock:
            self._enable_cache = enable
            if not enable:
                simulators_to_close = self._drain_cache_unlocked()
        if simulators_to_close:
            self._close_simulators(simulators_to_close)
        logger.info(f"输入模拟器缓存{'已启用' if enable else '已禁用'}")

    def set_default_operation_mode(self, mode: str):
        """设置默认操作模式"""
        if mode in [InputSimulatorType.STANDARD_WINDOW, InputSimulatorType.EMULATOR_WINDOW, "auto"]:
            simulators_to_close: List[BaseInputSimulator] = []
            with self._lock:
                self._default_operation_mode = mode
                # 清除缓存，强制重新创建模拟器
                simulators_to_close = self._drain_cache_unlocked()
            if simulators_to_close:
                self._close_simulators(simulators_to_close)
            logger.info(f"默认操作模式已设置为: {mode}")
        else:
            logger.warning(f"无效的操作模式: {mode}")

    def set_default_execution_mode(self, mode: str):
        """设置默认执行模式"""
        valid_modes = ["foreground", "background"]
        if mode in valid_modes or mode.startswith('foreground') or mode.startswith('background'):
            simulators_to_close: List[BaseInputSimulator] = []
            with self._lock:
                self._default_execution_mode = mode
                # 清除缓存，强制重新创建模拟器
                simulators_to_close = self._drain_cache_unlocked()
            if simulators_to_close:
                self._close_simulators(simulators_to_close)
            logger.info(f"默认执行模式已设置为: {mode}")
        else:
            logger.warning(f"无效的执行模式: {mode}")

    def get_simulator(self, hwnd: int, operation_mode: Optional[str] = None,
                     execution_mode: Optional[str] = None, device_id: Optional[str] = None) -> Optional[BaseInputSimulator]:
        """
        获取输入模拟器（支持多线程并发）

        每个线程获取独立的模拟器实例，避免并发冲突

        Args:
            hwnd: 窗口句柄
            operation_mode: 操作模式，None使用默认值
            execution_mode: 执行模式，None使用默认值
                          支持模式: 'foreground', 'background'
            device_id: 目标设备ID (多设备支持)

        Returns:
            BaseInputSimulator: 输入模拟器实例
        """
        # 使用默认值
        if operation_mode is None:
            operation_mode = self._default_operation_mode
        if execution_mode is None:
            # 如果没有指定执行模式，使用默认值
            # 如果默认值也是None，说明需要调用方明确指定，抛出警告
            if self._default_execution_mode is None:
                logger.error("execution_mode为None且没有设置默认值，调用方必须明确指定执行模式！")
                return None
            execution_mode = self._default_execution_mode
            logger.debug(f"execution_mode为None，使用默认值: {execution_mode}")

        # 如果禁用缓存，直接创建新实例
        if not self._enable_cache:
            simulator = InputSimulatorFactory.create_simulator(hwnd, operation_mode, execution_mode, device_id=device_id)
            return simulator

        # 获取当前线程ID，确保每个线程使用独立的模拟器实例
        thread_id = threading.get_ident()

        # 生成缓存键（包含线程ID和device_id）
        cache_key = (thread_id, hwnd, operation_mode, execution_mode, device_id)

        simulators_to_close: List[BaseInputSimulator] = []
        cached_simulator: Optional[BaseInputSimulator] = None
        now = time.monotonic()

        with self._lock:
            simulators_to_close.extend(self._prune_cache_unlocked(now=now))

            # 检查缓存
            if cache_key in self._simulators:
                simulator = self._simulators[cache_key]
                # 验证窗口是否仍然有效
                if self._is_window_valid(hwnd):
                    self._simulator_access_ts[cache_key] = now
                    cached_simulator = simulator
                else:
                    simulators_to_close.extend(self._evict_cache_keys_unlocked([cache_key]))

        if simulators_to_close:
            self._close_simulators(simulators_to_close)
        if cached_simulator is not None:
            return cached_simulator

        # 创建新的模拟器
        simulator = InputSimulatorFactory.create_simulator(hwnd, operation_mode, execution_mode, device_id=device_id)
        if simulator:
            simulators_to_close = []
            now = time.monotonic()
            with self._lock:
                simulators_to_close.extend(self._prune_cache_unlocked(now=now))
                self._simulators[cache_key] = simulator
                self._simulator_access_ts[cache_key] = now
                simulators_to_close.extend(self._prune_cache_unlocked(now=now, force=True))
            if simulators_to_close:
                self._close_simulators(simulators_to_close)
            logger.debug(f"为线程{thread_id}创建新的输入模拟器实例（hwnd={hwnd}, op_mode={operation_mode}, exec_mode={execution_mode}, device_id={device_id}）")

        return simulator

    def clear_cache(self):
        """清除模拟器缓存"""
        simulators: List[BaseInputSimulator] = []
        with self._lock:
            simulators = self._drain_cache_unlocked()
        if simulators:
            self._close_simulators(simulators)
        logger.info("输入模拟器缓存已清除")

    def get_default_operation_mode(self) -> str:
        """获取默认操作模式"""
        return self._default_operation_mode

    def get_default_execution_mode(self) -> str:
        """获取默认执行模式"""
        return self._default_execution_mode


# 全局管理器实例
global_input_simulator_manager = GlobalInputSimulatorManager()
