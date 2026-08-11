from ..main_window_parts.main_window_pause_orchestrator import (
    main_window_pause_workflow,
    main_window_resume_workflow,
    main_window_toggle_pause_workflow,
)
from ..main_window_parts.main_window_start_orchestrator import (
    main_window_safe_start_tasks,
    main_window_start_tasks,
)
from ..main_window_parts.main_window_stop_orchestrator import (
    main_window_safe_stop_tasks,
    main_window_stop_tasks,
)

class MainWindowExecutionFlowLifecycleMixin:

    def safe_start_tasks(self, reset_jump_cancel=True):

        """安全启动任务，带状态检查和防重复调用保护 - 启动所有便签页的工作流

        Args:

            reset_jump_cancel: 是否重置跳转取消标志（True表示用户手动启动，False表示自动跳转启动）

        """

        return main_window_safe_start_tasks(self, reset_jump_cancel=reset_jump_cancel)

    def _resume_workflow(self):

        """恢复暂停的工作流"""

        return main_window_resume_workflow(self)

    def toggle_pause_workflow(self):

        """切换暂停/恢复工作流（快捷键调用）"""

        return main_window_toggle_pause_workflow(self)

    def _pause_workflow(self):

        """暂停工作流（快捷键调用）"""

        return main_window_pause_workflow(self)

    def safe_stop_tasks(self):

        """安全停止任务 - 精简版"""

        return main_window_safe_stop_tasks(self)

    def start_tasks(self):

        """传统启动方法，现在调用安全启动"""

        return main_window_start_tasks(self)

    def stop_tasks(self):

        """传统停止方法，现在调用安全停止"""

        return main_window_stop_tasks(self)
