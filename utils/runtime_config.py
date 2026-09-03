"""进程内读取主配置的统一入口。

utils 层不导入 app_core：由 app_core.config_store 在导入时注册“规范化后的配置”提供者。
任何要读配置的进程（主进程、工作流子进程、插件宿主自检）都必须先导入 app_core.config_store；
没有提供者时直接报错，不再退回直读 JSON 文件——直读会绕过校验，让旧值悄悄流入运行时。
"""

from __future__ import annotations

from typing import Callable, Mapping, Optional

ConfigProvider = Callable[[], Mapping]
_provider: Optional[ConfigProvider] = None


def set_runtime_config_provider(provider: Optional[ConfigProvider]) -> None:
    """注册返回当前主配置（Mapping）的回调；传 None 取消注册。"""
    global _provider
    _provider = provider if callable(provider) else None


def get_runtime_config() -> dict:
    """返回当前主配置的副本。未注册提供者或提供者失败时抛出 RuntimeError。"""
    provider = _provider
    if provider is None:
        raise RuntimeError(
            "运行时配置提供者未注册：请先 import app_core.config_store"
        )
    data = provider()
    if not isinstance(data, Mapping):
        raise RuntimeError(f"运行时配置提供者返回了非映射类型: {type(data).__name__}")
    return dict(data)
