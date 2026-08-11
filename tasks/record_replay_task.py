"""
录制和回放任务模块
支持录制鼠标和键盘操作，并按指定速度回放
仅支持前台模式，确保回放精准度
工作流执行时自动回放录制的操作
"""

import time
import json
import logging
import os
from typing import Dict, Any, Optional, Tuple
from pynput.mouse import Button, Controller as MouseController
from pynput.keyboard import Controller as KeyboardController, Key
from utils.app_paths import get_config_path
from utils.relative_mouse_move import perform_timed_relative_move
from utils.window_binding_utils import get_bound_windows_for_mode

try:
    import win32api
    import win32con
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False
    logging.warning("win32api 不可用，相对位移回放功能可能受限")

# 导入高精度计时器
try:
    from utils.high_precision_timer import HighPrecisionTimer, PerformanceMonitor
    HIGH_PRECISION_AVAILABLE = True
except ImportError:
    HIGH_PRECISION_AVAILABLE = False
    logging.warning("高精度计时器不可用，将使用标准time模块")

# 导入增强型输入控制器
try:
    from utils.enhanced_input import (
        create_mouse_controller,
        create_keyboard_controller,
        is_pydirectinput_available
    )
    ENHANCED_INPUT_AVAILABLE = True
except ImportError:
    ENHANCED_INPUT_AVAILABLE = False
    logging.warning("增强型输入控制器不可用，将使用标准pynput")

# 导入性能优化器
try:
    from utils.performance_optimizer import apply_playback_optimizations, restore_default_priority
    PERFORMANCE_OPTIMIZER_AVAILABLE = True
except ImportError:
    PERFORMANCE_OPTIMIZER_AVAILABLE = False
    logging.warning("性能优化器不可用")

logger = logging.getLogger(__name__)
TASK_NAME = '录制回放'



def get_params_definition() -> Dict[str, Any]:
    """返回参数定义"""
    return {
        # 录制参数
        "---record_params---": {
            "type": "separator",
            "label": "录制参数"
        },
        "recording_area": {
            "label": "录制区域",
            "type": "select",
            "options": ["全屏录制", "窗口录制"],
            "default": "全屏录制",
            "tooltip": "选择录制范围：全屏录制所有位置，窗口录制仅限绑定窗口内"
        },
        "recording_mode": {
            "label": "录制模式",
            "type": "select",
            "options": ["绝对坐标", "相对位移"],
            "default": "绝对坐标",
            "tooltip": "绝对坐标：记录鼠标的屏幕位置（通用）\n相对位移：记录鼠标的移动增量（适合锁鼠游戏）"
        },
        "record_mouse": {
            "label": "录制鼠标",
            "type": "checkbox",
            "default": True,
            "tooltip": "是否录制鼠标移动和点击"
        },
        "record_keyboard": {
            "label": "录制键盘",
            "type": "checkbox",
            "default": True,
            "tooltip": "是否录制键盘按键"
        },
        "recording_precision": {
            "label": "录制精度",
            "type": "select",
            "options": ["低 (0.2秒)", "中 (0.1秒)", "高 (0.05秒)", "极高 (0.01秒)"],
            "default": "中 (0.1秒)",
            "tooltip": "控制鼠标移动记录的精细程度。越高文件越大，但回放越精准"
        },
        "record_control": {
            "label": "录制",
            "type": "custom",
            "widget_hint": "record_control",
            "button_text": "开始录制",
            "tooltip": "按下快捷键开始/停止录制\n录制完成后点击下方【应用】按钮保存"
        },

        # 回放参数
        "---replay_params---": {
            "type": "separator",
            "label": "回放参数"
        },
        "speed": {
            "label": "回放速度",
            "type": "float",
            "default": 1.0,
            "min": 0.1,
            "max": 10.0,
            "step": 0.1,
            "decimals": 1,
            "tooltip": "回放速度倍率（1.0为正常速度，2.0为两倍速，0.5为半速）"
        },
        "loop_count": {
            "label": "循环次数",
            "type": "int",
            "default": 1,
            "min": 1,
            "max": 1000,
            "tooltip": "回放循环次数（1表示播放一次）"
        },
        "replay_control": {
            "label": "回放",
            "type": "custom",
            "widget_hint": "replay_control",
            "button_text": "测试回放",
            "tooltip": "测试已录制的操作（工作流执行时自动回放）"
        },
        "edit_actions": {
            "label": "步骤编辑",
            "type": "custom",
            "widget_hint": "action_editor",
            "button_text": "编辑步骤",
            "tooltip": "打开步骤编辑器，查看和编辑录制的操作步骤"
        },
        "recorded_actions": {
            "label": "",
            "type": "hidden",
            "default": "",
            "tooltip": "录制的动作数据（JSON格式）"
        },
    }


def execute_task(params: Dict[str, Any], counters: Dict[str, int],
                execution_mode='foreground', **kwargs) -> Tuple[bool, str, Optional[int]]:
    """执行回放任务（工作流执行时自动回放录制的操作）

    注意：录制回放仅支持前台模式
    """
    logger.info("开始执行录制回放任务")

    stop_checker = kwargs.get('stop_checker', None)
    pause_checker = kwargs.get('pause_checker', None)

    # 工作流执行时，始终执行回放
    try:
        return _execute_replay(params, counters, stop_checker, pause_checker, kwargs)
    except Exception as e:
        logger.error(f"录制回放任务执行失败: {e}", exc_info=True)
        return False, '执行下一步', None


def _execute_replay(params: Dict[str, Any], counters: Dict[str, int],
                   stop_checker, pause_checker, kwargs, highlight_callback=None) -> Tuple[bool, str, Optional[int]]:
    """执行回放（前台模式，使用高精度计时）

    Args:
        params: 参数字典
        counters: 计数器字典
        stop_checker: 停止检查函数
        kwargs: 其他参数
        highlight_callback: 高亮回调函数，用于在回放时高亮当前步骤
    """
    speed = float(params.get('speed', 1.0))
    loop_count_raw = params.get('loop_count', 1)
    loop_count = int(loop_count_raw) if loop_count_raw is not None else 1
    if loop_count <= 0:
        loop_count = 1
    logger.info(f"[回放任务] 回放参数: speed={speed}, loop_count={loop_count}, raw={loop_count_raw}")
    start_from_index = int(params.get('start_from_index', 0))  # 新增：起始索引

    # 获取录制数据
    recorded_actions_json = params.get('recorded_actions', '')
    if not recorded_actions_json:
        # 尝试从counters获取
        card_id = kwargs.get('card_id')
        if card_id:
            recorded_actions_json = counters.get(f'__recorded_actions_{card_id}', '')

    if not recorded_actions_json:
        logger.warning("没有可回放的录制数据，跳过当前回放步骤")
        return True, '执行下一步', None

    try:
        if isinstance(recorded_actions_json, str):
            data = json.loads(recorded_actions_json)
        else:
            data = recorded_actions_json

        # 兼容新旧格式
        if isinstance(data, dict) and 'actions' in data:
            # 新格式：包含元数据
            recording_area = data.get('recording_area', '全屏录制')
            recording_mode = data.get('recording_mode', '绝对坐标')
            actions = data['actions']
        elif isinstance(data, list):
            # 旧格式：纯动作列表
            recording_area = '全屏录制'
            recording_mode = '绝对坐标'
            actions = data
        else:
            logger.error("录制数据格式错误")
            return False, '停止工作流', None

    except json.JSONDecodeError as e:
        logger.error(f"录制数据格式错误: {e}")
        return False, '停止工作流', None

    if not actions:
        logger.warning("录制数据为空，跳过当前回放步骤")
        return True, '执行下一步', None

    logger.info(f"录制数据解析完成: 区域={recording_area}, 模式={recording_mode}, 动作数={len(actions)}")

    # 验证起始索引
    if start_from_index < 0 or start_from_index >= len(actions):
        logger.warning(f"起始索引 {start_from_index} 超出范围，重置为0")
        start_from_index = 0

    if start_from_index > 0:
        logger.info(f"将从第 {start_from_index + 1} 步开始回放（跳过前 {start_from_index} 步）")

    # 窗口录制模式：获取当前窗口位置并激活窗口
    window_offset_x, window_offset_y = 0, 0
    if recording_area == '窗口录制':
        try:
            import win32gui
            import ctypes

            # 【关键修复】优先使用传入的target_hwnd参数，而不是从config.json读取
            # 这样标签页绑定的窗口才能生效
            target_hwnd = kwargs.get('target_hwnd', None)
            hwnd = target_hwnd
            if hwnd:
                logger.info(f"使用传入的窗口句柄: {hwnd} (来自标签页绑定或全局配置)")
            else:
                # 如果没有传入target_hwnd，回退到从config.json读取（向下兼容）
                logger.warning(f"未传入target_hwnd，回退到从config.json读取窗口句柄")
                try:
                    config_path = get_config_path()
                    if os.path.exists(config_path):
                        with open(config_path, 'r', encoding='utf-8') as f:
                            config_data = json.load(f)

                        # 从当前生效窗口列表获取 hwnd
                        bound_windows = get_bound_windows_for_mode(config_data)
                        if bound_windows:
                            for window_info in bound_windows:
                                if window_info.get('enabled', True):
                                    hwnd = window_info.get('hwnd')
                                    if hwnd:
                                        logger.info(f"从config.json获取窗口句柄: {hwnd}")
                                        break
                except Exception as e:
                    logger.error(f"从config.json读取窗口句柄失败: {e}")
                    return False, '执行下一步', None

            if hwnd and win32gui.IsWindow(hwnd):
                # 【关键】使用与录制相同的激活逻辑 - 查找顶级父窗口并使用TOPMOST激活
                logger.info(f"[录制回放] ========== 开始窗口激活流程 ==========")
                logger.info(f"[录制回放] 绑定窗口句柄: {hwnd}")

                try:
                    import win32process
                    import win32con

                    # 步骤0: 查找顶级父窗口（主窗口）
                    logger.info(f"[录制回放] 步骤0: 查找顶级父窗口...")
                    target_hwnd = hwnd
                    parent = win32gui.GetParent(hwnd)

                    # 如果有父窗口，向上查找到顶级窗口
                    while parent != 0:
                        target_hwnd = parent
                        parent = win32gui.GetParent(parent)

                    # 如果找到了父窗口，记录信息
                    if target_hwnd != hwnd:
                        parent_title = win32gui.GetWindowText(target_hwnd)
                        child_title = win32gui.GetWindowText(hwnd)
                        logger.info(f"[录制回放] 检测到子窗口，将激活父窗口: 父窗口={target_hwnd} ({parent_title}), 子窗口={hwnd} ({child_title})")
                    else:
                        window_title = win32gui.GetWindowText(hwnd)
                        logger.info(f"[录制回放] 未检测到父窗口，将激活当前窗口: {hwnd} ({window_title})")

                    # 使用找到的顶级窗口进行激活
                    activation_hwnd = target_hwnd

                    # 步骤1: 恢复最小化的窗口
                    logger.info(f"[录制回放] 步骤1: 检查窗口是否最小化...")
                    if win32gui.IsIconic(activation_hwnd):
                        logger.info(f"[录制回放] 窗口已最小化，正在恢复: {activation_hwnd}")
                        win32gui.ShowWindow(activation_hwnd, win32con.SW_RESTORE)
                        time.sleep(0.1)
                    else:
                        logger.info(f"[录制回放] 窗口未最小化")

                    # 步骤2: 确保窗口可见并在顶层
                    logger.info(f"[录制回放] 步骤2: 显示窗口...")
                    win32gui.ShowWindow(activation_hwnd, win32con.SW_SHOW)
                    time.sleep(0.05)

                    # 步骤3: 将窗口置于最顶层（临时）
                    logger.info(f"[录制回放] 步骤3: 设置窗口为TOPMOST...")
                    HWND_TOPMOST = -1
                    HWND_NOTOPMOST = -2
                    SWP_NOMOVE = 0x0002
                    SWP_NOSIZE = 0x0001
                    SWP_SHOWWINDOW = 0x0040

                    # 设置为topmost
                    ctypes.windll.user32.SetWindowPos(
                        activation_hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
                    )
                    time.sleep(0.1)
                    logger.info(f"[录制回放] 已设置为TOPMOST")

                    # 步骤4: 获取线程ID并附加输入
                    logger.info(f"[录制回放] 步骤4: 附加线程输入...")
                    foreground_hwnd = win32gui.GetForegroundWindow()
                    foreground_thread_id = None  # 在外层定义，避免作用域问题
                    target_thread_id = None

                    if foreground_hwnd != 0:
                        foreground_thread_id = win32process.GetWindowThreadProcessId(foreground_hwnd)[0]
                        target_thread_id = win32process.GetWindowThreadProcessId(activation_hwnd)[0]
                        logger.info(f"[录制回放] 前台窗口: {foreground_hwnd}, 前台线程: {foreground_thread_id}, 目标线程: {target_thread_id}")

                        # 附加线程输入
                        if foreground_thread_id != target_thread_id:
                            ctypes.windll.user32.AttachThreadInput(foreground_thread_id, target_thread_id, True)
                            logger.info(f"[录制回放] 已附加线程输入")
                        else:
                            logger.info(f"[录制回放] 前台线程与目标线程相同，无需附加")
                    else:
                        logger.warning(f"[录制回放] 无法获取前台窗口")

                    # 步骤5: 设置为前台窗口
                    logger.info(f"[录制回放] 步骤5: 设置为前台窗口...")
                    win32gui.SetForegroundWindow(activation_hwnd)
                    time.sleep(0.1)
                    current_fg = win32gui.GetForegroundWindow()
                    logger.info(f"[录制回放] SetForegroundWindow后，当前前台窗口: {current_fg}")

                    # 步骤6: 取消topmost，恢复为普通窗口
                    logger.info(f"[录制回放] 步骤6: 取消TOPMOST...")
                    ctypes.windll.user32.SetWindowPos(
                        activation_hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
                    )

                    # 步骤7: 分离线程输入
                    logger.info(f"[录制回放] 步骤7: 分离线程输入...")
                    if foreground_hwnd != 0 and foreground_thread_id is not None and target_thread_id is not None:
                        if foreground_thread_id != target_thread_id:
                            ctypes.windll.user32.AttachThreadInput(foreground_thread_id, target_thread_id, False)
                            logger.info(f"[录制回放] 已分离线程输入")

                    # 步骤8: 再次确认窗口在前台
                    logger.info(f"[录制回放] 步骤8: 再次确认窗口在前台...")
                    win32gui.BringWindowToTop(activation_hwnd)
                    time.sleep(0.2)

                    final_fg = win32gui.GetForegroundWindow()
                    window_title = win32gui.GetWindowText(activation_hwnd)
                    logger.info(f"[录制回放] 激活完成! 目标窗口: {activation_hwnd} ({window_title}), 当前前台: {final_fg}")

                    if final_fg == activation_hwnd:
                        logger.info(f"[录制回放] ✓ 窗口激活成功!")
                    else:
                        logger.warning(f"[录制回放] ✗ 窗口可能未激活成功，前台窗口不匹配")

                except Exception as e:
                    logger.error(f"[录制回放] ✗ 激活窗口过程发生异常: {e}", exc_info=True)
                    # 尝试备用方法：简单激活
                    try:
                        logger.info(f"[录制回放] 尝试备用激活方法...")
                        win32gui.ShowWindow(hwnd, 5)  # SW_SHOW
                        win32gui.SetForegroundWindow(hwnd)
                    except:
                        pass

                logger.info(f"[录制回放] ========== 窗口激活流程结束 ==========")

                # 【关键】已在激活流程中等待0.2秒，无需额外等待

                # 获取窗口位置（用于坐标转换）
                # 【修复】使用客户区坐标而不是窗口矩形，确保与录制时一致
                try:
                    # 获取客户区在屏幕上的位置
                    client_pos = win32gui.ClientToScreen(hwnd, (0, 0))
                    window_offset_x, window_offset_y = client_pos[0], client_pos[1]

                    # 获取窗口矩形用于对比
                    window_rect = win32gui.GetWindowRect(hwnd)
                    window_title = win32gui.GetWindowText(hwnd)

                    logger.info(f"窗口回放模式: 句柄={hwnd}, 标题={window_title}")
                    logger.info(f"  窗口矩形 (含边框): ({window_rect[0]}, {window_rect[1]})")
                    logger.info(f"  客户区位置 (实际使用): ({window_offset_x}, {window_offset_y})")
                    logger.info(f"  边框偏移: ({window_offset_x - window_rect[0]}, {window_offset_y - window_rect[1]})")
                except Exception as e:
                    logger.warning(f"获取客户区位置失败，回退到窗口矩形: {e}")
                    rect = win32gui.GetWindowRect(hwnd)
                    window_offset_x, window_offset_y = rect[0], rect[1]
                    window_title = win32gui.GetWindowText(hwnd)
                    logger.info(f"窗口回放模式: 句柄={hwnd}, 标题={window_title}, 窗口位置: ({window_offset_x}, {window_offset_y})")
            else:
                logger.error(f"窗口句柄无效或窗口不存在 (hwnd={hwnd})，无法进行窗口回放")
                return False, '执行下一步', None
        except Exception as e:
            logger.error(f"获取窗口位置失败: {e}")
            return False, '执行下一步', None

    logger.info(f"开始回放 ({recording_area}) {len(actions)} 个操作，速度: {speed}x, 循环: {loop_count} 次")

    # 智能性能优化（仅在高负载时提升优先级）
    if PERFORMANCE_OPTIMIZER_AVAILABLE:
        apply_playback_optimizations()  # 默认智能模式

    # 初始化高精度计时器和性能监控
    if HIGH_PRECISION_AVAILABLE:
        timer = HighPrecisionTimer()
        perf_monitor = PerformanceMonitor()
        logger.info("使用高精度计时器进行回放")
    else:
        timer = None
        perf_monitor = None
        logger.info("使用标准time模块进行回放")

    # 初始化增强型输入控制器
    if ENHANCED_INPUT_AVAILABLE:
        mouse_ctrl = create_mouse_controller(prefer_pydirectinput=True)
        keyboard_ctrl = create_keyboard_controller(prefer_pydirectinput=True)
        if is_pydirectinput_available():
            logger.info("使用PyDirectInput进行输入控制（极低延迟模式）")
        else:
            logger.info("PyDirectInput不可用，使用pynput")
    else:
        mouse_ctrl = MouseController()
        keyboard_ctrl = KeyboardController()
        logger.info("使用标准pynput进行输入控制")

    def _move_mouse_to_with_retry(
        target_x: int,
        target_y: int,
        max_attempts: int = 3,
        timeout: float = 0.08,
        tolerance: int = 2,
    ) -> bool:
        x = int(target_x)
        y = int(target_y)
        attempts = max(1, int(max_attempts))
        wait_timeout = max(0.01, float(timeout))
        tol = max(0, int(tolerance))

        for _ in range(attempts):
            try:
                mouse_ctrl.position = (x, y)
            except Exception as e:
                logger.warning(f"[回放] 鼠标移动失败: {e}")
                return False

            deadline = time.perf_counter() + wait_timeout
            while time.perf_counter() <= deadline:
                try:
                    cur_x, cur_y = mouse_ctrl.position
                except Exception:
                    cur_x, cur_y = x, y
                if abs(int(cur_x) - x) <= tol and abs(int(cur_y) - y) <= tol:
                    return True
                time.sleep(0.002)

        return False

    def _wait_if_paused(replay_start_time_val: float) -> tuple[float, bool]:
        if not pause_checker:
            return replay_start_time_val, False
        if not pause_checker():
            return replay_start_time_val, False
        logger.info("回放已暂停，等待恢复...")
        pause_start_time = timer.get_time() if timer else time.time()
        while pause_checker():
            if stop_checker and stop_checker():
                logger.info("回放被用户中断")
                return replay_start_time_val, True
            time.sleep(0.05)
        pause_end_time = timer.get_time() if timer else time.time()
        pause_duration = pause_end_time - pause_start_time
        logger.info(f"回放已恢复，暂停时长: {pause_duration:.3f}秒")
        return replay_start_time_val + pause_duration, False

    # 执行回放循环
    for loop in range(loop_count):
        if loop > 0:
            logger.info(f"开始第 {loop + 1}/{loop_count} 次循环")

        # 使用高精度计时器
        if timer:
            replay_start_time = timer.get_time()
        else:
            replay_start_time = time.time()

        # 从指定索引开始回放
        for i in range(start_from_index, len(actions)):
            # 暂停检查（暂停期间顺延回放时间基准）
            replay_start_time, paused_stopped = _wait_if_paused(replay_start_time)
            if paused_stopped:
                if perf_monitor:
                    perf_monitor.print_report()
                return False, '停止工作流', None

            # 调用高亮回调（如果提供）
            if highlight_callback:
                try:
                    highlight_callback(i)
                except Exception as e:
                    logger.warning(f"高亮回调失败: {e}")

            # 检查停止信号
            if stop_checker and stop_checker():
                logger.info("回放被用户中断")
                if perf_monitor:
                    perf_monitor.print_report()
                return False, '停止工作流', None

            action = actions[i]
            action_type = action.get('type')
            action_time = action.get('time', 0)

            # 计算该动作应该在什么时候执行（相对于回放开始的时间）
            scheduled_time = action_time / speed
            target_time = replay_start_time + scheduled_time

            # 等待到目标时间（加入停止检查，避免长等待时无法终止）
            if timer:
                # 使用高精度计时器，分片等待以便响应停止
                while True:
                    now = timer.get_time()
                    remaining = target_time - now
                    if remaining <= 0:
                        break
                    # 暂停检查
                    if pause_checker and pause_checker():
                        replay_start_time, paused_stopped = _wait_if_paused(replay_start_time)
                        if paused_stopped:
                            if perf_monitor:
                                perf_monitor.print_report()
                            return False, '停止工作流', None
                        target_time = replay_start_time + scheduled_time
                        continue
                    if stop_checker and stop_checker():
                        logger.info("回放被用户中断")
                        if hasattr(_execute_replay, '_replay_engine'):
                            try:
                                _execute_replay._replay_engine.stop()
                            except Exception:
                                pass
                        if perf_monitor:
                            perf_monitor.print_report()
                        return False, '停止工作流', None
                    # 10ms粒度等待，兼顾精度与可中断性
                    sleep_time = min(0.01, remaining)
                    timer.precise_sleep(sleep_time)

                # 记录时间误差
                if perf_monitor:
                    expected_time = replay_start_time + scheduled_time
                    perf_monitor.record_timing_error(expected_time, timer.get_time())
            else:
                now = time.time()
                delay = target_time - now
                if delay > 0:
                    while delay > 0:
                        # 暂停检查
                        if pause_checker and pause_checker():
                            replay_start_time, paused_stopped = _wait_if_paused(replay_start_time)
                            if paused_stopped:
                                if perf_monitor:
                                    perf_monitor.print_report()
                                return False, '停止工作流', None
                            target_time = replay_start_time + scheduled_time
                            delay = target_time - time.time()
                            continue
                        if stop_checker and stop_checker():
                            logger.info("回放被用户中断")
                            if hasattr(_execute_replay, '_replay_engine'):
                                try:
                                    _execute_replay._replay_engine.stop()
                                except Exception:
                                    pass
                            if perf_monitor:
                                perf_monitor.print_report()
                            return False, '停止工作流', None
                        sleep_time = min(0.05, delay)
                        time.sleep(sleep_time)
                        delay = target_time - time.time()
                elif delay < -0.01:  # 如果延迟超过10ms，记录警告
                    logger.warning(f"回放动作 {i} 延迟: {-delay:.3f}秒")

            # 执行动作（在尽可能接近目标时间的时刻执行）
            try:
                if action_type == 'mouse_move':
                    x, y = action['x'], action['y']
                    # 窗口模式：转换相对坐标为绝对坐标
                    if recording_area == '窗口录制':
                        x += window_offset_x
                        y += window_offset_y
                    if not _move_mouse_to_with_retry(x, y):
                        logger.warning(f"[回放] 鼠标移动未到位: ({x}, {y})")
                        continue

                elif action_type == 'mouse_move_relative':
                    dx, dy = action.get('dx', 0), action.get('dy', 0)
                    try:
                        duration = max(0.0, float(action.get('duration', 0.0) or 0.0))
                    except (TypeError, ValueError):
                        duration = 0.0

                    def _send_relative_step(step_x: int, step_y: int) -> bool:
                        if WIN32_AVAILABLE:
                            win32api.mouse_event(win32con.MOUSEEVENTF_MOVE, int(step_x), int(step_y), 0, 0)
                            return True
                        logger.warning("[回放] Win32API 不可用，无法执行相对移动")
                        return _send_relative_move_via_sendinput(step_x, step_y)

                    if duration > 0:
                        if not perform_timed_relative_move(
                            dx,
                            dy,
                            duration,
                            _send_relative_step,
                            stop_checker=stop_checker,
                        ):
                            logger.warning(f"[replay] relative move incomplete: ({dx}, {dy}), duration={duration}")
                            continue
                    elif not _send_relative_step(dx, dy):
                        logger.warning(f"[回放] 相对移动失败：({dx}, {dy})")
                        continue
                elif action_type == 'mouse_click':
                    x, y = action['x'], action['y']
                    logger.info(f"[回放] 点击事件: 原始坐标=({x}, {y}), 录制区域={recording_area}")

                    # 窗口模式：转换相对坐标为绝对坐标
                    if recording_area == '窗口录制':
                        logger.info(f"[回放] 窗口模式: window_offset=({window_offset_x}, {window_offset_y})")
                        x += window_offset_x
                        y += window_offset_y
                        logger.info(f"[回放] 转换后屏幕坐标=({x}, {y})")
                    else:
                        logger.info(f"[回放] 全屏模式: 使用原始坐标({x}, {y})")

                    # 先移动鼠标到目标位置（与测试回放保持一致）
                    if not _move_mouse_to_with_retry(x, y):
                        logger.warning(f"[回放] 点击前鼠标移动未到位: ({x}, {y})")
                        continue
                    logger.info(f"[回放] 移动鼠标到 ({x}, {y})")

                    button_name = action.get('button', 'left')
                    pressed = action.get('pressed', True)

                    # 转换按钮名称
                    if button_name == 'left':
                        button = Button.left
                    elif button_name == 'right':
                        button = Button.right
                    elif button_name == 'middle':
                        button = Button.middle
                    else:
                        button = Button.left  # 默认左键

                    if pressed:
                        mouse_ctrl.press(button)
                        logger.info(f"[回放] 按下 {button_name} 键")
                    else:
                        mouse_ctrl.release(button)
                        logger.info(f"[回放] 释放 {button_name} 键")

                elif action_type == 'mouse_scroll':
                    dx, dy = action.get('dx', 0), action.get('dy', 0)
                    # WHEEL_DELTA = 120 是Windows标准滚轮单位
                    # pynput录制的值通常是1或-1，乘以120转换
                    if dy != 0:
                        wheel_delta = int(dy * 120)
                        win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, wheel_delta, 0)
                        logger.info(f"[回放] 垂直滚轮 dy={dy}, delta={wheel_delta}")
                    if dx != 0:
                        wheel_delta = int(dx * 120)
                        win32api.mouse_event(win32con.MOUSEEVENTF_HWHEEL, 0, 0, wheel_delta, 0)
                        logger.info(f"[回放] 水平滚轮 dx={dx}, delta={wheel_delta}")

                elif action_type == 'key_press':
                    # 使用统一的回放引擎处理按键（Windows API + 扫描码，解决按键丢失问题）
                    key_str = action.get('key', '')
                    if key_str:
                        # 调用统一的回放引擎执行按键
                        from utils.replay_engine import ReplayEngine
                        if not hasattr(_execute_replay, '_replay_engine'):
                            _execute_replay._replay_engine = ReplayEngine()
                        _execute_replay._replay_engine.execute_action(action, recording_area, window_offset_x, window_offset_y, recording_mode)
                    else:
                        logger.warning(f"按键为空")

                elif action_type == 'key_release':
                    # 使用统一的回放引擎处理按键释放
                    key_str = action.get('key', '')
                    if key_str:
                        # 调用统一的回放引擎执行按键释放
                        from utils.replay_engine import ReplayEngine
                        if not hasattr(_execute_replay, '_replay_engine'):
                            _execute_replay._replay_engine = ReplayEngine()
                        _execute_replay._replay_engine.execute_action(action, recording_area, window_offset_x, window_offset_y, recording_mode)
                    else:
                        logger.warning(f"按键为空")

            except Exception as e:
                logger.warning(f"回放动作 {i} 失败: {e}")
                continue

        if loop < loop_count - 1:
            # 循环间隔
            if timer:
                timer.precise_sleep(0.5)
            else:
                time.sleep(0.5)

    # 打印性能报告
    if perf_monitor:
        perf_monitor.print_report()

    # 恢复默认优先级
    if PERFORMANCE_OPTIMIZER_AVAILABLE:
        restore_default_priority()

    logger.info("回放完成")
    return True, '执行下一步', None



def _send_relative_move_via_sendinput(dx: int, dy: int) -> bool:
    """使用绝对移动模拟相对移动（回退方案）

    注意：直接使用 MOUSEEVENTF_MOVE 标志会受鼠标加速影响，
    使用pynput的绝对移动来模拟相对移动是最可靠的方法。

    Args:
        dx: X轴相对偏移
        dy: Y轴相对偏移
    """
    try:
        from pynput.mouse import Controller
        mouse = Controller()

        # 获取当前位置
        current_x, current_y = mouse.position

        # 计算目标位置
        target_x = current_x + dx
        target_y = current_y + dy

        # 使用绝对移动
        mouse.position = (target_x, target_y)

    except Exception as e:
        logger.warning(f"pynput相对移动失败: {e}")
