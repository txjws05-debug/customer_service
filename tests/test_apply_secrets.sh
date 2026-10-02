#!/usr/bin/env bash
# ============================================================
# deploy/apply-secrets.sh 的行为测试（不依赖服务器、不依赖 GitHub）
#
# 这个脚本负责把 GitHub Secrets 落到服务器上的 deploy/backend.env，
# 一旦逻辑错，表现是「改了 Secret 但线上没生效」——很难排查。
# 所以把它的语义固定成断言，本地和 CI 跑的是同一份。
#
# 用法：bash tests/test_apply_secrets.sh
# ============================================================
set -euo pipefail

cd "$(dirname "$0")/.."

FLAG="/tmp/cs-env-changed"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"; rm -f "$FLAG"' EXIT

mkdir -p "$tmp/deploy"
cp deploy/apply-secrets.sh "$tmp/deploy/"
printf 'LLM_API_KEY=keepme\nEMBEDDING_MODEL=old-model\n' > "$tmp/deploy/backend.env"

run() { (cd "$tmp" && env "$@" bash deploy/apply-secrets.sh); }
env_file="$tmp/deploy/backend.env"

fail() { echo "FAIL: $1" >&2; exit 1; }

echo "1) 没传值：一个字都不该动（包括无关变量）"
run DUMMY=1 >/dev/null
grep -qx 'EMBEDDING_MODEL=old-model' "$env_file" || fail "未传值时配置被改动了"
grep -qx 'LLM_API_KEY=keepme' "$env_file" || fail "动了无关变量"
echo "   OK"

echo "2) 传值：覆盖、不产生重复行、特殊字符原样落盘"
run EMBEDDING_MODEL=text-embedding-v3 EMBEDDING_API_KEY='sk-a$b&c|d' >/dev/null
grep -qx 'EMBEDDING_MODEL=text-embedding-v3' "$env_file" || fail "配置未更新"
if [ "$(grep -c '^EMBEDDING_MODEL=' "$env_file")" != "1" ]; then
  fail "产生了重复行"
fi
grep -qxF 'EMBEDDING_API_KEY=sk-a$b&c|d' "$env_file" \
  || fail "密钥里的特殊字符被 shell 解释了"
echo "   OK"

echo "3) 传 \"-\"：清除该项（用于回退到本地向量）"
run EMBEDDING_MODEL=- >/dev/null
if grep -q '^EMBEDDING_MODEL=' "$env_file"; then
  fail "未按 - 清除"
fi
echo "   OK"

echo "4) 变化标记：有变化才留，无变化不留"
rm -f "$FLAG"
run EMBEDDING_MODEL=x >/dev/null
[ -f "$FLAG" ] || fail "有变化时未留下标记"

rm -f "$FLAG"                       # 关键：清掉上一次留下的标记再测「无变化」
run EMBEDDING_MODEL=x >/dev/null
if [ -f "$FLAG" ]; then
  fail "无变化时不该留下标记（会导致每次部署都白重建容器）"
fi
echo "   OK"

echo "5) 缺 env 文件必须失败，而不是静默跳过"
rm "$env_file"
if run EMBEDDING_MODEL=x >/dev/null 2>&1; then
  fail "缺少 env 文件时应当返回失败"
fi
echo "   OK"

echo
echo "apply-secrets.sh 全部断言通过"
