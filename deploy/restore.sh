#!/bin/bash
# 备份恢复：演练（默认）与真恢复（需 --yes）。
#
# 「写完脚本」不等于「有备份」—— 所以默认行为是**演练**：
# 把备份灌进一个临时库，逐表比对行数，比对通过才算这个备份可用。
# 真恢复要显式加 --yes，因为它会覆盖线上库。
set -euo pipefail

PG=${PG_CONTAINER:-cs-postgres}
PGUSER=${PG_USER:-cs}

usage() {
    cat <<'EOF'
用法：
  restore.sh --verify  <db> <file.sql.gz>   演练：恢复到临时库并比对行数
  restore.sh --restore <db> <file.sql.gz> --yes   真恢复：覆盖线上库

示例：
  restore.sh --verify commerce /opt/backups/commerce-20261028-171500.sql.gz
EOF
    exit 2
}

mode=${1:-}
db=${2:-}
file=${3:-}

[ -n "$mode" ] && [ -n "$db" ] && [ -n "$file" ] || usage
[ -f "$file" ] || { echo "备份文件不存在：$file" >&2; exit 1; }

# 每张表都要比对；缺表说明备份不完整
case "$db" in
    commerce) tables="orders order_items products product_skus users cart_items coupons user_coupons" ;;
    customer_service) tables="users dialogue_states knowledge_chunks knowledge_meta" ;;
    *) echo "未知库：$db" >&2; exit 2 ;;
esac

count_of() {  # count_of <db> <table>
    docker exec "$PG" psql -U "$PGUSER" -d "$1" -tAc "select count(*) from $2" 2>/dev/null | tr -d ' [:space:]'
}

start_ts=$(date +%s)

if [ "$mode" = "--verify" ]; then
    tmp="verify_$(date +%H%M%S)_$$"
    echo "== 演练开始：$file -> 临时库 $tmp =="
    docker exec "$PG" psql -U "$PGUSER" -d postgres -q -c "DROP DATABASE IF EXISTS $tmp"
    docker exec "$PG" psql -U "$PGUSER" -d postgres -q -c "CREATE DATABASE $tmp"
    if ! gunzip -c "$file" | docker exec -i "$PG" psql -U "$PGUSER" -d "$tmp" -q >/dev/null 2>&1; then
        echo "恢复失败：导入报错" >&2
        docker exec "$PG" psql -U "$PGUSER" -d postgres -q -c "DROP DATABASE IF EXISTS $tmp"
        exit 1
    fi
    fail=0
    printf '%-24s %10s %10s %s\n' 表 备份行数 当前库行数 结果
    for t in $tables; do
        a=$(count_of "$tmp" "$t"); b=$(count_of "$db" "$t")
        if [ -z "$a" ] || [ -z "$b" ]; then
            printf '%-24s %10s %10s %s\n' "$t" "${a:-缺失}" "${b:-缺失}" "FAIL"
            fail=1
        elif [ "$a" -ge "$b" ]; then
            # 备份行数 >= 当前库：正常（备份之后可能删过数据）
            printf '%-24s %10s %10s %s\n' "$t" "$a" "$b" "OK"
        else
            printf '%-24s %10s %10s %s\n' "$t" "$a" "$b" "FAIL(备份更少)"
            fail=1
        fi
    done
    docker exec "$PG" psql -U "$PGUSER" -d postgres -q -c "DROP DATABASE IF EXISTS $tmp"
    elapsed=$(( $(date +%s) - start_ts ))
    if [ "$fail" -eq 0 ]; then
        echo "演练结果：PASS，耗时 ${elapsed}s（RTO 实测值）"
        exit 0
    fi
    echo "演练结果：FAIL，耗时 ${elapsed}s" >&2
    exit 1
fi

if [ "$mode" = "--restore" ]; then
    [ "${4:-}" = "--yes" ] || { echo "真恢复会覆盖 $db，请显式追加 --yes" >&2; exit 2; }
    echo "== 真恢复：$file -> $db =="
    docker exec "$PG" psql -U "$PGUSER" -d postgres -q -c \
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$db' AND pid<>pg_backend_pid()"
    docker exec "$PG" psql -U "$PGUSER" -d postgres -q -c "DROP DATABASE IF EXISTS $db"
    docker exec "$PG" psql -U "$PGUSER" -d postgres -q -c "CREATE DATABASE $db"
    gunzip -c "$file" | docker exec -i "$PG" psql -U "$PGUSER" -d "$db" -q >/dev/null
    elapsed=$(( $(date +%s) - start_ts ))
    echo "恢复完成，耗时 ${elapsed}s。请立刻验证业务："
    echo "  curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/shop/products?page_size=1"
    exit 0
fi

usage
