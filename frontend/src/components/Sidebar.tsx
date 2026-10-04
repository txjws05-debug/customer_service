"use client";

// 左侧导航（固定 240px，移动端变成抽屉）。
//
// 规范来源：设计规范里「语义色 + 左侧导航 + 顶栏标题」那一套 ——
// 导航项只写角色色（text-muted / bg-brand-soft / text-brand-ink），
// 选中态与悬停态由 token 决定，组件本身不关心具体色号。

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Headset,
  LayoutDashboard,
  Package,
  ShoppingCart,
  Store,
  User,
  X,
  type LucideIcon,
} from "lucide-react";
import { getUser } from "@/lib/auth";
import { commerceUserId } from "@/lib/shop";

interface NavItem {
  name: string;
  href: string;
  icon: LucideIcon;
  /** 精确匹配（否则 /mall 会一直高亮，因为所有页面都以它开头） */
  exact?: boolean;
}

interface NavSection {
  name?: string;
  items: NavItem[];
}

const NAV_SECTIONS: NavSection[] = [
  {
    items: [
      { name: "商城", href: "/mall", icon: Store },
      { name: "购物车", href: "/cart", icon: ShoppingCart },
    ],
  },
  {
    name: "我的",
    items: [
      { name: "我的订单", href: "/orders", icon: Package },
      { name: "优惠券与积分", href: "/me", icon: User },
    ],
  },
  {
    name: "服务",
    items: [
      { name: "在线客服", href: "/chat", icon: Headset },
    ],
  },
  {
    name: "运营",
    items: [
      { name: "订单与履约", href: "/admin", icon: LayoutDashboard, exact: true },
      { name: "售后审核台", href: "/admin/after-sales", icon: Package },
      { name: "经营看板", href: "/admin/stats", icon: LayoutDashboard },
      { name: "优惠券管理", href: "/admin/coupons", icon: Store },
    ],
  },
];

export function Sidebar({ onCloseMobile }: { onCloseMobile?: () => void }) {
  const pathname = usePathname();
  const account = commerceUserId(getUser()?.username);

  const isActive = (item: NavItem) =>
    item.exact ? pathname === item.href : pathname === item.href ||
      pathname.startsWith(`${item.href}/`);

  return (
    <aside className="flex h-full w-[240px] shrink-0 flex-col border-r border-line bg-canvas">
      {/* 品牌 */}
      <div className="flex h-14 items-center justify-between border-b border-line px-4">
        <div className="flex items-center gap-2.5">
          <div className="flex size-8 items-center justify-center rounded-lg bg-indigo-600">
            <Headset className="size-4 text-white" />
          </div>
          <span className="text-lg font-bold text-strong">智能客服</span>
        </div>
        {onCloseMobile && (
          <button
            onClick={onCloseMobile}
            className="rounded-lg p-1.5 text-faint transition hover:bg-muted-surface lg:hidden"
          >
            <X className="size-4" />
          </button>
        )}
      </div>

      {/* 导航 */}
      <nav className="flex-1 overflow-y-auto px-3 py-4">
        {NAV_SECTIONS.map((section, index) => (
          <div key={section.name ?? index} className={index > 0 ? "mt-6" : ""}>
            {section.name && (
              <p className="mb-1.5 px-3 text-xs font-medium uppercase tracking-wider text-faint">
                {section.name}
              </p>
            )}
            <div className="space-y-0.5">
              {section.items.map((item) => {
                const active = isActive(item);
                const Icon = item.icon;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={() => onCloseMobile?.()}
                    className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                      active
                        ? "bg-brand-soft text-brand-ink"
                        : "text-muted hover:bg-muted-surface hover:text-strong"
                    }`}
                  >
                    <Icon className={`size-4 shrink-0 ${active ? "text-brand-ink" : ""}`} />
                    <span>{item.name}</span>
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* 底部：当前商城账号 */}
      <div className="space-y-2 border-t border-line px-3 py-3">
        <p className="px-3 text-xs text-faint">商城账号</p>
        <p className="px-3 text-sm font-medium text-body">{account}</p>
      </div>
    </aside>
  );
}
