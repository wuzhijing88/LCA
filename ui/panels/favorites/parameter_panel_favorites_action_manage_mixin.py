from ..parameter_panel_support import *
from utils.workflow_workspace_utils import (
    build_workspace_favorites,
    favorite_path_key,
    update_workflow_gallery_path,
)


class ParameterPanelFavoritesActionManageMixin:
        def _collect_selected_favorites_items(self):

            """收集当前用于管理操作的列表项；未选中时给出明确提示。"""

            selected_items = self._favorites_list.selectedItems() if self._favorites_list else []

            if selected_items:

                return selected_items

            current_item = self._favorites_list.currentItem() if self._favorites_list else None

            if current_item:

                return [current_item]

            QMessageBox.information(
                self,
                "请先选中工作流",
                "请先点击要移除的工作流所在行，再点击“移除工作区”。\n"
                "左侧复选框仅用于“启动选中的工作流”，不会作为移除目标。",
            )

            return []

        def _queue_favorites_pending_close(self, filepaths):

            pending_close_paths = dict(getattr(self, '_favorites_pending_close_paths', {}) or {})

            for filepath in filepaths or []:

                raw_path = str(filepath or '').strip()

                if not raw_path:

                    continue

                normalized_path = os.path.abspath(os.path.normpath(raw_path))

                key = favorite_path_key(normalized_path)

                if not key:

                    continue

                pending_close_paths[key] = normalized_path

            self._favorites_pending_close_paths = pending_close_paths

        def _rebuild_workspace_favorites(self):

            self._favorites = build_workspace_favorites(
                getattr(self, '_favorite_workspaces', []),
                self._favorites,
            )

        def _on_favorites_add(self):

            """添加工作区目录。"""

            workspace_dir = QFileDialog.getExistingDirectory(

                self, "选择工作区目录", ""

            )

            normalized_workspace = os.path.abspath(os.path.normpath(workspace_dir)) if workspace_dir else ""

            if not normalized_workspace:

                return

            if normalized_workspace in getattr(self, '_favorite_workspaces', []):

                QMessageBox.information(self, "工作区已存在", f"该工作区已添加：\n{normalized_workspace}")

                return

            self._favorite_workspaces.append(normalized_workspace)

            self._rebuild_workspace_favorites()

            self._save_favorites_config()

            if getattr(self, '_favorites_mode', False):

                self._refresh_favorites_list()

        def _on_favorites_remove(self):

            """移除选中工作流所属的工作区。"""

            selected_items = self._collect_selected_favorites_items()

            if not selected_items:

                return

            workspace_dirs = set()

            filepaths = []

            for item in selected_items:

                filepath = item.data(Qt.ItemDataRole.UserRole)

                if not filepath:

                    continue

                filepaths.append(filepath)

                for fav in self._favorites:

                    if fav.get('filepath') != filepath:

                        continue

                    workspace_dir = str(fav.get('workspace_dir') or '').strip()

                    if workspace_dir:

                        workspace_dirs.add(os.path.normpath(workspace_dir))

                    break

            if not filepaths:

                return

            if not workspace_dirs:

                self._favorites = [f for f in self._favorites if f.get('filepath') not in filepaths]

                self._queue_favorites_pending_close(filepaths)

                self._save_favorites_config()

                if getattr(self, '_favorites_mode', False):

                    self._refresh_favorites_list()

                return

            affected_filepaths = [
                fav.get('filepath')
                for fav in self._favorites
                if os.path.normpath(str(fav.get('workspace_dir') or '').strip()) in workspace_dirs
            ]

            self._favorite_workspaces = [
                path
                for path in getattr(self, '_favorite_workspaces', [])
                if os.path.normpath(path) not in workspace_dirs
            ]

            self._queue_favorites_pending_close(affected_filepaths)

            self._rebuild_workspace_favorites()

            self._save_favorites_config()

            if getattr(self, '_favorites_mode', False):

                self._refresh_favorites_list()

        def _on_favorites_browse(self):

            """浏览并打开工作流。"""

            filepaths, _ = QFileDialog.getOpenFileNames(

                self, "打开工作流文件", "", "工作流文件 (*.json)"

            )

            for filepath in filepaths:

                self.workflow_open_requested.emit(filepath)

        def _on_favorites_select_all(self):

            """全选。"""

            for i in range(self._favorites_list.count()):

                item = self._favorites_list.item(i)

                widget = self._favorites_list.itemWidget(item)

                if widget:

                    checkbox = widget.findChild(QCheckBox)

                    if checkbox:

                        checkbox.setChecked(True)

        def _on_favorites_deselect_all(self):

            """取消全选。"""

            for i in range(self._favorites_list.count()):

                item = self._favorites_list.item(i)

                widget = self._favorites_list.itemWidget(item)

                if widget:

                    checkbox = widget.findChild(QCheckBox)

                    if checkbox:

                        checkbox.setChecked(False)

        def _on_favorites_check_changed(self, filepath: str, state):

            """勾选状态改变，仅记录状态，等待应用时统一同步。"""

            checked = state == 2

            for f in self._favorites:

                if f['filepath'] == filepath:

                    f['checked'] = checked

                    break

            logger.info(f"勾选状态改变(待应用): {filepath}, checked={checked}")

            self._save_favorites_config()

        def _on_favorites_rows_moved(self, parent, start, end, destination, row):

            """列表项拖动排序后。"""

            new_favorites = []

            for i in range(self._favorites_list.count()):

                item = self._favorites_list.item(i)

                filepath = item.data(Qt.ItemDataRole.UserRole)

                for f in self._favorites:

                    if f['filepath'] == filepath:

                        new_favorites.append(f)

                        break

            self._favorites = new_favorites

            self._save_favorites_config()

        def _on_favorites_context_menu(self, pos):

            """右键菜单。"""

            item = self._favorites_list.itemAt(pos)

            if not item:

                return

            menu = self._create_panel_context_menu()

            delete_action = menu.addAction("移除工作区")

            delete_action.triggered.connect(self._on_favorites_remove)

            menu.exec_(self._favorites_list.mapToGlobal(pos))

        def _on_favorites_item_double_clicked(self, item):

            """双击打开（不执行）。"""

            filepath = item.data(Qt.ItemDataRole.UserRole)

            if not os.path.exists(filepath):

                from PySide6.QtWidgets import QMessageBox

                QMessageBox.warning(self, "文件不存在", f"工作流文件不存在:\n{filepath}")

                return

            self.workflow_open_requested.emit(filepath)

        def _on_favorites_gallery_browse(self, filepath: str):

            """为单个工作流设置自定义图库目录。"""

            if not filepath:

                return

            gallery_dir = QFileDialog.getExistingDirectory(

                self, "选择自定义图库目录", ""

            )

            normalized_gallery = os.path.abspath(os.path.normpath(gallery_dir)) if gallery_dir else ""

            if not normalized_gallery:

                return

            try:

                result = update_workflow_gallery_path(filepath, normalized_gallery)

            except Exception as e:

                logger.error(f"更新工作流图库路径失败: {e}", exc_info=True)

                QMessageBox.warning(self, "更新失败", f"无法更新图库路径：\n{e}")

                return

            for fav in self._favorites:

                if fav.get('filepath') == filepath:

                    fav['gallery_path'] = result.get('gallery_path', '')

                    break

            self._save_favorites_config()

            if getattr(self, '_favorites_mode', False):

                self._refresh_favorites_list()

            main_window = getattr(self, 'parent_window', None)

            if main_window and hasattr(main_window, '_refresh_open_workflow_gallery_dir'):

                try:

                    main_window._refresh_open_workflow_gallery_dir(
                        filepath,
                        result.get('gallery_path', ''),
                        result.get('workflow_data'),
                    )

                except Exception:

                    logger.warning("同步已打开工作流图库路径失败", exc_info=True)

            updated_image_count = int(result.get('updated_image_count') or 0)

            QMessageBox.information(
                self,
                "图库路径已更新",
                f"已更新图库路径：\n{normalized_gallery}\n\n自动匹配导入图片数量：{updated_image_count}",
            )
