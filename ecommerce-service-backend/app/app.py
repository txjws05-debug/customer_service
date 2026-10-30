from __future__ import annotations

import hmac
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app import cache, metrics
from app.api import router
from app.audit import AuditMiddleware
from app.shop_admin_api import router as shop_admin_router
from app.shop_after_sale_api import router as shop_after_sale_router
from app.shop_api import router as shop_router
from app.shop_service import ShopError
from app.config import settings
from app.security import AuthMiddleware
from app.trace import TraceMiddleware, setup_logging as setup_trace_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 生产环境不允许把鉴权关掉：off 只该存在于本地与灰度窗口。
    # 宁可启动失败（立刻可见），也不要带着「没上锁的门」跑一整天。
    if settings.app_env == "prod" and settings.auth_enforce == "off":
        raise RuntimeError(
            "生产环境(AUTH_ENFORCE=off)不允许启动：请设为 warn 或 on")
    # 商品缓存是可选能力：没配 REDIS_URL、或 Redis 连不上，都只是「没有缓存」，
    # 服务照常启动并直连 PostgreSQL —— 缓存永远不能成为可用性的单点。
    setup_trace_logging()
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
    # 生产默认关掉 /docs：接口形状不该公网可见，要看就设 EXPOSE_DOCS=true
    docs_url="/docs" if settings.expose_docs else None,
    redoc_url="/redoc" if settings.expose_docs else None,
    openapi_url="/openapi.json" if settings.expose_docs else None,
)

# 鉴权挂中间件：一次覆盖全部路由（含以后新增的），也才能在服务层拿到身份
# 先加审计、再加鉴权 → 运行时顺序是 鉴权 → 审计 → 路由，
# 审计才能拿到已解析的身份（挂反了就全是 anonymous）
app.add_middleware(AuditMiddleware)
app.add_middleware(AuthMiddleware)
# 后添加的在外层：trace 要包住鉴权，401/403 的日志也得有 id
app.add_middleware(TraceMiddleware)

app.include_router(router)


@app.get("/metrics", include_in_schema=False)
def metrics_endpoint(request: Request):
    """Prometheus 抓取端点。

    只在内网暴露（Caddy 不转发 /metrics，公网 404），另可用 METRICS_TOKEN
    做 Bearer 校验 —— 指标里有路径、错误率、耗时分布，等于运行画像。
    """
    expected = settings.metrics_token
    if expected:
        got = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(got.encode(), expected.encode()):
            raise HTTPException(status_code=401, detail="metrics 需要访问令牌")
    return PlainTextResponse(metrics.render(),
                             media_type="text/plain; version=0.0.4; charset=utf-8")


@app.get("/health", tags=["系统"], summary="健康检查（匿名）")
def health() -> dict:
    """容器健康检查专用：必须匿名、且不碰数据库，避免把依赖故障放大成容器反复重启。"""
    return {"status": "ok"}
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
