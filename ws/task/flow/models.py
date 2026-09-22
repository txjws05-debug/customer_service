from dataclasses import dataclass, field

from ws.task.flow.steps import FlowStep, StartFlowStep

@dataclass
class FlowSlot:
    name :str
    type: str ="any"
    label: str=""
    description: str=""
@dataclass
class Flow:
    id :str
    description: str=""
    steps: list[FlowStep] = field(default_factory=list)
    slots: list[FlowSlot]= field(default_factory=list)
    name: str | None =None

    def get_start_step(self)-> StartFlowStep:
        for step in self.steps:
             if isinstance(step,StartFlowStep):
                 return step
        raise Exception("Flow not found")

    def get_step_by_id(self,step_id)->FlowStep:
        for step in self.steps:
            if step.id==step_id:
                return  step
        raise Exception('step not found')
@dataclass
class FlowCatalog:
    flows: dict[str,Flow] = field(default_factory=dict)
    slots: dict[str,FlowSlot]=field(default_factory=dict)

    def get_flow_by_id(self,flow_id)-> Flow:
        return self.flows[flow_id ]