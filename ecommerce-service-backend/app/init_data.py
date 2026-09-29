"""建表 + 课程演示数据初始化（PostgreSQL）。

设计要点：
- 用 Base.metadata.create_all 建表，PostgreSQL 下无需外部 SQL 脚本。
- 仅在 users 表为空时写入数据，重复启动不会覆盖已有数据。
- 数据与课程脚本 002_init_commerce.sql 完全一致：
  用户 u1001/u1002/u1003、6 个真实型号商品（iPhone 15 Pro 等）、8 笔订单
  覆盖 待发货/待揽收/运输中/已完成/已取消，含物流轨迹、退款申请、发货提醒。
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app import models
from app.database import engine

logger = logging.getLogger("ecommerce.init")


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
    logger.info("课程演示数据初始化完成")


def _seed(db: Session) -> None:
    # ---------------- 用户 ----------------
    users = [
        models.User(user_id="u1001", nickname="小李", level="PLUS",
                    mobile_masked="138****1234",
                    created_at=datetime(2026, 4, 1, 9, 0, 0)),
        models.User(user_id="u1002", nickname="王敏", level="普通会员",
                    mobile_masked="139****5678",
                    created_at=datetime(2026, 4, 2, 10, 30, 0)),
        models.User(user_id="u1003", nickname="陈晨", level="PLUS",
                    mobile_masked="137****2468",
                    created_at=datetime(2026, 4, 3, 19, 20, 0)),
    ]
    db.add_all(users)
    db.flush()
    u1001, u1002, u1003 = users

    # ---------------- 商品 ----------------
    products = [
        models.Product(
            product_id="SKU10001",
            title="iPhone 15 Pro 256G 远峰蓝",
            description="6.1 英寸超视网膜 XDR 显示屏，A17 Pro 芯片，支持 5 倍光学变焦。",
            price=Decimal("8999.00"), stock_status="有货",
            cover_url="https://example.com/images/iphone15pro.jpg",
            attributes_json={"颜色": "远峰蓝", "容量": "256GB",
                             "屏幕尺寸": "6.1英寸", "网络": "5G"},
            created_at=datetime(2026, 3, 20, 12, 0, 0),
        ),
        models.Product(
            product_id="SKU10002",
            title="小米恒温电热水壶 3",
            description="1.7L 容量，恒温保温，多档温度调节。",
            price=Decimal("149.00"), stock_status="有货",
            cover_url="https://example.com/images/kettle3.jpg",
            attributes_json={"容量": "1.7L", "功率": "1800W", "材质": "304不锈钢"},
            created_at=datetime(2026, 3, 22, 14, 0, 0),
        ),
        models.Product(
            product_id="SKU10003",
            title="暖火暖宝宝贴 20片装",
            description="发热稳定，贴身保暖，适合秋冬日常使用。",
            price=Decimal("14.90"), stock_status="有货",
            cover_url="https://example.com/images/warm.jpg",
            attributes_json={"规格": "20片装", "持续时长": "约10小时",
                             "适用部位": "腹部/腰部/背部"},
            created_at=datetime(2026, 3, 25, 8, 30, 0),
        ),
        models.Product(
            product_id="SKU10004",
            title="Apple Watch Series 9 GPS 45mm",
            description="支持全天候视网膜显示屏，健康监测与运动记录。",
            price=Decimal("2999.00"), stock_status="有货",
            cover_url="https://example.com/images/watch-s9.jpg",
            attributes_json={"颜色": "午夜色", "表壳尺寸": "45mm", "连接方式": "GPS版"},
            created_at=datetime(2026, 3, 27, 11, 10, 0),
        ),
        models.Product(
            product_id="SKU10005",
            title="美的空气炸锅 5L",
            description="大容量可视窗设计，支持多菜单模式。",
            price=Decimal("399.00"), stock_status="有货",
            cover_url="https://example.com/images/airfryer.jpg",
            attributes_json={"容量": "5L", "功率": "1500W", "颜色": "奶白色"},
            created_at=datetime(2026, 3, 29, 16, 20, 0),
        ),
        models.Product(
            product_id="SKU10006",
            title="罗技 MX Master 3S 鼠标",
            description="静音微动，支持多设备切换，适合办公与设计。",
            price=Decimal("699.00"), stock_status="有货",
            cover_url="https://example.com/images/mx-master-3s.jpg",
            attributes_json={"颜色": "石墨灰", "连接方式": "蓝牙/USB接收器",
                             "适用系统": "Windows/macOS"},
            created_at=datetime(2026, 3, 30, 13, 40, 0),
        ),
    ]
    db.add_all(products)
    db.flush()
    by_sku = {p.product_id: p for p in products}

    # ---------------- 订单 ----------------
    # (order_id, 用户, SKU, 状态, 状态说明, 金额, 创建时间, 收货人, 手机, 地址)
    order_specs = [
        ("A20260410001", u1001, "SKU10001", "待发货",
         "商家正在备货，预计 24 小时内发出。", "8999.00",
         datetime(2026, 4, 10, 10, 0, 0), "李先生", "138****1234",
         "上海市浦东新区世纪大道 100 号"),
        ("A20260408002", u1001, "SKU10002", "运输中",
         "包裹已发出，正在配送途中。", "149.00",
         datetime(2026, 4, 8, 15, 30, 0), "李先生", "138****1234",
         "上海市浦东新区世纪大道 100 号"),
        ("A20260405003", u1001, "SKU10003", "已完成",
         "订单已签收完成。", "14.90",
         datetime(2026, 4, 5, 11, 20, 0), "李先生", "138****1234",
         "上海市浦东新区世纪大道 100 号"),
        ("A20260407004", u1001, "SKU10004", "待揽收",
         "商家已打包完成，正在等待物流揽收。", "2999.00",
         datetime(2026, 4, 7, 18, 15, 0), "李先生", "138****1234",
         "上海市浦东新区世纪大道 100 号"),
        ("A20260402005", u1001, "SKU10005", "已取消",
         "订单已取消，款项将在 1-3 个工作日内原路退回。", "399.00",
         datetime(2026, 4, 2, 9, 45, 0), "李先生", "138****1234",
         "上海市浦东新区世纪大道 100 号"),
        ("B20260409001", u1002, "SKU10006", "运输中",
         "包裹正在运输途中，请耐心等待。", "699.00",
         datetime(2026, 4, 9, 20, 30, 0), "王女士", "139****5678",
         "杭州市西湖区文三路 88 号"),
        ("B20260401002", u1002, "SKU10002", "已完成",
         "订单已签收完成。", "149.00",
         datetime(2026, 4, 1, 14, 5, 0), "王女士", "139****5678",
         "杭州市西湖区文三路 88 号"),
        ("C20260406001", u1003, "SKU10005", "待发货",
         "商品正在备货，预计明日发出。", "399.00",
         datetime(2026, 4, 6, 12, 25, 0), "陈先生", "137****2468",
         "北京市朝阳区建国路 56 号"),
    ]

    orders = []
    for order_id, user, sku, status, desc, amount, created, name, phone, addr in order_specs:
        product = by_sku[sku]
        order = models.Order(
            order_id=order_id, user_id=user.id, status=status, status_desc=desc,
            amount=Decimal(amount), created_at=created,
            receiver_name=name, receiver_phone_masked=phone, receiver_address=addr,
        )
        db.add(order)
        db.flush()
        order.items.append(
            models.OrderItem(
                order_id=order.id, product_id=product.id,
                title_snapshot=product.title,
                quantity=1, price=product.price,
            )
        )
        orders.append(order)

    by_order = {o.order_id: o for o in orders}

    # ---------------- 物流记录与轨迹 ----------------
    logistics_specs = [
        ("A20260408002", "京东物流", "JD000123456789", "运输中",
         "包裹已到达上海分拨中心，正在安排派送。", datetime(2026, 4, 10, 9, 0, 0),
         [("2026-04-10 09:00:00", "包裹已到达上海分拨中心，正在安排派送。"),
          ("2026-04-09 19:30:00", "包裹已从苏州分拨中心发出。"),
          ("2026-04-09 11:20:00", "商家已出库，京东物流已揽收。")]),
        ("A20260405003", "京东物流", "JD000987654321", "已签收",
         "您的包裹已签收。", datetime(2026, 4, 6, 18, 30, 0),
         [("2026-04-06 18:30:00", "您的包裹已签收。"),
          ("2026-04-06 10:00:00", "配送员已开始派送。")]),
        ("B20260409001", "顺丰速运", "SF0005566778899", "派送中",
         "快件已到达派送站点，正在安排派送。", datetime(2026, 4, 11, 8, 40, 0),
         [("2026-04-11 08:40:00", "快件已到达派送站点，正在安排派送。"),
          ("2026-04-10 22:15:00", "快件已到达杭州转运中心。"),
          ("2026-04-10 09:20:00", "商家已发货，顺丰已揽收。")]),
    ]
    for order_id, company, tracking, status, desc, updated, traces in logistics_specs:
        record = models.LogisticsRecord(
            order_id=by_order[order_id].id, logistics_company=company,
            tracking_number=tracking, status=status, status_desc=desc,
            updated_at=updated,
        )
        db.add(record)
        db.flush()
        for ts, trace_desc in traces:
            db.add(models.LogisticsTrace(
                logistics_record_id=record.id,
                trace_time=datetime.strptime(ts, "%Y-%m-%d %H:%M:%S"),
                trace_desc=trace_desc,
            ))

    # ---------------- 退款申请 ----------------
    db.add_all([
        models.RefundRequest(
            refund_id="R202604070001", order_id=by_order["A20260405003"].id,
            operator="system", reason="收到商品后不想要了",
            status="completed", status_desc="退款已完成，款项已原路退回。",
            created_at=datetime(2026, 4, 7, 9, 30, 0),
        ),
        models.RefundRequest(
            refund_id="R202604100002", order_id=by_order["B20260401002"].id,
            operator="system", reason="商品有轻微瑕疵",
            status="processing", status_desc="退款申请正在审核中。",
            created_at=datetime(2026, 4, 10, 16, 20, 0),
        ),
    ])

    # ---------------- 发货提醒 ----------------
    db.add_all([
        models.ShippingUrgeRequest(
            urge_id="U202604100001", order_id=by_order["A20260410001"].id,
            operator="system", reason="用户希望尽快发货",
            status="submitted", status_desc="发货提醒已创建，商家会尽快处理。",
            created_at=datetime(2026, 4, 10, 18, 0, 0),
        ),
        models.ShippingUrgeRequest(
            urge_id="U202604070002", order_id=by_order["C20260406001"].id,
            operator="system", reason="用户着急使用，希望加快发货",
            status="submitted", status_desc="发货提醒已创建，商家会尽快处理。",
            created_at=datetime(2026, 4, 7, 10, 15, 0),
        ),
    ])
