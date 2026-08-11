import win32gui
import win32ui
import win32con
import win32api
import numpy as np
import time
import random
import logging
from typing import Optional, Tuple
import cv2 # Required for image format conversion

# Ensure pywin32 is available
try:
    import win32gui
    import win32ui
    import win32con
    import win32api
    PYWIN32_AVAILABLE = True
except ImportError:
    PYWIN32_AVAILABLE = False
    # Let the calling task handle the warning/error if background mode is attempted

import ctypes # 确保导入了 ctypes
import cv2
import numpy as np
import win32gui
import win32ui
import win32con
import logging

# 其他现有的导入保持不变...

def capture_window_background(hwnd: int) -> Optional[np.ndarray]:
    """
    捕获窗口客户区内容（仅使用PrintWindow方法）

    Args:
        hwnd: 窗口句柄

    Returns:
        NumPy数组（BGR格式）或None
    """
    if not PYWIN32_AVAILABLE:
        logging.error("capture_window_background: pywin32 未安装。")
        return None

    if not hwnd or not win32gui.IsWindow(hwnd):
        logging.error(f"capture_window_background: 无效的窗口句柄 {hwnd}")
        return None

    return _try_capture_with_printwindow(hwnd)

def _try_capture_with_printwindow(hwnd: int) -> Optional[np.ndarray]:
    """使用 PrintWindow API 尝试捕获窗口内容，并保持与当前 DPI 感知链一致"""
    img = None
    hwnd_dc = None
    mfc_dc = None
    save_dc = None
    save_bitmap = None

    try:
        if not hwnd or not isinstance(hwnd, int):
            logging.error("[PrintWindow] 窗口句柄无效")
        else:
            capture_width = 0
            capture_height = 0
            try:
                left, top, right, bot = win32gui.GetClientRect(hwnd)
                capture_width = right - left
                capture_height = bot - top
            except Exception as e:
                logging.error(f"[PrintWindow] 获取客户区尺寸异常: {e}")

            if capture_width > 0 and capture_height > 0:
                logging.debug(f"[PrintWindow] 客户区尺寸={capture_width}x{capture_height}")
                hwnd_dc = win32gui.GetDC(hwnd)
                if hwnd_dc:
                    mfc_dc_ok = False
                    try:
                        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
                        if mfc_dc:
                            mfc_dc_ok = True
                        else:
                            logging.error("[PrintWindow] 创建MFC DC失败")
                    except Exception as e:
                        logging.error(f"[PrintWindow] 创建MFC DC异常: {e}")

                    if mfc_dc_ok:
                        save_dc_ok = False
                        try:
                            save_dc = mfc_dc.CreateCompatibleDC()
                            if save_dc:
                                save_dc_ok = True
                            else:
                                logging.error("[PrintWindow] 创建兼容DC失败")
                        except Exception as e:
                            logging.error(f"[PrintWindow] 创建兼容DC异常: {e}")

                        if save_dc_ok:
                            bitmap_ok = False
                            try:
                                save_bitmap = win32ui.CreateBitmap()
                                if save_bitmap:
                                    save_bitmap.CreateCompatibleBitmap(mfc_dc, capture_width, capture_height)
                                    save_dc.SelectObject(save_bitmap)
                                    bitmap_ok = True
                                else:
                                    logging.error("[PrintWindow] 创建位图失败")
                            except Exception as e:
                                logging.error(f"[PrintWindow] 创建位图异常: {e}")

                            if bitmap_ok:
                                result = 0
                                safe_hdc = None
                                try:
                                    safe_hdc = save_dc.GetSafeHdc()
                                    if safe_hdc is None:
                                        logging.error("[PrintWindow] 获取DC句柄失败")
                                    else:
                                        result = ctypes.windll.user32.PrintWindow(hwnd, safe_hdc, 3)
                                        if result:
                                            logging.debug(f"[PrintWindow] 成功")
                                        else:
                                            logging.warning(f"[PrintWindow] 失败，返回值={result}")
                                except Exception as e:
                                    logging.error(f"[PrintWindow] PrintWindow异常: {e}")
                                    result = 0

                                if result:
                                    try:
                                        bmp_info = save_bitmap.GetInfo()
                                        if not bmp_info or not isinstance(bmp_info, dict):
                                            logging.error("[PrintWindow] 位图信息无效")
                                        else:
                                            bmp_h = bmp_info.get('bmHeight')
                                            bmp_w = bmp_info.get('bmWidth')

                                            if bmp_h is None or bmp_w is None or bmp_h <= 0 or bmp_w <= 0:
                                                logging.error(f"[PrintWindow] 位图尺寸无效: width={bmp_w}, height={bmp_h}")
                                            else:
                                                try:
                                                    bmp_str = save_bitmap.GetBitmapBits(True)
                                                    if not bmp_str or not isinstance(bmp_str, (bytes, bytearray)):
                                                        logging.error("[PrintWindow] 获取位图数据失败")
                                                    else:
                                                        expected_size = bmp_h * bmp_w * 4
                                                        if len(bmp_str) < expected_size:
                                                            logging.error(f"[PrintWindow] 位图数据不完整: {len(bmp_str)} < {expected_size}")
                                                        else:
                                                            try:
                                                                img_array = np.frombuffer(bmp_str, dtype=np.uint8).reshape(bmp_h, bmp_w, 4)
                                                                img = cv2.cvtColor(img_array, cv2.COLOR_BGRA2BGR)
                                                                logging.debug(f"[PrintWindow] 成功转换，尺寸={img.shape}")
                                                            except Exception as e:
                                                                logging.error(f"[PrintWindow] reshape异常: {e}")
                                                except Exception as e:
                                                    logging.error(f"[PrintWindow] 获取位图数据异常: {e}")
                                    except Exception as e:
                                        logging.error(f"[PrintWindow] 处理位图异常: {e}")
                else:
                    logging.error("[PrintWindow] 获取窗口DC失败")
            else:
                logging.error(f"[PrintWindow] 客户区尺寸无效: {capture_width}x{capture_height}")

    except Exception as e:
        logging.error(f"[PrintWindow] 未预期的异常: {e}")
        img = None
    finally:
        cleanup_errors = []

        if save_bitmap is not None:
            try:
                handle = save_bitmap.GetHandle()
                if handle:
                    win32gui.DeleteObject(handle)
            except Exception as e:
                cleanup_errors.append(f"bitmap: {e}")
            try:
                del save_bitmap
            except:
                pass

        if save_dc is not None:
            try:
                save_dc.DeleteDC()
            except Exception as e:
                cleanup_errors.append(f"save_dc: {e}")
            try:
                del save_dc
            except:
                pass

        if mfc_dc is not None:
            try:
                mfc_dc.DeleteDC()
            except Exception as e:
                cleanup_errors.append(f"mfc_dc: {e}")
            try:
                del mfc_dc
            except:
                pass

        if hwnd_dc is not None:
            try:
                win32gui.ReleaseDC(hwnd, hwnd_dc)
            except Exception as e:
                cleanup_errors.append(f"hwnd_dc: {e}")
            try:
                del hwnd_dc
            except:
                pass

        if cleanup_errors:
            logging.warning(f"[PrintWindow] 清理错误: {cleanup_errors}")

    return img

def capture_window_content(hwnd: int) -> Tuple[Optional[object], int, int]:
    """
    捕获窗口内容并返回PIL图像和尺寸

    Args:
        hwnd: 窗口句柄

    Returns:
        Tuple[PIL.Image, width, height] 或 (None, 0, 0) 如果失败
    """
    try:
        # 使用现有的capture_window_background函数
        img_array = capture_window_background(hwnd)
        if img_array is None:
            return None, 0, 0

        # 转换numpy数组为PIL图像
        from PIL import Image

        # img_array是BGR格式，需要转换为RGB
        img_rgb = cv2.cvtColor(img_array, cv2.COLOR_BGR2RGB)

        # 转换为PIL图像
        height, width = img_rgb.shape[:2]
        pil_image = Image.fromarray(img_rgb)

        return pil_image, width, height

    except Exception as e:
        logging.error(f"capture_window_content失败: {e}")
        return None, 0, 0

# --- ADDED: Dictionary for VK codes (copied from find_color_task) ---
VK_CODE = {
    'backspace':0x08, 'tab':0x09, 'clear':0x0C, 'enter':0x0D, 'shift':0x10, 'ctrl':0x11,
    'alt':0x12, 'pause':0x13, 'caps_lock':0x14, 'esc':0x1B, 'spacebar':0x20,
    'page_up':0x21, 'page_down':0x22, 'end':0x23, 'home':0x24, 'left':0x25,
    'up':0x26, 'right':0x27, 'down':0x28, 'select':0x29, 'print':0x2A,
    'execute':0x2B, 'print_screen':0x2C, 'ins':0x2D, 'del':0x2E, 'help':0x2F,
    '0':0x30, '1':0x31, '2':0x32, '3':0x33, '4':0x34, '5':0x35, '6':0x36, '7':0x37, '8':0x38, '9':0x39,
    'a':0x41, 'b':0x42, 'c':0x43, 'd':0x44, 'e':0x45, 'f':0x46, 'g':0x47, 'h':0x48, 'i':0x49, 'j':0x4A,
    'k':0x4B, 'l':0x4C, 'm':0x4D, 'n':0x4E, 'o':0x4F, 'p':0x50, 'q':0x51, 'r':0x52, 's':0x53, 't':0x54,
    'u':0x55, 'v':0x56, 'w':0x57, 'x':0x58, 'y':0x59, 'z':0x5A,
    'numpad_0':0x60, 'numpad_1':0x61, 'numpad_2':0x62, 'numpad_3':0x63, 'numpad_4':0x64,
    'numpad_5':0x65, 'numpad_6':0x66, 'numpad_7':0x67, 'numpad_8':0x68, 'numpad_9':0x69,
    'multiply_key':0x6A, 'add_key':0x6B, 'separator_key':0x6C, 'subtract_key':0x6D,
    'decimal_key':0x6E, 'divide_key':0x6F,
    'F1':0x70, 'F2':0x71, 'F3':0x72, 'F4':0x73, 'F5':0x74, 'F6':0x75, 'F7':0x76, 'F8':0x77,
    'F9':0x78, 'F10':0x79, 'F11':0x7A, 'F12':0x7B, 'F13':0x7C, 'F14':0x7D, 'F15':0x7E, 'F16':0x7F,
    'F17':0x80, 'F18':0x81, 'F19':0x82, 'F20':0x83, 'F21':0x84, 'F22':0x85, 'F23':0x86, 'F24':0x87,
    'num_lock':0x90, 'scroll_lock':0x91, 'left_shift':0xA0, 'right_shift':0xA1,
    'left_control':0xA2, 'right_control':0xA3, 'left_menu':0xA4, 'right_menu':0xA5,
    'browser_back':0xA6, 'browser_forward':0xA7, 'browser_refresh':0xA8, 'browser_stop':0xA9,
    'browser_search':0xAA, 'browser_favorites':0xAB, 'browser_start_and_home':0xAC,
    'volume_mute':0xAD, 'volume_Down':0xAE, 'volume_up':0xAF, 'next_track':0xB0,
    'previous_track':0xB1, 'stop_media':0xB2, 'play/pause_media':0xB3, 'start_mail':0xB4,
    'select_media':0xB5, 'start_application_1':0xB6, 'start_application_2':0xB7,
    'attn_key':0xF6, 'crsel_key':0xF7, 'exsel_key':0xF8, 'play_key':0xFA, 'zoom_key':0xFB,
    'clear_key':0xFE, '+':0xBB, ',':0xBC, '-':0xBD, '.':0xBE, '/':0xBF, '`':0xC0, ';':0xBA,
    '[':0xDB, '\\':0xDC, ']':0xDD, "'":0xDE # Escaped backslash
}
# ---------------------------------------------------------------------
def click_background(hwnd: int, x: int, y: int, button: str = 'left', clicks: int = 1, interval: float = 0.1, random_range_x: int = 0, random_range_y: int = 0) -> bool:
    """
    Sends mouse click messages to a window at specified client coordinates.
    使用标准的SendMessage/PostMessage方法，适用于普通窗口和部分模拟器。

    Args:
        hwnd: The target window handle (HWND).
        x: The x-coordinate relative to the window's client area.
        y: The y-coordinate relative to the window's client area.
        button: Mouse button ('left', 'right', 'middle').
        clicks: Number of clicks.
        interval: Delay between clicks (in seconds).
        random_range_x: Range for random x-coordinate offset.
        random_range_y: Range for random y-coordinate offset.

    Returns:
        True if messages were sent successfully, False otherwise.
    """
    # 使用本地 Win32 消息执行后台点击。
    if not PYWIN32_AVAILABLE:
        logging.error("click_background: pywin32 未安装。")
        return False

    if not hwnd or not win32gui.IsWindow(hwnd):
        logging.error(f"click_background: 无效的窗口句柄 {hwnd}")
        return False

    return _click_standard_background(hwnd, x, y, button, clicks, interval, random_range_x, random_range_y)

def _click_standard_background(hwnd: int, x: int, y: int, button: str = 'left', clicks: int = 1, interval: float = 0.1, random_range_x: int = 0, random_range_y: int = 0) -> bool:
    """标准后台点击方法"""
    # Combine coordinates into lParam for messages
    # Ensure coordinates are integers
    x = int(round(x))
    y = int(round(y))
    lParam = win32api.MAKELONG(x, y)

    # Define message constants
    WM_LBUTTONDOWN = win32con.WM_LBUTTONDOWN
    WM_LBUTTONUP = win32con.WM_LBUTTONUP
    WM_RBUTTONDOWN = win32con.WM_RBUTTONDOWN
    WM_RBUTTONUP = win32con.WM_RBUTTONUP
    WM_MBUTTONDOWN = win32con.WM_MBUTTONDOWN
    WM_MBUTTONUP = win32con.WM_MBUTTONUP
    
    # Define wParam constants (usually 0 for simple clicks, but might need flags)
    wParam = 0
    MK_LBUTTON = win32con.MK_LBUTTON
    MK_RBUTTON = win32con.MK_RBUTTON
    MK_MBUTTON = win32con.MK_MBUTTON

    if button == 'left':
        down_message = WM_LBUTTONDOWN
        up_message = WM_LBUTTONUP
        wParam_down = MK_LBUTTON # Some apps might check this on DOWN message
    elif button == 'right':
        down_message = WM_RBUTTONDOWN
        up_message = WM_RBUTTONUP
        wParam_down = MK_RBUTTON
    elif button == 'middle':
        down_message = WM_MBUTTONDOWN
        up_message = WM_MBUTTONUP
        wParam_down = MK_MBUTTON
    else:
        logging.error(f"click_background: 不支持的按钮 '{button}'")
        return False

    all_success = True
    try:
        for i in range(clicks):
            # Apply random offsets
            final_x = x + random.randint(-random_range_x, random_range_x)
            final_y = y + random.randint(-random_range_y, random_range_y)
            final_lParam = win32api.MAKELONG(final_x, final_y)

            # Send DOWN message
            # Use PostMessage for non-blocking behavior
            win32api.PostMessage(hwnd, down_message, wParam_down, final_lParam)
            time.sleep(0.02) # Small delay, adjust if needed
            # Send UP message (wParam is usually 0 for UP)
            win32api.PostMessage(hwnd, up_message, 0, final_lParam) 
            
            # logging.info(f"后台点击 {i+1}/{clicks} 消息已发送到 HWND {hwnd} at ({final_x},{final_y}) (原始: {x},{y})")
            if clicks > 1 and i < clicks - 1:
                time.sleep(interval) # User-specified interval between clicks
                
    except Exception as e:
        logging.error(f"发送点击消息到窗口 {hwnd} 时发生错误: {e}", exc_info=True)
        all_success = False
        
    return all_success

if __name__ == '__main__':
    # Example Usage (Requires manually finding a target HWND)
    # target_title = "Calculator" # Example
    target_title = "Untitled - Notepad" # Example: English Notepad
    # target_title = "无标题 - 记事本" # Example: Chinese Notepad
    
    # Setup basic logging for testing this module directly
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[logging.StreamHandler()])
        
    if not PYWIN32_AVAILABLE:
         logging.error("Please install pywin32 first: pip install pywin32")
    else:
        hwnd = win32gui.FindWindow(None, target_title)
        if hwnd:
            logging.info(f"Found window '{target_title}' with HWND: {hwnd}")
            
            # Test Capture
            logging.info("Attempting background capture...")
            captured_image = capture_window_background(hwnd)
            if captured_image is not None:
                logging.info("Background capture successful!")
                try:
                    # Display the captured image (optional, requires cv2)
                    window_name = "Background Capture Test"
                    cv2.imshow(window_name, captured_image)
                    logging.info(f"Displaying captured image. Press any key in the '{window_name}' window to close...")
                    cv2.waitKey(0)
                    cv2.destroyAllWindows()
                    logging.info("Capture window closed.")
                except ImportError:
                    logging.warning("OpenCV not fully available, cannot display image.")
                except Exception as display_err:
                    logging.error(f"Error displaying image: {display_err}", exc_info=True)
            else:
                logging.error("Background capture failed.")

        else:
            logging.error(f"Window with title '{target_title}' not found.") 
