"""Single source of truth for the packaged offline OCR runtime."""

from __future__ import annotations

from types import MappingProxyType
from typing import Final, Mapping

OCR_MODEL_NAME: Final = "PP-OCRv4 mobile"
OCR_MODEL_DIRECTORY: Final = "models/rapidocr"

OCR_MODEL_FILES: Final[Mapping[str, tuple[str, str]]] = MappingProxyType({
    "det": (
        "ch_PP-OCRv4_det_mobile.onnx",
        "d2a7720d45a54257208b1e13e36a8479894cb74155a5efe29462512d42f49da9",
    ),
    "cls": (
        "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
        "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c",
    ),
    "rec": (
        "ch_PP-OCRv4_rec_mobile.onnx",
        "48fc40f24f6d2a207a2b1091d3437eb3cc3eb6b676dc3ef9c37384005483683b",
    ),
})

OCR_REQUIRED_REQUIREMENTS: Final[Mapping[str, str]] = MappingProxyType({
    "rapidocr": "3.9.2",
    "onnxruntime-directml": "1.23.0",
})

OCR_REQUIRED_RUNTIME_DLLS: Final = (
    "DirectML.dll",
    "onnxruntime.dll",
    "onnxruntime_providers_shared.dll",
)

__all__ = [
    "OCR_MODEL_DIRECTORY",
    "OCR_MODEL_FILES",
    "OCR_MODEL_NAME",
    "OCR_REQUIRED_REQUIREMENTS",
    "OCR_REQUIRED_RUNTIME_DLLS",
]
