from ..parameter_panel_support import *

from .parameter_panel_selector_picker_package_refresh_apply_mixin import (
    ParameterPanelSelectorPickerPackageRefreshApplyMixin,
)
from .parameter_panel_selector_picker_package_refresh_runtime_mixin import (
    ParameterPanelSelectorPickerPackageRefreshRuntimeMixin,
)
from .parameter_panel_selector_picker_package_refresh_state_mixin import (
    ParameterPanelSelectorPickerPackageRefreshStateMixin,
)


class ParameterPanelSelectorPickerPackageRefreshMixin(
    ParameterPanelSelectorPickerPackageRefreshRuntimeMixin,
    ParameterPanelSelectorPickerPackageRefreshApplyMixin,
    ParameterPanelSelectorPickerPackageRefreshStateMixin,
):

    def _refresh_package_list(self, combo_box: QComboBox):
        logger.info("开始刷新已安装应用包名列表...")
        refresh_button = self._find_package_refresh_button(combo_box)
        self._set_package_refresh_button_state(refresh_button, False, "刷新中")
        current_text = combo_box.currentText().strip()
        thread = self._create_package_fetch_thread()

        def on_packages_fetched(packages):
            try:
                self._set_package_refresh_button_state(refresh_button, True, "刷新")
                self._apply_package_fetch_result(combo_box, current_text, packages)
            except Exception as e:
                logger.error(f"处理应用包名列表失败: {e}", exc_info=True)
                self._show_package_refresh_error(e)
            finally:
                self._forget_package_fetch_thread(thread)
                try:
                    if thread:
                        QTimer.singleShot(0, thread.deleteLater)
                except Exception:
                    pass

        thread.finished.connect(on_packages_fetched)
        thread.start()
        self._remember_package_fetch_thread(thread)
