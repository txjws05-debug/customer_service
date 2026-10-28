#!/bin/bash
# 备份两个 PostgreSQL 库 + 三个环境文件。
#
# 设计要点（每一条都是踩过坑才加的）：
# 1. 只有「文件非空」才算成功；失败批次不写 .last_success，避免以为有备份其实没有；
# 2. 环境文件含密钥，单独打包并 chmod 600 —— 丢了 env 比丢库更难恢复
#    （JWT_SECRET_KEY 变了所有人要重登，POSTGRES_PASSWORD 改了老库不认）；
# 3. 保留策略按「成功批次数」而不是文件时间：备份失败那天不该占掉一个位置。
set -euo pipefail

APP_DIR=${APP_DIR:-/opt/customer_service}
BK_DIR=${BK_DIR:-/opt/backups}
PG=${PG_CONTAINER:-cs-postgres}
PGUSER=${PG_USER:-cs}
KEEP_BATCHES=${KEEP_BATCHES:-7}

STAMP=$(date +%Y%m%d-%H%M%S)
mkdir -p "$BK_DIR"
chmod 700 "$BK_DIR"

written=()
for db in customer_service commerce; do
    out="$BK_DIR/${db}-${STAMP}.sql.gz"
    # pg_dump 走自定义格式更稳，但纯文本 + gzip 便于人工排查，这里选后者
    if docker exec "$PG" pg_dump -U "$PGUSER" -d "$db" | gzip -6 > "$out"; then
        if [ -s "$out" ]; then
            written+=("$out")
        else
            echo "备份失败：$db 产出为空文件" >&2
            rm -f "$out"
            exit 1
        fi
    else
        echo "备份失败：$db pg_dump 报错" >&2
        rm -f "$out"
        exit 1
    fi
done

# 配置与环境：丢了库还能重建，丢了密钥就得重新签发
ENV_TAR="$BK_DIR/env-${STAMP}.tar.gz"
tar czf "$ENV_TAR" -C "$APP_DIR" deploy/.env deploy/backend.env deploy/ecommerce.env
chmod 600 "$BK_DIR"/*.gz

echo "$STAMP" > "$BK_DIR/.last_success"

# 按批保留：每批 2 个 sql + 1 个 env
ls -1t "$BK_DIR"/*.sql.gz 2>/dev/null | tail -n +$((KEEP_BATCHES * 2 + 1)) | xargs -r rm -f
ls -1t "$BK_DIR"/env-*.tar.gz 2>/dev/null | tail -n +$((KEEP_BATCHES + 1)) | xargs -r rm -f

total=$(du -sh "$BK_DIR" | cut -f1)
echo "备份完成 stamp=$STAMP 文件=$((${#written[@]} + 1)) 个 目录用量=$total"
for f in "${written[@]}" "$ENV_TAR"; do
    printf '  %s  %s\n' "$(basename "$f")" "$(du -h "$f" | cut -f1)"
done
