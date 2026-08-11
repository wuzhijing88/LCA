from .parameter_panel_favorites_action_execute_mixin import (
    ParameterPanelFavoritesActionExecuteMixin,
)
from .parameter_panel_favorites_action_manage_mixin import (
    ParameterPanelFavoritesActionManageMixin,
)


class ParameterPanelFavoritesActionMixin(
    ParameterPanelFavoritesActionManageMixin,
    ParameterPanelFavoritesActionExecuteMixin,
):
    pass
