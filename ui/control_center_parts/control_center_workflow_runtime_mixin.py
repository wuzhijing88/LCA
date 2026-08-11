from ..control_center_parts.control_center_workflow_ocr_mixin import ControlCenterWorkflowOcrMixin
from ..control_center_parts.control_center_workflow_start_mixin import ControlCenterWorkflowStartMixin
from ..control_center_parts.control_center_workflow_stop_mixin import ControlCenterWorkflowStopMixin


class ControlCenterWorkflowRuntimeMixin(
    ControlCenterWorkflowStartMixin,
    ControlCenterWorkflowOcrMixin,
    ControlCenterWorkflowStopMixin,
):
    pass
