from ..parameter_panel_support import *


class ParameterPanelSelectorCoordinateBasicRuntimeMixin:

    def _select_coordinate(self, param_name: str):
        logger.info(f"坐标选择按钮被点击，参数名: {param_name}")
        try:
            from PySide6.QtWidgets import QMessageBox
            from ui.selectors.coordinate_selector import CoordinateSelectorWidget

            self.coordinate_selector = CoordinateSelectorWidget(self)
            target_window_hwnd = self._get_target_window_hwnd()
            if not target_window_hwnd:
                logger.error("未找到目标窗口句柄")
                QMessageBox.warning(self, "错误", "未找到目标窗口，请先绑定窗口")
                return

            self.coordinate_selector.target_window_hwnd = target_window_hwnd
            logger.info(f"设置坐标选择器窗口句柄: {target_window_hwnd}")
            self.coordinate_selector.coordinate_selected.connect(
                lambda x, y, selected_param=param_name: self._on_coordinate_selected(selected_param, x, y)
            )
            self.coordinate_selector.start_selection()
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox

            logger.error(f"启动坐标选择工具失败: {e}")
            QMessageBox.warning(self, "错误", f"启动坐标选择工具失败: {str(e)}")
