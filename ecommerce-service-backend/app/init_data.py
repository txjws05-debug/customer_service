"""建表 + 演示数据初始化。

设计要点：
- 用 Base.metadata.create_all 建表，MySQL / SQLite 通用，不依赖外部 SQL 脚本。
- 仅在 users 表为空时写入演示数据，重复启动不会污染已有数据。
- 覆盖 README 列出的全部订单状态，便于客服流程演示与面试展示。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app import models
from app.database import engine

logger = logging.getLogger("ecommerce.init")

# 演示用户：与客服 Agent 联调时使用的 user_id
DEMO_USER_ID = "u1001"


def create_tables() -> None:
    models.Base.metadata.create_all(bind=engine)
    logger.info("数据表已就绪: %s", ", ".join(inspect(engine).get_table_names()))


def seed_if_empty() -> None:
    with Session(engine) as db:
        if db.scalar(select(models.User).limit(1)) is not None:
            logger.info("已存在数据，跳过演示数据初始化")
            return
        _seed(db)
        # 显式提交：不依赖 Session 上下文退出时的隐式行为，确保数据落库
        db.commit()
    logger.info("演示数据初始化完成")


def _seed(db: Session) -> None:
    now = datetime.now()

    users = [
        models.User(
            user_id=DEMO_USER_ID,
            nickname="演示用户",
            level="黄金会员",
            mobile_masked="138****8888",
            created_at=now - timedelta(days=400),
        ),
        models.User(
            user_id="u1002",
            nickname="张三",
            level="普通会员",
            mobile_masked="139****0001",
            created_at=now - timedelta(days=200),
        ),
    ]
    db.add_all(users)
    db.flush()
    u1001, u1002 = users

    products = [
        models.Product(
            product_id="p1001",
            title="无线降噪耳机 Pro",
            description="主动降噪，续航 36 小时，支持多设备同时连接。",
            price=Decimal("899.00"),
            stock_status="有货",
            cover_url="https://picsum.photos/seed/p1001/400/400",
            attributes_json={"颜色": "曜石黑", "保修": "两年", "重量": "46g"},
            created_at=now - timedelta(days=120),
        ),
        models.Product(
            product_id="p1002",
            title="智能保温杯 500ml",
            description="316 不锈钢内胆，LED 温度显示，24 小时恒温。",
            price=Decimal("199.00"),
            stock_status="有货",
            cover_url="https://picsum.photos/seed/p1002/400/400",
            attributes_json={"容量": "500ml", "材质": "316不锈钢", "保温": "24小时"},
            created_at=now - timedelta(days=90),
        ),
        models.Product(
            product_id="p1003",
            title="机械键盘 87 键",
            description="客制化热插拔，Gasket 结构，支持三模连接。",
            price=Decimal("459.00"),
            stock_status="缺货",
            cover_url="https://picsum.photos/seed/p1003/400/400",
            attributes_json={"轴体": "静音红轴", "配列": "87键", "连接": "三模"},
            created_at=now - timedelta(days=60),
        ),
        models.Product(
            product_id="p1004",
            title="人体工学椅 标准版",
            description="四级腰托，可调头枕与扶手，静音万向轮。",
            price=Decimal("1299.00"),
            stock_status="有货",
            cover_url="https://picsum.photos/seed/p1004/400/400",
            attributes_json={"承重": "150kg", "靠背": "网布", "保修": "五年"},
            created_at=now - timedelta(days=45),
        ),
        models.Product(
            product_id="p1005",
            title="桌面显示器支架",
            description="单臂气压式，支持 17-32 英寸，承重 9kg。",
            price=Decimal("159.00"),
            stock_status="有货",
            cover_url="https://picsum.photos/seed/p1005/400/400",
            attributes_json={"适配": "17-32英寸", "承重": "9kg", "安装": "夹持/穿孔"},
            created_at=now - timedelta(days=30),
        ),
    ]
    db.add_all(products)
    db.flush()

    # (order_id, user, product, 数量, 状态, 状态说明, 几天前)
    order_specs = [
        ("O20260801001", u1001, products[0], 1, "待发货", "商家正在备货，预计 24 小时内发出", 3),
        ("O20260801002", u1001, products[1], 2, "待揽收", "包裹已打包，等待快递上门揽收", 4),
        ("O20260801003", u1001, products[3], 1, "运输中", "包裹已从北京分拨中心发出，正在运往上海", 6),
        ("O20260801004", u1001, products[4], 1, "已完成", "订单已完成，感谢您的购买", 20),
        ("O20260801005", u1001, products[2], 1, "已取消", "订单已取消，款项将原路退回", 25),
        ("O20260801006", u1002, products[1], 1, "运输中", "包裹已到达上海转运中心", 5),
        ("O20260801007", u1002, products[0], 1, "已完成", "订单已完成", 15),
    ]

    orders = []
    for order_id, user, product, qty, status, status_desc, days_ago in order_specs:
        order = models.Order(
            order_id=order_id,
            user_id=user.id,
            status=status,
            status_desc=status_desc,
            amount=(product.price * qty).quantize(Decimal("0.01")),
            created_at=now - timedelta(days=days_ago),
            receiver_name="演示收货人",
            receiver_phone_masked="138****8888",
            receiver_address="上海市普陀区中江路 888 号 1 号楼 1201 室",
        )
        db.add(order)
        db.flush()
        order.items.append(
            models.OrderItem(
                order_id=order.id,
                product_id=product.id,
                title_snapshot=product.title,
                quantity=qty,
                price=product.price,
            )
        )
        orders.append(order)

    by_id = {order.order_id: order for order in orders}

    # 物流记录：与 README 的演示状态对应
    logistics_specs = [
        ("O20260801003", "顺丰速运", "SF1234567890123", "运输中", "快件已发出，正在运往目的地",
         ["【北京】快件已从北京分拨中心发出", "【北京】快件已到达北京集散中心", "【北京】顺丰速运已收取快件"]),
        ("O20260801002", "中通快递", "ZT9876543210987", "待揽收", "等待快递员上门揽收",
         ["【上海】商家已打包，等待快递揽收"]),
        ("O20260801004", "京东物流", "JD5566778899001", "已签收", "快件已签收，感谢使用",
         ["【上海】快件已签收，签收人：本人", "【上海】快件正在派送中", "【上海】快件已到达上海配送站"]),
        ("O20260801006", "圆通速递", "YT1122334455667", "运输中", "快件已到达上海转运中心",
         ["【上海】快件已到达上海转运中心", "【杭州】快件已从杭州分拨中心发出"]),
    ]
    for order_id, company, tracking, status, status_desc, traces in logistics_specs:
        record = models.LogisticsRecord(
            order_id=by_id[order_id].id,
            logistics_company=company,
            tracking_number=tracking,
            status=status,
            status_desc=status_desc,
            updated_at=now - timedelta(hours=2),
        )
        db.add(record)
        db.flush()
        for idx, desc in enumerate(traces):
            db.add(
                models.LogisticsTrace(
                    logistics_record_id=record.id,
                    trace_time=now - timedelta(hours=idx * 8 + 2),
                    trace_desc=desc,
                )
            )

    # 预置一条退款申请：用于演示「重复申请返回 409」
    db.add(
        models.RefundRequest(
            refund_id="R20260801120000AB12CD",
            order_id=by_id["O20260801002"].id,
            operator=DEMO_USER_ID,
            reason="拍错了，不想要了",
            status="submitted",
            status_desc="退款申请已提交，正在审核中。",
            created_at=now - timedelta(days=1),
        )
    )

    # 预置一条发货提醒：用于演示重复提醒场景
    db.add(
        models.ShippingUrgeRequest(
            urge_id="U20260801180000EF34GH",
            order_id=by_id["O20260801001"].id,
            operator=DEMO_USER_ID,
            reason="希望尽快发货",
            status="submitted",
            status_desc="发货提醒已创建，商家会尽快处理。",
            created_at=now - timedelta(hours=6),
        )
    )
