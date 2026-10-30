#!/bin/bash
# 验证备份保留策略（C-03 的「连续 7 天成功、第 8 天失败不删旧备份」）。
#
# 为什么要有这个脚本：保留策略只写不验，等于没人知道它对不对。
# 真等 7 天不现实，所以用 `BACKUP_STAMP` 注入时间 + 假的 docker 模拟成功/失败，
# 一分钟内跑完 8 天，且**完全不碰真实数据库**。
#
#   bash deploy/test_backup_retention.sh
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
BACKUP_SH=${BACKUP_SH:-$HERE/backup.sh}
KEEP=7
FAILED=0

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

export BK_DIR="$TMP/backups"
export APP_DIR="$TMP/app"
mkdir -p "$APP_DIR/deploy" "$TMP/bin"
for f in .env backend.env ecommerce.env; do
    echo "FAKE=1" > "$APP_DIR/deploy/$f"
done

# 假 docker：模拟 pg_dump 成功/失败，不连库
cat > "$TMP/bin/docker" <<'STUB'
#!/bin/bash
if [ "${STUB_FAIL:-0}" = "1" ]; then
    echo "stub: pg_dump failed" >&2
    exit 1
fi
echo "-- fake pg_dump output"
STUB
chmod +x "$TMP/bin/docker"
export PATH="$TMP/bin:$PATH"

run_backup() {  # $1=stamp  $2=是否模拟失败(1/0)
    BACKUP_STAMP="$1" STUB_FAIL="${2:-0}" bash "$BACKUP_SH" >/dev/null 2>&1
}

count_env()  { ls -1 "$BK_DIR"/env-*.tar.gz 2>/dev/null | wc -l | tr -d ' '; }
count_sql()  { ls -1 "$BK_DIR"/*.sql.gz     2>/dev/null | wc -l | tr -d ' '; }
last_succ()  { cat "$BK_DIR/.last_success" 2>/dev/null || echo "-"; }

check() {  # $1=描述 $2=实际 $3=期望
    if [ "$2" = "$3" ]; then
        echo "  [PASS] $1（$2）"
    else
        echo "  [FAIL] $1：实际=$2 期望=$3"
        FAILED=1
    fi
}

echo "== 第 1~7 天：全部成功 =="
for day in 1 2 3 4 5 6 7; do
    run_backup "2026100${day}-030000" 0 || { echo "  [FAIL] 第 $day 天备份应成功"; FAILED=1; }
done
check "环境包数量（7 批）" "$(count_env)" "$KEEP"
check "SQL 数量（7 批 × 2 库）" "$(count_sql)" "$((KEEP * 2))"
check ".last_success 为第 7 天" "$(last_succ)" "20261007-030000"

echo "== 第 8 天：模拟备份失败 =="
if run_backup "20261008-030000" 1; then
    echo "  [FAIL] 失败批次应返回非 0"
    FAILED=1
else
    echo "  [PASS] 失败批次返回非 0"
fi
check "旧备份未被删除（环境包）" "$(count_env)" "$KEEP"
check "旧备份未被删除（SQL）" "$(count_sql)" "$((KEEP * 2))"
check "失败不推进 .last_success" "$(last_succ)" "20261007-030000"
check "失败批次未留下空文件" "$(ls -1 "$BK_DIR"/*20261008* 2>/dev/null | wc -l | tr -d ' ')" "0"

echo "== 第 8 天重试：改为成功 =="
run_backup "20261008-030000" 0 || { echo "  [FAIL] 重试应成功"; FAILED=1; }
check "仍然只保留 7 批" "$(count_env)" "$KEEP"
check "SQL 仍为 14 个" "$(count_sql)" "$((KEEP * 2))"
check "最旧一批（第 1 天）已被清理" "$(ls -1 "$BK_DIR"/*20261001* 2>/dev/null | wc -l | tr -d ' ')" "0"
check "最新一批（第 8 天）存在" "$(ls -1 "$BK_DIR"/env-20261008-030000.tar.gz 2>/dev/null | wc -l | tr -d ' ')" "1"
check ".last_success 推进到第 8 天" "$(last_succ)" "20261008-030000"

echo
if [ "$FAILED" = "0" ]; then
    echo "RESULT: PASS（保留 7 批、失败不删旧、失败不推进、重试正确修剪）"
    exit 0
fi
echo "RESULT: FAIL"
exit 1
