from pathlib import Path

from app_core.ocr_runtime_contract import (
    OCR_MODEL_DIRECTORY,
    OCR_MODEL_FILES,
    OCR_REQUIRED_RUNTIME_DLLS,
)
from build_assets.packaging.run_nuitka_main_build import (
    INCLUDE_MODULES,
    _build_command,
    _validate_ocr_build_inputs,
)
from build_assets.packaging.verify_packaged_ocr_runtime import (
    verify_packaged_ocr_runtime,
)
from build_assets.packaging.verify_packaged_subprocess_workers import (
    _validate_ocr_inference_response,
    _verify_build_modules,
)
from services.rapidocr_ocr_service import _MODEL_FILES


def test_source_ocr_contract_is_ready_for_packaging():
    project_root = Path(__file__).resolve().parents[1]

    _validate_ocr_build_inputs(project_root)
    assert _MODEL_FILES == OCR_MODEL_FILES
    assert "services.rapidocr_ocr_service" in INCLUDE_MODULES
    assert not any(
        option.startswith("--noinclude-data-files=rapidocr/models/")
        for option in _build_command("build")
    )


def test_packaged_ocr_verifier_accepts_exact_contract(tmp_path, monkeypatch):
    model_dir = tmp_path / OCR_MODEL_DIRECTORY
    model_dir.mkdir(parents=True)
    expected_hashes = {}
    for filename, expected_hash in OCR_MODEL_FILES.values():
        (model_dir / filename).write_bytes(b"model")
        expected_hashes[filename] = expected_hash
    for filename in OCR_REQUIRED_RUNTIME_DLLS:
        (tmp_path / filename).write_bytes(b"dll")

    monkeypatch.setattr(
        "build_assets.packaging.verify_packaged_ocr_runtime._sha256",
        lambda path: expected_hashes[path.name],
    )

    assert verify_packaged_ocr_runtime(tmp_path) == []


def test_packaged_ocr_verifier_rejects_extra_models(tmp_path, monkeypatch):
    model_dir = tmp_path / OCR_MODEL_DIRECTORY
    model_dir.mkdir(parents=True)
    expected_hashes = {}
    for filename, expected_hash in OCR_MODEL_FILES.values():
        (model_dir / filename).write_bytes(b"model")
        expected_hashes[filename] = expected_hash
    (model_dir / "unexpected_model.onnx").write_bytes(b"wrong-model")
    for filename in OCR_REQUIRED_RUNTIME_DLLS:
        (tmp_path / filename).write_bytes(b"dll")

    monkeypatch.setattr(
        "build_assets.packaging.verify_packaged_ocr_runtime._sha256",
        lambda path: expected_hashes.get(path.name, "wrong"),
    )

    errors = verify_packaged_ocr_runtime(tmp_path)
    assert any("unexpected" in error.lower() for error in errors)


def test_packaged_ocr_smoke_requires_real_inference_result():
    request_id = "ocr-smoke"
    window_hwnd = 1234
    response = {
        "request_id": request_id,
        "window_hwnd": window_hwnd,
        "success": True,
        "results": [{"text": "OCR", "confidence": 0.99, "bbox": []}],
    }

    assert _validate_ocr_inference_response(response, request_id, window_hwnd) == (True, "")
    response["results"] = []
    ok, reason = _validate_ocr_inference_response(response, request_id, window_hwnd)
    assert not ok
    assert reason.startswith("ocr_inference_empty")


def test_packaged_module_verifier_requires_rapidocr_service(tmp_path):
    ok, missing = _verify_build_modules(tmp_path)

    assert not ok
    assert "module.services.rapidocr_ocr_service.c" in missing
