#!/usr/bin/env python
"""Verify third-party component hashes before packaging."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = PROJECT_ROOT / "build_assets" / "third_party" / "manifest.json"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(manifest_path: Path, *, require_all: bool) -> list[str]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if payload.get("schema_version") != 1:
        errors.append("不支持的第三方清单格式版本")
    for component in payload["components"]:
        name = str(component.get("name") or "未知组件")
        relative_path = str(component.get("path") or "")
        source = PROJECT_ROOT / relative_path
        expected = str(component.get("sha256") or "").lower()
        if not source.is_file():
            if require_all:
                errors.append(f"缺少第三方组件: {name}: {relative_path}")
            continue
        if not expected:
            errors.append(f"第三方组件缺少 SHA256: {name}")
            continue
        actual = _sha256(source)
        if actual != expected:
            errors.append(f"第三方组件 SHA256 不一致: {name}: {actual} != {expected}")
        if not str(component.get("license") or "").strip():
            errors.append(f"第三方组件缺少许可证信息: {name}")
        if not str(component.get("source_url") or "").strip():
            errors.append(f"第三方组件缺少来源地址: {name}")
    errors.extend(_verify_python_dependencies(payload))
    return errors


def _verify_python_dependencies(payload: dict) -> list[str]:
    """清单里的 Python 依赖必须和当前 venv 的传递闭包一致。

    Nuitka 会把闭包里的每个包编进 dist；清单少列一个，SBOM 就少一个组件。
    多列一个说明 venv 里已经卸掉了，同样要报。
    """
    import re

    from build_assets.packaging.generate_third_party_manifest import (
        collect_runtime_distribution_closure,
        excluded_from_bundle,
    )

    def _norm(name: str) -> str:
        return re.sub(r"[-_.]+", "-", str(name or "")).strip().lower()

    errors: list[str] = []
    listed = {
        _norm(item.get("name")): item
        for item in payload["python_dependencies"]
        if isinstance(item, dict)
    }
    try:
        closure = collect_runtime_distribution_closure()
    except RuntimeError as exc:
        return [str(exc)]

    for normalized, info in sorted(closure.items()):
        item = listed.get(normalized)
        if item is None:
            errors.append(
                f"第三方清单缺少 Python 依赖: {info['name']}=={info['version']} "
                f"(required_by={info['required_by'] or 'direct'}); 运行 generate_third_party_manifest.py 重新生成"
            )
            continue
        if str(item.get("version") or "") != str(info["version"]):
            errors.append(
                f"Python 依赖版本不一致: {info['name']} 清单={item.get('version')} 已安装={info['version']}"
            )
        expected_bundled = not excluded_from_bundle(normalized)
        if not isinstance(item.get("bundled"), bool):
            errors.append(f"Python 依赖的 bundled 字段必须为布尔值: {info['name']}")
        elif item["bundled"] != expected_bundled:
            errors.append(
                f"Python 依赖的 bundled 标记已过期: {info['name']} 清单={item['bundled']} 构建={expected_bundled}"
            )
    for normalized in sorted(set(listed) - set(closure)):
        errors.append(f"第三方清单包含不属于运行时依赖的 Python 包: {listed[normalized].get('name')}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--require-all", action="store_true")
    args = parser.parse_args()
    errors = verify(Path(args.manifest).resolve(), require_all=args.require_all)
    for error in errors:
        print(f"错误: {error}", file=sys.stderr)
    if errors:
        return 1
    print("第三方依赖清单校验通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
