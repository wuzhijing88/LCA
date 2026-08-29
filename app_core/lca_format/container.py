from __future__ import annotations

import io
import struct
import zipfile
from typing import Dict, Mapping

from app_core.lca_format.constants import (
    DEFAULT_KEY_ID,
    LCA_FLAGS,
    LCA_FORMAT_VERSION,
    LCA_HEADER_SIZE,
    LCA_MAGIC,
    USER_ERROR_INVALID,
)
from app_core.lca_format.crypto import CryptoError, aes_gcm_decrypt, aes_gcm_encrypt
from app_core.lca_format.keys import get_aes_key


class LcaFormatError(RuntimeError):
    """LCA1 容器格式错误。"""


def _build_aad(*, ver: int, flags: int, key_id: int) -> bytes:
    return LCA_MAGIC + struct.pack("<HHH", ver, flags, key_id)


def _files_to_zip_bytes(files: Mapping[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, data in sorted(files.items()):
            archive.writestr(path.replace("\\", "/"), data)
    return buffer.getvalue()


def _zip_bytes_to_files(plain_zip: bytes) -> Dict[str, bytes]:
    buffer = io.BytesIO(plain_zip)
    with zipfile.ZipFile(buffer, "r") as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def seal_lca_bytes(files: Mapping[str, bytes], *, key_id: int = DEFAULT_KEY_ID) -> bytes:
    plain_zip = _files_to_zip_bytes(files)
    ver = LCA_FORMAT_VERSION
    flags = LCA_FLAGS
    key = get_aes_key(key_id)
    aad = _build_aad(ver=ver, flags=flags, key_id=key_id)
    nonce, ciphertext_with_tag = aes_gcm_encrypt(key, plain_zip, aad=aad)
    header = LCA_MAGIC + struct.pack("<HHH", ver, flags, key_id) + nonce
    return header + ciphertext_with_tag


def unseal_lca_bytes(blob: bytes) -> Dict[str, bytes]:
    if len(blob) < LCA_HEADER_SIZE + 16:
        raise LcaFormatError(USER_ERROR_INVALID)

    if blob[: len(LCA_MAGIC)] != LCA_MAGIC:
        raise LcaFormatError(USER_ERROR_INVALID)

    ver, flags, key_id = struct.unpack("<HHH", blob[len(LCA_MAGIC) : len(LCA_MAGIC) + 6])

    if ver != LCA_FORMAT_VERSION:
        raise LcaFormatError(USER_ERROR_INVALID)

    if flags != LCA_FLAGS:
        raise LcaFormatError(USER_ERROR_INVALID)

    nonce = blob[len(LCA_MAGIC) + 6 : LCA_HEADER_SIZE]
    ciphertext_with_tag = blob[LCA_HEADER_SIZE:]

    try:
        key = get_aes_key(key_id)
    except KeyError:
        raise LcaFormatError(USER_ERROR_INVALID) from None

    aad = _build_aad(ver=ver, flags=flags, key_id=key_id)
    try:
        plain_zip = aes_gcm_decrypt(key, nonce, ciphertext_with_tag, aad=aad)
    except CryptoError:
        raise LcaFormatError(USER_ERROR_INVALID) from None

    try:
        return _zip_bytes_to_files(plain_zip)
    except (zipfile.BadZipFile, OSError):
        raise LcaFormatError(USER_ERROR_INVALID) from None
