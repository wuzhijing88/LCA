from .workflow_view_context_menu_mixin import WorkflowViewContextMenuMixin
from .workflow_view_loading_mixin import WorkflowViewLoadingMixin
from .workflow_view_serialization_mixin import WorkflowViewSerializationMixin


class WorkflowViewIoMixin(
    WorkflowViewContextMenuMixin,
    WorkflowViewSerializationMixin,
    WorkflowViewLoadingMixin,
):
    pass
