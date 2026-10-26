"""脚本卡片参数面板的重置和资源释放。"""
import copy

from app_core.card_plugins import BUNDLE_PARAMETER, PLUGIN_TASK_TYPE


def reset_card_plugin_parameters(panel):
    if panel.current_task_type != PLUGIN_TASK_TYPE:
        raise ValueError("当前参数面板不是脚本卡片")
    values = {BUNDLE_PARAMETER: copy.deepcopy(panel.current_parameters[BUNDLE_PARAMETER])}
    for name, definition in panel.param_definitions.items():
        if name != BUNDLE_PARAMETER:
            values[name] = copy.deepcopy(definition["default"])
    panel.current_parameters = values
    panel.runtime_parameters = {key: value for key, value in panel.runtime_parameters.items() if key[0] != panel.current_card_id}
    panel._release_panel_runtime()
    panel._rebuild_parameter_widgets(preserve_scroll=False)
    values = panel._plugin_parameter_controller.collect()
    panel.current_parameters = copy.deepcopy(values)
    if panel.current_card_id is not None:
        panel.parameters_changed.emit(panel.current_card_id, copy.deepcopy(values))
    panel._opened_parameters_snapshot = copy.deepcopy(values)


def release_card_plugin_panel(panel):
    if panel.current_task_type != PLUGIN_TASK_TYPE:
        return
    panel.current_task_type = None
    timer = getattr(panel, "_update_timer", None)
    if timer is not None:
        timer.stop()
    panel._clear_content()
    panel.current_parameters.clear()
    panel._opened_parameters_snapshot.clear()
    panel.param_definitions = {}
    panel.task_module = None
    panel.current_card_id = None
    panel.current_task_type = None
