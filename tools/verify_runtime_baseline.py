#!/usr/bin/env python
"""Fast, deterministic checks required before runtime or packaging work."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app_core.app_config import APP_EDITION
from app_core.ocr_runtime_contract import OCR_REQUIRED_REQUIREMENTS


def _load_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        if "==" not in line:
            raise ValueError(f"dependency must be exactly pinned: {line}")
        name, version = line.split("==", 1)
        pins[name.strip().lower()] = version.strip()
    return pins


def verify() -> dict[str, object]:
    errors: list[str] = []
    if APP_EDITION != "离线版":
        errors.append(f"unexpected application edition: {APP_EDITION!r}")

    runtime_requirements = PROJECT_ROOT / "requirements-runtime.txt"
    pins = _load_pins(runtime_requirements)
    for name, expected in OCR_REQUIRED_REQUIREMENTS.items():
        if pins.get(name) != expected:
            errors.append(f"OCR dependency mismatch: {name}={pins.get(name)!r}, expected {expected!r}")

    required_paths = (
        PROJECT_ROOT / "pyproject.toml",
        PROJECT_ROOT / "tests",
        PROJECT_ROOT / "docs" / "testing.md",
        PROJECT_ROOT / "docs" / "architecture.md",
        PROJECT_ROOT / "docs" / "task_authoring.md",
        PROJECT_ROOT / "build_assets" / "third_party" / "manifest.json",
        PROJECT_ROOT / ".github" / "workflows" / "quality.yml",
    )
    for path in required_paths:
        if not path.exists():
            errors.append(f"missing baseline path: {path.relative_to(PROJECT_ROOT)}")

    generic_core_paths = (
        PROJECT_ROOT / "task_workflow" / "executor.py",
        PROJECT_ROOT / "utils" / "wgc_hwnd_capture.py",
    )
    forbidden_target_names = ("二重螺旋",)
    for path in generic_core_paths:
        source = path.read_text(encoding="utf-8-sig")
        for target_name in forbidden_target_names:
            if target_name in source:
                errors.append(f"target-specific name in generic core: {path.name}: {target_name}")

    return {
        "ok": not errors,
        "edition": "offline",
        "runtime_dependency_count": len(pins),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = verify()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["ok"]:
        print(
            f"runtime baseline verified: edition={result['edition']} "
            f"dependencies={result['runtime_dependency_count']}"
        )
    else:
        for error in result["errors"]:
            print(f"ERROR: {error}", file=sys.stderr)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
