import json
import logging
import os
import time
from typing import Optional, Tuple

from utils.app_paths import get_config_path
from utils.window.window_binding_utils import get_active_bound_window_hwnd
from utils.window.window_coordinate_common import build_window_info

logger = logging.getLogger(__name__)


def load_enabled_bound_window_hwnd_from_config() -> Optional[int]:
    config_path = get_config_path()
    if not os.path.exists(config_path):
        raise FileNotFoundError(config_path)

    with open(config_path, 'r', encoding='utf-8') as file:
        config_data = json.load(file)

    hwnd = get_active_bound_window_hwnd(config_data)
    if hwnd:
        logger.info(f'从config.json的活动绑定窗口获取句柄: {hwnd}')
        return hwnd
    return None


def resolve_window_activation_hwnd(hwnd: int, log_prefix: str = '') -> int:
    import win32gui

    target_hwnd = hwnd
    parent = win32gui.GetParent(hwnd)
    while parent != 0:
        target_hwnd = parent
        parent = win32gui.GetParent(parent)

    if target_hwnd != hwnd:
        parent_title = win32gui.GetWindowText(target_hwnd)
        child_title = win32gui.GetWindowText(hwnd)
        prefix = f'[{log_prefix}] ' if log_prefix else ''
        logger.info(
            f'{prefix}检测到子窗口，激活父窗口: '
            f'{target_hwnd} ({parent_title}), 子窗口: {hwnd} ({child_title})'
        )
    return target_hwnd


def activate_window(hwnd: int, log_prefix: str = '') -> Optional[int]:
    import ctypes
    import win32con
    import win32gui
    import win32process

    if not hwnd:
        logger.warning(f'[{log_prefix}] 窗口句柄无效，跳过激活' if log_prefix else '窗口句柄无效，跳过激活')
        return None

    if not win32gui.IsWindow(hwnd):
        logger.warning(
            f'[{log_prefix}] 窗口句柄无效或未找到 (hwnd={hwnd})'
            if log_prefix
            else f'窗口句柄无效或未找到 (hwnd={hwnd})'
        )
        return None

    from utils.window.window_identity import is_desktop_window

    if is_desktop_window(hwnd):
        prefix = f'[{log_prefix}] ' if log_prefix else ''
        logger.info(f'{prefix}目标是桌面，跳过窗口激活')
        return hwnd

    activation_hwnd = resolve_window_activation_hwnd(hwnd, log_prefix=log_prefix)
    from utils.window.virtual_desktop import skip_cross_desktop_activation

    if skip_cross_desktop_activation(activation_hwnd, log_prefix=log_prefix):
        return activation_hwnd
    if win32gui.IsIconic(activation_hwnd):
        win32gui.ShowWindow(activation_hwnd, win32con.SW_RESTORE)
        time.sleep(0.1)

    win32gui.ShowWindow(activation_hwnd, win32con.SW_SHOW)
    time.sleep(0.05)

    hwnd_topmost = -1
    hwnd_notopmost = -2
    swp_nomove = 0x0002
    swp_nosize = 0x0001
    swp_showwindow = 0x0040
    ctypes.windll.user32.SetWindowPos(
        activation_hwnd,
        hwnd_topmost,
        0,
        0,
        0,
        0,
        swp_nomove | swp_nosize | swp_showwindow,
    )
    time.sleep(0.1)

    foreground_hwnd = win32gui.GetForegroundWindow()
    attached = False
    if foreground_hwnd != 0:
        foreground_thread_id = win32process.GetWindowThreadProcessId(foreground_hwnd)[0]
        target_thread_id = win32process.GetWindowThreadProcessId(activation_hwnd)[0]
        if foreground_thread_id != target_thread_id:
            ctypes.windll.user32.AttachThreadInput(foreground_thread_id, target_thread_id, True)
            attached = True

    try:
        win32gui.SetForegroundWindow(activation_hwnd)
        time.sleep(0.1)
    finally:
        ctypes.windll.user32.SetWindowPos(
            activation_hwnd,
            hwnd_notopmost,
            0,
            0,
            0,
            0,
            swp_nomove | swp_nosize | swp_showwindow,
        )
        if attached and foreground_hwnd != 0:
            try:
                foreground_thread_id2 = win32process.GetWindowThreadProcessId(foreground_hwnd)[0]
                target_thread_id2 = win32process.GetWindowThreadProcessId(activation_hwnd)[0]
                if foreground_thread_id2 != target_thread_id2:
                    ctypes.windll.user32.AttachThreadInput(
                        foreground_thread_id2,
                        target_thread_id2,
                        False,
                    )
            except Exception:
                pass

    win32gui.BringWindowToTop(activation_hwnd)
    time.sleep(0.2)
    return activation_hwnd


def activate_overlay_window(hwnd: int, log_prefix: str = '覆盖层') -> bool:
    import ctypes
    import win32gui
    import win32process

    if not hwnd:
        logger.warning(f'[{log_prefix}] 覆盖层句柄无效，跳过激活')
        return False

    try:
        user32 = ctypes.windll.user32
        overlay_hwnd = int(hwnd)
        user32.SetWindowPos(
            overlay_hwnd,
            -1,
            0,
            0,
            0,
            0,
            0x0001 | 0x0002,
        )
        foreground_hwnd = win32gui.GetForegroundWindow()
        attached = False
        foreground_tid = 0
        overlay_tid = win32process.GetWindowThreadProcessId(overlay_hwnd)[0]
        if foreground_hwnd and foreground_hwnd != overlay_hwnd:
            foreground_tid = win32process.GetWindowThreadProcessId(foreground_hwnd)[0]
            if foreground_tid and foreground_tid != overlay_tid:
                attached = bool(user32.AttachThreadInput(foreground_tid, overlay_tid, True))
        try:
            user32.SetForegroundWindow(overlay_hwnd)
            user32.SetActiveWindow(overlay_hwnd)
            user32.BringWindowToTop(overlay_hwnd)
            user32.EnableWindow(overlay_hwnd, True)
        finally:
            if attached:
                user32.AttachThreadInput(foreground_tid, overlay_tid, False)
        return True
    except Exception as error:
        logger.warning(f'[{log_prefix}] Windows API激活覆盖层失败: {error}')
        return False


def force_window_top(hwnd: int, log_prefix: str = '窗口') -> bool:
    import ctypes

    if not hwnd:
        logger.warning(f'[{log_prefix}] 目标窗口句柄无效，无法置顶')
        return False
    from utils.window.virtual_desktop import skip_cross_desktop_activation

    if skip_cross_desktop_activation(hwnd, log_prefix=log_prefix):
        return False

    try:
        user32 = ctypes.windll.user32
        user32.SetWindowPos(
            int(hwnd),
            -1,
            0,
            0,
            0,
            0,
            0x0001 | 0x0002 | 0x0010,
        )
        user32.SetForegroundWindow(int(hwnd))
        return True
    except Exception as error:
        logger.warning(f'[{log_prefix}] 强制置顶失败: {error}')
        return False


def schedule_window_top_boost(
    hwnd: int,
    log_prefix: str = '窗口',
    intervals_ms: tuple[int, ...] = (100, 600, 1500),
) -> None:
    from PySide6.QtCore import QTimer

    if not hwnd:
        logger.warning(f'[{log_prefix}] 目标窗口句柄无效，跳过置顶调度')
        return

    for delay in intervals_ms:
        QTimer.singleShot(
            int(delay),
            lambda target_hwnd=hwnd, prefix=log_prefix: force_window_top(
                target_hwnd,
                log_prefix=prefix,
            ),
        )

    logger.info(f'[{log_prefix}] 已启动目标窗口置顶调度: {list(intervals_ms)}')


def activate_overlay_widget(
    overlay,
    *,
    log_prefix: str = '覆盖层',
    focus: bool = True,
) -> bool:
    try:
        overlay.raise_()
        overlay.activateWindow()
        if focus and hasattr(overlay, 'setFocus'):
            overlay.setFocus()
        return activate_overlay_window(int(overlay.winId()), log_prefix=log_prefix)
    except Exception as error:
        logger.warning(f'[{log_prefix}] 激活覆盖层失败: {error}')
        return False


def overlay_is_activatable(overlay) -> bool:
    try:
        if overlay is None:
            return False
        if getattr(overlay, '_closing', False):
            return False
        overlay.isVisible()
        return True
    except RuntimeError:
        return False


def overlay_is_interacting(overlay) -> bool:
    try:
        return bool(
            getattr(overlay, 'selecting', False)
            or getattr(overlay, 'selection_pending', False)
            or getattr(overlay, 'dragging', False)
        )
    except RuntimeError:
        return False


def grab_overlay_input(overlay, *, log_prefix: str = '覆盖层', activate: bool = False) -> bool:
    try:
        from PySide6.QtCore import Qt

        if not overlay_is_activatable(overlay):
            return False
        try:
            if not overlay.isVisible():
                return False
            window = overlay.windowHandle() if hasattr(overlay, "windowHandle") else None
            if window is not None and hasattr(window, "isExposed") and not window.isExposed():
                return False
        except RuntimeError:
            return False
        if activate and not overlay_is_interacting(overlay):
            overlay.raise_()
            overlay.activateWindow()
            if hasattr(overlay, 'setFocus'):
                overlay.setFocus(Qt.FocusReason.OtherFocusReason)
        overlay.grabMouse()
        overlay.grabKeyboard()
        overlay._is_ready_for_input = True
        return True
    except RuntimeError:
        return False
    except Exception as error:
        logger.warning(f'[{log_prefix}] 抓取覆盖层输入失败: {error}')
        return False


def release_overlay_input(overlay) -> None:
    try:
        overlay.releaseMouse()
    except Exception:
        pass
    try:
        overlay.releaseKeyboard()
    except Exception:
        pass


def overlay_can_receive_input(overlay) -> bool:
    try:
        from PySide6.QtWidgets import QWidget

        if overlay is None or not overlay.isVisible():
            return False
        if overlay.isActiveWindow() or overlay.hasFocus():
            return True
        return QWidget.mouseGrabber() is overlay
    except RuntimeError:
        return False


def show_and_raise_widget(
    widget,
    *,
    log_prefix: str = '窗口',
) -> bool:
    try:
        widget.show()
        widget.raise_()
        return True
    except Exception as error:
        logger.warning(f'[{log_prefix}] 显示部件失败: {error}')
        return False


def show_and_activate_overlay(
    overlay,
    *,
    log_prefix: str = '覆盖层',
    focus: bool = False,
) -> bool:
    try:
        overlay.show()
    except Exception as error:
        logger.warning(f'[{log_prefix}] 显示覆盖层失败: {error}')
        return False
    return activate_overlay_widget(overlay, log_prefix=log_prefix, focus=focus)


def schedule_overlay_activation_boost(
    overlay,
    *,
    log_prefix: str = '覆盖层',
    intervals_ms: tuple[int, ...] = (50, 150, 300),
    focus: bool = True,
) -> None:
    from PySide6.QtCore import QTimer

    def _boost():
        try:
            if not overlay_is_activatable(overlay) or not overlay.isVisible():
                return
            if overlay_is_interacting(overlay):
                return
            overlay.raise_()
            grab_overlay_input(overlay, log_prefix=log_prefix, activate=False)
        except RuntimeError:
            return
        _ = focus

    for delay in intervals_ms:
        QTimer.singleShot(int(delay), _boost)


def ensure_overlay_ready_for_input(
    overlay,
    *,
    log_prefix: str,
    ready_message: str,
    retry_message: str,
    exhausted_message: str,
    max_attempts: int = 3,
    retry_delay_ms: int = 200,
    auto_show: bool = False,
    allow_closed_skip: bool = False,
) -> None:
    from PySide6.QtCore import QTimer

    _ = allow_closed_skip
    if not overlay_is_activatable(overlay):
        return
    if overlay_is_interacting(overlay):
        overlay._is_ready_for_input = True
        return

    try:
        if not overlay.isVisible():
            if not auto_show:
                return
            logger.warning(f'[{log_prefix}] 覆盖层不可见，强制显示')
            overlay.show()
            if not overlay_is_activatable(overlay) or not overlay.isVisible():
                return

        if overlay_can_receive_input(overlay) or getattr(overlay, '_is_ready_for_input', False):
            grab_overlay_input(overlay, log_prefix=log_prefix, activate=False)
            overlay._is_ready_for_input = True
            logger.info(ready_message)
            return

        grabbed = grab_overlay_input(overlay, log_prefix=log_prefix, activate=False)
        if overlay_can_receive_input(overlay) or grabbed:
            overlay._is_ready_for_input = True
            logger.info(ready_message)
            return

        activate_overlay_widget(overlay, log_prefix=log_prefix, focus=True)
        grabbed = grab_overlay_input(overlay, log_prefix=log_prefix, activate=False)

        if overlay_can_receive_input(overlay) or grabbed:
            overlay._is_ready_for_input = True
            logger.info(ready_message)
            return

        attempts = int(getattr(overlay, '_activation_attempts', 0)) + 1
        overlay._activation_attempts = attempts
        logger.warning(retry_message.format(attempt=attempts, max_attempts=max_attempts))

        if attempts < max_attempts:
            QTimer.singleShot(int(retry_delay_ms), overlay._ensure_ready_for_input)
            return

        grab_overlay_input(overlay, log_prefix=log_prefix)
        overlay._is_ready_for_input = True
        logger.warning(exhausted_message)
    except RuntimeError:
        return
    except Exception as error:
        logger.error(f'[{log_prefix}] 确保窗口就绪时出错: {error}')
        if overlay_is_activatable(overlay):
            overlay._is_ready_for_input = True


def resolve_window_client_rect(hwnd: int, log_prefix: str = '') -> Tuple[int, int, int, int]:
    import win32gui

    try:
        window_info = build_window_info(hwnd)
        native_rect = window_info.get('client_native_rect') if window_info else None
        if not native_rect or len(native_rect) != 4:
            raise ValueError('客户区原生矩形不可用')

        left, top, right, bottom = [int(value) for value in native_rect]
        window_rect = (left, top, right - left, bottom - top)
        prefix = f'[{log_prefix}] ' if log_prefix else ''
        logger.info(
            f'{prefix}使用客户区坐标: '
            f'位置=({window_rect[0]}, {window_rect[1]}), '
            f'尺寸=({window_rect[2]}, {window_rect[3]})'
        )
        return window_rect
    except Exception as error:
        prefix = f'[{log_prefix}] ' if log_prefix else ''
        logger.warning(f'{prefix}获取客户区失败，使用窗口矩形: {error}')
        rect = win32gui.GetWindowRect(hwnd)
        return rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1]


def resolve_window_client_offset(hwnd: int, log_prefix: str = '') -> Tuple[int, int]:
    import win32gui

    try:
        window_info = build_window_info(hwnd)
        native_rect = window_info.get('client_native_rect') if window_info else None
        if not native_rect or len(native_rect) != 4:
            raise ValueError('客户区原生矩形不可用')

        left, top, _, _ = [int(value) for value in native_rect]
        window_offset_x, window_offset_y = left, top
        rect = win32gui.GetWindowRect(hwnd)
        window_title = win32gui.GetWindowText(hwnd)
        prefix = f'[{log_prefix}] ' if log_prefix else ''
        logger.info(f'{prefix}窗口回放模式: 句柄={hwnd}, 标题={window_title}')
        logger.info(f'{prefix}  窗口矩形 (含边框): ({rect[0]}, {rect[1]})')
        logger.info(
            f'{prefix}  客户区位置 (实际使用): '
            f'({window_offset_x}, {window_offset_y})'
        )
        logger.info(
            f'{prefix}  边框偏移: '
            f'({window_offset_x - rect[0]}, {window_offset_y - rect[1]})'
        )
        return window_offset_x, window_offset_y
    except Exception as error:
        prefix = f'[{log_prefix}] ' if log_prefix else ''
        raise RuntimeError(f'{prefix}获取客户区位置失败: {error}') from error


def resolve_replay_window_offsets_from_config(
    recording_area: str,
    log_prefix: str = '回放',
) -> Tuple[Optional[int], Optional[int]]:
    if recording_area != '窗口录制':
        return 0, 0

    try:
        hwnd = load_enabled_bound_window_hwnd_from_config()
    except FileNotFoundError:
        return None, None
    except Exception as error:
        logger.error(f'从config.json读取窗口句柄失败: {error}')
        return None, None

    if not hwnd:
        logger.warning('无法进行窗口回放')
        return None, None

    try:
        import win32gui

        if not win32gui.IsWindow(hwnd):
            logger.error(f'窗口句柄无效或未找到 (hwnd={hwnd})')
            logger.warning('窗口不存在或已关闭，无法进行窗口回放')
            return None, None

        if not activate_window(hwnd, log_prefix=log_prefix):
            logger.warning('无法进行窗口回放')
            return None, None
        return resolve_window_client_offset(hwnd, log_prefix=log_prefix)
    except Exception as error:
        logger.error(f'获取窗口位置失败: {error}', exc_info=True)
        logger.warning('无法进行窗口回放')
        return None, None
