"""Search the public LCA source repository for the in-app AI assistant.

The assistant does not use a bundled knowledge dump. Review looks at the
current default branch of the open-source repo.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from app_core.app_config import APP_SOURCE_REPOSITORY, app_source_url

REPO_CHECK_SECONDS = 6 * 3600
REPO_HTTP_TIMEOUT = 20
MAX_REPO_ZIP_BYTES = 40 * 1024 * 1024
MAX_REPO_FILE_BYTES = 512 * 1024
MAX_READ_CHARS = 12000
MAX_SEARCH_PATHS = 30
MAX_SEARCH_FILES = 24
MAX_MATCH_LINES = 40
MAX_LINE_CHARS = 240
_TEXT_EXTS = {".py", ".md", ".json", ".txt"}
_SKIP_DIR_NAMES = {".git", "__pycache__", "venv", "node_modules"}
_CACHE_LOCK = threading.RLock()
_MEMORY_STAMP = 0.0
_MEMORY_BRANCH = ""
_MEMORY_SHA = ""
_MEMORY_FILES: Dict[str, str] = {}
_GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "LCA-Desktop/1.0",
}


def _cache_root() -> Path:
    from utils.app_paths import get_user_data_dir

    return Path(get_user_data_dir()) / "ai_repo_cache"


def _stamp_path() -> Path:
    return _cache_root() / "stamp.json"


def _snapshot_dir() -> Path:
    return _cache_root() / "snapshot"


def clear_ai_repo_cache() -> None:
    global _MEMORY_STAMP, _MEMORY_BRANCH, _MEMORY_SHA, _MEMORY_FILES
    with _CACHE_LOCK:
        _MEMORY_STAMP = 0.0
        _MEMORY_BRANCH = ""
        _MEMORY_SHA = ""
        _MEMORY_FILES = {}
        root = _cache_root()
        if root.is_dir():
            shutil.rmtree(root, ignore_errors=True)


def _repo_owner_name() -> Tuple[str, str]:
    host, _, path = APP_SOURCE_REPOSITORY.partition("/")
    if host.lower() != "github.com" or not path or "/" not in path.strip("/"):
        raise RuntimeError("开源仓库不是 GitHub 地址，无法搜索")
    owner, _, name = path.strip("/").partition("/")
    owner = owner.strip()
    name = name.strip().removesuffix(".git")
    if not owner or not name or "/" in name:
        raise RuntimeError("开源仓库地址无效")
    return owner, name


def _http_get(
    url: str,
    *,
    opener: Optional[Callable[..., Any]] = None,
    timeout: int = REPO_HTTP_TIMEOUT,
    accept: str = "",
) -> bytes:
    post = opener or urllib.request.urlopen
    headers = dict(_GITHUB_HEADERS)
    if accept:
        headers["Accept"] = accept
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with post(request, timeout=max(5, int(timeout))) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        code = int(getattr(exc, "code", 0) or 0)
        if code == 403:
            raise RuntimeError("开源仓库暂时无法访问：GitHub 限流") from exc
        if code == 404:
            raise RuntimeError("开源仓库不存在或默认分支不可用") from exc
        raise RuntimeError(f"开源仓库返回 HTTP {code}") from exc
    except Exception as exc:
        raise RuntimeError(f"无法连接开源仓库：{exc}") from exc
    return data


def _default_branch(*, opener: Optional[Callable[..., Any]] = None) -> str:
    owner, name = _repo_owner_name()
    raw = _http_get(f"https://api.github.com/repos/{owner}/{name}", opener=opener)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("开源仓库仓库信息不是有效 JSON") from exc
    branch = str((payload or {}).get("default_branch") or "").strip()
    if not branch:
        raise RuntimeError("开源仓库没有默认分支")
    return branch


def _head_sha(branch: str, *, opener: Optional[Callable[..., Any]] = None) -> str:
    owner, name = _repo_owner_name()
    raw = _http_get(
        f"https://api.github.com/repos/{owner}/{name}/commits/{branch}",
        opener=opener,
    )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("开源仓库提交信息不是有效 JSON") from exc
    sha = str((payload or {}).get("sha") or "").strip()
    if not sha:
        raise RuntimeError("开源仓库没有提交记录")
    return sha


def _normalize_repo_path(path: str) -> str:
    text = str(path or "").replace("\\", "/").strip()
    if not text:
        raise ValueError("仓库路径无效")
    if text.startswith("/") or ":" in text.split("/", 1)[0]:
        raise ValueError("仓库路径无效")
    parts: List[str] = []
    for part in text.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            raise ValueError("仓库路径无效")
        parts.append(part)
    if not parts:
        raise ValueError("仓库路径无效")
    return "/".join(parts)


def _safe_extract_name(member: str, prefix: str) -> Optional[str]:
    name = str(member or "").replace("\\", "/")
    if not name or name.endswith("/"):
        return None
    if prefix and name.startswith(prefix):
        name = name[len(prefix) :]
    name = name.lstrip("/")
    if not name:
        return None
    try:
        normalized = _normalize_repo_path(name)
    except ValueError:
        return None
    parts = normalized.split("/")
    if any(part in _SKIP_DIR_NAMES for part in parts):
        return None
    ext = os.path.splitext(normalized)[1].lower()
    if ext not in _TEXT_EXTS:
        return None
    return normalized


def _load_stamp() -> Dict[str, Any]:
    path = _stamp_path()
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_stamp(branch: str, sha: str, *, fetched: bool = True) -> None:
    root = _cache_root()
    root.mkdir(parents=True, exist_ok=True)
    now = time.time()
    previous = _load_stamp()
    payload = {
        "repo": APP_SOURCE_REPOSITORY,
        "branch": branch,
        "sha": sha,
        "fetched_at": now if fetched else float(previous.get("fetched_at") or now),
        "checked_at": now,
    }
    with open(_stamp_path(), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def _check_is_fresh(stamp: Optional[Dict[str, Any]] = None) -> bool:
    payload = dict(stamp or _load_stamp())
    if str(payload.get("repo") or "") != APP_SOURCE_REPOSITORY:
        return False
    if "checked_at" in payload:
        checked = float(payload.get("checked_at") or 0)
    else:
        checked = float(payload.get("fetched_at") or 0)
    return checked > 0 and time.time() - checked < REPO_CHECK_SECONDS


def repo_snapshot_ready() -> bool:
    if _MEMORY_FILES:
        return True
    stamp = _load_stamp()
    return (
        str(stamp.get("repo") or "") == APP_SOURCE_REPOSITORY
        and _snapshot_dir().is_dir()
        and bool(stamp.get("sha") or stamp.get("fetched_at"))
    )


def cached_snapshot_id() -> str:
    if _MEMORY_SHA:
        return _MEMORY_SHA
    return str(_load_stamp().get("sha") or "")


def _read_snapshot_files(root: Path) -> Dict[str, str]:
    files: Dict[str, str] = {}
    root_key = os.path.normcase(str(root.resolve()))
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in _SKIP_DIR_NAMES]
        for filename in filenames:
            full = Path(current) / filename
            try:
                resolved = str(full.resolve())
            except OSError:
                continue
            if not os.path.normcase(resolved).startswith(root_key):
                continue
            relative = full.relative_to(root).as_posix()
            ext = os.path.splitext(relative)[1].lower()
            if ext not in _TEXT_EXTS:
                continue
            try:
                size = full.stat().st_size
            except OSError:
                continue
            if size <= 0 or size > MAX_REPO_FILE_BYTES:
                continue
            try:
                text = full.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            files[relative] = text
    return files


def _extract_zip(blob: bytes, destination: Path) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile as exc:
        raise RuntimeError("开源仓库源码压缩包无效") from exc
    names = archive.namelist()
    prefix = ""
    if names:
        first = str(names[0] or "").replace("\\", "/")
        head = first.split("/", 1)[0]
        if head and all(str(item or "").replace("\\", "/").startswith(head + "/") or str(item or "").replace("\\", "/") == head for item in names):
            prefix = head + "/"
    destination.mkdir(parents=True, exist_ok=True)
    dest_key = os.path.normcase(str(destination.resolve()))
    for info in archive.infolist():
        if info.is_dir():
            continue
        relative = _safe_extract_name(info.filename, prefix)
        if not relative:
            continue
        if info.file_size > MAX_REPO_FILE_BYTES:
            continue
        target = (destination / relative).resolve()
        if not os.path.normcase(str(target)).startswith(dest_key):
            raise RuntimeError("开源仓库压缩包路径无效")
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info, "r") as source:
            data = source.read()
        if not data:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        target.write_text(text, encoding="utf-8")


def _remember(files: Dict[str, str], branch: str, sha: str, stamp: float) -> Dict[str, str]:
    global _MEMORY_STAMP, _MEMORY_BRANCH, _MEMORY_SHA, _MEMORY_FILES
    _MEMORY_FILES = dict(files)
    _MEMORY_BRANCH = branch
    _MEMORY_SHA = sha
    _MEMORY_STAMP = stamp
    return dict(_MEMORY_FILES)


def _disk_files() -> Dict[str, str]:
    root = _snapshot_dir()
    if not root.is_dir():
        return {}
    return _read_snapshot_files(root)


def _refresh_snapshot(*, opener: Optional[Callable[..., Any]] = None) -> Tuple[str, str, Dict[str, str]]:
    owner, name = _repo_owner_name()
    branch = _default_branch(opener=opener)
    sha = _head_sha(branch, opener=opener)
    url = f"https://codeload.github.com/{owner}/{name}/zip/refs/heads/{branch}"
    blob = _http_get(
        url,
        opener=opener,
        timeout=max(REPO_HTTP_TIMEOUT, 30),
        accept="*/*",
    )
    if not blob:
        raise RuntimeError("开源仓库源码是空的")
    if len(blob) > MAX_REPO_ZIP_BYTES:
        raise RuntimeError("开源仓库源码过大")
    root = _cache_root()
    root.mkdir(parents=True, exist_ok=True)
    incoming = root / "snapshot.tmp"
    current = _snapshot_dir()
    if incoming.exists():
        shutil.rmtree(incoming, ignore_errors=True)
    try:
        _extract_zip(blob, incoming)
        files = _read_snapshot_files(incoming)
        if not files:
            raise RuntimeError("开源仓库里没有可阅读的源码")
        if current.exists():
            shutil.rmtree(current, ignore_errors=True)
        os.replace(incoming, current)
        _write_stamp(branch, sha, fetched=True)
    finally:
        if incoming.exists():
            shutil.rmtree(incoming, ignore_errors=True)
    return branch, sha, files


def ensure_source_repository(*, opener: Optional[Callable[..., Any]] = None) -> Dict[str, str]:
    now = time.time()
    with _CACHE_LOCK:
        stamp = _load_stamp()
        if _MEMORY_FILES and _check_is_fresh({"repo": APP_SOURCE_REPOSITORY, "checked_at": _MEMORY_STAMP}):
            return dict(_MEMORY_FILES)
        disk = dict(_MEMORY_FILES) if _MEMORY_FILES else _disk_files()
        stamp_ok = str(stamp.get("repo") or "") == APP_SOURCE_REPOSITORY and bool(disk)
        if stamp_ok and _check_is_fresh(stamp):
            return _remember(
                disk,
                str(stamp.get("branch") or ""),
                str(stamp.get("sha") or ""),
                float(stamp.get("checked_at") or now),
            )
        if stamp_ok:
            branch = str(stamp.get("branch") or "")
            try:
                if not branch:
                    branch = _default_branch(opener=opener)
                sha = _head_sha(branch, opener=opener)
            except Exception:
                sha = str(stamp.get("sha") or "")
                _write_stamp(branch, sha, fetched=False)
                return _remember(disk, branch, sha, now)
            if sha == str(stamp.get("sha") or ""):
                _write_stamp(branch, sha, fetched=False)
                return _remember(disk, branch, sha, now)
        branch, sha, files = _refresh_snapshot(opener=opener)
        return _remember(files, branch, sha, now)


def list_source_repository_files(*, opener: Optional[Callable[..., Any]] = None) -> List[str]:
    return sorted(ensure_source_repository(opener=opener))


def read_source_repository_file(path: str, *, opener: Optional[Callable[..., Any]] = None) -> str:
    normalized = _normalize_repo_path(path)
    files = ensure_source_repository(opener=opener)
    text = files.get(normalized)
    if text is None:
        raise FileNotFoundError(f"开源仓库中没有这个文件：{normalized}")
    if len(text) <= MAX_READ_CHARS:
        return text
    return text[:MAX_READ_CHARS] + "\n…（已截断）"


def search_source_repository(keyword: str, *, opener: Optional[Callable[..., Any]] = None) -> str:
    query = " ".join(str(keyword or "").split())
    if not query:
        raise ValueError("搜索词不能为空")
    terms = [item for item in query.lower().split() if item]
    if not terms:
        raise ValueError("搜索词不能为空")
    files = ensure_source_repository(opener=opener)
    path_hits = [path for path in files if all(term in path.lower() for term in terms)]
    if path_hits:
        fetch_paths = path_hits[:MAX_SEARCH_FILES]
    else:
        ranked = [
            path for path in files
            if os.path.splitext(path)[1].lower() in {".py", ".md"}
        ]
        ranked.sort(
            key=lambda path: (
                0 if path.startswith("tasks/") else
                1 if path.startswith("task_workflow/") else
                2 if path.startswith("docs/") else
                3,
                path,
            )
        )
        fetch_paths = ranked[:80]

    lines = [f"开源仓库 {APP_SOURCE_REPOSITORY}（{app_source_url()}）搜索「{query}」："]
    if path_hits:
        lines.append("路径：")
        for path in path_hits[:MAX_SEARCH_PATHS]:
            lines.append(f"- {path}")
    hits = 0
    for path in fetch_paths:
        text = files.get(path) or ""
        matched: List[str] = []
        for index, raw in enumerate(text.splitlines(), start=1):
            if not any(term in raw.lower() for term in terms):
                continue
            snippet = raw.strip()
            if len(snippet) > MAX_LINE_CHARS:
                snippet = snippet[:MAX_LINE_CHARS] + "…"
            matched.append(f"{path}:{index}:{snippet}")
            hits += 1
            if len(matched) >= 8:
                break
        if matched:
            lines.append("")
            lines.extend(matched)
        if hits >= MAX_MATCH_LINES:
            break
    if not path_hits and hits == 0:
        return f"开源仓库中没有与「{query}」匹配的文件或源码。"
    text = "\n".join(lines)
    if len(text) <= MAX_READ_CHARS:
        return text
    return text[:MAX_READ_CHARS] + "\n…（已截断）"
