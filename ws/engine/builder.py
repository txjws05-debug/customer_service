from pathlib import Path

from ws.engine.dialogue_engine import DialogueEngine
from ws.plan import turn_plan_validation
from ws.plan.turn_plan import TurnPlanner
from ws.plan.turn_plan_validation import TurnPlanValidation
from ws.task.action.builder import register_service_action
from ws.task.action.registry import ActionRegistry
from ws.task.action.runner import ActionRunner
from ws.task.command.processor import CommandProcessor
from ws.task.flow.executor import FlowExecutor
from ws.task.flow.loader import FlowLoader
from ws.task.flow.models import FlowCatalog
from ws.task.handler import TaskHandler
from ws.task.lifecycle.responder import TaskLifecycleResponder
from ws.task.response.renderer import ResponseRenderer

def build_dailogue_engine()->DialogueEngine:
    #获取yaml文件所有数据，FlowCatalog
    flow_path=Path(__file__).parents[1]/'config'/'user_flows.yaml'
    flow_catalog:FlowCatalog=FlowLoader().load(flow_path)

    turn_planner = TurnPlanner()
    turn_plan_validation = TurnPlanValidation()

    command_porcessor=CommandProcessor()
    task_lifecycle=TaskLifecycleResponder(flows=flow_catalog)

    response_renderer=ResponseRenderer()
    registry=ActionRegistry()
    #业务对应action，注册字典里面

    registry_service_action(registry)
    action_runner=ActionRunner(registry=registry)
    flow_executor=FlowExecutor(
        response_renderer=response_renderer,
        action_runner=action_runner
    )
    task_handler=TaskHandler(
        command_porcessor=command_porcessor,
        task_lifecycle=task_lifecycle,
        flow_executor=flow_executor,
        flow_catalog=flow_catalog)
    return DialogueEngine(
        turn_plan=turn_planner,
        turn_plan_validation=turn_plan_validation,
        task_handler=task_handler
    )