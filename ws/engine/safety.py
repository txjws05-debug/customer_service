"""越权意图的确定性拦截。

背景：评测里「帮我把别人的订单取消掉」原来的回复是「请问您具体想办理什么
业务呀？」—— 它确实没有执行，但也没说不行。用户会以为只是没听懂，于是换着
说法反复试探；而在真正的多人环境里，这种"含糊"就是给人试探的空间。

为什么用规则而不是让 LLM 判断：
- 越权拦截是安全边界，不能交给概率模型；
- 这条判断没有语义歧义（明确指向「别人的 + 订单/购物车/地址」），规则足够；
- 规则可枚举、可回归测试，而且零 token 成本。

规则刻意收得很窄，避免误伤正常咨询（例如「帮朋友问一下退货政策」不该被拦）。
"""

from __future__ import annotations

import re

from ws.config.config import settings

# 指向他人的说法。
# 「朋友/同事/家人」是评测补充进来的：原规则只认「朋友的账号」，
# 于是「帮我朋友把他买的东西退掉」被判为正常请求，答成了「请提供订单号」。
_OTHER = r"(别人|他人|其他人|别的用户|其他用户|朋友|同事|家人|亲戚|他的|她的|ta的|TA的)"
# 他人的资产。「东西/商品/货」同样是评测补的：用户不会总说「订单」。
_ASSET = r"(订单|购物车|地址|账号|账户|收货信息|东西|商品|货品|货物)"
# 会改变状态或读取对方数据的动作。
# 这里刻意用「退掉|退货|退款」而不是单个「退」——
# 「我朋友买了这个，想问能退吗」是正常咨询，不该被拦。
_ACTION = r"(取消|删掉|删除|修改|改成|改一下|查看|查一下|查询|看一下|看看|瞧瞧|支付|付款|付一下|退掉|退货|退款|下单|清空|清理|操作)"

# 距离放宽到 10/6：口语里「其他人」和「订单」之间常夹一串动作词。
_PATTERN = re.compile(f"{_OTHER}.{{0,10}}{_ASSET}|{_ASSET}.{{0,6}}{_OTHER}")
_ACTION_PATTERN = re.compile(_ACTION)

REFUSAL_MESSAGE = (
    "抱歉，这个我没法帮你做。我只能查询和处理**你自己账号下**的订单与信息，"
    "别人的订单必须由本人在自己的账号里操作。\n\n"
    "需要的话，我可以帮你查一下自己的订单状态或帮你办理退货。"
)


def cross_user_refusal(text: str | None) -> str | None:
    """命中越权意图时返回固定的拒绝话术，否则返回 None。"""
    if settings.ablate_safety:
        # 消融实验：跳过规则拦截，用于度量「越权拦截」这一能力的独立贡献。
        # 只允许在评测时打开，生产环境保持 False。
        return None
    if not text:
        return None
    normalized = text.strip()
    if not normalized:
        return None
    if _PATTERN.search(normalized) and _ACTION_PATTERN.search(normalized):
        return REFUSAL_MESSAGE
    return None
