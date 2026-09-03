# -*- coding: utf-8 -*-
"""导出包内容指纹：防改 workflows / assets 后仍用原 manifest 运行。"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Mapping


INTEGRITY_MANIFEST_KEY = "content_sha256"


def _normalize_name(name: str) -> str:
    return str(name or "").replace("\\", "/").lstrip("/")


def package_content_files(files: Mapping[str, bytes]) -> Dict[str, bytes]:
    """只保留包内原始路径，去掉 load_files_into_memory 注入的运行时别名。

    别名包括 ``images/...`` 以及图片/UI 资源的 basename 索引；若参与哈希会误报篡改。
    """
    normalized: Dict[str, bytes] = {
        _normalize_name(name): (data if isinstance(data, (bytes, bytearray)) else bytes(data))
        for name, data in files.items()
        if _normalize_name(name)
    }
    basename_aliases: set[str] = set()
    for name in normalized:
        if name.startswith("assets/images/") or name.startswith("ui_assets/"):
            base = name.rsplit("/", 1)[-1]
            if base:
                basename_aliases.add(base)
    kept: Dict[str, bytes] = {}
    for name, data in normalized.items():
        if name.startswith("images/"):
            continue
        if "/" not in name and name not in {"manifest.json", "ui.json", "icon.ico"} and name in basename_aliases:
            continue
        kept[name] = data
    return kept


def compute_content_sha256(files: Mapping[str, bytes]) -> str:
    """对除 manifest.json 外的包内文件做稳定摘要（忽略运行时别名）。"""
    digest = hashlib.sha256()
    items = sorted(package_content_files(files).items(), key=lambda item: item[0])
    for name, data in items:
        if name == "manifest.json":
            continue
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(data)
        digest.update(b"\0")
    return digest.hexdigest()


def stamp_package_files(files: Mapping[str, bytes]) -> Dict[str, bytes]:
    """写入 manifest.content_sha256，返回新的文件字典。"""
    out = package_content_files(files)
    raw_manifest = out.get("manifest.json")
    if raw_manifest is None:
        raise ValueError("缺少 manifest.json，无法写入完整性摘要")
    try:
        manifest: Dict[str, Any] = json.loads(raw_manifest.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("manifest.json 不是合法 JSON") from exc
    if not isinstance(manifest, dict):
        raise ValueError("manifest.json 必须是对象")
    digest = compute_content_sha256(out)
    manifest[INTEGRITY_MANIFEST_KEY] = digest
    out["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    return out


def verify_package_files(files: Mapping[str, bytes], *, require: bool = False) -> None:
    """校验内存中的包文件；旧包无摘要时默认跳过。"""
    normalized = package_content_files(files)
    raw_manifest = normalized.get("manifest.json")
    if raw_manifest is None:
        if require:
            raise ValueError("程序包缺少 manifest.json")
        return
    try:
        manifest = json.loads(raw_manifest.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("manifest.json 损坏") from exc
    if not isinstance(manifest, dict):
        raise ValueError("manifest.json 损坏")
    expected = str(manifest.get(INTEGRITY_MANIFEST_KEY) or "").strip().lower()
    if not expected:
        if require:
            raise ValueError("程序包缺少完整性摘要，请重新导出")
        return
    actual = compute_content_sha256(normalized)
    if actual != expected:
        raise ValueError("程序包内容已被篡改或损坏")


def verify_player_memory_package(*, require: bool = False) -> None:
    from app_core.player.memory_store import list_player_memory_files

    verify_package_files(list_player_memory_files(), require=require)
