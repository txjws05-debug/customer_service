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
    ];
  },
};

export default nextConfig;
