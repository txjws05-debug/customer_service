#!/usr/bin/env bash
# ============================================================
# 校验配置类 Secret 的「形态」（只看形状，绝不打印值）。
#
# 为什么要它：配置填错时，原来的表现是「流水线跑 4 分钟 → 服务器上报 401」，
# 而且报错看不出是"值没填对"。线上真实踩过：
#   - Secret 存成空值（GitHub 允许），列表里有名字、值是空的
#   - 复制时把整行配置/命令一起粘了进来，长度 118（正常约 35），
#     其中夹带的引号/换行还会把 CI→服务器的环境变量转发弄坏
# 现在这些都在这里当场判掉，部署在 SSH 之前就失败，并说清楚该怎么改。
#
# 用法：bash deploy/check-secrets.sh
#   退出码 0 = 形态正常（或压根没配 embedding，属于合法的本地向量模式）
#   退出码 1 = 配置形态明显有问题
#
# 只校验「打算用 API embedding」的情况：三项全空 = 用本地词法向量，合法。
# ============================================================
set -uo pipefail

# API Key 的合理长度区间（百炼约 35，留足其它厂商的余量）
MIN_KEY_LEN=20
MAX_KEY_LEN=80

failed=0

fail() {
  # ::error:: 会让 GitHub 在 Actions 页面上把它标红，一眼能看到
  echo "::error::$1"
  failed=1
}

check_shape() {
  local name="$1" value="$2"

  if [[ -z "$value" ]]; then
    fail "${name} 未配置或为空。注意 GitHub 允许保存「空值」Secret —— \
列表里能看到名字，值却是空的，请在 Secret 页面点铅笔图标重新粘贴并保存。"
    return
  fi

  if printf '%s' "$value" | LC_ALL=C grep -q '[^ -~]'; then
    fail "${name} 含非 ASCII 字符，几乎可以肯定填的是配置文档里的中文占位符。"
    return
  fi

  if printf '%s' "$value" | LC_ALL=C grep -q '[[:space:]]'; then
    fail "${name} 含空白或换行字符，几乎可以肯定复制时把配置行/命令一起带了进来。"
    return
  fi

  echo "  ${name} 形态正常（长度 ${#value}）"
}

base_url="${EMBEDDING_BASE_URL:-}"
model="${EMBEDDING_MODEL:-}"
api_key="${EMBEDDING_API_KEY:-}"

if [[ -z "$base_url" && -z "$model" && -z "$api_key" ]]; then
  echo "未配置 EMBEDDING_*：使用内置本地词法向量（合法状态，跳过校验）"
  exit 0
fi

echo "校验 embedding 配置形态（不打印值）："
check_shape EMBEDDING_BASE_URL "$base_url"
check_shape EMBEDDING_MODEL "$model"
check_shape EMBEDDING_API_KEY "$api_key"

# 长度只对 key 做（base_url 本身就比 key 长）
if [[ -n "$api_key" ]]; then
  if (( ${#api_key} < MIN_KEY_LEN || ${#api_key} > MAX_KEY_LEN )); then
    fail "EMBEDDING_API_KEY 长度 ${#api_key}，超出合理区间 ${MIN_KEY_LEN}~${MAX_KEY_LEN}（百炼约 35）。\
复制时很可能多选了旁边的文字，请回控制台用列表里的「复制」按钮重新复制。"
  fi
fi

exit "$failed"
