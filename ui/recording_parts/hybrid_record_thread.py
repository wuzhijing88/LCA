"""
优化的录制线程 - 集成Raw Input和传统方式

支持三种录制模式:
1. Raw Input相对移动 (FPS游戏推荐)
2. 传统轮询相对移动 (兼容模式)
3. 绝对坐标录制 (普通操作)
"""

import json
import time
import logging
import threading
from typing import Optional, List, Dict, Any
from PySide6.QtCore import Signal, QThread

logger = logging.getLogger(__name__)

# 导入Raw Input录制器
try:
    from utils.raw_input_recorder import RawInputRecorder
    RAW_INPUT_AVAILABLE = True
except ImportError:
    RAW_INPUT_AVAILABLE = False
    logger.warning("Raw Input不可用，将使用传统方式")


class HybridRecordThread(QThread):
    """
    混合录制线程 - 智能选择最佳录制方式

    录制模式选择逻辑:
    - 相对位移 + Raw Input可用 → Raw Input (最佳精度)
    - 相对位移 + Raw Input不可用 → 传统轮询 (兼容)
    - 绝对坐标 → 传统轮询 (必需)
    """

    recording_finished = Signal(list)
    recording_progress = Signal(str)
    step_count_updated = Signal(int)

    def __init__(self,
                 duration: float,
                 record_mouse: bool,
                 record_keyboard: bool,
                 recording_area: str = "全屏录制",
                 window_rect: tuple = None,
                 mouse_move_interval: float = 0.1,
                 recording_mode: str = "绝对坐标",
                 filter_record_hotkey: str = None):
        super().__init__()

        self.duration = duration
        self.record_mouse = record_mouse
        self.record_keyboard = record_keyboard
        self.recording_area = recording_area
        self.window_rect = window_rect
        self.mouse_move_interval = mouse_move_interval
        self.recording_mode = recording_mode
        self.filter_record_hotkey = filter_record_hotkey

        self._filter_key_names = set()
        self._filter_mouse_buttons = set()
        self._init_record_hotkey_filter(filter_record_hotkey)

        self.recording_data = []
        self.recording_active = False
        self.start_time = 0
        self.step_count = 0

        self._pynput_listener_lock = threading.Lock()
        self._pynput_listeners = []

        # 选择录制方式
        self.use_raw_input = (
            recording_mode == "相对位移" and
            RAW_INPUT_AVAILABLE and
            self.record_mouse
            # Raw Input现在支持全屏和窗口录制（只记录相对移动，不受录制区域影响）
        )

        if self.use_raw_input:
            logger.info(f"✓ 使用 Raw Input 录制相对移动 (高精度) - 录制区域: {recording_area}")
        else:
            reason = []
            if recording_mode != "相对位移":
                reason.append(f"模式为{recording_mode}")
            if not RAW_INPUT_AVAILABLE:
                reason.append("Raw Input不可用")
            if not self.record_mouse:
                reason.append("未启用录制鼠标")

            reason_str = ", ".join(reason) if reason else "未知原因"
            logger.info(f"✓ 使用传统轮询录制 ({reason_str}) - 录制区域: {recording_area}")

    def run(self):
        """执行录制"""
        try:
            if self.use_raw_input:
                self._run_raw_input_mode()
            else:
                self._run_traditional_mode()
        except Exception as e:
            logger.error(f"录制失败: {e}", exc_info=True)
            self.recording_progress.emit(f"录制失败: {e}")
            self.recording_finished.emit([])
        finally:
            self._stop_tracked_pynput_listeners()

    def _track_pynput_listener(self, listener):
        if not listener:
            return
        with self._pynput_listener_lock:
            self._pynput_listeners.append(listener)

    def _untrack_pynput_listener(self, listener):
        if not listener:
            return
        with self._pynput_listener_lock:
            try:
                self._pynput_listeners.remove(listener)
            except ValueError:
                pass

    def _stop_tracked_pynput_listeners(self):
        with self._pynput_listener_lock:
            listeners = list(self._pynput_listeners)
            self._pynput_listeners.clear()

        for listener in listeners:
            try:
                listener.stop()
            except Exception:
                pass

    def _init_record_hotkey_filter(self, hotkey_value):
        """Initialize filter list for record hotkey events."""
        if not hotkey_value:
            return
        if isinstance(hotkey_value, (list, tuple, set)):
            for item in hotkey_value:
                self._add_hotkey_filter(item)
            return
        self._add_hotkey_filter(hotkey_value)

    def _add_hotkey_filter(self, hotkey_value):
        """Add a single hotkey value into filter sets."""
        try:
            key = str(hotkey_value).strip()
        except Exception:
            return
        if not key:
            return

        upper_key = key.upper()
        lower_key = key.lower()

        if upper_key in ("XBUTTON1", "XBUTTON2"):
            self._filter_mouse_buttons.add("x1" if upper_key == "XBUTTON1" else "x2")
            return

        # Handle direct stored values like "numpad_1"
        if lower_key.startswith("numpad_"):
            self._filter_key_names.add(lower_key)
            return

        if upper_key == "NUMLOCK":
            self._filter_key_names.add("num_lock")
            return

        if upper_key.startswith("NUM") and upper_key != "NUMLOCK":
            num_rest = upper_key[3:]
            num_map = {
                "0": "numpad_0",
                "1": "numpad_1",
                "2": "numpad_2",
                "3": "numpad_3",
                "4": "numpad_4",
                "5": "numpad_5",
                "6": "numpad_6",
                "7": "numpad_7",
                "8": "numpad_8",
                "9": "numpad_9",
                "MULTIPLY": "numpad_multiply",
                "ADD": "numpad_add",
                "SUBTRACT": "numpad_subtract",
                "DIVIDE": "numpad_divide",
                "DECIMAL": "numpad_decimal",
            }
            mapped = num_map.get(num_rest)
            if mapped:
                self._filter_key_names.add(mapped)
                # NumLock off alternate names
                alt_map = {
                    "numpad_0": "insert",
                    "numpad_1": "end",
                    "numpad_2": "down",
                    "numpad_3": "pagedown",
                    "numpad_4": "left",
                    "numpad_5": "clear",
                    "numpad_6": "right",
                    "numpad_7": "home",
                    "numpad_8": "up",
                    "numpad_9": "pageup",
                    "numpad_decimal": "delete",
                }
                alt_name = alt_map.get(mapped)
                if alt_name:
                    self._filter_key_names.add(alt_name)
            return

        if upper_key.startswith("F") and upper_key[1:].isdigit():
            self._filter_key_names.add(lower_key)
            return

        nav_map = {
            "HOME": "home",
            "END": "end",
            "INSERT": "insert",
            "DELETE": "delete",
            "PAGEUP": "pageup",
            "PAGEDOWN": "pagedown",
            "PRINTSCREEN": "printscreen",
            "SCROLLLOCK": "scrolllock",
            "PAUSE": "pause",
        }
        mapped = nav_map.get(upper_key)
        if mapped:
            self._filter_key_names.add(mapped)
            return

    def _run_raw_input_mode(self):
        """Raw Input录制模式"""
        try:
            # 创建Raw Input录制器
            raw_recorder = RawInputRecorder()

            # 启动录制
            if not raw_recorder.start_recording():
                logger.error("Raw Input录制启动失败，自动回退到传统轮询模式")
                self.recording_progress.emit("Raw Input启动失败，自动切换到传统模式")
                # 重置标志，回退到传统模式
                self.use_raw_input = False  # 标记为不使用Raw Input
                # 注意：不要设置 recording_active = False，让传统模式继续
                self._run_traditional_mode()
                return

            self.recording_progress.emit("Raw Input录制中... (高精度)")
            self.recording_active = True
            self.start_time = time.time()

            # 鼠标点击和滚轮录制（独立线程 - Raw Input只记录移动）
            mouse_click_thread = None
            mouse_click_data_list = []
            scroll_thread = None
            scroll_data_list = []
            if self.record_mouse:
                # 点击录制线程（使用win32api轮询）
                mouse_click_thread = threading.Thread(
                    target=self._record_mouse_clicks_polling,
                    args=(mouse_click_data_list,),
                    daemon=True
                )
                mouse_click_thread.start()

                # 滚轮录制线程（使用pynput，因为win32api无法轮询检测滚轮）
                scroll_thread = threading.Thread(
                    target=self._record_scroll_with_pynput,
                    args=(scroll_data_list,),
                    daemon=True
                )
                scroll_thread.start()

            # 键盘录制（如果需要）
            keyboard_thread = None
            keyboard_data_list = []
            if self.record_keyboard:
                keyboard_thread = threading.Thread(
                    target=self._record_keyboard_polling,
                    args=(keyboard_data_list,),
                    daemon=True
                )
                keyboard_thread.start()

            # 等待录制时长
            elapsed = 0
            while elapsed < self.duration and self.recording_active:
                time.sleep(0.1)
                elapsed = time.time() - self.start_time

                # 更新进度
                if int(elapsed) % 5 == 0 and elapsed > 0:
                    self.recording_progress.emit(
                        f"Raw Input录制中... {int(elapsed)}秒"
                    )

            # 停止录制
            raw_mouse_data = raw_recorder.stop_recording()
            self.recording_active = False

            # 合并数据：Raw Input移动 + 点击 + 滚轮 + 键盘
            all_data = raw_mouse_data.copy() if self.record_mouse else []

            # 添加鼠标点击数据
            if self.record_mouse and mouse_click_thread:
                mouse_click_thread.join(timeout=1.0)
                all_data.extend(mouse_click_data_list)

            # 添加滚轮数据
            if self.record_mouse and scroll_thread:
                scroll_thread.join(timeout=1.0)
                all_data.extend(scroll_data_list)

            # 添加键盘数据
            if self.record_keyboard and keyboard_thread:
                keyboard_thread.join(timeout=1.0)
                all_data.extend(keyboard_data_list)

            # 按时间排序
            all_data.sort(key=lambda x: x['time'])

            self.recording_data = all_data
            self.recording_progress.emit(
                f"Raw Input录制完成: {len(all_data)} 事件"
            )
            self.recording_finished.emit(all_data)

        except Exception as e:
            logger.error(f"Raw Input录制异常: {e}", exc_info=True)
            self.recording_progress.emit(f"Raw Input录制失败: {e}")
            self.recording_finished.emit([])

    def _run_traditional_mode(self):
        """传统录制模式 - 使用pynput钩子（鼠标+键盘）"""
        logger.info("开始录制模式（pynput钩子）")
        self.recording_data = []
        self.recording_active = True
        self.start_time = time.time()

        self.recording_progress.emit("录制中...")
        logger.info(f"录制模式启动: duration={self.duration}, recording_active={self.recording_active}")

        # 数据列表（由pynput监听器填充）
        mouse_data = []
        keyboard_data = []

        # 鼠标移动节流控制
        last_mouse_move_time = [0]  # 使用列表以便在闭包中修改
        last_mouse_pos = [None]

        # 启动鼠标监听线程
        mouse_thread = None
        if self.record_mouse:
            mouse_thread = threading.Thread(
                target=self._record_mouse_with_pynput,
                args=(mouse_data, last_mouse_move_time, last_mouse_pos),
                daemon=True
            )
            mouse_thread.start()
            logger.info("鼠标监听线程已启动（pynput钩子模式）")

        # 启动键盘监听线程
        keyboard_thread = None
        if self.record_keyboard:
            keyboard_thread = threading.Thread(
                target=self._record_keyboard_polling,
                args=(keyboard_data,),
                daemon=True
            )
            keyboard_thread.start()
            logger.info("键盘监听线程已启动（pynput钩子模式）")

        # 等待录制完成或超时
        while (time.time() - self.start_time) < self.duration and self.recording_active:
            time.sleep(0.05)

        # 停止录制
        self.recording_active = False

        # 等待线程结束
        if mouse_thread and mouse_thread.is_alive():
            mouse_thread.join(timeout=1.0)
        if keyboard_thread and keyboard_thread.is_alive():
            keyboard_thread.join(timeout=1.0)

        # 合并数据并按时间排序
        all_data = mouse_data + keyboard_data
        all_data.sort(key=lambda x: x.get('time', 0))
        self.recording_data = all_data

        logger.info(f"录制完成: elapsed={(time.time() - self.start_time):.2f}s, 鼠标事件={len(mouse_data)}, 键盘事件={len(keyboard_data)}, 总计={len(all_data)}")
        self.recording_progress.emit(f"录制完成: {len(all_data)} 事件")
        self.recording_finished.emit(self.recording_data)

    def _record_mouse_with_pynput(self, data_list, last_move_time, last_pos):
        """使用pynput监听器录制鼠标（基于SetWindowsHookEx，实时捕获）"""
        try:
            from pynput import mouse

            def on_move(x, y):
                if not self.recording_active:
                    return False
                timestamp = time.time() - self.start_time

                # 节流控制：根据mouse_move_interval限制移动事件频率
                if timestamp - last_move_time[0] < self.mouse_move_interval:
                    last_pos[0] = (x, y)
                    return

                # 计算坐标
                if self.recording_mode == "相对位移":
                    # 相对位移模式不限制窗口范围
                    if last_pos[0] is not None:
                        dx = x - last_pos[0][0]
                        dy = y - last_pos[0][1]
                        if dx != 0 or dy != 0:
                            data_list.append({
                                'type': 'mouse_move_relative',
                                'time': timestamp,
                                'dx': dx,
                                'dy': dy
                            })
                else:
                    # 绝对坐标模式：窗口录制时检查是否在窗口范围内
                    if self.recording_area == "窗口录制" and self.window_rect:
                        win_x, win_y, win_w, win_h = self.window_rect
                        if not (win_x <= x < win_x + win_w and win_y <= y < win_y + win_h):
                            last_pos[0] = (x, y)
                            return  # 窗口外的移动不录制
                        rel_x = x - win_x
                        rel_y = y - win_y
                    else:
                        rel_x, rel_y = x, y

                    data_list.append({
                        'type': 'mouse_move',
                        'time': timestamp,
                        'x': rel_x,
                        'y': rel_y
                    })

                last_move_time[0] = timestamp
                last_pos[0] = (x, y)

            def on_click(x, y, button, pressed):
                if not self.recording_active:
                    return False

                # 窗口录制模式：检查是否在窗口范围内
                if self.recording_area == "窗口录制" and self.window_rect:
                    win_x, win_y, win_w, win_h = self.window_rect
                    if not (win_x <= x < win_x + win_w and win_y <= y < win_y + win_h):
                        return  # 窗口外的点击不录制

                timestamp = time.time() - self.start_time

                # 转换按钮名称
                button_map = {
                    mouse.Button.left: 'left',
                    mouse.Button.right: 'right',
                    mouse.Button.middle: 'middle'
                }
                button_name = button_map.get(button, str(button))
                if self._filter_mouse_buttons:
                    button_name_lower = button_name.lower()
                    if ('x1' in button_name_lower and 'x1' in self._filter_mouse_buttons) or \
                       ('x2' in button_name_lower and 'x2' in self._filter_mouse_buttons):
                        return

                # 计算点击坐标
                click_x, click_y = x, y
                if self.recording_area == "窗口录制" and self.window_rect:
                    win_x, win_y = self.window_rect[0], self.window_rect[1]
                    click_x = x - win_x
                    click_y = y - win_y

                data_list.append({
                    'type': 'mouse_click',
                    'time': timestamp,
                    'x': click_x,
                    'y': click_y,
                    'button': button_name,
                    'pressed': pressed
                })
                if pressed:
                    self.step_count += 1
                    self.step_count_updated.emit(self.step_count)
                logger.info(f"[录制] 鼠标{button_name}键 {'按下' if pressed else '释放'} at ({click_x}, {click_y})")

            def on_scroll(x, y, dx, dy):
                if not self.recording_active:
                    return False

                # 窗口录制模式：检查是否在窗口范围内
                if self.recording_area == "窗口录制" and self.window_rect:
                    win_x, win_y, win_w, win_h = self.window_rect
                    if not (win_x <= x < win_x + win_w and win_y <= y < win_y + win_h):
                        return  # 窗口外的滚轮不录制

                timestamp = time.time() - self.start_time

                # pynput返回的dx/dy是归一化值(通常1或-1)
                # 直接存储，回放时会乘以120转换为Windows滚轮单位
                data_list.append({
                    'type': 'mouse_scroll',
                    'time': timestamp,
                    'dx': dx,
                    'dy': dy
                })
                self.step_count += 1
                self.step_count_updated.emit(self.step_count)
                logger.info(f"[录制] 鼠标滚轮 dx={dx}, dy={dy}")

            # 使用pynput监听器
            listener = mouse.Listener(on_move=on_move, on_click=on_click, on_scroll=on_scroll)
            self._track_pynput_listener(listener)
            try:
                listener.start()
                while self.recording_active:
                    time.sleep(0.05)
            finally:
                try:
                    listener.stop()
                except Exception:
                    pass
                try:
                    listener.join(timeout=1.0)
                except Exception:
                    pass
                self._untrack_pynput_listener(listener)

        except ImportError:
            raise RuntimeError("pynput模块不可用，无法录制鼠标")
        except Exception as e:
            raise RuntimeError(f"pynput鼠标监听失败: {e}")

    def _record_mouse_events_with_pynput(self, data_list):
        """鼠标点击和滚轮录制（使用pynput - 用于Raw Input模式）"""
        try:
            from pynput import mouse

            def on_click(x, y, button, pressed):
                if not self.recording_active:
                    return False

                timestamp = time.time() - self.start_time

                button_map = {
                    mouse.Button.left: 'left',
                    mouse.Button.right: 'right',
                    mouse.Button.middle: 'middle'
                }
                button_name = button_map.get(button, str(button))

                # 相对位移模式：记录绝对坐标（回放时会用到）
                click_x, click_y = x, y

                data_list.append({
                    'type': 'mouse_click',
                    'time': timestamp,
                    'x': click_x,
                    'y': click_y,
                    'button': button_name,
                    'pressed': pressed
                })
                if pressed:
                    self.step_count += 1
                    self.step_count_updated.emit(self.step_count)
                logger.info(f"[Raw Input点击录制] {button_name}键 {'按下' if pressed else '释放'} at ({click_x}, {click_y})")

            def on_scroll(x, y, dx, dy):
                if not self.recording_active:
                    return False

                timestamp = time.time() - self.start_time

                data_list.append({
                    'type': 'mouse_scroll',
                    'time': timestamp,
                    'dx': dx,
                    'dy': dy
                })
                self.step_count += 1
                self.step_count_updated.emit(self.step_count)
                logger.info(f"[Raw Input滚轮录制] dx={dx}, dy={dy}")

            listener = mouse.Listener(on_click=on_click, on_scroll=on_scroll)
            self._track_pynput_listener(listener)
            try:
                listener.start()
                while self.recording_active:
                    time.sleep(0.05)
            finally:
                try:
                    listener.stop()
                except Exception:
                    pass
                try:
                    listener.join(timeout=1.0)
                except Exception:
                    pass
                self._untrack_pynput_listener(listener)

        except Exception as e:
            logger.error(f"鼠标事件录制失败: {e}")

    def _record_mouse_clicks_polling(self, data_list):
        """鼠标点击录制（使用win32api轮询，获取准确位置）"""
        try:
            import win32api
            import win32con

            # 按键状态跟踪
            button_states = {
                'left': False,
                'right': False,
                'middle': False
            }
            button_vk = {
                'left': win32con.VK_LBUTTON,
                'right': win32con.VK_RBUTTON,
                'middle': win32con.VK_MBUTTON
            }

            while self.recording_active:
                timestamp = time.time() - self.start_time

                for button_name, vk_code in button_vk.items():
                    # 检查按键状态（高位表示按下）
                    state = win32api.GetAsyncKeyState(vk_code)
                    is_pressed = (state & 0x8000) != 0

                    # 状态变化时记录
                    if is_pressed != button_states[button_name]:
                        button_states[button_name] = is_pressed
                        # 使用win32api获取准确的鼠标位置
                        x, y = win32api.GetCursorPos()

                        # 窗口录制模式：转换为窗口相对坐标
                        click_x, click_y = x, y
                        if self.recording_area == "窗口录制" and self.window_rect:
                            win_x, win_y = self.window_rect[0], self.window_rect[1]
                            click_x = x - win_x
                            click_y = y - win_y

                        data_list.append({
                            'type': 'mouse_click',
                            'time': timestamp,
                            'x': click_x,
                            'y': click_y,
                            'button': button_name,
                            'pressed': is_pressed
                        })
                        if is_pressed:
                            self.step_count += 1
                            self.step_count_updated.emit(self.step_count)
                        logger.info(f"[win32api点击录制] {button_name}键 {'按下' if is_pressed else '释放'} at ({click_x}, {click_y})")

                time.sleep(0.005)  # 5ms轮询间隔

        except ImportError:
            raise RuntimeError("win32api模块不可用，无法录制鼠标点击")
        except Exception as e:
            raise RuntimeError(f"win32api鼠标点击录制失败: {e}")

    def _record_scroll_with_pynput(self, data_list):
        """滚轮录制（使用pynput，滚轮不需要位置信息）"""
        try:
            from pynput import mouse

            def on_scroll(x, y, dx, dy):
                if not self.recording_active:
                    return False

                timestamp = time.time() - self.start_time

                # 滚轮只记录方向和量，不记录位置
                # 回放时在当前鼠标位置滚动
                data_list.append({
                    'type': 'mouse_scroll',
                    'time': timestamp,
                    'dx': dx,
                    'dy': dy
                })
                self.step_count += 1
                self.step_count_updated.emit(self.step_count)
                logger.info(f"[pynput滚轮录制] dx={dx}, dy={dy}")

            listener = mouse.Listener(on_scroll=on_scroll)
            self._track_pynput_listener(listener)
            try:
                listener.start()
                while self.recording_active:
                    time.sleep(0.05)
            finally:
                try:
                    listener.stop()
                except Exception:
                    pass
                try:
                    listener.join(timeout=1.0)
                except Exception:
                    pass
                self._untrack_pynput_listener(listener)

        except ImportError:
            raise RuntimeError("pynput模块不可用，无法录制滚轮")
        except Exception as e:
            raise RuntimeError(f"pynput滚轮录制失败: {e}")

    def _record_keyboard_polling(self, data_list):
        """键盘录制（使用pynput监听器，比轮询更准确）"""
        try:
            from pynput import keyboard

            def on_press(key):
                if not self.recording_active:
                    return False  # 停止监听
                timestamp = time.time() - self.start_time
                key_name = self._pynput_key_to_name(key)
                if key_name:
                    key_name = key_name.lower()
                if key_name and key_name in self._filter_key_names:
                    return
                if key_name:
                    data_list.append({
                        'type': 'key_press',
                        'time': timestamp,
                        'key': key_name
                    })
                    self.step_count += 1
                    self.step_count_updated.emit(self.step_count)

            def on_release(key):
                if not self.recording_active:
                    return False  # 停止监听
                timestamp = time.time() - self.start_time
                key_name = self._pynput_key_to_name(key)
                if key_name:
                    key_name = key_name.lower()
                if key_name and key_name in self._filter_key_names:
                    return
                if key_name:
                    data_list.append({
                        'type': 'key_release',
                        'time': timestamp,
                        'key': key_name
                    })

            listener = keyboard.Listener(on_press=on_press, on_release=on_release)
            self._track_pynput_listener(listener)
            try:
                listener.start()
                while self.recording_active:
                    time.sleep(0.05)  # 只用于检查停止标志
            finally:
                try:
                    listener.stop()
                except Exception:
                    pass
                try:
                    listener.join(timeout=1.0)
                except Exception:
                    pass
                self._untrack_pynput_listener(listener)

        except ImportError:
            raise RuntimeError("pynput模块不可用，无法录制键盘")
        except Exception as e:
            raise RuntimeError(f"pynput键盘监听失败: {e}")

    def _pynput_key_to_name(self, key):
        """将pynput按键对象转换为键名"""
        from pynput import keyboard

        # 特殊键映射
        special_key_map = {
            keyboard.Key.space: ' ',
            keyboard.Key.enter: 'enter',
            keyboard.Key.esc: 'esc',
            keyboard.Key.tab: 'tab',
            keyboard.Key.backspace: 'backspace',
            keyboard.Key.delete: 'delete',
            keyboard.Key.shift: 'shift',
            keyboard.Key.shift_l: 'lshift',
            keyboard.Key.shift_r: 'rshift',
            keyboard.Key.ctrl: 'ctrl',
            keyboard.Key.ctrl_l: 'lctrl',
            keyboard.Key.ctrl_r: 'rctrl',
            keyboard.Key.alt: 'alt',
            keyboard.Key.alt_l: 'lalt',
            keyboard.Key.alt_r: 'ralt',
            keyboard.Key.left: 'left',
            keyboard.Key.right: 'right',
            keyboard.Key.up: 'up',
            keyboard.Key.down: 'down',
            keyboard.Key.home: 'home',
            keyboard.Key.end: 'end',
            keyboard.Key.page_up: 'pageup',
            keyboard.Key.page_down: 'pagedown',
            keyboard.Key.insert: 'insert',
            keyboard.Key.caps_lock: 'caps_lock',
            keyboard.Key.num_lock: 'num_lock',
        }

        # F功能键
        for i in range(1, 13):
            special_key_map[getattr(keyboard.Key, f'f{i}', None)] = f'f{i}'

        # 数字小键盘按键 - VK码直接映射
        # Windows虚拟键码对应关系
        numpad_vk_map = {
            0x60: 'numpad_0',   # VK_NUMPAD0
            0x61: 'numpad_1',   # VK_NUMPAD1
            0x62: 'numpad_2',   # VK_NUMPAD2
            0x63: 'numpad_3',   # VK_NUMPAD3
            0x64: 'numpad_4',   # VK_NUMPAD4
            0x65: 'numpad_5',   # VK_NUMPAD5
            0x66: 'numpad_6',   # VK_NUMPAD6
            0x67: 'numpad_7',   # VK_NUMPAD7
            0x68: 'numpad_8',   # VK_NUMPAD8
            0x69: 'numpad_9',   # VK_NUMPAD9
            0x6A: 'numpad_multiply',  # VK_MULTIPLY
            0x6B: 'numpad_add',       # VK_ADD
            0x6D: 'numpad_subtract',  # VK_SUBTRACT
            0x6E: 'numpad_decimal',   # VK_DECIMAL
            0x6F: 'numpad_divide',    # VK_DIVIDE
        }

        if key in special_key_map:
            return special_key_map[key]

        # 检查是否为数字小键盘按键（通过VK码判断）
        if hasattr(key, 'vk') and key.vk in numpad_vk_map:
            return numpad_vk_map[key.vk]

        # 普通字符键
        if hasattr(key, 'char') and key.char:
            return key.char.lower() if len(key.char) == 1 else key.char

        # 未知键
        return None

    def stop(self):
        """停止录制"""
        self.recording_active = False
        self._stop_tracked_pynput_listeners()


# 导出
__all__ = ['HybridRecordThread', 'RAW_INPUT_AVAILABLE']
