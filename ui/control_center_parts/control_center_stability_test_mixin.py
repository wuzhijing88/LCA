from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from ui.control_center_parts.control_center_policy import (
    CONTROL_CENTER_FOREGROUND_BLOCK_MESSAGE,
    control_center_allows_execution_mode,
    resolve_control_center_execution_mode,
)
from ui.control_center_parts.stability_test_builder import generate_stability_pack, scan_stability_assets
from ui.control_center_parts.stability_test_run import (
    apply_generated_assignments,
    assignment_entries_from_paths,
    snapshot_assignments,
)

logger = logging.getLogger(__name__)

STABILITY_TEST_CONFIRM_MESSAGE = (
    "将为每个窗口生成 2～3 条互不相同的随机脚本并立即启动。\n\n"
    "脚本会在已绑定窗口上随机点击、按键、识图、YOLO，可能干扰正在运行的游戏或程序。\n"
    "本次只改中控当前分配，不会写入你原来的配置。停止全部后会恢复原分配。"
)


class ControlCenterStabilityTestMixin:
    def run_stability_test(self):
        if getattr(self, "_is_closing", False):
            return False
        if not control_center_allows_execution_mode(resolve_control_center_execution_mode(self)):
            QMessageBox.warning(self, "无法启动", CONTROL_CENTER_FOREGROUND_BLOCK_MESSAGE)
            return False
        if self._is_parent_window_busy():
            QMessageBox.warning(self, "无法启动", "主窗口正在执行任务，请先停止主窗口任务。")
            return False

        targets = self._stability_test_targets()
        if not targets:
            QMessageBox.information(self, "提示", "没有可测的绑定窗口。")
            return False

        reply = QMessageBox.warning(
            self,
            "稳定性实测",
            STABILITY_TEST_CONFIRM_MESSAGE,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return False

        if self.is_any_task_running():
            self.log_message("稳定性实测：先停止当前任务再换一批脚本")
            self.stop_all_tasks(window_ids=[])
            self._restore_stability_test_assignments()

        try:
            pack_dir = self._stability_test_output_dir()
            assets = scan_stability_assets()
            pack = generate_stability_pack(
                [item["window_id"] for item in targets],
                pack_dir,
                assets=assets,
            )
        except Exception as exc:
            logger.exception("生成稳定性实测脚本失败")
            QMessageBox.warning(self, "生成失败", f"生成随机脚本失败：{exc}")
            return False

        if not getattr(self, "_stability_test_active", False):
            self._stability_test_snapshot = snapshot_assignments(self.window_workflows)

        generated = {}
        for window_id, paths in pack.items():
            generated[window_id] = assignment_entries_from_paths(paths)
            self.log_message(
                f"稳定性实测：窗口{window_id} <- {', '.join(Path(path).name for path in paths)}"
            )
        if assets.images or assets.models or assets.dicts:
            self.log_message(
                "稳定性实测素材：图{images} 模型{models} 字库{dicts}".format(
                    images=len(assets.images),
                    models=len(assets.models),
                    dicts=len(assets.dicts),
                )
            )
        else:
            self.log_message("稳定性实测：未找到图/模型/字库，视觉类卡片将走失败分支")

        apply_generated_assignments(self.window_workflows, generated)
        self._stability_test_active = True
        self._refresh_all_window_workflow_cells()
        self.on_selection_changed()
        self.log_message(f"稳定性实测脚本已生成：{pack_dir}")
        return bool(self.start_all_tasks(window_ids=list(generated.keys()), interactive=True))

    def _stability_test_targets(self):
        targets = []
        for row in self._get_all_rows():
            window_info = self._get_row_window_info(row)
            if not window_info:
                continue
            window_id = self._window_runtime_id(window_info, row)
            if not window_id:
                continue
            targets.append({"row": row, "window_id": str(window_id), "window_info": window_info})
        return targets

    def _stability_test_output_dir(self) -> Path:
        from utils.app_paths import get_runtime_state_dir

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = Path(get_runtime_state_dir("LCA")) / "stability_test" / stamp
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _restore_stability_test_assignments(self):
        snapshot = getattr(self, "_stability_test_snapshot", None)
        if snapshot is None:
            self._stability_test_active = False
            return
        self.window_workflows.clear()
        apply_generated_assignments(self.window_workflows, snapshot)
        self._stability_test_snapshot = None
        self._stability_test_active = False
        try:
            self._refresh_all_window_workflow_cells()
            self.on_selection_changed()
        except Exception:
            logger.debug("恢复稳定性实测分配后刷新表格失败", exc_info=True)
        self.log_message("稳定性实测：已恢复原来的工作流分配")
