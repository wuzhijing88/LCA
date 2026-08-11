from ..parameter_panel_support import *


class ParameterPanelActionsContextMixin:

        def _show_random_target_context_menu(self, target_card_id: int, widget: QWidget, pos):

            """显示随机跳转目标的右键菜单"""

            menu = self._create_panel_context_menu()

            set_weight_action = menu.addAction("设置权重")

            delete_action = menu.addAction("删除连线")

            action = menu.exec_(widget.mapToGlobal(pos))

            if action == set_weight_action:

                self._edit_random_branch_weight(target_card_id)

            elif action == delete_action:

                if self.current_card_id is not None:

                    self.request_delete_random_connection.emit(self.current_card_id, target_card_id)





        def _edit_random_branch_weight(self, target_card_id: int):

            if self.current_card_id is None:

                return

            current_weight = get_branch_weight(

                self.current_parameters.get('random_weights'),

                target_card_id,

            )

            weight, ok = QInputDialog.getInt(

                self,

                "设置权重",

                f"目标卡片 {target_card_id} 的权重：",

                current_weight,

                1,

                999999,

                1,

            )

            if not ok:

                return

            updated_weights = set_branch_weight(

                self.current_parameters.get('random_weights'),

                target_card_id,

                weight,

            )

            self.current_parameters['random_weights'] = updated_weights

            self.parameters_changed.emit(self.current_card_id, {'random_weights': updated_weights})

            self._refresh_conditional_widgets()





        def _create_panel_context_menu(self) -> QMenu:

            """创建参数面板统一的右键菜单样式（与主窗口右键菜单保持一致）"""

            return apply_unified_menu_style(QMenu(self), frameless=True)
