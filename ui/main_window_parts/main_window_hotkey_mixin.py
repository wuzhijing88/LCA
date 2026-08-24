from .main_window_hotkey_core_mixin import MainWindowHotkeyCoreMixin
from .main_window_hotkey_handlers_mixin import MainWindowHotkeyHandlersMixin
from .main_window_hotkey_setup_mixin import MainWindowHotkeySetupMixin


class MainWindowHotkeyMixin(
    MainWindowHotkeyCoreMixin,
    MainWindowHotkeySetupMixin,
    MainWindowHotkeyHandlersMixin,
):
    pass
