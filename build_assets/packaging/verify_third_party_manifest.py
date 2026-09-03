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
        errors.append("unsupported third-party manifest schema")
    for component in payload.get("components", []):
        name = str(component.get("name") or "unknown")
        relative_path = str(component.get("path") or "")
        source = PROJECT_ROOT / relative_path
        expected = str(component.get("sha256") or "").lower()
        if not source.is_file():
            if require_all:
                errors.append(f"missing component: {name}: {relative_path}")
            continue
        if not expected:
            errors.append(f"missing sha256: {name}")
            continue
        actual = _sha256(source)
        if actual != expected:
            errors.append(f"sha256 mismatch: {name}: {actual} != {expected}")
        if not str(component.get("license") or "").strip():
            errors.append(f"missing license: {name}")
        if not str(component.get("source_url") or "").strip():
            errors.append(f"missing source_url: {name}")
    errors.extend(_verify_python_dependencies(payload))
    return errors


def _verify_python_dependencies(payload: dict) -> list[str]:
    """清单里的 Python 依赖必须和当前 venv 的传递闭包一致。

    Nuitka 会把闭包里的每个包编进 dist；清单少列一个，SBOM 就少一个组件。
    多列一个说明 venv 里已经卸掉了，同样要报。
    """
    from build_assets.packaging.generate_third_party_manifest import (
        collect_runtime_distribution_closure,
        excluded_from_bundle,
    )
    import re

    def _norm(name: str) -> str:
        return re.sub(r"[-_.]+", "-", str(name or "")).strip().lower()

    errors: list[str] = []
    listed = {
        _norm(item.get("name")): item
        for item in payload.get("python_dependencies", [])
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
                f"python dependency missing from manifest: {info['name']}=={info['version']} "
                f"(required_by={info['required_by'] or 'direct'}); 运行 generate_third_party_manifest.py 重新生成"
            )
            continue
        if str(item.get("version") or "") != str(info["version"]):
            errors.append(
                f"python dependency version drift: {info['name']} manifest={item.get('version')} installed={info['version']}"
            )
        expected_bundled = not excluded_from_bundle(normalized)
        if bool(item.get("bundled", True)) != expected_bundled:
            errors.append(
                f"python dependency bundled flag stale: {info['name']} manifest={item.get('bundled')} build={expected_bundled}"
            )
    for normalized in sorted(set(listed) - set(closure)):
        errors.append(f"python dependency listed but not in runtime closure: {listed[normalized].get('name')}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--require-all", action="store_true")
    args = parser.parse_args()
    errors = verify(Path(args.manifest).resolve(), require_all=args.require_all)
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        return 1
    print("third-party manifest verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
