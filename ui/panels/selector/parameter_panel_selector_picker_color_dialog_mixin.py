from ..parameter_panel_support import *


class ParameterPanelSelectorPickerColorDialogMixin:

            def _select_color(self, line_edit: QLineEdit):



                """汉化的Qt颜色选择对话框"""



                current_color = QColor(line_edit.text())







                # 创建颜色对话框



                dialog = QColorDialog(self)



                dialog.setWindowTitle("选择颜色")



                dialog.setCurrentColor(current_color)



                dialog.setOption(QColorDialog.DontUseNativeDialog, True)







                # 手动汉化按钮文本



                def translate_color_dialog_buttons():



                    for button in dialog.findChildren(QPushButton):



                        button_text = button.text().lower()



                        if 'ok' in button_text or button_text == '&ok':



                            button.setText("确定(&O)")



                        elif 'cancel' in button_text or button_text == '&cancel':



                            button.setText("取消(&C)")



                        elif 'pick screen color' in button_text or 'screen' in button_text:



                            button.setText("屏幕取色")



                        elif 'add to custom colors' in button_text or 'custom' in button_text:



                            button.setText("添加到自定义颜色")







                from PySide6.QtCore import QTimer



                QTimer.singleShot(50, translate_color_dialog_buttons)







                if dialog.exec() == QDialog.Accepted:



                    color = dialog.selectedColor()



                    if color.isValid():



                        line_edit.setText(color.name())



                        # 同步更新current_parameters



                        param_name = self._update_current_parameter_from_widget(line_edit, color.name())



                        if param_name and self.current_card_id is not None:



                            self.parameters_changed.emit(self.current_card_id, {param_name: color.name()})
