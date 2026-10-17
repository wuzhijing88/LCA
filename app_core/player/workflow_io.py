"""独立程序包内的现行 LCA 工程读取。"""

from typing import Any, Optional


def read_player_memory_lca(path: str) -> Optional[dict[str, Any]]:
    from app_core.lca_format.project_io import load_lca_from_bytes
    from app_core.player.memory_store import get_player_memory_file

    raw = get_player_memory_file(path)
    if raw is None:
        return None
    workflow, session = load_lca_from_bytes(raw)
    try:
        return workflow
    finally:
        session.close()
