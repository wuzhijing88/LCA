from ..parameter_panel_support import *


class ParameterPanelMediaMultiImageThumbnailUpdateMixin:
            def _update_thumbnail_grid(self, param_name: str, paths_text: str):



                """更新缩略图网格显示"""



                try:



                    container_key = f"{param_name}_thumbnail_container"



                    if container_key not in self.widgets:



                        return







                    container = self.widgets[container_key]



                    layout = container.layout()







                    # 清除现有的缩略图



                    while layout.count():



                        item = layout.takeAt(0)



                        widget = item.widget()



                        if widget:



                            widget.deleteLater()







                    # 解析路径



                    file_paths = self._parse_image_paths(paths_text)







                    if not file_paths:



                        # 没有图片时显示提示



                        placeholder = QLabel('点击"选择多个图片..."添加图片')



                        placeholder



                        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)



                        layout.addWidget(placeholder)



                        return







                    # 使用网格布局来放置缩略图，支持多行



                    grid_widget = QWidget()



                    grid_layout = QGridLayout(grid_widget)



                    grid_layout.setContentsMargins(0, 0, 0, 0)



                    grid_layout.setSpacing(10)







                    # 每行显示的缩略图数量



                    columns = 3



                    for i, path in enumerate(file_paths):



                        row = i // columns



                        col = i % columns



                        thumbnail = ThumbnailWidget(path, size=60)



                        thumbnail.clicked.connect(self._show_image_viewer)



                        thumbnail.delete_requested.connect(lambda p=path, name=param_name: self._delete_single_image(name, p))



                        grid_layout.addWidget(thumbnail, row, col)







                    layout.addWidget(grid_widget)







                except Exception as e:



                    logger.error(f"更新缩略图网格失败: {e}", exc_info=True)
