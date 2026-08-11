from .global_settings_dialog_window_lookup_mixin import GlobalSettingsDialogWindowLookupMixin
from .global_settings_dialog_window_manage_mixin import GlobalSettingsDialogWindowManageMixin


class GlobalSettingsDialogWindowCrudMixin(
    GlobalSettingsDialogWindowLookupMixin,
    GlobalSettingsDialogWindowManageMixin,
):
    pass
