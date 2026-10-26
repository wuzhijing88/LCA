"""需要打开 GUI 对话框的参数按钮动作。

任务模块的参数定义里只声明 `action` 名称；凡是要弹窗的实现都放在这里，
这样 tasks 层不需要导入任何 ui 模块。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional


def open_dict_maker(params: Dict[str, Any], **kwargs) -> bool:
    """打开点阵字库制作对话框，并把结果回填到参数面板。"""
    from ui.dialogs.dict_maker_dialog import DictMakerDialog, apply_dict_maker_result_to_panel

    panel = kwargs['parameter_panel']
    images_dir = str(panel.images_dir or '').strip()
    dicts_dir = str(panel.dicts_dir or '').strip()
    if not images_dir or not dicts_dir:
        raise ValueError('当前工程字库目录未绑定，无法制作字库')
    parent = panel
    dialog = DictMakerDialog(
        parent,
        target_hwnd=kwargs.get("target_hwnd"),
        params=params or {},
        images_dir=images_dir,
        dicts_dir=dicts_dir,
    )
    from ui.dialogs.dialog_manager import exec_dialog
    saved = exec_dialog(dialog, read_result=lambda result: (dialog.saved_dict_path, dialog.saved_color_format) if result else None)
    if saved is not None:
        apply_dict_maker_result_to_panel(panel, *saved)
    return True


UI_BUTTON_ACTIONS: Dict[str, Callable[..., Any]] = {
    "open_dict_maker": open_dict_maker,
}


def resolve_ui_button_action(action: str) -> Optional[Callable[..., Any]]:
    return UI_BUTTON_ACTIONS.get(str(action or "").strip())
