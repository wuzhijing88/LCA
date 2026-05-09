from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app_core.client_identity import attempt_client_registration
from app_core.license_runtime import (
    bind_license_to_hwid,
    enforce_online_validation,
    set_validation_session,
    validate_license_with_server_v2,
)
from app_core.license_store import (
    clear_local_license,
    has_local_license_cache,
    load_local_license,
)

ERROR_TITLE = "\u9519\u8bef"
NETWORK_ERROR_TITLE = "\u7f51\u7edc\u9519\u8bef"
PLUGIN_LICENSE_REQUIRED_TITLE = "\u63d2\u4ef6\u6a21\u5f0f\u9700\u8981\u6388\u6743"
PLUGIN_LICENSE_FAILED_TITLE = "\u63d2\u4ef6\u6388\u6743\u9a8c\u8bc1\u5931\u8d25"
ACCOUNT_BANNED_TITLE = "\u8d26\u53f7\u5df2\u88ab\u5c01\u7981"
LICENSE_EMPTY_TITLE = "\u6388\u6743\u7801\u4e3a\u7a7a"
CACHE_CLEARED_SUFFIX = "\n\n\u672c\u5730\u6388\u6743\u7f13\u5b58\u5df2\u6e05\u7406\u3002"


@dataclass(frozen=True)
class PluginActivationResult:
    success: bool
    title: str
    message: str
    status_code: int = 0
    license_type: str = "unknown"
    validation_enabled: bool = True
    requires_license_input: bool = False
    cache_cleared: bool = False


def _result(
    *,
    success: bool,
    title: str = "",
    message: str = "",
    status_code: int = 0,
    license_type: str = "unknown",
    validation_enabled: bool = True,
    requires_license_input: bool = False,
    cache_cleared: bool = False,
) -> PluginActivationResult:
    return PluginActivationResult(
        success=success,
        title=title,
        message=message,
        status_code=status_code,
        license_type=license_type,
        validation_enabled=validation_enabled,
        requires_license_input=requires_license_input,
        cache_cleared=cache_cleared,
    )


def _close_session_quietly(session: Optional[object]) -> None:
    if session is None:
        return
    try:
        session.close()
    except Exception:
        pass


def _build_validation_failure_message(
    status_code: int,
    extra_message: str = "",
    bind_attempted: bool = False,
) -> str:
    if status_code == 401:
        base_message = (
            "\u6388\u6743\u7801\u65e0\u6548\u3001\u5df2\u8fc7\u671f\u3001"
            "\u5df2\u7981\u7528\u6216\u4e0e\u5f53\u524d\u673a\u5668\u4e0d\u5339\u914d\u3002"
        )
    elif status_code == 403:
        base_message = "\u670d\u52a1\u5668\u62d2\u7edd\u672c\u6b21\u6388\u6743\u9a8c\u8bc1\u3002"
    elif status_code == 503:
        base_message = "\u5f53\u524d\u7f51\u7edc\u4e0d\u53ef\u7528\uff0c\u65e0\u6cd5\u5b8c\u6210\u6388\u6743\u9a8c\u8bc1\u3002"
    elif status_code == 400:
        base_message = "\u6388\u6743\u7801\u683c\u5f0f\u65e0\u6548\u6216\u8fd0\u884c\u65f6\u6821\u9a8c\u672a\u901a\u8fc7\u3002"
    elif status_code == 0:
        base_message = "\u65e0\u6cd5\u8fde\u63a5\u6388\u6743\u670d\u52a1\u5668\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002"
    else:
        base_message = (
            f"\u6388\u6743\u9a8c\u8bc1\u5931\u8d25\uff08\u72b6\u6001\u7801\uff1a{status_code}\uff09\u3002"
        )

    if bind_attempted:
        base_message = (
            f"{base_message}\n"
            "\u5df2\u5c1d\u8bd5\u81ea\u52a8\u7ed1\u5b9a\uff0c\u4f46\u672a\u6210\u529f\u3002"
        )
    if extra_message:
        base_message = f"{base_message}\n{extra_message}"
    return base_message


def _should_clear_cached_license(status_code: int) -> bool:
    return int(status_code or 0) in {400, 401, 403, 404, 409}


def _normalize_status_code(value: object, default: int = 0) -> int:
    try:
        return int(value or 0)
    except Exception:
        return int(default)


def _normalize_license_type(value: object) -> str:
    text = str(value or "").strip()
    return text or "unknown"


def _normalize_registration_result(result: object) -> dict:
    return result if isinstance(result, dict) else {}


def _normalize_online_validation_result(result: object) -> tuple[bool, int, str]:
    if not isinstance(result, (tuple, list)):
        return False, 503, "unknown"

    items = list(result) + [None, None, None]
    return (
        bool(items[0]),
        _normalize_status_code(items[1]),
        _normalize_license_type(items[2]),
    )


def _normalize_server_validation_result(result: object) -> tuple[bool, int, str, dict]:
    if not isinstance(result, (tuple, list)):
        return False, 503, "unknown", {}

    items = list(result) + [None, None, None, None]
    extra_info = items[3] if isinstance(items[3], dict) else {}
    return (
        bool(items[0]),
        _normalize_status_code(items[1]),
        _normalize_license_type(items[2]),
        extra_info,
    )


def _safe_register_client_for_plugin_mode(hardware_id: str) -> dict:
    try:
        return _normalize_registration_result(_register_client_for_plugin_mode(hardware_id))
    except Exception:
        return {}


def _safe_enforce_online_validation(hardware_id: str, license_key: str) -> tuple[bool, int, str]:
    try:
        return _normalize_online_validation_result(
            enforce_online_validation(hardware_id, license_key)
        )
    except Exception:
        return False, 503, "unknown"


def _safe_validate_license_with_server(
    hardware_id: str,
    license_key: str,
) -> tuple[bool, int, str, dict]:
    try:
        return _normalize_server_validation_result(
            validate_license_with_server_v2(hardware_id, license_key)
        )
    except Exception:
        return False, 503, "unknown", {}


def _safe_bind_license_to_hwid(
    hardware_id: str,
    license_key: str,
    session: object,
) -> bool:
    try:
        return bool(bind_license_to_hwid(hardware_id, license_key, session))
    except Exception:
        return False


def _register_client_for_plugin_mode(hardware_id: str) -> dict:
    return attempt_client_registration(hardware_id, None)


def prepare_plugin_mode_activation(hardware_id: str) -> PluginActivationResult:
    normalized_hardware_id = str(hardware_id or "").strip()
    if len(normalized_hardware_id) != 64:
        return _result(
            success=False,
            title=ERROR_TITLE,
            message="\u65e0\u6cd5\u83b7\u53d6\u786c\u4ef6ID\uff0c\u8bf7\u68c0\u67e5\u7cfb\u7edf\u73af\u5883\u3002",
        )

    set_validation_session()
    return _result(
        success=True,
        status_code=200,
        license_type="LOCAL_ONLY",
        validation_enabled=False,
    )

    registration_result = _safe_register_client_for_plugin_mode(normalized_hardware_id)
    if not registration_result.get("success", False):
        if registration_result.get("is_banned", False):
            ban_reason = str(registration_result.get("ban_reason") or "\u672a\u63d0\u4f9b\u539f\u56e0").strip()
            return _result(
                success=False,
                title=ACCOUNT_BANNED_TITLE,
                message=(
                    "\u60a8\u7684\u786c\u4ef6ID\u5df2\u88ab\u5c01\u7981\uff0c\u65e0\u6cd5\u542f\u7528\u63d2\u4ef6\u6a21\u5f0f\u3002"
                    f"\n\n\u5c01\u7981\u539f\u56e0\uff1a{ban_reason}"
                ),
            )
        return _result(
            success=False,
            title=NETWORK_ERROR_TITLE,
            message="\u65e0\u6cd5\u8fde\u63a5\u5230\u670d\u52a1\u5668\uff0c\u8bf7\u68c0\u67e5\u7f51\u7edc\u8fde\u63a5\u3002",
        )

    validation_enabled = bool(registration_result.get("license_validation_enabled", True))
    if not validation_enabled:
        return _result(success=True, validation_enabled=False)

    cache_exists = has_local_license_cache()
    license_key = load_local_license()
    if not license_key:
        if cache_exists:
            cache_cleared = clear_local_license()
            message = (
                "\u672c\u5730\u6388\u6743\u6587\u4ef6\u65e0\u6cd5\u89e3\u5bc6\u6216\u5df2\u635f\u574f\uff0c"
                "\u8bf7\u91cd\u65b0\u8f93\u5165\u6388\u6743\u7801\u3002"
            )
            if cache_cleared:
                message = f"{message}{CACHE_CLEARED_SUFFIX}"
            return _result(
                success=False,
                title=PLUGIN_LICENSE_FAILED_TITLE,
                message=message,
                cache_cleared=cache_cleared,
            )
        return _result(
            success=False,
            title=PLUGIN_LICENSE_REQUIRED_TITLE,
            message="\u542f\u7528\u63d2\u4ef6\u6a21\u5f0f\u9700\u8981\u6709\u6548\u7684\u6388\u6743\u7801\u3002",
            requires_license_input=True,
            validation_enabled=True,
        )

    is_valid, status_code, license_type = _safe_enforce_online_validation(
        normalized_hardware_id,
        license_key,
    )
    if is_valid:
        return _result(
            success=True,
            status_code=status_code,
            license_type=license_type,
            validation_enabled=True,
        )

    cache_cleared = False
    if _should_clear_cached_license(status_code):
        cache_cleared = clear_local_license()
    message = _build_validation_failure_message(status_code)
    if cache_cleared:
        message = f"{message}{CACHE_CLEARED_SUFFIX}"
    return _result(
        success=False,
        title=PLUGIN_LICENSE_FAILED_TITLE,
        message=message,
        status_code=status_code,
        validation_enabled=True,
        cache_cleared=cache_cleared,
    )


def validate_plugin_license_key(
    hardware_id: str,
    license_key: str,
    session: object,
) -> PluginActivationResult:
    normalized_hardware_id = str(hardware_id or "").strip()
    normalized_license_key = str(license_key or "").strip()

    if len(normalized_hardware_id) != 64:
        return _result(
            success=False,
            title=ERROR_TITLE,
            message="\u65e0\u6548\u7684\u786c\u4ef6ID\u3002",
        )
    if not normalized_license_key:
        return _result(
            success=False,
            title=LICENSE_EMPTY_TITLE,
            message="\u8bf7\u8f93\u5165\u6388\u6743\u7801\u540e\u518d\u9a8c\u8bc1\u3002",
        )

    set_validation_session()
    return _result(
        success=True,
        title="\u672c\u5730\u6a21\u5f0f\u5df2\u542f\u7528",
        message="\u5df2\u79fb\u9664\u5728\u7ebf\u6388\u6743\u9a8c\u8bc1\u3002",
        status_code=200,
        license_type="LOCAL_ONLY",
        validation_enabled=False,
    )

    bind_attempted = False
    is_valid, status_code, license_type, extra_info = _safe_validate_license_with_server(
        normalized_hardware_id,
        normalized_license_key,
    )
    if is_valid:
        set_validation_session(extra_info.get("session_token"))
        return _result(
            success=True,
            title="\u6388\u6743\u9a8c\u8bc1\u6210\u529f",
            message=(
                f"\u6388\u6743\u9a8c\u8bc1\u6210\u529f\uff0c\u7c7b\u578b\uff1a{license_type}"
            ),
            status_code=status_code,
            license_type=license_type,
        )

    if status_code in (0, 400, 401, 404, 409):
        bind_attempted = True
        if _safe_bind_license_to_hwid(
            normalized_hardware_id,
            normalized_license_key,
            session,
        ):
            is_valid, status_code, license_type, extra_info = _safe_validate_license_with_server(
                normalized_hardware_id,
                normalized_license_key,
            )
            if is_valid:
                set_validation_session(extra_info.get("session_token"))
                return _result(
                    success=True,
                    title="\u6388\u6743\u9a8c\u8bc1\u6210\u529f",
                    message=(
                        f"\u6388\u6743\u7ed1\u5b9a\u5e76\u9a8c\u8bc1\u6210\u529f\uff0c\u7c7b\u578b\uff1a{license_type}"
                    ),
                    status_code=status_code,
                    license_type=license_type,
                )

    extra_message = ""
    if isinstance(extra_info, dict):
        extra_message = str(extra_info.get("message") or "").strip()
    return _result(
        success=False,
        title="\u6388\u6743\u9a8c\u8bc1\u5931\u8d25",
        message=_build_validation_failure_message(
            status_code,
            extra_message=extra_message,
            bind_attempted=bind_attempted,
        ),
        status_code=status_code,
        license_type=license_type,
    )
