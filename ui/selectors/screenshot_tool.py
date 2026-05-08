#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
截图工具 - 使用当前截图引擎捕获窗口客户区
专为找图点击任务设计，与找图测试完全一致
"""

import logging
import os
import time
import ctypes
from datetime import datetime
from typing import Optional, Tuple
from PySide6.QtWidgets import QWidget, QMessageBox, QFileDialog, QPushButton
from PySide6.QtCore import Signal, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QPainter, QPen, QColor, QBrush, QPixmap, QCursor, QPalette, QFontMetrics
from PIL import Image
import numpy as np
import cv2

logger = logging.getLogger(__name__)
from utils.window_coordinate_common import (
    get_qt_virtual_desktop_rect,
    build_window_info,
    qt_global_to_native_point,
)
from ui.system_parts.message_box_translator import show_critical_box
from utils.window_overlay_utils import (
    draw_dynamic_center_crosshair,
    draw_overlay_frame,
    fill_overlay_event_background,
    get_overlay_debug_snapshot,
    get_window_client_overlay_metrics,
    map_native_rect_to_local,
    sync_overlay_geometry,
)
from utils.window_activation_utils import (
    activate_window,
    schedule_overlay_activation_boost,
    show_and_activate_overlay,
)


def _get_default_images_dir() -> str:
    """Get default images directory."""
    try:
        from utils.app_paths import get_images_dir

        return get_images_dir("LCA")
    except Exception:
        fallback = os.path.abspath("images")
        try:
            os.makedirs(fallback, exist_ok=True)
        except Exception:
            pass
        return fallback


def _get_context_images_dir(context) -> str:
    """优先使用上层上下文传入的图片目录，保证截图与工作流目录一致。"""
    try:
        candidate = str(getattr(context, "images_dir", "") or "").strip()
    except Exception:
        candidate = ""
    return candidate or _get_default_images_dir()

try:
    import win32gui
    import win32api
    PYWIN32_AVAILABLE = True
except ImportError:
    PYWIN32_AVAILABLE = False
    logger.warning("pywin32 not available, screenshot tool may have limited functionality")

class ScreenshotOverlay(QWidget):
    """截图覆盖层 - 使用当前截图引擎捕获窗口客户区"""

    screenshot_taken = Signal(str)  # 截图保存路径
    screenshot_cancelled = Signal()  # 取消截图

    # 支持的截图格式
    SUPPORTED_FORMATS = {
        'png': {'ext': '.png', 'cv2_params': [int(cv2.IMWRITE_PNG_COMPRESSION), 3]},
        'jpg': {'ext': '.jpg', 'cv2_params': [int(cv2.IMWRITE_JPEG_QUALITY), 95]},
        'bmp': {'ext': '.bmp', 'cv2_params': []},
    }

    def __init__(
        self,
        target_hwnd: Optional[int] = None,
        save_dir: str = "images",
        parent=None,
        screenshot_format: str = "bmp",
        card_id: Optional[int] = None,
        workflow_id: Optional[object] = None,
    ):
        super().__init__(None)  # 独立窗口

        self.target_hwnd = target_hwnd
        raw_save_dir = str(save_dir or "").strip()
        if (not raw_save_dir) or raw_save_dir.replace("/", "\\").lower() in {"images", ".\images"}:
            self.save_dir = _get_default_images_dir()
        else:
            if os.path.isabs(raw_save_dir):
                self.save_dir = raw_save_dir
            else:
                try:
                    from utils.app_paths import get_app_root

                    self.save_dir = os.path.abspath(os.path.join(get_app_root(), raw_save_dir))
                except Exception:
                    self.save_dir = os.path.abspath(raw_save_dir)
        self.parent_widget = parent
        self.card_id = card_id
        self._workflow_token = self._normalize_workflow_token(workflow_id)
        self._completion_emitted = False

        # 截图格式设置
        self.screenshot_format = screenshot_format if screenshot_format in self.SUPPORTED_FORMATS else 'bmp'

        # 窗口信息
        self.window_info = None
        self.target_window_title = ""

        # 选择区域
        self.selecting = False
        self.selection_ready = False
        self.dragging_selection = False
        self.resizing_selection = False
        self.resize_mode = None
        self.resize_margin = 8
        self.drag_last_pos = QPoint()
        self.start_pos = QPoint()
        self.current_pos = QPoint()
        self.selection_rect = QRect()
        self.last_selection_rect = QRect()  # 用于优化重绘

        # 截图数据
        self.screenshot_pixmap = None
        self.screenshot_image = None

        # DPI和窗口信息
        self.device_pixel_ratio = 1.0
        self.client_qt_rect = None  # 窗口客户区在Qt逻辑坐标中的位置
        self.client_physical_pos = None  # 窗口客户区在屏幕物理坐标中的位置（原始值，避免舍入误差）

        # 性能优化：缓存字体和颜色
        from PySide6.QtGui import QFont
        self.hint_font = QFont("Microsoft YaHei", 12)
        self.size_font = QFont("Microsoft YaHei", 11)
        self.selection_color = QColor(0, 120, 215)
        self.hint_color = QColor(0, 255, 0)
        self.mask_color = QColor(0, 0, 0, 100)

        # 窗口设置
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

        # 提示文字
        self.hint_text = "拖动鼠标选择截图区域 | 右键或ESC取消"

        self.confirm_button = QPushButton("确定", self)
        self.confirm_button.setObjectName("screenshotConfirmButton")
        self.confirm_button.setFixedSize(84, 34)
        self.confirm_button.setProperty("primary", True)
        self.confirm_button.setAutoDefault(False)
        self.confirm_button.setDefault(False)
        self.confirm_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.confirm_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_button.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.confirm_button.clicked.connect(self._confirm_selection)
        self.confirm_button.hide()

        self.reselect_button = QPushButton("重选", self)
        self.reselect_button.setObjectName("screenshotReselectButton")
        self.reselect_button.setFixedSize(84, 34)
        self.reselect_button.setAutoDefault(False)
        self.reselect_button.setDefault(False)
        self.reselect_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.reselect_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reselect_button.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.reselect_button.clicked.connect(self._reset_selection)
        self.reselect_button.hide()
        self._apply_action_buttons_theme()

        logger.info(f"创建截图工具覆盖层，目标窗口: {target_hwnd}")

        # 如果有目标窗口，获取窗口信息
        if self.target_hwnd and PYWIN32_AVAILABLE:
            self.window_info = self._get_window_info(self.target_hwnd)

    @staticmethod
    def _normalize_workflow_token(workflow_id: Optional[object]) -> str:
        """将工作流标识转换为可用于文件名的安全 token。"""
        raw = str(workflow_id or "").strip()
        if not raw:
            return ""

        invalid_chars = set('<>:"/\\|?*')
        chars = []
        for ch in raw:
            if ch in invalid_chars or ord(ch) < 32:
                chars.append("_")
            elif ch.isspace():
                chars.append("_")
            else:
                chars.append(ch)

        token = "".join(chars).strip("._ ")
        while "__" in token:
            token = token.replace("__", "_")
        return token[:64]

    def _build_card_filename_base(self) -> str:
        """构建卡片截图文件名基础部分（不含扩展名）。"""
        if self._workflow_token:
            return f"{self._workflow_token}_{self.card_id}"
        return f"card_{self.card_id}"

    def _emit_screenshot_taken_once(self, filepath: str) -> None:
        if self._completion_emitted:
            return
        self._completion_emitted = True
        self.screenshot_taken.emit(filepath)

    def _emit_screenshot_cancelled_once(self) -> None:
        if self._completion_emitted:
            return
        self._completion_emitted = True
        self.screenshot_cancelled.emit()

    def capture_and_show(self):
        """捕获屏幕并显示覆盖层"""
        try:
            self._completion_emitted = False

            # 仅在使用 WGC 引擎时清理 WGC 缓存，避免与其他引擎日志混淆
            try:
                from utils.screenshot_helper import get_screenshot_engine
                engine = get_screenshot_engine()
            except Exception:
                engine = "unknown"

            if engine == "wgc":
                try:
                    from utils.screenshot_helper import clear_screenshot_cache
                    clear_screenshot_cache()
                    logger.debug("WGC缓存已清理")
                except Exception as e:
                    logger.debug(f"清理WGC缓存失败: {e}")

            logger.info(f"开始捕获截图，窗口句柄: {self.target_hwnd}")

            # 激活目标窗口（对于模拟器，激活主窗口）
            if self.target_hwnd and PYWIN32_AVAILABLE:
                # 检测是否为模拟器，如果是则激活主窗口
                window_to_activate = self.target_hwnd
                try:
                    pass
                except Exception as e:
                    logger.debug(f"模拟器检测失败，使用默认激活逻辑: {e}")

                logger.info(f"激活窗口: {window_to_activate}")
                self._activate_target_window(window_to_activate)
                import time
                time.sleep(0.5)

                # 验证窗口是否激活成功
                try:
                    foreground_hwnd = win32gui.GetForegroundWindow()
                    if foreground_hwnd == window_to_activate or foreground_hwnd == self.target_hwnd:
                        logger.info(f"窗口激活成功 (前台: {foreground_hwnd})")
                    else:
                        logger.warning(f"窗口可能未激活，当前前台窗口: {foreground_hwnd}, 目标: {window_to_activate}")
                        self._activate_target_window(window_to_activate)
                        time.sleep(0.3)
                except Exception as e:
                    logger.warning(f"验证窗口激活状态失败: {e}")

            # 统一使用窗口客户区截图
            if not self.target_hwnd:
                logger.error("未提供目标窗口句柄，无法截图")
                show_critical_box(self.parent_widget, "截图失败", "未绑定目标窗口\n\n请先绑定一个窗口再使用截图工具")
                return False

            # 【关键修复】锁定窗口坐标，截图前后保持一致
            # 在截图前获取并缓存窗口位置，避免截图期间窗口移动导致偏移
            try:
                self._snapshot_window_position()
            except Exception as e:
                logger.error(f"锁定窗口坐标失败: {e}")
                show_critical_box(self.parent_widget, "截图失败", f"无法获取窗口位置\n\n{str(e)}")
                return False

            try:
                from utils.screenshot_helper import get_screenshot_engine
                current_engine = get_screenshot_engine()
            except Exception:
                current_engine = "unknown"
            logger.info(f"使用 {str(current_engine).upper()} 窗口客户区截图")
            screenshot = self._capture_window_wgc()

            if screenshot is None:
                logger.error("截图失败：无法获取屏幕截图")
                QMessageBox.critical(
                    None,
                    "截图失败",
                    "无法获取屏幕截图\n\n请在全局设置里更换适合当前系统的截图引擎。"
                )
                return False

            # 保存截图数据（现在统一为numpy.ndarray BGR格式）
            self.screenshot_image = screenshot

            # 获取屏幕信息（先获取，用于设置DPI）
            screen_geometry = get_qt_virtual_desktop_rect() or QRect(0, 0, 0, 0)

            # 转换为QPixmap用于显示（统一处理numpy数组）
            import cv2
            screenshot_rgb = cv2.cvtColor(screenshot, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(screenshot_rgb)
            self.screenshot_pixmap = self._pil_to_qpixmap(pil_image)

            if self.screenshot_pixmap is None:
                logger.error("无法转换截图为QPixmap")
                return False

            logger.info(f"截图QPixmap创建: 尺寸={self.screenshot_pixmap.width()}x{self.screenshot_pixmap.height()}")

            # 设置为全屏
            sync_overlay_geometry(self)
            if show_and_activate_overlay(self, log_prefix='截图覆盖层', focus=True):
                logger.info("已使用统一覆盖层激活链启动截图覆盖层")

            # 保存DPI信息用于绘制
            self.device_pixel_ratio = 1.0

            native_client_rect = (
                int(self._snapshot_client_pos[0]),
                int(self._snapshot_client_pos[1]),
                int(self._snapshot_client_pos[0] + self._snapshot_client_w),
                int(self._snapshot_client_pos[1] + self._snapshot_client_h),
            )
            self.client_qt_rect = self._native_rect_to_overlay_rect(native_client_rect)
            if not self.client_qt_rect or self.client_qt_rect.isEmpty():
                logger.error("客户区坐标转换失败")
                self.hide()
                self.close()
                return False

            try:
                snapshot = get_overlay_debug_snapshot(self, native_client_rect)
                logger.info(
                    "截图覆盖层映射诊断: "
                    f"native_rect={native_client_rect}, "
                    f"client_qt_rect=({self.client_qt_rect.x()}, {self.client_qt_rect.y()}, {self.client_qt_rect.width()}, {self.client_qt_rect.height()}), "
                    f"coord_mode={snapshot.get('coord_mode')}, "
                    f"widget_qt_geometry={snapshot.get('widget_qt_geometry')}, "
                    f"widget_native_rect={snapshot.get('widget_native_rect')}, "
                    f"widget_global_bottom_right={snapshot.get('widget_global_bottom_right')}"
                )
            except Exception as e:
                logger.warning(f"记录截图覆盖层映射诊断失败: {e}")

            logger.info(f"覆盖层设置为全屏: {screen_geometry}")
            logger.info(
                f"窗口客户区Qt坐标: ({self.client_qt_rect.x()}, {self.client_qt_rect.y()}) "
                f"{self.client_qt_rect.width()}x{self.client_qt_rect.height()}"
            )
            logger.info(f"截图实际尺寸: {screenshot.shape[1]}x{screenshot.shape[0]}")

            schedule_overlay_activation_boost(
                self,
                log_prefix='截图覆盖层',
                intervals_ms=(50, 150, 300),
                focus=True,
            )

            logger.info("截图覆盖层已显示，等待用户选择区域")

            return True

        except Exception as e:
            logger.error(f"捕获并显示截图失败: {e}", exc_info=True)
            try:
                self.hide()
                self.close()
            except Exception:
                pass
            return False

    def _snapshot_window_position(self):
        """
        快照窗口位置（截图前调用）

        【关键修复】在截图前锁定窗口坐标，保存时使用快照值避免时序竞争
        """
        if not PYWIN32_AVAILABLE:
            raise Exception("pywin32不可用")

        client_screen_pos = None
        client_width = 0
        client_height = 0

        metrics = get_window_client_overlay_metrics(self.target_hwnd)
        native_rect = metrics.get("native_rect") if metrics else None
        if not native_rect or len(native_rect) != 4:
            raise RuntimeError("获取标准化窗口快照失败")

        left, top, right, bottom = [int(value) for value in native_rect]
        if right <= left or bottom <= top:
            raise RuntimeError("标准化窗口客户区尺寸无效")

        client_screen_pos = (left, top)
        client_width = right - left
        client_height = bottom - top

        # 保存快照数据
        self._snapshot_client_pos = client_screen_pos
        self._snapshot_client_w = client_width
        self._snapshot_client_h = client_height

        logger.info(f"窗口位置快照: 客户区位置={client_screen_pos}, 尺寸={self._snapshot_client_w}x{self._snapshot_client_h}")

    def _native_rect_to_overlay_rect(self, native_rect: Tuple[int, int, int, int]) -> QRect:
        """Convert a Win32 native rect to an overlay-local Qt rect."""
        return map_native_rect_to_local(self, native_rect)

    def _get_window_info(self, hwnd: int):
        """获取窗口信息（包括DPI处理）"""
        if not hwnd or hwnd == 0:
            logger.warning("窗口句柄无效，无法获取窗口信息")
            return None

        try:
            # 检查窗口是否存在
            if not win32gui.IsWindow(hwnd):
                logger.error(f"窗口句柄 {hwnd} 无效（窗口不存在）")
                return None

            # 获取窗口标题
            self.target_window_title = win32gui.GetWindowText(hwnd)
            window_info = build_window_info(hwnd)
            if not window_info:
                logger.error("获取窗口信息失败: 返回空结果")
                return None

            client_screen_pos = window_info['client_screen_pos']
            client_width = window_info['client_width']
            client_height = window_info['client_height']
            window_dpi = window_info['window_dpi']

            logger.info(f"窗口信息: 标题='{self.target_window_title}', "
                       f"客户区位置({client_screen_pos}), "
                       f"尺寸({client_width}x{client_height}), DPI={window_dpi}")

            return window_info

        except Exception as e:
            logger.error(f"获取窗口信息失败: {e}")
            return None

    def _activate_target_window(self, hwnd: int):
        """激活并置顶目标窗口"""
        if not hwnd or hwnd == 0:
            logger.warning("窗口句柄无效，跳过激活")
            return

        try:
            # 检查窗口是否存在
            if PYWIN32_AVAILABLE and not win32gui.IsWindow(hwnd):
                logger.error(f"窗口句柄 {hwnd} 无效（窗口不存在），跳过激活")
                return
            activation_hwnd = activate_window(hwnd, log_prefix='截图')
            if activation_hwnd:
                logger.info(f"截图目标窗口激活完成: {activation_hwnd}")
            else:
                logger.warning("截图目标窗口激活失败")

        except Exception as e:
            logger.warning(f"激活目标窗口失败: {e}", exc_info=True)

    def _capture_window_wgc(self):
        """捕获窗口客户区截图（与识图任务保持同一链路）。"""
        try:
            if not PYWIN32_AVAILABLE:
                logger.warning("pywin32不可用，无法捕获窗口")
                return None

            # 与 image_match_click 执行路径统一：始终走 capture_window_smart。
            from tasks.task_utils import capture_window_smart
            try:
                from utils.screenshot_helper import get_screenshot_engine
                engine = get_screenshot_engine()
            except Exception:
                engine = "unknown"
            screenshot = capture_window_smart(self.target_hwnd, client_area_only=True)

            if screenshot is not None:
                logger.info(f"{str(engine).upper()} 窗口截图成功（客户区），尺寸: {screenshot.shape}")
                return screenshot

            logger.warning(f"{str(engine).upper()} 窗口截图失败")
            return None

        except Exception as e:
            logger.error(f"窗口截图异常: {e}", exc_info=True)
            return None

    def _pil_to_qpixmap(self, pil_image):
        """PIL图像转QPixmap (优化版 - 减少内存拷贝)"""
        try:
            # 确保RGB模式
            if pil_image.mode != 'RGB':
                pil_image = pil_image.convert('RGB')

            # 直接从PIL创建QImage，避免numpy中间转换
            from PySide6.QtGui import QImage

            # 获取PIL图像数据
            width, height = pil_image.size
            img_data = pil_image.tobytes('raw', 'RGB')
            bytes_per_line = 3 * width

            # 创建QImage (使用tobytes避免numpy数组拷贝)
            q_image = QImage(img_data, width, height, bytes_per_line, QImage.Format.Format_RGB888)

            # 深拷贝QImage数据，因为PIL数据可能被释放
            q_image = q_image.copy()

            return QPixmap.fromImage(q_image)

        except Exception as e:
            logger.error(f"PIL图像转换失败: {e}")
            return None

    def _set_selection_ready(self, ready: bool):
        self.selection_ready = bool(ready)
        if self.selection_ready:
            self.hint_text = "可拖动微调 | 方向键微调(Shift=5px, Ctrl+方向键缩放) | 点“确定”保存"
            self.confirm_button.show()
            self.reselect_button.show()
            self._update_action_buttons_position()
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.hint_text = "拖动鼠标选择截图区域 | 右键或ESC取消"
            self.confirm_button.hide()
            self.reselect_button.hide()
            self.setCursor(Qt.CursorShape.CrossCursor)

    def _cursor_for_resize_mode(self, mode: Optional[str]):
        if mode in ('left', 'right'):
            return Qt.CursorShape.SizeHorCursor
        if mode in ('top', 'bottom'):
            return Qt.CursorShape.SizeVerCursor
        if mode in ('top_left', 'bottom_right'):
            return Qt.CursorShape.SizeFDiagCursor
        if mode in ('top_right', 'bottom_left'):
            return Qt.CursorShape.SizeBDiagCursor
        if mode == 'move':
            return Qt.CursorShape.SizeAllCursor
        return Qt.CursorShape.CrossCursor

    def _hit_test_resize_mode(self, point: QPoint) -> Optional[str]:
        if not self.selection_ready or self.selection_rect.isEmpty():
            return None

        rect = self.selection_rect
        margin = self.resize_margin

        in_y = rect.top() - margin <= point.y() <= rect.bottom() + margin
        in_x = rect.left() - margin <= point.x() <= rect.right() + margin
        near_left = in_y and abs(point.x() - rect.left()) <= margin
        near_right = in_y and abs(point.x() - rect.right()) <= margin
        near_top = in_x and abs(point.y() - rect.top()) <= margin
        near_bottom = in_x and abs(point.y() - rect.bottom()) <= margin

        if near_left and near_top:
            return 'top_left'
        if near_right and near_top:
            return 'top_right'
        if near_left and near_bottom:
            return 'bottom_left'
        if near_right and near_bottom:
            return 'bottom_right'
        if near_left:
            return 'left'
        if near_right:
            return 'right'
        if near_top:
            return 'top'
        if near_bottom:
            return 'bottom'
        if rect.contains(point):
            return 'move'
        return None

    def _update_action_buttons_position(self):
        if not self.selection_ready or self.selection_rect.isEmpty():
            return

        gap = 8
        total_w = self.confirm_button.width() + self.reselect_button.width() + gap
        x = self.selection_rect.right() + 12
        y = self.selection_rect.bottom() - self.confirm_button.height()

        if x + total_w > self.width() - 8:
            x = self.selection_rect.left() - total_w - 12
        if x < 8:
            x = 8

        if y < 8:
            y = self.selection_rect.bottom() + 12
        if y + self.confirm_button.height() > self.height() - 8:
            y = self.height() - self.confirm_button.height() - 8

        self.confirm_button.move(x, y)
        self.reselect_button.move(x + self.confirm_button.width() + gap, y)

    def _clamp_point_to_client(self, point: QPoint) -> QPoint:
        if not self.client_qt_rect:
            return point
        x = max(self.client_qt_rect.left(), min(point.x(), self.client_qt_rect.right()))
        y = max(self.client_qt_rect.top(), min(point.y(), self.client_qt_rect.bottom()))
        return QPoint(x, y)

    def _clamp_rect_to_client(self, rect: QRect) -> QRect:
        if not self.client_qt_rect or rect.isEmpty():
            return rect

        width = max(1, min(rect.width(), self.client_qt_rect.width()))
        height = max(1, min(rect.height(), self.client_qt_rect.height()))

        max_x = self.client_qt_rect.x() + self.client_qt_rect.width() - width
        max_y = self.client_qt_rect.y() + self.client_qt_rect.height() - height

        x = max(self.client_qt_rect.x(), min(rect.x(), max_x))
        y = max(self.client_qt_rect.y(), min(rect.y(), max_y))

        return QRect(x, y, width, height)

    def _move_selection_by(self, dx: int, dy: int):
        if self.selection_rect.isEmpty():
            return
        moved = QRect(self.selection_rect)
        moved.translate(dx, dy)
        self.selection_rect = self._clamp_rect_to_client(moved)
        self._update_action_buttons_position()
        self.update()

    def _resize_selection_by(self, dw: int, dh: int):
        if self.selection_rect.isEmpty():
            return

        min_size = 10
        new_width = max(min_size, self.selection_rect.width() + dw)
        new_height = max(min_size, self.selection_rect.height() + dh)
        resized = QRect(self.selection_rect.x(), self.selection_rect.y(), new_width, new_height)
        resized = self._clamp_rect_to_client(resized)

        if resized.width() >= min_size and resized.height() >= min_size:
            self.selection_rect = resized
            self._update_action_buttons_position()
            self.update()

    def _resize_selection_with_mouse(self, dx: int, dy: int):
        if self.selection_rect.isEmpty() or not self.resize_mode:
            return

        min_size = 10
        rect = QRect(self.selection_rect)
        client = self.client_qt_rect or self.rect()

        left = rect.left()
        right = rect.right()
        top = rect.top()
        bottom = rect.bottom()

        mode = self.resize_mode
        if 'left' in mode:
            left += dx
        if 'right' in mode:
            right += dx
        if 'top' in mode:
            top += dy
        if 'bottom' in mode:
            bottom += dy

        if 'left' in mode:
            left = max(client.left(), min(left, right - min_size + 1))
        if 'right' in mode:
            right = min(client.right(), max(right, left + min_size - 1))
        if 'top' in mode:
            top = max(client.top(), min(top, bottom - min_size + 1))
        if 'bottom' in mode:
            bottom = min(client.bottom(), max(bottom, top + min_size - 1))

        resized = QRect(QPoint(left, top), QPoint(right, bottom)).normalized()
        if resized.width() >= min_size and resized.height() >= min_size:
            self.selection_rect = self._clamp_rect_to_client(resized)
            self._update_action_buttons_position()
            self.update()

    def _confirm_selection(self):
        if self.selection_rect.isEmpty() or not self.selection_ready:
            QMessageBox.warning(self, "提示", "请先框选有效区域")
            return
        self._save_screenshot()

    def _reset_selection(self):
        self.selecting = False
        self.dragging_selection = False
        self.resizing_selection = False
        self.resize_mode = None
        self.selection_rect = QRect()
        self.last_selection_rect = QRect()
        self._set_selection_ready(False)
        self.update()

    def _draw_magnifier(self, painter: QPainter):
        return

    def mousePressEvent(self, event):
        """鼠标按下事件"""
        if event.button() == Qt.MouseButton.LeftButton:
            click_pos = event.pos()
            self.current_pos = click_pos

            if self.client_qt_rect and not self.client_qt_rect.contains(click_pos):
                return

            if self.selection_ready and not self.selection_rect.isEmpty():
                hit_mode = self._hit_test_resize_mode(click_pos)
                if hit_mode:
                    self.drag_last_pos = click_pos
                    if hit_mode == 'move':
                        self.dragging_selection = True
                        self.resizing_selection = False
                        self.resize_mode = None
                    else:
                        self.dragging_selection = False
                        self.resizing_selection = True
                        self.resize_mode = hit_mode
                    self.setCursor(self._cursor_for_resize_mode(hit_mode))
                    event.accept()
                    return

            self._set_selection_ready(False)
            self.dragging_selection = False
            self.resizing_selection = False
            self.resize_mode = None
            self.selecting = True
            self.start_pos = self._clamp_point_to_client(click_pos)
            self.current_pos = self.start_pos
            self.selection_rect = QRect()
            self.update()
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            # 右键取消
            self._emit_screenshot_cancelled_once()
            self.close()

    def mouseMoveEvent(self, event):
        """鼠标移动事件 (优化版 - 只重绘必要区域)"""
        self.current_pos = event.pos()

        if self.selecting:
            self.current_pos = self._clamp_point_to_client(event.pos())
            old_rect = self.selection_rect
            # 更新选择矩形
            self.selection_rect = QRect(self.start_pos, self.current_pos).normalized()
            self.selection_rect = self._clamp_rect_to_client(self.selection_rect)

            # 性能优化：只重绘变化的区域
            if old_rect != self.selection_rect:
                # 计算需要更新的区域（旧矩形 + 新矩形的并集）
                update_region = old_rect.united(self.selection_rect)
                # 扩展一点边界以确保边框完全刷新
                update_region.adjust(-5, -5, 5, 5)
                self.update(update_region)
            else:
                # 如果没有变化，不重绘
                pass
            event.accept()
            return

        if self.dragging_selection:
            delta = event.pos() - self.drag_last_pos
            if delta.x() != 0 or delta.y() != 0:
                self._move_selection_by(delta.x(), delta.y())
                self.drag_last_pos = event.pos()
            event.accept()
            return

        if self.resizing_selection:
            delta = event.pos() - self.drag_last_pos
            if delta.x() != 0 or delta.y() != 0:
                self._resize_selection_with_mouse(delta.x(), delta.y())
                self.drag_last_pos = event.pos()
            event.accept()
            return

        if self.selection_ready and not self.selection_rect.isEmpty():
            hit_mode = self._hit_test_resize_mode(event.pos())
            if hit_mode:
                self.setCursor(self._cursor_for_resize_mode(hit_mode))
            elif self.client_qt_rect and self.client_qt_rect.contains(event.pos()):
                self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        elif self.client_qt_rect and self.client_qt_rect.contains(event.pos()):
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

        self.update()

    def mouseReleaseEvent(self, event):
        """鼠标释放事件"""
        if event.button() == Qt.MouseButton.LeftButton and self.selecting:
            self.selecting = False
            self.current_pos = self._clamp_point_to_client(event.pos())
            self.selection_rect = QRect(self.start_pos, self.current_pos).normalized()
            self.selection_rect = self._clamp_rect_to_client(self.selection_rect)

            if self.selection_rect.width() > 10 and self.selection_rect.height() > 10:
                self._set_selection_ready(True)
                self.update()
            else:
                self.selection_rect = QRect()
                self._set_selection_ready(False)
                self.update()
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton and self.dragging_selection:
            self.dragging_selection = False
            self._update_action_buttons_position()
            self.update()
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton and self.resizing_selection:
            self.resizing_selection = False
            self.resize_mode = None
            self._update_action_buttons_position()
            self.update()
            event.accept()

    def keyPressEvent(self, event):
        """键盘事件"""
        if event.key() == Qt.Key.Key_Escape:
            # ESC取消
            self._emit_screenshot_cancelled_once()
            self.close()
            event.accept()
            return

        if self.selection_ready and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._confirm_selection()
            event.accept()
            return

        if self.selection_ready and not self.selection_rect.isEmpty():
            step = 5 if (event.modifiers() & Qt.KeyboardModifier.ShiftModifier) else 1
            resize_mode = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)

            key = event.key()
            if resize_mode:
                if key == Qt.Key.Key_Left:
                    self._resize_selection_by(-step, 0)
                    event.accept()
                    return
                if key == Qt.Key.Key_Right:
                    self._resize_selection_by(step, 0)
                    event.accept()
                    return
                if key == Qt.Key.Key_Up:
                    self._resize_selection_by(0, -step)
                    event.accept()
                    return
                if key == Qt.Key.Key_Down:
                    self._resize_selection_by(0, step)
                    event.accept()
                    return
            else:
                if key == Qt.Key.Key_Left:
                    self._move_selection_by(-step, 0)
                    event.accept()
                    return
                if key == Qt.Key.Key_Right:
                    self._move_selection_by(step, 0)
                    event.accept()
                    return
                if key == Qt.Key.Key_Up:
                    self._move_selection_by(0, -step)
                    event.accept()
                    return
                if key == Qt.Key.Key_Down:
                    self._move_selection_by(0, step)
                    event.accept()
                    return

        super().keyPressEvent(event)

    def paintEvent(self, event):
        """Paint overlay."""
        painter = QPainter(self)

        fill_overlay_event_background(painter, self)

        if self.screenshot_pixmap and self.client_qt_rect:
            painter.drawPixmap(self.client_qt_rect, self.screenshot_pixmap)

        if self.client_qt_rect:
            draw_overlay_frame(painter, self.client_qt_rect, border_color=QColor(0, 255, 0), border_width=3)

        # 绘制半透明遮罩（未选择区域）
        if self.selecting or not self.selection_rect.isEmpty():
            # 创建遮罩
            painter.fillRect(self.rect(), self.mask_color)

            # 清除选择区域的遮罩（显示原图）
            if not self.selection_rect.isEmpty():
                painter.save()
                painter.setClipRect(self.selection_rect)
                if self.client_qt_rect and self.screenshot_pixmap:
                    painter.drawPixmap(self.client_qt_rect, self.screenshot_pixmap)
                painter.restore()

                # 绘制选择框边界
                pen = QPen(self.selection_color, 2, Qt.PenStyle.SolidLine)
                painter.setPen(pen)
                painter.drawRect(self.selection_rect)

                # 绘制中心准心（随框选尺寸缩放，并限制在框选区域内）
                draw_dynamic_center_crosshair(
                    painter,
                    self.selection_rect,
                    color=QColor(255, 0, 0),
                    inset=1,
                )

                # 绘制尺寸信息
                size_text = f"{self.selection_rect.width()} x {self.selection_rect.height()}"
                self._draw_selection_size_label(painter, self.selection_rect, size_text)

                if self.selection_ready:
                    self._update_action_buttons_position()

        # 绘制提示文字
        painter.setPen(self.hint_color)
        painter.setFont(self.hint_font)
        painter.drawText(20, 30, self.hint_text)

    def _draw_selection_size_label(self, painter: QPainter, selection_rect: QRect, text: str) -> None:
        """绘制框选尺寸标签，避免与操作按钮重叠。"""
        if not text:
            return

        painter.save()
        painter.setFont(self.size_font)
        metrics = QFontMetrics(self.size_font)
        text_w = metrics.horizontalAdvance(text)
        text_h = metrics.height()

        pad_x = 8
        pad_y = 4
        box_w = text_w + pad_x * 2
        box_h = text_h + pad_y * 2

        # 优先放在框内左上角；空间不足则放在框外上方，避免与右下角按钮冲突
        x = selection_rect.left() + 8
        y = selection_rect.top() + 8
        if selection_rect.width() < box_w + 16 or selection_rect.height() < box_h + 16:
            x = selection_rect.left()
            y = selection_rect.top() - box_h - 6

        # 屏幕边界保护
        x = max(6, min(x, self.width() - box_w - 6))
        y = max(6, min(y, self.height() - box_h - 6))

        label_rect = QRect(int(x), int(y), int(box_w), int(box_h))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 160))
        painter.drawRoundedRect(label_rect, 6, 6)

        painter.setPen(QColor(255, 255, 255))
        painter.drawText(label_rect.adjusted(pad_x, pad_y, -pad_x, -pad_y), Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    def _apply_action_buttons_theme(self) -> None:
        """应用截图操作按钮主题样式（与全局主题保持一致）。"""
        palette = {
            "text": "#333333",
            "text_disabled": "#999999",
            "surface": "#f5f5f5",
            "border": "#e0e0e0",
            "border_light": "#eeeeee",
            "hover": "#e8e8e8",
            "pressed": "#d8d8d8",
            "accent": "#0078d4",
            "accent_hover": "#1084d8",
            "accent_pressed": "#006cbe",
        }

        try:
            from themes import get_theme_manager

            theme_manager = get_theme_manager()
            for key in list(palette.keys()):
                value = str(theme_manager.get_color(key) or "").strip()
                if value:
                    palette[key] = value
        except Exception:
            pass

        surface_qc = QColor(palette["surface"])
        hover_qc = QColor(palette["hover"])
        pressed_qc = QColor(palette["pressed"])
        border_qc = QColor(palette["border"])

        if not surface_qc.isValid():
            surface_qc = QColor("#f5f5f5")
        if not hover_qc.isValid():
            hover_qc = QColor("#e8e8e8")
        if not pressed_qc.isValid():
            pressed_qc = QColor("#d8d8d8")
        if not border_qc.isValid():
            border_qc = QColor("#d0d0d0")

        surface_rgba = f"rgba({surface_qc.red()}, {surface_qc.green()}, {surface_qc.blue()}, 228)"
        hover_rgba = f"rgba({hover_qc.red()}, {hover_qc.green()}, {hover_qc.blue()}, 240)"
        pressed_rgba = f"rgba({pressed_qc.red()}, {pressed_qc.green()}, {pressed_qc.blue()}, 246)"
        border_rgba = f"rgba({border_qc.red()}, {border_qc.green()}, {border_qc.blue()}, 235)"

        common_style = (
            "outline: none;"
            "border-radius: 10px;"
            "padding: 0 14px;"
            "font-family: \"Microsoft YaHei\";"
            "font-size: 12px;"
            "font-weight: 600;"
            "min-height: 30px;"
            "letter-spacing: 0.5px;"
        )

        action_style = (
            f"""
            QPushButton#screenshotConfirmButton {{
                {common_style}
                background-color: {palette['accent']};
                color: #ffffff;
                border: 1px solid {palette['accent']};
            }}
            QPushButton#screenshotConfirmButton:hover {{
                background-color: {palette['accent_hover']};
                border-color: {palette['accent_hover']};
            }}
            QPushButton#screenshotConfirmButton:pressed {{
                background-color: {palette['accent_pressed']};
                border-color: {palette['accent_pressed']};
            }}
            QPushButton#screenshotConfirmButton:focus {{
                outline: none;
                border: 1px solid {palette['accent_hover']};
            }}
            QPushButton#screenshotConfirmButton:disabled {{
                background-color: {palette['surface']};
                color: {palette['text_disabled']};
                border: 1px solid {palette['border_light']};
            }}

            QPushButton#screenshotReselectButton {{
                {common_style}
                background-color: {surface_rgba};
                color: {palette['text']};
                border: 1px solid {border_rgba};
            }}
            QPushButton#screenshotReselectButton:hover {{
                background-color: {hover_rgba};
                border-color: {border_rgba};
            }}
            QPushButton#screenshotReselectButton:pressed {{
                background-color: {pressed_rgba};
                border-color: {border_rgba};
            }}
            QPushButton#screenshotReselectButton:focus {{
                outline: none;
                border: 1px solid {border_rgba};
            }}
            QPushButton#screenshotReselectButton:disabled {{
                background-color: {palette['surface']};
                color: {palette['text_disabled']};
                border: 1px solid {palette['border_light']};
            }}
            """
        )

        self.confirm_button.setStyleSheet(action_style)
        self.reselect_button.setStyleSheet(action_style)

    def _save_screenshot(self):
        """保存截图（全屏覆盖+DPI转换模式）"""
        try:
            # 确保保存目录存在
            if not os.path.exists(self.save_dir):
                os.makedirs(self.save_dir)

            # 获取格式配置
            format_info = self.SUPPORTED_FORMATS.get(self.screenshot_format, self.SUPPORTED_FORMATS['bmp'])
            ext = format_info['ext']

            # 生成文件名（优先按卡片ID命名，便于重复截图覆盖）
            if isinstance(self.card_id, int) and self.card_id >= 0:
                base_name = self._build_card_filename_base()
                filename = f"{base_name}{ext}"
            else:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"screenshot_{timestamp}{ext}"
            filepath = os.path.join(self.save_dir, filename)

            # 卡片命名模式：先清理同名不同后缀，避免残留旧格式文件
            if isinstance(self.card_id, int) and self.card_id >= 0:
                base_name = self._build_card_filename_base()
                for fmt_name, fmt_info in self.SUPPORTED_FORMATS.items():
                    stale_path = os.path.join(self.save_dir, f"{base_name}{fmt_info['ext']}")
                    if stale_path != filepath and os.path.exists(stale_path):
                        try:
                            os.remove(stale_path)
                            logger.debug(f"已清理旧截图文件: {stale_path}")
                        except Exception as cleanup_err:
                            logger.warning(f"清理旧截图文件失败: {stale_path}, {cleanup_err}")

            # 【关键】坐标转换：基于截图时锁定的客户区映射，避免打包环境 DPI 偏移
            if not self.client_qt_rect:
                logger.error("缺少窗口客户区信息")
                return

            # 用户框选的Qt逻辑坐标
            sel_x = self.selection_rect.x()
            sel_y = self.selection_rect.y()
            sel_width = self.selection_rect.width()
            sel_height = self.selection_rect.height()

            # 仅使用“客户区矩形 + 截图分辨率”做比例换算，避免全局坐标二次换算误差
            client_left = int(self.client_qt_rect.x())
            client_top = int(self.client_qt_rect.y())
            client_w_qt = max(1, int(self.client_qt_rect.width()))
            client_h_qt = max(1, int(self.client_qt_rect.height()))

            rel_qt_x = sel_x - client_left
            rel_qt_y = sel_y - client_top
            rel_qt_w = sel_width
            rel_qt_h = sel_height

            capture_w = max(1, int(getattr(self, "_snapshot_client_w", 1)))
            capture_h = max(1, int(getattr(self, "_snapshot_client_h", 1)))
            if self.screenshot_image is not None and isinstance(self.screenshot_image, np.ndarray):
                try:
                    capture_h, capture_w = [max(1, int(v)) for v in self.screenshot_image.shape[:2]]
                except Exception:
                    capture_w = max(1, int(getattr(self, "_snapshot_client_w", 1)))
                    capture_h = max(1, int(getattr(self, "_snapshot_client_h", 1)))
            elif self.screenshot_pixmap:
                try:
                    capture_w = max(1, int(self.screenshot_pixmap.width()))
                    capture_h = max(1, int(self.screenshot_pixmap.height()))
                except Exception:
                    capture_w = max(1, int(getattr(self, "_snapshot_client_w", 1)))
                    capture_h = max(1, int(getattr(self, "_snapshot_client_h", 1)))

            scale_x = capture_w / float(client_w_qt)
            scale_y = capture_h / float(client_h_qt)

            relative_physical_x = int(round(rel_qt_x * scale_x))
            relative_physical_y = int(round(rel_qt_y * scale_y))
            physical_width = max(1, int(round(rel_qt_w * scale_x)))
            physical_height = max(1, int(round(rel_qt_h * scale_y)))

            # 仅用于日志对齐（坐标系原点）
            client_screen_pos = self._snapshot_client_pos
            sel_physical_x = int(client_screen_pos[0]) + int(relative_physical_x)
            sel_physical_y = int(client_screen_pos[1]) + int(relative_physical_y)
            logger.info(f"==== 坐标转换详细诊断 ====")
            logger.info(f"框选区域Qt逻辑: ({sel_x}, {sel_y}) {sel_width}x{sel_height}")
            logger.info(f"客户区Qt逻辑: ({self.client_qt_rect.x()}, {self.client_qt_rect.y()}) {self.client_qt_rect.width()}x{self.client_qt_rect.height()}")
            logger.info(f"客户区物理坐标(快照): {client_screen_pos}")
            logger.info(f"框选区域物理屏幕坐标: ({sel_physical_x}, {sel_physical_y})")
            logger.info(f"相对客户区物理坐标: ({relative_physical_x}, {relative_physical_y})")
            logger.info(f"物理尺寸: {physical_width}x{physical_height}")

            if self.screenshot_image is not None and isinstance(self.screenshot_image, np.ndarray):
                import cv2

                # 边界检查
                img_h, img_w = self.screenshot_image.shape[:2]
                try:
                    from utils.screenshot_helper import get_screenshot_engine
                    engine = get_screenshot_engine()
                except Exception:
                    engine = "unknown"
                logger.info(f"{str(engine).upper()} 截图尺寸(物理像素): {img_w}x{img_h}")

                # 直接使用相对坐标裁剪，不再判断WGC返回内容
                x = max(0, min(relative_physical_x, img_w - 1))
                y = max(0, min(relative_physical_y, img_h - 1))
                w = min(physical_width, img_w - x)
                h = min(physical_height, img_h - y)

                logger.info(f"实际裁剪区域(物理像素): ({x}, {y}) {w}x{h}")

                # 检查边界修正
                if x != relative_physical_x or y != relative_physical_y or w != physical_width or h != physical_height:
                    logger.warning(f"边界修正发生: 原始({relative_physical_x}, {relative_physical_y}) {physical_width}x{physical_height}")
                    logger.warning(f"             修正为({x}, {y}) {w}x{h}")

                # 裁剪并保存
                cropped_img = self.screenshot_image[y:y+h, x:x+w]
                self._save_cv_image_to_path(cropped_img, filepath, format_info)

                self._invalidate_saved_template_cache(filepath)

                logger.info(f"窗口截图已保存: {filepath} (格式: {self.screenshot_format}, 物理像素尺寸: {w}x{h})")
                self._emit_screenshot_taken_once(filepath)
                self.close()

            elif self.screenshot_pixmap:
                # 备用方案：使用QPixmap
                relative_rect = QRect(relative_physical_x, relative_physical_y, physical_width, physical_height)
                cropped = self.screenshot_pixmap.copy(relative_rect)
                cropped.save(filepath)

                self._invalidate_saved_template_cache(filepath)

                logger.info(f"窗口截图已保存: {filepath}")
                self._emit_screenshot_taken_once(filepath)
                self.close()

            else:
                logger.error("无截图数据")
                self._emit_screenshot_cancelled_once()
                self.close()

        except Exception as e:
            logger.error(f"保存截图失败: {e}", exc_info=True)
            QMessageBox.critical(self, "错误", f"保存截图失败: {str(e)}")
            self._emit_screenshot_cancelled_once()
            self.close()

    def closeEvent(self, event):
        self._emit_screenshot_cancelled_once()
        super().closeEvent(event)

    @staticmethod
    def _save_cv_image_to_path(image: np.ndarray, filepath: str, format_info: dict) -> None:
        """
        使用编码后写字节的方式保存图片，避免 Windows 下中文路径被错误编码。
        """
        ext = str(format_info.get("ext", ".png") or ".png")
        cv2_params = list(format_info.get("cv2_params") or [])

        if cv2_params:
            ok, buffer = cv2.imencode(ext, image, cv2_params)
        else:
            ok, buffer = cv2.imencode(ext, image)

        if not ok or buffer is None:
            raise RuntimeError("图片编码失败")

        with open(filepath, "wb") as f:
            f.write(buffer.tobytes())

    def _invalidate_saved_template_cache(self, filepath: str) -> None:
        """截图保存后主动失效模板缓存，避免立即识别命中旧图。"""
        try:
            from pathlib import Path
            from utils.template_preloader import get_global_preloader

            preloader = get_global_preloader()
            if preloader is None:
                return

            normalized = str(Path(filepath).resolve())
            preloader.invalidate_template(normalized)
            preloader.invalidate_template(filepath)
            preloader.invalidate_template(filepath.replace("\\", "/"))
        except Exception:
            pass

class QuickScreenshotButton:
    """快速截图按钮助手类 - 用于集成到参数面板"""

    def __init__(self, parent_panel, target_hwnd: Optional[int] = None):
        """
        初始化快速截图按钮

        Args:
            parent_panel: 父面板（参数面板）
            target_hwnd: 目标窗口句柄
        """
        self.parent_panel = parent_panel
        self.target_hwnd = target_hwnd
        self.save_dir = _get_context_images_dir(parent_panel)
        self.screenshot_overlay = None

    def _get_screenshot_format(self) -> str:
        """从全局配置获取截图格式"""
        try:
            from app_core.config_store import load_config
            config = load_config()
            return config.get('screenshot_format', 'bmp')
        except Exception as e:
            logger.warning(f"获取截图格式配置失败: {e}, 使用默认BMP格式")
            return 'bmp'

    def create_button(self, text="快速截图"):
        """创建截图按钮"""
        from PySide6.QtWidgets import QPushButton

        button = QPushButton(text)
        button.setToolTip("点击后拖动鼠标选择区域截图\n截图将自动保存到 images 目录")
        button.clicked.connect(self.start_screenshot)

        # 设置样式
        button.setStyleSheet("""
            QPushButton {
                background-color: #0078D4;
                color: white;
                border: none;
                padding: 5px 10px;
                border-radius: 3px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #1084D8;
            }
            QPushButton:pressed {
                background-color: #006CC1;
            }
        """)

        return button

    def start_screenshot(self):
        """开始截图"""
        try:
            logger.info("启动快速截图工具")

            # 获取截图格式配置
            screenshot_format = self._get_screenshot_format()
            logger.info(f"使用截图格式: {screenshot_format}")

            workflow_id = None
            try:
                if self.parent_panel and hasattr(self.parent_panel, "_get_active_workflow_file_token"):
                    workflow_id = self.parent_panel._get_active_workflow_file_token()
            except Exception:
                workflow_id = None

            # 创建截图覆盖层
            self.screenshot_overlay = ScreenshotOverlay(
                target_hwnd=self.target_hwnd,
                save_dir=self.save_dir,
                parent=self.parent_panel,
                screenshot_format=screenshot_format,
                workflow_id=workflow_id,
            )

            # 连接信号
            self.screenshot_overlay.screenshot_taken.connect(self._on_screenshot_taken)
            self.screenshot_overlay.screenshot_cancelled.connect(self._on_screenshot_cancelled)

            # 捕获并显示
            if not self.screenshot_overlay.capture_and_show():
                logger.error("启动截图工具失败")
                self.screenshot_overlay = None

        except Exception as e:
            logger.error(f"启动截图工具失败: {e}", exc_info=True)
            show_critical_box(self.parent_widget, "错误", f"启动截图工具失败: {str(e)}")

    def _on_screenshot_taken(self, filepath):
        """截图完成回调"""
        logger.info(f"截图已保存: {filepath}")
        self.screenshot_overlay = None

    def _on_screenshot_cancelled(self):
        """截图取消回调"""
        logger.info("截图已取消")
        self.screenshot_overlay = None

    def set_target_hwnd(self, hwnd: int):
        """设置目标窗口句柄"""
        self.target_hwnd = hwnd

    def set_save_dir(self, save_dir: str):
        """设置保存目录"""
        self.save_dir = save_dir
