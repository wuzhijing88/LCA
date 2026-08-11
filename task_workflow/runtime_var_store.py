# -*- coding: utf-8 -*-
"""
运行时变量存储（SQLite）。

目标：
1. 避免大量运行变量长期常驻主进程内存。
2. 支持按变量名懒加载读取。
3. 工作流文件仅保存轻量引用标记（manifest）。
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
from typing import Any, Dict, Optional, Tuple, Union

from utils.app_paths import get_runtime_data_dir, get_user_data_dir

STORAGE_KIND = "sqlite_runtime_vars_v1"
GLOBAL_STORAGE_KIND = "sqlite_global_vars_v1"

_DB_FILE_NAME = "workflow_runtime_vars.db"
_DB_PATH_ENV_NAME = "LCA_RUNTIME_VARS_DB_PATH"
_DB_INIT_LOCK = threading.Lock()
_DB_IO_LOCK = threading.Lock()
_DB_READY = False
_DB_PATH_CACHE: Optional[str] = None
_MANIFEST_SHADOW_KEYS = {"storage", "task_key", "count", "updated_at"}
_RUNTIME_VARS_IN_BATCH = 400
VarSource = Optional[Union[int, str]]


def _normalize_path(path: str) -> str:
    try:
        return os.path.normcase(os.path.abspath(path))
    except Exception:
        return str(path or "")


def _normalize_var_source(source: Any) -> VarSource:
    if source is None:
        return None

    if isinstance(source, str):
        text = source.strip()
        if not text:
            return None
        if text.lower() == "global" or text == "全局变量":
            return "global"
        try:
            return int(text)
        except Exception:
            return None

    try:
        return int(source)
    except Exception:
        return None


def _build_runtime_db_candidates() -> Tuple[str, str, str, str]:
    primary_dir = get_runtime_data_dir("LCA")
    legacy_user_root_dir = get_user_data_dir("LCA")
    temp_dir = os.path.join(tempfile.gettempdir(), "LCA")
    legacy_cwd_dir = os.path.join(os.getcwd(), ".runtime_data")
    return (
        os.path.join(primary_dir, _DB_FILE_NAME),
        os.path.join(legacy_user_root_dir, _DB_FILE_NAME),
        os.path.join(temp_dir, _DB_FILE_NAME),
        os.path.join(legacy_cwd_dir, _DB_FILE_NAME),
    )


def _is_dir_writable(dir_path: str) -> bool:
    try:
        os.makedirs(dir_path, exist_ok=True)
    except Exception:
        return False

    probe_name = f"rw_probe_{os.getpid()}_{int(time.time() * 1000)}.tmp"
    probe_path = os.path.join(dir_path, probe_name)
    try:
        with open(probe_path, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe_path)
        return True
    except Exception:
        try:
            if os.path.exists(probe_path):
                os.remove(probe_path)
        except Exception:
            pass
        return False


def _pick_best_existing_db(paths) -> Optional[str]:
    best_path = None
    best_score = None
    for raw_path in paths or []:
        path = str(raw_path or "").strip()
        if not path:
            continue
        try:
            if not os.path.exists(path):
                continue
            size = int(os.path.getsize(path))
            mtime = float(os.path.getmtime(path))
        except Exception:
            continue
        score = (size > 0, mtime, size)
        if best_score is None or score > best_score:
            best_score = score
            best_path = path
    return best_path


def _safe_runtime_row_count(db_path: Optional[str]) -> int:
    path = str(db_path or "").strip()
    if not path or not os.path.exists(path):
        return 0
    conn = None
    try:
        conn = sqlite3.connect(path, timeout=2)
        row = conn.execute("SELECT COUNT(1) FROM runtime_vars").fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def _copy_runtime_db(source_path: str, target_path: str) -> None:
    src = str(source_path or "").strip()
    dst = str(target_path or "").strip()
    if not src or not dst:
        return
    if _normalize_path(src) == _normalize_path(dst):
        return
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        for suffix in ("-wal", "-shm"):
            sidecar_src = src + suffix
            sidecar_dst = dst + suffix
            if os.path.exists(sidecar_src):
                shutil.copy2(sidecar_src, sidecar_dst)
    except Exception:
        pass


def _get_db_path() -> str:
    global _DB_PATH_CACHE
    if _DB_PATH_CACHE:
        return _DB_PATH_CACHE

    forced_db_path = str(os.environ.get(_DB_PATH_ENV_NAME) or "").strip()
    if forced_db_path:
        try:
            os.makedirs(os.path.dirname(forced_db_path), exist_ok=True)
        except Exception:
            pass
        _DB_PATH_CACHE = forced_db_path
        return _DB_PATH_CACHE

    primary_db, legacy_user_root_db, temp_db, legacy_cwd_db = _build_runtime_db_candidates()
    writable_targets = [primary_db, legacy_user_root_db, temp_db, legacy_cwd_db]
    all_candidates = [primary_db, legacy_user_root_db, temp_db, legacy_cwd_db]
    source_db = _pick_best_existing_db(all_candidates)

    selected_target = None
    for candidate in writable_targets:
        if _is_dir_writable(os.path.dirname(candidate)):
            selected_target = candidate
            break

    if selected_target is None:
        selected_target = source_db or primary_db
        _DB_PATH_CACHE = selected_target
        return _DB_PATH_CACHE

    if source_db and _normalize_path(source_db) != _normalize_path(selected_target):
        source_rows = _safe_runtime_row_count(source_db)
        target_rows = _safe_runtime_row_count(selected_target)
        if source_rows > 0 and target_rows <= 0:
            _copy_runtime_db(source_db, selected_target)

    _DB_PATH_CACHE = selected_target
    return _DB_PATH_CACHE


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(_get_db_path(), timeout=30)


def _ensure_schema() -> None:
    global _DB_READY
    if _DB_READY:
        return

    with _DB_INIT_LOCK:
        if _DB_READY:
            return
        conn = _connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_vars (
                    task_key TEXT NOT NULL,
                    var_key TEXT NOT NULL,
                    var_value TEXT,
                    var_source INTEGER,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (task_key, var_key)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_runtime_vars_task_key ON runtime_vars(task_key)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS global_vars (
                    var_key TEXT PRIMARY KEY,
                    var_entry TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS global_var_meta (
                    meta_key TEXT PRIMARY KEY,
                    meta_value TEXT
                )
                """
            )
            conn.commit()
            _DB_READY = True
        finally:
            conn.close()


def is_storage_manifest(data: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(data, dict):
        return False
    if str(data.get("storage") or "").strip() != STORAGE_KIND:
        return False
    task_key = str(data.get("task_key") or "").strip()
    return bool(task_key)


def build_task_key(
    filepath: Optional[str],
    task_id: Optional[int] = None,
    task_name: Optional[str] = None,
) -> str:
    """生成稳定任务 key。优先使用文件路径，其次回退会话 key。"""
    path = str(filepath or "").strip()
    if path:
        normalized = os.path.normcase(os.path.abspath(path)).replace("\\", "/")
        return f"path:{normalized}"

    tid = "none"
    try:
        if task_id is not None:
            tid = str(int(task_id))
    except Exception:
        tid = str(task_id or "none")
    name = str(task_name or "").strip()
    return f"session:{tid}:{name}"


def _sanitize_manifest_shadow_vars(
    task_key: str,
    global_vars: Optional[Dict[str, Any]],
    var_sources: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, VarSource]]:
    if not isinstance(global_vars, dict):
        return {}, {}

    normalized_vars = dict(global_vars)
    normalized_sources = {
        str(name): _normalize_var_source(source)
        for name, source in dict(var_sources or {}).items()
        if str(name).strip()
    }

    if not _MANIFEST_SHADOW_KEYS.issubset(set(normalized_vars.keys())):
        return normalized_vars, normalized_sources

    storage_value = str(normalized_vars.get("storage") or "").strip()
    shadow_task_key = str(normalized_vars.get("task_key") or "").strip()
    if storage_value != STORAGE_KIND or not shadow_task_key:
        return normalized_vars, normalized_sources

    try:
        int(normalized_vars.get("count") or 0)
        float(normalized_vars.get("updated_at") or 0.0)
    except Exception:
        return normalized_vars, normalized_sources

    for key in _MANIFEST_SHADOW_KEYS:
        normalized_vars.pop(key, None)
        normalized_sources.pop(key, None)
    return normalized_vars, normalized_sources


def _normalize_snapshot(snapshot: Optional[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    if not isinstance(snapshot, dict):
        return {}, {}

    if is_storage_manifest(snapshot):
        manifest_task_key = str(snapshot.get("task_key") or "").strip()
        if not manifest_task_key:
            return {}, {}
        try:
            loaded_vars, loaded_sources = load_runtime_snapshot(manifest_task_key)
        except Exception:
            return {}, {}
        return _sanitize_manifest_shadow_vars(
            manifest_task_key,
            loaded_vars,
            loaded_sources,
        )

    global_vars = snapshot.get("global_vars")
    if isinstance(global_vars, dict):
        var_sources = snapshot.get("var_sources", {})
        if not isinstance(var_sources, dict):
            var_sources = {}
        return dict(global_vars), {
            str(name): _normalize_var_source(source)
            for name, source in var_sources.items()
            if str(name).strip()
        }

    # 兼容旧格式：变量字典平铺
    legacy_vars = {}
    for key, value in snapshot.items():
        name = str(key or "").strip()
        if not name:
            continue
        legacy_vars[name] = value
    return legacy_vars, {}


def _serialize_var_value(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    except Exception:
        return json.dumps(str(value), ensure_ascii=False, separators=(",", ":"))


def save_runtime_snapshot(task_key: str, snapshot: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """保存变量快照到 SQLite，并返回轻量引用标记。"""
    normalized_task_key = str(task_key or "").strip()
    if not normalized_task_key:
        raise ValueError("task_key 不能为空")

    _ensure_schema()
    global_vars, var_sources = _normalize_snapshot(snapshot)
    updated_at = float(time.time())

    rows = []
    for key, value in global_vars.items():
        name = str(key or "").strip()
        if not name:
            continue

        source = var_sources.get(name)
        source_value = _normalize_var_source(source)

        value_text = _serialize_var_value(value)
        rows.append((normalized_task_key, name, value_text, source_value, updated_at))

    with _DB_IO_LOCK:
        conn = _connect()
        try:
            conn.execute("DELETE FROM runtime_vars WHERE task_key = ?", (normalized_task_key,))
            if rows:
                conn.executemany(
                    """
                    INSERT INTO runtime_vars(task_key, var_key, var_value, var_source, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    rows,
                )
            conn.commit()
        finally:
            conn.close()

    return {
        "storage": STORAGE_KIND,
        "task_key": normalized_task_key,
        "count": len(rows),
        "updated_at": updated_at,
    }


def set_runtime_var(task_key: str, key: str, value: Any, source: VarSource = None) -> bool:
    """写入/更新单个运行变量。"""
    normalized_task_key = str(task_key or "").strip()
    normalized_key = str(key or "").strip()
    if not normalized_task_key or not normalized_key:
        return False

    _ensure_schema()
    source_value = _normalize_var_source(source)

    updated_at = float(time.time())
    value_text = _serialize_var_value(value)

    with _DB_IO_LOCK:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO runtime_vars(task_key, var_key, var_value, var_source, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (normalized_task_key, normalized_key, value_text, source_value, updated_at),
            )
            conn.commit()
            return True
        finally:
            conn.close()



def set_runtime_vars(task_key: str, items: Dict[str, Tuple[Any, VarSource]]) -> int:
    """批量写入/更新运行变量，返回写入条数。"""
    normalized_task_key = str(task_key or "").strip()
    if not normalized_task_key:
        return 0

    rows = []
    updated_at = float(time.time())
    for key, payload in (items or {}).items():
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue

        value = None
        source = None
        if isinstance(payload, tuple):
            if len(payload) >= 1:
                value = payload[0]
            if len(payload) >= 2:
                source = payload[1]
        else:
            value = payload

        source_value = _normalize_var_source(source)
        value_text = _serialize_var_value(value)
        rows.append((normalized_task_key, normalized_key, value_text, source_value, updated_at))

    if not rows:
        return 0

    _ensure_schema()
    with _DB_IO_LOCK:
        conn = _connect()
        try:
            conn.executemany(
                """
                INSERT OR REPLACE INTO runtime_vars(task_key, var_key, var_value, var_source, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()
    return len(rows)


def remove_runtime_var(task_key: str, key: str) -> bool:
    """删除单个运行变量。"""
    normalized_task_key = str(task_key or "").strip()
    normalized_key = str(key or "").strip()
    if not normalized_task_key or not normalized_key:
        return False

    _ensure_schema()
    with _DB_IO_LOCK:
        conn = _connect()
        try:
            cursor = conn.execute(
                "DELETE FROM runtime_vars WHERE task_key = ? AND var_key = ?",
                (normalized_task_key, normalized_key),
            )
            conn.commit()
            return bool(getattr(cursor, "rowcount", 0))
        finally:
            conn.close()



def remove_runtime_vars(task_key: str, keys: Any) -> int:
    """批量删除运行变量，返回删除条数。"""
    normalized_task_key = str(task_key or "").strip()
    if not normalized_task_key:
        return 0

    normalized_keys = []
    seen = set()
    for key in (keys or []):
        name = str(key or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        normalized_keys.append(name)

    if not normalized_keys:
        return 0

    _ensure_schema()
    deleted_total = 0
    with _DB_IO_LOCK:
        conn = _connect()
        try:
            batch_size = max(1, int(_RUNTIME_VARS_IN_BATCH))
            for start in range(0, len(normalized_keys), batch_size):
                batch_keys = normalized_keys[start : start + batch_size]
                placeholders = ",".join(["?"] * len(batch_keys))
                params = [normalized_task_key] + batch_keys
                cursor = conn.execute(
                    f"DELETE FROM runtime_vars WHERE task_key = ? AND var_key IN ({placeholders})",
                    params,
                )
                try:
                    deleted_total += int(getattr(cursor, "rowcount", 0) or 0)
                except Exception:
                    pass
            conn.commit()
        finally:
            conn.close()
    return deleted_total


def get_runtime_var(task_key: str, key: str) -> Tuple[bool, Any, VarSource]:
    """按变量名读取（懒加载）。"""
    normalized_task_key = str(task_key or "").strip()
    normalized_key = str(key or "").strip()
    if not normalized_task_key or not normalized_key:
        return False, None, None

    _ensure_schema()
    with _DB_IO_LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                """
                SELECT var_value, var_source
                FROM runtime_vars
                WHERE task_key = ? AND var_key = ?
                """,
                (normalized_task_key, normalized_key),
            ).fetchone()
        finally:
            conn.close()

    if not row:
        return False, None, None

    value_text, source = row
    try:
        value = json.loads(value_text) if value_text is not None else None
    except Exception:
        value = value_text

    source_value = _normalize_var_source(source)
    return True, value, source_value


def get_runtime_vars(task_key: str, keys: Any) -> Dict[str, Tuple[Any, VarSource]]:
    """批量按变量名读取，返回 {var_key: (value, source)}。"""
    normalized_task_key = str(task_key or "").strip()
    if not normalized_task_key:
        return {}

    normalized_keys = []
    seen = set()
    for key in (keys or []):
        name = str(key or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        normalized_keys.append(name)

    if not normalized_keys:
        return {}

    _ensure_schema()
    result: Dict[str, Tuple[Any, VarSource]] = {}
    with _DB_IO_LOCK:
        conn = _connect()
        try:
            batch_size = max(1, int(_RUNTIME_VARS_IN_BATCH))
            for start in range(0, len(normalized_keys), batch_size):
                batch_keys = normalized_keys[start : start + batch_size]
                placeholders = ",".join(["?"] * len(batch_keys))
                params = [normalized_task_key] + batch_keys
                query = (
                    "SELECT var_key, var_value, var_source FROM runtime_vars "
                    f"WHERE task_key = ? AND var_key IN ({placeholders})"
                )
                rows = conn.execute(query, params).fetchall()

                for row in rows or []:
                    if not row or len(row) < 3:
                        continue
                    name = str(row[0] or "").strip()
                    if not name:
                        continue

                    value_text = row[1]
                    try:
                        value = json.loads(value_text) if value_text is not None else None
                    except Exception:
                        value = value_text

                    source = row[2]
                    source_value = _normalize_var_source(source)
                    result[name] = (value, source_value)
        finally:
            conn.close()

    return result


def list_runtime_var_sources(task_key: str) -> Dict[str, VarSource]:
    """仅返回变量名与来源，不加载变量值。"""
    normalized_task_key = str(task_key or "").strip()
    if not normalized_task_key:
        return {}

    _ensure_schema()
    with _DB_IO_LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                """
                SELECT var_key, var_source
                FROM runtime_vars
                WHERE task_key = ?
                """,
                (normalized_task_key,),
            ).fetchall()
        finally:
            conn.close()

    result: Dict[str, VarSource] = {}
    for row in rows or []:
        if not row or len(row) < 2:
            continue
        key = str(row[0] or "").strip()
        if not key:
            continue
        source = row[1]
        result[key] = _normalize_var_source(source)
    return result


def load_runtime_snapshot(task_key: str) -> Tuple[Dict[str, Any], Dict[str, VarSource]]:
    """加载指定任务的完整变量快照。"""
    normalized_task_key = str(task_key or "").strip()
    if not normalized_task_key:
        return {}, {}

    _ensure_schema()
    with _DB_IO_LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                """
                SELECT var_key, var_value, var_source
                FROM runtime_vars
                WHERE task_key = ?
                """,
                (normalized_task_key,),
            ).fetchall()
        finally:
            conn.close()

    global_vars: Dict[str, Any] = {}
    var_sources: Dict[str, VarSource] = {}
    for row in rows or []:
        if not row or len(row) < 3:
            continue
        key = str(row[0] or "").strip()
        if not key:
            continue

        value_text = row[1]
        try:
            value = json.loads(value_text) if value_text is not None else None
        except Exception:
            value = value_text
        global_vars[key] = value

        source = row[2]
        var_sources[key] = _normalize_var_source(source)

    return _sanitize_manifest_shadow_vars(
        normalized_task_key,
        global_vars,
        var_sources,
    )


def clear_runtime_snapshot(task_key: str) -> None:
    normalized_task_key = str(task_key or "").strip()
    if not normalized_task_key:
        return

    _ensure_schema()
    with _DB_IO_LOCK:
        conn = _connect()
        try:
            conn.execute("DELETE FROM runtime_vars WHERE task_key = ?", (normalized_task_key,))
            conn.commit()
        finally:
            conn.close()


def _normalize_global_store_payload(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {
        "version": 1,
        "kdf": None,
        "variables": {},
        "unlock": {},
        "storage": GLOBAL_STORAGE_KIND,
    }
    if not isinstance(data, dict):
        return normalized

    version = data.get("version", 1)
    try:
        normalized["version"] = int(version)
    except Exception:
        normalized["version"] = 1

    kdf = data.get("kdf")
    normalized["kdf"] = kdf if isinstance(kdf, dict) else None

    unlock = data.get("unlock")
    normalized["unlock"] = unlock if isinstance(unlock, dict) else {}

    variables = data.get("variables")
    if isinstance(variables, dict):
        fixed_vars: Dict[str, Dict[str, Any]] = {}
        for key, entry in variables.items():
            name = str(key or "").strip()
            if not name or not isinstance(entry, dict):
                continue
            fixed_vars[name] = dict(entry)
        normalized["variables"] = fixed_vars

    return normalized


def load_global_store_snapshot() -> Tuple[Dict[str, Any], bool]:
    """加载全局变量存储快照。返回 (payload, has_data)。"""
    _ensure_schema()

    has_data = False
    with _DB_IO_LOCK:
        conn = _connect()
        try:
            meta_rows = conn.execute(
                """
                SELECT meta_key, meta_value
                FROM global_var_meta
                """
            ).fetchall()
            var_rows = conn.execute(
                """
                SELECT var_key, var_entry
                FROM global_vars
                """
            ).fetchall()
        finally:
            conn.close()

    payload: Dict[str, Any] = {
        "version": 1,
        "kdf": None,
        "variables": {},
        "unlock": {},
        "storage": GLOBAL_STORAGE_KIND,
    }

    if meta_rows:
        has_data = True
    for row in meta_rows or []:
        if not row or len(row) < 2:
            continue
        key = str(row[0] or "").strip()
        value_text = row[1]
        if not key:
            continue
        try:
            value = json.loads(value_text) if value_text is not None else None
        except Exception:
            value = value_text

        if key == "version":
            try:
                payload["version"] = int(value)
            except Exception:
                payload["version"] = 1
        elif key == "kdf":
            payload["kdf"] = value if isinstance(value, dict) else None
        elif key == "unlock":
            payload["unlock"] = value if isinstance(value, dict) else {}

    variables: Dict[str, Dict[str, Any]] = {}
    if var_rows:
        has_data = True
    for row in var_rows or []:
        if not row or len(row) < 2:
            continue
        name = str(row[0] or "").strip()
        if not name:
            continue
        entry_text = row[1]
        try:
            entry = json.loads(entry_text) if entry_text is not None else {}
        except Exception:
            entry = {}
        if not isinstance(entry, dict):
            entry = {"type": "string", "secret": False, "value": str(entry)}
        variables[name] = entry
    payload["variables"] = variables

    return _normalize_global_store_payload(payload), has_data


def save_global_store_snapshot(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """保存全局变量存储快照到 SQLite。"""
    payload = _normalize_global_store_payload(data)
    updated_at = float(time.time())

    variable_rows = []
    for name, entry in (payload.get("variables") or {}).items():
        key = str(name or "").strip()
        if not key:
            continue
        variable_rows.append((key, _serialize_var_value(entry), updated_at))

    meta_rows = [
        ("version", _serialize_var_value(payload.get("version", 1))),
        ("kdf", _serialize_var_value(payload.get("kdf"))),
        ("unlock", _serialize_var_value(payload.get("unlock") or {})),
        ("storage", _serialize_var_value(GLOBAL_STORAGE_KIND)),
    ]

    _ensure_schema()
    with _DB_IO_LOCK:
        conn = _connect()
        try:
            conn.execute("DELETE FROM global_vars")
            if variable_rows:
                conn.executemany(
                    """
                    INSERT INTO global_vars(var_key, var_entry, updated_at)
                    VALUES (?, ?, ?)
                    """,
                    variable_rows,
                )

            conn.execute("DELETE FROM global_var_meta")
            conn.executemany(
                """
                INSERT INTO global_var_meta(meta_key, meta_value)
                VALUES (?, ?)
                """,
                meta_rows,
            )
            conn.commit()
        finally:
            conn.close()

    payload["storage"] = GLOBAL_STORAGE_KIND
    return payload

