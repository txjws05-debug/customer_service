#!/bin/bash
# 多轮任务评测入口：一条命令跑完「清旧账号 → 跑用例 → 记账 → 报告」。
#
#   bash deploy/run_eval.sh                      # 全部用例
#   bash deploy/run_eval.sh --limit 3            # 只跑前 3 条（改完提示词先冒烟）
#   bash deploy/run_eval.sh --only T63,T67       # 只跑改动相关的几条（推荐）
#   EVAL_TOKEN_CAP=300000 bash deploy/run_eval.sh --only T01
#
# 为什么固定成脚本而不是临时命令：
#   - 跑评测要同时满足三个条件（当前镜像 tag、中台服务令牌、清购物车），
#     靠记忆拼命令迟早漏一个，漏了就会得到一份不可信的报告；
#   - 每轮都会留下 eval_* 账号，必须在一个入口里顺手清掉；
#   - 2026-11-02 把两个模型的余额跑空过一次。原因是「为了验 2 条修复重跑整套」，
#     同一个套件被整跑 33 次。所以现在每次运行都要记账，且必须能按 ID 筛。
#
# 记账落在 eval_runs/_cost_ledger.csv，一行一次运行。查历史：
#   column -s, -t eval_runs/_cost_ledger.csv
set -euo pipefail

APP_DIR=${APP_DIR:-/opt/customer_service}
cd "$APP_DIR"

TAG=$(sed -n 's/^IMAGE_TAG=//p' deploy/.env | head -1)
[ -n "$TAG" ] || { echo "deploy/.env 里没有 IMAGE_TAG" >&2; exit 1; }
SVC=$(sed -n 's/^COMMERCE_SERVICE_TOKEN=//p' deploy/backend.env | head -1)
MTOKEN=$(sed -n 's/^METRICS_TOKEN=//p' deploy/backend.env | head -1)

# 读进程内累计 token 用量。读不到就返回 0（记账失败不该挡住评测本身）
token_used() {
  docker exec -e MT="$MTOKEN" cs-backend python -c "
import os, urllib.request
try:
    r = urllib.request.Request('http://127.0.0.1:18082/metrics',
        headers={'Authorization': 'Bearer ' + os.environ.get('MT', '')})
    text = urllib.request.urlopen(r, timeout=5).read().decode()
    for line in text.splitlines():
        if line.startswith('chat_budget_used '):
            print(int(float(line.split()[1])))
            break
    else:
        print(0)
except Exception:
    print(0)
" 2>/dev/null || echo 0
}

BEFORE=$(token_used)

# 先清上一轮留下的评测账号，避免「一个用户问了一百次」这种假象
bash deploy/cleanup_eval.sh --yes

# 评测本身可能因通过率不达标退出 1（--threshold 默认 0.9）。
# 记账不能因此被跳过，所以先关掉 set -e，最后再把退出码透传出去。
set +e
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
  --reset-stock \
  "$@"
EVAL_RC=$?
set -e

AFTER=$(token_used)
DELTA=$(( AFTER - BEFORE ))
mkdir -p eval_runs
printf '%s,%s,%s,%s\n' \
  "$(date '+%Y-%m-%d %H:%M:%S')" "$TAG" "$DELTA" "$*" \
  >> eval_runs/_cost_ledger.csv

DELTA=$DELTA python3 - <<'PY'
import json
import os

used = int(os.environ["DELTA"])
try:
    report = json.load(open("task_eval_report.json", encoding="utf-8"))
    total = report.get("total") or 0
    passed = report.get("passed") or 0
except Exception:
    total = passed = 0

per = used / total if total else 0
print(f"本次消耗 {used:,} tokens | 用例 {total} 条（通过 {passed}）| 单条≈{per:,.0f}")

cap = int(os.environ.get("EVAL_TOKEN_CAP") or 0)
if cap and used > cap:
    print(f"超过本次上限 {cap:,} tokens（-{used - cap:,}）", file=os.sys.stderr)
PY

# 透传评测本身的退出码（1 = 通过率低于门槛）
exit "$EVAL_RC"
