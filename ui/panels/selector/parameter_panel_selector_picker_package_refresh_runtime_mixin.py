from ..parameter_panel_support import *
from PySide6.QtCore import QThread, Signal


class _PackageListFetchThread(QThread):
    finished = Signal(object)

    def __init__(self, fetch_callback, parent=None):
        super().__init__(parent)
        self._fetch_callback = fetch_callback

    def run(self):
        packages = self._fetch_callback()
        self.finished.emit(packages)


class ParameterPanelSelectorPickerPackageRefreshRuntimeMixin:

    def _fetch_installed_packages_list(self):
        try:
            from tasks import app_manager_task

            return app_manager_task.get_installed_packages_list()
        except Exception as e:
            logger.error(f"获取应用包名列表失败: {e}", exc_info=True)
            return None

    def _create_package_fetch_thread(self):
        return _PackageListFetchThread(self._fetch_installed_packages_list)
