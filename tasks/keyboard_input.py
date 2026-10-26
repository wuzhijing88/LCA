# -*- coding: utf-8 -*-
import logging
import os
import time
import random
import string
import re
import json
import math
from typing import Dict, Any, Optional, List, Set, Tuple
import ctypes

import win32api
import win32con
import win32gui
import win32process

from utils.input.foreground_input_manager import get_foreground_input_manager

foreground_input = get_foreground_input_manager()

from .task_utils import precise_sleep, coerce_bool
from .click_action_executor import execute_simulator_click_action
from .click_param_resolver import normalize_click_action
from .click_simulator_adapters import ForegroundDriverSimulatorAdapter
from utils.input.input_timing import (
    DEFAULT_CLICK_HOLD_SECONDS,
    DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS,
    DEFAULT_KEY_HOLD_SECONDS,
    DEFAULT_RANDOM_CLICK_HOLD_MAX_SECONDS,
    DEFAULT_RANDOM_CLICK_HOLD_MIN_SECONDS,
    DEFAULT_RANDOM_KEY_HOLD_MAX_SECONDS,
    DEFAULT_RANDOM_KEY_HOLD_MIN_SECONDS,
)
from utils.input.key_repeat import hold_with_system_repeat, run_system_repeat_schedule

logger = logging.getLogger(__name__)

# 任务类型标识
TASK_TYPE = "模拟键盘操作"
TASK_NAME = "模拟键盘操作"

_VAR_PATTERN = re.compile(r"\$\{([^{}]+)\}|\{\{([^{}]+)\}\}")
_MISSING = object()
_COMPLETE_PRESS_HOLD_SECONDS = DEFAULT_KEY_HOLD_SECONDS
_DEFAULT_COMBO_REPEAT_INTERVAL_SECONDS = 0.02
_COMBO_STEP_SPLIT_PATTERN = re.compile(r"[,\n;，；]+")
_COMBO_ARG_SPLIT_PATTERN = re.compile(r"[,，]")
_COMBO_REPEAT_SUFFIX_PATTERN = re.compile(
    r"^(?P<body>.+?)\s*\*\s*(?P<count>\d+)(?:\s*(?:@|/|每隔|间隔)\s*(?P<interval>\d+(?:\.\d+)?))?\s*$"
)
_COMBO_WAIT_TOKEN_PATTERN = re.compile(
    r"^(?P<name>wait|delay|sleep|pause|等待|延迟|停顿)\s*(?:\((?P<args>[^()]*)\)|(?P<plain>\d+(?:\.\d+)?(?:\s*[,，]\s*\d+(?:\.\d+)?)?))\s*$",
    re.IGNORECASE,
)
_COMBO_KEY_FUNCTION_TOKEN_PATTERN = re.compile(
    r"^(?P<name>key_down|keydown|down_key|key_hold|key_up|keyup|up_key|key_release|release_key|key_press|keypress|press_key|key_tap|tap_key|key|press|tap|按键按下|按键按住|按键松开|按键释放|按键点按|按键敲击|按键)\s*\((?P<args>[^()]*)\)\s*$",
    re.IGNORECASE,
)
_COMBO_KEY_FUNCTION_ACTIONS = {
    "key_down": "down",
    "keydown": "down",
    "down_key": "down",
    "key_hold": "down",
    "按键按下": "down",
    "按键按住": "down",
    "key_up": "up",
    "keyup": "up",
    "up_key": "up",
    "key_release": "up",
    "release_key": "up",
    "按键松开": "up",
    "按键释放": "up",
    "key_press": "press",
    "keypress": "press",
    "press_key": "press",
    "key_tap": "press",
    "tap_key": "press",
    "key": "press",
    "press": "press",
    "tap": "press",
    "按键点按": "press",
    "按键敲击": "press",
    "按键": "press",
}
_COMBO_ACTION_SUFFIX_PATTERN = re.compile(
    r"^(?P<key>.+?)(?:\((?P<act1>[^()]+)\)|\s+(?P<act2>down|hold|up|release|press|tap|click|按下|按住|松开|弹起|抬起|释放|完整按键|完整|点按|点击|敲击))$",
    re.IGNORECASE,
)
_COMBO_ACTION_ALIASES = {
    "down": "down",
    "hold": "down",
    "按下": "down",
    "按住": "down",
    "up": "up",
    "release": "up",
    "松开": "up",
    "弹起": "up",
    "抬起": "up",
    "释放": "up",
    "press": "press",
    "tap": "press",
    "click": "press",
    "完整": "press",
    "完整按键": "press",
    "点按": "press",
    "点击": "press",
    "敲击": "press",
}
_COMBO_KEY_ALIASES = {
    "control": "ctrl",
    "ctrl": "ctrl",
    "ctl": "ctrl",
    "lctrl": "ctrl",
    "rctrl": "ctrl",
    "leftctrl": "ctrl",
    "rightctrl": "ctrl",
    "控制": "ctrl",
    "控制键": "ctrl",
    "option": "alt",
    "alt": "alt",
    "lalt": "alt",
    "ralt": "alt",
    "leftalt": "alt",
    "rightalt": "alt",
    "菜单": "alt",
    "shift": "shift",
    "lshift": "shift",
    "rshift": "shift",
    "leftshift": "shift",
    "rightshift": "shift",
    "win": "win",
    "windows": "win",
    "command": "win",
    "super": "win",
    "空格": "space",
    "回车": "enter",
    "返回": "enter",
    "删除": "delete",
    "退格": "backspace",
    "esc": "esc",
    "escape": "esc",
    "上": "up",
    "下": "down",
    "左": "left",
    "右": "right",
    "方向上": "up",
    "方向下": "down",
    "方向左": "left",
    "方向右": "right",
    "上箭头": "up",
    "下箭头": "down",
    "左箭头": "left",
    "右箭头": "right",
    "页上": "pageup",
    "上一页": "pageup",
    "页下": "pagedown",
    "下一页": "pagedown",
    "大写锁定": "capslock",
    "数字锁定": "numlock",
    "截图": "printscreen",
}
_RECORDED_KEY_ALIASES = {
    "left ctrl": "ctrl",
    "right ctrl": "ctrl",
    "lctrl": "ctrl",
    "rctrl": "ctrl",
    "leftctrl": "ctrl",
    "rightctrl": "ctrl",
    "left shift": "shift",
    "right shift": "shift",
    "lshift": "shift",
    "rshift": "shift",
    "leftshift": "shift",
    "rightshift": "shift",
    "left alt": "alt",
    "right alt": "alt",
    "lalt": "alt",
    "ralt": "alt",
    "leftalt": "alt",
    "rightalt": "alt",
    "alt gr": "alt",
    "left windows": "win",
    "right windows": "win",
    "windows": "win",
    "spacebar": "space",
    "page down": "pagedown",
    "page up": "pageup",
    "caps lock": "capslock",
    "num lock": "numlock",
    "scroll lock": "scrolllock",
    "print screen": "printscreen",
}
_COMBO_MOUSE_PREFIX_ALIASES = {
    "mouse_left": "left",
    "mouseleft": "left",
    "mouse_l": "left",
    "lbutton": "left",
    "leftbutton": "left",
    "left": "left",
    "左键": "left",
    "鼠标左键": "left",
    "鼠标左": "left",
    "mouse_right": "right",
    "mouseright": "right",
    "mouse_r": "right",
    "rbutton": "right",
    "rightbutton": "right",
    "right": "right",
    "右键": "right",
    "鼠标右键": "right",
    "鼠标右": "right",
    "mouse_middle": "middle",
    "mousemiddle": "middle",
    "mouse_m": "middle",
    "mbutton": "middle",
    "middlebutton": "middle",
    "middle": "middle",
    "中键": "middle",
    "鼠标中键": "middle",
    "鼠标中": "middle",
}
_COMBO_MOUSE_ACTION_SUFFIX_ALIASES = {
    "_double": "双击",
    "_dbl": "双击",
    "double": "双击",
    "dbl": "双击",
    "双击": "双击",
    "_down": "仅按下",
    "down": "仅按下",
    "_press": "仅按下",
    "press": "仅按下",
    "按下": "仅按下",
    "按住": "仅按下",
    "_up": "仅松开",
    "up": "仅松开",
    "_release": "仅松开",
    "release": "仅松开",
    "松开": "仅松开",
    "弹起": "仅松开",
    "抬起": "仅松开",
    "释放": "仅松开",
    "_click": "完整点击",
    "_single": "完整点击",
    "click": "完整点击",
    "tap": "完整点击",
    "single": "完整点击",
    "点击": "完整点击",
    "单击": "完整点击",
    "点按": "完整点击",
}
_COMBO_MOUSE_ACTION_SUFFIX_ITEMS = sorted(
    _COMBO_MOUSE_ACTION_SUFFIX_ALIASES.items(),
    key=lambda item: len(item[0]),
    reverse=True,
)
_COMBO_MOUSE_WHEEL_PREFIX_ALIASES = {
    "mouse_wheel_up": "up",
    "mouse_wheel_down": "down",
    "mousewheelup": "up",
    "mousewheeldown": "down",
    "mouse_scroll_up": "up",
    "mouse_scroll_down": "down",
    "mousescrollup": "up",
    "mousescrolldown": "down",
    "wheel_up": "up",
    "wheel_down": "down",
    "wheelup": "up",
    "wheeldown": "down",
    "scroll_up": "up",
    "scroll_down": "down",
    "scrollup": "up",
    "scrolldown": "down",
    "滚轮上": "up",
    "滚轮下": "down",
    "滚轮向上": "up",
    "滚轮向下": "down",
    "鼠标滚轮上": "up",
    "鼠标滚轮下": "down",
    "鼠标滚轮向上": "up",
    "鼠标滚轮向下": "down",
}
_COMBO_INSERT_MOUSE_ACTION_OPTIONS: List[Tuple[str, Optional[str]]] = [
    ("左键单击", "mouse_left"),
    ("左键双击", "mouse_left_double"),
    ("左键按下", "mouse_left_down"),
    ("左键松开", "mouse_left_up"),
    ("---", None),
    ("右键单击", "mouse_right"),
    ("右键双击", "mouse_right_double"),
    ("右键按下", "mouse_right_down"),
    ("右键松开", "mouse_right_up"),
    ("---", None),
    ("中键单击", "mouse_middle"),
    ("中键双击", "mouse_middle_double"),
    ("中键按下", "mouse_middle_down"),
    ("中键松开", "mouse_middle_up"),
    ("---", None),
    ("滚轮上滚", "mouse_wheel_up"),
    ("滚轮下滚", "mouse_wheel_down"),
]

KEY_MOUSE_INPUT_TYPE = "键盘按键"
KEY_MOUSE_ACTION_COMPLETE = "完整执行"
KEY_MOUSE_ACTION_HOLD = "只按下"
KEY_MOUSE_ACTION_RELEASE = "只释放"
_MAX_KEY_MOUSE_KEYS: Optional[int] = None
_MAX_KEY_MOUSE_MOUSE_ACTIONS: Optional[int] = None
_RECORDED_DOUBLE_CLICK_SECONDS = 0.35
_RECORDED_DOUBLE_CLICK_DISTANCE = 8
_RECORDED_DELAY_MIN_SECONDS = 0.02
_RECORDED_LONG_PRESS_SECONDS = 0.20


def _stringify_value(value) -> str:
    if isinstance(value, (dict, list, tuple)):
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return str(value)
    return str(value)


def _publish_typed_text(kwargs: Any, text: Any) -> None:
    try:
        from task_workflow.card_payload import publish_card_payload
        from task_workflow.workflow_context import get_workflow_context

        publish_card_payload(
            kwargs.get("workflow_context") or get_workflow_context(),
            kwargs.get("card_id"),
            last_input_text=str(text or ""),
        )
    except Exception:
        pass


def _resolve_text_template(text: str) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        return _stringify_value(text)
    return text


def _coerce_non_negative_duration(value: Any) -> float:
    """校验现行输入时长，不把无效参数改成其他时长继续执行。"""
    try:
        duration = float(value)
    except (TypeError, ValueError):
        raise ValueError("按键时长必须是大于等于0的有限秒数") from None
    if not math.isfinite(duration) or duration < 0:
        raise ValueError("按键时长必须是大于等于0的有限秒数")
    return duration


def _hold_for_duration(duration: Any, label: str = "时长") -> float:
    """高精度保持指定时长，并记录实际偏差（毫秒）。"""
    target = _coerce_non_negative_duration(duration)
    if target <= 0:
        return 0.0

    start = time.perf_counter()
    precise_sleep(target, spin_threshold=0.05, coarse_slice=0.005)
    elapsed = time.perf_counter() - start

    # 极端情况下兜底补足，确保不少于目标时长
    remaining = target - elapsed
    if remaining > 0:
        precise_sleep(remaining, spin_threshold=0.05, coarse_slice=0.005)
        elapsed = time.perf_counter() - start

    drift_ms = (elapsed - target) * 1000.0
    if abs(drift_ms) >= 2.0:
        logger.debug(f"[{label}] 目标={target:.4f}s, 实际={elapsed:.4f}s, 偏差={drift_ms:+.2f}ms")

    return elapsed


def _combo_key_repeat_enabled(params: Optional[Dict[str, Any]] = None) -> bool:
    if not params or "combo_key_repeat" not in params:
        return True
    return coerce_bool(params.get("combo_key_repeat"))


def _combo_key_repeat_interval(params: Optional[Dict[str, Any]] = None) -> Optional[float]:
    if not _combo_key_repeat_enabled(params):
        return None
    if not params or "combo_key_repeat_interval" not in params:
        return None
    value = params.get("combo_key_repeat_interval")
    if value is None or value == "":
        return None
    interval = float(value)
    if not math.isfinite(interval) or interval < 0:
        raise ValueError("连发间隔必须是大于等于0的有限秒数，0表示系统重复率")
    if interval == 0:
        return None
    return interval


def _foreground_repeat_target(pressed_keys: List[str]) -> Optional[str]:
    modifiers = {"ctrl", "shift", "alt", "win", "lctrl", "rctrl", "lshift", "rshift", "lalt", "ralt", "lwin", "rwin"}
    for key_name in reversed(pressed_keys):
        if str(key_name).strip().lower() not in modifiers:
            return str(key_name).strip()
    return None


def _execute_precise_key_hold(
    driver: Any,
    key: str,
    hold_duration: Any,
    label: str = "按键按住",
    enable_repeat: bool = True,
    repeat_interval: Optional[float] = None,
    stop_checker=None,
) -> bool:
    """按住；enable_repeat 为真时按间隔或系统键盘重复率补发。"""
    if driver is None:
        return False

    key_name = str(key or "").strip()
    if not key_name:
        return False
    if not hasattr(driver, "key_down") or not hasattr(driver, "key_up"):
        logger.error(f"[{label}] 驱动不支持按下/松开: {key_name}")
        return False

    safe_hold = _coerce_non_negative_duration(hold_duration)
    try:
        return hold_with_system_repeat(
            down=lambda: bool(driver.key_down(key_name)),
            up=lambda: bool(driver.key_up(key_name)),
            repeat=lambda: bool(driver.key_up(key_name)) and bool(driver.key_down(key_name)),
            duration=safe_hold,
            sleep=lambda seconds: _hold_for_duration(seconds, label),
            enable_repeat=bool(enable_repeat),
            repeat_interval=repeat_interval,
            stop_checker=stop_checker,
        )
    except InterruptedError:
        raise
    except Exception:
        logger.exception(f"[{label}] 按住失败: {key_name}")
        return False


def _default_complete_press_hold_seconds() -> float:
    """完整按键默认按压时长（秒）。"""
    return _COMPLETE_PRESS_HOLD_SECONDS


def _resolve_press_hold_duration(step: Dict[str, Any]) -> float:
    if "hold_duration" in step and step.get("hold_duration") is not None:
        return _coerce_non_negative_duration(step.get("hold_duration"))
    return _default_complete_press_hold_seconds()


def show_text_examples(params: Dict[str, Any], **kwargs) -> None:
    """显示文本输入格式示例"""
    from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton, QLabel

    parameter_panel = kwargs.get('parameter_panel')
    main_window = kwargs.get('main_window')
    parent = parameter_panel if parameter_panel else main_window

    dialog = QDialog(parent)
    dialog.setWindowTitle("文本输入格式示例")
    dialog.resize(640, 520)

    layout = QVBoxLayout(dialog)

    title = QLabel("文本输入格式示例")
    title.setObjectName("text_input_examples_title")
    layout.addWidget(title)

    text_edit = QTextEdit()
    text_edit.setReadOnly(True)

    examples_text = """
=== 基础用法 ===

1. 单组文本
   直接填写要输入的内容，例如：
   你好，世界

2. 多组文本
   每行一组，按配置依次输入：
   账号123
   密码456

=== 提示 ===
• 文本按字面量发送，不会做模板替换
• 换行、空格和标点都会原样输入
"""

    text_edit.setPlainText(examples_text.strip())
    text_edit.setObjectName("text_input_examples_text")
    layout.addWidget(text_edit)

    close_btn = QPushButton("关闭")
    close_btn.clicked.connect(dialog.accept)
    layout.addWidget(close_btn)

    dialog.exec()


def show_combo_sequence_examples(params: Dict[str, Any], **kwargs) -> None:
    """显示键盘按键配置的详细说明。"""
    from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton, QLabel

    parameter_panel = kwargs.get('parameter_panel')
    main_window = kwargs.get('main_window')
    parent = parameter_panel if parameter_panel else main_window

    dialog = QDialog(parent)
    dialog.setWindowTitle("键盘按键详细说明")
    dialog.resize(700, 560)

    layout = QVBoxLayout(dialog)

    title = QLabel("可编辑键盘按键说明")
    title.setObjectName("combo_sequence_examples_title")
    layout.addWidget(title)

    text_edit = QTextEdit()
    text_edit.setReadOnly(True)

    examples_text = """
=== 基础写法 ===

1. 完整按键
   写法: a
   含义: 按下并松开 a

2. 连按次数
   写法: a*3
   写法: a*5@0.2
   写法: key_press(a,5,0.2)
   含义: 连按 3 次 a
   说明: @0.2 或第 3 个参数表示每次之间等待 0.2 秒

3. 按下/松开
   写法: ctrl(按下), a, ctrl(松开)
   写法: ctrl(按下), a*5@0.2, ctrl(松开)
   写法: ctrl hold + a tap + ctrl release
   含义: 先按住 ctrl，执行 a，再松开 ctrl

4. 等待
   写法: wait(0.2)
   写法: wait 0.2
   写法: wait(0.1,0.3)
   含义: 固定等待 0.2 秒，或随机等待 0.1-0.3 秒

5. 快捷组合写法
   写法: ctrl+shift+a
   含义: 自动展开为按下 ctrl/shift/a，再逆序松开
   说明: 可连续写多组，例如 ctrl+a, wait(0.1), ctrl+c

=== 鼠标动作（支持多步骤与坐标） ===

6. 单击（默认）
   写法: mouse_left(1163,947)
   写法: 鼠标左键(1163,947)
   写法: 鼠标左键点击(1163，947)
   含义: 在坐标 (1163,947) 执行一次左键点击

7. 双击
   写法: mouse_left_double(1163,947)
   写法: 鼠标左键双击(1163,947)

8. 按下/松开
   写法: mouse_left_down(1163,947), mouse_left_up(1163,947)
   写法: 鼠标左键按下(1163,947), 鼠标左键松开(1163,947)
   说明: 可穿插按键与等待，适合拖拽或按住技能键再点击

9. 右键/中键
   写法: mouse_right(300,400)
   写法: mouse_middle_double(300,400)

10. 滚轮
   写法: mouse_wheel_up(300,400)
   写法: mouse_wheel_down(300,400,3)  # 第3个参数是滚动步数
   写法: 鼠标滚轮上(300,400), 鼠标滚轮下(300,400,3)
   写法: 滚轮向下(3)
   写法: mouse_wheel_down() / mouse_wheel_down(3)  # 无坐标时使用当前鼠标位置

11. 与按键混合
   写法: w(按下), mouse_left(1163,947), w(松开)
   写法: w(按下), mouse_left(), w(松开)  # 无坐标点击当前鼠标位置
   写法: shift(按住), 鼠标左键按下(500,300), wait 0.2, 鼠标左键松开(650,300), shift(松开)

12. 常用别名
   命令式写法: key_down(ctrl), key_press(a,3,0.1), key_up(ctrl)
   按键动作: down/hold/按下/按住, up/release/松开/释放, press/tap/点按/敲击
   鼠标动作: click/tap/点击/单击, double/dbl/双击, down/按住, up/release/松开
   按键名: 空格/回车/退格/上箭头/下箭头/左箭头/右箭头/上一页/下一页

=== 分隔符 ===

13. 步骤分隔支持 , ; 换行 和 +
   示例: w(按下)+wait(0.05)+space+w(松开)

=== 面板工具 ===

14. 开始录制按键
   点击后开始记录按键，再点一次停止并回填到输入框
   录制支持连续按键与多个鼠标单击/双击动作

15. 获取点击坐标 + 插入鼠标动作
   先取坐标，再点“插入鼠标动作”选择类型自动导入

=== 注意 ===

• 坐标按目标窗口客户区处理
• 插入时坐标是 0,0 会自动写成无坐标语法（执行时使用当前鼠标位置）
• 按住方式选“持续按下”时保持按下直到松开；选“连发”时在保持期间继续补发
• 连发间隔设为 0 使用系统重复率，大于 0 时使用指定的秒数
• 按键动作与鼠标动作默认不限制数量，可按顺序自由组合
• 显式写了 (按下) 的按键，必须写对应的 (松开)
• 推荐先用“详细说明”里的格式填写，避免语法错误
"""

    text_edit.setPlainText(examples_text.strip())
    text_edit.setObjectName("combo_sequence_examples_text")
    layout.addWidget(text_edit)

    close_btn = QPushButton("关闭")
    close_btn.clicked.connect(dialog.accept)
    layout.addWidget(close_btn)

    dialog.exec()


def _execute_combo_mouse_action(simulator, mouse_op: dict, logger) -> bool:
    """
    执行组合键中的鼠标操作

    Args:
        simulator: 输入模拟器实例
        mouse_op: 鼠标操作信息 {'button': 'left/right/middle', 'action': '完整点击/仅按下/仅松开', 'x': int, 'y': int, 'hold_duration': float, 'enable_auto_release': bool}
        logger: 日志记录器

    Returns:
        bool: 操作是否成功
    """
    class _ComboMouseSimulatorAdapter:
        def __init__(self, raw_simulator):
            self._simulator = raw_simulator
            self.supports_atomic_click_hold = bool(getattr(raw_simulator, "supports_atomic_click_hold", False))

        def click(
            self,
            x: int,
            y: int,
            button: str = "left",
            clicks: int = 1,
            interval: float = 0.0,
            duration: float = 0.0,
        ) -> bool:
            if not hasattr(self._simulator, 'click'):
                raise AttributeError("模拟器不支持click接口")
            safe_duration = float(duration)
            if not math.isfinite(safe_duration) or safe_duration < 0:
                raise ValueError("鼠标保持时间无效")

            return bool(self._simulator.click(
                int(x), int(y), button=button, clicks=int(clicks),
                interval=float(interval), duration=safe_duration,
            ))

        def mouse_down(self, x: int, y: int, button: str = "left") -> bool:
            return bool(self._simulator.mouse_down(int(x), int(y), button))

        def mouse_up(self, x: int, y: int, button: str = "left") -> bool:
            return bool(self._simulator.mouse_up(int(x), int(y), button))

        def double_click(self, x: int, y: int, button: str = "left", interval=None, hold_duration=None) -> bool:
            double_fn = getattr(self._simulator, "double_click", None)
            if not callable(double_fn):
                return False
            return bool(double_fn(int(x), int(y), button, interval=interval, hold_duration=hold_duration))

    try:
        button = mouse_op.get('button', 'left')
        action = normalize_click_action(mouse_op.get('action', '完整点击'))
        x, y = int(mouse_op['x']), int(mouse_op['y'])
        hold_duration = float(mouse_op.get('hold_duration', 0.0))
        if not math.isfinite(hold_duration) or hold_duration < 0:
            raise ValueError("鼠标保持时间无效")
        enable_auto_release = mouse_op.get('enable_auto_release', True)
        if not isinstance(enable_auto_release, bool):
            raise ValueError("自动弹起参数必须是布尔值")
    except (ValueError, TypeError, KeyError) as exc:
        logger.error(f"[组合键鼠标] 参数无效：{exc}")
        return False

    logger.debug(f"[组合键鼠标] 执行: {button}键 - {action} @ ({x}, {y}), 持续={hold_duration}s")

    try:
        adapter = _ComboMouseSimulatorAdapter(simulator)
        result = execute_simulator_click_action(
            simulator=adapter,
            x=x,
            y=y,
            button=button,
            click_action=action,
            clicks=1,
            interval=0.0,
            hold_duration=hold_duration,
            auto_release=enable_auto_release,
            mode_label="组合键鼠标",
            logger_obj=logger,
            require_atomic_hold=bool(getattr(adapter, "supports_atomic_click_hold", False)),
        )
        if result and action == '仅按下' and not enable_auto_release and hold_duration > 0:
            precise_sleep(hold_duration)
        return bool(result)

    except Exception as e:
        logger.error(f"[组合键鼠标] 执行异常: {e}")
        return False


def _execute_foreground_combo_mouse_action(
    foreground_input,
    x: Optional[int],
    y: Optional[int],
    button: str,
    action: str,
    hold_duration: float,
    enable_auto_release: bool,
    logger,
    execution_mode: str = "foreground",
    target_hwnd: Optional[int] = None,
) -> bool:
    """前台组合键鼠标统一入口：完整点击/双击仅走click_mouse。"""
    try:
        normalized_action = normalize_click_action(action)
        if not normalized_action:
            logger.error(f"[前台模式组合键] 未知鼠标动作: {action}")
            return False

        safe_hold_duration = float(hold_duration)
        if not math.isfinite(safe_hold_duration) or safe_hold_duration < 0:
            raise ValueError("鼠标保持时间无效")

        if x is None or y is None:
            safe_x, safe_y = _resolve_foreground_runtime_position(foreground_input)
        else:
            safe_x, safe_y = int(x), int(y)

        adapter = ForegroundDriverSimulatorAdapter(foreground_input)
        return bool(
            execute_simulator_click_action(
                simulator=adapter,
                x=safe_x,
                y=safe_y,
                button=button,
                click_action=normalized_action,
                clicks=1,
                interval=0.0,
                hold_duration=safe_hold_duration,
                auto_release=enable_auto_release,
                mode_label="前台模式组合键",
                logger_obj=logger,
                require_atomic_hold=True,
                execution_mode=execution_mode,
                target_hwnd=target_hwnd,
                task_type="模拟键盘操作",
            )
        )
    except Exception as e:
        logger.error(f"[前台模式组合键] 鼠标操作失败: {e}")
        return False


def _normalize_combo_action(action_raw: Any) -> str:
    """归一化可编辑组合键动作。"""
    if action_raw is None:
        return ""
    action = str(action_raw).strip().lower()
    if not action:
        return ""
    return _COMBO_ACTION_ALIASES.get(action, "")


def _normalize_combo_key_name(raw_key: Any) -> str:
    """归一化可编辑组合键的键名。"""
    key_name = str(raw_key or "").strip()
    if not key_name:
        return ""

    key_name = key_name.replace("＋", "+").replace(" ", "")
    lowered = key_name.lower()

    if lowered in _COMBO_KEY_ALIASES:
        return _COMBO_KEY_ALIASES[lowered]
    if key_name in _COMBO_KEY_ALIASES:
        return _COMBO_KEY_ALIASES[key_name]

    if key_name.endswith("键"):
        trim_key = key_name[:-1].strip()
        if trim_key in _COMBO_KEY_ALIASES:
            return _COMBO_KEY_ALIASES[trim_key]
        trim_lower = trim_key.lower()
        if trim_lower in _COMBO_KEY_ALIASES:
            return _COMBO_KEY_ALIASES[trim_lower]

    return lowered


def _normalize_key_mouse_action(action_raw: Any) -> str:
    """只接受现行执行方式。"""
    action_text = str(action_raw or KEY_MOUSE_ACTION_COMPLETE).strip()
    if action_text not in {KEY_MOUSE_ACTION_COMPLETE, KEY_MOUSE_ACTION_HOLD, KEY_MOUSE_ACTION_RELEASE}:
        raise ValueError("按键执行方式只能是 完整执行、只按下 或 只释放")
    return action_text


def _format_combo_wait_duration(duration: Any) -> str:
    """格式化 wait 语法的时长文本。"""
    safe_duration = _coerce_non_negative_duration(duration)
    formatted = f"{safe_duration:.3f}".rstrip("0").rstrip(".")
    return formatted or "0"


def _build_combo_wait_token(duration: Any = 0.0, duration_max: Any = None) -> str:
    """构建固定/随机等待步骤。"""
    safe_duration = _coerce_non_negative_duration(duration)
    if duration_max is None:
        if safe_duration <= 0:
            return ""
        return f"wait({_format_combo_wait_duration(safe_duration)})"

    safe_duration_max = _coerce_non_negative_duration(duration_max)
    if safe_duration_max < safe_duration:
        safe_duration, safe_duration_max = safe_duration_max, safe_duration
    if safe_duration_max <= 0:
        return ""
    return f"wait({_format_combo_wait_duration(safe_duration)},{_format_combo_wait_duration(safe_duration_max)})"


def _parse_combo_wait_token(token_body: str) -> Optional[Dict[str, Any]]:
    """解析等待步骤，支持 wait(0.2) / wait(0.1,0.3)。"""
    text = str(token_body or "").strip()
    if not text:
        return None

    match = _COMBO_WAIT_TOKEN_PATTERN.match(text)
    if not match:
        return None

    args_text = str(match.group("args") or match.group("plain") or "").strip()
    if not args_text:
        return None

    parts = [part.strip() for part in _COMBO_ARG_SPLIT_PATTERN.split(args_text) if part.strip()]
    if len(parts) == 1:
        duration = _coerce_non_negative_duration(parts[0])
        return {
            "duration": duration,
            "duration_min": duration,
            "duration_max": duration,
            "random": False,
        }
    if len(parts) == 2:
        duration_min = _coerce_non_negative_duration(parts[0])
        duration_max = _coerce_non_negative_duration(parts[1])
        if duration_max < duration_min:
            duration_min, duration_max = duration_max, duration_min
        return {
            "duration": duration_min,
            "duration_min": duration_min,
            "duration_max": duration_max,
            "random": True,
        }
    return None


def _parse_combo_key_function_token(token_body: str) -> Optional[Dict[str, Any]]:
    """解析命令式按键步骤，示例：key_down(ctrl) / key_press(a,3,0.2) / key_up(ctrl)。"""
    text = str(token_body or "").strip()
    if not text:
        return None

    match = _COMBO_KEY_FUNCTION_TOKEN_PATTERN.match(text)
    if not match:
        return None

    action_name = str(match.group("name") or "").strip().lower()
    action = _COMBO_KEY_FUNCTION_ACTIONS.get(action_name, "")
    if not action:
        return None

    args_text = str(match.group("args") or "").strip()
    if not args_text:
        return None

    parts = [part.strip() for part in _COMBO_ARG_SPLIT_PATTERN.split(args_text) if part.strip()]
    if len(parts) not in (1, 2, 3):
        return None

    key_name = _normalize_combo_key_name(parts[0])
    if not key_name:
        return None

    count = 1
    if len(parts) == 2:
        try:
            count = max(1, int(parts[1]))
        except Exception:
            return None

    repeat_interval = None
    if len(parts) == 3:
        try:
            count = max(1, int(parts[1]))
            repeat_interval = _coerce_non_negative_duration(parts[2])
        except Exception:
            return None

    return {"op": action, "key": key_name, "count": count, "repeat_interval": repeat_interval}


def _resolve_combo_repeat_interval(step: Dict[str, Any], default: float = _DEFAULT_COMBO_REPEAT_INTERVAL_SECONDS) -> float:
    """解析重复步骤之间的等待间隔。"""
    interval = step.get("repeat_interval")
    return default if interval is None else _coerce_non_negative_duration(interval)


def _resolve_combo_wait_duration(step: Dict[str, Any]) -> float:
    """解析等待步骤的实际执行时长。"""
    duration = _coerce_non_negative_duration(step.get("duration", 0.0))
    duration_min = _coerce_non_negative_duration(step.get("duration_min", duration))
    duration_max = _coerce_non_negative_duration(step.get("duration_max", duration_min))
    if duration_max < duration_min:
        duration_min, duration_max = duration_max, duration_min
    if coerce_bool(step.get("random", False)) or duration_max > duration_min:
        return random.uniform(duration_min, duration_max)
    return duration


def normalize_parameters(params: Dict[str, Any]) -> Dict[str, Any]:
    """校验现行参数，不在运行或面板入口转换旧按键格式。"""
    normalized_params = dict(params or {})
    input_type = str(normalized_params.get("input_type", "") or "").strip()
    if input_type not in {"文本输入", KEY_MOUSE_INPUT_TYPE}:
        raise ValueError("键盘输入类型只能是 文本输入 或 键盘按键，旧格式必须先经过工程转换")
    combo_sequence = str(normalized_params.get("combo_key_sequence_text", "") or "").strip()
    if "combo_key_action" in normalized_params:
        normalized_params["combo_key_action"] = _normalize_key_mouse_action(normalized_params["combo_key_action"])

    if combo_sequence:
        normalized_params["combo_key_sequence_text"] = combo_sequence

    return normalized_params


def normalize_panel_parameters(params: Dict[str, Any]) -> Dict[str, Any]:
    """供参数面板调用的参数归一化入口。"""
    if "combo_key_action" in params:
        raise ValueError("combo_key_action 是脚本执行参数，不属于卡片参数面板")
    return normalize_parameters(params)


def _split_combo_expression_steps(expression_text: str) -> List[str]:
    """拆分可编辑组合键步骤。"""
    text = str(expression_text or "").strip()
    if not text:
        return []

    normalized = text.replace("\r", "\n")
    if re.search(
        r"(按键|按下|按住|松开|弹起|抬起|释放|点按|点击|敲击|key_|key\s*\(|keydown|keyup|keypress|down|hold|up|release|press|tap|click|\*\s*\d+|mouse_|鼠标|\(\s*-?\d+\s*[,，]\s*-?\d+\s*\))",
        normalized,
        re.IGNORECASE,
    ):
        normalized = re.sub(r"\s*\+\s*", ",", normalized)

    parts: List[str] = []
    current_chars: List[str] = []
    paren_depth = 0
    split_chars = {",", "，", ";", "；", "\n"}

    for ch in normalized:
        if ch == "(":
            paren_depth += 1
            current_chars.append(ch)
            continue
        if ch == ")":
            if paren_depth > 0:
                paren_depth -= 1
            current_chars.append(ch)
            continue

        if ch in split_chars and paren_depth == 0:
            token = "".join(current_chars).strip()
            if token:
                parts.append(token)
            current_chars = []
            continue

        current_chars.append(ch)

    tail = "".join(current_chars).strip()
    if tail:
        parts.append(tail)

    if parts:
        return parts
    return [text]


def _build_mouse_action_identity(step: Dict[str, Any]) -> Tuple[Any, ...]:
    """构建鼠标逻辑动作标识，用于匹配按下/松开这一类成对鼠标步骤。"""
    return (
        str(step.get("button", "left") or "left").strip().lower(),
        int(step.get("x", 0) or 0) if step.get("x") is not None else None,
        int(step.get("y", 0) or 0) if step.get("y") is not None else None,
        bool(step.get("use_current_position", False)),
    )


def _combo_limit_exceeded(limit: Optional[int], value: int) -> bool:
    """None 表示不限制；正整数表示启用上限。"""
    return isinstance(limit, int) and limit > 0 and value > limit


def _count_recorded_key_actions(events: List[Dict[str, Any]]) -> int:
    """统计录制中的按键动作数，仅按 key down 计数。"""
    total = 0
    for event in events:
        if str(event.get("type", "") or "").strip().lower() != "key":
            continue
        if str(event.get("event_type", "") or "").strip().lower() == "down":
            total += 1
    return total


def _validate_key_mouse_operation_limits(operations: List[Dict[str, Any]]) -> None:
    """按配置校验按键/鼠标动作数量；默认不限制，保留入口便于以后按需收紧。"""
    active_keys: Set[str] = set()
    key_action_count = 0
    mouse_action_count = 0
    pending_mouse_down: Set[Tuple[Any, ...]] = set()

    for step in operations:
        op = str(step.get("op", "") or "").strip().lower()
        key_name = str(step.get("key", "") or "").strip()
        count = max(1, int(step.get("count", 1) or 1))

        if op == "down":
            if key_name:
                key_action_count += 1
                if _combo_limit_exceeded(_MAX_KEY_MOUSE_KEYS, key_action_count):
                    raise ValueError(f"键盘按键最多只允许 {_MAX_KEY_MOUSE_KEYS} 个按键动作")
                active_keys.add(key_name)
                if _combo_limit_exceeded(_MAX_KEY_MOUSE_KEYS, len(active_keys)):
                    raise ValueError(f"键盘按键最多同时按下 {_MAX_KEY_MOUSE_KEYS} 个键")
            continue

        if op == "up":
            if key_name:
                active_keys.discard(key_name)
            continue

        if op == "press":
            key_action_count += count
            if _combo_limit_exceeded(_MAX_KEY_MOUSE_KEYS, key_action_count):
                raise ValueError(f"键盘按键最多只允许 {_MAX_KEY_MOUSE_KEYS} 个按键动作")
            current_key_count = len(active_keys) + (0 if key_name in active_keys else 1)
            if _combo_limit_exceeded(_MAX_KEY_MOUSE_KEYS, current_key_count):
                raise ValueError(f"键盘按键最多同时按下 {_MAX_KEY_MOUSE_KEYS} 个键")
            continue

        if op == "mouse_wheel":
            mouse_action_count += count
            if _combo_limit_exceeded(_MAX_KEY_MOUSE_MOUSE_ACTIONS, mouse_action_count):
                raise ValueError(f"键盘按键最多只允许 {_MAX_KEY_MOUSE_MOUSE_ACTIONS} 个鼠标动作")
            continue

        if op not in ("mouse_action", "mouse_click"):
            continue

        action_count = count
        mouse_action = normalize_click_action(step.get("mouse_action", "完整点击"))
        identity = _build_mouse_action_identity(step)

        if mouse_action == "仅按下":
            mouse_action_count += action_count
            pending_mouse_down.add(identity)
        elif mouse_action == "仅松开":
            if identity in pending_mouse_down:
                pending_mouse_down.discard(identity)
            else:
                mouse_action_count += action_count
        else:
            mouse_action_count += action_count

        if _combo_limit_exceeded(_MAX_KEY_MOUSE_MOUSE_ACTIONS, mouse_action_count):
            raise ValueError(f"键盘按键最多只允许 {_MAX_KEY_MOUSE_MOUSE_ACTIONS} 个鼠标动作")


def _validate_key_operation_pairs(operations: List[Dict[str, Any]]) -> None:
    """显式按下的键必须有对应松开，避免工作流执行后残留按下状态。"""
    pending_key_down_counts: Dict[str, int] = {}

    for step in operations:
        op = str(step.get("op", "") or "").strip().lower()
        if op not in ("down", "up"):
            continue

        key_name = str(step.get("key", "") or "").strip().lower()
        if not key_name:
            continue

        if op == "down":
            pending_key_down_counts[key_name] = int(pending_key_down_counts.get(key_name, 0) or 0) + 1
            continue

        current_count = int(pending_key_down_counts.get(key_name, 0) or 0)
        if current_count <= 0:
            raise ValueError(f"按键 {key_name}(松开) 缺少对应的 {key_name}(按下)")
        if current_count == 1:
            pending_key_down_counts.pop(key_name, None)
        else:
            pending_key_down_counts[key_name] = current_count - 1

    unpaired_keys = [key_name for key_name, count in pending_key_down_counts.items() if int(count or 0) > 0]
    if unpaired_keys:
        raise ValueError(
            "显式按下的按键必须配套松开："
            + ", ".join(f"{key_name}(按下)->{key_name}(松开)" for key_name in unpaired_keys)
        )


def _build_combo_chord_operations(keys: List[str]) -> List[Dict[str, Any]]:
    """将 ctrl+shift+a 形式展开为按下/松开序列。"""
    operations: List[Dict[str, Any]] = []
    for key_name in keys:
        operations.append({"op": "down", "key": key_name, "count": 1})
    for key_name in reversed(keys):
        operations.append({"op": "up", "key": key_name, "count": 1})
    return operations


def _resolve_combo_mouse_prefix_action(prefix_raw: str) -> Optional[Tuple[str, str]]:
    """解析鼠标前缀，返回 (button, click_action)。"""
    prefix = str(prefix_raw or "").strip().lower().replace(" ", "").replace("-", "_")
    if not prefix:
        return None

    direct_button = _COMBO_MOUSE_PREFIX_ALIASES.get(prefix)
    if direct_button:
        return direct_button, "完整点击"

    for suffix, click_action in _COMBO_MOUSE_ACTION_SUFFIX_ITEMS:
        if not prefix.endswith(suffix):
            continue
        base = prefix[: -len(suffix)].strip()
        if not base:
            continue
        button = _COMBO_MOUSE_PREFIX_ALIASES.get(base)
        if button:
            return button, click_action

    return None


def _parse_combo_mouse_action_token(token_body: str) -> Optional[Dict[str, Any]]:
    """解析鼠标步骤，支持单击/双击/按下/松开，示例：mouse_left_down(100,200)。"""
    text = str(token_body or "").strip()
    if not text or "(" not in text or not text.endswith(")"):
        return None

    left_paren = text.find("(")
    prefix = text[:left_paren].strip()
    if not prefix:
        return None

    parsed_prefix = _resolve_combo_mouse_prefix_action(prefix)
    if not parsed_prefix:
        return None
    button, click_action = parsed_prefix

    inside = text[left_paren + 1 : -1].strip()
    if not inside:
        return {
            "button": button,
            "click_action": click_action,
            "x": None,
            "y": None,
            "use_current_position": True,
        }

    parts = [part.strip() for part in _COMBO_ARG_SPLIT_PATTERN.split(inside)]
    if len(parts) != 2:
        return None
    try:
        x_value = int(parts[0])
        y_value = int(parts[1])
    except Exception:
        return None

    if x_value == 0 and y_value == 0:
        return {
            "button": button,
            "click_action": click_action,
            "x": None,
            "y": None,
            "use_current_position": True,
        }

    return {
        "button": button,
        "click_action": click_action,
        "x": x_value,
        "y": y_value,
        "use_current_position": False,
    }


def _parse_combo_mouse_wheel_token(token_body: str) -> Optional[Dict[str, Any]]:
    """解析滚轮步骤，示例：mouse_wheel_up(100,200) / mouse_wheel_down(100,200,3)。"""
    text = str(token_body or "").strip()
    if not text or "(" not in text or not text.endswith(")"):
        return None

    left_paren = text.find("(")
    prefix = text[:left_paren].strip().lower().replace(" ", "").replace("-", "_")
    if not prefix:
        return None

    direction = _COMBO_MOUSE_WHEEL_PREFIX_ALIASES.get(prefix)
    if not direction:
        return None

    inside = text[left_paren + 1 : -1].strip()
    if not inside:
        return {
            "direction": direction,
            "x": None,
            "y": None,
            "wheel_clicks": 1,
            "use_current_position": True,
        }

    parts = [part.strip() for part in _COMBO_ARG_SPLIT_PATTERN.split(inside) if part.strip()]
    if len(parts) == 1:
        try:
            wheel_clicks = max(1, int(parts[0]))
        except Exception:
            return None
        return {
            "direction": direction,
            "x": None,
            "y": None,
            "wheel_clicks": wheel_clicks,
            "use_current_position": True,
        }

    if len(parts) not in (2, 3):
        return None

    try:
        x_value = int(parts[0])
        y_value = int(parts[1])
        wheel_clicks = int(parts[2]) if len(parts) == 3 else 1
    except Exception:
        return None

    wheel_clicks = max(1, wheel_clicks)
    if x_value == 0 and y_value == 0:
        return {
            "direction": direction,
            "x": None,
            "y": None,
            "wheel_clicks": wheel_clicks,
            "use_current_position": True,
        }
    return {
        "direction": direction,
        "x": x_value,
        "y": y_value,
        "wheel_clicks": wheel_clicks,
        "use_current_position": False,
    }


def _normalize_recorded_combo_key_name(raw_key: Any) -> str:
    """标准化录制到的键名。"""
    key_text = str(raw_key or "").strip().lower()
    if not key_text:
        return ""

    key_text = key_text.replace("＋", "+")
    key_text = _RECORDED_KEY_ALIASES.get(key_text, key_text)
    if key_text.startswith("num "):
        maybe_num = key_text.replace("num ", "num")
        if maybe_num:
            key_text = maybe_num

    return _normalize_combo_key_name(key_text)


def _resolve_recorded_combo_key_name(event: Any) -> str:
    """从录制事件读取键名；缺少键名时保持未知，不猜测扫描码。"""
    return _normalize_recorded_combo_key_name(event.name)


def _format_recorded_mouse_token(event: Dict[str, Any]) -> str:
    """将录制到的鼠标事件转成文本步骤。"""
    button = str(event.get("button", "left") or "left").strip().lower()
    action = str(event.get("action", "完整点击") or "完整点击").strip()
    prefix_map = {
        "left": "mouse_left",
        "right": "mouse_right",
        "middle": "mouse_middle",
    }
    prefix = prefix_map[button]
    action = normalize_click_action(action)
    if action == "双击":
        prefix = f"{prefix}_double"
    elif action == "仅按下":
        prefix = f"{prefix}_down"
    elif action == "仅松开":
        prefix = f"{prefix}_up"

    x_value = event.get("x", None)
    y_value = event.get("y", None)
    if x_value is None or y_value is None:
        return f"{prefix}()"
    return f"{prefix}({int(x_value)},{int(y_value)})"


def _recording_timestamp() -> float:
    """录制专用单调时间戳，避免系统时间调整影响间隔。"""
    return time.perf_counter()


def _get_recorded_event_time(event: Dict[str, Any]) -> float:
    value = float(event['time'])
    if not math.isfinite(value):
        raise ValueError("录制事件时间无效")
    return value


def _get_recorded_event_end_time(event: Dict[str, Any]) -> float:
    value = float(event['end_time'])
    if not math.isfinite(value) or value < _get_recorded_event_time(event):
        raise ValueError("录制事件结束时间无效")
    return value


def _append_recorded_delay_token(result_parts: List[str], delay_seconds: float) -> None:
    """将相邻录制动作之间的真实间隔写成 wait(...)。"""
    safe_delay = float(delay_seconds)
    if not math.isfinite(safe_delay) or safe_delay < 0:
        raise ValueError("录制动作间隔无效")
    if safe_delay < _RECORDED_DELAY_MIN_SECONDS:
        return
    wait_token = _build_combo_wait_token(safe_delay)
    if wait_token:
        result_parts.append(wait_token)


def _build_recorded_combo_sequence(events: List[Dict[str, Any]]) -> str:
    """将录制到的键盘/鼠标事件转成可编辑步骤文本。"""
    if not events:
        return ""

    tokens: List[Dict[str, Any]] = []
    index = 0
    total = len(events)

    while index < total:
        event = events[index]
        event_kind = str(event.get("type", "") or "").strip().lower()
        if event_kind == "mouse":
            tokens.append(dict(event))
            index += 1
            continue

        event_type = str(event.get("event_type", "") or "").strip().lower()
        key_name = str(event.get("key", "") or "").strip()
        if not key_name:
            index += 1
            continue

        if event_type == "down" and index + 1 < total:
            next_event = events[index + 1]
            if (
                str(next_event.get("type", "") or "").strip().lower() == "key"
                and str(next_event.get("event_type", "") or "").strip().lower() == "up"
                and str(next_event.get("key", "") or "").strip() == key_name
            ):
                down_time = _get_recorded_event_time(event)
                up_time = _get_recorded_event_time(next_event)
                hold_seconds = 0.0
                if down_time is not None and up_time is not None:
                    hold_seconds = max(0.0, float(up_time) - float(down_time))
                if hold_seconds >= _RECORDED_LONG_PRESS_SECONDS:
                    tokens.append({"type": "key", "op": "down", "key": key_name, "time": down_time, "end_time": down_time})
                    tokens.append({"type": "key", "op": "up", "key": key_name, "time": up_time, "end_time": up_time})
                else:
                    tokens.append({"type": "key", "op": "press", "key": key_name, "time": down_time, "end_time": up_time})
                index += 2
                continue

        if event_type == "down":
            event_time = _get_recorded_event_time(event)
            tokens.append({"type": "key", "op": "down", "key": key_name, "time": event_time, "end_time": event_time})
        elif event_type == "up":
            event_time = _get_recorded_event_time(event)
            tokens.append({"type": "key", "op": "up", "key": key_name, "time": event_time, "end_time": event_time})
        index += 1

    result_parts: List[str] = []
    index = 0
    total = len(tokens)
    previous_end_time: Optional[float] = None

    def append_timed_part(token: Dict[str, Any], part: str) -> None:
        nonlocal previous_end_time
        if not part:
            return
        start_time = _get_recorded_event_time(token)
        if previous_end_time is not None and start_time is not None:
            _append_recorded_delay_token(result_parts, start_time - previous_end_time)
        result_parts.append(part)
        end_time = _get_recorded_event_end_time(token)
        if end_time is not None:
            previous_end_time = end_time

    while index < total:
        token = tokens[index]
        token_type = str(token.get("type", "") or "").strip().lower()
        if token_type == "mouse":
            append_timed_part(token, _format_recorded_mouse_token(token))
            index += 1
            continue

        op = token.get("op", "")
        key_name = token.get("key", "")
        if not key_name:
            index += 1
            continue

        if op == "press":
            append_timed_part(token, key_name)
            index += 1
            continue

        if op == "down":
            append_timed_part(token, f"{key_name}(按下)")
        elif op == "up":
            append_timed_part(token, f"{key_name}(松开)")
        index += 1

    return ", ".join(result_parts)


def _update_combo_record_button_text(parameter_panel, recording: bool) -> None:
    """更新录制按钮文案。"""
    if not parameter_panel:
        return
    button_widget = None
    if hasattr(parameter_panel, "widgets"):
        button_widget = parameter_panel.widgets.get("combo_key_sequence_record")
    if button_widget and hasattr(button_widget, "setText"):
        button_widget.setText("停止录制按键" if recording else "开始录制按键")


def _apply_recorded_combo_sequence(parameter_panel, combo_sequence: str) -> None:
    """将录制结果写回参数面板。"""
    if not parameter_panel:
        return

    try:
        parameter_panel.current_parameters["combo_key_sequence_text"] = combo_sequence
    except Exception:
        pass

    try:
        if hasattr(parameter_panel, "widgets"):
            text_widget = parameter_panel.widgets.get("combo_key_sequence_text")
            if text_widget and hasattr(text_widget, "setPlainText"):
                text_widget.setPlainText(combo_sequence)
            elif text_widget and hasattr(text_widget, "setText"):
                text_widget.setText(combo_sequence)
    except Exception:
        pass

    try:
        card_id = getattr(parameter_panel, "current_card_id", None)
        if card_id is not None and hasattr(parameter_panel, "parameters_changed"):
            parameter_panel.parameters_changed.emit(card_id, {"combo_key_sequence_text": combo_sequence})
    except Exception:
        pass


def _cleanup_combo_sequence_recording(parameter_panel, keyboard_module=None, mouse_module=None):
    setattr(parameter_panel, '_combo_seq_recording_active', False)
    errors = []
    keyboard_hook = getattr(parameter_panel, '_combo_seq_recording_hook', None)
    if keyboard_hook is not None:
        try:
            if keyboard_module is None:
                raise RuntimeError('键盘录制接口不可用，无法卸载钩子')
            try:
                keyboard_module.unhook(keyboard_hook)
            except (KeyError, ValueError):
                pass
        except Exception as error:
            errors.append(error)
        else:
            setattr(parameter_panel, '_combo_seq_recording_hook', None)
    remaining = []
    for hook in list(getattr(parameter_panel, '_combo_seq_recording_mouse_hooks', []) or []):
        try:
            if mouse_module is None:
                raise RuntimeError('鼠标录制接口不可用，无法卸载钩子')
            try:
                mouse_module.unhook(hook)
            except (KeyError, ValueError):
                pass
        except Exception as error:
            remaining.append(hook)
            errors.append(error)
    setattr(parameter_panel, '_combo_seq_recording_mouse_hooks', remaining)
    for name, value in (('_combo_seq_recording_events', []), ('_combo_seq_recording_pressed_keys', set()), ('_combo_seq_recording_ignored_keys', set()), ('_combo_seq_recording_last_mouse', None), ('_combo_seq_block_global_record_hotkey', False)):
        setattr(parameter_panel, name, value)
    if errors:
        raise RuntimeError(f'键鼠录制钩子卸载失败：{errors[0]}')


def should_ignore_recorded_mouse_click(
    *,
    on_qt_widget: bool,
    hit_pid: int,
    app_pid: int,
    hit_is_target_tree: bool,
) -> bool:
    """录制时忽略点在本程序界面上的点击，避免把「停止录制」写进序列。"""
    if hit_is_target_tree:
        return False
    if bool(on_qt_widget):
        return True
    return int(app_pid or 0) > 0 and int(hit_pid or 0) == int(app_pid)


def _hwnd_is_in_tree(hwnd: int, root: int) -> bool:
    hwnd = int(hwnd or 0)
    root = int(root or 0)
    if hwnd <= 0 or root <= 0:
        return False
    if hwnd == root:
        return True
    try:
        hit_root = int(win32gui.GetAncestor(hwnd, win32con.GA_ROOT) or 0)
        target_root = int(win32gui.GetAncestor(root, win32con.GA_ROOT) or root)
        if hit_root and target_root and hit_root == target_root:
            return True
    except Exception:
        pass
    current = hwnd
    seen = set()
    while current and current not in seen:
        if current == root:
            return True
        seen.add(current)
        try:
            current = int(win32gui.GetParent(current) or 0)
        except Exception:
            break
    return False


def _cursor_hit_hwnd() -> int:
    try:
        screen_x, screen_y = win32api.GetCursorPos()
        return int(win32gui.WindowFromPoint((int(screen_x), int(screen_y))) or 0)
    except Exception:
        return 0


def _window_process_id(hwnd: int) -> int:
    hwnd = int(hwnd or 0)
    if hwnd <= 0:
        return 0
    try:
        _thread_id, process_id = win32process.GetWindowThreadProcessId(hwnd)
        return int(process_id or 0)
    except Exception:
        return 0


def _cursor_is_on_qt_widget() -> bool:
    try:
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return False
        return app.widgetAt(QCursor.pos()) is not None
    except Exception:
        return False


def _should_ignore_combo_record_mouse(target_hwnd: Optional[int]) -> bool:
    hit_hwnd = _cursor_hit_hwnd()
    return should_ignore_recorded_mouse_click(
        on_qt_widget=_cursor_is_on_qt_widget(),
        hit_pid=_window_process_id(hit_hwnd),
        app_pid=int(os.getpid()),
        hit_is_target_tree=_hwnd_is_in_tree(hit_hwnd, int(target_hwnd or 0)),
    )


def _resolve_recorded_mouse_position(target_hwnd: Optional[int]) -> Tuple[int, int]:
    """获取录制时鼠标坐标；获取或客户区转换失败时不记录伪造坐标。"""
    screen_x, screen_y = win32api.GetCursorPos()
    if target_hwnd:
        client_x, client_y = win32gui.ScreenToClient(int(target_hwnd), (int(screen_x), int(screen_y)))
        return int(client_x), int(client_y)
    return int(screen_x), int(screen_y)


def toggle_combo_key_sequence_record(params: Dict[str, Any], **kwargs) -> None:
    """开始/停止键盘按键录制，可记录多段按键与鼠标单击/双击动作。"""
    parameter_panel = kwargs.get("parameter_panel")
    if not parameter_panel:
        logger.warning("键盘按键录制失败：参数面板不可用")
        return

    try:
        import keyboard
        import mouse
    except Exception:
        logger.error("键盘按键录制失败：监听组件不可用")
        return

    target_hwnd = kwargs.get("target_hwnd")
    is_recording = bool(getattr(parameter_panel, "_combo_seq_recording_active", False))

    if is_recording:
        recorded_events = list(getattr(parameter_panel, "_combo_seq_recording_events", []))
        _cleanup_combo_sequence_recording(parameter_panel, keyboard, mouse)
        combo_sequence = _build_recorded_combo_sequence(recorded_events)
        _apply_recorded_combo_sequence(parameter_panel, combo_sequence)
        _update_combo_record_button_text(parameter_panel, False)
        logger.info(f"键盘按键录制已停止，记录步骤数: {len(recorded_events)}")
        return

    recorded_events: List[Dict[str, Any]] = []
    pressed_keys: Set[str] = set()
    ignored_keys: Set[str] = set()
    setattr(parameter_panel, "_combo_seq_recording_events", recorded_events)
    setattr(parameter_panel, "_combo_seq_recording_pressed_keys", pressed_keys)
    setattr(parameter_panel, "_combo_seq_recording_ignored_keys", ignored_keys)
    setattr(parameter_panel, "_combo_seq_recording_last_mouse", None)

    def _on_key_event(event):
        try:
            event_time = _recording_timestamp()
            event_type = str(getattr(event, "event_type", "") or "").strip().lower()
            if event_type not in ("down", "up"):
                return
            key_name = _resolve_recorded_combo_key_name(event)
            if not key_name:
                return
            if event_type == "down":
                if key_name in pressed_keys:
                    return
                if _combo_limit_exceeded(_MAX_KEY_MOUSE_KEYS, _count_recorded_key_actions(recorded_events)):
                    ignored_keys.add(key_name)
                    return
                pressed_keys.add(key_name)
                recorded_events.append({"type": "key", "event_type": "down", "key": key_name, "time": event_time})
                return
            if key_name in ignored_keys:
                ignored_keys.discard(key_name)
                return
            if key_name in pressed_keys:
                pressed_keys.remove(key_name)
            recorded_events.append({"type": "key", "event_type": "up", "key": key_name, "time": event_time})
        except Exception:
            return

    def _on_mouse_event(button_name: str):
        try:
            if _should_ignore_combo_record_mouse(target_hwnd):
                return
            now = _recording_timestamp()
            x_value, y_value = _resolve_recorded_mouse_position(target_hwnd)
            last_mouse = getattr(parameter_panel, "_combo_seq_recording_last_mouse", None)

            if isinstance(last_mouse, dict):
                event_index = int(last_mouse.get("event_index", -1) or -1)
                if event_index == len(recorded_events) - 1 and 0 <= event_index < len(recorded_events):
                    same_button = str(last_mouse.get("button", "") or "").strip().lower() == button_name
                    delta_time = now - float(last_mouse.get("time", 0.0) or 0.0)
                    delta_x = abs(int(last_mouse.get("x", 0) or 0) - x_value)
                    delta_y = abs(int(last_mouse.get("y", 0) or 0) - y_value)
                    if same_button and delta_time <= _RECORDED_DOUBLE_CLICK_SECONDS and delta_x <= _RECORDED_DOUBLE_CLICK_DISTANCE and delta_y <= _RECORDED_DOUBLE_CLICK_DISTANCE:
                        first_event = recorded_events[event_index]
                        first_time = _get_recorded_event_time(first_event)
                        recorded_events[event_index] = {
                            "type": "mouse",
                            "button": button_name,
                            "action": "双击",
                            "x": x_value,
                            "y": y_value,
                            "time": first_time,
                            "end_time": now,
                        }
                        setattr(
                            parameter_panel,
                            "_combo_seq_recording_last_mouse",
                            {
                                "button": button_name,
                                "time": now,
                                "x": x_value,
                                "y": y_value,
                                "event_index": event_index,
                            },
                        )
                        return

            recorded_events.append(
                {
                    "type": "mouse",
                    "button": button_name,
                    "action": "完整点击",
                    "x": x_value,
                    "y": y_value,
                    "time": now,
                    "end_time": now,
                }
            )
            setattr(
                parameter_panel,
                "_combo_seq_recording_last_mouse",
                {
                    "button": button_name,
                    "time": now,
                    "x": x_value,
                    "y": y_value,
                    "event_index": len(recorded_events) - 1,
                },
            )
        except Exception:
            return

    keyboard_hook = None
    mouse_hooks: List[Any] = []
    try:
        keyboard_hook = keyboard.hook(_on_key_event, suppress=False)
        for button in ('left', 'right', 'middle'):
            mouse_hooks.append(mouse.on_button(lambda selected=button: _on_mouse_event(selected), buttons=(button,), types=('down',)))
    except Exception as error:
        setattr(parameter_panel, '_combo_seq_recording_hook', keyboard_hook)
        setattr(parameter_panel, '_combo_seq_recording_mouse_hooks', mouse_hooks)
        _cleanup_combo_sequence_recording(parameter_panel, keyboard, mouse)
        raise RuntimeError(f'启动键鼠录制失败：{error}') from error

    setattr(parameter_panel, "_combo_seq_recording_active", True)
    setattr(parameter_panel, "_combo_seq_recording_hook", keyboard_hook)
    setattr(parameter_panel, "_combo_seq_recording_mouse_hooks", mouse_hooks)
    setattr(parameter_panel, "_combo_seq_block_global_record_hotkey", True)
    _update_combo_record_button_text(parameter_panel, True)
    logger.info("键盘按键录制已开始")


def insert_combo_mouse_action_from_picker(params: Dict[str, Any], **kwargs) -> None:
    """统一插入鼠标动作：点击后弹出动作列表供选择。"""
    parameter_panel = kwargs.get("parameter_panel")
    if not parameter_panel:
        logger.warning("插入组合步骤失败：参数面板不可用")
        return

    prefix = _pick_combo_mouse_action_prefix(parameter_panel)
    if not prefix:
        return
    _insert_combo_step_from_picker(parameter_panel, prefix)


def _pick_combo_mouse_action_prefix(parameter_panel) -> Optional[str]:
    """以项目风格分组按钮面板选择要插入的鼠标动作前缀。"""
    try:
        from PySide6.QtWidgets import (
            QDialog,
            QVBoxLayout,
            QHBoxLayout,
            QLabel,
            QPushButton,
            QGroupBox,
            QWidget,
            QGridLayout,
        )
    except Exception:
        logger.error("插入鼠标动作失败：UI组件不可用")
        return None

    dialog = QDialog(parameter_panel)
    dialog.setWindowTitle("插入鼠标动作")
    dialog.setMinimumSize(560, 340)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(14, 14, 14, 14)
    layout.setSpacing(10)

    tip = QLabel("点击动作按钮即可插入；坐标为 0,0 时会使用当前鼠标位置。")
    tip.setWordWrap(True)
    layout.addWidget(tip)

    click_group = QGroupBox("点击动作", dialog)
    click_wrap = QWidget(click_group)
    click_grid = QGridLayout(click_wrap)
    click_grid.setContentsMargins(8, 10, 8, 8)
    click_grid.setHorizontalSpacing(8)
    click_grid.setVerticalSpacing(8)

    click_group_layout = QVBoxLayout(click_group)
    click_group_layout.setContentsMargins(0, 0, 0, 0)
    click_group_layout.addWidget(click_wrap)

    wheel_group = QGroupBox("滚轮动作", dialog)
    wheel_wrap = QWidget(wheel_group)
    wheel_grid = QGridLayout(wheel_wrap)
    wheel_grid.setContentsMargins(8, 10, 8, 8)
    wheel_grid.setHorizontalSpacing(8)
    wheel_grid.setVerticalSpacing(8)

    wheel_group_layout = QVBoxLayout(wheel_group)
    wheel_group_layout.setContentsMargins(0, 0, 0, 0)
    wheel_group_layout.addWidget(wheel_wrap)

    layout.addWidget(click_group)
    layout.addWidget(wheel_group)

    selected_prefix: Dict[str, Optional[str]] = {"value": None}

    def _insert_prefix(prefix: str):
        selected_prefix["value"] = str(prefix or "").strip()
        if selected_prefix["value"]:
            dialog.accept()

    click_rows: List[Tuple[str, List[Tuple[str, str]]]] = [
        ("左键", [("单击", "mouse_left"), ("双击", "mouse_left_double"), ("按下", "mouse_left_down"), ("松开", "mouse_left_up")]),
        ("右键", [("单击", "mouse_right"), ("双击", "mouse_right_double"), ("按下", "mouse_right_down"), ("松开", "mouse_right_up")]),
        ("中键", [("单击", "mouse_middle"), ("双击", "mouse_middle_double"), ("按下", "mouse_middle_down"), ("松开", "mouse_middle_up")]),
    ]

    for row_idx, (row_title, actions) in enumerate(click_rows):
        title_btn = QPushButton(row_title, click_wrap)
        title_btn.setEnabled(False)
        title_btn.setProperty("class", "secondary")
        title_btn.setMinimumHeight(30)
        click_grid.addWidget(title_btn, row_idx, 0)

        for col_idx, (label, prefix) in enumerate(actions, start=1):
            action_btn = QPushButton(label, click_wrap)
            action_btn.setProperty("class", "primary")
            action_btn.setMinimumHeight(30)
            action_btn.clicked.connect(lambda _checked=False, p=prefix: _insert_prefix(p))
            click_grid.addWidget(action_btn, row_idx, col_idx)

    wheel_actions: List[Tuple[str, str]] = [
        ("上滚", "mouse_wheel_up"),
        ("下滚", "mouse_wheel_down"),
    ]
    for col_idx, (label, prefix) in enumerate(wheel_actions):
        action_btn = QPushButton(label, wheel_wrap)
        action_btn.setProperty("class", "primary")
        action_btn.setMinimumHeight(34)
        action_btn.clicked.connect(lambda _checked=False, p=prefix: _insert_prefix(p))
        wheel_grid.addWidget(action_btn, 0, col_idx)

    button_layout = QHBoxLayout()
    button_layout.addStretch(1)
    cancel_btn = QPushButton("取消", dialog)
    cancel_btn.setProperty("class", "danger")
    cancel_btn.setMinimumHeight(34)
    cancel_btn.clicked.connect(dialog.reject)
    button_layout.addWidget(cancel_btn)
    layout.addLayout(button_layout)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return selected_prefix.get("value")


def _insert_combo_step_from_picker(parameter_panel, prefix: str) -> None:
    """将坐标导入为指定步骤前缀。"""
    if not parameter_panel:
        logger.warning("插入组合步骤失败：参数面板不可用")
        return

    current_params = getattr(parameter_panel, "current_parameters", {}) or {}
    try:
        x_value = int(current_params.get("combo_seq_mouse_x", 0) or 0)
        y_value = int(current_params.get("combo_seq_mouse_y", 0) or 0)
    except Exception:
        x_value, y_value = 0, 0

    use_current_position = (x_value == 0 and y_value == 0)
    if use_current_position:
        token = f"{prefix}()"
    else:
        token = f"{prefix}({x_value},{y_value})"
    existing_text = str(current_params.get("combo_key_sequence_text", "") or "").strip()
    try:
        if hasattr(parameter_panel, "widgets"):
            text_widget = parameter_panel.widgets.get("combo_key_sequence_text")
            if text_widget and hasattr(text_widget, "toPlainText"):
                existing_text = str(text_widget.toPlainText() or "").strip()
            elif text_widget and hasattr(text_widget, "text"):
                existing_text = str(text_widget.text() or "").strip()
    except Exception:
        pass
    if existing_text:
        merged_text = f"{existing_text}, {token}"
    else:
        merged_text = token

    _apply_recorded_combo_sequence(parameter_panel, merged_text)
    logger.info(f"已插入组合步骤: {token}")


def _parse_combo_expression(
    expression: Any,
    *,
    require_matched_pairs: bool = True,
) -> List[Dict[str, Any]]:
    """解析可编辑组合键表达式。"""
    expression_text = str(expression or "").strip()
    if not expression_text:
        return []

    parsed_operations: List[Dict[str, Any]] = []
    step_texts = _split_combo_expression_steps(expression_text)

    for raw_step in step_texts:
        step = raw_step.strip()
        if not step:
            continue

        repeat_count = 1
        repeat_interval: Optional[float] = None
        body = step

        repeat_match = _COMBO_REPEAT_SUFFIX_PATTERN.match(body)
        if repeat_match:
            body = str(repeat_match.group("body") or "").strip()
            repeat_count = int(repeat_match.group("count") or 1)
            if repeat_count <= 0:
                raise ValueError(f"无效重复次数：{step}")
            interval_text = str(repeat_match.group("interval") or "").strip()
            if interval_text:
                repeat_interval = _coerce_non_negative_duration(
                    interval_text,
                )

        wait_info = _parse_combo_wait_token(body)
        if wait_info:
            parsed_operations.append(
                {
                    "op": "wait",
                    "duration": wait_info["duration"],
                    "duration_min": wait_info["duration_min"],
                    "duration_max": wait_info["duration_max"],
                    "random": bool(wait_info.get("random", False)),
                    "count": repeat_count,
                }
            )
            continue

        key_function_info = _parse_combo_key_function_token(body)
        if key_function_info:
            action = str(key_function_info.get("op") or "press")
            inner_count = max(1, int(key_function_info.get("count", 1) or 1))
            total_count = repeat_count * inner_count
            step_repeat_interval = (
                repeat_interval
                if repeat_interval is not None
                else key_function_info.get("repeat_interval", None)
            )
            if action in ("down", "up") and total_count > 1:
                raise ValueError(f"按下/松开步骤不支持重复次数：{step}")
            parsed_operations.append(
                {
                    "op": action,
                    "key": str(key_function_info.get("key") or ""),
                    "count": total_count,
                    "repeat_interval": step_repeat_interval,
                }
            )
            continue

        mouse_wheel_info = _parse_combo_mouse_wheel_token(body)
        if mouse_wheel_info:
            parsed_operations.append(
                {
                    "op": "mouse_wheel",
                    "direction": str(mouse_wheel_info["direction"]),
                    "x": mouse_wheel_info.get("x"),
                    "y": mouse_wheel_info.get("y"),
                    "wheel_clicks": int(mouse_wheel_info["wheel_clicks"]),
                    "use_current_position": bool(mouse_wheel_info.get("use_current_position", False)),
                    "count": repeat_count,
                    "repeat_interval": repeat_interval,
                }
            )
            continue

        mouse_action_info = _parse_combo_mouse_action_token(body)
        if mouse_action_info:
            click_action = str(mouse_action_info.get("click_action") or "完整点击")
            if click_action in ("仅按下", "仅松开") and repeat_count > 1:
                raise ValueError(f"鼠标按下/松开步骤不支持重复次数：{step}")
            parsed_operations.append(
                {
                    "op": "mouse_action",
                    "button": mouse_action_info["button"],
                    "mouse_action": click_action,
                    "x": mouse_action_info.get("x"),
                    "y": mouse_action_info.get("y"),
                    "use_current_position": bool(mouse_action_info.get("use_current_position", False)),
                    "count": repeat_count,
                    "repeat_interval": repeat_interval,
                }
            )
            continue

        action = ""
        key_body = body
        action_match = _COMBO_ACTION_SUFFIX_PATTERN.match(body)
        if action_match:
            key_body = str(action_match.group("key") or "").strip()
            action_raw = action_match.group("act1") or action_match.group("act2") or ""
            action = _normalize_combo_action(action_raw)
            if not action:
                raise ValueError(f"无效动作：{step}")
        else:
            for action_suffix in ("完整按键", "按下", "按住", "松开", "弹起", "抬起", "释放", "完整", "点按", "点击", "敲击"):
                if body.endswith(action_suffix):
                    key_body = body[: -len(action_suffix)].strip()
                    action = _normalize_combo_action(action_suffix)
                    break

        if "+" in key_body and not action:
            chord_keys = []
            for token in key_body.split("+"):
                normalized_key = _normalize_combo_key_name(token)
                if not normalized_key:
                    raise ValueError(f"无效键名：{step}")
                chord_keys.append(normalized_key)

            if not chord_keys:
                raise ValueError(f"无效组合：{step}")

            for repeat_index in range(repeat_count):
                parsed_operations.extend(_build_combo_chord_operations(chord_keys))
                if repeat_interval is not None and repeat_index < repeat_count - 1:
                    parsed_operations.append(
                        {
                            "op": "wait",
                            "duration": repeat_interval,
                            "duration_min": repeat_interval,
                            "duration_max": repeat_interval,
                            "random": False,
                            "count": 1,
                        }
                    )
            continue

        normalized_key = _normalize_combo_key_name(key_body)
        if not normalized_key:
            raise ValueError(f"无效键名：{step}")

        if action in ("down", "up") and repeat_count > 1:
            raise ValueError(f"按下/松开步骤不支持重复次数：{step}")

        parsed_operations.append(
            {
                "op": action or "press",
                "key": normalized_key,
                "count": repeat_count,
                "repeat_interval": repeat_interval,
            }
        )

    _validate_key_mouse_operation_limits(parsed_operations)
    if require_matched_pairs:
        _validate_key_operation_pairs(parsed_operations)
    return parsed_operations


def _apply_combo_key_action(
    operations: List[Dict[str, Any]],
    action: Any,
) -> List[Dict[str, Any]]:
    """把「只按下 / 只释放」落到已解析步骤上，避免裸键名被当成完整按键。"""
    normalized_action = _normalize_key_mouse_action(action)
    if normalized_action == KEY_MOUSE_ACTION_COMPLETE:
        return list(operations)

    rewritten: List[Dict[str, Any]] = []
    for step in operations:
        op = str(step.get("op") or "").strip().lower()
        if op in {"wait", "mouse_action", "mouse_wheel"}:
            rewritten.append(dict(step))
            continue
        if normalized_action == KEY_MOUSE_ACTION_HOLD:
            if op == "up":
                continue
            item = dict(step)
            if op == "press":
                item["op"] = "down"
            rewritten.append(item)
            continue
        if normalized_action == KEY_MOUSE_ACTION_RELEASE:
            if op == "down":
                continue
            item = dict(step)
            if op == "press":
                item["op"] = "up"
            rewritten.append(item)
            continue
        rewritten.append(dict(step))

    if not rewritten:
        raise ValueError("只按下或只释放没有可执行的按键步骤")
    return rewritten


def _coalesce_simple_key_hold(operations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """单键「按下 → 等待 → 松开」收成一次带时长的完整按键，避免驱动两次点按。"""
    coalesced: List[Dict[str, Any]] = []
    pressed_keys = set()
    index = 0
    while index < len(operations):
        down_step = operations[index]
        if (
            not pressed_keys
            and index + 2 < len(operations)
            and str(down_step.get("op") or "").strip().lower() == "down"
            and str(operations[index + 1].get("op") or "").strip().lower() == "wait"
            and str(operations[index + 2].get("op") or "").strip().lower() == "up"
            and int(down_step.get("count", 1) or 1) == 1
            and int(operations[index + 2].get("count", 1) or 1) == 1
            and str(down_step.get("key") or "").strip().lower()
            == str(operations[index + 2].get("key") or "").strip().lower()
        ):
            hold_duration = _resolve_combo_wait_duration(operations[index + 1])
            coalesced.append(
                {
                    "op": "press",
                    "key": str(down_step.get("key") or ""),
                    "count": 1,
                    "hold_duration": hold_duration,
                }
            )
            index += 3
            continue
        coalesced.append(down_step)
        op = str(down_step.get("op") or "").strip().lower()
        key = str(down_step.get("key") or "").strip().lower()
        if op == "down":
            pressed_keys.add(key)
        elif op == "up":
            pressed_keys.discard(key)
        index += 1
    return coalesced


def _resolve_combo_operations(sequence: Any, action: Any = KEY_MOUSE_ACTION_COMPLETE) -> List[Dict[str, Any]]:
    normalized_action = _normalize_key_mouse_action(action)
    require_pairs = normalized_action == KEY_MOUSE_ACTION_COMPLETE
    operations = _parse_combo_expression(
        sequence,
        require_matched_pairs=require_pairs,
    )
    operations = _apply_combo_key_action(operations, normalized_action)
    return _coalesce_simple_key_hold(operations)


def _release_foreground_keys(driver: Any, pressed_keys: List[str]) -> None:
    """失败或停止时释放前台已按下按键。"""
    if not driver or not hasattr(driver, "key_up"):
        return
    for key_name in reversed(pressed_keys):
        try:
            driver.key_up(key_name)
        except Exception:
            continue


def _release_background_keys(simulator: Any, pressed_vk_codes: List[int]) -> None:
    """失败或停止时释放后台已按下按键。"""
    if simulator is None:
        return
    for vk_code in reversed(pressed_vk_codes):
        try:
            simulator.send_key_up(vk_code)
        except Exception:
            continue


def _resolve_foreground_runtime_position(foreground_input_manager: Any) -> Tuple[int, int]:
    """从已选前台输入管理器读取当前位置；失败时禁止猜测坐标。"""
    if foreground_input_manager is None:
        raise RuntimeError("前台输入管理器不可用")
    x, y = foreground_input_manager.get_mouse_position()
    return int(x), int(y)


def _resolve_background_runtime_position(simulator: Any) -> Tuple[int, int]:
    """读取所选后台模拟器的鼠标位置并转换为客户区坐标。"""
    if simulator is None or not simulator.hwnd:
        raise RuntimeError("后台输入模拟器或窗口不可用")
    screen_x, screen_y = simulator.get_mouse_position()
    client_x, client_y = win32gui.ScreenToClient(int(simulator.hwnd), (int(screen_x), int(screen_y)))
    return int(client_x), int(client_y)


def _release_foreground_mouse_buttons(
    foreground_input_manager: Any,
    pressed_mouse_buttons: List[Tuple[str, Optional[int], Optional[int]]],
    target_hwnd: Optional[int],
) -> None:
    """失败或停止时释放前台已按下鼠标按键。"""
    if foreground_input_manager is None:
        return
    for button, x_value, y_value in reversed(pressed_mouse_buttons):
        try:
            if not foreground_input_manager.mouse_up(0, 0, button):
                logger.error("前台鼠标弹起失败：%s", button)
        except Exception as exc:
            logger.error("前台鼠标弹起失败：%s", exc)
            continue


def _release_background_mouse_buttons(
    simulator: Any,
    pressed_mouse_buttons: List[Tuple[str, Optional[int], Optional[int]]],
) -> None:
    """失败或停止时释放后台已按下鼠标按键。"""
    if simulator is None:
        return
    for button, x_value, y_value in reversed(pressed_mouse_buttons):
        try:
            if not simulator.mouse_up(0, 0, button):
                logger.error("后台鼠标弹起失败：%s", button)
        except Exception as exc:
            logger.error("后台鼠标弹起失败：%s", exc)
            continue


def _to_foreground_screen_coord(target_hwnd: Optional[int], x: int, y: int) -> Tuple[int, int]:
    """将客户区坐标转换为屏幕坐标（前台模式）。"""
    if not target_hwnd:
        return int(x), int(y)

    try:
        screen_x, screen_y = win32gui.ClientToScreen(target_hwnd, (int(x), int(y)))
        return int(screen_x), int(screen_y)
    except Exception as exc:
        raise RuntimeError("组合键鼠标客户区坐标转换失败") from exc


def _execute_combo_expression_foreground(
    driver: Any,
    operations: List[Dict[str, Any]],
    stop_checker=None,
    foreground_input_manager=None,
    target_hwnd: Optional[int] = None,
    failure_detail: Optional[Dict[str, str]] = None,
    enable_repeat: bool = True,
    repeat_interval: Optional[float] = None,
) -> bool:
    """执行可编辑组合键（前台）。"""
    def _set_failure_detail(message: str) -> None:
        if failure_detail is not None:
            failure_detail["message"] = str(message or "").strip()

    if not driver or not hasattr(driver, "key_down") or not hasattr(driver, "key_up"):
        message = "[前台模式组合键] 驱动不支持key_down/key_up方法"
        logger.error(message)
        _set_failure_detail(message)
        return False

    pressed_keys: List[str] = []
    pressed_mouse_buttons: List[Tuple[str, Optional[int], Optional[int]]] = []
    modifier_key_names = {"ctrl", "shift", "alt", "win"}
    try:
        for step in operations:
            _raise_if_stopped(stop_checker, "前台组合键可编辑序列")
            op = str(step.get("op", "") or "").strip().lower()
            key_name = str(step.get("key", "") or "").strip()
            count = int(step.get("count", 1) or 1)
            if op == "wait":
                for _ in range(max(1, count)):
                    _raise_if_stopped(stop_checker, "前台组合键可编辑序列")
                    wait_duration = _resolve_combo_wait_duration(step)
                    if wait_duration <= 0:
                        continue
                    target_key = _foreground_repeat_target(pressed_keys)
                    if enable_repeat and target_key:
                        if not run_system_repeat_schedule(
                            repeat=lambda key=target_key: bool(driver.key_up(key)) and bool(driver.key_down(key)),
                            duration=wait_duration,
                            sleep=lambda seconds: _hold_for_duration(seconds, "前台组合键等待"),
                            enable_repeat=True,
                            repeat_interval=repeat_interval,
                            stop_checker=stop_checker,
                        ):
                            message = f"[前台模式组合键] 连发失败: {target_key}"
                            logger.error(message)
                            _set_failure_detail(message)
                            _release_foreground_keys(driver, pressed_keys)
                            _release_foreground_mouse_buttons(foreground_input_manager, pressed_mouse_buttons, target_hwnd)
                            return False
                    else:
                        run_system_repeat_schedule(
                            repeat=lambda: True, duration=wait_duration,
                            sleep=lambda seconds: _hold_for_duration(seconds, "前台组合键等待"),
                            enable_repeat=False, stop_checker=stop_checker,
                        )
                continue
            if op == "mouse_wheel":
                direction = str(step.get("direction", "down") or "down").strip().lower()
                if direction not in ("up", "down"):
                    direction = "down"
                raw_x = step.get("x", None)
                raw_y = step.get("y", None)
                use_current_position = bool(step.get("use_current_position", False)) or raw_x is None or raw_y is None
                x_value = int(raw_x) if raw_x is not None else 0
                y_value = int(raw_y) if raw_y is not None else 0
                wheel_clicks = max(1, int(step.get("wheel_clicks", 1) or 1))
                step_repeat_gap = _resolve_combo_repeat_interval(step, 0.01)

                if foreground_input_manager is None or not hasattr(foreground_input_manager, "scroll_mouse"):
                    message = "[前台模式组合键] 可编辑序列滚轮失败：输入管理器不支持滚轮"
                    logger.error(message)
                    _set_failure_detail(message)
                    _release_foreground_keys(driver, pressed_keys)
                    _release_foreground_mouse_buttons(foreground_input_manager, pressed_mouse_buttons, target_hwnd)
                    return False

                total_scroll_steps = max(1, count) * wheel_clicks
                for step_index in range(total_scroll_steps):
                    _raise_if_stopped(stop_checker, "前台组合键可编辑序列")
                    if target_hwnd:
                        _activate_foreground_window(target_hwnd)
                        precise_sleep(0.08)
                    # LB 等驱动下，修饰键可能在长滚轮过程中丢状态，这里逐步重申修饰键按下。
                    for held_key in pressed_keys:
                        if held_key in modifier_key_names:
                            try:
                                driver.key_down(held_key)
                            except Exception:
                                continue
                    if use_current_position:
                        screen_x, screen_y = _resolve_foreground_runtime_position(foreground_input_manager)
                    else:
                        screen_x, screen_y = _to_foreground_screen_coord(target_hwnd, x_value, y_value)
                    # 按 1 刻度逐次发送，避免部分目标将大 delta 折叠为单次滚动。
                    result = bool(
                        foreground_input_manager.scroll_mouse(direction, clicks=1, x=screen_x, y=screen_y)
                    )
                    if not result:
                        message = f"[前台模式组合键] 滚轮失败: direction={direction}, clicks={wheel_clicks}, pos=({screen_x},{screen_y})"
                        logger.error(message)
                        _set_failure_detail(message)
                        _release_foreground_keys(driver, pressed_keys)
                        _release_foreground_mouse_buttons(
                            foreground_input_manager,
                            pressed_mouse_buttons,
                            target_hwnd,
                        )
                        return False
                    if step_index < total_scroll_steps - 1 and step_repeat_gap > 0:
                        _hold_for_duration(step_repeat_gap, "前台组合键滚轮步进间隔")
                continue

            if op in ("mouse_click", "mouse_action"):
                button = str(step.get("button", "left") or "left").strip().lower()
                raw_x = step.get("x", None)
                raw_y = step.get("y", None)
                use_current_position = bool(step.get("use_current_position", False)) or raw_x is None or raw_y is None
                x_value = int(raw_x) if raw_x is not None else 0
                y_value = int(raw_y) if raw_y is not None else 0
                click_action = str(step.get("mouse_action", "完整点击") or "完整点击").strip()
                normalized_action = normalize_click_action(click_action)
                auto_release = normalized_action != "仅按下"
                step_repeat_gap = _resolve_combo_repeat_interval(step)

                if foreground_input_manager is None:
                    message = "[前台模式组合键] 可编辑序列鼠标点击失败：输入管理器不可用"
                    logger.error(message)
                    _set_failure_detail(message)
                    _release_foreground_keys(driver, pressed_keys)
                    _release_foreground_mouse_buttons(foreground_input_manager, pressed_mouse_buttons, target_hwnd)
                    return False

                for i in range(max(1, count)):
                    _raise_if_stopped(stop_checker, "前台组合键可编辑序列")
                    stored_x: Optional[int] = x_value
                    stored_y: Optional[int] = y_value
                    if target_hwnd:
                        _activate_foreground_window(target_hwnd)
                        precise_sleep(0.08)
                    # 鼠标步骤前重申修饰键，避免 shift(按下)+点击 时修饰状态被吞掉。
                    for held_key in pressed_keys:
                        if held_key in modifier_key_names:
                            try:
                                driver.key_down(held_key)
                            except Exception:
                                continue
                    if use_current_position:
                        screen_x, screen_y = _resolve_foreground_runtime_position(foreground_input_manager)
                        stored_x, stored_y = None, None
                        if target_hwnd:
                            try:
                                client_x, client_y = win32gui.ScreenToClient(target_hwnd, (screen_x, screen_y))
                                stored_x, stored_y = int(client_x), int(client_y)
                            except Exception:
                                stored_x, stored_y = None, None
                    else:
                        screen_x, screen_y = _to_foreground_screen_coord(target_hwnd, x_value, y_value)
                    if not _execute_foreground_combo_mouse_action(
                        foreground_input_manager,
                        screen_x,
                        screen_y,
                        button,
                        normalized_action,
                        0.0,
                        auto_release,
                        logger,
                        execution_mode="foreground",
                        target_hwnd=target_hwnd,
                    ):
                        message = (
                            f"[前台模式组合键] 鼠标步骤失败: action={normalized_action}, "
                            f"button={button}, pos=({screen_x},{screen_y})。"
                            "前台模式的鼠标完整点击需要绑定窗口已经在前台；请确认目标窗口可见、未最小化，并已成功激活。"
                        )
                        logger.error(message)
                        _set_failure_detail(message)
                        _release_foreground_keys(driver, pressed_keys)
                        _release_foreground_mouse_buttons(foreground_input_manager, pressed_mouse_buttons, target_hwnd)
                        return False

                    if normalized_action == "仅按下":
                        pressed_mouse_buttons.append((button, stored_x, stored_y))
                    elif normalized_action == "仅松开":
                        for idx in range(len(pressed_mouse_buttons) - 1, -1, -1):
                            if pressed_mouse_buttons[idx][0] == button:
                                pressed_mouse_buttons.pop(idx)
                                break

                    if count > 1 and i < count - 1 and step_repeat_gap > 0:
                        _hold_for_duration(step_repeat_gap, "前台组合键重复间隔")
                continue

            if not key_name:
                message = "[前台模式组合键] 可编辑序列存在空键名"
                logger.error(message)
                _set_failure_detail(message)
                _release_foreground_keys(driver, pressed_keys)
                _release_foreground_mouse_buttons(foreground_input_manager, pressed_mouse_buttons, target_hwnd)
                return False

            if op == "down":
                if not bool(driver.key_down(key_name)):
                    message = f"[前台模式组合键] 按下失败: {key_name}"
                    logger.error(message)
                    _set_failure_detail(message)
                    _release_foreground_keys(driver, pressed_keys)
                    _release_foreground_mouse_buttons(foreground_input_manager, pressed_mouse_buttons, target_hwnd)
                    return False
                pressed_keys.append(key_name)
                continue

            if op == "up":
                result = bool(driver.key_up(key_name))
                if not result:
                    message = f"[前台模式组合键] 松开失败: {key_name}"
                    _set_failure_detail(message)
                    logger.error(message)
                    _release_foreground_keys(driver, pressed_keys)
                    _release_foreground_mouse_buttons(foreground_input_manager, pressed_mouse_buttons, target_hwnd)
                    return False
                for idx in range(len(pressed_keys) - 1, -1, -1):
                    if pressed_keys[idx] == key_name:
                        pressed_keys.pop(idx)
                        break
                continue

            step_repeat_gap = _resolve_combo_repeat_interval(step)
            for i in range(max(1, count)):
                _raise_if_stopped(stop_checker, "前台组合键可编辑序列")
                hold_duration = _resolve_press_hold_duration(step)
                custom_hold = "hold_duration" in step and step.get("hold_duration") is not None
                held_key_names = list(pressed_keys)
                if held_key_names:
                    modified_press_fn = getattr(driver, "modified_key_press", None)
                    if not callable(modified_press_fn):
                        message = f"[前台模式组合键] 驱动不支持带修饰键按住: {key_name}"
                        logger.error(message)
                        _set_failure_detail(message)
                        _release_foreground_keys(driver, pressed_keys)
                        _release_foreground_mouse_buttons(foreground_input_manager, pressed_mouse_buttons, target_hwnd)
                        return False
                    try:
                        modified_ok = bool(modified_press_fn(key_name, held_key_names, hold_duration))
                    except Exception:
                        logger.exception(f"[前台模式组合键] 修饰键按住失败: {key_name}")
                        modified_ok = False
                    if not modified_ok:
                        message = f"[前台模式组合键] 修饰键按住失败: {key_name}"
                        logger.error(message)
                        _set_failure_detail(message)
                        _release_foreground_keys(driver, pressed_keys)
                        _release_foreground_mouse_buttons(foreground_input_manager, pressed_mouse_buttons, target_hwnd)
                        return False
                    if count > 1 and i < count - 1 and step_repeat_gap > 0:
                        _hold_for_duration(step_repeat_gap, "前台组合键重复间隔")
                    continue

                if not _execute_precise_key_hold(
                    driver,
                    key_name,
                    hold_duration,
                    "前台组合键可编辑序列",
                    enable_repeat=enable_repeat and custom_hold,
                    repeat_interval=repeat_interval,
                    stop_checker=stop_checker,
                ):
                    message = f"[前台模式组合键] 按键按住失败: {key_name}"
                    logger.error(message)
                    _set_failure_detail(message)
                    _release_foreground_keys(driver, pressed_keys)
                    _release_foreground_mouse_buttons(foreground_input_manager, pressed_mouse_buttons, target_hwnd)
                    return False
                if count > 1 and i < count - 1 and step_repeat_gap > 0:
                    _hold_for_duration(step_repeat_gap, "前台组合键重复间隔")

        return True
    except InterruptedError:
        _release_foreground_keys(driver, pressed_keys)
        _release_foreground_mouse_buttons(foreground_input_manager, pressed_mouse_buttons, target_hwnd)
        raise
    except Exception as e:
        message = f"[前台模式组合键] 可编辑序列执行失败: {e}"
        logger.error(message, exc_info=True)
        _set_failure_detail(message)
        _release_foreground_keys(driver, pressed_keys)
        _release_foreground_mouse_buttons(foreground_input_manager, pressed_mouse_buttons, target_hwnd)
        return False


def _execute_combo_expression_background(
    simulator: Any,
    operations: List[Dict[str, Any]],
    stop_checker=None,
    enable_repeat: bool = True,
    repeat_interval: Optional[float] = None,
) -> bool:
    """执行可编辑组合键（后台）。"""
    if simulator is None:
        logger.error("[后台模式] 模拟器为空，无法执行可编辑组合键")
        return False

    pressed_vk_codes: List[int] = []
    pressed_mouse_buttons: List[Tuple[str, Optional[int], Optional[int]]] = []
    modifier_vk_codes = {
        VK_CODE.get("ctrl"),
        VK_CODE.get("shift"),
        VK_CODE.get("alt"),
        VK_CODE.get("win"),
        VK_CODE.get("lwin"),
        VK_CODE.get("rwin"),
    }
    modifier_vk_codes.discard(None)
    try:
        for step in operations:
            _raise_if_stopped(stop_checker, "后台组合键可编辑序列")
            op = str(step.get("op", "") or "").strip().lower()
            key_name = str(step.get("key", "") or "").strip().lower()
            count = int(step.get("count", 1) or 1)
            if op == "wait":
                for _ in range(max(1, count)):
                    _raise_if_stopped(stop_checker, "后台组合键可编辑序列")
                    wait_duration = _resolve_combo_wait_duration(step)
                    if wait_duration <= 0:
                        continue
                    target_vk = None
                    for held_vk in reversed(pressed_vk_codes):
                        if held_vk not in modifier_vk_codes:
                            target_vk = held_vk
                            break
                    if enable_repeat and target_vk is not None:
                        repeat_fn = getattr(simulator, "send_key_repeat", None)
                        if not callable(repeat_fn):
                            logger.error("[后台模式] 模拟器不支持连发")
                            _release_background_keys(simulator, pressed_vk_codes)
                            _release_background_mouse_buttons(simulator, pressed_mouse_buttons)
                            return False
                        if not run_system_repeat_schedule(
                            repeat=lambda vk=target_vk: bool(repeat_fn(vk)),
                            duration=wait_duration,
                            sleep=lambda seconds: _hold_for_duration(seconds, "后台组合键等待"),
                            enable_repeat=True,
                            repeat_interval=repeat_interval,
                            stop_checker=stop_checker,
                        ):
                            logger.error(f"[后台模式] 连发失败: vk={target_vk}")
                            _release_background_keys(simulator, pressed_vk_codes)
                            _release_background_mouse_buttons(simulator, pressed_mouse_buttons)
                            return False
                    else:
                        run_system_repeat_schedule(
                            repeat=lambda: True, duration=wait_duration,
                            sleep=lambda seconds: _hold_for_duration(seconds, "后台组合键等待"),
                            enable_repeat=False, stop_checker=stop_checker,
                        )
                continue
            if op == "mouse_wheel":
                direction = str(step.get("direction", "down") or "down").strip().lower()
                if direction not in ("up", "down"):
                    direction = "down"
                raw_x = step.get("x", None)
                raw_y = step.get("y", None)
                use_current_position = bool(step.get("use_current_position", False)) or raw_x is None or raw_y is None
                x_value = int(raw_x) if raw_x is not None else 0
                y_value = int(raw_y) if raw_y is not None else 0
                wheel_clicks = max(1, int(step.get("wheel_clicks", 1) or 1))
                step_repeat_gap = _resolve_combo_repeat_interval(step, 0.01)

                total_scroll_steps = max(1, count) * wheel_clicks
                delta_unit = 120 if direction == "up" else -120
                for step_index in range(total_scroll_steps):
                    _raise_if_stopped(stop_checker, "后台组合键可编辑序列")
                    runtime_x, runtime_y = x_value, y_value
                    if use_current_position:
                        runtime_x, runtime_y = _resolve_background_runtime_position(simulator)
                    # 后台滚轮前重申修饰键按下，降低修饰状态漂移导致的乱滚。
                    for held_vk in pressed_vk_codes:
                        if held_vk in modifier_vk_codes:
                            try:
                                simulator.send_key_down(int(held_vk))
                            except Exception:
                                continue
                    result = False
                    if hasattr(simulator, "scroll"):
                        try:
                            result = bool(simulator.scroll(int(runtime_x), int(runtime_y), int(delta_unit)))
                        except Exception:
                            result = False
                    elif hasattr(simulator, "scroll_mouse"):
                        try:
                            result = bool(simulator.scroll_mouse(direction, 1, x=int(runtime_x), y=int(runtime_y)))
                        except Exception:
                            result = False

                    if not result:
                        logger.error(
                            f"[后台模式] 滚轮失败: direction={direction}, clicks={wheel_clicks}, pos=({runtime_x},{runtime_y})"
                        )
                        _release_background_keys(simulator, pressed_vk_codes)
                        _release_background_mouse_buttons(simulator, pressed_mouse_buttons)
                        return False

                    if step_index < total_scroll_steps - 1 and step_repeat_gap > 0:
                        _hold_for_duration(step_repeat_gap, "后台组合键滚轮步进间隔")
                continue

            if op in ("mouse_click", "mouse_action"):
                button = str(step.get("button", "left") or "left").strip().lower()
                raw_x = step.get("x", None)
                raw_y = step.get("y", None)
                use_current_position = bool(step.get("use_current_position", False)) or raw_x is None or raw_y is None
                x_value = int(raw_x) if raw_x is not None else 0
                y_value = int(raw_y) if raw_y is not None else 0
                click_action = str(step.get("mouse_action", "完整点击") or "完整点击").strip()
                normalized_action = normalize_click_action(click_action)
                auto_release = normalized_action != "仅按下"
                step_repeat_gap = _resolve_combo_repeat_interval(step)

                for i in range(max(1, count)):
                    _raise_if_stopped(stop_checker, "后台组合键可编辑序列")
                    runtime_x, runtime_y = x_value, y_value
                    if use_current_position:
                        runtime_x, runtime_y = _resolve_background_runtime_position(simulator)
                    # 后台鼠标步骤前重申修饰键，与滚轮路径保持一致。
                    for held_vk in pressed_vk_codes:
                        if held_vk in modifier_vk_codes:
                            try:
                                simulator.send_key_down(int(held_vk))
                            except Exception:
                                continue
                    mouse_op = {
                        "button": button,
                        "action": normalized_action,
                        "x": runtime_x,
                        "y": runtime_y,
                        "hold_duration": 0.0,
                        "enable_auto_release": auto_release,
                    }
                    if not _execute_combo_mouse_action(simulator, mouse_op, logger):
                        logger.error(
                            f"[后台模式] 鼠标步骤失败: action={normalized_action}, button={button}, pos=({runtime_x},{runtime_y})"
                        )
                        _release_background_keys(simulator, pressed_vk_codes)
                        _release_background_mouse_buttons(simulator, pressed_mouse_buttons)
                        return False

                    if normalized_action == "仅按下":
                        pressed_mouse_buttons.append((button, runtime_x, runtime_y))
                    elif normalized_action == "仅松开":
                        for idx in range(len(pressed_mouse_buttons) - 1, -1, -1):
                            if pressed_mouse_buttons[idx][0] == button:
                                pressed_mouse_buttons.pop(idx)
                                break

                    if count > 1 and i < count - 1 and step_repeat_gap > 0:
                        _hold_for_duration(step_repeat_gap, "后台组合键重复间隔")
                continue

            vk_code = VK_CODE.get(key_name)

            if not vk_code:
                logger.error(f"[后台模式] 可编辑序列包含无效键: {key_name}")
                _release_background_keys(simulator, pressed_vk_codes)
                _release_background_mouse_buttons(simulator, pressed_mouse_buttons)
                return False

            if op == "down":
                if not bool(simulator.send_key_down(vk_code)):
                    logger.error(f"[后台模式] 按下失败: {key_name}")
                    _release_background_keys(simulator, pressed_vk_codes)
                    _release_background_mouse_buttons(simulator, pressed_mouse_buttons)
                    return False
                pressed_vk_codes.append(vk_code)
                continue

            if op == "up":
                result = bool(simulator.send_key_up(vk_code))
                if not result:
                    logger.error(f"[后台模式] 松开失败: {key_name}")
                    _release_background_keys(simulator, pressed_vk_codes)
                    _release_background_mouse_buttons(simulator, pressed_mouse_buttons)
                    return False
                for idx in range(len(pressed_vk_codes) - 1, -1, -1):
                    if pressed_vk_codes[idx] == vk_code:
                        pressed_vk_codes.pop(idx)
                        break
                continue

            send_key = getattr(simulator, "send_key", None)
            send_key_hold = getattr(simulator, "send_key_hold", None)
            step_repeat_gap = _resolve_combo_repeat_interval(step)
            hold_duration = _resolve_press_hold_duration(step)
            custom_hold = "hold_duration" in step and step.get("hold_duration") is not None
            for i in range(max(1, count)):
                _raise_if_stopped(stop_checker, "后台组合键可编辑序列")
                if custom_hold and callable(send_key_hold):
                    if not bool(
                        send_key_hold(
                            vk_code,
                            hold_duration,
                            enable_repeat=enable_repeat,
                            repeat_interval=repeat_interval,
                            stop_checker=stop_checker,
                        )
                    ):
                        logger.error(f"[后台模式] 按键按住失败: {key_name}")
                        _release_background_keys(simulator, pressed_vk_codes)
                        _release_background_mouse_buttons(simulator, pressed_mouse_buttons)
                        return False
                elif custom_hold or not callable(send_key):
                    logger.error("[后台模式] 模拟器不支持指定的按键动作")
                    _release_background_keys(simulator, pressed_vk_codes)
                    _release_background_mouse_buttons(simulator, pressed_mouse_buttons)
                    return False
                elif not bool(send_key(vk_code)):
                    logger.error(f"[后台模式] 按键执行失败: {key_name}")
                    _release_background_keys(simulator, pressed_vk_codes)
                    _release_background_mouse_buttons(simulator, pressed_mouse_buttons)
                    return False

                if count > 1 and i < count - 1 and step_repeat_gap > 0:
                    _hold_for_duration(step_repeat_gap, "后台组合键重复间隔")

        return True
    except InterruptedError:
        _release_background_keys(simulator, pressed_vk_codes)
        _release_background_mouse_buttons(simulator, pressed_mouse_buttons)
        raise
    except Exception as e:
        logger.error(f"[后台模式] 可编辑序列执行失败: {e}", exc_info=True)
        _release_background_keys(simulator, pressed_vk_codes)
        _release_background_mouse_buttons(simulator, pressed_mouse_buttons)
        return False


def _parse_text_groups(text_groups_input: Any) -> List[str]:
    """解析多组文本，支持字符串/列表/其他类型输入。"""
    if text_groups_input is None:
        return []
    if isinstance(text_groups_input, (list, tuple)):
        groups = []
        for item in text_groups_input:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                groups.append(text)
        return groups
    if not isinstance(text_groups_input, str):
        text_groups_str = str(text_groups_input)
    else:
        text_groups_str = text_groups_input
    if not text_groups_str:
        return []

    # 首先尝试按换行符分割
    lines = [line.strip() for line in text_groups_str.split('\n') if line.strip()]

    # 如果只有一行，则按逗号分割（支持中文逗号和英文逗号）
    if len(lines) == 1:
        line = lines[0]
        # 先统一替换中文逗号为英文逗号，然后分割
        line = line.replace('，', ',')
        text_groups = [text.strip() for text in line.split(',') if text.strip()]
        logger.info(f"按逗号分割解析到{len(text_groups)}组文本: {text_groups}")
        return text_groups
    else:
        # 多行模式，每行一组
        logger.info(f"按行分割解析到{len(lines)}组文本: {lines}")
        return lines

def _get_enabled_runtime_windows() -> list:
    """读取当前多窗口执行器登记的窗口；无法读取时直接失败。"""
    import sys

    module = sys.modules.get('ui.main_window_parts.main_window')
    if module is None:
        raise RuntimeError("多窗口执行器不可用，窗口索引未知")
    for obj in vars(module).values():
        executor = getattr(obj, 'multi_executor', None)
        if executor is not None:
            windows = executor.get_enabled_windows()
            if windows:
                return list(windows)
    raise RuntimeError("无法读取多窗口执行器的启用窗口")


def _get_current_window_index(card_id: int, target_hwnd: Optional[int] = None) -> int:
    """只使用执行器登记的窗口顺序，禁止硬编码或哈希猜测。"""
    if not target_hwnd:
        raise RuntimeError("目标窗口句柄缺失，窗口索引未知")
    for index, window in enumerate(_get_enabled_runtime_windows()):
        if window.hwnd == target_hwnd:
            return index
    raise RuntimeError("目标窗口未登记，窗口索引未知")

def _get_or_init_multi_text_state(context, card_id: int, text_groups: List[str], reset_on_next_run: bool) -> dict:
    """获取或初始化多组文本输入状态"""
    if reset_on_next_run:
        logger.info("启用了'下次执行重置文本组记录'，重置多组文本状态")
        state = {
            'text_groups': text_groups.copy(),
            'completed_combinations': [],  # 使用list而不是set，便于JSON序列化
            'window_assignments': {},  # 窗口到文本的分配记录
            'text_usage_count': {i: 0 for i in range(len(text_groups))},  # 每个文本被使用的次数
            'total_windows': 0,  # 参与的窗口总数
            'initialized': True
        }
        context.set_card_data(card_id, 'multi_text_input_state', state)
        return state

    # 尝试获取现有状态
    existing_state = context.get_card_data(card_id, 'multi_text_input_state')
    if existing_state and existing_state.get('initialized'):
        # 检查文本组配置是否发生变化
        old_text_groups = existing_state.get('text_groups', [])
        if old_text_groups != text_groups:
            logger.info(f"检测到文本组配置变化: {old_text_groups} -> {text_groups}")
            # 文本组发生变化，重新初始化状态
            logger.info("文本组配置变化，重新初始化状态")
            state = {
                'text_groups': text_groups.copy(),
                'completed_combinations': [],
                'window_assignments': {},
                'text_usage_count': {i: 0 for i in range(len(text_groups))},
                'total_windows': 0,
                'initialized': True
            }
            context.set_card_data(card_id, 'multi_text_input_state', state)
            return state
        else:
            # 文本组配置未变化，检查是否已完成
            if _is_multi_text_input_complete(text_groups, existing_state):
                logger.info("检测到多组文本输入已完成，清除旧状态并重新初始化")
                context.clear_card_ocr_data(card_id)
                # 重新初始化
                state = {
                    'text_groups': text_groups.copy(),
                    'completed_combinations': [],
                    'window_assignments': {},
                    'text_usage_count': {i: 0 for i in range(len(text_groups))},
                    'total_windows': 0,
                    'initialized': True
                }
                context.set_card_data(card_id, 'multi_text_input_state', state)
                return state
            else:
                # 更新文本组配置（防止配置变化）
                existing_state['text_groups'] = text_groups.copy()
                logger.info(f"恢复多组文本输入状态，已完成组合数: {len(existing_state.get('completed_combinations', []))}")
                return existing_state

    # 初始化新状态
    logger.info(f"初始化多组文本输入状态: 共{len(text_groups)}组文本")
    state = {
        'text_groups': text_groups.copy(),
        'completed_combinations': [],  # 使用list而不是set
        'window_assignments': {},
        'text_usage_count': {i: 0 for i in range(len(text_groups))},
        'total_windows': 0,
        'initialized': True
    }
    context.set_card_data(card_id, 'multi_text_input_state', state)
    return state

def _find_target_text_for_window(text_groups: List[str], window_index: int,
                                completed_combinations: list, input_state: dict) -> tuple[str, int]:
    """为指定窗口查找目标文本"""
    if not text_groups:
        return "", -1

    # 策略1：优先使用窗口索引对应的文本（如果未完成）
    preferred_index = window_index % len(text_groups)
    preferred_combination = f"window_{window_index}_text_{preferred_index}"

    if preferred_combination not in completed_combinations:
        return text_groups[preferred_index], preferred_index

    # 策略2：查找该窗口还未完成的其他文本
    for text_index, text in enumerate(text_groups):
        combination_key = f"window_{window_index}_text_{text_index}"
        if combination_key not in completed_combinations:
            return text, text_index

    # 策略3：如果该窗口所有文本都已完成，检查是否还有全局未完成的文本
    # 查找全局使用次数最少且该窗口未完成的文本
    text_usage_count = input_state.get('text_usage_count', {})

    # 找到全局使用次数最少的文本
    if text_usage_count:
        min_usage = min(text_usage_count.values())
        for text_index, usage_count in text_usage_count.items():
            if usage_count == min_usage:
                combination_key = f"window_{window_index}_text_{text_index}"
                # 只有当这个窗口还没有完成这个文本时才返回
                if combination_key not in completed_combinations:
                    return text_groups[text_index], text_index

    # 如果该窗口已经完成了所有可能的文本，返回空（表示该窗口无需再执行）
    return "", -1

def _is_multi_text_input_complete(text_groups: List[str], input_state: dict) -> bool:
    """
    判断多组文本输入是否完成

    保守的完成条件：只有当所有文本组都至少被一个窗口使用过时才算完成
    这样可以确保记忆机制正常工作，不会过早清除状态
    """
    completed_combinations = input_state.get('completed_combinations', [])

    if not completed_combinations:
        return False

    # 统计已完成的文本
    completed_texts = set()

    for combination in completed_combinations:
        if combination.startswith('window_') and '_text_' in combination:
            parts = combination.split('_text_')
            text_index = int(parts[1])
            completed_texts.add(text_index)

    num_texts = len(text_groups)
    num_completed_texts = len(completed_texts)

    logger.debug(f"完成判断 - 文本组数:{num_texts}, 已完成文本数:{num_completed_texts}")

    # 只有当所有文本都至少被一个窗口完成时才算真正完成
    if num_completed_texts >= num_texts:
        logger.info(f"所有{num_texts}组文本都已完成，可以清除状态")
        return True

    logger.debug(f"还有{num_texts - num_completed_texts}组文本未完成，保持状态")
    return False

def _handle_multi_text_input(text_groups: List[str], card_id: int, window_index: int,
                           reset_on_next_run: bool = False) -> tuple[str, int]:
    """
    处理多组文本输入逻辑 - 支持单窗口循环输入和多窗口并行输入

    策略：
    1. 单窗口场景（window_index=0）：使用计数器循环输入每组文本
    2. 多窗口场景：每个窗口分配对应索引的文本
    3. 启用重置时：清除状态，从头开始

    Returns:
        tuple[str, int]: (要输入的文本, 下一个卡片ID或None)
    """
    try:
        if not text_groups:
            logger.warning("文本组为空")
            return "", None

        from task_workflow.workflow_context import get_workflow_context
        context = get_workflow_context()

        # 状态键
        counter_key = f"multi_text_input_counter_{card_id}"

        # 获取当前计数器值
        current_counter = context.get_card_data(card_id, counter_key, 0)

        # 如果启用了重置选项，清除计数器
        if reset_on_next_run:
            current_counter = 0
            context.set_card_data(card_id, counter_key, 0)
            logger.info("重置多组文本输入计数器")

        is_multi_window = len(_get_enabled_runtime_windows()) > 1

        # 计算文本索引
        if is_multi_window:
            # 多窗口场景：使用窗口索引
            text_index = window_index % len(text_groups)
            logger.info(f"[多窗口模式] 窗口{window_index}分配文本组{text_index}")
        else:
            # 单窗口场景：使用循环计数器
            text_index = current_counter % len(text_groups)

            logger.info(f"[单窗口循环模式] 计数器={current_counter}, 文本组索引={text_index}, 总共{len(text_groups)}组")

            # 更新计数器到下一组
            next_counter = current_counter + 1
            context.set_card_data(card_id, counter_key, next_counter)
            logger.info(f"[单窗口循环模式] 更新计数器: {current_counter} -> {next_counter}")

        target_text = text_groups[text_index]

        # 添加详细的诊断日志
        logger.info("=== 多组文本分配详情 ===")
        logger.info(f"卡片ID: {card_id}")
        logger.info(f"窗口索引: {window_index}")
        logger.info(f"是否多窗口: {is_multi_window}")
        logger.info(f"文本组总数: {len(text_groups)}")
        logger.info(f"文本组列表: {text_groups}")
        logger.info(f"当前计数器: {current_counter}")
        logger.info(f"计算的文本索引: {text_index}")
        logger.info(f"分配的文本: '{target_text}'")
        logger.info(f"重置模式: {reset_on_next_run}")
        logger.info("=========================")

        return target_text, None

    except Exception as e:
        logger.error(f"多组文本输入处理失败: {e}", exc_info=True)
        raise RuntimeError("多组文本输入处理失败") from e

# --- Constants for Typing Simulation ---
RANDOM_DELAY_THRESHOLD = 0.05 # Apply random delay if base delay is >= 50ms
RANDOM_DELAY_FACTOR = 0.3   # Randomize delay by +/- 30%

# ===================================================================
# Windows Virtual Key Codes 映射表
# ===================================================================
# 按键名称到Windows虚拟键码的完整映射表
# Windows virtual-key code mapping.
# 按字母顺序排序，便于查找和维护

VK_CODE = {
    # === A-Z 字母键 ===
    'a': 0x41, 'b': 0x42, 'c': 0x43, 'd': 0x44, 'e': 0x45,
    'f': 0x46, 'g': 0x47, 'h': 0x48, 'i': 0x49, 'j': 0x4A,
    'k': 0x4B, 'l': 0x4C, 'm': 0x4D, 'n': 0x4E, 'o': 0x4F,
    'p': 0x50, 'q': 0x51, 'r': 0x52, 's': 0x53, 't': 0x54,
    'u': 0x55, 'v': 0x56, 'w': 0x57, 'x': 0x58, 'y': 0x59,
    'z': 0x5A,

    # === 0-9 数字键 ===
    '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34,
    '5': 0x35, '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39,

    # === 功能键 F1-F12 ===
    'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73,
    'f5': 0x74, 'f6': 0x75, 'f7': 0x76, 'f8': 0x77,
    'f9': 0x78, 'f10': 0x79, 'f11': 0x7A, 'f12': 0x7B,

    # === 数字键盘 ===
    'numpad0': 0x60, 'numpad1': 0x61, 'numpad2': 0x62, 'numpad3': 0x63,
    'numpad4': 0x64, 'numpad5': 0x65, 'numpad6': 0x66, 'numpad7': 0x67,
    'numpad8': 0x68, 'numpad9': 0x69,

    # === 符号键（按字母顺序） ===
    "'": 0xDE,           # 单引号/撇号
    ',': 0xBC,           # 逗号
    '-': 0xBD,           # 减号/连字符
    '.': 0xBE,           # 句号
    '/': 0xBF,           # 正斜杠
    ';': 0xBA,           # 分号
    '=': 0xBB,           # 等号
    '[': 0xDB,           # 左方括号
    '\\': 0xDC,          # 反斜杠
    ']': 0xDD,           # 右方括号
    '`': 0xC0,           # 反引号

    # === 数字键盘运算符 ===
    'add': 0x6B,         # 数字键盘加号 +
    'decimal': 0x6E,     # 数字键盘小数点 .
    'divide': 0x6F,      # 数字键盘除号 /
    'multiply': 0x6A,    # 数字键盘乘号 *
    'separator': 0x6C,   # 数字键盘分隔符
    'subtract': 0x6D,    # 数字键盘减号 -

    # === 修饰键 ===
    'alt': 0x12,         # Alt键
    'ctrl': 0x11,        # Ctrl键
    'shift': 0x10,       # Shift键

    # === 导航键 ===
    'down': 0x28,        # 下箭头
    'end': 0x23,         # End键
    'home': 0x24,        # Home键
    'left': 0x25,        # 左箭头
    'pagedown': 0x22,    # Page Down
    'pageup': 0x21,      # Page Up
    'right': 0x27,       # 右箭头
    'up': 0x26,          # 上箭头

    # === 编辑键 ===
    'backspace': 0x08,   # 退格键
    'delete': 0x2E,      # Delete键
    'insert': 0x2D,      # Insert键
    'tab': 0x09,         # Tab键

    # === 系统键 ===
    'apps': 0x5D,        # 应用程序键（右键菜单）
    'capslock': 0x14,    # Caps Lock
    'enter': 0x0D,       # 回车键
    'esc': 0x1B,         # Escape键
    'lwin': 0x5B,        # 左Windows键
    'numlock': 0x90,     # Num Lock
    'pause': 0x13,       # Pause键
    'rwin': 0x5C,        # 右Windows键
    'scrolllock': 0x91,  # Scroll Lock
    'space': 0x20,       # 空格键

    # === 常用别名 ===
    'apostrophe': 0xDE,  # 单引号别名
    'backslash': 0xDC,   # 反斜杠别名
    'caps': 0x14,        # Caps Lock别名
    'comma': 0xBC,       # 逗号别名
    'control': 0x11,     # Ctrl别名
    'del': 0x2E,         # Delete别名
    'equal': 0xBB,       # 等号别名
    'escape': 0x1B,      # Escape别名
    'grave': 0xC0,       # 反引号别名
    'lbracket': 0xDB,    # 左方括号别名
    'menu': 0x5D,        # 应用程序键别名
    'minus': 0xBD,       # 减号别名
    'period': 0xBE,      # 句号别名
    'quote': 0xDE,       # 单引号别名
    'rbracket': 0xDD,    # 右方括号别名
    'return': 0x0D,      # 回车键别名
    'scroll': 0x91,      # Scroll Lock别名
    'semicolon': 0xBA,   # 分号别名
    'slash': 0xBF,       # 正斜杠别名
    'win': 0x5B,         # 左Windows键别名
    'windows': 0x5B,     # 左Windows键别名
}

# --- Helper for Foreground Activation ---
def _activate_foreground_window(target_hwnd: Optional[int]):
    if not target_hwnd:
        logger.warning("前台输入需要绑定目标窗口")
        return False

    try:
        if not win32gui.IsWindow(target_hwnd):
            logger.warning(f"目标窗口句柄 {target_hwnd} 无效或已销毁")
            return False
        from utils.window.virtual_desktop import skip_cross_desktop_activation

        if skip_cross_desktop_activation(target_hwnd, log_prefix="键盘按键"):
            return False

        from utils.window.window_activation_utils import activate_window
        if not activate_window(int(target_hwnd), log_prefix="键盘按键"):
            return False

        activated_hwnd = win32gui.GetForegroundWindow()
        target_root = int(win32gui.GetAncestor(int(target_hwnd), win32con.GA_ROOT) or 0)
        active_root = int(win32gui.GetAncestor(int(activated_hwnd), win32con.GA_ROOT) or 0)
        if activated_hwnd == target_hwnd or (target_root > 0 and target_root == active_root):
            logger.debug(f"窗口 {target_hwnd} 已成功激活。")
            return True

        logger.warning(f"目标窗口 {target_hwnd} 未激活，当前前台窗口为 {activated_hwnd}")
        return False

    except Exception as e:
        logger.warning(f"激活目标窗口 {target_hwnd} 失败: {e}")
        return False

# ==================================
#  Helper Functions
# ==================================

def _raise_if_stopped(stop_checker=None, label: str = "") -> None:
    if stop_checker and stop_checker():
        message = "[键盘输入] 检测到停止信号"
        if label:
            message = f"{message} ({label})"
        logger.info(message)
        raise InterruptedError(message)


def _send_simulated_text(target_hwnd, text: str, delay: float = 0.0, stop_checker=None, use_focus: bool = False, execution_mode=None) -> bool:
    """原生仿真输入。前台必须先激活绑定窗口，再走 Unicode SendInput。"""
    try:
        hwnd = int(target_hwnd or 0)
    except (TypeError, ValueError):
        hwnd = 0
    if hwnd <= 0:
        logger.error("[文本输入] 仿真输入需要绑定窗口")
        return False
    if use_focus and not _activate_foreground_window(hwnd):
        logger.error("[文本输入] 未能激活绑定窗口，仿真输入未发送")
        return False
    try:
        from utils.input.simulated_text import send_simulated_text

        return bool(send_simulated_text(
            hwnd, str(text or ""), delay, stop_checker, use_focus, execution_mode=execution_mode,
        ))
    except InterruptedError:
        raise
    except Exception as exc:
        logger.error("[文本输入] 仿真输入发送失败: %s", exc, exc_info=True)
        return False


def _send_text_enter(target_hwnd, execution_mode, stop_checker, simulator=None):
    """回车沿所选后端执行，插件文本和回车共用同一实例。"""
    _raise_if_stopped(stop_checker, "文本输入后回车")
    precise_sleep(0.05)
    _raise_if_stopped(stop_checker, "文本输入后回车")
    if simulator is not None:
        if not simulator.send_key(VK_CODE["enter"]):
            raise RuntimeError("文字已输入，但插件回车发送失败")
        return
    if execution_mode.startswith("foreground"):
        if not foreground_input.initialize():
            raise RuntimeError("文字已输入，但回车驱动初始化失败")
        driver = foreground_input.get_active_driver()
        if foreground_input.get_driver_type() == "pyautogui":
            if not _activate_foreground_window(target_hwnd):
                raise RuntimeError("文字已输入，但回车前未能激活绑定窗口")
            precise_sleep(0.05)
            _raise_if_stopped(stop_checker, "文本输入后回车")
        if driver is None or not driver.press_key("enter"):
            raise RuntimeError("文字已输入，但回车发送失败")
        return
    from utils.input_simulation import global_input_simulator_manager

    enter_simulator = global_input_simulator_manager.create_temporary_simulator(target_hwnd, execution_mode)
    if enter_simulator is None:
        raise RuntimeError("文字已输入，但回车输入实例不可用")
    try:
        _raise_if_stopped(stop_checker, "文本输入后回车")
        if not enter_simulator.send_key(VK_CODE["enter"]):
            raise RuntimeError("文字已输入，但回车发送失败")
    finally:
        global_input_simulator_manager.close_simulator(enter_simulator)


def _send_text_input(target_hwnd, text, execution_mode, delay, stop_checker, press_enter=False):
    """按配置选择唯一文字通道，失败直接结束，不改用其他后端。"""
    from utils.input_simulation import global_input_simulator_manager
    from utils.input_simulation.mode_utils import is_plugin_input_backend
    from utils.runtime_config import get_runtime_config

    _raise_if_stopped(stop_checker, "文本输入")
    if is_plugin_input_backend(get_runtime_config()):
        simulator = global_input_simulator_manager.create_temporary_simulator(target_hwnd, execution_mode)
        if simulator is None:
            raise RuntimeError("插件文本输入实例不可用")
        try:
            if not simulator.send_text(text, stop_checker=stop_checker, delay=delay):
                raise RuntimeError("插件文本输入发送失败")
            if press_enter:
                _send_text_enter(target_hwnd, execution_mode, stop_checker, simulator=simulator)
        finally:
            global_input_simulator_manager.close_simulator(simulator)
        return
    use_focus = execution_mode.startswith("foreground")
    if use_focus:
        foreground_input.set_execution_mode(execution_mode)
    if not _send_simulated_text(
        target_hwnd, text, delay, stop_checker, use_focus=use_focus, execution_mode=execution_mode,
    ):
        raise RuntimeError("仿真输入发送失败")
    if press_enter:
        _send_text_enter(target_hwnd, execution_mode, stop_checker)


def _execute_text_input(params, target_hwnd, execution_mode, stop_checker, kwargs):
    """所有文本后端共用多组轮换、模板解析和回车参数。"""
    _raise_if_stopped(stop_checker, "文本输入")
    text_mode = params.get("text_input_mode", "单组文本")
    if text_mode not in {"单组文本", "多组文本"}:
        raise ValueError(f"文本输入模式无效：{text_mode!r}")
    text = params.get("text_to_type", "")
    if text_mode == "多组文本":
        groups = _parse_text_groups(params.get("text_groups", ""))
        if not groups:
            raise ValueError("多组文本解析失败")
        card_id = kwargs.get("card_id", 0)
        window_index = _get_current_window_index(card_id, target_hwnd)
        text, _ = _handle_multi_text_input(
            groups, card_id, window_index, params.get("reset_text_groups_on_next_run", False),
        )
        if not text:
            return
    text = _resolve_text_template(text)
    if not str(text or "").strip():
        raise ValueError("文本为空，无法执行")
    _publish_typed_text(kwargs, text)
    _send_text_input(
        target_hwnd, text, execution_mode, params.get("delay_between_keystrokes", 0.01), stop_checker,
        press_enter=params.get("press_enter_after_text", False),
    )


# ==================================
#  Task Execution Logic
# ==================================
def execute_task(params, counters, execution_mode='foreground', target_hwnd=None, window_region=None,
                 pause_checker=None, **kwargs):
    """执行现行键盘输入操作（文本输入/按键序列），支持前/后台模式。

    Args:
        pause_checker: 暂停检查函数，返回True表示需要暂停
    """
    params = normalize_parameters(params)
    logger.debug(f"Executing keyboard input with params: {params}")
    stop_checker = kwargs.get('stop_checker', None)

    # --- Get common parameters ---
    input_type = params.get('input_type')
    combo_key_sequence_text = str(params.get('combo_key_sequence_text', '') or '').strip()
    if combo_key_sequence_text:
        combo_key_sequence_text = _resolve_text_template(combo_key_sequence_text).strip()
        _publish_typed_text(kwargs, combo_key_sequence_text)
    # Success and Failure params
    success_action = params.get('on_success', '执行下一步')
    success_jump_target = params.get('success_jump_target_id')
    failure_action = params.get('on_failure', '执行下一步')
    failure_jump_target = params.get('failure_jump_target_id')
    try:
        if execution_mode not in {"foreground", "foreground_driver", "foreground_py", "background", "background_sendmessage", "background_postmessage"}:
            raise ValueError(f"不支持的按键执行模式: {execution_mode}")

        if input_type == "文本输入":
            try:
                _execute_text_input(params, target_hwnd, execution_mode, stop_checker, kwargs)
                return True, success_action, success_jump_target
            except InterruptedError:
                return False, "停止工作流", None
            except Exception as exc:
                logger.error("文本输入失败：%s", exc, exc_info=True)
                return False, failure_action, failure_jump_target, str(exc)

        # 新增：根据执行模式设置前台输入管理器的强制模式（严格隔离）
        is_foreground_mode = execution_mode and execution_mode.startswith('foreground')
        if is_foreground_mode:
            foreground_input.set_execution_mode(execution_mode)
            logger.info(f"[鼠标模式] 前台模式 - {execution_mode}")

        # 前台模式键盘按键执行
        if is_foreground_mode and input_type == KEY_MOUSE_INPUT_TYPE:
            logger.info("[前台模式键盘按键] 启动前台键盘按键执行流程")
            try:
                if not foreground_input.initialize():
                    detail = "[前台模式键盘按键] 驱动初始化失败"
                    logger.error(detail)
                    return False, failure_action, failure_jump_target, detail

                driver = foreground_input._active_driver
                driver_type = foreground_input.get_driver_type()
                logger.info(f"[前台模式键盘按键] 使用驱动: {driver_type}")

                # 前台按键/组合键会发到当前前台窗口；含鼠标动作时还有前台校验，所以所有前台驱动都先激活目标。
                if target_hwnd:
                    _activate_foreground_window(target_hwnd)
                    precise_sleep(0.1)

                if not driver or not hasattr(driver, 'key_down') or not hasattr(driver, 'key_up'):
                    detail = "[前台模式键盘按键] 驱动不支持key_down/key_up方法"
                    logger.error(detail)
                    return False, failure_action, failure_jump_target, detail

                if not combo_key_sequence_text:
                    detail = "[前台模式键盘按键] 可编辑内容为空，无法执行"
                    logger.error(detail)
                    return False, failure_action, failure_jump_target, detail

                try:
                    combo_operations = _resolve_combo_operations(
                        combo_key_sequence_text,
                        params.get("combo_key_action", KEY_MOUSE_ACTION_COMPLETE),
                    )
                except ValueError as parse_error:
                    detail = f"[前台模式键盘按键] 可编辑内容解析失败: {parse_error}"
                    logger.error(detail)
                    return False, failure_action, failure_jump_target, detail

                if not combo_operations:
                    detail = "[前台模式键盘按键] 可编辑内容为空，无法执行"
                    logger.error(detail)
                    return False, failure_action, failure_jump_target, detail

                logger.info(f"[前台模式键盘按键] 可编辑内容解析成功，共 {len(combo_operations)} 步")
                combo_failure_detail: Dict[str, str] = {}
                if _execute_combo_expression_foreground(
                    driver,
                    combo_operations,
                    stop_checker,
                    foreground_input_manager=foreground_input,
                    target_hwnd=target_hwnd,
                    failure_detail=combo_failure_detail,
                    enable_repeat=_combo_key_repeat_enabled(params),
                    repeat_interval=_combo_key_repeat_interval(params),
                ):
                    logger.info("[前台模式键盘按键] 可编辑内容执行成功")
                    return True, success_action, success_jump_target
                detail = combo_failure_detail.get("message") or (
                    "[前台模式键盘按键] 可编辑内容执行失败。"
                    "如果组合键包含鼠标完整点击，请确认绑定目标窗口可见、未最小化，并且能被切到前台。"
                )
                logger.error(detail)
                return False, failure_action, failure_jump_target, detail

            except InterruptedError:
                return False, "停止工作流", None
            except Exception as e:
                detail = f"[前台模式键盘按键] 执行失败: {e}"
                logger.error(detail, exc_info=True)
                return False, failure_action, failure_jump_target, detail

        # 前台模式守卫：如果是前台模式但没有匹配到任何操作类型，返回错误
        if is_foreground_mode:
            logger.error(f"[前台模式] 不支持的输入类型: {input_type}")
            return False, failure_action, failure_jump_target

        # 前台分支已在上方严格结束；以下是显式后台模式分支。
        normalized_execution_mode = str(execution_mode or '').strip().lower()
        is_background_mode = normalized_execution_mode.startswith('background')
        if is_background_mode:
            if not target_hwnd:
                logger.error("无法执行后台模式：未提供目标窗口句柄 (target_hwnd)。")
                return False, failure_action, failure_jump_target

            logger.debug(f"开始执行键盘输入，模式: {execution_mode}，目标窗口: {target_hwnd}")

            # 键盘按键处理（后台模式）
            if input_type == KEY_MOUSE_INPUT_TYPE:
                logger.info("[后台模式] 处理键盘按键")
                try:
                    from utils.input_simulation import global_input_simulator_manager

                    # 获取输入模拟器
                    simulator = global_input_simulator_manager.get_simulator(
                        target_hwnd, "auto", execution_mode
                    )

                    if not simulator:
                        logger.error("[后台模式] 无法获取输入模拟器")
                        return False, failure_action, failure_jump_target

                    if not combo_key_sequence_text:
                        logger.error("[后台模式] 可编辑内容为空，无法执行")
                        return False, failure_action, failure_jump_target

                    try:
                        combo_operations = _resolve_combo_operations(
                            combo_key_sequence_text,
                            params.get("combo_key_action", KEY_MOUSE_ACTION_COMPLETE),
                        )
                    except ValueError as parse_error:
                        logger.error(f"[后台模式] 可编辑内容解析失败: {parse_error}")
                        return False, failure_action, failure_jump_target

                    if not combo_operations:
                        logger.error("[后台模式] 可编辑内容为空，无法执行")
                        return False, failure_action, failure_jump_target

                    logger.info(f"[后台模式] 可编辑内容解析成功，共 {len(combo_operations)} 步")
                    if _execute_combo_expression_background(
                        simulator,
                        combo_operations,
                        stop_checker,
                        enable_repeat=_combo_key_repeat_enabled(params),
                        repeat_interval=_combo_key_repeat_interval(params),
                    ):
                        logger.info("[后台模式] 可编辑内容执行成功")
                        return True, success_action, success_jump_target
                    logger.error("[后台模式] 可编辑内容执行失败")
                    return False, failure_action, failure_jump_target

                except InterruptedError:
                    return False, "停止工作流", None
                except Exception as e:
                    logger.error(f"[后台模式] 键盘按键执行失败: {e}", exc_info=True)
                    return False, failure_action, failure_jump_target

            # 其他input_type处理
            return False, failure_action, failure_jump_target

        return False, failure_action, failure_jump_target

    except Exception as e:
        logger.error(f"键盘输入执行失败: {e}", exc_info=True)
        return False, failure_action, failure_jump_target


def get_params_definition() -> Dict[str, Dict[str, Any]]:
    """获取参数定义"""
    from tasks.task_utils import (
        get_standard_next_step_delay_params,
        get_standard_action_params,
        merge_params_definitions,
    )

    standard_delay_params = get_standard_next_step_delay_params()
    standard_action_params = get_standard_action_params()

    keyboard_params = {
        "input_type": {
            "label": "输入类型",
            "type": "select",
            "options": [KEY_MOUSE_INPUT_TYPE, "文本输入"],
            "default": "文本输入",
            "tooltip": "选择键盘输入的类型"
        },

        # 文本输入参数
        "---text_input_params---": {
            "type": "separator",
            "label": "文本输入参数",
            "condition": {"param": "input_type", "value": "文本输入"}
        },
        "text_input_mode": {
            "label": "文本输入模式",
            "type": "select",
            "options": ["单组文本", "多组文本"],
            "default": "单组文本",
            "condition": {"param": "input_type", "value": "文本输入"}
        },
        "text_input_examples_button": {
            "label": "格式示例",
            "type": "button",
            "button_text": "查看格式示例",
            "tooltip": "查看文本输入的格式示例",
            "action": "show_text_examples",
            "condition": {"param": "input_type", "value": "文本输入"}
        },
        "text_to_type": {
            "label": "要输入的文本",
            "type": "textarea",
            "default": "",
            "tooltip": "原生前台使用 Unicode 键盘输入，后台发送字符消息。插件后端使用大漠文字接口，由插件设置控制输入法通道。原生后台开启层级广播时，目标窗口自动转发可能造成重复输入",
            "condition": [
                {"param": "input_type", "value": "文本输入"},
                {"param": "text_input_mode", "value": "单组文本"}
            ]
        },
        "text_groups": {
            "label": "多组文本",
            "type": "textarea",
            "default": "",
            "tooltip": "多组文本，每行一组",
            "condition": [
                {"param": "input_type", "value": "文本输入"},
                {"param": "text_input_mode", "value": "多组文本"}
            ]
        },
        "delay_between_keystrokes": {
            "label": "键间延迟(秒)",
            "type": "float",
            "default": 0.1,
            "min": 0.0,
            "max": 10.0,
            "decimals": 2,
            "tooltip": "原生仿真输入和插件文本输入每个字之间的间隔",
            "condition": {"param": "input_type", "value": "文本输入"}
        },
        "press_enter_after_text": {
            "label": "输入后按回车",
            "type": "bool",
            "default": False,
            "tooltip": "文本输入完成后自动按回车键",
            "condition": {"param": "input_type", "value": "文本输入"}
        },
        "reset_text_groups_on_next_run": {
            "label": "每次重新加载文本",
            "type": "bool",
            "default": False,
            "tooltip": "启用：每次执行都重新加载文本列表；禁用：仅在启动时加载一次",
            "condition": [
                {"param": "input_type", "value": "文本输入"},
                {"param": "text_input_mode", "value": "多组文本"}
            ]
        },
        "---keyboard_key_params---": {
            "type": "separator",
            "label": "键盘按键参数",
            "condition": {"param": "input_type", "value": KEY_MOUSE_INPUT_TYPE}
        },
        "combo_key_repeat": {
            "label": "按住方式",
            "type": "select",
            "options": {False: "持续按下", True: "连发"},
            "default": True,
            "tooltip": "持续按下：只按下一次，保持到松开；连发：按住期间按重复率或指定间隔补发。用于按下、等待、松开的序列，不改变单次点按或明确指定的连按次数。",
            "condition": {"param": "input_type", "value": KEY_MOUSE_INPUT_TYPE}
        },
        "combo_key_repeat_interval": {
            "label": "连发间隔(秒)",
            "type": "float",
            "default": 0.0,
            "min": 0.0,
            "max": 60.0,
            "step": 0.01,
            "decimals": 3,
            "tooltip": "0使用系统键盘重复率；大于0时，每隔指定秒数连发一次。持续按下时不使用此参数。",
            "condition": {
                "param": "input_type", "value": KEY_MOUSE_INPUT_TYPE,
                "and": {"param": "combo_key_repeat", "value": True}
            }
        },
        "combo_key_sequence_text": {
            "label": "可编辑内容",
            "type": "textarea",
            "default": "",
            "height": 72,
            "placeholder": "示例1: a\n示例2: ctrl+shift+a\n示例3: key_down(ctrl), key_press(a,5,0.2), key_up(ctrl)\n示例4: ctrl(按下), a*5@0.2, ctrl(松开)\n示例5: mouse_left(500,300), wait 0.2, mouse_right(500,300)\n示例6: mouse_wheel_down(500,300,3)",
            "tooltip": "支持多段按键、快捷组合、命令式按键、重复间隔、等待、多个鼠标动作和滚轮；显式按下/按住的按键必须配套松开。",
            "condition": {"param": "input_type", "value": KEY_MOUSE_INPUT_TYPE}
        },
        "combo_key_sequence_record": {
            "label": "录制按键",
            "type": "button",
            "button_text": "开始录制按键",
            "action": "toggle_combo_key_sequence_record",
            "tooltip": "支持连续录制按键与多个鼠标单击或双击动作，坐标和动作间隔会一并写入。",
            "condition": {"param": "input_type", "value": KEY_MOUSE_INPUT_TYPE}
        },
        "combo_key_sequence_help": {
            "label": "详细说明",
            "type": "button",
            "button_text": "查看详细说明",
            "action": "show_combo_sequence_examples",
            "tooltip": "打开键盘按键的填写说明与示例",
            "condition": {"param": "input_type", "value": KEY_MOUSE_INPUT_TYPE}
        },
        "combo_key_sequence_mouse_coord_selector": {
            "label": "鼠标动作坐标",
            "type": "button",
            "button_text": "获取点击坐标",
            "tooltip": "用于插入鼠标动作或滚轮步骤",
            "condition": {"param": "input_type", "value": KEY_MOUSE_INPUT_TYPE},
            "widget_hint": "coordinate_selector_with_display",
            "related_params": ["combo_seq_mouse_x", "combo_seq_mouse_y"]
        },
        "combo_key_sequence_insert_mouse_action": {
            "label": "插入鼠标动作",
            "type": "button",
            "button_text": "插入鼠标动作",
            "action": "insert_combo_mouse_action_from_picker",
            "tooltip": "点击选择要插入的鼠标动作；可连续插入多个动作。",
            "condition": {"param": "input_type", "value": KEY_MOUSE_INPUT_TYPE}
        },
        "combo_seq_mouse_x": {
            "label": "鼠标X",
            "type": "int",
            "default": 0,
            "hidden": True,
            "condition": {"param": "input_type", "value": KEY_MOUSE_INPUT_TYPE}
        },
        "combo_seq_mouse_y": {
            "label": "鼠标Y",
            "type": "int",
            "default": 0,
            "hidden": True,
            "condition": {"param": "input_type", "value": KEY_MOUSE_INPUT_TYPE}
        },
    }

    return merge_params_definitions(
        keyboard_params,
        standard_delay_params,
        standard_action_params
    )
