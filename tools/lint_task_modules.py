#!/usr/bin/env python
"""Static contract checks for task modules without importing heavy runtimes."""

from __future__ import annotations

import ast
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TASKS_ROOT = PROJECT_ROOT / "tasks"
LEGACY_UI_IMPORT_ALLOWLIST = {
    "image_match_probe.py",
    "keyboard_input.py",
    "mouse_action_task.py",
    "yolo_detection.py",
}


def lint_task_file(path: Path) -> list[str]:
    errors: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if (
                    path.name not in LEGACY_UI_IMPORT_ALLOWLIST
                    and (alias.name == "ui" or alias.name.startswith("ui."))
                ):
                    errors.append(f"{path.name}:{node.lineno}: task module imports UI")
                if (
                    path.name not in LEGACY_UI_IMPORT_ALLOWLIST
                    and (alias.name == "PySide6" or alias.name.startswith("PySide6."))
                ):
                    errors.append(f"{path.name}:{node.lineno}: task module imports PySide6")
        elif isinstance(node, ast.ImportFrom):
            module = str(node.module or "")
            if (
                path.name not in LEGACY_UI_IMPORT_ALLOWLIST
                and (module == "ui" or module.startswith("ui."))
            ):
                errors.append(f"{path.name}:{node.lineno}: task module imports UI")
            if (
                path.name not in LEGACY_UI_IMPORT_ALLOWLIST
                and (module == "PySide6" or module.startswith("PySide6."))
            ):
                errors.append(f"{path.name}:{node.lineno}: task module imports PySide6")
    return errors


def main() -> int:
    errors: list[str] = []
    for path in sorted(TASKS_ROOT.glob("*.py")):
        errors.extend(lint_task_file(path))
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        return 1
    print("task module contracts verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
