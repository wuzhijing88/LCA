"""Offline RapidOCR service backed by local PP-OCRv4 mobile ONNX models."""

from __future__ import annotations

import gc
import hashlib
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

from services.ocr_runtime_contract import OCR_MODEL_FILES, OCR_MODEL_NAME
from utils.app_paths import get_app_root


logger = logging.getLogger(__name__)


_MODEL_FILES = OCR_MODEL_FILES


def _read_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _read_bool_env(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    normalized = str(raw_value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RapidOCROCRService:
    """Own one RapidOCR engine inside an OCR worker process."""

    def __init__(self) -> None:
        self._engine = None
        self._service_active = False
        self._is_initializing = False
        self._init_error: Optional[str] = None
        self._error_count = 0
        self._last_success_time = 0.0
        self._init_lock = threading.RLock()
        self._recognition_lock = threading.Lock()
        self._model_dir = Path(get_app_root()) / "models" / "rapidocr"
        self._model_paths = {
            key: self._model_dir / filename
            for key, (filename, _expected_hash) in _MODEL_FILES.items()
        }
        self._cpu_threads = _read_int_env("OCR_CPU_THREADS", 2, 1, 8)
        self._use_directml = _read_bool_env("OCR_USE_DIRECTML", False)
        self._use_angle_classifier = _read_bool_env(
            "OCR_USE_ANGLE_CLASSIFIER",
            True,
        )

    @property
    def init_error(self) -> Optional[str]:
        return self._init_error

    def _validate_local_models(self) -> bool:
        problems: List[str] = []
        for key, (filename, expected_hash) in _MODEL_FILES.items():
            path = self._model_paths[key]
            if not path.is_file():
                problems.append(f"缺少 {filename}")
                continue
            try:
                actual_hash = _sha256(path)
            except OSError as exc:
                problems.append(f"无法读取 {filename}: {exc}")
                continue
            if actual_hash.lower() != expected_hash.lower():
                problems.append(f"校验失败 {filename}")

        if problems:
            self._init_error = (
                f"本地 RapidOCR 模型不可用: {'；'.join(problems)}。"
                f"请检查目录 {self._model_dir}"
            )
            logger.error(self._init_error)
            return False
        return True

    def initialize(self, force_reinit: bool = False) -> bool:
        if self._engine is not None and not force_reinit:
            self._service_active = True
            return True

        with self._init_lock:
            if self._engine is not None and not force_reinit:
                self._service_active = True
                return True
            if self._is_initializing:
                return False

            self._is_initializing = True
            self._init_error = None
            try:
                if not self._validate_local_models():
                    return False

                from rapidocr import (
                    LangCls,
                    LangDet,
                    LangRec,
                    ModelType,
                    OCRVersion,
                    RapidOCR,
                )

                params = {
                    "Global.model_root_dir": str(self._model_dir),
                    "Global.text_score": 0.0,
                    "Global.use_det": True,
                    "Global.use_cls": self._use_angle_classifier,
                    "Global.use_rec": True,
                    "Global.log_level": "warning",
                    "EngineConfig.onnxruntime.intra_op_num_threads": self._cpu_threads,
                    "EngineConfig.onnxruntime.inter_op_num_threads": 1,
                    "EngineConfig.onnxruntime.enable_cpu_mem_arena": False,
                    "EngineConfig.onnxruntime.use_dml": self._use_directml,
                    "Det.ocr_version": OCRVersion.PPOCRV4,
                    "Det.model_type": ModelType.MOBILE,
                    "Det.lang_type": LangDet.CH,
                    "Det.model_path": str(self._model_paths["det"]),  # 指定本地 v4，避免 RapidOCR 回落到自带 v6
                    "Det.limit_type": "max",
                    "Det.limit_side_len": 960,
                    "Det.thresh": 0.2,
                    "Det.box_thresh": 0.3,
                    "Det.use_dilation": False,
                    "Cls.ocr_version": OCRVersion.PPOCRV4,
                    "Cls.model_type": ModelType.MOBILE,
                    "Cls.lang_type": LangCls.CH,
                    "Cls.model_path": str(self._model_paths["cls"]),
                    "Rec.ocr_version": OCRVersion.PPOCRV4,
                    "Rec.model_type": ModelType.MOBILE,
                    "Rec.lang_type": LangRec.CH,
                    "Rec.model_path": str(self._model_paths["rec"]),
                }

                self._engine = RapidOCR(params=params)
                self._service_active = True
                self._error_count = 0
                backend = "DirectML" if self._use_directml else "CPU"
                logger.info(
                    "RapidOCR 初始化成功: model=%s, backend=%s, cpu_threads=%s",
                    OCR_MODEL_NAME,
                    backend,
                    self._cpu_threads,
                )
                return True
            except Exception as exc:
                self._engine = None
                self._service_active = False
                self._init_error = f"{exc.__class__.__name__}: {exc}"
                logger.error("RapidOCR 初始化失败: %s", self._init_error, exc_info=True)
                return False
            finally:
                self._is_initializing = False

    def is_ready(self) -> bool:
        return self._service_active and self._engine is not None

    @staticmethod
    def _prepare_image(image: np.ndarray) -> np.ndarray:
        if not isinstance(image, np.ndarray) or image.size == 0:
            raise ValueError("OCR 输入图像为空")
        if image.ndim == 2:
            prepared = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        elif image.ndim == 3 and image.shape[2] == 4:
            prepared = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        elif image.ndim == 3 and image.shape[2] == 3:
            prepared = image
        else:
            raise ValueError(f"不支持的 OCR 图像形状: {image.shape}")
        return np.ascontiguousarray(prepared, dtype=np.uint8)

    def recognize_text(
        self,
        image: np.ndarray,
        confidence: float = 0.5,
    ) -> List[Dict[str, Any]]:
        if not self.is_ready() and not self.initialize():
            logger.warning("RapidOCR 服务未就绪: %s", self._init_error or "未知原因")
            return []

        score_threshold = max(0.0, min(1.0, float(confidence)))
        try:
            prepared = self._prepare_image(image)
            with self._recognition_lock:
                result = self._engine(
                    prepared,
                    use_det=True,
                    use_cls=self._use_angle_classifier,
                    use_rec=True,
                    text_score=score_threshold,
                )

            boxes = getattr(result, "boxes", None)
            texts = getattr(result, "txts", None)
            scores = getattr(result, "scores", None)
            if boxes is None or texts is None or scores is None:
                return []

            formatted_results: List[Dict[str, Any]] = []
            for box, text, score in zip(boxes, texts, scores):
                numeric_score = float(score)
                if numeric_score < score_threshold:
                    continue
                raw_box = box.tolist() if hasattr(box, "tolist") else list(box)
                converted_box = [
                    [float(coordinate) for coordinate in point]
                    for point in raw_box
                ]
                formatted_results.append(
                    {
                        "text": str(text),
                        "confidence": numeric_score,
                        "bbox": converted_box,
                    }
                )

            self._last_success_time = time.time()
            self._error_count = 0
            return formatted_results
        except Exception as exc:
            self._error_count += 1
            logger.error("RapidOCR 识别失败: %s", exc, exc_info=True)
            if self._error_count >= 3:
                logger.warning("RapidOCR 连续识别失败，释放引擎并等待下次请求重建")
                self.shutdown(deep_cleanup=True)
            return []

    def cleanup(self) -> None:
        self.shutdown(deep_cleanup=True)

    def shutdown(self, deep_cleanup: bool = False) -> None:
        self._service_active = False
        if deep_cleanup:
            with self._init_lock:
                self._engine = None
                self._error_count = 0
                gc.collect()
                logger.info("RapidOCR 模型资源已释放")

    def get_service_info(self) -> Dict[str, Any]:
        return {
            "engine_type": "rapidocr_onnxruntime",
            "model_type": OCR_MODEL_NAME,
            "backend": "DirectML" if self._use_directml else "CPU",
            "cpu_threads": self._cpu_threads,
            "angle_classifier": self._use_angle_classifier,
            "service_active": self._service_active,
            "error_count": self._error_count,
            "last_success_time": self._last_success_time,
            "model_dir": str(self._model_dir),
            "init_error": self._init_error,
        }


_rapidocr_service: Optional[RapidOCROCRService] = None
_rapidocr_service_lock = threading.Lock()


def get_rapidocr_service() -> RapidOCROCRService:
    global _rapidocr_service
    if _rapidocr_service is not None:
        return _rapidocr_service
    with _rapidocr_service_lock:
        if _rapidocr_service is None:
            _rapidocr_service = RapidOCROCRService()
    return _rapidocr_service


__all__ = ["RapidOCROCRService", "get_rapidocr_service"]
