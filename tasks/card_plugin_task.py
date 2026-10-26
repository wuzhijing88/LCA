"""通过现行脚本运行器执行带完整插件快照的卡片。"""
from __future__ import annotations

import copy
import logging
import tempfile

from app_core.card_plugins import (
    BUNDLE_PARAMETER, PLUGIN_TASK_TYPE, bundle_from_parameters, running_package, input_parameter_key,
)
from task_workflow.card_plugin_runtime import CardPluginInvocation, plugin_execution_scope
from task_workflow.script_sandbox import run_script
from task_workflow.workflow_context import get_runtime_store

TASK_TYPE = PLUGIN_TASK_TYPE
TASK_NAME = PLUGIN_TASK_TYPE
REQUIRES_INPUT_LOCK = False
SUPPORTED_CONNECTION_TYPES = frozenset({"sequential", "success", "failure"})
logger = logging.getLogger(__name__)


def get_params_definition():
    return {BUNDLE_PARAMETER: {"type": "hidden"}}


class CardPluginTaskAdapter:
    TASK_TYPE = TASK_TYPE
    REQUIRES_INPUT_LOCK = REQUIRES_INPUT_LOCK
    SUPPORTED_CONNECTION_TYPES = SUPPORTED_CONNECTION_TYPES

    def __init__(self, parameters):
        bundle = bundle_from_parameters(parameters)
        if set(parameters) != {BUNDLE_PARAMETER, *(input_parameter_key(name) for name in bundle.manifest["parameters"])}:
            raise ValueError("脚本卡片参数缺失或包含未声明的字段")
        self.TASK_NAME = bundle.manifest["name"]
        self._definitions = bundle.parameter_definitions()
        self._definitions[BUNDLE_PARAMETER] = {"type": "hidden"}

    def get_params_definition(self):
        return copy.deepcopy(self._definitions)

    def execute_task(self, *args, **kwargs):
        return execute_task(*args, **kwargs)


def bind_card(parameters):
    return CardPluginTaskAdapter(parameters)


def execute_task(params, counters, execution_mode="foreground", target_hwnd=None, window_region=None, card_id=None, **kwargs):
    from tasks.script_task import build_script_run_context
    from task_workflow.resource_context import current_package_session, workflow_resource_scope
    from app_core.player.memory_store import has_player_memory_files, list_player_memory_files

    store = get_runtime_store()
    store.bind_counters(counters)
    store.set_current_card_id(card_id)
    store.publish(card_id, kind="card_plugin", ok=False, outputs={})
    try:
        bundle = bundle_from_parameters(params)
        context = build_script_run_context(
            {"script_environment": bundle.manifest["environment"]}, bundle.source,
            counters, execution_mode, target_hwnd, window_region, card_id, **kwargs,
        )
        original_dirs = {key: context.get(key) for key in ("images_dir", "sounds_dir", "dicts_dir", "yolo_dir", "replays_dir", "plugins_dir")}
        with running_package(bundle.digest):
            with tempfile.TemporaryDirectory(prefix="lca-card-") as directory:
                session = current_package_session()
                memory_files = list_player_memory_files() if session is None and has_player_memory_files() else None
                invocation = CardPluginInvocation(bundle, params, directory, original_dirs, package_session=session, files=memory_files)
                try:
                    context.update(invocation.resource_dirs)
                    context["plugin_invocation"] = invocation
                    with plugin_execution_scope(invocation), workflow_resource_scope(**invocation.resource_dirs, package_session=None):
                        success, detail = run_script(bundle.source, store, logger, context=context)
                    outputs = invocation.finish() if success else {}
                finally:
                    invocation.close()
        if not success:
            store.publish(card_id, kind="card_plugin", ok=False, error=detail, outputs={})
            return False, "执行下一步", None, detail or "脚本卡片执行失败"
        store.publish(card_id, kind="card_plugin", ok=True, outputs=outputs)
        return True, "执行下一步", None
    except Exception as exc:
        detail = str(exc)
        logger.error("脚本卡片执行失败：%s", detail)
        store.publish(card_id, kind="card_plugin", ok=False, error=detail, outputs={})
        return False, "执行下一步", None, detail
