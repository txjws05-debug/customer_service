from ws.task.action.registry import ActionRegistory
from ws.task.custom.logistics_tracking import LookupTracking
from ws.task.custom.lookup_order_status import LookupOrderStatus


def register_service_action(registory:ActionRegistory):
    registory.register_action(LookupTracking())
    registory.register_action(LookupOrderStatus())
