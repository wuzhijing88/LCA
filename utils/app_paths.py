import os
import sys


_PYTHON_LAUNCHER_NAMES = {"python.exe", "pythonw.exe", "py.exe", "pyw.exe"}


def _to_long_path(path: str) -> str:
    if not path or os.name != "nt" or "~" not in path:
        return path

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


def _is_python_launcher(path: str) -> bool:
    return os.path.basename(str(path or "")).lower() in _PYTHON_LAUNCHER_NAMES


def _is_existing_app_executable(path: str) -> bool:
    candidate = str(path or "").strip()
    if not candidate or not os.path.isfile(candidate):
        return False
    if _is_python_launcher(candidate):
        return False
    if os.name == "nt":
        return candidate.lower().endswith(".exe")
    return os.access(candidate, os.X_OK)


def _windows_module_filename() -> str:
    if os.name != "nt":
        return ""
    try:
        import ctypes

        buffer = ctypes.create_unicode_buffer(32768)
        length = ctypes.windll.kernel32.GetModuleFileNameW(None, buffer, len(buffer))
        if not length:
            return ""
        return _to_long_path(os.path.abspath(buffer.value))
    except Exception:
        return ""


def is_packaged_runtime() -> bool:
    if bool(getattr(sys, "frozen", False)):
        return True
    for module_name in ("__main__", __name__):
        module = sys.modules.get(module_name)
        if module is not None and hasattr(module, "__compiled__"):
            return True
    return False


def resolve_running_executable() -> str:
    """Resolve the real process image, not Nuitka's compile-time sys.executable."""
    candidates = []
    module_filename = _windows_module_filename()
    if module_filename:
        candidates.append(module_filename)

    argv0 = str(sys.argv[0] if sys.argv else "").strip()
    if argv0:
        candidates.append(_to_long_path(os.path.abspath(argv0)))

    executable = str(sys.executable or "").strip()
    if executable:
        candidates.append(_to_long_path(os.path.abspath(executable)))

    seen = set()
    for candidate in candidates:
        normalized = os.path.normcase(candidate)
        if not candidate or normalized in seen:
            continue
        seen.add(normalized)
        if _is_existing_app_executable(candidate):
            return candidate
    return ""


def get_app_root() -> str:
    if is_packaged_runtime():
        frozen_executable = str(sys.executable or "").strip()
        if frozen_executable and not _is_python_launcher(frozen_executable):
            return _to_long_path(os.path.dirname(os.path.abspath(frozen_executable)))
        executable = resolve_running_executable()
        if executable:
            return _to_long_path(os.path.dirname(executable))
        argv0 = str(sys.argv[0] if sys.argv else "").strip()
        if argv0:
            return _to_long_path(os.path.dirname(os.path.abspath(argv0)))
        return _to_long_path(os.path.dirname(os.path.abspath(sys.executable or ".")))
    return _to_long_path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_user_data_dir(app_name: str = "LCA") -> str:
    override = str(os.getenv("LCA_USER_DATA_DIR", "") or "").strip()
    if override:
        return _ensure_dir(_to_long_path(os.path.abspath(os.path.expandvars(override))))
    portable = str(os.getenv("LCA_PORTABLE", "") or "").strip().lower()
    if portable in {"1", "true", "yes", "on"}:
        return _ensure_dir(get_app_root())
    local_app_data = str(os.getenv("LOCALAPPDATA", "") or "").strip()
    if not local_app_data:
        local_app_data = os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return _ensure_dir(
        _to_long_path(os.path.join(os.path.abspath(local_app_data), str(app_name or "LCA")))
    )


def _ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def _instance_slot() -> int:
    try:
        from utils.instance_runtime import get_instance_slot

        return int(get_instance_slot())
    except Exception:
        return 1


def get_config_path(app_name: str = "LCA") -> str:
    slot = _instance_slot()
    if slot <= 1:
        return os.path.join(get_user_data_dir(app_name), "config.json")
    return os.path.join(get_user_data_dir(app_name), f"config.instance-{slot}.json")


def get_favorites_path(app_name: str = "LCA") -> str:
    return os.path.join(get_user_data_dir(app_name), "workflow_favorites.json")


def get_images_dir(app_name: str = "LCA") -> str:
    return _ensure_dir(os.path.join(get_user_data_dir(app_name), "images"))


def get_dicts_dir(app_name: str = "LCA") -> str:
    return _ensure_dir(os.path.join(get_images_dir(app_name), "dicts"))


def get_sounds_dir(app_name: str = "LCA") -> str:
    return _ensure_dir(os.path.join(get_user_data_dir(app_name), "sounds"))


def get_maps_dir(app_name: str = "LCA") -> str:
    return _ensure_dir(os.path.join(get_user_data_dir(app_name), "maps"))


def normalize_workflow_image_path(raw_path: str, app_name: str = "LCA") -> str:
    value = str(raw_path or "").strip()
    if not value or value.startswith("memory://"):
        return value

    normalized_text = value.replace("\\", "/")
    while normalized_text.startswith("./"):
        normalized_text = normalized_text[2:]

    if normalized_text.lower().startswith("images/"):
        suffix = normalized_text[len("images/"):].lstrip("/")
        return f"images/{suffix}" if suffix else "images"

    if not os.path.isabs(value):
        return normalized_text

    absolute_value = os.path.abspath(value)
    images_root = os.path.abspath(get_images_dir(app_name))
    absolute_normcase = os.path.normcase(absolute_value)
    images_normcase = os.path.normcase(images_root)
    if absolute_normcase == images_normcase:
        return "images"
    images_prefix = images_normcase + os.sep
    if absolute_normcase.startswith(images_prefix):
        relative_path = os.path.relpath(absolute_value, images_root).replace(os.sep, "/")
        return f"images/{relative_path}"
    return absolute_value


def get_resource_root() -> str:
    return _ensure_dir(os.path.join(get_app_root(), "resources"))


def get_resource_path(*parts: str) -> str:
    return os.path.join(get_resource_root(), *parts)


def get_logs_dir(app_name: str = "LCA") -> str:
    slot = _instance_slot()
    if slot <= 1:
        return _ensure_dir(os.path.join(get_user_data_dir(app_name), "logs"))
    return _ensure_dir(os.path.join(get_user_data_dir(app_name), "logs", f"instance-{slot}"))


def get_runtime_data_dir(app_name: str = "LCA") -> str:
    slot = _instance_slot()
    if slot <= 1:
        return _ensure_dir(os.path.join(get_user_data_dir(app_name), "runtime_data"))
    return _ensure_dir(os.path.join(get_user_data_dir(app_name), "runtime_data", f"instance-{slot}"))


def get_workflows_dir(app_name: str = "LCA") -> str:
    return _ensure_dir(os.path.join(get_user_data_dir(app_name), "workflows"))


def get_runtime_state_dir(app_name: str = "LCA") -> str:
    slot = _instance_slot()
    if slot <= 1:
        return _ensure_dir(os.path.join(get_user_data_dir(app_name), "runtime", "state"))
    return _ensure_dir(os.path.join(get_user_data_dir(app_name), "runtime", "state", f"instance-{slot}"))
