# ===== 前端镜像：Next.js 16 standalone =====
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# ⚠️ 关键：构建期把 API 基址固定为「空字符串」，
# 前端就会用相对路径请求 /api/*，由反向代理转发到后端容器。
# 若不设置，lib/api.ts 会回退到 http://127.0.0.1:18082 —— 那是「浏览器所在机器」，
# 线上会直接连接失败。
ARG NEXT_PUBLIC_API_BASE=""
ENV NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE}
ENV NEXT_TELEMETRY_DISABLED=1

RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    TZ=Asia/Shanghai

# standalone 产物：自带最小 node_modules，无需装依赖
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
# public 目录若不存在，下面的 COPY 会因通配符而跳过
COPY --from=builder /app/public* ./public/

EXPOSE 3000
CMD ["node", "server.js"]
