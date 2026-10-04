from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app import cache
from app.api import router
from app.shop_admin_api import router as shop_admin_router
from app.shop_after_sale_api import router as shop_after_sale_router
from app.shop_api import router as shop_router
from app.shop_service import ShopError


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 商品缓存是可选能力：没配 REDIS_URL、或 Redis 连不上，都只是「没有缓存」，
    # 服务照常启动并直连 PostgreSQL —— 缓存永远不能成为可用性的单点。
    cache.configure_from_settings()
    yield


openapi_tags = [
    {
        "name": "系统",
        "description": "服务可用性与基础检查接口。",
    },
    {
        "name": "用户",
        "description": "查询用户相关的订单列表和商品列表。",
    },
    {
        "name": "订单",
        "description": "订单详情、订单状态、物流信息，以及订单相关操作请求。",
    },
    {
        "name": "商品",
        "description": "商品详情查询接口。",
    },
    {
        "name": "交易-商品",
        "description": "交易域商品接口：类目、搜索、规格（/shop 前缀）。",
    },
    {
        "name": "交易-购物车",
        "description": "购物车增删改查。",
    },
    {
        "name": "交易-结算",
        "description": "结算预览：算钱、校验库存与优惠券。",
    },
    {
        "name": "交易-地址",
        "description": "收货地址簿。",
    },
    {
        "name": "交易-营销",
        "description": "优惠券与积分。",
    },
    {
        "name": "交易-订单",
        "description": "下单、支付、取消、确认收货与订单查询（含状态机）。",
    },
    {
        "name": "交易-售后",
        "description": "售后工单：仅退款/退货退款的状态机流程。",
    },
    {
        "name": "交易-评价",
        "description": "订单评价、追评与商品评价聚合。",
    },
    {
        "name": "运营-订单",
        "description": "商家后台：全站订单查询、发货与履约推进。",
    },
    {
        "name": "运营-售后",
        "description": "商家后台：售后审核台与评价回复。",
    },
    {
        "name": "运营-库存",
        "description": "商家后台：库存调整与低库存预警。",
    },
    {
        "name": "运营-营销",
        "description": "商家后台：优惠券模板与定向发券。",
    },
    {
        "name": "运营-看板",
        "description": "商家后台：GMV、订单分布、售后率、热销榜等经营指标。",
    },
]


app = FastAPI(
    title="Atguigu 电商业务服务",
    version="0.2.0",
    description=(
        "为 atguigu 客服项目提供订单、物流、商品与订单操作能力的示例电商服务。\n\n"
        "- 根路径：既有只读接口（客服 Agent 在用，保持兼容）\n"
        "- `/shop/*`：交易域接口（购物车、下单、支付、收货、优惠券、积分）\n\n"
        "PostgreSQL 是唯一事实来源；可选的 Redis 只用于加速商品读路径。"
    ),
    openapi_tags=openapi_tags,
    lifespan=lifespan,
)

app.include_router(router)
# 交易域独立命名空间：既有只读接口的路径与响应结构一概不动
app.include_router(shop_router, prefix="/shop")
app.include_router(shop_after_sale_router, prefix="/shop")
# 运营管理端：商家后台视角（订单履约、售后审核台、库存、发券、看板）
app.include_router(shop_admin_router, prefix="/shop/admin")


@app.exception_handler(ShopError)
async def shop_error_handler(request: Request, exc: ShopError) -> JSONResponse:
    """业务校验失败统一转成 {code, message, data} 信封。

    这样路由层不用写 try/except，错误格式也与既有 ApiResponse 一致，
    前端/Agent 只需处理一种错误结构。
    """
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.status_code, "message": exc.message, "data": None},
    )
