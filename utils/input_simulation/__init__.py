"""
输入模拟模块
提供统一的键盘鼠标模拟接口，使用相同选项处理所有目标窗口
"""

from .base import BaseInputSimulator, InputSimulatorType, ElementNotFoundError
from .standard_window import StandardWindowInputSimulator
from .plugin_simulator import PluginInputSimulator
from .factory import (
    InputSimulatorFactory,
    GlobalInputSimulatorManager,
    global_input_simulator_manager,
    SimulatorBackend,
    BackendNotAvailableError
)

__all__ = [
    'BaseInputSimulator',
    'InputSimulatorType',
    'ElementNotFoundError',
    'StandardWindowInputSimulator',
    'PluginInputSimulator',
    'InputSimulatorFactory',
    'GlobalInputSimulatorManager',
    'global_input_simulator_manager',
    'SimulatorBackend',
    'BackendNotAvailableError'
]
