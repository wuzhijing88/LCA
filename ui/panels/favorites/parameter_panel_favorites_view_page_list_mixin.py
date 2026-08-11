from ..parameter_panel_support import *


class ParameterPanelFavoritesViewPageListMixin:

    _FAVORITES_LIST_STYLE = (
        "QListWidget#favoritesList { outline: none; }"
        "QListWidget#favoritesList::item {"
        " margin: 0px;"
        " padding: 0px;"
        " border: 1px solid transparent;"
        " border-radius: 6px;"
        "}"
        "QListWidget#favoritesList::item:selected {"
        " background-color: rgba(0, 120, 212, 48);"
        " border: 1px solid rgba(0, 120, 212, 140);"
        "}"
        "QListWidget#favoritesList::item:selected:active {"
        " background-color: rgba(0, 120, 212, 58);"
        " border: 1px solid rgba(0, 120, 212, 165);"
        "}"
        "QListWidget#favoritesList::item:selected:!active {"
        " background-color: rgba(0, 120, 212, 42);"
        " border: 1px solid rgba(0, 120, 212, 120);"
        "}"
        "QListWidget#favoritesList::item:hover:!selected {"
        " background-color: rgba(127, 127, 127, 26);"
        "}"
    )

    def _create_favorites_list_widget(self):
        favorites_list = QListWidget()
        favorites_list.setObjectName("favoritesList")
        favorites_list.setStyleSheet(self._FAVORITES_LIST_STYLE)
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
