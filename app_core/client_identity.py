from __future__ import annotations

import hashlib
import logging
import os
import platform
import socket
import uuid
from typing import Optional, Union

from utils.app_paths import get_hardware_id_path
from utils.log_message_translator import translate_log_message

logger = logging.getLogger(__name__)

try:
    import wmi  # type: ignore

    _WMI_LIB_AVAILABLE = True
except ImportError:
    wmi = None
    _WMI_LIB_AVAILABLE = False


def _resolve_server_settings() -> tuple[str, Union[bool, str]]:
    return "", True


def sanitize_error_message(error_msg: str) -> str:
    import re

    patterns = [
        r"host='[\d\.]+', port=\d+",
        r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+",
        r"HTTPConnectionPool\(host='[^']+', port=\d+\)",
        r"https?://[\d\.]+:\d+",
        r"/api/[a-zA-Z_/]+",
    ]

    sanitized_msg = str(error_msg or "")
    for pattern in patterns:
        sanitized_msg = re.sub(pattern, "[SERVER_INFO]", sanitized_msg)

    if "Read timed out" in sanitized_msg or "Connection" in sanitized_msg:
        return "杩炴帴鏈嶅姟绔秴鏃舵垨鏈嶅姟涓嶅彲鐢?"
    if "Max retries exceeded" in sanitized_msg:
        return "鏈嶅姟绔繛鎺ラ噸璇曟鏁板凡杈句笂闄?"
    if "Connection refused" in sanitized_msg:
        return "鏈嶅姟绔嫆缁濊繛鎺?"
    if "Name or service not known" in sanitized_msg:
        return "鏈嶅姟绔湴鍧€瑙ｆ瀽澶辫触"
    return translate_log_message(sanitized_msg)


def _normalize_hardware_id(value: object) -> str:
    text = str(value or "").strip().lower()
    if len(text) == 64 and all(ch in "0123456789abcdef" for ch in text):
        return text
    return ""


def _persist_hardware_id(hardware_id_path: str, hardware_id: str) -> None:
    directory = os.path.dirname(hardware_id_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(hardware_id_path, "w", encoding="utf-8") as file:
        file.write(hardware_id)


def get_hardware_id() -> Optional[str]:
    logger.info("正在根据运行时标识源重新生成硬件 ID")

    hardware_id_path = get_hardware_id_path()
    try:
        if os.path.exists(hardware_id_path):
            with open(hardware_id_path, "r", encoding="utf-8") as file:
                saved_id = _normalize_hardware_id(file.read())
            if saved_id:
                return saved_id
            logger.warning("Saved hardware ID is invalid; regenerating")
    except Exception as exc:
        logger.warning("Failed to read saved hardware ID: %s", exc)

    ids: dict[str, str] = {}

    if _WMI_LIB_AVAILABLE and os.name == "nt" and wmi is not None:
        try:
            client = wmi.WMI()
            wmi_uuids = [item.UUID for item in client.Win32_ComputerSystemProduct() if item.UUID]
            if wmi_uuids:
                wmi_uuid = str(wmi_uuids[0]).replace("-", "").lower()
                if len(wmi_uuid) == 32 and all(ch in "0123456789abcdef" for ch in wmi_uuid):
                    ids["wmi"] = hashlib.sha256(wmi_uuid.encode("utf-8")).hexdigest()
                else:
                    logger.warning("WMI UUID 鏍煎紡寮傚父: %s", wmi_uuids[0])
            else:
                logger.warning("WMI 鏈繑鍥?UUID")
        except Exception as exc:
            logger.warning("璇诲彇 WMI UUID 澶辫触: %s", exc)
    elif not _WMI_LIB_AVAILABLE:
        logger.warning("WMI 渚濊禆涓嶅彲鐢紝宸茶烦杩?WMI 纭欢 ID 鏉ユ簮")

    if "wmi" not in ids:
        try:
            system_info = f"{platform.system()}-{platform.machine()}-{socket.gethostname()}"
            try:
                import multiprocessing

                system_info += f"-{multiprocessing.cpu_count()}"
            except Exception:
                pass
            ids["system"] = hashlib.sha256(system_info.encode("utf-8")).hexdigest()
        except Exception as exc:
            logger.warning("鏋勫缓绯荤粺淇℃伅纭欢 ID 澶辫触: %s", exc)

    if ids:
        selected_id = ids.get("wmi") or ids.get("system") or next(iter(ids.values()))
        try:
            _persist_hardware_id(hardware_id_path, selected_id)
        except Exception as exc:
            logger.warning("鍐欏叆纭欢 ID 澶辫触: %s", exc)
        return selected_id

    fallback_seed = f"{platform.node()}-{uuid.uuid4()}"
    fallback_id = hashlib.sha256(fallback_seed.encode("utf-8")).hexdigest()
    logger.warning("鎵€鏈夌‖浠?ID 鏉ユ簮鍧囧け璐ワ紝灏嗕娇鐢ㄤ复鏃剁敓鎴愮殑鍥為€€ ID")
    try:
        _persist_hardware_id(hardware_id_path, fallback_id)
    except Exception as exc:
        logger.warning("鍐欏叆鍥為€€纭欢 ID 澶辫触: %s", exc)
    return fallback_id


def attempt_client_registration(hw_id: str, session=None) -> dict:
    if not hw_id or not isinstance(hw_id, str) or len(hw_id) != 64:
        logger.critical("纭欢 ID 鏍煎紡鏃犳晥: %s", hw_id)
        return {"success": False, "is_banned": False, "error": "invalid_hwid_format"}

    return {
        "success": True,
        "is_banned": False,
        "license_validation_enabled": False,
        "mode": "local_only",
    }
