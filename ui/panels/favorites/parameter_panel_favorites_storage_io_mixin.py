from ..parameter_panel_support import *
from utils.workflow_workspace_utils import (
    load_workspace_favorites_snapshot,
    save_workspace_favorites_snapshot,
)


class ParameterPanelFavoritesStorageIOMixin:
        def _normalize_favorites(self, favorites: list) -> tuple[list, bool]:
            """清理收藏配置，移除已废弃字段并补齐基础结构。"""
            normalized_favorites = []
            changed = False

            if not isinstance(favorites, list):
                return [], bool(favorites)

            for item in favorites:
                if not isinstance(item, dict):
                    changed = True
                    continue

                filepath = str(item.get('filepath') or '').strip()
                if not filepath:
                    changed = True
                    continue

                filepath = os.path.normpath(filepath)

                name = str(item.get('name') or '').strip()
                if not name:
                    name = self._build_favorite_default_name(filepath)
                    changed = True

                normalized_item = {
                    'name': name,
                    'filepath': filepath,
                    'checked': bool(item.get('checked', True)),
                }
                workspace_dir = str(item.get('workspace_dir') or '').strip()
                if workspace_dir:
                    normalized_item['workspace_dir'] = os.path.normpath(workspace_dir)
                gallery_path = str(item.get('gallery_path') or '').strip()
                if gallery_path:
                    normalized_item['gallery_path'] = os.path.normpath(gallery_path)
                source = str(item.get('source') or '').strip()
                if source:
                    normalized_item['source'] = source

                if normalized_item != item:
                    changed = True

                normalized_favorites.append(normalized_item)

            return normalized_favorites, changed
        def _sync_workspace_favorites_snapshot(self) -> tuple[list[str], list[dict], bool]:
            """同步工作区收藏快照，并在必要时回写配置。"""
            workspaces, favorites, changed = load_workspace_favorites_snapshot(self._favorites_config_path)
            self._favorite_workspaces = workspaces
            return workspaces, favorites, changed
        def _load_favorites_data(self):
            """加载收藏数据（不含UI设置）"""
            try:
                if os.path.exists(self._favorites_config_path):
                    _, favorites, changed = self._sync_workspace_favorites_snapshot()
                    self._favorites, normalized_changed = self._normalize_favorites(favorites)
                    changed = changed or normalized_changed
                    if changed:
                        self._save_favorites_config()
                    logger.info(f"加载工作流收藏数据: {len(self._favorites)} 个")
                else:
                    self._favorite_workspaces = []
                    self._favorites = []
            except Exception as e:
                logger.error(f"加载工作流收藏数据失败: {e}")
                self._favorite_workspaces = []
                self._favorites = []
        def _save_favorites_config(self):
            """保存收藏配置"""
            try:
                save_workspace_favorites_snapshot(
                    self._favorites_config_path,
                    getattr(self, '_favorite_workspaces', []),
                    self._favorites,
                )
                logger.info(f"保存工作流收藏配置: {len(self._favorites)} 个")
            except Exception as e:
                logger.error(f"保存工作流收藏配置失败: {e}")
