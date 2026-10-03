"""交易闭环所需的演示数据 —— 幂等补种。

与 init_data._seed 的区别：那份只在 users 表为空时跑（全新库），
这份是**增量**的：线上库已经有用户/商品/订单了，这里把新域的数据补上，
并在已有表上做必要回填（商品类目/品牌、会员标记、订单实付金额、积分等）。
每个子步骤都自带「为空才写」的判断，重复启动不会产生重复数据。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.database import engine
from app import shop_rules as rules

logger = logging.getLogger("ecommerce.seed_shop")

# 商品 → (类目, 品牌)
PRODUCT_META: dict[str, tuple[str, str]] = {
    "SKU10001": ("手机数码", "Apple"),
    "SKU10004": ("智能穿戴", "Apple"),
    "SKU10002": ("厨房家电", "小米"),
    "SKU10005": ("厨房家电", "美的"),
    "SKU10003": ("日用百货", "暖火"),
    "SKU10006": ("电脑办公", "罗技"),
}

# 每个商品规格 → (规格编码后缀, 规格字典, 价格, 原价, 库存)
SKU_SPECS: dict[str, list[tuple[str, dict, str, str | None, int]]] = {
    "SKU10001": [
        ("01", {"颜色": "远峰蓝", "容量": "256GB"}, "8999.00", "9999.00", 20),
        ("02", {"颜色": "原色钛金属", "容量": "256GB"}, "8999.00", "9999.00", 8),
        ("03", {"颜色": "远峰蓝", "容量": "512GB"}, "10999.00", "11999.00", 5),
    ],
    "SKU10002": [
        ("01", {"颜色": "白色", "容量": "1.7L"}, "149.00", None, 120),
    ],
    "SKU10003": [
        ("01", {"规格": "20片装"}, "14.90", "19.90", 500),
        ("02", {"规格": "40片装"}, "26.90", "35.00", 300),
    ],
    "SKU10004": [
        ("01", {"颜色": "午夜色", "表壳": "45mm"}, "2999.00", "3199.00", 30),
        ("02", {"颜色": "银色", "表壳": "41mm"}, "2799.00", "2999.00", 12),
    ],
    "SKU10005": [
        ("01", {"颜色": "奶白色", "容量": "5L"}, "399.00", "499.00", 60),
    ],
    "SKU10006": [
        ("01", {"颜色": "石墨灰"}, "699.00", "749.00", 45),
    ],
}

ADDRESS_SPECS: dict[str, list[tuple[str, str, str, str, str, str, bool]]] = {
    "u1001": [
        ("李先生", "138****1234", "上海市", "上海市", "浦东新区", "世纪大道 100 号", True),
        ("李先生", "138****1234", "上海市", "上海市", "徐汇区", "漕溪北路 5 号 12 层", False),
    ],
    "u1002": [
        ("王女士", "139****5678", "浙江省", "杭州市", "西湖区", "文三路 88 号", True),
    ],
    "u1003": [
        ("陈先生", "137****2468", "北京市", "北京市", "朝阳区", "建国路 56 号", True),
    ],
}

COUPON_SPECS = [
    # (code, 名称, 类型, 门槛, 面额, 折扣率, 有效天数, 总量, 每人限领)
    ("C_NEW10", "新人专享 满100减10", "full_reduce", "100", "10", None, 30, 1000, 1),
    ("C_500_50", "满500减50", "full_reduce", "500", "50", None, 60, 500, 2),
    ("C_9OFF", "满199享9折", "discount", "199", None, "0.900", 30, 800, 1),
]

USER_COUPON_SPECS: dict[str, list[str]] = {
    "u1001": ["C_500_50", "C_9OFF"],
    "u1002": ["C_NEW10"],
    "u1003": ["C_NEW10", "C_9OFF"],
}

REVIEW_SPECS = [
    # (订单号, 评分, 内容, 商家回复)
    ("A20260405003", 5, "贴在腰上很暖和，一整天都是热的，回购了。", "感谢支持，注意别直接贴皮肤哦～"),
    ("B20260401002", 4, "烧水很快，保温效果不错，就是壶身稍重。", None),
]


def seed_shop_if_empty() -> None:
    """把交易域的数据补齐；已存在则跳过对应部分。"""
    with Session(engine) as db:
        _seed_categories(db)
        _seed_skus(db)
        _seed_addresses(db)
        _seed_coupons(db)
        _backfill_products(db)
        _backfill_members(db)
        _seed_reviews(db)
        _recompute_product_aggregates(db)
        _recompute_user_points(db)
        db.commit()
    logger.info("交易域演示数据检查完成")


def _empty(db: Session, model) -> bool:
    return db.scalar(select(model).limit(1)) is None


def _seed_categories(db: Session) -> None:
    if not _empty(db, models.Category):
        return
    names = ["手机数码", "智能穿戴", "厨房家电", "日用百货", "电脑办公"]
    for index, name in enumerate(names):
        db.add(models.Category(name=name, sort=index, created_at=rules.now()))
    db.flush()
    logger.info("补种类目 %d 个", len(names))


def _seed_skus(db: Session) -> None:
    if not _empty(db, models.ProductSku):
        return
    products = db.scalars(select(models.Product)).all()
    if not products:
        return
    created = 0
    for product in products:
        specs = SKU_SPECS.get(product.product_id)
        if not specs:
            continue
        for suffix, spec, price, original, stock in specs:
            db.add(models.ProductSku(
                product_id=product.id,
                sku_code=f"{product.product_id}-{suffix}",
                spec_json=spec,
                price=Decimal(price),
                original_price=Decimal(original) if original else None,
                stock=stock,
                status="在售",
                created_at=rules.now(),
            ))
            created += 1
    db.flush()
    logger.info("补种商品规格 %d 条", created)


def _seed_addresses(db: Session) -> None:
    if not _empty(db, models.Address):
        return
    users = db.scalars(select(models.User)).all()
    created = 0
    for user in users:
        for name, phone, province, city, district, detail, is_default in ADDRESS_SPECS.get(user.user_id, []):
            db.add(models.Address(
                user_id=user.id, receiver_name=name, phone_masked=phone,
                province=province, city=city, district=district, detail=detail,
                is_default=is_default, created_at=rules.now(),
            ))
            created += 1
    db.flush()
    logger.info("补种收货地址 %d 条", created)


def _seed_coupons(db: Session) -> None:
    if _empty(db, models.Coupon):
        users_by_biz = {u.user_id: u for u in db.scalars(select(models.User)).all()}
        now = rules.now()
        by_code: dict[str, models.Coupon] = {}
        for code, name, ctype, threshold, amount, rate, days, total, per_user in COUPON_SPECS:
            coupon = models.Coupon(
                code=code, name=name, type=ctype,
                threshold=Decimal(threshold),
                amount=Decimal(amount) if amount else None,
                rate=Decimal(rate) if rate else None,
                start_at=now - timedelta(days=1), end_at=now + timedelta(days=days),
                total=total, claimed=0, per_user_limit=per_user, created_at=now,
            )
            db.add(coupon)
            by_code[code] = coupon
        db.flush()
        logger.info("补种优惠券模板 %d 张", len(by_code))

    if not _empty(db, models.UserCoupon):
        return
    # 给已有用户发券（模板存在的前提下）
    coupons = {c.code: c for c in db.scalars(select(models.Coupon)).all()}
    users = {u.user_id: u for u in db.scalars(select(models.User)).all()}
    now = rules.now()
    created = 0
    for biz_id, codes in USER_COUPON_SPECS.items():
        user = users.get(biz_id)
        if not user:
            continue
        for code in codes:
            coupon = coupons.get(code)
            if not coupon:
                continue
            db.add(models.UserCoupon(
                user_id=user.id, coupon_id=coupon.id, status="unused",
                received_at=now,
            ))
            coupon.claimed = (coupon.claimed or 0) + 1
            created += 1
    db.flush()
    logger.info("补种用户券 %d 张", created)


def _backfill_products(db: Session) -> None:
    """回填类目/品牌，并用 SKU 最低价刷新展示价与库存状态。"""
    categories = {c.name: c for c in db.scalars(select(models.Category)).all()}
    products = db.scalars(select(models.Product)).all()
    touched = 0
    for product in products:
        meta = PRODUCT_META.get(product.product_id)
        if meta:
            category_name, brand = meta
            category = categories.get(category_name)
            if category and product.category_id != category.id:
                product.category_id = category.id
                touched += 1
            if brand and product.brand != brand:
                product.brand = brand
                touched += 1
        if product.status is None:
            product.status = "在售"
        skus = [s for s in product.skus if s.status == "在售"]
        if skus:
            lowest = min(s.price for s in skus)
            if product.price != lowest:
                product.price = lowest
                touched += 1
            total_stock = sum(s.stock for s in skus)
            stock_status = "有货" if total_stock > 10 else ("紧张" if total_stock > 0 else "无货")
            if product.stock_status != stock_status:
                product.stock_status = stock_status
                touched += 1
    db.flush()
    if touched:
        logger.info("回填商品类目/价格/库存状态 %d 处", touched)


def _backfill_members(db: Session) -> None:
    """同步会员标记与订单实付金额（历史订单没有 pay_amount）。"""
    users = db.scalars(select(models.User)).all()
    for user in users:
        if user.is_plus != (user.level == "PLUS"):
            user.is_plus = user.level == "PLUS"
    orders = db.scalars(select(models.Order).filter(models.Order.pay_amount.is_(None))).all()
    for order in orders:
        order.pay_amount = order.amount
        if order.discount_amount is None:
            order.discount_amount = Decimal("0")
        if order.freight_amount is None:
            order.freight_amount = Decimal("0")
    db.flush()
    if orders:
        logger.info("回填订单实付金额 %d 笔", len(orders))


def _seed_reviews(db: Session) -> None:
    if not _empty(db, models.Review):
        return
    created = 0
    for order_no, rating, content, reply in REVIEW_SPECS:
        order = db.scalar(select(models.Order).filter(models.Order.order_id == order_no))
        if not order or not order.items:
            continue
        item = order.items[0]
        db.add(models.Review(
            order_id=order.id, product_id=item.product_id, user_id=order.user_id,
            rating=rating, content=content, images_json=[], reply=reply,
            created_at=order.created_at + timedelta(days=2),
        ))
        created += 1
    db.flush()
    if created:
        logger.info("补种商品评价 %d 条", created)


def _recompute_product_aggregates(db: Session) -> None:
    """按评价重算商品评分；按非取消订单重算销量。"""
    products = db.scalars(select(models.Product)).all()
    for product in products:
        avg, count = db.execute(
            select(func.avg(models.Review.rating), func.count(models.Review.id))
            .filter(models.Review.product_id == product.id)
        ).one()
        product.rating_avg = Decimal(str(round(float(avg), 2))) if avg is not None else Decimal("0")
        product.rating_count = int(count or 0)

        sales = db.scalar(
            select(func.coalesce(func.sum(models.OrderItem.quantity), 0))
            .join(models.Order, models.Order.id == models.OrderItem.order_id)
            .filter(models.OrderItem.product_id == product.id)
            .filter(models.Order.status != rules.STATUS_CANCELED)
        )
        product.sales_count = int(sales or 0)
    db.flush()


def _recompute_user_points(db: Session) -> None:
    """让用户的积分/成长值与「已完成订单 + 积分流水」保持一致（自愈）。

    不变量：users.points == sum(points_ledger.change)。
    这样即使中途只补了列没补流水（或反过来），重跑一次就能对齐，
    不会出现「余额 0 但流水有记录」这种对不上的状态。
    """
    users = db.scalars(select(models.User)).all()
    for user in users:
        finished = db.scalars(
            select(models.Order)
            .filter(models.Order.user_id == user.id)
            .filter(models.Order.status == rules.STATUS_FINISHED)
        ).all()
        expected_points = sum(rules.calc_points(o.payable, user.is_plus) for o in finished)
        expected_growth = sum(rules.calc_growth(o.payable) for o in finished)

        ledger_total = db.scalar(
            select(func.coalesce(func.sum(models.PointsLedger.change), 0))
            .filter(models.PointsLedger.user_id == user.id)
        )
        ledger_total = int(ledger_total or 0)

        # 完全没有流水但有应得积分（例如老订单）：补一条汇总流水
        if ledger_total == 0 and expected_points > 0:
            db.add(models.PointsLedger(
                user_id=user.id, change=expected_points, balance_after=expected_points,
                reason="历史订单累计", created_at=rules.now(),
            ))
            ledger_total = expected_points

        if user.points != ledger_total:
            user.points = ledger_total
        if user.growth != expected_growth:
            user.growth = expected_growth
    db.flush()
