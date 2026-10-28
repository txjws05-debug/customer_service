"""对象级授权：谁能看/动哪一条数据。

放在服务层而不是路由层，是因为所有用户态接口都会经过 `get_user()` 和
`_get_order()` —— 两处一卡，存量接口与以后新增的接口都自动覆盖，不会漏。

规则：
- 服务令牌、运营令牌：跨用户放行（Agent 要把用户自己的数据取回来）；
- 用户 JWT：只能碰 `cuid` 等于自己的数据；
- 匿名：只在 AUTH_ENFORCE 非 on 时出现，放行以保持改造前行为（灰度期）。
"""

from __future__ import annotations

import logging

from app.security import current_context

logger = logging.getLogger(__name__)


def _shop_error(message: str, status_code: int):
    # 延迟导入避免与 shop_service 形成循环依赖
    from app.shop_service import ShopError

    return ShopError(message, status_code)


def ensure_user_scope(user_id: str) -> None:
    """校验当前身份能不能操作这个商城账号的数据。"""
    ctx = current_context()
    if ctx.is_privileged or ctx.kind == "anonymous":
        return
    if not ctx.cuid:
        # 旧 token 没有 cuid：宁可拒绝，也不能回落成某个默认账号 —— 那等于
        # 让所有人都变成同一个商城用户，越权反而比改造前更严重。
        raise _shop_error("登录凭证缺少商城账号，请重新登录。", 403)
    if ctx.cuid != user_id:
        logger.warning("越权拦截 user=%s cuid=%s target=%s", ctx.subject, ctx.cuid, user_id)
        raise _shop_error("无权访问其他用户的数据。", 403)


def ensure_order_scope(order) -> None:
    """校验当前身份能不能操作这笔订单。

    别人的订单一律返回 404 而不是 403 —— 403 等于告诉对方「这个订单号存在」，
    会变成订单号枚举通道。
    """
    ctx = current_context()
    if ctx.is_privileged or ctx.kind == "anonymous":
        return
    owner = getattr(getattr(order, "user", None), "user_id", None)
    if not ctx.cuid:
        raise _shop_error("登录凭证缺少商城账号，请重新登录。", 403)
    if owner != ctx.cuid:
        logger.warning("越权拦截 user=%s cuid=%s order=%s owner=%s",
                       ctx.subject, ctx.cuid,
                       getattr(order, "order_id", "?"), owner)
        raise _shop_error("订单不存在。", 404)
