from ..parameter_panel_support import *


class ParameterPanelSelectorPickerPackageSelectDialogMixin:

    def _create_package_search_edit(self, layout):
        search_edit = QLineEdit()
        search_edit.setPlaceholderText("搜索包名...")
        layout.addWidget(search_edit)
        return search_edit

    def _create_package_list_widget(self, packages, layout):
        list_widget = QListWidget()
        list_widget.addItems(packages)
        layout.addWidget(list_widget)
        return list_widget

    def _apply_package_search_filter(self, list_widget, text):
        needle = text.lower()
        for index in range(list_widget.count()):
            item = list_widget.item(index)
            item.setHidden(needle not in item.text().lower())

    def _apply_selected_package_to_line_edit(self, line_edit, package_name):
        line_edit.setText(package_name)
        param_name = self._update_current_parameter_from_widget(line_edit, package_name)
        if param_name and self.current_card_id is not None:
            self.parameters_changed.emit(self.current_card_id, {param_name: package_name})

    def _create_package_select_dialog(self, packages, line_edit):
        from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

        dialog = QDialog(self)
        dialog.setWindowTitle(f"选择应用包名 (共{len(packages)}个)")
        dialog.setMinimumSize(500, 400)

        layout = QVBoxLayout(dialog)
        info_label = QLabel(f"找到 {len(packages)} 个已安装的第三方应用：")
        layout.addWidget(info_label)

        search_edit = self._create_package_search_edit(layout)
        list_widget = self._create_package_list_widget(packages, layout)
        search_edit.textChanged.connect(
            lambda text, widget=list_widget: self._apply_package_search_filter(widget, text)
        )

        button_layout = QHBoxLayout()
        ok_button = QPushButton("确定")
        cancel_button = QPushButton("取消")
        ok_button.clicked.connect(dialog.accept)
        cancel_button.clicked.connect(dialog.reject)
        button_layout.addWidget(ok_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)

        def on_item_double_clicked(item):
            self._apply_selected_package_to_line_edit(line_edit, item.text())
            dialog.accept()

        list_widget.itemDoubleClicked.connect(on_item_double_clicked)
        return dialog, list_widget
