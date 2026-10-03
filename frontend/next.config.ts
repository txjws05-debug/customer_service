import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // 本地开发走同源：Next dev server 把 /api/* 代理到 FastAPI 后端（18082），
  // 前端代码里没有跨域、没有硬编码 host，与生产环境反向代理行为一致。
  async rewrites() {
    const rewrites = [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:18082/api/:path*",
      },
    ];

    // /shop 的代理只在本地开发生效：生产环境由 Caddy 直接把 /shop/* 转发给中台
    // （见 deploy/Caddyfile）。如果生产也带上这条 rewrite，一旦 Caddy 没把 /shop
    // 转走，请求就会落到容器内的 127.0.0.1:18081（那里没有服务）→ 前端只看到
    // 一个 500，完全看不出是路由问题。去掉后同一场景会得到诚实的 404。
    if (process.env.NODE_ENV === "development") {
      rewrites.push({
        source: "/shop/:path*",
        destination: "http://127.0.0.1:18081/shop/:path*",
      });
    }

    return rewrites;
  },
};

export default nextConfig;
