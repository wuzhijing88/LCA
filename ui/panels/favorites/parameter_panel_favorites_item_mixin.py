from .parameter_panel_favorites_item_selection_mixin import (
    ParameterPanelFavoritesItemSelectionMixin,
)
from .parameter_panel_favorites_item_storage_mixin import (
    ParameterPanelFavoritesItemStorageMixin,
)


class ParameterPanelFavoritesItemMixin(
    ParameterPanelFavoritesItemSelectionMixin,
    ParameterPanelFavoritesItemStorageMixin,
):
    pass
