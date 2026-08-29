from ..parameter_panel_support import *
from app_core.lca_format.constants import LCA_FILE_FILTER
from utils.window.window_activation_utils import show_and_raise_widget
from task_workflow.workspace import favorite_path_key
from task_workflow.workspace import (
    build_workspace_favorites,
    favorite_path_key,
    update_workflow_gallery_path,
)
from task_workflow.workspace import (
    load_workspace_favorites_snapshot,
    save_workspace_favorites_snapshot,
)

class ParameterPanelFavoritesMixin:

    def show_favorites(self):

        """显示工作流收藏列表"""

        self._favorites_mode = True

        self.current_card_id = None

        self.current_task_type = None

        self.title_input.setReadOnly(True)

        self._set_footer_buttons_visible(True)

        self._clear_content()

        self._load_favorites_data()

        self._create_favorites_ui()

        self._update_favorites_title()

        self._position_panel()

        self.manually_closed = False

        show_and_raise_widget(self, log_prefix='收藏面板展示')
        QTimer.singleShot(0, self._position_panel)

        if hasattr(self, 'reset_button') and self.reset_button is not None:
            self.reset_button.setVisible(False)

    def _set_favorites_view(self, view_name: str):

        if view_name == 'market':
            return

        self._favorites_active_view = 'favorites'

        self._update_favorites_title()

    def _update_favorites_title(self):

        self.title_input.setText("工作区工作流")

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

    def _create_favorites_workflow_page(self, parent_layout):
        self._create_favorites_toolbar(parent_layout)
        self._create_favorites_header(parent_layout)
        self._create_favorites_list_section(parent_layout)
        self._create_favorites_start_button(parent_layout)

    def _create_favorites_toolbar_button(self, text, tooltip, slot, width=None):
        button = QPushButton(text)
        if tooltip:
            button.setToolTip(tooltip)
        if width is not None:
            button.setFixedWidth(width)
        button.clicked.connect(slot)
        return button

    def _create_favorites_toolbar(self, parent_layout):
        toolbar_layout = QHBoxLayout()

        action_buttons = [
            ("添加工作区", "添加工作流工作区目录", self._on_favorites_add, None),
            ("移除工作区", "移除当前选中行所属的工作区；左侧勾选仅用于启动", self._on_favorites_remove, None),
        ]
        for text, tooltip, slot, width in action_buttons:
            toolbar_layout.addWidget(
                self._create_favorites_toolbar_button(text, tooltip, slot, width)
            )

        toolbar_layout.addStretch()

        toggle_buttons = [
            ("全选", None, self._on_favorites_select_all, 50),
            ("取消", None, self._on_favorites_deselect_all, 50),
        ]
        for text, tooltip, slot, width in toggle_buttons:
            toolbar_layout.addWidget(
                self._create_favorites_toolbar_button(text, tooltip, slot, width)
            )

        parent_layout.addLayout(toolbar_layout)

    def _init_favorites_column_metrics(self):
        self._favorites_col_metrics = {
            "item_outer_margin": 2,
            "header_left_margin": 6,
            "header_right_margin": 6,
            "item_left_margin": 4,
            "item_right_margin": 4,
            "spacing": 6,
            "check_width": 20,
        }

    def _create_favorites_header(self, parent_layout):
        self._init_favorites_column_metrics()
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(
            self._favorites_col_metrics["header_left_margin"],
            0,
            self._favorites_col_metrics["header_right_margin"],
            0,
        )
        header_layout.setSpacing(self._favorites_col_metrics["spacing"])
        self._favorites_header_layout = header_layout

        header_check = QLabel("")
        header_check.setFixedWidth(self._favorites_col_metrics["check_width"])
        header_layout.addWidget(header_check)

        header_name = QLabel("名称")
        header_layout.addWidget(header_name, 1)
        parent_layout.addLayout(header_layout)

    def _favorites_list_style(self) -> str:
        from themes import theme_rgba

        return (
            "QListWidget#favoritesList { outline: none; }"
            "QListWidget#favoritesList::item {"
            " margin: 0px;"
            " padding: 0px;"
            " border: 1px solid transparent;"
            " border-radius: 6px;"
            "}"
            "QListWidget#favoritesList::item:selected {"
            f" background-color: {theme_rgba('accent', 48, '#0078d4')};"
            f" border: 1px solid {theme_rgba('accent', 140, '#0078d4')};"
            "}"
            "QListWidget#favoritesList::item:selected:active {"
            f" background-color: {theme_rgba('accent', 58, '#0078d4')};"
            f" border: 1px solid {theme_rgba('accent', 165, '#0078d4')};"
            "}"
            "QListWidget#favoritesList::item:selected:!active {"
            f" background-color: {theme_rgba('accent', 42, '#0078d4')};"
            f" border: 1px solid {theme_rgba('accent', 120, '#0078d4')};"
            "}"
            "QListWidget#favoritesList::item:hover:!selected {"
            f" background-color: {theme_rgba('text', 26, '#333333')};"
            "}"
        )

    def _create_favorites_list_widget(self):
        favorites_list = QListWidget()
        favorites_list.setObjectName("favoritesList")
        favorites_list.setStyleSheet(self._favorites_list_style())
        favorites_list.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        favorites_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        favorites_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        favorites_list.customContextMenuRequested.connect(self._on_favorites_context_menu)
        favorites_list.itemDoubleClicked.connect(self._on_favorites_item_double_clicked)
        self._favorites_list = favorites_list
        return favorites_list

    def _populate_favorites_list_widget(self):
        for fav in self._favorites:
            self._add_favorites_list_item(fav)

    def _connect_favorites_list_layout_sync(self):
        self._favorites_list.verticalScrollBar().rangeChanged.connect(
            lambda *_: self._update_favorites_header_margins()
        )
        QTimer.singleShot(0, self._update_favorites_header_margins)

    def _create_favorites_list_section(self, parent_layout):
        favorites_list = self._create_favorites_list_widget()
        parent_layout.addWidget(favorites_list, 1)
        self._populate_favorites_list_widget()
        self._connect_favorites_list_layout_sync()

    def _create_favorites_start_button(self, parent_layout):
        self._favorites_start_btn = QPushButton("启动选中的工作流")
        self._favorites_start_btn.setMinimumHeight(36)
        self._favorites_start_btn.setStyleSheet("font-weight: bold;")
        self._favorites_start_btn.clicked.connect(self._on_favorites_start_batch)
        parent_layout.addWidget(self._favorites_start_btn)

    def _select_favorites_item(self, list_item: QListWidgetItem, event) -> None:
        if not list_item or not hasattr(self, "_favorites_list") or not self._favorites_list:
            return

        self._favorites_list.setFocus()
        modifiers = event.modifiers() if event else Qt.KeyboardModifier.NoModifier

        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            current_row = self._favorites_list.currentRow()
            target_row = self._favorites_list.row(list_item)
            if current_row < 0:
                current_row = target_row

            start = min(current_row, target_row)
            end = max(current_row, target_row)
            self._favorites_list.clearSelection()
            for row in range(start, end + 1):
                item = self._favorites_list.item(row)
                if item:
                    item.setSelected(True)
            self._favorites_list.setCurrentRow(target_row)
            return

        if modifiers & Qt.KeyboardModifier.ControlModifier:
            list_item.setSelected(not list_item.isSelected())
            self._favorites_list.setCurrentItem(list_item)
            return

        self._favorites_list.clearSelection()
        list_item.setSelected(True)
        self._favorites_list.setCurrentItem(list_item)

    def _add_favorites_list_item(self, fav: dict):
        item_widget = QWidget()
        item_widget.setAutoFillBackground(False)
        item_widget.setStyleSheet("background-color: transparent;")

        layout = QHBoxLayout(item_widget)
        metrics = getattr(self, "_favorites_col_metrics", None) or {
            "item_left_margin": 4,
            "item_right_margin": 4,
            "spacing": 6,
            "check_width": 20,
        }
        layout.setContentsMargins(metrics["item_left_margin"], 2, metrics["item_right_margin"], 2)
        layout.setSpacing(metrics["spacing"])

        checkbox = QCheckBox()
        checkbox.setChecked(fav.get("checked", True))
        checkbox.setFixedWidth(metrics["check_width"])
        checkbox.setToolTip("选中参与批量执行")
        checkbox.stateChanged.connect(
            lambda state, fp=fav["filepath"]: self._on_favorites_check_changed(fp, state)
        )
        layout.addWidget(checkbox)

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(2)

        name_label = QLabel(fav["name"])
        name_label.setToolTip(
            f"名称: {fav.get('name', '')}\n"
            "提示: 双击打开，右键更多操作"
        )
        name_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        content_layout.addWidget(name_label)

        gallery_path = str(fav.get("gallery_path") or "").strip()
        gallery_label = QLabel(
            "图库：已设置自定义图库" if gallery_path else "图库：默认图库"
        )
        gallery_label.setWordWrap(True)
        gallery_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        content_layout.addWidget(gallery_label)

        layout.addWidget(content_widget, 1)

        gallery_button = QPushButton("自定义图库")
        gallery_button.setMinimumWidth(96)
        gallery_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        is_local_workflow = bool(fav.get("filepath"))
        gallery_button.setEnabled(is_local_workflow)
        gallery_button.setToolTip("为当前工作流设置自定义图库目录" if is_local_workflow else "该工作流不支持此操作")
        if is_local_workflow:
            gallery_button.clicked.connect(
                lambda _checked=False, fp=fav["filepath"]: self._on_favorites_gallery_browse(fp)
            )
        layout.addWidget(gallery_button)

        list_item = QListWidgetItem()
        list_item.setSizeHint(QSize(0, 62))
        list_item.setData(Qt.ItemDataRole.UserRole, fav["filepath"])
        list_item.setFlags(list_item.flags() | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)

        self._favorites_list.addItem(list_item)
        self._favorites_list.setItemWidget(list_item, item_widget)

        if not hasattr(self, "_favorites_event_filters"):
            self._favorites_event_filters = []
        selection_filter = FavoritesItemEventFilter(self, list_item)
        item_widget.installEventFilter(selection_filter)
        checkbox.installEventFilter(selection_filter)
        name_label.installEventFilter(selection_filter)
        gallery_label.installEventFilter(selection_filter)
        content_widget.installEventFilter(selection_filter)
        self._favorites_event_filters.append(selection_filter)

    def _refresh_favorites_list(self):
        favorites_list = getattr(self, "_favorites_list", None)
        if favorites_list is None:
            return

        if hasattr(self, "_favorites_event_filters"):
            self._favorites_event_filters = []

        favorites_list.clear()
        for fav in self._favorites:
            self._add_favorites_list_item(fav)

    def _clear_favorites_runtime_refs(self):
        self._favorites_list = None

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

            self, "打开工作流文件", "", LCA_FILE_FILTER

        )

        for filepath in filepaths:

            self.workflow_open_requested.emit(filepath)

    def _set_all_favorites_checked(self, checked: bool):
        """统一设置收藏列表所有条目的勾选状态。"""
        for i in range(self._favorites_list.count()):
            item = self._favorites_list.item(i)
            widget = self._favorites_list.itemWidget(item)
            if widget:
                checkbox = widget.findChild(QCheckBox)
                if checkbox:
                    checkbox.setChecked(checked)

    def _on_favorites_select_all(self):
        """全选。"""
        self._set_all_favorites_checked(True)

    def _on_favorites_deselect_all(self):
        """取消全选。"""
        self._set_all_favorites_checked(False)

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

    def _on_favorites_execute_single(self, filepath: str):
        """兼容旧入口：统一改为启动已勾选的工作流"""
        _ = filepath
        self._on_favorites_start_batch()

    def _on_favorites_start_batch(self):
        """启动批量执行"""
        from PySide6.QtWidgets import QMessageBox

        # 获取选中的工作流及其配置
        selected_favs = [f for f in self._favorites if f.get('checked', True)]

        if not selected_favs:
            QMessageBox.information(self, "提示", "请先选择要执行的工作流")
            return

        selected = [f['filepath'] for f in selected_favs]

        # 检查文件
        missing = [fp for fp in selected if not os.path.exists(fp)]
        if missing:
            QMessageBox.warning(self, "文件缺失", "以下工作流文件不存在:\n" + "\n".join(missing))
            return

        logger.info(f"批量执行工作流: count={len(selected)}")
        self.batch_execute_requested.emit(selected)

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
