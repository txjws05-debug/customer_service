"use client";

// 我的订单列表：状态筛选 + 订单卡片 + 待评价徽标。
// 沿用聊天页的浅色风格（白底 / slate 文字 / indigo 主色）。

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { ChevronRight, Loader2, Package, Star } from "lucide-react";
import { toast } from "sonner";

import { getToken, getUser } from "@/lib/auth";
import {
  ORDER_STATUSES,
  commerceUserId,
  money,
  shop,
  type OrderListItem,
} from "@/lib/shop";

const ALL = "全部";

const TABS: readonly string[] = [ALL, ...ORDER_STATUSES];

/** 不同订单状态用不同颜色，便于一眼扫出待办。 */
function statusBadgeClass(status: string): string {
  if (status === "待付款") return "bg-amber-50 text-amber-600 border-amber-200";
  if (
    status === "待发货" ||
    status === "待揽收" ||
    status === "运输中" ||
    status === "待收货"
  ) {
    return "bg-blue-50 text-blue-600 border-blue-200";
  }
  if (status === "已完成") {
    return "bg-emerald-50 text-emerald-600 border-emerald-200";
  }
  return "bg-slate-100 text-slate-500 border-slate-200";
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`rounded-full border px-2 py-0.5 text-xs ${statusBadgeClass(status)}`}
    >
      {status}
    </span>
  );
}

function OrderCard({
  order,
  pendingReview,
}: {
  order: OrderListItem;
  pendingReview: boolean;
}) {
  return (
    <Link
      href={`/orders/${order.order_id}`}
      className="block rounded-xl border border-slate-200 bg-white transition hover:border-indigo-300 hover:shadow-sm"
    >
      <div className="flex items-center justify-between gap-2 border-b border-slate-100 px-4 py-2.5">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="truncate text-sm font-medium text-slate-700">
            订单号 {order.order_id}
          </span>
          {pendingReview && (
            <span className="flex items-center gap-0.5 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11px] text-amber-600">
              <Star size={11} />
              待评价
            </span>
          )}
        </div>
        <StatusBadge status={order.status} />
      </div>

      <div className="flex items-center gap-3 px-4 py-3">
        {order.cover_url ? (
          <Image
            src={order.cover_url}
            alt={order.title}
            width={64}
            height={64}
            unoptimized
            className="h-16 w-16 flex-none rounded-lg border border-slate-200 object-cover"
          />
        ) : (
          <div className="flex h-16 w-16 flex-none items-center justify-center rounded-lg bg-slate-100 text-slate-400">
            <Package size={22} />
          </div>
        )}

        <div className="min-w-0 flex-1">
          <p className="truncate text-sm text-slate-800">{order.title}</p>
          <p className="mt-1 text-xs text-slate-500">
            共 {order.quantity} 件 ·{" "}
            {new Date(order.created_at).toLocaleString("zh-CN")}
          </p>
        </div>

        <div className="flex flex-none items-center gap-1">
          <span className="text-sm font-semibold text-slate-800">
            {money(order.pay_amount)}
          </span>
          <ChevronRight size={16} className="text-slate-300" />
        </div>
      </div>
    </Link>
  );
}

export default function OrdersPage() {
  const router = useRouter();
  const [user, setUser] = useState<string | null>(null);
  const [status, setStatus] = useState<string>(ALL);
  const [orders, setOrders] = useState<OrderListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [pending, setPending] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // 登录校验 + 初始化筛选状态（支持 /orders?status=待付款 直接进入）
  //
  // 这里刻意不用 useSearchParams：它在 App Router 下需要一个 Suspense 边界，
  // 否则 `next build` 会在预渲染阶段直接失败
  // （useSearchParams() should be wrapped in a suspense boundary）。
  // 直接读 window.location.search 效果一样，且不需要额外的组件拆分。
  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    const account = commerceUserId(getUser()?.username);
    setUser(account);
    const fromQuery = new URLSearchParams(window.location.search).get("status");
    if (fromQuery && TABS.includes(fromQuery)) setStatus(fromQuery);
  }, [router]);

  const load = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    setError("");
    try {
      const [list, pend] = await Promise.all([
        shop.orders(user, status === ALL ? undefined : status),
        shop.pendingReviews(user),
      ]);
      setOrders(list.orders ?? []);
      setTotal(list.total);
      setPending(pend.order_ids ?? []);
    } catch (err) {
      const message = (err as Error).message || "订单加载失败";
      setError(message);
      setOrders([]);
      setTotal(0);
      toast.error(message);
    } finally {
      setLoading(false);
    }
  }, [user, status]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="min-h-full">

      <main className="mx-auto max-w-4xl px-4 py-6">
        <div className="mb-4 flex items-baseline justify-between">
          <h1 className="text-lg font-semibold text-slate-800">我的订单</h1>
          {!loading && !error && (
            <span className="text-xs text-slate-500">共 {total} 笔</span>
          )}
        </div>

        {/* 状态筛选 */}
        <div className="mb-4 flex flex-wrap gap-2">
          {TABS.map((tab) => (
            <button
              key={tab}
              onClick={() => setStatus(tab)}
              className={`rounded-full border px-3 py-1.5 text-sm transition ${
                status === tab
                  ? "border-indigo-500 bg-indigo-500 text-white"
                  : "border-slate-200 bg-white text-slate-600 hover:border-indigo-300 hover:text-indigo-600"
              }`}
            >
              {tab}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="flex items-center justify-center gap-2 py-20 text-slate-400">
            <Loader2 className="animate-spin" size={18} />
            <span className="text-sm">加载中…</span>
          </div>
        ) : error ? (
          <div className="rounded-xl border border-slate-200 bg-white p-10 text-center">
            <p className="text-sm text-red-500">{error}</p>
            <button
              onClick={() => void load()}
              className="mt-3 rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-600 transition hover:border-indigo-300 hover:text-indigo-600"
            >
              重新加载
            </button>
          </div>
        ) : orders.length === 0 ? (
          <div className="rounded-xl border border-slate-200 bg-white p-12 text-center">
            <Package size={40} className="mx-auto mb-3 text-slate-300" />
            <p className="text-sm text-slate-500">还没有订单，去商城逛逛</p>
            <Link
              href="/shop"
              className="mt-4 inline-block rounded-lg bg-indigo-500 px-4 py-2 text-sm text-white transition hover:bg-indigo-600"
            >
              去商城逛逛
            </Link>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {orders.map((order) => (
              <OrderCard
                key={order.order_id}
                order={order}
                pendingReview={pending.includes(order.order_id)}
              />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
