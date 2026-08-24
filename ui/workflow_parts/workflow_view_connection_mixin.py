from .workflow_view_connection_core_mixin import WorkflowViewConnectionCoreMixin
from .workflow_view_connection_drag_mixin import WorkflowViewConnectionDragMixin
from .workflow_view_connection_sequence_mixin import WorkflowViewConnectionSequenceMixin
from .workflow_view_connection_validation_mixin import WorkflowViewConnectionValidationMixin


class WorkflowViewConnectionMixin(
    WorkflowViewConnectionCoreMixin,
    WorkflowViewConnectionDragMixin,
    WorkflowViewConnectionSequenceMixin,
    WorkflowViewConnectionValidationMixin,
):
    pass
