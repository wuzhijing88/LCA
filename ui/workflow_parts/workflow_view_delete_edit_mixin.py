from .workflow_view_delete_card_mixin import WorkflowViewDeleteCardMixin
from .workflow_view_edit_interaction_mixin import WorkflowViewEditInteractionMixin


class WorkflowViewDeleteEditMixin(
    WorkflowViewDeleteCardMixin,
    WorkflowViewEditInteractionMixin,
):
    pass
