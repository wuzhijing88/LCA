from ..parameter_panel_support import *


class ParameterPanelWindowVisualMixin:

        def paintEvent(self, event):

            """绘制圆角背景（10px圆角，与主窗口保持一致）"""

            painter = QPainter(self)

            painter.setRenderHint(QPainter.RenderHint.Antialiasing)



            # 创建圆角矩形路径

            path = QPainterPath()

            rect = self.rect()

            shadow_margin = max(0, int(getattr(self, "_shadow_margin", 0)))

            radius = 10  # 圆角半径，与主窗口保持一致

            content_rect = rect.adjusted(shadow_margin, shadow_margin, -shadow_margin, -shadow_margin)

            path.addRoundedRect(content_rect, radius, radius)



            # 从主题管理器获取背景颜色

            try:

                from themes import get_theme_manager

                theme_manager = get_theme_manager()

                bg_color = theme_manager.get_qcolor('background')

                bg_color.setAlpha(250)  # 略透明

                border_color = theme_manager.get_qcolor('border')

            except:

                # 回退到深色主题颜色

                bg_color = QColor(30, 30, 30, 250)

                border_color = QColor(62, 62, 62)



            # 绘制阴影（内置阴影边框）

            if shadow_margin > 0 and not getattr(self, "_use_native_shadow", False):

                for i in range(shadow_margin, 0, -1):

                    alpha = int(20 * (i / shadow_margin))

                    shadow_rect = content_rect.adjusted(-i, -i, i, i)

                    shadow_path = QPainterPath()

                    shadow_path.addRoundedRect(shadow_rect, radius + i, radius + i)

                    painter.fillPath(shadow_path, QBrush(QColor(0, 0, 0, alpha)))



            # 绘制背景

            painter.fillPath(path, QBrush(bg_color))



            # 绘制边框（2px粗边框，模拟系统边框效果）

            painter.setPen(QPen(border_color, 2))

            painter.drawPath(path)





        def _try_enable_native_shadow(self) -> None:

            """尝试启用系统级阴影（Windows 11 DWM 圆角）"""

            if os.name != "nt":

                return

            try:

                import ctypes

                from ctypes import wintypes



                hwnd = int(self.winId())

                DWMWA_WINDOW_CORNER_PREFERENCE = 33

                DWMWCP_ROUND = 2



                preference = wintypes.DWORD(DWMWCP_ROUND)

                result = ctypes.windll.dwmapi.DwmSetWindowAttribute(

                    hwnd,

                    DWMWA_WINDOW_CORNER_PREFERENCE,

                    ctypes.byref(preference),

                    ctypes.sizeof(preference),

                )

                if result == 0:

                    self._use_native_shadow = True

                    self._shadow_margin = 0

            except Exception:

                self._use_native_shadow = False
