from ws.task.action.base import ActionResult
from ws.domain.message import UserMessage, BotMessage
from ws.domain.state import DialogueState
from ws.task.action.base import ActionCall
from ws.task.action.runner import ActionRunner
from ws.task.flow.links import FlowStepLink, ConditionalLink, FallbackLink
from ws.task.flow.models import FlowCatalog, Flow
from ws.task.flow.steps import FlowStep, StartFlowStep, ResponseFlowStep, CollectSlotStep, ActionFlowStep, \
    EndFlowStep
from ws.task.response.render import ResponseRender

class FlowExecutor:
    def __init__(self,response_renderer:ResponseRender,action_runner):
        self.response_renderer =response_renderer
        self._action_runner =action_runner


    async def run_task(self,state:DialogueState,user_message:UserMessage,flows:FlowCatalog)->list[BotMessage]:
        bot_messages: list[BotMessage]=[]
        #判断当前是否有活跃任务 没有：
        if not state.tasks.active:
            return bot_messages
        #有
        for _ in range(100):
            #推进步骤实现
            flows:Flow = flows.get_flow_by_id(state.tasks.active.flow_id)
            step:FlowStep =flows.get_step_by_id(state.tasks.active.step_id)
            #判断步骤类型
            if isinstance(step,StartFlowStep):
                 self._run_step(step,state)
                 continue
            if  isinstance(step,ResponseFlowStep):
                 bot_message: BotMessage=await self.response_renderer.render(step.template,state,user_message)
                 bot_messages.append(bot_message)
                 self._run_step(step,state)
                 continue

            if isinstance(step,CollectSlotStep):
                # need_input是bool  true:需要用户输入，没有槽位数据   false：有槽位数据
                need_input=await self._run_collect_step(step,state,user_message,bot_messages)
                if need_input:
                    return bot_messages
                else :
                    # 有槽位数据，推进下一步
                    self._run_step(step,state)
                    continue
            if isinstance(step,ActionFlowStep):
                #1从action中获取action值
                action_name=step.action
                action_kwargs=step.args
                action_call=ActionCall(action_name,action_kwargs)
                #2根据action值找到对应attion业务对象
                #4把action返回结果封装处理
                #3调用action业务对象里面的方法调用中台接口
                action_result:ActionResult=await self._action_runner.run(
                    action_call=action_call,
                    state=state
                )
                #封装处理，封装state里面slots里面
                state.tasks.active.slots.update(
                    action_result.slot_updates
                )
                # 推进下一步
                self._run_step(step,state)
                continue

            if isinstance(step, EndFlowStep):
                state.tasks.active = None
                return bot_messages

    def _run_step(self,step:FlowStep,state:DialogueState):
        #把当前步骤的next值设置当前ative里面步骤id
        #next_step_id=step.next
        #step.next有两种情况 字符串 列表 if then else
        next_step_id=self._select_next_step(step.next,state)
        state.tasks.active.step_id=next_step_id
    #如何跳转到下一步,找到下一步的步骤id的方法
    def _select_next_step(self,next:list[FlowStepLink],state:DialogueState)->str:
        #如果next是一个字符串
        if len(next)==1:
            return next[0].target

        for link in next :
            if isinstance(link,ConditionalLink):
                #从state里面获取需要数据，和if条件比较条件是否成立
                result=bool(eval(link.condition,{},{"slots":state.tasks.active.slots}))
                if result:
                    return link.target
                continue
            if isinstance(link,FallbackLink):
                return link.target
    #处理collect类型步骤
    async def _run_collect_step(self,step:CollectSlotStep,
                          state:DialogueState,
                          user_message:UserMessage,
                          bot_messages:list[BotMessage])->bool:
        #1从当前活跃任务获取槽位数据
        slots:dict=state.tasks.active.slots
        slots_value=slots.get(step.solt_name)

        #2 如果当前活跃任务获取不到槽位数据，从聚焦对像获取槽位数据
        if not slots_value:
            #从聚焦对象获取槽位数据
            self.get_slot_data_focused_object(step,state)

        #3如果山方面两个步骤执行之后槽位数据都获取不到，给用户返回信息
        #true需要用户输入
        slots_value=state.tasks.active.slots.get(step.solt_name)
        if not  slots_value:
            bot_message=await self.response_renderer.render(
                step.template,state,user_message
            )
            bot_messages.append(bot_message)
            return True
        #4如果上面两步获取槽位数据
        else:
            #5判断配置文件是否有volidation校验
            if not step.validation:
                #推进下一步
                return False
        #6如果没有validation校验，直接推进下一步
            else:
                #7 如果有validation校验，判断校验条件是否成立，方法eval
                result=bool(eval(step.validation.condition,{},{'slots':state.tasks.active.slots}))

        #8如果校验成立，推进下一步
        if result:
            return False
        #9如果校验不成立，回复提示信息failure_response
        else:
            #从槽删除数据
            state.tasks.active.slots.pop(step.solt_name)
            bot_message= await self.response_renderer.render(
                step.validation.failure_template,state,user_message
            )
            bot_messages.append(bot_message)
            return True
    #从state聚焦对象获取槽位数据
    def get_slot_data_focused_object(self,step,state):
        #1判断focusd_object对象是否为空
        if not state.share.focuse_object:
            return
        #2foucued_object对象不为空
        #focused_object目前有两种 order product
        #对象类型 order
        if (step.solt_name=='order_number' and state.share.focuse_object.type=='order'):
            state.tasks.active.slots.update({step.solt_name:state.share.focuse_object.id})
            return
        if(step.solt_name=='product_id' and state.share.focuse_object.type=='product'):
            state.tasks.active.slots.update({step.solt_name:state.share.focuse_object.id})
            return
