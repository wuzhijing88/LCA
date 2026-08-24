"""
输入模拟模块
提供统一的键盘鼠标模拟接口，支持普通窗口和模拟器窗口
"""

from .base import BaseInputSimulator, InputSimulatorType, ElementNotFoundError
from .standard_window import StandardWindowInputSimulator
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
    'InputSimulatorFactory',
    'GlobalInputSimulatorManager',
    'global_input_simulator_manager',
    'SimulatorBackend',
    'BackendNotAvailableError'
]
