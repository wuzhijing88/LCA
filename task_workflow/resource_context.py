# -*- coding: utf-8 -*-
"""当前工作流的分类资源目录（按执行线程隔离）。"""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Iterator, Mapping, Optional

_IMAGES_DIR: ContextVar[str] = ContextVar("lca_workflow_images_dir", default="")
_SOUNDS_DIR: ContextVar[str] = ContextVar("lca_workflow_sounds_dir", default="")
_DICTS_DIR: ContextVar[str] = ContextVar("lca_workflow_dicts_dir", default="")
_YOLO_DIR: ContextVar[str] = ContextVar("lca_workflow_yolo_dir", default="")
_REPLAYS_DIR: ContextVar[str] = ContextVar("lca_workflow_replays_dir", default="")
_PLUGINS_DIR: ContextVar[str] = ContextVar("lca_workflow_plugins_dir", default="")

RESOURCE_DIR_KEYS = (
    "images_dir",
    "sounds_dir",
    "dicts_dir",
    "yolo_dir",
    "replays_dir",
    "plugins_dir",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def bind_workflow_resource_dirs(
    images_dir: str = "",
    sounds_dir: str = "",
    dicts_dir: str = "",
    yolo_dir: str = "",
    replays_dir: str = "",
    plugins_dir: str = "",
) -> None:
    _IMAGES_DIR.set(_text(images_dir))
    _SOUNDS_DIR.set(_text(sounds_dir))
    _DICTS_DIR.set(_text(dicts_dir))
    _YOLO_DIR.set(_text(yolo_dir))
    _REPLAYS_DIR.set(_text(replays_dir))
    _PLUGINS_DIR.set(_text(plugins_dir))


def bind_resource_dirs(dirs: Optional[Mapping[str, Any]] = None, **kwargs: Any) -> None:
    payload: Dict[str, Any] = dict(dirs or {})
    payload.update(kwargs)
    bind_workflow_resource_dirs(
        images_dir=_text(payload.get("images_dir")),
        sounds_dir=_text(payload.get("sounds_dir")),
        dicts_dir=_text(payload.get("dicts_dir")),
        yolo_dir=_text(payload.get("yolo_dir")),
        replays_dir=_text(payload.get("replays_dir")),
        plugins_dir=_text(payload.get("plugins_dir")),
    )
    _register_resolver_search_dirs(payload)


def _register_resolver_search_dirs(payload: Mapping[str, Any]) -> None:
    from utils.image_paths import get_image_path_resolver

    resolver = get_image_path_resolver()
    for key in ("images_dir", "dicts_dir"):
        path = _text(payload.get(key))
        if path and os.path.isdir(path):
            resolver.add_search_path(path, priority=0)


def bound_images_dir() -> str:
    return _text(_IMAGES_DIR.get())


def bound_sounds_dir() -> str:
    return _text(_SOUNDS_DIR.get())


def bound_dicts_dir() -> str:
    return _text(_DICTS_DIR.get())


def bound_yolo_dir() -> str:
    return _text(_YOLO_DIR.get())


def bound_replays_dir() -> str:
    return _text(_REPLAYS_DIR.get())


def bound_plugins_dir() -> str:
    return _text(_PLUGINS_DIR.get())


def current_images_dir() -> str:
    bound = bound_images_dir()
    if bound:
        return bound
    from utils.app_paths import get_images_dir

    return get_images_dir("LCA")


def current_sounds_dir() -> str:
    bound = bound_sounds_dir()
    if bound:
        return bound
    from utils.app_paths import get_sounds_dir

    return get_sounds_dir("LCA")


def current_dicts_dir() -> str:
    bound = bound_dicts_dir()
    if bound:
        return bound
    from utils.app_paths import get_dicts_dir

    return get_dicts_dir("LCA")


def current_yolo_dir() -> str:
    bound = bound_yolo_dir()
    if bound:
        return bound
    from utils.app_paths import get_app_root

    return os.path.join(get_app_root(), "yolo")


def current_replays_dir() -> str:
    bound = bound_replays_dir()
    if bound:
        return bound
    from utils.app_paths import get_app_root

    return os.path.join(get_app_root(), "replays")


def current_plugins_dir() -> str:
    bound = bound_plugins_dir()
    if bound:
        return bound
    from utils.app_paths import get_plugin_dir

    return get_plugin_dir()


def current_resource_dirs() -> Dict[str, str]:
    return {
        "images_dir": current_images_dir(),
        "sounds_dir": current_sounds_dir(),
        "dicts_dir": current_dicts_dir(),
        "yolo_dir": current_yolo_dir(),
        "replays_dir": current_replays_dir(),
        "plugins_dir": current_plugins_dir(),
    }


def resource_dirs_from_mapping(source: Any = None) -> Dict[str, str]:
    if isinstance(source, Mapping):
        return {key: _text(source.get(key)) for key in RESOURCE_DIR_KEYS}
    if source is None:
        return {key: "" for key in RESOURCE_DIR_KEYS}
    return {key: _text(getattr(source, key, "")) for key in RESOURCE_DIR_KEYS}


@contextmanager
def workflow_resource_scope(
    images_dir: str = "",
    sounds_dir: str = "",
    dicts_dir: str = "",
    yolo_dir: str = "",
    replays_dir: str = "",
    plugins_dir: str = "",
) -> Iterator[None]:
    tokens = (
        _IMAGES_DIR.set(_text(images_dir)),
        _SOUNDS_DIR.set(_text(sounds_dir)),
        _DICTS_DIR.set(_text(dicts_dir)),
        _YOLO_DIR.set(_text(yolo_dir)),
        _REPLAYS_DIR.set(_text(replays_dir)),
        _PLUGINS_DIR.set(_text(plugins_dir)),
    )
    try:
        yield
    finally:
        _IMAGES_DIR.reset(tokens[0])
        _SOUNDS_DIR.reset(tokens[1])
        _DICTS_DIR.reset(tokens[2])
        _YOLO_DIR.reset(tokens[3])
        _REPLAYS_DIR.reset(tokens[4])
        _PLUGINS_DIR.reset(tokens[5])
