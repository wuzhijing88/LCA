from __future__ import annotations

import ctypes
import io
import json
import os
import secrets
import shutil
import struct
import zipfile
from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple

from app_core.player.memory_store import load_files_into_memory, memory_uri


LCAP_MAGIC = b"LCAP1"
LCAP_FILENAME = "package.lcap"
LCAP_KEY_FILENAME = "package.key"  # 旧版残留，导出时会删除
_EXTRACT_DIRNAME = "player_package"
# v1: magic + ver + ciphertext(key 外置)
# v2: magic + ver + key32 + ciphertext（密钥内嵌）
# v3: magic + ver + bind_id16 + key32 + ciphertext（AAD 含 bind_id，与 exe 印记配对）
LCAP_VERSION_EMBEDDED_KEY = 2
LCAP_VERSION_BOUND = 3
BIND_ID_SIZE = 16
_EMPTY_BIND_ID = bytes(BIND_ID_SIZE)


class SecurePackageError(RuntimeError):
    pass


def _as_bytes(value: bytes | bytearray | memoryview) -> bytes:
    return bytes(value)


def _aes_gcm_encrypt(key: bytes, plaintext: bytes, aad: bytes = b"") -> bytes:
    nonce = secrets.token_bytes(12)
    ciphertext_with_tag = _bcrypt_aes_gcm(key, nonce, plaintext, aad=aad, encrypt=True)
    return nonce + ciphertext_with_tag


def _aes_gcm_decrypt(key: bytes, blob: bytes, aad: bytes = b"") -> bytes:
    if len(blob) < 12 + 16:
        raise SecurePackageError("加密包数据过短")
    nonce = blob[:12]
    payload = blob[12:]
    return _bcrypt_aes_gcm(key, nonce, payload, aad=aad, encrypt=False)


def _bcrypt_aes_gcm(
    key: bytes,
    nonce: bytes,
    data: bytes,
    *,
    aad: bytes,
    encrypt: bool,
) -> bytes:
    if len(key) not in (16, 24, 32):
        raise SecurePackageError("AES 密钥长度无效")
    if len(nonce) != 12:
        raise SecurePackageError("GCM nonce 必须为 12 字节")

    bcrypt = ctypes.windll.bcrypt
    BCRYPT_ALG_HANDLE = ctypes.c_void_p
    BCRYPT_KEY_HANDLE = ctypes.c_void_p
    NTSTATUS = ctypes.c_long

    class BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong),
            ("dwInfoVersion", ctypes.c_ulong),
            ("pbNonce", ctypes.c_void_p),
            ("cbNonce", ctypes.c_ulong),
            ("pbAuthData", ctypes.c_void_p),
            ("cbAuthData", ctypes.c_ulong),
            ("pbTag", ctypes.c_void_p),
            ("cbTag", ctypes.c_ulong),
            ("pbMacContext", ctypes.c_void_p),
            ("cbMacContext", ctypes.c_ulong),
            ("cbAAD", ctypes.c_ulong),
            ("cbData", ctypes.c_ulonglong),
            ("dwFlags", ctypes.c_ulong),
        ]

    alg = BCRYPT_ALG_HANDLE()
    key_handle = BCRYPT_KEY_HANDLE()
    status = NTSTATUS(
        bcrypt.BCryptOpenAlgorithmProvider(
            ctypes.byref(alg),
            "AES",
            None,
            0,
        )
    )
    if status.value != 0:
        raise SecurePackageError(f"打开 AES 算法失败: 0x{status.value & 0xFFFFFFFF:08X}")

    try:
        mode = ctypes.create_unicode_buffer("ChainingModeGCM")
        status = NTSTATUS(
            bcrypt.BCryptSetProperty(
                alg,
                "ChainingMode",
                ctypes.byref(mode),
                ctypes.sizeof(mode),
                0,
            )
        )
        if status.value != 0:
            raise SecurePackageError(f"设置 GCM 模式失败: 0x{status.value & 0xFFFFFFFF:08X}")

        key_buf = (ctypes.c_ubyte * len(key)).from_buffer_copy(key)
        status = NTSTATUS(
            bcrypt.BCryptGenerateSymmetricKey(
                alg,
                ctypes.byref(key_handle),
                None,
                0,
                key_buf,
                len(key),
                0,
            )
        )
        if status.value != 0:
            raise SecurePackageError(f"导入 AES 密钥失败: 0x{status.value & 0xFFFFFFFF:08X}")

        tag = (ctypes.c_ubyte * 16)()
        nonce_buf = (ctypes.c_ubyte * len(nonce)).from_buffer_copy(nonce)
        aad_buf = (ctypes.c_ubyte * len(aad)).from_buffer_copy(aad) if aad else None

        info = BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO()
        info.cbSize = ctypes.sizeof(BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO)
        info.dwInfoVersion = 1
        info.pbNonce = ctypes.cast(nonce_buf, ctypes.c_void_p)
        info.cbNonce = len(nonce)
        if aad_buf is not None:
            info.pbAuthData = ctypes.cast(aad_buf, ctypes.c_void_p)
            info.cbAuthData = len(aad)
        info.pbTag = ctypes.cast(tag, ctypes.c_void_p)
        info.cbTag = 16

        if encrypt:
            plain = _as_bytes(data)
            out = (ctypes.c_ubyte * max(len(plain), 1))()
            out_size = ctypes.c_ulong(0)
            status = NTSTATUS(
                bcrypt.BCryptEncrypt(
                    key_handle,
                    plain,
                    len(plain),
                    ctypes.byref(info),
                    None,
                    0,
                    out,
                    len(out),
                    ctypes.byref(out_size),
                    0,
                )
            )
            if status.value != 0:
                raise SecurePackageError(f"AES 加密失败: 0x{status.value & 0xFFFFFFFF:08X}")
            return bytes(out[: out_size.value]) + bytes(tag)

        if len(data) < 16:
            raise SecurePackageError("密文缺少认证标签")
        cipher = _as_bytes(data[:-16])
        incoming_tag = _as_bytes(data[-16:])
        ctypes.memmove(tag, incoming_tag, 16)
        out = (ctypes.c_ubyte * max(len(cipher), 1))()
        out_size = ctypes.c_ulong(0)
        status = NTSTATUS(
            bcrypt.BCryptDecrypt(
                key_handle,
                cipher,
                len(cipher),
                ctypes.byref(info),
                None,
                0,
                out,
                len(out),
                ctypes.byref(out_size),
                0,
            )
        )
        if status.value != 0:
            raise SecurePackageError("独立程序包解密失败（文件可能被篡改）")
        return bytes(out[: out_size.value])
    finally:
        if key_handle:
            bcrypt.BCryptDestroyKey(key_handle)
        if alg:
            bcrypt.BCryptCloseAlgorithmProvider(alg, 0)


def _zip_directory(package_dir: Path) -> bytes:
    buffer = io.BytesIO()
    root = package_dir.resolve()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for current, _dirnames, filenames in os.walk(root):
            current_path = Path(current)
            for filename in filenames:
                source = current_path / filename
                if not source.is_file():
                    continue
                arcname = source.relative_to(root).as_posix()
                archive.write(source, arcname)
    return buffer.getvalue()


def _read_zip_members(payload: bytes) -> Dict[str, bytes]:
    files: Dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
        for info in archive.infolist():
            name = info.filename.replace("\\", "/")
            if not name or name.endswith("/"):
                continue
            if name.startswith("/") or ".." in Path(name).parts:
                raise SecurePackageError(f"加密包内含非法路径: {name}")
            files[name] = archive.read(info)
    return files


def _normalize_bind_id(bind_id: bytes | bytearray | memoryview | None) -> bytes:
    if bind_id is None:
        return _EMPTY_BIND_ID
    raw = bytes(bind_id)
    if len(raw) != BIND_ID_SIZE:
        raise SecurePackageError(f"bind_id 长度必须为 {BIND_ID_SIZE} 字节")
    return raw


def read_lcap_bind_id(export_root: Path | str) -> Optional[bytes]:
    """读取密封包明文头中的 bind_id；非 v3 或缺失返回 None。"""
    lcap_path = find_sealed_package(Path(export_root))
    if lcap_path is None:
        return None
    blob = lcap_path.read_bytes()
    if not blob.startswith(LCAP_MAGIC) or len(blob) < len(LCAP_MAGIC) + 4:
        return None
    version = struct.unpack_from("<I", blob, len(LCAP_MAGIC))[0]
    if version != LCAP_VERSION_BOUND:
        return None
    offset = len(LCAP_MAGIC) + 4
    if len(blob) < offset + BIND_ID_SIZE:
        return None
    bind = blob[offset : offset + BIND_ID_SIZE]
    if bind == _EMPTY_BIND_ID:
        return None
    return bytes(bind)


def _zip_files(files: Mapping[str, bytes]) -> bytearray:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for raw_name, raw_data in files.items():
            name = str(raw_name or "").replace("\\", "/").lstrip("/")
            if not name or name.endswith("/") or name.startswith("/") or ".." in Path(name).parts:
                raise SecurePackageError(f"非法打包路径: {raw_name}")
            info = zipfile.ZipInfo(filename=name)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, bytes(raw_data or b""))
    payload = bytearray(buffer.getvalue())
    buffer.seek(0)
    buffer.truncate(0)
    buffer.close()
    return payload


def _zero_buffer(payload: bytearray) -> None:
    if payload:
        payload[:] = b"\x00" * len(payload)
    payload.clear()


def secure_remove_path(path: Path | str) -> None:
    """删除明文残留：先覆写文件再移除。不用于整棵运行时目录。"""
    target = Path(path)
    if not target.exists():
        return
    if target.is_file():
        _secure_overwrite_file(target)
        try:
            target.unlink()
        except OSError:
            pass
        return
    for child in sorted(target.rglob("*"), reverse=True):
        if child.is_file():
            _secure_overwrite_file(child)
            try:
                child.unlink()
            except OSError:
                pass
    shutil.rmtree(target, ignore_errors=True)


def _secure_overwrite_file(path: Path) -> None:
    try:
        size = int(path.stat().st_size)
    except OSError:
        return
    if size <= 0:
        return
    chunk = b"\x00" * min(size, 1024 * 1024)
    try:
        with open(path, "r+b", buffering=0) as handle:
            remaining = size
            handle.seek(0)
            while remaining > 0:
                written = handle.write(chunk[: remaining])
                remaining -= int(written or 0)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        pass


def seal_package_files(
    files: Mapping[str, bytes],
    output_dir: Path,
    *,
    bind_id: bytes | bytearray | memoryview | None = None,
) -> Path:
    """把内存中的明文文件打成 package.lcap，不落明文目录。"""
    if "manifest.json" not in files:
        raise SecurePackageError("待加密内容缺少 manifest.json")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    plain_zip = _zip_files(files)
    try:
        return _write_sealed_blob(plain_zip, output_dir, bind_id=bind_id)
    finally:
        _zero_buffer(plain_zip)


def _write_sealed_blob(
    plain_zip: bytes | bytearray,
    output_dir: Path,
    *,
    bind_id: bytes | bytearray | memoryview | None = None,
) -> Path:
    key = secrets.token_bytes(32)
    bind = _normalize_bind_id(bind_id)
    plaintext = bytes(plain_zip)
    if bind != _EMPTY_BIND_ID:
        encrypted = _aes_gcm_encrypt(key, plaintext, aad=LCAP_MAGIC + bind)
        blob = LCAP_MAGIC + struct.pack("<I", LCAP_VERSION_BOUND) + bind + key + encrypted
    else:
        encrypted = _aes_gcm_encrypt(key, plaintext, aad=LCAP_MAGIC)
        blob = LCAP_MAGIC + struct.pack("<I", LCAP_VERSION_EMBEDDED_KEY) + key + encrypted

    lcap_path = Path(output_dir) / LCAP_FILENAME
    lcap_path.write_bytes(blob)
    stale_key = Path(output_dir) / LCAP_KEY_FILENAME
    if stale_key.exists():
        try:
            stale_key.unlink()
        except OSError:
            pass
    try:
        ctypes.windll.kernel32.SetFileAttributesW(str(lcap_path), 0x2)
    except Exception:
        pass
    cleanup_extracted_package(output_dir)
    return lcap_path


def seal_package_dir(
    package_dir: Path,
    output_dir: Path,
    *,
    bind_id: bytes | bytearray | memoryview | None = None,
) -> Path:
    """把明文 package 打成内嵌密钥的加密包，并安全删除明文目录。"""
    package_dir = Path(package_dir)
    output_dir = Path(output_dir)
    if not package_dir.is_dir():
        raise SecurePackageError(f"待加密目录不存在: {package_dir}")
    if not (package_dir / "manifest.json").is_file():
        raise SecurePackageError("待加密目录缺少 manifest.json")

    plain_zip = bytearray(_zip_directory(package_dir))
    try:
        lcap_path = _write_sealed_blob(plain_zip, output_dir, bind_id=bind_id)
    finally:
        _zero_buffer(plain_zip)
    secure_remove_path(package_dir)
    return lcap_path


def find_sealed_package(export_root: Path) -> Optional[Path]:
    candidate = Path(export_root) / LCAP_FILENAME
    if candidate.is_file():
        return candidate
    return None


def decrypt_sealed_package_bytes(export_root: Path) -> bytes:
    export_root = Path(export_root)
    lcap_path = find_sealed_package(export_root)
    if lcap_path is None:
        raise SecurePackageError(f"未找到加密包: {export_root / LCAP_FILENAME}")

    blob = lcap_path.read_bytes()
    if not blob.startswith(LCAP_MAGIC):
        raise SecurePackageError("加密包格式无效")
    if len(blob) < len(LCAP_MAGIC) + 4:
        raise SecurePackageError("加密包损坏")
    version = struct.unpack_from("<I", blob, len(LCAP_MAGIC))[0]
    offset = len(LCAP_MAGIC) + 4
    if version == LCAP_VERSION_BOUND:
        if len(blob) < offset + BIND_ID_SIZE + 32:
            raise SecurePackageError("加密包绑定信息或密钥缺失")
        bind = blob[offset : offset + BIND_ID_SIZE]
        key = blob[offset + BIND_ID_SIZE : offset + BIND_ID_SIZE + 32]
        encrypted = blob[offset + BIND_ID_SIZE + 32 :]
        return _aes_gcm_decrypt(key, encrypted, aad=LCAP_MAGIC + bind)
    if version == LCAP_VERSION_EMBEDDED_KEY:
        if len(blob) < offset + 32:
            raise SecurePackageError("加密包密钥缺失")
        key = blob[offset : offset + 32]
        encrypted = blob[offset + 32 :]
        return _aes_gcm_decrypt(key, encrypted, aad=LCAP_MAGIC)
    if version == 1:
        key_path = export_root / LCAP_KEY_FILENAME
        if not key_path.is_file():
            raise SecurePackageError(f"缺少解密密钥: {key_path}")
        key = key_path.read_bytes()
        encrypted = blob[offset:]
        return _aes_gcm_decrypt(key, encrypted, aad=LCAP_MAGIC)
    raise SecurePackageError(f"不支持的加密包版本: {version}")


def assert_entry_package_binding(export_root: Path | str) -> None:
    """播放器印记与 package.lcap 必须携带同一 bind_id（防挪包）。"""
    from app_core.player.entry_stamp import ENTRY_PLAYER, read_own_entry_stamp_info

    stamp = read_own_entry_stamp_info()
    pkg_bind = read_lcap_bind_id(export_root)

    # 非打包播放器 / 无印记：不在此强制（由上层决定是否进播放器）
    if stamp is None or stamp.entry != ENTRY_PLAYER:
        return

    stamp_bound = stamp.has_package_bind
    pkg_bound = pkg_bind is not None

    if stamp_bound and not pkg_bound:
        raise SecurePackageError(
            "程序已绑定数据包，但 package.lcap 缺少绑定信息或版本过旧。\n"
            "请重新制作并完整安装独立程序。"
        )
    if pkg_bound and not stamp_bound:
        raise SecurePackageError(
            "数据包已绑定程序，但当前程序未携带绑定印记。\n"
            "请勿替换主程序或混用不同导出批次的文件。"
        )
    if stamp_bound and pkg_bound:
        import hmac as _hmac

        if not _hmac.compare_digest(stamp.bind_id, pkg_bind):
            raise SecurePackageError(
                "程序与数据包不匹配（可能被替换或混用了不同安装包的文件），无法启动。\n"
                "请重新安装完整的独立程序。"
            )


def load_sealed_package_memory(export_root: Path) -> Tuple[dict, dict, dict, str]:
    """
    解密到内存并注册 memory:// 图片提供者。
    返回 (manifest_raw, ui_raw, workflow_data, entry_memory_uri)
    不在磁盘留下工作流/图片明文。
    """
    assert_entry_package_binding(export_root)
    plain_zip = decrypt_sealed_package_bytes(export_root)
    files = _read_zip_members(plain_zip)
    if "manifest.json" not in files:
        raise SecurePackageError("加密包缺少 manifest.json")

    # 必须在注入 memory 别名之前校验，否则 images/ 与 basename 索引会误报篡改
    try:
        from app_core.player.package_integrity import verify_package_files

        verify_package_files(files, require=False)
    except ValueError as exc:
        raise SecurePackageError(str(exc)) from exc

    load_files_into_memory(files)
    cleanup_extracted_package(export_root)

    manifest = json.loads(files["manifest.json"].decode("utf-8"))
    ui_payload = {}
    if "ui.json" in files:
        ui_payload = json.loads(files["ui.json"].decode("utf-8"))

    entry_rel = str(manifest.get("entry_workflow") or "workflows/main.json").replace("\\", "/").lstrip("/")
    if entry_rel not in files:
        raise SecurePackageError(f"加密包缺少入口工作流: {entry_rel}")
    workflow_data = json.loads(files[entry_rel].decode("utf-8"))
    if not isinstance(workflow_data, dict):
        raise SecurePackageError("入口工作流格式无效")

    return manifest, ui_payload, workflow_data, memory_uri(entry_rel)


def unseal_package_to_dir(export_root: Path, *, extract_root: Optional[Path] = None) -> Path:
    """兼容旧接口：默认不再落盘，改为加载内存包并返回占位目录路径（export_root）。"""
    load_sealed_package_memory(export_root)
    return Path(export_root)


def cleanup_extracted_package(export_root: Path) -> None:
    userdata = Path(os.environ.get("LCA_USER_DATA_DIR") or (Path(export_root) / "userdata"))
    extracted = userdata / _EXTRACT_DIRNAME
    if extracted.exists():
        secure_remove_path(extracted)
    leftover = Path(export_root) / "package"
    if leftover.is_dir() and (leftover / "manifest.json").is_file():
        secure_remove_path(leftover)
