from ..parameter_panel_support import *
from .parameter_panel_image_viewer_dialog import ParameterPanelImageViewerDialog
from PySide6.QtGui import QPixmap


class ParameterPanelMediaPreviewMixin:
    _PREVIEW_IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff', '.webp')

    def _update_image_preview(self, image_path: str, preview_label: QLabel):
        """Update image preview."""
        try:
            self._reset_preview_label(preview_label)
            if not image_path or not image_path.strip():
                self._set_preview_status(preview_label, "未选择图片")
                return

            resolved_path = self._resolve_preview_image_path(image_path)
            self._set_preview_image_property(preview_label, resolved_path)

            validation_message = self._validate_preview_image_path(resolved_path)
            if validation_message:
                self._set_preview_status(preview_label, validation_message)
                return

            pixmap = self._load_preview_pixmap(resolved_path)
            if pixmap is None or pixmap.isNull():
                self._set_preview_status(preview_label, "无法加载图片")
                return

            self._apply_preview_pixmap(preview_label, pixmap)
            preview_label.setToolTip(self._build_preview_tooltip(image_path, resolved_path, pixmap))
            logger.debug(f"图片预览已更新: {resolved_path} ({pixmap.width()}x{pixmap.height()})")
        except Exception as e:
            logger.error(f"更新图片预览失败: {e}", exc_info=True)
            self._set_preview_status(preview_label, f"预览失败: {e}")

    def _reset_preview_label(self, preview_label: QLabel) -> None:
        preview_label.clear()
        preview_label.setToolTip("")

    def _set_preview_status(self, preview_label: QLabel, message: str) -> None:
        preview_label.setText(message)
        preview_label.setProperty("image_path", "")

    def _resolve_preview_image_path(self, image_path: str) -> str:
        if os.path.exists(image_path):
            return image_path
        try:
            from tasks.task_utils import get_image_path_resolver

            resolver = get_image_path_resolver()
            if self.images_dir and os.path.exists(self.images_dir):
                resolver.add_search_path(self.images_dir, priority=0)
            resolved_path = resolver.resolve(image_path)
            if resolved_path:
                logger.debug(f"图片路径自动解析: {image_path} -> {resolved_path}")
                return resolved_path
        except Exception as e:
            logger.warning(f"路径解析器调用失败: {e}")
        return image_path

    def _set_preview_image_property(self, preview_label: QLabel, resolved_path: str) -> None:
        preview_label.setProperty(
            "image_path",
            resolved_path if resolved_path and os.path.exists(resolved_path) else "",
        )

    def _validate_preview_image_path(self, resolved_path: str) -> Optional[str]:
        if not os.path.exists(resolved_path):
            return "文件不存在"
        if not resolved_path.lower().endswith(self._PREVIEW_IMAGE_EXTENSIONS):
            return "不是图片文件"
        return None

    def _load_preview_pixmap(self, resolved_path: str) -> Optional[QPixmap]:
        pixmap = QPixmap()
        for _ in range(3):
            try:
                with open(resolved_path, 'rb') as image_file:
                    file_bytes = image_file.read()
                if file_bytes and pixmap.loadFromData(file_bytes):
                    return pixmap
            except Exception:
                pass
            time.sleep(0.03)

        fallback_pixmap = QPixmap(resolved_path)
        if fallback_pixmap.isNull():
            return None
        return fallback_pixmap

    def _apply_preview_pixmap(self, preview_label: QLabel, pixmap: QPixmap) -> None:
        scaled_pixmap = pixmap.scaled(
            max(1, preview_label.width() - 6),
            74,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        preview_label.setPixmap(scaled_pixmap)
        preview_label.setScaledContents(False)

    def _build_preview_tooltip(self, image_path: str, resolved_path: str, pixmap: QPixmap) -> str:
        file_size = os.path.getsize(resolved_path) / 1024
        hint_text = "提示: 双击可查看原图（支持放大缩小）"
        if resolved_path != image_path:
            return (
                f"原路径: {image_path}\n"
                f"解析为: {resolved_path}\n"
                f"尺寸: {pixmap.width()} x {pixmap.height()} 像素\n"
                f"大小: {file_size:.1f} KB\n\n"
                f"{hint_text}"
            )
        return (
            f"路径: {resolved_path}\n"
            f"尺寸: {pixmap.width()} x {pixmap.height()} 像素\n"
            f"大小: {file_size:.1f} KB\n\n"
            f"{hint_text}"
        )

    def _show_image_viewer(self, image_path: str):
        """Show image viewer."""
        try:
            viewer = ParameterPanelImageViewerDialog(image_path, self)
            viewer.exec()
        except Exception as e:
            logger.error(f"显示图片查看器失败: {e}", exc_info=True)
            QMessageBox.critical(self, "错误", f"无法打开图片查看器: {e}")
