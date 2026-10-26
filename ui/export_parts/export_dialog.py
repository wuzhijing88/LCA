from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QEvent, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app_core.player.package import ensure_designer_ui
from ui.dialogs.dialog_manager import exec_dialog
from themes import apply_rounded_popup
from app_core.player.window_resolution import normalize_required_client_size
from ui.export_parts.assembler import assemble_standalone_export, safe_export_name
from ui.export_parts.player_dev_run import runtime_config_from_main
from ui.export_parts.player_ui_designer import PlayerUiDesignerDialog
from ui.export_parts.standalone_installer import (
    INNO_CHINESE_LANG_HELP,
    INNO_SETUP_DOWNLOAD_PAGE,
    ExportCancelled,
    MissingChineseLanguageError,
    MissingInnoSetupError,
    OutdatedInnoSetupError,
    require_iscc,
)
from ui.widgets.no_wheel_spinbox import NoWheelSpinBox as _NoWheelSpinBox
from utils.app_paths import get_images_dir, get_sounds_dir, get_user_data_dir

# 全局草稿：关闭「制作独立程序」对话框后仍保留，仅手动重置时清除
_DRAFT_FILENAME = "standalone_export_draft.json"


def _draft_path() -> Path:
    return Path(get_user_data_dir("LCA")) / _DRAFT_FILENAME


def _load_export_draft() -> dict[str, Any]:
    path = _draft_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"读取独立程序导出草稿失败: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"独立程序导出草稿格式无效: {path}")
    return data


def _save_export_draft(
    *,
    ui: Optional[dict],
    asset_map: Optional[dict],
    icon_path: str = "",
    app_name: str = "",
    catalog_ids: Optional[list] = None,
    required_client_width: int = 0,
    required_client_height: int = 0,
) -> None:
    req_w = int(required_client_width or 0)
    req_h = int(required_client_height or 0)
    if req_w < 0 or req_h < 0:
        raise ValueError("独立程序草稿的分辨率不能为负数")
    payload = {
        "ui": deepcopy(ui) if isinstance(ui, dict) else None,
        "asset_map": {
            str(k): str(v)
            for k, v in dict(asset_map or {}).items()
            if str(k).strip() and str(v).strip()
        },
        "icon_path": str(icon_path or "").strip(),
        "app_name": str(app_name or "").strip(),
        "catalog_ids": [str(x).strip() for x in (catalog_ids or []) if str(x).strip()],
        "required_client_width": req_w,
        "required_client_height": req_h,
    }
    path = _draft_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        raise OSError(f"保存独立程序导出草稿失败: {path}") from exc


def _clear_export_draft() -> None:
    path = _draft_path()
    path.unlink(missing_ok=True)


def _default_desktop_dir() -> Path:
    """使用 Windows 桌面目录，不猜测重定向后的目录。"""
    import ctypes
    from ctypes import wintypes

    buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
    result = ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf)
    if result != 0 or not Path(buf.value).is_dir():
        raise OSError("无法读取当前用户的桌面目录")
    return Path(buf.value)


class _AssembleWorker(QThread):
    progress = Signal(int, str)

    def __init__(self, kwargs: dict, *, catalog: list, entry_id: str, parent):
        super().__init__(parent)
        self._kwargs = deepcopy(kwargs)
        self._catalog = deepcopy(catalog)
        self._entry_id = entry_id
        self.setup_path = None
        self.error = None
        self.warnings = []
        # 直接销毁父窗口也必须先等后台释放子进程和临时目录。
        parent.destroyed.connect(self.cancel_and_wait)

    def cancel_and_wait(self, *_args):
        self.requestInterruption()
        self.wait()

    def _check_cancelled(self):
        if self.isInterruptionRequested():
            raise ExportCancelled("已取消制作安装包")

    def run(self):
        try:
            from ui.export_parts.export_scripts import apply_catalog_to_ui_exclusive, collect_multi_script_package

            def on_progress(value: int, message: str):
                self.progress.emit(int(value), str(message or ""))

            self._check_cancelled()
            require_iscc()
            on_progress(1, "正在收集工作流资源…")
            collection, scripts_meta = collect_multi_script_package(
                self._catalog, entry_id=self._entry_id, cancel_check=self._check_cancelled,
            )
            self._check_cancelled()
            if collection.errors:
                raise ValueError("导出前需要先处理这些问题：\n\n" + "\n".join(collection.errors[:12]))
            self.warnings = list(collection.warnings)
            self.setup_path = assemble_standalone_export(
                progress=on_progress,
                cancel_check=self._check_cancelled,
                collection=collection,
                scripts=scripts_meta,
                entry_script_id=self._entry_id,
                ui=apply_catalog_to_ui_exclusive(self._kwargs.pop("ui"), self._catalog),
                **self._kwargs,
            )
        except Exception as exc:
            self.error = exc
            # 不让异常回溯继续持有整份工作流、资源字节和构建局部对象。
            exc.__traceback__ = None
        finally:
            self._kwargs.clear()
            self._catalog.clear()


class StandaloneExportDialog(QDialog):
    """轻量导出：名称/路径/图标 + 独立界面设计器。"""

    def __init__(self, main_window, parent=None):
        super().__init__(parent or main_window)
        self._main = main_window
        self.setWindowTitle("制作独立程序")
        self.setMinimumWidth(560)
        self.resize(600, 460)
        self._output_follows_name = True
        self._ui_payload = None
        self._ui_asset_map: dict[str, str] = {}
        self._worker: _AssembleWorker | None = None
        self._closing = False
        self._progress: QProgressDialog | None = None
        self._export_app_name = ""
        self._export_warnings: list[str] = []
        self._export_catalog: list[dict[str, Any]] = []
        self._draft_catalog_ids: list[str] = []

        draft = _load_export_draft()
        draft_ui = draft.get("ui") if isinstance(draft.get("ui"), dict) else None
        draft_assets = draft.get("asset_map") if isinstance(draft.get("asset_map"), dict) else {}
        draft_icon = str(draft.get("icon_path") or "").strip()
        draft_name = str(draft.get("app_name") or "").strip()
        raw_ids = draft.get("catalog_ids")
        if isinstance(raw_ids, list):
            self._draft_catalog_ids = [str(x).strip() for x in raw_ids if str(x).strip()]
        draft_w = int(draft.get("required_client_width") or 0)
        draft_h = int(draft.get("required_client_height") or 0)
        if draft_w < 0 or draft_h < 0:
            raise ValueError("独立程序草稿的分辨率不能为负数")
        draft_req = (draft_w, draft_h)

        default_name = draft_name or self._default_app_name()
        self._desktop_dir = _default_desktop_dir()
        if isinstance(draft_ui, dict):
            self._ui_payload = deepcopy(draft_ui)
        self._ui_asset_map = {
            str(k): str(v)
            for k, v in dict(draft_assets or {}).items()
            if str(k).strip() and str(v).strip()
        }

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(14)

        field_h = 32

        def _form_label(text: str) -> QLabel:
            lab = QLabel(text)
            lab.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lab.setMinimumHeight(field_h)
            return lab

        def _browse_btn(slot) -> QPushButton:
            btn = QPushButton("浏览…")
            btn.setFixedSize(76, field_h)
            btn.clicked.connect(slot)
            return btn

        basic = QGroupBox("基本信息")
        basic_form = QFormLayout(basic)
        basic_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        basic_form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        basic_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        basic_form.setHorizontalSpacing(14)
        basic_form.setVerticalSpacing(12)
        basic_form.setContentsMargins(14, 18, 14, 14)

        self._name_edit = QLineEdit(default_name)
        self._name_edit.setPlaceholderText("安装后显示的程序名")
        self._name_edit.setClearButtonEnabled(True)
        self._name_edit.setMinimumHeight(field_h)
        self._name_edit.textChanged.connect(self._on_name_changed)
        self._name_edit.textChanged.connect(self._persist_draft)
        basic_form.addRow(_form_label("程序名称"), self._name_edit)

        self._output_edit = QLineEdit(str(self._desktop_dir / safe_export_name(default_name)))
        self._output_edit.setPlaceholderText("安装包保存目录")
        self._output_edit.setMinimumHeight(field_h)
        self._output_edit.textEdited.connect(self._on_output_edited)
        output_row = QHBoxLayout()
        output_row.setContentsMargins(0, 0, 0, 0)
        output_row.setSpacing(8)
        output_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        output_row.addWidget(self._output_edit, 1)
        output_row.addWidget(_browse_btn(self._choose_output), 0)
        basic_form.addRow(_form_label("保存位置"), output_row)

        self._icon_edit = QLineEdit(draft_icon)
        self._icon_edit.setPlaceholderText("可选，默认使用内置图标")
        self._icon_edit.setClearButtonEnabled(True)
        self._icon_edit.setMinimumHeight(field_h)
        self._icon_edit.textChanged.connect(self._persist_draft)
        icon_row = QHBoxLayout()
        icon_row.setContentsMargins(0, 0, 0, 0)
        icon_row.setSpacing(8)
        icon_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        icon_row.addWidget(self._icon_edit, 1)
        icon_row.addWidget(_browse_btn(self._choose_icon), 0)
        basic_form.addRow(_form_label("程序图标"), icon_row)

        root.addWidget(basic)

        res_box = QGroupBox("指定分辨率")
        res_layout = QHBoxLayout(res_box)
        res_layout.setContentsMargins(14, 18, 14, 14)
        res_layout.setSpacing(10)
        res_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        width_lab = QLabel("宽度")
        width_lab.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        width_lab.setMinimumHeight(field_h)
        self._req_width_spin = _NoWheelSpinBox()
        self._req_width_spin.setRange(0, 9999)
        self._req_width_spin.setValue(draft_req[0])
        self._req_width_spin.setMinimumHeight(field_h)
        self._req_width_spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._req_width_spin.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._req_width_spin.setToolTip("绑定窗口客户区宽度，必须大于 0")
        self._req_width_spin.valueChanged.connect(self._persist_draft)

        height_lab = QLabel("高度")
        height_lab.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        height_lab.setMinimumHeight(field_h)
        self._req_height_spin = _NoWheelSpinBox()
        self._req_height_spin.setRange(0, 9999)
        self._req_height_spin.setValue(draft_req[1])
        self._req_height_spin.setMinimumHeight(field_h)
        self._req_height_spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._req_height_spin.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._req_height_spin.setToolTip("绑定窗口客户区高度，必须大于 0")
        self._req_height_spin.valueChanged.connect(self._persist_draft)

        res_layout.addWidget(width_lab, 0)
        res_layout.addWidget(self._req_width_spin, 1)
        res_layout.addSpacing(8)
        res_layout.addWidget(height_lab, 0)
        res_layout.addWidget(self._req_height_spin, 1)

        root.addWidget(res_box)

        ui_box = QGroupBox("运行界面")
        ui_layout = QVBoxLayout(ui_box)
        ui_layout.setContentsMargins(14, 18, 14, 14)
        ui_layout.setSpacing(10)

        self._design_status = QLabel("未定制（将使用默认界面）")
        self._design_status.setWordWrap(True)
        self._design_status.setObjectName("StandaloneExportDesignStatus")
        ui_layout.addWidget(self._design_status)

        design_row = QHBoxLayout()
        design_row.setContentsMargins(0, 0, 0, 0)
        design_row.setSpacing(8)
        self._design_btn = QPushButton("设计运行界面")
        self._design_btn.setMinimumHeight(32)
        self._design_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._design_btn.clicked.connect(self._open_designer)
        self._reset_design_btn = QPushButton("重置")
        self._reset_design_btn.setMinimumHeight(32)
        self._reset_design_btn.setFixedWidth(76)
        self._reset_design_btn.setToolTip("清除已保存的自定义界面，恢复默认")
        self._reset_design_btn.clicked.connect(self._reset_design)
        design_row.addWidget(self._design_btn, 1)
        design_row.addWidget(self._reset_design_btn, 0)
        ui_layout.addLayout(design_row)
        root.addWidget(ui_box)

        self._refresh_design_status()
        root.addStretch(1)

        buttons = QDialogButtonBox(self)
        self._export_button = buttons.addButton("制作安装包", QDialogButtonBox.ButtonRole.AcceptRole)
        self._cancel_button = buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        self._export_button.setDefault(True)
        self._export_button.setMinimumWidth(112)
        self._export_button.setMinimumHeight(32)
        self._cancel_button.setMinimumHeight(32)
        self._export_button.clicked.connect(self._export)
        self._cancel_button.clicked.connect(self.reject)
        root.addWidget(buttons)

    def _default_app_name(self) -> str:
        default_name = "独立程序"
        current_task = self._current_task()
        if current_task is None:
            return default_name
        name = str(getattr(current_task, "name", "") or "").strip()
        if name.lower().endswith(".lca"):
            name = name[:-4]
        return name or default_name

    def _on_output_edited(self, _text: str):
        self._output_follows_name = False

    def _on_name_changed(self, text: str):
        if not self._output_follows_name:
            return
        name = safe_export_name(text.strip() or "独立程序")
        self._output_edit.setText(str(self._desktop_dir / name))

    def _choose_icon(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择图标", "", "图标 (*.ico);;所有文件 (*.*)")
        if path:
            self._icon_edit.setText(path)

    def _choose_output(self):
        start = self._output_edit.text().strip() or str(self._desktop_dir)
        path = QFileDialog.getExistingDirectory(self, "选择保存位置", start)
        if not path:
            return
        name = safe_export_name(self._name_edit.text().strip() or "独立程序")
        chosen = Path(path)
        if chosen.name != name:
            chosen = chosen / name
        self._output_follows_name = False
        self._output_edit.setText(str(chosen))

    def _has_custom_design(self) -> bool:
        return isinstance(self._ui_payload, dict) or bool(self._ui_asset_map)

    def _refresh_design_status(self):
        customized = self._has_custom_design()
        self._design_status.setProperty("customized", customized)
        self._design_status.style().unpolish(self._design_status)
        self._design_status.style().polish(self._design_status)
        if not self._has_custom_design():
            self._design_status.setText("当前使用默认运行界面。可点下方按钮打开设计器定制。")
            self._reset_design_btn.setEnabled(False)
            return
        widget_count = len((self._ui_payload or {}).get("widgets") or [])
        self._design_status.setText(f"已定制界面（{widget_count} 个控件），关闭本对话框也会保留。")
        self._reset_design_btn.setEnabled(True)

    def _persist_draft(self, *_args):
        catalog_ids = [str(item.get("id") or "") for item in self._export_catalog if item.get("id")]
        if not catalog_ids:
            catalog_ids = list(self._draft_catalog_ids)
        req_w = int(self._req_width_spin.value())
        req_h = int(self._req_height_spin.value())
        # 无定制、无图标、无目录勾选、无分辨率时不写空草稿
        if (
            not self._has_custom_design()
            and not self._icon_edit.text().strip()
            and not catalog_ids
            and req_w <= 0
            and req_h <= 0
        ):
            return
        _save_export_draft(
            ui=self._ui_payload,
            asset_map=self._ui_asset_map,
            icon_path=self._icon_edit.text().strip(),
            app_name=self._name_edit.text().strip(),
            catalog_ids=catalog_ids,
            required_client_width=req_w,
            required_client_height=req_h,
        )

    def _reset_design(self):
        if self._is_exporting():
            return
        if not self._has_custom_design() and not self._icon_edit.text().strip():
            return
        answer = QMessageBox.question(
            self,
            "重置界面",
            "确定清除已保存的自定义运行界面？\n关闭对话框不会丢失设计；只有确认重置才会清除。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._ui_payload = None
        self._ui_asset_map = {}
        self._icon_edit.blockSignals(True)
        self._icon_edit.clear()
        self._icon_edit.blockSignals(False)
        _clear_export_draft()
        self._refresh_design_status()

    def _required_client_size(self) -> tuple[int, int]:
        return normalize_required_client_size(
            self._req_width_spin.value(),
            self._req_height_spin.value(),
        )

    def _validate_required_client_size(self) -> bool:
        width = int(self._req_width_spin.value())
        height = int(self._req_height_spin.value())
        if width > 0 and height > 0:
            return True
        QMessageBox.warning(
            self,
            "无法继续",
            "请填写宽度和高度，且都必须大于 0。\n"
            "该尺寸将写入独立程序，绑定窗口时会按此自动调整。",
        )
        if width <= 0:
            self._req_width_spin.setFocus()
        else:
            self._req_height_spin.setFocus()
        return False

    def _ensure_export_catalog(self, *, force_prompt: bool = False) -> bool:
        """扫描工作区并弹出剔除对话框；成功则写入 self._export_catalog。"""
        from ui.export_parts.export_scripts import list_workspace_export_scripts
        from ui.export_parts.workspace_export_dialog import WorkspaceExportPickerDialog

        full = list_workspace_export_scripts(self._main)
        if not full:
            from ui.export_parts.export_scripts import workspace_dirs_from_main

            if not workspace_dirs_from_main(self._main):
                msg = "侧栏尚未添加工作区目录。请先在收藏面板添加工作区，无需打开工作流标签。"
            else:
                msg = "侧栏工作区目录下没有可打包的工作流（需已落盘且含卡片）。"
            QMessageBox.warning(self, "无法继续", msg)
            return False
        if self._export_catalog and not force_prompt:
            # 目录仍有效：只保留仍存在于工作区的项
            by_id = {str(item.get("id") or ""): item for item in full}
            kept = [dict(by_id[i["id"]]) for i in self._export_catalog if i.get("id") in by_id]
            if kept:
                self._export_catalog = kept
                return True
        pre = {str(i.get("id") or "") for i in self._export_catalog if i.get("id")}
        if not pre and self._draft_catalog_ids:
            pre = set(self._draft_catalog_ids)
        dlg = WorkspaceExportPickerDialog(
            full,
            preselected_ids=pre or None,
            parent=self,
        )
        selected = exec_dialog(
            dlg,
            read_result=lambda result: dlg.selected_catalog() if result == QDialog.DialogCode.Accepted else None,
        )
        if selected is None:
            return False
        self._export_catalog = selected
        self._draft_catalog_ids = [str(i.get("id") or "") for i in self._export_catalog if i.get("id")]
        self._persist_draft()
        return bool(self._export_catalog)

    def _session_catalog(self) -> list[dict[str, Any]]:
        return list(self._export_catalog or [])

    def _default_entry_id(self, catalog: list[dict[str, Any]], ui: Optional[dict] = None) -> str:
        from ui.export_parts.export_scripts import default_entry_script_id

        return default_entry_script_id(ui or self._ui_payload, catalog)

    def _live_run_context(self) -> dict:
        if not self._export_catalog:
            raise RuntimeError("请先选择要打包的工作流")
        required_width, required_height = self._required_client_size()
        catalog = self._session_catalog()
        entry_id = self._default_entry_id(catalog)
        entry = next((item for item in catalog if item.get("id") == entry_id), None)
        if entry is None:
            raise ValueError(f"入口脚本不在导出目录中: {entry_id}")
        workflow_data = dict(entry.get("workflow_data") or {})
        parent_file = str(entry.get("filepath") or "")
        from task_workflow.workspace import resolve_runtime_resource_dirs

        resource_dirs = resolve_runtime_resource_dirs(
            workflow_data,
            workflow_filepath=parent_file,
            default_images_dir=str(getattr(self._main, "images_dir", "") or get_images_dir("LCA")),
        )
        return {
            "workflow_data": workflow_data,
            "config": runtime_config_from_main(self._main),
            "images_dir": str(resource_dirs.get("images_dir") or get_images_dir("LCA")),
            "sounds_dir": str(resource_dirs.get("sounds_dir") or get_sounds_dir("LCA")),
            "parent_workflow_file": parent_file,
            "app_name": self._name_edit.text().strip() or "独立程序",
            "required_client_width": required_width,
            "required_client_height": required_height,
            "script_catalog": catalog,
            "entry_script_id": entry_id,
        }

    def _open_designer(self):
        if self._is_exporting():
            return
        if not self._validate_required_client_size():
            return
        if not self._ensure_export_catalog():
            return
        from ui.export_parts.export_scripts import (
            apply_catalog_to_ui_exclusive,
            assigned_script_ids,
        )

        app_name = self._name_edit.text().strip() or "独立程序"
        catalog = self._session_catalog()
        seed_base = self._ui_payload or {}
        seed_ui = apply_catalog_to_ui_exclusive(
            seed_base,
            catalog,
            append_missing=not bool(assigned_script_ids(seed_base)),
        )
        dialog = PlayerUiDesignerDialog(
            self,
            app_name=app_name,
            ui=seed_ui,
            asset_map=self._ui_asset_map,
            live_run_context=self._live_run_context,
            script_catalog=self._session_catalog,
        )
        designed = exec_dialog(
            dialog,
            read_result=lambda result: (
                dialog.result_ui, dict(dialog.result_asset_map or {})
            ) if result == QDialog.DialogCode.Accepted else None,
        )
        if designed is None:
            return
        self._ui_payload, self._ui_asset_map = designed
        self._refresh_design_status()
        self._persist_draft()

    def _current_workflow(self):
        workflow_view = getattr(self._main, "workflow_view", None)
        if workflow_view is None:
            raise RuntimeError("当前没有打开的工作流")
        workflow_data = workflow_view.serialize_workflow()
        if not workflow_data.get("cards"):
            raise RuntimeError("当前工作流没有卡片")
        return workflow_data

    def _current_task(self):
        tab_widget = getattr(self._main, "workflow_tab_widget", None)
        task_manager = getattr(self._main, "task_manager", None)
        if tab_widget is None or task_manager is None:
            return None
        task_id = tab_widget.get_current_task_id()
        if task_id is None:
            return None
        return task_manager.get_task(task_id)

    def _parent_workflow_file(self) -> str:
        task = self._current_task()
        return str(getattr(task, "filepath", "") or "") if task is not None else ""

    def _flush_parameter_panel_for_export(self) -> None:
        """导出前把参数面板未点「应用」的编辑写回卡片，避免漏掉刚填的路径。"""
        panel = getattr(self._main, "parameter_panel", None)
        if panel is None:
            return
        if getattr(panel, "current_card_id", None) is None:
            return
        panel._apply_parameters(auto_close=False)

    def _prompt_inno_setup_download(self, *, title: str, text: str, detail: str = ""):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(title)
        box.setText(text)
        box.setInformativeText(
            "请安装完成后再试。Inno Setup 不随本程序打包，以免增大体积。\n\n"
            + (
                detail.strip()
                if detail
                else f"下载页面：\n{INNO_SETUP_DOWNLOAD_PAGE}"
            )
        )
        open_btn = box.addButton("打开下载页", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("稍后再说", QMessageBox.ButtonRole.RejectRole)
        open_download = exec_dialog(box, read_result=lambda _result: box.clickedButton() == open_btn)
        if open_download:
            QDesktopServices.openUrl(QUrl(INNO_SETUP_DOWNLOAD_PAGE))

    def _prompt_install_inno_setup(self, detail: str = ""):
        self._prompt_inno_setup_download(
            title="请先安装 Inno Setup",
            text="制作安装包需要本机已安装 Inno Setup 6.3 或更高版本。",
            detail=detail,
        )

    def _prompt_outdated_inno_setup(self, detail: str = ""):
        self._prompt_inno_setup_download(
            title="Inno Setup 版本过旧",
            text="本机 Inno Setup 版本过旧或无法确认，需要 6.3 或更高版本才能制作安装包。",
            detail=detail,
        )

    def _prompt_missing_chinese_language(self, detail: str = ""):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("缺少 Inno 中文语言包")
        box.setText("本机 Inno Setup 缺少简体中文语言包（ChineseSimplified.isl）。")
        box.setInformativeText(
            detail.strip()
            if detail
            else (
                "请下载 ChineseSimplified.isl，放到 Inno Setup 的 Languages 目录后再试。\n\n"
                f"语言包下载：\n{INNO_CHINESE_LANG_HELP}"
            )
        )
        open_btn = box.addButton("打开下载页", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("知道了", QMessageBox.ButtonRole.RejectRole)
        open_download = exec_dialog(box, read_result=lambda _result: box.clickedButton() == open_btn)
        if open_download:
            QDesktopServices.openUrl(QUrl(INNO_CHINESE_LANG_HELP))

    def _is_exporting(self) -> bool:
        return self._worker is not None

    def _cancel_export(self):
        self._closing = True
        if self._worker is not None:
            self._worker.requestInterruption()
        self._close_progress()

    def reject(self):
        self._cancel_export()
        super().reject()

    def closeEvent(self, event):
        self._cancel_export()
        self._persist_draft()
        super().closeEvent(event)

    def event(self, event):
        if event.type() == QEvent.Type.DeferredDelete and self._worker is not None:
            self._cancel_export()
            self._disconnect_worker_signals()
            self._worker.cancel_and_wait()
        return super().event(event)

    def _set_busy(self, busy: bool):
        self._export_button.setEnabled(not busy)
        self._cancel_button.setEnabled(True)
        self._name_edit.setEnabled(not busy)
        self._output_edit.setEnabled(not busy)
        self._icon_edit.setEnabled(not busy)
        self._req_width_spin.setEnabled(not busy)
        self._req_height_spin.setEnabled(not busy)
        self._design_btn.setEnabled(not busy)
        self._reset_design_btn.setEnabled(False if busy else self._has_custom_design())
        self._export_button.setText("制作中…" if busy else "制作安装包")

    def _disconnect_worker_signals(self):
        worker = self._worker
        if worker is None:
            return
        for signal, slot in (
            (worker.progress, self._on_export_progress),
            (worker.finished, self._on_export_finished),
        ):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    def _close_progress(self):
        progress = self._progress
        self._progress = None
        if progress is None:
            return
        try:
            progress.canceled.disconnect(self.reject)
            progress.hide()
            progress.close()
            progress.deleteLater()
        except RuntimeError:
            pass

    def _on_export_progress(self, value: int, message: str):
        progress = self._progress
        if progress is None:
            return
        try:
            progress.setValue(int(value))
            text = str(message or "").strip()
            if text:
                progress.setLabelText(text)
        except RuntimeError:
            # 进度框已销毁或正在关闭
            self._progress = None

    def _on_export_finished(self):
        worker = self._worker
        if worker is None:
            return
        self._disconnect_worker_signals()
        self._worker = None
        error, setup_path = worker.error, worker.setup_path
        self._export_warnings = worker.warnings
        worker.deleteLater()
        self._close_progress()
        if self._closing or isinstance(error, ExportCancelled):
            return
        self._set_busy(False)
        if error is not None:
            self._on_export_failed(error)
        else:
            self._on_export_succeeded(setup_path)

    def _on_export_succeeded(self, setup_path):
        notes = []
        if self._export_warnings:
            notes.append("注意：\n" + "\n".join(self._export_warnings[:8]))
        extra = ("\n\n" + "\n\n".join(notes)) if notes else ""
        QMessageBox.information(
            self,
            "制作完成",
            f"已生成安装包：\n{setup_path}\n\n"
            f"安装后主程序为「{safe_export_name(self._export_app_name)}.exe」。{extra}",
        )
        self.accept()

    def _on_export_failed(self, exc):
        if isinstance(exc, MissingInnoSetupError):
            self._prompt_install_inno_setup(str(exc))
            return
        if isinstance(exc, OutdatedInnoSetupError):
            self._prompt_outdated_inno_setup(str(exc))
            return
        if isinstance(exc, MissingChineseLanguageError):
            self._prompt_missing_chinese_language(str(exc))
            return
        QMessageBox.critical(self, "制作失败", str(exc))

    def _export(self):
        try:
            self._start_export()
        except Exception as exc:
            worker = self._worker
            if worker is not None:
                worker.cancel_and_wait()
                self._disconnect_worker_signals()
                self._worker = None
                worker.deleteLater()
            self._close_progress()
            self._set_busy(False)
            QMessageBox.critical(self, "无法制作", str(exc))

    def _start_export(self):
        if self._is_exporting():
            return

        from ui.export_parts.export_scripts import (
            apply_catalog_to_ui_exclusive,
            assert_script_lists_exclusive,
            select_scripts_for_export,
        )

        output_text = self._output_edit.text().strip()
        if not output_text:
            QMessageBox.warning(self, "无法制作", "请选择保存位置")
            return
        output_dir = Path(output_text)
        self._flush_parameter_panel_for_export()

        if not self._validate_required_client_size():
            return
        if not self._ensure_export_catalog():
            return

        app_name = self._name_edit.text().strip() or "独立程序"
        required_width, required_height = self._required_client_size()

        catalog = self._session_catalog()
        if not catalog:
            QMessageBox.warning(self, "无法制作", "没有可导出的脚本（请先在工作区选择工作流）")
            return
        ui_seed = ensure_designer_ui(self._ui_payload or {}, app_name=app_name)
        conflict = assert_script_lists_exclusive(ui_seed)
        if conflict:
            QMessageBox.warning(self, "无法制作", conflict)
            return
        entry_id = self._default_entry_id(catalog, ui_seed)
        export_catalog = select_scripts_for_export(
            catalog,
            entry_id=entry_id,
            ui=ui_seed,
        )
        ui = apply_catalog_to_ui_exclusive(ui_seed, export_catalog)
        # 标题跟随程序名（若用户未在设计器里改过，仍以程序名为准）
        if not self._ui_payload:
            ui["title"] = app_name

        self._export_app_name = app_name
        kwargs = {
            "output_dir": output_dir,
            "app_name": app_name,
            "description": "",
            "ui": ui,
            "icon_path": self._icon_edit.text().strip(),
            "company": "",
            "version": "1.0.0",
            "ui_asset_map": self._ui_asset_map,
            "required_client_width": required_width,
            "required_client_height": required_height,
            "runtime_config": runtime_config_from_main(self._main),
        }
        self._set_busy(True)

        self._closing = False
        self._progress = QProgressDialog("正在准备制作安装包…", "取消", 0, 100, self)
        self._progress.setWindowTitle("制作安装包")
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress.setMinimumDuration(0)
        self._progress.canceled.connect(self.reject)
        apply_rounded_popup(self._progress, frameless=False)
        self._progress.setValue(0)
        self._progress.setAutoClose(False)
        self._progress.setAutoReset(False)
        self._progress.setMinimumWidth(420)
        self._progress.show()

        worker = _AssembleWorker(
            kwargs,
            catalog=export_catalog,
            entry_id=entry_id,
            parent=self,
        )
        worker.progress.connect(self._on_export_progress)
        worker.finished.connect(self._on_export_finished)
        self._worker = worker
        worker.start()
