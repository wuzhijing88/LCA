from __future__ import annotations

import ctypes
import secrets


class CryptoError(RuntimeError):
    pass


def _as_bytes(value: bytes | bytearray | memoryview) -> bytes:
    return bytes(value)


def aes_gcm_encrypt(key: bytes, plaintext: bytes, *, aad: bytes = b"") -> tuple[bytes, bytes]:
    """返回 (nonce, ciphertext_with_tag)。"""
    nonce = secrets.token_bytes(12)
    ciphertext_with_tag = _bcrypt_aes_gcm(key, nonce, plaintext, aad=aad, encrypt=True)
    return nonce, ciphertext_with_tag


def aes_gcm_decrypt(
    key: bytes,
    nonce: bytes,
    ciphertext_with_tag: bytes,
    *,
    aad: bytes = b"",
) -> bytes:
    if len(ciphertext_with_tag) < 16:
        raise CryptoError("密文缺少认证标签")
    return _bcrypt_aes_gcm(key, nonce, ciphertext_with_tag, aad=aad, encrypt=False)


def _bcrypt_aes_gcm(
    key: bytes,
    nonce: bytes,
    data: bytes,
    *,
    aad: bytes,
    encrypt: bool,
) -> bytes:
    if len(key) not in (16, 24, 32):
        raise CryptoError("AES 密钥长度无效")
    if len(nonce) != 12:
        raise CryptoError("GCM nonce 必须为 12 字节")

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
        raise CryptoError(f"打开 AES 算法失败: 0x{status.value & 0xFFFFFFFF:08X}")

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
            raise CryptoError(f"设置 GCM 模式失败: 0x{status.value & 0xFFFFFFFF:08X}")

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
            raise CryptoError(f"导入 AES 密钥失败: 0x{status.value & 0xFFFFFFFF:08X}")

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
                raise CryptoError(f"AES 加密失败: 0x{status.value & 0xFFFFFFFF:08X}")
            return bytes(out[: out_size.value]) + bytes(tag)

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
            raise CryptoError("AES 解密失败")
        return bytes(out[: out_size.value])
    finally:
        if key_handle:
            bcrypt.BCryptDestroyKey(key_handle)
        if alg:
            bcrypt.BCryptCloseAlgorithmProvider(alg, 0)
