"""从脚本声明导出逻辑插件；窗口只编辑元数据和预览接口。"""
from __future__ import annotations

import copy
import html
from pathlib import Path
import uuid
import weakref

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTextBrowser, QVBoxLayout, QWidget,
)

from app_core.card_plugins import CardPluginError, FORMAT_VERSION, RUNTIME_API_VERSION, build_package, extract_plugin_declarations, read_package, validate_plugin_declarations, write_package
from app_core.script_environments import normalize_environment
from themes import apply_rounded_popup, get_theme_manager

_TYPE_LABELS = {"text": "文本", "int": "整数", "float": "小数", "bool": "真假", "choice": "选项", "object": "字典", "list": "列表"}
_FILE_LABELS = {"image": "图片文件", "sound": "音频文件", "dict": "字库文件", "model": "模型文件", "replay": "回放文件", "component": "组件文件"}


class CardPluginExportDialog(QDialog):
    """参数与输出以源码为准，不提供第二套编辑表格。"""

    def __init__(self, source, environment, parent=None, suggested_name="", *, publication=None):
        environment = normalize_environment(environment)
        if publication is not None:
            fields = {"id", "version", "name", "description", "category", "sha256", "path"}
            if not isinstance(publication, dict) or set(publication) != fields or any(not isinstance(value, str) for value in publication.values()):
                raise CardPluginError("插件发布记录无效，请从现有插件重新读取")
        super().__init__(parent)
        self.setObjectName("cardPluginExportDialog")
        self.setWindowTitle("导出插件")
        self.setModal(True)
        apply_rounded_popup(self, frameless=False)
        self.resize(720, 640)
        self.setMinimumSize(620, 560)
        self._source = source
        self._environment = environment
        self._publication = copy.deepcopy(publication)
        self.exported_path = None
        self._declarations = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(16)
        title = QLabel("发布你的脚本卡片")
        title.setObjectName("cardPluginHeading")
        layout.addWidget(title)
        subtitle = QLabel("接口在脚本中声明，这里只确认名称与版本。")
        subtitle.setObjectName("cardPluginMuted")
        layout.addWidget(subtitle)
        metadata = QGridLayout()
        metadata.setHorizontalSpacing(14)
        metadata.setVerticalSpacing(7)
        self.name_edit = QLineEdit(suggested_name or "我的卡片")
        self.version_edit = QLineEdit("1.0.0")
        self.description_edit = QLineEdit()
        self.description_edit.setPlaceholderText("这张卡片用于完成什么？（选填）")
        metadata.addWidget(QLabel("卡片名称"), 0, 0)
        metadata.addWidget(QLabel("版本"), 0, 1)
        metadata.addWidget(self.name_edit, 1, 0)
        metadata.addWidget(self.version_edit, 1, 1)
        metadata.addWidget(QLabel("说明"), 2, 0, 1, 2)
        metadata.addWidget(self.description_edit, 3, 0, 1, 2)
        metadata.setColumnStretch(0, 3)
        metadata.setColumnStretch(1, 1)
        layout.addLayout(metadata)
        self.continue_button = QPushButton("继续发布已有插件")
        self.continue_button.setToolTip("读取已有 .lcac 的固定标识、版本和说明；当前脚本与接口保持不变。")
        self.continue_button.clicked.connect(self._continue_publication)
        layout.addWidget(self.continue_button, 0, Qt.AlignmentFlag.AlignLeft)
        runtime_choice = "本次导出使用 LCA 托管 Python，不携带本机解释器路径" if environment["mode"] == "isolated" else "本次导出不携带未启用的本机 Python 路径"
        self.managed_python_check = QCheckBox(runtime_choice)
        self.managed_python_check.setToolTip("此选择只影响导出的插件；独立环境将明确使用 LCA 托管 Python，当前脚本的开发环境保持不变。")
        self.managed_python_check.setVisible(bool(environment["interpreter"]))
        layout.addWidget(self.managed_python_check)
        advanced_button = QPushButton("展开高级设置")
        advanced_button.setObjectName("cardPluginAdvancedButton")
        advanced_button.setCheckable(True)
        layout.addWidget(advanced_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.advanced_section = QWidget()
        advanced = QGridLayout(self.advanced_section)
        advanced.setContentsMargins(0, 0, 0, 0)
        advanced.setHorizontalSpacing(14)
        self.id_edit = QLineEdit("user.card." + uuid.uuid4().hex)
        self.id_edit.setToolTip("更新同一个插件时沿用固定标识，并提高版本号。")
        self.category_edit = QLineEdit("自定义卡片")
        advanced.addWidget(QLabel("固定标识"), 0, 0)
        advanced.addWidget(QLabel("分类"), 0, 1)
        advanced.addWidget(self.id_edit, 1, 0)
        advanced.addWidget(self.category_edit, 1, 1)
        advanced.setColumnStretch(0, 3)
        advanced.setColumnStretch(1, 1)
        self.advanced_section.hide()
        if self._publication is not None:
            self._restore_publication_fields()
        advanced_button.toggled.connect(self.advanced_section.setVisible)
        advanced_button.toggled.connect(lambda enabled: advanced_button.setText("收起高级设置" if enabled else "展开高级设置"))
        layout.addWidget(self.advanced_section)
        interface_header = QHBoxLayout()
        interface_title = QLabel("脚本接口")
        interface_title.setObjectName("cardPluginSectionTitle")
        self.interface_summary = QLabel()
        self.interface_summary.setObjectName("cardPluginMuted")
        interface_header.addWidget(interface_title)
        interface_header.addStretch()
        interface_header.addWidget(self.interface_summary)
        layout.addLayout(interface_header)
        self.interface_preview = QTextBrowser()
        self.interface_preview.setObjectName("cardPluginInterfacePreview")
        self.interface_preview.setOpenExternalLinks(False)
        self.interface_preview.setReadOnly(True)
        self.interface_preview.setMinimumHeight(160)
        layout.addWidget(self.interface_preview, 1)
        note = QLabel("仅导出逻辑；图片、模型等文件由工作流参数提供。需要修改接口？请返回脚本编辑声明。")
        note.setObjectName("cardPluginExportNote")
        note.setWordWrap(True)
        layout.addWidget(note)
        footer = QHBoxLayout()
        footer.addStretch()
        cancel = QPushButton("返回编辑")
        cancel.clicked.connect(self.reject)
        self.export_button = QPushButton("导出插件包")
        self.export_button.setProperty("primary", True)
        self.export_button.clicked.connect(self._export)
        footer.addWidget(cancel)
        footer.addWidget(self.export_button)
        layout.addLayout(footer)
        self._refresh_interface_preview()
        manager = get_theme_manager()
        owner = weakref.ref(self)

        def changed(_theme):
            dialog = owner()
            if dialog is not None:
                dialog.update()

        manager.register_theme_change_callback(changed)
        self.destroyed.connect(lambda _=None: manager.unregister_theme_change_callback(changed))

    def _refresh_interface_preview(self):
        try:
            self._declarations = extract_plugin_declarations(self._source)
            validate_plugin_declarations(self._source, self._declarations)
        except ValueError as exc:
            self.interface_summary.setText("声明无效")
            self.interface_preview.setPlainText(str(exc))
            self.export_button.setEnabled(False)
            return
        parameters = self._declarations["parameters"]
        outputs = self._declarations["outputs"]
        self.interface_summary.setText(f"{len(parameters)} 个输入 · {len(outputs)} 个输出")
        sections = []
        for heading, definitions in (("输入参数", parameters), ("输出结果", outputs)):
            if not definitions:
                continue
            sections.append(f"<p><b>{heading}</b></p>")
            for name, definition in definitions.items():
                type_label = _FILE_LABELS[definition["resource_kind"]] if definition["type"] == "file" else _TYPE_LABELS[definition["type"]]
                requirement = "必填" if definition["required"] else "可选"
                parts = [type_label, requirement]
                if "default" in definition:
                    default = definition["default"]
                    default_text = ("真" if default else "假") if isinstance(default, bool) else repr(default)
                    default_label = "默认："
                    parts.append("由工作流选择文件" if definition["type"] == "file" else default_label + default_text)
                for key, label in (("min", "最小"), ("max", "最大"), ("step", "步长"), ("decimals", "小数位")):
                    if key in definition:
                        parts.append(f"{label}：{definition[key]}")
                if "options" in definition:
                    parts.append("选项：" + " / ".join(definition["options"]))
                if "tool" in definition:
                    parts.append("原生工具：" + definition["tool"]["类型"])
                sections.append("<p><b>" + html.escape(name) + "</b>　" + html.escape(" · ".join(parts)) + "<br>" + html.escape(definition["tooltip"]) + "</p>")
        self.interface_preview.setHtml("".join(sections) or "无输入和输出，此插件只执行脚本逻辑。")

    def _restore_publication_fields(self):
        for name in ("id", "version", "name", "description", "category"):
            getattr(self, name + "_edit").setText(self._publication[name])

    def _continue_publication(self):
        filename, _ = QFileDialog.getOpenFileName(self, "继续发布已有插件", "", "LCA 卡片插件 (*.lcac)")
        if not filename:
            return
        try:
            bundle = read_package(filename)
        except ValueError as exc:
            QMessageBox.warning(self, "无法读取插件", str(exc))
            return
        self._publication = self._record_publication(bundle, filename)
        self._restore_publication_fields()

    @staticmethod
    def _record_publication(bundle, filename):
        manifest = bundle.manifest
        return {**{name: manifest[name] for name in ("id", "version", "name", "description", "category")}, "sha256": bundle.digest, "path": filename}

    def publication_record(self):
        return copy.deepcopy(self._publication)

    def build_bundle(self):
        declarations = extract_plugin_declarations(self._source)
        environment = copy.deepcopy(self._environment)
        if environment["interpreter"]:
            if not self.managed_python_check.isChecked():
                raise CardPluginError("当前环境包含本机 Python 路径，请明确勾选不携带本机路径后再导出")
            environment["interpreter"] = ""
        manifest = {
            "format_version": FORMAT_VERSION, "runtime_api": RUNTIME_API_VERSION,
            "id": self.id_edit.text().strip(), "version": self.version_edit.text().strip(),
            "name": self.name_edit.text().strip(), "description": self.description_edit.text().strip(),
            "category": self.category_edit.text().strip(),
            "parameters": declarations["parameters"], "outputs": declarations["outputs"],
            "environment": environment,
        }
        bundle = build_package(manifest, self._source)
        if self._publication is not None and (manifest["id"], manifest["version"]) == (self._publication["id"], self._publication["version"]) and bundle.digest != self._publication["sha256"]:
            raise CardPluginError("相同标识和版本的插件内容发生变化，请修改版本号后再导出")
        return bundle

    def _export(self):
        try:
            bundle = self.build_bundle()
        except ValueError as exc:
            QMessageBox.warning(self, "无法导出", str(exc))
            return
        suggested_path = self._publication["path"] if self._publication is not None else bundle.manifest["name"] + ".lcac"
        filename, _ = QFileDialog.getSaveFileName(self, "导出插件", suggested_path, "LCA 卡片插件 (*.lcac)")
        if not filename:
            return
        try:
            if Path(filename).exists():
                previous = read_package(filename)
                if (previous.manifest["id"], previous.manifest["version"]) == (bundle.manifest["id"], bundle.manifest["version"]) and previous.digest != bundle.digest:
                    raise CardPluginError("目标文件已发布相同标识和版本，但内容不同，请修改版本号后再导出")
            write_package(filename, bundle)
        except ValueError as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", "无法检查目标插件文件，请检查目录权限及文件占用：" + str(exc))
            return
        self.exported_path = filename
        self._publication = self._record_publication(bundle, filename)
        self.accept()
