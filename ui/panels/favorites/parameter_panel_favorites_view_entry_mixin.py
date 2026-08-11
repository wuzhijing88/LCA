from ..parameter_panel_support import *
from utils.window_activation_utils import show_and_raise_widget


class ParameterPanelFavoritesViewEntryMixin:

            def show_favorites(self):



                """显示工作流收藏列表"""



                self._favorites_mode = True



                self.current_card_id = None



                self.current_task_type = None







                self.title_input.setReadOnly(True)



                self._set_footer_buttons_visible(True)







                self._clear_content()



                self._load_favorites_data()



                self._create_favorites_ui()



                self._update_favorites_title()







                self._position_panel()



                self.manually_closed = False



                show_and_raise_widget(self, log_prefix='收藏面板展示')
                QTimer.singleShot(0, self._position_panel)







                if hasattr(self, 'reset_button') and self.reset_button is not None:

                    self.reset_button.setVisible(False)





            def _set_favorites_view(self, view_name: str):



                if view_name == 'market':

                    return







                self._favorites_active_view = 'favorites'



                self._update_favorites_title()





            def _update_favorites_title(self):



                self.title_input.setText("工作区工作流")
