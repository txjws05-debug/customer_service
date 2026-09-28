import uvicorn
from ws.config.config import settings
from ws.utils.database import init_db_engine
from ws.utils.http import init_http_client

if __name__=="__main__":
    init_db_engine()
    init_http_client()
    uvicorn.run("ws.api.app:app",
                host=settings.app_host,
                port=settings.app_port)
