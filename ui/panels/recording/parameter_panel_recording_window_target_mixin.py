from utils.window_activation_utils import (
    activate_window,
    load_enabled_bound_window_hwnd_from_config,
    resolve_window_activation_hwnd,
    resolve_window_client_offset,
    resolve_window_client_rect,
)


class ParameterPanelRecordingWindowTargetMixin:
    def _load_enabled_bound_window_hwnd_from_config(self):
        return load_enabled_bound_window_hwnd_from_config()

    def _activate_bound_window(self, hwnd, log_prefix: str = ''):
        return activate_window(hwnd, log_prefix=log_prefix)

    def _resolve_bound_window_activation_hwnd(self, hwnd, log_prefix: str = ''):
        return resolve_window_activation_hwnd(hwnd, log_prefix=log_prefix)

    def _resolve_bound_window_client_rect(self, hwnd, log_prefix: str = ''):
        return resolve_window_client_rect(hwnd, log_prefix=log_prefix)

    def _resolve_bound_window_client_offset(self, hwnd, log_prefix: str = ''):
        return resolve_window_client_offset(hwnd, log_prefix=log_prefix)
