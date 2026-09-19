"""Local AI assistant conversation store. API keys are never written here."""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from typing import Any, Dict, List, Mapping, Optional, Sequence

from utils.app_paths import get_ai_sessions_path, get_user_data_dir

MAX_SESSIONS = 40
MAX_MESSAGES = 80
DEFAULT_TITLE = "新对话"


def _now() -> float:
    return time.time()


def empty_session(*, title: str = DEFAULT_TITLE) -> Dict[str, Any]:
    stamp = _now()
    return {
        "id": uuid.uuid4().hex,
        "title": title or DEFAULT_TITLE,
        "created_at": stamp,
        "updated_at": stamp,
        "messages": [],
    }


def empty_store() -> Dict[str, Any]:
    session = empty_session()
    return {"current_id": session["id"], "sessions": [session]}


def session_attachments_dir(session_id: str) -> str:
    path = os.path.join(get_user_data_dir(), "ai_attachments", str(session_id or "").strip())
    os.makedirs(path, exist_ok=True)
    return path


def _remove_session_attachments(session_id: str) -> None:
    folder = os.path.join(get_user_data_dir(), "ai_attachments", str(session_id or "").strip())
    if str(session_id or "").strip() and os.path.isdir(folder):
        shutil.rmtree(folder, ignore_errors=True)


def write_session_images(
    session_id: str,
    blobs: Sequence[Mapping[str, Any]],
) -> List[Dict[str, str]]:
    from app_core.ai_assistant import (
        AI_IMAGE_MIMES,
        MAX_AI_IMAGE_BYTES,
        MAX_AI_IMAGES_PER_TURN,
        attachable_image_mime,
    )

    items = list(blobs or [])
    if len(items) > MAX_AI_IMAGES_PER_TURN:
        raise ValueError(f"一次最多发送 {MAX_AI_IMAGES_PER_TURN} 张图片")
    folder = session_attachments_dir(session_id)
    mime_to_ext = {mime: ext for ext, mime in AI_IMAGE_MIMES.items() if ext != ".jpeg"}
    saved: List[Dict[str, str]] = []
    for item in items:
        data = item.get("data")
        if not isinstance(data, (bytes, bytearray)) or not data:
            raise ValueError("图片数据无效")
        raw = bytes(data)
        if len(raw) > MAX_AI_IMAGE_BYTES:
            raise ValueError(f"图片太大，单张不能超过 {MAX_AI_IMAGE_BYTES // (1024 * 1024)} MB")
        mime = attachable_image_mime(mime=str(item.get("mime") or ""))
        path = os.path.join(folder, uuid.uuid4().hex + mime_to_ext[mime])
        with open(path, "wb") as handle:
            handle.write(raw)
        saved.append({"path": path, "mime": mime})
    return saved


def write_session_files(
    session_id: str,
    blobs: Sequence[Mapping[str, Any]],
) -> List[Dict[str, str]]:
    from app_core.ai_assistant import (
        MAX_AI_WORKFLOW_FILE_BYTES,
        MAX_AI_WORKFLOW_FILES_PER_TURN,
        attachable_workflow_suffix,
    )

    items = list(blobs or [])
    if len(items) > MAX_AI_WORKFLOW_FILES_PER_TURN:
        raise ValueError(f"一次最多上传 {MAX_AI_WORKFLOW_FILES_PER_TURN} 个工作流文件")
    folder = session_attachments_dir(session_id)
    saved: List[Dict[str, str]] = []
    for item in items:
        data = item.get("data")
        if not isinstance(data, (bytes, bytearray)) or not data:
            raise ValueError("工作流文件数据无效")
        raw = bytes(data)
        if len(raw) > MAX_AI_WORKFLOW_FILE_BYTES:
            raise ValueError(
                f"工作流文件太大，单个不能超过 {MAX_AI_WORKFLOW_FILE_BYTES // (1024 * 1024)} MB"
            )
        name = str(item.get("name") or "").strip() or "workflow.json"
        ext = attachable_workflow_suffix(name)
        path = os.path.join(folder, uuid.uuid4().hex + ext)
        with open(path, "wb") as handle:
            handle.write(raw)
        saved.append({"path": path, "name": os.path.basename(name)})
    return saved


def _normalize_images(raw: Any) -> List[Dict[str, str]]:
    from app_core.ai_assistant import AI_IMAGE_MIME_SET

    images: List[Dict[str, str]] = []
    if not isinstance(raw, list):
        return images
    for item in raw:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        mime = str(item.get("mime") or "").strip().lower()
        if mime == "image/jpg":
            mime = "image/jpeg"
        if not path or mime not in AI_IMAGE_MIME_SET:
            continue
        images.append({"path": path, "mime": mime})
    return images


def _normalize_files(raw: Any) -> List[Dict[str, str]]:
    from app_core.ai_assistant import AI_WORKFLOW_EXTS

    files: List[Dict[str, str]] = []
    if not isinstance(raw, list):
        return files
    for item in raw:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        name = str(item.get("name") or "").strip() or os.path.basename(path)
        ext = os.path.splitext(name or path)[1].lower()
        if not path or ext not in AI_WORKFLOW_EXTS:
            continue
        files.append({"path": path, "name": name or os.path.basename(path)})
    return files


def _normalize_message(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    role = str(raw.get("role") or "").strip()
    content = str(raw.get("content") or "")
    images = _normalize_images(raw.get("images"))
    files = _normalize_files(raw.get("files"))
    thinking = str(raw.get("thinking") or "").strip() if role == "assistant" else ""
    if role not in {"user", "assistant"}:
        return None
    if not content.strip() and not images and not files and not thinking:
        return None
    message: Dict[str, Any] = {"role": role, "content": content}
    if images:
        message["images"] = images
    if files:
        message["files"] = files
    if thinking:
        message["thinking"] = thinking
    return message


def _normalize_session(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    session_id = str(raw.get("id") or "").strip() or uuid.uuid4().hex
    title = str(raw.get("title") or DEFAULT_TITLE).strip() or DEFAULT_TITLE
    messages = []
    for item in raw.get("messages") or []:
        message = _normalize_message(item)
        if message:
            messages.append(message)
        if len(messages) >= MAX_MESSAGES:
            break
    return {
        "id": session_id,
        "title": title,
        "created_at": float(raw.get("created_at") or _now()),
        "updated_at": float(raw.get("updated_at") or _now()),
        "messages": messages,
    }


def normalize_store(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return empty_store()
    sessions = []
    seen = set()
    for item in raw.get("sessions") or []:
        session = _normalize_session(item)
        if session is None or session["id"] in seen:
            continue
        seen.add(session["id"])
        sessions.append(session)
        if len(sessions) >= MAX_SESSIONS:
            break
    if not sessions:
        return empty_store()
    sessions.sort(key=lambda item: float(item.get("updated_at") or 0), reverse=True)
    current_id = str(raw.get("current_id") or "")
    if current_id not in {item["id"] for item in sessions}:
        current_id = sessions[0]["id"]
    return {"current_id": current_id, "sessions": sessions}


def load_ai_sessions(path: Optional[str] = None) -> Dict[str, Any]:
    target = path or get_ai_sessions_path()
    try:
        with open(target, "r", encoding="utf-8") as handle:
            return normalize_store(json.load(handle))
    except FileNotFoundError:
        return empty_store()
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return empty_store()


def save_ai_sessions(store: Dict[str, Any], path: Optional[str] = None) -> None:
    target = path or get_ai_sessions_path()
    directory = os.path.dirname(target)
    if directory:
        os.makedirs(directory, exist_ok=True)
    payload = normalize_store(store)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def get_session(store: Dict[str, Any], session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    wanted = str(session_id or store.get("current_id") or "")
    for session in store.get("sessions") or []:
        if session.get("id") == wanted:
            return session
    return None


def set_current_session(store: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    if get_session(store, session_id) is None:
        return store
    store["current_id"] = session_id
    return store


def create_session(store: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    session = empty_session(**kwargs)
    sessions = list(store.get("sessions") or [])
    sessions.insert(0, session)
    dropped = sessions[MAX_SESSIONS:]
    store["sessions"] = sessions[:MAX_SESSIONS]
    store["current_id"] = session["id"]
    for item in dropped:
        _remove_session_attachments(str(item.get("id") or ""))
    return session


def delete_session(store: Dict[str, Any], session_id: str) -> Optional[Dict[str, Any]]:
    sessions = [item for item in (store.get("sessions") or []) if item.get("id") != session_id]
    _remove_session_attachments(session_id)
    if not sessions:
        replacement = empty_session()
        store["sessions"] = [replacement]
        store["current_id"] = replacement["id"]
        return replacement
    store["sessions"] = sessions
    if store.get("current_id") == session_id:
        store["current_id"] = sessions[0]["id"]
    return get_session(store)


def rename_session(store: Dict[str, Any], session_id: str, title: str) -> Optional[Dict[str, Any]]:
    session = get_session(store, session_id)
    if session is None:
        return None
    session["title"] = str(title or "").strip() or DEFAULT_TITLE
    session["updated_at"] = _now()
    return session


def append_message(
    store: Dict[str, Any],
    session_id: str,
    role: str,
    content: str,
    *,
    images: Optional[Sequence[Mapping[str, Any]]] = None,
    files: Optional[Sequence[Mapping[str, Any]]] = None,
    thinking: str = "",
) -> Optional[Dict[str, Any]]:
    session = get_session(store, session_id)
    payload: Dict[str, Any] = {"role": role, "content": content}
    if images:
        payload["images"] = list(images)
    if files:
        payload["files"] = list(files)
    if thinking:
        payload["thinking"] = thinking
    message = _normalize_message(payload)
    if session is None or message is None:
        return None
    session["messages"] = (list(session.get("messages") or []) + [message])[-MAX_MESSAGES:]
    session["updated_at"] = _now()
    if session.get("title") in {"", DEFAULT_TITLE} and message["role"] == "user":
        title = suggest_session_title(message["content"])
        if title == DEFAULT_TITLE and message.get("images"):
            title = "图片"
        elif title == DEFAULT_TITLE and message.get("files"):
            title = suggest_session_title(str(message["files"][0].get("name") or ""))
            if title == DEFAULT_TITLE:
                title = "工作流文件"
        session["title"] = title
    return session


def suggest_session_title(text: str, *, max_length: int = 16) -> str:
    lines = str(text or "").splitlines()
    first = lines[0].strip() if lines else ""
    first = " ".join(first.split())
    if not first:
        return DEFAULT_TITLE
    return first[:max_length]


def chat_history(session: Optional[Dict[str, Any]], *, limit: int = 8) -> List[Dict[str, Any]]:
    messages = list((session or {}).get("messages") or [])
    history = []
    for item in messages[-max(1, int(limit)):]:
        message = _normalize_message(item)
        if message:
            history.append(message)
    return history


def latest_user_files(session: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
    for item in reversed(list((session or {}).get("messages") or [])):
        if str(item.get("role") or "") != "user":
            continue
        return _normalize_files(item.get("files"))
    return []


def latest_attached_files(session: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
    for item in reversed(list((session or {}).get("messages") or [])):
        if str(item.get("role") or "") != "user":
            continue
        files = _normalize_files(item.get("files"))
        if files:
            return files
    return []
