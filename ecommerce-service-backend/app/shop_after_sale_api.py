"""售后工单与评价的 API（同样挂在 /shop 前缀下）。

与 shop_api.py 分开是因为这块业务自成一体（售后状态机 + 评价），
拆开后单文件更短，也方便后续把运营端动作放进 admin_api.py 复用同一份服务。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import after_sale_service as svc
from app.database import get_db
from app.schemas import ApiResponse
from app.shop_schemas import (
    AfterSaleCreateRequest,
    AfterSaleReturnRequest,
    ReviewAppendRequest,
    ReviewCreateRequest,
)
from app.shop_service import get_user


router = APIRouter()


def _wrap(data) -> ApiResponse:
    return ApiResponse(data=data)


# ============================================================ 售后
@router.post("/orders/{order_id}/after-sales", response_model=ApiResponse,
             tags=["交易-售后"], summary="申请售后（仅退款 / 退货退款）")
def create_after_sale(order_id: str, payload: AfterSaleCreateRequest,
                      db: Session = Depends(get_db)):
    user = get_user(db, payload.user_id)
    return _wrap(svc.create_after_sale(db, user, order_id, payload))


@router.get("/users/{user_id}/after-sales", response_model=ApiResponse,
            tags=["交易-售后"], summary="我的售后单（可按状态筛选）")
def list_after_sales(user_id: str, status: str | None = Query(default=None),
                     db: Session = Depends(get_db)):
    user = get_user(db, user_id)
    return _wrap(svc.list_after_sales(db, user, status))


@router.get("/after-sales/{ticket_no}", response_model=ApiResponse,
            tags=["交易-售后"], summary="售后单详情")
def after_sale_detail(ticket_no: str, db: Session = Depends(get_db)):
    return _wrap(svc.after_sale_detail(db, ticket_no))


@router.post("/after-sales/{ticket_no}/cancel", response_model=ApiResponse,
             tags=["交易-售后"], summary="撤销售后申请")
def cancel_after_sale(ticket_no: str, db: Session = Depends(get_db)):
    return _wrap(svc.cancel_after_sale(db, ticket_no))


@router.post("/after-sales/{ticket_no}/return", response_model=ApiResponse,
             tags=["交易-售后"], summary="提交退货寄回信息（退货退款）")
def submit_return(ticket_no: str, payload: AfterSaleReturnRequest,
                  db: Session = Depends(get_db)):
    return _wrap(svc.submit_return(db, ticket_no, payload.tracking_number, payload.company))


# ============================================================ 评价
@router.post("/orders/{order_id}/reviews", response_model=ApiResponse,
             tags=["交易-评价"], summary="评价订单中的商品（支持一次评多个）")
def create_reviews(order_id: str, payload: ReviewCreateRequest,
                   db: Session = Depends(get_db)):
    user = get_user(db, payload.user_id)
    return _wrap(svc.create_reviews(db, user, order_id, payload))


@router.get("/products/{product_id}/reviews", response_model=ApiResponse,
            tags=["交易-评价"], summary="商品评价列表（含评分聚合）")
def list_product_reviews(
    product_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    return _wrap(svc.list_product_reviews(db, product_id, page, page_size))


@router.post("/users/{user_id}/reviews/{review_id}/append", response_model=ApiResponse,
             tags=["交易-评价"], summary="追加评价")
def append_review(user_id: str, review_id: int, payload: ReviewAppendRequest,
                  db: Session = Depends(get_db)):
    user = get_user(db, user_id)
    return _wrap(svc.append_review(db, user, review_id, payload.content))


@router.get("/users/{user_id}/pending-reviews", response_model=ApiResponse,
            tags=["交易-评价"], summary="待评价的已完成订单")
def pending_reviews(user_id: str, db: Session = Depends(get_db)):
    user = get_user(db, user_id)
    return _wrap({"user_id": user.user_id, "order_ids": svc.un_reviewed_orders(db, user)})
