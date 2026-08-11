from ..parameter_panel_support import *
from .parameter_panel_selector_picker_package_select_dialog_mixin import (
    ParameterPanelSelectorPickerPackageSelectDialogMixin,
)


class ParameterPanelSelectorPickerPackageSelectMixin(
    ParameterPanelSelectorPickerPackageSelectDialogMixin,
):

    def _select_package(self, line_edit: QLineEdit):
        logger.info("开始获取已安装应用包名列表...")
        try:
            packages = self._fetch_installed_packages_list()
            if not packages:
                self._show_package_list_unavailable_warning()
                return

            dialog, list_widget = self._create_package_select_dialog(packages, line_edit)
            if dialog.exec() != QDialog.Accepted:
                return

            current_item = list_widget.currentItem()
            if not current_item:
                logger.warning("未选择任何包名")
                return

            package_name = current_item.text()
            self._apply_selected_package_to_line_edit(line_edit, package_name)
            logger.info(f"用户选择了包名: {package_name}")
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox

            logger.error(f"获取应用包名列表失败: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                "错误",
                f"获取应用列表时发生错误：\n\n{str(e)}\n\n请查看日志获取详细信息。",
            )
