import importlib
import inspect
import pkgutil
from ws.task.action.base import Action
from ws.task.action.registry import ActionRegistry
from ws.task.custom.logistics_tracking import LookupTracking
from ws.task.custom.lookup_order_status import LookupOrderStatus
from ws.task.custom.similar_products import RecommendSimilarProducts
from ws.task.custom.shop_after_sale import ApplyAfterSale
from ws.task.custom.shop_cart import AddToCart, ViewCart
from ws.task.custom.shop_checkout import PayOrder, PlaceOrder
from ws.task.custom.shop_marketing import ListMyCoupons, MyPoints
from ws.task.custom.shop_orders import ConfirmReceipt, ListMyOrders
from ws.task.custom.shop_search import SearchProducts

# 系统内置的业务能力清单。
# 交易域（购物车/下单/支付/收货/优惠券/积分/售后/搜索）在这里一次性登记，
# 新增能力只需加一行 + 在 user_flows.yml 里编排成流程。
_SERVICE_ACTIONS: list[type[Action]] = [
    # 只读查询
    LookupTracking,
    LookupOrderStatus,
    RecommendSimilarProducts,
    # 交易
    AddToCart,
    ViewCart,
    PlaceOrder,
    PayOrder,
    ListMyOrders,
    ConfirmReceipt,
    ListMyCoupons,
    MyPoints,
    ApplyAfterSale,
    SearchProducts,
]


def register_service_action(registry: ActionRegistry):
    for action_class in _SERVICE_ACTIONS:
        registry.register_action(action_class())

def register_custom_actions(
        registry: ActionRegistry,
) ->None:
    #1加载当前扫描包路径
    package= importlib.import_module(
        "ws.task.custom"
    )
    # 找到包下面所有模块，对所有模块遍历
    for _,moudle_name,is_package in pkgutil.iter_modules(package.__path__,
           prefix=f"{package.__name__}.",):
        #如果ws.task.action.custom包下面，还有包
        if is_package:
            continue
        #如果不是包
        moudle = importlib.import_module(moudle_name)
        # 获取每个模块所有成员：
        for _,action_class in inspect.getmembers(moudle,inspect.isclass):
            #类的类型必须为Action类型
            #类不能是Action基类
            if not issubclass(action_class,Action) or action_class is Action:
                continue
            # action 必须是当前模块定义，不能是其他模块import进来的
            if action_class.__module__ != moudle.__name__:
                continue
            #注册
            registry.register_action(action_class())
