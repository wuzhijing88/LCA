#!/usr/bin/env python
"""Generate a reproducible inventory for bundled third-party components."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "build_assets" / "third_party" / "manifest.json"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

COMPONENTS = (
    {
        "name": "AutoHotkey",
        "version": "2.x",
        "path": "AutoHotkey/AutoHotkey64.exe",
        "license": "GPL-2.0-only",
        "source_url": "https://www.autohotkey.com/",
    },
    {
        "name": "Interception",
        "version": "1.x",
        "path": "Interception/library/x64/interception.dll",
        "license": "LGPL-3.0-only",
        "source_url": "https://github.com/oblitum/Interception",
    },
    {
        "name": "Interception-x86",
        "version": "1.x",
        "path": "Interception/library/x86/interception.dll",
        "license": "LGPL-3.0-only",
        "source_url": "https://github.com/oblitum/Interception",
    },
    {
        "name": "IbInputSimulator",
        "version": "local-pinned",
        "path": "tools/ibinputsimulator/Binding.AHK2/IbInputSimulator.dll",
        "license": "LicenseRef-Upstream",
        "source_url": "https://github.com/Chaoses-Ib/IbInputSimulator",
    },
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_dist_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", str(name or "")).strip().lower()


def read_direct_runtime_requirements() -> dict[str, str]:
    """requirements-runtime.txt 里显式钉死的直接依赖：规范化名 -> 版本。"""
    pinned: dict[str, str] = {}
    requirements = PROJECT_ROOT / "requirements-runtime.txt"
    for raw_line in requirements.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        name, version = line.split("==", 1)
        pinned[_normalize_dist_name(name)] = version.strip()
    return pinned


def collect_runtime_distribution_closure() -> dict[str, dict[str, object]]:
    """从直接依赖出发，按当前 venv 的元数据展开完整传递闭包。

    Nuitka 会把闭包里每一个包都编进 dist，SBOM 必须如实列出，
    否则清单声称的组件比实际发行的少。返回 规范化名 -> {name, version, direct, required_by}。
    """
    from importlib import metadata
    from packaging.markers import Marker
    from packaging.requirements import Requirement

    direct = read_direct_runtime_requirements()
    closure: dict[str, dict[str, object]] = {}
    queue: list[tuple[str, str | None]] = [(name, None) for name in direct]

    while queue:
        normalized, parent = queue.pop(0)
        if normalized in closure:
            if parent and parent not in closure[normalized]["required_by"]:
                closure[normalized]["required_by"].append(parent)
            continue
        try:
            dist = metadata.distribution(normalized)
        except metadata.PackageNotFoundError:
            # 直接依赖缺失是环境错误，由 verify 报；传递依赖缺失说明 marker 不匹配，跳过
            if normalized in direct:
                raise RuntimeError(f"运行依赖未安装: {normalized}")
            continue
        display_name = str(dist.metadata.get("Name") or normalized)
        closure[normalized] = {
            "name": display_name,
            "version": str(dist.version),
            "direct": normalized in direct,
            "required_by": [parent] if parent else [],
        }
        for spec in dist.requires or []:
            req = Requirement(spec)
            if req.marker is not None:
                # 只跟进无 extra 的默认依赖；extra 依赖不会被 pip 默认安装
                try:
                    if not req.marker.evaluate({"extra": ""}):
                        continue
                except Exception:
                    continue
            queue.append((_normalize_dist_name(req.name), normalized))

    return closure


# pip 发行包名 -> Nuitka 看到的顶层 import 名。只列不一致的。
_DIST_TO_IMPORT_NAMES = {
    "antlr4-python3-runtime": ("antlr4",),
    "charset-normalizer": ("charset_normalizer",),
    "opencv-python": ("cv2",),
    "onnxruntime-directml": ("onnxruntime",),
    "pillow": ("PIL",),
    "pyyaml": ("yaml",),
    "pyside6-essentials": ("PySide6",),
    "pyautogui": ("pyautogui",),
    "mouseinfo": ("mouseinfo",),
    "protobuf": ("google.protobuf",),
    "pywin32": ("win32api", "win32gui", "win32con", "pywintypes"),
    "typing-extensions": ("typing_extensions",),
    "winrt-runtime": ("winrt",),
}


def _import_names(normalized_dist_name: str) -> tuple[str, ...]:
    if normalized_dist_name in _DIST_TO_IMPORT_NAMES:
        return _DIST_TO_IMPORT_NAMES[normalized_dist_name]
    if normalized_dist_name.startswith("winrt-"):
        return ("winrt",)
    return (normalized_dist_name.replace("-", "_"),)


def excluded_from_bundle(normalized_dist_name: str) -> bool:
    """按 Nuitka 的 --nofollow-import-to 判断该发行包是否整体被排除在 dist 之外。"""
    from build_assets.packaging.run_nuitka_main_build import NOFOLLOW_IMPORTS

    blocked = {item.lower() for item in NOFOLLOW_IMPORTS}
    return all(name.lower() in blocked for name in _import_names(normalized_dist_name))


def _python_dependencies() -> list[dict[str, object]]:
    closure = collect_runtime_distribution_closure()
    dependencies = []
    for normalized in sorted(closure, key=lambda key: (not closure[key]["direct"], key)):
        item = closure[normalized]
        entry: dict[str, object] = {
            "name": item["name"],
            "version": item["version"],
            "direct": bool(item["direct"]),
            "bundled": not excluded_from_bundle(normalized),
        }
        if not item["direct"]:
            entry["required_by"] = sorted(str(x) for x in item["required_by"])
        dependencies.append(entry)
    return dependencies


def build_manifest() -> dict[str, object]:
    components = []
    for component in COMPONENTS:
        source = PROJECT_ROOT / component["path"]
        components.append(
            {
                **component,
                "present": source.is_file(),
                "sha256": _sha256(source) if source.is_file() else "",
            }
        )
    return {
        "schema_version": 1,
        "components": components,
        "python_dependencies": _python_dependencies(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(build_manifest(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"third_party_manifest={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
