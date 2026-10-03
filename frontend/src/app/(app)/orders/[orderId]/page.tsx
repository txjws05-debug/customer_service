"use client";

// 订单详情：金额明细 / 收货信息 / 物流 / 商品明细 / 状态时间线，
// 以及支付、取消、确认收货、申请售后、寄回、评价等操作。

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  Loader2,
  MapPin,
  Package,
  Star,
  Truck,
} from "lucide-react";
import { toast } from "sonner";

import { getToken, getUser } from "@/lib/auth";
import {
  AFTER_SALE_STATUS_LABEL,
  commerceUserId,
  money,
  shop,
  type AfterSaleTicket,
  type OrderDetail,
} from "@/lib/shop";

const PAY_CHANNELS = [
  { value: "wechat", label: "微信支付" },
  { value: "alipay", label: "支付宝" },
  { value: "card", label: "银行卡" },
];

const OPERATOR_LABEL: Record<string, string> = {
  user: "用户",
  admin: "商家/运营",
  system: "系统",
};

/** 可申请售后的状态：还没发货的只能整单退，发货后走退货退款。 */
const AFTER_SALE_ORDER_STATUSES = ["已完成", "待收货", "运输中", "待揽收", "待发货"];

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

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4">
      <h2 className="mb-3 text-sm font-semibold text-slate-800">{title}</h2>
      {children}
    </section>
  );
}

function InfoRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex justify-between gap-4 py-1 text-sm">
      <span className="flex-none text-slate-500">{label}</span>
      <span className="text-right text-slate-800">{children}</span>
    </div>
  );
}

/** 状态时间线：status_logs 里的 from_status → to_status。 */
function StatusTimeline({ order }: { order: OrderDetail }) {
  const logs = order.status_logs ?? [];
  if (logs.length === 0) {
    return <p className="text-sm text-slate-400">暂无状态记录</p>;
  }
  return (
    <ol className="flex flex-col gap-3">
      {logs.map((log, index) => (
        <li key={`${log.to_status}-${log.created_at}-${index}`} className="flex gap-3">
          <div className="flex flex-none flex-col items-center">
            <span className="mt-1 h-2 w-2 rounded-full bg-indigo-500" />
            {index < logs.length - 1 && (
              <span className="mt-1 w-px flex-1 bg-slate-200" />
            )}
          </div>
          <div className="min-w-0 flex-1 pb-1">
            <p className="text-sm text-slate-800">
              {log.from_status ? (
                <>
                  <span className="text-slate-500">{log.from_status}</span>
                  <span className="mx-1 text-slate-400">→</span>
                </>
              ) : null}
              <span className="font-medium">{log.to_status}</span>
            </p>
            <p className="mt-0.5 text-xs text-slate-500">
              操作方：
              {(OPERATOR_LABEL[log.operator] ?? log.operator) || "未知"}
              {" · "}
              {new Date(log.created_at).toLocaleString("zh-CN")}
            </p>
            {log.remark && (
              <p className="mt-0.5 text-xs text-slate-400">备注：{log.remark}</p>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

/** 单个售后工单：状态 + 撤销 + 填写寄回单号。 */
function AfterSaleCard({
  ticket,
  onChanged,
}: {
  ticket: AfterSaleTicket;
  onChanged: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [showReturn, setShowReturn] = useState(false);
  const [trackingNumber, setTrackingNumber] = useState("");
  const [company, setCompany] = useState("");

  async function cancelTicket() {
    setBusy(true);
    try {
      const updated = await shop.cancelAfterSale(ticket.ticket_no);
      toast.success(`售后单已撤销：${updated.status_desc}`);
      await onChanged();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function submitReturn(e: React.FormEvent) {
    e.preventDefault();
    if (!trackingNumber.trim()) {
      toast.error("请填写寄回单号");
      return;
    }
    setBusy(true);
    try {
      const updated = await shop.submitReturn(ticket.ticket_no, {
        tracking_number: trackingNumber.trim(),
        company: company.trim() || undefined,
      });
      toast.success(`已提交寄回信息：${updated.status_desc}`);
      setShowReturn(false);
      setTrackingNumber("");
      setCompany("");
      await onChanged();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm text-slate-800">
          工单 {ticket.ticket_no}
          <span className="ml-2 text-xs text-slate-500">{ticket.type_desc}</span>
        </span>
        <span className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-xs text-slate-600">
          {AFTER_SALE_STATUS_LABEL[ticket.status] ?? ticket.status}
        </span>
      </div>
      <p className="mt-1 text-xs text-slate-500">{ticket.status_desc}</p>
      <p className="mt-1 text-xs text-slate-500">
        退款金额：{money(ticket.refund_amount)} · 原因：{ticket.reason}
      </p>
      {ticket.evidence?.length > 0 && (
        <p className="mt-1 break-all text-xs text-slate-400">
          凭证：{ticket.evidence.join("，")}
        </p>
      )}
      {ticket.remark && (
        <p className="mt-1 text-xs text-slate-400">商家备注：{ticket.remark}</p>
      )}
      <p className="mt-1 text-xs text-slate-400">
        申请时间：{new Date(ticket.created_at).toLocaleString("zh-CN")} · 更新：
        {new Date(ticket.updated_at).toLocaleString("zh-CN")}
      </p>

      <div className="mt-2 flex flex-wrap gap-2">
        {ticket.can_cancel && (
          <button
            onClick={() => void cancelTicket()}
            disabled={busy}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-600 transition hover:border-red-300 hover:text-red-600 disabled:opacity-50"
          >
            撤销申请
          </button>
        )}
        {ticket.can_return && (
          <button
            onClick={() => setShowReturn((v) => !v)}
            className="rounded-lg border border-indigo-300 bg-white px-3 py-1.5 text-xs text-indigo-600 transition hover:bg-indigo-50"
          >
            {showReturn ? "收起" : "填写寄回单号"}
          </button>
        )}
      </div>

      {showReturn && ticket.can_return && (
        <form onSubmit={submitReturn} className="mt-3 flex flex-col gap-2">
          <input
            value={trackingNumber}
            onChange={(e) => setTrackingNumber(e.target.value)}
            placeholder="寄回物流单号（必填）"
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-none placeholder:text-slate-400 focus:border-indigo-400"
          />
          <input
            value={company}
            onChange={(e) => setCompany(e.target.value)}
            placeholder="物流公司（选填）"
            className="rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-none placeholder:text-slate-400 focus:border-indigo-400"
          />
          <button
            type="submit"
            disabled={busy}
            className="self-start rounded-lg bg-indigo-500 px-3 py-1.5 text-xs text-white transition hover:bg-indigo-600 disabled:opacity-50"
          >
            {busy ? "提交中…" : "提交寄回信息"}
          </button>
        </form>
      )}
    </div>
  );
}

/** 申请售后表单。 */
function AfterSaleForm({
  order,
  user,
  onCreated,
}: {
  order: OrderDetail;
  user: string;
  onCreated: () => Promise<void>;
}) {
  const [type, setType] = useState("refund_only");
  const [reason, setReason] = useState("");
  const [evidence, setEvidence] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!reason.trim()) {
      toast.error("请填写申请原因");
      return;
    }
    const urls = evidence
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean)
      .slice(0, 3);
    setBusy(true);
    try {
      const ticket = await shop.applyAfterSale(order.order_id, {
        user_id: user,
        type,
        reason: reason.trim(),
        evidence: urls.length > 0 ? urls : undefined,
      });
      toast.success(
        `售后申请已提交，工单号 ${ticket.ticket_no}（${
          (AFTER_SALE_STATUS_LABEL[ticket.status] ?? ticket.status)
        }）`,
      );
      setReason("");
      setEvidence("");
      await onCreated();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-4 text-sm text-slate-700">
        <label className="flex items-center gap-1.5">
          <input
            type="radio"
            name="after-sale-type"
            checked={type === "refund_only"}
            onChange={() => setType("refund_only")}
          />
          仅退款
        </label>
        <label className="flex items-center gap-1.5">
          <input
            type="radio"
            name="after-sale-type"
            checked={type === "return_refund"}
            onChange={() => setType("return_refund")}
          />
          退货退款
        </label>
      </div>
      <textarea
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        rows={2}
        placeholder="请填写申请原因（必填），例如：商品与描述不符"
        className="rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-none placeholder:text-slate-400 focus:border-indigo-400"
      />
      <input
        value={evidence}
        onChange={(e) => setEvidence(e.target.value)}
        placeholder="凭证图片 URL，多个用英文逗号分隔（选填，最多 3 条）"
        className="rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-none placeholder:text-slate-400 focus:border-indigo-400"
      />
      <button
        type="submit"
        disabled={busy}
        className="self-start rounded-lg bg-indigo-500 px-4 py-2 text-sm text-white transition hover:bg-indigo-600 disabled:opacity-50"
      >
        {busy ? "提交中…" : "提交售后申请"}
      </button>
    </form>
  );
}

interface ReviewDraft {
  rating: number;
  content: string;
}

/** 待评价时的评价表单：订单内每个商品一条评价。 */
function ReviewForm({
  order,
  user,
  onSubmitted,
}: {
  order: OrderDetail;
  user: string;
  onSubmitted: () => Promise<void>;
}) {
  const items = order.items ?? [];
  const [drafts, setDrafts] = useState<Record<string, ReviewDraft>>({});
  const [busy, setBusy] = useState(false);

  const draftOf = (productId: string): ReviewDraft =>
    drafts[productId] ?? { rating: 5, content: "" };

  function update(productId: string, patch: Partial<ReviewDraft>) {
    setDrafts((prev) => ({
      ...prev,
      [productId]: { ...(prev[productId] ?? { rating: 5, content: "" }), ...patch },
    }));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const payload = items.map((item) => {
      const draft = draftOf(item.product_id);
      return {
        product_id: item.product_id,
        rating: draft.rating,
        content: draft.content.trim(),
      };
    });
    if (payload.some((item) => !item.content)) {
      toast.error("请为每个商品填写评价内容");
      return;
    }
    setBusy(true);
    try {
      const created = await shop.createReviews(order.order_id, {
        user_id: user,
        items: payload,
      });
      toast.success(`评价成功，获得 ${created.length * 10} 积分（10 积分/条）`);
      await onSubmitted();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (items.length === 0) {
    return <p className="text-sm text-slate-400">该订单没有可评价的商品</p>;
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      {items.map((item) => {
        const draft = draftOf(item.product_id);
        return (
          <div
            key={item.product_id}
            className="rounded-lg border border-slate-200 bg-slate-50 p-3"
          >
            <p className="truncate text-sm text-slate-800">{item.title}</p>
            {item.spec_text && (
              <p className="mt-0.5 text-xs text-slate-500">{item.spec_text}</p>
            )}
            <div className="mt-2 flex items-center gap-1">
              {[1, 2, 3, 4, 5].map((star) => (
                <button
                  key={star}
                  type="button"
                  title={`${star} 星`}
                  onClick={() => update(item.product_id, { rating: star })}
                  className="p-0.5"
                >
                  <Star
                    size={16}
                    className={
                      star <= draft.rating
                        ? "fill-amber-400 text-amber-400"
                        : "text-slate-300"
                    }
                  />
                </button>
              ))}
              <span className="ml-1 text-xs text-slate-500">{draft.rating} 星</span>
            </div>
            <textarea
              value={draft.content}
              onChange={(e) => update(item.product_id, { content: e.target.value })}
              rows={2}
              placeholder="说说这次购物体验吧（必填）"
              className="mt-2 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none placeholder:text-slate-400 focus:border-indigo-400"
            />
          </div>
        );
      })}
      <button
        type="submit"
        disabled={busy}
        className="self-start rounded-lg bg-indigo-500 px-4 py-2 text-sm text-white transition hover:bg-indigo-600 disabled:opacity-50"
      >
        {busy ? "提交中…" : "提交评价"}
      </button>
    </form>
  );
}

export default function OrderDetailPage({
  params,
}: {
  params: Promise<{ orderId: string }>;
}) {
  const { orderId } = use(params);
  const router = useRouter();
  const [user, setUser] = useState<string | null>(null);
  const [order, setOrder] = useState<OrderDetail | null>(null);
  const [tickets, setTickets] = useState<AfterSaleTicket[]>([]);
  const [pending, setPending] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [payChannel, setPayChannel] = useState("wechat");
  const [cancelReason, setCancelReason] = useState("用户主动取消");

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    setUser(commerceUserId(getUser()?.username));
  }, [router]);

  const load = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    setError("");
    try {
      const detail = await shop.order(orderId);
      setOrder(detail);
      // 售后单与待评价状态是附加信息，失败不影响主详情展示
      const [afterSale, pendingReviews] = await Promise.allSettled([
        shop.afterSales(user),
        shop.pendingReviews(user),
      ]);
      if (afterSale.status === "fulfilled") {
        setTickets(
          (afterSale.value.tickets ?? []).filter((t) => t.order_id === orderId),
        );
      } else {
        setTickets([]);
      }
      if (pendingReviews.status === "fulfilled") {
        setPending((pendingReviews.value.order_ids ?? []).includes(orderId));
      } else {
        setPending(false);
      }
    } catch (err) {
      const message = (err as Error).message || "订单加载失败";
      setError(message);
      setOrder(null);
      toast.error(message);
    } finally {
      setLoading(false);
    }
  }, [user, orderId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handlePay() {
    if (!order) return;
    setBusy(true);
    try {
      const result = await shop.payOrder(order.order_id, payChannel);
      toast.success(
        `支付成功，交易号 ${result.trade_no}（${result.status_desc}，${money(
          result.amount,
        )}）`,
      );
      await load();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleCancel() {
    if (!order) return;
    setBusy(true);
    try {
      const result = await shop.cancelOrder(
        order.order_id,
        cancelReason.trim() || "用户主动取消",
      );
      toast.success(`订单已取消（${result.status_desc}），库存与优惠券已归还`);
      await load();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleReceive() {
    if (!order) return;
    setBusy(true);
    try {
      const result = await shop.receiveOrder(order.order_id);
      toast.success(
        `确认收货成功（${result.status_desc}），获得 ${result.earned_points} 积分`,
      );
      await load();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const canApplyAfterSale =
    order !== null && AFTER_SALE_ORDER_STATUSES.includes(order.status);
  const freight = order?.freight_amount ?? "0";
  const discount = order?.discount_amount ?? "0";

  return (
    <div className="min-h-full">

      <main className="mx-auto max-w-4xl px-4 py-6">
        <Link
          href="/orders"
          className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500 transition hover:text-indigo-600"
        >
          <ArrowLeft size={15} />
          返回订单列表
        </Link>

        {loading ? (
          <div className="flex items-center justify-center gap-2 py-20 text-slate-400">
            <Loader2 className="animate-spin" size={18} />
            <span className="text-sm">加载中…</span>
          </div>
        ) : error || !order ? (
          <div className="rounded-xl border border-slate-200 bg-white p-10 text-center">
            <p className="text-sm text-red-500">{error || "订单不存在"}</p>
            <button
              onClick={() => void load()}
              className="mt-3 rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-600 transition hover:border-indigo-300 hover:text-indigo-600"
            >
              重新加载
            </button>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {/* 状态 + 操作 */}
            <section className="rounded-xl border border-slate-200 bg-white p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`rounded-full border px-2.5 py-0.5 text-sm ${statusBadgeClass(
                        order.status,
                      )}`}
                    >
                      {order.status}
                    </span>
                    <span className="text-sm text-slate-500">{order.status_desc}</span>
                    {order.is_plus && (
                      <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs text-amber-600">
                        PLUS 会员
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    订单号 {order.order_id} · 下单时间{" "}
                    {new Date(order.created_at).toLocaleString("zh-CN")}
                  </p>
                </div>
              </div>

              {(order.can_pay || order.can_cancel || order.can_receive) && (
                <div className="mt-4 flex flex-col gap-3 border-t border-slate-100 pt-4">
                  {order.can_pay && (
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm text-slate-600">支付渠道</span>
                      <select
                        value={payChannel}
                        onChange={(e) => setPayChannel(e.target.value)}
                        className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-900 outline-none focus:border-indigo-400"
                      >
                        {PAY_CHANNELS.map((channel) => (
                          <option key={channel.value} value={channel.value}>
                            {channel.label}
                          </option>
                        ))}
                      </select>
                      <button
                        onClick={() => void handlePay()}
                        disabled={busy}
                        className="rounded-lg bg-indigo-500 px-4 py-2 text-sm text-white transition hover:bg-indigo-600 disabled:opacity-50"
                      >
                        立即支付 {money(order.pay_amount)}
                      </button>
                    </div>
                  )}

                  {order.can_cancel && (
                    <div className="flex flex-wrap items-center gap-2">
                      <input
                        value={cancelReason}
                        onChange={(e) => setCancelReason(e.target.value)}
                        placeholder="取消原因"
                        className="w-64 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-none placeholder:text-slate-400 focus:border-indigo-400"
                      />
                      <button
                        onClick={() => void handleCancel()}
                        disabled={busy}
                        className="rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-600 transition hover:border-red-300 hover:text-red-600 disabled:opacity-50"
                      >
                        取消订单
                      </button>
                    </div>
                  )}

                  {order.can_receive && (
                    <div>
                      <button
                        onClick={() => void handleReceive()}
                        disabled={busy}
                        className="rounded-lg bg-indigo-500 px-4 py-2 text-sm text-white transition hover:bg-indigo-600 disabled:opacity-50"
                      >
                        确认收货
                      </button>
                    </div>
                  )}
                </div>
              )}
            </section>

            {/* 金额明细 */}
            <Section title="金额明细">
              <InfoRow label="商品金额">{money(order.goods_amount)}</InfoRow>
              <InfoRow label="优惠">
                <span className={Number(discount) > 0 ? "text-red-500" : ""}>
                  -{money(discount)}
                </span>
              </InfoRow>
              <InfoRow label="运费">
                {Number(freight) === 0 ? (
                  <span className="text-emerald-600">免运费</span>
                ) : (
                  money(freight)
                )}
              </InfoRow>
              <div className="mt-2 flex justify-between border-t border-slate-100 pt-2 text-sm">
                <span className="text-slate-500">实付金额</span>
                <span className="font-semibold text-slate-900">
                  {money(order.pay_amount)}
                </span>
              </div>
            </Section>

            {/* 收货信息 */}
            <Section title="收货信息">
              <div className="flex gap-2 text-sm text-slate-800">
                <MapPin size={16} className="mt-0.5 flex-none text-indigo-500" />
                <div>
                  <p>
                    {order.receiver_name} · {order.receiver_phone_masked}
                  </p>
                  <p className="mt-1 text-slate-600">{order.receiver_address}</p>
                </div>
              </div>
            </Section>

            {/* 物流 */}
            <Section title="物流信息">
              {order.logistics_company || order.tracking_number ? (
                <div className="flex gap-2 text-sm text-slate-800">
                  <Truck size={16} className="mt-0.5 flex-none text-indigo-500" />
                  <div>
                    <p>{order.logistics_company || "未知物流公司"}</p>
                    <p className="mt-1 text-slate-600">
                      运单号：{order.tracking_number || "—"}
                    </p>
                    {order.shipped_at && (
                      <p className="mt-1 text-xs text-slate-500">
                        发货时间：{new Date(order.shipped_at).toLocaleString("zh-CN")}
                      </p>
                    )}
                  </div>
                </div>
              ) : (
                <p className="text-sm text-slate-400">暂无物流信息</p>
              )}
            </Section>

            {/* 商品明细 */}
            <Section title="商品明细">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-slate-500">
                      <th className="pb-2 font-normal">商品</th>
                      <th className="pb-2 font-normal">规格</th>
                      <th className="pb-2 font-normal">单价</th>
                      <th className="pb-2 font-normal">数量</th>
                      <th className="pb-2 text-right font-normal">小计</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(order.items ?? []).map((item) => (
                      <tr
                        key={item.product_id}
                        className="border-t border-slate-100 text-slate-800"
                      >
                        <td className="py-2 pr-2">{item.title}</td>
                        <td className="py-2 pr-2 text-slate-500">
                          {item.spec_text || "—"}
                        </td>
                        <td className="py-2 pr-2">{money(item.price)}</td>
                        <td className="py-2 pr-2">{item.quantity}</td>
                        <td className="py-2 text-right font-medium">
                          {money(item.subtotal)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {(order.items ?? []).length === 0 && (
                <p className="text-sm text-slate-400">没有商品明细</p>
              )}
            </Section>

            {/* 状态时间线 */}
            <Section title="状态时间线">
              <StatusTimeline order={order} />
            </Section>

            {/* 申请售后 */}
            {canApplyAfterSale && (
              <Section title="申请售后">
                <AfterSaleForm order={order} user={user ?? ""} onCreated={load} />
              </Section>
            )}

            {/* 该订单的售后单 */}
            <Section title="售后单">
              {tickets.length === 0 ? (
                <p className="text-sm text-slate-400">该订单暂无售后单</p>
              ) : (
                <div className="flex flex-col gap-3">
                  {tickets.map((ticket) => (
                    <AfterSaleCard
                      key={ticket.ticket_no}
                      ticket={ticket}
                      onChanged={load}
                    />
                  ))}
                </div>
              )}
            </Section>

            {/* 评价 */}
            <Section title="评价">
              {pending ? (
                <ReviewForm order={order} user={user ?? ""} onSubmitted={load} />
              ) : (
                <p className="flex items-center gap-1.5 text-sm text-slate-400">
                  <Package size={15} />
                  该订单暂无待评价商品（已评价或不支持评价）
                </p>
              )}
            </Section>
          </div>
        )}
      </main>
    </div>
  );
}
