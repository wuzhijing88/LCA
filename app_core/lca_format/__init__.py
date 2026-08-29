"""LCA 编辑器 `.lca` 工程格式（LCA1 容器）。"""

from app_core.lca_format.constants import LCA_EXTENSION, USER_ERROR_INVALID
from app_core.lca_format.container import LcaFormatError, seal_lca_bytes, unseal_lca_bytes
from app_core.lca_format.project_io import is_lca_path, load_lca_project, save_lca_project
from app_core.lca_format.session import LcaPackageSession

__all__ = [
    "LCA_EXTENSION",
    "LcaFormatError",
    "LcaPackageSession",
    "USER_ERROR_INVALID",
    "is_lca_path",
    "load_lca_project",
    "save_lca_project",
    "seal_lca_bytes",
    "unseal_lca_bytes",
]
