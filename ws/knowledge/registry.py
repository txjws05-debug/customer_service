from ws.knowledge.provider import KnowledgeProvider

#把provider注册,字典里面
class KnowledgeProviderRegistry():
     #初始化方法，传入所有的provider对象，进行注册
     def __init__(self,prvider_objs:list[KnowledgeProvider])->None:
         #把所有provider对象注册字典类型变量里面
         self._provider_by_id={
             provider_obj.provider_id : provider_obj
             for provider_obj in prvider_objs
         }

    #根据provider_id返回对应provider对象的方法
     def get(self,provider_id:str)->KnowledgeProvider:
        return self._provider_by_id.get(provider_id)
