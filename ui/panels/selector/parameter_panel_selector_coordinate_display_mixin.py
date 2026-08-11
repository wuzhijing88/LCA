from ..parameter_panel_support import *


class ParameterPanelSelectorCoordinateDisplayMixin:

        def _select_coordinate_with_display(self, param_name: str):

            """启动坐标选择工具（带显示更新）"""

            logger.info(f"坐标选择按钮被点击（带显示），参数名: {param_name}")



            try:

                from ui.selectors.coordinate_selector import CoordinateSelectorWidget



                # 创建坐标选择器

                self.coordinate_selector = CoordinateSelectorWidget(self)



                # 获取目标窗口句柄

                target_window_hwnd = self._get_target_window_hwnd()

                if target_window_hwnd:

                    self.coordinate_selector.target_window_hwnd = target_window_hwnd

                    logger.info(f"设置坐标选择器窗口句柄: {target_window_hwnd}")

                else:

                    logger.error("未找到目标窗口句柄")

                    from PySide6.QtWidgets import QMessageBox

                    QMessageBox.warning(self, "错误", "未找到目标窗口，请先绑定窗口")

                    return



                # 连接信号

                self.coordinate_selector.coordinate_selected.connect(

                    lambda x, y: self._on_coordinate_selected_with_display(param_name, x, y)

                )



                # 开始选择

                self.coordinate_selector.start_selection()



            except Exception as e:

                logger.error(f"启动坐标选择工具失败: {e}")

                from PySide6.QtWidgets import QMessageBox

                QMessageBox.warning(self, "错误", f"启动坐标选择工具失败: {str(e)}")





        def _on_coordinate_selected_with_display(self, param_name: str, x: int, y: int):

            """处理坐标选择完成（更新显示控件）"""

            try:

                logger.info(f"坐标选择完成（带显示）: param_name={param_name}, x={x}, y={y}")



                # 更新显示控件（使用参数名作为key）

                coord_display_key = f'_coord_display_{param_name}'

                if hasattr(self, coord_display_key):

                    coord_display = getattr(self, coord_display_key)

                    if coord_display:

                        coord_display.setText(f"{x},{y}")



                # 根据关联参数动态回填坐标参数

                coord_params_key = f'_coord_params_{param_name}'

                params_tuple = getattr(self, coord_params_key, None)

                x_param = 'coordinate_x'

                y_param = 'coordinate_y'

                related_params = []

                if isinstance(params_tuple, tuple) and len(params_tuple) >= 2:

                    x_param = params_tuple[0] or x_param

                    y_param = params_tuple[1] or y_param

                    if len(params_tuple) >= 3 and isinstance(params_tuple[2], (list, tuple)):

                        related_params = list(params_tuple[2])



                updates = {

                    x_param: x,

                    y_param: y,

                }



                # 若配置了第三个关联参数，则同步写入标准化坐标字符串，便于变量系统覆盖/回显

                if len(related_params) >= 3 and related_params[2]:

                    updates[str(related_params[2])] = f"{x},{y}"



                for key, value in updates.items():

                    self.current_parameters[key] = value



                logger.info(f"更新坐标参数: {updates}")



                # 发出参数更改信号

                if self.current_card_id is not None:

                    self.parameters_changed.emit(self.current_card_id, updates)



            except Exception as e:

                logger.error(f"处理坐标选择结果失败: {e}")
