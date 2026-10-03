"use client";

// 运营后台 · 优惠券管理。
// 券模板列表 + 新建券 + 定向发券。
// 金额字段（threshold / amount / rate）后端都是字符串，展示时用 money() 或原样换算。

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  BadgePercent,
  Inbox,
  LoaderCircle,
  Plus,
  RefreshCw,
  Send,
  X,
} from "lucide-react";
import { toast } from "sonner";

import { getToken } from "@/lib/auth";
import { money, shop, type AdminCoupon } from "@/lib/shop";

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

/** 折扣率字符串 → 「x 折」：0.900 → 9 折，0.855 → 8.55 折。 */
function discountText(rate?: string | null): string {
  if (rate === undefined || rate === null || rate === "") return "—";
  const number = Number(rate) * 10;
  if (Number.isNaN(number)) return `${rate} 折`;
  return `${Number(number.toFixed(2))} 折`;
}

function typeText(coupon: AdminCoupon): string {
  return coupon.type === "discount" ? "折扣" : "满减";
}

function faceText(coupon: AdminCoupon): string {
  if (coupon.type === "discount") return discountText(coupon.rate);
  return `减 ${money(coupon.amount)}`;
}

function parseUserIds(text: string): string[] {
  return text
    .split(/[,，\s;；]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export default function AdminCouponsPage() {
  const router = useRouter();

  const [coupons, setCoupons] = useState<AdminCoupon[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [grantCode, setGrantCode] = useState<string | null>(null);
  const [grantInput, setGrantInput] = useState("");
  const [granting, setGranting] = useState(false);

  const [form, setForm] = useState({
    code: "",
    name: "",
    type: "full_reduce",
    threshold: "0",
    amount: "",
    rate: "",
    days: "7",
    total: "1000",
    perUserLimit: "1",
  });
  const [creating, setCreating] = useState(false);

  const load = useCallback(
    async (options: { silent?: boolean } = {}) => {
      if (!getToken()) {
        router.replace("/login");
        return;
      }
      if (!options.silent) setLoading(true);
      setError("");
      try {
        const result = await shop.admin.coupons();
        setCoupons(result ?? []);
      } catch (err) {
        const message = err instanceof Error ? err.message : "优惠券加载失败";
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

  async function createCoupon() {
    const code = form.code.trim();
    if (!code) {
      toast.error("请填写券码");
      return;
    }
    const name = form.name.trim();
    if (!name) {
      toast.error("请填写券名称");
      return;
    }

    const body: {
      code: string;
      name: string;
      type: string;
      threshold?: string;
      amount?: string;
      rate?: string;
      days?: number;
      total?: number;
      per_user_limit?: number;
    } = { code, name, type: form.type };

    const threshold = form.threshold.trim();
    if (threshold) body.threshold = threshold;

    if (form.type === "full_reduce") {
      const amount = form.amount.trim();
      if (!amount) {
        toast.error("满减券必须填写优惠金额 amount");
        return;
      }
      body.amount = amount;
    } else {
      const rate = form.rate.trim();
      if (!rate) {
        toast.error("折扣券必须填写折扣率 rate（如 9 折填 0.9）");
        return;
      }
      body.rate = rate;
    }

    if (/^\d+$/.test(form.days.trim())) body.days = Number(form.days.trim());
    if (/^\d+$/.test(form.total.trim())) body.total = Number(form.total.trim());
    if (/^\d+$/.test(form.perUserLimit.trim())) {
      body.per_user_limit = Number(form.perUserLimit.trim());
    }

    setCreating(true);
    try {
      const created = await shop.admin.createCoupon(body);
      toast.success(`优惠券 ${created.code} 创建成功`);
      setForm({
        code: "",
        name: "",
        type: "full_reduce",
        threshold: "0",
        amount: "",
        rate: "",
        days: "7",
        total: "1000",
        perUserLimit: "1",
      });
      await load({ silent: true });
    } catch (err) {
      // 后端对满减缺 amount / 折扣缺 rate 等返回中文错误，直接展示
      toast.error(err instanceof Error ? err.message : "创建优惠券失败");
    } finally {
      setCreating(false);
    }
  }

  function openGrant(code: string) {
    setGrantCode(code);
    setGrantInput("");
  }

  async function submitGrant() {
    if (!grantCode) return;
    const userIds = parseUserIds(grantInput);
    if (userIds.length === 0) {
      toast.error("请输入至少一个用户号，如 u1001,u1002");
      return;
    }
    setGranting(true);
    try {
      const result = await shop.admin.grantCoupon(grantCode, userIds);
      if (result.skipped && result.skipped.length > 0) {
        toast.success(
          `发券 ${result.code}：成功 ${result.granted} 张，跳过：${result.skipped.join("、")}`,
        );
      } else {
        toast.success(`发券 ${result.code}：成功 ${result.granted} 张`);
      }
      setGrantCode(null);
      await load({ silent: true });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "发券失败");
    } finally {
      setGranting(false);
    }
  }

  return (
    <div className="min-h-full">

      <main className="mx-auto max-w-7xl space-y-4 px-4 py-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-slate-800">优惠券管理</h1>
            <p className="mt-0.5 text-xs text-slate-500">
              共 {coupons.length} 个券模板 · 支持新建与定向发券
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

        {/* 新建券 */}
        <section className="rounded-xl border border-slate-200 bg-white p-4">
          <h2 className="flex items-center gap-1.5 text-sm font-semibold text-slate-800">
            <Plus size={15} className="text-indigo-500" />
            新建券模板
          </h2>

          <div className="mt-3 grid gap-3 sm:grid-cols-3 lg:grid-cols-4">
            <label className="flex flex-col gap-1 text-xs text-slate-500">
              券码
              <input
                value={form.code}
                onChange={(event) =>
                  setForm((current) => ({ ...current, code: event.target.value }))
                }
                placeholder="如 NEW2024"
                className={INPUT_CLASS}
              />
            </label>

            <label className="flex flex-col gap-1 text-xs text-slate-500">
              名称
              <input
                value={form.name}
                onChange={(event) =>
                  setForm((current) => ({ ...current, name: event.target.value }))
                }
                placeholder="如 新人专享券"
                className={INPUT_CLASS}
              />
            </label>

            <label className="flex flex-col gap-1 text-xs text-slate-500">
              类型
              <select
                value={form.type}
                onChange={(event) =>
                  setForm((current) => ({ ...current, type: event.target.value }))
                }
                className={INPUT_CLASS}
              >
                <option value="full_reduce">满减（full_reduce）</option>
                <option value="discount">折扣（discount）</option>
              </select>
            </label>

            <label className="flex flex-col gap-1 text-xs text-slate-500">
              使用门槛（元）
              <input
                value={form.threshold}
                onChange={(event) =>
                  setForm((current) => ({ ...current, threshold: event.target.value }))
                }
                placeholder="0"
                className={INPUT_CLASS}
              />
            </label>

            {form.type === "full_reduce" ? (
              <label className="flex flex-col gap-1 text-xs text-slate-500">
                优惠金额（元，必填）
                <input
                  value={form.amount}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, amount: event.target.value }))
                  }
                  placeholder="如 20"
                  className={INPUT_CLASS}
                />
              </label>
            ) : (
              <label className="flex flex-col gap-1 text-xs text-slate-500">
                折扣率（必填，9 折填 0.9）
                <input
                  value={form.rate}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, rate: event.target.value }))
                  }
                  placeholder="0.9"
                  className={INPUT_CLASS}
                />
              </label>
            )}

            <label className="flex flex-col gap-1 text-xs text-slate-500">
              有效天数
              <input
                value={form.days}
                onChange={(event) =>
                  setForm((current) => ({ ...current, days: event.target.value }))
                }
                placeholder="7"
                className={INPUT_CLASS}
              />
            </label>

            <label className="flex flex-col gap-1 text-xs text-slate-500">
              发放总量
              <input
                value={form.total}
                onChange={(event) =>
                  setForm((current) => ({ ...current, total: event.target.value }))
                }
                placeholder="1000"
                className={INPUT_CLASS}
              />
            </label>

            <label className="flex flex-col gap-1 text-xs text-slate-500">
              每人限领
              <input
                value={form.perUserLimit}
                onChange={(event) =>
                  setForm((current) => ({ ...current, perUserLimit: event.target.value }))
                }
                placeholder="1"
                className={INPUT_CLASS}
              />
            </label>
          </div>

          <div className="mt-3 flex items-center gap-3">
            <button
              type="button"
              onClick={() => void createCoupon()}
              disabled={creating}
              className={BTN_PRIMARY}
            >
              {creating ? (
                <LoaderCircle size={13} className="animate-spin" />
              ) : (
                <Plus size={13} />
              )}
              创建优惠券
            </button>
            <span className="text-[11px] text-slate-400">
              满减券必须填优惠金额；折扣券必须填折扣率。
            </span>
          </div>
        </section>

        {/* 券模板列表 */}
        <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
          <div className="border-b border-slate-100 px-4 py-3">
            <h2 className="flex items-center gap-1.5 text-sm font-semibold text-slate-800">
              <BadgePercent size={15} className="text-indigo-500" />
              券模板列表
            </h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1100px] text-sm">
              <thead className="bg-slate-50 text-xs text-slate-500">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">券码</th>
                  <th className="px-3 py-2 text-left font-medium">名称</th>
                  <th className="px-3 py-2 text-left font-medium">类型</th>
                  <th className="px-3 py-2 text-right font-medium">门槛</th>
                  <th className="px-3 py-2 text-right font-medium">面额</th>
                  <th className="px-3 py-2 text-left font-medium">有效期</th>
                  <th className="px-3 py-2 text-right font-medium">总量</th>
                  <th className="px-3 py-2 text-right font-medium">已领取</th>
                  <th className="px-3 py-2 text-right font-medium">已核销</th>
                  <th className="px-3 py-2 text-right font-medium">每人限领</th>
                  <th className="px-3 py-2 text-left font-medium">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {loading && coupons.length === 0 ? (
                  Array.from({ length: 3 }).map((_, index) => (
                    <tr key={index} className="animate-pulse">
                      <td colSpan={11} className="px-3 py-4">
                        <div className="h-4 w-full rounded bg-slate-100" />
                      </td>
                    </tr>
                  ))
                ) : coupons.length === 0 ? (
                  <tr>
                    <td colSpan={11} className="px-3 py-10 text-center text-slate-400">
                      <Inbox size={22} className="mx-auto mb-2 text-slate-300" />
                      还没有券模板，先在上方新建一个
                    </td>
                  </tr>
                ) : (
                  coupons.map((coupon) => (
                    <tr key={coupon.code} className="align-top hover:bg-slate-50/70">
                      <td className="px-3 py-2.5 font-medium text-slate-800">
                        {coupon.code}
                      </td>
                      <td className="px-3 py-2.5 text-slate-700">{coupon.name}</td>
                      <td className="px-3 py-2.5">
                        <span
                          className={`inline-block rounded-full px-2 py-0.5 text-xs ${
                            coupon.type === "discount"
                              ? "bg-violet-50 text-violet-700"
                              : "bg-indigo-50 text-indigo-600"
                          }`}
                        >
                          {typeText(coupon)}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 text-right text-slate-600">
                        {money(coupon.threshold)}
                      </td>
                      <td className="px-3 py-2.5 text-right font-medium text-slate-800">
                        {faceText(coupon)}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2.5 text-xs text-slate-500">
                        <div>{formatTime(coupon.start_at)}</div>
                        <div className="text-slate-400">
                          至 {formatTime(coupon.end_at)}
                        </div>
                      </td>
                      <td className="px-3 py-2.5 text-right text-slate-600">
                        {coupon.total}
                      </td>
                      <td className="px-3 py-2.5 text-right text-slate-600">
                        {coupon.claimed}
                      </td>
                      <td className="px-3 py-2.5 text-right text-slate-600">
                        {coupon.used_count}
                      </td>
                      <td className="px-3 py-2.5 text-right text-slate-600">
                        {coupon.per_user_limit}
                      </td>
                      <td className="px-3 py-2.5">
                        <button
                          type="button"
                          onClick={() => openGrant(coupon.code)}
                          className={BTN_PRIMARY}
                        >
                          <Send size={13} />
                          发券
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      </main>

      {/* 定向发券 */}
      {grantCode ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/30 px-4">
          <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-4 shadow-lg">
            <div className="flex items-start justify-between">
              <div>
                <h2 className="text-sm font-semibold text-slate-800">定向发券</h2>
                <p className="mt-0.5 text-xs text-slate-500">券码 {grantCode}</p>
              </div>
              <button
                type="button"
                onClick={() => setGrantCode(null)}
                className="rounded-lg p-1 text-slate-400 transition hover:bg-slate-100"
              >
                <X size={15} />
              </button>
            </div>

            <label className="mt-3 flex flex-col gap-1 text-xs text-slate-500">
              用户号（逗号或空格分隔）
              <textarea
                value={grantInput}
                onChange={(event) => setGrantInput(event.target.value)}
                rows={3}
                placeholder="u1001,u1002"
                className={`${INPUT_CLASS} resize-none`}
              />
            </label>
            <p className="mt-1 text-[11px] text-slate-400">
              共 {parseUserIds(grantInput).length} 个账号；超出限领或不存在的账号会被跳过。
            </p>

            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setGrantCode(null)}
                disabled={granting}
                className={BTN_GHOST}
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => void submitGrant()}
                disabled={granting}
                className={BTN_PRIMARY}
              >
                {granting ? (
                  <LoaderCircle size={13} className="animate-spin" />
                ) : (
                  <Send size={13} />
                )}
                确认发券
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
