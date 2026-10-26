"""卡片跨工程粘贴时，按明确来源迁移图片；失败撤销本次新建文件。"""

from __future__ import annotations

import copy
import json
import shutil
from contextlib import contextmanager
from pathlib import Path

from task_workflow.workspace import _resource_param_kind


def _image_root(value: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("工作流图片目录未设置，无法粘贴图片卡片")
    root = Path(value)
    if not root.is_absolute():
        raise ValueError(f"工作流图片目录必须是绝对路径：{value}")
    return root.resolve()


def _same_file_content(source: Path, destination: Path) -> bool:
    if source.stat().st_size != destination.stat().st_size:
        return False
    with source.open("rb") as left, destination.open("rb") as right:
        while True:
            chunk = left.read(128 * 1024)
            if chunk != right.read(128 * 1024):
                return False
            if not chunk:
                return True


@contextmanager
def pasted_image_resources(cards: list[dict], *, source_images_dir: str, images_dir: str):
    """返回独立卡片数据，迁移图片后交给画布；不持有来源画布或工程会话。"""
    copied = copy.deepcopy(cards)
    source_root = None
    target_root = None

    sources: dict[Path, str] = {}
    planned: dict[Path, Path] = {}

    def rewrite_path(raw: str) -> str:
        nonlocal source_root, target_root
        if not raw.strip() or "{{" in raw:
            return raw
        if source_root is None:
            source_root = _image_root(source_images_dir)
            target_root = _image_root(images_dir)
        if source_root == target_root:
            return raw
        text = raw.strip().replace("\\", "/")
        if text.startswith("memory://"):
            raise ValueError(f"来源图片未落盘，无法跨工作流粘贴：{raw}")
        source = Path(text)
        if not source.is_absolute():
            for prefix in ("assets/images/", "images/"):
                if text.lower().startswith(prefix):
                    text = text[len(prefix):]
                    break
            source = (source_root / text).resolve()
            if not source.is_relative_to(source_root):
                raise ValueError(f"图片相对路径超出来源图片目录：{raw}")
        else:
            source = source.resolve()
        if not source.is_file():
            raise FileNotFoundError(f"来源图片不存在：{raw}\n来源路径：{source}")
        if source in sources:
            return sources[source]
        relative = source.relative_to(source_root) if source.is_relative_to(source_root) else Path(source.name)
        candidate = target_root / relative
        index = 2
        while True:
            destination = candidate.resolve()
            if not destination.is_relative_to(target_root):
                raise ValueError(f"目标图片路径超出目标图片目录：{candidate}")
            if destination in planned:
                matches = _same_file_content(source, planned[destination])
            elif destination.exists():
                matches = destination.is_file() and _same_file_content(source, destination)
            else:
                planned[destination] = source
                break
            if matches:
                break
            candidate = target_root / relative.with_name(f"{relative.stem}_{index}{relative.suffix}")
            index += 1
        logical = "images/" + destination.relative_to(target_root).as_posix()
        sources[source] = logical
        return logical

    def rewrite_value(value):
        if value is None:
            return None
        if isinstance(value, str):
            return "\n".join(rewrite_path(line) for line in value.split("\n"))
        if isinstance(value, list):
            return [rewrite_value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(rewrite_value(item) for item in value)
        raise TypeError("卡片图片参数必须是文本或文本列表")

    for card in copied:
        parameters = card["parameters"]
        if not isinstance(parameters, dict):
            raise TypeError("剪贴板卡片参数必须是字典")
        for key, value in parameters.items():
            if _resource_param_kind(key) in {"image", "images_multi"}:
                parameters[key] = rewrite_value(value)

        if card['task_type'] == "脚本卡片":
            from app_core.card_plugins import bundle_from_parameters, input_parameter_key

            definitions = bundle_from_parameters(parameters).manifest['parameters']
            for name, definition in definitions.items():
                if definition['type'] == 'file' and definition['resource_kind'] == 'image':
                    key = input_parameter_key(name)
                    parameters[key] = rewrite_value(parameters[key])
        elif card['task_type'] == "自定义脚本" and parameters.get('script_source'):
            from task_workflow.script_resources import extract_string_literals, resource_kind
            from tasks.script_task import script_source_hash

            source = parameters['script_source']
            if not isinstance(source, str):
                raise TypeError("自定义脚本源码必须是文本")
            rewritten = source
            for raw, start, end in reversed(extract_string_literals(source)):
                if resource_kind(raw) != 'image':
                    continue
                replacement = rewrite_path(raw)
                if replacement != raw:
                    rewritten = rewritten[:start] + json.dumps(replacement, ensure_ascii=False) + rewritten[end:]
            if rewritten != source:
                expected = parameters.get('script_source_sha256')
                if expected and expected != script_source_hash(source):
                    raise ValueError("自定义脚本源码校验失败，无法改写粘贴图片路径")
                parameters['script_source'] = rewritten
                if expected:
                    parameters['script_source_sha256'] = script_source_hash(rewritten)

    created_files: list[Path] = []
    created_dirs: list[Path] = []

    def ensure_directory(directory: Path) -> None:
        if directory.is_dir():
            return
        ensure_directory(directory.parent)
        directory.mkdir()
        created_dirs.append(directory)

    try:
        for destination, source in planned.items():
            ensure_directory(destination.parent)
            with source.open("rb") as reader, destination.open("xb") as writer:
                created_files.append(destination)
                shutil.copyfileobj(reader, writer, length=128 * 1024)
        yield copied
    except BaseException:
        for path in reversed(created_files):
            path.unlink()
        for directory in reversed(created_dirs):
            directory.rmdir()
        raise
