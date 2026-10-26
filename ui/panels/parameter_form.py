"""原生单列表单的布局收尾与可见图片刷新，不提供独立布局配置。"""
import weakref

from PySide6.QtCore import QObject, QTimer, Slot, Qt
from themes import get_theme_manager


class ParameterForm(QObject):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.rows = {}
        self._reveal_target = None
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_connection = self._layout_timer.timeout.connect(self._relayout)
        owner = weakref.ref(self)

        def changed(_theme):
            form = owner()
            if form is not None and form.panel is not None:
                form._layout_timer.start(0)

        self._theme_changed = changed
        try:
            get_theme_manager().register_theme_change_callback(changed)
        except Exception:
            self.close()
            raise

    @Slot()
    def _relayout(self):
        self.panel.content_layout.invalidate()
        self.panel.content_layout.activate()
        target, self._reveal_target = self._reveal_target, None
        if target is not None:
            row, widget = target
            self.panel.scroll_area.ensureWidgetVisible(row)
            widget.setFocus(Qt.FocusReason.OtherFocusReason)

    def _schedule_layout(self, *_args):
        if self.panel is not None:
            self._layout_timer.start(0)

    def add(self, name, row, presentation):
        self.rows[name] = row
        self.panel.content_layout.addWidget(row)

    def finish(self):
        self.panel.content_layout.addStretch()
        self._schedule_layout()

    def reveal(self, name, widget):
        self._reveal_target = (self.rows[name], widget)
        self._schedule_layout()

    def refresh(self, states, errors):
        for name, row in self.rows.items():
            row.setVisible(states[name].visible)
        self._schedule_layout()

    def close(self):
        if self.panel is None:
            return
        get_theme_manager().unregister_theme_change_callback(self._theme_changed)
        self._theme_changed = None
        self._layout_timer.stop()
        # 按连接句柄断开，避免释放时重新构造编译后的绑定方法。
        try:
            if not QObject.disconnect(self._layout_connection):
                raise RuntimeError("参数表单布局计时器断开失败")
        finally:
            self._layout_connection = None
            self._layout_timer.deleteLater()
            self._reveal_target = None
            self.rows.clear()
            self.panel = None
            self.deleteLater()
