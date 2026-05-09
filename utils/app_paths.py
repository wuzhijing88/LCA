import os
import sys
import shutil
from typing import Iterable, Optional


def _to_long_path(path: str) -> str:
    if not path or os.name != "nt" or "~" not in path:
        return path
    try:
        import ctypes
        get_long = ctypes.windll.kernel32.GetLongPathNameW
        get_long.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
        get_long.restype = ctypes.c_uint

        required = get_long(path, None, 0)
        if required == 0:
            return path
        buffer = ctypes.create_unicode_buffer(required)
        result = get_long(path, buffer, required)
        if result == 0:
            return path
        return buffer.value or path
    except Exception:
        return path


def get_app_root() -> str:
    if getattr(sys, "frozen", False):
        return _to_long_path(os.path.dirname(sys.executable))
    return _to_long_path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_legacy_user_data_dir(app_name: str = "LCA") -> str:
    base_dir = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if not base_dir:
        base_dir = os.path.expanduser("~")
    return os.path.join(base_dir, app_name)


def get_user_data_dir(app_name: str = "LCA") -> str:
    path = get_app_root()
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    return path


def _ensure_dir(path: str) -> str:
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    return path


def _get_runtime_root(app_name: str = "LCA") -> str:
    return get_app_root()


def _iter_legacy_names(filename_or_names: str | Iterable[str]) -> Iterable[str]:
    if isinstance(filename_or_names, str):
        yield filename_or_names
        return
    for item in filename_or_names:
        if item:
            yield str(item)


def _migrate_file(filename_or_names: str | Iterable[str], new_path: str, app_name: str = "LCA") -> None:
    if os.path.exists(new_path):
        return

    app_root = get_app_root()
    cwd = os.getcwd()
    legacy_user_data_dir = get_legacy_user_data_dir(app_name)
    try:
        argv_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    except Exception:
        argv_dir = ""

    for legacy_name in _iter_legacy_names(filename_or_names):
        legacy_paths = [
            os.path.join(app_root, legacy_name),
            os.path.join(legacy_user_data_dir, legacy_name),
        ]
        if argv_dir:
            legacy_paths.append(os.path.join(argv_dir, legacy_name))
        if not getattr(sys, "frozen", False):
            legacy_paths.append(os.path.join(cwd, legacy_name))

        for legacy_path in legacy_paths:
            if not legacy_path or legacy_path == new_path:
                continue
            if os.path.exists(legacy_path):
                try:
                    os.makedirs(os.path.dirname(new_path), exist_ok=True)
                    shutil.copy2(legacy_path, new_path)
                    return
                except Exception:
                    return


def get_config_path(app_name: str = "LCA") -> str:
    new_path = os.path.join(get_app_root(), "config.json")
    _migrate_file(["config.json", "config/default_config.json"], new_path, app_name=app_name)
    return new_path


def get_favorites_path(app_name: str = "LCA") -> str:
    new_path = os.path.join(get_app_root(), "workflow_favorites.json")
    _migrate_file("workflow_favorites.json", new_path, app_name=app_name)
    return new_path


def get_images_dir(app_name: str = "LCA") -> str:
    return _ensure_dir(os.path.join(get_app_root(), "images"))


def normalize_workflow_image_path(raw_path: str, app_name: str = "LCA") -> str:
    value = str(raw_path or "").strip()
    if not value or value.startswith("memory://"):
        return value

    normalized_text = value.replace("\\", "/")
    while normalized_text.startswith("./"):
        normalized_text = normalized_text[2:]

    if normalized_text.lower().startswith("ui/images/"):
        suffix = normalized_text[len("ui/images/"):].lstrip("/")
        return f"images/{suffix}" if suffix else "images"

    if normalized_text.lower().startswith("images/"):
        suffix = normalized_text[len("images/"):].lstrip("/")
        return f"images/{suffix}" if suffix else "images"

    if not os.path.isabs(value):
        return normalized_text

    absolute_value = os.path.abspath(value)
    candidate_roots = [
        get_images_dir(app_name),
        os.path.join(get_app_root(), "ui", "images"),
    ]
    absolute_normcase = os.path.normcase(absolute_value)

    for root in candidate_roots:
        root_abs = os.path.abspath(root)
        root_normcase = os.path.normcase(root_abs)
        root_prefix = root_normcase + os.sep
        if absolute_normcase == root_normcase:
            return "images"
        if absolute_normcase.startswith(root_prefix):
            relative_path = os.path.relpath(absolute_value, root_abs).replace(os.sep, "/")
            return f"images/{relative_path}"

    return absolute_value


def get_resource_root() -> str:
    return _ensure_dir(os.path.join(get_app_root(), "resources"))


def get_resource_path(*parts: str) -> str:
    return os.path.join(get_resource_root(), *parts)


def get_logs_dir(app_name: str = "LCA") -> str:
    return _ensure_dir(os.path.join(get_app_root(), "logs"))


def get_runtime_data_dir(app_name: str = "LCA") -> str:
    return _ensure_dir(os.path.join(get_app_root(), "runtime_data"))


def get_workflows_dir(app_name: str = "LCA") -> str:
    return _ensure_dir(os.path.join(get_app_root(), "workflows"))


def get_runtime_state_dir(app_name: str = "LCA") -> str:
    return _ensure_dir(os.path.join(get_app_root(), "runtime", "state"))


def get_hardware_id_path(app_name: str = "LCA") -> str:
    new_path = os.path.join(get_runtime_state_dir(app_name), "hardware_id.txt")
    _migrate_file(["runtime/state/hardware_id.txt", "hardware_id.txt"], new_path, app_name=app_name)
    return new_path


def get_license_cache_path(app_name: str = "LCA") -> str:
    new_path = os.path.join(get_runtime_state_dir(app_name), "license.dat")
    _migrate_file(["license.dat", os.path.join("ui", "license.dat")], new_path, app_name=app_name)
    return new_path
