"""安装、查看和卸载脚本卡片插件；安装不执行包内脚本。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)
from app_core.card_plugins import CardPluginStore, InvalidInstalledCardPlugin, read_package


class CardPluginManagerDialog(QDialog):
    def __init__(self, parent=None, store=None):
        super().__init__(parent)
        self.setObjectName("cardPluginManagerDialog")
        self.setWindowTitle("管理卡片插件")
        self.resize(780, 470)
        self.store = CardPluginStore() if store is None else store
        self._installed = []
        layout = QVBoxLayout(self)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["名称", "版本", "固定标识", "分类", "状态"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, width in ((0, 180), (2, 160), (3, 90)):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(column, width)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        install = QPushButton("导入插件")
        install.clicked.connect(self._install)
        self.uninstall_button = QPushButton("卸载选中插件")
        self.uninstall_button.clicked.connect(self._uninstall)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh)
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        buttons.addWidget(install)
        buttons.addWidget(self.uninstall_button)
        buttons.addWidget(refresh)
        buttons.addStretch()
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self):
        self._installed.clear()
        self.table.setRowCount(0)
        try:
            self._installed = self.store.inspect_installed()
        except Exception as exc:
            self.status.setText("插件列表读取失败：" + str(exc))
            self.uninstall_button.setEnabled(False)
            return False
        self.table.setRowCount(len(self._installed))
        invalid_count = 0
        for row, plugin in enumerate(self._installed):
            if isinstance(plugin, InvalidInstalledCardPlugin):
                invalid_count += 1
                values = [f"失效插件（目录：{plugin.path.parent.parent.name}）", "未知", "未知", "不可用", plugin.error]
            else:
                values = [plugin.manifest[field] for field in ("name", "version", "id", "category")] + ["可用"]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(str(plugin.path) + "\n" + value)
                self.table.setItem(row, column, item)
        self.uninstall_button.setEnabled(bool(self._installed))
        self.status.setText(f"可用 {len(self._installed) - invalid_count} 个，失效 {invalid_count} 个。失效插件不会加载，请选中后手动卸载或重新导出；不会自动转换或删除。工作流中的精确快照不受卸载影响，运行中的插件禁止卸载。")
        return True

    def _install(self):
        filename, _ = QFileDialog.getOpenFileName(self, "导入卡片插件", "", "LCA 卡片插件 (*.lcac)")
        if not filename:
            return
        try:
            bundle = read_package(filename)
            self.store.install(bundle)
        except Exception as exc:
            QMessageBox.warning(self, "导入失败", str(exc))
            return
        if self.refresh():
            QMessageBox.information(self, "导入完成", "插件已安装，可在添加卡片窗口选择。")

    def _uninstall(self):
        row = self.table.currentRow()
        if not 0 <= row < len(self._installed):
            return
        plugin = self._installed[row]
        invalid = isinstance(plugin, InvalidInstalledCardPlugin)
        description = f"失效插件：{plugin.path}\n原因：{plugin.error}" if invalid else f"“{plugin.manifest['name']}”（版本 {plugin.manifest['version']}）"
        answer = QMessageBox.question(self, "卸载卡片插件", f"确认卸载{description}？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            if invalid:
                self.store.uninstall_invalid(plugin)
            else:
                self.store.uninstall(plugin)
        except Exception as exc:
            QMessageBox.warning(self, "无法卸载", str(exc))
            return
        self.refresh()
