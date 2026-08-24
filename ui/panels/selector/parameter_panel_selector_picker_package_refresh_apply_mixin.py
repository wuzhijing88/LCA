from ..parameter_panel_support import *


class ParameterPanelSelectorPickerPackageRefreshApplyMixin:

    def _show_package_list_unavailable_warning(self):
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.warning(
            self,
            "无法获取应用列表",
            "未能获取已安装应用列表?\n\n"
            "可能的原因：\n"
            "1. ADB未正确连接\n"
            "2. 没有可用的模拟器设备\n"
            "3. 设备上没有安装第三方应用\n\n"
            "请检查ADB连接状态和设备。",
        )

    def _restore_package_combo_selection(self, combo_box: QComboBox, current_text: str, packages):
        combo_box.clear()
        combo_box.addItems(packages)
        if current_text and current_text in packages:
            index = combo_box.findText(current_text)
            if index >= 0:
                combo_box.setCurrentIndex(index)
            return
        if current_text:
            combo_box.addItem(current_text)
            combo_box.setCurrentText(current_text)

    def _apply_package_fetch_result(self, combo_box: QComboBox, current_text: str, packages):
        from shiboken6 import isValid

        if not isValid(combo_box) or not isValid(self):
            logger.warning("刷新完成时控件已被销毁，跳过更新")
            return
        if packages is None or not packages:
            self._show_package_list_unavailable_warning()
            return

        self._restore_package_combo_selection(combo_box, current_text, packages)
        logger.info(f"成功刷新包名列表，共 {len(packages)} 个应用")

    def _show_package_refresh_error(self, error):
        try:
            from shiboken6 import isValid

            if isValid(self):
                from PySide6.QtWidgets import QMessageBox

                QMessageBox.critical(
                    self,
                    "错误",
                    f"刷新应用列表时发生错误：\n\n{str(error)}\n\n请查看日志获取详细信息。",
                )
        except Exception:
            pass
