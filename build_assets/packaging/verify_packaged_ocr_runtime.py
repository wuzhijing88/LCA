#!/usr/bin/env python3
"""Verify that the release contains one complete, offline PP-OCRv4 runtime."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.ocr_runtime_contract import (
    OCR_MODEL_DIRECTORY,
    OCR_MODEL_FILES,
    OCR_REQUIRED_RUNTIME_DLLS,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_packaged_ocr_runtime(dist_root: Path) -> list[str]:
    errors: list[str] = []
    model_dir = dist_root / OCR_MODEL_DIRECTORY
    expected_names = {filename for filename, _expected_hash in OCR_MODEL_FILES.values()}
    actual_names = (
        {path.name for path in model_dir.glob("*.onnx") if path.is_file()}
        if model_dir.is_dir()
        else set()
    )
    if actual_names != expected_names:
        errors.append(
            "OCR model set mismatch: "
            f"missing={sorted(expected_names - actual_names)}, "
            f"unexpected={sorted(actual_names - expected_names)}"
        )

    for filename, expected_hash in OCR_MODEL_FILES.values():
        model_path = model_dir / filename
        if not model_path.is_file():
            continue
        if _sha256(model_path).lower() != expected_hash.lower():
            errors.append(f"OCR model hash mismatch: {model_path.relative_to(dist_root)}")

    for filename in OCR_REQUIRED_RUNTIME_DLLS:
        if not (dist_root / filename).is_file():
            errors.append(f"Missing OCR runtime DLL: {filename}")

    expected_model_paths = {
        (model_dir / filename).resolve(strict=False)
        for filename in expected_names
    }
    for onnx_path in dist_root.rglob("*.onnx"):
        if onnx_path.resolve(strict=False) not in expected_model_paths:
            errors.append(f"Unexpected packaged ONNX model: {onnx_path.relative_to(dist_root)}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify packaged offline OCR runtime")
    parser.add_argument("--dist", required=True)
    args = parser.parse_args()

    dist_root = Path(args.dist).resolve(strict=False)
    if not dist_root.is_dir():
        print(f"ERROR: packaged dist directory not found: {dist_root}", file=sys.stderr)
        return 2

    errors = verify_packaged_ocr_runtime(dist_root)
    if errors:
        print("ERROR: packaged OCR runtime verification failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(
        "OK: packaged PP-OCRv4 runtime verified "
        f"({len(OCR_MODEL_FILES)} models, {len(OCR_REQUIRED_RUNTIME_DLLS)} runtime DLLs)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
