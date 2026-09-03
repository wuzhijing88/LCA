# -*- coding: utf-8 -*-
"""大漠 BindWindow / BindWindowEx 失败原因翻译。

宿主在绑定失败时把 dm.GetLastError() 与 COM 异常一并带回；这里把它们翻成可读文案，
供试绑提示、日志与窗口条目标注共用。码表按官方 GetLastError 说明整理，个别条目在不同
dm 版本间措辞略有差异，未收录的码原样给出并提示查官方文档。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

# 与绑定直接相关的 GetLastError 取值（负数）。
BIND_ERROR_MESSAGES: dict[int, str] = {
    -1: "使用了收费绑定功能但插件未注册（注册码未生效或已过期）",
    -2: "目标窗口受保护或被安全软件拦截（模式 0/2 常见）；可关闭安全软件、以管理员运行或换绑定模式",
    -3: "目标窗口受保护或出现异常（模式 0/2）；可尝试其他绑定模式",
    -4: "模式 101/103 出现异常错误",
    -5: "模式 101/103 绑定失败；先关闭目标窗口重开再绑，或检查是否以管理员运行",
    -6: "模式 101/103 异常，可能被安全软件干扰",
    -7: "模式 101/103 异常，可能被安全软件干扰",
    -8: "模式 101/103 目标进程可能有保护，或插件版本过老",
    -9: "模式 101/103 异常，可能被安全软件干扰",
    -10: "模式 101/103 目标进程可能有保护，或插件版本过老",
    -11: "模式 101/103 目标进程有保护",
    -12: "模式 101/103 目标进程有保护",
    -13: "模式 101/103 目标进程有保护，或上一次绑定未解除；请先解绑再试",
    -14: "系统缺少运行库（如 DirectX）或所选 dx.mouse.api / dx.keypad.api 在该系统不可用",
    -16: "模式 0/2 绑定失败，目标窗口有保护",
    -17: "模式 101/103 绑定失败：目标进程里仍留有上一次未解绑的 dm.dll",
    -18: "绑定失败，插件版本过老或目标窗口有保护",
    -19: "绑定失败，dx.public.hide.dll 使用不当",
    -20: "绑定失败，dx.public.km.protect 使用不当",
    -21: "目标窗口句柄无效或窗口已关闭",
    -22: "系统不支持所选的 dx 模式",
    -23: "绑定失败，当前系统/进程位数不匹配（32 位相关）",
    -24: "绑定失败，dx.public.graphic.protect 使用不当",
    -25: "绑定失败，dx.public.disable.window.* 使用不当",
    -26: "使用了 dx.public.km.protect 但缺少配套设置",
    -27: "使用了 dx.public.prevent.block 但缺少配套设置",
    -28: "使用了 dx.public.anti.api 但缺少配套设置",
}


@dataclass(frozen=True)
class BindOutcome:
    """一次 bind RPC 的结果。宿主返回字典；老宿主或测试桩只返回布尔值时也能构造。"""

    ok: bool
    last_error: int = 0
    error: str = ""
    api: str = ""
    # 本次 bind 是否为该窗口新建了 dm 对象并向大漠 Reg；registrations 是宿主累计注册次数
    registered: bool = False
    registrations: int = 0

    def __bool__(self) -> bool:
        return bool(self.ok)

    @classmethod
    def from_rpc(cls, result: Any) -> "BindOutcome":
        if isinstance(result, cls):
            return result
        if isinstance(result, Mapping):
            try:
                last_error = int(result.get("last_error") or 0)
            except (TypeError, ValueError):
                last_error = 0
            try:
                registrations = int(result.get("registrations") or 0)
            except (TypeError, ValueError):
                registrations = 0
            return cls(
                ok=bool(result.get("ok")),
                last_error=last_error,
                error=str(result.get("error") or ""),
                api=str(result.get("api") or ""),
                registered=bool(result.get("registered")),
                registrations=registrations,
            )
        return cls(ok=bool(result))


def describe_bind_error_code(last_error: int) -> str:
    try:
        code = int(last_error)
    except (TypeError, ValueError):
        return ""
    if code == 0:
        return ""
    text = BIND_ERROR_MESSAGES.get(code)
    if text:
        return f"GetLastError={code}：{text}"
    return f"GetLastError={code}：未收录的错误码，请对照大漠官方文档 GetLastError 说明"


def describe_bind_failure(
    outcome: Optional[BindOutcome],
    *,
    display: str = "",
    mouse: str = "",
    keypad: str = "",
    mode: Optional[int] = None,
) -> str:
    """组合参数与宿主返回的信息，生成一句可读的失败原因。"""
    params = f"display={display or '-'} mouse={mouse or '-'} keypad={keypad or '-'} mode={mode if mode is not None else '-'}"
    if outcome is None:
        return f"绑定未执行（{params}）"
    parts: list[str] = []
    if outcome.api:
        parts.append(outcome.api)
    code_text = describe_bind_error_code(outcome.last_error)
    if code_text:
        parts.append(code_text)
    elif outcome.error:
        parts.append(outcome.error)
    else:
        parts.append("插件返回失败但未给出错误码")
    if outcome.error and code_text and outcome.error not in code_text:
        parts.append(outcome.error)
    return f"{'，'.join(parts)}（{params}）"


__all__ = [
    "BIND_ERROR_MESSAGES",
    "BindOutcome",
    "describe_bind_error_code",
    "describe_bind_failure",
]
