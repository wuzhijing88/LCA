from ..parameter_panel_support import *


class ParameterPanelWindowSetupMixin:

    def _setup_ui(self):
        self._configure_panel_size()
        main_layout = self._create_panel_root_layout()
        self._build_panel_title_bar(main_layout)
        content_container = self._build_panel_content_container()
        main_layout.addWidget(content_container)
        self.status_label = None
        self.hide()

    def _configure_panel_size(self) -> None:
        self.setFixedWidth(440 + self._shadow_margin * 2)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)

    def _create_panel_root_layout(self) -> QVBoxLayout:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(
            self._shadow_margin,
            self._shadow_margin,
            self._shadow_margin,
            self._shadow_margin,
        )
        main_layout.setSpacing(0)
        return main_layout

    def _build_panel_title_bar(self, main_layout: QVBoxLayout) -> None:
        self.title_frame = QFrame()
        self.title_frame.setFrameStyle(QFrame.Shape.NoFrame)
        self.title_frame.setFixedHeight(36)

        title_layout = QHBoxLayout(self.title_frame)
        title_layout.setContentsMargins(8, 3, 4, 3)

        self.title_input = QLineEdit('\u53c2\u6570\u8bbe\u7f6e')
        self.title_input.setFont(QFont('Microsoft YaHei', 10, QFont.Weight.Bold))
        self.title_input.setFrame(False)
        self.title_input.setReadOnly(False)
        self.title_input.setStyleSheet(
            'QLineEdit { background: transparent; border: none; padding: 0px; }'
        )
        self.title_input.editingFinished.connect(self._on_title_edited)
        title_layout.addWidget(self.title_input)
        title_layout.addStretch()

        self.close_button = CloseButton()
        self.close_button.clicked.connect(self.hide_panel)
        title_layout.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignVCenter)
        main_layout.addWidget(self.title_frame)

    def _build_panel_content_container(self) -> QFrame:
        content_container = QFrame()
        content_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        content_layout = QVBoxLayout(content_container)
        content_layout.setContentsMargins(6, 4, 6, 6)
        content_layout.setSpacing(6)
        self._build_panel_scroll_area(content_layout)
        self._build_panel_footer_buttons(content_layout)
        return content_container

    def _build_panel_scroll_area(self, content_layout: QVBoxLayout) -> None:
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)

        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(4, 4, 4, 4)
        self.content_layout.setSpacing(6)

        self.scroll_area.setWidget(self.content_widget)
        content_layout.addWidget(self.scroll_area)

    def _build_panel_footer_buttons(self, content_layout: QVBoxLayout) -> None:
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.apply_button = QPushButton('\u5e94\u7528')
        self.apply_button.clicked.connect(lambda: self._apply_parameters(auto_close=True))
        button_layout.addWidget(self.apply_button)

        self.reset_button = QPushButton('\u91cd\u7f6e')
        self.reset_button.clicked.connect(self._reset_parameters)
        button_layout.addWidget(self.reset_button)

        content_layout.addLayout(button_layout)
