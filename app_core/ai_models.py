"""按当前服务配置读取模型列表；不猜测模型、不降级或重试其他接口。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from app_core.ai_assistant import (
    AIProviderConfig,
    _ai_request_headers,
    _format_ai_http_error,
    normalize_ai_base_url,
)
from app_core.ai_stream import AICancellation, request_http

MAX_MODEL_RESPONSE_BYTES = 1024 * 1024
MAX_MODEL_COUNT = 10000


def fetch_ai_models(config: AIProviderConfig, *, cancel: AICancellation) -> list[str]:
    """仅接受 /models 的 data 数组与 id 字段，返回去重后的原始模型标识。"""
    cancel.check()
    if not config.base_url.strip():
        raise ValueError("请先填写 AI 服务地址")
    if not config.api_key.strip():
        raise ValueError("请先填写 API Key，再获取模型")
    if type(config.timeout) is not int or config.timeout <= 0:
        raise ValueError("获取模型的超时必须为正整数秒")
    headers = _ai_request_headers(config.api_key)
    headers["Accept"] = "application/json"
    request = urllib.request.Request(
        f"{normalize_ai_base_url(config.base_url)}/models", headers=headers, method="GET",
    )
    data = bytearray()
    try:
        request_http(request, timeout=config.timeout, cancel=cancel, consume=data.extend,
                     max_bytes=MAX_MODEL_RESPONSE_BYTES)
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read(2000).decode("utf-8", errors="replace")
        finally:
            exc.close()
        raise RuntimeError(_format_ai_http_error(exc.code, detail)) from exc
    cancel.check()
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("模型列表不是有效的 UTF-8 JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("模型列表格式错误：服务必须返回 data 数组")
    entries = payload["data"]
    if not entries:
        raise ValueError("服务未返回可用模型，请检查 API Key 的模型权限")
    if len(entries) > MAX_MODEL_COUNT:
        raise ValueError(f"模型数量超过上限（{MAX_MODEL_COUNT} 个）")
    models = {}
    for entry in entries:
        cancel.check()
        if not isinstance(entry, dict):
            raise ValueError("模型列表格式错误：每项必须是包含 id 的对象")
        identifier = entry.get("id")
        if not isinstance(identifier, str) or not identifier.strip() or identifier != identifier.strip():
            raise ValueError("模型列表格式错误：模型 id 必须是非空且无首尾空格的文本")
        models[identifier] = None
    return list(models)
