"use client";

// 商城页面的公共导航。深色星空主题留给登录/注册，交易页面沿用聊天页的浅色风格
// （bg-white + slate + indigo），保证「商城」这一块视觉上是一套。

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  Headset, LayoutDashboard, LogOut, Package, ShoppingCart, Store, User,
} from "lucide-react";
import { getUser, removeToken } from "@/lib/auth";
import { commerceUserId } from "@/lib/shop";

const LINKS = [
  { href: "/shop", label: "商城", icon: Store },
  { href: "/cart", label: "购物车", icon: ShoppingCart },
  { href: "/orders", label: "我的订单", icon: Package },
  { href: "/me", label: "我的", icon: User },
  { href: "/chat", label: "在线客服", icon: Headset },
  { href: "/admin", label: "运营后台", icon: LayoutDashboard },
];

export function ShopHeader({ cartCount }: { cartCount?: number }) {
  const pathname = usePathname();
  const router = useRouter();
  const [account, setAccount] = useState("");

  useEffect(() => {
    setAccount(commerceUserId(getUser()?.username));
  }, []);

  function logout() {
    removeToken();
    router.push("/login");
  }

  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
        <Link href="/shop" className="text-sm font-semibold text-slate-800">
          电商智能客服
        </Link>

        <nav className="flex flex-1 flex-wrap items-center gap-1">
          {LINKS.map(({ href, label, icon: Icon }) => {
            const active = pathname === href || pathname.startsWith(`${href}/`);
            return (
              <Link
                key={href}
                href={href}
                className={`flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-sm transition ${
                  active
                    ? "bg-indigo-50 text-indigo-600"
                    : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                <Icon size={15} />
                {label}
                {href === "/cart" && cartCount ? (
                  <span className="ml-0.5 rounded-full bg-indigo-500 px-1.5 text-[11px] text-white">
                    {cartCount}
                  </span>
                ) : null}
              </Link>
            );
          })}
        </nav>

        <div className="flex items-center gap-2 text-xs text-slate-500">
          <span className="rounded-full bg-slate-100 px-2 py-1">
            商城账号：{account || "…"}
          </span>
          <button
            onClick={logout}
            className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-sm text-slate-500 transition hover:bg-slate-100"
          >
            <LogOut size={14} />
            退出
          </button>
        </div>
      </div>
    </header>
  );
}
