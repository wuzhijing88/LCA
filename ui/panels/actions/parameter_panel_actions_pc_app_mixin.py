from ..parameter_panel_support import *


class ParameterPanelActionsPcAppMixin:

        def _handle_pc_app_manager_click(self):

            """处理电脑应用管理按钮点击"""

            try:

                from ui.pc_app_manager_dialog import PCAppManagerDialog  # type: ignore

                dialog = PCAppManagerDialog(self)



                # 连接应用更新信号

                def on_apps_updated():

                    # 刷新电脑应用选择器

                    if 'selected_pc_app' in self.widgets:

                        self._refresh_pc_app_list(self.widgets['selected_pc_app'])



                dialog.apps_updated.connect(on_apps_updated)

                dialog.exec()

                logger.info("电脑应用管理对话框已关闭")

            except Exception as e:

                logger.error(f"打开电脑应用管理对话框失败: {e}", exc_info=True)





        def _refresh_pc_app_list(self, combo_box):

            """刷新电脑应用列表"""

            try:

                # 保存当前选中的值

                current_text = combo_box.currentText()



                # 清空并重新加载

                combo_box.clear()



                from tasks import pc_app_manager

                apps = pc_app_manager.refresh_apps_list()

                for app in apps:

                    combo_box.addItem(app)



                # 恢复选择 - 使用setCurrentText

                if current_text:

                    combo_box.setCurrentText(current_text)



                logger.info(f"刷新电脑应用列表成功，共 {len(apps)} 个应用")

            except Exception as e:

                logger.error(f"刷新电脑应用列表失败: {e}")
