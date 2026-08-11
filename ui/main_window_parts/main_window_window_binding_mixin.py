from .main_window_window_binding_activation_mixin import MainWindowWindowBindingActivationMixin
from .main_window_window_binding_lookup_mixin import MainWindowWindowBindingLookupMixin
from .main_window_window_binding_resize_mixin import MainWindowWindowBindingResizeMixin
from .main_window_window_binding_state_mixin import MainWindowWindowBindingStateMixin


class MainWindowWindowBindingMixin(
    MainWindowWindowBindingResizeMixin,
    MainWindowWindowBindingLookupMixin,
    MainWindowWindowBindingStateMixin,
    MainWindowWindowBindingActivationMixin,
):
    pass
