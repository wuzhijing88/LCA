# -*- coding: utf-8 -*-
"""Global variable store with optional passphrase encryption."""

from __future__ import annotations

import base64
import copy
import json
import logging
import os
import random
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from utils.app_paths import get_user_data_dir

logger = logging.getLogger(__name__)

DEFAULT_ITERATIONS = 200_000
DEFAULT_VERSION = 1
_RANDOM_DEFAULTS = {
    "mode": "int",
    "min": 0,
    "max": 100,
    "precision": 2,
    "refresh": "per_run",
}
_EXPR_DEFAULTS = {
    "expr": "",
    "refresh": "manual",
}


def _b64encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64decode(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def _crypto_available() -> bool:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC  # noqa: F401
        return True
    except Exception:
        return False


def _protect_local_text(text: str) -> Optional[Dict[str, str]]:
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_byte)),
            ]

        payload = str(text or "").encode("utf-8")
        source_buffer = ctypes.create_string_buffer(payload)
        source_blob = DATA_BLOB(
            len(payload),
            ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)),
        )
        protected_blob = DATA_BLOB()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32

        ok = crypt32.CryptProtectData(
            ctypes.byref(source_blob),
            "LCA remembered unlock",
            None,
            None,
            None,
            0,
            ctypes.byref(protected_blob),
        )
        if not ok:
            return None
        try:
            protected = ctypes.string_at(protected_blob.pbData, protected_blob.cbData)
            return {
                "scheme": "dpapi",
                "value": _b64encode(protected),
            }
        finally:
            if protected_blob.pbData:
                kernel32.LocalFree(protected_blob.pbData)
    except Exception:
        return None


def _unprotect_local_text(token: Any) -> Optional[str]:
    if os.name != "nt" or not isinstance(token, dict):
        return None
    if str(token.get("scheme") or "").strip().lower() != "dpapi":
        return None
    protected_text = str(token.get("value") or "").strip()
    if not protected_text:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_byte)),
            ]

        protected = _b64decode(protected_text)
        protected_buffer = ctypes.create_string_buffer(protected)
        protected_blob = DATA_BLOB(
            len(protected),
            ctypes.cast(protected_buffer, ctypes.POINTER(ctypes.c_byte)),
        )
        plain_blob = DATA_BLOB()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32

        ok = crypt32.CryptUnprotectData(
            ctypes.byref(protected_blob),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(plain_blob),
        )
        if not ok:
            return None
        try:
            plain = ctypes.string_at(plain_blob.pbData, plain_blob.cbData)
            return plain.decode("utf-8")
        finally:
            if plain_blob.pbData:
                kernel32.LocalFree(plain_blob.pbData)
    except Exception:
        return None


def _derive_key(passphrase: str, salt: bytes, iterations: int) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def _encrypt_text(key: bytes, text: str) -> Dict[str, str]:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, text.encode("utf-8"), None)
    return {
        "alg": "aesgcm",
        "nonce": _b64encode(nonce),
        "ciphertext": _b64encode(ciphertext),
    }


def _decrypt_text(key: bytes, enc: Dict[str, str]) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = _b64decode(enc.get("nonce", ""))
    ciphertext = _b64decode(enc.get("ciphertext", ""))
    data = AESGCM(key).decrypt(nonce, ciphertext, None)
    return data.decode("utf-8")


class GlobalVarStore:
    """Global variable store with optional encryption for secret fields."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: Dict[str, Any] = {
            "version": DEFAULT_VERSION,
            "kdf": None,
            "variables": {},
            "unlock": {},
        }
        self._key: Optional[bytes] = None
        self._loaded = False
        self._last_passphrase: Optional[str] = None
        self._revision: int = 0
        self._lock = threading.RLock()

    @property
    def loaded(self) -> bool:
        with self._lock:
            return self._loaded

    @property
    def revision(self) -> int:
        with self._lock:
            return int(self._revision)

    def _bump_revision(self) -> None:
        with self._lock:
            self._revision += 1

    def load(self) -> None:
        loaded_from_db = False
        try:
            from task_workflow.runtime_var_store import load_global_store_snapshot

            payload, has_data = load_global_store_snapshot()
            if has_data and isinstance(payload, dict):
                with self._lock:
                    self.data = payload
                loaded_from_db = True
        except Exception as exc:
            logger.warning("从数据库加载全局变量失败：%s", exc)

        if not loaded_from_db and self.path.exists():
            try:
                with self.path.open("r", encoding="utf-8") as f:
                    payload = json.load(f)
                if isinstance(payload, dict):
                    with self._lock:
                        self.data = payload
                try:
                    from task_workflow.runtime_var_store import save_global_store_snapshot

                    with self._lock:
                        data_snapshot = copy.deepcopy(self.data)
                    migrated = save_global_store_snapshot(data_snapshot)
                    if isinstance(migrated, dict):
                        with self._lock:
                            self.data = migrated
                except Exception as migrate_err:
                    logger.warning("迁移旧版全局变量文件失败：%s", migrate_err)
            except Exception as exc:
                logger.warning("加载旧版全局变量文件失败：%s", exc)
        with self._lock:
            self._loaded = True
        self._bump_revision()

    def save(self) -> None:
        try:
            from task_workflow.runtime_var_store import save_global_store_snapshot

            with self._lock:
                data_snapshot = copy.deepcopy(self.data)
            payload = save_global_store_snapshot(data_snapshot)
            if isinstance(payload, dict):
                with self._lock:
                    self.data = payload
        except Exception as exc:
            logger.warning("保存全局变量到数据库失败：%s", exc)

    def has_encrypted(self) -> bool:
        with self._lock:
            variables = self.data.get("variables", {})
            if not isinstance(variables, dict):
                return False
            return any(isinstance(entry, dict) and "enc" in entry for entry in variables.values())

    def is_locked(self) -> bool:
        with self._lock:
            variables = self.data.get("variables", {})
            if not isinstance(variables, dict):
                return False
            has_encrypted = any(
                isinstance(entry, dict) and "enc" in entry
                for entry in variables.values()
            )
            return bool(has_encrypted and self._key is None)

    def _get_kdf_params(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            kdf_data = self.data.get("kdf")
            if isinstance(kdf_data, dict) and kdf_data.get("salt") and kdf_data.get("iterations"):
                return dict(kdf_data)
            return None

    def _normalize_random_config(self, config: Any) -> Dict[str, Any]:
        if not isinstance(config, dict):
            config = {}
        mode = str(config.get("mode", _RANDOM_DEFAULTS["mode"])).lower()
        if mode not in ("int", "float"):
            mode = _RANDOM_DEFAULTS["mode"]
        refresh = str(config.get("refresh", _RANDOM_DEFAULTS["refresh"])).lower()
        if refresh not in ("manual", "on_read", "per_run"):
            refresh = _RANDOM_DEFAULTS["refresh"]
        try:
            min_value = float(config.get("min", _RANDOM_DEFAULTS["min"]))
        except (TypeError, ValueError):
            min_value = float(_RANDOM_DEFAULTS["min"])
        try:
            max_value = float(config.get("max", _RANDOM_DEFAULTS["max"]))
        except (TypeError, ValueError):
            max_value = float(_RANDOM_DEFAULTS["max"])
        if max_value < min_value:
            min_value, max_value = max_value, min_value
        try:
            precision = int(config.get("precision", _RANDOM_DEFAULTS["precision"]))
        except (TypeError, ValueError):
            precision = _RANDOM_DEFAULTS["precision"]
        precision = max(0, min(6, precision))
        return {
            "mode": mode,
            "min": min_value,
            "max": max_value,
            "precision": precision,
            "refresh": refresh,
        }

    def _normalize_expression_config(self, config: Any) -> Dict[str, Any]:
        if not isinstance(config, dict):
            config = {"expr": str(config) if config is not None else ""}
        expr = str(config.get("expr", _EXPR_DEFAULTS["expr"])).strip()
        refresh = str(config.get("refresh", _EXPR_DEFAULTS["refresh"])).lower()
        if refresh not in ("manual", "on_read", "per_run"):
            refresh = _EXPR_DEFAULTS["refresh"]
        normalized = {"expr": expr, "refresh": refresh}
        if "initial" in config:
            normalized["initial"] = config.get("initial")
        return normalized

    def _normalize_var_type(self, raw_type: Any) -> str:
        text = str(raw_type or "string").strip().lower()
        mapping = {
            "text": "string",
            "str": "string",
            "string": "string",
            "int": "int",
            "integer": "int",
            "float": "float",
            "double": "float",
            "bool": "bool",
            "boolean": "bool",
            "list": "list",
            "array": "list",
            "dict": "dict",
            "object": "dict",
            "map": "dict",
            "null": "null",
            "none": "null",
            "secret": "secret",
            "random": "random",
            "expression": "expression",
        }
        return mapping.get(text, "string")

    def _generate_random_value(self, config: Dict[str, Any]) -> Any:
        config = self._normalize_random_config(config)
        min_value = config["min"]
        max_value = config["max"]
        if config["mode"] == "int":
            return int(random.randint(int(min_value), int(max_value)))
        value = random.uniform(min_value, max_value)
        return round(value, config["precision"])

    def _get_random_value(self, name: str, entry: Dict[str, Any]) -> Any:
        config = self._normalize_random_config(entry.get("config") or {})
        refresh = config.get("refresh", _RANDOM_DEFAULTS["refresh"])
        if refresh == "on_read" or "value" not in entry:
            entry["value"] = self._generate_random_value(config)
            entry["ts"] = time.time()
        return entry.get("value")

    def _ensure_kdf(self, passphrase: str) -> bytes:
        kdf_data = self._get_kdf_params()
        if not kdf_data:
            salt = os.urandom(16)
            iterations = DEFAULT_ITERATIONS
            kdf_data = {
                "method": "pbkdf2_sha256",
                "salt": _b64encode(salt),
                "iterations": iterations,
            }
            with self._lock:
                self.data["kdf"] = dict(kdf_data)
        else:
            salt = _b64decode(kdf_data.get("salt", ""))
            iterations = int(kdf_data.get("iterations", DEFAULT_ITERATIONS))
        return _derive_key(passphrase, salt, iterations)

    def unlock(self, passphrase: str) -> bool:
        with self._lock:
            has_encrypted = any(
                isinstance(entry, dict) and "enc" in entry
                for entry in (self.data.get("variables", {}) or {}).values()
            )
            if not has_encrypted:
                self._key = None
                return True
            if not _crypto_available():
                return False
        try:
            key = self._ensure_kdf(passphrase)
            with self._lock:
                variables = self.data.get("variables", {})
                for entry in variables.values():
                    if isinstance(entry, dict) and "enc" in entry:
                        _decrypt_text(key, entry["enc"])
                        break
                old_locked = self._key is None
                self._key = key
                self._last_passphrase = passphrase
            if old_locked:
                self._bump_revision()
            return True
        except Exception:
            return False

    def lock(self) -> None:
        with self._lock:
            was_locked = self._key is None
            self._key = None
        if not was_locked:
            self._bump_revision()

    def _get_unlock_config(self) -> Dict[str, Any]:
        with self._lock:
            data = self.data.get("unlock")
            if isinstance(data, dict):
                return dict(data)
            return {}

    def remember_unlock_enabled(self) -> bool:
        cfg = self._get_unlock_config()
        return bool(cfg.get("remember"))

    def get_remembered_passphrase(self) -> Optional[str]:
        cfg = self._get_unlock_config()
        token = cfg.get("passphrase")
        if not token:
            return None
        if isinstance(token, dict):
            return _unprotect_local_text(token)
        try:
            return _b64decode(str(token)).decode("utf-8")
        except Exception:
            return None

    def get_cached_passphrase(self) -> Optional[str]:
        with self._lock:
            return self._last_passphrase

    def set_remember_unlock(self, remember: bool, passphrase: Optional[str] = None) -> bool:
        with self._lock:
            cfg = self.data.setdefault("unlock", {})
            cfg["remember"] = bool(remember)
            if not remember:
                cfg.pop("passphrase", None)
                return True
            if passphrase is None:
                passphrase = self._last_passphrase
            if not passphrase:
                return False
            protected = _protect_local_text(passphrase)
            if not isinstance(protected, dict):
                return False
            cfg["passphrase"] = protected
            return True

    def try_auto_unlock(self) -> bool:
        if not self.is_locked():
            return True
        passphrase = self.get_remembered_passphrase()
        if not passphrase:
            return False
        return self.unlock(passphrase)

    def is_secret(self, name: str) -> bool:
        with self._lock:
            entry = self.data.get("variables", {}).get(name, {})
            if not isinstance(entry, dict):
                return False
            return bool(entry.get("secret") or entry.get("type") == "secret" or "enc" in entry)

    def get_value(self, name: str) -> Any:
        with self._lock:
            entry = self.data.get("variables", {}).get(name, {})
            if not isinstance(entry, dict):
                return None
            if "enc" in entry:
                if self._key is None:
                    return None
                try:
                    return _decrypt_text(self._key, entry["enc"])
                except Exception:
                    return None
            if entry.get("type") == "random":
                return self._get_random_value(name, entry)
            if entry.get("type") == "expression":
                return entry.get("value")
            return entry.get("value")

    def set_value(
        self,
        name: str,
        value: Any,
        *,
        var_type: str = "text",
        secret: bool = False,
        encrypt: bool = False,
        passphrase: Optional[str] = None,
    ) -> bool:
        if not name:
            return False
        var_type = self._normalize_var_type(var_type)
        entry: Dict[str, Any] = {
            "type": var_type,
            "secret": bool(secret),
        }
        if var_type == "random":
            config = value if isinstance(value, dict) else {}
            entry["config"] = self._normalize_random_config(config)
            entry["value"] = self._generate_random_value(entry["config"])
            entry["ts"] = time.time()
            with self._lock:
                self.data.setdefault("variables", {})[name] = entry
            self._bump_revision()
            return True
        if var_type == "expression":
            config = value if isinstance(value, dict) else {"expr": str(value) if value is not None else ""}
            entry["config"] = self._normalize_expression_config(config)
            entry["value"] = entry["config"].get("initial")
            entry["ts"] = time.time()
            with self._lock:
                self.data.setdefault("variables", {})[name] = entry
            self._bump_revision()
            return True
        if encrypt:
            if not _crypto_available():
                return False
            if passphrase is None:
                return False
            try:
                key = self._ensure_kdf(passphrase)
                with self._lock:
                    self._key = key
                entry["enc"] = _encrypt_text(key, str(value))
            except Exception:
                return False
        else:
            if var_type == "null":
                entry["value"] = None
            else:
                entry["value"] = value
        with self._lock:
            self.data.setdefault("variables", {})[name] = entry
        self._bump_revision()
        return True

    def refresh_random_vars(self, refresh_mode: str = "per_run") -> int:
        refresh_mode = str(refresh_mode or "per_run").lower()
        with self._lock:
            variables = self.data.get("variables", {})
            if not isinstance(variables, dict):
                return 0
            count = 0
            for entry in variables.values():
                if not isinstance(entry, dict):
                    continue
                if entry.get("type") != "random":
                    continue
                config = self._normalize_random_config(entry.get("config") or {})
                if config.get("refresh") != refresh_mode:
                    continue
                entry["value"] = self._generate_random_value(config)
                entry["ts"] = time.time()
                count += 1
        if count > 0:
            self._bump_revision()
        return count

    def delete(self, name: str) -> None:
        removed = None
        with self._lock:
            variables = self.data.get("variables", {})
            if isinstance(variables, dict):
                removed = variables.pop(name, None)
        if removed is not None:
            self._bump_revision()

    def clear(self) -> None:
        should_bump = False
        with self._lock:
            variables = self.data.get("variables", {})
            self.data["variables"] = {}
            should_bump = isinstance(variables, dict) and bool(variables)
        if should_bump:
            self._bump_revision()

    def list_names(self) -> list:
        with self._lock:
            variables = self.data.get("variables", {})
            if isinstance(variables, dict):
                return sorted(variables.keys(), key=lambda value: str(value))
            return []

    def apply_to_context(self, context, *, force: bool = False) -> bool:
        if not context:
            return False
        with self._lock:
            variables = self.data.get("variables", {})
            if not isinstance(variables, dict):
                variables = {}
            revision = int(self._revision)
            is_locked = any(
                isinstance(entry, dict) and "enc" in entry
                for entry in variables.values()
            ) and self._key is None
            names = list(variables.keys())

        sync_token = (revision, bool(is_locked), len(names))
        if not force and getattr(context, "_global_store_sync_token", None) == sync_token:
            return False

        global_vars_payload = {}
        global_sources_payload = {}
        for name in names:
            value = self.get_value(name)
            key = str(name)
            global_vars_payload[key] = value
            global_sources_payload[key] = "global"

        context.import_vars(
            {
                "global_vars": global_vars_payload,
                "var_sources": global_sources_payload,
            }
        )
        try:
            context._global_store_sync_token = sync_token
        except Exception:
            pass
        return True


_GLOBAL_STORE: Optional[GlobalVarStore] = None
_GLOBAL_STORE_LOCK = threading.RLock()


def _resolve_global_store_path() -> Path:
    user_store_path = Path(get_user_data_dir("LCA")) / "config" / "credentials.json"
    legacy_store_path = Path(__file__).resolve().parent.parent / "config" / "credentials.json"

    if not user_store_path.exists() and legacy_store_path.exists():
        try:
            user_store_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(legacy_store_path), str(user_store_path))
        except Exception as exc:
            logger.warning("迁移旧版全局变量存储失败：%s", exc)

    return user_store_path


def get_global_store() -> GlobalVarStore:
    global _GLOBAL_STORE
    with _GLOBAL_STORE_LOCK:
        if _GLOBAL_STORE is None:
            store_path = _resolve_global_store_path()
            _GLOBAL_STORE = GlobalVarStore(store_path)
        return _GLOBAL_STORE


def ensure_global_context_loaded() -> GlobalVarStore:
    store = get_global_store()
    if not store.loaded:
        with _GLOBAL_STORE_LOCK:
            if not store.loaded:
                store.load()
    store.try_auto_unlock()
    try:
        from task_workflow.workflow_context import get_workflow_context

        context = get_workflow_context("global")
        store.apply_to_context(context)
    except Exception as exc:
        logger.debug("应用全局变量到上下文失败：%s", exc)
    return store
