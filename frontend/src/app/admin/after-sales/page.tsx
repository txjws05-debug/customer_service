"use client";

// 运营后台 · 售后审核台。
//
// 工单状态流转（与中台一致）：
//   submitted --approve--> approved（退货退款）→ returning --receive--> received --complete--> completed
//   submitted --reject--> rejected
//   approved --complete--> completed（仅退款）
// complete 对退货退款会回滚库存。

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  CircleCheck,
  CircleX,
  Inbox,
  LoaderCircle,
  PackageCheck,
  RefreshCw,
} from "lucide-react";
import { toast } from "sonner";

import { ShopHeader } from "@/components/ShopHeader";
import { getToken } from "@/lib/auth";
import {
  AFTER_SALE_STATUS_LABEL,
  money,
  shop,
  type AfterSaleTicket,
} from "@/lib/shop";

const TABS: { value: string; label: string }[] = [
  { value: "", label: "全部" },
  { value: "submitted", label: AFTER_SALE_STATUS_LABEL.submitted },
  { value: "approved", label: AFTER_SALE_STATUS_LABEL.approved },
  { value: "returning", label: AFTER_SALE_STATUS_LABEL.returning },
  { value: "received", label: AFTER_SALE_STATUS_LABEL.received },
  { value: "completed", label: AFTER_SALE_STATUS_LABEL.completed },
  { value: "rejected", label: AFTER_SALE_STATUS_LABEL.rejected },
];

const BTN_PRIMARY =
  "inline-flex items-center gap-1 rounded-lg bg-indigo-600 px-2.5 py-1.5 text-xs font-medium text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50";

const BTN_DANGER =
  "inline-flex items-center gap-1 rounded-lg border border-rose-200 bg-rose-50 px-2.5 py-1.5 text-xs font-medium text-rose-600 transition hover:bg-rose-100 disabled:cursor-not-allowed disabled:opacity-50";

const BTN_GHOST =
  "inline-flex items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50";

const INPUT_CLASS =
  "rounded-lg border border-slate-200 px-2.5 py-1.5 text-sm text-slate-800 outline-none focus:border-indigo-400";

const STATUS_BADGE: Record<string, string> = {
  submitted: "bg-amber-50 text-amber-700",
  approved: "bg-indigo-50 text-indigo-600",
  rejected: "bg-rose-50 text-rose-600",
  returning: "bg-sky-50 text-sky-700",
  received: "bg-violet-50 text-violet-700",
  completed: "bg-emerald-50 text-emerald-700",
  canceled: "bg-slate-100 text-slate-500",
};

type PendingAction = {
  ticketNo: string;
  action: "approve" | "reject" | "receive" | "complete";
};

function formatTime(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

function actionTitle(action: PendingAction["action"]): string {
  if (action === "approve") return "审核通过";
  if (action === "reject") return "审核驳回";
  if (action === "receive") return "确认收到退货";
  return "完成售后";
}

function defaultRemark(action: PendingAction["action"]): string {
  if (action === "approve") return "符合售后条件";
  if (action === "reject") return "不符合售后条件";
  if (action === "receive") return "已收到退回商品";
  return "退款已完成";
}

function statusText(ticket: AfterSaleTicket): string {
  return ticket.status_desc || AFTER_SALE_STATUS_LABEL[ticket.status] || ticket.status;
}

export default function AdminAfterSalesPage() {
  const router = useRouter();

  const [status, setStatus] = useState("");
  const [tickets, setTickets] = useState<AfterSaleTicket[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [pending, setPending] = useState<PendingAction | null>(null);
  const [remark, setRemark] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [busyTicket, setBusyTicket] = useState<string | null>(null);

  const load = useCallback(
    async (options: { silent?: boolean } = {}) => {
      if (!getToken()) {
        router.replace("/login");
        return;
      }
      if (!options.silent) setLoading(true);
      setError("");
      try {
        const result = await shop.admin.afterSales(status || undefined);
        setTickets(result.tickets ?? []);
        setTotal(result.total ?? 0);
      } catch (err) {
        const message = err instanceof Error ? err.message : "售后工单加载失败";
        setError(message);
        if (options.silent) toast.error(message);
      } finally {
        setLoading(false);
      }
    },
    [router, status],
  );

  useEffect(() => {
    void load();
  }, [load]);

  function openAction(ticket: AfterSaleTicket, action: PendingAction["action"]) {
    setPending({ ticketNo: ticket.ticket_no, action });
    setRemark(defaultRemark(action));
  }

  async function submitPending() {
    if (!pending) return;
    setSubmitting(true);
    const text = remark.trim();
    try {
      const { ticketNo, action } = pending;
      const result =
        action === "approve"
          ? await shop.admin.approveAfterSale(ticketNo, text)
          : action === "reject"
            ? await shop.admin.rejectAfterSale(ticketNo, text)
            : action === "receive"
              ? await shop.admin.receiveAfterSale(ticketNo, text)
              : await shop.admin.completeAfterSale(ticketNo, text);
      toast.success(
        `工单 ${result.ticket_no} · ${statusText(result)}${
          text ? `（备注：${text}）` : ""
        }`,
      );
      setPending(null);
      await load({ silent: true });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "操作失败");
    } finally {
      setSubmitting(false);
    }
  }

  /** 直接调用（不需要备注的场景：确认收货 / 完成售后）。 */
  async function runDirect(ticket: AfterSaleTicket, action: "receive" | "complete") {
    setBusyTicket(ticket.ticket_no);
    try {
      const result =
        action === "receive"
          ? await shop.admin.receiveAfterSale(ticket.ticket_no, "商家已收货")
          : await shop.admin.completeAfterSale(ticket.ticket_no, "售后完成");
      toast.success(`工单 ${result.ticket_no} · ${statusText(result)}`);
      await load({ silent: true });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "操作失败");
    } finally {
      setBusyTicket(null);
    }
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <ShopHeader />

      <main className="mx-auto max-w-7xl space-y-4 px-4 py-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-slate-800">售后审核台</h1>
            <p className="mt-0.5 text-xs text-slate-500">
              共 {total} 张工单 · 当前筛选：
              {status ? AFTER_SALE_STATUS_LABEL[status] ?? status : "全部"}
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

        {/* 状态 tab */}
        <div className="flex flex-wrap gap-1">
          {TABS.map((tab) => (
            <button
              key={tab.value || "all"}
              type="button"
              onClick={() => setStatus(tab.value)}
              className={`rounded-lg px-3 py-1.5 text-xs transition ${
                status === tab.value
                  ? "bg-indigo-50 font-medium text-indigo-600"
                  : "text-slate-600 hover:bg-slate-100"
              }`}
            >
              {tab.label}
            </button>
          ))}
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

        <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1100px] text-sm">
              <thead className="bg-slate-50 text-xs text-slate-500">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">工单号</th>
                  <th className="px-3 py-2 text-left font-medium">订单号</th>
                  <th className="px-3 py-2 text-left font-medium">类型</th>
                  <th className="px-3 py-2 text-right font-medium">退款金额</th>
                  <th className="px-3 py-2 text-left font-medium">原因</th>
                  <th className="px-3 py-2 text-left font-medium">状态</th>
                  <th className="px-3 py-2 text-left font-medium">备注</th>
                  <th className="px-3 py-2 text-left font-medium">更新时间</th>
                  <th className="px-3 py-2 text-left font-medium">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {loading && tickets.length === 0 ? (
                  Array.from({ length: 3 }).map((_, index) => (
                    <tr key={index} className="animate-pulse">
                      <td colSpan={9} className="px-3 py-4">
                        <div className="h-4 w-full rounded bg-slate-100" />
                      </td>
                    </tr>
                  ))
                ) : tickets.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="px-3 py-10 text-center text-slate-400">
                      <Inbox size={22} className="mx-auto mb-2 text-slate-300" />
                      当前筛选下没有售后工单
                    </td>
                  </tr>
                ) : (
                  tickets.map((ticket) => {
                    const busy = busyTicket === ticket.ticket_no;
                    const canComplete =
                      ticket.status === "approved" || ticket.status === "received";
                    return (
                      <tr key={ticket.ticket_no} className="align-top hover:bg-slate-50/70">
                        <td className="px-3 py-2.5 font-medium text-slate-800">
                          {ticket.ticket_no}
                        </td>
                        <td className="px-3 py-2.5 text-slate-600">{ticket.order_id}</td>
                        <td className="px-3 py-2.5 text-slate-600">
                          {ticket.type_desc || ticket.type}
                        </td>
                        <td className="px-3 py-2.5 text-right font-medium text-slate-800">
                          {money(ticket.refund_amount)}
                        </td>
                        <td className="max-w-[220px] px-3 py-2.5 text-slate-600">
                          <div className="line-clamp-2">{ticket.reason || "—"}</div>
                          {ticket.evidence && ticket.evidence.length > 0 ? (
                            <div className="mt-1 text-xs text-slate-400">
                              凭证 {ticket.evidence.length} 张
                            </div>
                          ) : null}
                        </td>
                        <td className="px-3 py-2.5">
                          <span
                            className={`inline-block rounded-full px-2 py-0.5 text-xs ${
                              STATUS_BADGE[ticket.status] ?? "bg-slate-100 text-slate-600"
                            }`}
                          >
                            {statusText(ticket)}
                          </span>
                        </td>
                        <td className="max-w-[180px] px-3 py-2.5 text-xs text-slate-500">
                          <span className="line-clamp-2">{ticket.remark || "—"}</span>
                        </td>
                        <td className="whitespace-nowrap px-3 py-2.5 text-xs text-slate-500">
                          {formatTime(ticket.updated_at)}
                        </td>
                        <td className="px-3 py-2.5">
                          <div className="flex flex-col items-start gap-1">
                            {ticket.status === "submitted" ? (
                              <>
                                <button
                                  type="button"
                                  onClick={() => openAction(ticket, "approve")}
                                  className={BTN_PRIMARY}
                                >
                                  <CircleCheck size={13} />
                                  审核通过
                                </button>
                                <button
                                  type="button"
                                  onClick={() => openAction(ticket, "reject")}
                                  className={BTN_DANGER}
                                >
                                  <CircleX size={13} />
                                  审核驳回
                                </button>
                              </>
                            ) : null}

                            {ticket.status === "returning" ? (
                              <>
                                <button
                                  type="button"
                                  onClick={() => void runDirect(ticket, "receive")}
                                  disabled={busy}
                                  className={BTN_PRIMARY}
                                >
                                  {busy ? (
                                    <LoaderCircle size={13} className="animate-spin" />
                                  ) : (
                                    <PackageCheck size={13} />
                                  )}
                                  确认收到退货
                                </button>
                                <button
                                  type="button"
                                  onClick={() => openAction(ticket, "receive")}
                                  className="text-[11px] text-slate-400 underline hover:text-slate-600"
                                >
                                  带备注确认
                                </button>
                              </>
                            ) : null}

                            {canComplete ? (
                              <>
                                <button
                                  type="button"
                                  onClick={() => void runDirect(ticket, "complete")}
                                  disabled={busy}
                                  className={BTN_PRIMARY}
                                >
                                  {busy ? (
                                    <LoaderCircle size={13} className="animate-spin" />
                                  ) : (
                                    <CircleCheck size={13} />
                                  )}
                                  完成售后
                                </button>
                                <button
                                  type="button"
                                  onClick={() => openAction(ticket, "complete")}
                                  className="text-[11px] text-slate-400 underline hover:text-slate-600"
                                >
                                  带备注完成
                                </button>
                                <span className="text-[11px] text-slate-400">
                                  退货退款会回滚库存
                                </span>
                              </>
                            ) : null}

                            {ticket.status !== "submitted" &&
                            ticket.status !== "returning" &&
                            !canComplete ? (
                              <span className="text-[11px] text-slate-400">
                                {ticket.status === "completed"
                                  ? "已完成，无待办操作"
                                  : ticket.status === "rejected"
                                    ? "已驳回，无待办操作"
                                    : ticket.status === "canceled"
                                      ? "用户已撤销，无待办操作"
                                      : "当前状态无可用操作"}
                              </span>
                            ) : null}
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
      </main>

      {/* 备注小表单 */}
      {pending ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/30 px-4">
          <div className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-4 shadow-lg">
            <h2 className="text-sm font-semibold text-slate-800">
              {actionTitle(pending.action)}
            </h2>
            <p className="mt-0.5 text-xs text-slate-500">工单 {pending.ticketNo}</p>

            <label className="mt-3 flex flex-col gap-1 text-xs text-slate-500">
              备注（可留空）
              <input
                value={remark}
                onChange={(event) => setRemark(event.target.value)}
                placeholder={defaultRemark(pending.action)}
                className={INPUT_CLASS}
              />
            </label>

            {pending.action === "complete" ? (
              <p className="mt-2 rounded-lg bg-amber-50 px-2 py-1.5 text-[11px] text-amber-700">
                退货退款类型的工单完成后会回滚库存。
              </p>
            ) : null}

            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setPending(null)}
                disabled={submitting}
                className={BTN_GHOST}
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => void submitPending()}
                disabled={submitting}
                className={pending.action === "reject" ? BTN_DANGER : BTN_PRIMARY}
              >
                {submitting ? <LoaderCircle size={13} className="animate-spin" /> : null}
                确认{actionTitle(pending.action)}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
