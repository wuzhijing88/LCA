from .workflow_view_clipboard_copy_paste_mixin import WorkflowViewClipboardCopyPasteMixin
from .workflow_view_clipboard_delete_mixin import WorkflowViewClipboardDeleteMixin
from .workflow_view_undo_apply_mixin import WorkflowViewUndoApplyMixin
from .workflow_view_undo_state_mixin import WorkflowViewUndoStateMixin


class WorkflowViewClipboardUndoMixin(
    WorkflowViewClipboardDeleteMixin,
    WorkflowViewClipboardCopyPasteMixin,
    WorkflowViewUndoStateMixin,
    WorkflowViewUndoApplyMixin,
):
    pass
