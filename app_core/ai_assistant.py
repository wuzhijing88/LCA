"""AI assistant chat helpers.

The UI talks to any OpenAI-compatible chat-completions endpoint. Capability
facts come from searching the public source repository, not a bundled dump.
"""

from __future__ import annotations

import base64
import http.client
import io
import json
import os
import socket
import time
import hashlib
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
import inspect
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


DEFAULT_BASE_URL = "https://lcaa.xyz/v1"
DEFAULT_MODEL = "gpt-5.5"
MAX_PROMPT_CHARS = 12000
MAX_AI_IMAGES_PER_TURN = 4
MAX_AI_WORKFLOW_FILES_PER_TURN = 2
MAX_WORKFLOW_AI_IMAGES = 12
MAX_AI_IMAGE_BYTES = 8 * 1024 * 1024
MAX_AI_WORKFLOW_FILE_BYTES = 8 * 1024 * 1024
MAX_RESOURCE_TEXT_CHARS = 8000
IMAGE_ONLY_PROMPT = "请识别图片。"
FILE_ONLY_PROMPT = "请检查这份上传的工作流是否格式正确。格式有误就进行修复。"
WORKFLOW_IMAGES_PROMPT = "下面是当前工作流引用的图片，顺序与「工作流资源」中的附图编号一致。"
_RESOURCE_KIND_LABELS = {
    "image": "图片",
    "dict": "字库",
    "model": "模型",
    "audio": "声音",
    "replay": "回放",
    "component": "组件",
}
_WORKFLOW_IMAGE_CONVERT_EXTS = {".bmp", ".tif", ".tiff"}
AI_IMAGE_MIMES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
AI_IMAGE_MIME_SET = frozenset(AI_IMAGE_MIMES.values())
AI_WORKFLOW_EXTS = frozenset({".json", ".lca"})
MAX_WORKFLOW_CONTEXT_CHARS = 32000
MAX_PARAM_VALUE_CHARS = 6000
CAPABILITY_DOC_NAME = "WORKFLOW_AND_SCRIPTS.md"
_SKIP_PARAM_TYPES = {"separator", "hidden", "button"}
_LINE_TYPE_LABELS = {
    "sequential": "顺序",
    "success": "成功",
    "failure": "失败",
    "random": "随机",
}
AI_REQUEST_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = (0.4, 1.2)
_RETRYABLE_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}
_RETRYABLE_TEXT = (
    "remote end closed",
    "connection reset",
    "connection aborted",
    "broken pipe",
    "timed out",
    "temporarily unavailable",
    "eof occurred",
)
_CACHE_LOCK = threading.RLock()
_RESPONSE_CACHE: Dict[str, tuple[float, str]] = {}
AI_CACHE_TTL_SECONDS = 900
AI_CACHE_MAX_ENTRIES = 64
AI_CACHE_SCHEMA_VERSION = "4"
_CACHE_HITS = 0
_CACHE_MISSES = 0
AI_TOOL_ROUNDS = 20
STOP_SEARCH_PROMPT = "不要再调用工具。根据已经查阅的开源仓库源码给出审查结论。"
SEARCH_LIMIT_REPLY = "已停止继续搜索开源仓库。下面是本次查阅过程，请据此继续提问。"
AI_REPO_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_repo",
            "description": "在 LCA 开源仓库中搜索文件路径或源码。审查卡片、参数、端口和脚本命令时必须先搜索。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索词，例如卡片名、参数名、命令名或文件名",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_repo_file",
            "description": "读取开源仓库中的一个源码或文档文件。路径相对于仓库根目录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "仓库内路径，例如 tasks/delay_task.py",
                    }
                },
                "required": ["path"],
            },
        },
    },
]
_CHAT_SYSTEM_PROMPT = (
    "你是 LCA 的 AI 助手。"
    "卡片参数、端口、脚本命令和现行格式以开源仓库的现行源码为准，不要使用过时说明或记忆。"
    "卡片、参数和脚本命令以本机缓存的开源仓库源码为准。"
    "search_repo 和 read_repo_file 只读本机缓存，不会每次对话都重新下载仓库。"
    "需要核对现行实现时再调用它们；同一轮对话里已经查过的内容不要再搜。"
    "寒暄或与卡片、脚本无关的问题不要搜仓库。"
    "仓库里没有的能力就是没有，直接失败或标成未知。不要编造已删除的卡片名、参数名、命令或旧别名。"
    "若附有「当前正在编辑的工作流」，那是用户当前画布上的现行内容，包含未保存修改；"
    "回答当前流程、当前卡片或当前脚本的问题时必须以这份快照为准，并用仓库源码核对参数和命令。"
    "用户消息可能附带图片；请直接根据图片内容回答。"
    "用户消息可能附带 .json 或 .lca 工作流文件，会作为「用户上传的工作流」给出；"
    "检查或修复上传文件时以这份快照为准，不要和当前画布搞混。"
    "当前工作流引用的文件会作为「工作流资源」给出，其中已读取的文本是文件原文；"
    "已附图的图片与用户消息前的工作流附图编号一致。"
    "用户要求审查或修正时，按缓存的开源仓库源码检查结构、连线、卡片参数和自定义脚本，先用中文说明问题和改法。"
    "上传的工作流格式有误时，按「用户上传的工作流」给出修正；点应用后写入当前正在编辑的工作流。"
    "需要改画布时，必须输出一个语言标记为 工作流 的代码块，内容是只含 ops 数组的 JSON；"
    "未改动的卡片不要写进 ops。不要编造已删除的卡片名、参数名、命令或旧别名。"
    "禁止把卡片输出连到自己；循环必须经过另一张有输入口的卡片再连回来。"
    "用户点击「应用」后才会写入当前正在编辑的工作流；未点击前画布不变。"
    "用户点击「下载」会把修正后的工作流存成 .lca 文件，不改磁盘上的原文件，也不写入画布。"
)
REVIEW_WORKFLOW_PROMPT = (
    "请审查当前正在编辑的工作流。"
    "用本机缓存的开源仓库源码核对现行卡片、参数和脚本，指出结构、连线、卡片参数和自定义脚本中的问题，并说明原因。"
    "若可以修正，先用中文说明改了什么，再给出一个完整的 ```工作流 JSON 代码块供我点应用或下载。"
    "没有问题时明确说没有发现问题，不要输出工作流代码块。"
)
_WORKFLOW_CONTEXT_HEADER = "## 当前正在编辑的工作流"
_UPLOADED_WORKFLOW_HEADER = "## 用户上传的工作流"
_UPLOADED_KIND_LABELS = {
    "current": "现行 LCA 工程",
    "json": "JSON 工作流",
    "legacy_lca1": "旧版加密工程",
    "plain_zip": "旧版明文工程",
}
_UNSUPPORTED_WORKFLOW_FILE = "只支持上传 .json 或 .lca 工作流文件"


def _cache_key(config: AIProviderConfig, messages: Iterable[Mapping[str, Any]]) -> str:
    payload = {
        "schema": AI_CACHE_SCHEMA_VERSION,
        "endpoint": config.endpoint(),
        "model": str(config.model or DEFAULT_MODEL),
        "tools": [str(item["function"]["name"]) for item in AI_REPO_TOOLS],
        "messages": [_api_chat_message(item) for item in messages],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def clear_ai_response_cache() -> None:
    global _CACHE_HITS, _CACHE_MISSES
    with _CACHE_LOCK:
        _RESPONSE_CACHE.clear()
        _CACHE_HITS = 0
        _CACHE_MISSES = 0


def ai_response_cache_stats() -> Dict[str, int]:
    """Return cache size for diagnostics without exposing cached content."""
    now = time.time()
    with _CACHE_LOCK:
        expired = [key for key, (stamp, _) in _RESPONSE_CACHE.items()
                   if now - stamp >= AI_CACHE_TTL_SECONDS]
        for key in expired:
            _RESPONSE_CACHE.pop(key, None)
        return {"entries": len(_RESPONSE_CACHE), "max_entries": AI_CACHE_MAX_ENTRIES,
                "hits": _CACHE_HITS, "misses": _CACHE_MISSES}


def load_ai_provider_settings() -> Dict[str, Any]:
    """Load API connection settings from this instance's local store."""
    values = {
        "base_url": DEFAULT_BASE_URL,
        "model": DEFAULT_MODEL,
        "api_key": "",
        "timeout": 90,
    }
    try:
        from utils.instance_runtime import create_app_settings

        settings = create_app_settings()
        saved_base_url = str(settings.value("ai/base_url", "") or "").strip()
        values["base_url"] = normalize_ai_base_url(saved_base_url or DEFAULT_BASE_URL)
        saved_model = str(settings.value("ai/model", "") or "").strip()
        values["model"] = saved_model or DEFAULT_MODEL
        values["api_key"] = str(settings.value("ai/api_key", ""))
        values["timeout"] = int(settings.value("ai/timeout", values["timeout"]))
    except Exception:
        pass
    return values


def normalize_ai_base_url(base_url: str) -> str:
    """Append /v1 when missing. Keep an existing /v1. Empty falls back to default."""
    base = str(base_url or "").strip()
    if not base:
        return DEFAULT_BASE_URL
    base = base.rstrip("/")
    completions = "/chat/completions"
    if base.endswith(completions):
        base = base[: -len(completions)].rstrip("/")
    if not base.lower().endswith("/v1"):
        base = f"{base}/v1"
    return base


def save_ai_provider_settings(
    *,
    base_url: str,
    model: str,
    api_key: str,
    timeout: int,
) -> None:
    from utils.instance_runtime import create_app_settings

    settings = create_app_settings()
    settings.setValue("ai/base_url", normalize_ai_base_url(base_url))
    settings.setValue("ai/model", str(model or "").strip())
    settings.setValue("ai/api_key", str(api_key or ""))
    settings.setValue("ai/timeout", int(timeout or 90))


@dataclass(frozen=True)
class AIProviderConfig:
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    api_key: str = ""
    timeout: int = 90

    def endpoint(self) -> str:
        return f"{normalize_ai_base_url(self.base_url)}/chat/completions"


def _format_ai_http_error(status_code: int, detail: str) -> str:
    text = str(detail or "").strip()
    if status_code == 403 and "1010" in text:
        return (
            "AI 服务返回 HTTP 403（Cloudflare 1010）：请求被网站的浏览器完整性检查拦截了，"
            "还没到达模型接口。请确认网关已放行桌面客户端，或在 Cloudflare 里对 /v1 关闭 Browser Integrity Check。"
        )
    if text:
        return f"AI 服务返回 HTTP {status_code}: {text}"
    return f"AI 服务返回 HTTP {status_code}"


def model_supports_temperature(model: str) -> bool:
    """Newer chat/reasoning models often reject a custom temperature."""
    name = str(model or "").strip().lower()
    return not name.startswith(("gpt-5", "o1", "o3", "o4"))


def attachable_image_mime(path: str = "", *, mime: str = "") -> str:
    """Return a vision-API mime type, or raise if the file/type is not allowed."""
    text = str(mime or "").strip().lower()
    if text == "image/jpg":
        text = "image/jpeg"
    if text:
        if text not in AI_IMAGE_MIME_SET:
            raise ValueError("不支持的图片格式。请使用 PNG、JPG、WEBP 或 GIF。")
        return text
    ext = os.path.splitext(str(path or ""))[1].lower()
    mapped = AI_IMAGE_MIMES.get(ext)
    if not mapped:
        raise ValueError(f"不支持的图片格式：{ext or '未知'}。请使用 PNG、JPG、WEBP 或 GIF。")
    return mapped


def attachable_workflow_suffix(path: str = "") -> str:
    """Return .json or .lca, or raise if the file is not an allowed workflow upload."""
    ext = os.path.splitext(str(path or ""))[1].lower()
    if ext not in AI_WORKFLOW_EXTS:
        raise ValueError(_UNSUPPORTED_WORKFLOW_FILE)
    return ext


def _decode_uploaded_text(blob: bytes) -> str:
    return bytes(blob).decode("utf-8-sig")


def _uploaded_format_note(kind: str) -> str:
    label = _UPLOADED_KIND_LABELS.get(kind, kind or "未知")
    if kind == "current":
        return f"原始格式：{label}。"
    return f"原始格式：{label}。已在内存中转成现行格式，未改磁盘上的原文件。"


def _unwrap_uploaded_workflow(payload: Mapping[str, Any]) -> Dict[str, Any]:
    from task_workflow.workflow_payload import workflow_body

    body = workflow_body(payload)
    if not isinstance(body.get("cards"), list) or not isinstance(body.get("connections"), list):
        raise ValueError("工作流缺少卡片列表或连线列表")
    return body


def inspect_uploaded_workflow_bytes(blob: bytes, *, name: str) -> Dict[str, Any]:
    """Inspect an uploaded .json/.lca in memory. Does not write or convert the original file."""
    filename = str(name or "").strip() or "未命名"
    ext = attachable_workflow_suffix(filename)
    data = bytes(blob or b"")
    result: Dict[str, Any] = {
        "status": "error",
        "name": filename,
        "filepath": filename,
        "size": len(data),
        "kind": "",
        "error": "",
        "raw_text": "",
        "workflow": None,
    }
    if not data:
        result["error"] = "工作流文件是空的"
        return result
    if len(data) > MAX_AI_WORKFLOW_FILE_BYTES:
        result["error"] = (
            f"工作流文件太大，单个不能超过 {MAX_AI_WORKFLOW_FILE_BYTES // (1024 * 1024)} MB"
        )
        return result

    from app_core.lca_format.container import LcaFormatError
    from app_core.lca_format.legacy_convert import convert_project_bytes, inspect_project_bytes
    from app_core.lca_format.project_io import workflow_from_embedded_bytes

    try:
        kind = inspect_project_bytes(data)
    except LcaFormatError as exc:
        result["error"] = str(exc) or "不是有效的工作流文件"
        if ext == ".json":
            try:
                result["raw_text"] = _truncate_context_text(
                    _decode_uploaded_text(data),
                    MAX_RESOURCE_TEXT_CHARS,
                )
            except UnicodeDecodeError:
                result["raw_text"] = ""
        return result
    result["kind"] = kind
    try:
        converted = convert_project_bytes(data, display_name=os.path.splitext(filename)[0])
        workflow = _unwrap_uploaded_workflow(workflow_from_embedded_bytes(converted))
    except LcaFormatError as exc:
        result["error"] = str(exc) or "无法转换成现行工作流"
        if ext == ".json":
            try:
                result["raw_text"] = _truncate_context_text(
                    _decode_uploaded_text(data),
                    MAX_RESOURCE_TEXT_CHARS,
                )
            except UnicodeDecodeError:
                result["raw_text"] = ""
        return result
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        result["error"] = str(exc) or "无法读取工作流内容"
        if ext == ".json":
            try:
                result["raw_text"] = _truncate_context_text(
                    _decode_uploaded_text(data),
                    MAX_RESOURCE_TEXT_CHARS,
                )
            except UnicodeDecodeError:
                result["raw_text"] = ""
        return result
    result["status"] = "ok"
    result["workflow"] = workflow
    result["format_note"] = _uploaded_format_note(kind)
    return result


def inspect_uploaded_workflow_file(path: str, *, display_name: str = "") -> Dict[str, Any]:
    filename = str(display_name or "").strip() or os.path.basename(str(path or ""))
    attachable_workflow_suffix(filename or str(path or ""))
    if not path or not os.path.isfile(path):
        return {
            "status": "error",
            "name": filename or "未命名",
            "filepath": filename or "未命名",
            "size": 0,
            "kind": "",
            "error": "找不到上传的工作流文件",
            "raw_text": "",
            "workflow": None,
        }
    size = os.path.getsize(path)
    if size <= 0:
        return {
            "status": "error",
            "name": filename,
            "filepath": filename,
            "size": 0,
            "kind": "",
            "error": "工作流文件是空的",
            "raw_text": "",
            "workflow": None,
        }
    if size > MAX_AI_WORKFLOW_FILE_BYTES:
        return {
            "status": "error",
            "name": filename,
            "filepath": filename,
            "size": size,
            "kind": "",
            "error": (
                f"工作流文件太大，单个不能超过 {MAX_AI_WORKFLOW_FILE_BYTES // (1024 * 1024)} MB"
            ),
            "raw_text": "",
            "workflow": None,
        }
    try:
        with open(path, "rb") as handle:
            blob = handle.read()
    except OSError:
        return {
            "status": "error",
            "name": filename,
            "filepath": filename,
            "size": 0,
            "kind": "",
            "error": "找不到上传的工作流文件",
            "raw_text": "",
            "workflow": None,
        }
    return inspect_uploaded_workflow_bytes(blob, name=filename)


def format_uploaded_workflows_context(files: Optional[Sequence[Mapping[str, Any]]] = None) -> str:
    """Text snapshot of user-uploaded .json/.lca files for the chat system prompt."""
    items = list(files or [])
    if not items:
        return ""
    if len(items) > MAX_AI_WORKFLOW_FILES_PER_TURN:
        raise ValueError(f"一次最多上传 {MAX_AI_WORKFLOW_FILES_PER_TURN} 个工作流文件")
    blocks = [_UPLOADED_WORKFLOW_HEADER]
    for item in items:
        path = str(item.get("path") or "").strip()
        name = str(item.get("name") or "").strip() or os.path.basename(path) or "未命名"
        snapshot = inspect_uploaded_workflow_file(path, display_name=name)
        size = int(snapshot.get("size") or 0)
        size_text = _format_file_size(size) if size > 0 else ""
        heading = f"### {snapshot.get('name') or name}"
        if size_text:
            heading += f"（{size_text}）"
        blocks.append("")
        blocks.append(heading)
        if snapshot.get("status") != "ok":
            error = str(snapshot.get("error") or "未知错误").strip() or "未知错误"
            blocks.append(f"格式：无效。{error}")
            raw_text = str(snapshot.get("raw_text") or "")
            if raw_text:
                blocks.append("原文：")
                blocks.append("```json")
                blocks.append(raw_text.rstrip("\n"))
                blocks.append("```")
            continue
        note = str(snapshot.get("format_note") or "").strip()
        if note:
            blocks.append(note)
        blocks.append(
            format_editor_workflow_context(
                {
                    "status": "ok",
                    "name": snapshot.get("name") or name,
                    "filepath": snapshot.get("filepath") or name,
                    "workflow": snapshot.get("workflow"),
                },
                resources=[],
                header="",
            )
        )
    text = "\n".join(part for part in blocks if part is not None)
    if len(text) <= MAX_WORKFLOW_CONTEXT_CHARS:
        return text
    return _truncate_context_text(text, MAX_WORKFLOW_CONTEXT_CHARS)


def uploaded_workflow_for_apply(files: Optional[Sequence[Mapping[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """Return the first uploaded workflow as an ops source. Missing file fails."""
    items = list(files or [])
    if not items:
        return None
    path = str(items[0].get("path") or "").strip()
    name = str(items[0].get("name") or "").strip() or os.path.basename(path) or "未命名"
    if not path or not os.path.isfile(path):
        raise FileNotFoundError("找不到上传的工作流文件")
    snapshot = inspect_uploaded_workflow_file(path, display_name=name)
    if snapshot.get("status") == "ok" and isinstance(snapshot.get("workflow"), dict):
        return dict(snapshot["workflow"])
    return {"cards": [], "connections": []}


def proposal_source_workflow(
    main_window: Any = None,
    files: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Tuple[Dict[str, Any], str]:
    """Source dict for applying or downloading a 工作流 ops block."""
    items = list(files or [])
    if items:
        source = uploaded_workflow_for_apply(items)
        name = str(items[0].get("name") or "").strip() or os.path.basename(
            str(items[0].get("path") or "")
        ) or "工作流"
        stem = os.path.splitext(name)[0].strip() or "工作流"
        if source is None:
            raise RuntimeError("找不到上传的工作流文件")
        return source, stem
    snapshot = collect_editor_workflow_snapshot(main_window)
    if snapshot.get("status") == "empty":
        raise RuntimeError("当前没有打开的工作流")
    if snapshot.get("status") == "error":
        error = str(snapshot.get("error") or "未知错误").strip() or "未知错误"
        raise RuntimeError(f"无法读取当前工作流：{error}")
    workflow = snapshot.get("workflow")
    if not isinstance(workflow, dict):
        raise RuntimeError("当前工作流数据不是字典")
    name = str(snapshot.get("name") or "").strip() or "工作流"
    return dict(workflow), name


def editor_task_types(main_window: Any = None) -> List[str]:
    view, _task = _current_editor_view(main_window)
    modules = getattr(view, "task_modules", None) if view is not None else None
    if isinstance(modules, dict) and modules:
        return [str(name).strip() for name in modules.keys() if str(name).strip()]
    from tasks import PRIMARY_TASK_MODULES

    return [str(name).strip() for name in PRIMARY_TASK_MODULES.keys() if str(name).strip()]


def encode_ai_image_file(path: str) -> str:
    mime = attachable_image_mime(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"找不到图片文件：{path}")
    size = os.path.getsize(path)
    if size <= 0:
        raise ValueError("图片文件是空的")
    if size > MAX_AI_IMAGE_BYTES:
        raise ValueError(f"图片太大，单张不能超过 {MAX_AI_IMAGE_BYTES // (1024 * 1024)} MB")
    with open(path, "rb") as handle:
        raw = handle.read()
    return f"data:{mime};base64,{base64.standard_b64encode(raw).decode('ascii')}"


def encode_image_for_chat(path: str) -> str:
    """Encode a workflow or chat image. Convert BMP/TIFF to PNG for the vision API."""
    ext = os.path.splitext(str(path or ""))[1].lower()
    if ext in AI_IMAGE_MIMES:
        return encode_ai_image_file(path)
    if ext not in _WORKFLOW_IMAGE_CONVERT_EXTS:
        raise ValueError(f"不支持的图片格式：{ext or '未知'}。请使用 PNG、JPG、WEBP、GIF、BMP 或 TIF。")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"找不到图片文件：{path}")
    size = os.path.getsize(path)
    if size <= 0:
        raise ValueError("图片文件是空的")
    if size > MAX_AI_IMAGE_BYTES:
        raise ValueError(f"图片太大，单张不能超过 {MAX_AI_IMAGE_BYTES // (1024 * 1024)} MB")
    from PIL import Image

    with Image.open(path) as image:
        image.load()
        converted = image.convert("RGBA") if image.mode in {"RGBA", "LA", "P"} else image.convert("RGB")
        buffer = io.BytesIO()
        converted.save(buffer, format="PNG")
        raw = buffer.getvalue()
    if not raw:
        raise ValueError("图片文件是空的")
    if len(raw) > MAX_AI_IMAGE_BYTES:
        raise ValueError(f"图片太大，单张不能超过 {MAX_AI_IMAGE_BYTES // (1024 * 1024)} MB")
    return f"data:image/png;base64,{base64.standard_b64encode(raw).decode('ascii')}"


def build_user_message_content(
    text: str,
    images: Optional[Sequence[Mapping[str, Any]]] = None,
    *,
    max_images: int = MAX_AI_IMAGES_PER_TURN,
) -> Any:
    body = str(text or "")[:MAX_PROMPT_CHARS]
    files = list(images or [])
    if not files:
        return body
    limit = max(1, int(max_images))
    if len(files) > limit:
        raise ValueError(f"一次最多发送 {limit} 张图片")
    parts: List[Dict[str, Any]] = [
        {"type": "text", "text": body.strip() or IMAGE_ONLY_PROMPT},
    ]
    for item in files:
        url = str(item.get("data_url") or "").strip()
        if not url:
            url = encode_image_for_chat(str(item.get("path") or ""))
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": url},
            }
        )
    return parts


def _api_chat_message(item: Mapping[str, Any]) -> Dict[str, Any]:
    role = str(item.get("role") or "user")
    if role == "tool":
        return {
            "role": "tool",
            "tool_call_id": str(item.get("tool_call_id") or ""),
            "content": str(item.get("content") or ""),
        }
    message: Dict[str, Any] = {"role": role}
    tool_calls = item.get("tool_calls")
    content = item.get("content")
    if tool_calls:
        message["tool_calls"] = list(tool_calls)
        if content in (None, ""):
            message["content"] = None
        elif isinstance(content, list):
            message["content"] = content
        else:
            message["content"] = str(content)
        return message
    if isinstance(content, list):
        message["content"] = content
        return message
    message["content"] = str(content or "")
    return message


def build_chat_payload(
    config: AIProviderConfig,
    messages: Iterable[Mapping[str, Any]],
    *,
    include_temperature: Optional[bool] = None,
    tools: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    model = str(config.model or DEFAULT_MODEL).strip()
    payload: Dict[str, Any] = {
        "model": model,
        "messages": [_api_chat_message(item) for item in messages],
    }
    if include_temperature if include_temperature is not None else model_supports_temperature(model):
        payload["temperature"] = 0.2
    if tools:
        payload["tools"] = list(tools)
    return payload


def _ai_request_headers(api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {str(api_key).strip()}",
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "identity",
        "Connection": "close",
        "User-Agent": "LCA-Desktop/1.0",
    }


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.URLError):
        return str(getattr(exc, "reason", "") or exc)
    return str(exc)


def is_retryable_ai_error(exc: BaseException) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return int(getattr(exc, "code", 0) or 0) in _RETRYABLE_HTTP_STATUS
    if isinstance(
        exc,
        (
            http.client.RemoteDisconnected,
            http.client.IncompleteRead,
            http.client.BadStatusLine,
            ConnectionResetError,
            ConnectionAbortedError,
            BrokenPipeError,
            TimeoutError,
            socket.timeout,
        ),
    ):
        return True
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, BaseException) and is_retryable_ai_error(reason):
            return True
    text = _error_text(exc).lower()
    return any(token in text for token in _RETRYABLE_TEXT)


def _temperature_rejected(status_code: int, detail: str) -> bool:
    if int(status_code) not in {400, 422}:
        return False
    text = str(detail or "").lower()
    return "temperature" in text


def format_ai_transport_error(exc: BaseException) -> str:
    text = _error_text(exc)
    lowered = text.lower()
    if any(token in lowered for token in ("remote end closed", "connection reset", "broken pipe", "eof occurred")):
        return (
            "AI 服务在返回结果前断开了连接。多半是网关瞬时断开或请求较大，"
            "请再试一次；若反复出现，可把超时调大，或换一个可用的模型和地址。"
        )
    if any(token in lowered for token in ("timed out", "timeout")):
        return "等待 AI 服务超时。请把超时调大后再试，或检查网络和接口地址。"
    if text:
        return f"无法连接 AI 服务: {text}"
    return "无法连接 AI 服务"


def _read_http_error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")[:500]
    except Exception:
        return ""


def _post_chat_request(
    request: urllib.request.Request,
    timeout: int,
    opener: Callable[..., Any],
) -> str:
    with opener(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def _parse_chat_completion(raw: str) -> str:
    parsed = _parse_chat_message(raw)
    if parsed["tool_calls"]:
        raise RuntimeError("AI 服务响应包含未处理的工具调用")
    return parsed["content"]


def _text_from_parts(parts: Any, *, kinds: Sequence[str]) -> str:
    chunks: List[str] = []
    if not isinstance(parts, list):
        return ""
    allowed = {str(item) for item in kinds}
    for part in parts:
        if not isinstance(part, dict):
            continue
        kind = str(part.get("type") or "text").strip() or "text"
        if kind not in allowed:
            continue
        piece = str(part.get("text") or part.get("content") or part.get("thinking") or "")
        if piece.strip():
            chunks.append(piece)
    return "\n".join(chunks).strip()


def _message_reasoning(message: Mapping[str, Any]) -> str:
    for key in ("reasoning_content", "reasoning"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            text = str(value.get("text") or value.get("content") or "").strip()
            if text:
                return text
        if isinstance(value, list):
            text = _text_from_parts(value, kinds=("text", "output_text", "reasoning", "thinking"))
            if text:
                return text
    content = message.get("content")
    return _text_from_parts(content, kinds=("reasoning", "thinking"))


def _parse_chat_message(raw: str) -> Dict[str, Any]:
    try:
        data = json.loads(raw)
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("AI 服务响应不是有效的 chat-completions 格式") from exc
    if not isinstance(message, dict):
        raise RuntimeError("AI 服务响应不是有效的 chat-completions 格式")
    content = message.get("content")
    if isinstance(content, list):
        text = _text_from_parts(content, kinds=("text", "output_text"))
    else:
        text = str(content or "").strip()
    reasoning = _message_reasoning(message)
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list):
        tool_calls = []
    tool_calls = [item for item in tool_calls if isinstance(item, dict)]
    if not text and not tool_calls:
        raise RuntimeError("AI 返回了空内容")
    return {"content": text, "reasoning": reasoning, "tool_calls": tool_calls}


def _tool_arguments(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and str(raw).strip():
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("工具参数不是有效 JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("工具参数必须是 JSON 对象")
        return payload
    raise ValueError("工具参数无效")


_TOOL_RESULT_LOCK = threading.RLock()
_TOOL_RESULTS: Dict[str, str] = {}
_TOOL_RESULT_MAX = 64


def _tool_result_key(name: str, payload: Mapping[str, Any]) -> str:
    from app_core.ai_repo import cached_snapshot_id

    return json.dumps(
        {"sha": cached_snapshot_id(), "name": name, "args": dict(payload)},
        ensure_ascii=False,
        sort_keys=True,
    )


def execute_ai_tool(name: str, arguments: Any) -> str:
    payload = _tool_arguments(arguments)
    cache_key = _tool_result_key(name, payload)
    with _TOOL_RESULT_LOCK:
        cached = _TOOL_RESULTS.get(cache_key)
        if cached is not None:
            return cached
    if name == "search_repo":
        keyword = str(payload.get("query") or "").strip()
        if not keyword:
            raise ValueError("缺少参数：query")
        from app_core.ai_repo import search_source_repository

        result = search_source_repository(keyword)
    elif name == "read_repo_file":
        path = str(payload.get("path") or "").strip()
        if not path:
            raise ValueError("缺少参数：path")
        from app_core.ai_repo import read_source_repository_file

        result = read_source_repository_file(path)
    else:
        raise ValueError(f"未知工具：{name}")
    with _TOOL_RESULT_LOCK:
        _TOOL_RESULTS[cache_key] = result
        while len(_TOOL_RESULTS) > _TOOL_RESULT_MAX:
            _TOOL_RESULTS.pop(next(iter(_TOOL_RESULTS)))
    return result


def _run_tool_call(call: Mapping[str, Any]) -> str:
    function = call.get("function") if isinstance(call.get("function"), Mapping) else call
    name = str((function or {}).get("name") or "").strip()
    arguments = (function or {}).get("arguments")
    try:
        return execute_ai_tool(name, arguments)
    except Exception as exc:
        return str(exc)


def describe_tool_call(call: Mapping[str, Any]) -> str:
    function = call.get("function") if isinstance(call.get("function"), Mapping) else call
    name = str((function or {}).get("name") or "").strip()
    try:
        payload = _tool_arguments((function or {}).get("arguments"))
    except Exception:
        payload = {}
    if name == "search_repo":
        query = str(payload.get("query") or "").strip()
        return f"搜索开源仓库：{query}" if query else "搜索开源仓库"
    if name == "read_repo_file":
        path = str(payload.get("path") or "").strip()
        return f"读取仓库文件：{path}" if path else "读取仓库文件"
    return f"调用工具：{name or '未知'}"


def _post_chat_round(
    config: AIProviderConfig,
    messages: Sequence[Mapping[str, Any]],
    *,
    timeout: int,
    post: Callable[..., Any],
    include_temperature: bool,
    tools: Optional[Sequence[Mapping[str, Any]]] = AI_REPO_TOOLS,
) -> Tuple[Dict[str, Any], bool]:
    last_error: Optional[BaseException] = None
    temperature = include_temperature
    for attempt in range(AI_REQUEST_ATTEMPTS):
        payload = build_chat_payload(
            config,
            messages,
            include_temperature=temperature,
            tools=tools,
        )
        request = urllib.request.Request(
            config.endpoint(),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=_ai_request_headers(str(config.api_key)),
            method="POST",
        )
        try:
            parsed = _parse_chat_message(_post_chat_request(request, timeout, post))
            return parsed, temperature
        except urllib.error.HTTPError as exc:
            last_error = exc
            detail = _read_http_error_detail(exc)
            if temperature and _temperature_rejected(exc.code, detail):
                temperature = False
                continue
            if is_retryable_ai_error(exc) and attempt + 1 < AI_REQUEST_ATTEMPTS:
                time.sleep(_RETRY_BACKOFF_SECONDS[min(attempt, len(_RETRY_BACKOFF_SECONDS) - 1)])
                continue
            raise RuntimeError(_format_ai_http_error(exc.code, detail)) from exc
        except Exception as exc:
            last_error = exc
            if is_retryable_ai_error(exc) and attempt + 1 < AI_REQUEST_ATTEMPTS:
                time.sleep(_RETRY_BACKOFF_SECONDS[min(attempt, len(_RETRY_BACKOFF_SECONDS) - 1)])
                continue
            raise RuntimeError(format_ai_transport_error(exc)) from exc
    raise RuntimeError(format_ai_transport_error(last_error or RuntimeError("未知网络错误")))


def _apply_tool_calls(
    working: List[Mapping[str, Any]],
    parsed: Mapping[str, Any],
    *,
    progress: Optional[Callable[[str], None]],
    thinking: List[str],
) -> None:
    reasoning = str(parsed.get("reasoning") or "").strip()
    if reasoning:
        thinking.append(reasoning)
        if progress:
            progress(reasoning.splitlines()[0][:80])
    content = str(parsed.get("content") or "").strip()
    if content:
        thinking.append(content)
    assistant: Dict[str, Any] = {
        "role": "assistant",
        "content": parsed.get("content") or None,
        "tool_calls": list(parsed.get("tool_calls") or []),
    }
    working.append(assistant)
    for call in list(parsed.get("tool_calls") or []):
        call_id = str(call.get("id") or "").strip()
        if not call_id:
            raise RuntimeError("AI 工具调用缺少 id")
        line = describe_tool_call(call)
        thinking.append(line)
        if progress:
            progress(line)
        working.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "content": _run_tool_call(call),
            }
        )


def complete_ai_chat(
    config: AIProviderConfig,
    messages: Iterable[Mapping[str, Any]],
    *,
    opener: Optional[Callable[..., Any]] = None,
    use_cache: bool = True,
    progress: Optional[Callable[[str], None]] = None,
) -> Tuple[str, str]:
    """Call chat-completions, run repo tools, and return (answer, thinking)."""
    if not str(config.api_key or "").strip():
        raise ValueError("请先填写 API Key")
    message_list = list(messages)
    key = _cache_key(config, message_list) if (use_cache and opener is None) else ""
    if key:
        global _CACHE_HITS, _CACHE_MISSES
        with _CACHE_LOCK:
            cached = _RESPONSE_CACHE.get(key)
            if cached and time.time() - cached[0] < AI_CACHE_TTL_SECONDS:
                _CACHE_HITS += 1
                text = cached[1]
                thinking = cached[2] if len(cached) > 2 else ""
                return text, str(thinking or "")
            _CACHE_MISSES += 1
            _RESPONSE_CACHE.pop(key, None)
    timeout = max(5, int(config.timeout))
    post = opener or urllib.request.urlopen
    include_temperature = model_supports_temperature(str(config.model or DEFAULT_MODEL))
    if opener is None:
        from app_core.ai_repo import ensure_source_repository, repo_snapshot_ready

        if not repo_snapshot_ready() and progress:
            progress("正在下载开源仓库缓存…")
        ensure_source_repository()
    working: List[Mapping[str, Any]] = list(message_list)
    thinking: List[str] = []
    tool_rounds = 0
    while True:
        parsed, include_temperature = _post_chat_round(
            config,
            working,
            timeout=timeout,
            post=post,
            include_temperature=include_temperature,
            tools=AI_REPO_TOOLS,
        )
        tool_calls = parsed["tool_calls"]
        if not tool_calls:
            reasoning = str(parsed.get("reasoning") or "").strip()
            if reasoning:
                thinking.append(reasoning)
            result = parsed["content"]
            packed = "\n".join(item for item in thinking if item).strip()
            if key:
                with _CACHE_LOCK:
                    _RESPONSE_CACHE[key] = (time.time(), result, packed)
                    while len(_RESPONSE_CACHE) > AI_CACHE_MAX_ENTRIES:
                        _RESPONSE_CACHE.pop(next(iter(_RESPONSE_CACHE)))
            return result, packed
        _apply_tool_calls(working, parsed, progress=progress, thinking=thinking)
        tool_rounds += 1
        if tool_rounds < AI_TOOL_ROUNDS:
            continue
        if progress:
            progress("正在根据已查阅的源码给出结论…")
        working.append({"role": "user", "content": STOP_SEARCH_PROMPT})
        parsed, include_temperature = _post_chat_round(
            config,
            working,
            timeout=timeout,
            post=post,
            include_temperature=include_temperature,
            tools=None,
        )
        reasoning = str(parsed.get("reasoning") or "").strip()
        if reasoning:
            thinking.append(reasoning)
        result = str(parsed.get("content") or "").strip() or SEARCH_LIMIT_REPLY
        packed = "\n".join(item for item in thinking if item).strip()
        if key:
            with _CACHE_LOCK:
                _RESPONSE_CACHE[key] = (time.time(), result, packed)
                while len(_RESPONSE_CACHE) > AI_CACHE_MAX_ENTRIES:
                    _RESPONSE_CACHE.pop(next(iter(_RESPONSE_CACHE)))
        return result, packed


def chat_completion(
    config: AIProviderConfig,
    messages: Iterable[Mapping[str, Any]],
    *,
    opener: Optional[Callable[..., Any]] = None,
    use_cache: bool = True,
) -> str:
    """Call an OpenAI-compatible endpoint and return its text content."""
    text, _thinking = complete_ai_chat(
        config,
        messages,
        opener=opener,
        use_cache=use_cache,
    )
    return text


def resolve_capability_document_path() -> Optional[str]:
    """Locate the workflow/script capability markdown shipped with the app."""
    candidates = []
    try:
        from utils.app_paths import get_app_root

        candidates.append(os.path.join(get_app_root(), "docs", CAPABILITY_DOC_NAME))
    except Exception:
        pass
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates.append(os.path.join(project_root, "docs", CAPABILITY_DOC_NAME))
    seen = set()
    for path in candidates:
        normalized = os.path.normcase(os.path.abspath(path))
        if normalized in seen:
            continue
        seen.add(normalized)
        if os.path.isfile(path):
            return path
    return None


def load_capability_document() -> str:
    path = resolve_capability_document_path()
    if not path:
        raise FileNotFoundError("缺少产品说明文档 docs/WORKFLOW_AND_SCRIPTS.md")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read().strip()
    except OSError as exc:
        raise FileNotFoundError("无法读取产品说明文档 docs/WORKFLOW_AND_SCRIPTS.md") from exc
    if not text:
        raise RuntimeError("产品说明文档 docs/WORKFLOW_AND_SCRIPTS.md 为空")
    return text


def _format_condition_value(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return " 或 ".join(str(item) for item in value)
    return str(value)


def _compact_condition(condition: Any) -> str:
    if isinstance(condition, list):
        return " 且 ".join(part for part in (_compact_condition(item) for item in condition) if part)
    if not isinstance(condition, Mapping):
        return ""
    name = condition.get("param")
    if not name:
        return ""
    operator = str(condition.get("operator") or "=").strip() or "="
    value = condition.get("value")
    if operator == "in":
        text = f"{name} 为 {_format_condition_value(value)}"
    elif operator == "!=":
        text = f"{name}≠{value}"
    elif operator == "=":
        text = f"{name}={value}"
    else:
        text = f"{name}{operator}{value}"
    extra = condition.get("and")
    if extra:
        nested = _compact_condition(extra)
        if nested:
            text = f"{text} 且 {nested}"
    return text


def _collapse_capability_text(text: Any) -> str:
    return " ".join(str(text or "").split()).strip()


def _format_option_text(options: Any) -> str:
    if isinstance(options, Mapping):
        return " | ".join(str(item) for item in options.keys())
    if isinstance(options, list) and options:
        return " | ".join(str(item) for item in options)
    return ""


def _format_param_capability(name: str, spec: Mapping[str, Any]) -> str:
    label = str(spec.get("label") or name).strip()
    param_type = str(spec.get("type") or "text").strip()
    attrs = [param_type]
    if "default" in spec and spec.get("default") not in (None, ""):
        attrs.append(f"default={spec.get('default')}")
    for key in ("min", "max", "step", "decimals"):
        if key in spec and spec.get(key) not in (None, ""):
            attrs.append(f"{key}={spec.get(key)}")
    if spec.get("required"):
        attrs.append("必填")
    if spec.get("readonly"):
        attrs.append("只读")
    if spec.get("multiline"):
        attrs.append("多行")
    line = f"{name} ({', '.join(attrs)}): {label}"
    tooltip = _collapse_capability_text(spec.get("tooltip") or spec.get("description")).rstrip("。.")
    if tooltip and tooltip != label:
        line += f"。{tooltip}"
    placeholder = _collapse_capability_text(spec.get("placeholder"))
    if placeholder:
        line += f"；占位 {placeholder}"
    file_filter = _collapse_capability_text(spec.get("file_filter") or spec.get("file_types"))
    if file_filter:
        line += f"；文件 {file_filter}"
    option_text = _format_option_text(spec.get("options", spec.get("choices")))
    if option_text:
        line += f"；选项 {option_text}"
    condition = spec.get("condition", spec.get("conditions"))
    compact = _compact_condition(condition)
    if compact:
        line += f"；当 {compact}"
    return line


def format_card_capability_catalog(task_modules: Optional[Mapping[str, Any]] = None) -> str:
    """Compact live parameter schema for every registered card type."""
    modules = task_modules
    if modules is None:
        from tasks import PRIMARY_TASK_MODULES

        modules = PRIMARY_TASK_MODULES
    lines = ["## 当前卡片参数（运行时）"]
    for task_type in modules:
        module = modules[task_type]
        getter = getattr(module, "get_params_definition", None)
        lines.append(f"### {task_type}")
        if callable(getattr(module, "check_monitor_trigger", None)):
            lines.append("- 监控节点：工作流启动时登记，不参与顺序执行。")
        else:
            lines.append("- 可执行节点。")
        if not callable(getter):
            lines.append("- （无参数定义）")
            continue
        try:
            definitions = getter()
        except Exception as exc:
            lines.append(f"- （读取参数定义失败：{exc}）")
            continue
        wrote = False
        for name, spec in (definitions or {}).items():
            if not isinstance(spec, Mapping):
                continue
            if str(name).startswith("---") or spec.get("hidden"):
                continue
            if str(spec.get("type") or "").strip().lower() in _SKIP_PARAM_TYPES:
                continue
            lines.append(f"- {_format_param_capability(str(name), spec)}")
            wrote = True
        if not wrote:
            lines.append("- （无可填写参数）")
    return "\n".join(lines)


_SCRIPT_PARAM_ALIASES = {
    "偏移横坐标": "偏移x",
    "偏移纵坐标": "偏移y",
    "随机横坐标": "随机",
    "随机纵坐标": "随机",
    "横坐标": "x",
    "纵坐标": "y",
    "按键内容": "按键",
    "起点横坐标": "x1",
    "起点纵坐标": "y1",
    "终点横坐标": "x2",
    "终点纵坐标": "y2",
    "text": "文本",
}
_SCRIPT_KWARGS_FORWARD = {
    "等图": ("找图", ()),
    "等图消失": ("找图", ()),
    "持续找图": ("找图", ("点击", "双击")),
    "等色": ("找色", ()),
    "等色消失": ("找色", ()),
    "等文字": ("找字", ()),
    "等文字消失": ("找字", ()),
    "等字库": ("找字库", ()),
    "等字库消失": ("找字库", ()),
    "等检测": ("检测", ()),
    "等检测消失": ("检测", ()),
    "持续检测": ("检测", ()),
    "按下": ("点击", ("双击", "动作", "次数", "间隔", "按住秒", "自动松开")),
    "松开": ("点击", ("双击", "动作", "次数", "间隔", "按住秒", "自动松开")),
    "按住": ("点击", ("双击", "动作", "次数", "自动松开")),
    "连点": ("点击", ("双击", "动作", "按住秒", "自动松开")),
}
_SCRIPT_ELEMENT_PARAMS = (
    ("名称", None),
    ("自动化ID", None),
    ("类名", None),
    ("控件类型", None),
    ("序号", 0),
    ("搜索深度", 30),
    ("超时", 5.0),
    ("目标", "当前"),
)
_SCRIPT_RESULT_FIELDS = (
    "通过", "类型", "内容", "分数", "阈值", "类别", "路径", "列表",
    "x", "y", "宽", "高", "左", "上", "右", "下",
    "颜色", "红", "绿", "蓝", "句柄", "返回值", "退出码",
    "标准输出", "标准错误", "进程号", "状态", "模式", "消息", "投递",
    "DPI", "缩放", "父句柄", "深度", "运行", "结果", "错误", "名字",
    "自动化ID", "类名", "控件类型", "开始时间", "完成时间",
    "头", "字节数", "地址", "勾选", "展开", "启用", "脱离屏幕", "聚焦",
    "动作", "设备号", "按钮", "摇杆X", "摇杆Y", "摇杆Z", "方向帽", "已连接",
    "DPI感知", "管理员", "DirectX", "OpenGL", "截图",
)


def _script_insert_paths(item: Mapping[str, Any]) -> List[str]:
    names = [part.strip() for part in str(item.get("name") or "").split("/") if part.strip()]
    return names or [str(item.get("name") or "").strip()]


def _is_example_param_name(name: str) -> bool:
    text = str(name or "").strip()
    if not text:
        return True
    if text[:1] in {'"', "'", "("}:
        return True
    stripped = text[1:] if text[:1] in "+-" else text
    return stripped.replace(".", "", 1).isdigit()


def _catalog_param_entries(item: Mapping[str, Any]) -> List[Tuple[str, Any, bool]]:
    raw = item.get("params")
    groups: Sequence[Any]
    if not raw:
        groups = ()
    elif isinstance(raw, (list, tuple)) and raw and isinstance(raw[0], (list, tuple)):
        groups = raw
    elif isinstance(raw, (list, tuple)):
        groups = (raw,)
    else:
        groups = ()
    entries: List[Tuple[str, Any, bool]] = []
    seen = set()
    for group in groups:
        for part in group:
            text = str(part).strip()
            if not text or "=" in text[:1]:
                continue
            name, has_default, default = text, False, None
            if "=" in text:
                name, raw_default = text.split("=", 1)
                name = name.strip()
                has_default = True
                default = _parse_catalog_default(raw_default.strip())
            if _is_example_param_name(name) or name in seen:
                continue
            seen.add(name)
            entries.append((name, default, has_default))
    return entries


def _parse_catalog_default(text: str) -> Any:
    value = str(text or "").strip()
    if value in {"无", "空", "None"}:
        return None
    if value in {"真", "True"}:
        return True
    if value in {"假", "False"}:
        return False
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def _format_script_default(value: Any) -> str:
    if value is None:
        return "无"
    if value is True:
        return "真"
    if value is False:
        return "假"
    if value == "":
        return '""'
    if isinstance(value, str):
        return value
    return str(value)


def _public_param_name(name: str) -> str:
    return _SCRIPT_PARAM_ALIASES.get(name, name)


def _script_runtime_callables() -> Dict[str, Any]:
    from task_workflow.script_commands import CommandHost
    from task_workflow.script_sandbox import (
        COMMAND_NAMES,
        _ClipboardApi,
        _DataApi,
        _EventView,
        _ExternalComponentApi,
        _HotkeyView,
        _InputDeviceView,
        _NetworkView,
        _PerformanceView,
        _ProcessView,
        _RegionApi,
        _TimerView,
        _VarsApi,
        _WindowView,
        script_assert,
        script_clamp,
        script_contains,
        script_cos,
        script_dict_get,
        script_dict_keys,
        script_dict_set,
        script_dict_values,
        script_endswith,
        script_extract_number,
        script_find,
        script_json_dump,
        script_json_parse,
        script_list_append,
        script_list_extend,
        script_list_pop,
        script_now_ms,
        script_random,
        script_replace,
        script_round,
        script_sin,
        script_slice,
        script_sort,
        script_split,
        script_sqrt,
        script_startswith,
        script_strip,
        script_type,
    )

    mapping: Dict[str, Any] = {}
    for name in COMMAND_NAMES:
        fn = getattr(CommandHost, name, None)
        if callable(fn):
            mapping[name] = fn
    mapping.update(
        {
            "开方": script_sqrt,
            "平方根": script_sqrt,
            "正弦": script_sin,
            "余弦": script_cos,
            "限制": script_clamp,
            "随机": script_random,
            "包含": script_contains,
            "截取": script_slice,
            "替换": script_replace,
            "分割": script_split,
            "时间": script_now_ms,
            "去空格": script_strip,
            "查找": script_find,
            "提取数字": script_extract_number,
            "JSON解析": script_json_parse,
            "JSON生成": script_json_dump,
            "字典获取": script_dict_get,
            "字典设置": script_dict_set,
            "列表追加": script_list_append,
            "列表合并": script_list_extend,
            "列表弹出": script_list_pop,
            "字典键": script_dict_keys,
            "字典值": script_dict_values,
            "类型": script_type,
            "断言": script_assert,
            "开头是": script_startswith,
            "结尾是": script_endswith,
            "排序": script_sort,
            "四舍五入": script_round,
        }
    )
    views = {
        "窗口": _WindowView,
        "输入设备": _InputDeviceView,
        "进程": _ProcessView,
        "网络": _NetworkView,
        "事件": _EventView,
        "热键": _HotkeyView,
        "定时器": _TimerView,
        "组件": _ExternalComponentApi,
        "数据": _DataApi,
        "性能": _PerformanceView,
        "剪贴板": _ClipboardApi,
        "变量": _VarsApi,
        "区域": _RegionApi,
    }
    for root, cls in views.items():
        for name, fn in inspect.getmembers(cls, predicate=inspect.isfunction):
            if name.startswith("_"):
                continue
            mapping[f"{root}.{name}"] = fn
    return mapping


def _inspect_callable_params(fn: Any) -> Tuple[List[Tuple[str, Any, bool, bool]], List[str]]:
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return [], []
    entries: List[Tuple[str, Any, bool, bool]] = []
    varnames: List[str] = []
    for param in signature.parameters.values():
        if param.name in {"self", "cls"}:
            continue
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            varnames.append(param.name)
            continue
        if param.kind is inspect.Parameter.VAR_POSITIONAL:
            entries.append((f"*{param.name}", None, False, True))
            continue
        has_default = param.default is not inspect.Parameter.empty
        default = param.default if has_default else None
        entries.append((param.name, default, has_default, False))
    return entries, varnames


_MOUSE_BUTTON_PATHS = frozenset(
    {
        "点击",
        "找图",
        "找色",
        "按下",
        "松开",
        "按住",
        "连点",
        "点文字",
        "点字库",
        "点元素",
        "等图",
        "等图消失",
        "持续找图",
        "等色",
        "等色消失",
    }
)


def _script_param_options(path: str, name: str) -> str:
    if name == "模式":
        return "前台驱动 | 前台脚本 | 后台消息 | 后台投递"
    if name == "按钮" or (name == "键" and path in _MOUSE_BUTTON_PATHS):
        return "左键 | 右键 | 中键"
    if name == "动作":
        if path == "按键":
            return "按下 | 松开"
        if path in _MOUSE_BUTTON_PATHS:
            return "完整点击 | 双击 | 仅按下 | 仅松开"
        return ""
    if name == "策略":
        return "最近 | 最大 | 置信度最高"
    if name == "方式" and path == "输入":
        return "仿真输入 | 粘贴"
    if name == "方向" and path == "滚轮":
        return "向上 | 向下"
    if name == "状态" and path == "窗口.元素切换":
        return "真 | 假"
    return ""


def _runtime_param_entries(path: str, runtime_map: Mapping[str, Any]) -> Tuple[List[Tuple[str, Any, bool]], bool]:
    if path in {"窗口.元素展开", "窗口.元素折叠"}:
        return [(name, default, True) for name, default in _SCRIPT_ELEMENT_PARAMS], False
    fn = runtime_map.get(path)
    if not callable(fn):
        return [], False
    raw_entries, _varnames = _inspect_callable_params(fn)
    entries: List[Tuple[str, Any, bool]] = []
    seen = set()
    has_varargs = False
    for name, default, has_default, variadic in raw_entries:
        if variadic:
            has_varargs = True
            continue
        public = _public_param_name(name)
        if not public or public in seen:
            continue
        if public == "目标" and path.startswith("窗口.") and default is None:
            default = "当前"
        seen.add(public)
        entries.append((public, default, has_default))
    forward = _SCRIPT_KWARGS_FORWARD.get(path)
    if forward:
        source, skipped = forward
        skip = set(skipped)
        source_entries, _ = _runtime_param_entries(source, runtime_map)
        known = {name for name, _default, _has in entries}
        for name, default, has_default in source_entries:
            if name in skip or name in known or name in {"超时", "间隔"}:
                continue
            entries.append((name, default, has_default))
    return entries, has_varargs


def _merge_script_params(path: str, item: Mapping[str, Any], runtime_map: Mapping[str, Any]) -> List[Tuple[str, Any, bool]]:
    runtime_entries, has_varargs = _runtime_param_entries(path, runtime_map)
    runtime_by_name = {name: (default, has_default) for name, default, has_default in runtime_entries}
    ordered: List[Tuple[str, Any, bool]] = []
    seen = set()

    def add(name: str, default: Any, has_default: bool) -> None:
        if not name or name in seen or name.startswith("*"):
            return
        seen.add(name)
        ordered.append((name, default, has_default))

    catalog_entries = _catalog_param_entries(item)
    if runtime_by_name:
        for name, default, has_default in catalog_entries:
            if name in runtime_by_name:
                runtime_default, runtime_has_default = runtime_by_name[name]
                add(name, runtime_default, runtime_has_default)
            elif has_varargs or path.startswith("组件."):
                add(name, default, has_default)
        for name, default, has_default in runtime_entries:
            add(name, default, has_default)
    else:
        for name, default, has_default in catalog_entries:
            add(name, default, has_default)
    return ordered


def _format_script_param(path: str, name: str, default: Any, has_default: bool) -> str:
    if name.startswith("*"):
        return name
    text = name
    if has_default:
        text += f"={_format_script_default(default)}"
    options = _script_param_options(path, name)
    if options:
        text += f"（{options}）"
    return text


def format_script_command_catalog() -> str:
    """Live custom-script commands, matching the editor command list."""
    from tasks.script_hints import KEYWORD_HINTS, _FIELD_HINTS
    from tasks.script_task import SCRIPT_INSERT_GROUPS

    runtime_map = _script_runtime_callables()
    lines = ["## 自定义脚本命令（运行时）"]
    for group in SCRIPT_INSERT_GROUPS:
        title = str(group.get("title") or "命令").strip()
        lines.append(f"### {title}")
        for item in group.get("items") or ():
            if not isinstance(item, Mapping):
                continue
            signature = str(item.get("signature") or item.get("snippet") or item.get("name") or "").strip()
            if not signature:
                continue
            signature = " | ".join(part.strip() for part in signature.splitlines() if part.strip())
            note = str(item.get("note") or "").strip()
            line = f"- {signature}"
            if note:
                line += f"：{note}"
            lines.append(line)
            paths = _script_insert_paths(item)
            if len(paths) == 1:
                params = _merge_script_params(paths[0], item, runtime_map)
                if params:
                    rendered = "；".join(
                        _format_script_param(paths[0], name, default, has_default)
                        for name, default, has_default in params
                    )
                    lines.append(f"  参数 {rendered}")
            else:
                for path in paths:
                    params = _merge_script_params(path, item, runtime_map)
                    if not params:
                        continue
                    rendered = "；".join(
                        _format_script_param(path, name, default, has_default)
                        for name, default, has_default in params
                    )
                    lines.append(f"  {path} 参数 {rendered}")
    lines.append("### 控制流")
    for name, hint in KEYWORD_HINTS.items():
        if not isinstance(hint, Mapping):
            continue
        display = " / ".join(str(item) for item in (hint.get("display") or ()) if item)
        note = str(hint.get("note") or "").strip()
        line = f"- {display or name}"
        if note:
            line += f"：{note}"
        lines.append(line)
    lines.append("### 结果字段")
    for name, text in _FIELD_HINTS.items():
        lines.append(f"- {name}：{text}")
    lines.append("- 结果对象字段：" + "、".join(f"结果.{name}" for name in _SCRIPT_RESULT_FIELDS))
    return "\n".join(lines)


def _truncate_context_text(text: str, limit: int) -> str:
    value = str(text or "")
    if len(value) <= limit:
        return value
    keep = max(0, limit - 8)
    return f"{value[:keep]}…（已截断）"


def _bounded_param_value(value: Any) -> Any:
    if isinstance(value, str):
        return _truncate_context_text(value, MAX_PARAM_VALUE_CHARS)
    dumped = json.dumps(value, ensure_ascii=False, allow_nan=False)
    if len(dumped) <= MAX_PARAM_VALUE_CHARS:
        return value
    return _truncate_context_text(dumped, MAX_PARAM_VALUE_CHARS)


def _format_coord(value: Any) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.1f}"


def _format_card_position(card: Mapping[str, Any]) -> str:
    if "pos_x" not in card or "pos_y" not in card:
        return ""
    return f"位置：{_format_coord(card['pos_x'])}, {_format_coord(card['pos_y'])}"


def _format_connection_type(line_type: Any) -> str:
    key = str(line_type or "").strip()
    if not key:
        raise ValueError("连线类型不能为空")
    return _LINE_TYPE_LABELS.get(key, key)


def _current_editor_view(main_window: Any) -> Tuple[Any, Any]:
    if main_window is None:
        return None, None
    tab = getattr(main_window, "workflow_tab_widget", None)
    view = None
    task = None
    if tab is not None:
        getter = getattr(tab, "get_current_workflow_view", None)
        if callable(getter):
            view = getter()
        task_id_getter = getattr(tab, "get_current_task_id", None)
        task_id = task_id_getter() if callable(task_id_getter) else None
        manager = getattr(tab, "task_manager", None)
        get_task = getattr(manager, "get_task", None) if manager is not None else None
        if callable(get_task) and task_id is not None:
            task = get_task(task_id)
    if view is None:
        view = getattr(main_window, "workflow_view", None)
    return view, task


def editor_resource_dirs(main_window: Any = None) -> Dict[str, str]:
    from task_workflow.resource_context import current_resource_dirs, resource_dirs_from_mapping

    current = current_resource_dirs()
    _view, task = _current_editor_view(main_window)
    if task is None:
        return current
    bound = resource_dirs_from_mapping(task)
    return {key: str(bound.get(key) or "") or current[key] for key in current}


def _workflow_resource_kind(path: str) -> str:
    from task_workflow.script_resources import resource_kind

    kind = resource_kind(path)
    if kind:
        return kind
    ext = os.path.splitext(str(path or ""))[1].lower()
    if ext in AI_IMAGE_MIMES or ext in _WORKFLOW_IMAGE_CONVERT_EXTS:
        return "image"
    if ext == ".txt":
        return "dict"
    return ""


def _iter_resource_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        if "\n" in value or ";" in value:
            for part in value.replace(";", "\n").splitlines():
                part = part.strip()
                if part:
                    yield part
            return
        text = value.strip()
        if text:
            yield text
        return
    if isinstance(value, Mapping):
        for item in value.values():
            yield from _iter_resource_strings(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_resource_strings(item)


def _format_file_size(size: int) -> str:
    if size < 1024:
        return f"{size} 字节"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _read_resource_text(path: str, kind: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if kind == "image" or kind in {"model", "audio"}:
        return ""
    if kind == "component" and ext != ".py":
        return ""
    if kind not in {"dict", "replay"} and not (kind == "component" and ext == ".py"):
        return ""
    with open(path, "r", encoding="utf-8") as handle:
        return _truncate_context_text(handle.read(), MAX_RESOURCE_TEXT_CHARS)


def _inspect_workflow_file(path: str, kind: str) -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "size": os.path.getsize(path),
        "width": 0,
        "height": 0,
        "text": "",
        "data_url": "",
        "error": "",
        "attach": False,
    }
    if kind == "image":
        try:
            from PIL import Image

            with Image.open(path) as image:
                info["width"], info["height"] = image.size
        except Exception:
            pass
        try:
            info["data_url"] = encode_image_for_chat(path)
            info["attach"] = True
        except Exception as exc:
            info["error"] = str(exc)
        return info
    try:
        info["text"] = _read_resource_text(path, kind)
    except UnicodeDecodeError:
        info["error"] = "不是 UTF-8 文本"
    except OSError as exc:
        info["error"] = str(exc)
    return info


def collect_workflow_resources(
    workflow: Optional[Mapping[str, Any]],
    dirs: Optional[Mapping[str, str]] = None,
) -> List[Dict[str, Any]]:
    from task_workflow.script_resources import list_script_resources, resolve_resource_path

    if not isinstance(workflow, Mapping):
        return []
    cards = workflow.get("cards")
    if not isinstance(cards, list):
        return []
    dir_map = dict(dirs or {})
    dir_kwargs = {
        "images_dir": str(dir_map.get("images_dir") or ""),
        "sounds_dir": str(dir_map.get("sounds_dir") or ""),
        "dicts_dir": str(dir_map.get("dicts_dir") or ""),
        "yolo_dir": str(dir_map.get("yolo_dir") or ""),
        "replays_dir": str(dir_map.get("replays_dir") or ""),
        "plugins_dir": str(dir_map.get("plugins_dir") or ""),
    }
    found: Dict[str, Dict[str, Any]] = {}

    def add(raw_path: str, card_id: Any, abs_path: str = "") -> None:
        text = str(raw_path or "").replace("\\", "/").strip()
        if not text:
            return
        kind = _workflow_resource_kind(text)
        if not kind:
            return
        resolved = str(abs_path or "").strip() or resolve_resource_path(text, **dir_kwargs)
        exists = bool(resolved and os.path.isfile(resolved))
        key = os.path.normcase(os.path.abspath(resolved)) if resolved else f"{kind}:{text.lower()}"
        item = found.get(key)
        if item is None:
            item = {
                "kind": kind,
                "path": text,
                "abs_path": resolved,
                "exists": exists,
                "card_ids": [],
                "size": 0,
                "width": 0,
                "height": 0,
                "text": "",
                "data_url": "",
                "error": "",
                "attach": False,
                "attach_index": 0,
            }
            if exists:
                item.update(_inspect_workflow_file(resolved, kind))
                item["exists"] = True
            found[key] = item
        if card_id is not None and card_id not in item["card_ids"]:
            item["card_ids"].append(card_id)

    for card in cards:
        if not isinstance(card, Mapping):
            continue
        card_id = card.get("id")
        parameters = card.get("parameters")
        if not isinstance(parameters, Mapping):
            continue
        source = parameters.get("script_source")
        if isinstance(source, str) and source.strip():
            for resource in list_script_resources(source, **dir_kwargs):
                add(str(resource.get("path") or ""), card_id, str(resource.get("abs_path") or ""))
        for key, value in parameters.items():
            if key == "script_source":
                continue
            for raw in _iter_resource_strings(value):
                add(raw, card_id)

    items = list(found.values())
    items.sort(key=lambda item: (item["card_ids"][:1] or [10**9], item["kind"], item["path"].lower()))
    attach_index = 0
    for item in items:
        if not item.get("attach"):
            continue
        if attach_index >= MAX_WORKFLOW_AI_IMAGES:
            item["attach"] = False
            item["data_url"] = ""
            continue
        attach_index += 1
        item["attach_index"] = attach_index
    return items


def _format_workflow_resources(resources: Sequence[Mapping[str, Any]]) -> List[str]:
    if not resources:
        return []
    lines = [
        "",
        "### 工作流资源",
        "下列文件已按工作流引用读取。图片若标明已附图，编号与随后的工作流附图一致。",
    ]
    for item in resources:
        kind = str(item.get("kind") or "")
        label = _RESOURCE_KIND_LABELS.get(kind, kind or "文件")
        path = str(item.get("path") or "")
        card_ids = item.get("card_ids") or []
        loc = f"（卡片 {'、'.join(str(card_id) for card_id in card_ids)}）" if card_ids else ""
        if not item.get("exists"):
            lines.append(f"- {label} `{path}`{loc}：不存在")
            continue
        parts = [f"- {label} `{path}`{loc}：存在"]
        width = int(item.get("width") or 0)
        height = int(item.get("height") or 0)
        if width > 0 and height > 0:
            parts.append(f"{width}×{height}")
        size = int(item.get("size") or 0)
        if size > 0:
            parts.append(_format_file_size(size))
        attach_index = int(item.get("attach_index") or 0)
        if attach_index:
            parts.append(f"已附图 {attach_index}")
        elif kind == "image":
            parts.append("未附图")
        if kind in {"model", "audio"} or (kind == "component" and not item.get("text")):
            parts.append("二进制，不作为文本展开")
        error = str(item.get("error") or "").strip()
        if error:
            parts.append(error)
        lines.append("，".join(parts))
        text = str(item.get("text") or "")
        if text:
            lines.append("```")
            lines.append(text.rstrip("\n"))
            lines.append("```")
    return lines


def collect_editor_workflow_snapshot(main_window: Any = None) -> Dict[str, Any]:
    """Read the active editor canvas. Missing editor is empty; read failure is error."""
    view, task = _current_editor_view(main_window)
    serialize = getattr(view, "serialize_workflow", None)
    if view is None or not callable(serialize):
        return {"status": "empty"}
    try:
        workflow = serialize()
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
    if not isinstance(workflow, dict):
        return {"status": "error", "error": "当前工作流数据不是字典"}
    return {
        "status": "ok",
        "name": str(getattr(task, "name", "") or "").strip(),
        "filepath": str(getattr(task, "filepath", "") or "").strip(),
        "modified": bool(getattr(task, "modified", False)),
        "workflow": workflow,
    }


def format_editor_workflow_context(
    snapshot: Optional[Mapping[str, Any]] = None,
    *,
    resources: Optional[Sequence[Mapping[str, Any]]] = None,
    resource_dirs: Optional[Mapping[str, str]] = None,
    header: Optional[str] = None,
) -> str:
    """Compact text of the active editor workflow for the chat system prompt."""
    header = _WORKFLOW_CONTEXT_HEADER if header is None else str(header)
    if not isinstance(snapshot, Mapping) or snapshot.get("status") == "empty":
        return f"{header}\n当前没有打开的工作流。" if header else "当前没有打开的工作流。"
    if snapshot.get("status") == "error":
        error = str(snapshot.get("error") or "未知错误").strip() or "未知错误"
        message = f"无法读取当前工作流：{error}"
        return f"{header}\n{message}" if header else message
    workflow = snapshot.get("workflow")
    if not isinstance(workflow, Mapping):
        message = "无法读取当前工作流：工作流数据不是字典"
        return f"{header}\n{message}" if header else message

    cards = workflow.get("cards")
    connections = workflow.get("connections")
    if not isinstance(cards, list):
        message = "无法读取当前工作流：卡片列表无效"
        return f"{header}\n{message}" if header else message
    if not isinstance(connections, list):
        message = "无法读取当前工作流：连线列表无效"
        return f"{header}\n{message}" if header else message

    name = str(snapshot.get("name") or "").strip() or "未命名"
    filepath = str(snapshot.get("filepath") or "").strip() or "尚未保存到文件"
    lines: List[str] = []
    if header:
        lines.append(header)
    lines.append(f"名称：{name}")
    lines.append(f"文件：{filepath}")
    if "modified" in snapshot:
        saved = "未保存" if snapshot.get("modified") else "已保存"
        lines.append(f"保存状态：{saved}")
    note = str(snapshot.get("format_note") or "").strip()
    if note:
        lines.append(note)
    lines.append(f"卡片数：{len(cards)}；连线数：{len(connections)}")
    export_cards: List[Dict[str, Any]] = []
    export_connections: List[Dict[str, Any]] = []

    for card in cards:
        if not isinstance(card, Mapping):
            return f"{header}\n无法读取当前工作流：存在无效卡片"
        card_id = card.get("id")
        task_type = str(card.get("task_type") or "").strip()
        if card_id is None or not task_type:
            return f"{header}\n无法读取当前工作流：存在无效卡片"
        custom_name = str(card.get("custom_name") or "").strip()
        title = f"### 卡片 {card_id}：{task_type}"
        if custom_name:
            title += f"（{custom_name}）"
        lines.append("")
        lines.append(title)
        try:
            position = _format_card_position(card)
        except (TypeError, ValueError):
            return f"{header}\n无法读取当前工作流：存在无效卡片"
        if position:
            lines.append(position)
        parameters = card.get("parameters")
        bounded: Dict[str, Any] = {}
        if isinstance(parameters, Mapping) and parameters:
            try:
                bounded = {str(key): _bounded_param_value(value) for key, value in parameters.items()}
                dumped = json.dumps(bounded, ensure_ascii=False, indent=2, allow_nan=False)
            except (TypeError, ValueError):
                return f"{header}\n无法读取当前工作流：存在无效卡片"
            lines.append("参数：")
            lines.append(dumped)
        export_cards.append({
            "id": card_id,
            "task_type": task_type,
            "pos_x": card.get("pos_x"),
            "pos_y": card.get("pos_y"),
            "parameters": bounded,
            "custom_name": card.get("custom_name"),
        })

    if connections:
        lines.append("")
        lines.append("### 连线")
        for item in connections:
            if not isinstance(item, Mapping):
                return f"{header}\n无法读取当前工作流：存在无效连线"
            start_id = item.get("start_card_id")
            end_id = item.get("end_card_id")
            raw_type = str(item.get("type") or "").strip()
            try:
                line_type = _format_connection_type(raw_type)
            except ValueError:
                return f"{header}\n无法读取当前工作流：存在无效连线"
            if start_id is None or end_id is None:
                return f"{header}\n无法读取当前工作流：存在无效连线"
            lines.append(f"- 卡片 {start_id} -{line_type}-> 卡片 {end_id}")
            export_connections.append({
                "start_card_id": start_id,
                "end_card_id": end_id,
                "type": raw_type,
            })

    resource_items = list(resources) if resources is not None else collect_workflow_resources(workflow, resource_dirs)
    lines.extend(_format_workflow_resources(resource_items))

    metadata = workflow.get("metadata")
    if isinstance(metadata, Mapping) and metadata:
        try:
            dumped_metadata = json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False)
        except (TypeError, ValueError):
            return f"{header}\n无法读取当前工作流：元数据无法序列化"
        lines.append("")
        lines.append("### 元数据")
        lines.append(dumped_metadata)

    export_payload: Dict[str, Any] = {
        "cards": export_cards,
        "connections": export_connections,
    }
    if isinstance(metadata, Mapping) and metadata:
        export_payload["metadata"] = dict(metadata)
    try:
        dumped_export = json.dumps(export_payload, ensure_ascii=False, indent=2, allow_nan=False)
    except (TypeError, ValueError) as exc:
        return f"{header}\n无法读取当前工作流：工作流 JSON 无法序列化：{exc}"
    lines.append("")
    lines.append("### 可应用的工作流JSON")
    lines.append("长参数可能已截断。修正时只把要改的项写进 ops，未改动的卡片不要整份回写。")
    lines.append(dumped_export)

    text = "\n".join(lines)
    if len(text) <= MAX_WORKFLOW_CONTEXT_CHARS:
        return text
    return _truncate_context_text(text, MAX_WORKFLOW_CONTEXT_CHARS)


def editor_workflow_bundle(main_window: Any = None) -> Tuple[str, List[Dict[str, Any]]]:
    snapshot = collect_editor_workflow_snapshot(main_window)
    dirs = editor_resource_dirs(main_window)
    workflow = snapshot.get("workflow") if isinstance(snapshot, Mapping) else None
    resources = collect_workflow_resources(workflow if isinstance(workflow, Mapping) else None, dirs)
    text = format_editor_workflow_context(snapshot, resources=resources)
    images = [
        {"path": str(item.get("abs_path") or ""), "data_url": str(item.get("data_url") or "")}
        for item in resources
        if int(item.get("attach_index") or 0) > 0
    ]
    return text, images


def editor_workflow_context(main_window: Any = None) -> str:
    text, _images = editor_workflow_bundle(main_window)
    return text


def chat_system_prompt(
    task_modules: Optional[Mapping[str, Any]] = None,
    *,
    workflow_context: Optional[str] = None,
    uploaded_workflow_context: Optional[str] = None,
) -> str:
    from app_core.app_config import APP_SOURCE_REPOSITORY, app_source_url

    parts = [
        _CHAT_SYSTEM_PROMPT,
        f"开源仓库：{APP_SOURCE_REPOSITORY}（{app_source_url()}）。",
    ]
    context = str(workflow_context or "").strip()
    if context:
        parts.append(context)
    uploaded = str(uploaded_workflow_context or "").strip()
    if uploaded:
        parts.append(uploaded)
    return "\n\n".join(parts)


def build_ai_chat_messages(
    system: str,
    history: Iterable[Mapping[str, Any]],
    *,
    extra_images: Optional[Sequence[Mapping[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """System + recent turns. Image turns become OpenAI vision content parts."""
    messages: list[dict[str, Any]] = [{"role": "system", "content": str(system or "")}]
    for item in history:
        role = str(item.get("role") or "user")
        if role not in {"user", "assistant"}:
            continue
        text = str(item.get("content") or "")[:MAX_PROMPT_CHARS]
        images = item.get("images") or []
        if images:
            content = build_user_message_content(text, images)
        else:
            content = text
        if content == "" or content == []:
            continue
        messages.append({"role": role, "content": content})
    extras = list(extra_images or [])
    if extras:
        payload = {
            "role": "user",
            "content": build_user_message_content(
                WORKFLOW_IMAGES_PROMPT,
                extras,
                max_images=MAX_WORKFLOW_AI_IMAGES,
            ),
        }
        if len(messages) > 1 and messages[-1].get("role") == "user":
            messages.insert(-1, payload)
        else:
            messages.append(payload)
    return messages
