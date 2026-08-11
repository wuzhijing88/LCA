"""
窗口句柄管理器
"""

import logging
import math
import time
import threading
from typing import Dict, Optional, Callable, Any, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class WindowInfo:
    """窗口信息"""
    hwnd: int
    title: str
    class_name: str = ""
    rect: Optional[Tuple[int, int, int, int]] = None
    last_update: float = 0.0

class WindowHandleManager:
    """窗口句柄管理器"""
    
    def __init__(self):
        self._window_registry: Dict[str, WindowInfo] = {}
        self._update_callbacks: Dict[str, Callable[[int, int], None]] = {}
        self._user_notification_callbacks = []  # 用户通知回调列表
        self._invalid_windows = {}  # 失效窗口记录
        self._lock = threading.RLock()
        self._monitoring = False
        self._monitor_thread = None
        self._monitor_stop_event = threading.Event()
        
        logger.info("窗口句柄管理器初始化完成")
    
    def register_window(self, key: str, hwnd: int, title: str) -> bool:
        """注册窗口"""
        try:
            with self._lock:
                snapshot = self._capture_window_snapshot(hwnd, title)
                window_info = WindowInfo(
                    hwnd=hwnd,
                    title=snapshot.get('title') or title,
                    class_name=snapshot.get('class_name', ''),
                    rect=snapshot.get('rect'),
                    last_update=time.time()
                )

                self._window_registry[key] = window_info
                logger.info(f"注册窗口: {key} -> HWND:{hwnd}, 标题:{title}")
                return True

        except Exception as e:
            logger.error(f"注册窗口失败: {e}")
            return False
    
    def get_window_hwnd(self, key: str) -> Optional[int]:
        """获取窗口句柄"""
        with self._lock:
            window_info = self._window_registry.get(key)
            if window_info:
                # 检查窗口是否仍然有效
                if self._is_window_valid(window_info.hwnd):
                    return window_info.hwnd
                else:
                    logger.warning(f"窗口句柄已失效: {key} -> HWND:{window_info.hwnd}")
                    # 尝试重新查找
                    new_hwnd = self._find_window_by_info(window_info)
                    if new_hwnd:
                        self._update_window_hwnd(key, new_hwnd)
                        return new_hwnd
            return None
    
    def add_update_callback(self, key: str, callback: Callable[[int, int], None]):
        """添加窗口句柄更新回调"""
        with self._lock:
            self._update_callbacks[key] = callback
            logger.debug(f"添加窗口句柄更新回调: {key}")

    def add_user_notification_callback(self, callback: Callable[[str, any], None]):
        """添加用户通知回调，当窗口句柄失效时调用"""
        with self._lock:
            if callback not in self._user_notification_callbacks:
                self._user_notification_callbacks.append(callback)
                logger.debug(f"添加用户通知回调: {callback}")

    def remove_user_notification_callback(self, callback: Callable[[str, any], None]):
        """移除用户通知回调"""
        with self._lock:
            if callback in self._user_notification_callbacks:
                self._user_notification_callbacks.remove(callback)
                logger.debug(f"移除用户通知回调: {callback}")

    def get_invalid_windows(self) -> dict:
        """获取失效的窗口列表"""
        with self._lock:
            return self._invalid_windows.copy()

    def clear_invalid_window(self, key: str):
        """清除失效窗口记录（用户重新绑定后调用）"""
        with self._lock:
            if key in self._invalid_windows:
                del self._invalid_windows[key]
                logger.debug(f"清除失效窗口记录: {key}")
    
    def remove_update_callback(self, key: str):
        """移除窗口句柄更新回调"""
        with self._lock:
            if key in self._update_callbacks:
                del self._update_callbacks[key]
                logger.debug(f"移除窗口句柄更新回调: {key}")
    
    def start_monitoring(self, interval: float = 5.0):
        """开始监控窗口句柄变化"""
        if self._monitoring:
            return
        
        self._monitoring = True
        self._monitor_stop_event.clear()
        
        def monitor_loop():
            while self._monitoring:
                try:
                    self._check_all_windows()
                    if self._monitor_stop_event.wait(interval):
                        break
                except Exception as e:
                    logger.error(f"窗口监控异常: {e}")
                    if self._monitor_stop_event.wait(interval):
                        break
        
        self._monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self._monitor_thread.start()
        logger.info(f"开始窗口句柄监控，间隔: {interval}秒")
    
    def stop_monitoring(self):
        """停止监控窗口句柄变化"""
        self._monitoring = False
        self._monitor_stop_event.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=2.0)
            self._monitor_thread = None
        logger.info("停止窗口句柄监控")

    def _check_all_windows(self):
        """检查所有注册的窗口"""
        # 【闪退修复】在锁内获取快照，然后在锁外进行耗时的窗口验证
        with self._lock:
            windows_snapshot = list(self._window_registry.items())

        # 在锁外检查窗口有效性（避免长时间持锁）
        for key, window_info in windows_snapshot:
            try:
                if not self._is_window_valid(window_info.hwnd):
                    logger.warning(f"检测到窗口句柄失效: {key} -> HWND:{window_info.hwnd}，窗口可能已关闭或重启，请手动重新绑定")
                    # 不再自动重新绑定，仅提示用户手动重新绑定
                    self._notify_user_rebind_needed(key, window_info)
            except Exception as e:
                logger.error(f"检查窗口 {key} 时发生异常: {e}")
    
    def _notify_user_rebind_needed(self, key: str, window_info):
        """通知用户需要手动重新绑定窗口"""
        try:
            window_title = window_info.title if hasattr(window_info, 'title') else '未知窗口'
            logger.warning(f"窗口句柄失效通知: '{window_title}' (绑定键: {key})")

            # 触发UI通知回调
            if hasattr(self, '_user_notification_callbacks') and self._user_notification_callbacks:
                for callback in self._user_notification_callbacks:
                    try:
                        callback(key, window_info)
                    except Exception as e:
                        logger.error(f"执行用户通知回调失败: {e}")

            # 记录失效的窗口，供UI查询
            if not hasattr(self, '_invalid_windows'):
                self._invalid_windows = {}
            self._invalid_windows[key] = {
                'window_info': window_info,
                'invalid_time': time.time(),
                'notified': True
            }

        except Exception as e:
            logger.error(f"通知用户重新绑定失败: {e}")

    def _is_window_valid(self, hwnd: int) -> bool:
        """检查窗口句柄是否有效"""
        try:
            import win32gui
            return win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd)
        except:
            return False

    def _capture_window_snapshot(self, hwnd: int, title: str = "") -> Dict[str, Any]:
        snapshot = {
            'title': str(title or '').strip(),
            'class_name': '',
            'rect': None,
        }
        try:
            import win32gui

            hwnd_int = int(hwnd or 0)
            if hwnd_int <= 0 or not win32gui.IsWindow(hwnd_int):
                return snapshot

            actual_title = str(win32gui.GetWindowText(hwnd_int) or '').strip()
            if actual_title:
                snapshot['title'] = actual_title

            try:
                snapshot['class_name'] = str(win32gui.GetClassName(hwnd_int) or '').strip()
            except Exception:
                snapshot['class_name'] = ''

            try:
                left, top, right, bottom = win32gui.GetWindowRect(hwnd_int)
                if right > left and bottom > top:
                    snapshot['rect'] = (int(left), int(top), int(right), int(bottom))
            except Exception:
                snapshot['rect'] = None
        except Exception:
            pass
        return snapshot

    @staticmethod
    def _window_match_score(window_info: WindowInfo, class_name: str, rect: Optional[Tuple[int, int, int, int]]) -> float:
        score = 0.0
        expected_class = str(getattr(window_info, 'class_name', '') or '').strip().lower()
        actual_class = str(class_name or '').strip().lower()
        if expected_class:
            score += 0.0 if expected_class == actual_class else 1_000_000.0

        expected_rect = getattr(window_info, 'rect', None)
        if not expected_rect or not rect:
            return score

        try:
            exp_left, exp_top, exp_right, exp_bottom = [int(v) for v in expected_rect]
            cur_left, cur_top, cur_right, cur_bottom = [int(v) for v in rect]
            exp_width = max(1, exp_right - exp_left)
            exp_height = max(1, exp_bottom - exp_top)
            cur_width = max(1, cur_right - cur_left)
            cur_height = max(1, cur_bottom - cur_top)
            exp_center_x = exp_left + (exp_width / 2.0)
            exp_center_y = exp_top + (exp_height / 2.0)
            cur_center_x = cur_left + (cur_width / 2.0)
            cur_center_y = cur_top + (cur_height / 2.0)
            center_distance = math.hypot(cur_center_x - exp_center_x, cur_center_y - exp_center_y)
            size_delta = abs(cur_width - exp_width) + abs(cur_height - exp_height)
            return score + center_distance + (size_delta * 0.25)
        except Exception:
            return score
    
    def _find_window_by_info(self, window_info: WindowInfo) -> Optional[int]:
        """根据窗口信息重新查找窗口句柄"""
        try:
            import win32gui

            # 通用方法：根据标题精确查找
            target_title = str(window_info.title or '').strip()
            if not target_title:
                return None

            candidates = []

            def collect_window_proc(hwnd, lParam):
                try:
                    if not win32gui.IsWindowVisible(hwnd):
                        return True

                    title = str(win32gui.GetWindowText(hwnd) or '').strip()
                    if title != target_title:
                        return True

                    class_name = ''
                    rect = None
                    try:
                        class_name = str(win32gui.GetClassName(hwnd) or '').strip()
                    except Exception:
                        class_name = ''
                    try:
                        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                        if right > left and bottom > top:
                            rect = (int(left), int(top), int(right), int(bottom))
                    except Exception:
                        rect = None
                    candidates.append((int(hwnd), class_name, rect))
                except Exception:
                    pass
                return True

            win32gui.EnumWindows(collect_window_proc, None)

            if not candidates:
                return None

            scored_candidates = sorted(
                candidates,
                key=lambda item: self._window_match_score(window_info, item[1], item[2]),
            )
            found_hwnd = int(scored_candidates[0][0])
            logger.info(f"通过窗口特征重新找到窗口: {window_info.title} -> HWND:{found_hwnd}")
            return found_hwnd


        except Exception as e:
            logger.error(f"重新查找窗口失败: {e}")
            return None
    
    def _update_window_hwnd(self, key: str, new_hwnd: int):
        """更新窗口句柄"""
        with self._lock:
            if key in self._window_registry:
                old_hwnd = self._window_registry[key].hwnd

                # 防抖：如果句柄没有真正改变，跳过更新
                if old_hwnd == new_hwnd:
                    return

                # 防抖：检查是否在短时间内重复更新
                current_time = time.time()
                last_update = self._window_registry[key].last_update
                if current_time - last_update < 2.0:  # 2秒内不重复更新
                    logger.debug(f"跳过重复更新窗口句柄: {key} (距离上次更新 {current_time - last_update:.1f}秒)")
                    return

                snapshot = self._capture_window_snapshot(new_hwnd, self._window_registry[key].title)
                self._window_registry[key].hwnd = new_hwnd
                if snapshot.get('title'):
                    self._window_registry[key].title = snapshot['title']
                self._window_registry[key].class_name = snapshot.get('class_name', '')
                self._window_registry[key].rect = snapshot.get('rect')
                self._window_registry[key].last_update = current_time

                logger.info(f"更新窗口句柄: {key} -> {old_hwnd} => {new_hwnd}")

                # 通知回调 - 使用线程安全的方式
                if key in self._update_callbacks:
                    try:
                        # 在新线程中执行回调，避免阻塞监控线程
                        callback = self._update_callbacks[key]

                        def safe_callback():
                            try:
                                callback(old_hwnd, new_hwnd)
                            except Exception as e:
                                logger.error(f"窗口句柄更新回调执行失败: {e}")

                        # 使用线程池执行回调，避免阻塞
                        import threading
                        callback_thread = threading.Thread(target=safe_callback, daemon=True)
                        callback_thread.start()

                    except Exception as e:
                        logger.error(f"启动窗口句柄更新回调线程失败: {e}")
    
    def unregister_window(self, key: str):
        """注销窗口"""
        with self._lock:
            if key in self._window_registry:
                del self._window_registry[key]
                logger.info(f"注销窗口: {key}")
            
            if key in self._update_callbacks:
                del self._update_callbacks[key]
    
    def get_all_registered_windows(self) -> Dict[str, WindowInfo]:
        """获取所有注册的窗口"""
        with self._lock:
            return self._window_registry.copy()


# 全局实例
_window_handle_manager = None

def get_window_handle_manager() -> WindowHandleManager:
    """获取窗口句柄管理器实例"""
    global _window_handle_manager
    if _window_handle_manager is None:
        _window_handle_manager = WindowHandleManager()
    return _window_handle_manager
