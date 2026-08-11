from ..parameter_panel_support import *


class ParameterPanelWidgetMultilineTypeConnectedTargetsMixin:
    def _create_multiline_connected_targets_widget(self):
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(6)

        connections = self.current_parameters.get('_random_connections', [])
        if connections:
            for conn in connections:
                conn_task_type = conn.get('task_type', '')
                conn_card_id = conn.get('card_id', '')
                conn_weight = get_branch_weight(
                    self.current_parameters.get('random_weights'),
                    conn_card_id,
                )
                display_text = f"{conn_task_type} (ID: {conn_card_id})  权重: {conn_weight}"

                card_label = QLabel(display_text)
                card_label.setStyleSheet(
                    """
                    QLabel {
                        color: #333333;
                        background-color: #f8f8f8;
                        border: 1px solid #ddd;
                        border-radius: 4px;
                        padding: 6px 10px;
                    }
                    """
                )
                card_label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                card_label.customContextMenuRequested.connect(
                    partial(self._show_random_target_context_menu, conn_card_id, card_label)
                )
                container_layout.addWidget(card_label)
        else:
            hint_frame = QFrame()
            hint_frame.setObjectName('randomTargetCard')
            hint_layout = QHBoxLayout(hint_frame)
            hint_layout.setContentsMargins(8, 6, 8, 6)

            hint_label = QLabel('未连接任何目标卡片，请从右侧紫色端口拖拽连线')
            hint_label.setWordWrap(True)
            hint_layout.addWidget(hint_label)

            container_layout.addWidget(hint_frame)

        return container
