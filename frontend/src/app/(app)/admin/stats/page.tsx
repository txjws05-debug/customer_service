"use client";

// 运营后台 · 经营看板。
// 订单状态分布用纯 CSS 横向条形（不引入图表库），低库存可直接调整绝对库存值。

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  BadgePercent,
  Boxes,
  CircleDollarSign,
  Coins,
  Inbox,
  LoaderCircle,
  RefreshCw,
  Ticket,
  TrendingUp,
  TriangleAlert,
  Users,
} from "lucide-react";
import { toast } from "sonner";

import { getToken } from "@/lib/auth";
import { ORDER_STATUSES, money, shop, type Stats } from "@/lib/shop";

const BTN_PRIMARY =
  "inline-flex items-center gap-1 rounded-lg bg-indigo-600 px-2.5 py-1.5 text-xs font-medium text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50";

const BTN_GHOST =
  "inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50";

const INPUT_CLASS =
  "rounded-lg border border-slate-200 px-2.5 py-1.5 text-sm text-slate-800 outline-none focus:border-indigo-400";

const BAR_COLOR: Record<string, string> = {
  待付款: "bg-amber-400",
  待发货: "bg-indigo-500",
  待揽收: "bg-sky-400",
  运输中: "bg-blue-500",
  待收货: "bg-violet-500",
  已完成: "bg-emerald-500",
  已取消: "bg-slate-400",
};

/** 售后率是后端给的百分比数字字符串（如 "8.33"），只做展示格式化。 */
function formatPercent(value?: string | null): string {
  if (value === undefined || value === null || value === "") return "0.00%";
  const number = Number(value);
  if (Number.isNaN(number)) return `${value}%`;
  return `${number.toFixed(2)}%`;
}

function Card({
  label,
  value,
  icon,
  hint,
}: {
  label: string;
  value: string | number;
  icon: React.ReactNode;
  hint?: string;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
      <div className="flex items-center gap-1.5 text-xs text-slate-500">
        {icon}
        {label}
      </div>
      <div className="mt-1.5 text-xl font-semibold text-slate-800">{value}</div>
      {hint ? <div className="mt-0.5 text-[11px] text-slate-400">{hint}</div> : null}
    </div>
  );
}

export default function AdminStatsPage() {
  const router = useRouter();

  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [stockInputs, setStockInputs] = useState<Record<string, string>>({});
  const [busySku, setBusySku] = useState<string | null>(null);

  const load = useCallback(
    async (options: { silent?: boolean } = {}) => {
      if (!getToken()) {
        router.replace("/login");
        return;
      }
      if (!options.silent) setLoading(true);
      setError("");
      try {
        const result = await shop.admin.stats();
        setStats(result);
        setStockInputs((current) => {
          const next: Record<string, string> = {};
          (result.low_stock ?? []).forEach((item) => {
            next[item.sku_code] = current[item.sku_code] ?? String(item.stock);
          });
          return next;
        });
      } catch (err) {
        const message = err instanceof Error ? err.message : "看板数据加载失败";
        setError(message);
        if (options.silent) toast.error(message);
      } finally {
        setLoading(false);
      }
    },
    [router],
  );

  useEffect(() => {
    void load();
  }, [load]);

  async function saveStock(skuCode: string, currentStock: number) {
    const raw = (stockInputs[skuCode] ?? "").trim();
    if (!/^\d+$/.test(raw)) {
      toast.error("请输入 0 或正整数库存");
      return;
    }
    const next = Number(raw);
    if (!Number.isSafeInteger(next)) {
      toast.error("库存数值过大");
      return;
    }
    if (next === currentStock) {
      toast.error("库存没有变化。");
      return;
    }
    setBusySku(skuCode);
    try {
      const result = await shop.admin.updateStock(skuCode, next, "运营调整");
      const delta = result.change >= 0 ? `+${result.change}` : `${result.change}`;
      toast.success(
        `${result.sku_code} 库存 ${delta}，现为 ${result.stock}（${result.status}）`,
      );
      await load({ silent: true });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "库存调整失败");
    } finally {
      setBusySku(null);
    }
  }

  const statusCounts = stats?.status_counts ?? {};
  const statusTotal = ORDER_STATUSES.reduce(
    (sum, name) => sum + (statusCounts[name] ?? 0),
    0,
  );
  const lowStock = stats?.low_stock ?? [];
  const topProducts = stats?.top_products ?? [];

  return (
    <div className="min-h-full">

      <main className="mx-auto max-w-7xl space-y-4 px-4 py-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-slate-800">经营看板</h1>
            <p className="mt-0.5 text-xs text-slate-500">
              交易、售后、营销与库存的整体视图
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

        {loading && !stats ? (
          <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
            {Array.from({ length: 12 }).map((_, index) => (
              <div
                key={index}
                className="h-[86px] animate-pulse rounded-xl border border-slate-200 bg-white"
              />
            ))}
          </div>
        ) : !stats ? (
          <div className="rounded-xl border border-slate-200 bg-white px-4 py-10 text-center text-slate-400">
            <Inbox size={22} className="mx-auto mb-2 text-slate-300" />
            暂无看板数据
          </div>
        ) : (
          <>
            {/* 指标卡 */}
            <section className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
              <Card
                label="GMV"
                value={money(stats.gmv)}
                icon={<CircleDollarSign size={13} className="text-indigo-500" />}
              />
              <Card
                label="已付款订单"
                value={stats.paid_order_count}
                icon={<TrendingUp size={13} className="text-indigo-500" />}
              />
              <Card
                label="已完成订单"
                value={stats.finished_order_count}
                icon={<TrendingUp size={13} className="text-emerald-500" />}
              />
              <Card
                label="已取消订单"
                value={stats.canceled_order_count}
                icon={<TrendingUp size={13} className="text-slate-400" />}
              />
              <Card
                label="售后单数"
                value={stats.after_sale_count}
                icon={<TriangleAlert size={13} className="text-amber-500" />}
              />
              <Card
                label="售后率"
                value={formatPercent(stats.after_sale_rate)}
                icon={<TriangleAlert size={13} className="text-amber-500" />}
                hint="售后单数 / 已付款订单"
              />
              <Card
                label="发放券数"
                value={stats.coupon_issued}
                icon={<Ticket size={13} className="text-indigo-500" />}
              />
              <Card
                label="核销券数"
                value={stats.coupon_used}
                icon={<BadgePercent size={13} className="text-indigo-500" />}
              />
              <Card
                label="发放积分"
                value={stats.points_issued}
                icon={<Coins size={13} className="text-amber-500" />}
              />
              <Card
                label="用户数"
                value={stats.user_count}
                icon={<Users size={13} className="text-indigo-500" />}
              />
              <Card
                label="在售商品数"
                value={stats.product_count}
                icon={<Boxes size={13} className="text-indigo-500" />}
              />
              <Card
                label="低库存规格"
                value={lowStock.length}
                icon={<TriangleAlert size={13} className="text-rose-500" />}
                hint="库存 ≤ 10"
              />
            </section>

            <div className="grid gap-4 lg:grid-cols-2">
              {/* 订单状态分布 */}
              <section className="rounded-xl border border-slate-200 bg-white p-4">
                <h2 className="text-sm font-semibold text-slate-800">订单状态分布</h2>
                <p className="mt-0.5 text-xs text-slate-500">
                  共 {statusTotal} 笔订单（不含未知状态）
                </p>
                <div className="mt-3 space-y-2.5">
                  {ORDER_STATUSES.map((name) => {
                    const count = statusCounts[name] ?? 0;
                    const ratio = statusTotal > 0 ? count / statusTotal : 0;
                    const percent = (ratio * 100).toFixed(1);
                    return (
                      <div key={name}>
                        <div className="flex justify-between text-xs text-slate-600">
                          <span>{name}</span>
                          <span className="text-slate-400">
                            {count} 笔 · {percent}%
                          </span>
                        </div>
                        <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-slate-100">
                          <div
                            className={`h-full rounded-full ${BAR_COLOR[name] ?? "bg-indigo-400"}`}
                            style={{ width: `${ratio * 100}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>

              {/* 热销榜 */}
              <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
                <div className="border-b border-slate-100 px-4 py-3">
                  <h2 className="text-sm font-semibold text-slate-800">热销榜</h2>
                  <p className="mt-0.5 text-xs text-slate-500">按销量排序</p>
                </div>
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-xs text-slate-500">
                    <tr>
                      <th className="px-4 py-2 text-left font-medium">商品</th>
                      <th className="px-4 py-2 text-right font-medium">销量</th>
                      <th className="px-4 py-2 text-right font-medium">销售额</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {topProducts.length === 0 ? (
                      <tr>
                        <td colSpan={3} className="px-4 py-8 text-center text-slate-400">
                          暂无销售数据
                        </td>
                      </tr>
                    ) : (
                      topProducts.map((item, index) => (
                        <tr key={item.product_id} className="hover:bg-slate-50/70">
                          <td className="px-4 py-2.5 text-slate-700">
                            <span className="mr-1.5 text-xs text-slate-400">
                              {index + 1}
                            </span>
                            {item.title}
                          </td>
                          <td className="px-4 py-2.5 text-right text-slate-600">
                            {item.quantity}
                          </td>
                          <td className="px-4 py-2.5 text-right font-medium text-slate-800">
                            {money(item.amount)}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </section>
            </div>

            {/* 低库存预警 */}
            <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-3">
                <div>
                  <h2 className="flex items-center gap-1.5 text-sm font-semibold text-slate-800">
                    <TriangleAlert size={15} className="text-rose-500" />
                    低库存预警
                  </h2>
                  <p className="mt-0.5 text-xs text-slate-500">
                    库存 ≤ 10 的规格，库存 ≤ 5 标红；调整库存为绝对值
                  </p>
                </div>
                <span className="rounded-full bg-rose-50 px-2 py-1 text-xs text-rose-600">
                  {lowStock.length} 条
                </span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[820px] text-sm">
                  <thead className="bg-slate-50 text-xs text-slate-500">
                    <tr>
                      <th className="px-4 py-2 text-left font-medium">规格码</th>
                      <th className="px-4 py-2 text-left font-medium">商品</th>
                      <th className="px-4 py-2 text-left font-medium">规格</th>
                      <th className="px-4 py-2 text-right font-medium">库存</th>
                      <th className="px-4 py-2 text-left font-medium">调整库存</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {lowStock.length === 0 ? (
                      <tr>
                        <td colSpan={5} className="px-4 py-8 text-center text-slate-400">
                          暂无低库存规格
                        </td>
                      </tr>
                    ) : (
                      lowStock.map((item) => {
                        const busy = busySku === item.sku_code;
                        return (
                          <tr key={item.sku_code} className="hover:bg-slate-50/70">
                            <td className="px-4 py-2.5 font-medium text-slate-800">
                              {item.sku_code}
                            </td>
                            <td className="px-4 py-2.5 text-slate-700">{item.title}</td>
                            <td className="px-4 py-2.5 text-slate-500">
                              {item.spec_text || "—"}
                            </td>
                            <td
                              className={`px-4 py-2.5 text-right font-medium ${
                                item.stock <= 5 ? "text-rose-600" : "text-slate-800"
                              }`}
                            >
                              {item.stock}
                            </td>
                            <td className="px-4 py-2.5">
                              <div className="flex items-center gap-2">
                                <input
                                  value={stockInputs[item.sku_code] ?? ""}
                                  onChange={(event) =>
                                    setStockInputs((current) => ({
                                      ...current,
                                      [item.sku_code]: event.target.value,
                                    }))
                                  }
                                  inputMode="numeric"
                                  className={`${INPUT_CLASS} w-24`}
                                  placeholder="新的库存"
                                />
                                <button
                                  type="button"
                                  onClick={() => void saveStock(item.sku_code, item.stock)}
                                  disabled={busy}
                                  className={BTN_PRIMARY}
                                >
                                  {busy ? (
                                    <LoaderCircle size={13} className="animate-spin" />
                                  ) : null}
                                  保存
                                </button>
                              </div>
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </section>
          </>
        )}
      </main>
    </div>
  );
}
