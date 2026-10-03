import { AppShell } from "@/components/AppShell";

// 应用外壳统一在这里挂：商城 / 购物车 / 订单 / 我的 / 在线客服 / 运营后台
// 都走这一层，页面自身只关心内容（顶栏标题由外壳按路径推断）。
// 用路由组 (app) 是为了让 URL 保持 /shop、/orders… 不变，同时只写一个布局。
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
