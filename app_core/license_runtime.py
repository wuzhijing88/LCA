import secrets
import sys
import time
from typing import Optional

from app_core.runtime_security import run_runtime_guard as _run_guard
from app_core.runtime_security import run_runtime_validator as _run_validator

AUTH_ENDPOINT = ""


def set_validation_session(session_token: Optional[str] = None) -> str:
    token = str(session_token or "").strip() or secrets.token_hex(32)
    sys._auth_session_token = token
    sys._last_validation_time = time.time()
    return token


def check_network_connectivity() -> bool:
    return True


def validate_license_with_server_v2(hw_id: str, key: str) -> tuple[bool, int, str, dict]:
    _run_guard()
    if not _run_validator(hw_id, key):
        return False, 400, "invalid", {}

    session_token = set_validation_session()
    return True, 200, "LOCAL_ONLY", {
        "validation_mode": "local_only",
        "license_validation_enabled": False,
        "session_token": session_token,
    }


def validate_license_with_server(hw_id: str, key: str) -> tuple[bool, int, str]:
    _run_guard()
    if not _run_validator(hw_id, key):
        return False, 400, "invalid"

    set_validation_session()
    return True, 200, "LOCAL_ONLY"


def bind_license_to_hwid(hw_id: str, license_key: str, session) -> bool:
    return True


def enforce_online_validation(hardware_id: str, license_key: str) -> tuple:
    _run_guard()
    set_validation_session()
    return True, 200, "LOCAL_ONLY"
