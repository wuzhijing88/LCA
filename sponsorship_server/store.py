"""SQLite 订单存储；每次操作确定性关闭连接，不缓存支付状态。"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .payments import PaymentError


class OrderStore:
    def __init__(self, database: Path):
        self.database = database

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.database, timeout=0.5)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    amount_cents INTEGER NOT NULL CHECK(amount_cents BETWEEN 100 AND 500000),
                    payment_type TEXT NOT NULL CHECK(payment_type IN ('alipay', 'wxpay')),
                    nickname TEXT NOT NULL,
                    message TEXT NOT NULL,
                    is_public INTEGER NOT NULL CHECK(is_public IN (0, 1)),
                    created_at TEXT NOT NULL,
                    paid_at TEXT,
                    trade_no TEXT UNIQUE
                );
                CREATE INDEX IF NOT EXISTS orders_wall ON orders(paid_at DESC, order_id DESC);
            """)

    def create(self, order_id: str, cents: int, payment_type: str, nickname: str,
               message: str, is_public: bool) -> dict:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        expected = (cents, payment_type, nickname, message, int(is_public))
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
            if row is not None:
                if tuple(row[key] for key in ("amount_cents", "payment_type", "nickname", "message", "is_public")) != expected:
                    raise PaymentError("此表单已经提交，请刷新赞助首页后重新填写")
                return dict(row)
            connection.execute("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL)",
                               (order_id, *expected, now))
            return dict(connection.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone())

    def get(self, order_id: str) -> dict:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
            if row is None:
                raise PaymentError("赞助订单不存在")
            return dict(row)

    def mark_paid(self, order_id: str, trade_no: str):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            with self.connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute("SELECT trade_no FROM orders WHERE order_id = ?", (order_id,)).fetchone()
                if row is None:
                    raise PaymentError("赞助订单不存在")
                if row["trade_no"] is not None:
                    if row["trade_no"] != trade_no:
                        raise PaymentError("订单已经关联其它支付流水")
                    return
                connection.execute("UPDATE orders SET paid_at = ?, trade_no = ? WHERE order_id = ?",
                                   (now, trade_no, order_id))
        except sqlite3.IntegrityError as exc:
            raise PaymentError("支付流水已被其它订单使用") from exc

    def wall(self, page: int) -> tuple[list[dict], bool, int, int]:
        with self.connection() as connection:
            # 匿名订单也表达感谢；不将其真实昵称、留言从存储层传入页面。
            rows = connection.execute("""
                SELECT CASE WHEN is_public = 1 THEN nickname ELSE '匿名赞助者' END AS nickname,
                       CASE WHEN is_public = 1 THEN message ELSE '' END AS message,
                       amount_cents, substr(paid_at, 1, 10) AS date
                FROM orders WHERE paid_at IS NOT NULL
                ORDER BY paid_at DESC, order_id DESC LIMIT 25 OFFSET ?
            """, ((page - 1) * 24,)).fetchall()
            summary = connection.execute("SELECT COUNT(*), COALESCE(SUM(amount_cents), 0) FROM orders WHERE paid_at IS NOT NULL").fetchone()
            return [dict(row) for row in rows[:24]], len(rows) > 24, summary[0], summary[1]
