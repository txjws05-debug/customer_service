"use client";

// 应用外壳：左侧导航 + 顶栏（页面标题）+ 内容区。
//
// 规范对齐点：
//   · h-screen + overflow-hidden 的外层，只有内容区自己滚动；
//   · 顶栏 h-14、border-line、bg-canvas，标题用 text-body；
//   · 内容区居中限宽（聊天页例外：它要占满高度、自己管滚动）；
//   · 移动端把左侧导航变成抽屉（背景遮罩 + 240px 面板）。

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { LogOut, Menu } from "lucide-react";
import { Sidebar } from "./Sidebar";
import { getToken, getUser, removeToken } from "@/lib/auth";
import { commerceUserId } from "@/lib/shop";

// 顶栏标题按路径取，页面本身不需要再声明标题
const TITLES: Record<string, string> = {
  "/mall": "商城",
  "/cart": "购物车",
  "/orders": "我的订单",
  "/me": "优惠券与积分",
  "/chat": "在线客服",
  "/admin": "订单与履约",
  "/admin/after-sales": "售后审核台",
  "/admin/stats": "经营看板",
  "/admin/coupons": "优惠券管理",
};

function titleFor(pathname: string): string {
  if (TITLES[pathname]) return TITLES[pathname];
  if (pathname.startsWith("/orders/")) return "订单详情";
  if (pathname.startsWith("/mall/")) return "商品详情";
  return "";
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  // token / 账号存在 localStorage：服务端渲染时读不到，直接渲染会在客户端
  // 首次渲染时产生不一致（hydration mismatch）。等挂载后再渲染外壳。
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => setHydrated(true), []);

  useEffect(() => {
    if (hydrated && !getToken()) {
      router.replace("/login");
    }
  }, [hydrated, router]);

  // 路由变化时收起移动端抽屉
  const [prevPath, setPrevPath] = useState(pathname);
  if (prevPath !== pathname) {
    setPrevPath(pathname);
    setOpen(false);
  }

  if (!hydrated) {
    return (
      <div className="flex h-screen items-center justify-center bg-subtle">
        <div className="flex flex-col items-center gap-3">
          <div className="size-8 animate-spin rounded-full border-2 border-indigo-600 border-t-transparent" />
          <p className="text-sm text-faint">加载中…</p>
        </div>
      </div>
    );
  }

  const isChat = pathname.startsWith("/chat");
  const account = commerceUserId(getUser()?.username);

  return (
    <div className="flex h-screen overflow-hidden bg-subtle">
      {/* 桌面端固定侧栏 */}
      <div className="hidden lg:block">
        <Sidebar />
      </div>

      {/* 移动端抽屉 */}
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div
            className="absolute inset-0 bg-black/40 backdrop-blur-sm"
            onClick={() => setOpen(false)}
          />
          <div className="absolute left-0 top-0 z-50 h-full w-[240px] shadow-xl">
            <Sidebar onCloseMobile={() => setOpen(false)} />
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-line bg-canvas px-4">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setOpen(true)}
              className="-ml-1 rounded-lg p-1.5 text-muted transition hover:bg-muted-surface lg:hidden"
            >
              <Menu className="size-5" />
            </button>
            <h2 className="text-sm font-medium text-body">{titleFor(pathname)}</h2>
          </div>

          <div className="flex items-center gap-2">
            <span className="hidden rounded-full bg-muted-surface px-2.5 py-1 text-xs text-muted sm:inline">
              商城账号：{account}
            </span>
            <button
              onClick={() => {
                removeToken();
                router.replace("/login");
              }}
              className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-sm text-muted transition hover:bg-muted-surface"
            >
              <LogOut size={15} />
              <span className="hidden sm:inline">退出</span>
            </button>
          </div>
        </header>

        {isChat ? (
          // 聊天页要占满高度并自己滚消息区，不能再套一层滚动容器
          <main className="flex min-h-0 flex-1 flex-col overflow-hidden">
            {children}
          </main>
        ) : (
          // 页面各自带 mx-auto max-w-* 容器，这里只负责滚动，不再套一层内边距
          <main className="flex-1 overflow-y-auto">{children}</main>
        )}
      </div>
    </div>
  );
}
