"""任务节点契约。

注册表（tasks/__init__.py）里的每个 task_type 都对应一个模块，模块分两类：

- 可执行节点（TaskModule）：工作流走到这张卡片时调用 ``execute_task``。
- 监控节点（MonitorModule，目前只有“附加条件”）：不参与顺序执行，工作流启动时调用
  ``register_monitor`` 登记，之后由执行器在目标卡片完成后调用 ``check_monitor_trigger``。

``TASK_TYPE`` 是持久化在工作流文件里的稳定标识，必须与注册表键一致；``TASK_NAME`` 只用于显示。
``validate_task_module`` 在注册表首次加载模块时执行，违反契约会立刻抛出 ``TaskContractError``，
而不是等到运行时才因缺少属性报错。
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, Tuple, runtime_checkable


@runtime_checkable
class TaskModule(Protocol):
    """可执行任务节点模块需要提供的接口。"""

    TASK_TYPE: str
    TASK_NAME: str

    def get_params_definition(self) -> Dict[str, Dict[str, Any]]: ...

    def execute_task(
        self,
        params: Dict[str, Any],
        counters: Dict[str, int],
        execution_mode: str,
        **kwargs: Any,
    ) -> Any:
        """返回 TaskResult，或旧式 (success, action, jump_id[, detail]) 元组；由执行器统一规范化。"""


@runtime_checkable
class MonitorModule(Protocol):
    """监控类节点（附加条件）模块需要提供的接口。"""

    TASK_TYPE: str
    TASK_NAME: str

    def get_params_definition(self) -> Dict[str, Dict[str, Any]]: ...

    def register_monitor(
        self,
        card_id: int,
        parameters: Dict[str, Any],
        context: Any,
        **kwargs: Any,
    ) -> Tuple[bool, str]: ...

    def check_monitor_trigger(
        self,
        monitor_config: Dict[str, Any],
        target_card_result: bool,
        context: Any,
    ) -> Optional[Dict[str, Any]]: ...


# 可选扩展点：存在时必须可调用。
OPTIONAL_TASK_HOOKS = ("requires_input_lock", "get_display_name")


class TaskContractError(TypeError):
    """任务模块不满足契约。"""


def _module_label(module: Any) -> str:
    return str(getattr(module, "__name__", None) or repr(module))


def _require_callable(module: Any, task_type: str, name: str) -> None:
    attr = getattr(module, name, None)
    if not callable(attr):
        raise TaskContractError(f"任务 '{task_type}' 的模块 {_module_label(module)} 缺少可调用的 {name}()")


def _require_identity(module: Any, task_type: str) -> None:
    module_type = getattr(module, "TASK_TYPE", None)
    if module_type != task_type:
        raise TaskContractError(
            f"任务模块 {_module_label(module)} 的 TASK_TYPE={module_type!r} 与注册表键 {task_type!r} 不一致"
        )
    task_name = getattr(module, "TASK_NAME", None)
    if not isinstance(task_name, str) or not task_name.strip():
        raise TaskContractError(f"任务 '{task_type}' 的模块 {_module_label(module)} 缺少非空的 TASK_NAME")


def validate_task_module(module: Any, task_type: str, *, executable: bool = True) -> None:
    """校验模块满足契约；不满足时抛出 TaskContractError。"""
    _require_identity(module, task_type)
    _require_callable(module, task_type, "get_params_definition")
    if executable:
        _require_callable(module, task_type, "execute_task")
    else:
        _require_callable(module, task_type, "register_monitor")
        _require_callable(module, task_type, "check_monitor_trigger")
    for hook in OPTIONAL_TASK_HOOKS:
        attr = getattr(module, hook, None)
        if attr is not None and not callable(attr):
            raise TaskContractError(f"任务 '{task_type}' 的 {hook} 存在但不可调用")


__all__ = [
    "MonitorModule",
    "OPTIONAL_TASK_HOOKS",
    "TaskContractError",
    "TaskModule",
    "validate_task_module",
]
