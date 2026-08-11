from ..parameter_panel_support import *


class ParameterPanelFavoritesItemStorageMixin:
    def _build_favorite_default_name(self, filepath: str) -> str:
        raw_path = str(filepath or "").strip()
        normalized_path = os.path.normpath(raw_path)
        if not normalized_path:
            return raw_path
        return os.path.splitext(os.path.basename(normalized_path))[0]

    def _add_favorite_entry(
        self,
        filepath: str,
        custom_name: str = "",
        checked: bool = True,
        emit_state: bool = True,
    ) -> str:
        raw_path = str(filepath or "").strip()
        safe_path = os.path.normpath(raw_path)
        if not safe_path:
            return "invalid"
        if not os.path.exists(safe_path):
            return "invalid"

        default_name = self._build_favorite_default_name(safe_path)
        display_name = str(custom_name or "").strip() or default_name
        normalized_target = os.path.normcase(os.path.normpath(safe_path))

        for fav in self._favorites:
            fav_path = fav.get("filepath", "")
            compare_value = os.path.normcase(os.path.normpath(fav_path))
            if compare_value != normalized_target:
                continue

            changed = False
            if display_name and fav.get("name") != display_name:
                fav["name"] = display_name
                changed = True
            if checked and not fav.get("checked", True):
                fav["checked"] = True
                changed = True

            if changed:
                self._save_favorites_config()
                if getattr(self, "_favorites_mode", False):
                    self._refresh_favorites_list()
                if emit_state:
                    self.workflow_check_changed.emit(safe_path, bool(fav.get("checked", True)))
                return "updated"
            return "exists"

        fav = {"name": display_name, "filepath": safe_path, "checked": bool(checked)}
        self._favorites.append(fav)
        if getattr(self, "_favorites_mode", False) and hasattr(self, "_favorites_list"):
            self._add_favorites_list_item(fav)
        self._save_favorites_config()
        if emit_state:
            self.workflow_check_changed.emit(safe_path, bool(checked))
        return "added"
