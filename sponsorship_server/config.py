"""赞助服务启动配置；缺少商户或部署参数时直接失败。"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


def require_origin(value: str, label: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError(f"{label} 必须是独立域名的 HTTPS 地址，不能包含路径、账号或查询参数")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError(f"{label} 端口无效") from exc
    return value.rstrip("/")


@dataclass(frozen=True)
class Settings:
    public_url: str
    gateway_url: str
    pid: str
    key: str = field(repr=False)
    csrf_secret: str = field(repr=False)
    database: Path
    payment_types: tuple[str, ...] = ("alipay", "wxpay")

    def __post_init__(self):
        object.__setattr__(self, "public_url", require_origin(self.public_url, "赞助网页地址"))
        object.__setattr__(self, "gateway_url", require_origin(self.gateway_url, "ZPAY 网关地址"))
        if not self.pid.isascii() or not self.pid.isdecimal():
            raise ValueError("ZPAY 商户 ID 必须是数字")
        if not self.key or self.key != self.key.strip():
            raise ValueError("ZPAY 商户密钥为空或包含首尾空白")
        if len(self.csrf_secret) < 32:
            raise ValueError("表单密钥至少需要 32 个字符")
        if not self.database.is_absolute():
            raise ValueError("赞助数据库必须使用绝对路径")
        if (not self.payment_types or len(set(self.payment_types)) != len(self.payment_types)
                or any(item not in ("alipay", "wxpay") for item in self.payment_types)):
            raise ValueError("支付方式只允许 alipay、wxpay，且不能重复")


def load_settings() -> Settings:
    def required(name):
        value = os.environ.get(name)
        if not value:
            raise ValueError(f"赞助服务缺少环境配置：{name}")
        return value

    return Settings(
        public_url=required("SPONSOR_PUBLIC_URL"),
        gateway_url=required("ZPAY_GATEWAY_URL"),
        pid=required("ZPAY_PID"),
        key=required("ZPAY_KEY"),
        csrf_secret=required("SPONSOR_CSRF_SECRET"),
        database=Path(required("SPONSOR_DATABASE")),
        payment_types=tuple(required("ZPAY_PAYMENT_TYPES").split(",")),
    )
