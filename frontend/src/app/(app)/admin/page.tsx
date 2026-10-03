"use client";

// 运营后台 · 订单管理与履约。
//
// 状态机（与中台一致）：
//   待发货 --ship--> 待揽收 --advance--> 运输中 --advance--> 待收货
// 「待揽收 / 运输中」可以推进履约，每次推进由后端追加一条物流轨迹。

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ChevronLeft,
  ChevronRight,
  Inbox,
  LoaderCircle,
  PackageCheck,
  RefreshCw,
  Search,
  Truck,
  X,
} from "lucide-react";
import { toast } from "sonner";

import { getToken } from "@/lib/auth";
import {
  ORDER_STATUSES,
  money,
  shop,
  type AdminOrderListItem,
  type AdminOrderList,
} from "@/lib/shop";

const PAGE_SIZE = 20;

const CARD_STYLE =
  "rounded-xl border border-slate-200 bg-white px-4 py-3 text-left transition";

const BTN_PRIMARY =
  "inline-flex items-center gap-1 rounded-lg bg-indigo-600 px-2.5 py-1.5 text-xs font-medium text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50";

const BTN_GHOST =
  "inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50";

const INPUT_CLASS =
  "rounded-lg border border-slate-200 px-2.5 py-1.5 text-sm text-slate-800 outline-none focus:border-indigo-400";

function formatTime(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

/** 状态徽标配色：与中台状态语义对应。 */
const STATUS_BADGE: Record<string, string> = {
  待付款: "bg-amber-50 text-amber-700",
  待发货: "bg-indigo-50 text-indigo-600",
  待揽收: "bg-sky-50 text-sky-700",
  运输中: "bg-blue-50 text-blue-700",
  待收货: "bg-violet-50 text-violet-700",
  已完成: "bg-emerald-50 text-emerald-700",
  已取消: "bg-slate-100 text-slate-500",
};

/** 操作按钮以中台状态文案为准，回退到英文状态码，兼容两种返回。 */
function isStatus(order: AdminOrderListItem, label: string, code: string): boolean {
  return order.status_desc === label || order.status === code;
}

/** 不能推进时的原因说明。 */
function advanceDisabledReason(order: AdminOrderListItem): string {
  if (isStatus(order, "待发货", "pending_ship")) return "待发货订单请先发货";
  if (isStatus(order, "待付款", "pending_pay")) return "待付款订单不能推进履约";
  if (isStatus(order, "已完成", "finished")) return "已完成，无需推进";
  if (isStatus(order, "已取消", "canceled")) return "已取消，无需推进";
  if (isStatus(order, "待收货", "pending_receive")) return "待收货，等待用户确认";
  return "当前状态不支持推进";
}

export default function AdminOrdersPage() {
  const router = useRouter();

  const [data, setData] = useState<AdminOrderList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [status, setStatus] = useState("");
  const [userId, setUserId] = useState("");
  const [userIdInput, setUserIdInput] = useState("");
  const [page, setPage] = useState(1);

  const [shipTarget, setShipTarget] = useState<AdminOrderListItem | null>(null);
  const [shipCompany, setShipCompany] = useState("顺丰速运");
  const [shipTracking, setShipTracking] = useState("");
  const [shipping, setShipping] = useState(false);
  const [busyOrderId, setBusyOrderId] = useState<string | null>(null);

  const load = useCallback(
    async (options: { silent?: boolean } = {}) => {
      if (!getToken()) {
        router.replace("/login");
        return;
      }
      if (!options.silent) setLoading(true);
      setError("");
      try {
        const result = await shop.admin.orders({
          status: status || undefined,
          user_id: userId || undefined,
          page,
          page_size: PAGE_SIZE,
        });
        setData(result);
      } catch (err) {
        const message = err instanceof Error ? err.message : "订单加载失败";
        setError(message);
        if (options.silent) toast.error(message);
      } finally {
        setLoading(false);
      }
    },
    [router, status, userId, page],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const orders = data?.orders ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const counts = data?.status_counts ?? {};

  function selectStatus(next?: string) {
    setStatus(next ?? "");
    setPage(1);
  }

  function applyUserFilter() {
    setUserId(userIdInput.trim());
    setPage(1);
  }

  function resetFilters() {
    setStatus("");
    setUserId("");
    setUserIdInput("");
    setPage(1);
  }

  function openShip(order: AdminOrderListItem) {
    setShipTarget(order);
    setShipCompany("顺丰速运");
    setShipTracking("");
  }

  async function submitShip() {
    if (!shipTarget) return;
    setShipping(true);
    try {
      const result = await shop.admin.ship(shipTarget.order_id, {
        company: shipCompany.trim(),
        tracking_number: shipTracking.trim(),
      });
      toast.success(
        `订单 ${result.order_id} 已发货：${result.status_desc}${
          result.tracking_number ? `（${result.tracking_number}）` : ""
        }`,
      );
      setShipTarget(null);
      await load({ silent: true });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "发货失败");
    } finally {
      setShipping(false);
    }
  }

  async function advance(order: AdminOrderListItem) {
    setBusyOrderId(order.order_id);
    try {
      const result = await shop.admin.advance(order.order_id);
      toast.success(
        `${result.status_desc}${result.latest_trace ? ` · ${result.latest_trace}` : ""}`,
      );
      await load({ silent: true });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "推进履约失败");
    } finally {
      setBusyOrderId(null);
    }
  }

  return (
    <div className="min-h-full">

      <main className="mx-auto max-w-7xl space-y-4 px-4 py-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-slate-800">订单管理与履约</h1>
            <p className="mt-0.5 text-xs text-slate-500">
              共 {total} 笔订单 · 第 {page} / {totalPages} 页 · 每页 {PAGE_SIZE} 笔
            </p>
          </div>
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className={BTN_GHOST}
          >
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
            刷新
          </button>
        </div>

        {/* 状态数量卡片：点击即筛选 */}
        <section className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
          <button
            type="button"
            onClick={() => selectStatus(undefined)}
            className={`${CARD_STYLE} ${
              status === "" ? "border-indigo-400 ring-1 ring-indigo-200" : "hover:border-slate-300"
            }`}
          >
            <div className="text-xs text-slate-500">全部</div>
            <div className="mt-1 text-lg font-semibold text-slate-800">
              {Object.values(counts).reduce((sum, value) => sum + value, 0)}
            </div>
          </button>
          {ORDER_STATUSES.map((name) => (
            <button
              key={name}
              type="button"
              onClick={() => selectStatus(name)}
              className={`${CARD_STYLE} ${
                status === name ? "border-indigo-400 ring-1 ring-indigo-200" : "hover:border-slate-300"
              }`}
            >
              <div className="text-xs text-slate-500">{name}</div>
              <div className="mt-1 text-lg font-semibold text-slate-800">
                {counts[name] ?? 0}
              </div>
            </button>
          ))}
        </section>

        {/* 筛选 */}
        <section className="flex flex-wrap items-end gap-2 rounded-xl border border-slate-200 bg-white px-4 py-3">
          <label className="flex flex-col gap-1 text-xs text-slate-500">
            状态
            <select
              value={status}
              onChange={(event) => selectStatus(event.target.value || undefined)}
              className={INPUT_CLASS}
            >
              <option value="">全部状态</option>
              {ORDER_STATUSES.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-xs text-slate-500">
            用户号
            <input
              value={userIdInput}
              onChange={(event) => setUserIdInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") applyUserFilter();
              }}
              placeholder="u1001"
              className={`${INPUT_CLASS} w-40`}
            />
          </label>

          <button type="button" onClick={applyUserFilter} className={BTN_PRIMARY}>
            <Search size={13} />
            查询
          </button>
          <button type="button" onClick={resetFilters} className={BTN_GHOST}>
            重置
          </button>
        </section>

        {/* 列表 */}
        <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1000px] text-sm">
              <thead className="bg-slate-50 text-xs text-slate-500">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">订单号</th>
                  <th className="px-3 py-2 text-left font-medium">用户</th>
                  <th className="px-3 py-2 text-left font-medium">商品</th>
                  <th className="px-3 py-2 text-right font-medium">件数</th>
                  <th className="px-3 py-2 text-right font-medium">实付</th>
                  <th className="px-3 py-2 text-left font-medium">状态</th>
                  <th className="px-3 py-2 text-left font-medium">物流</th>
                  <th className="px-3 py-2 text-left font-medium">创建时间</th>
                  <th className="px-3 py-2 text-left font-medium">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {loading && orders.length === 0 ? (
                  Array.from({ length: 3 }).map((_, index) => (
                    <tr key={index} className="animate-pulse">
                      <td colSpan={9} className="px-3 py-4">
                        <div className="h-4 w-full rounded bg-slate-100" />
                      </td>
                    </tr>
                  ))
                ) : orders.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="px-3 py-10 text-center text-slate-400">
                      <Inbox size={22} className="mx-auto mb-2 text-slate-300" />
                      没有符合条件的订单
                    </td>
                  </tr>
                ) : (
                  orders.map((order) => {
                    const canShip = isStatus(order, "待发货", "pending_ship");
                    const canAdvance =
                      isStatus(order, "待揽收", "pending_pickup") ||
                      isStatus(order, "运输中", "in_transit");
                    const busy = busyOrderId === order.order_id;
                    return (
                      <tr key={order.order_id} className="align-top hover:bg-slate-50/70">
                        <td className="px-3 py-2.5 font-medium text-slate-800">
                          {order.order_id}
                        </td>
                        <td className="px-3 py-2.5 text-slate-600">
                          <div className="font-medium text-slate-700">{order.user_id}</div>
                          <div className="text-xs text-slate-400">
                            {order.nickname || "—"}
                          </div>
                        </td>
                        <td className="max-w-[220px] px-3 py-2.5 text-slate-600">
                          <span className="line-clamp-2">{order.title || "—"}</span>
                        </td>
                        <td className="px-3 py-2.5 text-right text-slate-600">
                          {order.quantity}
                        </td>
                        <td className="px-3 py-2.5 text-right font-medium text-slate-800">
                          {money(order.pay_amount)}
                        </td>
                        <td className="px-3 py-2.5">
                          <span
                            className={`inline-block rounded-full px-2 py-0.5 text-xs ${
                              STATUS_BADGE[order.status_desc] ?? "bg-slate-100 text-slate-600"
                            }`}
                          >
                            {order.status_desc || order.status}
                          </span>
                        </td>
                        <td className="px-3 py-2.5 text-xs text-slate-500">
                          {order.logistics_company || order.tracking_number ? (
                            <>
                              <div>{order.logistics_company || "—"}</div>
                              <div className="text-slate-400">
                                {order.tracking_number || "—"}
                              </div>
                            </>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td className="whitespace-nowrap px-3 py-2.5 text-xs text-slate-500">
                          {formatTime(order.created_at)}
                        </td>
                        <td className="px-3 py-2.5">
                          <div className="flex flex-col items-start gap-1">
                            {canShip ? (
                              <button
                                type="button"
                                onClick={() => openShip(order)}
                                className={BTN_PRIMARY}
                              >
                                <Truck size={13} />
                                发货
                              </button>
                            ) : (
                              <button
                                type="button"
                                disabled
                                title="当前状态无需发货"
                                className={BTN_PRIMARY}
                              >
                                <Truck size={13} />
                                发货
                              </button>
                            )}

                            {canAdvance ? (
                              <button
                                type="button"
                                onClick={() => void advance(order)}
                                disabled={busy}
                                className={BTN_GHOST}
                              >
                                {busy ? (
                                  <LoaderCircle size={13} className="animate-spin" />
                                ) : (
                                  <PackageCheck size={13} />
                                )}
                                推进履约
                              </button>
                            ) : (
                              <button
                                type="button"
                                disabled
                                title={advanceDisabledReason(order)}
                                className={BTN_GHOST}
                              >
                                <PackageCheck size={13} />
                                推进履约
                              </button>
                            )}

                            {!canAdvance ? (
                              <span className="text-[11px] text-slate-400">
                                {advanceDisabledReason(order)}
                              </span>
                            ) : (
                              <span className="text-[11px] text-slate-400">
                                推进后自动追加物流轨迹
                              </span>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {/* 分页 */}
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 px-4 py-3 text-xs text-slate-500">
            <span>
              第 {page} 页 · 共 {totalPages} 页 · 合计 {total} 笔
            </span>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setPage((current) => Math.max(1, current - 1))}
                disabled={page <= 1 || loading}
                className={BTN_GHOST}
              >
                <ChevronLeft size={13} />
                上一页
              </button>
              <button
                type="button"
                onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
                disabled={page >= totalPages || loading}
                className={BTN_GHOST}
              >
                下一页
                <ChevronRight size={13} />
              </button>
            </div>
          </div>
        </section>

        {error ? (
          <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-600">
            {error}
            <button
              type="button"
              onClick={() => void load()}
              className="ml-3 underline hover:no-underline"
            >
              重试
            </button>
          </div>
        ) : null}
      </main>

      {/* 发货小表单 */}
      {shipTarget ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/30 px-4">
          <div className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-4 shadow-lg">
            <div className="flex items-start justify-between">
              <div>
                <h2 className="text-sm font-semibold text-slate-800">订单发货</h2>
                <p className="mt-0.5 text-xs text-slate-500">
                  {shipTarget.order_id} · {money(shipTarget.pay_amount)}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShipTarget(null)}
                className="rounded-lg p-1 text-slate-400 transition hover:bg-slate-100"
              >
                <X size={15} />
              </button>
            </div>

            <div className="mt-3 space-y-3">
              <label className="flex flex-col gap-1 text-xs text-slate-500">
                物流公司
                <input
                  value={shipCompany}
                  onChange={(event) => setShipCompany(event.target.value)}
                  placeholder="顺丰速运"
                  className={INPUT_CLASS}
                />
              </label>
              <label className="flex flex-col gap-1 text-xs text-slate-500">
                运单号（留空由系统自动生成）
                <input
                  value={shipTracking}
                  onChange={(event) => setShipTracking(event.target.value)}
                  placeholder="可留空"
                  className={INPUT_CLASS}
                />
              </label>
            </div>

            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShipTarget(null)}
                disabled={shipping}
                className={BTN_GHOST}
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => void submitShip()}
                disabled={shipping}
                className={BTN_PRIMARY}
              >
                {shipping ? (
                  <LoaderCircle size={13} className="animate-spin" />
                ) : (
                  <Truck size={13} />
                )}
                确认发货
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
