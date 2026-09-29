# ===== 后端镜像：FastAPI + LangChain 客服 Agent =====
# 用 uv 管理依赖，多阶段构建，最终镜像不含构建工具
FROM python:3.12-slim AS builder

# uv：极快的 Python 依赖安装（项目本身就用 uv 管理）
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple/

WORKDIR /app

# 先只拷贝依赖清单，最大化利用 Docker 层缓存
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# 再拷贝源码
COPY ws ./ws
COPY .env.example ./.env.example

# ------------------------- 运行阶段 -------------------------
FROM python:3.12-slim

# pgvector 客户端无需额外包；这里只需要时区与最小运行库
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# 仅拷贝虚拟环境与源码，镜像更小
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/ws /app/ws

EXPOSE 18082

# 单 worker：服务器内存有限（2C2G），多 worker 会放大内存占用
CMD ["python", "-m", "ws.api.main"]
