from ..parameter_panel_support import *


class ParameterPanelMediaBrowserMixin:

        def _enable_browser_accessibility(self):

            """启用Chrome/Edge浏览器的UIAutomation辅助功能支持"""

            import winreg

            import os

            from PySide6.QtWidgets import QMessageBox



            try:

                success_count = 0



                # 常见浏览器快捷方式路径

                shortcut_paths = [

                    os.path.expanduser(r"~\Desktop\Google Chrome.lnk"),

                    os.path.expanduser(r"~\Desktop\Microsoft Edge.lnk"),

                    r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Google Chrome.lnk",

                    r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Microsoft Edge.lnk",

                ]



                # 尝试修改快捷方式添加启动参数

                try:

                    from utils.win32com_runtime import prepare_win32com_runtime

                    prepare_win32com_runtime()
                    import win32com.client
                    shell = win32com.client.Dispatch("WScript.Shell")



                    for shortcut_path in shortcut_paths:

                        if os.path.exists(shortcut_path):

                            try:

                                shortcut = shell.CreateShortCut(shortcut_path)

                                args = shortcut.Arguments or ""



                                if "--force-renderer-accessibility" not in args:

                                    new_args = args + " --force-renderer-accessibility=complete"

                                    shortcut.Arguments = new_args.strip()

                                    shortcut.Save()

                                    success_count += 1

                                else:

                                    success_count += 1

                            except:

                                pass

                except ImportError:

                    pass



                # 同时设置注册表

                for browser_name, key_path in [

                    ("Chrome", r"SOFTWARE\Google\Chrome\Accessibility"),

                    ("Edge", r"SOFTWARE\Microsoft\Edge\Accessibility")

                ]:

                    for hive in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:

                        try:

                            key = winreg.CreateKeyEx(hive, key_path, 0, winreg.KEY_SET_VALUE)

                            winreg.SetValueEx(key, "AccessibilityMode", 0, winreg.REG_DWORD, 1)

                            winreg.CloseKey(key)

                            break

                        except:

                            continue



                msg = "已尝试启用浏览器UIAutomation支持。\n\n"

                msg += "重要步骤:\n"

                msg += "1. 完全关闭浏览器（包括后台进程，可在任务管理器中结束）\n"

                msg += "2. 重新打开浏览器\n\n"

                msg += "如仍不生效，请手动在浏览器快捷方式目标后添加:\n"

                msg += "--force-renderer-accessibility=complete"



                QMessageBox.information(self, "设置完成", msg)



            except Exception as e:

                logger.error(f"启用浏览器辅助功能失败: {e}")

                QMessageBox.warning(

                    self,

                    "提示",

                    "请手动在浏览器快捷方式目标后添加:\n"

                    "--force-renderer-accessibility=complete\n\n"

                    "然后完全关闭浏览器后重新打开。"

                )
