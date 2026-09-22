import uvicorn
from ws.config.config import settings
from ws.utils.database import init_db_engine

if __name__=="__main__":
    init_db_engine()
    uvicorn.run("atguigu.api.app:app",
                host=settings.app_host,
                port=settings.app_port)
