from ..parameter_panel_support import *


class ParameterPanelSelectorBindingStartMixin:
    def _select_ocr_region(self, param_name: str):
        """启动OCR区域选择工具"""
        logger.info(f"OCR区域选择按钮被点击，参数名: {param_name}")

        try:
            from ui.selectors.ocr_region_selector import OCRRegionSelectorWidget

            # 获取绑定的窗口句柄
            target_window_hwnd = self._get_bound_window_hwnd()

            if not target_window_hwnd:
                from PySide6.QtWidgets import QMessageBox
                logger.warning("未找到绑定的窗口")
                QMessageBox.warning(self, "警告", "未找到绑定的窗口，请先绑定目标窗口")
                return

            # 创建区域选择器，直接传递窗口句柄
            self.region_selector = OCRRegionSelectorWidget(self)

            # 设置目标窗口句柄
            if hasattr(self.region_selector, 'set_target_window_hwnd'):
                self.region_selector.set_target_window_hwnd(target_window_hwnd)
            elif hasattr(self.region_selector, 'set_target_window'):
                # 兼容旧版本，获取窗口标题
                try:
                    import win32gui
                    window_title = win32gui.GetWindowText(target_window_hwnd)
                    self.region_selector.set_target_window(window_title)
                except Exception as e:
                    logger.warning(f"获取窗口标题失败: {e}")
                    # 直接使用句柄作为标题
                    self.region_selector.set_target_window(f"窗口{target_window_hwnd}")

            # 连接信号
            self.region_selector.region_selected.connect(
                lambda x, y, w, h: self._on_ocr_region_selected(param_name, x, y, w, h)
            )

            # 开始选择
            self.region_selector.start_selection()

        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            logger.error(f"启动区域选择工具失败: {str(e)}")
            import traceback
            logger.error(f"详细错误信息:\n{traceback.format_exc()}")
            QMessageBox.warning(self, "错误", f"启动区域选择工具失败: {str(e)}")
