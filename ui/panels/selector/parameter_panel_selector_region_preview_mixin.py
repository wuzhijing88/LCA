from ..parameter_panel_support import *


class ParameterPanelSelectorRegionPreviewMixin:

    def _start_yolo_realtime_preview(self):
        try:
            target_hwnd = self._get_bound_window_hwnd()
            if not target_hwnd:
                from PySide6.QtWidgets import QMessageBox

                QMessageBox.warning(self, "提示", "请先绑定目标窗口")
                return

            model_path = self.current_parameters.get('model_path', '')
            if not model_path:
                from PySide6.QtWidgets import QMessageBox

                QMessageBox.warning(self, "提示", "请先选择YOLO模型文件")
                return

            conf_threshold = self.current_parameters.get('confidence_threshold', 0.5)
            target_classes_str = self.current_parameters.get('target_classes', '')
            target_classes = None
            if target_classes_str and target_classes_str != "全部类别":
                target_classes = [target_classes_str.strip()]

            from tasks.yolo_detection import start_realtime_preview

            start_realtime_preview(
                hwnd=target_hwnd,
                model_path=model_path,
                conf_threshold=conf_threshold,
                target_classes=target_classes,
            )
            logger.info(f"YOLO 实时预览已启动: hwnd={target_hwnd}, model={model_path}")
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox

            logger.error(f"启动 YOLO 实时预览失败: {exc}")
            QMessageBox.warning(self, "错误", f"启动实时预览失败: {str(exc)}")
