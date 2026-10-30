#!/bin/bash
# 多轮任务评测入口：一条命令跑完「清旧账号 → 跑用例 → 报告」。
#
#   bash deploy/run_eval.sh                 # 全部 20 条
#   bash deploy/run_eval.sh --limit 3       # 只跑前 3 条（改完提示词先冒烟）
#
# 为什么固定成脚本而不是临时命令：
#   - 跑评测要同时满足三个条件（当前镜像 tag、中台服务令牌、清购物车），
#     靠记忆拼命令迟早漏一个，漏了就会得到一份不可信的报告；
#   - 每轮都会留下 eval_* 账号，必须在一个入口里顺手清掉。
set -euo pipefail

APP_DIR=${APP_DIR:-/opt/customer_service}
cd "$APP_DIR"

TAG=$(sed -n 's/^IMAGE_TAG=//p' deploy/.env | head -1)
[ -n "$TAG" ] || { echo "deploy/.env 里没有 IMAGE_TAG" >&2; exit 1; }
SVC=$(sed -n 's/^COMMERCE_SERVICE_TOKEN=//p' deploy/backend.env | head -1)

# 先清上一轮留下的评测账号，避免「一个用户问了一百次」这种假象
bash deploy/cleanup_eval.sh --yes

docker run --rm --network container:cs-backend \
  -v "$APP_DIR:/src" -w /src -e PYTHONPATH=/src \
  -e COMMERCE_SERVICE_TOKEN="$SVC" \
  --entrypoint /app/.venv/bin/python \
  "ghcr.io/txjws05-debug/customer-service-api:${TAG}" \
  /src/tools/task_eval.py \
  --base-url http://127.0.0.1:18082 \
  --cases tools/task_cases.yaml \
  --json /src/task_eval_report.json \
  --commerce-url http://ecommerce:18081 \
  "$@"
