#!/bin/bash
# 审计表保留策略：默认保留 30 天。
#
# 为什么需要：`audit_log` 只增不删，每个写请求一条。按现在的量级不显眼，
# 但它是唯一会**随运行时间自然恶化**的表 —— 一旦成了几十万行，
# 按时间范围查审计会变慢，磁盘也会被慢慢吃掉。
#
# 为什么是 30 天：审计的用途是「近期追责」，30 天足够覆盖一次事故回溯。
# 更长的留存应该走归档（当前没做），而不是把主表撑大。
#
# 时区说明：`created_at` 是应用侧写进来的本地时间（naive），
# 与数据库的 `now()` 可能差几个小时。30 天的阈值上这点偏差无所谓，
# 但不要用它做「精确到小时」的判断。
#
#   bash deploy/cleanup_audit.sh          # 只看会删多少（dry-run）
#   bash deploy/cleanup_audit.sh --yes    # 真删
set -euo pipefail

PG=${PG_CONTAINER:-cs-postgres}
PGUSER=${PG_USER:-cs}
DB=${PG_DB:-commerce}
KEEP_DAYS=${KEEP_DAYS:-30}

APPLY=0
[ "${1:-}" = "--yes" ] && APPLY=1

q() { docker exec "$PG" psql -U "$PGUSER" -d "$DB" -tAc "$1"; }

total=$(q "select count(*) from audit_log")
old=$(q "select count(*) from audit_log
         where created_at < (now() - interval '${KEEP_DAYS} days')::timestamp")

echo "审计表共 $total 条，其中超过 ${KEEP_DAYS} 天的 $old 条"

if [ "$old" = "0" ]; then
    echo "无需清理"
    exit 0
fi

if [ "$APPLY" != "1" ]; then
    echo "（dry-run）确认无误后加 --yes 执行"
    exit 0
fi

# 分批删除：一次删太多会长时间持锁，也和正常写入抢 IO。
# 10000 条一批，直到没有可删的为止。
deleted=0
while :; do
    n=$(q "with batch as (
             select id from audit_log
              where created_at < (now() - interval '${KEEP_DAYS} days')::timestamp
              limit 10000
           ), gone as (
             delete from audit_log using batch where audit_log.id = batch.id
             returning 1
           ) select count(*) from gone")
    deleted=$((deleted + n))
    [ "$n" = "0" ] && break
done

left=$(q "select count(*) from audit_log")
echo "已删除 $deleted 条，剩余 $left 条"
