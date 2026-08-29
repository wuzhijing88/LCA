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
