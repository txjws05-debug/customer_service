import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // 本地开发走同源：Next dev server 把 /api/* 代理到 FastAPI 后端（18082），
  // 前端代码里没有跨域、没有硬编码 host，与生产环境反向代理行为一致。
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:18082/api/:path*",
      },
      {
        // 电商中台交易域（商城/购物车/订单/运营后台）。
        // 生产环境由 Caddy 把 /shop/* 直接转发到中台（见 deploy/Caddyfile），
        // 这条 rewrite 只在本地开发生效，保证前端始终用相对路径、不跨域。
        source: "/shop/:path*",
        destination: "http://127.0.0.1:18081/shop/:path*",
      },
    ];
  },
};

export default nextConfig;
