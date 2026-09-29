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

    #商城 API
    commerce_api_base_url: str

    #JWT（本地演示，密钥给了默认值；上线请通过环境变量覆盖）
    jwt_secret_key: str = "customer-service-dev-secret-please-change"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720

    #服务器
    app_host:str
    app_port:int

    model_config = SettingsConfigDict(env_file=ENV_FILE, extra='ignore')
settings=Settings()