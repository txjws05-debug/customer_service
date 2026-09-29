import importlib
import inspect
import pkgutil
from ws.task.action.base import Action
from ws.task.action.registry import ActionRegistry
from ws.task.custom.logistics_tracking import LookupTracking
from ws.task.custom.lookup_order_status import LookupOrderStatus
from ws.task.custom.similar_products import RecommendSimilarProducts

def register_service_action(registry: ActionRegistry):
    registry.register_action(LookupTracking())
    registry.register_action(LookupOrderStatus())
    registry.register_action(RecommendSimilarProducts())

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
