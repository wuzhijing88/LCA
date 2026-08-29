from __future__ import annotations

import hashlib

_APP_SALT = b"lca-editor-format-v1"
_KEY_MATERIAL: dict[int, bytes] = {
    1: _APP_SALT + b":key-id-1",
}


def get_aes_key(key_id: int) -> bytes:
    material = _KEY_MATERIAL.get(key_id)
    if material is None:
        raise KeyError(key_id)
    return hashlib.sha256(material).digest()
