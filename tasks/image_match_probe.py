# -*- coding: utf-8 -*-
"""
统一图片识别测试模块

该模块提供统一的测试找图方法，确保：
1. 插件模式和原生模式严格隔离
2. 测试找图与实际运行使用完全相同的逻辑
3. 所有模块调用同一个入口
"""

import os
import logging
from typing import Dict, Any, Optional, List, Tuple

from tasks.task_utils import coerce_bool, capture_and_match_template_smart
import cv2
import numpy as np
from utils.smart_image_matcher import normalize_match_image

logger = logging.getLogger(__name__)


def test_image_recognition(params: Dict[str, Any], target_hwnd: Optional[int] = None,
                           main_window=None, parameter_panel=None):
    """
    统一测试图片识别功能，在绑定窗口上绘制找到的图片区域

    Args:
        params: 参数字典，包含image_path、confidence等
        target_hwnd: 目标窗口句柄
        main_window: 主窗口对象（用于隐藏）
        parameter_panel: 参数面板对象（用于隐藏）
    """
    # 定义恢复窗口的函数（使用信号槽确保在主线程执行）
    def restore_windows():
        try:
            from PySide6.QtCore import QTimer
            if main_window:
                QTimer.singleShot(0, main_window, main_window.show)
                if hasattr(main_window, "raise_"):
                    QTimer.singleShot(0, main_window, main_window.raise_)
            if parameter_panel:
                QTimer.singleShot(0, parameter_panel, parameter_panel.show)
                if hasattr(parameter_panel, "raise_"):
                    QTimer.singleShot(0, parameter_panel, parameter_panel.raise_)
                if hasattr(parameter_panel, "activateWindow"):
                    QTimer.singleShot(0, parameter_panel, parameter_panel.activateWindow)
        except Exception as e:
            logger.warning(f"[测试识别] 恢复窗口失败: {e}")

    try:
        import win32gui

        logger.info("=" * 60)
        logger.info("开始测试图片识别")
        logger.info("=" * 60)

        # 窗口已在调用方（parameter_panel）隐藏，此处不再重复隐藏

        # 1. 获取参数
        image_path = params.get('image_path', '')
        image_paths_text = params.get('image_paths', '').strip()
        confidence = params.get('confidence', 0.8)
        preprocessing_method = params.get('preprocessing_method', '无')
        multi_image_mode = params.get('multi_image_mode', '单图识别')
        use_recognition_region = coerce_bool(params.get('use_recognition_region', False))
        recognition_region_x = params.get('recognition_region_x', 0)
        recognition_region_y = params.get('recognition_region_y', 0)
        recognition_region_width = params.get('recognition_region_width', 0)
        recognition_region_height = params.get('recognition_region_height', 0)

        # 2. 收集所有待测试的图片路径（由用户选择的模式决定）
        if multi_image_mode == '多图识别':
            image_path_for_test = ''
        else:
            image_path_for_test = image_path
            image_paths_text = ''
        test_image_paths = _collect_image_paths(image_path_for_test, image_paths_text)

        if not test_image_paths:
            logger.error("测试失败: 未指定目标图片路径或所有图片路径无效")
            restore_windows()
            return

        if not target_hwnd:
            logger.error("测试失败: 未绑定目标窗口")
            restore_windows()
            return

        if not win32gui.IsWindow(target_hwnd):
            logger.error(f"测试失败: 窗口句柄无效: {target_hwnd}")
            restore_windows()
            return

        if multi_image_mode == '多图识别':
            import re
            raw_entries = [line.strip() for line in re.split(r'[\n;]+', image_paths_text)
                           if line.strip() and not line.strip().startswith('#')]
            logger.info(f"多图路径条目数: {len(raw_entries)}, 有效图片数: {len(test_image_paths)}")
            if not raw_entries:
                logger.warning("当前选择为多图识别，但未提供多图路径文本")
        logger.info(f"待测试图片数量: {len(test_image_paths)}")
        for i, p in enumerate(test_image_paths):
            logger.info(f"  [{i+1}] {os.path.basename(p)}")
        logger.info(f"置信度阈值: {confidence}")

        # 多图区域参数覆盖（仅多图测试时启用）
        if multi_image_mode == '多图识别' and coerce_bool(params.get('multi_use_recognition_region', False)):
            use_recognition_region = True
            recognition_region_x = params.get('multi_recognition_region_x', 0)
            recognition_region_y = params.get('multi_recognition_region_y', 0)
            recognition_region_width = params.get('multi_recognition_region_width', 0)
            recognition_region_height = params.get('multi_recognition_region_height', 0)

        # 3. 判断使用插件模式还是原生模式
        use_plugin = False
        try:
            from app_core.plugin_bridge import is_plugin_enabled
            use_plugin = is_plugin_enabled()
        except ImportError:
            pass

        # 4. 执行匹配
        if use_plugin:
            logger.info("[测试识别] 使用插件模式")
            match_results = _test_with_plugin(
                test_image_paths, target_hwnd, confidence,
                use_recognition_region, recognition_region_x, recognition_region_y,
                recognition_region_width, recognition_region_height
            )
        else:
            logger.info("[测试识别] 使用原生模式")
            match_results = _test_with_opencv(
                test_image_paths, target_hwnd, confidence, preprocessing_method,
                use_recognition_region, recognition_region_x, recognition_region_y,
                recognition_region_width, recognition_region_height
            )

        # 5. 显示结果
        logger.info(f"匹配完成，找到 {len(match_results)}/{len(test_image_paths)} 张图片")

        if not match_results:
            logger.warning(f"未找到任何目标图片")
            logger.info("=" * 60)
            logger.info("测试完成 - 未找到目标")
            logger.info("=" * 60)
            restore_windows()
            return

        # 输出所有找到的结果
        logger.info("找到的图片:")
        for result in match_results:
            img_name, found_x, found_y, w, h, sim = result[:6]
            center_x = found_x + w // 2
            center_y = found_y + h // 2
            logger.info(f"  {img_name}: 位置=({found_x}, {found_y}), 中心=({center_x}, {center_y}), 尺寸={w}x{h}, 相似度={sim:.4f}")

        # 6. 绘制结果覆盖层（覆盖层关闭后会恢复窗口）
        _draw_overlay(target_hwnd, match_results, restore_windows)

        logger.info("=" * 60)
        logger.info("测试完成")
        logger.info("=" * 60)

        # 注意：不在这里调用 restore_windows()，由 _draw_overlay 在覆盖层关闭后调用

    except Exception as e:
        logger.error(f"测试图片识别失败: {e}", exc_info=True)
        restore_windows()


def _collect_image_paths(image_path: str, image_paths_text: str) -> List[str]:
    """收集所有待测试的图片路径"""
    test_image_paths = []
    import re
    resolver = None
    try:
        from tasks.task_utils import get_image_path_resolver
        resolver = get_image_path_resolver()
        resolver.clear_cache()
    except Exception:
        resolver = None

    # 单图模式
    if image_path:
        try:
            resolved = resolver.resolve(image_path) if resolver else None
        except Exception:
            resolved = None
        if resolved and os.path.exists(resolved):
            test_image_paths.append(resolved)
        elif os.path.exists(image_path):
            test_image_paths.append(image_path)

    # 多图模式
    if image_paths_text:
        lines = re.split(r'[\n;]+', image_paths_text)
        common_dir = None
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith('#'):
                if line.startswith('# 共同目录:'):
                    common_dir = line.replace('# 共同目录:', '').strip()
                continue

            if '  # ' in line:
                filename = line.split('  # ')[0].strip()
                directory = line.split('  # ')[1].strip()
                full_path = os.path.join(directory, filename)
            elif common_dir and not os.path.isabs(line):
                full_path = os.path.join(common_dir, line)
            else:
                full_path = line

            try:
                resolved = resolver.resolve(full_path) if resolver else None
            except Exception:
                resolved = None
            candidate_path = resolved if resolved and os.path.exists(resolved) else full_path
            if os.path.exists(candidate_path) and candidate_path not in test_image_paths:
                test_image_paths.append(candidate_path)

    return test_image_paths


def _test_with_plugin(image_paths: List[str], target_hwnd: int, confidence: float,
                      use_region: bool, region_x: int, region_y: int,
                      region_w: int, region_h: int) -> List[Tuple]:
    """
    使用插件模式进行测试找图

    与实际运行 _evaluate_image_condition 中的插件模式逻辑完全一致
    """
    import win32gui
    from app_core.plugin_bridge import plugin_find_pic_with_confidence

    match_results = []

    # 获取窗口客户区尺寸
    client_rect = win32gui.GetClientRect(target_hwnd)
    client_w = client_rect[2] - client_rect[0]
    client_h = client_rect[3] - client_rect[1]

    # 确定搜索区域
    if use_region and region_w > 0 and region_h > 0:
        search_x1, search_y1 = region_x, region_y
        search_x2 = min(region_x + region_w, client_w)
        search_y2 = min(region_y + region_h, client_h)
    else:
        search_x1, search_y1 = 0, 0
        search_x2, search_y2 = client_w, client_h

    # 对每张图片进行匹配
    for img_path in image_paths:
        img_name = os.path.basename(img_path)
        try:
            # 获取模板尺寸
            template = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
            if template is None:
                logger.warning(f"  无法读取图片: {img_name}")
                continue
            template_h, template_w = template.shape[:2]

            # 调用插件找图（与实际运行逻辑一致）
            result = plugin_find_pic_with_confidence(
                hwnd=target_hwnd,
                x1=search_x1, y1=search_y1,
                x2=search_x2, y2=search_y2,
                pic_name=os.path.abspath(img_path),
                similarity=confidence
            )

            if result:
                actual_confidence = result.get('confidence', 0.0)
                if result.get('found'):
                    match_results.append((img_name, result['x'], result['y'], template_w, template_h, actual_confidence, client_w, client_h))
                    logger.info(f"  [插件] {img_name}: 找到 @ ({result['x']}, {result['y']}), 相似度={actual_confidence:.4f}")
                else:
                    logger.info(f"  [插件] {img_name}: 未达阈值 (相似度={actual_confidence:.4f} < {confidence})")
            else:
                logger.info(f"  [插件] {img_name}: 未找到")

        except Exception as e:
            logger.warning(f"  [插件] {img_name}: 匹配出错 - {e}")

    return match_results


def _test_with_opencv(image_paths: List[str], target_hwnd: int, confidence: float,
                      preprocessing_method: str, use_region: bool, region_x: int,
                      region_y: int, region_w: int, region_h: int) -> List[Tuple]:
    """使用原生模式（OpenCV）进行测试找图。

    统一调用本地截图引擎执行“截图+匹配”。
    """
    from tasks.mouse_action_task import safe_imread

    match_results = []

    roi_param = None
    if use_region and region_w > 0 and region_h > 0:
        roi_param = (int(region_x), int(region_y), int(region_w), int(region_h))
        logger.info(f"已应用识别区域: {roi_param}")

    for img_path in image_paths:
        img_name = os.path.basename(img_path)
        try:
            template = safe_imread(img_path, cv2.IMREAD_COLOR)
            if template is None:
                logger.warning(f"  无法读取图片: {img_name}")
                continue

            template = normalize_match_image(template)
            if template is None:
                logger.warning(f"  模板规范化失败: {img_name}")
                continue

            try:
                from utils.screenshot_helper import get_screenshot_engine
                match_engine = str(get_screenshot_engine() or "wgc").strip().lower()
            except Exception:
                match_engine = "wgc"
            if match_engine not in {"wgc", "printwindow", "gdi", "dxgi"}:
                match_engine = "wgc"

            match_response = capture_and_match_template_smart(
                target_hwnd=target_hwnd,
                template=template,
                confidence_threshold=float(confidence),
                template_key=(str(img_path) if img_path else None),
                capture_timeout=0.8,
                engine=match_engine,
                roi=roi_param,
                client_area_only=True,
                use_cache=False,
            )

            if not match_response or not bool(match_response.get("success")):
                err = (match_response or {}).get("error") if isinstance(match_response, dict) else "unknown_error"
                logger.info(f"  [OpenCV-Engine] {img_name}: 匹配失败 ({err})")
                continue

            try:
                max_val = float(match_response.get("confidence", 0.0) or 0.0)
            except Exception:
                max_val = 0.0

            raw_location = match_response.get("location")
            parsed_location = None
            if isinstance(raw_location, (list, tuple)) and len(raw_location) == 4:
                try:
                    parsed_location = (
                        int(raw_location[0]),
                        int(raw_location[1]),
                        int(raw_location[2]),
                        int(raw_location[3]),
                    )
                except Exception:
                    parsed_location = None

            if bool(match_response.get("matched", False)) and parsed_location is not None and max_val >= confidence:
                found_x, found_y, template_w, template_h = parsed_location
                screenshot_w = match_response.get("screenshot_width")
                screenshot_h = match_response.get("screenshot_height")
                if screenshot_w is None or screenshot_h is None:
                    screenshot_shape = match_response.get("screenshot_shape")
                    if isinstance(screenshot_shape, (list, tuple)) and len(screenshot_shape) >= 2:
                        try:
                            screenshot_h = int(screenshot_shape[0])
                            screenshot_w = int(screenshot_shape[1])
                        except Exception:
                            screenshot_w = None
                            screenshot_h = None

                if screenshot_w is None or int(screenshot_w) <= 0:
                    screenshot_w = template.shape[1] if len(template.shape) >= 2 else template_w
                if screenshot_h is None or int(screenshot_h) <= 0:
                    screenshot_h = template.shape[0] if len(template.shape) >= 2 else template_h

                match_results.append((
                    img_name,
                    found_x,
                    found_y,
                    template_w,
                    template_h,
                    max_val,
                    int(screenshot_w),
                    int(screenshot_h),
                ))
                logger.info(f"  [OpenCV-Engine] {img_name}: 找到 @ ({found_x}, {found_y}), 相似度 {max_val:.4f}")
            else:
                logger.info(f"  [OpenCV-Engine] {img_name}: 未达阈值 (相似度 {max_val:.4f} < {confidence})")

        except Exception as e:
            logger.warning(f"  [OpenCV-Engine] {img_name}: 匹配出错 - {e}")

    return match_results
def _draw_overlay(
    target_hwnd: int,
    match_results: List[Tuple],
    restore_callback=None,
    source_size: Optional[Tuple[int, int]] = None,
):
    """在窗口上绘制识别结果覆盖层

    Args:
        target_hwnd: 目标窗口句柄
        match_results: 匹配结果列表
        restore_callback: 覆盖层关闭后的回调函数（用于恢复主窗口）
        source_size: 结果坐标对应的来源尺寸（宽, 高）
    """
    try:
        from PySide6.QtWidgets import QWidget, QApplication
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtGui import QPainter, QPen, QColor, QFont
        from ui.widgets.window_overlay_utils import (
            draw_dynamic_center_crosshair,
            get_window_client_overlay_metrics,
            map_native_rect_to_local,
            sync_overlay_geometry,
        )

        class RecognitionOverlay(QWidget):
            def __init__(self, hwnd, results, on_close_callback=None, result_source_size=None):
                super().__init__(None)
                self.target_hwnd = hwnd
                self.match_results = results
                self.on_close_callback = on_close_callback
                self._result_source_size = result_source_size
                self._client_native_rect = None
                self._client_physical_size = (0, 0)

                self.colors = [
                    QColor(0, 255, 0),
                    QColor(255, 165, 0),
                    QColor(0, 191, 255),
                    QColor(255, 0, 255),
                    QColor(255, 255, 0),
                    QColor(0, 255, 255),
                ]

                self.setWindowFlags(
                    Qt.WindowType.FramelessWindowHint |
                    Qt.WindowType.WindowStaysOnTopHint |
                    Qt.WindowType.Tool |
                    Qt.WindowType.WindowTransparentForInput
                )
                self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
                self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
                self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

                self._position_overlay()

            def _position_overlay(self):
                try:
                    sync_overlay_geometry(self)
                    metrics = get_window_client_overlay_metrics(self.target_hwnd)
                    if not metrics:
                        logger.warning("图片识别预览覆盖层坐标转换失败")
                        return
                    native_rect = metrics.get("native_rect")
                    if not native_rect or len(native_rect) != 4:
                        logger.warning("图片识别预览覆盖层客户区原生坐标无效")
                        return

                    self._client_native_rect = tuple(int(v) for v in native_rect)
                    physical_size = metrics.get("physical_size", (0, 0))
                    self._client_physical_size = (
                        max(1, int(physical_size[0])) if len(physical_size) >= 1 else 1,
                        max(1, int(physical_size[1])) if len(physical_size) >= 2 else 1,
                    )
                except Exception as e:
                    logger.error(f"定位覆盖层失败: {e}")

            def paintEvent(self, event):
                painter = QPainter(self)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)

                if not self._client_native_rect or len(self._client_native_rect) != 4:
                    painter.end()
                    return

                client_left, client_top, client_right, client_bottom = self._client_native_rect
                client_w = max(1, int(client_right - client_left))
                client_h = max(1, int(client_bottom - client_top))

                source_w = client_w
                source_h = client_h
                if self._client_physical_size[0] > 0 and self._client_physical_size[1] > 0:
                    source_w, source_h = self._client_physical_size
                if (
                    isinstance(self._result_source_size, (list, tuple))
                    and len(self._result_source_size) >= 2
                ):
                    try:
                        parsed_w = int(self._result_source_size[0])
                        parsed_h = int(self._result_source_size[1])
                        if parsed_w > 0 and parsed_h > 0:
                            source_w = parsed_w
                            source_h = parsed_h
                    except Exception:
                        pass

                for i, result in enumerate(self.match_results):
                    img_name, x, y, w, h, sim = result[:6]
                    color = self.colors[i % len(self.colors)]

                    current_source_w = source_w
                    current_source_h = source_h
                    if len(result) >= 8:
                        try:
                            parsed_source_w = int(result[6])
                            parsed_source_h = int(result[7])
                            if parsed_source_w > 0 and parsed_source_h > 0:
                                current_source_w = parsed_source_w
                                current_source_h = parsed_source_h
                        except Exception:
                            pass

                    source_to_client_x = client_w / float(current_source_w) if current_source_w > 0 else 1.0
                    source_to_client_y = client_h / float(current_source_h) if current_source_h > 0 else 1.0

                    native_left = int(round(client_left + (x * source_to_client_x)))
                    native_top = int(round(client_top + (y * source_to_client_y)))
                    native_width = max(1, int(round(w * source_to_client_x)))
                    native_height = max(1, int(round(h * source_to_client_y)))
                    draw_rect = map_native_rect_to_local(
                        self,
                        (
                            native_left,
                            native_top,
                            native_left + native_width,
                            native_top + native_height,
                        ),
                    )
                    if draw_rect.isEmpty():
                        continue

                    # 绘制矩形框
                    box_pen_width = 3
                    pen = QPen(color, box_pen_width)
                    painter.setPen(pen)
                    painter.drawRect(draw_rect)

                    draw_dynamic_center_crosshair(
                        painter,
                        draw_rect,
                        color=color,
                        inset=box_pen_width,
                    )

                    # 绘制标签
                    font = QFont("Microsoft YaHei", 10)
                    font.setBold(True)
                    painter.setFont(font)
                    label = f"{img_name}: {sim:.2%}"
                    painter.drawText(int(draw_rect.left()), int(draw_rect.top()) - 5, label)

                painter.end()

            def closeEvent(self, event):
                """覆盖层关闭时调用回调"""
                if self.on_close_callback:
                    try:
                        self.on_close_callback()
                    except Exception as e:
                        logger.error(f"恢复窗口回调失败: {e}")
                super().closeEvent(event)

        app = QApplication.instance()
        if app is None:
            logger.error("QApplication 实例不存在，无法绘制覆盖层")
            if restore_callback:
                restore_callback()
            return

        def _promote_overlay_window(widget):
            try:
                import ctypes

                hwnd = int(widget.winId())
                if hwnd <= 0:
                    return

                user32 = ctypes.windll.user32
                user32.SetWindowPos(
                    hwnd,
                    -1,
                    0,
                    0,
                    0,
                    0,
                    0x0001 | 0x0002 | 0x0010 | 0x0040,
                )
            except Exception:
                pass

        # 使用闭包捕获变量
        hwnd = target_hwnd
        results = list(match_results)
        callback = restore_callback
        result_source_size = source_size
        OverlayClass = RecognitionOverlay

        def create_and_show_overlay():
            try:
                overlay = OverlayClass(hwnd, results, callback, result_source_size)

                # 保持引用防止被垃圾回收
                if not hasattr(_draw_overlay, '_overlay_instances'):
                    _draw_overlay._overlay_instances = []
                _draw_overlay._overlay_instances.append(overlay)

                # 清理引用的回调
                def on_destroyed():
                    try:
                        if hasattr(_draw_overlay, '_overlay_instances'):
                            _draw_overlay._overlay_instances.remove(overlay)
                    except (ValueError, RuntimeError):
                        pass

                overlay.destroyed.connect(on_destroyed)
                overlay.show()
                overlay.raise_()
                overlay.update()
                _promote_overlay_window(overlay)
                QTimer.singleShot(50, lambda: _promote_overlay_window(overlay))
                QTimer.singleShot(150, lambda: _promote_overlay_window(overlay))
                QTimer.singleShot(300, lambda: _promote_overlay_window(overlay))

                # 3秒后自动关闭
                QTimer.singleShot(3000, overlay.close)

                logger.info(f"已绘制识别结果覆盖层，3秒后自动消失")
            except Exception as e:
                logger.error(f"创建覆盖层失败: {e}", exc_info=True)
                if callback:
                    callback()

        # 确保在主线程执行
        from PySide6.QtCore import QThread, QObject, Signal

        if QThread.currentThread() == app.thread():
            # 已在主线程，直接执行
            create_and_show_overlay()
        else:
            # 在子线程，使用信号槽机制转发到主线程
            logger.info("在子线程，通过信号槽转发到主线程创建覆盖层")

            # 使用模块级单例 Invoker 对象
            if not hasattr(_draw_overlay, '_invoker'):
                class Invoker(QObject):
                    invoke = Signal(object)

                    def __init__(self):
                        super().__init__()
                        self.invoke.connect(self._run)

                    def _run(self, func):
                        try:
                            func()
                        except Exception as e:
                            logger.error(f"Invoker 执行失败: {e}")

                invoker = Invoker()
                invoker.moveToThread(app.thread())
                _draw_overlay._invoker = invoker

            _draw_overlay._invoker.invoke.emit(create_and_show_overlay)

    except Exception as e:
        logger.error(f"绘制覆盖层失败: {e}", exc_info=True)
        if restore_callback:
            restore_callback()

