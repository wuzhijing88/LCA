from ..parameter_panel_support import *


class ParameterPanelFavoritesItemSelectionMixin:
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
