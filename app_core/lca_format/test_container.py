import io
import struct
import zipfile

import pytest

from app_core.lca_format import container
from app_core.lca_format.constants import USER_ERROR_INVALID
from app_core.lca_format.container import LcaFormatError, seal_lca_bytes, unseal_lca_bytes


def test_seal_unseal_roundtrip():
    files = {
        "manifest.json": b'{"schema_version":1,"format":"lca_editor"}',
        "workflows/main.json": b'{"cards":[],"connections":[]}',
        "assets/images/a.bmp": b"BMPDATA",
    }
    blob = seal_lca_bytes(files)
    assert blob.startswith(b"LCA1")
    assert b"cards" not in blob  # 明文不应直接可见
    out = unseal_lca_bytes(blob)
    assert out["workflows/main.json"] == files["workflows/main.json"]
    assert out["assets/images/a.bmp"] == b"BMPDATA"


def test_bad_magic_raises():
    try:
        unseal_lca_bytes(b"XXXX" + b"\x00" * 40)
        assert False
    except LcaFormatError as exc:
        assert "无法打开：不是有效的 LCA 工程文件" in str(exc)


def test_truncated_raises():
    files = {"manifest.json": b"{}", "workflows/main.json": b"{}"}
    blob = seal_lca_bytes(files)
    try:
        unseal_lca_bytes(blob[:-8])
        assert False
    except LcaFormatError:
        pass


def _craft_header(*, ver: int = 1, flags: int = 0, key_id: int = 1) -> bytes:
    return b"LCA1" + struct.pack("<HHH", ver, flags, key_id) + b"\x00" * 12


def test_unsupported_version_raises_before_decrypt():
    blob = _craft_header(ver=2) + b"\x00" * 32
    try:
        unseal_lca_bytes(blob)
        assert False
    except LcaFormatError as exc:
        assert USER_ERROR_INVALID in str(exc)


def test_unknown_key_id_raises():
    blob = _craft_header(key_id=999) + b"\x00" * 32
    try:
        unseal_lca_bytes(blob)
        assert False
    except LcaFormatError as exc:
        assert USER_ERROR_INVALID in str(exc)


def test_unknown_flags_raises():
    blob = _craft_header(flags=1) + b"\x00" * 32
    try:
        unseal_lca_bytes(blob)
        assert False
    except LcaFormatError as exc:
        assert USER_ERROR_INVALID in str(exc)


def test_zip_reader_rejects_excessive_member_count():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("first.txt", b"one")
        archive.writestr("second.txt", b"two")

    with pytest.raises(LcaFormatError, match=USER_ERROR_INVALID):
        container._zip_bytes_to_files(buffer.getvalue(), max_members=1)


def test_zip_reader_rejects_excessive_total_size():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("large.bin", b"x" * 32)

    with pytest.raises(LcaFormatError, match=USER_ERROR_INVALID):
        container._zip_bytes_to_files(buffer.getvalue(), max_uncompressed_bytes=16)


def test_zip_reader_rejects_suspicious_member_compression_ratio():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("compressed.bin", b"x" * 4096)

    with pytest.raises(LcaFormatError, match=USER_ERROR_INVALID):
        container._zip_bytes_to_files(
            buffer.getvalue(),
            max_compression_ratio=2,
        )
