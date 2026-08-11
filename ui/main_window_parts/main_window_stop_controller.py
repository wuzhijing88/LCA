import logging


logger = logging.getLogger(__name__)


RUNTIME_STATE_IDLE = "idle"
_RUNTIME_OWNER_ORDER = ("multi_executor", "executor", "task_manager")


def _normalize_runtime_state(state) -> str:
    state_text = str(state or "").strip().lower()
    return state_text or RUNTIME_STATE_IDLE


def _get_runtime_binding(ctx, owner_name):
    target = getattr(ctx, owner_name, None)
    if target is None:
        return None

    return {
        "owner": owner_name,
        "target": target,
    }


def _get_runtime_state(binding) -> str:
    if not binding:
        return RUNTIME_STATE_IDLE

    target = binding["target"]
    getter = getattr(target, "get_pause_state", None)
    if callable(getter):
        try:
            return _normalize_runtime_state(getter())
        except Exception as exc:
            logger.warning("读取运行时状态失败: owner=%s, error=%s", binding["owner"], exc)

    is_running = getattr(target, "is_running", None)
    if callable(is_running):
        try:
            return "running" if is_running() else RUNTIME_STATE_IDLE
        except Exception:
            return RUNTIME_STATE_IDLE

    return RUNTIME_STATE_IDLE


def _iter_runtime_bindings(ctx):
    yielded = set()
    preferred_owner = str(getattr(ctx, "_runtime_stop_owner", "") or "").strip()
    if not preferred_owner:
        preferred_owner = str(getattr(ctx, "_runtime_pause_owner", "") or "").strip()

    if preferred_owner:
        binding = _get_runtime_binding(ctx, preferred_owner)
        if binding:
            yielded.add(preferred_owner)
            yield binding

    for owner_name in _RUNTIME_OWNER_ORDER:
        if owner_name in yielded:
            continue
        binding = _get_runtime_binding(ctx, owner_name)
        if binding:
            yield binding


def resolve_active_stop_targets(ctx):
    active_bindings = []
    for binding in _iter_runtime_bindings(ctx):
        state = _get_runtime_state(binding)
        if state != RUNTIME_STATE_IDLE:
            active_bindings.append(binding)
    return active_bindings


def _call_executor_stop(executor, force: bool) -> bool:
    request_stop = getattr(executor, "request_stop", None)
    if not callable(request_stop):
        return False

    try:
        result = request_stop(force=bool(force))
    except TypeError:
        result = request_stop()

    if result is None:
        return True
    return bool(result)


def _call_task_manager_stop(task_manager) -> bool:
    stop_all = getattr(task_manager, "stop_all", None)
    if not callable(stop_all):
        return False

    result = stop_all()
    if result is None:
        return True
    return bool(result)


def _call_multi_executor_stop(multi_executor, force: bool) -> bool:
    stop_all = getattr(multi_executor, "stop_all", None)
    if not callable(stop_all):
        return False

    try:
        result = stop_all(force=bool(force))
    except TypeError:
        result = stop_all()

    if result is None:
        return True
    return bool(result)


def _force_stop_binding(binding, force: bool) -> bool:
    owner = binding["owner"]
    target = binding["target"]

    if owner == "task_manager":
        return _call_task_manager_stop(target)
    if owner == "multi_executor":
        return _call_multi_executor_stop(target, force=force)
    if owner == "executor":
        return _call_executor_stop(target, force=force)
    return False


def force_stop_main_window_workflow(ctx, source: str = "manual", force: bool = True) -> bool:
    active_bindings = resolve_active_stop_targets(ctx)
    if not active_bindings:
        logger.warning("没有可停止的活动运行时")
        return False

    all_succeeded = True
    for binding in active_bindings:
        ctx._runtime_stop_owner = binding["owner"]
        try:
            if not _force_stop_binding(binding, force=force):
                logger.warning("停止运行时失败: owner=%s, source=%s", binding["owner"], source)
                all_succeeded = False
        except Exception as exc:
            logger.error("停止运行时异常: owner=%s, source=%s, error=%s", binding["owner"], source, exc)
            all_succeeded = False

    return all_succeeded
