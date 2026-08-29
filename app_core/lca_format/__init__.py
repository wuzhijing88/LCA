"""LCA 编辑器 `.lca` 工程格式（LCA1 容器）。"""

from app_core.lca_format.constants import LCA_EXTENSION, USER_ERROR_INVALID
from app_core.lca_format.container import LcaFormatError, seal_lca_bytes, unseal_lca_bytes

__all__ = [
    "LCA_EXTENSION",
    "LcaFormatError",
    "USER_ERROR_INVALID",
    "seal_lca_bytes",
    "unseal_lca_bytes",
]
