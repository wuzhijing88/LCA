"""应用程序标识。离线版不维护数字版本号。"""

from urllib.parse import urlunsplit

APP_NAME = "LCA"
APP_EDITION = "离线版"
APP_VERSION = APP_EDITION
APP_SUMMARY = "本地、视觉驱动的 Windows 桌面工作流自动化程序。"
APP_LICENSE_NAME = "GNU Affero General Public License v3.0"
APP_LICENSE_SPDX = "AGPL-3.0-only"
APP_SOURCE_REPOSITORY = "github.com/wuzhijing88/LCA"


def app_source_url() -> str:
    host, _, path = APP_SOURCE_REPOSITORY.partition("/")
    return urlunsplit(("https", host, f"/{path}", "", ""))
