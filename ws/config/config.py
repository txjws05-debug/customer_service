from pathlib import  Path
from pydantic_settings import BaseSettings,SettingsConfigDict
ENV_FILE=Path(__file__).parents[2]/'.env'

class Settings(BaseSettings):
    #LLM
    llm_api_key:str
    llm_model:str
    llm_base_url:str

    #数据库
    database_url:str


    #商城API
    commerce_api_key:str

    #商城 API
    commerce_api_key_base_url:str

    #服务器
    app_host:str
    app_port:int

    model_config = SettingsConfigDict(env_file=ENV_FILE)
settings=Settings()