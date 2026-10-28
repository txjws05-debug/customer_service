#!/bin/bash
# 一条命令按镜像 tag 回滚，并自检；失败自动切回原 tag。
#
# 为什么需要它：本机没有 CI，镜像只能从已有 tag 里选。出事时最怕的是
# 「记得有个好用的版本，但不记得是哪个 sha / 不知道该改哪一行」。
set -euo pipefail

APP_DIR=${APP_DIR:-/opt/customer_service}
cd "$APP_DIR"

tag=${1:-}
shift || true
services=${*:-"backend ecommerce"}

if [ -z "$tag" ]; then
    cat <<'EOF'
用法：rollback.sh <image_tag> [service...]
例：  rollback.sh b1d4aff645e411213f4ba75357778127f2421306
     rollback.sh 3874fa418358c093f31115e3f691c217b1f1ace3 backend

可用 tag（本机已有镜像）：
EOF
    docker images --format '{{.Tag}}' ghcr.io/txjws05-debug/customer-service-api | head -10 | sed 's/^/  /'
    exit 2
fi

for svc in $services; do
    case "$svc" in
        backend) repo=customer-service-api ;;
        ecommerce) repo=customer-service-ecommerce ;;
        frontend) repo=customer-service-web ;;
        *) echo "未知服务：$svc" >&2; exit 2 ;;
    esac
    if ! docker image inspect "ghcr.io/txjws05-debug/${repo}:${tag}" >/dev/null 2>&1; then
        echo "本机没有镜像 ${repo}:${tag}，无法回滚到它" >&2
        exit 1
    fi
done

old_tag=$(sed -n 's/^IMAGE_TAG=//p' deploy/.env | head -1)
echo "当前 IMAGE_TAG=$old_tag -> 目标 $tag（服务：$services）"
cp deploy/.env "deploy/.env.rollback.$(date +%Y%m%d-%H%M%S)"
sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=${tag}/" deploy/.env

rollback_again() {
    echo "自检失败，切回 $old_tag" >&2
    sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=${old_tag}/" deploy/.env
    docker compose -f docker-compose.prod.yml --env-file deploy/.env up -d --pull never --force-recreate $services >/dev/null 2>&1 || true
    exit 1
}

docker compose -f docker-compose.prod.yml --env-file deploy/.env up -d --pull never --force-recreate $services 2>&1 | tail -3

for i in $(seq 1 40); do
    ok=1
    for svc in $services; do
        name="cs-${svc}"
        st=$(docker inspect "$name" --format '{{.State.Health.Status}}' 2>/dev/null || echo none)
        [ "$st" = "healthy" ] || ok=0
    done
    [ "$ok" = "1" ] && break
    sleep 3
done

[ "$ok" = "1" ] || rollback_again

echo "回滚完成，容器健康。"
docker ps --format '{{.Names}}\t{{.Status}}' | grep -E "cs-(backend|ecommerce|frontend)"
cat <<'EOF'

注意：镜像回滚会把 docker cp 进去的热修代码一并还原。
如果那次修复已提交到 git，重新注入即可：
  git checkout <分支> && for f in ...; do docker cp ... ; done && docker restart cs-backend
EOF
