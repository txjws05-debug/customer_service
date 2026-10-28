# 客服端（Agent）补丁镜像：以线上运行的镜像为底座，只覆盖今天改过的文件。
#
# 为什么不完整重建：Dockerfile 里 `uv sync` 需要访问 PyPI，这台机器拉包会卡死；
# 而代码本身已经全部提交到 git，网络恢复后随时可以改用根目录 Dockerfile 重建。
ARG BASE=ghcr.io/txjws05-debug/customer-service-api:b1d4aff645e411213f4ba75357778127f2421306
FROM ${BASE}

COPY ws/utils/http.py        /app/ws/utils/http.py
COPY ws/utils/llm_client.py  /app/ws/utils/llm_client.py
COPY ws/utils/logging_config.py /app/ws/utils/logging_config.py
COPY ws/trace.py           /app/ws/trace.py
COPY ws/metrics.py         /app/ws/metrics.py
COPY ws/config/config.py     /app/ws/config/config.py
COPY ws/security/jwt.py      /app/ws/security/jwt.py
COPY ws/api/app.py           /app/ws/api/app.py
