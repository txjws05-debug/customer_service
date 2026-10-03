#!/usr/bin/env bash
# ============================================================
# 判断这次 push 改了哪些组件，决定要重建哪几个镜像。
#
# 输入：stdin 一行一个改动文件路径（通常来自 git diff --name-only）
# 输出：GITHUB_OUTPUT 兼容的 key=value 行（直接 >> "$GITHUB_OUTPUT" 即可），
#       同时打到 stdout，方便本地直接跑。
#
# 为什么要它：一次 push 只改前端时，没必要重建后端和中台镜像 ——
# 三个镜像各自要构建 + 服务器要拉，白白多花几分钟。
# 未改动的组件改走「只复制 manifest」的复用路径（不传层数据）。
#
# 用法：
#   git diff --name-only <before> <sha> | bash deploy/detect-changes.sh
#   bash deploy/detect-changes.sh < 文件列表.txt
# ============================================================
set -uo pipefail

api=false
ecommerce=false
web=false
deploy_only=false

while IFS= read -r file; do
  [ -z "$file" ] && continue
  case "$file" in
    # 客服 Agent 镜像：Dockerfile + ws + 依赖清单
    Dockerfile|ws/*|pyproject.toml|uv.lock|.env.example) api=true ;;
    # 电商中台镜像
    ecommerce-service-backend/*) ecommerce=true ;;
    # 前端镜像
    frontend/*) web=true ;;
  esac
  case "$file" in
    # 只影响「怎么部署」，不影响镜像内容：镜像可以复用，但需要重新部署
    deploy/*|docker-compose*.yml|.github/workflows/*) deploy_only=true ;;
  esac
done

images_csv=","
[ "$api" = true ] && images_csv="${images_csv}api,"
[ "$ecommerce" = true ] && images_csv="${images_csv}ecommerce,"
[ "$web" = true ] && images_csv="${images_csv}web,"

deploy_needed=false
if [ "$api" = true ] || [ "$ecommerce" = true ] || [ "$web" = true ] || [ "$deploy_only" = true ]; then
  deploy_needed=true
fi

cat <<EOF
api=${api}
ecommerce=${ecommerce}
web=${web}
images_csv=${images_csv}
deploy_needed=${deploy_needed}
EOF
