"""需要打开 GUI 对话框的参数按钮动作。

任务模块的参数定义里只声明 `action` 名称；凡是要弹窗的实现都放在这里，
这样 tasks 层不需要导入任何 ui 模块。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional


def open_dict_maker(params: Dict[str, Any], **kwargs) -> bool:
    """打开点阵字库制作对话框，并把结果回填到参数面板。"""
    from ui.dialogs.dict_maker_dialog import DictMakerDialog, apply_dict_maker_result_to_panel

    parent = kwargs.get("parameter_panel") or kwargs.get("main_window")
    dialog = DictMakerDialog(
        parent,
        target_hwnd=kwargs.get("target_hwnd"),
        params=params or {},
    )
    if dialog.exec():
        apply_dict_maker_result_to_panel(
            kwargs.get("parameter_panel"),
            dialog.saved_dict_path,
            dialog.saved_color_format,
        )
    return True


UI_BUTTON_ACTIONS: Dict[str, Callable[..., Any]] = {
    "open_dict_maker": open_dict_maker,
}


def resolve_ui_button_action(action: str) -> Optional[Callable[..., Any]]:
    return UI_BUTTON_ACTIONS.get(str(action or "").strip())
