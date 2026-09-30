#!/usr/bin/env bash
# ============================================================
# 在服务器上探测 GHCR 镜像是否可用，判断该走「拉取」还是「本地构建」。
#
# 用法：bash deploy/check-registry.sh
# ============================================================
set -u

OWNER="${1:-txjws05-debug}"
REGISTRY="ghcr.io"

echo "=============================================="
echo " GHCR 镜像探测  ($(date '+%Y-%m-%d %H:%M:%S'))"
echo "=============================================="
printf "%-14s %-8s %s\n" "PACKAGE" "HTTP" "含义"
echo "----------------------------------------------"

overall="unknown"
for pkg in customer-service-api customer-service-ecommerce customer-service-web; do
  code=$(curl -s -o /dev/null -w "%{http_code}" \
    "https://${REGISTRY}/v2/${OWNER}/${pkg}/manifests/latest" 2>/dev/null || echo "000")

  case "$code" in
    200) meaning="已公开，可直接拉取" ;;
    401) meaning="需认证 —— 匿名请求一律 401，无法据此判断包是否存在" ;;
    403) meaning="无权限" ;;
    404) meaning="确认不存在（CI 未成功推送过）" ;;
    000) meaning="网络不可达（检查 DNS / 出网）" ;;
    *)   meaning="未知状态" ;;
  esac

  printf "%-14s %-8s %s\n" "$pkg" "$code" "$meaning"

  # 只要有一个 404，说明 CI 从未成功推送，本地构建是唯一出路
  if [ "$code" = "404" ]; then overall="missing"; fi
  if [ "$code" = "401" ] && [ "$overall" != "missing" ]; then overall="private"; fi
  if [ "$code" = "200" ] && [ "$overall" = "unknown" ]; then overall="public"; fi
done

echo "----------------------------------------------"
case "$overall" in
  public)
    echo "结论：镜像已公开，可直接拉取部署："
    echo "  docker compose -f docker-compose.prod.yml --env-file deploy/.env up -d"
    ;;
  private)
    echo "结论：匿名请求返回 401，无法判断包究竟「存在但私有」还是「根本不存在」"
    echo "      （GHCR 对匿名请求一律返回 401，不区分两者）。"
    echo "先用带 read:packages 的 PAT 复核真实存在性："
    echo "  docker login ghcr.io -u ${OWNER} -p <read:packages 的 PAT>"
    echo "  docker manifest inspect ghcr.io/${OWNER}/customer-service-api:latest >/dev/null \\"
    echo "    && echo '镜像存在' || echo '镜像不存在'"
    echo "  A) 若存在：在 GitHub → Packages 把三个包设为 public（推荐，一次搞定）"
    echo "  B) 若不存在：说明 CI 的 build 阶段从未成功推送，先修 CI"
    echo "完成后执行："
    echo "  docker compose -f docker-compose.prod.yml --env-file deploy/.env up -d"
    ;;
  missing)
    echo "结论：GHCR 上没有镜像，说明 CI 的 build 阶段未成功。"
    echo "请先看 Actions 结果：https://github.com/${OWNER}/customer_service/actions"
    echo "若要临时在服务器本地构建（内存紧张，可能 OOM）："
    echo "  COMPOSE_PARALLEL_LIMIT=1 docker compose --env-file deploy/.env up -d --build"
    ;;
  *)
    echo "结论：无法确定。请检查服务器出网是否正常。"
    ;;
esac
echo "=============================================="
