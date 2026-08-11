from ..parameter_panel_support import *


class ParameterPanelSelectorCoordinateMultiMixin:

        def _select_multi_coordinates(self, param_name: str):

            """启动多点坐标选择工具"""

            logger.info(f"多点坐标选择按钮被点击，参数名: {param_name}")



            try:

                from ui.selectors.coordinate_selector import MultiPointCoordinateSelectorWidget



                # 创建多点坐标选择器

                self.multi_coordinate_selector = MultiPointCoordinateSelectorWidget(self)



                # 获取目标窗口句柄

                target_window_hwnd = self._get_target_window_hwnd()

                if target_window_hwnd:

                    self.multi_coordinate_selector.target_window_hwnd = target_window_hwnd

                    logger.info(f"设置多点坐标选择器窗口句柄: {target_window_hwnd}")

                else:

                    logger.error("未找到目标窗口句柄")

                    from PySide6.QtWidgets import QMessageBox

                    QMessageBox.warning(self, "错误", "未找到目标窗口，请先绑定窗口")

                    return



                # 连接信号

                self.multi_coordinate_selector.coordinates_selected.connect(

                    lambda coords, timestamps: self._on_multi_coordinates_selected(param_name, coords, timestamps)

                )



                # 开始选择

                logger.info("开始启动多点坐标选择器...")

                self.multi_coordinate_selector.start_selection()



            except Exception as e:

                logger.error(f"启动多点坐标选择工具失败: {e}")

                from PySide6.QtWidgets import QMessageBox

                QMessageBox.warning(self, "错误", f"启动多点坐标选择工具失败: {str(e)}")





        def _on_multi_coordinates_selected(self, param_name: str, coordinates: list, timestamps: list):

            """处理多点坐标选择完成"""

            try:

                logger.info(f"多点坐标选择完成: {param_name}, {len(coordinates)} 个点")



                # 将坐标列表和时间戳转换为文本格式

                # 格式: x,y,timestamp

                if timestamps and len(timestamps) == len(coordinates):

                    coord_text = "\n".join([f"{x},{y},{t:.3f}" for (x, y), t in zip(coordinates, timestamps)])

                    logger.info(f"已保存带时间戳的路径点: {len(coordinates)}个点, 总时长={timestamps[-1]:.3f}s")

                else:

                    # 如果没有时间戳，使用原格式

                    coord_text = "\n".join([f"{x},{y}" for x, y in coordinates])

                    logger.warning("未获取时间戳，使用默认格式保存坐标")



                # 更新对应的文本编辑框

                if param_name in self.widgets:

                    widget = self.widgets[param_name]

                    if hasattr(widget, 'setPlainText'):

                        widget.setPlainText(coord_text)

                        logger.info(f"已更新路径点坐标")



                # 同步更新current_parameters

                self.current_parameters[param_name] = coord_text



                # 自动应用参数（不关闭面板，以便用户继续编辑）

                self._apply_parameters(auto_close=False)



            except Exception as e:

                logger.error(f"处理多点坐标选择结果失败: {e}")
