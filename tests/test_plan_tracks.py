# -*- coding: utf-8 -*-
"""一句话里出现多个「轨道」时的处理。

背景（2026-11-02 评测 T07）：「还没发货，能改收货地址吗」被计划模型拆成
task（改地址）+ knowledge（发货时效）两个轨道，校验直接反问
「请一次只办理一件事，您希望先处理哪一个？」—— 用户会觉得系统没听懂，
因为他只提了一件事，「还没发货」是前提。

现在改为按「办理 > 咨询 > 闲聊」取一个，不把用户挡在门外。
"""

from ws.domain.state import DialogueState, TaskInstance
from ws.plan.models import (
    KnowledgeTurnPlan,
    TaskTurnPlan,
    TurnPlan,
)
from ws.plan.turn_plan_validation import TurnPlanValidation
from ws.task.command.models import CancelTaskCommand, StartFlowCommand


class _Catalog:
    # 校验会查 flow 是否存在于目录里，所以测试目录要真的有这个流程
    flows: dict = {"address_change": object()}


def _validate(plan: TurnPlan, state: DialogueState | None = None):
    return TurnPlanValidation().validate(
        turn_plan=plan, state=state or DialogueState(sender_id="u1"),
        flow_catalog=_Catalog())


def test_task_and_knowledge_prefers_task():
    """条件从句 + 一个请求：按办理处理，不再反问「先办哪个」。"""
    plan = TurnPlan(
        task=TaskTurnPlan(commands=[StartFlowCommand(command="start_flow", flow="address_change")]),
        knowledge=KnowledgeTurnPlan(intents=["shipping_time"]))
    result = _validate(plan)
    assert result.valid is True


def test_task_without_commands_falls_back_to_knowledge():
    """task 轨道是空的（模型只给了壳），就退到知识咨询，而不是判「缺指令」。"""
    plan = TurnPlan(
        task=TaskTurnPlan(commands=[]),
        knowledge=KnowledgeTurnPlan(intents=["shipping_time"]))
    result = _validate(plan)
    assert result.valid is True


def test_cancel_with_unknown_task_id_passes_validation():
    """取消一个对不上的任务是正常对话，不该判成「非法指令」。

    「我要买这个」→「算了不买了」时订单已经建好、任务已结束，
    模型给回的 task_id 自然匹配不上任何 active/paused。
    原来会反问「抱歉，这个操作我暂时无法完成」，用户一脸问号。
    """
    plan = TurnPlan(task=TaskTurnPlan(commands=[
        CancelTaskCommand(command="cancel_task", task_id="no-such-task")]))
    result = _validate(plan)
    assert result.valid is True


def test_cancel_active_task_still_works():
    """正常取消仍然要能走通（放宽不能把正路也堵了）。"""
    state = DialogueState(sender_id="u1")
    state.tasks.active = TaskInstance(flow_id="place_order", step_id="start")
    plan = TurnPlan(task=TaskTurnPlan(commands=[
        CancelTaskCommand(command="cancel_task", task_id=state.tasks.active.task_id)]))
    assert _validate(plan, state).valid is True


def test_unknown_flow_still_rejected():
    """放宽的是取消，不是流程校验：不存在的 flow 仍然要拦。"""
    plan = TurnPlan(task=TaskTurnPlan(commands=[
        StartFlowCommand(command="start_flow", flow="no_such_flow")]))
    result = _validate(plan)
    assert result.valid is False
