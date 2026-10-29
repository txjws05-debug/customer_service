#!/bin/bash
# 上线/回滚后的四秒体检。
#
# 为什么需要它：回滚脚本能判断「容器 healthy」，但 healthy 只说明进程活着，
# 不说明业务对。上次回滚没真跑，就是因为缺这个判断标准 ——
# 回滚完盯着 docker ps 看，看不出问题。
#
# 四项刻意选「不依赖任何密钥」的检查，这样它在任何环境都能直接跑：
#   1. 前端页面能打开
#   2. 中台公开读接口正常
#   3. 鉴权真的在生效（运营端匿名必须 401）
#   4. 接口文档真的关着（/docs 必须 404）
# 对话功能需要登录态，不放进 smoke（否则每次都要带密码，跑不起来）。
set -uo pipefail

BASE=${BASE_URL:-http://127.0.0.1}
fail=0

check() {  # check <名称> <期望状态码> <路径> [方法]
    local name=$1 expect=$2 path=$3 method=${4:-GET}
    local code
    code=$(curl -s -o /dev/null -m 10 -X "$method" -w '%{http_code}' "$BASE$path")
    if [ "$code" = "$expect" ]; then
        printf '  [PASS] %-28s %s\n' "$name" "$code"
    else
        printf '  [FAIL] %-28s %s（期望 %s）\n' "$name" "$code" "$expect"
        fail=1
    fi
}

echo "== smoke: $BASE =="
check "前端 /chat"                 200 "/chat"
check "中台商品（匿名可读）"        200 "/shop/products?page_size=1"
check "中台运营端（匿名应拦）"      401 "/shop/admin/orders"
check "接口文档（应已关闭）"        404 "/docs"
check "对话接口（匿名应拦）"        401 "/api/chat" POST

if [ "$fail" -ne 0 ]; then
    echo "smoke 失败：有检查项不符合预期，不要继续发布。"
    exit 1
fi
echo "smoke 通过。"
