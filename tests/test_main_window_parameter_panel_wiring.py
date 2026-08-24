import unittest
from types import SimpleNamespace

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from tasks import get_task_modules
from ui.main_window_parts.main_window_parameter_panel_sync_mixin import (
    MainWindowParameterPanelSyncMixin,
)
from ui.main_window_parts.main_window_workflow_switch_tabs_mixin import (
    MainWindowWorkflowSwitchTabsMixin,
)
from ui.workflow_parts.workflow_view import WorkflowView


class _MainWindowStub(
    QObject,
    MainWindowWorkflowSwitchTabsMixin,
    MainWindowParameterPanelSyncMixin,
):
    # 真实 MainWindow 是 QObject；UniqueConnection 对非 QObject 接收者会静默失效，
    # 因此测试桩必须继承 QObject 才能复现真实接线行为。
    def __init__(self, view):
        super().__init__()
        self.workflow_view = view
        self.workflow_tab_widget = None
        self.task_manager = None
        self.shown_card_ids = []

    def update_status_bar_for_selection(self):
        pass

    def _show_parameter_panel(self, card_id: int):
        self.shown_card_ids.append(card_id)


class ParameterPanelWiringTests(unittest.TestCase):
    """回归：切换工作流后，新增卡片的双击信号必须接到参数面板。"""

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _create_view(self):
        view = WorkflowView(task_modules=get_task_modules(), images_dir="images")
        state_manager = SimpleNamespace(get_current_state=lambda: "stopped")
        view.main_window = SimpleNamespace(task_state_manager=state_manager)
        self.addCleanup(view.clear_workflow)
        return view

    def test_card_added_after_switch_opens_parameter_panel(self):
        view = self._create_view()
        stub = _MainWindowStub(view)

        stub._finish_current_workflow_view_switch(None)

        card = view.add_task_card(0, 0, task_type="模拟鼠标操作")
        self.assertIsNotNone(card, "添加卡片失败")
        self.assertTrue(
            bool(card.property("_mw_param_signal_connected")),
            "新增卡片未接上参数面板信号",
        )

        # 模拟双击卡片：发出编辑请求信号，应触发参数面板显示
        card.edit_settings_requested.emit(card.card_id)
        self.assertEqual(stub.shown_card_ids, [card.card_id])

    def test_existing_cards_are_wired_on_switch(self):
        view = self._create_view()
        card = view.add_task_card(0, 0, task_type="模拟鼠标操作")
        self.assertIsNotNone(card)

        stub = _MainWindowStub(view)
        stub._finish_current_workflow_view_switch(None)

        card.edit_settings_requested.emit(card.card_id)
        self.assertEqual(stub.shown_card_ids, [card.card_id])

    def test_old_view_card_added_is_disconnected(self):
        old_view = self._create_view()
        new_view = self._create_view()
        stub = _MainWindowStub(old_view)
        stub._finish_current_workflow_view_switch(None)

        stub.workflow_view = new_view
        stub._finish_current_workflow_view_switch(old_view)

        # 旧视图新增卡片不应再回调当前主窗口的接线逻辑
        card = old_view.add_task_card(0, 0, task_type="模拟鼠标操作")
        self.assertIsNotNone(card)
        self.assertFalse(bool(card.property("_mw_param_signal_connected")))


if __name__ == "__main__":
    unittest.main()
