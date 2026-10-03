#!/usr/bin/env bash
# ============================================================
# deploy/check-secrets.sh 的行为测试（不依赖 GitHub、不依赖服务器）
#
# 它负责在部署前判掉「配置填错」的各种姿势，所以每一种都要有断言：
# 空值、中文占位符、夹带空白、长度异常 —— 并且任何情况下都不许泄露值。
#
# 用法：bash tests/test_check_secrets.sh
# ============================================================
set -euo pipefail

cd "$(dirname "$0")/.."

fail() { echo "FAIL: $1" >&2; exit 1; }
run() { env "$@" bash deploy/check-secrets.sh; }

echo "1) 三项全空 = 合法的本地向量模式，应通过"
out="$(run DUMMY=1)"
echo "$out" | grep -q '本地词法向量' || fail "三项全空时应说明走本地向量"
echo "   OK"

echo "2) 正常配置应通过"
out="$(run EMBEDDING_BASE_URL='https://dashscope.aliyuncs.com/compatible-mode/v1' \
           EMBEDDING_MODEL='text-embedding-v3' \
           EMBEDDING_API_KEY='sk-0123456789abcdef0123456789abcdef')"
echo "$out" | grep -q '形态正常' || fail "正常配置被误判为有问题"
echo "   OK"

echo "3) 空值 key 必须判失败（GitHub 允许保存空值 Secret）"
if run EMBEDDING_BASE_URL='https://x/v1' EMBEDDING_MODEL='m' EMBEDDING_API_KEY='' \
     >/dev/null 2>&1; then
  fail "空值 key 竟然通过了"
fi
echo "   OK"

echo "4) 中文占位符必须判失败"
if run EMBEDDING_BASE_URL='https://x/v1' EMBEDDING_MODEL='m' \
     EMBEDDING_API_KEY='sk-把这里换成你的真实key' >/dev/null 2>&1; then
  fail "中文占位符竟然通过了"
fi
echo "   OK"

echo "5) 夹带空白（把整行配置粘了进来）必须判失败"
if run EMBEDDING_BASE_URL='https://x/v1' EMBEDDING_MODEL='m' \
     EMBEDDING_API_KEY='sk-abc EMBEDDING_MODEL=text-embedding-v3' >/dev/null 2>&1; then
  fail "含空白的值竟然通过了"
fi
echo "   OK"

echo "6) 长 key 必须放行（回归：曾因假设「约 35 个字符」把有效 key 拦住）"
# 线上真实情况：一把可用的百炼 key 是 117 个字符，curl 返回 200。
# 当初按「约 35」加了长度上限，结果直接拦下部署，白卡了好几轮。
long_key="sk-$(printf 'a%.0s' {1..114})"
out="$(run EMBEDDING_BASE_URL='https://x/v1' EMBEDDING_MODEL='m' \
           EMBEDDING_API_KEY="$long_key")" \
  || fail "117 个字符的 key 被误判为错误（长度不该作为判据）"
echo "$out" | grep -q '形态正常' || fail "长 key 应被判为形态正常"
echo "   OK"

echo "7) 任何情况下都不能把值本身打印出来"
secret='sk-SUPERSECRETVALUE0123456789abcdef'
out="$(run EMBEDDING_BASE_URL='https://x/v1' EMBEDDING_MODEL='m' \
           EMBEDDING_API_KEY="$secret" || true)"
if echo "$out" | grep -q 'SUPERSECRETVALUE'; then
  fail "校验脚本把密钥值打印出来了"
fi
echo "   OK"

echo
echo "check-secrets.sh 全部断言通过"
