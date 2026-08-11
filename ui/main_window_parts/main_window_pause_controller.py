import logging


logger = logging.getLogger(__name__)


PAUSE_STATE_IDLE = "idle"
PAUSE_STATE_RUNNING = "running"
PAUSE_STATE_PAUSED = "paused"

_RUNTIME_OWNER_ORDER = ("multi_executor", "executor", "task_manager")


def _normalize_pause_state(state) -> str:
    state_text = str(state or "").strip().lower()
    if state_text in (PAUSE_STATE_IDLE, PAUSE_STATE_RUNNING, PAUSE_STATE_PAUSED):
        return state_text
    return PAUSE_STATE_IDLE


def _get_runtime_binding(ctx, owner_name):
    target = getattr(ctx, owner_name, None)
    if target is None:
        return None

    if owner_name == "task_manager":
        return {
            "owner": owner_name,
            "target": target,
            "pause_method": "pause_all_tasks",
            "resume_method": "resume_all_tasks",
        }

    if owner_name == "multi_executor":
        return {
            "owner": owner_name,
            "target": target,
            "pause_method": "pause_all",
            "resume_method": "resume_all",
        }

    if owner_name == "executor":
        return {
            "owner": owner_name,
            "target": target,
            "pause_method": "pause",
            "resume_method": "resume",
        }

    return None


def _get_binding_pause_state(binding) -> str:
    if not binding:
        return PAUSE_STATE_IDLE

    target = binding["target"]
    getter = getattr(target, "get_pause_state", None)
    if not callable(getter):
        return PAUSE_STATE_IDLE

    try:
        return _normalize_pause_state(getter())
    except Exception as exc:
        logger.warning("读取暂停状态失败: owner=%s, error=%s", binding["owner"], exc)
        return PAUSE_STATE_IDLE


def _iter_runtime_bindings(ctx):
    yielded = set()

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


def resolve_main_window_pause_target(ctx):
    for binding in _iter_runtime_bindings(ctx):
        state = _get_binding_pause_state(binding)
        if state != PAUSE_STATE_IDLE:
            return binding, state
    return None, PAUSE_STATE_IDLE


def get_main_window_pause_state(ctx) -> str:
    _binding, state = resolve_main_window_pause_target(ctx)
    return state


def _call_runtime_method(binding, action: str) -> bool:
    method_name = binding["pause_method"] if action == "pause" else binding["resume_method"]
    method = getattr(binding["target"], method_name, None)
    if not callable(method):
        logger.warning("运行时缺少暂停控制方法: owner=%s, action=%s", binding["owner"], action)
        return False

    result = method()
    if result is None:
        return True
    return bool(result)


def _sync_pause_flags(ctx, paused: bool, source: str) -> None:
    if hasattr(ctx, "_is_paused"):
        ctx._is_paused = bool(paused)

    if not hasattr(ctx, "_auto_pause_source"):
        return

    if source in ("timed", "random"):
        ctx._auto_pause_source = source if paused else None
        return

    ctx._auto_pause_source = None


def _sync_pause_ui(ctx, paused: bool, source: str) -> None:
    try:
        if paused:
            if hasattr(ctx, "_set_button_to_paused_state"):
                ctx._set_button_to_paused_state()
        else:
            if hasattr(ctx, "_set_button_to_running_state"):
                ctx._set_button_to_running_state()

        if hasattr(ctx, "_set_line_animation_paused"):
            ctx._set_line_animation_paused("task_runtime", bool(paused))

        floating_controller = getattr(ctx, "_floating_controller", None)
        if floating_controller:
            if paused and hasattr(floating_controller, "on_workflow_paused"):
                floating_controller.on_workflow_paused()
            elif not paused and hasattr(floating_controller, "on_workflow_resumed"):
                floating_controller.on_workflow_resumed()

        _sync_pause_flags(ctx, paused=paused, source=source)
    except Exception as exc:
        logger.error("同步暂停UI状态失败: paused=%s, error=%s", paused, exc)


def set_main_window_pause_state(ctx, paused: bool, error_context=None, source: str = "manual") -> bool:
    binding, state = resolve_main_window_pause_target(ctx)
    desired_state = PAUSE_STATE_PAUSED if paused else PAUSE_STATE_RUNNING

    if binding is None:
        logger.warning("没有可用于暂停控制的活动运行时")
        return False

    ctx._runtime_pause_owner = binding["owner"]

    if state == desired_state:
        _sync_pause_ui(ctx, paused=paused, source=source)
        return True

    action = "pause" if paused else "resume"

    try:
        if not _call_runtime_method(binding, action=action):
            logger.warning("暂停控制调用失败: owner=%s, action=%s", binding["owner"], action)
            return False

        observed_state = _get_binding_pause_state(binding)
        if observed_state != desired_state:
            logger.warning(
                "暂停控制未达到目标状态: owner=%s, action=%s, expected=%s, actual=%s",
                binding["owner"],
                action,
                desired_state,
                observed_state,
            )
            return False

        _sync_pause_ui(ctx, paused=paused, source=source)
        logger.info("暂停控制已执行: owner=%s, action=%s", binding["owner"], action)
        return True
    except Exception as exc:
        if error_context:
            logger.error("%s失败: %s", error_context, exc)
        else:
            logger.error("暂停控制失败: owner=%s, action=%s, error=%s", binding["owner"], action, exc)
        return False


def toggle_main_window_pause(ctx, source: str = "manual") -> bool:
    state = get_main_window_pause_state(ctx)
    if state == PAUSE_STATE_PAUSED:
        return set_main_window_pause_state(
            ctx,
            paused=False,
            error_context="恢复工作流",
            source=source,
        )

    if state == PAUSE_STATE_RUNNING:
        return set_main_window_pause_state(
            ctx,
            paused=True,
            error_context="暂停工作流",
            source=source,
        )

    logger.warning("当前没有处于运行或暂停状态的工作流")
    return False


def pause_main_window_workflow(ctx, source: str = "manual") -> bool:
    return set_main_window_pause_state(
        ctx,
        paused=True,
        error_context="暂停工作流",
        source=source,
    )


def resume_main_window_workflow(ctx, source: str = "manual") -> bool:
    return set_main_window_pause_state(
        ctx,
        paused=False,
        error_context="恢复工作流",
        source=source,
    )
