import logging
import os

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QMessageBox
from app_core.client_identity import attempt_client_registration, get_hardware_id
from app_core.license_store import LICENSE_FILE, load_local_license, save_local_license
from app_core.license_runtime import enforce_online_validation
from app_core.plugin_activation_service import prepare_plugin_mode_activation
from ..dialogs.license_input_dialog import LicenseInputDialog

from ..main_window_parts.main_window_support import normalize_execution_mode_setting
from utils.window_coordinate_common import center_window_on_widget_screen

logger = logging.getLogger(__name__)


class GlobalSettingsDialogVisibilityMixin:

    def _update_foreground_driver_visibility(self):

        """根据执行模式更新前台驱动选择控件的显示。"""

        internal_mode = self.mode_combo.currentData()

        if not internal_mode:

            current_mode = self.mode_combo.currentText()

            internal_mode = self.MODE_INTERNAL_MAP.get(current_mode, "")

        is_foreground_driver_mode = internal_mode == 'foreground_driver'

        if hasattr(self, 'foreground_driver_widget'):

            self.foreground_driver_widget.setVisible(is_foreground_driver_mode)

        if hasattr(self, 'foreground_keyboard_driver_widget'):

            self.foreground_keyboard_driver_widget.setVisible(is_foreground_driver_mode)

        mouse_backend = None

        if hasattr(self, 'foreground_driver_combo'):

            mouse_backend = self.foreground_driver_combo.currentData()

            if not mouse_backend:

                backend_text = self.foreground_driver_combo.currentText()

                mouse_backend = self.FOREGROUND_DRIVER_BACKEND_MAP.get(backend_text, 'interception')

        keyboard_backend = None

        if hasattr(self, 'foreground_keyboard_driver_combo'):

            keyboard_backend = self.foreground_keyboard_driver_combo.currentData()

            if not keyboard_backend:

                keyboard_text = self.foreground_keyboard_driver_combo.currentText()

                keyboard_backend = self.FOREGROUND_DRIVER_BACKEND_MAP.get(keyboard_text, 'interception')

        is_ib_backend = (

            str(mouse_backend or '').strip().lower() == 'ibinputsimulator'

            or str(keyboard_backend or '').strip().lower() == 'ibinputsimulator'

        )

        # 任一输入类型选择 IbInputSimulator 时显示 Ib 驱动类型

        if hasattr(self, 'ib_driver_widget'):

            self.ib_driver_widget.setVisible(is_foreground_driver_mode and is_ib_backend)

        if hasattr(self, 'ib_driver_combo'):

            self.ib_driver_combo.setEnabled(is_foreground_driver_mode and is_ib_backend)

        # 延迟到事件循环后再重排一次，修复切换瞬间高度计算不完整

        try:

            def _refresh_layout_once():

                try:

                    if hasattr(self, 'exec_mode_group') and self.exec_mode_group.layout():

                        self.exec_mode_group.layout().invalidate()

                        self.exec_mode_group.layout().activate()

                        self.exec_mode_group.updateGeometry()

                    if hasattr(self, 'exec_tab') and self.exec_tab.layout():

                        self.exec_tab.layout().invalidate()

                        self.exec_tab.layout().activate()

                        self.exec_tab.updateGeometry()

                        self.exec_tab.update()

                    self.adjustSize()

                except Exception:

                    pass

            def _refresh_layout_deferred():

                try:

                    _refresh_layout_once()

                    if hasattr(self, 'tab_widget') and self.tab_widget:

                        current_index = self.tab_widget.currentIndex()

                        if current_index >= 0:

                            self.tab_widget.setCurrentIndex(current_index)

                except Exception:

                    pass

            QTimer.singleShot(0, _refresh_layout_once)

            QTimer.singleShot(30, _refresh_layout_once)

            QTimer.singleShot(80, _refresh_layout_deferred)

        except Exception:

            pass

    def _update_binding_params_visibility(self):

        """

        更新绑定参数显示（仅UI切换，不验证授权）

        在对话框初始化时调用，根据当前配置显示对应的UI

        """

        plugin_enabled = self.plugin_enabled_check.isChecked()

        # 切换执行模式组可见性（启用插件时隐藏整个组）

        if hasattr(self, 'exec_mode_group'):

            self.exec_mode_group.setVisible(not plugin_enabled)

        # 切换截图方式选择组可见性（启用插件时隐藏）

        if hasattr(self, 'screenshot_engine_group'):

            self.screenshot_engine_group.setVisible(not plugin_enabled)

            if not plugin_enabled and hasattr(self, 'screenshot_engine_combo'):

                self._update_screenshot_engine_visibility()

            if hasattr(self, '_update_foreground_driver_visibility'):

                self._update_foreground_driver_visibility()

        # 切换执行模式标签页中的OLA插件绑定参数可见性

        if hasattr(self, 'exec_plugin_binding_group'):

            self.exec_plugin_binding_group.setVisible(plugin_enabled)

        if hasattr(self, 'native_window_settings_group'):

            self.native_window_settings_group.setVisible(not plugin_enabled)
            self.native_window_settings_group.setEnabled(not plugin_enabled)

        if hasattr(self, 'plugin_window_settings_group'):

            self.plugin_window_settings_group.setVisible(plugin_enabled)
            self.plugin_window_settings_group.setEnabled(plugin_enabled)

        if plugin_enabled and hasattr(self, '_refresh_plugin_binding_editor_context'):

            self._refresh_plugin_binding_editor_context()

        # 强制刷新布局，避免显示异常 - 使用延迟确保Qt完成布局计算

        if hasattr(self, 'exec_tab'):

            def refresh_layout():

                # 激活并更新布局

                if self.exec_tab.layout():

                    self.exec_tab.layout().invalidate()

                    self.exec_tab.layout().activate()

                    self.exec_tab.layout().update()

                # 更新控件几何形状

                self.exec_tab.updateGeometry()

                self.exec_tab.update()

                if hasattr(self, 'plugin_window_settings_group'):

                    window_tab = self.plugin_window_settings_group.parentWidget()

                    if window_tab and window_tab.layout():

                        window_tab.layout().invalidate()

                        window_tab.layout().activate()

                        window_tab.updateGeometry()

                        window_tab.update()

                # 调整对话框大小

                self.adjustSize()

            # 使用100ms延迟确保布局计算完成

            QTimer.singleShot(100, refresh_layout)

    def _toggle_binding_params_visibility(self):

        """

        切换绑定参数显示

        - 启用插件时：显示插件绑定参数，隐藏原有实现绑定参数和前后台模式选择

        - 禁用插件时：隐藏插件绑定参数，显示原有实现绑定参数和前后台模式选择

        """

        plugin_enabled = self.plugin_enabled_check.isChecked()

        # 如果要启用插件，首先检查服务器是否需要验证

        if plugin_enabled:

            import os

            # 首先检查服务器是否启用了验证

            try:



                # 获取硬件ID

                hardware_id = get_hardware_id()

                if not hardware_id:

                    logger.error("无法获取硬件ID")

                    QMessageBox.critical(

                        self,

                        "错误",

                        "无法获取硬件ID，请检查系统环境。"

                    )

                    self.plugin_enabled_check.blockSignals(True)

                    self.plugin_enabled_check.setChecked(False)

                    self.plugin_enabled_check.blockSignals(False)

                    return

                # 查询服务器验证状态

                http_session = None

                try:

                    registration_result = attempt_client_registration(hardware_id, http_session)

                finally:

                    try:

                        http_session.close()

                    except Exception:

                        pass

                if not registration_result.get("success", False):

                    logger.warning("无法连接到服务器获取验证状态")

                    QMessageBox.warning(

                        self,

                        "网络错误",

                        "无法连接到服务器，请检查网络连接。"

                    )

                    self.plugin_enabled_check.blockSignals(True)

                    self.plugin_enabled_check.setChecked(False)

                    self.plugin_enabled_check.blockSignals(False)

                    return

                # 检查是否被封禁

                if registration_result.get("is_banned", False):

                    ban_reason = registration_result.get("ban_reason", "未提供原因")

                    logger.critical(f"硬件ID已被封禁: {ban_reason}")

                    QMessageBox.critical(

                        self,

                        "账号已被封禁",

                        f"您的硬件ID已被封禁，无法使用插件模式。\n\n封禁原因: {ban_reason}\n\n如有疑问，请联系技术支持。"

                    )

                    self.plugin_enabled_check.blockSignals(True)

                    self.plugin_enabled_check.setChecked(False)

                    self.plugin_enabled_check.blockSignals(False)

                    return

                # 获取服务器验证状态

                server_license_validation_enabled = registration_result.get("license_validation_enabled", True)

                logger.info(f"服务器许可证验证状态: {'开启' if server_license_validation_enabled else '关闭'}")

                # 如果服务器验证已关闭，直接允许启用插件模式

                if not server_license_validation_enabled:

                    logger.info("服务器验证已关闭，插件模式无需授权验证")

                    # 跳过编辑器授权验证，但仍需要继续校验插件运行时激活状态

                # 服务器验证已开启，需要检查授权

                else:

                    logger.info("服务器验证已开启，插件模式需要授权验证")

            except Exception as e:

                logger.error(f"检查服务器验证状态时出错: {e}", exc_info=True)

                QMessageBox.critical(

                    self,

                    "错误",

                    f"检查服务器验证状态时出错：{str(e)}\n\n插件模式已被禁用。"

                )

                self.plugin_enabled_check.blockSignals(True)

                self.plugin_enabled_check.setChecked(False)

                self.plugin_enabled_check.blockSignals(False)

                return

            if server_license_validation_enabled:

                # 检查授权文件是否存在（避免每次都要求输入授权码）

                license_file = LICENSE_FILE

                # 【修复】如果授权文件存在，进行强制在线验证确保授权有效

                if os.path.exists(license_file):

                    logger.info("检测到授权文件存在，正在验证授权有效性...")

                    # 导入验证函数

                    try:
                        # 获取硬件ID和授权码

                        hardware_id = get_hardware_id()

                        license_key = load_local_license()

                        # 【修复】如果无法获取硬件ID或授权码（可能是文件被篡改），直接视为验证失败

                        if not hardware_id:

                            logger.critical("无法获取硬件ID，授权验证失败")

                            # 删除无效的授权文件

                            try:

                                if os.path.exists(license_file):

                                    os.remove(license_file)

                                    logger.info("已删除无效的授权文件")

                            except:

                                pass

                            # 强制取消勾选

                            self.plugin_enabled_check.blockSignals(True)

                            self.plugin_enabled_check.setChecked(False)

                            self.plugin_enabled_check.blockSignals(False)

                            QMessageBox.critical(

                                self,

                                "插件授权验证失败",

                                "无法获取硬件ID，授权验证失败。\n\n"

                                "插件模式已被禁用。"

                            )

                            return

                        if not license_key:

                            logger.critical("无法解密授权文件，文件可能被篡改或损坏")

                            # 删除无效的授权文件

                            try:

                                if os.path.exists(license_file):

                                    os.remove(license_file)

                                    logger.info("已删除无效的授权文件")

                            except:

                                pass

                            # 强制取消勾选

                            self.plugin_enabled_check.blockSignals(True)

                            self.plugin_enabled_check.setChecked(False)

                            self.plugin_enabled_check.blockSignals(False)

                            QMessageBox.critical(

                                self,

                                "插件授权验证失败",

                                "授权文件无法解密，文件可能被篡改或损坏。\n\n"

                                "插件模式已被禁用，授权文件已删除。"

                            )

                            return

                        # 执行在线验证

                        is_valid, status_code, license_type = enforce_online_validation(hardware_id, license_key)

                        if not is_valid:

                            logger.critical(f"插件授权验证失败：状态码 {status_code}")

                            # 删除无效的授权文件

                            try:

                                if os.path.exists(license_file):

                                    os.remove(license_file)

                                    logger.info("已删除无效的授权文件")

                            except:

                                pass

                            # 强制取消勾选

                            self.plugin_enabled_check.blockSignals(True)

                            self.plugin_enabled_check.setChecked(False)

                            self.plugin_enabled_check.blockSignals(False)

                            plugin_enabled = False

                            QMessageBox.critical(

                                self,

                                "插件授权验证失败",

                                f"插件模式授权验证失败（状态码：{status_code}）。\n\n"

                                "可能的原因：\n"

                                "- 授权码已过期\n"

                                "- 授权码无效\n"

                                "- 授权文件被篡改\n"

                                "- 网络连接失败\n\n"

                                "插件模式已被禁用，授权文件已删除。"

                            )

                            return  # 提前返回，不继续启用插件

                        else:

                            logger.info(f"插件授权验证成功，授权类型: {license_type}")

                    except Exception as e:

                        logger.error(f"授权验证过程出错: {e}", exc_info=True)

                        # 删除可能损坏的授权文件

                        try:

                            if os.path.exists(license_file):

                                os.remove(license_file)

                                logger.info("已删除可能损坏的授权文件")

                        except:

                            pass

                        # 强制取消勾选

                        self.plugin_enabled_check.blockSignals(True)

                        self.plugin_enabled_check.setChecked(False)

                        self.plugin_enabled_check.blockSignals(False)

                        QMessageBox.critical(

                            self,

                            "插件授权验证异常",

                            f"插件模式授权验证过程中发生异常：\n{str(e)}\n\n"

                            "插件模式已被禁用，授权文件已删除。"

                        )

                        return  # 提前返回

                else:

                    # 授权文件不存在，需要用户输入授权码

                    logger.warning("插件模式需要授权验证，当前未找到授权文件")

                    # 弹出授权验证对话框

                    result = self._show_license_dialog()

                    # 如果授权失败或用户取消，退回到原有模式

                    if not result:

                        logger.info("授权验证失败或用户取消，禁用插件模式")

                        # 强制取消勾选

                        self.plugin_enabled_check.blockSignals(True)  # 阻止信号，避免递归调用

                        self.plugin_enabled_check.setChecked(False)

                        self.plugin_enabled_check.blockSignals(False)

                        plugin_enabled = False  # 更新状态变量

                        QMessageBox.warning(

                            self,

                            "插件模式需要授权",

                            "启用插件模式需要有效的授权码。\n已退回到原有模式。"

                        )

            if plugin_enabled:

                from app_core.plugin_bridge import check_plugin_mode_runtime

                runtime_ready, runtime_message = check_plugin_mode_runtime(
                    'ola',
                    runtime_config_override=(
                        self._collect_current_plugin_ola_auth()
                        if hasattr(self, '_collect_current_plugin_ola_auth')
                        else None
                    ),
                )

                if not runtime_ready:

                    logger.error(f"插件运行时校验失败: {runtime_message}")

                    self.plugin_enabled_check.blockSignals(True)

                    self.plugin_enabled_check.setChecked(False)

                    self.plugin_enabled_check.blockSignals(False)

                    QMessageBox.critical(

                        self,

                        "插件模式需要激活",

                        runtime_message or "插件模式未激活，请先完成插件授权。"

                    )

                    return

        # 验证完成后，更新UI显示

        self._update_binding_params_visibility()

    def _show_license_dialog(self):

        """显示授权验证对话框，返回是否验证成功"""

        try:

            # 检查 hardware_id 是否有效

            if not self.hardware_id or len(self.hardware_id) != 64:

                logger.error(f"无效的硬件ID: {self.hardware_id}")

                return False

            # 创建HTTP会话

            http_session = None

            try:

                # 显示授权对话框

                license_dialog = LicenseInputDialog(self.hardware_id, http_session, parent=self)

                center_window_on_widget_screen(license_dialog, self)

                result = license_dialog.exec()

            finally:

                try:

                    http_session.close()

                except Exception:

                    pass

            if result == QDialog.DialogCode.Accepted:

                # 验证成功，保存授权码

                self.license_key = license_dialog.get_license_key()

                logger.info("插件模式授权验证成功")

                # 保存授权码到本地

                try:
                    save_local_license(self.license_key)

                    logger.info("已保存授权码到本地")

                except Exception as save_error:

                    logger.warning(f"保存授权码失败: {save_error}")

                return True

            else:

                # 用户取消或验证失败

                logger.info("用户取消授权验证或验证失败")

                return False

        except Exception as e:

            logger.error(f"显示授权对话框失败: {e}")

            import traceback

            logger.error(traceback.format_exc())

            return False

    def _disable_plugin_enabled_checkbox(self):

        if not hasattr(self, 'plugin_enabled_check'):

            return

        self.plugin_enabled_check.blockSignals(True)

        self.plugin_enabled_check.setChecked(False)

        self.plugin_enabled_check.blockSignals(False)

    def _toggle_binding_params_visibility(self):

        plugin_enabled = self.plugin_enabled_check.isChecked()

        if plugin_enabled:

            self.hardware_id = str(get_hardware_id() or "").strip()

            activation_result = prepare_plugin_mode_activation(self.hardware_id)

            if activation_result.requires_license_input:

                if not self._show_license_dialog():

                    logger.info("插件授权未完成，禁用插件模式")

                    self._disable_plugin_enabled_checkbox()

                    QMessageBox.warning(

                        self,

                        "插件模式需要授权",

                        "启用插件模式需要有效的授权码。\n已退回到原有模式。",

                    )

                    return

            elif not activation_result.success:

                logger.error(f"插件授权检查失败: {activation_result.message}")

                self._disable_plugin_enabled_checkbox()

                QMessageBox.critical(

                    self,

                    activation_result.title or "插件授权验证失败",

                    activation_result.message or "插件模式授权验证失败。",

                )

                return

            from app_core.plugin_bridge import check_plugin_mode_runtime

            runtime_ready, runtime_message = check_plugin_mode_runtime(
                'ola',
                runtime_config_override=(
                    self._collect_current_plugin_ola_auth()
                    if hasattr(self, '_collect_current_plugin_ola_auth')
                    else None
                ),
            )

            if not runtime_ready:

                logger.error(f"插件运行时校验失败: {runtime_message}")

                self._disable_plugin_enabled_checkbox()

                QMessageBox.critical(

                    self,

                    "插件模式需要激活",

                    runtime_message or "插件模式未激活，请先完成插件授权。",

                )

                return

        self._update_binding_params_visibility()

    def _show_license_dialog(self):

        try:

            if not self.hardware_id or len(self.hardware_id) != 64:

                logger.error(f"无效的硬件ID: {self.hardware_id}")

                return False

            http_session = None

            try:

                license_dialog = LicenseInputDialog(self.hardware_id, http_session, parent=self)

                center_window_on_widget_screen(license_dialog, self)

                result = license_dialog.exec()

            finally:

                try:

                    http_session.close()

                except Exception:

                    pass

            if result != QDialog.DialogCode.Accepted:

                logger.info("用户取消授权验证或验证失败")

                return False

            self.license_key = license_dialog.get_license_key()

            if not self.license_key:

                logger.warning("授权验证通过后未获取到授权码")

                return False

            try:

                save_local_license(self.license_key)

            except Exception as save_error:

                logger.warning(f"保存授权码失败: {save_error}")

            logger.info("插件模式授权验证成功")

            return True

        except Exception as e:

            logger.error(f"显示授权对话框失败: {e}", exc_info=True)

            return False

    def _disable_plugin_enabled_checkbox(self):

        if not hasattr(self, 'plugin_enabled_check'):

            return

        self.plugin_enabled_check.blockSignals(True)

        self.plugin_enabled_check.setChecked(False)

        self.plugin_enabled_check.blockSignals(False)

    def _toggle_binding_params_visibility(self):

        plugin_enabled = self.plugin_enabled_check.isChecked()

        if plugin_enabled:

            self.hardware_id = str(get_hardware_id() or "").strip()

            activation_result = prepare_plugin_mode_activation(self.hardware_id)

            if activation_result.requires_license_input:

                if not self._show_license_dialog():

                    logger.info("plugin authorization not completed, disabling plugin mode")

                    self._disable_plugin_enabled_checkbox()

                    QMessageBox.warning(

                        self,

                        "\u63d2\u4ef6\u6a21\u5f0f\u9700\u8981\u6388\u6743",

                        "\u542f\u7528\u63d2\u4ef6\u6a21\u5f0f\u9700\u8981\u6709\u6548\u7684\u6388\u6743\u7801\u3002\n"
                        "\u5df2\u9000\u56de\u5230\u539f\u6709\u6a21\u5f0f\u3002",

                    )

                    return

            elif not activation_result.success:

                logger.error(f"插件授权检查失败：{activation_result.message}")

                self._disable_plugin_enabled_checkbox()

                QMessageBox.critical(

                    self,

                    activation_result.title or "\u63d2\u4ef6\u6388\u6743\u9a8c\u8bc1\u5931\u8d25",

                    activation_result.message or "\u63d2\u4ef6\u6a21\u5f0f\u6388\u6743\u9a8c\u8bc1\u5931\u8d25\u3002",

                )

                return

            from app_core.plugin_bridge import check_plugin_mode_runtime

            runtime_ready, runtime_message = check_plugin_mode_runtime(
                'ola',
                runtime_config_override=(
                    self._collect_current_plugin_ola_auth()
                    if hasattr(self, '_collect_current_plugin_ola_auth')
                    else None
                ),
            )

            if not runtime_ready:

                logger.error(f"插件运行时检查失败：{runtime_message}")

                self._disable_plugin_enabled_checkbox()

                QMessageBox.critical(

                    self,

                    "\u63d2\u4ef6\u6a21\u5f0f\u9700\u8981\u6fc0\u6d3b",

                    runtime_message or "\u63d2\u4ef6\u6a21\u5f0f\u672a\u6fc0\u6d3b\uff0c\u8bf7\u5148\u5b8c\u6210\u63d2\u4ef6\u6388\u6743\u3002",

                )

                return

        self._update_binding_params_visibility()

    def _show_license_dialog(self):

        try:

            if not self.hardware_id or len(self.hardware_id) != 64:

                logger.error(f"invalid hardware id: {self.hardware_id}")

                return False

            http_session = None

            try:

                license_dialog = LicenseInputDialog(self.hardware_id, http_session, parent=self)

                center_window_on_widget_screen(license_dialog, self)

                result = license_dialog.exec()

            finally:

                try:

                    http_session.close()

                except Exception:

                    pass

            if result != QDialog.DialogCode.Accepted:

                logger.info("user cancelled license validation or validation failed")

                return False

            self.license_key = license_dialog.get_license_key()

            if not self.license_key:

                logger.warning("validated license dialog returned an empty license key")

                return False

            try:

                save_local_license(self.license_key)

            except Exception as save_error:

                logger.warning(f"持久化许可证密钥失败：{save_error}")

            logger.info("plugin authorization completed")

            return True

        except Exception as e:

            logger.error(f"显示许可证弹窗失败：{e}", exc_info=True)

            return False

    def _update_execution_mode_visibility(self):

        """更新执行模式设置的可见性（现在始终显示，由用户手动选择）"""

        # 执行模式设置始终可见，不再根据窗口数量自动隐藏

        if hasattr(self, 'exec_mode_group'):

            self.exec_mode_group.setVisible(True)

    def _refresh_plugin_mode_ui(self):

        """刷新插件模式UI控件状态"""

        try:

            plugin_settings = self.current_config.get('plugin_settings', {})

            is_enabled = plugin_settings.get('enabled', False)

            # 阻塞信号，避免触发验证逻辑

            if hasattr(self, 'plugin_enabled_check'):

                self.plugin_enabled_check.blockSignals(True)

                self.plugin_enabled_check.setChecked(is_enabled)

                self.plugin_enabled_check.blockSignals(False)

                logger.info(f"[UI刷新] 插件模式复选框状态已更新: {is_enabled}")

                if hasattr(self, '_apply_plugin_ola_auth_to_controls') and hasattr(self, '_get_effective_plugin_ola_auth'):

                    self._apply_plugin_ola_auth_to_controls(self._get_effective_plugin_ola_auth())

                # 刷新绑定参数的可见性

                self._update_binding_params_visibility()

            # 刷新执行模式下拉框

            if hasattr(self, 'mode_combo'):

                execution_mode = normalize_execution_mode_setting(

                    self.current_config.get('execution_mode', 'background_sendmessage')

                )

                display_mode = self.MODE_DISPLAY_MAP.get(execution_mode, "前台一模式")

                self.mode_combo.blockSignals(True)

                self.mode_combo.setCurrentText(display_mode)

                self.mode_combo.blockSignals(False)

                if hasattr(self, 'foreground_driver_combo'):

                    legacy_backend = str(

                        self.current_config.get('foreground_driver_backend', 'interception') or 'interception'

                    ).strip().lower()

                    mouse_backend = str(

                        self.current_config.get('foreground_mouse_driver_backend', legacy_backend) or legacy_backend

                    ).strip().lower()

                    backend_index = self.foreground_driver_combo.findData(mouse_backend)

                    if backend_index < 0:

                        backend_index = self.foreground_driver_combo.findData('interception')

                    if backend_index >= 0:

                        self.foreground_driver_combo.blockSignals(True)

                        self.foreground_driver_combo.setCurrentIndex(backend_index)

                        self.foreground_driver_combo.blockSignals(False)

                if hasattr(self, 'foreground_keyboard_driver_combo'):

                    legacy_backend = str(

                        self.current_config.get('foreground_driver_backend', 'interception') or 'interception'

                    ).strip().lower()

                    keyboard_backend = str(

                        self.current_config.get('foreground_keyboard_driver_backend', legacy_backend) or legacy_backend

                    ).strip().lower()

                    keyboard_backend_index = self.foreground_keyboard_driver_combo.findData(keyboard_backend)

                    if keyboard_backend_index < 0:

                        keyboard_backend_index = self.foreground_keyboard_driver_combo.findData('interception')

                    if keyboard_backend_index >= 0:

                        self.foreground_keyboard_driver_combo.blockSignals(True)

                        self.foreground_keyboard_driver_combo.setCurrentIndex(keyboard_backend_index)

                        self.foreground_keyboard_driver_combo.blockSignals(False)

                if hasattr(self, 'ib_driver_combo'):

                    ib_driver = str(self.current_config.get('ibinputsimulator_driver', 'Logitech') or 'Logitech').strip()

                    ib_index = self.ib_driver_combo.findData(ib_driver)

                    if ib_index < 0:

                        ib_index = self.ib_driver_combo.findData('Logitech')

                    if ib_index >= 0:

                        self.ib_driver_combo.blockSignals(True)

                        self.ib_driver_combo.setCurrentIndex(ib_index)

                        self.ib_driver_combo.blockSignals(False)

                self._update_foreground_driver_visibility()

                logger.info(f"[UI刷新] 执行模式下拉框状态已更新: {display_mode}")

        except Exception as e:

            logger.warning(f"刷新插件模式UI失败: {e}")
