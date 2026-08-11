"""
输入模拟基础接口模块
定义键盘鼠标模拟的统一接口
"""

from abc import ABC, abstractmethod
from typing import Optional, Tuple, Dict, Any, List
import logging
from utils.input_timing import DEFAULT_KEY_HOLD_SECONDS

logger = logging.getLogger(__name__)


class BaseInputSimulator(ABC):
    """输入模拟器基础接口"""
    
    def __init__(self, hwnd: int):
        """
        初始化输入模拟器
        
        Args:
            hwnd: 目标窗口句柄
        """
        self.hwnd = hwnd
        self.logger = logger
    
    @abstractmethod
    def click(self, x: int, y: int, button: str = 'left', clicks: int = 1, interval: float = 0.1) -> bool:
        """
        鼠标点击

        Args:
            x: X坐标
            y: Y坐标
            button: 鼠标按钮 ('left', 'right', 'middle')
            clicks: 点击次数
            interval: 点击间隔

        Returns:
            bool: 操作是否成功
        """
        pass

    @abstractmethod
    def mouse_down(self, x: int, y: int, button: str = 'left') -> bool:
        """
        鼠标按下

        Args:
            x: X坐标
            y: Y坐标
            button: 鼠标按钮 ('left', 'right', 'middle')

        Returns:
            bool: 操作是否成功
        """
        pass

    @abstractmethod
    def mouse_up(self, x: int, y: int, button: str = 'left') -> bool:
        """
        鼠标释放

        Args:
            x: X坐标
            y: Y坐标
            button: 鼠标按钮 ('left', 'right', 'middle')

        Returns:
            bool: 操作是否成功
        """
        pass

    @abstractmethod
    def double_click(self, x: int, y: int, button: str = 'left') -> bool:
        """
        鼠标双击

        Args:
            x: X坐标
            y: Y坐标
            button: 鼠标按钮

        Returns:
            bool: 操作是否成功
        """
        pass

    @abstractmethod
    def move_mouse(self, x: int, y: int) -> bool:
        """
        鼠标移动

        Args:
            x: X坐标
            y: Y坐标

        Returns:
            bool: 操作是否成功
        """
        pass

    @abstractmethod
    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int,
             duration: float = 1.0, button: str = 'left') -> bool:
        """
        鼠标拖拽
        
        Args:
            start_x: 起始X坐标
            start_y: 起始Y坐标
            end_x: 结束X坐标
            end_y: 结束Y坐标
            duration: 拖拽持续时间
            button: 鼠标按钮
            
        Returns:
            bool: 操作是否成功
        """
        pass
    
    @abstractmethod
    def scroll(self, x: int, y: int, delta: int) -> bool:
        """
        鼠标滚轮
        
        Args:
            x: X坐标
            y: Y坐标
            delta: 滚动量
            
        Returns:
            bool: 操作是否成功
        """
        pass
    
    @abstractmethod
    def send_key(self, vk_code: int, scan_code: int = 0, extended: bool = False) -> bool:
        """
        发送按键
        
        Args:
            vk_code: 虚拟键码
            scan_code: 扫描码
            extended: 是否为扩展键
            
        Returns:
            bool: 操作是否成功
        """
        pass
    
    @abstractmethod
    def send_key_down(self, vk_code: int, scan_code: int = 0, extended: bool = False) -> bool:
        """
        发送按键按下
        
        Args:
            vk_code: 虚拟键码
            scan_code: 扫描码
            extended: 是否为扩展键
            
        Returns:
            bool: 操作是否成功
        """
        pass
    
    @abstractmethod
    def send_key_up(self, vk_code: int, scan_code: int = 0, extended: bool = False) -> bool:
        """
        发送按键释放
        
        Args:
            vk_code: 虚拟键码
            scan_code: 扫描码
            extended: 是否为扩展键
            
        Returns:
            bool: 操作是否成功
        """
        pass
    
    @abstractmethod
    def send_text(self, text: str, stop_checker=None) -> bool:
        """
        发送文本
        
        Args:
            text: 要发送的文本
            stop_checker: 停止检查函数，返回True表示需要停止
            
        Returns:
            bool: 操作是否成功
        """
        pass
    
    @abstractmethod
    def send_key_combination(self, keys: list, hold_duration: float = DEFAULT_KEY_HOLD_SECONDS) -> bool:
        """
        发送组合键

        Args:
            keys: 按键列表
            hold_duration: 按键保持时间

        Returns:
            bool: 操作是否成功
        """
        pass

    @abstractmethod
    def press_key_combination(self, keys: list) -> bool:
        """
        按下组合键（不释放）

        Args:
            keys: 按键列表

        Returns:
            bool: 操作是否成功
        """
        pass

    @abstractmethod
    def release_key_combination(self, keys: list) -> bool:
        """
        释放组合键

        Args:
            keys: 按键列表（逆序释放）

        Returns:
            bool: 操作是否成功
        """
        pass

    def click_element(
        self,
        name: str = None,
        automation_id: str = None,
        class_name: str = None,
        control_type: str = None,
        found_index: int = 0,
        search_depth: int = 10,
        timeout: float = 5.0,
        use_invoke: bool = True
    ) -> bool:
        """
        点击UI元素（基于UIAutomation）

        通过控件属性定位元素并点击。此方法仅原生模式支持，
        插件模式调用会抛出 NotImplementedError。

        Args:
            name: 元素名称（Name属性）
            automation_id: 自动化ID（AutomationId属性）
            class_name: 类名（ClassName属性）
            control_type: 控件类型（如 "ButtonControl", "EditControl"）
            found_index: 匹配到多个元素时选择第几个（从0开始）
            search_depth: 搜索深度
            timeout: 超时时间（秒）
            use_invoke: True使用Invoke模式（不移动鼠标），False使用坐标点击

        Returns:
            bool: 操作是否成功

        Raises:
            NotImplementedError: 当前模式不支持元素点击
            ElementNotFoundError: 未找到指定元素
            TimeoutError: 查找元素超时
        """
        raise NotImplementedError(f"{self.__class__.__name__} 不支持元素点击功能")

    def find_element(
        self,
        name: str = None,
        automation_id: str = None,
        class_name: str = None,
        control_type: str = None,
        search_depth: int = 10,
        timeout: float = 5.0
    ) -> Optional[Any]:
        """
        查找UI元素（基于UIAutomation）

        Args:
            name: 元素名称
            automation_id: 自动化ID
            class_name: 类名
            control_type: 控件类型
            search_depth: 搜索深度
            timeout: 超时时间（秒）

        Returns:
            找到的元素对象，未找到返回None

        Raises:
            NotImplementedError: 当前模式不支持元素查找
        """
        raise NotImplementedError(f"{self.__class__.__name__} 不支持元素查找功能")

    def find_all_elements(
        self,
        name: str = None,
        automation_id: str = None,
        class_name: str = None,
        control_type: str = None,
        search_depth: int = 10,
        timeout: float = 5.0
    ) -> List[Any]:
        """
        查找所有匹配的UI元素

        Args:
            name: 元素名称
            automation_id: 自动化ID
            class_name: 类名
            control_type: 控件类型
            search_depth: 搜索深度
            timeout: 超时时间（秒）

        Returns:
            匹配的元素列表

        Raises:
            NotImplementedError: 当前模式不支持元素查找
        """
        raise NotImplementedError(f"{self.__class__.__name__} 不支持元素查找功能")

    def get_element_text(
        self,
        name: str = None,
        automation_id: str = None,
        class_name: str = None,
        control_type: str = None,
        search_depth: int = 10,
        timeout: float = 5.0
    ) -> Optional[str]:
        """
        获取UI元素的文本内容

        Args:
            name: 元素名称
            automation_id: 自动化ID
            class_name: 类名
            control_type: 控件类型
            search_depth: 搜索深度
            timeout: 超时时间（秒）

        Returns:
            元素文本，未找到返回None

        Raises:
            NotImplementedError: 当前模式不支持此功能
        """
        raise NotImplementedError(f"{self.__class__.__name__} 不支持获取元素文本功能")


class ElementNotFoundError(Exception):
    """元素未找到异常"""
    pass


class InputSimulatorType:
    """输入模拟器类型枚举"""
    STANDARD_WINDOW = "standard_window"  # 普通窗口
    EMULATOR_WINDOW = "emulator_window"  # 模拟器窗口
