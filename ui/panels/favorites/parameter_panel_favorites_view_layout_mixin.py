from ..parameter_panel_support import *
from utils.workflow_workspace_utils import favorite_path_key


class ParameterPanelFavoritesViewLayoutMixin:

            def _create_favorites_ui(self):



                """创建工作流收藏界面。"""



                entry_layout = QHBoxLayout()



                entry_layout.setContentsMargins(0, 0, 0, 0)



                entry_layout.setSpacing(8)







                entry_layout.addStretch(1)



                self.content_layout.addLayout(entry_layout)







                workflow_page = QWidget()



                workflow_layout = QVBoxLayout(workflow_page)



                workflow_layout.setContentsMargins(0, 0, 0, 0)



                workflow_layout.setSpacing(6)



                self._create_favorites_workflow_page(workflow_layout)



                self.content_layout.addWidget(workflow_page, 1)







                self._favorites_active_view = 'favorites'



                self._update_favorites_title()





            def _update_favorites_header_margins(self):



                if not hasattr(self, "_favorites_list") or not hasattr(self, "_favorites_header_layout"):



                    return



                metrics = getattr(self, "_favorites_col_metrics", None)



                if not metrics:



                    return



                viewport_rect = self._favorites_list.viewport().geometry()



                left = viewport_rect.x() + metrics["item_left_margin"]



                right = (



                    self._favorites_list.width()



                    - (viewport_rect.x() + viewport_rect.width())



                    + metrics["item_right_margin"]



                )



                self._favorites_header_layout.setContentsMargins(left, 0, right, 0)





            def _sync_favorites_tabs(self):



                """Sync favorites tab open/close state after apply."""



                try:



                    current_path_keys = set()



                    for fav in self._favorites:



                        filepath = fav.get('filepath')



                        if not filepath:



                            continue



                        current_path_keys.add(favorite_path_key(filepath))



                    pending_close_paths = dict(getattr(self, '_favorites_pending_close_paths', {}) or {})



                    for key, filepath in pending_close_paths.items():



                        if not filepath or key in current_path_keys:



                            continue



                        self.workflow_check_changed.emit(filepath, False)



                    for fav in self._favorites:



                        filepath = fav.get('filepath')



                        if not filepath:



                            continue



                        checked = fav.get('checked', True)



                        self.workflow_check_changed.emit(filepath, checked)



                    self._favorites_pending_close_paths = {}



                except Exception as e:



                    logger.error(f"同步收藏标签页失败: {e}")
