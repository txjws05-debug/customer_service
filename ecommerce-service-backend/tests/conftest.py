"""交易域集成测试的夹具。

用真实 PostgreSQL 建一个一次性测试库（不是 SQLite）—— 交易链路的库存行锁
（SELECT ... FOR UPDATE）、Numeric 金额、JSON 列都必须在真库上验证。

- 本机没有可用数据库时自动 skip，纯函数测试照常运行；
- CI 里由 job 的 services: postgres 提供，并有冒烟断言确保真的跑了。
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

import pytest

# 管理员连接：用来建/删测试库。默认指向本地临时 PG，CI 里用环境变量覆盖。
ADMIN_URL = os.getenv(
    "TEST_ADMIN_DATABASE_URL",
    "postgresql+psycopg2://cs:test@127.0.0.1:55433/postgres",
)
TEST_DB_NAME = os.getenv("TEST_DB_NAME", "commerce_shop_test")


def _url_for_database(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{name}", parts.query, parts.fragment))


TEST_URL = _url_for_database(ADMIN_URL, TEST_DB_NAME)
# 必须在导入 app.* 之前设置：app.database 在导入时就按 DATABASE_URL 建 engine
os.environ["DATABASE_URL"] = TEST_URL


@pytest.fixture(scope="session")
def prepared_database() -> str:
    """建一个干净的测试库并灌入演示数据，结束后删掉。"""
    from sqlalchemy import create_engine, text

    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT", future=True)
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    except Exception as exc:  # noqa: BLE001 - 连不上就跳过，本地也能跑纯函数测试
        admin.dispose()
        pytest.skip(f"没有可用的 PostgreSQL（{ADMIN_URL}）：{exc}")

    from app.init_data import create_tables, ensure_columns, seed_if_empty
    from app.seed_shop import seed_shop_if_empty

    create_tables()
    ensure_columns()
    seed_if_empty()
    seed_shop_if_empty()

    yield TEST_URL

    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture()
def client(prepared_database: str):
    """HTTP 客户端：验证路由、状态码与错误信封。"""
    from fastapi.testclient import TestClient

    from app.app import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def db(prepared_database: str):
    """直接查库，用来断言库存、流水这类副作用。"""
    from app.database import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def ship_order(db):
    """模拟运营端发货：待发货 → 待收货，并写一条物流记录。

    真正的发货接口属于运营端（admin_api，下一切片）。在用户侧用例里
    需要一个「已经发货」的订单，就先用它推进状态。
    """
    from app import models
    from app import shop_rules as rules

    def _ship(order_id: str) -> None:
        from sqlalchemy import select

        order = db.scalar(select(models.Order).filter(models.Order.order_id == order_id))
        assert order is not None, f"订单 {order_id} 不存在"
        order.status = rules.STATUS_PENDING_RECEIVE
        order.status_desc = rules.describe(rules.STATUS_PENDING_RECEIVE)
        order.shipped_at = rules.now()
        db.add(models.LogisticsRecord(
            order_id=order.id, logistics_company="顺丰速运",
            tracking_number=f"SF{order.id:010d}", status="派送中",
            status_desc="快件已到达派送站点。", updated_at=rules.now(),
        ))
        db.commit()

    return _ship


def data_of(response) -> dict:
    """取出 ApiResponse 信封里的 data，顺便断言请求成功。"""
    assert response.status_code == 200, f"{response.status_code}: {response.text}"
    payload = response.json()
    assert payload["code"] == 0, payload
    return payload["data"]
