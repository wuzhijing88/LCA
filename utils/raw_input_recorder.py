"""
优化的鼠标相对移动录制器 - 使用Windows Raw Input API
基于2025年最佳实践，专为FPS游戏优化

主要特性：
1. 使用Raw Input API获取原始鼠标增量（未经Windows加速/缩放处理）
2. 高精度时间戳记录
3. 最小延迟的回放
4. 支持鼠标锁定场景（FPS游戏）
"""

import ctypes
from collections import deque
from ctypes import wintypes
import threading
import time
import logging
from typing import List, Dict, Callable, Optional, Deque

from utils.replay_engine import ReplayEngine

logger = logging.getLogger(__name__)

try:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
except Exception:
    user32 = None
    kernel32 = None


# ==================== Windows API 常量 ====================
WM_INPUT = 0x00FF
RID_INPUT = 0x10000003
RIDEV_INPUTSINK = 0x00000100
RIDEV_REMOVE = 0x00000001
HID_USAGE_PAGE_GENERIC = 0x01
HID_USAGE_GENERIC_MOUSE = 0x02
MOUSE_MOVE_RELATIVE = 0
LRESULT = wintypes.LPARAM

# ==================== Windows API 结构定义 ====================
class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", wintypes.LPVOID),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON)
    ]


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", wintypes.USHORT),
        ("usUsage", wintypes.USHORT),
        ("dwFlags", wintypes.DWORD),
        ("hwndTarget", wintypes.HWND)
    ]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", wintypes.DWORD),
        ("dwSize", wintypes.DWORD),
        ("hDevice", wintypes.HANDLE),
        ("wParam", wintypes.WPARAM)
    ]


class RAWMOUSE(ctypes.Structure):
    _fields_ = [
        ("usFlags", wintypes.USHORT),
        ("usButtonFlags", wintypes.USHORT),
        ("usButtonData", wintypes.USHORT),
        ("ulRawButtons", wintypes.ULONG),
        ("lLastX", ctypes.c_long),  # 原始X增量
        ("lLastY", ctypes.c_long),  # 原始Y增量
        ("ulExtraInformation", wintypes.ULONG)
    ]


class RAWINPUT(ctypes.Structure):
    _fields_ = [
        ("header", RAWINPUTHEADER),
        ("mouse", RAWMOUSE)
    ]


def _init_winapi_prototypes():
    if not user32 or not kernel32:
        return

    if getattr(_init_winapi_prototypes, "_initialized", False):
        return
    _init_winapi_prototypes._initialized = True

    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE

    user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
    user32.RegisterClassExW.restype = wintypes.ATOM

    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND

    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL

    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = LRESULT

    user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
    user32.PeekMessageW.restype = wintypes.BOOL

    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.TranslateMessage.restype = wintypes.BOOL

    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = LRESULT

    user32.RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE), wintypes.UINT, wintypes.UINT]
    user32.RegisterRawInputDevices.restype = wintypes.BOOL

    user32.GetRawInputData.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPVOID, ctypes.POINTER(wintypes.UINT), wintypes.UINT]
    user32.GetRawInputData.restype = wintypes.UINT

    user32.SendInput.argtypes = [wintypes.UINT, wintypes.LPVOID, ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT


class RawInputRecorder:
    """使用Raw Input API的高精度鼠标录制器"""

    def __init__(self):
        self.recording = False
        # 录制数据强制上限，避免长时间录制把主进程内存撑爆
        self._max_recorded_events = 200000
        self._dropped_events = 0
        self.recorded_data: Deque[Dict] = deque(maxlen=self._max_recorded_events)
        self.start_time = 0
        self.hwnd = None
        self._thread = None
        self._message_window_class = None
        self._init_success = False  # 初始化成功标志
        self._init_event = threading.Event()  # 初始化完成事件

    def _join_message_thread(self, timeout: float = 1.0) -> None:
        """等待消息线程退出并清理线程引用。"""
        thread = self._thread
        if thread and thread.is_alive():
            try:
                thread.join(timeout=timeout)
            except Exception:
                pass
        if thread is self._thread and (thread is None or not thread.is_alive()):
            self._thread = None

    def start_recording(self) -> bool:
        """开始录制鼠标原始输入"""
        if self.recording:
            logger.warning("录制已经在进行中")
            return False

        try:
            _init_winapi_prototypes()
            if not user32 or not kernel32:
                raise RuntimeError("Raw Input Recorder 仅支持 Windows")

            self.recorded_data.clear()
            self._dropped_events = 0
            self.start_time = time.perf_counter()
            self.recording = True
            self._init_success = False
            self._init_event.clear()

            # 在独立线程中创建消息循环
            self._thread = threading.Thread(target=self._message_loop, daemon=True)
            self._thread.start()

            # 等待初始化完成（最多等待2秒）
            if not self._init_event.wait(timeout=2.0):
                logger.error("Raw Input 初始化超时")
                self.recording = False
                self._join_message_thread(timeout=1.0)
                return False

            if not self._init_success:
                logger.error("Raw Input 初始化失败")
                self.recording = False
                self._join_message_thread(timeout=1.0)
                return False

            logger.info("✓ Raw Input 录制已启动")
            return True

        except Exception as e:
            logger.error(f"启动Raw Input录制失败: {e}", exc_info=True)
            self.recording = False
            self._join_message_thread(timeout=1.0)
            return False

    def stop_recording(self) -> List[Dict]:
        """停止录制并返回数据"""
        if not self.recording:
            logger.warning("没有正在进行的录制")
            return []

        self.recording = False

        # 注销Raw Input设备
        if self.hwnd:
            try:
                self._unregister_raw_input()
            except Exception as e:
                logger.error(f"注销Raw Input失败: {e}")

        # 等待线程结束
        self._join_message_thread(timeout=1.0)

        if self._dropped_events > 0:
            logger.warning(f"Raw Input录制达到上限，已丢弃最旧事件 {self._dropped_events} 条")
        logger.info(f"✓ 录制完成，共记录 {len(self.recorded_data)} 个原始移动事件")
        return list(self.recorded_data)

    def _message_loop(self):
        """Windows消息循环（在独立线程中运行）"""
        try:
            _init_winapi_prototypes()
            if not user32 or not kernel32:
                raise RuntimeError("Raw Input Recorder 仅支持 Windows")

            # 创建消息窗口
            self._create_message_window()

            if not self.hwnd:
                logger.error("创建消息窗口失败")
                self.recording = False  # 重置录制状态
                self._init_success = False
                self._init_event.set()  # 通知初始化失败
                return

            # 注册Raw Input设备
            if not self._register_raw_input():
                logger.error("注册Raw Input设备失败")
                self.recording = False  # 重置录制状态
                self._init_success = False
                self._init_event.set()  # 通知初始化失败
                return

            logger.debug(f"Raw Input消息窗口已创建，HWND: {self.hwnd}")

            # 初始化成功，通知主线程
            self._init_success = True
            self._init_event.set()

            # 消息循环
            msg = wintypes.MSG()
            while self.recording:
                # 非阻塞获取消息
                result = user32.PeekMessageW(
                    ctypes.byref(msg),
                    None,
                    0,
                    0,
                    1  # PM_REMOVE
                )

                if result:
                    if msg.message == WM_INPUT:
                        self._process_raw_input(msg.lParam)
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                else:
                    time.sleep(0.001)  # 1ms休眠避免CPU占用过高

            logger.debug("Raw Input消息循环结束")

        except Exception as e:
            logger.error(f"Raw Input消息循环异常: {e}", exc_info=True)
        finally:
            # 清理
            if self.hwnd:
                try:
                    user32.DestroyWindow(self.hwnd)
                except:
                    pass
                self.hwnd = None

    def _create_message_window(self):
        """创建隐藏的消息窗口"""
        try:
            # 窗口类名
            class_name = f"RawInputRecorder_{id(self)}"
            logger.debug(f"[Raw Input] 准备创建消息窗口，类名: {class_name}")

            # 定义窗口过程
            WndProcType = ctypes.WINFUNCTYPE(
                LRESULT,
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM
            )

            def wnd_proc(hwnd, msg, wparam, lparam):
                if msg == WM_INPUT:
                    return 0
                # 需要使用 c_int64 来处理可能的大整数
                return user32.DefWindowProcW(
                    wintypes.HWND(hwnd),
                    wintypes.UINT(msg),
                    wintypes.WPARAM(wparam),
                    wintypes.LPARAM(lparam)
                )

            self._wnd_proc = WndProcType(wnd_proc)

            # 获取模块句柄
            h_instance = kernel32.GetModuleHandleW(None)
            logger.debug(f"[Raw Input] 模块句柄: {h_instance}")

            # 注册窗口类
            wndclass = WNDCLASSEXW()
            wndclass.cbSize = ctypes.sizeof(WNDCLASSEXW)
            wndclass.lpfnWndProc = ctypes.cast(self._wnd_proc, wintypes.LPVOID)
            wndclass.hInstance = h_instance
            wndclass.lpszClassName = class_name

            class_atom = user32.RegisterClassExW(ctypes.byref(wndclass))
            if not class_atom:
                error_code = ctypes.get_last_error()
                logger.error(f"[Raw Input] 注册窗口类失败，错误码: {error_code}")
                return

            self._message_window_class = class_atom
            logger.debug(f"[Raw Input] 窗口类注册成功，atom: {class_atom}")

            # 创建消息窗口（隐藏）
            # 使用 MAKEINTATOM 将 class_atom 转换为字符串指针
            self.hwnd = user32.CreateWindowExW(
                0,  # dwExStyle
                class_name,
                "Raw Input Recorder",  # lpWindowName
                0,  # dwStyle
                0, 0, 0, 0,  # x, y, width, height
                None,  # hWndParent
                None,  # hMenu
                h_instance,  # hInstance
                None  # lpParam
            )

            if not self.hwnd:
                error_code = ctypes.get_last_error()
                logger.error(f"[Raw Input] 创建消息窗口失败，错误码: {error_code}")
            else:
                logger.debug(f"[Raw Input] 消息窗口创建成功，HWND: {self.hwnd}")

        except Exception as e:
            logger.error(f"创建消息窗口异常: {e}", exc_info=True)

    def _register_raw_input(self) -> bool:
        """注册Raw Input设备"""
        try:
            logger.debug("[Raw Input] 准备注册Raw Input设备...")
            rid = RAWINPUTDEVICE()
            rid.usUsagePage = HID_USAGE_PAGE_GENERIC
            rid.usUsage = HID_USAGE_GENERIC_MOUSE
            rid.dwFlags = RIDEV_INPUTSINK  # 即使窗口不在前台也接收输入
            rid.hwndTarget = self.hwnd

            result = user32.RegisterRawInputDevices(
                ctypes.byref(rid),
                1,
                ctypes.sizeof(RAWINPUTDEVICE)
            )

            if not result:
                error_code = ctypes.get_last_error()
                logger.error(f"[Raw Input] 注册Raw Input设备失败，错误码: {error_code}")
                return False

            logger.debug("[Raw Input] Raw Input设备注册成功")
            return True

        except Exception as e:
            logger.error(f"[Raw Input] 注册Raw Input设备异常: {e}", exc_info=True)
            return False

    def _unregister_raw_input(self):
        """注销Raw Input设备"""
        try:
            rid = RAWINPUTDEVICE()
            rid.usUsagePage = HID_USAGE_PAGE_GENERIC
            rid.usUsage = HID_USAGE_GENERIC_MOUSE
            rid.dwFlags = RIDEV_REMOVE
            rid.hwndTarget = None

            user32.RegisterRawInputDevices(
                ctypes.byref(rid),
                1,
                ctypes.sizeof(RAWINPUTDEVICE)
            )
        except Exception as e:
            logger.error(f"注销Raw Input设备异常: {e}")

    def _process_raw_input(self, lparam):
        """处理WM_INPUT消息"""
        try:
            # 获取数据大小
            size = wintypes.UINT()
            user32.GetRawInputData(
                lparam,
                RID_INPUT,
                None,
                ctypes.byref(size),
                ctypes.sizeof(RAWINPUTHEADER)
            )

            # 分配缓冲区
            buffer = ctypes.create_string_buffer(size.value)

            # 获取Raw Input数据
            result = user32.GetRawInputData(
                lparam,
                RID_INPUT,
                buffer,
                ctypes.byref(size),
                ctypes.sizeof(RAWINPUTHEADER)
            )

            if result == 0xFFFFFFFF:
                return

            # 解析数据
            raw_input = ctypes.cast(buffer, ctypes.POINTER(RAWINPUT)).contents

            # 只处理相对移动
            if raw_input.mouse.usFlags == MOUSE_MOVE_RELATIVE:
                dx = raw_input.mouse.lLastX
                dy = raw_input.mouse.lLastY

                # 只记录非零移动
                if dx != 0 or dy != 0:
                    timestamp = time.perf_counter() - self.start_time

                    if len(self.recorded_data) >= self._max_recorded_events:
                        self._dropped_events += 1
                    self.recorded_data.append({
                        'type': 'mouse_move_relative',
                        'time': timestamp,
                        'dx': dx,
                        'dy': dy
                    })

        except Exception as e:
            logger.error(f"处理Raw Input数据异常: {e}", exc_info=True)


class OptimizedMouseReplayer:
    """优化的鼠标回放器 - 复用统一回放引擎。"""

    @staticmethod
    def replay_relative_movements(actions: List[Dict], speed: float = 1.0) -> bool:
        """
        回放相对鼠标移动

        Args:
            actions: 动作列表，每个动作包含 type, time, dx, dy
            speed: 回放速度倍率

        Returns:
            是否成功完成回放
        """
        try:
            replay_actions = [
                action for action in actions
                if action.get('type') == 'mouse_move_relative'
            ]
            if not replay_actions:
                logger.info("没有可回放的相对移动事件")
                return True

            logger.info(f"开始回放相对移动事件，共 {len(replay_actions)} 条")
            replay_engine = ReplayEngine()
            success = replay_engine.replay(
                actions=replay_actions,
                speed=speed,
                loop_count=1,
                recording_area='全屏录制',
                window_offset_x=0,
                window_offset_y=0,
                precise_timer=None,
                recording_mode='相对位移',
            )
            if success:
                logger.info("✓ 相对移动回放完成")
            else:
                logger.warning("相对移动回放未完成")
            return success

        except Exception as e:
            logger.error(f"回放相对移动失败: {e}", exc_info=True)
            return False


# ==================== 使用示例 ====================
if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    logger.info("=" * 60)
    logger.info("Raw Input 鼠标录制测试")
    logger.info("=" * 60)
    logger.info("按Enter开始录制...")
    input()

    recorder = RawInputRecorder()
    recorder.start_recording()

    logger.info("✓ 录制已开始，移动鼠标进行测试")
    logger.info("按Enter停止录制...")
    input()

    data = recorder.stop_recording()

    logger.info(f"\n录制完成！共记录 {len(data)} 个移动事件")

    if data:
        logger.info("\n前5个事件:")
        for i, event in enumerate(data[:5]):
            logger.info(f"  {i+1}. 时间:{event['time']:.4f}s, dx:{event['dx']}, dy:{event['dy']}")

        logger.info("\n按Enter开始回放...")
        input()

        replayer = OptimizedMouseReplayer()
        replayer.replay_relative_movements(data, speed=1.0)

        logger.info("✓ 回放完成")
