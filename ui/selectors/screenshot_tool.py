#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
截图工具 - 使用当前截图引擎捕获窗口客户区
专为找图点击任务设计，与找图测试完全一致
"""

import logging
import os
from datetime import datetime
from typing import Optional, Tuple
from PySide6.QtWidgets import QApplication, QWidget, QMessageBox, QPushButton
from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal, QEvent, QObject
from shiboken6 import isValid
from themes import get_theme_manager, theme_color
from PySide6.QtGui import QPainter, QPen, QColor, QPixmap, QFontMetrics
from PIL import Image
import numpy as np
import cv2

logger = logging.getLogger(__name__)
from utils.window.window_coordinate_common import (
    get_qt_virtual_desktop_rect,
    build_window_info,
)
from ui.system_parts.message_box_translator import show_critical_box
from utils.window.window_overlay_utils import (
    OVERLAY_TEXT_COLOR,
    apply_overlay_text_style,
    capture_virtual_desktop_pixmap,
    configure_opaque_picker_overlay,
    draw_dynamic_center_crosshair,
    draw_overlay_frame,
    draw_picker_backdrop,
    get_overlay_debug_snapshot,
    get_window_client_overlay_metrics,
    map_native_rect_to_local,
    overlay_hint_font,
    prime_picker_backdrop,
    sync_overlay_geometry,
)
from utils.window.window_activation_utils import (
    activate_window,
    schedule_overlay_activation_boost,
    schedule_overlay_callback,
    release_overlay_input,
    show_and_activate_overlay,
)
from ui.selectors.selection_adjust import (
    cursor_for_selection_hit,
    hit_test_selection,
    scale_rect_by_wheel,
    wheel_event_delta_y,
)


def _normalize_screenshot_save_dir(save_dir):
    if not isinstance(save_dir, str) or not save_dir.strip():
        raise ValueError("未设置截图保存目录")
    return os.path.abspath(save_dir)

import win32gui

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
        unique_filename: bool = False,
    ):
        if screenshot_format not in self.SUPPORTED_FORMATS:
            raise ValueError(f"不支持的截图格式：{screenshot_format}")
        resolved_save_dir = _normalize_screenshot_save_dir(save_dir)
        super().__init__(None)  # 独立窗口

        self.target_hwnd = target_hwnd
        self.save_dir = resolved_save_dir
        self.parent_widget = parent
        self.card_id = card_id
        self._workflow_token = self._normalize_workflow_token(workflow_id)
        self.unique_filename = bool(unique_filename)
        self._completion_emitted = False
        self._resources_released = False
        self._theme_registered = False
        self._composed_backdrop = None
        self._composed_backdrop_key = None
        if parent is not None:
            parent.destroyed.connect(self._on_owner_destroyed)

        # 截图格式设置
        self.screenshot_format = screenshot_format

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
        self.desktop_pixmap = None

        # DPI和窗口信息
        self.device_pixel_ratio = 1.0
        self.client_qt_rect = None  # 窗口客户区在Qt逻辑坐标中的位置
        self.client_physical_pos = None  # 窗口客户区在屏幕物理坐标中的位置（原始值，避免舍入误差）

        # 性能优化：缓存字体和颜色
        self.hint_font = overlay_hint_font()
        self.size_font = overlay_hint_font()
        self.selection_color = QColor(theme_color("selection_target"))
        self.hint_color = OVERLAY_TEXT_COLOR
        self.mask_color = QColor(theme_color("selection_backdrop"))

        # 抓图前保持轻量 Tool 窗，和仓库旧实现一致。
        # 这里如果先建成不透明原生顶层窗，会和 DXGI Desktop Duplication 抢 D3D，dxcam 直接失败。
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._closing = False

        # 提示文字
        self.hint_text = "拖动鼠标选择截图区域 | 右键或ESC取消"

        try:
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
            self._theme_registered = True
            get_theme_manager().register_theme_change_callback(self._on_theme_changed)

            logger.info(f"创建截图工具覆盖层，目标窗口: {target_hwnd}")

            # 如果有目标窗口，获取窗口信息
            if self.target_hwnd:
                self.window_info = self._get_window_info(self.target_hwnd)
        except Exception:
            self._release_capture()
            self.deleteLater()
            raise

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

    def _allocate_unique_filepath(self, ext: str) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if isinstance(self.card_id, int) and self.card_id >= 0:
            prefix = self._build_card_filename_base()
        else:
            prefix = "screenshot"
        filename = f"{prefix}_{timestamp}{ext}"
        filepath = os.path.join(self.save_dir, filename)
        index = 1
        while os.path.exists(filepath):
            filename = f"{prefix}_{timestamp}_{index}{ext}"
            filepath = os.path.join(self.save_dir, filename)
            index += 1
        return filepath

    def _build_card_filename_base(self) -> str:
        """构建卡片截图文件名基础部分（不含扩展名）。"""
        if self._workflow_token:
            return f"{self._workflow_token}_{self.card_id}"
        return f"card_{self.card_id}"

    def _emit_screenshot_taken_once(self, path: str):
        if self._completion_emitted:
            return
        self._completion_emitted = True
        self.close()
        if isValid(self):
            self.screenshot_taken.emit(path)

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
            from utils.capture.screenshot_helper import get_screenshot_engine, clear_screenshot_cache
            engine = get_screenshot_engine()

            if engine == "wgc":
                clear_screenshot_cache()

            logger.info(f"开始捕获截图，窗口句柄: {self.target_hwnd}")

            # 激活目标窗口（桌面不能置顶，跳过）
            if self.target_hwnd:
                from utils.window.window_identity import is_desktop_window

                if is_desktop_window(self.target_hwnd):
                    logger.info("目标是桌面，跳过窗口激活")
                else:
                    window_to_activate = self.target_hwnd
                    logger.info(f"激活窗口: {window_to_activate}")
                    self._activate_target_window(window_to_activate)
                    import time
                    time.sleep(0.5)

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
                self.close()
                return False

            # 【关键修复】锁定窗口坐标，截图前后保持一致
            # 在截图前获取并缓存窗口位置，避免截图期间窗口移动导致偏移
            try:
                self._snapshot_window_position()
            except Exception as e:
                logger.error(f"锁定窗口坐标失败: {e}")
                show_critical_box(self.parent_widget, "截图失败", f"无法获取窗口位置\n\n{str(e)}")
                self.close()
                return False

            current_engine = engine
            logger.info(f"使用 {str(current_engine).upper()} 窗口客户区截图")
            screenshot = self._capture_window_wgc()

            if screenshot is None:
                logger.error("截图失败：无法获取屏幕截图")
                detail = ""
                try:
                    from utils.capture.screenshot_helper import get_last_screenshot_error

                    detail = str(get_last_screenshot_error(current_engine) or "").strip()
                except Exception:
                    detail = ""
                tip = "无法获取屏幕截图\n\n请在全局设置里更换适合当前窗口的截图引擎（如 WGC / PrintWindow）。"
                if detail:
                    tip = f"{tip}\n\n详情：{detail}"
                QMessageBox.critical(None, "截图失败", tip)
                self.close()
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
                self.close()
                return False

            logger.info(f"截图QPixmap创建: 尺寸={self.screenshot_pixmap.width()}x{self.screenshot_pixmap.height()}")
            self.desktop_pixmap = capture_virtual_desktop_pixmap()

            # 抓完再改成不透明顶层窗，避免半透明 Tool 被点穿。
            configure_opaque_picker_overlay(self)
            self._apply_action_buttons_theme()

            # 先铺好覆盖层几何并算好客户区，再显示，避免第一帧把窗口截图拉满全屏。
            sync_overlay_geometry(self)
            self.device_pixel_ratio = 1.0
            native_client_rect = (
                int(self._snapshot_client_pos[0]),
                int(self._snapshot_client_pos[1]),
                int(self._snapshot_client_pos[0] + self._snapshot_client_w),
                int(self._snapshot_client_pos[1] + self._snapshot_client_h),
            )
            self.client_qt_rect = self._native_rect_to_overlay_rect(native_client_rect)
            if self._should_use_full_overlay_selection():
                self.client_qt_rect = QRect(self.rect())
                logger.info("截图覆盖层改用全屏框选区域: %sx%s", self.client_qt_rect.width(), self.client_qt_rect.height())
            elif not self._client_rect_is_usable():
                logger.warning("显示前客户区尚未对齐，先只画桌面，避免把窗口截图拉满全屏")

            if show_and_activate_overlay(self, log_prefix='截图覆盖层', focus=True):
                logger.info("已使用统一覆盖层激活链启动截图覆盖层")
            if self._closing:
                self.close()
                return False
            sync_overlay_geometry(self)
            mapped_rect = self._native_rect_to_overlay_rect(native_client_rect)
            if self._should_use_full_overlay_selection():
                self.client_qt_rect = QRect(self.rect())
            elif mapped_rect and not mapped_rect.isEmpty():
                self.client_qt_rect = mapped_rect

            prime_picker_backdrop(
                self,
                desktop_pixmap=self.desktop_pixmap,
                window_pixmap=self.screenshot_pixmap if self._client_rect_is_usable() else None,
                target_rect=self.client_qt_rect,
            )

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
            for delay in (0, 50, 160, 320):
                schedule_overlay_callback(self, delay, self._grab_overlay_input)

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

    def _should_use_full_overlay_selection(self):
        from utils.window.window_identity import is_desktop_window
        return is_desktop_window(self.target_hwnd)

    def _client_rect_is_usable(self) -> bool:
        rect = self.client_qt_rect
        if rect is None or rect.isEmpty():
            return False
        overlap = rect.intersected(self.rect())
        return overlap.width() >= 32 and overlap.height() >= 32

    def _grab_overlay_input(self) -> None:
        try:
            if getattr(self, "_closing", False) or not self.isVisible() or self.selection_ready:
                return
            self.raise_()
            self.activateWindow()
            self.setFocus(Qt.FocusReason.OtherFocusReason)
            self.grabMouse()
            self.grabKeyboard()
            logger.info("截图覆盖层已抓取鼠标和键盘")
        except RuntimeError:
            return
        except Exception as exc:
            logger.warning("截图覆盖层抓取输入失败: %s", exc)

    def _release_overlay_input(self):
        release_overlay_input(self)

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

    def _activate_target_window(self, hwnd):
        if not hwnd or not win32gui.IsWindow(hwnd):
            raise ValueError("截图目标窗口无效")
        if not activate_window(hwnd, log_prefix='截图'):
            raise RuntimeError("无法激活截图目标窗口")

    def _capture_window_wgc(self):
        from tasks.task_utils import capture_window_smart
        return capture_window_smart(self.target_hwnd, client_area_only=True)

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
            self.hint_text = "滚轮缩放 | 四角调大小 | 拖动边框移动 | 方向键微调(Shift=5px, Ctrl+方向键缩放) | 点“确定”保存"
            self._release_overlay_input()
            self.confirm_button.show()
            self.reselect_button.show()
            self._update_action_buttons_position()
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.hint_text = "拖动鼠标选择截图区域 | 右键或ESC取消"
            self.confirm_button.hide()
            self.reselect_button.hide()
            self.setCursor(Qt.CursorShape.CrossCursor)
            if self.isVisible():
                self._grab_overlay_input()

    def _cursor_for_resize_mode(self, mode: Optional[str]):
        return cursor_for_selection_hit(mode)

    def _hit_test_resize_mode(self, point: QPoint) -> Optional[str]:
        if not self.selection_ready or self.selection_rect.isEmpty():
            return None
        return hit_test_selection(point, self.selection_rect, self.resize_margin)

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
        old_rect = QRect(self.selection_rect)
        self.selection_rect = self._clamp_rect_to_client(moved)
        self._update_action_buttons_position()
        self._invalidate_selection_region(old_rect, self.selection_rect)

    def _resize_selection_by(self, dw: int, dh: int):
        if self.selection_rect.isEmpty():
            return

        min_size = 10
        new_width = max(min_size, self.selection_rect.width() + dw)
        new_height = max(min_size, self.selection_rect.height() + dh)
        resized = QRect(self.selection_rect.x(), self.selection_rect.y(), new_width, new_height)
        resized = self._clamp_rect_to_client(resized)

        if resized.width() >= min_size and resized.height() >= min_size:
            old_rect = QRect(self.selection_rect)
            self.selection_rect = resized
            self._update_action_buttons_position()
            self._invalidate_selection_region(old_rect, self.selection_rect)

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
            old_rect = QRect(self.selection_rect)
            self.selection_rect = self._clamp_rect_to_client(resized)
            self._update_action_buttons_position()
            self._invalidate_selection_region(old_rect, self.selection_rect)

    def _invalidate_selection_region(self, old_rect: QRect, new_rect: QRect) -> None:
        dirty = QRect(old_rect).united(new_rect)
        if dirty.isEmpty():
            return
        dirty.adjust(-16, -40, 16, 16)
        self.update(dirty.intersected(self.rect()))

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
            if self.client_qt_rect and not self.client_qt_rect.contains(click_pos):
                click_pos = self._clamp_point_to_client(click_pos)
            self.current_pos = click_pos

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
                self._invalidate_selection_region(old_rect, self.selection_rect)
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

    def wheelEvent(self, event):
        if (
            not self.selection_ready
            or self.selection_rect.isEmpty()
            or self.selecting
            or self.dragging_selection
            or self.resizing_selection
        ):
            event.ignore()
            return

        delta_y = wheel_event_delta_y(event)
        if delta_y == 0:
            event.accept()
            return

        bounds = self.client_qt_rect if self.client_qt_rect else self.rect()
        new_rect = scale_rect_by_wheel(self.selection_rect, bounds, delta_y)
        new_rect = self._clamp_rect_to_client(new_rect)
        if new_rect != self.selection_rect:
            old_rect = QRect(self.selection_rect)
            self.selection_rect = new_rect
            self._update_action_buttons_position()
            self._invalidate_selection_region(old_rect, self.selection_rect)
        event.accept()

    def paintEvent(self, event):
        if self._resources_released:
            return
        """Paint overlay."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        dirty = event.rect() if event is not None else self.rect()

        window_pixmap = self.screenshot_pixmap if self._client_rect_is_usable() else None
        draw_picker_backdrop(
            painter,
            self,
            desktop_pixmap=self.desktop_pixmap,
            window_pixmap=window_pixmap,
            target_rect=self.client_qt_rect,
        )

        if self.client_qt_rect:
            draw_overlay_frame(painter, self.client_qt_rect, border_color=QColor(theme_color("selection_target")), border_width=3)

        if self.selecting or not self.selection_rect.isEmpty():
            painter.fillRect(dirty, self.mask_color)
            if not self.selection_rect.isEmpty():
                painter.save()
                painter.setClipRect(self.selection_rect.intersected(dirty))
                draw_picker_backdrop(
                    painter,
                    self,
                    desktop_pixmap=self.desktop_pixmap,
                    window_pixmap=self.screenshot_pixmap,
                    target_rect=self.client_qt_rect,
                )
                painter.restore()

                pen = QPen(self.selection_color, 2, Qt.PenStyle.SolidLine)
                painter.setPen(pen)
                painter.drawRect(self.selection_rect)

                draw_dynamic_center_crosshair(
                    painter,
                    self.selection_rect,
                    color=QColor(theme_color("selection_marker")),
                    inset=1,
                )

                size_text = f"{self.selection_rect.width()} x {self.selection_rect.height()}"
                self._draw_selection_size_label(painter, self.selection_rect, size_text)

        apply_overlay_text_style(painter)
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
        painter.setBrush(QColor(theme_color("selection_backdrop")))
        painter.drawRoundedRect(label_rect, 6, 6)

        painter.setPen(OVERLAY_TEXT_COLOR)
        painter.drawText(label_rect.adjusted(pad_x, pad_y, -pad_x, -pad_y), Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    def _apply_action_buttons_theme(self) -> None:
        from themes.capture_tools import apply_capture_action_buttons
        apply_capture_action_buttons(self.confirm_button, self.reselect_button)

    def _save_screenshot(self):
        if self._closing:
            return
        try:
            if self.client_qt_rect is None or self.client_qt_rect.isEmpty():
                raise ValueError("缺少有效的窗口客户区信息")
            image = self.screenshot_image
            if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] != 3 or not image.size:
                raise ValueError("缺少有效的窗口截图数据")
            selection = self.selection_rect.intersected(self.client_qt_rect)
            if selection.isEmpty():
                raise ValueError("截图选区为空")
            img_h, img_w = image.shape[:2]
            scale_x = img_w / self.client_qt_rect.width()
            scale_y = img_h / self.client_qt_rect.height()
            x = max(0, min(int(round((selection.x() - self.client_qt_rect.x()) * scale_x)), img_w - 1))
            y = max(0, min(int(round((selection.y() - self.client_qt_rect.y()) * scale_y)), img_h - 1))
            width = min(max(1, int(round(selection.width() * scale_x))), img_w - x)
            height = min(max(1, int(round(selection.height() * scale_y))), img_h - y)
            format_info = self.SUPPORTED_FORMATS[self.screenshot_format]
            os.makedirs(self.save_dir, exist_ok=True)
            if self.unique_filename or not (type(self.card_id) is int and self.card_id >= 0):
                filepath = self._allocate_unique_filepath(format_info['ext'])
            else:
                filepath = os.path.join(self.save_dir, self._build_card_filename_base() + format_info['ext'])
            self._save_cv_image_to_path(image[y:y+height, x:x+width], filepath, format_info)
            if not self.unique_filename and type(self.card_id) is int and self.card_id >= 0:
                for info in self.SUPPORTED_FORMATS.values():
                    stale = os.path.join(self.save_dir, self._build_card_filename_base() + info['ext'])
                    if stale != filepath and os.path.exists(stale):
                        os.remove(stale)
            self._invalidate_saved_template_cache(filepath)
        except Exception as error:
            logger.exception("保存截图失败")
            self.close()
            QMessageBox.critical(None, "截图失败", f"保存截图失败：{error}")
            return
        self._emit_screenshot_taken_once(filepath)

    def _on_theme_changed(self, *_args):
        if not self._resources_released:
            self.selection_color = QColor(theme_color("selection_target"))
            self.mask_color = QColor(theme_color("selection_backdrop"))
            self._composed_backdrop = self._composed_backdrop_key = None
            self.update()

    def _release_capture(self):
        if self._resources_released:
            return
        self._resources_released = True
        if self._theme_registered:
            get_theme_manager().unregister_theme_change_callback(self._on_theme_changed)
            self._theme_registered = False
        self._closing = True
        release_overlay_input(self)
        self.screenshot_image = None
        self.screenshot_pixmap = None
        self.desktop_pixmap = None
        self._composed_backdrop = None
        self._composed_backdrop_key = None
        self.selecting = self.selection_ready = False
        self.dragging_selection = self.resizing_selection = False
        self.selection_rect = QRect()

    def _on_owner_destroyed(self):
        self._release_capture()
        self.deleteLater()

    def close(self):
        self._release_capture()
        result = super().close()
        if isValid(self):
            self._emit_screenshot_cancelled_once()
        return result

    def closeEvent(self, event):
        self._release_capture()
        super().closeEvent(event)
        self._emit_screenshot_cancelled_once()

    def hideEvent(self, event):
        self._release_capture()
        super().hideEvent(event)
        self._emit_screenshot_cancelled_once()

    def event(self, event):
        if event.type() == QEvent.Type.DeferredDelete:
            self._release_capture()
        return super().event(event)

    @staticmethod
    def _save_cv_image_to_path(image: np.ndarray, filepath: str, format_info: dict) -> None:
        """
        使用编码后写字节的方式保存图片，避免 Windows 下中文路径被错误编码。
        """
        ext = format_info["ext"]
        cv2_params = format_info["cv2_params"]

        if cv2_params:
            ok, buffer = cv2.imencode(ext, image, cv2_params)
        else:
            ok, buffer = cv2.imencode(ext, image)

        if not ok or buffer is None:
            raise RuntimeError("图片编码失败")

        with open(filepath, "wb") as f:
            f.write(buffer.tobytes())

    def _invalidate_saved_template_cache(self, filepath):
        from pathlib import Path
        from utils.match.template_preloader import get_global_preloader
        from utils.image_paths import get_image_path_resolver
        preloader = get_global_preloader()
        if preloader is not None:
            for name in {str(Path(filepath).resolve()), filepath, filepath.replace("\\", "/")}:
                preloader.invalidate_template(name)
        get_image_path_resolver().invalidate(filepath)
