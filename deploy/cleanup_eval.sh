#!/bin/bash
# 清理评测账号。
#
# 每跑一轮评测都会注册一个 `eval_xxxxxxxx` 用户并产生对话状态。不清理会无限堆积
# （截至 2026-10-30 已积累 9 个），副作用有两个：
#   1. `select count(*) from users` 越来越不像真实用户数；
#   2. 真要按用户排查问题时，得先滤掉一堆测试账号。
#
# 安全边界（这三条比功能本身重要）：
#   - 只删 username / sender_id 以 `eval_` 开头的行，绝不碰真实用户；
#     下划线在 LIKE 里是通配符，所以写成 `eval\_%` 精确匹配前缀；
#   - 默认 dry-run，必须加 --yes 才真删；
#   - 只动 customer_service 库；commerce 库里评测产生的购物车由 runner 自己清，
#     评测不下单，所以没有订单要处理。
#
#   bash deploy/cleanup_eval.sh          # 只看会删多少
#   bash deploy/cleanup_eval.sh --yes    # 真删
set -euo pipefail

PG=${PG_CONTAINER:-cs-postgres}
PGUSER=${PG_USER:-cs}
DB=${PG_DB:-customer_service}

APPLY=0
[ "${1:-}" = "--yes" ] && APPLY=1

q() { docker exec "$PG" psql -U "$PGUSER" -d "$DB" -tAc "$1"; }

users=$(q "select count(*) from users where username like 'eval\\_%'")
states=$(q "select count(*) from dialogue_states where sender_id like 'eval\\_%'")
tickets=$(q "select count(*) from handoff_tickets where sender_id like 'eval\\_%'")

echo "待清理：用户 $users 个、对话状态 $states 条、工单 $tickets 条"

if [ "$users" = "0" ] && [ "$states" = "0" ] && [ "$tickets" = "0" ]; then
    echo "没有需要清理的记录"
    exit 0
fi

if [ "$APPLY" != "1" ]; then
    echo "（dry-run）确认无误后加 --yes 执行"
    exit 0
fi

# 先删子表再删主表：即使将来加了外键也不会因约束失败
docker exec "$PG" psql -U "$PGUSER" -d "$DB" -v ON_ERROR_STOP=1 \
    -c "delete from handoff_tickets where sender_id like 'eval\\_%'" \
    -c "delete from dialogue_states where sender_id like 'eval\\_%'" \
    -c "delete from users where username like 'eval\\_%'" >/dev/null

left_users=$(q "select count(*) from users where username like 'eval\\_%'")
left_states=$(q "select count(*) from dialogue_states where sender_id like 'eval\\_%'")
total_users=$(q "select count(*) from users")

echo "清理后：eval 用户 $left_users 个、eval 对话状态 $left_states 条；真实用户总数 $total_users"
if [ "$left_users" != "0" ]; then
    echo "残留未清理干净" >&2
    exit 1
fi
echo "清理完成"
