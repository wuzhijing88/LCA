from ..parameter_panel_support import *


class ParameterPanelSelectorPickerColorListMixin:

            def _populate_color_list(self, color_list, color_string: str):



                """填充颜色列表，显示颜色块和坐标信息"""



                from PySide6.QtWidgets import QListWidgetItem



                from PySide6.QtGui import QPixmap, QIcon, QPainter, QBrush, QColor



                from PySide6.QtCore import Qt







                color_list.clear()







                if not color_string or not color_string.strip():



                    return







                # 解析颜色字符串：格式为 "R,G,B|偏移X,偏移Y,R,G,B|..."



                parts = color_string.strip().split('|')







                for i, part in enumerate(parts):



                    part = part.strip()



                    if not part:



                        continue







                    try:



                        values = [v.strip() for v in part.split(',')]







                        if i == 0:



                            # 基准点：R,G,B



                            if len(values) >= 3:



                                r, g, b = int(values[0]), int(values[1]), int(values[2])



                                display_text = f"基准点  RGB({r},{g},{b})"



                                color = QColor(r, g, b)



                            else:



                                continue



                        else:



                            # 偏移点：偏移X,偏移Y,R,G,B



                            if len(values) >= 5:



                                offset_x, offset_y = int(values[0]), int(values[1])



                                r, g, b = int(values[2]), int(values[3]), int(values[4])



                                display_text = f"偏移({offset_x:+d},{offset_y:+d})  RGB({r},{g},{b})"



                                color = QColor(r, g, b)



                            else:



                                continue







                        # 创建颜色图标（16x16 的颜色块）



                        pixmap = QPixmap(16, 16)



                        pixmap.fill(Qt.GlobalColor.transparent)



                        painter = QPainter(pixmap)



                        painter.setRenderHint(QPainter.RenderHint.Antialiasing)



                        painter.setBrush(QBrush(color))



                        # 从主题管理器获取边框颜色



                        from themes import get_theme_manager



                        theme_mgr = get_theme_manager()



                        border_color = QColor(theme_mgr.get_color('border'))



                        painter.setPen(border_color)



                        painter.drawRect(0, 0, 15, 15)



                        painter.end()







                        # 添加列表项



                        item = QListWidgetItem(QIcon(pixmap), display_text)



                        color_list.addItem(item)







                    except (ValueError, IndexError) as e:



                        logger.warning(f"解析颜色部分失败: {part}, 错误: {e}")



                        continue
