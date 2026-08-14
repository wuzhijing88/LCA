import os
import sys


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


def get_app_root() -> str:
    if getattr(sys, "frozen", False):
        return _to_long_path(os.path.dirname(sys.executable))
    return _to_long_path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_user_data_dir(app_name: str = "LCA") -> str:
    return get_app_root()


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
        return os.path.join(get_app_root(), "config.json")
    return os.path.join(get_app_root(), f"config.instance-{slot}.json")


def get_favorites_path(app_name: str = "LCA") -> str:
    return os.path.join(get_app_root(), "workflow_favorites.json")


def get_images_dir(app_name: str = "LCA") -> str:
    return _ensure_dir(os.path.join(get_app_root(), "images"))


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
        return _ensure_dir(os.path.join(get_app_root(), "logs"))
    return _ensure_dir(os.path.join(get_app_root(), "logs", f"instance-{slot}"))


def get_runtime_data_dir(app_name: str = "LCA") -> str:
    slot = _instance_slot()
    if slot <= 1:
        return _ensure_dir(os.path.join(get_app_root(), "runtime_data"))
    return _ensure_dir(os.path.join(get_app_root(), "runtime_data", f"instance-{slot}"))


def get_workflows_dir(app_name: str = "LCA") -> str:
    return _ensure_dir(os.path.join(get_app_root(), "workflows"))


def get_runtime_state_dir(app_name: str = "LCA") -> str:
    slot = _instance_slot()
    if slot <= 1:
        return _ensure_dir(os.path.join(get_app_root(), "runtime", "state"))
    return _ensure_dir(os.path.join(get_app_root(), "runtime", "state", f"instance-{slot}"))
