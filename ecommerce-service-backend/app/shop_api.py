"""交易域 API（挂载在 /shop 前缀下）。

为什么单独开一个命名空间：既有只读接口（/orders/{id}、/users/{id}/orders …）
已经上线并被客服 Agent 使用，路径不能动。新交易域统一放 /shop/*，
两边互不影响，升级也各自独立。

业务错误（ShopError）由 app.py 里注册的异常处理器统一转成
{code, message, data} 信封 + 对应 HTTP 状态码，所以这里不写 try/except。
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import shop_service as svc
from app.database import get_db
from app.schemas import ApiResponse
from app.shop_schemas import (
    AddressCreateRequest,
    CartAddRequest,
    CartUpdateRequest,
    OrderCreateRequest,
    PayRequest,
    PreviewRequest,
    CancelRequest,
)


router = APIRouter()


def _wrap(data) -> ApiResponse:
    return ApiResponse(data=data)


# ============================================================ 商品与搜索
@router.get("/categories", response_model=ApiResponse, tags=["交易-商品"],
            summary="商品类目（含在售商品数）")
def list_categories(db: Session = Depends(get_db)):
    return _wrap(svc.list_categories(db))


@router.get("/products", response_model=ApiResponse, tags=["交易-商品"],
            summary="商品搜索：关键词/类目/价格区间/排序/分页")
def search_products(
    q: str | None = Query(default=None, description="关键词，匹配标题与描述"),
    category_id: int | None = Query(default=None),
    min_price: Decimal | None = Query(default=None, ge=0),
    max_price: Decimal | None = Query(default=None, ge=0),
    sort: str = Query(default="default",
                      description="default/sales/rating/price_asc/price_desc/newest"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    return _wrap(svc.search_products(
        db, keyword=q, category_id=category_id, min_price=min_price,
        max_price=max_price, sort=sort, page=page, page_size=page_size,
    ))


@router.get("/products/{product_id}", response_model=ApiResponse, tags=["交易-商品"],
            summary="商品详情（含全部在售规格）")
def product_detail(product_id: str, db: Session = Depends(get_db)):
    return _wrap(svc.product_detail(db, product_id))


# ============================================================ 购物车
@router.get("/users/{user_id}/cart", response_model=ApiResponse, tags=["交易-购物车"],
            summary="查看购物车")
def get_cart(user_id: str, db: Session = Depends(get_db)):
    user = svc.get_user(db, user_id)
    return _wrap(svc.cart_to_data(db, user))


@router.post("/users/{user_id}/cart", response_model=ApiResponse, tags=["交易-购物车"],
             summary="加入购物车（同一规格自动累加）")
def add_to_cart(user_id: str, payload: CartAddRequest, db: Session = Depends(get_db)):
    user = svc.get_user(db, user_id)
    return _wrap(svc.add_to_cart(db, user, payload.sku_code, payload.quantity))


@router.patch("/users/{user_id}/cart/{item_id}", response_model=ApiResponse,
              tags=["交易-购物车"], summary="修改数量或勾选状态")
def update_cart_item(user_id: str, item_id: int, payload: CartUpdateRequest,
                     db: Session = Depends(get_db)):
    user = svc.get_user(db, user_id)
    return _wrap(svc.update_cart_item(db, user, item_id, payload.quantity, payload.selected))


@router.delete("/users/{user_id}/cart/{item_id}", response_model=ApiResponse,
               tags=["交易-购物车"], summary="删除购物车条目")
def remove_cart_item(user_id: str, item_id: int, db: Session = Depends(get_db)):
    user = svc.get_user(db, user_id)
    return _wrap(svc.remove_cart_item(db, user, item_id))


@router.post("/users/{user_id}/cart/preview", response_model=ApiResponse,
             tags=["交易-结算"], summary="结算预览：算钱 + 校验库存/优惠券/地址")
def preview(user_id: str, payload: PreviewRequest | None = None,
            db: Session = Depends(get_db)):
    user = svc.get_user(db, user_id)
    payload = payload or PreviewRequest()
    return _wrap(svc.preview(db, user, payload.coupon_code, payload.address_id))


# ============================================================ 地址与券
@router.get("/users/{user_id}/addresses", response_model=ApiResponse,
            tags=["交易-地址"], summary="收货地址列表")
def list_addresses(user_id: str, db: Session = Depends(get_db)):
    user = svc.get_user(db, user_id)
    return _wrap(svc.list_addresses(db, user))


@router.post("/users/{user_id}/addresses", response_model=ApiResponse,
             tags=["交易-地址"], summary="新增收货地址")
def create_address(user_id: str, payload: AddressCreateRequest,
                   db: Session = Depends(get_db)):
    user = svc.get_user(db, user_id)
    return _wrap(svc.create_address(db, user, payload))


@router.get("/users/{user_id}/coupons", response_model=ApiResponse,
            tags=["交易-营销"], summary="我的优惠券（可按商品金额筛出可用的）")
def list_coupons(
    user_id: str,
    goods_amount: Decimal | None = Query(
        default=None, ge=0, description="带上商品金额则只返回当前可用的券"),
    db: Session = Depends(get_db),
):
    user = svc.get_user(db, user_id)
    return _wrap(svc.list_user_coupons(db, user, goods_amount))


@router.get("/users/{user_id}/points", response_model=ApiResponse,
            tags=["交易-营销"], summary="我的积分（余额 + 流水）")
def get_points(user_id: str, db: Session = Depends(get_db)):
    user = svc.get_user(db, user_id)
    return _wrap(svc.points_summary(db, user))


# ============================================================ 订单
@router.post("/orders", response_model=ApiResponse, tags=["交易-订单"],
             summary="下单（items 为立即购买；不传则结算购物车勾选项）")
def create_order(payload: OrderCreateRequest, db: Session = Depends(get_db)):
    user = svc.get_user(db, payload.user_id)
    return _wrap(svc.create_order(
        db, user, address_id=payload.address_id,
        coupon_code=payload.coupon_code, items=payload.items,
    ))


@router.get("/users/{user_id}/orders", response_model=ApiResponse,
            tags=["交易-订单"], summary="我的订单（可按状态筛选）")
def list_orders(
    user_id: str,
    status: str | None = Query(default=None, description="如 待付款/待发货/运输中/待收货/已完成/已取消"),
    db: Session = Depends(get_db),
):
    user = svc.get_user(db, user_id)
    return _wrap(svc.list_orders(db, user, status))


@router.get("/orders/{order_id}", response_model=ApiResponse, tags=["交易-订单"],
            summary="订单详情（金额明细 + 状态流转记录 + 可否操作）")
def order_detail(order_id: str, db: Session = Depends(get_db)):
    return _wrap(svc.order_detail(db, order_id))


@router.post("/orders/{order_id}/pay", response_model=ApiResponse, tags=["交易-订单"],
             summary="支付订单（mock 渠道）")
def pay_order(order_id: str, payload: PayRequest | None = None,
              db: Session = Depends(get_db)):
    payload = payload or PayRequest()
    return _wrap(svc.pay_order(db, order_id, payload.channel))


@router.post("/orders/{order_id}/cancel", response_model=ApiResponse,
             tags=["交易-订单"], summary="取消订单（归还库存与优惠券）")
def cancel_order(order_id: str, payload: CancelRequest | None = None,
                 db: Session = Depends(get_db)):
    payload = payload or CancelRequest()
    return _wrap(svc.cancel_order(db, order_id, payload.reason))


@router.post("/orders/{order_id}/receive", response_model=ApiResponse,
             tags=["交易-订单"], summary="确认收货（订单完成并发放积分）")
def receive_order(order_id: str, db: Session = Depends(get_db)):
    return _wrap(svc.receive_order(db, order_id))
