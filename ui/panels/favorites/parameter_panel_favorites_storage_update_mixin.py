from ..parameter_panel_support import *


class ParameterPanelFavoritesStorageUpdateMixin:
        def update_favorite_name(self, filepath: str, custom_name: Optional[str]):

            """更新收藏列表中的工作流名称"""

            if not filepath:

                return



            new_name = custom_name.strip() if custom_name else ""

            if not new_name:

                new_name = self._build_favorite_default_name(filepath)



            normalized_target = os.path.normcase(os.path.normpath(filepath))

            updated = False

            for fav in self._favorites:

                fav_path = fav.get('filepath', '')

                compare_value = os.path.normcase(os.path.normpath(fav_path))

                if compare_value == normalized_target:

                    if fav.get('name') != new_name:

                        fav['name'] = new_name

                        updated = True

                    break



            if updated:

                self._save_favorites_config()

                if getattr(self, '_favorites_mode', False):

                    self._refresh_favorites_list()

        def update_favorite_entry(self, old_filepath: str, new_filepath: str, new_name: Optional[str] = None):

            """更新收藏列表中的工作流路径与名称"""

            if not old_filepath:

                return



            normalized_old = os.path.normcase(os.path.normpath(old_filepath))

            target_path = new_filepath or old_filepath

            name_value = (new_name or "").strip()

            if not name_value:

                name_value = self._build_favorite_default_name(target_path)



            updated = False

            for fav in self._favorites:

                fav_path = fav.get('filepath', '')

                compare_value = os.path.normcase(os.path.normpath(fav_path))

                if compare_value == normalized_old:

                    fav['filepath'] = target_path

                    workspace_dir = os.path.dirname(target_path) if target_path else ''

                    if workspace_dir:

                        fav['workspace_dir'] = os.path.normpath(workspace_dir)

                    if fav.get('name') != name_value:

                        fav['name'] = name_value

                    updated = True



            if not updated:

                return



            self._save_favorites_config()

            if getattr(self, '_favorites_mode', False):

                self._refresh_favorites_list()

                return
