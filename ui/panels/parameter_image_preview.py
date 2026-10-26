"""声明式图片预览只在有效参数进入视口后持有图像与读取任务。"""
from task_workflow.expr import contains_interpolation
from PySide6.QtWidgets import QLabel
from ui.panels.media.image_preview import ImagePreviewLabel


class ParameterImagePreview(ImagePreviewLabel):
    def __init__(self, parent):
        super().__init__(parent)
        self._viewport_active = False
        self._declared_path = ""
        self.setFixedHeight(96)
        self.setMinimumWidth(0)
        self.setProperty("imagePreview", True)

    def set_image_path(self, path, images_dir):
        self._declared_path = path
        unresolved = contains_interpolation(path)
        super().set_image_path("" if unresolved else path, images_dir)
        if unresolved:
            self.setText("图片路径待运行时解析")
        elif not self._viewport_active:
            self.cancel_loading()
            self.setText("移入视口后加载图片" if path else "未选择图片")

    def set_viewport_active(self, active):
        if self._viewport_active == active:
            return
        self._viewport_active = active
        if active:
            self.set_image_path(self._declared_path, self._images_dir)
        else:
            self.cancel_loading()
            self.setText("移入视口后加载图片" if self._declared_path else "未选择图片")

    def _start_loading(self):
        if self._viewport_active and self.isVisible() and not self.visibleRegion().isEmpty():
            super()._start_loading()
        elif self._viewport_active:
            self.set_viewport_active(False)

    def showEvent(self, event):
        if self._viewport_active:
            super().showEvent(event)
        else:
            QLabel.showEvent(self, event)

    def release(self):
        self._viewport_active = False
        self.cancel_loading()
        self._declared_path = ""
        self.image_path = ""
        self._images_dir = ""
