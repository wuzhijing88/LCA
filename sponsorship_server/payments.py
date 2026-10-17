"""ZPAY 现行页面支付协议：https://zpayz.cn/doc.html。"""

import asyncio
import hashlib
import hmac
import re
from decimal import Decimal

import httpx

from .config import Settings

ORDER_NAME = "LCA 开发赞助"
# ZPAY submit.php 的现行收银台跳转地址。
CHECKOUT_ORIGIN = "https://api.z-pay.cn"


class PaymentError(ValueError):
    pass


class GatewayUnavailable(RuntimeError):
    pass


def amount_cents(value: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"(?:0|[1-9][0-9]{0,4})(?:\.[0-9]{1,2})?", value):
        raise PaymentError("金额必须是最多两位小数的数字")
    cents = int(Decimal(value) * 100)
    if not 100 <= cents <= 500000:
        raise PaymentError("单次赞助金额为 1～5000 元")
    return cents


def money_text(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def sign_fields(fields: dict[str, str], key: str) -> str:
    if any(not name.isascii() for name in fields):
        raise PaymentError("支付参数名必须使用 ASCII 字符")
    content = "&".join(
        f"{name}={fields[name]}" for name in sorted(fields)
        if name not in ("sign", "sign_type") and fields[name] != ""
    )
    return hashlib.md5((content + key).encode("utf-8")).hexdigest()


def checkout_fields(order: dict, settings: Settings) -> dict[str, str]:
    fields = {
        "pid": settings.pid,
        "type": order["payment_type"],
        "out_trade_no": order["order_id"],
        "notify_url": settings.public_url + "/notify",
        "return_url": settings.public_url + "/return",
        "name": ORDER_NAME,
        "money": money_text(order["amount_cents"]),
        "sign_type": "MD5",
    }
    fields["sign"] = sign_fields(fields, settings.key)
    return fields


def verify_notice(fields: dict[str, str], order: dict, settings: Settings) -> str:
    signature = fields.get("sign", "")
    if (fields.get("sign_type") != "MD5" or not re.fullmatch(r"[0-9a-f]{32}", signature)
            or not hmac.compare_digest(signature, sign_fields(fields, settings.key))):
        raise PaymentError("支付通知签名无效")
    if (fields.get("pid") != settings.pid or fields.get("out_trade_no") != order["order_id"]
            or fields.get("type") != order["payment_type"] or fields.get("name") != ORDER_NAME
            or fields.get("trade_status") != "TRADE_SUCCESS"
            or amount_cents(fields.get("money", "")) != order["amount_cents"]):
        raise PaymentError("支付通知与订单信息不一致")
    trade_no = fields.get("trade_no", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", trade_no):
        raise PaymentError("支付流水号无效")
    if order["trade_no"] is not None and order["trade_no"] != trade_no:
        raise PaymentError("支付流水号与已确认订单不一致")
    return trade_no


class ZpayGateway:
    def __init__(self, client: httpx.AsyncClient, settings: Settings):
        self.client = client
        self.settings = settings

    async def confirm(self, order: dict, trade_no: str) -> None:
        try:
            # 回调响应应少于五秒；总耗时也有上限，禁止网络失败后改判已支付。
            data = await asyncio.wait_for(self._query(order["order_id"]), timeout=3)
        except (httpx.HTTPError, asyncio.TimeoutError, ValueError) as exc:
            raise GatewayUnavailable("暂时无法向支付平台确认到账，请稍后重新核实") from exc
        if not isinstance(data, dict) or type(data.get("code")) is not int or data["code"] != 1:
            raise GatewayUnavailable("支付平台未返回有效订单，到账状态未知")
        if type(data.get("status")) is int and data["status"] == 0:
            raise GatewayUnavailable("支付平台尚未确认到账，请稍后重新核实，无需重复付款")
        if (type(data.get("status")) is not int or data["status"] != 1
                or str(data.get("pid", "")) != self.settings.pid
                or data.get("out_trade_no") != order["order_id"]
                or data.get("trade_no") != trade_no or data.get("type") != order["payment_type"]
                or data.get("name") != ORDER_NAME
                or amount_cents(data.get("money", "")) != order["amount_cents"]):
            raise PaymentError("支付平台尚未确认到账或订单信息不一致")

    async def _query(self, order_id: str):
        # 不输出含商户密钥的请求 URL，不跟随重定向。
        async with self.client.stream("GET", self.settings.gateway_url + "/api.php", params={
            "act": "order", "pid": self.settings.pid, "key": self.settings.key,
            "out_trade_no": order_id,
        }) as response:
            response.raise_for_status()
            content = bytearray()
            async for block in response.aiter_bytes():
                content.extend(block)
                if len(content) > 65536:
                    raise ValueError("支付平台响应过大")
        import json
        return json.loads(content)
