"""运营管理端 API（/shop/admin/*）。

客服 Agent 与用户端用的是 /shop/*；这里是商家后台视角：订单管理与履约、
售后审核台、库存调整、优惠券发放、经营看板。共用同一套状态机与业务规则，
因此后台推进的状态就是用户端看到的状态，不会出现两套口径。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import admin_service as admin
from app import after_sale_service as after_sale
from app.database import get_db
from app.schemas import ApiResponse
from app.shop_schemas import (
    AdvanceRequest,
    CouponCreateRequest,
    CouponGrantRequest,
    RemarkRequest,
    ShipRequest,
    StockUpdateRequest,
)


router = APIRouter()


def _wrap(data) -> ApiResponse:
    return ApiResponse(data=data)


# ============================================================ 订单与履约
@router.get("/orders", response_model=ApiResponse, tags=["运营-订单"],
            summary="全站订单（可按状态/用户筛选，含各状态数量）")
def list_orders(
    status: str | None = Query(default=None),
    user_id: str | None = Query(default=None, description="业务用户号，如 u1001"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return _wrap(admin.list_orders(db, status, user_id, page, page_size))


@router.post("/orders/{order_id}/ship", response_model=ApiResponse, tags=["运营-订单"],
             summary="发货：待发货 → 待揽收（建立物流单）")
def ship_order(order_id: str, payload: ShipRequest | None = None,
               db: Session = Depends(get_db)):
    payload = payload or ShipRequest()
    return _wrap(admin.ship_order(db, order_id, payload.company, payload.tracking_number))


@router.post("/orders/{order_id}/advance", response_model=ApiResponse, tags=["运营-订单"],
             summary="推进履约：待揽收 → 运输中 → 待收货（附物流轨迹）")
def advance_order(order_id: str, payload: AdvanceRequest | None = None,
                  db: Session = Depends(get_db)):
    payload = payload or AdvanceRequest()
    return _wrap(admin.advance_order(db, order_id, payload.remark))


# ============================================================ 售后审核台
@router.get("/after-sales", response_model=ApiResponse, tags=["运营-售后"],
            summary="售后工单列表（审核台）")
def list_after_sales(
    status: str | None = Query(default=None,
                               description="submitted/approved/rejected/returning/received/completed"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return _wrap(after_sale.list_all_tickets(db, status, limit))


@router.post("/after-sales/{ticket_no}/approve", response_model=ApiResponse,
             tags=["运营-售后"], summary="审核通过")
def approve_after_sale(ticket_no: str, payload: RemarkRequest | None = None,
                       db: Session = Depends(get_db)):
    payload = payload or RemarkRequest()
    return _wrap(after_sale.review_ticket(db, ticket_no, True, payload.remark))


@router.post("/after-sales/{ticket_no}/reject", response_model=ApiResponse,
             tags=["运营-售后"], summary="审核驳回")
def reject_after_sale(ticket_no: str, payload: RemarkRequest | None = None,
                      db: Session = Depends(get_db)):
    payload = payload or RemarkRequest(remark="不符合售后条件")
    return _wrap(after_sale.review_ticket(db, ticket_no, False, payload.remark))


@router.post("/after-sales/{ticket_no}/receive", response_model=ApiResponse,
             tags=["运营-售后"], summary="确认收到退货（returning → received）")
def receive_after_sale(ticket_no: str, payload: RemarkRequest | None = None,
                       db: Session = Depends(get_db)):
    payload = payload or RemarkRequest()
    return _wrap(after_sale.receive_return(db, ticket_no, payload.remark))


@router.post("/after-sales/{ticket_no}/complete", response_model=ApiResponse,
             tags=["运营-售后"], summary="完成售后（退款；退货退款会回滚库存）")
def complete_after_sale(ticket_no: str, payload: RemarkRequest | None = None,
                        db: Session = Depends(get_db)):
    payload = payload or RemarkRequest()
    return _wrap(after_sale.complete_after_sale(db, ticket_no, payload.remark))


@router.post("/reviews/{review_id}/reply", response_model=ApiResponse,
             tags=["运营-售后"], summary="商家回复评价")
def reply_review(review_id: int, payload: RemarkRequest | None = None,
                 db: Session = Depends(get_db)):
    payload = payload or RemarkRequest()
    return _wrap(after_sale.reply_review(db, review_id, payload.remark or "感谢您的反馈！"))


# ============================================================ 库存
@router.patch("/skus/{sku_code}/stock", response_model=ApiResponse, tags=["运营-库存"],
              summary="调整库存（绝对值，写库存流水）")
def update_stock(sku_code: str, payload: StockUpdateRequest,
                 db: Session = Depends(get_db)):
    return _wrap(admin.update_stock(db, sku_code, payload))


@router.get("/low-stock", response_model=ApiResponse, tags=["运营-库存"],
            summary="低库存预警")
def low_stock(threshold: int = Query(default=10, ge=0),
              db: Session = Depends(get_db)):
    return _wrap(admin.low_stock(db, threshold))


# ============================================================ 优惠券
@router.get("/coupons", response_model=ApiResponse, tags=["运营-营销"],
            summary="优惠券模板列表（含领取/核销数）")
def list_coupons(db: Session = Depends(get_db)):
    return _wrap(admin.list_coupons(db))


@router.post("/coupons", response_model=ApiResponse, tags=["运营-营销"],
             summary="新建优惠券模板")
def create_coupon(payload: CouponCreateRequest, db: Session = Depends(get_db)):
    return _wrap(admin.create_coupon(db, payload))


@router.post("/coupons/{code}/grant", response_model=ApiResponse, tags=["运营-营销"],
             summary="定向发券（超限领的用户会被跳过）")
def grant_coupon(code: str, payload: CouponGrantRequest,
                 db: Session = Depends(get_db)):
    return _wrap(admin.grant_coupon(db, code, payload.user_ids))


# ============================================================ 看板
@router.get("/stats", response_model=ApiResponse, tags=["运营-看板"],
            summary="经营看板：GMV/订单分布/售后率/券核销/积分/热销榜/低库存")
def stats(db: Session = Depends(get_db)):
    return _wrap(admin.stats(db))
