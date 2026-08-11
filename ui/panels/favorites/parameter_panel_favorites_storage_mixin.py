from .parameter_panel_favorites_storage_io_mixin import (
    ParameterPanelFavoritesStorageIOMixin,
)
from .parameter_panel_favorites_storage_update_mixin import (
    ParameterPanelFavoritesStorageUpdateMixin,
)


class ParameterPanelFavoritesStorageMixin(
    ParameterPanelFavoritesStorageIOMixin,
    ParameterPanelFavoritesStorageUpdateMixin,
):
    pass
