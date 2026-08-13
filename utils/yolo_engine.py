#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
YOLO ONNX推理引擎
纯ONNX Runtime实现，无需PyTorch/ultralytics依赖
体积优化：从454MB降至约20MB
"""

import os
import ast
import json
import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort
from utils.app_paths import get_app_root
from utils.input_simulation.mode_utils import is_foreground_mode

logger = logging.getLogger(__name__)


def _read_max_cached_engine_instances() -> int:
    raw_value = os.getenv("YOLO_ENGINE_MAX_CACHED_INSTANCES", "2")
    try:
        value = int(raw_value)
    except Exception:
        value = 2
    return max(1, min(8, value))


@dataclass
class DetectionResult:
    """检测结果数据类"""
    x1: int
    y1: int
    x2: int
    y2: int
    confidence: float
    class_id: int
    class_name: str
    track_id: Optional[int] = None

    @property
    def bbox(self) -> Tuple[int, int, int, int]:
        return (self.x1, self.y1, self.x2, self.y2)

    @property
    def center_x(self) -> int:
        return (self.x1 + self.x2) // 2

    @property
    def center_y(self) -> int:
        return (self.y1 + self.y2) // 2

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    @property
    def area(self) -> int:
        return self.width * self.height

    def __repr__(self) -> str:
        track_str = f", track_id={self.track_id}" if self.track_id is not None else ""
        return (f"DetectionResult(class={self.class_name}, conf={self.confidence:.2f}, "
                f"center=({self.center_x}, {self.center_y}), size={self.width}x{self.height}{track_str})")


class YOLOONNXEngine:
    """YOLO ONNX推理引擎 - 纯ONNX Runtime实现"""

    _instances: "OrderedDict[str, YOLOONNXEngine]" = OrderedDict()
    _lock = threading.Lock()
    _max_cached_instances = _read_max_cached_engine_instances()

    @staticmethod
    def _normalize_input_size(input_size: Optional[int]) -> Optional[int]:
        if input_size is None:
            return None
        try:
            value = int(input_size)
        except Exception:
            return None
        if value <= 0:
            return None
        return value

    @classmethod
    def _build_instance_key(cls, model_path: str, input_size: Optional[int]) -> str:
        normalized_model_path = str(model_path or "yolo/yolov8n.onnx").strip()
        normalized_input_size = cls._normalize_input_size(input_size)
        return f"{normalized_model_path}_{normalized_input_size}"

    @staticmethod
    def _normalize_threshold(value: float, default: float) -> float:
        try:
            normalized = float(value)
        except Exception:
            normalized = default
        if normalized < 0.0:
            return 0.0
        if normalized > 1.0:
            return 1.0
        return normalized

    def _apply_runtime_thresholds(self, conf_threshold: float, iou_threshold: float) -> None:
        self.conf_threshold = self._normalize_threshold(conf_threshold, 0.5)
        self.iou_threshold = self._normalize_threshold(iou_threshold, 0.45)

    def __new__(cls, model_path: str = "yolo/yolov8n.onnx",
                conf_threshold: float = 0.5, iou_threshold: float = 0.45,
                input_size: Optional[int] = None):
        """缓存模式 - 同模型/输入尺寸复用实例，并限制缓存数量。"""
        key = cls._build_instance_key(model_path=model_path, input_size=input_size)
        evicted_instance = None
        with cls._lock:
            if key in cls._instances:
                instance = cls._instances[key]
                cls._instances.move_to_end(key)
                return instance

            instance = super().__new__(cls)
            cls._instances[key] = instance

            if len(cls._instances) > cls._max_cached_instances:
                _, evicted_instance = cls._instances.popitem(last=False)

        if evicted_instance is not None:
            try:
                evicted_instance.unload_model()
            except Exception as e:
                logger.warning("淘汰旧YOLO引擎实例失败: %s", e)
        return instance

    def __init__(self, model_path: str = "yolo/yolov8n.onnx",
                 conf_threshold: float = 0.5, iou_threshold: float = 0.45,
                 input_size: Optional[int] = None):
        if hasattr(self, '_initialized') and self._initialized:
            self._apply_runtime_thresholds(conf_threshold, iou_threshold)
            return

        self.model_path = model_path
        self.conf_threshold = 0.5
        self.iou_threshold = 0.45
        self._session = None
        self._model_loaded = False
        self._load_lock = threading.Lock()
        self._input_name = None
        self._output_names = None
        self._input_shape = None
        self._input_size = self._normalize_input_size(input_size)
        self._input_size_override = None
        self._input_size_warned = False
        self._class_names = []
        self._device = 'CPU'  # 默认CPU，加载模型时会更新
        self._apply_runtime_thresholds(conf_threshold, iou_threshold)
        self._initialized = True

    def _resolve_model_path(self) -> Path:
        path = Path(self.model_path)
        if path.is_absolute():
            if path.is_file():
                return path
            raise FileNotFoundError(f"模型文件不存在: {path}")

        candidate = Path(get_app_root()) / self.model_path
        if candidate.is_file():
            return candidate
        raise FileNotFoundError(f"模型文件不存在: {candidate}")

    def _load_model(self) -> bool:
        """加载ONNX模型"""
        if self._model_loaded:
            return True

        with self._load_lock:
            if self._model_loaded:
                return True

            try:
                model_path = self._resolve_model_path()
                if model_path.suffix.lower() != '.onnx':
                    raise ValueError(f"不支持的模型格式: {model_path.suffix}，只支持.onnx格式")

                # 创建ONNX Runtime会话
                sess_options = ort.SessionOptions()
                sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

                # 自动检测ONNX Runtime provider，和地图定位共用同一套选择逻辑
                available_providers = ort.get_available_providers()
                from utils.dml_adapter import (
                    build_onnxruntime_providers,
                    is_gpu_onnx_provider,
                    provider_name_from_entry,
                )

                providers, device_desc = build_onnxruntime_providers(available_providers)
                requested_provider_names = [provider_name_from_entry(provider) for provider in providers]
                logger.info(
                    "ONNX Runtime providers: requested=%s target=%s available=%s",
                    requested_provider_names,
                    device_desc,
                    list(available_providers),
                )

                self._session = ort.InferenceSession(
                    str(model_path),
                    sess_options=sess_options,
                    providers=providers
                )

                # 记录实际使用的provider
                actual_provider = self._session.get_providers()[0] if self._session.get_providers() else 'Unknown'
                self._device = 'GPU' if is_gpu_onnx_provider(actual_provider) else 'CPU'
                logger.info(f"ONNX Runtime实际使用: {actual_provider}")

                # 获取模型输入输出信息
                self._input_name = self._session.get_inputs()[0].name
                self._output_names = [output.name for output in self._session.get_outputs()]
                self._input_shape = self._session.get_inputs()[0].shape

                if self._input_size:
                    if self._is_dynamic_shape(self._input_shape):
                        self._input_size_override = int(self._input_size)
                        logger.info(f"Using dynamic input size override: {self._input_size_override}")
                    elif not self._input_size_warned:
                        self._input_size_warned = True
                        logger.warning("Input size override ignored: static model input shape")

                # 尝试加载类别名称（从元数据或配置文件）
                self._load_class_names(model_path)

                self._model_loaded = True
                logger.info(f"ONNX模型加载成功: {model_path}")
                logger.info(f"  输入: {self._input_name} {self._input_shape}")
                logger.info(f"  输出: {self._output_names}")
                logger.info(f"  类别数: {len(self._class_names)}")
                return True

            except Exception as e:
                logger.error(f"加载ONNX模型失败: {e}")
                raise


    @staticmethod
    def _is_dynamic_dim(dim) -> bool:
        return dim is None or dim == -1 or (isinstance(dim, str) and dim != "")

    @classmethod
    def _is_dynamic_shape(cls, shape) -> bool:
        return any(cls._is_dynamic_dim(dim) for dim in shape)

    @staticmethod
    def _read_classes_file(classes_file: Path) -> List[str]:
        encodings = ["utf-8", "gbk", "gb2312", "iso-8859-1"]
        for encoding in encodings:
            try:
                with open(classes_file, 'r', encoding=encoding) as f:
                    class_names = [line.strip() for line in f if line.strip()]
                if class_names:
                    return class_names
            except UnicodeDecodeError:
                continue
            except Exception:
                break
        return []

    @staticmethod
    def _parse_class_names_value(value: Optional[str]) -> List[str]:
        if not value:
            return []
        if isinstance(value, bytes):
            try:
                value = value.decode("utf-8")
            except Exception:
                value = value.decode(errors="ignore")
        if not isinstance(value, str):
            return []

        try:
            parsed = json.loads(value)
        except Exception:
            try:
                parsed = ast.literal_eval(value)
            except Exception:
                return []

        if isinstance(parsed, dict):
            try:
                items = sorted(parsed.items(), key=lambda kv: int(kv[0]))
            except Exception:
                items = sorted(parsed.items(), key=lambda kv: str(kv[0]))
            return [str(v).strip() for _, v in items if str(v).strip()]

        if isinstance(parsed, list):
            return [str(v).strip() for v in parsed if str(v).strip()]

        return []

    def _load_class_names_from_metadata(self) -> List[str]:
        if not self._session:
            return []
        try:
            meta = self._session.get_modelmeta()
            custom_map = getattr(meta, "custom_metadata_map", None) or {}
            names_value = (
                custom_map.get("names")
                or custom_map.get("names_str")
                or custom_map.get("classes")
            )
            class_names = self._parse_class_names_value(names_value)
            if class_names:
                logger.info("Loaded class names from ONNX metadata")
            return class_names
        except Exception as e:
            logger.warning(f"从 ONNX 元数据读取类别名失败：{e}")
            return []

    def _load_class_names(self, model_path: Path):
        """加载类别名称"""
        metadata_names = self._load_class_names_from_metadata()
        if metadata_names:
            self._class_names = metadata_names
            return

        classes_file = model_path.parent / "classes.txt"
        if classes_file.exists():
            try:
                class_names = self._read_classes_file(classes_file)
                if class_names:
                    self._class_names = class_names
                    logger.info(
                        "Loaded %d classes from %s",
                        len(self._class_names),
                        classes_file.name,
                    )
                    return
            except Exception as e:
                logger.warning(f"读取 classes.txt 失败：{e}")

        self._class_names = []
        logger.warning("未在 ONNX 元数据或 classes.txt 中找到类别名，将使用 class_id 标签")

    def _preprocess(self, image: np.ndarray) -> Tuple[np.ndarray, float, Tuple[int, int]]:
        """预处理图像"""
        # 获取输入尺寸
        input_height = self._input_shape[2] if len(self._input_shape) > 2 else 640
        input_width = self._input_shape[3] if len(self._input_shape) > 3 else 640

        if self._input_size_override and self._input_size_override > 0:
            input_height = self._input_size_override
            input_width = self._input_size_override

        # 保持宽高比缩放
        h, w = image.shape[:2]
        scale = min(input_width / w, input_height / h)
        new_w, new_h = int(w * scale), int(h * scale)

        # 缩放图像
        resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

        # 填充到模型输入尺寸
        padded = np.full((input_height, input_width, 3), 114, dtype=np.uint8)
        padded[:new_h, :new_w] = resized

        # 转换为NCHW格式并归一化
        input_tensor = padded.transpose(2, 0, 1).astype(np.float32) / 255.0
        input_tensor = np.expand_dims(input_tensor, axis=0)

        return input_tensor, scale, (new_w, new_h)

    def _postprocess(self, outputs: List[np.ndarray], scale: float,
                     orig_shape: Tuple[int, int]) -> List[DetectionResult]:
        """后处理检测结果"""
        # YOLOv8输出格式: (1, 84, 8400) 或 (1, num_classes+4, num_boxes)
        predictions = outputs[0]

        # 转置为 (num_boxes, num_classes+4)
        if len(predictions.shape) == 3:
            predictions = predictions[0].T
        else:
            predictions = predictions.T

        # 提取框和分数
        boxes = predictions[:, :4]  # x, y, w, h
        scores = predictions[:, 4:]  # class scores

        # 获取最高分数的类别
        class_ids = np.argmax(scores, axis=1)
        confidences = np.max(scores, axis=1)

        # 置信度过滤
        mask = confidences >= self.conf_threshold
        boxes = boxes[mask]
        confidences = confidences[mask]
        class_ids = class_ids[mask]

        if len(boxes) == 0:
            return []

        # 转换为x1y1x2y2格式
        x_center, y_center, w, h = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
        x1 = x_center - w / 2
        y1 = y_center - h / 2
        x2 = x_center + w / 2
        y2 = y_center + h / 2

        # 缩放回原图尺寸
        x1 = (x1 / scale).astype(int)
        y1 = (y1 / scale).astype(int)
        x2 = (x2 / scale).astype(int)
        y2 = (y2 / scale).astype(int)

        # NMS
        boxes_for_nms = np.column_stack([x1, y1, x2, y2])
        indices = self._nms(boxes_for_nms, confidences, self.iou_threshold)

        # 构建结果
        results = []
        for idx in indices:
            class_id = int(class_ids[idx])
            class_name = self._class_names[class_id] if class_id < len(self._class_names) else f"class_{class_id}"

            result = DetectionResult(
                x1=int(x1[idx]),
                y1=int(y1[idx]),
                x2=int(x2[idx]),
                y2=int(y2[idx]),
                confidence=float(confidences[idx]),
                class_id=class_id,
                class_name=class_name
            )
            results.append(result)

        return results

    @staticmethod
    def _nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> List[int]:
        """非极大值抑制"""
        x1 = boxes[:, 0]
        y1 = boxes[:, 1]
        x2 = boxes[:, 2]
        y2 = boxes[:, 3]

        areas = (x2 - x1) * (y2 - y1)
        order = scores.argsort()[::-1]

        keep = []
        while order.size > 0:
            i = order[0]
            keep.append(i)

            xx1 = np.maximum(x1[i], x1[order[1:]])
            yy1 = np.maximum(y1[i], y1[order[1:]])
            xx2 = np.minimum(x2[i], x2[order[1:]])
            yy2 = np.minimum(y2[i], y2[order[1:]])

            w = np.maximum(0.0, xx2 - xx1)
            h = np.maximum(0.0, yy2 - yy1)
            inter = w * h

            iou = inter / (areas[i] + areas[order[1:]] - inter)
            inds = np.where(iou <= iou_threshold)[0]
            order = order[inds + 1]

        return keep

    def predict(self, image: np.ndarray, classes: Optional[List[str]] = None) -> List[DetectionResult]:
        """执行检测"""
        self._load_model()

        try:
            import time
            t0 = time.perf_counter()

            # 预处理
            input_tensor, scale, _ = self._preprocess(image)
            orig_shape = image.shape[:2]
            t1 = time.perf_counter()

            # 推理
            outputs = self._session.run(self._output_names, {self._input_name: input_tensor})
            t2 = time.perf_counter()

            # 后处理
            detections = self._postprocess(outputs, scale, orig_shape)
            t3 = time.perf_counter()

            # 类别过滤
            if classes and "全部类别" not in classes:
                detections = [d for d in detections if d.class_name in classes]

            t4 = time.perf_counter()
            logger.debug(
                "YOLO性能: 预处理=%dms, 推理=%dms, 后处理=%dms, 总计=%dms",
                int((t1 - t0) * 1000),
                int((t2 - t1) * 1000),
                int((t3 - t2) * 1000),
                int((t4 - t0) * 1000),
            )

            return detections

        except Exception as e:
            logger.error(f"ONNX推理失败: {e}")
            import traceback
            traceback.print_exc()
            return []

    def detect_from_hwnd(self, hwnd: int,
                         target_classes: Optional[List[str]] = None,
                         conf_threshold: Optional[float] = None,
                         execution_mode: str = "background",
                         iou_threshold: Optional[float] = None,
                         roi: Optional[Tuple[int, int, int, int]] = None) -> Tuple[List[DetectionResult], Optional[np.ndarray]]:
        """从窗口句柄进行检测

        Args:
            roi: 感兴趣区域 (x, y, width, height)，仅在此区域内检测
        """
        screenshot = self._capture_window(hwnd, execution_mode)
        if screenshot is None:
            return [], None

        screenshot = self._ensure_bgr(screenshot)

        # 裁剪ROI区域
        if roi and roi[2] > 0 and roi[3] > 0:
            x, y, w, h = roi
            img_h, img_w = screenshot.shape[:2]
            x1 = max(0, min(x, img_w))
            y1 = max(0, min(y, img_h))
            x2 = max(0, min(x + w, img_w))
            y2 = max(0, min(y + h, img_h))
            if x2 > x1 and y2 > y1:
                roi_img = screenshot[y1:y2, x1:x2]
                detections = self.predict(roi_img, target_classes)
                # 坐标转换回原图
                for det in detections:
                    det.x1 += x1
                    det.y1 += y1
                    det.x2 += x1
                    det.y2 += y1
                return detections, screenshot

        detections = self.predict(screenshot, target_classes)
        return detections, screenshot

    def track_from_hwnd(self, hwnd: int,
                        target_classes: Optional[List[str]] = None,
                        conf_threshold: Optional[float] = None,
                        execution_mode: str = "background",
                        iou_threshold: Optional[float] = None,
                        tracker_type: str = "bytetrack.yaml",
                        persist: bool = True) -> Tuple[List[DetectionResult], Optional[np.ndarray]]:
        raise RuntimeError("ONNX 引擎不支持目标跟踪")

    def _capture_window(self, hwnd: int, execution_mode: str = "background") -> Optional[np.ndarray]:
        """捕获窗口截图。"""
        if not is_foreground_mode(execution_mode):
            logger.error("YOLO截图仅支持前台模式，当前模式: %s", execution_mode)
            return None

        # 复用统一截图引擎，避免重复实现截图逻辑
        try:
            from utils.screenshot_helper import (
                _capture_with_engine,
                get_screenshot_engine,
                probe_dxgi_runtime_available,
            )

            img_bgr = None
            engine_used = None
            current_engine = get_screenshot_engine()
            if current_engine not in {"dxgi", "gdi"}:
                logger.error(
                    "YOLO capture only supports dxgi/gdi; current_engine=%s",
                    current_engine,
                )
                return None

            if current_engine == "dxgi":
                dxgi_available = False
                try:
                    dxgi_available = bool(probe_dxgi_runtime_available())
                except Exception:
                    dxgi_available = False
                if not dxgi_available:
                    logger.warning("YOLO DXGI预检失败，继续尝试实际抓图")
            img_bgr = _capture_with_engine(
                hwnd=hwnd,
                client_area_only=True,
                engine=current_engine,
                timeout=0.8,
            )
            engine_used = current_engine
            if img_bgr is None:
                logger.error("YOLO 截图失败：句柄=%s，引擎=%s", hwnd, engine_used)
                return None
            return img_bgr
        except Exception as e:
            logger.error(f"YOLO 截图失败：{e}")
            return None

    @staticmethod
    def _ensure_bgr(image: np.ndarray) -> np.ndarray:
        """确保图像是BGR格式"""
        if image is None:
            return None
        if len(image.shape) == 2:
            return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        if image.shape[2] == 4:
            return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        return image

    @property
    def names(self) -> Dict[int, str]:
        """获取类别名称字典"""
        return {i: name for i, name in enumerate(self._class_names)}

    def unload_model(self):
        """卸载YOLO模型，释放ONNX会话和内存"""
        with self._load_lock:
            try:
                if self._session:
                    del self._session
                    self._session = None
                    logger.info("YOLO模型会话已释放")

                # 清理输入输出元数据
                self._input_name = None
                self._output_names = None
                self._input_shape = None

                # 清理类名列表
                if self._class_names:
                    self._class_names.clear()
                    self._class_names = []

            except Exception as e:
                logger.error(f"卸载YOLO模型失败: {e}")
            finally:
                self._model_loaded = False
                try:
                    import gc
                    gc.collect()
                except Exception:
                    pass

    @classmethod
    def clear_instances(cls):
        """清理所有实例"""
        with cls._lock:
            for instance in cls._instances.values():
                try:
                    instance.unload_model()
                except Exception as e:
                    logger.error(f"清理实例失败: {e}")
            cls._instances.clear()
            try:
                import gc
                gc.collect()
            except Exception:
                pass
            logger.info("已清理所有ONNX引擎实例")


def get_yolo_engine(model_path: str = "yolo/yolov8n.onnx",
                    conf_threshold: float = 0.5,
                    iou_threshold: float = 0.45,
                    input_size: Optional[int] = None) -> YOLOONNXEngine:
    """获取 YOLO ONNX 引擎实例。"""
    normalized_path = str(model_path or "").strip()
    if not normalized_path:
        raise ValueError("YOLO 模型路径不能为空")
    if normalized_path.lower().endswith(".pt"):
        raise ValueError("YOLO 只支持 .onnx 模型，不接受 .pt")

    return YOLOONNXEngine(
        model_path=normalized_path,
        conf_threshold=conf_threshold,
        iou_threshold=iou_threshold,
        input_size=input_size,
    )
