#!/bin/bash
# 在限内存的临时容器里构建 Next.js：OOM 时只会杀掉这个容器，不会波及线上服务。
set -uo pipefail
OUT=/tmp/fe-out
rm -rf "$OUT" && mkdir -p "$OUT"
echo "开始 $(date '+%T')，可用内存 $(free -m | awk '/Mem/{print $7}')MB"
docker run --rm --name fe-build \
  --memory=900m --memory-swap=2200m --cpus=1.5 \
  -e NODE_OPTIONS=--max-old-space-size=768 -e NEXT_TELEMETRY_DISABLED=1 -e NEXT_PUBLIC_API_BASE= \
  -v /opt/customer_service/frontend:/src:ro -v "$OUT":/out \
  node:22-alpine sh -c '
    set -e
    mkdir -p /work && cd /work
    cp -r /src/. /work/ && rm -rf node_modules .next
    npm ci --no-audit --no-fund --registry=https://registry.npmmirror.com > /out/npm.log 2>&1
    npm run build > /out/build.log 2>&1
    cp -r .next/standalone /out/standalone && cp -r .next/static /out/static && cp -r public /out/public
    echo BUILD_OK > /out/status'
rc=$?
echo "容器退出码 $rc，结束 $(date '+%T')"
[ -f "$OUT/status" ] && cat "$OUT/status" || { echo BUILD_FAILED; tail -15 "$OUT/build.log" 2>/dev/null; tail -5 "$OUT/npm.log" 2>/dev/null; }
echo FE_BUILD_DONE
