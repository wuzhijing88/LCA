from ..parameter_panel_support import *


class ParameterPanelSelectorPickerPackageRefreshStateMixin:

    def _find_package_refresh_button(self, combo_box: QComboBox):
        parent = combo_box.parent()
        if parent is None:
            return None
        for child in parent.children():
            if isinstance(child, QPushButton) and "刷新" in child.text():
                return child
        return None

    def _set_package_refresh_button_state(self, refresh_button, enabled: bool, text: str):
        try:
            from shiboken6 import isValid

            if refresh_button and isValid(refresh_button):
                refresh_button.setEnabled(enabled)
                refresh_button.setText(text)
        except Exception:
            pass

    def _remember_package_fetch_thread(self, thread):
        if not hasattr(self, "_fetch_threads"):
            self._fetch_threads = []
        self._fetch_threads.append(thread)

    def _forget_package_fetch_thread(self, thread):
        try:
            if thread and hasattr(self, "_fetch_threads") and thread in self._fetch_threads:
                self._fetch_threads.remove(thread)
        except Exception:
            pass
