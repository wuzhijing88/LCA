from .parameter_panel_favorites_view_page_footer_mixin import (
    ParameterPanelFavoritesViewPageFooterMixin,
)
from .parameter_panel_favorites_view_page_header_mixin import (
    ParameterPanelFavoritesViewPageHeaderMixin,
)
from .parameter_panel_favorites_view_page_list_mixin import (
    ParameterPanelFavoritesViewPageListMixin,
)
from .parameter_panel_favorites_view_page_toolbar_mixin import (
    ParameterPanelFavoritesViewPageToolbarMixin,
)


class ParameterPanelFavoritesViewPageMixin(
    ParameterPanelFavoritesViewPageToolbarMixin,
    ParameterPanelFavoritesViewPageHeaderMixin,
    ParameterPanelFavoritesViewPageListMixin,
    ParameterPanelFavoritesViewPageFooterMixin,
):

    def _create_favorites_workflow_page(self, parent_layout):
        self._create_favorites_toolbar(parent_layout)
        self._create_favorites_header(parent_layout)
        self._create_favorites_list_section(parent_layout)
        self._create_favorites_start_button(parent_layout)
