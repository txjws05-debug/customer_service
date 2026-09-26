from pathlib import Path

import yaml
from langchain_core._api import path

from ws.task.flow.models import Flow, FlowCatalog, FlowSlot
from ws.task.flow.steps import FlowStep

class FlowLoader:
    def load(self,path:Path)->FlowCatalog:
        flow_data = path.read_text(encoding="utf-8")
        flow_dict=yaml.safe_load(flow_data)

        slots: dict[str,FlowSlot] =self._load_slots(flow_dict['slots'])

        flows: dict[str,Flow] = self._load_flows(flow_dict['flows'],slots)
        return FlowCatalog(flows=flows,slots=slots)

    def _load_slots(self,slots_data:dict[str,dict]) -> dict[str,FlowSlot]:
        slots: dict[str,FlowSlot]={}
        for slot_name,slots_data in slots_data.items():
            slots[slot_name] =  FlowSlot(
                name=slot_name,
                **slots_data
            )
        return slots

    def _load_flows(self,flows_data:dict[str,dict],
                    slots:dict[str,FlowSlot])->dict[str,Flow]:
        flows:dict[str,Flow]={}
        for flow_id ,flow_data in flows_data.items():
            flow_slots: list[FlowSlot]=[
                slots[collect_step['slot_name']]
                for collect_step in flow_data['steps']
                if collect_step['type']=='collect'
            ]
            # 步骤列表
            steps: list[FlowStep] = [
                FlowStep.from_dict(flow_step)
                for flow_step in flow_data['steps']
            ]
            # 封装 Flow 对象
            flow: Flow = Flow(
                id=flow_id,
                description=flow_data['description'],
                steps=steps,
                slots=flow_slots,
                name=flow_data['name'],
            )
            flows[flow_id] = flow
        return flows
def loader (self,paths: list[Path])-> FlowLoader:
    flows:dict[str,Flow]={}
    slots: dict[str,FlowSlot]={}

    for path in paths:
        catalog= self.load(path)
        flows.update(catalog.flows)
        slots.update(catalog.slots)
    return FlowCatalog(flows=flows,slots=slots)

def loader_many(self,paths:list[Path])-> FlowCatalog:
    flows:dict[str,Flow]={}
    slots:dict[str,FlowSlot]={}

    for path in paths:
        catalog=self.load(path)
        #dict用update合并（list 合并用extend，注意区别）
        flows.update(catalog.flows)
        slots.update(catalog.slots)
    return FlowCatalog(flows=flows,slots=slots)
if __name__ == "__main__":
    loader = FlowLoader()
    path = Path(__file__).parents[2] / 'config' / 'test.yml'
    result = loader.load(path)
    print(result)