#!/usr/bin/env bash
# ============================================================
# 把 CI 传进来的配置（来自 GitHub Secrets）落成服务器上的 env 变量。
#
# 目的：让「改密钥 / 换 embedding 模型」也走 CI/CD —— 只改 GitHub Secret
# 再重跑流水线即可，不需要登录服务器手改 deploy/backend.env。
#
# 约定：
#   - 变量为空        → 跳过，不动服务器上已有的值
#   - 变量为单个 "-"  → 删除该行（用于回退，例如去掉 EMBEDDING_* 退回本地向量）
#   - 只有内容真的变了才会写文件，并置一个标记让部署流程补一次容器重建
#
# 密钥安全：sed 只用于按「变量名」删行，密钥值一律经 printf 写入，
# 因此值里出现 $ & | / 等特殊字符也不会被解释。
#
# 想再多管一个变量：下面加一行 apply XXX，并在 workflow 的 envs/env 里带上它。
# ============================================================
set -euo pipefail

cd "$(dirname "$0")/.."

ENV_FILE="deploy/backend.env"
CHANGED_FLAG="/tmp/cs-env-changed"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "!! 缺少 $ENV_FILE，无法下发配置" >&2
  exit 1
fi

changed=0

apply() {
  local key="$1"
  local value="${!key:-}"

  # 没传值 = 不管理这一项
  if [[ -z "$value" ]]; then
    return 0
  fi

  # 传了 "-" = 明确要求清除该项
  if [[ "$value" == "-" ]]; then
    if grep -q "^${key}=" "$ENV_FILE"; then
      sed -i "/^${key}=/d" "$ENV_FILE"
      echo "  [env] ${key} 已清除"
      changed=1
    fi
    return 0
  fi

  # 已经一致就不动文件，避免每次部署都白重建一次容器
  if grep -qxF "${key}=${value}" "$ENV_FILE"; then
    echo "  [env] ${key} 无变化"
    return 0
  fi

  sed -i "/^${key}=/d" "$ENV_FILE"
  printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  echo "  [env] ${key} 已更新"
  changed=1
}

apply EMBEDDING_BASE_URL
apply EMBEDDING_MODEL
apply EMBEDDING_API_KEY
apply EMBEDDING_DIM

if [[ "$changed" -eq 1 ]]; then
  touch "$CHANGED_FLAG"
  echo "==> 配置有变化，部署后会重建 backend 容器"
else
  echo "==> 配置无变化"
fi
