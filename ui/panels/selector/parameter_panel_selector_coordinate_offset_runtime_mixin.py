from ..parameter_panel_support import *


class ParameterPanelSelectorCoordinateOffsetRuntimeMixin:

    def _ensure_offset_selector(self):
        from ui.selectors.coordinate_selector import OffsetSelectorWidget

        if self.offset_selector is None:
            self.offset_selector = OffsetSelectorWidget(self)
            self.offset_selector.offset_selected.connect(self._handle_offset_selected)
        return self.offset_selector

    def _select_offset(self, param_name: str):
        logger.info(f"偏移选择按钮被点击，参数名: {param_name}")
        try:
            offset_selector = self._ensure_offset_selector()
            self._offset_param_name = param_name

            target_window_hwnd = self._get_target_window_hwnd()
            if not target_window_hwnd:
                logger.error("未找到目标窗口句柄")
                from PySide6.QtWidgets import QMessageBox

                QMessageBox.warning(
                    self,
                    "错误",
                    "未找到目标窗口，请先绑定窗口",
                )
                return

            offset_selector.target_window_hwnd = target_window_hwnd
            logger.info(
                f"设置偏移选择器窗口句柄: {target_window_hwnd}"
            )
            offset_selector.base_point = None
            offset_selector.base_rect = None

            base_x, base_y, base_rect = self._resolve_offset_base_for_selection(param_name)
            if base_x is not None and base_y is not None:
                offset_selector.set_base_point(int(base_x), int(base_y))
            if base_rect is not None:
                try:
                    offset_selector.set_base_rect(*base_rect)
                except Exception:
                    pass

            offset_selector.start_selection()
        except Exception as exc:
            logger.error(f"启动偏移选择工具失败: {exc}")
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(
                self,
                "错误",
                f"启动偏移选择工具失败: {str(exc)}",
            )
