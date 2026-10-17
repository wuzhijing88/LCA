"""赞助网页、支付表单与 ZPAY 回调。"""

import hashlib
import hmac
import logging
import re
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qsl

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from .config import Settings, load_settings
from .payments import (
    CHECKOUT_ORIGIN, GatewayUnavailable, PaymentError, ZpayGateway, amount_cents,
    checkout_fields, money_text, verify_notice,
)
from .store import OrderStore

ROOT = Path(__file__).resolve().parent
COOKIE = "__Host-lca-sponsor-form"
PAYMENT_LABELS = {"alipay": "支付宝", "wxpay": "微信支付"}


def make_form_token(secret: str) -> str:
    content = f"{int(time.time())}.{secrets.token_hex(24)}"
    return content + "." + hmac.new(secret.encode(), content.encode(), hashlib.sha256).hexdigest()


def valid_form_token(token: str, secret: str) -> bool:
    if not re.fullmatch(r"[0-9]{10}\.[0-9a-f]{48}\.[0-9a-f]{64}", token):
        return False
    issued, nonce, signature = token.split(".")
    expected = hmac.new(secret.encode(), f"{issued}.{nonce}".encode(), hashlib.sha256).hexdigest()
    return 0 <= time.time() - int(issued) < 3600 and hmac.compare_digest(signature, expected)


def unique_fields(pairs: list[tuple[str, str]]) -> dict[str, str]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise PaymentError("请求包含重复字段")
        result[key] = value
    return result


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else load_settings()
    store = OrderStore(settings.database)
    templates = Jinja2Templates(directory=str(ROOT / "templates"))
    templates.env.filters["money"] = money_text

    @asynccontextmanager
    async def lifespan(app):
        await run_in_threadpool(store.initialize)
        # httpx 的 INFO 请求日志包含查询字符串，订单查询协议会携带商户密钥。
        logging.getLogger("httpx").setLevel(logging.WARNING)
        async with httpx.AsyncClient(timeout=2.5, follow_redirects=False, trust_env=False) as client:
            app.state.gateway = ZpayGateway(client, settings)
            try:
                yield
            finally:
                app.state.gateway = None

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    def render(request, template, context=None, status_code=200):
        return templates.TemplateResponse(request=request, name=template,
                                          context=context or {}, status_code=status_code)

    @app.middleware("http")
    async def protect_response(request, call_next):
        if len(request.scope["query_string"]) > 8192:
            return PlainTextResponse("请求参数过长", status_code=413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        # 同源表单保留 Origin；跨域前往支付平台时不携带本站地址。
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self'; "
            f"form-action 'self' {settings.gateway_url} {CHECKOUT_ORIGIN}; "
            "frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    @app.exception_handler(PaymentError)
    async def payment_error(request, exc):
        if request.url.path == "/notify":
            return PlainTextResponse("fail", status_code=400)
        return render(request, "result.html", {"confirmed": False, "message": str(exc)}, 400)

    @app.exception_handler(GatewayUnavailable)
    async def gateway_error(request, exc):
        if request.url.path == "/notify":
            return PlainTextResponse("fail", status_code=503)
        return render(request, "result.html", {"confirmed": False, "message": str(exc), "retry": True}, 503)

    @app.exception_handler(sqlite3.Error)
    async def database_error(request, exc):
        if request.url.path == "/notify":
            return PlainTextResponse("fail", status_code=503)
        return render(request, "result.html", {"confirmed": False, "message": "暂时无法读取或保存订单，请稍后重试"}, 503)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        message = "页面不存在" if exc.status_code == 404 else "请求无法处理，请返回赞助首页重试"
        return render(request, "result.html", {"confirmed": False, "message": message}, exc.status_code)

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        page_text = request.query_params.get("page", "1")
        if not re.fullmatch(r"[1-9][0-9]{0,4}", page_text):
            raise PaymentError("赞助墙页码无效")
        page = int(page_text)
        sponsors, has_next, count, total = await run_in_threadpool(store.wall, page)
        token = make_form_token(settings.csrf_secret)
        response = render(request, "index.html", {
            "sponsors": sponsors, "has_next": has_next, "page": page,
            "count": count, "total": total, "token": token,
            "payment_types": {key: PAYMENT_LABELS[key] for key in settings.payment_types},
        })
        response.set_cookie(COOKIE, token, max_age=3600, secure=True, httponly=True, samesite="lax", path="/")
        return response

    @app.get("/assets/theme.css")
    async def theme():
        return Response((ROOT.parent / "themes" / "sponsorship.css").read_text(encoding="utf-8"), media_type="text/css")

    @app.get("/favicon.ico")
    async def project_icon():
        return Response((ROOT.parent / "resources" / "icon.ico").read_bytes(), media_type="image/vnd.microsoft.icon")

    @app.get("/assets/checkout.js")
    async def checkout_script():
        return Response((ROOT / "static" / "checkout.js").read_text(encoding="utf-8"), media_type="text/javascript")

    @app.get("/assets/sponsor.js")
    async def sponsor_script():
        return Response((ROOT / "static" / "sponsor.js").read_text(encoding="utf-8"), media_type="text/javascript")

    @app.post("/orders", response_class=HTMLResponse)
    async def create_order(request: Request):
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/x-www-form-urlencoded":
            raise PaymentError("赞助表单格式无效")
        if request.headers.get("origin") != settings.public_url:
            raise PaymentError("表单来源无效，请刷新赞助首页")
        body = bytearray()
        async for block in request.stream():
            body.extend(block)
            if len(body) > 8192:
                raise PaymentError("赞助表单内容过长")
        try:
            fields = unique_fields(parse_qsl(body.decode("utf-8"), keep_blank_values=True,
                                            encoding="utf-8", errors="strict", max_num_fields=6))
        except (ValueError, UnicodeDecodeError) as exc:
            raise PaymentError("赞助表单编码或字段数量无效") from exc
        allowed = {"token", "amount", "payment_type", "nickname", "message", "public"}
        if fields.keys() - allowed:
            raise PaymentError("赞助表单包含未知字段")
        token = fields.get("token", "")
        cookie = request.cookies.get(COOKIE, "")
        if not cookie or not hmac.compare_digest(cookie.encode(), token.encode()) or not valid_form_token(token, settings.csrf_secret):
            raise PaymentError("赞助表单已过期，请刷新首页后重新填写")
        cents = amount_cents(fields.get("amount", ""))
        payment_type = fields.get("payment_type", "")
        if payment_type not in settings.payment_types:
            raise PaymentError("请选择已开通的支付方式")
        nickname = fields.get("nickname", "").strip()
        message = fields.get("message", "").strip()
        if len(nickname) > 24 or len(message) > 200 or any(ord(c) < 32 for c in nickname + message):
            raise PaymentError("昵称最多 24 字，留言最多 200 字，不能包含控制字符")
        if fields.get("public", "") not in ("", "yes"):
            raise PaymentError("公开展示选项无效")
        public = fields.get("public") == "yes"
        if public and not nickname:
            raise PaymentError("公开展示时请填写昵称")
        # 同一份有效表单只有一个订单号，双击或网络重发不会重复创建订单。
        order_id = str(int(hashlib.sha256(token.encode()).hexdigest(), 16) % (10 ** 32)).zfill(32)
        order = await run_in_threadpool(store.create, order_id, cents, payment_type,
                                       nickname if public else "", message if public else "", public)
        if order["paid_at"] is not None:
            return render(request, "result.html", {"confirmed": True, "message": "这笔赞助已完成，感谢你的支持！"})
        return render(request, "checkout.html", {
            "gateway": settings.gateway_url + "/submit.php",
            "fields": checkout_fields(order, settings), "amount": cents,
        })

    async def confirm_notice(request):
        fields = unique_fields(request.query_params.multi_items())
        order_id = fields.get("out_trade_no", "")
        if not re.fullmatch(r"[0-9]{32}", order_id):
            raise PaymentError("赞助订单号无效")
        order = await run_in_threadpool(store.get, order_id)
        trade_no = verify_notice(fields, order, settings)
        if order["paid_at"] is None:
            await app.state.gateway.confirm(order, trade_no)
            await run_in_threadpool(store.mark_paid, order_id, trade_no)

    @app.get("/notify", response_class=PlainTextResponse)
    async def notify(request: Request):
        await confirm_notice(request)
        return PlainTextResponse("success")

    @app.get("/return", response_class=HTMLResponse)
    async def payment_return(request: Request):
        await confirm_notice(request)
        return render(request, "result.html", {
            "confirmed": True, "message": "赞助成功，感谢你支持 LCA 持续开发！",
        })

    @app.get("/healthz", response_class=PlainTextResponse)
    async def health():
        await run_in_threadpool(store.wall, 1)
        return PlainTextResponse("ok")

    return app
