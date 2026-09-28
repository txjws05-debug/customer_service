from pathlib import Path




from ws.chitchat.handler import ChitchatHandler
from ws.clarify.handler import ClarifyResponder
from ws.knowledge.handle import KnowledgeHandler
from ws.knowledge.intents import KNOWLEDGE_INTENTS
from ws.knowledge.provider import ApiProductProvider, ApiOrderProvider, FAQProvider, RAGProvider
from ws.knowledge.registry import KnowledgeProviderRegistry
from ws.knowledge.responder import KnowledgeResponder
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
from ws.task.response.render import ResponseRender

def build_dailogue_engine()->DialogueEngine:
    #获取yaml文件所有数据，FlowCatalog
    flow_path=Path(__file__).parents[1]/'config'/'user_flows.yml'
    flow_catalog:FlowCatalog=FlowLoader().load(flow_path)

    turn_planner = TurnPlanner()
    turn_plan_validation = TurnPlanValidation()

    command_processor=CommandProcessor()
    task_lifecycle=TaskLifecycleResponder(flows=flow_catalog)

    response_renderer=ResponseRender()
    registry=ActionRegistry()
    #业务对应action，注册字典里面

    register_service_action(registry)
    action_runner=ActionRunner(registry=registry)
    flow_executor=FlowExecutor(
        response_renderer=response_renderer,
        action_runner=action_runner
    )
    task_handler=TaskHandler(
        command_processor=command_processor,
        task_lifecycle=task_lifecycle,
        flow_executor=flow_executor,
        flow_catalog=flow_catalog)
    provider_registry=KnowledgeProviderRegistry([
        ApiProductProvider(),
        ApiOrderProvider(),
        FAQProvider(),
        RAGProvider()
    ])
    knowledge_responder = KnowledgeResponder()
    knowledge_handler =KnowledgeHandler(
        knowledge_intents=KNOWLEDGE_INTENTS,
        provider_registry=provider_registry,
        knowledge_responder=knowledge_responder
    )

    clarify_responder=ClarifyResponder()
    chitchat_handler=ChitchatHandler()
    return DialogueEngine(
        turn_plan=turn_planner,
        turn_plan_validation=turn_plan_validation,
        task_handler=task_handler,

        #新增三个对象
        knowledge_handler = knowledge_handler,
        chitchat_handler= chitchat_handler,
        clarify_responder = clarify_responder
    )