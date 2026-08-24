from .parameter_panel_media_file_select_mixin import ParameterPanelMediaFileSelectMixin
from .parameter_panel_media_file_workflow_mixin import ParameterPanelMediaFileWorkflowMixin


class ParameterPanelMediaFileMixin(
    ParameterPanelMediaFileSelectMixin,
    ParameterPanelMediaFileWorkflowMixin,
):
    pass
