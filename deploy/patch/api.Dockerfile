# 客服端（Agent）补丁镜像：以线上运行的镜像为底座，整体覆盖源码目录。
#
# 为什么整目录而不是逐文件：逐文件 COPY 时每加一个模块都要改这张清单，
# 漏一个就是「线上跑的是旧代码、本地测试是新的」这种最难查的问题。
# 整目录覆盖不会漏，代价只是镜像层大一点（ws/ 本来也只有几百 KB）。
#
# 为什么不完整重建：根 Dockerfile 里 `uv sync` 要访问 PyPI，这台机器拉包会卡死；
# 代码本身已全部提交到 git，网络恢复后随时可以改用根 Dockerfile 重建。
ARG BASE=ghcr.io/txjws05-debug/customer-service-api:b1d4aff645e411213f4ba75357778127f2421306
FROM ${BASE}

COPY ws /app/ws
